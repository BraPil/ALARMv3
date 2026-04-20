# AAA + ALARMv3 Strategy Notes — 2026-04-20

## Context  
This discussion focused on using BraPil/Agentic-AI-Architect to help develop BraPil/ALARMv3.

## Key conclusions  
- Agentic-AI-Architect should run as a separate server/process initially and be consumed by ALARMv3 over REST.
- ALARMv3 should likely become MCP-capable and likely MCP-first for v3 UX but still be built on a modular core engine.
- ALARMv3 should preserve the original legacy repo as a read-only reference while writing artifacts and modernization work to separate locations.
- A bounded orchestration/task-queue model is preferred over unconstrained self-cloning swarms.
- Storage should start local-first with local artifacts plus SQLite or similar and later evolve toward Postgres/pgvector and SharePoint sync.
- AAA should host influencer/source-grounded persona analogs internally instead of as many separate standalone bots.

## ALARMv3 vision captured in this discussion  
The user's desired workflow in GitHub Codespaces: user loads ALARM MCP in a legacy app workspace, ALARM detects and confirms the target codebase and archive guardrails, recursively maps the application with parallel workers, builds a compendium and architecture maps, performs analysis and prioritizes modernization suggestions, and upon approval creates a separate local repo/workspace to implement and test selected upgrades.

## Recommended ALARMv3 architecture direction  
### Interaction surface  
MCP tools/resources/prompts for attach workspace, guardrails, discovery/mapping, analysis/recommendations, and transformation.

### Core engine  
Workspace manager, guardrail manager, discovery engine, swarm/task orchestrator, knowledge/indexing layer, analysis engine, recommendation engine, transformation engine, and sync adapters.

### Storage and artifacts  
Local-first artifact layout under .alarm or similar and future SharePoint sync adapter.

### Safety model  
Source repo, artifact repo/path, and target modernization repo.

### Phased implementation  
A staged path from safe discovery to recursive mapping to knowledge retrieval to analysis/prioritization to transformation mode to external sync/advisor integrations.

## Recommended AAA architecture direction  
### Persona analogs  
ColeBot should be absorbed into AAA as a persona/source profile pattern and extended to other influential voices like Andrej Karpathy, Alex Wang, Yann LeCun, etc.

### Shared pipeline  
Persona analogs should be source-grounded approximations of public views rather than pretending to be the actual person.

### MCP tools for personas  

### Why not 20 separate bots  

## Codespaces / Claude Code workflow guidance  
The recommended setup is a Claude Code panel in the IDE plus integrated terminals for runtime, validation, jobs, and optionally a terminal claude session. The difference between orchestration terminals and validation/background terminals should be explained. 

## Open questions / next steps  
- Defining ALARM MCP tools/resources/prompts.
- Designing the AAA persona registry schema and source ingestion rules.
- Choosing local-first metadata/vector storage details.
- Defining SharePoint sync endpoints later.
- Deciding when and how AAA should expose MCP surfaces.

## Important caveats  
Exhaustive coverage should be treated as a measurable goal with explicit coverage reporting rather than an unverifiable absolute claim, and destructive or implementation actions should require explicit approval boundaries.