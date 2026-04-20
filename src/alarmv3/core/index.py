"""SQLite schema for ALARMv3 analysis artifacts.

All analysis data — manifest, symbols, dependency graph, complexity metrics,
code chunks, and recommendations — lives in a single analysis.db per session.
WAL mode is mandatory for concurrent worker writes.
"""

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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    rank           INTEGER NOT NULL,
    category       TEXT NOT NULL,   -- security | modernization | quality | dependency
    severity       TEXT NOT NULL,   -- critical | high | medium | low
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    affected_files TEXT NOT NULL DEFAULT '[]',  -- JSON array of paths
    effort         TEXT,                         -- S | M | L | XL
    rationale      TEXT,
    approved       INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recommendation_session
    ON recommendation(session_id, rank);
"""

_ALL_SCHEMAS = [_MANIFEST, _DEPENDENCY, _SYMBOL, _COMPLEXITY, _CHUNK, _RECOMMENDATION]


def init_analysis_db(db_path: "Path") -> None:
    """Create or migrate the analysis database at db_path."""
    import sqlite3
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for schema in _ALL_SCHEMAS:
            conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
