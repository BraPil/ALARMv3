"""Wipe and rebuild code_chunk + chunk_vectors for an existing session.

Use after upgrading the chunker (e.g. extending file_overview coverage) when
you want the existing analysis.db to reflect the new chunking strategy
without a full re-discovery.

The script:
  1. DELETEs every code_chunk row and every chunk_vectors entry for the session.
  2. Calls KnowledgeBuilder.build() to re-create both layers from the existing
     symbol/manifest tables, embedding via Ollama nomic-embed-text.

Note: chunk_vectors is a vec0 virtual table — sqlite-vec stores the vectors in
companion tables (chunk_vectors_chunks, chunk_vectors_rowids,
chunk_vectors_vector_chunks00, chunk_vectors_info). DELETEing from the virtual
table propagates to all of them.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from alarmv3.core.knowledge import KnowledgeBuilder, _vec_conn  # noqa: E402
from alarmv3.core.session import Session  # noqa: E402


def _wipe_chunks(db_path: Path, session_id: str) -> dict[str, int]:
    """Delete code_chunk and chunk_vectors rows for the session."""
    cleared = {}
    # 1. chunk_vectors uses vec0 — needs the sqlite-vec extension loaded.
    conn = _vec_conn(db_path)
    try:
        # Map chunk_id -> exists in vectors. The vec0 virtual table doesn't
        # expose session_id, but chunk_id is a 1:1 FK to code_chunk.id.
        chunk_ids = [r[0] for r in conn.execute(
            "SELECT id FROM code_chunk WHERE session_id=?", (session_id,)).fetchall()]
        deleted = 0
        for cid in chunk_ids:
            try:
                cur = conn.execute("DELETE FROM chunk_vectors WHERE chunk_id=?", (cid,))
                deleted += cur.rowcount or 0
            except sqlite3.OperationalError:
                pass
        cleared["chunk_vectors"] = deleted
        conn.commit()
    finally:
        conn.close()

    # 2. code_chunk rows.
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        cur = conn.execute("DELETE FROM code_chunk WHERE session_id=?", (session_id,))
        cleared["code_chunk"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return cleared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alarm-dir", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    alarm_dir = Path(args.alarm_dir)
    session_db = alarm_dir / "session.db"
    artifact_dir = alarm_dir / "sessions" / args.session_id
    analysis_db = artifact_dir / "analysis.db"
    for p in (session_db, artifact_dir, analysis_db):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2

    cleared = _wipe_chunks(analysis_db, args.session_id)
    print("Wiped:")
    for k, v in cleared.items():
        print(f"  {k}: {v}")

    session = Session(session_db, args.session_id)
    print(f"Session: {session.session_id} (state={session.state.value})")
    print(f"Source:  {session.source_path}")

    builder = KnowledgeBuilder(session)
    result = builder.build()
    print("Re-chunk + re-embed complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
