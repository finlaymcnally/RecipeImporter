from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from .command_resolution import resolve_registered_command
from .bench_single_book import (
    _build_single_book_interactive_shard_recommendations,
)

runtime = sys.modules["cookimport.cli_support"]
from cookimport.cli_support.bench import (
    INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS,
    INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS,
    INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK,
)

# Snapshot the fully initialized root support namespace so these moved
# flow/progress helpers can keep their unqualified references.
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _stats_dashboard_command():
    return resolve_registered_command(
        "cookimport.cli_commands.analytics", "stats_dashboard"
    )


def _stage_command():
    return resolve_registered_command("cookimport.cli_commands.stage", "stage")


def _resolve_interactive_benchmark_preset_gold(
    *,
    preset_id: str,
    output_dir: Path,
) -> Path | None:
    normalized_preset_id = str(preset_id or "").strip().lower()
    if (
        normalized_preset_id
        != INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST
    ):
        return None
    target_display = "saltfatacidheatcutdown"
    for path in _discover_freeform_gold_exports(output_dir):
        display_label = _display_gold_export_path(path, output_dir).strip().lower()
        if display_label == target_display:
            return path
    return None


def _interactive_benchmark_preset_summary(preset_id: str) -> str:
    normalized_preset_id = str(preset_id or "").strip().lower()
    if (
        normalized_preset_id
        == INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST
    ):
        return (
            "saltfatacidheatcutdown fast Codex Exec "
            "(block labelling + recipe + knowledge, 5/5/5, "
            "gpt-5.3-codex-spark, low)"
        )
    return normalized_preset_id or "interactive benchmark preset"


def _format_interactive_target_size(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        size_bytes = int(path.stat().st_size)
    except OSError:
        return None
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.1f} KB"
    return f"{size_bytes} B"


def _build_import_codex_target_context(
    *,
    selection: object,
    input_folder: Path,
) -> dict[str, object]:
    if selection == "all":
        return {
            "title": "Target: all supported input files",
            "summary_lines": [
                f"Input root: {input_folder}",
                "Exact survivability recommendations are deferred until each book is deterministically planned.",
            ],
        }
    if isinstance(selection, Path):
        size_text = _format_interactive_target_size(selection)
        summary_lines = [f"Source: {selection.name}"]
        if size_text:
            summary_lines.append(f"Source size: {size_text}")
        return {
            "title": f"Target: {selection.name}",
            "summary_lines": summary_lines,
        }
    return {
        "title": "Target: import run",
        "summary_lines": [f"Input root: {input_folder}"],
    }


