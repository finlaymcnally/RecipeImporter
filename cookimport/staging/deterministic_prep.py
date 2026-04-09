from __future__ import annotations

import datetime as dt
import inspect
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.codex_decision import BUCKET1_FIXED_BEHAVIOR_VERSION
from cookimport.config.prediction_identity import ALL_METHOD_PREDICTION_IDENTITY_FIELDS
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_adapters import (
    build_benchmark_call_kwargs_from_run_settings,
)
from cookimport.config.run_settings_contracts import summarize_run_config_payload
from cookimport.core.models import ConversionResult, SourceBlock, SourceSupport
from cookimport.core.reporting import compute_file_hash
from cookimport.core.slug import slugify_name
from cookimport.core.source_model import (
    normalize_source_blocks,
    normalize_source_support,
    source_blocks_to_rows,
)
from cookimport.llm.prompt_preview import write_prompt_preview_for_existing_run
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
    LabelFirstStageResult,
    RecipeSpan,
    RecipeSpanDecision,
)
from cookimport.paths import resolve_book_cache_root
from cookimport.staging.book_cache import (
    acquire_entry_lock,
    build_preview_cache_key,
    deterministic_prep_artifact_root,
    entry_lock_path,
    preview_cache_manifest_path,
    read_json_dict,
    release_entry_lock,
    stable_json_sha256,
    wait_for_entry,
    write_json_atomic,
)
from cookimport.staging.pipeline_runtime import ExtractedBookBundle, RecipeBoundaryResult
from cookimport.staging.recipe_ownership import recipe_ownership_from_payload
from cookimport.staging.output_names import (
    LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME,
    LINE_ROLE_PIPELINE_DIR_NAME,
)

_DETERMINISTIC_PREP_BUNDLE_SCHEMA_VERSION = "deterministic_prep_bundle.v2"
_DETERMINISTIC_PREP_KEY_SCHEMA_VERSION = "deterministic_prep_key.v2"
_DETERMINISTIC_PREP_MANIFEST_FILE_NAME = "deterministic_prep_bundle_manifest.json"
_DETERMINISTIC_PREP_CONVERSION_RESULT_FILE_NAME = "conversion_result.json"
_PREVIEW_DIR_NAME = "prompt-preview"
_DETERMINISTIC_PREP_EXCLUDED_FIELDS = {
    "llm_recipe_pipeline",
    "llm_knowledge_pipeline",
    "line_role_pipeline",
    "atomic_block_splitter",
    "line_role_codex_exec_style",
    "knowledge_codex_exec_style",
    "codex_farm_recipe_mode",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
    "codex_farm_failure_mode",
}
_DETERMINISTIC_PREP_INCLUDED_FIELDS = tuple(
    field_name
    for field_name in ALL_METHOD_PREDICTION_IDENTITY_FIELDS
    if field_name not in _DETERMINISTIC_PREP_EXCLUDED_FIELDS
)
_GENERATE_PRED_RUN_ARTIFACTS_PARAMETER_NAMES: frozenset[str] | None = None
_CURRENT_PREVIEW_MANIFEST_SCHEMA_VERSION = "codex_prompt_preview.v3"


@dataclass(frozen=True, slots=True)
class DeterministicPrepBundleResult:
    prep_key: str
    source_file: Path
    source_hash: str
    workbook_slug: str
    importer_name: str
    artifact_root: Path
    manifest_path: Path
    processed_run_root: Path
    prediction_run_root: Path
    conversion_result_path: Path
    processed_report_path: Path | None
    stage_block_predictions_path: Path | None
    cache_hit: bool
    timing: dict[str, float]
    deterministic_settings: dict[str, Any]
    book_cache_root: Path | None = None
    conversion_cache_summary: dict[str, Any] | None = None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    return read_json_dict(path)


