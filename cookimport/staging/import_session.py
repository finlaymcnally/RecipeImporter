from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.slug import slugify_name
from cookimport.core.timing import TimingStats, measure
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
from cookimport.parsing.tables import extract_and_annotate_tables
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_raw_artifacts,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
    write_tip_outputs,
    write_topic_candidate_outputs,
)


@dataclass(frozen=True)
class StageImportSessionResult:
    run_root: Path
    workbook_slug: str
    source_file: Path
    source_hash: str
    importer_name: str
    conversion_result: ConversionResult
    report_path: Path
    stage_block_predictions_path: Path
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None
    llm_report: dict[str, Any]
    timing: dict[str, Any]


def _notify(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _resolve_source_hash(result: ConversionResult, source_file: Path) -> str:
    for artifact in result.raw_artifacts:
        source_hash = getattr(artifact, "source_hash", None)
        if source_hash:
            return str(source_hash)
    try:
        return compute_file_hash(source_file)
    except Exception:  # noqa: BLE001
        return "unknown"


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
) -> StageImportSessionResult:
    stats = timing_stats or TimingStats()
    workbook_slug = slugify_name(source_file.stem)
    parsing_overrides = (
        mapping_config.parsing_overrides
        if mapping_config is not None and mapping_config.parsing_overrides
        else None
    )

    llm_schema_overrides: dict[str, dict[str, Any]] | None = None
    llm_draft_overrides: dict[str, dict[str, Any]] | None = None
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}

    if run_settings.llm_recipe_pipeline.value != "off":
        _notify(progress_callback, "Running codex-farm recipe pipeline...")
        try:
            llm_apply = run_codex_farm_recipe_pipeline(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=workbook_slug,
                full_blocks=full_blocks,
                progress_callback=progress_callback,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                if result.report is None:
                    result.report = ConversionReport()
                result.report.warnings.append(
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}"
                )
                llm_report = {
                    "enabled": True,
                    "pipeline": run_settings.llm_recipe_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            result = llm_apply.updated_conversion_result
            llm_schema_overrides = llm_apply.intermediate_overrides_by_recipe_id
            llm_draft_overrides = llm_apply.final_overrides_by_recipe_id
            llm_report = dict(llm_apply.llm_report)

    extracted_tables = []
    if result.non_recipe_blocks:
        _notify(progress_callback, "Extracting knowledge tables...")
        extracted_tables = extract_and_annotate_tables(
            result.non_recipe_blocks,
            source_hash=_resolve_source_hash(result, source_file),
        )

    _notify(progress_callback, "Generating knowledge chunks...")
    if result.non_recipe_blocks:
        result.chunks = chunks_from_non_recipe_blocks(
            result.non_recipe_blocks,
            overrides=parsing_overrides,
        )
    elif result.topic_candidates:
        result.chunks = chunks_from_topic_candidates(
            result.topic_candidates,
            overrides=parsing_overrides,
        )

    if run_settings.llm_knowledge_pipeline.value != "off":
        _notify(progress_callback, "Running codex-farm knowledge harvest...")
        try:
            knowledge_apply = run_codex_farm_knowledge_harvest(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=workbook_slug,
                overrides=parsing_overrides,
                full_blocks=full_blocks,
                progress_callback=progress_callback,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                if result.report is None:
                    result.report = ConversionReport()
                result.report.warnings.append(
                    "LLM knowledge harvest failed; continuing without knowledge artifacts: "
                    f"{exc}"
                )
                llm_report["knowledge"] = {
                    "enabled": True,
                    "pipeline": run_settings.llm_knowledge_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            llm_report["knowledge"] = dict(knowledge_apply.llm_report)

    if result.report is None:
        result.report = ConversionReport()
    result.report.importer_name = importer_name
    if run_config is not None:
        result.report.run_config = dict(run_config)
    result.report.run_config_hash = run_config_hash
    result.report.run_config_summary = run_config_summary
    result.report.llm_codex_farm = llm_report
    result.report.run_timestamp = run_dt.isoformat(timespec="seconds")
    enrich_report_with_stats(
        result.report,
        result,
        source_file,
        count_diagnostics_path=count_diagnostics_path,
    )

    output_stats = output_stats or OutputStats(run_root)
    intermediate_dir = run_root / "intermediate drafts" / workbook_slug
    final_dir = run_root / "final drafts" / workbook_slug
    tips_dir = run_root / "tips" / workbook_slug
    knowledge_root = run_root / "knowledge" / workbook_slug
    stage_predictions_path = run_root / ".bench" / workbook_slug / "stage_block_predictions.json"

    with measure(stats, "writing"):
        _notify(progress_callback, "Writing outputs...")
        with measure(stats, "write_intermediate_seconds"):
            write_intermediate_outputs(
                result,
                intermediate_dir,
                output_stats=output_stats,
                schemaorg_overrides_by_recipe_id=llm_schema_overrides,
                instruction_step_options=run_config,
            )
        with measure(stats, "write_final_seconds"):
            write_draft_outputs(
                result,
                final_dir,
                output_stats=output_stats,
                draft_overrides_by_recipe_id=llm_draft_overrides,
                ingredient_parser_options=run_config,
                instruction_step_options=run_config,
            )
        with measure(stats, "write_sections_seconds"):
            write_section_outputs(
                run_root,
                workbook_slug,
                result.recipes,
                output_stats=output_stats,
                write_markdown=write_markdown,
                instruction_step_options=run_config,
            )
        with measure(stats, "write_tips_seconds"):
            write_tip_outputs(
                result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        with measure(stats, "write_topic_candidates_seconds"):
            write_topic_candidate_outputs(
                result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        if result.chunks:
            with measure(stats, "write_chunks_seconds"):
                write_chunk_outputs(
                    result.chunks,
                    run_root / "chunks" / workbook_slug,
                    output_stats=output_stats,
                    write_markdown=write_markdown,
                )
        with measure(stats, "write_tables_seconds"):
            write_table_outputs(
                run_root,
                workbook_slug,
                extracted_tables,
                source_file=source_file.name,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        if write_raw_artifacts_enabled:
            with measure(stats, "write_raw_seconds"):
                write_raw_artifacts(result, run_root, output_stats=output_stats)
        with measure(stats, "write_stage_block_predictions_seconds"):
            write_stage_block_predictions(
                results=result,
                run_root=run_root,
                workbook_slug=workbook_slug,
                source_file=str(source_file),
                archive_blocks=full_blocks,
                knowledge_block_classifications_path=knowledge_root / "block_classifications.jsonl",
                knowledge_snippets_path=knowledge_root / "snippets.jsonl",
                output_stats=output_stats,
            )

    if output_stats.file_counts:
        result.report.output_stats = output_stats.to_report()
    report_path = write_report(result.report, run_root, source_file.stem)

    return StageImportSessionResult(
        run_root=run_root,
        workbook_slug=workbook_slug,
        source_file=source_file,
        source_hash=_resolve_source_hash(result, source_file),
        importer_name=importer_name,
        conversion_result=result,
        report_path=report_path,
        stage_block_predictions_path=stage_predictions_path,
        run_config=dict(run_config) if run_config is not None else None,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        llm_report=llm_report,
        timing=stats.to_dict(),
    )
