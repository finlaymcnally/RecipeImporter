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
    SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    SINGLE_CORRECTION_STAGE_PIPELINE_ID,
    build_codex_farm_recipe_execution_plan,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner


def _build_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread", "1 tablespoon butter"],
                recipeInstructions=[
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                provenance={"location": {"start_block": 1, "end_block": 5}},
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
                        {"index": 3, "text": "1 tablespoon butter"},
                        {"index": 4, "text": "Toast the bread until golden."},
                        {"index": 5, "text": "Spread with butter and serve hot."},
                    ],
                    "block_count": 6,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_run_settings(pack_root: Path, *, llm_recipe_pipeline: str) -> RunSettings:
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    return RunSettings.model_validate(
        {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_context_blocks": 3,
            "codex_farm_failure_mode": "fail",
            "codex_farm_recipe_mode": "extract",
        }
    )


def test_orchestrator_runs_single_correction_pipeline_and_writes_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )
    runner = FakeCodexFarmRunner(
        output_builders={
            SINGLE_CORRECTION_STAGE_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "canonical_recipe": {
                    "title": "Toast",
                    "ingredients": [
                        "1 slice bread",
                        "1 tablespoon butter",
                    ],
                    "steps": [
                        "Toast the bread until golden.",
                        "Spread with butter and serve hot.",
                    ],
                    "description": None,
                    "recipeYield": None,
                },
                "ingredient_step_mapping": [
                    {"ingredient_index": 0, "step_indexes": [0]},
                    {"ingredient_index": 1, "step_indexes": [1]},
                ],
                "ingredient_step_mapping_reason": None,
                "selected_tags": [
                    {"category": "meal", "label": "breakfast", "confidence": 0.83},
                    {"category": "method", "label": "toasted", "confidence": 0.79},
                ],
                "warnings": [],
            }
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [SINGLE_CORRECTION_STAGE_PIPELINE_ID]
    assert apply_result.intermediate_overrides_by_recipe_id == {}
    assert apply_result.final_overrides_by_recipe_id
    final_payload = apply_result.final_overrides_by_recipe_id["urn:recipe:test:toast"]
    assert [line["raw_text"] for line in final_payload["steps"][0]["ingredient_lines"]] == [
        "1 slice bread"
    ]
    assert [line["raw_text"] for line in final_payload["steps"][1]["ingredient_lines"]] == [
        "1 tablespoon butter"
    ]

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["pipeline"] == SINGLE_CORRECTION_RECIPE_PIPELINE_ID
    assert manifest["pipelines"] == {
        "recipe_correction": SINGLE_CORRECTION_STAGE_PIPELINE_ID
    }
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert manifest["counts"]["build_final_recipe_ok"] == 1
    assert sorted(manifest["process_runs"].keys()) == ["recipe_correction"]
    correction_input_paths = sorted(
        (apply_result.llm_raw_dir / "recipe_correction" / "in").glob("*.json")
    )
    assert len(correction_input_paths) == 1
    correction_input = json.loads(
        correction_input_paths[0].read_text(encoding="utf-8")
    )
    assert "draft_hint" not in correction_input
    assert "provenance" not in correction_input["recipe_candidate_hint"]
    assert correction_input["tagging_guide"]["version"] == "recipe_tagging_guide.v1"
    assert apply_result.updated_conversion_result.recipes[0].tags == [
        "breakfast",
        "toasted",
    ]


def test_execution_plan_uses_semantic_single_correction_stages(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    plan = build_codex_farm_recipe_execution_plan(
        conversion_result=result,
        run_settings=settings,
        workbook_slug="book",
    )

    assert plan["pipeline"] == SINGLE_CORRECTION_RECIPE_PIPELINE_ID
    stages = plan["planned_tasks"][0]["planned_stages"]
    assert [stage["stage_key"] for stage in stages] == [
        "build_intermediate_det",
        "recipe_llm_correct_and_link",
        "build_final_recipe",
    ]
    assert stages[1]["pipeline_id"] == SINGLE_CORRECTION_STAGE_PIPELINE_ID


def test_stage_one_file_skips_codex_farm_when_pipeline_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

    monkeypatch.setattr(
        "cookimport.staging.import_session.run_codex_farm_recipe_pipeline",
        _fake_orchestrator,
    )
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
        run_config=RunSettings(llm_recipe_pipeline="off").to_run_config_dict(),
    )

    assert response["status"] == "success"
    assert orchestrator_called["value"] is False
