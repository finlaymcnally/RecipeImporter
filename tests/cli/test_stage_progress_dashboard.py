from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

from typer.testing import CliRunner
import pytest

from cookimport import cli
from cookimport import cli_worker
import cookimport.cli_commands.stage as stage_cli
import cookimport.cli_support.progress as progress_cli
import cookimport.cli_support.stage as stage_support
from cookimport.cli import JobSpec
from cookimport.core.executor_fallback import ProcessThreadExecutorResolution


runner = CliRunner()


def test_stage_run_summary_collects_codex_guardrail_warnings(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    summary_path = run_root / "raw" / "llm" / "book" / "recipe_phase_runtime" / "recipe_stage_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "task_file_guardrails": {
                    "warning_count": 1,
                    "largest_assignment": {
                        "worker_id": "worker-001",
                        "task_file_bytes": 24576,
                        "task_file_estimated_tokens": 5000,
                    },
                },
                "worker_session_guardrails": {
                    "planned_happy_path_worker_cap": 1,
                    "actual_happy_path_worker_sessions": 1,
                    "cap_exceeded": False,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    warnings = stage_support._collect_codex_guardrail_warnings(  # noqa: SLF001
        run_root,
        {
            "stages": [
                {
                    "stage_key": "recipe_refine",
                    "stage_label": "Recipe Refine",
                    "workbooks": [
                        {
                            "artifact_paths": {
                                "recipe_stage_summary_json": str(
                                    summary_path.relative_to(run_root)
                                )
                            }
                        }
                    ],
                }
            ]
        },
    )

    assert warnings == [
        "Recipe Refine: 1 planned task.json warning(s); largest assignment worker-001 was 24.0 KiB (~5000 tokens)."
    ]


def _patch_stage_attr(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: object,
) -> None:
    for module in (cli, stage_cli, progress_cli):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value)


class _StatusConsoleSink:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def print(self, message: object, *_args: object, **_kwargs: object) -> None:
        self.messages.append(str(message))


class _StatusTracker:
    def __init__(
        self,
        status_messages: list[str],
        printed_messages: list[str],
    ) -> None:
        self.status_messages = status_messages
        self.console = _StatusConsoleSink(printed_messages)

    def __enter__(self) -> "_StatusTracker":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def update(self, message: str) -> None:
        self.status_messages.append(str(message))


class _PlainConsole:
    is_terminal = True
    is_dumb_terminal = False

    def status(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("plain mode should not invoke console.status")


class _LiveConsole:
    is_terminal = True
    is_dumb_terminal = False

    def __init__(self, status_messages: list[str], printed_messages: list[str]) -> None:
        self.status_messages = status_messages
        self.printed_messages = printed_messages

    def status(self, message: object, *_args: object, **_kwargs: object) -> _StatusTracker:
        self.status_messages.append(str(message))
        return _StatusTracker(self.status_messages, self.printed_messages)


def _install_fake_stage_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    source_path: Path,
    *,
    split_job: bool = False,
) -> None:
    _patch_stage_attr(monkeypatch, "_iter_files", lambda *_args, **_kwargs: [source_path])
    _patch_stage_attr(
        monkeypatch,
        "_merge_source_jobs",
        lambda *_args, **_kwargs: {
            "file": source_path.name,
            "status": "success",
            "recipes": 1,
            "tips": 0,
            "duration": 0.12,
        },
    )
    if split_job:
        monkeypatch.setattr(
            cli_worker,
            "execute_source_job",
            lambda *_args, **_kwargs: {
                "status": "success",
                "file": source_path.name,
                "recipes": 1,
                "tips": 0,
                "duration": 0.12,
                "importer_name": "pdf",
                "result": None,
            },
        )
    else:
        monkeypatch.setattr(
            cli_worker,
            "execute_source_job",
            lambda *_args, **_kwargs: {
                "status": "success",
                "file": source_path.name,
                "recipes": 1,
                "tips": 0,
                "duration": 0.12,
                "importer_name": "text",
                "result": None,
            },
        )
    _patch_stage_attr(
        monkeypatch,
        "plan_source_jobs",
        (
            lambda *_args, **_kwargs: [
                JobSpec(
                    file_path=source_path,
                    job_index=0,
                    job_count=1,
                    start_page=0,
                    end_page=0,
                )
            ]
            if split_job
            else [JobSpec(file_path=source_path, job_index=0, job_count=1)]
        ),
    )
    _patch_stage_attr(
        monkeypatch,
        "resolve_process_thread_executor",
        lambda **_kwargs: ProcessThreadExecutorResolution(
            backend="serial",
            executor=None,
            messages=(),
        ),
    )


