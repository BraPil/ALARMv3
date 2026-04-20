"""Unit tests for CLI commands — no API calls, no LLM."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from alarmv3.cli.main import cli


@pytest.fixture()
def runner():
    return CliRunner()


# ── --help / version ──────────────────────────────────────────────────────────

def test_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.output
    assert "init-config" in result.output
    assert "status" in result.output


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# ── init-config ───────────────────────────────────────────────────────────────

def test_init_config_creates_file(runner, tmp_path):
    result = runner.invoke(cli, ["init-config", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    config = tmp_path / ".alarmv3" / "config.yaml"
    assert config.exists()


def test_init_config_valid_yaml(runner, tmp_path):
    import yaml
    runner.invoke(cli, ["init-config", "--workspace", str(tmp_path)])
    config = tmp_path / ".alarmv3" / "config.yaml"
    data = yaml.safe_load(config.read_text())
    assert data["version"] == "0.1.0"
    assert "cpp" in data["languages"]
    assert "vbnet" in data["languages"]
    assert data["llm"]["model"] == "claude-sonnet-4-6"


def test_init_config_idempotent(runner, tmp_path):
    runner.invoke(cli, ["init-config", "--workspace", str(tmp_path)])
    result = runner.invoke(cli, ["init-config", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "already exists" in result.output


# ── status ────────────────────────────────────────────────────────────────────

def test_status_no_session(runner, tmp_path):
    result = runner.invoke(cli, ["status", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "No active session" in result.output


def test_status_with_session(runner, tmp_path):
    from alarmv3.core.session import SessionManager
    from alarmv3.core.guardrails import SessionState

    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")
    session.transition_to(SessionState.ATTACHED)

    result = runner.invoke(cli, ["status", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "ATTACHED" in result.output
    assert session.session_id in result.output


# ── analyze (no LLM) ──────────────────────────────────────────────────────────

def test_analyze_missing_source(runner, tmp_path):
    result = runner.invoke(cli, ["analyze", str(tmp_path / "nonexistent")])
    assert result.exit_code != 0


def test_analyze_help(runner):
    result = runner.invoke(cli, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "SOURCE_PATH" in result.output
    assert "--workers" in result.output
