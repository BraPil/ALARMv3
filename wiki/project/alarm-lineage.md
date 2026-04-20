# ALARM Lineage: v1 → v2 → v3
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: project, history, alarmv1, alarmv2, alarmv3

Three generations of the ALARM tool, each correcting the gaps of the previous.

## Generational summary

| Dimension | v1 (C#) | v2 (Python) | v3 (Python, planned) |
|-----------|---------|-------------|----------------------|
| **Language** | C# | Python | Python |
| **Scope** | AutoCAD/Oracle specific | Universal multi-language | Universal + opinionated |
| **Intelligence** | Rule-based | RAG/ML | LLM-native, MCP-first |
| **Guidance** | Prescriptive (specific paths) | Exploratory (query-driven) | Both: understand + prescribe |
| **Architecture** | Adapter pattern layers | Component-based modules | Core engine + MCP wrapper + adapters |
| **Setup** | Heavy (.NET, protocols) | Moderate (RAG infra) | Minimal (click, pyyaml, rich) |

## What each version got right

**v1 — The Specialist**
- Concrete migration paths for its target domain
- Multi-layer test strategy, explicit risk assessment
- Incremental 300 LOC safety limit
- CI/CD integration

**v2 — The Generalist**
- Universal language support via tree-sitter
- RAG-powered semantic understanding
- Natural language code queries
- Auto-generated documentation

## Gaps neither version closed

1. No actionable refactoring plans (v1 had tools; v2 had understanding — neither connected them)
2. No cost/benefit or ROI analysis
3. No team collaboration or progress tracking
4. One-shot only — no continuous monitoring as code evolves
5. Generic recommendations, not context-specific

## The v3 synthesis

> Combine v1's **prescriptive guidance** with v2's **universal understanding**, delivered via MCP with minimal setup.

v3 design principles derived from lineage analysis:
- Start simple, go deep (v2 complexity only when needed)
- Opinionated defaults (v1's strong guidance as default paths)
- Learn from code (v2's semantic understanding)
- Incremental safety (v1's small-change philosophy)
- Modern tooling — LLM-native without heavyweight deps

## See also
- [ALARMv3 Overview](alarmv3-overview.md)
- [MCP-First Architecture](../concepts/mcp-first.md)
