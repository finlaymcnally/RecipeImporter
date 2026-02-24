from __future__ import annotations

import inspect
import json
import os
import time
from pathlib import Path

import pytest

import cookimport.cli as cli
from cookimport.core.progress_messages import (
    format_worker_activity,
    format_worker_activity_reset,
)


def test_format_status_progress_message_appends_elapsed_after_threshold() -> None:
    assert (
        cli._format_status_progress_message(
            "Working on upload...",
            elapsed_seconds=9,
            elapsed_threshold_seconds=10,
        )
        == "Working on upload..."
    )
    assert (
        cli._format_status_progress_message(
            "Working on upload...",
            elapsed_seconds=10,
            elapsed_threshold_seconds=10,
        )
        == "Working on upload... (10s)"
    )


def test_format_status_progress_message_appends_eta_and_average() -> None:
    assert (
        cli._format_status_progress_message(
            "Running freeform prelabeling... task 4/10",
            elapsed_seconds=3,
            elapsed_threshold_seconds=10,
            eta_seconds=18,
            avg_seconds_per_task=3.0,
        )
        == "Running freeform prelabeling... task 4/10 (eta 18s, avg 3s/task)"
    )
    assert (
        cli._format_status_progress_message(
            "Running freeform prelabeling... task 4/10",
            elapsed_seconds=12,
            elapsed_threshold_seconds=10,
            eta_seconds=18,
            avg_seconds_per_task=3.0,
        )
        == "Running freeform prelabeling... task 4/10 (eta 18s, avg 3s/task, 12s)"
    )


def test_extract_progress_counter_uses_right_most_counter() -> None:
    assert cli._extract_progress_counter("item 1/5 [book] task 3/12") == (3, 12)
    assert cli._extract_progress_counter("Phase done.") is None


def test_run_with_progress_status_shows_elapsed_for_long_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStatus:
        def __init__(self, messages: list[str]) -> None:
            self._messages = messages

        def __enter__(self) -> "_FakeStatus":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def update(self, message: str) -> None:
            self._messages.append(message)

    recorded: list[str] = []

    class _CaptureStatus:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def __call__(self, message: str, spinner: str = "dots") -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureStatus()
    monkeypatch.setattr(cli.console, "status", capture)

    def _run(update_progress):
        update_progress("Extracting candidate 46/46...")
        time.sleep(1.2)
        recorded.append("done")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        elapsed_threshold_seconds=1,
        tick_seconds=0.1,
    )

    assert result == {"ok": True}
    assert recorded == ["done"]
    assert any(
        "Import: Extracting candidate 46/46... (" in message and "s)" in message
        for message in capture.messages
    )


def test_run_with_progress_status_shows_eta_for_xy_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStatus:
        def __init__(self, messages: list[str]) -> None:
            self._messages = messages

        def __enter__(self) -> "_FakeStatus":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def update(self, message: str) -> None:
            self._messages.append(message)

    class _CaptureStatus:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def __call__(self, message: str, spinner: str = "dots") -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureStatus()
    monkeypatch.setattr(cli.console, "status", capture)

    def _run(update_progress):
        update_progress("Running freeform prelabeling... task 1/4")
        time.sleep(0.12)
        update_progress("Running freeform prelabeling... task 2/4")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
    )

    assert result == {"ok": True}
    assert any(
        "Import: Running freeform prelabeling... task 2/4 (eta " in message
        and "avg " in message
        and "s/task" in message
        for message in capture.messages
    )


def test_run_with_progress_status_renders_worker_activity_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStatus:
        def __init__(self, messages: list[str]) -> None:
            self._messages = messages

        def __enter__(self) -> "_FakeStatus":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def update(self, message: str) -> None:
            self._messages.append(message)

    class _CaptureStatus:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def __call__(self, message: str, spinner: str = "dots") -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureStatus()
    monkeypatch.setattr(cli.console, "status", capture)

    def _run(update_progress):
        update_progress("Running freeform prelabeling... task 1/4 (workers=2)")
        update_progress(format_worker_activity(1, 2, "task 1/4 blocks 0-39"))
        update_progress(format_worker_activity(2, 2, "task 2/4 blocks 40-79"))
        update_progress("Running freeform prelabeling... task 2/4 (workers=2)")
        update_progress(format_worker_activity_reset())
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
    )

    assert result == {"ok": True}
    assert any(
        "worker 01: task 1/4 blocks 0-39" in message
        and "worker 02: task 2/4 blocks 40-79" in message
        for message in capture.messages
    )
    assert "worker 01:" not in capture.messages[-1]


