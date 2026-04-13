from __future__ import annotations

import json

from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.knowledge_stage.structured_session_contract import (
    build_knowledge_edited_task_file_from_classification_response,
    build_knowledge_edited_task_file_from_grouping_response,
    build_knowledge_structured_prompt,
    knowledge_task_file_to_structured_packet,
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


def test_classification_structured_packet_and_prompt_use_compact_binary_surface() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=21, text="Acid brightens rich dishes."),
            _shard(shard_id="book.ks0001.nr", block_index=22, text="Chapter opener."),
        ],
    )

    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=task_file,
        packet_kind="initial",
    )
    prompt = build_knowledge_structured_prompt(
        task_file_payload=task_file,
        packet=packet,
    )

    assert packet["rows"] == [
        "r01 | 21 | Acid brightens rich dishes.",
        "r02 | 22 | Chapter opener.",
    ]
    assert "labels" in prompt
    assert "keep_for_review" in prompt
    assert "keep it `other` in this first pass" in prompt
    assert "let the explanatory body carry the knowledge" in prompt
    assert "Do not think about tags during classification." in prompt


def test_classification_structured_response_accepts_labels_array() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=21, text="Acid brightens rich dishes."),
            _shard(shard_id="book.ks0001.nr", block_index=22, text="Chapter opener."),
        ],
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_classification_response(
        original_task_file=task_file,
        response_text=json.dumps({"labels": ["keep_for_review", "other"]}),
    )

    assert edited is not None
    assert errors == ()
    assert metadata == {}
    answers, validation_errors, validation_metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )
    assert validation_errors == ()
    assert validation_metadata["failed_unit_ids"] == []
    assert answers == {
        "knowledge::21": {"category": "keep_for_review"},
        "knowledge::22": {"category": "other"},
    }


def test_grouping_structured_prompt_is_group_first_and_parser_maps_group_grounding() -> None:
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
                        {"i": 30, "id": "book.ks0000.nr:30", "t": "BALANCE"},
                        {
                            "i": 31,
                            "id": "book.ks0000.nr:31",
                            "t": "Use gentle heat for eggs.",
                        },
                        {
                            "i": 32,
                            "id": "book.ks0000.nr:32",
                            "t": "Rest dough before rolling.",
                        },
                    ],
                },
                metadata={"owned_block_indices": [30, 31, 32], "owned_block_count": 3},
            ),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::30": {"category": "other"},
            "knowledge::31": {"category": "keep_for_review"},
            "knowledge::32": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=grouping_task_file,
        packet_kind="initial",
    )
    prompt = build_knowledge_structured_prompt(
        task_file_payload=grouping_task_file,
        packet=packet,
    )

    assert packet["row_facts"] == [
        "r01 | classification=keep_for_review",
        "r02 | classification=keep_for_review",
    ]
    assert packet["ordered_rows"] == [
        "ctx01 | other | 30 | BALANCE",
        "r01 | keep_for_review | 31 | Use gentle heat for eggs.",
        "r02 | keep_for_review | 32 | Rest dough before rolling.",
    ]
    assert "split-and-tag pass" in prompt
    assert "Return one `groups` array." in prompt
    assert "choose the group boundaries with the tag story in mind" in prompt
    assert "ordered_rows" in prompt
    assert "ctxXX" in prompt
    assert "Put `why_no_existing_tag` and `retrieval_query` on the group object itself" in prompt
    assert "Valid proposed-tag example" in prompt

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "groups": [
                    {
                        "group_id": "g01",
                        "start_row_id": "r01",
                        "end_row_id": "r01",
                        "topic_label": "Heat control",
                        "grounding": {
                            "tag_keys": ["saute"],
                            "category_keys": ["cooking-method"],
                            "proposed_tags": [],
                        },
                        "why_no_existing_tag": None,
                        "retrieval_query": None,
                    },
                    {
                        "group_id": "g02",
                        "start_row_id": "r02",
                        "end_row_id": "r02",
                        "topic_label": "Dough resting",
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": ["techniques"],
                            "proposed_tags": [
                                {
                                    "key": "dough-resting",
                                    "display_name": "Dough resting",
                                    "category_key": "techniques",
                                }
                            ],
                        },
                        "why_no_existing_tag": "No existing tag fits the dough-resting concept.",
                        "retrieval_query": "why rest dough before rolling",
                    },
                ]
            }
        ),
    )

    assert edited is not None
    assert errors == ()
    assert metadata == {}
    answers, validation_errors, validation_metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )
    assert validation_errors == ()
    assert validation_metadata["failed_unit_ids"] == []
    assert answers["knowledge::31"]["group_id"] == "g01"
    assert answers["knowledge::31"]["grounding"]["tag_keys"] == ["saute"]
    assert answers["knowledge::32"]["grounding"]["proposed_tags"] == [
        {
            "key": "dough-resting",
            "display_name": "Dough resting",
            "category_key": "techniques",
        }
    ]


