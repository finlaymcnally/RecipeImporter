from __future__ import annotations

import inspect
import json
import os
import re
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


def _write_fake_all_method_prediction_phase_artifacts(
    *,
    kwargs: dict[str, object],
    source_file: Path,
    extractor: str,
    signature_seed: str | None = None,
    prediction_seconds: float = 0.0,
) -> None:
    eval_output_dir = kwargs["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    run_config_hash = f"hash-{extractor}"
    run_config_summary = f"epub_extractor={extractor}"
    record_text = signature_seed or extractor
    predictions_out = kwargs.get("predictions_out")
    if isinstance(predictions_out, Path):
        write_prediction_records(
            predictions_out,
            [
                make_prediction_record(
                    example_id=f"all-method:{source_file.name}:{record_text}:0",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"pred::{record_text}",
                        "block_features": {"signature_seed": record_text},
                    },
                    predict_meta={
                        "source_file": str(source_file),
                        "source_hash": f"source-{source_file.stem}",
                        "workbook_slug": source_file.stem,
                        "run_config_hash": run_config_hash,
                        "run_config_summary": run_config_summary,
                        "timing": {"prediction_seconds": prediction_seconds},
                    },
                )
            ],
        )

    pred_run = eval_output_dir / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": f"source-{source_file.stem}",
                "run_config_hash": run_config_hash,
                "run_config_summary": run_config_summary,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_config": {
                    "execution_mode": str(kwargs.get("execution_mode") or "predict-only"),
                    "predict_only": True,
                },
                "artifacts": {
                    "timing": {
                        "total_seconds": prediction_seconds,
                        "prediction_seconds": prediction_seconds,
                        "evaluation_seconds": 0.0,
                    }
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_fake_all_method_eval_artifacts(
    *,
    eval_output_dir: Path,
    score: float,
    total_seconds: float | None = None,
) -> None:
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "precision": score,
        "recall": score,
        "f1": score,
        "practical_precision": score,
        "practical_recall": score,
        "practical_f1": score,
    }
    if total_seconds is not None:
        report["timing"] = {
            "total_seconds": float(total_seconds),
            "prediction_seconds": 0.0,
            "evaluation_seconds": float(total_seconds),
        }
    (eval_output_dir / "eval_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (eval_output_dir / "eval_report.md").write_text("report", encoding="utf-8")


def _write_labelstudio_compare_source_row(
    *,
    run_root: Path,
    source_key: str,
    practical_f1: float,
    line_accuracy: float,
    ingredient_recall: float,
    variant_recall: float,
    llm_recipe_pipeline: str,
    codex_farm_recipe_mode: str,
    write_required_llm_debug: bool,
    write_prompt_manifests: bool | None = None,
    include_prediction_run_config: bool = True,
) -> dict[str, object]:
    source_root = run_root / "sources" / source_key
    eval_root = source_root / "winner_eval"
    prediction_run_root = eval_root / "prediction-run"
    prediction_run_root.mkdir(parents=True, exist_ok=True)

    (eval_root / "aligned_prediction_blocks.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )

    eval_report = {
        "practical_f1": practical_f1,
        "overall_line_accuracy": line_accuracy,
        "per_label": {
            "INGREDIENT_LINE": {"recall": ingredient_recall},
            "RECIPE_VARIANT": {"recall": variant_recall},
        },
        "artifacts": {
            "aligned_prediction_blocks_jsonl": "aligned_prediction_blocks.jsonl",
        },
    }
    (eval_root / "eval_report.json").write_text(
        json.dumps(eval_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if write_prompt_manifests is None:
        write_prompt_manifests = bool(write_required_llm_debug)
    if include_prediction_run_config:
        prediction_run_config = {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "codex_farm_recipe_mode": codex_farm_recipe_mode,
        }
    else:
        prediction_run_config = {}
    prediction_run_manifest = {
        "run_config": (
            {"prediction_run_config": prediction_run_config}
            if prediction_run_config
            else {}
        ),
        "artifacts": {},
    }
    (eval_root / "run_manifest.json").write_text(
        json.dumps(prediction_run_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if (
        llm_recipe_pipeline == "codex-farm-3pass-v1"
        and codex_farm_recipe_mode == "benchmark"
        and write_required_llm_debug
    ):
        llm_root = prediction_run_root / "llm"
        pass1_in = llm_root / "pass1_chunking" / "in"
        pass1_out = llm_root / "pass1_chunking" / "out"
        pass2_in = llm_root / "pass2_schemaorg" / "in"
        pass2_out = llm_root / "pass2_schemaorg" / "out"
        pass3_in = llm_root / "pass3_final" / "in"
        pass3_out = llm_root / "pass3_final" / "out"
        for folder in (pass1_in, pass1_out, pass2_in, pass2_out, pass3_in, pass3_out):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "r0000.json").write_text("{}", encoding="utf-8")
        llm_manifest = {
            "paths": {
                "pass1_in": str(pass1_in),
                "pass1_out": str(pass1_out),
                "pass2_in": str(pass2_in),
                "pass2_out": str(pass2_out),
                "pass3_in": str(pass3_in),
                "pass3_out": str(pass3_out),
            }
        }
        llm_manifest_path = prediction_run_root / "llm_manifest.json"
        llm_manifest_path.write_text(
            json.dumps(llm_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        prediction_run_manifest["artifacts"]["llm_manifest_json"] = str(llm_manifest_path)
        if write_prompt_manifests:
            prompt_input_payloads = [
                pass1_in / "prompt_request_0.json",
                pass2_in / "prompt_request_1.json",
                pass3_in / "prompt_request_2.json",
            ]
            prompt_output_payloads = [
                pass1_out / "prompt_response_0.json",
                pass2_out / "prompt_response_1.json",
                pass3_out / "prompt_response_2.json",
            ]
            for payload_path in prompt_input_payloads:
                payload_path.write_text("{}", encoding="utf-8")
            for payload_path in prompt_output_payloads:
                payload_path.write_text("{}", encoding="utf-8")
            prompt_inputs_manifest_path = prediction_run_root / "prompt_inputs_manifest.txt"
            prompt_outputs_manifest_path = prediction_run_root / "prompt_outputs_manifest.txt"
            prompt_inputs_manifest_path.write_text(
                "\n".join(str(path) for path in prompt_input_payloads) + "\n",
                encoding="utf-8",
            )
            prompt_outputs_manifest_path.write_text(
                "\n".join(str(path) for path in prompt_output_payloads) + "\n",
                encoding="utf-8",
            )
            prediction_run_manifest["artifacts"]["prompt_inputs_manifest_txt"] = str(
                prompt_inputs_manifest_path
            )
            prediction_run_manifest["artifacts"]["prompt_outputs_manifest_txt"] = str(
                prompt_outputs_manifest_path
            )

    (prediction_run_root / "run_manifest.json").write_text(
        json.dumps(prediction_run_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    source_report_path = source_root / "all_method_benchmark_report.json"
    source_report = {
        "winner_by_f1": {
            "eval_report_json": str(eval_root / "eval_report.json"),
        }
    }
    source_report_path.write_text(
        json.dumps(source_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "source_group_key": source_key,
        "report_json_path": str(source_report_path),
        "winner_metrics": {
            "precision": practical_f1,
            "recall": practical_f1,
            "f1": practical_f1,
            "practical_f1": practical_f1,
        },
    }


def _write_labelstudio_compare_multi_source_report(
    run_root: Path,
    rows: list[dict[str, object]],
) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    payload = {"sources": rows}
    (run_root / "all_method_benchmark_multi_source_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
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
        "task: scheduler heavy 0/2 | wing 1 | eval 0 | active 2 | pending 0"
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
        "task: scheduler heavy 0/2 | wing 1 | eval 0 | active 2 | pending 0"
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


def test_extract_all_method_dashboard_metrics_from_task_line() -> None:
    message = (
        "overall source 5/7 | config 71/91\n"
        "current source: saltfatacidheatCUTDOWN.epub (10 of 15 configs; ok 10, fail 0)\n"
        "queue:\n"
        "  [>] saltfatacidheatCUTDOWN.epub - 10 of 15 (ok 10, fail 0)\n"
        "task: scheduler heavy 0/4 | wing 0 | eval 5 | active 5 | pending 0"
    )
    assert cli._extract_all_method_dashboard_metrics(message) == {
        "wing": 0,
        "eval": 5,
        "active": 5,
        "pending": 0,
    }


def test_run_with_progress_status_uses_eval_tail_floor_for_all_method_eta(
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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    def _snapshot(completed: int) -> str:
        return (
            f"overall source 1/1 | config {completed}/10\n"
            "current source: thefoodlabCUTDOWN.epub (2 of 10 configs; ok 2, fail 0)\n"
            "queue:\n"
            "  [>] thefoodlabCUTDOWN.epub - 2 of 10 (ok 2, fail 0)\n"
            "task: scheduler heavy 0/4 | wing 0 | eval 5 | active 5 | pending 0"
        )

    capture = _CaptureStatus()
    monkeypatch.setattr(cli.console, "status", capture)

    def _run(update_progress):
        update_progress(_snapshot(1))
        time.sleep(0.08)
        update_progress(_snapshot(2))
        # Simulate a long eval tail with no additional completions.
        time.sleep(1.6)
        update_progress(_snapshot(2))
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
        force_live_status=True,
    )

    assert result == {"ok": True}
    eta_seconds = [
        int(match.group(1))
        for message in capture.messages
        if "overall source 1/1 | config 2/10" in message
        for match in [re.search(r"eta (\d+)s", message)]
        if match is not None
    ]
    assert eta_seconds, "Expected ETA on all-method progress line"
    assert max(eta_seconds) >= 2


def test_run_with_progress_status_defaults_to_plain_for_agent_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _GuardConsole:
        is_terminal = True
        is_dumb_terminal = False

        def status(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("Live status should not be used in agent env default mode.")

    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.delenv("COOKIMPORT_PLAIN_PROGRESS", raising=False)
    monkeypatch.setattr(cli, "console", _GuardConsole())
    plain_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: plain_messages.append(str(message)),
    )

    def _run(update_progress):
        update_progress("Quality suite task 1/2")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running bench quality suite...",
        progress_prefix="Bench quality",
        run=_run,
    )

    assert result == {"ok": True}
    assert any(
        "Bench quality: Quality suite task 1/2" in message for message in plain_messages
    )


def test_run_with_progress_status_agent_plain_default_allows_explicit_live_override(
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

    class _CaptureConsole:
        is_terminal = True
        is_dumb_terminal = False

        def __init__(self) -> None:
            self.status_calls = 0
            self.messages: list[str] = []

        def status(
            self,
            message: str,
            spinner: str = "dots",
            **_kwargs: object,
        ) -> _FakeStatus:
            self.status_calls += 1
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureConsole()
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("COOKIMPORT_PLAIN_PROGRESS", "0")
    monkeypatch.setattr(cli, "console", capture)

    def _run(update_progress):
        update_progress("Quality suite task 1/2")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running bench quality suite...",
        progress_prefix="Bench quality",
        run=_run,
        tick_seconds=0.05,
    )

    assert result == {"ok": True}
    assert capture.status_calls == 1
    assert any(
        "Bench quality: Quality suite task 1/2" in message for message in capture.messages
    )


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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
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
        force_live_status=True,
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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
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
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any(
        "Import: Running freeform prelabeling... task 2/4 (eta " in message
        and "avg " in message
        and "s/task" in message
        for message in capture.messages
    )


def test_run_with_progress_status_writes_processing_timeseries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureStatus()
    monkeypatch.setattr(cli.console, "status", capture)
    telemetry_path = tmp_path / "processing_timeseries.jsonl"

    def _run(update_progress):
        update_progress("Preparing task 1/2")
        time.sleep(0.06)
        update_progress("Preparing task 2/2")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
        telemetry_path=telemetry_path,
        telemetry_heartbeat_seconds=0.05,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert telemetry_path.exists()
    rows = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    assert rows[0]["event"] == "started"
    assert rows[-1]["event"] == "finished"
    assert any(row.get("task_current") == 2 for row in rows)
    assert any("cpu_utilization_pct" in row for row in rows)


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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
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
        force_live_status=True,
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

        def __call__(self, message: str, spinner: str = "dots", **_kwargs: object) -> _FakeStatus:
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
        force_live_status=True,
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


def test_build_codex_farm_prompt_response_log_writes_task_category_logs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "pass1_chunking" / "in"
    pass1_out = run_dir / "pass1_chunking" / "out"
    pass2_in = run_dir / "pass2_schemaorg" / "in"
    pass2_out = run_dir / "pass2_schemaorg" / "out"
    pass3_in = run_dir / "pass3_final" / "in"
    pass3_out = run_dir / "pass3_final" / "out"
    for folder in (pass1_in, pass1_out, pass2_in, pass2_out, pass3_in, pass3_out):
        folder.mkdir(parents=True, exist_ok=True)

    attached = run_dir / "attachments" / "task1_notes.txt"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("attachment content\n", encoding="utf-8")

    (pass1_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass1 prompt", "attachment_file_path": str(attached)}),
        encoding="utf-8",
    )
    (pass1_out / "r0000.json").write_text(
        json.dumps({"result": "pass1 response"}),
        encoding="utf-8",
    )
    (pass2_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass2 prompt"}),
        encoding="utf-8",
    )
    (pass2_out / "r0000.json").write_text(
        json.dumps({"result": "pass2 response"}),
        encoding="utf-8",
    )
    (pass3_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass3 prompt"}),
        encoding="utf-8",
    )
    (pass3_out / "r0000.json").write_text(
        json.dumps({"result": "pass3 response"}),
        encoding="utf-8",
    )

    (run_dir / "llm_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-farm-3pass-v1",
                "paths": {
                    "pass1_in": str(pass1_in),
                    "pass1_out": str(pass1_out),
                    "pass2_in": str(pass2_in),
                    "pass2_out": str(pass2_out),
                    "pass3_in": str(pass3_in),
                    "pass3_out": str(pass3_out),
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    log_path = cli._build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
    )

    assert log_path == eval_output_dir / "codexfarm" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT pass1 => r0000.json" in combined
    assert "OUTPUT pass3 => r0000.json" in combined

    task1_path = eval_output_dir / "codexfarm" / "prompt_task1_pass1_chunking.txt"
    task2_path = eval_output_dir / "codexfarm" / "prompt_task2_pass2_schemaorg.txt"
    task3_path = eval_output_dir / "codexfarm" / "prompt_task3_pass3_final.txt"
    for category_path in (task1_path, task2_path, task3_path):
        assert category_path.exists()

    task1_text = task1_path.read_text(encoding="utf-8")
    assert "ATTACHMENT task1 =>" in task1_text
    assert str(attached) in task1_text
    assert "attachment content" in task1_text

    manifest_path = eval_output_dir / "codexfarm" / "prompt_category_logs_manifest.txt"
    assert manifest_path.exists()
    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [str(task1_path), str(task2_path), str(task3_path)]

    full_prompt_log_path = eval_output_dir / "codexfarm" / "full_prompt_log.jsonl"
    assert full_prompt_log_path.exists()
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 3
    assert {str(row.get("pass") or "") for row in full_prompt_rows} == {
        "pass1",
        "pass2",
        "pass3",
    }
    pass1_row = next(row for row in full_prompt_rows if row.get("pass") == "pass1")
    assert pass1_row["call_id"] == "r0000"
    assert pass1_row["request_messages"][0]["role"] == "user"
    assert "pass1 prompt" in pass1_row["request_messages"][0]["content"]
    assert pass1_row["parsed_response"] == {"result": "pass1 response"}
    assert pass1_row["raw_response"]["output_file"].endswith("r0000.json")


def test_build_codex_farm_prompt_response_log_handles_missing_pass_dirs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "pass1_chunking" / "in"
    pass1_out = run_dir / "pass1_chunking" / "out"
    pass1_in.mkdir(parents=True, exist_ok=True)
    pass1_out.mkdir(parents=True, exist_ok=True)
    (pass1_in / "r0000.json").write_text(json.dumps({"prompt_text": "ok"}), encoding="utf-8")
    (pass1_out / "r0000.json").write_text(json.dumps({"result": "ok"}), encoding="utf-8")

    (run_dir / "llm_manifest.json").write_text(
        json.dumps(
            {
                "paths": {
                    "pass1_in": str(pass1_in),
                    "pass1_out": str(pass1_out),
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    log_path = cli._build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
    )
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "codexfarm" / "prompt_task1_pass1_chunking.txt").exists()
    assert not (eval_output_dir / "codexfarm" / "prompt_task2_pass2_schemaorg.txt").exists()
    assert not (eval_output_dir / "codexfarm" / "prompt_task3_pass3_final.txt").exists()
    full_prompt_log_path = eval_output_dir / "codexfarm" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["pass"] == "pass1"


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
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **kwargs: kwargs["global_defaults"],
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
    assert eval_output_dir.name == "vanilla"
    assert eval_output_dir.parent.name == "single-offline-benchmark"
    assert eval_output_dir.parent.parent.parent == golden_root / "benchmark-vs-golden"
    processed_output_dir = captured["processed_output_dir"]
    assert isinstance(processed_output_dir, Path)
    assert processed_output_dir.name == "vanilla"
    assert processed_output_dir.parent.name == "single-offline-benchmark"
    assert processed_output_dir.parent.parent.parent == configured_output
    assert captured["no_upload"] is True
    assert captured["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert captured["write_markdown"] is False
    assert "label_studio_url" not in captured
    assert "label_studio_api_key" not in captured
    assert captured["epub_extractor"] == "beautifulsoup"
    assert mode_prompts
    assert not any("offline, no upload" in title for title in mode_prompts[0])
    assert not any("uploads to Label Studio" in title for title in mode_prompts[0])
    assert not any("All method benchmark" in title for title in mode_prompts[0])


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
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **kwargs: kwargs["global_defaults"],
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
    assert eval_output_dir.name == "vanilla"
    assert eval_output_dir.parent.name == "single-offline-benchmark"
    assert eval_output_dir.parent.parent.parent == golden_root / "benchmark-vs-golden"
    processed_output_dir = captured["processed_output_dir"]
    assert isinstance(processed_output_dir, Path)
    assert processed_output_dir.name == "vanilla"
    assert processed_output_dir.parent.name == "single-offline-benchmark"
    assert processed_output_dir.parent.parent.parent == configured_output
    assert captured["no_upload"] is True
    assert captured["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert "allow_labelstudio_write" not in captured
    assert "label_studio_url" not in captured
    assert "label_studio_api_key" not in captured


def test_interactive_generate_dashboard_runs_without_browser_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["generate_dashboard", "exit"])

    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {"output_dir": str(configured_output)})
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Dashboard flow should not ask to open a browser.")
        ),
    )

    captured: dict[str, object] = {}

    def fake_stats_dashboard(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "stats_dashboard", fake_stats_dashboard)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["output_root"] == configured_output
    assert captured["golden_root"] == golden_root
    assert captured["out_dir"] == configured_output.parent / ".history" / "dashboard"
    assert captured["open_browser"] is False
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
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **kwargs: kwargs["global_defaults"],
    )
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
    assert benchmark_calls[0]["eval_output_dir"].name == "vanilla"
    assert benchmark_calls[0]["eval_output_dir"].parent.name == "single-offline-benchmark"
    assert benchmark_calls[0]["no_upload"] is True
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert mode_prompt_count == 1
    assert not any("uploads to Label Studio" in title for title in mode_titles)


def test_interactive_single_offline_codex_enabled_runs_vanilla_then_codex_and_writes_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-3pass-v1"},
        warn_context="test codex-enabled",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_path = str(tmp_path / "book.epub")

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        llm_pipeline = str(kwargs.get("llm_recipe_pipeline") or "").strip().lower()
        metrics = {
            "precision": 0.42 if llm_pipeline == "codex-farm-3pass-v1" else 0.39,
            "recall": 0.33 if llm_pipeline == "codex-farm-3pass-v1" else 0.30,
            "f1": 0.37 if llm_pipeline == "codex-farm-3pass-v1" else 0.34,
            "practical_precision": None,
            "practical_recall": None,
            "practical_f1": None,
        }
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": source_path},
                    "run_config": {
                        "llm_recipe_pipeline": llm_pipeline,
                        "codex_farm_model": (
                            "gpt-5.3-codex-spark"
                            if llm_pipeline == "codex-farm-3pass-v1"
                            else None
                        ),
                        "codex_farm_reasoning_effort": (
                            "low" if llm_pipeline == "codex-farm-3pass-v1" else None
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_offline_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-farm-3pass-v1",
    ]
    expected_split_cache_dir = (
        benchmark_eval_output / "single-offline-benchmark" / ".split-cache"
    )
    assert [call["single_offline_split_cache_mode"] for call in benchmark_calls] == [
        "auto",
        "auto",
    ]
    assert [call["single_offline_split_cache_dir"] for call in benchmark_calls] == [
        expected_split_cache_dir,
        expected_split_cache_dir,
    ]
    split_cache_keys = [
        str(call.get("single_offline_split_cache_key") or "")
        for call in benchmark_calls
    ]
    assert split_cache_keys[0]
    assert split_cache_keys[0] == split_cache_keys[1]
    assert [call["single_offline_split_cache_force"] for call in benchmark_calls] == [
        False,
        False,
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-offline-benchmark" / "vanilla",
        benchmark_eval_output / "single-offline-benchmark" / "codexfarm",
    ]
    assert [call["processed_output_dir"] for call in benchmark_calls] == [
        processed_output_root
        / benchmark_eval_output.name
        / "single-offline-benchmark"
        / "vanilla",
        processed_output_root
        / benchmark_eval_output.name
        / "single-offline-benchmark"
        / "codexfarm",
    ]

    comparison_json = (
        benchmark_eval_output
        / "single-offline-benchmark"
        / "codex_vs_vanilla_comparison.json"
    )
    comparison_md = (
        benchmark_eval_output
        / "single-offline-benchmark"
        / "codex_vs_vanilla_comparison.md"
    )
    assert comparison_json.exists()
    assert not comparison_md.exists()

    payload = json.loads(comparison_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "codex_vs_vanilla_comparison.v2"
    assert payload["run_timestamp"] == benchmark_eval_output.name
    assert payload["source_file"] == source_path
    assert payload["variants"]["codexfarm"]["eval_output_dir"].endswith(
        "/single-offline-benchmark/codexfarm"
    )
    assert payload["variants"]["vanilla"]["eval_output_dir"].endswith(
        "/single-offline-benchmark/vanilla"
    )
    assert payload["metrics"]["codexfarm"]["strict_accuracy"] == pytest.approx(0.42)
    assert payload["metrics"]["vanilla"]["strict_accuracy"] == pytest.approx(0.39)
    assert "precision" not in payload["metrics"]["codexfarm"]
    assert "precision" not in payload["metrics"]["vanilla"]
    assert "precision" not in payload["deltas"]["codex_minus_vanilla"]
    assert payload["deltas"]["codex_minus_vanilla"]["strict_accuracy"] == pytest.approx(0.03)
    assert payload["deltas"]["codex_minus_vanilla"]["macro_f1_excluding_other"] is None
    assert payload["metadata"]["codex_farm_runtime"]["codex_model"] == "gpt-5.3-codex-spark"
    assert (
        payload["metadata"]["codex_farm_runtime"]["codex_reasoning_effort"] == "low"
    )


def test_interactive_single_offline_uses_book_slug_in_session_root_when_source_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test source-slugged-single-offline-root",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_file = tmp_path / "The Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _FakeStdin())
    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(source_file)}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_offline_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    source_slug = cli.slugify_name(source_file.stem)
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output
        / "single-offline-benchmark"
        / source_slug
        / "vanilla"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-offline-benchmark"
        / source_slug
        / "vanilla"
    )


def test_single_offline_comparison_markdown_table_columns_are_width_aligned() -> None:
    payload = {
        "schema_version": "codex_vs_vanilla_comparison.v2",
        "run_timestamp": "2026-03-02_21.25.24",
        "source_file": "book.epub",
        "variants": {
            "codexfarm": {"eval_output_dir": "codex"},
            "vanilla": {"eval_output_dir": "vanilla"},
        },
        "metrics": {
            "codexfarm": {
                "strict_accuracy": 0.438589,
                "macro_f1_excluding_other": 0.295998,
            },
            "vanilla": {
                "strict_accuracy": 0.399915,
                "macro_f1_excluding_other": 0.290594,
            },
        },
        "deltas": {
            "codex_minus_vanilla": {
                "strict_accuracy": 0.038674,
                "macro_f1_excluding_other": 0.005404,
            }
        },
        "metadata": {},
    }

    markdown = cli._format_single_offline_comparison_markdown(payload)
    table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
    assert len(table_lines) == 4

    expected_pipes = [idx for idx, char in enumerate(table_lines[0]) if char == "|"]
    assert len(expected_pipes) == 5
    for line in table_lines[1:]:
        assert [idx for idx, char in enumerate(line) if char == "|"] == expected_pipes

    assert table_lines[0] == "| Metric                     | CodexFarm |  Vanilla | Codex - Vanilla |"
    assert table_lines[2] == "| `strict_accuracy`          |  0.438589 | 0.399915 |        0.038674 |"
    assert table_lines[3] == "| `macro_f1_excluding_other` |  0.295998 | 0.290594 |        0.005404 |"
    assert "Compatibility aliases in eval JSON" not in markdown


def test_single_offline_comparison_markdown_includes_per_label_breakdown() -> None:
    payload = {
        "schema_version": "codex_vs_vanilla_comparison.v2",
        "run_timestamp": "2026-03-02_21.25.24",
        "source_file": "book.epub",
        "variants": {
            "codexfarm": {"eval_output_dir": "codex"},
            "vanilla": {"eval_output_dir": "vanilla"},
        },
        "metrics": {},
        "deltas": {"codex_minus_vanilla": {}},
        "metadata": {
            "per_label_breakdown": {
                "schema_version": "single_offline_per_label_breakdown.v1",
                "run_timestamp": "2026-03-02_21.25.24",
                "eval_count": 2,
                "rows": [
                    {
                        "label": "RECIPE_TITLE",
                        "precision": 0.811111,
                        "recall": 0.598361,
                        "gold_total": 122,
                        "pred_total": 90,
                    },
                    {
                        "label": "INGREDIENT_LINE",
                        "precision": 0.745341,
                        "recall": 0.137300,
                        "gold_total": 874,
                        "pred_total": 161,
                    },
                ],
            }
        },
    }

    markdown = cli._format_single_offline_comparison_markdown(payload)
    assert "## Per-Label Breakdown (2026-03-02_21.25.24, 2 evals)" in markdown
    assert (
        "Per label: precision answers false alarms, recall answers misses."
        in markdown
    )
    assert "| Label           | Precision | Recall | Gold | Pred |" in markdown
    assert "| INGREDIENT_LINE |    0.7453 | 0.1373 |  874 |  161 |" in markdown
    assert "| RECIPE_TITLE    |    0.8111 | 0.5984 |  122 |   90 |" in markdown


def test_single_offline_comparison_artifacts_include_per_label_breakdown(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "precision": 0.5,
                "recall": 0.6,
                "f1": 0.55,
                "per_label": {
                    "RECIPE_TITLE": {
                        "precision": 1.0,
                        "recall": 0.5,
                        "gold_total": 10,
                        "pred_total": 5,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "precision": 0.4,
                "recall": 0.5,
                "f1": 0.45,
                "per_label": {
                    "RECIPE_TITLE": {
                        "precision": 0.5,
                        "recall": 1.0,
                        "gold_total": 4,
                        "pred_total": 8,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    written = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_21.25.24",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=True,
    )

    assert written is not None
    comparison_json_path, comparison_md_path = written
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    per_label_breakdown = payload["metadata"]["per_label_breakdown"]
    assert per_label_breakdown["schema_version"] == "single_offline_per_label_breakdown.v1"
    assert per_label_breakdown["run_timestamp"] == "2026-03-02_21.25.24"
    assert per_label_breakdown["eval_count"] == 2
    assert len(per_label_breakdown["rows"]) == 1
    row = per_label_breakdown["rows"][0]
    assert row["label"] == "RECIPE_TITLE"
    assert row["precision"] == pytest.approx(9 / 13)
    assert row["recall"] == pytest.approx(9 / 14)
    assert row["gold_total"] == 14
    assert row["pred_total"] == 13

    assert comparison_md_path is not None
    markdown = comparison_md_path.read_text(encoding="utf-8")
    assert "## Per-Label Breakdown (2026-03-02_21.25.24, 2 evals)" in markdown
    assert "| RECIPE_TITLE |    0.6923 | 0.6429 |   14 |   13 |" in markdown


def test_interactive_single_offline_codex_disabled_runs_only_vanilla_and_skips_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test codex-off",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_offline_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-offline-benchmark" / "vanilla"
    )
    assert not (
        benchmark_eval_output
        / "single-offline-benchmark"
        / "codex_vs_vanilla_comparison.json"
    ).exists()
    assert not (
        benchmark_eval_output
        / "single-offline-benchmark"
        / "codex_vs_vanilla_comparison.md"
    ).exists()


def test_single_offline_comparison_artifacts_markdown_toggle(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.50, "recall": 0.60, "f1": 0.55}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.40, "recall": 0.50, "f1": 0.45}),
        encoding="utf-8",
    )

    comparison_paths = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=False,
    )

    assert comparison_paths is not None
    comparison_json_path, comparison_md_path = comparison_paths
    assert comparison_json_path.exists()
    assert comparison_md_path is None
    assert not (session_root / "codex_vs_vanilla_comparison.md").exists()

    comparison_paths_markdown = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=True,
    )
    assert comparison_paths_markdown is not None
    _, comparison_md_path_markdown = comparison_paths_markdown
    assert comparison_md_path_markdown is not None
    assert comparison_md_path_markdown.exists()


def test_interactive_single_offline_markdown_enabled_writes_one_top_level_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-3pass-v1"},
        warn_context="test markdown-summary",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_path = str(tmp_path / "book.epub")

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        llm_pipeline = str(kwargs.get("llm_recipe_pipeline") or "").strip().lower()
        metrics = {
            "overall_line_accuracy": 0.71 if llm_pipeline == "codex-farm-3pass-v1" else 0.68,
            "precision": 0.42 if llm_pipeline == "codex-farm-3pass-v1" else 0.39,
            "recall": 0.41 if llm_pipeline == "codex-farm-3pass-v1" else 0.38,
            "f1": 0.40 if llm_pipeline == "codex-farm-3pass-v1" else 0.37,
            "macro_f1_excluding_other": 0.52
            if llm_pipeline == "codex-farm-3pass-v1"
            else 0.49,
            "practical_precision": 0.31 if llm_pipeline == "codex-farm-3pass-v1" else 0.29,
            "practical_recall": 0.30 if llm_pipeline == "codex-farm-3pass-v1" else 0.28,
            "practical_f1": 0.29 if llm_pipeline == "codex-farm-3pass-v1" else 0.27,
        }
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": source_path}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_offline_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=True,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert all(call["write_markdown"] is False for call in benchmark_calls)
    session_root = benchmark_eval_output / "single-offline-benchmark"
    summary_path = session_root / "single_offline_summary.md"
    assert summary_path.exists()
    md_files = sorted(session_root.rglob("*.md"))
    assert md_files == [summary_path]
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "Single Offline Benchmark Summary" in summary_text
    assert "Codex vs Vanilla" in summary_text
    assert "codex_vs_vanilla_comparison.json" in summary_text
    assert not (session_root / "codex_vs_vanilla_comparison.md").exists()


def test_single_offline_comparison_includes_codex_runtime_from_llm_manifest_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "default_codex_reasoning_effort", lambda cmd=None: "high")

    session_root = tmp_path / "single-offline-benchmark"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.40, "recall": 0.32, "f1": 0.35}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.38, "recall": 0.30, "f1": 0.33}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "run_manifest.json").write_text(
        json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
        encoding="utf-8",
    )
    (codex_eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "source": {"path": str(tmp_path / "book.epub")},
                "run_config": {
                    "llm_recipe_pipeline": "codex-farm-3pass-v1",
                    "codex_farm_model": None,
                    "codex_farm_reasoning_effort": None,
                },
                "artifacts": {"pred_run_dir": "prediction-run"},
            }
        ),
        encoding="utf-8",
    )

    llm_manifest_path = (
        codex_eval_output_dir
        / "prediction-run"
        / "raw"
        / "llm"
        / "book"
        / "llm_manifest.json"
    )
    llm_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    llm_manifest_path.write_text(
        json.dumps(
            {
                "codex_farm_model": None,
                "codex_farm_reasoning_effort": None,
                "process_runs": {
                    "pass1": {
                        "process_payload": {
                            "codex_model": "gpt-5.3-codex-spark",
                            "codex_reasoning_effort": None,
                        },
                        "telemetry_report": {
                            "insights": {
                                "model_reasoning_breakdown": [
                                    {
                                        "model": "gpt-5.3-codex-spark",
                                        "reasoning_effort": "<default>",
                                    }
                                ]
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    written = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file=str(tmp_path / "book.epub"),
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
    )

    assert written is not None
    comparison_json_path = written[0]
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["codex_farm_runtime"]["codex_model"] == "gpt-5.3-codex-spark"
    assert (
        payload["metadata"]["codex_farm_runtime"]["codex_reasoning_effort"]
        == "high"
    )


def test_interactive_single_offline_codex_failure_preserves_vanilla_and_skips_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-3pass-v1"},
        warn_context="test codex-fails",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        llm_pipeline = str(kwargs.get("llm_recipe_pipeline") or "").strip().lower()
        if llm_pipeline == "codex-farm-3pass-v1":
            raise cli.typer.Exit(2)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.30, "recall": 0.20, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_offline_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-farm-3pass-v1",
    ]
    vanilla_eval_dir = benchmark_eval_output / "single-offline-benchmark" / "vanilla"
    assert (vanilla_eval_dir / "eval_report.json").exists()
    assert not (
        benchmark_eval_output
        / "single-offline-benchmark"
        / "codex_vs_vanilla_comparison.json"
    ).exists()


def test_labelstudio_benchmark_compare_payload_passes_with_required_debug_artifacts(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["schema_version"] == "labelstudio_benchmark_compare.v1"
    assert payload["overall"]["verdict"] == "PASS"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["sea_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["foodlab_variant_recall_nonzero"]["passed"] is True


def test_labelstudio_benchmark_compare_payload_fails_when_required_debug_artifacts_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False


def test_labelstudio_benchmark_compare_payload_fails_when_benchmark_mode_metadata_is_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                write_prompt_manifests=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False
    assert (
        "Missing required debug artifacts:"
        in str(gates_by_name["foodlab_debug_artifacts_present"]["reason"])
    )
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "inferred benchmark mode from artifacts (metadata missing)" in str(warning)
        for warning in warnings
    )


def test_labelstudio_benchmark_compare_payload_infers_benchmark_mode_from_artifacts_and_passes(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        (
            "Running benchmark-only debug checks for thefoodlabcutdown using "
            "inferred benchmark mode from artifacts (metadata missing)"
        ) in str(warning)
        for warning in warnings
    )
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["foodlab_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True


def test_labelstudio_benchmark_compare_payload_skips_debug_checks_when_mode_unknown(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "Could not confirm benchmark mode for seaandsmokecutdown: "
        "mode metadata is missing and artifact signals are not conclusive."
        in str(warning)
        for warning in warnings
    )
    source_row = payload["sources"]["seaandsmokecutdown"]
    assert isinstance(source_row, dict)
    candidate_context = source_row.get("candidate")
    assert isinstance(candidate_context, dict)
    debug_payload = candidate_context.get("debug_artifacts")
    assert isinstance(debug_payload, dict)
    assert debug_payload.get("required") is False
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["sea_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True


def test_labelstudio_benchmark_action_compare_dispatches_to_compare_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    compare_out = tmp_path / "compare-out"
    captured: dict[str, object] = {}

    def fake_compare(**kwargs):
        captured.update(kwargs)
        return {"overall": {"verdict": "PASS"}}

    monkeypatch.setattr(cli, "labelstudio_benchmark_compare", fake_compare)

    cli.labelstudio_benchmark(
        action="compare",
        baseline=baseline,
        candidate=candidate,
        compare_out=compare_out,
        fail_on_regression=True,
    )

    assert captured["baseline"] == baseline
    assert captured["candidate"] == candidate
    assert captured["out_dir"] == compare_out
    assert captured["fail_on_regression"] is True


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
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Sample title",
                    "location": {"features": {"extraction_backend": "unstructured"}},
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
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
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert captured_generate["path"] == source_file
    assert captured_generate["run_manifest_kind"] == "bench_pred_run"
    assert captured_generate["write_markdown"] is False
    assert captured_generate["write_label_studio_tasks"] is False
    run_manifest_path = eval_root / "run_manifest.json"
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["upload"] is False
    assert run_manifest["run_config"]["write_markdown"] is False
    assert run_manifest["run_config"]["write_label_studio_tasks"] is False
    assert "eval_report_md" not in run_manifest["artifacts"]
    assert not (eval_root / "eval_report.md").exists()


def test_labelstudio_benchmark_predictions_out_writes_prediction_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Sample title",
                    "location": {"features": {"extraction_backend": "unstructured"}},
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
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
    assert record.prediction["schema_kind"] == "stage-block.v1"
    assert record.prediction["block_index"] == 0
    assert record.prediction["pred_label"] == "RECIPE_TITLE"
    assert record.prediction["block_text"] == "Sample title"
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
    predictions_in = tmp_path / "prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="labelstudio-benchmark:hash-123:block:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Sample title",
                    "block_features": {"extraction_backend": "unstructured"},
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                    "workbook_slug": "book",
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

    replay_dir = eval_root / ".prediction-record-replay"
    assert captured_eval["stage_predictions_json"] == (
        replay_dir / "stage_block_predictions.from_records.json"
    )
    assert captured_eval["extracted_blocks_json"] == (
        replay_dir / "extracted_archive.from_records.json"
    )
    replay_stage_payload = json.loads(
        (replay_dir / "stage_block_predictions.from_records.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_stage_payload["block_labels"] == {"0": "RECIPE_TITLE"}
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["upload"] is False
    assert "prediction_record_input_jsonl" in run_manifest["artifacts"]


def test_labelstudio_benchmark_predictions_in_supports_legacy_run_pointer_record(
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
                "block_count": 1,
                "block_labels": {"0": "OTHER"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps([{"index": 0, "text": "Sample"}], sort_keys=True),
        encoding="utf-8",
    )

    predictions_in = tmp_path / "legacy-prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="legacy-example-0",
                example_index=0,
                prediction={
                    "pred_run_dir": str(prediction_run),
                    "stage_block_predictions_path": str(stage_predictions_path),
                    "extracted_archive_path": str(extracted_archive_path),
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                    "timing": {"prediction_seconds": 1.0},
                },
            )
        ],
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

    eval_root = tmp_path / "eval-legacy-record"
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


def test_labelstudio_benchmark_legacy_and_pipelined_modes_match_report_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
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


def test_labelstudio_benchmark_predict_only_mode_skips_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
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
            "timing": {"prediction_seconds": 1.25},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("predict-only mode must not run stage-block evaluation.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "evaluate_canonical_text",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("predict-only mode must not run canonical evaluation.")
        ),
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("predict-only mode must not append benchmark CSV.")
        ),
    )

    eval_root = tmp_path / "eval-predict-only"
    predictions_out = tmp_path / "prediction-records.jsonl"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        execution_mode="predict-only",
        predictions_out=predictions_out,
    )

    assert not (eval_root / "eval_report.json").exists()
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["execution_mode"] == "predict-only"
    assert run_manifest["run_config"]["predict_only"] is True
    assert "prediction_record_output_jsonl" in run_manifest["artifacts"]
    records = list(read_prediction_records(predictions_out))
    assert len(records) == 1


def test_labelstudio_benchmark_pipelined_mode_overlaps_prediction_with_eval_prewarm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    canonical_text_path = gold_export_root / "canonical_text.txt"
    canonical_spans_path = gold_export_root / "canonical_span_labels.jsonl"
    canonical_text_path.write_text("Title", encoding="utf-8")
    canonical_spans_path.write_text("{}\n", encoding="utf-8")

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

    prewarm_started = threading.Event()
    producer_observed_prewarm: dict[str, bool] = {"value": False}

    def _fake_generate_pred_run_artifacts(**_kwargs):
        producer_observed_prewarm["value"] = prewarm_started.wait(timeout=1.0)
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 0.4},
        }

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)

    def _fake_ensure_canonical_gold_artifacts(*, export_root: Path):
        assert export_root == gold_export_root
        prewarm_started.set()
        return {
            "canonical_text_path": canonical_text_path,
            "canonical_span_labels_path": canonical_spans_path,
        }

    monkeypatch.setattr(
        cli,
        "ensure_canonical_gold_artifacts",
        _fake_ensure_canonical_gold_artifacts,
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_canonical_text(**kwargs):
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
                "overall_line_accuracy": 0.0,
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
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_evaluate_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-pipelined"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        execution_mode="pipelined",
        eval_mode="canonical-text",
    )

    assert producer_observed_prewarm["value"] is True
    assert isinstance(captured_eval.get("canonical_paths"), dict)


def test_labelstudio_benchmark_pipelined_mode_streams_records_before_producer_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
            "timing": {"prediction_seconds": 0.2},
        },
    )

    consumer_saw_first_record = threading.Event()
    producer_finished = threading.Event()
    original_prediction_record_stage_row = cli._prediction_record_stage_row

    def _wrapped_prediction_record_stage_row(record):
        row = original_prediction_record_stage_row(record)
        if row is not None and int(row[0]) == 0:
            consumer_saw_first_record.set()
        return row

    monkeypatch.setattr(
        cli,
        "_prediction_record_stage_row",
        _wrapped_prediction_record_stage_row,
    )

    def _streaming_predict_stage(*, bundle, selected_source):
        predict_meta = cli._prediction_record_meta_from_bundle(
            bundle=bundle,
            selected_source=selected_source,
            workbook_slug="book",
        )
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:0",
            example_index=0,
            prediction={
                "schema_kind": "stage-block.v1",
                "block_index": 0,
                "pred_label": "RECIPE_TITLE",
                "block_text": "Title",
                "block_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        assert consumer_saw_first_record.wait(timeout=1.0)
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:1",
            example_index=1,
            prediction={
                "schema_kind": "stage-block.v1",
                "block_index": 1,
                "pred_label": "OTHER",
                "block_text": "Body",
                "block_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        producer_finished.set()

    monkeypatch.setattr(cli, "predict_stage", _streaming_predict_stage)

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_stage_blocks(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 2,
                    "pred_total": 2,
                    "gold_matched": 2,
                    "pred_matched": 2,
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
        }

    monkeypatch.setattr(cli, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-pipelined-streaming"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        execution_mode="pipelined",
    )

    assert consumer_saw_first_record.is_set()
    assert producer_finished.is_set()
    replay_dir = eval_root / ".prediction-record-replay" / "pipelined"
    assert captured_eval["stage_predictions_json"] == (
        replay_dir / "stage_block_predictions.from_records.json"
    )
    replay_payload = json.loads(
        (replay_dir / "stage_block_predictions.from_records.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_payload["block_labels"] == {"0": "RECIPE_TITLE", "1": "OTHER"}


def test_labelstudio_benchmark_pipelined_mode_propagates_consumer_stream_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
            "timing": {"prediction_seconds": 0.2},
        },
    )

    def _invalid_streaming_predict_stage(*, bundle, selected_source):
        predict_meta = cli._prediction_record_meta_from_bundle(
            bundle=bundle,
            selected_source=selected_source,
            workbook_slug="book",
        )
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:0",
            example_index=0,
            prediction={
                "schema_kind": "unsupported-kind.v1",
                "block_index": 0,
                "pred_label": "RECIPE_TITLE",
                "block_text": "Title",
                "block_features": {},
            },
            predict_meta=predict_meta,
        )

    monkeypatch.setattr(cli, "predict_stage", _invalid_streaming_predict_stage)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluation should not run when streaming consumer fails.")
        ),
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=tmp_path / "eval-pipelined-error",
            no_upload=True,
            execution_mode="pipelined",
        )


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
        captured_eval["sequence_matcher_env"] = os.environ.get(cli.SEQUENCE_MATCHER_ENV)
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
            sequence_matcher="dmp",
        )

    assert captured_eval["gold_export_root"] == gold_spans.parent
    assert captured_eval["sequence_matcher_env"] == "dmp"
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
    assert run_manifest["run_config"]["sequence_matcher"] == "dmp"


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
        section_detector_backend="shared_v1",
        multi_recipe_splitter="rules_v1",
        multi_recipe_trace=True,
        multi_recipe_min_ingredient_lines=2,
        multi_recipe_min_instruction_lines=2,
        multi_recipe_for_the_guardrail=False,
    )

    assert captured["runtime_epub_extractor"] == "beautifulsoup"
    assert captured["section_detector_backend"] == "shared_v1"
    assert captured["multi_recipe_splitter"] == "rules_v1"
    assert captured["multi_recipe_trace"] is True
    assert captured["multi_recipe_min_ingredient_lines"] == 2
    assert captured["multi_recipe_min_instruction_lines"] == 2
    assert captured["multi_recipe_for_the_guardrail"] is False
    assert os.environ.get("C3IMP_EPUB_EXTRACTOR") == "unstructured"


