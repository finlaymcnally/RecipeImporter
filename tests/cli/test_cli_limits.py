from __future__ import annotations

from cookimport.cli_worker import apply_result_limits as _apply_result_limits
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate


def test_apply_result_limits_truncates_recipes():
    result = ConversionResult(
        recipes=[RecipeCandidate(name=f"Recipe {idx}") for idx in range(4)],
        report=ConversionReport(),
    )

    recipes_taken, truncated = _apply_result_limits(
        result,
        recipe_limit=2,
        limit_label=2,
    )

    assert truncated is True
    assert recipes_taken == 2
    assert len(result.recipes) == 2
    assert result.report.total_recipes == 2
    assert result.report.warnings
