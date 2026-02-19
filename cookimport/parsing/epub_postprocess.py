from __future__ import annotations

import re
from typing import Iterable

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning, patterns

_BULLET_PREFIX_RE = re.compile(r"^(?:[•●◦▪‣·*]|[-–—])\s+")
_PAGE_MARKER_RE = re.compile(r"^(?:page\s*)?\d{1,4}$", re.IGNORECASE)


def postprocess_epub_blocks(blocks: list[Block]) -> list[Block]:
    """Apply shared EPUB cleanup after extraction for all HTML-based extractors."""
    output: list[Block] = []

    for block in blocks:
        normalized_text = cleaning.normalize_epub_text(block.text)
        if not normalized_text:
            continue
        if _is_noise_block(block, normalized_text):
            continue

        segments = _split_segments(block, normalized_text)
        if not segments:
            continue

        base_stable_key = _as_non_empty_str(block.features.get("unstructured_stable_key"))
        for split_index, segment_text in enumerate(segments):
            next_block = block.model_copy(deep=True)
            next_block.text = segment_text
            if len(segments) > 1:
                next_block.add_feature("epub_postprocess_split_index", split_index)
                next_block.add_feature("epub_postprocess_split_count", len(segments))
                if base_stable_key:
                    next_block.add_feature("epub_split_from_stable_key", base_stable_key)
                    next_block.add_feature(
                        "unstructured_stable_key",
                        f"{base_stable_key}:line{split_index}",
                    )
            output.append(next_block)

    return output


def _as_non_empty_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_noise_block(block: Block, text: str) -> bool:
    if block.features.get("epub_noise_kind"):
        return True
    if _PAGE_MARKER_RE.match(text):
        return True
    return False


def _split_segments(block: Block, text: str) -> list[str]:
    lines = _normalize_lines(text.splitlines())
    if len(lines) <= 1:
        return lines

    should_split = (
        block.type == BlockType.TABLE
        or bool(block.features.get("is_list_item"))
        or bool(block.features.get("unstructured_category") == "ListItem")
        or _looks_like_ingredient_lines(lines)
        or (len(lines) >= 3 and max(len(line) for line in lines) <= 90)
    )
    if should_split:
        return lines
    return [cleaning.normalize_epub_text(" ".join(lines))]


def _normalize_lines(lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        line_text = cleaning.normalize_epub_text(line)
        if not line_text:
            continue
        line_text = _BULLET_PREFIX_RE.sub("", line_text)
        line_text = cleaning.normalize_epub_text(line_text)
        if line_text:
            normalized.append(line_text)
    return normalized


def _looks_like_ingredient_lines(lines: list[str]) -> bool:
    return any(patterns.QUANTITY_RE.match(line) for line in lines)
