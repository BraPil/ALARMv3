"""Integration tests — full attach → map → analyze pipeline.

Uses tests/fixtures/sample_repo (C++, VB.NET files) as the source.
No LLM calls; synthesis is not exercised here.
"""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alarmv3.core.guardrails import SessionState
from alarmv3.core.session import SessionManager
from alarmv3.core.discovery import FileScanner
from alarmv3.core.analysis import Analyzer

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture()
def workspace(tmp_path):
    return tmp_path


@pytest.fixture()
def session(workspace):
    sm = SessionManager(workspace)
    s = sm.get_or_create()
    s.set_source(SAMPLE_REPO)
    return s


# ── Discovery phase ───────────────────────────────────────────────────────────

def test_scanner_discovers_all_files(session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        total = FileScanner(SAMPLE_REPO, session).scan(pool, "job-map")

    # fixture has: main.cpp, utils.cpp, utils.h, Module1.vb
    assert total == 4


def test_manifest_populated(session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "job-map")

    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT relative_path, language, is_eligible FROM manifest WHERE session_id=?",
        (session.session_id,),
    ).fetchall()
    conn.close()

    langs = {r["relative_path"]: r["language"] for r in rows}
    assert langs.get("main.cpp") == "cpp"
    assert langs.get("utils.cpp") == "cpp"
    assert langs.get("utils.h") == "cpp"
    assert langs.get("Module1.vb") == "vbnet"

    eligible = [r["relative_path"] for r in rows if r["is_eligible"]]
    assert len(eligible) == 4


def test_cpp_files_enqueued_with_priority(session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "job-map")

    stats = session.queue_stats("analysis")
    assert sum(stats.values()) == 4
    assert stats.get("pending", 0) == 4


def test_mapping_sets_metadata(session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "job-map")

    assert session.get_metadata()["manifest_file_count"] == 4


# ── Analysis phase ────────────────────────────────────────────────────────────

@pytest.fixture()
def mapped_session(session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "job-map")
    return session


def test_analysis_runs_all_files(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        stats = Analyzer(mapped_session).run(pool, "job-analyze")

    assert stats["files_analyzed"] == 4
    assert stats["files_failed"] == 0


def test_cpp_symbols_extracted(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(mapped_session).run(pool, "job-analyze")

    db = mapped_session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM symbol WHERE session_id=?",
        (mapped_session.session_id,),
    ).fetchall()}
    conn.close()

    # main.cpp defines main(); utils.cpp/utils.h define Helper class and run()
    assert "main" in names
    assert "Helper" in names


def test_vbnet_symbols_extracted(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(mapped_session).run(pool, "job-analyze")

    db = mapped_session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM symbol WHERE session_id=?",
        (mapped_session.session_id,),
    ).fetchall()}
    conn.close()

    assert "Module1" in names
    assert "Application" in names
    assert "Run" in names


def test_complexity_metrics_written(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(mapped_session).run(pool, "job-analyze")

    db = mapped_session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM complexity_metric WHERE session_id=?",
        (mapped_session.session_id,),
    ).fetchone()[0]
    conn.close()

    # 4 files × 2 metrics (loc + total_lines) = 8
    assert count == 8


def test_cpp_includes_written_as_dependencies(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(mapped_session).run(pool, "job-analyze")

    db = mapped_session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    modules = {r[0] for r in conn.execute(
        "SELECT target_module FROM dependency_edge WHERE session_id=?",
        (mapped_session.session_id,),
    ).fetchall()}
    conn.close()

    assert "iostream" in modules
    assert "utils.h" in modules


def test_work_queue_drained_after_analysis(mapped_session):
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(mapped_session).run(pool, "job-analyze")

    stats = mapped_session.queue_stats("analysis")
    assert stats.get("pending", 0) == 0
    assert stats.get("running", 0) == 0
    assert stats.get("complete", 0) == 4


# ── Full state-machine walk ───────────────────────────────────────────────────

def test_state_machine_full_walk(workspace):
    """Walk through every Phase 1 state transition end-to-end."""
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    assert session.state == SessionState.UNATTACHED

    session.set_source(SAMPLE_REPO)
    session.transition_to(SessionState.ATTACHED)
    assert session.state == SessionState.ATTACHED

    session.transition_to(SessionState.READ_ONLY_CONFIRMED)

    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        FileScanner(SAMPLE_REPO, session).scan(pool, "map")
    with ThreadPoolExecutor(max_workers=2) as pool:
        Analyzer(session).run(pool, "analyze")

    session.transition_to(SessionState.ANALYSIS_COMPLETE)
    assert session.state == SessionState.ANALYSIS_COMPLETE

    # Verify state persisted across a fresh SessionManager lookup
    reloaded = SessionManager(workspace).get()
    assert reloaded.state == SessionState.ANALYSIS_COMPLETE
