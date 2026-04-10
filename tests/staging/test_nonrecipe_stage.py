from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
)
from cookimport.parsing.recipe_span_grouping import recipe_boundary_from_labels
from cookimport.staging.nonrecipe_stage import (
    block_rows_for_nonrecipe_late_outputs,
    build_nonrecipe_authority_contract,
    build_nonrecipe_stage_result,
    refine_nonrecipe_stage_result,
)
from cookimport.staging.recipe_ownership import build_recipe_ownership_result
from cookimport.staging.writer import (
    OutputStats,
    write_knowledge_outputs_artifact,
    write_nonrecipe_stage_outputs,
)
from tests.nonrecipe_stage_helpers import make_recipe_ownership_result


def _block_label(
    index: int,
    label: str,
) -> AuthoritativeBlockLabel:
    return AuthoritativeBlockLabel(
        source_block_id=f"b{index}",
        source_block_index=index,
        supporting_atomic_indices=[],
        deterministic_label=label,
        final_label=label,
        decided_by="rule",
        reason_tags=[],
    )


def _ownership_result(
    *,
    full_blocks: list[dict[str, object]],
    owned_block_indices: list[int] | None = None,
    divested_block_indices: list[int] | None = None,
) -> object:
    return make_recipe_ownership_result(
        owned_by_recipe_id={"urn:recipe:test:r0": list(owned_block_indices or [])},
        divested_by_recipe_id={"urn:recipe:test:r0": list(divested_block_indices or [])},
        all_block_indices=[
            int(block["index"])
            for block in full_blocks
        ],
    )


def test_nonrecipe_stage_ignores_recipe_local_blocks_inside_recipe_span() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Intro"},
        {"index": 1, "block_id": "b1", "text": "Recipe title"},
        {"index": 2, "block_id": "b2", "text": "Technique note inside recipe"},
        {"index": 3, "block_id": "b3", "text": "Outro"},
    ]
    result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "RECIPE_TITLE"),
            _block_label(2, "RECIPE_NOTES"),
            _block_label(3, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(
            full_blocks=full_blocks,
            owned_block_indices=[1, 2],
        ),
    )

    assert result.seed.seed_route_by_index == {0: "candidate", 3: "candidate"}
    assert [span.span_id for span in result.seed.seed_nonrecipe_spans] == [
        "nr.candidate.0.1",
        "nr.candidate.3.4",
    ]


def test_nonrecipe_stage_groups_contiguous_candidate_and_excluded_routes() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Technique 1"},
        {"index": 1, "block_id": "b1", "text": "Technique 2"},
        {"index": 2, "block_id": "b2", "text": "Front matter"},
        {"index": 3, "block_id": "b3", "text": "Still front matter"},
    ]
    result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
            _block_label(2, "NONRECIPE_EXCLUDE"),
            _block_label(3, "NONRECIPE_EXCLUDE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    assert [span.span_id for span in result.seed.seed_candidate_spans] == [
        "nr.candidate.0.2"
    ]
    assert [span.span_id for span in result.seed.seed_excluded_spans] == [
        "nr.exclude.2.4"
    ]


def test_nonrecipe_stage_normalizes_divested_recipe_local_labels_to_candidates() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Recipe title"},
        {"index": 1, "block_id": "b1", "text": "Serving note now outside recipe"},
        {"index": 2, "block_id": "b2", "text": "Front matter"},
    ]
    result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "RECIPE_TITLE"),
            _block_label(1, "RECIPE_NOTES"),
            _block_label(2, "NONRECIPE_EXCLUDE"),
        ],
        recipe_ownership_result=_ownership_result(
            full_blocks=full_blocks,
            owned_block_indices=[0],
            divested_block_indices=[1],
        ),
    )

    assert result.seed.seed_route_by_index == {1: "candidate", 2: "exclude"}
    assert result.routing.candidate_block_indices == [1]
    assert result.routing.excluded_block_indices == [2]
    assert result.routing.warnings == [
        "block 1: divested recipe-local label 'RECIPE_NOTES' normalized to NONRECIPE_CANDIDATE for nonrecipe routing"
    ]


