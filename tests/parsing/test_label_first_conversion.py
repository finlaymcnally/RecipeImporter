from __future__ import annotations

from pathlib import Path

from cookimport.core.models import ConversionReport, ConversionResult
from cookimport.parsing.label_first_conversion import (
    build_conversion_result_from_label_spans,
)
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
    RecipeSpan,
    RecipeSpanDecision,
    _atomize_archive_blocks,
)


def test_build_conversion_result_from_label_spans_uses_authoritative_non_recipe_blocks() -> None:
    archive_blocks = [
        {"index": 0, "block_id": "block:0", "text": "Pancakes", "location": {"block_index": 0}},
        {"index": 1, "block_id": "block:1", "text": "1 cup flour", "location": {"block_index": 1}},
        {"index": 2, "block_id": "block:2", "text": "Whisk batter", "location": {"block_index": 2}},
        {"index": 3, "block_id": "block:3", "text": "Why batter rests matters", "location": {"block_index": 3}},
    ]
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
            source_block_id="block:3",
            source_block_index=3,
            atomic_index=3,
            text="Why batter rests matters",
            deterministic_label="KNOWLEDGE",
            final_label="KNOWLEDGE",
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
            supporting_atomic_indices=[3],
            deterministic_label="KNOWLEDGE",
            final_label="KNOWLEDGE",
            decided_by="rule",
        ),
    ]
    recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=2,
            block_indices=[0, 1, 2],
            source_block_ids=["block:0", "block:1", "block:2"],
            start_atomic_index=0,
            end_atomic_index=2,
            atomic_indices=[0, 1, 2],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]
    original_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[{"index": 99, "text": "old leftover"}],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path="/tmp/book.txt",
    )

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=[
            RecipeSpanDecision(
                span_id="recipe_span_0",
                decision="accepted_recipe_span",
                start_block_index=0,
                end_block_index=2,
                block_indices=[0, 1, 2],
                source_block_ids=["block:0", "block:1", "block:2"],
                start_atomic_index=0,
                end_atomic_index=2,
                atomic_indices=[0, 1, 2],
                title_block_index=0,
                title_atomic_index=0,
            )
        ],
    )

    result = updated.updated_conversion_result
    assert len(result.recipes) == 1
    assert result.recipes[0].name == "Pancakes"
    assert result.recipes[0].ingredients == ["1 cup flour"]
    assert result.recipes[0].instructions == ["Whisk batter"]
    assert [row["index"] for row in result.non_recipe_blocks] == [3]
    assert result.non_recipe_blocks[0]["text"] == "Why batter rests matters"
    assert updated.non_recipe_lines[0].final_label == "KNOWLEDGE"
    assert updated.span_decisions[0].decision == "accepted_recipe_span"


def test_build_conversion_result_from_label_spans_rejects_empty_title_only_spans() -> None:
    archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "DIFFUSION CALCULUS",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "Bright Cabbage Slaw",
            "location": {"block_index": 1},
        },
        {
            "index": 2,
            "block_id": "block:2",
            "text": "1 cabbage",
            "location": {"block_index": 2},
        },
        {
            "index": 3,
            "block_id": "block:3",
            "text": "Slice and toss.",
            "location": {"block_index": 3},
        },
    ]
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="DIFFUSION CALCULUS",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Bright Cabbage Slaw",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="1 cabbage",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:3",
            source_block_index=3,
            atomic_index=3,
            text="Slice and toss.",
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
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
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
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
    ]
    recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=0,
            block_indices=[0],
            source_block_ids=["block:0"],
            start_atomic_index=0,
            end_atomic_index=0,
            atomic_indices=[0],
            title_block_index=0,
            title_atomic_index=0,
        ),
        RecipeSpan(
            span_id="recipe_span_1",
            start_block_index=1,
            end_block_index=3,
            block_indices=[1, 2, 3],
            source_block_ids=["block:1", "block:2", "block:3"],
            start_atomic_index=1,
            end_atomic_index=3,
            atomic_indices=[1, 2, 3],
            title_block_index=1,
            title_atomic_index=1,
        ),
    ]
    original_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path="/tmp/book.txt",
    )

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=[
            RecipeSpanDecision(
                span_id="recipe_span_0",
                decision="accepted_recipe_span",
                start_block_index=0,
                end_block_index=0,
                block_indices=[0],
                source_block_ids=["block:0"],
                start_atomic_index=0,
                end_atomic_index=0,
                atomic_indices=[0],
                title_block_index=0,
                title_atomic_index=0,
            ),
            RecipeSpanDecision(
                span_id="recipe_span_1",
                decision="accepted_recipe_span",
                start_block_index=1,
                end_block_index=3,
                block_indices=[1, 2, 3],
                source_block_ids=["block:1", "block:2", "block:3"],
                start_atomic_index=1,
                end_atomic_index=3,
                atomic_indices=[1, 2, 3],
                title_block_index=1,
                title_atomic_index=1,
            ),
        ],
    )

    result = updated.updated_conversion_result
    assert [recipe.name for recipe in result.recipes] == ["Bright Cabbage Slaw"]
    assert updated.recipe_spans[0].span_id == "recipe_span_1"
    assert any(
        row.span_id == "recipe_span_0"
        and row.decision == "rejected_pseudo_recipe_span"
        and row.rejection_reason == "rejected_missing_recipe_body"
        for row in updated.span_decisions
    )
    assert [row["index"] for row in result.non_recipe_blocks] == [0]


def test_build_conversion_result_from_label_spans_keeps_title_plus_yield_stub() -> None:
    archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Tomato Vinaigrette",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "Makes about 1 cup",
            "location": {"block_index": 1},
        },
    ]
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
    recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=1,
            atomic_indices=[0, 1],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]
    original_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path="/tmp/book.txt",
    )

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=[
            RecipeSpanDecision(
                span_id="recipe_span_0",
                decision="accepted_recipe_span",
                start_block_index=0,
                end_block_index=1,
                block_indices=[0, 1],
                source_block_ids=["block:0", "block:1"],
                start_atomic_index=0,
                end_atomic_index=1,
                atomic_indices=[0, 1],
                title_block_index=0,
                title_atomic_index=0,
            )
        ],
    )

    result = updated.updated_conversion_result
    assert [recipe.name for recipe in result.recipes] == ["Tomato Vinaigrette"]
    assert result.recipes[0].recipe_yield == "Makes about 1 cup"
    assert updated.recipe_spans[0].span_id == "recipe_span_0"
    assert updated.span_decisions[0].decision == "accepted_recipe_span"


def test_atomize_archive_blocks_marks_recipe_provenance_as_within_span() -> None:
    archive_blocks = [
        {"index": 0, "block_id": "block:0", "text": "Pancakes", "location": {"block_index": 0}},
        {"index": 1, "block_id": "block:1", "text": "Makes 2", "location": {"block_index": 1}},
        {"index": 2, "block_id": "block:2", "text": "Preface text", "location": {"block_index": 2}},
    ]
    conversion_result = ConversionResult(
        recipes=[
            {
                "name": "Pancakes",
                "recipeIngredient": [],
                "recipeInstructions": [],
                "provenance": {"location": {"start_block": 0, "end_block": 1}},
            }
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path="/tmp/book.txt",
    )

    rows = _atomize_archive_blocks(
        archive_blocks,
        conversion_result=conversion_result,
        atomic_block_splitter="atomic-v1",
    )

    assert [row.within_recipe_span for row in rows] == [True, True, False]
    assert [row.recipe_id for row in rows] == ["recipe:0", "recipe:0", None]
