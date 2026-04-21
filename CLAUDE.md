# CLAUDE.md — ALARMv3

ALARMv3 is a legacy code modernization assistant. MCP-first interaction surface over a pure Python core engine.

## Quick commands

```bash
uv sync                               # Install all dependencies
uv run alarmv3-mcp                    # Run MCP server (stdio)
uv run alarmv3 analyze /path/to/repo  # Run full analysis via CLI
uv run alarmv3 init-config            # Initialize .alarmv3/config.yaml
uv run pytest tests/                  # Run tests
uv run ruff check src/                # Lint
```

## Architecture — three non-negotiable layers

```
src/alarmv3/
├── core/          Pure Python. ZERO MCP dependency. Testable in isolation.
│   ├── guardrails.py    State machine + WORM audit log (THE safety layer)
│   ├── session.py       SQLite session + work queue (WAL mode)
│   ├── index.py         SQLite schema definitions + init helper
│   ├── discovery.py     FileScanner — language detection, manifest building
│   ├── analysis.py      tree-sitter parsing, dependency graph, complexity
│   ├── synthesis.py     Claude API — recommendation generation ONLY
│   ├── knowledge.py     Chunking + Ollama embeddings + sqlite-vec (Phase 2)
│   ├── evaluation.py    Adversarial evaluator — separate Claude call (Phase 3)
│   ├── implementation.py Plan/build/eval pipeline + git commit to TARGET (Phase 4)
│   ├── artifacts.py     Markdown/JSON output writers
│   ├── language_researcher.py  Runtime grammar inference for unknown extensions (Phase 7)
│   └── orchestration.py ThreadPoolExecutor harness + SQLite work queue
├── mcp/           Thin wrapper. Delegates ALL logic to core. No business logic here.
│   ├── server.py        FastMCP entry point (stdio Phase 1; HTTP planned Phase 3)
│   ├── tools.py         6 tools — every call state-gated by guardrails
│   ├── resources.py     3 resources — session / manifest / recommendations
│   └── prompts.py       2 guided workflows
├── adapters/sync/ Pluggable I/O. Core uses base.py interface, never concrete classes.
│   ├── base.py          SyncAdapter ABC
│   └── localfs.py       LocalFS (SharePoint deferred to Phase 5)
└── cli/
    └── main.py          Click CLI wrapping the same core engine as MCP
```

## Dependency rules — enforced, not advisory

```
mcp/     → core/      ✓
core/    → adapters/  ✓  (via SyncAdapter interface only)
adapters/ → core/     ✗  NEVER
mcp/     → adapters/  ✗  NEVER
cli/     → core/      ✓
```

## Guardrail state machine

Every MCP tool call is rejected if the session is in the wrong state. No exceptions.

```
UNATTACHED
  → ATTACHED                        (attach_repository)
  → READ_ONLY_CONFIRMED             (confirm_guardrails — mandatory human gate)
  → ANALYSIS_IN_PROGRESS            (start_full_mapping)
  → RECOMMENDATIONS_PENDING_REVIEW  (generate_recommendations — evaluator ran)
  → ANALYSIS_COMPLETE               (review_recommendations — human accepted/rejected)
  → IMPLEMENTATION_PLANNED          (Phase 4: user approves specific recs)
  → WORKING_REPO_READY              (Phase 4: target directory created)
```

## The four trust zones

| Zone | Path | Rule |
|------|------|------|
| SOURCE | attached legacy repo | READ-ONLY. No writes. No execution. Ever. |
| ARTIFACT | `.alarmv3/sessions/<id>/` | Engine writes here only. |
| TARGET | modernization directory | Gated behind IMPLEMENTATION_PLANNED state. |
| GOVERNANCE | `.alarmv3/policy/` | Human writes only. Engine reads. |

## LLM boundary (board decision — do not violate)

`synthesis.py` and `implementation.py` call Claude. Nothing else calls Claude.
The LLM receives the **semantic graph** (SQLite query results), not raw source files.

```
deterministic: file discovery, AST parsing, dependency graph, complexity metrics, chunking
LLM-powered:   architecture pattern recognition, recommendations text, risk narrative
```

## Language support (Phase 1)

| Language | Parser | Priority | Notes |
|----------|--------|----------|-------|
| C++ | tree-sitter-cpp | HIGH | First real target |
| Visual Basic | regex fallback | HIGH | First real target; no PyPI grammar |
| Python | tree-sitter-python | Standard | |
| JS/TS | tree-sitter-javascript/typescript | Standard | |
| Java | tree-sitter-java | Standard | |
| C# | tree-sitter-c-sharp | Standard | |

