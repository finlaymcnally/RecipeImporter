"""Tests for step-level ingredient linking."""

from cookimport.core.models import HowToStep
from cookimport.parsing.step_ingredients import assign_ingredient_lines_to_steps


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
