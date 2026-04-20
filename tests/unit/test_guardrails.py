import pytest
from pathlib import Path

from alarmv3.core.guardrails import (
    GuardrailViolation, GuardrailsManager, SessionState,
)


@pytest.fixture
def g(tmp_path):
    return GuardrailsManager(tmp_path)


# ── State transitions ──────────────────────────────────────────────────────

def test_valid_transition(g):
    result = g.transition(SessionState.UNATTACHED, SessionState.ATTACHED)
    assert result == SessionState.ATTACHED


def test_full_chain(g):
    chain = [
        (SessionState.UNATTACHED,          SessionState.ATTACHED),
        (SessionState.ATTACHED,            SessionState.READ_ONLY_CONFIRMED),
        (SessionState.READ_ONLY_CONFIRMED, SessionState.ANALYSIS_IN_PROGRESS),
        (SessionState.ANALYSIS_IN_PROGRESS,SessionState.ANALYSIS_COMPLETE),
        (SessionState.ANALYSIS_COMPLETE,   SessionState.IMPLEMENTATION_PLANNED),
        (SessionState.IMPLEMENTATION_PLANNED, SessionState.WORKING_REPO_READY),
    ]
    for from_state, to_state in chain:
        assert g.transition(from_state, to_state) == to_state


def test_skip_transition_raises(g):
    with pytest.raises(GuardrailViolation, match="not permitted"):
        g.transition(SessionState.UNATTACHED, SessionState.READ_ONLY_CONFIRMED)


def test_reverse_transition_raises(g):
    with pytest.raises(GuardrailViolation):
        g.transition(SessionState.ATTACHED, SessionState.UNATTACHED)


def test_terminal_state_raises(g):
    with pytest.raises(GuardrailViolation):
        g.transition(SessionState.WORKING_REPO_READY, SessionState.UNATTACHED)


# ── State requirements ─────────────────────────────────────────────────────

def test_require_state_passes(g):
    g.require_state(SessionState.ATTACHED, SessionState.ATTACHED)  # no exception


def test_require_state_fails(g):
    with pytest.raises(GuardrailViolation, match="requires state"):
        g.require_state(SessionState.UNATTACHED, SessionState.ATTACHED)


def test_require_state_in_passes(g):
    g.require_state_in(
        SessionState.ATTACHED,
        [SessionState.ATTACHED, SessionState.READ_ONLY_CONFIRMED],
    )


def test_require_state_in_fails(g):
    with pytest.raises(GuardrailViolation):
        g.require_state_in(SessionState.UNATTACHED, [SessionState.ATTACHED])


# ── Trust zone enforcement ─────────────────────────────────────────────────

def test_no_write_to_source_raises(g, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    inside = source / "main.cpp"
    inside.touch()
    with pytest.raises(GuardrailViolation, match="source zone"):
        g.assert_no_write_to_source(inside, source)


def test_write_outside_source_ok(g, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "artifacts" / "summary.json"
    g.assert_no_write_to_source(outside, source)  # no exception


def test_no_execute_source_raises(g, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    script = source / "run.py"
    script.touch()
    with pytest.raises(GuardrailViolation, match="forbidden"):
        g.assert_no_execute(script, source)


# ── Audit log ──────────────────────────────────────────────────────────────

def test_audit_log_created(g, tmp_path):
    g.log_tool_call("attach_repository", {"path": "/tmp/repo"})
    log = tmp_path / "audit.log"
    assert log.exists()


def test_audit_log_is_append_only(g, tmp_path):
    g.log_tool_call("tool_a", {})
    g.log_tool_call("tool_b", {})
    log = tmp_path / "audit.log"
    lines = log.read_text().strip().split("\n")
    assert len(lines) == 2  # transition + 2 tool calls
    # Each line is valid JSON
    import json
    for line in lines:
        parsed = json.loads(line)
        assert "ts" in parsed
        assert "msg" in parsed


def test_audit_log_error(g, tmp_path):
    g.log_error("run_analysis", "something went wrong")
    log = tmp_path / "audit.log"
    assert "TOOL_ERROR" in log.read_text()
    assert "something went wrong" in log.read_text()
