# Phase 4 Plan: Implementation Mode
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: phase4, implementation, codegen, git-worktree, plan-build-eval

Phase 4 activates the TARGET zone. After the human has accepted recommendations (state: ANALYSIS_COMPLETE), they select specific items for implementation. The system clones the source into a separate working directory, generates code changes one recommendation at a time through a plan/build/eval loop, and gates every commit behind human review.

The source repo remains permanently read-only. Changes accumulate as discrete git commits in the TARGET directory only.

## Board of Governors input (2026-04-20)

Asked Cole Medin + board consensus (Medin, Huyen, Willison, Weng) + architecture recommendation via AAA.

**Cole Medin** (medium confidence): Three-agent harness (plan/build/eval) with adversarial tension. Harness sits above the agents — it is the reliability layer. Context management is the #1 failure mode (80% of agent failures). Load only the files being changed, not the whole repo. Independent eval agent, never self-review.

**Board consensus** (moderate agreement): Adversarial separation is right. Key tensions: (1) when does human-in-the-loop kick in? Resolution: every commit. (2) Evaluator must not become theatrical — must catch structural issues, not just cosmetic ones.

**Architecture recommendation** (high confidence — Cherny, Rastogi, Vasilev): Git worktrees for isolation. Phase-gated plans with testable acceptance criteria. Minimal MCP surface inside the impl pipeline — use git/linter CLIs via subprocess in core, not heavyweight MCP servers. Human gate before each commit.

**Vasilev note**: "I just deleted all my MCPs. Skills + CLI is all you need." Applied: the implementation pipeline internals use subprocess git/lint rather than MCP composition.

## Goals

1. `core/implementation.py` — `ImplementationPlanner` and `ImplementationRunner` (plan/build/eval loop)
2. `core/index.py` — `implementation_plan` and `implementation_change` tables
3. Git worktree clone of source into TARGET directory (human-specified path)
4. MCP tools: `plan_implementation`, `clone_for_implementation`, `implement_next`, `accept_change`, `reject_change`
5. MCP resources: `implementation://plan`, `implementation://changes`
6. Human gate before every commit — no autonomous writing

## State machine (unchanged structure, new utilization)

```
ANALYSIS_COMPLETE
  → IMPLEMENTATION_PLANNED   (plan_implementation — selects recs, builds plan)
  → WORKING_REPO_READY       (clone_for_implementation — TARGET cloned)
  → WORKING_REPO_READY       (implement_next / accept_change loop stays here)
```

`WORKING_REPO_READY` is the implementation-loop state. It persists until the user is done.

## Architecture: plan/build/eval per change

```
MCP: plan_implementation(session_id, rec_ids)
  └─ ImplementationPlanner.create_plan()
       reads accepted recommendations from DB
       orders by dependency (files shared → tackle shared files first)
       creates one plan_item per recommendation
       → stored in implementation_plan table
       → session transitions to IMPLEMENTATION_PLANNED

MCP: clone_for_implementation(session_id, target_path)
  └─ shutil.copytree(source → target) or git clone/worktree
     target path stored in session metadata
     → session transitions to WORKING_REPO_READY

MCP: implement_next(session_id)
  └─ ImplementationRunner.run_next()
       1. PLAN: load next pending plan_item + its context
          (reads only affected_files from TARGET, not full repo)
       2. BUILD: Claude generates a unified diff for the change
          (Claude sees: recommendation, file content, context)
       3. EVAL: separate Claude call validates the diff
          (does it implement the rec? does it introduce new issues?)
       4. store change as 'pending_review' with diff + eval result
       → returns diff + eval critique to human for review

MCP: accept_change(session_id, change_id)
  └─ applies diff to TARGET files
     git add + git commit in TARGET directory
     marks change 'accepted'
     → returns commit hash

MCP: reject_change(session_id, change_id, feedback)
  └─ discards diff
     stores feedback for retry
     marks change 'rejected_with_feedback'
     → implement_next will retry with feedback injected into context
```

## New module: `core/implementation.py`

