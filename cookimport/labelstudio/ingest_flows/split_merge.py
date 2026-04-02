from __future__ import annotations

from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
)
from cookimport.core.models import ConversionReport, ConversionResult
from cookimport.core.reporting import finalize_report_totals
from cookimport.core.source_model import (
    normalize_source_blocks,
    offset_source_blocks,
    offset_source_support,
)
from cookimport.labelstudio.ingest_support import _coerce_int
from cookimport.plugins import registry


def _parallel_convert_worker(
    path: Path,
    pipeline: str,
    run_mapping: Any = None,
    *,
    run_config: dict[str, Any] | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    start_spine: int | None = None,
    end_spine: int | None = None,
) -> tuple[str, ConversionResult]:
    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    kwargs: dict[str, Any] = {"progress_callback": None}
    if start_page is not None or end_page is not None:
        kwargs["start_page"] = start_page
        kwargs["end_page"] = end_page
    if start_spine is not None or end_spine is not None:
        kwargs["start_spine"] = start_spine
        kwargs["end_spine"] = end_spine

    run_settings = RunSettings.from_dict(
        project_run_config_payload(
            run_config,
            contract=RUN_SETTING_CONTRACT_FULL,
        ),
        warn_context="labelstudio split run config",
    )
    kwargs["run_settings"] = run_settings
    result = importer.convert(path, run_mapping, **kwargs)
    return importer.name, result

def _job_sort_key(job: dict[str, Any]) -> tuple[int, int]:
    if job.get("start_page") is not None:
        return (0, int(job.get("start_page") or 0))
    if job.get("start_spine") is not None:
        return (1, int(job.get("start_spine") or 0))
    return (2, int(job.get("job_index") or 0))

def _offset_mapping_int(payload: dict[str, Any], key: str, offset: int) -> None:
    value = _coerce_int(payload.get(key))
    if value is None:
        return
    payload[key] = value + offset

def _offset_location_fields(location: dict[str, Any], offset: int) -> None:
    for key in (
        "start_block",
        "end_block",
        "block_index",
        "startBlock",
        "endBlock",
        "blockIndex",
        "tip_block_index",
        "tipBlockIndex",
    ):
        _offset_mapping_int(location, key, offset)

def _offset_provenance_block_indices(provenance: dict[str, Any], offset: int) -> None:
    location = provenance.get("location")
    if isinstance(location, dict):
        _offset_location_fields(location, offset)

    atom = provenance.get("atom")
    if isinstance(atom, dict):
        _offset_mapping_int(atom, "block_index", offset)
        _offset_mapping_int(atom, "blockIndex", offset)

    _offset_mapping_int(provenance, "tip_block_index", offset)
    _offset_mapping_int(provenance, "tipBlockIndex", offset)

def _offset_result_block_indices(result: ConversionResult, offset: int) -> None:
    if offset <= 0:
        return
    result.source_blocks = offset_source_blocks(result.source_blocks, offset)
    result.source_support = offset_source_support(result.source_support, offset)

    for recipe in result.recipes:
        if isinstance(recipe.provenance, dict):
            _offset_provenance_block_indices(recipe.provenance, offset)

    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        _offset_location_fields(content, offset)
        blocks = content.get("blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                _offset_mapping_int(block, "index", offset)
                _offset_location_fields(block, offset)

def _extract_result_block_count(result: ConversionResult) -> int:
    if result.source_blocks:
        max_order_index = max(
            (int(block.order_index) for block in result.source_blocks),
            default=-1,
        )
        return max_order_index + 1 if max_order_index >= 0 else 0
    for artifact in result.raw_artifacts:
        metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
        if metadata.get("artifact_type") != "extracted_blocks":
            continue
        content = artifact.content
        if not isinstance(content, dict):
            continue
        block_count = _coerce_int(content.get("block_count"))
        if block_count is not None and block_count > 0:
            return block_count
        blocks = content.get("blocks")
        if isinstance(blocks, list) and blocks:
            return len(blocks)

    max_block_index = -1

    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            index = _coerce_int(block.get("index"))
            if index is not None:
                max_block_index = max(max_block_index, index)

    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        location = provenance.get("location")
        if not isinstance(location, dict):
            continue
        start = _coerce_int(location.get("start_block"))
        end = _coerce_int(location.get("end_block"))
        if start is not None:
            max_block_index = max(max_block_index, start)
        if end is not None:
            max_block_index = max(max_block_index, end)

    return max_block_index + 1 if max_block_index >= 0 else 0

def _merge_parallel_results(
    path: Path,
    importer_name: str,
    job_results: list[dict[str, Any]],
) -> ConversionResult:
    ordered_jobs = sorted(job_results, key=_job_sort_key)
    merged_source_blocks: list[Any] = []
    merged_source_support: list[Any] = []
    merged_raw_artifacts: list[Any] = []
    warnings: list[str] = []
    block_offset = 0

    for job in ordered_jobs:
        result = job["result"]
        _offset_result_block_indices(result, block_offset)
        merged_source_blocks.extend(result.source_blocks)
        merged_source_support.extend(result.source_support)
        merged_raw_artifacts.extend(result.raw_artifacts)
        block_offset += _extract_result_block_count(result)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            warnings.extend(
                f"Job {job.get('job_index')}: {error}" for error in result.report.errors
            )
    report = ConversionReport(warnings=warnings)

    merged_result = ConversionResult(
        recipes=[],
        source_blocks=normalize_source_blocks(merged_source_blocks),
        source_support=list(merged_source_support),
        raw_artifacts=merged_raw_artifacts,
        report=report,
        workbook=path.stem,
        workbook_path=str(path),
    )
    finalize_report_totals(report, merged_result, standalone_block_count=0)

    return merged_result
