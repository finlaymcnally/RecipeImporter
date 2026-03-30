from __future__ import annotations

import json

from cookimport.llm.knowledge_phase_workspace_tools import (
    KNOWLEDGE_OUTPUT_CONTRACT_FILENAME,
    KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_FILENAME,
    KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_FILENAME,
    assemble_final_output,
    build_knowledge_workspace_shard_metadata,
    build_pass1_packet,
    build_pass1_repair_packet,
    build_pass2_packet,
    build_pass2_repair_packet,
    render_knowledge_packet_hint,
    validate_pass1_packet_result,
    validate_pass2_packet_result,
    write_knowledge_output_contract,
    write_knowledge_worker_examples,
)


def test_pass2_packet_keeps_only_accepted_knowledge_rows() -> None:
    input_payload = {
        "bid": "book.ks0000.nr",
        "b": [
            {"i": 7, "t": "Marketing."},
            {"i": 8, "t": "Use low heat and whisk steadily."},
        ],
    }
    pass1_rows = [
        {
            "block_index": 7,
            "category": "other",
        },
        {
            "block_index": 8,
            "category": "knowledge",
        },
    ]

    assert build_pass2_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass2",
        input_payload=input_payload,
        pass1_rows=pass1_rows,
    ) == {
        "v": "1",
        "task_id": "book.ks0000.nr.pass2",
        "packet_kind": "pass2",
        "shard_id": "book.ks0000.nr",
        "rows": [
            {"block_index": 8, "text": "Use low heat and whisk steadily."},
        ],
    }

def test_assemble_final_output_round_trips_packet_results() -> None:
    assert assemble_final_output(
        shard_id="book.ks0000.nr",
        pass1_result={
            "task_id": "book.ks0000.nr.pass1",
            "packet_kind": "pass1",
            "shard_id": "book.ks0000.nr",
            "rows": [
                {"block_index": 7, "category": "other"},
                {"block_index": 8, "category": "knowledge"},
            ],
        },
        pass2_result={
            "task_id": "book.ks0000.nr.pass2",
            "packet_kind": "pass2",
            "shard_id": "book.ks0000.nr",
            "rows": [
                {
                    "block_index": 8,
                    "group_key": "heat-control",
                    "topic_label": "Heat control",
                }
            ],
        },
    ) == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {"block_index": 7, "category": "other", "reviewer_category": "other"},
            {"block_index": 8, "category": "knowledge", "reviewer_category": "knowledge"},
        ],
        "idea_groups": [
            {"group_id": "g01", "topic_label": "Heat control", "block_indices": [8]}
        ],
    }


def test_build_knowledge_workspace_shard_metadata_is_packet_lease_native() -> None:
    metadata = build_knowledge_workspace_shard_metadata(
        shard_id="book.ks0000.nr",
        input_payload={"b": [{"i": 4, "t": "Whisk."}, {"i": 5, "t": "Rest."}]},
        input_path="in/book.ks0000.nr.json",
        hint_path="hints/book.ks0000.nr.md",
        result_path="out/book.ks0000.nr.json",
    )

    assert metadata == {
        "workspace_processing_contract": "knowledge_packet_lease_v1",
        "shard_id": "book.ks0000.nr",
        "input_path": "in/book.ks0000.nr.json",
        "hint_path": "hints/book.ks0000.nr.md",
        "result_path": "out/book.ks0000.nr.json",
        "owned_row_count": 2,
        "owned_block_indices": [4, 5],
        "block_index_start": 4,
        "block_index_end": 5,
    }


def test_pass1_validator_rejects_missing_rows() -> None:
    _result, errors, metadata = validate_pass1_packet_result(
        packet_payload=build_pass1_packet(
            shard_id="book.ks0000.nr",
            task_id="book.ks0000.nr.pass1",
            input_payload={"b": [{"i": 4, "t": "Whisk"}, {"i": 5, "t": "Cool"}]},
        ),
        result_payload={
            "task_id": "book.ks0000.nr.pass1",
            "packet_kind": "pass1",
            "shard_id": "book.ks0000.nr",
            "rows": [{"block_index": 4, "category": "knowledge"}],
        },
    )

    assert errors == ("missing_owned_block_decisions",)
    assert metadata["missing_owned_block_indices"] == [5]


def test_pass2_validator_rejects_blank_topic_labels() -> None:
    packet = build_pass2_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass2",
        input_payload={"b": [{"i": 4, "t": "Whisk"}]},
        pass1_rows=[{"block_index": 4, "category": "knowledge"}],
    )
    _result, errors, metadata = validate_pass2_packet_result(
        packet_payload=packet,
        result_payload={
            "task_id": "book.ks0000.nr.pass2",
            "packet_kind": "pass2",
            "shard_id": "book.ks0000.nr",
            "rows": [{"block_index": 4, "group_key": "g01", "topic_label": ""}],
        },
    )

    assert errors == ("knowledge_block_missing_group",)
    assert metadata["knowledge_blocks_missing_group"] == [4]


