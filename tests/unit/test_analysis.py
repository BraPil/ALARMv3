"""Unit tests for core/analysis.py — parsers, extractors, and index init."""

import sqlite3
from pathlib import Path

import pytest

from alarmv3.core.index import init_analysis_db
from alarmv3.core.session import SessionManager
from alarmv3.core.analysis import (
    _python_deps,
    _cpp_deps,
    _vbnet_deps,
    _js_deps,
    _java_deps,
    _csharp_deps,
    _extract_vbnet_symbols,
    Analyzer,
)


@pytest.fixture()
def workspace(tmp_path):
    return tmp_path


@pytest.fixture()
def session(workspace):
    sm = SessionManager(workspace)
    return sm.get_or_create()


# ── init_analysis_db ──────────────────────────────────────────────────────────

def test_init_creates_all_tables(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert {"manifest", "dependency_edge", "symbol", "complexity_metric", "code_chunk", "recommendation"} <= tables


def test_init_is_idempotent(tmp_path):
    db = tmp_path / "analysis.db"
    init_analysis_db(db)
    init_analysis_db(db)  # must not raise


# ── Dependency extractors ─────────────────────────────────────────────────────

def test_python_deps_import():
    src = "import os\nimport sys\nfrom pathlib import Path\n"
    deps = _python_deps(src)
    assert ("os", "import", 1) in deps
    assert ("sys", "import", 2) in deps
    assert ("pathlib", "import", 3) in deps


def test_python_deps_ignores_blanks():
    assert _python_deps("x = 1\n") == []


def test_cpp_deps_angle_and_quote():
    src = '#include <iostream>\n#include "utils.h"\n'
    deps = _cpp_deps(src)
    assert ("iostream", "include", 1) in deps
    assert ("utils.h", "include", 2) in deps


def test_vbnet_deps():
    src = "Imports System\nImports System.Collections.Generic\n"
    deps = _vbnet_deps(src)
    assert ("System", "imports", 1) in deps
    assert ("System.Collections.Generic", "imports", 2) in deps


def test_js_deps_require_and_import():
    src = "const fs = require('fs');\nimport path from 'path';\n"
    deps = _js_deps(src)
    modules = [d[0] for d in deps]
    assert "fs" in modules
    assert "path" in modules


def test_java_deps():
    src = "import java.util.List;\nimport java.io.File;\n"
    deps = _java_deps(src)
    assert ("java.util.List", "import", 1) in deps
    assert ("java.io.File", "import", 2) in deps


def test_csharp_deps():
    src = "using System;\nusing System.Linq;\n"
    deps = _csharp_deps(src)
    assert ("System", "using", 1) in deps
    assert ("System.Linq", "using", 2) in deps


# ── VB.NET regex extractor ────────────────────────────────────────────────────

SAMPLE_VB = """\
Imports System

Module Module1
    Sub Main()
    End Sub
End Module

Public Class Application
    Public Sub Run()
    End Sub

    Private Function ProcessData() As Boolean
    End Function

    Public Interface IWorker
    End Interface

    Public Enum Status
    End Enum
End Class
"""


def test_vbnet_extracts_module():
    syms = _extract_vbnet_symbols(SAMPLE_VB, "/f.vb", "s1")
    names = [s["name"] for s in syms]
    assert "Module1" in names


def test_vbnet_extracts_class():
    syms = _extract_vbnet_symbols(SAMPLE_VB, "/f.vb", "s1")
    names = [s["name"] for s in syms]
    assert "Application" in names


def test_vbnet_extracts_functions():
    syms = _extract_vbnet_symbols(SAMPLE_VB, "/f.vb", "s1")
    names = [s["name"] for s in syms]
    assert "Main" in names
    assert "Run" in names
    assert "ProcessData" in names


def test_vbnet_symbol_fields():
    syms = _extract_vbnet_symbols(SAMPLE_VB, "/my/file.vb", "sess-xyz")
    for s in syms:
        assert s["session_id"] == "sess-xyz"
        assert s["file_path"] == "/my/file.vb"
        assert s["symbol_type"] in ("function", "class", "interface", "enum")
        assert isinstance(s["start_line"], int)


# ── Analyzer — tree-sitter integration ───────────────────────────────────────

PYTHON_SRC = """\
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"

async def main():
    g = Greeter()
    print(g.greet("world"))
"""

CPP_SRC = """\
#include <string>

class Helper {
public:
    void run();
};

void Helper::run() {}

int compute(int x) { return x * 2; }
"""


def test_analyzer_init_creates_db(session):
    analyzer = Analyzer(session)
    assert (session.artifact_dir / "analysis.db").exists()


def test_analyzer_python_symbols(session, tmp_path):
    src_file = tmp_path / "greeter.py"
    src_file.write_text(PYTHON_SRC)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = sqlite3.connect(db_path)
    import time
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, discovered_at) VALUES (?,?,?,?,?,?,?)",
        (session.session_id, str(src_file), "greeter.py", "python",
         len(PYTHON_SRC), PYTHON_SRC.count("\n"), time.time()),
    )
    conn.commit()
    conn.close()

    session.enqueue("analysis", str(src_file))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        stats = Analyzer(session).run(pool, "job-1")

    assert stats["files_analyzed"] == 1
    assert stats["symbols_extracted"] >= 2  # Greeter class + greet + main

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM symbol WHERE session_id=?", (session.session_id,)
    ).fetchall()]
    conn.close()
    assert "Greeter" in names
    assert "greet" in names
    assert "main" in names


