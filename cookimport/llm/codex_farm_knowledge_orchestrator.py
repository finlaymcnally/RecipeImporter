from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
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
from .codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from .phase_worker_runtime import run_phase_workers_v1

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
    runner: CodexFarmRunner | None = None,
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
    knowledge_out_dir = knowledge_stage_dir / "out"
    knowledge_in_dir.mkdir(parents=True, exist_ok=True)
    knowledge_out_dir.mkdir(parents=True, exist_ok=True)

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
            knowledge_out_dir=knowledge_out_dir,
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
    codex_runner: CodexFarmRunner = runner or SubprocessCodexFarmRunner(
        cmd=run_settings.codex_farm_cmd,
        progress_callback=progress_callback,
    )
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
            knowledge_out_dir=knowledge_out_dir,
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

    worker_count = max(1, int(run_settings.knowledge_worker_count or 1))
    phase_manifest = None
    worker_reports: list[dict[str, Any]] = []
    process_run_payload: dict[str, Any] | None = None
    try:
        phase_manifest, phase_worker_reports = run_phase_workers_v1(
            phase_key="extract_knowledge_optional",
            pipeline_id=pipeline_id,
            run_root=knowledge_stage_dir,
            shards=build_report.shard_entries,
            runner=codex_runner,
            worker_count=worker_count,
            root_dir=pipeline_root,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            max_turns_per_shard=run_settings.knowledge_shard_max_turns,
            proposal_validator=validate_knowledge_shard_output,
            settings={
                "llm_knowledge_pipeline": run_settings.llm_knowledge_pipeline.value,
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
            }
            for report in phase_worker_reports
        ]
        process_payloads = [
            dict(report.runner_result or {})
            for report in phase_worker_reports
            if isinstance(report.runner_result, Mapping)
        ]
        if len(process_payloads) == 1:
            process_run_payload = process_payloads[0]
        elif process_payloads:
            process_run_payload = {
                "runtime_mode": "phase_worker_runtime_v1",
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "pipeline_id": pipeline_id,
                "worker_runs": process_payloads,
            }
    except CodexFarmRunnerError as exc:
        elapsed_seconds = round(time.perf_counter() - started, 3)
        llm_report = _build_runtime_failed_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_out_dir=knowledge_out_dir,
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

    outputs, validated_payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(
        knowledge_stage_dir / "proposals"
    )
    _materialize_validated_knowledge_outputs(
        out_dir=knowledge_out_dir,
        payloads_by_shard_id=validated_payloads_by_shard_id,
    )
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
            "knowledge_out_dir": str(knowledge_out_dir),
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
    knowledge_out_dir: Path,
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
            "knowledge_out_dir": str(knowledge_out_dir),
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
    knowledge_out_dir: Path,
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
            "knowledge_out_dir": str(knowledge_out_dir),
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


def _materialize_validated_knowledge_outputs(
    *,
    out_dir: Path,
    payloads_by_shard_id: Mapping[str, dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sorted(out_dir.glob("*.json")):
        stale_path.unlink()
    for shard_id, payload in sorted(payloads_by_shard_id.items()):
        _write_json(payload, out_dir / f"{shard_id}.json")


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
