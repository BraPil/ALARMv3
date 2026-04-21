"""Integration: plan → implement → accept pipeline on sample_repo (mocked Claude)."""

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
    clone_source_to_target,
)
from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture()
def full_session(tmp_path):
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    source = SAMPLE_REPO if SAMPLE_REPO.exists() else tmp_path / "src"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.cpp").write_text("int main() { return 0; }\n") if not SAMPLE_REPO.exists() else None

    session.set_source(source)
    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)

    conn = sqlite3.connect(db)
    now = time.time()
    conn.execute(
        "INSERT INTO recommendation("
        "session_id, rank, category, severity, title, description, "
        "affected_files, effort, rationale, created_at, review_status, approved) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (session.session_id, 1, "security", "high", "Replace TLS 1.0",
         "Update TLS version in network layer.", '["main.cpp"]',
         "M", "Exploitable", now, "accepted", 1),
    )
    conn.commit()
    conn.close()

    for state in [
        SessionState.ATTACHED,
        SessionState.READ_ONLY_CONFIRMED,
        SessionState.ANALYSIS_IN_PROGRESS,
        SessionState.RECOMMENDATIONS_PENDING_REVIEW,
        SessionState.ANALYSIS_COMPLETE,
    ]:
        session.transition_to(state)
    return session


# ── Plan creation ─────────────────────────────────────────────────────────────

def test_plan_creation_from_accepted_recs(full_session):
    result = ImplementationPlanner(full_session).create_plan([1])
    assert result["plan_item_count"] == 1
    assert result["order"][0]["rank"] == 1


def test_plan_stored_in_db(full_session):
    ImplementationPlanner(full_session).create_plan([1])
    plan = ImplementationPlanner(full_session).get_plan()
    assert len(plan) == 1
    assert plan[0]["status"] == "pending"
    assert plan[0]["title"] == "Replace TLS 1.0"


# ── Clone + implement ─────────────────────────────────────────────────────────

def test_clone_and_implement_pipeline(full_session, tmp_path):
    """Full pipeline: plan → clone → implement_next → accept."""
    session = full_session
    target_path = tmp_path / "working_copy"

    ImplementationPlanner(session).create_plan([1])
    session.transition_to(SessionState.IMPLEMENTATION_PLANNED)

    clone_source_to_target(session.source_path, target_path)
    session.set_metadata("target_path", str(target_path))
    session.transition_to(SessionState.WORKING_REPO_READY)

    mock_plan = {"summary": "Update TLS", "steps": ["Replace TLS 1.0 calls"], "files_to_modify": ["main.cpp"], "risks": "minimal"}
    mock_diff = ""  # empty diff → no patch applied, but still committed
    mock_eval = {"verdict": "approve", "critique": "Looks correct.", "risk_level": 1}

    call_count = 0
    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        text = json.dumps(mock_plan) if call_count == 1 else (mock_diff if call_count == 2 else json.dumps(mock_eval))
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        return resp

    runner = ImplementationRunner(session)
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        impl_result = runner.run_next()

    assert "change_id" in impl_result
    assert impl_result["eval_verdict"] == "approve"

    accept_result = runner.accept_change(impl_result["change_id"])
    assert accept_result["status"] == "accepted"

    # Plan item should now be complete
    plan = ImplementationPlanner(session).get_plan()
    assert plan[0]["status"] == "complete"


def test_reject_and_retry_injects_feedback(full_session, tmp_path):
    """Reject a change, then implement_next retries with feedback in context."""
    session = full_session
    target_path = tmp_path / "working_copy"
    ImplementationPlanner(session).create_plan([1])
    session.transition_to(SessionState.IMPLEMENTATION_PLANNED)
    clone_source_to_target(session.source_path, target_path)
    session.set_metadata("target_path", str(target_path))
    session.transition_to(SessionState.WORKING_REPO_READY)

    captured_contents = []

    def mock_create(**kwargs):
        for msg in kwargs.get("messages", []):
            captured_contents.append(msg.get("content", ""))
        resp = MagicMock()
        resp.content = [MagicMock(text='{"summary":"x","steps":[],"files_to_modify":[],"risks":"none"}')]
        return resp

    runner = ImplementationRunner(session)

    # First attempt
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        result1 = runner.run_next()

    runner.reject_change(result1["change_id"], "Must use TLS 1.3 not TLS 1.2.")

    captured_contents.clear()

    # Retry
    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        runner.run_next()

    # Feedback should appear in the planner's context on retry
    assert any("TLS 1.3" in c for c in captured_contents)


def test_all_pending_returns_no_items(full_session, tmp_path):
    session = full_session
    target_path = tmp_path / "working_copy"
    ImplementationPlanner(session).create_plan([1])
    session.transition_to(SessionState.IMPLEMENTATION_PLANNED)
    clone_source_to_target(session.source_path, target_path)
    session.set_metadata("target_path", str(target_path))
    session.transition_to(SessionState.WORKING_REPO_READY)

    # Mark all plan items complete manually
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE implementation_plan SET status='complete' WHERE session_id=?",
        (session.session_id,),
    )
    conn.commit()
    conn.close()

    runner = ImplementationRunner(session)
    result = runner.run_next()
    assert result["status"] == "no_pending_items"


# ── State gate enforcement ────────────────────────────────────────────────────

def test_plan_requires_analysis_complete(full_session):
    """plan_implementation must be blocked unless state is ANALYSIS_COMPLETE."""
    from alarmv3.core.guardrails import GuardrailViolation
    # Session is already at ANALYSIS_COMPLETE — transition back to test gate
    session = full_session
    session.transition_to(SessionState.IMPLEMENTATION_PLANNED)
    with pytest.raises(GuardrailViolation):
        session.guardrails.require_state(session.state, SessionState.ANALYSIS_COMPLETE)


def test_working_repo_ready_in_transitions():
    from alarmv3.core.guardrails import GuardrailsManager, SessionState
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        g = GuardrailsManager(pathlib.Path(td))
        g.transition(SessionState.IMPLEMENTATION_PLANNED, SessionState.WORKING_REPO_READY)