def test_grouping_structured_response_rejects_context_only_row_ids() -> None:
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
                        {"i": 30, "id": "book.ks0000.nr:30", "t": "BALANCE"},
                        {
                            "i": 31,
                            "id": "book.ks0000.nr:31",
                            "t": "Use gentle heat for eggs.",
                        },
                    ],
                },
                metadata={"owned_block_indices": [30, 31], "owned_block_count": 2},
            ),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::30": {"category": "other"},
            "knowledge::31": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "groups": [
                    {
                        "group_id": "g01",
                        "row_ids": ["ctx01", "r01"],
                        "topic_label": "Heat control",
                        "grounding": {
                            "tag_keys": ["saute"],
                            "category_keys": ["cooking-method"],
                            "proposed_tags": [],
                        },
                        "why_no_existing_tag": None,
                        "retrieval_query": None,
                    }
                ]
            }
        ),
    )

    assert edited is not None
    assert "knowledge_unknown_row_ids" in errors
    assert metadata["unknown_row_ids"] == ["ctx01"]


def test_grouping_structured_response_salvages_nested_proposal_metadata() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=41, text="Rest dough before rolling."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={"knowledge::41": {"category": "keep_for_review"}},
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "groups": [
                    {
                        "group_id": "g01",
                        "start_row_id": "r01",
                        "end_row_id": "r01",
                        "topic_label": "Dough resting",
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": ["techniques"],
                            "proposed_tags": [
                                {
                                    "key": "dough-resting",
                                    "category_key": "techniques",
                                    "why_no_existing_tag": (
                                        "No existing tag covers the rest-before-rolling concept."
                                    ),
                                    "retrieval_query": "rest dough before rolling",
                                }
                            ],
                        },
                    }
                ]
            }
        ),
    )

    assert edited is not None
    assert errors == ()
    assert metadata == {}
    answers, validation_errors, validation_metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )

    assert validation_errors == ()
    assert validation_metadata["failed_unit_ids"] == []
    assert answers == {
        "knowledge::41": {
            "group_id": "g01",
            "topic_label": "Dough resting",
            "grounding": {
                "tag_keys": [],
                "category_keys": ["techniques"],
                "proposed_tags": [
                    {
                        "key": "dough-resting",
                        "display_name": "Dough resting",
                        "category_key": "techniques",
                    }
                ],
            },
            "why_no_existing_tag": "No existing tag covers the rest-before-rolling concept.",
            "retrieval_query": "rest dough before rolling",
        }
    }


