from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import (
    AuthoritativeRecipeSemantics,
    ConversionReport,
    ConversionResult,
    RecipeCandidate,
)
from cookimport.staging.writer import write_draft_outputs, write_intermediate_outputs


def test_writer_uses_schemaorg_and_draft_overrides(tmp_path: Path) -> None:
    recipe_id = "urn:recipe:test:1"
    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Original Name",
                identifier=recipe_id,
                recipeIngredient=["1 egg"],
                recipeInstructions=["Cook the egg."],
                provenance={"location": {"start_block": 0, "end_block": 2}},
            )
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(tmp_path / "book.txt"),
    )

    schemaorg_override = {
        "@context": "http://schema.org",
        "@type": "Recipe",
        "@id": recipe_id,
        "name": "LLM Title",
    }
    draft_override = {
        "schema_v": 1,
        "source": "book.txt",
        "recipe": {"title": "LLM Final"},
        "steps": [{"instruction": "LLM step.", "ingredient_lines": []}],
    }

    intermediate_dir = tmp_path / "intermediate"
    final_dir = tmp_path / "final"
    write_intermediate_outputs(
        result,
        intermediate_dir,
        schemaorg_overrides_by_recipe_id={recipe_id: schemaorg_override},
    )
    write_draft_outputs(
        result,
        final_dir,
        draft_overrides_by_recipe_id={recipe_id: draft_override},
    )

    intermediate_payload = json.loads((intermediate_dir / "r0.jsonld").read_text(encoding="utf-8"))
    final_payload = json.loads((final_dir / "r0.json").read_text(encoding="utf-8"))
    assert intermediate_payload == schemaorg_override
    assert final_payload["schema_v"] == draft_override["schema_v"]
    assert final_payload["source"] == draft_override["source"]
    assert final_payload["recipe"] == draft_override["recipe"]
    assert final_payload["steps"] == draft_override["steps"]


def test_writer_uses_authoritative_recipe_payloads_before_candidate_rebuild(tmp_path: Path) -> None:
    recipe_id = "urn:recipe:test:canonical"
    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Original Name",
                identifier=recipe_id,
                recipeIngredient=["1 egg"],
                recipeInstructions=["Cook the egg."],
                provenance={"location": {"start_block": 0, "end_block": 2}},
            )
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(tmp_path / "book.txt"),
    )

    authoritative_payload = AuthoritativeRecipeSemantics(
        recipeId=recipe_id,
        semanticAuthority="test",
        title="Canonical Omelet",
        ingredients=["2 eggs", "pinch salt"],
        instructions=["Beat eggs.", "Cook gently."],
        notes=["Source: notebook"],
        variants=["Soft scramble"],
        tags=["breakfast"],
        ingredientStepMapping={"0": [0], "1": [1]},
        source="book.txt",
    )

    final_dir = tmp_path / "final"
    write_draft_outputs(
        result,
        final_dir,
        authoritative_payloads_by_recipe_id={recipe_id: authoritative_payload},
    )

    final_payload = json.loads((final_dir / "r0.json").read_text(encoding="utf-8"))
    assert final_payload["recipe"]["title"] == "Canonical Omelet"
    assert final_payload["recipe"]["notes"] == "Source: notebook"
    assert final_payload["recipe"]["variants"] == ["Soft scramble"]
    assert [step["instruction"] for step in final_payload["steps"]] == [
        "Beat eggs.",
        "Cook gently.",
    ]
