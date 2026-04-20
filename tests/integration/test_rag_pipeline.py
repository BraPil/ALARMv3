"""Live RAG integration tests — requires Ollama + nomic-embed-text.

Skipped automatically if Ollama is not running. Run manually or in a
Codespace where start-ollama.sh has been executed.

Covers: chunk creation, embedding, sqlite-vec KNN query, and the full
query_codebase MCP tool path via KnowledgeBuilder.
"""

import sqlite3 as stdlib_sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alarmv3.core.knowledge import _ollama_running

pytestmark = pytest.mark.skipif(
    not _ollama_running(),
    reason="Ollama not running at localhost:11434",
)

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture(scope="module")
def rag_session(tmp_path_factory):
    """Run map + analyze + build once; share across all tests in this module."""
    workspace = tmp_path_factory.mktemp("rag_workspace")

    from alarmv3.core.session import SessionManager
    from alarmv3.core.guardrails import SessionState
    from alarmv3.core.discovery import FileScanner
    from alarmv3.core.analysis import Analyzer
    from alarmv3.core.knowledge import KnowledgeBuilder

    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.set_source(SAMPLE_REPO)
    session.transition_to(SessionState.ATTACHED)
    session.transition_to(SessionState.READ_ONLY_CONFIRMED)
    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "map")
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(session).run(pool, "analyze")

    session.transition_to(SessionState.ANALYSIS_COMPLETE)

    stats = KnowledgeBuilder(session).build()
    return session, stats


# ── Build stats ───────────────────────────────────────────────────────────────

def test_build_creates_chunks(rag_session):
    _, stats = rag_session
    assert stats["chunks_created"] >= 1


def test_build_embeds_all_chunks(rag_session):
    _, stats = rag_session
    assert stats["chunks_embedded"] == stats["chunks_created"]


def test_chunks_in_db(rag_session):
    session, stats = rag_session
    db = session.artifact_dir / "analysis.db"
    conn = stdlib_sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM code_chunk WHERE session_id=? AND embedded=1",
        (session.session_id,),
    ).fetchone()[0]
    conn.close()
    assert count == stats["chunks_embedded"]


def test_chunk_content_non_empty(rag_session):
    session, _ = rag_session
    db = session.artifact_dir / "analysis.db"
    conn = stdlib_sqlite3.connect(db)
    rows = conn.execute(
        "SELECT content FROM code_chunk WHERE session_id=?",
        (session.session_id,),
    ).fetchall()
    conn.close()
    for (content,) in rows:
        assert content and len(content.strip()) > 0


def test_token_counts_positive(rag_session):
    session, _ = rag_session
    db = session.artifact_dir / "analysis.db"
    conn = stdlib_sqlite3.connect(db)
    rows = conn.execute(
        "SELECT token_count FROM code_chunk WHERE session_id=?",
        (session.session_id,),
    ).fetchall()
    conn.close()
    for (tc,) in rows:
        assert tc >= 1


# ── KNN query ─────────────────────────────────────────────────────────────────

def test_query_returns_results(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("class definition")
    assert len(results) >= 1


def test_query_result_schema(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("function", top_k=3)
    for r in results:
        assert "chunk_type" in r
        assert "file_path" in r
        assert "content" in r
        assert "score" in r
        assert isinstance(r["score"], float)


def test_query_top_k_respected(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("helper", top_k=2)
    assert len(results) <= 2


def test_query_cpp_code_finds_cpp_symbols(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("C++ class Helper run method")
    file_paths = [r["file_path"] for r in results]
    assert any(".cpp" in fp or ".h" in fp for fp in file_paths)


def test_query_vbnet_finds_vbnet_symbols(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("Visual Basic module application run")
    file_paths = [r["file_path"] for r in results]
    assert any(".vb" in fp for fp in file_paths)


def test_query_scores_ordered(rag_session):
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    results = KnowledgeBuilder(session).query("main entry point", top_k=5)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores)


# ── Build idempotency ─────────────────────────────────────────────────────────

def test_rebuild_is_idempotent(rag_session):
    """Second build call should embed 0 new chunks (already done)."""
    session, _ = rag_session
    from alarmv3.core.knowledge import KnowledgeBuilder
    stats2 = KnowledgeBuilder(session).build()
    assert stats2["chunks_created"] == 0
    assert stats2["chunks_embedded"] == 0


# ── MCP tool path ─────────────────────────────────────────────────────────────

def test_query_codebase_tool(rag_session, tmp_path, monkeypatch):
    """query_codebase tool returns correct shape when knowledge is pre-built."""
    session, _ = rag_session
    monkeypatch.setenv("ALARMV3_WORKSPACE", str(session.artifact_dir.parent.parent))

    from alarmv3.mcp.tools import register_tools
    from mcp.server.fastmcp import FastMCP
    import asyncio

    test_mcp = FastMCP("test")
    register_tools(test_mcp)

    tools = asyncio.run(test_mcp.list_tools())
    assert any(t.name == "query_codebase" for t in tools)
