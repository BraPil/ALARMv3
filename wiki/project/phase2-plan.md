# Phase 2 Plan: RAG Layer
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: phase2, rag, sqlite-vec, ollama, query_codebase

Phase 2 adds natural language Q&A over the analyzed codebase. The user asks "which files handle authentication?" and gets back the relevant code chunks with source locations — without Claude reading raw files.

## Goals

1. Structure-aware chunking of discovered code (by function/class, not text windows)
2. Local embeddings via Ollama `nomic-embed-text` — no external calls
3. `sqlite-vec` cosine similarity index stored in `analysis.db`
4. New MCP tool: `query_codebase(question, top_k) → list[dict]`
5. Ollama running reliably in GitHub Codespaces (devcontainer)

## Board decision: chunk by structure, not text windows

Aishwarya Srinivasan principle: chunking by arbitrary text window (512 tokens, 50% overlap) loses function boundaries and mixes unrelated code. Instead, each chunk is one logical unit:
- One function or method (from `symbol` table start/end lines)
- One class body
- One file header (imports + module docstring)

This directly improves retrieval precision: a query for "file I/O" retrieves complete functions, not a mid-function window that happens to contain the word "file".

## Implementation plan

### 1. `knowledge.py` — `KnowledgeBuilder`

```python
class KnowledgeBuilder:
    def build(self) -> dict:
        """Chunk all eligible files; embed unembedded chunks via Ollama."""
        # 1. Read symbols from analysis.db
        # 2. For each symbol: slice source file by start_line/end_line
        # 3. Write to code_chunk table (content, content_hash, token_count)
        # 4. For each unembedded chunk: call Ollama → store vector in sqlite-vec
        # 5. Return stats: chunks_created, chunks_embedded, tokens_total

    def query(self, text: str, top_k: int = 10) -> list[dict]:
        """Embed query text; cosine search sqlite-vec; return ranked chunks."""
```

### 2. `sqlite-vec` integration

The `code_chunk` table already exists. Phase 2 adds a virtual table:

```sql
CREATE VIRTUAL TABLE chunk_vectors USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[768]   -- nomic-embed-text output dimension
);
```

Cosine similarity query:
```sql
SELECT c.*, v.distance
FROM chunk_vectors v
JOIN code_chunk c ON c.id = v.chunk_id
WHERE v.embedding MATCH ?  -- query vector
ORDER BY v.distance
LIMIT ?
```

### 3. New MCP tool: `query_codebase`

```python
@mcp.tool()
def query_codebase(question: str, top_k: int = 10) -> dict:
    """Ask a natural language question about the analyzed codebase.

    Embeds the question, retrieves the top-k most similar code chunks
    from the sqlite-vec index, and returns them with source locations.
    Requires state: ANALYSIS_COMPLETE or later.
    """
```

Returns:
```json
{
  "question": "...",
  "results": [
    {
      "chunk_type": "function",
      "symbol_name": "Helper::run",
      "file_path": "utils.cpp",
      "start_line": 8,
      "end_line": 12,
      "content": "...",
      "score": 0.92
    }
  ]
}
```

### 4. State machine change

`KNOWLEDGE_BUILT` added between `ANALYSIS_COMPLETE` and `IMPLEMENTATION_PLANNED`. `query_codebase` is available from `ANALYSIS_COMPLETE` onward (build is lazy — triggered on first query if not yet built).

### 5. Ollama in Codespaces

See [Ollama Codespaces](../tools/ollama-codespaces.md) for full setup. Summary:
- `nomic-embed-text` runs on CPU, ~274MB RAM — viable in standard Codespace (4-core, 8GB)
- Installed via official script in `postCreateCommand`
- Model pulled in `postStartCommand` (after network available)
- `ollama serve` starts as background daemon

## New test files

| File | Coverage |
|------|---------|
| `tests/unit/test_knowledge.py` | Chunker, token counting, chunk deduplication |
| `tests/integration/test_rag_pipeline.py` | Build → query on sample_repo (Ollama required; skipped otherwise) |
| `tests/unit/test_mcp_tools_phase2.py` | `query_codebase` tool schema and state-gate |

## Dependencies already installed

`sqlite-vec>=0.1.0` and `ollama>=0.3.0` are already in `pyproject.toml` and the lockfile — no `pyproject.toml` changes needed.

## See also
- [Phase 1 Implementation](phase1-implementation.md)
- [Ollama Codespaces](../tools/ollama-codespaces.md)
- [Board Decisions](../architecture/board-decisions.md) — Decision #4: nomic-embed-text via Ollama
