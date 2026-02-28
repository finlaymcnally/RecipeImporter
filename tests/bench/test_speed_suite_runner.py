from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cookimport.bench.speed_runner import (
    SpeedScenario,
    parse_speed_scenarios,
    run_speed_suite,
)
from cookimport.bench.speed_suite import SpeedSuite, SpeedTarget
from cookimport.config.run_settings import RunSettings


def test_parse_speed_scenarios_validates_and_dedupes() -> None:
    parsed = parse_speed_scenarios(
        "stage_import,benchmark_all_method_multi_source,stage_import"
    )
    assert parsed == [
        SpeedScenario.STAGE_IMPORT,
        SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE,
    ]

    with pytest.raises(ValueError):
        parse_speed_scenarios("nope")


def test_run_speed_suite_writes_artifacts_and_excludes_warmups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    suite = SpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )

    stage_total_values = iter([100.0, 10.0, 12.0])
    benchmark_total_values = iter([200.0, 20.0, 22.0])

    def _fake_stage(
        *,
        source_file: Path,
        sample_dir: Path,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, sample_dir, run_settings)
        total = next(stage_total_values)
        return {
            "total_seconds": total,
            "parsing_seconds": total / 2.0,
            "writing_seconds": total / 4.0,
            "timing": {"total_seconds": total},
        }

    def _fake_benchmark(
        *,
        source_file: Path,
        gold_spans_path: Path,
        sample_dir: Path,
        execution_mode: str,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, gold_spans_path, sample_dir, execution_mode, run_settings)
        total = next(benchmark_total_values)
        return {
            "total_seconds": total,
            "prediction_seconds": total / 4.0,
            "evaluation_seconds": total / 2.0,
            "timing": {"total_seconds": total},
        }

    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_stage_import_sample",
        _fake_stage,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_benchmark_sample",
        _fake_benchmark,
    )

    progress_messages: list[str] = []
    run_root = run_speed_suite(
        suite,
        tmp_path / "runs",
        scenarios=[
            SpeedScenario.STAGE_IMPORT,
            SpeedScenario.BENCHMARK_CANONICAL_LEGACY,
        ],
        warmups=1,
        repeats=2,
        max_targets=1,
        run_settings=RunSettings.from_dict({}, warn_context="test speed runner"),
        progress_callback=progress_messages.append,
    )

    assert (run_root / "suite_resolved.json").exists()
    assert (run_root / "samples.jsonl").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "report.md").exists()
    assert (run_root / "run_manifest.json").exists()
    assert progress_messages
    assert "task 1/6" in progress_messages[0]

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    rows = {
        (row["target_id"], row["scenario"]): row
        for row in summary["summary_rows"]
    }
    stage_row = rows[("alpha", "stage_import")]
    bench_row = rows[("alpha", "benchmark_canonical_legacy")]

    # Warmup values (100, 200) are excluded; medians come from repeat-only values.
    assert stage_row["median_total_seconds"] == pytest.approx(11.0)
    assert bench_row["median_total_seconds"] == pytest.approx(21.0)
    assert summary["run_settings_hash"]
    assert summary["sequence_matcher"] == "dmp"


def test_run_speed_suite_rejects_codex_farm_without_confirmation(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    suite = SpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )

    with pytest.raises(ValueError) as excinfo:
        run_speed_suite(
            suite,
            tmp_path / "runs",
            scenarios=[SpeedScenario.STAGE_IMPORT],
            warmups=0,
            repeats=1,
            run_settings=RunSettings.from_dict({}, warn_context="test speed runner"),
            include_codex_farm_requested=True,
            codex_farm_confirmed=False,
            progress_callback=None,
        )

    assert "explicit positive user confirmation" in str(excinfo.value)


def test_run_speed_suite_all_method_multi_source_runs_once_per_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "alpha.epub"
    source_b = tmp_path / "beta.epub"
    source_a.write_text("epub", encoding="utf-8")
    source_b.write_text("epub", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")
    gold_b.write_text('{"source_file":"beta.epub"}\n', encoding="utf-8")

    suite = SpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str(tmp_path.resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_a.resolve()),
                gold_spans_path=str(gold_a.resolve()),
            ),
            SpeedTarget(
                target_id="beta",
                source_file=str(source_b.resolve()),
                gold_spans_path=str(gold_b.resolve()),
            ),
        ],
        unmatched=[],
    )

    total_values = iter([100.0, 10.0, 12.0])
    target_counts_seen: list[int] = []

    def _fake_all_method(
        *,
        targets: list[SpeedTarget],
        sample_dir: Path,
        run_settings: RunSettings,
        include_codex_farm_requested: bool,
    ) -> dict[str, object]:
        _ = (sample_dir, run_settings, include_codex_farm_requested)
        target_counts_seen.append(len(targets))
        total = next(total_values)
        return {
            "total_seconds": total,
            "timing": {"total_seconds": total},
        }

    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_all_method_multi_source_sample",
        _fake_all_method,
    )

    progress_messages: list[str] = []
    run_root = run_speed_suite(
        suite,
        tmp_path / "runs",
        scenarios=[SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE],
        warmups=1,
        repeats=2,
        max_targets=None,
        run_settings=RunSettings.from_dict({}, warn_context="test speed runner"),
        progress_callback=progress_messages.append,
    )

    assert target_counts_seen == [2, 2, 2]
    assert progress_messages
    assert "task 1/3" in progress_messages[0]

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    rows = {
        (row["target_id"], row["scenario"]): row
        for row in summary["summary_rows"]
    }
    assert rows[
        (
            "__all_matched__",
            SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE.value,
        )
    ]["median_total_seconds"] == pytest.approx(11.0)


