# ALARMv3

**Automated Legacy App Refactoring and Modernization v3**  
*Next Generation Code Intelligence Platform*

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-3.0.0-green.svg)](https://github.com/BraPil/ALARMv3)

## 🚀 Overview

ALARMv3 is the next evolution in automated legacy application analysis and modernization. Building on the foundations of ALARMv1 (C# AutoCAD/Oracle focus) and ALARMv2 (Python RAG-based reverse engineering), v3 delivers a unified, intelligent platform for comprehensive codebase analysis and modernization planning.

### Key Features

- 🔍 **Multi-Language Analysis**: Supports Python, JavaScript, TypeScript, Java, C#, C/C++, Go, Rust, PHP, Ruby
- 📊 **Complexity Assessment**: Automated complexity scoring and risk evaluation
- 🎯 **Smart Recommendations**: Context-aware modernization suggestions
- 📈 **Priority-Based Planning**: Risk-driven modernization roadmap generation
- 📄 **Comprehensive Reports**: Detailed analysis reports in multiple formats
- ⚡ **Fast & Efficient**: Optimized file discovery and analysis
- 🛠️ **Flexible Configuration**: YAML-based configuration system
- 💻 **CLI Interface**: Easy-to-use command-line tools

## 📦 Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/BraPil/ALARMv3.git
cd ALARMv3

# Install in development mode
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"
```

### Using pip (when published)

```bash
pip install alarmv3
```

## 🎯 Quick Start

### 1. Analyze a Project

```bash
# Basic analysis
alarmv3 analyze /path/to/your/project

# With custom project name and output directory
alarmv3 analyze /path/to/project --project-name "MyApp" --output ./reports

# Using a configuration file
alarmv3 analyze /path/to/project --config alarmv3_config.yaml
```

### 2. Quick Scan

```bash
# Fast scan without full report generation
alarmv3 quick-scan /path/to/your/project
```

### 3. Generate Configuration Template

```bash
# Create a configuration file
alarmv3 init-config
# Edit alarmv3_config.yaml as needed
```

### 4. View Information

```bash
# Display ALARMv3 capabilities and information
alarmv3 info
```

## 📖 Usage Examples

### Basic Analysis

```bash
alarmv3 analyze ./my-legacy-app
```

**Output:**
```
🔍 ALARMv3 v3.0.0 - Starting Analysis
Target: ./my-legacy-app

✅ Analysis Complete!

📊 Summary:
  • Files analyzed: 156
  • Languages: python, javascript
  • Complexity: 45.3/100
  • Priority: MEDIUM

📄 Report: ./alarmv3_output/my_project_report_20260126_210000.md

💡 Top Recommendations:
  1. Consider upgrading to Python 3.12 for latest features
  2. Migrate to TypeScript for type safety
  3. Establish CI/CD pipeline for automated testing
```

### Using Configuration File

Create `alarmv3_config.yaml`:

```yaml
project_name: "legacy_webapp"
target_path: "./legacy-app"
log_level: "INFO"

analyzer:
  max_file_size: 10485760
  supported_languages:
    - python
    - javascript
    - typescript
  exclude_patterns:
    - "*.pyc"
    - "node_modules/*"
    - "dist/*"

modernization:
  target_frameworks:
    - "Python 3.12"
    - "Node.js 20"
  risk_threshold: "medium"

output:
  output_dir: "./analysis_results"
  generate_reports: true
  report_format: "markdown"
```

Run analysis:

```bash
alarmv3 analyze . --config alarmv3_config.yaml
```

## 🏗️ Architecture

ALARMv3 follows a modular architecture:

```
┌─────────────────────────────────────────┐
│           CLI Interface                 │
│        (User Commands)                  │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│         ALARMv3 Engine                  │
│    (Core Analysis Logic)                │
│  ┌─────────────────────────────────┐    │
│  │  • File Discovery               │    │
│  │  • Language Detection           │    │
│  │  • Complexity Calculation       │    │
│  │  • Recommendation Generation    │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│        Configuration System             │
│     (YAML-based Settings)               │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│         Report Generator                │
│    (Markdown/JSON Output)               │
└─────────────────────────────────────────┘
```

## 📊 Analysis Capabilities

### Language Detection

Automatically identifies programming languages in your codebase:
- Python (.py)
- JavaScript (.js, .jsx)
- TypeScript (.ts, .tsx)
- Java (.java)
- C# (.cs)
- C/C++ (.c, .cpp, .cc)
- Go (.go)
- Rust (.rs)
- PHP (.php)
- Ruby (.rb)

### Complexity Scoring

Analyzes codebase complexity based on:
- File count and distribution
- Average file size
- Language diversity
- Project structure

Scores range from 0-100:
- **0-30**: Low complexity (straightforward modernization)
- **30-60**: Medium complexity (requires planning)
- **60-100**: High complexity (significant effort needed)

### Recommendations

Generates context-aware recommendations:
- Language-specific upgrade paths
- Modern framework suggestions
- Testing strategies
- Architectural improvements
- Risk mitigation approaches

## 🔧 Configuration Options

### Analyzer Configuration

```yaml
analyzer:
  max_file_size: 10485760  # Maximum file size to analyze (bytes)
  supported_languages:     # Languages to include
    - python
    - javascript
  exclude_patterns:        # Patterns to exclude
    - "*.min.js"
    - "node_modules/*"
```

### Modernization Configuration

```yaml
modernization:
  target_frameworks:       # Target technologies
    - ".NET 8"
    - "Python 3.12"
  migration_strategies:    # Preferred approaches
    - "incremental"
    - "test-first"
  risk_threshold: "medium" # Risk tolerance (low/medium/high)
```

### Output Configuration

```yaml
output:
  output_dir: "./reports"
  generate_reports: true
  report_format: "markdown"  # markdown, html, json
```

## 🔄 Evolution

ALARMv3 represents the culmination of lessons learned from previous versions:

### ALARMv1 (C#)
- Focus: AutoCAD Map 3D and Oracle 19c migrations
- Architecture: Adapter pattern with .NET 8
- Approach: Incremental, test-first refactoring

### ALARMv2 (Python)
- Focus: Comprehensive reverse engineering
- Features: RAG integration, multi-language support
- Tools: AST parsing, complexity analysis

### ALARMv3 (Next-Gen)
- Focus: Unified intelligence platform
- Features: Smart recommendations, priority-based planning
- Design: Modular, extensible, configuration-driven
- Goal: Streamlined analysis with actionable insights

## 🛠️ Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/BraPil/ALARMv3.git
cd ALARMv3

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (if available)
pytest

# Format code
black src/

# Lint code
ruff src/
```

### Project Structure

```
ALARMv3/
├── src/alarmv3/           # Main package
│   ├── __init__.py        # Package initialization
│   ├── cli.py             # Command-line interface
│   ├── config.py          # Configuration management
│   └── core.py            # Core analysis engine
├── tests/                 # Test suite
├── docs/                  # Documentation
├── examples/              # Usage examples
├── pyproject.toml         # Project configuration
└── README.md              # This file
```

## 📝 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📬 Support

- Issues: [GitHub Issues](https://github.com/BraPil/ALARMv3/issues)
- Documentation: [GitHub Wiki](https://github.com/BraPil/ALARMv3/wiki)

## 🙏 Acknowledgments

Built upon the foundations of ALARMv1 and ALARMv2, incorporating lessons learned from real-world legacy modernization projects.

---

**ALARMv3** - Making Legacy Modernization Intelligent and Efficient
