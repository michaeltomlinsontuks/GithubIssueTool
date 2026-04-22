"""CLI entry point — three subcommands: gather-config, generate-skill, create-issues."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def cmd_gather_config(args: argparse.Namespace) -> None:
    """Handle the gather-config subcommand."""
    from src.gather import gather_config
    gather_config(repo=args.repo, config_dir=args.config_dir)


def cmd_generate_skill(args: argparse.Namespace) -> None:
    """Handle the generate-skill subcommand."""
    from src.skill_generator import generate_skill
    generate_skill(config_dir=args.config_dir, output_path=args.output)


def cmd_create_issues(args: argparse.Namespace) -> None:
    """Handle the create-issues subcommand."""
    from src.config_loader import load_project_config
    from src.gh_executor import execute_issues
    from src.validator import validate_issues

    # Load input JSON
    input_path = Path(args.input)
    if not input_path.exists():
        console.print(f"[red]Error: Input file not found: {input_path}[/red]")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[red]Error: Invalid JSON: {e}[/red]")
            sys.exit(1)

    # Load config
    config_dir = Path(args.config_dir)
    try:
        config = load_project_config(config_dir)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        sys.exit(1)

    # Determine schema path
    schema_path = Path(args.schema) if args.schema else Path("schemas/issues_schema.json")

    # Validate
    console.print("\n[bold blue]Validating issues...[/bold blue]\n")
    result = validate_issues(
        data, config,
        schema_path=schema_path,
        check_duplicates=not args.skip_duplicate_check,
    )

    # Print validation errors
    if result.errors:
        console.print(f"[bold red]❌ Validation failed with {len(result.errors)} error(s):[/bold red]\n")
        for err in result.errors:
            path_str = " → ".join(err.path) if err.path else err.issue_id
            console.print(f"  [red]●[/red] [{path_str}] [bold]{err.field}[/bold]: {err.message}")
            if err.suggestion:
                console.print(f"    [dim]{err.suggestion}[/dim]")
        sys.exit(1)

    # Print warnings
    if result.warnings:
        console.print(f"[yellow]⚠️  {len(result.warnings)} warning(s):[/yellow]\n")
        for warn in result.warnings:
            path_str = " → ".join(warn.path) if warn.path else warn.issue_id
            console.print(f"  [yellow]●[/yellow] [{path_str}] {warn.field}: {warn.message}")
        console.print()

    console.print("[green]✅ Validation passed![/green]")

    # Execute
    exec_result = execute_issues(
        data, config,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    if exec_result.failed:
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ghissue",
        description="GitHub Issue Tool — AI-powered batch issue creation via gh CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── gather-config ─────────────────────────────────────────────────────
    gather_parser = subparsers.add_parser(
        "gather-config",
        help="Pull repo metadata from GitHub into YAML config files",
    )
    gather_parser.add_argument(
        "--repo", "-r",
        required=True,
        help="Repository in owner/repo format (e.g. michaeltomlinsontuks/UMTAS)",
    )
    gather_parser.add_argument(
        "--config-dir", "-c",
        default="./config",
        help="Config output directory (default: ./config)",
    )
    gather_parser.set_defaults(func=cmd_gather_config)

    # ── generate-skill ────────────────────────────────────────────────────
    skill_parser = subparsers.add_parser(
        "generate-skill",
        help="Generate an AI skill prompt from config files",
    )
    skill_parser.add_argument(
        "--config-dir", "-c",
        default="./config",
        help="Config directory (default: ./config)",
    )
    skill_parser.add_argument(
        "--output", "-o",
        default="skill/github_issues.md",
        help="Output path for the skill prompt (default: skill/github_issues.md)",
    )
    skill_parser.set_defaults(func=cmd_generate_skill)

    # ── create-issues ─────────────────────────────────────────────────────
    create_parser = subparsers.add_parser(
        "create-issues",
        help="Validate and create issues from AI-generated JSON",
    )
    create_parser.add_argument(
        "input",
        help="Path to the AI-generated JSON file",
    )
    create_parser.add_argument(
        "--config-dir", "-c",
        default="./config",
        help="Config directory (default: ./config)",
    )
    create_parser.add_argument(
        "--schema", "-s",
        default=None,
        help="Path to JSON Schema (default: schemas/issues_schema.json)",
    )
    create_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print gh commands without executing",
    )
    create_parser.add_argument(
        "--skip-duplicate-check",
        action="store_true",
        help="Skip duplicate title detection (faster but may create duplicates)",
    )
    create_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    create_parser.set_defaults(func=cmd_create_issues)

    # Parse and dispatch
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
