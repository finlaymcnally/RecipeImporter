"""Semantic/fuzzy matching tests for step-level ingredient linking."""

import tests.parsing.test_step_ingredient_linking as _base

# Reuse shared imports/helpers from the base step ingredient test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

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
