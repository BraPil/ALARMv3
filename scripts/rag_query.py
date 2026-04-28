"""End-to-end RAG over an ALARMv3 session's vector index.

Retrieves the top-k code chunks from chunk_vectors via Ollama nomic-embed-text,
hands them to Claude as grounding context, and prints a citation-backed answer.

Usage:
    rag_query.py --db <analysis.db> --query "where is Oracle login handled?"

Optional:
    --top-k N           number of chunks to retrieve (default 8)
    --model MODEL       Claude model id (default claude-sonnet-4-6)
    --raw               print only the retrieval result, skip the LLM call
    --json              emit a structured JSON envelope instead of plain text

The chunks are formatted in the prompt as fenced blocks tagged with their
file:start-end so Claude's response can cite chunks by index.
"""

from __future__ import annotations

import argparse
import json
import os
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


def retrieve(db_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """Top-k chunks by vector distance. Each result has chunk metadata + content."""
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

    chunks = retrieve(db_path, args.query, args.top_k)

    if args.raw:
        if args.json:
            print(json.dumps({"query": args.query, "chunks": chunks}, indent=2))
        else:
            print(f"# Top {len(chunks)} chunks for: {args.query!r}\n")
            for i, c in enumerate(chunks, start=1):
                print(f"[{i}] {c['file_path']}:{c['start_line']}-{c['end_line']} "
                      f"({c['chunk_type']} {c['symbol_name'] or ''}) "
                      f"score={c['score']:.3f}")
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
