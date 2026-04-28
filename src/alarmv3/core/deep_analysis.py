"""Deep analysis engine — exhaustive multi-pass LLM synthesis over the full semantic graph.

Board decision (Phase 6). Replaces the single-pass statistical digest in synthesis.py
with a three-phase pipeline that achieves full codebase coverage:

  Phase A — SubsystemPartitioner
      Union-find clustering on dependency_edge graph → coherent architectural subsystems.
      Every file lands in exactly one subsystem.

  Phase B — Per-subsystem synthesis passes
      One Claude call per cluster. Each call receives all symbols, all internal dependency
      edges, and all complexity metrics for that subsystem. Bounded by max_symbols_per_pass
      to stay within context limits.

  Phase C — Complexity-tier deep pass
      Files whose cyclomatic complexity OR fan-in/fan-out exceeds threshold get a dedicated
      focused pass regardless of subsystem membership.

  Phase D — Aggregation pass
      All subsystem findings + complexity findings fed to a final Claude call that
      deduplicates, merges related items, and produces the ranked recommendation list.
      Result is stored in the existing recommendation table — all downstream tools unchanged.

Coverage is tracked in analysis_coverage so nothing is silently skipped.
The final recommendations run through the existing adversarial evaluator.
"""

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

import anthropic

from .session import Session

_GUID_RE = re.compile(r'^\{[0-9A-Fa-f-]{36}\}$')
# Modules so common across the codebase that they tell us nothing about
# clustering — every file imports them.
_FRAMEWORK_MODULE_PREFIXES = ("System.", "System$", "Microsoft.", "mscorlib")

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS_SUBSYSTEM = 6144
_MAX_TOKENS_COMPLEXITY = 4096
_MAX_TOKENS_AGGREGATION = 8192
_MAX_SYMBOLS_PER_PASS = 150   # cap per subsystem to stay within context
_MAX_EDGES_PER_PASS = 200
# Source-excerpt budget for the per-subsystem prompt. Without source, the
# LLM only sees symbol *names* and dependency edges, which on inferred
# languages (AutoLISP, AutoCAD-binaries-as-text) is opaque enough that the
# subsystem pass returns []. Including ~6 representative files at ~150 lines
# each gives the model real architecture to reason about.
_MAX_REPRESENTATIVE_FILES = 8
_MAX_LINES_PER_EXCERPT = 200
_MAX_EXCERPT_CHARS = 10000    # per-file safety cap
_MAX_TOTAL_EXCERPT_CHARS = 60000  # total cap across all reps in one prompt


# ── Prompts ────────────────────────────────────────────────────────────────────

_SUBSYSTEM_PROMPT = """\
You are a senior software architect analyzing one subsystem of a legacy
codebase that is the explicit target of a modernization initiative. Treat the
codebase as old enough that *something* will be visible — outdated language
constructs, deprecated APIs, hardcoded paths, missing error handling, copy-paste
patterns, dead code, security anti-patterns. The user already knows it needs
modernization; your job is to enumerate concrete findings, not to validate
whether modernization is warranted.

You receive the dependency graph, symbol table, complexity metrics, AND raw
source excerpts from the most representative files in this cluster. The
source excerpts are the primary reasoning input — read them line by line.

Focus on, in roughly this priority:
1. Security issues in the source — hardcoded credentials/paths/PII, injection
   risk, overly broad permissions, plaintext secrets, missing input validation
2. Modernization opportunities — outdated APIs, deprecated frameworks/runtimes,
   language version uplift, sync→async migration, removed third-party deps
3. Quality debt — missing error handling, copy-paste duplication, dead code,
   god objects, missing interfaces, fragile coupling
4. Architectural violations — circular dependencies, layer leaks, cross-cutting
   concerns, missing abstractions across files
5. Natural seams for extraction or shared utilities

Be specific. Cite file paths. When you cite a pattern, name the symbol or
keyword you saw. Avoid vague findings like "consider refactoring" — every
finding must point at a concrete defect with a concrete fix shape.

For inferred languages (AutoLISP, DCL, .pat, .atc, .xtp, etc.) the same rules
apply: hardcoded UNC paths, embedded usernames, OS-specific command literals,
duplicate scripts that differ only in parameters, etc. — these all count.

Return ONLY a valid JSON array of findings:
[{
  "category": "security|modernization|quality|dependency",
  "severity": "critical|high|medium|low",
  "title": "short title under 80 chars",
  "description": "2-4 sentences: what is wrong, why it matters, what the fix looks like",
  "affected_files": ["relative/path"],
  "effort": "S|M|L|XL",
  "rationale": "one sentence on why this matters now"
}]

Up to 10 findings. If you genuinely cannot see a single concrete defect after
reading the excerpts (extremely rare for a 35-year-old codebase), return [].
No text outside the JSON array.\
"""

