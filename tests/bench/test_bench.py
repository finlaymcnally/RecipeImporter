"""Tests for the offline benchmark suite (cookimport.bench)."""

from __future__ import annotations

import json
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




def test_bench_speed_discover_writes_suite(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    exports = gold_root / "alpha" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"alpha.epub"}\n',
        encoding="utf-8",
    )

    suite_out = tmp_path / "suite.json"
    cli.bench_speed_discover(
        gold_root=gold_root,
        input_root=input_root,
        out=suite_out,
    )

    payload = json.loads(suite_out.read_text(encoding="utf-8"))
    assert payload["targets"]
    assert payload["targets"][0]["target_id"] == "alpha"


def test_bench_speed_run_wires_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
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
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )

    def _fake_run_speed_suite(
        suite,
        out_dir,
        *,
        scenarios,
        warmups,
        repeats,
        max_targets,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        run_settings,
        include_codex_farm_requested,
        codex_farm_confirmed,
        progress_callback,
    ):
        _ = progress_callback
        captured["include_codex_farm_requested"] = include_codex_farm_requested
        captured["codex_farm_confirmed"] = codex_farm_confirmed
        captured["suite"] = suite
        captured["out_dir"] = out_dir
        captured["scenarios"] = scenarios
        captured["warmups"] = warmups
        captured["repeats"] = repeats
        captured["max_targets"] = max_targets
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured["run_settings"] = run_settings
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=2,
        max_targets=1,
        sequence_matcher="dmp",
    )

    assert captured["suite"] == loaded_suite
    assert captured["scenarios"] == [SpeedScenario.STAGE_IMPORT]
    assert captured["warmups"] == 1
    assert captured["repeats"] == 2
    assert captured["max_targets"] == 1
    assert captured["max_parallel_tasks"] is None
    assert captured["require_process_workers"] is False
    assert captured["resume_run_dir"] is None
    assert captured["include_codex_farm_requested"] is False
    assert captured["codex_farm_confirmed"] is False
    assert isinstance(captured["run_settings"], cli.RunSettings)
    assert captured["run_settings"].benchmark_sequence_matcher == "dmp"


