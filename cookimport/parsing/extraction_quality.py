from __future__ import annotations

from dataclasses import dataclass
import re

from cookimport.core.blocks import Block

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


@dataclass(frozen=True)
class ExtractionScore:
    score: float
    reasons: list[str]
    stats: dict[str, float | int]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_blocks(blocks: list[Block]) -> ExtractionScore:
    if not blocks:
        return ExtractionScore(
            score=0.0,
            reasons=["no_blocks"],
            stats={
                "total_blocks": 0,
                "heading_blocks": 0,
                "list_item_blocks": 0,
                "char_total": 0,
                "long_block_ratio": 1.0,
                "replacement_char_rate": 0.0,
                "control_char_rate": 0.0,
                "role_diversity": 0,
            },
        )

    texts = [str(block.text or "") for block in blocks]
    char_total = sum(len(text) for text in texts)
    heading_blocks = sum(1 for block in blocks if bool(block.features.get("is_heading")))
    list_item_blocks = sum(1 for block in blocks if bool(block.features.get("is_list_item")))
    long_blocks = sum(1 for text in texts if len(text) > 2000)

    replacement_chars = sum(text.count("�") for text in texts)
    control_chars = sum(len(_CONTROL_CHAR_RE.findall(text)) for text in texts)
    block_roles = {
        str(block.features.get("block_role"))
        for block in blocks
        if block.features.get("block_role") is not None
    }

    block_count = len(blocks)
    long_block_ratio = long_blocks / max(block_count, 1)
    replacement_char_rate = replacement_chars / max(char_total, 1)
    control_char_rate = control_chars / max(char_total, 1)

    score = 0.0
    reasons: list[str] = []

    if heading_blocks > 0:
        score += 0.20
    else:
        reasons.append("no_headings_detected")

    if list_item_blocks > 0:
        score += 0.20
    else:
        reasons.append("no_list_items_detected")

    if block_count >= 20:
        score += 0.20
    elif block_count >= 8:
        score += 0.12
        reasons.append("low_block_count")
    else:
        score += 0.04
        reasons.append("very_low_block_count")

    if long_block_ratio <= 0.12:
        score += 0.15
    elif long_block_ratio <= 0.30:
        score += 0.08
        reasons.append("some_overlong_blocks")
    else:
        reasons.append("overlong_blocks_dominate")

    if replacement_char_rate <= 0.001:
        score += 0.15
    elif replacement_char_rate <= 0.01:
        score += 0.07
        reasons.append("replacement_char_noise")
    else:
        reasons.append("replacement_char_rate_high")

    if control_char_rate <= 0.0001:
        score += 0.10
    elif control_char_rate <= 0.001:
        score += 0.05
        reasons.append("control_char_noise")
    else:
        reasons.append("control_char_rate_high")

    role_diversity = len(block_roles)
    if role_diversity >= 3:
        score += 0.10
    elif role_diversity == 2:
        score += 0.06
        reasons.append("limited_role_diversity")
    elif role_diversity == 1:
        score += 0.02
        reasons.append("single_role_only")
    else:
        reasons.append("missing_block_roles")

    score = _clamp(score)
    if score >= 0.75:
        reasons.insert(0, "healthy_structure")

    return ExtractionScore(
        score=score,
        reasons=reasons,
        stats={
            "total_blocks": block_count,
            "heading_blocks": heading_blocks,
            "list_item_blocks": list_item_blocks,
            "char_total": char_total,
            "long_block_ratio": round(long_block_ratio, 6),
            "replacement_char_rate": round(replacement_char_rate, 6),
            "control_char_rate": round(control_char_rate, 6),
            "role_diversity": role_diversity,
        },
    )
