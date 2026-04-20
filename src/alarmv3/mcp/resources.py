"""ALARMv3 MCP resources — 3 read-only session state resources."""

import json
import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..core.session import SessionManager


def _workspace() -> Path:
    return Path(os.environ.get("ALARMV3_WORKSPACE", Path.cwd()))


def register_resources(mcp: FastMCP) -> None:

    @mcp.resource("session://current")
    def session_current() -> str:
        """Current ALARMv3 session state and metadata."""
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            return json.dumps({
                "state": "UNATTACHED",
                "message": "No active session. Call attach_repository to begin.",
            }, indent=2)
        return json.dumps(session.to_dict(), indent=2)

    @mcp.resource("manifest://files")
    def manifest_files() -> str:
        """All files discovered in the most recent mapping."""
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            return json.dumps([])
        db_path = session.artifact_dir / "analysis.db"
        if not db_path.exists():
            return json.dumps([])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT relative_path, language, size_bytes, line_count, is_eligible "
                "FROM manifest WHERE session_id=? ORDER BY relative_path",
                (session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        return json.dumps([dict(r) for r in rows], indent=2)

    @mcp.resource("recommendations://latest")
    def recommendations_latest() -> str:
        """Latest prioritized modernization recommendations."""
        sm = SessionManager(_workspace())
        session = sm.get()
        if not session:
            return json.dumps([])
        db_path = session.artifact_dir / "analysis.db"
        if not db_path.exists():
            return json.dumps([])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT rank, category, severity, title, description, "
                "affected_files, effort, rationale, approved "
                "FROM recommendation WHERE session_id=? ORDER BY rank",
                (session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["affected_files"] = json.loads(d["affected_files"])
            result.append(d)
        return json.dumps(result, indent=2)