def test_nonrecipe_stage_routes_rejected_recipe_boundary_span_to_candidate_queue() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Using Acid"},
        {"index": 1, "block_id": "b1", "text": "Makes 1 cup"},
    ]
    labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="b0",
            source_block_index=0,
            atomic_index=0,
            text="Using Acid",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="b1",
            source_block_index=1,
            atomic_index=1,
            text="Makes 1 cup",
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
    ]
    block_labels = [
        _block_label(0, "RECIPE_TITLE"),
        _block_label(1, "YIELD_LINE"),
    ]

    recipe_spans, span_decisions, normalized_blocks = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )
    ownership = build_recipe_ownership_result(
        full_blocks=full_blocks,
        recipe_spans=recipe_spans,
        recipes=[],
    )
    result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=normalized_blocks,
        recipe_ownership_result=ownership,
    )

    assert recipe_spans == []
    assert span_decisions[0].decision == "rejected_pseudo_recipe_span"
    assert ownership.owned_block_indices == []
    assert ownership.available_to_nonrecipe_block_indices == [0, 1]
    assert result.seed.seed_route_by_index == {0: "candidate", 1: "candidate"}
    assert result.routing.candidate_block_indices == [0, 1]
    assert result.routing.excluded_block_indices == []


def test_nonrecipe_stage_writes_canonical_artifacts_when_llm_off(tmp_path: Path) -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Intro"},
        {"index": 1, "block_id": "b1", "text": "Technique"},
    ]
    stage_result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
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
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
        {"index": 1, "block_id": "b1", "text": "Useful technique"},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    assert seed.routing.excluded_block_indices == [0]
    assert seed.routing.candidate_block_indices == [1]
    assert seed.authority.authoritative_block_indices == [0]
    assert seed.authority.authoritative_block_category_by_index == {0: "other"}
    assert seed.candidate_status.finalized_candidate_block_indices == []
    assert seed.candidate_status.unresolved_candidate_block_indices == [1]
    assert seed.candidate_status.unresolved_candidate_route_by_index == {1: "candidate"}


def test_nonrecipe_stage_refinement_tracks_reviewed_blocks_without_reviewer_metadata() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "SALT"},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=[{"index": 0, "block_id": "b0", "text": "SALT"}],
        block_category_updates={0: "other"},
    )

    assert refined.seed.seed_route_by_index == {0: "candidate"}
    assert refined.authority.authoritative_block_indices == [0]
    assert refined.authority.authoritative_block_category_by_index == {0: "other"}
    assert refined.candidate_status.finalized_candidate_block_indices == [0]
    assert refined.candidate_status.unresolved_candidate_block_indices == []
    assert refined.refinement_report["reviewed_block_count"] == 1


def test_nonrecipe_stage_refinement_keeps_grounding_metadata_visible() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acid brightens rich dishes."},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=[{"index": 0, "block_id": "b0", "text": "Acid brightens rich dishes."}],
        block_category_updates={0: "knowledge"},
        grounding_by_block={
            0: {
                "packet_id": "book.ks0000.nr",
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
            }
        },
        grounding_summary={
            "kept_knowledge_block_count": 1,
            "retrieval_gate_rejected_block_count": 0,
            "weak_grounding_block_count": 0,
            "weak_grounding_after_invalid_grounding_drop_count": 0,
            "weak_grounding_category_only_count": 0,
            "knowledge_blocks_grounded_to_existing_tags": 1,
            "knowledge_blocks_using_proposed_tags": 0,
            "tag_proposal_count": 0,
            "weak_grounding_reason_counts": {},
        },
    )

    assert refined.refinement_report["grounding_counts"] == {
        "kept_knowledge_block_count": 1,
        "retrieval_gate_rejected_block_count": 0,
        "weak_grounding_block_count": 0,
        "weak_grounding_after_invalid_grounding_drop_count": 0,
        "weak_grounding_category_only_count": 0,
        "knowledge_blocks_grounded_to_existing_tags": 1,
        "knowledge_blocks_using_proposed_tags": 0,
        "tag_proposal_count": 0,
        "weak_grounding_reason_counts": {},
    }
    assert refined.refinement_report["grounding_by_block"] == {
        "0": {
            "packet_id": "book.ks0000.nr",
            "grounding": {
                "tag_keys": ["bright"],
                "category_keys": ["flavor-profile"],
                "proposed_tags": [],
            },
        }
    }


def test_nonrecipe_stage_writes_exclusion_ledger(tmp_path: Path) -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
        {"index": 1, "block_id": "b1", "text": "Useful technique text"},
    ]
    stage_result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
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
            "exclusion_source": "line_role",
            "final_category": "other",
            "preview": "Acknowledgments",
        }
    ]


