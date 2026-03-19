from __future__ import annotations

import json
import logging
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import format_stage_progress
from cookimport.core.models import ConversionResult, ParsingOverrides
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.runs import KNOWLEDGE_MANIFEST_FILE_NAME, stage_artifact_stem
from cookimport.staging.nonrecipe_stage import (
    NonRecipeStageResult,
    refine_nonrecipe_stage_result,
)

from .codex_farm_ids import sanitize_for_filename
from .codex_farm_knowledge_ingest import (
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from .codex_farm_knowledge_jobs import (
    build_knowledge_jobs,
)
from .codex_farm_knowledge_writer import KnowledgeWriteReport, write_knowledge_artifacts
from .codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    summarize_direct_telemetry_rows,
)
from .codex_farm_runner import (
    CodexFarmRunnerError,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from .knowledge_prompt_builder import build_knowledge_direct_prompt
from .phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)

logger = logging.getLogger(__name__)

COMPACT_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.compact.v1"
DEFAULT_KNOWLEDGE_PIPELINE_ID = COMPACT_KNOWLEDGE_PIPELINE_ID
_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD = 1
_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD = 6000
_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN = 4096
_KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW = 12000
_STRICT_JSON_WATCHDOG_POLICY = "strict_json_no_tools_v1"
_KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS = 3
_KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS = 1_000
_KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR = 4.0
_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES = 2


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


