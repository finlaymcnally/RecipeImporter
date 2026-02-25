from __future__ import annotations

import datetime as dt
import logging
import multiprocessing
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, MappingConfig
from cookimport.core.slug import slugify_name
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.timing import TimingStats, measure
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.plugins import registry
# Ensure plugins are registered in workers
from cookimport.plugins import excel, text, epub, pdf, recipesage, paprika  # noqa: F401
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
from cookimport.parsing.tables import ExtractedTable, extract_and_annotate_tables
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_raw_artifacts,
    write_report,
    write_section_outputs,
    write_table_outputs,
    write_tip_outputs,
    write_topic_candidate_outputs,
)

logger = logging.getLogger(__name__)


@contextmanager
def _temporary_epub_extractor(value: str | None):
    if not value:
        yield
        return
    previous = os.environ.get("C3IMP_EPUB_EXTRACTOR")
    os.environ["C3IMP_EPUB_EXTRACTOR"] = str(value)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("C3IMP_EPUB_EXTRACTOR", None)
        else:
            os.environ["C3IMP_EPUB_EXTRACTOR"] = previous

def _worker_label() -> str:
    return f"{multiprocessing.current_process().name} ({os.getpid()})"

def _safe_progress_put(progress_queue: Any | None, payload: tuple[Any, ...]) -> None:
    if not progress_queue:
        return
    try:
        put_nowait = getattr(progress_queue, "put_nowait", None)
        if callable(put_nowait):
            put_nowait(payload)
            return
        progress_queue.put(payload, block=False)
    except Exception:
        # Best-effort progress only; never block worker execution.
        pass

def _build_progress_reporter(
    progress_queue: Any | None,
    display_label: str,
    *,
    heartbeat_seconds: float = 5.0,
) -> tuple[str, Any, threading.Event, threading.Thread]:
    worker_label = _worker_label()
    last_message = {"text": "Starting job..."}
    stop_event = threading.Event()

    def _emit(msg: str) -> None:
        _safe_progress_put(
            progress_queue,
            (worker_label, display_label, msg, dt.datetime.now().timestamp()),
        )

    def report(msg: str) -> None:
        last_message["text"] = msg
        _emit(msg)

    def heartbeat() -> None:
        while not stop_event.wait(heartbeat_seconds):
            _emit(last_message["text"])

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    return worker_label, report, stop_event, thread

def apply_result_limits(
    result: Any,
    recipe_limit: int | None,
    tip_limit: int | None,
    *,
    limit_label: int | None = None,
) -> tuple[int, int, bool]:
    original_recipes = len(result.recipes)
    original_tips = len(result.tips)

    if recipe_limit is not None:
        result.recipes = result.recipes[: max(recipe_limit, 0)]
    if tip_limit is not None:
        result.tips = result.tips[: max(tip_limit, 0)]

    result.report.total_recipes = len(result.recipes)
    result.report.total_tips = len(result.tips)
    result.report.total_general_tips = len(result.tips)
    if result.tip_candidates:
        result.report.total_tip_candidates = len(result.tip_candidates)
        result.report.total_recipe_specific_tips = len(
            [tip for tip in result.tip_candidates if tip.scope == "recipe_specific"]
        )
        result.report.total_not_tips = len(
            [tip for tip in result.tip_candidates if tip.scope == "not_tip"]
        )

    truncated = len(result.recipes) < original_recipes or len(result.tips) < original_tips
    if truncated:
        parts = []
        if len(result.recipes) < original_recipes:
            parts.append(f"{len(result.recipes)} of {original_recipes} recipes")
        if len(result.tips) < original_tips:
            parts.append(f"{len(result.tips)} of {original_tips} tips")
        limit_prefix = f"Limit {limit_label} applied. " if limit_label is not None else "Limit applied. "
        result.report.warnings.append(f"{limit_prefix}Output truncated to {', '.join(parts)}.")

    return len(result.recipes), len(result.tips), truncated


def _apply_epub_auto_metadata(
    report: ConversionReport,
    *,
    epub_auto_selection: dict[str, Any] | None,
    epub_auto_selected_score: float | None,
) -> None:
    if epub_auto_selection is not None:
        report.epub_auto_selection = dict(epub_auto_selection)
    if epub_auto_selected_score is not None:
        report.epub_auto_selected_score = float(epub_auto_selected_score)


def _resolve_table_source_hash(result: Any, file_path: Path) -> str:
    for artifact in getattr(result, "raw_artifacts", []):
        source_hash = getattr(artifact, "source_hash", None)
        if source_hash:
            return str(source_hash)
    try:
        return compute_file_hash(file_path)
    except Exception:
        return "unknown"


