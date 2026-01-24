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
