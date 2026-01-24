from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Sequence

from cookimport.core.models import RecipeCandidate, TipCandidate, TipTags
from cookimport.parsing import signals
from cookimport.parsing.tip_taxonomy import (
    DAIRY_TERMS,
    FRUIT_TERMS,
    GRAIN_TERMS,
    HERB_TERMS,
    LEGUME_TERMS,
    MEAT_TERMS,
    OIL_FAT_TERMS,
    SPICE_TERMS,
    SWEETENER_TERMS,
    VEGETABLE_TERMS,
    TECHNIQUE_TERMS,
    TOOL_TERMS,
)

_TIP_PREFIX_RE = re.compile(r"^\s*(tip|tips|note|notes|hint|pro tip)\s*[:\-]+\s*", re.IGNORECASE)
_TIP_HEADER_ONLY_RE = re.compile(r"^\s*(tip|tips|note|notes|hints?)\s*[:\-]*\s*$", re.IGNORECASE)
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*\u2022]+\s+")
_RECIPE_SPECIFIC_HEADER_RE = re.compile(
    r"^\s*(why (this|the) recipe works|why it works|why this works|test kitchen note|"
    r"test kitchen tip|chef'?s notes?|why we (chose|use)|why this recipe)\s*:?\s*$",
    re.IGNORECASE,
)
_RECIPE_SPECIFIC_PHRASE_RE = re.compile(
    r"\b(this recipe|this dish|this version|this method|in this recipe)\b",
    re.IGNORECASE,
)

_ADVICE_CUE_RE = re.compile(
    r"\b(best|better|avoid|don't|do not|never|always|make sure|be sure|ensure|helps|prevent|"
    r"for best results|for better results|should|recommend|remember|important|key)\b",
    re.IGNORECASE,
)

_CONDITIONAL_CUE_RE = re.compile(r"\b(if|when|before|after)\b", re.IGNORECASE)

_PREFIX_STOPWORDS = {
    "mom",
    "mom's",
    "mother",
    "mother's",
    "grandma",
    "grandma's",
    "grandmother",
    "grandmother's",
    "dad",
    "dad's",
    "father",
    "father's",
    "aunt",
    "aunt's",
    "uncle",
    "uncle's",
    "chef",
    "chef's",
    "family",
    "family's",
    "my",
    "best",
    "easy",
    "quick",
    "simple",
    "perfect",
    "ultimate",
    "classic",
    "favorite",
    "favourite",
    "famous",
    "homemade",
    "weeknight",
    "everyday",
    "basic",
    "special",
}

_SUFFIX_STOPWORDS = {"recipe", "recipes"}