def test_build_pass1_and_pass2_packets_stay_sparse() -> None:
    pass1_packet = build_pass1_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass1",
        input_payload={"b": [{"i": 4, "t": "Whisk"}, {"i": 5, "t": "Rest"}]},
    )
    pass2_packet = build_pass2_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass2",
        input_payload={"b": [{"i": 4, "t": "Whisk"}, {"i": 5, "t": "Rest"}]},
        pass1_rows=[
            {"block_index": 4, "category": "knowledge"},
            {"block_index": 5, "category": "knowledge"},
        ],
    )

    assert pass1_packet == {
        "v": "1",
        "task_id": "book.ks0000.nr.pass1",
        "packet_kind": "pass1",
        "shard_id": "book.ks0000.nr",
        "rows": [
            {"block_index": 4, "text": "Whisk"},
            {"block_index": 5, "text": "Rest"},
        ],
    }
    assert pass2_packet == {
        "v": "1",
        "task_id": "book.ks0000.nr.pass2",
        "packet_kind": "pass2",
        "shard_id": "book.ks0000.nr",
        "rows": [
            {"block_index": 4, "text": "Whisk"},
            {"block_index": 5, "text": "Rest"},
        ],
    }


def test_render_knowledge_packet_hint_names_result_path_and_repair_rules() -> None:
    packet = build_pass1_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass1",
        input_payload={
            "b": [
                {"i": 10, "t": "Praise."},
                {"i": 11, "t": "Use low heat and whisk steadily."},
            ]
        },
        repair={"validation_errors": ["missing_owned_block_decisions"]},
    )

    hint = render_knowledge_packet_hint(
        packet_payload=packet,
        shard_hint_text="Use the shard-local hint first.",
        result_path="scratch/book.ks0000.nr.pass1.json",
    )

    assert "Open `current_packet.json`." in hint
    assert "Result path: `scratch/book.ks0000.nr.pass1.json`" in hint
    assert "Repair rules:" in hint
    assert "structural repair packet only" in hint
    assert "Use the shard-local hint first." in hint


def test_build_pass1_repair_packet_limits_rows_to_unresolved() -> None:
    packet = build_pass1_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass1",
        input_payload={
            "b": [
                {"i": 4, "t": "Whisk."},
                {"i": 5, "t": "Rest."},
            ]
        },
    )

    repair_packet = build_pass1_repair_packet(
        packet_payload=packet,
        validation_errors=("missing_owned_block_decisions",),
        validation_metadata={"unresolved_block_indices": [5]},
        accepted_rows=[{"block_index": 4, "category": "knowledge"}],
    )

    assert repair_packet["packet_kind"] == "pass1"
    assert repair_packet["task_id"] == "book.ks0000.nr.pass1.repair"
    assert repair_packet["rows"] == [{"block_index": 5, "text": "Rest."}]
    assert repair_packet["repair"]["accepted_rows"] == [
        {"block_index": 4, "category": "knowledge"}
    ]


def test_build_pass2_repair_packet_limits_rows_to_unresolved() -> None:
    packet = build_pass2_packet(
        shard_id="book.ks0000.nr",
        task_id="book.ks0000.nr.pass2",
        input_payload={
            "b": [
                {"i": 4, "t": "Whisk."},
                {"i": 5, "t": "Rest."},
            ]
        },
        pass1_rows=[
            {"block_index": 4, "category": "knowledge"},
            {"block_index": 5, "category": "knowledge"},
        ],
    )

    repair_packet = build_pass2_repair_packet(
        packet_payload=packet,
        validation_errors=("knowledge_block_missing_group",),
        validation_metadata={"unresolved_block_indices": [4]},
        accepted_rows=[
            {"block_index": 5, "group_key": "resting", "topic_label": "Resting"}
        ],
    )

    assert repair_packet == {
        "v": "1",
        "task_id": "book.ks0000.nr.pass2.repair",
        "packet_kind": "pass2",
        "shard_id": "book.ks0000.nr",
        "rows": [{"block_index": 4, "text": "Whisk."}],
        "repair": {
            "validation_errors": ["knowledge_block_missing_group"],
            "required_block_indices": [4],
            "accepted_rows": [
                {
                    "block_index": 5,
                    "group_key": "resting",
                    "topic_label": "Resting",
                }
            ],
        },
    }


def test_write_knowledge_contract_and_examples_publish_packet_result_shapes(
    tmp_path,
) -> None:
    write_knowledge_output_contract(worker_root=tmp_path)
    write_knowledge_worker_examples(worker_root=tmp_path)

    contract_text = (tmp_path / KNOWLEDGE_OUTPUT_CONTRACT_FILENAME).read_text(encoding="utf-8")
    pass1_example = json.loads(
        (tmp_path / "examples" / KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    pass2_example = json.loads(
        (tmp_path / "examples" / KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_FILENAME).read_text(
            encoding="utf-8"
        )
    )

    assert "current_packet.json" in contract_text
    assert "current_result_path.txt" in contract_text
    assert "Pass 1 result shape" in contract_text
    assert "Pass 2 result shape" in contract_text
    assert pass1_example["packet_kind"] == "pass1"
    assert pass2_example["packet_kind"] == "pass2"