def _preview_manifest_is_current(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if str(payload.get("schema_version") or "").strip() != _CURRENT_PREVIEW_MANIFEST_SCHEMA_VERSION:
        return False
    phase_plans = payload.get("phase_plans")
    return isinstance(phase_plans, Mapping)


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _single_path(paths: Sequence[Path]) -> Path:
    existing = [path for path in paths if path.exists()]
    if len(existing) != 1:
        raise ValueError(f"Expected exactly one matching path, found {len(existing)}")
    return existing[0]


def _workbook_slug_candidates(processed_run_root: Path, workbook_slug: str) -> tuple[Path, ...]:
    return (
        processed_run_root / "raw" / "source" / workbook_slug,
        processed_run_root / "label_refine" / workbook_slug,
        processed_run_root / "label_deterministic" / workbook_slug,
        processed_run_root / "recipe_boundary" / workbook_slug,
        processed_run_root / "recipe_authority" / workbook_slug,
        processed_run_root / LINE_ROLE_PIPELINE_DIR_NAME,
        processed_run_root / ".bench" / workbook_slug,
    )


def _resolve_cached_workbook_slug(processed_run_root: Path, workbook_slug: str) -> str:
    candidate = str(workbook_slug or "").strip()
    if not candidate:
        return candidate
    if any(path.exists() for path in _workbook_slug_candidates(processed_run_root, candidate)):
        return candidate
    normalized = slugify_name(candidate)
    if normalized != candidate and any(
        path.exists() for path in _workbook_slug_candidates(processed_run_root, normalized)
    ):
        return normalized
    return candidate


def _preview_manifest_key(selected_settings: RunSettings) -> str:
    return build_preview_cache_key(selected_settings)


def _deterministic_settings_payload(run_settings: RunSettings) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    run_config["bucket1_fixed_behavior_version"] = BUCKET1_FIXED_BEHAVIOR_VERSION
    return {
        "schema_version": _DETERMINISTIC_PREP_KEY_SCHEMA_VERSION,
        "settings": {
            key: run_config.get(key)
            for key in _DETERMINISTIC_PREP_INCLUDED_FIELDS
            if key in run_config
        },
    }


def build_deterministic_prep_key(
    *,
    source_file: Path,
    source_hash: str,
    run_settings: RunSettings,
) -> str:
    del source_file
    return stable_json_sha256(
        {
            "schema_version": _DETERMINISTIC_PREP_KEY_SCHEMA_VERSION,
            "source_hash": str(source_hash),
            "deterministic_settings": _deterministic_settings_payload(run_settings),
        }
    )


def _bundle_result_from_manifest(
    manifest_path: Path,
    *,
    cache_hit: bool,
) -> DeterministicPrepBundleResult | None:
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        manifest = _read_json(manifest_path)
    except Exception:  # noqa: BLE001
        return None
    if (
        str(manifest.get("schema_version") or "").strip()
        != _DETERMINISTIC_PREP_BUNDLE_SCHEMA_VERSION
    ):
        return None
    processed_run_root = Path(
        str(manifest.get("processed_run_root") or "")
    ).expanduser()
    prediction_run_root = Path(
        str(manifest.get("prediction_run_root") or "")
    ).expanduser()
    conversion_result_path = Path(
        str(manifest.get("conversion_result_path") or "")
    ).expanduser()
    if (
        not processed_run_root.exists()
        or not processed_run_root.is_dir()
        or not conversion_result_path.exists()
        or not conversion_result_path.is_file()
    ):
        return None
    processed_report_raw = str(manifest.get("processed_report_path") or "").strip()
    stage_predictions_raw = str(
        manifest.get("stage_block_predictions_path") or ""
    ).strip()
    timing_payload = _coerce_dict(manifest.get("timing"))
    book_cache_root_raw = str(manifest.get("book_cache_root") or "").strip()
    workbook_slug = _resolve_cached_workbook_slug(
        processed_run_root,
        str(manifest.get("workbook_slug") or "").strip(),
    )
    return DeterministicPrepBundleResult(
        prep_key=str(manifest.get("prep_key") or "").strip(),
        source_file=Path(str(manifest.get("source_file") or "")).expanduser(),
        source_hash=str(manifest.get("source_hash") or "").strip(),
        workbook_slug=workbook_slug,
        importer_name=str(manifest.get("importer_name") or "").strip(),
        artifact_root=manifest_path.parent,
        manifest_path=manifest_path,
        processed_run_root=processed_run_root,
        prediction_run_root=prediction_run_root,
        conversion_result_path=conversion_result_path,
        processed_report_path=(
            Path(processed_report_raw).expanduser() if processed_report_raw else None
        ),
        stage_block_predictions_path=(
            Path(stage_predictions_raw).expanduser() if stage_predictions_raw else None
        ),
        cache_hit=cache_hit,
        timing={
            key: value
            for key, raw_value in timing_payload.items()
            if (value := _coerce_float(raw_value)) is not None
        },
        deterministic_settings=_coerce_dict(manifest.get("deterministic_settings")),
        book_cache_root=(
            Path(book_cache_root_raw).expanduser() if book_cache_root_raw else None
        ),
        conversion_cache_summary=_coerce_dict(manifest.get("conversion_cache")),
    )


def load_deterministic_prep_bundle(
    manifest_path: Path | str,
) -> DeterministicPrepBundleResult:
    result = _bundle_result_from_manifest(Path(manifest_path).expanduser(), cache_hit=True)
    if result is None:
        raise ValueError(
            f"Deterministic prep bundle manifest is missing or invalid: {manifest_path}"
        )
    return result


def _manifest_path_for_prep_key(
    *,
    source_hash: str,
    prep_key: str,
    book_cache_root: Path | str | None,
) -> Path:
    return (
        deterministic_prep_artifact_root(
            book_cache_root=book_cache_root,
            source_hash=source_hash,
            prep_key=prep_key,
        )
        / _DETERMINISTIC_PREP_MANIFEST_FILE_NAME
    )


def load_existing_deterministic_prep_bundle(
    *,
    source_file: Path,
    run_settings: RunSettings,
    source_hash: str | None = None,
    book_cache_root: Path | str | None = None,
) -> DeterministicPrepBundleResult | None:
    resolved_source_file = source_file.expanduser()
    resolved_source_hash = source_hash or compute_file_hash(resolved_source_file)
    prep_key = build_deterministic_prep_key(
        source_file=resolved_source_file,
        source_hash=resolved_source_hash,
        run_settings=run_settings,
    )
    manifest_path = _manifest_path_for_prep_key(
        source_hash=resolved_source_hash,
        prep_key=prep_key,
        book_cache_root=book_cache_root,
    )
    return _bundle_result_from_manifest(manifest_path, cache_hit=True)


def _build_generate_prediction_kwargs(
    *,
    source_file: Path,
    run_settings: RunSettings,
    artifact_root: Path,
    book_cache_root: Path,
) -> dict[str, Any]:
    global _GENERATE_PRED_RUN_ARTIFACTS_PARAMETER_NAMES
    if _GENERATE_PRED_RUN_ARTIFACTS_PARAMETER_NAMES is None:
        from cookimport.labelstudio.ingest_flows.prediction_run import (
            generate_pred_run_artifacts,
        )

        _GENERATE_PRED_RUN_ARTIFACTS_PARAMETER_NAMES = frozenset(
            inspect.signature(generate_pred_run_artifacts).parameters
        )
    benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
        run_settings,
        output_dir=artifact_root / "prediction-run",
        eval_output_dir=artifact_root / "prediction-eval",
        eval_mode="canonical-text",
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
        processed_output_dir=artifact_root / "processed-output",
    )
    explicit_kwargs = {
        "path": source_file,
        "pipeline": "auto",
        "segment_blocks": 40,
        "segment_overlap": 5,
        "allow_codex": False,
        "write_markdown": False,
        "write_label_studio_tasks": False,
        "run_root_override": artifact_root / "prediction-run",
        "mirror_stage_artifacts_into_run_root": False,
    }
    prediction_kwargs = {
        key: value
        for key, value in benchmark_kwargs.items()
        if key in (_GENERATE_PRED_RUN_ARTIFACTS_PARAMETER_NAMES or set())
        and key not in explicit_kwargs
    }
    prediction_kwargs["processed_output_root"] = artifact_root / "processed-output"
    prediction_kwargs["book_cache_root"] = book_cache_root
    prediction_kwargs.update(explicit_kwargs)
    return prediction_kwargs


