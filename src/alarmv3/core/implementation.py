"""Implementation mode — plan/build/eval pipeline for applying accepted recommendations.

Phase 4. The source repo remains read-only. All changes go to the TARGET directory only.

Three Claude calls per change (board decision — Cole Medin Adversarial Dev pattern):
1. Planner   — scopes exactly what must change in the affected files
2. Builder   — generates a unified diff implementing the plan
3. Impl eval — adversarial review of the diff (separate call, separate prompt)

Context discipline (Vasilev + Cole Medin): each call loads only the affected files
from TARGET. Never loads the full repo. Prior rejection feedback is injected on retry.

Phase 5 additions:
- Project memory injected into planner/builder prompts
- Autopilot auto-acceptance for low-risk changes (policy-gated)
- run_batch() for parallel execution of independent plan items
"""

import concurrent.futures
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import anthropic

from .session import Session

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_PLANNER_PROMPT = """\
You are a software modernization planner. Given a specific modernization recommendation
and the current content of the affected files, produce a precise implementation scope.

Your output must be a JSON object:
{
  "summary": "one sentence: what exactly will be changed",
  "steps": ["step 1", "step 2", ...],
  "files_to_modify": ["relative/path/to/file", ...],
  "risks": "brief note on any risks or edge cases to watch for"
}

Be specific. Reference exact function names, line ranges, or patterns. Do not suggest
changes to files not listed in the recommendation's affected_files.\
"""

_BUILDER_PROMPT = """\
You are a software modernization engineer. Given an implementation plan and the current
file contents, generate a unified diff that implements the change.

Rules:
- Output ONLY the unified diff (--- a/ +++ b/ @@ format). No explanation before or after.
- Include enough context lines (3) for the diff to apply cleanly.
- Do not change anything outside the scope defined in the plan.
- Do not rename or move files.
- If a file needs no changes, omit it from the diff entirely.\
"""

_IMPL_EVALUATOR_PROMPT = """\
You are an adversarial code change reviewer. Your job is to FIND PROBLEMS with a
proposed code change before it is committed.

Evaluate:
1. Does the diff correctly implement the stated recommendation? (be skeptical)
2. Does it introduce new bugs, security issues, or regressions?
3. Are there edge cases or callers not addressed?
4. Is the diff syntactically correct and applicable?

Return a JSON object:
{
  "verdict": "approve" | "flag" | "reject",
  "critique": "specific issues found, or 'No significant issues.' if clean",
  "risk_level": 1-5
}\
"""


