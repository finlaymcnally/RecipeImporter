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


def _shard(*, rows: list[dict[str, object]] | None = None) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": rows
            or [
                {
                    "i": 10,
                    "id": "book.ks0000.nr:10",
                    "t": "Whisk oil into vinegar slowly to emulsify the dressing.",
                }
            ],
        },
        metadata={"owned_block_indices": [10], "owned_block_count": 1},
    )


def test_classification_task_file_uses_binary_category_only_answers() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard()],
    )

    assert "ontology" not in task_file
    assert task_file["answer_schema"] == {
        "allowed_values": {"category": ["keep_for_review", "other"]},
        "editable_pointer_pattern": "/units/*/answer",
        "example_answers": [{"category": "keep_for_review"}, {"category": "other"}],
        "required_keys": ["category"],
    }
    assert task_file["units"][0]["answer"] == {"category": None}
    assert "candidate_tag_keys" not in task_file["units"][0]["evidence"]
    assert any(
        "Do not invent a new tag in the first pass" in row
        for row in task_file["review_contract"]["anti_patterns"]
    )


def test_classification_validator_accepts_keep_for_review_and_other() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard()],
    )

    kept = deepcopy(task_file)
    kept["units"][0]["answer"] = {"category": "keep_for_review"}
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=kept,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {"knowledge::10": {"category": "keep_for_review"}}

    other = deepcopy(task_file)
    other["units"][0]["answer"] = {"category": "other"}
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=other,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {"knowledge::10": {"category": "other"}}


def test_classification_validator_rejects_extra_first_pass_grounding_keys() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard()],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "keep_for_review",
        "grounding": {
            "tag_keys": ["emulsify"],
            "category_keys": ["techniques"],
            "proposed_tags": [],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert answers_by_unit_id is None
    assert errors == ("classification_extra_answer_keys_forbidden",)
    assert metadata["failed_unit_ids"] == ["knowledge::10"]


def test_structured_prompt_keeps_first_pass_tag_free_and_binary() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard()],
    )
    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=task_file,
        packet_kind="initial",
    )

    prompt = build_knowledge_structured_prompt(
        task_file_payload=task_file,
        packet=packet,
    )

    assert "Classify each row only as `keep_for_review` or `other`." in prompt
    assert "Do not think about tags during classification." in prompt
    assert "Tagging happens only in the second pass." in prompt
    assert "rows sharing one group_id" not in prompt
    assert "Use the provided existing `tags` catalog first" not in prompt


def test_structured_packet_uses_compact_row_strings_without_ontology() -> None:
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

    assert packet["schema_version"] == "knowledge_structured_packet.v2"
    assert packet["rows"] == [
        "r01 | 10 | Whisk to emulsify.",
        "r02 | 11 | Chapter opener.",
    ]
    assert packet["context_before_rows"] == [
        "r01 | 9 | Previous row.",
        "r02 | 9 | Previous row.",
    ]
    assert packet["context_after_rows"] == [
        "r01 | 12 | Next row.",
        "r02 | 12 | Next row.",
    ]
    assert "ontology" not in packet
    assert "review_contract" not in packet
    assert "categories" not in packet
    assert "tags" not in packet
