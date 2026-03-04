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


def test_atomize_marks_explicit_prose_tag_for_fallback_paragraphs() -> None:
    outside_candidates = atomize_blocks(
        [
            {
                "block_id": "block:outside:1",
                "block_index": 1,
                "text": (
                    "Copper pans conduct heat quickly and evenly, so even small burner "
                    "changes show up immediately across the pan"
                ),
            }
        ],
        recipe_id=None,
        within_recipe_span=False,
    )
    assert len(outside_candidates) == 1
    assert outside_candidates[0].candidate_labels[0] == "KNOWLEDGE"
    assert "explicit_prose" in outside_candidates[0].rule_tags

    inside_candidates = atomize_blocks(
        [
            {
                "block_id": "block:inside:1",
                "block_index": 1,
                "text": (
                    "A long explanatory paragraph appears here, with narrative context "
                    "about texture and flavor choices rather than direct action"
                ),
            }
        ],
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    assert len(inside_candidates) == 1
    assert inside_candidates[0].candidate_labels[0] == "OTHER"
    assert "explicit_prose" in inside_candidates[0].rule_tags


def test_atomize_title_like_line_offers_recipe_title_candidate_inside_recipe() -> None:
    candidates = atomize_blocks(
        [
            {
                "block_id": "block:title:inside",
                "block_index": 4,
                "text": "A PORRIDGE OF LOVAGE STEMS",
            }
        ],
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    assert len(candidates) == 1
    assert candidates[0].candidate_labels[0] == "RECIPE_TITLE"
    assert "title_like" in candidates[0].rule_tags


def test_atomize_note_like_prose_not_preclassified_as_instruction() -> None:
    candidates = atomize_blocks(
        [
            {
                "block_id": "block:notes:inside",
                "block_index": 8,
                "text": (
                    "If you like a thinner finish, you can whisk in a splash of stock "
                    "right before serving to loosen the texture."
                ),
            }
        ],
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    assert len(candidates) == 1
    assert candidates[0].candidate_labels[0] == "RECIPE_NOTES"
    assert "note_like_prose" in candidates[0].rule_tags
    assert "instruction_like" not in candidates[0].rule_tags


def test_atomize_short_quantity_led_lines_stay_ingredient_candidates() -> None:
    candidates = atomize_blocks(
        [
            {
                "block_id": "block:ingredient:1",
                "block_index": 1,
                "text": "1 fresh bay leaf",
            },
            {
                "block_id": "block:ingredient:2",
                "block_index": 2,
                "text": "8 thin slices of five-day rye bread (page 244)",
            },
        ],
        recipe_id=None,
        within_recipe_span=False,
    )
    assert len(candidates) == 2
    assert candidates[0].candidate_labels[0] == "INGREDIENT_LINE"
    assert candidates[1].candidate_labels[0] == "INGREDIENT_LINE"


def test_atomize_keeps_instructional_multi_quantity_prose_unsplit() -> None:
    line = (
        "Pour 1 quart/1 L of water into the saucepan. Add the dried shiitakes, bring "
        "to a boil, then reduce the heat and simmer for 1 hour."
    )
    candidates = atomize_blocks(
        [{"block_id": "block:instr:1", "block_index": 1, "text": line}],
        recipe_id=None,
        within_recipe_span=False,
    )
    assert len(candidates) == 1
    assert candidates[0].text == line
    assert candidates[0].candidate_labels[0] == "INSTRUCTION_LINE"


def test_atomize_blocks_respects_off_splitter_mode() -> None:
    payload = _load_fixture("hollandaise_merged_block.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)

    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
        atomic_block_splitter="off",
    )

    assert len(candidates) == len(blocks)
    assert "TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER" in candidates[0].text
