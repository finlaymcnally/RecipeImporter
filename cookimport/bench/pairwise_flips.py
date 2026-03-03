from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_line_role_flips_vs_baseline(
    *,
    joined_line_rows: list[dict[str, Any]],
    line_role_predictions_path: Path | None,
    baseline_joined_line_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return rows where baseline label differs from candidate label.

    Preferred baseline source:
    - `baseline_joined_line_rows` from a paired history baseline eval run.

    Fallback baseline inference (when paired rows are unavailable):
    - rows decided by `codex` are treated as baseline `OTHER`
    - all other rows retain candidate label as baseline
    """
    baseline_by_sample_id, baseline_by_line_index = _build_baseline_lookup(
        baseline_joined_line_rows
    )
    if baseline_by_sample_id or baseline_by_line_index:
        output: list[dict[str, Any]] = []
        for row in joined_line_rows:
            line_index = _coerce_int(row.get("line_index"))
            if line_index is None:
                continue
            sample_id = str(row.get("sample_id") or f"line:{line_index}")
            baseline_row = baseline_by_sample_id.get(sample_id)
            if baseline_row is None:
                baseline_row = baseline_by_line_index.get(line_index)
            if baseline_row is None:
                continue
            candidate_label = (
                str(row.get("pred_label") or "OTHER").strip().upper() or "OTHER"
            )
            baseline_label = (
                str(baseline_row.get("pred_label") or "OTHER").strip().upper() or "OTHER"
            )
            if baseline_label == candidate_label:
                continue
            output.append(
                {
                    "sample_id": sample_id,
                    "line_index": line_index,
                    "line_text": str(row.get("line_text") or ""),
                    "gold_label": str(row.get("gold_label") or "OTHER"),
                    "baseline_label": baseline_label,
                    "candidate_label": candidate_label,
                    "decided_by": str(row.get("decided_by") or ""),
                    "baseline_source": "paired_history_baseline",
                }
            )
        output.sort(key=lambda item: (int(item["line_index"]), str(item["sample_id"])))
        return output

    if line_role_predictions_path is None:
        return []
    if not line_role_predictions_path.exists() or not line_role_predictions_path.is_file():
        return []

    decided_by_by_line_index = _load_decided_by_by_line_index(line_role_predictions_path)

    output: list[dict[str, Any]] = []
    for row in joined_line_rows:
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        decided_by = str(row.get("decided_by") or "").strip().lower()
        if not decided_by:
            decided_by = decided_by_by_line_index.get(line_index) or ""
        if not decided_by:
            continue
        candidate_label = str(row.get("pred_label") or "OTHER").strip().upper() or "OTHER"
        baseline_label = (
            "OTHER"
            if decided_by == "codex"
            else candidate_label
        )
        if baseline_label == candidate_label:
            continue
        output.append(
            {
                "sample_id": str(row.get("sample_id") or f"line:{line_index}"),
                "line_index": line_index,
                "line_text": str(row.get("line_text") or ""),
                "gold_label": str(row.get("gold_label") or "OTHER"),
                "baseline_label": baseline_label,
                "candidate_label": candidate_label,
                "decided_by": decided_by,
                "baseline_source": "inferred_from_line_role_decided_by",
            }
        )
    output.sort(key=lambda item: (int(item["line_index"]), str(item["sample_id"])))
    return output


def _load_decided_by_by_line_index(
    line_role_predictions_path: Path,
) -> dict[int, str]:
    decided_by_by_line_index: dict[int, str] = {}
    for raw_line in line_role_predictions_path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        atomic_index = _coerce_int(payload.get("atomic_index"))
        if atomic_index is None:
            continue
        decided_by = str(payload.get("decided_by") or "").strip().lower()
        if not decided_by:
            continue
        decided_by_by_line_index[atomic_index] = decided_by
    return decided_by_by_line_index


def _build_baseline_lookup(
    baseline_joined_line_rows: list[dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    by_sample_id: dict[str, dict[str, Any]] = {}
    by_line_index: dict[int, dict[str, Any]] = {}
    if not baseline_joined_line_rows:
        return by_sample_id, by_line_index
    for row in baseline_joined_line_rows:
        if not isinstance(row, dict):
            continue
        line_index = _coerce_int(row.get("line_index"))
        if line_index is not None:
            by_line_index[line_index] = row
        sample_id = str(row.get("sample_id") or "").strip()
        if sample_id:
            by_sample_id[sample_id] = row
    return by_sample_id, by_line_index


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
