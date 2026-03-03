from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cookimport.bench.segmentation_metrics import compute_segmentation_boundaries
from cookimport.labelstudio.howto_section import resolve_howto_label_sets_by_index
from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_SEGMENTATION_LABEL_PROJECTION_CORE = "core_structural_v1"
_SEGMENTATION_DEFAULT_METRICS: tuple[str, ...] = ("boundary_f1",)
_OPTIONAL_SEGMENTATION_METRICS: tuple[str, ...] = (
    "pk",
    "windowdiff",
    "boundary_similarity",
)
_SUPPORTED_SEGMENTATION_METRICS = set(_SEGMENTATION_DEFAULT_METRICS).union(
    _OPTIONAL_SEGMENTATION_METRICS
)
_STRUCTURAL_LABEL_PRIORITY: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
)
_STRUCTURAL_LABEL_SET = set(_STRUCTURAL_LABEL_PRIORITY)
_YIELD_TIME_LABELS = {"YIELD_LINE", "TIME_LINE"}

try:  # pragma: no cover - non-Unix runtimes may not expose resource.
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_segmentation_metric_name(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _parse_segmentation_metric_selection(
    raw_metrics: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[str]:
    if raw_metrics is None:
        return list(_SEGMENTATION_DEFAULT_METRICS)

    metric_chunks: list[str] = []
    if isinstance(raw_metrics, str):
        metric_chunks.extend(raw_metrics.split(","))
    elif isinstance(raw_metrics, (list, tuple, set)):
        for item in raw_metrics:
            metric_chunks.extend(str(item or "").split(","))
    else:
        raise ValueError(
            "segmentation_metrics must be a CSV string or collection of metric names."
        )

    selected: list[str] = []
    seen: set[str] = set()
    for chunk in metric_chunks:
        metric_name = _normalize_segmentation_metric_name(chunk)
        if not metric_name:
            continue
        if metric_name not in _SUPPORTED_SEGMENTATION_METRICS:
            raise ValueError(
                "Unsupported segmentation metric "
                f"{metric_name!r}. Supported metrics: {sorted(_SUPPORTED_SEGMENTATION_METRICS)}."
            )
        if metric_name in seen:
            continue
        selected.append(metric_name)
        seen.add(metric_name)

    if not selected:
        return list(_SEGMENTATION_DEFAULT_METRICS)
    return selected


def _project_structural_label(*, label: str, projection: str) -> str:
    if projection != _SEGMENTATION_LABEL_PROJECTION_CORE:
        raise ValueError(
            "Unsupported label projection "
            f"{projection!r}; expected {_SEGMENTATION_LABEL_PROJECTION_CORE!r}."
        )
    if label in _STRUCTURAL_LABEL_SET:
        return label
    return "OTHER"


def _project_structural_label_set(*, labels: set[str], projection: str) -> str:
    if projection != _SEGMENTATION_LABEL_PROJECTION_CORE:
        raise ValueError(
            "Unsupported label projection "
            f"{projection!r}; expected {_SEGMENTATION_LABEL_PROJECTION_CORE!r}."
        )
    for label in _STRUCTURAL_LABEL_PRIORITY:
        if label in labels:
            return label
    return "OTHER"


def _nearest_boundary(boundary_index: int, candidates: list[int]) -> tuple[int | None, int | None]:
    if not candidates:
        return None, None
    nearest = min(candidates, key=lambda value: (abs(value - boundary_index), value))
    return nearest, abs(nearest - boundary_index)


def _taxonomy_bucket_for_block_mismatch(gold_label: str, pred_label: str) -> str:
    if gold_label in _YIELD_TIME_LABELS or pred_label in _YIELD_TIME_LABELS:
        return "yield_time_errors"
    if gold_label == "INGREDIENT_LINE" or pred_label == "INGREDIENT_LINE":
        return "ingredient_errors"
    if gold_label == "INSTRUCTION_LINE" or pred_label == "INSTRUCTION_LINE":
        return "instruction_errors"
    if gold_label != "OTHER" and pred_label == "OTHER":
        return "extraction_failure"
    return "boundary_errors"


def _compute_error_taxonomy(
    *,
    gold_projected: dict[int, str],
    pred_projected: dict[int, str],
    segmentation_boundaries: dict[str, Any],
) -> dict[str, Any]:
    bucket_counts: dict[str, int] = {
        "extraction_failure": 0,
        "boundary_errors": 0,
        "ingredient_errors": 0,
        "instruction_errors": 0,
        "yield_time_errors": 0,
    }
    examples: dict[str, list[int]] = {name: [] for name in bucket_counts}

    for block_index in sorted(gold_projected):
        gold_label = gold_projected[block_index]
        pred_label = pred_projected[block_index]
        if gold_label == pred_label:
            continue
        bucket = _taxonomy_bucket_for_block_mismatch(gold_label, pred_label)
        bucket_counts[bucket] += 1
        if len(examples[bucket]) < 8:
            examples[bucket].append(block_index)

    boundary_miss_total = 0
    boundaries = segmentation_boundaries.get("boundaries")
    if isinstance(boundaries, dict):
        for metric_name, payload in boundaries.items():
            if metric_name == "overall_micro" or not isinstance(payload, dict):
                continue
            boundary_miss_total += int(payload.get("fp") or 0)
            boundary_miss_total += int(payload.get("fn") or 0)
    bucket_counts["boundary_errors"] += boundary_miss_total

    return {
        "bucket_counts": bucket_counts,
        "total_count": sum(bucket_counts.values()),
        "block_mismatch_count": sum(
            1 for block_index in gold_projected if gold_projected[block_index] != pred_projected[block_index]
        ),
        "boundary_miss_count": boundary_miss_total,
        "example_block_indices": examples,
    }


def _capture_eval_resource_snapshot() -> dict[str, float]:
    snapshot: dict[str, float] = {
        "process_cpu_seconds": max(0.0, float(time.process_time())),
    }
    thread_time_fn = getattr(time, "thread_time", None)
    if callable(thread_time_fn):
        try:
            snapshot["thread_cpu_seconds"] = max(0.0, float(thread_time_fn()))
        except Exception:  # noqa: BLE001
            pass
    if resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
        except Exception:  # noqa: BLE001
            usage = None
        if usage is not None:
            snapshot["ru_utime_seconds"] = max(0.0, float(usage.ru_utime))
            snapshot["ru_stime_seconds"] = max(0.0, float(usage.ru_stime))
            snapshot["ru_maxrss_kib"] = max(0.0, float(usage.ru_maxrss))
            snapshot["ru_inblock"] = max(0.0, float(usage.ru_inblock))
            snapshot["ru_oublock"] = max(0.0, float(usage.ru_oublock))
            snapshot["ru_minflt"] = max(0.0, float(usage.ru_minflt))
            snapshot["ru_majflt"] = max(0.0, float(usage.ru_majflt))
    return snapshot


def _diff_eval_resource_snapshots(
    start: dict[str, float],
    end: dict[str, float],
) -> dict[str, float]:
    delta_keys = (
        "process_cpu_seconds",
        "thread_cpu_seconds",
        "ru_utime_seconds",
        "ru_stime_seconds",
        "ru_inblock",
        "ru_oublock",
        "ru_minflt",
        "ru_majflt",
    )
    resources: dict[str, float] = {}
    for key in delta_keys:
        start_value = start.get(key)
        end_value = end.get(key)
        if start_value is None or end_value is None:
            continue
        resources[key] = max(0.0, float(end_value) - float(start_value))
    if "ru_maxrss_kib" in end:
        resources["peak_ru_maxrss_kib"] = max(0.0, float(end["ru_maxrss_kib"]))
    return resources


def _new_blockization_profile() -> dict[str, Any]:
    return {
        "min_block_index": None,
        "max_block_index": None,
        "seen_block_indices": set(),
        "extraction_backends": set(),
        "unstructured_html_parser_versions": set(),
        "unstructured_preprocess_modes": set(),
        "unstructured_skip_headers_footers": set(),
    }


def _update_blockization_profile_index(profile: dict[str, Any], block_index: int | None) -> None:
    if block_index is None:
        return
    seen = profile["seen_block_indices"]
    if not isinstance(seen, set):
        return
    seen.add(block_index)
    min_index = profile.get("min_block_index")
    max_index = profile.get("max_block_index")
    if min_index is None or block_index < min_index:
        profile["min_block_index"] = block_index
    if max_index is None or block_index > max_index:
        profile["max_block_index"] = block_index


def _update_blockization_profile_feature(
    profile: dict[str, Any],
    *,
    key: str,
    value: Any,
) -> None:
    if value is None:
        return
    target = profile.get(key)
    if not isinstance(target, set):
        return
    text = str(value).strip()
    if not text:
        return
    target.add(text)


def _update_blockization_profile_from_gold_payload(
    profile: dict[str, Any],
    payload: dict[str, Any],
    *,
    indices: list[int],
) -> None:
    for block_index in indices:
        _update_blockization_profile_index(profile, block_index)

    touched_blocks = payload.get("touched_blocks")
    if not isinstance(touched_blocks, list):
        return
    for touched in touched_blocks:
        if not isinstance(touched, dict):
            continue
        _update_blockization_profile_index(
            profile,
            _coerce_int(touched.get("block_index")),
        )
        location = touched.get("location")
        if not isinstance(location, dict):
            continue
        features = location.get("features")
        if not isinstance(features, dict):
            continue
        _update_blockization_profile_feature(
            profile,
            key="extraction_backends",
            value=features.get("extraction_backend"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_html_parser_versions",
            value=features.get("unstructured_html_parser_version"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_preprocess_modes",
            value=features.get("unstructured_preprocess_mode"),
        )
        if "unstructured_skip_headers_footers" in features:
            _update_blockization_profile_feature(
                profile,
                key="unstructured_skip_headers_footers",
                value=features.get("unstructured_skip_headers_footers"),
            )


def _serialize_blockization_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "labeled_block_count": len(profile.get("seen_block_indices", set())),
        "min_labeled_block_index": profile.get("min_block_index"),
        "max_labeled_block_index": profile.get("max_block_index"),
        "extraction_backends": sorted(profile.get("extraction_backends", set())),
        "unstructured_html_parser_versions": sorted(
            profile.get("unstructured_html_parser_versions", set())
        ),
        "unstructured_preprocess_modes": sorted(
            profile.get("unstructured_preprocess_modes", set())
        ),
        "unstructured_skip_headers_footers": sorted(
            profile.get("unstructured_skip_headers_footers", set())
        ),
    }


def _extract_profile_set(profile: dict[str, Any], key: str) -> set[str]:
    values = profile.get(key)
    if not isinstance(values, list):
        return set()
    extracted: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text:
            extracted.add(text)
    return extracted


def _collect_blockization_diagnostics(
    *,
    gold_profile: dict[str, Any],
    prediction_profile: dict[str, Any],
    missing_gold_indices: list[int],
    pred_block_count: int,
) -> list[dict[str, Any]]:
    missing_count = len(missing_gold_indices)
    missing_ratio = (
        (missing_count / pred_block_count) if pred_block_count > 0 else 0.0
    )

    gold_max = _coerce_int(gold_profile.get("max_labeled_block_index"))
    pred_max = _coerce_int(prediction_profile.get("max_labeled_block_index"))
    trailing_gap = 0
    trailing_missing_count = 0
    if gold_max is not None and pred_max is not None and pred_max > gold_max:
        trailing_gap = pred_max - gold_max
        trailing_missing_count = sum(
            1 for value in missing_gold_indices if value > gold_max
        )
    trailing_missing_ratio = (
        (trailing_missing_count / missing_count) if missing_count > 0 else 0.0
    )

    gold_backends = _extract_profile_set(gold_profile, "extraction_backends")
    pred_backends = _extract_profile_set(prediction_profile, "extraction_backends")
    backend_mismatch = bool(
        gold_backends and pred_backends and gold_backends.isdisjoint(pred_backends)
    )

    mismatch_fields: list[str] = []
    for field in (
        "unstructured_html_parser_versions",
        "unstructured_preprocess_modes",
        "unstructured_skip_headers_footers",
    ):
        gold_values = _extract_profile_set(gold_profile, field)
        pred_values = _extract_profile_set(prediction_profile, field)
        if gold_values and pred_values and gold_values.isdisjoint(pred_values):
            mismatch_fields.append(field)

    mismatch_signal = backend_mismatch or bool(mismatch_fields)
    drift_signal = (
        (missing_count >= 50 and missing_ratio >= 0.2)
        or trailing_gap >= 100
        or (trailing_missing_count >= 50 and trailing_missing_ratio >= 0.8)
    )
    if not mismatch_signal and not drift_signal:
        return []

    diagnostic: dict[str, Any] = {
        "missing_gold_count": missing_count,
        "pred_block_count": pred_block_count,
        "missing_gold_ratio": round(missing_ratio, 4),
        "trailing_gap_blocks": trailing_gap,
        "trailing_missing_count": trailing_missing_count,
        "trailing_missing_ratio": round(trailing_missing_ratio, 4),
        "gold_profile": gold_profile,
        "prediction_profile": prediction_profile,
    }
    if mismatch_fields:
        diagnostic["mismatched_unstructured_fields"] = mismatch_fields
    if mismatch_signal and drift_signal:
        diagnostic["error"] = "gold_prediction_blockization_mismatch"
    elif mismatch_signal:
        diagnostic["warning"] = "gold_prediction_blockization_mismatch"
    else:
        diagnostic["warning"] = "gold_prediction_block_index_drift_suspected"
    return [diagnostic]


def _format_blockization_mismatch_message(diagnostic: dict[str, Any]) -> str:
    gold_profile = diagnostic.get("gold_profile")
    prediction_profile = diagnostic.get("prediction_profile")
    gold_backends = []
    pred_backends = []
    if isinstance(gold_profile, dict):
        values = gold_profile.get("extraction_backends")
        if isinstance(values, list):
            gold_backends = [str(value) for value in values if str(value or "").strip()]
    if isinstance(prediction_profile, dict):
        values = prediction_profile.get("extraction_backends")
        if isinstance(values, list):
            pred_backends = [str(value) for value in values if str(value or "").strip()]

    return (
        "Detected severe gold/prediction blockization mismatch. "
        f"gold_backends={gold_backends or ['<unknown>']} "
        f"prediction_backends={pred_backends or ['<unknown>']} "
        f"missing_gold={int(diagnostic.get('missing_gold_count') or 0)}/"
        f"{int(diagnostic.get('pred_block_count') or 0)}. "
        "Re-run benchmark with the same extractor/blockization settings used to create the Label Studio gold export."
    )


def _extract_block_indices(payload: dict[str, Any]) -> list[int]:
    values = payload.get("touched_block_indices")
    items: list[Any]
    if isinstance(values, list):
        items = values
    else:
        touched_blocks = payload.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            return []
        items = [
            item.get("block_index")
            for item in touched_blocks
            if isinstance(item, dict) and item.get("block_index") is not None
        ]

    indices: list[int] = []
    for value in items:
        try:
            indices.append(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _excerpt(text: str, *, limit: int = 220) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)] + "..."


def _build_projected_structural_sequences(
    *,
    gold: dict[int, set[str]],
    pred: dict[int, str],
    label_projection: str,
) -> tuple[list[str], list[str], dict[int, str], dict[int, str]]:
    ordered_indices = sorted(gold)
    projected_gold_by_index: dict[int, str] = {}
    projected_pred_by_index: dict[int, str] = {}
    labels_gold: list[str] = []
    labels_pred: list[str] = []

    for index in ordered_indices:
        gold_projected = _project_structural_label_set(
            labels=gold[index],
            projection=label_projection,
        )
        pred_projected = _project_structural_label(
            label=pred[index],
            projection=label_projection,
        )
        projected_gold_by_index[index] = gold_projected
        projected_pred_by_index[index] = pred_projected
        labels_gold.append(gold_projected)
        labels_pred.append(pred_projected)

    return (
        labels_gold,
        labels_pred,
        projected_gold_by_index,
        projected_pred_by_index,
    )


def _build_boundary_mismatch_rows(
    *,
    segmentation_boundaries: dict[str, Any],
    block_texts: dict[int, str],
    workbook_slug: str,
    source_file: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    missed_rows: list[dict[str, Any]] = []
    false_positive_rows: list[dict[str, Any]] = []

    boundaries = segmentation_boundaries.get("boundaries")
    if not isinstance(boundaries, dict):
        return missed_rows, false_positive_rows

    for boundary_type, boundary_metrics in boundaries.items():
        if boundary_type == "overall_micro" or not isinstance(boundary_metrics, dict):
            continue

        pred_boundaries = [
            int(value)
            for value in boundary_metrics.get("pred_boundaries", [])
            if _coerce_int(value) is not None
        ]
        gold_boundaries = [
            int(value)
            for value in boundary_metrics.get("gold_boundaries", [])
            if _coerce_int(value) is not None
        ]

        for value in boundary_metrics.get("missed_gold_boundaries", []):
            boundary_index = _coerce_int(value)
            if boundary_index is None:
                continue
            nearest_pred, distance = _nearest_boundary(boundary_index, pred_boundaries)
            missed_rows.append(
                {
                    "boundary_type": boundary_type,
                    "gold_boundary_index": boundary_index,
                    "nearest_pred_boundary_index": nearest_pred,
                    "distance_blocks": distance,
                    "block_text_excerpt": _excerpt(block_texts.get(boundary_index, "")),
                    "workbook_slug": workbook_slug,
                    "source_file": source_file,
                }
            )

        for value in boundary_metrics.get("false_positive_boundaries", []):
            boundary_index = _coerce_int(value)
            if boundary_index is None:
                continue
            nearest_gold, distance = _nearest_boundary(boundary_index, gold_boundaries)
            false_positive_rows.append(
                {
                    "boundary_type": boundary_type,
                    "pred_boundary_index": boundary_index,
                    "nearest_gold_boundary_index": nearest_gold,
                    "distance_blocks": distance,
                    "block_text_excerpt": _excerpt(block_texts.get(boundary_index, "")),
                    "workbook_slug": workbook_slug,
                    "source_file": source_file,
                }
            )

    return missed_rows, false_positive_rows


def _load_extracted_block_texts(extracted_blocks_json: Path) -> dict[int, str]:
    if not extracted_blocks_json.exists() or not extracted_blocks_json.is_file():
        return {}

    try:
        payload = json.loads(extracted_blocks_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            records = [item for item in blocks if isinstance(item, dict)]

    by_index: dict[int, str] = {}
    for row in records:
        raw_index = row.get("index")
        if raw_index is None:
            raw_index = row.get("block_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        by_index[index] = str(row.get("text") or "")
    return by_index


def _load_extracted_block_profile(extracted_blocks_json: Path) -> dict[str, Any]:
    if not extracted_blocks_json.exists() or not extracted_blocks_json.is_file():
        return {}

    try:
        payload = json.loads(extracted_blocks_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            records = [item for item in blocks if isinstance(item, dict)]

    if not records:
        return {}

    profile = _new_blockization_profile()
    for row in records:
        raw_index = row.get("index")
        if raw_index is None:
            raw_index = row.get("block_index")
        _update_blockization_profile_index(profile, _coerce_int(raw_index))

        location = row.get("location")
        if not isinstance(location, dict):
            continue
        features = location.get("features")
        if not isinstance(features, dict):
            continue
        _update_blockization_profile_feature(
            profile,
            key="extraction_backends",
            value=features.get("extraction_backend"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_html_parser_versions",
            value=features.get("unstructured_html_parser_version"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_preprocess_modes",
            value=features.get("unstructured_preprocess_mode"),
        )
        if "unstructured_skip_headers_footers" in features:
            _update_blockization_profile_feature(
                profile,
                key="unstructured_skip_headers_footers",
                value=features.get("unstructured_skip_headers_footers"),
            )

    return _serialize_blockization_profile(profile)


def _coerce_gold_label_set(raw: Any, *, block_index: int) -> set[str]:
    if isinstance(raw, str):
        items: list[Any] = [raw]
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        raise ValueError(
            "Gold label payload must be a label string or label collection; "
            f"block_index={block_index} got {type(raw).__name__}."
        )

    labels: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        normalized = normalize_freeform_label(value)
        if normalized not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Unsupported freeform label in gold payload: {value!r}"
            )
        labels.add(normalized)

    if not labels:
        raise ValueError(f"Gold block {block_index} has no usable labels.")
    return labels


def _primary_gold_label(labels: set[str], *, pred_label: str | None = None) -> str:
    if pred_label and pred_label in labels:
        return pred_label
    for label in FREEFORM_LABELS:
        if label in labels:
            return label
    return sorted(labels)[0]


def load_gold_block_labels(
    freeform_span_labels_jsonl_path: Path,
    *,
    conflict_output_path: Path | None = None,
    require_exhaustive: bool = True,
    profile_output: dict[str, Any] | None = None,
) -> dict[int, set[str]]:
    assignments: dict[int, set[str]] = {}
    assignment_spans: dict[int, list[dict[str, Any]]] = {}
    profile = _new_blockization_profile()

    for line_number, line in enumerate(
        freeform_span_labels_jsonl_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in gold file at line {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            continue

        label_value = payload.get("label")
        if not isinstance(label_value, str) or not label_value.strip():
            continue
        normalized_label = normalize_freeform_label(label_value)
        if normalized_label not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Unsupported freeform label in gold file: {label_value!r}"
            )

        span_id = str(payload.get("span_id") or f"line:{line_number}")
        source_hash = payload.get("source_hash")
        source_file = payload.get("source_file")
        indices = _extract_block_indices(payload)
        if not indices:
            continue
        _update_blockization_profile_from_gold_payload(
            profile,
            payload,
            indices=indices,
        )
        for block_index in indices:
            assignments.setdefault(block_index, set()).add(normalized_label)
            assignment_spans.setdefault(block_index, []).append(
                {
                    "span_id": span_id,
                    "label": normalized_label,
                    "source_hash": source_hash,
                    "source_file": source_file,
                }
            )

    if not assignments:
        raise ValueError(
            f"Gold file contains no usable block labels: {freeform_span_labels_jsonl_path}"
        )

    assignments = resolve_howto_label_sets_by_index(assignments)

    conflicts: list[dict[str, Any]] = []
    for block_index, labels in sorted(assignments.items()):
        if len(labels) <= 1:
            continue
        conflicts.append(
            {
                "warning": "gold_block_has_multiple_labels",
                "block_index": block_index,
                "labels": sorted(labels),
                "spans": assignment_spans.get(block_index, []),
            }
        )

    if conflicts:
        if conflict_output_path is not None:
            _write_jsonl(conflict_output_path, conflicts)

    max_index = max(assignments)
    missing = [index for index in range(max_index + 1) if index not in assignments]
    if require_exhaustive and missing:
        diagnostics = list(conflicts)
        diagnostics.append(
            {
                "error": "gold_missing_block_labels",
                "missing_block_indices": missing,
            }
        )
        if conflict_output_path is not None:
            _write_jsonl(conflict_output_path, diagnostics)
        raise ValueError(
            "Gold is not exhaustive: missing labels for "
            f"{len(missing)} blocks (examples: {missing[:10]})."
        )

    if profile_output is not None:
        profile_output.clear()
        profile_output.update(_serialize_blockization_profile(profile))

    return {
        block_index: set(labels)
        for block_index, labels in sorted(assignments.items())
    }


def load_stage_block_labels(stage_block_predictions_json_path: Path) -> dict[int, str]:
    if not stage_block_predictions_json_path.exists():
        raise FileNotFoundError(
            "Missing stage block predictions manifest: "
            f"{stage_block_predictions_json_path}"
        )
    payload = json.loads(stage_block_predictions_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Stage block predictions payload must be an object.")

    schema_version = str(payload.get("schema_version") or "")
    if schema_version != "stage_block_predictions.v1":
        raise ValueError(
            "Unsupported stage block predictions schema version: "
            f"{schema_version or '<missing>'}"
        )

    raw_block_labels = payload.get("block_labels")
    if not isinstance(raw_block_labels, dict):
        raise ValueError("Stage block predictions missing block_labels map.")

    labels: dict[int, str] = {}
    for raw_index, raw_label in raw_block_labels.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid block index in stage predictions: {raw_index!r}") from None
        label = str(raw_label or "").strip()
        if label not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Invalid stage label {label!r} at block {index}; expected one of {sorted(_FREEFORM_LABEL_SET)}"
            )
        labels[index] = label

    block_count_raw = payload.get("block_count")
    expected_count: int | None = None
    try:
        if block_count_raw is not None:
            expected_count = int(block_count_raw)
    except (TypeError, ValueError):
        expected_count = None

    if expected_count is not None and expected_count >= 0:
        missing = [index for index in range(expected_count) if index not in labels]
        if missing:
            raise ValueError(
                "Stage block predictions are incomplete: "
                f"missing labels for {len(missing)} indices."
            )

    resolved_label_sets = resolve_howto_label_sets_by_index(
        {
            index: {label}
            for index, label in labels.items()
        }
    )
    resolved_labels: dict[int, str] = {}
    for index, original_label in sorted(labels.items()):
        resolved_set = {
            str(label)
            for label in resolved_label_sets.get(index, {original_label})
            if str(label) in _FREEFORM_LABEL_SET
        }
        if not resolved_set:
            resolved_set = {"OTHER"}
        resolved_labels[index] = _primary_gold_label(
            resolved_set,
            pred_label=original_label,
        )

    return resolved_labels


def compute_block_metrics(
    gold: dict[int, str | list[str] | tuple[str, ...] | set[str]],
    pred: dict[int, str],
) -> dict[str, Any]:
    gold_sets: dict[int, set[str]] = {}
    for raw_index, raw_labels in gold.items():
        try:
            block_index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid gold block index: {raw_index!r}") from None
        gold_sets[block_index] = _coerce_gold_label_set(
            raw_labels,
            block_index=block_index,
        )

    gold_indices = set(gold_sets)
    pred_indices = set(pred)
    if gold_indices != pred_indices:
        missing_in_gold = sorted(pred_indices - gold_indices)
        missing_in_pred = sorted(gold_indices - pred_indices)
        raise ValueError(
            "Gold/pred block index mismatch. "
            f"missing_in_gold={len(missing_in_gold)} missing_in_pred={len(missing_in_pred)}"
        )

    ordered_indices = sorted(gold)
    total_blocks = len(ordered_indices)
    matches = sum(1 for index in ordered_indices if pred[index] in gold_sets[index])
    accuracy = (matches / total_blocks) if total_blocks else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label in FREEFORM_LABELS:
        tp = sum(
            1
            for index in ordered_indices
            if label in gold_sets[index] and pred[index] == label
        )
        fp = sum(
            1
            for index in ordered_indices
            if label not in gold_sets[index] and pred[index] == label
        )
        fn = sum(
            1
            for index in ordered_indices
            if label in gold_sets[index] and pred[index] != label
        )
        gold_total = tp + fn
        pred_total = tp + fp
        precision = tp / pred_total if pred_total else 0.0
        recall = tp / gold_total if gold_total else 0.0
        f1 = 0.0
        if precision + recall > 0:
            f1 = (2 * precision * recall) / (precision + recall)

        per_label[label] = {
            "gold_total": gold_total,
            "pred_total": pred_total,
            "gold_matched": tp,
            "pred_matched": tp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "missed_block_indices": [
                index
                for index in ordered_indices
                if label in gold_sets[index] and pred[index] != label
            ],
            "false_positive_block_indices": [
                index
                for index in ordered_indices
                if label not in gold_sets[index] and pred[index] == label
            ],
        }

    macro_labels = [
        label
        for label in FREEFORM_LABELS
        if label != "OTHER"
        and (
            per_label[label]["gold_total"] > 0
            or per_label[label]["pred_total"] > 0
        )
    ]
    macro_f1 = 0.0
    if macro_labels:
        macro_f1 = sum(per_label[label]["f1"] for label in macro_labels) / len(macro_labels)

    worst_label = None
    worst_recall = None
    worst_gold_total = 0
    for label in FREEFORM_LABELS:
        if label == "OTHER":
            continue
        gold_total = int(per_label[label]["gold_total"])
        if gold_total <= 0:
            continue
        recall = float(per_label[label]["recall"])
        if worst_recall is None or recall < worst_recall:
            worst_label = label
            worst_recall = recall
            worst_gold_total = gold_total

    confusion: dict[str, dict[str, int]] = {}
    effective_gold: dict[int, str] = {
        index: _primary_gold_label(gold_sets[index], pred_label=pred[index])
        for index in ordered_indices
    }
    for index in ordered_indices:
        gold_label = effective_gold[index]
        pred_label = pred[index]
        by_gold = confusion.setdefault(gold_label, {})
        by_gold[pred_label] = int(by_gold.get(pred_label, 0)) + 1

    mismatched_indices = [
        index for index in ordered_indices if pred[index] not in gold_sets[index]
    ]
    missed_gold_blocks = [
        {
            "block_index": index,
            "gold_label": effective_gold[index],
            "gold_labels": sorted(gold_sets[index]),
            "pred_label": pred[index],
        }
        for index in mismatched_indices
        if effective_gold[index] != "OTHER"
    ]
    wrong_label_blocks = [
        {
            "block_index": index,
            "gold_label": effective_gold[index],
            "gold_labels": sorted(gold_sets[index]),
            "pred_label": pred[index],
        }
        for index in mismatched_indices
    ]

    counts = {
        "gold_total": total_blocks,
        "pred_total": total_blocks,
        "gold_matched": matches,
        "pred_matched": matches,
        "gold_missed": total_blocks - matches,
        "pred_false_positive": total_blocks - matches,
    }

    return {
        "eval_type": "stage_block_classification",
        "labels": list(FREEFORM_LABELS),
        "counts": counts,
        "strict_accuracy": accuracy,
        "overall_block_accuracy": accuracy,
        "macro_f1_excluding_other": macro_f1,
        "macro_f1_labels": macro_labels,
        "worst_label_recall": {
            "label": worst_label,
            "recall": worst_recall,
            "gold_total": worst_gold_total,
        },
        "per_label": per_label,
        "confusion": confusion,
        "missed_gold_blocks": missed_gold_blocks,
        "wrong_label_blocks": wrong_label_blocks,
    }


def _most_common_confusions(
    confusion: dict[str, dict[str, int]],
    *,
    limit: int = 10,
) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for gold_label, by_pred in confusion.items():
        for pred_label, count in by_pred.items():
            if gold_label == pred_label:
                continue
            rows.append((gold_label, pred_label, int(count)))
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows[:limit]


def format_stage_block_eval_report_md(report: dict[str, Any]) -> str:
    def _format_metric(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.3f}"

    counts = report.get("counts") or {}
    worst = report.get("worst_label_recall") or {}
    lines = [
        "# Stage Block Evaluation",
        "",
        f"- Overall block accuracy: {float(report.get('overall_block_accuracy', 0.0)):.3f}",
        (
            "- Macro F1 (excluding OTHER): "
            f"{float(report.get('macro_f1_excluding_other', 0.0)):.3f}"
        ),
        (
            "- WORST-LABEL RECALL: "
            f"{worst.get('label') or 'n/a'} "
            f"{float(worst.get('recall') or 0.0):.3f}"
        ),
        "",
        "## Counts",
        "",
        f"- Blocks: {int(counts.get('gold_total') or 0)}",
        f"- Correct: {int(counts.get('gold_matched') or 0)}",
        f"- Mismatched: {int(counts.get('gold_missed') or 0)}",
        "",
        "## Per Label",
        "",
    ]

    per_label = report.get("per_label") or {}
    if isinstance(per_label, dict):
        for label in FREEFORM_LABELS:
            stats = per_label.get(label)
            if not isinstance(stats, dict):
                continue
            lines.append(
                "- "
                f"{label}: "
                f"gold={int(stats.get('gold_total') or 0)} "
                f"pred={int(stats.get('pred_total') or 0)} "
                f"precision={float(stats.get('precision') or 0.0):.3f} "
                f"recall={float(stats.get('recall') or 0.0):.3f} "
                f"f1={float(stats.get('f1') or 0.0):.3f}"
            )

    segmentation = report.get("segmentation")
    if isinstance(segmentation, dict):
        lines.extend(["", "## Segmentation Boundary Metrics", ""])
        lines.append(
            "- Label projection: "
            f"{segmentation.get('label_projection') or _SEGMENTATION_LABEL_PROJECTION_CORE}"
        )
        lines.append(
            "- Boundary tolerance (blocks): "
            f"{int(segmentation.get('boundary_tolerance_blocks') or 0)}"
        )

        metrics_requested = segmentation.get("metrics_requested")
        if isinstance(metrics_requested, list) and metrics_requested:
            lines.append(
                "- Metrics requested: " + ", ".join(str(value) for value in metrics_requested)
            )

        boundaries = segmentation.get("boundaries")
        if isinstance(boundaries, dict):
            boundary_order = (
                "ingredient_start",
                "ingredient_end",
                "instruction_start",
                "instruction_end",
                "recipe_split",
                "overall_micro",
            )
            for boundary_name in boundary_order:
                payload = boundaries.get(boundary_name)
                if not isinstance(payload, dict):
                    continue
                label = boundary_name.replace("_", " ")
                lines.append(
                    "- "
                    f"{label}: "
                    f"gold={int(payload.get('gold_count') or 0)} "
                    f"pred={int(payload.get('pred_count') or 0)} "
                    f"tp={int(payload.get('tp') or 0)} "
                    f"fp={int(payload.get('fp') or 0)} "
                    f"fn={int(payload.get('fn') or 0)} "
                    f"precision={_format_metric(payload.get('precision'))} "
                    f"recall={_format_metric(payload.get('recall'))} "
                    f"f1={_format_metric(payload.get('f1'))}"
                )
                if bool(payload.get("not_applicable")):
                    lines.append("  note: no gold boundaries for this category")

        segeval = segmentation.get("segeval")
        if isinstance(segeval, dict) and segeval:
            lines.extend(["", "### Optional segeval Metrics", ""])
            for metric_name in ("pk", "windowdiff", "boundary_similarity"):
                if metric_name not in segeval:
                    continue
                lines.append(
                    f"- {metric_name}: {_format_metric(segeval.get(metric_name))}"
                )

    taxonomy = {}
    if isinstance(segmentation, dict):
        raw_taxonomy = segmentation.get("error_taxonomy")
        if isinstance(raw_taxonomy, dict):
            taxonomy = raw_taxonomy
    if taxonomy:
        lines.extend(["", "## Error Taxonomy", ""])
        bucket_counts = taxonomy.get("bucket_counts")
        if isinstance(bucket_counts, dict):
            for bucket_name in (
                "extraction_failure",
                "boundary_errors",
                "ingredient_errors",
                "instruction_errors",
                "yield_time_errors",
            ):
                lines.append(
                    "- "
                    f"{bucket_name}: "
                    f"{int(bucket_counts.get(bucket_name) or 0)}"
                )
        if "total_count" in taxonomy:
            lines.append(f"- total: {int(taxonomy.get('total_count') or 0)}")

    confusion = report.get("confusion")
    if isinstance(confusion, dict):
        common_confusions = _most_common_confusions(confusion)
        lines.extend(["", "## Most Common Confusions", ""])
        if common_confusions:
            for gold_label, pred_label, count in common_confusions:
                lines.append(f"- {gold_label} -> {pred_label}: {count}")
        else:
            lines.append("- None")

    artifacts = report.get("artifacts")
    if isinstance(artifacts, dict):
        lines.extend(["", "## Debug Pointers", ""])
        if artifacts.get("missed_gold_blocks_jsonl"):
            lines.append(
                "- missed_gold_blocks.jsonl: "
                f"{artifacts.get('missed_gold_blocks_jsonl')}"
            )
        if artifacts.get("wrong_label_blocks_jsonl"):
            lines.append(
                "- wrong_label_blocks.jsonl: "
                f"{artifacts.get('wrong_label_blocks_jsonl')}"
            )
        if artifacts.get("missed_gold_boundaries_jsonl"):
            lines.append(
                "- missed_gold_boundaries.jsonl: "
                f"{artifacts.get('missed_gold_boundaries_jsonl')}"
            )
        if artifacts.get("false_positive_boundaries_jsonl"):
            lines.append(
                "- false_positive_boundaries.jsonl: "
                f"{artifacts.get('false_positive_boundaries_jsonl')}"
            )
        if artifacts.get("gold_conflicts_jsonl"):
            lines.append(
                "- gold_conflicts.jsonl: "
                f"{artifacts.get('gold_conflicts_jsonl')}"
            )

    lines.append("")
    return "\n".join(lines)


def evaluate_stage_blocks(
    *,
    gold_freeform_jsonl: Path,
    stage_predictions_json: Path,
    extracted_blocks_json: Path,
    out_dir: Path,
    label_projection: str = _SEGMENTATION_LABEL_PROJECTION_CORE,
    boundary_tolerance_blocks: int = 0,
    segmentation_metrics: str | list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    if boundary_tolerance_blocks < 0:
        raise ValueError("boundary_tolerance_blocks must be >= 0.")
    selected_segmentation_metrics = _parse_segmentation_metric_selection(segmentation_metrics)

    evaluation_started = time.monotonic()
    resource_start = _capture_eval_resource_snapshot()
    subphase_seconds: dict[str, float] = {}

    out_dir.mkdir(parents=True, exist_ok=True)
    gold_conflicts_path = out_dir / "gold_conflicts.jsonl"

    load_gold_started = time.monotonic()
    gold_profile: dict[str, Any] = {}
    gold = load_gold_block_labels(
        gold_freeform_jsonl,
        conflict_output_path=gold_conflicts_path,
        require_exhaustive=False,
        profile_output=gold_profile,
    )
    subphase_seconds["load_gold_seconds"] = max(0.0, time.monotonic() - load_gold_started)

    load_prediction_started = time.monotonic()
    pred = load_stage_block_labels(stage_predictions_json)
    prediction_profile = _load_extracted_block_profile(extracted_blocks_json)
    stage_payload = json.loads(stage_predictions_json.read_text(encoding="utf-8"))
    block_texts = _load_extracted_block_texts(extracted_blocks_json)
    subphase_seconds["load_prediction_seconds"] = max(
        0.0,
        time.monotonic() - load_prediction_started,
    )

    diagnostics_started = time.monotonic()
    gold_indices = set(gold)
    pred_indices = set(pred)
    missing_gold = sorted(pred_indices - gold_indices)

    blockization_diagnostics = _collect_blockization_diagnostics(
        gold_profile=gold_profile,
        prediction_profile=prediction_profile,
        missing_gold_indices=missing_gold,
        pred_block_count=len(pred_indices),
    )
    if blockization_diagnostics:
        diagnostics = _read_jsonl(gold_conflicts_path)
        diagnostics.extend(blockization_diagnostics)
        _write_jsonl(gold_conflicts_path, diagnostics)
        fatal_diagnostic = next(
            (
                item
                for item in blockization_diagnostics
                if isinstance(item, dict)
                and item.get("error") == "gold_prediction_blockization_mismatch"
            ),
            None,
        )
        if isinstance(fatal_diagnostic, dict):
            raise ValueError(_format_blockization_mismatch_message(fatal_diagnostic))

    if missing_gold:
        for block_index in missing_gold:
            gold[block_index] = {"OTHER"}
        diagnostics = _read_jsonl(gold_conflicts_path)
        diagnostics.append(
            {
                "warning": "gold_missing_block_labels_defaulted_to_other",
                "missing_gold_indices": missing_gold,
                "default_label": "OTHER",
            }
        )
        _write_jsonl(gold_conflicts_path, diagnostics)

    gold_indices = set(gold)
    extra_gold = sorted(gold_indices - pred_indices)
    if extra_gold:
        diagnostics = _read_jsonl(gold_conflicts_path)
        diagnostics.append(
            {
                "error": "gold_pred_block_mismatch",
                "extra_gold_indices": extra_gold,
            }
        )
        _write_jsonl(gold_conflicts_path, diagnostics)
        raise ValueError(
            "Gold contains block labels not present in predictions. "
            f"extra_gold={len(extra_gold)}"
        )
    subphase_seconds["pre_metrics_checks_seconds"] = max(
        0.0,
        time.monotonic() - diagnostics_started,
    )

    metrics_started = time.monotonic()
    report = compute_block_metrics(gold, pred)
    subphase_seconds["metrics_seconds"] = max(0.0, time.monotonic() - metrics_started)

    workbook_slug = str(stage_payload.get("workbook_slug") or "")
    source_file = str(stage_payload.get("source_file") or "")

    segmentation_started = time.monotonic()
    (
        projected_gold_labels,
        projected_pred_labels,
        projected_gold_by_index,
        projected_pred_by_index,
    ) = _build_projected_structural_sequences(
        gold=gold,
        pred=pred,
        label_projection=label_projection,
    )
    segmentation = compute_segmentation_boundaries(
        labels_gold=projected_gold_labels,
        labels_pred=projected_pred_labels,
        tolerance_blocks=boundary_tolerance_blocks,
    )
    segmentation_payload: dict[str, Any] = {
        "label_projection": label_projection,
        "boundary_tolerance_blocks": int(boundary_tolerance_blocks),
        "metrics_requested": selected_segmentation_metrics,
        "boundaries": segmentation.get("boundaries", {}),
        "error_taxonomy": _compute_error_taxonomy(
            gold_projected=projected_gold_by_index,
            pred_projected=projected_pred_by_index,
            segmentation_boundaries=segmentation,
        ),
    }
    optional_metric_names = [
        metric_name
        for metric_name in selected_segmentation_metrics
        if metric_name in _OPTIONAL_SEGMENTATION_METRICS
    ]
    if optional_metric_names:
        optional_metrics_started = time.monotonic()
        from cookimport.bench.segeval_adapter import (
            OptionalSegmentationDependencyError,
            compute_optional_segmentation_metrics,
        )

        try:
            segmentation_payload["segeval"] = compute_optional_segmentation_metrics(
                labels_gold=projected_gold_labels,
                labels_pred=projected_pred_labels,
                requested_metrics=optional_metric_names,
            )
        except OptionalSegmentationDependencyError as exc:
            raise ValueError(str(exc)) from exc
        subphase_seconds["segmentation_optional_metrics_seconds"] = max(
            0.0,
            time.monotonic() - optional_metrics_started,
        )
    report["segmentation"] = segmentation_payload
    subphase_seconds["segmentation_seconds"] = max(
        0.0,
        time.monotonic() - segmentation_started,
    )

    mismatch_rows_started = time.monotonic()
    wrong_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    for mismatch in report.get("wrong_label_blocks", []):
        if not isinstance(mismatch, dict):
            continue
        block_index = int(mismatch.get("block_index", -1))
        gold_label = str(mismatch.get("gold_label") or "")
        raw_gold_labels = mismatch.get("gold_labels")
        gold_labels: list[str] = []
        if isinstance(raw_gold_labels, list):
            for value in raw_gold_labels:
                label = str(value or "").strip()
                if not label:
                    continue
                gold_labels.append(label)
        if not gold_labels and gold_label:
            gold_labels = [gold_label]
        pred_label = str(mismatch.get("pred_label") or "")
        row = {
            "block_index": block_index,
            "gold_label": gold_label,
            "gold_labels": sorted(set(gold_labels)),
            "pred_label": pred_label,
            "block_text_excerpt": _excerpt(block_texts.get(block_index, "")),
            "workbook_slug": workbook_slug,
            "source_file": source_file,
        }
        wrong_rows.append(row)
        if gold_label != "OTHER":
            missed_rows.append(dict(row))
    subphase_seconds["mismatch_rows_seconds"] = max(
        0.0,
        time.monotonic() - mismatch_rows_started,
    )

    boundary_mismatch_rows_started = time.monotonic()
    missed_boundary_rows, false_positive_boundary_rows = _build_boundary_mismatch_rows(
        segmentation_boundaries=segmentation,
        block_texts=block_texts,
        workbook_slug=workbook_slug,
        source_file=source_file,
    )
    subphase_seconds["boundary_mismatch_rows_seconds"] = max(
        0.0,
        time.monotonic() - boundary_mismatch_rows_started,
    )

    artifact_write_started = time.monotonic()
    missed_path = out_dir / "missed_gold_blocks.jsonl"
    wrong_path = out_dir / "wrong_label_blocks.jsonl"
    missed_boundaries_path = out_dir / "missed_gold_boundaries.jsonl"
    false_positive_boundaries_path = out_dir / "false_positive_boundaries.jsonl"
    _write_jsonl(missed_path, missed_rows)
    _write_jsonl(wrong_path, wrong_rows)
    _write_jsonl(missed_boundaries_path, missed_boundary_rows)
    _write_jsonl(false_positive_boundaries_path, false_positive_boundary_rows)

    # Legacy aliases keep existing bench packet/report tooling functioning.
    legacy_missed = [
        {
            "span_id": f"block:{row['block_index']}",
            "label": row["gold_label"],
            "start_block_index": row["block_index"],
            "end_block_index": row["block_index"],
            "pred_label": row["pred_label"],
        }
        for row in missed_rows
    ]
    legacy_false_positive = [
        {
            "span_id": f"block:{row['block_index']}",
            "label": row["pred_label"],
            "start_block_index": row["block_index"],
            "end_block_index": row["block_index"],
            "gold_label": row["gold_label"],
        }
        for row in wrong_rows
        if row["pred_label"] != "OTHER"
    ]
    _write_jsonl(out_dir / "missed_gold_spans.jsonl", legacy_missed)
    _write_jsonl(out_dir / "false_positive_preds.jsonl", legacy_false_positive)
    subphase_seconds["artifact_write_seconds"] = max(
        0.0,
        time.monotonic() - artifact_write_started,
    )

    report["source"] = {
        "workbook_slug": workbook_slug,
        "source_file": source_file,
        "source_hash": stage_payload.get("source_hash"),
    }
    report["blockization_profiles"] = {
        "gold": gold_profile,
        "prediction": prediction_profile,
    }
    if blockization_diagnostics:
        report["diagnostics"] = {
            "blockization": blockization_diagnostics,
        }
    report["artifacts"] = {
        "eval_report_json": str(out_dir / "eval_report.json"),
        "eval_report_md": str(out_dir / "eval_report.md"),
        "missed_gold_blocks_jsonl": str(missed_path),
        "wrong_label_blocks_jsonl": str(wrong_path),
        "missed_gold_boundaries_jsonl": str(missed_boundaries_path),
        "false_positive_boundaries_jsonl": str(false_positive_boundaries_path),
        "gold_conflicts_jsonl": (
            str(gold_conflicts_path) if gold_conflicts_path.exists() else ""
        ),
    }
    overall_boundary_metrics = report["segmentation"].get("boundaries", {}).get("overall_micro", {})
    if not isinstance(overall_boundary_metrics, dict):
        overall_boundary_metrics = {}
    evaluation_total_seconds = max(0.0, time.monotonic() - evaluation_started)
    resource_end = _capture_eval_resource_snapshot()
    report["evaluation_telemetry"] = {
        "total_seconds": evaluation_total_seconds,
        "subphases": {
            key: max(0.0, float(value))
            for key, value in subphase_seconds.items()
        },
        "resources": _diff_eval_resource_snapshots(resource_start, resource_end),
        "work_units": {
            "gold_block_count": float(len(gold)),
            "prediction_block_count": float(len(pred)),
            "missing_gold_defaulted_count": float(len(missing_gold)),
            "wrong_label_count": float(len(wrong_rows)),
            "segmentation_gold_boundary_count": float(
                int(overall_boundary_metrics.get("gold_count") or 0)
            ),
            "segmentation_pred_boundary_count": float(
                int(overall_boundary_metrics.get("pred_count") or 0)
            ),
            "segmentation_false_positive_boundary_count": float(
                int(overall_boundary_metrics.get("fp") or 0)
            ),
            "segmentation_missed_boundary_count": float(
                int(overall_boundary_metrics.get("fn") or 0)
            ),
        },
    }

    report_json_path = out_dir / "eval_report.json"
    report_md_path = out_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path.write_text(
        format_stage_block_eval_report_md(report),
        encoding="utf-8",
    )

    return {
        "report": report,
        "missed_gold_blocks": missed_rows,
        "wrong_label_blocks": wrong_rows,
        "missed_gold_boundaries": missed_boundary_rows,
        "false_positive_boundaries": false_positive_boundary_rows,
        "missed_gold": legacy_missed,
        "false_positive_preds": legacy_false_positive,
    }
