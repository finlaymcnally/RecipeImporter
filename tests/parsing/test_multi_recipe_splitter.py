from __future__ import annotations

from cookimport.parsing.multi_recipe_splitter import (
    MultiRecipeSplitConfig,
    split_candidate_lines,
)


def test_split_candidate_lines_rules_v1_splits_two_recipes() -> None:
    lines = [
        "Recipe One",
        "Ingredients",
        "1 cup flour",
        "Instructions",
        "Mix ingredients.",
        "Bake until golden.",
        "Recipe Two",
        "Ingredients",
        "2 eggs",
        "Instructions",
        "Whisk eggs.",
        "Cook gently.",
    ]

    result = split_candidate_lines(
        lines,
        config=MultiRecipeSplitConfig(
            backend="rules_v1",
            min_ingredient_lines=1,
            min_instruction_lines=1,
            enable_for_the_guardrail=True,
            trace=False,
        ),
    )

    assert len(result.spans) == 2
    assert result.spans[0].start == 0
    assert result.spans[0].end == 6
    assert result.spans[1].start == 6
    assert result.spans[1].end == len(lines)


def test_split_candidate_lines_for_the_guardrail_suppresses_false_boundary() -> None:
    lines = [
        "Cake",
        "Ingredients",
        "1 cup flour",
        "Instructions",
        "Bake cake.",
        "For the frosting",
        "1 tbsp butter",
        "Stir until creamy.",
        "Cookie",
        "Ingredients",
        "2 eggs",
        "Instructions",
        "Whisk eggs.",
    ]

    guarded = split_candidate_lines(
        lines,
        config=MultiRecipeSplitConfig(
            backend="rules_v1",
            min_ingredient_lines=1,
            min_instruction_lines=1,
            enable_for_the_guardrail=True,
            trace=False,
        ),
    )
    unguarded = split_candidate_lines(
        lines,
        config=MultiRecipeSplitConfig(
            backend="rules_v1",
            min_ingredient_lines=1,
            min_instruction_lines=1,
            enable_for_the_guardrail=False,
            trace=False,
        ),
    )

    assert len(guarded.spans) == 2
    assert len(unguarded.spans) >= len(guarded.spans)
    assert guarded.spans[1].start == 8


def test_split_candidate_lines_passthrough_backends_return_single_span() -> None:
    lines = [
        "Recipe One",
        "Ingredients",
        "1 cup flour",
        "Instructions",
        "Mix ingredients.",
    ]
    for backend in ("legacy", "off"):
        result = split_candidate_lines(
            lines,
            config=MultiRecipeSplitConfig(
                backend=backend,
                min_ingredient_lines=1,
                min_instruction_lines=1,
                enable_for_the_guardrail=True,
                trace=False,
            ),
        )
        assert len(result.spans) == 1
        assert result.spans[0].start == 0
        assert result.spans[0].end == len(lines)


def test_split_candidate_lines_trace_payload_is_populated_when_enabled() -> None:
    lines = [
        "Recipe One",
        "Ingredients",
        "1 cup flour",
        "Instructions",
        "Mix ingredients.",
        "Recipe Two",
        "Ingredients",
        "2 eggs",
        "Instructions",
        "Whisk eggs.",
    ]

    result = split_candidate_lines(
        lines,
        config=MultiRecipeSplitConfig(
            backend="rules_v1",
            min_ingredient_lines=1,
            min_instruction_lines=1,
            enable_for_the_guardrail=True,
            trace=True,
        ),
    )

    assert result.trace is not None
    assert result.trace["backend"] == "rules_v1"
    assert "accepted_boundaries" in result.trace
    assert "rejected_boundaries" in result.trace

