from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner
import pytest

from cookimport import cli
from cookimport import cli_worker
from cookimport.cli import JobSpec
from cookimport.core.executor_fallback import ProcessThreadExecutorResolution


runner = CliRunner()


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
    monkeypatch.setattr(cli, "_iter_files", lambda *_args, **_kwargs: [source_path])
    if split_job:
        monkeypatch.setattr(
            cli_worker,
            "stage_pdf_job",
            lambda *_args, **_kwargs: {
                "status": "success",
                "file": source_path.name,
                "recipes": 1,
                "tips": 0,
                "duration": 0.12,
            },
        )
        monkeypatch.setattr(
            cli,
            "_merge_pdf_jobs",
            lambda *_args, **_kwargs: {
                "file": source_path.name,
                "status": "success",
                "recipes": 1,
                "tips": 0,
                "duration": 0.12,
            },
        )
    else:
        monkeypatch.setattr(
            cli_worker,
            "stage_one_file",
            lambda *_args, **_kwargs: {
                "status": "success",
                "file": source_path.name,
                "recipes": 1,
                "tips": 0,
                "duration": 0.12,
            },
        )
    monkeypatch.setattr(
        cli,
        "_plan_jobs",
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
    monkeypatch.setattr(
        cli,
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
    monkeypatch.setattr(cli, "console", _PlainConsole())
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
            "--llm-tags-pipeline",
            "off",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "1"},
    )

    assert result.exit_code == 0
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 0 | pending 0 | errors 0"
        in result.output
    )
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 0 | pending 0 | errors 0\n"
        "current: simple_text.txt\n"
        "task: stage task 1/1" in result.output
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
    monkeypatch.setattr(cli, "console", _PlainConsole())
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
            "--llm-tags-pipeline",
            "off",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "1"},
    )

    assert result.exit_code == 0
    assert (
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0"
        in result.output
    )
    assert "Merging 1 jobs for split_text.pdf..." in result.output
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
    monkeypatch.setattr(cli, "console", _LiveConsole(status_messages, printed_messages))
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
            "--llm-tags-pipeline",
            "off",
        ],
        env={"COOKIMPORT_PLAIN_PROGRESS": "0"},
    )

    assert result.exit_code == 0
    assert any("overall jobs" in message for message in status_messages)
    assert any("stage task 1/1" in message for message in status_messages)
    assert any(
        "overall jobs 1/1 | imported 1 | active_workers 0 | pending 0 | errors 0\n"
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
