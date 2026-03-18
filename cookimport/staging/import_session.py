from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import (
    format_stage_counter_progress,
    format_stage_progress,
)
from cookimport.core.reporting import (
    build_authoritative_stage_report,
    compute_file_hash,
    enrich_report_with_stats,
)
from cookimport.core.slug import slugify_name
from cookimport.core.timing import TimingStats, measure
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
from cookimport.parsing.label_source_of_truth import (
    LabelFirstStageResult,
    build_label_first_stage_result,
)
from cookimport.parsing.tables import extract_and_annotate_tables
from cookimport.staging.nonrecipe_stage import (
    NonRecipeStageResult,
    block_rows_for_nonrecipe_stage,
    build_nonrecipe_stage_result,
)
from cookimport.staging.recipe_tag_normalization import (
    normalize_conversion_result_recipe_tags,
)
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_knowledge_outputs_artifact,
    write_intermediate_outputs,
    write_nonrecipe_stage_outputs,
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
    label_first_result: LabelFirstStageResult | None = None
    label_artifact_paths: dict[str, Path] | None = None
    nonrecipe_stage_result: NonRecipeStageResult | None = None


def _notify(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _notify_stage_progress(
    progress_callback: Callable[[str], None] | None,
    *,
    message: str,
    stage_label: str,
    task_current: int | None = None,
    task_total: int | None = None,
    detail_lines: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    if task_current is not None and task_total is not None:
        progress_callback(
            format_stage_counter_progress(
                message,
                task_current,
                task_total,
                stage_label=stage_label,
                detail_lines=detail_lines,
            )
        )
        return
    progress_callback(
        format_stage_progress(
            message,
            stage_label=stage_label,
            detail_lines=detail_lines,
        )
    )


def _resolve_source_hash(result: ConversionResult, source_file: Path) -> str:
    for artifact in result.raw_artifacts:
        source_hash = getattr(artifact, "source_hash", None)
        if source_hash:
            return str(source_hash)
    try:
        return compute_file_hash(source_file)
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )


def _write_label_first_artifacts(
    *,
    run_root: Path,
    workbook_slug: str,
    label_first_result: LabelFirstStageResult,
    line_role_pipeline: str,
) -> dict[str, Path]:
    det_lines_path = run_root / "label_det" / workbook_slug / "labeled_lines.jsonl"
    det_blocks_path = run_root / "label_det" / workbook_slug / "block_labels.json"
    final_lines_path = run_root / "label_llm_correct" / workbook_slug / "labeled_lines.jsonl"
    final_blocks_path = run_root / "label_llm_correct" / workbook_slug / "block_labels.json"
    final_diffs_path = run_root / "label_llm_correct" / workbook_slug / "label_diffs.jsonl"
    span_path = run_root / "group_recipe_spans" / workbook_slug / "recipe_spans.json"
    span_decisions_path = run_root / "group_recipe_spans" / workbook_slug / "span_decisions.json"
    authoritative_blocks_path = (
        run_root / "group_recipe_spans" / workbook_slug / "authoritative_block_labels.json"
    )

    det_line_rows = [
        {
            "source_block_id": row.source_block_id,
            "source_block_index": row.source_block_index,
            "atomic_index": row.atomic_index,
            "text": row.text,
            "label": row.deterministic_label,
            "final_label": row.final_label,
            "decided_by": row.decided_by,
            "reason_tags": list(row.reason_tags),
            "escalation_reasons": list(row.escalation_reasons),
        }
        for row in label_first_result.labeled_lines
    ]
    det_block_rows = {
        "schema_version": "label_det.v1",
        "workbook_slug": workbook_slug,
        "block_labels": [
            {
                "source_block_id": row.source_block_id,
                "source_block_index": row.source_block_index,
                "supporting_atomic_indices": list(row.supporting_atomic_indices),
                "label": row.deterministic_label,
                "final_label": row.final_label,
                "decided_by": row.decided_by,
                "reason_tags": list(row.reason_tags),
                "escalation_reasons": list(row.escalation_reasons),
            }
            for row in label_first_result.block_labels
        ],
    }
    _write_jsonl(det_lines_path, det_line_rows)
    _write_json(det_blocks_path, det_block_rows)

    wrote_final_stage = str(line_role_pipeline or "off").strip().lower() != "off"
    if wrote_final_stage:
        final_line_rows = [
            {
                "source_block_id": row.source_block_id,
                "source_block_index": row.source_block_index,
                "atomic_index": row.atomic_index,
                "text": row.text,
                "deterministic_label": row.deterministic_label,
                "label": row.final_label,
                "decided_by": row.decided_by,
                "reason_tags": list(row.reason_tags),
                "escalation_reasons": list(row.escalation_reasons),
            }
            for row in label_first_result.labeled_lines
        ]
        final_block_rows = {
            "schema_version": "label_llm_correct.v1",
            "workbook_slug": workbook_slug,
            "block_labels": [
                row.model_dump(mode="json")
                for row in label_first_result.block_labels
            ],
        }
        diff_rows = [
            {
                "atomic_index": row.atomic_index,
                "source_block_index": row.source_block_index,
                "text": row.text,
                "deterministic_label": row.deterministic_label,
                "final_label": row.final_label,
            }
            for row in label_first_result.labeled_lines
            if row.deterministic_label != row.final_label
        ]
        _write_jsonl(final_lines_path, final_line_rows)
        _write_json(final_blocks_path, final_block_rows)
        _write_jsonl(final_diffs_path, diff_rows)

    _write_json(
        span_path,
        {
            "schema_version": "group_recipe_spans.v1",
            "workbook_slug": workbook_slug,
            "recipe_spans": [
                row.model_dump(mode="json") for row in label_first_result.recipe_spans
            ],
        },
    )
    _write_json(
        span_decisions_path,
        {
            "schema_version": "group_recipe_span_decisions.v2",
            "workbook_slug": workbook_slug,
            "span_decisions": [
                _serialize_span_decision(row)
                for row in _span_decisions_for_artifacts(label_first_result)
            ],
        },
    )
    _write_json(
        authoritative_blocks_path,
        {
            "schema_version": "authoritative_block_labels.v1",
            "workbook_slug": workbook_slug,
            "block_labels": [
                row.model_dump(mode="json") for row in label_first_result.block_labels
            ],
        },
    )

    paths = {
        "label_det_lines_path": det_lines_path,
        "label_det_blocks_path": det_blocks_path,
        "recipe_spans_path": span_path,
        "span_decisions_path": span_decisions_path,
        "authoritative_block_labels_path": authoritative_blocks_path,
    }
    if wrote_final_stage:
        paths.update(
            {
                "label_llm_lines_path": final_lines_path,
                "label_llm_blocks_path": final_blocks_path,
                "label_llm_diffs_path": final_diffs_path,
            }
        )
    return paths


def _span_decisions_for_artifacts(
    label_first_result: LabelFirstStageResult,
) -> list[Any]:
    if label_first_result.span_decisions:
        return list(label_first_result.span_decisions)
    return [
        {
            "span_id": row.span_id,
            "decision": "accepted_recipe_span",
            "rejection_reason": None,
            "start_block_index": row.start_block_index,
            "end_block_index": row.end_block_index,
            "block_indices": list(row.block_indices),
            "source_block_ids": list(row.source_block_ids),
            "start_atomic_index": row.start_atomic_index,
            "end_atomic_index": row.end_atomic_index,
            "atomic_indices": list(row.atomic_indices),
            "title_block_index": row.title_block_index,
            "title_atomic_index": row.title_atomic_index,
            "warnings": list(row.warnings),
            "escalation_reasons": list(row.escalation_reasons),
            "decision_notes": list(row.decision_notes),
        }
        for row in label_first_result.recipe_spans
    ]


def _serialize_span_decision(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        payload = row.model_dump(mode="json")
    else:
        payload = dict(row)
    return {
        "span_id": payload.get("span_id"),
        "decision": payload.get("decision", "accepted_recipe_span"),
        "rejection_reason": payload.get("rejection_reason"),
        "start_block_index": payload.get("start_block_index"),
        "end_block_index": payload.get("end_block_index"),
        "block_indices": list(payload.get("block_indices") or []),
        "source_block_ids": list(payload.get("source_block_ids") or []),
        "start_atomic_index": payload.get("start_atomic_index"),
        "end_atomic_index": payload.get("end_atomic_index"),
        "atomic_indices": list(payload.get("atomic_indices") or []),
        "title_block_index": payload.get("title_block_index"),
        "title_atomic_index": payload.get("title_atomic_index"),
        "escalation_reasons": list(payload.get("escalation_reasons") or []),
        "decision_notes": list(payload.get("decision_notes") or []),
        "warnings": list(payload.get("warnings") or []),
    }


def _write_label_first_authority_mismatch_artifact(
    *,
    run_root: Path,
    workbook_slug: str,
    importer_recipe_count: int,
    authoritative_recipe_count: int,
    recipe_spans: list[dict[str, Any]],
) -> Path:
    mismatch_path = (
        run_root
        / "group_recipe_spans"
        / workbook_slug
        / "authority_mismatch.json"
    )
    _write_json(
        mismatch_path,
        {
            "schema_version": "group_recipe_spans_authority_mismatch.v1",
            "workbook_slug": workbook_slug,
            "importer_recipe_count": int(importer_recipe_count),
            "authoritative_recipe_count": int(authoritative_recipe_count),
            "warning": (
                "Authoritative Stage 2 regrouping produced zero recipes even though "
                "the importer reported recipe candidates. The run stayed on the "
                "authoritative label-first path."
            ),
            "recipe_spans": list(recipe_spans),
        },
    )
    return mismatch_path


def _append_report_warning(report: ConversionReport | None, message: str) -> ConversionReport:
    if report is None:
        report = ConversionReport()
    warnings = list(report.warnings or [])
    warnings.append(str(message))
    report.warnings = warnings
    return report


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
    original_result = result
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
    label_first_result: LabelFirstStageResult | None = None
    label_artifact_paths: dict[str, Path] | None = None
    nonrecipe_stage_result: NonRecipeStageResult | None = None
    live_llm_allowed = bool((run_config or {}).get("codex_execution_live_llm_allowed"))

    _notify_stage_progress(
        progress_callback,
        message="Building authoritative labels...",
        stage_label="authoritative labels",
        task_current=0,
        task_total=4,
    )
    with measure(stats, "label_source_of_truth_seconds"):
        label_first_result = build_label_first_stage_result(
            conversion_result=result,
            source_file=source_file,
            importer_name=importer_name,
            run_settings=run_settings,
            artifact_root=run_root,
            full_blocks=full_blocks,
            live_llm_allowed=live_llm_allowed,
            progress_callback=progress_callback,
        )
    result = label_first_result.updated_conversion_result
    label_artifact_paths = _write_label_first_artifacts(
        run_root=run_root,
        workbook_slug=workbook_slug,
        label_first_result=label_first_result,
        line_role_pipeline=str(getattr(run_settings.line_role_pipeline, "value", "off")),
    )
    if original_result.recipes and not result.recipes:
        result.report = _append_report_warning(
            result.report,
            "Authoritative Stage 2 regrouping found zero recipes after importer "
            "candidates were detected; keeping label-first outputs and writing "
            "group_recipe_spans authority diagnostics.",
        )
        label_artifact_paths["authority_mismatch_path"] = (
            _write_label_first_authority_mismatch_artifact(
                run_root=run_root,
                workbook_slug=workbook_slug,
                importer_recipe_count=len(original_result.recipes),
                authoritative_recipe_count=len(result.recipes),
                recipe_spans=[
                    row.model_dump(mode="json")
                    for row in label_first_result.recipe_spans
                ],
            )
        )

    if run_settings.llm_recipe_pipeline.value != "off":
        _notify_stage_progress(
            progress_callback,
            message="Running codex-farm recipe pipeline...",
            stage_label="recipe pipeline",
        )
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
                result.report = _append_report_warning(
                    result.report,
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}",
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

    archive_blocks = list(
        label_first_result.archive_blocks if label_first_result is not None else (full_blocks or [])
    )
    nonrecipe_stage_result = build_nonrecipe_stage_result(
        full_blocks=archive_blocks,
        final_block_labels=label_first_result.block_labels if label_first_result is not None else [],
        recipe_spans=label_first_result.recipe_spans if label_first_result is not None else [],
        overrides=parsing_overrides,
    )

    knowledge_write_report = None
    if run_settings.llm_knowledge_pipeline.value != "off":
        _notify_stage_progress(
            progress_callback,
            message="Running codex-farm knowledge harvest...",
            stage_label="knowledge harvest",
        )
        try:
            knowledge_apply = run_codex_farm_knowledge_harvest(
                conversion_result=result,
                nonrecipe_stage_result=nonrecipe_stage_result,
                recipe_spans=list(label_first_result.recipe_spans if label_first_result is not None else []),
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=workbook_slug,
                overrides=parsing_overrides,
                full_blocks=full_blocks,
                progress_callback=progress_callback,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                result.report = _append_report_warning(
                    result.report,
                    "LLM knowledge harvest failed; continuing without knowledge artifacts: "
                    f"{exc}",
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
            nonrecipe_stage_result = knowledge_apply.refined_stage_result
            knowledge_write_report = knowledge_apply.write_report

    nonrecipe_block_rows = block_rows_for_nonrecipe_stage(
        full_blocks=archive_blocks,
        stage_result=nonrecipe_stage_result,
    )

    extracted_tables = []
    if nonrecipe_block_rows:
        _notify_stage_progress(
            progress_callback,
            message="Extracting knowledge tables...",
            stage_label="extracting knowledge tables",
            detail_lines=[f"non-recipe blocks: {len(nonrecipe_block_rows)}"],
        )
        extracted_tables = extract_and_annotate_tables(
            nonrecipe_block_rows,
            source_hash=_resolve_source_hash(result, source_file),
        )

    chunk_detail_lines = [f"non-recipe blocks: {len(nonrecipe_block_rows)}"]
    if not nonrecipe_block_rows and result.topic_candidates:
        chunk_detail_lines.append(
            f"fallback topic candidates: {len(result.topic_candidates)}"
        )
    _notify_stage_progress(
        progress_callback,
        message="Generating knowledge chunks...",
        stage_label="knowledge chunk generation",
        detail_lines=chunk_detail_lines,
    )
    if nonrecipe_block_rows:
        result.chunks = chunks_from_non_recipe_blocks(
            nonrecipe_block_rows,
            overrides=parsing_overrides,
        )
    elif result.topic_candidates:
        result.chunks = chunks_from_topic_candidates(
            result.topic_candidates,
            overrides=parsing_overrides,
        )

    # Mirror the current final non-recipe authority onto ConversionResult so
    # downstream consumers read the same view used for scoring and staged outputs.
    result.non_recipe_blocks = nonrecipe_block_rows

    tag_normalization_report = normalize_conversion_result_recipe_tags(result)

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
        write_steps = [
            "nonrecipe outputs",
            "intermediate drafts",
            "final drafts",
            "section outputs",
            "tips",
            "topic candidates",
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
            write_nonrecipe_stage_outputs(
                nonrecipe_stage_result,
                run_root,
                output_stats=output_stats,
            )
            write_knowledge_outputs_artifact(
                run_root=run_root,
                stage_result=nonrecipe_stage_result,
                llm_report=llm_report.get("knowledge"),
                snippet_records=(
                    knowledge_write_report.snippet_records
                    if knowledge_write_report is not None
                    else []
                ),
                output_stats=output_stats,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_intermediate_seconds"):
            write_intermediate_outputs(
                result,
                intermediate_dir,
                output_stats=output_stats,
                schemaorg_overrides_by_recipe_id=llm_schema_overrides,
                instruction_step_options=run_config,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_final_seconds"):
            write_draft_outputs(
                result,
                final_dir,
                output_stats=output_stats,
                draft_overrides_by_recipe_id=llm_draft_overrides,
                ingredient_parser_options=run_config,
                instruction_step_options=run_config,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_sections_seconds"):
            write_section_outputs(
                run_root,
                workbook_slug,
                result.recipes,
                output_stats=output_stats,
                write_markdown=write_markdown,
                instruction_step_options=run_config,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_tips_seconds"):
            write_tip_outputs(
                result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_topic_candidates_seconds"):
            write_topic_candidate_outputs(
                result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        write_completed += 1
        _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        if result.chunks:
            with measure(stats, "write_chunks_seconds"):
                write_chunk_outputs(
                    result.chunks,
                    run_root / "chunks" / workbook_slug,
                    output_stats=output_stats,
                    write_markdown=write_markdown,
                )
            write_completed += 1
            _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_tables_seconds"):
            write_table_outputs(
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
                write_raw_artifacts(result, run_root, output_stats=output_stats)
            write_completed += 1
            _notify_write_progress(write_steps[write_completed] if write_completed < write_total else None)
        with measure(stats, "write_stage_block_predictions_seconds"):
            write_stage_block_predictions(
                results=result,
                run_root=run_root,
                workbook_slug=workbook_slug,
                source_file=str(source_file),
                archive_blocks=full_blocks,
                nonrecipe_stage_result=nonrecipe_stage_result,
                output_stats=output_stats,
                label_first_result=label_first_result,
            )
        write_completed += 1
        _notify_write_progress(None)

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
        label_first_result=label_first_result,
        label_artifact_paths=label_artifact_paths,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )
