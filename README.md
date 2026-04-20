# ALARMv3 - Research & Planning

**Automated Legacy App Refactoring and Modernization v3**

> 🚧 **Status**: Research and Planning Phase  
> This repository contains research, analysis, and architectural planning for the next generation of the ALARM toolchain.

## Project Overview

ALARMv3 is being designed as the next evolution of legacy code modernization tools, building upon:
- **ALARMv1**: C#-based tool focused on AutoCAD Map 3D and Oracle 19c migrations
- **ALARMv2**: Python-based comprehensive reverse engineering with RAG integration

## Current Phase: Research & Planning

We are currently in the research and planning phase, focusing on:

1. **Understanding the Evolution** 
   - Analyzing strengths and limitations of v1 and v2
   - Identifying patterns and lessons learned
   - Determining market gaps and opportunities

2. **Defining the Vision**
   - Target user personas and pain points
   - Core capabilities and features
   - Success metrics and goals

3. **Planning the Architecture**
   - System design and component architecture
   - Technology stack evaluation
   - Extension points and modularity

4. **Scoping the MVP**
   - Minimum viable feature set
   - Implementation timeline
   - Prioritization and phasing

## Repository Structure

```
ALARMv3/
├── README.md                    # This file
├── research/                    # Research and analysis documents
│   ├── alarmv1_analysis.md     # Deep dive into ALARMv1
│   ├── alarmv2_analysis.md     # Deep dive into ALARMv2
│   └── comparative_analysis.md # Comparison and synthesis
├── planning/                    # Planning and design documents
│   ├── vision_and_requirements.md         # Vision, personas, features
│   ├── technical_architecture.md          # System architecture
│   ├── mvp_scope.md                       # MVP definition and plan
│   ├── mcp_first_architecture.md          # MCP-first target structure
│   ├── mcp_server_spec.md                 # MCP tools/resources/prompts
│   └── artifact_and_orchestration_spec.md # Artifacts, coverage, orchestration
├── docs/                        # POC documentation
│   ├── POC_PLAN_ALARMv3.md     # POC scope and timeline
│   ├── METRICS.md               # Performance metrics template
│   └── EXPERIMENT_MATRIX.md     # Experiment tracking
└── scripts/                     # POC scripts
    ├── setup_env.sh             # Environment setup
    ├── run_index_and_log.sh     # Indexing pipeline
    ├── count_chroma.py          # Vector counting
    └── measure_cli_query.sh     # Latency measurement
```

## Research Documents

### [ALARMv1 Analysis](research/alarmv1_analysis.md)
In-depth analysis of the C#-based ALARM tool:
- Architecture patterns (adapter layers, MCP approach)
- Development methodology (test-first, incremental)
- Core tools (indexer, smoke tests, analyzers)
- Strengths and limitations

### [ALARMv2 Analysis](research/alarmv2_analysis.md)
Comprehensive review of the Python-based reverse engineering tool:
- RAG integration and semantic understanding
- Multi-language support and AST analysis
- Session management and query interface
- Strengths and limitations

### [Comparative Analysis](research/comparative_analysis.md)
Side-by-side comparison and synthesis:
- Evolution from v1 to v2
- Complementary strengths
- Gap analysis
- Market positioning
- The v3 opportunity

## Planning Documents

### [Vision & Requirements](planning/vision_and_requirements.md)
Defines what ALARMv3 should be:
- Vision statement and design philosophy
- Target user personas
- Feature roadmap (phases 1-4)
- Success metrics
- Technology considerations

### [Technical Architecture](planning/technical_architecture.md)
Detailed system design:
- Architectural layers and components
- Data models and flows
- Extension points
- Configuration schema
- Performance and security considerations

### [MVP Scope](planning/mvp_scope.md)
Implementation plan for the first release:
- MVP feature set (must-have vs. deferred)
- 4-6 week implementation timeline
- File structure and core modules
- Dependencies and success metrics
- Post-MVP roadmap

### [MCP-First Architecture](planning/mcp_first_architecture.md)
Target operating model for the next implementation phase:
- ALARM core vs MCP wrapper vs sync adapter boundaries
- read-only attached-repo flow and optional working-repo flow
- Codespaces-friendly local-first artifact model
- phased MCP-first delivery path

### [MCP Server Spec](planning/mcp_server_spec.md)
Canonical MCP contract for ALARMv3:
- tool surface
- resource inventory
- prompt inventory
- guardrail state transitions

### [Artifact & Orchestration Spec](planning/artifact_and_orchestration_spec.md)
Canonical local artifact and swarm-analysis contract:
- deterministic session layout
- provenance and coverage proof
- orchestration model and worker roles
- future SharePoint sync boundary

