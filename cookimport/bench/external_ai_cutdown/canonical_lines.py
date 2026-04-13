from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .io import _coerce_int, _excerpt, _iter_jsonl

_TITLE_LIKE_LABELS = {"RECIPE_TITLE"}
_TITLE_STRUCTURE_SUPPORT_LABELS = {
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
}
_TITLE_LINE_COVERAGE_MIN = 0.8
_TITLE_STRUCTURE_LOOKAHEAD_LINES = 8


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


def _load_gold_spans(canonical_spans_path: Path) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for row in _iter_jsonl(canonical_spans_path):
        start_char = _coerce_int(row.get("start_char"))
        end_char = _coerce_int(row.get("end_char"))
        label = str(row.get("label") or "").strip()
        if start_char is None or end_char is None or end_char <= start_char:
            continue
        if not label:
            continue
        spans.append(
            {
                "label": label,
                "start_char": start_char,
                "end_char": end_char,
            }
        )
    spans.sort(key=lambda span: (int(span["start_char"]), int(span["end_char"])))
    return spans


def _overlap_len(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _line_gold_labels(
    *,
    lines: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[int, list[str]]:
    provisional_labels_by_line: dict[int, list[str]] = {}
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
                if (
                    label in _TITLE_LIKE_LABELS
                    and not _should_project_title_label_to_line(
                        line=line,
                        span_start=span_start,
                        span_end=span_end,
                    )
                ):
                    scan_index += 1
                    continue
                overlap_by_label[label] += overlap
            scan_index += 1

        if not overlap_by_label:
            provisional_labels_by_line[line_index] = []
            continue

        ordered = sorted(
            overlap_by_label.items(),
            key=lambda item: (-item[1], item[0]),
        )
        provisional_labels_by_line[line_index] = [label for label, _ in ordered]

    labels_by_line: dict[int, list[str]] = {}
    for line in lines:
        line_index = int(line["line_index"])
        ordered_labels = list(provisional_labels_by_line.get(line_index) or [])
        if (
            set(ordered_labels) & _TITLE_LIKE_LABELS
            and not _line_has_title_support(
                line_index=line_index,
                current_labels=set(ordered_labels),
                labels_by_line=provisional_labels_by_line,
            )
        ):
            ordered_labels = [label for label in ordered_labels if label not in _TITLE_LIKE_LABELS]
        labels_by_line[line_index] = ordered_labels or ["OTHER"]

    return labels_by_line


def _should_project_title_label_to_line(
    *,
    line: dict[str, Any],
    span_start: int,
    span_end: int,
) -> bool:
    line_start = int(line["start_char"])
    line_end = int(line["end_char"])
    line_text = str(line.get("text") or "")
    if not line_text or line_end <= line_start:
        return False
    overlap = _overlap_len(line_start, line_end, span_start, span_end)
    if overlap <= 0:
        return False
    stripped = line_text.strip()
    content_len = len(stripped) if stripped else len(line_text)
    if content_len <= 0:
        return False
    return (overlap / content_len) >= _TITLE_LINE_COVERAGE_MIN


def _line_has_title_support(
    *,
    line_index: int,
    current_labels: set[str],
    labels_by_line: dict[int, list[str]],
) -> bool:
    current_has_other = "OTHER" in current_labels
    for offset in range(1, _TITLE_STRUCTURE_LOOKAHEAD_LINES + 1):
        neighbor_labels = set(labels_by_line.get(line_index + offset) or [])
        non_other_labels = neighbor_labels - {"OTHER"}
        if not non_other_labels:
            continue
        if non_other_labels & _TITLE_STRUCTURE_SUPPORT_LABELS:
            return True
        if current_has_other and non_other_labels & _TITLE_LIKE_LABELS:
            return False
    return False


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

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    lines = _build_canonical_lines(canonical_text)
    spans = _load_gold_spans(canonical_span_path)
    labels_by_line = _line_gold_labels(lines=lines, spans=spans)

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
