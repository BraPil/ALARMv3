# ALARMv3 MVP Scope & Implementation Plan

## MVP Definition

**Goal**: Deliver a working MCP-first tool that provides immediate value to users analyzing legacy codebases for modernization while preserving the attached repository as a read-only reference baseline.

**Timeline**: 4-6 weeks for an initial MCP-first foundation (assuming part-time development)

**Success Criteria**:
- Analyzes a codebase in < 2 minutes for 50k LOC
- Generates actionable recommendations
- Produces readable reports
- Supports 5+ programming languages
- Works out-of-box with minimal configuration

## MVP Feature Set

### ✅ In Scope (MUST HAVE)

#### 0. MCP-First Session and Guardrails
- Explicit repository attachment
- Mandatory guardrail confirmation before deep analysis
- Read-only analysis mode locked by default
- Session provenance and audit trail

#### 1. Basic Analysis Engine
- **File Scanner**
  - Recursive directory traversal
  - Immutable traversal manifest
  - Pattern-based filtering (exclude node_modules, etc.)
  - File size limits
  - Language detection by extension

- **Metrics Collection**
  - Lines of code per language
  - File count and structure
  - Basic complexity scoring (heuristic-based)
  - Dependency counting

- **Pattern Detection (Basic)**
  - Common anti-patterns (hardcoded credentials, etc.)
  - Framework detection (Django, React, Spring, etc.)
  - Configuration file identification
  - Coverage proof for mapped vs analyzed files

#### 2. Risk Assessment
- **Complexity Scoring**
  - File size-based
  - File count-based
  - Language diversity factor
  - Overall project complexity (0-100 scale)

- **Risk Classification**
  - Per-file risk levels (low/medium/high)
  - Project-level risk assessment
  - Hotspot identification (high-risk areas)

#### 3. Recommendations
- **Rule-Based Recommendations**
  - Language version upgrades (e.g., Python 2 → 3)
  - Outdated framework warnings
  - Missing tests indicators
  - Code organization suggestions

- **Prioritization**
  - Critical (security issues)
  - High (performance issues)
  - Medium (code quality)
  - Low (nice-to-have improvements)

#### 4. Reports
- **Markdown Report**
  - Executive summary
  - Metrics overview
  - Top 10 recommendations
  - Risk assessment
  - File structure overview

- **JSON Output**
  - Complete analysis data
  - Machine-readable format
  - For tool integration

#### 5. MCP Server Surface
- `attach_repository(path)`
- `confirm_guardrails(policy_profile)`
- `start_full_mapping(session_id, mode=read_only)`
- `run_dependency_analysis(session_id, depth=all)`
- `generate_architecture_knowledge(session_id)`
- `generate_modernization_recommendations(session_id, prioritization_profile)`

#### 6. CLI Interface
- `alarmv3 analyze <path>` - Run analysis
- `alarmv3 init-config` - Generate config template
- `alarmv3 version` - Show version info
- `alarmv3 help` - Show usage help

#### 7. Configuration
- **YAML-based config file**
  - Exclude/include patterns
  - Language preferences
  - Output settings
  - Risk thresholds
  - Worker pool and checkpoint settings

- **Sensible defaults**
  - Works without config file
  - Common exclusions pre-configured

### ⏭️ Deferred (POST-MVP)

#### Phase 2 Features
- Deep AST parsing
- Cyclomatic complexity calculation
- Dependency graph visualization
- HTML/PDF reports
- Interactive web UI
- Progress/event streaming for long MCP sessions
- Migration roadmap generation
- Effort estimation
- Task sequencing

#### Phase 3 Features
- AI-powered insights
- RAG integration
- Natural language queries
- Automated refactoring suggestions
- Team collaboration features
- CI/CD integration
- Progress tracking
- Code transformations in isolated working repos

#### Phase 4 Features
- Working repository/worktree creation
- Agent-swarm implementation briefs
- Migration journal generation
- SharePoint sync adapter

### ❌ Out of Scope (NOT PLANNED)

- Actual code transformation/refactoring
- Direct modification of the attached legacy repo during analysis mode
- IDE integration
- Real-time code analysis
- Cloud-hosted service
- Commercial licensing/support

## Technical Implementation Plan

### Week 1-2: Foundation

#### Day 1-3: Project Setup
```
✓ Repository structure
✓ Python package setup (pyproject.toml)
✓ Development environment
✓ Basic tests framework
✓ CI/CD pipeline (GitHub Actions)
```

**Deliverable**: Installable package with `alarmv3 --version`

#### Day 4-7: File Scanner
```
✓ Directory traversal
✓ Pattern filtering
✓ File categorization
✓ Language detection
✓ Basic metrics collection
```

**Deliverable**: `alarmv3 analyze .` shows file counts and languages

#### Day 8-10: Configuration System
```
✓ YAML config parsing
✓ Default configuration
✓ Config validation
✓ `init-config` command
```

**Deliverable**: Works with and without config file

### Week 3-4: Analysis Engine

#### Day 11-14: Basic Analysis
```
✓ Complexity scoring algorithm
✓ Framework detection
✓ Configuration file detection
✓ Dependency identification (imports, package files)
```

**Deliverable**: Analysis produces metrics and findings

#### Day 15-17: Risk Assessment
```
✓ Risk scoring per file
✓ Hotspot identification
✓ Project-level risk calculation
✓ Risk categorization
```

**Deliverable**: Risk assessment in analysis results

#### Day 18-21: Recommendations
```
✓ Rule-based recommendation engine
✓ Language-specific rules
✓ Framework-specific rules
✓ Priority assignment
```

**Deliverable**: Top 10 actionable recommendations

### Week 5-6: Output & Polish

