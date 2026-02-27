from __future__ import annotations

import inspect
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import cookimport.cli as cli
from cookimport.bench.prediction_records import (
    make_prediction_record,
    read_prediction_records,
    write_prediction_records,
)
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


def test_format_status_progress_message_appends_eta_to_top_line_for_multiline_payload() -> None:
    message = (
        "overall source 3/7 | config 58/91\n"
        "current source: AMatterOfTasteCUTDOWN.epub (13 of 15 configs; ok 13, fail 0)\n"
        "task: scheduler heavy 0/2 | wing 1 | active 2 | pending 0"
    )
    assert cli._format_status_progress_message(
        message,
        elapsed_seconds=3,
        elapsed_threshold_seconds=10,
        eta_seconds=174,
        avg_seconds_per_task=5.3,
    ) == (
        "overall source 3/7 | config 58/91 (eta 2m 54s, avg 5.3s/task)\n"
        "current source: AMatterOfTasteCUTDOWN.epub (13 of 15 configs; ok 13, fail 0)\n"
        "task: scheduler heavy 0/2 | wing 1 | active 2 | pending 0"
    )


def test_extract_progress_counter_uses_right_most_counter() -> None:
    assert cli._extract_progress_counter("item 1/5 [book] task 3/12") == (3, 12)
    dashboard_snapshot = (
        "overall source 0/7 | config 0/91\n"
        "current source: SeaAndSmokeCUTDOWN.epub (0 of 15 configs; ok 0, fail 0)\n"
        "current config 4/15: extractor_unstructured__parser_v1__skiphf_true__pre_none\n"
        "queue:\n"
        "  [>] SeaAndSmokeCUTDOWN.epub - 0 of 15 (ok 0, fail 0)\n"
        "task: overall source 0/7 | config 0/91 current config 4/15"
    )
    assert cli._extract_progress_counter(dashboard_snapshot) == (0, 91)
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


def test_all_method_dashboard_current_config_tracks_active_parallel_configs() -> None:
    source = cli.AllMethodTarget(
        gold_spans_path=Path("dummy/exports/freeform_span_labels.jsonl"),
        source_file=Path("dummy/book.epub"),
        source_file_name="book.epub",
        gold_display="dummy",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
            dimensions={"epub_extractor": "unstructured"},
        )
        for _ in range(3)
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants([(source, variants)])
    dashboard.start_source(0)
    dashboard.start_config(
        source_index=0,
        config_index=1,
        config_total=3,
        config_slug="config-one",
    )
    dashboard.start_config(
        source_index=0,
        config_index=2,
        config_total=3,
        config_slug="config-two",
    )
    dashboard.set_config_phase(source_index=0, config_index=1, phase="split_active")
    dashboard.set_config_phase(source_index=0, config_index=2, phase="evaluate")
    render_parallel = dashboard.render()
    assert "current configs 1-2/3 (2 active)" in render_parallel
    assert "active config workers:" in render_parallel
    assert "  config 01: split active | config-one" in render_parallel
    assert "  config 02: evaluate | config-two" in render_parallel

    dashboard.complete_config(source_index=0, success=True, config_index=1)
    render_single_active = dashboard.render()
    assert "current config 2/3: config-two" in render_single_active

    dashboard.complete_config(source_index=0, success=True, config_index=2)
    render_queued = dashboard.render()
    assert "current config 3/3: <queued>" in render_queued

    dashboard.start_config(
        source_index=0,
        config_index=3,
        config_total=3,
        config_slug="config-three",
    )
    dashboard.complete_config(source_index=0, success=True, config_index=3)
    render_done = dashboard.render()
    assert "current config " not in render_done