def test_run_speed_suite_parallel_task_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    suite = SpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )

    stage_started = threading.Event()
    benchmark_started = threading.Event()

    def _fake_stage(
        *,
        source_file: Path,
        sample_dir: Path,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, sample_dir, run_settings)
        stage_started.set()
        benchmark_started.wait(timeout=0.6)
        time.sleep(0.05)
        return {"total_seconds": 10.0, "timing": {"total_seconds": 10.0}}

    def _fake_benchmark(
        *,
        source_file: Path,
        gold_spans_path: Path,
        sample_dir: Path,
        execution_mode: str,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, gold_spans_path, sample_dir, execution_mode, run_settings)
        benchmark_started.set()
        stage_started.wait(timeout=0.6)
        time.sleep(0.05)
        return {"total_seconds": 20.0, "timing": {"total_seconds": 20.0}}

    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_stage_import_sample",
        _fake_stage,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_benchmark_sample",
        _fake_benchmark,
    )

    started = time.perf_counter()
    run_speed_suite(
        suite,
        tmp_path / "runs",
        scenarios=[
            SpeedScenario.STAGE_IMPORT,
            SpeedScenario.BENCHMARK_CANONICAL_LEGACY,
        ],
        warmups=0,
        repeats=1,
        max_parallel_tasks=2,
        run_settings=RunSettings.from_dict({}, warn_context="test speed runner parallel"),
        progress_callback=None,
    )
    elapsed = max(0.0, time.perf_counter() - started)

    # Serial dispatch would block on the 0.6s cross-wait; parallel dispatch stays well below.
    assert elapsed < 0.5


def test_run_speed_suite_resume_reuses_completed_task_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    suite = SpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )

    call_counts: dict[str, int] = {"stage": 0, "benchmark": 0}
    should_fail_benchmark = {"value": True}

    def _fake_stage(
        *,
        source_file: Path,
        sample_dir: Path,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, sample_dir, run_settings)
        call_counts["stage"] += 1
        return {"total_seconds": 10.0, "timing": {"total_seconds": 10.0}}

    def _fake_benchmark(
        *,
        source_file: Path,
        gold_spans_path: Path,
        sample_dir: Path,
        execution_mode: str,
        run_settings: RunSettings,
    ) -> dict[str, object]:
        _ = (source_file, gold_spans_path, sample_dir, execution_mode, run_settings)
        call_counts["benchmark"] += 1
        if should_fail_benchmark["value"]:
            raise RuntimeError("boom")
        return {"total_seconds": 20.0, "timing": {"total_seconds": 20.0}}

    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_stage_import_sample",
        _fake_stage,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner._run_benchmark_sample",
        _fake_benchmark,
    )

    runs_root = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="boom"):
        run_speed_suite(
            suite,
            runs_root,
            scenarios=[
                SpeedScenario.STAGE_IMPORT,
                SpeedScenario.BENCHMARK_CANONICAL_LEGACY,
            ],
            warmups=0,
            repeats=1,
            max_parallel_tasks=1,
            run_settings=RunSettings.from_dict({}, warn_context="test speed runner resume"),
            progress_callback=None,
        )

    run_dirs = sorted(path for path in runs_root.iterdir() if path.is_dir())
    assert len(run_dirs) == 1
    run_root = run_dirs[0]
    assert (run_root / "checkpoint.json").exists()

    should_fail_benchmark["value"] = False
    resumed_root = run_speed_suite(
        suite,
        runs_root,
        scenarios=[
            SpeedScenario.STAGE_IMPORT,
            SpeedScenario.BENCHMARK_CANONICAL_LEGACY,
        ],
        warmups=0,
        repeats=1,
        max_parallel_tasks=1,
        resume_run_dir=run_root,
        run_settings=RunSettings.from_dict({}, warn_context="test speed runner resume"),
        progress_callback=None,
    )
    assert resumed_root == run_root
    # Stage completed in the failed first attempt and is reused from snapshot.
    assert call_counts["stage"] == 1
    # Benchmark ran once for the failed attempt and once after resume.
    assert call_counts["benchmark"] == 2

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    rows = {
        (row["target_id"], row["scenario"]): row
        for row in summary["summary_rows"]
    }
    assert rows[("alpha", "stage_import")]["median_total_seconds"] == pytest.approx(10.0)
    assert rows[("alpha", "benchmark_canonical_legacy")]["median_total_seconds"] == pytest.approx(20.0)
