from __future__ import annotations

from cookimport.core.models import RecipeCandidate, TipCandidate
from cookimport.core.reporting import generate_recipe_id
from cookimport.staging.pdf_jobs import reassign_recipe_ids


def test_reassign_epub_recipe_ids_orders_by_spine():
    file_hash = "def456"
    recipe_a = RecipeCandidate(
        name="A",
        identifier="old-a",
        provenance={"location": {"start_spine": 2, "start_block": 5}},
    )
    recipe_b = RecipeCandidate(
        name="B",
        identifier="old-b",
        provenance={"location": {"start_spine": 1, "start_block": 1}},
    )
    recipe_c = RecipeCandidate(
        name="C",
        identifier="old-c",
        provenance={"location": {"start_block": 1}},
    )
    tips = [
        TipCandidate(text="Tip one", sourceRecipeId="old-a"),
        TipCandidate(text="Tip two", sourceRecipeId="old-b"),
    ]

    ordered, id_map = reassign_recipe_ids(
        [recipe_a, recipe_b, recipe_c],
        tips,
        file_hash=file_hash,
        importer_name="epub",
    )

    expected_ids = [
        generate_recipe_id("epub", file_hash, "c0"),
        generate_recipe_id("epub", file_hash, "c1"),
        generate_recipe_id("epub", file_hash, "c2"),
    ]

    assert [recipe.name for recipe in ordered] == ["B", "A", "C"]
    assert [recipe.identifier for recipe in ordered] == expected_ids
    assert ordered[0].provenance["location"]["chunk_index"] == 0
    assert ordered[1].provenance["location"]["chunk_index"] == 1
    assert ordered[2].provenance["location"]["chunk_index"] == 2

    assert tips[0].source_recipe_id == expected_ids[1]
    assert tips[1].source_recipe_id == expected_ids[0]
    assert id_map["old-a"] == expected_ids[1]
    assert id_map["old-b"] == expected_ids[0]
