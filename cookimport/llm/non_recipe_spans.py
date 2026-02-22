from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open span over a block stream: [start, end).

    Conventions:
    - start is inclusive
    - end is exclusive
    - spans are 0-indexed
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Span.start must be >= 0 (got {self.start}).")
        if self.end <= self.start:
            raise ValueError(
                "Span.end must be > Span.start for half-open spans "
                f"[start,end) (got start={self.start}, end={self.end})."
            )


def normalize_spans(spans: Iterable[Span]) -> list[Span]:
    """Sort and merge overlapping/adjacent spans."""
    normalized = sorted(list(spans), key=lambda item: (item.start, item.end))
    if not normalized:
        return []

    merged: list[Span] = []
    current = normalized[0]
    for span in normalized[1:]:
        if span.start <= current.end:
            current = Span(current.start, max(current.end, span.end))
            continue
        merged.append(current)
        current = span
    merged.append(current)
    return merged


def compute_non_recipe_spans(total_blocks: int, recipe_spans: Iterable[Span]) -> list[Span]:
    """Return the complement spans (non-recipe) within [0, total_blocks)."""
    if total_blocks < 0:
        raise ValueError(f"total_blocks must be >= 0 (got {total_blocks}).")

    normalized = normalize_spans(recipe_spans)
    for span in normalized:
        if span.end > total_blocks:
            raise ValueError(
                "Span.end out of bounds for total_blocks "
                f"(span={span}, total_blocks={total_blocks})."
            )

    non_recipe: list[Span] = []
    cursor = 0
    for span in normalized:
        if cursor < span.start:
            non_recipe.append(Span(cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < total_blocks:
        non_recipe.append(Span(cursor, total_blocks))
    return non_recipe


def slice_items_by_spans(items: Sequence[_T], spans: Iterable[Span]) -> list[_T]:
    """Slice a sequence by spans and return the concatenated items."""
    result: list[_T] = []
    total = len(items)
    for span in spans:
        if span.end > total:
            raise ValueError(
                "Span.end out of bounds for items length "
                f"(span={span}, len(items)={total})."
            )
        result.extend(items[span.start : span.end])
    return result
