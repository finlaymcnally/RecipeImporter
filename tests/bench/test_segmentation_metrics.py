from __future__ import annotations

import pytest

from cookimport.bench.segmentation_metrics import (
    Span,
    boundaries_from_runs,
    boundary_prf,
    compute_segmentation_boundaries,
    recipe_split_boundaries,
    runs,
)


def test_runs_and_boundaries_extract_contiguous_spans() -> None:
    labels = [
        "OTHER",
        "INGREDIENT_LINE",
        "INGREDIENT_LINE",
        "OTHER",
        "INGREDIENT_LINE",
    ]

    spans = runs(labels, "INGREDIENT_LINE")
    assert spans == [Span(start=1, end=2), Span(start=4, end=4)]
    assert boundaries_from_runs(spans, "start") == {1, 4}
    assert boundaries_from_runs(spans, "end") == {2, 4}


def test_recipe_split_boundaries_use_recipe_title_run_starts_after_first() -> None:
    labels = [
        "RECIPE_TITLE",
        "OTHER",
        "INGREDIENT_LINE",
        "RECIPE_TITLE",
        "OTHER",
        "RECIPE_TITLE",
    ]

    assert recipe_split_boundaries(labels) == {3, 5}


def test_boundary_prf_counts_exact_and_tolerance_matches() -> None:
    gold = {2, 6}
    pred = {2, 7}

    exact = boundary_prf(gold, pred, tolerance=0, not_applicable_when_gold_empty=False)
    assert exact["tp"] == 1
    assert exact["fp"] == 1
    assert exact["fn"] == 1
    assert exact["precision"] == pytest.approx(0.5)
    assert exact["recall"] == pytest.approx(0.5)
    assert exact["f1"] == pytest.approx(0.5)
    assert exact["missed_gold_boundaries"] == [6]
    assert exact["false_positive_boundaries"] == [7]

    tolerant = boundary_prf(gold, pred, tolerance=1, not_applicable_when_gold_empty=False)
    assert tolerant["tp"] == 2
    assert tolerant["fp"] == 0
    assert tolerant["fn"] == 0
    assert tolerant["precision"] == pytest.approx(1.0)
    assert tolerant["recall"] == pytest.approx(1.0)
    assert tolerant["f1"] == pytest.approx(1.0)


def test_boundary_prf_marks_not_applicable_when_gold_empty() -> None:
    metrics = boundary_prf(set(), {3}, tolerance=0, not_applicable_when_gold_empty=True)
    assert metrics["not_applicable"] is True
    assert metrics["tp"] == 0
    assert metrics["fp"] == 1
    assert metrics["fn"] == 0
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["f1"] is None


def test_compute_segmentation_boundaries_reports_boundary_categories() -> None:
    labels_gold = [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "INSTRUCTION_LINE",
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
    ]
    labels_pred = [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "INSTRUCTION_LINE",
        "INSTRUCTION_LINE",
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
    ]

    segmentation = compute_segmentation_boundaries(
        labels_gold=labels_gold,
        labels_pred=labels_pred,
        tolerance_blocks=0,
    )
    boundaries = segmentation["boundaries"]

    assert boundaries["ingredient_start"]["tp"] == 2
    assert boundaries["ingredient_end"]["tp"] == 1
    assert boundaries["ingredient_end"]["fp"] == 1
    assert boundaries["ingredient_end"]["fn"] == 1
    assert boundaries["instruction_start"]["tp"] == 1
    assert boundaries["instruction_start"]["fp"] == 1
    assert boundaries["instruction_start"]["fn"] == 1
    assert boundaries["recipe_split"]["tp"] == 1
    assert boundaries["overall_micro"]["tp"] == 7
    assert boundaries["overall_micro"]["fp"] == 2
    assert boundaries["overall_micro"]["fn"] == 2
    assert boundaries["overall_micro"]["f1"] == pytest.approx(7 / 9)


def test_compute_segmentation_boundaries_requires_equal_sequence_lengths() -> None:
    with pytest.raises(ValueError, match="equal length"):
        compute_segmentation_boundaries(
            labels_gold=["RECIPE_TITLE"],
            labels_pred=["RECIPE_TITLE", "OTHER"],
            tolerance_blocks=0,
        )
