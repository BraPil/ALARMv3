# LLM Wiki Pattern
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: concept, knowledge-management, wiki, karpathy

Andrej Karpathy's pattern for using an LLM to maintain a persistent, compounding markdown knowledge base.

## Core insight

Traditional RAG retrieves raw documents at query time. An LLM wiki instead **incrementally builds and maintains a synthesized wiki** — cross-references, contradictions, and synthesis accumulate rather than being rediscovered on each query.

The wiki is a **persistent, compounding artifact**. Each ingest makes every future query better.

## Why wikis die (and why this doesn't)

Humans abandon wikis because maintenance burden exceeds value. LLMs eliminate this friction — they don't forget cross-references, can touch 15 files simultaneously, and maintain consistency across dozens of pages without effort.

Division of labor:
- **Humans**: curate sources, ask questions, make decisions
- **LLM**: summarize, file, cross-reference, audit

## Three-layer architecture

| Layer | Description | LLM role |
|-------|-------------|----------|
| **Raw sources** | Immutable docs, PDFs, transcripts, URLs | Reads only |
| **Wiki** | LLM-generated markdown pages | Owns entirely |
| **Schema** | SCHEMA.md defining conventions and operations | Follows |

## Primary operations

**Ingest**: Drop a source → LLM extracts takeaways, updates 10-15 pages, logs entry, updates index.

**Query**: Ask question → LLM searches pages, synthesizes answer with citations, files new discoveries.

**Lint**: Periodic audit → LLM finds contradictions, stale claims, orphan pages, missing cross-refs.

## Supporting tools (optional)

- **Obsidian** — graph view for browsing connections
- **Obsidian Web Clipper** — convert web articles to markdown sources
- **qmd** — local search (BM25 + vector + LLM reranking) for large wikis

## Known tensions

- **Knowledge drift**: synthesized pages can gradually misrepresent sources if not re-ingested
- **Hallucination risk**: LLM may fabricate cross-references that didn't exist in sources
- **Hybrid mitigation**: keep original sources authoritative; use wiki pages as index cards pointing to them

## Application to ALARMv3

This wiki IS the pattern applied to itself. Every design decision, persona insight, architectural choice, and lesson learned gets filed here so future Claude sessions start informed.

## See also
- [Wiki Schema](../SCHEMA.md) — ALARMv3 wiki conventions
- [Cole Medin Persona](../personas/cole-medin.md) — first persona query filed here
