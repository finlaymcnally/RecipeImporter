from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STRUCTURE_LABEL_REPORT_SCHEMA_VERSION = "benchmark_structure_label_report.v1"

STRUCTURE_CORE_LABELS = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
)
RECIPE_CONTEXT_AUXILIARY_LABELS = (
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
)
NONRECIPE_CORE_LABELS = (
    "KNOWLEDGE",
    "OTHER",
)

_BUCKET_ORDER = {
    "structure_core": 0,
    "recipe_context_auxiliary": 1,
    "nonrecipe_core": 2,
    "other": 3,
}


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return float(number)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 6)


def _format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def label_bucket(label: str) -> str:
    normalized = str(label or "").strip()
    if normalized in STRUCTURE_CORE_LABELS:
        return "structure_core"
    if normalized in RECIPE_CONTEXT_AUXILIARY_LABELS:
        return "recipe_context_auxiliary"
    if normalized in NONRECIPE_CORE_LABELS:
        return "nonrecipe_core"
    return "other"


def _normalize_label_row(raw_row: dict[str, Any]) -> dict[str, Any] | None:
    label = str(raw_row.get("label") or "").strip()
    if not label:
        return None
    return {
        "label": label,
        "bucket": label_bucket(label),
        "pair_count_with_metrics": int(_coerce_int(raw_row.get("pair_count_with_metrics")) or 0),
        "gold_total_sum": int(_coerce_int(raw_row.get("gold_total_sum")) or 0),
        "pred_total_sum": int(_coerce_int(raw_row.get("pred_total_sum")) or 0),
        "codex_precision_avg": _coerce_float(raw_row.get("codex_precision_avg")),
        "baseline_precision_avg": _coerce_float(raw_row.get("baseline_precision_avg")),
        "delta_precision_avg": _coerce_float(raw_row.get("delta_precision_avg")),
        "codex_recall_avg": _coerce_float(raw_row.get("codex_recall_avg")),
        "baseline_recall_avg": _coerce_float(raw_row.get("baseline_recall_avg")),
        "delta_recall_avg": _coerce_float(raw_row.get("delta_recall_avg")),
        "codex_f1_avg": _coerce_float(raw_row.get("codex_f1_avg")),
        "baseline_f1_avg": _coerce_float(raw_row.get("baseline_f1_avg")),
        "delta_f1_avg": _coerce_float(raw_row.get("delta_f1_avg")),
        "confusion_delta_outbound_total": int(
            _coerce_int(raw_row.get("confusion_delta_outbound_total")) or 0
        ),
        "confusion_delta_inbound_total": int(
            _coerce_int(raw_row.get("confusion_delta_inbound_total")) or 0
        ),
        "top_confusion_outbound": (
            list(raw_row.get("top_confusion_outbound"))
            if isinstance(raw_row.get("top_confusion_outbound"), list)
            else []
        ),
        "top_confusion_inbound": (
            list(raw_row.get("top_confusion_inbound"))
            if isinstance(raw_row.get("top_confusion_inbound"), list)
            else []
        ),
    }


