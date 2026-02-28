"""Deterministic recipe yield extraction/parsing for Priority 6."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

from cookimport.core.models import HowToStep, RecipeCandidate

YIELD_MODE_LEGACY_V1 = "legacy_v1"
YIELD_MODE_SCORED_V1 = "scored_v1"

_ALLOWED_YIELD_MODES = {YIELD_MODE_LEGACY_V1, YIELD_MODE_SCORED_V1}

_YIELD_PREFIX_RE = re.compile(
    r"^\s*(serves?|servings?|yield|yields|makes?)\b",
    re.IGNORECASE,
)
_NUTRITION_HINT_RE = re.compile(
    r"\b(calories?|kcal|protein|fat|carb(?:s|ohydrates?)?|sodium|cholesterol|fiber|daily value|%dv)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?")
_RANGE_RE = re.compile(
    r"(?P<start>\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s*(?:-|to)\s*(?P<end>\d+(?:\.\d+)?(?:\s*/\s*\d+)?)",
    re.IGNORECASE,
)
_DOZEN_RE = re.compile(
    r"(?:(?P<count>\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s+)?dozen\b",
    re.IGNORECASE,
)

_WORD_NUMBERS: dict[str, float] = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
}

_STOPWORDS = {
    "about",
    "approximately",
    "approx",
    "around",
    "up",
    "to",
    "or",
    "and",
    "plus",
}


@dataclass(frozen=True)
class YieldCandidate:
    text: str
    source: str
    score: int


@dataclass(frozen=True)
class YieldParseResult:
    units: int | None
    unit_name: str | None
    detail: str | None


def normalize_yield_mode(payload: Mapping[str, Any] | None) -> str:
    source = payload or {}
    mode = str(
        source.get("p6_yield_mode", source.get("yield_mode", YIELD_MODE_LEGACY_V1))
    ).strip().lower().replace("-", "_")
    if mode in _ALLOWED_YIELD_MODES:
        return mode
    return YIELD_MODE_LEGACY_V1


def derive_yield_fields(
    candidate: RecipeCandidate,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive normalized draft yield fields from candidate text sources."""
    mode = normalize_yield_mode(payload)
    if mode == YIELD_MODE_LEGACY_V1:
        return {
            "yield_units": 1,
            "yield_phrase": candidate.recipe_yield,
            "yield_unit_name": None,
            "yield_detail": None,
            "_p6_yield_debug": {
                "yield_mode": mode,
                "selected_source": "legacy",
            },
        }

    candidates = _collect_candidates(candidate)
    selected = _select_candidate(candidates)
    selected_text = selected.text if selected is not None else (candidate.recipe_yield or None)
    parsed = _parse_yield_phrase(selected_text)

    return {
        "yield_units": parsed.units if parsed.units is not None else 1,
        "yield_phrase": selected_text,
        "yield_unit_name": parsed.unit_name,
        "yield_detail": parsed.detail,
        "_p6_yield_debug": {
            "yield_mode": mode,
            "selected_source": selected.source if selected is not None else None,
            "selected_score": selected.score if selected is not None else None,
            "selected_text": selected_text,
            "candidate_count": len(candidates),
        },
    }


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _add_candidate(
    values: dict[str, YieldCandidate],
    *,
    text: str,
    source: str,
    base_score: int,
) -> None:
    cleaned = _normalize_text(text)
    if not cleaned:
        return

    score = base_score
    if _YIELD_PREFIX_RE.match(cleaned):
        score += 20
    if _NUMBER_RE.search(cleaned):
        score += 15
    if len(cleaned) > 96:
        score -= 20
    if _NUTRITION_HINT_RE.search(cleaned):
        score -= 80

    key = cleaned.lower()
    previous = values.get(key)
    candidate = YieldCandidate(text=cleaned, source=source, score=score)
    if previous is None or candidate.score > previous.score:
        values[key] = candidate