def test_all_method_dashboard_renders_multiple_running_sources() -> None:
    source_a = cli.AllMethodTarget(
        gold_spans_path=Path("dummy-a/exports/freeform_span_labels.jsonl"),
        source_file=Path("dummy-a/book-a.epub"),
        source_file_name="book-a.epub",
        gold_display="dummy-a",
    )
    source_b = cli.AllMethodTarget(
        gold_spans_path=Path("dummy-b/exports/freeform_span_labels.jsonl"),
        source_file=Path("dummy-b/book-b.epub"),
        source_file_name="book-b.epub",
        gold_display="dummy-b",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants(
        [
            (source_a, variants),
            (source_b, variants),
        ]
    )
    dashboard.start_source(0)
    dashboard.start_source(1)

    rendered = dashboard.render()
    assert "active sources: 2" in rendered
    assert "  [>] book-a.epub" in rendered
    assert "  [>] book-b.epub" in rendered


def test_run_with_progress_status_escapes_dashboard_markers(
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
        update_progress("queue:\n  [x] done row")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
    )

    assert result == {"ok": True}
    assert any("\\[x]" in message for message in capture.messages)


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


def test_load_source_hint_from_gold_export_falls_back_to_segment_manifest(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("\n", encoding="utf-8")
    segment_manifest = exports / "freeform_segment_manifest.jsonl"
    segment_manifest.write_text(
        json.dumps({"segment_id": "s1", "source_file": "book.epub"}) + "\n",
        encoding="utf-8",
    )

    source_hint = cli._load_source_hint_from_gold_export(gold_path)
    assert source_hint == "book.epub"


def test_resolve_all_method_targets_uses_segment_manifest_when_gold_rows_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")

    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("\n", encoding="utf-8")
    (exports / "freeform_segment_manifest.jsonl").write_text(
        json.dumps({"segment_id": "s1", "source_file": "book.epub"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [gold_path])
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [source])

    matched, unmatched = cli._resolve_all_method_targets(tmp_path)

    assert len(matched) == 1
    assert matched[0].gold_spans_path == gold_path
    assert matched[0].source_file == source
    assert unmatched == []


def test_resolve_all_method_targets_returns_matched_and_unmatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")

    matched_gold = tmp_path / "matched" / "exports" / "freeform_span_labels.jsonl"
    matched_gold.parent.mkdir(parents=True, exist_ok=True)
    matched_gold.write_text(
        json.dumps({"source_file": "book.epub", "label": "RECIPE_TITLE"}) + "\n",
        encoding="utf-8",
    )

    missing_hint_gold = tmp_path / "missing-hint" / "exports" / "freeform_span_labels.jsonl"
    missing_hint_gold.parent.mkdir(parents=True, exist_ok=True)
    missing_hint_gold.write_text("{}\n", encoding="utf-8")

    missing_input_gold = tmp_path / "missing-input" / "exports" / "freeform_span_labels.jsonl"
    missing_input_gold.parent.mkdir(parents=True, exist_ok=True)
    missing_input_gold.write_text(
        json.dumps({"source_file": "unknown.epub", "label": "RECIPE_TITLE"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_discover_freeform_gold_exports",
        lambda *_: [matched_gold, missing_hint_gold, missing_input_gold],
    )
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [source])

    matched, unmatched = cli._resolve_all_method_targets(tmp_path)

    assert [row.gold_spans_path for row in matched] == [matched_gold]
    assert [row.source_file for row in matched] == [source]
    assert len(unmatched) == 2
    assert "Missing source hint" in unmatched[0].reason
    assert unmatched[0].gold_spans_path == missing_hint_gold
    assert unmatched[0].source_hint is None
    assert "No importable file named `unknown.epub`" in unmatched[1].reason
    assert unmatched[1].gold_spans_path == missing_input_gold
    assert unmatched[1].source_hint == "unknown.epub"


def test_infer_scope_from_project_payload_detects_new_freeform_labels() -> None:
    scope = cli._infer_scope_from_project_payload(
        {"label_config": "<View><Label value='RECIPE_VARIANT'/></View>"}
    )
    assert scope == "freeform-spans"


def test_infer_scope_from_project_payload_keeps_old_freeform_detection() -> None:
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
                "processed_report_path": str(
                    tmp_path
                    / "output"
                    / "2026-02-16_15.00.00"
                    / "book.excel_import_report.json"
                ),
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
    captured_dashboard: dict[str, object] = {}

    def _capture_append(*args, **kwargs):
        captured_csv.update(kwargs)
        csv_path = Path(args[1])
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "run_timestamp,run_dir,file_name,run_category\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )
    monkeypatch.setattr(cli, "stats_dashboard", lambda **kwargs: captured_dashboard.update(kwargs))

    cli.labelstudio_eval(
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
    )

    assert captured_csv["recipes"] == 14
    assert captured_csv["source_file"] == str(tmp_path / "input" / "book.epub")
    assert captured_dashboard["output_root"] == tmp_path / "output"
    assert captured_dashboard["out_dir"] == tmp_path / ".history" / "dashboard"


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
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
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


def test_interactive_labelstudio_filters_incompatible_effort_choices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            (True, "annotations", True),
            "span",
            "gpt-5.3-codex-spark",
            "low",
            "exit",
        ]
    )
    effort_choice_values: list[str] = []

    def fake_menu_select(message: str, *_args, **kwargs):
        if message == "Codex thinking effort for AI prelabeling:":
            for choice in kwargs.get("choices", []):
                value = getattr(choice, "value", None)
                if isinstance(value, str):
                    effort_choice_values.append(value)
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
    monkeypatch.setattr(
        cli,
        "default_codex_model",
        lambda cmd=None: "gpt-5.3-codex-spark",
    )
    monkeypatch.setattr(
        cli,
        "default_codex_reasoning_effort",
        lambda cmd=None: "minimal",
    )
    monkeypatch.setattr(
        cli,
        "list_codex_models",
        lambda cmd=None: [
            {
                "slug": "gpt-5.3-codex-spark",
                "display_name": "gpt-5.3-codex-spark",
                "description": "Ultra-fast coding model",
                "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
            }
        ],
    )
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
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

    assert captured["codex_model"] == "gpt-5.3-codex-spark"
    assert captured["codex_reasoning_effort"] == "low"
    assert "__default_effort__" not in effort_choice_values
    assert "minimal" not in effort_choice_values
    assert "none" not in effort_choice_values
    assert effort_choice_values == ["low", "medium", "high", "xhigh"]


def test_interactive_labelstudio_freeform_focus_escape_steps_back_one_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
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

    assert captured["segment_blocks"] == 40
    assert captured["segment_overlap"] == 7
    assert captured["segment_focus_blocks"] == 40
    assert prompt_messages.count("Freeform overlap (blocks):") == 2


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
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
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
    assert captured["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert "label_studio_url" not in captured
    assert "label_studio_api_key" not in captured
    assert captured["epub_extractor"] == "beautifulsoup"
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
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
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
    assert captured["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
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
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert mode_prompt_count == 1
    assert not any("uploads to Label Studio" in title for title in mode_titles)


def test_interactive_labelstudio_export_routes_to_export_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    menu_answers = iter(["labelstudio_export", "exit"])

    def fake_menu_select(*_args, **_kwargs):
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
    assert captured["output_dir"] == selected_output / "pulled-from-labelstudio"


def test_interactive_labelstudio_export_selects_project_before_export(
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
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

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
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

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
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
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
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
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


def test_labelstudio_benchmark_predictions_out_writes_prediction_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
                "recipe_count": 7,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 1.5},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    predictions_out = tmp_path / "prediction-records.jsonl"
    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        predictions_out=predictions_out,
    )

    records = list(read_prediction_records(predictions_out))
    assert len(records) == 1
    record = records[0]
    assert record.prediction["stage_block_predictions_path"] == str(
        prediction_run / "stage_block_predictions.json"
    )
    assert record.prediction["extracted_archive_path"] == str(
        prediction_run / "extracted_archive.json"
    )
    assert record.predict_meta["source_file"] == str(source_file)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert "prediction_record_output_jsonl" in run_manifest["artifacts"]


def test_labelstudio_benchmark_predictions_in_runs_evaluate_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    stage_predictions_path = prediction_run / "stage_block_predictions.json"
    extracted_archive_path = prediction_run / "extracted_archive.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path.write_text("[]\n", encoding="utf-8")

    predictions_in = tmp_path / "prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="example-0",
                example_index=0,
                prediction={
                    "pred_run_dir": str(prediction_run),
                    "stage_block_predictions_path": str(stage_predictions_path),
                    "extracted_archive_path": str(extracted_archive_path),
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                    "run_config": {"workers": 1},
                    "run_config_hash": "cfg-hash",
                    "run_config_summary": "workers=1",
                    "timing": {"prediction_seconds": 4.2},
                },
            )
        ],
    )

    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not resolve Label Studio credentials.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not regenerate prediction artifacts.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_labelstudio_import",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not upload prediction artifacts.")
        ),
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_stage_blocks(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        predictions_in=predictions_in,
    )

    assert captured_eval["stage_predictions_json"] == stage_predictions_path
    assert captured_eval["extracted_blocks_json"] == extracted_archive_path
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["upload"] is False
    assert "prediction_record_input_jsonl" in run_manifest["artifacts"]


