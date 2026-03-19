from __future__ import annotations

import math
from typing import Any, Sequence, TypeVar

DEFAULT_PHASE_PROMPT_TARGET_COUNT = 5
T = TypeVar("T")


def coerce_positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def resolve_items_per_shard(
    *,
    total_items: int,
    prompt_target_count: Any,
    items_per_shard: Any,
    default_items_per_shard: int,
) -> int:
    effective_total = max(0, int(total_items or 0))
    configured_items_per_shard = coerce_positive_int(items_per_shard)
    if configured_items_per_shard is not None:
        return configured_items_per_shard
    configured_prompt_target = coerce_positive_int(prompt_target_count)
    if effective_total <= 0:
        return 1
    if configured_prompt_target is not None:
        if effective_total <= configured_prompt_target:
            return effective_total
        return max(1, int(math.ceil(effective_total / configured_prompt_target)))
    return max(1, int(default_items_per_shard))


def resolve_shard_count(
    *,
    total_items: int,
    prompt_target_count: Any,
    items_per_shard: Any,
    default_items_per_shard: int,
) -> int:
    effective_total = max(0, int(total_items or 0))
    if effective_total <= 0:
        return 0
    configured_items_per_shard = coerce_positive_int(items_per_shard)
    if configured_items_per_shard is not None:
        return max(1, int(math.ceil(float(effective_total) / float(configured_items_per_shard))))
    configured_prompt_target = coerce_positive_int(prompt_target_count)
    if configured_prompt_target is not None:
        return max(1, min(effective_total, configured_prompt_target))
    default_items = max(1, int(default_items_per_shard))
    return max(1, int(math.ceil(float(effective_total) / float(default_items))))


def partition_contiguous_items(
    items: Sequence[T],
    *,
    shard_count: int,
) -> list[list[T]]:
    total_items = len(items)
    if total_items <= 0:
        return []
    effective_shard_count = max(1, min(int(shard_count or 1), total_items))
    base_size, remainder = divmod(total_items, effective_shard_count)
    partitions: list[list[T]] = []
    start = 0
    for shard_index in range(effective_shard_count):
        size = base_size + (1 if shard_index < remainder else 0)
        end = start + size
        partitions.append(list(items[start:end]))
        start = end
    return partitions
