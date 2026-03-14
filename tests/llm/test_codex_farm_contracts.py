from __future__ import annotations

import pytest
from pydantic import ValidationError

from cookimport.llm.codex_farm_contracts import (
    Pass1RecipeChunkingInput,
    Pass2SchemaOrgCompactInput,
    Pass2SchemaOrgOutput,
    Pass3FinalDraftCompactInput,
    Pass3FinalDraftInput,
    Pass3FinalDraftOutput,
    classify_pass2_structural_audit,
    classify_pass3_structural_audit,
)


def test_pass1_contract_accepts_required_nullable_fields() -> None:
    payload = Pass1RecipeChunkingInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "heuristic_start_block_index": None,
            "heuristic_end_block_index": None,
            "blocks_before": [],
            "blocks_candidate": [],
            "blocks_after": [],
        }
    )
    assert payload.heuristic_start_block_index is None
    assert payload.heuristic_end_block_index is None


def test_pass1_contract_pattern_hints_are_strict() -> None:
    payload = Pass1RecipeChunkingInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "heuristic_start_block_index": 10,
            "heuristic_end_block_index": 20,
            "blocks_before": [],
            "blocks_candidate": [],
            "blocks_after": [],
            "pattern_hints": [
                {
                    "hint_type": "duplicate_title_intro",
                    "start_block_index": 10,
                    "end_block_index": 14,
                    "note": "deterministic action: trim_candidate_start",
                }
            ],
        }
    )
    assert payload.pattern_hints
    assert payload.pattern_hints[0].hint_type == "duplicate_title_intro"

    with pytest.raises(ValidationError):
        Pass1RecipeChunkingInput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "workbook_slug": "book",
                "source_hash": "hash",
                "heuristic_start_block_index": 10,
                "heuristic_end_block_index": 20,
                "blocks_before": [],
                "blocks_candidate": [],
                "blocks_after": [],
                "pattern_hints": [
                    {
                        "hint_type": "toc_like_cluster",
                        "unexpected": "extra-key-not-allowed",
                    }
                ],
            }
        )


def test_pass3_contract_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Pass3FinalDraftOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "draft_v1": {"schema_v": 1},
            }
        )


def test_pass2_contract_accepts_json_string_fields() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": "{\"@type\":\"Recipe\",\"name\":\"T\"}",
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": "{\"name\":\"from_text\"}",
            "warnings": [],
        }
    )
    assert output.schemaorg_recipe == {"@type": "Recipe", "name": "T"}
    assert output.field_evidence == {"name": "from_text"}


def test_pass2_contract_recovers_malformed_field_evidence_into_warning() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": {"@type": "Recipe", "name": "Toast"},
            "extracted_ingredients": ["1 slice bread"],
            "extracted_instructions": ["Toast the bread."],
            "field_evidence": "{bad json",
            "warnings": [],
        }
    )

    assert output.field_evidence == {}
    assert output.warnings == [
        "pass2 recovered malformed field_evidence; replaced with empty object."
    ]


def test_pass2_contract_sanitizes_corrupted_extractive_arrays_but_keeps_unicode() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": {"@type": "Recipe", "name": "Toast"},
            "extracted_ingredients": ["1 jalapeño\x00 pepper"],
            "extracted_instructions": ["Stir\x00 gently."],
            "field_evidence": "{}",
            "warnings": [],
        }
    )

    assert output.extracted_ingredients == ["1 jalapeño pepper"]
    assert output.extracted_instructions == ["Stir gently."]


def test_pass3_contract_accepts_json_string_fields() -> None:
    output = Pass3FinalDraftOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "draft_v1": "{\"schema_v\":1,\"recipe\":{\"title\":\"T\"},\"steps\":[]}",
            "ingredient_step_mapping": "{}",
            "warnings": [],
        }
    )
    assert output.draft_v1 == {"schema_v": 1, "recipe": {"title": "T"}, "steps": []}
    assert output.ingredient_step_mapping == {}


def test_pass3_contract_accepts_empty_mapping_reason() -> None:
    output = Pass3FinalDraftOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "draft_v1": "{\"schema_v\":1,\"recipe\":{\"title\":\"T\"},\"steps\":[]}",
            "ingredient_step_mapping": "{}",
            "ingredient_step_mapping_reason": "unclear_alignment",
            "warnings": [],
        }
    )

    assert output.ingredient_step_mapping == {}
    assert output.ingredient_step_mapping_reason == "unclear_alignment"


