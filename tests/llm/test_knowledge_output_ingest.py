from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_ingest import (
    classify_knowledge_validation_failure,
    normalize_knowledge_worker_payload,
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


def _semantic_packet_payload(
    *,
    packet_id: str = "book.kp0000.nr",
    block_decisions: list[dict[str, object]] | None = None,
    idea_groups: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "block_decisions": block_decisions
        if block_decisions is not None
        else [
            {"block_index": 4, "category": "knowledge"},
            {"block_index": 5, "category": "other"},
        ],
        "idea_groups": idea_groups
        if idea_groups is not None
        else [
            {
                "group_id": "idea-1",
                "topic_label": "Whisking keeps the sauce smooth",
                "block_indices": [4],
                "snippets": [
                    {
                        "body": "Keep whisking so the sauce stays smooth.",
                        "evidence": [{"block_index": 4, "quote": "Keep whisking"}],
                    }
                ],
            }
        ],
    }


def _shard(
    *,
    shard_id: str = "book.kp0000.nr",
    owned_block_indices: list[int] | None = None,
) -> ShardManifestEntryV1:
    block_indices = owned_block_indices or [4, 5]
    input_payload = {
        "v": "1",
        "bid": shard_id,
        "b": [
            {
                "i": block_index,
                "t": (
                    "Keep whisking"
                    if block_index == 4
                    else "Advertisement copy that should stay other"
                ),
            }
            for block_index in block_indices
        ],
    }
    return ShardManifestEntryV1(
        shard_id=shard_id,
        owned_ids=(shard_id,),
        input_payload=input_payload,
        metadata={"owned_block_indices": block_indices},
    )


def _multi_packet_shard() -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.kp0000.nr", "book.kp0001.nr"),
        input_payload={
            "sid": "book.ks0000.nr",
            "p": [
                {
                    "v": "1",
                    "bid": "book.kp0000.nr",
                    "b": [{"i": 4, "t": "Keep whisking"}],
                },
                {
                    "v": "1",
                    "bid": "book.kp0001.nr",
                    "b": [{"i": 5, "t": "Advertisement copy that should stay other"}],
                },
            ],
        },
        metadata={"owned_packet_ids": ["book.kp0000.nr", "book.kp0001.nr"]},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_normalize_knowledge_worker_payload_serializes_semantic_packet_result() -> None:
    payload, metadata = normalize_knowledge_worker_payload(_semantic_packet_payload())

    assert payload == {
        "v": "3",
        "bid": "book.kp0000.nr",
        "d": [
            {"i": 4, "c": "knowledge", "rc": "knowledge"},
            {"i": 5, "c": "other", "rc": "other"},
        ],
        "g": [
            {
                "gid": "idea-1",
                "l": "Whisking keeps the sauce smooth",
                "bi": [4],
                "s": [
                    {
                        "b": "Keep whisking so the sauce stays smooth.",
                        "e": [{"i": 4, "q": "Keep whisking"}],
                    }
                ],
            }
        ],
    }
    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"


def test_normalize_knowledge_worker_payload_accepts_canonical_packet_output() -> None:
    payload, metadata = normalize_knowledge_worker_payload(
        {
            "v": "3",
            "bid": "book.kp0001.nr",
            "d": [{"i": 8, "c": "other", "rc": "other"}],
            "g": [],
        }
    )

    assert payload["bid"] == "book.kp0001.nr"
    assert payload["d"] == [{"i": 8, "c": "other", "rc": "other"}]
    assert "g" not in payload
    assert "v" not in payload
    assert metadata["worker_output_contract"] == "canonical_packet_result_v3"


def test_validate_knowledge_shard_output_accepts_semantic_packet_result() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_packet_payload(),
    )

    assert valid is True
    assert errors == ()
    assert metadata["bundle_id"] == "book.kp0000.nr"
    assert metadata["result_block_decision_count"] == 2
    assert metadata["idea_group_count"] == 1


def test_validate_knowledge_shard_output_accepts_multi_packet_wrapper() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _multi_packet_shard(),
        {
            "shard_id": "book.ks0000.nr",
            "packet_results": [
                _semantic_packet_payload(
                    packet_id="book.kp0000.nr",
                    block_decisions=[{"block_index": 4, "category": "knowledge"}],
                    idea_groups=[
                        {
                            "group_id": "idea-1",
                            "topic_label": "Whisking keeps the sauce smooth",
                            "block_indices": [4],
                            "snippets": [
                                {
                                    "body": "Keep whisking so the sauce stays smooth.",
                                    "evidence": [{"block_index": 4, "quote": "Keep whisking"}],
                                }
                            ],
                        }
                    ],
                ),
                _semantic_packet_payload(
                    packet_id="book.kp0001.nr",
                    block_decisions=[{"block_index": 5, "category": "other"}],
                    idea_groups=[],
                ),
            ],
        },
    )

    assert valid is True
    assert errors == ()
    assert metadata["owned_packet_count"] == 2
    assert metadata["validated_packet_count"] == 2
    assert metadata["owned_packet_ids"] == ["book.kp0000.nr", "book.kp0001.nr"]
    assert metadata["result_block_decision_count"] == 2
    assert metadata["idea_group_count"] == 1


