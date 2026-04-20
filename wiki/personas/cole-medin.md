# Cole Medin — Persona
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: persona, cole-medin, agents, harness, archon

Synthesized viewpoint of Cole Medin on AI coding agents and architecture, sourced from AAA knowledge base (YouTube transcripts, LinkedIn posts, blog posts).

**Confidence**: Low for MCP/legacy-specific questions (no direct coverage found); Medium-High for general agent architecture principles.

## Core philosophy

AI coding systems need **harnesses** — orchestration infrastructure that sequences agent sessions and makes AI coding deterministic and repeatable. Without a harness, AI coding is unpredictable and hard to trust in production.

## Key principles

**1. Harnesses are non-negotiable infrastructure**
Not a nice-to-have. The harness is what separates a toy demo from a system you can rely on. It orchestrates different agent sessions and enforces workflow.

**2. Separation of concerns kills sycophancy**
Planning, building, and evaluation must be distinct agents with separate contexts. The adversarial tension between them surfaces issues that a single agent would self-approve. *Source: 2026-04-09, YouTube transcript.*

**3. Own your framework**
Developers need frameworks that are simple, truly theirs, and evolvable over time. Complex multi-agent systems from GitHub that you don't understand are worse than simpler custom ones you do. *Source: 2026-02-20, YouTube transcript.*

**4. AI coding maturity arc**
The field has moved from autocomplete → autonomous feature-building. Tools like Claude Code are leading this. The interesting work now is building the harnesses on top, not the assistants themselves. *Source: 2026-03-26, YouTube transcript.*

**5. Self-evaluation is broken by design**
LLMs trained on human feedback are biased toward agreement. This is a training artifact, not fixable by prompting. Architecture must compensate.

## Archon

Cole's open-source harness builder — described as "the first open-source [AI coding harness]" (2026-04-09). Useful as a reference implementation for ALARMv3's orchestration design. The design philosophy: simple, customizable, evolvable.

## Recommended tools (Cole's stack)

- Claude Code + Claude Agent SDK
- Archon (his own project)
- Pydantic AI (structured outputs)
- n8n, LangChain (orchestration)
- OpenAI Agents SDK (comparable alternative)

## Relevance to ALARMv3

| Cole's principle | ALARMv3 application |
|-----------------|---------------------|
| Harnesses = determinism | MCP server as the harness |
| Separate plan/build/eval | Distinct agents for mapping, analysis, evaluation |
| Own your framework | Custom MCP wrapper; don't import a black-box agent framework |
| Adversarial evaluator | Coverage contract verification; future separate review agent |

## Source provenance (AAA, queried 2026-04-20)

- YouTube transcript, 2026-04-09: Archon unveil, harness concept
- YouTube transcript, 2026-03-26: AI coding maturity, harnesses
- YouTube transcript, 2026-03-23: Claude Code features
- YouTube transcript, 2026-02-20: framework ownership philosophy
- YouTube transcript, 2026-03-17: Claude Code GA timeline

## See also
- [Multi-Agent Architecture](../concepts/multi-agent-architecture.md)
- [MCP-First Architecture](../concepts/mcp-first.md)
- [AAA + ALARMv3 Strategy](../project/aaa-alarmv3-strategy.md)
