# ALARMv3 MCP-First Target Architecture

## Purpose

This document defines the target structure for ALARMv3 as an **MCP-first, Codespaces-friendly modernization platform**. It supplements the broader architecture and MVP documents with the product boundaries, operating model, and implementation direction needed to move from planning into execution.

## Product Boundaries

ALARMv3 should be split into three clear product surfaces:

### 1. ALARM Core Engine
Pure Python library with no MCP assumptions.

Responsibilities:
- repository attachment metadata and fingerprinting
- full recursive discovery and manifest generation
- language parsing and dependency extraction
- architecture synthesis and knowledge artifact generation
- risk scoring and modernization recommendation ranking
- local artifact storage and indexing
- orchestration, retries, checkpoints, and provenance

### 2. ALARM MCP Wrapper
Thin MCP server layer over the core engine.

Responsibilities:
- expose MCP tools, resources, and prompts
- manage user confirmations and guardrail state
- stream progress and session status
- provide Codespaces-friendly interaction flow
- separate read-only analysis from optional implementation actions

### 3. Sync Adapters
Pluggable export/import layer for artifact destinations.

Initial adapter:
- Local filesystem only

Deferred adapter:
- SharePoint app-specific spaces

Rules:
- sync is never required for successful analysis completion
- local artifacts are always the system of record first
- adapters consume finalized artifacts rather than mutating analysis flow

## Primary Operating Model

### Default Mode
- User opens a legacy repository in GitHub Codespaces
- ALARM MCP attaches to the current repository explicitly
- ALARM confirms guardrails with the user
- ALARM performs read-only recursive analysis
- ALARM stores artifacts locally inside a deterministic session layout
- ALARM generates knowledge maps, findings, and prioritized modernization recommendations

### Optional Implementation Mode
- User explicitly selects recommendations to pursue
- ALARM creates a separate working repository or worktree plan
- Agent swarms implement selected changes outside the archived source baseline
- Tests, validation, and migration documentation are produced in the working repo

## Repository Treatment

### Attached Legacy Repository
- treated as archive/reference by default
- analysis is read-only and non-executing
- path access is confined to the attached root
- no write operations occur without separate implementation-mode consent

### Working Repository
- optional and explicitly created later
- holds modernization changes, generated tests, and migration journal artifacts
- can reuse knowledge generated from the archived repository session

## MCP-First Surface Model

ALARMv3 should treat MCP as the primary interface, with CLI and future web views acting as secondary surfaces over the same core session model.

Primary MCP surface areas:
- tools for attachment, analysis, synthesis, recommendation, and optional working-repo actions
- resources for trees, graphs, findings, recommendations, policy, and provenance
- prompts for guardrail confirmation, architecture explanation, strategy generation, and implementation swarm briefing

See:
- `planning/mcp_server_spec.md`
- `planning/artifact_and_orchestration_spec.md`

## Core Engine Module Structure

Recommended package decomposition:

```text
src/alarmv3/
├── core/
│   ├── session/          # session metadata, checkpoints, fingerprints
│   ├── guardrails/       # policy state machine, consent, audit events
│   ├── discovery/        # recursive traversal, file typing, manifest generation
│   ├── analysis/         # parsers, graphs, metrics, pattern detection
│   ├── synthesis/        # architecture maps, glossary, recommendations
│   ├── artifacts/        # JSON/Markdown emitters and schema versioning
│   ├── index/            # SQLite index, FTS, graph metadata tables
│   └── orchestration/    # workers, queues, retries, telemetry
├── mcp/
│   ├── server.py         # MCP server entrypoint
│   ├── tools.py          # MCP tool handlers
│   ├── resources.py      # MCP resource registry
│   └── prompts.py        # reusable MCP prompt templates
└── adapters/
    └── sync/
        ├── localfs.py    # local artifact persistence adapter
        └── sharepoint.py # deferred adapter contract/implementation
```

## Local-First Artifact Layout

Artifacts should be written under a deterministic session root:

```text
.alarmv3/
└── sessions/
    └── <session_id>/
        ├── manifest/
        ├── graphs/
        ├── analysis/
        ├── knowledge/
        ├── recommendations/
        ├── orchestration/
        ├── policy/
        └── index.db
```

Guidelines:
- JSON is the source of truth
- Markdown is generated from JSON for human review
- every artifact includes schema version, session id, timestamp, and provenance
- artifacts are safe to sync later without requiring recomputation

## Codespaces Guidance

ALARMv3 should be designed to work cleanly inside GitHub Codespaces:
- require explicit `attach_repository(path)` to bind the currently open repo
- default artifact storage to the workspace unless a persistent path is configured
- use bounded worker pools and file-size limits to fit Codespaces resource ceilings
- support checkpointing and incremental resume for interrupted sessions
- avoid reliance on always-on external infrastructure

## Guardrail Requirements

Guardrails are mandatory and persistent:
- read-only analysis is the default and must be confirmed before deep analysis
- analyzed code is never executed
- writes are denied against the attached repository in analysis mode
- working-repo creation requires separate confirmation
- every policy decision is stored as an auditable session artifact

## Parallel Swarm Model

Parallel analysis should be coverage-first rather than best-effort:
- create immutable traversal manifest before deep analysis
- partition work by directory, language, and size class
- use worker classes for discovery, parsing, graph building, and synthesis
- track completion, retries, and fallbacks per worker
- enforce coverage gates before session completion

## Coverage Contract

Each session should report proof of completeness:
- `mapped_files == manifest_files`
- `analyzed_files == eligible_files`
- unresolved parse failures are explicitly recorded
- dependency graph coverage is reported with confidence metadata

## Phased Delivery

### Phase 0: Architecture Hardening
- canonical MCP surface spec
- guardrail state machine
- artifact and provenance schemas
- adapter boundaries

### Phase 1: Core Read-Only Analysis
- manifest generation
- recursive mapping
- local artifact emission
- local search/index
- coverage reporting

### Phase 2: MCP Wrapper
- MCP tools/resources/prompts
- progress streaming
- guardrail UX and audit trail

### Phase 3: Advanced Synthesis
- architecture maps
- integration/version/security analysis
- prioritized modernization roadmap

### Phase 4: Working-Repo Modernization
- working repo/worktree planning
- implementation swarm briefs
- testing and migration journal output

### Phase 5: SharePoint Sync
- artifact bundle sync
- destination mapping
- conflict and checksum policy

