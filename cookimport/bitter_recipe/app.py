from __future__ import annotations

import os
from pathlib import Path

import typer

from cookimport.bitter_recipe.interactive import interactive_mode
from cookimport.bitter_recipe.settings import load_settings
from cookimport.bitter_recipe import workflows


app = typer.Typer(
    name="bitter-recipe",
    add_completion=False,
    invoke_without_command=True,
    help="Corpus-first Label Studio workflow for building reviewed row-gold.",
)


def _limit_from_env() -> int | None:
    raw = str(os.getenv("C4IMP_LIMIT") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED)
    raise typer.Exit(1)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Build reviewed cookbook row-gold through a small Label Studio loop."""
    if ctx.invoked_subcommand is None:
        interactive_mode(limit=_limit_from_env())


@app.command("prepare")
def prepare(
    path: Path = typer.Argument(..., help="Cookbook source file to prepare."),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Override the default Label Studio project name.",
    ),
    prelabel: bool = typer.Option(
        False,
        "--prelabel/--no-prelabel",
        help="Ask Codex for first-pass labels before upload.",
    ),
) -> None:
    """Prepare one cookbook for Label Studio and upload tasks."""
    settings = load_settings()
    try:
        result = workflows.prepare_book(
            source_path=path,
            settings=settings,
            project_name=project_name,
            prelabel=prelabel,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    typer.secho(
        f"Prepared {path.name} -> {result['project_name']}",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"Run root: {result['run_root']}")


@app.command("export")
def export(
    book: str | None = typer.Option(
        None,
        "--book",
        help="Bitter-recipe source slug to export.",
    ),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Label Studio project name to export when no book slug is supplied.",
    ),
) -> None:
    """Export reviewed Label Studio labels back into row-gold artifacts."""
    settings = load_settings()
    try:
        result = workflows.export_book(
            settings=settings,
            book=book,
            project_name=project_name,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    typer.secho(f"Export root: {result['export_root']}", fg=typer.colors.GREEN)


@app.command("status")
def status(
    refresh: bool = typer.Option(
        True,
        "--refresh/--no-refresh",
        help="Refresh the bitter-recipe ledger from local manifests before printing.",
    ),
) -> None:
    """Show the current corpus queue and local book statuses."""
    settings = load_settings()
    rows = workflows.status_rows(settings, refresh=refresh)
    if not rows:
        typer.echo("No bitter-recipe books found.")
        return
    typer.echo("status     book                         project")
    typer.echo("---------  ---------------------------  ------------------------------")
    for row in rows:
        typer.echo(
            f"{str(row.get('status') or ''):<9}  "
            f"{str(row.get('source_slug') or ''):<27}  "
            f"{str(row.get('project_name') or '')}"
        )


@app.command("mark-reviewed")
def mark_reviewed(
    book: str = typer.Argument(..., help="Bitter-recipe source slug to mark reviewed."),
) -> None:
    """Mark one book as manually reviewed."""
    settings = load_settings()
    try:
        workflows.mark_reviewed(book=book, settings=settings)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    typer.secho(f"Marked {book} reviewed.", fg=typer.colors.GREEN)
