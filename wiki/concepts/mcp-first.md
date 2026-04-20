# MCP-First Architecture
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: concept, mcp, architecture, design-principle

Designing a system where the Model Context Protocol is the **primary interaction surface**, not an afterthought bolted onto a CLI.

## What MCP-first means for ALARMv3

The user interacts with ALARMv3 through MCP tools, resources, and prompts — not primarily via CLI commands. The Claude Code panel (or any MCP-capable client) is the intended UI.

Benefits:
- LLM can call tools directly — no context-switching between chat and terminal
- Tools, resources, and prompts are first-class citizens with schemas and type safety
- Guardrail confirmation becomes a structured tool call, not an honor-system convention
- Session state is surfaced as MCP resources (the LLM can read current session status)

## MCP surface for ALARMv3

Three layers of MCP exposure:

| Layer | Purpose |
|-------|---------|
| **Tools** | Actions: attach, confirm, map, analyze, recommend, transform |
| **Resources** | State: session manifest, dependency graph, recommendation list |
| **Prompts** | Guided workflows: "analyze this codebase", "explain this module" |

## Why not CLI-first?

CLI is still present (for scripting, CI, non-LLM users), but CLI wraps the same core engine that MCP exposes. The MCP layer is not a thin adapter — it is the designed interaction contract.

## MCP as a harness (Cole Medin alignment)

Cole Medin's concept of a **harness** — infrastructure that makes AI coding deterministic and repeatable — maps directly to MCP in ALARMv3. The MCP server is the harness: it enforces guardrails, manages session state, and gates what the LLM can do.

## Implementation notes

- MCP server lives in `src/alarmv3/mcp/` (server.py, tools.py, resources.py, prompts.py)
- Core engine (`src/alarmv3/core/`) has no MCP dependency — it's pure Python
- This keeps the core testable and the MCP wrapper thin

## See also
- [Three-Layer Boundary](../architecture/three-layer-boundary.md)
- [ALARMv3 Overview](../project/alarmv3-overview.md)
- [Multi-Agent Architecture](multi-agent-architecture.md)