def _notify_knowledge_progress(
    *,
    progress_callback: Callable[[str], None] | None,
    completed_tasks: int,
    total_tasks: int,
    running_tasks: int | None = None,
    worker_total: int | None = None,
    active_tasks: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    total = max(0, int(total_tasks))
    completed = max(0, min(total, int(completed_tasks)))
    message = f"Running codex-farm non-recipe knowledge review... task {completed}/{total}"
    if running_tasks is not None:
        message = f"{message} | running {max(0, int(running_tasks))}"
    remaining = max(0, total - completed)
    detail_lines = [f"queued shards: {remaining}"]
    if worker_total is not None:
        detail_lines.insert(0, f"configured workers: {max(0, int(worker_total))}")
    progress_callback(
        format_stage_progress(
            message,
            stage_label="non-recipe knowledge review",
            task_current=completed,
            task_total=total,
            running_workers=running_tasks,
            worker_total=worker_total,
            active_tasks=active_tasks,
            detail_lines=detail_lines,
        )
    )


@dataclass(frozen=True, slots=True)
class CodexFarmNonrecipeKnowledgeReviewResult:
    llm_report: dict[str, Any]
    llm_raw_dir: Path
    manifest_path: Path
    refined_stage_result: NonRecipeStageResult
    write_report: KnowledgeWriteReport | None = None


@dataclass(frozen=True, slots=True)
class _DirectKnowledgeWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    worker_runner_payload: dict[str, Any]


@dataclass(slots=True)
class _KnowledgeCohortWatchdogState:
    durations_ms: list[int] = field(default_factory=list)
    successful_examples: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            durations_ms = list(self.durations_ms)
            examples = [
                dict(example_payload)
                for example_payload in self.successful_examples[-_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES :]
            ]
        median_duration_ms = (
            int(statistics.median(durations_ms))
            if durations_ms
            else None
        )
        return {
            "completed_successful_shards": len(durations_ms),
            "median_duration_ms": median_duration_ms,
            "successful_examples": examples,
        }

    def record_validated_result(
        self,
        *,
        duration_ms: int | None,
        example_payload: Mapping[str, Any] | None,
    ) -> None:
        normalized_duration_ms = int(duration_ms or 0)
        if normalized_duration_ms <= 0:
            return
        with self.lock:
            self.durations_ms.append(normalized_duration_ms)
            if isinstance(example_payload, Mapping):
                self.successful_examples.append(dict(example_payload))
                self.successful_examples = self.successful_examples[
                    -_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES :
                ]


def run_codex_farm_nonrecipe_knowledge_review(
    *,
    conversion_result: ConversionResult,
    nonrecipe_stage_result: NonRecipeStageResult,
    recipe_spans: list[RecipeSpan],
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    overrides: ParsingOverrides | None = None,
    runner: CodexExecRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmNonrecipeKnowledgeReviewResult:
    """Optional Stage 7 review over non-recipe chunks via codex-farm."""
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    manifest_path = llm_raw_dir / KNOWLEDGE_MANIFEST_FILE_NAME

    if run_settings.llm_knowledge_pipeline.value == "off":
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
        )

    knowledge_stage_dir = llm_raw_dir / stage_artifact_stem("nonrecipe_knowledge_review")
    knowledge_in_dir = knowledge_stage_dir / "in"
    knowledge_in_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id = _non_empty(
        run_settings.codex_farm_pipeline_knowledge,
        fallback=DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    seed_candidate_spans = list(
        nonrecipe_stage_result.seed_nonrecipe_spans
        or nonrecipe_stage_result.nonrecipe_spans
    )
    if not seed_candidate_spans:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=None,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_nonrecipe_spans",
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm non-recipe knowledge review: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    configured_runner_cmd = str(run_settings.codex_farm_cmd or "").strip()
    if runner is None:
        codex_runner: CodexExecRunner = SubprocessCodexExecRunner(
            cmd=configured_runner_cmd
            if Path(configured_runner_cmd).name == "fake-codex-farm.py"
            else "codex exec"
        )
    else:
        codex_runner = runner
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )
    output_schema_path: str | None = None
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=run_settings.codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=(pipeline_id,),
            env=env,
        )
        output_schema_path = str(
            resolve_codex_farm_output_schema_path(
                root_dir=pipeline_root,
                pipeline_id=pipeline_id,
            )
        )

    started = time.perf_counter()
    build_report = build_knowledge_jobs(
        full_blocks=full_blocks_payload,
        candidate_spans=seed_candidate_spans,
        recipe_spans=recipe_spans,
        workbook_slug=workbook_slug,
        source_hash=_resolve_source_hash(conversion_result),
        out_dir=knowledge_in_dir,
        context_blocks=run_settings.codex_farm_knowledge_context_blocks,
        target_prompt_count=run_settings.knowledge_prompt_target_count,
        target_chunks_per_shard=run_settings.knowledge_shard_target_chunks,
        overrides=overrides,
    )
    for warning in build_report.planning_warnings:
        logger.warning("Knowledge planning warning for %s: %s", workbook_slug, warning)

    if build_report.shards_written == 0:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="all_chunks_skipped",
            seed_nonrecipe_span_count=build_report.seed_nonrecipe_span_count,
            chunk_count_before_pruning=build_report.chunk_count_before_pruning,
            skipped_chunk_count=build_report.skipped_chunk_count,
            skipped_lane_counts=dict(build_report.skipped_lane_counts),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    worker_count = resolve_phase_worker_count(
        requested_worker_count=run_settings.knowledge_worker_count,
        shard_count=len(build_report.shard_entries),
    )
    configured_worker_total = (
        max(1, int(run_settings.knowledge_worker_count))
        if run_settings.knowledge_worker_count is not None
        else worker_count
    )
    phase_manifest = None
    worker_reports: list[dict[str, Any]] = []
    process_run_payload: dict[str, Any] | None = None
    try:
        phase_manifest, phase_worker_reports, process_run_payload = _run_direct_knowledge_workers_v1(
            phase_key="nonrecipe_knowledge_review",
            pipeline_id=pipeline_id,
            run_root=knowledge_stage_dir,
            shards=build_report.shard_entries,
            runner=codex_runner,
            worker_count=worker_count,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            output_schema_path=Path(output_schema_path) if output_schema_path else None,
            settings={
                "llm_knowledge_pipeline": run_settings.llm_knowledge_pipeline.value,
                "knowledge_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "knowledge_worker_count": run_settings.knowledge_worker_count,
                "knowledge_shard_target_chunks": run_settings.knowledge_shard_target_chunks,
                "knowledge_shard_max_turns": run_settings.knowledge_shard_max_turns,
                "codex_farm_pipeline_knowledge": pipeline_id,
            },
            runtime_metadata={
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "input_mode": "stage7_seed_nonrecipe_spans",
                "workspace_root": str(workspace_root) if workspace_root is not None else None,
            },
            progress_worker_total=configured_worker_total,
            progress_callback=progress_callback,
        )
        worker_reports = [
            {
                "worker_id": report.worker_id,
                "shard_ids": list(report.shard_ids),
                "status": report.status,
                "proposal_count": report.proposal_count,
                "failure_count": report.failure_count,
                "runtime_mode_audit": dict(report.runtime_mode_audit or {}),
                "workspace_root": report.workspace_root,
                "metadata": dict(report.metadata),
                "runner_result": dict(report.runner_result or {}),
            }
            for report in phase_worker_reports
        ]
    except CodexFarmRunnerError as exc:
        elapsed_seconds = round(time.perf_counter() - started, 3)
        llm_report = _build_runtime_failed_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            build_report=build_report,
            elapsed_seconds=elapsed_seconds,
            error=str(exc),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    outputs, _ = read_validated_knowledge_outputs_from_proposals(knowledge_stage_dir / "proposals")
    missing_chunk_ids = sorted(set(build_report.chunk_ids) - set(outputs))
    (
        block_category_updates,
        reviewer_categories_by_block,
        applied_chunk_ids_by_block,
        conflicts,
        ignored_block_indices,
    ) = _collect_block_category_updates(
        outputs=outputs,
        allowed_block_indices=(
            nonrecipe_stage_result.seed_block_category_by_index
            or nonrecipe_stage_result.block_category_by_index
        ),
    )
    refined_stage_result = refine_nonrecipe_stage_result(
        stage_result=nonrecipe_stage_result,
        full_blocks=full_blocks_payload,
        block_category_updates=block_category_updates,
        reviewer_categories_by_block=reviewer_categories_by_block,
        applied_chunk_ids_by_block=applied_chunk_ids_by_block,
        conflicts=conflicts,
        ignored_block_indices=ignored_block_indices,
    )

    write_report = write_knowledge_artifacts(
        run_root=run_root,
        workbook_slug=workbook_slug,
        outputs=outputs,
        full_blocks_by_index=full_blocks_by_index,
        chunk_lane_by_id=build_report.chunk_lane_by_id,
    )

    elapsed_seconds = round(time.perf_counter() - started, 3)
    promotion_report = _load_json_dict(knowledge_stage_dir / "promotion_report.json")
    telemetry = _load_json_dict(knowledge_stage_dir / "telemetry.json")
    useful_chunk_count = sum(1 for output in outputs.values() if bool(output.is_useful))
    review_summary = _build_review_summary(
        build_report=build_report,
        validated_output_count=len(outputs),
        reviewed_shard_count=(
            int(phase_manifest.shard_count)
            if phase_manifest is not None
            else build_report.shards_written
        ),
        validated_shard_count=int(promotion_report.get("validated_shards") or 0),
        invalid_shard_count=int(promotion_report.get("invalid_shards") or 0),
        missing_output_shard_count=int(promotion_report.get("missing_output_shards") or 0),
        promoted_useful_chunk_count=useful_chunk_count,
        promoted_snippet_count=write_report.snippets_written,
    )
    llm_report = {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_seed_nonrecipe_spans",
        "authority_mode": str(
            refined_stage_result.refinement_report.get("authority_mode")
            or "knowledge_reviewed_seed_kept"
        ),
        "scored_effect": str(
            refined_stage_result.refinement_report.get("scored_effect")
            or "seed_only"
        ),
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": build_report.seed_nonrecipe_span_count,
            "chunks_built_before_pruning": build_report.chunk_count_before_pruning,
            "shards_written": build_report.shards_written,
            "chunks_written": build_report.chunks_written,
            "skipped_chunk_count": build_report.skipped_chunk_count,
            "outputs_parsed": len(outputs),
            "chunks_missing": len(missing_chunk_ids),
            "useful_chunks_promoted": useful_chunk_count,
            "snippets_written": write_report.snippets_written,
            "decisions_applied": len(block_category_updates),
            "changed_blocks": int(
                refined_stage_result.refinement_report.get("changed_block_count") or 0
            ),
            "worker_count": int(phase_manifest.worker_count) if phase_manifest is not None else worker_count,
            "validated_shards": int(promotion_report.get("validated_shards") or 0),
            "invalid_shards": int(promotion_report.get("invalid_shards") or 0),
            "missing_output_shards": int(promotion_report.get("missing_output_shards") or 0),
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {
            "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
            "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "snippets_path": str(write_report.snippets_path),
            "preview_path": str(write_report.preview_path),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": missing_chunk_ids,
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "planning_warnings": list(build_report.planning_warnings),
        "review_summary": review_summary,
        "refinement_report": dict(refined_stage_result.refinement_report),
        "process_run": process_run_payload,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_knowledge_review",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": int(phase_manifest.worker_count) if phase_manifest is not None else worker_count,
            "shard_count": int(phase_manifest.shard_count) if phase_manifest is not None else build_report.shards_written,
            "assignment_strategy": (
                str(phase_manifest.assignment_strategy)
                if phase_manifest is not None
                else "round_robin_v1"
            ),
            "telemetry": telemetry,
            "promotion_report": promotion_report,
            "worker_reports": worker_reports,
        },
        "stage_status": (
            "completed_with_failures"
            if int(promotion_report.get("invalid_shards") or 0) > 0
            or int(promotion_report.get("missing_output_shards") or 0) > 0
            else "completed"
        ),
    }
    _write_json(llm_report, manifest_path)

    return CodexFarmNonrecipeKnowledgeReviewResult(
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
        manifest_path=manifest_path,
        refined_stage_result=refined_stage_result,
        write_report=write_report,
    )


