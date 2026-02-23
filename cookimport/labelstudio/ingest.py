from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.config.run_settings import RunSettings, build_run_settings, compute_effective_workers
from cookimport.core.progress_messages import format_task_counter
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.parsing.tips import partition_tip_candidates
from cookimport.parsing.chunks import (
    chunks_from_non_recipe_blocks,
    chunks_from_topic_candidates,
)
from cookimport.parsing.epub_auto_select import (
    selected_auto_score,
    select_epub_extractor_auto,
    write_auto_extractor_artifact,
)
from cookimport.plugins import registry
from cookimport.labelstudio.block_tasks import (
    build_block_tasks,
    load_task_ids_from_jsonl,
    sample_block_tasks,
)
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    compute_freeform_task_coverage,
    resolve_segment_overlap_for_target,
    sample_freeform_tasks,
)
from cookimport.labelstudio.chunking import (
    build_extracted_archive,
    chunk_atomic,
    chunk_records_to_tasks,
    chunk_structural,
    compute_coverage,
    normalize_display_text,
    sample_chunks,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.label_config import LABEL_CONFIG_XML
from cookimport.labelstudio.label_config_blocks import build_block_label_config
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    build_freeform_label_config,
    normalize_freeform_label,
)
from cookimport.labelstudio.prelabel import (
    CodexCliProvider,
    PRELABEL_GRANULARITY_BLOCK,
    annotation_labels,
    codex_account_summary,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    codex_model_from_cmd,
    codex_reasoning_effort_from_cmd,
    default_codex_cmd,
    default_codex_reasoning_effort,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
    preflight_codex_model_access,
    prelabel_freeform_task,
    resolve_codex_model,
)
from cookimport.runs import RunManifest, RunSource, write_run_manifest
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_raw_artifacts,
    write_report,
    write_tip_outputs,
    write_topic_candidate_outputs,
)
from cookimport.staging.pdf_jobs import (
    plan_job_ranges,
    plan_pdf_page_ranges,
    reassign_recipe_ids,
)

logger = logging.getLogger(__name__)


def _task_progress_message(phase: str, current: int, total: int) -> str:
    return format_task_counter(phase, current, total, noun="task")


def _coerce_bool(value: bool | str | None, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_unstructured_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        raise ValueError(
            "Invalid epub_unstructured_html_parser_version. "
            "Expected one of: v1, v2."
        )
    return normalized


def _normalize_unstructured_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1", "semantic_v1"}:
        raise ValueError(
            "Invalid epub_unstructured_preprocess_mode. "
            "Expected one of: none, br_split_v1, semantic_v1."
        )
    return normalized


def _normalize_epub_extractor(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"unstructured", "legacy", "markdown", "auto", "markitdown"}:
        raise ValueError(
            "Invalid epub_extractor. "
            "Expected one of: unstructured, legacy, markdown, auto, markitdown."
        )
    return normalized


def _normalize_llm_recipe_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "codex-farm-3pass-v1"}:
        raise ValueError(
            "Invalid llm_recipe_pipeline. Expected one of: off, codex-farm-3pass-v1."
        )
    return normalized


def _normalize_codex_farm_failure_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"fail", "fallback"}:
        raise ValueError(
            "Invalid codex_farm_failure_mode. Expected one of: fail, fallback."
        )
    return normalized


def _normalize_codex_farm_pipeline_id(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}. Expected a non-empty pipeline id.")
    return normalized


