from __future__ import annotations

from collections import Counter

from cookimport.core.blocks import Block

_NEAR_EMPTY_LEN = 3
_SUPER_LONG_LEN = 600


def compute_epub_extraction_health(blocks: list[Block]) -> dict[str, object]:
    normalized_texts = [block.text.strip() for block in blocks if block.text and block.text.strip()]
    lowered_texts = [text.lower() for text in normalized_texts]

    total_blocks = len(blocks)
    non_empty_blocks = len(normalized_texts)
    total_chars = sum(len(text) for text in normalized_texts)
    near_empty_blocks = sum(1 for text in normalized_texts if len(text) <= _NEAR_EMPTY_LEN)
    super_long_blocks = sum(1 for text in normalized_texts if len(text) >= _SUPER_LONG_LEN)

    duplicates = Counter(lowered_texts)
    duplicate_instances = sum(count - 1 for count in duplicates.values() if count > 1)
    duplicate_rate = duplicate_instances / non_empty_blocks if non_empty_blocks else 0.0

    ingredient_like_blocks = sum(
        1
        for block in blocks
        if bool(block.features.get("is_ingredient_likely"))
        or bool(block.features.get("starts_with_quantity"))
    )

    top_repeated_lines = [
        {"text": text[:160], "count": count}
        for text, count in duplicates.most_common(10)
        if count > 1
    ]

    metrics = {
        "total_blocks": total_blocks,
        "non_empty_blocks": non_empty_blocks,
        "total_characters": total_chars,
        "near_empty_block_rate": (
            near_empty_blocks / non_empty_blocks if non_empty_blocks else 0.0
        ),
        "duplicate_block_rate": duplicate_rate,
        "super_long_block_count": super_long_blocks,
        "ingredient_like_block_count": ingredient_like_blocks,
    }

    return {
        "metrics": metrics,
        "warnings": epub_health_warnings(metrics),
        "top_repeated_lines": top_repeated_lines,
    }


def epub_health_warnings(metrics: dict[str, object]) -> list[str]:
    total_blocks = int(metrics.get("total_blocks", 0) or 0)
    non_empty_blocks = int(metrics.get("non_empty_blocks", 0) or 0)
    total_characters = int(metrics.get("total_characters", 0) or 0)
    near_empty_rate = float(metrics.get("near_empty_block_rate", 0.0) or 0.0)
    duplicate_rate = float(metrics.get("duplicate_block_rate", 0.0) or 0.0)
    super_long_blocks = int(metrics.get("super_long_block_count", 0) or 0)
    ingredient_like_blocks = int(metrics.get("ingredient_like_block_count", 0) or 0)

    warnings: list[str] = []
    if non_empty_blocks == 0:
        warnings.append("epub_suspiciously_low_text")
        return warnings

    if near_empty_rate >= 0.35 and non_empty_blocks >= 20:
        warnings.append("epub_empty_block_rate_high")
    if duplicate_rate >= 0.35 and non_empty_blocks >= 20:
        warnings.append("epub_duplicate_block_rate_high")
    if total_characters < 1000 and total_blocks >= 25:
        warnings.append("epub_suspiciously_low_text")
    if super_long_blocks >= 4 and non_empty_blocks >= 25:
        warnings.append("epub_too_many_super_long_blocks")
    if ingredient_like_blocks == 0 and non_empty_blocks >= 40:
        warnings.append("epub_no_ingredient_like_blocks")

    return warnings
