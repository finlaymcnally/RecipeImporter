from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_LABELS,
    normalize_freeform_label,
)

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)


def load_row_gold_line_labels(
    row_gold_path: Path,
    *,
    strict_empty_to_other: bool = True,
) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    lines: list[dict[str, Any]] = []
    labels_by_line: dict[int, list[str]] = {}

    for row in _read_jsonl(row_gold_path):
        line_index = _coerce_int(row.get("row_index"))
        if line_index is None:
            continue
        labels = _normalize_labels(
            row.get("labels"),
            strict_empty_to_other=strict_empty_to_other,
        )
        lines.append(
            {
                "line_index": int(line_index),
                "text": str(row.get("text") or ""),
                "row_id": str(row.get("row_id") or ""),
                "block_index": _coerce_int(row.get("block_index")),
            }
        )
        labels_by_line[int(line_index)] = labels

    lines.sort(key=lambda row: int(row["line_index"]))
    return lines, labels_by_line


def resolve_row_gold_path_from_eval_report(report: dict[str, Any]) -> Path | None:
    row_gold_path_raw = report.get("row_gold_labels_path")
    if not isinstance(row_gold_path_raw, str):
        output = report.get("output")
        row_gold_path_raw = (
            output.get("row_gold_labels_path")
            if isinstance(output, dict)
            else None
        )
    if not isinstance(row_gold_path_raw, str) or not row_gold_path_raw.strip():
        return None
    row_gold_path = Path(row_gold_path_raw)
    if not row_gold_path.exists() or not row_gold_path.is_file():
        return None
    return row_gold_path


def _normalize_labels(
    value: Any,
    *,
    strict_empty_to_other: bool,
) -> list[str]:
    if isinstance(value, list):
        labels = [normalize_freeform_label(str(item or "")) for item in value]
    elif value is None:
        labels = []
    else:
        labels = [normalize_freeform_label(str(value or ""))]
    normalized = sorted(
        {
            label
            for label in labels
            if label in _FREEFORM_LABEL_SET and label != "OTHER"
        }
    )
    if normalized:
        return normalized
    return ["OTHER"] if strict_empty_to_other else []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