def test_labelstudio_benchmark_rejects_invalid_epub_extractor() -> None:
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(epub_extractor="invalid")


def test_labelstudio_benchmark_rejects_policy_locked_markdown_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(epub_extractor="markdown")


def test_build_all_method_variants_epub_expected_count() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
    )
    assert len(variants) == 13
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 13
    assert any("extractor_unstructured" in variant.slug for variant in variants)
    assert not any("extractor_markdown" in variant.slug for variant in variants)
    assert not any("extractor_markitdown" in variant.slug for variant in variants)


def test_build_all_method_variants_epub_includes_markdown_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
        include_markdown_extractors=True,
    )
    assert len(variants) == 15
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 15
    assert any("extractor_markdown" in variant.slug for variant in variants)
    assert any("extractor_markitdown" in variant.slug for variant in variants)


def test_build_all_method_variants_non_epub_single_variant() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=False,
    )
    assert len(variants) == 1
    assert variants[0].dimensions["source_extension"] == ".pdf"


def test_build_all_method_variants_include_multi_recipe_dimension_when_non_legacy() -> None:
    base_settings = cli.RunSettings.from_dict(
        {"multi_recipe_splitter": "rules_v1"},
        warn_context="test",
    )
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=False,
    )

    assert len(variants) == 1
    assert variants[0].dimensions["multi_recipe_splitter"] == "rules_v1"
    assert "__multi_recipe_rules_v1" in variants[0].slug


