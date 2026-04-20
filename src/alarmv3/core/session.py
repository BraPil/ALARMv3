"""Session lifecycle and SQLite-backed work queue.

One session per workspace (Phase 1). Session state and work queue live in
.alarmv3/session.db (WAL mode). Analysis artifacts live in
.alarmv3/sessions/<uuid>/analysis.db.
"""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .guardrails import GuardrailsManager, SessionState


_SESSION_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS session (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL DEFAULT 'UNATTACHED',
    source_path  TEXT,
    artifact_dir TEXT NOT NULL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    metadata     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS work_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phase        TEXT    NOT NULL,
    file_path    TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending',
    priority     INTEGER NOT NULL DEFAULT 0,
    created_at   REAL    NOT NULL,
    started_at   REAL,
    completed_at REAL,
    error        TEXT,
    result       TEXT
);

CREATE INDEX IF NOT EXISTS idx_wq_phase_status
    ON work_queue(phase, status, priority DESC);
"""


class Session:
    """Single analysis session bound to a SQLite database."""

    def __init__(self, db_path: Path, session_id: str):
        self._db_path = db_path
        self.session_id = session_id

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def state(self) -> SessionState:
        return SessionState(self._row()["state"])

    @property
    def source_path(self) -> Optional[Path]:
        val = self._row()["source_path"]
        return Path(val) if val else None

    @property
    def artifact_dir(self) -> Path:
        return Path(self._row()["artifact_dir"])

    @property
    def guardrails(self) -> GuardrailsManager:
        return GuardrailsManager(self.artifact_dir)

    # ── Mutations ─────────────────────────────────────────────────────────

    def set_source(self, path: Path) -> None:
        self._update("source_path", str(path.resolve()))

    def transition_to(self, target: SessionState) -> None:
        new_state = self.guardrails.transition(self.state, target)
        self._update("state", new_state.value)

    def set_metadata(self, key: str, value) -> None:
        meta = self.get_metadata()
        meta[key] = value
        self._update("metadata", json.dumps(meta))

    def get_metadata(self) -> dict:
        return json.loads(self._row()["metadata"])

    # ── Work queue ────────────────────────────────────────────────────────

    def enqueue(self, phase: str, file_path: Optional[str] = None, priority: int = 0) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO work_queue(phase, file_path, status, priority, created_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (phase, file_path, priority, time.time()),
            )
            return cur.lastrowid

    def claim_work(self, phase: str) -> Optional[dict]:
        """Atomically claim the next pending item for a phase."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue "
                "WHERE phase=? AND status='pending' "
                "ORDER BY priority DESC, id ASC LIMIT 1",
                (phase,),
            ).fetchone()
            if not row:
                return None
            started = time.time()
            conn.execute(
                "UPDATE work_queue SET status='running', started_at=? WHERE id=?",
                (started, row["id"]),
            )
            result = dict(row)
            result["status"] = "running"
            result["started_at"] = started
            return result

    def complete_work(self, item_id: int, result: Optional[dict] = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_queue SET status='complete', completed_at=?, result=? WHERE id=?",
                (time.time(), json.dumps(result) if result else None, item_id),
            )

    def fail_work(self, item_id: int, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_queue SET status='failed', completed_at=?, error=? WHERE id=?",
                (time.time(), error, item_id),
            )

    def queue_stats(self, phase: str) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as n FROM work_queue WHERE phase=? GROUP BY status",
                (phase,),
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}

    def to_dict(self) -> dict:
        row = self._row()
        return {
            "session_id": self.session_id,
            "state": row["state"],
            "source_path": row["source_path"],
            "artifact_dir": row["artifact_dir"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata"]),
        }

    # ── Internals ─────────────────────────────────────────────────────────

    def _row(self) -> sqlite3.Row:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM session WHERE id=?", (self.session_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Session {self.session_id} not found in {self._db_path}")
        return row

    def _update(self, column: str, value) -> None:
        with self._conn() as conn:
            conn.execute(
                f"UPDATE session SET {column}=?, updated_at=? WHERE id=?",
                (value, time.time(), self.session_id),
            )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class SessionManager:
    """Manages one session per workspace (.alarmv3/ layout).

    Phase 1: one session per workspace.
    Phase 2+: multiple sessions per workspace (multi-codebase comparison).
    """

    _ALARM_DIR = ".alarmv3"
    _DB_NAME = "session.db"

    def __init__(self, workspace_root: Path):
        self._workspace = workspace_root.resolve()
        self._alarm_dir = self._workspace / self._ALARM_DIR
        self._db_path = self._alarm_dir / self._DB_NAME

    def get_or_create(self) -> Session:
        """Return existing session or create a new one."""
        self._alarm_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM session LIMIT 1").fetchone()
            if row:
                return Session(self._db_path, row["id"])
            session_id = str(uuid.uuid4())
            artifact_dir = self._alarm_dir / "sessions" / session_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            conn.execute(
                "INSERT INTO session(id, state, artifact_dir, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, SessionState.UNATTACHED.value, str(artifact_dir),
                 time.time(), time.time()),
            )
            return Session(self._db_path, session_id)

    def get(self) -> Optional[Session]:
        """Return the active session, or None if no session exists."""
        if not self._db_path.exists():
            return None
        self._init_db()
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM session LIMIT 1").fetchone()
            return Session(self._db_path, row["id"]) if row else None

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SESSION_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