def canonicalize_recipe_name(name: str) -> str:
    cleaned = name.strip().lower()
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = cleaned.replace("\u2019", "'")
    cleaned = re.sub(r"[^a-z0-9\s'-]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t]
    normalized: list[str] = []
    for token in tokens:
        if token.endswith("'s"):
            base = token[:-2]
            if base in _PREFIX_STOPWORDS:
                continue
        normalized.append(token)
    while normalized and normalized[0] in _PREFIX_STOPWORDS:
        normalized.pop(0)
    while normalized and normalized[-1] in _SUFFIX_STOPWORDS:
        normalized.pop()
    return " ".join(normalized).strip()


def extract_tips(
    text: str,
    *,
    recipe_name: str | None = None,
    recipe_id: str | None = None,
    recipe_ingredients: Sequence[str] | None = None,
    provenance: dict[str, Any] | None = None,
    source_section: str | None = None,
    include_recipe_specific: bool = False,
) -> list[TipCandidate]:
    tips: list[TipCandidate] = []
    active_scope: str | None = None
    tip_counter = 0

    lines = text.splitlines()
    if len(lines) <= 1:
        lines = _split_tip_units(text)

    for raw_line in lines:
        stripped_line = raw_line.strip()
        if not stripped_line:
            active_scope = None
            continue
        if _RECIPE_SPECIFIC_HEADER_RE.match(stripped_line):
            active_scope = "recipe_specific"
            continue
        if _TIP_HEADER_ONLY_RE.match(stripped_line):
            active_scope = "general"
            continue

        units = _split_tip_units(stripped_line)
        for raw in units:
            score = _score_tip(raw)
            cleaned = _strip_tip_prefix(_strip_bullet_prefix(raw))
            if not cleaned:
                continue
            if score <= 0:
                continue

            scope = active_scope or _classify_scope(cleaned)
            if scope == "recipe_specific" and not include_recipe_specific:
                continue

            tip = TipCandidate(
                text=cleaned,
                scope=scope,
                tags=guess_tags(
                    cleaned,
                    recipe_name=recipe_name,
                    recipe_ingredients=recipe_ingredients,
                ),
                source_recipe_id=recipe_id,
                provenance=_build_tip_provenance(
                    provenance,
                    tip_index=tip_counter,
                    source_section=source_section,
                ),
                confidence=score,
            )
            tips.append(tip)
            tip_counter += 1
    return tips


def extract_tips_from_candidate(candidate: RecipeCandidate) -> list[TipCandidate]:
    if not candidate.description:
        return []
    recipe_id = candidate.identifier or _recipe_id_from_provenance(candidate.provenance)
    return extract_tips(
        candidate.description,
        recipe_name=candidate.name,
        recipe_id=recipe_id,
        recipe_ingredients=candidate.ingredients,
        provenance=candidate.provenance,
        source_section="description",
    )


def extract_recipe_specific_notes(candidate: RecipeCandidate) -> list[str]:
    if not candidate.description:
        return []
    tips = extract_tips(
        candidate.description,
        recipe_name=candidate.name,
        recipe_id=candidate.identifier,
        recipe_ingredients=candidate.ingredients,
        provenance=candidate.provenance,
        source_section="description",
        include_recipe_specific=True,
    )
    return [tip.text for tip in tips if tip.scope == "recipe_specific"]


def guess_tags(
    text: str,
    *,
    recipe_name: str | None = None,
    recipe_ingredients: Sequence[str] | None = None,
) -> TipTags:
    combined_parts = [text]
    if recipe_name:
        combined_parts.append(recipe_name)
    if recipe_ingredients:
        combined_parts.extend(recipe_ingredients)
    combined_text = " ".join(combined_parts).lower()

    tags = TipTags()

    if recipe_name:
        canonical = canonicalize_recipe_name(recipe_name)
        if canonical:
            tags.recipes.append(canonical)

    tags.meats = _match_taxonomy(combined_text, MEAT_TERMS)
    tags.vegetables = _match_taxonomy(combined_text, VEGETABLE_TERMS)
    tags.herbs = _match_taxonomy(combined_text, HERB_TERMS)
    tags.spices = _match_taxonomy(combined_text, SPICE_TERMS)
    tags.dairy = _match_taxonomy(combined_text, DAIRY_TERMS)
    tags.grains = _match_taxonomy(combined_text, GRAIN_TERMS)
    tags.legumes = _match_taxonomy(combined_text, LEGUME_TERMS)
    tags.fruits = _match_taxonomy(combined_text, FRUIT_TERMS)
    tags.sweeteners = _match_taxonomy(combined_text, SWEETENER_TERMS)
    tags.oils_fats = _match_taxonomy(combined_text, OIL_FAT_TERMS)
    tags.techniques = _match_taxonomy(combined_text, TECHNIQUE_TERMS)
    tags.tools = _match_taxonomy(combined_text, TOOL_TERMS)

    return tags


def _classify_scope(text: str) -> str:
    if _RECIPE_SPECIFIC_HEADER_RE.match(text):
        return "recipe_specific"
    if _RECIPE_SPECIFIC_PHRASE_RE.search(text):
        return "recipe_specific"
    return "general"


def _match_taxonomy(text: str, taxonomy: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    for canonical, variants in taxonomy.items():
        if _has_any_variant(text, variants):
            found.append(canonical)
    return found


def _has_any_variant(text: str, variants: Iterable[str]) -> bool:
    for variant in variants:
        pattern = r"\b" + re.escape(variant) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _split_tip_units(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines

    line = lines[0]
    if len(line) <= 180:
        return [line]

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line)
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences or [line]


def _strip_tip_prefix(text: str) -> str:
    if _TIP_HEADER_ONLY_RE.match(text):
        return ""
    return _TIP_PREFIX_RE.sub("", text).strip()


def _strip_bullet_prefix(text: str) -> str:
    return _BULLET_PREFIX_RE.sub("", text).strip()


def _score_tip(text: str) -> float:
    stripped = _strip_bullet_prefix(text.strip())
    if not stripped:
        return 0.0
    if _TIP_HEADER_ONLY_RE.match(stripped):
        return 0.0

    feats = signals.classify_block(stripped)
    has_tip_signal = bool(
        _TIP_PREFIX_RE.match(stripped)
        or _ADVICE_CUE_RE.search(stripped)
        or _CONDITIONAL_CUE_RE.search(stripped)
    )
    if feats.get("is_instruction_likely") and not has_tip_signal:
        return 0.0
    if feats.get("is_ingredient_likely"):
        return 0.0
    if feats.get("is_yield") or feats.get("is_time"):
        return 0.0

    if _TIP_PREFIX_RE.match(stripped):
        return 0.95
    if _ADVICE_CUE_RE.search(stripped):
        return 0.8
    if _CONDITIONAL_CUE_RE.search(stripped) and len(stripped.split()) >= 6:
        return 0.65

    return 0.0


def _build_tip_provenance(
    base: dict[str, Any] | None,
    *,
    tip_index: int | None = None,
    source_section: str | None = None,
) -> dict[str, Any]:
    if base:
        provenance = copy.deepcopy(base)
    else:
        provenance = {}

    if tip_index is not None:
        provenance["tip_index"] = tip_index
    if source_section:
        provenance["tip_source_section"] = source_section

    return provenance


def _recipe_id_from_provenance(provenance: dict[str, Any]) -> str | None:
    if not provenance:
        return None
    candidate_id = provenance.get("@id") or provenance.get("id")
    if candidate_id:
        return str(candidate_id)
    return None