def test_build_all_method_variants_html_webschema_policy_matrix() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("page.html"),
        include_codex_farm=False,
    )

    assert len(variants) == 3
    assert {variant.dimensions["web_schema_policy"] for variant in variants} == {
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    }


def test_build_all_method_variants_non_schema_json_single_variant(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payload.json"
    source.write_text('{"kind":"not-a-recipe"}', encoding="utf-8")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=source,
        include_codex_farm=False,
    )

    assert len(variants) == 1
    assert variants[0].dimensions["source_extension"] == ".json"


def test_build_all_method_variants_schema_json_webschema_policy_matrix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "schema.json"
    source.write_text(
        json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Toast",
                "recipeIngredient": ["1 slice bread"],
                "recipeInstructions": ["Toast bread."],
            }
        ),
        encoding="utf-8",
    )
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=source,
        include_codex_farm=False,
    )

    assert len(variants) == 3
    assert {variant.dimensions["web_schema_policy"] for variant in variants} == {
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    }


def test_resolve_all_method_codex_choice_when_requested() -> None:
    include_effective, warning = cli._resolve_all_method_codex_choice(True)
    assert include_effective is True
    assert warning is None


def test_build_all_method_variants_epub_includes_codex_farm_when_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.ALL_METHOD_CODEX_FARM_UNLOCK_ENV, "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=True,
    )
    assert len(variants) == 26
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 26
    assert any("__llm_recipe_codex_farm_3pass_v1" in variant.slug for variant in variants)


