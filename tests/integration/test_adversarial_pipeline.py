"""Integration test: synthesis → evaluation → review pipeline.

Tests the full Phase 3 flow on sample_repo without calling real Claude APIs.
Claude calls are mocked at the Anthropic client level.
"""

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alarmv3.core.guardrails import SessionState
from alarmv3.core.index import init_analysis_db
from alarmv3.core.orchestration import Orchestrator, _tally_verdicts
from alarmv3.core.session import SessionManager


SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture()
def session_at_analysis(tmp_path):
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    source = SAMPLE_REPO if SAMPLE_REPO.exists() else tmp_path / "src"
    source.mkdir(parents=True, exist_ok=True)
    session.set_source(source)
    session.transition_to(SessionState.ATTACHED)
    session.transition_to(SessionState.READ_ONLY_CONFIRMED)
    session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)

    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)

    # Seed minimal manifest + metrics so _build_context doesn't return zeros
    conn = sqlite3.connect(db)
    now = time.time()
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
        (session.session_id, str(source / "main.cpp"), "main.cpp", "cpp", 800, 60, 1, now),
    )
    conn.execute(
        "INSERT INTO complexity_metric(session_id, file_path, metric_name, metric_value, computed_at) "
        "VALUES (?,?,?,?,?)",
        (session.session_id, str(source / "main.cpp"), "loc", 60.0, now),
    )
    conn.execute(
        "INSERT INTO symbol(session_id, file_path, name, symbol_type) VALUES (?,?,?,?)",
        (session.session_id, str(source / "main.cpp"), "main", "function"),
    )
    conn.commit()
    conn.close()
    return session


# ── _tally_verdicts ────────────────────────────────────────────────────────────

def test_tally_verdicts_counts_correctly():
    evals = [
        {"verdict": "accept"},
        {"verdict": "revise"},
        {"verdict": "accept"},
        {"verdict": "reject"},
    ]
    tally = _tally_verdicts(evals)
    assert tally["accept"] == 2
    assert tally["revise"] == 1
    assert tally["reject"] == 1


def test_tally_verdicts_empty():
    assert _tally_verdicts([]) == {"accept": 0, "revise": 0, "reject": 0, "pending": 0}


def test_tally_verdicts_all_pending():
    evals = [{"verdict": "pending"}, {"verdict": "pending"}]
    tally = _tally_verdicts(evals)
    assert tally["pending"] == 2


# ── Full pipeline with mocked Claude ─────────────────────────────────────────

MOCK_RECOMMENDATIONS = [
    {
        "rank": 1, "category": "security", "severity": "high",
        "title": "Replace deprecated TLS 1.0",
        "description": "TLS 1.0 is end-of-life.",
        "affected_files": ["main.cpp"], "effort": "M",
        "rationale": "Exploitable vulnerability.",
    },
    {
        "rank": 2, "category": "modernization", "severity": "medium",
        "title": "Extract data access layer",
        "description": "Business logic mixed with DB queries.",
        "affected_files": ["main.cpp"], "effort": "L",
        "rationale": "Maintainability.",
    },
]

MOCK_EVALUATIONS = [
    {
        "rank": 1, "critique": "Effort underestimated; 12 call sites affected.",
        "risk_score": 4, "evaluator_effort": "L", "verdict": "revise",
    },
    {
        "rank": 2, "critique": "No significant issues.",
        "risk_score": 2, "evaluator_effort": "L", "verdict": "accept",
    },
]


def _make_claude_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def test_full_synthesis_evaluate_pipeline(session_at_analysis):
    """Synthesis → evaluator → both sets of results stored in DB."""
    session = session_at_analysis

    synth_response = _make_claude_response(json.dumps(MOCK_RECOMMENDATIONS))
    eval_response = _make_claude_response(json.dumps(MOCK_EVALUATIONS))

    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        return synth_response if call_count == 1 else eval_response

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        result = Orchestrator(session).synthesize_recommendations()

    assert result["recommendation_count"] == 2
    assert "evaluator_summary" in result
    assert result["evaluator_summary"]["revise"] == 1
    assert result["evaluator_summary"]["accept"] == 1

    # Verify DB state
    conn = sqlite3.connect(session.artifact_dir / "analysis.db")
    rows = conn.execute(
        "SELECT rank, evaluator_verdict, evaluator_critique, risk_score "
        "FROM recommendation WHERE session_id=? ORDER BY rank",
        (session.session_id,),
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][1] == "revise"
    assert rows[1][1] == "accept"
    assert rows[0][3] == 4  # risk_score


def test_pipeline_survives_evaluator_failure(session_at_analysis):
    """If evaluator Claude call fails, synthesis result is still stored."""
    session = session_at_analysis

    synth_response = _make_claude_response(json.dumps(MOCK_RECOMMENDATIONS))
    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return synth_response
        raise RuntimeError("Evaluator API timeout")

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        result = Orchestrator(session).synthesize_recommendations()

    # Synthesis must succeed; evaluator degraded gracefully
    assert result["recommendation_count"] == 2

    conn = sqlite3.connect(session.artifact_dir / "analysis.db")
    count = conn.execute(
        "SELECT COUNT(*) FROM recommendation WHERE session_id=?",
        (session.session_id,),
    ).fetchone()[0]
    conn.close()
    assert count == 2


def test_review_accept_reject_updates_db(session_at_analysis):
    """After synthesis, accepting rank 1 and rejecting rank 2 updates review_status."""
    session = session_at_analysis

    synth_response = _make_claude_response(json.dumps(MOCK_RECOMMENDATIONS))
    eval_response = _make_claude_response(json.dumps(MOCK_EVALUATIONS))
    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        return synth_response if call_count == 1 else eval_response

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        Orchestrator(session).synthesize_recommendations()

    session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "UPDATE recommendation SET review_status='accepted', approved=1 "
        "WHERE session_id=? AND rank=1", (session.session_id,)
    )
    conn.execute(
        "UPDATE recommendation SET review_status='rejected' "
        "WHERE session_id=? AND rank=2", (session.session_id,)
    )
    conn.commit()
    conn.close()

    session.transition_to(SessionState.ANALYSIS_COMPLETE)
    assert session.state == SessionState.ANALYSIS_COMPLETE

    conn = sqlite3.connect(db)
    statuses = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT rank, review_status FROM recommendation WHERE session_id=?",
            (session.session_id,),
        ).fetchall()
    }
    conn.close()
    assert statuses[1] == "accepted"
    assert statuses[2] == "rejected"


def test_aaa_grounding_injected_into_context(session_at_analysis):
    """If AAA grounding is provided, it appears in the synthesis context."""
    session = session_at_analysis

    captured_contexts = []

    def mock_create(**kwargs):
        # Capture the user message content
        for msg in kwargs.get("messages", []):
            if msg.get("role") == "user":
                captured_contexts.append(msg.get("content", ""))
        return _make_claude_response(json.dumps(MOCK_RECOMMENDATIONS[:1]))

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = mock_create
        from alarmv3.core.synthesis import Synthesizer
        Synthesizer(session).run(aaa_grounding="Use event-driven architecture.")

    assert any("aaa_architecture_grounding" in c for c in captured_contexts)
