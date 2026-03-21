from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_ingest import (
    normalize_knowledge_worker_payload,
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


def _semantic_packet_payload(
    *,
    packet_id: str,
    chunk_id: str,
    block_indices: list[int],
    useful: bool = True,
    snippet_body: str = "Keep whisking.",
    evidence_quote: str = "Keep whisking",
) -> dict[str, object]:
    block_decisions = [
        {
            "block_index": block_index,
            "category": "knowledge" if useful else "other",
        }
        for block_index in block_indices
    ]
    return {
        "packet_id": packet_id,
        "chunk_results": [
            {
                "chunk_id": chunk_id,
                "is_useful": useful,
                "block_decisions": block_decisions,
                "snippets": (
                    [
                        {
                            "body": snippet_body,
                            "evidence": [
                                {
                                    "block_index": block_indices[0],
                                    "quote": evidence_quote,
                                }
                            ],
                        }
                    ]
                    if useful
                    else []
                ),
                "reason_code": "grounded_useful" if useful else "all_other",
            }
        ],
    }


def test_normalize_knowledge_worker_payload_serializes_semantic_packet_result() -> None:
    payload, metadata = normalize_knowledge_worker_payload(
        _semantic_packet_payload(
            packet_id="book.ks0099.nr.task-001",
            chunk_id="book.c0099.nr",
            block_indices=[4, 5],
        )
    )

    assert metadata == {"worker_output_contract": "semantic_packet_result_v1"}
    assert payload == {
        "v": "2",
        "bid": "book.ks0099.nr.task-001",
        "r": [
            {
                "cid": "book.c0099.nr",
                "u": True,
                "d": [
                    {"i": 4, "c": "knowledge", "rc": "knowledge"},
                    {"i": 5, "c": "knowledge", "rc": "knowledge"},
                ],
                "s": [
                    {
                        "b": "Keep whisking.",
                        "e": [{"i": 4, "q": "Keep whisking"}],
                    }
                ],
            }
        ],
    }


def test_validate_knowledge_shard_output_accepts_semantic_packet_result() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0099.nr.task-001",
            owned_ids=("book.c0099.nr",),
            metadata={
                "owned_block_indices": [4, 5],
                "ordered_chunk_ids": ["book.c0099.nr"],
                "chunk_block_indices_by_id": {"book.c0099.nr": [4, 5]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0099.nr.task-001",
            chunk_id="book.c0099.nr",
            block_indices=[4, 5],
        ),
    )

    assert valid is True
    assert errors == ()
    assert metadata["worker_output_contract"] == "semantic_packet_result_v1"
    assert metadata["bundle_id"] == "book.ks0099.nr.task-001"
    assert metadata["result_chunk_count"] == 1


def test_validate_knowledge_shard_output_requires_exact_owned_chunk_ids() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0000.nr",
            owned_ids=("book.c0000.nr", "book.c0001.nr"),
            metadata={"owned_block_indices": [4, 5]},
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0000.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0000.nr",
                    "is_useful": True,
                    "block_decisions": [{"block_index": 4, "category": "knowledge"}],
                        "snippets": [
                            {
                                "body": "Keep whisking.",
                                "evidence": [{"block_index": 4, "quote": "Keep whisking"}],
                            }
                        ],
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("missing_owned_chunk_results",)
    assert metadata["missing_owned_chunk_ids"] == ["book.c0001.nr"]


def test_validate_knowledge_shard_output_rejects_empty_result_array_for_owned_chunks() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0003.nr",
            owned_ids=("book.c0100.nr", "book.c0101.nr"),
            metadata={"owned_block_indices": [40, 41]},
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0003.nr",
            "chunk_results": [],
        },
    )

    assert valid is False
    assert errors == ("missing_owned_chunk_results",)
    assert metadata["result_chunk_count"] == 0
    assert metadata["missing_owned_chunk_ids"] == ["book.c0100.nr", "book.c0101.nr"]