def test_resolve_all_method_markdown_extractors_requires_policy_unlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV, "1")
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    assert cli._resolve_all_method_markdown_extractors_choice() is False

    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    assert cli._resolve_all_method_markdown_extractors_choice() is True


def test_resolve_all_method_scheduler_limits_defaults_raise_split_slots_to_four() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(total_variants=12)
    assert inflight == 4
    assert split_slots == 4


def test_resolve_all_method_source_parallelism_defaults_scale_with_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    resolved = cli._resolve_all_method_source_parallelism(total_sources=7)
    assert resolved == 4


def test_resolve_all_method_source_parallelism_invalid_override_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 8)
    resolved = cli._resolve_all_method_source_parallelism(
        total_sources=5,
        requested=0,
    )
    assert resolved == 2


def test_resolve_all_method_source_parallelism_requested_cap_respects_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 6)
    resolved = cli._resolve_all_method_source_parallelism(
        total_sources=10,
        requested=12,
    )
    assert resolved == 6


def test_resolve_all_method_canonical_alignment_cache_root_uses_shared_benchmark_root(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "golden" / "benchmark-vs-golden"
    run_root = benchmark_root / "2026-02-27_17.54.41" / "all-method-benchmark"
    source_root = run_root / "seaandsmokecutdown"
    expected = benchmark_root / ".cache" / "canonical_alignment"

    assert cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=run_root
    ) == expected
    assert cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=source_root
    ) == expected