def _run_import(
    file_path: Path,
    mapping_config: MappingConfig | None,
    progress_callback: Any | None = None,
    *,
    start_page: int | None = None,
    end_page: int | None = None,
    start_spine: int | None = None,
    end_spine: int | None = None,
) -> tuple[Any, TimingStats, MappingConfig | None]:
    file_stats = TimingStats()

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        raise ValueError("No importer")

    resolved_mapping = mapping_config
    if resolved_mapping is None:
        if progress_callback:
            progress_callback("Inspecting file structure...")
        inspection = importer.inspect(file_path)
        resolved_mapping = inspection.mapping_stub

    with measure(file_stats, "parsing"):
        if start_page is not None or end_page is not None:
            if importer.name != "pdf":
                raise ValueError("Page range provided for non-PDF importer")
            result = importer.convert(
                file_path,
                resolved_mapping,
                progress_callback=progress_callback,
                start_page=start_page,
                end_page=end_page,
            )
        elif start_spine is not None or end_spine is not None:
            if importer.name != "epub":
                raise ValueError("Spine range provided for non-EPUB importer")
            result = importer.convert(
                file_path,
                resolved_mapping,
                progress_callback=progress_callback,
                start_spine=start_spine,
                end_spine=end_spine,
            )
        else:
            result = importer.convert(
                file_path, resolved_mapping, progress_callback=progress_callback
            )

    return result, file_stats, resolved_mapping

