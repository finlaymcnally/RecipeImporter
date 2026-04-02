from __future__ import annotations

import pytest
from pydantic import ValidationError

from cookimport.llm.codex_farm_contracts import (
    MergedRecipeRepairInput,
    MergedRecipeRepairOutput,
    RecipeCorrectionShardInput,
    RecipeCorrectionShardOutput,
    load_contract_json,
    serialize_merged_recipe_repair_input,
    serialize_recipe_correction_shard_input,
)


def test_merged_recipe_repair_input_accepts_missing_draft_hint() -> None:
    payload = MergedRecipeRepairInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "canonical_text": "Toast\n1 slice bread",
            "evidence_rows": [[1, "Toast"], [2, "1 slice bread"]],
            "recipe_candidate_hint": {"name": "Toast"},
            "authority_notes": ["authoritative_source=recipe_span_blocks"],
        }
    )

    assert payload.draft_hint == {}


def test_serialize_merged_recipe_repair_input_omits_empty_draft_hint() -> None:
    payload = MergedRecipeRepairInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "canonical_text": "Toast\n1 slice bread",
            "evidence_rows": [[1, "Toast"], [2, "1 slice bread"]],
            "recipe_candidate_hint": {"name": "Toast"},
            "authority_notes": ["authoritative_source=recipe_span_blocks"],
        }
    )

    serialized = serialize_merged_recipe_repair_input(payload)

    assert "draft_hint" not in serialized


def test_merged_recipe_repair_input_accepts_tagging_guide_object() -> None:
    payload = MergedRecipeRepairInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "canonical_text": "Toast\n1 slice bread",
            "evidence_rows": [[1, "Toast"], [2, "1 slice bread"]],
            "recipe_candidate_hint": {"name": "Toast"},
            "tagging_guide": {
                "v": "recipe_tagging_guide.v2",
                "c": [{"k": "meal", "x": ["breakfast"]}],
            },
            "authority_notes": ["authoritative_source=recipe_span_blocks"],
        }
    )

    assert payload.tagging_guide["v"] == "recipe_tagging_guide.v2"


def test_merged_repair_output_accepts_native_object_fields() -> None:
    output = MergedRecipeRepairOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "canonical_recipe": {
                "title": "Toast",
                "ingredients": ["1 slice bread"],
                "steps": ["Toast the bread."],
                "description": None,
                "recipeYield": None,
            },
            "ingredient_step_mapping": {"0": [0]},
            "ingredient_step_mapping_reason": None,
            "divested_block_indices": [],
            "selected_tags": [
                {"category": "meal", "label": "breakfast", "confidence": 0.92}
            ],
            "warnings": [],
        }
    )

    assert output.canonical_recipe.title == "Toast"
    assert output.ingredient_step_mapping == {"0": [0]}
    assert output.selected_tags[0].label == "breakfast"


def test_merged_repair_output_accepts_mapping_entry_arrays() -> None:
    output = MergedRecipeRepairOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "canonical_recipe": {
                "title": "Toast",
                "ingredients": ["1 slice bread"],
                "steps": ["Toast the bread."],
                "description": None,
                "recipeYield": None,
            },
            "ingredient_step_mapping": [
                {"ingredient_index": 0, "step_indexes": [0]},
                {"ingredient_index": 1, "step_indexes": [0, 1]},
            ],
            "ingredient_step_mapping_reason": None,
            "divested_block_indices": [],
            "selected_tags": [],
            "warnings": [],
        }
    )

    assert output.ingredient_step_mapping == {"0": [0], "1": [0, 1]}


def test_merged_repair_output_rejects_complex_empty_mapping_without_reason() -> None:
    with pytest.raises(ValidationError, match="ingredient_step_mapping_reason is required"):
        MergedRecipeRepairOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "repair_status": "repaired",
                "canonical_recipe": {
                    "title": "Toast",
                    "ingredients": ["1 slice bread", "1 tablespoon butter"],
                    "steps": ["Toast the bread.", "Spread with butter."],
                    "description": None,
                    "recipeYield": None,
                },
                "ingredient_step_mapping": [],
                "ingredient_step_mapping_reason": None,
                "divested_block_indices": [],
                "selected_tags": [],
                "warnings": [],
            }
        )


def test_merged_repair_output_accepts_single_step_empty_mapping_with_reason() -> None:
    output = MergedRecipeRepairOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "repair_status": "repaired",
            "canonical_recipe": {
                "title": "Toast",
                "ingredients": ["1 slice bread", "1 tablespoon butter"],
                "steps": ["Toast the bread and spread with butter."],
                "description": None,
                "recipeYield": None,
            },
            "ingredient_step_mapping": [],
            "ingredient_step_mapping_reason": "not_needed_single_step",
            "divested_block_indices": [],
            "selected_tags": [],
            "warnings": [],
        }
    )

    assert output.ingredient_step_mapping == {}
    assert output.ingredient_step_mapping_reason == "not_needed_single_step"


def test_merged_repair_output_rejects_multi_ingredient_single_step_empty_mapping_without_reason() -> None:
    with pytest.raises(ValidationError, match="ingredient_step_mapping_reason is required"):
        MergedRecipeRepairOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "repair_status": "repaired",
                "canonical_recipe": {
                    "title": "Blue Cheese Dressing",
                    "ingredients": [
                        "5 ounces blue cheese",
                        "1/2 cup creme fraiche",
                        "1 tablespoon vinegar",
                    ],
                    "steps": [
                        "Whisk everything together. Taste and adjust. Chill before serving."
                    ],
                    "description": None,
                    "recipeYield": None,
                },
                "ingredient_step_mapping": [],
                "ingredient_step_mapping_reason": None,
                "divested_block_indices": [],
                "selected_tags": [],
                "warnings": [],
            }
        )


