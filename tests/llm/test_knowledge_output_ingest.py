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
    packet_id: str,
    chunk_id: str,
    block_indices: list[int],
    useful: bool = True,
    snippet_body: str = "Keep whisking.",
    evidence_quote: str = "Keep whisking",
    snippets: list[dict[str, object]] | None = None,
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
                    snippets
                    if snippets is not None
                    else (
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
                    )
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


def test_normalize_knowledge_worker_payload_rewrites_known_semantic_category_aliases() -> None:
    payload, metadata = normalize_knowledge_worker_payload(
        {
            "packet_id": "book.ks0099.nr.task-002",
            "chunk_results": [
                {
                    "chunk_id": "book.c0100.nr",
                    "is_useful": True,
                    "block_decisions": [
                        {"block_index": 8, "category": "content"},
                        {"block_index": 9, "category": "heading"},
                        {
                            "block_index": 10,
                            "category": "noise",
                            "reviewer_category": "front_matter",
                        },
                    ],
                    "snippets": [
                        {
                            "body": "Use enough salt to wake up the stew.",
                            "evidence": [
                                {
                                    "block_index": 8,
                                    "quote": "Use enough salt to wake up the stew.",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    assert metadata == {
        "worker_output_contract": "semantic_packet_result_v1",
        "semantic_category_alias_rewrites": {
            "content": 1,
            "heading": 1,
            "noise": 1,
        },
        "semantic_category_alias_rewrite_count": 3,
    }
    assert payload == {
        "v": "2",
        "bid": "book.ks0099.nr.task-002",
        "r": [
            {
                "cid": "book.c0100.nr",
                "u": True,
                "d": [
                    {"i": 8, "c": "knowledge", "rc": "knowledge"},
                    {"i": 9, "c": "other", "rc": "decorative_heading"},
                    {"i": 10, "c": "other", "rc": "front_matter"},
                ],
                "s": [
                    {
                        "b": "Use enough salt to wake up the stew.",
                        "e": [
                            {
                                "i": 8,
                                "q": "Use enough salt to wake up the stew.",
                            }
                        ],
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


def test_validate_knowledge_shard_output_rewrites_known_semantic_category_aliases() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0099.nr.task-002",
            owned_ids=("book.c0100.nr",),
            metadata={
                "owned_block_indices": [8, 9],
                "ordered_chunk_ids": ["book.c0100.nr"],
                "chunk_block_indices_by_id": {"book.c0100.nr": [8, 9]},
            },
        ),
        {
            "packet_id": "book.ks0099.nr.task-002",
            "chunk_results": [
                {
                    "chunk_id": "book.c0100.nr",
                    "is_useful": True,
                    "block_decisions": [
                        {"block_index": 8, "category": "content"},
                        {"block_index": 9, "category": "content"},
                    ],
                    "snippets": [
                        {
                            "body": "Keep the broth at a lazy simmer.",
                            "evidence": [
                                {
                                    "block_index": 8,
                                    "quote": "Keep the broth at a lazy simmer.",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    assert valid is True
    assert errors == ()
    assert metadata["worker_output_contract"] == "semantic_packet_result_v1"
    assert metadata["semantic_category_alias_rewrites"] == {"content": 2}
    assert metadata["semantic_category_alias_rewrite_count"] == 2


def test_classify_knowledge_validation_failure_marks_snippet_copy_only_near_miss() -> None:
    classification = classify_knowledge_validation_failure(
        validation_errors=("semantic_snippet_echoes_full_chunk",),
        validation_metadata={"echoed_full_chunk_ids": ["book.c0003.nr"]},
    )

    assert classification == {
        "classification": "snippet_copy_only",
        "errors": ["semantic_snippet_echoes_full_chunk"],
        "reason_code": "snippet_copy_only",
        "reason_detail": (
            "At least one snippet body copies the cited evidence or the full owned chunk "
            "surface too closely."
        ),
        "snippet_copy_only": True,
        "has_snippet_copy_error": True,
        "has_schema_or_shape_error": False,
        "has_coverage_error": False,
        "repairable_near_miss": True,
        "snippet_only_repair": True,
    }


def test_classify_knowledge_validation_failure_does_not_treat_mixed_shape_and_snippet_errors_as_narrow_near_miss() -> None:
    classification = classify_knowledge_validation_failure(
        validation_errors=(
            "semantic_snippet_echoes_full_chunk",
            "schema_invalid",
        ),
        validation_metadata={
            "echoed_full_chunk_ids": ["book.c0003.nr"],
            "parse_error": "schema mismatch",
        },
    )

    assert classification["classification"] == "schema_or_shape_invalid"
    assert classification["snippet_copy_only"] is False
    assert classification["repairable_near_miss"] is False
    assert classification["snippet_only_repair"] is False


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


def test_validate_knowledge_shard_output_rejects_near_full_chunk_echo_snippet() -> None:
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
            snippet_body=source_text[18:],
            evidence_quote="turns glossy and smooth",
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0003.nr"]


def test_validate_knowledge_shard_output_rejects_verbatim_block_copy_snippet() -> None:
    source_text = (
        "Use a gentle simmer and stir constantly so the sauce stays glossy, "
        "smooth, and evenly emulsified instead of breaking around the edges."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0007.nr",
            owned_ids=("book.c0007.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0007.nr",
                "c": [
                    {
                        "cid": "book.c0007.nr",
                        "b": [{"i": 14, "t": source_text}],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [14],
                "ordered_chunk_ids": ["book.c0007.nr"],
                "chunk_block_indices_by_id": {"book.c0007.nr": [14]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0007.nr",
            chunk_id="book.c0007.nr",
            block_indices=[14],
            snippet_body=source_text,
            evidence_quote=source_text,
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0007.nr"]
    assert metadata["snippet_echo_reasons_by_chunk_id"] == {
        "book.c0007.nr": ["evidence_surface"]
    }


def test_validate_knowledge_shard_output_rejects_multi_block_evidence_surface_echo() -> None:
    block_a = (
        "Water is an essential element of practically all foods, and it behaves "
        "differently as temperatures rise through the kitchen."
    )
    block_b = (
        "Heat moves by conduction, convection, and radiation, shaping evaporation, "
        "browning, and the pace at which ingredients soften."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0010.nr",
            owned_ids=("book.c0010.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0010.nr",
                "c": [
                    {
                        "cid": "book.c0010.nr",
                        "b": [
                            {"i": 741, "t": block_a},
                            {"i": 742, "t": block_b},
                        ],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [741, 742],
                "ordered_chunk_ids": ["book.c0010.nr"],
                "chunk_block_indices_by_id": {"book.c0010.nr": [741, 742]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0010.nr",
            chunk_id="book.c0010.nr",
            block_indices=[741, 742],
            snippets=[
                {
                    "body": block_a,
                    "evidence": [{"block_index": 741, "quote": block_a}],
                }
            ],
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0010.nr"]
    assert metadata["snippet_echo_reasons_by_chunk_id"] == {
        "book.c0010.nr": ["evidence_surface"]
    }
    assert metadata["evidence_surface_echoes_by_chunk_id"] == {
        "book.c0010.nr": [
            {
                "snippet_index": 0,
                "block_indices": [741],
                "body_char_count": len(block_a.lower()),
                "evidence_surface_char_count": len(block_a.lower()),
            }
        ]
    }


def test_validate_knowledge_shard_output_rejects_aggregate_multi_snippet_copy() -> None:
    block_a = (
        "Water is an essential element of practically all foods, and it behaves "
        "differently as temperatures rise through the kitchen."
    )
    block_b = (
        "Heat moves by conduction, convection, and radiation, shaping evaporation, "
        "browning, and the pace at which ingredients soften."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0011.nr",
            owned_ids=("book.c0011.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0011.nr",
                "c": [
                    {
                        "cid": "book.c0011.nr",
                        "b": [
                            {"i": 741, "t": block_a},
                            {"i": 742, "t": block_b},
                        ],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [741, 742],
                "ordered_chunk_ids": ["book.c0011.nr"],
                "chunk_block_indices_by_id": {"book.c0011.nr": [741, 742]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0011.nr",
            chunk_id="book.c0011.nr",
            block_indices=[741, 742],
            snippets=[
                {
                    "body": block_a,
                    "evidence": [{"block_index": 741, "quote": block_a}],
                },
                {
                    "body": block_b,
                    "evidence": [{"block_index": 742, "quote": block_b}],
                },
            ],
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0011.nr"]
    assert metadata["snippet_echo_reasons_by_chunk_id"] == {
        "book.c0011.nr": ["aggregate_copied_surface", "evidence_surface"]
    }
    assert metadata["aggregate_copied_surface_by_chunk_id"] == {
        "book.c0011.nr": {
            "copied_block_indices": [741, 742],
            "copied_surface_char_count": len(f"{block_a} {block_b}".lower()),
            "full_chunk_char_count": len(f"{block_a} {block_b}".lower()),
            "copied_snippet_count": 2,
        }
    }


def test_validate_knowledge_shard_output_allows_short_exact_heading_quote() -> None:
    block_heading = "Water and Heat"
    block_body = (
        "Control the burner gradually so the pan and its contents warm evenly "
        "instead of scorching before the center catches up."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0012.nr",
            owned_ids=("book.c0012.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0012.nr",
                "c": [
                    {
                        "cid": "book.c0012.nr",
                        "b": [
                            {"i": 801, "t": block_heading},
                            {"i": 802, "t": block_body},
                        ],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [801, 802],
                "ordered_chunk_ids": ["book.c0012.nr"],
                "chunk_block_indices_by_id": {"book.c0012.nr": [801, 802]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0012.nr",
            chunk_id="book.c0012.nr",
            block_indices=[801, 802],
            snippet_body=block_heading,
            evidence_quote=block_heading,
        ),
    )

    assert valid is True
    assert errors == ()
    assert "echoed_full_chunk_ids" not in metadata


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
    assert metadata["strong_cue_empty_chunk_ids"] == ["book.c0005.nr"]
    assert metadata["knowledge_decision_count"] == 0
    assert metadata["snippet_count"] == 0
    assert metadata["useful_chunk_count"] == 0
    assert metadata["semantic_rejection"] is True

    classification = classify_knowledge_validation_failure(
        validation_errors=errors,
        validation_metadata=metadata,
    )
    assert classification["classification"] == "semantic_invalid"
    assert classification["reason_code"] == "semantic_all_false_empty_shard"
    assert "book.c0005.nr" in classification["reason_detail"]


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


def test_validate_knowledge_shard_output_rejects_unknown_semantic_category_alias() -> None:
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0008.nr",
            owned_ids=("book.c0008.nr",),
            metadata={
                "owned_block_indices": [41],
                "ordered_chunk_ids": ["book.c0008.nr"],
                "chunk_block_indices_by_id": {"book.c0008.nr": [41]},
            },
        ),
        {
            "packet_id": "book.ks0008.nr",
            "chunk_results": [
                {
                    "chunk_id": "book.c0008.nr",
                    "is_useful": False,
                    "block_decisions": [{"block_index": 41, "category": "marketing"}],
                    "snippets": [],
                }
            ],
        },
    )

    assert valid is False
    assert errors == ("schema_invalid",)
    assert "marketing" in metadata["parse_error"]


def test_validate_knowledge_shard_output_rejects_saved_run_style_near_full_chunk_echo() -> None:
    source_text = (
        "Salt, Fat, Acid, Heat is a wildly informative culinary resource with clear science, "
        "beautiful storytelling, and inspiration for cooks at every level. It meets you "
        "wherever you are in the kitchen and turns confidence into habit through practice."
    )
    valid, errors, metadata = validate_knowledge_shard_output(
        ShardManifestEntryV1(
            shard_id="book.ks0009.nr",
            owned_ids=("book.c0009.nr",),
            input_payload={
                "v": "2",
                "bid": "book.ks0009.nr",
                "c": [
                    {
                        "cid": "book.c0009.nr",
                        "b": [{"i": 42, "t": source_text}],
                    }
                ],
            },
            metadata={
                "owned_block_indices": [42],
                "ordered_chunk_ids": ["book.c0009.nr"],
                "chunk_block_indices_by_id": {"book.c0009.nr": [42]},
            },
        ),
        _semantic_packet_payload(
            packet_id="book.ks0009.nr",
            chunk_id="book.c0009.nr",
            block_indices=[42],
            snippet_body=source_text[:-12],
            evidence_quote="Salt, Fat, Acid, Heat is a wildly informative culinary resource",
        ),
    )

    assert valid is False
    assert errors == ("semantic_snippet_echoes_full_chunk",)
    assert metadata["echoed_full_chunk_ids"] == ["book.c0009.nr"]


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


def test_read_validated_knowledge_outputs_from_proposals_promotes_accepted_task_subset_from_coverage_only_invalid_wrapper(
    tmp_path: Path,
) -> None:
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "partial.json").write_text(
        json.dumps(
            {
                "shard_id": "book.ks0002.nr",
                "worker_id": "worker-001",
                "validation_errors": ["missing_owned_chunk_results"],
                "validation_metadata": {
                    "missing_owned_chunk_ids": ["book.c0003.nr"],
                    "task_aggregation": {
                        "accepted_task_ids": ["book.ks0002.nr.task-001"],
                        "missing_chunk_ids": ["book.c0003.nr"],
                        "task_id_by_chunk_id": {
                            "book.c0002.nr": "book.ks0002.nr.task-001",
                        },
                        "task_validation_errors_by_task_id": {
                            "book.ks0002.nr.task-002": [
                                "semantic_snippet_echoes_full_chunk"
                            ]
                        },
                    },
                },
                "payload": {
                    "v": "2",
                    "bid": "book.ks0002.nr",
                    "r": [
                        {
                            "cid": "book.c0002.nr",
                            "u": True,
                            "d": [{"i": 7, "c": "knowledge", "rc": "knowledge"}],
                            "s": [
                                {
                                    "b": "Keep whisking the butter into the sauce.",
                                    "e": [
                                        {
                                            "i": 7,
                                            "q": "Keep whisking the butter into the sauce.",
                                        }
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

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(
        proposals_dir
    )

    assert set(outputs) == {"book.c0002.nr"}
    assert set(payloads_by_shard_id) == {"book.ks0002.nr"}
    assert payloads_by_shard_id["book.ks0002.nr"]["r"][0]["cid"] == "book.c0002.nr"
