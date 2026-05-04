"""Unit tests for core/autopilot.py — policy-aware auto-acceptance.

Covers the new AutopilotPolicy.apply_to_session() and policy_file_exists
introduced for P0 #2 of the post-mortem plan. The two-stage filter is:
  (1) evaluator_verdict must be 'accept'
  (2) of those, the policy's should_auto_accept() must return True
"""

import sqlite3
import time

import pytest
import yaml

from alarmv3.core.autopilot import AutopilotPolicy
from alarmv3.core.guardrails import SessionState
from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_recs(session, recs: list[dict]):
    """Insert recommendations into the session DB.

    Each rec dict supports: rank, category, severity, evaluator_verdict,
    risk_score, evaluator_effort. Defaults are filled in.
    """
    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    now = time.time()
    for rec in recs:
        conn.execute(
            "INSERT INTO recommendation("
            "session_id, rank, category, severity, title, description, "
            "affected_files, effort, rationale, created_at, "
            "evaluator_verdict, risk_score, evaluator_effort) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session.session_id,
                rec["rank"],
                rec.get("category", "modernization"),
                rec.get("severity", "medium"),
                f"Rec {rec['rank']}",
                "Desc",
                "[]",
                rec.get("effort", "M"),
                "rationale",
                now,
                rec.get("evaluator_verdict", "accept"),
                rec.get("risk_score", 2),
                rec.get("evaluator_effort", "M"),
            ),
        )
    conn.commit()
    conn.close()


def _session(tmp_path):
    sm = SessionManager(tmp_path)
    s = sm.get_or_create()
    s.set_source(tmp_path / "src")
    s.transition_to(SessionState.ATTACHED)
    s.transition_to(SessionState.READ_ONLY_CONFIRMED)
    s.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
    s.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)
    return s


def _write_policy(alarm_dir, body: dict):
    p = alarm_dir / "policy" / "autopilot.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(body))


def _accepted_ranks(session) -> set[int]:
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT rank FROM recommendation WHERE session_id=? AND review_status='accepted'",
        (session.session_id,),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── policy_file_exists ────────────────────────────────────────────────────────


def test_policy_file_exists_false_without_file(tmp_path):
    p = AutopilotPolicy(tmp_path / ".alarmv3")
    assert p.policy_file_exists is False


def test_policy_file_exists_true_after_init_template(tmp_path):
    p = AutopilotPolicy(tmp_path / ".alarmv3")
    p.init_template()
    assert p.policy_file_exists is True


# ── apply_to_session — verdict gate ───────────────────────────────────────────


def test_apply_skips_recs_with_verdict_revise(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {
        "enabled": True,
        "rules": [{"category": "modernization", "max_risk_level": 5, "max_effort": "XL"}],
    })
    _seed_recs(s, [
        {"rank": 1, "evaluator_verdict": "accept"},
        {"rank": 2, "evaluator_verdict": "revise"},
        {"rank": 3, "evaluator_verdict": "reject"},
    ])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)

    assert _accepted_ranks(s) == {1}
    assert {r["rank"] for r in summary["accepted"]} == {1}
    assert {r["rank"] for r in summary["skipped_by_verdict"]} == {2, 3}
    assert summary["skipped_by_policy"] == []


def test_apply_skips_pending_verdict(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": True, "rules": [
        {"category": "modernization", "max_risk_level": 5, "max_effort": "XL"},
    ]})
    _seed_recs(s, [{"rank": 1, "evaluator_verdict": "pending"}])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == set()
    assert {r["rank"] for r in summary["skipped_by_verdict"]} == {1}


# ── apply_to_session — policy gate ────────────────────────────────────────────


def test_apply_skips_when_policy_disabled(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": False, "rules": []})
    _seed_recs(s, [{"rank": 1, "evaluator_verdict": "accept"}])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == set()
    assert {r["rank"] for r in summary["skipped_by_policy"]} == {1}
    assert summary["accepted"] == []


def test_apply_skips_when_no_policy_file(tmp_path):
    """Safe-default: no file → autopilot disabled → nothing accepted."""
    s = _session(tmp_path)
    # Deliberately do not write a policy file.
    _seed_recs(s, [{"rank": 1, "evaluator_verdict": "accept"}])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == set()
    assert {r["rank"] for r in summary["skipped_by_policy"]} == {1}


def test_apply_respects_max_risk_level(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": True, "rules": [
        {"category": "modernization", "max_risk_level": 2, "max_effort": "L"},
    ]})
    _seed_recs(s, [
        {"rank": 1, "evaluator_verdict": "accept", "risk_score": 1},
        {"rank": 2, "evaluator_verdict": "accept", "risk_score": 3},  # over max_risk
    ])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == {1}
    assert {r["rank"] for r in summary["skipped_by_policy"]} == {2}


def test_apply_respects_max_effort(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": True, "rules": [
        {"category": "modernization", "max_risk_level": 5, "max_effort": "M"},
    ]})
    _seed_recs(s, [
        {"rank": 1, "evaluator_verdict": "accept", "evaluator_effort": "S"},
        {"rank": 2, "evaluator_verdict": "accept", "evaluator_effort": "L"},  # over max_effort
    ])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == {1}
    assert {r["rank"] for r in summary["skipped_by_policy"]} == {2}


def test_apply_skips_when_no_matching_category_rule(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": True, "rules": [
        {"category": "quality", "max_risk_level": 5, "max_effort": "XL"},  # different category
    ]})
    _seed_recs(s, [{"rank": 1, "evaluator_verdict": "accept", "category": "security"}])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == set()
    assert {r["rank"] for r in summary["skipped_by_policy"]} == {1}


# ── apply_to_session — happy path ─────────────────────────────────────────────


def test_apply_accepts_when_verdict_and_policy_match(tmp_path):
    s = _session(tmp_path)
    _write_policy(s.alarm_dir, {"enabled": True, "rules": [
        {"category": "modernization", "max_risk_level": 3, "max_effort": "M",
         "description": "auto-accept low risk modernization"},
    ]})
    _seed_recs(s, [
        {"rank": 1, "evaluator_verdict": "accept", "risk_score": 2,
         "evaluator_effort": "M", "category": "modernization"},
    ])

    summary = AutopilotPolicy(s.alarm_dir).apply_to_session(s)
    assert _accepted_ranks(s) == {1}
    assert summary["accepted"][0]["rule"] == "auto-accept low risk modernization"
