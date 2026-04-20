"""ALARMv3 MCP tools — 6 tools, all state-gated by guardrails.

Every tool call:
1. Logs to the WORM audit log
2. Validates session state before executing
3. Propagates GuardrailViolation as a tool error (LLM cannot bypass)
"""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..core.session import SessionManager
from ..core.guardrails import SessionState, GuardrailViolation, ANALYSIS_COMPLETE_STATES


def _workspace() -> Path:
    return Path(os.environ.get("ALARMV3_WORKSPACE", Path.cwd()))


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

            from ..core.orchestration import Orchestrator
            result = Orchestrator(session).synthesize_recommendations()
            session.transition_to(SessionState.ANALYSIS_COMPLETE)

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

            from ..core.knowledge import KnowledgeBuilder, OllamaUnavailableError
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
