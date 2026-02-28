from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1


def _first_ingredient_line(draft: dict) -> dict:
    for step in draft["steps"]:
        ingredient_lines = step.get("ingredient_lines", [])
        if ingredient_lines:
            return ingredient_lines[0]
    raise AssertionError("Draft did not contain any ingredient lines.")


def test_variants_extracted_from_instructions():
    candidate = RecipeCandidate(
        name="Test Recipe",
        ingredients=["1 cup flour"],
        instructions=[
            "Mix flour.",
            "Variation spicy: add pepper.",
            "Variants: add herbs.",
        ],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["variants"] == [
        "Variation spicy: add pepper.",
        "Variants: add herbs.",
    ]

    step_texts = [step["instruction"] for step in draft["steps"]]
    assert step_texts == ["Mix flour."]


def test_variants_only_instructions_keep_fallback_step():
    candidate = RecipeCandidate(
        name="Test Recipe",
        ingredients=[],
        instructions=["Variation: add herbs."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["variants"] == ["Variation: add herbs."]
    assert draft["steps"][0]["instruction"] == "See original recipe for details."
    assert draft["steps"][0]["ingredient_lines"] == []


def test_multiblock_variants_extracted():
    """Test that a 'Variation' header followed by content is captured as variants."""
    candidate = RecipeCandidate(
        name="Red Wine Vinaigrette",
        ingredients=["1/4 cup red wine vinegar", "3/4 cup olive oil"],
        instructions=[
            "Whisk vinegar and oil together.",
            "Season to taste.",
            "Variation",
            "• To make Honey-Mustard Vinaigrette, add 1 tablespoon honey and 1 teaspoon mustard.",
        ],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["variants"] == [
        "• To make Honey-Mustard Vinaigrette, add 1 tablespoon honey and 1 teaspoon mustard.",
    ]

    step_texts = [step["instruction"] for step in draft["steps"]]
    assert "Variation" not in step_texts
    assert step_texts == ["Whisk vinegar and oil together.", "Season to taste."]


def test_multiblock_variants_with_multiple_bullets():
    """Test that multiple bullet points after a Variation header are all captured."""
    candidate = RecipeCandidate(
        name="Basic Salad",
        ingredients=["lettuce", "tomato"],
        instructions=[
            "Toss ingredients together.",
            "Variations",
            "• Add cucumber for crunch.",
            "• Substitute spinach for lettuce.",
            "• Add feta cheese for richness.",
        ],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    assert draft["recipe"]["variants"] == [
        "• Add cucumber for crunch.",
        "• Substitute spinach for lettuce.",
        "• Add feta cheese for richness.",
    ]
    step_texts = [step["instruction"] for step in draft["steps"]]
    # Prep step is added for unassigned ingredients (lettuce, tomato not mentioned in instruction)
    assert step_texts == ["Gather and prepare ingredients.", "Toss ingredients together."]


def test_ingredient_parser_options_override_missing_unit_policy():
    candidate = RecipeCandidate(
        name="Onion Soup",
        ingredients=["2 onions"],
        instructions=["Chop the onions."],
    )

    default_draft = recipe_candidate_to_draft_v1(candidate)
    assert _first_ingredient_line(default_draft)["raw_unit_text"] is None

    legacy_draft = recipe_candidate_to_draft_v1(
        candidate,
        ingredient_parser_options={"ingredient_missing_unit_policy": "legacy_medium"},
    )
    assert _first_ingredient_line(legacy_draft)["raw_unit_text"] == "medium"


def test_instruction_step_segmentation_options_split_long_blob():
    candidate = RecipeCandidate(
        name="Long Instructions",
        ingredients=[],
        instructions=[
            "Whisk flour and sugar together until smooth. Add milk and stir constantly. "
            "Simmer for 10 minutes, then finish with butter.",
        ],
    )

    baseline_draft = recipe_candidate_to_draft_v1(
        candidate,
        instruction_step_options={"instruction_step_segmentation_policy": "off"},
    )
    segmented_draft = recipe_candidate_to_draft_v1(
        candidate,
        instruction_step_options={
            "instruction_step_segmentation_policy": "always",
            "instruction_step_segmenter": "heuristic_v1",
        },
    )

    assert len(baseline_draft["steps"]) == 1
    assert len(segmented_draft["steps"]) >= 3
    assert any(
        step["instruction"].startswith("Add milk")
        for step in segmented_draft["steps"]
    )
