"""Incrementally add secret_pattern chunks to an existing session.

Unlike rechunk_session.py which wipes everything, this only runs the new
_extract_secret_chunks step against the existing manifest+symbol tables.
The other chunk types (function/class/file_overview) are left untouched,
so embedding cost is bounded by the count of new secret-pattern chunks.

Use after upgrading the chunker's secret patterns when a full rechunk
would be wasteful.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from alarmv3.core.knowledge import KnowledgeBuilder, _vec_conn  # noqa: E402
from alarmv3.core.session import Session  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alarm-dir", required=True)
    ap.add_argument("--session-id", required=True)
    args = ap.parse_args()

    alarm_dir = Path(args.alarm_dir)
    session_db = alarm_dir / "session.db"
    artifact_dir = alarm_dir / "sessions" / args.session_id
    db_path = artifact_dir / "analysis.db"
    for p in (session_db, artifact_dir, db_path):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2
    session = Session(session_db, args.session_id)

    builder = KnowledgeBuilder(session)
    conn = _vec_conn(db_path)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM code_chunk WHERE chunk_type='secret_pattern' AND session_id=?",
            (args.session_id,),
        ).fetchone()[0]

        eligible = conn.execute(
            "SELECT file_path, relative_path, line_count FROM manifest "
            "WHERE session_id=? AND is_eligible=1",
            (args.session_id,),
        ).fetchall()
        added = builder._extract_secret_chunks(conn, eligible)
        conn.commit()
        print(f"secret_pattern chunks before: {before}, added: {added}")

        # Embed the newly-created (embedded=0) chunks.
        embedded = builder._embed_chunks(conn)
        print(f"embedded: {embedded}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
