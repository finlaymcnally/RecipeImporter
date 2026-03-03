from __future__ import annotations

import json
from pathlib import Path

from cookimport.parsing.recipe_block_atomizer import atomize_blocks
from tests.paths import FIXTURES_DIR


def _load_fixture(name: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "canonical_labeling" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_atomize_hollandaise_merged_block_into_atomic_candidates() -> None:
    payload = _load_fixture("hollandaise_merged_block.json")
    recipe_id = str(payload.get("recipe_id") or "")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)

    candidates = atomize_blocks(
        blocks,
        recipe_id=recipe_id,
        within_recipe_span=True,
    )

    by_text = {candidate.text: candidate for candidate in candidates}
    assert "NOTE: Keep blender cup warm." in by_text
    assert "MAKES ABOUT 1 CUP" in by_text
    assert "3 large egg yolks" in by_text
    assert "1 tablespoon lemon juice" in by_text
    assert "1 stick unsalted butter, melted" in by_text
    assert "Kosher salt." in by_text
    assert "TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER" in by_text

    assert by_text["NOTE: Keep blender cup warm."].candidate_labels[0] == "RECIPE_NOTES"
    assert by_text["MAKES ABOUT 1 CUP"].candidate_labels[0] == "YIELD_LINE"
    assert by_text["3 large egg yolks"].candidate_labels[0] == "INGREDIENT_LINE"
    assert by_text["1 tablespoon lemon juice"].candidate_labels[0] == "INGREDIENT_LINE"
    assert by_text["1 stick unsalted butter, melted"].candidate_labels[0] == "INGREDIENT_LINE"
    assert by_text["Kosher salt."].candidate_labels[0] == "INGREDIENT_LINE"
    assert (
        by_text["TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER"].candidate_labels[0]
        == "HOWTO_SECTION"
    )

    for index, candidate in enumerate(candidates):
        assert candidate.atomic_index == index


def test_atomize_range_ingredient_not_yield() -> None:
    payload = _load_fixture("ingredient_vs_yield_ranges.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)

    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    by_text = {candidate.text: candidate for candidate in candidates}

    assert by_text["SERVES 4"].candidate_labels[0] == "YIELD_LINE"
    assert by_text["4 to 6 chicken leg quarters"].candidate_labels[0] == "INGREDIENT_LINE"
    assert by_text["2 tablespoons olive oil"].candidate_labels[0] == "INGREDIENT_LINE"


def test_atomize_omelet_variant_fixture() -> None:
    payload = _load_fixture("omelet_variant_lines.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)

    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    by_text = {candidate.text: candidate for candidate in candidates}

    assert (
        by_text["DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET"].candidate_labels[0]
        == "RECIPE_VARIANT"
    )
    assert by_text["3 tablespoons whole milk"].candidate_labels[0] == "INGREDIENT_LINE"
    assert (
        by_text["1. Whisk eggs with milk and season with salt."].candidate_labels[0]
        == "INSTRUCTION_LINE"
    )


def test_atomize_inline_numbered_steps_into_multiple_instruction_candidates() -> None:
    payload = _load_fixture("braised_chicken_tail_steps.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)

    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )

    texts = [candidate.text for candidate in candidates]
    assert texts == [
        "1. Brown chicken skin-side down.",
        "2. Add onions and cook until soft.",
        "3. Cover and braise for 45 minutes.",
    ]
    assert all(candidate.candidate_labels[0] == "INSTRUCTION_LINE" for candidate in candidates)
