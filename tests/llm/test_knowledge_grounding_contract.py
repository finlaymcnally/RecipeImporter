from __future__ import annotations

from copy import deepcopy

from cookimport.llm.knowledge_stage.task_file_contracts import (
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


def _shard(*, text: str) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [{"i": 10, "id": "book.ks0000.nr:10", "t": text}],
        },
        metadata={"owned_block_indices": [10], "owned_block_count": 1},
    )


def test_classification_task_file_exposes_ontology_once_and_candidate_tags_per_unit() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Whisk oil into vinegar slowly to emulsify the dressing.")],
    )

    assert task_file["ontology"]["catalog_version"] == "cookbook-tag-catalog-2026-03-30"
    assert "emulsify" in task_file["units"][0]["evidence"]["candidate_tag_keys"]
    assert task_file["units"][0]["answer"] == {
        "category": None,
        "reviewer_category": None,
        "retrieval_concept": None,
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }


def test_grounding_validator_accepts_existing_and_proposed_tag_answers() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Whisk oil into vinegar slowly to emulsify the dressing.")],
    )

    existing = deepcopy(task_file)
    existing["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": "Emulsify dressings by slow whisking",
        "grounding": {
            "tag_keys": ["emulsify"],
            "category_keys": ["techniques"],
            "proposed_tags": [],
        },
    }
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=existing,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id is not None
    assert answers_by_unit_id["knowledge::10"]["grounding"]["tag_keys"] == ["emulsify"]

    proposed = deepcopy(task_file)
    proposed["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": "Mount pan sauce with cold butter",
        "grounding": {
            "tag_keys": [],
            "category_keys": ["techniques"],
            "proposed_tags": [
                {
                    "key": "mount-pan-sauce",
                    "display_name": "Mount Pan Sauce",
                    "category_key": "techniques",
                }
            ],
        },
    }
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=proposed,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id is not None
    assert answers_by_unit_id["knowledge::10"]["grounding"]["proposed_tags"] == [
        {
            "key": "mount-pan-sauce",
            "display_name": "Mount Pan Sauce",
            "category_key": "techniques",
        }
    ]


def test_grounding_validator_demotes_unknown_or_empty_grounding_to_other() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Good advice, but not grounded.")],
    )
    demoted = deepcopy(task_file)
    demoted["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": "General cooking advice",
        "grounding": {
            "tag_keys": ["not-a-real-tag"],
            "category_keys": [],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=demoted,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert metadata["grounding_gate_demoted_unit_ids"] == ["knowledge::10"]
    assert metadata["grounding_gate_demotion_reason_counts"] == {
        "invalid_grounding_dropped_to_empty": 1
    }
    assert answers_by_unit_id == {
        "knowledge::10": {
            "category": "other",
            "reviewer_category": "other",
            "retrieval_concept": None,
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        }
    }


def test_grounding_validator_drops_invalid_entries_when_valid_grounding_survives() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Whisk oil into vinegar slowly to emulsify the dressing.")],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": "Emulsify dressings by slow whisking",
        "grounding": {
            "tag_keys": ["emulsify", "not-a-real-tag"],
            "category_keys": ["techniques", "not-a-real-category"],
            "proposed_tags": [
                {
                    "key": "bad key",
                    "display_name": "Bad Key",
                    "category_key": "techniques",
                },
                {
                    "key": "stable-emulsion",
                    "display_name": "Stable Emulsion",
                    "category_key": "techniques",
                },
            ],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert metadata["grounding_gate_demoted_unit_ids"] == []
    assert answers_by_unit_id is not None
    assert answers_by_unit_id["knowledge::10"]["grounding"] == {
        "tag_keys": ["emulsify"],
        "category_keys": ["techniques"],
        "proposed_tags": [
            {
                "key": "stable-emulsion",
                "display_name": "Stable Emulsion",
                "category_key": "techniques",
            }
        ],
    }


def test_grounding_validator_still_rejects_missing_retrieval_concept() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Good advice, but not grounded.")],
    )
    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": None,
        "grounding": {
            "tag_keys": ["not-a-real-tag"],
            "category_keys": [],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == ("knowledge_missing_retrieval_concept",)
    assert metadata["failed_unit_ids"] == ["knowledge::10"]
