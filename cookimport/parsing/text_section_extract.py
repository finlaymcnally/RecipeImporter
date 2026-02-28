from __future__ import annotations

import re
from typing import Callable

from cookimport.parsing import cleaning
from cookimport.parsing.section_detector import extract_structured_sections_from_lines

LineNormalizer = Callable[[str], str]


def _default_ingredient_line_normalizer(line: str) -> str:
    return re.sub(r"^\s*[-*]+\s+", "", line).strip()


def _default_instruction_line_normalizer(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*]+\s+", "", line)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned)
    return cleaned.strip()


def extract_sections_from_text_blob(
    text: str,
    *,
    ingredient_line_normalizer: LineNormalizer | None = None,
    instruction_line_normalizer: LineNormalizer | None = None,
) -> dict[str, list[str]]:
    """Return ingredient/instruction/note lines when section headers are detected.

    If no recognized section headers are present, returns an empty mapping so callers
    can keep legacy fallback behavior.
    """

    normalized = cleaning.normalize_text(str(text))
    lines = normalized.split("\n")
    structured_sections, found_any_header = extract_structured_sections_from_lines(lines)
    if not found_any_header:
        return {}

    normalize_ingredient = (
        ingredient_line_normalizer or _default_ingredient_line_normalizer
    )
    normalize_instruction = (
        instruction_line_normalizer or _default_instruction_line_normalizer
    )

    sections: dict[str, list[str]] = {"ingredients": [], "instructions": [], "notes": []}
    for line in structured_sections.get("ingredients", []):
        normalized_line = normalize_ingredient(line)
        if normalized_line:
            sections["ingredients"].append(normalized_line)
    for line in structured_sections.get("instructions", []):
        normalized_line = normalize_instruction(line)
        if normalized_line:
            sections["instructions"].append(normalized_line)
    for line in structured_sections.get("notes", []):
        stripped = str(line).strip()
        if stripped:
            sections["notes"].append(stripped)
    return sections

