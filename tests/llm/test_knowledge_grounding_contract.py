from __future__ import annotations

from copy import deepcopy

from cookimport.llm.knowledge_stage.structured_session_contract import (
    build_knowledge_structured_prompt,
    knowledge_task_file_to_structured_packet,
)
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


def test_classification_task_file_exposes_ontology_once_without_repo_tag_hints() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Whisk oil into vinegar slowly to emulsify the dressing.")],
    )

    assert task_file["ontology"]["catalog_version"] == "cookbook-tag-catalog-2026-03-30"
    assert "candidate_tag_keys" not in task_file["units"][0]["evidence"]
    assert task_file["units"][0]["answer"] == {
        "category": None,
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


def test_grounding_validator_keeps_knowledge_with_weak_grounding_after_invalid_drop() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Good advice, but not grounded.")],
    )
    demoted = deepcopy(task_file)
    demoted["units"][0]["answer"] = {
        "category": "knowledge",
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
    assert metadata["weak_grounding_unit_ids"] == ["knowledge::10"]
    assert metadata["weak_grounding_reason_counts"] == {
        "invalid_grounding_dropped_to_empty": 1
    }
    assert answers_by_unit_id == {
        "knowledge::10": {
            "category": "knowledge",
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        }
    }


def test_grounding_validator_accepts_category_only_grounding_as_weak_knowledge() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Salt early so it has time to penetrate.")],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": [],
            "category_keys": ["techniques"],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert metadata["weak_grounding_unit_ids"] == ["knowledge::10"]
    assert metadata["weak_grounding_reason_counts"] == {"category_only_grounding": 1}
    assert answers_by_unit_id == {
        "knowledge::10": {
            "category": "knowledge",
            "grounding": {
                "tag_keys": [],
                "category_keys": ["techniques"],
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
    assert metadata["weak_grounding_unit_ids"] == []
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


def test_grounding_validator_still_rejects_malformed_grounding_shapes() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Good advice, but not grounded.")],
    )
    invalid = deepcopy(task_file)
    invalid["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": "not-a-real-tag",
            "category_keys": [],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == ("invalid_grounding_tag_keys",)
    assert metadata["failed_unit_ids"] == ["knowledge::10"]


def test_structured_prompt_explicitly_forbids_category_only_grounding() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Salt early so it has time to penetrate.")],
    )
    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=task_file,
        packet_kind="initial",
    )

    prompt = build_knowledge_structured_prompt(
        task_file_payload=task_file,
        packet=packet,
    )

    assert "category-only grounding is invalid" in prompt
    assert "return `other` with empty grounding" in prompt


def test_structured_packet_uses_local_row_ids_and_compact_hints() -> None:
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
                        {"i": 10, "id": "book.ks0000.nr:10", "t": "Whisk to emulsify."},
                        {"i": 11, "id": "book.ks0000.nr:11", "t": "Chapter opener."},
                    ],
                    "x": {
                        "p": [{"i": 9, "t": "Previous row."}],
                        "n": [{"i": 12, "t": "Next row."}],
                    },
                },
                metadata={"owned_block_indices": [10, 11], "owned_block_count": 2},
            )
        ],
    )

    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=task_file,
        packet_kind="initial",
    )

    assert [row["row_id"] for row in packet["rows"]] == ["r01", "r02"]
    assert [row["text"] for row in packet["rows"]] == [
        "Whisk to emulsify.",
        "Chapter opener.",
    ]
    assert packet["rows"][0]["context_before"] == "Previous row."
    assert packet["rows"][0]["context_after"] == "Next row."
    assert "candidate_tag_keys" not in packet["rows"][0]
    assert "categories" in packet
    assert "ontology" not in packet
    assert "review_contract" not in packet
