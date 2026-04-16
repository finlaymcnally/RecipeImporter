from __future__ import annotations

import pytest

from cookimport.labelstudio.eval_freeform import (
    LabeledRange,
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
)


def _span(span_id: str, label: str, start: int, end: int) -> LabeledRange:
    return LabeledRange(
        span_id=span_id,
        source_hash="src-hash",
        source_file="book.epub",
        label=label,
        start_row_index=start,
        end_row_index=end,
    )


def test_practical_metrics_surface_granularity_mismatch() -> None:
    gold = [
        _span("g1", "INGREDIENT_LINE", 10, 10),
        _span("g2", "INSTRUCTION_LINE", 30, 30),
        _span("g3", "RECIPE_TITLE", 50, 50),
    ]
    predicted = [
        _span("p1", "INGREDIENT_LINE", 1, 25),
        _span("p2", "INSTRUCTION_LINE", 20, 45),
        _span("p3", "RECIPE_TITLE", 40, 70),
    ]

    result = evaluate_predicted_vs_freeform(predicted, gold, overlap_threshold=0.5)
    report = result["report"]

    assert report["counts"]["gold_matched"] == 0
    assert report["counts"]["pred_matched"] == 0
    assert report["f1"] == pytest.approx(0.0)

    assert report["practical_counts"]["gold_matched"] == 3
    assert report["practical_counts"]["pred_matched"] == 3
    assert report["practical_recall"] == pytest.approx(1.0)
    assert report["practical_precision"] == pytest.approx(1.0)
    assert report["practical_f1"] == pytest.approx(1.0)

    assert report["supported_practical_recall"] == pytest.approx(1.0)
    assert report["supported_practical_precision"] == pytest.approx(1.0)
    assert report["supported_practical_f1"] == pytest.approx(1.0)

    span_width_stats = report["span_width_stats"]
    assert span_width_stats["gold"]["p50"] == pytest.approx(1.0)
    assert span_width_stats["pred"]["p50"] == pytest.approx(26.0)

    mismatch = report["granularity_mismatch"]
    assert mismatch["likely"] is True
    assert mismatch["ratio_p50_pred_to_gold"] >= 4.0


def test_practical_metrics_rendered_in_markdown() -> None:
    gold = [_span("g1", "INGREDIENT_LINE", 10, 10)]
    predicted = [_span("p1", "INGREDIENT_LINE", 1, 25)]

    report = evaluate_predicted_vs_freeform(predicted, gold, overlap_threshold=0.5)["report"]
    report_md = format_freeform_eval_report_md(report)

    assert "Practical / Content overlap (any-overlap):" in report_md
    assert "Strict / Localization (IoU>=0.5):" in report_md
    assert "Granularity mismatch likely:" in report_md
