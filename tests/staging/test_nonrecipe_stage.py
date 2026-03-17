from __future__ import annotations

import json
from pathlib import Path

from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, RecipeSpan
from cookimport.staging.nonrecipe_stage import build_nonrecipe_stage_result
from cookimport.staging.writer import (
    OutputStats,
    write_knowledge_outputs_artifact,
    write_nonrecipe_stage_outputs,
)


def _block_label(index: int, label: str) -> AuthoritativeBlockLabel:
    return AuthoritativeBlockLabel(
        source_block_id=f"b{index}",
        source_block_index=index,
        supporting_atomic_indices=[],
        deterministic_label=label,
        final_label=label,
        decided_by="rule",
        reason_tags=[],
    )


def test_nonrecipe_stage_excludes_knowledge_inside_recipe_span() -> None:
    result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Intro"},
            {"index": 1, "block_id": "b1", "text": "Recipe title"},
            {"index": 2, "block_id": "b2", "text": "Technique note inside recipe"},
            {"index": 3, "block_id": "b3", "text": "Outro"},
        ],
        final_block_labels=[
            _block_label(0, "OTHER"),
            _block_label(1, "RECIPE_TITLE"),
            _block_label(2, "KNOWLEDGE"),
            _block_label(3, "KNOWLEDGE"),
        ],
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=1,
                end_block_index=3,
                block_indices=[1, 2],
                source_block_ids=["b1", "b2"],
            )
        ],
    )

    assert result.block_category_by_index == {0: "other", 3: "knowledge"}
    assert [span.span_id for span in result.nonrecipe_spans] == [
        "nr.other.0.1",
        "nr.knowledge.3.4",
    ]


def test_nonrecipe_stage_groups_contiguous_knowledge_and_normalizes_noise() -> None:
    result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Technique 1"},
            {"index": 1, "block_id": "b1", "text": "Technique 2"},
            {"index": 2, "block_id": "b2", "text": "Front matter"},
            {"index": 3, "block_id": "b3", "text": "Still front matter"},
        ],
        final_block_labels=[
            _block_label(0, "KNOWLEDGE"),
            _block_label(1, "KNOWLEDGE"),
            _block_label(2, "BOILERPLATE"),
            _block_label(3, "OTHER"),
        ],
        recipe_spans=[],
    )

    assert [span.span_id for span in result.knowledge_spans] == ["nr.knowledge.0.2"]
    assert [span.span_id for span in result.other_spans] == ["nr.other.2.4"]


def test_nonrecipe_stage_writes_canonical_artifacts_when_llm_off(tmp_path: Path) -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Intro"},
            {"index": 1, "block_id": "b1", "text": "Technique"},
        ],
        final_block_labels=[_block_label(0, "OTHER"), _block_label(1, "KNOWLEDGE")],
        recipe_spans=[],
    )
    stats = OutputStats(tmp_path)

    nonrecipe_path = write_nonrecipe_stage_outputs(
        stage_result,
        tmp_path,
        output_stats=stats,
    )
    knowledge_path = write_knowledge_outputs_artifact(
        run_root=tmp_path,
        stage_result=stage_result,
        llm_report={"enabled": False, "pipeline": "off"},
        snippet_records=[],
        output_stats=stats,
    )

    nonrecipe_payload = json.loads(nonrecipe_path.read_text(encoding="utf-8"))
    knowledge_payload = json.loads(knowledge_path.read_text(encoding="utf-8"))

    assert nonrecipe_payload["schema_version"] == "nonrecipe_spans.v2"
    assert nonrecipe_payload["counts"]["knowledge_spans"] == 1
    assert nonrecipe_payload["seed_counts"]["knowledge_spans"] == 1
    assert knowledge_payload["pipeline"] == "off"
    assert knowledge_payload["schema_version"] == "knowledge_outputs.v2"
    assert knowledge_payload["counts"]["snippets_written"] == 0
    assert knowledge_payload["knowledge_spans"][0]["span_id"] == "nr.knowledge.1.2"
    assert knowledge_payload["seed_knowledge_spans"][0]["span_id"] == "nr.knowledge.1.2"
