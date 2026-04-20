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
        }

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
