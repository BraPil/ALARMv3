"""Unit tests for core/implementation.py — planner, runner, helpers."""

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alarmv3.core.guardrails import SessionState
from alarmv3.core.implementation import (
    ImplementationPlanner,
    ImplementationRunner,
    _format_files,
    _format_rec,
    _load_file_contents,
    _order_by_dependency,
    _parse_json_response,
    clone_source_to_target,
)
from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def session_with_accepted_recs(tmp_path):
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")
    (tmp_path / "src").mkdir()

    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    now = time.time()
    for rank, files in [(1, '["main.cpp"]'), (2, '["utils.cpp","main.cpp"]'), (3, '["db.cpp"]')]:
        conn.execute(
            "INSERT INTO recommendation("
            "session_id, rank, category, severity, title, description, "
            "affected_files, effort, rationale, created_at, review_status, approved) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (session.session_id, rank, "security", "high",
             f"Rec {rank}", f"Do thing {rank}", files, "M", "reason", now,
             "accepted", 1),
        )
    conn.commit()
    conn.close()

    session.transition_to(SessionState.ATTACHED)
    session.transition_to(SessionState.READ_ONLY_CONFIRMED)
    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
    session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)
    session.transition_to(SessionState.ANALYSIS_COMPLETE)
    return session


# ── _order_by_dependency ──────────────────────────────────────────────────────

def test_order_shared_files_first():
    recs = [
        {"rank": 1, "affected_files": ["a.cpp"]},
        {"rank": 2, "affected_files": ["a.cpp", "b.cpp"]},
        {"rank": 3, "affected_files": []},
    ]
    ordered = _order_by_dependency(recs)
    assert ordered[0]["rank"] == 2  # most files first


def test_order_same_file_count_by_rank():
    recs = [
        {"rank": 3, "affected_files": ["x.cpp"]},
        {"rank": 1, "affected_files": ["y.cpp"]},
    ]
    ordered = _order_by_dependency(recs)
    assert ordered[0]["rank"] == 1


# ── _parse_json_response ──────────────────────────────────────────────────────

def test_parse_json_valid():
    result = _parse_json_response('{"verdict": "approve"}', default={})
    assert result["verdict"] == "approve"


def test_parse_json_embedded():
    result = _parse_json_response('Some text {"verdict": "flag"} more text', default={})
    assert result["verdict"] == "flag"


def test_parse_json_malformed_returns_default():
    result = _parse_json_response("not json at all", default={"verdict": "pending"})
    assert result["verdict"] == "pending"


def test_parse_json_empty_returns_default():
    result = _parse_json_response("", default={"x": 1})
    assert result["x"] == 1


# ── _load_file_contents ───────────────────────────────────────────────────────