def stage_one_file(
    file_path: Path,
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    progress_queue: Any | None = None,
    display_name: str | None = None,
    epub_extractor: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
) -> dict[str, Any]:
    """Process a single file and return a summary."""

    display_label = display_name or file_path.name
    worker_label, _report_progress, stop_event, heartbeat_thread = _build_progress_reporter(
        progress_queue,
        display_label,
    )

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        return {
            "file": file_path.name,
            "status": "skipped",
            "reason": "No importer",
            "worker_label": worker_label,
        }

    try:
        start_total = dt.datetime.now()
        workbook_slug = slugify_name(file_path.stem)
        run_settings = RunSettings.from_dict(run_config, warn_context="stage run config")
        
        intermediate_dir = out / "intermediate drafts" / workbook_slug
        final_dir = out / "final drafts" / workbook_slug
        tips_dir = out / "tips" / workbook_slug

        # Note: mapping_config is already passed in and overridden by CLI if needed
        _report_progress("Starting file...")
        _report_progress("Parsing recipes...")
        with _temporary_epub_extractor(epub_extractor):
            result, file_stats, resolved_mapping = _run_import(
                file_path,
                mapping_config,
                _report_progress,
            )

        if limit is not None:
            apply_result_limits(
                result,
                limit,
                limit,
                limit_label=limit,
            )

        llm_schema_overrides: dict[str, dict[str, Any]] | None = None
        llm_draft_overrides: dict[str, dict[str, Any]] | None = None
        llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
        if run_settings.llm_recipe_pipeline.value != "off":
            _report_progress("Running codex-farm recipe pipeline...")
            try:
                llm_apply = run_codex_farm_recipe_pipeline(
                    conversion_result=result,
                    run_settings=run_settings,
                    run_root=out,
                    workbook_slug=workbook_slug,
                )
            except CodexFarmRunnerError as exc:
                if run_settings.codex_farm_failure_mode.value == "fallback":
                    warning = (
                        "LLM recipe pipeline failed; falling back to deterministic outputs: "
                        f"{exc}"
                    )
                    result.report.warnings.append(warning)
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

        extracted_tables: list[ExtractedTable] = []
        if run_settings.table_extraction.value == "on" and result.non_recipe_blocks:
            _report_progress("Extracting knowledge tables...")
            extracted_tables = extract_and_annotate_tables(
                result.non_recipe_blocks,
                source_hash=_resolve_table_source_hash(result, file_path),
            )

        # Generate knowledge chunks
        _report_progress("Generating knowledge chunks...")
        parsing_overrides = None
        if resolved_mapping and resolved_mapping.parsing_overrides:
            parsing_overrides = resolved_mapping.parsing_overrides
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
            _report_progress("Running codex-farm knowledge harvest...")
            try:
                knowledge_apply = run_codex_farm_knowledge_harvest(
                    conversion_result=result,
                    run_settings=run_settings,
                    run_root=out,
                    workbook_slug=workbook_slug,
                    overrides=parsing_overrides,
                )
            except CodexFarmRunnerError as exc:
                if run_settings.codex_farm_failure_mode.value == "fallback":
                    warning = (
                        "LLM knowledge harvest failed; continuing without knowledge artifacts: "
                        f"{exc}"
                    )
                    result.report.warnings.append(warning)
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

        # Enrich report
        result.report.importer_name = importer.name
        if run_config is not None:
            result.report.run_config = dict(run_config)
        result.report.run_config_hash = run_config_hash
        result.report.run_config_summary = run_config_summary
        result.report.llm_codex_farm = llm_report
        _apply_epub_auto_metadata(
            result.report,
            epub_auto_selection=epub_auto_selection,
            epub_auto_selected_score=epub_auto_selected_score,
        )
        result.report.run_timestamp = run_dt.isoformat(timespec="seconds")
        enrich_report_with_stats(result.report, result, file_path)

        output_stats = OutputStats(out)
        with measure(file_stats, "writing"):
            _report_progress("Writing outputs...")
            with measure(file_stats, "write_intermediate_seconds"):
                write_intermediate_outputs(
                    result,
                    intermediate_dir,
                    output_stats=output_stats,
                    schemaorg_overrides_by_recipe_id=llm_schema_overrides,
                )
            with measure(file_stats, "write_final_seconds"):
                write_draft_outputs(
                    result,
                    final_dir,
                    output_stats=output_stats,
                    draft_overrides_by_recipe_id=llm_draft_overrides,
                )
            with measure(file_stats, "write_sections_seconds"):
                write_section_outputs(
                    out,
                    workbook_slug,
                    result.recipes,
                    output_stats=output_stats,
                )
            with measure(file_stats, "write_tips_seconds"):
                write_tip_outputs(result, tips_dir, output_stats=output_stats)
            with measure(file_stats, "write_topic_candidates_seconds"):
                write_topic_candidate_outputs(result, tips_dir, output_stats=output_stats)

            if result.chunks:
                chunks_dir = out / "chunks" / workbook_slug
                with measure(file_stats, "write_chunks_seconds"):
                    write_chunk_outputs(result.chunks, chunks_dir, output_stats=output_stats)
            if run_settings.table_extraction.value == "on":
                with measure(file_stats, "write_tables_seconds"):
                    write_table_outputs(
                        out,
                        workbook_slug,
                        extracted_tables,
                        source_file=file_path.name,
                        output_stats=output_stats,
                    )

            with measure(file_stats, "write_raw_seconds"):
                write_raw_artifacts(result, out, output_stats=output_stats)

        file_stats.total_seconds = (dt.datetime.now() - start_total).total_seconds()
        if output_stats.file_counts:
            result.report.output_stats = output_stats.to_report()
        result.report.timing = file_stats.to_dict()
        write_report(result.report, out, file_path.stem)
        
        _report_progress("Done")

        return {
            "file": file_path.name,
            "status": "success",
            "recipes": len(result.recipes),
            "tips": len(result.tips),
            "duration": file_stats.total_seconds,
            "worker_label": worker_label,
        }
    except Exception as exc:
        _report_progress(f"Error: {exc}")
        # Write error report
        report = ConversionReport(
            errors=[str(exc)],
            sourceFile=str(file_path),
            importerName=importer.name,
            runTimestamp=run_dt.isoformat(timespec="seconds"),
            runConfig=dict(run_config) if run_config is not None else None,
            runConfigHash=run_config_hash,
            runConfigSummary=run_config_summary,
        )
        _apply_epub_auto_metadata(
            report,
            epub_auto_selection=epub_auto_selection,
            epub_auto_selected_score=epub_auto_selected_score,
        )
        write_report(report, out, file_path.stem)
        return {
            "file": file_path.name,
            "status": "error",
            "reason": str(exc),
            "worker_label": worker_label,
        }
    finally:
        stop_event.set()
        if heartbeat_thread.is_alive():
            heartbeat_thread.join(timeout=0.5)


