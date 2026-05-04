"""ALARMv3 MCP tools — 6 tools, all state-gated by guardrails.

Every tool call:
1. Logs to the WORM audit log
2. Validates session state before executing
3. Propagates GuardrailViolation as a tool error (LLM cannot bypass)
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..core.guardrails import ANALYSIS_COMPLETE_STATES, GuardrailViolation, SessionState
from ..core.session import SessionManager


def _workspace() -> Path:
    return Path(os.environ.get("ALARMV3_WORKSPACE", Path.cwd()))


def _try_aaa_grounding(problem_summary: str) -> "str | None":
    """Best-effort call to AAA REST API for architecture grounding.

    Reads AAA_REST_URL from environment (e.g. http://localhost:8080).
    Returns None silently if AAA is unavailable — never blocks synthesis.
    """
    base_url = os.environ.get("AAA_REST_URL", "").rstrip("/")
    if not base_url:
        return None
    try:
        payload = json.dumps({"problem_statement": problem_summary}).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/architecture-recommendation",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("recommendation", "")
    except Exception:
        return None


def _knowledge_built(session) -> bool:
    """True if at least one embedded chunk exists for this session."""
    db_path = session.artifact_dir / "analysis.db"
    if not db_path.exists():
        return False
    try:
        import pysqlite3 as sqlite3
        import sqlite_vec
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.enable_load_extension(False)
        n = conn.execute(
            "SELECT COUNT(*) FROM code_chunk WHERE session_id=? AND embedded=1",
            (session.session_id,),
        ).fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def register_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    def attach_repository(source_path: str) -> dict:
        """Attach ALARMv3 to a legacy codebase.

        Creates a session and sets the source path. The source repository
        is treated as a read-only archive — it will never be modified.
        Call confirm_guardrails next.

        Args:
            source_path: Absolute or relative path to the legacy codebase root.
        """
        sm = SessionManager(_workspace())
        session = sm.get_or_create()
        g = session.guardrails
        g.log_tool_call("attach_repository", {"source_path": source_path})

        try:
            g.require_state(session.state, SessionState.UNATTACHED)
            path = Path(source_path).resolve()
            if not path.exists():
                raise ValueError(f"Path does not exist: {path}")
            if not path.is_dir():
                raise ValueError(f"Path is not a directory: {path}")

            session.set_source(path)
            session.transition_to(SessionState.ATTACHED)

            file_estimate = sum(1 for p in path.rglob("*") if p.is_file())
            return {
                "session_id": session.session_id,
                "state": session.state.value,
                "source_path": str(path),
                "file_count_estimate": file_estimate,
                "next_step": "Call confirm_guardrails(session_id) to proceed.",
            }
        except (GuardrailViolation, ValueError) as e:
            g.log_error("attach_repository", str(e))
            raise

    @mcp.tool()
    def confirm_guardrails(session_id: str) -> dict:
        """Confirm read-only guardrails before analysis begins.

        This is a mandatory gate. By calling this tool you confirm:
        - The source repository will NOT be modified
        - Analysis artifacts are written to .alarmv3/ only
        - Analyzed code will NEVER be executed

        Args:
            session_id: The session ID returned by attach_repository.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("confirm_guardrails", {"session_id": session_id})

        try:
            g.require_state(session.state, SessionState.ATTACHED)
            session.transition_to(SessionState.READ_ONLY_CONFIRMED)
            return {
                "session_id": session_id,
                "state": session.state.value,
                "confirmed": True,
                "next_step": "Call start_full_mapping(session_id) to begin discovery.",
            }
        except GuardrailViolation as e:
            g.log_error("confirm_guardrails", str(e))
            raise

    @mcp.tool()
    def start_full_mapping(session_id: str) -> dict:
        """Begin recursive file discovery and manifest building.

        Discovers all source files, detects languages, and builds the file
        manifest. Runs in the background — poll get_job_status(job_id)
        until status is 'complete'.

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("start_full_mapping", {"session_id": session_id})

        try:
            g.require_state(session.state, SessionState.READ_ONLY_CONFIRMED)
            session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)

            from ..core.orchestration import Orchestrator
            job_id = Orchestrator(session).start_mapping()

            return {
                "session_id": session_id,
                "job_id": job_id,
                "state": session.state.value,
                "next_step": f"Poll get_job_status('{job_id}') until status='complete', then call run_analysis.",
            }
        except GuardrailViolation as e:
            g.log_error("start_full_mapping", str(e))
            raise

    @mcp.tool()
    def get_job_status(job_id: str) -> dict:
        """Get the status and progress of a running analysis job.

        Args:
            job_id: The job ID returned by start_full_mapping or run_analysis.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            raise ValueError("No active session. Call attach_repository first.")

        from ..core.orchestration import Orchestrator
        return Orchestrator(session).get_job_status(job_id)

    @mcp.tool()
    def run_analysis(session_id: str) -> dict:
        """Run dependency graph construction and complexity analysis.

        Parses all discovered source files with tree-sitter (or regex fallback
        for VB.NET), builds the dependency graph, computes complexity metrics,
        and prepares code chunks for RAG (Phase 2). Runs in the background.

        Requires mapping to be complete (state: ANALYSIS_IN_PROGRESS).

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("run_analysis", {"session_id": session_id})

        try:
            g.require_state(session.state, SessionState.ANALYSIS_IN_PROGRESS)

            from ..core.orchestration import Orchestrator
            job_id = Orchestrator(session).start_analysis()

            return {
                "session_id": session_id,
                "job_id": job_id,
                "state": session.state.value,
                "next_step": f"Poll get_job_status('{job_id}') until complete, then call generate_recommendations.",
            }
        except GuardrailViolation as e:
            g.log_error("run_analysis", str(e))
            raise

    @mcp.tool()
    def generate_recommendations(session_id: str) -> dict:
        """Generate prioritized modernization recommendations using Claude.

        Assembles a context from the dependency graph and complexity metrics,
        then calls Claude to synthesize architecture patterns and produce an
        ordered, actionable recommendation list. Runs synchronously (may take
        10–30 seconds for large codebases).

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("generate_recommendations", {"session_id": session_id})

        try:
            g.require_state(session.state, SessionState.ANALYSIS_IN_PROGRESS)

            aaa_grounding = _try_aaa_grounding(
                f"Legacy codebase at {session.source_path}: "
                "generate prioritized modernization recommendations"
            )
            if aaa_grounding:
                g.log_tool_call("aaa_grounding_fetched", {"chars": len(aaa_grounding)})

            from ..core.orchestration import Orchestrator
            result = Orchestrator(session).synthesize_recommendations(
                aaa_grounding=aaa_grounding
            )
            session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

            return {**result, "state": session.state.value}
        except GuardrailViolation as e:
            g.log_error("generate_recommendations", str(e))
            raise

    @mcp.tool()
    def query_codebase(session_id: str, question: str, top_k: int = 10) -> dict:
        """Ask a natural language question about the analyzed codebase.

        Embeds the question with nomic-embed-text (via local Ollama), searches
        the sqlite-vec index for the most similar code chunks, and returns them
        with source locations. The knowledge index is built lazily on the first
        call after analysis completes.

        Requires Ollama running at localhost:11434 with nomic-embed-text pulled.
        Requires state: ANALYSIS_COMPLETE or later.

        Args:
            session_id: The session ID.
            question: Natural language question about the codebase.
            top_k: Number of results to return (default 10, max 50).
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("query_codebase", {"session_id": session_id, "question": question})

        try:
            g.require_state_in(session.state, ANALYSIS_COMPLETE_STATES)
            top_k = min(max(1, top_k), 50)

            from ..core.knowledge import KnowledgeBuilder
            kb = KnowledgeBuilder(session)

            # Lazy build: embed on first query if not already done
            needs_build = not _knowledge_built(session)
            if needs_build:
                kb.build()

            results = kb.query(question, top_k=top_k)
            return {
                "session_id": session_id,
                "question": question,
                "results": results,
                "total": len(results),
                "index_built_this_call": needs_build,
            }
        except GuardrailViolation as e:
            g.log_error("query_codebase", str(e))
            raise

    @mcp.tool()
    def review_recommendations(
        session_id: str,
        accept_ids: list[int],
        reject_ids: list[int],
    ) -> dict:
        """Human review gate: accept or reject evaluated recommendations.

        After generate_recommendations runs the adversarial evaluator, call this
        tool to record your decisions. Review the evaluator critique first at
        recommendations://evaluated. Accepted recommendations are stored and
        available for implementation planning. Rejected recommendations are
        archived.

        Requires state: RECOMMENDATIONS_PENDING_REVIEW.

        Args:
            session_id: The session ID.
            accept_ids: List of recommendation rank numbers to accept.
            reject_ids: List of recommendation rank numbers to reject.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call(
            "review_recommendations",
            {"session_id": session_id, "accept_ids": accept_ids, "reject_ids": reject_ids},
        )

        try:
            g.require_state(session.state, SessionState.RECOMMENDATIONS_PENDING_REVIEW)

            import sqlite3
            db_path = session.artifact_dir / "analysis.db"
            conn = sqlite3.connect(db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            skipped_due_to_verdict: list[int] = []
            try:
                for rank in accept_ids:
                    cur = conn.execute(
                        "UPDATE recommendation SET review_status='accepted', approved=1 "
                        "WHERE session_id=? AND rank=? AND evaluator_verdict='accept'",
                        (session_id, rank),
                    )
                    if cur.rowcount == 0:
                        # Disambiguate: rank may not exist, or verdict isn't 'accept'.
                        # Only report verdict-skips; missing ranks are caller error.
                        existing_verdict = conn.execute(
                            "SELECT evaluator_verdict FROM recommendation "
                            "WHERE session_id=? AND rank=?",
                            (session_id, rank),
                        ).fetchone()
                        if existing_verdict is not None and existing_verdict[0] != "accept":
                            skipped_due_to_verdict.append(rank)
                for rank in reject_ids:
                    conn.execute(
                        "UPDATE recommendation SET review_status='rejected' "
                        "WHERE session_id=? AND rank=?",
                        (session_id, rank),
                    )
                accepted_count = conn.execute(
                    "SELECT COUNT(*) FROM recommendation "
                    "WHERE session_id=? AND review_status='accepted'",
                    (session_id,),
                ).fetchone()[0]
                conn.commit()
            finally:
                conn.close()

            session.transition_to(SessionState.ANALYSIS_COMPLETE)

            applied_accepts = len(accept_ids) - len(skipped_due_to_verdict)
            msg_lines = [
                f"Review complete. {accepted_count} recommendations accepted."
            ]
            if skipped_due_to_verdict:
                msg_lines.append(
                    f"Skipped {len(skipped_due_to_verdict)} accept(s) — "
                    f"evaluator_verdict not 'accept': ranks {skipped_due_to_verdict}. "
                    "Override requires re-running the evaluator or editing the verdict."
                )
            msg_lines.append("Full results at recommendations://latest.")
            msg_lines.append("Proceed to implementation planning when ready.")

            return {
                "session_id": session_id,
                "state": session.state.value,
                "accepted": applied_accepts,
                "rejected": len(reject_ids),
                "skipped_due_to_verdict": skipped_due_to_verdict,
                "total_accepted": accepted_count,
                "message": " ".join(msg_lines),
            }
        except GuardrailViolation as e:
            g.log_error("review_recommendations", str(e))
            raise

    @mcp.tool()
    def plan_implementation(session_id: str, rec_ranks: list[int]) -> dict:
        """Select accepted recommendations and create an ordered implementation plan.

        Reads the accepted recommendations at the given ranks, orders them by
        dependency (files shared across multiple recs are tackled first), and
        stores a phase-by-phase implementation plan.

        Requires state: ANALYSIS_COMPLETE. Only accepted recommendations can be planned.

        Args:
            session_id: The session ID.
            rec_ranks: List of recommendation rank numbers to include in the plan.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("plan_implementation", {"session_id": session_id, "rec_ranks": rec_ranks})

        try:
            g.require_state(session.state, SessionState.ANALYSIS_COMPLETE)

            from ..core.implementation import ImplementationPlanner
            result = ImplementationPlanner(session).create_plan(rec_ranks)
            session.transition_to(SessionState.IMPLEMENTATION_PLANNED)

            return {
                **result,
                "state": session.state.value,
                "message": (
                    f"Implementation plan created: {result['plan_item_count']} items. "
                    "Call clone_for_implementation to set up the working directory."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("plan_implementation", str(e))
            raise

    @mcp.tool()
    def clone_for_implementation(session_id: str, target_path: str) -> dict:
        """Clone the source repository to a new working directory for implementation.

        Copies the source repo to target_path (which must not exist). Sets up a
        local git repo in the target so each accepted change gets its own commit.
        The source repository is NEVER modified.

        Requires state: IMPLEMENTATION_PLANNED.

        Args:
            session_id: The session ID.
            target_path: Absolute path where the working copy will be created.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("clone_for_implementation", {"session_id": session_id, "target_path": target_path})

        try:
            g.require_state(session.state, SessionState.IMPLEMENTATION_PLANNED)

            from pathlib import Path as _Path

            from ..core.implementation import clone_source_to_target

            source = session.source_path
            if not source:
                raise ValueError("No source path attached to session")

            target = _Path(target_path).resolve()
            g.assert_no_write_to_source(target, source)
            clone_source_to_target(source, target)

            session.set_metadata("target_path", str(target))
            session.transition_to(SessionState.WORKING_REPO_READY)

            return {
                "session_id": session_id,
                "state": session.state.value,
                "target_path": str(target),
                "message": (
                    f"Working copy created at {target}. "
                    "Call implement_next to begin applying changes."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("clone_for_implementation", str(e))
            raise

    @mcp.tool()
    def implement_next(session_id: str) -> dict:
        """Generate the next code change through the plan/build/eval pipeline.

        Takes the next pending plan item, loads only the affected files from the
        working copy, runs three Claude calls (planner → builder → adversarial
        evaluator), and returns the proposed diff with evaluation results.

        Does NOT write any files. Call accept_change or reject_change after reviewing.
        If a prior attempt was rejected, the feedback is automatically injected.

        Requires state: WORKING_REPO_READY.

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("implement_next", {"session_id": session_id})

        try:
            g.require_state(session.state, SessionState.WORKING_REPO_READY)

            from ..core.implementation import ImplementationRunner
            result = ImplementationRunner(session).run_next()
            return {**result, "state": session.state.value}
        except GuardrailViolation as e:
            g.log_error("implement_next", str(e))
            raise

    @mcp.tool()
    def accept_change(session_id: str, change_id: int) -> dict:
        """Accept a generated code change and commit it to the working directory.

        Applies the diff to the TARGET files and creates a git commit. The source
        repository is never touched. Review the diff at implementation://changes
        before calling this.

        Requires state: WORKING_REPO_READY.

        Args:
            session_id: The session ID.
            change_id: The change ID returned by implement_next.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("accept_change", {"session_id": session_id, "change_id": change_id})

        try:
            g.require_state(session.state, SessionState.WORKING_REPO_READY)

            from ..core.implementation import ImplementationRunner
            result = ImplementationRunner(session).accept_change(change_id)
            return {**result, "state": session.state.value}
        except GuardrailViolation as e:
            g.log_error("accept_change", str(e))
            raise

    @mcp.tool()
    def reject_change(session_id: str, change_id: int, feedback: str) -> dict:
        """Reject a generated code change and provide feedback for retry.

        Discards the proposed diff and stores your feedback. The next call to
        implement_next will retry the same plan item with your feedback injected
        into the context.

        Requires state: WORKING_REPO_READY.

        Args:
            session_id: The session ID.
            change_id: The change ID returned by implement_next.
            feedback: Specific feedback explaining what was wrong and what to do instead.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("reject_change", {"session_id": session_id, "change_id": change_id})

        try:
            g.require_state(session.state, SessionState.WORKING_REPO_READY)

            from ..core.implementation import ImplementationRunner
            result = ImplementationRunner(session).reject_change(change_id, feedback)
            return {**result, "state": session.state.value}
        except GuardrailViolation as e:
            g.log_error("reject_change", str(e))
            raise

    # ── Phase 6 tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def run_deep_analysis(
        session_id: str,
        max_subsystems: int = 15,
        cyclomatic_threshold: int = 10,
        coupling_threshold: int = 10,
    ) -> dict:
        """Run exhaustive multi-pass LLM synthesis over the full codebase semantic graph.

        A more thorough alternative to generate_recommendations. Instead of a single
        pass over a statistical digest, this runs:

          1. SubsystemPartitioner — union-find clustering of the dependency graph
             into coherent architectural subsystems (every file gets covered)
          2. Per-subsystem passes — one Claude call per cluster with all symbols,
             all internal dependency edges, and all complexity metrics for that cluster
          3. Complexity-tier deep pass — focused analysis of files whose cyclomatic
             complexity or fan-in/fan-out exceeds the threshold
          4. Aggregation pass — deduplication, cross-subsystem promotion, final ranking
          5. Adversarial evaluator — same evaluator as generate_recommendations

        Runs in the background. Poll get_job_status(job_id) until status='complete',
        then call review_recommendations as normal.

        Cost note: N subsystems × ~1 Claude call each + 2 shared passes. Estimated
        10–30 Claude calls for a typical codebase.

        Requires state: ANALYSIS_IN_PROGRESS.

        Args:
            session_id: The session ID.
            max_subsystems: Maximum subsystem passes to run (default 15, max 30).
                            Smaller clusters are merged into a 'remaining' bucket.
            cyclomatic_threshold: Files with cyclomatic complexity >= this get the
                                  complexity-tier deep pass (default 10).
            coupling_threshold: Files with combined fan-in+fan-out >= this also get
                                the complexity-tier pass (default 10).
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("run_deep_analysis", {
            "session_id": session_id,
            "max_subsystems": max_subsystems,
            "cyclomatic_threshold": cyclomatic_threshold,
            "coupling_threshold": coupling_threshold,
        })

        try:
            g.require_state(session.state, SessionState.ANALYSIS_IN_PROGRESS)
            max_subsystems = min(max(1, max_subsystems), 30)

            aaa_grounding = _try_aaa_grounding(
                f"Legacy codebase at {session.source_path}: "
                "exhaustive modernization analysis across all subsystems"
            )
            if aaa_grounding:
                g.log_tool_call("aaa_grounding_fetched", {"chars": len(aaa_grounding)})

            from ..core.orchestration import Orchestrator
            job_id = Orchestrator(session).start_deep_analysis(
                max_subsystems=max_subsystems,
                cyclomatic_threshold=cyclomatic_threshold,
                coupling_threshold=coupling_threshold,
                aaa_grounding=aaa_grounding,
            )
            session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

            return {
                "session_id": session_id,
                "job_id": job_id,
                "state": session.state.value,
                "max_subsystems": max_subsystems,
                "cyclomatic_threshold": cyclomatic_threshold,
                "coupling_threshold": coupling_threshold,
                "next_step": (
                    f"Poll get_job_status('{job_id}') until status='complete'. "
                    "Then review at recommendations://evaluated and call review_recommendations."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("run_deep_analysis", str(e))
            raise

    # ── Phase 7 tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def research_unknown_languages(
        session_id: str,
        max_samples_per_language: int = 5,
        persist_on_success: bool = True,
    ) -> dict:
        """Infer grammar patterns for files that discovery could not classify.

        Discovery marks files with unrecognised extensions as ineligible
        (e.g. AutoLISP .lsp/.dcl, PowerShell .ps1/.psm1, COBOL .cob, etc.).
        This tool runs a one-shot Claude call per language family on a small
        sample of those files to learn their syntax, then:

          1. Extracts inferred function/class/import symbols using the learned
             regex patterns and stores them in the existing symbol and
             dependency_edge tables (symbol_type='inferred_function', etc.)
          2. Marks previously-ineligible files as eligible so they appear in
             subsequent analysis passes
          3. If the symbol yield passes a plausibility gate, persists the
             grammar to ProjectMemory (category='pattern') so future sessions
             can skip the Claude inference step

        Runs in the background. Call get_job_status(job_id) to poll.
        Best called AFTER start_full_mapping completes but BEFORE
        run_analysis or run_deep_analysis, so inferred symbols are included
        in the semantic graph.

        Requires state: ANALYSIS_IN_PROGRESS.

        Args:
            session_id: The session ID.
            max_samples_per_language: Max file samples sent to Claude per
                                      unknown extension (default 5).
            persist_on_success: Whether to write validated grammars to
                                ProjectMemory for reuse in future sessions
                                (default True).
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("research_unknown_languages", {
            "session_id": session_id,
            "max_samples_per_language": max_samples_per_language,
            "persist_on_success": persist_on_success,
        })

        try:
            g.require_state(session.state, SessionState.ANALYSIS_IN_PROGRESS)
            max_samples_per_language = min(max(1, max_samples_per_language), 20)

            from ..core.orchestration import Orchestrator
            job_id = Orchestrator(session).start_language_research(
                max_samples_per_language=max_samples_per_language,
                persist_on_success=persist_on_success,
            )

            return {
                "session_id": session_id,
                "job_id": job_id,
                "state": session.state.value,
                "next_step": (
                    f"Poll get_job_status('{job_id}') until status='complete'. "
                    "Then continue with run_analysis or run_deep_analysis — "
                    "inferred symbols will be included automatically."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("research_unknown_languages", str(e))
            raise

    # ── Phase 5 tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def implement_batch(session_id: str, max_concurrent: int = 3) -> dict:
        """Run plan/build/eval for all pending items, parallelising independent ones.

        Items whose affected files do not overlap are dispatched concurrently using
        a thread pool. Items that share files are serialised to prevent conflicting
        patches. Returns results for all items — auto-accepted changes are committed
        automatically; others require accept_change / reject_change.

        Requires state: WORKING_REPO_READY.

        Args:
            session_id: The session ID.
            max_concurrent: Max parallel workers per batch (default 3, max 8).
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("implement_batch", {"session_id": session_id, "max_concurrent": max_concurrent})

        try:
            g.require_state(session.state, SessionState.WORKING_REPO_READY)
            max_concurrent = min(max(1, max_concurrent), 8)

            from ..core.implementation import ImplementationRunner
            results = ImplementationRunner(session).run_batch(max_concurrent)

            pending_review = [r for r in results if not r.get("auto_accepted") and "error" not in r]
            auto_accepted = [r for r in results if r.get("auto_accepted")]
            errors = [r for r in results if "error" in r]

            return {
                "state": session.state.value,
                "total": len(results),
                "auto_accepted": len(auto_accepted),
                "pending_review": len(pending_review),
                "errors": len(errors),
                "results": results,
                "message": (
                    f"Batch complete: {len(auto_accepted)} auto-accepted, "
                    f"{len(pending_review)} awaiting review, {len(errors)} errors."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("implement_batch", str(e))
            raise

    @mcp.tool()
    def record_project_memory(
        session_id: str,
        category: str,
        key: str,
        content: str,
    ) -> dict:
        """Record a convention, decision, anti-pattern, or pattern to persistent project memory.

        Memory entries survive across sessions and are injected into synthesis and
        implementation prompts so accumulated knowledge influences future recommendations.

        Categories:
          - convention: coding style or naming rules discovered in this codebase
          - decision: architecture decisions (e.g., "we use Repository pattern, not Active Record")
          - antipattern: patterns to avoid (e.g., "do not use global singletons for state")
          - pattern: established patterns to follow (e.g., "all services use constructor injection")

        Args:
            session_id: The session ID (for audit attribution).
            category: One of: convention, decision, antipattern, pattern.
            key: Short unique identifier for this memory (e.g., "naming/class_suffix").
            content: The memory content — 1-3 sentences describing the rule or decision.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("record_project_memory", {"session_id": session_id, "category": category, "key": key})

        from ..core.memory import ProjectMemory
        result = ProjectMemory(session.alarm_dir).record(category, key, content, session_id)
        return {**result, "message": f"Memory recorded: [{category}] {key}"}

    @mcp.tool()
    def list_project_memory(category: str = "") -> dict:
        """List all persistent project memory entries, optionally filtered by category.

        Args:
            category: Filter by category (convention | decision | antipattern | pattern).
                      Leave empty to return all entries.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            raise ValueError("No active session. Call attach_repository first.")

        from ..core.memory import ProjectMemory
        entries = ProjectMemory(session.alarm_dir).list(category or None)
        return {
            "total": len(entries),
            "category_filter": category or "all",
            "entries": entries,
        }

    @mcp.tool()
    def get_autopilot_policy() -> dict:
        """Show the current autopilot auto-acceptance policy.

        If no policy file exists, returns the disabled default and writes a
        template to .alarmv3/policy/autopilot.yaml for human configuration.
        The policy file is in the GOVERNANCE zone — only humans should edit it.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            raise ValueError("No active session. Call attach_repository first.")

        from ..core.autopilot import AutopilotPolicy
        ap = AutopilotPolicy(session.alarm_dir)
        policy = ap.get_policy()
        template_path = None
        if not (session.alarm_dir / "policy" / "autopilot.yaml").exists():
            template_path = ap.init_template()
        return {
            "policy": policy,
            "policy_path": str(session.alarm_dir / "policy" / "autopilot.yaml"),
            "template_written": template_path is not None,
            "message": (
                "Template written to policy_path — edit it to configure auto-acceptance rules."
                if template_path else
                "Policy loaded from policy_path."
            ),
        }

    @mcp.tool()
    def register_repo(session_id: str) -> dict:
        """Register this session's repository in the cross-repo dependency registry.

        Extracts exported public symbols and language distribution from the
        completed analysis, then stores them in .alarmv3/crossrepo.db. Once two
        or more repos are registered, call query_cross_repo to discover coupling.

        Requires analysis to be complete (state: ANALYSIS_COMPLETE or later).

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("register_repo", {"session_id": session_id})

        try:
            g.require_state_in(session.state, ANALYSIS_COMPLETE_STATES)
            if not session.source_path:
                raise ValueError("No source path attached to session")

            from ..core.crossrepo import CrossRepoRegistry
            registry = CrossRepoRegistry(session.alarm_dir)
            result = registry.register(
                session_id,
                str(session.source_path),
                session.artifact_dir / "analysis.db",
            )
            return {
                **result,
                "state": session.state.value,
                "message": (
                    f"Registered {result['exported_module_count']} exported symbols. "
                    "Call query_cross_repo to find coupling with other registered repos."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("register_repo", str(e))
            raise

    @mcp.tool()
    def query_cross_repo(session_id: str) -> dict:
        """Find coupling between this repo and other registered repos.

        Matches this session's unresolved external module references against
        public symbols exported by other registered repos. Returns a ranked list
        of coupled repos with shared module names.

        Requires register_repo to have been called on this session and at least
        one other session.

        Requires state: ANALYSIS_COMPLETE or later.

        Args:
            session_id: The session ID.
        """
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session or session.session_id != session_id:
            raise ValueError(f"No active session with id: {session_id}")

        g = session.guardrails
        g.log_tool_call("query_cross_repo", {"session_id": session_id})

        try:
            g.require_state_in(session.state, ANALYSIS_COMPLETE_STATES)

            from ..core.crossrepo import CrossRepoRegistry
            registry = CrossRepoRegistry(session.alarm_dir)
            coupling = registry.find_coupling(
                session_id, session.artifact_dir / "analysis.db"
            )
            registered = registry.list_registered()
            return {
                "session_id": session_id,
                "state": session.state.value,
                "registered_repos": len(registered),
                "coupled_repos": len(coupling),
                "coupling": coupling,
                "message": (
                    f"Found {len(coupling)} coupled repo(s) across {len(registered)} registered. "
                    "Coupling is ordered by shared module count (highest first)."
                ) if coupling else (
                    f"No coupling found across {len(registered)} registered repo(s). "
                    "Register more repos or check that analysis is complete."
                ),
            }
        except GuardrailViolation as e:
            g.log_error("query_cross_repo", str(e))
            raise
