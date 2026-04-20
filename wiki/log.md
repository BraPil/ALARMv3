# Wiki Log

Append-only. Most recent at top.

---

## [2026-04-20] ingest | Phase 3 implementation complete
Phase 3 shipped: adversarial evaluator (evaluation.py), RECOMMENDATIONS_PENDING_REVIEW guardrail state, review_recommendations MCP tool, recommendations://evaluated resource, AAA grounding hook (AAA_REST_URL env var, degrades gracefully). 154 tests passing (no regressions). Ready for PR.
AAA consulted via get_consensus + ask_persona before implementation — strong consensus for architectural separation of evaluator from synthesizer.

---

## [2026-04-20] ingest | Phase 2 merged + Phase 3 branch open
Phase 2 shipped: RAG layer (sqlite-vec + Ollama nomic-embed-text), structure-aware chunking, `query_codebase` MCP tool, full test suite. PR #4 merged to main. Phase 3 branch `phase-3/adversarial-evaluator` created.
AAA Board consulted (Cole Medin + consensus across Medin/Weng/Huyen/Willison) for Phase 3 design. Strong consensus: adversarial evaluator must be architecturally separated from synthesis; human review gate required before recommendations stored.
Pages added: project/phase3-plan.md
Pages updated: index.md (+1 page, count 13), architecture/board-decisions.md (Phase 3 scope)

---

## [2026-04-20] ingest | Phase 1 complete + Phase 2 branch open
Phase 1 shipped: 44 files, 5698 lines, 115 tests passing (105 unit/integration + 10 live API). Ollama installed and verified in Codespace (nomic-embed-text, 768-dim, CPU). Phase 2 branch `phase-2/rag-query-codebase` created.
Pages added: project/phase1-implementation.md, project/phase2-plan.md, tools/ollama-codespaces.md
Pages updated: project/alarmv3-overview.md (Phase 1 complete status, updated tool table, Phase 2 state), architecture/board-decisions.md (Phase 1 verified), index.md (+4 pages, count 12)

---

## [2026-04-20] ingest | Board of Governors session + Brandt's 7 architectural answers
AAA Board (11 personas) debated 6 architectural decisions for ALARMv3 Phase 1. Brandt answered all 7 clarifying questions. Decisions locked: 6-language set (Python/JS/TS/Java/C#/C++/VB), Claude API only for synthesis, nomic-embed-text for embeddings, stdio MCP Phase 1, AAA always co-present, one session per workspace Phase 1, target is separate directory.
Pages added: architecture/board-decisions.md, personas/mitko-vasilev.md
Pages updated: concepts/multi-agent-architecture.md (Vasilev principle), personas/cole-medin.md (adversarial dev)
Implementation completed: 25+ Phase 1 files written; pytest suite created (unit tests for guardrails, session, discovery)

---

## [2026-04-20] ingest | ALARMv3 founding knowledge base
Seeded wiki from planning docs (7 spec files), research docs (v1/v2/comparative analyses), strategy notes (AAA+ALARMv3), and Cole Medin persona query via AAA MCP.
Pages touched: project/alarmv3-overview.md, project/alarm-lineage.md, concepts/mcp-first.md, concepts/multi-agent-architecture.md, concepts/llm-wiki.md, personas/cole-medin.md, architecture/three-layer-boundary.md
