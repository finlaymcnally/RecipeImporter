from __future__ import annotations

from copy import deepcopy

from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_GROUP_SCHEMA_VERSION,
    KNOWLEDGE_GROUP_STAGE_KEY,
    build_knowledge_classification_task_file,
    build_knowledge_grouping_task_file,
    validate_knowledge_grouping_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root="/tmp/worker-001",
    )


def _shard(*, block_index: int, text: str) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [{"i": block_index, "id": f"book.ks0000.nr:{block_index}", "t": text}],
        },
        metadata={"owned_block_indices": [block_index], "owned_block_count": 1},
    )


def test_grouping_task_file_only_contains_accepted_knowledge_units() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=5, text="Balsamic Vinaigrette"),
            _shard(block_index=6, text="Use low heat and whisk steadily."),
        ],
    )

    grouping_task_file, grouping_unit_to_shard_id = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::5": {
                "category": "other",
                "reviewer_category": "chapter_taxonomy",
            },
            "knowledge::6": {
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    assert grouping_task_file["schema_version"] == KNOWLEDGE_GROUP_SCHEMA_VERSION
    assert grouping_task_file["stage_key"] == KNOWLEDGE_GROUP_STAGE_KEY
    assert [unit["unit_id"] for unit in grouping_task_file["units"]] == ["knowledge::6"]
    assert grouping_unit_to_shard_id == {"knowledge::6": "book.ks0000.nr"}


def test_grouping_validator_requires_non_empty_group_fields() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(block_index=8, text="Use low heat and whisk steadily.")],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::8": {
                "category": "knowledge",
                "reviewer_category": "knowledge",
            }
        },
        unit_to_shard_id=unit_to_shard_id,
    )
    edited = deepcopy(grouping_task_file)
    edited["units"][0]["answer"] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {
        "knowledge::8": {
            "group_key": "heat-control",
            "topic_label": "Heat control",
        }
    }

    invalid = deepcopy(grouping_task_file)
    invalid["units"][0]["answer"] = {"group_key": "heat-control", "topic_label": ""}
    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == ("knowledge_block_missing_group",)
    assert metadata["failed_unit_ids"] == ["knowledge::8"]
    assert metadata["knowledge_blocks_missing_group"] == [8]
