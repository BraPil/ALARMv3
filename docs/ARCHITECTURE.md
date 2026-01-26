# ALARMv3 Architecture

## System Overview

ALARMv3 is designed as a modular, extensible platform for analyzing and modernizing legacy codebases. The architecture emphasizes:

- **Simplicity**: Clear separation of concerns
- **Extensibility**: Easy to add new analyzers and generators
- **Performance**: Efficient file processing and analysis
- **Configurability**: Flexible YAML-based configuration

## Core Components

### 1. Configuration System (`config.py`)

Manages all system configuration through a hierarchical structure:

```
Config
├── AnalyzerConfig (file discovery, language support)
├── ModernizationConfig (target frameworks, strategies)
├── AIConfig (AI/ML features - future expansion)
└── OutputConfig (report generation settings)
```

**Key Features:**
- YAML-based configuration files
- Sensible defaults for quick start
- Dataclass-based for type safety
- Easy serialization/deserialization

### 2. Core Engine (`core.py`)

The `ALARMv3Engine` is the heart of the system:

```python
ALARMv3Engine
├── analyze()              # Main analysis entry point
├── _discover_files()      # File system traversal
├── _detect_languages()    # Language identification
├── _calculate_complexity()  # Complexity scoring
├── _generate_recommendations()  # Smart suggestions
└── generate_report()      # Report creation
```

**Analysis Flow:**
1. File Discovery → Recursively find relevant files
2. Language Detection → Identify programming languages
3. Complexity Calculation → Assess codebase complexity
4. Recommendation Generation → Create actionable suggestions
5. Report Generation → Produce formatted output

### 3. CLI Interface (`cli.py`)

Command-line interface built with Click:

- `analyze`: Full analysis with report generation
- `quick-scan`: Fast scan without full report
- `init-config`: Generate configuration template
- `info`: Display system information

### 4. Result Types

**AnalysisResult**: Dataclass containing:
- Timestamp and project metadata
- File and language statistics
- Complexity scores
- Prioritization level
- Recommendations list
- Detailed findings dictionary

## Data Flow

```
User Input
    ↓
CLI Command Parser
    ↓
Configuration Loader
    ↓
ALARMv3Engine.analyze()
    ↓
├─→ File Discovery
├─→ Language Detection
├─→ Complexity Analysis
└─→ Recommendation Engine
    ↓
AnalysisResult
    ↓
Report Generator
    ↓
Output (Markdown/JSON)
```

## Extension Points

### Adding New Language Support

1. Update language map in `_detect_languages()`
2. Add file extension mappings
3. Update supported_languages in config

### Adding New Analysis Metrics

1. Create new calculation method in `ALARMv3Engine`
2. Add result fields to `AnalysisResult`
3. Update report generation to include new metrics

### Custom Recommendation Rules

1. Extend `_generate_recommendations()` method
2. Add conditional logic based on analysis results
3. Consider language, complexity, and project characteristics

## Design Principles

1. **Minimal Dependencies**: Core functionality uses standard library where possible
2. **Type Safety**: Dataclasses and type hints throughout
3. **Testability**: Pure functions and dependency injection
4. **Logging**: Comprehensive logging at all levels
5. **Error Handling**: Graceful degradation and informative errors

## Future Enhancements

- **Advanced AST Analysis**: Deep code structure analysis
- **RAG Integration**: Semantic code understanding (from v2)
- **ML-based Predictions**: Learning from past modernizations
- **Interactive Mode**: Step-by-step guided modernization
- **Plugin System**: External analyzer plugins
- **Multi-format Reports**: HTML, PDF, interactive dashboards

## Performance Considerations

- **File Filtering**: Early exclusion of irrelevant files
- **Lazy Loading**: Process files on-demand when needed
- **Parallel Processing**: Future enhancement for large codebases
- **Caching**: Result caching for repeated analyses

## Security Considerations

- **Path Validation**: Prevent directory traversal attacks
- **File Size Limits**: Prevent resource exhaustion
- **Safe YAML Loading**: Use safe_load for configuration
- **Input Sanitization**: Validate all user inputs
