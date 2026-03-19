from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact, RecipeCandidate
from cookimport.llm.codex_farm_orchestrator import (
    SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    SINGLE_CORRECTION_STAGE_PIPELINE_ID,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner


def _build_lines_only_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 3}},
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
                    "lines": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                    ],
                },
                metadata={"artifact_type": "extracted_lines"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def test_orchestrator_accepts_full_text_lines_when_blocks_missing(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "bundle_version": "1",
            "shard_id": payload.get("sid"),
            "recipes": [
                {
                    "bundle_version": "1",
                    "recipe_id": payload["r"][0]["rid"],
                    "repair_status": "repaired",
                    "status_reason": None,
                    "canonical_recipe": {
                        "title": "Toast",
                        "ingredients": ["1 slice bread"],
                        "steps": ["Toast the bread."],
                        "description": None,
                        "recipeYield": None,
                    },
                    "ingredient_step_mapping": [],
                    "ingredient_step_mapping_reason": "not_needed_single_step",
                    "selected_tags": [
                        {
                            "category": "meal",
                            "label": "breakfast",
                            "confidence": 0.8,
                        }
                    ],
                    "warnings": [],
                }
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_lines_only_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["counts"]["recipe_shards_total"] == 1
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert manifest["counts"]["build_final_recipe_ok"] == 1
