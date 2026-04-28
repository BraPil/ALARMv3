"""Re-run deep analysis (Phases A-D + adversarial evaluation) on an existing
session, leveraging the symbols/metrics/edges already in analysis.db.

Use after migrate_paths_to_relative.py has run, or when prompt/selector
changes need to be replayed without re-discovering or re-parsing source.

The script:
  1. Clears subsystem, subsystem_finding, analysis_coverage rows for the session
     (recommendation rows are cleared by DeepSynthesizer itself).
  2. Re-loads the session from session.db and instantiates DeepSynthesizer.
  3. Runs the four-phase pipeline + adversarial evaluator.
  4. Prints the resulting summary.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Make src/ importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from alarmv3.core.deep_analysis import DeepSynthesizer  # noqa: E402
from alarmv3.core.session import Session  # noqa: E402


def _clear_prior_deep_artifacts(db_path: Path, session_id: str) -> dict[str, int]:
    cleared: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        for table in ("subsystem", "subsystem_finding", "analysis_coverage"):
            cur = conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
            cleared[table] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return cleared


def _progress(pct: int, msg: str) -> None:
    bar = ("█" * (pct // 2)).ljust(50)
    sys.stdout.write(f"\r[{bar}] {pct:3d}% {msg[:80]:<80}")
    sys.stdout.flush()
    if pct >= 100:
        sys.stdout.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alarm-dir", required=True,
                        help="Path to .alarmv3 dir (e.g. /workspaces/ADDS_ALARMv3/.alarmv3)")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--max-subsystems", type=int, default=15)
    parser.add_argument("--keep-prior", action="store_true",
                        help="Skip the table-clearing step (will produce duplicates).")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        return 2

    alarm_dir = Path(args.alarm_dir)
    session_db = alarm_dir / "session.db"
    artifact_dir = alarm_dir / "sessions" / args.session_id
    analysis_db = artifact_dir / "analysis.db"

    for p in (session_db, artifact_dir, analysis_db):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2

    if not args.keep_prior:
        cleared = _clear_prior_deep_artifacts(analysis_db, args.session_id)
        print("Cleared prior deep-analysis rows:")
        for t, n in cleared.items():
            print(f"  {t}: {n}")
        print()

    session = Session(session_db, args.session_id)
    print(f"Session: {session.session_id} (state={session.state.value})")
    print(f"Source:  {session.source_path}")
    print()

    synth = DeepSynthesizer(session, progress_cb=_progress)
    result = synth.run(max_subsystems=args.max_subsystems)

    print()
    print("=" * 80)
    print("Deep analysis complete.")
    print(f"  Subsystems:                    {result['subsystem_count']}")
    print(f"  Files covered:                 {result['files_covered']} ({result['coverage_pct']:.0f}%)")
    print(f"  Outlier files (complexity):    {result['outlier_files_analyzed']}")
    print(f"  Raw findings (pre-aggregation):{result['raw_findings_count']}")
    print(f"  Recommendations:               {result['recommendation_count']}")
    print(f"  Evaluator: accept={result['evaluator_summary']['accept']}  "
          f"revise={result['evaluator_summary']['revise']}  "
          f"reject={result['evaluator_summary']['reject']}")
    print()
    print("Top 5 recommendations:")
    for r in result['top_recommendations']:
        print(f"  [{r.get('rank','?')}] {r.get('severity','?'):8s} {r.get('category','?'):14s} {r.get('title','')[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
