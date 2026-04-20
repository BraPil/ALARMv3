"""Unit tests for core/knowledge.py — chunking logic and helpers.

Ollama-free: tests that exercise _slice_file, _approx_tokens, chunk creation
logic, and the vec connection helper. Embedding tests require Ollama and are
in tests/integration/test_rag_pipeline.py.
"""

import hashlib
import sqlite3 as stdlib_sqlite3
import time
from pathlib import Path

import pytest

from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager
from alarmv3.core.knowledge import (
    _slice_file,
    _approx_tokens,
    _vec_conn,
    _ensure_vec_table,
    _ollama_running,
    KnowledgeBuilder,
    OllamaUnavailableError,
)

SAMPLE_PY = """\
import os

class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"

def main():
    g = Greeter()
    print(g.greet("world"))
"""


@pytest.fixture()
def workspace(tmp_path):
    return tmp_path


@pytest.fixture()
def session(workspace):
    sm = SessionManager(workspace)
    return sm.get_or_create()


@pytest.fixture()
def seeded_db(session, tmp_path):
    """Session with analysis.db, a manifest file, and symbols populated."""
    src = tmp_path / "greeter.py"
    src.write_text(SAMPLE_PY)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)

    conn = stdlib_sqlite3.connect(db_path)
    now = time.time()
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
        (session.session_id, str(src), "greeter.py", "python",
         len(SAMPLE_PY), SAMPLE_PY.count("\n"), 1, now),
    )
    conn.execute(
        "INSERT INTO symbol(session_id, file_path, name, symbol_type, start_line, end_line) "
        "VALUES (?,?,?,?,?,?)",
        (session.session_id, str(src), "Greeter", "class", 3, 5),
    )
    conn.execute(
        "INSERT INTO symbol(session_id, file_path, name, symbol_type, start_line, end_line) "
        "VALUES (?,?,?,?,?,?)",
        (session.session_id, str(src), "greet", "function", 4, 5),
    )
    conn.execute(
        "INSERT INTO symbol(session_id, file_path, name, symbol_type, start_line, end_line) "
        "VALUES (?,?,?,?,?,?)",
        (session.session_id, str(src), "main", "function", 7, 9),
    )
    conn.commit()
    conn.close()
    return session, src


# ── _slice_file ───────────────────────────────────────────────────────────────

def test_slice_file_full(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\nline3\n")
    assert _slice_file(str(f), 1, 3) == "line1\nline2\nline3"


def test_slice_file_partial(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\nline3\n")
    assert _slice_file(str(f), 2, 2) == "line2"


def test_slice_file_missing_returns_none():
    assert _slice_file("/nonexistent/file.py", 1, 5) is None


def test_slice_file_empty_content_returns_none(tmp_path):
    f = tmp_path / "empty.py"
    f.write_text("   \n   \n")
    assert _slice_file(str(f), 1, 2) is None


# ── _approx_tokens ────────────────────────────────────────────────────────────

def test_approx_tokens_nonempty():
    assert _approx_tokens("hello world") == max(1, len("hello world") // 4)


def test_approx_tokens_minimum_one():
    assert _approx_tokens("x") == 1


# ── vec connection ────────────────────────────────────────────────────────────

def test_vec_conn_opens(session):
    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = _vec_conn(db_path)
    ver = conn.execute("SELECT vec_version()").fetchone()[0]
    conn.close()
    assert ver.startswith("v")


def test_ensure_vec_table_creates(session):
    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = _vec_conn(db_path)
    _ensure_vec_table(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' OR type='shadow'"
    ).fetchall()}
    conn.close()
    assert "chunk_vectors" in tables


def test_ensure_vec_table_idempotent(session):
    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = _vec_conn(db_path)
    _ensure_vec_table(conn)
    _ensure_vec_table(conn)  # must not raise
    conn.close()


# ── KnowledgeBuilder.build (Ollama skipped) ───────────────────────────────────

def test_build_raises_if_ollama_down(seeded_db, monkeypatch):
    session, _ = seeded_db
    monkeypatch.setattr("alarmv3.core.knowledge._ollama_running", lambda: False)
    with pytest.raises(OllamaUnavailableError):
        KnowledgeBuilder(session).build()


def test_create_chunks_from_symbols(seeded_db, monkeypatch):
    """Chunk creation runs even without Ollama (we skip the embed step)."""
    session, src = seeded_db
    monkeypatch.setattr("alarmv3.core.knowledge._ollama_running", lambda: True)

    kb = KnowledgeBuilder(session)
    db_path = session.artifact_dir / "analysis.db"
    conn = _vec_conn(db_path)
    _ensure_vec_table(conn)

    created = kb._create_chunks(conn)
    conn.close()

    assert created >= 2  # at least Greeter class + main function

    # Verify rows in code_chunk
    check = stdlib_sqlite3.connect(db_path)
    rows = check.execute(
        "SELECT symbol_name, chunk_type FROM code_chunk WHERE session_id=?",
        (session.session_id,),
    ).fetchall()
    check.close()
    names = {r[0] for r in rows}
    assert "Greeter" in names or "main" in names


def test_create_chunks_idempotent(seeded_db, monkeypatch):
    """Running _create_chunks twice should not create duplicates."""
    session, _ = seeded_db
    monkeypatch.setattr("alarmv3.core.knowledge._ollama_running", lambda: True)

    kb = KnowledgeBuilder(session)
    db_path = session.artifact_dir / "analysis.db"
    conn = _vec_conn(db_path)
    _ensure_vec_table(conn)

    count1 = kb._create_chunks(conn)
    count2 = kb._create_chunks(conn)
    conn.close()

    assert count2 == 0  # second run finds nothing new


def test_file_header_chunk_for_symbolless_file(session):
    """A file with no symbols should still get a file_header chunk."""
    header_only = "-- just a sql file\nSELECT 1;\n"
    tmp_sql = Path(session.artifact_dir) / "query.sql"
    tmp_sql.write_text(header_only)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)

    conn_std = stdlib_sqlite3.connect(db_path)
    conn_std.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
        (session.session_id, str(tmp_sql), "query.sql", "sql", 30, 2, 1, time.time()),
    )
    conn_std.commit()
    conn_std.close()

    monkeypatch_needed = False  # no build call — calling _create_chunks directly
    kb = KnowledgeBuilder(session)
    conn = _vec_conn(db_path)
    _ensure_vec_table(conn)
    created = kb._create_chunks(conn)
    conn.close()

    assert created >= 1
    check = stdlib_sqlite3.connect(db_path)
    chunk_types = [r[0] for r in check.execute(
        "SELECT chunk_type FROM code_chunk WHERE session_id=?",
        (session.session_id,),
    ).fetchall()]
    check.close()
    assert "file_header" in chunk_types
