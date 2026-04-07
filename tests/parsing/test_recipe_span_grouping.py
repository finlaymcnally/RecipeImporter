from __future__ import annotations

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
)
from cookimport.parsing.recipe_span_grouping import recipe_boundary_from_labels


def test_recipe_boundary_from_labels_splits_on_non_recipe_boundaries_and_rejects_incomplete_span() -> None:
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

    spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert [row.source_block_index for row in normalized_blocks] == [0, 1, 2, 3, 4, 5]
    assert len(spans) == 1
    assert [row.decision for row in span_decisions] == [
        "accepted_recipe_span",
        "rejected_pseudo_recipe_span",
    ]
    assert spans[0].block_indices == [0, 1, 2]
    assert spans[0].title_block_index == 0
    assert spans[0].escalation_reasons == []
    assert span_decisions[1].block_indices == [4, 5]
    assert span_decisions[1].title_block_index == 4
    assert span_decisions[1].rejection_reason == "rejected_missing_ingredient_evidence"
    assert "recipe_span_missing_ingredient_label" in span_decisions[1].warnings
    assert [row.final_label for row in normalized_blocks] == [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "KNOWLEDGE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_recipe_boundary_from_labels_rejects_recipeish_blocks_without_title() -> None:
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

    spans, span_decisions, _normalized_blocks = recipe_boundary_from_labels(
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


def test_recipe_boundary_from_labels_rejects_title_only_note_span_without_core_fields() -> None:
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

    spans, span_decisions, _normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert len(span_decisions) == 1
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert (
        span_decisions[0].rejection_reason
        == "rejected_missing_ingredient_and_instruction_evidence"
    )
    assert "recipe_span_missing_ingredient_label" in span_decisions[0].warnings
    assert "recipe_span_missing_instruction_label" in span_decisions[0].warnings
    assert "missing_required_recipe_fields" in span_decisions[0].escalation_reasons
    assert "span_missing_ingredient_block" in span_decisions[0].decision_notes
    assert "span_missing_instruction_block" in span_decisions[0].decision_notes


def test_recipe_boundary_from_labels_routes_rejected_title_only_blocks_to_nonrecipe() -> None:
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

    spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert len(span_decisions) == 1
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert (
        span_decisions[0].rejection_reason
        == "rejected_missing_ingredient_and_instruction_evidence"
    )
    assert normalized_blocks[0].deterministic_label == "RECIPE_TITLE"
    assert normalized_blocks[0].final_label == "NONRECIPE_CANDIDATE"
    assert "recipe_span_rejected_to_route" in normalized_blocks[0].reason_tags


def test_recipe_boundary_from_labels_rejects_title_plus_yield_stub() -> None:
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

    spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert (
        span_decisions[0].rejection_reason
        == "rejected_missing_ingredient_and_instruction_evidence"
    )
    assert [row.final_label for row in normalized_blocks] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_recipe_boundary_from_labels_rejects_title_plus_ingredients_without_instructions() -> None:
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Tomato Salad",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="2 tomatoes",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
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
    ]

    spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert spans == []
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert span_decisions[0].rejection_reason == "rejected_missing_instruction_evidence"
    assert "recipe_span_missing_instruction_label" in span_decisions[0].warnings
    assert [row.final_label for row in normalized_blocks] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_recipe_boundary_from_labels_keeps_anchored_recipe_through_single_nonrecipe_candidate_gap() -> None:
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
            deterministic_label="NONRECIPE_CANDIDATE",
            final_label="NONRECIPE_CANDIDATE",
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
            deterministic_label="NONRECIPE_CANDIDATE",
            final_label="NONRECIPE_CANDIDATE",
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

    spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )

    assert len(spans) == 1
    assert spans[0].block_indices == [0, 1, 2, 3, 4, 5]
    assert [row.decision for row in span_decisions] == ["accepted_recipe_span"]
    assert [row.final_label for row in normalized_blocks] == [
        "RECIPE_TITLE",
        "YIELD_LINE",
        "INGREDIENT_LINE",
        "RECIPE_NOTES",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
    ]
    assert normalized_blocks[3].decided_by == "fallback"
    assert "accepted_recipe_span_nonrecipe_gap_to_notes" in normalized_blocks[3].reason_tags
    assert (
        "accepted_recipe_span_nonrecipe_gap_to_notes"
        in normalized_blocks[3].escalation_reasons
    )
