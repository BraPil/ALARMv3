"""Per-codebase policy overlay.

Loaded by `--policy <path>` flags on scripts and CLI commands. Lets a single
ALARMv3 install drive analysis on multiple legacy codebases without baking
codebase-specific strings (system prompts, file-extension hints, path
stop-words, wiki templates) into core modules.

Format is YAML. All fields are optional — anything not specified falls back
to the engine's hardcoded defaults, so passing no policy preserves current
behavior. See `policy/adds.yaml` for the canonical example extracted from
the ADDS run.

This module deliberately holds no business logic — it's a parsed-config
holder. Callers (rag_query, generate_full_wiki, synthesis, deep_analysis,
discovery) consult the relevant property and merge with their defaults.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class CodebasePolicy:
    """Read-only view onto a YAML policy file. Empty policy = engine defaults."""

    def __init__(self, data: dict | None = None, source_path: Path | None = None):
        self._data: dict = data or {}
        self._source_path: Path | None = source_path

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def empty(cls) -> "CodebasePolicy":
        """Policy with no overrides. Every property returns None or [] as appropriate."""
        return cls(data={})

    @classmethod
    def load(cls, path: str | Path | None) -> "CodebasePolicy":
        """Load a policy from `path`, or return an empty policy if `path` is None.

        Raises FileNotFoundError if the path is given but doesn't exist —
        better to fail loudly than silently fall back to ADDS defaults.
        """
        if path is None:
            return cls.empty()
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Codebase policy file not found: {p}")
        with open(p) as f:
            loaded = yaml.safe_load(f)
        if loaded is None:
            return cls(data={}, source_path=p)
        if not isinstance(loaded, dict):
            raise ValueError(
                f"Policy file {p} must be a YAML mapping at the top level, "
                f"got {type(loaded).__name__}"
            )
        return cls(data=loaded, source_path=p)

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    # ── Codebase identity ────────────────────────────────────────────────────

    @property
    def codebase_name(self) -> str:
        return self._data.get("codebase", {}).get("name", "this codebase")

    @property
    def codebase_description(self) -> str | None:
        desc = self._data.get("codebase", {}).get("description")
        return desc if desc else None

    # ── RAG retrieval (consumed by scripts/rag_query.py) ──────────────────────

    @property
    def rag_prompt(self) -> str | None:
        """Override for the RAG system prompt. None = engine default."""
        return self._data.get("rag_prompt")

    @property
    def ext_patterns(self) -> list[tuple[str, list[str]]] | None:
        """Override for path-aware extension patterns.

        Returns a list of (canonical_extension, [regex_pattern, ...]) tuples,
        or None if the policy doesn't specify. Engine default lives in
        `scripts/rag_query.py:_EXT_PATTERNS`.
        """
        raw = self._data.get("ext_patterns")
        if raw is None:
            return None
        # YAML format: list of {ext: ".lsp", patterns: [...]} mappings
        return [(item["ext"], list(item["patterns"])) for item in raw]

    @property
    def path_stop(self) -> set[str] | None:
        """Override for path-segment stop-words. Engine default in rag_query.py."""
        stop = self._data.get("path_stop")
        return set(stop) if stop is not None else None

    # ── Discovery (consumed by core/discovery.py) ─────────────────────────────

    @property
    def extra_ignored_extensions(self) -> set[str]:
        """Codebase-specific extensions to add to the engine's IGNORED_EXTENSIONS.

        Returns an empty set if not specified — codebase policies extend the
        baseline rather than replacing it.
        """
        extras = self._data.get("extra_ignored_extensions") or []
        return {e.lower() for e in extras}

    # ── Synthesis / deep-analysis prompt overlays ─────────────────────────────

    @property
    def synthesis_overlay(self) -> str | None:
        """Codebase-specific text appended to the synthesis system prompt.

        None = no overlay. Use this to inject domain framing
        ("This is a billing system; correctness means matching baseline
        bills…") without replacing the generic recommendation contract.
        """
        return self._data.get("synthesis_overlay")

    @property
    def deep_analysis_overlay(self) -> str | None:
        """Codebase-specific text appended to deep-analysis aggregation."""
        return self._data.get("deep_analysis_overlay")

    # ── Wiki generation (consumed by scripts/generate_full_wiki.py) ───────────

    @property
    def wiki(self) -> dict[str, Any]:
        return dict(self._data.get("wiki", {}))

    @property
    def wiki_title(self) -> str | None:
        return self.wiki.get("title")

    @property
    def commit_message_format(self) -> str | None:
        """Format string for implementation commits, e.g. '{name} #{rank}: {summary}'."""
        return self.wiki.get("commit_message_format")

    # ── Build verification (Phase 5b — P1 #5; field reserved for future use) ─

    @property
    def build_command(self) -> str | None:
        return self._data.get("build", {}).get("cmd")

    @property
    def build_cwd(self) -> str | None:
        return self._data.get("build", {}).get("cwd")
