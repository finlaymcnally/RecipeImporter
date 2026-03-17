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
