from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

_MULTISPACE_SPLIT_RE = re.compile(r"\s{2,}")
_MARKDOWN_DIVIDER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_REFERENCE_TABLE_CAPTION_RE = re.compile(
    r"\b(conversion|equivalenc|temperature|doneness|weight|weights|volume|mass)\b",
    re.IGNORECASE,
)
_REFERENCE_TABLE_HEADER_PREFIX_RE = re.compile(
    r"^\s*(?P<header_a>[A-Za-z%/°.]+)\s+(?P<header_b>[A-Za-z%/°.]+)\s+(?P<body>.+)$"
)
_REFERENCE_VALUE_PAIR_RE = re.compile(
    r"(?P<left>-?\d+(?:\.\d+)?(?:/\d+)?(?:\s*\([^)]{1,80}\))?)\s+"
    r"(?P<right>-?\d+(?:\.\d+)?)"
)
_WHITESPACE_RE = re.compile(r"\s+")


class ExtractedTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    caption: str | None = None
    start_block_index: int
    end_block_index: int
    headers: list[str] | None = None
    rows: list[list[str]] = Field(default_factory=list)
    row_block_indices: list[int] = Field(default_factory=list)
    markdown: str
    row_texts: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _CandidateRow:
    sequence_pos: int
    block_index: int
    cells: list[str]
    separator: bool
    parse_mode: str


def detect_tables_from_non_recipe_blocks(
    non_recipe_blocks: Sequence[Mapping[str, Any]],
    *,
    source_hash: str = "unknown",
    min_rows: int = 3,
    caption_lookback: int = 3,
) -> list[ExtractedTable]:
    if not non_recipe_blocks:
        return []

    normalized_blocks: list[dict[str, Any]] = [
        dict(block) for block in non_recipe_blocks if isinstance(block, Mapping)
    ]
    if not normalized_blocks:
        return []

    candidates = _find_candidate_rows(normalized_blocks)
    tables: list[ExtractedTable] = []
    index = 0
    while index < len(candidates):
        run: list[_CandidateRow] = [candidates[index]]
        scan = index + 1
        while scan < len(candidates):
            previous = run[-1]
            current = candidates[scan]
            if current.sequence_pos != previous.sequence_pos + 1:
                break
            run.append(current)
            scan += 1

        for segment in _split_run_by_column_consistency(run):
            if not _is_valid_table_segment(segment, min_rows=min_rows):
                continue
            table = _build_table(
                segment,
                normalized_blocks=normalized_blocks,
                source_hash=source_hash,
                caption_lookback=caption_lookback,
            )
            if table is not None:
                tables.append(table)

        index = scan

    occupied_block_indices = {
        block_index
        for table in tables
        for block_index in table.row_block_indices
    }
    tables.extend(
        _salvage_flattened_reference_tables(
            normalized_blocks,
            source_hash=source_hash,
            caption_lookback=caption_lookback,
            occupied_block_indices=occupied_block_indices,
        )
    )
    return tables


def annotate_non_recipe_blocks_with_tables(
    non_recipe_blocks: list[dict[str, Any]],
    tables: Sequence[ExtractedTable],
) -> None:
    if not non_recipe_blocks or not tables:
        return

    block_by_index: dict[int, dict[str, Any]] = {}
    for block in non_recipe_blocks:
        block_index = _coerce_int(block.get("index"))
        if block_index is None:
            continue
        block_by_index[block_index] = block

    for table in tables:
        for row_index, block_index in enumerate(table.row_block_indices):
            block = block_by_index.get(block_index)
            if block is None:
                continue
            features = block.get("features")
            if not isinstance(features, dict):
                features = {}

            features["table_id"] = table.table_id
            features["table_row_index"] = row_index
            features["table_column_count"] = len(table.rows[row_index]) if row_index < len(table.rows) else 0
            if table.caption:
                features["table_caption"] = table.caption

            block["features"] = features
            block["table_id"] = table.table_id
            block["table_row_index"] = row_index
            block["table_hint"] = {
                "table_id": table.table_id,
                "caption": table.caption,
                "markdown": table.markdown,
                "row_index_in_table": row_index,
            }


def extract_and_annotate_tables(
    non_recipe_blocks: list[dict[str, Any]],
    *,
    source_hash: str = "unknown",
) -> list[ExtractedTable]:
    tables = detect_tables_from_non_recipe_blocks(
        non_recipe_blocks,
        source_hash=source_hash,
    )
    annotate_non_recipe_blocks_with_tables(non_recipe_blocks, tables)
    return tables