def test_stage_plain_progress_with_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = tmp_path / "simple_text.txt"
    source_file.write_text("hello world", encoding="utf-8")
    output_root = tmp_path / "output"
    _patch_stage_attr(monkeypatch, "console", _PlainConsole())
    _install_fake_stage_pipeline(monkeypatch, source_file)

    result = runner.invoke(
        cli.app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_root),
            "--workers",
            "1",
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "1"},
    )

    assert result.exit_code == 0
    assert (
        "overall jobs 0/1 | imported 0 | active_workers 0 | pending 1 | errors 0"
        in result.output
    )
    assert (
        "overall jobs 0/1 | imported 0 | active_workers 0 | pending 1 | errors 0\n"
        "current: simple_text.txt\n"
        "task: stage task 0/1" in result.output
    )
    assert "Merging 1 source job(s) for simple_text.txt..." in result.output
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0"
        in result.output
    )
    assert "Staged 1 file(s)." in result.output
    assert "[yellow]" not in result.output
    assert "[green]" not in result.output
    assert "[red]" not in result.output


def test_stage_merge_phase_messages_use_shared_snapshot_in_plain_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = tmp_path / "split_text.pdf"
    source_file.write_text("hello world", encoding="utf-8")
    output_root = tmp_path / "output"
    _patch_stage_attr(monkeypatch, "console", _PlainConsole())
    _install_fake_stage_pipeline(monkeypatch, source_file, split_job=True)

    result = runner.invoke(
        cli.app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_root),
            "--workers",
            "1",
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "1"},
    )

    assert result.exit_code == 0
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0"
        in result.output
    )
    assert "Merging 1 source job(s) for split_text.pdf..." in result.output
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0\n"
        "current: split_text.pdf\n"
        "task: stage task 1/1" in result.output
    )
    assert "current: split_text.pdf" in result.output
    assert (
        "split_text.pdf: 1 recipes, 0 tips (merge 0.12s)" in result.output
    )
    assert "MainProcess: split_text.pdf - Merge done (0.12s) (" in result.output


def test_stage_live_progress_updates_use_shared_status_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = tmp_path / "simple_text.txt"
    source_file.write_text("hello world", encoding="utf-8")
    output_root = tmp_path / "output"

    status_messages: list[str] = []
    printed_messages: list[str] = []
    _patch_stage_attr(
        monkeypatch,
        "console",
        _LiveConsole(status_messages, printed_messages),
    )
    _install_fake_stage_pipeline(monkeypatch, source_file)

    result = runner.invoke(
        cli.app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_root),
            "--workers",
            "1",
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "0"},
    )

    assert result.exit_code == 0
    assert any("overall jobs" in message for message in status_messages)
    assert any("stage task 1/1" in message for message in status_messages)
    assert any(
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0\n"
        "current: simple_text.txt\n"
        "task: stage task 1/1" in message
        for message in status_messages
    )
    assert any("task: stage task 1/1" in message for message in status_messages)
    assert any(
        "current: simple_text.txt" in message
        for message in status_messages
    )
    assert any(
        "simple_text.txt" in message and "recipes" in message
        for message in printed_messages
    )
    assert "Staged 1 file(s)." in result.output


def test_stage_live_progress_falls_back_to_plain_when_live_slot_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = tmp_path / "simple_text.txt"
    source_file.write_text("hello world", encoding="utf-8")
    output_root = tmp_path / "output"

    @contextmanager
    def _deny_live_slot(_slot_limit: int):
        yield False

    _patch_stage_attr(monkeypatch, "_acquire_live_status_slot", _deny_live_slot)
    _patch_stage_attr(monkeypatch, "console", _PlainConsole())
    _install_fake_stage_pipeline(monkeypatch, source_file)

    result = runner.invoke(
        cli.app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_root),
            "--workers",
            "1",
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "0"},
    )

    assert result.exit_code == 0
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0"
        in result.output
    )
    assert "Staged 1 file(s)." in result.output
