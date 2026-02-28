from __future__ import annotations

import pytest
from pydantic import ValidationError

from cookimport.llm.codex_farm_contracts import (
    Pass1RecipeChunkingInput,
    Pass3FinalDraftOutput,
)


def test_pass1_contract_accepts_required_nullable_fields() -> None:
    payload = Pass1RecipeChunkingInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "heuristic_start_block_index": None,
            "heuristic_end_block_index": None,
            "blocks_before": [],
            "blocks_candidate": [],
            "blocks_after": [],
        }
    )
    assert payload.heuristic_start_block_index is None
    assert payload.heuristic_end_block_index is None


def test_pass1_contract_pattern_hints_are_strict() -> None:
    payload = Pass1RecipeChunkingInput.model_validate(
        {
            "bundle_version": "1",
            "recipe_id": "urn:recipe:test",
            "workbook_slug": "book",
            "source_hash": "hash",
            "heuristic_start_block_index": 10,
            "heuristic_end_block_index": 20,
            "blocks_before": [],
            "blocks_candidate": [],
            "blocks_after": [],
            "pattern_hints": [
                {
                    "hint_type": "duplicate_title_intro",
                    "start_block_index": 10,
                    "end_block_index": 14,
                    "note": "deterministic action: trim_candidate_start",
                }
            ],
        }
    )
    assert payload.pattern_hints
    assert payload.pattern_hints[0].hint_type == "duplicate_title_intro"

    with pytest.raises(ValidationError):
        Pass1RecipeChunkingInput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "workbook_slug": "book",
                "source_hash": "hash",
                "heuristic_start_block_index": 10,
                "heuristic_end_block_index": 20,
                "blocks_before": [],
                "blocks_candidate": [],
                "blocks_after": [],
                "pattern_hints": [
                    {
                        "hint_type": "toc_like_cluster",
                        "unexpected": "extra-key-not-allowed",
                    }
                ],
            }
        )


def test_pass3_contract_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Pass3FinalDraftOutput.model_validate(
            {
                "bundle_version": "1",
                "recipe_id": "urn:recipe:test",
                "draft_v1": {"schema_v": 1},
            }
        )