def test_resolve_all_method_canonical_alignment_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override_root = tmp_path / "cache-override"
    monkeypatch.setenv(
        cli.ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV,
        str(override_root),
    )

    resolved = cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=tmp_path / "run" / "all-method-benchmark"
    )

    assert resolved == override_root


def test_plan_all_method_source_jobs_tail_pair_interleaves_heavy_and_light(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_names = ["alpha", "beta", "gamma", "delta"]
    targets: list[tuple[cli.AllMethodTarget, list[cli.AllMethodVariant]]] = []
    for name in source_names:
        source_file = tmp_path / f"{name}.epub"
        source_file.write_text("x", encoding="utf-8")
        gold_spans = tmp_path / name / "exports" / "freeform_span_labels.jsonl"
        gold_spans.parent.mkdir(parents=True, exist_ok=True)
        gold_spans.write_text("{}\n", encoding="utf-8")
        targets.append(
            (
                cli.AllMethodTarget(
                    gold_spans_path=gold_spans,
                    source_file=source_file,
                    source_file_name=source_file.name,
                    gold_display=name,
                ),
                [variant],
            )
        )

    estimates = {
        "alpha.epub": 400.0,
        "beta.epub": 300.0,
        "gamma.epub": 200.0,
        "delta.epub": 100.0,
    }

    def fake_estimate(*, target, variants, prior_report_root=None):
        _ = variants
        _ = prior_report_root
        return cli._AllMethodSourceEstimate(
            estimated_seconds=estimates[target.source_file_name],
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=1,
        )

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)

    discovery_plans = cli._plan_all_method_source_jobs(
        target_variants=targets,
        scheduling_strategy="discovery",
        shard_threshold_seconds=99999.0,
        shard_max_parts=1,
        shard_min_variants=2,
    )
    assert [plan.source_file.name for plan in discovery_plans] == [
        "alpha.epub",
        "beta.epub",
        "gamma.epub",
        "delta.epub",
    ]

    tail_pair_plans = cli._plan_all_method_source_jobs(
        target_variants=targets,
        scheduling_strategy="tail_pair",
        shard_threshold_seconds=99999.0,
        shard_max_parts=1,
        shard_min_variants=2,
    )
    assert [plan.source_file.name for plan in tail_pair_plans] == [
        "alpha.epub",
        "delta.epub",
        "beta.epub",
        "gamma.epub",
    ]


def test_plan_all_method_source_jobs_shards_heavy_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = [
        cli.AllMethodVariant(
            slug=f"extractor_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(6)
    ]
    source_file = tmp_path / "heavy.epub"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "heavy" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="heavy",
            ),
            variants,
        )
    ]

    monkeypatch.setattr(
        cli,
        "_estimate_all_method_source_cost",
        lambda **_kwargs: cli._AllMethodSourceEstimate(
            estimated_seconds=3000.0,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=6,
        ),
    )

    shard_plans = cli._plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy="discovery",
        shard_threshold_seconds=1000.0,
        shard_max_parts=3,
        shard_min_variants=2,
    )
    assert len(shard_plans) == 3
    assert [len(plan.variants) for plan in shard_plans] == [2, 2, 2]
    assert all(plan.shard_total == 3 for plan in shard_plans)

    unsharded_plans = cli._plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy="discovery",
        shard_threshold_seconds=5000.0,
        shard_max_parts=3,
        shard_min_variants=2,
    )
    assert len(unsharded_plans) == 1
    assert len(unsharded_plans[0].variants) == 6


def test_plan_all_method_global_work_items_tail_pair_interleaves_sharded_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    heavy_variants = [
        cli.AllMethodVariant(
            slug=f"heavy_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(4)
    ]
    light_variant = cli.AllMethodVariant(
        slug="light_01",
        run_settings=base_settings,
        dimensions={"variant": 1},
    )

    heavy_source = tmp_path / "heavy.epub"
    light_source = tmp_path / "light.docx"
    heavy_source.write_text("x", encoding="utf-8")
    light_source.write_text("x", encoding="utf-8")
    heavy_gold = tmp_path / "gold-heavy" / "exports" / "freeform_span_labels.jsonl"
    light_gold = tmp_path / "gold-light" / "exports" / "freeform_span_labels.jsonl"
    heavy_gold.parent.mkdir(parents=True, exist_ok=True)
    light_gold.parent.mkdir(parents=True, exist_ok=True)
    heavy_gold.write_text("{}\n", encoding="utf-8")
    light_gold.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=heavy_gold,
                source_file=heavy_source,
                source_file_name=heavy_source.name,
                gold_display="heavy",
            ),
            heavy_variants,
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=light_gold,
                source_file=light_source,
                source_file_name=light_source.name,
                gold_display="light",
            ),
            [light_variant],
        ),
    ]

    def fake_estimate(*, target, variants, prior_report_root=None):
        _ = variants
        _ = prior_report_root
        estimated = 3000.0 if target.source_file == heavy_source else 100.0
        return cli._AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=len(variants),
        )

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)

    work_items = cli._plan_all_method_global_work_items(
        target_variants=target_variants,
        scheduling_strategy=cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
        shard_threshold_seconds=1000.0,
        shard_max_parts=2,
        shard_min_variants=2,
        root_output_dir=tmp_path / "run",
        processed_output_root=tmp_path / "processed",
        canonical_alignment_cache_root=tmp_path / "cache",
    )

    assert [item.global_dispatch_index for item in work_items] == [1, 2, 3, 4, 5]
    assert [item.source_file_name for item in work_items] == [
        "heavy.epub",
        "heavy.epub",
        "light.docx",
        "heavy.epub",
        "heavy.epub",
    ]
    heavy_items = [item for item in work_items if item.source_file == heavy_source]
    assert [item.config_index for item in heavy_items] == [1, 2, 3, 4]
    assert all(item.config_total == 4 for item in heavy_items)


def test_run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    heavy_variants = [
        cli.AllMethodVariant(
            slug=f"heavy_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(4)
    ]
    light_variant = cli.AllMethodVariant(
        slug="light_01",
        run_settings=base_settings,
        dimensions={"variant": 1},
    )
    heavy_source = tmp_path / "heavy.epub"
    light_source = tmp_path / "light.docx"
    heavy_source.write_text("x", encoding="utf-8")
    light_source.write_text("x", encoding="utf-8")
    heavy_gold = tmp_path / "gold-heavy" / "exports" / "freeform_span_labels.jsonl"
    light_gold = tmp_path / "gold-light" / "exports" / "freeform_span_labels.jsonl"
    heavy_gold.parent.mkdir(parents=True, exist_ok=True)
    light_gold.parent.mkdir(parents=True, exist_ok=True)
    heavy_gold.write_text("{}\n", encoding="utf-8")
    light_gold.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=heavy_gold,
                source_file=heavy_source,
                source_file_name=heavy_source.name,
                gold_display="heavy",
            ),
            heavy_variants,
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=light_gold,
                source_file=light_source,
                source_file_name=light_source.name,
                gold_display="light",
            ),
            [light_variant],
        ),
    ]

    def fake_estimate(*, target, variants, prior_report_root=None):
        _ = variants
        _ = prior_report_root
        estimated = 3000.0 if target.source_file == heavy_source else 100.0
        return cli._AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=len(variants),
        )

    call_order: list[str] = []

    def fake_prediction_once(**kwargs):
        source_file = kwargs["source_file"]
        variant = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        assert isinstance(source_file, Path)
        assert isinstance(root_output_dir, Path)
        call_order.append(source_file.name)

        config_dir_name = cli._all_method_config_dir_name(config_index, variant)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"global:{source_file.name}:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file.name}:{variant.slug}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file),
                        "source_hash": f"source-{source_file.stem}",
                    },
                )
            ],
        )

        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant.run_settings.stable_hash(),
            "run_config_summary": variant.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant.dimensions),
        }

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)
    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)

    report_md_path = cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=1,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        source_scheduling=cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
        source_shard_threshold_seconds=1000.0,
        source_shard_max_parts=2,
        source_shard_min_variants=2,
        smart_scheduler=False,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["scheduler_scope"] == "global_config_queue"
    assert payload["source_job_count_planned"] == 3
    assert payload["source_schedule_plan"][1]["source_file_name"] == light_source.name
    assert len(call_order) == 5
    assert call_order.index(light_source.name) < 4


