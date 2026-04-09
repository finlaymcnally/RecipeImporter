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


def _semantic_payload(
    *,
    packet_id: str = "book.ks0000.nr",
    block_decisions: list[dict[str, object]] | None = None,
    idea_groups: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "block_decisions": block_decisions
        if block_decisions is not None
        else [
            {
                "block_index": 4,
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["emulsify"],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
            },
            {
                "block_index": 5,
                "category": "other",
                "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
            },
        ],
        "idea_groups": idea_groups
        if idea_groups is not None
        else [
            {
                "group_id": "g01",
                "topic_label": "Heat control",
                "block_indices": [4],
            }
        ],
    }


def _shard() -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 4, "t": "Keep whisking."},
                {"i": 5, "t": "Marketing copy."},
            ],
        },
        metadata={"owned_block_indices": [4, 5]},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_normalize_knowledge_worker_payload_serializes_semantic_packet_result() -> None:
    payload, metadata = normalize_knowledge_worker_payload(_semantic_payload())

    assert payload == {
        "v": "3",
        "bid": "book.ks0000.nr",
        "d": [
            {
                "i": 4,
                "c": "knowledge",
                "gr": {"tk": ["emulsify"], "ck": ["techniques"], "pt": []},
            },
            {
                "i": 5,
                "c": "other",
                "gr": {"tk": [], "ck": [], "pt": []},
            },
        ],
        "g": [
            {
                "gid": "g01",
                "l": "Heat control",
                "bi": [4],
                "s": [],
            }
        ],
    }
    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"


def test_validate_knowledge_shard_output_accepts_grouped_shard_result() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_payload(),
    )

    assert valid is True
    assert errors == ()
    assert metadata["bundle_id"] == "book.ks0000.nr"
    assert metadata["result_block_decision_count"] == 2
    assert metadata["idea_group_count"] == 1


def test_validate_knowledge_shard_output_rejects_group_that_contains_other_block() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_payload(
            idea_groups=[
                {
                    "group_id": "g01",
                    "topic_label": "Too broad",
                    "block_indices": [4, 5],
                }
            ],
        ),
    )

    assert valid is False
    assert errors == ("group_contains_other_block",)
    assert metadata["group_blocks_out_of_surface"] == [5]


def test_validate_knowledge_shard_output_rejects_missing_group_for_kept_block() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_payload(idea_groups=[]),
    )

    assert valid is False
    assert errors == ("knowledge_block_missing_group",)
    assert metadata["knowledge_blocks_missing_group"] == [4]


def test_validate_knowledge_shard_output_rejects_unknown_grounding_tag_keys() -> None:
    payload = _semantic_payload()
    payload["block_decisions"][0]["grounding"]["tag_keys"] = ["not-a-real-tag"]

    valid, errors, metadata = validate_knowledge_shard_output(_shard(), payload)

    assert valid is False
    assert "unknown_grounding_tag_key" in errors
    assert metadata["unknown_grounding_tag_keys"] == ["not-a-real-tag"]


def test_classify_knowledge_validation_failure_marks_near_miss() -> None:
    failure = classify_knowledge_validation_failure(
        validation_errors=("knowledge_block_missing_group",),
        validation_metadata={"knowledge_blocks_missing_group": [4]},
    )

    assert failure["classification"] == "repairable_near_miss"
    assert failure["reason_code"] == "repairable_near_miss"


def test_read_validated_knowledge_outputs_from_proposals_promotes_only_valid_shards(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "book.ks0000.nr.json",
        {
            "payload": normalize_knowledge_worker_payload(_semantic_payload())[0],
            "validation_errors": [],
            "validation_metadata": {"bundle_id": "book.ks0000.nr"},
        },
    )
    _write_json(
        tmp_path / "book.ks0001.nr.json",
        {
            "payload": None,
            "validation_errors": ["missing_output_file"],
            "validation_metadata": {},
        },
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(tmp_path)

    assert sorted(outputs) == ["book.ks0000.nr"]
    assert sorted(payloads_by_shard_id) == ["book.ks0000.nr"]
    assert outputs["book.ks0000.nr"].idea_groups[0].topic_label == "Heat control"


def test_read_validated_knowledge_outputs_from_proposals_accepts_weak_grounding(
    tmp_path: Path,
) -> None:
    payload = _semantic_payload(
        block_decisions=[
            {
                "block_index": 4,
                "category": "knowledge",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
            },
            {
                "block_index": 5,
                "category": "other",
                "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
            },
        ],
    )
    _write_json(
        tmp_path / "book.ks0000.nr.json",
        {
            "payload": payload,
            "validation_errors": [],
            "validation_metadata": {
                "bundle_id": "book.ks0000.nr",
                "weak_grounding_block_count": 1,
                "weak_grounding_reason_counts": {"category_only_grounding": 1},
            },
        },
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(tmp_path)

    assert sorted(outputs) == ["book.ks0000.nr"]
    assert sorted(payloads_by_shard_id) == ["book.ks0000.nr"]
    assert outputs["book.ks0000.nr"].block_decisions[0].grounding.tag_keys == []
    assert outputs["book.ks0000.nr"].block_decisions[0].grounding.category_keys == [
        "techniques"
    ]


def test_read_validated_knowledge_outputs_from_proposals_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    payload = normalize_knowledge_worker_payload(_semantic_payload())[0]
    _write_json(
        tmp_path / "a.json",
        {"payload": payload, "validation_errors": [], "validation_metadata": {}},
    )
    _write_json(
        tmp_path / "b.json",
        {"payload": payload, "validation_errors": [], "validation_metadata": {}},
    )

    with pytest.raises(ValueError, match="Duplicate packet_id"):
        read_validated_knowledge_outputs_from_proposals(tmp_path)