def _build_noop_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    stage_status: str,
    seed_nonrecipe_span_count: int = 0,
    chunk_count_before_pruning: int = 0,
    skipped_chunk_count: int = 0,
    skipped_lane_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    authority_mode = (
        "knowledge_not_run_no_nonrecipe_spans"
        if stage_status == "no_nonrecipe_spans"
        else "knowledge_not_run_all_chunks_skipped"
    )
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_seed_nonrecipe_spans",
        "authority_mode": authority_mode,
        "scored_effect": "seed_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "chunks_built_before_pruning": int(chunk_count_before_pruning),
            "shards_written": 0,
            "chunks_written": 0,
            "skipped_chunk_count": int(skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": 0,
            "useful_chunks_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "missing_output_shards": 0,
        },
        "timing": {"total_seconds": 0.0},
        "paths": {
            "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
            "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": [],
        "skipped_lane_counts": dict(skipped_lane_counts or {}),
        "review_summary": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "chunk_count_before_pruning": int(chunk_count_before_pruning),
            "reviewed_chunk_count": 0,
            "skipped_chunk_count": int(skipped_chunk_count),
            "skipped_noise_chunk_count": int((skipped_lane_counts or {}).get("noise") or 0),
            "skipped_low_signal_chunk_count": int((skipped_lane_counts or {}).get("low_signal") or 0),
            "reviewed_shard_count": 0,
            "validated_output_chunk_count": 0,
            "validated_shard_count": 0,
            "invalid_shard_count": 0,
            "missing_output_shard_count": 0,
            "promoted_useful_chunk_count": 0,
            "promoted_snippet_count": 0,
        },
        "stage_status": stage_status,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_knowledge_review",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": 0,
            "worker_reports": [],
        },
    }


def _build_runtime_failed_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    build_report: Any,
    elapsed_seconds: float,
    error: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_seed_nonrecipe_spans",
        "authority_mode": "knowledge_not_run_runtime_failed",
        "scored_effect": "seed_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(build_report.seed_nonrecipe_span_count),
            "chunks_built_before_pruning": int(build_report.chunk_count_before_pruning),
            "shards_written": int(build_report.shards_written),
            "chunks_written": int(build_report.chunks_written),
            "skipped_chunk_count": int(build_report.skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": int(build_report.chunks_written),
            "useful_chunks_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "missing_output_shards": int(build_report.shards_written),
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {
            "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
            "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": list(build_report.chunk_ids),
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "planning_warnings": list(build_report.planning_warnings),
        "review_summary": _build_review_summary(
            build_report=build_report,
            validated_output_count=0,
            reviewed_shard_count=int(build_report.shards_written),
            validated_shard_count=0,
            invalid_shard_count=0,
            missing_output_shard_count=int(build_report.shards_written),
            promoted_useful_chunk_count=0,
            promoted_snippet_count=0,
        ),
        "stage_status": "runtime_failed",
        "error": error,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_knowledge_review",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": int(build_report.shards_written),
            "worker_reports": [],
        },
    }


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _build_review_summary(
    *,
    build_report: Any,
    validated_output_count: int,
    reviewed_shard_count: int,
    validated_shard_count: int,
    invalid_shard_count: int,
    missing_output_shard_count: int,
    promoted_useful_chunk_count: int,
    promoted_snippet_count: int,
) -> dict[str, int]:
    skipped_lane_counts = dict(getattr(build_report, "skipped_lane_counts", {}) or {})
    return {
        "seed_nonrecipe_span_count": int(
            getattr(build_report, "seed_nonrecipe_span_count", 0) or 0
        ),
        "chunk_count_before_pruning": int(
            getattr(build_report, "chunk_count_before_pruning", 0) or 0
        ),
        "reviewed_chunk_count": int(getattr(build_report, "chunks_written", 0) or 0),
        "skipped_chunk_count": int(getattr(build_report, "skipped_chunk_count", 0) or 0),
        "skipped_noise_chunk_count": int(skipped_lane_counts.get("noise") or 0),
        "skipped_low_signal_chunk_count": int(skipped_lane_counts.get("low_signal") or 0),
        "reviewed_shard_count": int(reviewed_shard_count),
        "validated_output_chunk_count": int(validated_output_count),
        "validated_shard_count": int(validated_shard_count),
        "invalid_shard_count": int(invalid_shard_count),
        "missing_output_shard_count": int(missing_output_shard_count),
        "promoted_useful_chunk_count": int(promoted_useful_chunk_count),
        "promoted_snippet_count": int(promoted_snippet_count),
    }


def _runtime_artifact_paths(knowledge_stage_dir: Path) -> dict[str, str]:
    return {
        "phase_manifest_path": str(knowledge_stage_dir / "phase_manifest.json"),
        "shard_manifest_path": str(knowledge_stage_dir / "shard_manifest.jsonl"),
        "worker_assignments_path": str(knowledge_stage_dir / "worker_assignments.json"),
        "promotion_report_path": str(knowledge_stage_dir / "promotion_report.json"),
        "telemetry_path": str(knowledge_stage_dir / "telemetry.json"),
        "failures_path": str(knowledge_stage_dir / "failures.json"),
        "proposals_dir": str(knowledge_stage_dir / "proposals"),
    }


def _run_direct_knowledge_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    runner: CodexExecRunner,
    worker_count: int,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    progress_worker_total: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1], dict[str, Any]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_workers_v1(
        run_root=run_root,
        shards=shards,
        worker_count=worker_count,
    )
    _write_jsonl(
        run_root / artifacts["shard_manifest"],
        [asdict(shard) for shard in shards],
    )
    _write_json(
        [asdict(assignment) for assignment in assignments],
        run_root / artifacts["worker_assignments"],
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    total_shards = len(shards)
    completed_shards = 0
    displayed_worker_total = (
        max(0, int(progress_worker_total))
        if progress_worker_total is not None
        else worker_count
    )
    initial_active_tasks = [
        assignment.shard_ids[0]
        for assignment in assignments
        if assignment.shard_ids
    ]
    _notify_knowledge_progress(
        progress_callback=progress_callback,
        completed_tasks=0,
        total_tasks=total_shards,
        running_tasks=min(len(initial_active_tasks), total_shards),
        worker_total=displayed_worker_total,
        active_tasks=initial_active_tasks[: max(1, min(len(initial_active_tasks), total_shards))],
    )
    progress_lock = threading.Lock()
    cohort_watchdog_state = _KnowledgeCohortWatchdogState()
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        nonlocal completed_shards
        with progress_lock:
            pending = pending_shards_by_worker.get(worker_id) or []
            if shard_id in pending:
                pending.remove(shard_id)
            completed_shards += 1
            remaining_shards = max(0, total_shards - completed_shards)
            next_active_tasks: list[str] = []
            for next_assignment in assignments:
                worker_pending = pending_shards_by_worker.get(next_assignment.worker_id) or []
                if worker_pending:
                    next_active_tasks.append(worker_pending[0])
            running_tasks = min(len(next_active_tasks), remaining_shards)
            _notify_knowledge_progress(
                progress_callback=progress_callback,
                completed_tasks=completed_shards,
                total_tasks=total_shards,
                running_tasks=running_tasks,
                worker_total=displayed_worker_total,
                active_tasks=next_active_tasks[:running_tasks] if remaining_shards > 0 else [],
            )

    with ThreadPoolExecutor(
        max_workers=max(1, len(assignments)),
        thread_name_prefix="knowledge-worker",
    ) as executor:
        futures_by_worker_id = {
            assignment.worker_id: executor.submit(
                _run_direct_knowledge_worker_assignment_v1,
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                cohort_watchdog_state=cohort_watchdog_state,
                shard_completed_callback=_mark_shard_completed,
            )
            for assignment in assignments
        }
        for assignment in assignments:
            result = futures_by_worker_id[assignment.worker_id].result()
            worker_reports.append(result.report)
            all_proposals.extend(result.proposals)
            failures.extend(result.failures)
            stage_rows.extend(result.stage_rows)

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(1 for proposal in all_proposals if proposal.status == "missing_output"),
    }
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
        "rows": stage_rows,
        "summary": _summarize_direct_rows(stage_rows),
    }
    _write_json(promotion_report, run_root / artifacts["promotion_report"])
    _write_json(telemetry, run_root / artifacts["telemetry"])
    _write_json(failures, run_root / artifacts["failures"])

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        max_turns_per_shard=1,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(asdict(manifest), run_root / artifacts["phase_manifest"])
    process_run_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=[
            dict(report.runner_result or {})
            for report in worker_reports
            if isinstance(report.runner_result, Mapping)
        ],
        stage_rows=stage_rows,
    )
    return manifest, worker_reports, process_run_payload


