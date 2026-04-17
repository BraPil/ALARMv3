# ALARMv3 Technical Architecture

## System Overview

ALARMv3 is designed as a modular, extensible platform that balances simplicity with power. The architecture emphasizes progressive enhancement: works immediately with minimal setup, but supports advanced features when needed.

## Architectural Layers

### Layer 1: Interface Layer
**Purpose**: User interaction and command execution

```
┌─────────────────────────────────────┐
│         CLI Interface               │
│  • Commands (analyze, plan, track)  │
│  • Interactive prompts              │
│  • Progress indicators              │
└─────────────────────────────────────┘
           │
┌─────────────────────────────────────┐
│      Web UI (Optional)              │
│  • Dashboard                        │
│  • Project browser                  │
│  • Interactive reports              │
└─────────────────────────────────────┘
```

**Technologies:**
- CLI: Click or Typer
- Web: FastAPI + React (optional, future phase)

### Layer 2: Project Management Layer
**Purpose**: Session handling, state management, persistence

```
┌─────────────────────────────────────┐
│      Project Manager                │
│  ┌─────────────────────────────┐    │
│  │ ProjectSession              │    │
│  │  • Metadata                 │    │
│  │  • Configuration            │    │
│  │  • Analysis results         │    │
│  │  • Progress tracking        │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

**Data Storage:**
- SQLite for session data
- JSON for analysis results
- YAML for configuration

**Key Entities:**
```python
Project
  ├── id: str
  ├── name: str
  ├── path: Path
  ├── created_at: datetime
  ├── config: Config
  ├── analyses: List[Analysis]
  └── roadmap: MigrationRoadmap

Analysis
  ├── id: str
  ├── timestamp: datetime
  ├── metrics: CodeMetrics
  ├── findings: List[Finding]
  └── recommendations: List[Recommendation]

MigrationRoadmap
  ├── tasks: List[Task]
  ├── priorities: Dict[str, int]
  ├── estimates: Dict[str, str]
  └── dependencies: Graph
```

### Layer 3: Analysis Engine
**Purpose**: Core code analysis and understanding

```
┌─────────────────────────────────────────┐
│         Analysis Engine                 │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   File Scanner                  │    │
│  │    • Discovery                  │    │
│  │    • Filtering                  │    │
│  │    • Categorization             │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Language Analyzers            │    │
│  │    • Python Parser              │    │
│  │    • JavaScript/TS Parser       │    │
│  │    • Java Parser                │    │
│  │    • C#/C++ Parsers             │    │
│  │    • Generic Text Analyzer      │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Metrics Calculators           │    │
│  │    • Complexity                 │    │
│  │    • Maintainability            │    │
│  │    • Test coverage              │    │
│  │    • Dependency health          │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Pattern Detectors             │    │
│  │    • Anti-patterns              │    │
│  │    • Code smells                │    │
│  │    • Design patterns            │    │
│  │    • Framework usage            │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**Parser Strategy:**
- **tree-sitter**: Primary parser (universal, fast)
- **Language-specific AST**: Fallback for deeper analysis
- **Regex patterns**: Quick heuristics

**Metrics Collected:**
```python
CodeMetrics
  ├── lines_of_code: int
  ├── files_count: int
  ├── languages: Dict[str, int]
  ├── complexity_score: float (0-100)
  ├── maintainability_index: float (0-100)
  ├── test_coverage: float (0-100)
  ├── dependency_count: int
  ├── outdated_dependencies: int
  └── technical_debt_hours: float
```

### Layer 4: Intelligence Engine
**Purpose**: Generate insights, recommendations, and migration plans

