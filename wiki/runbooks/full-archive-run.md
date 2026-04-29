# Full-archive run runbook

> **Status**: current
> **Last updated**: 2026-04-28
> **Tags**: operations, runbook, regression-checklist, lessons-learned

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
- [ ] Read-only enforced — no local writes. If the source repo's local `origin` push URL points at a writable remote, replace with `DISABLE_PUSH_TO_READ_ONLY_ARCHIVE` to neutralise it (see [reference_codespace_git_push.md](../../../home/codespace/.claude/projects/-workspaces-ALARMv3/memory/reference_codespace_git_push.md)).
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

---

## 5. RAG querying patterns

The post-run RAG layer is a first-class deliverable, not a debug aid. Use it.

### 5.1 Direct script

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/rag_query.py \
  --db /workspaces/<NAME>_ALARMv3/.alarmv3/sessions/<id>/analysis.db \
  --query "where is Oracle authentication handled?" \
  --top-k 8
```

### 5.2 Useful seed queries (validated on ADDS)

| Question | What to look for in retrieval |
|---|---|
| "Where is authentication initiated?" | Login/credential modules at top |
| "Show me SQL injection via concatenation" | `WHERE ... = '" + xxx + "'` patterns |
| "How does the deployment script copy files?" | Batch/PowerShell scripts with `xcopy`/`robocopy` |
| "What modernization opportunities exist in language X?" | High-LOC files in subsystem X |
| "Where are credentials hardcoded?" | INI/config files + connection-string assemblies |

### 5.3 What the RAG layer is NOT good at

- **"How many X exist?"** counting questions — vector search doesn't aggregate.
- **"What changed between commit A and B?"** — use `git log` / `git diff`.
- **Cross-language call graph** — the dependency_edge table is sparse (csharp `using` only, no LISP call edges yet).

For aggregation/counting, query the analysis.db directly via SQL.

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

## 7. BillGen-specific notes (TODO when starting)

This section is empty until the first BillGen run. Planned additions:
- Domain summary (one paragraph — what BillGen does, sourced from code or docs)
- Expected eligible-file count after binary blocklist
- Anything BillGen-specific the analyzer doesn't know (custom languages, calling conventions, build system gotchas)
- Inputs the autopilot policy should be tightened for (e.g. "block any change touching billing-rate code without explicit accept")

## See also

- [SCHEMA.md](../SCHEMA.md) — wiki conventions
- [project/phase1-implementation.md](../project/phase1-implementation.md) — engine internals
- [project/phase2-plan.md](../project/phase2-plan.md) — RAG layer design
- [tools/ollama-codespaces.md](../tools/ollama-codespaces.md) — Ollama setup
