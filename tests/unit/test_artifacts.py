"""Unit tests for core/artifacts.py — Markdown and JSON output writers."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager
from alarmv3.core.artifacts import ArtifactWriter


@pytest.fixture()
def session(tmp_path):
    sm = SessionManager(tmp_path)
    s = sm.get_or_create()
    s.set_source(tmp_path / "src")
    return s


@pytest.fixture()
def db_path(session):
    db = session.artifact_dir / "analysis.db"
    init_analysis_db(db)
    return db


def _insert_manifest(db_path, session_id, rows):
    conn = sqlite3.connect(db_path)
    for r in rows:
        conn.execute(
            "INSERT INTO manifest(session_id, file_path, relative_path, language, "
            "size_bytes, line_count, is_eligible, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, r["file_path"], r["relative_path"], r.get("language"),
             r.get("size_bytes", 0), r.get("line_count", 0), r.get("is_eligible", 1), time.time()),
        )
    conn.commit()
    conn.close()


def _insert_recommendations(db_path, session_id, rows):
    conn = sqlite3.connect(db_path)
    for r in rows:
        conn.execute(
            "INSERT INTO recommendation(session_id, rank, category, severity, title, "
            "description, affected_files, effort, rationale, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session_id, r["rank"], r["category"], r["severity"], r["title"],
             r["description"], json.dumps(r.get("affected_files", [])),
             r.get("effort"), r.get("rationale"), time.time()),
        )
    conn.commit()
    conn.close()


def _insert_symbols(db_path, session_id, rows):
    conn = sqlite3.connect(db_path)
    for r in rows:
        conn.execute(
            "INSERT INTO symbol(session_id, file_path, name, symbol_type) VALUES (?,?,?,?)",
            (session_id, r["file_path"], r["name"], r["symbol_type"]),
        )
    conn.commit()
    conn.close()


def _insert_complexity(db_path, session_id, file_path, metrics: dict):
    conn = sqlite3.connect(db_path)
    for name, value in metrics.items():
        conn.execute(
            "INSERT INTO complexity_metric(session_id, file_path, metric_name, metric_value, computed_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, file_path, name, value, time.time()),
        )
    conn.commit()
    conn.close()


# ── write_manifest_json ───────────────────────────────────────────────────────

def test_manifest_json_written(session, db_path):
    _insert_manifest(db_path, session.session_id, [
        {"file_path": "/src/main.py", "relative_path": "main.py", "language": "python"},
        {"file_path": "/src/utils.py", "relative_path": "utils.py", "language": "python"},
    ])
    writer = ArtifactWriter(session)
    out = writer.write_manifest_json()

    assert out.exists()
    data = json.loads(out.read_text())
    paths = [r["relative_path"] for r in data]
    assert "main.py" in paths
    assert "utils.py" in paths


def test_manifest_json_empty(session, db_path):
    out = ArtifactWriter(session).write_manifest_json()
    assert json.loads(out.read_text()) == []


# ── write_recommendations_md ──────────────────────────────────────────────────

def test_recommendations_md_written(session, db_path):
    _insert_recommendations(db_path, session.session_id, [
        {
            "rank": 1, "category": "security", "severity": "critical",
            "title": "SQL Injection", "description": "Use parameterized queries.",
            "affected_files": ["main.cpp"], "effort": "M", "rationale": "PCI requirement",
        },
    ])
    out = ArtifactWriter(session).write_recommendations_md()

    assert out.exists()
    text = out.read_text()
    assert "SQL Injection" in text
    assert "critical" in text
    assert "main.cpp" in text
    assert "PCI requirement" in text


def test_recommendations_md_empty(session, db_path):
    out = ArtifactWriter(session).write_recommendations_md()
    text = out.read_text()
    assert "Total recommendations**: 0" in text


def test_recommendations_md_multiple_ranks(session, db_path):
    _insert_recommendations(db_path, session.session_id, [
        {"rank": 1, "category": "security", "severity": "high",
         "title": "Alpha", "description": "Desc A"},
        {"rank": 2, "category": "quality", "severity": "low",
         "title": "Beta", "description": "Desc B"},
    ])
    text = ArtifactWriter(session).write_recommendations_md().read_text()
    assert text.index("Alpha") < text.index("Beta")


# ── write_summary_json ────────────────────────────────────────────────────────

def test_summary_json_structure(session, db_path):
    _insert_manifest(db_path, session.session_id, [
        {"file_path": "/src/a.py", "relative_path": "a.py", "language": "python"},
        {"file_path": "/src/b.cpp", "relative_path": "b.cpp", "language": "cpp"},
    ])
    _insert_symbols(db_path, session.session_id, [
        {"file_path": "/src/a.py", "name": "Foo", "symbol_type": "class"},
        {"file_path": "/src/a.py", "name": "bar", "symbol_type": "function"},
    ])
    _insert_complexity(db_path, session.session_id, "/src/a.py", {"loc": 50.0})
    _insert_complexity(db_path, session.session_id, "/src/b.cpp", {"loc": 120.0})

    out = ArtifactWriter(session).write_summary_json()
    summary = json.loads(out.read_text())

    assert summary["session_id"] == session.session_id
    assert summary["language_distribution"]["python"] == 1
    assert summary["language_distribution"]["cpp"] == 1
    assert summary["symbol_types"]["class"] == 1
    assert summary["symbol_types"]["function"] == 1
    assert summary["total_loc"] == 170
    assert summary["recommendation_count"] == 0


def test_summary_json_no_data(session, db_path):
    summary = json.loads(ArtifactWriter(session).write_summary_json().read_text())
    assert summary["total_loc"] == 0
    assert summary["recommendation_count"] == 0
    assert summary["language_distribution"] == {}


# ── write_all ─────────────────────────────────────────────────────────────────

def test_write_all_returns_three_paths(session, db_path):
    result = ArtifactWriter(session).write_all()
    assert set(result.keys()) == {"recommendations_md", "manifest_json", "summary_json"}
    for path in result.values():
        assert path.exists()
