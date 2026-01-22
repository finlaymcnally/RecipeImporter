from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable

from cookimport.core.models import HowToStep

_WORD_RE = re.compile(r"[a-z0-9]+")

_ALL_INGREDIENTS_PATTERNS = (
    re.compile(r"\ball ingredients\b"),
    re.compile(r"\ball of the ingredients\b"),
    re.compile(r"\ball the ingredients\b"),
    re.compile(r"\bcombine all ingredients\b"),
    re.compile(r"\bmix all ingredients\b"),
    re.compile(r"\bstir all ingredients\b"),
    re.compile(r"\bcombine everything\b"),
    re.compile(r"\bmix everything\b"),
    re.compile(r"\bstir everything\b"),
)

_UNIT_TOKENS = {
    "cup",
    "cups",
    "tbsp",
    "tablespoon",
    "tablespoons",
    "tsp",
    "teaspoon",
    "teaspoons",
    "g",
    "kg",
    "oz",
    "ounce",
    "ounces",
    "lb",
    "lbs",
    "pound",
    "pounds",
    "ml",
    "l",
    "liter",
    "liters",
    "pinch",
    "pinches",
    "dash",
    "dashes",
    "clove",
    "cloves",
    "stalk",
    "stalks",
    "slice",
    "slices",
    "can",
    "cans",
    "package",
    "packages",
    "stick",
    "sticks",
}

_RAW_DROP_TOKENS = {"optional"}

_WEAK_MATCH_CAP = 3

_SECTION_DROP_LEADING = {"for", "the"}
_SECTION_DROP_TRAILING = {"ingredients"}


@dataclass(frozen=True)
class Alias:
    tokens: tuple[str, ...]
    source: str

    @property
    def score(self) -> tuple[int, int, int]:
        return (len(self.tokens), sum(len(token) for token in self.tokens), int(self.source == "input_item"))


@dataclass(frozen=True)
class Match:
    index: int
    tokens: tuple[str, ...]
    score: tuple[int, int, int]
    strength: str


@dataclass
class IngredientGroup:
    aliases: tuple[tuple[str, ...], ...]
    indices: list[int]


