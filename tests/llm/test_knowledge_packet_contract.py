from __future__ import annotations

from cookimport.llm.codex_farm_knowledge_ingest import (
    normalize_knowledge_worker_payload,
    validate_knowledge_shard_output,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


def _packet_payload(*, packet_id: str, block_indices: list[int]) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "block_decisions": [
            {"block_index": block_index, "category": "knowledge"}
            for block_index in block_indices
        ],
        "idea_groups": [
            {
                "group_id": "g01",
                "topic_label": "Heat control",
                "block_indices": list(block_indices),
                "snippets": [
                    {
                        "body": "Use steady heat to control the pan.",
                        "evidence": [
                            {
                                "block_index": block_indices[0],
                                "quote": "Use steady heat",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _shard(*, packet_id: str, block_indices: list[int]) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id=packet_id,
        owned_ids=(packet_id,),
        evidence_refs=tuple(f"block:{index}" for index in block_indices),
        input_payload={
            "v": "1",
            "bid": packet_id,
            "b": [{"i": index, "t": f"Block {index} text."} for index in block_indices],
        },
        metadata={"owned_block_indices": list(block_indices)},
    )


def test_normalize_knowledge_worker_payload_serializes_packet_result() -> None:
    payload, metadata = normalize_knowledge_worker_payload(
        _packet_payload(packet_id="book.kp0001.nr", block_indices=[4, 5])
    )

    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"
    assert payload == {
        "v": "3",
        "bid": "book.kp0001.nr",
        "d": [
            {"i": 4, "c": "knowledge", "rc": "knowledge"},
            {"i": 5, "c": "knowledge", "rc": "knowledge"},
        ],
        "g": [
            {
                "gid": "g01",
                "l": "Heat control",
                "bi": [4, 5],
                "s": [
                    {
                        "b": "Use steady heat to control the pan.",
                        "e": [{"i": 4, "q": "Use steady heat"}],
                    }
                ],
            }
        ],
    }


def test_validate_knowledge_shard_output_accepts_complete_packet_groups() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(packet_id="book.kp0002.nr", block_indices=[10, 11]),
        _packet_payload(packet_id="book.kp0002.nr", block_indices=[10, 11]),
    )

    assert valid is True
    assert errors == ()
    assert metadata["knowledge_decision_count"] == 2
    assert metadata["idea_group_count"] == 1


def test_validate_knowledge_shard_output_rejects_knowledge_blocks_missing_groups() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(packet_id="book.kp0003.nr", block_indices=[20, 21]),
        {
            "packet_id": "book.kp0003.nr",
            "block_decisions": [
                {"block_index": 20, "category": "knowledge"},
                {"block_index": 21, "category": "knowledge"},
            ],
            "idea_groups": [
                {
                    "group_id": "g01",
                    "topic_label": "One block only",
                    "block_indices": [20],
                    "snippets": [
                        {
                            "body": "Keep the pan steady.",
                            "evidence": [
                                {"block_index": 20, "quote": "Keep the pan steady."}
                            ],
                        }
                    ],
                }
            ],
        },
    )

    assert valid is False
    assert "knowledge_block_missing_group" in errors
    assert metadata["knowledge_blocks_missing_group"] == [21]