def test_labelstudio_import_prints_processing_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setattr(
        cli,
        "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": tmp_path / "out",
        },
    )
    ticks = iter([100.0, 165.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        task_scope="pipeline",
        prelabel=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_BLOCK,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
        codex_farm_pipeline_pass1="recipe.chunking.v1",
        codex_farm_pipeline_pass2="recipe.schemaorg.v1",
        codex_farm_pipeline_pass3="recipe.final.v1",
    )

    assert "Processing time: 1m 5s" in secho_messages


def test_labelstudio_import_prints_prelabel_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setattr(
        cli,
        "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 9,
            "tasks_uploaded": 9,
            "run_root": tmp_path / "out",
            "prelabel_report_path": str(tmp_path / "prelabel_report.json"),
            "prelabel_inline_annotations_fallback": False,
            "prelabel": {
                "task_count": 9,
                "success_count": 1,
                "failure_count": 8,
                "allow_partial": True,
                "errors_path": str(tmp_path / "prelabel_errors.jsonl"),
                "token_usage_enabled": False,
            },
        },
    )
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        task_scope="freeform-spans",
        segment_blocks=40,
        segment_focus_blocks=40,
        prelabel=True,
        prelabel_allow_partial=True,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_SPAN,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
        codex_farm_pipeline_pass1="recipe.chunking.v1",
        codex_farm_pipeline_pass2="recipe.schemaorg.v1",
        codex_farm_pipeline_pass3="recipe.final.v1",
    )

    assert any("PRELABEL ERRORS: 8/9 tasks failed (1 succeeded)." in line for line in secho_messages)
    assert any("Upload continued because allow-partial mode is enabled." in line for line in secho_messages)
    assert any("For fail-fast behavior, use --no-prelabel-allow-partial." in line for line in secho_messages)
    assert any("Prelabel errors: " in line for line in secho_messages)


def test_labelstudio_import_prints_prelabel_token_usage_with_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setattr(
        cli,
        "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 4,
            "tasks_uploaded": 4,
            "run_root": tmp_path / "out",
            "prelabel_report_path": str(tmp_path / "prelabel_report.json"),
            "prelabel_inline_annotations_fallback": False,
            "prelabel": {
                "task_count": 4,
                "success_count": 4,
                "failure_count": 0,
                "allow_partial": False,
                "token_usage_enabled": True,
                "token_usage": {
                    "input_tokens": 111,
                    "cached_input_tokens": 22,
                    "output_tokens": 33,
                    "reasoning_tokens": 44,
                    "calls_with_usage": 4,
                },
            },
        },
    )
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        task_scope="freeform-spans",
        segment_blocks=40,
        segment_focus_blocks=40,
        prelabel=True,
        prelabel_allow_partial=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_SPAN,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
        codex_farm_pipeline_pass1="recipe.chunking.v1",
        codex_farm_pipeline_pass2="recipe.schemaorg.v1",
        codex_farm_pipeline_pass3="recipe.final.v1",
    )

    assert any(
        (
            "Prelabel token usage: input=111 cached_input=22 output=33 "
            "reasoning=44 calls_with_usage=4"
        )
        in line
        for line in secho_messages
    )


def test_labelstudio_import_routes_freeform_focus_and_target_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
    monkeypatch.setattr(
        cli,
        "_run_labelstudio_import_with_status",
        lambda **kwargs: kwargs["run_import"](lambda _message: None),
    )
    captured: dict[str, object] = {}

    def _fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": tmp_path / "out",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", _fake_run_labelstudio_import)
    monkeypatch.setattr(cli.typer, "secho", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        task_scope="freeform-spans",
        segment_blocks=40,
        segment_overlap=5,
        segment_focus_blocks=28,
        target_task_count=55,
        prelabel=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_BLOCK,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
        codex_farm_pipeline_pass1="recipe.chunking.v1",
        codex_farm_pipeline_pass2="recipe.schemaorg.v1",
        codex_farm_pipeline_pass3="recipe.final.v1",
    )

    assert captured["segment_blocks"] == 40
    assert captured["segment_overlap"] == 5
    assert captured["segment_focus_blocks"] == 28
    assert captured["target_task_count"] == 55
    assert captured["prelabel_timeout_seconds"] == cli.DEFAULT_PRELABEL_TIMEOUT_SECONDS


def test_discover_freeform_gold_exports_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book" / "exports"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book" / "exports"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_path = older / "freeform_span_labels.jsonl"
    newer_path = newer / "freeform_span_labels.jsonl"
    older_path.write_text("{}\n", encoding="utf-8")
    newer_path.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_freeform_gold_exports(tmp_path)
    assert discovered[0] == newer_path
    assert discovered[1] == older_path


def test_discover_freeform_gold_exports_includes_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    exports = golden_root / "sample" / "freeform" / "2026-02-10_20:36:41" / "labelstudio" / "book" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    golden_path = exports / "freeform_span_labels.jsonl"
    golden_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    discovered = cli._discover_freeform_gold_exports(output_root)
    assert golden_path in discovered


def test_display_gold_export_path_relative_to_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    path = golden_root / "sample" / "freeform" / "exports" / "freeform_span_labels.jsonl"
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    display = cli._display_gold_export_path(path, output_root)
    assert display == "sample/freeform/exports/freeform_span_labels.jsonl"


