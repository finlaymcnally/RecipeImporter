from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.cli_worker import stage_one_file
from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.core.timing import TimingStats
from cookimport.llm.codex_farm_orchestrator import (
    PASS1_PIPELINE_ID,
    PASS2_PIPELINE_ID,
    PASS3_PIPELINE_ID,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError, SubprocessCodexFarmRunner
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner


def _build_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 4}},
            )
        ],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Serve warm."},
                    ],
                    "block_count": 5,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_run_settings(pack_root: Path) -> RunSettings:
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    return RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_context_blocks": 3,
            "codex_farm_failure_mode": "fail",
        }
    )


def test_orchestrator_runs_three_passes_and_writes_manifest(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    runner = FakeCodexFarmRunner()

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID, PASS3_PIPELINE_ID]
    assert apply_result.intermediate_overrides_by_recipe_id
    assert apply_result.final_overrides_by_recipe_id
    assert apply_result.llm_report["enabled"] is True
    manifest_path = apply_result.llm_raw_dir / "llm_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["pass1_ok"] == 1
    assert manifest["counts"]["pass3_ok"] == 1


def test_orchestrator_uses_configured_pipeline_ids_and_workspace_root(
    tmp_path: Path,
) -> None:
    class _RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_pipeline(
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
        ) -> None:
            self.calls.append(
                {
                    "pipeline_id": pipeline_id,
                    "root_dir": root_dir,
                    "workspace_root": workspace_root,
                    "env_root": env.get("CODEX_FARM_ROOT"),
                }
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            for in_path in sorted(in_dir.glob("*.json")):
                payload = json.loads(in_path.read_text(encoding="utf-8"))
                if pipeline_id == "custom.pass1":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "is_recipe": True,
                        "start_block_index": payload.get("heuristic_start_block_index"),
                        "end_block_index": payload.get("heuristic_end_block_index"),
                        "title": None,
                        "reasoning_tags": ["recording-runner"],
                        "excluded_block_ids": [],
                    }
                elif pipeline_id == "custom.pass2":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "schemaorg_recipe": {
                            "@context": "http://schema.org",
                            "@type": "Recipe",
                            "name": "Custom Recipe",
                        },
                        "extracted_ingredients": [],
                        "extracted_instructions": [],
                        "field_evidence": {},
                        "warnings": [],
                    }
                elif pipeline_id == "custom.pass3":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "draft_v1": {
                            "schema_v": 1,
                            "source": None,
                            "recipe": {"title": "Custom Recipe"},
                            "steps": [
                                {
                                    "instruction": "See original recipe for details.",
                                    "ingredient_lines": [],
                                }
                            ],
                        },
                        "ingredient_step_mapping": {},
                        "warnings": [],
                    }
                else:
                    raise AssertionError(f"Unexpected pipeline id: {pipeline_id}")
                (out_dir / in_path.name).write_text(
                    json.dumps(output, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    pack_root = tmp_path / "pack"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(pack_root)
    settings = settings.model_copy(
        update={
            "codex_farm_workspace_root": str(workspace_root),
            "codex_farm_pipeline_pass1": "custom.pass1",
            "codex_farm_pipeline_pass2": "custom.pass2",
            "codex_farm_pipeline_pass3": "custom.pass3",
        }
    )
    result = _build_conversion_result(source)
    runner = _RecordingRunner()

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert [call["pipeline_id"] for call in runner.calls] == [
        "custom.pass1",
        "custom.pass2",
        "custom.pass3",
    ]
    for call in runner.calls:
        assert call["root_dir"] == pack_root
        assert call["workspace_root"] == workspace_root
        assert call["env_root"] == str(pack_root)

    manifest_path = apply_result.llm_raw_dir / "llm_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pipelines"] == {
        "pass1": "custom.pass1",
        "pass2": "custom.pass2",
        "pass3": "custom.pass3",
    }
    assert apply_result.llm_report["pipelines"] == manifest["pipelines"]


def test_orchestrator_recipe_level_failures_fallback_without_crashing(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda _payload: {
                "bundle_version": "1",
                "recipe_id": "oops",
            }
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    assert apply_result.intermediate_overrides_by_recipe_id == {}
    assert apply_result.final_overrides_by_recipe_id == {}
    assert len(apply_result.updated_conversion_result.recipes) == 1
    assert apply_result.llm_report["counts"]["pass2_errors"] == 1


def test_stage_one_file_skips_codex_farm_when_pipeline_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    out = tmp_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    fake_result = _build_conversion_result(source)

    orchestrator_called = {"value": False}

    def _fake_orchestrator(**_kwargs):
        orchestrator_called["value"] = True
        raise AssertionError("orchestrator should not run when llm pipeline is off")

    def _fake_import(*_args, **_kwargs):
        return fake_result.model_copy(deep=True), TimingStats(), MappingConfig()

    monkeypatch.setattr("cookimport.cli_worker.run_codex_farm_recipe_pipeline", _fake_orchestrator)
    monkeypatch.setattr("cookimport.cli_worker._run_import", _fake_import)
    monkeypatch.setattr(
        "cookimport.cli_worker.registry.best_importer_for_path",
        lambda _path: (SimpleNamespace(name="text"), 1.0),
    )

    response = stage_one_file(
        source,
        out,
        MappingConfig(),
        None,
        dt.datetime.now(),
        run_config=RunSettings().to_run_config_dict(),
    )

    assert response["status"] == "success"
    assert orchestrator_called["value"] is False


def test_subprocess_runner_reports_missing_binary(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    runner = SubprocessCodexFarmRunner(cmd="definitely-missing-codex-farm-binary")
    with pytest.raises(CodexFarmRunnerError):
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})


def test_subprocess_runner_passes_root_and_workspace_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    workspace_root = tmp_path / "workspace"
    in_dir.mkdir(parents=True, exist_ok=True)
    root_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        captured["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"EXTRA_ENV": "1"},
        root_dir=root_dir,
        workspace_root=workspace_root,
    )

    command = captured.get("command")
    assert isinstance(command, list)
    assert "--root" in command
    assert str(root_dir) in command
    assert "--workspace-root" in command
    assert str(workspace_root) in command
