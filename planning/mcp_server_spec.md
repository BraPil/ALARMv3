# ALARMv3 MCP Server Specification

## Purpose

This document defines the canonical MCP-facing surface for ALARMv3. The goal is to make the MCP server a stable wrapper over the core engine while keeping policy, artifacts, and session state explicit.

## Design Rules

- MCP is the primary interactive surface
- tool handlers delegate to core engine services
- resources expose durable session state and generated knowledge
- prompts standardize user confirmations and downstream agent work
- MCP must preserve the attached repository as read-only during analysis mode

## Required MCP Tools

### Repository and Session
- `attach_repository(path)`
  - validates path
  - captures repository fingerprint
  - creates or resumes a session
  - refuses unsafe roots or parent-directory escape

- `confirm_guardrails(policy_profile)`
  - records user consent
  - locks analysis mode to read-only
  - stores guardrail artifact and audit event

### Analysis and Mapping
- `start_full_mapping(session_id, mode="read_only")`
  - builds traversal manifest
  - launches discovery/parsing workers
  - emits manifest and coverage telemetry

- `run_dependency_analysis(session_id, depth="all")`
  - builds dependency, module, and call relationships
  - records unresolved edges with fallback reasons

- `run_security_functionality_integration_version_analysis(session_id)`
  - produces categorized findings
  - stores confidence metadata and source references

### Knowledge and Recommendations
- `generate_architecture_knowledge(session_id)`
  - generates architecture map, component catalog, glossary, and narrative summaries

- `generate_modernization_recommendations(session_id, prioritization_profile)`
  - creates ranked recommendations with rationale, effort, impact, and sequencing dependencies

### Optional Implementation Flow
- `create_working_repo_plan(session_id)`
  - defines safe implementation scope and repo/worktree strategy

- `spawn_working_repo(session_id, selected_items)`
  - requires separate confirmation
  - creates isolated implementation target
  - copies or links approved artifacts only

## Required MCP Resources

### Repository
- `repo/tree`
- `repo/dependency-graph`
- `repo/call-graph`
- `repo/framework-inventory`

### Analysis
- `analysis/security-findings`
- `analysis/functionality-findings`
- `analysis/integration-risks`
- `analysis/version-gaps`

### Knowledge
- `knowledge/architecture-map`
- `knowledge/component-catalog`
- `knowledge/glossary`

### Recommendations
- `recommendations/prioritized`
- `recommendations/roadmap`

### Session and Policy
- `session/guardrails`
- `session/provenance`
- `session/coverage-proof`
- `session/progress`

## Required MCP Prompts

- `guardrails_confirmation_prompt`
  - explains read-only analysis, no code execution, path confinement, and optional later implementation mode

- `architecture_explainer_prompt`
  - explains generated architecture maps and major subsystems in user-facing language

- `modernization_strategy_prompt`
  - turns findings into phased modernization options with rationale

- `implementation_swarm_brief_prompt`
  - packages selected recommendations into an isolated working-repo execution brief

- `validation_and_test_plan_prompt`
  - proposes test, validation, and documentation tasks for selected modernization changes

## Guardrail State Machine

```text
UNATTACHED
  ↓ attach_repository
ATTACHED
  ↓ confirm_guardrails
READ_ONLY_CONFIRMED
  ↓ start_full_mapping
ANALYSIS_IN_PROGRESS
  ↓ analysis complete
ANALYSIS_COMPLETE
  ↓ create_working_repo_plan
IMPLEMENTATION_PLANNED
  ↓ explicit approval
WORKING_REPO_READY
```

Rules:
- analysis tools are unavailable until guardrails are confirmed
- write-capable implementation actions are unavailable in read-only analysis state
- all state transitions are logged to session provenance

## MCP Error Boundaries

Errors should be reported as structured session-safe failures:
- invalid path / unsafe root
- missing guardrail confirmation
- artifact not yet generated
- resource limit exceeded
- worker failure with partial fallback preserved

## Codespaces Expectations

- the MCP server should assume the user is operating in the current Codespaces workspace
- path handling must avoid accidental attachment to parent directories
- long-running mapping must support resumable progress updates
- local artifacts must remain usable even if the Codespace is stopped and resumed

