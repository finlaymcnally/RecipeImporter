from __future__ import annotations

from pathlib import Path
from typing import Any

from cookimport.bench.row_gold_lines import (
    load_row_gold_line_labels,
    resolve_row_gold_path_from_eval_report,
)

from .io import _coerce_int, _excerpt


def _build_correct_label_sample(
    *,
    eval_report: dict[str, Any],
    wrong_label_rows: list[dict[str, Any]],
    sample_limit: int,
    excerpt_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row_gold_path = resolve_row_gold_path_from_eval_report(eval_report)
    if row_gold_path is None:
        return [], {"status": "skipped", "reason": "missing_row_gold_path"}

    lines, label_sets_by_line = load_row_gold_line_labels(
        row_gold_path,
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
        "row_gold_labels_path": str(row_gold_path),
    }
    return sample, metadata
