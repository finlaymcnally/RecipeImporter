from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from cookimport.parsing.section_detector import (
    SectionKind,
    detect_sections_from_lines,
    normalize_section_key as _normalize_section_key,
)

_DEFAULT_SECTION_KEY = "main"
_DEFAULT_SECTION_NAME = "Main"


@dataclass(frozen=True)
class SectionHeaderHit:
    source: str
    original_index: int
    raw_line: str
    display_name: str
    key: str


@dataclass(frozen=True)
class SectionedLines:
    lines_no_headers: list[str]
    section_key_by_line: list[str]
    section_display_by_key: dict[str, str]
    header_hits: list[SectionHeaderHit]


def normalize_section_key(display_name: str) -> str:
    return _normalize_section_key(display_name)


def is_ingredient_section_header_line(text: str) -> bool:
    detected = detect_sections_from_lines(
        [text],
        preferred_kind=SectionKind.INGREDIENTS,
    )
    return any(span.header_index == 0 for span in detected.spans)


def extract_ingredient_sections(raw_ingredient_lines: list[str]) -> SectionedLines:
    return _extract_sections(
        raw_ingredient_lines,
        source="ingredients",
        is_header=is_ingredient_section_header_line,
        preferred_kind=SectionKind.INGREDIENTS,
    )


def extract_instruction_sections(raw_instruction_lines: list[str]) -> SectionedLines:
    return _extract_sections(
        raw_instruction_lines,
        source="instructions",
        is_header=is_instruction_section_header_line,
        preferred_kind=SectionKind.INSTRUCTIONS,
    )


def is_instruction_section_header_line(text: str) -> bool:
    detected = detect_sections_from_lines(
        [text],
        preferred_kind=SectionKind.INSTRUCTIONS,
    )
    return any(span.header_index == 0 for span in detected.spans)


def _extract_sections(
    raw_lines: list[str],
    *,
    source: str,
    is_header: Callable[[str], bool],
    preferred_kind: SectionKind,
) -> SectionedLines:
    _ = is_header
    detected = detect_sections_from_lines(
        raw_lines,
        preferred_kind=preferred_kind,
    )

    line_key_by_index: dict[int, str] = {}
    header_by_index: dict[int, tuple[str, str]] = {}
    section_display_by_key: dict[str, str] = {
        _DEFAULT_SECTION_KEY: _DEFAULT_SECTION_NAME,
    }

    for span in detected.spans:
        section_display_by_key.setdefault(span.key, span.name)
        if span.header_index is not None and span.header_index not in header_by_index:
            header_by_index[span.header_index] = (span.key, span.name)
        if span.end_index <= span.start_index:
            continue
        for index in range(span.start_index, span.end_index):
            line_key_by_index[index] = span.key

    lines_no_headers: list[str] = []
    section_key_by_line: list[str] = []
    header_hits: list[SectionHeaderHit] = []

    for original_index, raw_line in enumerate(raw_lines):
        line = str(raw_line).strip()
        if not line:
            continue
        if original_index in header_by_index:
            key, display_name = header_by_index[original_index]
            header_hits.append(
                SectionHeaderHit(
                    source=source,
                    original_index=original_index,
                    raw_line=line,
                    display_name=display_name,
                    key=key,
                )
            )
            continue
        lines_no_headers.append(line)
        section_key_by_line.append(
            line_key_by_index.get(original_index, _DEFAULT_SECTION_KEY)
        )

    return SectionedLines(
        lines_no_headers=lines_no_headers,
        section_key_by_line=section_key_by_line,
        section_display_by_key=section_display_by_key,
        header_hits=header_hits,
    )


__all__ = [
    "SectionHeaderHit",
    "SectionedLines",
    "extract_ingredient_sections",
    "extract_instruction_sections",
    "is_ingredient_section_header_line",
    "is_instruction_section_header_line",
    "normalize_section_key",
]