def test_load_gold_recipe_headers_from_summary_prefers_recipe_counts(tmp_path: Path) -> None:
    exports = tmp_path / "run" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (exports / "summary.json").write_text(
        json.dumps(
            {
                "recipe_counts": {"recipe_headers": 9},
                "counts": {"recipe_headers": 2},
            }
        ),
        encoding="utf-8",
    )

    assert cli._load_gold_recipe_headers_from_summary(gold_path) == 9


def test_load_gold_recipe_headers_from_summary_falls_back_to_counts(tmp_path: Path) -> None:
    exports = tmp_path / "run" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (exports / "summary.json").write_text(
        json.dumps({"counts": {"recipe_headers": 4}}),
        encoding="utf-8",
    )

    assert cli._load_gold_recipe_headers_from_summary(gold_path) == 4


def test_discover_prediction_runs_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book-a"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book-b"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_marker = older / "label_studio_tasks.jsonl"
    newer_marker = newer / "label_studio_tasks.jsonl"
    older_marker.write_text("{}\n", encoding="utf-8")
    newer_marker.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_prediction_runs(tmp_path)
    assert discovered[0] == newer
    assert discovered[1] == older


def test_infer_source_file_from_manifest_path(tmp_path: Path) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")
    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (run_root / "manifest.json").write_text(
        json.dumps({"source_file": str(source)}), encoding="utf-8"
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source


def test_infer_source_file_from_gold_row_uses_default_input(
    tmp_path: Path, monkeypatch
) -> None:
    input_root = tmp_path / "data" / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    source = input_root / "book.epub"
    source.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_INPUT", input_root)

    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text(
        json.dumps({"source_file": "book.epub", "label": "RECIPE_NOTES"}) + "\n",
        encoding="utf-8",
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source


def test_infer_scope_from_project_payload_detects_new_freeform_labels() -> None:
    scope = cli._infer_scope_from_project_payload(
        {"label_config": "<View><Label value='RECIPE_VARIANT'/></View>"}
    )
    assert scope == "freeform-spans"


def test_infer_scope_from_project_payload_keeps_legacy_freeform_detection() -> None:
    scope = cli._infer_scope_from_project_payload(
        {"label_config": "<View><Label value='VARIANT'/></View>"}
    )
    assert scope == "freeform-spans"


def test_labelstudio_benchmark_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "k"))
    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [])
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(output_dir=tmp_path / "empty-golden")


def test_labelstudio_eval_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    gold_spans = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "eval"

    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "# report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    captured: dict[str, object] = {}

    def fake_eval(*_args, overlap_threshold: float, force_source_match: bool, **_kwargs):
        captured["overlap_threshold"] = overlap_threshold
        captured["force_source_match"] = force_source_match
        return {"report": {}, "missed_gold": [], "false_positive_preds": []}

    monkeypatch.setattr(cli, "evaluate_predicted_vs_freeform", fake_eval)

    cli.labelstudio_eval(
        scope="freeform-spans",
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
    )

    assert captured["overlap_threshold"] == 0.5
    assert isinstance(captured["overlap_threshold"], float)
    assert captured["force_source_match"] is False
    assert isinstance(captured["force_source_match"], bool)


def test_labelstudio_eval_appends_benchmark_recipes_from_pred_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "recipe_count": 14,
                "source_file": str(tmp_path / "input" / "book.epub"),
                "processed_report_path": "",
            }
        ),
        encoding="utf-8",
    )
    gold_spans = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "eval"

    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "# report")
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {},
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    cli.labelstudio_eval(
        scope="freeform-spans",
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
    )

    assert captured_csv["recipes"] == 14
    assert captured_csv["source_file"] == str(tmp_path / "input" / "book.epub")


def test_sum_bench_recipe_count_from_per_item_manifests(tmp_path: Path) -> None:
    run_root = tmp_path / "bench-run"
    (run_root / "per_item" / "a" / "pred_run").mkdir(parents=True, exist_ok=True)
    (run_root / "per_item" / "b" / "pred_run").mkdir(parents=True, exist_ok=True)
    (run_root / "per_item" / "c" / "pred_run").mkdir(parents=True, exist_ok=True)

    (run_root / "per_item" / "a" / "pred_run" / "manifest.json").write_text(
        json.dumps({"recipe_count": 4}),
        encoding="utf-8",
    )
    (run_root / "per_item" / "b" / "pred_run" / "manifest.json").write_text(
        json.dumps({"recipe_count": 7}),
        encoding="utf-8",
    )
    (run_root / "per_item" / "c" / "pred_run" / "manifest.json").write_text(
        json.dumps({}),
        encoding="utf-8",
    )

    assert cli._sum_bench_recipe_count(run_root) == 11


