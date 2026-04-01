from __future__ import annotations

import cookimport.cli_support.progress as progress_support
from cookimport.core.progress_messages import format_stage_progress
import tests.labelstudio.benchmark_helper_support as _base

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_progress_split_module_appends_processing_timeseries_marker_with_json_safe(
    tmp_path: Path,
) -> None:
    telemetry_path = tmp_path / "processing_timeseries.jsonl"

    progress_support._append_processing_timeseries_marker(
        telemetry_path=telemetry_path,
        event="started",
        payload={
            "processed_run_root": tmp_path / "processed",
            "nested": {"report_path": tmp_path / "report.json"},
        },
    )

    rows = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [
        {
            "event": "started",
            "nested": {"report_path": str(tmp_path / "report.json")},
            "processed_run_root": str(tmp_path / "processed"),
            "timestamp": rows[0]["timestamp"],
        }
    ]


def test_processing_timeseries_writer_serializes_path_payloads(
    tmp_path: Path,
) -> None:
    telemetry_path = tmp_path / "processing_timeseries.jsonl"
    writer = cli._ProcessingTimeseriesWriter(path=telemetry_path, heartbeat_seconds=0.05)

    writer.write_row(
        snapshot="stage task 1/1",
        force=True,
        payload={
            "event": "update",
            "run_dir": tmp_path / "run",
            "worker_status": [{"artifact_path": tmp_path / "artifact.json"}],
        },
    )

    rows = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [
        {
            "cpu_utilization_pct": rows[0]["cpu_utilization_pct"],
            "event": "update",
            "monotonic_seconds": rows[0]["monotonic_seconds"],
            "run_dir": str(tmp_path / "run"),
            "snapshot": "stage task 1/1",
            "timestamp": rows[0]["timestamp"],
            "worker_status": [{"artifact_path": str(tmp_path / "artifact.json")}],
        }
    ]

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


def test_extract_progress_stage_label_strips_line_role_shard_suffix() -> None:
    assert (
        cli._extract_progress_stage_label(
            "Running canonical line-role pipeline... shard 2/4 | running 3"
        )
        == "Running canonical line-role pipeline..."
    )


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


def test_recent_rate_average_seconds_per_task_biases_toward_latest_step() -> None:
    samples: deque[tuple[float, int]] = deque(
        [
            (8.0, 2),  # older: 4s/task, 4s/task
            (6.0, 1),  # older: 6s/task
            (9.0, 3),  # newest: 3s/task x3
        ]
    )
    # Most recent five steps: 3,3,3,6,4 with weights 30/20/20/20/10.
    weighted = (3.0 * 0.30 + 3.0 * 0.20 + 3.0 * 0.20 + 6.0 * 0.20 + 4.0 * 0.10) / 1.0
    # Shared ETA estimator blends weighted recent history with the newest step.
    expected = (3.0 * 0.50) + (weighted * 0.50)
    assert cli._recent_rate_average_seconds_per_task(samples) == pytest.approx(expected)


def test_recent_rate_average_seconds_per_task_reacts_faster_to_latest_slowdown() -> None:
    samples: deque[tuple[float, int]] = deque(
        [
            (2.0, 2),  # older: 1s/task
            (2.0, 2),  # older: 1s/task
            (20.0, 1),  # newest: 20s/task
        ]
    )
    recent_average = cli._recent_rate_average_seconds_per_task(samples)
    assert recent_average is not None
    # A pure weighted-average estimator would be 6.7s/task for this shape.
    # Recency blending should move much closer to the newest observed duration.
    assert recent_average > 10.0


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
        time.sleep(1.05)
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
    _patch_cli_attr(monkeypatch, "console", _GuardConsole())
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
    _patch_cli_attr(monkeypatch, "console", capture)

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


def test_run_with_progress_status_falls_back_to_plain_when_live_slots_are_full(
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
    _patch_cli_attr(monkeypatch, "console", capture)
    monkeypatch.setenv("COOKIMPORT_PLAIN_PROGRESS", "0")
    monkeypatch.setenv("COOKIMPORT_LIVE_STATUS_SLOTS", "1")
    plain_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: plain_messages.append(str(message)),
    )

    release_first = threading.Event()
    first_started = threading.Event()
    first_result: dict[str, object] = {}
    first_errors: list[Exception] = []

    def _run_first(update_progress):
        update_progress("Benchmark task 1/1")
        first_started.set()
        assert release_first.wait(timeout=2.0)
        return {"ok": True}

    def _invoke_first() -> None:
        try:
            first_result["value"] = cli._run_with_progress_status(
                initial_status="Running benchmark...",
                progress_prefix="Bench",
                run=_run_first,
                tick_seconds=0.05,
                force_live_status=True,
            )
        except Exception as exc:  # noqa: BLE001
            first_errors.append(exc)

    first_thread = threading.Thread(target=_invoke_first, daemon=True)
    first_thread.start()
    assert first_started.wait(timeout=1.0)

    second_result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Bench",
        run=lambda update_progress: (
            update_progress("Benchmark task 1/1") or {"ok": True}
        ),
        tick_seconds=0.05,
        force_live_status=True,
    )

    release_first.set()
    first_thread.join(timeout=2.0)
    assert not first_errors
    assert first_result.get("value") == {"ok": True}
    assert second_result == {"ok": True}
    assert capture.status_calls == 1
    assert any("Bench: Benchmark task 1/1" in message for message in plain_messages)


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
        time.sleep(1.05)
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
        time.sleep(0.06)
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


