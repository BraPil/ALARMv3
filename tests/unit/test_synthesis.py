"""Unit tests for core/synthesis.py — context assembly and response parsing."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager
from alarmv3.core.synthesis import _parse_recommendations, _SYSTEM_PROMPT, Synthesizer


# ── _parse_recommendations ────────────────────────────────────────────────────

def test_parse_valid_json_array():
    recs = [{"rank": 1, "title": "Fix it", "category": "security", "severity": "high"}]
    result = _parse_recommendations(json.dumps(recs))
    assert result == recs


def test_parse_json_embedded_in_text():
    text = 'Sure! Here are the recommendations:\n[{"rank":1,"title":"X"}]\nDone.'
    result = _parse_recommendations(text)
    assert len(result) == 1
    assert result[0]["title"] == "X"


def test_parse_empty_array():
    assert _parse_recommendations("[]") == []


def test_parse_malformed_returns_empty():
    assert _parse_recommendations("not json at all") == []


def test_parse_no_brackets_returns_empty():
    assert _parse_recommendations('{"rank": 1}') == []


def test_parse_truncated_json_returns_empty():
    assert _parse_recommendations('[{"rank": 1, "title": "Unc') == []


# ── _SYSTEM_PROMPT ────────────────────────────────────────────────────────────

def test_system_prompt_not_empty():
    assert len(_SYSTEM_PROMPT) > 100


def test_system_prompt_mentions_json_array():
    assert "JSON array" in _SYSTEM_PROMPT


def test_system_prompt_mentions_severity_values():
    for level in ("critical", "high", "medium", "low"):
        assert level in _SYSTEM_PROMPT


# ── Synthesizer._build_context ────────────────────────────────────────────────

@pytest.fixture()
def seeded_session(tmp_path):
    sm = SessionManager(tmp_path)
    session = sm.get_or_create()
    session.set_source(tmp_path / "src")

    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    now = time.time()

    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
        (session.session_id, "/src/main.cpp", "main.cpp", "cpp", 500, 40, 1, now),
    )
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
        (session.session_id, "/src/utils.vb", "utils.vb", "vbnet", 300, 25, 1, now),
    )
    conn.execute(
        "INSERT INTO symbol(session_id, file_path, name, symbol_type) VALUES (?,?,?,?)",
        (session.session_id, "/src/main.cpp", "main", "function"),
    )
    conn.execute(
        "INSERT INTO complexity_metric(session_id, file_path, metric_name, metric_value, computed_at) "
        "VALUES (?,?,?,?,?)",
        (session.session_id, "/src/main.cpp", "loc", 35.0, now),
    )
    conn.execute(
        "INSERT INTO dependency_edge(session_id, source_file, target_module, dep_type, line_number) "
        "VALUES (?,?,?,?,?)",
        (session.session_id, "/src/main.cpp", "iostream", "include", 1),
    )
    conn.commit()
    conn.close()
    return session


def test_build_context_keys(seeded_session):
    ctx = Synthesizer(seeded_session)._build_context()
    required = {
        "source_path", "total_files", "eligible_files", "total_loc",
        "language_distribution", "total_dependencies", "total_symbols",
        "largest_files", "sample_symbols",
    }
    assert required <= ctx.keys()


def test_build_context_counts(seeded_session):
    ctx = Synthesizer(seeded_session)._build_context()
    assert ctx["total_files"] == 2
    assert ctx["eligible_files"] == 2
    assert ctx["total_loc"] == 35
    assert ctx["total_dependencies"] == 1
    assert ctx["total_symbols"] == 1


def test_build_context_language_distribution(seeded_session):
    ctx = Synthesizer(seeded_session)._build_context()
    assert ctx["language_distribution"]["cpp"] == 1
    assert ctx["language_distribution"]["vbnet"] == 1


def test_build_context_sample_symbols(seeded_session):
    ctx = Synthesizer(seeded_session)._build_context()
    names = [s["name"] for s in ctx["sample_symbols"]]
    assert "main" in names