class ImplementationPlanner:
    """Creates an ordered implementation plan from accepted recommendations."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    def create_plan(self, rec_ids: list[int]) -> dict:
        """Read accepted recommendations by rank, order by shared-file dependency, store plan."""
        recs = self._load_recommendations(rec_ids)
        ordered = _order_by_dependency(recs)

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        plan_ids = []
        try:
            for idx, rec in enumerate(ordered):
                cur = conn.execute(
                    "INSERT INTO implementation_plan"
                    "(session_id, rec_rank, title, affected_files, order_index, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        self._session.session_id,
                        rec["rank"],
                        rec["title"],
                        json.dumps(rec.get("affected_files", [])),
                        idx,
                        now,
                    ),
                )
                plan_ids.append(cur.lastrowid)
            conn.commit()
        finally:
            conn.close()

        return {
            "plan_item_count": len(ordered),
            "plan_ids": plan_ids,
            "order": [{"rank": r["rank"], "title": r["title"]} for r in ordered],
        }

    def get_plan(self) -> list[dict]:
        """Return all plan items for this session in order."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, rec_rank, title, affected_files, order_index, status "
                "FROM implementation_plan WHERE session_id=? ORDER BY order_index",
                (self._session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["affected_files"] = json.loads(d["affected_files"])
            result.append(d)
        return result

    def _load_recommendations(self, rec_ids: list[int]) -> list[dict]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" * len(rec_ids))
            rows = conn.execute(
                f"SELECT rank, title, description, affected_files, rationale "
                f"FROM recommendation WHERE session_id=? AND rank IN ({placeholders}) "
                f"AND review_status='accepted' ORDER BY rank",
                [self._session.session_id, *rec_ids],
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["affected_files"] = json.loads(d["affected_files"])
            result.append(d)
        return result


class ImplementationRunner:
    """Runs the plan/build/eval loop for one plan item at a time."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    @property
    def target_path(self) -> Path | None:
        meta = self._session.get_metadata()
        t = meta.get("target_path")
        return Path(t) if t else None

    def run_next(self) -> dict:
        """Execute plan/build/eval for the next pending plan item.

        Returns the diff and evaluator critique for human review.
        Does NOT write any files — that requires accept_change().
        """
        item = self._next_pending_item()
        if not item:
            return {"status": "no_pending_items", "message": "All plan items are complete."}

        target = self.target_path
        if not target or not target.exists():
            raise ValueError(f"Target directory not found: {target}")

        self._set_item_status(item["id"], "in_progress")

        prior_feedback = self._get_prior_feedback(item["id"])
        file_contents = _load_file_contents(item["affected_files"], target)

        rec = self._load_recommendation(item["rec_rank"])

        try:
            plan = self._call_planner(rec, file_contents, prior_feedback)
            diff = self._call_builder(rec, plan, file_contents)
            evaluation = self._call_evaluator(rec, diff, file_contents)
        except Exception as e:
            self._set_item_status(item["id"], "pending")
            raise RuntimeError(f"Implementation pipeline failed: {e}") from e

        change_id = self._store_change(item["id"], diff, evaluation)

        result = {
            "plan_item_id": item["id"],
            "change_id": change_id,
            "rec_rank": item["rec_rank"],
            "title": item["title"],
            "diff": diff,
            "eval_verdict": evaluation.get("verdict", "pending"),
            "eval_critique": evaluation.get("critique", ""),
            "eval_risk_level": evaluation.get("risk_level"),
            "auto_accepted": False,
        }

        # Phase 5: check autopilot policy — auto-commit if change meets threshold
        from .autopilot import AutopilotPolicy
        policy = AutopilotPolicy(self._session.alarm_dir)
        auto_ok, auto_reason = policy.should_auto_accept(
            rec.get("category", ""),
            evaluation.get("risk_level"),
            rec.get("effort"),
        )
        if auto_ok and evaluation.get("verdict") in ("approve", "flag"):
            accept_result = self.accept_change(change_id, _auto_reason=auto_reason)
            result.update({
                "auto_accepted": True,
                "auto_accept_reason": auto_reason,
                "commit_hash": accept_result.get("commit_hash"),
                "message": (
                    f"Auto-accepted (autopilot): {item['title']}. "
                    f"Rule: {auto_reason}. Commit: {accept_result.get('commit_hash', 'n/a')}."
                ),
            })
        else:
            result["message"] = (
                f"Change generated for: {item['title']}. "
                f"Evaluator verdict: {evaluation.get('verdict')}. "
                "Call accept_change or reject_change."
            )

        return result

    def accept_change(self, change_id: int, _auto_reason: "str | None" = None) -> dict:
        """Apply the accepted diff to TARGET files and git-commit the result."""
        change = self._load_change(change_id)
        if not change:
            raise ValueError(f"Change {change_id} not found")
        if change["review_status"] not in ("pending_review",):
            raise ValueError(f"Change {change_id} is not pending review (status: {change['review_status']})")

        target = self.target_path
        if not target:
            raise ValueError("No target directory set")

        diff_text = change["diff_text"] or ""
        commit_hash = None

        if diff_text.strip():
            _apply_diff(diff_text, target)
            commit_hash = _git_commit(
                target,
                message=f"ALARMv3: {self._load_plan_item_title(change['plan_item_id'])}",
            )

        review_status = "auto_accepted" if _auto_reason else "accepted"
        now = time.time()
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "UPDATE implementation_change SET review_status=?, "
                "commit_hash=?, reviewed_at=? WHERE id=?",
                (review_status, commit_hash, now, change_id),
            )
            conn.execute(
                "UPDATE implementation_plan SET status='complete' WHERE id=?",
                (change["plan_item_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        if _auto_reason:
            self._session.guardrails._audit(
                f"AUTOPILOT_ACCEPT change_id={change_id}",
                {"auto_reason": _auto_reason, "commit_hash": commit_hash},
            )

        return {
            "change_id": change_id,
            "commit_hash": commit_hash,
            "status": review_status,
            "message": f"Change applied and committed. Hash: {commit_hash or 'n/a (empty diff)'}",
        }

    def reject_change(self, change_id: int, feedback: str) -> dict:
        """Discard the diff and store feedback for retry."""
        change = self._load_change(change_id)
        if not change:
            raise ValueError(f"Change {change_id} not found")

        now = time.time()
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "UPDATE implementation_change SET review_status='rejected', "
                "feedback=?, reviewed_at=? WHERE id=?",
                (feedback, now, change_id),
            )
            conn.execute(
                "UPDATE implementation_plan SET status='pending' WHERE id=?",
                (change["plan_item_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "change_id": change_id,
            "status": "rejected",
            "message": "Change rejected. Call implement_next to retry with your feedback.",
        }

    def get_changes(self) -> list[dict]:
        """Return all changes for this session."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT ic.id, ic.plan_item_id, ip.title, ip.order_index, "
                "ic.eval_verdict, ic.eval_critique, ic.review_status, "
                "ic.commit_hash, ic.created_at "
                "FROM implementation_change ic "
                "JOIN implementation_plan ip ON ip.id = ic.plan_item_id "
                "WHERE ic.session_id=? ORDER BY ic.created_at DESC",
                (self._session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ── Internal helpers ───────────────────────────────────────────────────

    def _next_pending_item(self) -> dict | None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, rec_rank, title, affected_files FROM implementation_plan "
                "WHERE session_id=? AND status='pending' ORDER BY order_index LIMIT 1",
                (self._session.session_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        d = dict(row)
        d["affected_files"] = json.loads(d["affected_files"])
        return d

    def _set_item_status(self, item_id: int, status: str) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "UPDATE implementation_plan SET status=? WHERE id=?", (status, item_id)
            )
            conn.commit()
        finally:
            conn.close()

    def _get_prior_feedback(self, plan_item_id: int) -> str | None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            row = conn.execute(
                "SELECT feedback FROM implementation_change "
                "WHERE session_id=? AND plan_item_id=? AND review_status='rejected' "
                "ORDER BY created_at DESC LIMIT 1",
                (self._session.session_id, plan_item_id),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def _load_recommendation(self, rank: int) -> dict:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT rank, title, description, rationale, affected_files "
                "FROM recommendation WHERE session_id=? AND rank=?",
                (self._session.session_id, rank),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError(f"Recommendation rank {rank} not found")
        d = dict(row)
        d["affected_files"] = json.loads(d["affected_files"])
        return d

    def _load_change(self, change_id: int) -> dict | None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM implementation_change WHERE id=? AND session_id=?",
                (change_id, self._session.session_id),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def _load_plan_item_title(self, plan_item_id: int) -> str:
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            row = conn.execute(
                "SELECT title FROM implementation_plan WHERE id=?", (plan_item_id,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else f"plan-item-{plan_item_id}"

    def _store_change(self, plan_item_id: int, diff: str, evaluation: dict) -> int:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            cur = conn.execute(
                "INSERT INTO implementation_change"
                "(session_id, plan_item_id, diff_text, eval_critique, eval_verdict, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    self._session.session_id,
                    plan_item_id,
                    diff,
                    evaluation.get("critique", ""),
                    evaluation.get("verdict", "pending"),
                    time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # ── Parallel batch (Phase 5) ───────────────────────────────────────────

    def run_batch(self, max_concurrent: int = 3) -> list[dict]:
        """Run plan/build/eval for all pending items, parallelising independent ones.

        Items whose affected_files sets do not overlap are dispatched concurrently.
        Items that share files are serialised to avoid conflicting patches.
        Returns a list of results in completion order — callers review and call
        accept_change / reject_change on each.
        """
        pending = self._get_all_pending()
        if not pending:
            return [{"status": "no_pending_items", "message": "All plan items are complete."}]

        batches = _batch_independent(pending, max_concurrent)
        all_results: list[dict] = []
        for batch in batches:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = {executor.submit(self._run_item, item): item for item in batch}
                for future in concurrent.futures.as_completed(futures):
                    item = futures[future]
                    try:
                        all_results.append(future.result())
                    except Exception as exc:
                        all_results.append({
                            "plan_item_id": item["id"],
                            "title": item["title"],
                            "status": "error",
                            "error": str(exc),
                        })
        return all_results

    def _get_all_pending(self) -> list[dict]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, rec_rank, title, affected_files FROM implementation_plan "
                "WHERE session_id=? AND status='pending' ORDER BY order_index",
                (self._session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["affected_files"] = json.loads(d["affected_files"])
            result.append(d)
        return result

    def _run_item(self, item: dict) -> dict:
        """Run plan/build/eval for a single item dict (used by run_batch threads)."""
        self._set_item_status(item["id"], "in_progress")
        target = self.target_path
        if not target or not target.exists():
            raise ValueError(f"Target directory not found: {target}")
        prior_feedback = self._get_prior_feedback(item["id"])
        file_contents = _load_file_contents(item["affected_files"], target)
        rec = self._load_recommendation(item["rec_rank"])
        try:
            plan = self._call_planner(rec, file_contents, prior_feedback)
            diff = self._call_builder(rec, plan, file_contents)
            evaluation = self._call_evaluator(rec, diff, file_contents)
        except Exception as exc:
            self._set_item_status(item["id"], "pending")
            raise RuntimeError(f"Pipeline failed for item {item['id']}: {exc}") from exc

        change_id = self._store_change(item["id"], diff, evaluation)

        result = {
            "plan_item_id": item["id"],
            "change_id": change_id,
            "rec_rank": item["rec_rank"],
            "title": item["title"],
            "diff": diff,
            "eval_verdict": evaluation.get("verdict", "pending"),
            "eval_critique": evaluation.get("critique", ""),
            "eval_risk_level": evaluation.get("risk_level"),
            "auto_accepted": False,
        }

        from .autopilot import AutopilotPolicy
        policy = AutopilotPolicy(self._session.alarm_dir)
        auto_ok, auto_reason = policy.should_auto_accept(
            rec.get("category", ""),
            evaluation.get("risk_level"),
            rec.get("effort"),
        )
        if auto_ok and evaluation.get("verdict") in ("approve", "flag"):
            accept_result = self.accept_change(change_id, _auto_reason=auto_reason)
            result.update({
                "auto_accepted": True,
                "auto_accept_reason": auto_reason,
                "commit_hash": accept_result.get("commit_hash"),
                "message": (
                    f"Auto-accepted (autopilot): {item['title']}. "
                    f"Rule: {auto_reason}. Commit: {accept_result.get('commit_hash', 'n/a')}."
                ),
            })
        else:
            result["message"] = (
                f"Change generated for: {item['title']}. "
                f"Evaluator verdict: {evaluation.get('verdict')}. "
                "Call accept_change or reject_change."
            )
        return result

    # ── LLM calls ─────────────────────────────────────────────────────────

    def _call_planner(self, rec: dict, files: dict[str, str], feedback: str | None) -> dict:
        client = anthropic.Anthropic()
        content = _format_rec(rec) + _format_files(files)
        if feedback:
            content += f"\n\n## Prior attempt feedback\n\n{feedback}"

        from .memory import ProjectMemory
        memory_text = ProjectMemory(self._session.alarm_dir).format_for_prompt()
        system_text = _PLANNER_PROMPT
        if memory_text:
            system_text = system_text + "\n\n" + memory_text

        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return _parse_json_response(msg.content[0].text, default={})

    def _call_builder(self, rec: dict, plan: dict, files: dict[str, str]) -> str:
        client = anthropic.Anthropic()
        content = (
            _format_rec(rec)
            + f"\n\n## Implementation plan\n\n{json.dumps(plan, indent=2)}"
            + _format_files(files)
        )
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[{"type": "text", "text": _BUILDER_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return msg.content[0].text.strip()

    def _call_evaluator(self, rec: dict, diff: str, files: dict[str, str]) -> dict:
        client = anthropic.Anthropic()
        content = (
            _format_rec(rec)
            + f"\n\n## Proposed diff\n\n```diff\n{diff}\n```"
            + _format_files(files)
        )
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": _IMPL_EVALUATOR_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return _parse_json_response(msg.content[0].text, default={"verdict": "flag", "critique": "Parse error"})


# ── Module-level helpers ───────────────────────────────────────────────────────

def clone_source_to_target(source_path: Path, target_path: Path) -> None:
    """Copy source repo to target directory. Target must not already exist."""
    if target_path.exists():
        raise ValueError(f"Target path already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_path, target_path, symlinks=False)
    _git_init_if_needed(target_path)


def _git_init_if_needed(path: Path) -> None:
    """Ensure target has a git repo so we can commit changes."""
    if not (path / ".git").exists():
        subprocess.run(["git", "init"], cwd=path, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "alarmv3@localhost"],
            cwd=path, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "ALARMv3"],
            cwd=path, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "add", "-A"], cwd=path, capture_output=True, check=False
        )
        subprocess.run(
            ["git", "commit", "-m", "ALARMv3: initial snapshot from source"],
            cwd=path, capture_output=True, check=False,
        )


def _batch_independent(items: list[dict], max_concurrent: int) -> list[list[dict]]:
    """Partition plan items into batches where no two items in the same batch share files.

    Items with shared affected_files are serialised into separate batches so their
    diffs do not conflict. Within each batch, all items can run in parallel.
    """
    batches: list[list[dict]] = []
    remaining = list(items)
    while remaining:
        batch: list[dict] = []
        used_files: set[str] = set()
        deferred: list[dict] = []
        for item in remaining:
            item_files = set(item.get("affected_files", []))
            if not (item_files & used_files) and len(batch) < max_concurrent:
                batch.append(item)
                used_files |= item_files
            else:
                deferred.append(item)
        batches.append(batch)
        remaining = deferred
    return batches


def _order_by_dependency(recs: list[dict]) -> list[dict]:
    """Order recommendations so shared-file changes come first.

    Recs that touch more files (higher coupling) are tackled earlier to
    avoid later changes stepping on earlier ones.
    """
    return sorted(recs, key=lambda r: (-len(r.get("affected_files", [])), r["rank"]))


def _load_file_contents(affected_files: list[str], target: Path) -> dict[str, str]:
    """Load content of affected files from TARGET directory."""
    contents: dict[str, str] = {}
    for rel_path in affected_files:
        candidate = target / rel_path
        if candidate.exists() and candidate.is_file():
            try:
                contents[rel_path] = candidate.read_text(errors="replace")
            except OSError:
                contents[rel_path] = ""
    return contents


def _apply_diff(diff_text: str, target: Path) -> None:
    """Apply a unified diff produced by an LLM to the target directory.

    LLM diffs routinely have three issues that defeat standard patch/git-apply:
    1. Wrapped in ```diff ... ``` fences
    2. File paths carry a leading source-repo prefix (e.g. a/workspaces/ADDS/...)
       rather than being relative to the target root
    3. Hunk @@ line counts that are off by a few lines

    Strategy: reconstruct each file's new content from the diff's context (+)
    and unchanged ( ) lines, stripping removed (-) lines. This is immune to
    hunk-count errors and path-prefix confusion.
    """
    import re as _re

    # Strip markdown fences and normalise line endings
    text = diff_text.replace("\r\n", "\n")
    text = _re.sub(r"^```[a-z]*\n?", "", text, flags=_re.MULTILINE)
    text = text.replace("```", "").strip()

    lines = text.splitlines()

    # Parse into per-file hunks
    # Collect (target_rel_path, list_of_hunk_lines) pairs
    files: list[tuple[str, list[str]]] = []
    cur_path: str | None = None
    cur_lines: list[str] = []

    def _extract_path(header: str) -> str:
        """Strip a/b prefix and any leading absolute path components."""
        p = header.strip()
        # Git quotes paths that contain spaces or unicode (e.g.
        # "a/Original files/Foo.Cmd"). Strip the surrounding quotes before
        # any other processing or every later check fails.
        if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
            p = p[1:-1]
        # Remove leading a/ or b/
        p = _re.sub(r"^[ab]/", "", p)
        # If path still looks absolute or contains the source root, strip
        # everything up to the first path component that exists in target
        parts = Path(p).parts
        for i in range(len(parts)):
            candidate = Path(*parts[i:])
            if (target / candidate).exists():
                return str(candidate)
        return p  # best effort

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            # Save previous file
            if cur_path is not None:
                files.append((cur_path, cur_lines))
            cur_lines = []
            cur_path = None
            # Next line should be +++
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                raw = lines[i + 1][4:].split("\t")[0]  # strip timestamp
                cur_path = _extract_path(raw)
                i += 2
                continue
        elif line.startswith("@@ "):
            pass  # hunk header — just skip, we don't need line counts
        elif cur_path is not None and not line.startswith("--- "):
            cur_lines.append(line)
        i += 1

    if cur_path is not None:
        files.append((cur_path, cur_lines))

    if not files:
        return  # nothing to apply

    for rel_path, hunk_lines in files:
        dest = target / rel_path
        if not dest.exists():
            continue  # skip files not present in target

        # Rebuild new file content from context + added lines
        new_content_lines = []
        for ln in hunk_lines:
            if ln.startswith("+"):
                new_content_lines.append(ln[1:])
            elif ln.startswith("-"):
                pass  # removed line
            elif ln.startswith("@@ "):
                pass  # hunk header inside lines list
            else:
                # Context line (starts with space or is bare)
                new_content_lines.append(ln[1:] if ln.startswith(" ") else ln)

        if new_content_lines:
            dest.write_text("\n".join(new_content_lines) + "\n", encoding="utf-8")


def _git_commit(target: Path, message: str) -> str | None:
    """Stage all changes and commit in the target directory. Returns commit hash."""
    subprocess.run(["git", "add", "-A"], cwd=target, capture_output=True, check=False)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=target, capture_output=True,
    )
    if result.returncode != 0:
        return None
    log = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        cwd=target, capture_output=True,
    )
    return log.stdout.decode().strip() or None


def _format_rec(rec: dict) -> str:
    return (
        f"## Recommendation (rank {rec['rank']})\n\n"
        f"**Title**: {rec['title']}\n"
        f"**Description**: {rec['description']}\n"
        f"**Rationale**: {rec.get('rationale', '')}\n"
        f"**Affected files**: {', '.join(rec.get('affected_files', []))}"
    )


def _format_files(files: dict[str, str]) -> str:
    if not files:
        return "\n\n## Affected files\n\n(No files found in target directory)"
    parts = ["\n\n## Current file contents"]
    for path, content in files.items():
        parts.append(f"\n### {path}\n\n```\n{content[:8000]}\n```")
    return "\n".join(parts)


def _parse_json_response(text: str, default: dict) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return default
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return default
