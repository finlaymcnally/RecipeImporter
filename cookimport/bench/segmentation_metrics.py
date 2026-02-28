from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def runs(labels: list[str], target_label: str) -> list[Span]:
    spans: list[Span] = []
    run_start: int | None = None

    for index, label in enumerate(labels):
        if label == target_label:
            if run_start is None:
                run_start = index
            continue
        if run_start is not None:
            spans.append(Span(start=run_start, end=index - 1))
            run_start = None

    if run_start is not None:
        spans.append(Span(start=run_start, end=len(labels) - 1))
    return spans


def boundaries_from_runs(spans: list[Span], which: Literal["start", "end"]) -> set[int]:
    if which == "start":
        return {span.start for span in spans}
    if which == "end":
        return {span.end for span in spans}
    raise ValueError(f"Unsupported boundary selector: {which!r}")


def recipe_split_boundaries(labels: list[str]) -> set[int]:
    title_runs = runs(labels, "RECIPE_TITLE")
    if len(title_runs) <= 1:
        return set()
    return {span.start for span in title_runs[1:]}


def _validate_tolerance(tolerance: int) -> int:
    if tolerance < 0:
        raise ValueError("Boundary tolerance must be >= 0.")
    return int(tolerance)


def _match_boundaries(
    *,
    gold_boundaries: set[int],
    pred_boundaries: set[int],
    tolerance: int,
) -> tuple[list[dict[str, int]], set[int], set[int]]:
    unmatched_gold = set(gold_boundaries)
    unmatched_pred = set(pred_boundaries)
    matches: list[dict[str, int]] = []

    for pred_boundary in sorted(pred_boundaries):
        candidates = [
            gold_boundary
            for gold_boundary in unmatched_gold
            if abs(gold_boundary - pred_boundary) <= tolerance
        ]
        if not candidates:
            continue
        matched_gold = min(
            candidates,
            key=lambda gold_boundary: (abs(gold_boundary - pred_boundary), gold_boundary),
        )
        unmatched_gold.discard(matched_gold)
        unmatched_pred.discard(pred_boundary)
        matches.append(
            {
                "gold": matched_gold,
                "pred": pred_boundary,
                "distance_blocks": abs(matched_gold - pred_boundary),
            }
        )
    return matches, unmatched_gold, unmatched_pred


def _compute_prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision_denominator = tp + fp
    recall_denominator = tp + fn
    precision = (tp / precision_denominator) if precision_denominator > 0 else 0.0
    recall = (tp / recall_denominator) if recall_denominator > 0 else 0.0
    f1 = 0.0
    if precision + recall > 0:
        f1 = (2.0 * precision * recall) / (precision + recall)
    return precision, recall, f1


def boundary_prf(
    gold: set[int],
    pred: set[int],
    tolerance: int,
    *,
    not_applicable_when_gold_empty: bool,
) -> dict[str, Any]:
    tolerance = _validate_tolerance(tolerance)
    matches, missed_gold, false_positive_pred = _match_boundaries(
        gold_boundaries=gold,
        pred_boundaries=pred,
        tolerance=tolerance,
    )

    tp = len(matches)
    fp = len(false_positive_pred)
    fn = len(missed_gold)
    precision: float | None
    recall: float | None
    f1: float | None
    not_applicable = bool(not_applicable_when_gold_empty and len(gold) == 0)
    if not_applicable:
        precision = None
        recall = None
        f1 = None
    else:
        precision, recall, f1 = _compute_prf(tp, fp, fn)

    return {
        "tolerance_blocks": tolerance,
        "gold_count": len(gold),
        "pred_count": len(pred),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "not_applicable": not_applicable,
        "gold_boundaries": sorted(gold),
        "pred_boundaries": sorted(pred),
        "matched_boundaries": matches,
        "missed_gold_boundaries": sorted(missed_gold),
        "false_positive_boundaries": sorted(false_positive_pred),
    }


def compute_segmentation_boundaries(
    *,
    labels_gold: list[str],
    labels_pred: list[str],
    tolerance_blocks: int,
) -> dict[str, Any]:
    if len(labels_gold) != len(labels_pred):
        raise ValueError(
            "Gold/pred projected label sequences must have equal length for segmentation metrics."
        )
    tolerance_blocks = _validate_tolerance(tolerance_blocks)

    boundary_metrics: dict[str, dict[str, Any]] = {}

    target_specs: tuple[tuple[str, str, Literal["start", "end"]], ...] = (
        ("ingredient_start", "INGREDIENT_LINE", "start"),
        ("ingredient_end", "INGREDIENT_LINE", "end"),
        ("instruction_start", "INSTRUCTION_LINE", "start"),
        ("instruction_end", "INSTRUCTION_LINE", "end"),
    )
    for metric_name, target_label, boundary_selector in target_specs:
        gold_runs = runs(labels_gold, target_label)
        pred_runs = runs(labels_pred, target_label)
        gold_boundaries = boundaries_from_runs(gold_runs, boundary_selector)
        pred_boundaries = boundaries_from_runs(pred_runs, boundary_selector)
        boundary_metrics[metric_name] = boundary_prf(
            gold_boundaries,
            pred_boundaries,
            tolerance_blocks,
            not_applicable_when_gold_empty=True,
        )

    recipe_split_gold = recipe_split_boundaries(labels_gold)
    recipe_split_pred = recipe_split_boundaries(labels_pred)
    boundary_metrics["recipe_split"] = boundary_prf(
        recipe_split_gold,
        recipe_split_pred,
        tolerance_blocks,
        not_applicable_when_gold_empty=True,
    )

    micro_tp = 0
    micro_fp = 0
    micro_fn = 0
    for metric in boundary_metrics.values():
        micro_tp += int(metric.get("tp") or 0)
        micro_fp += int(metric.get("fp") or 0)
        micro_fn += int(metric.get("fn") or 0)
    micro_precision, micro_recall, micro_f1 = _compute_prf(micro_tp, micro_fp, micro_fn)
    boundary_metrics["overall_micro"] = {
        "tolerance_blocks": tolerance_blocks,
        "gold_count": micro_tp + micro_fn,
        "pred_count": micro_tp + micro_fp,
        "tp": micro_tp,
        "fp": micro_fp,
        "fn": micro_fn,
        "precision": micro_precision,
        "recall": micro_recall,
        "f1": micro_f1,
        "not_applicable": False,
    }

    return {
        "boundaries": boundary_metrics,
    }
