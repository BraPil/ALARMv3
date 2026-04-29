# Wiki Log

Append-only. Most recent at top.

---

## [2026-04-28] ingest | Full-archive ADDS run continuation — 5 silent-failure paths fixed, RAG validated end-to-end

Continued the 2026-04-28 ADDS full-archive run after observing only 16 of an expected ~20 recommendations and 14 of 16 changes committing in the morning batch. Diagnosis: five silent-failure paths in the engine, all now fixed.

**Bugs found and fixed in commit `90c6a9a`:**
1. **Path-convention split** — `core/analysis.py` (csharp/python/js tree-sitter) wrote absolute paths to `symbol`/`complexity_metric`/`dependency_edge`/`code_chunk` while `core/language_researcher.py` wrote relative paths. Result: 49 csharp + 8 javascript files were silently dropped from every relative-path query, including the representative-file selector in `deep_analysis`. Fix: writers normalize to `manifest.relative_path` form; one-shot `scripts/migrate_paths_to_relative.py` for existing DBs.
2. **Token-cap truncation** — `_MAX_TOKENS_SUBSYSTEM=2048` truncated 10-finding responses; the naïve `[`..`]` JSON slicer returned `[]`. Fix: cap raised to 6144 and `_parse_findings` walks the array recovering complete `{}` objects.
3. **Source-excerpt presentation** — original prompt JSON-encoded source code, escaping every newline. Fix: `_format_subsystem_message` puts each rep file in a fenced code block. Findings density 0–9 per cluster → 10/10 per cluster.
4. **Body-only diff applicator** — `_apply_diff` rebuilt files from hunk lines alone, dropping out-of-hunk content. Fix: `_splice_hunks` fuzzy-locates each hunk and splices in place.
5. **Missing evaluation_report writer** — added `ArtifactWriter.write_evaluation_report_md`.

**Bug found and fixed post-`90c6a9a`:**
6. **Symbol-sparse files invisible to RAG** — `Upd_S_Map_AddsW10_Trans_Test_Local.Cmd` had 3 GOTO-label "function" symbols at lines 6/10/81; chunker counted that as "has symbols" and skipped the file_overview emit. The file's actual Xcopy/icacls body was not retrievable. Fix: `_create_chunks` now emits a `file_overview` chunk (up to 200 lines) for **every** eligible file regardless of symbol presence.

**Run results post-fix:** 50 raw findings (was 16) across 5 subsystems → 20 ranked recommendations (was 16); adversarial verdicts 8 accept / 11 revise / 1 reject; subsystems 0/1/2 (110 LISP / 66 C# / 51 LookUpTable) now produce 10/10 findings each (previously empty). RAG validated end-to-end on three real questions including SQL injection localisation, Oracle login flow, and a deploy-script question that exposed the file_overview bug.

**Pages added:** runbooks/full-archive-run.md (the consolidated lessons-learned + pre-flight checklist for the next codebase, e.g. BillGen).

**Pages updated:** index.md (+1 page, count 15), log.md (this entry).

---

## [2026-04-20] ingest | Phase 4 implementation complete
Phase 4 shipped: implementation.py (plan/build/eval pipeline, git commit to TARGET), implementation_plan + implementation_change DB tables, 5 new MCP tools (plan_implementation, clone_for_implementation, implement_next, accept_change, reject_change), 2 new resources (implementation://plan, implementation://changes). 190 tests passing.
Board consulted via AAA (Cole Medin + consensus + architecture recommendation) before implementation. Key decisions: git worktree clone for isolation, context discipline (load only affected files), human gate before every commit, retry-with-feedback loop on rejection.

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