def resolve_or_build_deterministic_prep_bundle(
    *,
    source_file: Path,
    run_settings: RunSettings,
    processed_output_root: Path,
    progress_callback: Callable[[str], None] | None = None,
    book_cache_root: Path | str | None = None,
) -> DeterministicPrepBundleResult:
    source_file = source_file.expanduser()
    del processed_output_root
    resolved_book_cache_root = resolve_book_cache_root(book_cache_root)
    source_hash = compute_file_hash(source_file)
    cached = load_existing_deterministic_prep_bundle(
        source_file=source_file,
        run_settings=run_settings,
        source_hash=source_hash,
        book_cache_root=resolved_book_cache_root,
    )
    if cached is not None:
        return cached
    prep_key = build_deterministic_prep_key(
        source_file=source_file,
        source_hash=source_hash,
        run_settings=run_settings,
    )
    manifest_path = _manifest_path_for_prep_key(
        source_hash=source_hash,
        prep_key=prep_key,
        book_cache_root=resolved_book_cache_root,
    )
    artifact_root = manifest_path.parent
    lock_path = entry_lock_path(artifact_root)
    lock_acquired = acquire_entry_lock(lock_path)
    if not lock_acquired:
        waited = wait_for_entry(
            load_entry=lambda: load_existing_deterministic_prep_bundle(
                source_file=source_file,
                run_settings=run_settings,
                source_hash=source_hash,
                book_cache_root=resolved_book_cache_root,
            ),
            lock_path=lock_path,
        )
        if waited is not None:
            return waited
        lock_acquired = acquire_entry_lock(lock_path)
        if not lock_acquired:
            raise ValueError(
                f"Deterministic prep cache entry stayed locked without a manifest: {manifest_path}"
            )

    try:
        if artifact_root.exists() and not manifest_path.exists():
            shutil.rmtree(artifact_root)
        artifact_root.mkdir(parents=True, exist_ok=True)
        prediction_kwargs = _build_generate_prediction_kwargs(
            source_file=source_file,
            run_settings=run_settings,
            artifact_root=artifact_root,
            book_cache_root=resolved_book_cache_root,
        )
        if progress_callback is not None:
            progress_callback(f"Preparing deterministic bundle for {source_file.name}...")

        from cookimport.labelstudio.ingest_flows.prediction_run import (
            generate_pred_run_artifacts,
        )

        prediction_result = generate_pred_run_artifacts(**prediction_kwargs)
        processed_run_root_raw = prediction_result.get("processed_run_root")
        if processed_run_root_raw is None:
            raise ValueError("Deterministic prep build did not produce processed outputs.")
        processed_run_root = Path(str(processed_run_root_raw)).expanduser()
        conversion_result_payload = prediction_result.get("conversion_result")
        if not isinstance(conversion_result_payload, dict):
            raise ValueError("Deterministic prep build did not return conversion_result.")
        conversion_result_path = artifact_root / _DETERMINISTIC_PREP_CONVERSION_RESULT_FILE_NAME
        write_json_atomic(conversion_result_path, conversion_result_payload)

        deterministic_settings = _coerce_dict(
            _deterministic_settings_payload(run_settings).get("settings")
        )
        book_cache_summary = _coerce_dict(prediction_result.get("book_cache"))
        manifest = {
            "schema_version": _DETERMINISTIC_PREP_BUNDLE_SCHEMA_VERSION,
            "prep_key": prep_key,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "source_file": str(source_file),
            "source_hash": source_hash,
            "workbook_slug": slugify_name(
                str(prediction_result.get("book_id") or source_file.stem)
            ),
            "importer_name": str(prediction_result.get("importer_name") or "").strip(),
            "artifact_root": str(artifact_root),
            "book_cache_root": str(resolved_book_cache_root),
            "prediction_run_root": str(prediction_result.get("run_root") or ""),
            "processed_run_root": str(processed_run_root),
            "conversion_result_path": str(conversion_result_path),
            "processed_report_path": (
                str(prediction_result.get("processed_report_path") or "").strip() or None
            ),
            "stage_block_predictions_path": (
                str(prediction_result.get("stage_block_predictions_path") or "").strip()
                or None
            ),
            "timing": _coerce_dict(prediction_result.get("timing")),
            "deterministic_settings": deterministic_settings,
            "deterministic_settings_summary": summarize_run_config_payload(
                deterministic_settings,
                contract="product",
            ),
            "conversion_cache": _coerce_dict(book_cache_summary.get("conversion")),
        }
        write_json_atomic(manifest_path, manifest)
        built = _bundle_result_from_manifest(manifest_path, cache_hit=False)
        if built is None:
            raise ValueError(
                f"Built deterministic prep bundle manifest could not be reloaded: {manifest_path}"
            )
        return built
    finally:
        if lock_acquired:
            release_entry_lock(lock_path)


