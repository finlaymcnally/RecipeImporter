from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.analytics.perf_report import _CSV_FIELDS
from cookimport.bench.artifact_gc import run_benchmark_gc
from cookimport.cli import app


runner = CliRunner()


def _write_history_row(csv_path: Path, run_dir: Path) -> None:
    row = {field: "" for field in _CSV_FIELDS}
    row.update(
        {
            "run_timestamp": "2026-02-16T15:00:00",
            "run_dir": str(run_dir),
            "run_category": "benchmark_eval",
            "eval_scope": "freeform-spans",
            "file_name": "book.epub",
            "precision": "0.1",
            "recall": "0.2",
        }
    )
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_eval_report(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "strict_accuracy": 0.42,
                "macro_f1_excluding_other": 0.33,
                "per_label": {
                    "INGREDIENT_LINE": {
                        "precision": 0.1,
                        "recall": 0.2,
                        "gold_total": 2,
                        "pred_total": 3,
                    }
                },
                "boundary": {
                    "correct": 4,
                    "over": 1,
                    "under": 2,
                    "partial": 0,
                },
            }
        ),
        encoding="utf-8",
    )


def test_benchmark_gc_dry_run_keeps_files_unchanged(tmp_path: Path) -> None:
    old_run = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    new_run = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-02_10.00.00"
    _write_eval_report(old_run)
    _write_eval_report(new_run)
    (old_run / "payload.bin").write_bytes(b"x" * 2048)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=1,
        keep_full_days=0,
        dry_run=True,
        drop_speed_artifacts=False,
    )

    assert result.pruned_run_roots == 1
    assert result.kept_run_roots == 1
    assert result.reclaimed_bytes >= 2048
    assert old_run.exists()
    assert new_run.exists()


def test_benchmark_gc_apply_hydrates_csv_then_prunes_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)
    (run_dir / "payload.bin").write_bytes(b"y" * 512)

    output_root = tmp_path / "output"
    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, run_dir)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.pruned_run_roots == 1
    assert result.history_rows_scanned == 1
    assert result.history_rows_updated == 1
    assert result.history_backup_path is not None
    backup_path = Path(result.history_backup_path)
    assert backup_path.exists()
    assert not run_dir.exists()

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["per_label_json"]
    assert row["strict_accuracy"] == "0.42"
    assert row["macro_f1_excluding_other"] == "0.33"
    assert row["boundary_correct"] == "4"


def test_benchmark_gc_drop_speed_artifacts_overrides_keep_policy(tmp_path: Path) -> None:
    speed_run = tmp_path / "golden" / "bench" / "speed" / "runs" / "2026-02-03_10.00.00"
    _write_eval_report(speed_run)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=99,
        keep_full_days=3650,
        dry_run=True,
        drop_speed_artifacts=True,
    )

    assert result.pruned_speed_run_roots == 1
    assert result.kept_run_roots == 0


def test_bench_gc_cli_dry_run_outputs_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)

    result = runner.invoke(
        app,
        [
            "bench",
            "gc",
            "--golden-root",
            str(tmp_path / "golden"),
            "--output-root",
            str(tmp_path / "output"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Benchmark GC Dry Run" in result.stdout
    assert "no files changed (dry-run)" in result.stdout
