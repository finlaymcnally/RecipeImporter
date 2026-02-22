from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import multiprocessing
import os
import queue
import re
import shutil
import threading
import time
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Dict, Any, Annotated, Callable

import questionary
import typer
from prompt_toolkit.keys import Keys
from questionary.prompts.common import Choice as QuestionaryChoice, Separator as QuestionarySeparator
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.text import Text

from cookimport.cli_ui.run_settings_flow import choose_run_settings
from cookimport.config.last_run_store import save_last_run_settings
from cookimport.config.run_settings import RunSettings, build_run_settings, compute_effective_workers
from cookimport.core.mapping_io import load_mapping_config, save_mapping_config
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import format_phase_counter
from cookimport.core.overrides_io import load_parsing_overrides
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.slug import slugify_name
from cookimport.core.timing import TimingStats, measure
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.ingest import (
    generate_pred_run_artifacts,
    run_labelstudio_decorate,
    run_labelstudio_import,
)
from cookimport.labelstudio.eval_canonical import (
    evaluate_structural_vs_gold,
    format_eval_report_md,
    load_gold_spans,
    load_predicted_spans,
    write_jsonl,
)
from cookimport.labelstudio.eval_freeform import (
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)
from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.labelstudio.prelabel import default_codex_model
from cookimport.plugins import registry
from cookimport.plugins import excel, text, epub, pdf, recipesage, paprika  # noqa: F401
from cookimport.runs import RunManifest, RunSource, write_run_manifest
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
from cookimport.parsing.epub_auto_select import (
    selected_auto_score,
    select_epub_extractor_auto,
    write_auto_extractor_artifact,
)
from cookimport.parsing.tips import partition_tip_candidates
from cookimport.staging.pdf_jobs import (
    plan_job_ranges,
    plan_pdf_page_ranges,
    reassign_recipe_ids,
)
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_report,
    write_tip_outputs,
    write_topic_candidate_outputs,
)

app = typer.Typer(add_completion=False, invoke_without_command=True)
bench_app = typer.Typer(name="bench", help="Offline benchmark suite tools.")
app.add_typer(bench_app)

from cookimport.tagging.cli import tag_catalog_app, tag_recipes_app  # noqa: E402
from cookimport.epubdebug.cli import epub_app, race_epub_extractors  # noqa: E402
app.add_typer(tag_catalog_app)
app.add_typer(tag_recipes_app)
app.add_typer(epub_app, name="epub")
console = Console()
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "input"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "output"
DEFAULT_INTERACTIVE_OUTPUT = DEFAULT_OUTPUT
DEFAULT_EPUB_RACE_OUTPUT_ROOT = DEFAULT_OUTPUT / "EPUBextractorRace"
DEFAULT_GOLDEN = Path(__file__).parent.parent / "data" / "golden"
DEFAULT_BENCH_SUITES = DEFAULT_GOLDEN / "bench" / "suites"
DEFAULT_BENCH_RUNS = DEFAULT_GOLDEN / "bench" / "runs"
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "cookimport.json"
REPO_ROOT = Path(__file__).parent.parent
BACK_ACTION = "__back__"
SUPPORTED_LABELSTUDIO_TASK_SCOPES = {"pipeline", "canonical-blocks", "freeform-spans"}
_MENU_SHORTCUT_KEYS = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
)


def _menu_option_count(choices: list[Any]) -> int:
    return sum(
        1
        for raw_choice in choices
        if not isinstance(QuestionaryChoice.build(raw_choice), QuestionarySeparator)
    )


def _menu_shortcut_bindings(choices: list[Any]) -> dict[str, Any]:
    selectable_choices: list[QuestionaryChoice] = []
    for raw_choice in choices:
        built_choice = QuestionaryChoice.build(raw_choice)
        if isinstance(built_choice, QuestionarySeparator) or built_choice.disabled:
            continue
        selectable_choices.append(built_choice)

    available_shortcuts = list(_MENU_SHORTCUT_KEYS)
    bindings: dict[str, Any] = {}

    # Respect explicit shortcuts first.
    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str) and shortcut_key:
            if shortcut_key in available_shortcuts:
                available_shortcuts.remove(shortcut_key)
            bindings[shortcut_key] = built_choice.value

    # Mirror Questionary's auto-assignment order for remaining choices.
    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str):
            continue
        if shortcut_key is False:
            continue
        if not available_shortcuts:
            break
        assigned = available_shortcuts.pop(0)
        bindings[assigned] = built_choice.value

    return bindings


def _menu_select(
    message: str,
    *,
    choices: list[Any],
    menu_help: str | None = None,
    **kwargs: Any,
) -> Any:
    """Select helper with Backspace support for one-level menu back navigation."""
    option_count = _menu_option_count(choices)
    use_shortcuts = option_count <= len(_MENU_SHORTCUT_KEYS)
    shortcut_bindings = _menu_shortcut_bindings(choices) if use_shortcuts else {}
    if menu_help:
        typer.secho(menu_help, fg=typer.colors.BRIGHT_BLACK)
    question = questionary.select(
        message,
        choices=choices,
        instruction=(
            "(Type number shortcut to select, Enter to select, Backspace to go back)"
            if use_shortcuts
            else "(Enter to select, Backspace to go back)"
        ),
        use_shortcuts=use_shortcuts,
        **kwargs,
    )

    @question.application.key_bindings.add(Keys.Backspace, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=BACK_ACTION)

    if use_shortcuts:
        for key, value in shortcut_bindings.items():
            if key not in "0123456789":
                continue

            def _register_numeric_shortcut(shortcut: str, selected_value: Any) -> None:
                @question.application.key_bindings.add(shortcut, eager=True)
                def _select_by_shortcut(event: Any) -> None:
                    event.app.exit(result=selected_value)

            _register_numeric_shortcut(key, value)

    return question.ask()


def _load_settings() -> Dict[str, Any]:
    """Load user settings from config file."""
    defaults = {
        "workers": 7,
        "pdf_split_workers": 7,
        "epub_split_workers": 7,
        "epub_extractor": "unstructured",
        "epub_unstructured_html_parser_version": "v1",
        "epub_unstructured_skip_headers_footers": False,
        "epub_unstructured_preprocess_mode": "br_split_v1",
        "ocr_device": "auto",
        "ocr_batch_size": 1,
        "pdf_pages_per_job": 50,
        "epub_spine_items_per_job": 10,
        "warm_models": False,
        "output_dir": str(DEFAULT_INTERACTIVE_OUTPUT),
    }
    if not DEFAULT_CONFIG_PATH.exists():
        return defaults
    try:
        with open(DEFAULT_CONFIG_PATH, "r") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                return {**defaults, **loaded}
            return defaults
    except Exception:
        return defaults


def _save_settings(settings: Dict[str, Any]) -> None:
    """Save user settings to config file."""
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def _resolve_interactive_labelstudio_settings(
    settings: Dict[str, Any],
) -> tuple[str, str]:
    """Resolve Label Studio creds for interactive flows, persisting prompted values."""
    env_url = os.getenv("LABEL_STUDIO_URL")
    env_api_key = os.getenv("LABEL_STUDIO_API_KEY")
    stored_url = str(settings.get("label_studio_url", "") or "").strip()
    stored_api_key = str(settings.get("label_studio_api_key", "") or "").strip()

    label_studio_url = env_url or stored_url
    label_studio_api_key = env_api_key or stored_api_key

    if not label_studio_url:
        label_studio_url = questionary.text(
            "Label Studio URL:",
            default=stored_url or "http://localhost:8080",
        ).ask()
    if not label_studio_api_key:
        label_studio_api_key = questionary.password(
            "Label Studio API key:",
        ).ask()

    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

    changed = False
    if not env_url and url != stored_url:
        settings["label_studio_url"] = url
        changed = True
    if not env_api_key and api_key != stored_api_key:
        settings["label_studio_api_key"] = api_key
        changed = True
    if changed:
        _save_settings(settings)

    if not env_url and not env_api_key:
        preflight_error = _preflight_labelstudio_credentials(url, api_key)
        if preflight_error and _is_labelstudio_credential_error(preflight_error):
            typer.secho(
                "Saved Label Studio credentials were rejected. Please enter updated values.",
                fg=typer.colors.YELLOW,
            )
            refreshed_url = questionary.text(
                "Label Studio URL:",
                default=url,
            ).ask()
            refreshed_api_key = questionary.password(
                "Label Studio API key:",
            ).ask()
            url, api_key = _resolve_labelstudio_settings(refreshed_url, refreshed_api_key)
            settings["label_studio_url"] = url
            settings["label_studio_api_key"] = api_key
            _save_settings(settings)
            retry_error = _preflight_labelstudio_credentials(url, api_key)
            if retry_error and _is_labelstudio_credential_error(retry_error):
                _fail(f"Updated Label Studio credentials were rejected: {retry_error}")

    return url, api_key


def _preflight_labelstudio_credentials(url: str, api_key: str) -> str | None:
    """Best-effort interactive credential probe; returns error text on failure."""
    try:
        client = LabelStudioClient(url, api_key)
        client.list_projects()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def _is_labelstudio_credential_error(error_text: str) -> bool:
    normalized = error_text.lower()
    return (
        "api error 401" in normalized
        or "api error 403" in normalized
        or "api error 404" in normalized
    )


def _list_importable_files(folder: Path) -> list[Path]:
    """List files in a folder that have a valid importer."""
    if not folder.exists():
        return []
    files = []
    for f in folder.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            _, score = registry.best_importer_for_path(f)
            if score > 0:
                files.append(f)
    return sorted(files)


