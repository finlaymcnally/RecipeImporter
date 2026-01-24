from __future__ import annotations

from cookimport.cli import _apply_result_limits
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate, TipCandidate


def test_apply_result_limits_truncates_recipes_and_tips():
    result = ConversionResult(
        recipes=[RecipeCandidate(name=f"Recipe {idx}") for idx in range(4)],
        tips=[TipCandidate(text=f"Tip {idx}") for idx in range(3)],
        report=ConversionReport(),
    )

    recipes_taken, tips_taken, truncated = _apply_result_limits(
        result,
        recipe_limit=2,
        tip_limit=1,
        limit_label=2,
    )

    assert truncated is True
    assert recipes_taken == 2
    assert tips_taken == 1
    assert len(result.recipes) == 2
    assert len(result.tips) == 1
    assert result.report.total_recipes == 2
    assert result.report.total_tips == 1
    assert result.report.warnings
