from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_DEFAULT_SECTION_KEY = "main"
_DEFAULT_SECTION_NAME = "Main"

_INGREDIENT_SECTION_KEYWORDS = {
    "assembly",
    "batter",
    "brine",
    "coating",
    "crust",
    "dressing",
    "drizzle",
    "filling",
    "frosting",
    "garnish",
    "glaze",
    "ingredients",
    "marinade",
    "rub",
    "sauce",
    "seasoning",
    "stuffing",
    "topping",
}

_INSTRUCTION_SECTION_ALLOWLIST = {
    "assembly",
    "optional",
    "to serve",
}

_INSTRUCTION_VERB_DENYLIST = {
    "add",
    "bake",
    "beat",
    "boil",
    "combine",
    "cook",
    "drain",
    "fold",
    "fry",
    "heat",
    "mix",
    "pour",
    "reduce",
    "roast",
    "saute",
    "season",
    "simmer",
    "stir",
    "whisk",
}

_STOPWORDS = {"a", "an", "for", "the"}

_WORD_RE = re.compile(r"[a-z0-9]+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_LEADING_BULLET_RE = re.compile(r"^\s*[-*•]+\s+")
_LEADING_NUMBER_RE = re.compile(r"^\s*\d+[.)]\s+")
_FOR_PREFIX_RE = re.compile(r"^for(?:\s+the)?\s+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_FOR_PATTERN_RE = re.compile(r"^for(?:\s+the)?\s+[a-z][a-z'/-]*(?:\s+[a-z][a-z'/-]*){0,4}$", re.IGNORECASE)
_COLON_SECTION_RE = re.compile(r"^[a-z][a-z'/-]*(?:\s+[a-z][a-z'/-]*){0,4}:$", re.IGNORECASE)


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
    """Normalize a section display name into a stable matching key."""
    lowered = display_name.strip().rstrip(":").lower()
    lowered = _FOR_PREFIX_RE.sub("", lowered)
    lowered = _PUNCT_RE.sub(" ", lowered)
    tokens = [token for token in _WORD_RE.findall(lowered) if token and token not in _STOPWORDS]
    if not tokens:
        return ""
    return "_".join(tokens)


def is_ingredient_section_header_line(text: str) -> bool:
    """Return True when an ingredient line looks like a component header."""
    stripped = text.strip().rstrip(":")
    if not stripped:
        return False

    if re.match(r"^[A-Z][A-Z\s]{0,20}$", stripped) and not any(c.isdigit() for c in stripped):
        words = stripped.split()
        if len(words) <= 3:
            return True

    if re.match(r"^[Ff]or(?:\s+[Tt]he)?\s+\w+", stripped):
        return True

    if stripped.lower() in _INGREDIENT_SECTION_KEYWORDS:
        return True

    return False


def extract_ingredient_sections(raw_ingredient_lines: list[str]) -> SectionedLines:
    """Extract section headers from raw ingredient lines."""
    return _extract_sections(
        raw_ingredient_lines,
        source="ingredients",
        is_header=is_ingredient_section_header_line,
    )


def extract_instruction_sections(raw_instruction_lines: list[str]) -> SectionedLines:
    """Extract section headers from raw instruction lines using conservative rules."""
    return _extract_sections(
        raw_instruction_lines,
        source="instructions",
        is_header=is_instruction_section_header_line,
    )


def is_instruction_section_header_line(text: str) -> bool:
    """Return True when an instruction line is likely a section heading."""
    stripped = _normalize_display_name(text)
    if not stripped:
        return False

    if len(stripped) > 60:
        return False
    if any(char.isdigit() for char in stripped):
        return False

    lower = stripped.lower()
    has_colon = text.strip().endswith(":")

    if _contains_instruction_verb_phrase(lower):
        return False

    if lower in _INSTRUCTION_SECTION_ALLOWLIST:
        return True
    if _FOR_PATTERN_RE.match(lower):
        return True
    if _COLON_SECTION_RE.match(text.strip()):
        return True

    if has_colon:
        # Allow short title-like headings ending with colon.
        words = lower.split()
        if 1 <= len(words) <= 5 and _looks_title_or_upper(stripped):
            return True

    return False


def _contains_instruction_verb_phrase(lower: str) -> bool:
    if "," in lower:
        for verb in _INSTRUCTION_VERB_DENYLIST:
            if re.search(rf"\b{re.escape(verb)}\b", lower):
                return True
    if re.search(r"[.!?]", lower):
        return True
    return False


def _looks_title_or_upper(text: str) -> bool:
    words = [word for word in text.split() if word]
    if not words:
        return False

    alpha_words = [word for word in words if any(char.isalpha() for char in word)]
    if not alpha_words:
        return False

    if all(word.isupper() for word in alpha_words):
        return True

    title_like = 0
    for word in alpha_words:
        first_alpha = next((char for char in word if char.isalpha()), "")
        if first_alpha and first_alpha.isupper():
            title_like += 1
    return title_like >= max(1, len(alpha_words) - 1)


def _extract_sections(
    raw_lines: list[str],
    *,
    source: str,
    is_header: Callable[[str], bool],
) -> SectionedLines:
    lines_no_headers: list[str] = []
    section_key_by_line: list[str] = []
    section_display_by_key: dict[str, str] = {_DEFAULT_SECTION_KEY: _DEFAULT_SECTION_NAME}
    header_hits: list[SectionHeaderHit] = []

    active_key = _DEFAULT_SECTION_KEY
    fallback_counter = 0

    for original_index, raw_line in enumerate(raw_lines):
        line = str(raw_line).strip()
        if not line:
            continue

        if is_header(line):
            display_name = _normalize_display_name(line)
            key = normalize_section_key(display_name)
            if not key:
                fallback_counter += 1
                key = f"section_{fallback_counter}"
            active_key = key
            section_display_by_key.setdefault(key, display_name)
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
        section_key_by_line.append(active_key)

    return SectionedLines(
        lines_no_headers=lines_no_headers,
        section_key_by_line=section_key_by_line,
        section_display_by_key=section_display_by_key,
        header_hits=header_hits,
    )


def _normalize_display_name(value: str) -> str:
    cleaned = _LEADING_BULLET_RE.sub("", value)
    cleaned = _LEADING_NUMBER_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    cleaned = cleaned.rstrip(":").strip()
    return _MULTI_SPACE_RE.sub(" ", cleaned)


__all__ = [
    "SectionHeaderHit",
    "SectionedLines",
    "extract_ingredient_sections",
    "extract_instruction_sections",
    "is_ingredient_section_header_line",
    "is_instruction_section_header_line",
    "normalize_section_key",
]