def _slice_summary(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored_rows = [
        row
        for row in rows
        if int(row.get("gold_total_sum") or 0) > 0 or int(row.get("pred_total_sum") or 0) > 0
    ]
    return {
        "slice": name,
        "label_count": len(rows),
        "scored_label_count": len(scored_rows),
        "labels": [str(row.get("label") or "") for row in rows],
        "scored_labels": [str(row.get("label") or "") for row in scored_rows],
        "pair_count_with_metrics_max": max(
            (int(row.get("pair_count_with_metrics") or 0) for row in rows),
            default=0,
        ),
        "gold_total_sum": sum(int(row.get("gold_total_sum") or 0) for row in rows),
        "pred_total_sum": sum(int(row.get("pred_total_sum") or 0) for row in rows),
        "codex_precision_avg": _mean(
            [_coerce_float(row.get("codex_precision_avg")) for row in scored_rows]
        ),
        "baseline_precision_avg": _mean(
            [_coerce_float(row.get("baseline_precision_avg")) for row in scored_rows]
        ),
        "delta_precision_avg": _mean(
            [_coerce_float(row.get("delta_precision_avg")) for row in scored_rows]
        ),
        "codex_recall_avg": _mean(
            [_coerce_float(row.get("codex_recall_avg")) for row in scored_rows]
        ),
        "baseline_recall_avg": _mean(
            [_coerce_float(row.get("baseline_recall_avg")) for row in scored_rows]
        ),
        "delta_recall_avg": _mean(
            [_coerce_float(row.get("delta_recall_avg")) for row in scored_rows]
        ),
        "codex_f1_avg": _mean([_coerce_float(row.get("codex_f1_avg")) for row in scored_rows]),
        "baseline_f1_avg": _mean(
            [_coerce_float(row.get("baseline_f1_avg")) for row in scored_rows]
        ),
        "delta_f1_avg": _mean([_coerce_float(row.get("delta_f1_avg")) for row in scored_rows]),
    }


def _load_boundary_counts(run_dir: Path) -> dict[str, Any] | None:
    payload = _load_json_object(run_dir / "eval_report.json")
    if not payload:
        return None
    boundary = payload.get("boundary")
    boundary = boundary if isinstance(boundary, dict) else {}
    correct = int(_coerce_int(boundary.get("correct")) or 0)
    over = int(_coerce_int(boundary.get("over")) or 0)
    under = int(_coerce_int(boundary.get("under")) or 0)
    partial = int(_coerce_int(boundary.get("partial")) or 0)
    total = correct + over + under + partial
    return {
        "correct": correct,
        "over": over,
        "under": under,
        "partial": partial,
        "total": total,
        "exact_ratio": (correct / total) if total > 0 else None,
        "error_total": over + under + partial,
    }


def _boundary_summary(
    *,
    pair_rows: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for pair in pair_rows:
        source_key = str(pair.get("source_key") or "").strip()
        codex_run_id = str(pair.get("codex_run_id") or "").strip()
        baseline_run_id = str(pair.get("baseline_run_id") or "").strip()
        if not source_key or not codex_run_id or not baseline_run_id:
            continue
        codex_run_dir = run_dir_by_id.get(codex_run_id)
        baseline_run_dir = run_dir_by_id.get(baseline_run_id)
        if codex_run_dir is None or baseline_run_dir is None:
            continue
        codex_boundary = _load_boundary_counts(codex_run_dir)
        baseline_boundary = _load_boundary_counts(baseline_run_dir)
        if codex_boundary is None or baseline_boundary is None:
            continue
        codex_exact = _coerce_float(codex_boundary.get("exact_ratio"))
        baseline_exact = _coerce_float(baseline_boundary.get("exact_ratio"))
        row = {
            "source_key": source_key,
            "codex_run_id": codex_run_id,
            "baseline_run_id": baseline_run_id,
            "codex_correct": int(codex_boundary.get("correct") or 0),
            "baseline_correct": int(baseline_boundary.get("correct") or 0),
            "delta_correct": int(codex_boundary.get("correct") or 0)
            - int(baseline_boundary.get("correct") or 0),
            "codex_error_total": int(codex_boundary.get("error_total") or 0),
            "baseline_error_total": int(baseline_boundary.get("error_total") or 0),
            "delta_error_total": int(codex_boundary.get("error_total") or 0)
            - int(baseline_boundary.get("error_total") or 0),
            "codex_exact_ratio": codex_exact,
            "baseline_exact_ratio": baseline_exact,
            "delta_exact_ratio": (
                round(codex_exact - baseline_exact, 6)
                if codex_exact is not None and baseline_exact is not None
                else None
            ),
        }
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("source_key") or ""))
    return {
        "pair_count": len(rows),
        "rows": rows,
        "codex_exact_ratio_avg": _mean(
            [_coerce_float(row.get("codex_exact_ratio")) for row in rows]
        ),
        "baseline_exact_ratio_avg": _mean(
            [_coerce_float(row.get("baseline_exact_ratio")) for row in rows]
        ),
        "delta_exact_ratio_avg": _mean(
            [_coerce_float(row.get("delta_exact_ratio")) for row in rows]
        ),
        "codex_error_total_avg": _mean(
            [float(int(row.get("codex_error_total") or 0)) for row in rows]
        ),
        "baseline_error_total_avg": _mean(
            [float(int(row.get("baseline_error_total") or 0)) for row in rows]
        ),
        "delta_error_total_avg": _mean(
            [float(int(row.get("delta_error_total") or 0)) for row in rows]
        ),
    }