_COMPLEXITY_TIER_PROMPT = """\
You are a software architect doing a focused deep review of the highest-complexity files
in a legacy codebase.

These files have been flagged for elevated cyclomatic complexity or extreme fan-in/fan-out.
High complexity + high coupling = highest blast radius during modernization.

For each file, identify:
1. Decomposition opportunities — what single responsibility violations exist
2. Hidden coupling — what this file knows about that it shouldn't
3. Testability problems caused by the complexity
4. Refactoring risk — who depends on this, what breaks if it changes

Return ONLY a valid JSON array (same schema as above). Up to 15 findings. No text outside the array.\
"""

_AGGREGATION_PROMPT = """\
You are a senior software architect consolidating findings from multiple analysis passes
of a legacy codebase into a final prioritized modernization plan.

You receive a JSON object with findings from N subsystem passes and a complexity-tier pass.
Produce a single deduplicated, ranked recommendation list.

Rules:
- Merge duplicate findings (same file + same issue type → one item)
- Promote findings that appear across multiple subsystems — cross-cutting issues rank higher
- Rank by: severity (critical first), then cross-subsystem impact, then effort (S before XL)
- Maximum 20 final recommendations
- Add a "rank" integer field (1 = highest priority)
- Preserve all original fields; if merging, union the affected_files lists

Return ONLY a valid JSON array ordered by rank (1 first). No text outside the array.\
"""


# ── Partitioner ────────────────────────────────────────────────────────────────