def test_labelstudio_commands_default_output_roots() -> None:
    import_param = inspect.signature(cli.labelstudio_import).parameters["output_dir"]
    export_param = inspect.signature(cli.labelstudio_export).parameters["output_dir"]
    benchmark_param = inspect.signature(cli.labelstudio_benchmark).parameters["output_dir"]
    eval_overlap_param = inspect.signature(cli.labelstudio_eval).parameters["overlap_threshold"]
    eval_force_match_param = inspect.signature(cli.labelstudio_eval).parameters["force_source_match"]

    assert getattr(import_param.default, "default", None) == cli.DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO
    assert getattr(export_param.default, "default", None) == cli.DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO
    assert benchmark_param.default == cli.DEFAULT_GOLDEN_BENCHMARK
    assert eval_overlap_param.default == 0.5
    assert eval_force_match_param.default is False


def test_resolve_interactive_labelstudio_settings_uses_saved_credentials_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "label_studio_url": "http://localhost:8080",
        "label_studio_api_key": "saved-key",
    }
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("URL prompt should not run when creds are already saved.")
        ),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("API key prompt should not run when creds are already saved.")
        ),
    )
    monkeypatch.setattr(cli, "_preflight_labelstudio_credentials", lambda *_: None)

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "saved-key"


def test_resolve_interactive_labelstudio_settings_prompts_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings: dict[str, str] = {}
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def __init__(self, value: str):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: _Prompt("http://localhost:8080"),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: _Prompt("new-key"),
    )
    saved_snapshots: list[dict[str, str]] = []
    monkeypatch.setattr(
        cli,
        "_save_settings",
        lambda payload: saved_snapshots.append(dict(payload)),
    )
    monkeypatch.setattr(cli, "_preflight_labelstudio_credentials", lambda *_: None)

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "new-key"
    assert settings["label_studio_url"] == "http://localhost:8080"
    assert settings["label_studio_api_key"] == "new-key"
    assert saved_snapshots[-1]["label_studio_url"] == "http://localhost:8080"
    assert saved_snapshots[-1]["label_studio_api_key"] == "new-key"


def test_resolve_interactive_labelstudio_settings_returns_none_on_prompt_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings: dict[str, str] = {}
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def ask(self):
            return None

    monkeypatch.setattr(cli.questionary, "text", lambda *_args, **_kwargs: _Prompt())
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("API key prompt should not run after URL prompt cancel.")
        ),
    )

    assert cli._resolve_interactive_labelstudio_settings(settings) is None


def test_resolve_interactive_labelstudio_settings_reprompts_when_saved_creds_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "label_studio_url": "http://localhost:8080",
        "label_studio_api_key": "stale-key",
    }
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def __init__(self, value: str):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: _Prompt("http://localhost:8080"),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: _Prompt("fresh-key"),
    )
    probe_calls: list[tuple[str, str]] = []

    def fake_preflight(url: str, api_key: str) -> str | None:
        probe_calls.append((url, api_key))
        if api_key == "stale-key":
            return "Label Studio API error 401 on /api/projects?page=1&page_size=100: unauthorized"
        return None

    monkeypatch.setattr(cli, "_preflight_labelstudio_credentials", fake_preflight)
    saved_snapshots: list[dict[str, str]] = []
    monkeypatch.setattr(
        cli,
        "_save_settings",
        lambda payload: saved_snapshots.append(dict(payload)),
    )

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "fresh-key"
    assert probe_calls == [
        ("http://localhost:8080", "stale-key"),
        ("http://localhost:8080", "fresh-key"),
    ]
    assert settings["label_studio_api_key"] == "fresh-key"
    assert saved_snapshots[-1]["label_studio_api_key"] == "fresh-key"


def test_is_labelstudio_credential_error() -> None:
    assert cli._is_labelstudio_credential_error("Label Studio API error 401 on /api/projects: unauthorized")
    assert cli._is_labelstudio_credential_error("Label Studio API error 403 on /api/projects: forbidden")
    assert not cli._is_labelstudio_credential_error("timed out connecting to host")


def test_co_locate_prediction_run_for_benchmark_moves_into_eval_dir(tmp_path: Path) -> None:
    timestamp_root = tmp_path / "output" / "2026-02-10_21:09:52"
    pred_run = timestamp_root / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    marker = pred_run / "label_studio_tasks.jsonl"
    marker.write_text("{}\n", encoding="utf-8")
    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved == eval_output_dir / "prediction-run"
    assert moved.exists()
    assert (moved / "label_studio_tasks.jsonl").exists()
    assert not pred_run.exists()
    assert not (timestamp_root / "labelstudio").exists()
    assert not timestamp_root.exists()


def test_co_locate_prediction_run_for_benchmark_overwrites_existing_target(tmp_path: Path) -> None:
    pred_run = tmp_path / "output" / "2026-02-10_21:09:52" / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "new.txt").write_text("new\n", encoding="utf-8")

    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    existing_target = eval_output_dir / "prediction-run"
    existing_target.mkdir(parents=True, exist_ok=True)
    (existing_target / "old.txt").write_text("old\n", encoding="utf-8")

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved.exists()
    assert (moved / "new.txt").exists()
    assert not (moved / "old.txt").exists()