def test_labelstudio_benchmark_legacy_and_pipelined_modes_match_report_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 2.0},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    legacy_eval_root = tmp_path / "eval-legacy"
    pipelined_eval_root = tmp_path / "eval-pipelined"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=legacy_eval_root,
        no_upload=True,
        execution_mode="legacy",
    )
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=pipelined_eval_root,
        no_upload=True,
        execution_mode="pipelined",
    )

    legacy_report = json.loads(
        (legacy_eval_root / "eval_report.json").read_text(encoding="utf-8")
    )
    pipelined_report = json.loads(
        (pipelined_eval_root / "eval_report.json").read_text(encoding="utf-8")
    )
    legacy_report.pop("timing", None)
    pipelined_report.pop("timing", None)
    assert legacy_report == pipelined_report

    legacy_manifest = json.loads(
        (legacy_eval_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    pipelined_manifest = json.loads(
        (pipelined_eval_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert legacy_manifest["run_config"]["execution_mode"] == "legacy"
    assert pipelined_manifest["run_config"]["execution_mode"] == "pipelined"


def test_labelstudio_benchmark_canonical_text_mode_uses_canonical_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
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
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call stage-block evaluator.")
        ),
    )

    captured_eval: dict[str, object] = {}

    def _fake_eval_canonical_text(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_line_accuracy": 1.0,
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
                "evaluation_telemetry": {
                    "total_seconds": 1.5,
                    "subphases": {
                        "load_prediction_seconds": 0.12,
                        "load_gold_seconds": 0.34,
                        "alignment_seconds": 0.56,
                        "alignment_sequence_matcher_seconds": 0.45,
                    },
                    "resources": {
                        "process_cpu_seconds": 0.2,
                        "peak_ru_maxrss_kib": 123.0,
                    },
                    "work_units": {
                        "prediction_block_count": 10,
                        "prediction_text_char_count": 4567,
                    },
                },
            },
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_eval_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    eval_root = tmp_path / "eval"
    scheduler_events: list[dict[str, object]] = []
    with cli._benchmark_scheduler_event_overrides(
        scheduler_event_callback=lambda payload: scheduler_events.append(dict(payload))
    ):
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=eval_root,
            no_upload=True,
            eval_mode="canonical-text",
        )

    assert captured_eval["gold_export_root"] == gold_spans.parent
    assert captured_csv["eval_scope"] == "canonical-text"
    timing = captured_csv.get("timing")
    assert isinstance(timing, dict)
    checkpoints = timing.get("checkpoints")
    assert isinstance(checkpoints, dict)
    assert checkpoints["prediction_load_seconds"] == pytest.approx(0.12)
    assert checkpoints["gold_load_seconds"] == pytest.approx(0.34)
    assert checkpoints["evaluate_alignment_seconds"] == pytest.approx(0.56)
    assert checkpoints["evaluate_alignment_sequence_matcher_seconds"] == pytest.approx(0.45)
    assert checkpoints["evaluate_resource_process_cpu_seconds"] == pytest.approx(0.2)
    assert checkpoints["evaluate_work_prediction_block_count"] == pytest.approx(10.0)
    assert checkpoints["evaluate_work_prediction_text_char_count"] == pytest.approx(4567.0)
    event_names = [str(row.get("event") or "") for row in scheduler_events]
    assert "evaluate_started" in event_names
    assert "evaluate_finished" in event_names
    evaluate_finished_events = [
        row for row in scheduler_events if str(row.get("event") or "") == "evaluate_finished"
    ]
    assert evaluate_finished_events
    assert evaluate_finished_events[-1]["prediction_load_seconds"] == pytest.approx(0.12)
    assert evaluate_finished_events[-1]["gold_load_seconds"] == pytest.approx(0.34)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["eval_mode"] == "canonical-text"


def test_labelstudio_benchmark_captures_eval_profile_artifacts_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS", "0.001")
    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N", "5")
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call stage-block evaluator.")
        ),
    )

    def _fake_eval_canonical_text(**_kwargs):
        time.sleep(0.01)
        return {
            "report": {
                "counts": {"gold_total": 1, "pred_total": 1},
                "overall_line_accuracy": 1.0,
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "per_label": {},
                "evaluation_telemetry": {
                    "subphases": {
                        "load_prediction_seconds": 0.01,
                        "load_gold_seconds": 0.01,
                    }
                },
                "artifacts": {},
            },
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_eval_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        eval_mode="canonical-text",
    )

    assert (eval_root / "eval_profile.pstats").exists()
    assert (eval_root / "eval_profile_top.txt").exists()
    assert (eval_root / "eval_profile_top.txt").read_text(encoding="utf-8").strip()
    timing = captured_csv.get("timing")
    assert isinstance(timing, dict)
    checkpoints = timing.get("checkpoints")
    assert isinstance(checkpoints, dict)
    assert checkpoints["evaluate_profile_captured"] == pytest.approx(1.0)
    assert checkpoints["evaluate_profile_threshold_seconds"] == pytest.approx(0.001)
    assert checkpoints["evaluate_profile_artifact_write_seconds"] >= 0.0
    report = json.loads((eval_root / "eval_report.json").read_text(encoding="utf-8"))
    profiling = report["evaluation_telemetry"]["profiling"]
    assert profiling["enabled"] is True
    assert profiling["captured"] is True
    assert profiling["top_n"] == pytest.approx(5.0)
    assert profiling["threshold_seconds"] == pytest.approx(0.001)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert "eval_profile_pstats" in run_manifest["artifacts"]
    assert "eval_profile_top" in run_manifest["artifacts"]


