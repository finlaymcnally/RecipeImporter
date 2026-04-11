from __future__ import annotations

from copy import deepcopy

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


def test_classification_task_file_is_binary_and_tag_free() -> None:
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
    assert "ontology" not in task_file
    assert task_file["answer_schema"] == {
        "editable_pointer_pattern": "/units/*/answer",
        "required_keys": ["category"],
        "allowed_values": {"category": ["keep_for_review", "other"]},
        "example_answers": [
            {"category": "keep_for_review"},
            {"category": "other"},
        ],
    }
    assert unit_to_shard_id == {"knowledge::14": "book.ks0000.nr"}
    unit = task_file["units"][0]
    assert unit["answer"] == {"category": None}
    assert unit["evidence"]["context_before"] == "Previous local context."
    assert unit["evidence"]["context_after"] == "Next local context."


def test_classification_validator_accepts_only_binary_categories() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=21, text="Acid brightens rich food."),
            _shard(shard_id="book.ks0001.nr", block_index=22, text="Chapter opener."),
        ],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {"category": "keep_for_review"}
    edited["units"][1]["answer"] = {"category": "other"}

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {
        "knowledge::21": {"category": "keep_for_review"},
        "knowledge::22": {"category": "other"},
    }


def test_classification_validator_rejects_extra_answer_keys_and_invalid_categories() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(shard_id="book.ks0000.nr", block_index=31, text="Acid can wake up heavy dishes.")],
    )

    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {"tag_keys": ["bright"]},
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == (
        "classification_extra_answer_keys_forbidden",
        "invalid_category",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::31"]
    assert metadata["unresolved_block_indices"] == [31]


def test_classification_repair_scope_stays_filtered_to_failed_units() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=41, text="Use low heat."),
            _shard(shard_id="book.ks0001.nr", block_index=42, text="Decorative heading."),
        ],
    )
    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {"category": "knowledge"}
    invalid["units"][1]["answer"] = {"category": "other"}

    _answers, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=invalid,
    )

    repair_task_file = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=metadata["failed_unit_ids"],
        previous_answers_by_unit_id={
            "knowledge::41": invalid["units"][0]["answer"],
            "knowledge::42": invalid["units"][1]["answer"],
        },
        validation_feedback_by_unit_id=build_task_file_answer_feedback(
            validation_errors=errors,
            validation_metadata=metadata,
        ),
    )

    assert repair_task_file["mode"] == "repair"
    assert repair_task_file["schema_version"] == KNOWLEDGE_CLASSIFY_SCHEMA_VERSION
    assert [unit["unit_id"] for unit in repair_task_file["units"]] == ["knowledge::41"]