def test_run_all_method_benchmark_global_queue_smart_eval_tail_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = [
        cli.AllMethodVariant(
            slug=f"cfg_{index}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in (1, 2, 3)
    ]
    source_file = tmp_path / "book.docx"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="gold",
            ),
            variants,
        )
    ]

    started_at: dict[int, float] = {}
    evaluate_started_at: dict[int, float] = {}
    finished_at: dict[int, float] = {}
    state_lock = threading.Lock()

    def fake_prediction_once(**kwargs):
        source_file_local = kwargs["source_file"]
        variant = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        scheduler_events_dir = kwargs["scheduler_events_dir"]
        assert isinstance(source_file_local, Path)
        assert isinstance(root_output_dir, Path)
        assert isinstance(scheduler_events_dir, Path)

        config_dir_name = cli._all_method_config_dir_name(config_index, variant)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)

        def emit(event_name: str) -> None:
            event_path = scheduler_events_dir / f"config_{config_index:03d}.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "event": event_name,
                            "config_index": config_index,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

        with state_lock:
            started_at[config_index] = time.monotonic()
        emit("config_started")
        emit("split_active_started")
        time.sleep(0.03)
        emit("split_active_finished")
        emit("post_started")
        emit("post_finished")
        emit("evaluate_started")
        with state_lock:
            evaluate_started_at[config_index] = time.monotonic()
        time.sleep(0.35 if config_index == 1 else 0.2)
        emit("evaluate_finished")
        emit("config_finished")
        with state_lock:
            finished_at[config_index] = time.monotonic()

        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"tail:{source_file_local.name}:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file_local.name}:{config_index}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file_local),
                        "source_hash": f"source-{source_file_local.stem}",
                    },
                )
            ],
        )

        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant.run_settings.stable_hash(),
            "run_config_summary": variant.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant.dimensions),
        }

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=1,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        max_eval_tail_pipelines=1,
        source_scheduling=cli.ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
        smart_scheduler=True,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler_summary"]
    assert scheduler["configured_inflight_pipelines"] == 1
    assert scheduler["eval_tail_headroom_effective"] == 1
    assert scheduler["max_active_pipelines_observed"] >= 2
    assert evaluate_started_at[1] <= started_at[2]
    assert started_at[2] < finished_at[1]


def test_run_all_method_benchmark_global_queue_non_epub_eval_uses_default_extractor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant = cli.AllMethodVariant(
        slug="source_docx",
        run_settings=settings,
        dimensions={"source_extension": ".docx"},
    )
    source_file = tmp_path / "book.docx"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="gold",
            ),
            [variant],
        )
    ]

    def fake_prediction_once(**kwargs):
        source_file_local = kwargs["source_file"]
        variant_local = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        config_dir_name = cli._all_method_config_dir_name(config_index, variant_local)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"default-extractor:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file_local.name}:{config_index}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file_local),
                        "source_hash": f"source-{source_file_local.stem}",
                    },
                )
            ],
        )
        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant_local.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant_local.run_settings.stable_hash(),
            "run_config_summary": variant_local.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant_local.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant_local.dimensions),
        }

    captured_epub_extractors: list[str | None] = []

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        captured_epub_extractors.append(kwargs.get("epub_extractor"))
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)

    cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        smart_scheduler=False,
    )

    assert captured_epub_extractors == [None]


def test_resolve_all_method_scheduler_limits_invalid_overrides_fall_back_to_defaults() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(
        total_variants=12,
        max_inflight_pipelines=0,
        max_concurrent_split_phases=0,
    )
    assert inflight == 4
    assert split_slots == 4


def test_resolve_all_method_scheduler_runtime_defaults_and_smart_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_configured == 6
    assert runtime.eval_tail_headroom_effective == 6
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 8
    assert runtime.effective_inflight_pipelines == 8
    assert runtime.cpu_budget_per_source == 8


def test_resolve_all_method_scheduler_runtime_invalid_wing_respects_fixed_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=3,
        max_concurrent_split_phases=2,
        wing_backlog_target=0,
        smart_scheduler=False,
    )
    assert runtime.configured_inflight_pipelines == 3
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 2
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_configured == 5
    assert runtime.eval_tail_headroom_effective == 5
    assert runtime.smart_scheduler_enabled is False
    assert runtime.max_active_during_eval == 3
    assert runtime.effective_inflight_pipelines == 3


def test_resolve_all_method_scheduler_runtime_smart_tail_buffer_clamps_to_total() -> None:
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=4,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        max_eval_tail_pipelines=3,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 3
    assert runtime.eval_tail_headroom_effective == 2
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 4
    assert runtime.effective_inflight_pipelines == 4


def test_resolve_all_method_scheduler_runtime_respects_eval_tail_cap_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        max_eval_tail_pipelines=1,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 1
    assert runtime.eval_tail_headroom_effective == 1
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 3
    assert runtime.effective_inflight_pipelines == 3


def test_resolve_all_method_scheduler_runtime_bounds_explicit_eval_tail_by_cpu_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 5)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        max_eval_tail_pipelines=10,
        smart_scheduler=True,
    )
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 10
    assert runtime.cpu_budget_per_source == 4
    assert runtime.eval_tail_headroom_effective == 4
    assert runtime.max_active_during_eval == 6


def test_resolve_all_method_scheduler_runtime_auto_eval_tail_respects_source_parallelism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=40,
        max_inflight_pipelines=4,
        max_concurrent_split_phases=4,
        smart_scheduler=True,
        source_parallelism_effective=4,
    )
    assert runtime.configured_inflight_pipelines == 4
    assert runtime.split_phase_slots == 4
    assert runtime.wing_backlog_target == 4
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_effective == 0
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 4
    assert runtime.effective_inflight_pipelines == 4


def test_resolve_all_method_scheduler_runtime_caps_split_slots_with_resource_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=40,
        max_inflight_pipelines=8,
        max_concurrent_split_phases=8,
        smart_scheduler=True,
        source_parallelism_effective=4,
    )
    assert runtime.split_phase_slots_requested == 8
    assert runtime.split_phase_slots == 4
    assert runtime.split_phase_slot_mode == "resource_guard"
    assert runtime.split_phase_slot_cap_by_cpu == 4
    assert runtime.split_phase_slot_cap_by_memory >= 1


def test_resolve_all_method_scheduler_admission_pressure_boosts_when_heavy_slots_starve() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 0,
            "split_wait": 0,
            "prep_active": 0,
            "post_active": 0,
            "evaluate_active": 0,
            "wing_backlog": 0,
            "active": 1,
        },
        pending_count=5,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=40.0,
    )
    assert decision.reason == "pressure_boost"
    assert decision.pressure_boost == 0
    assert decision.active_cap == 2
    assert decision.guard_target >= 6


def test_resolve_all_method_scheduler_admission_clamps_when_wing_backlog_is_saturated() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 2,
            "split_wait": 3,
            "prep_active": 2,
            "post_active": 0,
            "evaluate_active": 0,
            "wing_backlog": 5,
            "active": 5,
        },
        pending_count=3,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=35.0,
    )
    assert decision.reason == "saturation_clamp"
    assert decision.saturation_clamp is True
    assert decision.active_cap == 2
    assert decision.guard_target == 4


def test_resolve_all_method_scheduler_admission_clamps_when_cpu_hot() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 1,
            "split_wait": 1,
            "prep_active": 1,
            "post_active": 0,
            "evaluate_active": 1,
            "wing_backlog": 2,
            "active": 3,
        },
        pending_count=2,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=99.0,
    )
    assert decision.reason == "cpu_hot_clamp"
    assert decision.cpu_hot_clamp is True
    assert decision.active_cap == 4


def test_resolve_all_method_split_worker_cap_uses_cpu_and_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 8 * 1024 * 1024 * 1024)

    cap, guard = cli._resolve_all_method_split_worker_cap(
        split_phase_slots=4,
        source_parallelism_effective=1,
    )

    assert cap == 1
    assert guard["split_worker_cap_by_cpu"] == 4
    assert guard["split_worker_cap_by_memory"] == 1
    assert guard["split_worker_cap_per_config"] == 1


def test_all_method_prediction_reuse_summary_detects_safe_and_blocked_split_convert_candidates() -> None:
    rows = [
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-a",
            "prediction_split_convert_input_key": "split-a",
        },
        {
            "status": "ok",
            "prediction_result_source": "reused_in_run",
            "prediction_reuse_key": "pred-a",
            "prediction_split_convert_input_key": "split-a",
        },
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-b1",
            "prediction_split_convert_input_key": "split-b",
        },
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-b2",
            "prediction_split_convert_input_key": "split-b",
        },
        {
            "status": "ok",
            "prediction_result_source": "reused_cross_run",
            "prediction_reuse_key": "pred-c",
            "prediction_split_convert_input_key": "split-c",
        },
    ]

    summary = cli._all_method_prediction_reuse_summary(rows)

    assert summary["prediction_signatures_unique"] == 4
    assert summary["prediction_runs_executed"] == 3
    assert summary["prediction_results_reused_in_run"] == 1
    assert summary["prediction_results_reused_cross_run"] == 1
    assert summary["split_convert_input_groups"] == 3
    assert summary["split_convert_reuse_candidates"] == 2
    assert summary["split_convert_reuse_safe_candidates"] == 1
    assert summary["split_convert_reuse_blocked_by_prediction_variance"] == 1


def test_build_all_method_eval_signature_is_stable_for_same_payload(tmp_path: Path) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    predictions_path = tmp_path / "prediction-records.jsonl"
    write_prediction_records(
        predictions_path,
        [
            make_prediction_record(
                example_id="sig:stable:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title",
                    "block_features": {},
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-1",
                    "workbook_slug": "book",
                },
            )
        ],
    )

    signature_a = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_path,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    signature_b = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_path,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )

    assert signature_a == signature_b


def test_build_all_method_eval_signature_changes_when_inputs_change(tmp_path: Path) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    predictions_a = tmp_path / "prediction-a.jsonl"
    predictions_b = tmp_path / "prediction-b.jsonl"
    write_prediction_records(
        predictions_a,
        [
            make_prediction_record(
                example_id="sig:a:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title A",
                    "block_features": {},
                },
                predict_meta={"source_file": str(source_file), "source_hash": "hash-1"},
            )
        ],
    )
    write_prediction_records(
        predictions_b,
        [
            make_prediction_record(
                example_id="sig:b:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title B",
                    "block_features": {},
                },
                predict_meta={"source_file": str(source_file), "source_hash": "hash-1"},
            )
        ],
    )

    base_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_a,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    changed_prediction_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_b,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    gold_spans.write_text('{"changed":true}\n', encoding="utf-8")
    changed_gold_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_a,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )

    assert base_signature != changed_prediction_signature
    assert base_signature != changed_gold_signature


