from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionResult, MappingConfig
from cookimport.core.reporting import build_authoritative_stage_report
from cookimport.core.slug import slugify_name
from cookimport.core.source_model import write_source_model_artifacts
from cookimport.core.timing import TimingStats, measure
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks
from cookimport.parsing.label_source_of_truth import LabelFirstStageResult
from cookimport.staging.import_session_contracts import StageImportSessionResult
from cookimport.staging.import_session_flows.authority import (
    _write_label_first_artifacts,
)
from cookimport.staging.import_session_flows.reporting import _notify_stage_progress
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.staging.pipeline_runtime import (
    ExtractedBookBundle,
    NonrecipeFinalizeResult,
    NonrecipeRouteResult,
    RecipeBoundaryResult,
    RecipeRefineResult,
    build_extracted_book_bundle,
    run_nonrecipe_finalize_stage,
    run_nonrecipe_route_stage,
    run_recipe_refine_stage,
)
from cookimport.staging.recipe_tag_normalization import (
    normalize_conversion_result_recipe_tags,
)
from cookimport.staging.writer import OutputStats


def _runtime():
    from cookimport.staging import import_session as runtime

    return runtime


def execute_stage_import_session_from_result(
    *,
    result: ConversionResult,
    source_file: Path,
    run_root: Path,
    run_dt: dt.datetime,
    importer_name: str,
    run_settings: RunSettings,
    run_config: dict[str, Any] | None,
    run_config_hash: str | None,
    run_config_summary: str | None,
    mapping_config: MappingConfig | None = None,
    write_markdown: bool = True,
    progress_callback: Callable[[str], None] | None = None,
    timing_stats: TimingStats | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    write_raw_artifacts_enabled: bool = True,
    count_diagnostics_path: Path | None = None,
    output_stats: OutputStats | None = None,
    recipe_limit: int | None = None,
    recipe_limit_label: int | None = None,
) -> StageImportSessionResult:
    runtime = _runtime()
    stats = timing_stats or TimingStats()
    workbook_slug = slugify_name(source_file.stem)
    parsing_overrides = (
        mapping_config.parsing_overrides
        if mapping_config is not None and mapping_config.parsing_overrides
        else None
    )

    authoritative_recipe_payloads_by_recipe_id: dict[str, Any] = {}
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
    label_first_result: LabelFirstStageResult | None = None
    label_artifact_paths: dict[str, Path] | None = None
    source_artifact_paths: dict[str, Path] | None = None
    nonrecipe_stage_result: NonRecipeStageResult | None = None
    live_llm_allowed = bool((run_config or {}).get("codex_execution_live_llm_allowed"))
    extracted_book_bundle: ExtractedBookBundle | None = None
    recipe_boundary_result: RecipeBoundaryResult | None = None
    recipe_refine_result: RecipeRefineResult | None = None
    nonrecipe_route_result: NonrecipeRouteResult | None = None
    nonrecipe_finalize_result: NonrecipeFinalizeResult | None = None

    extracted_book_bundle = build_extracted_book_bundle(
        result=result,
        source_file=source_file,
        importer_name=importer_name,
        full_blocks=full_blocks,
    )

    _notify_stage_progress(
        progress_callback,
        message="Building authoritative labels...",
        stage_label="authoritative labels",
        task_current=0,
        task_total=4,
    )
    with measure(stats, "label_source_of_truth_seconds"):
        recipe_boundary_result = runtime.run_recipe_boundary_stage(
            extracted_bundle=extracted_book_bundle,
            run_settings=run_settings,
            artifact_root=run_root,
            live_llm_allowed=live_llm_allowed,
            progress_callback=progress_callback,
        )
    label_first_result = recipe_boundary_result.label_first_result
    result = recipe_boundary_result.conversion_result
    label_artifact_paths = _write_label_first_artifacts(
        run_root=run_root,
        workbook_slug=workbook_slug,
        label_first_result=label_first_result,
        line_role_pipeline=str(getattr(run_settings.line_role_pipeline, "value", "off")),
    )

    if run_settings.llm_recipe_pipeline.value != "off":
        _notify_stage_progress(
            progress_callback,
            message="Running codex-farm recipe pipeline...",
            stage_label="recipe pipeline",
        )
    with measure(stats, "recipe_refine_seconds"):
        recipe_refine_result = run_recipe_refine_stage(
            recipe_boundary_result=recipe_boundary_result,
            run_settings=run_settings,
            run_root=run_root,
            run_config=run_config,
            progress_callback=progress_callback,
        )
    result = recipe_refine_result.conversion_result
    authoritative_recipe_payloads_by_recipe_id = dict(
        recipe_refine_result.authoritative_recipe_payloads_by_recipe_id
    )
    llm_report = dict(recipe_refine_result.llm_report)

    with measure(stats, "nonrecipe_route_seconds"):
        nonrecipe_route_result = run_nonrecipe_route_stage(
            recipe_boundary_result=recipe_boundary_result,
            recipe_refine_result=recipe_refine_result,
            overrides=parsing_overrides,
        )
    nonrecipe_stage_result = nonrecipe_route_result.stage_result

    if run_settings.llm_knowledge_pipeline.value != "off":
        _notify_stage_progress(
            progress_callback,
            message="Running codex-farm non-recipe finalize...",
            stage_label="non-recipe finalize",
        )
    with measure(stats, "nonrecipe_finalize_seconds"):
        nonrecipe_finalize_result = run_nonrecipe_finalize_stage(
            nonrecipe_route_result=nonrecipe_route_result,
            run_settings=run_settings,
            run_root=run_root,
            overrides=parsing_overrides,
            progress_callback=progress_callback,
        )
    nonrecipe_stage_result = nonrecipe_finalize_result.stage_result
    if nonrecipe_finalize_result.llm_report is not None:
        llm_report["knowledge"] = dict(nonrecipe_finalize_result.llm_report)

    nonrecipe_block_rows = list(nonrecipe_finalize_result.late_output_nonrecipe_blocks)

    extracted_tables = []
    if nonrecipe_block_rows:
        _notify_stage_progress(
            progress_callback,
            message="Extracting knowledge tables...",
            stage_label="extracting knowledge tables",
            detail_lines=[f"non-recipe blocks: {len(nonrecipe_block_rows)}"],
        )
        extracted_tables = runtime.extract_and_annotate_tables(
            nonrecipe_block_rows,
            source_hash=extracted_book_bundle.source_hash,
        )

    if run_settings.llm_knowledge_pipeline.value == "off":
        chunk_detail_lines = [f"non-recipe blocks: {len(nonrecipe_block_rows)}"]
        _notify_stage_progress(
            progress_callback,
            message="Generating deterministic non-recipe chunks...",
            stage_label="knowledge chunk generation",
            detail_lines=chunk_detail_lines,
        )
        if nonrecipe_block_rows:
            result.chunks = chunks_from_non_recipe_blocks(
                nonrecipe_block_rows,
                overrides=parsing_overrides,
            )
        else:
            result.chunks = []
    else:
        result.chunks = []

    # ConversionResult keeps only strict final non-recipe authority. Late outputs may
    # use a broader routed candidate queue when non-recipe finalize did not run.
    result.non_recipe_blocks = list(nonrecipe_finalize_result.authoritative_nonrecipe_blocks)

    tag_normalization_report = normalize_conversion_result_recipe_tags(result)
    if recipe_limit is not None:
        from cookimport.cli_worker import apply_result_limits

        apply_result_limits(
            result,
            recipe_limit,
            limit_label=recipe_limit_label,
        )

    result.report = build_authoritative_stage_report(result.report)
    result.report.importer_name = importer_name
    if run_config is not None:
        result.report.run_config = dict(run_config)
    result.report.run_config_hash = run_config_hash
    result.report.run_config_summary = run_config_summary
    llm_report["recipe_tags"] = {
        "mode": "inline_recipe_correction",
        "normalization": tag_normalization_report,
    }
    result.report.llm_codex_farm = llm_report
    result.report.run_timestamp = run_dt.isoformat(timespec="seconds")
    runtime.enrich_report_with_stats(
        result.report,
        result,
        source_file,
        count_diagnostics_path=count_diagnostics_path,
    )

    output_stats = output_stats or OutputStats(run_root)
    source_artifact_paths = write_source_model_artifacts(
        run_root,
        workbook_slug,
        result.source_blocks or extracted_book_bundle.source_blocks,
        result.source_support or extracted_book_bundle.source_support,
        output_stats=output_stats,
    )
    intermediate_dir = run_root / "intermediate drafts" / workbook_slug
    final_dir = run_root / "final drafts" / workbook_slug
    authoritative_recipe_payloads_path = (
        run_root
        / "recipe_authority"
        / workbook_slug
        / "authoritative_recipe_payloads.json"
    )
    stage_predictions_path = run_root / ".bench" / workbook_slug / "stage_block_predictions.json"

    with measure(stats, "writing"):
        write_steps = [
            "nonrecipe outputs",
            "recipe authority",
            "intermediate drafts",
            "final drafts",
            "section outputs",
            "chunks" if result.chunks else None,
            "tables",
            "raw artifacts" if write_raw_artifacts_enabled else None,
            "stage block predictions",
        ]
        write_steps = [step for step in write_steps if step is not None]
        write_total = len(write_steps)
        write_completed = 0

        def _notify_write_progress(step_label: str | None = None) -> None:
            detail_lines = [
                f"recipes: {len(result.recipes)}",
                f"chunks: {len(result.chunks or [])}",
                f"tables: {len(extracted_tables)}",
            ]
            if step_label:
                detail_lines.append(f"current output: {step_label}")
            _notify_stage_progress(
                progress_callback,
                message="Writing outputs...",
                stage_label="writing outputs",
                task_current=write_completed,
                task_total=write_total,
                detail_lines=detail_lines,
            )

        _notify_write_progress(write_steps[0] if write_steps else None)
        with measure(stats, "write_nonrecipe_seconds"):
            runtime.write_nonrecipe_stage_outputs(
                nonrecipe_stage_result,
                run_root,
                output_stats=output_stats,
            )
            runtime.write_knowledge_outputs_artifact(
                run_root=run_root,
                stage_result=nonrecipe_stage_result,
                llm_report=llm_report.get("knowledge"),
                knowledge_group_records=(
                    nonrecipe_finalize_result.nonrecipe_finalize_write_report.group_records
                    if nonrecipe_finalize_result is not None
                    and nonrecipe_finalize_result.nonrecipe_finalize_write_report is not None
                    else []
                ),
                snippet_records=(
                    nonrecipe_finalize_result.nonrecipe_finalize_write_report.snippet_records
                    if nonrecipe_finalize_result is not None
                    and nonrecipe_finalize_result.nonrecipe_finalize_write_report is not None
                    else []
                ),
                output_stats=output_stats,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_recipe_authority_seconds"):
            runtime.write_authoritative_recipe_semantics(
                payloads_by_recipe_id=authoritative_recipe_payloads_by_recipe_id,
                out_path=authoritative_recipe_payloads_path,
                workbook_slug=workbook_slug,
                refinement_mode=recipe_refine_result.refinement_mode if recipe_refine_result is not None else "unknown",
                output_stats=output_stats,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_intermediate_seconds"):
            runtime.write_intermediate_outputs(
                result,
                intermediate_dir,
                output_stats=output_stats,
                authoritative_payloads_by_recipe_id=authoritative_recipe_payloads_by_recipe_id,
                instruction_step_options=run_config,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_final_seconds"):
            runtime.write_draft_outputs(
                result,
                final_dir,
                output_stats=output_stats,
                authoritative_payloads_by_recipe_id=authoritative_recipe_payloads_by_recipe_id,
                ingredient_parser_options=run_config,
                instruction_step_options=run_config,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_sections_seconds"):
            runtime.write_section_outputs(
                run_root,
                workbook_slug,
                result.recipes,
                output_stats=output_stats,
                write_markdown=write_markdown,
                instruction_step_options=run_config,
                authoritative_payloads_by_recipe_id=authoritative_recipe_payloads_by_recipe_id,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        if result.chunks:
            with measure(stats, "write_chunks_seconds"):
                runtime.write_chunk_outputs(
                    result.chunks,
                    run_root / "chunks" / workbook_slug,
                    output_stats=output_stats,
                    write_markdown=write_markdown,
                )
            write_completed += 1
            _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_tables_seconds"):
            runtime.write_table_outputs(
                run_root,
                workbook_slug,
                extracted_tables,
                source_file=source_file.name,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        if write_raw_artifacts_enabled:
            with measure(stats, "write_raw_seconds"):
                runtime.write_raw_artifacts(result, run_root, output_stats=output_stats)
            write_completed += 1
            _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_stage_block_predictions_seconds"):
            runtime.write_stage_block_predictions(
                results=result,
                run_root=run_root,
                workbook_slug=workbook_slug,
                source_file=str(source_file),
                archive_blocks=list(extracted_book_bundle.archive_blocks),
                nonrecipe_stage_result=nonrecipe_stage_result,
                output_stats=output_stats,
                label_first_result=label_first_result,
            )
        write_completed += 1
        _notify_write_progress(None)

    if output_stats.file_counts:
        result.report.output_stats = output_stats.to_report()
    report_path = runtime.write_report(result.report, run_root, source_file.stem)

    return StageImportSessionResult(
        run_root=run_root,
        workbook_slug=workbook_slug,
        source_file=source_file,
        source_hash=extracted_book_bundle.source_hash,
        importer_name=importer_name,
        conversion_result=result,
        report_path=report_path,
        stage_block_predictions_path=stage_predictions_path,
        run_config=dict(run_config) if run_config is not None else None,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        llm_report=llm_report,
        timing=stats.to_dict(),
        label_first_result=label_first_result,
        label_artifact_paths=label_artifact_paths,
        source_artifact_paths=source_artifact_paths,
        authoritative_recipe_payloads_path=authoritative_recipe_payloads_path,
        nonrecipe_stage_result=nonrecipe_stage_result,
        extracted_book_bundle=extracted_book_bundle,
        recipe_boundary_result=recipe_boundary_result,
        recipe_refine_result=recipe_refine_result,
        nonrecipe_route_result=nonrecipe_route_result,
        nonrecipe_finalize_result=nonrecipe_finalize_result,
    )
