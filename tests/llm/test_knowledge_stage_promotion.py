from __future__ import annotations

from types import SimpleNamespace

from cookimport.llm.codex_farm_knowledge_ingest import validate_knowledge_shard_output
from cookimport.llm.knowledge_stage.promotion import _collect_block_grounding_details
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
    combine_knowledge_task_file_outputs,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr", "book.ks0001.nr"),
        workspace_root="/tmp/worker-001",
    )


def _shard(
    *,
    shard_id: str,
    blocks: list[tuple[int, str]],
) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id=shard_id,
        owned_ids=(shard_id,),
        input_payload={
            "v": "1",
            "bid": shard_id,
            "b": [
                {"i": block_index, "id": f"{shard_id}:{block_index}", "t": text}
                for block_index, text in blocks
            ],
        },
        metadata={
            "owned_block_indices": [block_index for block_index, _text in blocks],
            "owned_block_count": len(blocks),
        },
    )


def test_promotion_projects_group_grounding_onto_final_rows() -> None:
    shards = [
        _shard(
            shard_id="book.ks0000.nr",
            blocks=[
                (10, "Balsamic Vinaigrette"),
                (11, "Acid brightens rich dishes by cutting heaviness."),
                (12, "A squeeze of lemon can rescue a heavy sauce."),
            ],
        ),
        _shard(
            shard_id="book.ks0001.nr",
            blocks=[(25, "Front matter fluff.")],
        ),
    ]
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=shards,
    )

    outputs = combine_knowledge_task_file_outputs(
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::10": {"category": "other"},
            "knowledge::11": {"category": "keep_for_review"},
            "knowledge::12": {"category": "keep_for_review"},
            "knowledge::25": {"category": "other"},
        },
        grouping_answers_by_unit_id={
            "knowledge::11": {
                "group_id": "g01",
                "topic_label": "Acid balance",
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            },
            "knowledge::12": {
                "group_id": "g01",
                "topic_label": "Acid balance",
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            },
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    assert outputs["book.ks0000.nr"] == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {
                "block_index": 10,
                "category": "other",
                "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
            },
            {
                "block_index": 11,
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
            },
            {
                "block_index": 12,
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
            },
        ],
        "idea_groups": [
            {
                "group_id": "g01",
                "topic_label": "Acid balance",
                "block_indices": [11, 12],
                "grounding": {
                    "tag_keys": ["bright"],
                    "category_keys": ["flavor-profile"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            }
        ],
    }
    assert outputs["book.ks0001.nr"] == {
        "packet_id": "book.ks0001.nr",
        "block_decisions": [
            {
                "block_index": 25,
                "category": "other",
                "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
            }
        ],
        "idea_groups": [],
    }
    for shard in shards:
        valid, errors, metadata = validate_knowledge_shard_output(
            shard,
            outputs[shard.shard_id],
        )
        assert valid is True
        assert errors == ()
        assert metadata["knowledge_decision_count"] >= 0


def test_grounding_detail_rollup_uses_group_oriented_counts() -> None:
    outputs = {
        "book.ks0000.nr": SimpleNamespace(
            block_decisions=(
                SimpleNamespace(
                    block_index=10,
                    category="other",
                    grounding=SimpleNamespace(tag_keys=(), category_keys=(), proposed_tags=()),
                ),
                SimpleNamespace(
                    block_index=11,
                    category="knowledge",
                    grounding=SimpleNamespace(
                        tag_keys=("heat-control",),
                        category_keys=("techniques",),
                        proposed_tags=(),
                    ),
                ),
                SimpleNamespace(
                    block_index=12,
                    category="knowledge",
                    grounding=SimpleNamespace(
                        tag_keys=(),
                        category_keys=("techniques",),
                        proposed_tags=(
                            SimpleNamespace(
                                key="rendering-fat",
                                display_name="Rendering fat",
                                category_key="techniques",
                            ),
                        ),
                    ),
                ),
            )
        )
    }

    _grounding_by_block, counts, proposal_rows = _collect_block_grounding_details(
        outputs=outputs,
        allowed_block_indices={10: "candidate", 11: "candidate", 12: "candidate"},
        proposal_metadata_by_packet_id={
            "book.ks0000.nr": {
                "kept_for_review_block_count": 2,
                "group_resolution_details": [
                    {
                        "group_id": "g01",
                        "topic_label": "Heat control",
                        "block_indices": [11],
                        "grounding": {
                            "tag_keys": ["saute"],
                            "category_keys": ["cooking-method"],
                            "proposed_tags": [],
                        },
                    },
                    {
                        "group_id": "g02",
                        "topic_label": "Rendering fat",
                        "block_indices": [12],
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": ["techniques"],
                            "proposed_tags": [
                                {
                                    "key": "rendering-fat",
                                    "display_name": "Rendering fat",
                                    "category_key": "techniques",
                                }
                            ],
                        },
                        "why_no_existing_tag": "No existing tag fits the rendering idea.",
                        "retrieval_query": "how to render chicken fat",
                    },
                ],
            }
        },
    )

    assert counts["kept_for_review_block_count"] == 2
    assert counts["kept_knowledge_block_count"] == 2
    assert counts["retrieval_gate_rejected_block_count"] == 1
    assert counts["knowledge_group_count"] == 2
    assert counts["knowledge_group_split_count"] == 1
    assert counts["knowledge_groups_using_existing_tags"] == 1
    assert counts["knowledge_groups_using_proposed_tags"] == 1
    assert counts["knowledge_blocks_grounded_to_existing_tags"] == 1
    assert counts["knowledge_blocks_using_proposed_tags"] == 1
    assert len(counts["group_resolution_details"]) == 2
    assert proposal_rows == [
        {
            "key": "rendering-fat",
            "display_name": "Rendering fat",
            "category_key": "techniques",
            "occurrence_count": 1,
            "packet_ids": ["book.ks0000.nr"],
            "block_indices": [12],
        }
    ]
