from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from cookimport.bench.eval_canonical_text import (
    _build_canonical_lines as _build_canonical_lines_impl,
    _load_canonical_gold_spans as _load_gold_spans_impl,
    _overlap_len as _overlap_len_impl,
    build_canonical_gold_line_labels,
)

from .io import _coerce_int, _excerpt


def _build_canonical_lines(canonical_text: str) -> list[dict[str, Any]]:
    return _build_canonical_lines_impl(canonical_text)


def _load_gold_spans(canonical_spans_path: Path) -> list[dict[str, Any]]:
    return _load_gold_spans_impl(canonical_spans_path)


def _overlap_len(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return _overlap_len_impl(a_start, a_end, b_start, b_end)


def _line_gold_labels(
    *,
    lines: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[int, list[str]]:
    labels_by_line: dict[int, list[str]] = {}
    span_cursor = 0
    span_total = len(spans)

    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])

        while span_cursor < span_total and int(spans[span_cursor]["end_char"]) <= line_start:
            span_cursor += 1

        overlap_by_label: dict[str, int] = defaultdict(int)
        scan_index = span_cursor
        while scan_index < span_total:
            span = spans[scan_index]
            label = str(span["label"])
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            overlap = _overlap_len(line_start, line_end, span_start, span_end)
            if overlap > 0:
                overlap_by_label[label] += overlap
            scan_index += 1

        if not overlap_by_label:
            labels_by_line[line_index] = ["OTHER"]
            continue

        ordered = sorted(
            overlap_by_label.items(),
            key=lambda item: (-item[1], item[0]),
        )
        labels_by_line[line_index] = [label for label, _ in ordered]

    return labels_by_line


def _build_correct_label_sample(
    *,
    eval_report: dict[str, Any],
    wrong_label_rows: list[dict[str, Any]],
    sample_limit: int,
    excerpt_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical = eval_report.get("canonical")
    if not isinstance(canonical, dict):
        return [], {"status": "skipped", "reason": "missing_canonical_block"}

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_span_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_span_path_raw, str):
        return [], {"status": "skipped", "reason": "missing_canonical_paths"}

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_span_path = Path(canonical_span_path_raw)
    if not canonical_text_path.is_file() or not canonical_span_path.is_file():
        return [], {
            "status": "skipped",
            "reason": "canonical_paths_not_found",
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_span_path),
        }

    lines, label_sets_by_line = build_canonical_gold_line_labels(
        canonical_text_path=canonical_text_path,
        canonical_spans_path=canonical_span_path,
        strict_empty_to_other=True,
    )
    labels_by_line = {
        int(line_index): sorted(labels)
        for line_index, labels in label_sets_by_line.items()
    }

    wrong_line_indices = {
        idx
        for row in wrong_label_rows
        if (idx := _coerce_int(row.get("line_index"))) is not None
    }

    primary_pool: list[dict[str, Any]] = []
    fallback_pool: list[dict[str, Any]] = []

    for line in lines:
        line_index = int(line["line_index"])
        if line_index in wrong_line_indices:
            continue
        gold_labels = labels_by_line.get(line_index, ["OTHER"])
        gold_label = gold_labels[0] if gold_labels else "OTHER"
        row = {
            "line_index": line_index,
            "line_text_excerpt": _excerpt(str(line.get("text") or ""), max_len=excerpt_limit),
            "gold_label": gold_label,
            "gold_labels": gold_labels,
            "pred_label": gold_label,
            "correctness_basis": "line_index_absent_from_wrong_label_lines",
        }
        if gold_label == "OTHER":
            fallback_pool.append(row)
        else:
            primary_pool.append(row)

    combined = primary_pool + fallback_pool
    sample = combined[:sample_limit]
    metadata = {
        "status": "ok",
        "candidate_rows_total": len(combined),
        "sample_rows": len(sample),
        "non_other_candidates": len(primary_pool),
        "other_candidates": len(fallback_pool),
        "canonical_text_path": str(canonical_text_path),
        "canonical_span_labels_path": str(canonical_span_path),
    }
    return sample, metadata
