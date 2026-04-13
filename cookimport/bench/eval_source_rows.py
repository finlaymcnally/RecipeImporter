from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS, normalize_freeform_label

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)


def evaluate_source_rows(
    *,
    gold_export_root: Path,
    stage_predictions_json: Path,
    extracted_blocks_json: Path,
    out_dir: Path,
) -> dict[str, Any]:
    del extracted_blocks_json
    out_dir.mkdir(parents=True, exist_ok=True)
    row_gold_path = _resolve_row_gold_path(gold_export_root)
    prediction_rows_path = _resolve_prediction_rows_path(stage_predictions_json)
    gold_rows = _read_jsonl(row_gold_path)
    prediction_rows = _read_jsonl(prediction_rows_path)

    gold_by_row_id: dict[str, dict[str, Any]] = {}
    gold_row_id_by_row_index: dict[int, str] = {}
    for row in gold_rows:
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            continue
        gold_by_row_id[row_id] = row
        row_index = _coerce_int(row.get("row_index"))
        if row_index is not None and row_index not in gold_row_id_by_row_index:
            gold_row_id_by_row_index[row_index] = row_id

    prediction_by_row_id: dict[str, dict[str, Any]] = {}
    for row in prediction_rows:
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            row_index = _coerce_int(row.get("row_index", row.get("atomic_index")))
            if row_index is not None:
                row_id = gold_row_id_by_row_index.get(row_index, "")
        if not row_id:
            continue
        prediction_by_row_id[row_id] = row

    aligned_rows: list[dict[str, Any]] = []
    wrong_rows: list[dict[str, Any]] = []
    per_label: dict[str, dict[str, int]] = {
        label: {"gold": 0, "pred": 0, "correct": 0} for label in sorted(_FREEFORM_LABEL_SET)
    }
    confusion: dict[str, dict[str, int]] = {}
    correct = 0
    total = 0
    missing_prediction_count = 0

    for row_id, gold_row in sorted(
        gold_by_row_id.items(),
        key=lambda item: (_coerce_int(item[1].get("row_index")) or -1, item[0]),
    ):
        gold_labels = _normalize_labels(gold_row.get("labels"))
        if not gold_labels:
            continue
        primary_gold = gold_labels[0]
        prediction = prediction_by_row_id.get(row_id)
        pred_label = normalize_freeform_label(
            str((prediction or {}).get("label") or (prediction or {}).get("final_label") or "OTHER")
        )
        if pred_label not in _FREEFORM_LABEL_SET:
            pred_label = "OTHER"
        is_correct = pred_label in set(gold_labels)
        row_index = _coerce_int(gold_row.get("row_index"))
        block_index = _coerce_int(gold_row.get("block_index"))
        text = str(gold_row.get("text") or (prediction or {}).get("text") or "")
        payload = {
            "row_id": row_id,
            "row_index": row_index,
            "line_index": row_index,
            "block_index": block_index,
            "line_text": text,
            "gold_label": primary_gold,
            "gold_labels": gold_labels,
            "pred_label": pred_label,
            "is_wrong_label": not is_correct,
        }
        aligned_rows.append(payload)
        total += 1
        per_label.setdefault(primary_gold, {"gold": 0, "pred": 0, "correct": 0})["gold"] += 1
        per_label.setdefault(pred_label, {"gold": 0, "pred": 0, "correct": 0})["pred"] += 1
        by_gold = confusion.setdefault(primary_gold, {})
        by_gold[pred_label] = int(by_gold.get(pred_label, 0)) + 1
        if is_correct:
            correct += 1
            per_label.setdefault(primary_gold, {"gold": 0, "pred": 0, "correct": 0})["correct"] += 1
        else:
            wrong_rows.append(payload)
        if prediction is None:
            missing_prediction_count += 1

    micro_precision = correct / total if total else 0.0
    micro_recall = correct / total if total else 0.0
    micro_f1 = _f1(micro_precision, micro_recall)

    per_label_rows: dict[str, dict[str, Any]] = {}
    macro_labels: list[str] = []
    macro_f1_total = 0.0
    worst_label = "OTHER"
    worst_recall = 1.0
    worst_gold_total = 0
    for label in sorted(per_label):
        gold_count = int(per_label[label]["gold"])
        pred_count = int(per_label[label]["pred"])
        correct_count = int(per_label[label]["correct"])
        precision = correct_count / pred_count if pred_count else 0.0
        recall = correct_count / gold_count if gold_count else 0.0
        f1 = _f1(precision, recall)
        per_label_rows[label] = {
            "gold_total": gold_count,
            "pred_total": pred_count,
            "tp": correct_count,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }
        if label != "OTHER":
            macro_labels.append(label)
            macro_f1_total += f1
            if gold_count > 0 and recall <= worst_recall:
                worst_label = label
                worst_recall = recall
                worst_gold_total = gold_count

    macro_f1 = macro_f1_total / len(macro_labels) if macro_labels else 0.0

    wrong_path = out_dir / "wrong_label_lines.jsonl"
    aligned_path = out_dir / "aligned_prediction_blocks.jsonl"
    report_path = out_dir / "eval_report.json"
    _write_jsonl(wrong_path, wrong_rows)
    _write_jsonl(aligned_path, aligned_rows)
    report = {
        "eval_mode": "source-rows",
        "eval_type": "source_row_classification",
        "labels": list(sorted(_FREEFORM_LABEL_SET)),
        "gold_export_root": str(gold_export_root),
        "row_gold_labels_path": str(row_gold_path),
        "row_label_predictions_path": str(prediction_rows_path),
        "counts": {
            "gold_total": total,
            "pred_total": total,
            "gold_matched": correct,
            "pred_matched": correct,
            "gold_missed": total - correct,
            "pred_false_positive": total - correct,
            "gold_rows": len(gold_by_row_id),
            "pred_rows": len(prediction_by_row_id),
            "scored_rows": total,
            "correct_rows": correct,
            "wrong_rows": len(wrong_rows),
            "missing_prediction_rows": missing_prediction_count,
        },
        "metrics": {
            "micro_precision": round(micro_precision, 6),
            "micro_recall": round(micro_recall, 6),
            "micro_f1": round(micro_f1, 6),
            "accuracy": round(correct / total, 6) if total else 0.0,
        },
        "strict_accuracy": round(correct / total, 6) if total else 0.0,
        "overall_block_accuracy": round(correct / total, 6) if total else 0.0,
        "overall_line_accuracy": round(correct / total, 6) if total else 0.0,
        "macro_f1_excluding_other": round(macro_f1, 6),
        "macro_f1_labels": macro_labels,
        "worst_label_recall": {
            "label": worst_label,
            "recall": round(worst_recall if worst_gold_total else 0.0, 6),
            "gold_total": int(worst_gold_total),
        },
        "per_label": per_label_rows,
        "confusion": confusion,
        "wrong_label_blocks": wrong_rows,
        "wrong_label_lines": wrong_rows,
        "output": {
            "wrong_label_lines_path": str(wrong_path),
            "aligned_prediction_blocks_path": str(aligned_path),
            "eval_report_path": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "report": report,
        "report_md_text": format_source_row_eval_report_md(report),
        "wrong_label_lines_path": wrong_path,
        "aligned_prediction_blocks_path": aligned_path,
        "eval_report_path": report_path,
    }


def format_source_row_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    lines = [
        "# Source Rows Eval",
        "",
        f"- Scored rows: {counts.get('scored_rows', 0)}",
        f"- Correct rows: {counts.get('correct_rows', 0)}",
        f"- Wrong rows: {counts.get('wrong_rows', 0)}",
        f"- Missing prediction rows: {counts.get('missing_prediction_rows', 0)}",
        f"- Overall line accuracy: {float(report.get('overall_line_accuracy') or 0.0):.3f}",
        (
            "- Macro F1 (excluding OTHER): "
            f"{float(report.get('macro_f1_excluding_other') or 0.0):.3f}"
        ),
        "",
        "## Per Label",
        "",
    ]
    per_label = report.get("per_label") if isinstance(report.get("per_label"), dict) else {}
    for label in sorted(per_label):
        row = per_label[label]
        lines.append(
            f"- {label}: gold={row.get('gold_total', 0)} "
            f"pred={row.get('pred_total', 0)} "
            f"correct={row.get('tp', 0)} "
            f"f1={float(row.get('f1', 0.0)):.4f}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _resolve_row_gold_path(gold_export_root: Path) -> Path:
    if gold_export_root.is_file():
        if gold_export_root.name == "row_gold_labels.jsonl":
            return gold_export_root
        gold_export_root = gold_export_root.parent
    candidate = gold_export_root / "row_gold_labels.jsonl"
    if not candidate.exists():
        raise FileNotFoundError(f"row_gold_labels.jsonl not found under {gold_export_root}")
    return candidate


def _resolve_prediction_rows_path(stage_predictions_json: Path) -> Path:
    candidates = [
        stage_predictions_json.parent / "row_label_predictions.jsonl",
        stage_predictions_json.parent / "semantic_line_role_predictions.jsonl",
        stage_predictions_json.parent / "line_role_predictions.jsonl",
        stage_predictions_json.parent.parent / "line-role-pipeline" / "row_label_predictions.jsonl",
        stage_predictions_json.parent.parent / "line-role-pipeline" / "semantic_line_role_predictions.jsonl",
        stage_predictions_json.parent.parent / "line-role-pipeline" / "line_role_predictions.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not locate row prediction artifact beside {stage_predictions_json}"
    )


def _normalize_labels(value: Any) -> list[str]:
    if isinstance(value, list):
        labels = [normalize_freeform_label(str(item or "")) for item in value]
    elif value is None:
        labels = []
    else:
        labels = [normalize_freeform_label(str(value or ""))]
    return [label for label in labels if label in _FREEFORM_LABEL_SET]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _f1(precision: float, recall: float) -> float:
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    return (2 * precision * recall) / (precision + recall)