def _find_candidate_rows(normalized_blocks: Sequence[dict[str, Any]]) -> list[_CandidateRow]:
    rows: list[_CandidateRow] = []
    for sequence_pos, block in enumerate(normalized_blocks):
        parsed = _parse_structured_epub_row_block(block)
        if parsed is None:
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            parsed = _parse_row(text)
        if parsed is None:
            continue
        block_index = _coerce_int(block.get("index"))
        if block_index is None:
            block_index = sequence_pos
        rows.append(
            _CandidateRow(
                sequence_pos=sequence_pos,
                block_index=block_index,
                cells=parsed["cells"],
                separator=parsed["separator"],
                parse_mode=parsed["parse_mode"],
            )
        )
    return rows


def _parse_structured_epub_row_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    features = block.get("features")
    if not isinstance(features, Mapping):
        return None
    if not bool(features.get("epub_table_row")):
        return None
    raw_cells = features.get("epub_table_cells")
    if not isinstance(raw_cells, Sequence) or isinstance(raw_cells, (str, bytes)):
        return None
    cells = [_normalize_cell(cell) for cell in raw_cells]
    if len(cells) < 2 or not any(cells):
        return None
    return {
        "cells": cells,
        "separator": False,
        "parse_mode": "epub_structured",
    }


def _parse_row(text: str) -> dict[str, Any] | None:
    if "\n" in text:
        return None

    parsed_pipe = _parse_pipe_row(text)
    if parsed_pipe is not None:
        return parsed_pipe

    parsed_tab = _parse_delimited_row(text, "\t", parse_mode="tab")
    if parsed_tab is not None:
        return parsed_tab

    parsed_space = _parse_multispace_row(text)
    if parsed_space is not None:
        return parsed_space

    return None


def _parse_pipe_row(text: str) -> dict[str, Any] | None:
    if "|" not in text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [_normalize_cell(cell) for cell in stripped.split("|")]
    cells = _drop_empty_edges(cells)
    if len(cells) < 2:
        return None
    if not any(cell for cell in cells):
        return None
    separator = all(_is_markdown_divider_cell(cell) for cell in cells if cell)
    return {
        "cells": cells,
        "separator": separator,
        "parse_mode": "pipe",
    }


def _parse_delimited_row(text: str, delimiter: str, *, parse_mode: str) -> dict[str, Any] | None:
    if delimiter not in text:
        return None
    cells = [_normalize_cell(cell) for cell in text.split(delimiter)]
    cells = _drop_empty_edges(cells)
    if len(cells) < 2:
        return None
    if not any(cell for cell in cells):
        return None
    return {
        "cells": cells,
        "separator": False,
        "parse_mode": parse_mode,
    }


def _parse_multispace_row(text: str) -> dict[str, Any] | None:
    if "  " not in text:
        return None
    cells = [_normalize_cell(cell) for cell in _MULTISPACE_SPLIT_RE.split(text)]
    cells = [cell for cell in cells if cell]
    if len(cells) < 2:
        return None
    long_cells = [cell for cell in cells if len(cell) > 80]
    if long_cells:
        return None
    return {
        "cells": cells,
        "separator": False,
        "parse_mode": "multispace",
    }


def _drop_empty_edges(cells: list[str]) -> list[str]:
    trimmed = list(cells)
    while trimmed and not trimmed[0]:
        trimmed = trimmed[1:]
    while trimmed and not trimmed[-1]:
        trimmed = trimmed[:-1]
    return trimmed


def _is_markdown_divider_cell(value: str) -> bool:
    return bool(_MARKDOWN_DIVIDER_CELL_RE.match(value.strip()))