def test_interactive_labelstudio_freeform_scope_routes_to_freeform_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            "freeform-spans",
            (True, "annotations", True),
            "span",
            "__default__",
            "__default_effort__",
            "exit",
        ]
    )

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    text_answers = iter(["", "42", "6", "28", "55"])

    class _Prompt:
        def __init__(self, value: str | bool):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "default_codex_cmd", lambda: "codex exec -")
    monkeypatch.setattr(
        cli,
        "codex_account_summary",
        lambda _cmd=None: "prelabel@example.com (pro)",
    )
    monkeypatch.setattr(cli, "default_codex_model", lambda cmd=None: None)
    monkeypatch.setattr(cli, "list_codex_models", lambda cmd=None: [])
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(next(text_answers)),
    )

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["task_scope"] == "freeform-spans"
    assert captured["chunk_level"] == "both"
    assert captured["segment_blocks"] == 42
    assert captured["segment_overlap"] == 6
    assert captured["segment_focus_blocks"] == 28
    assert captured["target_task_count"] == 55
    assert captured["prelabel"] is True
    assert captured["prelabel_upload_as"] == "annotations"
    assert captured["prelabel_allow_partial"] is True
    assert captured["prelabel_granularity"] == "span"
    assert captured["prelabel_timeout_seconds"] == cli.DEFAULT_PRELABEL_TIMEOUT_SECONDS
    assert captured["prelabel_workers"] == 15
    assert captured["codex_cmd"] == "codex exec -"
    assert captured["codex_model"] is None
    assert captured["codex_reasoning_effort"] is None
    assert captured["prelabel_track_token_usage"] is True
    assert callable(captured["progress_callback"])
    assert captured["output_dir"] == (tmp_path / "golden" / "sent-to-labelstudio")
    assert captured["overwrite"] is True
    assert captured["resume"] is False


def test_interactive_labelstudio_freeform_focus_escape_steps_back_one_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            "freeform-spans",
            (False, "annotations", False),
            "exit",
        ]
    )

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    prompt_answers = iter(
        [
            "",     # project name
            "40",   # segment size
            "5",    # overlap
            None,   # Esc at focus -> back to overlap
            "7",    # overlap after stepping back
            "40",   # focus
            "",     # target task count
        ]
    )
    prompt_messages: list[str] = []

    def fake_prompt_text(message: str, **_kwargs):
        prompt_messages.append(message)
        return next(prompt_answers)

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_prompt_text", fake_prompt_text)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["task_scope"] == "freeform-spans"
    assert captured["segment_blocks"] == 40
    assert captured["segment_overlap"] == 7
    assert captured["segment_focus_blocks"] == 40
    assert prompt_messages.count("Freeform overlap (blocks):") == 2


def test_interactive_labelstudio_import_forces_overwrite_without_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(["labelstudio", selected_file, "pipeline", "both", "exit"])

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    class _Prompt:
        def __init__(self, value: str | bool):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(""),
    )

    confirm_prompts: list[str] = []

    def fake_confirm(message: str, *args, **kwargs):
        confirm_prompts.append(message)
        if "Overwrite existing project" in message:
            raise AssertionError("Interactive import should not ask overwrite confirmation.")
        if "Upload tasks to Label Studio now?" in message:
            return _Prompt(True)
        raise AssertionError(f"Unexpected confirmation prompt: {message}")

    monkeypatch.setattr(cli.questionary, "confirm", fake_confirm)

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert confirm_prompts == []
    assert captured["overwrite"] is True
    assert captured["resume"] is False
    assert callable(captured["progress_callback"])


