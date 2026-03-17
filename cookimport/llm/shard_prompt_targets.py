from __future__ import annotations

import math
from typing import Any

DEFAULT_PHASE_PROMPT_TARGET_COUNT = 5


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