```
┌─────────────────────────────────────────┐
│      Recommendation Engine              │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Risk Assessor                 │    │
│  │    • Complexity risk            │    │
│  │    • Change impact              │    │
│  │    • Dependency risk            │    │
│  │    • Test coverage risk         │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Priority Ranker               │    │
│  │    • Impact scoring             │    │
│  │    • Effort estimation          │    │
│  │    • Value calculation          │    │
│  │    • Dependency ordering        │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Task Generator                │    │
│  │    • Refactoring tasks          │    │
│  │    • Testing tasks              │    │
│  │    • Migration tasks            │    │
│  │    • Documentation tasks        │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Pattern Library               │    │
│  │    • Migration patterns         │    │
│  │    • Code templates             │    │
│  │    • Best practices             │    │
│  │    • Anti-pattern fixes         │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**Recommendation Types:**
```python
Recommendation
  ├── id: str
  ├── type: RecommendationType  # REFACTOR, TEST, UPDATE, DOCUMENT
  ├── priority: Priority  # CRITICAL, HIGH, MEDIUM, LOW
  ├── title: str
  ├── description: str
  ├── rationale: str
  ├── effort: Effort  # XS, S, M, L, XL
  ├── impact: Impact  # HIGH, MEDIUM, LOW
  ├── files_affected: List[Path]
  ├── code_snippets: List[CodeSnippet]
  ├── before_example: Optional[str]
  ├── after_example: Optional[str]
  ├── pattern: Optional[Pattern]
  └── dependencies: List[str]  # Other recommendation IDs
```

### Layer 5: Output Generation
**Purpose**: Create consumable reports and artifacts

```
┌─────────────────────────────────────────┐
│       Report Generators                 │
│  ┌─────────────────────────────────┐    │
│  │   Executive Report              │    │
│  │    • Summary                    │    │
│  │    • ROI analysis               │    │
│  │    • Timeline                   │    │
│  │    • Risk overview              │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Technical Report              │    │
│  │    • Detailed findings          │    │
│  │    • Code metrics               │    │
│  │    • Recommendations            │    │
│  │    • Migration roadmap          │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Task List                     │    │
│  │    • Prioritized backlog        │    │
│  │    • Effort estimates           │    │
│  │    • Dependencies               │    │
│  │    • Assignments                │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**Output Formats:**
- Markdown (primary)
- HTML (with CSS/JS for interactive)
- JSON (for API/integration)
- PDF (generated from HTML)

## Data Flow

### Analysis Workflow

```
1. User Input
   ├── CLI command: alarmv3 analyze /path/to/project
   └── Config file (optional)
        ↓
2. Project Initialization
   ├── Create/load project session
   ├── Load configuration
   └── Setup output directory
        ↓
3. File Discovery
   ├── Scan directory tree
   ├── Apply exclusion filters
   ├── Categorize by language
   └── Calculate initial metrics
        ↓
4. Deep Analysis
   ├── Parse files with appropriate parser
   ├── Extract AST information
   ├── Calculate complexity metrics
   ├── Build dependency graph
   └── Detect patterns and anti-patterns
        ↓
5. Intelligence Processing
   ├── Assess risks
   ├── Generate recommendations
   ├── Prioritize tasks
   ├── Estimate effort
   └── Create migration roadmap
        ↓
6. Output Generation
   ├── Generate reports
   ├── Create dashboards
   ├── Save session data
   └── Display summary to user
```

### Incremental Analysis

For large projects, support incremental analysis:
```
First Run:
  → Full scan + baseline metrics
  → Save results + file hashes

Subsequent Runs:
  → Scan for changed files
  → Re-analyze only changed files
  → Update dependency graph
  → Recalculate affected metrics
  → Compare with baseline
```

## Extension Points

### 1. Language Analyzers
```python
class LanguageAnalyzer(ABC):
    @abstractmethod
    def can_analyze(self, file: Path) -> bool:
        """Check if this analyzer supports the file"""
        
    @abstractmethod
    def analyze(self, file: Path) -> AnalysisResult:
        """Perform deep analysis of the file"""
        
    @abstractmethod
    def extract_dependencies(self, file: Path) -> List[Dependency]:
        """Extract import/dependency information"""
```