`Analyzer._init_parsers()` catches `ImportError` for each parser individually — missing
parsers silently degrade; they never block startup.

## Storage layout

```
.alarmv3/                    ← gitignored
├── session.db               # Session state + work queue (SQLite WAL)
├── config.yaml              # User config
├── memory.db                # Phase 5: cross-session project memory (conventions, decisions)
├── crossrepo.db             # Phase 5: cross-repo dependency registry
├── policy/
│   └── autopilot.yaml       # Phase 5: auto-acceptance rules (GOVERNANCE — human-written)
└── sessions/<uuid>/
    ├── analysis.db          # Manifest, symbols, graph, chunks, recommendations
    └── audit.log            # WORM append-only log (never truncate this)
```

## External services

| Service | Used by | Config |
|---------|---------|--------|
| Claude API | `synthesis.py` | ANTHROPIC_API_KEY env var |
| Ollama (localhost:11434) | `knowledge.py` (Phase 2) | nomic-embed-text model |
| AAA MCP server | via `.mcp.json` | always co-present in Codespaces |

## Adding a language parser

1. Add `".ext": "langname"` to `LANGUAGE_MAP` in `discovery.py`
2. Add `langname` to `PHASE_1_LANGUAGES` in `discovery.py`
3. Add `try/except ImportError` parser init in `Analyzer._init_parsers()` in `analysis.py`
4. Add `_langname_extractor` function in `analysis.py`
5. Register it in `_EXTRACTORS` dict in `analysis.py`
6. Add PyPI package to `pyproject.toml` dependencies

## Register ALARMv3 MCP in .mcp.json (when ready)

```json
"alarmv3": {
  "command": "uv",
  "args": ["run", "alarmv3-mcp"],
  "env": { "ALARMV3_WORKSPACE": "${workspaceFolder}" }
}
```

## Phase 5: architecture

### New core modules

| Module | Purpose |
|--------|---------|
| `core/memory.py` | `ProjectMemory` — `.alarmv3/memory.db`, cross-session conventions/decisions/anti-patterns. Injected into synthesis and planner prompts. |
| `core/autopilot.py` | `AutopilotPolicy` — reads `.alarmv3/policy/autopilot.yaml` (GOVERNANCE). `should_auto_accept(category, risk_level, effort)` gates auto-commit. Every auto-accept is audit-logged. |
| `core/crossrepo.py` | `CrossRepoRegistry` — `.alarmv3/crossrepo.db`. Register repos, match external deps against other repos' exported symbols. |

### New MCP tools (Phase 5)

| Tool | State gate | Purpose |
|------|-----------|---------|
| `implement_batch` | WORKING_REPO_READY | Parallel plan/build/eval using ThreadPoolExecutor; groups independent items |
| `record_project_memory` | any | Write a convention/decision/antipattern/pattern to persistent memory |
| `list_project_memory` | any | List all memory entries, optionally filtered by category |
| `get_autopilot_policy` | any | Show policy; writes template if absent |
| `register_repo` | ANALYSIS_COMPLETE+ | Register this repo's exported symbols in cross-repo registry |
| `query_cross_repo` | ANALYSIS_COMPLETE+ | Find coupled repos by matching external deps against registry |

### Parallel batch design (`implement_batch`)

Items are partitioned into batches by file overlap: items with no shared `affected_files`
run concurrently in the same batch; items that share files are serialised into the next
batch. Within each batch a `ThreadPoolExecutor` runs the full plan→build→eval pipeline
per item. Autopilot auto-accepts eligible results without a human gate.

### Autopilot safety invariants

1. Disabled by default — the policy file must explicitly set `enabled: true`.
2. Only `approve` or `flag` evaluator verdicts qualify; `reject` always requires human review.
3. Every auto-acceptance is written to the WORM audit log (`AUTOPILOT_ACCEPT` event).
4. The policy file lives in the GOVERNANCE zone — the engine reads it, never writes the rules.

## Phase 6: deep analysis engine

`core/deep_analysis.py` — exhaustive multi-pass synthesis replacing the single statistical digest.

### Architecture

```
SubsystemPartitioner
  └─ union-find on dependency_edge graph
  └─ every eligible file lands in exactly one subsystem
  └─ excess clusters merged into a 'remaining' bucket (max_subsystems cap)

DeepSynthesizer — four phases:
  A. partition    → subsystem table
  B. per-subsystem Claude calls → subsystem_finding (all symbols + edges per cluster)
  C. complexity-tier pass       → subsystem_finding (outlier files: cyclomatic/coupling threshold)
  D. aggregation pass           → recommendation table (deduplication + ranking)
  + adversarial evaluator (reused from Phase 3)
```

