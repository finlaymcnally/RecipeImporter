from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from cookimport.config.run_settings import RunSettings
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
    CodexExecRunResult,
    CodexExecRunner,
    SubprocessCodexExecRunner,
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


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class CodexFarmKnowledgeHarvestResult:
    llm_report: dict[str, Any]
    llm_raw_dir: Path
    manifest_path: Path
    refined_stage_result: NonRecipeStageResult
    write_report: KnowledgeWriteReport | None = None


def run_codex_farm_knowledge_harvest(
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
) -> CodexFarmKnowledgeHarvestResult:
    """Optional knowledge stage: harvest cooking knowledge from Stage 7 spans via codex-farm."""
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    manifest_path = llm_raw_dir / KNOWLEDGE_MANIFEST_FILE_NAME

    if run_settings.llm_knowledge_pipeline.value == "off":
        return CodexFarmKnowledgeHarvestResult(
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
        )

    knowledge_stage_dir = llm_raw_dir / stage_artifact_stem("extract_knowledge_optional")
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
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_nonrecipe_spans",
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmKnowledgeHarvestResult(
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
            "Cannot run codex-farm knowledge harvest: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    codex_runner: CodexExecRunner = runner or SubprocessCodexExecRunner(cmd="codex exec")
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

    if build_report.shards_written == 0:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="all_chunks_skipped",
            skipped_chunk_count=build_report.skipped_chunk_count,
            skipped_lane_counts=dict(build_report.skipped_lane_counts),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmKnowledgeHarvestResult(
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
    phase_manifest = None
    worker_reports: list[dict[str, Any]] = []
    process_run_payload: dict[str, Any] | None = None
    try:
        phase_manifest, phase_worker_reports, process_run_payload = _run_direct_knowledge_workers_v1(
            phase_key="extract_knowledge_optional",
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
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            build_report=build_report,
            elapsed_seconds=elapsed_seconds,
            error=str(exc),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmKnowledgeHarvestResult(
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
            "jobs_written": build_report.jobs_written,
            "shards_written": build_report.shards_written,
            "chunks_written": build_report.chunks_written,
            "jobs_skipped": build_report.skipped_chunk_count,
            "outputs_parsed": len(outputs),
            "chunks_missing": len(missing_chunk_ids),
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
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "snippets_path": str(write_report.snippets_path),
            "preview_path": str(write_report.preview_path),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": missing_chunk_ids,
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "refinement_report": dict(refined_stage_result.refinement_report),
        "process_run": process_run_payload,
        "phase_worker_runtime": {
            "phase_key": "extract_knowledge_optional",
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

    return CodexFarmKnowledgeHarvestResult(
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
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    stage_status: str,
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
            "jobs_written": 0,
            "shards_written": 0,
            "chunks_written": 0,
            "jobs_skipped": int(skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": 0,
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
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": [],
        "skipped_lane_counts": dict(skipped_lane_counts or {}),
        "stage_status": stage_status,
        "phase_worker_runtime": {
            "phase_key": "extract_knowledge_optional",
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
            "jobs_written": int(build_report.jobs_written),
            "shards_written": int(build_report.shards_written),
            "chunks_written": int(build_report.chunks_written),
            "jobs_skipped": int(build_report.skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": int(build_report.chunks_written),
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
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": list(build_report.chunk_ids),
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "stage_status": "runtime_failed",
        "error": error,
        "phase_worker_runtime": {
            "phase_key": "extract_knowledge_optional",
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

    for assignment in assignments:
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
        worker_runner_results: list[dict[str, Any]] = []

        for shard in assigned_shards:
            input_path = in_dir / f"{shard.shard_id}.json"
            _write_worker_input(path=input_path, payload=shard.input_payload, input_text=shard.input_text)
            shard_root = shard_dir / shard.shard_id
            shard_root.mkdir(parents=True, exist_ok=True)
            prompt_text = build_knowledge_direct_prompt(_coerce_dict(shard.input_payload))
            (shard_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")

            run_result = runner.run_structured_prompt(
                prompt_text=prompt_text,
                input_payload=_coerce_dict(shard.input_payload),
                working_dir=worker_root,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
            )

            worker_runner_results.append(run_result.to_payload(worker_id=assignment.worker_id, shard_id=shard.shard_id))
            stage_rows.append(run_result.telemetry_row(worker_id=assignment.worker_id, shard_id=shard.shard_id))
            (shard_root / "events.jsonl").write_text(_render_events_jsonl(run_result.events), encoding="utf-8")
            _write_json({"text": run_result.response_text}, shard_root / "last_message.json")
            _write_json(dict(run_result.usage or {}), shard_root / "usage.json")

            payload: dict[str, Any] | None = None
            validation_errors: tuple[str, ...] = ()
            validation_metadata: dict[str, Any] = {}
            proposal_status = "validated"
            response_text = str(run_result.response_text or "").strip()
            if not response_text:
                validation_errors = ("missing_output_file",)
                proposal_status = "missing_output"
            else:
                try:
                    parsed_payload = json.loads(response_text)
                except json.JSONDecodeError as exc:
                    validation_errors = ("response_json_invalid",)
                    validation_metadata = {"parse_error": str(exc)}
                    proposal_status = "invalid"
                else:
                    if isinstance(parsed_payload, dict):
                        payload = parsed_payload
                        valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
                            shard,
                            parsed_payload,
                        )
                        proposal_status = "validated" if valid else "invalid"
                    else:
                        validation_errors = ("response_not_json_object",)
                        validation_metadata = {"response_type": type(parsed_payload).__name__}
                        proposal_status = "invalid"

            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            wrapper_payload = {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            }
            _write_json(wrapper_payload, proposal_path)
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                },
                shard_root / "status.json",
            )
            if proposal_status != "validated":
                worker_failure_count += 1
                reason = (
                    "proposal_validation_failed"
                    if proposal_status == "invalid"
                    else "missing_output_file"
                )
                failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": reason,
                        "validation_errors": list(validation_errors),
                    }
                )
            else:
                worker_proposal_count += 1

            all_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status=proposal_status,
                    proposal_path=_relative_path(run_root, proposal_path),
                    payload=payload,
                    validation_errors=validation_errors,
                    metadata=dict(validation_metadata or {}),
                )
            )

        worker_runner_payload = _aggregate_worker_runner_payload(
            pipeline_id=pipeline_id,
            worker_runs=worker_runner_results,
        )
        _write_json(worker_runner_payload, worker_root / "status.json")
        worker_reports.append(
            WorkerExecutionReportV1(
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
            )
        )

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


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _summarize_direct_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    summary = {
        "call_count": len(rows),
        "tokens_input": 0,
        "tokens_cached_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_total": 0,
    }
    for row in rows:
        summary["tokens_input"] += int(row.get("tokens_input") or 0)
        summary["tokens_cached_input"] += int(row.get("tokens_cached_input") or 0)
        summary["tokens_output"] += int(row.get("tokens_output") or 0)
        summary["tokens_reasoning"] += int(row.get("tokens_reasoning") or 0)
        summary["tokens_total"] += int(row.get("tokens_total") or 0)
    return summary


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
) -> tuple[dict[int, str], dict[int, list[str]], list[dict[str, Any]], list[int]]:
    normalized_allowed = {
        int(block_index): str(category or "other")
        for block_index, category in allowed_block_indices.items()
    }
    decisions_by_block: dict[int, list[tuple[str, str]]] = {}
    ignored_block_indices: list[int] = []
    for chunk_id, output in outputs.items():
        for decision in output.block_decisions:
            block_index = int(decision.block_index)
            if block_index not in normalized_allowed:
                ignored_block_indices.append(block_index)
                continue
            decisions_by_block.setdefault(block_index, []).append(
                (str(chunk_id), str(decision.category))
            )

    block_category_updates: dict[int, str] = {}
    applied_chunk_ids_by_block: dict[int, list[str]] = {}
    conflicts: list[dict[str, Any]] = []
    for block_index, decision_rows in sorted(decisions_by_block.items()):
        categories = {category for _, category in decision_rows}
        if len(categories) > 1:
            conflicts.append(
                {
                    "block_index": int(block_index),
                    "seed_category": normalized_allowed.get(block_index),
                    "decisions": [
                        {"chunk_id": chunk_id, "category": category}
                        for chunk_id, category in decision_rows
                    ],
                    "resolution": "kept_seed_category",
                }
            )
            continue
        block_category_updates[block_index] = next(iter(categories))
        applied_chunk_ids_by_block[block_index] = [
            chunk_id for chunk_id, _ in decision_rows
        ]
    return (
        block_category_updates,
        applied_chunk_ids_by_block,
        conflicts,
        ignored_block_indices,
    )
