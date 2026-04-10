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
from cookimport.parsing.recipe_span_grouping import recipe_boundary_from_labels


def _make_empty_label_first_original_result() -> ConversionResult:
    return ConversionResult(
        recipes=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path="/tmp/book.txt",
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
    original_result = _make_empty_label_first_original_result()

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
    assert [row["index"] for row in updated.outside_recipe_blocks] == [3]
    assert updated.outside_recipe_blocks[0]["text"] == "Why batter rests matters"
    assert updated.non_recipe_lines[0].final_label == "KNOWLEDGE"
    assert updated.span_decisions[0].decision == "accepted_recipe_span"


def _run_title_only_span_rejection_fixture() -> dict[str, object]:
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
    recipe_spans, span_decisions, _normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )
    original_result = _make_empty_label_first_original_result()

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=span_decisions,
    )
    return {"updated": updated}


def test_build_conversion_result_from_label_spans_rejects_empty_title_only_spans() -> None:
    fixture = _run_title_only_span_rejection_fixture()
    updated = fixture["updated"]
    result = updated.updated_conversion_result
    assert [recipe.name for recipe in result.recipes] == ["Bright Cabbage Slaw"]
    assert updated.recipe_spans[0].span_id == "recipe_span_1"


def test_build_conversion_result_from_label_spans_records_rejected_title_only_span() -> None:
    fixture = _run_title_only_span_rejection_fixture()
    updated = fixture["updated"]
    assert any(
        row.span_id == "recipe_span_0"
        and row.decision == "rejected_pseudo_recipe_span"
        and row.rejection_reason
        == "rejected_missing_ingredient_and_instruction_evidence"
        for row in updated.span_decisions
    )
    assert [row["index"] for row in updated.outside_recipe_blocks] == [0]


def test_build_conversion_result_from_label_spans_keeps_explicit_invariant_warning_instead_of_late_demotion() -> None:
    archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Bare Title",
            "location": {"block_index": 0},
        },
    ]
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Bare Title",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        )
    ]
    block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        )
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
        )
    ]
    original_result = _make_empty_label_first_original_result()

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
            )
        ],
    )

    result = updated.updated_conversion_result
    assert [recipe.name for recipe in result.recipes] == ["Bare Title"]
    assert updated.recipe_spans[0].span_id == "recipe_span_0"
    assert updated.span_decisions[0].decision == "accepted_recipe_span"
    assert (
        updated.span_decisions[0].warnings
        == ["accepted_recipe_span_projection_missing_body:recipe_span_0"]
    )


def test_build_conversion_result_from_label_spans_keeps_variant_rows_with_parent_recipe() -> None:
    archive_blocks = [
        {"index": 0, "block_id": "block:0", "text": "Bright Cabbage Slaw", "location": {"block_index": 0}},
        {"index": 1, "block_id": "block:1", "text": "1 small cabbage", "location": {"block_index": 1}},
        {"index": 2, "block_id": "block:2", "text": "Toss well and season to taste.", "location": {"block_index": 2}},
        {"index": 3, "block_id": "block:3", "text": "Variations", "location": {"block_index": 3}},
        {
            "index": 4,
            "block_id": "block:4",
            "text": "To make Asian Slaw, add ginger and sesame oil.",
            "location": {"block_index": 4},
        },
    ]
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Bright Cabbage Slaw",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 small cabbage",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Toss well and season to taste.",
            deterministic_label="INSTRUCTION_LINE",
            final_label="INSTRUCTION_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:3",
            source_block_index=3,
            atomic_index=3,
            text="Variations",
            deterministic_label="RECIPE_VARIANT",
            final_label="RECIPE_VARIANT",
            decided_by="codex",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:4",
            source_block_index=4,
            atomic_index=4,
            text="To make Asian Slaw, add ginger and sesame oil.",
            deterministic_label="RECIPE_VARIANT",
            final_label="RECIPE_VARIANT",
            decided_by="codex",
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
            deterministic_label="RECIPE_VARIANT",
            final_label="RECIPE_VARIANT",
            decided_by="codex",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:4",
            source_block_index=4,
            supporting_atomic_indices=[4],
            deterministic_label="RECIPE_VARIANT",
            final_label="RECIPE_VARIANT",
            decided_by="codex",
        ),
    ]
    recipe_spans, span_decisions, _normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )
    original_result = _make_empty_label_first_original_result()

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=block_labels,
        recipe_spans=recipe_spans,
        span_decisions=span_decisions,
    )

    result = updated.updated_conversion_result
    assert len(result.recipes) == 1
    assert result.recipes[0].name == "Bright Cabbage Slaw"
    assert result.recipes[0].instructions == [
        "Toss well and season to taste.",
        "Variations",
        "To make Asian Slaw, add ginger and sesame oil.",
    ]
    assert updated.outside_recipe_blocks == []
    assert updated.non_recipe_lines == []
    assert updated.updated_conversion_result.report.warnings == [
        "label_source_of_truth=label-first-v1"
    ]


def test_build_conversion_result_from_label_spans_routes_title_plus_yield_stub_to_nonrecipe() -> None:
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
    recipe_spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )
    original_result = _make_empty_label_first_original_result()

    updated = build_conversion_result_from_label_spans(
        source_file=Path("/tmp/book.txt"),
        importer_name="text",
        source_hash="hash-123",
        original_result=original_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=normalized_blocks,
        recipe_spans=recipe_spans,
        span_decisions=span_decisions,
    )

    result = updated.updated_conversion_result
    assert result.recipes == []
    assert updated.recipe_spans == []
    assert updated.span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert (
        updated.span_decisions[0].rejection_reason
        == "rejected_missing_ingredient_and_instruction_evidence"
    )
    assert [row["index"] for row in updated.outside_recipe_blocks] == [0, 1]
    assert [row.final_label for row in updated.block_labels] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_atomize_archive_blocks_ignores_old_recipe_provenance_before_grouping() -> None:
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

    assert [row.within_recipe_span for row in rows] == [None, None, None]
    assert [row.recipe_id for row in rows] == [None, None, None]
