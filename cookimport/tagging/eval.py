"""Eval harness for measuring tag suggestion quality against a gold set."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from cookimport.tagging.catalog import TagCatalog
from cookimport.tagging.engine import TagSuggestion

logger = logging.getLogger(__name__)


@dataclass
class CategoryMetrics:
    category_key: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class EvalResult:
    total_recipes: int = 0
    per_category: dict[str, CategoryMetrics] = field(default_factory=dict)

    @property
    def overall_precision(self) -> float:
        tp = sum(m.true_positives for m in self.per_category.values())
        fp = sum(m.false_positives for m in self.per_category.values())
        return tp / (tp + fp) if (tp + fp) > 0 else 1.0

    @property
    def overall_recall(self) -> float:
        tp = sum(m.true_positives for m in self.per_category.values())
        fn = sum(m.false_negatives for m in self.per_category.values())
        return tp / (tp + fn) if (tp + fn) > 0 else 1.0


def evaluate(
    catalog: TagCatalog,
    predictions: dict[str, list[TagSuggestion]],
    gold_labels: dict[str, list[str]],
) -> EvalResult:
    """Compute precision/recall per category.

    Args:
        catalog: The tag catalog (for resolving tag -> category).
        predictions: fixture_id -> list of TagSuggestions.
        gold_labels: fixture_id -> list of expected tag_key_norms.

    Returns:
        EvalResult with per-category and overall metrics.
    """
    result = EvalResult(total_recipes=len(gold_labels))

    for fixture_id, expected_keys in gold_labels.items():
        predicted = predictions.get(fixture_id, [])
        predicted_keys = {s.tag_key for s in predicted}
        expected_set = set(expected_keys)

        # Group by category for metrics
        all_keys = predicted_keys | expected_set
        for key in all_keys:
            cat_key = catalog.category_key_for_tag(key)
            if cat_key is None:
                cat_key = "__unknown__"

            if cat_key not in result.per_category:
                result.per_category[cat_key] = CategoryMetrics(category_key=cat_key)

            metrics = result.per_category[cat_key]
            in_predicted = key in predicted_keys
            in_expected = key in expected_set

            if in_predicted and in_expected:
                metrics.true_positives += 1
            elif in_predicted and not in_expected:
                metrics.false_positives += 1
            elif not in_predicted and in_expected:
                metrics.false_negatives += 1

    return result


def load_gold_labels(path: Path) -> dict[str, list[str]]:
    """Load gold labels from a JSON file: {fixture_id: [tag_key_norm, ...]}."""
    with open(path) as f:
        data = json.load(f)
    return {k: v for k, v in data.items()}


def format_eval_report(result: EvalResult) -> str:
    """Format eval results as human-readable text."""
    lines = [
        f"Eval: {result.total_recipes} recipes",
        f"Overall precision: {result.overall_precision:.2%}",
        f"Overall recall: {result.overall_recall:.2%}",
        "",
        "Per-category:",
    ]
    for cat_key in sorted(result.per_category):
        m = result.per_category[cat_key]
        lines.append(
            f"  {cat_key}: P={m.precision:.2%} R={m.recall:.2%} F1={m.f1:.2%} "
            f"(TP={m.true_positives} FP={m.false_positives} FN={m.false_negatives})"
        )
    return "\n".join(lines)
