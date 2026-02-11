from __future__ import annotations

import datetime as dt
import json
import logging
import multiprocessing
import os
import queue
import shutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Dict, Any, Annotated

import questionary
import typer
from prompt_toolkit.keys import Keys
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.text import Text

from cookimport.core.mapping_io import load_mapping_config, save_mapping_config
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.overrides_io import load_parsing_overrides
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.slug import slugify_name
from cookimport.core.timing import TimingStats, measure
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.ingest import run_labelstudio_import
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
from cookimport.plugins import registry
from cookimport.plugins import excel, text, epub, pdf, recipesage, paprika  # noqa: F401
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
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
console = Console()
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "input"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "output"
DEFAULT_INTERACTIVE_OUTPUT = DEFAULT_OUTPUT
DEFAULT_GOLDEN = Path(__file__).parent.parent / "data" / "golden"
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "cookimport.json"
BACK_ACTION = "__back__"


def _menu_select(
    message: str,
    *,
    choices: list[Any],
    menu_help: str | None = None,
    **kwargs: Any,
) -> Any:
    """Select helper with Backspace support for one-level menu back navigation."""
    if menu_help:
        typer.secho(menu_help, fg=typer.colors.BRIGHT_BLACK)
    question = questionary.select(
        message,
        choices=choices,
        instruction="(Enter to select, Backspace to go back)",
        **kwargs,
    )

    @question.application.key_bindings.add(Keys.Backspace, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=BACK_ACTION)

    return question.ask()


