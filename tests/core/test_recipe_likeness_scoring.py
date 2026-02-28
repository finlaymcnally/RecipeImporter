from __future__ import annotations

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import RecipeCandidate, RecipeLikenessResult, RecipeLikenessTier
from cookimport.core.scoring import (
    recipe_gate_action,
    score_recipe_candidate,
    score_recipe_likeness,
    summarize_recipe_likeness,
)


def test_score_recipe_likeness_is_deterministic() -> None:
    settings = RunSettings()
    candidate = RecipeCandidate(
        name="Skillet Potatoes",
        recipeIngredient=["2 potatoes", "1 tbsp olive oil", "salt"],
        recipeInstructions=["Slice potatoes.", "Cook in skillet until browned."],
        description="A quick skillet side dish.",
    )

    first = score_recipe_likeness(candidate, settings=settings)
    second = score_recipe_likeness(candidate, settings=settings)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert score_recipe_candidate(candidate) == first.score


def test_score_recipe_likeness_rejects_missing_core_fields() -> None:
    result = score_recipe_likeness(
        RecipeCandidate(
            name="Notes",
            recipeIngredient=[],
            recipeInstructions=[],
            description="General chapter commentary.",
        ),
        settings=RunSettings(),
    )

    assert result.tier == RecipeLikenessTier.reject
    assert recipe_gate_action(result, settings=RunSettings()) == "reject"


def test_recipe_gate_action_respects_tier_and_minimum_lines() -> None:
    settings = RunSettings(
        recipe_score_min_ingredient_lines=2,
        recipe_score_min_instruction_lines=1,
    )
    gold = RecipeLikenessResult(
        score=0.9,
        tier=RecipeLikenessTier.gold,
        backend="heuristic_v1",
        version="2026-02-28",
        features={"ingredient_count": 3, "instruction_count": 2},
        reasons=[],
    )
    silver_low_lines = RecipeLikenessResult(
        score=0.62,
        tier=RecipeLikenessTier.silver,
        backend="heuristic_v1",
        version="2026-02-28",
        features={"ingredient_count": 1, "instruction_count": 0},
        reasons=[],
    )
    bronze = RecipeLikenessResult(
        score=0.42,
        tier=RecipeLikenessTier.bronze,
        backend="heuristic_v1",
        version="2026-02-28",
        features={"ingredient_count": 2, "instruction_count": 1},
        reasons=[],
    )

    assert recipe_gate_action(gold, settings=settings) == "keep_full"
    assert recipe_gate_action(silver_low_lines, settings=settings) == "keep_partial"
    assert recipe_gate_action(bronze, settings=settings) == "keep_partial"


def test_summarize_recipe_likeness_includes_thresholds_and_stats() -> None:
    settings = RunSettings(
        recipe_score_gold_min=0.8,
        recipe_score_silver_min=0.6,
        recipe_score_bronze_min=0.4,
    )
    results = [
        RecipeLikenessResult(
            score=0.91,
            tier=RecipeLikenessTier.gold,
            backend="heuristic_v1",
            version="2026-02-28",
            features={},
            reasons=[],
        ),
        RecipeLikenessResult(
            score=0.65,
            tier=RecipeLikenessTier.silver,
            backend="heuristic_v1",
            version="2026-02-28",
            features={},
            reasons=[],
        ),
        RecipeLikenessResult(
            score=0.45,
            tier=RecipeLikenessTier.bronze,
            backend="heuristic_v1",
            version="2026-02-28",
            features={},
            reasons=[],
        ),
    ]

    summary = summarize_recipe_likeness(results, rejected_count=2, settings=settings)

    assert summary["backend"] == "heuristic_v1"
    assert summary["thresholds"] == {"gold": 0.8, "silver": 0.6, "bronze": 0.4}
    assert summary["counts"]["gold"] == 1
    assert summary["counts"]["silver"] == 1
    assert summary["counts"]["bronze"] == 1
    assert summary["rejectedCandidateCount"] == 2
    assert summary["scoreStats"]["max"] == 0.91