def _load_source_model_artifacts(
    *,
    processed_run_root: Path,
    workbook_slug: str,
) -> tuple[list[SourceBlock], list[SourceSupport]]:
    source_dir = processed_run_root / "raw" / "source" / workbook_slug
    source_blocks = [
        SourceBlock.model_validate(row)
        for row in _read_jsonl_dicts(source_dir / "source_blocks.jsonl")
    ]
    source_support_payload = json.loads(
        (source_dir / "source_support.json").read_text(encoding="utf-8")
    )
    source_support = [
        SourceSupport.model_validate(row)
        for row in (source_support_payload if isinstance(source_support_payload, list) else [])
        if isinstance(row, Mapping)
    ]
    return (
        normalize_source_blocks(source_blocks),
        normalize_source_support(source_support),
    )


def _load_archive_blocks(processed_run_root: Path) -> list[dict[str, Any]]:
    full_text_path = _single_path(list(processed_run_root.glob("raw/*/*/full_text.json")))
    full_text_payload = _read_json(full_text_path)
    raw_blocks = full_text_payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError(f"Expected non-empty blocks in {full_text_path}")
    archive_blocks: list[dict[str, Any]] = []
    for fallback_index, raw_block in enumerate(raw_blocks):
        if not isinstance(raw_block, Mapping):
            continue
        payload = dict(raw_block)
        payload["index"] = int(raw_block.get("index", fallback_index))
        payload["block_id"] = str(
            raw_block.get("block_id") or raw_block.get("blockId") or f"block:{fallback_index}"
        )
        archive_blocks.append(payload)
    if not archive_blocks:
        raise ValueError(f"No usable archive blocks found in {full_text_path}")
    return archive_blocks


def _normalize_authoritative_labeled_line_row(
    row: Mapping[str, Any],
) -> AuthoritativeLabeledLine:
    deterministic_label = row.get("deterministic_label")
    if deterministic_label is None:
        deterministic_label = row.get("label")
    final_label = row.get("final_label")
    if final_label is None:
        final_label = row.get("label") or deterministic_label
    return AuthoritativeLabeledLine.model_validate(
        {
            "source_block_id": row.get("source_block_id"),
            "source_block_index": row.get("source_block_index"),
            "atomic_index": row.get("atomic_index"),
            "text": row.get("text"),
            "within_recipe_span_hint": row.get("within_recipe_span_hint"),
            "deterministic_label": deterministic_label,
            "final_label": final_label,
            "decided_by": row.get("decided_by"),
            "reason_tags": row.get("reason_tags") or [],
            "escalation_reasons": row.get("escalation_reasons") or [],
        }
    )


def _block_rows_for_indices(
    archive_blocks: Sequence[Mapping[str, Any]],
    block_indices: Sequence[int],
) -> list[dict[str, Any]]:
    block_index_set = {int(index) for index in block_indices}
    rows: list[dict[str, Any]] = []
    for raw_block in archive_blocks:
        if not isinstance(raw_block, Mapping):
            continue
        try:
            block_index = int(raw_block.get("index"))
        except (TypeError, ValueError):
            continue
        if block_index in block_index_set:
            rows.append(dict(raw_block))
    rows.sort(key=lambda row: int(row.get("index", 0)))
    return rows


def _average_int(total: Any, count: Any) -> int | None:
    total_int = _coerce_int(total)
    count_int = _coerce_int(count)
    if total_int is None or count_int is None or count_int <= 0:
        return None
    return int(round(total_int / count_int))


def _average_float(total: Any, count: Any) -> float | None:
    total_int = _coerce_int(total)
    count_int = _coerce_int(count)
    if total_int is None or count_int is None or count_int <= 0:
        return None
    return round(float(total_int) / float(count_int), 2)


def _owned_unit_label_for_step(step_id: str) -> str:
    return {
        "line_role": "lines",
        "recipe": "recipes",
        "knowledge": "chars",
    }.get(step_id, "units")


