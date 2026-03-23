from __future__ import annotations

import json

from cookimport.core.models import RecipeCandidate
from cookimport.core.models import ConversionReport, ConversionResult
from cookimport.staging.draft_v1 import (
    _sanitize_staging_line,
    apply_line_role_spans_to_recipes,
    recipe_candidate_to_draft_v1,
)
from cookimport.staging.writer import write_draft_outputs


def _all_lines(draft: dict) -> list[dict]:
    lines: list[dict] = []
    for step in draft["steps"]:
        lines.extend(step.get("ingredient_lines", []))
    return lines


def test_draft_v1_uses_staging_placeholders_for_unresolved_ids() -> None:
    candidate = RecipeCandidate(
        name="Test Recipe",
        ingredients=["1 cup FLOUR"],
        instructions=["Mix flour."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)
    line = _all_lines(draft)[0]

    assert isinstance(line["ingredient_id"], str)
    assert line["ingredient_id"].strip() != ""
    assert line["input_unit_id"] is None


def test_draft_v1_downgrades_approximate_without_qty_to_unquantified() -> None:
    candidate = RecipeCandidate(
        name="Seasoning",
        ingredients=["salt, to taste"],
        instructions=["Season to taste."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)
    line = _all_lines(draft)[0]

    assert line["quantity_kind"] == "unquantified"
    assert line["input_qty"] is None
    assert line["input_unit_id"] is None


def test_draft_v1_downgrades_non_positive_qty_to_unquantified() -> None:
    candidate = RecipeCandidate(
        name="Edge Case",
        ingredients=["0"],
        instructions=["Serve."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)
    line = _all_lines(draft)[0]

    assert line["raw_text"] == "0"
    assert line["quantity_kind"] == "unquantified"
    assert line["input_qty"] is None
    assert line["input_unit_id"] is None


def test_draft_v1_never_emits_section_header_lines() -> None:
    candidate = RecipeCandidate(
        name="Header Test",
        ingredients=["FILLING", "1 cup flour"],
        instructions=["Mix flour."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    for line in _all_lines(draft):
        assert line["quantity_kind"] in {"exact", "approximate", "unquantified"}
        assert line["quantity_kind"] != "section_header"


def test_draft_v1_normalizes_blank_source_to_null() -> None:
    candidate = RecipeCandidate(
        name="Source Cleanup",
        ingredients=["salt"],
        instructions=["Mix."],
        source="   ",
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["source"] is None


def test_draft_v1_falls_back_to_untitled_title_when_blank() -> None:
    candidate = RecipeCandidate(
        name="   ",
        ingredients=["salt"],
        instructions=["Mix."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["title"] == "Untitled Recipe"


def test_draft_v1_serializes_candidate_tags_structurally() -> None:
    candidate = RecipeCandidate(
        name="Tagged Recipe",
        ingredients=["salt"],
        instructions=["Mix."],
        tags=["weeknight", "quick"],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["tags"] == ["weeknight", "quick"]
    assert draft["recipe"].get("notes") is None


def test_draft_v1_honors_explicit_ingredient_step_mapping_override() -> None:
    candidate = RecipeCandidate(
        name="Mapping Override",
        ingredients=["1 cup flour", "1 egg"],
        instructions=["Whisk the egg.", "Fold in the flour."],
    )

    draft = recipe_candidate_to_draft_v1(
        candidate,
        instruction_step_options={"instruction_step_segmentation_policy": "off"},
        ingredient_step_mapping_override={"0": [1], "1": [0]},
        ingredient_step_mapping_reason=None,
    )

    assert [line["raw_text"] for line in draft["steps"][0]["ingredient_lines"]] == ["1 egg"]
    assert [line["raw_text"] for line in draft["steps"][1]["ingredient_lines"]] == [
        "1 cup flour"
    ]


def test_sanitize_staging_line_caps_recipe_multiplier() -> None:
    line = _sanitize_staging_line(
        {
            "linked_recipe_id": "linked-recipe-123",
            "ingredient_id": "should-be-cleared",
            "quantity_kind": "exact",
            "input_qty": 150,
            "input_unit_id": "should-be-cleared",
        }
    )

    assert line is not None
    assert line["linked_recipe_id"] == "linked-recipe-123"
    assert line["ingredient_id"] is None
    assert line["input_qty"] == 100.0
    assert line["input_unit_id"] is None


def test_sanitize_staging_line_drops_blank_linked_recipe_id() -> None:
    line = _sanitize_staging_line(
        {
            "linked_recipe_id": "   ",
            "quantity_kind": "exact",
            "input_qty": 2,
            "raw_ingredient_text": "flour",
        }
    )

    assert line is not None
    assert line["linked_recipe_id"] is None
    assert line["ingredient_id"] == "flour"


def test_write_draft_outputs_writes_canonical_draft_shape(tmp_path) -> None:
    candidate = RecipeCandidate(
        name="Alias Recipe",
        ingredients=["1 cup flour", "1 egg"],
        instructions=["Mix ingredients.", "Bake until done."],
        identifier="urn:recipeimport:test:alias",
    )
    result = ConversionResult(
        recipes=[candidate],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="alias-recipe",
        workbookPath="alias-recipe.txt",
    )
    out_dir = tmp_path / "final drafts" / "alias-recipe"

    write_draft_outputs(result, out_dir)

    payload = json.loads((out_dir / "r0.json").read_text(encoding="utf-8"))
    assert payload["recipe"]["title"] == "Alias Recipe"
    assert [line["raw_text"] for line in payload["steps"][0]["ingredient_lines"]] == [
        "1 cup flour",
        "1 egg",
    ]
    assert payload["steps"][0]["instruction"] == "Gather and prepare ingredients."
    instructions_tail = " ".join(
        step["instruction"] for step in payload["steps"][1:]
    )
    assert "Mix ingredients." in instructions_tail
    assert "Bake until done." in instructions_tail


def test_write_draft_outputs_preserves_canonical_override_shape(tmp_path) -> None:
    candidate = RecipeCandidate(
        name="Ignored Name",
        ingredients=["salt"],
        instructions=["Stir."],
        identifier="urn:recipeimport:test:override",
    )
    result = ConversionResult(
        recipes=[candidate],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="override",
        workbookPath="override.txt",
    )
    out_dir = tmp_path / "final drafts" / "override"
    override_payload = {
        "schema_v": 1,
        "source": "override.txt",
        "recipe": {"title": "Override Recipe"},
        "steps": [
            {
                "instruction": "Whisk quickly.",
                "ingredient_lines": [
                    {"raw_text": "2 eggs"},
                    {"raw_text": "pinch salt"},
                ],
            }
        ],
    }

    write_draft_outputs(
        result,
        out_dir,
        draft_overrides_by_recipe_id={candidate.identifier: override_payload},
    )

    payload = json.loads((out_dir / "r0.json").read_text(encoding="utf-8"))
    assert payload["recipe"]["title"] == "Override Recipe"
    assert [line["raw_text"] for line in payload["steps"][0]["ingredient_lines"]] == [
        "2 eggs",
        "pinch salt",
    ]
    assert [step["instruction"] for step in payload["steps"]] == ["Whisk quickly."]


def test_write_draft_outputs_drops_legacy_override_aliases(tmp_path) -> None:
    candidate = RecipeCandidate(
        name="Ignored",
        ingredients=["salt"],
        instructions=["Stir."],
        identifier="urn:recipeimport:test:override-preserve",
    )
    result = ConversionResult(
        recipes=[candidate],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="override-preserve",
        workbookPath="override-preserve.txt",
    )
    out_dir = tmp_path / "final drafts" / "override-preserve"
    override_payload = {
        "schema_v": 1,
        "source": "override.txt",
        "recipe": {"title": "Derived Title"},
        "steps": [{"instruction": "Derived instruction", "ingredient_lines": []}],
        "name": "Pinned Name",
        "ingredients": ["pinned ingredient"],
        "instructions": ["Pinned instruction"],
    }

    write_draft_outputs(
        result,
        out_dir,
        draft_overrides_by_recipe_id={candidate.identifier: override_payload},
    )

    payload = json.loads((out_dir / "r0.json").read_text(encoding="utf-8"))
    assert payload["recipe"]["title"] == "Derived Title"
    assert payload["steps"] == [{"instruction": "Derived instruction", "ingredient_lines": []}]
    assert "name" not in payload
    assert "ingredients" not in payload
    assert "instructions" not in payload


def test_apply_line_role_spans_to_recipes_keeps_credible_name_when_title_lacks_boundary_evidence() -> None:
    recipe = RecipeCandidate(
        name="Chicken Soup",
        ingredients=["1 cup stock"],
        instructions=["Heat stock."],
    )
    result = ConversionResult(recipes=[recipe], report=ConversionReport())

    apply_line_role_spans_to_recipes(
        conversion_result=result,
        spans=[
            {
                "recipe_index": 0,
                "line_index": 0,
                "within_recipe_span": True,
                "label": "RECIPE_TITLE",
                "text": "SAUCES",
            },
            {
                "recipe_index": 0,
                "line_index": 1,
                "within_recipe_span": True,
                "label": "OTHER",
                "text": (
                    "I learned this in a restaurant kitchen, and this paragraph is "
                    "narrative framing rather than recipe-local structure."
                ),
            },
        ],
    )

    assert recipe.name == "Chicken Soup"


def test_apply_line_role_spans_to_recipes_promotes_boundary_supported_title() -> None:
    recipe = RecipeCandidate(
        name="Untitled Recipe",
        ingredients=[],
        instructions=[],
    )
    result = ConversionResult(recipes=[recipe], report=ConversionReport())

    apply_line_role_spans_to_recipes(
        conversion_result=result,
        spans=[
            {
                "recipe_index": 0,
                "line_index": 0,
                "within_recipe_span": True,
                "label": "RECIPE_TITLE",
                "text": "PAN-SEARED SALMON",
            },
            {
                "recipe_index": 0,
                "line_index": 1,
                "within_recipe_span": True,
                "label": "YIELD_LINE",
                "text": "Serves 4",
            },
            {
                "recipe_index": 0,
                "line_index": 2,
                "within_recipe_span": True,
                "label": "INGREDIENT_LINE",
                "text": "2 salmon fillets",
            },
            {
                "recipe_index": 0,
                "line_index": 3,
                "within_recipe_span": True,
                "label": "INSTRUCTION_LINE",
                "text": "Heat oil in a skillet.",
            },
        ],
    )

    assert recipe.name == "PAN-SEARED SALMON"
