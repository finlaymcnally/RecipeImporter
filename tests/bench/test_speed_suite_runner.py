from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.speed_runner import (
    SpeedScenario,
    parse_speed_scenarios,
    run_speed_suite,
)
from cookimport.bench.speed_suite import SpeedSuite, SpeedTarget


def test_parse_speed_scenarios_validates_and_dedupes() -> None:
    parsed = parse_speed_scenarios(
        "stage_import,benchmark_canonical_legacy,stage_import"
    )
    assert parsed == [
        SpeedScenario.STAGE_IMPORT,
        SpeedScenario.BENCHMARK_CANONICAL_LEGACY,
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

    def _fake_stage(*, source_file: Path, sample_dir: Path) -> dict[str, object]:
        _ = (source_file, sample_dir)
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
        sequence_matcher: str,
    ) -> dict[str, object]:
        _ = (source_file, gold_spans_path, sample_dir, execution_mode, sequence_matcher)
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
        sequence_matcher="fallback",
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