def test_labelstudio_benchmark_writes_eval_timing_and_passes_csv_timing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
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
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "boundary": {"correct": 1, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {
                "total_seconds": 9.0,
                "prediction_seconds": 9.0,
                "parsing_seconds": 6.0,
                "writing_seconds": 2.0,
                "ocr_seconds": 0.5,
                "checkpoints": {"split_wait_seconds": 0.2},
            },
        },
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    report_payload = json.loads((eval_root / "eval_report.json").read_text(encoding="utf-8"))
    timing = report_payload.get("timing")
    assert isinstance(timing, dict)
    assert timing["prediction_seconds"] == pytest.approx(9.0)
    assert timing["evaluation_seconds"] >= 0.0
    assert timing["artifact_write_seconds"] >= 0.0
    assert timing["history_append_seconds"] >= 0.0
    assert timing["total_seconds"] >= timing["prediction_seconds"]
    assert timing["checkpoints"]["prediction_load_seconds"] >= 0.0
    assert timing["checkpoints"]["evaluate_seconds"] >= 0.0
    assert isinstance(captured_csv.get("timing"), dict)
    assert captured_csv["timing"]["prediction_seconds"] == pytest.approx(9.0)


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
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

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
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

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
        epub_extractor="beautifulsoup",
    )

    assert captured["runtime_epub_extractor"] == "beautifulsoup"
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


def test_resolve_all_method_scheduler_limits_defaults_raise_split_slots_to_four() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(total_variants=12)
    assert inflight == 4
    assert split_slots == 4


def test_resolve_all_method_source_parallelism_defaults_to_two() -> None:
    resolved = cli._resolve_all_method_source_parallelism(total_sources=7)
    assert resolved == 2


def test_resolve_all_method_source_parallelism_invalid_override_falls_back_to_default() -> None:
    resolved = cli._resolve_all_method_source_parallelism(
        total_sources=5,
        requested=0,
    )
    assert resolved == 2


def test_resolve_all_method_scheduler_limits_invalid_overrides_fall_back_to_defaults() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(
        total_variants=12,
        max_inflight_pipelines=0,
        max_concurrent_split_phases=0,
    )
    assert inflight == 4
    assert split_slots == 4


def test_resolve_all_method_scheduler_runtime_defaults_and_smart_backlog() -> None:
    configured, split_slots, wing_target, eval_tail_cap, smart_enabled, effective = (
        cli._resolve_all_method_scheduler_runtime(
            total_variants=12,
            max_inflight_pipelines=2,
            max_concurrent_split_phases=2,
            wing_backlog_target=3,
            smart_scheduler=True,
        )
    )
    assert configured == 2
    assert split_slots == 2
    assert wing_target == 3
    assert eval_tail_cap == 2
    assert smart_enabled is True
    assert effective == 7


def test_resolve_all_method_scheduler_runtime_invalid_wing_respects_fixed_mode() -> None:
    configured, split_slots, wing_target, eval_tail_cap, smart_enabled, effective = (
        cli._resolve_all_method_scheduler_runtime(
            total_variants=12,
            max_inflight_pipelines=3,
            max_concurrent_split_phases=2,
            wing_backlog_target=0,
            smart_scheduler=False,
        )
    )
    assert configured == 3
    assert split_slots == 2
    assert wing_target == 2
    assert eval_tail_cap == 2
    assert smart_enabled is False
    assert effective == 3


