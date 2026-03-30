from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, RecipeSpan
from cookimport.staging.nonrecipe_stage import (
    block_rows_for_nonrecipe_late_outputs,
    build_nonrecipe_authority_contract,
    build_nonrecipe_stage_result,
    refine_nonrecipe_stage_result,
)
from cookimport.staging.writer import (
    OutputStats,
    write_knowledge_outputs_artifact,
    write_nonrecipe_stage_outputs,
)


def _block_label(
    index: int,
    label: str,
    *,
    exclusion_reason: str | None = None,
) -> AuthoritativeBlockLabel:
    return AuthoritativeBlockLabel(
        source_block_id=f"b{index}",
        source_block_index=index,
        supporting_atomic_indices=[],
        deterministic_label=label,
        final_label=label,
        decided_by="rule",
        reason_tags=[],
        exclusion_reason=exclusion_reason,
    )


def test_nonrecipe_stage_ignores_recipe_local_blocks_inside_recipe_span() -> None:
    result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Intro"},
            {"index": 1, "block_id": "b1", "text": "Recipe title"},
            {"index": 2, "block_id": "b2", "text": "Technique note inside recipe"},
            {"index": 3, "block_id": "b3", "text": "Outro"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "RECIPE_TITLE"),
            _block_label(2, "RECIPE_NOTES"),
            _block_label(3, "NONRECIPE_CANDIDATE"),
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

    assert result.seed.seed_route_by_index == {0: "candidate", 3: "candidate"}
    assert [span.span_id for span in result.seed.seed_nonrecipe_spans] == [
        "nr.candidate.0.1",
        "nr.candidate.3.4",
    ]


def test_nonrecipe_stage_groups_contiguous_candidate_and_excluded_routes() -> None:
    result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Technique 1"},
            {"index": 1, "block_id": "b1", "text": "Technique 2"},
            {"index": 2, "block_id": "b2", "text": "Front matter"},
            {"index": 3, "block_id": "b3", "text": "Still front matter"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
            _block_label(2, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
            _block_label(3, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
        ],
        recipe_spans=[],
    )

    assert [span.span_id for span in result.seed.seed_candidate_spans] == [
        "nr.candidate.0.2"
    ]
    assert [span.span_id for span in result.seed.seed_excluded_spans] == [
        "nr.exclude.2.4"
    ]


def test_nonrecipe_stage_writes_canonical_artifacts_when_llm_off(tmp_path: Path) -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Intro"},
            {"index": 1, "block_id": "b1", "text": "Technique"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE", exclusion_reason="navigation"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )
    stats = OutputStats(tmp_path)

    nonrecipe_path = write_nonrecipe_stage_outputs(
        stage_result,
        tmp_path,
        output_stats=stats,
    )
    candidate_status_path = write_knowledge_outputs_artifact(
        run_root=tmp_path,
        stage_result=stage_result,
        llm_report={"enabled": False, "pipeline": "off"},
        knowledge_group_records=[],
        snippet_records=[],
        output_stats=stats,
    )

    nonrecipe_payload = json.loads(nonrecipe_path.read_text(encoding="utf-8"))
    candidate_status_payload = json.loads(
        candidate_status_path.read_text(encoding="utf-8")
    )
    authority_payload = json.loads(
        (tmp_path / "09_nonrecipe_authority.json").read_text(encoding="utf-8")
    )

    assert nonrecipe_payload["schema_version"] == "nonrecipe_route.v1"
    assert nonrecipe_payload["counts"]["candidate_blocks"] == 1
    assert nonrecipe_payload["counts"]["excluded_blocks"] == 1
    assert nonrecipe_payload["candidate_block_ids"] == ["b1"]
    assert nonrecipe_payload["excluded_block_ids"] == ["b0"]
    assert authority_payload["schema_version"] == "nonrecipe_authority.v1"
    assert authority_payload["counts"]["final_authority_blocks"] == 1
    assert authority_payload["authoritative_block_category_by_index"] == {"0": "other"}
    assert candidate_status_payload["pipeline"] == "off"
    assert candidate_status_payload["schema_version"] == "nonrecipe_finalize_status.v1"
    assert candidate_status_payload["candidate_status"] == "not_run"
    assert candidate_status_payload["counts"]["snippets_written"] == 0
    assert candidate_status_payload["counts"]["final_authority_blocks"] == 1
    assert candidate_status_payload["unresolved_candidate_route_by_index"] == {
        "1": "candidate",
    }
    assert candidate_status_payload["unresolved_candidate_spans"][0]["span_id"] == (
        "nr.candidate.1.2"
    )
    assert stage_result.routing.candidate_block_indices == [1]
    assert stage_result.authority.authoritative_block_indices == [0]
    assert stage_result.candidate_status.finalized_candidate_block_indices == []
    assert stage_result.candidate_status.unresolved_candidate_block_indices == [1]


def test_nonrecipe_stage_splits_routing_from_final_authority() -> None:
    seed = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )

    assert seed.routing.excluded_block_indices == [0]
    assert seed.routing.candidate_block_indices == [1]
    assert seed.authority.authoritative_block_indices == [0]
    assert seed.authority.authoritative_block_category_by_index == {0: "other"}
    assert seed.candidate_status.finalized_candidate_block_indices == []
    assert seed.candidate_status.unresolved_candidate_block_indices == [1]
    assert seed.candidate_status.unresolved_candidate_route_by_index == {1: "candidate"}


def test_nonrecipe_stage_refinement_keeps_internal_reviewer_categories_internal() -> None:
    seed = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "SALT"},
        ],
        final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
        recipe_spans=[],
    )

    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=[{"index": 0, "block_id": "b0", "text": "SALT"}],
        block_category_updates={0: "other"},
        reviewer_categories_by_block={0: "chapter_taxonomy"},
    )

    assert refined.seed.seed_route_by_index == {0: "candidate"}
    assert refined.authority.authoritative_block_indices == [0]
    assert refined.authority.authoritative_block_category_by_index == {0: "other"}
    assert refined.candidate_status.finalized_candidate_block_indices == [0]
    assert refined.candidate_status.unresolved_candidate_block_indices == []
    assert refined.refinement_report["reviewer_category_counts"] == {
        "chapter_taxonomy": 1
    }


