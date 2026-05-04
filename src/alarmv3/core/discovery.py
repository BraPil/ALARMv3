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

from .index import init_analysis_db
from .session import Session

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

# Extensions that contribute no source code to analysis. Filtered at discovery
# time so the manifest stays clean and the Phase 7 language researcher never
# tries to fabricate a "grammar" for binary or pure-metadata files. (Without
# this filter, sampling a .bmp produces a Claude grammar with empty pattern
# lists, the researcher still flips is_eligible=1, and the eligible pool gets
# drowned in non-source noise — which is exactly what happened on the first
# full-archive ADDS run.)
IGNORED_EXTENSIONS = frozenset({
    # Raster/vector images
    ".bmp", ".gif", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".ico", ".cur",
    # Compiled / linked binaries (Windows + POSIX)
    ".dll", ".so", ".dylib", ".exe", ".obj", ".o", ".a", ".lib", ".exp", ".pdb",
    # ActiveX / AutoCAD compiled extensions
    ".ocx", ".oca", ".arx", ".vlx",
    # Archive formats
    ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".jar", ".war", ".ear",
    # AutoCAD binary / engineering data
    ".dwt", ".dst", ".dwg", ".dxf",
    ".shx", ".slb", ".stb", ".pc3", ".pmp", ".cuix",
    ".lut",
    # Office / documentation binaries
    ".chm", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".rtf",
    # Windows shell shortcuts and misc binaries
    ".lnk", ".mnr",
})


class FileScanner:
    """Discovers files in the source zone and populates the manifest."""

    def __init__(self, source: Path, session: Session, *, extra_ignored_extensions=None):
        """Args:
            source: source root.
            session: ALARMv3 session.
            extra_ignored_extensions: optional iterable of extra extensions
                (lowercase, dot-prefixed) to add to the engine's
                IGNORED_EXTENSIONS for this scan. Typically supplied from a
                CodebasePolicy overlay so per-codebase binary blobs (e.g.
                .rpt, .dacpac for billing systems) can be filtered without
                editing the engine baseline.
        """
        self._source = source
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"
        self._ignored = IGNORED_EXTENSIONS | frozenset(extra_ignored_extensions or ())
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
            # Skip known-binary / non-source extensions before they reach the
            # manifest or the language researcher (engine baseline + policy extras)
            if path.suffix.lower() in self._ignored:
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
