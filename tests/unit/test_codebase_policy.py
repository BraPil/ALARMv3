"""Unit tests for core/codebase_policy.py.

The loader is intentionally thin — these tests pin the public surface
(CodebasePolicy.empty, .load, and every property) so consumers
(rag_query, generate_full_wiki, synthesis, deep_analysis, discovery)
can rely on the contract.
"""

import textwrap

import pytest

from alarmv3.core.codebase_policy import CodebasePolicy


# ── empty / load ──────────────────────────────────────────────────────────────


def test_empty_returns_engine_defaults():
    p = CodebasePolicy.empty()
    assert p.codebase_name == "this codebase"
    assert p.codebase_description is None
    assert p.rag_prompt is None
    assert p.ext_patterns is None
    assert p.path_stop is None
    assert p.extra_ignored_extensions == set()
    assert p.synthesis_overlay is None
    assert p.deep_analysis_overlay is None
    assert p.wiki == {}
    assert p.commit_message_format is None
    assert p.build_command is None


def test_load_none_returns_empty():
    p = CodebasePolicy.load(None)
    assert p.codebase_name == "this codebase"
    assert p.source_path is None


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CodebasePolicy.load(tmp_path / "nope.yaml")


def test_load_non_mapping_raises(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("- just a list")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        CodebasePolicy.load(p)


def test_load_empty_yaml_returns_empty_policy(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("")
    policy = CodebasePolicy.load(p)
    assert policy.codebase_name == "this codebase"
    assert policy.source_path == p


# ── codebase identity ────────────────────────────────────────────────────────


def test_codebase_name_and_description(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        codebase:
          name: BillGen
          description: Hypothetical billing system
    """))
    policy = CodebasePolicy.load(p)
    assert policy.codebase_name == "BillGen"
    assert policy.codebase_description == "Hypothetical billing system"


# ── rag_prompt ────────────────────────────────────────────────────────────────


def test_rag_prompt_passthrough(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        rag_prompt: |
          You are answering about codebase X.
          Rule 1: only quote chunks.
    """))
    policy = CodebasePolicy.load(p)
    assert "codebase X" in policy.rag_prompt
    assert "Rule 1" in policy.rag_prompt


# ── ext_patterns ──────────────────────────────────────────────────────────────


def test_ext_patterns_parsed(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent(r"""
        ext_patterns:
          - ext: ".sql"
            patterns: ['\.sql\b', '\bt-?sql\b']
          - ext: ".dtsx"
            patterns: ['\.dtsx\b', '\bssis\b']
    """))
    policy = CodebasePolicy.load(p)
    eps = policy.ext_patterns
    assert eps is not None
    assert eps[0] == (".sql", [r"\.sql\b", r"\bt-?sql\b"])
    assert eps[1] == (".dtsx", [r"\.dtsx\b", r"\bssis\b"])


def test_ext_patterns_omitted_returns_none(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("codebase:\n  name: X")
    policy = CodebasePolicy.load(p)
    assert policy.ext_patterns is None


# ── path_stop ─────────────────────────────────────────────────────────────────


def test_path_stop_returns_set(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        path_stop:
          - src
          - lib
    """))
    policy = CodebasePolicy.load(p)
    assert policy.path_stop == {"src", "lib"}


# ── extra_ignored_extensions ──────────────────────────────────────────────────


def test_extra_ignored_extensions_lowercased(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        extra_ignored_extensions:
          - .RPT
          - .DACPAC
    """))
    policy = CodebasePolicy.load(p)
    assert policy.extra_ignored_extensions == {".rpt", ".dacpac"}


def test_extra_ignored_extensions_empty_default():
    assert CodebasePolicy.empty().extra_ignored_extensions == set()


# ── synthesis / deep_analysis overlays ────────────────────────────────────────


def test_overlays_optional(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        synthesis_overlay: "Domain: billing systems."
        deep_analysis_overlay: "Pay attention to T-SQL stored procs."
    """))
    policy = CodebasePolicy.load(p)
    assert policy.synthesis_overlay == "Domain: billing systems."
    assert policy.deep_analysis_overlay == "Pay attention to T-SQL stored procs."


# ── wiki / commit format ──────────────────────────────────────────────────────


def test_wiki_fields(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        wiki:
          title: BillGen Modernization Wiki
          commit_message_format: "BillGen modernization #{rank}: {summary}"
    """))
    policy = CodebasePolicy.load(p)
    assert policy.wiki_title == "BillGen Modernization Wiki"
    assert policy.commit_message_format == "BillGen modernization #{rank}: {summary}"


# ── build verification ───────────────────────────────────────────────────────


def test_build_fields(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(textwrap.dedent("""\
        build:
          cmd: dotnet build
          cwd: src/BillGen
    """))
    policy = CodebasePolicy.load(p)
    assert policy.build_command == "dotnet build"
    assert policy.build_cwd == "src/BillGen"


# ── golden test against the shipped policy/adds.yaml ─────────────────────────


def test_shipped_adds_policy_loads():
    """The repo-shipped policy/adds.yaml must always parse cleanly."""
    from pathlib import Path as _Path
    repo_root = _Path(__file__).resolve().parents[2]
    policy = CodebasePolicy.load(repo_root / "policy" / "adds.yaml")
    assert policy.codebase_name == "ADDS"
    assert "AutoCAD" in policy.codebase_description
    assert policy.rag_prompt is not None
    assert "ADDS legacy codebase" in policy.rag_prompt
    assert policy.path_stop is not None
    assert "Original files" in policy.path_stop
    eps = policy.ext_patterns
    assert eps is not None
    exts = [e for e, _ in eps]
    assert ".lsp" in exts
    assert ".Lsp" in exts
    assert ".LSP" in exts
    assert ".Cmd" in exts
    assert policy.commit_message_format == "ADDS modernization #{rank}: {summary}"
