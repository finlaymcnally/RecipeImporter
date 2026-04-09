from __future__ import annotations

from copy import deepcopy
import json

from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
    KNOWLEDGE_CLASSIFY_STAGE_KEY,
    build_task_file_answer_feedback,
    build_knowledge_classification_task_file,
    validate_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root="/tmp/worker-001",
    )


def _shard(*, shard_id: str, block_index: int, text: str) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id=shard_id,
        owned_ids=(shard_id,),
        input_payload={
            "v": "1",
            "bid": shard_id,
            "b": [{"i": block_index, "id": f"{shard_id}:{block_index}", "t": text, "hl": 2}],
            "x": {
                "p": [{"i": block_index - 1, "t": "Previous local context."}],
                "n": [{"i": block_index + 1, "t": "Next local context."}],
            },
        },
        metadata={"owned_block_indices": [block_index], "owned_block_count": 1},
    )


def test_classification_task_file_uses_split_schema_and_local_evidence_only() -> None:
    task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                block_index=14,
                text="Balsamic Vinaigrette",
            )
        ],
    )

    assert task_file["schema_version"] == KNOWLEDGE_CLASSIFY_SCHEMA_VERSION
    assert task_file["stage_key"] == KNOWLEDGE_CLASSIFY_STAGE_KEY
    assert "editable_json_pointers" not in task_file
    assert task_file["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert unit_to_shard_id == {"knowledge::14": "book.ks0000.nr"}
    assert task_file["ontology"]["catalog_version"] == "cookbook-tag-catalog-2026-03-30"
    unit = task_file["units"][0]
    assert unit["answer"] == {
        "category": None,
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }
    assert "group_key" not in unit["answer"]
    assert "topic_label" not in unit["answer"]
    assert unit["evidence"]["context_before"] == "Previous local context."
    assert unit["evidence"]["context_after"] == "Next local context."
    assert unit["evidence"]["structure"] == {"heading_level": 2, "table_hint": None}
    assert isinstance(unit["evidence"]["candidate_tag_keys"], list)


def test_classification_validator_rejects_invalid_other_grounding_and_preserves_repair_scope() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                block_index=21,
                text="Acid brightens rich food by balancing heaviness.",
            ),
            _shard(
                shard_id="book.ks0001.nr",
                block_index=22,
                text="Chapter 3: Dressings",
            ),
        ],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": ["bright"],
            "category_keys": ["flavor-profile"],
            "proposed_tags": [],
        },
    }
    edited["units"][1]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {
        "knowledge::21": {
            "category": "knowledge",
            "grounding": {
                "tag_keys": ["bright"],
                "category_keys": ["flavor-profile"],
                "proposed_tags": [],
            },
        },
        "knowledge::22": {
            "category": "other",
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        },
    }

    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": ["bright"],
            "category_keys": ["flavor-profile"],
            "proposed_tags": [],
        },
    }
    invalid["units"][1]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert "other_grounding_forbidden" in errors
    assert metadata["failed_unit_ids"] == ["knowledge::21"]
    repair_task_file = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=metadata["failed_unit_ids"],
        previous_answers_by_unit_id={
            "knowledge::21": invalid["units"][0]["answer"],
            "knowledge::22": invalid["units"][1]["answer"],
        },
        validation_feedback_by_unit_id={
            "knowledge::21": {"validation_errors": list(errors)}
        },
    )
    assert repair_task_file["mode"] == "repair"
    assert repair_task_file["schema_version"] == KNOWLEDGE_CLASSIFY_SCHEMA_VERSION
    assert [unit["unit_id"] for unit in repair_task_file["units"]] == ["knowledge::21"]


def test_classification_validator_keeps_ungrounded_knowledge_and_records_weak_grounding() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                block_index=31,
                text="Acid can wake up heavy dishes.",
            )
        ],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert metadata["weak_grounding_unit_ids"] == ["knowledge::31"]
    assert metadata["weak_grounding_block_indices"] == [31]
    assert metadata["weak_grounding_reason_counts"] == {"missing_grounding": 1}
    assert answers_by_unit_id == {
        "knowledge::31": {
            "category": "knowledge",
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        }
    }


def test_task_file_answer_feedback_is_filtered_to_each_failed_unit() -> None:
    feedback_by_unit_id = build_task_file_answer_feedback(
        validation_errors=(
            "other_grounding_forbidden",
            "invalid_category",
        ),
        validation_metadata={
            "failed_unit_ids": ["knowledge::21", "knowledge::22"],
            "error_details": [
                {
                    "path": "/units/knowledge::21/answer/grounding",
                    "code": "other_grounding_forbidden",
                    "message": "other rows must not carry grounding metadata",
                },
                {
                    "path": "/units/knowledge::22/answer/category",
                    "code": "invalid_category",
                    "message": "category must be 'knowledge' or 'other'",
                },
            ],
        },
    )

    assert feedback_by_unit_id == {
        "knowledge::21": {
            "validation_errors": ["other_grounding_forbidden"],
            "error_details": [
                {
                    "path": "/units/knowledge::21/answer/grounding",
                    "code": "other_grounding_forbidden",
                    "message": "other rows must not carry grounding metadata",
                }
            ],
        },
        "knowledge::22": {
            "validation_errors": ["invalid_category"],
            "error_details": [
                {
                    "path": "/units/knowledge::22/answer/category",
                    "code": "invalid_category",
                    "message": "category must be 'knowledge' or 'other'",
                }
            ],
        },
    }


def test_filtered_repair_feedback_stays_materially_smaller_than_repeated_shared_feedback() -> None:
    unit_count = 24
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [
                        {
                            "i": block_index,
                            "id": f"book.ks0000.nr:{block_index}",
                            "t": f"Knowledge block {block_index}",
                        }
                        for block_index in range(unit_count)
                    ],
                },
                metadata={
                    "owned_block_indices": list(range(unit_count)),
                    "owned_block_count": unit_count,
                },
            )
        ],
    )
    validation_errors = ("knowledge_missing_grounding",)
    error_details = [
        {
            "path": f"/units/knowledge::{block_index}/answer/grounding",
            "code": "knowledge_missing_grounding",
            "message": "x" * 2000,
        }
        for block_index in range(unit_count)
    ]
    failed_unit_ids = [f"knowledge::{block_index}" for block_index in range(unit_count)]

    filtered_feedback = build_task_file_answer_feedback(
        validation_errors=validation_errors,
        validation_metadata={
            "failed_unit_ids": failed_unit_ids,
            "error_details": error_details,
        },
    )
    filtered_repair_task = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=failed_unit_ids,
        previous_answers_by_unit_id={},
        validation_feedback_by_unit_id=filtered_feedback,
    )

    naive_feedback = {
        unit_id: {
            "validation_errors": list(validation_errors),
            "error_details": [dict(detail) for detail in error_details],
        }
        for unit_id in failed_unit_ids
    }
    naive_repair_task = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=failed_unit_ids,
        previous_answers_by_unit_id={},
        validation_feedback_by_unit_id=naive_feedback,
    )

    filtered_size = len(json.dumps(filtered_repair_task, sort_keys=True))
    naive_size = len(json.dumps(naive_repair_task, sort_keys=True))

    assert filtered_size < naive_size // 4
