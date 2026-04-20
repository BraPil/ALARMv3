"""File discovery and manifest building.

Scans the source zone recursively, detects language by extension, and
populates the manifest table. Concurrently-safe: each file is processed
by a pool worker that writes its own SQLite connection (WAL mode).

C++ and Visual Basic are the Phase 1 priority targets — their files get
higher work-queue priority so they're analyzed first.
"""

import hashlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

from .session import Session
from .index import init_analysis_db


# Extension → language name (canonical lowercase)
LANGUAGE_MAP: dict[str, str] = {
    # C++ / C — Phase 1 priority
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c":   "cpp",  # treat plain C as cpp for analysis purposes
    ".h":   "cpp", ".hpp": "cpp", ".hxx": "cpp", ".inl": "cpp",
    # Visual Basic — Phase 1 priority
    ".vb": "vbnet", ".bas": "vbnet", ".cls": "vbnet",
    ".frm": "vbnet", ".ctl": "vbnet",
    # Python
    ".py": "python", ".pyi": "python",
    # JavaScript / TypeScript
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    # Java
    ".java": "java",
    # C#
    ".cs": "csharp",
    # Others (parsed if grammar available, else metrics only)
    ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".php": "php", ".kt": "kotlin", ".swift": "swift",
    # Data / config (indexed but not parsed for symbols)
    ".sql": "sql", ".xml": "xml",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".txt": "text",
}

# Languages with active Phase 1 parsing support
PHASE_1_LANGUAGES = {"python", "javascript", "typescript", "java", "csharp", "cpp", "vbnet"}

# Languages that get elevated queue priority (the first real targets)
PRIORITY_LANGUAGES = {"cpp", "vbnet"}

# Directories that are never scanned
EXCLUDE_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".pytest_cache",
    "build", "dist", "out", "bin", "obj", "target",
    ".venv", "venv", "env", ".env",
    ".alarmv3", ".tox",
    "packages", "vendor",
})


class FileScanner:
    """Discovers files in the source zone and populates the manifest."""

    def __init__(self, source: Path, session: Session):
        self._source = source
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        init_analysis_db(self._db_path)

    def scan(self, pool: ThreadPoolExecutor, job_id: str) -> int:
        """Discover all files and write manifest rows. Returns total file count."""
        files = list(self._iter_files())
        futures = {pool.submit(self._process_file, f): f for f in files}

        completed = 0
        for future in as_completed(futures):
            future.result()  # propagate worker exceptions
            completed += 1
            if completed % 200 == 0:
                self._session.set_metadata("mapping_progress", completed)

        self._session.set_metadata("manifest_file_count", completed)
        return completed

    def _iter_files(self) -> Iterator[Path]:
        for path in self._source.rglob("*"):
            if not path.is_file():
                continue
            # Skip excluded directories anywhere in the path
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            yield path

    def _process_file(self, path: Path) -> None:
        rel = path.relative_to(self._source)
        ext = path.suffix.lower()
        language = LANGUAGE_MAP.get(ext)
        is_eligible = 1 if language in PHASE_1_LANGUAGES else 0

        try:
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            line_count = data.count(b"\n") + 1
            size_bytes = len(data)
        except (PermissionError, OSError):
            sha256 = None
            line_count = None
            size_bytes = None
            is_eligible = 0

        # Enqueue eligible files for the analysis phase.
        # C++ and VB get priority=1 so they are claimed first.
        if is_eligible:
            priority = 1 if language in PRIORITY_LANGUAGES else 0
            self._session.enqueue("analysis", str(path), priority)

        # Write manifest row (thread-local connection, WAL allows concurrent writes)
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT OR IGNORE INTO manifest "
                "(session_id, file_path, relative_path, language, size_bytes, "
                " line_count, is_eligible, sha256, discovered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._session.session_id,
                    str(path),
                    str(rel),
                    language,
                    size_bytes,
                    line_count,
                    is_eligible,
                    sha256,
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
