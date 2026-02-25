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


def test_head_alias_matches_partial_name():
    """Head token of multi-word ingredient matches partial mentions."""
    ingredient_lines = [
        _ingredient_line("sage leaves"),
    ]
    steps = [
        "Fry the sage in hot oil.",  # Uses "sage" not "sage leaves"
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assert _names(result[0]) == ["sage leaves"]


def test_lemmatized_plural_match():
    """Plural forms in steps should match singular ingredients via lemmatization."""
    ingredient_lines = [
        _ingredient_line("onion"),
    ]
    steps = [
        "Add the onions to the pan.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert _names(result[0]) == ["onion"]
    assert debug_info.candidates[0].match_kind == "semantic"


def test_lemmatized_floured_match():
    """Adjectival forms like 'floured' should match flour ingredients."""
    ingredient_lines = [
        _ingredient_line("all-purpose flour"),
    ]
    steps = [
        "On a well-floured board, roll the dough.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert _names(result[0]) == ["all-purpose flour"]
    assert debug_info.candidates[0].match_kind == "semantic"


def test_synonym_green_onion_match():
    """Synonym expansion should match scallions to green onions."""
    ingredient_lines = [
        _ingredient_line("scallions"),
    ]
    steps = [
        "Add the green onions to the bowl.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert _names(result[0]) == ["scallions"]
    assert debug_info.candidates[0].match_kind == "semantic"


def test_synonym_chickpea_match():
    """Synonym expansion should match chickpeas to garbanzo beans."""
    ingredient_lines = [
        _ingredient_line("chickpeas"),
    ]
    steps = [
        "Add the garbanzo beans and stir.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert _names(result[0]) == ["chickpeas"]
    assert debug_info.candidates[0].match_kind == "semantic"


def test_fuzzy_typo_match():
    """Fuzzy fallback should rescue near-miss typos when exact/semantic fail."""
    ingredient_lines = [
        _ingredient_line("coriander"),
    ]
    steps = [
        "Add the corriander to the pan.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert _names(result[0]) == ["coriander"]
    assert debug_info.candidates[0].match_kind == "fuzzy"


def test_earliest_use_verb_wins_over_stronger_alias():
    """When multiple steps have use verbs, earliest wins even with weaker alias."""
    ingredient_lines = [
        _ingredient_line("sage leaves"),
    ]
    steps = [
        "Fry the sage.",          # Earlier use verb, weaker alias
        "Add the sage leaves.",   # Later use verb, stronger alias
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Step 0 should win because it's the earliest use verb
    assert _names(result[0]) == ["sage leaves"]
    assert _names(result[1]) == []


def test_quantity_split_with_half():
    """'half' splits quantity evenly between steps."""
    ingredient_lines = [{
        "quantity_kind": "exact",
        "raw_ingredient_text": "croutons",
        "raw_text": "4 cups croutons",
        "input_qty": 4.0,
    }]
    steps = [
        "Add half the croutons.",
        "Add the remaining croutons.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Both steps should have croutons with halved quantity
    assert len(result[0]) == 1
    assert len(result[1]) == 1
    assert result[0][0]["input_qty"] == 2.0
    assert result[1][0]["input_qty"] == 2.0


def test_fry_is_use_verb():
    """'fry' is classified as a use verb, not reference."""
    ingredient_lines = [
        _ingredient_line("onions"),
    ]
    steps = [
        "Fry the onions until golden.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert len(debug_info.candidates) == 1
    assert debug_info.candidates[0].verb_signal == "use"
    assert _names(result[0]) == ["onions"]


def test_roll_is_use_verb():
    """'roll' is classified as a use verb (e.g., dough handling)."""
    ingredient_lines = [
        _ingredient_line("tart dough"),
    ]
    steps = [
        "Roll the dough into a circle.",
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    assert len(debug_info.candidates) == 1
    assert debug_info.candidates[0].verb_signal == "use"
    assert _names(result[0]) == ["tart dough"]


def test_split_only_applies_to_immediate_ingredient():
    """'remaining croutons, squash' should NOT split squash."""
    ingredient_lines = [
        _ingredient_line("butternut squash"),
    ]
    steps = [
        "Roast the butternut squash.",
        "Add the remaining croutons, squash, hazelnuts.",  # "remaining" is for croutons, not squash
    ]

    result, debug_info = assign_ingredient_lines_to_steps(
        steps, ingredient_lines, debug=True
    )

    # Squash should only be in step 0 (roast), not step 1
    assigned_steps = [i for i, lines in enumerate(result) if _names(lines)]
    assert assigned_steps == [0], f"Expected [0], got {assigned_steps}"
    # The step 1 candidate should NOT have split signal
    step1_candidates = [c for c in debug_info.candidates if c.step_index == 1]
    if step1_candidates:
        assert step1_candidates[0].verb_signal != "split"


def test_reserve_without_remaining_does_not_split():
    """Weak split words alone should not trigger multi-step assignment."""
    ingredient_lines = [
        _ingredient_line("olive oil"),
    ]
    steps = [
        "Reserve the olive oil.",
        "Add the olive oil to the pan.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    assigned_steps = [i for i, step_lines in enumerate(result) if _names(step_lines)]
    assert assigned_steps == [1], f"Expected step 1 only, got {assigned_steps}"


def test_split_penalty_lowers_confidence():
    """Split assignments reduce confidence slightly for review triage."""
    ingredient_lines = [{
        "quantity_kind": "exact",
        "raw_ingredient_text": "croutons",
        "raw_text": "4 cups croutons",
        "input_qty": 4.0,
        "confidence": 0.9,
    }]
    steps = [
        "Add half the croutons.",
        "Add the remaining croutons.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    expected = round(0.9 - step_ingredients_mod._SPLIT_CONFIDENCE_PENALTY, 3)
    assert result[0][0]["confidence"] == expected
    assert result[1][0]["confidence"] == expected


def test_collective_term_spices_assigns_unmatched():
    """Collective term 'spices' assigns unmatched spice ingredients to that step."""
    ingredient_lines = [
        _ingredient_line("sugar"),
        _ingredient_line("ground cinnamon"),
        _ingredient_line("ground ginger"),
        _ingredient_line("ground cloves"),
    ]
    steps = [
        "Combine sugar and spices in a bowl.",  # "spices" should match cinnamon, ginger, cloves
        "Stir to combine.",
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Sugar matched directly, spices should bring in cinnamon, ginger, cloves
    step0_names = _names(result[0])
    assert "sugar" in step0_names, "sugar should match directly"
    assert "ground cinnamon" in step0_names, "cinnamon should match via 'spices'"
    assert "ground ginger" in step0_names, "ginger should match via 'spices'"
    assert "ground cloves" in step0_names, "cloves should match via 'spices'"


def test_collective_term_herbs_assigns_unmatched():
    """Collective term 'herbs' assigns unmatched herb ingredients to that step."""
    ingredient_lines = [
        _ingredient_line("olive oil"),
        _ingredient_line("fresh basil"),
        _ingredient_line("thyme"),
    ]
    steps = [
        "Heat oil in pan.",
        "Add fresh herbs and stir.",  # "herbs" should match basil and thyme
    ]

    result = assign_ingredient_lines_to_steps(steps, ingredient_lines)

    # Oil goes to step 0 (explicit match)
    assert "olive oil" in _names(result[0])
    # Herbs go to step 1 via collective term
    step1_names = _names(result[1])
    assert "fresh basil" in step1_names, "basil should match via 'herbs'"
    assert "thyme" in step1_names, "thyme should match via 'herbs'"
