from __future__ import annotations

from cookimport.parsing.sections import (
    extract_ingredient_sections,
    extract_instruction_sections,
    normalize_section_key,
)


def test_extract_sectioned_lines_aligns_ingredients_and_instructions() -> None:
    ingredients = [
        "For the meat:",
        "1 lb beef",
        "1 tsp salt",
        "For the gravy:",
        "2 tbsp flour",
        "1 tsp salt",
    ]
    instructions = [
        "For the meat:",
        "Season the meat with salt.",
        "Brown the beef.",
        "For the gravy:",
        "Whisk flour into drippings.",
        "Season the gravy with salt.",
    ]

    ingredient_sections = extract_ingredient_sections(ingredients)
    instruction_sections = extract_instruction_sections(instructions)

    assert ingredient_sections.lines_no_headers == [
        "1 lb beef",
        "1 tsp salt",
        "2 tbsp flour",
        "1 tsp salt",
    ]
    assert instruction_sections.lines_no_headers == [
        "Season the meat with salt.",
        "Brown the beef.",
        "Whisk flour into drippings.",
        "Season the gravy with salt.",
    ]

    assert ingredient_sections.section_key_by_line == ["meat", "meat", "gravy", "gravy"]
    assert instruction_sections.section_key_by_line == ["meat", "meat", "gravy", "gravy"]

    assert ingredient_sections.header_hits[0].original_index == 0
    assert ingredient_sections.header_hits[1].original_index == 3
    assert instruction_sections.header_hits[0].original_index == 0
    assert instruction_sections.header_hits[1].original_index == 3



def test_instruction_section_detection_is_conservative_for_real_steps() -> None:
    instructions = [
        "For the sauce:",
        "Mix, stir, and bake:",
        "Cook until thick.",
    ]

    sectioned = extract_instruction_sections(instructions)

    assert sectioned.lines_no_headers == [
        "Mix, stir, and bake:",
        "Cook until thick.",
    ]
    assert sectioned.section_key_by_line == ["sauce", "sauce"]



def test_normalize_section_key_strips_for_the_and_punctuation() -> None:
    assert normalize_section_key("For the Gravy:") == "gravy"
