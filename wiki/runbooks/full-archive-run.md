# Full-archive run runbook

> **Status**: current
> **Last updated**: 2026-04-29
> **Tags**: operations, runbook, regression-checklist, lessons-learned, modernization-planning

End-to-end recipe for running ALARMv3 against a new legacy codebase from scratch, with a pre-flight checklist that encodes every silent-failure path we've hit so far. Designed so the next codebase (BillGen) starts at the quality level the ADDS full-archive run finished at — not at the empty-findings starting line we hit on 2026-04-28.

---

## 0. Definitions

| Term | Meaning |
|---|---|
| **Source archive** | `/workspaces/<NAME>/` — the read-only legacy codebase. Never modify. Treat like a git tag pinned to a specific commit. |
| **Target** | `/workspaces/<NAME>_modernized*/` — fresh git repo where ALARMv3 commits land. |
| **Workspace** | `/workspaces/<NAME>_ALARMv3/` — holds `.alarmv3/sessions/<id>/`, `RUN_PLAN.md`, `wiki/`. The `.alarmv3/` is the engine's per-session state. |
| **Session** | One UUID-keyed run. `analysis.db` lives at `.alarmv3/sessions/<id>/analysis.db`. |

---

## 1. Pre-flight (do this BEFORE the run, not after)

### 1.1 Source archive

- [ ] Source repo clone exists at `/workspaces/<NAME>/`.
- [ ] Read-only enforced — no local writes. If the source repo's local `origin` push URL points at a writable remote, neutralise the push side: `git remote set-url --push origin DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`. Any future `git push origin` will then error out instead of silently writing to the archive. (Fetch still works.)
- [ ] Snapshot: record the commit hash you are running against. The wiki and recommendation set will cite it.
- [ ] Quick sanity: `find /workspaces/<NAME> -type f | wc -l` matches the manifest count you expect. If you see 10 000+ files, something is bringing in a `node_modules`/`bin/` bulk dump — fix the source clone before running.

### 1.2 Modernized target

- [ ] `/workspaces/<NAME>_modernized*/` is a **fresh** git clone of the source archive (`git clone <archive> <target>`).
- [ ] Target's git remote points at a **separate** GitHub repo, NOT the source archive. Verify with `git remote -v` — origin should not match the source.
- [ ] If the target repo doesn't exist on GitHub yet:
      ```
      env -u GITHUB_TOKEN -u GH_TOKEN gh repo create BraPil/<NAME>_modernized --private \
        --description "ALARMv3 modernization target — derived from BraPil/<NAME>_Orig"
      ```
      Then `git remote rename origin archive`, `git remote add origin https://github.com/BraPil/<NAME>_modernized.git`, and `git remote set-url --push archive DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`.

### 1.3 Workspace

- [ ] `/workspaces/<NAME>_ALARMv3/` exists. Drop a `RUN_PLAN.md` here describing the goal of the run before kicking off.
- [ ] `.alarmv3/policy/autopilot.yaml` configured (defaults are usually fine for first run).

### 1.4 Engine

