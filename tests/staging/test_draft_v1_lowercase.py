from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1


def test_draft_v1_lowercases_ingredient_fields():
    candidate = RecipeCandidate(
        name="Test Recipe",
        ingredients=["1 Cup FLOUR", "PINCH SALT"],
        instructions=["Mix flour and salt."],
    )

    draft = recipe_candidate_to_draft_v1(candidate)

    ingredient_lines = draft["steps"][0]["ingredient_lines"]
    assert ingredient_lines

    for line in ingredient_lines:
        for key in ("raw_text", "raw_ingredient_text", "raw_unit_text", "note", "preparation"):
            value = line.get(key)
            if isinstance(value, str):
                assert value == value.lower()
