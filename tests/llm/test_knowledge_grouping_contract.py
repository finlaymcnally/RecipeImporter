from __future__ import annotations

from copy import deepcopy

from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_GROUP_SCHEMA_VERSION,
    KNOWLEDGE_GROUP_STAGE_KEY,
    KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    build_knowledge_classification_task_file,
    build_knowledge_grouping_task_file,
    build_knowledge_grouping_task_files,
    validate_knowledge_grouping_task_file,
)
from cookimport.llm.knowledge_stage.structured_session_contract import (
    build_knowledge_edited_task_file_from_grouping_response,
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
            "knowledge::5": {"category": "other"},
            "knowledge::6": {"category": "knowledge"},
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
            "knowledge::8": {"category": "knowledge"}
        },
        unit_to_shard_id=unit_to_shard_id,
    )
    edited = deepcopy(grouping_task_file)
    edited["units"][0]["answer"] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
        "proposal_decision": "not_applicable",
        "proposed_tag": None,
        "why_no_existing_tag": None,
        "retrieval_query": None,
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
            "proposal_decision": "not_applicable",
            "proposed_tag": None,
            "why_no_existing_tag": None,
            "retrieval_query": None,
        }
    }

    invalid = deepcopy(grouping_task_file)
    invalid["units"][0]["answer"] = {"group_key": "heat-control", "topic_label": ""}
    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == (
        "knowledge_block_missing_group",
        "invalid_proposal_decision",
        "knowledge_grouping_proposal_forbidden",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::8"]
    assert metadata["knowledge_blocks_missing_group"] == [8]


def test_grouping_validator_accepts_approved_ingredient_proposal_category() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(block_index=9, text="Choose fresh extra-virgin olive oil.")],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::9": {"category": "proposal_candidate"}
        },
        unit_to_shard_id=unit_to_shard_id,
    )
    edited = deepcopy(grouping_task_file)
    edited["units"][0]["answer"] = {
        "group_key": "olive-oil-selection",
        "topic_label": "Choosing olive oil",
        "proposal_decision": "approved",
        "proposed_tag": {
            "key": "extra-virgin-olive-oil-selection",
            "display_name": "Choosing extra-virgin olive oil",
            "category_key": "ingredients",
        },
        "why_no_existing_tag": "This captures ingredient selection guidance not covered by an existing tag.",
        "retrieval_query": "how to choose extra virgin olive oil",
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {
        "knowledge::9": {
            "group_key": "olive-oil-selection",
            "topic_label": "Choosing olive oil",
            "proposal_decision": "approved",
            "proposed_tag": {
                "key": "extra-virgin-olive-oil-selection",
                "display_name": "Choosing extra-virgin olive oil",
                "category_key": "ingredients",
            },
            "why_no_existing_tag": "This captures ingredient selection guidance not covered by an existing tag.",
            "retrieval_query": "how to choose extra virgin olive oil",
        }
    }


def test_grouping_task_files_keep_large_grouping_scope_in_one_task_file() -> None:
    block_count = KNOWLEDGE_GROUP_TASK_MAX_UNITS + 1
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
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
                        for block_index in range(block_count)
                    ],
                },
                metadata={
                    "owned_block_indices": list(range(block_count)),
                    "owned_block_count": block_count,
                },
            )
        ],
    )
    classification_answers_by_unit_id = {
        f"knowledge::{block_index}": {"category": "knowledge"}
        for block_index in range(block_count)
    }

    task_files, grouping_unit_to_shard_id, batch_unit_ids = build_knowledge_grouping_task_files(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id=classification_answers_by_unit_id,
        unit_to_shard_id=unit_to_shard_id,
    )

    assert len(task_files) == 1
    assert len(batch_unit_ids) == 1
    assert len(task_files[0]["units"]) == block_count
    assert task_files[0]["grouping_batch"] == {
        "current_batch_index": 1,
        "total_batches": 1,
        "unit_count": block_count,
        "total_grouping_unit_count": block_count,
        "remaining_batches_after_this": 0,
        "estimated_evidence_chars": task_files[0]["grouping_batch"]["estimated_evidence_chars"],
        "max_units_per_batch": KNOWLEDGE_GROUP_TASK_MAX_UNITS,
        "max_evidence_chars_per_batch": task_files[0]["grouping_batch"][
            "max_evidence_chars_per_batch"
        ],
        "shard_ids": ["book.ks0000.nr"],
    }
    assert set(batch_unit_ids[0]) == {
        f"knowledge::{block_index}" for block_index in range(block_count)
    }
    assert grouping_unit_to_shard_id[f"knowledge::{block_count - 1}"] == "book.ks0000.nr"


def test_grouping_task_files_use_custom_limits_from_classification_task() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [
                        {"i": 1, "id": "book.ks0000.nr:1", "t": "A" * 40},
                        {"i": 2, "id": "book.ks0000.nr:2", "t": "B" * 40},
                        {"i": 3, "id": "book.ks0000.nr:3", "t": "C" * 40},
                    ],
                },
                metadata={"owned_block_indices": [1, 2, 3], "owned_block_count": 3},
            )
        ],
        knowledge_group_task_max_units=2,
        knowledge_group_task_max_evidence_chars=10_000,
    )
    classification_answers_by_unit_id = {
        "knowledge::1": {"category": "knowledge"},
        "knowledge::2": {"category": "knowledge"},
        "knowledge::3": {"category": "knowledge"},
    }

    transition_task_file, _grouping_unit_to_shard_id = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id=classification_answers_by_unit_id,
        unit_to_shard_id=unit_to_shard_id,
        max_units_per_batch=int(
            classification_task_file["grouping_limits"]["max_units_per_batch"]
        ),
        max_evidence_chars_per_batch=int(
            classification_task_file["grouping_limits"]["max_evidence_chars_per_batch"]
        ),
    )

    assert classification_task_file["grouping_limits"] == {
        "max_units_per_batch": 2,
        "max_evidence_chars_per_batch": 10_000,
    }
    assert len(transition_task_file["units"]) == 3
    assert transition_task_file["grouping_batch"]["max_units_per_batch"] == 2
    assert transition_task_file["grouping_batch"]["total_batches"] == 1


def test_structured_grouping_response_accepts_group_index_alias() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(block_index=8, text="Use low heat and whisk steadily.")],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::8": {"category": "knowledge"}
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=(
            '{"rows":[{"row_id":"r01","group_index":"heat-control","topic_label":"Heat control","proposal_decision":"not_applicable","proposed_tag":null,"why_no_existing_tag":null,"retrieval_query":null}]}'
        ),
    )

    assert edited is not None
    assert errors == ()
    assert metadata == {}
    assert edited["units"][0]["answer"] == {
        "group_key": "heat-control",
        "topic_label": "Heat control",
        "proposal_decision": "not_applicable",
        "proposed_tag": None,
        "why_no_existing_tag": "",
        "retrieval_query": "",
    }