def _normalize_cell(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _split_run_by_column_consistency(run: Sequence[_CandidateRow]) -> list[list[_CandidateRow]]:
    if not run:
        return []
    segments: list[list[_CandidateRow]] = []
    current: list[_CandidateRow] = []
    counts: Counter[int] = Counter()
    for row in run:
        column_count = len(row.cells)
        if not current:
            current.append(row)
            counts[column_count] += 1
            continue
        dominant = _dominant_column_count(counts)
        if abs(column_count - dominant) > 1:
            segments.append(current)
            current = [row]
            counts = Counter({column_count: 1})
            continue
        current.append(row)
        counts[column_count] += 1
    if current:
        segments.append(current)
    return segments


def _dominant_column_count(counts: Counter[int]) -> int:
    if not counts:
        return 0
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _is_valid_table_segment(segment: Sequence[_CandidateRow], *, min_rows: int) -> bool:
    if not segment:
        return False
    if max(len(row.cells) for row in segment) < 2:
        return False
    has_divider = any(row.separator for row in segment)
    if len(segment) >= min_rows:
        return True
    return len(segment) >= 2 and has_divider


def _build_table(
    segment: Sequence[_CandidateRow],
    *,
    normalized_blocks: Sequence[dict[str, Any]],
    source_hash: str,
    caption_lookback: int,
) -> ExtractedTable | None:
    if not segment:
        return None

    target_columns = _dominant_column_count(Counter(len(row.cells) for row in segment))
    if target_columns < 2:
        return None
    normalized_segment = [_normalize_row_width(row, target_columns) for row in segment]

    headers, body_rows, notes = _infer_headers(normalized_segment)
    if not body_rows:
        return None

    start_index = normalized_segment[0].block_index
    end_index = normalized_segment[-1].block_index
    caption = _infer_caption(
        normalized_blocks,
        start_pos=normalized_segment[0].sequence_pos,
        lookback=caption_lookback,
    )
    markdown = _render_markdown(headers=headers, rows=body_rows)
    row_texts = _render_row_texts(headers=headers, rows=body_rows)
    table_id = _stable_table_id(source_hash=source_hash, start=start_index, end=end_index)
    confidence = _score_table(
        rows=normalized_segment,
        headers=headers,
    )
    notes.append(f"parse_modes={','.join(sorted({row.parse_mode for row in normalized_segment}))}")

    return ExtractedTable(
        table_id=table_id,
        caption=caption,
        start_block_index=start_index,
        end_block_index=end_index,
        headers=headers,
        rows=body_rows,
        row_block_indices=[row.block_index for row in normalized_segment if not row.separator],
        markdown=markdown,
        row_texts=row_texts,
        confidence=confidence,
        notes=notes,
    )


def _normalize_row_width(row: _CandidateRow, width: int) -> _CandidateRow:
    cells = list(row.cells)
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    elif len(cells) > width:
        overflow = " ".join(cell for cell in cells[width - 1 :] if cell).strip()
        cells = cells[: width - 1] + [overflow]
    return _CandidateRow(
        sequence_pos=row.sequence_pos,
        block_index=row.block_index,
        cells=cells,
        separator=row.separator,
        parse_mode=row.parse_mode,
    )


def _infer_headers(rows: Sequence[_CandidateRow]) -> tuple[list[str] | None, list[list[str]], list[str]]:
    notes: list[str] = []
    if not rows:
        return None, [], notes

    header_cells: list[str] | None = None
    data_rows: list[list[str]]

    if len(rows) >= 2 and not rows[0].separator and rows[1].separator:
        header_cells = rows[0].cells
        data_rows = [row.cells for row in rows[2:] if not row.separator]
        notes.append("headers=inferred_from_markdown_divider")
    elif len(rows) >= 2 and _looks_like_header_row(rows[0].cells, rows[1].cells):
        header_cells = rows[0].cells
        data_rows = [row.cells for row in rows[1:] if not row.separator]
        notes.append("headers=inferred_from_first_row")
    else:
        data_rows = [row.cells for row in rows if not row.separator]

    if header_cells is not None:
        header_cells = [_fallback_header(cell, idx) for idx, cell in enumerate(header_cells)]
    return header_cells, data_rows, notes


def _looks_like_header_row(first_row: Sequence[str], second_row: Sequence[str]) -> bool:
    if not first_row or not second_row:
        return False
    if any(_contains_digits(cell) for cell in first_row):
        return False
    if any(_contains_digits(cell) for cell in second_row):
        return True
    short_header_cells = sum(1 for cell in first_row if 0 < len(cell) <= 24)
    return short_header_cells >= max(1, len(first_row) // 2)


def _contains_digits(value: str) -> bool:
    return any(character.isdigit() for character in value)


def _fallback_header(value: str, column_index: int) -> str:
    rendered = value.strip()
    if rendered:
        return rendered
    return f"Column {column_index + 1}"


def _infer_caption(
    blocks: Sequence[dict[str, Any]],
    *,
    start_pos: int,
    lookback: int,
) -> str | None:
    if start_pos <= 0:
        return None
    floor = max(0, start_pos - max(1, lookback))
    for sequence_pos in range(start_pos - 1, floor - 1, -1):
        candidate = blocks[sequence_pos]
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue
        if _parse_row(text) is not None:
            continue
        features = candidate.get("features")
        if _looks_like_caption(text, features):
            return text
    return None


def _looks_like_caption(text: str, features: Any) -> bool:
    if isinstance(features, Mapping) and bool(features.get("is_header_likely")):
        return True
    if len(text) > 90:
        return False
    if text.endswith(":"):
        return True
    if text.isupper():
        return True
    return text.istitle() and len(text.split()) <= 10


def _render_markdown(*, headers: list[str] | None, rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    if width <= 0:
        return ""

    effective_headers = headers or [f"Column {index + 1}" for index in range(width)]
    if len(effective_headers) < width:
        effective_headers = list(effective_headers) + [
            f"Column {index + 1}" for index in range(len(effective_headers), width)
        ]
    elif len(effective_headers) > width:
        effective_headers = list(effective_headers[:width])

    lines = [
        _markdown_row(effective_headers),
        _markdown_row(["---"] * width),
    ]
    for row in rows:
        normalized = list(row)
        if len(normalized) < width:
            normalized.extend([""] * (width - len(normalized)))
        elif len(normalized) > width:
            normalized = normalized[:width]
        lines.append(_markdown_row(normalized))
    return "\n".join(lines)


def _markdown_row(cells: Sequence[str]) -> str:
    escaped = [str(cell).replace("|", r"\|").strip() for cell in cells]
    return "| " + " | ".join(escaped) + " |"


def _render_row_texts(*, headers: list[str] | None, rows: Sequence[Sequence[str]]) -> list[str]:
    rendered: list[str] = []
    for row in rows:
        if headers:
            pairs: list[str] = []
            for index, cell in enumerate(row):
                header = headers[index] if index < len(headers) else f"Column {index + 1}"
                cell_value = str(cell).strip()
                if not cell_value:
                    continue
                pairs.append(f"{header}: {cell_value}")
            text = " | ".join(pairs).strip()
        else:
            text = " | ".join(str(cell).strip() for cell in row if str(cell).strip()).strip()
        if text:
            rendered.append(text)
    return rendered


def _stable_table_id(*, source_hash: str, start: int, end: int) -> str:
    seed = f"{source_hash}:{start}:{end}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"tbl_{start}_{end}_{digest}"


def _score_table(*, rows: Sequence[_CandidateRow], headers: list[str] | None) -> float:
    score = 0.55
    if headers:
        score += 0.1
    if any(row.separator for row in rows):
        score += 0.1
    content_rows = sum(1 for row in rows if not row.separator)
    score += min(0.25, content_rows * 0.04)
    if len({len(row.cells) for row in rows}) > 2:
        score -= 0.1
    return max(0.05, min(0.99, round(score, 3)))


def _salvage_flattened_reference_tables(
    normalized_blocks: Sequence[dict[str, Any]],
    *,
    source_hash: str,
    caption_lookback: int,
    occupied_block_indices: set[int],
) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    for sequence_pos, block in enumerate(normalized_blocks):
        block_index = _coerce_int(block.get("index"))
        if block_index is None or block_index in occupied_block_indices:
            continue
        text = str(block.get("text") or "").strip()
        if not text or "\n" in text:
            continue
        caption = _infer_caption(
            normalized_blocks,
            start_pos=sequence_pos,
            lookback=caption_lookback,
        )
        if not caption or not _REFERENCE_TABLE_CAPTION_RE.search(caption):
            continue
        parsed = _parse_flattened_reference_table(text)
        if parsed is None:
            continue
        markdown = _render_markdown(headers=parsed["headers"], rows=parsed["rows"])
        row_texts = _render_row_texts(headers=parsed["headers"], rows=parsed["rows"])
        tables.append(
            ExtractedTable(
                table_id=_stable_table_id(
                    source_hash=source_hash,
                    start=block_index,
                    end=block_index,
                ),
                caption=caption,
                start_block_index=block_index,
                end_block_index=block_index,
                headers=parsed["headers"],
                rows=parsed["rows"],
                row_block_indices=[block_index],
                markdown=markdown,
                row_texts=row_texts,
                confidence=0.43,
                notes=[
                    "headers=salvaged_from_flattened_reference",
                    "parse_modes=flattened_reference_salvage",
                    "row_block_indices=single_source_block",
                ],
            )
        )
    return tables


def _parse_flattened_reference_table(text: str) -> dict[str, list[list[str]] | list[str]] | None:
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    header_match = _REFERENCE_TABLE_HEADER_PREFIX_RE.match(normalized)
    if header_match is None:
        return None

    headers = [
        _normalize_cell(header_match.group("header_a")),
        _normalize_cell(header_match.group("header_b")),
    ]
    if any(_contains_digits(header) for header in headers):
        return None

    body = header_match.group("body").strip()
    rows: list[list[str]] = []
    position = 0
    while position < len(body):
        match = _REFERENCE_VALUE_PAIR_RE.match(body, position)
        if match is None:
            return None
        rows.append(
            [
                _normalize_cell(match.group("left")),
                _normalize_cell(match.group("right")),
            ]
        )
        position = match.end()
        while position < len(body) and body[position].isspace():
            position += 1

    if len(rows) < 3:
        return None
    return {
        "headers": headers,
        "rows": rows,
    }


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
