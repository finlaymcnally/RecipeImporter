from __future__ import annotations

import pytest

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


def test_score_recipe_likeness_applies_pattern_penalties_from_flags_and_actions() -> None:
    base_candidate = RecipeCandidate(
        name="Herb Bread",
        recipeIngredient=[
            "2 cups bread flour",
            "1 tbsp olive oil",
            "1 tsp kosher salt",
            "1 tsp instant yeast",
        ],
        recipeInstructions=[
            "Whisk flour, salt, and yeast in a bowl.",
            "Add water and olive oil, then mix into a shaggy dough.",
            "Let rest, shape, and bake until deeply golden.",
        ],
        description="A straightforward overnight loaf with crisp crust and open crumb.",
        provenance={"location": {"start_block": 12}},
    )
    baseline = score_recipe_likeness(base_candidate, settings=RunSettings())
    assert baseline.features["pattern_penalty_total"] == 0.0

    flagged_candidate = RecipeCandidate(
        name=base_candidate.name,
        recipeIngredient=list(base_candidate.ingredients),
        recipeInstructions=list(base_candidate.instructions),
        description=base_candidate.description,
        provenance={
            "location": {
                "start_block": 12,
                "pattern_flags": ["toc_like_cluster"],
                "pattern_actions": [
                    {"action": "trim_candidate_start"},
                    {"action": "reject_overlap_duplicate_candidate"},
                ],
            }
        },
    )
    flagged = score_recipe_likeness(flagged_candidate, settings=RunSettings())

    assert flagged.features["pattern_toc_like_penalty"] == pytest.approx(0.18, abs=1e-4)
    assert flagged.features["pattern_duplicate_title_penalty"] == pytest.approx(0.09, abs=1e-4)
    assert flagged.features["pattern_overlap_duplicate_penalty"] == pytest.approx(0.26, abs=1e-4)
    assert flagged.features["pattern_penalty_total"] == pytest.approx(0.53, abs=1e-4)
    assert flagged.features["pattern_flag_toc_like_cluster"] is True
    assert flagged.features["pattern_flag_duplicate_title_intro"] is True
    assert flagged.features["pattern_flag_overlap_duplicate_candidate"] is True
    assert "pattern_toc_like_penalty" in flagged.reasons
    assert "pattern_duplicate_title_penalty" in flagged.reasons
    assert "pattern_overlap_duplicate_penalty" in flagged.reasons
    assert flagged.score < baseline.score
