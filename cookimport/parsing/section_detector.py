from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from cookimport.core.blocks import Block
from cookimport.core.models import ParsingOverrides
from cookimport.parsing import signals

_DEFAULT_SECTION_KEY = "main"
_DEFAULT_SECTION_NAME = "Main"
_NOTES_SECTION_KEY = "notes"
_NOTES_SECTION_NAME = "Notes"

_STOPWORDS = {"a", "an", "for", "the"}
_WORD_RE = re.compile(r"[a-z0-9]+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_FOR_PREFIX_RE = re.compile(r"^for(?:\s+the)?\s+", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"\s+")
_LEADING_BULLET_RE = re.compile(r"^\s*[-*•]+\s+")
_LEADING_NUMBER_RE = re.compile(r"^\s*\d+[.)]\s+")
_FOR_PATTERN_RE = re.compile(
    r"^for(?:\s+the)?\s+[a-z][a-z'/-]*(?:\s+[a-z][a-z'/-]*){0,4}:?$",
    re.IGNORECASE,
)
_COLON_SECTION_RE = re.compile(
    r"^[a-z][a-z'/-]*(?:\s+[a-z][a-z'/-]*){0,4}:$",
    re.IGNORECASE,
)
_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|crush|cook|bake|roast|fry|grill|"
    r"blanch|season|serve|add|melt|place|put|pour|combine|fold|return|remove|drain|"
    r"peel|chop|slice|cut|toss|leave|cool|refrigerate|strain|set|beat|whip|simmer|"
    r"boil|reduce|cover|unwrap|sear|saute)\b",
    re.IGNORECASE,
)
_SECTION_HEADER_TOP_LEVEL_RE = re.compile(
    r"^\s*(ingredients?|instructions?|directions?|method|steps?|preparation|notes?|tips?)\s*:?\s*$",
    re.IGNORECASE,
)
_INGREDIENT_HEADER_ALIASES = {"ingredient", "ingredients"}
_INSTRUCTION_HEADER_ALIASES = {
    "instruction",
    "instructions",
    "direction",
    "directions",
    "method",
    "step",
    "steps",
    "preparation",
}
_NOTES_HEADER_ALIASES = {"note", "notes", "tip", "tips"}
_INSTRUCTION_SECTION_ALLOWLIST = {"assembly", "optional", "to serve"}
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
_FOR_COMPONENT_BANNED_WORDS = {
    "best",
    "better",
    "optimal",
    "this",
    "that",
    "each",
    "every",
    "more",
    "about",
    "details",
    "results",
}


class SectionKind(str, Enum):
    INGREDIENTS = "ingredients"
    INSTRUCTIONS = "instructions"
    NOTES = "notes"
    OTHER = "other"


@dataclass(frozen=True)
class SectionSpan:
    kind: SectionKind
    key: str
    name: str
    start_index: int
    end_index: int
    header_index: int | None


@dataclass(frozen=True)
class DetectedSections:
    spans: list[SectionSpan]


@dataclass(frozen=True)
class _Entry:
    index: int
    text: str
    features: dict[str, Any] | None


@dataclass(frozen=True)
class _HeaderMatch:
    kind: SectionKind
    key: str
    name: str
    is_top_level: bool


@dataclass(frozen=True)
class _ActiveState:
    kind: SectionKind
    key: str
    name: str
    header_index: int | None


def normalize_section_key(display_name: str) -> str:
    lowered = display_name.strip().rstrip(":").lower()
    lowered = _FOR_PREFIX_RE.sub("", lowered)
    lowered = _PUNCT_RE.sub(" ", lowered)
    tokens = [
        token
        for token in _WORD_RE.findall(lowered)
        if token and token not in _STOPWORDS
    ]
    if not tokens:
        return ""
    return "_".join(tokens)


def detect_sections_from_lines(
    lines: list[str],
    *,
    overrides: ParsingOverrides | None = None,
    preferred_kind: SectionKind | None = None,
) -> DetectedSections:
    entries: list[_Entry] = []
    for index, raw_line in enumerate(lines):
        text = str(raw_line).strip()
        if not text:
            continue
        entries.append(_Entry(index=index, text=text, features=None))
    return _detect_from_entries(
        entries=entries,
        overrides=overrides,
        preferred_kind=preferred_kind,
    )