def test_run_all_method_evaluate_prediction_record_once_preserves_fail_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_error = "Unable to load prediction record from /tmp/preds.jsonl: malformed record"

    def fake_labelstudio_benchmark(**_kwargs):
        cli._fail(expected_error)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    summary = cli._run_all_method_evaluate_prediction_record_once(
        gold_spans_path=tmp_path / "gold.jsonl",
        source_file=tmp_path / "book.epub",
        prediction_record_path=tmp_path / "predictions.jsonl",
        eval_output_dir=tmp_path / "eval",
        processed_output_dir=tmp_path / "processed",
        sequence_matcher="dmp",
        epub_extractor="unstructured",
        overlap_threshold=0.5,
        force_source_match=False,
        alignment_cache_dir=None,
    )

    assert summary["status"] == "failed"
    assert summary["error"] == expected_error
    assert summary["error"] != "1"


def test_run_all_method_benchmark_dedupes_eval_by_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
    extractors = ("unstructured", "beautifulsoup", "markdown")
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
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    signature_seed_by_extractor = {
        "unstructured": "shared",
        "beautifulsoup": "shared",
        "markdown": "unique",
    }
    score_by_extractor = {
        "unstructured": 0.55,
        "beautifulsoup": 0.33,
        "markdown": 0.88,
    }
    eval_calls: list[str] = []

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
                signature_seed=signature_seed_by_extractor[extractor],
            )
            return
        eval_calls.append(extractor)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score_by_extractor[extractor],
            total_seconds=2.0,
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
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["evaluation_signatures_unique"] == 2
    assert payload["evaluation_runs_executed"] == 2
    assert payload["evaluation_results_reused_in_run"] == 1
    assert payload["evaluation_results_reused_cross_run"] == 0
    assert len(eval_calls) == 2

    rows_by_slug = {
        row.get("slug"): row
        for row in payload["variants"]
        if row.get("status") == "ok"
    }
    shared_rep = rows_by_slug["extractor_unstructured"]
    shared_dup = rows_by_slug["extractor_beautifulsoup"]
    assert shared_rep["evaluation_result_source"] == "executed"
    assert shared_dup["evaluation_result_source"] == "reused_in_run"
    assert shared_rep["eval_signature"] == shared_dup["eval_signature"]
    assert shared_rep["evaluation_representative_config_dir"] == shared_rep["config_dir"]
    assert shared_dup["evaluation_representative_config_dir"] == shared_rep["config_dir"]
    assert shared_rep["f1"] == pytest.approx(shared_dup["f1"])


def test_run_all_method_benchmark_reuses_signature_cache_across_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=settings,
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    eval_call_count = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal eval_call_count
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
                signature_seed="shared",
            )
            return
        eval_call_count += 1
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.77,
            total_seconds=1.5,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    shared_alignment_cache_dir = (
        tmp_path / "shared-cache" / "canonical_alignment" / "book_source"
    )

    first_report_md = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-run-1",
        processed_output_root=tmp_path / "processed-1",
        overlap_threshold=0.5,
        force_source_match=False,
        canonical_alignment_cache_dir_override=shared_alignment_cache_dir,
    )
    first_payload = json.loads(first_report_md.with_suffix(".json").read_text(encoding="utf-8"))
    assert first_payload["evaluation_runs_executed"] == 1
    assert first_payload["evaluation_results_reused_cross_run"] == 0

    second_report_md = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-run-2",
        processed_output_root=tmp_path / "processed-2",
        overlap_threshold=0.5,
        force_source_match=False,
        canonical_alignment_cache_dir_override=shared_alignment_cache_dir,
    )
    second_payload = json.loads(second_report_md.with_suffix(".json").read_text(encoding="utf-8"))

    assert eval_call_count == 1
    assert second_payload["evaluation_runs_executed"] == 0
    assert second_payload["evaluation_results_reused_cross_run"] == 1
    second_rows = [
        row
        for row in second_payload["variants"]
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    assert len(second_rows) == 1
    second_row = second_rows[0]
    assert second_row["evaluation_result_source"] == "reused_cross_run"
    assert second_row["evaluation_representative_config_dir"] == second_row["config_dir"]
    cache_root = tmp_path / "shared-cache" / "eval_signature_results" / "book_source"
    assert cache_root.exists()
    assert list(cache_root.glob("*.json"))


def test_run_all_method_benchmark_resource_guard_caps_split_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = cli.RunSettings.from_dict(
        {
            "workers": 10,
            "pdf_split_workers": 10,
            "epub_split_workers": 10,
            "epub_extractor": "unstructured",
        },
        warn_context="test",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=settings,
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    captured_workers: list[tuple[int, int, int]] = []

    def fake_labelstudio_benchmark(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            captured_workers.append(
                (
                    int(kwargs.get("workers") or 0),
                    int(kwargs.get("pdf_split_workers") or 0),
                    int(kwargs.get("epub_split_workers") or 0),
                )
            )
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 5)
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)

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
        max_concurrent_split_phases=2,
        max_inflight_pipelines=2,
        smart_scheduler=False,
    )

    assert captured_workers == [(4, 4, 4)]
    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler"]
    assert scheduler["split_worker_cap_per_config"] == 4
    assert scheduler["split_worker_cap_by_cpu"] == 4
    assert scheduler["split_worker_cap_by_memory"] >= 4


def test_run_all_method_prediction_once_reuses_cached_prediction_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert first_row["prediction_reuse_scope"] == "executed"
    assert second_row["prediction_result_source"] == "reused_in_run"
    assert second_row["prediction_reuse_scope"] == "in_run"
    assert second_row["prediction_representative_config_dir"] == first_row["config_dir"]
    assert second_row["prediction_reuse_key"] == first_row["prediction_reuse_key"]
    assert (
        second_row["prediction_split_convert_input_key"]
        == first_row["prediction_split_convert_input_key"]
    )

    second_timing = cli._normalize_timing_payload(second_row.get("timing"))
    second_checkpoints = second_timing.get("checkpoints")
    assert isinstance(second_checkpoints, dict)
    assert second_checkpoints["all_method_prediction_reused_in_run"] == pytest.approx(1.0)
    assert second_checkpoints["all_method_prediction_reuse_copy_seconds"] >= 0.0

    second_prediction_record = root_output_dir / str(second_row["prediction_record_jsonl"])
    assert second_prediction_record.exists()


def test_run_all_method_prediction_once_reuses_cached_prediction_artifacts_across_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    shared_prediction_reuse_cache = tmp_path / "shared-prediction-reuse-cache"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_root_output_dir = tmp_path / "all-method-a"
    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=first_root_output_dir,
        scratch_root=first_root_output_dir / ".scratch",
        processed_output_root=tmp_path / "processed-output-a",
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        prediction_reuse_cache_dir=shared_prediction_reuse_cache,
        split_worker_cap_per_config=None,
    )
    second_root_output_dir = tmp_path / "all-method-b"
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=second_root_output_dir,
        scratch_root=second_root_output_dir / ".scratch",
        processed_output_root=tmp_path / "processed-output-b",
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        prediction_reuse_cache_dir=shared_prediction_reuse_cache,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "reused_cross_run"
    assert second_row["prediction_reuse_scope"] == "cross_run"
    assert second_row["prediction_representative_config_dir"] == first_row["config_dir"]
    second_prediction_record = second_root_output_dir / str(
        second_row["prediction_record_jsonl"]
    )
    assert second_prediction_record.exists()


def test_run_all_method_prediction_once_reuse_falls_back_when_hardlink_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    def _failing_link(_src: str, _dst: str, *args, **kwargs) -> None:
        raise OSError("simulated hardlink failure")

    monkeypatch.setattr(cli.os, "link", _failing_link)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "reused_in_run"
    second_prediction_record = root_output_dir / str(second_row["prediction_record_jsonl"])
    assert second_prediction_record.exists()