## POC (Proof of Concept)

In parallel with the planning phase, we've developed a POC framework to validate key design choices for ALARMv3. See [docs/POC_PLAN_ALARMv3.md](docs/POC_PLAN_ALARMv3.md) for details.

### POC Goals

1. **Reproducible indexing pipeline**: Measure index time, chunk/vector counts, and database size
2. **Retrieval quality vs model choice**: Compare embedding models (all-MiniLM vs CodeBERT)
3. **Vector DB feasibility**: Pilot Postgres+pgvector, Chroma, and FAISS prototypes
4. **Serving & latency**: Measure CLI/HTTP query latency and validate SLOs (target p95 < 200ms)
5. **Monitoring & drift baseline**: Produce similarity histograms and drift detection metrics
6. **CI/CD & reproducibility**: Ensure MLflow records dataset snapshots, docker tags, and git SHAs

### Quick Start

1. **Setup Environment**
   ```bash
   ./scripts/setup_env.sh
   source .venv/bin/activate
   ```

2. **Run Indexing Pipeline**
   ```bash
   # Create a demo app or use an existing codebase
   mkdir -p /tmp/demo_app
    echo "# Demo code" > /tmp/demo_app/main.py

   # Run indexing
   ./scripts/run_index_and_log.sh /tmp/demo_app ./out
   ```

3. **Count Vectors in Database**
   ```bash
   python scripts/count_chroma.py ./out/rag_db
   ```

4. **Measure Query Latency**
   ```bash
   # Find session_id from the created session file name
    SESSION_ID=$(ls ./out/session_*.json | head -1 | sed 's/.*session_//' | sed 's/.json//')

   # Measure latency with 100 queries
   ./scripts/measure_cli_query.sh $SESSION_ID "How does authentication work?" 100
   ```

### POC Documentation

- **[POC Plan](docs/POC_PLAN_ALARMv3.md)** - Scope, timeline, and acceptance criteria
- **[Metrics](docs/METRICS.md)** - Operational and quality metrics template
- **[Experiment Matrix](docs/EXPERIMENT_MATRIX.md)** - Experiment tracking structure

### POC Scripts

- `scripts/setup_env.sh` - Virtual environment setup with ML dependencies
- `scripts/run_index_and_log.sh` - Indexing pipeline with timestamped logging
- `scripts/count_chroma.py` - Vector and storage size measurement
- `scripts/measure_cli_query.sh` - Query latency benchmarking with SLO validation

Scripts produce structured JSON output for metrics aggregation. Session files track app_path, db_path, chunk counts, and duration for reproducibility.

## Key Insights

### What Makes v3 Different

1. **Intelligent Simplicity**: RAG-like insights without heavyweight setup
2. **Actionable by Default**: Every analysis produces concrete next steps
3. **Progressive Enhancement**: Works out-of-box, powerful with configuration
4. **Universal Yet Opinionated**: Supports any language but provides strong guidance
5. **Collaborative**: Built for teams, not just individuals

### The Sweet Spot

ALARMv3 aims to combine:
- **v1's prescriptive guidance** + **v2's universal understanding**
- Concrete migration plans + Deep code comprehension
- Modern AI assistance + Minimal setup complexity

## Next Steps

1. ✅ **Research Phase** (Complete)
   - Analyzed v1 and v2
   - Identified opportunities
   - Defined vision

2. ✅ **Planning Phase** (Complete)
   - Designed architecture
   - Scoped MVP
   - Created timeline

3. 🔄 **POC Phase** (In Progress)
   - Validate embedding model choices
   - Compare vector DB options
   - Measure retrieval quality and latency
   - Establish monitoring baselines

4. 🔄 **Validation Phase** (Next)
   - Review with stakeholders
   - Gather feedback on approach
   - Refine scope based on input

5. ⏳ **Implementation Phase** (Upcoming)
   - Build MCP-first MVP core
   - Iterate based on testing
   - Release v0.1.0

## Contributing

This project is currently in the planning phase. Feedback on the research and planning documents is welcome!

Areas where input would be valuable:
- User persona validation
- Feature prioritization
- Technology stack choices
- Architecture design patterns
- POC experiment results and insights

## License

To be determined (likely MIT)

## Contact

For questions or feedback, please open an issue in this repository.

---

**Note**: This repository is primarily research and planning documents with a POC framework for validation, including MCP-first architecture and artifact specifications that define the next implementation phase. Full implementation will begin after the planning and POC phases are validated and refined based on feedback.
