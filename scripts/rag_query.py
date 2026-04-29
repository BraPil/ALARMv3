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

OLLAMA_MODEL = "nomic-embed-text"
DEFAULT_CLAUDE = "claude-sonnet-4-6"

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
        conn.execute(
            "INSERT INTO temp.chunks_fts(chunk_id, content) "
            "SELECT id, content FROM main.code_chunk"
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
    vec_results: list[dict],
    kw_results: list[dict],
    top_k: int,
    k_const: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion of two ranked lists.

    Score per chunk = sum(1 / (k_const + rank_in_each_list)). Standard k=60
    from Cormack et al. 2009 — small enough that top ranks dominate, large
    enough that mid-rank agreement still matters.
    """
    fused: dict[int, float] = {}
    by_id: dict[int, dict] = {}
    sources: dict[int, set[str]] = {}
    ranks: dict[int, dict[str, int]] = {}

    for rank, r in enumerate(vec_results, start=1):
        cid = r["id"]
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k_const + rank)
        by_id[cid] = r
        sources.setdefault(cid, set()).add("vec")
        ranks.setdefault(cid, {})["vec"] = rank
    for rank, r in enumerate(kw_results, start=1):
        cid = r["id"]
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k_const + rank)
        by_id.setdefault(cid, r)
        sources.setdefault(cid, set()).add("kw")
        ranks.setdefault(cid, {})["kw"] = rank

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])
    out: list[dict] = []
    for cid, score in ordered[:top_k]:
        c = dict(by_id[cid])
        c["score"] = score
        c["sources"] = sorted(sources[cid])
        c["ranks"] = ranks[cid]
        out.append(c)
    return out


def retrieve(
    db_path: Path,
    query: str,
    top_k: int = 8,
    mode: str = "hybrid",
    candidates: int = 30,
) -> list[dict]:
    """Dispatch to the requested retrieval strategy."""
    if mode == "vector":
        return retrieve_vector(db_path, query, top_k)
    if mode == "keyword":
        return retrieve_keyword(db_path, query, top_k)
    if mode == "hybrid":
        n = max(candidates, top_k)
        v = retrieve_vector(db_path, query, n)
        k = retrieve_keyword(db_path, query, n)
        return fuse_rrf(v, k, top_k)
    raise ValueError(f"unknown mode: {mode}")


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
                 "text": _RAG_PROMPT.format(n=len(chunks)),
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
    parser.add_argument("--model", default=DEFAULT_CLAUDE)
    parser.add_argument("--raw", action="store_true",
                        help="Print only retrieval results, skip LLM")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON envelope")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        return 2

    chunks = retrieve(db_path, args.query, args.top_k, args.mode, args.candidates)

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
