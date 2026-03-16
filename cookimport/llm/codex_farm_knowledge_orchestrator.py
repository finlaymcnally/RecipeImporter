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
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult

from .codex_farm_ids import sanitize_for_filename
from .codex_farm_knowledge_ingest import read_knowledge_outputs
from .codex_farm_knowledge_jobs import (
    COMPACT_KNOWLEDGE_JOB_FORMAT,
    LEGACY_KNOWLEDGE_JOB_FORMAT,
    build_knowledge_jobs,
)
from .codex_farm_knowledge_writer import KnowledgeWriteReport, write_knowledge_artifacts
from .codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)

logger = logging.getLogger(__name__)

LEGACY_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.v1"
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
    if not nonrecipe_stage_result.knowledge_spans:
        llm_report = {
            "enabled": True,
            "pipeline": run_settings.llm_knowledge_pipeline.value,
            "pipeline_id": pipeline_id,
            "input_mode": "stage7_knowledge_spans",
            "counts": {
                "jobs_written": 0,
                "jobs_skipped": 0,
                "outputs_parsed": 0,
                "chunks_missing": 0,
                "snippets_written": 0,
            },
            "timing": {"total_seconds": 0.0},
            "paths": {
                "knowledge_in_dir": str(knowledge_in_dir),
                "knowledge_out_dir": str(knowledge_out_dir),
                "manifest_path": str(manifest_path),
            },
            "missing_chunk_ids": [],
            "stage_status": "no_knowledge_spans",
        }
        _write_json(llm_report, manifest_path)
        return CodexFarmKnowledgeHarvestResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
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
        knowledge_spans=nonrecipe_stage_result.knowledge_spans,
        recipe_spans=recipe_spans,
        workbook_slug=workbook_slug,
        source_hash=_resolve_source_hash(conversion_result),
        out_dir=knowledge_in_dir,
        context_blocks=run_settings.codex_farm_knowledge_context_blocks,
        overrides=overrides,
        job_format=_resolve_knowledge_job_format(pipeline_id),
    )

    if build_report.jobs_written == 0:
        llm_report = {
            "enabled": True,
            "pipeline": run_settings.llm_knowledge_pipeline.value,
            "pipeline_id": pipeline_id,
            "input_mode": "stage7_knowledge_spans",
            "output_schema_path": output_schema_path,
            "counts": {
                "jobs_written": 0,
                "jobs_skipped": build_report.skipped_chunk_count,
                "outputs_parsed": 0,
                "chunks_missing": 0,
                "snippets_written": 0,
            },
            "timing": {"total_seconds": 0.0},
            "paths": {
                "knowledge_in_dir": str(knowledge_in_dir),
                "knowledge_out_dir": str(knowledge_out_dir),
                "manifest_path": str(manifest_path),
            },
            "missing_chunk_ids": [],
            "skipped_lane_counts": dict(build_report.skipped_lane_counts),
            "stage_status": "all_chunks_skipped",
        }
        _write_json(llm_report, manifest_path)
        return CodexFarmKnowledgeHarvestResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            write_report=None,
        )

    process_run = codex_runner.run_pipeline(
        pipeline_id,
        knowledge_in_dir,
        knowledge_out_dir,
        env,
        root_dir=pipeline_root,
        workspace_root=workspace_root,
        model=codex_model,
        reasoning_effort=codex_reasoning_effort,
    )
    process_run_payload = as_pipeline_run_result_payload(process_run)

    outputs = read_knowledge_outputs(knowledge_out_dir)
    missing_chunk_ids = sorted(set(build_report.chunk_ids) - set(outputs))

    write_report = write_knowledge_artifacts(
        run_root=run_root,
        workbook_slug=workbook_slug,
        outputs=outputs,
        full_blocks_by_index=full_blocks_by_index,
        chunk_lane_by_id=build_report.chunk_lane_by_id,
    )

    elapsed_seconds = round(time.perf_counter() - started, 3)
    llm_report = {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_knowledge_spans",
        "output_schema_path": output_schema_path,
        "counts": {
            "jobs_written": build_report.jobs_written,
            "jobs_skipped": build_report.skipped_chunk_count,
            "outputs_parsed": len(outputs),
            "chunks_missing": len(missing_chunk_ids),
            "snippets_written": write_report.snippets_written,
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_out_dir": str(knowledge_out_dir),
            "snippets_path": str(write_report.snippets_path),
            "preview_path": str(write_report.preview_path),
            "manifest_path": str(manifest_path),
        },
        "missing_chunk_ids": missing_chunk_ids,
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "process_run": process_run_payload,
    }
    _write_json(llm_report, manifest_path)

    return CodexFarmKnowledgeHarvestResult(
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
        manifest_path=manifest_path,
        write_report=write_report,
    )


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_knowledge_job_format(pipeline_id: str) -> str:
    if str(pipeline_id).strip() == COMPACT_KNOWLEDGE_PIPELINE_ID:
        return COMPACT_KNOWLEDGE_JOB_FORMAT
    return LEGACY_KNOWLEDGE_JOB_FORMAT


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
