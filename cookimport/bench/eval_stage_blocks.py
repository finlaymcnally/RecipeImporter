from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)


def _extract_block_indices(payload: dict[str, Any]) -> list[int]:
    values = payload.get("touched_block_indices")
    items: list[Any]
    if isinstance(values, list):
        items = values
    else:
        touched_blocks = payload.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            return []
        items = [
            item.get("block_index")
            for item in touched_blocks
            if isinstance(item, dict) and item.get("block_index") is not None
        ]

    indices: list[int] = []
    for value in items:
        try:
            indices.append(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _excerpt(text: str, *, limit: int = 220) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)] + "..."


def _load_extracted_block_texts(extracted_blocks_json: Path) -> dict[int, str]:
    if not extracted_blocks_json.exists() or not extracted_blocks_json.is_file():
        return {}

    try:
        payload = json.loads(extracted_blocks_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            records = [item for item in blocks if isinstance(item, dict)]

    by_index: dict[int, str] = {}
    for row in records:
        raw_index = row.get("index")
        if raw_index is None:
            raw_index = row.get("block_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        by_index[index] = str(row.get("text") or "")
    return by_index


def load_gold_block_labels(
    freeform_span_labels_jsonl_path: Path,
    *,
    conflict_output_path: Path | None = None,
) -> dict[int, str]:
    assignments: dict[int, set[str]] = {}
    assignment_spans: dict[int, list[dict[str, Any]]] = {}

    for line_number, line in enumerate(
        freeform_span_labels_jsonl_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in gold file at line {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            continue

        label_value = payload.get("label")
        if not isinstance(label_value, str) or not label_value.strip():
            continue
        normalized_label = normalize_freeform_label(label_value)
        if normalized_label not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Unsupported freeform label in gold file: {label_value!r}"
            )

        span_id = str(payload.get("span_id") or f"line:{line_number}")
        source_hash = payload.get("source_hash")
        source_file = payload.get("source_file")
        indices = _extract_block_indices(payload)
        if not indices:
            continue
        for block_index in indices:
            assignments.setdefault(block_index, set()).add(normalized_label)
            assignment_spans.setdefault(block_index, []).append(
                {
                    "span_id": span_id,
                    "label": normalized_label,
                    "source_hash": source_hash,
                    "source_file": source_file,
                }
            )

    if not assignments:
        raise ValueError(
            f"Gold file contains no usable block labels: {freeform_span_labels_jsonl_path}"
        )

    conflicts: list[dict[str, Any]] = []
    for block_index, labels in sorted(assignments.items()):
        if len(labels) <= 1:
            continue
        conflicts.append(
            {
                "block_index": block_index,
                "labels": sorted(labels),
                "spans": assignment_spans.get(block_index, []),
            }
        )

    if conflicts:
        if conflict_output_path is not None:
            _write_jsonl(conflict_output_path, conflicts)
        raise ValueError(
            "Gold conflicts detected: one or more blocks have multiple labels. "
            "Fix gold labeling and retry."
        )

    max_index = max(assignments)
    missing = [index for index in range(max_index + 1) if index not in assignments]
    if missing:
        if conflict_output_path is not None:
            _write_jsonl(
                conflict_output_path,
                [
                    {
                        "error": "gold_missing_block_labels",
                        "missing_block_indices": missing,
                    }
                ],
            )
        raise ValueError(
            "Gold is not exhaustive: missing labels for "
            f"{len(missing)} blocks (examples: {missing[:10]})."
        )

    return {
        block_index: next(iter(labels))
        for block_index, labels in sorted(assignments.items())
    }


def load_stage_block_labels(stage_block_predictions_json_path: Path) -> dict[int, str]:
    if not stage_block_predictions_json_path.exists():
        raise FileNotFoundError(
            "Missing stage block predictions manifest: "
            f"{stage_block_predictions_json_path}"
        )
    payload = json.loads(stage_block_predictions_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Stage block predictions payload must be an object.")

    schema_version = str(payload.get("schema_version") or "")
    if schema_version != "stage_block_predictions.v1":
        raise ValueError(
            "Unsupported stage block predictions schema version: "
            f"{schema_version or '<missing>'}"
        )

    raw_block_labels = payload.get("block_labels")
    if not isinstance(raw_block_labels, dict):
        raise ValueError("Stage block predictions missing block_labels map.")

    labels: dict[int, str] = {}
    for raw_index, raw_label in raw_block_labels.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid block index in stage predictions: {raw_index!r}") from None
        label = str(raw_label or "").strip()
        if label not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Invalid stage label {label!r} at block {index}; expected one of {sorted(_FREEFORM_LABEL_SET)}"
            )
        labels[index] = label

    block_count_raw = payload.get("block_count")
    expected_count: int | None = None
    try:
        if block_count_raw is not None:
            expected_count = int(block_count_raw)
    except (TypeError, ValueError):
        expected_count = None

    if expected_count is not None and expected_count >= 0:
        missing = [index for index in range(expected_count) if index not in labels]
        if missing:
            raise ValueError(
                "Stage block predictions are incomplete: "
                f"missing labels for {len(missing)} indices."
            )

    return dict(sorted(labels.items()))


def compute_block_metrics(gold: dict[int, str], pred: dict[int, str]) -> dict[str, Any]:
    gold_indices = set(gold)
    pred_indices = set(pred)
    if gold_indices != pred_indices:
        missing_in_gold = sorted(pred_indices - gold_indices)
        missing_in_pred = sorted(gold_indices - pred_indices)
        raise ValueError(
            "Gold/pred block index mismatch. "
            f"missing_in_gold={len(missing_in_gold)} missing_in_pred={len(missing_in_pred)}"
        )

    ordered_indices = sorted(gold)
    total_blocks = len(ordered_indices)
    matches = sum(1 for index in ordered_indices if gold[index] == pred[index])
    accuracy = (matches / total_blocks) if total_blocks else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label in FREEFORM_LABELS:
        tp = sum(1 for index in ordered_indices if gold[index] == label and pred[index] == label)
        fp = sum(1 for index in ordered_indices if gold[index] != label and pred[index] == label)
        fn = sum(1 for index in ordered_indices if gold[index] == label and pred[index] != label)
        gold_total = tp + fn
        pred_total = tp + fp
        precision = tp / pred_total if pred_total else 0.0
        recall = tp / gold_total if gold_total else 0.0
        f1 = 0.0
        if precision + recall > 0:
            f1 = (2 * precision * recall) / (precision + recall)

        per_label[label] = {
            "gold_total": gold_total,
            "pred_total": pred_total,
            "gold_matched": tp,
            "pred_matched": tp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "missed_block_indices": [
                index for index in ordered_indices if gold[index] == label and pred[index] != label
            ],
            "false_positive_block_indices": [
                index for index in ordered_indices if gold[index] != label and pred[index] == label
            ],
        }

    macro_labels = [
        label
        for label in FREEFORM_LABELS
        if label != "OTHER"
        and (
            per_label[label]["gold_total"] > 0
            or per_label[label]["pred_total"] > 0
        )
    ]
    macro_f1 = 0.0
    if macro_labels:
        macro_f1 = sum(per_label[label]["f1"] for label in macro_labels) / len(macro_labels)

    worst_label = None
    worst_recall = None
    worst_gold_total = 0
    for label in FREEFORM_LABELS:
        if label == "OTHER":
            continue
        gold_total = int(per_label[label]["gold_total"])
        if gold_total <= 0:
            continue
        recall = float(per_label[label]["recall"])
        if worst_recall is None or recall < worst_recall:
            worst_label = label
            worst_recall = recall
            worst_gold_total = gold_total

    confusion: dict[str, dict[str, int]] = {}
    for index in ordered_indices:
        gold_label = gold[index]
        pred_label = pred[index]
        by_gold = confusion.setdefault(gold_label, {})
        by_gold[pred_label] = int(by_gold.get(pred_label, 0)) + 1

    mismatched_indices = [index for index in ordered_indices if gold[index] != pred[index]]
    missed_gold_blocks = [
        {
            "block_index": index,
            "gold_label": gold[index],
            "pred_label": pred[index],
        }
        for index in mismatched_indices
        if gold[index] != "OTHER"
    ]
    wrong_label_blocks = [
        {
            "block_index": index,
            "gold_label": gold[index],
            "pred_label": pred[index],
        }
        for index in mismatched_indices
    ]

    counts = {
        "gold_total": total_blocks,
        "pred_total": total_blocks,
        "gold_matched": matches,
        "pred_matched": matches,
        "gold_missed": total_blocks - matches,
        "pred_false_positive": total_blocks - matches,
    }

    return {
        "eval_type": "stage_block_classification",
        "labels": list(FREEFORM_LABELS),
        "counts": counts,
        "overall_block_accuracy": accuracy,
        "macro_f1_excluding_other": macro_f1,
        "macro_f1_labels": macro_labels,
        "worst_label_recall": {
            "label": worst_label,
            "recall": worst_recall,
            "gold_total": worst_gold_total,
        },
        "per_label": per_label,
        "confusion": confusion,
        "missed_gold_blocks": missed_gold_blocks,
        "wrong_label_blocks": wrong_label_blocks,
        # Compatibility fields used elsewhere in reports/history.
        "precision": accuracy,
        "recall": accuracy,
        "f1": accuracy,
        "practical_precision": macro_f1,
        "practical_recall": macro_f1,
        "practical_f1": macro_f1,
    }


def _most_common_confusions(
    confusion: dict[str, dict[str, int]],
    *,
    limit: int = 10,
) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for gold_label, by_pred in confusion.items():
        for pred_label, count in by_pred.items():
            if gold_label == pred_label:
                continue
            rows.append((gold_label, pred_label, int(count)))
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows[:limit]


def format_stage_block_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts") or {}
    worst = report.get("worst_label_recall") or {}
    lines = [
        "# Stage Block Evaluation",
        "",
        f"- Overall block accuracy: {float(report.get('overall_block_accuracy', 0.0)):.3f}",
        (
            "- Macro F1 (excluding OTHER): "
            f"{float(report.get('macro_f1_excluding_other', 0.0)):.3f}"
        ),
        (
            "- WORST-LABEL RECALL: "
            f"{worst.get('label') or 'n/a'} "
            f"{float(worst.get('recall') or 0.0):.3f}"
        ),
        "",
        "## Counts",
        "",
        f"- Blocks: {int(counts.get('gold_total') or 0)}",
        f"- Correct: {int(counts.get('gold_matched') or 0)}",
        f"- Mismatched: {int(counts.get('gold_missed') or 0)}",
        "",
        "## Per Label",
        "",
    ]

    per_label = report.get("per_label") or {}
    if isinstance(per_label, dict):
        for label in FREEFORM_LABELS:
            stats = per_label.get(label)
            if not isinstance(stats, dict):
                continue
            lines.append(
                "- "
                f"{label}: "
                f"gold={int(stats.get('gold_total') or 0)} "
                f"pred={int(stats.get('pred_total') or 0)} "
                f"precision={float(stats.get('precision') or 0.0):.3f} "
                f"recall={float(stats.get('recall') or 0.0):.3f} "
                f"f1={float(stats.get('f1') or 0.0):.3f}"
            )

    confusion = report.get("confusion")
    if isinstance(confusion, dict):
        common_confusions = _most_common_confusions(confusion)
        lines.extend(["", "## Most Common Confusions", ""])
        if common_confusions:
            for gold_label, pred_label, count in common_confusions:
                lines.append(f"- {gold_label} -> {pred_label}: {count}")
        else:
            lines.append("- None")

    artifacts = report.get("artifacts")
    if isinstance(artifacts, dict):
        lines.extend(["", "## Debug Pointers", ""])
        if artifacts.get("missed_gold_blocks_jsonl"):
            lines.append(
                "- missed_gold_blocks.jsonl: "
                f"{artifacts.get('missed_gold_blocks_jsonl')}"
            )
        if artifacts.get("wrong_label_blocks_jsonl"):
            lines.append(
                "- wrong_label_blocks.jsonl: "
                f"{artifacts.get('wrong_label_blocks_jsonl')}"
            )
        if artifacts.get("gold_conflicts_jsonl"):
            lines.append(
                "- gold_conflicts.jsonl: "
                f"{artifacts.get('gold_conflicts_jsonl')}"
            )

    lines.append("")
    return "\n".join(lines)


def evaluate_stage_blocks(
    *,
    gold_freeform_jsonl: Path,
    stage_predictions_json: Path,
    extracted_blocks_json: Path,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gold_conflicts_path = out_dir / "gold_conflicts.jsonl"

    gold = load_gold_block_labels(
        gold_freeform_jsonl,
        conflict_output_path=gold_conflicts_path,
    )
    pred = load_stage_block_labels(stage_predictions_json)

    gold_indices = set(gold)
    pred_indices = set(pred)
    missing_gold = sorted(pred_indices - gold_indices)
    extra_gold = sorted(gold_indices - pred_indices)
    if missing_gold or extra_gold:
        mismatch_rows = [
            {
                "error": "gold_pred_block_mismatch",
                "missing_gold_indices": missing_gold,
                "extra_gold_indices": extra_gold,
            }
        ]
        _write_jsonl(gold_conflicts_path, mismatch_rows)
        raise ValueError(
            "Gold/pred block sets differ. "
            f"missing_gold={len(missing_gold)} extra_gold={len(extra_gold)}"
        )

    report = compute_block_metrics(gold, pred)

    stage_payload = json.loads(stage_predictions_json.read_text(encoding="utf-8"))
    workbook_slug = str(stage_payload.get("workbook_slug") or "")
    source_file = str(stage_payload.get("source_file") or "")

    block_texts = _load_extracted_block_texts(extracted_blocks_json)

    wrong_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    for mismatch in report.get("wrong_label_blocks", []):
        if not isinstance(mismatch, dict):
            continue
        block_index = int(mismatch.get("block_index", -1))
        gold_label = str(mismatch.get("gold_label") or "")
        pred_label = str(mismatch.get("pred_label") or "")
        row = {
            "block_index": block_index,
            "gold_label": gold_label,
            "pred_label": pred_label,
            "block_text_excerpt": _excerpt(block_texts.get(block_index, "")),
            "workbook_slug": workbook_slug,
            "source_file": source_file,
        }
        wrong_rows.append(row)
        if gold_label != "OTHER":
            missed_rows.append(dict(row))

    missed_path = out_dir / "missed_gold_blocks.jsonl"
    wrong_path = out_dir / "wrong_label_blocks.jsonl"
    _write_jsonl(missed_path, missed_rows)
    _write_jsonl(wrong_path, wrong_rows)

    # Legacy aliases keep existing bench packet/report tooling functioning.
    legacy_missed = [
        {
            "span_id": f"block:{row['block_index']}",
            "label": row["gold_label"],
            "start_block_index": row["block_index"],
            "end_block_index": row["block_index"],
            "pred_label": row["pred_label"],
        }
        for row in missed_rows
    ]
    legacy_false_positive = [
        {
            "span_id": f"block:{row['block_index']}",
            "label": row["pred_label"],
            "start_block_index": row["block_index"],
            "end_block_index": row["block_index"],
            "gold_label": row["gold_label"],
        }
        for row in wrong_rows
        if row["pred_label"] != "OTHER"
    ]
    _write_jsonl(out_dir / "missed_gold_spans.jsonl", legacy_missed)
    _write_jsonl(out_dir / "false_positive_preds.jsonl", legacy_false_positive)

    report["source"] = {
        "workbook_slug": workbook_slug,
        "source_file": source_file,
        "source_hash": stage_payload.get("source_hash"),
    }
    report["artifacts"] = {
        "eval_report_json": str(out_dir / "eval_report.json"),
        "eval_report_md": str(out_dir / "eval_report.md"),
        "missed_gold_blocks_jsonl": str(missed_path),
        "wrong_label_blocks_jsonl": str(wrong_path),
        "gold_conflicts_jsonl": (
            str(gold_conflicts_path) if gold_conflicts_path.exists() else ""
        ),
    }

    report_json_path = out_dir / "eval_report.json"
    report_md_path = out_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path.write_text(
        format_stage_block_eval_report_md(report),
        encoding="utf-8",
    )

    return {
        "report": report,
        "missed_gold_blocks": missed_rows,
        "wrong_label_blocks": wrong_rows,
        "missed_gold": legacy_missed,
        "false_positive_preds": legacy_false_positive,
    }
