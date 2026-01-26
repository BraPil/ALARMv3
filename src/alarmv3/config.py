"""Configuration management for ALARMv3."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class AnalyzerConfig:
    """Configuration for code analysis."""

    max_file_size: int = 10 * 1024 * 1024  # 10MB default
    supported_languages: List[str] = field(
        default_factory=lambda: [
            "python",
            "javascript",
            "typescript",
            "java",
            "csharp",
            "cpp",
            "go",
            "rust",
            "php",
            "ruby",
        ]
    )
    exclude_patterns: List[str] = field(
        default_factory=lambda: [
            "*.pyc",
            "__pycache__/*",
            "node_modules/*",
            "*.min.js",
            "*.min.css",
            "dist/*",
            "build/*",
            ".git/*",
        ]
    )
    include_patterns: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class ModernizationConfig:
    """Configuration for modernization strategies."""

    target_frameworks: List[str] = field(
        default_factory=lambda: [".NET 8", "Python 3.12", "Node.js 20", "Java 21"]
    )
    migration_strategies: List[str] = field(
        default_factory=lambda: ["incremental", "adapter-pattern", "test-first"]
    )
    risk_threshold: str = "medium"  # low, medium, high


@dataclass
class AIConfig:
    """Configuration for AI/ML features."""

    enable_ai: bool = True
    enable_rag: bool = True
    model_name: str = "default"
    max_context_size: int = 8192
    temperature: float = 0.7


@dataclass
class OutputConfig:
    """Configuration for output generation."""

    output_dir: Path = field(default_factory=lambda: Path("./alarmv3_output"))
    generate_reports: bool = True
    generate_documentation: bool = True
    report_format: str = "markdown"  # markdown, html, json


@dataclass
class Config:
    """Main configuration for ALARMv3."""

    project_name: str = "alarmv3_project"
    target_path: Path = field(default_factory=lambda: Path("."))
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    modernization: ModernizationConfig = field(default_factory=ModernizationConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    log_level: str = "INFO"

    @classmethod
    def from_file(cls, config_path: Path) -> "Config":
        """Load configuration from YAML file."""
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        return cls(
            project_name=data.get("project_name", "alarmv3_project"),
            target_path=Path(data.get("target_path", ".")),
            analyzer=AnalyzerConfig(**data.get("analyzer", {})),
            modernization=ModernizationConfig(**data.get("modernization", {})),
            ai=AIConfig(**data.get("ai", {})),
            output=OutputConfig(
                output_dir=Path(data.get("output", {}).get("output_dir", "./alarmv3_output")),
                **{k: v for k, v in data.get("output", {}).items() if k != "output_dir"},
            ),
            log_level=data.get("log_level", "INFO"),
        )

    def to_file(self, config_path: Path) -> None:
        """Save configuration to YAML file."""
        data = {
            "project_name": self.project_name,
            "target_path": str(self.target_path),
            "analyzer": {
                "max_file_size": self.analyzer.max_file_size,
                "supported_languages": self.analyzer.supported_languages,
                "exclude_patterns": self.analyzer.exclude_patterns,
                "include_patterns": self.analyzer.include_patterns,
            },
            "modernization": {
                "target_frameworks": self.modernization.target_frameworks,
                "migration_strategies": self.modernization.migration_strategies,
                "risk_threshold": self.modernization.risk_threshold,
            },
            "ai": {
                "enable_ai": self.ai.enable_ai,
                "enable_rag": self.ai.enable_rag,
                "model_name": self.ai.model_name,
                "max_context_size": self.ai.max_context_size,
                "temperature": self.ai.temperature,
            },
            "output": {
                "output_dir": str(self.output.output_dir),
                "generate_reports": self.output.generate_reports,
                "generate_documentation": self.output.generate_documentation,
                "report_format": self.output.report_format,
            },
            "log_level": self.log_level,
        }

        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