def _assign_workers_v1(
    *,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shards),
    )
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [
        WorkerAssignmentV1(
            worker_id=f"worker-{index + 1:03d}",
            shard_ids=tuple(bucket),
            workspace_root=str(run_root / "workers" / f"worker-{index + 1:03d}"),
        )
        for index, bucket in enumerate(buckets)
    ]


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")


def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _run_direct_knowledge_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json([asdict(shard) for shard in assigned_shards], worker_root / "assigned_shards.json")

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []

    for shard in assigned_shards:
        input_path = in_dir / f"{shard.shard_id}.json"
        _write_worker_input(path=input_path, payload=shard.input_payload, input_text=shard.input_text)
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        prompt_text = build_knowledge_direct_prompt(_coerce_dict(shard.input_payload))
        (shard_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is not None:
            run_result = _build_preflight_rejected_run_result(
                prompt_text=prompt_text,
                output_schema_path=output_schema_path,
                working_dir=worker_root,
                reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
                reason_detail=str(
                    preflight_failure.get("reason_detail") or "knowledge shard failed preflight"
                ),
            )
            _write_live_status(
                shard_root / "live_status.json",
                {
                    "state": "preflight_rejected",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                    "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
                    "elapsed_seconds": 0.0,
                    "last_event_seconds_ago": None,
                    "command_execution_count": 0,
                    "reasoning_item_count": 0,
                },
            )
        else:
            run_result = runner.run_structured_prompt(
                prompt_text=prompt_text,
                input_payload=_coerce_dict(shard.input_payload),
                working_dir=worker_root,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                workspace_task_label="knowledge review shard",
                supervision_callback=_build_strict_json_watchdog_callback(
                    live_status_path=shard_root / "live_status.json",
                    cohort_watchdog_state=cohort_watchdog_state,
                    shard_id=shard.shard_id,
                ),
            )
        _finalize_live_status(
            shard_root / "live_status.json",
            run_result=run_result,
        )

        worker_runner_results.append(
            run_result.to_payload(worker_id=assignment.worker_id, shard_id=shard.shard_id)
        )
        stage_rows.append(
            run_result.telemetry_row(worker_id=assignment.worker_id, shard_id=shard.shard_id)
        )
        primary_row = stage_rows[-1]
        primary_runner_row = None
        initial_runner_telemetry = worker_runner_results[-1].get("telemetry")
        initial_runner_rows = (
            initial_runner_telemetry.get("rows")
            if isinstance(initial_runner_telemetry, Mapping)
            else None
        )
        if isinstance(initial_runner_rows, list) and initial_runner_rows:
            first_runner_row = initial_runner_rows[0]
            if isinstance(first_runner_row, dict):
                primary_runner_row = first_runner_row
        (shard_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, shard_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), shard_root / "usage.json")
        _write_json(run_result.workspace_manifest(), shard_root / "workspace_manifest.json")

        payload, validation_errors, validation_metadata, proposal_status = (
            _evaluate_knowledge_response(
                shard=shard,
                response_text=run_result.response_text,
            )
        )
        active_run_result = run_result
        final_success_run_result = run_result
        initial_proposal_status = proposal_status
        watchdog_retry_attempted = False
        watchdog_retry_status = "not_attempted"
        watchdog_retry_examples: list[dict[str, Any]] = []
        if _should_attempt_knowledge_watchdog_retry(run_result=run_result):
            watchdog_retry_attempted = True
            watchdog_retry_examples = (
                cohort_watchdog_state.snapshot().get("successful_examples") or []
            )
            watchdog_retry_root = shard_root / "watchdog_retry"
            watchdog_retry_root.mkdir(parents=True, exist_ok=True)
            watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=shard,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                reason_code=str(run_result.supervision_reason_code or ""),
                reason_detail=str(run_result.supervision_reason_detail or ""),
                successful_examples=watchdog_retry_examples,
                live_status_path=watchdog_retry_root / "live_status.json",
            )
            _finalize_live_status(
                watchdog_retry_root / "live_status.json",
                run_result=watchdog_retry_run_result,
            )
            watchdog_retry_payload = watchdog_retry_run_result.to_payload(
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
            )
            worker_runner_results.append(watchdog_retry_payload)
            watchdog_retry_row = watchdog_retry_run_result.telemetry_row(
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
            )
            watchdog_retry_row["is_watchdog_retry_attempt"] = True
            watchdog_retry_row["watchdog_retry_attempt_index"] = 1
            stage_rows.append(watchdog_retry_row)
            watchdog_retry_runner_telemetry = watchdog_retry_payload.get("telemetry")
            watchdog_retry_runner_rows = (
                watchdog_retry_runner_telemetry.get("rows")
                if isinstance(watchdog_retry_runner_telemetry, Mapping)
                else None
            )
            if isinstance(watchdog_retry_runner_rows, list) and watchdog_retry_runner_rows:
                first_watchdog_retry_runner_row = watchdog_retry_runner_rows[0]
                if isinstance(first_watchdog_retry_runner_row, dict):
                    first_watchdog_retry_runner_row["is_watchdog_retry_attempt"] = True
                    first_watchdog_retry_runner_row["watchdog_retry_attempt_index"] = 1
            (watchdog_retry_root / "events.jsonl").write_text(
                _render_events_jsonl(watchdog_retry_run_result.events),
                encoding="utf-8",
            )
            _write_json(
                {"text": watchdog_retry_run_result.response_text},
                watchdog_retry_root / "last_message.json",
            )
            _write_json(
                dict(watchdog_retry_run_result.usage or {}),
                watchdog_retry_root / "usage.json",
            )
            _write_json(
                watchdog_retry_run_result.workspace_manifest(),
                watchdog_retry_root / "workspace_manifest.json",
            )
            (
                payload,
                validation_errors,
                validation_metadata,
                proposal_status,
            ) = _evaluate_knowledge_response(
                shard=shard,
                response_text=watchdog_retry_run_result.response_text,
            )
            watchdog_retry_row["proposal_status"] = proposal_status
            if isinstance(watchdog_retry_runner_rows, list) and watchdog_retry_runner_rows:
                first_watchdog_retry_runner_row = watchdog_retry_runner_rows[0]
                if isinstance(first_watchdog_retry_runner_row, dict):
                    first_watchdog_retry_runner_row["proposal_status"] = proposal_status
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "watchdog_retry_reason_code": run_result.supervision_reason_code,
                    "watchdog_retry_reason_detail": run_result.supervision_reason_detail,
                    "state": watchdog_retry_run_result.supervision_state or "completed",
                    "reason_code": watchdog_retry_run_result.supervision_reason_code,
                    "reason_detail": watchdog_retry_run_result.supervision_reason_detail,
                    "retryable": watchdog_retry_run_result.supervision_retryable,
                },
                watchdog_retry_root / "status.json",
            )
            watchdog_retry_status = (
                "recovered" if proposal_status == "validated" else "failed"
            )
            active_run_result = watchdog_retry_run_result
            final_success_run_result = watchdog_retry_run_result
        retry_attempted = False
        retry_status = "not_attempted"
        retry_child_shard_ids: list[str] = []
        retry_failure_rows: list[dict[str, Any]] = []
        if _should_retry_knowledge_shard_split(
            shard=shard,
            proposal_status=proposal_status,
            validation_errors=validation_errors,
            validation_metadata=validation_metadata,
            response_text=active_run_result.response_text,
        ):
            retry_attempted = True
            retry_shards = _split_failed_knowledge_shard_for_retry(
                shard,
                max_retry_chunk_count=_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD,
                max_retry_chars=_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD,
            )
            retry_child_shard_ids = [retry_shard.shard_id for retry_shard in retry_shards]
            retry_results_by_shard_id: dict[str, dict[str, Any]] = {}
            retry_all_validated = bool(retry_shards)
            for retry_index, retry_shard in enumerate(retry_shards, start=1):
                retry_root = shard_root / "retry_shards" / retry_shard.shard_id
                retry_root.mkdir(parents=True, exist_ok=True)
                retry_input_path = retry_root / "input.json"
                _write_worker_input(
                    path=retry_input_path,
                    payload=retry_shard.input_payload,
                    input_text=retry_shard.input_text,
                )
                retry_prompt_text = build_knowledge_direct_prompt(
                    _coerce_dict(retry_shard.input_payload)
                )
                (retry_root / "prompt.txt").write_text(retry_prompt_text, encoding="utf-8")
                retry_run_result = runner.run_structured_prompt(
                    prompt_text=retry_prompt_text,
                    input_payload=_coerce_dict(retry_shard.input_payload),
                    working_dir=worker_root,
                    env=env,
                    output_schema_path=output_schema_path,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    workspace_task_label="knowledge review retry shard",
                    supervision_callback=_build_strict_json_watchdog_callback(
                        live_status_path=retry_root / "live_status.json",
                    ),
                )
                _finalize_live_status(
                    retry_root / "live_status.json",
                    run_result=retry_run_result,
                )
                retry_payload_wrapper = retry_run_result.to_payload(
                    worker_id=assignment.worker_id,
                    shard_id=retry_shard.shard_id,
                )
                worker_runner_results.append(retry_payload_wrapper)
                retry_row = retry_run_result.telemetry_row(
                    worker_id=assignment.worker_id,
                    shard_id=retry_shard.shard_id,
                )
                retry_row["is_retry_attempt"] = True
                retry_row["retry_attempt_index"] = retry_index
                retry_row["retry_parent_shard_id"] = shard.shard_id
                stage_rows.append(retry_row)
                retry_runner_telemetry = retry_payload_wrapper.get("telemetry")
                retry_runner_rows = (
                    retry_runner_telemetry.get("rows")
                    if isinstance(retry_runner_telemetry, Mapping)
                    else None
                )
                if isinstance(retry_runner_rows, list) and retry_runner_rows:
                    first_retry_runner_row = retry_runner_rows[0]
                    if isinstance(first_retry_runner_row, dict):
                        first_retry_runner_row["is_retry_attempt"] = True
                        first_retry_runner_row["retry_attempt_index"] = retry_index
                        first_retry_runner_row["retry_parent_shard_id"] = shard.shard_id
                (retry_root / "events.jsonl").write_text(
                    _render_events_jsonl(retry_run_result.events),
                    encoding="utf-8",
                )
                _write_json({"text": retry_run_result.response_text}, retry_root / "last_message.json")
                _write_json(dict(retry_run_result.usage or {}), retry_root / "usage.json")
                _write_json(
                    retry_run_result.workspace_manifest(),
                    retry_root / "workspace_manifest.json",
                )
                (
                    retry_payload_candidate,
                    retry_errors,
                    retry_metadata,
                    retry_proposal_status,
                ) = _evaluate_knowledge_response(
                    shard=retry_shard,
                    response_text=retry_run_result.response_text,
                )
                retry_row["proposal_status"] = retry_proposal_status
                if isinstance(retry_runner_rows, list) and retry_runner_rows:
                    first_retry_runner_row = retry_runner_rows[0]
                    if isinstance(first_retry_runner_row, dict):
                        first_retry_runner_row["proposal_status"] = retry_proposal_status
                _write_json(
                {
                    "status": retry_proposal_status,
                    "validation_errors": list(retry_errors),
                    "validation_metadata": dict(retry_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "retry_parent_shard_id": shard.shard_id,
                    "state": retry_run_result.supervision_state or "completed",
                    "reason_code": retry_run_result.supervision_reason_code,
                    "reason_detail": retry_run_result.supervision_reason_detail,
                    "retryable": retry_run_result.supervision_retryable,
                },
                retry_root / "status.json",
            )
                if retry_proposal_status != "validated" or retry_payload_candidate is None:
                    retry_all_validated = False
                    retry_failure_rows.append(
                        {
                            "shard_id": retry_shard.shard_id,
                            "proposal_status": retry_proposal_status,
                            "validation_errors": list(retry_errors),
                            "validation_metadata": dict(retry_metadata or {}),
                        }
                    )
                    continue
                retry_results_by_shard_id[retry_shard.shard_id] = retry_payload_candidate
            if retry_all_validated:
                combined_retry_rows: list[dict[str, Any]] = []
                for retry_shard in retry_shards:
                    retry_payload_candidate = retry_results_by_shard_id.get(retry_shard.shard_id) or {}
                    chunk_rows = retry_payload_candidate.get("r")
                    if isinstance(chunk_rows, list):
                        combined_retry_rows.extend(
                            dict(row) for row in chunk_rows if isinstance(row, Mapping)
                        )
                combined_retry_payload = {
                    "v": "2",
                    "bid": shard.shard_id,
                    "r": combined_retry_rows,
                }
                (
                    payload,
                    validation_errors,
                    validation_metadata,
                    proposal_status,
                ) = _evaluate_knowledge_response(
                    shard=shard,
                    response_text=json.dumps(combined_retry_payload, sort_keys=True),
                )
                if proposal_status == "validated":
                    retry_status = "recovered"
                else:
                    retry_status = "failed"
                    retry_failure_rows.append(
                        {
                            "shard_id": shard.shard_id,
                            "proposal_status": proposal_status,
                            "validation_errors": list(validation_errors),
                            "validation_metadata": dict(validation_metadata or {}),
                        }
                    )
            else:
                retry_status = "failed"
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "retry_failures": retry_failure_rows,
                }

        repair_attempted = False
        repair_status = "not_attempted"
        if _should_attempt_knowledge_repair(
            proposal_status=proposal_status,
            validation_errors=validation_errors,
        ):
            repair_attempted = True
            repair_run_result = _run_knowledge_repair_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=shard,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                original_response_text=str(active_run_result.response_text or ""),
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                live_status_path=shard_root / "repair_live_status.json",
            )
            _finalize_live_status(
                shard_root / "repair_live_status.json",
                run_result=repair_run_result,
            )
            repair_payload = repair_run_result.to_payload(
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
            )
            worker_runner_results.append(repair_payload)
            repair_row = repair_run_result.telemetry_row(
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
            )
            repair_row["is_repair_attempt"] = True
            repair_row["repair_attempt_index"] = 1
            stage_rows.append(repair_row)
            (shard_root / "repair_events.jsonl").write_text(
                _render_events_jsonl(repair_run_result.events),
                encoding="utf-8",
            )
            _write_json(
                {"text": repair_run_result.response_text},
                shard_root / "repair_last_message.json",
            )
            _write_json(
                dict(repair_run_result.usage or {}),
                shard_root / "repair_usage.json",
            )
            _write_json(
                repair_run_result.workspace_manifest(),
                shard_root / "repair_workspace_manifest.json",
            )
            repair_payload_candidate, repair_errors, repair_metadata, repair_proposal_status = (
                _evaluate_knowledge_response(
                    shard=shard,
                    response_text=repair_run_result.response_text,
                )
            )
            repair_status = (
                "repaired" if repair_proposal_status == "validated" else "failed"
            )
            repair_row["proposal_status"] = repair_proposal_status
            repair_row["repair_attempted"] = True
            repair_row["repair_status"] = repair_status
            repair_runner_telemetry = repair_payload.get("telemetry")
            repair_runner_rows = (
                repair_runner_telemetry.get("rows")
                if isinstance(repair_runner_telemetry, Mapping)
                else None
            )
            if isinstance(repair_runner_rows, list) and repair_runner_rows:
                repair_runner_row = repair_runner_rows[0]
                if isinstance(repair_runner_row, dict):
                    repair_runner_row["proposal_status"] = repair_proposal_status
                    repair_runner_row["repair_attempted"] = True
                    repair_runner_row["repair_status"] = repair_status
                    repair_runner_row["is_repair_attempt"] = True
                    repair_runner_row["repair_attempt_index"] = 1
            _write_json(
                {
                    "attempted": True,
                    "status": repair_status,
                    "original_validation_errors": list(validation_errors),
                    "repair_validation_errors": list(repair_errors),
                    "state": repair_run_result.supervision_state or "completed",
                    "reason_code": repair_run_result.supervision_reason_code,
                    "reason_detail": repair_run_result.supervision_reason_detail,
                    "retryable": repair_run_result.supervision_retryable,
                },
                shard_root / "repair_status.json",
            )
            if repair_proposal_status == "validated":
                payload = repair_payload_candidate
                validation_errors = repair_errors
                validation_metadata = dict(repair_metadata or {})
                proposal_status = "validated"
                final_success_run_result = repair_run_result
            else:
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "repair_validation_errors": list(repair_errors),
                }
        primary_row["proposal_status"] = (
            initial_proposal_status
            if watchdog_retry_attempted or retry_attempted or repair_attempted
            else proposal_status
        )
        primary_row["final_proposal_status"] = proposal_status
        primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
        primary_row["watchdog_retry_status"] = watchdog_retry_status
        primary_row["retry_attempted"] = retry_attempted
        primary_row["retry_status"] = retry_status
        primary_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
        primary_row["repair_attempted"] = repair_attempted
        primary_row["repair_status"] = repair_status
        if primary_runner_row is not None:
            primary_runner_row["proposal_status"] = (
                initial_proposal_status
                if watchdog_retry_attempted or retry_attempted or repair_attempted
                else proposal_status
            )
            primary_runner_row["final_proposal_status"] = proposal_status
            primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
            primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
            primary_runner_row["retry_attempted"] = retry_attempted
            primary_runner_row["retry_status"] = retry_status
            primary_runner_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
            primary_runner_row["repair_attempted"] = repair_attempted
            primary_runner_row["repair_status"] = repair_status

        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        wrapper_payload = {
            "shard_id": shard.shard_id,
            "worker_id": assignment.worker_id,
            "payload": payload,
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "watchdog_retry_attempted": watchdog_retry_attempted,
            "watchdog_retry_status": watchdog_retry_status,
            "retry_attempted": retry_attempted,
            "retry_status": retry_status,
            "retry_child_shard_ids": list(retry_child_shard_ids),
            "repair_attempted": repair_attempted,
            "repair_status": repair_status,
        }
        _write_json(wrapper_payload, proposal_path)
        _write_json(
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "retry_attempted": retry_attempted,
                "retry_status": retry_status,
                "retry_child_shard_ids": list(retry_child_shard_ids),
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "state": run_result.supervision_state or "completed",
                "reason_code": run_result.supervision_reason_code,
                "reason_detail": run_result.supervision_reason_detail,
                "retryable": run_result.supervision_retryable,
            },
            shard_root / "status.json",
        )
        if proposal_status != "validated":
            worker_failure_count += 1
            reason = _failure_reason_from_run_result(
                run_result=run_result,
                proposal_status=proposal_status,
            )
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": reason,
                    "validation_errors": list(validation_errors),
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                }
            )
        else:
            worker_proposal_count += 1

        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=payload,
                validation_errors=validation_errors,
                metadata={
                    **dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "retry_attempted": retry_attempted,
                    "retry_status": retry_status,
                    "retry_child_shard_ids": list(retry_child_shard_ids),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                },
            )
        )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

        if proposal_status == "validated":
            cohort_watchdog_state.record_validated_result(
                duration_ms=final_success_run_result.duration_ms,
                example_payload=_build_knowledge_watchdog_example(
                    shard=shard,
                    payload=payload,
                ),
            )

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": output_schema_path is not None,
                "tool_affordances_requested": False,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _evaluate_knowledge_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    payload = parsed_payload
    valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
        shard,
        parsed_payload,
    )
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _preflight_knowledge_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    payload = _coerce_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    chunks = payload.get("c")
    if not owned_ids:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no owned chunk ids",
        }
    if not isinstance(chunks, list) or not chunks:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no model-facing chunks",
        }
    chunk_ids: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains a non-object chunk payload",
            }
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains a chunk without `cid`",
            }
        chunk_ids.append(chunk_id)
    if sorted(chunk_ids) != sorted(owned_ids):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard owned ids do not match chunk payload ids",
        }
    return None


