# ALARMv3 Wiki Index

Last updated: 2026-04-20 | Pages: 14

## Project

- [ALARMv3 Overview](project/alarmv3-overview.md) — What ALARMv3 is, guardrail state machine, MCP tools, trust zones, current status
- [Phase 1 Implementation](project/phase1-implementation.md) — What was built, test suite (115 tests), live synthesis results, known gaps
- [Phase 2 Plan](project/phase2-plan.md) — RAG layer: sqlite-vec, nomic-embed-text, query_codebase tool, Ollama in Codespaces
- [Phase 3 Plan](project/phase3-plan.md) — Adversarial evaluator, AAA grounding, risk/effort scoring, human review gate
- [Phase 4 Plan](project/phase4-plan.md) — Implementation mode: plan/build/eval, git clone to TARGET, human-gated commits
- [ALARM Lineage: v1 → v2 → v3](project/alarm-lineage.md) — How each generation corrected the last; the v3 synthesis
- [AAA + ALARMv3 Strategy](project/aaa-alarmv3-strategy.md) — Companion project relationship, key architectural decisions, open questions

## Concepts

- [MCP-First Architecture](concepts/mcp-first.md) — Why MCP is the primary interaction surface, not a CLI add-on
- [Multi-Agent Architecture](concepts/multi-agent-architecture.md) — Harnesses, separation of concerns, sycophancy, bounded orchestration
- [LLM Wiki Pattern](concepts/llm-wiki.md) — Karpathy's compounding knowledge base pattern; what this wiki is

## Personas

- [Cole Medin](personas/cole-medin.md) — AI coding agent architecture; harnesses, Archon, adversarial evaluators
- [Mitko Vasilev](personas/mitko-vasilev.md) — LLM boundary principle; semantic graph over raw files

## Architecture

- [Three-Layer Boundary](architecture/three-layer-boundary.md) — Core engine / MCP wrapper / sync adapters; dependency rules
- [Board of Governors Decisions](architecture/board-decisions.md) — 8 locked architectural decisions; phase roadmap

## Tools

- [Ollama in Codespaces](tools/ollama-codespaces.md) — Running nomic-embed-text on CPU in GitHub Codespaces; devcontainer setup
