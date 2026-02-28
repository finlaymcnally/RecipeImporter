from __future__ import annotations

import json

from cookimport.parsing.schemaorg_ingest import (
    collect_schemaorg_recipe_objects,
    flatten_schema_recipe_instructions,
    parse_schema_duration,
    schema_recipe_confidence,
    schema_recipe_to_candidate,
)
from tests.paths import FIXTURES_DIR


def test_collect_schemaorg_recipe_objects_from_graph_fixture() -> None:
    payload = json.loads(
        (FIXTURES_DIR / "webschema" / "recipe_graph.jsonld").read_text(encoding="utf-8")
    )

    recipes = collect_schemaorg_recipe_objects(payload)

    assert len(recipes) == 1
    assert recipes[0]["name"] == "Garlic Rice"


def test_flatten_schema_recipe_instructions_keeps_section_name_and_steps() -> None:
    recipe_obj = {
        "@type": "Recipe",
        "recipeInstructions": [
            {
                "@type": "HowToSection",
                "name": "For the sauce",
                "itemListElement": [
                    {"@type": "HowToStep", "text": "Whisk soy sauce and vinegar."},
                    {"@type": "HowToStep", "text": "Simmer for 2 minutes."},
                ],
            }
        ],
    }

    flattened = flatten_schema_recipe_instructions(recipe_obj)

    assert flattened == [
        "For the sauce",
        "Whisk soy sauce and vinegar.",
        "Simmer for 2 minutes.",
    ]


def test_parse_schema_duration_normalizes_common_duration_phrases() -> None:
    assert parse_schema_duration("1 hr 30 mins") == "PT1H30M"
    assert parse_schema_duration("45 min") == "PT45M"
    assert parse_schema_duration("PT20M") == "PT20M"


def test_schema_recipe_to_candidate_maps_fields() -> None:
    recipe_obj = {
        "@type": "Recipe",
        "name": "Roasted Potatoes",
        "recipeIngredient": ["2 russet potatoes", "1 tbsp olive oil"],
        "recipeInstructions": ["Heat oven to 425F.", "Roast until crisp."],
        "recipeYield": "4 servings",
        "prepTime": "15 minutes",
        "cookTime": "30 minutes",
        "author": {"@type": "Person", "name": "Chef Example"},
        "url": "https://example.test/roasted-potatoes",
    }

    candidate = schema_recipe_to_candidate(
        recipe_obj,
        source="fixture",
        confidence=0.91,
        provenance={"location": {"schema_index": 0}},
    )

    assert candidate.name == "Roasted Potatoes"
    assert candidate.ingredients == ["2 russet potatoes", "1 tbsp olive oil"]
    assert candidate.instructions == ["Heat oven to 425F.", "Roast until crisp."]
    assert candidate.recipe_yield == "4 servings"
    assert candidate.prep_time == "PT15M"
    assert candidate.cook_time == "PT30M"
    assert candidate.author == "Chef Example"
    assert candidate.source_url == "https://example.test/roasted-potatoes"
    assert candidate.source == "fixture"
    assert candidate.provenance["location"]["schema_index"] == 0
    assert candidate.confidence == 0.91


def test_schema_recipe_confidence_rewards_core_fields() -> None:
    recipe_obj = {
        "@type": "Recipe",
        "name": "Chili",
        "recipeIngredient": ["1 lb beef", "1 onion", "1 can tomatoes"],
        "recipeInstructions": ["Brown beef.", "Simmer with tomatoes."],
    }

    score, reasons = schema_recipe_confidence(
        recipe_obj,
        min_ingredients=2,
        min_instruction_steps=1,
    )

    assert score >= 0.8
    assert "has_name" in reasons
    assert "ingredients_threshold_met" in reasons
    assert "instructions_threshold_met" in reasons

