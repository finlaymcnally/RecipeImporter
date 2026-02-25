from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.analytics.perf_report import _CSV_FIELDS
from cookimport.cli import app


runner = CliRunner()


def _write_benchmark_row(csv_path: Path, run_dir: Path) -> None:
    row = {field: "" for field in _CSV_FIELDS}
    row.update(
        {
            "run_timestamp": "2026-02-16T15:00:00",
            "run_dir": str(run_dir),
            "run_category": "benchmark_eval",
            "eval_scope": "freeform-spans",
        }
    )
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_prediction_manifest(eval_dir: Path, processed_report: Path) -> None:
    pred_run = eval_dir / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    processed_report.parent.mkdir(parents=True, exist_ok=True)
    processed_report.write_text(json.dumps({"totalRecipes": 9}), encoding="utf-8")
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "recipe_count": 9,
                "processed_report_path": str(processed_report),
                "source_file": "book.epub",
            }
        ),
        encoding="utf-8",
    )


def test_benchmark_csv_backfill_cli_dry_run_does_not_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "output" / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_15.00.00"
    processed_report = (
        tmp_path / "output" / "2026-02-16_14.59.00" / "book.excel_import_report.json"
    )

    _write_benchmark_row(csv_path, eval_dir)
    _write_prediction_manifest(eval_dir, processed_report)

    captured_dashboard_calls: list[dict[str, object]] = []

    def fake_stats_dashboard(**kwargs):
        captured_dashboard_calls.append(kwargs)

    monkeypatch.setattr("cookimport.cli.stats_dashboard", fake_stats_dashboard)

    result = runner.invoke(
        app,
        ["benchmark-csv-backfill", "--history-csv", str(csv_path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Rows updated: 1" in result.stdout
    assert captured_dashboard_calls == []

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["recipes"] == ""
    assert row["report_path"] == ""
    assert row["file_name"] == ""


def test_benchmark_csv_backfill_cli_writes_updates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "output" / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_15.30.00"
    processed_report = (
        tmp_path / "output" / "2026-02-16_15.29.00" / "book.excel_import_report.json"
    )

    _write_benchmark_row(csv_path, eval_dir)
    _write_prediction_manifest(eval_dir, processed_report)

    captured_dashboard: dict[str, object] = {}

    def fake_stats_dashboard(**kwargs):
        captured_dashboard.update(kwargs)

    monkeypatch.setattr("cookimport.cli.stats_dashboard", fake_stats_dashboard)

    result = runner.invoke(
        app,
        ["benchmark-csv-backfill", "--history-csv", str(csv_path)],
    )
    assert result.exit_code == 0
    assert "Rows updated: 1" in result.stdout
    assert "Recipes filled: 1" in result.stdout
    assert "Report paths filled: 1" in result.stdout
    assert captured_dashboard["output_root"] == (
        csv_path.parent.parent / "__dashboard_refresh__"
    )
    assert captured_dashboard["out_dir"] == csv_path.parent / "dashboard"
    assert captured_dashboard["open_browser"] is False
    assert captured_dashboard["since_days"] is None
    assert captured_dashboard["scan_reports"] is False

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["recipes"] == "9"
    assert row["report_path"] == str(processed_report)
    assert row["file_name"] == "book.epub"
