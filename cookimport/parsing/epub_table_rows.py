from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Sequence

from bs4 import BeautifulSoup, FeatureNotFound, Tag, XMLParsedAsHTMLWarning

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning

EPUB_TABLE_CELL_DELIMITER = " | "


@dataclass(frozen=True)
class EpubStructuredRow:
    cells: list[str]
    html: str
    is_header_row: bool


def extract_structured_epub_rows_from_html(html: str) -> list[EpubStructuredRow]:
    if not html:
        return []
    soup = _soup_from_html(html)
    rows: list[EpubStructuredRow] = []
    for row in soup.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        structured_row = structured_epub_row_from_tag(row)
        if structured_row is not None:
            rows.append(structured_row)
    return rows


def structured_epub_row_from_tag(row: Tag) -> EpubStructuredRow | None:
    cells = [cell for cell in row.find_all(_is_table_cell_tag, recursive=False)]
    if not cells:
        cells = [cell for cell in row.find_all(_is_table_cell_tag)]
    if not cells:
        return None

    normalized_cells = [
        cleaning.normalize_epub_text(cell.get_text(" ", strip=True))
        for cell in cells
    ]
    if not any(cell for cell in normalized_cells):
        return None

    header_like_cells = sum(1 for cell in cells if _is_header_like_cell(cell))
    return EpubStructuredRow(
        cells=normalized_cells,
        html=str(row),
        is_header_row=header_like_cells >= max(1, len(cells)),
    )


def render_structured_epub_row_text(cells: Sequence[str]) -> str:
    return EPUB_TABLE_CELL_DELIMITER.join(str(cell or "").strip() for cell in cells)


def build_structured_epub_row_block(
    row: EpubStructuredRow,
    *,
    structure_source: str,
) -> Block:
    block = Block(
        text=render_structured_epub_row_text(row.cells),
        type=BlockType.TABLE,
        html=row.html,
        font_weight="normal",
    )
    block.add_feature("epub_table_row", True)
    block.add_feature("epub_table_cells", list(row.cells))
    block.add_feature("epub_table_column_count", len(row.cells))
    block.add_feature("epub_table_header_row", row.is_header_row)
    block.add_feature("epub_table_structure_source", structure_source)
    return block


def _soup_from_html(html: str) -> BeautifulSoup:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        try:
            return BeautifulSoup(html, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(html, "html.parser")


def _is_table_cell_tag(tag: Tag) -> bool:
    return tag.name in {"td", "th"}


def _is_header_like_cell(cell: Tag) -> bool:
    if cell.name == "th":
        return True
    class_tokens = [str(token).strip().lower() for token in cell.get("class", [])]
    return any("head" in token for token in class_tokens)
