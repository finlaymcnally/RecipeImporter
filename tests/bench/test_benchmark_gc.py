from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.analytics.dashboard_collect import collect_dashboard_data
from cookimport.analytics.perf_report import _CSV_FIELDS
from cookimport.bench.artifact_gc import run_benchmark_gc
from cookimport.cli import _prune_benchmark_outputs, app


runner = CliRunner()


def _write_history_row(csv_path: Path, run_dir: Path, *, report_path: Path | None = None) -> None:
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
            "strict_accuracy": "0.42",
            "macro_f1_excluding_other": "0.33",
            "boundary_correct": "4",
            "boundary_over": "1",
            "boundary_under": "2",
            "boundary_partial": "0",
            "per_label_json": '[{"gold_total":2,"label":"INGREDIENT_LINE","precision":0.1,"pred_total":3,"recall":0.2}]',
        }
    )
    if report_path is not None:
        row["report_path"] = str(report_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_history_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            rendered = {field: "" for field in _CSV_FIELDS}
            rendered.update(row)
            writer.writerow(rendered)


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

    assert result.pruned_run_roots == 0
    assert result.skipped_unconfirmed_run_roots == 1
    assert result.kept_run_roots == 2
    assert result.reclaimed_bytes == 0
    assert old_run.exists()
    assert new_run.exists()


def test_benchmark_gc_apply_prunes_runs_without_mutating_csv(tmp_path: Path) -> None:
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
    assert result.history_rows_updated == 0
    assert result.history_rows_pruned == 0
    assert result.history_backup_path is None
    assert not run_dir.exists()

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["per_label_json"]
    assert row["strict_accuracy"] == "0.42"
    assert row["macro_f1_excluding_other"] == "0.33"
    assert row["boundary_correct"] == "4"


def test_benchmark_gc_apply_prune_keeps_csv_unchanged_when_already_durable(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)
    output_root = tmp_path / "output"
    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_rows(
        csv_path,
        [
            {
                "run_timestamp": "2026-02-16T15:00:00",
                "run_dir": str(run_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "file_name": "book.epub",
                "strict_accuracy": "0.42",
                "macro_f1_excluding_other": "0.33",
                "boundary_correct": "4",
                "boundary_over": "1",
                "boundary_under": "2",
                "boundary_partial": "0",
                "per_label_json": '[{"gold_total":2,"label":"INGREDIENT_LINE","precision":0.1,"pred_total":3,"recall":0.2}]',
            }
        ],
    )

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.pruned_run_roots == 1
    assert result.history_rows_updated == 0
    assert result.history_rows_pruned == 0
    assert result.history_backup_path is None
    assert not run_dir.exists()


def test_benchmark_gc_apply_without_history_csv_keeps_unconfirmed_runs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.total_run_roots == 1
    assert result.pruned_run_roots == 0
    assert result.skipped_unconfirmed_run_roots == 1
    assert run_dir.exists()


def test_benchmark_gc_apply_with_unmatched_history_keeps_unconfirmed_runs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)

    csv_path = tmp_path / ".history" / "performance_history.csv"
    other_run = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-02_10.00.00"
    _write_history_row(csv_path, other_run)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.total_run_roots == 1
    assert result.pruned_run_roots == 0
    assert result.skipped_unconfirmed_run_roots == 1
    assert run_dir.exists()


def test_benchmark_gc_apply_is_idempotent_without_csv_backup_or_mutation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)
    output_root = tmp_path / "output"
    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, run_dir)

    first = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )
    assert first.pruned_run_roots == 1
    assert first.history_rows_updated == 0
    assert first.history_rows_pruned == 0
    assert first.history_backup_path is None

    second = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )
    assert second.total_run_roots == 0
    assert second.pruned_run_roots == 0
    assert second.history_rows_updated == 0
    assert second.history_rows_pruned == 0
    assert second.history_backup_path is None


