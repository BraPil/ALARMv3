# Multi-Agent Architecture
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: concept, agents, architecture, harness, sycophancy

Patterns for orchestrating multiple specialized AI agents to produce better, more reliable outcomes than a single monolithic agent.

## Core problem: sycophancy

LLMs trained on human feedback develop a bias toward agreement — they rate their own output favorably. A single agent that plans, builds, AND evaluates its work will approve mediocre output. This is a fundamental training artifact, not a configuration issue.

**Solution**: Separate evaluator agent with its own context and adversarial framing.

## Separation of concerns model (Cole Medin)

Three distinct agent roles, each with independent context:

| Agent | Responsibility | Why separate? |
|-------|---------------|---------------|
| **Planner** | Decompose task, create spec | No implementation bias |
| **Builder** | Execute against spec | No self-evaluation |
| **Evaluator** | Critique output vs. spec | No authorship attachment |

The adversarial tension between Builder and Evaluator surfaces issues that a single agent would self-censor.

## Harnesses

A **harness** is the orchestration infrastructure that:
- Sequences agent sessions
- Passes context between sessions
- Enforces the workflow (you can't skip evaluation)
- Makes AI coding **deterministic and repeatable**

For ALARMv3, the MCP server is the harness. It gates what the LLM can do and ensures the guardrail state machine is respected.

## ALARMv3 agent mapping

| Role | ALARMv3 equivalent |
|------|-------------------|
| Planner | `start_full_mapping` + `run_dependency_analysis` |
| Builder | `generate_architecture_knowledge` + `generate_modernization_recommendations` |
| Evaluator | Coverage contract verification + separate review agent (future) |

## Bounded orchestration vs. swarms

ALARMv3 uses **bounded orchestration** — a task queue with explicit worker limits — rather than unbounded self-cloning swarms. Reasons:
- Codespaces resource constraints (CPU/memory bounded)
- Predictable, checkpointable progress
- Easier to reason about safety and coverage

## Key tools in this space

- **Claude Agent SDK** — primary for ALARMv3
- **Archon** (Cole Medin) — open-source harness builder; reference implementation worth studying
- **Pydantic AI** — structured agent outputs
- **n8n / LangChain** — orchestration if needed

## See also
- [MCP-First Architecture](mcp-first.md) — MCP as the harness layer
- [Cole Medin Persona](../personas/cole-medin.md)
- [Three-Layer Boundary](../architecture/three-layer-boundary.md)
