from __future__ import annotations

import builtins
import csv
import datetime as dt
import inspect
import json
import os
import re
import threading
import time
from collections import deque
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


def test_recent_rate_average_seconds_per_task_uses_weighted_last_five_steps() -> None:
    samples: deque[tuple[float, int]] = deque(
        [
            (8.0, 2),  # older: 4s/task, 4s/task
            (6.0, 1),  # older: 6s/task
            (9.0, 3),  # newest: 3s/task x3
        ]
    )
    # Most recent five steps: 3,3,3,6,4 with weights 30/20/20/20/10.
    expected = (3.0 * 0.30 + 3.0 * 0.20 + 3.0 * 0.20 + 6.0 * 0.20 + 4.0 * 0.10) / 1.0
    assert cli._recent_rate_average_seconds_per_task(samples) == pytest.approx(expected)


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


def test_run_with_progress_status_bootstraps_eta_when_first_counter_starts_above_one(
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
        update_progress("Benchmark import task 2/4")
        time.sleep(1.2)
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
    assert any("Benchmark: Benchmark import task 2/4 (eta " in message for message in capture.messages)


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


def test_run_with_progress_status_clamps_live_box_width_to_terminal(
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
        width = 72

        def __init__(self) -> None:
            self.messages: list[str] = []

        def status(
            self,
            message: str,
            spinner: str = "dots",
            **_kwargs: object,
        ) -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureConsole()
    monkeypatch.setattr(cli, "console", capture)

    long_task = (
        "r0011_urn_recipeimport_epub_"
        "3d419982b11ed7c2503ba73deac8b6964c077c685dbd9ac199387b6a5504ed58_c11.json"
    )

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.final.v1 task 4/19 | running 8 | "
            f"active [{long_task}]"
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Benchmark import running...",
        progress_prefix="Benchmark import (SeaAndSmokeCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    borders = [
        border
        for message in capture.messages
        for border in re.findall(r"\+[+-]+\+", message)
    ]
    assert borders
    assert max(len(border) for border in borders) <= capture.width - 2


def test_run_with_progress_status_preserves_eta_when_live_line_is_truncated(
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
        width = 72

        def __init__(self) -> None:
            self.messages: list[str] = []

        def status(
            self,
            message: str,
            spinner: str = "dots",
            **_kwargs: object,
        ) -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureConsole()
    monkeypatch.setattr(cli, "console", capture)

    long_task = (
        "r0017_urn_recipeimport_epub_"
        "3d419982b11ed7c2503ba73deac8b6964c077c685dbd9ac199387b6a5504ed58_c11.json"
    )

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.final.v1 task 1/4 | running 3 | "
            f"active [{long_task}]"
        )
        time.sleep(0.8)
        update_progress(
            "codex-farm recipe.final.v1 task 2/4 | running 3 | "
            f"active [{long_task}]"
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Benchmark import running...",
        progress_prefix="Benchmark import (SeaAndSmokeCUTDOWN.epub)",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any(
        "Benchmark import" in message and "(eta " in message and "avg " in message
        for message in capture.messages
    )


def test_run_with_progress_status_humanizes_codex_stage_in_live_panel(
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
        width = 86

        def __init__(self) -> None:
            self.messages: list[str] = []

        def status(
            self,
            message: str,
            spinner: str = "dots",
            **_kwargs: object,
        ) -> _FakeStatus:
            self.messages.append(message)
            return _FakeStatus(self.messages)

    capture = _CaptureConsole()
    monkeypatch.setattr(cli, "console", capture)

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.schemaorg.v1 task 2/9 | running 2 | "
            "active [r0002.json, r0007.json]"
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Benchmark import running...",
        progress_prefix="Benchmark import (SeaAndSmokeCUTDOWN.epub)",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any("stage: pass2 schemaorg" in message for message in capture.messages)
    assert any(
        "codex-farm pass2 schemaorg" in message and "task" in message
        for message in capture.messages
    )
    assert any("active tasks (2/2, 7 left)" in message for message in capture.messages)


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
    assert captured["codex_farm_pass3_skip_pass2_ok"] is True


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
                "llm_codex_farm": {
                    "process_runs": {
                        "pass1": {
                            "process_payload": {
                                "telemetry": {
                                    "rows": [
                                        {
                                            "tokens_input": 11,
                                            "tokens_cached_input": 2,
                                            "tokens_output": 3,
                                            "tokens_reasoning": 1,
                                            "tokens_total": 14,
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
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
    assert captured_csv["tokens_input"] == 11
    assert captured_csv["tokens_cached_input"] == 2
    assert captured_csv["tokens_output"] == 3
    assert captured_csv["tokens_reasoning"] == 1
    assert captured_csv["tokens_total"] == 14
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "pass1_chunking" / "in"
    pass1_out = run_dir / "pass1_chunking" / "out"
    pass2_in = run_dir / "pass2_schemaorg" / "in"
    pass2_out = run_dir / "pass2_schemaorg" / "out"
    pass3_in = run_dir / "pass3_final" / "in"
    pass3_out = run_dir / "pass3_final" / "out"
    pass4_in = run_dir / "pass4_knowledge" / "in"
    pass4_out = run_dir / "pass4_knowledge" / "out"
    pass5_in = run_dir / "pass5_tags" / "in"
    pass5_out = run_dir / "pass5_tags" / "out"
    for folder in (
        pass1_in,
        pass1_out,
        pass2_in,
        pass2_out,
        pass3_in,
        pass3_out,
        pass4_in,
        pass4_out,
        pass5_in,
        pass5_out,
    ):
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
    (pass4_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass4 prompt"}),
        encoding="utf-8",
    )
    (pass4_out / "r0000.json").write_text(
        json.dumps({"result": "pass4 response"}),
        encoding="utf-8",
    )
    (pass5_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass5 prompt"}),
        encoding="utf-8",
    )
    (pass5_out / "r0000.json").write_text(
        json.dumps({"result": "pass5 response"}),
        encoding="utf-8",
    )

    telemetry_csv = tmp_path / "var" / "codex_exec_activity.csv"
    telemetry_csv.parent.mkdir(parents=True, exist_ok=True)
    with telemetry_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "input_path",
                "prompt_text",
                "model",
                "reasoning_effort",
                "sandbox",
                "ask_for_approval",
                "web_search",
                "output_schema_path",
                "task_id",
                "worker_id",
                "status",
                "duration_ms",
                "attempt_index",
                "execution_attempt_index",
                "lease_claim_index",
                "prompt_chars",
                "prompt_sha256",
                "output_bytes",
                "output_sha256",
                "output_payload_present",
                "output_preview_chars",
                "output_preview_truncated",
                "output_preview",
                "tokens_input",
                "tokens_cached_input",
                "tokens_output",
                "tokens_reasoning",
                "tokens_total",
                "usage_json",
                "finished_at_utc",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "run-pass1",
                "input_path": str(pass1_in / "r0000.json"),
                "prompt_text": "Telemetry prompt body",
                "model": "gpt-5-test",
                "reasoning_effort": "high",
                "sandbox": "workspace-write",
                "ask_for_approval": "true",
                "web_search": "false",
                "output_schema_path": "/tmp/schema-pass1.json",
                "task_id": "task-pass1",
                "worker_id": "worker-pass1",
                "status": "ok",
                "duration_ms": "321",
                "attempt_index": "1",
                "execution_attempt_index": "1",
                "lease_claim_index": "1",
                "prompt_chars": "20",
                "prompt_sha256": "sha-prompt",
                "output_bytes": "21",
                "output_sha256": "sha-output",
                "output_payload_present": "true",
                "output_preview_chars": "21",
                "output_preview_truncated": "false",
                "output_preview": "response-preview",
                "tokens_input": "111",
                "tokens_cached_input": "11",
                "tokens_output": "22",
                "tokens_reasoning": "5",
                "tokens_total": "133",
                "usage_json": "{\"tokens\":123}",
                "finished_at_utc": "2026-03-02T23:59:00Z",
            }
        )

    (run_dir / "llm_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-farm-3pass-v1",
                "codex_farm_model": "manifest-model",
                "codex_farm_reasoning_effort": "medium",
                "process_runs": {
                    "pass1": {
                        "run_id": "run-pass1",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                    "pass2": {
                        "run_id": "run-pass2",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                    "pass3": {
                        "run_id": "run-pass3",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                },
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
    (run_dir / "pass4_knowledge_manifest.json").write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.knowledge.v1",
                "paths": {
                    "pass4_in_dir": str(pass4_in),
                    "pass4_out_dir": str(pass4_out),
                },
                "process_run": {
                    "run_id": "run-pass4",
                    "telemetry": {"csv_path": str(telemetry_csv)},
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "pass5_tags_manifest.json").write_text(
        json.dumps(
            {
                "llm_report": {
                    "pipeline_id": "recipe.tags.v1",
                    "paths": {"in_dir": str(pass5_in), "out_dir": str(pass5_out)},
                    "process_run": {
                        "run_id": "run-pass5",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
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

    assert log_path == eval_output_dir / "codexfarm" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT pass1 => r0000.json" in combined
    assert "OUTPUT pass3 => r0000.json" in combined

    task1_path = eval_output_dir / "codexfarm" / "prompt_task1_pass1_chunking.txt"
    task2_path = eval_output_dir / "codexfarm" / "prompt_task2_pass2_schemaorg.txt"
    task3_path = eval_output_dir / "codexfarm" / "prompt_task3_pass3_final.txt"
    task4_path = eval_output_dir / "codexfarm" / "prompt_task4_pass4_knowledge.txt"
    task5_path = eval_output_dir / "codexfarm" / "prompt_task5_pass5_tags.txt"
    for category_path in (task1_path, task2_path, task3_path, task4_path, task5_path):
        assert category_path.exists()

    task1_text = task1_path.read_text(encoding="utf-8")
    assert "ATTACHMENT task1 =>" in task1_text
    assert str(attached) in task1_text
    assert "attachment content" in task1_text

    manifest_path = eval_output_dir / "codexfarm" / "prompt_category_logs_manifest.txt"
    assert manifest_path.exists()
    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [
        str(task1_path),
        str(task2_path),
        str(task3_path),
        str(task4_path),
        str(task5_path),
    ]

    full_prompt_log_path = eval_output_dir / "codexfarm" / "full_prompt_log.jsonl"
    assert full_prompt_log_path.exists()
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 5
    assert {str(row.get("pass") or "") for row in full_prompt_rows} == {
        "pass1",
        "pass2",
        "pass3",
        "pass4",
        "pass5",
    }
    pass1_row = next(row for row in full_prompt_rows if row.get("pass") == "pass1")
    assert pass1_row["call_id"] == "r0000"
    assert pass1_row["request_messages"][0]["role"] == "user"
    assert pass1_row["request_payload_source"] == "telemetry_csv"
    assert pass1_row["request_messages"][0]["content"] == "Telemetry prompt body"
    assert pass1_row["request"]["model"] == "gpt-5-test"
    assert pass1_row["request"]["reasoning_effort"] == "high"
    assert pass1_row["request"]["sandbox"] == "workspace-write"
    assert pass1_row["request"]["ask_for_approval"] is True
    assert pass1_row["request"]["web_search"] is False
    assert pass1_row["request"]["output_schema_path"] == "/tmp/schema-pass1.json"
    assert pass1_row["timestamp_utc"] == "2026-03-02T23:59:00Z"
    assert pass1_row["request_telemetry"]["task_id"] == "task-pass1"
    assert pass1_row["request_telemetry"]["prompt_chars"] == 20
    assert pass1_row["request_telemetry"]["tokens_total"] == 133
    assert pass1_row["request_telemetry"]["usage_json"] == {"tokens": 123}
    assert pass1_row["parsed_response"] == {"result": "pass1 response"}
    assert pass1_row["raw_response"]["output_file"].endswith("r0000.json")

    prompt_samples_path = (
        eval_output_dir
        / "codexfarm"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## pass1 (Chunking)" in prompt_samples
    assert "## pass2 (Schema.org Extraction)" in prompt_samples
    assert "## pass3 (Final Draft)" in prompt_samples
    assert "## pass4 (Knowledge Harvest)" in prompt_samples
    assert "## pass5 (Tag Suggestions)" in prompt_samples
    assert "call_id: `r0000`" in prompt_samples
    assert "Telemetry prompt body" in prompt_samples


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
    assert not (eval_output_dir / "codexfarm" / "prompt_task4_pass4_knowledge.txt").exists()
    assert not (eval_output_dir / "codexfarm" / "prompt_task5_pass5_tags.txt").exists()
    full_prompt_log_path = eval_output_dir / "codexfarm" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["pass"] == "pass1"
    prompt_samples_path = (
        eval_output_dir
        / "codexfarm"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## pass1 (Chunking)" in prompt_samples
    assert "## pass2 (Schema.org Extraction)" in prompt_samples
    assert "## pass4 (Knowledge Harvest)" in prompt_samples
    assert "## pass5 (Tag Suggestions)" in prompt_samples
    assert "_No rows captured for this pass._" in prompt_samples


def test_write_stage_run_manifest_includes_codexfarm_artifacts(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = tmp_path / "output"
    run_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    requested_path = tmp_path / "source.txt"
    requested_path.write_text("hello\n", encoding="utf-8")
    (run_root / "source.excel_import_report.json").write_text(
        json.dumps({"importerName": "text"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    codexfarm_dir = run_root / "codexfarm"
    codexfarm_dir.mkdir(parents=True, exist_ok=True)
    (codexfarm_dir / "prompt_request_response_log.txt").write_text(
        "prompt log\n",
        encoding="utf-8",
    )
    (codexfarm_dir / "prompt_category_logs_manifest.txt").write_text(
        "prompt_task1_pass1_chunking.txt\n",
        encoding="utf-8",
    )
    (codexfarm_dir / "full_prompt_log.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (codexfarm_dir / "prompt_type_samples_from_full_prompt_log.md").write_text(
        "# samples\n",
        encoding="utf-8",
    )

    cli._write_stage_run_manifest(
        run_root=run_root,
        output_root=output_root,
        requested_path=requested_path,
        run_dt=dt.datetime(2026, 3, 3, 12, 0, 0),
        run_config={"llm_recipe_pipeline": "codex-farm-3pass-v1"},
    )

    run_manifest_payload = json.loads(
        (run_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    artifacts = run_manifest_payload.get("artifacts")
    assert isinstance(artifacts, dict)
    assert artifacts["codexfarm_dir"] == "codexfarm"
    assert artifacts["codexfarm_prompt_request_response_txt"] == (
        "codexfarm/prompt_request_response_log.txt"
    )
    assert artifacts["codexfarm_prompt_category_logs_manifest_txt"] == (
        "codexfarm/prompt_category_logs_manifest.txt"
    )
    assert artifacts["codexfarm_full_prompt_log_jsonl"] == (
        "codexfarm/full_prompt_log.jsonl"
    )
    assert artifacts["codexfarm_prompt_type_samples_from_full_prompt_log_md"] == (
        "codexfarm/prompt_type_samples_from_full_prompt_log.md"
    )


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
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )
    menu_answers = iter(["labelstudio_benchmark", "single_offline", "exit"])
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
        lambda **_kwargs: selected_benchmark_settings,
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
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )
    menu_answers = iter(["labelstudio_benchmark", "single_offline", "exit"])

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
        lambda **_kwargs: selected_benchmark_settings,
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

    menu_answers = iter(["labelstudio_benchmark", "single_offline", "exit"])
    mode_prompt_count = 0
    mode_titles: list[str] = []
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )

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
        lambda **_kwargs: selected_benchmark_settings,
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
    refresh_calls: list[dict[str, object]] = []

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
    monkeypatch.setattr(
        cli,
        "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(kwargs),
    )

    monkeypatch.setattr(
        cli,
        "_write_single_offline_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run by default for single-offline")
        ),
    )

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
    assert [call["line_role_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-line-role-v1",
    ]
    assert [call["atomic_block_splitter"] for call in benchmark_calls] == [
        "off",
        "atomic-v1",
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
    assert "starter_pack_v1" not in payload["metadata"]
    assert len(refresh_calls) == 1
    assert refresh_calls[0]["reason"] == "single-offline benchmark variant batch append"
    assert refresh_calls[0]["csv_path"] == cli.history_csv_for_output(
        processed_output_root
        / benchmark_eval_output.name
        / "single-offline-benchmark"
        / cli._DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    assert refresh_calls[0]["output_root"] == processed_output_root
    assert (
        refresh_calls[0]["dashboard_out_dir"]
        == cli.history_root_for_output(processed_output_root) / "dashboard"
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
    refresh_calls: list[dict[str, object]] = []

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
    monkeypatch.setattr(
        cli,
        "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(kwargs),
    )
    monkeypatch.setattr(
        cli,
        "_write_single_offline_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run for vanilla-only single-offline")
        ),
    )

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
    assert len(refresh_calls) == 1
    assert refresh_calls[0]["reason"] == "single-offline benchmark variant batch append"
    assert refresh_calls[0]["csv_path"] == cli.history_csv_for_output(
        processed_output_root
        / benchmark_eval_output.name
        / "single-offline-benchmark"
        / cli._DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    assert refresh_calls[0]["output_root"] == processed_output_root
    assert (
        refresh_calls[0]["dashboard_out_dir"]
        == cli.history_root_for_output(processed_output_root) / "dashboard"
    )


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


def test_single_offline_comparison_artifacts_trigger_starter_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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

    starter_calls: list[Path] = []

    def _fake_starter_pack_writer(*, session_root: Path) -> Path:
        starter_calls.append(session_root)
        starter_dir = session_root / "starter_pack_v1"
        starter_dir.mkdir(parents=True, exist_ok=True)
        (session_root / "benchmark_summary.md").write_text(
            "# Flattened benchmark summary\n",
            encoding="utf-8",
        )
        return starter_dir

    monkeypatch.setattr(cli, "_write_single_offline_starter_pack", _fake_starter_pack_writer)

    comparison_paths = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=False,
        write_starter_pack=True,
    )

    assert comparison_paths is not None
    comparison_json_path, _ = comparison_paths
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    starter_metadata = metadata.get("starter_pack_v1")
    assert isinstance(starter_metadata, dict)
    assert starter_metadata.get("relative_path") == "starter_pack_v1"
    assert starter_metadata.get("manifest_file") == "starter_pack_v1/10_process_manifest.json"
    flattened_metadata = metadata.get("flattened_summary")
    assert isinstance(flattened_metadata, dict)
    assert flattened_metadata.get("relative_path") == "benchmark_summary.md"
    assert starter_calls == [session_root]


def test_single_offline_starter_pack_fallback_loader_registers_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    session_root.mkdir(parents=True, exist_ok=True)
    helper_script_path = tmp_path / "fake_benchmark_helper.py"
    helper_script_path.write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "",
                "@dataclass",
                "class _DataclassProbe:",
                "    value: int = 1",
                "",
                "def build_starter_pack_for_existing_runs(*, input_dir, output_dir, write_flattened_summary=False):",
                "    starter_dir = output_dir / 'starter_pack_v1'",
                "    starter_dir.mkdir(parents=True, exist_ok=True)",
                "    if write_flattened_summary:",
                "        (output_dir / 'benchmark_summary.md').write_text('# summary\\n', encoding='utf-8')",
                "    return {'ok': True}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name == "scripts.benchmark_cutdown_for_external_ai":
            raise ModuleNotFoundError("No module named 'scripts'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    real_spec_from_file_location = cli.importlib.util.spec_from_file_location

    def _fake_spec_from_file_location(name, location, *args, **kwargs):  # type: ignore[no-untyped-def]
        return real_spec_from_file_location(name, helper_script_path, *args, **kwargs)

    monkeypatch.setattr(
        cli.importlib.util,
        "spec_from_file_location",
        _fake_spec_from_file_location,
    )

    starter_dir = cli._write_single_offline_starter_pack(session_root=session_root)

    assert starter_dir == session_root / "starter_pack_v1"
    assert (session_root / "starter_pack_v1").is_dir()
    assert (session_root / "benchmark_summary.md").is_file()


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

    monkeypatch.setattr(
        cli,
        "_write_single_offline_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run by default")
        ),
    )

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
    assert summary_path in md_files
    upload_bundle_dir = session_root / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    assert upload_bundle_dir.is_dir()
    assert {
        path.name
        for path in upload_bundle_dir.iterdir()
        if path.is_file()
    } == set(cli.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES)
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


def test_pred_run_context_enriches_codex_runtime_from_llm_manifest_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "default_reasoning_level": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(cli, "default_codex_reasoning_effort", lambda cmd=None: None)

    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(tmp_path / "book.epub"),
                "source_hash": "source-hash",
                "recipe_count": 7,
                "run_config": {
                    "llm_recipe_pipeline": "codex-farm-3pass-v1",
                    "codex_farm_cmd": "codex-farm",
                    "workers": 1,
                },
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
                "llm_codex_farm": {
                    "process_runs": {
                        "pass1": {
                            "process_payload": {
                                "codex_model": "gpt-5.3-codex-spark",
                                "codex_reasoning_effort": None,
                                "telemetry": {
                                    "rows": [
                                        {
                                            "tokens_input": 101,
                                            "tokens_cached_input": 9,
                                            "tokens_output": 12,
                                            "tokens_reasoning": 1,
                                            "tokens_total": 114,
                                        }
                                    ]
                                },
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
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    context = cli._load_pred_run_recipe_context(pred_run)

    assert context.run_config is not None
    assert context.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
    assert context.run_config.get("codex_farm_reasoning_effort") == "high"
    assert context.run_config_hash is None
    assert context.run_config_summary is None
    assert context.tokens_input == 101
    assert context.tokens_cached_input == 9
    assert context.tokens_output == 12
    assert context.tokens_reasoning == 1
    assert context.tokens_total == 114


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
    monkeypatch.setattr(
        cli,
        "_write_single_offline_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run when codex variant fails")
        ),
    )

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



















































































































































