def stage_pdf_job(
    file_path: Path,
    out: Path,
    mapping_config: MappingConfig | None,
    run_dt: dt.datetime,
    start_page: int,
    end_page: int,
    job_index: int,
    job_count: int,
    progress_queue: Any | None = None,
    display_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
) -> dict[str, Any]:
    """Process a PDF page-range job and return a mergeable payload."""

    display_label = display_name or file_path.name
    worker_label, _report_progress, stop_event, heartbeat_thread = _build_progress_reporter(
        progress_queue,
        display_label,
    )

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        return {
            "file": file_path.name,
            "status": "skipped",
            "reason": "No importer",
            "job_index": job_index,
            "job_count": job_count,
            "start_page": start_page,
            "end_page": end_page,
            "worker_label": worker_label,
        }

    try:
        start_total = dt.datetime.now()
        _report_progress("Starting job...")
        _report_progress("Parsing recipes...")
        result, file_stats, _ = _run_import(
            file_path,
            mapping_config,
            _report_progress,
            start_page=start_page,
            end_page=end_page,
        )

        workbook_slug = slugify_name(file_path.stem)
        job_root = out / ".job_parts" / workbook_slug / f"job_{job_index}"

        with measure(file_stats, "writing"):
            _report_progress("Writing raw artifacts...")
            write_raw_artifacts(result, job_root)

        result.report.importer_name = importer.name
        if run_config is not None:
            result.report.run_config = dict(run_config)
        result.report.run_config_hash = run_config_hash
        result.report.run_config_summary = run_config_summary
        result.raw_artifacts = []
        file_stats.total_seconds = (dt.datetime.now() - start_total).total_seconds()

        _report_progress("Done")

        return {
            "file": file_path.name,
            "status": "success",
            "recipes": len(result.recipes),
            "tips": len(result.tips),
            "duration": file_stats.total_seconds,
            "timing": file_stats.to_dict(),
            "job_index": job_index,
            "job_count": job_count,
            "start_page": start_page,
            "end_page": end_page,
            "result": result,
            "worker_label": worker_label,
        }
    except Exception as exc:
        _report_progress(f"Error: {exc}")
        return {
            "file": file_path.name,
            "status": "error",
            "reason": str(exc),
            "job_index": job_index,
            "job_count": job_count,
            "start_page": start_page,
            "end_page": end_page,
            "worker_label": worker_label,
        }
    finally:
        stop_event.set()
        if heartbeat_thread.is_alive():
            heartbeat_thread.join(timeout=0.5)


def stage_epub_job(
    file_path: Path,
    out: Path,
    mapping_config: MappingConfig | None,
    run_dt: dt.datetime,
    start_spine: int,
    end_spine: int,
    job_index: int,
    job_count: int,
    progress_queue: Any | None = None,
    display_name: str | None = None,
    epub_extractor: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
) -> dict[str, Any]:
    """Process an EPUB spine-range job and return a mergeable payload."""

    display_label = display_name or file_path.name
    worker_label, _report_progress, stop_event, heartbeat_thread = _build_progress_reporter(
        progress_queue,
        display_label,
    )

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        return {
            "file": file_path.name,
            "status": "skipped",
            "reason": "No importer",
            "job_index": job_index,
            "job_count": job_count,
            "start_spine": start_spine,
            "end_spine": end_spine,
            "worker_label": worker_label,
        }

    try:
        start_total = dt.datetime.now()
        _report_progress("Starting job...")
        _report_progress("Parsing recipes...")
        with _temporary_epub_extractor(epub_extractor):
            result, file_stats, _ = _run_import(
                file_path,
                mapping_config,
                _report_progress,
                start_spine=start_spine,
                end_spine=end_spine,
            )

        workbook_slug = slugify_name(file_path.stem)
        job_root = out / ".job_parts" / workbook_slug / f"job_{job_index}"

        with measure(file_stats, "writing"):
            _report_progress("Writing raw artifacts...")
            write_raw_artifacts(result, job_root)

        result.report.importer_name = importer.name
        if run_config is not None:
            result.report.run_config = dict(run_config)
        result.report.run_config_hash = run_config_hash
        result.report.run_config_summary = run_config_summary
        _apply_epub_auto_metadata(
            result.report,
            epub_auto_selection=epub_auto_selection,
            epub_auto_selected_score=epub_auto_selected_score,
        )
        result.raw_artifacts = []
        file_stats.total_seconds = (dt.datetime.now() - start_total).total_seconds()

        _report_progress("Done")

        return {
            "file": file_path.name,
            "status": "success",
            "recipes": len(result.recipes),
            "tips": len(result.tips),
            "duration": file_stats.total_seconds,
            "timing": file_stats.to_dict(),
            "job_index": job_index,
            "job_count": job_count,
            "start_spine": start_spine,
            "end_spine": end_spine,
            "result": result,
            "worker_label": worker_label,
        }
    except Exception as exc:
        _report_progress(f"Error: {exc}")
        return {
            "file": file_path.name,
            "status": "error",
            "reason": str(exc),
            "job_index": job_index,
            "job_count": job_count,
            "start_spine": start_spine,
            "end_spine": end_spine,
            "worker_label": worker_label,
        }
    finally:
        stop_event.set()
        if heartbeat_thread.is_alive():
            heartbeat_thread.join(timeout=0.5)
