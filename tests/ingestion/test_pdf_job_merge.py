from __future__ import annotations

from cookimport.core.models import RecipeCandidate
from cookimport.core.reporting import generate_recipe_id
from cookimport.staging.pdf_jobs import plan_pdf_page_ranges, reassign_pdf_recipe_ids


def test_plan_pdf_page_ranges_split():
    ranges = plan_pdf_page_ranges(page_count=200, workers=4, pages_per_job=50)
    assert ranges == [(0, 50), (50, 100), (100, 150), (150, 200)]


def test_plan_pdf_page_ranges_no_split():
    ranges = plan_pdf_page_ranges(page_count=40, workers=4, pages_per_job=50)
    assert ranges == [(0, 40)]


def test_reassign_pdf_recipe_ids_updates_order():
    file_hash = "abc123"
    recipe_a = RecipeCandidate(
        name="A",
        identifier="old-a",
        provenance={"location": {"start_page": 5, "start_block": 20}},
    )
    recipe_b = RecipeCandidate(
        name="B",
        identifier="old-b",
        provenance={"location": {"start_page": 2, "start_block": 10}},
    )
    recipe_c = RecipeCandidate(
        name="C",
        identifier="old-c",
        provenance={"location": {"start_block": 1}},
    )

    ordered, id_map = reassign_pdf_recipe_ids(
        [recipe_a, recipe_b, recipe_c],
        file_hash=file_hash,
    )

    expected_ids = [
        generate_recipe_id("pdf", file_hash, "c0"),
        generate_recipe_id("pdf", file_hash, "c1"),
        generate_recipe_id("pdf", file_hash, "c2"),
    ]

    assert [recipe.name for recipe in ordered] == ["B", "A", "C"]
    assert [recipe.identifier for recipe in ordered] == expected_ids
    assert ordered[0].provenance["location"]["chunk_index"] == 0
    assert ordered[1].provenance["location"]["chunk_index"] == 1
    assert ordered[2].provenance["location"]["chunk_index"] == 2

    assert id_map["old-a"] == expected_ids[1]
    assert id_map["old-b"] == expected_ids[0]
