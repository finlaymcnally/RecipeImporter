from __future__ import annotations

import json

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
            _shard(shard_id="book.ks0000.nr", block_index=31, text="Use gentle heat for eggs."),
            _shard(shard_id="book.ks0001.nr", block_index=32, text="Rest dough before rolling."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-structured-001",
        worker_id="worker-structured-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
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
    assert "group-first tagging pass" in prompt
    assert "Rows about the same idea must share the same `group_id`" in prompt

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text=json.dumps(
            {
                "rows": [
                    {
                        "row_id": "r01",
                        "group_id": "g01",
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
                        "row_id": "r02",
                        "group_id": "g02",
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
