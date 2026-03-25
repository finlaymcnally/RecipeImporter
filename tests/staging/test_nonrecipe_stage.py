from __future__ import annotations

import json
from pathlib import Path

from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, RecipeSpan
from cookimport.staging.nonrecipe_stage import (
    build_nonrecipe_stage_result,
    refine_nonrecipe_stage_result,
)
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
    authority_payload = json.loads(
        (tmp_path / "09_nonrecipe_authority.json").read_text(encoding="utf-8")
    )

    assert nonrecipe_payload["schema_version"] == "nonrecipe_seed_routing.v1"
    assert nonrecipe_payload["counts"]["review_eligible_blocks"] == 2
    assert nonrecipe_payload["counts"]["review_excluded_blocks"] == 0
    assert nonrecipe_payload["review_eligible_block_ids"] == ["b0", "b1"]
    assert "review_eligible_seed_block_category_by_index" not in nonrecipe_payload
    assert "seed_block_category_by_index" not in nonrecipe_payload
    assert authority_payload["schema_version"] == "nonrecipe_authority.v1"
    assert authority_payload["counts"]["final_authority_blocks"] == 0
    assert authority_payload["authoritative_block_category_by_index"] == {}
    assert knowledge_payload["pipeline"] == "off"
    assert knowledge_payload["schema_version"] == "nonrecipe_review_status.v1"
    assert knowledge_payload["review_status"] == "not_run"
    assert knowledge_payload["counts"]["snippets_written"] == 0
    assert knowledge_payload["counts"]["final_authority_blocks"] == 0
    assert knowledge_payload["unreviewed_block_category_by_index"] == {
        "0": "other",
        "1": "knowledge",
    }
    assert knowledge_payload["unreviewed_spans"][1]["span_id"] == "nr.knowledge.1.2"
    assert stage_result.routing.review_eligible_block_indices == [0, 1]
    assert stage_result.authority.authoritative_block_indices == []
    assert stage_result.review_status.reviewed_block_indices == []
    assert stage_result.review_status.unreviewed_review_eligible_block_indices == [0, 1]


def test_nonrecipe_stage_splits_routing_from_final_authority() -> None:
    seed = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        final_block_labels=[
            AuthoritativeBlockLabel(
                source_block_id="b0",
                source_block_index=0,
                supporting_atomic_indices=[],
                deterministic_label="OTHER",
                final_label="OTHER",
                decided_by="rule",
                reason_tags=[],
                review_exclusion_reason="front_matter",
            ),
            _block_label(1, "KNOWLEDGE"),
        ],
        recipe_spans=[],
    )

    assert seed.routing.review_excluded_block_indices == [0]
    assert seed.routing.review_eligible_block_indices == [1]
    assert seed.authority.authoritative_block_indices == [0]
    assert seed.authority.authoritative_block_category_by_index == {0: "other"}
    assert seed.review_status.reviewed_block_indices == []
    assert seed.review_status.unreviewed_review_eligible_block_indices == [1]
    assert seed.review_status.unreviewed_block_category_by_index == {1: "knowledge"}


def test_nonrecipe_stage_refinement_keeps_internal_reviewer_categories_internal() -> None:
    seed = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "SALT"},
        ],
        final_block_labels=[_block_label(0, "KNOWLEDGE")],
        recipe_spans=[],
    )

    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=[{"index": 0, "block_id": "b0", "text": "SALT"}],
        block_category_updates={0: "other"},
        reviewer_categories_by_block={0: "chapter_taxonomy"},
    )

    assert refined.block_category_by_index == {0: "other"}
    assert refined.authority.authoritative_block_indices == [0]
    assert refined.authority.authoritative_block_category_by_index == {0: "other"}
    assert refined.review_status.reviewed_block_indices == [0]
    assert refined.review_status.unreviewed_review_eligible_block_indices == []
    assert refined.refinement_report["reviewer_category_counts"] == {
        "chapter_taxonomy": 1
    }
    assert refined.refinement_report["changed_blocks"] == [
        {
            "block_index": 0,
            "seed_category": "knowledge",
            "final_category": "other",
            "reviewer_category": "chapter_taxonomy",
            "applied_chunk_ids": [],
        }
    ]


def test_nonrecipe_stage_writes_review_exclusion_ledger(tmp_path: Path) -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique text"},
        ],
        final_block_labels=[
            AuthoritativeBlockLabel(
                source_block_id="b0",
                source_block_index=0,
                supporting_atomic_indices=[],
                deterministic_label="OTHER",
                final_label="OTHER",
                decided_by="rule",
                reason_tags=[],
                review_exclusion_reason="front_matter",
            ),
            _block_label(1, "OTHER"),
        ],
        recipe_spans=[],
    )

    write_nonrecipe_stage_outputs(stage_result, tmp_path)

    payload = json.loads(
        (tmp_path / "08_nonrecipe_seed_routing.json").read_text(encoding="utf-8")
    )
    ledger_rows = [
        json.loads(line)
        for line in (tmp_path / "08_nonrecipe_review_exclusions.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert payload["counts"]["review_excluded_blocks"] == 1
    assert payload["review_excluded_block_indices"] == [0]
    assert payload["review_excluded_block_ids"] == ["b0"]
    assert ledger_rows == [
        {
            "block_id": "b0",
            "block_index": 0,
            "exclusion_source": "line_role",
            "final_category": "other",
            "preview": "Acknowledgments",
            "review_exclusion_reason": "front_matter",
        }
    ]