def test_validate_knowledge_shard_output_rejects_synthetic_processing_error_chunk() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0001.nr",
            owned_ids=("book.c0007.nr",),
            metadata={"owned_block_indices": [4]},
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0001.nr",
            "chunk_results": [
                {
                    "chunk_id": "processing_error",
                    "is_useful": True,
                    "block_decisions": [{"block_index": 4, "category": "knowledge"}],
                    "snippets": [
                        {
                            "body": "Could not process.",
                            "evidence": [{"block_index": 0, "quote": "bad"}],
                        }
                    ],
                }
            ],
        },
    )

    assert valid is False
    assert errors == (
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
        "snippet_evidence_out_of_surface",
    )
    assert metadata["missing_owned_chunk_ids"] == ["book.c0007.nr"]
    assert metadata["unexpected_chunk_ids"] == ["processing_error"]
    assert metadata["out_of_surface_evidence_block_indices"] == [0]


def test_validate_knowledge_shard_output_requires_exact_block_decision_coverage() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0002.nr",
            owned_ids=("book.c0002.nr",),
            metadata={
                "owned_block_indices": [8, 9],
                "ordered_chunk_ids": ["book.c0002.nr"],
                "chunk_block_indices_by_id": {"book.c0002.nr": [8, 9]},
            },
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0002.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0002.nr",
                    "is_useful": False,
                    "block_decisions": [{"block_index": 8, "category": "other"}],
                    "snippets": [],
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("block_decision_coverage_mismatch",)
    assert metadata["chunk_block_coverage_mismatches"] == {
        "book.c0002.nr": {"expected": [8, 9], "observed": [8]}
    }


