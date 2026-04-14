from __future__ import annotations

from typing import Any

from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_LABELS,
    normalize_freeform_label,
)

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_TITLE_STRUCTURE_SUPPORT_LABELS = {
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
}
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
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            if span_end > line_start:
                label = normalize_freeform_label(str(span["label"]))
                if label in _FREEFORM_LABEL_SET:
                    labels.add(label)
            scan_index += 1

        if not labels and strict_empty_to_other:
            labels.add("OTHER")
        if labels:
            provisional_labels_by_line[line_index] = labels

    return provisional_labels_by_line


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


def _overlap_len(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _excerpt(text: str, max_len: int = 120) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_len:
        return value
    return value[: max(0, max_len - 3)].rstrip() + "..."


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