class SubsystemPartitioner:
    """Clusters files into subsystems using union-find on the dependency_edge graph."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    def partition(self, min_cluster_size: int = 2, max_subsystems: int = 15) -> list[dict]:
        """Return a list of subsystem dicts covering every eligible file.

        Clusters are ordered by (file_count × avg_complexity) descending so the most
        architecturally significant subsystems are processed first.

        If the number of natural clusters exceeds max_subsystems, the smallest clusters
        are merged into a final "remaining" bucket so every file is still covered.
        """
        files, edges = self._load_graph()
        if not files:
            return []

        components = _union_find(files, edges)
        clusters = sorted(components.values(), key=lambda c: -len(c))

        # Separate large clusters from singletons
        significant = [c for c in clusters if len(c) >= min_cluster_size]
        singletons = [f for c in clusters if len(c) < min_cluster_size for f in c]

        # Enforce max_subsystems: merge excess clusters into a "remaining" bucket
        if len(significant) > max_subsystems - 1:
            overflow = [f for c in significant[max_subsystems - 1:] for f in c]
            significant = significant[:max_subsystems - 1]
            singletons = singletons + overflow

        subsystems = []
        for idx, cluster in enumerate(significant):
            stats = self._compute_stats(cluster)
            subsystems.append({
                "index": idx,
                "name": _derive_name(cluster, idx),
                "files": cluster,
                **stats,
            })

        if singletons:
            stats = self._compute_stats(singletons)
            subsystems.append({
                "index": len(subsystems),
                "name": "remaining",
                "files": singletons,
                **stats,
            })

        # Order by importance: file_count × avg_complexity
        subsystems.sort(key=lambda s: -(s["file_count"] * max(s["avg_complexity"], 1.0)))
        return subsystems

    def get_complexity_outliers(self, cyclomatic_threshold: int = 10, coupling_threshold: int = 10) -> list[str]:
        """Return files whose cyclomatic complexity or fan-in+fan-out exceeds the threshold."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        try:
            high_cyclo = {
                r["file_path"]
                for r in conn.execute(
                    "SELECT file_path FROM complexity_metric "
                    "WHERE session_id=? AND metric_name='cyclomatic' AND metric_value>=?",
                    (sid, cyclomatic_threshold),
                ).fetchall()
            }
            high_coupling = {
                r["file_path"]
                for r in conn.execute(
                    "SELECT file_path FROM complexity_metric "
                    "WHERE session_id=? AND metric_name IN ('coupling_in','coupling_out') "
                    "GROUP BY file_path HAVING SUM(metric_value)>=?",
                    (sid, coupling_threshold),
                ).fetchall()
            }
        finally:
            conn.close()
        return sorted(high_cyclo | high_coupling)

    # ── Internals ──────────────────────────────────────────────────────────

    def _load_graph(self) -> tuple[list[str], list[tuple[str, str]]]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        try:
            files = [
                r["relative_path"]
                for r in conn.execute(
                    "SELECT relative_path FROM manifest WHERE session_id=? AND is_eligible=1",
                    (sid,),
                ).fetchall()
            ]
            # Path normaliser: extractors are inconsistent — tree-sitter
            # writes absolute paths into dependency_edge.source_file while the
            # language researcher writes manifest-relative paths. Strip the
            # source-root prefix so every edge endpoint matches the manifest.
            source_root = str(self._session.source_path).rstrip("/") + "/"

            def _norm(p: Optional[str]) -> Optional[str]:
                if not p:
                    return None
                return p[len(source_root):] if p.startswith(source_root) else p

            # 1) Resolved file-to-file edges. Most extractors only know
            #    target_module today, so this set is usually small.
            resolved_edges: list[tuple[str, str]] = []
            for r in conn.execute(
                "SELECT source_file, target_file FROM dependency_edge "
                "WHERE session_id=? AND target_file IS NOT NULL AND target_file != ''",
                (sid,),
            ).fetchall():
                s, t = _norm(r["source_file"]), _norm(r["target_file"])
                if s and t:
                    resolved_edges.append((s, t))

            # 2) Shared-module fallback. Files that import the same internal
            #    module are coupled. Filter out framework modules (everyone
            #    imports them) and SLN-section GUIDs.
            module_index: dict[str, set[str]] = {}
            for r in conn.execute(
                "SELECT source_file, target_module FROM dependency_edge "
                "WHERE session_id=? AND target_module IS NOT NULL AND target_module != ''",
                (sid,),
            ).fetchall():
                mod = (r["target_module"] or "").strip()
                if not mod or _is_noise_module(mod):
                    continue
                src = _norm(r["source_file"])
                if not src:
                    continue
                module_index.setdefault(mod, set()).add(src)
        finally:
            conn.close()

        # Cap the cluster signal: skip modules touched by more than half the
        # codebase (System-level), keep modules with 2+ source files.
        ubiquity = max(2, len(files) // 2)
        module_edges: list[tuple[str, str]] = []
        for mod, srcs in module_index.items():
            srcs_in_files = sorted(srcs.intersection(files))
            if 2 <= len(srcs_in_files) <= ubiquity:
                anchor = srcs_in_files[0]
                module_edges.extend((anchor, s) for s in srcs_in_files[1:])

        # 3) Path-prefix coupling. Files in the same 3-level directory are
        #    almost always part of the same subsystem. This is the most
        #    reliable architectural signal we have when symbol resolution is
        #    incomplete (which it always is for legacy AutoLISP / VBS / etc).
        path_edges = _path_prefix_edges(files, depth=3)

        return files, resolved_edges + module_edges + path_edges

    def _compute_stats(self, files: list[str]) -> dict:
        if not files:
            return {"file_count": 0, "total_loc": 0, "avg_complexity": 0.0}
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        placeholders = ",".join("?" * len(files))
        try:
            loc_row = conn.execute(
                f"SELECT SUM(metric_value) FROM complexity_metric "
                f"WHERE session_id=? AND metric_name='loc' AND file_path IN ({placeholders})",
                [sid, *files],
            ).fetchone()
            cyc_row = conn.execute(
                f"SELECT AVG(metric_value) FROM complexity_metric "
                f"WHERE session_id=? AND metric_name='cyclomatic' AND file_path IN ({placeholders})",
                [sid, *files],
            ).fetchone()
        finally:
            conn.close()
        return {
            "file_count": len(files),
            "total_loc": int(loc_row[0] or 0),
            "avg_complexity": round(float(cyc_row[0] or 0), 2),
        }


# ── Synthesizer ────────────────────────────────────────────────────────────────

class DeepSynthesizer:
    """Runs the four-phase deep synthesis pipeline and stores results."""

    def __init__(self, session: Session, progress_cb: Optional[Callable[[int, str], None]] = None):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        self._progress = progress_cb or (lambda pct, msg: None)

    def run(
        self,
        max_subsystems: int = 15,
        cyclomatic_threshold: int = 10,
        coupling_threshold: int = 10,
        aaa_grounding: Optional[str] = None,
    ) -> dict:
        """Execute full deep analysis pipeline. Returns result dict (same shape as Synthesizer.run)."""
        partitioner = SubsystemPartitioner(self._session)

        # Phase A — partition
        self._progress(5, "Partitioning dependency graph into subsystems…")
        subsystems = partitioner.partition(max_subsystems=max_subsystems)
        outlier_files = partitioner.get_complexity_outliers(cyclomatic_threshold, coupling_threshold)

        self._store_subsystems(subsystems)
        total_files_covered = sum(s["file_count"] for s in subsystems)

        # Phase B — per-subsystem passes
        all_findings: list[dict] = []
        for idx, subsystem in enumerate(subsystems):
            pct = 10 + int((idx / max(len(subsystems), 1)) * 55)
            self._progress(pct, f"Analyzing subsystem {idx + 1}/{len(subsystems)}: {subsystem['name']}…")
            context = _build_subsystem_context(
                self._session.session_id, subsystem, self._db_path,
                source_root=self._session.source_path,
            )
            findings = self._call_subsystem(context, subsystem["name"])
            self._store_finding(subsystem["index"], "subsystem", findings)
            self._mark_coverage(subsystem["files"], "subsystem")
            all_findings.extend(findings)

        # Phase C — complexity-tier deep pass
        self._progress(70, f"Complexity-tier pass: {len(outlier_files)} outlier files…")
        if outlier_files:
            complexity_context = _build_complexity_context(
                self._session.session_id, outlier_files, self._db_path
            )
            complexity_findings = self._call_complexity_tier(complexity_context)
            self._store_finding(None, "complexity_tier", complexity_findings)
            self._mark_coverage(outlier_files, "complexity_tier")
            all_findings.extend(complexity_findings)

        # Phase D — aggregation
        self._progress(80, "Aggregating and deduplicating findings…")
        if aaa_grounding:
            all_findings_with_grounding = {"findings": all_findings, "aaa_grounding": aaa_grounding}
        else:
            all_findings_with_grounding = {"findings": all_findings}

        from .memory import ProjectMemory
        memory_text = ProjectMemory(self._session.alarm_dir).format_for_prompt()

        recommendations = self._call_aggregation(all_findings_with_grounding, memory_text)
        self._store_recommendations(recommendations)

        # Adversarial evaluation (reuse existing evaluator)
        self._progress(90, "Running adversarial evaluator on aggregated recommendations…")
        from .evaluation import RecommendationEvaluator
        from .synthesis import Synthesizer
        evaluator = RecommendationEvaluator(self._session)
        repo_context = Synthesizer(self._session)._build_context()
        evaluations = evaluator.evaluate(recommendations, repo_context)
        evaluator.store_evaluations(evaluations)

        self._progress(100, "Deep analysis complete.")

        from .orchestration import _tally_verdicts
        verdict_summary = _tally_verdicts(evaluations)

        coverage_pct = self._coverage_percentage()
        return {
            "session_id": self._session.session_id,
            "recommendation_count": len(recommendations),
            "recommendations": recommendations,
            "top_recommendations": recommendations[:5],
            "subsystem_count": len(subsystems),
            "files_covered": total_files_covered,
            "coverage_pct": coverage_pct,
            "outlier_files_analyzed": len(outlier_files),
            "raw_findings_count": len(all_findings),
            "evaluator_summary": verdict_summary,
            "message": (
                f"Deep analysis complete: {len(subsystems)} subsystems, "
                f"{total_files_covered} files covered ({coverage_pct:.0f}%), "
                f"{len(recommendations)} recommendations. "
                f"Evaluator: {verdict_summary['accept']} accept, "
                f"{verdict_summary['revise']} revise, "
                f"{verdict_summary['reject']} reject. "
                "Review at recommendations://evaluated then call review_recommendations."
            ),
        }

    # ── LLM calls ─────────────────────────────────────────────────────────

    def _call_subsystem(self, context: dict, name: str) -> list[dict]:
        client = anthropic.Anthropic()
        content = _format_subsystem_message(name, context)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS_SUBSYSTEM,
            system=[{"type": "text", "text": _SUBSYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return _parse_findings(msg.content[0].text)

    def _call_complexity_tier(self, context: dict) -> list[dict]:
        client = anthropic.Anthropic()
        content = f"## Complexity outliers\n\n{json.dumps(context, indent=2)}"
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS_COMPLEXITY,
            system=[{"type": "text", "text": _COMPLEXITY_TIER_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return _parse_findings(msg.content[0].text)

    def _call_aggregation(self, findings_payload: dict, memory_text: str) -> list[dict]:
        client = anthropic.Anthropic()
        system_text = _AGGREGATION_PROMPT
        if memory_text:
            system_text = system_text + "\n\n" + memory_text
        content = f"## All findings ({len(findings_payload.get('findings', []))} items)\n\n{json.dumps(findings_payload, indent=2)}"
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS_AGGREGATION,
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return _parse_findings(msg.content[0].text)

    # ── Storage helpers ────────────────────────────────────────────────────

    def _store_subsystems(self, subsystems: list[dict]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        sid = self._session.session_id
        try:
            for s in subsystems:
                conn.execute(
                    "INSERT OR REPLACE INTO subsystem"
                    "(session_id, subsystem_index, name, file_count, total_loc, avg_complexity, files, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (sid, s["index"], s["name"], s["file_count"],
                     s["total_loc"], s["avg_complexity"],
                     json.dumps(s["files"]), now),
                )
            conn.commit()
        finally:
            conn.close()

    def _store_finding(self, subsystem_index: Optional[int], pass_type: str, findings: list[dict]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "INSERT INTO subsystem_finding"
                "(session_id, subsystem_index, pass_type, findings_json, created_at) "
                "VALUES (?,?,?,?,?)",
                (self._session.session_id, subsystem_index, pass_type,
                 json.dumps(findings), time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def _mark_coverage(self, files: list[str], pass_type: str) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        sid = self._session.session_id
        try:
            for f in files:
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_coverage(session_id, file_path, pass_type, covered_at) "
                    "VALUES (?,?,?,?)",
                    (sid, f, pass_type, now),
                )
            conn.commit()
        finally:
            conn.close()

    def _store_recommendations(self, recommendations: list[dict]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        sid = self._session.session_id
        try:
            # Clear any prior recs from this session before storing deep analysis results
            conn.execute("DELETE FROM recommendation WHERE session_id=?", (sid,))
            for rec in recommendations:
                conn.execute(
                    "INSERT INTO recommendation"
                    "(session_id, rank, category, severity, title, "
                    " description, affected_files, effort, rationale, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        rec.get("rank", 99),
                        rec.get("category", "modernization"),
                        rec.get("severity", "medium"),
                        rec.get("title", ""),
                        rec.get("description", ""),
                        json.dumps(rec.get("affected_files", [])),
                        rec.get("effort", "M"),
                        rec.get("rationale", ""),
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _coverage_percentage(self) -> float:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM manifest WHERE session_id=? AND is_eligible=1", (sid,)
            ).fetchone()[0]
            covered = conn.execute(
                "SELECT COUNT(DISTINCT file_path) FROM analysis_coverage WHERE session_id=?", (sid,)
            ).fetchone()[0]
        finally:
            conn.close()
        return (covered / total * 100) if total > 0 else 0.0


# ── Module-level helpers ───────────────────────────────────────────────────────

def _is_noise_module(mod: str) -> bool:
    """True if this target_module is too generic to use as a clustering signal."""
    if _GUID_RE.match(mod):
        return True
    return any(mod.startswith(prefix) for prefix in _FRAMEWORK_MODULE_PREFIXES) or mod == "System"


def _path_prefix_edges(files: list[str], depth: int = 3) -> list[tuple[str, str]]:
    """Group files by their first `depth` path segments and connect within each group.

    This is the always-on fallback that gives the partitioner a meaningful
    graph even when no resolved file-to-file edges exist. Without it, every
    file ends up as its own component and union-find produces one giant
    "remaining" bucket. Star topology (every file → group anchor) is enough
    for union-find to merge them into one component.
    """
    groups: dict[str, list[str]] = {}
    for f in files:
        parts = f.split("/")
        if len(parts) >= depth:
            key = "/".join(parts[:depth])
        elif len(parts) >= 2:
            key = "/".join(parts[:-1])
        else:
            key = "(root)"
        groups.setdefault(key, []).append(f)

    edges: list[tuple[str, str]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        anchor = group[0]
        for f in group[1:]:
            edges.append((anchor, f))
    return edges


def _union_find(files: list[str], edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Return connected components as {root: [file, ...]} via union-find with path compression."""
    parent = {f: f for f in files}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for src, tgt in edges:
        if src in parent and tgt in parent:
            union(src, tgt)

    components: dict[str, list[str]] = {}
    for f in files:
        root = find(f)
        components.setdefault(root, []).append(f)
    return components


def _derive_name(files: list[str], idx: int) -> str:
    """Derive a human-readable name from the deepest common directory.

    Walks down each path level by level and picks the deepest segment that
    most files share. This produces names like "19.0/Adds" or
    "Div_Map Archive/LookUpTable" instead of the always-shared top-level
    folder when every file lives under one root.
    """
    if not files:
        return f"subsystem_{idx:03d}"

    # Walk from depth 1 outward. At each depth, find the most common prefix.
    # Stop when no single prefix covers a clear majority of the cluster.
    parts_by_file = [f.split("/") for f in files]
    max_depth = min(len(p) for p in parts_by_file)
    best_name: Optional[str] = None
    for depth in range(1, max_depth + 1):
        counts: dict[str, int] = {}
        for parts in parts_by_file:
            key = "/".join(parts[:depth])
            counts[key] = counts.get(key, 0) + 1
        dominant = max(counts, key=lambda k: counts[k])
        share = counts[dominant] / len(files)
        if share < 0.5:
            break
        best_name = dominant
    return f"{best_name}_cluster" if best_name else f"subsystem_{idx:03d}"


def _build_subsystem_context(
    session_id: str,
    subsystem: dict,
    db_path: Path,
    source_root: Optional[Path] = None,
) -> dict:
    """Build a rich context dict for one subsystem — all metrics, bounded symbols, source excerpts."""
    files = subsystem["files"]
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(files))
    try:
        symbols = [
            {"name": r["name"], "type": r["symbol_type"], "file": r["file_path"],
             "start_line": r["start_line"], "is_public": bool(r["is_public"])}
            for r in conn.execute(
                f"SELECT name, symbol_type, file_path, start_line, is_public FROM symbol "
                f"WHERE session_id=? AND file_path IN ({placeholders}) "
                f"ORDER BY is_public DESC LIMIT {_MAX_SYMBOLS_PER_PASS}",
                [session_id, *files],
            ).fetchall()
        ]
        internal_edges = [
            {"from": r["source_file"], "to": r["target_file"], "type": r["dep_type"]}
            for r in conn.execute(
                f"SELECT source_file, target_file, dep_type FROM dependency_edge "
                f"WHERE session_id=? AND source_file IN ({placeholders}) "
                f"AND target_file IN ({placeholders}) LIMIT {_MAX_EDGES_PER_PASS}",
                [session_id, *files, *files],
            ).fetchall()
        ]
        cross_edges = [
            {"from": r["source_file"], "to": r["target_module"] or r["target_file"], "type": r["dep_type"]}
            for r in conn.execute(
                f"SELECT source_file, target_file, target_module, dep_type FROM dependency_edge "
                f"WHERE session_id=? AND source_file IN ({placeholders}) "
                f"AND (target_file NOT IN ({placeholders}) OR target_file IS NULL) "
                f"LIMIT 100",
                [session_id, *files, *files],
            ).fetchall()
        ]
        metrics = {}
        for r in conn.execute(
            f"SELECT file_path, metric_name, metric_value FROM complexity_metric "
            f"WHERE session_id=? AND file_path IN ({placeholders})",
            [session_id, *files],
        ).fetchall():
            metrics.setdefault(r["file_path"], {})[r["metric_name"]] = r["metric_value"]
        symbol_counts = {
            r["file_path"]: r["n"]
            for r in conn.execute(
                f"SELECT file_path, COUNT(*) AS n FROM symbol "
                f"WHERE session_id=? AND file_path IN ({placeholders}) "
                f"GROUP BY file_path",
                [session_id, *files],
            ).fetchall()
        }
    finally:
        conn.close()

    representatives = _select_representative_files(files, metrics, symbol_counts)
    source_excerpts = _read_source_excerpts(representatives, source_root) if source_root else []

    return {
        "file_count": len(files),
        "files_with_metrics": [
            {"file": f, "metrics": metrics.get(f, {})} for f in files
        ],
        "symbols": symbols,
        "internal_dependency_edges": internal_edges,
        "cross_boundary_edges": cross_edges,
        "source_excerpts": source_excerpts,
    }


def _select_representative_files(
    files: list[str],
    metrics: dict[str, dict],
    symbol_counts: dict[str, int],
) -> list[str]:
    """Pick up to _MAX_REPRESENTATIVE_FILES files most likely to expose architecture.

    Score = cyclomatic*10 + symbols*2 + loc*0.01. Falls back to symbol count
    alone for inferred-language files where complexity metrics are absent.
    """
    scores: list[tuple[float, str]] = []
    for f in files:
        m = metrics.get(f, {}) or {}
        cyc = float(m.get("cyclomatic", 0) or 0)
        loc = float(m.get("loc", 0) or 0)
        syms = float(symbol_counts.get(f, 0))
        score = cyc * 10.0 + syms * 2.0 + loc * 0.01
        scores.append((score, f))
    scores.sort(key=lambda t: -t[0])
    return [f for _, f in scores[:_MAX_REPRESENTATIVE_FILES]]


def _format_subsystem_message(name: str, context: dict) -> str:
    """Format the subsystem message so source excerpts appear as raw code blocks.

    JSON-encoding source code escapes newlines and quotes, which forces the
    model to mentally re-parse the text. Putting code in fenced blocks keeps
    it readable and dramatically improves the quality of findings.
    """
    excerpts = context.get("source_excerpts", []) or []
    metadata = {k: v for k, v in context.items() if k != "source_excerpts"}

    parts: list[str] = [f"## Subsystem: {name}\n"]
    parts.append(
        f"This subsystem contains {metadata.get('file_count', 0)} files. "
        f"Below: (1) the most representative files as raw source, "
        f"(2) symbols, dependency edges, and per-file metrics.\n"
    )

    if excerpts:
        parts.append("---\n## Representative source files\n")
        for ex in excerpts:
            f = ex.get("file", "unknown")
            content = ex.get("content", "")
            lang_hint = _language_fence(f)
            parts.append(f"### `{f}`\n\n```{lang_hint}\n{content}\n```\n")

    parts.append("---\n## Structured metadata (JSON)\n")
    parts.append("```json\n" + json.dumps(metadata, indent=2) + "\n```\n")
    return "\n".join(parts)


def _language_fence(file_path: str) -> str:
    """Pick a fence language hint from extension. Falls back to text."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {
        "cs": "csharp", "vb": "vbnet", "py": "python", "js": "javascript",
        "ts": "typescript", "java": "java", "cpp": "cpp", "h": "cpp",
        "lsp": "lisp", "lisp": "lisp", "mnl": "lisp",
        "ps1": "powershell", "psm1": "powershell",
        "sh": "bash", "cmd": "bat", "bat": "bat",
        "sql": "sql", "xml": "xml", "html": "html", "htm": "html",
        "json": "json", "yaml": "yaml", "yml": "yaml", "ini": "ini",
        "md": "markdown",
    }.get(ext, "text")


def _read_source_excerpts(
    rel_paths: list[str],
    source_root: Path,
) -> list[dict]:
    """Read the first _MAX_LINES_PER_EXCERPT lines of each representative file.

    Accepts both relative-to-source-root paths (the canonical form) and
    legacy absolute paths from earlier extractor versions.
    """
    excerpts: list[dict] = []
    total_chars = 0
    for rel in rel_paths:
        if total_chars >= _MAX_TOTAL_EXCERPT_CHARS:
            break
        candidate = Path(rel)
        full = candidate if candidate.is_absolute() else (source_root / rel)
        try:
            text = full.read_text(errors="replace")
        except OSError:
            continue
        snippet = "\n".join(text.splitlines()[:_MAX_LINES_PER_EXCERPT])
        if len(snippet) > _MAX_EXCERPT_CHARS:
            snippet = snippet[:_MAX_EXCERPT_CHARS] + "\n... [excerpt truncated]"
        if not snippet.strip():
            continue
        # Respect the global budget — truncate the last entry if needed.
        remaining = _MAX_TOTAL_EXCERPT_CHARS - total_chars
        if len(snippet) > remaining:
            snippet = snippet[:remaining] + "\n... [budget truncated]"
        excerpts.append({"file": rel, "content": snippet})
        total_chars += len(snippet)
    return excerpts


def _build_complexity_context(session_id: str, outlier_files: list[str], db_path: Path) -> dict:
    """Build a deep context for complexity-tier outlier files."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(outlier_files))
    try:
        all_symbols = [
            {"name": r["name"], "type": r["symbol_type"], "file": r["file_path"],
             "start_line": r["start_line"], "end_line": r["end_line"], "signature": r["signature"]}
            for r in conn.execute(
                f"SELECT name, symbol_type, file_path, start_line, end_line, signature "
                f"FROM symbol WHERE session_id=? AND file_path IN ({placeholders})",
                [session_id, *outlier_files],
            ).fetchall()
        ]
        all_metrics = {}
        for r in conn.execute(
            f"SELECT file_path, metric_name, metric_value FROM complexity_metric "
            f"WHERE session_id=? AND file_path IN ({placeholders})",
            [session_id, *outlier_files],
        ).fetchall():
            all_metrics.setdefault(r["file_path"], {})[r["metric_name"]] = r["metric_value"]

        callers = [
            {"caller": r["source_file"], "callee": r["target_file"], "type": r["dep_type"]}
            for r in conn.execute(
                f"SELECT source_file, target_file, dep_type FROM dependency_edge "
                f"WHERE session_id=? AND target_file IN ({placeholders}) LIMIT 200",
                [session_id, *outlier_files],
            ).fetchall()
        ]
        callees = [
            {"caller": r["source_file"], "callee": r["target_file"], "type": r["dep_type"]}
            for r in conn.execute(
                f"SELECT source_file, target_file, dep_type FROM dependency_edge "
                f"WHERE session_id=? AND source_file IN ({placeholders}) LIMIT 200",
                [session_id, *outlier_files],
            ).fetchall()
        ]
    finally:
        conn.close()

    return {
        "outlier_file_count": len(outlier_files),
        "files_with_metrics": [
            {"file": f, "metrics": all_metrics.get(f, {})} for f in outlier_files
        ],
        "all_symbols": all_symbols,
        "who_calls_these_files": callers,
        "what_these_files_call": callees,
    }


def _parse_findings(text: str) -> list[dict]:
    """Extract JSON array of findings from Claude's response.

    Handles three failure modes that have actually occurred:
      - Response prefixed with ```json fence (start of array still parseable).
      - Response truncated by max_tokens mid-finding (needs balanced-bracket
        recovery — drop the partial last item and close the array).
      - Response wrapped in extra prose; the array is still locatable by
        scanning for the first `[` followed by a `{`.
    """
    start = text.find("[")
    if start < 0:
        return []
    # First try the fast path: the array closes cleanly.
    end = text.rfind("]") + 1
    if end > start:
        try:
            result = json.loads(text[start:end])
            if isinstance(result, list):
                return [r for r in result if isinstance(r, dict)]
        except json.JSONDecodeError:
            pass

    # Recovery path: walk from `start` and collect complete top-level objects.
    # Bracket counting with string-state tracking keeps us out of trouble on
    # quoted brackets/braces inside finding descriptions.
    i = start + 1
    depth = 0
    in_string = False
    escape = False
    obj_start: Optional[int] = None
    findings: list[dict] = []
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
        elif ch == "\\" and in_string:
            escape = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and obj_start is not None:
                    candidate = text[obj_start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            findings.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = None
            elif ch == "]" and depth == 0:
                break
        i += 1
    return findings