def test_bench_speed_run_loads_run_settings_file_and_applies_matcher_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
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
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_settings_file = tmp_path / "run_settings.json"
    run_settings_file.write_text(
        json.dumps(
            {
                "workers": 3,
                "benchmark_sequence_matcher": "not-dmp",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    def _fake_run_speed_suite(
        suite,
        out_dir,
        *,
        scenarios,
        warmups,
        repeats,
        max_targets,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        run_settings,
        include_codex_farm_requested,
        codex_farm_confirmed,
        progress_callback,
    ):
        _ = (
            suite,
            out_dir,
            scenarios,
            warmups,
            repeats,
            max_targets,
            max_parallel_tasks,
            require_process_workers,
            resume_run_dir,
            include_codex_farm_requested,
            codex_farm_confirmed,
            progress_callback,
        )
        captured["run_settings"] = run_settings
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=2,
        max_targets=1,
        run_settings_file=run_settings_file,
        sequence_matcher="dmp",
    )

    run_settings = captured["run_settings"]
    assert isinstance(run_settings, cli.RunSettings)
    assert run_settings.workers == 3
    assert run_settings.benchmark_sequence_matcher == "dmp"


def test_bench_speed_run_forwards_parallel_and_resume_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
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
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    def _fake_run_speed_suite(
        _suite,
        _out_dir,
        *,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        progress_callback,
        **kwargs,
    ):
        _ = progress_callback
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured.update(kwargs)
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=1,
        max_parallel_tasks=3,
        require_process_workers=True,
        resume_run_dir=run_root,
    )

    assert captured["max_parallel_tasks"] == 3
    assert captured["require_process_workers"] is True
    assert captured["resume_run_dir"] == run_root


def test_bench_speed_run_rejects_missing_resume_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
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

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )

    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_run(
            suite=suite_path,
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=1,
            resume_run_dir=tmp_path / "missing-run-dir",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--resume-run-dir" in failures[0]


def test_bench_speed_run_requires_codex_farm_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_run(
            suite=tmp_path / "suite.json",
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=1,
            include_codex_farm=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--speedsuite-codex-farm-confirmation" in failures[0]


def test_bench_speed_run_passes_codex_farm_confirmation_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
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
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr(
        "cookimport.cli._ensure_codex_farm_cmd_available",
        lambda _cmd: None,
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include: (True, None),
    )

    def _fake_run_speed_suite(
        _suite,
        _out_dir,
        *,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        progress_callback,
        **kwargs,
    ):
        _ = progress_callback
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured.update(kwargs)
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=1,
        include_codex_farm=True,
        speedsuite_codex_farm_confirmation=cli.SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN,
    )

    assert captured["include_codex_farm_requested"] is True
    assert captured["codex_farm_confirmed"] is True
    assert captured["max_parallel_tasks"] is None
    assert captured["require_process_workers"] is False
    assert captured["resume_run_dir"] is None


def test_bench_speed_compare_fail_on_regression_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "comparisons"

    monkeypatch.setattr(
        "cookimport.bench.speed_compare.compare_speed_runs",
        lambda **_kwargs: {
            "thresholds": {
                "regression_pct": 5.0,
                "absolute_seconds_floor": 0.5,
            },
            "rows": [],
            "missing_in_baseline": [],
            "missing_in_candidate": [],
            "overall": {"verdict": "FAIL"},
        },
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_compare.format_speed_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_compare(
            baseline=baseline,
            candidate=candidate,
            out_dir=out_dir,
            regression_pct=5.0,
            absolute_seconds_floor=0.5,
            fail_on_regression=True,
        )

    assert excinfo.value.exit_code == 1


def test_bench_speed_compare_forwards_allow_settings_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def _fake_compare_speed_runs(**kwargs):
        captured.update(kwargs)
        return {
            "thresholds": {
                "regression_pct": 5.0,
                "absolute_seconds_floor": 0.5,
            },
            "rows": [],
            "missing_in_baseline": [],
            "missing_in_candidate": [],
            "overall": {"verdict": "PASS"},
        }

    monkeypatch.setattr(
        "cookimport.bench.speed_compare.compare_speed_runs",
        _fake_compare_speed_runs,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_compare.format_speed_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_compare(
        baseline=baseline,
        candidate=candidate,
        out_dir=tmp_path / "comparisons",
        regression_pct=5.0,
        absolute_seconds_floor=0.5,
        fail_on_regression=False,
        allow_settings_mismatch=True,
    )

    assert captured["allow_settings_mismatch"] is True


def test_bench_quality_discover_writes_suite(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    exports = gold_root / "alpha" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"alpha.epub","label":"OTHER"}\n',
        encoding="utf-8",
    )
    (exports / "canonical_text.txt").write_text("abc", encoding="utf-8")

    suite_out = tmp_path / "quality_suite.json"
    cli.bench_quality_discover(
        gold_root=gold_root,
        input_root=input_root,
        out=suite_out,
        max_targets=1,
        seed=42,
    )

    payload = json.loads(suite_out.read_text(encoding="utf-8"))
    assert payload["targets"]
    assert payload["selected_target_ids"]
    assert payload["selection"]["algorithm_version"] == "quality_representative_v1"


def test_bench_quality_run_wires_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchQualitySuite(
        name="quality_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v1",
            "seed": 42,
            "max_targets": 1,
            "matched_count": 1,
            "strata_counts": {"small:sparse": 1},
        },
        targets=[
            BenchQualityTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
                source_hint="alpha.epub",
                canonical_text_chars=3,
                gold_span_rows=1,
                label_count=1,
                size_bucket="small",
                label_bucket="sparse",
            )
        ],
        selected_target_ids=["alpha"],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    experiments_file = tmp_path / "experiments.json"
    experiments_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiments": [{"id": "baseline", "run_settings_patch": {}}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    base_settings_file = tmp_path / "base_settings.json"
    base_settings_file.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.quality_suite.load_quality_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_suite.validate_quality_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )

    def _fake_run_quality_suite(
        suite,
        out_dir,
        *,
        experiments_file,
        base_run_settings_file,
        progress_callback,
        **_kwargs,
    ):
        _ = progress_callback
        captured["max_parallel_experiments"] = _kwargs.get("max_parallel_experiments")
        captured["require_process_workers"] = _kwargs.get("require_process_workers")
        captured["resume_run_dir"] = _kwargs.get("resume_run_dir")
        captured["include_codex_farm_requested"] = _kwargs.get(
            "include_codex_farm_requested"
        )
        captured["codex_farm_confirmed"] = _kwargs.get("codex_farm_confirmed")
        captured["suite"] = suite
        captured["out_dir"] = out_dir
        captured["experiments_file"] = experiments_file
        captured["base_run_settings_file"] = base_run_settings_file
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.quality_runner.run_quality_suite",
        _fake_run_quality_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_quality_run(
        suite=suite_path,
        experiments_file=experiments_file,
        out_dir=tmp_path / "runs",
        resume_run_dir=run_root,
        base_run_settings_file=base_settings_file,
    )

    assert captured["suite"] == loaded_suite
    assert captured["experiments_file"] == experiments_file
    assert captured["base_run_settings_file"] == base_settings_file
    assert captured["resume_run_dir"] == run_root
    assert captured["max_parallel_experiments"] is None
    assert captured["require_process_workers"] is False
    assert captured["include_codex_farm_requested"] is False
    assert captured["codex_farm_confirmed"] is False