def _build_single_book_benchmark_codex_target_context(
    *,
    gold_spans: Path,
    source_file: Path,
    golden_root: Path,
    recommendations_builder: object | None = None,
) -> dict[str, object]:
    source_size = _format_interactive_target_size(source_file)
    summary_lines = [
        f"Gold: {_display_gold_export_path(gold_spans, golden_root)}",
        f"Source: {source_file.name}",
    ]
    if source_size:
        summary_lines.append(f"Source size: {source_size}")
    context: dict[str, object] = {
        "title": f"Target: {source_file.name}",
        "summary_lines": summary_lines,
    }
    if recommendations_builder is not None:
        context["recommendations_builder"] = recommendations_builder
    return context

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
                    "Stage: Convert files from data/input into cookbook outputs",
                    value="import",
                )
            )
            choices.append(
                questionary.Choice(
                    "Label Studio upload: Create labeling tasks (uploads)",
                    value="labelstudio",
                )
            )
        choices.append(
            questionary.Choice(
                "Label Studio export: Export completed labels into golden artifacts",
                value="labelstudio_export",
            )
        )
        choices.append(
            questionary.Choice(
                "Evaluate vs freeform gold: Generate predictions and compare to your labels",
                value="labelstudio_benchmark",
            )
        )
        choices.append(
            questionary.Choice(
                "Dashboard: Build lifetime stats dashboard HTML",
                value="generate_dashboard",
            )
        )
        choices.append(
            questionary.Choice(
                "Settings: Change saved interactive defaults",
                value="settings",
            )
        )
        choices.append(questionary.Choice("Exit: Close the tool", value="exit"))

        action = _menu_select(
            "What would you like to do?",
            choices=choices,
            menu_help=(
                "Pick a workflow. Stage converts files into cookbook outputs. Label Studio upload "
                "creates annotation tasks. Export pulls completed labels into golden artifacts. "
                "Evaluate runs predictions and compares them against freeform gold. Dashboard "
                "builds a static lifetime summary."
            ),
        )

        if action == BACK_ACTION:
            continue

        if action is None or action == "exit":
            raise typer.Exit(0)

        if action == "generate_dashboard":
            typer.secho(
                f"Generating dashboard from {output_folder}...",
                fg=typer.colors.CYAN,
            )
            _stats_dashboard_command()(
                output_root=output_folder,
                golden_root=DEFAULT_GOLDEN,
                out_dir=history_root_for_output(output_folder) / "dashboard",
                open_browser=False,
                since_days=None,
                scan_reports=False,
            )
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
                    questionary.Choice(
                        "Import all: Process every supported file",
                        value="all",
                    ),
                    *[questionary.Choice(f.name, value=f) for f in importable_files]
                ]
            )

            if selection in {None, BACK_ACTION}:
                continue

            typer.echo()

            global_run_settings = RunSettings.from_dict(
                _run_settings_payload_from_settings(settings),
                warn_context="interactive global settings",
            )
            selected_run_settings = choose_run_settings(
                global_defaults=global_run_settings,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
                prompt_confirm=_prompt_confirm,
                prompt_text=_prompt_text,
                prompt_codex_ai_settings=True,
                prompt_recipe_pipeline_menu=True,
                interactive_codex_surface_options=("recipe", "knowledge"),
                interactive_codex_target_context=_build_import_codex_target_context(
                    selection=selection,
                    input_folder=input_folder,
                ),
            )
            if selected_run_settings is None:
                typer.secho("Import cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                f"Run settings hash: {selected_run_settings.short_hash()}",
                fg=typer.colors.CYAN,
            )

            # Apply EPUB settings via env vars (read at call time by epub.py).
            os.environ["C3IMP_EPUB_EXTRACTOR"] = selected_run_settings.epub_extractor.value
            _set_epub_unstructured_env(
                html_parser_version=selected_run_settings.epub_unstructured_html_parser_version.value,
                skip_headers_footers=selected_run_settings.epub_unstructured_skip_headers_footers,
                preprocess_mode=selected_run_settings.epub_unstructured_preprocess_mode.value,
            )

            common_args = build_stage_call_kwargs_from_run_settings(
                selected_run_settings,
                out=output_folder,
                mapping=None,
                overrides=None,
                limit=limit,
                write_markdown=True,
            )
            common_args["allow_codex"] = codex_surfaces_enabled(
                selected_run_settings.to_run_config_dict()
            )

            if selection == "all":
                run_folder = _stage_command()(path=input_folder, **common_args)
            else:
                run_folder = _stage_command()(path=selection, **common_args)

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

            project_name = _prompt_text(
                "Project name (leave blank to auto-name):",
                default="",
            )
            if project_name is None:
                continue
            if project_name is not None:
                project_name = project_name.strip() or None

            # Label Studio import is freeform-only.
            segment_blocks = 40
            segment_overlap = 5
            segment_focus_blocks = 40
            target_task_count: int | None = None
            prelabel = False
            prelabel_provider = "codex-farm"
            prelabel_timeout_seconds = DEFAULT_PRELABEL_TIMEOUT_SECONDS
            prelabel_cache_dir: Path | None = None
            prelabel_workers = 15
            prelabel_upload_as = "annotations"
            prelabel_granularity = PRELABEL_GRANULARITY_SPAN
            prelabel_allow_partial = False
            codex_cmd: str | None = None
            codex_model: str | None = None
            codex_reasoning_effort: str | None = None
            prelabel_track_token_usage = True

            freeform_segment_settings = _prompt_freeform_segment_settings(
                segment_blocks_default=segment_blocks,
                segment_overlap_default=segment_overlap,
                segment_focus_blocks_default=segment_focus_blocks,
                target_task_count_default=target_task_count,
            )
            if freeform_segment_settings is None:
                continue
            (
                segment_blocks,
                segment_overlap,
                segment_focus_blocks,
                target_task_count,
            ) = freeform_segment_settings
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
                        "strict annotations (recommended) - fail upload if any prelabel task fails",
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
                prelabel_granularity = PRELABEL_GRANULARITY_SPAN
                typer.secho(
                    "AI prelabel labeling style: actual freeform row spans.",
                    fg=typer.colors.CYAN,
                )
                codex_cmd = default_codex_cmd()
                resolved_account = codex_account_summary(codex_cmd)
                if resolved_account:
                    typer.secho(
                        f"Prelabel account: {resolved_account}",
                        fg=typer.colors.CYAN,
                    )
                else:
                    typer.secho(
                        "Prelabel account: unavailable for selected command.",
                        fg=typer.colors.YELLOW,
                    )

                detected_model = default_codex_model(cmd=codex_cmd)
                detected_label = detected_model or "pipeline/default model"
                discovered_models = list_codex_models(cmd=codex_cmd)
                supported_efforts_by_model: dict[str, tuple[str, ...]] = {}
                model_choices: list[QuestionaryChoice] = [
                    questionary.Choice(
                        f"use Codex default ({detected_label})",
                        value="__default__",
                    )
                ]
                seen_model_ids: set[str] = set()
                for entry in discovered_models:
                    model_id = str(entry.get("slug") or "").strip()
                    if not model_id or model_id in seen_model_ids:
                        continue
                    description = str(entry.get("description") or "").strip()
                    label = model_id if not description else f"{model_id} - {description}"
                    model_choices.append(questionary.Choice(label, value=model_id))
                    raw_supported_efforts = entry.get("supported_reasoning_efforts")
                    if isinstance(raw_supported_efforts, list):
                        normalized_supported_efforts: list[str] = []
                        for raw_effort in raw_supported_efforts:
                            if not isinstance(raw_effort, str):
                                continue
                            try:
                                normalized_effort = normalize_codex_reasoning_effort(
                                    raw_effort
                                )
                            except ValueError:
                                continue
                            if (
                                normalized_effort
                                and normalized_effort
                                not in normalized_supported_efforts
                            ):
                                normalized_supported_efforts.append(normalized_effort)
                        if normalized_supported_efforts:
                            supported_efforts_by_model[model_id] = tuple(
                                normalized_supported_efforts
                            )
                    seen_model_ids.add(model_id)
                model_choices.append(
                    questionary.Choice("custom model id...", value="__custom__")
                )
                model_choice = _menu_select(
                    "Codex model for AI prelabeling:",
                    menu_help=(
                        "Pick a model explicitly for this run, or leave it on the "
                        "pipeline/default model."
                    ),
                    choices=model_choices,
                )
                if model_choice in {None, BACK_ACTION}:
                    continue
                if model_choice == "__custom__":
                    custom_default = detected_model or ""
                    custom_model = _prompt_text(
                        "Codex model id:",
                        default=custom_default,
                    )
                    if custom_model is None:
                        continue
                    codex_model = custom_model.strip() or None
                elif model_choice == "__default__":
                    codex_model = None
                else:
                    codex_model = str(model_choice)

                selected_model = (codex_model or detected_model or "").strip()
                allowed_efforts = [
                    effort
                    for effort in CODEX_REASONING_EFFORT_VALUES
                    if effort != "minimal"
                ]
                model_supported_efforts = (
                    supported_efforts_by_model.get(selected_model)
                    if selected_model
                    else None
                )
                if model_supported_efforts:
                    supported_set = set(model_supported_efforts)
                    allowed_efforts = [
                        effort for effort in allowed_efforts if effort in supported_set
                    ]

                detected_effort = codex_reasoning_effort_from_cmd(
                    codex_cmd
                ) or default_codex_reasoning_effort(cmd=codex_cmd)
                detected_effort_label = detected_effort or "config default"
                effort_description = {
                    "none": "disable extra reasoning",
                    "minimal": "lightest reasoning",
                    "low": "low reasoning budget",
                    "medium": "balanced reasoning",
                    "high": "deeper reasoning",
                    "xhigh": "maximum reasoning",
                }
                effort_choices: list[QuestionaryChoice] = []
                if detected_effort is None or detected_effort in allowed_efforts:
                    effort_choices.append(
                        questionary.Choice(
                            f"use Codex default ({detected_effort_label})",
                            value="__default_effort__",
                        )
                    )
                else:
                    typer.secho(
                        (
                            f"Codex default thinking effort '{detected_effort}' "
                            "is incompatible with this model/workflow."
                        ),
                        fg=typer.colors.YELLOW,
                    )
                for effort in allowed_efforts:
                    detail = effort_description.get(effort, "")
                    label = effort if not detail else f"{effort} - {detail}"
                    effort_choices.append(
                        questionary.Choice(label, value=effort)
                    )
                if not effort_choices:
                    typer.secho(
                        "No compatible Codex thinking effort options are available.",
                        fg=typer.colors.RED,
                    )
                    continue
                effort_choice = _menu_select(
                    "Codex thinking effort for AI prelabeling:",
                    menu_help=(
                        "Pick a reasoning effort for this run "
                        "(Codex config: model_reasoning_effort). "
                        "Minimal is hidden due Codex tool requirements."
                    ),
                    choices=effort_choices,
                )
                if effort_choice in {None, BACK_ACTION}:
                    continue
                if effort_choice == "__default_effort__":
                    codex_reasoning_effort = None
                else:
                    codex_reasoning_effort = str(effort_choice)

            # Interactive flow always recreates the project if it exists.
            overwrite = True

            resolved_creds = _resolve_interactive_labelstudio_settings(settings)
            if resolved_creds is None:
                continue
            url, api_key = resolved_creds
            interactive_import_timeseries_path = _processing_timeseries_history_path(
                root=_golden_sent_to_labelstudio_root(),
                scope="labelstudio_import",
                source_name=selected_file.name,
            )

            import_started_at = time.monotonic()
            try:
                result = _run_labelstudio_import_with_status(
                    source_name=selected_file.name,
                    telemetry_path=interactive_import_timeseries_path,
                    run_import=lambda update_progress: run_labelstudio_import(
                        path=selected_file,
                        output_dir=_golden_sent_to_labelstudio_root(),
                        pipeline="auto",
                        project_name=project_name,
                        segment_blocks=segment_blocks,
                        segment_overlap=segment_overlap,
                        segment_focus_blocks=segment_focus_blocks,
                        target_task_count=target_task_count,
                        overwrite=overwrite,
                        resume=False,
                        label_studio_url=url,
                        label_studio_api_key=api_key,
                        limit=None,
                        sample=None,
                        progress_callback=update_progress,
                        prelabel=prelabel,
                        prelabel_provider=prelabel_provider,
                        codex_cmd=codex_cmd,
                        codex_model=codex_model,
                        codex_reasoning_effort=codex_reasoning_effort,
                        prelabel_timeout_seconds=prelabel_timeout_seconds,
                        prelabel_cache_dir=prelabel_cache_dir,
                        prelabel_workers=prelabel_workers,
                        prelabel_upload_as=prelabel_upload_as,
                        prelabel_granularity=prelabel_granularity,
                        prelabel_allow_partial=prelabel_allow_partial,
                        prelabel_track_token_usage=prelabel_track_token_usage,
                        allow_labelstudio_write=True,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))
            processing_time_seconds = max(0.0, time.monotonic() - import_started_at)

            typer.secho(
                f"Label Studio project: {result['project_name']} (id={result['project_id']})",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                f"Tasks created: {result['tasks_total']} (uploaded {result['tasks_uploaded']})",
                fg=typer.colors.CYAN,
            )
            typer.secho(
                f"Processing time: {_format_processing_time(processing_time_seconds)}",
                fg=typer.colors.CYAN,
            )
            typer.secho(
                f"Processing telemetry: {interactive_import_timeseries_path}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            if prelabel:
                _print_prelabel_completion_summary(
                    prelabel_summary=result.get("prelabel") or {},
                    report_path=result.get("prelabel_report_path"),
                    inline_annotation_fallback=bool(
                        result.get("prelabel_inline_annotations_fallback")
                    ),
                )
            typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio_export":
            target_output_dir = _golden_pulled_from_labelstudio_root()

            resolved_creds = _resolve_interactive_labelstudio_settings(settings)
            if resolved_creds is None:
                continue
            url, api_key = resolved_creds
            project_name, detected_scope = _select_export_project(
                label_studio_url=url,
                label_studio_api_key=api_key,
            )
            if not project_name:
                continue
            if detected_scope:
                typer.secho(
                    f"Detected project type: {detected_scope}",
                    fg=typer.colors.BRIGHT_BLACK,
                )

            try:
                result = run_labelstudio_export(
                    project_name=project_name,
                    output_dir=target_output_dir,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    run_dir=None,
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))

            typer.secho(
                f"Export complete. Summary: {result['summary_path']}",
                fg=typer.colors.GREEN,
            )
            continue

        elif action == "labelstudio_benchmark":
            benchmark_eval_output = (
                _golden_benchmark_root()
                / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
            )

            benchmark_mode = _menu_select(
                "How would you like to evaluate?",
                menu_help=(
                    "All modes are offline (no upload).\n"
                    "Single book runs one local prediction + eval vs freeform gold.\n"
                    "Salt Fat Acid Heat preset jumps straight to one saved fast Codex Exec single-book run.\n"
                    "Selected matched books lets you pick specific books.\n"
                    "All matched books repeats that same config across each matched golden set."
                ),
                choices=[
                    questionary.Choice(
                        "Single Book: One local prediction + eval vs freeform gold",
                        value=INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK,
                    ),
                    questionary.Choice(
                        (
                            "Salt Fat Acid Heat preset: "
                            "Fast Codex Exec single-book benchmark"
                        ),
                        value=INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST,
                    ),
                    questionary.Choice(
                        "Selected Matched Books: Pick which matched books to run",
                        value=INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS,
                    ),
                    questionary.Choice(
                        "All Matched Books: Repeat one config for every matched golden set",
                        value=INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS,
                    ),
                ],
            )
            if benchmark_mode in {None, BACK_ACTION}:
                continue

            benchmark_defaults_payload = {
                key: value
                for key, value in settings.items()
                if key in RunSettings.model_fields
            }
            benchmark_defaults = RunSettings.from_dict(
                benchmark_defaults_payload,
                warn_context="interactive benchmark global settings",
            )
            preset_gold_spans: Path | None = None
            resolved_single_book_inputs: tuple[Path, Path] | None = None
            if (
                benchmark_mode
                == INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST
            ):
                selected_benchmark_settings = build_interactive_benchmark_preset_settings(
                    preset_id=benchmark_mode,
                    global_defaults=benchmark_defaults,
                    output_dir=output_folder,
                )
                preset_gold_spans = _resolve_interactive_benchmark_preset_gold(
                    preset_id=benchmark_mode,
                    output_dir=DEFAULT_GOLDEN,
                )
                if preset_gold_spans is None:
                    typer.secho(
                        (
                            "Benchmark cancelled. Could not find a freeform gold export "
                            "labeled `saltfatacidheatcutdown`."
                        ),
                        fg=typer.colors.YELLOW,
                    )
                    continue
                typer.secho(
                    (
                        "Using benchmark preset: "
                        f"{_interactive_benchmark_preset_summary(benchmark_mode)}"
                    ),
                    fg=typer.colors.CYAN,
                )
            else:
                if benchmark_mode == INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK:
                    resolved_single_book_inputs = _resolve_benchmark_gold_and_source(
                        gold_spans=None,
                        source_file=None,
                        output_dir=DEFAULT_GOLDEN,
                        allow_cancel=True,
                    )
                    if resolved_single_book_inputs is None:
                        typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                        continue

                single_book_recommendations_builder = None
                if resolved_single_book_inputs is not None:
                    single_book_source = resolved_single_book_inputs[1]

                    def _recommendations_builder(
                        selected_settings: RunSettings,
                        _selected_step_ids: Sequence[str],
                    ) -> dict[str, dict[str, object]]:
                        typer.secho(
                            (
                                "Preparing deterministic shard survivability "
                                f"suggestions for {single_book_source.name}..."
                            ),
                            fg=typer.colors.CYAN,
                        )
                        try:
                            return _build_single_book_interactive_shard_recommendations(
                                source_file=single_book_source,
                                selected_settings=selected_settings,
                                processed_output_root=output_folder,
                            )
                        except Exception as exc:  # noqa: BLE001
                            typer.secho(
                                (
                                    "Interactive shard survivability preview unavailable; "
                                    f"using generic guidance instead: {exc}"
                                ),
                                fg=typer.colors.YELLOW,
                            )
                            return {}

                    single_book_recommendations_builder = _recommendations_builder

                selected_benchmark_settings = choose_run_settings(
                    global_defaults=benchmark_defaults,
                    output_dir=output_folder,
                    menu_select=_menu_select,
                    back_action=BACK_ACTION,
                    prompt_confirm=_prompt_confirm,
                    prompt_text=_prompt_text,
                    prompt_codex_ai_settings=True,
                    prompt_recipe_pipeline_menu=True,
                    prompt_benchmark_llm_surface_toggles=True,
                    interactive_codex_target_context=(
                        _build_single_book_benchmark_codex_target_context(
                            gold_spans=resolved_single_book_inputs[0],
                            source_file=resolved_single_book_inputs[1],
                            golden_root=DEFAULT_GOLDEN,
                            recommendations_builder=(
                                single_book_recommendations_builder
                            ),
                        )
                        if resolved_single_book_inputs is not None
                        else None
                    ),
                )
                if selected_benchmark_settings is None:
                    typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                    continue

            typer.secho(
                f"Run settings hash: {selected_benchmark_settings.short_hash()}",
                fg=typer.colors.CYAN,
            )

            benchmark_write_markdown = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_WRITE_MARKDOWN_ENV),
                default=True,
            )
            benchmark_write_labelstudio_tasks = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS_ENV),
                default=False,
            )
            benchmark_write_single_book_starter_pack = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_SINGLE_BOOK_WRITE_STARTER_PACK_ENV),
                default=False,
            )

            if benchmark_mode in {
                INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK,
                INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST,
            }:
                _interactive_single_book_benchmark(
                    selected_benchmark_settings=selected_benchmark_settings,
                    benchmark_eval_output=benchmark_eval_output,
                    processed_output_root=output_folder,
                    golden_root=DEFAULT_GOLDEN,
                    write_markdown=benchmark_write_markdown,
                    write_label_studio_tasks=benchmark_write_labelstudio_tasks,
                    write_starter_pack=benchmark_write_single_book_starter_pack,
                    preselected_gold_spans=(
                        preset_gold_spans
                        if preset_gold_spans is not None
                        else (
                            resolved_single_book_inputs[0]
                            if resolved_single_book_inputs is not None
                            else None
                        )
                    ),
                    preselected_source_file=(
                        resolved_single_book_inputs[1]
                        if resolved_single_book_inputs is not None
                        else None
                    ),
                )
            elif benchmark_mode in {
                INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS,
                INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS,
            }:
                _interactive_single_profile_all_matched_benchmark(
                    selected_benchmark_settings=selected_benchmark_settings,
                    benchmark_eval_output=benchmark_eval_output,
                    processed_output_root=output_folder,
                    golden_root=DEFAULT_GOLDEN,
                    write_markdown=benchmark_write_markdown,
                    write_label_studio_tasks=benchmark_write_labelstudio_tasks,
                    allow_subset_selection=(
                        benchmark_mode
                        == INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS
                    ),
                )
            continue

__all__ = ['_interactive_mode']
