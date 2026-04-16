from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_ingest import (
    normalize_knowledge_worker_payload,
    read_validated_knowledge_outputs_from_proposals,
    sanitize_knowledge_worker_payload_for_shard,
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
                "grounding": {
                    "tag_keys": ["emulsify"],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
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
        metadata={"owned_row_indices": [4, 5]},
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
                "gr": {"tk": ["emulsify"], "ck": ["techniques"], "pt": []},
                "wn": None,
                "rq": None,
                "s": [],
            }
        ],
    }
    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"


def test_normalize_knowledge_worker_payload_recovers_missing_packet_id_from_fallback() -> None:
    payload, metadata = normalize_knowledge_worker_payload(
        {
            "block_decisions": _semantic_payload()["block_decisions"],
            "idea_groups": _semantic_payload()["idea_groups"],
        },
        fallback_packet_id="book.ks0000.nr",
    )

    assert payload["bid"] == "book.ks0000.nr"
    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"
    assert metadata["worker_output_packet_id_source"] == "fallback_packet_id"


def test_validate_knowledge_shard_output_rejects_group_that_contains_other_block() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        _shard(),
        _semantic_payload(
            idea_groups=[
                {
                    "group_id": "g01",
                    "topic_label": "Too broad",
                    "block_indices": [4, 5],
                    "grounding": {
                        "tag_keys": ["emulsify"],
                        "category_keys": ["techniques"],
                        "proposed_tags": [],
                    },
                    "why_no_existing_tag": None,
                    "retrieval_query": None,
                }
            ],
        ),
    )

    assert valid is False
    assert errors == ("group_contains_other_block",)
    assert metadata["group_rows_out_of_surface"] == [5]


def test_sanitize_knowledge_worker_payload_preserves_group_grounding() -> None:
    payload, metadata = sanitize_knowledge_worker_payload_for_shard(
        _shard(),
        _semantic_payload(),
    )

    assert metadata["worker_output_contract"] == "semantic_packet_result_v2"
    assert payload["g"] == [
        {
            "gid": "g01",
            "l": "Heat control",
            "bi": [4],
            "gr": {"tk": ["emulsify"], "ck": ["techniques"], "pt": []},
            "wn": None,
            "rq": None,
            "s": [],
        }
    ]


def test_read_validated_knowledge_outputs_from_proposals_loads_group_grounding(tmp_path: Path) -> None:
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    _write_json(
        proposals_dir / "book.ks0000.nr.json",
        {
            "payload": _semantic_payload(),
            "validation_errors": [],
            "validation_metadata": {},
        },
    )

    outputs, payloads_by_packet_id = read_validated_knowledge_outputs_from_proposals(
        proposals_dir
    )

    assert list(outputs) == ["book.ks0000.nr"]
    assert outputs["book.ks0000.nr"].idea_groups[0].grounding.tag_keys == ["emulsify"]
    assert payloads_by_packet_id["book.ks0000.nr"]["g"][0]["gr"]["tk"] == ["emulsify"]
