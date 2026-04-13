from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label


def write_row_gold_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def derive_row_gold_bundle(span_rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_state: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    for span_row in span_rows:
        label = normalize_freeform_label(str(span_row.get("label") or "OTHER"))
        touched_rows = span_row.get("touched_rows")
        if not isinstance(touched_rows, list):
            continue
        for touched in touched_rows:
            if not isinstance(touched, dict):
                continue
            row_id = str(touched.get("row_id") or "").strip()
            if not row_id:
                continue
            row_index = _coerce_int(touched.get("row_index", touched.get("block_index")))
            source_block_index = _coerce_int(
                touched.get("source_block_index", touched.get("block_index"))
            )
            entry = row_state.setdefault(
                row_id,
                {
                    "row_id": row_id,
                    "row_index": row_index,
                    "block_index": source_block_index,
                    "row_ordinal": _coerce_int(touched.get("row_ordinal")),
                    "text": str(touched.get("text") or span_row.get("selected_text") or ""),
                    "source_hash": str(span_row.get("source_hash") or "unknown"),
                    "source_file": str(span_row.get("source_file") or "unknown"),
                    "labels": set(),
                    "span_ids": [],
                },
            )
            entry["labels"].add(label)
            entry["span_ids"].append(str(span_row.get("span_id") or ""))

    rows: list[dict[str, Any]] = []
    for row_id, entry in sorted(
        row_state.items(),
        key=lambda item: (
            _coerce_int(item[1].get("row_index")) or -1,
            item[0],
        ),
    ):
        labels = sorted(str(label) for label in entry["labels"])
        row_payload = {
            "row_id": row_id,
            "row_index": entry.get("row_index"),
            "block_index": entry.get("block_index"),
            "row_ordinal": entry.get("row_ordinal"),
            "text": entry.get("text"),
            "source_hash": entry.get("source_hash"),
            "source_file": entry.get("source_file"),
            "labels": labels,
        }
        rows.append(row_payload)
        if len(labels) > 1:
            conflicts.append(
                {
                    **row_payload,
                    "span_ids": [value for value in entry["span_ids"] if value],
                }
            )

    return {
        "rows": rows,
        "conflicts": conflicts,
    }


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