def test_run_with_progress_status_resets_eta_history_when_stage_changes(
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
        update_progress(
            format_stage_progress(
                "Stage one task 1/10",
                stage_label="stage one",
                task_current=1,
                task_total=10,
            )
        )
        time.sleep(0.05)
        update_progress(
            format_stage_progress(
                "Stage one task 2/10",
                stage_label="stage one",
                task_current=2,
                task_total=10,
            )
        )
        time.sleep(0.05)
        update_progress(
            format_stage_progress(
                "Stage two task 2/10",
                stage_label="stage two",
                task_current=2,
                task_total=10,
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.01,
        force_live_status=True,
    )

    assert result == {"ok": True}
    stage_two_messages = [
        message for message in capture.messages if "Stage two task 2/10" in message
    ]
    assert stage_two_messages, "Expected stage two progress updates"
    assert not any("avg " in message for message in stage_two_messages)


def test_parallel_bootstrap_eta_seconds_uses_worker_waves() -> None:
    assert (
        cli._parallel_bootstrap_eta_seconds(
            avg_seconds_per_task=1.0,
            remaining=9,
            parallelism=9,
        )
        == 1
    )
    assert (
        cli._parallel_bootstrap_eta_seconds(
            avg_seconds_per_task=1.0,
            remaining=9,
            parallelism=1,
        )
        == 9
    )


def test_single_profile_dashboard_bootstrap_eta_uses_parallel_workers() -> None:
    now = time.monotonic()
    row = cli._SingleProfileBookDashboardRow(
        source_name="saltfatacidheatCUTDOWN.epub",
        total_configs=1,
        status="running",
        current_counter=(1, 10),
        worker_total=10,
        worker_statuses={index: "busy" for index in range(1, 10)},
        phase_started_at=now - 1.2,
    )

    eta_seconds = cli._SingleProfileProgressDashboard._estimate_eta_seconds(row, now)

    assert eta_seconds is not None
    assert eta_seconds <= 2


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
        time.sleep(1.05)
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


def test_run_with_progress_status_writes_structured_stage_timeseries_fields(
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
        update_progress(
            format_stage_progress(
                "Running codex-farm non-recipe finalize... task 1/4 | running 2",
                stage_label="non-recipe finalize",
                work_unit_label="task",
                task_current=1,
                task_total=4,
                running_workers=2,
                worker_total=4,
                worker_running=2,
                worker_completed=2,
                followup_running=1,
                followup_completed=3,
                followup_total=4,
                followup_label="repair/retry",
                artifact_counts={"proposal_count": 3, "repair_running": 1},
                active_tasks=["knowledge-shard-0001", "knowledge-shard-0002"],
                detail_lines=["configured workers: 4", "queued tasks: 3"],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        telemetry_path=telemetry_path,
        force_live_status=True,
    )

    assert result == {"ok": True}
    rows = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row.get("stage_label") == "non-recipe finalize" for row in rows)
    assert any(row.get("work_unit_label") == "task" for row in rows)
    assert any(row.get("worker_total") == 4 for row in rows)
    assert any(row.get("worker_active") == 2 for row in rows)
    assert any(row.get("worker_completed") == 2 for row in rows)
    assert any(row.get("followup_label") == "repair/retry" for row in rows)
    assert any((row.get("artifact_counts") or {}).get("proposal_count") == 3 for row in rows)
    assert any(row.get("active_tasks") == ["knowledge-shard-0001", "knowledge-shard-0002"] for row in rows)
    assert any("configured workers: 4" in (row.get("detail_lines") or []) for row in rows)


def test_format_stage_progress_round_trips_typed_fields() -> None:
    payload = parse_stage_progress(
        format_stage_progress(
            "Running recipe correction... task 2/3",
            stage_label="recipe pipeline",
            work_unit_label="recipe task",
            task_current=2,
            task_total=3,
            running_workers=1,
            worker_total=2,
            worker_running=1,
            worker_completed=1,
            worker_failed=0,
            followup_running=2,
            followup_completed=1,
            followup_total=2,
            followup_label="shard finalization",
            artifact_counts={"proposal_count": 1, "repair_running": 2},
            last_activity_at="2026-03-21T16:00:00+00:00",
            active_tasks=["recipe-shard-0002.task-001"],
            detail_lines=["configured workers: 2"],
        )
    )

    assert payload is not None
    assert payload["work_unit_label"] == "recipe task"
    assert payload["worker_running"] == 1
    assert payload["worker_completed"] == 1
    assert payload["followup_label"] == "shard finalization"
    assert payload["artifact_counts"] == {
        "proposal_count": 1,
        "repair_running": 2,
    }
