# Wiki Log

Append-only. Most recent at top.

---

## [2026-05-04] post-mortem | ADDS modernization comparison + cross-model verification + P0 plan locked

End-of-day post-mortem on the ADDS run. Three parallel research agents (one per repo) compared `BraPil/ADDS2025` (human-led, shipped to production 2026-01-28) vs. `BraPil/ADDS_modernized_run2` (AI-led, ALARMv3 output, never built). A second model (GPT-5.5) did the same task independently in a separate Claude Code session; verifying their findings against the local working tree at `aee03c6` produced a sharper P0 plan.

**Single-source post-mortem:** `BraPil/ADDS_modernized_run2:Documentation/postmortem-and-billgen-readiness.md` (file retains the BillGen-tagged name for stable URLs; content is now codebase-agnostic).

**Headline finding:** ALARMv3 already has the schema and infrastructure to gate auto-accept; nobody enforces it. `src/alarmv3/core/index.py:115-119` defines `evaluator_verdict ∈ {pending,accept,revise,reject}` and `review_status ∈ {pending,accepted,rejected}` as separate columns. Three independent code paths issue `UPDATE recommendation SET review_status='accepted' …` with no predicate on `evaluator_verdict`:
- `scripts/demo_full_run.py:79-86` (helper) called from `:197-201` (review-gate site)
- `src/alarmv3/cli/main.py:96-103` (independent inline copy)
- `src/alarmv3/mcp/tools.py:363-368` (the human review tool itself)

`src/alarmv3/core/autopilot.py:53-101` is the unused safe gate — full policy engine with category/risk/effort rules and a safe default (`enabled: False`) when no policy file. Routing the demo and CLI auto-accept through it would honor the architectural intent the schema already encodes.

**P0 plan (in execution):**
1. Add `AND evaluator_verdict='accept'` predicate at all three SQL sites; tests assert `revise`/`reject` cannot be auto-accepted.
2. Route demo + CLI through `Autopilot.should_auto_accept()`; default-disabled fallback.
3. Per-codebase policy overlay (`--policy` flag) — replaces hardcoded ADDS strings at `scripts/rag_query.py:47-49,224-241`, `scripts/generate_full_wiki.py:395,448`, `src/alarmv3/core/synthesis.py:22-45`, `src/alarmv3/core/deep_analysis.py:127-142`. Extract current values into `policy/adds.toml` for back-compat.
4. Update `wiki/runbooks/full-archive-run.md §8` from BillGen-specific placeholder to next-codebase prep checklist.

**P1 backlog (queued):** build-verification phase 5b; hypothesis ledger (new `hypothesis`/`hypothesis_evidence`/`hypothesis_decision` tables — schema in post-mortem §11.1, contributed by GPT-5.5 with `chunk_id` FK for retrieval-replay determinism); LLM-as-acceptance-checker phase; default `--rerank` on; encoding hardening (`charset-normalizer` fallback chain); `CHECK` constraint on `manifest.relative_path NOT LIKE '/%'`; `IGNORED_EXTENSIONS` from policy.

