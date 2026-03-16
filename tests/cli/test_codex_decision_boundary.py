from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import typer

from cookimport import cli, entrypoint
from cookimport.config.codex_decision import bucket1_fixed_behavior, classify_codex_surfaces


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
            llm_recipe_pipeline="codex-farm-single-correction-v1",
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

    monkeypatch.setattr(cli, "_fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.stage(
            path=source_file,
            out=tmp_path / "output",
            llm_recipe_pipeline="codex-farm-single-correction-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_stage_plan_mode_allows_codex_without_allow_codex(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")

    run_root = cli.stage(
        path=source_file,
        out=tmp_path / "output",
        llm_recipe_pipeline="codex-farm-single-correction-v1",
        codex_execution_policy="plan",
    )

    run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    plan_payload = json.loads(
        (run_root / "codex_execution_plan.json").read_text(encoding="utf-8")
    )
    assert run_manifest["run_config"]["codex_execution_policy_requested_mode"] == "plan"
    assert run_manifest["run_config"]["codex_execution_policy_resolved_mode"] == "plan"
    assert run_manifest["run_config"]["codex_execution_plan_only"] is True
    assert run_manifest["artifacts"]["codex_execution_plan_json"] == "codex_execution_plan.json"
    assert plan_payload["plan_only"] is True
    assert plan_payload["context"] == "stage"


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
            llm_recipe_pipeline="codex-farm-single-correction-v1",
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

    monkeypatch.setattr(cli, "_fail", _fake_fail)

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


def test_labelstudio_import_plan_mode_allows_codex_without_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.txt"
    source_file.write_text("recipe", encoding="utf-8")
    prediction_run = tmp_path / "prediction-run"
    prediction_run.mkdir(parents=True)
    plan_path = prediction_run / "codex_execution_plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **kwargs: captured.update(kwargs) or {
            "run_root": prediction_run,
            "codex_execution_plan_path": plan_path,
        },
    )
    monkeypatch.setattr(
        cli,
        "_require_labelstudio_write_consent",
        lambda _allowed: pytest.fail("plan mode should not require upload consent"),
    )
    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_args, **_kwargs: pytest.fail("plan mode should not resolve Label Studio settings"),
    )

    cli.labelstudio_import(
        path=source_file,
        output_dir=tmp_path / "labelstudio",
        llm_recipe_pipeline="codex-farm-single-correction-v1",
        codex_execution_policy="plan",
    )

    assert captured["allow_codex"] is False
    assert captured["codex_execution_policy"] == "plan"
    assert captured["run_manifest_kind"] == "labelstudio_import"


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
            llm_recipe_pipeline="codex-farm-single-correction-v1",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--allow-codex" in failures[0]


def test_labelstudio_benchmark_plan_mode_allows_codex_without_allow_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "prediction-run"
    prediction_run.mkdir(parents=True)
    prediction_manifest = prediction_run / "manifest.json"
    prediction_manifest.write_text("{}", encoding="utf-8")
    plan_path = prediction_run / "codex_execution_plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}
    fixed_bucket1_behavior = bucket1_fixed_behavior()

    def _fake_generate_pred_run_artifacts(**kwargs):
        captured.update(kwargs)
        return {
            "run_root": prediction_run,
            "manifest_path": prediction_manifest,
            "codex_execution_plan_path": plan_path,
            "run_config": {
                "llm_recipe_pipeline": "codex-farm-single-correction-v1",
                "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
            },
            "run_config_hash": "hash",
            "run_config_summary": "summary",
            "source_hash": "source-hash",
            "importer_name": "epub",
        }

    monkeypatch.setattr(cli, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "processed",
        eval_output_dir=eval_root,
        no_upload=True,
        llm_recipe_pipeline="codex-farm-single-correction-v1",
        llm_knowledge_pipeline="codex-farm-knowledge-v1",
        codex_farm_pipeline_knowledge="recipe.knowledge.custom.v9",
        codex_farm_knowledge_context_blocks=19,
        codex_execution_policy="plan",
    )

    assert captured["allow_codex"] is False
    assert captured["codex_execution_policy"] == "plan"
    assert captured["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"
    assert (
        captured["codex_farm_pipeline_knowledge"]
        == fixed_bucket1_behavior.codex_farm_pipeline_knowledge
    )
    assert captured["codex_farm_knowledge_context_blocks"] == 19
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["codex_execution_policy_requested_mode"] == "plan"
    assert run_manifest["run_config"]["codex_execution_policy_resolved_mode"] == "plan"
    assert run_manifest["run_config"]["codex_execution_plan_only"] is True
    assert run_manifest["artifacts"]["prediction_codex_execution_plan_json"].endswith(
        "codex_execution_plan.json"
    )
    assert run_manifest["run_config"]["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"


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

    monkeypatch.setattr(cli, "_fail", _fake_fail)
    monkeypatch.setattr(cli, "_is_agent_execution_environment", lambda: False)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-farm-single-correction-v1",
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

    monkeypatch.setattr(cli, "_fail", _fake_fail)
    monkeypatch.setattr(cli, "_is_agent_execution_environment", lambda: True)

    with pytest.raises(typer.Exit) as excinfo:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "processed",
            eval_output_dir=tmp_path / "eval",
            no_upload=True,
            llm_recipe_pipeline="codex-farm-single-correction-v1",
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

    monkeypatch.setattr(cli, "_fail", _fake_fail)
    monkeypatch.setattr(cli, "_is_agent_execution_environment", lambda: True)
    interactive_token = cli._INTERACTIVE_CLI_ACTIVE.set(True)

    try:
        cli._enforce_live_labelstudio_benchmark_codex_guardrails(
            codex_execution_policy="execute",
            any_codex_enabled=True,
            benchmark_codex_confirmation=None,
        )
    finally:
        cli._INTERACTIVE_CLI_ACTIVE.reset(interactive_token)

    assert failures == []


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


def test_import_entrypoint_forwards_codex_execution_policy_flag(
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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cookimport-import",
            "--codex-execution-policy",
            "plan",
        ],
    )

    entrypoint.main()

    assert captured["path"] == Path("/tmp/input")
    assert captured["codex_execution_policy"] == "plan"
