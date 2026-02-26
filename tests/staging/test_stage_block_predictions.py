from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import (
    ChunkLane,
    ConversionReport,
    ConversionResult,
    KnowledgeChunk,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.staging.stage_block_predictions import build_stage_block_predictions


def _build_result() -> ConversionResult:
    recipe = RecipeCandidate(
        name="Simple Soup",
        recipeIngredient=["1 cup stock", "Salt"],
        recipeInstructions=["Heat stock.", "Variations: add herbs.", "Serve."],
        recipeYield="Serves 2",
        prepTime="PT10M",
        comment=[{"text": "Chef's note: taste first."}],
        provenance={"location": {"start_block": 0, "end_block": 7}},
    )

    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "blocks": [
                {"index": 0, "text": "Simple Soup", "features": {"is_heading": True}},
                {"index": 1, "text": "Serves 2"},
                {"index": 2, "text": "Prep time: 10 minutes"},
                {"index": 3, "text": "1 cup stock", "features": {"block_role": "ingredient_line"}},
                {"index": 4, "text": "Salt", "features": {"block_role": "ingredient_line"}},
                {"index": 5, "text": "Heat stock.", "features": {"block_role": "instruction_line"}},
                {"index": 6, "text": "Variations: add herbs.", "features": {"block_role": "instruction_line"}},
                {"index": 7, "text": "Chef's note: taste first."},
                {"index": 8, "text": "Use clean tools for food safety."},
            ],
            "block_count": 9,
        },
        metadata={"artifact_type": "extracted_blocks"},
    )

    return ConversionResult(
        recipes=[recipe],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="simple",
        workbookPath="/tmp/simple.txt",
    )


def test_build_stage_block_predictions_assigns_one_label_per_block(tmp_path: Path) -> None:
    result = _build_result()
    snippets_path = tmp_path / "snippets.jsonl"
    snippets_path.write_text(
        json.dumps(
            {
                "snippet_id": "k1",
                "provenance": {"block_indices": [8]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_stage_block_predictions(
        result,
        "simple",
        knowledge_snippets_path=snippets_path,
    )

    assert payload["schema_version"] == "stage_block_predictions.v1"
    assert payload["block_count"] == 9

    block_labels = payload["block_labels"]
    assert set(block_labels.keys()) == {str(index) for index in range(9)}

    assert block_labels["0"] == "RECIPE_TITLE"
    assert block_labels["1"] == "YIELD_LINE"
    assert block_labels["2"] == "TIME_LINE"
    assert block_labels["3"] == "INGREDIENT_LINE"
    assert block_labels["4"] == "INGREDIENT_LINE"
    assert block_labels["5"] == "INSTRUCTION_LINE"
    assert block_labels["6"] == "RECIPE_VARIANT"
    assert block_labels["7"] == "RECIPE_NOTES"
    assert block_labels["8"] == "KNOWLEDGE"

    label_blocks = payload["label_blocks"]
    for index in range(9):
        label = block_labels[str(index)]
        assert index in label_blocks[label]

    conflicts = payload["conflicts"]
    assert any(
        conflict.get("block_index") == 6
        and set(conflict.get("labels", [])) == {"INSTRUCTION_LINE", "RECIPE_VARIANT"}
        for conflict in conflicts
    )


def test_build_stage_block_predictions_falls_back_to_chunk_lane_knowledge() -> None:
    result = _build_result()
    result.non_recipe_blocks = [
        {"index": 8, "text": "Use clean tools for food safety.", "features": {}}
    ]
    result.chunks = [
        KnowledgeChunk(
            id="c0",
            lane=ChunkLane.KNOWLEDGE,
            text="Use clean tools for food safety.",
            blockIds=[0],
        )
    ]

    payload = build_stage_block_predictions(result, "simple")

    assert payload["block_labels"]["8"] == "KNOWLEDGE"
    assert 8 in payload["label_blocks"]["KNOWLEDGE"]
