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
            try:
                for rank in accept_ids:
                    conn.execute(
                        "UPDATE recommendation SET review_status='accepted', approved=1 "
                        "WHERE session_id=? AND rank=?",
                        (session_id, rank),
                    )
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

            return {
                "session_id": session_id,
                "state": session.state.value,
                "accepted": len(accept_ids),
                "rejected": len(reject_ids),
                "total_accepted": accepted_count,
                "message": (
                    f"Review complete. {accepted_count} recommendations accepted. "
                    "Full results at recommendations://latest. "
                    "Proceed to implementation planning when ready."
                ),
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
