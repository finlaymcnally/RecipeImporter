from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1


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
