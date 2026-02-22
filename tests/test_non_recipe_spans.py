from __future__ import annotations

import pytest

from cookimport.llm.non_recipe_spans import (
    Span,
    compute_non_recipe_spans,
    normalize_spans,
    slice_items_by_spans,
)


def test_compute_non_recipe_spans_no_recipe_spans_returns_all() -> None:
    assert compute_non_recipe_spans(5, []) == [Span(0, 5)]


def test_compute_non_recipe_spans_middle_span_returns_two_gaps() -> None:
    assert compute_non_recipe_spans(10, [Span(3, 6)]) == [Span(0, 3), Span(6, 10)]


def test_normalize_spans_merges_overlaps() -> None:
    assert normalize_spans([Span(1, 5), Span(3, 7)]) == [Span(1, 7)]


def test_normalize_spans_merges_adjacent_half_open_spans() -> None:
    assert normalize_spans([Span(1, 3), Span(3, 6)]) == [Span(1, 6)]


def test_compute_non_recipe_spans_span_touches_edges() -> None:
    assert compute_non_recipe_spans(6, [Span(0, 2)]) == [Span(2, 6)]
    assert compute_non_recipe_spans(6, [Span(4, 6)]) == [Span(0, 4)]
    assert compute_non_recipe_spans(6, [Span(0, 6)]) == []


def test_span_validation_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="start must be >= 0"):
        Span(-1, 2)
    with pytest.raises(ValueError, match="end must be > Span.start"):
        Span(2, 2)
    with pytest.raises(ValueError, match="end must be > Span.start"):
        Span(3, 1)


def test_compute_non_recipe_spans_rejects_span_out_of_total_bounds() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        compute_non_recipe_spans(3, [Span(0, 4)])


def test_slice_items_by_spans_concat_slices() -> None:
    items = list("abcdef")
    spans = [Span(0, 2), Span(4, 6)]
    assert slice_items_by_spans(items, spans) == ["a", "b", "e", "f"]


def test_slice_items_by_spans_rejects_out_of_bounds_span() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        slice_items_by_spans([1, 2, 3], [Span(0, 4)])
