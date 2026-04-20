"""ALARMv3 CLI — wraps the same core engine as the MCP server.

Commands:
  alarmv3 analyze <source_path>   Full end-to-end analysis
  alarmv3 init-config             Initialize .alarmv3/config.yaml
  alarmv3 status                  Show current session state
  alarmv3 version                 Print version
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="alarmv3")
def cli():
    """ALARMv3 — Intelligent legacy code modernization assistant."""
    pass


@cli.command()
@click.argument("source_path", type=click.Path(exists=True))
@click.option("--workspace", default=".", show_default=True,
              help="Workspace root where .alarmv3/ will be created.")
@click.option("--workers", default=4, show_default=True,
              help="Number of parallel analysis workers.")
def analyze(source_path: str, workspace: str, workers: int):
    """Attach to SOURCE_PATH and run full analysis end-to-end."""
    from concurrent.futures import ThreadPoolExecutor

    from ..core.analysis import Analyzer
    from ..core.artifacts import ArtifactWriter
    from ..core.discovery import FileScanner
    from ..core.guardrails import GuardrailViolation, SessionState
    from ..core.session import SessionManager
    from ..core.synthesis import Synthesizer

    sm = SessionManager(Path(workspace))
    session = sm.get_or_create()

    console.print("\n[bold cyan]ALARMv3[/bold cyan] — Legacy Modernization Assistant")
    console.print(f"Source  : [dim]{Path(source_path).resolve()}[/dim]")
    console.print(f"Artifacts: [dim]{session.artifact_dir}[/dim]\n")

    try:
        # ── Step 1: Attach + confirm ──────────────────────────────────────
        if session.state == SessionState.UNATTACHED:
            session.set_source(Path(source_path).resolve())
            session.transition_to(SessionState.ATTACHED)
            session.transition_to(SessionState.READ_ONLY_CONFIRMED)
            console.print("[green]✓[/green] Attached — source is read-only (guardrails confirmed)")

        # ── Step 2: Map ───────────────────────────────────────────────────
        if session.state == SessionState.READ_ONLY_CONFIRMED:
            session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          console=console, transient=True) as prog:
                task = prog.add_task("Discovering files...")
                scanner = FileScanner(session.source_path, session)
                with ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="alarmv3-scan") as pool:
                    count = scanner.scan(pool, "mapping")
                prog.update(task, description=f"Discovered {count} files")
            console.print(f"[green]✓[/green] Discovered {count:,} files")

        # ── Step 3: Analyze ───────────────────────────────────────────────
        if session.state == SessionState.ANALYSIS_IN_PROGRESS:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          console=console, transient=True) as prog:
                task = prog.add_task("Parsing ASTs and building dependency graph...")
                analyzer = Analyzer(session)
                with ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="alarmv3-parse") as pool:
                    stats = analyzer.run(pool, "analysis")
                prog.update(task, description="Analysis complete")
            console.print(
                f"[green]✓[/green] Analyzed {stats['files_analyzed']:,} files, "
                f"{stats['symbols_extracted']:,} symbols extracted"
                + (f" ({stats['files_failed']} failed)" if stats.get("files_failed") else "")
            )

        # ── Step 4: Synthesize ────────────────────────────────────────────
        with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                      console=console, transient=True) as prog:
            task = prog.add_task("Generating recommendations (Claude)...")
            result = Synthesizer(session).run()
            session.transition_to(SessionState.ANALYSIS_COMPLETE)
        console.print(f"[green]✓[/green] Generated {result['recommendation_count']} recommendations")

        # ── Step 5: Write artifacts ───────────────────────────────────────
        paths = ArtifactWriter(session).write_all()
        console.print(f"[green]✓[/green] Artifacts written to [dim]{session.artifact_dir}[/dim]")

        # ── Summary table ─────────────────────────────────────────────────
        _print_recommendations(session)

        console.print(f"\nFull report: [dim]{paths['recommendations_md']}[/dim]")

    except GuardrailViolation as e:
        console.print(f"\n[red]Guardrail violation:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise


@cli.command("init-config")
@click.option("--workspace", default=".", show_default=True)
def init_config(workspace: str):
    """Initialize ALARMv3 configuration in the workspace."""
    import yaml

    alarm_dir = Path(workspace) / ".alarmv3"
    alarm_dir.mkdir(exist_ok=True)
    config_path = alarm_dir / "config.yaml"

    if config_path.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
        return

    config = {
        "version": "0.1.0",
        "max_workers": 4,
        "languages": [
            "python", "javascript", "typescript",
            "java", "csharp", "cpp", "vbnet",
        ],
        "exclude_dirs": [
            ".git", "node_modules", "__pycache__",
            "build", "dist", "bin", "obj",
        ],
        "llm": {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
        },
        "embedding": {
            "provider": "ollama",
            "model": "nomic-embed-text",
            "base_url": "http://localhost:11434",
        },
    }
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    console.print(f"[green]✓[/green] Config written to [dim]{config_path}[/dim]")


@cli.command()
@click.option("--workspace", default=".", show_default=True)
def status(workspace: str):
    """Show current session state."""
    from ..core.session import SessionManager

    sm = SessionManager(Path(workspace))
    session = sm.get()
    if not session:
        console.print("[yellow]No active session.[/yellow] Run `alarmv3 analyze` to begin.")
        return

    d = session.to_dict()
    console.print(f"Session : [dim]{d['session_id']}[/dim]")
    console.print(f"State   : [bold]{d['state']}[/bold]")
    console.print(f"Source  : [dim]{d['source_path'] or 'not set'}[/dim]")
    console.print(f"Artifacts: [dim]{d['artifact_dir']}[/dim]")


# ── Helpers ────────────────────────────────────────────────────────────────

def _print_recommendations(session) -> None:
    import sqlite3

    db_path = session.artifact_dir / "analysis.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT rank, severity, category, title, effort "
        "FROM recommendation WHERE session_id=? ORDER BY rank LIMIT 10",
        (session.session_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return

    table = Table(title="\nTop Recommendations", show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Severity", width=10)
    table.add_column("Category", width=14)
    table.add_column("Title")
    table.add_column("Effort", width=6)

    colors = {"critical": "red", "high": "orange3", "medium": "yellow", "low": "green"}
    for r in rows:
        c = colors.get(r["severity"], "white")
        table.add_row(
            str(r["rank"]),
            f"[{c}]{r['severity']}[/{c}]",
            r["category"],
            r["title"],
            r["effort"] or "-",
        )
    console.print(table)