def _top_cross_bucket_confusions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        gold_label = str(row.get("label") or "").strip()
        gold_bucket = str(row.get("bucket") or "").strip() or "other"
        for confusion in row.get("top_confusion_outbound") or []:
            if not isinstance(confusion, dict):
                continue
            pred_label = str(confusion.get("pred_label") or "").strip()
            if not pred_label:
                continue
            pred_bucket = label_bucket(pred_label)
            if pred_bucket == gold_bucket:
                continue
            output.append(
                {
                    "gold_label": gold_label,
                    "gold_bucket": gold_bucket,
                    "pred_label": pred_label,
                    "pred_bucket": pred_bucket,
                    "delta_count": int(_coerce_int(confusion.get("delta_count")) or 0),
                }
            )
    output.sort(
        key=lambda row: (
            -abs(int(row.get("delta_count") or 0)),
            str(row.get("gold_label") or ""),
            str(row.get("pred_label") or ""),
        )
    )
    return output[:10]


def build_structure_label_report(
    *,
    per_label_metrics: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    label_rows = [
        row
        for row in (
            _normalize_label_row(raw_row)
            for raw_row in per_label_metrics
            if isinstance(raw_row, dict)
        )
        if row is not None
    ]
    label_rows.sort(
        key=lambda row: (
            _BUCKET_ORDER.get(str(row.get("bucket") or "other"), 99),
            str(row.get("label") or ""),
        )
    )

    structure_rows = [row for row in label_rows if row.get("bucket") == "structure_core"]
    auxiliary_rows = [
        row for row in label_rows if row.get("bucket") == "recipe_context_auxiliary"
    ]
    nonrecipe_rows = [row for row in label_rows if row.get("bucket") == "nonrecipe_core"]
    other_rows = [row for row in label_rows if row.get("bucket") == "other"]
    boundary = _boundary_summary(pair_rows=pair_rows, run_dir_by_id=run_dir_by_id)

    structure_slice = _slice_summary("structure_core", structure_rows)
    auxiliary_slice = _slice_summary("recipe_context_auxiliary", auxiliary_rows)
    nonrecipe_slice = _slice_summary("nonrecipe_core", nonrecipe_rows)
    other_slice = _slice_summary("other", other_rows)

    reading_hints: list[str] = []
    if boundary.get("pair_count"):
        reading_hints.append(
            "Boundary exact-match ratio "
            f"codex={_format_metric(_coerce_float(boundary.get('codex_exact_ratio_avg')))} "
            f"baseline={_format_metric(_coerce_float(boundary.get('baseline_exact_ratio_avg')))} "
            f"delta={_format_metric(_coerce_float(boundary.get('delta_exact_ratio_avg')))}."
        )
    reading_hints.append(
        "Core structure labels "
        f"codex_f1={_format_metric(_coerce_float(structure_slice.get('codex_f1_avg')))} "
        f"baseline_f1={_format_metric(_coerce_float(structure_slice.get('baseline_f1_avg')))} "
        f"delta_f1={_format_metric(_coerce_float(structure_slice.get('delta_f1_avg')))}."
    )
    reading_hints.append(
        "Nonrecipe labels "
        f"codex_f1={_format_metric(_coerce_float(nonrecipe_slice.get('codex_f1_avg')))} "
        f"baseline_f1={_format_metric(_coerce_float(nonrecipe_slice.get('baseline_f1_avg')))} "
        f"delta_f1={_format_metric(_coerce_float(nonrecipe_slice.get('delta_f1_avg')))}."
    )
    cross_bucket = _top_cross_bucket_confusions(label_rows)
    if cross_bucket:
        first = cross_bucket[0]
        reading_hints.append(
            "Largest cross-bucket confusion delta "
            f"{first['gold_label']}->{first['pred_label']} "
            f"(delta_count={int(first.get('delta_count') or 0)})."
        )

    return {
        "schema_version": STRUCTURE_LABEL_REPORT_SCHEMA_VERSION,
        "pair_count": len(pair_rows),
        "label_groups": {
            "structure_core": list(STRUCTURE_CORE_LABELS),
            "recipe_context_auxiliary": list(RECIPE_CONTEXT_AUXILIARY_LABELS),
            "nonrecipe_core": list(NONRECIPE_CORE_LABELS),
        },
        "reading_hints": reading_hints,
        "slices": {
            "structure_core": structure_slice,
            "recipe_context_auxiliary": auxiliary_slice,
            "nonrecipe_core": nonrecipe_slice,
            "other": other_slice,
        },
        "boundary": boundary,
        "top_cross_bucket_confusions": cross_bucket,
        "label_rows": label_rows,
    }