def _settings_menu(current_settings: Dict[str, Any]) -> None:
    """Run the settings configuration menu."""
    while True:
        # Refresh values in display
        choice = _menu_select(
            "Settings Configuration",
            menu_help=(
                "Tune defaults used by stage/benchmark jobs. "
                "These settings are saved to cookimport.json."
            ),
            choices=[
                questionary.Choice(
                    f"Workers: {current_settings.get('workers', 4)} - max parallel file jobs",
                    value="workers",
                ),
                questionary.Choice(
                    f"PDF Split Workers: {current_settings.get('pdf_split_workers', 7)} - max PDF shard jobs",
                    value="pdf_split_workers",
                ),
                questionary.Choice(
                    f"EPUB Split Workers: {current_settings.get('epub_split_workers', 7)} - max EPUB shard jobs",
                    value="epub_split_workers",
                ),
                questionary.Choice(
                    f"EPUB Extractor: {current_settings.get('epub_extractor', 'unstructured')} - unstructured/legacy/markdown/auto/markitdown",
                    value="epub_extractor",
                ),
                questionary.Choice(
                    (
                        "Unstructured HTML Parser: "
                        f"{current_settings.get('epub_unstructured_html_parser_version', 'v1')} - v1/v2"
                    ),
                    value="epub_unstructured_html_parser_version",
                ),
                questionary.Choice(
                    (
                        "Unstructured Skip Headers/Footers: "
                        f"{'Yes' if current_settings.get('epub_unstructured_skip_headers_footers', False) else 'No'}"
                    ),
                    value="epub_unstructured_skip_headers_footers",
                ),
                questionary.Choice(
                    (
                        "Unstructured EPUB Preprocess: "
                        f"{current_settings.get('epub_unstructured_preprocess_mode', 'br_split_v1')} - none/br_split_v1/semantic_v1"
                    ),
                    value="epub_unstructured_preprocess_mode",
                ),
                questionary.Choice(
                    f"OCR Device: {current_settings.get('ocr_device', 'auto')} - auto/cpu/cuda/mps",
                    value="ocr_device",
                ),
                questionary.Choice(
                    f"OCR Batch Size: {current_settings.get('ocr_batch_size', 1)} - pages per OCR call",
                    value="ocr_batch_size",
                ),
                questionary.Choice(
                    f"Output Folder: {current_settings.get('output_dir', str(DEFAULT_INTERACTIVE_OUTPUT))} - stage artifacts",
                    value="output_dir",
                ),
                questionary.Choice(
                    f"PDF Pages/Job: {current_settings.get('pdf_pages_per_job', 50)} - split size per PDF task",
                    value="pdf_pages_per_job",
                ),
                questionary.Choice(
                    f"EPUB Spine Items/Job: {current_settings.get('epub_spine_items_per_job', 10)} - split size per EPUB task",
                    value="epub_spine_items_per_job",
                ),
                questionary.Choice(
                    f"Warm Models: {'Yes' if current_settings.get('warm_models', False) else 'No'} - preload heavy models",
                    value="warm_models",
                ),
                questionary.Separator(),
                questionary.Choice("Back to Main Menu - return without changing anything", value="back"),
            ]
        )
        
        if choice in {"back", BACK_ACTION} or choice is None:
            break
            
        if choice == "workers":
            val = questionary.text("Enter number of workers:", default=str(current_settings.get("workers", 7))).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "pdf_split_workers":
            val = questionary.text(
                "Enter PDF split workers:",
                default=str(current_settings.get("pdf_split_workers", 7)),
            ).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_split_workers":
            val = questionary.text(
                "Enter EPUB split workers:",
                default=str(current_settings.get("epub_split_workers", 7)),
            ).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_extractor":
            val = _menu_select(
                "Select EPUB extraction engine:",
                choices=["unstructured", "legacy", "markdown", "auto", "markitdown"],
                default=current_settings.get("epub_extractor", "unstructured"),
                menu_help=(
                    "Unstructured uses semantic HTML partitioning for richer block extraction. "
                    "Legacy uses BeautifulSoup tag-based parsing. Markdown converts spine HTML into markdown first. "
                    "Auto scores sample spine docs and chooses the best backend for each EPUB. "
                    "MarkItDown is retained as legacy whole-book markdown mode."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_extractor"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_html_parser_version":
            val = _menu_select(
                "Select Unstructured HTML parser version:",
                choices=["v1", "v2"],
                default=current_settings.get(
                    "epub_unstructured_html_parser_version",
                    "v1",
                ),
                menu_help=(
                    "Choose Unstructured partition_html parser version for EPUB extraction."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_html_parser_version"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_skip_headers_footers":
            val = questionary.confirm(
                "Skip headers/footers in Unstructured HTML partitioning?",
                default=bool(
                    current_settings.get(
                        "epub_unstructured_skip_headers_footers",
                        False,
                    )
                ),
            ).ask()
            if val is not None:
                current_settings["epub_unstructured_skip_headers_footers"] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_unstructured_preprocess_mode":
            val = _menu_select(
                "Select EPUB HTML preprocess mode before Unstructured:",
                choices=["none", "br_split_v1", "semantic_v1"],
                default=current_settings.get(
                    "epub_unstructured_preprocess_mode",
                    "br_split_v1",
                ),
                menu_help=(
                    "none keeps raw HTML; br_split_v1 splits BR-separated paragraphs "
                    "into block tags; semantic_v1 currently aliases br_split_v1."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_preprocess_mode"] = val
                _save_settings(current_settings)

        elif choice == "ocr_device":
            val = _menu_select(
                "Select OCR Device:",
                choices=["auto", "cpu", "cuda", "mps"],
                default=current_settings.get("ocr_device", "auto"),
                menu_help="Choose OCR hardware. Use auto unless you need to force a device.",
            )
            if val and val != BACK_ACTION:
                current_settings["ocr_device"] = val
                _save_settings(current_settings)
                
        elif choice == "ocr_batch_size":
            val = questionary.text("Enter OCR batch size:", default=str(current_settings.get("ocr_batch_size", 1))).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["ocr_batch_size"] = int(val)
                _save_settings(current_settings)

        elif choice == "output_dir":
            val = questionary.text(
                "Enter output folder for interactive runs:",
                default=str(current_settings.get("output_dir", str(DEFAULT_INTERACTIVE_OUTPUT))),
            ).ask()
            if val:
                current_settings["output_dir"] = str(Path(val).expanduser())
                _save_settings(current_settings)

        elif choice == "pdf_pages_per_job":
            val = questionary.text(
                "Enter PDF pages per job:",
                default=str(current_settings.get("pdf_pages_per_job", 50)),
            ).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_pages_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_spine_items_per_job":
            val = questionary.text(
                "Enter EPUB spine items per job:",
                default=str(current_settings.get("epub_spine_items_per_job", 10)),
            ).ask()
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_spine_items_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "warm_models":
            val = questionary.confirm("Warm models on start?", default=current_settings.get("warm_models", False)).ask()
            if val is not None:
                current_settings["warm_models"] = val
                _save_settings(current_settings)


def _interactive_epub_race(epub_files: list[Path]) -> None:
    """Run the one-file EPUB extractor race flow from interactive mode."""
    if not epub_files:
        typer.secho("No EPUB files found in data/input.", fg=typer.colors.YELLOW)
        return

    selected_epub = _menu_select(
        "Select an EPUB file for extractor race:",
        choices=[questionary.Choice(path.name, value=path) for path in epub_files],
        menu_help=(
            "Runs the same deterministic auto-selection scorer used by "
            "--epub-extractor auto and writes epub_race_report.json."
        ),
    )
    if selected_epub in {None, BACK_ACTION}:
        return

    default_out = DEFAULT_EPUB_RACE_OUTPUT_ROOT / selected_epub.stem
    out_raw = questionary.text(
        "Race output folder:",
        default=str(default_out),
    ).ask()
    if out_raw is None:
        return
    out_dir = Path(out_raw.strip() or str(default_out)).expanduser()

    force = False
    if out_dir.exists() and out_dir.is_dir() and any(out_dir.iterdir()):
        overwrite = questionary.confirm(
            "Output folder is not empty. Continue with overwrite behavior?",
            default=False,
        ).ask()
        if overwrite is None or not overwrite:
            typer.secho("EPUB race cancelled.", fg=typer.colors.YELLOW)
            return
        force = True

    candidates_raw = questionary.text(
        "Candidate extractors (comma-separated):",
        default="unstructured,markdown,legacy",
    ).ask()
    if candidates_raw is None:
        return
    candidates = candidates_raw.strip() or "unstructured,markdown,legacy"

    try:
        race_epub_extractors(
            path=selected_epub,
            out=out_dir,
            candidates=candidates,
            json_output=False,
            force=force,
        )
    except typer.Exit as exc:
        if int(exc.exit_code or 0) != 0:
            typer.secho("EPUB race failed. See error above.", fg=typer.colors.YELLOW)


def _interactive_mode(*, limit: int | None = None) -> None:
    """Run the interactive guided flow."""
    typer.secho("\n  Recipe Import Tool\n", fg=typer.colors.CYAN, bold=True)

    input_folder = DEFAULT_INPUT
    settings = _load_settings()

    while True:
        output_folder = Path(str(settings.get("output_dir") or DEFAULT_INTERACTIVE_OUTPUT)).expanduser()
        # Scan for importable files first to know what context to show
        importable_files = _list_importable_files(input_folder)
        epub_files = [path for path in importable_files if path.suffix.lower() == ".epub"]

        choices = []
        if importable_files:
            choices.append(
                questionary.Choice(
                    "Stage files from data/input - produce cookbook outputs",
                    value="import",
                )
            )
            choices.append(
                questionary.Choice(
                    "Label Studio: create labeling tasks (uploads)",
                    value="labelstudio",
                )
            )
        if epub_files:
            choices.append(
                questionary.Choice(
                    "EPUB debug: race extractors on one file",
                    value="epub_race",
                )
            )
        choices.append(
            questionary.Choice(
                "Label Studio: export completed labels to golden artifacts",
                value="labelstudio_export",
            )
        )
        choices.append(
            questionary.Choice(
                "Label Studio: decorate existing freeform project with AI spans",
                value="labelstudio_decorate",
            )
        )
        choices.append(
            questionary.Choice(
                "Evaluate predictions vs freeform gold (re-score or generate)",
                value="labelstudio_benchmark",
            )
        )
        choices.append(
            questionary.Choice(
                "Generate dashboard - build lifetime stats dashboard HTML",
                value="generate_dashboard",
            )
        )
        choices.append(
            questionary.Choice(
                "Settings - tune worker/OCR/output defaults",
                value="settings",
            )
        )
        choices.append(questionary.Choice("Exit - close the tool", value="exit"))

        action = _menu_select(
            "What would you like to do?",
            choices=choices,
            menu_help=(
                "Choose a workflow. Stage produces cookbook outputs, Label Studio task "
                "creation uploads annotation tasks, export pulls completed labels, "
                "EPUB race runs a one-file extractor comparison, "
                "decorate adds new AI spans to existing freeform projects, "
                "and evaluate compares predictions against gold. "
                "Dashboard builds a static lifetime summary."
            ),
        )

        if action == BACK_ACTION:
            continue

        if action is None or action == "exit":
            raise typer.Exit(0)

        if action == "generate_dashboard":
            open_dashboard = questionary.confirm(
                "Open dashboard in your browser after generation?",
                default=True,
            ).ask()
            if open_dashboard is None:
                continue
            typer.secho(
                f"Generating dashboard from {output_folder}...",
                fg=typer.colors.CYAN,
            )
            stats_dashboard(
                output_root=output_folder,
                golden_root=DEFAULT_GOLDEN,
                out_dir=output_folder / ".history" / "dashboard",
                open_browser=bool(open_dashboard),
                since_days=None,
                scan_reports=False,
            )
            continue

        if action == "epub_race":
            _interactive_epub_race(epub_files)
            continue

        if action == "settings":
            _settings_menu(settings)
            continue

        elif action == "import":
            if not importable_files:
                # Should be unreachable given the check above, but safe to keep
                typer.secho(
                    f"\nNo supported files found in {input_folder}",
                    fg=typer.colors.YELLOW,
                )
                input("Press Enter to continue...")
                continue

            typer.secho(f"\nFound {len(importable_files)} importable file(s) in {input_folder}", fg=typer.colors.GREEN)

            selection = _menu_select(
                "Which file(s) would you like to import?",
                menu_help=(
                    "Import All processes every supported file in data/input. "
                    "Choosing one file runs conversion only for that file."
                ),
                choices=[
                    questionary.Choice("Import All - process every supported file", value="all"),
                    *[questionary.Choice(f.name, value=f) for f in importable_files]
                ]
            )

            if selection in {None, BACK_ACTION}:
                continue

            typer.echo()

            global_run_settings = RunSettings.model_validate(settings)
            selected_run_settings = choose_run_settings(
                kind="import",
                global_defaults=global_run_settings,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
            )
            if selected_run_settings is None:
                typer.secho("Import cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                "Run settings: "
                f"{selected_run_settings.summary()} "
                f"(hash {selected_run_settings.short_hash()})",
                fg=typer.colors.CYAN,
            )

            # Apply EPUB settings via env vars (read at call time by epub.py).
            os.environ["C3IMP_EPUB_EXTRACTOR"] = selected_run_settings.epub_extractor.value
            _set_epub_unstructured_env(
                html_parser_version=selected_run_settings.epub_unstructured_html_parser_version.value,
                skip_headers_footers=selected_run_settings.epub_unstructured_skip_headers_footers,
                preprocess_mode=selected_run_settings.epub_unstructured_preprocess_mode.value,
            )

            common_args = {
                "out": output_folder,
                "mapping": None,
                "overrides": None,
                "limit": limit,
                "workers": selected_run_settings.workers,
                "pdf_split_workers": selected_run_settings.pdf_split_workers,
                "epub_split_workers": selected_run_settings.epub_split_workers,
                "epub_extractor": selected_run_settings.epub_extractor.value,
                "epub_unstructured_html_parser_version": (
                    selected_run_settings.epub_unstructured_html_parser_version.value
                ),
                "epub_unstructured_skip_headers_footers": (
                    selected_run_settings.epub_unstructured_skip_headers_footers
                ),
                "epub_unstructured_preprocess_mode": (
                    selected_run_settings.epub_unstructured_preprocess_mode.value
                ),
                "ocr_device": selected_run_settings.ocr_device.value,
                "ocr_batch_size": selected_run_settings.ocr_batch_size,
                "pdf_pages_per_job": selected_run_settings.pdf_pages_per_job,
                "epub_spine_items_per_job": selected_run_settings.epub_spine_items_per_job,
                "warm_models": selected_run_settings.warm_models,
            }

            if selection == "all":
                run_folder = stage(path=input_folder, **common_args)
            else:
                run_folder = stage(path=selection, **common_args)

            save_last_run_settings("import", output_folder, selected_run_settings)
            typer.secho(f"\nOutputs written to: {run_folder}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio":
            if not importable_files:
                typer.secho(
                    f"\nNo supported files found in {input_folder}",
                    fg=typer.colors.YELLOW,
                )
                input("Press Enter to continue...")
                continue

            file_choices = [
                questionary.Choice(f.name, value=f) for f in importable_files
            ]
            selected_file = _menu_select(
                "Select a file to import into Label Studio:",
                choices=file_choices,
                menu_help="Pick the source file to turn into Label Studio tasks.",
            )

            if selected_file in {None, BACK_ACTION}:
                continue

            project_name = questionary.text(
                "Project name (leave blank to auto-name):",
                default="",
            ).ask()
            if project_name is not None:
                project_name = project_name.strip() or None

            task_scope = _menu_select(
                "Task scope:",
                menu_help=(
                    "Scope controls labeling style. Pipeline labels chunk outputs, canonical "
                    "labels every block, and freeform labels arbitrary spans."
                ),
                choices=[
                    questionary.Choice(
                        "pipeline chunks - label structural/atomic pipeline chunks",
                        value="pipeline",
                    ),
                    questionary.Choice(
                        "canonical blocks - one label per extracted block",
                        value="canonical-blocks",
                    ),
                    questionary.Choice(
                        "freeform spans - highlight arbitrary text spans",
                        value="freeform-spans",
                    ),
                ],
            )

            if task_scope in {None, BACK_ACTION}:
                continue

            chunk_level = "both"
            context_window = 1
            segment_blocks = 40
            segment_overlap = 5
            prelabel = False
            prelabel_provider = "codex-cli"
            prelabel_timeout_seconds = 120
            prelabel_cache_dir: Path | None = None
            prelabel_upload_as = "annotations"
            prelabel_allow_partial = False
            codex_model: str | None = None
            prelabel_track_token_usage = True

            if task_scope == "pipeline":
                chunk_level = _menu_select(
                    "Chunk level:",
                    menu_help=(
                        "Choose which pipeline chunk types to upload for annotation."
                    ),
                    choices=[
                        questionary.Choice(
                            "both - include structural recipe chunks and atomic line chunks",
                            value="both",
                        ),
                        questionary.Choice(
                            "structural only - recipe-level chunk boundaries",
                            value="structural",
                        ),
                        questionary.Choice(
                            "atomic only - line-level ingredient/instruction chunks",
                            value="atomic",
                        ),
                    ],
                )
                if chunk_level in {None, BACK_ACTION}:
                    continue
            elif task_scope == "canonical-blocks":
                context_window_raw = questionary.text(
                    "Canonical context window (blocks):",
                    default="1",
                ).ask()
                if context_window_raw is None:
                    continue
                try:
                    context_window = max(0, int(context_window_raw.strip()))
                except ValueError:
                    typer.secho("Context window must be an integer >= 0.", fg=typer.colors.RED)
                    continue
            elif task_scope == "freeform-spans":
                segment_blocks_raw = questionary.text(
                    "Freeform segment size (blocks per task):",
                    default="40",
                ).ask()
                if segment_blocks_raw is None:
                    continue
                segment_overlap_raw = questionary.text(
                    "Freeform overlap (blocks):",
                    default="5",
                ).ask()
                if segment_overlap_raw is None:
                    continue
                try:
                    segment_blocks = int(segment_blocks_raw.strip())
                    segment_overlap = int(segment_overlap_raw.strip())
                except ValueError:
                    typer.secho("Segment settings must be integers.", fg=typer.colors.RED)
                    continue
                if segment_blocks < 1:
                    typer.secho("Segment size must be >= 1.", fg=typer.colors.RED)
                    continue
                if segment_overlap < 0:
                    typer.secho("Segment overlap must be >= 0.", fg=typer.colors.RED)
                    continue
                prelabel_mode = _menu_select(
                    "AI prelabel mode before upload:",
                    menu_help=(
                        "Choose strict vs allow-partial behavior for AI prelabels. "
                        "Predictions mode is an advanced/debug option."
                    ),
                    choices=[
                        questionary.Choice(
                            "off - upload tasks without AI prelabels",
                            value=(False, "annotations", False),
                        ),
                        questionary.Choice(
                            "strict annotations - fail upload if any prelabel task fails",
                            value=(True, "annotations", False),
                        ),
                        questionary.Choice(
                            "allow-partial annotations - continue upload and record failures",
                            value=(True, "annotations", True),
                        ),
                        questionary.Choice(
                            "strict predictions (advanced) - upload AI output as predictions",
                            value=(True, "predictions", False),
                        ),
                        questionary.Choice(
                            "allow-partial predictions (advanced) - predictions + partial failures",
                            value=(True, "predictions", True),
                        ),
                    ],
                )
                if prelabel_mode in {None, BACK_ACTION}:
                    continue
                prelabel, prelabel_upload_as, prelabel_allow_partial = prelabel_mode
                if prelabel:
                    detected_model = default_codex_model()
                    detected_label = detected_model or "Codex CLI default"
                    model_choice = _menu_select(
                        "Codex model for AI prelabeling:",
                        menu_help=(
                            "Pick a model explicitly for this run, or leave it on the "
                            "Codex CLI default."
                        ),
                        choices=[
                            questionary.Choice(
                                f"use Codex default ({detected_label})",
                                value="__default__",
                            ),
                            questionary.Choice("gpt-5.3-codex", value="gpt-5.3-codex"),
                            questionary.Choice("custom model id...", value="__custom__"),
                        ],
                    )
                    if model_choice in {None, BACK_ACTION}:
                        continue
                    if model_choice == "__custom__":
                        custom_default = detected_model or ""
                        custom_model = questionary.text(
                            "Codex model id:",
                            default=custom_default,
                        ).ask()
                        if custom_model is None:
                            continue
                        codex_model = custom_model.strip() or None
                    elif model_choice == "__default__":
                        codex_model = None
                    else:
                        codex_model = str(model_choice)

            # Interactive flow always recreates the project if it exists.
            overwrite = True

            url, api_key = _resolve_interactive_labelstudio_settings(settings)

            try:
                result = _run_labelstudio_import_with_status(
                    source_name=selected_file.name,
                    run_import=lambda update_progress: run_labelstudio_import(
                        path=selected_file,
                        output_dir=DEFAULT_GOLDEN,
                        pipeline="auto",
                        project_name=project_name,
                        chunk_level=chunk_level,
                        task_scope=task_scope,
                        context_window=context_window,
                        segment_blocks=segment_blocks,
                        segment_overlap=segment_overlap,
                        overwrite=overwrite,
                        resume=False,
                        label_studio_url=url,
                        label_studio_api_key=api_key,
                        limit=None,
                        sample=None,
                        progress_callback=update_progress,
                        prelabel=prelabel,
                        prelabel_provider=prelabel_provider,
                        codex_cmd=None,
                        codex_model=codex_model,
                        prelabel_timeout_seconds=prelabel_timeout_seconds,
                        prelabel_cache_dir=prelabel_cache_dir,
                        prelabel_upload_as=prelabel_upload_as,
                        prelabel_allow_partial=prelabel_allow_partial,
                        prelabel_track_token_usage=prelabel_track_token_usage,
                        allow_labelstudio_write=True,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))

            typer.secho(
                f"Label Studio project: {result['project_name']} (id={result['project_id']})",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                f"Tasks created: {result['tasks_total']} (uploaded {result['tasks_uploaded']})",
                fg=typer.colors.CYAN,
            )
            if prelabel:
                report_path = result.get("prelabel_report_path")
                prelabel_summary = result.get("prelabel") or {}
                usage_payload: Any = None
                usage_enabled = prelabel_track_token_usage
                if isinstance(prelabel_summary, dict):
                    model_label = prelabel_summary.get("codex_model")
                    if model_label:
                        typer.secho(
                            f"Prelabel model: {model_label}",
                            fg=typer.colors.CYAN,
                        )
                    usage_payload = prelabel_summary.get("token_usage")
                    usage_enabled = bool(
                        prelabel_summary.get(
                            "token_usage_enabled",
                            prelabel_track_token_usage,
                        )
                    )
                _print_token_usage_summary(
                    prefix="Prelabel token usage",
                    usage=usage_payload,
                    enabled=usage_enabled,
                )
                if report_path:
                    typer.secho(
                        f"Prelabel report: {report_path}",
                        fg=typer.colors.CYAN,
                    )
            typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio_export":
            target_output_dir = DEFAULT_GOLDEN

            url, api_key = _resolve_interactive_labelstudio_settings(settings)
            project_name, detected_scope = _select_export_project(
                label_studio_url=url,
                label_studio_api_key=api_key,
            )
            if not project_name:
                continue
            if detected_scope in SUPPORTED_LABELSTUDIO_TASK_SCOPES:
                export_scope = detected_scope
                typer.secho(
                    f"Using detected project type: {export_scope}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            else:
                export_scope = _menu_select(
                    "Export scope:",
                    menu_help="Choose the task type used by the project you already labeled.",
                    choices=[
                        questionary.Choice(
                            "pipeline chunks - chunk-level labels",
                            value="pipeline",
                        ),
                        questionary.Choice(
                            "canonical blocks - block-level labels and derived spans",
                            value="canonical-blocks",
                        ),
                        questionary.Choice(
                            "freeform spans - offset-based highlighted spans",
                            value="freeform-spans",
                        ),
                    ],
                )
                if export_scope in {None, BACK_ACTION}:
                    continue

            try:
                result = run_labelstudio_export(
                    project_name=project_name,
                    output_dir=target_output_dir,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    run_dir=None,
                    export_scope=export_scope,
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))

            typer.secho(
                f"Export complete. Summary: {result['summary_path']}",
                fg=typer.colors.GREEN,
            )
            continue

        elif action == "labelstudio_decorate":
            url, api_key = _resolve_interactive_labelstudio_settings(settings)
            project_name, detected_scope = _select_export_project(
                label_studio_url=url,
                label_studio_api_key=api_key,
            )
            if not project_name:
                continue
            if detected_scope and detected_scope != "freeform-spans":
                typer.secho(
                    (
                        f"Selected project type looks like `{detected_scope}`. "
                        "Decorate currently supports freeform-spans."
                    ),
                    fg=typer.colors.YELLOW,
                )
                proceed_anyway = questionary.confirm(
                    "Try decorating this project as freeform-spans anyway?",
                    default=False,
                ).ask()
                if proceed_anyway is not True:
                    continue

            label_choices = [
                questionary.Choice(
                    label,
                    value=label,
                    checked=label in {"YIELD_LINE", "TIME_LINE"},
                )
                for label in FREEFORM_LABELS
            ]
            selected_labels = questionary.checkbox(
                "Select label types to add:",
                choices=label_choices,
                validate=lambda selected: bool(selected) or "Pick at least one label.",
            ).ask()
            if selected_labels is None:
                continue
            add_labels = {str(label) for label in selected_labels}
            if not add_labels:
                typer.secho("Pick at least one label.", fg=typer.colors.RED)
                continue

            no_write = questionary.confirm(
                "Dry run only? (recommended first)",
                default=True,
            ).ask()
            if no_write is None:
                continue
            no_write = bool(no_write)
            if not no_write:
                confirmed_write = questionary.confirm(
                    "Create new annotations in Label Studio now?",
                    default=False,
                ).ask()
                if confirmed_write is not True:
                    typer.secho("Decorate cancelled.", fg=typer.colors.YELLOW)
                    continue

            try:
                result = run_labelstudio_decorate(
                    project_name=project_name,
                    output_dir=DEFAULT_GOLDEN,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    add_labels=add_labels,
                    task_scope="freeform-spans",
                    prelabel_provider="codex-cli",
                    codex_cmd=None,
                    prelabel_timeout_seconds=120,
                    prelabel_cache_dir=None,
                    allow_labelstudio_write=not no_write,
                    no_write=no_write,
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))

            counts = result["report"]["counts"]
            typer.secho(
                f"Decorate complete ({'dry-run' if no_write else 'write'} mode).",
                fg=typer.colors.GREEN,
            )
            typer.secho(f"Tasks scanned: {counts['tasks_total']}", fg=typer.colors.CYAN)
            if no_write:
                typer.secho(
                    f"Would create annotations: {counts['dry_run_would_create']}",
                    fg=typer.colors.CYAN,
                )
            else:
                typer.secho(
                    f"Annotations created: {counts['created']}",
                    fg=typer.colors.CYAN,
                )
            if counts["failed"]:
                typer.secho(f"Failures: {counts['failed']}", fg=typer.colors.YELLOW)
            typer.secho(f"Report: {result['report_path']}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio_benchmark":
            benchmark_eval_output = (
                DEFAULT_GOLDEN
                / "eval-vs-pipeline"
                / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
            )
            gold_candidates = _discover_freeform_gold_exports(DEFAULT_GOLDEN)
            prediction_runs = _discover_prediction_runs(DEFAULT_GOLDEN)
            benchmark_mode = "upload"
            if gold_candidates and prediction_runs:
                selected_mode = _menu_select(
                    "How would you like to evaluate?",
                    menu_help=(
                        "Use eval-only to re-score an existing prediction run "
                        "(for updated gold/settings). "
                        "Use upload only when you need to generate fresh predictions."
                    ),
                    choices=[
                        questionary.Choice(
                            "Evaluate existing prediction run (no upload)",
                            value="eval-only",
                        ),
                        questionary.Choice(
                            "Generate predictions + evaluate (uploads to Label Studio)",
                            value="upload",
                        ),
                    ],
                )
                if selected_mode in {None, BACK_ACTION}:
                    continue
                benchmark_mode = str(selected_mode)

            if benchmark_mode == "eval-only":
                selected_gold = _menu_select(
                    "Select a freeform gold export:",
                    menu_help="Choose the labeled freeform export to score against.",
                    choices=[
                        questionary.Choice(
                            _display_gold_export_path(path, DEFAULT_GOLDEN),
                            value=path,
                        )
                        for path in gold_candidates[:30]
                    ],
                )
                if selected_gold in {None, BACK_ACTION}:
                    typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                    continue

                selected_pred_run = _menu_select(
                    "Select a prediction run:",
                    menu_help=(
                        "Choose the existing prediction task run to compare against the selected gold export."
                    ),
                    choices=[
                        questionary.Choice(
                            _display_prediction_run_path(path, DEFAULT_GOLDEN),
                            value=path,
                        )
                        for path in prediction_runs[:30]
                    ],
                )
                if selected_pred_run in {None, BACK_ACTION}:
                    typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                    continue

                typer.secho(
                    "Eval-only mode: no pipeline run settings applied.",
                    fg=typer.colors.BRIGHT_BLACK,
                )
                labelstudio_eval(
                    scope="freeform-spans",
                    pred_run=Path(selected_pred_run),
                    gold_spans=Path(selected_gold),
                    output_dir=benchmark_eval_output,
                )
                continue

            benchmark_defaults = RunSettings.model_validate(settings)
            selected_benchmark_settings = choose_run_settings(
                kind="benchmark",
                global_defaults=benchmark_defaults,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
            )
            if selected_benchmark_settings is None:
                typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                "Run settings: "
                f"{selected_benchmark_settings.summary()} "
                f"(hash {selected_benchmark_settings.short_hash()})",
                fg=typer.colors.CYAN,
            )

            url, api_key = _resolve_interactive_labelstudio_settings(settings)
            labelstudio_benchmark(
                output_dir=DEFAULT_GOLDEN,
                eval_output_dir=benchmark_eval_output,
                allow_labelstudio_write=True,
                label_studio_url=url,
                label_studio_api_key=api_key,
                epub_extractor=selected_benchmark_settings.epub_extractor.value,
                epub_unstructured_html_parser_version=(
                    selected_benchmark_settings.epub_unstructured_html_parser_version.value
                ),
                epub_unstructured_skip_headers_footers=(
                    selected_benchmark_settings.epub_unstructured_skip_headers_footers
                ),
                epub_unstructured_preprocess_mode=(
                    selected_benchmark_settings.epub_unstructured_preprocess_mode.value
                ),
                ocr_device=selected_benchmark_settings.ocr_device.value,
                ocr_batch_size=selected_benchmark_settings.ocr_batch_size,
                warm_models=selected_benchmark_settings.warm_models,
                workers=selected_benchmark_settings.workers,
                pdf_split_workers=selected_benchmark_settings.pdf_split_workers,
                epub_split_workers=selected_benchmark_settings.epub_split_workers,
                pdf_pages_per_job=selected_benchmark_settings.pdf_pages_per_job,
                epub_spine_items_per_job=selected_benchmark_settings.epub_spine_items_per_job,
            )
            save_last_run_settings("benchmark", output_folder, selected_benchmark_settings)
            continue


@app.callback()
def main(ctx: typer.Context) -> None:
    """Recipe Import - Convert source files to schema.org Recipe JSON and cookbook3 outputs."""
    if ctx.invoked_subcommand is None:
        limit_value = os.getenv("C3IMP_LIMIT")
        limit = None
        if limit_value:
            try:
                limit = int(limit_value)
            except ValueError:
                limit = None
        _interactive_mode(limit=limit)


def _fail(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _format_token_usage_line(prefix: str, usage: dict[str, Any]) -> str:
    return (
        f"{prefix}: "
        f"input={usage.get('input_tokens', 0)} "
        f"cached_input={usage.get('cached_input_tokens', 0)} "
        f"output={usage.get('output_tokens', 0)} "
        f"calls_with_usage={usage.get('calls_with_usage', 0)}"
    )


def _print_token_usage_summary(
    *,
    prefix: str,
    usage: Any,
    enabled: bool,
) -> None:
    if not enabled:
        return
    if isinstance(usage, dict):
        typer.secho(
            _format_token_usage_line(prefix, usage),
            fg=typer.colors.CYAN,
        )
        return
    typer.secho(
        f"{prefix}: unavailable (Codex did not emit usage totals)",
        fg=typer.colors.YELLOW,
    )


def _normalize_epub_extractor(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"unstructured", "legacy", "markdown", "auto", "markitdown"}:
        _fail(
            f"Invalid EPUB extractor: {value!r}. "
            "Expected one of: unstructured, legacy, markdown, auto, markitdown."
        )
    return normalized


def _normalize_unstructured_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        _fail(
            f"Invalid EPUB Unstructured HTML parser version: {value!r}. "
            "Expected one of: v1, v2."
        )
    return normalized


def _normalize_unstructured_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1", "semantic_v1"}:
        _fail(
            f"Invalid EPUB Unstructured preprocess mode: {value!r}. "
            "Expected one of: none, br_split_v1, semantic_v1."
        )
    return normalized


def _normalize_ocr_device(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "cpu", "cuda", "mps"}:
        _fail(
            f"Invalid OCR device: {value!r}. "
            "Expected one of: auto, cpu, cuda, mps."
        )
    return normalized


def _parse_csv_labels(value: str) -> set[str]:
    labels = {item.strip().upper() for item in value.split(",") if item.strip()}
    if not labels:
        _fail("At least one label is required (example: YIELD_LINE,TIME_LINE).")
    return labels


@contextmanager
def _temporary_epub_extractor(value: str) -> Iterable[None]:
    previous = os.environ.get("C3IMP_EPUB_EXTRACTOR")
    os.environ["C3IMP_EPUB_EXTRACTOR"] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("C3IMP_EPUB_EXTRACTOR", None)
        else:
            os.environ["C3IMP_EPUB_EXTRACTOR"] = previous


def _set_epub_unstructured_env(
    *,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> None:
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode


@contextmanager
def _temporary_epub_unstructured_options(
    *,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    previous_parser = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION")
    previous_skip = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
    previous_preprocess = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE")
    _set_epub_unstructured_env(
        html_parser_version=html_parser_version,
        skip_headers_footers=skip_headers_footers,
        preprocess_mode=preprocess_mode,
    )
    try:
        yield
    finally:
        if previous_parser is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = previous_parser
        if previous_skip is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = previous_skip
        if previous_preprocess is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = previous_preprocess


def _warm_all_models(ocr_device: str = "auto") -> None:
    """Proactively load heavy models into memory."""
    from cookimport.ocr.doctr_engine import warm_ocr_model
    from cookimport.parsing.spacy_support import warm_spacy_model
    from cookimport.parsing.ingredients import warm_ingredient_parser

    # Warm SpaCy
    warm_spacy_model()
    # Warm Ingredient Parser
    warm_ingredient_parser()
    # Warm OCR
    try:
        warm_ocr_model(device=ocr_device)
    except Exception as e:
        logger.warning(f"Failed to warm OCR model: {e}")


def _resolve_labelstudio_settings(
    label_studio_url: str | None,
    label_studio_api_key: str | None,
) -> tuple[str, str]:
    url = label_studio_url or os.getenv("LABEL_STUDIO_URL")
    api_key = label_studio_api_key or os.getenv("LABEL_STUDIO_API_KEY")
    if not url:
        _fail("Label Studio URL missing. Use --label-studio-url or LABEL_STUDIO_URL.")
    if not api_key:
        _fail("Label Studio API key missing. Use --label-studio-api-key or LABEL_STUDIO_API_KEY.")
    return url, api_key


def _prompt_manual_project_name() -> str | None:
    project_name_raw = questionary.text(
        "Label Studio project name to export:",
        default="",
    ).ask()
    if project_name_raw is None:
        return None
    project_name = project_name_raw.strip()
    if not project_name:
        typer.secho("Project name is required for export.", fg=typer.colors.RED)
        return None
    return project_name


def _discover_manifest_project_scopes(*roots: Path) -> dict[str, str]:
    """Best-effort map of project title -> task scope from local manifest history."""
    latest_by_project: dict[str, tuple[float, str]] = {}
    for root in roots:
        if not root.exists():
            continue
        for manifest_path in root.glob("**/labelstudio/**/manifest.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            project_name = str(payload.get("project_name", "")).strip()
            task_scope = str(payload.get("task_scope", "")).strip()
            if not project_name or not task_scope:
                continue
            try:
                mtime = manifest_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            previous = latest_by_project.get(project_name)
            if previous is None or mtime >= previous[0]:
                latest_by_project[project_name] = (mtime, task_scope)
    return {project_name: scope for project_name, (_mtime, scope) in latest_by_project.items()}


def _infer_scope_from_project_payload(project: dict[str, Any]) -> str | None:
    """Infer task scope from Label Studio project payload when available."""
    explicit_scope = str(project.get("task_scope", "")).strip()
    if explicit_scope in SUPPORTED_LABELSTUDIO_TASK_SCOPES:
        return explicit_scope

    label_config = str(project.get("label_config", "") or "")
    if not label_config:
        return None

    if any(
        marker in label_config
        for marker in (
            "YIELD_LINE",
            "TIME_LINE",
            "RECIPE_NOTES",
            "RECIPE_VARIANT",
            "KNOWLEDGE",
            # Backward compatibility with older freeform projects.
            "NOTES",
            "VARIANT",
        )
    ):
        return "freeform-spans"
    if (
        "RECIPE_TITLE" in label_config
        and "INGREDIENT_LINE" in label_config
        and "INSTRUCTION_LINE" in label_config
        and "NARRATIVE" in label_config
        and "VARIANT" not in label_config
        and "RECIPE_VARIANT" not in label_config
    ):
        return "canonical-blocks"
    if "mixed" in label_config and "value_usefulness" in label_config:
        return "pipeline"
    return None


def _select_export_project(
    *,
    label_studio_url: str,
    label_studio_api_key: str,
) -> tuple[str | None, str | None]:
    try:
        client = LabelStudioClient(label_studio_url, label_studio_api_key)
        projects = client.list_projects()
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Could not fetch Label Studio projects ({exc}). Falling back to manual entry.",
            fg=typer.colors.YELLOW,
        )
        return _prompt_manual_project_name(), None

    known_scopes = _discover_manifest_project_scopes(DEFAULT_GOLDEN, DEFAULT_OUTPUT)
    scope_by_title: dict[str, str | None] = {}
    for project in projects:
        if not isinstance(project, dict):
            continue
        title = str(project.get("title", "")).strip()
        if not title:
            continue
        scope_by_title[title] = known_scopes.get(title) or _infer_scope_from_project_payload(project)

    project_titles = sorted(scope_by_title.keys(), key=str.casefold)

    if not project_titles:
        typer.secho(
            "No Label Studio projects found. Enter a project name manually.",
            fg=typer.colors.YELLOW,
        )
        return _prompt_manual_project_name(), None

    selection = _menu_select(
        "Select Label Studio project to export:",
        menu_help="Choose an existing project title (with detected type), or switch to manual entry.",
        choices=[
            questionary.Choice("Type project name manually", value="__manual__"),
            *[
                questionary.Choice(
                    f"{title} [type: {scope_by_title.get(title) or 'unknown'}]",
                    value=title,
                )
                for title in project_titles
            ],
        ],
    )
    if selection in {None, BACK_ACTION}:
        return None, None
    if selection == "__manual__":
        return _prompt_manual_project_name(), None
    selected_project = str(selection)
    return selected_project, scope_by_title.get(selected_project)


def _select_export_project_name(
    *,
    label_studio_url: str,
    label_studio_api_key: str,
) -> str | None:
    project_name, _detected_scope = _select_export_project(
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    return project_name


def _require_labelstudio_write_consent(allow_labelstudio_write: bool) -> None:
    if not allow_labelstudio_write:
        _fail(
            "Label Studio uploads are blocked by default. "
            "Re-run with --allow-labelstudio-write to push tasks."
        )


def _run_labelstudio_import_with_status(
    *,
    source_name: str,
    run_import: Callable[[Callable[[str], None]], dict[str, Any]],
) -> dict[str, Any]:
    with console.status(
        f"[bold cyan]Running Label Studio import for {source_name}...[/bold cyan]",
        spinner="dots",
    ) as status:

        def update_progress(msg: str) -> None:
            status.update(
                f"[bold cyan]Label Studio import ({source_name}): {msg}[/bold cyan]"
            )

        return run_import(update_progress)


def _discover_freeform_gold_exports(output_dir: Path) -> list[Path]:
    roots: list[Path] = [output_dir]
    if DEFAULT_OUTPUT not in roots:
        roots.append(DEFAULT_OUTPUT)
    if DEFAULT_GOLDEN not in roots:
        roots.append(DEFAULT_GOLDEN)

    seen: set[Path] = set()
    exports: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/exports/freeform_span_labels.jsonl"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            exports.append(path)

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except Exception:  # noqa: BLE001
            mtime = 0.0
        return (mtime, str(path))

    exports.sort(key=_sort_key, reverse=True)
    return exports


def _discover_prediction_runs(output_dir: Path) -> list[Path]:
    roots: list[Path] = [output_dir]
    if DEFAULT_OUTPUT not in roots:
        roots.append(DEFAULT_OUTPUT)
    if DEFAULT_GOLDEN not in roots:
        roots.append(DEFAULT_GOLDEN)

    seen: set[Path] = set()
    runs: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for marker in root.glob("**/label_studio_tasks.jsonl"):
            run_dir = marker.parent
            if not run_dir.exists() or not run_dir.is_dir():
                continue
            resolved = run_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            runs.append(run_dir)

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = (path / "label_studio_tasks.jsonl").stat().st_mtime
        except Exception:  # noqa: BLE001
            mtime = 0.0
        return (mtime, str(path))

    runs.sort(key=_sort_key, reverse=True)
    return runs


def _infer_source_file_from_freeform_gold(gold_spans: Path) -> Path | None:
    run_root = gold_spans.parent.parent
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            manifest = None
        if isinstance(manifest, dict):
            source_file = manifest.get("source_file")
            if source_file:
                candidate = Path(str(source_file))
                if candidate.exists() and candidate.is_file():
                    return candidate

    try:
        first_line = next(
            line for line in gold_spans.read_text(encoding="utf-8").splitlines() if line.strip()
        )
        payload = json.loads(first_line)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    source_file = payload.get("source_file")
    if not source_file:
        return None
    source_name = Path(str(source_file)).name
    input_candidate = DEFAULT_INPUT / source_name
    if input_candidate.exists() and input_candidate.is_file():
        return input_candidate
    return None


def _co_locate_prediction_run_for_benchmark(pred_run: Path, eval_output_dir: Path) -> Path:
    """Move benchmark prediction artifacts under the eval run directory."""
    if not pred_run.exists() or not pred_run.is_dir():
        _fail(f"Prediction run directory not found: {pred_run}")
    original_parent = pred_run.parent
    stop_exclusive = pred_run.parents[2] if len(pred_run.parents) > 2 else None
    target = eval_output_dir / "prediction-run"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pred_run), str(target))
    _prune_empty_dirs(original_parent, stop_exclusive=stop_exclusive)
    return target


def _load_total_recipes_from_report_path(
    report_path_value: Path | str | None,
) -> int | None:
    if report_path_value is None:
        return None
    report_path = Path(report_path_value)
    if not report_path.exists() or not report_path.is_file():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    total_recipes = payload.get("totalRecipes")
    try:
        return int(total_recipes)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PredRunContext:
    recipes: int | None
    processed_report_path: str
    source_file: str
    source_hash: str | None
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None
    epub_auto_selected_score: float | None


def _load_pred_run_recipe_context(
    pred_run: Path,
) -> PredRunContext:
    """Return recipe/report/source/run-config context for a prediction run."""
    manifest_path = pred_run / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            epub_auto_selected_score=None,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            epub_auto_selected_score=None,
        )
    if not isinstance(payload, dict):
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            epub_auto_selected_score=None,
        )

    source_file = str(payload.get("source_file") or "")
    source_hash = str(payload.get("source_hash") or "").strip() or None
    processed_report_path = str(payload.get("processed_report_path") or "")
    run_config = payload.get("run_config")
    if not isinstance(run_config, dict):
        run_config = None
    run_config_hash = str(payload.get("run_config_hash") or "").strip() or None
    run_config_summary = str(payload.get("run_config_summary") or "").strip() or None
    auto_score = payload.get("epub_auto_selected_score")
    if auto_score is None and run_config is not None:
        auto_score = run_config.get("epub_auto_selected_score")
    try:
        epub_auto_selected_score = (
            float(auto_score) if auto_score is not None and str(auto_score).strip() != "" else None
        )
    except (TypeError, ValueError):
        epub_auto_selected_score = None

    recipes: int | None
    try:
        recipes = int(payload.get("recipe_count"))
    except (TypeError, ValueError):
        recipes = None

    if recipes is None and processed_report_path:
        recipes = _load_total_recipes_from_report_path(processed_report_path)

    return PredRunContext(
        recipes=recipes,
        processed_report_path=processed_report_path,
        source_file=source_file,
        source_hash=source_hash,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        epub_auto_selected_score=epub_auto_selected_score,
    )


def _sum_bench_recipe_count(run_root: Path) -> int | None:
    total = 0
    found_any = False
    for manifest_path in run_root.glob("per_item/*/pred_run/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue

        recipe_count: int | None
        try:
            recipe_count = int(payload.get("recipe_count"))
        except (TypeError, ValueError):
            recipe_count = None

        if recipe_count is None:
            processed_report_path = payload.get("processed_report_path")
            recipe_count = _load_total_recipes_from_report_path(processed_report_path)

        if recipe_count is None:
            continue
        total += recipe_count
        found_any = True

    return total if found_any else None


def _prune_empty_dirs(start: Path, *, stop_exclusive: Path | None = None) -> None:
    """Best-effort cleanup of empty directories after moving benchmark artifacts."""
    current = start
    while True:
        if stop_exclusive is not None and current == stop_exclusive:
            break
        try:
            current.rmdir()
        except OSError:
            break
        if current.parent == current:
            break
        current = current.parent


def _display_gold_export_path(path: Path, output_dir: Path) -> str:
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _display_prediction_run_path(path: Path, output_dir: Path) -> str:
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_run_manifest_best_effort(run_root: Path, manifest: RunManifest) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write run_manifest.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write run_manifest.json in %s: %s", run_root, exc)


def _write_stage_run_manifest(
    *,
    run_root: Path,
    output_root: Path,
    requested_path: Path,
    run_dt: dt.datetime,
    run_config: dict[str, Any],
) -> None:
    report_paths = sorted(run_root.glob("*.excel_import_report.json"))
    importer_name: str | None = None
    if report_paths:
        try:
            report_payload = json.loads(report_paths[0].read_text(encoding="utf-8"))
            if isinstance(report_payload, dict):
                importer_name = str(report_payload.get("importerName") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            importer_name = None

    source_hash: str | None = None
    if requested_path.is_file():
        try:
            source_hash = compute_file_hash(requested_path)
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Warning: failed to compute source hash for run manifest: {exc}",
                fg=typer.colors.YELLOW,
                err=True,
            )

    artifacts: dict[str, Any] = {}
    if report_paths:
        artifacts["reports"] = [path.name for path in report_paths]
    for path_key, artifact_key in (
        ("intermediate drafts", "intermediate_drafts_dir"),
        ("final drafts", "final_drafts_dir"),
        ("tips", "tips_dir"),
        ("chunks", "chunks_dir"),
        ("raw", "raw_dir"),
    ):
        target = run_root / path_key
        if target.exists():
            artifacts[artifact_key] = path_key
    history_csv = output_root / ".history" / "performance_history.csv"
    if history_csv.exists():
        artifacts["history_csv"] = str(history_csv)

    manifest = RunManifest(
        run_kind="stage",
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(requested_path),
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes="Stage run outputs for cookbook import.",
    )
    _write_run_manifest_best_effort(run_root, manifest)


def _write_eval_run_manifest(
    *,
    run_root: Path,
    run_kind: str,
    source_path: str | None,
    source_hash: str | None,
    importer_name: str | None,
    run_config: dict[str, Any],
    artifacts: dict[str, Any],
    notes: str | None = None,
) -> None:
    manifest = RunManifest(
        run_kind=run_kind,
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=source_path,
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes=notes,
    )
    _write_run_manifest_best_effort(run_root, manifest)


def _require_importer(path: Path):
    importer, score = registry.best_importer_for_path(path)
    if importer is None or score <= 0:
        _fail("No importer available for this path.")
    return importer


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            yield path


def _resolve_mapping_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".mapping.yaml")
    sidecar_json = workbook.with_suffix(".mapping.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "mappings" / f"{workbook.stem}.mapping.yaml"
    if staged.exists():
        return staged
    return None


def _resolve_overrides_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".overrides.yaml")
    sidecar_json = workbook.with_suffix(".overrides.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "overrides" / f"{workbook.stem}.overrides.yaml"
    if staged.exists():
        return staged
    return None


@dataclass(frozen=True)
class JobSpec:
    file_path: Path
    job_index: int
    job_count: int
    start_page: int | None = None
    end_page: int | None = None
    start_spine: int | None = None
    end_spine: int | None = None

    @property
    def is_split(self) -> bool:
        return self.split_kind is not None

    @property
    def split_kind(self) -> str | None:
        if self.start_page is not None or self.end_page is not None:
            return "pdf"
        if self.start_spine is not None or self.end_spine is not None:
            return "epub"
        return None

    @property
    def display_name(self) -> str:
        if not self.is_split:
            return self.file_path.name
        if self.split_kind == "epub":
            start = (self.start_spine or 0) + 1
            end = self.end_spine or start
            return f"{self.file_path.name} [spine {start}-{end}]"
        start = (self.start_page or 0) + 1
        end = self.end_page or start
        return f"{self.file_path.name} [pages {start}-{end}]"


def _resolve_pdf_page_count(path: Path) -> int | None:
    importer = registry.get_importer("pdf")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    page_count = inspection.sheets[0].page_count
    if page_count is None:
        return None
    try:
        return int(page_count)
    except (TypeError, ValueError):
        return None


def _resolve_epub_spine_count(path: Path) -> int | None:
    importer = registry.get_importer("epub")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    spine_count = inspection.sheets[0].spine_count
    if spine_count is None:
        return None
    try:
        return int(spine_count)
    except (TypeError, ValueError):
        return None


def _plan_jobs(
    files: list[Path],
    *,
    workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    epub_extractor: str = "unstructured",
    epub_extractor_by_file: dict[Path, str] | None = None,
) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    for file_path in files:
        selected_epub_extractor = str(
            (epub_extractor_by_file or {}).get(file_path, epub_extractor)
        ).strip().lower()
        if (
            pdf_split_workers > 1
            and file_path.suffix.lower() == ".pdf"
            and pdf_pages_per_job > 0
        ):
            page_count = _resolve_pdf_page_count(file_path)
            if page_count:
                ranges = plan_pdf_page_ranges(
                    page_count,
                    pdf_split_workers,
                    pdf_pages_per_job,
                )
                if len(ranges) > 1:
                    for idx, (start, end) in enumerate(ranges):
                        jobs.append(
                            JobSpec(
                                file_path=file_path,
                                job_index=idx,
                                job_count=len(ranges),
                                start_page=start,
                                end_page=end,
                            )
                        )
                    continue
        if (
            epub_split_workers > 1
            and file_path.suffix.lower() == ".epub"
            and selected_epub_extractor not in {"markitdown", "auto"}
            and epub_spine_items_per_job > 0
        ):
            spine_count = _resolve_epub_spine_count(file_path)
            if spine_count:
                ranges = plan_job_ranges(
                    spine_count,
                    epub_split_workers,
                    epub_spine_items_per_job,
                )
                if len(ranges) > 1:
                    for idx, (start, end) in enumerate(ranges):
                        jobs.append(
                            JobSpec(
                                file_path=file_path,
                                job_index=idx,
                                job_count=len(ranges),
                                start_spine=start,
                                end_spine=end,
                            )
                        )
                    continue
        jobs.append(JobSpec(file_path=file_path, job_index=0, job_count=1))
    return jobs


def _merge_raw_artifacts(out: Path, workbook_slug: str, job_results: list[dict[str, Any]]) -> None:
    job_parts_root = out / ".job_parts" / workbook_slug
    if not job_parts_root.exists():
        return

    for job in job_results:
        job_index = int(job.get("job_index", 0))
        job_raw_root = job_parts_root / f"job_{job_index}" / "raw"
        if not job_raw_root.exists():
            continue
        for raw_path in job_raw_root.rglob("*"):
            if raw_path.is_dir():
                continue
            relative = raw_path.relative_to(job_raw_root)
            target = out / "raw" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = _prefix_collision(target, job_index)
            shutil.move(str(raw_path), str(target))

    shutil.rmtree(job_parts_root, ignore_errors=True)
    job_parts_parent = out / ".job_parts"
    try:
        if job_parts_parent.exists() and not any(job_parts_parent.iterdir()):
            job_parts_parent.rmdir()
    except OSError:
        pass


def _prefix_collision(path: Path, job_index: int) -> Path:
    prefix = f"job_{job_index}_"
    candidate = path.with_name(f"{prefix}{path.name}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{prefix}{counter}_{path.name}")
        counter += 1
    return candidate


def _normalize_epub_auto_selection_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    return dict(payload)


def _resolve_epub_auto_selected_score(
    payload: dict[str, Any] | None,
) -> float | None:
    return selected_auto_score(payload)


def _write_error_report(
    out: Path,
    file_path: Path,
    run_dt: dt.datetime,
    errors: list[str],
    *,
    importer_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
) -> None:
    report = ConversionReport(
        errors=errors,
        sourceFile=str(file_path),
        importerName=importer_name,
        runTimestamp=run_dt.isoformat(timespec="seconds"),
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    if epub_auto_selection is not None:
        report.epub_auto_selection = _normalize_epub_auto_selection_payload(epub_auto_selection)
    if epub_auto_selected_score is not None:
        report.epub_auto_selected_score = float(epub_auto_selected_score)
    write_report(report, out, file_path.stem)


def _job_range_start(job: dict[str, Any]) -> int:
    start_page = job.get("start_page")
    if start_page is not None:
        return int(start_page)
    start_spine = job.get("start_spine")
    if start_spine is not None:
        return int(start_spine)
    return 0


def _merge_split_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    importer_name: str,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workbook_slug = slugify_name(file_path.stem)
    merge_stats = TimingStats()
    merge_start = time.monotonic()

    def _report_status(message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            return

    ordered_jobs = sorted(job_results, key=_job_range_start)
    should_write_chunks = False
    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        if result.non_recipe_blocks or result.topic_candidates:
            should_write_chunks = True
            break

    phase_labels = [
        "Merging job payloads...",
        "Reassigning recipe IDs...",
        "Building chunks...",
        "Writing merged outputs...",
        "Writing intermediate drafts...",
        "Writing final drafts...",
        "Writing tips...",
        "Writing topic candidates...",
    ]
    if should_write_chunks:
        phase_labels.append("Writing chunks...")
    phase_labels.extend(
        [
            "Writing report...",
            "Merging raw artifacts...",
            "Merge done",
        ]
    )
    phase_total = len(phase_labels)
    phase_current = 0

    def _report_phase(label: str) -> None:
        nonlocal phase_current
        phase_current += 1
        _report_status(
            format_phase_counter("merge", phase_current, phase_total, label=label)
        )

    _report_phase("Merging job payloads...")
    merged_recipes: list[Any] = []
    merged_tip_candidates: list[Any] = []
    merged_topic_candidates: list[Any] = []
    merged_non_recipe_blocks: list[Any] = []
    warnings: list[str] = []
    epub_backends: set[str] = set()
    standalone_block_total = 0
    standalone_topic_block_total = 0

    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        merged_recipes.extend(result.recipes)
        merged_tip_candidates.extend(result.tip_candidates)
        merged_topic_candidates.extend(result.topic_candidates)
        merged_non_recipe_blocks.extend(result.non_recipe_blocks)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            for error in result.report.errors:
                warnings.append(f"Job {job.get('job_index')}: {error}")
        if result.report and result.report.epub_backend:
            epub_backends.add(str(result.report.epub_backend))
        if result.report:
            standalone_block_total += result.report.total_standalone_blocks
            standalone_topic_block_total += result.report.total_standalone_topic_blocks

    _report_phase("Reassigning recipe IDs...")
    file_hash = compute_file_hash(file_path)
    sorted_recipes, _ = reassign_recipe_ids(
        merged_recipes,
        merged_tip_candidates,
        file_hash=file_hash,
        importer_name=importer_name,
    )
    tips, _, _ = partition_tip_candidates(merged_tip_candidates)

    report = ConversionReport(
        warnings=warnings,
        importerName=importer_name,
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    if epub_auto_selection is None:
        for job in ordered_jobs:
            result = job.get("result")
            if result is None or result.report is None:
                continue
            if result.report.epub_auto_selection:
                epub_auto_selection = dict(result.report.epub_auto_selection)
                break
    if epub_auto_selected_score is None:
        for job in ordered_jobs:
            result = job.get("result")
            if result is None or result.report is None:
                continue
            if result.report.epub_auto_selected_score is not None:
                epub_auto_selected_score = float(result.report.epub_auto_selected_score)
                break
    if epub_auto_selection is not None:
        report.epub_auto_selection = _normalize_epub_auto_selection_payload(epub_auto_selection)
    if epub_auto_selected_score is not None:
        report.epub_auto_selected_score = float(epub_auto_selected_score)
    if importer_name == "epub" and epub_backends:
        report.epub_backend = sorted(epub_backends)[0]
        if len(epub_backends) > 1:
            report.warnings.append(
                "epub_backend_inconsistent_across_split_jobs: "
                + ", ".join(sorted(epub_backends))
            )
    merged_result = ConversionResult(
        recipes=sorted_recipes,
        tips=tips,
        tip_candidates=merged_tip_candidates,
        topic_candidates=merged_topic_candidates,
        non_recipe_blocks=merged_non_recipe_blocks,
        raw_artifacts=[],
        report=report,
        workbook=file_path.stem,
        workbook_path=str(file_path),
    )

    from cookimport.cli_worker import apply_result_limits
    apply_result_limits(merged_result, limit, limit, limit_label=limit)
    report.total_topic_candidates = len(merged_result.topic_candidates)
    report.total_standalone_blocks = standalone_block_total
    report.total_standalone_topic_blocks = standalone_topic_block_total
    if standalone_block_total:
        standalone_coverage = standalone_topic_block_total / standalone_block_total
        report.standalone_topic_coverage = standalone_coverage
        if standalone_coverage < 0.9 and not any(
            warning.startswith("Standalone topic coverage low:") for warning in warnings
        ):
            report.warnings.append(
                "Standalone topic coverage low: "
                f"{standalone_topic_block_total} of {standalone_block_total} blocks "
                f"represented ({standalone_coverage:.0%})."
            )

    parsing_overrides = (
        mapping_config.parsing_overrides if mapping_config and mapping_config.parsing_overrides else None
    )
    _report_phase("Building chunks...")
    if merged_result.non_recipe_blocks:
        merged_result.chunks = chunks_from_non_recipe_blocks(
            merged_result.non_recipe_blocks,
            overrides=parsing_overrides,
        )
    elif merged_result.topic_candidates:
        merged_result.chunks = chunks_from_topic_candidates(
            merged_result.topic_candidates,
            overrides=parsing_overrides,
        )

    report.run_timestamp = run_dt.isoformat(timespec="seconds")
    enrich_report_with_stats(report, merged_result, file_path)

    output_stats = OutputStats(out)
    _report_phase("Writing merged outputs...")
    with measure(merge_stats, "writing"):
        intermediate_dir = out / "intermediate drafts" / workbook_slug
        final_dir = out / "final drafts" / workbook_slug
        tips_dir = out / "tips" / workbook_slug

        _report_phase("Writing intermediate drafts...")
        with measure(merge_stats, "write_intermediate_seconds"):
            write_intermediate_outputs(merged_result, intermediate_dir, output_stats=output_stats)
        _report_phase("Writing final drafts...")
        with measure(merge_stats, "write_final_seconds"):
            write_draft_outputs(merged_result, final_dir, output_stats=output_stats)
        _report_phase("Writing tips...")
        with measure(merge_stats, "write_tips_seconds"):
            write_tip_outputs(merged_result, tips_dir, output_stats=output_stats)
        _report_phase("Writing topic candidates...")
        with measure(merge_stats, "write_topic_candidates_seconds"):
            write_topic_candidate_outputs(merged_result, tips_dir, output_stats=output_stats)

        if should_write_chunks:
            _report_phase("Writing chunks...")
            if merged_result.chunks:
                chunks_dir = out / "chunks" / workbook_slug
                with measure(merge_stats, "write_chunks_seconds"):
                    write_chunk_outputs(merged_result.chunks, chunks_dir, output_stats=output_stats)

    merge_stats.parsing_seconds = sum(
        float(job.get("timing", {}).get("parsing_seconds", 0.0)) for job in job_results
    )
    merge_stats.ocr_seconds = sum(
        float(job.get("timing", {}).get("ocr_seconds", 0.0)) for job in job_results
    )
    merge_overhead = max(0.0, time.monotonic() - merge_start - merge_stats.writing_seconds)
    merge_stats.checkpoints["merge_seconds"] = merge_overhead
    merge_stats.total_seconds = (
        merge_stats.parsing_seconds + merge_stats.writing_seconds + merge_overhead
    )

    if output_stats.file_counts:
        report.output_stats = output_stats.to_report()
    report.timing = merge_stats.to_dict()
    _report_phase("Writing report...")
    write_report(report, out, file_path.stem)

    _report_phase("Merging raw artifacts...")
    _merge_raw_artifacts(out, workbook_slug, job_results)
    _report_phase("Merge done")

    return {
        "file": file_path.name,
        "status": "success",
        "recipes": len(merged_result.recipes),
        "tips": len(merged_result.tips),
        "duration": merge_stats.total_seconds,
    }


def _merge_pdf_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="pdf",
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        status_callback=status_callback,
    )


def _merge_epub_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="epub",
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        epub_auto_selection=epub_auto_selection,
        epub_auto_selected_score=epub_auto_selected_score,
        status_callback=status_callback,
    )


@app.command()
def stage(
    path: Path = typer.Argument(..., help="File or folder containing source files."),
    out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
    mapping: Path | None = typer.Option(None, "--mapping", help="Mapping file path."),
    overrides: Path | None = typer.Option(
        None,
        "--overrides",
        help="Parsing overrides file path.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Limit output to the first N recipes and N tips per file.",
    ),
    ocr_device: str = typer.Option(
        "auto",
        "--ocr-device",
        help="OCR device to use (auto, cpu, cuda, mps).",
    ),
    ocr_batch_size: int = typer.Option(
        1,
        "--ocr-batch-size",
        min=1,
        help="Number of pages to process per OCR model call.",
    ),
    pdf_pages_per_job: int = typer.Option(
        50,
        "--pdf-pages-per-job",
        min=1,
        help="Target page count per PDF job when splitting large PDFs.",
    ),
    epub_spine_items_per_job: int = typer.Option(
        10,
        "--epub-spine-items-per-job",
        min=1,
        help="Target spine items per EPUB job when splitting large EPUBs.",
    ),
    warm_models: bool = typer.Option(
        False,
        "--warm-models",
        help="Proactively load heavy models before processing.",
    ),
    workers: int = typer.Option(
        7,
        "--workers",
        "-w",
        min=1,
        help="Number of parallel worker processes.",
    ),
    pdf_split_workers: int = typer.Option(
        7,
        "--pdf-split-workers",
        min=1,
        help="Max workers used to split a single PDF into jobs.",
    ),
    epub_split_workers: int = typer.Option(
        7,
        "--epub-split-workers",
        min=1,
        help="Max workers used to split a single EPUB into jobs.",
    ),
    epub_extractor: str = typer.Option(
        "unstructured",
        "--epub-extractor",
        help=(
            "EPUB extraction engine: unstructured (semantic), legacy (BeautifulSoup), "
            "markdown (HTML->Markdown), auto (deterministic pre-selection), "
            "or markitdown (legacy whole-book EPUB->markdown mode)."
        ),
    ),
    epub_unstructured_html_parser_version: str = typer.Option(
        "v1",
        "--epub-unstructured-html-parser-version",
        help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
    ),
    epub_unstructured_skip_headers_footers: bool = typer.Option(
        False,
        "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
    ),
    epub_unstructured_preprocess_mode: str = typer.Option(
        "br_split_v1",
        "--epub-unstructured-preprocess-mode",
        help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1, semantic_v1.",
    ),
) -> Path:
    """Stage recipes from a source file or folder.

    Outputs are organized as:
      {out}/{timestamp}/intermediate drafts/{filename}/  - schema.org Recipe JSON
      {out}/{timestamp}/final drafts/{filename}/         - cookbook3 format
      {out}/{timestamp}/tips/{filename}/                 - Tip/knowledge snippets
      {out}/{timestamp}/<workbook>.excel_import_report.json - Conversion report
    """
    selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        epub_unstructured_html_parser_version
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        epub_unstructured_preprocess_mode
    )
    selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
    selected_ocr_device = _normalize_ocr_device(ocr_device)

    # Apply EPUB unstructured runtime options for this run.
    # Extractor choice is passed explicitly into worker calls.
    _set_epub_unstructured_env(
        html_parser_version=selected_html_parser_version,
        skip_headers_footers=selected_skip_headers_footers,
        preprocess_mode=selected_preprocess_mode,
    )

    if not path.exists():
        _fail(f"Path not found: {path}")
    if mapping is not None and not mapping.exists():
        _fail(f"Mapping file not found: {mapping}")
    if overrides is not None and not overrides.exists():
        _fail(f"Overrides file not found: {overrides}")

    if warm_models:
        with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
            _warm_all_models(ocr_device=selected_ocr_device)

    # Create timestamped output folder for this run
    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    output_root = out
    out = output_root / timestamp
    out.mkdir(parents=True, exist_ok=True)

    files_to_process = list(_iter_files(path))

    if not files_to_process:
        typer.secho("No files found to process.", fg=typer.colors.YELLOW)
        return out

    mapping_override: MappingConfig | None = None
    if mapping is not None:
        mapping_override = load_mapping_config(mapping)
    
    # Resolve mapping config once for parallel runs if provided
    # or use it as a template for overrides
    base_mapping = mapping_override or MappingConfig()
    base_mapping.ocr_device = selected_ocr_device
    base_mapping.ocr_batch_size = ocr_batch_size
    if overrides is not None:
        base_mapping.parsing_overrides = load_parsing_overrides(overrides)

    imported = 0
    errors: list[str] = []
    effective_epub_extractors: dict[Path, str] = {
        file_path: selected_epub_extractor
        for file_path in files_to_process
        if file_path.suffix.lower() == ".epub"
    }
    epub_auto_selection_by_file: dict[Path, dict[str, Any]] = {}
    epub_auto_selected_score_by_file: dict[Path, float] = {}
    if selected_epub_extractor == "auto":
        for file_path in files_to_process:
            if file_path.suffix.lower() != ".epub":
                continue
            resolution = select_epub_extractor_auto(file_path)
            effective_epub_extractors[file_path] = resolution.effective_extractor
            source_hash = compute_file_hash(file_path)
            auto_payload = {
                **resolution.artifact,
                "source_file": str(file_path),
                "source_hash": source_hash,
            }
            epub_auto_selection_by_file[file_path] = auto_payload
            selected_score = _resolve_epub_auto_selected_score(auto_payload)
            if selected_score is not None:
                epub_auto_selected_score_by_file[file_path] = selected_score
            write_auto_extractor_artifact(
                run_root=out,
                source_hash=source_hash,
                artifact=auto_payload,
            )
            typer.secho(
                (
                    f"Auto-selected EPUB extractor for {file_path.name}: "
                    f"{resolution.effective_extractor}"
                ),
                fg=typer.colors.CYAN,
            )

    all_epub = all(f.suffix.lower() == ".epub" for f in files_to_process)
    run_settings = build_run_settings(
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=selected_epub_extractor,
        epub_unstructured_html_parser_version=selected_html_parser_version,
        epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
        epub_unstructured_preprocess_mode=selected_preprocess_mode,
        ocr_device=selected_ocr_device,
        ocr_batch_size=ocr_batch_size,
        warm_models=warm_models,
        mapping_path=mapping,
        overrides_path=overrides,
        all_epub=all_epub,
        effective_workers=compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=selected_epub_extractor,
            all_epub=all_epub,
        ),
    )
    effective_workers = run_settings.effective_workers or workers
    run_config = run_settings.to_run_config_dict()
    run_config["epub_extractor_requested"] = selected_epub_extractor
    run_config["epub_extractor_effective"] = (
        selected_epub_extractor
        if selected_epub_extractor != "auto"
        else "resolved_per_file"
    )

    def _stable_run_config_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _render_run_config_summary(payload: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in sorted(payload):
            value = payload[key]
            rendered = "true" if value is True else "false" if value is False else str(value)
            parts.append(f"{key}={rendered}")
        return " | ".join(parts)

    def _run_config_for_file(file_path: Path) -> dict[str, Any]:
        if file_path.suffix.lower() != ".epub":
            return dict(run_config)
        payload = dict(run_config)
        payload["epub_extractor_effective"] = effective_epub_extractors.get(
            file_path,
            selected_epub_extractor,
        )
        return payload

    def _epub_auto_selection_for_file(file_path: Path) -> dict[str, Any] | None:
        payload = epub_auto_selection_by_file.get(file_path)
        if payload is None:
            return None
        return dict(payload)

    def _epub_auto_selected_score_for_file(file_path: Path) -> float | None:
        score = epub_auto_selected_score_by_file.get(file_path)
        if score is None:
            return None
        return float(score)

    run_config_hash = _stable_run_config_hash(run_config)
    run_config_summary = _render_run_config_summary(run_config)

    from concurrent.futures import ProcessPoolExecutor, as_completed
    from cookimport.cli_worker import stage_one_file, stage_pdf_job, stage_epub_job
    progress_queue = None
    try:
        manager = multiprocessing.Manager()
        progress_queue = manager.Queue()
    except Exception:
        progress_queue = None
    
    # UI State
    worker_status: Dict[str, Dict[str, Any]] = {}
    worker_lock = threading.Lock()
    
    job_specs = _plan_jobs(
        files_to_process,
        workers=workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        epub_extractor=selected_epub_extractor,
        epub_extractor_by_file=effective_epub_extractors,
    )
    total_jobs = len(job_specs)
    expected_jobs: dict[Path, int] = {}
    for job in job_specs:
        if job.is_split and job.file_path not in expected_jobs:
            expected_jobs[job.file_path] = job.job_count

    progress_bar = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
    )
    overall_task = progress_bar.add_task("Total Progress", total=total_jobs)

    worker_render_cache: Text | None = None
    worker_render_last = 0.0

    def _set_worker_status(
        worker_label: str,
        filename: str,
        status: str,
        *,
        updated_at: float | None = None,
    ) -> None:
        nonlocal worker_render_cache, worker_render_last
        if updated_at is None:
            updated_at = time.time()
        with worker_lock:
            worker_status[str(worker_label)] = {
                "file": str(filename),
                "status": str(status),
                "updated_at": float(updated_at),
            }
        worker_render_cache = None
        worker_render_last = 0.0

    def _format_worker_lines() -> Text:
        nonlocal worker_render_cache, worker_render_last
        now = time.time()
        if worker_render_cache is not None and (now - worker_render_last) < 5:
            return worker_render_cache

        with worker_lock:
            items = list(worker_status.items())

        if not items:
            worker_render_cache = Text("Waiting for worker updates...")
            worker_render_last = now
            return worker_render_cache

        task = progress_bar.tasks[0] if progress_bar.tasks else None
        run_complete = bool(task and task.completed >= task.total)

        lines = []
        for worker_label, entry in sorted(items, key=lambda item: item[0]):
            age_seconds = max(0, int(now - entry["updated_at"]))
            age_label = "just now" if age_seconds < 1 else f"{age_seconds}s ago"
            status = entry["status"]
            if not run_complete and status in {"Done", "skipped"}:
                status = "Idle"
            lines.append(
                f"{worker_label}: {entry['file']} - {status} ({age_label})"
            )
        worker_render_cache = Text("\n".join(lines))
        worker_render_last = now
        return worker_render_cache

    class WorkerDashboard:
        def __rich__(self) -> Group:
            return Group(
                Panel(progress_bar),
                Panel(_format_worker_lines(), title="Workers (updated every 5s)"),
            )

    # Background thread to consume queue
    stop_event = threading.Event()
    queue_thread = None
    if progress_queue is not None:
        def process_queue():
            while not stop_event.is_set():
                try:
                    # Non-blocking get with short timeout
                    try:
                        record = progress_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    
                    if isinstance(record, (tuple, list)) and len(record) == 4:
                        worker_label, filename, status, updated_at = record
                    elif isinstance(record, (tuple, list)) and len(record) == 2:
                        filename, status = record
                        worker_label = "worker"
                        updated_at = time.time()
                    else:
                        continue

                    _set_worker_status(
                        str(worker_label),
                        str(filename),
                        str(status),
                        updated_at=float(updated_at),
                    )
                except Exception:
                    pass

        queue_thread = threading.Thread(target=process_queue, daemon=True)
        queue_thread.start()

    typer.secho(
        f"Processing {len(files_to_process)} file(s) as {total_jobs} job(s) using {effective_workers} workers...",
        fg=typer.colors.CYAN,
    )

    job_results_by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

    def _run_config_hash_for_file(file_path: Path) -> str:
        return _stable_run_config_hash(_run_config_for_file(file_path))

    def _run_config_summary_for_file(file_path: Path) -> str:
        return _render_run_config_summary(_run_config_for_file(file_path))

    def handle_job_result(job: JobSpec, res: dict[str, Any], live: Live) -> None:
        nonlocal imported
        job_run_config = _run_config_for_file(job.file_path)
        job_run_config_hash = _run_config_hash_for_file(job.file_path)
        job_run_config_summary = _run_config_summary_for_file(job.file_path)
        job_epub_auto_selection = _epub_auto_selection_for_file(job.file_path)
        job_epub_auto_selected_score = _epub_auto_selected_score_for_file(job.file_path)

        if job.is_split:
            job_results_by_file[job.file_path].append(res)
            if res.get("status") == "error":
                live.console.print(
                    f"[red]✘ Error {job.file_path.name} job {job.job_index}: {res.get('reason')}[/red]"
                )

            expected_count = expected_jobs.get(job.file_path, job.job_count)
            if len(job_results_by_file[job.file_path]) == expected_count:
                results = job_results_by_file.pop(job.file_path)
                failed = [r for r in results if r.get("status") != "success"]
                if failed:
                    reasons = [
                        f"job {r.get('job_index')}: {r.get('reason')}"
                        for r in failed
                    ]
                    if not reasons:
                        reasons = ["job failure"]
                    message = "; ".join(reasons)
                    errors.append(f"{job.file_path.name}: {message}")
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        "Merge skipped (job errors)",
                    )
                    live.console.print(
                        f"[red]✘ Error {job.file_path.name}: {message}[/red]"
                    )
                    _write_error_report(
                        out,
                        job.file_path,
                        run_dt,
                        reasons,
                        importer_name=job.split_kind,
                        run_config=job_run_config,
                        run_config_hash=job_run_config_hash,
                        run_config_summary=job_run_config_summary,
                        epub_auto_selection=job_epub_auto_selection,
                        epub_auto_selected_score=job_epub_auto_selected_score,
                    )
                else:
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        f"Merging {expected_count} job(s)...",
                    )
                    live.console.print(
                        f"Merging {expected_count} jobs for {job.file_path.name}..."
                    )
                    try:
                        def _main_merge_status(message: str) -> None:
                            _set_worker_status(
                                "MainProcess",
                                job.file_path.name,
                                message,
                            )

                        if job.split_kind == "epub":
                            merged = _merge_epub_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                job_epub_auto_selection,
                                job_epub_auto_selected_score,
                                status_callback=_main_merge_status,
                            )
                        else:
                            merged = _merge_pdf_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                status_callback=_main_merge_status,
                            )
                        imported += 1
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            f"Merge done ({merged['duration']:.2f}s)",
                        )
                        live.console.print(
                            f"[green]✔ {merged['file']}: {merged['recipes']} recipes, "
                            f"{merged['tips']} tips (merge {merged['duration']:.2f}s)[/green]"
                        )
                    except Exception as exc:
                        errors.append(f"{job.file_path.name}: {exc}")
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            "Merge error",
                        )
                        live.console.print(
                            f"[red]✘ Error {job.file_path.name}: {exc}[/red]"
                        )
                        _write_error_report(
                            out,
                            job.file_path,
                            run_dt,
                            [str(exc)],
                            importer_name=job.split_kind,
                            run_config=job_run_config,
                            run_config_hash=job_run_config_hash,
                            run_config_summary=job_run_config_summary,
                            epub_auto_selection=job_epub_auto_selection,
                            epub_auto_selected_score=job_epub_auto_selected_score,
                        )
        else:
            if res["status"] == "success":
                imported += 1
                live.console.print(
                    f"[green]✔ {res['file']}: {res['recipes']} recipes, {res['tips']} tips ({res['duration']:.2f}s)[/green]"
                )
            elif res["status"] == "skipped":
                live.console.print(
                    f"[yellow]⚠ Skipping {res['file']}: {res['reason']}[/yellow]"
                )
            else:
                errors.append(f"{res['file']}: {res['reason']}")
                live.console.print(
                    f"[red]✘ Error {res['file']}: {res['reason']}[/red]"
                )

    dashboard = WorkerDashboard()
    with Live(dashboard, refresh_per_second=10) as live:
        try:
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                futures: dict[Any, JobSpec] = {}
                for job in job_specs:
                    job_run_config = _run_config_for_file(job.file_path)
                    job_run_config_hash = _run_config_hash_for_file(job.file_path)
                    job_run_config_summary = _run_config_summary_for_file(job.file_path)
                    job_epub_extractor = effective_epub_extractors.get(job.file_path)
                    job_epub_auto_selection = _epub_auto_selection_for_file(job.file_path)
                    job_epub_auto_selected_score = _epub_auto_selected_score_for_file(
                        job.file_path
                    )
                    if job.is_split:
                        if job.split_kind == "epub":
                            futures[
                                executor.submit(
                                    stage_epub_job,
                                    job.file_path,
                                    out,
                                    base_mapping,
                                    run_dt,
                                    job.start_spine,
                                    job.end_spine,
                                    job.job_index,
                                    job.job_count,
                                    progress_queue,
                                    job.display_name,
                                    job_epub_extractor,
                                    job_run_config,
                                    job_run_config_hash,
                                    job_run_config_summary,
                                    job_epub_auto_selection,
                                    job_epub_auto_selected_score,
                                )
                            ] = job
                        else:
                            futures[
                                executor.submit(
                                    stage_pdf_job,
                                    job.file_path,
                                    out,
                                    base_mapping,
                                    run_dt,
                                    job.start_page,
                                    job.end_page,
                                    job.job_index,
                                    job.job_count,
                                    progress_queue,
                                    job.display_name,
                                    job_run_config,
                                    job_run_config_hash,
                                    job_run_config_summary,
                                )
                            ] = job
                    else:
                        futures[
                            executor.submit(
                                stage_one_file,
                                job.file_path,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                progress_queue,
                                job.display_name,
                                job_epub_extractor,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                job_epub_auto_selection,
                                job_epub_auto_selected_score,
                            )
                        ] = job

                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        res = future.result()
                    except Exception as exc:
                        res = {
                            "file": job.file_path.name,
                            "status": "error",
                            "reason": str(exc),
                            "job_index": job.job_index,
                            "job_count": job.job_count,
                            "start_page": job.start_page,
                            "end_page": job.end_page,
                            "start_spine": job.start_spine,
                            "end_spine": job.end_spine,
                        }

                    progress_bar.update(overall_task, advance=1)
                    handle_job_result(job, res, live)
        except PermissionError:
            live.console.print(
                "[yellow]⚠ Multiprocessing unavailable; running jobs serially.[/yellow]"
            )
            for job in job_specs:
                job_run_config = _run_config_for_file(job.file_path)
                job_run_config_hash = _run_config_hash_for_file(job.file_path)
                job_run_config_summary = _run_config_summary_for_file(job.file_path)
                job_epub_extractor = effective_epub_extractors.get(job.file_path)
                job_epub_auto_selection = _epub_auto_selection_for_file(job.file_path)
                job_epub_auto_selected_score = _epub_auto_selected_score_for_file(
                    job.file_path
                )
                if job.is_split:
                    if job.split_kind == "epub":
                        res = stage_epub_job(
                            job.file_path,
                            out,
                            base_mapping,
                            run_dt,
                            job.start_spine,
                            job.end_spine,
                            job.job_index,
                            job.job_count,
                            progress_queue,
                            job.display_name,
                            job_epub_extractor,
                            job_run_config,
                            job_run_config_hash,
                            job_run_config_summary,
                            job_epub_auto_selection,
                            job_epub_auto_selected_score,
                        )
                    else:
                        res = stage_pdf_job(
                            job.file_path,
                            out,
                            base_mapping,
                            run_dt,
                            job.start_page,
                            job.end_page,
                            job.job_index,
                            job.job_count,
                            progress_queue,
                            job.display_name,
                            job_run_config,
                            job_run_config_hash,
                            job_run_config_summary,
                        )
                else:
                    res = stage_one_file(
                        job.file_path,
                        out,
                        base_mapping,
                        limit,
                        run_dt,
                        progress_queue,
                        job.display_name,
                        job_epub_extractor,
                        job_run_config,
                        job_run_config_hash,
                        job_run_config_summary,
                        job_epub_auto_selection,
                        job_epub_auto_selected_score,
                    )
                progress_bar.update(overall_task, advance=1)
                handle_job_result(job, res, live)

    stop_event.set()
    if queue_thread is not None:
        queue_thread.join()

    typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
    if errors:
        typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
        for message in errors:
            typer.secho(f"- {message}", fg=typer.colors.YELLOW)

    try:
        from cookimport.analytics.perf_report import (
            append_history_csv,
            build_perf_summary,
            format_summary_line,
            history_path,
        )

        summary = build_perf_summary(out)
        if summary.rows:
            typer.secho("\nPerformance summary:", fg=typer.colors.CYAN)
            typer.echo(f"Run: {out}")
            for row in summary.rows:
                typer.echo(format_summary_line(row))

            if summary.total_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
                typer.secho(
                    f"Outliers (total time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.parsing_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
                typer.secho(
                    f"Outliers (parsing time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.writing_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
                typer.secho(
                    f"Outliers (writing time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.per_unit_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
                typer.secho(
                    f"Outliers (per-unit > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.per_recipe_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
                typer.secho(
                    "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
                    fg=typer.colors.YELLOW,
                )
            if summary.knowledge_heavy:
                heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
                typer.secho(
                    "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
                    fg=typer.colors.CYAN,
                )

            append_history_csv(summary.rows, history_path(output_root))
    except Exception as exc:
        logger.warning("Performance summary skipped: %s", exc)

    _write_stage_run_manifest(
        run_root=out,
        output_root=output_root,
        requested_path=path,
        run_dt=run_dt,
        run_config=run_config,
    )

    return out

    typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
    if errors:
        typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
        for message in errors:
            typer.secho(f"- {message}", fg=typer.colors.YELLOW)

    return out


@app.command("perf-report")
def perf_report(
    run_dir: Path | None = typer.Option(
        None,
        "--run-dir",
        help="Run folder to summarize (defaults to latest under --out-dir).",
    ),
    out_dir: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--out-dir",
        help="Root output folder used to locate runs and history CSV.",
    ),
    write_csv: bool = typer.Option(
        True,
        "--write-csv/--no-csv",
        help="Append results to the performance history CSV.",
    ),
) -> None:
    """Summarize per-file performance metrics for a run."""
    from cookimport.analytics.perf_report import (
        append_history_csv,
        build_perf_summary,
        format_summary_line,
        history_path,
        resolve_run_dir,
    )

    resolved = resolve_run_dir(run_dir, out_dir)
    if resolved is None or not resolved.exists():
        _fail(f"No run folder found under {out_dir}.")

    summary = build_perf_summary(resolved)
    if not summary.rows:
        _fail(f"No conversion reports found in {resolved}.")

    typer.secho(f"Performance summary for {resolved}", fg=typer.colors.CYAN)
    for row in summary.rows:
        typer.echo(format_summary_line(row))

    if summary.total_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
        typer.secho(
            f"Outliers (total time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.parsing_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
        typer.secho(
            f"Outliers (parsing time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.writing_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
        typer.secho(
            f"Outliers (writing time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.per_unit_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
        typer.secho(
            f"Outliers (per-unit > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.per_recipe_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
        typer.secho(
            "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
            fg=typer.colors.YELLOW,
        )
    if summary.knowledge_heavy:
        heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
        typer.secho(
            "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
            fg=typer.colors.CYAN,
        )

    if write_csv:
        append_history_csv(summary.rows, history_path(out_dir))


@app.command("stats-dashboard")
def stats_dashboard(
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output-root",
        help="Root output folder for staged imports.",
    ),
    golden_root: Path = typer.Option(
        DEFAULT_GOLDEN,
        "--golden-root",
        help="Root folder for golden-set / benchmark data.",
    ),
    out_dir: Path = typer.Option(
        DEFAULT_OUTPUT / ".history" / "dashboard",
        "--out-dir",
        help="Directory where the dashboard will be written.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the generated dashboard in the default browser.",
    ),
    since_days: int | None = typer.Option(
        None,
        "--since-days",
        help="Only include runs from the last N days.",
    ),
    scan_reports: bool = typer.Option(
        False,
        "--scan-reports",
        help="Force scanning individual *.excel_import_report.json files.",
    ),
) -> None:
    """Generate a static lifetime-stats dashboard (HTML)."""
    from cookimport.analytics.dashboard_collect import collect_dashboard_data
    from cookimport.analytics.dashboard_render import render_dashboard

    data = collect_dashboard_data(
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        scan_reports=scan_reports,
    )

    html_path = render_dashboard(out_dir, data)

    if data.collector_warnings:
        typer.secho(
            f"Collector warnings ({len(data.collector_warnings)}):",
            fg=typer.colors.YELLOW,
        )
        for w in data.collector_warnings[:10]:
            typer.secho(f"  - {w}", fg=typer.colors.YELLOW)

    typer.secho(f"Wrote dashboard to {out_dir}", fg=typer.colors.GREEN)
    typer.echo(f"Open this file in your browser:\n  {html_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(html_path.as_uri())


@app.command("benchmark-csv-backfill")
def benchmark_csv_backfill(
    out_dir: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--out-dir",
        help="Output root used to resolve the default history CSV path.",
    ),
    history_csv: Path | None = typer.Option(
        None,
        "--history-csv",
        help="Explicit performance_history.csv path (overrides --out-dir).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be patched without writing to disk.",
    ),
) -> None:
    """One-off patch for older benchmark CSV rows missing manifest-backed fields."""
    from cookimport.analytics.perf_report import (
        backfill_benchmark_history_csv,
        history_path,
    )

    csv_path = history_csv or history_path(out_dir)
    if not csv_path.exists():
        _fail(f"History CSV not found: {csv_path}")

    summary = backfill_benchmark_history_csv(csv_path, write=not dry_run)

    if dry_run:
        typer.secho(f"Dry run complete: {csv_path}", fg=typer.colors.CYAN)
    else:
        typer.secho(f"Backfill complete: {csv_path}", fg=typer.colors.GREEN)
    typer.echo(f"Benchmark rows scanned: {summary.benchmark_rows}")
    typer.echo(f"Rows updated: {summary.rows_updated}")
    typer.echo(f"Recipes filled: {summary.recipes_filled}")
    typer.echo(f"Report paths filled: {summary.report_paths_filled}")
    typer.echo(f"Source file fields filled: {summary.source_files_filled}")
    typer.echo(f"Rows still missing recipes: {summary.rows_still_missing_recipes}")

    if dry_run and summary.rows_updated > 0:
        typer.secho("Re-run without --dry-run to persist these patches.", fg=typer.colors.YELLOW)


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="Workbook file to inspect."),
    out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
    write_mapping: bool = typer.Option(
        False,
        "--write-mapping",
        help="Write a mapping stub alongside staged outputs.",
    ),
) -> None:
    """Inspect a single workbook and print layout guesses."""
    if not path.exists():
        _fail(f"Path not found: {path}")
    if not path.is_file():
        _fail("Inspect expects a workbook file.")

    importer = _require_importer(path)
    with console.status(f"[bold cyan]Inspecting {path.name}...[/bold cyan]", spinner="dots"):
        inspection = importer.inspect(path)
    typer.secho(f"Workbook: {path.name}", fg=typer.colors.CYAN)
    for sheet in inspection.sheets:
        layout = sheet.layout or "unknown"
        header_row = sheet.header_row or 0
        confidence = sheet.confidence if sheet.confidence is not None else 0.0
        note = " (low confidence)" if sheet.low_confidence else ""
        typer.echo(f"- {sheet.name}: {layout} header_row={header_row} score={confidence:.2f}{note}")
    if write_mapping and inspection.mapping_stub is not None:
        mapping_path = out / "mappings" / f"{path.stem}.mapping.yaml"
        save_mapping_config(mapping_path, inspection.mapping_stub)
        typer.secho(f"Wrote mapping stub to {mapping_path}", fg=typer.colors.GREEN)


@app.command("labelstudio-import")
def labelstudio_import(
    path: Path = typer.Argument(..., help="Cookbook file to import for labeling."),
    output_dir: Path = typer.Option(
        DEFAULT_GOLDEN, "--output-dir", help="Output folder for artifacts."
    ),
    pipeline: str = typer.Option("auto", "--pipeline", help="Importer pipeline name or auto."),
    project_name: str | None = typer.Option(
        None, "--project-name", help="Label Studio project name."
    ),
    chunk_level: str = typer.Option(
        "both",
        "--chunk-level",
        help="Chunk level: structural, atomic, or both.",
    ),
    task_scope: str = typer.Option(
        "pipeline",
        "--task-scope",
        help="Task scope: pipeline, canonical-blocks, or freeform-spans.",
    ),
    context_window: int = typer.Option(
        1,
        "--context-window",
        min=0,
        help="Block context window for canonical-blocks.",
    ),
    segment_blocks: int = typer.Option(
        40,
        "--segment-blocks",
        min=1,
        help="Blocks per task for freeform-spans.",
    ),
    segment_overlap: int = typer.Option(
        5,
        "--segment-overlap",
        min=0,
        help="Overlapping blocks between freeform-spans segments.",
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite/--resume", help="Overwrite project or resume."
    ),
    label_studio_url: str | None = typer.Option(
        None, "--label-studio-url", help="Label Studio base URL."
    ),
    label_studio_api_key: str | None = typer.Option(
        None, "--label-studio-api-key", help="Label Studio API key."
    ),
    allow_labelstudio_write: bool = typer.Option(
        False,
        "--allow-labelstudio-write/--no-allow-labelstudio-write",
        help="Explicitly allow writing tasks to Label Studio.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", min=1, help="Limit number of chunks."
    ),
    sample: int | None = typer.Option(
        None, "--sample", min=1, help="Randomly sample N chunks."
    ),
    prelabel: bool = typer.Option(
        False,
        "--prelabel/--no-prelabel",
        help=(
            "For freeform-spans: ask local Codex CLI for first-pass labels and "
            "attach completed annotations before upload."
        ),
    ),
    prelabel_provider: str = typer.Option(
        "codex-cli",
        "--prelabel-provider",
        help="LLM provider backend for prelabeling (currently: codex-cli).",
    ),
    codex_cmd: str | None = typer.Option(
        None,
        "--codex-cmd",
        help=(
            "Command used for Codex CLI prelabel calls. "
            "Defaults to COOKIMPORT_CODEX_CMD or `codex exec -`."
        ),
    ),
    codex_model: str | None = typer.Option(
        None,
        "--codex-model",
        help=(
            "Explicit Codex model for prelabel calls. "
            "When omitted, uses COOKIMPORT_CODEX_MODEL or your Codex CLI default model."
        ),
    ),
    prelabel_timeout_seconds: int = typer.Option(
        120,
        "--prelabel-timeout-seconds",
        min=1,
        help="Timeout per prelabel provider call.",
    ),
    prelabel_cache_dir: Path | None = typer.Option(
        None,
        "--prelabel-cache-dir",
        help="Optional cache directory for prompt/response snapshots.",
    ),
    prelabel_upload_as: str = typer.Option(
        "annotations",
        "--prelabel-upload-as",
        help="Upload prelabels as completed annotations or predictions.",
    ),
    prelabel_allow_partial: bool = typer.Option(
        False,
        "--prelabel-allow-partial/--no-prelabel-allow-partial",
        help=(
            "Allow upload to continue when some prelabel tasks fail. "
            "Failures are recorded in prelabel report files."
        ),
    ),
) -> None:
    """Create and upload Label Studio tasks for pipeline/canonical/freeform scopes."""
    _require_labelstudio_write_consent(allow_labelstudio_write)
    if prelabel and task_scope != "freeform-spans":
        _fail("--prelabel is only supported with --task-scope freeform-spans.")
    normalized_prelabel_upload_as = prelabel_upload_as.strip().lower()
    if normalized_prelabel_upload_as not in {"annotations", "predictions"}:
        _fail(
            "--prelabel-upload-as must be one of: annotations, predictions."
        )
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
    try:
        result = _run_labelstudio_import_with_status(
            source_name=path.name,
            run_import=lambda update_progress: run_labelstudio_import(
                path=path,
                output_dir=output_dir,
                pipeline=pipeline,
                project_name=project_name,
                chunk_level=chunk_level,
                task_scope=task_scope,
                context_window=context_window,
                segment_blocks=segment_blocks,
                segment_overlap=segment_overlap,
                overwrite=overwrite,
                resume=not overwrite,
                label_studio_url=url,
                label_studio_api_key=api_key,
                limit=limit,
                sample=sample,
                progress_callback=update_progress,
                prelabel=prelabel,
                prelabel_provider=prelabel_provider,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
                prelabel_timeout_seconds=prelabel_timeout_seconds,
                prelabel_cache_dir=prelabel_cache_dir,
                prelabel_upload_as=normalized_prelabel_upload_as,
                prelabel_allow_partial=prelabel_allow_partial,
                prelabel_track_token_usage=True,
                allow_labelstudio_write=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    typer.secho(
        f"Label Studio project: {result['project_name']} (id={result['project_id']})",
        fg=typer.colors.GREEN,
    )
    typer.secho(
        f"Tasks created: {result['tasks_total']} (uploaded {result['tasks_uploaded']})",
        fg=typer.colors.CYAN,
    )
    if prelabel:
        prelabel_summary = result.get("prelabel") or {}
        usage_payload: Any = None
        usage_enabled = True
        if isinstance(prelabel_summary, dict):
            model_label = prelabel_summary.get("codex_model")
            if model_label:
                typer.secho(f"Prelabel model: {model_label}", fg=typer.colors.CYAN)
            usage_payload = prelabel_summary.get("token_usage")
            usage_enabled = bool(
                prelabel_summary.get(
                    "token_usage_enabled",
                    True,
                )
            )
        _print_token_usage_summary(
            prefix="Prelabel token usage",
            usage=usage_payload,
            enabled=usage_enabled,
        )
        report_path = result.get("prelabel_report_path")
        if report_path:
            typer.secho(
                f"Prelabel report: {report_path}",
                fg=typer.colors.CYAN,
            )
        if result.get("prelabel_inline_annotations_fallback"):
            typer.secho(
                "Inline annotation upload fallback was used "
                "(uploaded tasks first, then created annotations).",
                fg=typer.colors.YELLOW,
            )
    typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
    typer.echo("\nTo export labels:\n")
    typer.echo(
        f'cookimport labelstudio-export --project-name "{result["project_name"]}" '
        f'--label-studio-url {url} --label-studio-api-key $LABEL_STUDIO_API_KEY'
    )


@app.command("labelstudio-export")
def labelstudio_export(
    project_name: str = typer.Option(..., "--project-name", help="Label Studio project name."),
    output_dir: Path = typer.Option(
        DEFAULT_GOLDEN, "--output-dir", help="Output folder for manifests."
    ),
    run_dir: Path | None = typer.Option(
        None, "--run-dir", help="Specific labelstudio run directory to export."
    ),
    export_scope: str = typer.Option(
        "pipeline",
        "--export-scope",
        help="Export scope: pipeline, canonical-blocks, or freeform-spans.",
    ),
    label_studio_url: str | None = typer.Option(
        None, "--label-studio-url", help="Label Studio base URL."
    ),
    label_studio_api_key: str | None = typer.Option(
        None, "--label-studio-api-key", help="Label Studio API key."
    ),
) -> None:
    """Export completed Label Studio annotations into golden-set JSONL artifacts."""
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
    try:
        result = run_labelstudio_export(
            project_name=project_name,
            output_dir=output_dir,
            label_studio_url=url,
            label_studio_api_key=api_key,
            run_dir=run_dir,
            export_scope=export_scope,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    summary_path = result["summary_path"]
    typer.secho(f"Export complete. Summary: {summary_path}", fg=typer.colors.GREEN)


@app.command("labelstudio-decorate")
def labelstudio_decorate(
    project_name: str = typer.Option(
        ..., "--project-name", help="Label Studio project name to decorate."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_GOLDEN,
        "--output-dir",
        help="Output folder for decorate reports.",
    ),
    task_scope: str = typer.Option(
        "freeform-spans",
        "--task-scope",
        help="Task scope to decorate (currently only freeform-spans).",
    ),
    add_labels: str = typer.Option(
        ...,
        "--add-labels",
        help="Comma-separated label names to add (example: YIELD_LINE,TIME_LINE).",
    ),
    label_studio_url: str | None = typer.Option(
        None, "--label-studio-url", help="Label Studio base URL."
    ),
    label_studio_api_key: str | None = typer.Option(
        None, "--label-studio-api-key", help="Label Studio API key."
    ),
    prelabel_provider: str = typer.Option(
        "codex-cli",
        "--prelabel-provider",
        help="LLM provider backend (currently: codex-cli).",
    ),
    codex_cmd: str | None = typer.Option(
        None,
        "--codex-cmd",
        help=(
            "Command used for Codex CLI calls. "
            "Defaults to COOKIMPORT_CODEX_CMD or `codex exec -`."
        ),
    ),
    codex_model: str | None = typer.Option(
        None,
        "--codex-model",
        help=(
            "Explicit Codex model for decorate calls. "
            "When omitted, uses COOKIMPORT_CODEX_MODEL or your Codex CLI default model."
        ),
    ),
    prelabel_timeout_seconds: int = typer.Option(
        120,
        "--prelabel-timeout-seconds",
        min=1,
        help="Timeout per Codex CLI call.",
    ),
    prelabel_cache_dir: Path | None = typer.Option(
        None,
        "--prelabel-cache-dir",
        help="Optional cache directory for prompt/response snapshots.",
    ),
    no_write: bool = typer.Option(
        False,
        "--no-write",
        help="Dry run only: compute and report changes without creating annotations.",
    ),
    allow_labelstudio_write: bool = typer.Option(
        False,
        "--allow-labelstudio-write/--no-allow-labelstudio-write",
        help=(
            "Explicitly allow creating annotations in Label Studio "
            "(ignored in --no-write mode)."
        ),
    ),
) -> None:
    """Decorate existing freeform tasks with additive LLM annotations."""
    if task_scope != "freeform-spans":
        _fail("labelstudio-decorate currently supports --task-scope freeform-spans only.")
    if not no_write:
        _require_labelstudio_write_consent(allow_labelstudio_write)
    labels = _parse_csv_labels(add_labels)
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

    try:
        with console.status(
            f"[bold cyan]Running Label Studio decorate for {project_name}...[/bold cyan]",
            spinner="dots",
        ) as status:
            def update_progress(msg: str) -> None:
                status.update(
                    f"[bold cyan]Label Studio decorate ({project_name}): {msg}[/bold cyan]"
                )

            result = run_labelstudio_decorate(
                project_name=project_name,
                output_dir=output_dir,
                label_studio_url=url,
                label_studio_api_key=api_key,
                add_labels=labels,
                task_scope=task_scope,
                prelabel_provider=prelabel_provider,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
                prelabel_timeout_seconds=prelabel_timeout_seconds,
                prelabel_cache_dir=prelabel_cache_dir,
                prelabel_track_token_usage=True,
                allow_labelstudio_write=allow_labelstudio_write,
                no_write=no_write,
                progress_callback=update_progress,
            )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    counts = result["report"]["counts"]
    typer.secho(
        f"Decorate complete ({'dry-run' if no_write else 'write'} mode).",
        fg=typer.colors.GREEN,
    )
    typer.secho(f"Tasks scanned: {counts['tasks_total']}", fg=typer.colors.CYAN)
    if no_write:
        typer.secho(
            f"Would create annotations: {counts['dry_run_would_create']}",
            fg=typer.colors.CYAN,
        )
    else:
        typer.secho(f"Annotations created: {counts['created']}", fg=typer.colors.CYAN)
    if counts["failed"]:
        typer.secho(f"Failures: {counts['failed']}", fg=typer.colors.YELLOW)
    report_payload = result.get("report") if isinstance(result.get("report"), dict) else {}
    usage = report_payload.get("token_usage")
    usage_enabled = bool(
        report_payload.get(
            "token_usage_enabled",
            True,
        )
    )
    _print_token_usage_summary(
        prefix="Decorate token usage",
        usage=usage,
        enabled=usage_enabled,
    )
    typer.secho(f"Report: {result['report_path']}", fg=typer.colors.CYAN)


@app.command("labelstudio-eval")
def labelstudio_eval(
    scope: str = typer.Argument(
        ..., help="Evaluation scope (canonical-blocks, freeform-spans)."
    ),
    pred_run: Path = typer.Option(
        ..., "--pred-run", help="Label Studio run directory with label_studio_tasks.jsonl."
    ),
    gold_spans: Path = typer.Option(
        ..., "--gold-spans", help="Path to canonical or freeform gold JSONL."
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="Output folder for eval artifacts."
    ),
    overlap_threshold: Annotated[
        float,
        typer.Option(
            "--overlap-threshold",
            min=0.0,
            max=1.0,
            help="Jaccard overlap threshold for matching.",
        ),
    ] = 0.5,
    force_source_match: Annotated[
        bool,
        typer.Option(
            "--force-source-match",
            help=(
                "Ignore source hash/file identity when matching spans. "
                "Useful for comparing renamed/truncated source variants."
            ),
        ),
    ] = False,
) -> None:
    """Evaluate pipeline predictions against canonical or freeform gold sets."""
    if scope not in {"canonical-blocks", "freeform-spans"}:
        _fail("Supported scopes: canonical-blocks, freeform-spans.")
    if not pred_run.exists():
        _fail(f"Predicted run not found: {pred_run}")
    if not gold_spans.exists():
        _fail(f"Gold spans file not found: {gold_spans}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if scope == "canonical-blocks":
        predicted = load_predicted_spans(pred_run)
        gold = load_gold_spans(gold_spans)
        result = evaluate_structural_vs_gold(
            predicted, gold, overlap_threshold=overlap_threshold
        )
        report = result["report"]
        report_md = format_eval_report_md(report)
    else:
        predicted = load_predicted_labeled_ranges(pred_run)
        gold = load_gold_freeform_ranges(gold_spans)
        result = evaluate_predicted_vs_freeform(
            predicted,
            gold,
            overlap_threshold=overlap_threshold,
            force_source_match=force_source_match,
        )
        report = result["report"]
        report_md = format_freeform_eval_report_md(report)

    report_json_path = output_dir / "eval_report.json"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_md_path = output_dir / "eval_report.md"
    report_md_path.write_text(report_md, encoding="utf-8")

    write_jsonl(output_dir / "missed_gold_spans.jsonl", result["missed_gold"])
    write_jsonl(
        output_dir / "false_positive_preds.jsonl", result["false_positive_preds"]
    )

    pred_context = _load_pred_run_recipe_context(pred_run)
    csv_source_file = pred_context.source_file or ""
    csv_history_root = DEFAULT_OUTPUT
    if pred_context.processed_report_path:
        processed_report = Path(pred_context.processed_report_path)
        if (
            processed_report.name.endswith(".excel_import_report.json")
            and len(processed_report.parents) >= 2
        ):
            csv_history_root = processed_report.parents[1]

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    append_benchmark_csv(
        report,
        history_path(csv_history_root),
        run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        run_dir=str(output_dir),
        eval_scope=scope,
        source_file=csv_source_file,
        recipes=pred_context.recipes,
        processed_report_path=pred_context.processed_report_path,
        run_config=pred_context.run_config,
        run_config_hash=pred_context.run_config_hash,
        run_config_summary=pred_context.run_config_summary,
        epub_auto_selected_score=pred_context.epub_auto_selected_score,
    )

    eval_run_config: dict[str, Any] = {
        "scope": scope,
        "overlap_threshold": overlap_threshold,
        "force_source_match": force_source_match,
    }
    if pred_context.run_config is not None:
        eval_run_config["prediction_run_config"] = pred_context.run_config
    if pred_context.run_config_hash:
        eval_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
    if pred_context.run_config_summary:
        eval_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

    _write_eval_run_manifest(
        run_root=output_dir,
        run_kind="labelstudio_eval",
        source_path=pred_context.source_file or None,
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=eval_run_config,
        artifacts={
            "pred_run_dir": _path_for_manifest(output_dir, pred_run),
            "gold_spans_jsonl": _path_for_manifest(output_dir, gold_spans),
            "eval_report_json": "eval_report.json",
            "eval_report_md": "eval_report.md",
            "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
            "false_positive_preds_jsonl": "false_positive_preds.jsonl",
            "history_csv": str(csv_history_root / ".history" / "performance_history.csv"),
        },
        notes="Evaluation report against exported gold spans.",
    )

    typer.secho(
        f"Evaluation complete. Report: {report_md_path}",
        fg=typer.colors.GREEN,
    )


_QUANTITY_TOKEN_RE = re.compile(
    r"(?<!\w)(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*"
    r"(?:cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l)\b",
    flags=re.IGNORECASE,
)


def _p95_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, ((len(ordered) * 95 + 99) // 100) - 1)
    return int(ordered[idx])


def _has_multiple_quantity_tokens(text: str) -> bool:
    return len(_QUANTITY_TOKEN_RE.findall(text)) >= 2


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True)
        for row in rows
    )
    path.write_text(payload + "\n", encoding="utf-8")


@app.command("debug-epub-extract")
def debug_epub_extract(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    out: Path = typer.Option(
        DEFAULT_OUTPUT / "epub-debug",
        "--out",
        help="Output root for debug extraction artifacts.",
    ),
    spine: int = typer.Option(
        0,
        "--spine",
        min=0,
        help="Spine index to extract for variant comparison.",
    ),
    variants: bool = typer.Option(
        False,
        "--variants",
        help=(
            "Run the parser/preprocess variant grid "
            "(v1/v2 x none/br_split_v1) instead of a single variant."
        ),
    ),
    html_parser_version: str = typer.Option(
        "v1",
        "--html-parser-version",
        help="Single-run parser version when --variants is not set (v1 or v2).",
    ),
    preprocess_mode: str = typer.Option(
        "none",
        "--preprocess-mode",
        help=(
            "Single-run preprocess mode when --variants is not set "
            "(none, br_split_v1, semantic_v1)."
        ),
    ),
    skip_headers_footers: bool = typer.Option(
        False,
        "--skip-headers-footers/--no-skip-headers-footers",
        help="Pass skip_headers_and_footers into Unstructured partition_html.",
    ),
) -> None:
    """Compare unstructured EPUB extraction variants for one spine XHTML document."""
    from cookimport.parsing.block_roles import assign_block_roles
    from cookimport.parsing.epub_postprocess import postprocess_epub_blocks
    from cookimport.parsing.epub_html_normalize import normalize_epub_html_for_unstructured
    from cookimport.parsing import signals
    from cookimport.parsing.unstructured_adapter import (
        UnstructuredHtmlOptions,
        partition_html_to_blocks,
    )

    if not path.exists() or not path.is_file():
        _fail(f"EPUB file not found: {path}")
    if path.suffix.lower() != ".epub":
        _fail(f"Expected an EPUB file, got: {path}")

    selected_parser = _normalize_unstructured_html_parser_version(html_parser_version)
    selected_preprocess = _normalize_unstructured_preprocess_mode(preprocess_mode)

    run_root = out / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    run_root.mkdir(parents=True, exist_ok=True)

    importer = epub.EpubImporter()
    _title, spine_items = importer._read_epub_spine(path)  # noqa: SLF001
    if not spine_items:
        _fail("No spine items found in EPUB.")
    if spine >= len(spine_items):
        _fail(
            f"Spine index out of range: {spine}. "
            f"EPUB has {len(spine_items)} spine entries."
        )

    spine_path = spine_items[spine].path
    with zipfile.ZipFile(path) as zip_handle:
        raw_html = zip_handle.read(spine_path).decode("utf-8", errors="replace")
    (run_root / "raw_spine.xhtml").write_text(raw_html, encoding="utf-8")

    variant_pairs: list[tuple[str, str]]
    if variants:
        variant_pairs = [
            (parser_version, preprocess_variant)
            for preprocess_variant in ("none", "br_split_v1")
            for parser_version in ("v1", "v2")
        ]
    else:
        variant_pairs = [(selected_parser, selected_preprocess)]

    summary_rows: list[dict[str, Any]] = []
    for parser_version, preprocess_variant in variant_pairs:
        variant_slug = f"parser_{parser_version}__preprocess_{preprocess_variant}"
        variant_dir = run_root / variant_slug
        variant_dir.mkdir(parents=True, exist_ok=True)

        normalized_html = normalize_epub_html_for_unstructured(
            raw_html,
            mode=preprocess_variant,
        )
        (variant_dir / "normalized_spine.xhtml").write_text(
            normalized_html,
            encoding="utf-8",
        )

        options = UnstructuredHtmlOptions(
            html_parser_version=parser_version,
            skip_headers_and_footers=skip_headers_footers,
            preprocess_mode=preprocess_variant,
        )
        try:
            blocks, diagnostics = partition_html_to_blocks(
                normalized_html,
                spine_index=spine,
                source_location_id=path.stem,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001
            (variant_dir / "error.txt").write_text(str(exc), encoding="utf-8")
            summary_rows.append(
                {
                    "variant": variant_slug,
                    "html_parser_version": parser_version,
                    "preprocess_mode": preprocess_variant,
                    "skip_headers_footers": skip_headers_footers,
                    "error": str(exc),
                    "block_count": 0,
                    "p95_block_length": 0,
                    "blocks_with_multiple_quantities": 0,
                    "ingredient_line_block_count": 0,
                }
            )
            continue
        blocks = postprocess_epub_blocks(blocks)
        for block in blocks:
            signals.enrich_block(block)
        assign_block_roles(blocks)

        blocks_rows = [
            {
                "index": index,
                "text": block.text,
                "type": str(block.type),
                "font_weight": block.font_weight,
                "features": dict(block.features),
            }
            for index, block in enumerate(blocks)
        ]
        _write_jsonl_rows(variant_dir / "blocks.jsonl", blocks_rows)
        _write_jsonl_rows(variant_dir / "unstructured_elements.jsonl", diagnostics)

        block_lengths = [len(block.text) for block in blocks if block.text]
        ingredient_line_count = sum(
            1
            for block in blocks
            if block.features.get("block_role") == "ingredient_line"
        )
        multi_quantity_count = sum(
            1
            for block in blocks
            if _has_multiple_quantity_tokens(block.text)
        )
        summary_rows.append(
            {
                "variant": variant_slug,
                "html_parser_version": parser_version,
                "preprocess_mode": preprocess_variant,
                "skip_headers_footers": skip_headers_footers,
                "block_count": len(blocks),
                "p95_block_length": _p95_int(block_lengths),
                "blocks_with_multiple_quantities": multi_quantity_count,
                "ingredient_line_block_count": ingredient_line_count,
            }
        )

    summary_payload = {
        "source_file": str(path),
        "spine_index": spine,
        "spine_path": spine_path,
        "variants": summary_rows,
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    typer.secho(f"Wrote EPUB debug extraction artifacts to: {run_root}", fg=typer.colors.GREEN)
    for row in summary_rows:
        typer.echo(
            " | ".join(
                [
                    row["variant"],
                    f"blocks={row['block_count']}",
                    f"p95_len={row['p95_block_length']}",
                    f"multi_qty={row['blocks_with_multiple_quantities']}",
                    f"ingredient_line={row['ingredient_line_block_count']}",
                ]
            )
        )


@app.command("labelstudio-benchmark")
def labelstudio_benchmark(
    gold_spans: Annotated[Path | None, typer.Option(
        "--gold-spans",
        help="Path to freeform_span_labels.jsonl (prompts if omitted).",
    )] = None,
    source_file: Annotated[Path | None, typer.Option(
        "--source-file",
        help="Source file to import and benchmark (prompts if omitted).",
    )] = None,
    output_dir: Annotated[Path, typer.Option(
        "--output-dir",
        help="Scratch output root used while generating prediction tasks before co-locating under eval output.",
    )] = DEFAULT_GOLDEN,
    processed_output_dir: Annotated[Path, typer.Option(
        "--processed-output-dir",
        help="Output root for staged cookbook outputs generated during benchmark (for upload/review).",
    )] = DEFAULT_OUTPUT,
    eval_output_dir: Annotated[Path | None, typer.Option(
        "--eval-output-dir", help="Output folder for benchmark report artifacts."
    )] = None,
    overlap_threshold: Annotated[float, typer.Option(
        "--overlap-threshold",
        min=0.0,
        max=1.0,
        help="Jaccard overlap threshold for matching.",
    )] = 0.5,
    force_source_match: Annotated[bool, typer.Option(
        "--force-source-match",
        help=(
            "Ignore source hash/file identity when matching spans. "
            "Useful for comparing renamed/truncated source variants."
        ),
    )] = False,
    pipeline: Annotated[str, typer.Option("--pipeline", help="Importer pipeline name or auto.")] = "auto",
    chunk_level: Annotated[str, typer.Option(
        "--chunk-level",
        help="Chunk level for predictions: structural, atomic, or both.",
    )] = "both",
    project_name: Annotated[str | None, typer.Option(
        "--project-name",
        help="Optional Label Studio project name for prediction import.",
    )] = None,
    allow_labelstudio_write: Annotated[bool, typer.Option(
        "--allow-labelstudio-write/--no-allow-labelstudio-write",
        help=(
            "Explicitly allow uploading prediction tasks to Label Studio. "
            "Ignored when --no-upload is set."
        ),
    )] = False,
    no_upload: Annotated[bool, typer.Option(
        "--no-upload",
        help=(
            "Generate prediction artifacts locally and evaluate without "
            "uploading to Label Studio."
        ),
    )] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite/--resume", help="Overwrite prediction project or resume.")] = False,
    label_studio_url: Annotated[str | None, typer.Option("--label-studio-url", help="Label Studio base URL.")] = None,
    label_studio_api_key: Annotated[str | None, typer.Option("--label-studio-api-key", help="Label Studio API key.")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Number of parallel worker processes for prediction import.")] = 7,
    pdf_split_workers: Annotated[int, typer.Option("--pdf-split-workers", min=1, help="Max workers used when splitting a PDF prediction import.")] = 7,
    epub_split_workers: Annotated[int, typer.Option("--epub-split-workers", min=1, help="Max workers used when splitting an EPUB prediction import.")] = 7,
    pdf_pages_per_job: Annotated[int, typer.Option("--pdf-pages-per-job", min=1, help="Target page count per PDF split job.")] = 50,
    epub_spine_items_per_job: Annotated[int, typer.Option("--epub-spine-items-per-job", min=1, help="Target spine items per EPUB split job.")] = 10,
    ocr_device: Annotated[str, typer.Option(
        "--ocr-device",
        help="OCR device to use (auto, cpu, cuda, mps).",
    )] = "auto",
    ocr_batch_size: Annotated[int, typer.Option(
        "--ocr-batch-size",
        min=1,
        help="Number of pages to process per OCR model call.",
    )] = 1,
    warm_models: Annotated[bool, typer.Option(
        "--warm-models",
        help="Proactively load heavy models before prediction import.",
    )] = False,
    epub_extractor: Annotated[str, typer.Option(
        "--epub-extractor",
        help=(
            "EPUB extraction engine: unstructured (semantic), legacy (BeautifulSoup), "
            "markdown (HTML->Markdown), auto (deterministic pre-selection), "
            "or markitdown (legacy whole-book EPUB->markdown mode)."
        ),
    )] = "unstructured",
    epub_unstructured_html_parser_version: Annotated[str, typer.Option(
        "--epub-unstructured-html-parser-version",
        help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
    )] = "v1",
    epub_unstructured_skip_headers_footers: Annotated[bool, typer.Option(
        "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
    )] = False,
    epub_unstructured_preprocess_mode: Annotated[str, typer.Option(
        "--epub-unstructured-preprocess-mode",
        help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1, semantic_v1.",
    )] = "br_split_v1",
) -> None:
    """Run benchmark eval against freeform gold, with optional upload step."""
    selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        epub_unstructured_html_parser_version
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        epub_unstructured_preprocess_mode
    )
    selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
    selected_ocr_device = _normalize_ocr_device(ocr_device)
    url: str | None = None
    api_key: str | None = None
    if not no_upload:
        _require_labelstudio_write_consent(allow_labelstudio_write)
        url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

    selected_gold = gold_spans
    if selected_gold is None:
        candidates = _discover_freeform_gold_exports(output_dir)
        if not candidates:
            _fail(
                "No freeform gold exports found. Run `cookimport labelstudio-export --export-scope freeform-spans` first."
            )
        selected_gold = _menu_select(
            "Select a freeform gold export:",
            menu_help=(
                "Choose the labeled freeform export to benchmark against. "
                "Newest exports are listed first."
            ),
            choices=[
                questionary.Choice(
                    _display_gold_export_path(path, output_dir),
                    value=path,
                )
                for path in candidates[:30]
            ],
        )
        if selected_gold in {None, BACK_ACTION}:
            _fail("Benchmark cancelled.")
    if not selected_gold.exists():
        _fail(f"Gold spans file not found: {selected_gold}")

    selected_source = source_file
    inferred_source = None
    if selected_source is None:
        inferred_source = _infer_source_file_from_freeform_gold(selected_gold)
    if selected_source is None and inferred_source is not None:
        use_inferred = questionary.confirm(
            f"Use inferred source file `{inferred_source}`?",
            default=True,
        ).ask()
        if use_inferred:
            selected_source = inferred_source
    if selected_source is None:
        importable_files = _list_importable_files(DEFAULT_INPUT)
        if importable_files:
            source_choice = _menu_select(
                "Select source file to benchmark:",
                menu_help=(
                    "Choose the source file used to generate prediction tasks "
                    "for comparison to the selected gold export."
                ),
                choices=[
                    *[questionary.Choice(path.name, value=path) for path in importable_files],
                    questionary.Choice("Enter a custom path", value="custom"),
                ],
            )
            if source_choice in {None, BACK_ACTION}:
                _fail("Benchmark cancelled.")
            if source_choice == "custom":
                source_path = questionary.text("Enter source file path:").ask()
                if not source_path:
                    _fail("Benchmark cancelled.")
                selected_source = Path(source_path)
            else:
                selected_source = source_choice
        else:
            source_path = questionary.text("Enter source file path:").ask()
            if not source_path:
                _fail("Benchmark cancelled.")
            selected_source = Path(source_path)
    if not selected_source.exists() or not selected_source.is_file():
        _fail(f"Source file not found: {selected_source}")
    _require_importer(selected_source)

    if eval_output_dir is None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        eval_output_dir = selected_gold.parent.parent / "eval-vs-pipeline" / timestamp
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    if warm_models:
        with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
            _warm_all_models(ocr_device=selected_ocr_device)

    try:
        with _temporary_epub_extractor(selected_epub_extractor):
            with _temporary_epub_unstructured_options(
                html_parser_version=selected_html_parser_version,
                skip_headers_footers=selected_skip_headers_footers,
                preprocess_mode=selected_preprocess_mode,
            ):
                with console.status(
                    f"[bold cyan]Generating prediction tasks for {selected_source.name}...[/bold cyan]",
                    spinner="dots",
                ) as status:
                    def update_progress(msg: str) -> None:
                        status.update(
                            f"[bold cyan]Benchmark import ({selected_source.name}): {msg}[/bold cyan]"
                        )

                    if no_upload:
                        import_result = generate_pred_run_artifacts(
                            path=selected_source,
                            output_dir=output_dir,
                            pipeline=pipeline,
                            chunk_level=chunk_level,
                            task_scope="pipeline",
                            context_window=1,
                            segment_blocks=40,
                            segment_overlap=5,
                            limit=None,
                            sample=None,
                            workers=workers,
                            pdf_split_workers=pdf_split_workers,
                            epub_split_workers=epub_split_workers,
                            pdf_pages_per_job=pdf_pages_per_job,
                            epub_spine_items_per_job=epub_spine_items_per_job,
                            epub_extractor=selected_epub_extractor,
                            epub_unstructured_html_parser_version=selected_html_parser_version,
                            epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                            epub_unstructured_preprocess_mode=selected_preprocess_mode,
                            ocr_device=selected_ocr_device,
                            ocr_batch_size=ocr_batch_size,
                            warm_models=warm_models,
                            processed_output_root=processed_output_dir,
                            progress_callback=update_progress,
                            run_manifest_kind="bench_pred_run",
                        )
                    else:
                        import_result = run_labelstudio_import(
                            path=selected_source,
                            output_dir=output_dir,
                            pipeline=pipeline,
                            project_name=project_name,
                            chunk_level=chunk_level,
                            task_scope="pipeline",
                            context_window=1,
                            segment_blocks=40,
                            segment_overlap=5,
                            overwrite=overwrite,
                            resume=not overwrite,
                            label_studio_url=url or "",
                            label_studio_api_key=api_key or "",
                            limit=None,
                            sample=None,
                            progress_callback=update_progress,
                            workers=workers,
                            pdf_split_workers=pdf_split_workers,
                            epub_split_workers=epub_split_workers,
                            pdf_pages_per_job=pdf_pages_per_job,
                            epub_spine_items_per_job=epub_spine_items_per_job,
                            epub_extractor=selected_epub_extractor,
                            epub_unstructured_html_parser_version=selected_html_parser_version,
                            epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                            epub_unstructured_preprocess_mode=selected_preprocess_mode,
                            ocr_device=selected_ocr_device,
                            ocr_batch_size=ocr_batch_size,
                            warm_models=warm_models,
                            processed_output_root=processed_output_dir,
                            allow_labelstudio_write=True,
                        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    pred_run = _co_locate_prediction_run_for_benchmark(
        Path(import_result["run_root"]),
        eval_output_dir,
    )
    predicted = load_predicted_labeled_ranges(pred_run)
    gold = load_gold_freeform_ranges(selected_gold)
    eval_result = evaluate_predicted_vs_freeform(
        predicted,
        gold,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )
    report = eval_result["report"]
    report_md = format_freeform_eval_report_md(report)

    report_json_path = eval_output_dir / "eval_report.json"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_md_path = eval_output_dir / "eval_report.md"
    report_md_path.write_text(report_md, encoding="utf-8")
    write_jsonl(eval_output_dir / "missed_gold_spans.jsonl", eval_result["missed_gold"])
    write_jsonl(
        eval_output_dir / "false_positive_preds.jsonl",
        eval_result["false_positive_preds"],
    )

    pred_context = _load_pred_run_recipe_context(pred_run)
    benchmark_recipes = pred_context.recipes
    manifest_report_path = pred_context.processed_report_path
    processed_report_path = import_result.get("processed_report_path")
    csv_report_path = manifest_report_path
    if not csv_report_path and processed_report_path is not None:
        csv_report_path = str(processed_report_path)
    if benchmark_recipes is None and processed_report_path is not None:
        benchmark_recipes = _load_total_recipes_from_report_path(processed_report_path)

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    append_benchmark_csv(
        report,
        history_path(processed_output_dir),
        run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        run_dir=str(eval_output_dir),
        eval_scope="freeform-spans",
        source_file=str(selected_source),
        recipes=benchmark_recipes,
        processed_report_path=csv_report_path,
        run_config=pred_context.run_config,
        run_config_hash=pred_context.run_config_hash,
        run_config_summary=pred_context.run_config_summary,
        epub_auto_selected_score=pred_context.epub_auto_selected_score,
    )

    benchmark_run_config: dict[str, Any] = {
        "overlap_threshold": overlap_threshold,
        "force_source_match": force_source_match,
        "upload": not no_upload,
        "epub_extractor": selected_epub_extractor,
        "epub_unstructured_html_parser_version": selected_html_parser_version,
        "epub_unstructured_skip_headers_footers": selected_skip_headers_footers,
        "epub_unstructured_preprocess_mode": selected_preprocess_mode,
        "ocr_device": selected_ocr_device,
        "ocr_batch_size": ocr_batch_size,
        "workers": workers,
        "pdf_split_workers": pdf_split_workers,
        "epub_split_workers": epub_split_workers,
        "pdf_pages_per_job": pdf_pages_per_job,
        "epub_spine_items_per_job": epub_spine_items_per_job,
        "warm_models": warm_models,
    }
    if pred_context.run_config is not None:
        benchmark_run_config["prediction_run_config"] = pred_context.run_config
    if pred_context.run_config_hash:
        benchmark_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
    if pred_context.run_config_summary:
        benchmark_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

    benchmark_artifacts: dict[str, Any] = {
        "pred_run_dir": _path_for_manifest(eval_output_dir, pred_run),
        "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
        "eval_report_json": "eval_report.json",
        "eval_report_md": "eval_report.md",
        "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
        "false_positive_preds_jsonl": "false_positive_preds.jsonl",
        "history_csv": str(processed_output_dir / ".history" / "performance_history.csv"),
    }
    if csv_report_path:
        benchmark_artifacts["processed_report_json"] = _path_for_manifest(
            eval_output_dir,
            csv_report_path,
        )
    processed_run_root = import_result.get("processed_run_root")
    if processed_run_root:
        benchmark_artifacts["processed_output_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )

    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark",
        source_path=str(selected_source),
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=benchmark_run_config,
        artifacts=benchmark_artifacts,
        notes=(
            "Benchmark evaluation against freeform gold spans. "
            + ("Upload disabled." if no_upload else "Prediction tasks uploaded to Label Studio.")
        ),
    )

    typer.secho("Benchmark complete.", fg=typer.colors.GREEN)
    typer.secho(f"Gold spans: {selected_gold}", fg=typer.colors.CYAN)
    typer.secho(f"Prediction run: {pred_run}", fg=typer.colors.CYAN)
    if processed_run_root:
        typer.secho(f"Processed output: {processed_run_root}", fg=typer.colors.CYAN)
    typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)


@bench_app.command("validate")
def bench_validate(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
) -> None:
    """Validate a bench suite manifest (check source files and gold dirs exist)."""
    from cookimport.bench.suite import load_suite, validate_suite

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho(
        f"Suite '{s.name}' is valid ({len(s.items)} item(s)).",
        fg=typer.colors.GREEN,
    )


@bench_app.command("run")
def bench_run(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
    out_dir: Path = typer.Option(
        DEFAULT_BENCH_RUNS,
        "--out-dir",
        help="Output directory for bench runs.",
    ),
    baseline: Path | None = typer.Option(
        None, "--baseline", help="Previous run directory to compute deltas against."
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="Knob config JSON file."
    ),
) -> None:
    """Run the offline benchmark suite: generate predictions, evaluate, report."""
    from cookimport.bench.packet import build_iteration_packet
    from cookimport.bench.runner import run_suite
    from cookimport.bench.suite import load_suite, validate_suite

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Suite validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    config: dict | None = None
    if config_path and config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))

    try:
        with console.status(
            "[bold cyan]Running bench suite...[/bold cyan]", spinner="dots"
        ) as status:
            def update_progress(msg: str) -> None:
                status.update(f"[bold cyan]Bench: {msg}[/bold cyan]")

            run_root, agg_metrics = run_suite(
                s,
                out_dir,
                repo_root=REPO_ROOT,
                config=config,
                baseline_run_dir=baseline,
                progress_callback=update_progress,
            )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    # Build iteration packet
    build_iteration_packet(run_root, baseline_run_dir=baseline)
    bench_recipe_total = _sum_bench_recipe_count(run_root)

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    append_benchmark_csv(
        agg_metrics,
        history_path(DEFAULT_OUTPUT),
        run_timestamp=run_root.name,
        run_dir=str(run_root),
        eval_scope="bench-suite",
        source_file=s.name,
        recipes=bench_recipe_total,
        run_config=config,
    )

    typer.secho("Bench suite complete.", fg=typer.colors.GREEN)
    typer.secho(f"Report: {run_root / 'report.md'}", fg=typer.colors.CYAN)
    typer.secho(f"Metrics: {run_root / 'metrics.json'}", fg=typer.colors.CYAN)
    typer.secho(f"Packet: {run_root / 'iteration_packet'}", fg=typer.colors.CYAN)


@bench_app.command("sweep")
def bench_sweep(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
    out_dir: Path = typer.Option(
        DEFAULT_BENCH_RUNS,
        "--out-dir",
        help="Output directory for sweep runs.",
    ),
    budget: int = typer.Option(
        25, "--budget", min=1, help="Max number of sweep configurations to try."
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for sweep."),
    objective: str = typer.Option(
        "coverage", "--objective", help="Optimization objective (coverage or precision)."
    ),
) -> None:
    """Run a parameter sweep over the bench suite."""
    from cookimport.bench.suite import load_suite, validate_suite
    from cookimport.bench.sweep import run_sweep

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Suite validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        with console.status(
            "[bold cyan]Running parameter sweep...[/bold cyan]", spinner="dots"
        ) as status:
            def update_progress(msg: str) -> None:
                status.update(f"[bold cyan]Sweep: {msg}[/bold cyan]")

            sweep_root = run_sweep(
                s,
                out_dir,
                repo_root=REPO_ROOT,
                budget=budget,
                seed=seed,
                objective=objective,
                progress_callback=update_progress,
            )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    typer.secho("Sweep complete.", fg=typer.colors.GREEN)
    typer.secho(f"Results: {sweep_root}", fg=typer.colors.CYAN)


@bench_app.command("knobs")
def bench_knobs() -> None:
    """List all tunable knobs and their defaults."""
    from cookimport.bench.knobs import list_knobs

    knobs = list_knobs()
    if not knobs:
        typer.echo("No tunable knobs registered.")
        return
    for knob in knobs:
        bounds = f" bounds={knob.bounds}" if knob.bounds else ""
        choices = f" choices={list(knob.choices)}" if knob.choices else ""
        typer.echo(
            f"  {knob.name} ({knob.kind}) default={knob.default}{bounds}{choices}"
        )
        if knob.description:
            typer.secho(f"    {knob.description}", fg=typer.colors.BRIGHT_BLACK)


if __name__ == "__main__":
    app()