def _build_phase_recommendation_payload(
    *,
    step_id: str,
    phase_plan: Mapping[str, Any],
) -> dict[str, Any]:
    survivability = (
        phase_plan.get("survivability")
        if isinstance(phase_plan.get("survivability"), Mapping)
        else {}
    )
    totals = (
        survivability.get("totals")
        if isinstance(survivability.get("totals"), Mapping)
        else {}
    )
    current_shard_count = (
        _coerce_int(phase_plan.get("shard_count"))
        or _coerce_int(survivability.get("current_shard_count"))
        or 0
    )
    owned_unit_count = (
        _coerce_int(phase_plan.get("work_unit_count"))
        or _coerce_int(phase_plan.get("owned_id_count"))
        or _coerce_int(totals.get("owned_unit_count"))
        or 0
    )
    owned_ids_per_shard = (
        phase_plan.get("owned_ids_per_shard")
        if isinstance(phase_plan.get("owned_ids_per_shard"), Mapping)
        else {}
    )
    work_units_per_shard = (
        phase_plan.get("work_units_per_shard")
        if isinstance(phase_plan.get("work_units_per_shard"), Mapping)
        else {}
    )
    worst_shard = (
        survivability.get("worst_shard")
        if isinstance(survivability.get("worst_shard"), Mapping)
        else {}
    )
    minimum_safe_shard_count = (
        phase_plan.get("survivability_recommended_shard_count")
        if phase_plan.get("survivability_recommended_shard_count") is not None
        else phase_plan.get("minimum_safe_shard_count")
    )
    binding_limit = str(phase_plan.get("binding_limit") or "").strip() or None
    requested_shard_count = _coerce_int(phase_plan.get("requested_shard_count"))
    budget_native_shard_count = _coerce_int(phase_plan.get("budget_native_shard_count"))
    launch_shard_count = _coerce_int(phase_plan.get("launch_shard_count"))
    return {
        "minimum_safe_shard_count": (
            int(minimum_safe_shard_count)
            if minimum_safe_shard_count is not None
            else None
        ),
        "survivability_recommended_shard_count": (
            int(minimum_safe_shard_count)
            if minimum_safe_shard_count is not None
            else None
        ),
        "binding_limit": binding_limit,
        "requested_shard_count": requested_shard_count,
        "budget_native_shard_count": budget_native_shard_count,
        "launch_shard_count": launch_shard_count,
        "planning_warnings": [
            str(item).strip()
            for item in phase_plan.get("planning_warnings") or []
            if str(item).strip()
        ],
        "current_shard_count": current_shard_count or None,
        "owned_unit_count": owned_unit_count or None,
        "estimated_input_tokens_total": _coerce_int(
            totals.get("estimated_input_tokens")
        ),
        "estimated_peak_session_tokens_total": _coerce_int(
            totals.get("estimated_peak_session_tokens")
        ),
        "owned_unit_label": str(phase_plan.get("work_unit_label") or "").strip()
        or _owned_unit_label_for_step(step_id),
        "owned_units_per_shard_avg": (
            round(float(work_units_per_shard.get("avg") or 0.0), 2)
            if work_units_per_shard
            else (
                round(float(owned_ids_per_shard.get("avg") or 0.0), 2)
                if owned_ids_per_shard
                else _average_float(owned_unit_count, current_shard_count)
            )
        ),
        "avg_input_tokens_per_shard": _average_int(
            totals.get("estimated_input_tokens"),
            current_shard_count,
        ),
        "avg_output_tokens_per_shard": _average_int(
            totals.get("estimated_output_tokens"),
            current_shard_count,
        ),
        "avg_followup_tokens_per_shard": _average_int(
            totals.get("estimated_followup_tokens"),
            current_shard_count,
        ),
        "avg_peak_session_tokens_per_shard": _average_int(
            totals.get("estimated_peak_session_tokens"),
            current_shard_count,
        ),
        "worst_peak_session_tokens": _coerce_int(
            worst_shard.get("estimated_peak_session_tokens")
        ),
    }


