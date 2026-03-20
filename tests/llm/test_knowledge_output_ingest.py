from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_ingest import (
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


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
