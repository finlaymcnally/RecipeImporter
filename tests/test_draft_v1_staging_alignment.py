from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1


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
