# AAA + ALARMv3 Strategy
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: project, aaa, alarmv3, strategy, architecture

How Agentic-AI-Architect (AAA) and ALARMv3 relate and co-evolve.

## Relationship

AAA (BraPil/Agentic-AI-Architect) is a **companion project** — a separate REST server consumed by ALARMv3. It is not embedded in ALARMv3; it runs as a sidecar.

ALARMv3 calls AAA for:
- Persona-grounded architecture recommendations (e.g., Cole Medin on agent design)
- Knowledge base search over curated AI practitioner content
- Trending tool intelligence

## Key decisions (2026-04-20)

| Decision | Rationale |
|----------|-----------|
| AAA runs as separate process | Clean separation; ALARMv3 stays focused on code analysis |
| ALARMv3 is MCP-first | v3 UX built on MCP tools/resources/prompts; core engine remains modular |
| Source repo is read-only archive | Safety guardrail; artifacts and modernization work go elsewhere |
| Bounded orchestration, not swarms | Codespaces-friendly; avoids uncontrolled self-cloning |
| Local-first storage | SQLite + local artifacts now; Postgres/pgvector + SharePoint later |
| AAA hosts personas internally | One registry, not 20 separate bots |

## AAA persona model

Persona analogs are **source-grounded approximations of public views** — not impersonations. Each persona is built from indexed LinkedIn posts, YouTube transcripts, blog posts, and GitHub READMEs. The system synthesizes their likely viewpoint; confidence level and provenance are always returned.

Currently available: Cole Medin, Andrej Karpathy, Chip Huyen, Simon Willison, Lilian Weng (50+ total).

## Open questions

- Exact ALARM MCP tools/resources/prompts surface (deferred to implementation phase)
- AAA persona registry schema and source ingestion rules
- Local-first vector storage details (SQLite-vec vs. ChromaDB)
- SharePoint sync endpoints (deferred)
- Whether and when AAA exposes its own MCP surface

## See also
- [ALARMv3 Overview](alarmv3-overview.md)
- [Cole Medin Persona](../personas/cole-medin.md)
- [Multi-Agent Architecture](../concepts/multi-agent-architecture.md)
