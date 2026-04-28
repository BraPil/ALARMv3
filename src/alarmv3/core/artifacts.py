"""Artifact writers — Markdown and JSON output from analysis results."""

import json
import sqlite3
from pathlib import Path

from .session import Session


class ArtifactWriter:

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        self._out = session.artifact_dir

    def write_all(self) -> dict[str, Path]:
        return {
            "recommendations_md": self.write_recommendations_md(),
            "manifest_json": self.write_manifest_json(),
            "summary_json": self.write_summary_json(),
            "evaluation_report_md": self.write_evaluation_report_md(),
        }

    def write_evaluation_report_md(self) -> Path:
        """Render the adversarial evaluator's verdicts and critiques as Markdown.

        Surfaces the columns that the evaluator writes onto the recommendation
        table (verdict / critique / effort / risk_score) but that no other
        artifact exposes. Intended as the human review companion to
        recommendations.md.
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT rank, category, severity, title, description, rationale, "
            "affected_files, effort, evaluator_verdict, evaluator_critique, "
            "evaluator_effort, risk_score "
            "FROM recommendation WHERE session_id=? ORDER BY rank",
            (self._session.session_id,),
        ).fetchall()
        conn.close()

        verdict_counts: dict[str, int] = {}
        risk_buckets = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in rows:
            v = (r["evaluator_verdict"] or "pending").lower()
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
            rs = r["risk_score"]
            if rs is not None and rs in risk_buckets:
                risk_buckets[rs] += 1

        lines: list[str] = [
            "# ALARMv3 Adversarial Evaluation Report\n",
            f"**Session**: `{self._session.session_id}`  ",
            f"**Source**: `{self._session.source_path}`\n",
            f"**Total recommendations evaluated**: {len(rows)}\n",
            "## Summary\n",
            "| Verdict | Count |",
            "|---|---:|",
        ]
        for v in ("accept", "revise", "reject", "pending"):
            lines.append(f"| {v} | {verdict_counts.get(v, 0)} |")
        lines.append("")
        lines.append("| Risk score | Count |")
        lines.append("|---:|---:|")
        for k in (1, 2, 3, 4, 5):
            lines.append(f"| {k} | {risk_buckets[k]} |")
        lines.append("\n---\n")

        verdict_emoji = {"accept": "✅", "revise": "✏️", "reject": "❌", "pending": "⏳"}
        for r in rows:
            v = (r["evaluator_verdict"] or "pending").lower()
            emoji = verdict_emoji.get(v, "⚪")
            lines.append(f"## {r['rank']}. {emoji} {r['title']}")
            lines.append(
                f"**Category**: `{r['category']}` | "
                f"**Severity**: `{r['severity']}` | "
                f"**Risk**: `{r['risk_score'] if r['risk_score'] is not None else 'n/a'}` | "
                f"**Effort (orig → eval)**: `{r['effort'] or '?'}` → "
                f"`{r['evaluator_effort'] or '?'}`\n"
            )
            critique = r["evaluator_critique"] or "_No critique recorded._"
            lines.append("### Evaluator critique\n")
            lines.append(critique)
            lines.append("\n### Original rationale\n")
            lines.append(r["rationale"] or "_(none)_")
            try:
                affected = json.loads(r["affected_files"]) if r["affected_files"] else []
            except (TypeError, json.JSONDecodeError):
                affected = []
            if affected:
                lines.append("\n### Affected files")
                for f in affected:
                    lines.append(f"- `{f}`")
            lines.append("\n---\n")

        out = self._out / "evaluation_report.md"
        out.write_text("\n".join(lines))
        return out

    def write_recommendations_md(self) -> Path:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recommendation WHERE session_id=? ORDER BY rank",
            (self._session.session_id,),
        ).fetchall()
        conn.close()

        lines = [
            "# ALARMv3 Modernization Recommendations\n",
            f"**Session**: `{self._session.session_id}`  ",
            f"**Source**: `{self._session.source_path}`\n",
            f"**Total recommendations**: {len(rows)}\n",
            "---\n",
        ]
        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        for r in rows:
            emoji = severity_emoji.get(r["severity"], "⚪")
            lines.append(f"## {r['rank']}. {emoji} {r['title']}")
            lines.append(f"**Category**: `{r['category']}` | "
                         f"**Severity**: `{r['severity']}` | "
                         f"**Effort**: `{r['effort'] or '?'}`\n")
            lines.append(r["description"])
            if r["rationale"]:
                lines.append(f"\n> {r['rationale']}")
            affected = json.loads(r["affected_files"])
            if affected:
                lines.append("\n**Affected files**:")
                for f in affected:
                    lines.append(f"- `{f}`")
            lines.append("\n---\n")

        out = self._out / "recommendations.md"
        out.write_text("\n".join(lines))
        return out

    def write_manifest_json(self) -> Path:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT relative_path, language, size_bytes, line_count, is_eligible "
            "FROM manifest WHERE session_id=? ORDER BY relative_path",
            (self._session.session_id,),
        ).fetchall()
        conn.close()
        out = self._out / "manifest.json"
        out.write_text(json.dumps([dict(r) for r in rows], indent=2))
        return out

    def write_summary_json(self) -> Path:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        sid = self._session.session_id
        lang_dist = {
            r["language"]: r["n"]
            for r in conn.execute(
                "SELECT language, COUNT(*) AS n FROM manifest "
                "WHERE session_id=? AND language IS NOT NULL GROUP BY language",
                (sid,),
            ).fetchall()
        }
        symbol_types = {
            r["symbol_type"]: r["n"]
            for r in conn.execute(
                "SELECT symbol_type, COUNT(*) AS n FROM symbol "
                "WHERE session_id=? GROUP BY symbol_type",
                (sid,),
            ).fetchall()
        }
        total_loc = conn.execute(
            "SELECT SUM(metric_value) FROM complexity_metric "
            "WHERE session_id=? AND metric_name='loc'",
            (sid,),
        ).fetchone()[0] or 0
        rec_count = conn.execute(
            "SELECT COUNT(*) FROM recommendation WHERE session_id=?", (sid,)
        ).fetchone()[0]
        conn.close()

        summary = {
            "session_id": sid,
            "source_path": str(self._session.source_path),
            "state": self._session.state.value,
            "language_distribution": lang_dist,
            "symbol_types": symbol_types,
            "total_loc": int(total_loc),
            "recommendation_count": rec_count,
        }
        out = self._out / "summary.json"
        out.write_text(json.dumps(summary, indent=2))
        return out