def test_nonrecipe_stage_requires_final_label_for_every_nonrecipe_block() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Intro"},
        {"index": 1, "block_id": "b1", "text": "Useful technique"},
    ]
    with pytest.raises(ValueError, match="Missing final block label for non-recipe block 1"):
        build_nonrecipe_stage_result(
            full_blocks=full_blocks,
            final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
            recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
        )


def test_nonrecipe_stage_rejects_invalid_final_nonrecipe_labels() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Useful technique"},
    ]
    with pytest.raises(
        ValueError,
        match="Invalid non-recipe route label at block 0: unexpected route label 'BROKEN_LABEL'",
    ):
        build_nonrecipe_stage_result(
            full_blocks=full_blocks,
            final_block_labels=[_block_label(0, "BROKEN_LABEL")],
            recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
        )


def test_nonrecipe_stage_rejects_recipe_only_labels_outside_recipe() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Heading"},
    ]
    with pytest.raises(
        ValueError,
        match="Invalid non-recipe route label at block 0: unexpected route label 'RECIPE_TITLE'",
    ):
        build_nonrecipe_stage_result(
            full_blocks=full_blocks,
            final_block_labels=[_block_label(0, "RECIPE_TITLE")],
            recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
        )


def test_nonrecipe_late_output_rows_use_candidate_queue_before_review() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
        {"index": 1, "block_id": "b1", "text": "Useful technique"},
    ]
    stage_result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    rows = block_rows_for_nonrecipe_late_outputs(
        full_blocks=full_blocks,
        stage_result=stage_result,
    )

    assert [row["index"] for row in rows] == [1]
    assert rows[0]["nonrecipe_final_category"] == "candidate"


def test_nonrecipe_authority_contract_uses_candidate_queue_before_review() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
        {"index": 1, "block_id": "b1", "text": "Useful technique"},
    ]
    stage_result = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    contract = build_nonrecipe_authority_contract(
        full_blocks=full_blocks,
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
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Useful technique"},
        {"index": 1, "block_id": "b1", "text": "History note"},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_CANDIDATE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )
    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=full_blocks,
        block_category_updates={0: "knowledge"},
    )

    contract = build_nonrecipe_authority_contract(
        full_blocks=full_blocks,
        stage_result=refined,
    )

    assert contract.late_output_mode == "final_authority"
    assert [row["index"] for row in contract.final_blocks] == [0]
    assert [row["index"] for row in contract.late_output_blocks] == [0]
    assert contract.scoring_view.unresolved_candidate_block_indices == [1]


def test_nonrecipe_stage_forces_excluded_rows_to_final_other_even_if_bad_map_leaks_in() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Acknowledgments"},
        {"index": 1, "block_id": "b1", "text": "Useful technique"},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[
            _block_label(0, "NONRECIPE_EXCLUDE"),
            _block_label(1, "NONRECIPE_CANDIDATE"),
        ],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    refined = refine_nonrecipe_stage_result(
        stage_result=seed,
        full_blocks=full_blocks,
        block_category_updates={0: "knowledge", 1: "knowledge"},
    )

    assert refined.authority.authoritative_block_indices == [0, 1]
    assert refined.authority.authoritative_block_category_by_index == {
        0: "other",
        1: "knowledge",
    }
    assert [span.span_id for span in refined.authority.authoritative_other_spans] == [
        "nr.other.0.1"
    ]
    assert [span.span_id for span in refined.authority.authoritative_knowledge_spans] == [
        "nr.knowledge.1.2"
    ]


def test_nonrecipe_stage_refinement_rejects_invalid_final_category() -> None:
    full_blocks = [
        {"index": 0, "block_id": "b0", "text": "Useful technique"},
    ]
    seed = build_nonrecipe_stage_result(
        full_blocks=full_blocks,
        final_block_labels=[_block_label(0, "NONRECIPE_CANDIDATE")],
        recipe_ownership_result=_ownership_result(full_blocks=full_blocks),
    )

    with pytest.raises(ValueError, match="Invalid final non-recipe label at block 0"):
        refine_nonrecipe_stage_result(
            stage_result=seed,
            full_blocks=full_blocks,
            block_category_updates={0: "maybe"},
        )
