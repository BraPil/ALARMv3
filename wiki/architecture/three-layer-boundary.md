# Three-Layer Product Boundary
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: architecture, design, layers, mcp, adapters

ALARMv3's clean separation into core engine, MCP wrapper, and sync adapters.

## The three layers

```
┌─────────────────────────────────────────────┐
│           ALARM MCP Wrapper                 │
│   server.py  tools.py  resources.py         │
│   prompts.py                                │
│   Thin. Knows MCP protocol. Delegates all   │
│   logic to core engine.                     │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│           ALARM Core Engine                 │
│   session  guardrails  discovery  analysis  │
│   synthesis  artifacts  index               │
│   orchestration                             │
│   Pure Python. No MCP dependency.           │
│   Fully testable in isolation.              │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│           Sync Adapters                     │
│   LocalFS (now)   SharePoint (deferred)     │
│   Pluggable. Core engine never calls        │
│   adapters directly — uses interface.       │
└─────────────────────────────────────────────┘
```

## Why this boundary matters

**MCP wrapper stays thin**: If MCP protocol changes or a new surface (CLI, REST, web UI) is needed, the core engine doesn't change. The MCP wrapper is a translation layer, not a logic layer.

**Core engine is portable**: Can be tested without a running MCP server. Can be wrapped by future surfaces (web dashboard, REST API, GitHub Action) without refactoring.

**Adapters are pluggable**: SharePoint sync is deferred but the interface is defined. LocalFS adapter works now. Adding SharePoint later doesn't touch core or MCP.

## Package layout

```
src/alarmv3/
├── core/
│   ├── session.py
│   ├── guardrails.py
│   ├── discovery.py
│   ├── analysis.py
│   ├── synthesis.py
│   ├── artifacts.py
│   ├── index.py
│   └── orchestration.py
├── mcp/
│   ├── server.py
│   ├── tools.py
│   ├── resources.py
│   └── prompts.py
└── adapters/
    └── sync/
        ├── localfs.py
        └── sharepoint.py    ← deferred
```

## Dependency rule

```
mcp/ → core/      ✓
core/ → adapters/ ✓ (via interface)
adapters/ → core/ ✗
mcp/ → adapters/  ✗
```

## See also
- [ALARMv3 Overview](../project/alarmv3-overview.md)
- [MCP-First Architecture](../concepts/mcp-first.md)