**Cross-model lessons captured:**
- Two-model + verification raised confidence and shrunk the P0 acceptance-gate fix from "redesign state machine" to "3-line SQL patch." Pattern worth repeating on the next major analysis.
- GPT-5.5 contributed: hypothesis-ledger concept (motivated by ADDS2025's APC Transmission 3-pass theory-evolution report), output-equivalence reconciliation spec (P2 #16, applies to generated-artifact codebases), specific LISP digitizer back-port (`Updated Files/lisp/Adds/Lisp/Adds.Lsp` lines 746/751-752/757-758/766-767 still have the unsafe `(atof (getcfg "AppData/Adds/DigiURx"))` `stringp nil` path that ADDS2025 fixed via `LoadMouseCfg` + `ADDS25_LISP_Startup.log`).
- Opus 4.7 contributed: code-pointer-level analysis; identified that the schema and autopilot infrastructure already exist; concrete back-port list against ADDS2025; deferred-validation framing.

**Memory entries added (durable cross-session):** `adds2025_human_refactor.md`, `run2_outperformed_adds2025.md`, `alarmv3_billgen_strengthening.md` — referenced from `MEMORY.md`.

**Pages updated:**
- `wiki/runbooks/full-archive-run.md §8` — BillGen placeholder → "Per-codebase prep checklist" (codebase-agnostic, references the post-mortem)
- `wiki/log.md` (this entry)

---

## [2026-04-29] handoff | BillGen live-demo runbook + kickoff prompt ready for next session

End-of-day handoff package for the BillGen modernization run. Synthesizes every lesson from the ADDS execution into an executable playbook plus a paste-ready prompt to drop into a fresh Claude Code session tomorrow.

**Pages added**:
- `wiki/runbooks/billgen-live-demo.md` — day-by-day playbook (Day 0 pre-flight → Day 7 hand-off). 5-7 days of focused engineer time. References the ADDS template throughout via GitHub URLs so a cold session can resolve them.
- `launch-prompts/billgen-kickoff.md` — paste-ready prompt for a new Claude Code session. Includes the long form (with required-reading list, Phase 0 pause checkpoint, day-by-day structure, critical constraints reminder block) and a shorter autonomous variant for runs 2+.

**Lessons captured in the runbook (from ADDS)**:
- `[SuppressUnmanagedCodeSecurity]` strip needs to catch BOTH bare and fully-qualified attribute forms
- Version-pinned native API references (`acdb17.dll` stuck on AutoCAD 2007 by accident-of-history) need careful audit and `dumpbin /EXPORTS` capture for new host versions
- "Hardcoded credentials" is overloaded — separate the actual hardcoded values, the salt-from-tutorial, and the `Password=" + var + "` concat issue (different fixes)
- "UNC paths" might not be UNC strings (ADDS used `MapDrive "M:", "server", "share"` calls instead). A generic `\\X\Y` regex is a false-positive trap
- Build reranker prompts with f-strings, not `str.format()` — chunk content contains literal `{}` from C# array initializers
- LISP / embedded scripting files port unchanged when the host application provides the runtime; do NOT rewrite them as part of the forced minimum
- The forced-vs-optional distinction is the discipline that prevents legacy-modernization-as-rewrite

**Pre-flight checklist** for each new codebase included at the bottom of the runbook (covers source archive, modernized target, analysis workspace, ALARMv3 engine, Phase 0 unblocking decisions, expected outputs).

**Pages updated**:
- `wiki/index.md` (page count → 17)
- `wiki/log.md` (this entry)

---

## [2026-04-29] application | First downstream consumer of the RAG pipeline — full ADDS modernization plan committed and Phases 1-5 executed (code-level)

The 4-source hybrid + reranker RAG (per the prior log entry) was used to drive the discovery pass for an ADDS modernization plan, then the plan was executed end-to-end as far as a Linux Codespace permits.

**Plan**: `wiki/project/adds-modernization-plan.md` (`ad9bd39`)
- AutoCAD Map 3D 2025 / Oracle 19c / .NET 8 forced migration in 5 phases (~11 weeks)
- 14-item ranked opportunity backlog post-shipping
- Risk register; open questions block
- RAG-derived current-state baseline table covering: solution artifacts, Oracle integration, AutoCAD API surface, LISP/C# interop, auth flow, threading, config, deployment chain, LISP scope, test infrastructure
- Key strategic insight: separate **forced** changes (cannot ship without) from **opportunistic** ones; ship the forced minimum first

**Notable RAG-derived findings used in the plan:**
- ADDS does NOT use Map 3D's GIS APIs — only one commented-out `// using AcadGIS = Autodesk.Gis.Map;` in `jigs.cs`. Map 3D 2025 is just the runtime host
- AutoCAD 2025 is the first version on .NET 8 — the framework upgrade is forced
- Only ~7,500 LOC of C# but ~25,000+ LOC of AutoLISP (Utils.Lsp 12,802; Acad.Lsp 7,764; GET_INIT.LSP 3,240; Common.Lsp 362)
- The famous "AES key" issue is `EncryptionKey = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"` + 13-byte salt `"Ivan Medvedev"` in `utilities.cs`
- "UNC paths" are actually `MapDrive "M:", "alxapsb12", "Adds"` calls in VBS launchers — no literal `\\server\share` strings exist
- `acdb17.dll` P/Invoke is pinning to AutoCAD 2007's database DLL by accident-of-history; needs `acdb25.dll` for AutoCAD 2025

**Execution**: `BraPil/ADDS_modernized_run2` (`c5ea202`)
- New top-level structure: `Updated Files/` (refactored codebase), `Documentation/` (phase records), `Original files/` (untouched baseline)
- Phase 1 — SDK-style csproj at `net8.0-windows`; Oracle.ManagedDataAccess.Core 23.x replacing ODP.NET classic; `[SuppressUnmanagedCodeSecurity]` removed; `acdb17.dll` → `acdb25.dll`; `acedEvaluateLisp` mangled-name TODO marker for Phase 0 verification
- Phase 2 — DPAPI Encrypt/Decrypt replacing hardcoded `EncryptionKey` + AES (with `LegacyDecrypt` shim for one-release migration); 4 priority SQL injection sites parameterized; `OracleConnectionStringBuilder` replacing concat; `using` on every disposable
- Phase 3 — `Install-Adds.ps1` + `Uninstall-Adds.ps1` + `divisions.json` replace 9 VBS/Cmd files; per-user ACL on AddsTemp replaces overly broad `Users:(oi)(ci)f`
- Phase 4 — `AddsConfig` typed access to `appsettings.template.json`; workspace switch in `adds.cs` converted to dictionary lookup
- Phase 5 — `Adds.Tests` xUnit project + 3 test classes; GitHub Actions workflow with `build-and-test` + `powershell-syntax` jobs
- 9 markdown documents under `Documentation/` recording per-phase changes, deferred items, and acceptance criteria
- Single-source-of-truth `deferred-validation.md` enumerates every item that requires Windows + AutoCAD 2025 + Oracle 19c to acceptance-test

**Honest scope statement**: this Codespace pass produced all the code-level transformations and authoring work. It explicitly cannot validate `dotnet build` against AutoCAD assemblies, Oracle 19c connectivity, the new `acedEvaluateLisp` mangled name, AutoCAD NETLOAD, or the PowerShell installer end-to-end — those require a Windows + AutoCAD 2025 + Oracle 19c workstation. Every such item is enumerated in `Documentation/deferred-validation.md` in the modernized repo.

**Pages added**:
- `wiki/project/adds-modernization-plan.md`

**Pages updated**:
- `wiki/index.md` (count → 16)
- `wiki/log.md` (this entry)

---

## [2026-04-29] ingest | RAG retrieval evolved from vector-only → 4-source hybrid + reranker; probe scorecard 7/7 ✅

Probe-driven iteration on `scripts/rag_query.py` after the 2026-04-28 RAG layer revealed several blind spots. Designed a 7-question probe set covering single-file-type, sparse-content, cross-cutting, comparative, dense-token, exact-symbol, and synthesis queries. Iterated until all 7 surface the right evidence.

**Commits in order:**
1. **`540b6bb`** — initial `scripts/rag_query.py` (vector-only via Ollama nomic-embed-text → sqlite-vec → Claude with citations).
2. **`0a2d0c0`** — chunker emits `file_overview` for **every** eligible file (was: only files with zero symbols), so symbol-sparse files like `.Cmd` deploy scripts have their bodies indexed. Plus `scripts/rechunk_session.py` for incremental upgrades.
3. **`df9d61c`** — hybrid retrieval. BM25 over an in-memory FTS5 index fused with vector via standard Reciprocal Rank Fusion (k=60). `--mode {vector,keyword,hybrid}` with hybrid as default. Closes the embedder-blind-spot for batch/shell content (was rank ~925/2501, now mid-tier).
4. **`0e435e8`** — path-aware retrieval. Third source filtered by `file_path LIKE` patterns extracted at runtime: file extensions via regex, distinctive directory segments (length ≥ 5 or containing a digit) pulled from the manifest. When multiple patterns are detected, top-N per pattern is interleaved and `_ensure_pattern_coverage()` force-includes the per-pattern top-1 if RRF didn't surface it. Path-source weight=2.0.
5. **`80ed18b`** — `secret_pattern` chunker. Short context-windowed (line ± 5) chunks for AES byte arrays, ADO.NET connection strings, credential variable assignments, MapDrive network mounts, AWS keys, JWTs, basic-auth URLs. FTS5 now indexes `chunk_type + symbol_name + content` so metadata tokens like `credential_assignment` participate in BM25. New `secret` retrieval source auto-fires when the query mentions security keywords. `scripts/add_secret_chunks.py` runs only this extraction step (~20-50 chunks instead of the full ~2500-chunk re-embed).
6. **`bbb08b8`** — opt-in `--rerank` flag. Sends top-N candidates to Claude Haiku 4.5 with a structured 0-100 relevance scoring prompt. Default off (each call adds ~$0.005 + 1-2s). Failure-safe: any API error or malformed output falls back to RRF order. Closes the last ⚠️ (vector pollution on short single-symbol queries).

**Bug worth recording:** when the draft `unc_path` regex was first added to the secret patterns, it matched 800 LISP-escaped local paths like `"C:\\Data\\file.txt"` and produced massive false positives. Removed in favor of `network_share_call` matching `MapDrive "M:", "server", "share"` — the actual idiom in legacy VBS launchers. If a future codebase has literal `\\server\share` strings, add the pattern back with a lookbehind: `(?<=["'\s])\\{2,4}[a-zA-Z][\w-]+\\{1,2}[\w.$-]+`.

**Bug worth recording:** the reranker prompt builder used `str.format()`, which raised `ValueError: Single '}' encountered` on chunks containing literal `{}` (C# `new byte[] { 0x49, ... }`, JSON, dict literals). Fixed: use f-strings, never `.format()`, when chunk content is interpolated.

**Probe scorecard journey:**

| Probe | Vector | + Hybrid | + Path | + Secret | + Rerank |
|---|---|---|---|---|---|
| 1 (`.vbs` scripts exist) | ❌ | ❌ | ✅ | ✅ | ✅ |
| 2 (hardcoded credentials) | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ |
| 3 (error handling) | ✅ | ✅ | ✅ | ✅ | ✅ better |
| 4 (19.0 vs Div_Map) | ❌ | ❌ | ✅ | ✅ | ✅ better |
| 5 (UNC / network shares) | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ |
| 6 (`What does C:MakXCopFils do?`) | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ |
| 7 (highest-severity risks) | ✅ | ✅ | ✅ | ✅ | ✅ |

**Pages updated:** runbooks/full-archive-run.md (4 new silent-failure entries 4.6–4.9; section 5 rewritten with the new pipeline overview, trace tags, expanded seed queries; broken cross-repo memory link replaced with inline guidance), log.md (this entry), index.md (date bumped).

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
