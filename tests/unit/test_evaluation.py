"""Unit tests for core/evaluation.py — adversarial evaluator."""

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alarmv3.core.evaluation import (
    RecommendationEvaluator,
    _fallback_evaluations,
    _parse_evaluations,
)
from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager


# ── _parse_evaluations ────────────────────────────────────────────────────────

def test_parse_valid_array():
    data = [{"rank": 1, "critique": "OK", "risk_score": 2, "evaluator_effort": "M", "verdict": "accept"}]
    assert _parse_evaluations(json.dumps(data)) == data


def test_parse_embedded_in_text():
    text = 'Analysis complete:\n[{"rank":1,"verdict":"revise"}]\nDone.'
    result = _parse_evaluations(text)
    assert len(result) == 1
    assert result[0]["verdict"] == "revise"


def test_parse_empty():
    assert _parse_evaluations("[]") == []


def test_parse_malformed_returns_empty():
    assert _parse_evaluations("not json") == []


def test_parse_no_brackets_returns_empty():
    assert _parse_evaluations('{"rank": 1}') == []


# ── _fallback_evaluations ─────────────────────────────────────────────────────

def test_fallback_preserves_ranks():
    recs = [{"rank": 1, "title": "A"}, {"rank": 2, "title": "B"}]
    result = _fallback_evaluations(recs)
    assert len(result) == 2
    assert result[0]["rank"] == 1
    assert result[1]["rank"] == 2


def test_fallback_verdict_is_pending():
    recs = [{"rank": 1}]
    result = _fallback_evaluations(recs)
    assert result[0]["verdict"] == "pending"


def test_fallback_none_scores():
    recs = [{"rank": 1}]
    result = _fallback_evaluations(recs)
    assert result[0]["risk_score"] is None
    assert result[0]["evaluator_effort"] is None


def test_fallback_empty_input():
    assert _fallback_evaluations([]) == []


# ── RecommendationEvaluator fixtures ─────────────────────────────────────────

@pytest.fixture()
def eval_session(tmp_path):
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")
    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)

    conn = sqlite3.connect(db)
    now = time.time()
    conn.execute(
        "INSERT INTO recommendation("
        "session_id, rank, category, severity, title, description, "
        "affected_files, effort, rationale, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session.session_id, 1, "security", "high", "Fix TLS", "Update TLS 1.0",
         "[]", "M", "Exploitable", now),
    )
    conn.execute(
        "INSERT INTO recommendation("
        "session_id, rank, category, severity, title, description, "
        "affected_files, effort, rationale, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session.session_id, 2, "modernization", "medium", "Refactor DB", "Split layer",
         "[]", "L", "Maintainability", now),
    )
    conn.commit()
    conn.close()
    return session


# ── store_evaluations ─────────────────────────────────────────────────────────

def test_store_evaluations_writes_to_db(eval_session):
    evaluations = [
        {"rank": 1, "critique": "Missing cert pinning.", "risk_score": 4,
         "evaluator_effort": "L", "verdict": "revise"},
        {"rank": 2, "critique": "No significant issues.", "risk_score": 2,
         "evaluator_effort": "L", "verdict": "accept"},
    ]
    evaluator = RecommendationEvaluator(eval_session)
    evaluator.store_evaluations(evaluations)

    db = eval_session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT evaluator_critique, risk_score, evaluator_verdict "
        "FROM recommendation WHERE session_id=? AND rank=1",
        (eval_session.session_id,),
    ).fetchone()
    conn.close()
    assert row[0] == "Missing cert pinning."
    assert row[1] == 4
    assert row[2] == "revise"


def test_store_evaluations_empty_is_noop(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    evaluator.store_evaluations([])  # must not raise


# ── get_evaluated_recommendations ────────────────────────────────────────────

def test_get_evaluated_recommendations_returns_all(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    result = evaluator.get_evaluated_recommendations()
    assert len(result) == 2
    assert result[0]["rank"] == 1
    assert result[1]["rank"] == 2


def test_get_evaluated_affected_files_is_list(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    result = evaluator.get_evaluated_recommendations()
    assert isinstance(result[0]["affected_files"], list)


def test_get_evaluated_includes_evaluator_fields(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    result = evaluator.get_evaluated_recommendations()
    for rec in result:
        assert "evaluator_verdict" in rec
        assert "review_status" in rec


# ── evaluate — mocked Claude call ────────────────────────────────────────────

def test_evaluate_returns_list_of_same_length(eval_session):
    fake_evaluations = [
        {"rank": 1, "critique": "OK", "risk_score": 2, "evaluator_effort": "M", "verdict": "accept"},
        {"rank": 2, "critique": "Vague.", "risk_score": 3, "evaluator_effort": "XL", "verdict": "revise"},
    ]
    evaluator = RecommendationEvaluator(eval_session)
    with patch.object(evaluator, "_call_claude", return_value=fake_evaluations):
        recs = [{"rank": 1}, {"rank": 2}]
        result = evaluator.evaluate(recs, {})
    assert len(result) == 2
    assert result[0]["verdict"] == "accept"


def test_evaluate_falls_back_on_claude_error(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    with patch.object(evaluator, "_call_claude", side_effect=RuntimeError("API down")):
        recs = [{"rank": 1}, {"rank": 2}]
        result = evaluator.evaluate(recs, {})
    assert len(result) == 2
    assert all(r["verdict"] == "pending" for r in result)


def test_evaluate_empty_recommendations(eval_session):
    evaluator = RecommendationEvaluator(eval_session)
    assert evaluator.evaluate([], {}) == []


# ── Evaluator system prompt ───────────────────────────────────────────────────

from alarmv3.core.evaluation import _EVALUATOR_SYSTEM_PROMPT


def test_evaluator_prompt_is_adversarial():
    assert "FIND PROBLEMS" in _EVALUATOR_SYSTEM_PROMPT


def test_evaluator_prompt_mentions_verdicts():
    for verdict in ("accept", "revise", "reject"):
        assert verdict in _EVALUATOR_SYSTEM_PROMPT


def test_evaluator_prompt_mentions_risk_score():
    assert "risk_score" in _EVALUATOR_SYSTEM_PROMPT
