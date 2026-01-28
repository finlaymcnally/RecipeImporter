from __future__ import annotations

from cookimport.core.models import ParsingOverrides, RecipeCandidate
from cookimport.parsing.tips import (
    canonicalize_recipe_name,
    chunk_standalone_blocks,
    extract_tip_candidates_from_candidate,
    extract_tips,
    extract_tips_from_candidate,
    guess_tags,
)


def test_canonicalize_recipe_name():
    name = "Mom's Favorite Scrambled Eggs"
    assert canonicalize_recipe_name(name) == "scrambled eggs"


def test_extract_tips_from_description():
    candidate = RecipeCandidate(
        name="Mom's Favorite Scrambled Eggs",
        description="Tip: Remove eggs from the pan just before they finish cooking.",
    )
    tips = extract_tips_from_candidate(candidate)
    assert tips == []
    candidates = extract_tip_candidates_from_candidate(candidate)
    assert len(candidates) == 1
    assert candidates[0].scope == "recipe_specific"
    assert candidates[0].text.startswith("Remove eggs from the pan")
    assert "scrambled eggs" in candidates[0].tags.recipes
    assert candidates[0].source_recipe_title == "Mom's Favorite Scrambled Eggs"
    assert candidates[0].standalone is True


def test_guess_tags_from_text():
    text = "Sear steak in a cast iron skillet; rest before slicing."
    tags = guess_tags(text, recipe_name="Perfect Steak")
    assert "beef" in tags.meats
    assert "sear" in tags.cooking_methods
    assert "cast iron" in tags.tools


def test_extract_standalone_tip_with_advice_cue():
    text = "Salt food regularly while cooking; it makes things taste better."
    tips = extract_tips(text)
    assert len(tips) == 1
    assert tips[0].text.startswith("Salt food regularly")


def test_recipe_specific_header_is_skipped():
    text = "Why this recipe works\nUse a small skillet to control heat."
    tips = extract_tips(text)
    assert tips == []


def test_dependent_fragment_is_dropped():
    text = "With this in mind, salt early."
    tips = extract_tips(text)
    assert tips == []


def test_narrative_sentence_is_rejected():
    text = "In my mind, the two minimum qualifications for a cook are curiosity and patience."
    tips = extract_tips(text)
    assert tips == []


def test_tip_header_block_is_extracted():
    text = (
        "Tip:\nUse a hot skillet for best searing, and let the meat rest so the juices "
        "redistribute before slicing."
    )
    tips = extract_tips(text)
    assert len(tips) == 1
    assert tips[0].text.startswith("Use a hot skillet")


def test_tip_header_override_is_respected():
    overrides = ParsingOverrides(tipHeaders=["chef's secret"])
    text = (
        "Chef's Secret:\n"
        "Chill the dough overnight so the butter stays cold and the crust stays flaky."
    )
    tips = extract_tips(text, overrides=overrides)
    assert len(tips) == 1
    assert "Chill the dough overnight" in tips[0].text


def test_guess_tags_additional_categories():
    text = "Finish pasta with basil, parmesan, olive oil, and a drizzle of honey."
    tags = guess_tags(text, recipe_name="Pasta")
    assert "pasta" in tags.dishes
    assert "basil" in tags.herbs
    assert "cheese" in tags.dairy
    assert "pasta" in tags.grains
    assert "olive oil" in tags.oils_fats
    assert "honey" in tags.sweeteners


def test_guess_tags_cooking_methods():
    text = "For best results, braise the beef and finish with a quick sear."
    tags = guess_tags(text, recipe_name="Beef")
    assert "braise" in tags.techniques
    assert "braise" in tags.cooking_methods
    assert "sear" in tags.cooking_methods


def test_chunk_standalone_blocks_merges_headers():
    blocks = [
        (0, "WHICH SALT SHOULD I USE?"),
        (1, "Kosher salt draws moisture efficiently."),
        (2, "If you must use table salt, use less."),
    ]
    containers = chunk_standalone_blocks(blocks)
    assert len(containers) == 1
    container = containers[0]
    assert container.header == "WHICH SALT SHOULD I USE?"
    texts = [text for _, text in container.blocks]
    assert "WHICH SALT SHOULD I USE?" in texts
    assert any("table salt" in text for text in texts)


def test_permissive_you_can_tip_is_kept():
    text = "You can wash delicate items like berries and then dry them in a salad spinner."
    tips = extract_tips(text)
    assert len(tips) == 1