def test_run_all_method_prediction_once_uses_adapter_forwarding_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.html"
    source_file.write_text("<html></html>", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    settings = cli.RunSettings.from_dict(
        {
            "workers": 6,
            "pdf_split_workers": 5,
            "epub_split_workers": 4,
            "multi_recipe_splitter": "rules_v1",
            "multi_recipe_trace": True,
            "multi_recipe_min_ingredient_lines": 3,
            "multi_recipe_min_instruction_lines": 2,
            "multi_recipe_for_the_guardrail": False,
            "web_schema_extractor": "extruct",
            "web_schema_normalizer": "pyld",
            "web_html_text_extractor": "trafilatura",
            "web_schema_policy": "schema_only",
            "web_schema_min_confidence": 0.82,
            "web_schema_min_ingredients": 4,
            "web_schema_min_instruction_steps": 3,
            "ingredient_text_fix_backend": "ftfy",
            "ingredient_pre_normalize_mode": "aggressive_v1",
            "ingredient_packaging_mode": "regex_v1",
            "ingredient_parser_backend": "hybrid_nlp_then_quantulum3",
            "ingredient_unit_canonicalizer": "pint",
            "ingredient_missing_unit_policy": "each",
            "p6_time_backend": "quantulum3_v1",
            "p6_time_total_strategy": "selective_sum_v1",
            "p6_temperature_backend": "hybrid_regex_quantulum3_v1",
            "p6_temperature_unit_backend": "pint_v1",
            "p6_ovenlike_mode": "off",
            "p6_yield_mode": "scored_v1",
            "p6_emit_metadata_debug": True,
            "recipe_scorer_backend": "heuristic_v1",
            "recipe_score_gold_min": 0.8,
            "recipe_score_silver_min": 0.6,
            "recipe_score_bronze_min": 0.4,
            "recipe_score_min_ingredient_lines": 2,
            "recipe_score_min_instruction_lines": 2,
        },
        warn_context="test",
    )
    variant = cli.AllMethodVariant(
        slug="forwarding-check",
        run_settings=settings,
        dimensions={"source_extension": "html"},
    )

    captured_kwargs: dict[str, object] = {}

    def fake_labelstudio_benchmark(**kwargs):
        captured_kwargs.update(kwargs)
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor=str(kwargs.get("epub_extractor") or "unstructured"),
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert row["status"] == "ok"
    config_dir_name = cli._all_method_config_dir_name(1, variant)
    expected_kwargs = cli.build_benchmark_call_kwargs_from_run_settings(
        settings,
        output_dir=scratch_root / config_dir_name,
        processed_output_dir=processed_output_root / config_dir_name,
        eval_output_dir=root_output_dir / config_dir_name,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        execution_mode=cli.BENCHMARK_EXECUTION_MODE_PREDICT_ONLY,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
        sequence_matcher_override=settings.benchmark_sequence_matcher,
    )
    expected_kwargs.update(
        {
            "gold_spans": gold_spans,
            "source_file": source_file,
            "predictions_out": root_output_dir / config_dir_name / "prediction-records.jsonl",
            "overlap_threshold": 0.5,
            "force_source_match": False,
            "alignment_cache_dir": None,
        }
    )

    for key, value in expected_kwargs.items():
        assert key in captured_kwargs
        assert captured_kwargs[key] == value


def test_run_all_method_benchmark_writes_ranked_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
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
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        processed_output_dir = kwargs["processed_output_dir"]
        assert isinstance(processed_output_dir, Path)
        captured_processed_dirs.append(processed_output_dir)
        alignment_cache_dir = kwargs["alignment_cache_dir"]
        assert isinstance(alignment_cache_dir, Path)
        captured_alignment_cache_dirs.append(alignment_cache_dir)
        extractor = str(kwargs.get("epub_extractor") or "")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor or "unstructured",
            )
            return
        f1 = 0.82 if extractor == "markdown" else 0.40
        total_seconds = 8.0 if extractor == "markdown" else 5.0
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=f1,
            total_seconds=total_seconds,
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
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
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
            extractor = str(kwargs.get("epub_extractor") or "")
            eval_output_dir = kwargs["eval_output_dir"]
            assert isinstance(eval_output_dir, Path)
            if str(kwargs.get("execution_mode") or "") == "predict-only":
                assert cli._BENCHMARK_SPLIT_PHASE_SLOTS.get() == 2
                assert cli._BENCHMARK_SPLIT_PHASE_GATE_DIR.get()
                time.sleep(delays[extractor])
                _write_fake_all_method_prediction_phase_artifacts(
                    kwargs=kwargs,
                    source_file=source_file,
                    extractor=extractor,
                )
                return
            f1 = scores[extractor]
            _write_fake_all_method_eval_artifacts(
                eval_output_dir=eval_output_dir,
                score=f1,
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
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            if extractor == "unstructured":
                time.sleep(1.35)
            else:
                time.sleep(0.02)
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        score = 0.9 if extractor == "markdown" else 0.2
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
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
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            call_counts[extractor] = call_counts.get(extractor, 0) + 1
        if (
            str(kwargs.get("execution_mode") or "") == "predict-only"
            and extractor == "beautifulsoup"
            and call_counts[extractor] == 1
        ):
            raise RuntimeError("synthetic transient failure")

        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        score = {
            "unstructured": 0.5,
            "beautifulsoup": 0.75,
            "markdown": 0.9,
        }[extractor]
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
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
    base_payload = base_settings.to_run_config_dict()
    variants = [
        cli.AllMethodVariant(
            slug=f"config_{index:02d}",
            run_settings=cli.RunSettings.from_dict(
                {
                    **base_payload,
                    # Keep scheduler test focused on admission/slot behavior by
                    # forcing unique prediction signatures per config.
                    "ocr_batch_size": index,
                },
                warn_context="test",
            ),
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
        "evaluate": 0.22,
    }
    split_gate = threading.Semaphore(2)

    def fake_labelstudio_benchmark(**kwargs):
        callback = cli._BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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
                callback({"event": "evaluate_started"})
                time.sleep(phase_profile["evaluate"])
                callback({"event": "evaluate_finished"})
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        config_parts = eval_output_dir.name.split("_", 2)
        config_index = int(config_parts[1]) if len(config_parts) > 1 else 0
        score = 0.5 + (config_index * 0.01)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
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
        fixed_scheduler["heavy_slot_utilization_pct"] + 8.0
    )
    assert smart_scheduler["max_active_pipelines_observed"] <= smart_scheduler[
        "effective_inflight_pipelines"
    ]
    assert smart_scheduler["eval_tail_headroom_mode"] == "auto"
    assert smart_scheduler["eval_tail_headroom_effective"] >= 1
    assert smart_scheduler["max_active_during_eval"] == smart_scheduler[
        "effective_inflight_pipelines"
    ]
    assert smart_scheduler["max_active_pipelines_observed"] >= 3
    assert smart_scheduler["max_eval_active_observed"] >= 1


def test_run_all_method_benchmark_writes_scheduler_timeseries(
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
        for index in range(1, 3)
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    def fake_labelstudio_benchmark(**kwargs):
        callback = cli._BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            if callback is not None:
                callback({"event": "prep_started"})
                time.sleep(0.03)
                callback({"event": "split_wait_started"})
                time.sleep(0.03)
                callback({"event": "split_wait_finished"})
                callback({"event": "split_active_started"})
                time.sleep(0.03)
                callback({"event": "split_active_finished"})
                callback({"event": "post_started"})
                time.sleep(0.03)
                callback({"event": "post_finished"})
                callback({"event": "evaluate_started"})
                time.sleep(0.03)
                callback({"event": "evaluate_finished"})
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
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
        smart_scheduler=True,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler"]
    timeseries_path = Path(str(scheduler["timeseries_path"]))
    assert timeseries_path.exists()
    assert timeseries_path.name == cli.ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    assert scheduler["snapshot_poll_seconds"] == cli.ALL_METHOD_SCHEDULER_POLL_SECONDS
    assert scheduler["timeseries_heartbeat_seconds"] >= cli.ALL_METHOD_SCHEDULER_POLL_SECONDS

    rows = [
        json.loads(line)
        for line in timeseries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    assert scheduler["timeseries_row_count"] == len(rows)
    assert any(int(row.get("active", 0)) == 0 and int(row.get("pending", 0)) == 0 for row in rows)
    first = rows[0]
    assert "snapshot" in first
    assert "cpu_utilization_pct" in first
    assert "heavy_active" in first
    assert "heavy_capacity" in first
    assert "wing_backlog" in first
    assert "evaluate_active" in first
    assert "active" in first
    assert "pending" in first
    assert "admission_active_cap" in first
    assert "admission_guard_target" in first
    assert "admission_wing_target" in first
    assert "admission_reason" in first
    assert "elapsed_seconds" in first
    assert scheduler["adaptive_admission_adjustments"] >= 0
    assert scheduler["split_phase_slots_requested"] >= scheduler["split_phase_slots"]


def test_run_all_method_benchmark_falls_back_to_thread_executor_when_process_workers_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
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
        extractor = str(kwargs.get("epub_extractor") or "")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            call_count += 1
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
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
    assert any(
        "using thread-based config concurrency" in message.lower()
        for message in messages
    )


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
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
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
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
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
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
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
            assert kwargs["source_parallelism_effective"] == 2
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
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["source_parallelism_configured"] == 2
    assert payload["source_parallelism_effective"] == 2
    assert payload["source_schedule_strategy"] == cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR
    assert payload["source_job_count_planned"] == 3
    assert len(payload["source_schedule_plan"]) == 3
    assert max_active_sources <= 2
    assert max_active_sources >= 2
    assert [row["source_file_name"] for row in payload["sources"]] == [
        source_a.name,
        source_b.name,
        source_c.name,
    ]
    assert all(row["source_shard_total"] == 1 for row in payload["sources"])


def test_run_all_method_benchmark_multi_source_shards_source_and_reuses_cache_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = [
        cli.AllMethodVariant(
            slug=f"extractor_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(6)
    ]
    source = tmp_path / "heavy-source.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold-heavy" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold-heavy",
            ),
            variants,
        )
    ]

    monkeypatch.setattr(
        cli,
        "_estimate_all_method_source_cost",
        lambda **_kwargs: cli._AllMethodSourceEstimate(
            estimated_seconds=3600.0,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=6,
        ),
    )

    cache_overrides: list[Path] = []

    def fake_run_all_method_benchmark(**kwargs):
        cache_override = kwargs["canonical_alignment_cache_dir_override"]
        assert isinstance(cache_override, Path)
        cache_overrides.append(cache_override)
        shard_variants = kwargs["variants"]
        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        variant_count = len(shard_variants)
        f1 = 0.5 + (variant_count * 0.05)
        report_payload = {
            "successful_variants": variant_count,
            "failed_variants": 0,
            "winner_by_f1": {"precision": f1, "recall": f1, "f1": f1},
            "timing_summary": {
                "source_wall_seconds": float(variant_count),
                "config_total_seconds": float(variant_count),
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": float(variant_count),
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

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        source_scheduling="discovery",
        source_shard_threshold_seconds=1000.0,
        source_shard_max_parts=3,
        source_shard_min_variants=2,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    assert len(cache_overrides) == 3
    assert len({path.as_posix() for path in cache_overrides}) == 1
    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["source_job_count_planned"] == 3
    assert payload["source_schedule_strategy"] == "discovery"
    assert len(payload["sources"]) == 1
    source_row = payload["sources"][0]
    assert source_row["status"] == "ok"
    assert source_row["source_shard_total"] == 3
    assert source_row["variant_count_planned"] == 6
    assert source_row["variant_count_successful"] == 6
    assert len(source_row["source_shards"]) == 3


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
        assert kwargs["source_parallelism_effective"] == 2
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
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    assert per_source_refresh_values == [False, False]
    assert len(batch_refresh_calls) == 1


def test_run_all_method_benchmark_multi_source_defaults_to_global_scheduler_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
            [
                cli.AllMethodVariant(
                    slug="extractor_unstructured",
                    run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
                    dimensions={"epub_extractor": "unstructured"},
                )
            ],
        )
    ]

    expected_report_path = tmp_path / "global.md"
    captured: dict[str, object] = {}

    def fake_global_queue(**kwargs):
        captured.update(kwargs)
        return expected_report_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_global_queue", fake_global_queue)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark_multi_source_legacy",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Default scheduler scope should dispatch to global queue.")
        ),
    )

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
    )

    assert report_md_path == expected_report_path
    assert captured["target_variants"] == target_variants


def test_run_all_method_benchmark_multi_source_dispatches_legacy_scheduler_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
            [
                cli.AllMethodVariant(
                    slug="extractor_unstructured",
                    run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
                    dimensions={"epub_extractor": "unstructured"},
                )
            ],
        )
    ]

    expected_report_path = tmp_path / "legacy.md"
    captured: dict[str, object] = {}

    def fake_legacy(**kwargs):
        captured.update(kwargs)
        return expected_report_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_multi_source_legacy", fake_legacy)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark_global_queue",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Legacy scheduler scope should not dispatch to global queue.")
        ),
    )

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    assert report_md_path == expected_report_path
    assert captured["target_variants"] == target_variants


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

    confirm_answers = iter([False, False, True])
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
    confirm_answers = iter([False, False, True])
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
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
            "instruction_step_segmentation_policy": "off",
        },
        warn_context="test all-method chooser",
    )
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: chosen_settings,
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
    assert (
        captured["selected_benchmark_settings"].to_run_config_dict()
        == chosen_settings.to_run_config_dict()
    )
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT


def test_interactive_benchmark_single_profile_all_matched_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "single_offline_all_matched", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
            "instruction_step_segmentation_policy": "off",
        },
        warn_context="test single-profile chooser",
    )
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: chosen_settings,
    )
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not resolve Label Studio credentials."
            )
        ),
    )
    monkeypatch.setattr(
        cli,
        "_interactive_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not route to all-method runner."
            )
        ),
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "_interactive_single_profile_all_matched_benchmark",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    saved_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli,
        "save_last_run_settings",
        lambda *args, **_kwargs: saved_calls.append(args),
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert isinstance(captured.get("selected_benchmark_settings"), cli.RunSettings)
    assert (
        captured["selected_benchmark_settings"].to_run_config_dict()
        == chosen_settings.to_run_config_dict()
    )
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT
    assert captured["write_markdown"] is True
    assert captured["write_label_studio_tasks"] is False
    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "benchmark"


def test_interactive_single_profile_all_matched_benchmark_runs_each_target_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-02-28_03.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict({}, warn_context="test")

    benchmark_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert benchmark_calls[0]["gold_spans"] == gold_a
    assert benchmark_calls[0]["source_file"] == source_a
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert benchmark_calls[0]["execution_mode"] == cli.BENCHMARK_EXECUTION_MODE_LEGACY
    assert benchmark_calls[0]["no_upload"] is True
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / "01_book_a"
    )
    assert benchmark_calls[1]["gold_spans"] == gold_b
    assert benchmark_calls[1]["source_file"] == source_b
    assert benchmark_calls[1]["eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "02_book_b"
    )


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
        lambda **_kwargs: cli.RunSettings.from_dict(
            {
                "epub_extractor": "beautifulsoup",
                "instruction_step_segmentation_policy": "off",
            },
            warn_context="test all-method chooser",
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