### 2. Pattern Detectors
```python
class PatternDetector(ABC):
    @abstractmethod
    def detect(self, code: CodeContext) -> List[Pattern]:
        """Detect patterns in the code"""
        
    @abstractmethod
    def severity(self, pattern: Pattern) -> Severity:
        """Assess pattern severity"""
```

### 3. Recommendation Generators
```python
class RecommendationGenerator(ABC):
    @abstractmethod
    def generate(self, analysis: Analysis) -> List[Recommendation]:
        """Generate recommendations from analysis"""
        
    @abstractmethod
    def prioritize(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """Prioritize recommendations"""
```

### 4. Report Formatters
```python
class ReportFormatter(ABC):
    @abstractmethod
    def format(self, data: ReportData) -> str:
        """Format report data"""
        
    @abstractmethod
    def extension(self) -> str:
        """File extension for this format"""
```

## Configuration Schema

```yaml
# alarmv3.yaml

project:
  name: "my_legacy_app"
  description: "Legacy app modernization"

analysis:
  target_path: "./src"
  
  scanner:
    max_file_size_mb: 10
    exclude_patterns:
      - "node_modules/**"
      - "*.min.js"
      - "__pycache__/**"
    include_patterns:
      - "**/*.py"
      - "**/*.js"
      - "**/*.java"
  
  languages:
    - python
    - javascript
    - java
  
  metrics:
    calculate_complexity: true
    calculate_maintainability: true
    analyze_dependencies: true
    detect_patterns: true

recommendations:
  risk_tolerance: medium  # low, medium, high
  
  priorities:
    security_issues: critical
    performance_issues: high
    code_quality: medium
    documentation: low
  
  effort_estimation: true
  dependency_analysis: true

roadmap:
  max_tasks: 50
  group_by: module  # module, priority, effort
  
  phases:
    - name: "Quick Wins"
      criteria: "effort:small AND impact:high"
    - name: "Foundation"
      criteria: "risk:high"
    - name: "Enhancement"
      criteria: "remaining"

output:
  directory: "./alarmv3_output"
  
  formats:
    - markdown
    - html
    - json
  
  reports:
    - executive_summary
    - technical_details
    - task_list
    - risk_matrix
  
  include_code_snippets: true
  max_snippet_lines: 20

plugins:
  enabled:
    - pattern_library
    - smart_recommendations
  
  optional:
    - ai_insights  # Requires additional setup
    - rag_search   # Requires vector DB
```

## Performance Considerations

### Optimization Strategies

1. **Lazy Loading**
   - Parse files only when deep analysis needed
   - Cache parsed ASTs for reuse

2. **Parallel Processing**
   - Analyze files in parallel
   - Use process pool for CPU-intensive tasks

3. **Incremental Analysis**
   - Track file changes
   - Only re-analyze modified files
   - Maintain dependency cache

4. **Memory Management**
   - Stream large files
   - Limit AST retention
   - Periodic garbage collection

5. **Caching**
   - Cache file hashes
   - Cache analysis results
   - Cache dependency graphs

### Scalability Targets

| Codebase Size | Analysis Time | Memory Usage |
|--------------|---------------|--------------|
| Small (< 10k LOC) | < 10 seconds | < 100 MB |
| Medium (10k-100k LOC) | < 2 minutes | < 500 MB |
| Large (100k-1M LOC) | < 10 minutes | < 2 GB |
| Very Large (> 1M LOC) | < 30 minutes | < 4 GB |

## Security Considerations

1. **Path Traversal**: Validate all paths, stay within project root
2. **Code Execution**: Never execute analyzed code
3. **Resource Limits**: Enforce file size and count limits
4. **Dependency Security**: Check dependencies for known vulnerabilities
5. **Data Privacy**: Don't send code to external services by default

## Testing Strategy

1. **Unit Tests**: Core algorithms and parsers
2. **Integration Tests**: End-to-end analysis workflows
3. **Performance Tests**: Scalability and resource usage
4. **Fixture Tests**: Real-world project samples
5. **Regression Tests**: Ensure consistency across versions