def test_bench_quality_run_rejects_missing_resume_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_run(
            suite=tmp_path / "suite.json",
            experiments_file=tmp_path / "experiments.json",
            out_dir=tmp_path / "runs",
            resume_run_dir=tmp_path / "does-not-exist",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--resume-run-dir must point to an existing directory" in failures[0]


def test_bench_quality_run_requires_codex_farm_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_run(
            suite=tmp_path / "suite.json",
            experiments_file=tmp_path / "experiments.json",
            out_dir=tmp_path / "runs",
            include_codex_farm=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--qualitysuite-codex-farm-confirmation" in failures[0]


def test_bench_quality_run_passes_codex_farm_confirmation_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchQualitySuite(
        name="quality_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v1",
            "seed": 42,
            "max_targets": 1,
            "matched_count": 1,
            "strata_counts": {"small:sparse": 1},
        },
        targets=[
            BenchQualityTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
                source_hint="alpha.epub",
                canonical_text_chars=3,
                gold_span_rows=1,
                label_count=1,
                size_bucket="small",
                label_bucket="sparse",
            )
        ],
        selected_target_ids=["alpha"],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    experiments_file = tmp_path / "experiments.json"
    experiments_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiments": [{"id": "baseline", "run_settings_patch": {}}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.quality_suite.load_quality_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_suite.validate_quality_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr(
        "cookimport.cli._ensure_codex_farm_cmd_available",
        lambda _cmd: None,
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include: (True, None),
    )

    def _fake_run_quality_suite(
        _suite,
        _out_dir,
        *,
        progress_callback,
        **kwargs,
    ):
        _ = progress_callback
        captured.update(kwargs)
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.quality_runner.run_quality_suite",
        _fake_run_quality_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_quality_run(
        suite=suite_path,
        experiments_file=experiments_file,
        out_dir=tmp_path / "runs",
        require_process_workers=True,
        include_codex_farm=True,
        qualitysuite_codex_farm_confirmation=cli.QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN,
    )

    assert captured["include_codex_farm_requested"] is True
    assert captured["codex_farm_confirmed"] is True
    assert captured["require_process_workers"] is True


