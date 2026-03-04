"""Tests for the stats-dashboard feature: schema, collectors, renderer."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from cookimport.analytics.dashboard_schema import (
    BenchmarkLabelMetrics,
    BenchmarkRecord,
    DashboardData,
    DashboardSummary,
    RunCategory,
    StageRecord,
)
from cookimport.analytics.dashboard_collect import collect_dashboard_data
from cookimport.analytics.dashboard_render import render_dashboard
from cookimport.analytics.perf_report import (
    append_benchmark_csv,
    append_history_csv,
    backfill_benchmark_history_csv,
    history_path,
    _CSV_FIELDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_csv_row(values: dict[str, str]) -> str:
    row = {field: "" for field in _CSV_FIELDS}
    row.update(values)
    return ",".join(str(row[field]) for field in _CSV_FIELDS)


SAMPLE_CSV_HEADER = ",".join(_CSV_FIELDS)

SAMPLE_CSV_ROW1 = _sample_csv_row(
    {
        "run_timestamp": "2026-02-10T10:00:00",
        "run_dir": "data/output/2026-02-10_10.00.00",
        "file_name": "cookbook_a.xlsx",
        "report_path": "data/output/2026-02-10_10.00.00/cookbook_a.excel_import_report.json",
        "total_seconds": "5.5",
        "parsing_seconds": "1.2",
        "writing_seconds": "3.8",
        "ocr_seconds": "0.0",
        "recipes": "20",
        "tips": "5",
        "tip_candidates": "3",
        "topic_candidates": "2",
        "total_units": "30",
        "per_recipe_seconds": "0.275",
        "per_tip_seconds": "1.1",
        "per_tip_candidate_seconds": "1.833",
        "per_topic_candidate_seconds": "2.75",
        "per_unit_seconds": "0.183",
        "output_files": "10",
        "output_bytes": "50000",
        "knowledge_share": "0.066",
        "dominant_stage": "writing",
        "dominant_stage_seconds": "3.8",
        "dominant_checkpoint": "write_final_seconds",
        "dominant_checkpoint_seconds": "3.5",
        "run_category": "stage_import",
    }
)

SAMPLE_CSV_ROW2 = _sample_csv_row(
    {
        "run_timestamp": "2026-02-11T14:30:00",
        "run_dir": "data/output/2026-02-11_14.30.00",
        "file_name": "cookbook_b.epub",
        "report_path": "data/output/2026-02-11_14.30.00/cookbook_b.excel_import_report.json",
        "importer_name": "epub",
        "total_seconds": "12.3",
        "parsing_seconds": "4.5",
        "writing_seconds": "6.1",
        "ocr_seconds": "1.7",
        "recipes": "50",
        "tips": "10",
        "tip_candidates": "8",
        "topic_candidates": "5",
        "total_units": "73",
        "per_recipe_seconds": "0.246",
        "per_tip_seconds": "1.23",
        "per_tip_candidate_seconds": "1.5375",
        "per_topic_candidate_seconds": "2.46",
        "per_unit_seconds": "0.168",
        "output_files": "25",
        "output_bytes": "120000",
        "knowledge_share": "0.068",
        "dominant_stage": "writing",
        "dominant_stage_seconds": "6.1",
        "dominant_checkpoint": "write_final_seconds",
        "dominant_checkpoint_seconds": "5.8",
        "run_category": "stage_import",
    }
)

SAMPLE_CSV_BENCH_ROW = _sample_csv_row(
    {
        "run_timestamp": "2026-02-11T16:00:00",
        "run_dir": "data/golden/eval-vs-pipeline/2026-02-11_16.00.00",
        "file_name": "my_book.pdf",
        "run_category": "benchmark_eval",
        "eval_scope": "freeform-spans",
        "precision": "0.05",
        "recall": "0.25",
        "f1": "0.08333333333333333",
        "practical_precision": "0.70",
        "practical_recall": "0.85",
        "practical_f1": "0.767741935483871",
        "gold_total": "100",
        "gold_recipe_headers": "11",
        "gold_matched": "25",
        "pred_total": "500",
        "supported_precision": "0.08",
        "supported_recall": "0.55",
        "supported_practical_precision": "0.72",
        "supported_practical_recall": "0.88",
        "supported_practical_f1": "0.7919999999999999",
        "granularity_mismatch_likely": "1",
        "pred_width_p50": "28",
        "gold_width_p50": "1",
        "boundary_correct": "10",
        "boundary_over": "8",
        "boundary_under": "5",
        "boundary_partial": "2",
        "tokens_input": "1234",
        "tokens_cached_input": "234",
        "tokens_output": "345",
        "tokens_reasoning": "12",
        "tokens_total": "1591",
    }
)


SAMPLE_REPORT_JSON = {
    "runTimestamp": "2026-02-12T09:00:00",
    "sourceFile": "test_book.pdf",
    "importerName": "pdf",
    "totalRecipes": 15,
    "totalTips": 3,
    "totalTipCandidates": 2,
    "totalTopicCandidates": 1,
    "warnings": ["low confidence on sheet 2"],
    "errors": [],
    "timing": {
        "total_seconds": 8.0,
        "parsing_seconds": 3.0,
        "writing_seconds": 4.5,
        "ocr_seconds": 0.5,
        "checkpoints": {"write_final_seconds": 4.0},
    },
    "outputStats": {
        "files": {
            "total": {"count": 8, "bytes": 45000},
        },
    },
    "runConfig": {
        "epub_extractor": "beautifulsoup",
        "epub_extractor_requested": "beautifulsoup",
        "epub_extractor_effective": "beautifulsoup",
        "ocr_device": "auto",
        "ocr_batch_size": 1,
        "effective_workers": 10,
    },
    "runConfigHash": "abc123def456",
    "runConfigSummary": "epub_extractor=beautifulsoup | ocr_device=auto | ocr_batch_size=1 | effective_workers=10",
}


SAMPLE_EVAL_REPORT = {
    "precision": 0.05,
    "recall": 0.25,
    "f1": 0.08333333333333333,
    "practical_precision": 0.7,
    "practical_recall": 0.85,
    "practical_f1": 0.767741935483871,
    "supported_practical_precision": 0.72,
    "supported_practical_recall": 0.88,
    "supported_practical_f1": 0.792,
    "span_width_stats": {
        "gold": {"min": 1, "p50": 1, "p90": 2, "max": 4, "avg": 1.2},
        "pred": {"min": 3, "p50": 28, "p90": 45, "max": 60, "avg": 24.5},
    },
    "granularity_mismatch": {
        "likely": True,
        "reason": "Strict IoU is near zero while practical overlap is high.",
        "ratio_p50_pred_to_gold": 28.0,
    },
    "counts": {
        "gold_total": 100,
        "gold_matched": 25,
        "gold_missed": 75,
        "pred_total": 500,
        "pred_matched": 25,
        "pred_false_positive": 475,
    },
    "recipe_counts": {
        "gold_recipe_headers": 11,
        "predicted_recipe_count": 14,
    },
    "per_label": {
        "RECIPE_TITLE": {
            "precision": 0.1,
            "recall": 0.4,
            "gold_total": 30,
            "pred_total": 120,
        },
        "INGREDIENT_LINE": {
            "precision": 0.03,
            "recall": 0.2,
            "gold_total": 70,
            "pred_total": 380,
        },
    },
    "boundary": {
        "correct": 10,
        "over": 8,
        "under": 5,
        "partial": 2,
    },
    "app_aligned": {
        "supported_labels_relaxed": {
            "precision": 0.08,
            "recall": 0.55,
        }
    },
}


def _write_csv(tmp_path: Path) -> Path:
    """Create a small performance_history.csv fixture."""
    history_dir = tmp_path / "output" / ".history"
    history_dir.mkdir(parents=True)
    csv_path = history_dir / "performance_history.csv"
    csv_path.write_text(
        SAMPLE_CSV_HEADER + "\n" + SAMPLE_CSV_ROW1 + "\n" + SAMPLE_CSV_ROW2 + "\n",
        encoding="utf-8",
    )
    return csv_path


def _write_report_json(tmp_path: Path) -> Path:
    """Create a conversion report JSON in a timestamp folder."""
    run_dir = tmp_path / "output" / "2026-02-12_09.00.00"
    run_dir.mkdir(parents=True)
    report_path = run_dir / "test_book.excel_import_report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT_JSON), encoding="utf-8")
    return report_path


def _write_eval_report(tmp_path: Path) -> Path:
    """Create a benchmark eval fixture."""
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_00.30.00"
    eval_dir.mkdir(parents=True)
    eval_path = eval_dir / "eval_report.json"
    eval_path.write_text(json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8")
    return eval_path


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_dashboard_data_minimal(self):
        d = DashboardData()
        assert d.schema_version == "12"
        assert d.stage_records == []
        assert d.benchmark_records == []

    def test_stage_record_from_dict(self):
        r = StageRecord(
            file_name="test.xlsx",
            recipes=10,
            total_seconds=5.0,
            per_recipe_seconds=0.5,
        )
        assert r.run_category == RunCategory.stage_import
        assert r.per_recipe_seconds == 0.5

    def test_benchmark_record_f1(self):
        r = BenchmarkRecord(precision=0.5, recall=0.5)
        # F1 is not computed automatically in the schema; the collector does it
        assert r.f1 is None

    def test_optional_fields_are_none(self):
        r = StageRecord(file_name="x")
        assert r.total_seconds is None
        assert r.recipes is None
        assert r.warnings_count is None
        assert r.run_config is None
        assert r.run_config_warning is None


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------

class TestCollectors:
    def test_csv_collector(self, tmp_path):
        _write_csv(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 2
        r0 = data.stage_records[0]
        assert r0.file_name == "cookbook_a.xlsx"
        assert r0.recipes == 20
        assert r0.total_seconds == 5.5
        assert r0.run_category == RunCategory.stage_import

    def test_csv_collector_derived_fields(self, tmp_path):
        _write_csv(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        r1 = data.stage_records[1]
        assert r1.per_recipe_seconds == pytest.approx(0.246)
        assert r1.total_units == 73

    def test_report_json_fallback(self, tmp_path):
        _write_report_json(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_reports=True,
        )
        # No CSV, so falls through to report scanning
        assert len(data.stage_records) == 1
        r = data.stage_records[0]
        assert r.file_name == "test_book.pdf"
        assert r.recipes == 15
        assert r.warnings_count == 1
        assert r.errors_count == 0
        assert r.run_config == {
            "epub_extractor": "beautifulsoup",
            "epub_extractor_requested": "beautifulsoup",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.epub_extractor_requested is None
        assert r.epub_extractor_effective is None
        assert r.run_config_hash == "abc123def456"
        assert "epub_extractor=beautifulsoup" in str(r.run_config_summary)

    def test_csv_collector_stage_run_config_json(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T11:00:00",
                "run_dir": str(tmp_path / "output" / "2026-02-12_11.00.00"),
                "file_name": "book.epub",
                "importer_name": "epub",
                "run_category": "stage_import",
                "total_seconds": "9.5",
                "recipes": "4",
                "epub_extractor_requested": "auto",
                "epub_extractor_effective": "beautifulsoup",
                "run_config_json": json.dumps(
                    {
                        "epub_extractor": "auto",
                        "epub_extractor_requested": "auto",
                        "epub_extractor_effective": "beautifulsoup",
                        "ocr_device": "auto",
                        "ocr_batch_size": 1,
                        "effective_workers": 10,
                    }
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        r = data.stage_records[0]
        assert r.file_name == "book.epub"
        assert r.importer_name == "epub"
        assert r.run_config == {
            "epub_extractor": "auto",
            "epub_extractor_requested": "auto",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.epub_extractor_requested == "auto"
        assert r.epub_extractor_effective == "beautifulsoup"
        assert r.run_config_hash is not None
        assert "epub_extractor=auto" in str(r.run_config_summary)

    def test_csv_collector_stage_run_config_fallback_from_report(self, tmp_path):
        report_path = _write_report_json(tmp_path)
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"

        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T09:00:00",
                "run_dir": str(report_path.parent),
                "file_name": "test_book.pdf",
                "report_path": str(report_path),
                "run_category": "stage_import",
                "total_seconds": "8.0",
                "recipes": "15",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].run_config == {
            "epub_extractor": "beautifulsoup",
            "epub_extractor_requested": "beautifulsoup",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert data.stage_records[0].epub_extractor_requested is None
        assert data.stage_records[0].epub_extractor_effective is None
        assert data.stage_records[0].run_config_hash == "abc123def456"
        assert "epub_extractor=beautifulsoup" in str(data.stage_records[0].run_config_summary)

    def test_csv_collector_stage_run_config_warning_when_report_missing(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"

        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T09:00:00",
                "run_dir": str(tmp_path / "output" / "2026-02-12_09.00.00"),
                "file_name": "test_book.pdf",
                "report_path": str(
                    tmp_path / "output" / "2026-02-12_09.00.00"
                    / "test_book.excel_import_report.json"
                ),
                "run_category": "stage_import",
                "total_seconds": "8.0",
                "recipes": "15",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].run_config is None
        assert data.stage_records[0].run_config_warning == "missing report (stale row)"

    def test_benchmark_collector(self, tmp_path):
        _write_eval_report(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.precision == pytest.approx(0.05)
        assert b.recall == pytest.approx(0.25)
        assert b.f1 is not None  # computed by collector
        assert b.practical_precision == pytest.approx(0.7)
        assert b.practical_recall == pytest.approx(0.85)
        assert b.practical_f1 == pytest.approx(0.767741935483871)
        assert b.gold_total == 100
        assert b.gold_recipe_headers == 11
        assert b.boundary_correct == 10
        assert len(b.per_label) == 2
        assert b.supported_recall == pytest.approx(0.55)
        assert b.supported_practical_recall == pytest.approx(0.88)
        assert b.granularity_mismatch_likely is True
        assert b.pred_width_p50 == pytest.approx(28.0)
        assert b.gold_width_p50 == pytest.approx(1.0)

    def test_benchmark_collector_includes_nested_all_method_eval_reports(self, tmp_path):
        run_ts = "2026-02-23_16.01.06"
        all_method_root = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / run_ts
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        config_a = all_method_root / "config_001_aaa"
        config_b = all_method_root / "config_002_bbb"
        config_a.mkdir(parents=True)
        config_b.mkdir(parents=True)
        (config_a / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        report_b = dict(SAMPLE_EVAL_REPORT)
        report_b["precision"] = 0.11
        report_b["recall"] = 0.31
        report_b["f1"] = 0.16238095238095238
        (config_b / "eval_report.json").write_text(
            json.dumps(report_b),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 2
        assert {r.run_timestamp for r in data.benchmark_records} == {run_ts}
        assert all(
            "all-method-benchmark/thefoodlabcutdown/config_" in str(r.artifact_dir)
            for r in data.benchmark_records
        )

    def test_benchmark_collector_includes_nested_single_offline_variant_eval_reports(
        self,
        tmp_path,
    ):
        run_ts = "2026-03-02_12.34.56"
        single_offline_root = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / run_ts
            / "single-offline-benchmark"
        )
        vanilla_dir = single_offline_root / "vanilla"
        codex_dir = single_offline_root / "codexfarm"
        vanilla_dir.mkdir(parents=True)
        codex_dir.mkdir(parents=True)
        (vanilla_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        codex_report = dict(SAMPLE_EVAL_REPORT)
        codex_report["precision"] = 0.11
        codex_report["recall"] = 0.31
        codex_report["f1"] = 0.16238095238095238
        (codex_dir / "eval_report.json").write_text(
            json.dumps(codex_report),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        records = [
            r
            for r in data.benchmark_records
            if "single-offline-benchmark/" in str(r.artifact_dir)
        ]
        assert len(records) == 2
        assert {r.run_timestamp for r in records} == {run_ts}
        assert {Path(str(r.artifact_dir)).name for r in records} == {"vanilla", "codexfarm"}

    def test_benchmark_collector_normalizes_suffixed_run_dir_timestamps(self, tmp_path):
        run_dir_name = "2026-02-28_02.03.18_manual-top5-thefoodlab-all-matched"
        normalized_ts = "2026-02-28_02.03.18"
        all_method_root = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / run_dir_name
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        config_a = all_method_root / "config_001_aaa"
        config_b = all_method_root / "config_002_bbb"
        config_a.mkdir(parents=True)
        config_b.mkdir(parents=True)
        (config_a / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        (config_b / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        records = [
            r
            for r in data.benchmark_records
            if "all-method-benchmark/thefoodlabcutdown/config_" in str(r.artifact_dir)
        ]
        assert len(records) == 2
        assert {r.run_timestamp for r in records} == {normalized_ts}

    def test_csv_collector_benchmark_run_config_columns(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T11:05:00",
                "run_dir": str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_11.05.00"),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.2",
                "recall": "0.4",
                "run_config_hash": "cfg123",
                "run_config_summary": "epub_extractor=beautifulsoup | workers=7",
                "run_config_json": json.dumps({"epub_extractor": "beautifulsoup", "workers": 7}),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config_hash == "cfg123"
        assert record.run_config_summary == "epub_extractor=beautifulsoup | workers=7"
        assert record.run_config == {"epub_extractor": "beautifulsoup", "workers": 7}

    def test_csv_collector_merges_nested_benchmark_history_csv_rows_and_skips_gated_runs(
        self, tmp_path
    ):
        output_root = tmp_path / "output"
        history_dir = output_root / ".history"
        history_dir.mkdir(parents=True)
        primary_csv_path = history_dir / "performance_history.csv"

        primary_row = {field: "" for field in _CSV_FIELDS}
        primary_row.update(
            {
                "run_timestamp": "2026-03-03T01:00:40",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_12.23.20_line-role-gated-foodlab-det-strict"
                ),
                "file_name": "thefoodlabCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.3298",
                "macro_f1_excluding_other": "0.2575",
                "gold_total": "2353",
                "gold_matched": "776",
            }
        )
        with primary_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(primary_row)

        nested_history_dir = (
            output_root
            / "2026-03-03_01.24.28"
            / "single-offline-benchmark"
            / "seaandsmokecutdown"
            / ".history"
        )
        nested_history_dir.mkdir(parents=True)
        nested_csv_path = nested_history_dir / "performance_history.csv"
        nested_row = {field: "" for field in _CSV_FIELDS}
        nested_row.update(
            {
                "run_timestamp": "2026-03-03T01:25:45",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_01.24.28"
                    / "single-offline-benchmark"
                    / "seaandsmokecutdown"
                    / "vanilla"
                ),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.3849",
                "macro_f1_excluding_other": "0.4042",
                "gold_total": "595",
                "gold_matched": "229",
            }
        )
        with nested_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(nested_row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        artifact_dirs = {str(record.artifact_dir) for record in data.benchmark_records}
        assert any(
            "2026-03-03_01.24.28/single-offline-benchmark/seaandsmokecutdown/vanilla"
            in path
            for path in artifact_dirs
        )
        assert all("line-role-gated" not in path for path in artifact_dirs)

    def test_csv_collector_backfills_codex_runtime_from_prediction_run_manifest(
        self, tmp_path
    ):
        output_root = tmp_path / "output"
        history_dir = output_root / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        eval_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_01.24.28"
            / "single-offline-benchmark"
            / "seaandsmokecutdown"
            / "codexfarm"
        )
        pred_run_dir = eval_dir / "prediction-run"
        pred_run_dir.mkdir(parents=True, exist_ok=True)
        (pred_run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(tmp_path / "input" / "SeaAndSmokeCUTDOWN.epub"),
                    "importer_name": "epub",
                    "recipe_count": 19,
                    "run_config": {
                        "llm_recipe_pipeline": "codex-farm-3pass-v1",
                        "workers": 7,
                    },
                    "llm_codex_farm": {
                        "process_runs": {
                            "pass1": {
                                "process_payload": {
                                    "codex_model": "gpt-5.3-codex-spark",
                                    "codex_reasoning_effort": "<default>",
                                }
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        row = {field: "" for field in _CSV_FIELDS}
        row.update(
            {
                "run_timestamp": "2026-03-03T04:28:32",
                "run_dir": str(eval_dir),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.2739",
                "macro_f1_excluding_other": "0.3484",
                "gold_total": "595",
                "gold_matched": "163",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "codex-farm-3pass-v1",
                        "workers": 7,
                    }
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config is not None
        assert record.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert record.run_config.get("codex_farm_reasoning_effort") == "<default>"
        assert "codex_farm_model=gpt-5.3-codex-spark" in str(record.run_config_summary)
        assert "codex_farm_reasoning_effort=<default>" in str(record.run_config_summary)

    def test_csv_collector_keeps_backfilled_ai_effort_rows(self, tmp_path):
        output_root = tmp_path / "output"
        history_dir = output_root / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        row = {field: "" for field in _CSV_FIELDS}
        row.update(
            {
                "run_timestamp": "2026-03-03T01:28:32",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_01.24.28"
                    / "single-offline-benchmark"
                    / "seaandsmokecutdown"
                    / "codexfarm"
                ),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.2739",
                "macro_f1_excluding_other": "0.3484",
                "gold_total": "595",
                "gold_matched": "163",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "codex-farm-3pass-v1",
                        "workers": 7,
                        "codex_farm_model": "gpt-5.3-codex-spark",
                        "codex_farm_reasoning_effort": "high",
                    }
                ),
                "run_config_summary": (
                    "llm_recipe_pipeline=codex-farm-3pass-v1 | workers=7 | "
                    "codex_farm_model=gpt-5.3-codex-spark | "
                    "codex_farm_reasoning_effort=high"
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config is not None
        assert record.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert record.run_config.get("codex_farm_reasoning_effort") == "high"
        assert "codex_farm_reasoning_effort=high" in str(record.run_config_summary)

    def test_benchmark_csv_recipes_backfill_from_processed_report_path(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        processed_report = (
            tmp_path / "output" / "2026-02-16_11.00.00" / "book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(
            json.dumps({"totalRecipes": 23}),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T11:05:00",
                "run_dir": str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_11.05.00"),
                "file_name": "book.epub",
                "report_path": str(processed_report),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.5",
                "recall": "0.6",
                "gold_total": "10",
                "gold_matched": "6",
                "pred_total": "12",
                # Intentionally leave recipes empty to validate report-path backfill.
                "recipes": "",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert data.benchmark_records[0].recipes == 23

    def test_benchmark_collector_prediction_run_manifest_enrichment(self, tmp_path):
        eval_path = _write_eval_report(tmp_path)
        pred_run_dir = eval_path.parent / "prediction-run"
        pred_run_dir.mkdir(parents=True, exist_ok=True)
        processed_report_path = (
            tmp_path / "output" / "2026-02-12_11.22.33" / "book.excel_import_report.json"
        )
        processed_report_path.parent.mkdir(parents=True, exist_ok=True)
        processed_report_path.write_text(
            json.dumps({"totalRecipes": 17}),
            encoding="utf-8",
        )
        (pred_run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "task_count": 42,
                    "recipe_count": 19,
                    "source_file": "/tmp/source/book.epub",
                    "importer_name": "epub",
                    "run_config": {
                        "epub_extractor": "beautifulsoup",
                        "ocr_device": "auto",
                        "workers": 6,
                        "codex_farm_model": None,
                        "codex_farm_reasoning_effort": None,
                    },
                    "llm_codex_farm": {
                        "codex_farm_model": None,
                        "codex_farm_reasoning_effort": None,
                        "process_runs": {
                            "pass1": {
                                "process_payload": {
                                    "codex_model": "gpt-5.3-codex-spark",
                                    "codex_reasoning_effort": None,
                                    "telemetry_report": {
                                        "insights": {
                                            "model_reasoning_breakdown": [
                                                {
                                                    "model": "gpt-5.3-codex-spark",
                                                    "reasoning_effort": "<default>",
                                                }
                                            ]
                                        }
                                    },
                                }
                            }
                        },
                    },
                    "processed_report_path": str(processed_report_path),
                }
            ),
            encoding="utf-8",
        )
        (pred_run_dir / "coverage.json").write_text(
            json.dumps({"extracted_chars": 200, "chunked_chars": 150}),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.task_count == 42
        assert b.source_file == "/tmp/source/book.epub"
        assert b.importer_name == "epub"
        assert b.run_config is not None
        assert b.run_config.get("epub_extractor") == "beautifulsoup"
        assert b.run_config.get("ocr_device") == "auto"
        assert b.run_config.get("workers") == 6
        assert b.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert b.run_config.get("codex_farm_reasoning_effort") == "<default>"
        assert b.processed_report_path == str(processed_report_path)
        assert b.recipes == 19
        assert b.extracted_chars == 200
        assert b.chunked_chars == 150
        assert b.coverage_ratio == pytest.approx(0.75)

    def test_combined_collection(self, tmp_path):
        _write_csv(tmp_path)
        _write_eval_report(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert data.summary.total_stage_records == 2
        assert data.summary.total_benchmark_records == 1
        assert data.summary.total_recipes == 70  # 20 + 50

    def test_mixed_timestamp_formats_sort_by_time_and_summary_latest(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        def _bench_row(ts: str, run_dir: Path, source_file: str) -> str:
            return _sample_csv_row(
                {
                    "run_timestamp": ts,
                    "run_dir": str(run_dir),
                    "file_name": source_file,
                    "run_category": "benchmark_eval",
                    "eval_scope": "freeform-spans",
                    "precision": "0.05",
                    "recall": "0.25",
                    "f1": "0.08333333333333333",
                    "gold_total": "100",
                    "gold_matched": "25",
                    "pred_total": "500",
                    "supported_precision": "0.08",
                    "supported_recall": "0.55",
                    "boundary_correct": "10",
                    "boundary_over": "8",
                    "boundary_under": "5",
                    "boundary_partial": "2",
                }
            )

        older_ts = "2026-02-15_23.25.45"
        newer_ts = "2026-02-15T23:59:24"
        older_dir = tmp_path / "golden" / "eval-vs-pipeline" / older_ts
        newer_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-15_23.59.24"
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + _bench_row(newer_ts, newer_dir, "book_newer.epub") + "\n"
            + _bench_row(older_ts, older_dir, "book_older.epub") + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert [r.run_timestamp for r in data.benchmark_records] == [older_ts, newer_ts]
        assert data.summary.latest_benchmark_timestamp == newer_ts

    def test_csv_benchmark_rows_skip_pytest_temp_eval_artifacts(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        def _bench_row(ts: str, run_dir: Path, source_file: str) -> str:
            return _sample_csv_row(
                {
                    "run_timestamp": ts,
                    "run_dir": str(run_dir),
                    "file_name": source_file,
                    "run_category": "benchmark_eval",
                    "eval_scope": "freeform-spans",
                    "precision": "0.05",
                    "recall": "0.25",
                    "f1": "0.08333333333333333",
                    "gold_total": "100",
                    "gold_matched": "25",
                    "pred_total": "500",
                    "supported_precision": "0.08",
                    "supported_recall": "0.55",
                    "boundary_correct": "10",
                    "boundary_over": "8",
                    "boundary_under": "5",
                    "boundary_partial": "2",
                }
            )

        keep_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_00.04.14"
        skip_dir = tmp_path / "pytest-46" / "test_labelstudio_benchmark_pas0" / "eval"

        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + _bench_row("2026-02-16_00.04.14", keep_dir, "keep.epub") + "\n"
            + _bench_row("2026-02-15T23:59:24", skip_dir, "book.epub") + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert data.benchmark_records[0].source_file == "keep.epub"

    def test_benchmark_scan_rows_skip_gated_eval_artifacts(self, tmp_path):
        keep_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_01.24.28"
            / "single-offline-benchmark"
            / "seaandsmokecutdown"
            / "vanilla"
        )
        skip_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
            / "single-offline-benchmark"
            / "thefoodlabcutdown"
            / "codexfarm"
        )
        keep_dir.mkdir(parents=True, exist_ok=True)
        skip_dir.mkdir(parents=True, exist_ok=True)
        (keep_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        (skip_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert "line-role-gated" not in str(data.benchmark_records[0].artifact_dir)

    def test_empty_roots(self, tmp_path):
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 0
        assert len(data.benchmark_records) == 0

    def test_malformed_json_skipped(self, tmp_path):
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_01.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text("{bad json", encoding="utf-8")

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 0
        assert len(data.collector_warnings) > 0

    def test_job_parts_ignored(self, tmp_path):
        # .job_parts directory should never be scanned
        parts_dir = tmp_path / "output" / ".job_parts" / "test" / "job_0"
        parts_dir.mkdir(parents=True)
        (parts_dir / "test.excel_import_report.json").write_text(
            json.dumps(SAMPLE_REPORT_JSON), encoding="utf-8"
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_reports=True,
        )
        assert len(data.stage_records) == 0

    def test_prediction_run_excluded(self, tmp_path):
        pred_dir = (
            tmp_path / "golden" / "eval-vs-pipeline"
            / "2026-02-11_01.00.00" / "prediction-run"
        )
        pred_dir.mkdir(parents=True)
        (pred_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 0


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

class TestRenderer:
    def test_render_produces_files(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="a.xlsx", recipes=10, total_seconds=2.0),
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=10),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        assert html_path.exists()
        assert (tmp_path / "dash" / "assets" / "dashboard_data.json").exists()
        assert (tmp_path / "dash" / "assets" / "dashboard_ui_state.json").exists()
        assert (tmp_path / "dash" / "assets" / "dashboard.js").exists()
        assert (tmp_path / "dash" / "assets" / "style.css").exists()

    def test_render_preserves_existing_program_ui_state(self, tmp_path):
        out_dir = tmp_path / "dash"
        state_path = out_dir / "assets" / "dashboard_ui_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        original_payload = {
            "version": 1,
            "saved_at": "2026-03-03T18:22:00Z",
            "previous_runs": {"visible_columns": ["run_timestamp", "ai_model"]},
        }
        state_path.write_text(json.dumps(original_payload), encoding="utf-8")

        render_dashboard(out_dir, DashboardData())

        persisted_payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted_payload == original_payload

    def test_data_json_validates(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="b.epub", recipes=5),
            ],
            benchmark_records=[
                BenchmarkRecord(
                    precision=0.1,
                    recall=0.3,
                    importer_name="epub",
                    run_config={"epub_extractor": "beautifulsoup", "ocr_device": "auto"},
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)
        raw = json.loads(
            (tmp_path / "dash" / "assets" / "dashboard_data.json").read_text()
        )
        # Verify it round-trips through the schema
        loaded = DashboardData.model_validate(raw)
        assert len(loaded.stage_records) == 1
        assert len(loaded.benchmark_records) == 1

    def test_html_includes_previous_runs_columns(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    artifact_dir="/tmp/eval",
                    strict_accuracy=0.2,
                    macro_f1_excluding_other=0.55,
                    precision=0.1,
                    recall=0.2,
                    practical_f1=0.55,
                    importer_name="epub",
                    source_file="/tmp/source/book.epub",
                    run_config={"epub_extractor": "beautifulsoup", "ocr_device": "auto"},
                ),
            ],
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "Previous Runs" in html
        assert 'id="previous-runs-table"' in html
        assert 'class="previous-runs-header-row"' in html
        assert 'class="previous-runs-active-filters-row"' in html
        assert 'class="previous-runs-filter-spacer-row"' in html
        assert "<th>Timestamp</th>" not in html
        assert "<th>Strict Precision</th>" not in html
        assert "<th>Strict Recall</th>" not in html
        assert "<th>Practical F1</th>" not in html
        assert "<th>Strict F1</th>" not in html
        assert "strict_accuracy" in html
        assert "macro_f1_excluding_other" in html
        assert ">AI Model + Effort<" not in html
        assert "Run Config" not in html
        assert "<th>Artifact</th>" not in html

    def test_html_includes_previous_runs_filter_controls(self, tmp_path):
        html_path = render_dashboard(tmp_path / "dash", DashboardData())
        html = html_path.read_text(encoding="utf-8")
        assert 'id="previous-runs-filter-panel"' not in html
        assert 'id="previous-runs-filter-status"' not in html
        assert 'id="previous-runs-clear-filters"' in html
        assert 'id="previous-runs-columns-toggle"' in html
        assert 'id="previous-runs-columns-popup"' in html
        assert 'id="previous-runs-columns-checklist"' in html
        assert 'id="previous-runs-global-filter-mode"' in html
        assert 'id="previous-runs-column-reset"' in html
        assert 'id="previous-runs-preset-select"' in html
        assert 'id="previous-runs-preset-load"' in html
        assert 'id="previous-runs-preset-save-current"' in html
        assert 'id="previous-runs-preset-delete"' in html
        assert 'id="previous-runs-preset-status"' in html
        assert 'id="isolate-panel"' in html
        assert 'id="isolate-combine"' in html
        assert 'id="isolate-add"' in html
        assert 'id="isolate-clear"' in html
        assert 'id="isolate-rules"' in html
        assert 'id="isolate-status"' in html
        assert 'id="isolate-insights"' in html
        assert 'id="compare-control-panel"' in html
        assert 'id="compare-control-view-mode"' in html
        assert 'id="compare-control-outcome-field"' in html
        assert 'id="compare-control-compare-field"' in html
        assert 'id="compare-control-split-field"' in html
        assert 'id="compare-control-hold-fields"' in html
        assert 'id="compare-control-group-selection"' in html
        assert 'id="compare-control-filter-subset"' in html
        assert 'id="compare-control-clear-selection"' in html
        assert 'id="compare-control-status"' in html
        assert 'id="compare-control-results"' in html
        assert 'id="quick-filters-panel"' in html
        assert 'id="quick-filters-advanced"' not in html
        assert 'id="previous-runs-presets-toggle"' not in html
        assert 'id="previous-runs-presets-popup"' not in html
        assert 'id="quick-filter-exclude-ai-tests"' in html
        assert 'id="quick-filter-official-only"' in html
        assert 'id="previous-runs-clear-all-filters"' in html
        assert 'id="quick-filter-exclude-ai-tests" type="checkbox" checked' not in html
        assert 'id="quick-filter-official-only" type="checkbox" checked' in html
        assert 'id="quick-filters-status"' in html

    def test_dashboard_js_orders_columns_popup_by_visible_order(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const checklistOrder = [...previousRunsVisibleColumns].filter(" in js
        assert "if (!visibleSet.has(fieldName)) {" in js

    def test_dashboard_js_tracks_isolate_table_filter_control_source(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert 'let previousRunsFilterControlSource = "table";' in js
        assert 'let previousRunsColumnFilterGlobalMode = "and";' in js
        assert "Control: isolate synced to table filters." in js
        assert "Control: table filters (isolate rules saved)." in js
        assert "Column combine: " in js
        assert "OR across columns." in js

    def test_dashboard_js_supports_cross_column_or_filter_mode(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function normalizePreviousRunsColumnFilterGlobalMode(value)" in js
        assert "if (topMode === \"or\") {" in js
        assert "return groups.some(matchesGroup);" in js

    def test_dashboard_js_supports_isolate_numeric_operators(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const ISOLATE_OPERATORS_TEXT = [" in js
        assert "const ISOLATE_OPERATORS_NUMERIC = [" in js
        assert '["gt", ">"]' in js
        assert '["gte", ">="]' in js
        assert '["lt", "<"]' in js
        assert '["lte", "<="]' in js
        assert "const COMPARE_CONTROL_VIEW_MODES = new Set(" in js
        assert "function normalizeCompareControlState(rawState)" in js
        assert "function buildCompareControlFieldCatalog(records)" in js
        assert "function chooseDefaultCompareOutcome(catalog)" in js
        assert "function analyzeCompareControlCategoricalRaw(records, outcomeField, compareField)" in js
        assert "function analyzeCompareControlNumericRaw(records, outcomeField, compareField)" in js
        assert "function analyzeCompareControlCategoricalControlled(records, outcomeField, compareField, holdFields)" in js
        assert "function analyzeCompareControlNumericControlled(records, outcomeField, compareField, holdFields)" in js
        assert "function renderCompareControlPanel(context)" in js
        assert "function syncCompareControlSelectionToTableFilters()" in js
        assert 'class="isolate-rule-value isolate-rule-value-input"' in js
        assert "function isolateFieldIsNumeric(records, fieldName)" in js
        assert "function isolateOperatorsForField(fieldInfo)" in js
        assert "function isolateClauseHasActiveSelection(clause)" in js

    def test_html_includes_diagnostics_and_history_frames(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    file_name="book.epub",
                    importer_name="epub",
                    run_config={
                        "epub_extractor": "beautifulsoup",
                        "ocr_device": "auto",
                        "ocr_batch_size": 1,
                        "effective_workers": 10,
                    },
                    total_seconds=12.0,
                    recipes=6,
                    per_recipe_seconds=2.0,
                    artifact_dir="/tmp/output/2026-02-11_16.00.00",
                )
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=6),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "All-Method Benchmark Runs" not in html
        assert "Diagnostics (Latest Benchmark)" in html
        assert 'id="runtime-section"' in html
        assert 'id="per-label-rolling-window-size"' in html
        assert 'id="per-label-comparison-point-value"' in html
        assert 'class="per-label-rolling-group"' in html
        assert 'class="per-label-col-head">Run<br>Precision<br>' in html
        assert 'class="per-label-col-sub">(codexfarm)</span>' in html
        assert 'class="per-label-col-head">Run<br>Recall<br>' in html
        assert 'class="per-label-rolling-window-value">10</span>' in html
        assert 'Rolling <span class="per-label-comparison-mode-value">Delta</span>:' in html
        assert "Point value" in html
        assert "Previous Runs" in html
        assert 'class="table-wrap table-scroll"' in html
        assert "Stage / Import Throughput" not in html
        assert "Benchmark Evaluations" not in html

    def test_html_embeds_inline_data_for_file_scheme(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="local.xlsx", recipes=3, total_seconds=1.5),
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=3),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert 'id="dashboard-data-inline"' in html
        assert "__DASHBOARD_DATA_INLINE__" not in html
        assert '"file_name": "local.xlsx"' in html

    def test_html_includes_highcharts_secondary_cdn_fallback(self, tmp_path):
        html_path = render_dashboard(tmp_path / "dash", DashboardData())
        html = html_path.read_text(encoding="utf-8")
        assert 'src="https://code.highcharts.com/stock/highstock.js"' in html
        assert "if (!window.Highcharts || typeof window.Highcharts.stockChart !== 'function')" in html
        assert "https://cdn.jsdelivr.net/npm/highcharts/highstock.js" in html
        assert 'src="https://code.highcharts.com/highcharts-more.js"' in html
        assert "if (!window.Highcharts || !window.Highcharts.seriesTypes || typeof window.Highcharts.seriesTypes.arearange !== 'function')" in html
        assert "https://cdn.jsdelivr.net/npm/highcharts/highcharts-more.js" in html

    def test_js_uses_timestamp_comparators_for_run_sorting(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-15_23.25.45",
                    artifact_dir="/tmp/eval-older",
                    precision=0.1,
                    recall=0.2,
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-15T23:59:24",
                    artifact_dir="/tmp/eval-newer",
                    precision=0.2,
                    recall=0.3,
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const m = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})[T_](\\d{2})[.:](\\d{2})[.:](\\d{2})(?:_.+)?$/);" in js
        assert "useUTC: false" in js
        assert "const d = new Date(" in js
        assert "Number(m[1])" in js
        assert "function compareRunTimestampAsc(aTs, bTs)" in js
        assert "function compareRunTimestampDesc(aTs, bTs)" in js
        assert "compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)" in js

    def test_js_renders_previous_runs_table_and_links_timestamp_to_artifact(
        self, tmp_path
    ):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function renderPreviousRuns()" in js
        assert 'document.getElementById("previous-runs-section")' in js
        assert 'document.getElementById("previous-runs-table")' in js
        assert "function renderPreviousRunsCell(row, fieldName)" in js
        assert 'const href = row.href || "";' in js
        assert 'const ALL_METHOD_SEGMENT = "all-method-benchmark";' in js
        assert 'let previousRunsSortField = "run_timestamp";' in js
        assert 'let previousRunsSortDirection = "desc";' in js
        assert "function comparePreviousRunsRows(leftRow, rightRow)" in js
        assert "th.addEventListener(\"click\", event => {" in js
        assert "Click to sort A→Z / Z→A." in js
        assert "(?:_.+)?$/.test(text);" in js
        assert "runDirTimestamp: runDirTimestamp || fallbackTimestamp || null," in js
        assert '"all-method-benchmark-run__" + slugToken(ts) + ".html"' in js
        assert "function sourceLabelForRecord(record)" in js
        assert "function sourceSlugFromArtifactPath(pathValue)" in js
        assert "function importerLabelForRecord(record)" in js
        assert "all-method: " in js
        assert "function aiModelEffortLabelForRecord(record)" in js
        assert "function aiModelLabelForRecord(record)" in js
        assert "function aiEffortLabelForRecord(record)" in js
        assert "function benchmarkVariantFromPathOrPipeline(record)" in js
        assert "function rawAiModelForRecord(record)" in js
        assert "function rawAiEffortForRecord(record)" in js
        assert 'const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);' in js
        assert 'if (benchmarkVariantForRecord(record) === "vanilla") return null;' in js
        assert "function previousRunsAllTokenUseDisplay(row)" in js
        assert "function previousRunsAllTokenUseTitle(row)" in js
        assert "function formatTokenCountCompact(value)" in js
        assert "formatTokenCountCompact(parts.total)" in js
        assert "formatTokenCountCompact(parts.input)" in js
        assert "formatTokenCountCompact(parts.output)" in js
        assert 'if (pipelineText === "off") return "off";' in js
        assert "return \"-\";" in js
        assert 'lower === "<default>"' in js
        assert "function renderLatestRuntime()" in js
        assert 'const latestTs = String(preferred[0].run_timestamp || "");' in js
        assert "const latestGroup = preferred.filter(" in js
        assert "const totalTokenUse = formatTokenCountCompact(" in js
        assert "previousRunsDiscountedTokenTotal(" in js
        assert "rawTotalTokenUse" not in js
        assert "AI Runtime" not in js
        assert "'<tr><td>Token use</td><td>' + esc(totalTokenUse) + '</td></tr>'" in js
        assert "Raw total tokens" not in js
        assert "link.href = href;" in js

    def test_js_supports_previous_runs_column_header_filters(
        self, tmp_path
    ):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS = [" in js
        assert "const PREVIOUS_RUNS_UNARY_FILTER_OPERATORS = new Set(" in js
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_MODES = [" in js
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL = Object.fromEntries(" in js
        assert "const PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT = 8;" in js
        assert '"source_label"' in js
        assert '"ai_model"' in js
        assert '"ai_effort"' in js
        assert '"all_token_use"' in js
        assert "let previousRunsQuickFilters = {" in js
        assert "exclude_ai_tests: false" in js
        assert "official_full_golden_only: true" in js
        assert "let previousRunsViewPresets = Object.create(null);" in js
        assert "let previousRunsSelectedPreset = \"\";" in js
        assert "const PREVIOUS_RUNS_PRESET_NAME_MAX = 80;" in js
        assert "const PREVIOUS_RUNS_PRESET_MAX_COUNT = 40;" in js
        assert 'const DASHBOARD_UI_STATE_STORAGE_KEY = "cookimport.stats_dashboard.ui_state.v1";' in js
        assert 'const DASHBOARD_UI_STATE_SERVER_PATH = "assets/dashboard_ui_state.json";' in js
        assert "const DASHBOARD_UI_STATE_SYNC_INTERVAL_MS = 3000;" in js
        assert "function loadDashboardUiState()" in js
        assert "function loadDashboardUiStateFromProgramStore()" in js
        assert "function startDashboardUiProgramSyncLoop()" in js
        assert "function persistDashboardUiState()" in js
        assert "function persistDashboardUiStateToProgramStore(payload)" in js
        assert "function persistDashboardUiStateToBrowserStorage(payload)" in js
        assert "function sanitizePreviousRunsPresetName(rawName)" in js
        assert "function sanitizePreviousRunsPresetState(rawPreset)" in js
        assert "function sanitizePreviousRunsPresetMap(rawPresets)" in js
        assert "compare_control: normalizeCompareControlState(compareControlState)," in js
        assert "function previousRunsPresetNames()" in js
        assert "function renderPreviousRunsPresetEditor()" in js
        assert "function captureCurrentPreviousRunsPresetState()" in js
        assert "function applyPreviousRunsPresetByName(rawName)" in js
        assert "function saveCurrentPreviousRunsViewPreset(rawName)" in js
        assert "function deletePreviousRunsPreset(rawName)" in js
        assert "let dashboardTableColumnWidths = Object.create(null);" in js
        assert "const tableColumnWidths = sanitizeDashboardTableColumnWidths(dashboardTableColumnWidths);" in js
        assert "table_column_widths: tableColumnWidths," in js
        assert "previous_runs_presets: previousRunsPresets," in js
        assert "selected_preset: selectedPresetName," in js
        assert "saved_at: savedAt," in js
        assert "setDashboardTableColumnWidth(previousRunsTableKey, fieldName, nextWidth);" in js
        assert "function setupResizableDashboardTable(table, options)" in js
        assert "function setupResizableDashboardTables()" in js
        assert 'clearDashboardTableColumnWidths("per-label-table");' in js
        assert "tableKey: \"boundary-table\"" not in js
        assert "tableKey: \"runtime-table\"" not in js
        assert "setupResizableDashboardTables();" in js
        assert "window.localStorage" in js
        assert "loadDashboardUiState();" in js
        assert "loadDashboardUiStateFromProgramStore()" in js
        assert "loadDashboardUiStateFromProgramStore({ force: true })" in js
        assert 'fetch(DASHBOARD_UI_STATE_SERVER_PATH, { cache: "no-store" })' in js
        assert "storage.setItem(DASHBOARD_UI_STATE_STORAGE_KEY, JSON.stringify(payload));" in js
        assert 'method: "PUT"' in js
        assert "if (dashboardUiStatePersistSuppressed) return;" in js
        assert "persistDashboardUiState();" in js
        assert "function setupPreviousRunsFilters()" in js
        assert "function setupPreviousRunsQuickFilters()" in js
        assert "function setupCompareControlControls()" in js
        assert "function setupPreviousRunsPresetControls()" in js
        assert "function setPreviousRunsPresetsPopupOpen(nextOpen)" not in js
        assert "function applyPreviousRunsQuickFilters(records, options)" in js
        assert "function isLikelyAiTestBenchmarkRecord(record)" in js
        assert "timestampSuffix = segment.match(" in js
        assert "(manual|smoke|test|debug|quick|probe|sample|trial)" in js
        assert "function isOfficialGoldenBenchmarkRecord(record)" in js
        assert 'if (!path.includes("/benchmark-vs-golden/")) return false;' in js
        assert 'if (!path.includes("/single-offline-benchmark/")) return false;' in js
        assert 'return variant === "vanilla" || variant === "codexfarm";' in js
        assert 'const clearBtn = document.getElementById("previous-runs-clear-filters");' in js
        assert 'const clearAllBtn = document.getElementById("previous-runs-clear-all-filters");' in js
        assert "function clearAllPreviousRunsFilters()" in js
        assert "function collectBenchmarkFieldPaths()" in js
        assert "function normalizePreviousRunsColumnFilterList(rawValue)" in js
        assert "function previousRunsColumnFilterClauses(fieldName)" in js
        assert "function previousRunsColumnFilterMode(fieldName)" in js
        assert "function setPreviousRunsColumnFilterMode(fieldName, mode)" in js
        assert "function addPreviousRunsColumnFilter(fieldName, operator, value)" in js
        assert "function removePreviousRunsColumnFilterAt(fieldName, index)" in js
        assert "function activePreviousRunsColumnFilters()" in js
        assert "function previousRunsIconSvgPath(iconName)" in js
        assert "function setPreviousRunsIcon(button, iconName)" in js
        assert "function formatPreviousRunsColumnFilterSummary(fieldName, filter)" in js
        assert "function formatPreviousRunsColumnFiltersSummary(fieldName, clauses)" in js
        assert "function groupPreviousRunsFiltersByField(filters)" in js
        assert "function recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode)" in js
        assert "function previousRunsRecordsMatchingOtherFilters(excludedField)" in js
        assert "function previousRunsColumnSuggestionCandidates(fieldName, typedText)" in js
        assert "function previousRunsSuggestionScore(typedLower, candidateLower)" in js
        assert '"run_config.model"' in js
        assert "function evaluatePreviousRunsFilterOperator(value, operator, expected)" in js
        assert "function currentPreviousRunsFilterResult()" in js
        assert "const filterResult = currentPreviousRunsFilterResult();" in js
        assert "const PREVIOUS_RUNS_DEFAULT_COLUMNS = [" in js
        assert "const PREVIOUS_RUNS_COLUMN_META = {" in js
        assert "function setupPreviousRunsColumnsControls()" in js
        assert "function renderPreviousRunsTableColumns(table, columns)" in js
        assert "function renderPreviousRunsColumnEditor()" in js
        assert 'const toggleBtn = document.getElementById("previous-runs-presets-toggle");' not in js
        assert 'const popup = document.getElementById("previous-runs-presets-popup");' not in js
        assert 'const presetSelect = document.getElementById("previous-runs-preset-select");' in js
        assert 'const presetLoadBtn = document.getElementById("previous-runs-preset-load");' in js
        assert 'const presetSaveCurrentBtn = document.getElementById("previous-runs-preset-save-current");' in js
        assert 'const presetDeleteBtn = document.getElementById("previous-runs-preset-delete");' in js
        assert 'const filterRow = table.querySelector("thead tr.previous-runs-active-filters-row");' in js
        assert 'const spacerRow = table.querySelector("thead tr.previous-runs-filter-spacer-row");' in js
        assert "let previousRunsOpenFilterField = \"\";" in js
        assert "let previousRunsOpenFilterDraft = null;" in js
        assert "function openPreviousRunsColumnFilterEditor(fieldName)" in js
        assert "function closePreviousRunsColumnFilterEditor()" in js
        assert 'setPreviousRunsIcon(toggleBtn, isEditorOpen ? "minus" : "plus");' in js
        assert 'summaryItem.className = "previous-runs-column-filter-summary-item";' in js
        assert 'summaryRemoveBtn.className = "previous-runs-column-filter-summary-remove";' in js
        assert 'setPreviousRunsIcon(summaryRemoveBtn, "close");' in js
        assert 'popover.className = "previous-runs-column-filter-popover";' in js
        assert 'modeWrap.className = "previous-runs-column-filter-mode";' in js
        assert 'modeButtons.className = "previous-runs-column-filter-mode-buttons";' in js
        assert "setPreviousRunsColumnFilterMode(fieldName, modeValue);" in js
        assert 'activeList.className = "previous-runs-column-filter-active-list";' in js
        assert 'setPreviousRunsIcon(removeBtn, "close");' in js
        assert "removePreviousRunsColumnFilterAt(fieldName, clauseIndex);" in js
        assert "addPreviousRunsColumnFilter(fieldName, operatorSelect.value || \"contains\", valueInput.value || \"\");" in js
        assert 'suggestionWrap.className = "previous-runs-column-filter-suggestions";' in js
        assert 'suggestionList.className = "previous-runs-column-filter-suggestions-list";' in js
        assert 'valueInput.dataset.topSuggestion = topCandidate;' in js
        assert "if (unary || meta.numeric) {" in js
        assert 'if (event.key === "Tab" && !event.shiftKey) {' in js
        assert "Tab completes top match." in js
        assert 'saveBtn.textContent = "Save";' in js
        assert 'closeBtn.textContent = "Close";' in js
        assert "let previousRunsDraggedColumn = null;" in js
        assert "function reorderPreviousRunsColumns(fromField, toField)" in js
        assert "th.draggable = true;" in js
        assert 'th.addEventListener("dragstart", event => {' in js
        assert 'th.addEventListener("drop", event => {' in js

    def test_js_per_label_aggregates_latest_run_timestamp_group(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-27_17.54.41",
                    artifact_dir="/tmp/eval/latest/a",
                    precision=0.5,
                    recall=0.5,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=1.0,
                            recall=0.5,
                            gold_total=10,
                            pred_total=5,
                        )
                    ],
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-27_17.54.41",
                    artifact_dir="/tmp/eval/latest/b",
                    precision=0.6,
                    recall=0.6,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=0.5,
                            recall=1.0,
                            gold_total=4,
                            pred_total=8,
                        )
                    ],
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-26_17.47.33",
                    artifact_dir="/tmp/eval/older",
                    precision=0.7,
                    recall=0.7,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=0.25,
                            recall=0.25,
                            gold_total=100,
                            pred_total=100,
                        )
                    ],
                ),
            ]
        )
        render_dashboard(tmp_path / "dash", data)
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function isSpeedBenchmarkRecord(record)" in js
        assert '.replace(/\\\\/g, "/")' in js
        assert ".toLowerCase();" in js
        assert 'return path.includes("/bench/speed/runs/");' in js
        assert "function isAllMethodBenchmarkRecord(record)" in js
        assert 'return path.includes("/all-method-benchmark/");' in js
        assert "const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;" in js
        assert "const latestAllMethodRecords = preferredRecords.filter(r =>" in js
        assert "isAllMethodBenchmarkRecord(r)" in js
        assert "const candidateRecords = latestAllMethodRecords.length > 0" in js
        assert "function latestRunGroupRecords(records, hasData)" in js
        assert "const latestRunGroup = benchmarkRunGroupInfo(latestRecord);" in js
        assert "const latestRunGroupKey = String((latestRunGroup && latestRunGroup.runGroupKey) || \"\").trim();" in js
        assert "const latestRunRecords = (records || []).filter(record => {" in js
        assert "const recordRunGroup = benchmarkRunGroupInfo(record);" in js
        assert 'if (segment !== "benchmark-vs-golden") continue;' in js
        assert 'latestRunRecords.length + " evals)"' in js
        assert "function aggregatePerLabelRows(records)" in js
        assert "function setupPerLabelControls()" in js
        assert "function syncPerLabelRollingWindowUi()" in js
        assert "function syncPerLabelComparisonModeUi()" in js
        assert "function normalizePerLabelRollingWindowSize(value)" in js
        assert "function normalizePerLabelComparisonMode(value)" in js
        assert "function rollingPerLabelByVariant(records, variant, windowSize)" in js
        assert "const rollingWindowSize = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);" in js
        assert "per_label_comparison_mode: normalizePerLabelComparisonMode(perLabelComparisonMode)" in js
        assert 'const checkbox = document.getElementById("per-label-comparison-point-value");' in js
        assert "const rawDelta = baselineNum - valueNum;" in js
        assert 'benchmarkVariantForRecord(record) === "codexfarm"' in js
        assert 'benchmarkVariantForRecord(record) === "vanilla"' in js

    def test_js_boundary_prefers_non_speed_records_when_available(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function renderBoundary()" in js
        assert "function isSpeedBenchmarkRecord(record)" in js
        assert "const hasBoundaryMetrics = function(record)" in js
        assert "const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;" in js
        assert "const latestAllMethodRecords = preferredRecords.filter(r =>" in js
        assert "const candidateRecords = latestAllMethodRecords.length > 0" in js
        assert "const latestRunGroup = latestRunGroupRecords(candidateRecords, hasBoundaryMetrics);" in js
        assert 'latestRunRecords.length + " evals)"' in js
        assert "Coverage: " in js
        assert "Matched (boundary unclassified)" in js
        assert '<th>% of gold</th>' in js
        assert '% of matched' not in js
        assert "Unmatched gold spans" in js

    def test_js_init_skips_removed_control_setup(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "setupFilters();" not in js
        assert "setupExtractorFilters();" not in js
        assert "setupThroughputModeControls();" not in js
        assert "setupGlobalCollapseControls();" not in js
        assert "renderPreviousRuns();" in js

    def test_benchmark_trend_chart_uses_fixed_height(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        css = (tmp_path / "dash" / "assets" / "style.css").read_text(encoding="utf-8")
        assert ".highcharts-host {" in css
        assert "height: 800px;" in css
        assert "const HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED = false;" in js
        assert "window.Highcharts.setOptions({" in js
        assert "mouseWheel: {" in js
        assert "enabled: HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED" in js
        assert 'window.Highcharts.stockChart("benchmark-trend-chart", {' in js
        assert "chart: {" in js
        assert "height: 800," in js
        assert "rangeSelector: {" in js
        assert '{ type: "all", text: "All" }' in js
        assert "selected: 5," in js
        assert "const allRunTimestamps = sorted" in js
        assert "const timelineMin = allRunTimestamps.length ? allRunTimestamps[0] : null;" in js
        assert "const timelineMax = allRunTimestamps.length ? allRunTimestamps[allRunTimestamps.length - 1] : null;" in js
        assert "const xAxisConfig = {" in js
        assert "if (timelineMin != null) xAxisConfig.min = timelineMin;" in js
        assert "if (timelineMax != null) xAxisConfig.max = timelineMax;" in js
        assert "xAxis: xAxisConfig," in js
        assert "function benchmarkVariantForRecord(record)" in js
        assert "function benchmarkRunGroupInfo(record)" in js
        assert "runGroupTimestampText" in js
        assert "function benchmarkRunGroupXAxisTimestampMs(record, runGroup)" in js
        assert "const xMs = benchmarkRunGroupXAxisTimestampMs(record, runGroup);" in js
        assert "if (xMs == null) return null;" in js
        assert "function trendSeriesPointForRunGroup(series, runGroupKey, hoveredX)" in js
        assert "function buildTrendRegression(points)" in js
        assert "function withTrendOverlays(baseSeriesList)" in js
        assert "function isTrendOverlaySeries(series)" in js
        assert "function buildBenchmarkTrendSeries(records)" in js
        assert "const hasPairedVariants =" in js
        assert 'name: metric.key + " (" + variant + ")"' in js
        assert "series: trendSeries," in js
        assert 'type: "scatter"' in js
        assert 'type: "arearange"' in js
        assert 'name: baseSeries.name + " trend"' in js
        assert 'name: baseSeries.name + " ±1σ"' in js
        assert "lineWidth: 0," in js
        assert "shared: false," in js
        assert "formatter: function()" in js
        assert "if (!series || series.visible === false || isTrendOverlaySeries(series)) return;" in js
        assert "trendSeriesPointForRunGroup(series, runGroupKey, hoveredX)" in js
        assert "runGroupKey" in js
        assert "runGroupLabel" in js
        assert "&#9679;" in js

    def test_previous_runs_table_has_horizontal_scroll_css(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        css = (tmp_path / "dash" / "assets" / "style.css").read_text(encoding="utf-8")
        assert ".diagnostics-grid {" in css
        assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);" in css
        assert "--previous-runs-visible-body-rows: 10;" in css
        assert ".quick-filters-panel {" in css
        assert ".quick-filters-list {" in css
        assert ".quick-filters-advanced {" not in css
        assert ".quick-filters-advanced-body {" not in css
        assert ".quick-filters-actions {" in css
        assert ".quick-filters-presets-control {" not in css
        assert ".previous-runs-presets-toggle {" not in css
        assert ".previous-runs-presets-popup {" not in css
        assert ".previous-runs-analysis-panels {" in css
        assert ".compare-control-panel {" in css
        assert ".compare-control-controls {" in css
        assert ".compare-control-results {" in css
        assert "#previous-runs-clear-all-filters {" in css
        assert "#quick-filters-status {" in css
        assert ".previous-runs-presets-panel {" in css
        assert "#previous-runs-preset-select {" in css
        assert ".previous-runs-presets-actions {" in css
        assert ".table-scroll {" in css
        assert "min-height: calc(" in css
        assert "max-height: calc(" in css
        assert "overflow-y: auto;" in css
        assert "--previous-runs-filter-row-height: 2.18rem;" in css
        assert "--previous-runs-spacer-row-height: 2.18rem;" in css
        assert "#previous-runs-table {" in css
        assert "border-collapse: separate;" in css
        assert "border-spacing: 0;" in css
        assert "width: max-content;" in css
        assert "min-width: 1600px;" in css
        assert "#previous-runs-table th," in css
        assert "white-space: nowrap;" in css
        th_block = re.search(r"#previous-runs-table th \{([^}]*)\}", css, re.DOTALL)
        assert th_block is not None
        assert "position: relative;" not in th_block.group(1)
        assert "#previous-runs-table th.previous-runs-draggable {" in css
        assert "#previous-runs-table th.previous-runs-drag-target {" in css
        assert ".previous-runs-resize-handle," in css
        assert ".dashboard-table-resize-handle {" in css
        assert ".dashboard-resizable-table th," in css
        assert "#previous-runs-table thead tr.previous-runs-header-row th:not(:last-child)," in css
        assert ".dashboard-resizable-table thead tr:first-child th:not(:last-child) {" in css
        assert "border-right: 1px solid #d6e0ea;" in css
        assert "#runtime-summary,\n#boundary-summary {" in css
        assert "overflow-x: hidden;" in css
        assert "#per-label-section {" in css
        assert "overflow-x: auto;" in css
        assert "cursor: col-resize;" in css

    def test_render_builds_all_method_standalone_pages(self, tmp_path):
        all_method_root = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        all_method_root_second = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "dinnerfor2cutdown"
        )
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:04:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_001_aaa_extractor_beautifulsoup"
                    ),
                    precision=0.12,
                    recall=0.44,
                    f1=0.19,
                    practical_f1=0.54,
                    recipes=7,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup | workers=7",
                    run_config_hash="hash001",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:05:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_002_bbb_extractor_markdown"
                    ),
                    precision=0.20,
                    recall=0.60,
                    f1=0.30,
                    practical_f1=0.62,
                    recipes=9,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=markdown | workers=7",
                    run_config_hash="hash002",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:06:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_003_ccc_extractor_auto__parser_v2__skiphf_true__pre_br_split_v1"
                    ),
                    precision=0.08,
                    recall=0.30,
                    f1=0.13,
                    practical_f1=0.40,
                    recipes=8,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_hash="hash003",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:07:10",
                    artifact_dir=str(
                        all_method_root_second
                        / "config_001_aaa_extractor_beautifulsoup"
                    ),
                    precision=0.25,
                    recall=0.58,
                    f1=0.35,
                    practical_f1=0.68,
                    recipes=10,
                    gold_recipe_headers=12,
                    source_file="/tmp/DinnerFor2CUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup | workers=7",
                    run_config_hash="hash001",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:08:10",
                    artifact_dir=str(
                        all_method_root_second
                        / "config_002_bbb_extractor_markdown"
                    ),
                    precision=0.31,
                    recall=0.66,
                    f1=0.42,
                    practical_f1=0.81,
                    recipes=12,
                    gold_recipe_headers=12,
                    source_file="/tmp/DinnerFor2CUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=markdown | workers=7",
                    run_config_hash="hash002",
                ),
            ]
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "All-Method Benchmark Runs" not in html
        assert "all-method-benchmark/index.html" not in html

        all_method_dir = tmp_path / "dash" / "all-method-benchmark"
        run_detail_path = (
            all_method_dir
            / "all-method-benchmark-run__2026-02-23_16.01.06.html"
        )
        assert run_detail_path.exists()
        detail_path = (
            all_method_dir
            / "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html"
        )
        assert detail_path.exists()
        detail_path_second = (
            all_method_dir
            / "all-method-benchmark__2026-02-23_16.01.06__dinnerfor2cutdown.html"
        )
        assert detail_path_second.exists()

        detail_html = detail_path.read_text(encoding="utf-8")
        assert 'class="all-method-quick-nav"' in detail_html
        assert 'href="#detail-summary"' in detail_html
        assert 'href="#detail-charts"' in detail_html
        assert 'href="#detail-ranked-table"' in detail_html
        assert 'id="detail-charts"' in detail_html
        assert 'id="detail-ranked-table"' in detail_html
        assert 'class="section-details"' in detail_html
        assert "Run Summary" in detail_html
        assert "Compact stats only (no per-config labels)" in detail_html
        assert "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>" in detail_html
        assert "Metric Bar Charts" in detail_html
        assert "One bar per run/configuration for each metric category." in detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source." in detail_html
        assert "Run 01" in detail_html
        assert "metric-bar-fill" in detail_html
        assert "Metric Web Charts (Radar)" in detail_html
        assert "Each web is one run/configuration." in detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source." in detail_html
        assert "metric-radar-svg" in detail_html
        assert "Run 01: config_002_bbb_extractor_markdown" in detail_html
        assert "<strong>Golden recipes:</strong> 10" in detail_html
        strict_precision_block = detail_html.split("<h3>Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:20.00%"' in strict_precision_block
        assert 'style="width:100.00%"' not in strict_precision_block
        recipes_identified_block = detail_html.split("<h3>Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:90.00%"' in recipes_identified_block
        assert 'style="width:70.00%"' in recipes_identified_block
        assert "Strict Precision" in detail_html
        assert "Practical F1" in detail_html
        assert ">Extractor</span></th>" in detail_html
        assert ">Parser</span></th>" in detail_html
        assert ">Skip HF</th>" in detail_html
        assert ">Preprocess</th>" in detail_html
        assert "<td>auto</td>" in detail_html
        assert "<td>v2</td>" in detail_html
        assert "<td>true</td>" in detail_html
        assert "<td>br_split_v1</td>" in detail_html
        assert "<td>markdown</td>" in detail_html
        assert "<td>-</td>" in detail_html
        assert "Ranked Configurations" in detail_html
        assert detail_html.find("config_002_bbb_extractor_markdown") < detail_html.find(
            "config_001_aaa_extractor_beautifulsoup"
        )
        assert "strict_f1=0.3000" in detail_html
        assert 'href="../index.html#previous-runs-section"' in detail_html

        run_detail_html = run_detail_path.read_text(encoding="utf-8")
        assert 'href="../index.html#previous-runs-section"' in run_detail_html
        assert 'class="all-method-quick-nav"' in run_detail_html
        assert 'href="#run-summary"' in run_detail_html
        assert 'href="#run-charts"' in run_detail_html
        assert 'href="#run-config-table"' in run_detail_html
        assert 'href="#run-drilldown"' in run_detail_html
        assert 'id="run-charts"' in run_detail_html
        assert 'id="run-config-table"' in run_detail_html
        assert 'id="run-drilldown"' in run_detail_html
        assert "Run Summary" in run_detail_html
        assert "Compact stats across aggregated config rows" in run_detail_html
        assert "Metric Bar Charts" in run_detail_html
        assert "One bar per aggregated configuration for each metric category." in run_detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book." in run_detail_html
        assert "Config 01" in run_detail_html
        assert "metric-bar-fill" in run_detail_html
        assert "Metric Web Charts (Radar)" in run_detail_html
        assert "Each web is one aggregated configuration." in run_detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book." in run_detail_html
        assert "metric-radar-svg" in run_detail_html
        assert "Config 01: config_002_bbb_extractor_markdown" in run_detail_html
        assert "Per-Cookbook Average Metric Bar Charts" in run_detail_html
        assert "One bar per cookbook. Values are averaged across all configs that ran for that cookbook." in run_detail_html
        assert "Labels use Book 01/Book 02 order from Per-Book Drilldown." in run_detail_html
        assert "Highest avg strict precision:" in run_detail_html
        assert "Highest avg strict recall:" in run_detail_html
        assert "Book 01" in run_detail_html
        assert "Per-Cookbook Average Web Charts (Radar)" in run_detail_html
        assert "Each web is one cookbook with metrics averaged across all configs that ran for that cookbook." in run_detail_html
        assert "Book 01: DinnerFor2CUTDOWN.epub (configs=2)" in run_detail_html
        avg_book_precision_block = run_detail_html.split("<h3>Avg Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:13.33%"' in avg_book_precision_block
        assert 'style="width:28.00%"' in avg_book_precision_block
        avg_book_recipes_identified_block = run_detail_html.split("<h3>Avg Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:80.00%"' in avg_book_recipes_identified_block
        assert 'style="width:91.67%"' in avg_book_recipes_identified_block
        mean_precision_block = run_detail_html.split("<h3>Mean Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:25.50%"' in mean_precision_block
        assert 'style="width:100.00%"' not in mean_precision_block
        mean_recipes_identified_block = run_detail_html.split("<h3>Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:95.00%"' in mean_recipes_identified_block
        assert "Mean Strict Precision" in run_detail_html
        assert "Mean Practical F1" in run_detail_html
        assert "Config Performance Across Books" in run_detail_html
        assert "Per-Book Drilldown" in run_detail_html
        assert "Open book details" in run_detail_html
        assert "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html" in run_detail_html
        assert "all-method-benchmark__2026-02-23_16.01.06__dinnerfor2cutdown.html" in run_detail_html
        assert run_detail_html.find("config_002_bbb_extractor_markdown") < run_detail_html.find(
            "config_001_aaa_extractor_beautifulsoup"
        )

    def test_all_method_renders_report_variants_without_eval_reports(self, tmp_path):
        golden_root = tmp_path / "golden"
        all_method_root = (
            golden_root
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        all_method_root.mkdir(parents=True, exist_ok=True)

        for idx in range(1, 4):
            config_dir = all_method_root / f"config_{idx:03d}_cfg{idx}_extractor_beautifulsoup"
            (config_dir / "prediction-run").mkdir(parents=True, exist_ok=True)
            (config_dir / "prediction-run" / "manifest.json").write_text(
                json.dumps(
                    {
                        "importer_name": "epub",
                        "source_file": "/tmp/thefoodlabCUTDOWN.epub",
                        "recipe_count": 10 + idx,
                        "run_config": {"epub_extractor": "beautifulsoup"},
                    }
                ),
                encoding="utf-8",
            )

        (all_method_root / "all_method_benchmark_report.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-02-23T16:10:00",
                    "source_file": "/tmp/thefoodlabCUTDOWN.epub",
                    "variants": [
                        {
                            "config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "executed",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash001",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                        {
                            "config_dir": "config_002_cfg2_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "reused_in_run",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash002",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                        {
                            "config_dir": "config_003_cfg3_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "reused_in_run",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash003",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:04:10",
                    artifact_dir=str(all_method_root / "config_001_cfg1_extractor_beautifulsoup"),
                    precision=0.10,
                    recall=0.20,
                    f1=0.1333,
                    practical_f1=0.4444,
                    recipes=11,
                    gold_recipe_headers=20,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_hash="hash001",
                )
            ],
        )
        render_dashboard(tmp_path / "dash", data)

        all_method_index = tmp_path / "dash" / "all-method-benchmark" / "index.html"
        assert not all_method_index.exists()

        run_detail_html = (
            tmp_path
            / "dash"
            / "all-method-benchmark"
            / "all-method-benchmark-run__2026-02-23_16.01.06.html"
        ).read_text(encoding="utf-8")
        assert "<strong>Run folder:</strong> 2026-02-23_16.01.06" in run_detail_html
        assert "<strong>Configs aggregated:</strong> 3" in run_detail_html

        detail_path = (
            tmp_path
            / "dash"
            / "all-method-benchmark"
            / "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html"
        )
        detail_html = detail_path.read_text(encoding="utf-8")
        assert "config_001_cfg1_extractor_beautifulsoup" in detail_html
        assert "config_002_cfg2_extractor_beautifulsoup" in detail_html
        assert "config_003_cfg3_extractor_beautifulsoup" in detail_html

    def test_render_includes_single_profile_sweep_runs(self, tmp_path):
        golden_root = tmp_path / "golden"
        single_profile_root = (
            golden_root
            / "benchmark-vs-golden"
            / "2026-02-28_03.35.11"
            / "single-profile-benchmark"
        )
        hash_value = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-28_03.35.11",
                    artifact_dir=str(single_profile_root / "01_book_a"),
                    precision=0.35,
                    recall=0.45,
                    f1=0.3938,
                    practical_f1=0.55,
                    recipes=10,
                    gold_recipe_headers=12,
                    source_file="/tmp/book_a.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup",
                    run_config_hash=hash_value,
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-28_03.35.11",
                    artifact_dir=str(single_profile_root / "02_book_b"),
                    precision=0.40,
                    recall=0.50,
                    f1=0.4444,
                    practical_f1=0.60,
                    recipes=11,
                    gold_recipe_headers=13,
                    source_file="/tmp/book_b.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup",
                    run_config_hash=hash_value,
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)

        all_method_dir = tmp_path / "dash" / "all-method-benchmark"
        assert not (all_method_dir / "index.html").exists()

        run_detail_html = (
            all_method_dir
            / "all-method-benchmark-run__2026-02-28_03.35.11.html"
        ).read_text(encoding="utf-8")
        assert "<strong>Book jobs:</strong> 2" in run_detail_html
        assert "<strong>Configs aggregated:</strong> 1" in run_detail_html
        assert "profile_abcdef123456" in run_detail_html
        assert "all-method-benchmark__2026-02-28_03.35.11__01_book_a.html" in run_detail_html
        assert "all-method-benchmark__2026-02-28_03.35.11__02_book_b.html" in run_detail_html

    def test_render_all_method_section_when_no_groups(self, tmp_path):
        golden_root = tmp_path / "golden-empty"
        golden_root.mkdir(parents=True, exist_ok=True)
        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:05:10",
                    artifact_dir="/tmp/eval/2026-02-23_16.05.10",
                    precision=0.20,
                    recall=0.60,
                    f1=0.30,
                )
            ]
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "all-method-benchmark/index.html" not in html
        assert "No all-method benchmark runs found in benchmark history." not in html
        assert not (tmp_path / "dash" / "all-method-benchmark" / "index.html").exists()
        assert not (tmp_path / "dash" / "all-method-benchmark.html").exists()

    def test_idempotent(self, tmp_path):
        data = DashboardData()
        render_dashboard(tmp_path / "dash", data)
        render_dashboard(tmp_path / "dash", data)  # should not error
        assert (tmp_path / "dash" / "index.html").exists()


# ---------------------------------------------------------------------------
# Benchmark CSV tests
# ---------------------------------------------------------------------------

class TestBenchmarkCsv:
    def test_benchmark_csv_append(self, tmp_path):
        """append_benchmark_csv writes a row with benchmark columns populated."""
        csv_path = tmp_path / "history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["run_category"] == "benchmark_eval"
        assert row["eval_scope"] == "freeform-spans"
        assert float(row["precision"]) == pytest.approx(0.05)
        assert float(row["recall"]) == pytest.approx(0.25)
        assert float(row["f1"]) == pytest.approx(0.08333333333333333)
        assert float(row["practical_precision"]) == pytest.approx(0.7)
        assert float(row["practical_recall"]) == pytest.approx(0.85)
        assert float(row["practical_f1"]) == pytest.approx(0.767741935483871)
        assert row["gold_total"] == "100"
        assert row["gold_recipe_headers"] == "11"
        assert row["gold_matched"] == "25"
        assert row["pred_total"] == "500"
        assert float(row["supported_precision"]) == pytest.approx(0.08)
        assert float(row["supported_recall"]) == pytest.approx(0.55)
        assert float(row["supported_practical_precision"]) == pytest.approx(0.72)
        assert float(row["supported_practical_recall"]) == pytest.approx(0.88)
        assert float(row["supported_practical_f1"]) == pytest.approx(0.792)
        assert row["granularity_mismatch_likely"] == "1"
        assert float(row["pred_width_p50"]) == pytest.approx(28.0)
        assert float(row["gold_width_p50"]) == pytest.approx(1.0)
        assert row["boundary_correct"] == "10"
        assert row["boundary_over"] == "8"
        assert row["boundary_under"] == "5"
        assert row["boundary_partial"] == "2"
        assert row["file_name"] == "my_book.pdf"
        assert row["importer_name"] == "pdf"
        assert row["report_path"] == ""
        assert row["tokens_total"] == ""
        # Stage-only fields should be empty
        assert row["recipes"] == ""
        assert row["total_seconds"] == ""

    def test_benchmark_csv_append_with_recipes_and_processed_report_path(self, tmp_path):
        csv_path = tmp_path / "history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
            recipes=31,
            processed_report_path="/tmp/output/2026-02-11_15.59.00/my_book.excel_import_report.json",
            run_config={"epub_extractor": "beautifulsoup", "workers": 7},
            tokens_input=300,
            tokens_cached_input=50,
            tokens_output=80,
            tokens_reasoning=10,
            tokens_total=390,
            timing={
                "total_seconds": 21.5,
                "prediction_seconds": 17.0,
                "evaluation_seconds": 3.1,
                "artifact_write_seconds": 1.0,
                "history_append_seconds": 0.4,
                "parsing_seconds": 11.2,
                "writing_seconds": 4.0,
                "ocr_seconds": 0.6,
                "checkpoints": {
                    "prediction_load_seconds": 0.8,
                    "gold_load_seconds": 0.3,
                    "evaluate_seconds": 2.0,
                },
            },
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["recipes"] == "31"
        assert row["importer_name"] == "pdf"
        assert (
            row["report_path"]
            == "/tmp/output/2026-02-11_15.59.00/my_book.excel_import_report.json"
        )
        assert float(row["total_seconds"]) == pytest.approx(21.5)
        assert float(row["parsing_seconds"]) == pytest.approx(11.2)
        assert float(row["writing_seconds"]) == pytest.approx(4.0)
        assert float(row["ocr_seconds"]) == pytest.approx(0.6)
        assert float(row["benchmark_prediction_seconds"]) == pytest.approx(17.0)
        assert float(row["benchmark_evaluation_seconds"]) == pytest.approx(3.1)
        assert float(row["benchmark_artifact_write_seconds"]) == pytest.approx(1.0)
        assert float(row["benchmark_history_append_seconds"]) == pytest.approx(0.4)
        assert float(row["benchmark_total_seconds"]) == pytest.approx(21.5)
        assert float(row["benchmark_prediction_load_seconds"]) == pytest.approx(0.8)
        assert float(row["benchmark_gold_load_seconds"]) == pytest.approx(0.3)
        assert float(row["benchmark_evaluate_seconds"]) == pytest.approx(2.0)
        assert row["tokens_input"] == "300"
        assert row["tokens_cached_input"] == "50"
        assert row["tokens_output"] == "80"
        assert row["tokens_reasoning"] == "10"
        assert row["tokens_total"] == "390"
        assert row["run_config_hash"] != ""
        assert "epub_extractor=beautifulsoup" in row["run_config_summary"]
        assert row["run_config_json"] != ""

    def test_benchmark_csv_timing_falls_back_to_processed_report(self, tmp_path):
        csv_path = tmp_path / "history.csv"
        processed_report = (
            tmp_path
            / "output"
            / "2026-02-11_15.59.00"
            / "my_book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(
            json.dumps(
                {
                    "totalRecipes": 31,
                    "timing": {
                        "total_seconds": 18.0,
                        "prediction_seconds": 18.0,
                        "parsing_seconds": 9.2,
                        "writing_seconds": 3.1,
                        "ocr_seconds": 0.4,
                        "checkpoints": {
                            "processed_output_write_seconds": 2.4,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
            processed_report_path=str(processed_report),
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))

        assert float(row["total_seconds"]) == pytest.approx(18.0)
        assert float(row["parsing_seconds"]) == pytest.approx(9.2)
        assert float(row["writing_seconds"]) == pytest.approx(3.1)
        assert float(row["ocr_seconds"]) == pytest.approx(0.4)
        assert float(row["benchmark_prediction_seconds"]) == pytest.approx(18.0)
        assert float(row["benchmark_total_seconds"]) == pytest.approx(18.0)

    def test_csv_with_mixed_rows(self, tmp_path):
        """CSV with both stage and benchmark rows; collector produces both."""
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + SAMPLE_CSV_ROW1 + "\n"
            + SAMPLE_CSV_BENCH_ROW + "\n",
            encoding="utf-8",
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].file_name == "cookbook_a.xlsx"
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.precision == pytest.approx(0.05)
        assert b.recall == pytest.approx(0.25)
        assert b.practical_precision == pytest.approx(0.70)
        assert b.practical_recall == pytest.approx(0.85)
        assert b.practical_f1 == pytest.approx(0.767741935483871)
        assert b.gold_total == 100
        assert b.boundary_correct == 10
        assert b.supported_recall == pytest.approx(0.55)
        assert b.supported_practical_recall == pytest.approx(0.88)
        assert b.granularity_mismatch_likely is True
        assert b.source_file == "my_book.pdf"
        assert b.tokens_input == 1234
        assert b.tokens_cached_input == 234
        assert b.tokens_output == 345
        assert b.tokens_reasoning == 12
        assert b.tokens_total == 1591
        assert b.recipes is None
        assert b.gold_recipe_headers == 11

    def test_csv_and_json_benchmark_rows_merge_by_artifact_dir(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )

        csv_path = history_dir / "performance_history.csv"
        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-11T16:00:00",
                "run_dir": str(eval_dir),
                "file_name": "my_book.pdf",
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.05",
                "recall": "0.25",
                "f1": "0.08333333333333333",
                "gold_total": "100",
                "gold_matched": "25",
                "pred_total": "500",
                "supported_precision": "0.08",
                "supported_recall": "0.55",
                "boundary_correct": "10",
                "boundary_over": "8",
                "boundary_under": "5",
                "boundary_partial": "2",
            }
        )
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n" + bench_row + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_benchmark_reports=True,
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.artifact_dir == str(eval_dir)
        assert b.source_file == "my_book.pdf"
        assert b.recipes == 14
        assert b.gold_recipe_headers == 11
        assert len(b.per_label) == 2

    def test_csv_benchmark_rows_do_not_json_merge_without_opt_in_scan(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )

        csv_path = history_dir / "performance_history.csv"
        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-11T16:00:00",
                "run_dir": str(eval_dir),
                "file_name": "my_book.pdf",
                "run_category": "benchmark_eval",
                "precision": "0.05",
                "recall": "0.25",
                "f1": "0.08333333333333333",
            }
        )
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n" + bench_row + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.recipes is None
        assert record.gold_recipe_headers is None

    def test_benchmark_csv_per_label_json_roundtrip(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir=str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"),
            eval_scope="freeform-spans",
            source_file="book.epub",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        labels = {entry.label for entry in data.benchmark_records[0].per_label}
        assert labels == {"RECIPE_TITLE", "INGREDIENT_LINE"}

    def test_benchmark_csv_schema_migration(self, tmp_path):
        """Existing CSV without new columns gets migrated when appending."""
        csv_path = tmp_path / "history.csv"
        # Write old-format CSV (missing benchmark columns)
        old_header = (
            "run_timestamp,run_dir,file_name,report_path,importer_name,"
            "total_seconds,parsing_seconds,writing_seconds,ocr_seconds,"
            "recipes,tips,tip_candidates,topic_candidates,"
            "standalone_blocks,standalone_topic_blocks,standalone_topic_coverage,"
            "total_units,per_recipe_seconds,per_tip_seconds,"
            "per_tip_candidate_seconds,per_topic_candidate_seconds,per_unit_seconds,"
            "output_files,output_bytes,knowledge_share,knowledge_heavy,"
            "dominant_stage,dominant_stage_seconds,dominant_checkpoint,dominant_checkpoint_seconds"
        )
        old_row = (
            "2026-02-10T10:00:00,/some/dir,test.xlsx,,,"
            "5.5,1.2,3.8,0.0,"
            "20,5,3,2,"
            ",,,"
            "30,0.275,1.1,1.833,2.75,0.183,"
            "10,50000,0.066,,"
            "writing,3.8,write_final_seconds,3.5"
        )
        csv_path.write_text(old_header + "\n" + old_row + "\n", encoding="utf-8")

        # Append a benchmark row — should trigger schema migration
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
        )

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames) == _CSV_FIELDS
            rows = list(reader)

        assert len(rows) == 2
        # Old row should have empty benchmark fields after migration
        assert rows[0]["run_category"] == ""
        assert rows[0]["precision"] == ""
        assert rows[0]["recipes"] == "20"
        # New row should have benchmark fields populated
        assert rows[1]["run_category"] == "benchmark_eval"
        assert float(rows[1]["precision"]) == pytest.approx(0.05)

    def test_backfill_benchmark_csv_from_prediction_manifest(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.05.00"
        pred_run = eval_dir / "prediction-run"
        pred_run.mkdir(parents=True, exist_ok=True)
        processed_report = (
            tmp_path / "output" / "2026-02-16_14.04.00" / "book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(json.dumps({"totalRecipes": 12}), encoding="utf-8")
        (pred_run / "manifest.json").write_text(
            json.dumps(
                {
                    "recipe_count": 12,
                    "processed_report_path": str(processed_report),
                    "source_file": "book.epub",
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:05:00",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)
        assert summary.benchmark_rows == 1
        assert summary.rows_updated == 1
        assert summary.recipes_filled == 1
        assert summary.report_paths_filled == 1
        assert summary.source_files_filled == 1
        assert summary.rows_still_missing_recipes == 0

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["recipes"] == "12"
        assert row["report_path"] == str(processed_report)
        assert row["file_name"] == "book.epub"

    def test_backfill_benchmark_csv_sums_bench_suite_item_recipes(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        run_dir = tmp_path / "golden" / "bench" / "runs" / "2026-02-16_14.20.00"
        (run_dir / "per_item" / "a" / "pred_run").mkdir(parents=True, exist_ok=True)
        (run_dir / "per_item" / "b" / "pred_run").mkdir(parents=True, exist_ok=True)
        (run_dir / "per_item" / "a" / "pred_run" / "manifest.json").write_text(
            json.dumps({"recipe_count": 4}),
            encoding="utf-8",
        )
        processed_report = (
            tmp_path / "output" / "2026-02-16_14.19.00" / "item-b.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(json.dumps({"totalRecipes": 7}), encoding="utf-8")
        (run_dir / "per_item" / "b" / "pred_run" / "manifest.json").write_text(
            json.dumps({"processed_report_path": str(processed_report)}),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:21:00",
                "run_dir": str(run_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "bench-suite",
                "file_name": "my-suite",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)
        assert summary.benchmark_rows == 1
        assert summary.rows_updated == 1
        assert summary.recipes_filled == 1
        assert summary.report_paths_filled == 0
        assert summary.source_files_filled == 0
        assert summary.rows_still_missing_recipes == 0

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["recipes"] == "11"
        assert row["report_path"] == ""