def test_validate_knowledge_shard_output_rejects_non_grounded_snippet_body() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0002.nr",
            owned_ids=("book.c0002.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0002.nr",
                "c": [
                    {
                        "cid": "book.c0002.nr",
                        "b": [{"i": 8, "t": "Whisk the batter until smooth."}],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [8],
                "ordered_chunk_ids": ["book.c0002.nr"],
                "chunk_block_indices_by_id": {"book.c0002.nr": [8]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0002.nr",
            chunk_id="book.c0002.nr",
            block_indices=[8],
            snippet_body="12345!!!",
            evidence_quote="Whisk the batter",
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_body_not_grounded_text",)
    assert metadata["non_grounded_snippet_chunk_ids"] == ["book.c0002.nr"]


def test_validate_knowledge_shard_output_rejects_full_chunk_echo_snippet() -> None:
    source_text = (
        "Whisk the batter slowly until it turns glossy and smooth, then scrape the bowl "
        "well and keep mixing until no dry pockets remain anywhere in the mixture, "
        "pausing only to fold down the sides and bottom so the texture stays even."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0003.nr",
            owned_ids=("book.c0003.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0003.nr",
                "c": [
                    {
                        "cid": "book.c0003.nr",
                        "b": [{"i": 9, "t": source_text}],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [9],
                "ordered_chunk_ids": ["book.c0003.nr"],
                "chunk_block_indices_by_id": {"book.c0003.nr": [9]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0003.nr",
            chunk_id="book.c0003.nr",
            block_indices=[9],
            snippet_body=source_text,
            evidence_quote="Whisk the batter slowly",
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0003.nr"]


def test_validate_knowledge_shard_output_rejects_cross_chunk_evidence() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0004.nr",
            owned_ids=("book.c0004.nr",),
            metadata={
                "owned_block_indices": [12, 13],
                "ordered_chunk_ids": ["book.c0004.nr"],
                "chunk_block_indices_by_id": {"book.c0004.nr": [12, 13]},
            },
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0004.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0004.nr",
                    "is_useful": True,
                    "block_decisions": [
                        {"block_index": 12, "category": "knowledge"},
                        {"block_index": 13, "category": "knowledge"},
                    ],
                    "snippets": [
                        {
                            "body": "Use a low simmer.",
                            "evidence": [{"block_index": 99, "quote": "bad pointer"}],
                        }
                    ],
                }
            ],
        },
    )

    assert valid is False
    assert errors == (
        "snippet_evidence_out_of_surface",
        "snippet_evidence_wrong_chunk_surface",
    )
    assert metadata["cross_chunk_evidence_by_chunk_id"] == {"book.c0004.nr": [99]}


def test_validate_knowledge_shard_output_rejects_semantic_all_false_empty_shard() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0005.nr",
            owned_ids=("book.c0005.nr",),
            metadata={
                "owned_block_indices": [20, 21],
                "ordered_chunk_ids": ["book.c0005.nr"],
                "chunk_block_indices_by_id": {"book.c0005.nr": [20, 21]},
                "chunk_knowledge_cue_by_id": {"book.c0005.nr": True},
            },
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0005.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0005.nr",
                    "is_useful": False,
                    "block_decisions": [
                        {"block_index": 20, "category": "other"},
                        {"block_index": 21, "category": "other"},
                    ],
                    "snippets": [],
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("semantic_all_false_empty_shard",)
    assert metadata["knowledge_cue_chunk_ids"] == ["book.c0005.nr"]
    assert metadata["semantic_rejection"] is True


def test_validate_knowledge_shard_output_allows_true_all_other_front_matter() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0006.nr",
            owned_ids=("book.c0006.nr",),
            metadata={
                "owned_block_indices": [30, 31],
                "ordered_chunk_ids": ["book.c0006.nr"],
                "chunk_block_indices_by_id": {"book.c0006.nr": [30, 31]},
                "chunk_knowledge_cue_by_id": {"book.c0006.nr": False},
            },
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0006.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0006.nr",
                    "is_useful": False,
                    "block_decisions": [
                        {"block_index": 30, "category": "other"},
                        {"block_index": 31, "category": "other"},
                    ],
                    "snippets": [],
                }
            ],
        },
    )

    assert valid is True
    assert errors == ()
    assert metadata["reviewed_all_other"] is True
    assert metadata["semantic_rejection"] is False


def test_validate_knowledge_shard_output_requires_useful_rows_to_include_snippet() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0007.nr",
            owned_ids=("book.c0007.nr",),
            metadata={"owned_block_indices": [40], "chunk_block_indices_by_id": {"book.c0007.nr": [40]}},
        ),
        {
            "bundle_version": "2",
            "bundle_id": "book.ks0007.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0007.nr",
                    "is_useful": True,
                    "block_decisions": [{"block_index": 40, "category": "knowledge"}],
                    "snippets": [],
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("schema_invalid",)
    assert "useful chunk results must include at least one snippet" in metadata["parse_error"]


def test_read_validated_knowledge_outputs_from_proposals_skips_invalid_rows(
    tmp_path: Path,
) -> None:
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "valid.json").write_text(
        json.dumps(
            {
                "shard_id": "book.ks0000.nr",
                "worker_id": "worker-001",
                "validation_errors": [],
                "payload": {
                    "bundle_version": "2",
                    "bundle_id": "book.ks0000.nr",
                    "chunk_results": [
                        {
                            "chunk_id": "book.c0000.nr",
                            "is_useful": True,
                            "block_decisions": [
                                {"block_index": 4, "category": "knowledge"},
                            ],
                            "snippets": [
                                {
                                    "body": "Keep whisking.",
                                    "evidence": [
                                        {"block_index": 4, "quote": "Keep whisking"}
                                    ],
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (proposals_dir / "invalid.json").write_text(
        json.dumps(
            {
                "shard_id": "book.ks0001.nr",
                "worker_id": "worker-001",
                "validation_errors": ["block_decision_out_of_surface"],
                "payload": {
                    "bundle_version": "2",
                    "bundle_id": "book.ks0001.nr",
                    "chunk_results": [],
                },
            }
        ),
        encoding="utf-8",
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(
        proposals_dir
    )

    assert set(outputs) == {"book.c0000.nr"}
    assert set(payloads_by_shard_id) == {"book.ks0000.nr"}
