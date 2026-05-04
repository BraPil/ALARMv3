"""End-to-end RAG over an ALARMv3 session's index, with hybrid retrieval.

Retrieves the top-k code chunks via three configurable strategies and hands
them to Claude as grounding context, returning a citation-backed answer.

Retrieval modes:
  - vector   : pure semantic similarity via Ollama nomic-embed-text + sqlite-vec
  - keyword  : BM25 over an in-memory FTS5 index built from code_chunk.content
  - hybrid   : both, fused by Reciprocal Rank Fusion (default)

Vector retrieval misses content that is dense in domain-specific tokens the
embedder under-represents (verified 2026-04-29: nomic-embed-text ranks .Cmd
batch-script chunks at position ~925/2501 even when the query contains the
literal terms "Xcopy", "batch", "icacls"). Keyword retrieval covers that
blind spot; RRF combines without needing score calibration.

Usage:
    rag_query.py --db <analysis.db> --query "..."

Optional:
    --top-k N           final chunks to return (default 8)
    --mode MODE         vector | keyword | hybrid (default hybrid)
    --candidates N      per-side candidates pulled before fusion (default 30)
    --model MODEL       Claude model id (default claude-sonnet-4-6)
    --raw               print only the retrieval result, skip the LLM call
    --json              emit a structured JSON envelope instead of plain text
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import ollama
import pysqlite3 as sqlite3_with_ext
import sqlite_vec

# Make the alarmv3 package importable when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from alarmv3.core.codebase_policy import CodebasePolicy  # noqa: E402

OLLAMA_MODEL = "nomic-embed-text"
DEFAULT_CLAUDE = "claude-sonnet-4-6"
DEFAULT_RERANK = "claude-haiku-4-5-20251001"

# Module-level policy holder. set_policy() swaps it; consumers read _active_policy
# first and fall back to the engine defaults below. Empty policy = legacy behavior.
_active_policy: CodebasePolicy = CodebasePolicy.empty()


def set_policy(policy: CodebasePolicy) -> None:
    """Activate a codebase policy for this script's runtime. Idempotent."""
    global _active_policy
    _active_policy = policy


# Engine default RAG prompt. ADDS-coupled for backward compatibility — load
# `policy/adds.yaml` (or any other codebase policy) via `--policy` to override.
_RAG_PROMPT = """\
You are an expert code-archaeology assistant for the ADDS legacy codebase
(AutoCAD plugin: AutoLISP + C# + PowerShell + Oracle). The user has asked a
question about the codebase. Below are the {n} most-relevant code chunks
retrieved by semantic similarity from the indexed source.

Rules:
1. Answer ONLY from the chunks. If the chunks don't contain the answer, say
   so explicitly and name what's missing.
2. Cite chunks inline using [chunk N] where N is the chunk's index in the
   list below. Multiple citations: [chunk 2, chunk 5].
3. When you quote code, keep it to short snippets (1-3 lines) inside backticks.
4. Be concise — a paragraph or two, plus a short bullet list of evidence.
5. If the chunks contradict each other, surface that.
"""


def _rag_prompt() -> str:
    return _active_policy.rag_prompt or _RAG_PROMPT


def _vec_conn(db_path: Path) -> sqlite3_with_ext.Connection:
    conn = sqlite3_with_ext.connect(str(db_path), timeout=10)
    conn.enable_load_extension(True)
    conn.load_extension(sqlite_vec.loadable_path())
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3_with_ext.Row
    return conn


def embed(text: str) -> list[float]:
    """Embed via the same Ollama model the index was built with."""
    resp = ollama.embeddings(model=OLLAMA_MODEL, prompt=text[:2000])
    return resp["embedding"]


