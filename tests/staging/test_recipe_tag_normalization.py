from __future__ import annotations

from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.staging.recipe_tag_normalization import (
    normalize_conversion_result_recipe_tags,
    normalize_tag_label,
)


def test_normalize_tag_label_collapses_case_and_punctuation_variants() -> None:
    assert normalize_tag_label("Gluten-Free") == "gluten free"
    assert normalize_tag_label("  GLUTEN free ") == "gluten free"
    assert normalize_tag_label("Instant_Pot") == "instant pot"


def test_normalize_conversion_result_recipe_tags_dedupes_recipe_and_reports_variants() -> None:
    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="One",
                recipeIngredient=["1 chicken breast"],
                recipeInstructions=["Cook."],
                tags=["Weeknight", "week-night", "Chicken"],
            ),
            RecipeCandidate(
                name="Two",
                recipeIngredient=["1 onion"],
                recipeInstructions=["Cook."],
                tags=["gluten free", "Gluten-Free"],
            ),
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    summary = normalize_conversion_result_recipe_tags(result)

    assert result.recipes[0].tags == ["weeknight", "chicken"]
    assert result.recipes[1].tags == ["gluten free"]
    assert summary["variant_groups"] == {
        "gluten free": ["gluten free", "Gluten-Free"],
        "weeknight": ["Weeknight", "week-night"],
    }