def assign_ingredient_lines_to_steps(
    steps: list[str | HowToStep],
    ingredient_lines: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Return a per-step list of ingredient lines in original order."""
    step_texts = [_coerce_step_text(step) for step in steps]
    if not step_texts:
        return []
    if not ingredient_lines:
        return [[] for _ in step_texts]

    groups = _build_groups(ingredient_lines)
    alias_map = _build_alias_map(ingredient_lines)
    non_header_indices = [
        idx
        for idx, line in enumerate(ingredient_lines)
        if line.get("quantity_kind") != "section_header"
    ]

    results: list[list[dict[str, Any]]] = []
    for step_text in step_texts:
        step_tokens = _tokenize(step_text)
        normalized_step = " ".join(step_tokens)
        if not step_tokens:
            results.append([])
            continue

        if _has_all_ingredients_phrase(normalized_step):
            results.append(_build_step_lines(non_header_indices, ingredient_lines))
            continue

        include_indices: set[int] = set()

        for group in groups:
            if _step_mentions_group(step_tokens, group.aliases):
                include_indices.update(group.indices)

        matches = _find_matches(step_tokens, alias_map)
        strong_matches = [match for match in matches if match.strength == "strong"]
        weak_matches = [match for match in matches if match.strength == "weak"]

        strong_tokens = {token for match in strong_matches for token in match.tokens}
        weak_matches = [
            match
            for match in weak_matches
            if not (set(match.tokens) & strong_tokens)
        ]

        if len(weak_matches) > _WEAK_MATCH_CAP:
            weak_matches = sorted(weak_matches, key=lambda match: match.score, reverse=True)[
                :_WEAK_MATCH_CAP
            ]

        include_indices.update(match.index for match in strong_matches)
        include_indices.update(match.index for match in weak_matches)

        results.append(_build_step_lines(include_indices, ingredient_lines))

    return results


def _coerce_step_text(step: str | HowToStep) -> str:
    if isinstance(step, HowToStep):
        return step.text
    return str(step) if step is not None else ""


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _WORD_RE.findall(text.lower())


def _clean_raw_text(text: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", " ", text)
    cleaned = cleaned.split(",", 1)[0]
    return cleaned


def _filter_alias_tokens(tokens: Iterable[str], drop_units: bool) -> list[str]:
    filtered: list[str] = []
    for token in tokens:
        if token.isdigit():
            continue
        if drop_units and token in _UNIT_TOKENS:
            continue
        if token in _RAW_DROP_TOKENS:
            continue
        filtered.append(token)
    return filtered


def _build_aliases(line: dict[str, Any]) -> list[Alias]:
    aliases: list[Alias] = []
    seen: set[tuple[str, ...]] = set()

    input_item = line.get("input_item") or ""
    input_tokens = _filter_alias_tokens(_tokenize(input_item), drop_units=False)
    if input_tokens:
        alias_tokens = tuple(input_tokens)
        aliases.append(Alias(tokens=alias_tokens, source="input_item"))
        seen.add(alias_tokens)

    raw_text = line.get("raw_text") or ""
    if raw_text:
        raw_tokens = _filter_alias_tokens(
            _tokenize(_clean_raw_text(raw_text)),
            drop_units=True,
        )
        if raw_tokens:
            alias_tokens = tuple(raw_tokens)
            if alias_tokens not in seen:
                aliases.append(Alias(tokens=alias_tokens, source="raw_text"))
                seen.add(alias_tokens)

    if len(input_tokens) > 1:
        tail = (input_tokens[-1],)
        if tail not in seen:
            aliases.append(Alias(tokens=tail, source="tail"))
            seen.add(tail)

    return aliases


def _build_alias_map(ingredient_lines: list[dict[str, Any]]) -> dict[int, list[Alias]]:
    alias_map: dict[int, list[Alias]] = {}
    for idx, line in enumerate(ingredient_lines):
        if line.get("quantity_kind") == "section_header":
            continue
        alias_map[idx] = _build_aliases(line)
    return alias_map


def _build_groups(ingredient_lines: list[dict[str, Any]]) -> list[IngredientGroup]:
    groups: list[IngredientGroup] = []
    current_group: IngredientGroup | None = None

    for idx, line in enumerate(ingredient_lines):
        if line.get("quantity_kind") == "section_header":
            label = line.get("input_item") or line.get("raw_text") or ""
            tokens = _normalize_section_tokens(label)
            if tokens:
                aliases = [tuple(tokens)]
                if "dry" in tokens:
                    aliases.append(("dry", "ingredients"))
                if "wet" in tokens:
                    aliases.append(("wet", "ingredients"))
                current_group = IngredientGroup(aliases=tuple(aliases), indices=[])
                groups.append(current_group)
            else:
                current_group = None
            continue

        if current_group is not None:
            current_group.indices.append(idx)

    return groups


def _normalize_section_tokens(label: str) -> list[str]:
    tokens = _tokenize(label)
    while tokens and tokens[0] in _SECTION_DROP_LEADING:
        tokens = tokens[1:]
    while tokens and tokens[-1] in _SECTION_DROP_TRAILING:
        tokens = tokens[:-1]
    return tokens


def _step_mentions_group(step_tokens: list[str], aliases: tuple[tuple[str, ...], ...]) -> bool:
    return any(_contains_phrase_tokens(step_tokens, list(alias)) for alias in aliases)


def _has_all_ingredients_phrase(normalized_step: str) -> bool:
    return any(pattern.search(normalized_step) for pattern in _ALL_INGREDIENTS_PATTERNS)


def _contains_phrase_tokens(step_tokens: list[str], phrase_tokens: list[str]) -> bool:
    if not phrase_tokens:
        return False
    if len(phrase_tokens) > len(step_tokens):
        return False
    for start in range(len(step_tokens) - len(phrase_tokens) + 1):
        if step_tokens[start : start + len(phrase_tokens)] == phrase_tokens:
            return True
    return False


def _find_matches(step_tokens: list[str], alias_map: dict[int, list[Alias]]) -> list[Match]:
    matches: list[Match] = []
    for idx, aliases in alias_map.items():
        best_alias = _find_best_alias_match(step_tokens, aliases)
        if best_alias is None:
            continue
        strength = "strong" if len(best_alias.tokens) > 1 else "weak"
        matches.append(
            Match(
                index=idx,
                tokens=best_alias.tokens,
                score=best_alias.score,
                strength=strength,
            )
        )
    return matches


def _find_best_alias_match(step_tokens: list[str], aliases: list[Alias]) -> Alias | None:
    best: Alias | None = None
    for alias in aliases:
        if not _contains_phrase_tokens(step_tokens, list(alias.tokens)):
            continue
        if best is None or alias.score > best.score:
            best = alias
    return best


def _build_step_lines(
    include_indices: Iterable[int],
    ingredient_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    include_set = set(include_indices)
    return [
        copy.deepcopy(line)
        for idx, line in enumerate(ingredient_lines)
        if idx in include_set and line.get("quantity_kind") != "section_header"
    ]
