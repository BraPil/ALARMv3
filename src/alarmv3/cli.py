"""Command-line interface for ALARMv3."""

import click
from pathlib import Path
import sys
from typing import Optional

from alarmv3 import __version__
from alarmv3.config import Config
from alarmv3.core import ALARMv3Engine


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """ALARMv3 - Next Generation Code Intelligence Platform for Legacy Modernization."""
    pass


@cli.command()
@click.argument("target_path", type=click.Path(exists=True), required=True)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
@click.option(
    "--project-name",
    "-n",
    default="alarmv3_project",
    help="Project name for analysis",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="./alarmv3_output",
    help="Output directory for reports",
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Logging level",
)
def analyze(
    target_path: str,
    config: Optional[str],
    project_name: str,
    output: str,
    log_level: str,
) -> None:
    """Analyze a codebase for modernization opportunities."""
    click.echo(f"🔍 ALARMv3 v{__version__} - Starting Analysis")
    click.echo(f"Target: {target_path}")

    try:
        # Load or create configuration
        if config:
            cfg = Config.from_file(Path(config))
            click.echo(f"Loaded configuration from: {config}")
        else:
            cfg = Config(
                project_name=project_name,
                target_path=Path(target_path),
                log_level=log_level,
            )
            cfg.output.output_dir = Path(output)

        # Run analysis
        engine = ALARMv3Engine(cfg)
        result = engine.analyze()

        # Generate report
        report_path = engine.generate_report(result)

        # Display summary
        click.echo("\n✅ Analysis Complete!")
        click.echo(f"\n📊 Summary:")
        click.echo(f"  • Files analyzed: {result.total_files}")
        click.echo(f"  • Languages: {', '.join(result.languages_detected)}")
        click.echo(f"  • Complexity: {result.complexity_score:.1f}/100")
        click.echo(f"  • Priority: {result.modernization_priority.upper()}")
        click.echo(f"\n📄 Report: {report_path}")
        click.echo(f"\n💡 Top Recommendations:")
        for i, rec in enumerate(result.recommendations[:3], 1):
            click.echo(f"  {i}. {rec}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("output_path", type=click.Path(), default="alarmv3_config.yaml")
def init_config(output_path: str) -> None:
    """Generate a configuration file template."""
    click.echo(f"Creating configuration template: {output_path}")

    config = Config()
    config.to_file(Path(output_path))

    click.echo(f"✅ Configuration file created: {output_path}")
    click.echo("Edit this file to customize your analysis settings.")


@cli.command()
def info() -> None:
    """Display ALARMv3 information and capabilities."""
    click.echo(f"ALARMv3 v{__version__}")
    click.echo("\n🎯 Next Generation Code Intelligence Platform")
    click.echo("\nCapabilities:")
    click.echo("  • Multi-language code analysis")
    click.echo("  • Automated complexity assessment")
    click.echo("  • Modernization recommendations")
    click.echo("  • Risk-based prioritization")
    click.echo("  • Comprehensive reporting")
    click.echo("\nSupported Languages:")
    click.echo("  Python, JavaScript, TypeScript, Java, C#, C/C++, Go, Rust, PHP, Ruby")
    click.echo("\nEvolution:")
    click.echo("  • ALARMv1: C# AutoCAD/Oracle migration focus")
    click.echo("  • ALARMv2: Python RAG-based reverse engineering")
    click.echo("  • ALARMv3: Next-gen unified intelligence platform")


@cli.command()
@click.argument("target_path", type=click.Path(exists=True), required=True)
def quick_scan(target_path: str) -> None:
    """Perform a quick scan without generating full reports."""
    click.echo(f"⚡ Quick Scan: {target_path}")

    try:
        config = Config(
            target_path=Path(target_path),
            log_level="WARNING",
        )
        config.output.generate_reports = False

        engine = ALARMv3Engine(config)
        result = engine.analyze()

        click.echo(f"\n📊 Results:")
        click.echo(f"  Files: {result.total_files}")
        click.echo(f"  Languages: {', '.join(result.languages_detected) or 'None detected'}")
        click.echo(f"  Complexity: {result.complexity_score:.1f}/100")
        click.echo(f"  Priority: {result.modernization_priority.upper()}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