def retrieve_vector(db_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """Top-k chunks by cosine distance via sqlite-vec. Lower score = closer."""
    vec = embed(query)
    conn = _vec_conn(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                c.id, c.chunk_type, c.symbol_name,
                c.file_path, c.start_line, c.end_line, c.content,
                v.distance AS score
            FROM chunk_vectors v
            JOIN code_chunk c ON c.id = v.chunk_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            [sqlite_vec.serialize_float32(vec), top_k],
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# Stop words pruned from FTS5 queries. Kept minimal — most "content words" in
# code questions (paths, identifiers, command names) are domain-specific and
# we want them to participate.
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "doing", "done",
    "how", "what", "where", "when", "which", "who", "why",
    "and", "or", "of", "to", "in", "on", "for", "with", "by", "from", "at",
    "this", "that", "these", "those", "it", "its",
    "use", "used", "uses", "using",
}


def _fts_query(q: str) -> str:
    """Lower, alphanum-tokenize, drop stops, OR-join. Empty input returns ''."""
    tokens = re.findall(r"[A-Za-z0-9_]{2,}", q.lower())
    tokens = [t for t in tokens if t not in _STOP]
    return " OR ".join(tokens)


def retrieve_keyword(db_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """Top-k chunks by BM25 over an in-memory FTS5 index of code_chunk.content.

    The FTS5 index is built per-call (~sub-second for 2501 chunks). Persisting
    it in analysis.db is a future optimization — keep this lazy until the
    chunker is the canonical writer for it.
    """
    fts_q = _fts_query(query)
    if not fts_q:
        return []

    conn = _vec_conn(db_path)
    try:
        # FTS5's bm25() and MATCH operators don't accept a schema-qualified
        # table name (`schema.tbl`), so the FTS table lives in a temp schema
        # which is unqualified by default.
        conn.execute(
            """
            CREATE VIRTUAL TABLE temp.chunks_fts USING fts5(
                content,
                chunk_id UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        # Index chunk_type + symbol_name + content together so metadata
        # tokens (e.g. "credential_assignment", "network_share_call",
        # "function MyLoginObj") let security-themed and symbol-named
        # queries match the right chunks lexically.
        conn.execute(
            "INSERT INTO temp.chunks_fts(chunk_id, content) "
            "SELECT id, "
            "  COALESCE(chunk_type,'') || ' ' || "
            "  COALESCE(symbol_name,'') || ' ' || "
            "  COALESCE(content,'') "
            "FROM main.code_chunk"
        )
        rows = conn.execute(
            """
            SELECT
                c.id, c.chunk_type, c.symbol_name,
                c.file_path, c.start_line, c.end_line, c.content,
                bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN main.code_chunk c ON c.id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ?
            ORDER BY bm25(chunks_fts)
            LIMIT ?
            """,
            [fts_q, top_k],
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def fuse_rrf(
    sources_lists: dict[str, list[dict]],
    top_k: int,
    k_const: int = 60,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """Weighted Reciprocal Rank Fusion of N ranked lists.

    Score per chunk = sum(weight_i / (k_const + rank_in_list_i)). Standard
    k=60 from Cormack et al. 2009. Default weight=1 per source.

    Path-source weight is bumped to 2.0 because path-filtered hits represent
    a user-explicit constraint ("the .vbs files I asked about"); single-source
    rank-1 in path should outrank mid-rank cross-agreement in vec+kw, which
    raw RRF would otherwise let win.
    """
    weights = weights or {}
    fused: dict[int, float] = {}
    by_id: dict[int, dict] = {}
    sources: dict[int, set[str]] = {}
    ranks: dict[int, dict[str, int]] = {}

    for src_name, results in sources_lists.items():
        w = weights.get(src_name, 1.0)
        for rank, r in enumerate(results, start=1):
            cid = r["id"]
            fused[cid] = fused.get(cid, 0.0) + w / (k_const + rank)
            by_id.setdefault(cid, r)
            sources.setdefault(cid, set()).add(src_name)
            ranks.setdefault(cid, {})[src_name] = rank

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])
    out: list[dict] = []
    for cid, score in ordered[:top_k]:
        c = dict(by_id[cid])
        c["score"] = score
        c["sources"] = sorted(sources[cid])
        c["ranks"] = ranks[cid]
        out.append(c)
    return out


# Extension aliases: query-side regex → canonical extension stored in file_path.
# Match either ".ext" verbatim, common synonyms (vbscript, autolisp), or
# "<ext> file/script/code" patterns. Case-insensitive on the query side; the
# resulting LIKE pattern preserves the case the chunker stored.
_EXT_PATTERNS: list[tuple[str, list[str]]] = [
    (".vbs", [r"\.vbs\b", r"\bvbscript\b", r"\bvbs\s+(?:file|script|code)"]),
    (".cs",  [r"\.cs\b", r"\bc#", r"\bcsharp\b", r"\bcs\s+(?:file|code)"]),
    (".lsp", [r"\.lsp\b", r"\blsp\b", r"\blisp\b", r"\bautolisp\b", r"\bvlx\b"]),
    (".Lsp", [r"\.lsp\b", r"\blsp\b", r"\blisp\b", r"\bautolisp\b", r"\bvlx\b"]),
    (".LSP", [r"\.lsp\b", r"\blsp\b", r"\blisp\b", r"\bautolisp\b", r"\bvlx\b"]),
    (".Cmd", [r"\.cmd\b", r"\bbatch\s+(?:file|script)", r"\bcmd\s+(?:file|script)"]),
    (".sln", [r"\.sln\b", r"\bsolution\s+file"]),
    (".js",  [r"\.js\b", r"\bjavascript\b"]),
    (".ini", [r"\.ini\b"]),
    (".prv", [r"\.prv\b"]),
]

# Path segments to skip — too generic to be useful constraints.
_PATH_STOP = {
    "Original files", "Adds", "Common", "Lisp", "User", "Forms",
    "Archive", "Utils", "Menu", "Template", "Support",
}


def _path_segments(db_path: Path) -> set[str]:
    """Distinctive directory-segment strings from the index's file_paths.

    "Distinctive" = length >= 5 OR contains a digit (catches '19.0'). Generic
    segments (e.g. 'Common', 'Adds' for ADDS) are excluded via the active
    codebase policy's path_stop, falling back to _PATH_STOP if no policy.
    """
    stop = _active_policy.path_stop or _PATH_STOP
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        rows = conn.execute("SELECT DISTINCT file_path FROM code_chunk").fetchall()
    finally:
        conn.close()
    segs: set[str] = set()
    for (fp,) in rows:
        for seg in fp.split("/"):
            if not seg or seg in stop:
                continue
            if len(seg) >= 5 or any(c.isdigit() for c in seg):
                segs.add(seg)
    return segs


def _extract_path_constraints(query: str, db_path: Path) -> list[str]:
    """Detect file-type and path-prefix mentions; return SQL LIKE patterns.

    Empty list = no constraint detected (caller should skip path-filtered
    retrieval). Multiple patterns are OR'd by the caller.
    """
    patterns: list[str] = []
    q_lower = query.lower()

    ext_patterns = _active_policy.ext_patterns or _EXT_PATTERNS
    seen_exts: set[str] = set()
    for ext, regexes in ext_patterns:
        if ext.lower() in seen_exts:
            continue  # don't double-add (.lsp/.Lsp/.LSP are case variants)
        if any(re.search(rx, q_lower) for rx in regexes):
            patterns.append(f"%{ext}")
            seen_exts.add(ext.lower())

    for seg in _path_segments(db_path):
        if seg.lower() in q_lower:
            patterns.append(f"%{seg}%")

    return patterns


# Query keywords that indicate the user is asking about security-sensitive
# content. When detected, we run a `secret_pattern`-typed retrieval source
# so the chunker's secret-extraction work is not drowned by surrounding
# code. The set is intentionally a mix of crypto/auth and network-share
# vocabulary — the same `secret_pattern` chunks cover both because the
# chunker emits crypto AND network_share_call chunks under that type.
_SECRET_QUERY_KEYWORDS = {
    "credential", "credentials", "password", "passwords",
    "secret", "secrets", "token", "tokens",
    "api key", "api-key", "apikey", "access key", "auth token",
    "encryption", "encrypt", "decrypt", "cipher",
    "salt", "init vector", "iv ", "private key", "signing key",
    "connection string", "connection strings",
    "network share", "network shares", "unc path", "unc paths",
    "smb share", "drive mapping", "mapped drive", "map drive",
    "hardcoded",
}


def _is_secret_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _SECRET_QUERY_KEYWORDS)


def retrieve_typed(
    db_path: Path, query: str, top_k: int, chunk_type: str
) -> list[dict]:
    """BM25 over chunks restricted to a single chunk_type, scored over
    chunk_type + symbol_name + content.

    Used to surface `secret_pattern` chunks for credential/network queries
    without competing against the much larger pool of function/file_overview
    chunks. When the query phrasing doesn't lexically match crypto code
    (e.g. "where are passwords?" vs. an `EncryptionKey =` line), the small
    type-restricted pool keeps the secret chunks visible.
    """
    fts_q = _fts_query(query)
    if not fts_q:
        return []
    conn = _vec_conn(db_path)
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE temp.chunks_fts_typed USING fts5(
                content,
                chunk_id UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        conn.execute(
            "INSERT INTO temp.chunks_fts_typed(chunk_id, content) "
            "SELECT id, "
            "  COALESCE(chunk_type,'') || ' ' || "
            "  COALESCE(symbol_name,'') || ' ' || "
            "  COALESCE(content,'') "
            "FROM main.code_chunk WHERE chunk_type=?",
            [chunk_type],
        )
        rows = conn.execute(
            """
            SELECT
                c.id, c.chunk_type, c.symbol_name,
                c.file_path, c.start_line, c.end_line, c.content,
                bm25(chunks_fts_typed) AS score
            FROM chunks_fts_typed
            JOIN main.code_chunk c ON c.id = chunks_fts_typed.chunk_id
            WHERE chunks_fts_typed MATCH ?
            ORDER BY bm25(chunks_fts_typed)
            LIMIT ?
            """,
            [fts_q, top_k],
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def retrieve_path_filtered(
    db_path: Path, query: str, top_k: int, patterns: list[str]
) -> list[dict]:
    """BM25 over chunks whose file_path matches any LIKE pattern.

    Empty patterns → empty result. The same in-memory FTS5 strategy as
    retrieve_keyword, but the FTS table is populated only with matching
    chunks. When the constraint is narrow (e.g., '%.vbs' in this index =
    8 files), this guarantees those files compete only against each other.
    """
    if not patterns:
        return []
    where_clauses = " OR ".join(["file_path LIKE ?"] * len(patterns))
    fts_q = _fts_query(query)

    conn = _vec_conn(db_path)
    try:
        rows: list = []
        # 1. BM25 within the constraint, IF we have query tokens to match on.
        if fts_q:
            conn.execute(
                """
                CREATE VIRTUAL TABLE temp.chunks_fts_pf USING fts5(
                    content,
                    chunk_id UNINDEXED,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            # Same metadata-aware indexing as retrieve_keyword: include
            # chunk_type and symbol_name so e.g. "credential_assignment"
            # tokens are searchable.
            conn.execute(
                f"INSERT INTO temp.chunks_fts_pf(chunk_id, content) "
                f"SELECT id, "
                f"  COALESCE(chunk_type,'') || ' ' || "
                f"  COALESCE(symbol_name,'') || ' ' || "
                f"  COALESCE(content,'') "
                f"FROM main.code_chunk WHERE {where_clauses}",
                patterns,
            )
            rows = conn.execute(
                """
                SELECT
                    c.id, c.chunk_type, c.symbol_name,
                    c.file_path, c.start_line, c.end_line, c.content,
                    bm25(chunks_fts_pf) AS score
                FROM chunks_fts_pf
                JOIN main.code_chunk c ON c.id = chunks_fts_pf.chunk_id
                WHERE chunks_fts_pf MATCH ?
                ORDER BY bm25(chunks_fts_pf)
                LIMIT ?
                """,
                [fts_q, top_k],
            ).fetchall()

        # 2. Fallback: BM25 produced nothing (common when the query asks
        # *about* a file type rather than about its content — e.g.,
        # ".vbs scripts exist" doesn't appear in any .vbs file's body).
        # Return one file_overview per matching file so the caller sees
        # what's there.
        if not rows:
            rows = conn.execute(
                f"""
                SELECT
                    id, chunk_type, symbol_name,
                    file_path, start_line, end_line, content,
                    0.0 AS score
                FROM main.code_chunk
                WHERE ({where_clauses}) AND chunk_type='file_overview'
                ORDER BY file_path
                LIMIT ?
                """,
                patterns + [top_k],
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def retrieve(
    db_path: Path,
    query: str,
    top_k: int = 8,
    mode: str = "hybrid",
    candidates: int = 30,
    path_aware: bool = True,
    rerank: bool = False,
    rerank_model: str = DEFAULT_RERANK,
    rerank_pool: int = 20,
) -> list[dict]:
    """Dispatch to the requested retrieval strategy.

    In hybrid mode with `path_aware=True` (default), a third source is
    added when the query mentions a file extension (".vbs files") or a
    distinctive directory segment ("19.0", "Div_Map Archive"): a BM25
    pool restricted to chunks whose file_path matches. Without it,
    type-narrow questions return drowning-in-irrelevant-files results
    because neither vector nor full-content BM25 indexes file paths.
    """
    if mode == "vector":
        return retrieve_vector(db_path, query, top_k)
    if mode == "keyword":
        return retrieve_keyword(db_path, query, top_k)
    if mode == "hybrid":
        n = max(candidates, top_k)
        sources_lists: dict[str, list[dict]] = {
            "vec": retrieve_vector(db_path, query, n),
            "kw": retrieve_keyword(db_path, query, n),
        }
        weights = {"vec": 1.0, "kw": 1.0}
        patterns: list[str] = []
        if path_aware:
            patterns = _extract_path_constraints(query, db_path)
            if patterns:
                sources_lists["path"] = _path_source_interleaved(
                    db_path, query, n, patterns
                )
                weights["path"] = 2.0
            # Secret-typed source: when the query asks about credentials /
            # network shares / crypto, also pull from the small pool of
            # secret_pattern chunks. Same path-aware flag controls it
            # since both are query-intent-based filters.
            if _is_secret_query(query):
                sources_lists["secret"] = retrieve_typed(
                    db_path, query, n, "secret_pattern"
                )
                weights["secret"] = 2.0

        # Coverage guarantee + reranker pool sizing: when reranking, fuse
        # to a wider window so the reranker has more candidates to work
        # with. Pattern coverage runs over that same wider window.
        target_k = max(rerank_pool, top_k) if rerank else top_k
        fused = fuse_rrf(sources_lists, target_k, weights=weights)
        if path_aware and len(patterns) > 1:
            fused = _ensure_pattern_coverage(
                db_path, query, patterns, fused, target_k
            )

        if rerank:
            reranked = rerank_with_llm(query, fused, model=rerank_model)
            return reranked[:top_k]
        return fused[:top_k]


def _ensure_pattern_coverage(
    db_path: Path,
    query: str,
    patterns: list[str],
    fused: list[dict],
    top_k: int,
) -> list[dict]:
    """Guarantee at least one chunk per path pattern in top_k.

    For each pattern, look up its top-1 BM25 hit (path-filtered). If absent
    from `fused`, append it and drop the lowest-scored entry whose source
    set is *not* {path} (so we don't sacrifice path-source coverage to make
    room for itself). Replacement preserves rank order otherwise.
    """
    present_ids = {c["id"] for c in fused}
    forced: list[dict] = []
    for p in patterns:
        top1 = retrieve_path_filtered(db_path, query, 1, [p])
        if not top1:
            continue
        cid = top1[0]["id"]
        if cid in present_ids or cid in {c["id"] for c in forced}:
            continue
        # Annotate so the trace output shows the chunk was forced-included
        # for pattern coverage.
        chunk = dict(top1[0])
        chunk["sources"] = ["path-forced"]
        chunk["ranks"] = {"path-forced": 1}
        forced.append(chunk)

    if not forced:
        return fused

    out = list(fused)
    for chunk in forced:
        # Find a non-path-only chunk to evict (scan from the bottom).
        evict_idx = None
        for i in range(len(out) - 1, -1, -1):
            srcs = set(out[i].get("sources", []))
            if srcs != {"path"}:
                evict_idx = i
                break
        if evict_idx is None:
            # All current entries are path-source only — append, trim later.
            out.append(chunk)
        else:
            out[evict_idx] = chunk

    return out[:top_k]


def _path_source_interleaved(
    db_path: Path, query: str, n: int, patterns: list[str]
) -> list[dict]:
    """Path-source for fusion. Single-pattern: pass through. Multi-pattern:
    round-robin top-N across each pattern's independent ranked list, deduped
    by chunk id, so each pattern gets equal representation regardless of how
    BM25 over the combined pool would weight them.

    Motivation: when a user mentions multiple distinct file types or paths
    (".cs files under 19.0/" vs ".lsp files under Div_Map Archive/"),
    pooling all matches into one BM25 rank lets one side dominate by token
    volume — interleaving guarantees both halves of a comparison surface.
    """
    if len(patterns) <= 1:
        return retrieve_path_filtered(db_path, query, n, patterns)
    per_pattern = [retrieve_path_filtered(db_path, query, n, [p]) for p in patterns]
    out: list[dict] = []
    seen: set[int] = set()
    for i in range(n):
        for results in per_pattern:
            if i >= len(results):
                continue
            cid = results[i]["id"]
            if cid in seen:
                continue
            out.append(results[i])
            seen.add(cid)
            if len(out) >= n:
                return out
    return out
    raise ValueError(f"unknown mode: {mode}")


_RERANK_PROMPT = """\
You are scoring code chunks for relevance to a single user question.

For each chunk below (numbered 1..{n}), output an integer relevance score
from 0 to 100 where:
  100 = chunk directly answers the question (e.g. it IS the function/code
        the user asked about, or contains the literal facts requested)
   50 = chunk is related context that helps answer the question but is
        not itself the answer
    0 = chunk is irrelevant — different topic, boilerplate, or noise

Output ONLY a JSON array of {n} integers in chunk order, no prose, no
keys, no explanation. Example for 3 chunks: [85, 12, 0]
"""


def _rerank_chunk_block(c: dict, n: int, max_chars: int = 800) -> str:
    """One-line metadata + truncated content, designed for reranker prompts.

    Uses an f-string so chunk content (which often contains literal `{}`
    from C# array initializers, JSON, etc.) doesn't get interpreted as
    format placeholders.
    """
    sym = c.get("symbol_name") or ""
    body = (c.get("content") or "").strip()
    if len(body) > max_chars:
        body = body[:max_chars] + " ..."
    return (
        f"chunk {n}: {c['file_path']}:{c['start_line']}-{c['end_line']} "
        f"({c['chunk_type']} {sym})\n{body}"
    )


def rerank_with_llm(
    query: str, candidates: list[dict], model: str = DEFAULT_RERANK
) -> list[dict]:
    """LLM-as-reranker. Sends a batch of candidates to Claude with a
    score-per-chunk prompt, parses the JSON array, returns the same list
    re-sorted by reranker score (desc), with `score` overwritten and
    `sources` augmented with 'rerank'.

    Failure mode: if the model returns malformed output, we fall back to
    the original (RRF) order so reranking is never worse than not reranking.
    """
    if not candidates:
        return candidates
    import anthropic
    client = anthropic.Anthropic()

    chunk_blocks = [
        _rerank_chunk_block(c, i + 1) for i, c in enumerate(candidates)
    ]
    prompt = (
        f"Question: {query}\n\n"
        f"Chunks:\n\n" + "\n\n---\n\n".join(chunk_blocks)
    )

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=400,
            system=[{"type": "text",
                     "text": _RERANK_PROMPT.format(n=len(candidates)),
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
    except Exception:
        return candidates  # API failure → fall back to RRF order

    # Parse the first JSON array we find. Reranker prompt asks for nothing
    # else, but defensive: tolerate stray text around it.
    m = re.search(r"\[\s*[\d\s,.-]+\s*\]", raw)
    if not m:
        return candidates
    try:
        scores = json.loads(m.group(0))
        if (not isinstance(scores, list)
                or len(scores) != len(candidates)
                or not all(isinstance(s, (int, float)) for s in scores)):
            return candidates
    except json.JSONDecodeError:
        return candidates

    paired = list(zip(candidates, scores))
    paired.sort(key=lambda x: -x[1])
    out: list[dict] = []
    for rank, (c, s) in enumerate(paired, start=1):
        c2 = dict(c)
        c2["score"] = float(s)
        srcs = list(c2.get("sources", []))
        if "rerank" not in srcs:
            srcs.append("rerank")
        c2["sources"] = sorted(srcs)
        ranks = dict(c2.get("ranks", {}))
        ranks["rerank"] = rank
        c2["ranks"] = ranks
        out.append(c2)
    return out


def _format_chunks(chunks: list[dict]) -> str:
    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        sym = c.get("symbol_name") or c.get("chunk_type")
        # cap chunk content to avoid prompt blow-up
        content = (c.get("content") or "").strip()
        if len(content) > 3000:
            content = content[:3000] + "\n... [chunk truncated]"
        parts.append(
            f"### chunk {i}: `{c['file_path']}:{c['start_line']}-{c['end_line']}`  "
            f"({c['chunk_type']} `{sym}` · score={c['score']:.3f})\n\n"
            f"```\n{content}\n```"
        )
    return "\n\n".join(parts)


def answer(query: str, chunks: list[dict], model: str = DEFAULT_CLAUDE) -> str:
    """Call Claude with chunks as grounding context, return the answer text."""
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        system=[{"type": "text",
                 "text": _rag_prompt().format(n=len(chunks)),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"## Question\n\n{query}\n\n"
                f"## Retrieved chunks\n\n{_format_chunks(chunks)}"
            ),
        }],
    )
    return msg.content[0].text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to analysis.db")
    parser.add_argument("--query", required=True, help="Natural-language question")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--mode", choices=["vector", "keyword", "hybrid"],
                        default="hybrid",
                        help="Retrieval strategy (default: hybrid)")
    parser.add_argument("--candidates", type=int, default=30,
                        help="Per-side candidates pulled before fusion (hybrid only)")
    parser.add_argument("--no-path-aware", action="store_true",
                        help="Disable the path-filtered third source in hybrid mode")
    parser.add_argument("--rerank", action="store_true",
                        help="LLM-rerank the top-N candidates after RRF fusion")
    parser.add_argument("--rerank-model", default=DEFAULT_RERANK,
                        help=f"Reranker model id (default: {DEFAULT_RERANK})")
    parser.add_argument("--rerank-pool", type=int, default=20,
                        help="Candidates fed to the reranker before truncation to top-k")
    parser.add_argument("--model", default=DEFAULT_CLAUDE)
    parser.add_argument("--policy", type=str, default=None,
                        help="Path to a codebase policy YAML (overrides RAG prompt, "
                             "ext patterns, and path stop-words). See policy/adds.yaml.")
    parser.add_argument("--raw", action="store_true",
                        help="Print only retrieval results, skip LLM")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON envelope")
    args = parser.parse_args()

    if args.policy:
        try:
            set_policy(CodebasePolicy.load(args.policy))
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR loading policy: {e}", file=sys.stderr)
            return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        return 2

    chunks = retrieve(
        db_path, args.query, args.top_k, args.mode, args.candidates,
        path_aware=not args.no_path_aware,
        rerank=args.rerank,
        rerank_model=args.rerank_model,
        rerank_pool=args.rerank_pool,
    )

    if args.raw:
        if args.json:
            print(json.dumps({"query": args.query, "mode": args.mode,
                              "chunks": chunks}, indent=2))
        else:
            print(f"# Top {len(chunks)} chunks for: {args.query!r}  (mode={args.mode})\n")
            for i, c in enumerate(chunks, start=1):
                src = ""
                if "sources" in c:
                    src_tag = "+".join(c["sources"])
                    rk = c.get("ranks", {})
                    rk_str = ",".join(f"{s}#{rk[s]}" for s in c["sources"])
                    src = f" [{src_tag} {rk_str}]"
                print(f"[{i}] {c['file_path']}:{c['start_line']}-{c['end_line']} "
                      f"({c['chunk_type']} {c['symbol_name'] or ''}) "
                      f"score={c['score']:.4f}{src}")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    text = answer(args.query, chunks, model=args.model)
    if args.json:
        print(json.dumps({
            "query": args.query, "answer": text,
            "chunks": [{k: v for k, v in c.items() if k != "content"} for c in chunks],
        }, indent=2))
    else:
        print(f"# Question\n\n{args.query}\n\n")
        print(f"# Top {len(chunks)} chunks retrieved\n")
        for i, c in enumerate(chunks, start=1):
            print(f"  [{i}] {c['file_path']}:{c['start_line']}-{c['end_line']}  score={c['score']:.3f}")
        print()
        print(f"# Answer\n\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
