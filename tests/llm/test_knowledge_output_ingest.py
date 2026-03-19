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
                            "title": None,
                            "body": "Keep whisking.",
                            "tags": [],
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
                    "is_useful": False,
                    "block_decisions": [{"block_index": 4, "category": "other"}],
                    "snippets": [
                        {
                            "title": "Fallback",
                            "body": "Could not process.",
                            "tags": ["invalid"],
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
                                    "title": None,
                                    "body": "Keep whisking.",
                                    "tags": [],
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