### Coverage guarantee

Every eligible file is assigned to exactly one subsystem by union-find. Coverage is tracked
in `analysis_coverage` per file per pass. The `run_deep_analysis` tool reports `coverage_pct`
so gaps are visible, not silent.

### New MCP tool

| Tool | State gate | Purpose |
|------|-----------|---------|
| `run_deep_analysis` | ANALYSIS_IN_PROGRESS | Background multi-pass synthesis; returns job_id |

Parameters: `max_subsystems` (default 15, max 30), `cyclomatic_threshold` (default 10),
`coupling_threshold` (default 10). After completion, same review flow as `generate_recommendations`.

### New DB tables (analysis.db per session)

| Table | Purpose |
|-------|---------|
| `subsystem` | Cluster metadata: name, file list, LOC, avg complexity |
| `subsystem_finding` | Raw Claude findings per pass before aggregation |
| `analysis_coverage` | Per-file coverage tracking across pass types |

## Phase 7: runtime language researcher

`core/language_researcher.py` — three-tier self-improving language support for unknown extensions
(AutoLISP `.lsp/.dcl`, PowerShell `.ps1/.psm1`, COBOL, MUMPS, etc.).

### Architecture

```
Tier 1 — detection (unchanged discovery.py)
  └─ unknown-extension files marked is_eligible=0, language=NULL in manifest

Tier 2 — runtime inference (LanguageResearcher)
  └─ groups ineligible files by extension
  └─ checks language_grammar cache (session-local) → ProjectMemory (cross-session)
  └─ if no cache: samples up to 5 files, sends to Claude → grammar descriptor
       grammar: {language_name, function_patterns[], class_patterns[], import_patterns[], notes}
  └─ applies patterns line-by-line to ALL files of that extension
  └─ writes inferred symbols → symbol table (symbol_type='inferred_function' | 'inferred_class')
  └─ writes inferred deps   → dependency_edge table (dep_type='inferred_import')
  └─ marks files is_eligible=1 so downstream passes include them

Tier 3 — validated persistence
  └─ if symbol yield ≥ 3 AND names pass _PLAUSIBLE_NAME_RE:
       cache grammar in language_grammar table (session-local hit on re-run)
       persist to ProjectMemory category='pattern', key='language/<ext>'
       → future sessions skip the Claude inference step entirely
```

### LLM boundary note

Grammar inference is a meta-task: we feed tiny FILE SAMPLES so Claude can DESCRIBE the syntax.
This is explicitly not architecture analysis. The board rule ("LLM reads semantic graph, not raw
source files") applies to recommendation generation, not to learning what `defun` means in AutoLISP.

### Recommended workflow with deep analysis

```
start_full_mapping(session_id)          → wait complete
research_unknown_languages(session_id)  → wait complete  ← NEW — do this before analysis
run_analysis(session_id)                → wait complete
run_deep_analysis(session_id)           → wait complete
review_recommendations(session_id, ...)
```

### New MCP tool

| Tool | State gate | Purpose |
|------|-----------|---------|
| `research_unknown_languages` | ANALYSIS_IN_PROGRESS | Background grammar inference; returns job_id |

Parameters: `max_samples_per_language` (default 5, max 20), `persist_on_success` (default True).

### New DB table (analysis.db per session)

| Table | Purpose |
|-------|---------|
| `language_grammar` | Cached grammar descriptors (JSON) per extension per session |

---

## Phase roadmap

| Phase | Scope | Key deliverable |
|-------|-------|----------------|
| 1 | Attach → Map → Analyze → Recommend | Working MCP + CLI, 6 languages |
| 2 | sqlite-vec RAG, query_codebase tool | Natural language Q&A over codebase |
| 3 | Risk-weighted priority, AAA integration | Effort estimates, persona recommendations |
| 4 | Implementation mode | Adversarial Dev pattern, separate cloned dir |
| 5 | Persistent memory, autopilot, parallel batch, cross-repo | Enterprise-scale modernization |
| 6 | Deep analysis engine | Exhaustive subsystem-partitioned multi-pass synthesis |
| 7 (current) | Runtime language researcher | Self-improving grammar inference for unknown languages |
| 8 | Continuous mode, SharePoint sync | Re-run on commit, team features |
