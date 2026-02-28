from __future__ import annotations

from bisect import bisect_left
from typing import Iterable, Mapping

HOWTO_SECTION_LABEL = "HOWTO_SECTION"
INGREDIENT_LINE_LABEL = "INGREDIENT_LINE"
INSTRUCTION_LINE_LABEL = "INSTRUCTION_LINE"
_SECTION_TARGET_LABELS: tuple[str, str] = (
    INGREDIENT_LINE_LABEL,
    INSTRUCTION_LINE_LABEL,
)


def resolve_howto_label_sets_by_index(
    label_sets_by_index: Mapping[int, Iterable[str]],
    *,
    default_label: str = INSTRUCTION_LINE_LABEL,
) -> dict[int, set[str]]:
    """Map HOWTO_SECTION labels to ingredient/instruction labels using nearby context."""

    resolved: dict[int, set[str]] = {
        int(index): {str(label) for label in labels}
        for index, labels in label_sets_by_index.items()
    }

    target_indices_by_label = {
        label: sorted(
            index
            for index, labels in resolved.items()
            if label in labels and HOWTO_SECTION_LABEL not in labels
        )
        for label in _SECTION_TARGET_LABELS
    }

    for index in sorted(resolved):
        labels = resolved.get(index, set())
        if HOWTO_SECTION_LABEL not in labels:
            continue
        inferred = _infer_section_target_label(
            index=index,
            labels=labels,
            target_indices_by_label=target_indices_by_label,
            default_label=default_label,
        )
        updated = set(labels)
        updated.discard(HOWTO_SECTION_LABEL)
        if inferred:
            updated.add(inferred)
        if not updated:
            updated.add(default_label)
        resolved[index] = updated

    return resolved


def resolve_howto_label_for_range(
    *,
    start_index: int,
    end_index: int,
    label_sets_by_index: Mapping[int, Iterable[str]],
    default_label: str = INSTRUCTION_LINE_LABEL,
) -> str:
    ingredient_votes = 0
    instruction_votes = 0
    for index in range(int(start_index), int(end_index) + 1):
        labels = {str(label) for label in label_sets_by_index.get(index, ())}
        if INGREDIENT_LINE_LABEL in labels:
            ingredient_votes += 1
        if INSTRUCTION_LINE_LABEL in labels:
            instruction_votes += 1
    if ingredient_votes > instruction_votes:
        return INGREDIENT_LINE_LABEL
    if instruction_votes > ingredient_votes:
        return INSTRUCTION_LINE_LABEL
    return default_label


def _infer_section_target_label(
    *,
    index: int,
    labels: set[str],
    target_indices_by_label: Mapping[str, list[int]],
    default_label: str,
) -> str:
    if INGREDIENT_LINE_LABEL in labels and INSTRUCTION_LINE_LABEL not in labels:
        return INGREDIENT_LINE_LABEL
    if INSTRUCTION_LINE_LABEL in labels and INGREDIENT_LINE_LABEL not in labels:
        return INSTRUCTION_LINE_LABEL

    left_label, left_distance = _nearest_label(index, target_indices_by_label, direction="left")
    right_label, right_distance = _nearest_label(index, target_indices_by_label, direction="right")

    if left_label and right_label and left_label == right_label:
        return left_label

    candidates: list[tuple[int, str]] = []
    if left_label is not None and left_distance is not None:
        candidates.append((left_distance, left_label))
    if right_label is not None and right_distance is not None:
        candidates.append((right_distance, right_label))
    if not candidates:
        return default_label

    min_distance = min(distance for distance, _ in candidates)
    nearest = sorted(
        label for distance, label in candidates if distance == min_distance
    )
    if len(nearest) == 1:
        return nearest[0]
    return default_label


def _nearest_label(
    index: int,
    target_indices_by_label: Mapping[str, list[int]],
    *,
    direction: str,
) -> tuple[str | None, int | None]:
    candidates: list[tuple[int, str]] = []
    for label in _SECTION_TARGET_LABELS:
        indices = target_indices_by_label.get(label, [])
        if not indices:
            continue
        position = bisect_left(indices, index)
        if direction == "left":
            candidate = indices[position - 1] if position > 0 else None
            if candidate is None:
                continue
            distance = index - candidate
        else:
            candidate = indices[position] if position < len(indices) else None
            if candidate is None:
                continue
            distance = candidate - index
        candidates.append((distance, label))
    if not candidates:
        return None, None
    distance, label = min(candidates, key=lambda item: (item[0], item[1]))
    return label, distance


__all__ = [
    "HOWTO_SECTION_LABEL",
    "INGREDIENT_LINE_LABEL",
    "INSTRUCTION_LINE_LABEL",
    "resolve_howto_label_for_range",
    "resolve_howto_label_sets_by_index",
]