def test_merged_repair_output_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        MergedRecipeRepairOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "canonical_recipe": {"title": "Toast"},
                "divested_block_indices": [],
            }
        )


def test_recipe_correction_shard_input_accepts_multi_recipe_payload() -> None:
    payload = RecipeCorrectionShardInput.model_validate(
        {
            "bundle_version": "1",
            "shard_id": "recipe-shard-0000-r0000-r0001",
            "owned_recipe_ids": ["urn:recipe:test:1", "urn:recipe:test:2"],
            "recipes": [
                {
                    "recipe_id": "urn:recipe:test:1",
                    "canonical_text": "Toast",
                    "evidence_rows": [[1, "Toast"]],
                    "recipe_candidate_hint": {"n": "Toast"},
                    "candidate_quality_hint": {
                        "evidence_row_count": 1,
                        "evidence_ingredient_count": 0,
                        "evidence_step_count": 0,
                        "hint_ingredient_count": 0,
                        "hint_step_count": 0,
                        "suspicion_flags": ["short_span"],
                    },
                    "warnings": [],
                },
                {
                    "recipe_id": "urn:recipe:test:2",
                    "canonical_text": "Tea",
                    "evidence_rows": [[2, "Tea"]],
                    "recipe_candidate_hint": {"n": "Tea"},
                    "candidate_quality_hint": {
                        "evidence_row_count": 1,
                        "evidence_ingredient_count": 0,
                        "evidence_step_count": 0,
                        "hint_ingredient_count": 0,
                        "hint_step_count": 0,
                        "suspicion_flags": ["short_span"],
                    },
                    "warnings": ["sparse_evidence"],
                },
            ],
            "tagging_guide": {"v": "recipe_tagging_guide.v2"},
        }
    )

    serialized = serialize_recipe_correction_shard_input(payload)

    assert payload.recipes[1].warnings == ["sparse_evidence"]
    assert payload.recipes[0].candidate_quality_hint.suspicion_flags == ["short_span"]
    assert serialized["ids"] == ["urn:recipe:test:1", "urn:recipe:test:2"]
    assert serialized["r"][0]["q"]["f"] == ["short_span"]


def test_recipe_correction_shard_output_accepts_nested_recipe_outputs() -> None:
    output = RecipeCorrectionShardOutput.model_validate(
        {
            "bundle_version": "1",
            "shard_id": "recipe-shard-0000-r0000-r0001",
            "recipes": [
                {
                    "bundle_version": "1",
                    "recipe_id": "urn:recipe:test:1",
                    "repair_status": "repaired",
                    "status_reason": None,
                    "canonical_recipe": {
                        "title": "Toast",
                        "ingredients": ["1 slice bread"],
                        "steps": ["Toast the bread."],
                        "description": None,
                        "recipeYield": None,
                    },
                    "ingredient_step_mapping": {"0": [0]},
                    "ingredient_step_mapping_reason": None,
                    "divested_block_indices": [],
                    "selected_tags": [],
                    "warnings": [],
                }
            ],
        }
    )

    assert output.shard_id == "recipe-shard-0000-r0000-r0001"
    assert output.recipes[0].recipe_id == "urn:recipe:test:1"
    assert output.recipes[0].repair_status == "repaired"


def test_recipe_correction_shard_output_accepts_explicit_not_a_recipe_status() -> None:
    output = RecipeCorrectionShardOutput.model_validate(
        {
            "bundle_version": "1",
            "shard_id": "recipe-shard-0000-r0000-r0001",
            "recipes": [
                {
                    "bundle_version": "1",
                    "recipe_id": "urn:recipe:test:1",
                    "repair_status": "not_a_recipe",
                    "status_reason": "chapter_heading",
                    "canonical_recipe": None,
                    "ingredient_step_mapping": [],
                    "ingredient_step_mapping_reason": "not_applicable_not_a_recipe",
                    "divested_block_indices": [1],
                    "selected_tags": [],
                    "warnings": ["candidate_rejected"],
                }
            ],
        }
    )

    assert output.recipes[0].repair_status == "not_a_recipe"
    assert output.recipes[0].canonical_recipe is None
    assert output.recipes[0].status_reason == "chapter_heading"


def test_recipe_correction_shard_output_rejects_unknown_repair_status() -> None:
    with pytest.raises(ValidationError):
        RecipeCorrectionShardOutput.model_validate(
            {
                "bundle_version": "1",
                "shard_id": "recipe-shard-0000-r0000-r0001",
                "recipes": [
                    {
                        "bundle_version": "1",
                        "recipe_id": "urn:recipe:test:1",
                        "repair_status": "maybe_recipe",
                        "status_reason": None,
                        "canonical_recipe": None,
                        "ingredient_step_mapping": [],
                        "ingredient_step_mapping_reason": "unknown",
                        "divested_block_indices": [],
                        "selected_tags": [],
                        "warnings": [],
                    }
                ],
            }
        )


def test_load_contract_json_validates_against_model(tmp_path) -> None:
    path = tmp_path / "payload.json"
    path.write_text(
        """{
  "bundle_version": "1",
  "recipe_id": "urn:recipe:test",
  "canonical_recipe": {
    "title": "Toast",
    "ingredients": ["1 slice bread"],
    "steps": ["Toast the bread."],
    "description": null,
    "recipeYield": null
  },
  "ingredient_step_mapping": {"0": [0]},
  "ingredient_step_mapping_reason": null,
  "divested_block_indices": [],
  "selected_tags": [],
  "warnings": []
}
""",
        encoding="utf-8",
    )

    output = load_contract_json(path, MergedRecipeRepairOutput)

    assert output.canonical_recipe.steps == ["Toast the bread."]