def test_grouping_repair_packet_preserves_previous_answer_and_validation_feedback() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=31, text="Use gentle heat for eggs."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={"knowledge::31": {"category": "keep_for_review"}},
        unit_to_shard_id=unit_to_shard_id,
    )
    repair_task_file = build_repair_task_file(
        original_task_file=grouping_task_file,
        failed_unit_ids=["knowledge::31"],
        previous_answers_by_unit_id={
            "knowledge::31": {
                "group_id": "g01",
                "topic_label": "",
                "grounding": {
                    "tag_keys": ["saute"],
                    "category_keys": ["cooking-method"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            }
        },
        validation_feedback_by_unit_id={
            "knowledge::31": {
                "validation_errors": ["knowledge_block_missing_group"],
                "error_details": [
                    {
                        "path": "/units/knowledge::31/answer/topic_label",
                        "code": "knowledge_block_missing_group",
                        "message": "topic_label must be a non-empty string",
                    }
                ],
            }
        },
        repair_validation_errors=["knowledge_block_missing_group"],
        repair_validation_metadata={
            "failed_unit_ids": ["knowledge::31"],
            "error_details": [
                {
                    "path": "/units/knowledge::31/answer/topic_label",
                    "code": "knowledge_block_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            ],
        },
    )
    repair_task_file["repair_root_cause_summary"] = {
        "validation_errors": ["invalid_proposed_tag_display_name"],
        "message": (
            "invalid_proposed_tag_display_name | proposed display_name must be a short "
            "non-empty string | /units/knowledge::31/answer/grounding/proposed_tags/0/display_name"
        ),
        "error_details": [
            {
                "path": "/units/knowledge::31/answer/grounding/proposed_tags/0/display_name",
                "code": "invalid_proposed_tag_display_name",
                "message": "proposed display_name must be a short non-empty string",
            }
        ],
    }

    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=repair_task_file,
        packet_kind="grouping_1_repair",
        validation_errors=["knowledge_block_missing_group"],
    )
    prompt = build_knowledge_structured_prompt(
        task_file_payload=repair_task_file,
        packet=packet,
    )

    assert packet["repair_feedback_rows"] == [
        {
            "row_id": "r01",
            "previous_answer": {
                "group_id": "g01",
                "topic_label": "",
                "grounding": {
                    "tag_keys": ["saute"],
                    "category_keys": ["cooking-method"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            },
            "validation_errors": ["knowledge_block_missing_group"],
            "error_details": [
                {
                    "path": "/units/knowledge::31/answer/topic_label",
                    "code": "knowledge_block_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            ],
        }
    ]
    assert packet["previous_groups"] == [
        {
            "start_row_id": "r01",
            "end_row_id": "r01",
            "row_ids": ["r01"],
            "validation_errors": ["knowledge_block_missing_group"],
            "error_details": [
                {
                    "path": "/units/knowledge::31/answer/topic_label",
                    "code": "knowledge_block_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            ],
            "group_id": "g01",
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
        }
    ]
    assert packet["repair_validation_summary"]["validation_errors"] == [
        "knowledge_block_missing_group"
    ]
    assert packet["repair_root_cause_summary"]["validation_errors"] == [
        "invalid_proposed_tag_display_name"
    ]
    assert "repair_feedback_rows" in prompt
    assert "previous_groups" in prompt
    assert "repair_validation_summary" in prompt
    assert "repair_root_cause_summary" in prompt


def test_grouping_structured_response_rejects_noncontiguous_group_spans() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=31, text="Use gentle heat for eggs."),
            _shard(shard_id="book.ks0001.nr", block_index=32, text="Rest dough before rolling."),
            _shard(shard_id="book.ks0002.nr", block_index=33, text="Return to gentle heat."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::31": {"category": "keep_for_review"},
            "knowledge::32": {"category": "keep_for_review"},
            "knowledge::33": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "groups": [
                    {
                        "group_id": "g01",
                        "row_ids": ["r01", "r03"],
                        "topic_label": "Heat control",
                        "grounding": {
                            "tag_keys": ["saute"],
                            "category_keys": ["cooking-method"],
                            "proposed_tags": [],
                        },
                        "why_no_existing_tag": None,
                        "retrieval_query": None,
                    }
                ]
            }
        ),
    )

    assert edited is not None
    assert "knowledge_group_noncontiguous_span" in errors
    assert metadata["failed_unit_ids"] == ["knowledge::31", "knowledge::32", "knowledge::33"]


def test_classification_repair_packet_preserves_packet_level_count_feedback() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(shard_id="book.ks0000.nr", block_index=21, text="Acid brightens rich dishes."),
            _shard(shard_id="book.ks0001.nr", block_index=22, text="Chapter opener."),
        ],
    )
    repair_task_file = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=["knowledge::21", "knowledge::22"],
        previous_answers_by_unit_id={},
        validation_feedback_by_unit_id={},
        repair_validation_errors=["label_count_mismatch"],
        repair_validation_metadata={
            "expected_label_count": 2,
            "returned_label_count": 1,
        },
    )

    packet = knowledge_task_file_to_structured_packet(
        task_file_payload=repair_task_file,
        packet_kind="classification_repair",
        validation_errors=["label_count_mismatch"],
    )

    assert packet["repair_validation_summary"] == {
        "validation_errors": ["label_count_mismatch"],
        "expected_label_count": 2,
        "returned_label_count": 1,
    }
