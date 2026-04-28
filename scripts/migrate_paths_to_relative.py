"""Migrate analysis.db so every (symbol, complexity_metric, dependency_edge,
code_chunk) row stores paths relative to session.source_path.

Background. Two extractors populated these tables with different conventions:
  - core/analysis.py (tree-sitter for csharp/python/js/etc.) wrote ABSOLUTE paths
  - core/language_researcher.py (Phase 7 inferred langs) wrote RELATIVE paths

Result: downstream queries that join on relative paths (the partitioner, the
representative-file selector in deep_analysis, etc.) drop every row written by
analysis.py. On the ADDS run that meant 49 csharp + 8 javascript files were
invisible to deep_analysis even though their symbols were on disk.

This migration is idempotent — running it twice is safe.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def normalize_paths(db_path: Path, source_root: Path) -> dict[str, int]:
    """Strip source_root prefix from all path columns. Returns per-table counts updated."""
    if not db_path.exists():
        raise FileNotFoundError(f"analysis.db not found at {db_path}")

    prefix = str(source_root).rstrip("/") + "/"
    updates: dict[str, int] = {}

    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        # symbol.file_path
        cur = conn.execute(
            "UPDATE symbol SET file_path = SUBSTR(file_path, ?) "
            "WHERE file_path LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["symbol"] = cur.rowcount

        # complexity_metric.file_path
        cur = conn.execute(
            "UPDATE complexity_metric SET file_path = SUBSTR(file_path, ?) "
            "WHERE file_path LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["complexity_metric"] = cur.rowcount

        # dependency_edge.source_file
        cur = conn.execute(
            "UPDATE dependency_edge SET source_file = SUBSTR(source_file, ?) "
            "WHERE source_file LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["dependency_edge.source_file"] = cur.rowcount

        # dependency_edge.target_file (rare but possible)
        cur = conn.execute(
            "UPDATE dependency_edge SET target_file = SUBSTR(target_file, ?) "
            "WHERE target_file LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["dependency_edge.target_file"] = cur.rowcount

        # code_chunk.file_path
        cur = conn.execute(
            "UPDATE code_chunk SET file_path = SUBSTR(file_path, ?) "
            "WHERE file_path LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["code_chunk"] = cur.rowcount

        # analysis_coverage.file_path
        cur = conn.execute(
            "UPDATE analysis_coverage SET file_path = SUBSTR(file_path, ?) "
            "WHERE file_path LIKE ?",
            (len(prefix) + 1, prefix + "%"),
        )
        updates["analysis_coverage"] = cur.rowcount

        conn.commit()
    finally:
        conn.close()
    return updates


def verify(db_path: Path) -> dict[str, dict[str, int]]:
    """After migration: count how many rows still look absolute (start with /)."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        results: dict[str, dict[str, int]] = {}
        for table, col in [
            ("symbol", "file_path"),
            ("complexity_metric", "file_path"),
            ("dependency_edge", "source_file"),
            ("dependency_edge", "target_file"),
            ("code_chunk", "file_path"),
            ("analysis_coverage", "file_path"),
        ]:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            absolute = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE '/%'"
            ).fetchone()[0]
            results[f"{table}.{col}"] = {"total": total, "still_absolute": absolute}
        return results
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to analysis.db")
    parser.add_argument(
        "--source-root", required=True,
        help="Absolute path used as the prefix to strip (e.g. /workspaces/ADDS)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    source_root = Path(args.source_root)

    print(f"DB:          {db_path}")
    print(f"Source root: {source_root}")
    if args.dry_run:
        print("(dry-run — counting rows that would change)")
        prefix = str(source_root).rstrip("/") + "/"
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            for table, col in [
                ("symbol", "file_path"),
                ("complexity_metric", "file_path"),
                ("dependency_edge", "source_file"),
                ("dependency_edge", "target_file"),
                ("code_chunk", "file_path"),
                ("analysis_coverage", "file_path"),
            ]:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?",
                    (prefix + "%",),
                ).fetchone()[0]
                print(f"  {table}.{col}: {n} rows would be normalized")
        finally:
            conn.close()
        return 0

    updates = normalize_paths(db_path, source_root)
    print("Rows updated:")
    for k, v in updates.items():
        print(f"  {k}: {v}")

    print("\nPost-migration verification:")
    for k, stats in verify(db_path).items():
        print(f"  {k}: {stats['still_absolute']}/{stats['total']} still absolute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