def test_resolve_all_method_scheduler_runtime_smart_tail_buffer_clamps_to_total() -> None:
    configured, split_slots, wing_target, eval_tail_cap, smart_enabled, effective = (
        cli._resolve_all_method_scheduler_runtime(
            total_variants=4,
            max_inflight_pipelines=2,
            max_concurrent_split_phases=2,
            wing_backlog_target=3,
            max_eval_tail_pipelines=3,
            smart_scheduler=True,
        )
    )
    assert configured == 2
    assert split_slots == 2
    assert wing_target == 3
    assert eval_tail_cap == 3
    assert smart_enabled is True
    assert effective == 4


def test_resolve_all_method_scheduler_runtime_respects_eval_tail_cap_override() -> None:
    configured, split_slots, wing_target, eval_tail_cap, smart_enabled, effective = (
        cli._resolve_all_method_scheduler_runtime(
            total_variants=12,
            max_inflight_pipelines=2,
            max_concurrent_split_phases=2,
            wing_backlog_target=3,
            max_eval_tail_pipelines=1,
            smart_scheduler=True,
        )
    )
    assert configured == 2
    assert split_slots == 2
    assert wing_target == 3
    assert eval_tail_cap == 1
    assert smart_enabled is True
    assert effective == 6


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
    captured_alignment_cache_dirs: list[Path] = []

    def fake_labelstudio_benchmark(**kwargs):
        progress_callback = cli._BENCHMARK_PROGRESS_CALLBACK.get()
        assert callable(progress_callback)
        assert kwargs.get("eval_mode") == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        processed_output_dir = kwargs["processed_output_dir"]
        assert isinstance(processed_output_dir, Path)
        captured_processed_dirs.append(processed_output_dir)
        alignment_cache_dir = kwargs["alignment_cache_dir"]
        assert isinstance(alignment_cache_dir, Path)
        captured_alignment_cache_dirs.append(alignment_cache_dir)
        extractor = str(kwargs.get("epub_extractor") or "")
        f1 = 0.82 if extractor == "markdown" else 0.40
        total_seconds = 8.0 if extractor == "markdown" else 5.0
        report = {
            "precision": f1,
            "recall": f1,
            "f1": f1,
            "practical_precision": f1,
            "practical_recall": f1,
            "practical_f1": f1,
            "timing": {
                "total_seconds": total_seconds,
                "prediction_seconds": total_seconds - 1.2,
                "evaluation_seconds": 1.2,
            },
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
    assert payload["timing_summary"]["source_wall_seconds"] >= 0.0
    assert payload["timing_summary"]["config_total_seconds"] == pytest.approx(13.0)
    assert payload["timing_summary"]["slowest_config_dir"] == payload["winner_by_f1"]["config_dir"]
    assert payload["variants"][0]["rank"] == 1
    assert payload["variants"][0]["run_config_hash"] == "hash-markdown"
    assert payload["variants"][0]["timing"]["total_seconds"] == pytest.approx(8.0)
    assert captured_processed_dirs
    assert captured_alignment_cache_dirs
    for processed_dir in captured_processed_dirs:
        assert str(processed_dir).startswith(str(processed_root))
    for cache_dir in captured_alignment_cache_dirs:
        assert cache_dir == (tmp_path / "all-method" / ".cache" / "canonical_alignment")


def test_run_all_method_benchmark_parallel_queue_respects_inflight_and_rank_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
    extractors = ("unstructured", "beautifulsoup", "markdown", "markitdown")
    variants = [
        cli.AllMethodVariant(
            slug=f"extractor_{extractor}",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": extractor},
                warn_context="test",
            ),
            dimensions={"epub_extractor": extractor},
        )
        for extractor in extractors
    ]
    scores = {
        "unstructured": 0.44,
        "beautifulsoup": 0.62,
        "markdown": 0.71,
        "markitdown": 0.89,
    }
    delays = {
        "unstructured": 0.08,
        "beautifulsoup": 0.03,
        "markdown": 0.06,
        "markitdown": 0.01,
    }
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    active_count = 0
    max_active = 0
    state_lock = threading.Lock()

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal active_count, max_active
        with state_lock:
            active_count += 1
            max_active = max(max_active, active_count)
        try:
            assert cli._BENCHMARK_SPLIT_PHASE_SLOTS.get() == 2
            assert cli._BENCHMARK_SPLIT_PHASE_GATE_DIR.get()

            extractor = str(kwargs.get("epub_extractor") or "")
            eval_output_dir = kwargs["eval_output_dir"]
            assert isinstance(eval_output_dir, Path)
            eval_output_dir.mkdir(parents=True, exist_ok=True)

            time.sleep(delays[extractor])
            f1 = scores[extractor]
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
        finally:
            with state_lock:
                active_count -= 1

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=3,
        max_concurrent_split_phases=2,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert max_active <= 3
    assert max_active >= 2
    assert payload["successful_variants"] == 4
    assert payload["failed_variants"] == 0
    assert payload["winner_by_f1"]["run_config_hash"] == "hash-markitdown"
    ranked_hashes = [
        row["run_config_hash"]
        for row in payload["variants"]
        if row.get("status") == "ok"
    ]
    assert ranked_hashes == [
        "hash-markitdown",
        "hash-markdown",
        "hash-beautifulsoup",
        "hash-unstructured",
    ]


