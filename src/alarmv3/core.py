"""Core engine for ALARMv3."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging
from datetime import datetime

from alarmv3.config import Config


@dataclass
class AnalysisResult:
    """Results from code analysis."""

    timestamp: str
    project_name: str
    total_files: int
    languages_detected: List[str]
    complexity_score: float
    modernization_priority: str
    recommendations: List[str]
    detailed_findings: Dict[str, Any]


class ALARMv3Engine:
    """Main engine for ALARMv3 operations."""

    def __init__(self, config: Config):
        """Initialize the ALARM engine."""
        self.config = config
        self.logger = self._setup_logging()
        self._ensure_output_directory()

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration."""
        logger = logging.getLogger("alarmv3")
        logger.setLevel(getattr(logging, self.config.log_level))

        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger

    def _ensure_output_directory(self) -> None:
        """Ensure output directory exists."""
        self.config.output.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Output directory: {self.config.output.output_dir}")

    def analyze(self, target_path: Optional[Path] = None) -> AnalysisResult:
        """
        Analyze a codebase for modernization opportunities.

        Args:
            target_path: Path to analyze (uses config if not provided)

        Returns:
            AnalysisResult with findings and recommendations
        """
        target = target_path or self.config.target_path
        self.logger.info(f"Starting analysis of: {target}")

        # Discover files
        files = self._discover_files(target)
        self.logger.info(f"Discovered {len(files)} files")

        # Detect languages
        languages = self._detect_languages(files)
        self.logger.info(f"Languages detected: {', '.join(languages)}")

        # Calculate complexity
        complexity = self._calculate_complexity(files)
        self.logger.info(f"Complexity score: {complexity:.2f}")

        # Generate recommendations
        recommendations = self._generate_recommendations(languages, complexity)

        # Determine priority
        priority = self._determine_priority(complexity)

        result = AnalysisResult(
            timestamp=datetime.now().isoformat(),
            project_name=self.config.project_name,
            total_files=len(files),
            languages_detected=languages,
            complexity_score=complexity,
            modernization_priority=priority,
            recommendations=recommendations,
            detailed_findings={
                "target_path": str(target),
                "files_analyzed": [str(f) for f in files[:10]],  # Sample
                "excluded_patterns": self.config.analyzer.exclude_patterns,
            },
        )

        self.logger.info("Analysis complete")
        return result

    def _discover_files(self, target: Path) -> List[Path]:
        """Discover relevant files in the target directory."""
        files = []
        if target.is_file():
            return [target]

        for pattern in self.config.analyzer.include_patterns:
            if pattern == "*":
                # Get all files recursively
                for file in target.rglob("*"):
                    if file.is_file() and self._should_include_file(file):
                        files.append(file)
            else:
                files.extend([f for f in target.rglob(pattern) if self._should_include_file(f)])

        return list(set(files))  # Remove duplicates

    def _should_include_file(self, file: Path) -> bool:
        """Check if file should be included in analysis."""
        # Check file size
        try:
            if file.stat().st_size > self.config.analyzer.max_file_size:
                return False
        except OSError:
            return False

        # Check exclude patterns
        file_str = str(file)
        for pattern in self.config.analyzer.exclude_patterns:
            pattern_clean = pattern.replace("*", "")
            if pattern_clean in file_str:
                return False

        return True

    def _detect_languages(self, files: List[Path]) -> List[str]:
        """Detect programming languages from file extensions."""
        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".c": "c",
            ".go": "go",
            ".rs": "rust",
            ".php": "php",
            ".rb": "ruby",
        }

        languages = set()
        for file in files:
            lang = language_map.get(file.suffix.lower())
            if lang and lang in self.config.analyzer.supported_languages:
                languages.add(lang)

        return sorted(list(languages))

    def _calculate_complexity(self, files: List[Path]) -> float:
        """Calculate overall complexity score."""
        # Simple heuristic based on file count and size
        if not files:
            return 0.0

        total_size = sum(f.stat().st_size for f in files if f.exists())
        avg_file_size = total_size / len(files) if files else 0

        # Normalize to 0-100 scale
        file_count_score = min(len(files) / 100, 1.0) * 50
        size_score = min(avg_file_size / 100000, 1.0) * 50

        return file_count_score + size_score

    def _generate_recommendations(self, languages: List[str], complexity: float) -> List[str]:
        """Generate modernization recommendations."""
        recommendations = []

        # Language-specific recommendations
        if "python" in languages:
            recommendations.append("Consider upgrading to Python 3.12 for latest features")
            recommendations.append("Use type hints for better code maintainability")

        if "javascript" in languages or "typescript" in languages:
            recommendations.append("Migrate to TypeScript for type safety")
            recommendations.append("Consider modern build tools (Vite, esbuild)")

        if "java" in languages:
            recommendations.append("Upgrade to Java 21 LTS for modern features")
            recommendations.append("Consider migration to Spring Boot 3.x")

        if "csharp" in languages:
            recommendations.append("Migrate to .NET 8 for improved performance")
            recommendations.append("Adopt minimal APIs for modern web services")

        # Complexity-based recommendations
        if complexity > 60:
            recommendations.append("High complexity detected - consider refactoring into smaller modules")
            recommendations.append("Implement comprehensive testing before modernization")

        # General recommendations
        recommendations.append("Establish CI/CD pipeline for automated testing")
        recommendations.append("Document architecture before major changes")
        recommendations.append("Use adapter pattern for external dependencies")

        return recommendations

    def _determine_priority(self, complexity: float) -> str:
        """Determine modernization priority based on complexity."""
        if complexity < 30:
            return "low"
        elif complexity < 60:
            return "medium"
        else:
            return "high"

    def generate_report(self, result: AnalysisResult) -> Path:
        """Generate analysis report."""
        report_path = (
            self.config.output.output_dir
            / f"{self.config.project_name}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )

        with open(report_path, "w") as f:
            f.write(f"# ALARMv3 Analysis Report\n\n")
            f.write(f"**Project:** {result.project_name}\n")
            f.write(f"**Timestamp:** {result.timestamp}\n\n")
            f.write(f"## Summary\n\n")
            f.write(f"- **Total Files Analyzed:** {result.total_files}\n")
            f.write(f"- **Languages Detected:** {', '.join(result.languages_detected)}\n")
            f.write(f"- **Complexity Score:** {result.complexity_score:.2f}/100\n")
            f.write(f"- **Modernization Priority:** {result.modernization_priority.upper()}\n\n")
            f.write(f"## Recommendations\n\n")
            for i, rec in enumerate(result.recommendations, 1):
                f.write(f"{i}. {rec}\n")
            f.write(f"\n## Next Steps\n\n")
            f.write("1. Review the recommendations above\n")
            f.write("2. Create a modernization plan\n")
            f.write("3. Set up testing infrastructure\n")
            f.write("4. Begin incremental refactoring\n")
            f.write("5. Monitor and validate changes\n")

        self.logger.info(f"Report generated: {report_path}")
        return report_path
