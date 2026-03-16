from __future__ import annotations

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
)
from cookimport.parsing.recipe_span_grouping import group_recipe_spans_from_labels


def test_group_recipe_spans_from_labels_splits_on_non_recipe_boundaries() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Whisk batter",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:4",
            source_block_index=4,
            atomic_index=3,
            text="Waffles",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:5",
            source_block_index=5,
            atomic_index=4,
            text="Bake until crisp",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
    ]
    block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:2",
            source_block_index=2,
            supporting_atomic_indices=[2],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:3",
            source_block_index=3,
            supporting_atomic_indices=[],
            deterministic_label="KNOWLEDGE",
            final_label="KNOWLEDGE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:4",
            source_block_index=4,
            supporting_atomic_indices=[3],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:5",
            source_block_index=5,
            supporting_atomic_indices=[4],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
    ]

    spans, normalized_blocks = group_recipe_spans_from_labels(block_labels, labeled_lines)

    assert [row.source_block_index for row in normalized_blocks] == [0, 1, 2, 3, 4, 5]
    assert len(spans) == 2
    assert spans[0].block_indices == [0, 1, 2]
    assert spans[0].title_block_index == 0
    assert spans[1].block_indices == [4, 5]
    assert spans[1].title_block_index == 4


def test_group_recipe_spans_from_labels_warns_when_recipeish_blocks_have_no_title() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Whisk batter",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
    ]
    block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            confidence=0.9,
            decided_by="rule",
        ),
    ]

    spans, _normalized_blocks = group_recipe_spans_from_labels(block_labels, labeled_lines)

    assert len(spans) == 1
    assert "recipe_span_missing_title_label" in spans[0].warnings