def _build_preflight_rejected_run_result(
    *,
    prompt_text: str,
    output_schema_path: Path | None,
    working_dir: Path,
    reason_code: str,
    reason_detail: str,
) -> CodexExecRunResult:
    timestamp = _format_utc_now()
    return CodexExecRunResult(
        command=[],
        subprocess_exit_code=0,
        output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
        prompt_text=prompt_text,
        response_text=None,
        turn_failed_message=reason_detail,
        events=(),
        usage={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        source_working_dir=str(working_dir),
        execution_working_dir=None,
        execution_agents_path=None,
        duration_ms=0,
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
        supervision_state="preflight_rejected",
        supervision_reason_code=reason_code,
        supervision_reason_detail=reason_detail,
        supervision_retryable=False,
    )


def _build_strict_json_watchdog_callback(
    *,
    live_status_path: Path,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState | None = None,
    shard_id: str | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        decision: CodexExecSupervisionDecision | None = None
        cohort_snapshot = (
            cohort_watchdog_state.snapshot()
            if cohort_watchdog_state is not None
            else {}
        )
        cohort_completed_successful_shards = int(
            cohort_snapshot.get("completed_successful_shards") or 0
        )
        cohort_median_duration_ms = cohort_snapshot.get("median_duration_ms")
        cohort_elapsed_ratio = None
        if int(cohort_median_duration_ms or 0) > 0:
            cohort_elapsed_ratio = round(
                (snapshot.elapsed_seconds * 1000.0) / float(cohort_median_duration_ms),
                3,
            )
        if snapshot.command_execution_count > 0:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_command_execution_forbidden",
                reason_detail="strict JSON stage attempted tool use",
                retryable=True,
            )
        elif snapshot.reasoning_item_count >= 2 and not snapshot.has_final_agent_message:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_reasoning_without_output",
                reason_detail="strict JSON stage emitted repeated reasoning without a final answer",
                retryable=True,
            )
        elif (
            cohort_completed_successful_shards >= _KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0) >= _KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS
            and (snapshot.elapsed_seconds * 1000.0)
            >= (float(cohort_median_duration_ms) * _KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR)
            and not snapshot.has_final_agent_message
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_cohort_runtime_outlier",
                reason_detail=(
                    "strict JSON stage exceeded sibling median runtime without reaching final output"
                ),
                retryable=True,
            )
        _write_live_status(
            live_status_path,
            {
                "state": (
                    "watchdog_killed"
                    if isinstance(decision, CodexExecSupervisionDecision)
                    and decision.action == "terminate"
                    else "running"
                ),
                "elapsed_seconds": round(snapshot.elapsed_seconds, 3),
                "last_event_seconds_ago": (
                    round(snapshot.last_event_seconds_ago, 3)
                    if snapshot.last_event_seconds_ago is not None
                    else None
                ),
                "event_count": snapshot.event_count,
                "command_execution_count": snapshot.command_execution_count,
                "reasoning_item_count": snapshot.reasoning_item_count,
                "last_command": snapshot.last_command,
                "last_command_repeat_count": snapshot.last_command_repeat_count,
                "has_final_agent_message": snapshot.has_final_agent_message,
                "timeout_seconds": snapshot.timeout_seconds,
                "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
                "shard_id": shard_id,
                "cohort_completed_successful_shards": cohort_completed_successful_shards,
                "cohort_median_duration_ms": cohort_median_duration_ms,
                "cohort_elapsed_ratio": cohort_elapsed_ratio,
                "reason_code": decision.reason_code if decision is not None else None,
                "reason_detail": decision.reason_detail if decision is not None else None,
                "retryable": decision.retryable if decision is not None else False,
            },
        )
        return decision

    return _callback


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
) -> None:
    _write_live_status(
        live_status_path,
        {
            "state": run_result.supervision_state or "completed",
            "reason_code": run_result.supervision_reason_code,
            "reason_detail": run_result.supervision_reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
        },
    )