def test_run_all_method_benchmark_marks_timeout_and_finishes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        if extractor == "unstructured":
            time.sleep(1.35)
        else:
            time.sleep(0.02)
        score = 0.9 if extractor == "markdown" else 0.2
        report = {
            "precision": score,
            "recall": score,
            "f1": score,
            "practical_precision": score,
            "practical_recall": score,
            "practical_f1": score,
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
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=1,
        config_timeout_seconds=1,
        retry_failed_configs=0,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["successful_variants"] == 1
    assert payload["failed_variants"] == 1
    failed_rows = [row for row in payload["variants"] if row.get("status") != "ok"]
    assert len(failed_rows) == 1
    assert "timed out after 1s" in str(failed_rows[0].get("error", "")).lower()


def test_run_all_method_benchmark_retries_only_failed_configs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_beautifulsoup",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "beautifulsoup"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "beautifulsoup"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    call_counts: dict[str, int] = {}

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "")
        call_counts[extractor] = call_counts.get(extractor, 0) + 1
        if extractor == "beautifulsoup" and call_counts[extractor] == 1:
            raise RuntimeError("synthetic transient failure")

        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        score = {
            "unstructured": 0.5,
            "beautifulsoup": 0.75,
            "markdown": 0.9,
        }[extractor]
        report = {
            "precision": score,
            "recall": score,
            "f1": score,
            "practical_precision": score,
            "practical_recall": score,
            "practical_f1": score,
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
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=3,
        max_concurrent_split_phases=2,
        retry_failed_configs=1,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert call_counts["beautifulsoup"] == 2
    assert call_counts["unstructured"] == 1
    assert call_counts["markdown"] == 1
    assert payload["successful_variants"] == 3
    assert payload["failed_variants"] == 0
    assert payload["retry_failed_configs_requested"] == 1
    assert payload["retry_passes_executed"] == 1
    assert payload["retry_recovered_configs"] == 1


def test_run_all_method_benchmark_smart_scheduler_improves_heavy_slot_utilization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = [
        cli.AllMethodVariant(
            slug=f"config_{index:02d}",
            run_settings=base_settings,
            dimensions={"index": index},
        )
        for index in range(1, 7)
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    phase_profile = {
        "prep": 0.18,
        "split_wait": 0.02,
        "split_active": 0.22,
        "post": 0.15,
    }
    split_gate = threading.Semaphore(2)

    def fake_labelstudio_benchmark(**kwargs):
        callback = cli._BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
        if callback is not None:
            callback({"event": "prep_started"})
            time.sleep(phase_profile["prep"])
            callback({"event": "prep_finished"})
            callback({"event": "split_wait_started"})
            time.sleep(phase_profile["split_wait"])
            split_gate.acquire()
            try:
                callback({"event": "split_wait_finished"})
                callback({"event": "split_active_started"})
                time.sleep(phase_profile["split_active"])
                callback({"event": "split_active_finished"})
            finally:
                split_gate.release()
            callback({"event": "post_started"})
            time.sleep(phase_profile["post"])
            callback({"event": "post_finished"})

        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        config_parts = eval_output_dir.name.split("_", 2)
        config_index = int(config_parts[1]) if len(config_parts) > 1 else 0
        score = 0.5 + (config_index * 0.01)
        report = {
            "precision": score,
            "recall": score,
            "f1": score,
            "practical_precision": score,
            "practical_recall": score,
            "practical_f1": score,
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
                    "run_config_hash": f"hash-{config_index:03d}",
                    "run_config_summary": f"config={config_index}",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    fixed_report = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-fixed",
        processed_output_root=tmp_path / "processed-fixed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=2,
        smart_scheduler=False,
    )
    fixed_payload = json.loads(fixed_report.with_suffix(".json").read_text(encoding="utf-8"))
    fixed_scheduler = fixed_payload["scheduler"]

    smart_report = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-smart",
        processed_output_root=tmp_path / "processed-smart",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=2,
        smart_scheduler=True,
    )
    smart_payload = json.loads(smart_report.with_suffix(".json").read_text(encoding="utf-8"))
    smart_scheduler = smart_payload["scheduler"]

    assert smart_scheduler["heavy_slot_utilization_pct"] > (
        fixed_scheduler["heavy_slot_utilization_pct"] + 15.0
    )
    assert smart_scheduler["max_active_pipelines_observed"] <= smart_scheduler[
        "effective_inflight_pipelines"
    ]
    assert smart_scheduler["max_active_pipelines_observed"] >= 3


def test_run_all_method_benchmark_falls_back_to_serial_when_executor_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    class BrokenExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("denied")

    monkeypatch.setattr(cli, "ProcessPoolExecutor", BrokenExecutor)

    call_count = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal call_count
        call_count += 1
        extractor = str(kwargs.get("epub_extractor") or "")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "precision": 0.7,
            "recall": 0.7,
            "f1": 0.7,
            "practical_precision": 0.7,
            "practical_recall": 0.7,
            "practical_f1": 0.7,
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

    messages: list[str] = []
    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: messages.append(str(message)),
    )

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=4,
        max_concurrent_split_phases=2,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert call_count == len(variants)
    assert payload["successful_variants"] == len(variants)
    assert any("falling back to serial mode" in message.lower() for message in messages)