def test_interactive_benchmark_uses_golden_output_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["labelstudio_benchmark", "single_offline", "global", "exit"])
    mode_prompts: list[list[str]] = []

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        if prompt == "How would you like to evaluate?":
            mode_prompts.append(
                [str(choice.title) for choice in _kwargs.get("choices", [])]
            )
        return next(menu_answers)

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "legacy"},
    )
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    def _unexpected_confirm(*_args, **_kwargs):
        raise AssertionError("Interactive benchmark upload should not ask for confirmation.")

    monkeypatch.setattr(cli.questionary, "confirm", _unexpected_confirm)

    captured: dict[str, object] = {}

    def fake_labelstudio_benchmark(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["output_dir"] == golden_root / "benchmark-vs-golden"
    eval_output_dir = captured["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    assert eval_output_dir.parent == golden_root / "benchmark-vs-golden"
    assert captured["no_upload"] is True
    assert "label_studio_url" not in captured
    assert "label_studio_api_key" not in captured
    assert captured["epub_extractor"] == "legacy"
    assert mode_prompts
    assert any("offline, no upload" in title for title in mode_prompts[0])
    assert any("All method benchmark" in title for title in mode_prompts[0])
    assert not any("uploads to Label Studio" in title for title in mode_prompts[0])


def test_interactive_benchmark_single_offline_mode_skips_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["labelstudio_benchmark", "single_offline", "global", "exit"])

    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "legacy"},
    )
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )

    captured: dict[str, object] = {}

    def fake_labelstudio_benchmark(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["output_dir"] == golden_root / "benchmark-vs-golden"
    eval_output_dir = captured["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    assert eval_output_dir.parent == golden_root / "benchmark-vs-golden"
    assert captured["no_upload"] is True
    assert "allow_labelstudio_write" not in captured
    assert "label_studio_url" not in captured
    assert "label_studio_api_key" not in captured


def test_interactive_generate_dashboard_prompts_and_opens_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["generate_dashboard", "exit"])

    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {"output_dir": str(configured_output)})
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    confirm_messages: list[str] = []

    class _Prompt:
        def __init__(self, value: bool):
            self._value = value

        def ask(self):
            return self._value

    def fake_confirm(message: str, *_args, **_kwargs):
        confirm_messages.append(message)
        return _Prompt(True)

    monkeypatch.setattr(cli.questionary, "confirm", fake_confirm)

    captured: dict[str, object] = {}

    def fake_stats_dashboard(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "stats_dashboard", fake_stats_dashboard)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert confirm_messages == ["Open dashboard in your browser after generation?"]
    assert captured["output_root"] == configured_output
    assert captured["golden_root"] == golden_root
    assert captured["out_dir"] == configured_output.parent / ".history" / "dashboard"
    assert captured["open_browser"] is True
    assert captured["since_days"] is None
    assert captured["scan_reports"] is False


def test_interactive_benchmark_ignores_existing_eval_artifacts_and_runs_offline_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden_root = tmp_path / "golden"
    pred_run = golden_root / "some-run" / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    gold_spans = golden_root / "some-run" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    menu_answers = iter(["labelstudio_benchmark", "single_offline", "global", "exit"])
    mode_prompt_count = 0
    mode_titles: list[str] = []

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        nonlocal mode_prompt_count
        if prompt == "How would you like to evaluate?":
            mode_prompt_count += 1
            mode_titles.extend(str(choice.title) for choice in _kwargs.get("choices", []))
        return next(menu_answers)

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )
    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [gold_spans])
    monkeypatch.setattr(cli, "_discover_prediction_runs", lambda *_: [pred_run])

    eval_calls: list[dict[str, object]] = []
    benchmark_calls: list[dict[str, object]] = []

    monkeypatch.setattr(cli, "labelstudio_eval", lambda **kwargs: eval_calls.append(kwargs))
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert eval_calls == []
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["output_dir"] == golden_root / "benchmark-vs-golden"
    assert benchmark_calls[0]["no_upload"] is True
    assert mode_prompt_count == 1
    assert not any("uploads to Label Studio" in title for title in mode_titles)


def test_interactive_labelstudio_export_routes_to_export_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    menu_answers = iter(["labelstudio_export", "exit"])

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        if prompt == "Export scope:":
            raise AssertionError("Known project type should skip export scope prompt.")
        return next(menu_answers)

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", selected_output)
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setattr(cli, "_select_export_project", lambda **_: ("Bench Project", "freeform-spans"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_export(**kwargs):
        captured.update(kwargs)
        return {"summary_path": selected_output / "summary.json"}

    monkeypatch.setattr(cli, "run_labelstudio_export", fake_run_labelstudio_export)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["project_name"] == "Bench Project"
    assert captured["export_scope"] == "freeform-spans"
    assert captured["output_dir"] == selected_output / "pulled-from-labelstudio"


def test_interactive_labelstudio_export_selects_project_before_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    events: list[str] = []

    state = {"main_calls": 0}

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        events.append(f"menu:{prompt}")
        if prompt == "What would you like to do?":
            state["main_calls"] += 1
            return "labelstudio_export" if state["main_calls"] == 1 else "exit"
        if prompt == "Export scope:":
            return "pipeline"
        raise AssertionError(f"Unexpected prompt: {prompt}")

    def fake_select_export_project(**_kwargs):
        events.append("select_project")
        return "Bench Project", None

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", selected_output)
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setattr(cli, "_select_export_project", fake_select_export_project)
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli,
        "run_labelstudio_export",
        lambda **_kwargs: {"summary_path": selected_output / "summary.json"},
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert events == [
        "menu:What would you like to do?",
        "select_project",
        "menu:Export scope:",
        "menu:What would you like to do?",
    ]


def test_select_export_project_returns_detected_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "Alpha"},
            ]

    monkeypatch.setattr(cli, "LabelStudioClient", FakeClient)
    monkeypatch.setattr(cli, "_discover_manifest_project_scopes", lambda *_: {"Alpha": "pipeline"})
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: "Alpha")

    selected, scope = cli._select_export_project(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Alpha"
    assert scope == "pipeline"


def test_select_export_project_name_uses_project_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "beta"},
                {"title": "Alpha"},
                {"title": ""},
            ]

    def fake_menu_select(*_args, **_kwargs):
        assert _kwargs["choices"][1].value == "Alpha"
        assert _kwargs["choices"][1].title == "Alpha [type: pipeline]"
        assert _kwargs["choices"][2].value == "beta"
        assert _kwargs["choices"][2].title == "beta [type: unknown]"
        return "beta"

    monkeypatch.setattr(cli, "LabelStudioClient", FakeClient)
    monkeypatch.setattr(cli, "_discover_manifest_project_scopes", lambda *_: {"Alpha": "pipeline"})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "beta"