def _build_book_summary_payload(
    *,
    prep_bundle: DeterministicPrepBundleResult,
    phase_plans: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        recipe_boundary_result = load_recipe_boundary_result_from_deterministic_prep_bundle(
            prep_bundle
        )
    except Exception:  # noqa: BLE001
        return None
    recipe_phase = (
        phase_plans.get("recipe_refine")
        if isinstance(phase_plans.get("recipe_refine"), Mapping)
        else {}
    )
    knowledge_phase = (
        phase_plans.get("nonrecipe_finalize")
        if isinstance(phase_plans.get("nonrecipe_finalize"), Mapping)
        else {}
    )
    recipe_guess_count = _coerce_int(recipe_phase.get("owned_id_count")) or len(
        recipe_boundary_result.label_first_result.recipe_spans
    )
    knowledge_packet_count = _coerce_int(knowledge_phase.get("owned_id_count"))
    return {
        "block_count": len(recipe_boundary_result.extracted_bundle.archive_blocks),
        "line_count": len(recipe_boundary_result.label_first_result.labeled_lines),
        "recipe_guess_count": recipe_guess_count,
        "recipe_owned_block_count": len(recipe_boundary_result.recipe_owned_blocks),
        "outside_recipe_block_count": len(recipe_boundary_result.outside_recipe_blocks),
        "knowledge_packet_count": knowledge_packet_count,
    }


def load_recipe_boundary_result_from_deterministic_prep_bundle(
    prep_bundle: DeterministicPrepBundleResult,
) -> RecipeBoundaryResult:
    conversion_result = ConversionResult.model_validate(
        _read_json(prep_bundle.conversion_result_path)
    )
    processed_run_root = prep_bundle.processed_run_root
    workbook_slug = prep_bundle.workbook_slug
    source_blocks, source_support = _load_source_model_artifacts(
        processed_run_root=processed_run_root,
        workbook_slug=workbook_slug,
    )
    archive_blocks = (
        source_blocks_to_rows(source_blocks)
        if source_blocks
        else _load_archive_blocks(processed_run_root)
    )
    labeled_lines_path = (
        processed_run_root
        / LINE_ROLE_PIPELINE_DIR_NAME
        / LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME
    )
    if not labeled_lines_path.exists():
        labeled_lines_path = (
            processed_run_root / "label_refine" / workbook_slug / "labeled_lines.jsonl"
        )
    if not labeled_lines_path.exists():
        labeled_lines_path = (
            processed_run_root / "label_deterministic" / workbook_slug / "labeled_lines.jsonl"
        )
    labeled_lines = [
        _normalize_authoritative_labeled_line_row(row)
        for row in _read_jsonl_dicts(labeled_lines_path)
    ]
    block_labels_payload = _read_json(
        processed_run_root
        / "recipe_boundary"
        / workbook_slug
        / "authoritative_block_labels.json"
    )
    block_labels = [
        AuthoritativeBlockLabel.model_validate(row)
        for row in block_labels_payload.get("block_labels") or []
        if isinstance(row, Mapping)
    ]
    recipe_spans_payload = _read_json(
        processed_run_root / "recipe_boundary" / workbook_slug / "recipe_spans.json"
    )
    recipe_spans = [
        RecipeSpan.model_validate(row)
        for row in recipe_spans_payload.get("recipe_spans") or []
        if isinstance(row, Mapping)
    ]
    span_decisions_path = (
        processed_run_root / "recipe_boundary" / workbook_slug / "span_decisions.json"
    )
    span_decisions_payload = (
        _read_json(span_decisions_path) if span_decisions_path.exists() else {}
    )
    span_decisions = [
        RecipeSpanDecision.model_validate(row)
        for row in span_decisions_payload.get("span_decisions") or []
        if isinstance(row, Mapping)
    ]
    recipe_ownership_payload = _read_json(
        processed_run_root
        / "recipe_authority"
        / workbook_slug
        / "recipe_block_ownership.json"
    )
    recipe_ownership_result = recipe_ownership_from_payload(
        recipe_ownership_payload,
        full_blocks=archive_blocks,
    )
    owned_block_indices = {
        int(block_index)
        for block_index in recipe_ownership_result.owned_block_indices
    }
    non_recipe_lines = [
        row
        for row in labeled_lines
        if int(row.source_block_index) not in owned_block_indices
    ]
    outside_recipe_blocks = [
        dict(block)
        for block in archive_blocks
        if int(block.get("index", -1)) not in owned_block_indices
    ]
    label_first_result = LabelFirstStageResult(
        authoritative_label_stage_key=(
            "line_role"
            if (
                processed_run_root
                / LINE_ROLE_PIPELINE_DIR_NAME
                / LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME
            ).exists()
            else "label_refine"
        ),
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=span_decisions,
        non_recipe_lines=non_recipe_lines,
        outside_recipe_blocks=outside_recipe_blocks,
        updated_conversion_result=conversion_result,
        archive_blocks=[dict(block) for block in archive_blocks],
        source_hash=prep_bundle.source_hash,
    )
    extracted_book_bundle = ExtractedBookBundle(
        source_file=prep_bundle.source_file,
        workbook_slug=workbook_slug,
        importer_name=prep_bundle.importer_name,
        source_hash=prep_bundle.source_hash,
        conversion_result=conversion_result,
        source_blocks=source_blocks,
        source_support=source_support,
        archive_blocks=[dict(block) for block in archive_blocks],
    )
    return RecipeBoundaryResult(
        extracted_bundle=extracted_book_bundle,
        label_first_result=label_first_result,
        conversion_result=conversion_result,
        recipe_ownership_result=recipe_ownership_result,
        recipe_owned_blocks=_block_rows_for_indices(
            archive_blocks,
            recipe_ownership_result.owned_block_indices,
        ),
        outside_recipe_blocks=outside_recipe_blocks,
    )


def _copy_cache_payload_path(source_path: Path, target_path: Path) -> None:
    if not source_path.exists():
        return
    if target_path.exists():
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, target_path)
    else:
        shutil.copy2(source_path, target_path)


