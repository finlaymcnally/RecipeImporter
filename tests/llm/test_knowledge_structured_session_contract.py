from __future__ import annotations

import json

from cookimport.llm.knowledge_stage.structured_session_contract import (
    build_knowledge_edited_task_file_from_classification_response,
    build_knowledge_edited_task_file_from_grouping_response,
)
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
    build_knowledge_grouping_task_file,
    validate_knowledge_classification_task_file,
    validate_knowledge_grouping_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-structured-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root="/tmp/worker-structured-001",
    )


def _shard(*, shard_id: str, block_index: int, text: str) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id=shard_id,
        owned_ids=(shard_id,),
        input_payload={
            "v": "1",
            "bid": shard_id,
            "b": [{"i": block_index, "id": f"{shard_id}:{block_index}", "t": text}],
        },
        metadata={"owned_block_indices": [block_index], "owned_block_count": 1},
    )


def test_classification_structured_response_reports_missing_duplicate_and_unknown_row_ids() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                block_index=21,
                text="Acid brightens rich dishes.",
            ),
            _shard(
                shard_id="book.ks0001.nr",
                block_index=22,
                text="Chapter opener.",
            ),
        ],
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_classification_response(
        original_task_file=task_file,
        response_text=json.dumps(
            {
                "rows": [
                    {
                        "row_id": "r01",
                        "category": "knowledge",
                        "grounding": {
                            "tag_keys": ["bright"],
                            "category_keys": ["flavor-profile"],
                            "proposed_tags": [],
                        },
                    },
                    {
                        "row_id": "r01",
                        "category": "other",
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": [],
                            "proposed_tags": [],
                        },
                    },
                    {
                        "row_id": "r99",
                        "category": "other",
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": [],
                            "proposed_tags": [],
                        },
                    },
                ]
            }
        ),
    )

    assert edited is not None
    assert errors == (
        "knowledge_missing_response_rows",
        "knowledge_duplicate_row_ids",
        "knowledge_unknown_row_ids",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::21", "knowledge::22"]
    assert metadata["missing_block_indices"] == [22]
    assert metadata["missing_row_ids"] == ["r02"]
    assert metadata["duplicate_row_ids"] == ["r01"]
    assert metadata["unknown_row_ids"] == ["r99"]
    assert edited["units"][0]["answer"]["category"] == "knowledge"
    assert edited["units"][1]["answer"]["category"] is None

    _answers, validation_errors, validation_metadata = (
        validate_knowledge_classification_task_file(
            original_task_file=task_file,
            edited_task_file=edited,
        )
    )

    assert "knowledge_block_missing_decision" in validation_errors
    assert "invalid_category" not in validation_errors
    assert validation_metadata["failed_unit_ids"] == ["knowledge::22"]
    assert validation_metadata["missing_block_indices"] == [22]


def test_grouping_structured_response_reports_missing_duplicate_and_unknown_row_ids() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                block_index=31,
                text="Use gentle heat for eggs.",
            ),
            _shard(
                shard_id="book.ks0001.nr",
                block_index=32,
                text="Rest dough before rolling.",
            ),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id=str(classification_task_file.get("assignment_id") or ""),
        worker_id=str(classification_task_file.get("worker_id") or ""),
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::31": {
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["heat-control"],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
            },
            "knowledge::32": {
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["resting"],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
            },
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "rows": [
                    {
                        "row_id": "r01",
                        "group_key": "heat-control",
                        "topic_label": "Heat control",
                    },
                    {
                        "row_id": "r01",
                        "group_key": "heat-control-duplicate",
                        "topic_label": "Duplicate",
                    },
                    {
                        "row_id": "r99",
                        "group_key": "unexpected",
                        "topic_label": "Unexpected",
                    },
                ]
            }
        ),
    )

    assert edited is not None
    assert errors == (
        "knowledge_missing_response_rows",
        "knowledge_duplicate_row_ids",
        "knowledge_unknown_row_ids",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::31", "knowledge::32"]
    assert metadata["missing_block_indices"] == [32]
    assert metadata["missing_row_ids"] == ["r02"]
    assert metadata["duplicate_row_ids"] == ["r01"]
    assert metadata["unknown_row_ids"] == ["r99"]
    assert edited["units"][0]["answer"] == {
        "group_key": "heat-control",
        "topic_label": "Heat control",
    }
    assert edited["units"][1]["answer"] == {}

    _answers, validation_errors, validation_metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )

    assert validation_errors == ("knowledge_block_missing_group",)
    assert validation_metadata["failed_unit_ids"] == ["knowledge::32"]
    assert validation_metadata["knowledge_blocks_missing_group"] == [32]
