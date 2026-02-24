"""Aggregate metrics and markdown report for bench suite runs."""

from __future__ import annotations

from typing import Any


def aggregate_metrics(per_item_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-item eval results into a suite-level summary."""
    total_gold = 0
    total_pred = 0
    total_gold_matched = 0
    total_pred_matched = 0
    total_gold_missed = 0
    total_pred_fp = 0
    total_practical_gold = 0
    total_practical_pred = 0
    total_practical_gold_matched = 0
    total_practical_pred_matched = 0
    total_supported_practical_gold = 0
    total_supported_practical_pred = 0
    total_supported_practical_gold_matched = 0
    total_supported_practical_pred_matched = 0

    per_label_accum: dict[str, dict[str, int]] = {}

    for item in per_item_results:
        report = item.get("report", {})
        counts = report.get("counts", {})
        practical_counts = report.get("practical_counts") or counts
        supported_practical_counts = report.get("supported_practical_counts") or {}
        total_gold += counts.get("gold_total", 0)
        total_pred += counts.get("pred_total", 0)
        total_gold_matched += counts.get("gold_matched", 0)
        total_pred_matched += counts.get("pred_matched", 0)
        total_gold_missed += counts.get("gold_missed", 0)
        total_pred_fp += counts.get("pred_false_positive", 0)
        total_practical_gold += practical_counts.get("gold_total", 0)
        total_practical_pred += practical_counts.get("pred_total", 0)
        total_practical_gold_matched += practical_counts.get("gold_matched", 0)
        total_practical_pred_matched += practical_counts.get("pred_matched", 0)
        total_supported_practical_gold += supported_practical_counts.get("gold_total", 0)
        total_supported_practical_pred += supported_practical_counts.get("pred_total", 0)
        total_supported_practical_gold_matched += supported_practical_counts.get(
            "gold_matched", 0
        )
        total_supported_practical_pred_matched += supported_practical_counts.get(
            "pred_matched", 0
        )

        for label, stats in report.get("per_label", {}).items():
            if label not in per_label_accum:
                per_label_accum[label] = {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                }
            per_label_accum[label]["gold_total"] += stats.get("gold_total", 0)
            per_label_accum[label]["pred_total"] += stats.get("pred_total", 0)
            per_label_accum[label]["gold_matched"] += stats.get("gold_matched", 0)
            per_label_accum[label]["pred_matched"] += stats.get("pred_matched", 0)

    recall = (total_gold_matched / total_gold) if total_gold else 0.0
    precision = (total_pred_matched / total_pred) if total_pred else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    practical_recall = (
        total_practical_gold_matched / total_practical_gold
        if total_practical_gold
        else 0.0
    )
    practical_precision = (
        total_practical_pred_matched / total_practical_pred
        if total_practical_pred
        else 0.0
    )
    practical_f1 = (
        2 * practical_precision * practical_recall / (practical_precision + practical_recall)
        if (practical_precision + practical_recall) > 0
        else 0.0
    )
    supported_practical_recall = (
        total_supported_practical_gold_matched / total_supported_practical_gold
        if total_supported_practical_gold
        else 0.0
    )
    supported_practical_precision = (
        total_supported_practical_pred_matched / total_supported_practical_pred
        if total_supported_practical_pred
        else 0.0
    )
    supported_practical_f1 = (
        2 * supported_practical_precision * supported_practical_recall
        / (supported_practical_precision + supported_practical_recall)
        if (supported_practical_precision + supported_practical_recall) > 0
        else 0.0
    )
    pred_density = (total_pred / total_gold) if total_gold else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label, accum in sorted(per_label_accum.items()):
        gt = accum["gold_total"]
        pt = accum["pred_total"]
        per_label[label] = {
            **accum,
            "recall": (accum["gold_matched"] / gt) if gt else 0.0,
            "precision": (accum["pred_matched"] / pt) if pt else 0.0,
        }

    return {
        "counts": {
            "gold_total": total_gold,
            "pred_total": total_pred,
            "gold_matched": total_gold_matched,
            "pred_matched": total_pred_matched,
            "gold_missed": total_gold_missed,
            "pred_false_positive": total_pred_fp,
        },
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "practical_counts": {
            "gold_total": total_practical_gold,
            "pred_total": total_practical_pred,
            "gold_matched": total_practical_gold_matched,
            "pred_matched": total_practical_pred_matched,
            "gold_missed": max(0, total_practical_gold - total_practical_gold_matched),
            "pred_false_positive": max(
                0, total_practical_pred - total_practical_pred_matched
            ),
        },
        "practical_recall": practical_recall,
        "practical_precision": practical_precision,
        "practical_f1": practical_f1,
        "supported_practical_counts": {
            "gold_total": total_supported_practical_gold,
            "pred_total": total_supported_practical_pred,
            "gold_matched": total_supported_practical_gold_matched,
            "pred_matched": total_supported_practical_pred_matched,
            "gold_missed": max(
                0, total_supported_practical_gold - total_supported_practical_gold_matched
            ),
            "pred_false_positive": max(
                0, total_supported_practical_pred - total_supported_practical_pred_matched
            ),
        },
        "supported_practical_recall": supported_practical_recall,
        "supported_practical_precision": supported_practical_precision,
        "supported_practical_f1": supported_practical_f1,
        "prediction_density": pred_density,
        "per_label": per_label,
        "items_evaluated": len(per_item_results),
    }


def format_suite_report_md(
    aggregate: dict[str, Any],
    per_item: list[dict[str, Any]],
    *,
    suite_name: str = "",
) -> str:
    """Format an aggregate + per-item report as markdown."""
    counts = aggregate.get("counts", {})
    practical_counts = aggregate.get("practical_counts", {})
    lines = [
        f"# Bench Suite Report{' — ' + suite_name if suite_name else ''}",
        "",
        f"Items evaluated: {aggregate.get('items_evaluated', 0)}",
        f"Gold spans: {counts.get('gold_total', 0)}",
        f"Predicted spans: {counts.get('pred_total', 0)}",
        f"Prediction density: {aggregate.get('prediction_density', 0):.2f} preds/gold",
        "",
        "Practical metrics are content overlap (same label, any overlap).",
        "Strict metrics are localization quality (same label, IoU threshold).",
        "",
        f"**Practical Recall:** {aggregate.get('practical_recall', 0):.3f} "
        f"({practical_counts.get('gold_matched', 0)}/{practical_counts.get('gold_total', 0)})",
        f"**Practical Precision:** {aggregate.get('practical_precision', 0):.3f} "
        f"({practical_counts.get('pred_matched', 0)}/{practical_counts.get('pred_total', 0)})",
        f"**Practical F1:** {aggregate.get('practical_f1', 0):.3f}",
        "",
        f"**Strict Recall:** {aggregate.get('recall', 0):.3f} "
        f"({counts.get('gold_matched', 0)}/{counts.get('gold_total', 0)})",
        f"**Strict Precision:** {aggregate.get('precision', 0):.3f} "
        f"({counts.get('pred_matched', 0)}/{counts.get('pred_total', 0)})",
        f"**Strict F1:** {aggregate.get('f1', 0):.3f}",
        "",
        "## Per-Label Metrics",
        "",
    ]

    for label, stats in sorted(aggregate.get("per_label", {}).items()):
        lines.append(
            f"- **{label}**: recall={stats.get('recall', 0):.3f} "
            f"({stats.get('gold_matched', 0)}/{stats.get('gold_total', 0)}), "
            f"precision={stats.get('precision', 0):.3f} "
            f"({stats.get('pred_matched', 0)}/{stats.get('pred_total', 0)})"
        )

    lines.extend(["", "## Per-Item Summary", ""])
    for item in per_item:
        item_id = item.get("item_id", "?")
        report = item.get("report", {})
        ic = report.get("counts", {})
        requested_extractor = str(item.get("requested_epub_extractor") or "").strip()
        effective_extractor = str(item.get("effective_epub_extractor") or "").strip()
        extractor_note = ""
        if requested_extractor and effective_extractor:
            extractor_note = (
                f", extractor(requested/effective)={requested_extractor}/{effective_extractor}"
            )
        elif effective_extractor:
            extractor_note = f", extractor={effective_extractor}"
        lines.append(
            f"- **{item_id}**: recall={report.get('recall', 0):.3f} "
            f"({ic.get('gold_matched', 0)}/{ic.get('gold_total', 0)}), "
            f"precision={report.get('precision', 0):.3f} "
            f"({ic.get('pred_matched', 0)}/{ic.get('pred_total', 0)}), "
            f"practical_recall={report.get('practical_recall', 0):.3f}, "
            f"practical_precision={report.get('practical_precision', 0):.3f}"
            f"{extractor_note}"
        )

    lines.append("")
    return "\n".join(lines)
