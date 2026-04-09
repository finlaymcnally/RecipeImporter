from __future__ import annotations

from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.llm.recipe_stage_shared import (
    CodexFarmApplyResult,
    SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
)
from cookimport.parsing.label_source_of_truth import LabelFirstStageResult
from cookimport.staging.pipeline_runtime import (
    ExtractedBookBundle,
    RecipeBoundaryResult,
    run_recipe_refine_stage,
)
from cookimport.staging.recipe_authority_decisions import (
    RecipeAuthorityDecision,
    classify_recipe_ownership_action,
)
from cookimport.staging.recipe_ownership import RecipeDivestment
from tests.nonrecipe_stage_helpers import make_recipe_ownership_result


def _recipe(recipe_id: str) -> RecipeCandidate:
    return RecipeCandidate(
        name="Toast",
        identifier=recipe_id,
        recipeIngredient=["1 slice bread"],
        recipeInstructions=["Toast the bread."],
        provenance={"location": {"start_block": 0, "end_block": 1}},
    )


def test_run_recipe_refine_stage_applies_llm_recipe_divestments(monkeypatch, tmp_path: Path) -> None:
    recipe_id = "urn:recipe:test:toast"
    boundary_conversion = ConversionResult(
        recipes=[_recipe(recipe_id)],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(tmp_path / "book.txt"),
    )
    archive_blocks = [
        {"index": 0, "block_id": "b0", "text": "Toast"},
        {"index": 1, "block_id": "b1", "text": "1 slice bread"},
        {"index": 2, "block_id": "b2", "text": "Technique note"},
    ]
    boundary_result = RecipeBoundaryResult(
        extracted_bundle=ExtractedBookBundle(
            source_file=tmp_path / "book.txt",
            workbook_slug="book",
            importer_name="text",
            source_hash="hash-123",
            conversion_result=boundary_conversion,
            source_blocks=[],
            source_support=[],
            archive_blocks=archive_blocks,
        ),
        label_first_result=LabelFirstStageResult(
            updated_conversion_result=boundary_conversion,
            archive_blocks=archive_blocks,
        ),
        conversion_result=boundary_conversion,
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={recipe_id: [0, 1]},
            all_block_indices=[0, 1, 2],
            ownership_mode="recipe_boundary",
        ),
        recipe_owned_blocks=archive_blocks[:2],
        outside_recipe_blocks=[archive_blocks[2]],
    )

    refined_conversion = boundary_conversion.model_copy(deep=True)
    refined_conversion.recipes = []

    def _fake_recipe_pipeline(**_kwargs) -> CodexFarmApplyResult:
        return CodexFarmApplyResult(
            updated_conversion_result=refined_conversion,
            authoritative_recipe_payloads_by_recipe_id={},
            recipe_evidence_payloads_by_recipe_id={},
            recipe_authority_decisions_by_recipe_id={},
            llm_report={"enabled": True, "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID},
            llm_raw_dir=tmp_path / "raw" / "llm" / "book",
            recipe_divestments=[
                RecipeDivestment(
                    recipe_id=recipe_id,
                    block_indices=[0, 1],
                    reason="not_a_recipe",
                )
            ],
        )

    monkeypatch.setattr(
        "cookimport.staging.pipeline_runtime.run_codex_farm_recipe_pipeline",
        _fake_recipe_pipeline,
    )

    result = run_recipe_refine_stage(
        recipe_boundary_result=boundary_result,
        run_settings=RunSettings.from_dict(
            {"llm_recipe_pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID},
            warn_context="test",
        ),
        run_root=tmp_path / "run",
    )

    assert result.conversion_result.recipes == []
    assert result.recipe_ownership_result.owned_block_indices == []
    assert result.recipe_ownership_result.divested_block_indices == [0, 1]
    assert result.recipe_ownership_result.available_to_nonrecipe_block_indices == [0, 1, 2]


def test_run_recipe_refine_stage_keeps_fragmentary_recipe_owned_when_not_divested(
    monkeypatch,
    tmp_path: Path,
) -> None:
    recipe_id = "urn:recipe:test:toast"
    boundary_conversion = ConversionResult(
        recipes=[_recipe(recipe_id)],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(tmp_path / "book.txt"),
    )
    archive_blocks = [
        {"index": 0, "block_id": "b0", "text": "Toast"},
        {"index": 1, "block_id": "b1", "text": "1 slice bread"},
        {"index": 2, "block_id": "b2", "text": "Toast the bread."},
    ]
    boundary_result = RecipeBoundaryResult(
        extracted_bundle=ExtractedBookBundle(
            source_file=tmp_path / "book.txt",
            workbook_slug="book",
            importer_name="text",
            source_hash="hash-123",
            conversion_result=boundary_conversion,
            source_blocks=[],
            source_support=[],
            archive_blocks=archive_blocks,
        ),
        label_first_result=LabelFirstStageResult(
            updated_conversion_result=boundary_conversion,
            archive_blocks=archive_blocks,
        ),
        conversion_result=boundary_conversion,
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={recipe_id: [0, 1, 2]},
            all_block_indices=[0, 1, 2],
            ownership_mode="recipe_boundary",
        ),
        recipe_owned_blocks=archive_blocks,
        outside_recipe_blocks=[],
    )

    def _fake_recipe_pipeline(**_kwargs) -> CodexFarmApplyResult:
        return CodexFarmApplyResult(
            updated_conversion_result=boundary_conversion.model_copy(update={"recipes": []}, deep=True),
            authoritative_recipe_payloads_by_recipe_id={},
            recipe_evidence_payloads_by_recipe_id={},
            recipe_authority_decisions_by_recipe_id={
                recipe_id: RecipeAuthorityDecision(
                    recipe_id=recipe_id,
                    semantic_outcome="partial_recipe",
                    publish_status="withheld_partial",
                    ownership_action="retain",
                    owned_block_indices=[0, 1, 2],
                    divested_block_indices=[],
                    retained_block_indices=[0, 1, 2],
                    worker_repair_status="fragmentary",
                    final_recipe_authority_status="not_promoted",
                    final_recipe_authority_reason="valid_task_outcome_fragmentary",
                )
            },
            llm_report={"enabled": True, "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID},
            llm_raw_dir=tmp_path / "raw" / "llm" / "book",
            recipe_divestments=[],
        )

    monkeypatch.setattr(
        "cookimport.staging.pipeline_runtime.run_codex_farm_recipe_pipeline",
        _fake_recipe_pipeline,
    )

    result = run_recipe_refine_stage(
        recipe_boundary_result=boundary_result,
        run_settings=RunSettings.from_dict(
            {"llm_recipe_pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID},
            warn_context="test",
        ),
        run_root=tmp_path / "run",
    )

    assert result.conversion_result.recipes == []
    assert result.recipe_ownership_result.owned_block_indices == [0, 1, 2]
    assert result.recipe_ownership_result.divested_block_indices == []
    assert result.recipe_authority_decisions_by_recipe_id[recipe_id].publish_status == (
        "withheld_partial"
    )


def test_classify_recipe_ownership_action_marks_full_divestment_when_all_owned_blocks_divested() -> None:
    assert (
        classify_recipe_ownership_action(
            owned_block_indices=[10, 11, 12],
            divested_block_indices=[10, 11, 12],
        )
        == "fully_divested"
    )
    assert (
        classify_recipe_ownership_action(
            owned_block_indices=[10, 11, 12],
            divested_block_indices=[10, 12],
        )
        == "partially_divested"
    )
    assert (
        classify_recipe_ownership_action(
            owned_block_indices=[10, 11, 12],
            divested_block_indices=[],
        )
        == "retain"
    )