@contextmanager
def _temporary_epub_runtime_env(
    *,
    extractor: str,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    keys = (
        "C3IMP_EPUB_EXTRACTOR",
        "C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION",
        "C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS",
        "C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["C3IMP_EPUB_EXTRACTOR"] = extractor
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _dedupe_project_name(base_name: str, existing_titles: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in existing_titles:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _resolve_project_name(path: Path, project_name: str | None, client: LabelStudioClient) -> str:
    if project_name:
        return project_name

    base_name = path.stem.strip() or _slugify_name(path.stem)
    existing_titles = {
        str(project.get("title", ""))
        for project in client.list_projects()
        if isinstance(project, dict) and project.get("title")
    }
    return _dedupe_project_name(base_name, existing_titles)


def _find_latest_manifest(output_root: Path, project_name: str) -> Path | None:
    manifests = list(output_root.glob("**/labelstudio/**/manifest.json"))
    candidates = []
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("project_name") == project_name:
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _compute_block_task_coverage(
    archive: list[Any], tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    extracted_chars = sum(len(getattr(block, "text", "") or "") for block in archive)
    chunked_chars = 0
    for task in tasks:
        data = task.get("data") if isinstance(task, dict) else {}
        if isinstance(data, dict):
            chunked_chars += len(str(data.get("block_text") or ""))
    warnings: list[str] = []
    if extracted_chars == 0:
        warnings.append("No text extracted; OCR may be required for scanned documents.")
    elif chunked_chars < extracted_chars * 0.9:
        warnings.append(
            f"Chunk coverage low: {chunked_chars} of {extracted_chars} characters represented."
        )
    return {
        "extracted_chars": extracted_chars,
        "chunked_chars": chunked_chars,
        "warnings": warnings,
    }


def _task_id_key(task_scope: str) -> str:
    if task_scope == "canonical-blocks":
        return "block_id"
    if task_scope == "freeform-spans":
        return "segment_id"
    return "chunk_id"


def _task_id_value(task: dict[str, Any], task_scope: str) -> str | None:
    key = _task_id_key(task_scope)
    data = task.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if not value:
        return None
    return str(value)


def _normalize_prelabel_upload_as(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"annotations", "predictions"}:
        raise ValueError(
            "prelabel_upload_as must be one of: annotations, predictions"
        )
    return normalized


def _strip_task_annotations(task: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(task)
    cleaned.pop("annotations", None)
    cleaned.pop("predictions", None)
    return cleaned


def _task_annotation_pairs_for_upload(
    tasks: list[dict[str, Any]],
    *,
    task_scope: str,
) -> list[tuple[str, dict[str, Any]]]:
    pairs: list[tuple[str, dict[str, Any]]] = []
    for task in tasks:
        task_id = _task_id_value(task, task_scope)
        if not task_id:
            continue
        annotations = task.get("annotations")
        if not isinstance(annotations, list) or not annotations:
            continue
        annotation = annotations[0]
        if not isinstance(annotation, dict):
            continue
        pairs.append((task_id, annotation))
    return pairs


def _annotations_to_predictions(task: dict[str, Any]) -> dict[str, Any]:
    converted = _strip_task_annotations(task)
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or not annotations:
        return converted
    annotation = annotations[0]
    if not isinstance(annotation, dict):
        return converted
    result = annotation.get("result")
    if not isinstance(result, list) or not result:
        return converted
    prediction = {
        "model_version": "cookimport-prelabel",
        "score": 1.0,
        "result": result,
    }
    meta = annotation.get("meta")
    if isinstance(meta, dict):
        prediction["meta"] = meta
    converted["predictions"] = [prediction]
    return converted


def _build_prelabel_provider(
    *,
    prelabel_provider: str,
    codex_cmd: str | None,
    codex_model: str | None,
    codex_reasoning_effort: str | None,
    prelabel_timeout_seconds: int,
    prelabel_cache_dir: Path | None,
    prelabel_track_token_usage: bool,
) -> CodexCliProvider:
    normalized_provider = prelabel_provider.strip().lower()
    if normalized_provider != "codex-cli":
        raise ValueError("prelabel_provider must be 'codex-cli'")
    base_cmd = (codex_cmd or default_codex_cmd()).strip()
    normalized_effort = normalize_codex_reasoning_effort(codex_reasoning_effort)
    resolved_model = resolve_codex_model(codex_model, cmd=base_cmd)
    resolved_cmd = codex_cmd_with_model(base_cmd, resolved_model)
    resolved_cmd = codex_cmd_with_reasoning_effort(resolved_cmd, normalized_effort)
    effective_model = codex_model_from_cmd(resolved_cmd) or resolved_model
    return CodexCliProvider(
        cmd=resolved_cmd,
        timeout_s=prelabel_timeout_seconds,
        cache_dir=prelabel_cache_dir,
        track_usage=prelabel_track_token_usage,
        model=effective_model,
    )


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_manifest_best_effort(
    run_root: Path,
    manifest: RunManifest,
    *,
    notify: Callable[[str], None] | None = None,
) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        message = f"Warning: failed to write run_manifest.json in {run_root}: {exc}"
        if notify is not None:
            notify(message)
        logger.warning(message)


def _write_processed_outputs(
    *,
    result: ConversionResult,
    path: Path,
    run_dt: dt.datetime,
    output_root: Path,
    importer_name: str,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_auto_selection: dict[str, Any] | None = None,
    epub_auto_selected_score: float | None = None,
    schemaorg_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    draft_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    llm_codex_farm: dict[str, Any] | None = None,
) -> Path:
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = output_root / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    workbook_name = path.stem
    intermediate_dir = run_root / "intermediate drafts" / workbook_name
    final_dir = run_root / "final drafts" / workbook_name
    tips_dir = run_root / "tips" / workbook_name

    if result.non_recipe_blocks:
        result.chunks = chunks_from_non_recipe_blocks(result.non_recipe_blocks)
    elif result.topic_candidates:
        result.chunks = chunks_from_topic_candidates(result.topic_candidates)

    if result.report is None:
        result.report = ConversionReport()
    result.report.importer_name = importer_name
    if run_config is not None:
        result.report.run_config = dict(run_config)
    result.report.run_config_hash = run_config_hash
    result.report.run_config_summary = run_config_summary
    result.report.llm_codex_farm = llm_codex_farm
    if epub_auto_selection is not None:
        result.report.epub_auto_selection = dict(epub_auto_selection)
    if epub_auto_selected_score is not None:
        result.report.epub_auto_selected_score = float(epub_auto_selected_score)
    result.report.run_timestamp = run_dt.isoformat(timespec="seconds")
    enrich_report_with_stats(result.report, result, path)

    output_stats = OutputStats(run_root)
    write_intermediate_outputs(
        result,
        intermediate_dir,
        output_stats=output_stats,
        schemaorg_overrides_by_recipe_id=schemaorg_overrides_by_recipe_id,
    )
    write_draft_outputs(
        result,
        final_dir,
        output_stats=output_stats,
        draft_overrides_by_recipe_id=draft_overrides_by_recipe_id,
    )
    write_tip_outputs(result, tips_dir, output_stats=output_stats)
    write_topic_candidate_outputs(result, tips_dir, output_stats=output_stats)
    if result.chunks:
        chunks_dir = run_root / "chunks" / workbook_name
        write_chunk_outputs(result.chunks, chunks_dir, output_stats=output_stats)
    write_raw_artifacts(result, run_root, output_stats=output_stats)

    if output_stats.file_counts:
        result.report.output_stats = output_stats.to_report()
    write_report(result.report, run_root, workbook_name)
    return run_root


def _resolve_pdf_page_count(path: Path) -> int | None:
    importer = registry.get_importer("pdf")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    page_count = inspection.sheets[0].page_count
    if page_count is None:
        return None
    try:
        return int(page_count)
    except (TypeError, ValueError):
        return None


def _resolve_epub_spine_count(path: Path) -> int | None:
    importer = registry.get_importer("epub")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    spine_count = inspection.sheets[0].spine_count
    if spine_count is None:
        return None
    try:
        return int(spine_count)
    except (TypeError, ValueError):
        return None


def _plan_parallel_convert_jobs(
    path: Path,
    *,
    workers: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    epub_extractor: str = "unstructured",
) -> list[dict[str, int | None]]:
    suffix = path.suffix.lower()
    selected_epub_extractor = epub_extractor.strip().lower()
    if suffix == ".pdf" and pdf_split_workers > 1 and pdf_pages_per_job > 0:
        page_count = _resolve_pdf_page_count(path)
        if page_count:
            ranges = plan_pdf_page_ranges(
                page_count,
                pdf_split_workers,
                pdf_pages_per_job,
            )
            if len(ranges) > 1:
                return [
                    {
                        "job_index": idx,
                        "start_page": start,
                        "end_page": end,
                        "start_spine": None,
                        "end_spine": None,
                    }
                    for idx, (start, end) in enumerate(ranges)
                ]
    if (
        suffix == ".epub"
        and selected_epub_extractor not in {"markitdown", "auto"}
        and epub_split_workers > 1
        and epub_spine_items_per_job > 0
    ):
        spine_count = _resolve_epub_spine_count(path)
        if spine_count:
            ranges = plan_job_ranges(
                spine_count,
                epub_split_workers,
                epub_spine_items_per_job,
            )
            if len(ranges) > 1:
                return [
                    {
                        "job_index": idx,
                        "start_page": None,
                        "end_page": None,
                        "start_spine": start,
                        "end_spine": end,
                    }
                    for idx, (start, end) in enumerate(ranges)
                ]
    return [
        {
            "job_index": 0,
            "start_page": None,
            "end_page": None,
            "start_spine": None,
            "end_spine": None,
        }
    ]


def _parallel_convert_worker(
    path: Path,
    pipeline: str,
    run_mapping: Any = None,
    *,
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

    result = importer.convert(path, run_mapping, **kwargs)
    return importer.name, result


def _job_sort_key(job: dict[str, Any]) -> tuple[int, int]:
    if job.get("start_page") is not None:
        return (0, int(job.get("start_page") or 0))
    if job.get("start_spine") is not None:
        return (1, int(job.get("start_spine") or 0))
    return (2, int(job.get("job_index") or 0))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    for recipe in result.recipes:
        if isinstance(recipe.provenance, dict):
            _offset_provenance_block_indices(recipe.provenance, offset)

    for tip in result.tip_candidates:
        if isinstance(tip.provenance, dict):
            _offset_provenance_block_indices(tip.provenance, offset)

    for topic in result.topic_candidates:
        if isinstance(topic.provenance, dict):
            _offset_provenance_block_indices(topic.provenance, offset)

    for block in result.non_recipe_blocks:
        if isinstance(block, dict):
            _offset_mapping_int(block, "index", offset)
            location = block.get("location")
            if isinstance(location, dict):
                _offset_location_fields(location, offset)

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

    for block in result.non_recipe_blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is not None:
            max_block_index = max(max_block_index, index)

    return max_block_index + 1 if max_block_index >= 0 else 0


def _merge_parallel_results(
    path: Path,
    importer_name: str,
    job_results: list[dict[str, Any]],
) -> ConversionResult:
    ordered_jobs = sorted(job_results, key=_job_sort_key)
    merged_recipes: list[Any] = []
    merged_tip_candidates: list[Any] = []
    merged_topic_candidates: list[Any] = []
    merged_non_recipe_blocks: list[Any] = []
    merged_raw_artifacts: list[Any] = []
    warnings: list[str] = []
    block_offset = 0

    for job in ordered_jobs:
        result = job["result"]
        _offset_result_block_indices(result, block_offset)
        merged_recipes.extend(result.recipes)
        merged_tip_candidates.extend(result.tip_candidates)
        merged_topic_candidates.extend(result.topic_candidates)
        merged_non_recipe_blocks.extend(result.non_recipe_blocks)
        merged_raw_artifacts.extend(result.raw_artifacts)
        block_offset += _extract_result_block_count(result)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            warnings.extend(
                f"Job {job.get('job_index')}: {error}" for error in result.report.errors
            )

    file_hash = compute_file_hash(path)
    sorted_recipes, _ = reassign_recipe_ids(
        merged_recipes,
        merged_tip_candidates,
        file_hash=file_hash,
        importer_name=importer_name,
    )
    tips, _, _ = partition_tip_candidates(merged_tip_candidates)
    report = ConversionReport(warnings=warnings)

    return ConversionResult(
        recipes=sorted_recipes,
        tips=tips,
        tip_candidates=merged_tip_candidates,
        topic_candidates=merged_topic_candidates,
        non_recipe_blocks=merged_non_recipe_blocks,
        raw_artifacts=merged_raw_artifacts,
        report=report,
        workbook=path.stem,
        workbook_path=str(path),
    )


def generate_pred_run_artifacts(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str = "auto",
    chunk_level: str = "both",
    task_scope: str = "pipeline",
    context_window: int = 1,
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    limit: int | None = None,
    sample: int | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
    ocr_device: str = "auto",
    ocr_batch_size: int = 1,
    warm_models: bool = False,
    llm_recipe_pipeline: str = "off",
    codex_farm_cmd: str = "codex-farm",
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_pass1: str = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: str = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: str = "recipe.final.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_failure_mode: str = "fail",
    processed_output_root: Path | None = None,
    prelabel: bool = False,
    prelabel_provider: str = "codex-cli",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 120,
    prelabel_cache_dir: Path | None = None,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    progress_callback: Callable[[str], None] | None = None,
    run_manifest_kind: str = "bench_pred_run",
) -> dict[str, Any]:
    """Generate prediction-run artifacts offline (no Label Studio credentials needed).

    Performs extraction, conversion, task generation and writes all artifacts to disk.
    Returns metadata dict with run_root, tasks_total, manifest_path, etc.
    """
    def _notify(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    normalized_prelabel_granularity = normalize_prelabel_granularity(prelabel_granularity)

    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    book_slug = _slugify_name(path.stem)
    run_root = output_dir / timestamp / "labelstudio" / book_slug
    run_root.mkdir(parents=True, exist_ok=True)

    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    selected_epub_extractor = _normalize_epub_extractor(
        str(epub_extractor or os.environ.get("C3IMP_EPUB_EXTRACTOR", "unstructured"))
    )
    effective_epub_extractor = selected_epub_extractor
    auto_resolution_artifact: dict[str, Any] | None = None
    auto_selection_payload: dict[str, Any] | None = None
    auto_selection_score: float | None = None
    if (
        path.suffix.lower() == ".epub"
        and selected_epub_extractor == "auto"
        and importer.name == "epub"
    ):
        resolution = select_epub_extractor_auto(path)
        effective_epub_extractor = resolution.effective_extractor
        auto_resolution_artifact = dict(resolution.artifact)

    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        str(
            epub_unstructured_html_parser_version
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", "v1")
        )
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        str(
            epub_unstructured_preprocess_mode
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", "br_split_v1")
        )
    )
    selected_skip_headers_footers = _coerce_bool(
        (
            epub_unstructured_skip_headers_footers
            if epub_unstructured_skip_headers_footers is not None
            else os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
        ),
        default=False,
    )
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_pipeline_pass1 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass1,
        field_name="codex_farm_pipeline_pass1",
    )
    selected_codex_farm_pipeline_pass2 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass2,
        field_name="codex_farm_pipeline_pass2",
    )
    selected_codex_farm_pipeline_pass3 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass3,
        field_name="codex_farm_pipeline_pass3",
    )
    run_settings = build_run_settings(
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=selected_epub_extractor,
        epub_unstructured_html_parser_version=selected_html_parser_version,
        epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
        epub_unstructured_preprocess_mode=selected_preprocess_mode,
        ocr_device=ocr_device,
        ocr_batch_size=ocr_batch_size,
        warm_models=warm_models,
        llm_recipe_pipeline=selected_llm_recipe_pipeline,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
        codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
        codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_failure_mode=selected_codex_farm_failure_mode,
        all_epub=path.suffix.lower() == ".epub",
        effective_workers=compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=effective_epub_extractor,
            all_epub=path.suffix.lower() == ".epub",
        ),
    )
    run_config = run_settings.to_run_config_dict()
    run_config["epub_extractor_requested"] = selected_epub_extractor
    run_config["epub_extractor_effective"] = effective_epub_extractor
    run_config_hash = hashlib.sha256(
        json.dumps(
            run_config,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    run_config_summary = " | ".join(
        f"{key}={'true' if value is True else 'false' if value is False else value}"
        for key, value in sorted(run_config.items())
    )
    run_mapping: MappingConfig | None = None
    if path.suffix.lower() == ".pdf":
        run_mapping = MappingConfig(
            ocr_device=run_settings.ocr_device.value,
            ocr_batch_size=run_settings.ocr_batch_size,
        )

    with _temporary_epub_runtime_env(
        extractor=effective_epub_extractor,
        html_parser_version=selected_html_parser_version,
        skip_headers_footers=selected_skip_headers_footers,
        preprocess_mode=selected_preprocess_mode,
    ):
        job_specs = _plan_parallel_convert_jobs(
            path,
            workers=workers,
            pdf_split_workers=pdf_split_workers,
            epub_split_workers=epub_split_workers,
            pdf_pages_per_job=pdf_pages_per_job,
            epub_spine_items_per_job=epub_spine_items_per_job,
            epub_extractor=effective_epub_extractor,
        )
        if len(job_specs) == 1:
            result = importer.convert(path, run_mapping, progress_callback=progress_callback)
        else:
            _notify(
                f"Running {len(job_specs)} split job(s) with up to {max(1, workers)} workers..."
            )
            effective_workers = max(1, workers)
            if path.suffix.lower() == ".epub":
                effective_workers = max(effective_workers, epub_split_workers)
            if path.suffix.lower() == ".pdf":
                effective_workers = max(effective_workers, pdf_split_workers)
            max_workers = min(effective_workers, len(job_specs))
            job_results: list[dict[str, Any]] = []
            job_errors: list[str] = []

            def _run_job_serial(spec: dict[str, int | None]) -> None:
                importer_name, job_result = _parallel_convert_worker(
                    path,
                    pipeline,
                    run_mapping,
                    start_page=spec.get("start_page"),
                    end_page=spec.get("end_page"),
                    start_spine=spec.get("start_spine"),
                    end_spine=spec.get("end_spine"),
                )
                job_results.append(
                    {**spec, "result": job_result, "importer_name": importer_name}
                )

            try:
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(
                            _parallel_convert_worker,
                            path,
                            pipeline,
                            run_mapping,
                            start_page=spec.get("start_page"),
                            end_page=spec.get("end_page"),
                            start_spine=spec.get("start_spine"),
                            end_spine=spec.get("end_spine"),
                        ): spec
                        for spec in job_specs
                    }
                    completed = 0
                    for future in as_completed(futures):
                        spec = futures[future]
                        try:
                            importer_name, job_result = future.result()
                        except Exception as exc:
                            job_errors.append(
                                f"job {spec.get('job_index', '?')}: {exc}"
                            )
                            continue
                        job_results.append(
                            {
                                **spec,
                                "result": job_result,
                                "importer_name": importer_name,
                            }
                        )
                        completed += 1
                        _notify(f"Completed split job {completed}/{len(job_specs)}")
            except PermissionError:
                for spec in job_specs:
                    try:
                        _run_job_serial(spec)
                    except Exception as exc:  # noqa: BLE001
                        job_errors.append(
                            f"job {spec.get('job_index', '?')}: {exc}"
                        )
                    _notify(f"Completed split job {len(job_results)}/{len(job_specs)}")

            if job_errors:
                raise RuntimeError("Split conversion failed: " + "; ".join(job_errors))
            if not job_results:
                raise RuntimeError("Split conversion produced no results.")

            importer_name = str(job_results[0].get("importer_name") or importer.name)
            result = _merge_parallel_results(path, importer_name, job_results)
            _notify("Merged split job results.")

    llm_schema_overrides: dict[str, dict[str, Any]] | None = None
    llm_draft_overrides: dict[str, dict[str, Any]] | None = None
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
    if run_settings.llm_recipe_pipeline.value != "off":
        _notify("Running codex-farm recipe pipeline...")
        try:
            llm_apply = run_codex_farm_recipe_pipeline(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=book_slug,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}"
                )
                if result.report is None:
                    result.report = ConversionReport()
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
    if result.report is None:
        result.report = ConversionReport()
    result.report.llm_codex_farm = llm_report

    _notify("Building extracted archive...")
    archive = build_extracted_archive(result, result.raw_artifacts)
    _notify("Computing source file hash...")
    file_hash = compute_file_hash(path)
    if auto_resolution_artifact is not None:
        auto_selection_payload = {
            **auto_resolution_artifact,
            "source_file": str(path),
            "source_hash": file_hash,
        }
        auto_selection_score = selected_auto_score(auto_selection_payload)
        write_auto_extractor_artifact(
            run_root=run_root,
            source_hash=file_hash,
            artifact=auto_selection_payload,
        )
    if auto_selection_payload is not None:
        if result.report is None:
            result.report = ConversionReport()
        result.report.epub_auto_selection = dict(auto_selection_payload)
        if auto_selection_score is not None:
            result.report.epub_auto_selected_score = float(auto_selection_score)
    book_id = result.workbook or path.stem
    processed_run_root: Path | None = None
    processed_report_path: Path | None = None
    if processed_output_root is not None:
        _notify("Writing processed cookbook outputs...")
        processed_run_root = _write_processed_outputs(
            result=result,
            path=path,
            run_dt=run_dt,
            output_root=processed_output_root,
            importer_name=importer.name,
            run_config=run_config,
            run_config_hash=run_config_hash,
            run_config_summary=run_config_summary,
            epub_auto_selection=auto_selection_payload,
            epub_auto_selected_score=auto_selection_score,
            schemaorg_overrides_by_recipe_id=llm_schema_overrides,
            draft_overrides_by_recipe_id=llm_draft_overrides,
            llm_codex_farm=llm_report,
        )
        processed_report_path = (
            processed_run_root / f"{path.stem}.excel_import_report.json"
        )
        _notify("Processed cookbook outputs complete.")

    scopes = {"pipeline", "canonical-blocks", "freeform-spans"}
    if task_scope not in scopes:
        raise ValueError(
            "task_scope must be one of: pipeline, canonical-blocks, freeform-spans"
        )
    if prelabel and task_scope != "freeform-spans":
        raise ValueError("prelabel is only supported for task_scope=freeform-spans")

    tasks: list[dict[str, Any]] = []
    task_ids: list[str] = []
    coverage_payload: dict[str, Any]
    label_config = LABEL_CONFIG_XML
    chunk_ids: list[str] | None = None
    block_ids: list[str] | None = None
    segment_ids: list[str] | None = None
    prelabel_report_path: Path | None = None
    prelabel_errors_path: Path | None = None
    prelabel_prompt_log_path: Path | None = None
    prelabel_summary: dict[str, Any] | None = None
    resolved_segment_focus_blocks: int | None = None
    effective_segment_overlap: int | None = None

    if task_scope == "pipeline":
        levels = {"structural", "atomic", "both"}
        if chunk_level not in levels:
            raise ValueError("chunk_level must be one of: structural, atomic, both")

        _notify("Generating pipeline chunk candidates...")
        chunks = []
        if chunk_level in {"structural", "both"}:
            chunks.extend(
                chunk_structural(
                    result,
                    archive,
                    source_file=path.name,
                    book_id=book_id,
                    pipeline_used=importer.name,
                    file_hash=file_hash,
                )
            )
        if chunk_level in {"atomic", "both"}:
            chunks.extend(
                chunk_atomic(
                    result,
                    archive,
                    source_file=path.name,
                    book_id=book_id,
                    pipeline_used=importer.name,
                    file_hash=file_hash,
                )
            )

        if not chunks:
            raise RuntimeError("No chunks generated for labeling.")

        _notify("Computing pipeline chunk coverage...")
        coverage = compute_coverage(archive, chunks)
        coverage_payload = {
            "extracted_chars": coverage.extracted_chars,
            "chunked_chars": coverage.chunked_chars,
            "warnings": coverage.warnings,
        }
        if coverage.extracted_chars == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )

        _notify("Sampling chunk candidates...")
        chunks = sample_chunks(chunks, limit=limit, sample=sample)
        if not chunks:
            raise RuntimeError("No chunks generated after limit/sample filters.")

        _notify("Building Label Studio pipeline tasks...")
        tasks = chunk_records_to_tasks(chunks, source_hash=file_hash)
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        task_ids = list(chunk_ids)
    elif task_scope == "canonical-blocks":
        if chunk_level != "both":
            _notify("canonical-blocks ignores --chunk-level")
        if not archive:
            raise RuntimeError("No extracted blocks available for canonical labeling.")
        _notify("Building canonical block tasks...")
        tasks_all = build_block_tasks(
            archive,
            source_hash=file_hash,
            source_file=path.name,
            context_window=context_window,
        )
        if not tasks_all:
            raise RuntimeError("No block tasks generated for labeling.")
        coverage_payload = _compute_block_task_coverage(archive, tasks_all)
        if coverage_payload["extracted_chars"] == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )
        _notify("Sampling canonical block tasks...")
        tasks = sample_block_tasks(tasks_all, limit=limit, sample=sample)
        if not tasks:
            raise RuntimeError("No block tasks generated after limit/sample filters.")
        label_config = build_block_label_config()
        block_ids = [task.get("data", {}).get("block_id") for task in tasks if task]
        task_ids = [block_id for block_id in block_ids if block_id]
    else:
        if chunk_level != "both":
            _notify("freeform-spans ignores --chunk-level")
        if not archive:
            raise RuntimeError("No extracted blocks available for freeform labeling.")
        if segment_focus_blocks is None:
            resolved_segment_focus_blocks = segment_blocks
        else:
            resolved_segment_focus_blocks = int(segment_focus_blocks)
        if resolved_segment_focus_blocks < 1:
            raise ValueError("segment_focus_blocks must be >= 1")
        if resolved_segment_focus_blocks > segment_blocks:
            raise ValueError("segment_focus_blocks must be <= segment_blocks")
        effective_segment_overlap = resolve_segment_overlap_for_target(
            total_blocks=len(archive),
            segment_blocks=segment_blocks,
            requested_overlap=segment_overlap,
            target_task_count=target_task_count,
        )
        if (
            target_task_count is not None
            and effective_segment_overlap != segment_overlap
        ):
            _notify(
                "Adjusted freeform overlap to "
                f"{effective_segment_overlap} "
                f"(requested {segment_overlap}, target tasks {target_task_count})."
            )
        _notify("Building freeform span tasks...")
        tasks_all = build_freeform_span_tasks(
            archive=archive,
            source_hash=file_hash,
            source_file=path.name,
            book_id=book_id,
            segment_blocks=segment_blocks,
            segment_overlap=effective_segment_overlap,
            segment_focus_blocks=resolved_segment_focus_blocks,
        )
        if not tasks_all:
            raise RuntimeError("No freeform span tasks generated for labeling.")
        coverage_payload = compute_freeform_task_coverage(archive, tasks_all)
        if coverage_payload["extracted_chars"] == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )
        _notify("Sampling freeform span tasks...")
        tasks = sample_freeform_tasks(tasks_all, limit=limit, sample=sample)
        if not tasks:
            raise RuntimeError(
                "No freeform span tasks generated after limit/sample filters."
            )
        if prelabel:
            total_prelabel_tasks = len(tasks)
            _notify(
                _task_progress_message(
                    "Running freeform prelabeling...",
                    0,
                    total_prelabel_tasks,
                )
            )
            provider_cache_dir = prelabel_cache_dir or (run_root / "prelabel_cache")
            provider = _build_prelabel_provider(
                prelabel_provider=prelabel_provider,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
                codex_reasoning_effort=codex_reasoning_effort,
                prelabel_timeout_seconds=prelabel_timeout_seconds,
                prelabel_cache_dir=provider_cache_dir,
                prelabel_track_token_usage=prelabel_track_token_usage,
            )
            provider_cmd = str(
                getattr(provider, "cmd", (codex_cmd or default_codex_cmd()).strip())
            )
            _notify("Checking freeform prelabel model access...")
            preflight_codex_model_access(
                cmd=provider_cmd,
                timeout_s=min(30, max(1, int(prelabel_timeout_seconds))),
            )
            provider_model = getattr(
                provider,
                "model",
                resolve_codex_model(codex_model, cmd=provider_cmd),
            )
            provider_reasoning_effort = codex_reasoning_effort_from_cmd(provider_cmd)
            if provider_reasoning_effort is None:
                provider_reasoning_effort = normalize_codex_reasoning_effort(
                    codex_reasoning_effort
                )
            if provider_reasoning_effort is None:
                provider_reasoning_effort = default_codex_reasoning_effort(
                    cmd=provider_cmd
                )
            provider_account = codex_account_summary(provider_cmd)
            prelabel_prompt_log_path = run_root / "prelabel_prompt_log.jsonl"
            prelabel_prompt_log_path.write_text("", encoding="utf-8")
            prelabel_prompt_log_count = 0
            prelabel_errors: list[dict[str, Any]] = []
            prelabel_label_counts: dict[str, int] = {}
            prelabel_success = 0
            for task_index, task in enumerate(tasks, start=1):
                _notify(
                    _task_progress_message(
                        "Running freeform prelabeling...",
                        task_index,
                        total_prelabel_tasks,
                    )
                )
                segment_id = _task_id_value(task, "freeform-spans") or "<unknown>"
                prompt_task_index = task_index
                prompt_segment_id = segment_id

                def _write_prompt_log(entry: dict[str, Any]) -> None:
                    nonlocal prelabel_prompt_log_count
                    payload = dict(entry)
                    payload.setdefault("segment_id", prompt_segment_id)
                    payload["task_index"] = prompt_task_index
                    payload["task_total"] = total_prelabel_tasks
                    payload["logged_at"] = dt.datetime.now(
                        tz=dt.timezone.utc
                    ).isoformat(timespec="seconds")
                    payload["codex_cmd"] = provider_cmd
                    payload["codex_model"] = provider_model
                    payload["codex_reasoning_effort"] = provider_reasoning_effort
                    payload["codex_account"] = provider_account
                    with prelabel_prompt_log_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(
                                payload,
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                            + "\n"
                        )
                    prelabel_prompt_log_count += 1

                try:
                    annotation = prelabel_freeform_task(
                        task,
                        provider=provider,
                        allowed_labels=set(FREEFORM_ALLOWED_LABELS),
                        prelabel_granularity=normalized_prelabel_granularity,
                        prompt_log_callback=_write_prompt_log,
                    )
                except Exception as exc:  # noqa: BLE001
                    prelabel_errors.append(
                        {"segment_id": segment_id, "reason": str(exc)}
                    )
                    continue
                if annotation is None:
                    prelabel_errors.append(
                        {
                            "segment_id": segment_id,
                            "reason": "No valid labels produced by provider output.",
                        }
                    )
                    continue
                task["annotations"] = [annotation]
                prelabel_success += 1
                for label in sorted(annotation_labels(annotation)):
                    prelabel_label_counts[label] = prelabel_label_counts.get(label, 0) + 1

            prelabel_errors_path = run_root / "prelabel_errors.jsonl"
            if prelabel_errors:
                prelabel_errors_path.write_text(
                    "\n".join(
                        json.dumps(row, sort_keys=True) for row in prelabel_errors
                    )
                    + "\n",
                    encoding="utf-8",
                )
            else:
                prelabel_errors_path.write_text("", encoding="utf-8")
            provider_usage = None
            usage_summary = getattr(provider, "usage_summary", None)
            if callable(usage_summary):
                provider_usage = usage_summary()

            prelabel_summary = {
                "enabled": True,
                "provider": prelabel_provider,
                "granularity": normalized_prelabel_granularity,
                "codex_cmd": provider_cmd,
                "codex_model": provider_model,
                "codex_reasoning_effort": provider_reasoning_effort,
                "codex_account": provider_account,
                "cache_dir": str(provider_cache_dir),
                "task_count": len(tasks),
                "success_count": prelabel_success,
                "failure_count": len(prelabel_errors),
                "allow_partial": bool(prelabel_allow_partial),
                "token_usage_enabled": bool(prelabel_track_token_usage),
                "token_usage": provider_usage if prelabel_track_token_usage else None,
                "label_counts": prelabel_label_counts,
                "errors_path": str(prelabel_errors_path),
                "prompt_log_path": str(prelabel_prompt_log_path),
                "prompt_log_count": prelabel_prompt_log_count,
            }
            prelabel_report_path = run_root / "prelabel_report.json"
            prelabel_report_path.write_text(
                json.dumps(prelabel_summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            if prelabel_errors and not prelabel_allow_partial:
                raise RuntimeError(
                    "Prelabeling failed for one or more tasks. "
                    "Re-run with prelabel_allow_partial=True "
                    "(CLI: --prelabel-allow-partial) to continue "
                    "while recording failures."
                )

        label_config = build_freeform_label_config()
        segment_ids = [task.get("data", {}).get("segment_id") for task in tasks if task]
        task_ids = [segment_id for segment_id in segment_ids if segment_id]

    _notify("Writing prediction run artifacts...")
    archive_path = run_root / "extracted_archive.json"
    archive_payload = [
        {
            "index": block.index,
            "text": block.text,
            "location": block.location,
            "source_kind": block.source_kind,
        }
        for block in archive
    ]
    archive_path.write_text(
        json.dumps(archive_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    extracted_text = "\n\n".join(block.text for block in archive if block.text)
    (run_root / "extracted_text.txt").write_text(
        normalize_display_text(extracted_text) + "\n", encoding="utf-8"
    )

    tasks_path = run_root / "label_studio_tasks.jsonl"
    tasks_path.write_text(
        "\n".join(json.dumps(task) for task in tasks) + "\n", encoding="utf-8"
    )

    coverage_path = run_root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            coverage_payload,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = {
        "pipeline": importer.name,
        "importer_name": importer.name,
        "source_file": str(path),
        "source_hash": file_hash,
        "book_id": book_id,
        "recipe_count": len(result.recipes),
        "tip_count": len(result.tips),
        "run_timestamp": run_dt.isoformat(timespec="seconds"),
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "llm_codex_farm": llm_report,
        "epub_auto_selection": auto_selection_payload,
        "epub_auto_selected_score": auto_selection_score,
        "processed_run_root": (
            str(processed_run_root) if processed_run_root is not None else None
        ),
        "processed_report_path": (
            str(processed_report_path) if processed_report_path is not None else None
        ),
        "chunk_level": chunk_level if task_scope == "pipeline" else None,
        "task_scope": task_scope,
        "context_window": context_window if task_scope == "canonical-blocks" else None,
        "segment_blocks": segment_blocks if task_scope == "freeform-spans" else None,
        "segment_focus_blocks": (
            resolved_segment_focus_blocks if task_scope == "freeform-spans" else None
        ),
        "segment_overlap": (
            effective_segment_overlap if task_scope == "freeform-spans" else None
        ),
        "segment_overlap_requested": (
            segment_overlap if task_scope == "freeform-spans" else None
        ),
        "segment_overlap_effective": (
            effective_segment_overlap if task_scope == "freeform-spans" else None
        ),
        "target_task_count": (
            target_task_count if task_scope == "freeform-spans" else None
        ),
        "task_count": len(tasks),
        "task_ids": task_ids,
        "chunk_ids": chunk_ids,
        "block_ids": block_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": (
            str(prelabel_report_path) if prelabel_report_path is not None else None
        ),
        "prelabel_errors_path": (
            str(prelabel_errors_path) if prelabel_errors_path is not None else None
        ),
        "prelabel_prompt_log_path": (
            str(prelabel_prompt_log_path) if prelabel_prompt_log_path is not None else None
        ),
    }

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl": "label_studio_tasks.jsonl",
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": "extracted_archive.json",
        "extracted_text": "extracted_text.txt",
    }
    if prelabel_report_path is not None:
        run_manifest_artifacts["prelabel_report_json"] = _path_for_manifest(
            run_root, prelabel_report_path
        )
    if prelabel_errors_path is not None:
        run_manifest_artifacts["prelabel_errors_jsonl"] = _path_for_manifest(
            run_root, prelabel_errors_path
        )
    if prelabel_prompt_log_path is not None:
        run_manifest_artifacts["prelabel_prompt_log_jsonl"] = _path_for_manifest(
            run_root, prelabel_prompt_log_path
        )
    processed_run_path = _path_for_manifest(run_root, processed_run_root)
    if processed_run_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_path
    processed_report_manifest_path = _path_for_manifest(run_root, processed_report_path)
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path
    llm_manifest_path = (
        run_root
        / "raw"
        / "llm"
        / _slugify_name(path.stem)
        / "llm_manifest.json"
    )
    if llm_manifest_path.exists():
        run_manifest_artifacts["llm_manifest_json"] = _path_for_manifest(
            run_root,
            llm_manifest_path,
        )

    run_manifest_payload = RunManifest(
        run_kind=run_manifest_kind,
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=file_hash,
            importer_name=importer.name,
        ),
        run_config=run_config,
        artifacts=run_manifest_artifacts,
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Prediction run artifacts complete.")

    return {
        "run_root": run_root,
        "processed_run_root": processed_run_root,
        "processed_report_path": processed_report_path,
        "epub_auto_selection": auto_selection_payload,
        "epub_auto_selected_score": auto_selection_score,
        "tasks_total": len(tasks),
        "manifest_path": manifest_path,
        "tasks": tasks,
        "task_ids": task_ids,
        "chunk_ids": chunk_ids,
        "block_ids": block_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": prelabel_report_path,
        "prelabel_errors_path": prelabel_errors_path,
        "prelabel_prompt_log_path": prelabel_prompt_log_path,
        "label_config": label_config,
        "importer_name": importer.name,
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "llm_codex_farm": llm_report,
        "book_id": book_id,
        "file_hash": file_hash,
        "segment_focus_blocks": resolved_segment_focus_blocks,
        "segment_overlap_requested": segment_overlap if task_scope == "freeform-spans" else None,
        "segment_overlap_effective": effective_segment_overlap,
        "target_task_count": target_task_count if task_scope == "freeform-spans" else None,
    }


def run_labelstudio_import(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str,
    project_name: str | None,
    chunk_level: str,
    task_scope: str,
    context_window: int,
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    overwrite: bool,
    resume: bool,
    label_studio_url: str,
    label_studio_api_key: str,
    limit: int | None,
    sample: int | None,
    progress_callback: Callable[[str], None] | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
    ocr_device: str = "auto",
    ocr_batch_size: int = 1,
    warm_models: bool = False,
    llm_recipe_pipeline: str = "off",
    codex_farm_cmd: str = "codex-farm",
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_pass1: str = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: str = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: str = "recipe.final.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_failure_mode: str = "fail",
    processed_output_root: Path | None = None,
    prelabel: bool = False,
    prelabel_provider: str = "codex-cli",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 120,
    prelabel_cache_dir: Path | None = None,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_upload_as: str = "annotations",
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    auto_project_name_on_scope_mismatch: bool = False,
    allow_labelstudio_write: bool = False,
) -> dict[str, Any]:
    def _notify(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    if not allow_labelstudio_write:
        raise RuntimeError(
            "Label Studio write blocked. Re-run with explicit upload consent "
            "(allow_labelstudio_write=True)."
        )

    # Generate all artifacts offline first
    pred = generate_pred_run_artifacts(
        path=path,
        output_dir=output_dir,
        pipeline=pipeline,
        chunk_level=chunk_level,
        task_scope=task_scope,
        context_window=context_window,
        segment_blocks=segment_blocks,
        segment_overlap=segment_overlap,
        segment_focus_blocks=segment_focus_blocks,
        target_task_count=target_task_count,
        limit=limit,
        sample=sample,
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=epub_extractor,
        epub_unstructured_html_parser_version=epub_unstructured_html_parser_version,
        epub_unstructured_skip_headers_footers=epub_unstructured_skip_headers_footers,
        epub_unstructured_preprocess_mode=epub_unstructured_preprocess_mode,
        ocr_device=ocr_device,
        ocr_batch_size=ocr_batch_size,
        warm_models=warm_models,
        llm_recipe_pipeline=llm_recipe_pipeline,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_pass1=codex_farm_pipeline_pass1,
        codex_farm_pipeline_pass2=codex_farm_pipeline_pass2,
        codex_farm_pipeline_pass3=codex_farm_pipeline_pass3,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_failure_mode=codex_farm_failure_mode,
        processed_output_root=processed_output_root,
        prelabel=prelabel,
        prelabel_provider=prelabel_provider,
        codex_cmd=codex_cmd,
        codex_model=codex_model,
        codex_reasoning_effort=codex_reasoning_effort,
        prelabel_timeout_seconds=prelabel_timeout_seconds,
        prelabel_cache_dir=prelabel_cache_dir,
        prelabel_granularity=prelabel_granularity,
        prelabel_allow_partial=prelabel_allow_partial,
        prelabel_track_token_usage=prelabel_track_token_usage,
        progress_callback=progress_callback,
        run_manifest_kind="labelstudio_import",
    )

    run_root = pred["run_root"]
    tasks = pred["tasks"]
    label_config = pred["label_config"]
    upload_as = _normalize_prelabel_upload_as(prelabel_upload_as)

    # Label Studio upload
    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    _notify("Resolving Label Studio project...")
    project_title = _resolve_project_name(path, project_name, client)

    existing_project = client.find_project_by_title(project_title)
    if overwrite and existing_project:
        client.delete_project(existing_project["id"])
        existing_project = None

    had_existing_project = existing_project is not None
    project = existing_project
    if project is None:
        project = client.create_project(
            project_title,
            label_config,
            description="Cookbook benchmarking project (auto-generated)",
        )

    project_id = project.get("id")
    if project_id is None:
        raise RuntimeError("Label Studio project creation failed (missing id).")

    existing_task_ids: set[str] = set()
    resume_source: str | None = None
    if resume and not overwrite and had_existing_project:
        _notify("Checking resume metadata for existing tasks...")
        manifest_path = _find_latest_manifest(output_dir, project_title)
        if manifest_path and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            resume_scope = payload.get("task_scope", "pipeline")
            if resume_scope != task_scope:
                if auto_project_name_on_scope_mismatch and project_name is None:
                    _notify(
                        f"Existing project uses task_scope={resume_scope}; "
                        f"creating a new project for task_scope={task_scope}."
                    )
                    existing_titles = {
                        str(candidate.get("title", ""))
                        for candidate in client.list_projects()
                        if isinstance(candidate, dict) and candidate.get("title")
                    }
                    project_title = _dedupe_project_name(project_title, existing_titles)
                    project = client.create_project(
                        project_title,
                        label_config,
                        description="Cookbook benchmarking project (auto-generated)",
                    )
                    project_id = project.get("id")
                    if project_id is None:
                        raise RuntimeError("Label Studio project creation failed (missing id).")
                    had_existing_project = False
                else:
                    raise RuntimeError(
                        f"Existing project uses task_scope={resume_scope}; "
                        "use a matching task_scope or a new project name."
                    )
            else:
                resume_source = str(manifest_path)
                existing_task_ids = set(
                    payload.get("segment_ids")
                    or []
                ) or set(
                    payload.get("block_ids")
                    or payload.get("chunk_ids")
                    or payload.get("task_ids")
                    or []
                )
                tasks_path = manifest_path.parent / "label_studio_tasks.jsonl"
                if not existing_task_ids and tasks_path.exists():
                    existing_task_ids = load_task_ids_from_jsonl(
                        tasks_path, _task_id_key(task_scope)
                    )

    upload_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_id = _task_id_value(task, task_scope)
        if task_id and task_id in existing_task_ids:
            continue
        if prelabel and task_scope == "freeform-spans" and upload_as == "predictions":
            upload_tasks.append(_annotations_to_predictions(task))
        else:
            upload_tasks.append(task)

    batch_size = 200
    uploaded_count = 0
    inline_annotation_fallback = False
    inline_annotation_fallback_error: str | None = None
    post_import_annotation_pairs: list[tuple[str, dict[str, Any]]] = []
    post_import_annotations_created = 0
    post_import_annotation_errors: list[str] = []
    if upload_tasks:
        total_batches = (len(upload_tasks) + batch_size - 1) // batch_size
        _notify(f"Uploading {len(upload_tasks)} task(s) in {total_batches} batch(es)...")
    else:
        _notify("No new tasks to upload (resume skipped existing tasks).")
    for start in range(0, len(upload_tasks), batch_size):
        batch = upload_tasks[start : start + batch_size]
        if not batch:
            continue
        use_inline_annotations = (
            prelabel
            and task_scope == "freeform-spans"
            and upload_as == "annotations"
        )
        if use_inline_annotations:
            if inline_annotation_fallback:
                client.import_tasks(
                    project_id,
                    [_strip_task_annotations(task) for task in batch],
                )
                post_import_annotation_pairs.extend(
                    _task_annotation_pairs_for_upload(batch, task_scope=task_scope)
                )
            else:
                try:
                    client.import_tasks(project_id, batch)
                except Exception as exc:  # noqa: BLE001
                    inline_annotation_fallback = True
                    inline_annotation_fallback_error = str(exc)
                    _notify(
                        "Inline annotation import failed; retrying with "
                        "task-only upload and post-import annotation creation."
                    )
                    client.import_tasks(
                        project_id,
                        [_strip_task_annotations(task) for task in batch],
                    )
                    post_import_annotation_pairs.extend(
                        _task_annotation_pairs_for_upload(batch, task_scope=task_scope)
                    )
        else:
            client.import_tasks(project_id, batch)
        uploaded_count += len(batch)
        _notify(f"Uploaded {uploaded_count}/{len(upload_tasks)} task(s).")

    if inline_annotation_fallback and post_import_annotation_pairs:
        _notify("Resolving task IDs for post-import annotation creation...")
        remote_tasks = client.list_project_tasks(project_id)
        remote_task_ids: dict[str, int] = {}
        for remote_task in remote_tasks:
            if not isinstance(remote_task, dict):
                continue
            task_id = _task_id_value(remote_task, task_scope)
            if not task_id:
                continue
            remote_id = remote_task.get("id")
            try:
                remote_task_ids[task_id] = int(remote_id)
            except (TypeError, ValueError):
                continue

        _notify(
            f"Creating {len(post_import_annotation_pairs)} annotation(s) "
            "through Label Studio API..."
        )
        for task_id_value, annotation in post_import_annotation_pairs:
            labelstudio_task_id = remote_task_ids.get(task_id_value)
            if labelstudio_task_id is None:
                post_import_annotation_errors.append(
                    f"task id lookup failed for {task_id_value}"
                )
                continue
            try:
                client.create_annotation(labelstudio_task_id, annotation)
                post_import_annotations_created += 1
            except Exception as exc:  # noqa: BLE001
                post_import_annotation_errors.append(
                    f"task {task_id_value}: {exc}"
                )

        if post_import_annotation_errors:
            if prelabel_allow_partial:
                _notify(
                    "Warning: some post-import annotations failed and were skipped."
                )
            else:
                joined = "; ".join(post_import_annotation_errors[:8])
                raise RuntimeError(
                    "Post-import annotation creation failed: "
                    + joined
                )

    # Update manifest with LS-specific fields
    manifest_path = pred["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "project_name": project_title,
        "project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "resume_source": resume_source,
        "label_studio_url": label_studio_url,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_inline_annotations_fallback_error": inline_annotation_fallback_error,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    })
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    project_path = run_root / "project.json"
    project_path.write_text(
        json.dumps(project, indent=2, sort_keys=True), encoding="utf-8"
    )
    run_config_payload = pred.get("run_config")
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}
    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl": "label_studio_tasks.jsonl",
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": "extracted_archive.json",
        "extracted_text": "extracted_text.txt",
        "project_json": "project.json",
        "label_studio_project_name": project_title,
        "label_studio_project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    }
    prelabel_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_report_path"),
    )
    if prelabel_report_manifest_path:
        run_manifest_artifacts["prelabel_report_json"] = prelabel_report_manifest_path
    prelabel_errors_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_errors_path"),
    )
    if prelabel_errors_manifest_path:
        run_manifest_artifacts["prelabel_errors_jsonl"] = prelabel_errors_manifest_path
    prelabel_prompt_log_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_prompt_log_path"),
    )
    if prelabel_prompt_log_manifest_path:
        run_manifest_artifacts["prelabel_prompt_log_jsonl"] = (
            prelabel_prompt_log_manifest_path
        )
    processed_run_manifest_path = _path_for_manifest(run_root, pred.get("processed_run_root"))
    if processed_run_manifest_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_manifest_path
    processed_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("processed_report_path"),
    )
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path

    run_manifest_payload = RunManifest(
        run_kind="labelstudio_import",
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=str(pred.get("file_hash") or "") or None,
            importer_name=str(pred.get("importer_name") or "") or None,
        ),
        run_config=run_config_payload,
        artifacts=run_manifest_artifacts,
        notes="Label Studio import run with upload metadata.",
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Label Studio import artifacts complete.")

    return {
        "project": project,
        "project_name": project_title,
        "project_id": project_id,
        "run_root": run_root,
        "processed_run_root": pred["processed_run_root"],
        "processed_report_path": pred["processed_report_path"],
        "run_config": pred.get("run_config"),
        "run_config_hash": pred.get("run_config_hash"),
        "run_config_summary": pred.get("run_config_summary"),
        "prelabel": pred.get("prelabel"),
        "prelabel_report_path": pred.get("prelabel_report_path"),
        "prelabel_errors_path": pred.get("prelabel_errors_path"),
        "prelabel_prompt_log_path": pred.get("prelabel_prompt_log_path"),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_errors": post_import_annotation_errors,
        "tasks_total": pred["tasks_total"],
        "tasks_uploaded": uploaded_count,
        "manifest_path": manifest_path,
    }
