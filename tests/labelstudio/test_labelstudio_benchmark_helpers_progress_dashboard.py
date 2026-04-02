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


def test_run_with_progress_status_renders_last_activity_line(
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
                "Running recipe correction... task 1/3",
                stage_label="recipe pipeline",
                task_current=1,
                task_total=3,
                last_activity_at="2026-03-31T12:00:00+00:00",
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any("last activity:" in message for message in capture.messages)


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


def test_run_with_progress_status_keeps_structured_stage_worker_details_visible(
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
                "Running codex-farm non-recipe finalize... task 1/4 | running 2",
                stage_label="non-recipe finalize",
                task_current=1,
                task_total=4,
                running_workers=2,
                worker_total=4,
                active_tasks=["knowledge-shard-0001", "knowledge-shard-0002"],
                detail_lines=["configured workers: 4", "queued tasks: 3"],
            )
        )
        update_progress(
            format_stage_progress(
                "Running codex-farm non-recipe finalize... task 2/4",
                stage_label="non-recipe finalize",
                task_current=2,
                task_total=4,
                worker_total=4,
                detail_lines=["configured workers: 4", "queued tasks: 2"],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    knowledge_messages = [
        message
        for message in capture.messages
        if "non-recipe finalize" in message.lower()
    ]
    assert knowledge_messages
    assert any("configured workers: 4" in message for message in knowledge_messages)
    assert any("worker 01: knowledge-shard-0001" in message for message in knowledge_messages)
    assert any("worker 03: idle" in message for message in knowledge_messages)
    assert "queued tasks: 2" in capture.messages[-1]


def test_run_with_progress_status_renders_structured_worker_activity_snippets(
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
                "Running canonical line-role pipeline... shard 1/3 | running 1",
                stage_label="canonical line-role pipeline",
                task_current=1,
                task_total=3,
                running_workers=1,
                worker_total=2,
                active_tasks=[
                    "line-role-canonical-0001-a000000-a000294 (0/1 shards) | Running `python3 -m cookimport.llm.editable_task_file --summary`"
                ],
                detail_lines=["configured workers: 2", "queued shards: 2"],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any(
        "worker 01: line-role-canonical-0001-a000000-a000294 (0/1 shards) | Running"
        in message
        for message in capture.messages
    )


def test_run_with_progress_status_renders_all_ten_knowledge_workers(
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
                "Running codex-farm non-recipe finalize... task 0/10 | running 10",
                stage_label="non-recipe finalize",
                task_current=0,
                task_total=10,
                running_workers=10,
                worker_total=10,
                active_tasks=[f"knowledge-shard-{index:04d}" for index in range(1, 11)],
                detail_lines=["configured workers: 10", "queued tasks: 10"],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any("active tasks (10/10, 10 left)" in message for message in capture.messages)
    assert any("worker 10: knowledge-shard-0010" in message for message in capture.messages)
    assert all("active tasks (10/8" not in message for message in capture.messages)


def test_run_with_progress_status_respects_structured_five_worker_total(
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
                "Running canonical line-role pipeline... shard 3/5 | running 2",
                stage_label="canonical line-role pipeline",
                work_unit_label="shard",
                task_current=3,
                task_total=5,
                running_workers=2,
                worker_total=5,
                worker_running=2,
                worker_completed=3,
                worker_failed=0,
                active_tasks=[
                    "line-role-canonical-0004-a000883-a001176 (0/1 shards)",
                    "line-role-canonical-0005-a001177-a001470 (0/1 shards)",
                ],
                detail_lines=["configured workers: 5", "queued shards: 2"],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any("worker 05: done" in message for message in capture.messages)
    assert all("worker 06:" not in message for message in capture.messages)
    assert all("worker 08:" not in message for message in capture.messages)


def test_run_with_progress_status_renders_packet_scale_knowledge_worker_labels(
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
                "Running codex-farm non-recipe finalize... task 47/48 | running 1",
                stage_label="non-recipe finalize",
                task_current=47,
                task_total=48,
                running_workers=1,
                worker_total=1,
                active_tasks=["saltfatacidheatcutdown.ks0009.nr (47/48 tasks)"],
                detail_lines=[
                    "configured workers: 1",
                    "completed shards: 9/10",
                    "queued tasks: 1",
                ],
            )
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any("task 47/48" in message for message in capture.messages)
    assert any("queued tasks: 1" in message for message in capture.messages)
    assert any(
        "worker 01: saltfatacidheatcutdown.ks0009.nr (47/48 tasks)" in message
        for message in capture.messages
    )
    assert all("task 0/10" not in message for message in capture.messages)


def test_run_with_progress_status_clears_codex_worker_state_for_new_phase(
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
        update_progress("codex-farm recipe.correction.compact.v1 task 19/19 | running 0")
        update_progress("Running canonical line-role pipeline...")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (thefoodlabCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    phase_messages = [
        message
        for message in capture.messages
        if "canonical" in message.lower() and "line-role" in message.lower()
    ]
    assert phase_messages
    assert all("active workers: 0" not in message for message in phase_messages)
    assert all("stage:" not in message for message in phase_messages)


def test_run_with_progress_status_hides_zero_active_workers_row(
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
        update_progress("codex-farm recipe.correction.compact.v1 task 4/4 | running 0")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running benchmark...",
        progress_prefix="Benchmark import (roastchickenandotherstoriesCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert all("active workers: 0" not in message for message in capture.messages)


def test_run_with_progress_status_shows_eta_for_canonical_line_role_progress(
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
        update_progress("Running canonical line-role pipeline... shard 1/4 | running 4")
        time.sleep(0.06)
        update_progress("Running canonical line-role pipeline... shard 2/4 | running 3")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        elapsed_threshold_seconds=60,
        tick_seconds=0.05,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any(
        "eta " in message
        and "avg " in message
        for message in capture.messages
    )


def test_run_with_progress_status_shows_worker_rows_for_canonical_line_role_shard_progress(
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
        update_progress("Running canonical line-role pipeline... shard 1/4 | running 4")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Benchmark import (saltfatacidheatCUTDOWN.epub)",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    phase_messages = [
        message
        for message in capture.messages
        if "canonical" in message.lower() and "line-role" in message.lower()
    ]
    assert phase_messages
    assert any("active workers: 4" in message for message in phase_messages)
    assert any("worker 01: running" in message for message in phase_messages)


def test_run_with_progress_status_renders_stage_and_progress_lines_for_plain_task_updates(
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
        update_progress("Analyzing standalone knowledge blocks... task 2/5")
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Running import...",
        progress_prefix="Import",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert any(
        "stage: Analyzing standalone knowledge blocks..." in message
        for message in capture.messages
    )
    assert any("progress: task 2/5 (40%)" in message for message in capture.messages)
    assert any("remaining tasks: 3" in message for message in capture.messages)


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
    _patch_cli_attr(monkeypatch, "console", capture)

    long_task = (
        "r0011_urn_recipeimport_epub_"
        "3d419982b11ed7c2503ba73deac8b6964c077c685dbd9ac199387b6a5504ed58_c11.json"
    )

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.correction.compact.v1 task 4/19 | running 8 | "
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


def test_run_with_progress_status_wraps_long_lines_and_uses_larger_spinner(
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
        width = 96

        def __init__(self) -> None:
            self.messages: list[str] = []
            self.spinners: list[str] = []

        def status(
            self,
            message: str,
            spinner: str = "dots",
            **_kwargs: object,
        ) -> _FakeStatus:
            self.messages.append(message)
            self.spinners.append(spinner)
            return _FakeStatus(self.messages)

    capture = _CaptureConsole()
    _patch_cli_attr(monkeypatch, "console", capture)
    tail_token = "codex-dashboard-tail-token-visible"

    def _run(update_progress):
        update_progress(
            "overall source 0/1 | config 0/2\n"
            "books:\n"
            "book    | DinnerFor2CUTDOWN\n"
            "state   | recipe correction\n"
            "prog    | t3/9 v1/2\n"
            "eta     | 14s\n"
            f"w01     | codex stage detail {tail_token}"
        )
        return {"ok": True}

    result = cli._run_with_progress_status(
        initial_status="Benchmark import running...",
        progress_prefix="Single-profile benchmark",
        run=_run,
        force_live_status=True,
    )

    assert result == {"ok": True}
    assert capture.spinners == ["bouncingBar"]
    assert any(tail_token in message for message in capture.messages)


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
    _patch_cli_attr(monkeypatch, "console", capture)

    long_task = (
        "r0017_urn_recipeimport_epub_"
        "3d419982b11ed7c2503ba73deac8b6964c077c685dbd9ac199387b6a5504ed58_c11.json"
    )

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.correction.compact.v1 task 1/4 | running 3 | "
            f"active [{long_task}]"
        )
        time.sleep(0.55)
        update_progress(
            "codex-farm recipe.correction.compact.v1 task 2/4 | running 3 | "
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
    _patch_cli_attr(monkeypatch, "console", capture)

    def _run(update_progress):
        update_progress(
            "codex-farm recipe.correction.compact.v1 task 2/9 | running 2 | "
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
    assert any("stage: recipe correction" in message for message in capture.messages)
    assert any(
        "codex-farm recipe correction" in message and "task" in message
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
            run_settings=_benchmark_test_run_settings(),
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


def test_all_method_dashboard_preserves_long_task_message() -> None:
    source = cli.AllMethodTarget(
        gold_spans_path=Path("dummy/exports/freeform_span_labels.jsonl"),
        source_file=Path("dummy/book.epub"),
        source_file_name="book.epub",
        gold_display="dummy",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=_benchmark_test_run_settings(),
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants([(source, variants)])
    dashboard.start_source(0)
    dashboard.start_config(
        source_index=0,
        config_index=1,
        config_total=1,
        config_slug="extractor_unstructured",
    )
    tail_token = "single-profile-live-task-tail-token-visible"
    long_task = (
        "Running variant 2/2 (codex-exec) | book 1/1: DinnerFor2CUTDOWN.epub | "
        "codex-farm recipe.correction.compact.v1 stage detail "
        + ("x" * 220)
        + tail_token
    )
    dashboard.set_task(long_task)

    rendered = dashboard.render()
    assert f"task: {long_task}" in rendered
    assert tail_token in rendered


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
            run_settings=_benchmark_test_run_settings(),
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


def test_single_profile_dashboard_renders_book_columns_worker_rows_and_eta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"value": 100.0}
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock["value"])

    dashboard = cli._SingleProfileProgressDashboard(
        rows=[
            cli._SingleProfileBookDashboardRow(
                source_name="AMatterOfTasteCUTDOWN.epub",
                total_configs=1,
            ),
            cli._SingleProfileBookDashboardRow(
                source_name="SeaAndSmokeCUTDOWN.epub",
                total_configs=1,
            ),
        ],
        total_planned_configs=2,
    )
    dashboard.start_source(0)
    dashboard.start_source(1)
    dashboard.start_config(
        source_index=0,
        config_index=1,
        config_total=1,
        config_slug="codex-exec",
    )
    dashboard.start_config(
        source_index=1,
        config_index=1,
        config_total=1,
        config_slug="codex-exec",
    )
    dashboard.ingest_progress(
        source_index=0,
        message=(
            "codex-farm recipe.correction.compact.v1 task 1/4 | running 2 | "
            "active [r0001.json, r0002.json]"
        ),
    )
    clock["value"] = 106.0
    dashboard.ingest_progress(
        source_index=0,
        message=(
            "codex-farm recipe.correction.compact.v1 task 2/4 | running 2 | "
            "active [r0003.json, r0004.json]"
        ),
    )
    dashboard.ingest_progress(
        source_index=1,
        message="Running benchmark evaluation... task 1/2"
    )

    rendered = dashboard.render()
    assert "books:" in rendered
    assert "AMatterOfTasteCUTDOWN" in rendered
    assert "SeaAndSmokeCUTDOWN" in rendered
    assert "state   | recipe correction" in rendered
    assert "prog    | t2/4 v0/1" in rendered
    assert "eta     | 12s" in rendered
    assert "| 6s" in rendered
    assert "w01     | r0003.json" in rendered
    assert "w02     | r0004.json" in rendered


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