def detect_sections_from_blocks(
    blocks: list[Block],
    *,
    overrides: ParsingOverrides | None = None,
    preferred_kind: SectionKind | None = None,
) -> DetectedSections:
    entries: list[_Entry] = []
    for index, block in enumerate(blocks):
        text = str(block.text).strip()
        if not text:
            continue
        block_features = dict(block.features) if isinstance(block.features, dict) else None
        entries.append(_Entry(index=index, text=text, features=block_features))
    return _detect_from_entries(
        entries=entries,
        overrides=overrides,
        preferred_kind=preferred_kind,
    )


def extract_structured_sections_from_lines(
    lines: list[str],
    *,
    overrides: ParsingOverrides | None = None,
) -> tuple[dict[str, list[str]], bool]:
    entries: list[_Entry] = []
    for index, raw_line in enumerate(lines):
        text = str(raw_line).strip()
        if not text:
            continue
        entries.append(_Entry(index=index, text=text, features=None))
    if not entries:
        return ({}, False)

    detected = _detect_from_entries(
        entries=entries,
        overrides=overrides,
        preferred_kind=None,
    )
    line_to_span = _line_index_to_span(detected)
    header_to_span: dict[int, SectionSpan] = {}
    for span in detected.spans:
        if span.header_index is None:
            continue
        if span.header_index in header_to_span:
            continue
        header_to_span[span.header_index] = span
    top_level_headers = _top_level_header_indices(entries)
    if not top_level_headers:
        return ({}, False)

    sections = {"ingredients": [], "instructions": [], "notes": []}
    for entry in entries:
        if entry.index in top_level_headers:
            continue
        header_span = header_to_span.get(entry.index)
        if header_span is not None and header_span.key != _DEFAULT_SECTION_KEY:
            if header_span.kind == SectionKind.INGREDIENTS:
                sections["ingredients"].append(header_span.name)
            elif header_span.kind == SectionKind.INSTRUCTIONS:
                sections["instructions"].append(header_span.name)
            elif header_span.kind == SectionKind.NOTES:
                sections["notes"].append(header_span.name)
            continue
        span = line_to_span.get(entry.index)
        if span is None:
            continue
        if span.kind == SectionKind.INGREDIENTS:
            sections["ingredients"].append(entry.text)
        elif span.kind == SectionKind.INSTRUCTIONS:
            sections["instructions"].append(entry.text)
        elif span.kind == SectionKind.NOTES:
            sections["notes"].append(entry.text)
    return (sections, True)


def _detect_from_entries(
    *,
    entries: Sequence[_Entry],
    overrides: ParsingOverrides | None,
    preferred_kind: SectionKind | None,
) -> DetectedSections:
    if not entries:
        return DetectedSections(spans=[])

    default_kind = preferred_kind or SectionKind.OTHER
    active = _ActiveState(
        kind=default_kind,
        key=_default_key_for_kind(default_kind),
        name=_default_name_for_kind(default_kind),
        header_index=None,
    )
    pending_header: _ActiveState | None = None
    spans: list[SectionSpan] = []

    span_start: int | None = None
    span_kind: SectionKind | None = None
    span_key = _DEFAULT_SECTION_KEY
    span_name = _DEFAULT_SECTION_NAME
    span_header_index: int | None = None
    previous_end = entries[0].index

    def flush_span(next_start: int) -> None:
        nonlocal span_start, span_kind, span_key, span_name, span_header_index
        if span_start is None or span_kind is None:
            return
        if next_start <= span_start:
            return
        spans.append(
            SectionSpan(
                kind=span_kind,
                key=span_key,
                name=span_name,
                start_index=span_start,
                end_index=next_start,
                header_index=span_header_index,
            )
        )
        span_start = None
        span_kind = None
        span_key = _DEFAULT_SECTION_KEY
        span_name = _DEFAULT_SECTION_NAME
        span_header_index = None

    def append_empty_header_span(state: _ActiveState) -> None:
        header_index = state.header_index
        if header_index is None:
            return
        spans.append(
            SectionSpan(
                kind=state.kind,
                key=state.key,
                name=state.name,
                start_index=header_index,
                end_index=header_index,
                header_index=header_index,
            )
        )

    for position, entry in enumerate(entries):
        previous_end = max(previous_end, entry.index + 1)
        header_match = _classify_header(entry.text)
        if header_match is not None:
            flush_span(entry.index)
            if pending_header is not None:
                append_empty_header_span(pending_header)

            if header_match.is_top_level:
                next_kind = header_match.kind
            else:
                next_kind = _infer_component_kind(
                    entries=entries,
                    position=position,
                    active_kind=active.kind,
                    preferred_kind=preferred_kind,
                    overrides=overrides,
                )
            next_key = (
                header_match.key
                if header_match.key
                else _default_key_for_kind(next_kind)
            )
            next_name = (
                header_match.name
                if next_key != _default_key_for_kind(next_kind)
                else _default_name_for_kind(next_kind)
            )
            active = _ActiveState(
                kind=next_kind,
                key=next_key,
                name=next_name,
                header_index=entry.index,
            )
            pending_header = active
            continue

        if pending_header is not None:
            active = pending_header
            pending_header = None

        line_kind = active.kind
        line_key = active.key
        line_name = active.name
        line_header_index = active.header_index

        inferred_kind = _infer_kind_from_entry(entry, overrides=overrides)
        if line_kind == SectionKind.OTHER and inferred_kind != SectionKind.OTHER:
            line_kind = inferred_kind
            line_key = _default_key_for_kind(line_kind)
            line_name = _default_name_for_kind(line_kind)
            line_header_index = None
            active = _ActiveState(
                kind=line_kind,
                key=line_key,
                name=line_name,
                header_index=None,
            )

        if span_start is None:
            span_start = entry.index
            span_kind = line_kind
            span_key = line_key
            span_name = line_name
            span_header_index = line_header_index
            continue

        if (
            span_kind != line_kind
            or span_key != line_key
            or span_name != line_name
            or span_header_index != line_header_index
        ):
            flush_span(entry.index)
            span_start = entry.index
            span_kind = line_kind
            span_key = line_key
            span_name = line_name
            span_header_index = line_header_index

    flush_span(previous_end)
    if pending_header is not None:
        append_empty_header_span(pending_header)

    return DetectedSections(spans=spans)


