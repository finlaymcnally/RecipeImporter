from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import _sanitize_staging_line, recipe_candidate_to_draft_v1


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
