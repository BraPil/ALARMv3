# ALARMv3 MVP Scope & Implementation Plan

## MVP Definition

**Goal**: Deliver a working tool that provides immediate value to users analyzing legacy codebases for modernization.

**Timeline**: 4-6 weeks (assuming part-time development)

**Success Criteria**:
- Analyzes a codebase in < 2 minutes for 50k LOC
- Generates actionable recommendations
- Produces readable reports
- Supports 5+ programming languages
- Works out-of-box with minimal configuration

## MVP Feature Set

### ✅ In Scope (MUST HAVE)

#### 1. Basic Analysis Engine
- **File Scanner**
  - Recursive directory traversal
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

#### 5. CLI Interface
- `alarmv3 analyze <path>` - Run analysis
- `alarmv3 init-config` - Generate config template
- `alarmv3 version` - Show version info
- `alarmv3 help` - Show usage help

#### 6. Configuration
- **YAML-based config file**
  - Exclude/include patterns
  - Language preferences
  - Output settings
  - Risk thresholds

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
- Code transformations

### ❌ Out of Scope (NOT PLANNED)

- Actual code transformation/refactoring
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
│       ├── cli.py              # Click-based CLI
│       ├── config.py           # Configuration handling
│       ├── scanner.py          # File discovery
│       ├── analyzer.py         # Core analysis logic
│       ├── metrics.py          # Metrics calculation
│       ├── patterns.py         # Pattern detection
│       ├── risk.py             # Risk assessment
│       ├── recommendations.py  # Recommendation engine
│       ├── reports.py          # Report generation
│       └── utils.py            # Utilities
├── tests/
│   ├── __init__.py
│   ├── test_scanner.py
│   ├── test_analyzer.py
│   ├── test_recommendations.py
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

### 1. `scanner.py`
```python
class FileScanner:
    def scan(self, path: Path, config: Config) -> List[FileInfo]
    def detect_language(self, file: Path) -> Optional[str]
    def should_include(self, file: Path) -> bool
```

### 2. `analyzer.py`
```python
class Analyzer:
    def analyze_project(self, files: List[FileInfo]) -> Analysis
    def calculate_metrics(self, files: List[FileInfo]) -> Metrics
    def detect_frameworks(self, files: List[FileInfo]) -> List[Framework]
```

### 3. `risk.py`
```python
class RiskAssessor:
    def assess_file(self, file: FileInfo) -> RiskLevel
    def assess_project(self, analysis: Analysis) -> ProjectRisk
    def identify_hotspots(self, analysis: Analysis) -> List[Hotspot]
```

### 4. `recommendations.py`
```python
class RecommendationEngine:
    def generate(self, analysis: Analysis) -> List[Recommendation]
    def prioritize(self, recommendations: List[Recommendation]) -> List[Recommendation]
    def apply_rules(self, analysis: Analysis) -> List[Recommendation]
```

### 5. `reports.py`
```python
class ReportGenerator:
    def generate_markdown(self, analysis: Analysis) -> str
    def generate_json(self, analysis: Analysis) -> str
    def write_report(self, content: str, path: Path) -> None
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
