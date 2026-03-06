from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_PAGE_MARKER_ONLY_RE = re.compile(r"^\s*(?:page|p\.?)?\s*[#:]?\s*\d{1,4}\s*$", re.IGNORECASE)
_PAGE_MARKER_PREFIX_RE = re.compile(
    r"^\s*(?:page|p\.?)\s*#?\s*\d{1,4}\s*[-:|]\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_HEADING_LINE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 '&:/()\-]{2,80}$")
_SPACED_FRACTION_RE = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_QUANTITY_START_RE = re.compile(
    r"(?<!\w)"
    r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])"
    r"(?:\s*(?:"
    r"cups?|cup|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|"
    r"pounds?|lbs?|lb|grams?|g|kilograms?|kg|milliliters?|ml|"
    r"liters?|litres?|l|cloves?|cans?|packages?|pkg|pinch|dash|sprigs?"
    r"))?",
    re.IGNORECASE,
)


def normalize_pass2_evidence(
    blocks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build additive normalized evidence from pass2 blocks with provenance."""

    line_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    stats = {
        "input_block_count": len(blocks),
        "input_line_count": 0,
        "output_line_count": 0,
        "dropped_page_markers": 0,
        "folded_page_markers": 0,
        "split_quantity_lines": 0,
    }

    for block in blocks:
        block_index = _coerce_int(block.get("index"))
        if block_index is None:
            continue
        block_id = str(block.get("block_id") or f"b{block_index}")
        block_text = str(block.get("text") or "")
        heading_level = _coerce_int(block.get("heading_level"))

        raw_lines = block_text.splitlines() or [block_text]
        for source_line_index, raw_line in enumerate(raw_lines):
            text = _collapse_whitespace(raw_line)
            if not text:
                continue
            text = _normalize_numeric_slash_spacing(text)
            stats["input_line_count"] += 1

            if _is_heading_line(text, heading_level=heading_level):
                _append_line_row(
                    line_rows,
                    text=text,
                    source_block_index=block_index,
                    source_block_id=block_id,
                    source_line_index=source_line_index,
                    transform="heading_preserved",
                )
                continue

            if _PAGE_MARKER_ONLY_RE.match(text):
                stats["dropped_page_markers"] += 1
                events.append(
                    {
                        "action": "drop_page_marker",
                        "block_index": block_index,
                        "block_id": block_id,
                        "source_line_index": source_line_index,
                        "original_text": text,
                    }
                )
                continue

            folded_text = _fold_page_marker_prefix(text)
            if folded_text != text:
                stats["folded_page_markers"] += 1
                events.append(
                    {
                        "action": "fold_page_marker",
                        "block_index": block_index,
                        "block_id": block_id,
                        "source_line_index": source_line_index,
                        "original_text": text,
                        "normalized_text": folded_text,
                    }
                )
                text = folded_text

            split_lines = _split_quantity_item_join(text)
            if len(split_lines) > 1:
                stats["split_quantity_lines"] += 1
                events.append(
                    {
                        "action": "split_quantity_item_join",
                        "block_index": block_index,
                        "block_id": block_id,
                        "source_line_index": source_line_index,
                        "original_text": text,
                        "normalized_lines": split_lines,
                    }
                )
            for normalized_line in split_lines:
                _append_line_row(
                    line_rows,
                    text=normalized_line,
                    source_block_index=block_index,
                    source_block_id=block_id,
                    source_line_index=source_line_index,
                    transform="normalized",
                )

    normalized_lines = [str(row["text"]) for row in line_rows]
    stats["output_line_count"] = len(normalized_lines)
    return {
        "normalized_evidence_text": "\n".join(normalized_lines).strip(),
        "normalized_evidence_lines": normalized_lines,
        "line_rows": line_rows,
        "events": events,
        "stats": stats,
    }


def _append_line_row(
    rows: list[dict[str, Any]],
    *,
    text: str,
    source_block_index: int,
    source_block_id: str,
    source_line_index: int,
    transform: str,
) -> None:
    cleaned = _collapse_whitespace(text)
    if not cleaned:
        return
    rows.append(
        {
            "text": cleaned,
            "source_block_index": source_block_index,
            "source_block_id": source_block_id,
            "source_line_index": source_line_index,
            "transform": transform,
        }
    )


def _is_heading_line(text: str, *, heading_level: int | None) -> bool:
    if heading_level is not None and heading_level > 0:
        return True
    if _QUANTITY_START_RE.match(text):
        return False
    return bool(_HEADING_LINE_RE.match(text))


def _fold_page_marker_prefix(text: str) -> str:
    match = _PAGE_MARKER_PREFIX_RE.match(text)
    if not match:
        return text
    return _collapse_whitespace(match.group("rest"))


def _split_quantity_item_join(text: str) -> list[str]:
    matches = list(_QUANTITY_START_RE.finditer(text))
    if len(matches) < 2:
        return [text]

    boundaries: list[int] = []
    for match in matches[1:]:
        candidate = match.start()
        if candidate > 0 and text[candidate - 1] == "/":
            continue
        left = text[:candidate].strip(" ;,|")
        right = text[candidate:].strip(" ;,|")
        if left.endswith("/"):
            continue
        if not _looks_like_ingredient_fragment(left):
            continue
        if not _looks_like_ingredient_fragment(right):
            continue
        if left.endswith(":"):
            continue
        boundaries.append(candidate)

    if not boundaries:
        return [text]

    parts: list[str] = []
    cursor = 0
    for boundary in boundaries:
        part = _collapse_whitespace(text[cursor:boundary].strip(" ;,|"))
        if part:
            parts.append(part)
        cursor = boundary
    tail = _collapse_whitespace(text[cursor:].strip(" ;,|"))
    if tail:
        parts.append(tail)

    unique_parts = [part for part in parts if part]
    if len(unique_parts) < 2:
        return [text]
    return unique_parts


def _looks_like_ingredient_fragment(value: str) -> bool:
    text = _collapse_whitespace(value)
    if len(text) < 4:
        return False
    alpha_count = sum(1 for char in text if char.isalpha())
    return alpha_count >= 2


def _collapse_whitespace(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _normalize_numeric_slash_spacing(value: str) -> str:
    text = str(value or "")
    return _SPACED_FRACTION_RE.sub(r"\1/\2", text)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
