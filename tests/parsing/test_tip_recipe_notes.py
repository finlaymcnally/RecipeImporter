from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1


def test_recipe_specific_notes_added_to_recipe_notes():
    candidate = RecipeCandidate(
        name="Test Recipe",
        description="Why this recipe works\nKeep the heat low to avoid curdling.",
    )
    draft = recipe_candidate_to_draft_v1(candidate)
    notes = draft["recipe"].get("notes")
    assert notes is not None
    assert "Keep the heat low" in notes
