from __future__ import annotations

import sys
from pathlib import Path

import pytest
import typer

from cookimport import cli, entrypoint
from cookimport.config.codex_decision import (
    apply_benchmark_baseline_contract,
    apply_benchmark_codex_contract_from_baseline,
    apply_benchmark_variant_contract,
    classify_codex_surfaces,
    normalize_codex_execution_policy_mode,
)


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

    monkeypatch.setattr("cookimport.cli_commands.stage._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.stage(
            path=source_file,
            out=tmp_path / "output",
            llm_recipe_pipeline="codex-recipe-shard-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_stage_requires_allow_codex_for_merged_recipe_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli_commands.stage._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.stage(
            path=source_file,
            out=tmp_path / "output",
            llm_recipe_pipeline="codex-recipe-shard-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_removed_plan_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_codex_execution_policy_mode("plan")


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

    monkeypatch.setattr("cookimport.cli_commands.labelstudio._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_import(
            path=source_file,
            output_dir=tmp_path / "labelstudio",
            allow_labelstudio_write=True,
            llm_recipe_pipeline="codex-recipe-shard-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_labelstudio_import_prelabel_requires_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli_commands.labelstudio._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_import(
            path=source_file,
            output_dir=tmp_path / "labelstudio",
            allow_labelstudio_write=True,
            prelabel=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "prelabel" in failures[0]
    assert "--allow-codex" in failures[0]


def test_codex_surface_classification_treats_prelabel_as_codex_surface() -> None:
    surface = classify_codex_surfaces(
        {
            "prelabel_enabled": True,
            "prelabel_provider": "custom-provider",
        }
    )
    assert surface.prelabel_codex_enabled is True
    assert surface.any_codex_enabled is True
    assert surface.codex_surfaces == ("prelabel",)


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

    monkeypatch.setattr("cookimport.cli_commands.labelstudio._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-recipe-shard-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_labelstudio_benchmark_requires_benchmark_codex_confirmation(
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

    monkeypatch.setattr("cookimport.cli_support._fail", _fake_fail)
    monkeypatch.setattr("cookimport.cli_support._is_agent_execution_environment", lambda: False)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-recipe-shard-v1",
            allow_codex=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--benchmark-codex-confirmation" in failures[0]


def test_labelstudio_benchmark_live_codex_blocked_in_agent_environment(
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

    monkeypatch.setattr("cookimport.cli_support._fail", _fake_fail)
    monkeypatch.setattr("cookimport.cli_support._is_agent_execution_environment", lambda: True)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-recipe-shard-v1",
            allow_codex=True,
            benchmark_codex_confirmation=cli.BENCH_CODEX_FARM_CONFIRMATION_TOKEN,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "blocked in agent-run environments" in failures[0]


def test_labelstudio_benchmark_live_codex_interactive_mode_bypasses_agent_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli_support._fail", _fake_fail)
    monkeypatch.setattr("cookimport.cli_support._is_agent_execution_environment", lambda: True)
    interactive_token = cli._INTERACTIVE_CLI_ACTIVE.set(True)

    try:
        cli._enforce_live_labelstudio_benchmark_codex_guardrails(
            any_codex_enabled=True,
            benchmark_codex_confirmation=None,
        )
    finally:
        cli._INTERACTIVE_CLI_ACTIVE.reset(interactive_token)

    assert failures == []


def test_benchmark_contracts_preserve_selected_atomic_block_splitter() -> None:
    payload = {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "line_role_pipeline": "codex-line-role-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
        "atomic_block_splitter": "atomic-v1",
    }

    baseline = apply_benchmark_baseline_contract(payload)
    codex = apply_benchmark_codex_contract_from_baseline(baseline)
    baseline_variant = apply_benchmark_variant_contract(payload, "vanilla")
    codex_variant = apply_benchmark_variant_contract(payload, "codexfarm")

    assert baseline["atomic_block_splitter"] == "atomic-v1"
    assert codex["atomic_block_splitter"] == "atomic-v1"
    assert baseline_variant["atomic_block_splitter"] == "atomic-v1"
    assert codex_variant["atomic_block_splitter"] == "atomic-v1"


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
