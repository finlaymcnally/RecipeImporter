from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.parsing.yield_extraction import derive_yield_fields, normalize_yield_mode


def _candidate(**overrides) -> RecipeCandidate:
    payload = {
        "name": "Yield Test",
        "ingredients": ["1 cup flour"],
        "instructions": ["Mix well."],
    }
    payload.update(overrides)
    return RecipeCandidate(**payload)


def test_normalize_yield_mode_defaults_to_scored() -> None:
    assert normalize_yield_mode(None) == "scored_v1"
    assert normalize_yield_mode({"p6_yield_mode": "invalid"}) == "scored_v1"


def test_derive_yield_fields_scored_mode_uses_recipe_yield_when_present() -> None:
    candidate = _candidate(recipe_yield="Serves 4")

    fields = derive_yield_fields(candidate, payload={"p6_yield_mode": "scored_v1"})

    assert fields["yield_units"] == 4
    assert fields["yield_phrase"] == "Serves 4"
    assert fields["yield_unit_name"] == "serving"
    assert fields["yield_detail"] is None
    assert fields["_p6_yield_debug"]["selected_source"] == "recipe_yield"


def test_derive_yield_fields_scored_mode_selects_best_phrase() -> None:
    candidate = _candidate(
        recipe_yield=None,
        description="Calories: 220 per serving\nServes 6",
    )

    fields = derive_yield_fields(candidate, payload={"p6_yield_mode": "scored_v1"})

    assert fields["yield_units"] == 6
    assert fields["yield_phrase"] == "Serves 6"
    assert fields["yield_unit_name"] == "serving"
    assert fields["yield_detail"] is None
    assert fields["_p6_yield_debug"]["selected_source"] == "description"


def test_derive_yield_fields_scored_mode_parses_dozen_units() -> None:
    candidate = _candidate(recipe_yield="2 dozen cookies")

    fields = derive_yield_fields(candidate, payload={"p6_yield_mode": "scored_v1"})

    assert fields["yield_units"] == 24
    assert fields["yield_unit_name"] == "cooky"
    assert fields["yield_detail"] == "cookies"


def test_derive_yield_fields_scored_mode_parses_ranges() -> None:
    candidate = _candidate(recipe_yield="Makes 4-6 portions")

    fields = derive_yield_fields(candidate, payload={"p6_yield_mode": "scored_v1"})

    assert fields["yield_units"] == 5
    assert fields["yield_unit_name"] == "portion"
    assert fields["yield_detail"] == "portions"


def test_derive_yield_fields_scored_mode_ignores_nutrition_candidates() -> None:
    candidate = _candidate(
        recipe_yield=None,
        description="Nutrition: 300 calories per serving",
        instructions=["Calories: 190 per serving"],
        comments=[{"text": "%DV values vary by diet."}],
    )

    fields = derive_yield_fields(candidate, payload={"p6_yield_mode": "scored_v1"})

    assert fields["yield_units"] == 1
    assert fields["yield_phrase"] is None
    assert fields["yield_unit_name"] is None
    assert fields["yield_detail"] is None
