"""Tests for the stats-dashboard feature: schema, collectors, renderer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from cookimport.analytics.dashboard_schema import (
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

SAMPLE_CSV_HEADER = (
    "run_timestamp,run_dir,file_name,report_path,importer_name,"
    "total_seconds,parsing_seconds,writing_seconds,ocr_seconds,"
    "recipes,tips,tip_candidates,topic_candidates,"
    "standalone_blocks,standalone_topic_blocks,standalone_topic_coverage,"
    "total_units,per_recipe_seconds,per_tip_seconds,"
    "per_tip_candidate_seconds,per_topic_candidate_seconds,per_unit_seconds,"
    "output_files,output_bytes,knowledge_share,knowledge_heavy,"
    "dominant_stage,dominant_stage_seconds,dominant_checkpoint,dominant_checkpoint_seconds,"
    "run_category,eval_scope,precision,recall,f1,"
    "gold_total,gold_matched,pred_total,"
    "supported_precision,supported_recall,"
    "boundary_correct,boundary_over,boundary_under,boundary_partial,"
    "run_config_hash,run_config_summary,run_config_json"
)

SAMPLE_CSV_ROW1 = (
    "2026-02-10T10:00:00,data/output/2026-02-10_10.00.00,cookbook_a.xlsx,"
    "data/output/2026-02-10_10.00.00/cookbook_a.excel_import_report.json,,"
    "5.5,1.2,3.8,0.0,"
    "20,5,3,2,"
    ",,,"
    "30,0.275,1.1,1.833,2.75,0.183,"
    "10,50000,0.066,,"
    "writing,3.8,write_final_seconds,3.5,"
    "stage_import,,,,,,,,,,,,,"
)

SAMPLE_CSV_ROW2 = (
    "2026-02-11T14:30:00,data/output/2026-02-11_14.30.00,cookbook_b.epub,"
    "data/output/2026-02-11_14.30.00/cookbook_b.excel_import_report.json,epub,"
    "12.3,4.5,6.1,1.7,"
    "50,10,8,5,"
    ",,,"
    "73,0.246,1.23,1.5375,2.46,0.168,"
    "25,120000,0.068,,"
    "writing,6.1,write_final_seconds,5.8,"
    "stage_import,,,,,,,,,,,,,"
)

SAMPLE_CSV_BENCH_ROW = (
    "2026-02-11T16:00:00,data/golden/eval-vs-pipeline/2026-02-11_16.00.00,my_book.pdf,"
    ",,,,,"
    ",,,,,"
    ",,,"
    ",,,,,,"
    ",,,,,"
    ",,,"
    "benchmark_eval,freeform-spans,0.05,0.25,0.08333333333333333,"
    "100,25,500,"
    "0.08,0.55,"
    "10,8,5,2"
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
        "epub_extractor": "legacy",
        "ocr_device": "auto",
        "ocr_batch_size": 1,
        "effective_workers": 10,
    },
    "runConfigHash": "abc123def456",
    "runConfigSummary": "epub_extractor=legacy | ocr_device=auto | ocr_batch_size=1 | effective_workers=10",
}


SAMPLE_EVAL_REPORT = {
    "precision": 0.05,
    "recall": 0.25,
    "counts": {
        "gold_total": 100,
        "gold_matched": 25,
        "gold_missed": 75,
        "pred_total": 500,
        "pred_matched": 25,
        "pred_false_positive": 475,
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
        assert d.schema_version == "6"
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
            "epub_extractor": "legacy",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.run_config_hash == "abc123def456"
        assert "epub_extractor=legacy" in str(r.run_config_summary)

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
                "run_config_json": json.dumps(
                    {
                        "epub_extractor": "legacy",
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
            "epub_extractor": "legacy",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.run_config_hash is not None
        assert "epub_extractor=legacy" in str(r.run_config_summary)

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
            "epub_extractor": "legacy",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert data.stage_records[0].run_config_hash == "abc123def456"
        assert "epub_extractor=legacy" in str(data.stage_records[0].run_config_summary)

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
        assert b.gold_total == 100
        assert b.boundary_correct == 10
        assert len(b.per_label) == 2
        assert b.supported_recall == pytest.approx(0.55)

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
                "run_config_summary": "epub_extractor=legacy | workers=7",
                "run_config_json": json.dumps({"epub_extractor": "legacy", "workers": 7}),
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
        assert record.run_config_summary == "epub_extractor=legacy | workers=7"
        assert record.run_config == {"epub_extractor": "legacy", "workers": 7}

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
                        "epub_extractor": "legacy",
                        "ocr_device": "auto",
                        "workers": 6,
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
        assert b.run_config == {
            "epub_extractor": "legacy",
            "ocr_device": "auto",
            "workers": 6,
        }
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
            return (
                f"{ts},{run_dir},{source_file},"
                ",,,,,"
                ",,,,,"
                ",,,"
                ",,,,,,"
                ",,,,,"
                ",,,"
                "benchmark_eval,freeform-spans,0.05,0.25,0.08333333333333333,"
                "100,25,500,"
                "0.08,0.55,"
                "10,8,5,2"
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
            return (
                f"{ts},{run_dir},{source_file},"
                ",,,,,"
                ",,,,,"
                ",,,"
                ",,,,,,"
                ",,,,,"
                ",,,"
                "benchmark_eval,freeform-spans,0.05,0.25,0.08333333333333333,"
                "100,25,500,"
                "0.08,0.55,"
                "10,8,5,2"
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
        assert (tmp_path / "dash" / "assets" / "dashboard.js").exists()
        assert (tmp_path / "dash" / "assets" / "style.css").exists()

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
                    run_config={"epub_extractor": "legacy", "ocr_device": "auto"},
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

    def test_html_includes_benchmark_context_columns(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    artifact_dir="/tmp/eval",
                    precision=0.1,
                    recall=0.2,
                    importer_name="epub",
                    source_file="/tmp/source/book.epub",
                    run_config={"epub_extractor": "legacy", "ocr_device": "auto"},
                ),
            ],
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "Run Config" in html
        assert "<th>Recipes</th>" in html
        assert "Precision: how many predictions were correct." in html

    def test_html_includes_run_and_file_trend_views(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    file_name="book.epub",
                    importer_name="epub",
                    run_config={
                        "epub_extractor": "legacy",
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
        assert "Run / Date Trend (sec/recipe)" in html
        assert "Recent Runs (Date / Run View)" in html
        assert "File Trend (Selected File)" in html
        assert 'id="file-trend-select"' in html
        assert 'id="file-trend-chart"' in html
        assert 'id="file-trend-table"' in html
        assert "<th>File</th><th>Importer</th><th>Total (s)</th>" in html
        assert "<th>Recipes</th><th>sec/recipe</th><th>Run Config</th><th>Artifact</th>" in html

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
        assert "const m = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})[T_](\\d{2})[.:](\\d{2})[.:](\\d{2})$/);" in js
        assert "const d = new Date(" in js
        assert "Number(m[1])" in js
        assert "function compareRunTimestampAsc(aTs, bTs)" in js
        assert "function compareRunTimestampDesc(aTs, bTs)" in js
        assert "compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)" in js

    def test_js_marks_stale_run_config_warning(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    file_name="book.epub",
                    run_config_warning="missing report (stale row)",
                    total_seconds=12.0,
                    recipes=6,
                    per_recipe_seconds=2.0,
                    artifact_dir="/tmp/output/2026-02-11_16.00.00",
                )
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=6),
        )
        render_dashboard(tmp_path / "dash", data)
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "run_config_warning" in js
        assert 'class="warn-note"' in js
        assert "[warn] " in js

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
        assert float(row["f1"]) == pytest.approx(2 * 0.05 * 0.25 / (0.05 + 0.25))
        assert row["gold_total"] == "100"
        assert row["gold_matched"] == "25"
        assert row["pred_total"] == "500"
        assert float(row["supported_precision"]) == pytest.approx(0.08)
        assert float(row["supported_recall"]) == pytest.approx(0.55)
        assert row["boundary_correct"] == "10"
        assert row["boundary_over"] == "8"
        assert row["boundary_under"] == "5"
        assert row["boundary_partial"] == "2"
        assert row["file_name"] == "my_book.pdf"
        assert row["report_path"] == ""
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
            run_config={"epub_extractor": "legacy", "workers": 7},
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["recipes"] == "31"
        assert (
            row["report_path"]
            == "/tmp/output/2026-02-11_15.59.00/my_book.excel_import_report.json"
        )
        assert row["run_config_hash"] != ""
        assert "epub_extractor=legacy" in row["run_config_summary"]
        assert row["run_config_json"] != ""

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
        assert b.gold_total == 100
        assert b.boundary_correct == 10
        assert b.supported_recall == pytest.approx(0.55)
        assert b.source_file == "my_book.pdf"
        assert b.recipes is None

    def test_csv_and_json_benchmark_rows_merge_by_artifact_dir(self, tmp_path):
        history_dir = tmp_path / "output" / ".history"
        history_dir.mkdir(parents=True)
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )

        csv_path = history_dir / "performance_history.csv"
        bench_row = (
            "2026-02-11T16:00:00,"
            + str(eval_dir)
            + ",my_book.pdf,"
            ",,,,,"
            ",,,,,"
            ",,,"
            ",,,,,,"
            ",,,,,"
            ",,,"
            "benchmark_eval,freeform-spans,0.05,0.25,0.08333333333333333,"
            "100,25,500,"
            "0.08,0.55,"
            "10,8,5,2"
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
        b = data.benchmark_records[0]
        assert b.artifact_dir == str(eval_dir)
        assert b.source_file == "my_book.pdf"
        assert b.recipes is None
        assert len(b.per_label) == 2

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