def test_run_all_method_benchmark_multi_source_writes_combined_summary_with_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]
    unmatched = [
        cli.AllMethodUnmatchedGold(
            gold_spans_path=tmp_path / "gold-missing" / "exports" / "freeform_span_labels.jsonl",
            reason="Missing source hint in manifest, freeform_span_labels.jsonl, and freeform_segment_manifest.jsonl.",
            source_hint=None,
            gold_display="gold-missing",
        )
    ]

    def fake_run_all_method_benchmark(**kwargs):
        source_file = kwargs["source_file"]
        if source_file == source_b:
            raise RuntimeError("synthetic source failure")

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {
                "precision": 0.9,
                "recall": 0.8,
                "f1": 0.85,
            },
            "timing_summary": {
                "source_wall_seconds": 7.5,
                "config_total_seconds": 7.5,
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": 7.5,
            },
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=unmatched,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["matched_target_count"] == 2
    assert payload["unmatched_target_count"] == 1
    assert payload["total_config_runs_planned"] == 2
    assert payload["total_config_runs_completed"] == 1
    assert payload["total_config_runs_successful"] == 1
    assert payload["successful_source_count"] == 1
    assert payload["failed_source_count"] == 1
    assert payload["sources"][0]["status"] == "ok"
    assert payload["sources"][1]["status"] == "failed"
    assert payload["sources"][0]["timing_summary"]["source_wall_seconds"] == pytest.approx(7.5)
    assert payload["timing_summary"]["source_total_seconds"] == pytest.approx(7.5)
    assert payload["timing_summary"]["slowest_source"] == str(source_a)
    assert payload["timing_summary"]["slowest_config"] == "book_a/config_001"


def test_run_all_method_benchmark_multi_source_forwards_dashboard_snapshots_without_rewrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold",
            ),
            [variant],
        )
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants(target_variants)
    emitted_messages: list[str] = []

    def fake_run_all_method_benchmark(**kwargs):
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        progress_callback(
            "\n".join(
                [
                    "overall source 0/1 | config 0/1",
                    f"current source: {source.name} (0 of 1 configs; ok 0, fail 0)",
                    "current config 1/1: extractor_unstructured",
                    "queue:",
                    f"  [>] {source.name} - 0 of 1 (ok 0, fail 0)",
                ]
            )
        )

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "timing_summary": {"source_wall_seconds": 1.0, "config_total_seconds": 1.0},
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        progress_callback=emitted_messages.append,
        dashboard=dashboard,
    )

    assert any(message.startswith("overall source ") for message in emitted_messages)
    assert not any("task: overall source" in message for message in emitted_messages)


def test_run_all_method_benchmark_multi_source_rerenders_partial_dashboard_snapshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants(target_variants)
    emitted_messages: list[str] = []

    def fake_run_all_method_benchmark(**kwargs):
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        # Simulate a stale/partial snapshot from a nested callback. The wrapper
        # should rerender from the shared dashboard state instead.
        progress_callback(
            "\n".join(
                [
                    "overall source 0/2 | config 0/2",
                    f"current source: {source_a.name} (0 of 1 configs; ok 0, fail 0)",
                    "current config 1/1: extractor_unstructured",
                    "queue:",
                    f"  [>] {source_a.name} - 0 of 1 (ok 0, fail 0)",
                ]
            )
        )

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "timing_summary": {"source_wall_seconds": 1.0, "config_total_seconds": 1.0},
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        progress_callback=emitted_messages.append,
        dashboard=dashboard,
    )

    dashboard_messages = [
        message for message in emitted_messages if message.startswith("overall source ")
    ]
    assert dashboard_messages
    for message in dashboard_messages:
        assert source_a.name in message
        assert source_b.name in message


