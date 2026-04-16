from __future__ import annotations

from pathlib import Path

import questionary
import typer

from cookimport.bitter_recipe import adapters, workflows
from cookimport.bitter_recipe.paths import list_importable_sources, source_slug_for_path
from cookimport.bitter_recipe.prompts import (
    BACK_ACTION,
    menu_select,
    prompt_confirm,
    prompt_text,
)
from cookimport.bitter_recipe.settings import BitterRecipeSettings, load_settings, save_settings


def _print_status_rows(rows: list[dict[str, object]]) -> None:
    if not rows:
        typer.secho("No importable books found.", fg=typer.colors.YELLOW)
        return
    typer.echo("status     book                         project")
    typer.echo("---------  ---------------------------  ------------------------------")
    for row in rows:
        status = str(row.get("status") or "unstarted")
        slug = str(row.get("source_slug") or "")
        project_name = str(row.get("project_name") or "")
        typer.echo(f"{status:<9}  {slug:<27}  {project_name}")


def _select_book(settings: BitterRecipeSettings, *, limit: int | None = None) -> Path | None:
    sources = list_importable_sources(settings.input_root_path())
    if limit is not None:
        sources = sources[:limit]
    if not sources:
        typer.secho(
            f"No importable files found in {settings.input_root_path()}",
            fg=typer.colors.YELLOW,
        )
        return None
    choice = menu_select(
        "Choose a cookbook to prepare:",
        menu_help=(
            "Pick one importable source. Bitter-recipe uses that source to create or "
            "resume one Label Studio project and track the result in its own ledger."
        ),
        choices=[questionary.Choice(path.name, value=path) for path in sources],
    )
    if choice in {None, BACK_ACTION}:
        return None
    return Path(choice)


def _select_ledger_book(
    settings: BitterRecipeSettings,
    *,
    allowed_statuses: set[str] | None = None,
) -> str | None:
    rows = workflows.status_rows(settings)
    if allowed_statuses is not None:
        rows = [row for row in rows if str(row.get("status") or "") in allowed_statuses]
    if not rows:
        typer.secho("No matching bitter-recipe books found.", fg=typer.colors.YELLOW)
        return None
    choice = menu_select(
        "Choose a book:",
        choices=[
            questionary.Choice(
                f"{row['source_slug']} [{row['status']}]",
                value=str(row["source_slug"]),
            )
            for row in rows
        ],
    )
    if choice in {None, BACK_ACTION}:
        return None
    return str(choice)


def _settings_menu(settings: BitterRecipeSettings) -> BitterRecipeSettings:
    while True:
        choice = menu_select(
            "Bitter-recipe settings:",
            choices=[
                questionary.Choice(f"Input root: {settings.input_root}", value="input_root"),
                questionary.Choice(
                    f"Bitter-recipe root: {settings.bitter_recipe_root}",
                    value="bitter_recipe_root",
                ),
                questionary.Choice(
                    f"Label Studio URL: {settings.label_studio_url or '(env/blank)'}",
                    value="label_studio_url",
                ),
                questionary.Choice(
                    "Label Studio API key: "
                    + ("(saved)" if settings.label_studio_api_key else "(env/blank)"),
                    value="label_studio_api_key",
                ),
                questionary.Choice(
                    f"Segment blocks: {settings.segment_blocks}",
                    value="segment_blocks",
                ),
                questionary.Choice(
                    f"Segment overlap: {settings.segment_overlap}",
                    value="segment_overlap",
                ),
                questionary.Choice(
                    f"Segment focus blocks: {settings.segment_focus_blocks}",
                    value="segment_focus_blocks",
                ),
                questionary.Choice(
                    f"Default prelabel: {'on' if settings.default_prelabel else 'off'}",
                    value="default_prelabel",
                ),
                questionary.Choice(
                    f"Codex model: {settings.codex_model or '(pipeline default)'}",
                    value="codex_model",
                ),
                questionary.Choice(
                    "Codex reasoning: "
                    + (settings.codex_reasoning_effort or "(pipeline default)"),
                    value="codex_reasoning_effort",
                ),
                questionary.Choice("Verify Label Studio credentials now", value="verify"),
                questionary.Choice("Back", value="back"),
            ],
        )
        if choice in {None, BACK_ACTION, "back"}:
            save_settings(settings)
            return settings
        if choice == "input_root":
            value = prompt_text("Input root:", default=settings.input_root)
            if value is not None and value.strip():
                settings.input_root = value.strip()
        elif choice == "bitter_recipe_root":
            value = prompt_text(
                "Bitter-recipe root:",
                default=settings.bitter_recipe_root,
            )
            if value is not None and value.strip():
                settings.bitter_recipe_root = value.strip()
        elif choice == "label_studio_url":
            value = prompt_text(
                "Label Studio URL:",
                default=settings.label_studio_url,
            )
            if value is not None:
                settings.label_studio_url = value.strip()
        elif choice == "label_studio_api_key":
            value = prompt_text(
                "Label Studio API key:",
                default=settings.label_studio_api_key,
                password=True,
            )
            if value is not None:
                settings.label_studio_api_key = value.strip()
        elif choice == "segment_blocks":
            value = prompt_text(
                "Segment blocks:",
                default=str(settings.segment_blocks),
            )
            if value and value.strip().isdigit():
                settings.segment_blocks = max(1, int(value.strip()))
                settings.segment_focus_blocks = min(
                    settings.segment_focus_blocks,
                    settings.segment_blocks,
                )
        elif choice == "segment_overlap":
            value = prompt_text(
                "Segment overlap:",
                default=str(settings.segment_overlap),
            )
            if value and value.strip().isdigit():
                settings.segment_overlap = max(0, int(value.strip()))
        elif choice == "segment_focus_blocks":
            value = prompt_text(
                "Segment focus blocks:",
                default=str(settings.segment_focus_blocks),
            )
            if value and value.strip().isdigit():
                settings.segment_focus_blocks = min(
                    settings.segment_blocks,
                    max(1, int(value.strip())),
                )
        elif choice == "default_prelabel":
            toggled = prompt_confirm(
                "Use Codex prelabel by default?",
                default=settings.default_prelabel,
            )
            if toggled is not None:
                settings.default_prelabel = toggled
        elif choice == "codex_model":
            value = prompt_text(
                "Codex model override (blank = pipeline default):",
                default=settings.codex_model,
            )
            if value is not None:
                settings.codex_model = value.strip()
        elif choice == "codex_reasoning_effort":
            value = prompt_text(
                "Codex reasoning effort (blank = pipeline default):",
                default=settings.codex_reasoning_effort,
            )
            if value is not None:
                settings.codex_reasoning_effort = value.strip()
        elif choice == "verify":
            try:
                adapters.preflight_labelstudio_credentials(settings)
            except Exception as exc:  # noqa: BLE001
                typer.secho(f"Credential check failed: {exc}", fg=typer.colors.RED)
            else:
                typer.secho("Credential check passed.", fg=typer.colors.GREEN)


