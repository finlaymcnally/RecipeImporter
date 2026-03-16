from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import RecipeCandidate
from cookimport.staging.jsonld import recipe_candidate_to_jsonld
from cookimport.staging.writer import write_section_outputs


def _candidate() -> RecipeCandidate:
    return RecipeCandidate(
        name="Meat and Gravy",
        recipeIngredient=[
            "For the meat:",
            "1 lb beef",
            "1 tsp salt",
            "For the gravy:",
            "2 tbsp flour",
            "1 tsp salt",
        ],
        recipeInstructions=[
            "For the meat:",
            "Season the meat with salt.",
            "Brown the beef.",
            "For the gravy:",
            "Whisk flour into drippings.",
            "Season the gravy with salt.",
        ],
        provenance={"@id": "urn:recipe:test:sectioned"},
    )


def _segmented_candidate() -> RecipeCandidate:
    return RecipeCandidate(
        name="Segmented Sections",
        recipeIngredient=[
            "For the meat:",
            "1 lb beef",
            "For the gravy:",
            "2 tbsp flour",
        ],
        recipeInstructions=[
            "For the meat:\nSeason the meat with salt. Brown the beef. Rest 5 minutes.",
            "For the gravy:\nWhisk flour into drippings. Cook 2 minutes. Add stock and simmer.",
        ],
        provenance={"@id": "urn:recipe:test:segmented"},
    )



def test_jsonld_uses_howto_sections_and_ingredient_section_metadata() -> None:
    payload = recipe_candidate_to_jsonld(_candidate())

    instructions = payload["recipeInstructions"]
    assert isinstance(instructions, list)
    assert instructions[0]["@type"] == "HowToSection"
    assert instructions[0]["name"] == "For the meat"
    assert instructions[0]["itemListElement"][0]["@type"] == "HowToStep"
    assert instructions[0]["itemListElement"][0]["text"] == "Season the meat with salt."

    ingredient_sections = payload["recipeimport:ingredientSections"]
    assert [entry["key"] for entry in ingredient_sections] == ["meat", "gravy"]
    assert ingredient_sections[1]["recipeIngredient"] == ["2 tbsp flour", "1 tsp salt"]


def test_jsonld_serializes_candidate_tags_to_keywords() -> None:
    candidate = RecipeCandidate(
        name="Tagged JSONLD",
        recipeIngredient=["1 lb chicken"],
        recipeInstructions=["Cook the chicken."],
        tags=["weeknight", "chicken"],
    )

    payload = recipe_candidate_to_jsonld(candidate)

    assert payload["keywords"] == "weeknight, chicken"


def test_write_section_outputs_writes_json_and_markdown(tmp_path: Path) -> None:
    write_section_outputs(tmp_path, "sectioned", [_candidate()])

    section_json = tmp_path / "sections" / "sectioned" / "r0.sections.json"
    section_md = tmp_path / "sections" / "sectioned" / "sections.md"

    assert section_json.exists()
    assert section_md.exists()

    payload = json.loads(section_json.read_text(encoding="utf-8"))
    assert payload["title"] == "Meat and Gravy"
    assert [entry["key"] for entry in payload["sections"]] == ["meat", "gravy"]

    summary = section_md.read_text(encoding="utf-8")
    assert "For the meat" in summary
    assert "For the gravy" in summary


def test_instruction_segmentation_keeps_jsonld_and_sections_aligned(tmp_path: Path) -> None:
    options = {
        "instruction_step_segmentation_policy": "always",
        "instruction_step_segmenter": "heuristic_v1",
    }
    candidate = _segmented_candidate()

    payload = recipe_candidate_to_jsonld(
        candidate,
        instruction_step_options=options,
    )
    instructions = payload["recipeInstructions"]
    assert instructions[0]["@type"] == "HowToSection"
    assert len(instructions[0]["itemListElement"]) >= 3

    write_section_outputs(
        tmp_path,
        "segmented",
        [candidate],
        instruction_step_options=options,
    )
    section_json = tmp_path / "sections" / "segmented" / "r0.sections.json"
    section_payload = json.loads(section_json.read_text(encoding="utf-8"))
    section_steps_by_key = {
        section["key"]: section.get("steps", [])
        for section in section_payload["sections"]
    }
    jsonld_steps_by_key = {
        section["name"].split()[-1].lower(): [
            step["text"] for step in section["itemListElement"]
        ]
        for section in instructions
    }

    assert section_steps_by_key["meat"] == jsonld_steps_by_key["meat"]
    assert section_steps_by_key["gravy"] == jsonld_steps_by_key["gravy"]


def test_write_section_outputs_can_skip_markdown(tmp_path: Path) -> None:
    write_section_outputs(tmp_path, "sectioned", [_candidate()], write_markdown=False)

    section_json = tmp_path / "sections" / "sectioned" / "r0.sections.json"
    section_md = tmp_path / "sections" / "sectioned" / "sections.md"

    assert section_json.exists()
    assert not section_md.exists()
