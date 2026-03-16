from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cookimport.analytics.benchmark_timing import collect_all_method_timing_summary
from cookimport.analytics.perf_report import (
    PerfRow,
    append_benchmark_csv,
    append_history_csv,
    resolve_run_dir,
)
from cookimport.paths import HISTORY_ROOT, OUTPUT_ROOT, history_csv_for_output, history_root_for_output

REMOVED_EXTRACTOR_VALUE = "leg" "acy"


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


def test_resolve_run_dir_ignores_noncanonical_timestamp_format(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    noncanonical = out_dir / "2026-01-01-10-00-00"
    modern = out_dir / "2026-01-02_08.00.00"
    noncanonical.mkdir()
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


def test_history_root_for_repo_local_output_is_repo_history_root() -> None:
    assert history_root_for_output(OUTPUT_ROOT) == HISTORY_ROOT
    assert history_csv_for_output(OUTPUT_ROOT) == HISTORY_ROOT / "performance_history.csv"


def test_history_root_for_external_output_uses_output_parent(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    assert history_root_for_output(output_root) == tmp_path / ".history"
    assert history_csv_for_output(output_root) == tmp_path / ".history" / "performance_history.csv"


def test_collect_all_method_timing_summary_from_report_payloads(tmp_path: Path) -> None:
    all_method_root = (
        tmp_path
        / "golden"
        / "benchmark-vs-golden"
        / "2026-02-24_08.00.00"
        / "all-method-benchmark"
    )
    source_a = all_method_root / "book_a"
    source_b = all_method_root / "book_b"
    source_a.mkdir(parents=True, exist_ok=True)
    source_b.mkdir(parents=True, exist_ok=True)

    (source_a / "all_method_benchmark_report.json").write_text(
        """{
  "variants": [
    {
      "config_dir": "config_001",
      "status": "ok",
      "run_config_hash": "hash-a1",
      "run_config_summary": "extractor=removed_value",
      "timing": {"total_seconds": 4.0}
    },
    {
      "config_dir": "config_002",
      "status": "ok",
      "run_config_hash": "hash-a2",
      "run_config_summary": "extractor=markdown",
      "timing": {"total_seconds": 6.0}
    }
  ]
}
""",
        encoding="utf-8",
    )
    (source_b / "all_method_benchmark_report.json").write_text(
        """{
  "variants": [
    {
      "config_dir": "config_001",
      "status": "ok",
      "run_config_hash": "hash-b1",
      "run_config_summary": "extractor=unstructured",
      "timing": {"total_seconds": 10.0}
    }
  ]
}
""",
        encoding="utf-8",
    )

    payload = collect_all_method_timing_summary(all_method_root)

    assert payload["timing_summary"]["source_count"] == 2
    assert payload["timing_summary"]["variant_count"] == 3
    assert payload["timing_summary"]["source_total_seconds"] == 20.0
    assert payload["timing_summary"]["slowest_source"] in {"book_a", "book_b"}
    assert payload["timing_summary"]["slowest_config"] == "book_b/config_001"
