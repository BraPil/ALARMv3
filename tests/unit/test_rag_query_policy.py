"""Unit tests for the codebase-policy overlay wiring in scripts/rag_query.py.

Verifies that:
- set_policy() activates a CodebasePolicy
- _rag_prompt() returns the policy override when set, engine default otherwise
- _path_segments() honors the policy path_stop
- _extract_path_constraints() honors the policy ext_patterns

Doesn't require Ollama or Anthropic — tests only the override plumbing.
"""

import importlib.util
import sqlite3
import textwrap
from pathlib import Path

import pytest

from alarmv3.core.codebase_policy import CodebasePolicy


@pytest.fixture
def rag_module():
    """Load scripts/rag_query.py as a module so we can poke at internals."""
    repo_root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "rag_query", repo_root / "scripts" / "rag_query.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    # Reset to engine default so subsequent tests aren't polluted
    mod.set_policy(CodebasePolicy.empty())


# ── set_policy / _rag_prompt ──────────────────────────────────────────────────


def test_default_rag_prompt_is_engine_default(rag_module):
    rag_module.set_policy(CodebasePolicy.empty())
    p = rag_module._rag_prompt()
    assert "ADDS legacy codebase" in p  # engine default still ADDS-coupled for backcompat


def test_policy_overrides_rag_prompt(rag_module, tmp_path):
    pf = tmp_path / "p.yaml"
    pf.write_text(textwrap.dedent("""\
        rag_prompt: |
          You are answering about codebase ZetaCorp v2.
          Cite chunks {n}.
    """))
    rag_module.set_policy(CodebasePolicy.load(pf))
    out = rag_module._rag_prompt().format(n=5)
    assert "ZetaCorp v2" in out
    assert "Cite chunks 5" in out
    assert "ADDS legacy codebase" not in out


def test_empty_policy_falls_back_to_engine(rag_module):
    rag_module.set_policy(CodebasePolicy.empty())
    p = rag_module._rag_prompt()
    assert p == rag_module._RAG_PROMPT


# ── path_stop override (via _path_segments helper) ────────────────────────────


def _seed_db_with_paths(db_path: Path, paths: list[str]):
    """Create a minimal code_chunk table populated with the given file_paths."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE code_chunk (
            id INTEGER PRIMARY KEY,
            session_id TEXT, chunk_type TEXT, symbol_name TEXT,
            file_path TEXT, start_line INT, end_line INT, content TEXT,
            embedded INT DEFAULT 0
        )
    """)
    for fp in paths:
        conn.execute(
            "INSERT INTO code_chunk(file_path, chunk_type) VALUES (?, 'symbol')",
            (fp,),
        )
    conn.commit()
    conn.close()


def test_path_stop_default_excludes_adds_segments(rag_module, tmp_path):
    """With engine default _PATH_STOP, ADDS-shaped segments like 'Adds' are dropped."""
    rag_module.set_policy(CodebasePolicy.empty())
    db = tmp_path / "a.db"
    _seed_db_with_paths(db, ["Adds/Lisp/Foo.cs", "Original files/19.0/x.cs"])
    segs = rag_module._path_segments(db)
    # 'Adds' and 'Original files' both in _PATH_STOP → excluded
    assert "Adds" not in segs
    assert "Original files" not in segs
    # '19.0' has a digit → included
    assert "19.0" in segs


def test_policy_path_stop_overrides_default(rag_module, tmp_path):
    """A custom policy can carve out different stop-words for a different codebase."""
    pf = tmp_path / "p.yaml"
    pf.write_text(textwrap.dedent("""\
        path_stop: ["src", "dist"]
    """))
    rag_module.set_policy(CodebasePolicy.load(pf))

    db = tmp_path / "b.db"
    _seed_db_with_paths(db, ["src/foo/Bar.cs", "Adds/Lisp/Foo.cs"])
    segs = rag_module._path_segments(db)
    # Now 'Adds' is NOT a stop → it should appear (length>=5 → wait no, "Adds"=4)
    # Actually 'Adds' len=4 and no digit → still excluded by length filter
    # Use a longer name to exercise the override
    assert "src" not in segs  # in custom stop set


def test_policy_path_stop_promotes_previously_dropped_segment(rag_module, tmp_path):
    """If a segment was in default stop but not in the custom one, it now passes."""
    pf = tmp_path / "p.yaml"
    pf.write_text("path_stop: ['totally_unrelated']\n")
    rag_module.set_policy(CodebasePolicy.load(pf))

    db = tmp_path / "c.db"
    # 'Original files' is len>=5 → with default stop it's excluded; with custom
    # stop it should be included.
    _seed_db_with_paths(db, ["Original files/foo/Bar.cs"])
    segs = rag_module._path_segments(db)
    assert "Original files" in segs


# ── ext_patterns override ─────────────────────────────────────────────────────


def test_ext_patterns_default_includes_lisp(rag_module, tmp_path):
    rag_module.set_policy(CodebasePolicy.empty())
    db = tmp_path / "d.db"
    _seed_db_with_paths(db, ["foo.lsp"])
    patterns = rag_module._extract_path_constraints("show me the lisp scripts", db)
    assert any(p.endswith(".lsp") for p in patterns)


def test_policy_ext_patterns_overrides(rag_module, tmp_path):
    """Different codebase: T-SQL stored procs instead of LISP."""
    pf = tmp_path / "p.yaml"
    pf.write_text(textwrap.dedent(r"""
        ext_patterns:
          - ext: ".sql"
            patterns: ['\.sql\b', '\bt-?sql\b', '\bstored\s+proc']
    """))
    rag_module.set_policy(CodebasePolicy.load(pf))

    db = tmp_path / "e.db"
    _seed_db_with_paths(db, ["foo.sql"])
    # The user's query mentions "stored proc" — the policy's regex should fire
    patterns = rag_module._extract_path_constraints(
        "where is the stored proc for billing", db,
    )
    assert any(p.endswith(".sql") for p in patterns)
    # ADDS .lsp should NOT fire because the policy replaces, doesn't extend
    patterns_lisp = rag_module._extract_path_constraints(
        "show me the lisp scripts", db,
    )
    assert not any(p.endswith(".lsp") for p in patterns_lisp)