- [ ] ALARMv3 venv healthy: `/workspaces/ALARMv3/.venv/bin/python --version` returns 3.12+.
- [ ] Ollama running: `curl -s http://localhost:11434/api/tags | jq` shows `nomic-embed-text`. If not, `ollama serve` in a background shell.
- [ ] `ANTHROPIC_API_KEY` set in environment (`env | grep -i ANTHROPIC` should show `ANTHROPIC_API_KEY=***`).
- [ ] No stale session — `ls /workspaces/<NAME>_ALARMv3/.alarmv3/sessions/` is empty (or you've decided to resume an existing one).

### 1.5 Critical engine settings to verify before running

These are the settings that, if regressed, silently destroy run quality:

| File | Knob | Required value | Why |
|---|---|---|---|
| `core/deep_analysis.py` | `_MAX_TOKENS_SUBSYSTEM` | ≥ 6144 | 2048 truncated 10-finding responses → empty `[]` to caller |
| `core/deep_analysis.py` | `_MAX_REPRESENTATIVE_FILES` | 8 | Below 4: misses subsystem-spanning patterns |
| `core/deep_analysis.py` | `_MAX_LINES_PER_EXCERPT` | 200 | Below 100: misses class-level structure |
| `core/deep_analysis.py` | `_format_subsystem_message` | present | If missing, source goes through JSON-encoded escaping → poor finding density |
| `core/deep_analysis.py` | `_parse_findings` | walks `{}` blocks | If naïve `[`..`]` slicer, truncated arrays return `[]` |
| `core/analysis.py` | `_to_relative` helper | present and called from `_analyze_file` | Without it, csharp/python/js writers leak absolute paths |
| `core/knowledge.py` | `_OVERVIEW_LINES` | 200 | Below 100: misses the body of symbol-sparse files |
| `core/knowledge.py` | overview chunk emitted for **every** eligible file | yes | Without this, .Cmd / .lsp utilities with sparse symbols vanish from RAG |
| `core/knowledge.py` | `_extract_secret_chunks` called from `_create_chunks` | yes | Without it, hardcoded credentials/keys/network shares only appear inside larger function chunks where natural-language queries miss them |
| `core/knowledge.py` | `_SECRET_PATTERNS` does not contain a generic `unc_path` regex matching `\\X\\Y` | yes | A generic UNC pattern matches LISP-escaped local paths like `"C:\\Data\\file"` and produces hundreds of false-positive chunks |
| `scripts/rag_query.py` | FTS5 indexes `chunk_type + symbol_name + content` (not just content) | yes | Otherwise metadata tokens like `credential_assignment` don't participate in BM25 and security-themed queries miss the secret chunks |
| `scripts/rag_query.py` | `retrieve()` runs `vec` + `kw` + optional `path` + optional `secret` sources, fused via weighted RRF | yes | Pure vector retrieval ranks `.Cmd`/short-query targets at ~rank 925/2501 because nomic-embed-text under-represents shell-script and dense-token content |
| `core/implementation.py` | `_apply_diff` uses `_splice_hunks` | yes | Older "rebuild from hunk lines" version drops out-of-hunk content |
| `core/artifacts.py` | `write_evaluation_report_md` in `write_all` | yes | Without it, evaluator critique data sits unsurfaced in the DB |

A quick grep for these guards before kicking off the run takes 30 seconds and saves a 90-minute regenerate cycle.

---

## 2. Running the pipeline

### 2.1 First run from scratch

Use the demo driver — it does the full state-machine dance:

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/demo_full_run.py \
  --source /workspaces/<NAME> \
  --workspace /workspaces/<NAME>_ALARMv3 \
  --target /workspaces/<NAME>_modernized
```

Watch for these in the log:
- `STATE_TRANSITION ATTACHED -> READ_ONLY_CONFIRMED`
- `STATE_TRANSITION ANALYSIS_IN_PROGRESS -> RECOMMENDATIONS_PENDING_REVIEW`
- `AUTOPILOT_ACCEPT change_id=N commit_hash=<hash>`

### 2.2 Re-running deep analysis only on an existing session

When the source/manifest haven't changed but you want a fresh recommendation pass (e.g. after a prompt or selector tweak):

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/rerun_deep_analysis.py \
  --alarm-dir /workspaces/<NAME>_ALARMv3/.alarmv3 \
  --session-id <id>
```

This wipes `subsystem`, `subsystem_finding`, `analysis_coverage`, and the `recommendation` rows, then re-runs phases A–D + adversarial evaluation against the existing symbols/metrics.

### 2.3 Re-chunking + re-embedding only

When you've changed chunker logic and want the existing `analysis.db` to use the new strategy without re-discovering source:

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/rechunk_session.py \
  --alarm-dir /workspaces/<NAME>_ALARMv3/.alarmv3 \
  --session-id <id>
```

### 2.4 Migrating an old session

If `analysis.db` was produced before the path-convention fix landed, normalize all paths to relative form:

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/migrate_paths_to_relative.py \
  --db /workspaces/<NAME>_ALARMv3/.alarmv3/sessions/<id>/analysis.db \
  --source-root /workspaces/<NAME>
```

Idempotent — safe to run repeatedly.

---

## 3. Post-run sanity checks

"RUN COMPLETE" doesn't mean the output is healthy. Run these before declaring victory:

### 3.1 Discovery looks right

```python
# In `analysis.db`:
SELECT language, COUNT(*), SUM(line_count) FROM manifest
WHERE session_id=? AND is_eligible=1 GROUP BY language ORDER BY 2 DESC;
```

- Eligible file count > 100 for any non-toy codebase.
- No language has 1000+ files unless you expect that — if you see `inferred_bmp: 800`, the binary blocklist regressed.

### 3.2 Symbols and metrics actually populated

```python
SELECT COUNT(*) FROM symbol WHERE session_id=?;       -- expect > 0 across multiple langs
SELECT COUNT(*) FROM complexity_metric WHERE session_id=?;  -- expect 1 row per file × 2 metrics
SELECT COUNT(DISTINCT file_path) FROM symbol WHERE file_path LIKE '/%';  -- MUST be 0
```

A non-zero count of absolute paths in `symbol`/`complexity_metric`/`code_chunk` means the path-convention fix has regressed. Run `migrate_paths_to_relative.py` and audit `core/analysis.py`.

### 3.3 Subsystems produced findings

```python
SELECT s.subsystem_index, s.name, s.file_count,
       json_array_length(sf.findings_json) AS findings_count
FROM subsystem s LEFT JOIN subsystem_finding sf
  ON s.session_id=sf.session_id AND s.subsystem_index=sf.subsystem_index
  AND sf.pass_type='subsystem'
WHERE s.session_id=? ORDER BY s.subsystem_index;
```

- Every subsystem should have **non-zero** `findings_count`.
- If any subsystem returns 0, suspect: representative-file selector picking auto-generated files, or token cap truncation. Inspect via:
  ```python
  # Replay the representative-file selection
  scores = []
  for f in subsystem_files:
      score = cyc*10 + symbols*2 + loc*0.01
      scores.append((score, f))
  ```
  If the top picks are `.Designer.cs`, `.resx`, or other generated content, broaden `_select_representative_files` to filter by extension or symbol density.

### 3.4 Implementation actually committed

```python
SELECT COUNT(*) FROM implementation_change WHERE session_id=? AND commit_hash IS NOT NULL;
```

Should equal the count of accepted plan items minus any that legitimately had empty diffs (rare). If `commit_hash IS NULL` rows outnumber non-NULL, suspect:
- Diff applicator format issue (path quoting, fence stripping) — see `_apply_diff`.
- Partial-hunk diff that the older applicator couldn't splice — current version handles it via `_splice_hunks`.

### 3.5 RAG layer functional

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/rag_query.py \
  --db <analysis.db> \
  --query "where is authentication handled?" --raw
```

Top result should be a relevant file from the codebase. If chunks are missing or all show `chunk_type=function` for trivial labels, the chunker patch may have regressed — check `_create_chunks` is emitting `file_overview` for **every** eligible file.

---

## 4. Known silent-failure paths

These have actually happened. The patches are landed; the descriptions are kept so future audits can catch regressions.

### 4.1 Path-convention split between extractors *(fixed in `90c6a9a`)*

`core/analysis.py` (tree-sitter for csharp/python/js/ts/java/cpp) and `core/language_researcher.py` (Phase 7 inferred languages) wrote different forms of the same path into `symbol.file_path` etc. Result: 49 csharp + 8 javascript files were silently dropped from every relative-path query. **The bug was invisible** in `coverage_pct` (100%) and `subsystem_count` (5). It only surfaced by replaying the representative-file scorer per subsystem and noticing top picks were all `.resx` files.

### 4.2 Token-cap truncation *(fixed in `90c6a9a`)*

`_MAX_TOKENS_SUBSYSTEM = 2048` truncated 10-finding responses mid-array. The naïve `[`..`]` JSON slicer found a `]` somewhere inside a partial finding and returned `[]`. Fix: bumped cap to 6144 and `_parse_findings` walks the array collecting complete `{}` objects.

### 4.3 JSON-encoded source excerpts *(fixed in `90c6a9a`)*

The original prompt put source code inside a JSON-encoded user payload, so newlines and quotes were escaped. Models had to mentally re-parse the source. Findings density jumped from 0–9 per cluster to 10/10 per cluster after switching to fenced-code blocks per representative file via `_format_subsystem_message`.

### 4.4 Body-only diff applicator *(fixed in `90c6a9a`)*

`_apply_diff` rebuilt each file from hunk lines alone, so a partial hunk like `@@ -40,9 +40,10 @@` against a 60-line file produced a 10-line file. Fix: `_splice_hunks` fuzzy-locates each hunk and splices in place, preserving out-of-hunk lines.

### 4.5 Symbol-sparse files invisible to RAG *(fixed post-`90c6a9a`)*

Files like `Upd_S_Map_AddsW10_Trans_Test_Local.Cmd` had 3 GOTO-label "function" symbols at lines 6/10/81. The chunker counted them as having symbols → skipped the file_overview emit. Result: the body of the file (Xcopy/icacls calls) was invisible to RAG. Fix: `_create_chunks` now emits a `file_overview` chunk (up to 200 lines) for **every** eligible file, regardless of symbol presence.

### 4.6 Vector-only retrieval blind spot for batch/shell content *(fixed in `df9d61c`)*

`nomic-embed-text` (137M params, F16, the CPU-friendly Codespace choice) ranks token-dense legacy content like `.Cmd` batch scripts at ~position 925/2501 even when the query contains literal terms (`Xcopy`, `batch`, `icacls`). LISP functions named `Upd_INI`/`UpdDivINI` outrank actual deploy scripts because "INI"/"Update" reads as more deployment-adjacent in the embedder's training distribution.

Fix: `scripts/rag_query.py` adds a BM25 keyword path over an in-memory FTS5 index (built per-call, sub-second over 2501 chunks) and fuses with vector via standard Reciprocal Rank Fusion (k=60). `--mode hybrid` is now the default. Pure `--mode vector` and `--mode keyword` are still selectable for debugging.

### 4.7 Path / extension awareness gap *(fixed in `0e435e8`)*

Hybrid retrieval still failed type-narrow questions because neither vector nor full-content BM25 indexes file paths. "What .vbs scripts exist?" returned 0 .vbs files in top-8 (the .vbs files exist but their *content* doesn't contain the literal token "vbs"). "What's different between 19.0 and Div_Map archive?" returned 0 chunks from `19.0/*.cs` because BM25 over the combined pool over-weighted Div_Map content.

Fix: `scripts/rag_query.py` adds a third retrieval source filtered to `file_path LIKE`-matching chunks. Patterns are extracted from the query at runtime — `.vbs`/`.cs`/`.lsp`/etc. via regex, plus distinctive directory segments (length ≥ 5 or contains a digit) pulled from the manifest. When multiple patterns are detected, retrieval interleaves top-N per pattern and a coverage-guarantee step force-includes the per-pattern top-1 if absent. Path source has weight 2.0 in the weighted RRF.

A draft also included a generic `unc_path` regex matching `\\X\Y` patterns in any source file. It produced 800 false positives from LISP-escaped local Windows paths like `"C:\\Data\\file"`. **Removed.** If a future codebase has literal `\\server\share` strings, add the pattern back with a lookbehind: `(?<=["'\s])\\{2,4}[a-zA-Z][\w-]+\\{1,2}[\w.$-]+`.

### 4.8 Secret-shaped content invisible to RAG *(fixed in `80ed18b`)*

Hardcoded credentials, AES keys, PBKDF2 salts, and network-share calls live inside larger function chunks. A natural-language query like "Where are hardcoded credentials?" doesn't lexically match the surrounding function body, so BM25 and vector both miss them.

Fix: `core/knowledge.py` `_extract_secret_chunks()` emits a third chunk family — `chunk_type='secret_pattern'`, short context-windowed (line ± 5) — for regex matches: `aes_byte_array`, `connection_string`, `credential_assignment`, `network_share_call` (`MapDrive "M:", "server", "share"` idiom — much more reliable than UNC literal matching), `aws_access_key`, `jwt_token`, `auth_url`. Multiple labels matching one line collapse into a single chunk with joined symbol_name (e.g. `connection_string+credential_assignment`).

Retrieval also adds a `secret` source: when the query mentions credentials/passwords/encryption/network-share keywords (see `_SECRET_QUERY_KEYWORDS`), a 4th BM25 pool restricted to `chunk_type='secret_pattern'` is fused into RRF with weight 2.0.

For incremental adoption when only the secret patterns change, run `scripts/add_secret_chunks.py` instead of full `rechunk_session.py` — embeds only the new ~20-50 chunks rather than all ~2500.

### 4.9 Vector pollution on short single-symbol queries *(fixed in `bbb08b8`)*

Queries like "What does C:MakXCopFils do?" are short and not semantically rich. Vector retrieval pads top-K with `.sln` boilerplate (`TeamFoundationVersionControl`, `SolutionProperties`, etc.) that has no relation to the asked symbol. Even though the symbol IS at kw#1 from BM25, RRF places the boilerplate ahead of it.

Fix: `scripts/rag_query.py` adds an opt-in `--rerank` flag. After hybrid+path+secret fusion, the top-N candidates (default 20) are sent to Claude Haiku 4.5 with a structured "score 0-100 by relevance" prompt; results re-sorted by reranker score. On any failure (API error, malformed output, length mismatch) the function falls back to RRF order — reranking is never worse than not reranking. Default off because each call adds ~$0.005 + ~1-2s; opt in for precision-critical queries or single-symbol questions.

Bug fix worth recording: build the reranker prompt with f-strings, not `str.format()`. Chunk content routinely contains literal `{}` from C# array initializers (`new byte[] { 0x49, ... }`), JSON, dict literals — `.format()` raises `ValueError: Single '}' encountered`.

---

## 5. RAG querying patterns

The post-run RAG layer is a first-class deliverable, not a debug aid. Use it.

### 5.1 Pipeline overview

`scripts/rag_query.py` is a hybrid retriever with up to four parallel sources, fused via weighted Reciprocal Rank Fusion (k=60), with an optional LLM reranker on top:

```
                                       ┌────► retrieve_vector  (Ollama nomic-embed-text → sqlite-vec)
                                       │
                                       ├────► retrieve_keyword (in-memory FTS5 BM25 over chunk_type+
                                       │                        symbol_name+content)
                          query  ─────►├
                                       ├────► retrieve_path_filtered  (when query mentions an
                                       │      [auto-fired]            extension or distinctive
                                       │                              directory segment, weight=2.0)
                                       │
                                       └────► retrieve_typed=secret_pattern  (when query mentions
                                              [auto-fired]                    credential/password/
                                                                              network-share/etc.,
                                                                              weight=2.0)
                                                            │
                                       weighted RRF fusion ◄┘
                                                            │
                                       optional --rerank ◄──┤  (Claude Haiku 4.5, scores 0-100)
                                                            │
                                                       top-K out
```

Hybrid (`vec + kw`) is the default. The `path` and `secret` sources auto-fire based on query content; you don't need to flag them. Reranking is opt-in.

### 5.2 Direct script

```bash
cd /workspaces/ALARMv3

# Default: hybrid + path/secret auto-detection
.venv/bin/python scripts/rag_query.py \
  --db /workspaces/<NAME>_ALARMv3/.alarmv3/sessions/<id>/analysis.db \
  --query "where is Oracle authentication handled?" \
  --top-k 8

# Add --rerank for precision-critical queries (single-symbol questions,
# short queries, or any case where you need to filter vector noise):
.venv/bin/python scripts/rag_query.py --db <db> --rerank \
  --query "What does C:MakXCopFils do?"

# --raw skips the LLM answer and shows only the retrieved chunks +
# trace metadata (which sources contributed, RRF rank in each, fused
# score). Use for debugging or when you want chunks for downstream tools.
.venv/bin/python scripts/rag_query.py --db <db> --raw --query "..."

# Force a single retrieval mode (debugging only):
.venv/bin/python scripts/rag_query.py --db <db> --mode vector --query "..."
.venv/bin/python scripts/rag_query.py --db <db> --mode keyword --query "..."

# Disable the path/secret auto-sources (debugging only):
.venv/bin/python scripts/rag_query.py --db <db> --no-path-aware --query "..."
```

### 5.3 Trace tags in `--raw` output

Each chunk is annotated with which sources ranked it and at what rank:

| Tag | Meaning |
|---|---|
| `[vec vec#3]` | Only vector retrieval surfaced this chunk; rank 3 in vec list |
| `[kw kw#1]` | Only BM25 keyword retrieval; rank 1 |
| `[kw+vec kw#5,vec#2]` | Both vector and keyword sources agreed (high-confidence hit) |
| `[path path#1]` | Only the path-filtered source (query mentioned a file extension or directory) |
| `[kw+path+vec ...]` | Three-way agreement (typically the strongest signal) |
| `[secret secret#1]` | Only the secret-typed source (query mentioned credentials/passwords/etc.) |
| `[path-forced path-forced#1]` | Coverage-guarantee force-include; per-pattern top-1 was missing from RRF top_k |
| `[rerank rerank#1]` | Reranker-promoted (only present when `--rerank` is on) |

Use the trace to debug ranking surprises: if a chunk you expected isn't in top_k, `--top-k 30` and look at where it ranked in each source.

### 5.4 Useful seed queries (validated on ADDS — final scorecard 7/7 ✅)

| Question | Auto-fires | What surfaces |
|---|---|---|
| "Where is authentication initiated?" | — | Login/credential modules at top |
| "Show me SQL injection via concatenation" | secret | `Password=" + var + "` patterns + the connection-string sites |
| "How do the deployment scripts (.Cmd files) sync files?" | path, secret | `.Cmd` file_overviews + `MapDrive` calls in VBS launchers |
| "What .vbs scripts exist and what do they do?" | path | All .vbs file_overviews dominate top-K |
| "Where are hardcoded credentials, passwords, or connection strings?" | secret | `secret_pattern` chunks: `EncryptionKey =`, PBKDF2 salts, `Data Source=...Password=` |
| "What network shares and UNC paths are referenced?" | secret | `MapDrive "M:", "server", "share"` calls |
| "What does `<symbol>` do?" | — (use `--rerank`) | Single-symbol queries need rerank to suppress `.sln` / boilerplate noise |
| "Differences between 19.0/.cs and Div_Map archive?" | path | Both halves of the comparison via per-pattern coverage |
| "What are the highest-severity security/reliability risks?" | — | Cross-cutting synthesis — vector + kw agreement surfaces the hot spots |

### 5.5 What the RAG layer is NOT good at

- **"How many X exist?"** counting questions — vector search doesn't aggregate. Query analysis.db directly via SQL.
- **"What changed between commit A and B?"** — use `git log` / `git diff`.
- **Cross-language call graph** — the dependency_edge table is sparse (csharp `using` only, no LISP call edges yet).
- **Multi-codebase comparisons across sessions** — each `analysis.db` is per-session. Cross-session questions need joining DBs manually.

---

## 6. After the run

- [ ] Generate the wiki: `scripts/generate_full_wiki.py --db <db> --session-id <id> --source-root <src> --out /workspaces/<NAME>_ALARMv3/wiki/<NAME>_wiki.md`.
- [ ] Commit artifacts to the workspace repo (`<NAME>_ALARMv3`):
      - `.alarmv3/sessions/<id>/{analysis.db,recommendations.md,evaluation_report.md,manifest.json,summary.json}`
      - `.alarmv3/policy/autopilot.yaml`
      - `wiki/<NAME>_wiki.md`
- [ ] If the workspace repo is a sibling of the codespace's primary, push with the user-token override:
      ```
      env -u GITHUB_TOKEN -u GH_TOKEN git push origin main
      ```
- [ ] Add a `.gitignore` excluding `*.failed_run*/`, `*.pre_migration_backup`, `*.pre_rechunk_backup`, `*.subset_only_backup`.
- [ ] Update memory: any new silent-failure path → file under `feedback_*.md`. New domain detail about the codebase → `project_*.md`.

---

## 7. Driving a modernization plan from RAG output (validated 2026-04-29)

The RAG layer is also useful as the discovery surface for downstream
modernization planning. The pattern that worked for ADDS:

1. **Read the .csproj / .sln / app.config directly** before RAG — these
   are tiny and faster than RAG. Capture the framework version, NuGet
   state (or absence), reference paths, and source-control bindings.
2. **Run 8-12 targeted RAG queries** with `--rerank` covering the
   runtime patterns that .csproj alone doesn't reveal:
   - Database integration (driver, query construction, parameter use)
   - Plugin host API surface (managed namespaces, P/Invoke entries)
   - Cross-language interop (e.g. LISP/C# bridge in ADDS)
   - UI patterns (form lifecycle, data binding, modal usage)
   - Authentication and credential storage end-to-end
   - Threading and async patterns
   - Configuration loading (config files, hardcoded paths)
   - Deployment / install chain
   - Plugin entry point and command registration
   - LISP/secondary-language scope (file count, line counts, ownership)
   - Test infrastructure (frameworks, fixtures)
3. **Pull the existing recommendation table from the deep-analysis run**
   via `SELECT id, title, severity, effort, rationale FROM
   recommendation ORDER BY rank LIMIT 20` — this is the
   adversarially-evaluated ranked finding list. Use it as a sanity
   check for the plan's scope, not as the plan itself.
4. **Produce a four-section plan**:
   - Current state baseline (factual table; RAG-cited)
   - Target state table
   - **Forced vs optional changes** — the central strategic insight
     that prevents the migration from becoming a rewrite
   - Phased plan with per-phase deliverables, acceptance criteria,
     and an open-questions block

The first ADDS-modernization plan landed at
[`project/adds-modernization-plan.md`](../project/adds-modernization-plan.md).
That plan + the executed code-level migration in
`BraPil/ADDS_modernized_run2` is the canonical example to copy from
when planning the next codebase (BillGen).

**Honest scope statement is mandatory.** A code-level migration
performed in a Linux Codespace cannot build against AutoCAD managed
assemblies, cannot reach Oracle, and cannot validate any
plugin-host-bound code path. The modernization repo's
`Documentation/deferred-validation.md` enumerates every such item.
**Do not declare a migration shipped until every box in that file is
checked.**

---

## 8. BillGen-specific notes (TODO when starting)

This section is empty until the first BillGen run. Planned additions:
- Domain summary (one paragraph — what BillGen does, sourced from code or docs)
- Expected eligible-file count after binary blocklist
- Anything BillGen-specific the analyzer doesn't know (custom languages, calling conventions, build system gotchas)
- Inputs the autopilot policy should be tightened for (e.g. "block any change touching billing-rate code without explicit accept")

## See also

- [SCHEMA.md](../SCHEMA.md) — wiki conventions
- [project/phase1-implementation.md](../project/phase1-implementation.md) — engine internals
- [project/phase2-plan.md](../project/phase2-plan.md) — RAG layer design
- [project/adds-modernization-plan.md](../project/adds-modernization-plan.md) — the first downstream consumer of the RAG; validated planning template for legacy-codebase modernization
- [tools/ollama-codespaces.md](../tools/ollama-codespaces.md) — Ollama setup