def persist_deterministic_prep_bundle_from_stage_run(
    *,
    source_file: Path,
    run_settings: RunSettings,
    stage_run_root: Path,
    recipe_boundary_result: RecipeBoundaryResult,
    importer_name: str,
    timing: Mapping[str, Any] | None = None,
    processed_report_path: Path | None = None,
    stage_block_predictions_path: Path | None = None,
    book_cache_root: Path | str | None = None,
) -> DeterministicPrepBundleResult:
    resolved_source_file = source_file.expanduser()
    source_hash = str(recipe_boundary_result.extracted_bundle.source_hash or "").strip()
    if not source_hash:
        source_hash = compute_file_hash(resolved_source_file)
    existing = load_existing_deterministic_prep_bundle(
        source_file=resolved_source_file,
        run_settings=run_settings,
        source_hash=source_hash,
        book_cache_root=book_cache_root,
    )
    if existing is not None:
        return existing

    prep_key = build_deterministic_prep_key(
        source_file=resolved_source_file,
        source_hash=source_hash,
        run_settings=run_settings,
    )
    resolved_book_cache_root = resolve_book_cache_root(book_cache_root)
    artifact_root = deterministic_prep_artifact_root(
        book_cache_root=resolved_book_cache_root,
        source_hash=source_hash,
        prep_key=prep_key,
    )
    manifest_path = artifact_root / _DETERMINISTIC_PREP_MANIFEST_FILE_NAME
    lock_path = entry_lock_path(artifact_root)
    lock_acquired = acquire_entry_lock(lock_path)
    if not lock_acquired:
        waited = wait_for_entry(
            load_entry=lambda: load_existing_deterministic_prep_bundle(
                source_file=resolved_source_file,
                run_settings=run_settings,
                source_hash=source_hash,
                book_cache_root=resolved_book_cache_root,
            ),
            lock_path=lock_path,
        )
        if waited is not None:
            return waited
        lock_acquired = acquire_entry_lock(lock_path)
        if not lock_acquired:
            raise ValueError(
                f"Deterministic prep cache entry stayed locked without a manifest: {manifest_path}"
            )

    try:
        if artifact_root.exists() and not manifest_path.exists():
            shutil.rmtree(artifact_root)
        processed_run_root = artifact_root / "processed-output"
        processed_run_root.mkdir(parents=True, exist_ok=True)
        workbook_slug = recipe_boundary_result.extracted_bundle.workbook_slug
        conversion_result_path = artifact_root / _DETERMINISTIC_PREP_CONVERSION_RESULT_FILE_NAME
        write_json_atomic(
            conversion_result_path,
            recipe_boundary_result.conversion_result.model_dump(mode="json", by_alias=True),
        )
        _copy_cache_payload_path(
            stage_run_root / "raw" / "source" / workbook_slug,
            processed_run_root / "raw" / "source" / workbook_slug,
        )
        _copy_cache_payload_path(
            stage_run_root / "label_deterministic" / workbook_slug,
            processed_run_root / "label_deterministic" / workbook_slug,
        )
        _copy_cache_payload_path(
            stage_run_root / "label_refine" / workbook_slug,
            processed_run_root / "label_refine" / workbook_slug,
        )
        _copy_cache_payload_path(
            stage_run_root / "recipe_boundary" / workbook_slug,
            processed_run_root / "recipe_boundary" / workbook_slug,
        )
        _copy_cache_payload_path(
            stage_run_root / LINE_ROLE_PIPELINE_DIR_NAME,
            processed_run_root / LINE_ROLE_PIPELINE_DIR_NAME,
        )
        _copy_cache_payload_path(
            stage_run_root / "recipe_authority" / workbook_slug,
            processed_run_root / "recipe_authority" / workbook_slug,
        )
        _copy_cache_payload_path(
            stage_run_root / "raw" / importer_name / source_hash,
            processed_run_root / "raw" / importer_name / source_hash,
        )
        if stage_block_predictions_path is not None:
            _copy_cache_payload_path(
                stage_block_predictions_path,
                processed_run_root
                / ".bench"
                / workbook_slug
                / "stage_block_predictions.json",
            )
        if processed_report_path is not None and processed_report_path.exists():
            _copy_cache_payload_path(
                processed_report_path,
                processed_run_root / processed_report_path.name,
            )

        deterministic_settings = _coerce_dict(
            _deterministic_settings_payload(run_settings).get("settings")
        )
        manifest = {
            "schema_version": _DETERMINISTIC_PREP_BUNDLE_SCHEMA_VERSION,
            "prep_key": prep_key,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "source_file": str(resolved_source_file),
            "source_hash": source_hash,
            "workbook_slug": workbook_slug,
            "importer_name": importer_name,
            "artifact_root": str(artifact_root),
            "book_cache_root": str(resolved_book_cache_root),
            "prediction_run_root": str(artifact_root / "prediction-run"),
            "processed_run_root": str(processed_run_root),
            "conversion_result_path": str(conversion_result_path),
            "processed_report_path": (
                str(processed_run_root / processed_report_path.name)
                if processed_report_path is not None and processed_report_path.exists()
                else None
            ),
            "stage_block_predictions_path": (
                str(
                    processed_run_root
                    / ".bench"
                    / workbook_slug
                    / "stage_block_predictions.json"
                )
                if stage_block_predictions_path is not None
                else None
            ),
            "timing": _coerce_dict(timing),
            "deterministic_settings": deterministic_settings,
            "deterministic_settings_summary": summarize_run_config_payload(
                deterministic_settings,
                contract="product",
            ),
        }
        write_json_atomic(manifest_path, manifest)
        built = _bundle_result_from_manifest(manifest_path, cache_hit=False)
        if built is None:
            raise ValueError(
                f"Stage-run deterministic prep manifest could not be reloaded: {manifest_path}"
            )
        return built
    finally:
        if lock_acquired:
            release_entry_lock(lock_path)


