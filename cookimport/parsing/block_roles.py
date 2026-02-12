"""Deterministic block_role assignment.

Assigns a block_role feature to each Block using cheap, deterministic
heuristics. Roles help downstream chunk lane selection (knowledge vs noise)
and improve debugging visibility.

Roles (stored as Block.features["block_role"]):
    recipe_title       — heading that looks like a recipe name
    ingredient_line    — ingredient-like block
    instruction_line   — instruction-like block
    section_heading    — structural heading (chapter/section)
    tip_like           — short advisory text ("Note:", "Tip:", etc.)
    narrative          — substantive prose (technique, description)
    metadata           — yield, time, serving info
    other              — everything else (short fragments, noise)
"""

from __future__ import annotations

import re
from typing import List

from cookimport.core.blocks import Block

# Patterns for tip-like text
_TIP_PREFIXES_RE = re.compile(
    r"^\s*(note|tip|hint|variation|chef'?s?\s+(?:note|tip)|cook'?s?\s+(?:note|tip))\s*[:—–-]",
    re.IGNORECASE,
)


def assign_block_roles(blocks: List[Block]) -> None:
    """Assign block_role to each block in-place.

    Should be called after signals.enrich_block() so that features like
    is_heading, is_ingredient_likely, is_instruction_likely, is_yield, is_time
    are already populated.
    """
    for block in blocks:
        role = _classify_role(block)
        block.add_feature("block_role", role)


def _classify_role(block: Block) -> str:
    f = block.features
    text = block.text.strip()

    if not text:
        return "other"

    # Metadata (yield, time)
    if f.get("is_yield") or f.get("is_time"):
        return "metadata"

    # Ingredient header or ingredient-like
    if f.get("is_ingredient_header"):
        return "ingredient_line"
    if f.get("is_ingredient_likely") or f.get("starts_with_quantity"):
        return "ingredient_line"

    # Instruction header or instruction-like
    if f.get("is_instruction_header"):
        return "instruction_line"
    if f.get("is_instruction_likely"):
        return "instruction_line"

    # Headings: distinguish recipe titles from section headings
    if f.get("is_heading"):
        heading_level = f.get("heading_level", 3)
        # h1/h2 that are short → likely section/chapter heading
        if heading_level <= 2 and len(text) < 60:
            return "section_heading"
        # Other headings → likely recipe titles
        if len(text) <= 80:
            return "recipe_title"
        return "section_heading"

    # Tip-like text
    if _TIP_PREFIXES_RE.match(text):
        return "tip_like"

    # Narrative: substantive prose (>20 words or multiple sentences)
    word_count = len(text.split())
    if word_count >= 15:
        return "narrative"

    # Short text that's not anything specific
    if word_count < 4:
        return "other"

    return "narrative"
