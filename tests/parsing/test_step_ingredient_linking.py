"""Tests for step-level ingredient linking."""

from cookimport.core.models import HowToStep
from cookimport.parsing import step_ingredients as step_ingredients_mod
from cookimport.parsing.step_ingredients import assign_ingredient_lines_to_steps, DebugInfo


def _ingredient_line(name: str, quantity_kind: str = "unquantified") -> dict[str, str]:
    return {
        "quantity_kind": quantity_kind,
        "raw_ingredient_text": name,
        "raw_text": name,
    }


def _section_header(name: str) -> dict[str, str]:
    return {
        "quantity_kind": "section_header",
        "raw_ingredient_text": name,
        "raw_text": name,
    }


def _names(lines: list[dict[str, str]]) -> list[str]:
    return [line["raw_ingredient_text"] for line in lines]


def test_negative_matches_no_substrings():
    ingredient_lines = [
        _ingredient_line("oil"),
        _ingredient_line("salt"),
    ]
    steps = ["Boil water and season with unsalted butter."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == []


def test_multiword_preference():
    ingredient_lines = [
        _ingredient_line("chili powder"),
        _ingredient_line("powder"),
    ]
    steps = ["Add chili powder."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["chili powder"]


def test_section_header_grouping():
    ingredient_lines = [
        _section_header("Sauce"),
        _ingredient_line("tomato paste"),
        _ingredient_line("garlic"),
        _section_header("Filling"),
        _ingredient_line("cheese"),
    ]
    steps = ["Make the sauce.", "Stuff the filling."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["tomato paste", "garlic"]
    assert _names(result[1]) == ["cheese"]


def test_duplication_and_all_ingredients():
    ingredient_lines = [
        _ingredient_line("salt"),
        _ingredient_line("butter"),
    ]
    steps = ["Add salt.", "Melt butter.", "Mix all ingredients."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["salt"]
    assert _names(result[1]) == ["butter"]
    assert _names(result[2]) == ["salt", "butter"]


def test_howtostep_inputs():
    ingredient_lines = [
        _ingredient_line("sugar"),
        _ingredient_line("flour"),
    ]
    steps = [HowToStep(text="Add sugar."), "Stir in flour."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["sugar"]
    assert _names(result[1]) == ["flour"]


# --- Tests for ingredient-step duplication fix ---


def test_ingredient_assigned_to_single_best_step():
    """Ingredient mentioned in multiple steps assigned only to best match."""
    ingredient_lines = [
        _ingredient_line("artichokes"),
    ]
    # Artichokes mentioned in multiple steps - should only go to the best match
    steps = [
        "Prepare the artichokes by trimming the stems.",  # reference (prepare)
        "Add the artichokes to the pot.",                  # use (add) - BEST
        "Check if the artichokes are tender.",            # reference (check)
        "Serve the artichokes warm.",                      # reference (serve)
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Should only appear in step 2 (index 1) where "add" is used
    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 1, f"Expected 1 step, got {len(assigned_steps)}: {assigned_steps}"
    assert assigned_steps[0] == 1, f"Expected step 1, got {assigned_steps[0]}"


def test_use_verb_beats_reference_verb():
    """'Add butter' wins over 'cook butter'."""
    ingredient_lines = [
        _ingredient_line("butter"),
    ]
    steps = [
        "Cook the butter until browned.",  # reference verb (cook)
        "Add the butter to the sauce.",     # use verb (add) - should win
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 1
    assert assigned_steps[0] == 1  # "add" step wins


def test_split_language_allows_multi_step():
    """'Add half parsley' + 'remaining parsley' = both steps get it."""
    ingredient_lines = [
        _ingredient_line("parsley"),
    ]
    steps = [
        "Add half the parsley to the soup.",       # use + split (half)
        "Garnish with remaining parsley.",         # use + split (remaining)
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Both steps should get parsley due to split language
    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 2
    assert 0 in assigned_steps
    assert 1 in assigned_steps


def test_reserve_language_detection():
    """'reserving 2 tbsp' + 'add reserved' = both steps."""
    ingredient_lines = [
        _ingredient_line("olive oil"),
    ]
    steps = [
        "Drizzle olive oil over vegetables, reserving 2 tbsp.",  # use + split
        "Add the reserved olive oil at the end.",                 # use + split
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 2


def test_reference_verbs_deprioritized():
    """Steps with only reference verbs don't get ingredients when use verb exists."""
    ingredient_lines = [
        _ingredient_line("chicken"),
    ]
    steps = [
        "Let the chicken rest for 10 minutes.",   # reference (let, rest)
        "Stir in the chicken pieces.",             # use (stir)
        "Check if chicken is cooked through.",     # reference (check)
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 1
    assert assigned_steps[0] == 1  # "stir" step wins


def test_debug_mode_returns_info():
    """debug=True returns assignment trace."""
    ingredient_lines = [
        _ingredient_line("salt"),
        _ingredient_line("pepper"),
    ]
    steps = ["Add salt and pepper."]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert isinstance(debug_info, DebugInfo)
    assert len(debug_info.candidates) >= 2  # At least one candidate per ingredient
    assert len(debug_info.assignments) == 2  # One assignment per ingredient


def test_section_header_grouping_preserved():
    """Existing section header behavior unchanged."""
    ingredient_lines = [
        _section_header("Sauce"),
        _ingredient_line("tomato paste"),
        _ingredient_line("garlic"),
        _section_header("Filling"),
        _ingredient_line("cheese"),
    ]
    steps = ["Make the sauce.", "Stuff the filling."]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["tomato paste", "garlic"]
    assert _names(result[1]) == ["cheese"]


def test_section_context_disambiguates_repeated_ingredient_names() -> None:
    ingredient_lines = [
        {
            "quantity_kind": "exact",
            "raw_ingredient_text": "salt",
            "raw_text": "1 tsp salt (for meat)",
            "input_qty": 1.0,
        },
        {
            "quantity_kind": "exact",
            "raw_ingredient_text": "salt",
            "raw_text": "1 tsp salt (for gravy)",
            "input_qty": 1.0,
        },
    ]
    steps = [
        "Season the meat with salt.",
        "Season the gravy with salt.",
    ]

    result = assign_ingredient_lines_to_steps(
        steps,
        ingredient_lines,
        ingredient_section_key_by_line=["meat", "gravy"],
        step_section_key_by_step=["meat", "gravy"],
    )

    assert [line["raw_text"] for line in result[0]] == ["1 tsp salt (for meat)"]
    assert [line["raw_text"] for line in result[1]] == ["1 tsp salt (for gravy)"]


def test_all_ingredients_phrase_preserved():
    """'Combine all ingredients' still works."""
    ingredient_lines = [
        _ingredient_line("flour"),
        _ingredient_line("sugar"),
        _ingredient_line("eggs"),
    ]
    steps = [
        "Sift the flour.",
        "Combine all ingredients in a bowl.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Step 2 should have all ingredients
    assert _names(result[1]) == ["flour", "sugar", "eggs"]


def test_section_header_reference_only_later_step_does_not_duplicate_group_members() -> None:
    ingredient_lines = [
        _section_header("Gravy"),
        _ingredient_line("flour"),
    ]
    steps = [
        "Whisk the flour until smooth.",
        "Simmer the gravy until thickened.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["flour"]
    assert _names(result[1]) == []


def test_earlier_step_wins_tiebreaker():
    """When scores are equal, earlier step wins."""
    ingredient_lines = [
        _ingredient_line("salt"),
    ]
    # Both steps use "add" - equal verb signal, earlier should win
    steps = [
        "Add salt to taste.",
        "Add more salt if needed.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert len(assigned_steps) == 1
    assert assigned_steps[0] == 0  # Earlier step wins


def test_multi_ingredient_single_step():
    """Multiple ingredients can be assigned to the same step."""
    ingredient_lines = [
        _ingredient_line("onion"),
        _ingredient_line("garlic"),
        _ingredient_line("celery"),
    ]
    steps = [
        "Dice the onion, garlic, and celery.",
        "Cook the vegetables until soft.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # All three should be in step 0 where they're mentioned with action
    # Step 1 just says "vegetables" so shouldn't get them
    assert "onion" in _names(result[0])
    assert "garlic" in _names(result[0])
    assert "celery" in _names(result[0])