def build_shard_recommendations_from_prep_bundle(
    *,
    prep_bundle: DeterministicPrepBundleResult,
    selected_settings: RunSettings,
) -> dict[str, dict[str, Any]]:
    preview_root = prep_bundle.artifact_root / _PREVIEW_DIR_NAME
    preview_root.mkdir(parents=True, exist_ok=True)
    preview_manifest_path = preview_cache_manifest_path(
        book_cache_root=prep_bundle.book_cache_root,
        source_hash=prep_bundle.source_hash,
        prep_key=prep_bundle.prep_key,
        selected_settings=selected_settings,
    )
    preview_lock_path = entry_lock_path(preview_manifest_path)
    preview_manifest = (
        _read_json(preview_manifest_path)
        if preview_manifest_path.exists()
        else None
    )
    if not _preview_manifest_is_current(preview_manifest):
        lock_acquired = acquire_entry_lock(preview_lock_path)
        if not lock_acquired:
            waited = wait_for_entry(
                load_entry=lambda: (
                    _read_json(preview_manifest_path)
                    if preview_manifest_path.exists()
                    else None
                ),
                lock_path=preview_lock_path,
            )
            if _preview_manifest_is_current(waited):
                preview_manifest = waited
            else:
                lock_acquired = acquire_entry_lock(preview_lock_path)
                if not lock_acquired:
                    raise ValueError(
                        f"Prompt-preview cache entry stayed locked without a manifest: {preview_manifest_path}"
                    )
                preview_manifest = None
        else:
            preview_manifest = None
        try:
            if preview_manifest is None:
                generated_manifest_path = write_prompt_preview_for_existing_run(
                    run_path=prep_bundle.processed_run_root,
                    out_dir=preview_root,
                    repo_root=Path(__file__).resolve().parents[2],
                    llm_recipe_pipeline=selected_settings.llm_recipe_pipeline.value,
                    llm_knowledge_pipeline=selected_settings.llm_knowledge_pipeline.value,
                    line_role_pipeline=selected_settings.line_role_pipeline.value,
                    codex_farm_root=selected_settings.codex_farm_root,
                    codex_farm_cmd=selected_settings.codex_farm_cmd,
                    codex_farm_model=selected_settings.codex_farm_model,
                    codex_farm_reasoning_effort=(
                        selected_settings.codex_farm_reasoning_effort.value
                        if selected_settings.codex_farm_reasoning_effort is not None
                        else None
                    ),
                    codex_farm_context_blocks=selected_settings.codex_farm_context_blocks,
                    codex_farm_knowledge_context_blocks=(
                        selected_settings.codex_farm_knowledge_context_blocks
                    ),
                    atomic_block_splitter=selected_settings.atomic_block_splitter.value,
                    recipe_worker_count=selected_settings.recipe_worker_count,
                    recipe_prompt_target_count=selected_settings.recipe_prompt_target_count,
                    knowledge_prompt_target_count=(
                        selected_settings.knowledge_prompt_target_count
                    ),
                    knowledge_packet_input_char_budget=(
                        selected_settings.knowledge_packet_input_char_budget
                    ),
                    knowledge_packet_output_char_budget=(
                        selected_settings.knowledge_packet_output_char_budget
                    ),
                    knowledge_worker_count=selected_settings.knowledge_worker_count,
                    line_role_worker_count=selected_settings.line_role_worker_count,
                    line_role_prompt_target_count=(
                        selected_settings.line_role_prompt_target_count
                    ),
                    line_role_shard_target_lines=selected_settings.line_role_shard_target_lines,
                )
                preview_manifest = _read_json(generated_manifest_path)
                if not _preview_manifest_is_current(preview_manifest):
                    raise ValueError(
                        "Prompt-preview generation returned an out-of-date manifest schema"
                    )
                write_json_atomic(preview_manifest_path, preview_manifest)
        finally:
            if "lock_acquired" in locals() and lock_acquired:
                release_entry_lock(preview_lock_path)
    phase_plans = preview_manifest.get("phase_plans")
    if not isinstance(phase_plans, Mapping):
        return {}
    stage_to_step = {
        "line_role": "line_role",
        "recipe_refine": "recipe",
        "nonrecipe_finalize": "knowledge",
    }
    recommendations_by_step: dict[str, dict[str, Any]] = {}
    for stage_key, step_id in stage_to_step.items():
        phase_plan = phase_plans.get(stage_key)
        if not isinstance(phase_plan, Mapping):
            continue
        recommendations_by_step[step_id] = _build_phase_recommendation_payload(
            step_id=step_id,
            phase_plan=phase_plan,
        )
    book_summary = _build_book_summary_payload(
        prep_bundle=prep_bundle,
        phase_plans=phase_plans,
    )
    if book_summary is not None:
        recommendations_by_step["__book_summary__"] = book_summary
    return recommendations_by_step


__all__ = [
    "DeterministicPrepBundleResult",
    "build_deterministic_prep_key",
    "build_shard_recommendations_from_prep_bundle",
    "load_existing_deterministic_prep_bundle",
    "load_deterministic_prep_bundle",
    "load_recipe_boundary_result_from_deterministic_prep_bundle",
    "persist_deterministic_prep_bundle_from_stage_run",
    "resolve_or_build_deterministic_prep_bundle",
]
