---
name: Board of Governors Architectural Decisions
description: The 6 locked architectural decisions for ALARMv3 Phase 1, reached by AAA Board debate and confirmed by Brandt
type: architecture
---

# Board of Governors: ALARMv3 Architectural Decisions

Decided: 2026-04-20 | Board: 11 AAA personas | Confirmed by: Brandt Pileggi

## Decision Table

| # | Decision | Outcome | Dissent / Nuance |
|---|----------|---------|-----------------|
| 1 | Phase 1 language set | Python, JS/TS, Java, C#, C++, VB.NET | Tree-sitter-vbnet not on PyPI — regex fallback required |
| 2 | First real targets | C++ and VB.NET | Priority=1 in work queue; these are the actual legacy repos in scope |
| 3 | LLM synthesis | Claude API only (claude-sonnet-4-6) | Air-gap / local-LLM is Phase 4+; Claude is sole LLM call in system |
| 4 | Embedding model | nomic-embed-text via Ollama (local) | Phase 2; localhost:11434; no external calls for embeddings |
| 5 | MCP transport | stdio Phase 1 → standalone HTTP REST later | Keeps Codespace setup trivial; HTTP when multi-tenant |
| 6 | AAA availability | Always co-present companion | ALARMv3 calls AAA for architecture recommendations during synthesis |
| 7 | Session scope | One per workspace (Phase 1) | Multiple sessions per workspace in future phases |
| 8 | Target mode | Separate new directory cloned from source | Never modifies source; TARGET zone is gated behind IMPLEMENTATION_PLANNED state |

## Key Principles Locked In

**Vasilev Principle (LLM Boundary)**: LLM receives only the output of SQLite queries from `_build_context()`. It physically cannot see raw source files. Deterministic static analysis always runs first; LLM only synthesizes.

**Cole Medin Adversarial Dev**: Phase 2 introduces a separate evaluator that critiques recommendations before they are stored. Plan/build/eval are isolated agents.

**Guardrail State Machine**: 7-state machine (UNATTACHED → WORKING_REPO_READY) enforced at every MCP tool boundary. State transitions are WORM-audited.

**Four Trust Zones**:
- SOURCE — read-only, never written
- ARTIFACT — `.alarmv3/sessions/`, written by system
- TARGET — gated behind state machine, only after IMPLEMENTATION_PLANNED
- GOVERNANCE — `.alarmv3/policy/`, human-only writes

## Phase Roadmap

| Phase | Scope |
|-------|-------|
| 1 (done) | Core engine, MCP server (6 tools), guardrails, discovery, analysis (tree-sitter + regex), synthesis (Claude API), CLI |
| 2 | RAG layer: sqlite-vec, nomic-embed-text, structure-aware chunking, `query_codebase` MCP tool |
| 3 | Adversarial evaluator, multi-session, progress streaming |
| 4 | Air-gap / local LLM option, HTTP MCP transport |
| 5 | Continuous monitoring, ROI tracking, collaboration features |

## Implementation Notes

- `MAX_WORKERS = 4` — Codespaces safe; phases run sequentially to avoid memory pressure
- SQLite WAL mode — concurrent worker writes without locking; crash-recoverable
- tree-sitter grammar loading: each grammar wrapped in `try/except ImportError` — missing grammars degrade gracefully
- TypeScript special-case: `tsts.language_typescript()` (not `.language()`)
