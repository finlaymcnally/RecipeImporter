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
    assert any(
        "Do not invent a new tag in the first pass"
        in pattern
        for pattern in task_file["review_contract"]["anti_patterns"]
    )
    assert task_file["units"][0]["answer"] == {
        "category": None,
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }


def test_grounding_validator_accepts_existing_knowledge_and_empty_proposal_candidates() -> None:
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

    proposal_candidate = deepcopy(task_file)
    proposal_candidate["units"][0]["answer"] = {
        "category": "proposal_candidate",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=proposal_candidate,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id is not None
    assert answers_by_unit_id["knowledge::10"] == {
        "category": "proposal_candidate",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }


def test_grounding_validator_rejects_unknown_tag_when_no_existing_grounding_survives() -> None:
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

    assert answers_by_unit_id is None
    assert errors == (
        "unknown_grounding_tag_key",
        "knowledge_grounding_existing_tag_required",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::10"]


def test_grounding_validator_rejects_category_only_knowledge_grounding() -> None:
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

    assert answers_by_unit_id is None
    assert errors == ("knowledge_grounding_existing_tag_required",)
    assert metadata["failed_unit_ids"] == ["knowledge::10"]


def test_grounding_validator_rejects_first_pass_proposed_tags_even_with_valid_existing_tag() -> None:
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

    assert answers_by_unit_id is None
    assert errors == (
        "unknown_grounding_tag_key",
        "unknown_grounding_category_key",
        "classification_proposed_tags_forbidden",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::10"]


def test_grounding_validator_forbids_first_pass_proposed_tags_even_when_they_duplicate_existing_names() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(text="Whisk oil into vinegar slowly to emulsify the dressing.")],
    )
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": [],
            "category_keys": ["techniques"],
            "proposed_tags": [
                {
                    "key": "stable-emulsion",
                    "display_name": "Emulsify",
                    "category_key": "techniques",
                }
            ],
        },
    }

    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert answers_by_unit_id is None
    assert errors == (
        "classification_proposed_tags_forbidden",
        "knowledge_grounding_existing_tag_required",
    )
    assert metadata["failed_unit_ids"] == ["knowledge::10"]
    assert metadata["error_details"] == [
        {
            "path": "/units/knowledge::10/answer/grounding",
            "code": "classification_proposed_tags_forbidden",
            "message": (
                "first-pass classification must not invent proposed tags; use "
                "`proposal_candidate` instead"
            ),
        },
        {
            "path": "/units/knowledge::10/answer/grounding/tag_keys",
            "code": "knowledge_grounding_existing_tag_required",
            "message": "knowledge rows must ground to at least one existing tag key",
        }
    ]


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
    assert errors == (
        "invalid_grounding_tag_keys",
        "knowledge_grounding_existing_tag_required",
    )
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
    assert "Use the provided existing `tags` catalog first" in prompt
    assert (
        "Do not invent or preview proposed tags during classification. Proposal "
        "approval happens in the second pass."
    ) in prompt
    assert (
        "Do not coin broad chapter-theme, editorial, or pedagogy-summary tags"
    ) not in prompt
    assert "Reason about the packet holistically first" in prompt
    assert "Decide by local span, emit by row." in prompt
    assert (
        "A heading, bridge line, or short setup row may help nearby rows count as "
        "knowledge without itself being `knowledge`."
    ) in prompt
    assert (
        "do use row order and nearby rows to understand the local run"
    ) in prompt


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
    assert "categories" in packet
    assert "tags" in packet
    assert any(tag["key"] == "emulsify" for tag in packet["tags"])
    assert "ontology" not in packet
    assert "review_contract" not in packet
