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
                "version": "recipe_tagging_guide.v1",
                "categories": [{"key": "meal", "examples": ["breakfast"]}],
            },
            "authority_notes": ["authoritative_source=recipe_span_blocks"],
        }
    )

    assert payload.tagging_guide["version"] == "recipe_tagging_guide.v1"


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
            "selected_tags": [],
            "warnings": [],
        }
    )

    assert output.ingredient_step_mapping == {"0": [0], "1": [0, 1]}


def test_merged_repair_output_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        MergedRecipeRepairOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "canonical_recipe": {"title": "Toast"},
            }
        )


def test_recipe_correction_shard_input_accepts_multi_recipe_payload() -> None:
    payload = RecipeCorrectionShardInput.model_validate(
        {
            "bundle_version": "1",
            "shard_id": "recipe-shard-0000-r0000-r0001",
            "workbook_slug": "book",
            "source_hash": "hash",
            "owned_recipe_ids": ["urn:recipe:test:1", "urn:recipe:test:2"],
            "recipes": [
                {
                    "recipe_id": "urn:recipe:test:1",
                    "canonical_text": "Toast",
                    "evidence_rows": [[1, "Toast"]],
                    "recipe_candidate_hint": {"name": "Toast"},
                    "warnings": [],
                },
                {
                    "recipe_id": "urn:recipe:test:2",
                    "canonical_text": "Tea",
                    "evidence_rows": [[2, "Tea"]],
                    "recipe_candidate_hint": {"name": "Tea"},
                    "warnings": ["sparse_evidence"],
                },
            ],
            "tagging_guide": {"version": "recipe_tagging_guide.v1"},
            "authority_notes": ["preserve_owned_recipe_ids_exactly"],
        }
    )

    serialized = serialize_recipe_correction_shard_input(payload)

    assert payload.recipes[1].warnings == ["sparse_evidence"]
    assert serialized["owned_recipe_ids"] == ["urn:recipe:test:1", "urn:recipe:test:2"]


def test_recipe_correction_shard_output_accepts_nested_recipe_outputs() -> None:
    output = RecipeCorrectionShardOutput.model_validate(
        {
            "bundle_version": "1",
            "shard_id": "recipe-shard-0000-r0000-r0001",
            "recipes": [
                {
                    "bundle_version": "1",
                    "recipe_id": "urn:recipe:test:1",
                    "canonical_recipe": {
                        "title": "Toast",
                        "ingredients": ["1 slice bread"],
                        "steps": ["Toast the bread."],
                        "description": None,
                        "recipeYield": None,
                    },
                    "ingredient_step_mapping": {"0": [0]},
                    "ingredient_step_mapping_reason": None,
                    "selected_tags": [],
                    "warnings": [],
                }
            ],
        }
    )

    assert output.shard_id == "recipe-shard-0000-r0000-r0001"
    assert output.recipes[0].recipe_id == "urn:recipe:test:1"


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
  "selected_tags": [],
  "warnings": []
}
""",
        encoding="utf-8",
    )

    output = load_contract_json(path, MergedRecipeRepairOutput)

    assert output.canonical_recipe.steps == ["Toast the bread."]
