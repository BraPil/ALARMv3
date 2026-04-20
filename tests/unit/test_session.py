import pytest
from pathlib import Path

from alarmv3.core.session import Session, SessionManager
from alarmv3.core.guardrails import SessionState, GuardrailViolation


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


# ── SessionManager ─────────────────────────────────────────────────────────

def test_create_session(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    assert session.state == SessionState.UNATTACHED
    assert session.source_path is None


def test_get_or_create_is_idempotent(workspace):
    sm = SessionManager(workspace)
    s1 = sm.get_or_create()
    s2 = sm.get_or_create()
    assert s1.session_id == s2.session_id


def test_get_returns_none_before_create(workspace):
    sm = SessionManager(workspace)
    assert sm.get() is None


def test_get_returns_session_after_create(workspace):
    sm = SessionManager(workspace)
    s1 = sm.get_or_create()
    s2 = sm.get()
    assert s2 is not None
    assert s2.session_id == s1.session_id


def test_artifact_dir_created(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    assert session.artifact_dir.exists()


# ── State transitions ──────────────────────────────────────────────────────

def test_transition_persists(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.transition_to(SessionState.ATTACHED)
    # Re-load from DB
    session2 = sm.get()
    assert session2.state == SessionState.ATTACHED


def test_invalid_transition_raises(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    with pytest.raises(GuardrailViolation):
        session.transition_to(SessionState.ANALYSIS_COMPLETE)


# ── Source path ────────────────────────────────────────────────────────────

def test_set_source(workspace, tmp_path):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    source = tmp_path / "repo"
    source.mkdir()
    session.set_source(source)
    assert session.source_path == source.resolve()


# ── Metadata ───────────────────────────────────────────────────────────────

def test_metadata_roundtrip(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.set_metadata("files_found", 42)
    session.set_metadata("label", "test-run")
    meta = session.get_metadata()
    assert meta["files_found"] == 42
    assert meta["label"] == "test-run"


def test_metadata_defaults_empty(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    assert session.get_metadata() == {}


# ── Work queue ─────────────────────────────────────────────────────────────

def test_enqueue_and_claim(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.enqueue("analysis", "/src/main.cpp", priority=1)
    item = session.claim_work("analysis")
    assert item is not None
    assert item["file_path"] == "/src/main.cpp"
    assert item["status"] == "running"


def test_claim_returns_none_when_empty(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    assert session.claim_work("analysis") is None


def test_priority_ordering(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.enqueue("analysis", "/low.py", priority=0)
    session.enqueue("analysis", "/high.cpp", priority=1)
    item = session.claim_work("analysis")
    assert item["file_path"] == "/high.cpp"


def test_complete_work(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.enqueue("analysis", "/file.vb")
    item = session.claim_work("analysis")
    session.complete_work(item["id"], {"symbols": 12})
    stats = session.queue_stats("analysis")
    assert stats.get("complete") == 1
    assert stats.get("running", 0) == 0


def test_fail_work(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    session.enqueue("analysis", "/bad.cpp")
    item = session.claim_work("analysis")
    session.fail_work(item["id"], "parse error")
    stats = session.queue_stats("analysis")
    assert stats.get("failed") == 1


def test_queue_stats_mixed(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    for i in range(3):
        session.enqueue("analysis", f"/file{i}.py")
    item = session.claim_work("analysis")
    session.complete_work(item["id"])
    stats = session.queue_stats("analysis")
    assert stats["pending"] == 2
    assert stats["complete"] == 1


# ── to_dict ────────────────────────────────────────────────────────────────

def test_to_dict_keys(workspace):
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    d = session.to_dict()
    assert set(d.keys()) == {
        "session_id", "state", "source_path", "artifact_dir",
        "created_at", "updated_at", "metadata",
    }
