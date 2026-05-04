"""LLM-powered architecture recognition and recommendation generation.

This is the ONLY module that calls Claude. It receives a pre-built context
dict assembled from SQLite query results — it never reads raw source files.

Board decision (Mitko Vasilev): the LLM must operate on the semantic graph,
not on raw files. Feeding 40 repos of raw code to an LLM produces hallucinated
architecture at machine speed.
"""

import json
import sqlite3
import time

import anthropic

from .session import Session

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """\
You are a senior software architect reviewing a legacy codebase for modernization.

Your task is to generate a prioritized list of modernization recommendations based \
on static analysis data provided by the user.

For each recommendation, provide:
- rank: integer (1 = highest priority)
- category: one of: security, modernization, quality, dependency
- severity: one of: critical, high, medium, low
- title: one short line (under 80 chars)
- description: 2–4 sentences explaining the specific issue and fix
- affected_files: list of file paths from the summary
- effort: one of: S (hours), M (days), L (week), XL (weeks)
- rationale: one sentence on why this matters now

Focus on:
1. Security vulnerabilities or outdated dependencies (critical/high)
2. Architectural improvements with high LOC impact (high)
3. Code quality and maintainability (medium)
4. Quick wins that unlock larger refactors (any severity, effort=S)

Return ONLY a valid JSON array — no explanation text outside the array. \
Generate up to 20 recommendations, ordered by priority.

Example format:
[
  {
    "rank": 1,
    "category": "security",
    "severity": "critical",
    "title": "Replace deprecated TLS 1.0 usage in network layer",
    "description": "...",
    "affected_files": ["src/net/socket.cpp"],
    "effort": "M",
    "rationale": "TLS 1.0 is end-of-life and exploitable."
  }
]\
"""


class Synthesizer:
    """Generates recommendations by querying analysis.db and calling Claude."""

    def __init__(self, session: Session, *, synthesis_overlay: "str | None" = None):
        """Args:
            session: ALARMv3 session.
            synthesis_overlay: optional codebase-specific text appended to the
                system prompt. Typically supplied from CodebasePolicy.
                synthesis_overlay; injects domain framing without replacing
                the generic recommendation contract.
        """
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        self._overlay = synthesis_overlay

    def run(self, aaa_grounding: "str | None" = None) -> dict:
        context = self._build_context()
        if aaa_grounding:
            context["aaa_architecture_grounding"] = aaa_grounding
        from .memory import ProjectMemory
        memory_text = ProjectMemory(self._session.alarm_dir).format_for_prompt()
        if memory_text:
            context["project_memory"] = memory_text
        recommendations = self._call_claude(context)
        self._store(recommendations)
        return {
            "session_id": self._session.session_id,
            "recommendation_count": len(recommendations),
            "recommendations": recommendations,
            "top_recommendations": recommendations[:5],
            "message": (
                f"Generated {len(recommendations)} draft recommendations. "
                "Evaluator running — review at recommendations://evaluated"
            ),
        }

    # ── Context assembly (deterministic) ──────────────────────────────────

    def _build_context(self) -> dict:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        try:
            lang_dist = {
                r["language"]: r["n"]
                for r in conn.execute(
                    "SELECT language, COUNT(*) AS n FROM manifest "
                    "WHERE session_id=? AND is_eligible=1 AND language IS NOT NULL "
                    "GROUP BY language ORDER BY n DESC",
                    (sid,),
                ).fetchall()
            }
            total_files = conn.execute(
                "SELECT COUNT(*) FROM manifest WHERE session_id=?", (sid,)
            ).fetchone()[0]
            eligible_files = conn.execute(
                "SELECT COUNT(*) FROM manifest WHERE session_id=? AND is_eligible=1", (sid,)
            ).fetchone()[0]
            total_loc = conn.execute(
                "SELECT SUM(metric_value) FROM complexity_metric "
                "WHERE session_id=? AND metric_name='loc'", (sid,)
            ).fetchone()[0] or 0
            high_loc = [
                {"file": r["file_path"], "loc": int(r["metric_value"])}
                for r in conn.execute(
                    "SELECT file_path, metric_value FROM complexity_metric "
                    "WHERE session_id=? AND metric_name='loc' "
                    "ORDER BY metric_value DESC LIMIT 15",
                    (sid,),
                ).fetchall()
            ]
            dep_count = conn.execute(
                "SELECT COUNT(*) FROM dependency_edge WHERE session_id=?", (sid,)
            ).fetchone()[0]
            symbol_count = conn.execute(
                "SELECT COUNT(*) FROM symbol WHERE session_id=?", (sid,)
            ).fetchone()[0]
            top_symbols = [
                {"name": r["name"], "type": r["symbol_type"], "file": r["file_path"]}
                for r in conn.execute(
                    "SELECT name, symbol_type, file_path FROM symbol "
                    "WHERE session_id=? LIMIT 30",
                    (sid,),
                ).fetchall()
            ]
        finally:
            conn.close()

        return {
            "source_path": str(self._session.source_path),
            "total_files": total_files,
            "eligible_files": eligible_files,
            "total_loc": int(total_loc),
            "language_distribution": lang_dist,
            "total_dependencies": dep_count,
            "total_symbols": symbol_count,
            "largest_files": high_loc,
            "sample_symbols": top_symbols,
        }

    # ── LLM call ───────────────────────────────────────────────────────────

    def _call_claude(self, context: dict) -> list[dict]:
        client = anthropic.Anthropic()

        prompt = _SYSTEM_PROMPT
        if self._overlay:
            prompt = f"{prompt}\n\n## Codebase context\n\n{self._overlay}"

        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"## Codebase analysis data\n\n{json.dumps(context, indent=2)}",
            }],
        )

        text = message.content[0].text
        return _parse_recommendations(text)

    # ── Storage ────────────────────────────────────────────────────────────

    def _store(self, recommendations: list[dict]) -> None:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        try:
            for rec in recommendations:
                conn.execute(
                    "INSERT INTO recommendation"
                    "(session_id, rank, category, severity, title, "
                    " description, affected_files, effort, rationale, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        self._session.session_id,
                        rec.get("rank", 99),
                        rec.get("category", "modernization"),
                        rec.get("severity", "medium"),
                        rec.get("title", ""),
                        rec.get("description", ""),
                        json.dumps(rec.get("affected_files", [])),
                        rec.get("effort", "M"),
                        rec.get("rationale", ""),
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def _parse_recommendations(text: str) -> list[dict]:
    """Extract JSON array from Claude's response.

    Handles fenced code blocks (```json ... ```) and truncation at max_tokens
    by salvaging all complete objects before the truncation point.
    """
    # Strip markdown code fences
    cleaned = text.replace("```json", "").replace("```", "").strip()

    start = cleaned.find("[")
    if start < 0:
        return []

    # Try full parse first
    end = cleaned.rfind("]") + 1
    if end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass

    # Response was truncated — salvage all complete objects
    fragment = cleaned[start:]
    last_complete = fragment.rfind("},")
    if last_complete < 0:
        last_complete = fragment.rfind("}")
    if last_complete < 0:
        return []
    try:
        return json.loads(fragment[: last_complete + 1] + "\n]")
    except json.JSONDecodeError:
        return []