def test_benchmark_gc_preserves_dashboard_rows_after_prune(tmp_path: Path) -> None:
    run_root = tmp_path / "golden" / "benchmark-vs-golden" / "2026-02-01_10.00.00"
    run_dir = run_root / "single-book-benchmark" / "book" / "vanilla"
    _write_eval_report(run_dir)
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
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=0,
    )
    assert result.pruned_run_roots == 1
    assert not run_root.exists()

    data = collect_dashboard_data(
        output_root=output_root,
        golden_root=tmp_path / "golden",
    )
    assert len(data.benchmark_records) == 1
    record = data.benchmark_records[0]
    assert record.strict_accuracy == 0.42
    assert record.macro_f1_excluding_other == 0.33
    assert len(record.per_label) == 1


def test_benchmark_gc_keeps_unconfirmed_runs_when_history_rows_lack_durable_metrics(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "golden" / "bench" / "quality" / "runs" / "2026-02-01_10.00.00"
    _write_eval_report(run_dir)
    output_root = tmp_path / "output"
    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_rows(
        csv_path,
        [
            {
                "run_timestamp": "2026-02-16T15:00:00",
                "run_dir": str(run_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "file_name": "book.epub",
            },
            {
                "run_timestamp": "2026-02-16T15:00:01",
                "run_dir": str(run_dir / "config_001"),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "file_name": "book.epub",
            },
        ],
    )

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.pruned_run_roots == 0
    assert result.skipped_unconfirmed_run_roots == 1
    assert result.history_rows_pruned == 0
    assert run_dir.exists()
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["run_dir"] == str(run_dir)
    assert rows[1]["run_dir"] == str(run_dir / "config_001")


def test_benchmark_gc_drop_speed_artifacts_overrides_keep_policy(tmp_path: Path) -> None:
    speed_run = tmp_path / "golden" / "bench" / "speed" / "runs" / "2026-02-03_10.00.00"
    _write_eval_report(speed_run)
    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, speed_run)

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
    assert "candidate output run roots:" in result.stdout
    assert "no files changed (dry-run)" in result.stdout


def test_benchmark_gc_can_prune_labelstudio_benchmark_roots_when_enabled(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "golden" / "benchmark-vs-golden" / "2026-02-01_10.00.00"
    eval_dir = run_root / "single-book-benchmark" / "book" / "vanilla"
    _write_eval_report(eval_dir)

    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, eval_dir)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=0,
    )

    assert result.pruned_labelstudio_run_roots == 1
    assert not run_root.exists()


def test_benchmark_gc_keep_sentinel_skips_labelstudio_prune(tmp_path: Path) -> None:
    run_root = tmp_path / "golden" / "benchmark-vs-golden" / "2026-02-01_10.00.00"
    eval_dir = run_root / "single-book-benchmark" / "book" / "vanilla"
    _write_eval_report(eval_dir)
    (run_root / ".gc_keep.2026-02-20_10.00.00.txt").write_text(
        "Pinned.\n",
        encoding="utf-8",
    )

    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, eval_dir)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=0,
    )

    assert result.pruned_labelstudio_run_roots == 0
    assert result.pinned_kept_run_roots == 1
    assert run_root.exists()


def test_benchmark_gc_can_prune_labelstudio_processed_outputs_when_confirmed(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "golden" / "benchmark-vs-golden" / "2026-02-01_10.00.00"
    eval_dir = run_root / "single-book-benchmark" / "book" / "vanilla"
    _write_eval_report(eval_dir)

    output_root = tmp_path / "output"
    processed_root = output_root / run_root.name
    processed_report = processed_root / "report.json"
    processed_report.parent.mkdir(parents=True, exist_ok=True)
    processed_report.write_text("{}", encoding="utf-8")

    csv_path = tmp_path / ".history" / "performance_history.csv"
    _write_history_row(csv_path, eval_dir, report_path=processed_report)

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=0,
        wipe_output_runs=False,
        prune_benchmark_processed_outputs=True,
    )

    assert result.pruned_labelstudio_run_roots == 1
    assert result.pruned_processed_output_roots == 1
    assert not run_root.exists()
    assert not processed_root.exists()


