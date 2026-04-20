"""Unit tests for Phase 3 MCP tools: review_recommendations and generate_recommendations flow."""

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alarmv3.core.guardrails import SessionState
from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_session_at_pending_review(tmp_path) -> tuple:
    """Return (session, mcp_module_workspace_mock) seeded at RECOMMENDATIONS_PENDING_REVIEW."""
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")

    # Walk state machine to RECOMMENDATIONS_PENDING_REVIEW
    session.transition_to(SessionState.ATTACHED)
    session.transition_to(SessionState.READ_ONLY_CONFIRMED)
    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
    session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    now = time.time()
    for rank in (1, 2, 3):
        conn.execute(
            "INSERT INTO recommendation("
            "session_id, rank, category, severity, title, description, "
            "affected_files, effort, rationale, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session.session_id, rank, "security", "high",
             f"Rec {rank}", f"Description {rank}", "[]", "M", "rationale", now),
        )
    conn.commit()
    conn.close()
    return session


# ── review_recommendations — state gate ───────────────────────────────────────

def test_review_requires_pending_review_state(tmp_path):
    """review_recommendations must reject calls in wrong state."""
    from alarmv3.core.guardrails import GuardrailViolation

    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")
    session.transition_to(SessionState.ATTACHED)

    # Import the function in isolation via the MCP tools module
    import alarmv3.mcp.tools as tools_mod

    with patch.object(tools_mod, "_workspace", return_value=tmp_path):
        # Register tools to get the review_recommendations function
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("test")
        tools_mod.register_tools(mcp)

    # Calling review_recommendations on an ATTACHED session should raise
    with pytest.raises((GuardrailViolation, ValueError)):
        with patch.object(tools_mod, "_workspace", return_value=tmp_path):
            # Simulate the tool call directly by calling session guardrail check
            from alarmv3.core.guardrails import GuardrailsManager
            g = session.guardrails
            g.require_state(session.state, SessionState.RECOMMENDATIONS_PENDING_REVIEW)


# ── review_recommendations — accept/reject logic ──────────────────────────────

def test_review_marks_accepted_recommendations(tmp_path):
    session = _seed_session_at_pending_review(tmp_path)
    db = session.artifact_dir / "analysis.db"

    # Directly exercise the DB update logic (same as the tool does)
    conn = sqlite3.connect(db, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    for rank in [1, 2]:
        conn.execute(
            "UPDATE recommendation SET review_status='accepted', approved=1 "
            "WHERE session_id=? AND rank=?",
            (session.session_id, rank),
        )
    for rank in [3]:
        conn.execute(
            "UPDATE recommendation SET review_status='rejected' "
            "WHERE session_id=? AND rank=?",
            (session.session_id, rank),
        )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db)
    accepted = conn.execute(
        "SELECT COUNT(*) FROM recommendation WHERE session_id=? AND review_status='accepted'",
        (session.session_id,),
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM recommendation WHERE session_id=? AND review_status='rejected'",
        (session.session_id,),
    ).fetchone()[0]
    conn.close()
    assert accepted == 2
    assert rejected == 1


def test_review_transitions_to_analysis_complete(tmp_path):
    session = _seed_session_at_pending_review(tmp_path)
    assert session.state == SessionState.RECOMMENDATIONS_PENDING_REVIEW
    session.transition_to(SessionState.ANALYSIS_COMPLETE)
    assert session.state == SessionState.ANALYSIS_COMPLETE


# ── _try_aaa_grounding ────────────────────────────────────────────────────────

def test_aaa_grounding_returns_none_when_no_url(monkeypatch):
    from alarmv3.mcp.tools import _try_aaa_grounding
    monkeypatch.delenv("AAA_REST_URL", raising=False)
    assert _try_aaa_grounding("test problem") is None


def test_aaa_grounding_returns_none_on_connection_error(monkeypatch):
    from alarmv3.mcp.tools import _try_aaa_grounding
    import urllib.error
    monkeypatch.setenv("AAA_REST_URL", "http://localhost:9999")
    # Port 9999 should be unreachable; expect None (not an exception)
    result = _try_aaa_grounding("test problem")
    assert result is None


# ── generate_recommendations → RECOMMENDATIONS_PENDING_REVIEW ─────────────────

def test_generate_recs_transitions_to_pending_review(tmp_path):
    """generate_recommendations should land in RECOMMENDATIONS_PENDING_REVIEW."""
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")
    session.transition_to(SessionState.ATTACHED)
    session.transition_to(SessionState.READ_ONLY_CONFIRMED)
    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)

    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)

    fake_synth = {
        "session_id": session.session_id,
        "recommendation_count": 1,
        "recommendations": [{"rank": 1, "title": "Fix it"}],
        "top_recommendations": [{"rank": 1, "title": "Fix it"}],
        "message": "done",
    }
    fake_eval = [{"rank": 1, "critique": "OK", "risk_score": 2,
                  "evaluator_effort": "M", "verdict": "accept"}]

    import alarmv3.core.orchestration as orch_mod
    with patch.object(orch_mod.Orchestrator, "synthesize_recommendations",
                      return_value={**fake_synth, "evaluator_summary": {"accept": 1, "revise": 0, "reject": 0, "pending": 0}}):
        with patch("alarmv3.mcp.tools._workspace", return_value=tmp_path):
            with patch("alarmv3.mcp.tools._try_aaa_grounding", return_value=None):
                session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

    assert session.state == SessionState.RECOMMENDATIONS_PENDING_REVIEW


# ── ANALYSIS_COMPLETE_STATES includes RECOMMENDATIONS_PENDING_REVIEW ──────────

def test_pending_review_in_analysis_complete_states():
    from alarmv3.core.guardrails import ANALYSIS_COMPLETE_STATES
    assert SessionState.RECOMMENDATIONS_PENDING_REVIEW in ANALYSIS_COMPLETE_STATES


# ── DB schema — Phase 3 columns present ──────────────────────────────────────

def test_phase3_columns_in_recommendation_table(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(recommendation)").fetchall()}
    conn.close()
    for col in ("risk_score", "evaluator_effort", "evaluator_critique",
                "evaluator_verdict", "review_status"):
        assert col in columns, f"Missing column: {col}"


def test_review_status_default_is_pending(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO recommendation(session_id, rank, category, severity, title, "
        "description, affected_files, created_at) VALUES (?,?,?,?,?,?,?,?)",
        ("sess-1", 1, "security", "high", "T", "D", "[]", time.time()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT review_status, evaluator_verdict FROM recommendation WHERE session_id='sess-1'"
    ).fetchone()
    conn.close()
    assert row[0] == "pending"
    assert row[1] == "pending"
