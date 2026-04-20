# ALARMv3 Artifact, Index, and Orchestration Specification

## Purpose

This document defines the canonical local artifact model, coverage proof contract, orchestration strategy, and sync adapter boundary for ALARMv3.

## Artifact Principles

- local-first storage
- JSON as source of truth
- Markdown generated for human-readable views
- schema-versioned artifacts
- provenance attached to every artifact
- no external sync required for successful analysis

## Session Layout

```text
.alarmv3/
└── sessions/
    └── <session_id>/
        ├── manifest/
        │   ├── repository.json
        │   ├── files.json
        │   └── coverage.json
        ├── graphs/
        │   ├── dependency_graph.json
        │   ├── call_graph.json
        │   └── module_graph.json
        ├── analysis/
        │   ├── security_findings.json
        │   ├── functionality_findings.json
        │   ├── integration_risks.json
        │   └── version_gaps.json
        ├── knowledge/
        │   ├── architecture_map.json
        │   ├── component_catalog.json
        │   ├── glossary.json
        │   └── architecture_map.md
        ├── recommendations/
        │   ├── prioritized.json
        │   └── roadmap.md
        ├── orchestration/
        │   ├── run.json
        │   ├── workers.json
        │   └── progress_events.jsonl
        ├── policy/
        │   ├── guardrails.json
        │   └── audit_log.jsonl
        └── index.db
```

## Required Artifact Metadata

Every artifact should include:
- `schema_version`
- `session_id`
- `created_at`
- `repository_fingerprint`
- `generator`
- `provenance`

Minimum provenance fields:
- worker id or tool name
- source artifact references
- file set or shard processed
- fallback mode, if any

## Coverage Proof Contract

Each session must produce a coverage artifact with:
- total discovered files
- total eligible files
- mapped files count
- analyzed files count
- excluded files with reason
- unresolved parse count
- unresolved dependency edges count
- confidence summary by artifact family

Completion gates:
- mapped files must equal manifest files
- analyzed files must equal eligible files, or explicit fallback records must exist
- unresolved parse rate must remain below configurable threshold
- final recommendation generation must declare the analysis scope it used

## Parallel Orchestration Model

### Coordinator Responsibilities
- create immutable traversal manifest
- shard work by directory, language, and file size class
- schedule workers with bounded concurrency
- persist retries, fallbacks, and timings
- block completion until coverage gates pass

### Worker Types
- discovery workers
- parser workers
- dependency graph workers
- synthesis workers

### Worker Requirements
- deterministic input shard definition
- explicit retry policy
- structured failure capture
- artifact-level provenance output

## Local Index Strategy

Use SQLite as the session-local index:
- metadata tables for files, artifacts, findings, and recommendations
- FTS tables for glossary, architecture narratives, and recommendation text
- graph tables for dependency and call relationships

The index should support:
- exact lookup by file, component, or session id
- text search across generated knowledge
- lightweight joins across findings and recommendations

## Sync Adapter Boundary

Define an `ArtifactSyncAdapter` interface now.

Responsibilities:
- push finalized artifacts
- pull sync status
- validate checksums and schema version compatibility
- record sync outcomes without mutating source artifacts

### LocalFS Adapter
- default implementation
- writes to deterministic local session layout

### SharePoint Adapter
- deferred implementation
- target is app-specific spaces
- must consume finalized local bundles
- must not sit in the critical analysis path

## Codespaces Resource Strategy

- bounded worker pool sized for Codespaces CPU/memory limits
- file-size limits for parser tasks
- checkpoint after manifest, graphs, analysis, and recommendations
- resumable session behavior after Codespace stop/restart

