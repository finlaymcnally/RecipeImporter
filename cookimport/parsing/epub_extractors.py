from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Protocol

from bs4 import BeautifulSoup, FeatureNotFound, Tag

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning
from cookimport.parsing.markdown_blocks import markdown_to_blocks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EpubExtractionResult:
    blocks: list[Block]
    diagnostics_rows: list[dict[str, Any]]
    meta: dict[str, Any]


class EpubExtractor(Protocol):
    name: str

    def extract_spine_html(
        self,
        html: str,
        *,
        spine_index: int,
        source_location_id: str,
    ) -> EpubExtractionResult:
        ...


def _soup_from_html(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


class BeautifulSoupEpubExtractor:
    name = "beautifulsoup"

    _BULLET_PREFIX_RE = re.compile(r"^(?:[•●◦▪‣·*]|[-–—])\s+")

    def extract_spine_html(
        self,
        html: str,
        *,
        spine_index: int,
        source_location_id: str,
    ) -> EpubExtractionResult:
        soup = _soup_from_html(html)
        blocks: list[Block] = []
        diagnostics_rows: list[dict[str, Any]] = []
        emitted_table_nodes: set[int] = set()
        element_index = 0

        for row in soup.find_all("tr"):
            if not isinstance(row, Tag):
                continue
            if self._is_pagebreak_tag(row):
                continue
            if row.find_parent("nav"):
                continue
            row_block = self._build_table_row_block(
                row,
                spine_index=spine_index,
                source_location_id=source_location_id,
            )
            if row_block is None:
                continue

            stable_key = (
                f"{source_location_id}:spine{spine_index}:beautifulsoup{element_index}"
            )
            row_block.add_feature("beautifulsoup_stable_key", stable_key)
            blocks.append(row_block)
            diagnostics_rows.append(
                {
                    "source_location_id": source_location_id,
                    "spine_index": spine_index,
                    "element_index": element_index,
                    "tag_name": "tr",
                    "stable_key": stable_key,
                    "text": row_block.text,
                }
            )
            element_index += 1

            emitted_table_nodes.add(id(row))
            for cell in row.find_all(self._is_table_cell_tag):
                emitted_table_nodes.add(id(cell))

        for elem in soup.find_all(self._is_block_tag):
            if not isinstance(elem, Tag):
                continue
            if elem.name == "tr":
                continue
            if id(elem) in emitted_table_nodes:
                continue
            if self._is_pagebreak_tag(elem):
                continue

            nav_parent = elem.find_parent("nav")
            if isinstance(nav_parent, Tag):
                nav_tokens = (
                    self._tag_attr_tokens(nav_parent, "epub:type")
                    + self._tag_attr_tokens(nav_parent, "type")
                    + self._tag_attr_tokens(nav_parent, "role")
                )
                if any(token in {"toc", "doc-toc", "navigation"} for token in nav_tokens):
                    continue

            if self._has_block_children(elem):
                continue

            text = cleaning.normalize_epub_text(elem.get_text("\n"))
            if text:
                text = self._BULLET_PREFIX_RE.sub("", text)
                text = cleaning.normalize_epub_text(text)
            if not text:
                continue

            block_type = BlockType.TABLE if elem.name in {"td", "th"} else BlockType.TEXT
            block = Block(
                text=text,
                type=block_type,
                html=str(elem),
                font_weight=(
                    "bold"
                    if elem.name.startswith("h") or elem.find("strong") or elem.find("b")
                    else "normal"
                ),
            )
            block.add_feature("extraction_backend", self.name)
            block.add_feature("spine_index", spine_index)
            block.add_feature("source_location_id", source_location_id)
            if elem.name.startswith("h"):
                block.add_feature("is_heading", True)
                block.add_feature("heading_level", int(elem.name[1]))
            if elem.name == "li":
                block.add_feature("is_list_item", True)
            if elem.name in {"td", "th"}:
                block.add_feature("epub_table_cell", True)

            stable_key = (
                f"{source_location_id}:spine{spine_index}:beautifulsoup{element_index}"
            )
            block.add_feature("beautifulsoup_stable_key", stable_key)
            blocks.append(block)
            diagnostics_rows.append(
                {
                    "source_location_id": source_location_id,
                    "spine_index": spine_index,
                    "element_index": element_index,
                    "tag_name": elem.name,
                    "stable_key": stable_key,
                    "text": text,
                }
            )
            element_index += 1

        return EpubExtractionResult(
            blocks=blocks,
            diagnostics_rows=diagnostics_rows,
            meta={"backend": self.name, "block_count": len(blocks)},
        )

    def _tag_attr_tokens(self, tag: Tag, key: str) -> list[str]:
        raw = tag.attrs.get(key)
        if raw is None:
            return []
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        tokens: list[str] = []
        for value in values:
            text = str(value).strip().lower()
            if not text:
                continue
            tokens.extend(part for part in text.split() if part)
        return tokens

    def _is_pagebreak_tag(self, tag: Tag) -> bool:
        type_tokens = self._tag_attr_tokens(tag, "epub:type") + self._tag_attr_tokens(tag, "type")
        role_tokens = self._tag_attr_tokens(tag, "role")
        class_tokens = [token.lower() for token in tag.get("class", [])]
        if any("pagebreak" in token for token in type_tokens):
            return True
        if any("doc-pagebreak" in token for token in role_tokens):
            return True
        if any("pagebreak" in token for token in class_tokens):
            return True
        return False

    def _is_table_cell_tag(self, tag: Tag) -> bool:
        return tag.name in {"td", "th"}

    def _is_block_tag(self, tag: Tag) -> bool:
        return tag.name in {
            "p",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "blockquote",
            "td",
            "th",
            "tr",
        }

    def _has_block_children(self, tag: Tag) -> bool:
        for child in tag.children:
            if isinstance(child, Tag) and self._is_block_tag(child):
                return True
        return False

    def _build_table_row_block(
        self,
        row: Tag,
        *,
        spine_index: int,
        source_location_id: str,
    ) -> Block | None:
        cells = [cell for cell in row.find_all(self._is_table_cell_tag, recursive=False)]
        if not cells:
            cells = [cell for cell in row.find_all(self._is_table_cell_tag)]

        cell_text = [
            cleaning.normalize_epub_text(cell.get_text(" ", strip=True))
            for cell in cells
        ]
        cell_text = [value for value in cell_text if value]
        if not cell_text:
            return None

        block = Block(
            text=" ".join(cell_text),
            type=BlockType.TABLE,
            html=str(row),
            font_weight="normal",
        )
        block.add_feature("extraction_backend", self.name)
        block.add_feature("epub_table_row", True)
        block.add_feature("spine_index", spine_index)
        block.add_feature("source_location_id", source_location_id)
        return block


class UnstructuredEpubExtractor:
    name = "unstructured"

    def __init__(
        self,
        *,
        html_parser_version: str = "v1",
        skip_headers_and_footers: bool = False,
        preprocess_mode: str = "br_split_v1",
    ) -> None:
        self._html_parser_version = html_parser_version
        self._skip_headers_and_footers = bool(skip_headers_and_footers)
        self._preprocess_mode = preprocess_mode

    def extract_spine_html(
        self,
        html: str,
        *,
        spine_index: int,
        source_location_id: str,
    ) -> EpubExtractionResult:
        from cookimport.parsing.epub_html_normalize import normalize_epub_html_for_unstructured
        from cookimport.parsing.unstructured_adapter import (
            UnstructuredHtmlOptions,
            partition_html_to_blocks,
        )

        options = UnstructuredHtmlOptions(
            html_parser_version=self._html_parser_version,
            skip_headers_and_footers=self._skip_headers_and_footers,
            preprocess_mode=self._preprocess_mode,
        )
        normalized_html = normalize_epub_html_for_unstructured(html, mode=self._preprocess_mode)
        blocks, diagnostics_rows = partition_html_to_blocks(
            normalized_html,
            spine_index=spine_index,
            source_location_id=source_location_id,
            options=options,
        )
        for block in blocks:
            block.add_feature("extraction_backend", self.name)

        return EpubExtractionResult(
            blocks=blocks,
            diagnostics_rows=diagnostics_rows,
            meta={
                "backend": self.name,
                "block_count": len(blocks),
                "raw_html": html,
                "normalized_html": normalized_html,
                "unstructured_version": _resolve_unstructured_version(),
                "unstructured_html_parser_version": self._html_parser_version,
                "unstructured_skip_headers_footers": self._skip_headers_and_footers,
                "unstructured_preprocess_mode": self._preprocess_mode,
            },
        )


class MarkdownEpubExtractor:
    name = "markdown"

    def extract_spine_html(
        self,
        html: str,
        *,
        spine_index: int,
        source_location_id: str,
    ) -> EpubExtractionResult:
        markdown_text, conversion_meta = _html_to_markdown(html)
        source_path = Path(f"{source_location_id}.epub")
        blocks = markdown_to_blocks(
            markdown_text,
            source_path=source_path,
            source_location_id=source_location_id,
            extraction_backend=self.name,
        )

        diagnostics_rows: list[dict[str, Any]] = []
        for block_index, block in enumerate(blocks):
            block.add_feature("spine_index", spine_index)
            line_start = int(block.features.get("markdown_line_start") or 0)
            line_end = int(block.features.get("markdown_line_end") or line_start)
            stable_key = f"{source_location_id}:spine{spine_index}:md{block_index}"
            block.add_feature("markdown_stable_key", stable_key)

            kind = "paragraph"
            if bool(block.features.get("is_heading")):
                kind = "heading"
            elif bool(block.features.get("is_list_item")):
                kind = "list"

            diagnostics_rows.append(
                {
                    "source_location_id": source_location_id,
                    "spine_index": spine_index,
                    "line_start": line_start,
                    "line_end": line_end,
                    "kind": kind,
                    "text": block.text,
                    "stable_key": stable_key,
                }
            )

        return EpubExtractionResult(
            blocks=blocks,
            diagnostics_rows=diagnostics_rows,
            meta={
                "backend": self.name,
                "block_count": len(blocks),
                "pandoc_used": bool(conversion_meta.get("pandoc_used")),
                "markdown_converter": conversion_meta.get("converter", "markdownify"),
                "markdown_converter_error": conversion_meta.get("pandoc_error"),
                "markdownify_version": _resolve_markdownify_version(),
            },
        )


def _resolve_unstructured_version() -> str:
    try:
        return importlib_metadata.version("unstructured")
    except Exception:
        return "unknown"


def _resolve_markdownify_version() -> str:
    try:
        return importlib_metadata.version("markdownify")
    except Exception:
        return "unknown"


def _html_to_markdown(html: str) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {
        "pandoc_used": False,
        "converter": "markdownify",
        "pandoc_error": None,
    }

    pandoc_path = shutil.which("pandoc")
    if pandoc_path is not None:
        try:
            completed = subprocess.run(
                [pandoc_path, "--from", "html", "--to", "gfm"],
                input=html.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            markdown_text = completed.stdout.decode("utf-8", errors="replace")
            meta["pandoc_used"] = True
            meta["converter"] = "pandoc"
            return markdown_text, meta
        except Exception as exc:  # noqa: BLE001
            meta["pandoc_error"] = str(exc)

    try:
        from markdownify import markdownify as to_markdown
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "EPUB extractor 'markdown' requires the `markdownify` package. "
            "Install project deps (`pip install -e .[dev]`) and retry."
        ) from exc

    markdown_text = to_markdown(html, heading_style="ATX")
    return markdown_text, meta