def test_run_all_method_benchmark_multi_source_parallel_cap_and_ordering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_c = tmp_path / "book-c.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    source_c.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_c = tmp_path / "gold-c" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_c.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")
    gold_c.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_c,
                source_file=source_c,
                source_file_name=source_c.name,
                gold_display="gold-c",
            ),
            [variant],
        ),
    ]
    delays = {
        source_a: 0.12,
        source_b: 0.02,
        source_c: 0.04,
    }
    active_sources = 0
    max_active_sources = 0
    state_lock = threading.Lock()

    def fake_run_all_method_benchmark(**kwargs):
        nonlocal active_sources, max_active_sources
        with state_lock:
            active_sources += 1
            max_active_sources = max(max_active_sources, active_sources)
        try:
            source_file = kwargs["source_file"]
            root_output_dir = kwargs["root_output_dir"]
            assert isinstance(source_file, Path)
            assert isinstance(root_output_dir, Path)
            time.sleep(delays[source_file])
            root_output_dir.mkdir(parents=True, exist_ok=True)
            report_md_path = root_output_dir / "all_method_benchmark_report.md"
            report_md_path.write_text("ok", encoding="utf-8")
            report_payload = {
                "successful_variants": 1,
                "failed_variants": 0,
                "winner_by_f1": {"precision": 0.9, "recall": 0.8, "f1": 0.85},
                "timing_summary": {
                    "source_wall_seconds": delays[source_file],
                    "config_total_seconds": delays[source_file],
                    "slowest_config_dir": "config_001",
                    "slowest_config_seconds": delays[source_file],
                },
                "scheduler": {
                    "mode": "smart",
                    "split_phase_slots": 2,
                    "smart_tail_buffer_slots": 2,
                    "effective_inflight_pipelines": 4,
                    "heavy_slot_capacity_seconds": 1.0,
                    "heavy_slot_busy_seconds": 1.0,
                    "idle_gap_seconds": 0.0,
                    "avg_wing_backlog": 1.0,
                    "max_wing_backlog": 2,
                    "max_active_pipelines_observed": 4,
                },
            }
            report_md_path.with_suffix(".json").write_text(
                json.dumps(report_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return report_md_path
        finally:
            with state_lock:
                active_sources -= 1

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=2,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["source_parallelism_configured"] == 2
    assert payload["source_parallelism_effective"] == 2
    assert max_active_sources <= 2
    assert max_active_sources >= 2
    assert [row["source_file_name"] for row in payload["sources"]] == [
        source_a.name,
        source_b.name,
        source_c.name,
    ]


def test_run_all_method_benchmark_multi_source_batches_dashboard_refresh_when_parallel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]

    per_source_refresh_values: list[bool] = []
    batch_refresh_calls: list[dict[str, object]] = []

    def fake_run_all_method_benchmark(**kwargs):
        per_source_refresh_values.append(bool(kwargs["refresh_dashboard_after_source"]))
        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 0.9, "recall": 0.8, "f1": 0.85},
            "timing_summary": {
                "source_wall_seconds": 1.0,
                "config_total_seconds": 1.0,
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": 1.0,
            },
            "scheduler": {
                "mode": "smart",
                "split_phase_slots": 2,
                "smart_tail_buffer_slots": 2,
                "effective_inflight_pipelines": 4,
                "heavy_slot_capacity_seconds": 1.0,
                "heavy_slot_busy_seconds": 1.0,
                "idle_gap_seconds": 0.0,
                "avg_wing_backlog": 1.0,
                "max_wing_backlog": 2,
                "max_active_pipelines_observed": 4,
            },
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)
    monkeypatch.setattr(
        cli,
        "_refresh_dashboard_after_history_write",
        lambda **kwargs: batch_refresh_calls.append(kwargs),
    )

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=2,
    )

    assert per_source_refresh_values == [False, False]
    assert len(batch_refresh_calls) == 1


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
    scope_messages: list[str] = []

    def fake_menu_select(message: str, **_kwargs):
        scope_messages.append(message)
        return "single"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
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

    assert scope_messages == ["Select all method benchmark scope:"]
    assert captured["processed_output_root"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
        / source_slug
    )


def test_interactive_all_method_benchmark_all_matched_scope_routes_to_multi_source_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    benchmark_eval_output = tmp_path / "golden" / "2026-02-24_01.02.03"
    processed_output_root = tmp_path / "output"

    captured_scope_messages: list[str] = []

    def fake_menu_select(message: str, **_kwargs):
        captured_scope_messages.append(message)
        return "all_matched"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-matched scope should not use single-pair resolver.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (
            [
                cli.AllMethodTarget(
                    gold_spans_path=gold_spans,
                    source_file=source_file,
                    source_file_name=source_file.name,
                    gold_display="gold",
                )
            ],
            [],
        ),
    )

    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        dimensions={"epub_extractor": "unstructured"},
    )

    def fake_build_target_variants(*, targets, **_kwargs):
        return [(target, [variant]) for target in targets]

    monkeypatch.setattr(cli, "_build_all_method_target_variants", fake_build_target_variants)
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
        / "all_method_benchmark_multi_source_report.md"
    )

    def fake_run_multi_source(**kwargs):
        captured.update(kwargs)
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_multi_source", fake_run_multi_source)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-matched scope should not call single-source runner.")
        ),
    )

    cli._interactive_all_method_benchmark(
        selected_benchmark_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert captured_scope_messages == ["Select all method benchmark scope:"]
    assert "target_variants" in captured
    assert captured["processed_output_root"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
    )


def test_interactive_benchmark_all_method_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "all_method", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-method mode should not prompt for run settings.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "save_last_run_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-method mode should not overwrite last benchmark settings.")
        ),
    )
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

    assert isinstance(captured.get("selected_benchmark_settings"), cli.RunSettings)
    expected_defaults = cli.RunSettings.from_dict(
        {},
        warn_context="interactive benchmark global settings",
    )
    assert captured["selected_benchmark_settings"].to_run_config_dict() == expected_defaults.to_run_config_dict()
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT


def test_interactive_benchmark_all_method_mode_uses_scheduler_limits_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "all_method", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda: {
            cli.ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY: "4",
            cli.ALL_METHOD_MAX_INFLIGHT_SETTING_KEY: "6",
            cli.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY: 3,
            cli.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY: "5",
            cli.ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY: "120",
            cli.ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY: "2",
            cli.ALL_METHOD_WING_BACKLOG_SETTING_KEY: "5",
            cli.ALL_METHOD_SMART_SCHEDULER_SETTING_KEY: "false",
        },
    )
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-method mode should not prompt for run settings.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "save_last_run_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-method mode should not overwrite last benchmark settings.")
        ),
    )
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

    assert captured["max_parallel_sources"] == 4
    assert captured["max_inflight_pipelines"] == 6
    assert captured["max_concurrent_split_phases"] == 3
    assert captured["max_eval_tail_pipelines"] == 5
    assert captured["config_timeout_seconds"] == 120
    assert captured["retry_failed_configs"] == 2
    assert captured["wing_backlog_target"] == 5
    assert captured["smart_scheduler"] is False