def interactive_mode(*, limit: int | None = None) -> None:
    typer.secho("\n  Bitter Recipe Corpus Builder\n", fg=typer.colors.CYAN, bold=True)
    settings = load_settings()
    while True:
        action = menu_select(
            "What would you like to do?",
            menu_help=(
                "This lane is for building reviewed row-gold quickly. It reuses "
                "source-row extraction plus Label Studio import/export, and skips the "
                "heavy stage/benchmark machinery."
            ),
            choices=[
                questionary.Choice("Start or resume a book", value="prepare"),
                questionary.Choice("Export reviewed labels", value="export"),
                questionary.Choice("Queue status", value="status"),
                questionary.Choice("Mark a book reviewed", value="mark_reviewed"),
                questionary.Choice("Settings", value="settings"),
                questionary.Choice("Exit", value="exit"),
            ],
        )
        if action in {None, "exit"}:
            raise typer.Exit(0)
        if action == "status":
            _print_status_rows(workflows.status_rows(settings))
            continue
        if action == "settings":
            settings = _settings_menu(settings)
            continue
        if action == "prepare":
            selected_path = _select_book(settings, limit=limit)
            if selected_path is None:
                continue
            default_project = adapters.default_project_name(selected_path, settings)
            project_name = prompt_text(
                "Label Studio project name:",
                default=default_project,
            )
            if project_name is None:
                continue
            prelabel_choice = prompt_confirm(
                "Use Codex prelabel for this book?",
                default=settings.default_prelabel,
            )
            if prelabel_choice is None:
                continue
            try:
                result = workflows.prepare_book(
                    source_path=selected_path,
                    settings=settings,
                    project_name=project_name.strip() or default_project,
                    prelabel=prelabel_choice,
                )
            except Exception as exc:  # noqa: BLE001
                typer.secho(f"Prepare failed: {exc}", fg=typer.colors.RED)
            else:
                typer.secho(
                    f"Prepared {selected_path.name} -> {result['project_name']}",
                    fg=typer.colors.GREEN,
                )
            continue
        if action == "export":
            selected_slug = _select_ledger_book(
                settings,
                allowed_statuses={"uploaded", "exported", "reviewed", "failed"},
            )
            if selected_slug is None:
                continue
            try:
                result = workflows.export_book(settings=settings, book=selected_slug)
            except Exception as exc:  # noqa: BLE001
                typer.secho(f"Export failed: {exc}", fg=typer.colors.RED)
            else:
                typer.secho(
                    f"Exported row gold to {result['export_root']}",
                    fg=typer.colors.GREEN,
                )
            continue
        if action == "mark_reviewed":
            selected_slug = _select_ledger_book(
                settings,
                allowed_statuses={"exported", "reviewed", "uploaded"},
            )
            if selected_slug is None:
                continue
            try:
                workflows.mark_reviewed(book=selected_slug, settings=settings)
            except Exception as exc:  # noqa: BLE001
                typer.secho(f"Could not mark reviewed: {exc}", fg=typer.colors.RED)
            else:
                typer.secho(f"Marked {selected_slug} reviewed.", fg=typer.colors.GREEN)