```python
class ImplementationPlanner:
    def create_plan(self, rec_ids: list[int]) -> dict:
        """Read accepted recommendations, order by dependency, create plan items."""

class ImplementationRunner:
    PLANNER_PROMPT = "..."  # plan the specific change
    BUILDER_PROMPT = "..."  # generate unified diff
    EVALUATOR_PROMPT = "..."  # adversarial diff review

    def run_next(self) -> dict:
        """Execute plan/build/eval for the next pending item. Returns diff + eval."""

    def apply_change(self, change_id: int) -> str:
        """Apply accepted diff to TARGET files. Returns git commit hash."""
```

## New DB schema (appended to `core/index.py`)

```sql
CREATE TABLE IF NOT EXISTS implementation_plan (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    rec_rank        INTEGER NOT NULL,   -- FK to recommendation.rank
    title           TEXT NOT NULL,
    affected_files  TEXT NOT NULL,      -- JSON array
    order_index     INTEGER NOT NULL,   -- execution order
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | complete | skipped
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS implementation_change (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    plan_item_id    INTEGER NOT NULL,
    diff_text       TEXT,               -- unified diff
    eval_critique   TEXT,               -- evaluator's assessment
    eval_verdict    TEXT,               -- approve | flag | reject
    review_status   TEXT NOT NULL DEFAULT 'pending_review',
    feedback        TEXT,               -- human rejection feedback
    commit_hash     TEXT,               -- set after accept + git commit
    created_at      REAL NOT NULL,
    reviewed_at     REAL
);
```

## Context discipline (Vasilev + Cole Medin)

Each `implement_next` call loads only:
- The recommendation text (title + description + rationale)
- The current content of `affected_files` from the TARGET directory
- The evaluator's critique from the prior failed attempt (if retry)

It does NOT load:
- The full source repo
- Other recommendations
- The full analysis context

This keeps Claude's context lean and prevents cross-contamination between changes.

## LLM boundary (extended)

`synthesis.py` and `evaluation.py` (Phase 3) call Claude for recommendations.
`implementation.py` calls Claude three times per change:
1. **Planner** — scopes the specific change (what exactly needs to change in these files?)
2. **Builder** — generates a unified diff
3. **Impl evaluator** — adversarial review of the diff (separate call, adversarial prompt)

All three calls receive only SQLite-query-assembled context + target file content. Never raw browsing of the source repo.

## New MCP tools summary

| Tool | State required | Purpose |
|------|---------------|---------|
| `plan_implementation` | ANALYSIS_COMPLETE | Select accepted recs, create ordered plan |
| `clone_for_implementation` | IMPLEMENTATION_PLANNED | Clone source to TARGET path |
| `implement_next` | WORKING_REPO_READY | Generate next change (diff + eval), no write |
| `accept_change` | WORKING_REPO_READY | Apply diff, git commit in TARGET |
| `reject_change` | WORKING_REPO_READY | Discard diff, store feedback for retry |

## New test files

| File | Coverage |
|------|---------|
| `tests/unit/test_implementation.py` | ImplementationPlanner, ordering, DB writes |
| `tests/unit/test_mcp_tools_phase4.py` | Tool state gates, accept/reject flow |
| `tests/integration/test_implementation_pipeline.py` | Full plan → implement → accept on sample_repo (mocked Claude) |

## Implementation order

1. `core/index.py` — `implementation_plan` and `implementation_change` tables
2. `core/implementation.py` — `ImplementationPlanner.create_plan()` (no Claude yet)
3. `core/implementation.py` — `ImplementationRunner.run_next()` (Claude calls)
4. `core/implementation.py` — `ImplementationRunner.apply_change()` (diff + git)
5. `mcp/tools.py` — 5 new tools
6. `mcp/resources.py` — `implementation://plan`, `implementation://changes`
7. Tests

## See also

- [Phase 3 Plan](phase3-plan.md) — adversarial evaluator (prerequisite)
- [Cole Medin Persona](../personas/cole-medin.md) — Adversarial Dev pattern
- [Board Decisions](../architecture/board-decisions.md) — Decision #8: TARGET is separate directory
- [AAA + ALARMv3 Strategy](aaa-alarmv3-strategy.md)