def test_select_export_project_name_prefers_manifest_scope_over_payload_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "Alpha", "label_config": "<Label value='RECIPE_VARIANT'/>"},
            ]

    def fake_menu_select(*_args, **_kwargs):
        assert _kwargs["choices"][1].title == "Alpha [type: canonical-blocks]"
        return "Alpha"

    monkeypatch.setattr(cli, "LabelStudioClient", FakeClient)
    monkeypatch.setattr(
        cli,
        "_discover_manifest_project_scopes",
        lambda *_: {"Alpha": "canonical-blocks"},
    )
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Alpha"


def test_select_export_project_name_falls_back_to_manual_on_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RaisingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(cli, "LabelStudioClient", RaisingClient)
    monkeypatch.setattr(cli, "_prompt_manual_project_name", lambda: "Typed Name")

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Typed Name"


def test_interactive_main_menu_does_not_offer_inspect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_values: list[object] = []

    def fake_menu_select(*_args, **_kwargs):
        choices = _kwargs.get("choices", [])
        captured_values.extend(getattr(choice, "value", choice) for choice in choices)
        return "exit"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert "inspect" not in captured_values


def test_interactive_epub_race_routes_to_race_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_epub = tmp_path / "book.epub"
    source_epub.write_text("dummy", encoding="utf-8")
    race_out = tmp_path / "race-out"

    menu_answers = iter(["epub_race", source_epub, "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [source_epub])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})

    text_answers = iter([str(race_out), "unstructured,markdown,legacy"])
    text_prompt_defaults: list[str | None] = []

    class _Prompt:
        def __init__(self, answer: str):
            self.answer = answer

        def ask(self):
            return self.answer

    def _fake_text(*_args, **_kwargs):
        text_prompt_defaults.append(_kwargs.get("default"))
        return _Prompt(next(text_answers))

    monkeypatch.setattr(
        cli.questionary,
        "text",
        _fake_text,
    )

    def _unexpected_confirm(*_args, **_kwargs):
        raise AssertionError("confirm should not be called for empty/nonexistent output folder")

    monkeypatch.setattr(cli.questionary, "confirm", _unexpected_confirm)

    captured: dict[str, object] = {}

    def fake_race_epub_extractors(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "race_epub_extractors", fake_race_epub_extractors)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["path"] == source_epub
    assert captured["out"] == race_out
    assert captured["candidates"] == "unstructured,markdown,legacy"
    assert captured["json_output"] is False
    assert captured["force"] is False
    assert text_prompt_defaults[0] == str(cli.DEFAULT_EPUB_RACE_OUTPUT_ROOT / source_epub.stem)


def test_labelstudio_benchmark_passes_processed_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "write_jsonl", lambda *_: None)

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11-00-00-00",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    processed_root = tmp_path / "output"
    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=processed_root,
        eval_output_dir=eval_root,
        allow_labelstudio_write=True,
    )

    assert captured["processed_output_root"] == processed_root
    assert captured["auto_project_name_on_scope_mismatch"] is True


def test_labelstudio_benchmark_no_upload_uses_offline_pred_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not resolve Label Studio credentials.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_labelstudio_import",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not call run_labelstudio_import.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "write_jsonl", lambda *_: None)
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    captured_generate: dict[str, object] = {}

    def fake_generate_pred_run_artifacts(**kwargs):
        captured_generate.update(kwargs)
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        }

    monkeypatch.setattr(cli, "generate_pred_run_artifacts", fake_generate_pred_run_artifacts)

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    assert captured_generate["path"] == source_file
    assert captured_generate["run_manifest_kind"] == "bench_pred_run"
    run_manifest_path = eval_root / "run_manifest.json"
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["upload"] is False


def test_labelstudio_benchmark_applies_epub_extractor_for_prediction_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "unstructured")
    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "write_jsonl", lambda *_: None)

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured["runtime_epub_extractor"] = os.environ.get("C3IMP_EPUB_EXTRACTOR")
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11-00-00-00",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        eval_output_dir=tmp_path / "eval",
        allow_labelstudio_write=True,
        epub_extractor="legacy",
    )

    assert captured["runtime_epub_extractor"] == "legacy"
    assert os.environ.get("C3IMP_EPUB_EXTRACTOR") == "unstructured"