def _collect_candidates(candidate: RecipeCandidate) -> list[YieldCandidate]:
    collected: dict[str, YieldCandidate] = {}

    if candidate.recipe_yield:
        _add_candidate(
            collected,
            text=candidate.recipe_yield,
            source="recipe_yield",
            base_score=100,
        )

    if candidate.description:
        for line in str(candidate.description).splitlines():
            if _YIELD_PREFIX_RE.match(line):
                _add_candidate(collected, text=line, source="description", base_score=70)

    for item in candidate.instructions:
        line = item.text if isinstance(item, HowToStep) else str(item)
        if _YIELD_PREFIX_RE.match(line):
            _add_candidate(collected, text=line, source="instruction", base_score=65)

    for comment in candidate.comments:
        text = getattr(comment, "text", None)
        if isinstance(text, str) and _YIELD_PREFIX_RE.match(text):
            _add_candidate(collected, text=text, source="comment", base_score=60)

    return sorted(collected.values(), key=lambda row: row.score, reverse=True)


def _select_candidate(candidates: list[YieldCandidate]) -> YieldCandidate | None:
    for candidate in candidates:
        if candidate.score > 0:
            return candidate
    return None


def _parse_number_fragment(fragment: str) -> float | None:
    token = fragment.strip().lower()
    if not token:
        return None
    if token in _WORD_NUMBERS:
        return _WORD_NUMBERS[token]
    normalized = token.replace(" ", "")
    try:
        return float(Fraction(normalized))
    except Exception:
        return None


def _singularize(word: str) -> str:
    text = word.strip().lower()
    if text.endswith("ies") and len(text) > 3:
        return f"{text[:-3]}y"
    if text.endswith("s") and len(text) > 2:
        return text[:-1]
    return text


def _strip_prefix(text: str) -> tuple[str, str | None]:
    match = _YIELD_PREFIX_RE.match(text)
    if match is None:
        return text.strip(), None
    label = match.group(1).lower()
    remainder = text[match.end() :].strip(" :-")
    return (remainder or text.strip(), label)


def _parse_yield_phrase(text: str | None) -> YieldParseResult:
    if not isinstance(text, str):
        return YieldParseResult(units=None, unit_name=None, detail=None)

    cleaned = _normalize_text(text)
    if not cleaned or _NUTRITION_HINT_RE.search(cleaned):
        return YieldParseResult(units=None, unit_name=None, detail=None)

    remainder, label = _strip_prefix(cleaned)

    # Handle "dozen" expressions first (for example: "2 dozen cookies").
    dozen_match = _DOZEN_RE.search(remainder)
    if dozen_match is not None:
        raw_count = dozen_match.group("count")
        count = _parse_number_fragment(raw_count) if raw_count else 1.0
        if count is not None and count > 0:
            units = max(1, int(math.ceil(count * 12.0)))
            after = remainder[dozen_match.end() :].strip(" ,.-")
            unit_name = None
            detail = after or None
            if after:
                first_word = re.split(r"\W+", after)[0]
                if first_word and first_word.lower() not in _STOPWORDS:
                    unit_name = _singularize(first_word)
            return YieldParseResult(units=units, unit_name=unit_name, detail=detail)

    quantity: float | None = None
    quantity_end = 0

    range_match = _RANGE_RE.search(remainder)
    if range_match is not None:
        left = _parse_number_fragment(range_match.group("start"))
        right = _parse_number_fragment(range_match.group("end"))
        if left is not None and right is not None:
            quantity = (left + right) / 2.0
            quantity_end = range_match.end()

    if quantity is None:
        number_match = _NUMBER_RE.search(remainder)
        if number_match is not None:
            parsed = _parse_number_fragment(number_match.group(0))
            if parsed is not None:
                quantity = parsed
                quantity_end = number_match.end()

    if quantity is None:
        word_match = re.match(r"^\s*([A-Za-z]+)", remainder)
        if word_match is not None:
            parsed = _parse_number_fragment(word_match.group(1))
            if parsed is not None:
                quantity = parsed
                quantity_end = word_match.end()

    if quantity is None or quantity <= 0:
        return YieldParseResult(units=None, unit_name=None, detail=None)

    units = max(1, int(math.ceil(quantity)))
    tail = remainder[quantity_end:].strip(" ,.-")

    unit_name: str | None = None
    detail = tail or None
    if tail:
        first_word = re.split(r"\W+", tail)[0]
        if first_word and first_word.lower() not in _STOPWORDS:
            unit_name = _singularize(first_word)
    elif label is not None and label.startswith("serv"):
        unit_name = "serving"

    return YieldParseResult(units=units, unit_name=unit_name, detail=detail)
