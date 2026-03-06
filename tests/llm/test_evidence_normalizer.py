from __future__ import annotations

from cookimport.llm.evidence_normalizer import normalize_pass2_evidence


def test_normalize_pass2_evidence_drops_and_folds_page_markers() -> None:
    payload = normalize_pass2_evidence(
        [
            {"index": 10, "block_id": "b10", "text": "Page 10"},
            {"index": 11, "block_id": "b11", "text": "P. 11 - 1 cup sugar"},
        ]
    )

    assert payload["normalized_evidence_lines"] == ["1 cup sugar"]
    assert payload["stats"]["dropped_page_markers"] == 1
    assert payload["stats"]["folded_page_markers"] == 1
    assert payload["stats"]["output_line_count"] == 1


def test_normalize_pass2_evidence_splits_joined_quantity_lines() -> None:
    payload = normalize_pass2_evidence(
        [
            {
                "index": 20,
                "block_id": "b20",
                "text": "1 cup sugar 2 tbsp butter",
            }
        ]
    )

    assert payload["normalized_evidence_lines"] == ["1 cup sugar", "2 tbsp butter"]
    assert payload["stats"]["split_quantity_lines"] == 1
    assert payload["stats"]["output_line_count"] == 2


def test_normalize_pass2_evidence_preserves_heading_lines() -> None:
    payload = normalize_pass2_evidence(
        [
            {
                "index": 30,
                "block_id": "b30",
                "text": "FOR THE SAUCE",
            }
        ]
    )

    assert payload["normalized_evidence_lines"] == ["FOR THE SAUCE"]
    assert payload["line_rows"][0]["transform"] == "heading_preserved"


def test_normalize_pass2_evidence_normalizes_spaced_fractions() -> None:
    payload = normalize_pass2_evidence(
        [
            {
                "index": 40,
                "block_id": "b40",
                "text": "Makes about 1 / 2 cup",
            }
        ]
    )

    assert payload["normalized_evidence_lines"] == ["Makes about 1/2 cup"]


def test_normalize_pass2_evidence_keeps_dual_unit_lines_together() -> None:
    payload = normalize_pass2_evidence(
        [
            {
                "index": 50,
                "block_id": "b50",
                "text": "1 quart/1 L water 2 tbsp salt",
            }
        ]
    )

    assert payload["normalized_evidence_lines"] == [
        "1 quart/1 L water",
        "2 tbsp salt",
    ]