def _line_index_to_span(detected: DetectedSections) -> dict[int, SectionSpan]:
    payload: dict[int, SectionSpan] = {}
    for span in detected.spans:
        if span.end_index <= span.start_index:
            continue
        for line_index in range(span.start_index, span.end_index):
            payload[line_index] = span
    return payload


def _top_level_header_indices(entries: Sequence[_Entry]) -> set[int]:
    indices: set[int] = set()
    for entry in entries:
        match = _classify_header(entry.text)
        if match is None:
            continue
        if match.is_top_level:
            indices.add(entry.index)
    return indices


def _classify_header(text: str) -> _HeaderMatch | None:
    cleaned = _normalize_display_name(text)
    if not cleaned:
        return None

    top_level_match = _SECTION_HEADER_TOP_LEVEL_RE.match(cleaned)
    if top_level_match:
        token = top_level_match.group(1).strip().lower().rstrip(":")
        if token in _INGREDIENT_HEADER_ALIASES:
            return _HeaderMatch(
                kind=SectionKind.INGREDIENTS,
                key=_DEFAULT_SECTION_KEY,
                name=_DEFAULT_SECTION_NAME,
                is_top_level=True,
            )
        if token in _INSTRUCTION_HEADER_ALIASES:
            return _HeaderMatch(
                kind=SectionKind.INSTRUCTIONS,
                key=_DEFAULT_SECTION_KEY,
                name=_DEFAULT_SECTION_NAME,
                is_top_level=True,
            )
        if token in _NOTES_HEADER_ALIASES:
            return _HeaderMatch(
                kind=SectionKind.NOTES,
                key=_NOTES_SECTION_KEY,
                name=_NOTES_SECTION_NAME,
                is_top_level=True,
            )

    if not _looks_like_component_header(cleaned):
        return None

    component_key = normalize_section_key(cleaned)
    if not component_key:
        return None
    return _HeaderMatch(
        kind=SectionKind.OTHER,
        key=component_key,
        name=cleaned.rstrip(":").strip(),
        is_top_level=False,
    )


