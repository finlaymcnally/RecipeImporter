"""Tests for the offline benchmark suite (cookimport.bench)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import typer

import cookimport.cli as cli
from cookimport.bench.report import aggregate_metrics, format_suite_report_md
from cookimport.bench.speed_runner import SpeedScenario
from cookimport.bench.speed_suite import SpeedSuite as BenchSpeedSuite, SpeedTarget
from cookimport.bench.quality_suite import (
    QualitySuite as BenchQualitySuite,
    QualityTarget as BenchQualityTarget,
)
from cookimport.bench.noise import consolidate_predictions, dedupe_predictions, gate_noise
from cookimport.bench.cost import estimate_llm_costs, write_escalation_queue


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------


def test_aggregate_metrics_empty():
    agg = aggregate_metrics([])
    assert agg["recall"] == 0.0
    assert agg["precision"] == 0.0
    assert agg["practical_recall"] == 0.0
    assert agg["practical_precision"] == 0.0
    assert agg["practical_f1"] == 0.0
    assert agg["items_evaluated"] == 0


def test_aggregate_metrics_single_item():
    items = [
        {
            "item_id": "item1",
            "report": {
                "counts": {
                    "gold_total": 10,
                    "pred_total": 8,
                    "gold_matched": 7,
                    "pred_matched": 6,
                    "gold_missed": 3,
                    "pred_false_positive": 2,
                },
                "practical_counts": {
                    "gold_total": 10,
                    "pred_total": 8,
                    "gold_matched": 9,
                    "pred_matched": 7,
                    "gold_missed": 1,
                    "pred_false_positive": 1,
                },
                "recall": 0.7,
                "precision": 0.75,
                "practical_recall": 0.9,
                "practical_precision": 0.875,
                "per_label": {
                    "INGREDIENT_LINE": {
                        "gold_total": 5,
                        "pred_total": 4,
                        "gold_matched": 4,
                        "pred_matched": 3,
                    },
                    "INSTRUCTION_LINE": {
                        "gold_total": 5,
                        "pred_total": 4,
                        "gold_matched": 3,
                        "pred_matched": 3,
                    },
                },
            },
        }
    ]
    agg = aggregate_metrics(items)
    assert agg["counts"]["gold_total"] == 10
    assert agg["counts"]["gold_matched"] == 7
    assert agg["recall"] == 0.7
    assert agg["practical_recall"] == 0.9
    assert agg["practical_precision"] == 0.875
    assert agg["practical_f1"] == pytest.approx(
        2 * 0.875 * 0.9 / (0.875 + 0.9)
    )
    assert agg["items_evaluated"] == 1
    assert "INGREDIENT_LINE" in agg["per_label"]


def test_format_suite_report_md():
    agg = {
        "counts": {
            "gold_total": 10,
            "pred_total": 8,
            "gold_matched": 7,
            "pred_matched": 6,
            "gold_missed": 3,
            "pred_false_positive": 2,
        },
        "recall": 0.7,
        "precision": 0.75,
        "f1": 0.724137931,
        "practical_counts": {
            "gold_total": 10,
            "pred_total": 8,
            "gold_matched": 9,
            "pred_matched": 7,
        },
        "practical_recall": 0.9,
        "practical_precision": 0.875,
        "practical_f1": 0.887323944,
        "prediction_density": 0.8,
        "per_label": {},
        "items_evaluated": 1,
    }
    per_item = [
        {
            "item_id": "test",
            "report": {
                "counts": {"gold_matched": 7, "gold_total": 10, "pred_matched": 6, "pred_total": 8},
                "recall": 0.7,
                "precision": 0.75,
            },
        }
    ]
    md = format_suite_report_md(agg, per_item, suite_name="test")
    assert "Bench Suite Report" in md
    assert "test" in md
    assert "Stage-block benchmark metrics" in md
    assert "Macro F1 (excluding OTHER)" in md
    assert "**Practical F1:** 0.887" in md
    assert "**Strict F1:** 0.724" in md

# ---------------------------------------------------------------------------
# Noise reduction
# ---------------------------------------------------------------------------


def test_dedupe_predictions():
    preds = [
        {"source_hash": "h", "source_file": "f", "label": "A", "start_block_index": 0, "end_block_index": 5},
        {"source_hash": "h", "source_file": "f", "label": "A", "start_block_index": 0, "end_block_index": 5},
        {"source_hash": "h", "source_file": "f", "label": "B", "start_block_index": 0, "end_block_index": 5},
    ]
    deduped = dedupe_predictions(preds)
    assert len(deduped) == 2


def test_consolidate_predictions():
    preds = [
        {"label": "A", "start_block_index": 0, "end_block_index": 10},
        {"label": "A", "start_block_index": 2, "end_block_index": 5},
    ]
    result = consolidate_predictions(preds)
    assert len(result) == 1
    # Should keep the smaller span
    assert result[0]["start_block_index"] == 2


def test_gate_noise():
    preds = [
        {"label": "INGREDIENT_LINE"},
        {"label": "OTHER"},
        {"label": "NARRATIVE"},
        {"label": "INSTRUCTION_LINE"},
    ]
    filtered = gate_noise(preds)
    assert len(filtered) == 2
    labels = {p["label"] for p in filtered}
    assert "OTHER" not in labels
    assert "NARRATIVE" not in labels


# ---------------------------------------------------------------------------
# Cost estimator
# ---------------------------------------------------------------------------


def test_estimate_llm_costs_empty():
    result = estimate_llm_costs([])
    assert result["total_calls"] == 0
    assert result["estimated_total_cost_usd"] == 0.0


def test_estimate_llm_costs_with_predictions():
    preds = [
        {"start_block_index": 0, "end_block_index": 5},
        {"start_block_index": 10, "end_block_index": 15},
    ]
    result = estimate_llm_costs(preds)
    assert result["total_calls"] == 2
    assert result["estimated_total_tokens"] > 0
    assert result["estimated_total_cost_usd"] > 0


def test_write_escalation_queue(tmp_path: Path):
    preds = [
        {"label": "INGREDIENT_LINE", "text": "1 cup flour"},
        {"label": "OTHER", "text": "Once upon a time"},
    ]
    out = tmp_path / "queue.jsonl"
    write_escalation_queue(preds, out, labels={"INGREDIENT_LINE"})
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "flour" in lines[0]


# ---------------------------------------------------------------------------
# Offline pred-run does not touch LS client
# ---------------------------------------------------------------------------


def test_generate_pred_run_no_ls_env(monkeypatch):
    """generate_pred_run_artifacts should not import or use LS client."""
    import os
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    # Just verify the function is importable and has correct signature
    from cookimport.labelstudio.ingest import generate_pred_run_artifacts
    import inspect
    sig = inspect.signature(generate_pred_run_artifacts)
    params = set(sig.parameters.keys())
    assert "label_studio_url" not in params
    assert "label_studio_api_key" not in params
    assert "path" in params
    assert "output_dir" in params


# ---------------------------------------------------------------------------
# Determinism: aggregate report is stable
# ---------------------------------------------------------------------------


def test_aggregate_metrics_deterministic():
    items = [
        {
            "item_id": "a",
            "report": {
                "counts": {"gold_total": 5, "pred_total": 4, "gold_matched": 3, "pred_matched": 3, "gold_missed": 2, "pred_false_positive": 1},
                "recall": 0.6,
                "precision": 0.75,
                "per_label": {"INGREDIENT_LINE": {"gold_total": 3, "pred_total": 2, "gold_matched": 2, "pred_matched": 2}},
            },
        },
        {
            "item_id": "b",
            "report": {
                "counts": {"gold_total": 5, "pred_total": 6, "gold_matched": 4, "pred_matched": 4, "gold_missed": 1, "pred_false_positive": 2},
                "recall": 0.8,
                "precision": 0.667,
                "per_label": {"INGREDIENT_LINE": {"gold_total": 3, "pred_total": 4, "gold_matched": 3, "pred_matched": 3}},
            },
        },
    ]
    agg1 = aggregate_metrics(items)
    agg2 = aggregate_metrics(items)
    assert agg1 == agg2
