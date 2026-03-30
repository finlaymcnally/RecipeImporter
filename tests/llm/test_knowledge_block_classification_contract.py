from __future__ import annotations

from copy import deepcopy

from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
    KNOWLEDGE_CLASSIFY_STAGE_KEY,
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
    assert task_file["editable_json_pointers"] == ["/units/0/answer"]
    assert unit_to_shard_id == {"knowledge::14": "book.ks0000.nr"}
    assert task_file["ontology"]["catalog_version"] == "cookbook-tag-catalog-2026-03-30"
    unit = task_file["units"][0]
    assert unit["answer"] == {
        "category": None,
        "reviewer_category": None,
        "retrieval_concept": None,
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


def test_classification_validator_enforces_reviewer_category_rules_and_repair_scope() -> None:
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
        "reviewer_category": "knowledge",
        "retrieval_concept": "Balance richness with acid",
        "grounding": {
            "tag_keys": ["bright"],
            "category_keys": ["flavor-profile"],
            "proposed_tags": [],
        },
    }
    edited["units"][1]["answer"] = {
        "category": "other",
        "reviewer_category": "chapter_taxonomy",
        "retrieval_concept": None,
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
            "reviewer_category": "knowledge",
            "retrieval_concept": "Balance richness with acid",
            "grounding": {
                "tag_keys": ["bright"],
                "category_keys": ["flavor-profile"],
                "proposed_tags": [],
            },
        },
        "knowledge::22": {
            "category": "other",
            "reviewer_category": "chapter_taxonomy",
            "retrieval_concept": None,
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        },
    }

    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "other",
        "retrieval_concept": "Balance richness with acid",
        "grounding": {
            "tag_keys": ["bright"],
            "category_keys": ["flavor-profile"],
            "proposed_tags": [],
        },
    }
    invalid["units"][1]["answer"] = {
        "category": "other",
        "reviewer_category": "chapter_taxonomy",
        "retrieval_concept": None,
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
    assert "knowledge_reviewer_category_mismatch" in errors
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
