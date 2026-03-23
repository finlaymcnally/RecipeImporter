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
            "v": "1",
            "sid": payload.get("sid"),
            "r": [
                {
                    "v": "1",
                    "rid": payload["r"][0]["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": "Toast",
                        "i": ["1 slice bread"],
                        "s": ["Toast the bread."],
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": "not_needed_single_step",
                    "g": [
                        {
                            "c": "meal",
                            "l": "breakfast",
                            "f": 0.8,
                        }
                    ],
                    "w": [],
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
