---
name: Mitko Vasilev
description: Most directly relevant board member for ALARMv3 — deterministic static analysis first, LLM for synthesis only; dede pattern
type: persona
---

# Mitko Vasilev

Source: AAA MCP board session 2026-04-20 | Relevance to ALARMv3: **highest of all board members**

## Core Principle: The dede Pattern

Vasilev's defining contribution is the **dede pattern** (deterministic → semantic → synthesis):

1. **Deterministic phase**: Run static analysis tools (Roslyn for C#, tree-sitter for others) to extract a complete, verifiable semantic graph. No hallucination possible here.
2. **Semantic graph**: Store the structured output in a queryable database (SQLite in ALARMv3). Symbols, dependencies, complexity metrics, code chunks — all verifiable facts.
3. **Synthesis phase**: LLM agents query the semantic graph only. They never touch raw source files.

This is not an optimization — it's an architectural constraint that prevents an entire class of LLM errors (hallucinated function signatures, invented dependencies, misread file paths).

## ALARMv3 Application

The LLM boundary in ALARMv3 is a direct implementation of Vasilev's dede pattern:

```
analysis.py (tree-sitter / regex) → SQLite (symbols, edges, metrics)
                                         ↓
synthesis.py._build_context()     → structured dict
                                         ↓
synthesis.py._call_claude()       → recommendations
```

Claude in `synthesis.py` receives the output of `_build_context()` — a Python dict built entirely from SQLite queries. The `anthropic` client is the only external call; it has no file access.

## Key Insight for Legacy Codebases

Legacy code is particularly hostile to LLMs operating on raw text:
- Inconsistent naming conventions (hungarian notation, abbreviations)
- Dead code mixed with live code
- Implicit dependencies (shared globals, header-only implementations)
- Multi-language boundaries (VB.NET calling C++ DLLs via COM)

The semantic graph normalizes all of this before the LLM ever sees it. The graph contains **what is true**, not **what the code says**.

## Tooling Alignment

- **Roslyn (C#/VB.NET)**: Vasilev's preferred tool for .NET analysis; produces complete, type-resolved semantic models. ALARMv3 uses regex fallback for VB.NET Phase 1 (tree-sitter-vbnet not on PyPI), with Roslyn integration planned for Phase 3.
- **tree-sitter**: Vasilev-aligned for non-.NET languages; fast, error-tolerant, grammar-based.
- **SQLite**: Preferred over in-memory graphs for crash recovery and queryability.

## Difference from Other Board Members

Most board members discussed agent orchestration, tool selection, or embedding strategies. Vasilev's unique contribution is the **data architecture** constraint: what shape does the intermediate representation take, and who is allowed to access raw source?

This made him the most directly load-bearing board member for ALARMv3's Phase 1 design.
