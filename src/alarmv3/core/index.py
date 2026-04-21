"""SQLite schema for ALARMv3 analysis artifacts.

All analysis data — manifest, symbols, dependency graph, complexity metrics,
code chunks, and recommendations — lives in a single analysis.db per session.
WAL mode is mandatory for concurrent worker writes.
"""

import sqlite3
from pathlib import Path

_MANIFEST = """
CREATE TABLE IF NOT EXISTS manifest (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    file_path      TEXT    NOT NULL,
    relative_path  TEXT    NOT NULL,
    language       TEXT,
    size_bytes     INTEGER,
    line_count     INTEGER,
    is_eligible    INTEGER NOT NULL DEFAULT 1,
    excluded_reason TEXT,
    sha256         TEXT,
    discovered_at  REAL    NOT NULL,
    UNIQUE(session_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_manifest_session_lang
    ON manifest(session_id, language);
CREATE INDEX IF NOT EXISTS idx_manifest_eligible
    ON manifest(session_id, is_eligible);
"""

_DEPENDENCY = """
CREATE TABLE IF NOT EXISTS dependency_edge (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    target_file   TEXT,
    target_module TEXT,
    dep_type      TEXT NOT NULL,   -- import | include | require | using | imports
    line_number   INTEGER,
    is_resolved   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dep_source
    ON dependency_edge(session_id, source_file);
CREATE INDEX IF NOT EXISTS idx_dep_target
    ON dependency_edge(session_id, target_file);
"""

_SYMBOL = """
CREATE TABLE IF NOT EXISTS symbol (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    name        TEXT NOT NULL,
    symbol_type TEXT NOT NULL,   -- function | class | method | struct | enum | interface
    start_line  INTEGER,
    end_line    INTEGER,
    signature   TEXT,
    is_public   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_symbol_session_file
    ON symbol(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_symbol_name
    ON symbol(session_id, name);
"""

_COMPLEXITY = """
CREATE TABLE IF NOT EXISTS complexity_metric (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    metric_name  TEXT NOT NULL,   -- loc | cyclomatic | coupling_in | coupling_out
    metric_value REAL NOT NULL,
    computed_at  REAL NOT NULL,
    UNIQUE(session_id, file_path, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_complexity_session
    ON complexity_metric(session_id, file_path);
"""

_CHUNK = """
CREATE TABLE IF NOT EXISTS code_chunk (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    chunk_type   TEXT NOT NULL,   -- function | class | file_header | module
    symbol_name  TEXT,
    start_line   INTEGER,
    end_line     INTEGER,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count  INTEGER,
    embedded     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunk_session
    ON code_chunk(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_chunk_unembedded
    ON code_chunk(session_id, embedded) WHERE embedded = 0;
"""

_RECOMMENDATION = """
CREATE TABLE IF NOT EXISTS recommendation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    rank                INTEGER NOT NULL,
    category            TEXT NOT NULL,   -- security | modernization | quality | dependency
    severity            TEXT NOT NULL,   -- critical | high | medium | low
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    affected_files      TEXT NOT NULL DEFAULT '[]',  -- JSON array of paths
    effort              TEXT,                         -- S | M | L | XL (synthesizer estimate)
    rationale           TEXT,
    approved            INTEGER NOT NULL DEFAULT 0,
    created_at          REAL NOT NULL,
    risk_score          INTEGER,                      -- 1-5 from evaluator (Phase 3)
    evaluator_effort    TEXT,                         -- S | M | L | XL from evaluator
    evaluator_critique  TEXT,                         -- evaluator critique text
    evaluator_verdict   TEXT NOT NULL DEFAULT 'pending',  -- pending | accept | revise | reject
    review_status       TEXT NOT NULL DEFAULT 'pending'   -- pending | accepted | rejected (human)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_session
    ON recommendation(session_id, rank);
CREATE INDEX IF NOT EXISTS idx_recommendation_review
    ON recommendation(session_id, review_status);
"""

