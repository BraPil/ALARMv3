# Phase 3 Plan: Adversarial Evaluator + AAA Integration
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: phase3, adversarial-evaluator, aaa-integration, risk-scoring

Phase 3 hardens recommendation quality using Cole Medin's Adversarial Dev pattern — a separate evaluator agent that critiques generated recommendations before they are stored. It also wires in AAA persona intelligence during synthesis and adds effort/risk scoring to every recommendation.

## Board of Governors input (2026-04-20)

Asked Cole Medin and the full board (Medin, Weng, Huyen, Willison) via AAA for Phase 3 guidance.

**Cole Medin** (high confidence): Adversarial evaluation is the highest-priority item. The evaluator must be architecturally separated — not a self-review prompt. A single agent grading its own output will suppress real problems while flagging minor ones for credibility (sycophancy bias baked into training). The evaluator's explicit mandate is to *break* what the generator built.

**Board consensus** (strong agreement): Automated adversarial separation is the right pattern. Key tension: fully automated pipelines prevent sycophancy but lack accountability. Willison: humans remain the accountability layer. Resolution: surface the evaluator's critique to the user via a human review gate before recommendations are stored.

## Goals

1. `core/evaluation.py` — `RecommendationEvaluator` with adversarial system prompt, separate from `synthesis.py`
2. AAA integration in `synthesis.py` — call `get_architecture_recommendation` to ground synthesis before evaluation
3. Risk + effort scoring embedded in each recommendation (output of evaluator pass)
4. New MCP tool: `review_recommendations` — surfaces evaluator critique; human accepts or rejects before storage
5. New guardrail state: `RECOMMENDATIONS_PENDING_REVIEW` between `ANALYSIS_COMPLETE` and final `ANALYSIS_COMPLETE` (recommendations accepted)

## Architecture

### Recommendation pipeline (Phase 3)

```
synthesis.py                evaluation.py              mcp/tools.py
────────────                ──────────────             ────────────
_build_context()       →    evaluate(recs, context)  → review_recommendations()
  + AAA grounding call         adversarial critique       human gate
  → draft recommendations      risk + effort scores       accept / reject
                               → RECOMMENDATIONS_         stores accepted recs
                                 PENDING_REVIEW state
```

### LLM boundary preserved

`synthesis.py` continues to be the only module that calls Claude for generation. `evaluation.py` calls Claude for evaluation — same boundary, separate call, separate system prompt, separate context. Neither module sees raw source files.

### AAA grounding call (in `synthesis.py`)

Before drafting recommendations, `synthesis.py` calls `get_architecture_recommendation` via the AAA MCP server with the semantic graph summary as the problem statement. The returned recommendation is appended to the synthesis prompt as grounded context. This is optional/degradable — if AAA is unavailable, synthesis continues without it.

## New module: `core/evaluation.py`

```python
class RecommendationEvaluator:
    """Adversarial critic. Separate from synthesis.py — never self-reviews."""

    SYSTEM_PROMPT = """You are an adversarial code modernization evaluator.
    Your job is to FIND PROBLEMS with the following recommendations.
    Do not be diplomatic. Flag: vague advice, missing prerequisites,
    underestimated effort, ignored risk, and recommendations that contradict
    the codebase evidence. Score each recommendation on risk (1-5) and
    effort (S/M/L/XL). Return structured JSON."""

    def evaluate(self, recommendations: list[dict], context: dict) -> dict:
        """Critique recommendations; return scores + critique per item."""
```

Returns per-recommendation:
```json
{
  "id": "rec-001",
  "critique": "Effort is underestimated — 47 call sites must be migrated.",
  "risk_score": 4,
  "effort_estimate": "XL",
  "verdict": "revise" | "accept" | "reject"
}
```

## New MCP tool: `review_recommendations`

```python
@mcp.tool()
def review_recommendations(accept_ids: list[str], reject_ids: list[str]) -> dict:
    """Human gate: accept or reject evaluated recommendations.

    The evaluator critique is available via recommendations://evaluated.
    Call this tool after reviewing the critique to store accepted recommendations.
    Requires state: RECOMMENDATIONS_PENDING_REVIEW.
    """
```

## New MCP resource: `recommendations://evaluated`

Surfaces the evaluator's full critique (scores, verdicts, critique text) so the user can review it before calling `review_recommendations`.

## Guardrail state machine change

```
ANALYSIS_COMPLETE
  → RECOMMENDATIONS_PENDING_REVIEW   (generate_recommendations completes; evaluator ran)
  → ANALYSIS_COMPLETE (accepted)     (review_recommendations called; recs stored)
  → IMPLEMENTATION_PLANNED           (existing: user approves recs for implementation)
```

## Risk + effort scoring schema

Added to the `recommendation` table in `analysis.db`:

| Column | Type | Notes |
|--------|------|-------|
| `risk_score` | INTEGER | 1–5 from evaluator |
| `effort_estimate` | TEXT | S / M / L / XL |
| `evaluator_critique` | TEXT | Full critique text |
| `evaluator_verdict` | TEXT | accept / revise / reject |
| `review_status` | TEXT | pending / accepted / rejected (human decision) |

## New test files

| File | Coverage |
|------|---------|
| `tests/unit/test_evaluation.py` | Evaluator call, schema validation, verdict parsing |
| `tests/unit/test_mcp_tools_phase3.py` | `review_recommendations` state gate, accept/reject flow |
| `tests/integration/test_adversarial_pipeline.py` | Full synthesis → evaluate → review on sample_repo |

## AAA availability contract

`synthesis.py` wraps the AAA call in `try/except`. If AAA MCP is unavailable or returns an error, synthesis proceeds without grounding — no crash, no state corruption. The grounding call is logged in the audit log either way.

## Implementation order

1. `core/evaluation.py` — `RecommendationEvaluator` with schema + adversarial prompt
2. `core/index.py` — add risk/effort/critique columns to `recommendation` table
3. `synthesis.py` — add AAA grounding call (optional/degradable)
4. `synthesis.py` → `evaluation.py` pipeline — wire evaluator after draft generation
5. `core/guardrails.py` — add `RECOMMENDATIONS_PENDING_REVIEW` state + transitions
6. `mcp/tools.py` — `review_recommendations` tool
7. `mcp/resources.py` — `recommendations://evaluated` resource
8. Tests

## See also

- [Phase 2 Plan](phase2-plan.md) — RAG layer (prerequisite)
- [Cole Medin Persona](../personas/cole-medin.md) — Adversarial Dev pattern source
- [Board Decisions](../architecture/board-decisions.md) — Decision #6: AAA always co-present
- [AAA + ALARMv3 Strategy](aaa-alarmv3-strategy.md) — AAA as grounding layer