def test_bench_quality_lightweight_series_wires_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "lightweight" / "2026-03-01_10.15.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "lightweight_series_report.md").write_text("", encoding="utf-8")
    (run_root / "lightweight_series_summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )

    def _fake_run_quality_lightweight_series(
        *,
        gold_root,
        input_root,
        experiments_file,
        thresholds_file,
        profile_file,
        out_dir,
        resume_series_dir,
        max_parallel_experiments,
        require_process_workers,
        command,
        progress_callback,
    ):
        _ = progress_callback
        captured["gold_root"] = gold_root
        captured["input_root"] = input_root
        captured["experiments_file"] = experiments_file
        captured["thresholds_file"] = thresholds_file
        captured["profile_file"] = profile_file
        captured["out_dir"] = out_dir
        captured["resume_series_dir"] = resume_series_dir
        captured["max_parallel_experiments"] = max_parallel_experiments
        captured["require_process_workers"] = require_process_workers
        captured["command"] = command
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.quality_lightweight_series.run_quality_lightweight_series",
        _fake_run_quality_lightweight_series,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    gold_root = tmp_path / "gold"
    input_root = tmp_path / "input"
    experiments_file = tmp_path / "experiments.json"
    thresholds_file = tmp_path / "thresholds.json"
    profile_file = tmp_path / "profile.json"

    cli.bench_quality_lightweight_series(
        gold_root=gold_root,
        input_root=input_root,
        profile_file=profile_file,
        experiments_file=experiments_file,
        thresholds_file=thresholds_file,
        out_dir=tmp_path / "lightweight",
        max_parallel_experiments=3,
        require_process_workers=True,
    )

    assert captured["gold_root"] == gold_root
    assert captured["input_root"] == input_root
    assert captured["profile_file"] == profile_file
    assert captured["experiments_file"] == experiments_file
    assert captured["thresholds_file"] == thresholds_file
    assert captured["out_dir"] == tmp_path / "lightweight"
    assert captured["resume_series_dir"] is None
    assert captured["max_parallel_experiments"] == 3
    assert captured["require_process_workers"] is True
    assert "quality-lightweight-series" in str(captured["command"])


def test_bench_quality_lightweight_series_rejects_missing_resume_series_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_lightweight_series(
            gold_root=tmp_path / "gold",
            input_root=tmp_path / "input",
            profile_file=tmp_path / "profile.json",
            experiments_file=tmp_path / "experiments.json",
            thresholds_file=tmp_path / "thresholds.json",
            out_dir=tmp_path / "lightweight",
            resume_series_dir=tmp_path / "missing-series-dir",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--resume-series-dir must point to an existing directory" in failures[0]


def test_bench_quality_compare_fail_on_regression_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "comparisons"

    monkeypatch.setattr(
        "cookimport.bench.quality_compare.compare_quality_runs",
        lambda **_kwargs: {
            "metric_deltas": {},
            "overall": {"verdict": "FAIL", "reasons": ["regression"]},
        },
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_compare.format_quality_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_compare(
            baseline=baseline,
            candidate=candidate,
            out_dir=out_dir,
            strict_f1_drop_max=0.005,
            practical_f1_drop_max=0.005,
            source_success_rate_drop_max=0.0,
            fail_on_regression=True,
        )

    assert excinfo.value.exit_code == 1


def test_bench_quality_compare_forwards_selection_and_mismatch_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def _fake_compare_quality_runs(**kwargs):
        captured.update(kwargs)
        return {
            "metric_deltas": {},
            "overall": {"verdict": "PASS", "reasons": []},
        }

    monkeypatch.setattr(
        "cookimport.bench.quality_compare.compare_quality_runs",
        _fake_compare_quality_runs,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_compare.format_quality_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_quality_compare(
        baseline=baseline,
        candidate=candidate,
        out_dir=tmp_path / "comparisons",
        baseline_experiment_id="baseline",
        candidate_experiment_id="candidate",
        strict_f1_drop_max=0.005,
        practical_f1_drop_max=0.005,
        source_success_rate_drop_max=0.0,
        fail_on_regression=False,
        allow_settings_mismatch=True,
    )

    assert captured["baseline_experiment_id"] == "baseline"
    assert captured["candidate_experiment_id"] == "candidate"
    assert captured["allow_settings_mismatch"] is True


def test_bench_quality_leaderboard_saves_qualitysuite_winner_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "quality_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "leaderboards" / "baseline" / "2026-02-28_12.00.00"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "winner_run_settings": {
            "epub_extractor": "unstructured",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "semantic_v1",
            "llm_recipe_pipeline": "off",
        },
        "winner": {
            "rank": 1,
            "config_id": "winnerid",
            "coverage_sources": 1,
            "mean_practical_f1": 0.5,
            "mean_strict_f1": 0.4,
            "median_duration_seconds": 8.0,
        },
        "leaderboard": [],
        "total_source_groups": 1,
    }
    captured: dict[str, object] = {}

    class _Paths:
        def __init__(self, root: Path) -> None:
            self.out_dir = root
            self.leaderboard_json = root / "leaderboard.json"
            self.leaderboard_csv = root / "leaderboard.csv"
            self.pareto_json = root / "pareto_frontier.json"
            self.pareto_csv = root / "pareto_frontier.csv"
            self.winner_run_settings_json = root / "winner_run_settings.json"
            self.winner_dimensions_json = root / "winner_dimensions.json"

    monkeypatch.setattr(
        "cookimport.bench.quality_leaderboard.build_quality_leaderboard",
        lambda **_kwargs: payload,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_leaderboard.write_quality_leaderboard_artifacts",
        lambda _payload, *, out_dir: _Paths(out_dir),
    )

    def _fake_save_qualitysuite_winner_run_settings(output_dir, settings):
        captured["output_dir"] = output_dir
        captured["settings"] = settings

    monkeypatch.setattr(
        cli,
        "save_qualitysuite_winner_run_settings",
        _fake_save_qualitysuite_winner_run_settings,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("typer.echo", lambda *_args, **_kwargs: None)

    cli.bench_quality_leaderboard(
        experiment_id="baseline",
        run_dir=run_dir,
        out_dir=out_dir,
        top_n=5,
    )

    assert str(captured["output_dir"]).endswith("data/output")
    assert isinstance(captured["settings"], cli.RunSettings)
    settings = captured["settings"]
    assert settings.epub_extractor.value == "unstructured"
    assert settings.epub_unstructured_html_parser_version.value == "v2"
    assert settings.epub_unstructured_preprocess_mode.value == "semantic_v1"


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