def test_nonrecipe_stage_writes_exclusion_ledger(tmp_path: Path) -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique text"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )

    write_nonrecipe_stage_outputs(stage_result, tmp_path)

    payload = json.loads(
        (tmp_path / "08_nonrecipe_route.json").read_text(encoding="utf-8")
    )
    ledger_rows = [
        json.loads(line)
        for line in (tmp_path / "08_nonrecipe_exclusions.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert payload["counts"]["excluded_blocks"] == 1
    assert payload["excluded_block_indices"] == [0]
    assert payload["excluded_block_ids"] == ["b0"]
    assert ledger_rows == [
        {
            "block_id": "b0",
            "block_index": 0,
            "exclusion_reason": "front_matter",
            "exclusion_source": "line_role",
            "final_category": "other",
            "preview": "Acknowledgments",
        }
    ]


def test_nonrecipe_stage_requires_final_label_for_every_nonrecipe_block() -> None:
    with pytest.raises(ValueError, match="Missing final block label for non-recipe block 1"):
        build_nonrecipe_stage_result(
            full_blocks=[
                {"index": 0, "block_id": "b0", "text": "Intro"},
                {"index": 1, "block_id": "b1", "text": "Useful technique"},
            ],
            final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
            recipe_spans=[],
        )


def test_nonrecipe_stage_rejects_invalid_final_nonrecipe_labels() -> None:
    with pytest.raises(
        ValueError,
        match="Invalid non-recipe route label at block 0: unexpected route label 'BROKEN_LABEL'",
    ):
        build_nonrecipe_stage_result(
            full_blocks=[
                {"index": 0, "block_id": "b0", "text": "Useful technique"},
            ],
            final_block_labels=[_block_label(0, "BROKEN_LABEL")],
            recipe_spans=[],
        )


def test_nonrecipe_stage_rejects_recipe_only_labels_outside_recipe() -> None:
    with pytest.raises(
        ValueError,
        match="Invalid non-recipe route label at block 0: unexpected route label 'RECIPE_TITLE'",
    ):
        build_nonrecipe_stage_result(
            full_blocks=[
                {"index": 0, "block_id": "b0", "text": "Heading"},
            ],
            final_block_labels=[_block_label(0, "RECIPE_TITLE")],
            recipe_spans=[],
        )


def test_nonrecipe_late_output_rows_use_candidate_queue_before_review() -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )

    rows = block_rows_for_nonrecipe_late_outputs(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        stage_result=stage_result,
    )

    assert [row["index"] for row in rows] == [1]
    assert rows[0]["nonrecipe_final_category"] == "candidate"


def test_nonrecipe_authority_contract_uses_candidate_queue_before_review() -> None:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE", exclusion_reason="front_matter"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )

    contract = build_nonrecipe_authority_contract(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
            {"index": 1, "block_id": "b1", "text": "Useful technique"},
        ],
        stage_result=stage_result,
    )

    assert contract.late_output_mode == "candidate_queue"
    assert [row["index"] for row in contract.final_blocks] == [0]
    assert [row["index"] for row in contract.candidate_queue_blocks] == [1]
    assert [row["index"] for row in contract.excluded_blocks] == [0]
    assert [row["index"] for row in contract.late_output_blocks] == [1]
    assert contract.scoring_view.authoritative_block_category_by_index == {0: "other"}
    assert contract.scoring_view.unresolved_candidate_route_by_index == {1: "candidate"}


def test_nonrecipe_authority_contract_uses_final_authority_after_review() -> None:
    seed = build_nonrecipe_stage_result(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Useful technique"},
            {"index": 1, "block_id": "b1", "text": "History note"},
        ],
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_spans=[],
    )
    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Useful technique"},
            {"index": 1, "block_id": "b1", "text": "History note"},
        ],
        block_category_updates={0: "knowledge"},
    )

    contract = build_nonrecipe_authority_contract(
        full_blocks=[
            {"index": 0, "block_id": "b0", "text": "Useful technique"},
            {"index": 1, "block_id": "b1", "text": "History note"},
        ],
        stage_result=refined,
    )

    assert contract.late_output_mode == "final_authority"
    assert [row["index"] for row in contract.final_blocks] == [0]
    assert [row["index"] for row in contract.late_output_blocks] == [0]
    assert contract.scoring_view.unresolved_candidate_block_indices == [1]
