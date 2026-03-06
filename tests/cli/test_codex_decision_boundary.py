from __future__ import annotations

import sys
from pathlib import Path

import pytest
import typer

from cookimport import cli, entrypoint


def test_stage_requires_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.stage(
            path=source_file,
            out=tmp_path / "output",
            llm_recipe_pipeline="codex-farm-3pass-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_labelstudio_import_requires_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_import(
            path=source_file,
            output_dir=tmp_path / "labelstudio",
            allow_labelstudio_write=True,
            llm_recipe_pipeline="codex-farm-3pass-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_labelstudio_benchmark_requires_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-farm-3pass-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_import_entrypoint_forwards_allow_codex_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(entrypoint, "_load_settings", lambda: {})
    monkeypatch.setattr(entrypoint, "DEFAULT_INPUT", Path("/tmp/input"))
    monkeypatch.setattr(entrypoint, "DEFAULT_OUTPUT", Path("/tmp/output"))
    monkeypatch.setattr(
        entrypoint,
        "build_stage_call_kwargs_from_run_settings",
        lambda _settings, **kwargs: {"out": kwargs["out"]},
    )
    monkeypatch.setattr(
        entrypoint,
        "stage",
        lambda *, path, **kwargs: captured.update({"path": path, **kwargs}),
    )
    monkeypatch.setattr(entrypoint, "app", lambda: pytest.fail("app should not run"))
    monkeypatch.setattr(sys, "argv", ["cookimport-import", "--allow-codex"])

    entrypoint.main()

    assert captured["path"] == Path("/tmp/input")
    assert captured["allow_codex"] is True
