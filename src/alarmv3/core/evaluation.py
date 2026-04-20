"""Adversarial recommendation evaluator (Phase 3).

Architecturally separated from synthesis.py by design — a single agent
grading its own output suppresses real problems while flagging minor ones
for credibility (Cole Medin: sycophancy bias baked into training).

This module calls Claude with an adversarial mandate: find problems, not
confirm correctness. It never reads raw source files; it receives only the
draft recommendations and the same context dict that synthesis.py assembled.
"""

import json
import sqlite3

import anthropic

from .session import Session

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_EVALUATOR_SYSTEM_PROMPT = """\
You are an adversarial code modernization auditor. Your job is to FIND PROBLEMS
with a set of AI-generated modernization recommendations.

Be critical and specific. For each recommendation, evaluate:
1. Is the advice vague or overly generic? (flag it)
2. Is the effort estimate realistic? Underestimated effort is the most common failure.
3. Are there missing prerequisites or hidden dependencies?
4. Does the recommendation contradict or ignore evidence in the codebase data?
5. Could this recommendation cause harm if applied naively?

For each recommendation provide:
- rank: the same rank integer as the input recommendation
- critique: 1-3 sentences identifying the specific problem(s), or "No significant issues." if solid
- risk_score: integer 1-5 (1=low risk to apply, 5=high risk — could break things)
- evaluator_effort: your effort estimate — S (hours), M (days), L (week), XL (weeks+)
- verdict: "accept" (solid, apply as-is), "revise" (good idea, needs adjustment), \
"reject" (fundamentally flawed or harmful)

Return ONLY a valid JSON array — no explanation text outside the array. \
One object per recommendation, same order as input:
[
  {
    "rank": 1,
    "critique": "...",
    "risk_score": 3,
    "evaluator_effort": "L",
    "verdict": "accept"
  }
]\
"""


class RecommendationEvaluator:
    """Adversarial critic agent — architecturally separated from Synthesizer."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    def evaluate(self, recommendations: list[dict], context: dict) -> list[dict]:
        """Critique recommendations and return per-item evaluations.

        Returns a list of evaluation dicts (same length as recommendations),
        each containing rank, critique, risk_score, evaluator_effort, verdict.
        On any Claude failure, returns a degraded list of pending evaluations.
        """
        if not recommendations:
            return []
        try:
            return self._call_claude(recommendations, context)
        except Exception:
            return _fallback_evaluations(recommendations)

    def store_evaluations(self, evaluations: list[dict]) -> None:
        """Write evaluator results back to the recommendation rows."""
        if not evaluations:
            return
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for ev in evaluations:
                conn.execute(
                    "UPDATE recommendation SET "
                    "risk_score=?, evaluator_effort=?, evaluator_critique=?, evaluator_verdict=? "
                    "WHERE session_id=? AND rank=?",
                    (
                        ev.get("risk_score"),
                        ev.get("evaluator_effort"),
                        ev.get("critique", ""),
                        ev.get("verdict", "pending"),
                        self._session.session_id,
                        ev.get("rank"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_evaluated_recommendations(self) -> list[dict]:
        """Return all recommendations with their evaluator annotations."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT rank, category, severity, title, description, affected_files, "
                "effort, rationale, risk_score, evaluator_effort, evaluator_critique, "
                "evaluator_verdict, review_status "
                "FROM recommendation WHERE session_id=? ORDER BY rank",
                (self._session.session_id,),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["affected_files"] = json.loads(d["affected_files"])
            result.append(d)
        return result

    # ── LLM call ───────────────────────────────────────────────────────────

    def _call_claude(self, recommendations: list[dict], context: dict) -> list[dict]:
        client = anthropic.Anthropic()

        user_content = (
            "## Codebase context\n\n"
            f"{json.dumps(context, indent=2)}\n\n"
            "## Draft recommendations to evaluate\n\n"
            f"{json.dumps(recommendations, indent=2)}"
        )

        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": _EVALUATOR_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )

        text = message.content[0].text
        return _parse_evaluations(text)


def _parse_evaluations(text: str) -> list[dict]:
    """Extract JSON array from Claude's evaluator response."""
    start = text.find("[")
    end = text.rfind("]") + 1
    if start < 0 or end <= start:
        return []
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return []


def _fallback_evaluations(recommendations: list[dict]) -> list[dict]:
    """Return placeholder evaluations when the evaluator call fails."""
    return [
        {
            "rank": rec.get("rank", i + 1),
            "critique": "Evaluator unavailable — manual review required.",
            "risk_score": None,
            "evaluator_effort": None,
            "verdict": "pending",
        }
        for i, rec in enumerate(recommendations)
    ]