def _write_live_status(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(dict(payload), path)


def _failure_reason_from_run_result(
    *,
    run_result: CodexExecRunResult,
    proposal_status: str,
) -> str:
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code)
    if str(run_result.supervision_state or "").strip() in {
        "preflight_rejected",
        "watchdog_killed",
    }:
        return str(run_result.supervision_state)
    return (
        "proposal_validation_failed"
        if proposal_status == "invalid"
        else "missing_output_file"
    )


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _should_attempt_knowledge_watchdog_retry(
    *,
    run_result: CodexExecRunResult,
) -> bool:
    if str(run_result.supervision_state or "").strip() != "watchdog_killed":
        return False
    if not run_result.supervision_retryable:
        return False
    return str(run_result.supervision_reason_code or "").strip() in {
        "watchdog_command_execution_forbidden",
        "watchdog_reasoning_without_output",
        "watchdog_cohort_runtime_outlier",
    }


def _build_knowledge_watchdog_example(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    result_rows = payload.get("r")
    if not isinstance(result_rows, list):
        return None
    compact_rows = [
        dict(row_payload)
        for row_payload in result_rows[:2]
        if isinstance(row_payload, Mapping)
    ]
    if not compact_rows:
        return None
    return {
        "shard_id": shard.shard_id,
        "owned_ids": list(shard.owned_ids),
        "output": {
            "v": str(payload.get("v") or "2"),
            "bid": str(payload.get("bid") or shard.shard_id),
            "r": compact_rows,
        },
    }


def _is_pathological_knowledge_response_text(
    response_text: str,
    *,
    owned_chunk_count: int,
    returned_chunk_count: int,
) -> bool:
    cleaned = str(response_text or "")
    if not cleaned.strip():
        return False
    if re.search(rf"\s{{{_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN},}}", cleaned):
        return True
    effective_rows = max(1, int(returned_chunk_count or 0))
    chars_per_row = len(cleaned) / effective_rows
    if (
        int(owned_chunk_count or 0) > effective_rows
        and chars_per_row >= _KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW
    ):
        return True
    return False


def _should_retry_knowledge_shard_split(
    *,
    shard: ShardManifestEntryV1,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    response_text: str | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    if len(shard.owned_ids) <= 1:
        return False
    errors = {str(error) for error in validation_errors}
    if not errors.intersection(
        {
            "missing_owned_chunk_results",
            "unexpected_chunk_results",
            "response_json_invalid",
            "response_not_json_object",
        }
    ):
        return False
    returned_chunk_count = int(validation_metadata.get("result_chunk_count") or 0)
    if "missing_owned_chunk_results" in errors and returned_chunk_count < len(shard.owned_ids):
        return True
    return _is_pathological_knowledge_response_text(
        str(response_text or ""),
        owned_chunk_count=len(shard.owned_ids),
        returned_chunk_count=returned_chunk_count,
    )


def _split_failed_knowledge_shard_for_retry(
    shard: ShardManifestEntryV1,
    *,
    max_retry_chunk_count: int,
    max_retry_chars: int,
) -> tuple[ShardManifestEntryV1, ...]:
    payload = _coerce_dict(shard.input_payload)
    chunks = payload.get("c")
    if not isinstance(chunks, list):
        return ()
    normalized_max_chunks = max(1, int(max_retry_chunk_count or 1))
    normalized_max_chars = max(1, int(max_retry_chars or 1))
    retry_shards: list[ShardManifestEntryV1] = []
    current_group: list[dict[str, Any]] = []
    current_group_chars = 0

    def _flush_group(group: list[dict[str, Any]]) -> None:
        if not group:
            return
        retry_index = len(retry_shards) + 1
        retry_shard_id = f"{shard.shard_id}.retry{retry_index:02d}"
        retry_payload: dict[str, Any] = {
            "v": str(payload.get("v") or "2"),
            "bid": retry_shard_id,
            "c": [dict(chunk_payload) for chunk_payload in group],
        }
        if "x" in payload:
            retry_payload["x"] = payload["x"]
        if "g" in payload:
            retry_payload["g"] = payload["g"]
        owned_ids = tuple(
            str(chunk_payload.get("cid") or "").strip()
            for chunk_payload in group
            if str(chunk_payload.get("cid") or "").strip()
        )
        owned_block_indices = sorted(
            {
                int(block.get("i"))
                for chunk_payload in group
                for block in (chunk_payload.get("b") or [])
                if isinstance(block, Mapping) and block.get("i") is not None
            }
        )
        char_count = sum(
            len(str(block.get("t") or ""))
            for chunk_payload in group
            for block in (chunk_payload.get("b") or [])
            if isinstance(block, Mapping)
        )
        retry_shards.append(
            ShardManifestEntryV1(
                shard_id=retry_shard_id,
                owned_ids=owned_ids,
                evidence_refs=tuple(f"block:{index}" for index in owned_block_indices),
                input_payload=retry_payload,
                metadata={
                    **dict(shard.metadata or {}),
                    "owned_block_indices": list(owned_block_indices),
                    "chunk_count": len(owned_ids),
                    "char_count": char_count,
                    "retry_parent_shard_id": shard.shard_id,
                },
            )
        )

    for raw_chunk in chunks:
        if not isinstance(raw_chunk, Mapping):
            continue
        chunk_payload = dict(raw_chunk)
        chunk_char_count = sum(
            len(str(block.get("t") or ""))
            for block in (chunk_payload.get("b") or [])
            if isinstance(block, Mapping)
        )
        if current_group and (
            len(current_group) >= normalized_max_chunks
            or current_group_chars + chunk_char_count > normalized_max_chars
        ):
            _flush_group(current_group)
            current_group = []
            current_group_chars = 0
        current_group.append(chunk_payload)
        current_group_chars += chunk_char_count
    _flush_group(current_group)
    return tuple(retry_shards)


def _should_attempt_knowledge_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
) -> bool:
    if proposal_status != "invalid":
        return False
    repairable_errors = {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
    }
    return bool(set(validation_errors).intersection(repairable_errors))


def _run_knowledge_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    (worker_root / "shards" / shard.shard_id / "repair_prompt.txt").write_text(
        prompt_text,
        encoding="utf-8",
    )
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "knowledge",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "authoritative_input": _coerce_dict(shard.input_payload),
            "previous_output": _truncate_for_repair(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge repair shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _run_knowledge_watchdog_retry_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_watchdog_retry_prompt(
        shard=shard,
        reason_code=reason_code,
        reason_detail=reason_detail,
        successful_examples=successful_examples,
    )
    retry_root = worker_root / "shards" / shard.shard_id / "watchdog_retry"
    (retry_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "retry_mode": "knowledge_watchdog",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "retry_reason": {
                "code": reason_code,
                "detail": reason_detail,
            },
            "successful_examples": [dict(example_payload) for example_payload in successful_examples],
            "authoritative_input": _coerce_dict(shard.input_payload),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge watchdog retry shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _build_knowledge_watchdog_retry_prompt(
    *,
    shard: ShardManifestEntryV1,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
) -> str:
    owned_ids = ", ".join(str(chunk_id) for chunk_id in shard.owned_ids)
    example_rows = [
        json.dumps(dict(example_payload), ensure_ascii=False, sort_keys=True)
        for example_payload in successful_examples[:_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES]
        if isinstance(example_payload, Mapping)
    ]
    examples_block = (
        "\n".join(example_rows)
        if example_rows
        else "[no sibling examples available]"
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Retry the strict JSON knowledge shard after the previous attempt was stopped.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return exactly one result row for each owned chunk id.\n"
        f"- Owned chunk ids: {owned_ids}\n"
        "- Preserve chunk-local evidence and do not invent synthetic ids.\n\n"
        f"Previous stop reason: {reason_code or '[unknown]'}\n"
        f"Reason detail: {reason_detail or '[none recorded]'}\n\n"
        "Successful sibling examples:\n"
        "<BEGIN_SUCCESSFUL_SIBLING_EXAMPLES>\n"
        f"{examples_block}\n"
        "<END_SUCCESSFUL_SIBLING_EXAMPLES>\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n"
    )


def _build_knowledge_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    owned_ids = ", ".join(str(chunk_id) for chunk_id in shard.owned_ids)
    missing_ids = ", ".join(
        str(chunk_id)
        for chunk_id in (validation_metadata.get("missing_owned_chunk_ids") or [])
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Repair the invalid knowledge shard output.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return exactly one result row for each owned chunk id.\n"
        f"- Owned chunk ids: {owned_ids}\n"
        "- Preserve chunk-local evidence and do not invent synthetic ids.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        f"Missing owned chunk ids: {missing_ids or '[none recorded]'}\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_for_repair(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _truncate_for_repair(text: str, *, max_chars: int = 20_000) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "\n...[truncated]"


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _summarize_direct_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _aggregate_worker_runner_payload(
    *,
    pipeline_id: str,
    worker_runs: list[Mapping[str, Any]],
    stage_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for worker_run in worker_runs:
        telemetry = worker_run.get("telemetry")
        if not isinstance(telemetry, Mapping):
            continue
        worker_rows = telemetry.get("rows")
        if isinstance(worker_rows, list):
            rows.extend([dict(row) for row in worker_rows if isinstance(row, Mapping)])
    if stage_rows is not None:
        rows = [dict(row) for row in stage_rows if isinstance(row, Mapping)]
    return {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": [dict(payload) for payload in worker_runs],
        "telemetry": {
            "rows": rows,
            "summary": _summarize_direct_rows(rows),
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": True,
            "tool_affordances_requested": False,
        },
    }

def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            by_index[index] = dict(raw_block)
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
        )
    return root


def _non_empty(value: object, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_block_category_updates(
    *,
    outputs: Mapping[str, Any],
    allowed_block_indices: Mapping[int, str],
) -> tuple[
    dict[int, str],
    dict[int, str],
    dict[int, list[str]],
    list[dict[str, Any]],
    list[int],
]:
    normalized_allowed = {
        int(block_index): str(category or "other")
        for block_index, category in allowed_block_indices.items()
    }
    decisions_by_block: dict[int, list[tuple[str, str, str | None]]] = {}
    ignored_block_indices: list[int] = []
    for chunk_id, output in outputs.items():
        for decision in output.block_decisions:
            block_index = int(decision.block_index)
            if block_index not in normalized_allowed:
                ignored_block_indices.append(block_index)
                continue
            decisions_by_block.setdefault(block_index, []).append(
                (
                    str(chunk_id),
                    str(decision.category),
                    str(decision.reviewer_category or "").strip() or None,
                )
            )

    block_category_updates: dict[int, str] = {}
    reviewer_categories_by_block: dict[int, str] = {}
    applied_chunk_ids_by_block: dict[int, list[str]] = {}
    conflicts: list[dict[str, Any]] = []
    for block_index, decision_rows in sorted(decisions_by_block.items()):
        categories = {category for _, category, _ in decision_rows}
        if len(categories) > 1:
            conflicts.append(
                {
                    "block_index": int(block_index),
                    "seed_category": normalized_allowed.get(block_index),
                    "decisions": [
                        {
                            "chunk_id": chunk_id,
                            "category": category,
                            "reviewer_category": reviewer_category,
                        }
                        for chunk_id, category, reviewer_category in decision_rows
                    ],
                    "resolution": "kept_seed_category",
                }
            )
            continue
        block_category_updates[block_index] = next(iter(categories))
        reviewer_categories = [
            reviewer_category
            for _, _, reviewer_category in decision_rows
            if reviewer_category is not None
        ]
        if reviewer_categories:
            reviewer_categories_by_block[block_index] = reviewer_categories[0]
        applied_chunk_ids_by_block[block_index] = [
            chunk_id for chunk_id, _, _ in decision_rows
        ]
    return (
        block_category_updates,
        reviewer_categories_by_block,
        applied_chunk_ids_by_block,
        conflicts,
        ignored_block_indices,
    )