def _load_settings() -> Dict[str, Any]:
    """Load user settings from config file."""
    defaults = {
        "workers": 7,
        "pdf_split_workers": 7,
        "epub_split_workers": 7,
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
                    f"OCR Device: {current_settings.get('ocr_device', 'auto')} - auto/cpu/cuda/mps",
                    value="ocr_device",
                ),
                questionary.Choice(
                    f"OCR Batch Size: {current_settings.get('ocr_batch_size', 1)} - pages per OCR call",
                    value="ocr_batch_size",
                ),
                questionary.Choice(
                    f"Output Folder: {current_settings.get('output_dir', str(DEFAULT_INTERACTIVE_OUTPUT))} - stage/inspect artifacts",
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


def _interactive_mode(*, limit: int | None = None) -> None:
    """Run the interactive guided flow."""
    typer.secho("\n  Recipe Import Tool\n", fg=typer.colors.CYAN, bold=True)

    input_folder = DEFAULT_INPUT
    settings = _load_settings()

    while True:
        output_folder = Path(str(settings.get("output_dir") or DEFAULT_INTERACTIVE_OUTPUT)).expanduser()
        # Scan for importable files first to know what context to show
        importable_files = _list_importable_files(input_folder)

        choices = []
        if importable_files:
            choices.append(
                questionary.Choice(
                    "Import files from data/input - convert to RecipeSage outputs",
                    value="import",
                )
            )
            choices.append(
                questionary.Choice(
                    "Label Studio benchmark import - create labeling tasks from one source",
                    value="labelstudio",
                )
            )
        choices.append(
            questionary.Choice(
                "Label Studio export - pull finished labels into golden artifacts",
                value="labelstudio_export",
            )
        )
        choices.append(
            questionary.Choice(
                "Benchmark against labeled freeform export - run predictions + scoring",
                value="labelstudio_benchmark",
            )
        )
        choices.append(
            questionary.Choice(
                "Inspect a single file - preview inferred layout and confidence",
                value="inspect",
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
                "Choose a workflow. Import converts source files, Label Studio creates "
                "annotation tasks, Benchmark scores pipeline predictions against gold."
            ),
        )

        if action == BACK_ACTION:
            continue

        if action is None or action == "exit":
            raise typer.Exit(0)
            
        if action == "settings":
            _settings_menu(settings)
            continue

        if action == "inspect":
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
                "Select a file to inspect:",
                choices=file_choices,
                menu_help="Pick one source file to inspect parser layout guesses.",
            )

            if selected_file in {None, BACK_ACTION}:
                continue

            write_map = questionary.confirm(
                "Write a mapping file? (useful for customizing column mappings)",
                default=True,
            ).ask()

            if write_map is None:
                continue

            typer.echo()
            inspect(path=selected_file, out=output_folder, write_mapping=write_map)
            input("Press Enter to continue...")
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
            
            common_args = {
                "out": output_folder,
                "mapping": None,
                "overrides": None,
                "limit": limit,
                "workers": settings.get("workers", 7),
                "pdf_split_workers": settings.get("pdf_split_workers", 7),
                "epub_split_workers": settings.get("epub_split_workers", 7),
                "ocr_device": settings.get("ocr_device", "auto"),
                "ocr_batch_size": settings.get("ocr_batch_size", 1),
                "pdf_pages_per_job": settings.get("pdf_pages_per_job", 50),
                "epub_spine_items_per_job": settings.get("epub_spine_items_per_job", 10),
                "warm_models": settings.get("warm_models", False),
            }

            if selection == "all":
                run_folder = stage(path=input_folder, **common_args)
            else:
                run_folder = stage(path=selection, **common_args)

            typer.secho(f"\nOutputs written to: {run_folder}", fg=typer.colors.CYAN)
            break

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

            overwrite = questionary.confirm(
                "Overwrite existing project if it exists?",
                default=False,
            ).ask()

            if overwrite is None:
                continue

            allow_upload = questionary.confirm(
                "Upload tasks to Label Studio now?",
                default=False,
            ).ask()
            if allow_upload is not True:
                typer.secho("Label Studio upload cancelled.", fg=typer.colors.YELLOW)
                continue

            label_studio_url = os.getenv("LABEL_STUDIO_URL")
            label_studio_api_key = os.getenv("LABEL_STUDIO_API_KEY")

            if not label_studio_url:
                label_studio_url = questionary.text(
                    "Label Studio URL:",
                    default="http://localhost:8080",
                ).ask()
            if not label_studio_api_key:
                label_studio_api_key = questionary.password(
                    "Label Studio API key:",
                ).ask()

            url, api_key = _resolve_labelstudio_settings(
                label_studio_url, label_studio_api_key
            )

            try:
                result = run_labelstudio_import(
                    path=selected_file,
                    output_dir=DEFAULT_GOLDEN,
                    pipeline="auto",
                    project_name=project_name,
                    chunk_level=chunk_level,
                    task_scope=task_scope,
                    context_window=context_window,
                    segment_blocks=segment_blocks,
                    segment_overlap=segment_overlap,
                    overwrite=bool(overwrite),
                    resume=not overwrite,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    limit=None,
                    sample=None,
                    allow_labelstudio_write=True,
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
            typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
            break

        elif action == "labelstudio_export":
            project_name_raw = questionary.text(
                "Label Studio project name to export:",
                default="",
            ).ask()
            if project_name_raw is None:
                continue
            project_name = project_name_raw.strip()
            if not project_name:
                typer.secho("Project name is required for export.", fg=typer.colors.RED)
                continue

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

            target_output_dir = DEFAULT_GOLDEN

            label_studio_url = os.getenv("LABEL_STUDIO_URL")
            label_studio_api_key = os.getenv("LABEL_STUDIO_API_KEY")

            if not label_studio_url:
                label_studio_url = questionary.text(
                    "Label Studio URL:",
                    default="http://localhost:8080",
                ).ask()
            if not label_studio_api_key:
                label_studio_api_key = questionary.password(
                    "Label Studio API key:",
                ).ask()

            url, api_key = _resolve_labelstudio_settings(
                label_studio_url, label_studio_api_key
            )

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
            break

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
                    "How would you like to benchmark?",
                    menu_help=(
                        "Use eval-only when you already have prediction tasks. "
                        "Use upload only when you need to generate fresh predictions."
                    ),
                    choices=[
                        questionary.Choice(
                            "Score existing prediction run (no upload)",
                            value="eval-only",
                        ),
                        questionary.Choice(
                            "Generate fresh predictions + score (uploads to Label Studio)",
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

                labelstudio_eval(
                    scope="freeform-spans",
                    pred_run=Path(selected_pred_run),
                    gold_spans=Path(selected_gold),
                    output_dir=benchmark_eval_output,
                )
                break

            allow_upload = questionary.confirm(
                "Upload benchmark prediction tasks to Label Studio now?",
                default=False,
            ).ask()
            if allow_upload is not True:
                typer.secho(
                    "Benchmark upload cancelled. Select eval-only mode if you already have prediction runs.",
                    fg=typer.colors.YELLOW,
                )
                continue
            labelstudio_benchmark(
                output_dir=DEFAULT_GOLDEN,
                eval_output_dir=benchmark_eval_output,
                allow_labelstudio_write=True,
                workers=settings.get("workers", 7),
                pdf_split_workers=settings.get("pdf_split_workers", 7),
                epub_split_workers=settings.get("epub_split_workers", 7),
                pdf_pages_per_job=settings.get("pdf_pages_per_job", 50),
                epub_spine_items_per_job=settings.get("epub_spine_items_per_job", 10),
            )
            break


@app.callback()
def main(ctx: typer.Context) -> None:
    """Recipe Import - Convert Excel files to RecipeSage JSON-LD format."""
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


def _require_labelstudio_write_consent(allow_labelstudio_write: bool) -> None:
    if not allow_labelstudio_write:
        _fail(
            "Label Studio uploads are blocked by default. "
            "Re-run with --allow-labelstudio-write to push tasks."
        )


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
) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    for file_path in files:
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


def _write_error_report(out: Path, file_path: Path, run_dt: dt.datetime, errors: list[str]) -> None:
    report = ConversionReport(
        errors=errors,
        sourceFile=str(file_path),
        runTimestamp=run_dt.isoformat(timespec="seconds"),
    )
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
) -> dict[str, Any]:
    workbook_slug = slugify_name(file_path.stem)
    merge_stats = TimingStats()
    merge_start = time.monotonic()

    ordered_jobs = sorted(job_results, key=_job_range_start)
    merged_recipes: list[Any] = []
    merged_tip_candidates: list[Any] = []
    merged_topic_candidates: list[Any] = []
    merged_non_recipe_blocks: list[Any] = []
    warnings: list[str] = []
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
        if result.report:
            standalone_block_total += result.report.total_standalone_blocks
            standalone_topic_block_total += result.report.total_standalone_topic_blocks

    file_hash = compute_file_hash(file_path)
    sorted_recipes, _ = reassign_recipe_ids(
        merged_recipes,
        merged_tip_candidates,
        file_hash=file_hash,
        importer_name=importer_name,
    )
    tips, _, _ = partition_tip_candidates(merged_tip_candidates)

    report = ConversionReport(warnings=warnings)
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
    with measure(merge_stats, "writing"):
        intermediate_dir = out / "intermediate drafts" / workbook_slug
        final_dir = out / "final drafts" / workbook_slug
        tips_dir = out / "tips" / workbook_slug

        with measure(merge_stats, "write_intermediate_seconds"):
            write_intermediate_outputs(merged_result, intermediate_dir, output_stats=output_stats)
        with measure(merge_stats, "write_final_seconds"):
            write_draft_outputs(merged_result, final_dir, output_stats=output_stats)
        with measure(merge_stats, "write_tips_seconds"):
            write_tip_outputs(merged_result, tips_dir, output_stats=output_stats)
        with measure(merge_stats, "write_topic_candidates_seconds"):
            write_topic_candidate_outputs(merged_result, tips_dir, output_stats=output_stats)

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
    write_report(report, out, file_path.stem)

    _merge_raw_artifacts(out, workbook_slug, job_results)

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
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="pdf",
    )


