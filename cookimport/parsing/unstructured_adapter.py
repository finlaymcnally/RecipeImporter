"""Unstructured HTML partitioner → Block adapter.

Converts Unstructured elements from partition_html into the repo's Block model,
preserving ordering, split-job invariants, and full traceability metadata.

Env: set DO_NOT_TRACK=true to suppress Unstructured telemetry.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning

logger = logging.getLogger(__name__)

# Suppress Unstructured telemetry at import time.
os.environ.setdefault("DO_NOT_TRACK", "true")
os.environ.setdefault("SCARF_NO_ANALYTICS", "true")

# ---------------------------------------------------------------------------
# Category → BlockType mapping
# ---------------------------------------------------------------------------
_CATEGORY_TO_BLOCK_TYPE: dict[str, BlockType] = {
    "Title": BlockType.TEXT,
    "NarrativeText": BlockType.TEXT,
    "UncategorizedText": BlockType.TEXT,
    "Text": BlockType.TEXT,
    "ListItem": BlockType.TEXT,
    "Table": BlockType.TABLE,
    "FigureCaption": BlockType.TEXT,
    "Image": BlockType.IMAGE,
    "Header": BlockType.TEXT,
    "Footer": BlockType.TEXT,
    "Address": BlockType.TEXT,
    "Formula": BlockType.TEXT,
}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def partition_html_to_blocks(
    html: str,
    *,
    spine_index: int,
    source_location_id: str,
) -> tuple[list[Block], list[dict[str, Any]]]:
    """Partition a single EPUB spine HTML document via Unstructured.

    Returns
    -------
    blocks : list[Block]
        Blocks in stable extracted order (element order within the spine doc).
    diagnostics_rows : list[dict]
        JSON-serializable dicts, one per element, for JSONL persistence.
    """
    from unstructured.partition.html import partition_html as _partition_html

    elements = _partition_html(text=html)

    blocks: list[Block] = []
    diagnostics_rows: list[dict[str, Any]] = []

    for element_index, element in enumerate(elements):
        text = element.text or ""
        # Normalize using the repo's shared cleaning pipeline.
        text = cleaning.normalize_text(text)
        if not text:
            continue

        category = element.category or type(element).__name__
        metadata = element.metadata.to_dict() if hasattr(element.metadata, "to_dict") else {}
        category_depth = metadata.get("category_depth", 0) or 0
        parent_id = metadata.get("parent_id")
        element_id = element.id if hasattr(element, "id") else None

        stable_key = f"{source_location_id}:spine{spine_index}:e{element_index}"

        # Map to BlockType
        block_type = _CATEGORY_TO_BLOCK_TYPE.get(category, BlockType.TEXT)

        # Determine font_weight and heading info
        is_heading = category == "Title"
        heading_level = _clamp(int(category_depth) + 1, 1, 6) if is_heading else None
        font_weight = "bold" if is_heading else "normal"

        block = Block(
            text=text,
            type=block_type,
            font_weight=font_weight,
        )

        # Core traceability features
        block.add_feature("spine_index", spine_index)
        block.add_feature("unstructured_category", category)
        block.add_feature("unstructured_category_depth", int(category_depth))
        block.add_feature("unstructured_parent_id", parent_id)
        block.add_feature("unstructured_element_id", element_id)
        block.add_feature("unstructured_element_index", element_index)
        block.add_feature("unstructured_stable_key", stable_key)
        block.add_feature("source_location_id", source_location_id)

        # EPUB-specific signals expected by downstream (heading, list_item)
        if is_heading:
            block.add_feature("is_heading", True)
            block.add_feature("heading_level", heading_level)
        if category == "ListItem":
            block.add_feature("is_list_item", True)

        blocks.append(block)

        # Diagnostics row for JSONL artifact
        diagnostics_rows.append({
            "source_location_id": source_location_id,
            "spine_index": spine_index,
            "element_index": element_index,
            "element_id": element_id,
            "stable_key": stable_key,
            "category": category,
            "category_depth": int(category_depth),
            "parent_id": parent_id,
            "text": text,
            "html_tag": metadata.get("tag"),
        })

    return blocks, diagnostics_rows
