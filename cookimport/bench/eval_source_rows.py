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
    authority_by_row_index, authority_by_block_index, authority_path = _load_nonrecipe_authority_by_block_index(
        stage_predictions_json
    )

    gold_by_row_id: dict[str, dict[str, Any]] = {}
    gold_row_id_by_row_index: dict[int, str] = {}
    gold_by_row_index: dict[int, dict[str, Any]] = {}
    for row in gold_rows:
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            continue
        gold_by_row_id[row_id] = row
        row_index = _coerce_int(row.get("row_index"))
        if row_index is not None and row_index not in gold_row_id_by_row_index:
            gold_row_id_by_row_index[row_index] = row_id
        if row_index is not None and row_index not in gold_by_row_index:
            gold_by_row_index[row_index] = row

    prediction_by_row_id: dict[str, dict[str, Any]] = {}
    direct_row_id_match_rows = 0
    row_index_fallback_match_rows = 0
    row_identity_conflict_rows = 0
    for row in prediction_rows:
        original_row_id = str(row.get("row_id") or "").strip()
        row_index = _coerce_int(row.get("row_index", row.get("atomic_index")))
        resolved_gold_row: dict[str, Any] | None = None
        match_mode = ""
        direct_gold_row = gold_by_row_id.get(original_row_id) if original_row_id else None
        row_index_gold_row = gold_by_row_index.get(row_index) if row_index is not None else None
        if direct_gold_row is not None and row_index_gold_row is not None:
            if direct_gold_row is row_index_gold_row:
                resolved_gold_row = direct_gold_row
                match_mode = "row_id"
            else:
                row_identity_conflict_rows += 1
                resolved_gold_row, match_mode = _resolve_conflicting_gold_rows(
                    prediction_row=row,
                    direct_gold_row=direct_gold_row,
                    row_index_gold_row=row_index_gold_row,
                )
        elif direct_gold_row is not None:
            if _prediction_matches_gold_row(
                prediction_row=row,
                gold_row=direct_gold_row,
                require_row_index_match=False,
            ):
                resolved_gold_row = direct_gold_row
                match_mode = "row_id"
        elif row_index_gold_row is not None:
            resolved_gold_row = row_index_gold_row
            match_mode = "row_index"
        if resolved_gold_row is None:
            continue
        resolved_row_id = str(resolved_gold_row.get("row_id") or "").strip()
        if not resolved_row_id:
            continue
        existing = prediction_by_row_id.get(resolved_row_id)
        if existing is not None and _match_mode_rank(existing.get("_match_mode")) >= _match_mode_rank(match_mode):
            continue
        row_payload = dict(row)
        row_payload["_match_mode"] = match_mode
        row_payload["_resolved_row_id"] = resolved_row_id
        prediction_by_row_id[resolved_row_id] = row_payload

    for row in prediction_by_row_id.values():
        if row.get("_match_mode") == "row_id":
            direct_row_id_match_rows += 1
        elif row.get("_match_mode") == "row_index":
            row_index_fallback_match_rows += 1

    aligned_rows: list[dict[str, Any]] = []
    wrong_rows: list[dict[str, Any]] = []
    per_label: dict[str, dict[str, int]] = {
        label: {"gold": 0, "pred": 0, "correct": 0} for label in sorted(_FREEFORM_LABEL_SET)
    }
    confusion: dict[str, dict[str, int]] = {}
    correct = 0
    total = 0
    missing_prediction_count = 0
    authority_override_rows = 0

    for row_id, gold_row in sorted(
        gold_by_row_id.items(),
        key=lambda item: (_coerce_int(item[1].get("row_index")) or -1, item[0]),
    ):
        gold_labels = _normalize_labels(gold_row.get("labels"))
        if not gold_labels:
            continue
        primary_gold = gold_labels[0]
        prediction = prediction_by_row_id.get(row_id)
        raw_pred_label = str(
            (prediction or {}).get("label") or (prediction or {}).get("final_label") or "OTHER"
        )
        pred_label = normalize_freeform_label(raw_pred_label)
        pred_block_index = _coerce_int((prediction or {}).get("block_index"))
        pred_row_index = _coerce_int((prediction or {}).get("atomic_index", (prediction or {}).get("row_index")))
        reason_tags = {
            str(tag or "").strip()
            for tag in ((prediction or {}).get("reason_tags") or [])
            if str(tag or "").strip()
        }
        preserve_row_level_other = (
            raw_pred_label.strip().upper() == "NONRECIPE_EXCLUDE"
            or "nonrecipe_authority:preserved_exclude" in reason_tags
        )
        authority_label = None
        if not preserve_row_level_other:
            authority_label = _authority_category_to_label(authority_by_row_index.get(pred_row_index))
            if authority_label is None:
                authority_label = _authority_category_to_label(
                    authority_by_block_index.get(pred_block_index)
                )
        if authority_label is not None and authority_label != pred_label:
            pred_label = authority_label
            authority_override_rows += 1
        if pred_label not in _FREEFORM_LABEL_SET:
            pred_label = "OTHER"
        is_correct = pred_label in set(gold_labels)
        row_index = _coerce_int(gold_row.get("row_index"))
        source_block_index = _coerce_int(gold_row.get("source_block_index"))
        text = str(gold_row.get("text") or (prediction or {}).get("text") or "")
        payload = {
            "row_id": row_id,
            "row_index": row_index,
            "line_index": row_index,
            "source_block_index": source_block_index,
            "line_text": text,
            "gold_label": primary_gold,
            "gold_labels": gold_labels,
            "pred_label": pred_label,
            "prediction_match_mode": (prediction or {}).get("_match_mode"),
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
            "direct_row_id_match_rows": direct_row_id_match_rows,
            "row_index_fallback_match_rows": row_index_fallback_match_rows,
            "row_identity_conflict_rows": row_identity_conflict_rows,
            "authority_override_rows": authority_override_rows,
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
        "artifacts": {
            "nonrecipe_authority_path": str(authority_path) if authority_path is not None else None,
        },
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
        f"- Direct row-id matches: {counts.get('direct_row_id_match_rows', 0)}",
        f"- Row-index fallback matches: {counts.get('row_index_fallback_match_rows', 0)}",
        f"- Row identity conflicts: {counts.get('row_identity_conflict_rows', 0)}",
        f"- Authority overrides: {counts.get('authority_override_rows', 0)}",
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


def _load_nonrecipe_authority_by_block_index(
    stage_predictions_json: Path,
) -> tuple[dict[int, str], dict[int, str], Path | None]:
    manifest_path = stage_predictions_json.parent.parent / "run_manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return {}, {}, None
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}, None
    if not isinstance(manifest_payload, dict):
        return {}, {}, None
    artifacts = manifest_payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}, {}, None
    candidate_dirs: list[Path] = []
    for key in ("processed_output_run_dir", "stage_run_dir"):
        raw_value = artifacts.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        candidate = Path(raw_value)
        if not candidate.is_absolute():
            candidate = (manifest_path.parent / candidate).resolve()
        candidate_dirs.append(candidate)
    for candidate_dir in candidate_dirs:
        authority_path = candidate_dir / "09_nonrecipe_row_authority.json"
        if not authority_path.exists() or not authority_path.is_file():
            authority_path = candidate_dir / "09_nonrecipe_authority.json"
            if not authority_path.exists() or not authority_path.is_file():
                continue
        try:
            payload = json.loads(authority_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        row_map = payload.get("authoritative_row_category_by_index")
        block_map = payload.get("authoritative_block_category_by_index")
        normalized_rows: dict[int, str] = {}
        if isinstance(row_map, dict):
            for key, value in row_map.items():
                row_index = _coerce_int(key)
                if row_index is None:
                    continue
                category = str(value or "").strip().lower()
                if category in {"knowledge", "other"}:
                    normalized_rows[row_index] = category
        if not isinstance(block_map, dict):
            if normalized_rows:
                return normalized_rows, {}, authority_path
            continue
        normalized: dict[int, str] = {}
        for key, value in block_map.items():
            block_index = _coerce_int(key)
            if block_index is None:
                continue
            category = str(value or "").strip().lower()
            if category in {"knowledge", "other"}:
                normalized[block_index] = category
        if normalized or normalized_rows:
            return normalized_rows, normalized, authority_path
    return {}, {}, None


def _authority_category_to_label(category: str | None) -> str | None:
    if category == "knowledge":
        return "KNOWLEDGE"
    if category == "other":
        return "OTHER"
    return None


def _resolve_conflicting_gold_rows(
    *,
    prediction_row: dict[str, Any],
    direct_gold_row: dict[str, Any],
    row_index_gold_row: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    direct_text_match = _prediction_matches_gold_row(
        prediction_row=prediction_row,
        gold_row=direct_gold_row,
        require_row_index_match=False,
    )
    row_index_text_match = _prediction_matches_gold_row(
        prediction_row=prediction_row,
        gold_row=row_index_gold_row,
        require_row_index_match=True,
    )
    if row_index_text_match and not direct_text_match:
        return row_index_gold_row, "row_index"
    if direct_text_match and not row_index_text_match:
        return direct_gold_row, "row_id"
    return row_index_gold_row, "row_index"


def _prediction_matches_gold_row(
    *,
    prediction_row: dict[str, Any],
    gold_row: dict[str, Any],
    require_row_index_match: bool,
) -> bool:
    pred_row_index = _coerce_int(
        prediction_row.get("row_index", prediction_row.get("atomic_index"))
    )
    gold_row_index = _coerce_int(gold_row.get("row_index"))
    if require_row_index_match and pred_row_index is not None and gold_row_index is not None:
        if pred_row_index != gold_row_index:
            return False
    prediction_text = _normalize_match_text(prediction_row.get("text"))
    gold_text = _normalize_match_text(gold_row.get("text"))
    if prediction_text and gold_text:
        return prediction_text == gold_text
    if require_row_index_match and pred_row_index is not None and gold_row_index is not None:
        return pred_row_index == gold_row_index
    return True


def _normalize_match_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _match_mode_rank(value: Any) -> int:
    mode = str(value or "").strip().lower()
    if mode == "row_id":
        return 1
    if mode == "row_index":
        return 2
    return 0


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
