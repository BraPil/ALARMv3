"""Persistent project memory — conventions, decisions, and anti-patterns across sessions.

Phase 5. Backed by .alarmv3/memory.db (shared across all sessions in a workspace).
Injected into synthesis and implementation LLM prompts so discovered knowledge
accumulates over time rather than restarting from zero each session.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

_SCHEMA = """\
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS project_memory (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    category          TEXT NOT NULL,
    key               TEXT NOT NULL UNIQUE,
    content           TEXT NOT NULL,
    source_session_id TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_category ON project_memory(category);
"""

CATEGORIES = ("convention", "decision", "antipattern", "pattern")


class ProjectMemory:
    """Cross-session memory store for learned project conventions and decisions."""

    def __init__(self, alarm_dir: Path):
        self._db_path = alarm_dir / "memory.db"
        self._init()

    def record(
        self,
        category: str,
        key: str,
        content: str,
        session_id: Optional[str] = None,
    ) -> dict:
        """Insert or update a memory entry (upsert on key)."""
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")
        now = time.time()
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "INSERT INTO project_memory(category, key, content, source_session_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "content=excluded.content, updated_at=excluded.updated_at, "
                "source_session_id=excluded.source_session_id",
                (category, key, content, session_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return {"key": key, "category": category, "content": content}

    def delete(self, key: str) -> bool:
        """Remove a memory entry by key. Returns True if it existed."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            cur = conn.execute("DELETE FROM project_memory WHERE key=?", (key,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list(self, category: Optional[str] = None) -> list[dict]:
        """Return all memory entries, optionally filtered by category."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if category:
                rows = conn.execute(
                    "SELECT * FROM project_memory WHERE category=? ORDER BY updated_at DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM project_memory ORDER BY category, updated_at DESC"
                ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def format_for_prompt(self) -> str:
        """Return all entries formatted for injection into an LLM system prompt."""
        entries = self.list()
        if not entries:
            return ""
        by_category: dict[str, list[dict]] = {}
        for e in entries:
            by_category.setdefault(e["category"], []).append(e)
        lines = ["## Project memory (accumulated cross-session knowledge)\n"]
        for cat in CATEGORIES:
            items = by_category.get(cat)
            if not items:
                continue
            lines.append(f"\n### {cat.capitalize()}\n")
            for item in items:
                lines.append(f"- **{item['key']}**: {item['content']}")
        return "\n".join(lines)

    # ── Internal ───────────────────────────────────────────────────────────

    def _init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