def test_benchmark_gc_wipes_output_run_roots_but_preserves_history_dashboard(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    run_root = output_root / "2026-03-20_11.16.53"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.json").write_text("{}", encoding="utf-8")
    dashboard_dir = output_root / "history" / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    (dashboard_dir / "index.html").write_text("ok", encoding="utf-8")

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=output_root,
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
    )

    assert result.total_output_run_roots == 1
    assert result.pruned_output_run_roots == 1
    assert not run_root.exists()
    assert dashboard_dir.exists()


def test_benchmark_gc_keeps_five_newest_labelstudio_runs_and_cache_dir(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "golden" / "benchmark-vs-golden"
    kept_names = []
    for day in range(1, 8):
        run_root = benchmark_root / f"2026-03-0{day}_10.00.00"
        _write_eval_report(run_root / "single-book-benchmark" / "book" / "vanilla")
        kept_names.append(run_root.name)
    cache_dir = benchmark_root / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "cache.txt").write_text("ok", encoding="utf-8")

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=5,
        wipe_output_runs=False,
    )

    assert result.pruned_labelstudio_run_roots == 2
    remaining = sorted(
        path.name for path in benchmark_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )
    assert remaining == kept_names[-5:]
    assert cache_dir.exists()


def test_benchmark_gc_collects_hyphen_suffixed_labelstudio_run_dirs(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "golden" / "benchmark-vs-golden"
    old_run = benchmark_root / "2026-03-16_19.50.00-title-probe"
    new_run = benchmark_root / "2026-03-21_11.17.08"
    _write_eval_report(old_run / "single-book-benchmark" / "book" / "vanilla")
    _write_eval_report(new_run / "single-book-benchmark" / "book" / "vanilla")

    result = run_benchmark_gc(
        golden_root=tmp_path / "golden",
        output_root=tmp_path / "output",
        keep_full_runs=0,
        keep_full_days=0,
        dry_run=False,
        drop_speed_artifacts=False,
        include_labelstudio_benchmark=True,
        keep_labelstudio_runs=1,
        wipe_output_runs=False,
    )

    assert result.pruned_labelstudio_run_roots == 1
    assert not old_run.exists()
    assert new_run.exists()


def test_prune_benchmark_outputs_removes_eval_and_processed_dirs(
    tmp_path: Path,
) -> None:
    eval_root = (
        tmp_path
        / "golden"
        / "benchmark-vs-golden"
        / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    )
    eval_root.mkdir(parents=True, exist_ok=True)
    (eval_root / "eval_report.json").write_text("{}", encoding="utf-8")
    processed_root = tmp_path / "output" / eval_root.name
    processed_root.mkdir(parents=True, exist_ok=True)
    (processed_root / "dummy.txt").write_text("ok", encoding="utf-8")

    _prune_benchmark_outputs(
        eval_output_dir=eval_root,
        processed_run_root=processed_root,
        suppress_summary=True,
        suppress_output_prune=False,
    )

    assert not eval_root.exists()
    assert not processed_root.exists()


def test_prune_benchmark_outputs_keeps_official_run_dirs(
    tmp_path: Path,
) -> None:
    eval_root = (
        tmp_path
        / "golden"
        / "benchmark-vs-golden"
        / "2026-03-03_02.10.00"
    )
    eval_root.mkdir(parents=True, exist_ok=True)
    (eval_root / "eval_report.json").write_text("{}", encoding="utf-8")
    processed_root = tmp_path / "output" / eval_root.name
    processed_root.mkdir(parents=True, exist_ok=True)
    (processed_root / "dummy.txt").write_text("ok", encoding="utf-8")

    _prune_benchmark_outputs(
        eval_output_dir=eval_root,
        processed_run_root=processed_root,
        suppress_summary=True,
        suppress_output_prune=False,
    )

    assert eval_root.exists()
    assert processed_root.exists()
