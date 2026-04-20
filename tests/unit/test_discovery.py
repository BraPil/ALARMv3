import pytest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alarmv3.core.session import SessionManager
from alarmv3.core.guardrails import SessionState
from alarmv3.core.discovery import FileScanner, LANGUAGE_MAP, PHASE_1_LANGUAGES


@pytest.fixture
def session(tmp_path):
    sm = SessionManager(tmp_path / "workspace")
    s = sm.get_or_create()
    s.set_source(tmp_path / "source")
    s.transition_to(SessionState.ATTACHED)
    s.transition_to(SessionState.READ_ONLY_CONFIRMED)
    s.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
    return s


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "main.cpp").write_text("int main() { return 0; }")
    (repo / "utils.h").write_text("#pragma once\nvoid helper();")
    (repo / "Module1.vb").write_text("Module Module1\n  Sub Main()\n  End Sub\nEnd Module")
    (repo / "app.py").write_text("def run(): pass")
    (repo / "build").mkdir()
    (repo / "build" / "output.obj").write_text("binary")
    return repo


def test_scan_discovers_files(tmp_path, source_repo, session):
    scanner = FileScanner(source_repo, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        count = scanner.scan(pool, "test-job")
    assert count >= 4  # cpp, h, vb, py (not build/output.obj if excluded)


def test_excluded_dirs_skipped(tmp_path, source_repo, session):
    node_modules = source_repo / "node_modules"
    node_modules.mkdir()
    (node_modules / "lib.js").write_text("module.exports = {}")
    scanner = FileScanner(source_repo, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        count = scanner.scan(pool, "test-job")
    # node_modules files should not be in the queue
    queued = []
    while True:
        item = session.claim_work("analysis")
        if not item:
            break
        queued.append(item["file_path"])
    assert not any("node_modules" in p for p in queued)


def test_cpp_files_get_priority(tmp_path, source_repo, session):
    scanner = FileScanner(source_repo, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scanner.scan(pool, "test-job")
    # C++ files should be claimed before Python files
    item = session.claim_work("analysis")
    assert item is not None
    assert item["file_path"].endswith((".cpp", ".h", ".vb"))


def test_language_map_covers_phase1():
    phase1_exts = {".py", ".js", ".ts", ".java", ".cs", ".cpp", ".h", ".vb"}
    for ext in phase1_exts:
        lang = LANGUAGE_MAP.get(ext)
        assert lang is not None, f"Extension {ext} not in LANGUAGE_MAP"
        assert lang in PHASE_1_LANGUAGES, f"Language {lang} not in PHASE_1_LANGUAGES"
