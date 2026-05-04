"""Unit tests for codebase-policy overlay wiring in core modules.

Covers the overlay parameters added to:
- core/synthesis.py:Synthesizer (synthesis_overlay)
- core/deep_analysis.py:DeepSynthesizer (deep_analysis_overlay)
- core/discovery.py:FileScanner (extra_ignored_extensions)

The overlay surface is small: a string appended to a system prompt or a set
of extensions added to the discovery filter. These tests pin the wiring,
not LLM behavior.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alarmv3.core.deep_analysis import DeepSynthesizer
from alarmv3.core.discovery import FileScanner, IGNORED_EXTENSIONS
from alarmv3.core.session import SessionManager
from alarmv3.core.synthesis import Synthesizer


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture
def session(tmp_path):
    sm = SessionManager(tmp_path)
    s = sm.get_or_create()
    s.set_source(tmp_path / "src")
    return s


# ── Synthesizer overlay ───────────────────────────────────────────────────────


def test_synthesizer_default_no_overlay(session):
    s = Synthesizer(session)
    assert s._overlay is None


def test_synthesizer_stores_overlay(session):
    s = Synthesizer(session, synthesis_overlay="Domain: billing.")
    assert s._overlay == "Domain: billing."


def test_synthesizer_overlay_appended_to_prompt(session):
    """Verify the overlay appears in the system prompt string passed to Claude."""
    s = Synthesizer(session, synthesis_overlay="Pay attention to T-SQL stored procs.")

    captured: dict = {}

    class _FakeClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            captured["system"] = kwargs["system"]
            return MagicMock(content=[MagicMock(text="[]")])

    with patch("alarmv3.core.synthesis.anthropic.Anthropic", return_value=_FakeClient()):
        s._call_claude({"sample": "context"})

    system_text = captured["system"][0]["text"]
    assert "Pay attention to T-SQL stored procs." in system_text
    # Engine baseline text still present
    assert "JSON array" in system_text


def test_synthesizer_no_overlay_prompt_unchanged(session):
    """No overlay → system prompt is exactly _SYSTEM_PROMPT."""
    from alarmv3.core.synthesis import _SYSTEM_PROMPT
    s = Synthesizer(session)

    captured: dict = {}

    class _FakeClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            captured["system"] = kwargs["system"]
            return MagicMock(content=[MagicMock(text="[]")])

    with patch("alarmv3.core.synthesis.anthropic.Anthropic", return_value=_FakeClient()):
        s._call_claude({"sample": "context"})

    assert captured["system"][0]["text"] == _SYSTEM_PROMPT


# ── DeepSynthesizer overlay ───────────────────────────────────────────────────


def test_deep_synthesizer_default_no_overlay(session):
    d = DeepSynthesizer(session)
    assert d._overlay is None


def test_deep_synthesizer_stores_overlay(session):
    d = DeepSynthesizer(session, deep_analysis_overlay="Billing system context.")
    assert d._overlay == "Billing system context."


def test_deep_synthesizer_overlay_in_aggregation(session):
    """The overlay must appear in the aggregation system prompt, not subsystem/complexity."""
    d = DeepSynthesizer(session, deep_analysis_overlay="Domain: utility billing.")

    captured: dict = {}

    class _FakeClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            captured["system"] = kwargs["system"]
            return MagicMock(content=[MagicMock(text="[]")])

    with patch("alarmv3.core.deep_analysis.anthropic.Anthropic",
               return_value=_FakeClient()):
        d._call_aggregation({"findings": []}, memory_text="")

    system_text = captured["system"][0]["text"]
    assert "Domain: utility billing." in system_text


# ── FileScanner extra_ignored_extensions ──────────────────────────────────────


def test_filescanner_default_ignored_unchanged(tmp_path, session):
    """No extras → behavior matches the engine baseline IGNORED_EXTENSIONS."""
    src = tmp_path / "src"
    src.mkdir()
    fs = FileScanner(src, session)
    assert fs._ignored == IGNORED_EXTENSIONS


def test_filescanner_extra_extensions_added(tmp_path, session):
    src = tmp_path / "src"
    src.mkdir()
    fs = FileScanner(src, session, extra_ignored_extensions={".rpt", ".dacpac"})
    assert ".rpt" in fs._ignored
    assert ".dacpac" in fs._ignored
    # baseline still present
    assert ".dll" in fs._ignored


def test_filescanner_extras_skip_files(tmp_path, session):
    """A .rpt file should not be yielded when .rpt is in extras."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.cs").write_text("class A {}")
    (src / "b.rpt").write_bytes(b"\x00\x01\x02 binary report")

    fs_default = FileScanner(src, session)
    yielded_default = {p.name for p in fs_default._iter_files()}
    assert "a.cs" in yielded_default
    assert "b.rpt" in yielded_default  # baseline doesn't filter .rpt

    fs_with_extras = FileScanner(src, session, extra_ignored_extensions={".rpt"})
    yielded_extras = {p.name for p in fs_with_extras._iter_files()}
    assert "a.cs" in yielded_extras
    assert "b.rpt" not in yielded_extras
