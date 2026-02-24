from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cookimport.analytics.perf_report import (
    PerfRow,
    append_benchmark_csv,
    append_history_csv,
    resolve_run_dir,
)


def _make_perf_row(index: int, run_dir: Path) -> PerfRow:
    return PerfRow(
        file_name=f"book-{index}.epub",
        report_path=run_dir / f"book-{index}.excel_import_report.json",
        run_dir=run_dir,
        run_timestamp=f"2026-02-24T00:00:{index % 60:02d}",
        importer_name="epub",
        total_seconds=10.0 + index,
        parsing_seconds=4.0 + index,
        writing_seconds=3.0,
        ocr_seconds=0.0,
        recipes=1,
        tips=0,
        tip_candidates=0,
        topic_candidates=0,
        standalone_blocks=None,
        standalone_topic_blocks=None,
        standalone_topic_coverage=None,
        output_files=3,
        output_bytes=1000,
        checkpoints={},
        run_config={"workers": 1, "epub_extractor": "unstructured"},
        run_config_hash=f"hash-{index}",
        run_config_summary="workers=1 | epub_extractor=unstructured",
        epub_extractor_requested="unstructured",
        epub_extractor_effective="unstructured",
        epub_auto_selected_score=None,
    )


def _append_history_rows_worker(csv_path_text: str, start_index: int, count: int) -> None:
    csv_path = Path(csv_path_text)
    run_dir = csv_path.parent / "runs" / f"worker-{start_index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [_make_perf_row(start_index + offset, run_dir) for offset in range(count)]
    append_history_csv(rows, csv_path)


def _append_benchmark_rows_worker(csv_path_text: str, start_index: int, count: int) -> None:
    csv_path = Path(csv_path_text)
    for offset in range(count):
        index = start_index + offset
        report = {
            "counts": {"gold_total": 10, "gold_matched": 8, "pred_total": 9},
            "precision": 0.8,
            "recall": 0.7,
            "f1": 0.746,
            "practical_precision": 0.9,
            "practical_recall": 0.85,
            "practical_f1": 0.874,
            "boundary": {"correct": 5, "over": 1, "under": 2, "partial": 1},
        }
        append_benchmark_csv(
            report,
            csv_path,
            run_timestamp=f"2026-02-24T00:01:{index % 60:02d}",
            run_dir=f"/tmp/benchmark/run-{index}",
            eval_scope="freeform-spans",
            source_file=f"book-{index}.epub",
            recipes=3,
            run_config={"workers": 1, "epub_extractor": "unstructured"},
            run_config_hash=f"bench-hash-{index}",
            run_config_summary="workers=1 | epub_extractor=unstructured",
        )


def test_resolve_run_dir_detects_stage_timestamp_format(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    older = out_dir / "2026-02-16_11.00.00"
    newer = out_dir / "2026-02-16_12.30.45"
    older.mkdir()
    newer.mkdir()

    resolved = resolve_run_dir(None, out_dir)
    assert resolved == newer


def test_resolve_run_dir_accepts_legacy_timestamp_format(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    legacy = out_dir / "2026-01-01-10-00-00"
    modern = out_dir / "2026-01-02_08.00.00"
    legacy.mkdir()
    modern.mkdir()

    resolved = resolve_run_dir(None, out_dir)
    assert resolved == modern


def test_append_history_csv_parallel_writes_keep_valid_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "history" / "performance_history.csv"
    worker_count = 4
    rows_per_worker = 8
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _append_history_rows_worker,
                str(csv_path),
                worker_index * rows_per_worker,
                rows_per_worker,
            )
            for worker_index in range(worker_count)
        ]
        for future in futures:
            future.result()

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        header_count = sum(
            1 for line in handle if line.startswith("run_timestamp,")
        )
    assert header_count == 1

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == worker_count * rows_per_worker


def test_append_benchmark_csv_parallel_writes_keep_valid_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "history" / "performance_history.csv"
    worker_count = 4
    rows_per_worker = 10
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _append_benchmark_rows_worker,
                str(csv_path),
                worker_index * rows_per_worker,
                rows_per_worker,
            )
            for worker_index in range(worker_count)
        ]
        for future in futures:
            future.result()

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        header_count = sum(
            1 for line in handle if line.startswith("run_timestamp,")
        )
    assert header_count == 1

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == worker_count * rows_per_worker
    assert all(row.get("run_category") == "benchmark_eval" for row in rows)
