"""Live integration test — full pipeline including Claude API call.

Requires ANTHROPIC_API_KEY. Skipped automatically if not set.
Runs attach → map → analyze → synthesize on sample_repo and verifies
that real recommendations come back with the expected structure.
"""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.fixture(scope="module")
def live_session(tmp_path_factory):
    """Run the full pipeline once; share the result across all tests in this module."""
    workspace = tmp_path_factory.mktemp("live_workspace")

    from alarmv3.core.session import SessionManager
    from alarmv3.core.guardrails import SessionState
    from alarmv3.core.discovery import FileScanner
    from alarmv3.core.analysis import Analyzer
    from alarmv3.core.synthesis import Synthesizer

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

    result = Synthesizer(session).run()
    session.transition_to(SessionState.ANALYSIS_COMPLETE)

    return session, result


# ── Return shape ──────────────────────────────────────────────────────────────

def test_result_has_required_keys(live_session):
    _, result = live_session
    assert "session_id" in result
    assert "recommendation_count" in result
    assert "top_recommendations" in result
    assert "message" in result


def test_at_least_one_recommendation(live_session):
    _, result = live_session
    assert result["recommendation_count"] >= 1


def test_top_recommendations_capped_at_five(live_session):
    _, result = live_session
    assert len(result["top_recommendations"]) <= 5


# ── Recommendation schema ─────────────────────────────────────────────────────

VALID_CATEGORIES = {"security", "modernization", "quality", "dependency"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_EFFORTS = {"S", "M", "L", "XL"}


def test_recommendation_fields(live_session):
    _, result = live_session
    for rec in result["top_recommendations"]:
        assert isinstance(rec.get("rank"), int)
        assert rec.get("category") in VALID_CATEGORIES
        assert rec.get("severity") in VALID_SEVERITIES
        assert rec.get("title") and len(rec["title"]) <= 80
        assert rec.get("description")
        assert isinstance(rec.get("affected_files"), list)
        assert rec.get("effort") in VALID_EFFORTS


# ── DB persistence ────────────────────────────────────────────────────────────

def test_recommendations_persisted_to_db(live_session):
    session, result = live_session
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM recommendation WHERE session_id=?",
        (session.session_id,),
    ).fetchone()[0]
    conn.close()
    assert count == result["recommendation_count"]


def test_db_recommendation_rank_ordering(live_session):
    session, _ = live_session
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    ranks = [r[0] for r in conn.execute(
        "SELECT rank FROM recommendation WHERE session_id=? ORDER BY rank",
        (session.session_id,),
    ).fetchall()]
    conn.close()
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


def test_db_affected_files_is_valid_json(live_session):
    session, _ = live_session
    db = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT affected_files FROM recommendation WHERE session_id=?",
        (session.session_id,),
    ).fetchall()
    conn.close()
    for (af,) in rows:
        parsed = json.loads(af)
        assert isinstance(parsed, list)


# ── Artifact writing ──────────────────────────────────────────────────────────

def test_artifacts_written(live_session):
    session, _ = live_session
    from alarmv3.core.artifacts import ArtifactWriter
    paths = ArtifactWriter(session).write_all()

    assert paths["recommendations_md"].exists()
    assert paths["manifest_json"].exists()
    assert paths["summary_json"].exists()


def test_recommendations_md_contains_titles(live_session):
    session, result = live_session
    from alarmv3.core.artifacts import ArtifactWriter
    paths = ArtifactWriter(session).write_all()
    text = paths["recommendations_md"].read_text()
    for rec in result["top_recommendations"]:
        assert rec["title"] in text


def test_summary_json_counts_match(live_session):
    session, result = live_session
    from alarmv3.core.artifacts import ArtifactWriter
    paths = ArtifactWriter(session).write_all()
    summary = json.loads(paths["summary_json"].read_text())
    assert summary["recommendation_count"] == result["recommendation_count"]
    assert summary["total_loc"] > 0
    assert "cpp" in summary["language_distribution"]