def test_labelstudio_benchmark_rejects_invalid_epub_extractor() -> None:
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(epub_extractor="invalid")


def test_build_all_method_variants_epub_expected_count() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
    )
    assert len(variants) == 15
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 15
    assert any("extractor_unstructured" in variant.slug for variant in variants)
    assert any("extractor_markdown" in variant.slug for variant in variants)


def test_build_all_method_variants_non_epub_single_variant() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=False,
    )
    assert len(variants) == 1
    assert variants[0].dimensions["source_extension"] == ".pdf"


def test_resolve_all_method_codex_choice_remains_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    include_effective, warning = cli._resolve_all_method_codex_choice(True)
    assert include_effective is False
    assert warning is not None
    assert cli.ALL_METHOD_CODEX_FARM_UNLOCK_ENV in warning

    monkeypatch.setenv(cli.ALL_METHOD_CODEX_FARM_UNLOCK_ENV, "1")
    include_effective_unlocked, warning_unlocked = cli._resolve_all_method_codex_choice(
        True
    )
    assert include_effective_unlocked is False
    assert warning_unlocked is not None
    assert "policy-locked OFF" in warning_unlocked


def test_run_all_method_benchmark_writes_ranked_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    markdown_settings = cli.RunSettings.from_dict(
        {
            **base_settings.to_run_config_dict(),
            "epub_extractor": "markdown",
        },
        warn_context="test",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=base_settings,
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=markdown_settings,
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    captured_processed_dirs: list[Path] = []

    def fake_labelstudio_benchmark(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        processed_output_dir = kwargs["processed_output_dir"]
        assert isinstance(processed_output_dir, Path)
        captured_processed_dirs.append(processed_output_dir)
        extractor = str(kwargs.get("epub_extractor") or "")
        f1 = 0.82 if extractor == "markdown" else 0.40
        report = {
            "precision": f1,
            "recall": f1,
            "f1": f1,
            "practical_precision": f1,
            "practical_recall": f1,
            "practical_f1": f1,
        }
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (eval_output_dir / "eval_report.md").write_text("report", encoding="utf-8")
        pred_run = eval_output_dir / "prediction-run"
        pred_run.mkdir(parents=True, exist_ok=True)
        (pred_run / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(source_file),
                    "run_config_hash": f"hash-{extractor}",
                    "run_config_summary": f"epub_extractor={extractor}",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    processed_root = tmp_path / "processed-output"
    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=processed_root,
        overlap_threshold=0.5,
        force_source_match=False,
    )

    assert report_md_path.exists()
    report_json_path = report_md_path.with_suffix(".json")
    payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert payload["variant_count"] == 2
    assert payload["successful_variants"] == 2
    assert payload["winner_by_f1"]["run_config_hash"] == "hash-markdown"
    assert payload["variants"][0]["rank"] == 1
    assert payload["variants"][0]["run_config_hash"] == "hash-markdown"
    assert captured_processed_dirs
    for processed_dir in captured_processed_dirs:
        assert str(processed_dir).startswith(str(processed_root))


def test_interactive_all_method_benchmark_uses_timestamped_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    benchmark_eval_output = tmp_path / "golden" / "2026-02-24_01.02.03"
    processed_output_root = tmp_path / "output"
    source_slug = cli.slugify_name(source_file.stem)

    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )
    monkeypatch.setattr(
        cli,
        "_build_all_method_variants",
        lambda **_kwargs: [
            cli.AllMethodVariant(
                slug="extractor_unstructured",
                run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
                dimensions={"epub_extractor": "unstructured"},
            )
        ],
    )
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_codex_choice",
        lambda _include_requested: (False, None),
    )

    confirm_answers = iter([False, True])
    monkeypatch.setattr(
        cli,
        "_prompt_confirm",
        lambda *_args, **_kwargs: next(confirm_answers),
    )

    captured: dict[str, object] = {}
    report_md_path = (
        benchmark_eval_output
        / "all-method-benchmark"
        / source_slug
        / "all_method_benchmark_report.md"
    )

    def fake_run_all_method_benchmark(**kwargs):
        captured.update(kwargs)
        return report_md_path

    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark",
        fake_run_all_method_benchmark,
    )

    cli._interactive_all_method_benchmark(
        selected_benchmark_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert captured["processed_output_root"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
        / source_slug
    )


def test_interactive_benchmark_all_method_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "all_method", "global", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("All-method mode should not resolve Label Studio credentials.")
        ),
    )

    captured: dict[str, object] = {}

    def fake_interactive_all_method_benchmark(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        cli,
        "_interactive_all_method_benchmark",
        fake_interactive_all_method_benchmark,
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert "selected_benchmark_settings" in captured
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT
