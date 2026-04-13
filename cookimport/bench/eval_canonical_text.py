from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from cookimport.bench.canonical_alignment_cache import (
    CANONICAL_ALIGNMENT_ALGO_VERSION,
    CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
    CanonicalAlignmentDiskCache,
    build_cache_file_key,
    hash_block_boundaries,
    make_cache_entry,
    sha256_text,
)
from cookimport.bench.eval_stage_blocks import (
    _SEGMENTATION_LABEL_PROJECTION_CORE,
    _build_boundary_mismatch_rows,
    _build_projected_structural_sequences,
    _compute_error_taxonomy,
    compute_block_metrics,
    load_stage_block_prediction_manifest,
)
from cookimport.bench.segmentation_metrics import compute_segmentation_boundaries
from cookimport.bench.sequence_matcher_select import (
    SequenceMatcher as SelectedSequenceMatcher,
    get_sequence_matcher_selection,
)
from cookimport.labelstudio.canonical_gold import ensure_canonical_gold_artifacts
from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_BLOCK_SEPARATOR = "\n\n"
_ALIGNMENT_CHAR_MAP = {
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "…": ".",
}

_ALIGNMENT_STRATEGY_ENV = "COOKIMPORT_CANONICAL_ALIGNMENT_STRATEGY"
_ALIGNMENT_STRATEGIES = {"auto", "fast", "global"}
_ALIGNMENT_FAST_DEPRECATION_REASON = "fast_alignment_deprecated_accuracy_risk"
_ALIGNMENT_FAST_DEPRECATION_MESSAGE = (
    "Fast canonical alignment is disabled due to accuracy risk; "
    "global SequenceMatcher alignment is enforced."
)

_FAST_ALIGN_MIN_WINDOW_CHARS = 8000
_FAST_ALIGN_WINDOW_BLOCK_MULTIPLIER = 8
_FAST_ALIGN_LOOKBACK_CHARS = 320
_FAST_ALIGN_LOCAL_EXPAND_CHARS = 6000
_FAST_ALIGN_LOCAL_MIN_RATIO = 0.68
_FAST_ALIGN_LOCAL_MIN_CHARS = 24

_AUTO_MIN_NONEMPTY_BLOCK_MATCH_RATIO = 0.98
_AUTO_MIN_PREDICTION_CHAR_COVERAGE = 0.96
_AUTO_LOCAL_CONFIDENCE_MIN_RATIO = 0.93
_CANONICAL_BOUNDARY_OVERLAP_THRESHOLD = 0.5
_CANONICAL_SEGMENTATION_BOUNDARY_TOLERANCE_BLOCKS = 0
_CANONICAL_SEGMENTATION_METRICS_REQUESTED: tuple[str, ...] = ("boundary_f1",)
_TITLE_STRUCTURE_SUPPORT_LABELS = {
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
}
_TITLE_STRUCTURE_LOOKAHEAD_LINES = 8

try:  # pragma: no cover - non-Unix runtimes may not expose resource.
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _normalize_for_alignment(text: str) -> str:
    chars: list[str] = []
    for raw in text:
        mapped = _ALIGNMENT_CHAR_MAP.get(raw, raw)
        if mapped.isspace():
            chars.append(" ")
        else:
            chars.append(mapped.lower())
    return "".join(chars)


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


def _load_prediction_blocks(
    *,
    extracted_blocks_json: Path,
    stage_labels: dict[int, str],
) -> list[dict[str, Any]]:
    payload = json.loads(extracted_blocks_json.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            records = [row for row in blocks if isinstance(row, dict)]

    rows: list[dict[str, Any]] = []
    for row in records:
        block_index = _coerce_int(row.get("index"))
        if block_index is None:
            block_index = _coerce_int(row.get("block_index"))
        if block_index is None:
            continue
        label = stage_labels.get(block_index, "OTHER")
        if label not in _FREEFORM_LABEL_SET:
            label = "OTHER"
        rows.append(
            {
                "block_index": block_index,
                "label": label,
                "text": str(row.get("text") or ""),
            }
        )
    rows.sort(key=lambda row: int(row["block_index"]))
    return rows


def _join_blocks_with_offsets(
    blocks: list[dict[str, Any]],
    *,
    separator: str = _BLOCK_SEPARATOR,
) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    offset_rows: list[dict[str, Any]] = []
    cursor = 0
    for position, row in enumerate(blocks):
        text = str(row.get("text") or "")
        start_char = cursor
        end_char = start_char + len(text)
        offset_rows.append(
            {
                "block_index": int(row["block_index"]),
                "label": str(row.get("label") or "OTHER"),
                "text": text,
                "start_char": start_char,
                "end_char": end_char,
            }
        )
        parts.append(text)
        if position < len(blocks) - 1:
            parts.append(separator)
            cursor = end_char + len(separator)
        else:
            cursor = end_char
    return "".join(parts), offset_rows


def _interval_coverage(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals, key=lambda row: row[0])
    covered = 0
    current_start, current_end = ordered[0]
    for start_char, end_char in ordered[1:]:
        if start_char > current_end:
            covered += max(0, current_end - current_start)
            current_start, current_end = start_char, end_char
            continue
        current_end = max(current_end, end_char)
    covered += max(0, current_end - current_start)
    return covered


def _overlap_len(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> int:
    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    return max(0, overlap_end - overlap_start)


def _canonical_boundary_overlap_ratio(
    *,
    pred_start: int,
    pred_end: int,
    gold_start: int,
    gold_end: int,
) -> float:
    intersection = max(0, min(pred_end, gold_end) - max(pred_start, gold_start) + 1)
    if intersection <= 0:
        return 0.0
    union = (pred_end - pred_start + 1) + (gold_end - gold_start + 1) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _canonical_boundary_classification(
    *,
    pred_start: int,
    pred_end: int,
    gold_start: int,
    gold_end: int,
) -> str:
    if pred_start == gold_start and pred_end == gold_end:
        return "correct"
    if pred_start <= gold_start and pred_end >= gold_end:
        return "over"
    if pred_start >= gold_start and pred_end <= gold_end:
        return "under"
    return "partial"


def _build_canonical_line_boundary_spans(
    *,
    canonical_lines: list[dict[str, Any]],
    char_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not canonical_lines or not char_spans:
        return []

    ordered_lines = sorted(canonical_lines, key=lambda row: int(row["start_char"]))
    ordered_spans = sorted(
        char_spans,
        key=lambda row: (
            int(_coerce_int(row.get("start_char")) or -1),
            int(_coerce_int(row.get("end_char")) or -1),
        ),
    )

    line_spans: list[dict[str, Any]] = []
    line_cursor = 0
    line_total = len(ordered_lines)
    for span in ordered_spans:
        start_char = _coerce_int(span.get("start_char"))
        end_char = _coerce_int(span.get("end_char"))
        if start_char is None or end_char is None or end_char <= start_char:
            continue
        label = normalize_freeform_label(str(span.get("label") or "OTHER"))
        if label not in _FREEFORM_LABEL_SET:
            label = "OTHER"
        span_id = str(span.get("span_id") or "").strip()
        if not span_id:
            span_id = f"span:{len(line_spans)}"

        while (
            line_cursor < line_total
            and int(ordered_lines[line_cursor]["end_char"]) <= start_char
        ):
            line_cursor += 1

        first_line: int | None = None
        last_line: int | None = None
        scan_index = line_cursor
        while scan_index < line_total:
            line_row = ordered_lines[scan_index]
            line_start = int(line_row["start_char"])
            if line_start >= end_char:
                break
            line_end = int(line_row["end_char"])
            if line_end > start_char:
                line_index = int(line_row["line_index"])
                if first_line is None:
                    first_line = line_index
                last_line = line_index
            scan_index += 1

        if first_line is None or last_line is None:
            continue

        line_spans.append(
            {
                "span_id": span_id,
                "label": label,
                "start_block_index": first_line,
                "end_block_index": last_line,
            }
        )

    return line_spans


def _compute_canonical_boundary_counts(
    *,
    canonical_lines: list[dict[str, Any]],
    gold_spans: list[dict[str, Any]],
    aligned_prediction_blocks: list[dict[str, Any]],
    overlap_threshold: float,
) -> dict[str, int]:
    boundary_counts = {"correct": 0, "over": 0, "under": 0, "partial": 0}
    if not canonical_lines:
        return boundary_counts

    gold_char_spans = [
        {
            "span_id": str(row.get("span_id") or f"gold:{index}"),
            "label": str(row.get("label") or "OTHER"),
            "start_char": int(row["start_char"]),
            "end_char": int(row["end_char"]),
        }
        for index, row in enumerate(gold_spans)
        if isinstance(row, dict)
    ]
    pred_char_spans = [
        {
            "span_id": (
                f"pred:{int(_coerce_int(row.get('block_index')) or index)}:{index}"
            ),
            "label": str(row.get("label") or "OTHER"),
            "start_char": int(_coerce_int(row.get("canonical_start_char")) or 0),
            "end_char": int(_coerce_int(row.get("canonical_end_char")) or 0),
        }
        for index, row in enumerate(aligned_prediction_blocks)
        if isinstance(row, dict) and bool(row.get("matched"))
    ]

    gold_line_spans = _build_canonical_line_boundary_spans(
        canonical_lines=canonical_lines,
        char_spans=gold_char_spans,
    )
    pred_line_spans = _build_canonical_line_boundary_spans(
        canonical_lines=canonical_lines,
        char_spans=pred_char_spans,
    )
    if not gold_line_spans or not pred_line_spans:
        return boundary_counts

    gold_by_label: dict[str, list[dict[str, Any]]] = {}
    pred_by_label: dict[str, list[dict[str, Any]]] = {}
    for span in gold_line_spans:
        gold_by_label.setdefault(str(span["label"]), []).append(span)
    for span in pred_line_spans:
        pred_by_label.setdefault(str(span["label"]), []).append(span)
    for spans in gold_by_label.values():
        spans.sort(
            key=lambda row: (
                int(row["start_block_index"]),
                int(row["end_block_index"]),
            )
        )
    for spans in pred_by_label.values():
        spans.sort(
            key=lambda row: (
                int(row["start_block_index"]),
                int(row["end_block_index"]),
            )
        )

    for label, gold_label_spans in gold_by_label.items():
        pred_label_spans = pred_by_label.get(label, [])
        if not pred_label_spans:
            continue
        pred_cursor = 0
        pred_total = len(pred_label_spans)
        for gold_span in gold_label_spans:
            gold_start = int(gold_span["start_block_index"])
            gold_end = int(gold_span["end_block_index"])

            while (
                pred_cursor < pred_total
                and int(pred_label_spans[pred_cursor]["end_block_index"]) < gold_start
            ):
                pred_cursor += 1

            best_overlap = 0.0
            best_pred: dict[str, Any] | None = None
            scan_index = pred_cursor
            while scan_index < pred_total:
                pred_span = pred_label_spans[scan_index]
                pred_start = int(pred_span["start_block_index"])
                if pred_start > gold_end:
                    break
                pred_end = int(pred_span["end_block_index"])
                overlap = _canonical_boundary_overlap_ratio(
                    pred_start=pred_start,
                    pred_end=pred_end,
                    gold_start=gold_start,
                    gold_end=gold_end,
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_pred = pred_span
                scan_index += 1

            if best_pred is None or best_overlap < overlap_threshold:
                continue

            boundary_bucket = _canonical_boundary_classification(
                pred_start=int(best_pred["start_block_index"]),
                pred_end=int(best_pred["end_block_index"]),
                gold_start=gold_start,
                gold_end=gold_end,
            )
            boundary_counts[boundary_bucket] = (
                int(boundary_counts.get(boundary_bucket, 0)) + 1
            )

    return boundary_counts


def _collect_matching_blocks(
    matcher: Any,
) -> list[tuple[int, int, int]]:
    return [
        (int(match.a), int(match.a + match.size), int(match.b))
        for match in matcher.get_matching_blocks()
        if int(match.size) > 0
    ]


def _alignment_summary(
    *,
    aligned_rows: list[dict[str, Any]],
    prediction_blocks: list[dict[str, Any]],
    canonical_char_count: int,
    matching_block_count: int | None = None,
) -> dict[str, Any]:
    matched_ranges: list[tuple[int, int]] = []
    matched_block_count = 0
    nonempty_block_count = 0
    nonempty_matched_count = 0
    prediction_char_count = 0
    prediction_chars_matched = 0

    for row in aligned_rows:
        block_len = max(0, _coerce_int(row.get("block_char_count")) or 0)
        matched_chars = max(0, _coerce_int(row.get("matched_chars")) or 0)
        prediction_char_count += block_len
        prediction_chars_matched += min(block_len, matched_chars)
        if block_len > 0:
            nonempty_block_count += 1
        if not bool(row.get("matched")):
            continue
        canonical_start = _coerce_int(row.get("canonical_start_char"))
        canonical_end = _coerce_int(row.get("canonical_end_char"))
        if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
            continue
        matched_ranges.append((canonical_start, canonical_end))
        matched_block_count += 1
        if block_len > 0:
            nonempty_matched_count += 1

    covered_chars = _interval_coverage(matched_ranges)
    block_count = len(prediction_blocks)
    alignment: dict[str, Any] = {
        "canonical_char_count": canonical_char_count,
        "canonical_chars_covered": covered_chars,
        "canonical_char_coverage": (
            (covered_chars / canonical_char_count) if canonical_char_count > 0 else 0.0
        ),
        "prediction_block_count": block_count,
        "prediction_blocks_matched": matched_block_count,
        "prediction_block_match_ratio": (
            (matched_block_count / block_count) if block_count > 0 else 0.0
        ),
        "nonempty_prediction_block_count": nonempty_block_count,
        "nonempty_prediction_blocks_matched": nonempty_matched_count,
        "nonempty_prediction_block_match_ratio": (
            (nonempty_matched_count / nonempty_block_count)
            if nonempty_block_count > 0
            else 1.0
        ),
        "prediction_char_count": prediction_char_count,
        "prediction_chars_matched": prediction_chars_matched,
        "prediction_char_coverage": (
            (prediction_chars_matched / prediction_char_count)
            if prediction_char_count > 0
            else 1.0
        ),
    }
    if matching_block_count is not None:
        alignment["matching_block_count"] = matching_block_count
    return alignment


def _aligned_row(
    *,
    block: dict[str, Any],
    canonical_start: int | None,
    canonical_end: int | None,
    matched_chars: int,
) -> dict[str, Any]:
    pred_start = int(block["start_char"])
    pred_end = int(block["end_char"])
    block_length = max(0, pred_end - pred_start)
    normalized_matched_chars = min(block_length, max(0, int(matched_chars)))
    match_ratio = (
        (normalized_matched_chars / block_length)
        if block_length > 0
        else 0.0
    )
    matched = (
        canonical_start is not None
        and canonical_end is not None
        and canonical_end > canonical_start
        and normalized_matched_chars > 0
    )
    return {
        "block_index": int(block["block_index"]),
        "label": str(block.get("label") or "OTHER"),
        "block_text_excerpt": _excerpt(str(block.get("text") or "")),
        "prediction_start_char": pred_start,
        "prediction_end_char": pred_end,
        "canonical_start_char": canonical_start if matched else None,
        "canonical_end_char": canonical_end if matched else None,
        "matched_chars": normalized_matched_chars,
        "block_char_count": block_length,
        "match_ratio": round(match_ratio, 6),
        "matched": matched,
    }


def _alignment_cache_payload(
    *,
    aligned_rows: list[dict[str, Any]],
    alignment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "aligned_rows": [dict(row) for row in aligned_rows],
        "alignment": dict(alignment),
    }


def _load_alignment_cache_payload(
    *,
    payload: dict[str, Any],
    expected_block_count: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, None, "cache_payload_not_object"
    aligned_rows_raw = payload.get("aligned_rows")
    alignment_raw = payload.get("alignment")
    if not isinstance(aligned_rows_raw, list):
        return None, None, "cache_payload_missing_aligned_rows"
    if not isinstance(alignment_raw, dict):
        return None, None, "cache_payload_missing_alignment"
    if len(aligned_rows_raw) != max(0, int(expected_block_count)):
        return None, None, "cache_payload_block_count_mismatch"
    validated_rows: list[dict[str, Any]] = []
    for index, row in enumerate(aligned_rows_raw):
        if not isinstance(row, dict):
            return None, None, f"cache_payload_row_not_object:{index}"
        block_index = _coerce_int(row.get("block_index"))
        prediction_start = _coerce_int(row.get("prediction_start_char"))
        prediction_end = _coerce_int(row.get("prediction_end_char"))
        matched_chars = _coerce_int(row.get("matched_chars"))
        block_char_count = _coerce_int(row.get("block_char_count"))
        if block_index is None:
            return None, None, f"cache_payload_row_missing_block_index:{index}"
        if prediction_start is None or prediction_end is None or prediction_end < prediction_start:
            return None, None, f"cache_payload_row_bad_prediction_range:{index}"
        if matched_chars is None or block_char_count is None:
            return None, None, f"cache_payload_row_missing_counts:{index}"
        matched = row.get("matched")
        if not isinstance(matched, bool):
            return None, None, f"cache_payload_row_missing_matched_flag:{index}"
        canonical_start = _coerce_int(row.get("canonical_start_char"))
        canonical_end = _coerce_int(row.get("canonical_end_char"))
        if matched:
            if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
                return None, None, f"cache_payload_row_bad_canonical_range:{index}"
        validated_rows.append(dict(row))
    return validated_rows, dict(alignment_raw), None


def _align_prediction_blocks_global(
    *,
    prediction_text: str,
    canonical_text: str,
    prediction_blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, float]]:
    normalize_prediction_started = time.monotonic()
    prediction_normalized = _normalize_for_alignment(prediction_text)
    normalize_prediction_seconds = max(
        0.0, time.monotonic() - normalize_prediction_started
    )

    normalize_canonical_started = time.monotonic()
    canonical_normalized = _normalize_for_alignment(canonical_text)
    normalize_canonical_seconds = max(
        0.0, time.monotonic() - normalize_canonical_started
    )

    aligned_rows, alignment, alignment_phase_seconds = _align_prediction_blocks_global_from_normalized(
        prediction_normalized=prediction_normalized,
        canonical_normalized=canonical_normalized,
        prediction_blocks=prediction_blocks,
        canonical_char_count=len(canonical_text),
    )
    alignment_phase_seconds["normalize_prediction_seconds"] = normalize_prediction_seconds
    alignment_phase_seconds["normalize_canonical_seconds"] = normalize_canonical_seconds
    return aligned_rows, alignment, alignment_phase_seconds


def _align_prediction_blocks_global_from_normalized(
    *,
    prediction_normalized: str,
    canonical_normalized: str,
    prediction_blocks: list[dict[str, Any]],
    canonical_char_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, float]]:
    sequence_matcher_started = time.monotonic()
    matcher = SelectedSequenceMatcher(
        None,
        prediction_normalized,
        canonical_normalized,
        autojunk=False,
    )
    matching_blocks = _collect_matching_blocks(matcher)
    sequence_matcher_seconds = max(0.0, time.monotonic() - sequence_matcher_started)

    aligned_rows: list[dict[str, Any]] = []
    block_mapping_started = time.monotonic()
    for block in prediction_blocks:
        pred_start = int(block["start_char"])
        pred_end = int(block["end_char"])
        matched_chars = 0
        canonical_start: int | None = None
        canonical_end: int | None = None
        for match_pred_start, match_pred_end, match_canonical_start in matching_blocks:
            if match_pred_end <= pred_start or match_pred_start >= pred_end:
                continue
            overlap_start = max(pred_start, match_pred_start)
            overlap_end = min(pred_end, match_pred_end)
            overlap_size = overlap_end - overlap_start
            if overlap_size <= 0:
                continue
            matched_chars += overlap_size
            mapped_start = match_canonical_start + (overlap_start - match_pred_start)
            mapped_end = mapped_start + overlap_size
            if canonical_start is None or mapped_start < canonical_start:
                canonical_start = mapped_start
            if canonical_end is None or mapped_end > canonical_end:
                canonical_end = mapped_end

        aligned_rows.append(
            _aligned_row(
                block=block,
                canonical_start=canonical_start,
                canonical_end=canonical_end,
                matched_chars=matched_chars,
            )
        )
    block_mapping_seconds = max(0.0, time.monotonic() - block_mapping_started)

    alignment = _alignment_summary(
        aligned_rows=aligned_rows,
        prediction_blocks=prediction_blocks,
        canonical_char_count=canonical_char_count,
        matching_block_count=len(matching_blocks),
    )
    alignment["prediction_normalized_char_count"] = len(prediction_normalized)
    alignment["canonical_normalized_char_count"] = len(canonical_normalized)
    alignment_phase_seconds = {
        "sequence_matcher_seconds": sequence_matcher_seconds,
        "block_mapping_seconds": block_mapping_seconds,
    }
    return aligned_rows, alignment, alignment_phase_seconds


def _local_sequence_align_block(
    *,
    block_normalized: str,
    canonical_normalized: str,
    window_start: int,
    window_end: int,
) -> tuple[int, int, int, float] | None:
    if window_end <= window_start:
        return None
    window_text = canonical_normalized[window_start:window_end]
    if not window_text:
        return None

    matcher = SelectedSequenceMatcher(None, block_normalized, window_text, autojunk=False)
    matching_blocks = _collect_matching_blocks(matcher)
    if not matching_blocks:
        return None

    block_len = len(block_normalized)
    matched_chars = 0
    canonical_start: int | None = None
    canonical_end: int | None = None
    for match_block_start, match_block_end, match_window_start in matching_blocks:
        overlap_start = max(0, match_block_start)
        overlap_end = min(block_len, match_block_end)
        overlap_size = overlap_end - overlap_start
        if overlap_size <= 0:
            continue
        matched_chars += overlap_size
        mapped_start = window_start + match_window_start + (overlap_start - match_block_start)
        mapped_end = mapped_start + overlap_size
        if canonical_start is None or mapped_start < canonical_start:
            canonical_start = mapped_start
        if canonical_end is None or mapped_end > canonical_end:
            canonical_end = mapped_end

    if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
        return None
    if matched_chars <= 0:
        return None

    match_ratio = matched_chars / block_len if block_len > 0 else 0.0
    return canonical_start, canonical_end, matched_chars, match_ratio


def _align_prediction_blocks_fast(
    *,
    canonical_text: str,
    prediction_blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, float]]:
    normalize_canonical_started = time.monotonic()
    canonical_normalized = _normalize_for_alignment(canonical_text)
    normalize_canonical_seconds = max(0.0, time.monotonic() - normalize_canonical_started)
    canonical_len = len(canonical_normalized)

    aligned_rows: list[dict[str, Any]] = []
    search_cursor = 0
    fast_exact_matches = 0
    fast_local_matches = 0
    fast_local_low_confidence = 0
    fast_unresolved_nonempty_blocks = 0
    normalize_prediction_seconds = 0.0
    sequence_matcher_seconds = 0.0

    block_mapping_started = time.monotonic()
    for block in prediction_blocks:
        block_text = str(block.get("text") or "")
        normalize_prediction_started = time.monotonic()
        block_normalized = _normalize_for_alignment(block_text)
        normalize_prediction_seconds += max(
            0.0, time.monotonic() - normalize_prediction_started
        )
        block_len = len(block_normalized)
        if block_len <= 0:
            aligned_rows.append(
                _aligned_row(
                    block=block,
                    canonical_start=None,
                    canonical_end=None,
                    matched_chars=0,
                )
            )
            continue

        dynamic_window = max(
            _FAST_ALIGN_MIN_WINDOW_CHARS,
            block_len * _FAST_ALIGN_WINDOW_BLOCK_MULTIPLIER,
        )
        search_start = max(0, search_cursor - _FAST_ALIGN_LOOKBACK_CHARS)
        search_end = min(canonical_len, max(search_start + dynamic_window, search_cursor + block_len))

        canonical_start: int | None = None
        canonical_end: int | None = None
        matched_chars = 0
        local_match_ratio = 0.0

        exact_index = canonical_normalized.find(block_normalized, search_start, search_end)
        if exact_index >= 0:
            canonical_start = exact_index
            canonical_end = exact_index + block_len
            matched_chars = block_len
            fast_exact_matches += 1
        else:
            local_start = max(0, search_start - _FAST_ALIGN_LOCAL_EXPAND_CHARS)
            local_end = min(canonical_len, search_end + _FAST_ALIGN_LOCAL_EXPAND_CHARS)
            sequence_matcher_started = time.monotonic()
            local_match = _local_sequence_align_block(
                block_normalized=block_normalized,
                canonical_normalized=canonical_normalized,
                window_start=local_start,
                window_end=local_end,
            )
            sequence_matcher_seconds += max(
                0.0, time.monotonic() - sequence_matcher_started
            )
            if local_match is not None:
                local_canonical_start, local_canonical_end, local_chars, local_ratio = local_match
                if (
                    local_ratio >= _FAST_ALIGN_LOCAL_MIN_RATIO
                    and local_chars >= min(_FAST_ALIGN_LOCAL_MIN_CHARS, block_len)
                ):
                    canonical_start = local_canonical_start
                    canonical_end = local_canonical_end
                    matched_chars = local_chars
                    local_match_ratio = local_ratio
                    fast_local_matches += 1
                    if local_ratio < _AUTO_LOCAL_CONFIDENCE_MIN_RATIO:
                        fast_local_low_confidence += 1

        if canonical_start is None or canonical_end is None:
            fast_unresolved_nonempty_blocks += 1
            aligned_rows.append(
                _aligned_row(
                    block=block,
                    canonical_start=None,
                    canonical_end=None,
                    matched_chars=0,
                )
            )
            continue

        search_cursor = max(search_cursor, canonical_end)
        row = _aligned_row(
            block=block,
            canonical_start=canonical_start,
            canonical_end=canonical_end,
            matched_chars=matched_chars,
        )
        if local_match_ratio > 0.0:
            row["local_match_ratio"] = round(local_match_ratio, 6)
        aligned_rows.append(row)
    block_loop_seconds = max(0.0, time.monotonic() - block_mapping_started)
    block_mapping_seconds = max(
        0.0,
        block_loop_seconds - normalize_prediction_seconds - sequence_matcher_seconds,
    )

    alignment = _alignment_summary(
        aligned_rows=aligned_rows,
        prediction_blocks=prediction_blocks,
        canonical_char_count=len(canonical_text),
    )
    alignment["fast_exact_match_blocks"] = fast_exact_matches
    alignment["fast_local_match_blocks"] = fast_local_matches
    alignment["fast_local_low_confidence_blocks"] = fast_local_low_confidence
    alignment["fast_unresolved_nonempty_blocks"] = fast_unresolved_nonempty_blocks
    alignment["fast_window_min_chars"] = _FAST_ALIGN_MIN_WINDOW_CHARS
    alignment["fast_window_block_multiplier"] = _FAST_ALIGN_WINDOW_BLOCK_MULTIPLIER
    alignment["prediction_normalized_char_count"] = (
        _coerce_int(alignment.get("prediction_char_count")) or 0
    )
    alignment["canonical_normalized_char_count"] = len(canonical_normalized)
    alignment_phase_seconds = {
        "normalize_prediction_seconds": normalize_prediction_seconds,
        "normalize_canonical_seconds": normalize_canonical_seconds,
        "sequence_matcher_seconds": sequence_matcher_seconds,
        "block_mapping_seconds": block_mapping_seconds,
    }
    return aligned_rows, alignment, alignment_phase_seconds


def _auto_fallback_reason(alignment: dict[str, Any]) -> str | None:
    nonempty_match_ratio = float(alignment.get("nonempty_prediction_block_match_ratio") or 0.0)
    if nonempty_match_ratio < _AUTO_MIN_NONEMPTY_BLOCK_MATCH_RATIO:
        return (
            "fast_nonempty_block_match_ratio_below_threshold "
            f"({nonempty_match_ratio:.3f} < {_AUTO_MIN_NONEMPTY_BLOCK_MATCH_RATIO:.3f})"
        )

    prediction_char_coverage = float(alignment.get("prediction_char_coverage") or 0.0)
    if prediction_char_coverage < _AUTO_MIN_PREDICTION_CHAR_COVERAGE:
        return (
            "fast_prediction_char_coverage_below_threshold "
            f"({prediction_char_coverage:.3f} < {_AUTO_MIN_PREDICTION_CHAR_COVERAGE:.3f})"
        )

    low_confidence_local = _coerce_int(alignment.get("fast_local_low_confidence_blocks")) or 0
    if low_confidence_local > 0:
        return (
            "fast_local_alignment_low_confidence_blocks_present "
            f"(count={low_confidence_local})"
        )

    return None


def _requested_alignment_strategy() -> str:
    requested = str(os.getenv(_ALIGNMENT_STRATEGY_ENV, "auto") or "auto").strip().lower()
    if requested in _ALIGNMENT_STRATEGIES:
        return requested
    return "auto"


def _align_prediction_blocks_to_canonical(
    *,
    prediction_text: str,
    canonical_text: str,
    prediction_blocks: list[dict[str, Any]],
    strategy: str = "auto",
    alignment_cache_dir: Path | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, float],
    dict[str, Any],
    dict[str, Any],
]:
    normalized_strategy = str(strategy or "auto").strip().lower()
    if normalized_strategy not in _ALIGNMENT_STRATEGIES:
        normalized_strategy = "auto"
    matcher_selection = get_sequence_matcher_selection()

    normalize_prediction_started = time.monotonic()
    prediction_normalized = _normalize_for_alignment(prediction_text)
    normalize_prediction_seconds = max(
        0.0, time.monotonic() - normalize_prediction_started
    )
    normalize_canonical_started = time.monotonic()
    canonical_normalized = _normalize_for_alignment(canonical_text)
    normalize_canonical_seconds = max(0.0, time.monotonic() - normalize_canonical_started)

    aligned_rows: list[dict[str, Any]] | None = None
    alignment: dict[str, Any] | None = None
    global_phase_seconds: dict[str, float] = {
        "sequence_matcher_seconds": 0.0,
        "block_mapping_seconds": 0.0,
    }

    cache_enabled = alignment_cache_dir is not None
    cache_hit = False
    cache_load_seconds = 0.0
    cache_write_seconds = 0.0
    cache_validation_error: str | None = None
    cache_key_summary: str | None = None
    if cache_enabled:
        block_boundaries = [
            (
                int(_coerce_int(block.get("start_char")) or 0),
                int(_coerce_int(block.get("end_char")) or 0),
            )
            for block in prediction_blocks
        ]
        canonical_hash = sha256_text(canonical_normalized)
        prediction_hash = sha256_text(prediction_normalized)
        boundaries_hash = hash_block_boundaries(block_boundaries)
        cache_key_summary = (
            "v1/global/n1/"
            f"canon={canonical_hash[:12]}/"
            f"pred={prediction_hash[:12]}/"
            f"b={boundaries_hash[:12]}"
        )
        cache_key = build_cache_file_key(
            alignment_strategy="global",
            canonical_normalized_sha256=canonical_hash,
            prediction_normalized_sha256=prediction_hash,
            prediction_block_boundaries_sha256=boundaries_hash,
            normalization_version=CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
            algo_version=CANONICAL_ALIGNMENT_ALGO_VERSION,
        )
        expected_signatures = {
            "alignment_strategy": "global",
            "normalization_version": CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
            "repo_alignment_algo_version": CANONICAL_ALIGNMENT_ALGO_VERSION,
            "canonical_normalized_sha256": canonical_hash,
            "prediction_normalized_sha256": prediction_hash,
            "prediction_block_boundaries_sha256": boundaries_hash,
            "canonical_normalized_char_count": len(canonical_normalized),
            "prediction_normalized_char_count": len(prediction_normalized),
        }
        cache = CanonicalAlignmentDiskCache(Path(alignment_cache_dir))

        def _try_cache_load() -> None:
            nonlocal aligned_rows
            nonlocal alignment
            nonlocal cache_hit
            nonlocal cache_load_seconds
            nonlocal cache_validation_error
            load_started = time.monotonic()
            entry, error = cache.try_load(
                cache_key,
                expected_signatures=expected_signatures,
            )
            cache_load_seconds += max(0.0, time.monotonic() - load_started)
            if error is not None:
                cache_validation_error = error
            if entry is None:
                return
            loaded_rows, loaded_alignment, payload_error = _load_alignment_cache_payload(
                payload=entry.payload,
                expected_block_count=len(prediction_blocks),
            )
            if payload_error is not None:
                cache_validation_error = payload_error
                return
            if loaded_rows is None or loaded_alignment is None:
                cache_validation_error = "cache_payload_missing"
                return
            aligned_rows = loaded_rows
            alignment = loaded_alignment
            cache_hit = True

        _try_cache_load()
        if not cache_hit:
            with cache.lock_for_key(cache_key) as lock_acquired:
                if not cache_hit:
                    _try_cache_load()
                if cache_hit:
                    pass
                elif lock_acquired:
                    aligned_rows, alignment, global_phase_seconds = (
                        _align_prediction_blocks_global_from_normalized(
                            prediction_normalized=prediction_normalized,
                            canonical_normalized=canonical_normalized,
                            prediction_blocks=prediction_blocks,
                            canonical_char_count=len(canonical_text),
                        )
                    )
                    write_started = time.monotonic()
                    cache.write_atomic(
                        cache_key,
                        make_cache_entry(
                            alignment_strategy="global",
                            canonical_normalized_sha256=canonical_hash,
                            prediction_normalized_sha256=prediction_hash,
                            prediction_block_boundaries_sha256=boundaries_hash,
                            canonical_normalized_char_count=len(canonical_normalized),
                            prediction_normalized_char_count=len(prediction_normalized),
                            payload=_alignment_cache_payload(
                                aligned_rows=aligned_rows,
                                alignment=alignment,
                            ),
                        ),
                    )
                    cache_write_seconds = max(0.0, time.monotonic() - write_started)
    if aligned_rows is None or alignment is None:
        aligned_rows, alignment, global_phase_seconds = _align_prediction_blocks_global_from_normalized(
            prediction_normalized=prediction_normalized,
            canonical_normalized=canonical_normalized,
            prediction_blocks=prediction_blocks,
            canonical_char_count=len(canonical_text),
        )
    alignment_phase_seconds = {
        "normalize_prediction_seconds": normalize_prediction_seconds,
        "normalize_canonical_seconds": normalize_canonical_seconds,
        "sequence_matcher_seconds": max(
            0.0, float(global_phase_seconds.get("sequence_matcher_seconds") or 0.0)
        ),
        "block_mapping_seconds": max(
            0.0, float(global_phase_seconds.get("block_mapping_seconds") or 0.0)
        ),
    }
    deprecated_request = normalized_strategy in {"auto", "fast"}
    alignment.update(
        {
            "alignment_strategy": "global",
            "alignment_requested_strategy": normalized_strategy,
            "alignment_primary_strategy": "global",
            "alignment_fallback_used": deprecated_request,
            "alignment_fallback_reason": (
                _ALIGNMENT_FAST_DEPRECATION_REASON if deprecated_request else None
            ),
            "alignment_fast_path_deprecated": True,
            "alignment_fast_path_deprecation_reason": _ALIGNMENT_FAST_DEPRECATION_REASON,
            "alignment_fast_path_deprecation_message": _ALIGNMENT_FAST_DEPRECATION_MESSAGE,
        }
    )
    return aligned_rows, alignment, alignment_phase_seconds, {
        "enabled": cache_enabled,
        "hit": cache_hit,
        "key": cache_key_summary,
        "load_seconds": max(0.0, cache_load_seconds),
        "write_seconds": max(0.0, cache_write_seconds),
        "validation_error": cache_validation_error,
    }, {
        "implementation": matcher_selection.implementation,
        "version": matcher_selection.version,
        "forced_mode": matcher_selection.forced_mode,
        "requested_mode": matcher_selection.forced_mode or "fallback",
        "mode": matcher_selection.forced_mode or matcher_selection.implementation,
        "extra": dict(matcher_selection.extra_telemetry or {}),
    }


def _build_canonical_lines(canonical_text: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    cursor = 0
    for raw_line in canonical_text.splitlines(keepends=True):
        line_start = cursor
        line_end = line_start + len(raw_line)
        text_end = line_end
        while text_end > line_start and canonical_text[text_end - 1] in {"\n", "\r"}:
            text_end -= 1
        if text_end > line_start:
            lines.append(
                {
                    "line_index": len(lines),
                    "start_char": line_start,
                    "end_char": text_end,
                    "text": canonical_text[line_start:text_end],
                }
            )
        cursor = line_end
    if not lines and canonical_text:
        lines.append(
            {
                "line_index": 0,
                "start_char": 0,
                "end_char": len(canonical_text),
                "text": canonical_text,
            }
        )
    return lines


def _load_canonical_gold_spans(canonical_spans_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_jsonl(canonical_spans_path):
        start_char = _coerce_int(row.get("start_char"))
        end_char = _coerce_int(row.get("end_char"))
        label_raw = str(row.get("label") or "").strip()
        if start_char is None or end_char is None or end_char <= start_char:
            continue
        if not label_raw:
            continue
        label = normalize_freeform_label(label_raw)
        if label not in _FREEFORM_LABEL_SET:
            continue
        rows.append(
            {
                "span_id": str(row.get("span_id") or ""),
                "label": label,
                "start_char": start_char,
                "end_char": end_char,
            }
        )
    rows.sort(key=lambda row: (int(row["start_char"]), int(row["end_char"])))
    return rows


def _build_gold_line_labels(
    *,
    lines: list[dict[str, Any]],
    gold_spans: list[dict[str, Any]],
    strict_empty_to_other: bool,
) -> dict[int, set[str]]:
    provisional_labels_by_line: dict[int, set[str]] = {}
    span_cursor = 0
    span_total = len(gold_spans)

    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])

        while span_cursor < span_total and int(gold_spans[span_cursor]["end_char"]) <= line_start:
            span_cursor += 1

        labels: set[str] = set()
        scan_index = span_cursor
        while scan_index < span_total:
            span = gold_spans[scan_index]
            label = str(span["label"])
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            if span_end > line_start:
                labels.add(label)
            scan_index += 1

        if not labels and strict_empty_to_other:
            labels.add("OTHER")
        if labels:
            provisional_labels_by_line[line_index] = labels

    return provisional_labels_by_line


def build_canonical_gold_line_labels(
    *,
    canonical_text_path: Path,
    canonical_spans_path: Path,
    strict_empty_to_other: bool = True,
) -> tuple[list[dict[str, Any]], dict[int, set[str]]]:
    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    lines = _build_canonical_lines(canonical_text)
    gold_spans = _load_canonical_gold_spans(canonical_spans_path)
    labels = _build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=strict_empty_to_other,
    )
    return lines, labels


def _find_title_support_context(
    *,
    line_index: int,
    labels_by_line: dict[int, set[str]],
) -> dict[str, Any]:
    for offset in range(1, _TITLE_STRUCTURE_LOOKAHEAD_LINES + 1):
        neighbor_labels = set(labels_by_line.get(line_index + offset) or set())
        non_other_labels = neighbor_labels - {"OTHER"}
        if not non_other_labels:
            continue
        if non_other_labels & _TITLE_STRUCTURE_SUPPORT_LABELS:
            return {
                "status": "supported",
                "support_line_index": line_index + offset,
                "support_labels": sorted(non_other_labels & _TITLE_STRUCTURE_SUPPORT_LABELS),
            }
        if "RECIPE_TITLE" in non_other_labels:
            return {
                "status": "later_title_before_structure",
                "later_title_line_index": line_index + offset,
                "later_title_labels": sorted(non_other_labels),
            }
    return {"status": "missing"}


def _build_gold_projection_warnings(
    *,
    lines: list[dict[str, Any]],
    gold_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    labels_by_line = _build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=False,
    )
    warnings: list[dict[str, Any]] = []
    span_cursor = 0
    span_total = len(gold_spans)

    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])
        line_text = str(line.get("text") or "")
        line_labels = set(labels_by_line.get(line_index) or set())

        while span_cursor < span_total and int(gold_spans[span_cursor]["end_char"]) <= line_start:
            span_cursor += 1

        overlapping_spans: list[dict[str, Any]] = []
        scan_index = span_cursor
        while scan_index < span_total:
            span = gold_spans[scan_index]
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            overlap = _overlap_len(line_start, line_end, span_start, span_end)
            if overlap > 0:
                overlapping_spans.append(
                    {
                        "label": str(span["label"]),
                        "start_char": span_start,
                        "end_char": span_end,
                        "overlap_chars": overlap,
                    }
                )
            scan_index += 1

        stripped = line_text.strip()
        content_len = len(stripped) if stripped else len(line_text)
        if content_len <= 0:
            continue

        for label in ("RECIPE_TITLE", "RECIPE_VARIANT"):
            if label not in line_labels or "OTHER" not in line_labels:
                continue
            overlap_chars = sum(
                int(span["overlap_chars"])
                for span in overlapping_spans
                if str(span["label"]) == label
            )
            if overlap_chars <= 0:
                continue
            warnings.append(
                {
                    "warning": "gold_inline_label_subspan_inside_other_line",
                    "line_index": line_index,
                    "label": label,
                    "line_text_excerpt": _excerpt(line_text),
                    "label_overlap_chars": overlap_chars,
                    "line_content_chars": content_len,
                    "label_overlap_ratio": round(overlap_chars / content_len, 6),
                }
            )

        if "RECIPE_TITLE" not in line_labels:
            continue
        support = _find_title_support_context(
            line_index=line_index,
            labels_by_line=labels_by_line,
        )
        support_status = str(support.get("status") or "missing")
        if support_status == "supported":
            continue
        warning_row = {
            "line_index": line_index,
            "label": "RECIPE_TITLE",
            "line_text_excerpt": _excerpt(line_text),
            "lookahead_lines": _TITLE_STRUCTURE_LOOKAHEAD_LINES,
        }
        if support_status == "later_title_before_structure":
            warning_row["warning"] = "gold_recipe_title_precedes_later_recipe_title_before_structure"
            warning_row["later_title_line_index"] = int(
                support.get("later_title_line_index") or -1
            )
            warning_row["later_title_labels"] = list(support.get("later_title_labels") or [])
        else:
            warning_row["warning"] = "gold_recipe_title_without_nearby_recipe_structure"
        warnings.append(warning_row)

    return warnings


def _build_pred_line_labels(
    *,
    lines: list[dict[str, Any]],
    aligned_prediction_blocks: list[dict[str, Any]],
) -> dict[int, str]:
    matched_blocks: list[dict[str, Any]] = []
    for block in aligned_prediction_blocks:
        if not bool(block.get("matched")):
            continue
        canonical_start = _coerce_int(block.get("canonical_start_char"))
        canonical_end = _coerce_int(block.get("canonical_end_char"))
        if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
            continue
        matched_blocks.append(
            {
                "label": str(block.get("label") or "OTHER"),
                "start_char": canonical_start,
                "end_char": canonical_end,
            }
        )
    matched_blocks.sort(key=lambda row: (int(row["start_char"]), int(row["end_char"])))

    pred_line_labels: dict[int, str] = {}
    block_cursor = 0
    block_total = len(matched_blocks)

    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])

        while block_cursor < block_total and int(matched_blocks[block_cursor]["end_char"]) <= line_start:
            block_cursor += 1

        best_label = "OTHER"
        best_overlap = 0
        scan_index = block_cursor
        while scan_index < block_total:
            block = matched_blocks[scan_index]
            block_start = int(block["start_char"])
            if block_start >= line_end:
                break
            block_end = int(block["end_char"])
            overlap = _overlap_len(line_start, line_end, block_start, block_end)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = str(block["label"])
            elif overlap == best_overlap and best_label == "OTHER" and str(block["label"]) != "OTHER":
                best_label = str(block["label"])
            scan_index += 1

        pred_line_labels[line_index] = best_label

    return {
        index: label if label in _FREEFORM_LABEL_SET else "OTHER"
        for index, label in sorted(pred_line_labels.items())
    }


def _collect_unresolved_line_indices(
    *,
    lines: list[dict[str, Any]],
    aligned_prediction_blocks: list[dict[str, Any]],
    unresolved_block_indices: set[int],
) -> list[int]:
    if not unresolved_block_indices:
        return []

    unresolved_intervals: list[tuple[int, int]] = []
    for block in aligned_prediction_blocks:
        block_index = _coerce_int(block.get("block_index"))
        if block_index is None or block_index not in unresolved_block_indices:
            continue
        if not bool(block.get("matched")):
            continue
        canonical_start = _coerce_int(block.get("canonical_start_char"))
        canonical_end = _coerce_int(block.get("canonical_end_char"))
        if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
            continue
        unresolved_intervals.append((canonical_start, canonical_end))

    if not unresolved_intervals:
        return []

    unresolved_line_indices: list[int] = []
    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])
        if any(
            _overlap_len(line_start, line_end, start_char, end_char) > 0
            for start_char, end_char in unresolved_intervals
        ):
            unresolved_line_indices.append(line_index)
    return unresolved_line_indices


def _pick_primary_label(
    labels: set[str],
    *,
    preferred_label: str | None = None,
) -> str:
    if preferred_label and preferred_label in labels:
        return preferred_label
    for label in FREEFORM_LABELS:
        if label in labels:
            return label
    return "OTHER"


def _build_alignment_gap_rows(
    *,
    lines: list[dict[str, Any]],
    aligned_prediction_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    intervals: list[tuple[int, int]] = []
    for block in aligned_prediction_blocks:
        if not bool(block.get("matched")):
            continue
        canonical_start = _coerce_int(block.get("canonical_start_char"))
        canonical_end = _coerce_int(block.get("canonical_end_char"))
        if canonical_start is None or canonical_end is None or canonical_end <= canonical_start:
            continue
        intervals.append((canonical_start, canonical_end))
    intervals.sort(key=lambda row: (row[0], row[1]))

    gaps: list[dict[str, Any]] = []
    interval_cursor = 0
    interval_total = len(intervals)

    for line in lines:
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])

        while interval_cursor < interval_total and intervals[interval_cursor][1] <= line_start:
            interval_cursor += 1

        overlaps = False
        scan_index = interval_cursor
        while scan_index < interval_total:
            interval_start, interval_end = intervals[scan_index]
            if interval_start >= line_end:
                break
            if _overlap_len(line_start, line_end, interval_start, interval_end) > 0:
                overlaps = True
                break
            scan_index += 1

        if overlaps:
            continue

        gaps.append(
            {
                "line_index": int(line["line_index"]),
                "start_char": line_start,
                "end_char": line_end,
                "line_text_excerpt": _excerpt(str(line.get("text") or "")),
            }
        )

    return gaps


def _rows_from_line_mismatches(
    *,
    wrong_label_lines: list[dict[str, Any]],
    lines_by_index: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wrong_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    for mismatch in wrong_label_lines:
        line_index = _coerce_int(mismatch.get("block_index"))
        if line_index is None:
            continue
        line_payload = lines_by_index.get(line_index, {})
        row = {
            "line_index": line_index,
            "gold_label": str(mismatch.get("gold_label") or ""),
            "gold_labels": list(mismatch.get("gold_labels") or []),
            "pred_label": str(mismatch.get("pred_label") or ""),
            "line_text_excerpt": _excerpt(str(line_payload.get("text") or "")),
        }
        wrong_rows.append(row)
        if row["gold_label"] != "OTHER":
            missed_rows.append(dict(row))
    return missed_rows, wrong_rows


def format_canonical_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts") or {}
    authority_coverage = report.get("authority_coverage") or {}
    alignment = report.get("alignment") or {}
    segmentation = report.get("segmentation") or {}
    segmentation_boundaries = (
        segmentation.get("boundaries") if isinstance(segmentation, dict) else {}
    )
    segmentation_overall_micro = (
        segmentation_boundaries.get("overall_micro")
        if isinstance(segmentation_boundaries, dict)
        else {}
    )
    lines = [
        "# Canonical Text Evaluation",
        "",
        f"- Overall line accuracy: {float(report.get('overall_line_accuracy') or 0.0):.3f}",
        (
            "- Macro F1 (excluding OTHER): "
            f"{float(report.get('macro_f1_excluding_other') or 0.0):.3f}"
        ),
        "",
        "## Alignment Coverage",
        "",
        (
            "- Strategy: "
            f"{str(alignment.get('alignment_strategy') or 'unknown')}"
        ),
        (
            "- Fast alignment: "
            + (
                "disabled (accuracy risk; global alignment enforced)"
                if bool(alignment.get("alignment_fast_path_deprecated"))
                else "enabled"
            )
        ),
        (
            "- Canonical char coverage: "
            f"{float(alignment.get('canonical_char_coverage') or 0.0):.3f} "
            f"({int(alignment.get('canonical_chars_covered') or 0)}/"
            f"{int(alignment.get('canonical_char_count') or 0)})"
        ),
        (
            "- Prediction blocks matched: "
            f"{int(alignment.get('prediction_blocks_matched') or 0)}/"
            f"{int(alignment.get('prediction_block_count') or 0)}"
        ),
        "",
        "## Structural Segmentation",
        "",
        (
            "- Label projection: "
            f"{str(segmentation.get('label_projection') or _SEGMENTATION_LABEL_PROJECTION_CORE)}"
        ),
        (
            "- Boundary tolerance (lines): "
            f"{int(segmentation.get('boundary_tolerance_blocks') or 0)}"
        ),
        (
            "- Overall micro boundary F1: "
            f"{float(segmentation_overall_micro.get('f1') or 0.0):.3f}"
        ),
        (
            "- Boundary misses / false positives: "
            f"{int(segmentation_overall_micro.get('fn') or 0)}/"
            f"{int(segmentation_overall_micro.get('fp') or 0)}"
        ),
        "",
        "## Counts",
        "",
        f"- Scored lines: {int(counts.get('gold_total') or 0)}",
        (
            "- Prediction coverage: "
            f"{float(authority_coverage.get('prediction_coverage') or 0.0):.3f} "
            f"({int(authority_coverage.get('scored_prediction_lines') or 0)}/"
            f"{int(authority_coverage.get('total_prediction_lines') or 0)})"
        ),
        (
            "- Unresolved candidate lines: "
            f"{int(authority_coverage.get('unresolved_candidate_lines') or 0)}"
        ),
        f"- Correct: {int(counts.get('gold_matched') or 0)}",
        f"- Mismatched: {int(counts.get('gold_missed') or 0)}",
        "",
    ]
    return "\n".join(lines)


def evaluate_canonical_text(
    *,
    gold_export_root: Path,
    stage_predictions_json: Path,
    extracted_blocks_json: Path,
    out_dir: Path,
    strict_empty_gold_to_other: bool = True,
    alignment_cache_dir: Path | None = None,
    canonical_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    evaluation_started = time.monotonic()
    resource_start = _capture_eval_resource_snapshot()
    subphase_seconds: dict[str, float] = {}

    out_dir.mkdir(parents=True, exist_ok=True)
    load_gold_started = time.monotonic()
    resolved_canonical_paths = canonical_paths
    if resolved_canonical_paths is None:
        resolved_canonical_paths = ensure_canonical_gold_artifacts(
            export_root=gold_export_root
        )
    canonical_text_path = Path(resolved_canonical_paths["canonical_text_path"])
    canonical_spans_path = Path(resolved_canonical_paths["canonical_span_labels_path"])

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    canonical_lines = _build_canonical_lines(canonical_text)
    lines_by_index = {int(line["line_index"]): line for line in canonical_lines}
    canonical_line_texts = {
        int(line["line_index"]): str(line.get("text") or "")
        for line in canonical_lines
    }
    gold_spans = _load_canonical_gold_spans(canonical_spans_path)
    subphase_seconds["load_gold_seconds"] = max(0.0, time.monotonic() - load_gold_started)

    load_prediction_started = time.monotonic()
    prediction_manifest = load_stage_block_prediction_manifest(
        stage_predictions_json,
        resolve_howto_sections=False,
    )
    prediction_blocks = _load_prediction_blocks(
        extracted_blocks_json=extracted_blocks_json,
        stage_labels=prediction_manifest.labels,
    )
    prediction_text, prediction_block_rows = _join_blocks_with_offsets(prediction_blocks)
    subphase_seconds["load_prediction_seconds"] = max(
        0.0,
        time.monotonic() - load_prediction_started,
    )

    align_started = time.monotonic()
    requested_alignment_strategy = _requested_alignment_strategy()
    (
        aligned_blocks,
        alignment,
        alignment_phase_seconds,
        alignment_cache_telemetry,
        matcher_telemetry,
    ) = _align_prediction_blocks_to_canonical(
        prediction_text=prediction_text,
        canonical_text=canonical_text,
        prediction_blocks=prediction_block_rows,
        strategy=requested_alignment_strategy,
        alignment_cache_dir=alignment_cache_dir,
    )
    subphase_seconds["alignment_seconds"] = max(0.0, time.monotonic() - align_started)
    for key, value in alignment_phase_seconds.items():
        subphase_seconds[f"alignment_{key}"] = max(0.0, float(value))

    projection_started = time.monotonic()
    gold_line_labels = _build_gold_line_labels(
        lines=canonical_lines,
        gold_spans=gold_spans,
        strict_empty_to_other=strict_empty_gold_to_other,
    )
    gold_projection_warnings = _build_gold_projection_warnings(
        lines=canonical_lines,
        gold_spans=gold_spans,
    )
    pred_line_labels = _build_pred_line_labels(
        lines=canonical_lines,
        aligned_prediction_blocks=aligned_blocks,
    )
    unresolved_line_indices = _collect_unresolved_line_indices(
        lines=canonical_lines,
        aligned_prediction_blocks=aligned_blocks,
        unresolved_block_indices=set(prediction_manifest.unresolved_block_indices),
    )
    subphase_seconds["line_projection_seconds"] = max(
        0.0,
        time.monotonic() - projection_started,
    )

    metrics_started = time.monotonic()
    unresolved_line_index_set = set(unresolved_line_indices)
    scored_indices = sorted(
        (set(gold_line_labels) | set(pred_line_labels)) - unresolved_line_index_set
    )
    gold_for_metrics = {index: gold_line_labels.get(index, {"OTHER"}) for index in scored_indices}
    pred_for_metrics = {index: pred_line_labels.get(index, "OTHER") for index in scored_indices}
    scored_gold_line_labels = {
        index: labels
        for index, labels in gold_line_labels.items()
        if index not in unresolved_line_index_set
    }
    scored_pred_line_labels = {
        index: label
        for index, label in pred_line_labels.items()
        if index not in unresolved_line_index_set
    }

    report = compute_block_metrics(gold_for_metrics, pred_for_metrics)
    subphase_seconds["metrics_seconds"] = max(0.0, time.monotonic() - metrics_started)
    report["eval_type"] = "canonical_text_classification"
    report["eval_mode"] = "canonical_text"
    report["unit"] = "canonical_line"
    report["overall_line_accuracy"] = float(report.get("overall_block_accuracy") or 0.0)
    report["strict_accuracy"] = float(report.get("overall_line_accuracy") or 0.0)
    report["alignment"] = alignment
    report["canonical"] = {
        "line_count": len(canonical_lines),
        "gold_span_count": len(gold_spans),
        "canonical_text_path": str(canonical_text_path),
        "canonical_span_labels_path": str(canonical_spans_path),
        "gold_projection_warning_count": len(gold_projection_warnings),
        "gold_projection_warning_counts": {
            warning: sum(
                1
                for row in gold_projection_warnings
                if str(row.get("warning") or "") == warning
            )
            for warning in sorted(
                {
                    str(row.get("warning") or "")
                    for row in gold_projection_warnings
                    if str(row.get("warning") or "")
                }
            )
        },
    }
    total_prediction_lines = len(set(gold_line_labels) | set(pred_line_labels))
    report["authority_coverage"] = {
        "scoring_mode": "authoritative_predictions_only",
        "total_prediction_lines": total_prediction_lines,
        "scored_prediction_lines": len(scored_indices),
        "unresolved_candidate_lines": len(unresolved_line_indices),
        "prediction_coverage": (
            (len(scored_indices) / total_prediction_lines)
            if total_prediction_lines > 0
            else 1.0
        ),
        "unresolved_candidate_line_indices": unresolved_line_indices,
        "unresolved_candidate_block_indices": prediction_manifest.unresolved_block_indices,
        "unresolved_candidate_route_by_index": dict(
            prediction_manifest.unresolved_block_category_by_index
        ),
    }

    stage_payload = json.loads(stage_predictions_json.read_text(encoding="utf-8"))
    report["source"] = {
        "workbook_slug": str(stage_payload.get("workbook_slug") or ""),
        "source_file": str(stage_payload.get("source_file") or ""),
        "source_hash": stage_payload.get("source_hash"),
    }
    segmentation_started = time.monotonic()
    (
        projected_gold_labels,
        projected_pred_labels,
        projected_gold_by_index,
        projected_pred_by_index,
    ) = _build_projected_structural_sequences(
        gold=scored_gold_line_labels,
        pred=scored_pred_line_labels,
        label_projection=_SEGMENTATION_LABEL_PROJECTION_CORE,
    )
    segmentation = compute_segmentation_boundaries(
        labels_gold=projected_gold_labels,
        labels_pred=projected_pred_labels,
        tolerance_blocks=_CANONICAL_SEGMENTATION_BOUNDARY_TOLERANCE_BLOCKS,
    )
    report["segmentation"] = {
        "label_projection": _SEGMENTATION_LABEL_PROJECTION_CORE,
        "boundary_tolerance_blocks": _CANONICAL_SEGMENTATION_BOUNDARY_TOLERANCE_BLOCKS,
        "metrics_requested": list(_CANONICAL_SEGMENTATION_METRICS_REQUESTED),
        "boundaries": segmentation.get("boundaries", {}),
        "error_taxonomy": _compute_error_taxonomy(
            gold_projected=projected_gold_by_index,
            pred_projected=projected_pred_by_index,
            segmentation_boundaries=segmentation,
        ),
    }
    subphase_seconds["segmentation_seconds"] = max(
        0.0,
        time.monotonic() - segmentation_started,
    )
    boundary_started = time.monotonic()
    report["boundary"] = _compute_canonical_boundary_counts(
        canonical_lines=canonical_lines,
        gold_spans=gold_spans,
        aligned_prediction_blocks=aligned_blocks,
        overlap_threshold=_CANONICAL_BOUNDARY_OVERLAP_THRESHOLD,
    )
    report["boundary_overlap_threshold"] = _CANONICAL_BOUNDARY_OVERLAP_THRESHOLD
    subphase_seconds["boundary_metrics_seconds"] = max(
        0.0,
        time.monotonic() - boundary_started,
    )

    diagnostics_started = time.monotonic()
    wrong_line_metrics = report.get("wrong_label_blocks")
    if not isinstance(wrong_line_metrics, list):
        wrong_line_metrics = []
    missed_rows, wrong_rows = _rows_from_line_mismatches(
        wrong_label_lines=[row for row in wrong_line_metrics if isinstance(row, dict)],
        lines_by_index=lines_by_index,
    )
    unmatched_blocks = [row for row in aligned_blocks if not bool(row.get("matched"))]
    alignment_gaps = _build_alignment_gap_rows(
        lines=canonical_lines,
        aligned_prediction_blocks=aligned_blocks,
    )
    missed_boundary_rows, false_positive_boundary_rows = _build_boundary_mismatch_rows(
        segmentation_boundaries=segmentation,
        block_texts=canonical_line_texts,
        workbook_slug=str(stage_payload.get("workbook_slug") or ""),
        source_file=str(stage_payload.get("source_file") or ""),
    )
    subphase_seconds["diagnostics_build_seconds"] = max(
        0.0,
        time.monotonic() - diagnostics_started,
    )

    artifact_write_started = time.monotonic()
    missed_lines_path = out_dir / "missed_gold_lines.jsonl"
    wrong_lines_path = out_dir / "wrong_label_lines.jsonl"
    aligned_blocks_path = out_dir / "aligned_prediction_blocks.jsonl"
    unmatched_blocks_path = out_dir / "unmatched_pred_blocks.jsonl"
    alignment_gaps_path = out_dir / "alignment_gaps.jsonl"
    missed_boundaries_path = out_dir / "missed_gold_boundaries.jsonl"
    false_positive_boundaries_path = out_dir / "false_positive_boundaries.jsonl"
    gold_projection_warnings_path = out_dir / "gold_projection_warnings.jsonl"
    _write_jsonl(missed_lines_path, missed_rows)
    _write_jsonl(wrong_lines_path, wrong_rows)
    _write_jsonl(aligned_blocks_path, aligned_blocks)
    _write_jsonl(unmatched_blocks_path, unmatched_blocks)
    _write_jsonl(alignment_gaps_path, alignment_gaps)
    _write_jsonl(missed_boundaries_path, missed_boundary_rows)
    _write_jsonl(false_positive_boundaries_path, false_positive_boundary_rows)
    _write_jsonl(gold_projection_warnings_path, gold_projection_warnings)

    _write_jsonl(out_dir / "missed_gold_blocks.jsonl", missed_rows)
    _write_jsonl(out_dir / "wrong_label_blocks.jsonl", wrong_rows)

    report["artifacts"] = {
        "eval_report_json": str(out_dir / "eval_report.json"),
        "eval_report_md": str(out_dir / "eval_report.md"),
        "missed_gold_lines_jsonl": str(missed_lines_path),
        "wrong_label_lines_jsonl": str(wrong_lines_path),
        "aligned_prediction_blocks_jsonl": str(aligned_blocks_path),
        "unmatched_pred_blocks_jsonl": str(unmatched_blocks_path),
        "alignment_gaps_jsonl": str(alignment_gaps_path),
        "missed_gold_blocks_jsonl": str(out_dir / "missed_gold_blocks.jsonl"),
        "wrong_label_blocks_jsonl": str(out_dir / "wrong_label_blocks.jsonl"),
        "missed_gold_boundaries_jsonl": str(missed_boundaries_path),
        "false_positive_boundaries_jsonl": str(false_positive_boundaries_path),
        "gold_projection_warnings_jsonl": str(gold_projection_warnings_path),
    }

    subphase_seconds["artifact_write_seconds"] = max(
        0.0,
        time.monotonic() - artifact_write_started,
    )
    overall_boundary_metrics = (
        report.get("segmentation", {}).get("boundaries", {}).get("overall_micro", {})
    )
    if not isinstance(overall_boundary_metrics, dict):
        overall_boundary_metrics = {}

    evaluation_total_seconds = max(0.0, time.monotonic() - evaluation_started)
    resource_end = _capture_eval_resource_snapshot()
    report["evaluation_telemetry"] = {
        "total_seconds": evaluation_total_seconds,
        "alignment_sequence_matcher_impl": matcher_telemetry.get("implementation"),
        "alignment_sequence_matcher_version": matcher_telemetry.get("version"),
        "alignment_sequence_matcher_mode": matcher_telemetry.get("mode"),
        "alignment_sequence_matcher_requested_mode": matcher_telemetry.get(
            "requested_mode"
        ),
        "alignment_sequence_matcher_forced_mode": matcher_telemetry.get("forced_mode"),
        "alignment_cache_enabled": bool(alignment_cache_telemetry.get("enabled")),
        "alignment_cache_hit": bool(alignment_cache_telemetry.get("hit")),
        "alignment_cache_key": alignment_cache_telemetry.get("key"),
        "alignment_cache_load_seconds": max(
            0.0,
            float(alignment_cache_telemetry.get("load_seconds") or 0.0),
        ),
        "alignment_cache_write_seconds": max(
            0.0,
            float(alignment_cache_telemetry.get("write_seconds") or 0.0),
        ),
        "alignment_cache_validation_error": alignment_cache_telemetry.get(
            "validation_error"
        ),
        "subphases": {key: max(0.0, float(value)) for key, value in subphase_seconds.items()},
        "resources": _diff_eval_resource_snapshots(resource_start, resource_end),
        "work_units": {
            "canonical_line_count": float(len(canonical_lines)),
            "gold_span_count": float(len(gold_spans)),
            "prediction_block_count": float(len(prediction_blocks)),
            "aligned_block_count": float(len(aligned_blocks)),
            "prediction_text_char_count": float(len(prediction_text)),
            "canonical_text_char_count": float(len(canonical_text)),
            "prediction_normalized_char_count": float(
                _coerce_int(alignment.get("prediction_normalized_char_count")) or 0
            ),
            "canonical_normalized_char_count": float(
                _coerce_int(alignment.get("canonical_normalized_char_count")) or 0
            ),
            "canonical_chars_covered": float(
                _coerce_int(alignment.get("canonical_chars_covered")) or 0
            ),
            "alignment_nonempty_prediction_block_count": float(
                _coerce_int(alignment.get("nonempty_prediction_block_count")) or 0
            ),
            "alignment_nonempty_prediction_blocks_matched": float(
                _coerce_int(alignment.get("nonempty_prediction_blocks_matched")) or 0
            ),
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
    extra_matcher_telemetry = matcher_telemetry.get("extra")
    if isinstance(extra_matcher_telemetry, dict):
        for key, value in extra_matcher_telemetry.items():
            report["evaluation_telemetry"][str(key)] = value

    report_json_path = out_dir / "eval_report.json"
    report_md_path = out_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path.write_text(
        format_canonical_eval_report_md(report),
        encoding="utf-8",
    )

    return {
        "report": report,
        "missed_gold_blocks": missed_rows,
        "wrong_label_blocks": wrong_rows,
        "missed_gold_boundaries": missed_boundary_rows,
        "false_positive_boundaries": false_positive_boundary_rows,
    }
