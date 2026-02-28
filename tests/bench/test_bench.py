"""Tests for the offline benchmark suite (cookimport.bench)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

import cookimport.cli as cli
from cookimport.bench.suite import BenchItem, BenchSuite, load_suite, validate_suite
from cookimport.bench.report import aggregate_metrics, format_suite_report_md
from cookimport.bench.trace import TraceCollector
from cookimport.bench.speed_runner import SpeedScenario
from cookimport.bench.speed_suite import SpeedSuite as BenchSpeedSuite, SpeedTarget
from cookimport.bench.quality_suite import (
    QualitySuite as BenchQualitySuite,
    QualityTarget as BenchQualityTarget,
)
from cookimport.bench.knobs import (
    Tunable,
    effective_knobs,
    list_knobs,
    load_config,
    validate_knobs,
)
from cookimport.bench.noise import consolidate_predictions, dedupe_predictions, gate_noise
from cookimport.bench.cost import estimate_llm_costs, write_escalation_queue
from cookimport.bench.packet import build_iteration_packet
from cookimport.bench.pred_run import build_pred_run_for_source


# ---------------------------------------------------------------------------
# Suite model validation
# ---------------------------------------------------------------------------


def test_bench_suite_model_valid():
    suite = BenchSuite(
        name="test",
        items=[
            BenchItem(
                item_id="book1",
                source_path="data/input/test.epub",
                gold_dir="data/golden/test/labelstudio/book",
            )
        ],
    )
    assert suite.name == "test"
    assert len(suite.items) == 1
    assert suite.items[0].force_source_match is False


def test_bench_suite_model_force_source():
    item = BenchItem(
        item_id="forced",
        source_path="a.epub",
        gold_dir="b",
        force_source_match=True,
    )
    assert item.force_source_match is True


def test_load_suite_from_json(tmp_path: Path):
    suite_data = {
        "name": "dev",
        "items": [
            {
                "item_id": "item1",
                "source_path": "src.epub",
                "gold_dir": "gold/dir",
            }
        ],
    }
    suite_file = tmp_path / "suite.json"
    suite_file.write_text(json.dumps(suite_data), encoding="utf-8")
    suite = load_suite(suite_file)
    assert suite.name == "dev"
    assert suite.items[0].item_id == "item1"


def test_validate_suite_missing_source(tmp_path: Path):
    suite = BenchSuite(
        name="bad",
        items=[
            BenchItem(
                item_id="missing",
                source_path="nonexistent.epub",
                gold_dir="nonexistent_dir",
            )
        ],
    )
    errors = validate_suite(suite, tmp_path)
    assert any("Source file not found" in e for e in errors)
    assert any("Gold span labels not found" in e for e in errors)


def test_validate_suite_empty():
    suite = BenchSuite(name="empty", items=[])
    errors = validate_suite(suite, Path("/tmp"))
    assert any("no items" in e.lower() for e in errors)


def test_validate_suite_duplicate_ids(tmp_path: Path):
    suite = BenchSuite(
        name="dup",
        items=[
            BenchItem(item_id="same", source_path="a.epub", gold_dir="g"),
            BenchItem(item_id="same", source_path="b.epub", gold_dir="g"),
        ],
    )
    errors = validate_suite(suite, tmp_path)
    assert any("Duplicate" in e for e in errors)


def test_validate_suite_valid(tmp_path: Path):
    """Suite validates when all referenced files exist."""
    source = tmp_path / "data" / "input" / "test.epub"
    source.parent.mkdir(parents=True)
    source.write_text("fake epub", encoding="utf-8")
    gold_exports = tmp_path / "data" / "golden" / "exports"
    gold_exports.mkdir(parents=True)
    (gold_exports / "freeform_span_labels.jsonl").write_text("", encoding="utf-8")
    (gold_exports / "freeform_segment_manifest.jsonl").write_text("", encoding="utf-8")

    suite = BenchSuite(
        name="ok",
        items=[
            BenchItem(
                item_id="test",
                source_path="data/input/test.epub",
                gold_dir="data/golden",
            )
        ],
    )
    errors = validate_suite(suite, tmp_path)
    assert errors == []


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


# ---------------------------------------------------------------------------
# Trace collector
# ---------------------------------------------------------------------------


def test_trace_collector_basic(tmp_path: Path):
    tc = TraceCollector()
    tc.record("span_start", 5, {"label": "INGREDIENT_LINE"})
    tc.record("span_end", 10)
    assert len(tc.events) == 2
    assert tc.events[0]["event_type"] == "span_start"
    assert tc.events[0]["block_index"] == 5

    out = tmp_path / "trace.jsonl"
    tc.write(out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_trace_collector_clear():
    tc = TraceCollector()
    tc.record("test", 0)
    tc.clear()
    assert len(tc.events) == 0


# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------


def test_list_knobs():
    knobs = list_knobs()
    assert len(knobs) >= 1
    names = {k.name for k in knobs}
    assert "segment_blocks" in names
    assert "epub_extractor" in names
    assert "instruction_step_segmentation_policy" in names
    assert "instruction_step_segmenter" in names


def test_effective_knobs_defaults():
    eff = effective_knobs(None)
    assert "segment_blocks" in eff
    assert eff["segment_blocks"] == 40
    assert eff["instruction_step_segmentation_policy"] == "auto"
    assert eff["instruction_step_segmenter"] == "heuristic_v1"


def test_effective_knobs_override():
    eff = effective_knobs({"segment_blocks": 60})
    assert eff["segment_blocks"] == 60


def test_validate_knobs_out_of_bounds():
    errors = validate_knobs({"segment_blocks": 999})
    assert len(errors) == 1
    assert "out of bounds" in errors[0]


def test_validate_knobs_valid():
    errors = validate_knobs({"segment_blocks": 40})
    assert errors == []


def test_validate_knobs_rejects_invalid_epub_extractor():
    errors = validate_knobs({"epub_extractor": "not-a-real-backend"})
    assert errors
    assert "allowed values" in errors[0]


def test_validate_knobs_rejects_invalid_instruction_segmentation_policy():
    errors = validate_knobs({"instruction_step_segmentation_policy": "bad-policy"})
    assert errors
    assert "allowed values" in errors[0]


def test_load_config_missing():
    result = load_config(None)
    assert result == {}


def test_load_config_from_file(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"segment_blocks": 50}), encoding="utf-8")
    result = load_config(cfg_file)
    assert result["segment_blocks"] == 50


def test_build_pred_run_for_source_passes_epub_extractor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_text("epub", encoding="utf-8")
    out_dir = tmp_path / "runs"
    captured: dict[str, object] = {}

    def _fake_generate_pred_run_artifacts(**kwargs):
        captured.update(kwargs)
        return {"run_root": out_dir / "run"}

    monkeypatch.setattr(
        "cookimport.bench.pred_run.generate_pred_run_artifacts",
        _fake_generate_pred_run_artifacts,
    )

    build_pred_run_for_source(
        source,
        out_dir,
        config={
            "epub_extractor": "beautifulsoup",
            "instruction_step_segmentation_policy": "always",
            "instruction_step_segmenter": "heuristic_v1",
        },
    )

    assert captured["epub_extractor"] == "beautifulsoup"
    assert captured["instruction_step_segmentation_policy"] == "always"
    assert captured["instruction_step_segmenter"] == "heuristic_v1"


def test_bench_run_direct_write_flags_override_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite_file = tmp_path / "suite.json"
    suite_file.write_text("{}", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "write_markdown": True,
                "write_label_studio_tasks": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    fake_suite = BenchSuite(name="demo", items=[])
    captured_config: dict[str, object] = {}
    run_root = tmp_path / "run-root"
    run_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("cookimport.bench.suite.load_suite", lambda _path: fake_suite)
    monkeypatch.setattr("cookimport.bench.suite.validate_suite", lambda _suite, _repo_root: [])
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, initial_status, progress_prefix, run, **_kwargs: run(lambda _msg: None),
    )

    def _fake_run_suite(
        _suite,
        _out_dir,
        *,
        repo_root,
        config,
        baseline_run_dir,
        progress_callback,
    ):
        _ = (repo_root, baseline_run_dir, progress_callback)
        captured_config.update(config or {})
        return run_root, {"recall": 0.0, "precision": 0.0}

    monkeypatch.setattr("cookimport.bench.runner.run_suite", _fake_run_suite)
    monkeypatch.setattr(
        "cookimport.bench.packet.build_iteration_packet",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("cookimport.cli._sum_bench_recipe_count", lambda _run_root: 0)
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.history_path",
        lambda _output_root: tmp_path / "history.csv",
    )
    monkeypatch.setattr(
        "cookimport.cli._refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_run(
        suite=suite_file,
        out_dir=tmp_path / "runs",
        baseline=None,
        config_path=config_path,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert captured_config["write_markdown"] is False
    assert captured_config["write_label_studio_tasks"] is False


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
        run_settings,
        progress_callback,
    ):
        _ = progress_callback
        captured["suite"] = suite
        captured["out_dir"] = out_dir
        captured["scenarios"] = scenarios
        captured["warmups"] = warmups
        captured["repeats"] = repeats
        captured["max_targets"] = max_targets
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
        run_settings,
        progress_callback,
    ):
        _ = (suite, out_dir, scenarios, warmups, repeats, max_targets, progress_callback)
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
    ):
        _ = progress_callback
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
        base_run_settings_file=base_settings_file,
    )

    assert captured["suite"] == loaded_suite
    assert captured["experiments_file"] == experiments_file
    assert captured["base_run_settings_file"] == base_settings_file


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
# Iteration packet
# ---------------------------------------------------------------------------


def test_build_iteration_packet_empty(tmp_path: Path):
    """Packet builds without error on empty run root."""
    build_iteration_packet(tmp_path)
    # No per_item dir → nothing created
    assert not (tmp_path / "iteration_packet" / "cases.jsonl").exists()


def test_build_iteration_packet_with_data(tmp_path: Path):
    """Packet builds with per-item eval artifacts."""
    item_dir = tmp_path / "per_item" / "item1"
    eval_dir = item_dir / "eval_freeform"
    pred_dir = item_dir / "pred_run"
    eval_dir.mkdir(parents=True)
    pred_dir.mkdir(parents=True)

    missed = [
        {"label": "INGREDIENT_LINE", "start_block_index": 3, "end_block_index": 5},
    ]
    fps = [
        {"label": "OTHER", "start_block_index": 10, "end_block_index": 12},
    ]
    eval_report = {
        "counts": {"gold_total": 10, "gold_matched": 7, "gold_missed": 3, "pred_total": 8, "pred_matched": 6, "pred_false_positive": 2},
        "recall": 0.7,
        "precision": 0.75,
    }
    (eval_dir / "missed_gold_spans.jsonl").write_text(
        "\n".join(json.dumps(r) for r in missed), encoding="utf-8"
    )
    (eval_dir / "false_positive_preds.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fps), encoding="utf-8"
    )
    (eval_dir / "eval_report.json").write_text(
        json.dumps(eval_report), encoding="utf-8"
    )

    archive = [{"index": i, "text": f"block {i} text"} for i in range(20)]
    (pred_dir / "extracted_archive.json").write_text(
        json.dumps(archive), encoding="utf-8"
    )

    build_iteration_packet(tmp_path)

    packet_dir = tmp_path / "iteration_packet"
    assert (packet_dir / "cases.jsonl").exists()
    assert (packet_dir / "summary.md").exists()
    assert (packet_dir / "top_failures.md").exists()
    assert (packet_dir / "README.md").exists()

    cases_text = (packet_dir / "cases.jsonl").read_text(encoding="utf-8")
    cases = [json.loads(line) for line in cases_text.strip().splitlines()]
    assert len(cases) == 2
    # Missed gold should have higher severity than false positive
    assert cases[0]["case_type"] == "missed_gold"


def test_build_iteration_packet_demotes_strict_only_boundary_cases(tmp_path: Path):
    item_dir = tmp_path / "per_item" / "item1"
    eval_dir = item_dir / "eval_freeform"
    pred_dir = item_dir / "pred_run"
    eval_dir.mkdir(parents=True)
    pred_dir.mkdir(parents=True)

    missed = [
        {
            "span_id": "gold-a",
            "label": "INGREDIENT_LINE",
            "start_block_index": 3,
            "end_block_index": 5,
        },
        {
            "span_id": "gold-b",
            "label": "INGREDIENT_LINE",
            "start_block_index": 8,
            "end_block_index": 9,
        },
    ]
    fps = [
        {
            "span_id": "pred-a",
            "label": "OTHER",
            "start_block_index": 10,
            "end_block_index": 12,
        }
    ]
    eval_report = {
        "counts": {
            "gold_total": 2,
            "gold_matched": 0,
            "gold_missed": 2,
            "pred_total": 1,
            "pred_matched": 0,
            "pred_false_positive": 1,
        },
        "practical_counts": {
            "gold_total": 2,
            "gold_matched": 1,
            "gold_missed": 1,
            "pred_total": 1,
            "pred_matched": 1,
            "pred_false_positive": 0,
        },
        "recall": 0.0,
        "precision": 0.0,
        "practical_recall": 0.5,
        "practical_precision": 1.0,
        "practical_matching": {
            "matched_gold_span_ids": ["gold-a"],
            "matched_pred_span_ids": ["pred-a"],
        },
    }
    (eval_dir / "missed_gold_spans.jsonl").write_text(
        "\n".join(json.dumps(r) for r in missed), encoding="utf-8"
    )
    (eval_dir / "false_positive_preds.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fps), encoding="utf-8"
    )
    (eval_dir / "eval_report.json").write_text(json.dumps(eval_report), encoding="utf-8")
    archive = [{"index": i, "text": f"block {i}"} for i in range(20)]
    (pred_dir / "extracted_archive.json").write_text(json.dumps(archive), encoding="utf-8")

    build_iteration_packet(tmp_path)

    cases = [
        json.loads(line)
        for line in (tmp_path / "iteration_packet" / "cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(cases) == 3
    # Practical miss should outrank strict-only boundary misses/fps.
    assert cases[0]["case_type"] == "missed_gold"
    assert cases[1]["case_type"] in {"strict_boundary_miss", "strict_boundary_fp"}


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
