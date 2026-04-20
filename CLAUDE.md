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
│   ├── artifacts.py     Markdown/JSON output writers
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

`synthesis.py` calls Claude. Nothing else calls Claude. The LLM receives the
**semantic graph** (SQLite query results), not raw source files.

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

## Phase roadmap

| Phase | Scope | Key deliverable |
|-------|-------|----------------|
| 1 (current) | Attach → Map → Analyze → Recommend | Working MCP + CLI, 6 languages |
| 2 | sqlite-vec RAG, query_codebase tool | Natural language Q&A over codebase |
| 3 | Risk-weighted priority, AAA integration | Effort estimates, persona recommendations |
| 4 | Implementation mode | Adversarial Dev pattern, separate cloned dir |
| 5 | Continuous mode, SharePoint sync | Re-run on commit, team features |