def test_analyzer_cpp_symbols(session, tmp_path):
    src_file = tmp_path / "helper.cpp"
    src_file.write_text(CPP_SRC)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = sqlite3.connect(db_path)
    import time
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, discovered_at) VALUES (?,?,?,?,?,?,?)",
        (session.session_id, str(src_file), "helper.cpp", "cpp",
         len(CPP_SRC), CPP_SRC.count("\n"), time.time()),
    )
    conn.commit()
    conn.close()

    session.enqueue("analysis", str(src_file))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        stats = Analyzer(session).run(pool, "job-2")

    assert stats["files_analyzed"] == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM symbol WHERE session_id=?", (session.session_id,)
    ).fetchall()]
    conn.close()
    assert "Helper" in names


def test_analyzer_complexity_written(session, tmp_path):
    src_file = tmp_path / "sample.py"
    src_file.write_text(PYTHON_SRC)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = sqlite3.connect(db_path)
    import time
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, discovered_at) VALUES (?,?,?,?,?,?,?)",
        (session.session_id, str(src_file), "sample.py", "python",
         len(PYTHON_SRC), PYTHON_SRC.count("\n"), time.time()),
    )
    conn.commit()
    conn.close()

    session.enqueue("analysis", str(src_file))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        Analyzer(session).run(pool, "job-3")

    conn = sqlite3.connect(db_path)
    metrics = {r[0]: r[1] for r in conn.execute(
        "SELECT metric_name, metric_value FROM complexity_metric WHERE session_id=?",
        (session.session_id,),
    ).fetchall()}
    conn.close()
    assert "loc" in metrics
    assert metrics["loc"] > 0


def test_analyzer_python_deps_written(session, tmp_path):
    src = "import os\nfrom pathlib import Path\n\ndef fn(): pass\n"
    src_file = tmp_path / "deps.py"
    src_file.write_text(src)

    db_path = session.artifact_dir / "analysis.db"
    init_analysis_db(db_path)
    conn = sqlite3.connect(db_path)
    import time
    conn.execute(
        "INSERT INTO manifest(session_id, file_path, relative_path, language, "
        "size_bytes, line_count, discovered_at) VALUES (?,?,?,?,?,?,?)",
        (session.session_id, str(src_file), "deps.py", "python",
         len(src), src.count("\n"), time.time()),
    )
    conn.commit()
    conn.close()

    session.enqueue("analysis", str(src_file))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        Analyzer(session).run(pool, "job-4")

    conn = sqlite3.connect(db_path)
    modules = [r[0] for r in conn.execute(
        "SELECT target_module FROM dependency_edge WHERE session_id=?",
        (session.session_id,),
    ).fetchall()]
    conn.close()
    assert "os" in modules
    assert "pathlib" in modules
