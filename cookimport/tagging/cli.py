"""CLI commands for tag-catalog and tag-recipes."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

tag_catalog_app = typer.Typer(name="tag-catalog", help="Tag catalog management.")
tag_recipes_app = typer.Typer(name="tag-recipes", help="Auto-tag recipes.")


# ---------------------------------------------------------------------------
# tag-catalog commands
# ---------------------------------------------------------------------------

@tag_catalog_app.command("export")
def catalog_export(
    db_url: str = typer.Option(
        None, "--db-url", envvar="COOKIMPORT_DATABASE_URL",
        help="Postgres connection string.",
    ),
    out: Path = typer.Option(
        ..., "--out", help="Output path for tag_catalog.json.",
    ),
) -> None:
    """Export the tag catalog from the database to a JSON file."""
    from cookimport.tagging.catalog import load_catalog_from_db, export_catalog_to_json

    if not db_url:
        typer.secho("Error: --db-url or COOKIMPORT_DATABASE_URL required.", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        catalog = load_catalog_from_db(db_url)
    except Exception as exc:
        typer.secho(f"Error loading catalog from DB: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho(f"Loaded {catalog.category_count} categories, {catalog.tag_count} tags", fg=typer.colors.GREEN)
    fingerprint = export_catalog_to_json(catalog, out)
    typer.secho(f"Exported to {out} (fingerprint={fingerprint[:12]}...)", fg=typer.colors.CYAN)


# ---------------------------------------------------------------------------
# tag-recipes commands
# ---------------------------------------------------------------------------

@tag_recipes_app.command("debug-signals")
def debug_signals(
    draft: Optional[Path] = typer.Option(None, "--draft", help="Path to a single draft JSON."),
    db_url: Optional[str] = typer.Option(None, "--db-url", envvar="COOKIMPORT_DATABASE_URL"),
    recipe_id: Optional[str] = typer.Option(None, "--recipe-id", help="DB recipe UUID."),
) -> None:
    """Inspect the signal pack the tagger would see for a recipe."""
    from cookimport.tagging.signals import signals_from_draft_json

    if draft:
        signals = signals_from_draft_json(draft)
    elif db_url and recipe_id:
        from cookimport.tagging.db_read import fetch_recipe_bundle
        signals = fetch_recipe_bundle(db_url, recipe_id)
    else:
        typer.secho("Provide --draft or (--db-url + --recipe-id).", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Title: {signals.title}")
    typer.echo(f"Ingredients: {len(signals.ingredients)} lines")
    typer.echo(f"Instructions: {len(signals.instructions)} steps")
    typer.echo(f"Prep time: {signals.prep_time_minutes} min")
    typer.echo(f"Cook time: {signals.cook_time_minutes} min")
    typer.echo(f"Total time: {signals.total_time_minutes} min")
    typer.echo(f"Yield: {signals.yield_phrase}")
    typer.echo(f"Max oven temp: {signals.max_oven_temp_f} F")
    typer.echo(f"Attention: {signals.attention_level}")
    typer.echo(f"Cleanup: {signals.cleanup_level}")
    typer.echo(f"Spice level: {signals.spice_level}")


@tag_recipes_app.command("suggest")
def suggest(
    draft: Optional[Path] = typer.Option(None, "--draft", help="Path to a single draft JSON."),
    draft_dir: Optional[Path] = typer.Option(None, "--draft-dir", help="Folder of draft JSONs (recursive)."),
    catalog_json: Path = typer.Option(..., "--catalog-json", help="Path to tag_catalog.json."),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="Write *.tags.json files here."),
    explain: bool = typer.Option(False, "--explain", help="Show evidence for each suggestion."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process at most N recipes."),
    llm: bool = typer.Option(False, "--llm", help="Enable LLM second pass (disabled by default)."),
) -> None:
    """Suggest tags for staged draft recipes (deterministic + optional LLM)."""
    from cookimport.tagging.catalog import load_catalog_from_json, get_catalog_fingerprint_from_json
    from cookimport.tagging.engine import suggest_tags_deterministic
    from cookimport.tagging.signals import signals_from_draft_json
    from cookimport.tagging.render import (
        render_suggestions_text,
        serialize_suggestions_json,
        write_tags_json,
        write_run_report,
    )

    catalog = load_catalog_from_json(catalog_json)
    fingerprint = get_catalog_fingerprint_from_json(catalog_json)
    typer.secho(
        f"Catalog: {catalog.category_count} categories, {catalog.tag_count} tags (fp={fingerprint[:12]}...)",
        fg=typer.colors.CYAN,
    )

    # Collect draft files
    draft_files: list[Path] = []
    if draft:
        draft_files.append(draft)
    elif draft_dir:
        draft_files = sorted(draft_dir.rglob("*.json"))
    else:
        typer.secho("Provide --draft or --draft-dir.", fg=typer.colors.RED)
        raise typer.Exit(1)

    if limit:
        draft_files = draft_files[:limit]

    if not draft_files:
        typer.secho("No draft JSON files found.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    per_recipe: list[dict] = []
    for path in draft_files:
        try:
            signals = signals_from_draft_json(path)
        except Exception as exc:
            typer.secho(f"  Skip {path.name}: {exc}", fg=typer.colors.YELLOW)
            continue

        suggestions = suggest_tags_deterministic(catalog, signals)

        # Optional LLM second pass
        if llm:
            from cookimport.tagging.llm_second_pass import suggest_tags_with_llm
            from cookimport.tagging.policies import CATEGORY_POLICIES
            filled_cats = {s.category_key for s in suggestions}
            missing = [k for k in CATEGORY_POLICIES if k not in filled_cats]
            if missing:
                llm_suggestions = suggest_tags_with_llm(signals, catalog, missing, suggestions)
                if llm_suggestions:
                    suggestions.extend(llm_suggestions)
                    # Re-apply policies after merge
                    from cookimport.tagging.engine import _apply_policies
                    suggestions = _apply_policies(catalog, suggestions)

        text = render_suggestions_text(signals.title, suggestions, explain=explain)
        typer.echo(text)
        typer.echo("")

        if out_dir:
            tag_path = out_dir / path.with_suffix(".tags.json").name
            write_tags_json(tag_path, suggestions, title=signals.title, catalog_fingerprint=fingerprint)

        per_recipe.append(serialize_suggestions_json(
            suggestions, title=signals.title, catalog_fingerprint=fingerprint,
        ))

    # Write run report
    report_dir = out_dir or Path("data/output") / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H.%M.%S")
    report_path = report_dir / "tagging_report.json"
    write_run_report(report_path, len(per_recipe), per_recipe, catalog_fingerprint=fingerprint)
    typer.secho(f"\nProcessed {len(per_recipe)} recipes. Report: {report_path}", fg=typer.colors.GREEN)


@tag_recipes_app.command("apply")
def apply_tags(
    db_url: str = typer.Option(
        None, "--db-url", envvar="COOKIMPORT_DATABASE_URL",
        help="Postgres connection string.",
    ),
    recipe_id: Optional[str] = typer.Option(None, "--recipe-id", help="Single recipe UUID."),
    catalog_json: Path = typer.Option(..., "--catalog-json", help="Path to tag_catalog.json."),
    apply: bool = typer.Option(False, "--apply", help="Actually write tags (default is dry-run)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    explain: bool = typer.Option(False, "--explain", help="Show evidence for each suggestion."),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence", help="Override minimum confidence."),
    llm: bool = typer.Option(False, "--llm", help="Enable LLM second pass."),
    import_batch_id: Optional[str] = typer.Option(None, "--import-batch-id", help="Scope to import batch."),
    source: Optional[str] = typer.Option(None, "--source", help="Scope to source."),
    batch_limit: Optional[int] = typer.Option(None, "--limit", help="Max recipes in batch."),
) -> None:
    """Tag recipes in the database (dry-run by default)."""
    from cookimport.tagging.catalog import load_catalog_from_json, get_catalog_fingerprint_from_json
    from cookimport.tagging.db_read import fetch_recipe_bundle
    from cookimport.tagging.db_write import insert_tag_assignments, verify_tag_ids_exist
    from cookimport.tagging.engine import suggest_tags_deterministic
    from cookimport.tagging.render import render_suggestions_text

    if not db_url:
        typer.secho("Error: --db-url or COOKIMPORT_DATABASE_URL required.", fg=typer.colors.RED)
        raise typer.Exit(1)

    catalog = load_catalog_from_json(catalog_json)
    fingerprint = get_catalog_fingerprint_from_json(catalog_json)
    typer.secho(
        f"Catalog: {catalog.category_count} categories, {catalog.tag_count} tags (fp={fingerprint[:12]}...)",
        fg=typer.colors.CYAN,
    )

    # Collect recipe IDs
    recipe_ids: list[str] = []
    if recipe_id:
        recipe_ids.append(recipe_id)
    else:
        # Batch mode
        try:
            import psycopg
        except ImportError:
            typer.secho("psycopg required for DB access.", fg=typer.colors.RED)
            raise typer.Exit(1)

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM public.recipes
                    WHERE archived_at IS NULL
                      AND (import_batch_id = %(batch)s OR %(batch)s IS NULL)
                      AND (source = %(src)s OR %(src)s IS NULL)
                    ORDER BY created_at DESC
                    LIMIT %(lim)s
                    """,
                    {"batch": import_batch_id, "src": source, "lim": batch_limit or 100},
                )
                recipe_ids = [str(row[0]) for row in cur.fetchall()]

    if not recipe_ids:
        typer.secho("No recipes found.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    typer.secho(f"Processing {len(recipe_ids)} recipe(s)...", fg=typer.colors.CYAN)

    total_inserted = 0
    for rid in recipe_ids:
        try:
            signals = fetch_recipe_bundle(db_url, rid)
        except Exception as exc:
            typer.secho(f"  Skip {rid}: {exc}", fg=typer.colors.YELLOW)
            continue

        suggestions = suggest_tags_deterministic(catalog, signals)

        # Optional LLM
        if llm:
            from cookimport.tagging.llm_second_pass import suggest_tags_with_llm
            from cookimport.tagging.policies import CATEGORY_POLICIES
            filled_cats = {s.category_key for s in suggestions}
            missing = [k for k in CATEGORY_POLICIES if k not in filled_cats]
            if missing:
                llm_suggestions = suggest_tags_with_llm(signals, catalog, missing, suggestions)
                if llm_suggestions:
                    suggestions.extend(llm_suggestions)
                    from cookimport.tagging.engine import _apply_policies
                    suggestions = _apply_policies(catalog, suggestions)

        # Filter by min_confidence
        if min_confidence is not None:
            suggestions = [s for s in suggestions if s.confidence >= min_confidence]

        text = render_suggestions_text(signals.title, suggestions, explain=explain)
        typer.echo(text)

        if apply and suggestions:
            tag_ids = [catalog.get_tag_id(s.tag_key) for s in suggestions]
            tag_ids = [tid for tid in tag_ids if tid is not None]

            # Verify tag IDs exist in DB
            missing_ids = verify_tag_ids_exist(db_url, tag_ids)
            if missing_ids:
                typer.secho(
                    f"  ABORT: {len(missing_ids)} tag IDs not found in DB (catalog drift?). "
                    f"Missing: {missing_ids[:5]}",
                    fg=typer.colors.RED,
                )
                continue

            if not yes:
                confirm = typer.confirm(f"  Apply {len(tag_ids)} tags to {rid}?")
                if not confirm:
                    typer.echo("  Skipped.")
                    continue

            inserted = insert_tag_assignments(db_url, rid, tag_ids)
            total_inserted += inserted
            typer.secho(f"  Inserted {inserted} new assignments.", fg=typer.colors.GREEN)
        elif not apply:
            typer.secho("  (dry-run, use --apply to write)", fg=typer.colors.BRIGHT_BLACK)

        typer.echo("")

    if apply:
        typer.secho(f"Done. Total new assignments: {total_inserted}", fg=typer.colors.GREEN)
    else:
        typer.secho("Dry-run complete. Use --apply to write tags.", fg=typer.colors.CYAN)
