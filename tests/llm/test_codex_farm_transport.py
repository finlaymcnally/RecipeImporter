from __future__ import annotations

from cookimport.llm.codex_farm_transport import build_pass2_transport_selection


def test_build_pass2_transport_selection_uses_inclusive_end_and_exclusions() -> None:
    selection = build_pass2_transport_selection(
        recipe_id="urn:recipe:test:toast",
        bundle_name="toast__r000.json",
        pass1_status="ok",
        start_block_index=10,
        end_block_index=12,
        excluded_block_ids=["b11"],
        full_blocks_by_index={
            10: {"index": 10, "block_id": "b10", "text": "Toast"},
            11: {"index": 11, "block_id": "b11", "text": "1 slice bread"},
            12: {"index": 12, "block_id": "b12", "text": "Toast the bread."},
        },
    )

    assert selection.effective_indices == [10, 12]
    assert [int(row["index"]) for row in selection.included_blocks] == [10, 12]
    assert selection.audit["end_index_semantics"] == "inclusive"
    assert selection.audit["mismatch"] is False


def test_build_pass2_transport_selection_reports_missing_effective_indices() -> None:
    selection = build_pass2_transport_selection(
        recipe_id="urn:recipe:test:toast",
        bundle_name="toast__r000.json",
        pass1_status="ok",
        start_block_index=1,
        end_block_index=3,
        excluded_block_ids=[],
        full_blocks_by_index={
            1: {"index": 1, "block_id": "b1", "text": "Toast"},
            3: {"index": 3, "block_id": "b3", "text": "Serve"},
        },
    )

    assert selection.audit["mismatch"] is True
    assert "missing_effective_indices_in_payload" in selection.audit["mismatch_reasons"]
    assert selection.audit["missing_effective_indices"] == [2]
    assert selection.audit["payload_indices"] == [1, 3]


def test_build_pass2_transport_selection_requires_pass1_bounds() -> None:
    selection = build_pass2_transport_selection(
        recipe_id="urn:recipe:test:toast",
        bundle_name="toast__r000.json",
        pass1_status="error",
        start_block_index=None,
        end_block_index=None,
        excluded_block_ids=[],
        full_blocks_by_index={},
    )

    assert selection.audit["mismatch"] is True
    assert "missing_pass1_span_bounds" in selection.audit["mismatch_reasons"]
    assert selection.effective_indices == []
