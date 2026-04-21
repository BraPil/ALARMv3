"""Cross-repo dependency intelligence — registry and coupling analysis.

Phase 5. Backed by .alarmv3/crossrepo.db (shared across sessions).

When multiple repos are registered, find_coupling() cross-matches each repo's
unresolved external module references against other repos' exported public symbols.
Matches are stored as cross_repo_edge records and returned as coupling reports.

Enterprise context: a modernization campaign may span dozens of repos. This module
makes inter-repo dependencies explicit so recommendations can account for blast radius
beyond a single repo boundary.
"""

import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repo_registration (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL UNIQUE,
    repo_path        TEXT    NOT NULL,
    exported_modules TEXT    NOT NULL DEFAULT '[]',
    language_dist    TEXT    NOT NULL DEFAULT '{}',
    registered_at    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reg_session ON repo_registration(session_id);

CREATE TABLE IF NOT EXISTS cross_repo_edge (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_session_id TEXT    NOT NULL,
    target_session_id TEXT    NOT NULL,
    module_name       TEXT    NOT NULL,
    dep_count         INTEGER NOT NULL DEFAULT 1,
    discovered_at     REAL    NOT NULL,
    UNIQUE(source_session_id, target_session_id, module_name)
);
CREATE INDEX IF NOT EXISTS idx_edge_source ON cross_repo_edge(source_session_id);
CREATE INDEX IF NOT EXISTS idx_edge_target ON cross_repo_edge(target_session_id);
"""


class CrossRepoRegistry:
    """Registry of analyzed repos enabling coupling analysis across session boundaries."""

    def __init__(self, alarm_dir: Path):
        self._db_path = alarm_dir / "crossrepo.db"
        self._init()

    # ── Registration ───────────────────────────────────────────────────────

    def register(self, session_id: str, repo_path: str, analysis_db_path: Path) -> dict:
        """Register a repo. Extracts public symbols + language distribution from analysis.db."""
        exported, lang_dist = _extract_exports(session_id, analysis_db_path)
        now = time.time()
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "INSERT INTO repo_registration"
                "(session_id, repo_path, exported_modules, language_dist, registered_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "repo_path=excluded.repo_path, "
                "exported_modules=excluded.exported_modules, "
                "language_dist=excluded.language_dist, "
                "registered_at=excluded.registered_at",
                (session_id, repo_path, json.dumps(exported), json.dumps(lang_dist), now),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "session_id": session_id,
            "repo_path": repo_path,
            "exported_module_count": len(exported),
            "languages": lang_dist,
        }

    # ── Coupling analysis ──────────────────────────────────────────────────

    def find_coupling(self, session_id: str, analysis_db_path: Path) -> list[dict]:
        """Find other registered repos that this repo depends on or that depend on it.

        Matches this session's unresolved external dependencies against every other
        registered repo's exported symbol names.
        """
        external_deps = _extract_external_deps(session_id, analysis_db_path)
        if not external_deps:
            return []

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            others = conn.execute(
                "SELECT session_id, repo_path, exported_modules FROM repo_registration "
                "WHERE session_id != ?",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()

        results = []
        for other in others:
            other_exports = set(json.loads(other["exported_modules"]))
            matched = external_deps & other_exports
            if not matched:
                continue
            results.append({
                "target_session_id": other["session_id"],
                "target_repo_path": other["repo_path"],
                "shared_modules": sorted(matched),
                "coupling_count": len(matched),
            })
            self._record_edges(session_id, other["session_id"], matched)

        results.sort(key=lambda x: -x["coupling_count"])
        return results

    # ── Listing ────────────────────────────────────────────────────────────

    def list_registered(self) -> list[dict]:
        """Return all registered repos ordered by registration time (newest first)."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT session_id, repo_path, language_dist, registered_at "
                "FROM repo_registration ORDER BY registered_at DESC"
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["language_dist"] = json.loads(d["language_dist"])
            result.append(d)
        return result

    def get_edges(self, session_id: str) -> list[dict]:
        """Return all known cross-repo coupling edges for a session."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT e.*, r.repo_path AS target_repo_path "
                "FROM cross_repo_edge e "
                "JOIN repo_registration r ON r.session_id = e.target_session_id "
                "WHERE e.source_session_id=? "
                "ORDER BY e.dep_count DESC",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ── Internal ───────────────────────────────────────────────────────────

    def _init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _record_edges(self, source_id: str, target_id: str, modules: set[str]) -> None:
        now = time.time()
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for mod in modules:
                conn.execute(
                    "INSERT INTO cross_repo_edge"
                    "(source_session_id, target_session_id, module_name, dep_count, discovered_at) "
                    "VALUES (?,?,?,1,?) "
                    "ON CONFLICT(source_session_id, target_session_id, module_name) "
                    "DO UPDATE SET dep_count=dep_count+1",
                    (source_id, target_id, mod, now),
                )
            conn.commit()
        finally:
            conn.close()


# ── Module-level helpers ──────────────────────────────────────────────────────

def _extract_exports(session_id: str, analysis_db_path: Path) -> tuple[list[str], dict]:
    """Return (public_symbol_names, language_distribution) from analysis.db."""
    if not analysis_db_path.exists():
        return [], {}
    conn = sqlite3.connect(analysis_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        symbols = [
            r["name"]
            for r in conn.execute(
                "SELECT DISTINCT name FROM symbol "
                "WHERE session_id=? AND is_public=1 LIMIT 1000",
                (session_id,),
            ).fetchall()
        ]
        lang_rows = conn.execute(
            "SELECT language, COUNT(*) AS n FROM manifest "
            "WHERE session_id=? AND is_eligible=1 AND language IS NOT NULL "
            "GROUP BY language",
            (session_id,),
        ).fetchall()
        lang_dist = {r["language"]: r["n"] for r in lang_rows}
    finally:
        conn.close()
    return symbols, lang_dist


def _extract_external_deps(session_id: str, analysis_db_path: Path) -> set[str]:
    """Return the set of unresolved external module names from analysis.db."""
    if not analysis_db_path.exists():
        return set()
    conn = sqlite3.connect(analysis_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT target_module FROM dependency_edge "
            "WHERE session_id=? AND is_resolved=0 AND target_module IS NOT NULL",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return {r["target_module"] for r in rows if r["target_module"]}