def test_validate_knowledge_shard_output_rejects_removed_chunk_result_contract() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        {
            "packet_id": "book.kp0000.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0000.nr",
                    "is_useful": True,
                    "block_decisions": [{"block_index": 4, "category": "knowledge"}],
                    "snippets": [
                        {
                            "body": "Keep whisking so the sauce stays smooth.",
                            "evidence": [{"block_index": 4, "quote": "Keep whisking"}],
                        }
                    ],
                    "reason_code": "technique_or_mechanism",
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("schema_invalid",)
    assert "parse_error" in metadata


def test_validate_knowledge_shard_output_rejects_missing_owned_block_decision() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_packet_payload(
            block_decisions=[{"block_index": 4, "category": "knowledge"}],
        ),
    )

    assert valid is False
    assert errors == ("missing_owned_block_decisions",)
    assert metadata["missing_owned_block_indices"] == [5]


def test_validate_knowledge_shard_output_rejects_missing_idea_group_for_knowledge_block() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_packet_payload(idea_groups=[]),
    )

    assert valid is False
    assert errors == ("knowledge_block_missing_group",)
    assert metadata["knowledge_blocks_missing_group"] == [4]


def test_validate_knowledge_shard_output_rejects_group_that_contains_other_block() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_packet_payload(
            idea_groups=[
                {
                    "group_id": "idea-1",
                    "topic_label": "Bad mixed group",
                    "block_indices": [4, 5],
                    "snippets": [
                        {
                            "body": "Keep whisking so the sauce stays smooth.",
                            "evidence": [{"block_index": 4, "quote": "Keep whisking"}],
                        }
                    ],
                }
            ],
        ),
    )

    assert valid is False
    assert errors == ("group_contains_other_block",)
    assert metadata["group_contains_other_blocks"] == {"idea-1": [5]}


def test_classify_knowledge_validation_failure_detects_snippet_copy_only_near_miss() -> None:
    result = classify_knowledge_validation_failure(
        validation_errors=["semantic_snippet_copies_evidence_quote"],
        validation_metadata={"copied_quote_idea_group_ids": ["idea-1"]},
    )

    assert result["classification"] == "snippet_copy_only"
    assert result["repairable_near_miss"] is True
    assert result["snippet_only_repair"] is True


def test_classify_knowledge_validation_failure_detects_coverage_mismatch() -> None:
    result = classify_knowledge_validation_failure(
        validation_errors=["knowledge_block_group_conflict"],
        validation_metadata={"knowledge_blocks_with_multiple_groups": [4]},
    )

    assert result["classification"] == "repairable_near_miss"
    assert result["repairable_near_miss"] is True
    assert result["has_coverage_error"] is True


def test_read_validated_knowledge_outputs_from_proposals_promotes_only_valid_packets(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "valid.json",
        {
            "payload": normalize_knowledge_worker_payload(_semantic_packet_payload())[0],
            "validation_errors": [],
        },
    )
    _write_json(
        tmp_path / "invalid.json",
        {
            "payload": normalize_knowledge_worker_payload(
                _semantic_packet_payload(packet_id="book.kp0001.nr")
            )[0],
            "validation_errors": ["knowledge_block_missing_group"],
        },
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(tmp_path)

    assert list(outputs) == ["book.kp0000.nr"]
    assert outputs["book.kp0000.nr"].bundle_id == "book.kp0000.nr"


def test_read_validated_knowledge_outputs_from_proposals_promotes_multi_packet_wrapper(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "multi.json",
        {
            "payload": {
                "shard_id": "book.ks0000.nr",
                "packet_results": [
                    normalize_knowledge_worker_payload(
                        _semantic_packet_payload(
                            packet_id="book.kp0000.nr",
                            block_decisions=[{"block_index": 4, "category": "knowledge"}],
                            idea_groups=[
                                {
                                    "group_id": "idea-1",
                                    "topic_label": "Whisking keeps the sauce smooth",
                                    "block_indices": [4],
                                    "snippets": [
                                        {
                                            "body": "Keep whisking so the sauce stays smooth.",
                                            "evidence": [
                                                {"block_index": 4, "quote": "Keep whisking"}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        )
                    )[0],
                    normalize_knowledge_worker_payload(
                        _semantic_packet_payload(
                            packet_id="book.kp0001.nr",
                            block_decisions=[{"block_index": 5, "category": "other"}],
                            idea_groups=[],
                        )
                    )[0],
                ],
            },
            "validation_errors": [],
            "validation_metadata": {
                "owned_packet_ids": ["book.kp0000.nr", "book.kp0001.nr"],
                "owned_packet_count": 2,
            },
        },
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(tmp_path)

    assert sorted(outputs) == ["book.kp0000.nr", "book.kp0001.nr"]
    assert outputs["book.kp0000.nr"].bundle_id == "book.kp0000.nr"
    assert outputs["book.kp0001.nr"].bundle_id == "book.kp0001.nr"
    assert sorted(payloads_by_shard_id) == ["book.kp0000.nr", "book.kp0001.nr"]
    assert payloads_by_shard_id["book.kp0000.nr"]["g"][0]["gid"] == "idea-1"
    assert payloads_by_shard_id["book.kp0001.nr"]["d"] == [
        {"c": "other", "i": 5, "rc": "other"}
    ]


def test_read_validated_knowledge_outputs_from_proposals_rejects_duplicate_packet_ids(
    tmp_path: Path,
) -> None:
    payload = normalize_knowledge_worker_payload(_semantic_packet_payload())[0]
    _write_json(tmp_path / "a.json", {"payload": payload, "validation_errors": []})
    _write_json(tmp_path / "b.json", {"payload": payload, "validation_errors": []})

    with pytest.raises(ValueError, match="Duplicate packet_id"):
        read_validated_knowledge_outputs_from_proposals(tmp_path)