def test_load_file_contents_reads_existing(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    result = _load_file_contents(["main.cpp"], tmp_path)
    assert result["main.cpp"] == "int main() {}"


def test_load_file_contents_skips_missing(tmp_path):
    result = _load_file_contents(["nonexistent.cpp"], tmp_path)
    assert "nonexistent.cpp" not in result


def test_load_file_contents_empty_list(tmp_path):
    assert _load_file_contents([], tmp_path) == {}


# ── clone_source_to_target ────────────────────────────────────────────────────

def test_clone_creates_target(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.cpp").write_text("int main() {}")
    target = tmp_path / "target"
    clone_source_to_target(source, target)
    assert target.exists()
    assert (target / "main.cpp").exists()


def test_clone_target_must_not_exist(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        clone_source_to_target(source, target)


def test_clone_initializes_git(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("hello")
    target = tmp_path / "target"
    clone_source_to_target(source, target)
    assert (target / ".git").exists()


def test_clone_copies_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.cpp").write_text("// A")
    (source / "b.cpp").write_text("// B")
    target = tmp_path / "target"
    clone_source_to_target(source, target)
    assert (target / "a.cpp").read_text() == "// A"
    assert (target / "b.cpp").read_text() == "// B"


# ── ImplementationPlanner ─────────────────────────────────────────────────────

def test_create_plan_stores_items(session_with_accepted_recs):
    session = session_with_accepted_recs
    planner = ImplementationPlanner(session)
    result = planner.create_plan([1, 2, 3])

    assert result["plan_item_count"] == 3
    assert len(result["plan_ids"]) == 3


def test_create_plan_orders_by_dependency(session_with_accepted_recs):
    session = session_with_accepted_recs
    planner = ImplementationPlanner(session)
    planner.create_plan([1, 2])

    plan = planner.get_plan()
    # rec 2 has 2 files (main.cpp + utils.cpp), rec 1 has 1 file → rec 2 first
    assert plan[0]["rec_rank"] == 2
    assert plan[1]["rec_rank"] == 1


def test_create_plan_only_accepted(session_with_accepted_recs):
    session = session_with_accepted_recs
    # Mark rec 3 as rejected
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE recommendation SET review_status='rejected', approved=0 "
        "WHERE session_id=? AND rank=3", (session.session_id,)
    )
    conn.commit()
    conn.close()

    planner = ImplementationPlanner(session)
    result = planner.create_plan([1, 2, 3])
    # Rank 3 is rejected → should not appear in plan
    assert result["plan_item_count"] == 2


def test_get_plan_returns_all_items(session_with_accepted_recs):
    session = session_with_accepted_recs
    ImplementationPlanner(session).create_plan([1, 2])
    plan = ImplementationPlanner(session).get_plan()
    assert len(plan) == 2
    for item in plan:
        assert "affected_files" in item
        assert isinstance(item["affected_files"], list)


def test_get_plan_default_status_pending(session_with_accepted_recs):
    session = session_with_accepted_recs
    ImplementationPlanner(session).create_plan([1])
    plan = ImplementationPlanner(session).get_plan()
    assert plan[0]["status"] == "pending"


# ── ImplementationRunner — accept/reject ──────────────────────────────────────

@pytest.fixture()
def runner_session(tmp_path, session_with_accepted_recs):
    session = session_with_accepted_recs
    target = tmp_path / "target"
    target.mkdir()
    (target / "main.cpp").write_text("int main() { return 0; }")
    session.set_metadata("target_path", str(target))
    session.transition_to(SessionState.IMPLEMENTATION_PLANNED)
    session.transition_to(SessionState.WORKING_REPO_READY)
    return session, target


def _seed_plan_and_change(session, plan_rank=1, diff="--- a/main.cpp\n+++ b/main.cpp\n"):
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    now = time.time()
    cur = conn.execute(
        "INSERT INTO implementation_plan(session_id, rec_rank, title, affected_files, order_index, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (session.session_id, plan_rank, f"Plan item {plan_rank}", '["main.cpp"]', 0, now),
    )
    plan_id = cur.lastrowid
    cur2 = conn.execute(
        "INSERT INTO implementation_change(session_id, plan_item_id, diff_text, eval_verdict, created_at) "
        "VALUES (?,?,?,?,?)",
        (session.session_id, plan_id, diff, "approve", now),
    )
    change_id = cur2.lastrowid
    conn.commit()
    conn.close()
    return plan_id, change_id


def test_reject_change_marks_rejected(runner_session):
    session, _ = runner_session
    _, change_id = _seed_plan_and_change(session)
    runner = ImplementationRunner(session)
    result = runner.reject_change(change_id, "The diff is incomplete.")
    assert result["status"] == "rejected"


def test_reject_stores_feedback(runner_session):
    session, _ = runner_session
    _, change_id = _seed_plan_and_change(session)
    ImplementationRunner(session).reject_change(change_id, "Missing error handling.")
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    feedback = conn.execute(
        "SELECT feedback FROM implementation_change WHERE id=?", (change_id,)
    ).fetchone()[0]
    conn.close()
    assert feedback == "Missing error handling."


def test_reject_resets_plan_item_to_pending(runner_session):
    session, _ = runner_session
    plan_id, change_id = _seed_plan_and_change(session)
    ImplementationRunner(session).reject_change(change_id, "Bad diff.")
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    status = conn.execute(
        "SELECT status FROM implementation_plan WHERE id=?", (plan_id,)
    ).fetchone()[0]
    conn.close()
    assert status == "pending"


def test_accept_change_marks_accepted(runner_session):
    session, _ = runner_session
    # Empty diff — no actual patch to apply
    _, change_id = _seed_plan_and_change(session, diff="")
    result = ImplementationRunner(session).accept_change(change_id)
    assert result["status"] == "accepted"


def test_accept_change_marks_plan_complete(runner_session):
    session, _ = runner_session
    plan_id, change_id = _seed_plan_and_change(session, diff="")
    ImplementationRunner(session).accept_change(change_id)
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    status = conn.execute(
        "SELECT status FROM implementation_plan WHERE id=?", (plan_id,)
    ).fetchone()[0]
    conn.close()
    assert status == "complete"


def test_cannot_accept_already_accepted(runner_session):
    session, _ = runner_session
    _, change_id = _seed_plan_and_change(session, diff="")
    runner = ImplementationRunner(session)
    runner.accept_change(change_id)
    with pytest.raises(ValueError, match="not pending review"):
        runner.accept_change(change_id)


def test_get_changes_returns_all(runner_session):
    session, _ = runner_session
    _seed_plan_and_change(session)
    changes = ImplementationRunner(session).get_changes()
    assert len(changes) == 1
    assert "eval_verdict" in changes[0]
    assert "review_status" in changes[0]


# ── run_next — mocked Claude ──────────────────────────────────────────────────

def test_run_next_no_pending_items(runner_session):
    session, _ = runner_session
    result = ImplementationRunner(session).run_next()
    assert result["status"] == "no_pending_items"


def test_run_next_returns_diff(runner_session, tmp_path):
    session, target = runner_session
    ImplementationPlanner(session).create_plan([1])

    mock_plan = {"summary": "fix TLS", "steps": ["step1"], "files_to_modify": ["main.cpp"], "risks": "none"}
    mock_diff = "--- a/main.cpp\n+++ b/main.cpp\n@@ -1 +1 @@\n-old\n+new\n"
    mock_eval = {"verdict": "approve", "critique": "Looks good.", "risk_level": 1}

    responses = [
        json.dumps(mock_plan),
        mock_diff,
        json.dumps(mock_eval),
    ]
    call_idx = 0

    def mock_claude(**kwargs):
        nonlocal call_idx
        text = responses[min(call_idx, len(responses) - 1)]
        call_idx += 1
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        return resp

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_claude
        result = ImplementationRunner(session).run_next()

    assert "diff" in result
    assert "change_id" in result
    assert result["eval_verdict"] == "approve"


# ── Phase 4 DB schema ─────────────────────────────────────────────────────────

def test_phase4_tables_exist(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "implementation_plan" in tables
    assert "implementation_change" in tables


def test_implementation_plan_default_status(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO implementation_plan(session_id, rec_rank, title, affected_files, order_index, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("s1", 1, "Fix TLS", "[]", 0, time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT status FROM implementation_plan WHERE session_id='s1'").fetchone()
    conn.close()
    assert row[0] == "pending"
