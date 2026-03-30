"""Unstructured HTML partitioner → Block adapter.

Converts Unstructured elements from partition_html into the repo's Block model,
preserving ordering, split-job invariants, and full traceability metadata.

Env: set DO_NOT_TRACK=true to suppress Unstructured telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import warnings
from typing import Any, Literal

from bs4 import BeautifulSoup, FeatureNotFound, XMLParsedAsHTMLWarning

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning
from cookimport.parsing.epub_table_rows import (
    build_structured_epub_row_block,
    extract_structured_epub_rows_from_html,
    render_structured_epub_row_text,
)

logger = logging.getLogger(__name__)

# Suppress Unstructured telemetry at import time.
os.environ.setdefault("DO_NOT_TRACK", "true")
os.environ.setdefault("SCARF_NO_ANALYTICS", "true")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

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
_RECIPE_LIKE_MULTILINE_CATEGORIES = {"Title", "NarrativeText", "UncategorizedText", "Text"}
_RECIPE_LIKE_QUANTITY_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])\b"
)
_RECIPE_LIKE_STEP_RE = re.compile(
    r"^\s*(?:step\s+\d+[\.:)]?|\d+[\.)]\s+|"
    r"add|bake|beat|blend|boil|braise|broil|combine|cook|cool|drain|"
    r"fold|grill|heat|mix|place|pour|preheat|reduce|remove|roast|"
    r"season|serve|simmer|stir|transfer|whisk)\b",
    re.IGNORECASE,
)
_RECIPE_LIKE_HEADER_RE = re.compile(
    r"^\s*(?:ingredients?|instructions?|directions?|method|prep|"
    r"for the\b|to serve\b|serves?\b|makes\b|yield)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UnstructuredHtmlOptions:
    html_parser_version: Literal["v1", "v2"] = "v1"
    skip_headers_and_footers: bool = False
    preprocess_mode: str = "none"


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _to_json_primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _emphasis_coverage_ratio(text: str, emphasized_contents: list[str]) -> float:
    if not text:
        return 0.0
    emphasized_total = 0
    for part in emphasized_contents:
        normalized_part = cleaning.normalize_epub_text(part)
        if not normalized_part:
            continue
        emphasized_total += len(normalized_part)
    if emphasized_total <= 0:
        return 0.0
    return min(1.0, emphasized_total / max(len(text), 1))


def _split_list_item_lines(raw_text: str) -> list[str]:
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result: list[str] = []
    for line in lines:
        normalized_line = cleaning.normalize_epub_text(line)
        if normalized_line:
            result.append(normalized_line)
    return result


def _looks_recipe_like_line(text: str) -> bool:
    if not text:
        return False
    if _RECIPE_LIKE_QUANTITY_RE.match(text):
        return True
    if _RECIPE_LIKE_STEP_RE.match(text):
        return True
    if _RECIPE_LIKE_HEADER_RE.match(text):
        return True
    return False


def _split_recipe_like_multiline_text(raw_text: str, *, category: str) -> list[str]:
    if category not in _RECIPE_LIKE_MULTILINE_CATEGORIES:
        return []
    if "\n" not in raw_text and "\r" not in raw_text:
        return []

    normalized_lines = _split_list_item_lines(raw_text)
    if len(normalized_lines) < 2:
        return []

    recipe_like_count = sum(1 for line in normalized_lines if _looks_recipe_like_line(line))
    if recipe_like_count < 2:
        return []
    return normalized_lines


def _resolve_options(options: UnstructuredHtmlOptions | None) -> UnstructuredHtmlOptions:
    if options is None:
        return UnstructuredHtmlOptions()

    parser_version = str(options.html_parser_version).strip().lower()
    if parser_version not in {"v1", "v2"}:
        raise ValueError(
            "Invalid Unstructured html_parser_version. Expected one of: v1, v2."
        )

    preprocess_mode = str(options.preprocess_mode).strip().lower()
    if preprocess_mode not in {"none", "br_split_v1"}:
        raise ValueError(
            "Invalid Unstructured preprocess_mode. "
            "Expected one of: none, br_split_v1."
        )

    return UnstructuredHtmlOptions(
        html_parser_version=parser_version,  # type: ignore[arg-type]
        skip_headers_and_footers=bool(options.skip_headers_and_footers),
        preprocess_mode=preprocess_mode,
    )


def _prepare_partition_input_html(html: str, *, parser_version: str) -> str:
    if parser_version != "v2":
        return html

    try:
        soup = BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(html, "html.parser")

    if soup.find("body", class_="Document") or soup.find("div", class_="Page"):
        return html

    if soup.html is None:
        html_tag = soup.new_tag("html")
        body_tag = soup.new_tag("body")
        for node in list(soup.contents):
            body_tag.append(node.extract())
        html_tag.append(body_tag)
        soup.append(html_tag)
    elif soup.body is None:
        body_tag = soup.new_tag("body")
        for node in list(soup.html.contents):
            body_tag.append(node.extract())
        soup.html.append(body_tag)

    if soup.body is not None:
        classes = list(soup.body.get("class", []))
        if "Document" not in classes:
            classes.append("Document")
        soup.body["class"] = classes

    return str(soup)


def partition_html_to_blocks(
    html: str,
    *,
    spine_index: int,
    source_location_id: str,
    options: UnstructuredHtmlOptions | None = None,
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

    resolved_options = _resolve_options(options)
    partition_input_html = _prepare_partition_input_html(
        html,
        parser_version=resolved_options.html_parser_version,
    )
    elements = _partition_html(
        text=partition_input_html,
        skip_headers_and_footers=resolved_options.skip_headers_and_footers,
        html_parser_version=resolved_options.html_parser_version,
    )

    blocks: list[Block] = []
    diagnostics_rows: list[dict[str, Any]] = []

    for element_index, element in enumerate(elements):
        raw_text = element.text or ""
        # Normalize using the repo's shared cleaning pipeline.
        text = cleaning.normalize_epub_text(raw_text)
        if not text:
            continue

        category = element.category or type(element).__name__
        metadata = element.metadata.to_dict() if hasattr(element.metadata, "to_dict") else {}
        category_depth = metadata.get("category_depth", 0) or 0
        parent_id = _to_json_primitive(metadata.get("parent_id"))
        element_id = _to_json_primitive(element.id if hasattr(element, "id") else None)
        emphasized_tags = _coerce_string_list(metadata.get("emphasized_text_tags"))
        emphasized_contents = _coerce_string_list(metadata.get("emphasized_text_contents"))
        emphasis_ratio = _emphasis_coverage_ratio(text, emphasized_contents)
        has_bold_tag = any("b" in tag.lower() for tag in emphasized_tags)
        mostly_bold = has_bold_tag and emphasis_ratio >= 0.85

        # Map to BlockType
        block_type = _CATEGORY_TO_BLOCK_TYPE.get(category, BlockType.TEXT)

        text_segments = [text]
        split_reason: str | None = None
        structured_rows = None
        if category == "Table":
            table_html = metadata.get("text_as_html")
            if isinstance(table_html, str):
                structured_rows = extract_structured_epub_rows_from_html(table_html)
            if structured_rows:
                text_segments = [
                    render_structured_epub_row_text(row.cells)
                    for row in structured_rows
                ]
                split_reason = "table_html_rows"
        if category == "ListItem" and ("\n" in raw_text or "\r" in raw_text):
            split_lines = _split_list_item_lines(raw_text)
            if split_lines:
                text_segments = split_lines
                split_reason = "list_item_newline"
        elif category in _RECIPE_LIKE_MULTILINE_CATEGORIES:
            split_lines = _split_recipe_like_multiline_text(raw_text, category=category)
            if split_lines:
                text_segments = split_lines
                split_reason = "recipe_like_multiline"

        stable_key_base = f"{source_location_id}:spine{spine_index}:e{element_index}"
        for split_index, segment_text in enumerate(text_segments):
            stable_key = (
                stable_key_base
                if len(text_segments) == 1
                else f"{stable_key_base}.s{split_index}"
            )

            # Determine font_weight and heading info
            is_heading = category == "Title"
            heading_level = _clamp(int(category_depth) + 1, 1, 6) if is_heading else None
            font_weight = "bold" if (is_heading or mostly_bold) else "normal"

            block = Block(
                text=segment_text,
                type=block_type,
                font_weight=font_weight,
                html=structured_rows[split_index].html if structured_rows else None,
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
            block.add_feature(
                "unstructured_html_parser_version",
                resolved_options.html_parser_version,
            )
            block.add_feature(
                "unstructured_skip_headers_footers",
                bool(resolved_options.skip_headers_and_footers),
            )
            block.add_feature(
                "unstructured_preprocess_mode",
                resolved_options.preprocess_mode,
            )
            block.add_feature("unstructured_emphasis_tags", emphasized_tags)
            block.add_feature(
                "unstructured_emphasis_contents",
                emphasized_contents,
            )
            block.add_feature("unstructured_emphasis_ratio", emphasis_ratio)
            if len(text_segments) > 1:
                block.add_feature("unstructured_split_index", split_index)
                if split_reason is not None:
                    block.add_feature("unstructured_split_reason", split_reason)

            # EPUB-specific signals expected by downstream (heading, list_item)
            if is_heading:
                block.add_feature("is_heading", True)
                block.add_feature("heading_level", heading_level)
            if category == "ListItem":
                block.add_feature("is_list_item", True)
                block.add_feature("list_depth_hint", int(category_depth))
            if structured_rows:
                table_row_block = build_structured_epub_row_block(
                    structured_rows[split_index],
                    structure_source="unstructured_table_html",
                )
                block.features.update(table_row_block.features)

            blocks.append(block)

            # Diagnostics row for JSONL artifact
            diagnostics_rows.append({
                "source_location_id": source_location_id,
                "spine_index": spine_index,
                "element_index": element_index,
                "split_index": split_index if len(text_segments) > 1 else None,
                "split_reason": split_reason if len(text_segments) > 1 else None,
                "element_id": element_id,
                "stable_key": stable_key,
                "category": category,
                "category_depth": int(category_depth),
                "parent_id": parent_id,
                "text": segment_text,
                "html_tag": metadata.get("tag"),
                "html_parser_version": resolved_options.html_parser_version,
                "skip_headers_and_footers": bool(
                    resolved_options.skip_headers_and_footers
                ),
                "preprocess_mode": resolved_options.preprocess_mode,
                "emphasized_text_tags": emphasized_tags,
                "emphasized_text_contents": emphasized_contents,
                "emphasis_ratio": emphasis_ratio,
            })

    return blocks, diagnostics_rows