def _merge_epub_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="epub",
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
) -> Path:
    """Stage recipes from a source file or folder.

    Outputs are organized as:
      {out}/{timestamp}/intermediate drafts/{filename}/  - RecipeSage JSON-LD
      {out}/{timestamp}/final drafts/{filename}/         - RecipeDraftV1 format
      {out}/{timestamp}/tips/{filename}/                 - Tip/knowledge snippets
      {out}/{timestamp}/reports/                         - Conversion reports
    """
    if not path.exists():
        _fail(f"Path not found: {path}")
    if mapping is not None and not mapping.exists():
        _fail(f"Mapping file not found: {mapping}")
    if overrides is not None and not overrides.exists():
        _fail(f"Overrides file not found: {overrides}")

    if warm_models:
        with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
            _warm_all_models(ocr_device=ocr_device)

    # Create timestamped output folder for this run
    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    out = out / timestamp
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
    base_mapping.ocr_device = ocr_device
    base_mapping.ocr_batch_size = ocr_batch_size
    if overrides is not None:
        base_mapping.parsing_overrides = load_parsing_overrides(overrides)

    imported = 0
    errors: list[str] = []
    all_epub = all(f.suffix.lower() == ".epub" for f in files_to_process)
    effective_workers = workers
    if all_epub and epub_split_workers > workers:
        effective_workers = epub_split_workers

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

    def handle_job_result(job: JobSpec, res: dict[str, Any], live: Live) -> None:
        nonlocal imported

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
                    _write_error_report(out, job.file_path, run_dt, reasons)
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
                        if job.split_kind == "epub":
                            merged = _merge_epub_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                            )
                        else:
                            merged = _merge_pdf_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
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
                            out, job.file_path, run_dt, [str(exc)]
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

            append_history_csv(summary.rows, history_path(DEFAULT_OUTPUT))
    except Exception as exc:
        logger.warning("Performance summary skipped: %s", exc)

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
) -> None:
    """Import a cookbook into Label Studio for pipeline, canonical, or freeform labeling."""
    _require_labelstudio_write_consent(allow_labelstudio_write)
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
    try:
        with console.status(f"[bold cyan]Running Label Studio import for {path.name}...[/bold cyan]", spinner="dots") as status:
            def update_progress(msg: str) -> None:
                status.update(f"[bold cyan]Label Studio import ({path.name}): {msg}[/bold cyan]")

            result = run_labelstudio_import(
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
                allow_labelstudio_write=True,
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
    """Export labeled tasks from Label Studio into golden set JSONL."""
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
    overlap_threshold: float = typer.Option(
        0.5,
        "--overlap-threshold",
        min=0.0,
        max=1.0,
        help="Jaccard overlap threshold for matching.",
    ),
    force_source_match: bool = typer.Option(
        False,
        "--force-source-match",
        help=(
            "Ignore source hash/file identity when matching spans. "
            "Useful for comparing renamed/truncated source variants."
        ),
    ),
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

    typer.secho(
        f"Evaluation complete. Report: {report_md_path}",
        fg=typer.colors.GREEN,
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
        help="Explicitly allow writing prediction tasks to Label Studio.",
    )] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite/--resume", help="Overwrite prediction project or resume.")] = False,
    label_studio_url: Annotated[str | None, typer.Option("--label-studio-url", help="Label Studio base URL.")] = None,
    label_studio_api_key: Annotated[str | None, typer.Option("--label-studio-api-key", help="Label Studio API key.")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Number of parallel worker processes for prediction import.")] = 7,
    pdf_split_workers: Annotated[int, typer.Option("--pdf-split-workers", min=1, help="Max workers used when splitting a PDF prediction import.")] = 7,
    epub_split_workers: Annotated[int, typer.Option("--epub-split-workers", min=1, help="Max workers used when splitting an EPUB prediction import.")] = 7,
    pdf_pages_per_job: Annotated[int, typer.Option("--pdf-pages-per-job", min=1, help="Target page count per PDF split job.")] = 50,
    epub_spine_items_per_job: Annotated[int, typer.Option("--epub-spine-items-per-job", min=1, help="Target spine items per EPUB split job.")] = 10,
) -> None:
    """Run one-shot benchmark: pipeline predictions vs freeform labeled gold spans."""
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

    try:
        with console.status(
            f"[bold cyan]Generating prediction tasks for {selected_source.name}...[/bold cyan]",
            spinner="dots",
        ) as status:
            def update_progress(msg: str) -> None:
                status.update(
                    f"[bold cyan]Benchmark import ({selected_source.name}): {msg}[/bold cyan]"
                )

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
                label_studio_url=url,
                label_studio_api_key=api_key,
                limit=None,
                sample=None,
                progress_callback=update_progress,
                workers=workers,
                pdf_split_workers=pdf_split_workers,
                epub_split_workers=epub_split_workers,
                pdf_pages_per_job=pdf_pages_per_job,
                epub_spine_items_per_job=epub_spine_items_per_job,
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

    typer.secho("Benchmark complete.", fg=typer.colors.GREEN)
    typer.secho(f"Gold spans: {selected_gold}", fg=typer.colors.CYAN)
    typer.secho(f"Prediction run: {pred_run}", fg=typer.colors.CYAN)
    processed_run_root = import_result.get("processed_run_root")
    if processed_run_root:
        typer.secho(f"Processed output: {processed_run_root}", fg=typer.colors.CYAN)
    typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)


if __name__ == "__main__":
    app()