_IMPLEMENTATION_PLAN = """
CREATE TABLE IF NOT EXISTS implementation_plan (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    rec_rank        INTEGER NOT NULL,
    title           TEXT NOT NULL,
    affected_files  TEXT NOT NULL DEFAULT '[]',  -- JSON array
    order_index     INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | complete | skipped
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_impl_plan_session
    ON implementation_plan(session_id, order_index);
CREATE INDEX IF NOT EXISTS idx_impl_plan_status
    ON implementation_plan(session_id, status);
"""

_IMPLEMENTATION_CHANGE = """
CREATE TABLE IF NOT EXISTS implementation_change (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    plan_item_id    INTEGER NOT NULL,
    diff_text       TEXT,
    eval_critique   TEXT,
    eval_verdict    TEXT NOT NULL DEFAULT 'pending',  -- approve | flag | reject
    review_status   TEXT NOT NULL DEFAULT 'pending_review',
    feedback        TEXT,
    commit_hash     TEXT,
    created_at      REAL NOT NULL,
    reviewed_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_impl_change_session
    ON implementation_change(session_id, plan_item_id);
CREATE INDEX IF NOT EXISTS idx_impl_change_review
    ON implementation_change(session_id, review_status);
"""

_SUBSYSTEM = """
CREATE TABLE IF NOT EXISTS subsystem (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    subsystem_index  INTEGER NOT NULL,
    name             TEXT    NOT NULL,
    file_count       INTEGER NOT NULL,
    total_loc        REAL,
    avg_complexity   REAL,
    files            TEXT    NOT NULL DEFAULT '[]',
    created_at       REAL    NOT NULL,
    UNIQUE(session_id, subsystem_index)
);
CREATE INDEX IF NOT EXISTS idx_subsystem_session
    ON subsystem(session_id);
"""

_SUBSYSTEM_FINDING = """
CREATE TABLE IF NOT EXISTS subsystem_finding (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    subsystem_index  INTEGER,
    pass_type        TEXT    NOT NULL,   -- subsystem | complexity_tier | aggregation
    findings_json    TEXT    NOT NULL,
    created_at       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sf_session
    ON subsystem_finding(session_id, pass_type);
"""

_ANALYSIS_COVERAGE = """
CREATE TABLE IF NOT EXISTS analysis_coverage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    pass_type   TEXT    NOT NULL,
    covered_at  REAL    NOT NULL,
    UNIQUE(session_id, file_path, pass_type)
);
CREATE INDEX IF NOT EXISTS idx_coverage_session
    ON analysis_coverage(session_id);
"""

_LANGUAGE_GRAMMAR = """
CREATE TABLE IF NOT EXISTS language_grammar (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,
    file_ext      TEXT    NOT NULL,
    language_name TEXT    NOT NULL,
    grammar_json  TEXT    NOT NULL,
    created_at    REAL    NOT NULL,
    UNIQUE(session_id, file_ext)
);
CREATE INDEX IF NOT EXISTS idx_grammar_session
    ON language_grammar(session_id);
"""

_ALL_SCHEMAS = [
    _MANIFEST, _DEPENDENCY, _SYMBOL, _COMPLEXITY, _CHUNK,
    _RECOMMENDATION, _IMPLEMENTATION_PLAN, _IMPLEMENTATION_CHANGE,
    _SUBSYSTEM, _SUBSYSTEM_FINDING, _ANALYSIS_COVERAGE, _LANGUAGE_GRAMMAR,
]


def init_analysis_db(db_path: Path) -> None:
    """Create or migrate the analysis database at db_path."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for schema in _ALL_SCHEMAS:
            conn.executescript(schema)
        _migrate_recommendation_phase3(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_recommendation_phase3(conn: sqlite3.Connection) -> None:
    """Add Phase 3 evaluator columns to existing recommendation tables."""
    new_columns = [
        ("risk_score",         "INTEGER"),
        ("evaluator_effort",   "TEXT"),
        ("evaluator_critique", "TEXT"),
        ("evaluator_verdict",  "TEXT NOT NULL DEFAULT 'pending'"),
        ("review_status",      "TEXT NOT NULL DEFAULT 'pending'"),
    ]
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(recommendation)").fetchall()
    }
    for col_name, col_def in new_columns:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE recommendation ADD COLUMN {col_name} {col_def}"
            )
