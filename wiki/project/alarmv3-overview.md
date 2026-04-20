# ALARMv3 Overview
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: project, alarmv3, vision

An intelligent, actionable legacy modernization assistant — MCP-first, Python, local-first, read-only-by-default.

## What it does

ALARMv3 attaches to a legacy codebase (as a read-only archive), maps it, analyzes it with tree-sitter, and produces prioritized modernization recommendations via Claude. On approval, it creates a separate working repo/worktree to implement selected changes. The analyzed code is **never executed**.

## Core design constraints

- **MCP-first**: primary interface is MCP tools/resources/prompts, not CLI
- **Read-only by default**: source repo is archive; analysis artifacts go to `.alarmv3/`
- **Guardrails are mandatory**: state machine enforces safe progression, WORM-audited
- **LLM boundary (Vasilev Principle)**: Claude sees only SQLite query results, never raw files
- **JSON is source of truth**: Markdown is a human-readable projection
- **Codespaces-friendly**: bounded worker pools (MAX_WORKERS=4), checkpointing, resumable sessions
- **Coverage contract**: `mapped_files == manifest_files`, `analyzed_files == eligible_files`

## Guardrail state machine

```
UNATTACHED → ATTACHED → READ_ONLY_CONFIRMED → ANALYSIS_IN_PROGRESS
→ RECOMMENDATIONS_PENDING_REVIEW → ANALYSIS_COMPLETE
→ IMPLEMENTATION_PLANNED → WORKING_REPO_READY
```

Phase 3 adds `RECOMMENDATIONS_PENDING_REVIEW` between `ANALYSIS_IN_PROGRESS` and `ANALYSIS_COMPLETE` — the adversarial evaluator runs automatically, then `review_recommendations` lets the human accept or reject before recommendations are finalized.

## MCP tools

| Tool | State required | Purpose |
|------|---------------|---------|
| `attach_repository` | UNATTACHED | Bind to legacy codebase, set archive guardrail |
| `confirm_guardrails` | ATTACHED | Explicit human confirmation before deep analysis |
| `start_full_mapping` | READ_ONLY_CONFIRMED | Recursive file discovery, parallel workers |
| `get_job_status` | any | Poll background job progress |
| `run_analysis` | ANALYSIS_IN_PROGRESS | tree-sitter parse, dependency graph, complexity |
| `generate_recommendations` | ANALYSIS_IN_PROGRESS | Claude synthesis → ranked recommendations |
| `query_codebase` | ANALYSIS_COMPLETE+ | *(Phase 2)* Natural language RAG over code |
| `review_recommendations` | RECOMMENDATIONS_PENDING_REVIEW | *(Phase 3)* Human accept/reject gate after adversarial evaluation |

## MCP resources

| URI | Returns |
|-----|---------|
| `session://current` | Current session state and metadata |
| `manifest://files` | All discovered files with language/size |
| `recommendations://latest` | Full ranked recommendation set with review status |
| `recommendations://evaluated` | *(Phase 3)* Recommendations with adversarial critique and scores |

## Storage layout

```
.alarmv3/                       ← gitignored
├── session.db                  # SessionManager state + work queue (SQLite WAL)
├── config.yaml                 # User config
└── sessions/<uuid>/
    ├── analysis.db             # manifest, symbol, dependency, complexity, chunk, recommendation
    └── audit.log               # WORM append-only; never truncate
```

## Four trust zones

| Zone | Path | Rule |
|------|------|------|
| SOURCE | attached legacy repo | READ-ONLY. No writes. No execution. Ever. |
| ARTIFACT | `.alarmv3/sessions/<id>/` | Engine writes here only |
| TARGET | modernization directory | Gated behind IMPLEMENTATION_PLANNED |
| GOVERNANCE | `.alarmv3/policy/` | Human writes only; engine reads |

## Current status

**Phase 3 complete** (2026-04-20). Adversarial evaluator (`core/evaluation.py`), `RECOMMENDATIONS_PENDING_REVIEW` guardrail state, `review_recommendations` MCP tool, `recommendations://evaluated` resource, AAA grounding hook, and 154-test suite.

## See also
- [Phase 1 Implementation](phase1-implementation.md) — what was built, test results, live synthesis output
- [Phase 2 Plan](phase2-plan.md) — RAG layer, query_codebase tool, Ollama integration
- [ALARM Lineage](alarm-lineage.md) — how v1 and v2 informed v3
- [Three-Layer Boundary](../architecture/three-layer-boundary.md) — core/mcp/adapters split
- [Board Decisions](../architecture/board-decisions.md) — locked architectural choices
- [AAA + ALARMv3 Strategy](aaa-alarmv3-strategy.md) — companion project relationship