#### Day 22-25: Report Generation
```
✓ Markdown report formatter
✓ JSON output formatter
✓ Report sections (summary, metrics, recommendations)
✓ Code snippet inclusion
```

**Deliverable**: Readable Markdown report

#### Day 26-28: Testing & Validation
```
✓ Unit tests for core functions
✓ Integration tests for workflows
✓ Test on 5 real-world projects
✓ Performance testing
```

**Deliverable**: 80% test coverage, validated on real code

#### Day 29-30: Documentation & Release
```
✓ README with examples
✓ Usage documentation
✓ Architecture documentation
✓ Changelog
✓ v0.1.0 release
```

**Deliverable**: Publishable package with docs

## File Structure (MVP)

```
ALARMv3/
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   └── alarmv3/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py                    # Secondary CLI surface
│       ├── config.py                 # Configuration handling
│       ├── mcp/
│       │   ├── server.py             # MCP server entrypoint
│       │   ├── tools.py              # MCP tool handlers
│       │   ├── resources.py          # MCP resource registry
│       │   └── prompts.py            # MCP prompt templates
│       ├── core/
│       │   ├── session.py            # Session metadata and checkpoints
│       │   ├── guardrails.py         # Policy and consent state
│       │   ├── discovery.py          # Recursive manifest generation
│       │   ├── analysis.py           # Core analysis logic
│       │   ├── synthesis.py          # Knowledge and recommendations
│       │   ├── artifacts.py          # JSON/Markdown output
│       │   ├── index.py              # SQLite artifact index
│       │   └── orchestration.py      # Worker coordination and telemetry
│       └── adapters/
│           └── sync/
│               ├── localfs.py        # Local artifact persistence
│               └── sharepoint.py     # Deferred sync adapter
├── tests/
│   ├── __init__.py
│   ├── test_discovery.py
│   ├── test_analysis.py
│   ├── test_guardrails.py
│   ├── test_mcp_server.py
│   └── fixtures/
│       └── sample_projects/
├── docs/
│   ├── getting_started.md
│   ├── configuration.md
│   └── architecture.md
└── examples/
    └── alarmv3_config.yaml
```

## Core Modules (MVP)

### 1. `core/discovery.py`
```python
class DiscoveryEngine:
    def attach_repository(self, path: Path) -> ProjectSession
    def build_manifest(self, session: ProjectSession) -> TraversalManifest
    def detect_language(self, file: Path) -> Optional[str]
```

### 2. `core/analysis.py`
```python
class AnalysisEngine:
    def analyze_manifest(self, manifest: TraversalManifest) -> Analysis
    def calculate_metrics(self, files: List[FileInfo]) -> Metrics
    def build_dependency_graph(self, files: List[FileInfo]) -> Graph
```

### 3. `core/guardrails.py`
```python
class GuardrailManager:
    def confirm(self, session: ProjectSession, profile: PolicyProfile) -> GuardrailState
    def enforce_read_only(self, session: ProjectSession) -> None
    def write_audit_event(self, event: PolicyEvent) -> None
```

### 4. `core/synthesis.py`
```python
class SynthesisEngine:
    def generate_architecture_map(self, analysis: Analysis) -> ArchitectureMap
    def generate(self, analysis: Analysis) -> List[Recommendation]
    def prioritize(self, recommendations: List[Recommendation]) -> List[Recommendation]
```

### 5. `mcp/tools.py`
```python
class MCPToolHandlers:
    def attach_repository(self, path: str) -> ToolResult
    def confirm_guardrails(self, policy_profile: str) -> ToolResult
    def start_full_mapping(self, session_id: str, mode: str = "read_only") -> ToolResult
    def generate_modernization_recommendations(self, session_id: str, prioritization_profile: str) -> ToolResult
```

## Dependencies (Minimal)

```toml
[project]
dependencies = [
    "click>=8.0",         # CLI framework
    "pyyaml>=6.0",        # Config parsing
    "rich>=13.0",         # Pretty CLI output
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "black>=23.0",
    "ruff>=0.1.0",
]
```

## Success Metrics (MVP)

### Functional
- ✅ Analyzes Python, JavaScript, Java, C#, Go projects
- ✅ Completes analysis in < 2 minutes for 50k LOC
- ✅ Generates readable Markdown report
- ✅ Produces 5+ actionable recommendations
- ✅ Identifies risk hotspots

### Quality
- ✅ 80% test coverage
- ✅ Zero critical bugs
- ✅ < 5 medium bugs
- ✅ Documentation covers all features

### User Experience
- ✅ Install to first report: < 5 minutes
- ✅ Works without configuration
- ✅ Clear, actionable output
- ✅ No external service dependencies

## Risk Mitigation

### Technical Risks
1. **Performance on large codebases**
   - Mitigation: File size limits, streaming processing
   
2. **Language detection accuracy**
   - Mitigation: Extension-based as fallback, expandable mapping

3. **Recommendation quality**
   - Mitigation: Start conservative, gather feedback, iterate

### Scope Risks
1. **Feature creep**
   - Mitigation: Strict MVP definition, defer non-essential features

2. **Over-engineering**
   - Mitigation: Simple implementations first, refactor later

## Post-MVP Roadmap

### v0.2.0 - Enhanced Analysis
- Tree-sitter integration for AST parsing
- Cyclomatic complexity
- Dependency graph
- HTML reports

### v0.3.0 - Intelligence
- Pattern recognition library
- Migration pattern templates
- Effort estimation
- Task roadmap generation

### v0.4.0 - Collaboration
- Web UI dashboard
- Project workspaces
- Progress tracking
- Export to project management tools

### v1.0.0 - Production Ready
- Comprehensive testing
- Performance optimization
- Complete documentation
- Plugin system
- Stable API
