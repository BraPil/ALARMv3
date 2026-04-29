"""Code chunking, Ollama embeddings, and sqlite-vec index.

Structure-aware chunking: each chunk is one logical code unit (function,
class, file header) derived from the symbol table — not an arbitrary text
window. This keeps function boundaries intact and improves retrieval precision.

sqlite-vec requires pysqlite3 (not stdlib sqlite3) because the Codespace
Python is compiled without enable_load_extension support.
"""

import hashlib
import re
from pathlib import Path
from typing import Optional

import ollama
import pysqlite3 as sqlite3
import sqlite_vec

from .session import Session

OLLAMA_MODEL = "nomic-embed-text"
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_DIM = 768


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama is not reachable at OLLAMA_BASE_URL."""


def _ollama_running() -> bool:
    try:
        ollama.list()
        return True
    except Exception:
        return False


def _vec_conn(db_path: Path) -> sqlite3.Connection:
    """Open a pysqlite3 connection with sqlite-vec loaded."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.enable_load_extension(True)
    conn.load_extension(sqlite_vec.loadable_path())
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_vec_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors
        USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIM}]
        )
    """)
    conn.commit()


class KnowledgeBuilder:
    """Chunks code by structure and embeds via Ollama into sqlite-vec."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    # ── Public API ─────────────────────────────────────────────────────────

    def build(self) -> dict:
        """Chunk all eligible files and embed unembedded chunks.

        Reads symbols from the manifest+symbol tables, slices source files
        by start_line/end_line, writes code_chunk rows, then embeds each
        chunk via Ollama and stores vectors in the chunk_vectors vec0 table.

        Returns stats: chunks_created, chunks_embedded, chunks_skipped.
        """
        if not _ollama_running():
            raise OllamaUnavailableError(
                "Ollama is not running at http://localhost:11434. "
                "Run: nohup ollama serve > /tmp/ollama.log 2>&1 &"
            )

        conn = _vec_conn(self._db_path)
        try:
            _ensure_vec_table(conn)
            created = self._create_chunks(conn)
            embedded = self._embed_chunks(conn)
        finally:
            conn.close()

        return {
            "chunks_created": created,
            "chunks_embedded": embedded,
        }

    def query(self, text: str, top_k: int = 10) -> list[dict]:
        """Embed query text; cosine search sqlite-vec; return ranked chunks.

        Each result dict has: chunk_id, chunk_type, symbol_name, file_path,
        start_line, end_line, content, score (distance, lower=closer).
        """
        if not _ollama_running():
            raise OllamaUnavailableError(
                "Ollama is not running. Start it with: ollama serve"
            )

        vec = _embed(text)
        conn = _vec_conn(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    c.id, c.chunk_type, c.symbol_name,
                    c.file_path, c.start_line, c.end_line, c.content,
                    v.distance AS score
                FROM chunk_vectors v
                JOIN code_chunk c ON c.id = v.chunk_id
                WHERE v.embedding MATCH ? AND k=?
                ORDER BY v.distance
                """,
                [sqlite_vec.serialize_float32(vec), top_k],
            ).fetchall()
        finally:
            conn.close()

        return [dict(r) for r in rows]

    # ── Chunking ────────────────────────────────────────────────────────────

    # Per-file overview chunk size. Tuned to capture the body of typical legacy
    # files (.Cmd batch scripts, .lsp utilities, AutoLISP user scripts) that
    # have only a handful of small inferred symbols and would otherwise leave
    # their actual logic invisible to the RAG layer.
    _OVERVIEW_LINES = 200

    def _create_chunks(self, conn: sqlite3.Connection) -> int:
        """Create code_chunk rows from symbols + per-file overviews. Returns count.

        Two complementary chunk families are emitted:

          1. Structure-aware chunks — one per extracted symbol that has a known
             line range. These are the precise units the LLM reasons about for
             "what does function X do?" queries.

          2. File-overview chunks — one per eligible file covering lines
             1..min(N, _OVERVIEW_LINES). These guarantee the file's body is
             retrievable for "how does this file work?" queries even when the
             symbol extractor only found a handful of label/header lines (the
             common case for batch scripts, AutoLISP utilities with sparse
             defun coverage, .atc/.xtp config files, etc.).

        Originally the overview chunk was emitted only for files with zero
        symbols, but on the ADDS run that left the .Cmd deploy scripts
        invisible to RAG (they had 3 GOTO-label "function" symbols at lines
        6/10/81 which qualified them as "has symbols" but failed to capture
        the Xcopy/icacls body in between).
        """
        sid = self._session.session_id
        source_root = self._session.source_path
        created = 0

        def _resolve(p: str) -> str:
            """Return an absolute path for filesystem reads, accepting either form."""
            if Path(p).is_absolute() or source_root is None:
                return p
            return str(source_root / p)

        # 1. Structure-aware symbol chunks.
        symbols = conn.execute(
            """
            SELECT s.file_path, s.name, s.symbol_type, s.start_line, s.end_line
            FROM symbol s
            WHERE s.session_id=? AND s.start_line IS NOT NULL AND s.end_line IS NOT NULL
            """,
            (sid,),
        ).fetchall()

        for sym in symbols:
            content = _slice_file(_resolve(sym["file_path"]), sym["start_line"], sym["end_line"])
            if not content:
                continue
            if self._chunk_exists(conn, sym["file_path"], sym["start_line"]):
                continue
            h = hashlib.sha256(content.encode()).hexdigest()
            conn.execute(
                """
                INSERT INTO code_chunk
                (session_id, file_path, chunk_type, symbol_name,
                 start_line, end_line, content, content_hash, token_count, embedded)
                VALUES (?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    sid, sym["file_path"],
                    sym["symbol_type"], sym["name"],
                    sym["start_line"], sym["end_line"],
                    content, h, _approx_tokens(content),
                ),
            )
            created += 1

        # 2. File-overview chunk for every eligible file. The symbol table is
        # keyed by relative path; manifest exposes both absolute (file_path)
        # and relative (relative_path), so use the relative form for storage
        # and resolve to absolute for reading.
        eligible = conn.execute(
            "SELECT file_path, relative_path, line_count FROM manifest "
            "WHERE session_id=? AND is_eligible=1",
            (sid,),
        ).fetchall()

        for row in eligible:
            rel_fp = row["relative_path"] or row["file_path"]
            abs_fp = row["file_path"] or rel_fp
            if self._chunk_exists(conn, rel_fp, 1):
                continue
            end_line = min(row["line_count"] or self._OVERVIEW_LINES, self._OVERVIEW_LINES)
            content = _slice_file(abs_fp, 1, end_line)
            if not content:
                continue
            h = hashlib.sha256(content.encode()).hexdigest()
            conn.execute(
                """
                INSERT INTO code_chunk
                (session_id, file_path, chunk_type, symbol_name,
                 start_line, end_line, content, content_hash, token_count, embedded)
                VALUES (?,?,?,?,?,?,?,?,?,0)
                """,
                (sid, rel_fp, "file_overview", None, 1, end_line, content, h, _approx_tokens(content)),
            )
            created += 1

        # 3. Secret-pattern chunks — short, dense, focused on credential /
        #    key / network-share content. Surface for queries phrased in
        #    natural language ("hardcoded credentials", "UNC paths") that
        #    don't lexically match the surrounding function body.
        created += self._extract_secret_chunks(conn, eligible)

        conn.commit()
        return created

    # Patterns that mark a line as security-relevant. Each entry is
    # (label, compiled_regex). Labels become the chunk's symbol_name so the
    # type is discoverable from chunk metadata. Patterns are intentionally
    # conservative — false positives are cheap (extra chunks), false
    # negatives invisible (security findings missed).
    _SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
        # AES/key/IV/salt byte-array literals — 8+ hex bytes in `new byte[]`
        # initializer. Lower threshold catches typical PBKDF2 salts (8-13
        # bytes) and short symmetric keys.
        ("aes_byte_array", re.compile(
            r"new\s+byte\s*\[\s*\]\s*\{(?:[^}]*?(?:0x[0-9a-fA-F]{1,2}\s*,\s*){8,})",
            re.IGNORECASE,
        )),
        # ADO.NET / ODBC connection strings — at least one key=value pair
        # using a known connection-string keyword.
        ("connection_string", re.compile(
            r"\b(?:Data\s+Source|Initial\s+Catalog|User\s+(?:ID|Id)|"
            r"Provider|Trusted_Connection|Integrated\s+Security)\s*=",
            re.IGNORECASE,
        )),
        # Variable names that scream "secret" assigned to a string literal.
        # Matches `password = "..."`, `EncryptionKey = "..."`, `apiKey="..."`,
        # etc. Includes crypto-material names (key/IV/salt) that are common
        # markers of hardcoded cryptographic constants.
        ("credential_assignment", re.compile(
            r"\b(?:password|passwd|pwd|secret|"
            r"(?:api|access|auth|private|client|encryption|encrypt|decrypt|"
            r"crypto|cipher|hash|signing|sign|master)[-_]?(?:key|secret|token)|"
            r"(?:init[-_]?vector|init[-_]?vec|salt))"
            r"\b\s*[:=]\s*['\"][^'\"]+['\"]",
            re.IGNORECASE,
        )),
        # MapDrive-style network mount calls — `MapDrive "M:", "server",
        # "share"`. The semantic equivalent of a UNC literal in legacy VBS
        # launchers; surfaces the server/share names without needing the
        # `\\` syntax.
        ("network_share_call", re.compile(
            r'\bMap(?:Network)?Drive\s*\(?\s*"[A-Za-z]:"\s*,\s*"[\w.-]+"\s*,\s*"[\w.-]+"',
            re.IGNORECASE,
        )),
        # AWS access key id — a fixed format, very low false-positive rate.
        ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        # JWT — three base64url segments separated by dots, starting with
        # the `eyJ` header marker.
        ("jwt_token", re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
        )),
        # URL with embedded basic auth — the colon-at form leaks creds in
        # the URL itself.
        ("auth_url", re.compile(r"https?://[^/\s\"']+:[^@\s\"']+@")),
    ]

    # Lines of context around each match to capture variable names,
    # function context, and surrounding usage. Tuned so a chunk with
    # `_aesKey = new byte[] {` 5 lines above the byte literals still
    # captures the variable name.
    _SECRET_CONTEXT_BEFORE = 5
    _SECRET_CONTEXT_AFTER = 5

    def _extract_secret_chunks(
        self, conn: sqlite3.Connection, eligible: list[sqlite3.Row]
    ) -> int:
        """Emit chunk_type='secret_pattern' chunks for credential/key/UNC matches.

        Each match line gets one chunk covering match_line ± context. Multiple
        patterns matching the same line are collapsed into one chunk with all
        labels joined as the symbol_name.
        """
        sid = self._session.session_id
        created = 0

        for row in eligible:
            rel_fp = row["relative_path"] or row["file_path"]
            abs_fp = row["file_path"] or rel_fp
            try:
                text = Path(abs_fp).read_text(errors="replace")
            except (OSError, PermissionError):
                continue
            lines = text.splitlines()
            if not lines:
                continue

            # match_line (1-indexed) → set of pattern labels
            hits: dict[int, set[str]] = {}
            for label, pat in self._SECRET_PATTERNS:
                for m in pat.finditer(text):
                    line_num = text.count("\n", 0, m.start()) + 1
                    hits.setdefault(line_num, set()).add(label)

            for line_num in sorted(hits):
                # Avoid colliding with file_overview chunk at start_line=1.
                start = max(2, line_num - self._SECRET_CONTEXT_BEFORE)
                end = min(len(lines), line_num + self._SECRET_CONTEXT_AFTER)
                content = "\n".join(lines[start - 1: end]).strip()
                if not content:
                    continue
                if self._chunk_exists(conn, rel_fp, start):
                    continue
                symbol_name = "+".join(sorted(hits[line_num]))
                h = hashlib.sha256(content.encode()).hexdigest()
                conn.execute(
                    """
                    INSERT INTO code_chunk
                    (session_id, file_path, chunk_type, symbol_name,
                     start_line, end_line, content, content_hash,
                     token_count, embedded)
                    VALUES (?,?,?,?,?,?,?,?,?,0)
                    """,
                    (sid, rel_fp, "secret_pattern", symbol_name,
                     start, end, content, h, _approx_tokens(content)),
                )
                created += 1

        return created

    def _chunk_exists(self, conn: sqlite3.Connection, file_path: str, start_line: int) -> bool:
        return conn.execute(
            "SELECT 1 FROM code_chunk WHERE session_id=? AND file_path=? AND start_line=?",
            (self._session.session_id, file_path, start_line),
        ).fetchone() is not None

    # ── Embedding ───────────────────────────────────────────────────────────

    def _embed_chunks(self, conn: sqlite3.Connection) -> int:
        """Embed all unembedded chunks. Returns count embedded.

        Failures on individual chunks (e.g. a chunk that exceeds the embedder's
        context window even after truncation) are logged and skipped — the
        rest of the index still gets built. Without this, a single oversized
        chunk would abort the whole RAG build.
        """
        sid = self._session.session_id
        pending = conn.execute(
            "SELECT id, content FROM code_chunk WHERE session_id=? AND embedded=0",
            (sid,),
        ).fetchall()

        embedded = 0
        skipped = 0
        for chunk in pending:
            try:
                vec = _embed(chunk["content"])
            except Exception:
                skipped += 1
                continue
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id, embedding) VALUES (?, ?)",
                [chunk["id"], sqlite_vec.serialize_float32(vec)],
            )
            conn.execute(
                "UPDATE code_chunk SET embedded=1 WHERE id=?", (chunk["id"],)
            )
            embedded += 1

        conn.commit()
        if skipped:
            self._session.set_metadata("knowledge_skipped_chunks", skipped)
        return embedded


# ── Helpers ────────────────────────────────────────────────────────────────

def _embed(text: str) -> list[float]:
    # nomic-embed-text v1.5 has an 8192-token context window. 4000 chars is
    # ~1000-1500 code tokens — well inside the limit even for token-dense code.
    # If a chunk still exceeds context, halve and retry once before giving up.
    payload = text[:4000]
    try:
        resp = ollama.embeddings(model=OLLAMA_MODEL, prompt=payload)
    except Exception:
        resp = ollama.embeddings(model=OLLAMA_MODEL, prompt=payload[:2000])
    return resp["embedding"]


def _slice_file(file_path: str, start: int, end: int) -> Optional[str]:
    """Read lines [start, end] (1-indexed, inclusive) from a file."""
    try:
        lines = Path(file_path).read_text(errors="replace").splitlines()
        chunk = lines[start - 1: end]
        return "\n".join(chunk).strip() or None
    except (OSError, PermissionError):
        return None


def _approx_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)
