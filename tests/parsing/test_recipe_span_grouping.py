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
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Whisk batter",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:4",
            source_block_index=4,
            atomic_index=3,
            text="Waffles",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:5",
            source_block_index=5,
            atomic_index=4,
            text="Bake until crisp",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
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
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:2",
            source_block_index=2,
            supporting_atomic_indices=[2],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:3",
            source_block_index=3,
            supporting_atomic_indices=[],
            deterministic_label="KNOWLEDGE",
            final_label="KNOWLEDGE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:4",
            source_block_index=4,
            supporting_atomic_indices=[3],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:5",
            source_block_index=5,
            supporting_atomic_indices=[4],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
    ]

    spans, span_decisions, normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert [row.source_block_index for row in normalized_blocks] == [0, 1, 2, 3, 4, 5]
    assert len(spans) == 2
    assert [row.decision for row in span_decisions] == [
        "accepted_recipe_span",
        "accepted_recipe_span",
    ]
    assert spans[0].block_indices == [0, 1, 2]
    assert spans[0].title_block_index == 0
    assert spans[0].escalation_reasons == []
    assert spans[1].block_indices == [4, 5]
    assert spans[1].title_block_index == 4


def test_group_recipe_spans_from_labels_rejects_recipeish_blocks_without_title() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Whisk batter",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
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
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
    ]

    spans, span_decisions, _normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert len(span_decisions) == 1
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert span_decisions[0].rejection_reason == "rejected_missing_title_anchor"
    assert "recipe_span_missing_title_label" in span_decisions[0].warnings
    assert "missing_required_recipe_fields" in span_decisions[0].escalation_reasons
    assert "span_missing_title_block" in span_decisions[0].decision_notes


def test_group_recipe_spans_from_labels_rejects_title_only_note_span_without_body() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Weeknight Salad",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="A bright side dish for spring dinners.",
            deterministic_label="RECIPE_NOTES",
            final_label="RECIPE_NOTES",
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
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="RECIPE_NOTES",
            final_label="RECIPE_NOTES",
            decided_by="rule",
        ),
    ]

    spans, span_decisions, _normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert len(span_decisions) == 1
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert span_decisions[0].rejection_reason == "rejected_missing_recipe_body"
    assert "recipe_span_missing_recipe_body" in span_decisions[0].warnings
    assert "missing_required_recipe_fields" in span_decisions[0].escalation_reasons
    assert "span_missing_recipe_body" in span_decisions[0].decision_notes


def test_group_recipe_spans_from_labels_demotes_rejected_title_only_blocks_to_other() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:40",
            source_block_index=40,
            atomic_index=40,
            text="Using Acid",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
            reason_tags=["title_like"],
        ),
    ]
    block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:40",
            source_block_index=40,
            supporting_atomic_indices=[40],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
            reason_tags=["title_like"],
        ),
    ]

    spans, span_decisions, normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert len(span_decisions) == 1
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert span_decisions[0].rejection_reason == "rejected_missing_recipe_body"
    assert normalized_blocks[0].deterministic_label == "RECIPE_TITLE"
    assert normalized_blocks[0].final_label == "OTHER"
    assert "recipe_span_rejected_to_other" in normalized_blocks[0].reason_tags


def test_group_recipe_spans_from_labels_accepts_title_plus_yield_stub() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Tomato Vinaigrette",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Makes about 1 cup",
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
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
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
    ]

    spans, span_decisions, _normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert len(spans) == 1
    assert spans[0].block_indices == [0, 1]
    assert span_decisions[0].decision == "accepted_recipe_span"
    assert span_decisions[0].rejection_reason is None


def test_group_recipe_spans_from_labels_keeps_anchored_recipe_through_single_other_gap() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Vietnamese Cucumber Salad",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Serves 4 to 6",
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="3 scallions, finely sliced",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:3",
            source_block_index=3,
            atomic_index=3,
            text="1 large jalapeño, thinly sliced",
            deterministic_label="OTHER",
            final_label="OTHER",
            decided_by="codex",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:4",
            source_block_index=4,
            atomic_index=4,
            text="4 tablespoons lime juice",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:5",
            source_block_index=5,
            atomic_index=5,
            text="Serve immediately.",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
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
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:2",
            source_block_index=2,
            supporting_atomic_indices=[2],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:3",
            source_block_index=3,
            supporting_atomic_indices=[3],
            deterministic_label="OTHER",
            final_label="OTHER",
            decided_by="codex",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:4",
            source_block_index=4,
            supporting_atomic_indices=[4],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:5",
            source_block_index=5,
            supporting_atomic_indices=[5],
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
    ]

    spans, span_decisions, _normalized_blocks = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )

    assert len(spans) == 1
    assert spans[0].block_indices == [0, 1, 2, 3, 4, 5]
    assert [row.decision for row in span_decisions] == ["accepted_recipe_span"]