def test_pass3_input_accepts_json_string_schemaorg() -> None:
    payload = Pass3FinalDraftInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "schemaorg_recipe": "{\"name\":\"T\"}",
            "extracted_ingredients": [],
            "extracted_instructions": [],
        }
    )
    assert payload.schemaorg_recipe == {"name": "T"}


def test_pass2_compact_input_uses_evidence_rows_only() -> None:
    payload = Pass2SchemaOrgCompactInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "evidence_rows": [[3, "Dish Title"], [4, "1 cup flour"]],
        }
    )
    assert payload.evidence_rows == [(3, "Dish Title"), (4, "1 cup flour")]

    with pytest.raises(ValidationError):
        Pass2SchemaOrgCompactInput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "workbook_slug": "book",
                "source_hash": "hash",
                "evidence_rows": [],
                "canonical_text": "legacy field should be rejected",
            }
        )


def test_pass3_compact_input_accepts_json_string_recipe_metadata() -> None:
    payload = Pass3FinalDraftCompactInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "recipe_metadata": "{\"name\":\"Toast\",\"recipeYield\":\"2 servings\"}",
            "extracted_ingredients": ["1 slice bread"],
            "extracted_instructions": ["Toast the bread."],
        }
    )
    assert payload.recipe_metadata == {"name": "Toast", "recipeYield": "2 servings"}


def test_pass2_contract_repairs_mismatched_json_closers() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": (
                '{"@type":"Recipe","name":"T","recipeInstructions":["step 1","step 2"}'
            ),
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": "{}",
            "warnings": [],
        }
    )
    assert output.schemaorg_recipe["name"] == "T"
    assert output.schemaorg_recipe["recipeInstructions"] == ["step 1", "step 2"]


def test_pass2_contract_repairs_control_char_and_null_hex_artifacts() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": (
                '{"@type":"Recipe","name":"saut\x00e9","description":"line one\nline two"}'
            ),
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": "{}",
            "warnings": [],
        }
    )
    assert output.schemaorg_recipe["name"] == "sauté"
    assert output.schemaorg_recipe["description"] == "line one line two"


def test_pass2_contract_extracts_embedded_json_object() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": "note: {\"@type\":\"Recipe\",\"name\":\"T\"} trailing",
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": "{}",
            "warnings": [],
        }
    )
    assert output.schemaorg_recipe == {"@type": "Recipe", "name": "T"}


def test_pass3_contract_repairs_truncated_draft_json_string() -> None:
    output = Pass3FinalDraftOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "draft_v1": (
                '{"schema_v":1,"recipe":{"title":"T"},'
                '"steps":[{"instruction":"Step 1","ingredient_lines":[]}'
            ),
            "ingredient_step_mapping": "{}",
            "warnings": [],
        }
    )
    assert output.draft_v1["recipe"]["title"] == "T"
    assert output.draft_v1["steps"] == [{"instruction": "Step 1", "ingredient_lines": []}]


def test_pass2_structural_audit_flags_placeholder_title_and_extractive_mismatch() -> None:
    output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": {"@type": "Recipe", "name": "Untitled Recipe"},
            "extracted_ingredients": ["1 slice bread"],
            "extracted_instructions": ["Toast the bread."],
            "field_evidence": {},
            "warnings": [],
        }
    )

    audit = classify_pass2_structural_audit(
        output=output,
        guard_warnings=[
            "pass2 instruction[0] not found in canonical_text: 'Toast the bread.'"
        ],
        transport_verification={"status": "ok", "reason_codes": []},
    )

    assert audit.status == "failed"
    assert audit.severity == "hard"
    assert audit.reason_codes == [
        "placeholder_title",
        "extractive_text_not_in_transport_span",
    ]


def test_pass3_structural_audit_flags_empty_mapping_without_reason() -> None:
    pass2_output = Pass2SchemaOrgOutput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "schemaorg_recipe": {"@type": "Recipe", "name": "Toast"},
            "extracted_ingredients": ["1 slice bread", "1 tbsp butter"],
            "extracted_instructions": ["Toast the bread.", "Butter the toast."],
            "field_evidence": {},
            "warnings": [],
        }
    )

    audit = classify_pass3_structural_audit(
        draft_payload={
            "schema_v": 1,
            "recipe": {"title": "Toast"},
            "steps": [
                {"instruction": "Toast the bread.", "ingredient_lines": []},
                {"instruction": "Butter the toast.", "ingredient_lines": []},
            ],
        },
        pass2_output=pass2_output,
        ingredient_step_mapping={},
        ingredient_step_mapping_reason=None,
        pass2_reason_codes=[],
    )

    assert audit.status == "failed"
    assert audit.severity == "hard"
    assert audit.reason_codes == ["empty_mapping_without_reason"]