def _looks_like_component_header(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > 60:
        return False
    if any(char.isdigit() for char in stripped):
        return False

    lower = stripped.lower().rstrip(":").strip()
    if lower in _INSTRUCTION_SECTION_ALLOWLIST:
        return True
    if _contains_instruction_verb_phrase(lower):
        return False
    if re.search(r"[.!?;,]", stripped):
        return False

    if _FOR_PATTERN_RE.match(stripped):
        remainder = _FOR_PREFIX_RE.sub("", lower)
        if not remainder:
            return False
        words = remainder.split()
        if any(word in _FOR_COMPONENT_BANNED_WORDS for word in words):
            return False
        return True

    if _COLON_SECTION_RE.match(stripped):
        core = stripped.rstrip(":").strip()
        if _looks_title_or_upper(core):
            return True

    if re.match(r"^[A-Z][A-Z\s]{0,20}$", stripped) and len(stripped.split()) <= 3:
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


def _infer_component_kind(
    *,
    entries: Sequence[_Entry],
    position: int,
    active_kind: SectionKind,
    preferred_kind: SectionKind | None,
    overrides: ParsingOverrides | None,
) -> SectionKind:
    if active_kind in {SectionKind.INGREDIENTS, SectionKind.INSTRUCTIONS, SectionKind.NOTES}:
        return active_kind
    if preferred_kind is not None:
        return preferred_kind

    ingredient_votes = 0
    instruction_votes = 0
    notes_votes = 0
    scanned = 0
    for next_entry in entries[position + 1 :]:
        scanned += 1
        if scanned > 4:
            break
        header = _classify_header(next_entry.text)
        if header is not None:
            if header.is_top_level:
                if header.kind in {
                    SectionKind.INGREDIENTS,
                    SectionKind.INSTRUCTIONS,
                    SectionKind.NOTES,
                }:
                    return header.kind
                break
            continue
        inferred = _infer_kind_from_entry(next_entry, overrides=overrides)
        if inferred == SectionKind.INGREDIENTS:
            ingredient_votes += 1
        elif inferred == SectionKind.INSTRUCTIONS:
            instruction_votes += 1
        elif inferred == SectionKind.NOTES:
            notes_votes += 1

    if ingredient_votes > max(instruction_votes, notes_votes):
        return SectionKind.INGREDIENTS
    if instruction_votes > max(ingredient_votes, notes_votes):
        return SectionKind.INSTRUCTIONS
    if notes_votes > max(ingredient_votes, instruction_votes):
        return SectionKind.NOTES
    return SectionKind.INGREDIENTS


def _infer_kind_from_entry(
    entry: _Entry,
    *,
    overrides: ParsingOverrides | None,
) -> SectionKind:
    features = entry.features
    if features is None:
        features = signals.classify_block(entry.text, overrides=overrides)

    lower = entry.text.lower().strip()
    if lower.startswith(("note:", "notes:", "tip:", "tips:")):
        return SectionKind.NOTES
    if bool(features.get("is_instruction_header")):
        return SectionKind.INSTRUCTIONS
    if bool(features.get("is_ingredient_header")):
        return SectionKind.INGREDIENTS

    ingredient_likely = bool(features.get("is_ingredient_likely"))
    instruction_likely = bool(features.get("is_instruction_likely"))
    starts_with_quantity = bool(features.get("starts_with_quantity"))
    has_unit = bool(features.get("has_unit"))

    if ingredient_likely and not instruction_likely:
        return SectionKind.INGREDIENTS
    if instruction_likely and not ingredient_likely:
        return SectionKind.INSTRUCTIONS
    if starts_with_quantity or has_unit or re.match(r"^\s*[-*•]\s+", entry.text):
        return SectionKind.INGREDIENTS
    if _INSTRUCTION_LEAD_RE.match(entry.text) or re.match(r"^\s*\d+[.)]\s+", entry.text):
        return SectionKind.INSTRUCTIONS

    return SectionKind.OTHER


def _default_key_for_kind(kind: SectionKind) -> str:
    if kind == SectionKind.NOTES:
        return _NOTES_SECTION_KEY
    return _DEFAULT_SECTION_KEY


def _default_name_for_kind(kind: SectionKind) -> str:
    if kind == SectionKind.NOTES:
        return _NOTES_SECTION_NAME
    return _DEFAULT_SECTION_NAME


def _normalize_display_name(value: str) -> str:
    cleaned = _LEADING_BULLET_RE.sub("", value)
    cleaned = _LEADING_NUMBER_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return cleaned


__all__ = [
    "DetectedSections",
    "SectionKind",
    "SectionSpan",
    "detect_sections_from_blocks",
    "detect_sections_from_lines",
    "extract_structured_sections_from_lines",
    "normalize_section_key",
]
