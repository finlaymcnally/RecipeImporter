from __future__ import annotations

import re
from pathlib import Path

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning

_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_UNORDERED_LIST_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_ORDERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")


def _new_block(
    text: str,
    *,
    source_path: Path,
    extraction_backend: str,
    md_line_start: int,
    md_line_end: int,
    font_weight: str = "normal",
) -> Block | None:
    normalized = cleaning.normalize_text(text)
    if not normalized:
        return None
    block = Block(
        text=normalized,
        type=BlockType.TEXT,
        font_weight=font_weight,
    )
    block.add_feature("extraction_backend", extraction_backend)
    block.add_feature("md_line_start", md_line_start)
    block.add_feature("md_line_end", md_line_end)
    block.add_feature("source_location_id", source_path.stem)
    return block


def markdown_to_blocks(
    markdown_text: str,
    *,
    source_path: Path,
    extraction_backend: str,
) -> list[Block]:
    """Parse markdown lines into deterministic blocks with line provenance."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph_lines: list[str] = []
    paragraph_start: int | None = None

    def flush_paragraph(end_line: int) -> None:
        nonlocal paragraph_lines, paragraph_start
        if not paragraph_lines or paragraph_start is None:
            paragraph_lines = []
            paragraph_start = None
            return
        paragraph_text = " ".join(line.strip() for line in paragraph_lines if line.strip())
        block = _new_block(
            paragraph_text,
            source_path=source_path,
            extraction_backend=extraction_backend,
            md_line_start=paragraph_start,
            md_line_end=end_line,
        )
        if block is not None:
            blocks.append(block)
        paragraph_lines = []
        paragraph_start = None

    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            flush_paragraph(line_number - 1)
            continue

        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            flush_paragraph(line_number - 1)
            heading_level = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            block = _new_block(
                heading_text,
                source_path=source_path,
                extraction_backend=extraction_backend,
                md_line_start=line_number,
                md_line_end=line_number,
                font_weight="bold",
            )
            if block is not None:
                block.add_feature("is_heading", True)
                block.add_feature("heading_level", heading_level)
                blocks.append(block)
            continue

        list_match = _UNORDERED_LIST_RE.match(raw_line) or _ORDERED_LIST_RE.match(raw_line)
        if list_match:
            flush_paragraph(line_number - 1)
            list_text = list_match.group(1)
            block = _new_block(
                list_text,
                source_path=source_path,
                extraction_backend=extraction_backend,
                md_line_start=line_number,
                md_line_end=line_number,
            )
            if block is not None:
                block.add_feature("is_list_item", True)
                blocks.append(block)
            continue

        if paragraph_start is None:
            paragraph_start = line_number
        paragraph_lines.append(raw_line)

    flush_paragraph(len(lines))
    return blocks
