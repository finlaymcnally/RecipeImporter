from __future__ import annotations

from typing import Any

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)


def _coerce_gold_label_set(raw: Any, *, item_index: int) -> set[str]:
    if isinstance(raw, str):
        items: list[Any] = [raw]
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        raise ValueError(
            "Gold label payload must be a label string or label collection; "
            f"item_index={item_index} got {type(raw).__name__}."
        )

    labels: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        normalized = normalize_freeform_label(value)
        if normalized not in _FREEFORM_LABEL_SET:
            raise ValueError(f"Unsupported freeform label in gold payload: {value!r}")
        labels.add(normalized)

    if not labels:
        raise ValueError(f"Gold item {item_index} has no usable labels.")
    return labels


def _primary_gold_label(labels: set[str], *, pred_label: str | None = None) -> str:
    if pred_label and pred_label in labels:
        return pred_label
    for label in FREEFORM_LABELS:
        if label in labels:
            return label
    return sorted(labels)[0]


def compute_label_metrics(
    gold: dict[int, str | list[str] | tuple[str, ...] | set[str]],
    pred: dict[int, str],
) -> dict[str, Any]:
    gold_sets: dict[int, set[str]] = {}
    for raw_index, raw_labels in gold.items():
        try:
            item_index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid gold item index: {raw_index!r}") from None
        gold_sets[item_index] = _coerce_gold_label_set(
            raw_labels,
            item_index=item_index,
        )

    gold_indices = set(gold_sets)
    pred_indices = set(pred)
    if gold_indices != pred_indices:
        missing_in_gold = sorted(pred_indices - gold_indices)
        missing_in_pred = sorted(gold_indices - pred_indices)
        raise ValueError(
            "Gold/pred item index mismatch. "
            f"missing_in_gold={len(missing_in_gold)} missing_in_pred={len(missing_in_pred)}"
        )

    ordered_indices = sorted(gold_sets)
    total_items = len(ordered_indices)
    matches = sum(1 for index in ordered_indices if pred[index] in gold_sets[index])
    accuracy = (matches / total_items) if total_items else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label in FREEFORM_LABELS:
        tp = sum(
            1
            for index in ordered_indices
            if label in gold_sets[index] and pred[index] == label
        )
        fp = sum(
            1
            for index in ordered_indices
            if label not in gold_sets[index] and pred[index] == label
        )
        fn = sum(
            1
            for index in ordered_indices
            if label in gold_sets[index] and pred[index] != label
        )
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
            "missed_item_indices": [
                index
                for index in ordered_indices
                if label in gold_sets[index] and pred[index] != label
            ],
            "false_positive_item_indices": [
                index
                for index in ordered_indices
                if label not in gold_sets[index] and pred[index] == label
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
    effective_gold: dict[int, str] = {
        index: _primary_gold_label(gold_sets[index], pred_label=pred[index])
        for index in ordered_indices
    }
    for index in ordered_indices:
        gold_label = effective_gold[index]
        pred_label = pred[index]
        by_gold = confusion.setdefault(gold_label, {})
        by_gold[pred_label] = int(by_gold.get(pred_label, 0)) + 1

    counts = {
        "gold_total": total_items,
        "pred_total": total_items,
        "gold_matched": matches,
        "pred_matched": matches,
        "gold_missed": total_items - matches,
        "pred_false_positive": total_items - matches,
    }

    return {
        "labels": list(FREEFORM_LABELS),
        "counts": counts,
        "strict_accuracy": accuracy,
        "overall_accuracy": accuracy,
        "macro_f1_excluding_other": macro_f1,
        "macro_f1_labels": macro_labels,
        "worst_label_recall": {
            "label": worst_label,
            "recall": worst_recall,
            "gold_total": worst_gold_total,
        },
        "per_label": per_label,
        "confusion": confusion,
    }
