from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from cookimport.core.models import ParsingOverrides, RecipeCandidate, TipCandidate, TipTags
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

_BULLET_PREFIX_RE = re.compile(r"^\s*[-*\u2022]+\s+")

_TIP_PREFIX_LABELS = [
    "tip",
    "tips",
    "note",
    "notes",
    "hint",
    "hints",
    "pro tip",
]

_HEADER_LABELS = [
    "tip",
    "tips",
    "note",
    "notes",
    "hint",
    "hints",
    "pro tip",
    "make ahead",
    "make-ahead",
    "variation",
    "variations",
    "serve with",
    "serving suggestion",
    "storage",
    "leftovers",
    "substitution",
    "substitutions",
    "why this recipe works",
    "why the recipe works",
    "why it works",
    "why this works",
    "why this recipe",
    "test kitchen note",
    "test kitchen tip",
    "chef's note",
    "chef's notes",
]

_RECIPE_SPECIFIC_HEADER_RE = re.compile(
    r"^\s*(why (this|the) recipe works|why it works|why this works|test kitchen note|"
    r"test kitchen tip|chef'?s notes?|why we (chose|use)|why this recipe)\s*:?\s*$",
    re.IGNORECASE,
)
_RECIPE_SPECIFIC_PHRASE_RE = re.compile(
    r"\b(this recipe|this dish|this version|this method|in this recipe)\b",
    re.IGNORECASE,
)

_DISCOURSE_PREFIX_RE = re.compile(
    r"^\s*(and|but|so|then|also|finally|still|however|therefore|"
    r"in other words|with this in mind|for this reason|as a result|in addition)\b\s*[,;:]*\s*",
    re.IGNORECASE,
)

_DEPENDENT_PREFIX_RE = re.compile(
    r"^\s*(and|but|so|then|also|finally|still|however|therefore|"
    r"in other words|with this in mind|for this reason|as a result|in addition)\b",
    re.IGNORECASE,
)

_ENDS_WITH_STOPWORD_RE = re.compile(
    r"\b(a|an|the|and|or|to|of|for|with|without|in|on|at|by|from|as|into|onto)\s*$",
    re.IGNORECASE,
)
_END_PUNCT_RE = re.compile(r"[.!?]\s*$")

_NARRATIVE_RE = re.compile(
    r"\b(i remember|i clearly remember|i'm a firm believer|i am a firm believer|"
    r"come over to my house|come over|i once|i accidentally|i decided|i always thought|"
    r"in my opinion|in my mind|for me|to me|as a kid|as a child|growing up|"
    r"last week|years ago|when i|when we|i think|i believe|i like|i love|i prefer|"
    r"if there is, i can't think of it|can't think of it)\b",
    re.IGNORECASE,
)

_FIRST_PERSON_RE = re.compile(
    r"\b(i|i'm|i am|i've|i\u2019m|i\u2019ve|i'd|we|we're|we are|we've|"
    r"we\u2019re|we\u2019ve|my|our|me|us)\b",
    re.IGNORECASE,
)

_SECOND_PERSON_RE = re.compile(r"\b(you|your|you'll|you\u2019ll)\b", re.IGNORECASE)

_TIP_ACTION_RE = re.compile(
    r"\b(use|add|keep|avoid|don'?t|do not|never|always|make sure|be sure|"
    r"remember|let|allow|stir|whisk|mix|cook|bake|roast|season|salt|sear|rest|"
    r"preheat|chill|heat|simmer|reduce)\b",
    re.IGNORECASE,
)

_DIAGNOSTIC_CUE_RE = re.compile(
    r"\b(you'?ll know|you will know|ready when|done when|ripe when|look for)\b",
    re.IGNORECASE,
)

_BENEFIT_CUE_RE = re.compile(
    r"\b(makes?|helps?|keeps?)\b.*\b(better|easier|tastier|more tender|more flavorful|"
    r"crispier|juicier|moist|evenly)\b|\b(for|with)\s+(better|more)\b.*\b("
    r"flavor|results|texture|browning|tenderness)\b",
    re.IGNORECASE,
)

_ADVICE_CUE_RE = re.compile(
    r"\b(avoid|don't|do not|never|always|make sure|be sure|ensure|helps|prevent|"
    r"for best results|for better results|should|recommend|remember|important|key|"
    r"best way|best to)\b",
    re.IGNORECASE,
)

_CONDITIONAL_CUE_RE = re.compile(r"\b(if|when|before|after|until|once)\b", re.IGNORECASE)

_STRONG_ADVICE_RE = re.compile(
    r"\b(should|must|need to|needs to|important|key|remember|make sure|be sure|"
    r"ensure|avoid|never|always|for best results|for better results|recommend)\b",
    re.IGNORECASE,
)

_GENERAL_CUE_RE = re.compile(
    r"\b(in general|generally|always|never|when cooking|when baking|when roasting|"
    r"when grilling|every time|whenever|for any|for all)\b",
    re.IGNORECASE,
)

_AIM_TO_START_RE = re.compile(r"^\s*aim to\b", re.IGNORECASE)

_STRONG_IMPERATIVE_RE = re.compile(
    r"^\s*(?:always\s+|never\s+)?"
    r"(salt|season|rest|sear|whisk|stir|mix|use|add|keep|avoid|let|allow|bake|"
    r"roast|cook|aim|chill|preheat|heat|simmer|reduce|grill|toast)\b",
    re.IGNORECASE,
)

_MIN_GENERAL_WORDS = 12

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

_INGREDIENT_STOPWORDS = {
    "cup",
    "cups",
    "tablespoon",
    "tablespoons",
    "tbsp",
    "teaspoon",
    "teaspoons",
    "tsp",
    "ounce",
    "ounces",
    "oz",
    "pound",
    "pounds",
    "lb",
    "lbs",
    "gram",
    "grams",
    "g",
    "kg",
    "ml",
    "liter",
    "liters",
    "pinch",
    "pinches",
    "dash",
    "dashes",
    "to",
    "taste",
    "or",
    "and",
    "of",
    "the",
}

_RECIPE_SPECIFIC_HEADERS = {
    "why this recipe works",
    "why the recipe works",
    "why it works",
    "why this works",
    "why this recipe",
    "test kitchen note",
    "test kitchen tip",
    "chef's note",
    "chef's notes",
}

_CALLOUT_HEADERS = {
    "tip",
    "tips",
    "note",
    "notes",
    "hint",
    "hints",
    "pro tip",
    "make ahead",
    "make-ahead",
    "variation",
    "variations",
    "serve with",
    "serving suggestion",
    "storage",
    "leftovers",
    "substitution",
    "substitutions",
} | _RECIPE_SPECIFIC_HEADERS

_STRONG_TIP_PREFIXES = {
    "tip",
    "tips",
    "pro tip",
    "pro tips",
}

_WEAK_TIP_PREFIXES = {
    "note",
    "notes",
    "hint",
    "hints",
}

_WEAK_CALLOUT_HEADERS = {
    "note",
    "notes",
    "hint",
    "hints",
    "chef's note",
    "chef's notes",
}


def _normalize_header(header: str) -> str:
    cleaned = header.strip().lower()
    cleaned = cleaned.replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


@dataclass(frozen=True)
class TipParsingProfile:
    tip_prefix_re: re.Pattern
    tip_header_only_re: re.Pattern
    header_only_re: re.Pattern
    header_prefix_re: re.Pattern
    callout_headers: set[str]
    recipe_specific_headers: set[str]
    strong_prefixes: set[str]
    weak_prefixes: set[str]
    strong_headers: set[str]
    weak_headers: set[str]
    overrides: ParsingOverrides | None


def _build_tip_profile(overrides: ParsingOverrides | None) -> TipParsingProfile:
    header_labels = list(_HEADER_LABELS)
    prefix_labels = list(_TIP_PREFIX_LABELS)
    callout_headers = set(_CALLOUT_HEADERS)
    recipe_specific_headers = set(_RECIPE_SPECIFIC_HEADERS)
    weak_prefixes = {_normalize_header(label) for label in _WEAK_TIP_PREFIXES}
    strong_prefixes = {_normalize_header(label) for label in _STRONG_TIP_PREFIXES}
    weak_headers = {_normalize_header(label) for label in _WEAK_CALLOUT_HEADERS}

    if overrides:
        if overrides.tip_headers:
            header_labels.extend(overrides.tip_headers)
            callout_headers.update(_normalize_header(label) for label in overrides.tip_headers)
        if overrides.tip_prefixes:
            prefix_labels.extend(overrides.tip_prefixes)

    header_pattern = "|".join(
        sorted((re.escape(label) for label in header_labels), key=len, reverse=True)
    )
    prefix_pattern = "|".join(
        sorted((re.escape(label) for label in prefix_labels), key=len, reverse=True)
    )
    for label in prefix_labels:
        normalized = _normalize_header(label)
        if normalized in weak_prefixes:
            continue
        strong_prefixes.add(normalized)

    normalized_callouts = {_normalize_header(h) for h in callout_headers}
    normalized_recipe_specific = {_normalize_header(h) for h in recipe_specific_headers}
    strong_headers = normalized_callouts - weak_headers - normalized_recipe_specific

    return TipParsingProfile(
        tip_prefix_re=re.compile(
            rf"^\s*(?P<prefix>{prefix_pattern})\s*[:\-]+\s*", re.IGNORECASE
        ),
        tip_header_only_re=re.compile(
            rf"^\s*(?P<prefix>{prefix_pattern})\s*[:\-]*\s*$", re.IGNORECASE
        ),
        header_only_re=re.compile(
            rf"^\s*(?P<header>{header_pattern})\s*[:\-]*\s*$", re.IGNORECASE
        ),
        header_prefix_re=re.compile(
            rf"^\s*(?P<header>{header_pattern})\s*[:\-]+\s*(?P<content>.+)$",
            re.IGNORECASE,
        ),
        callout_headers=normalized_callouts,
        recipe_specific_headers=normalized_recipe_specific,
        strong_prefixes=strong_prefixes,
        weak_prefixes=weak_prefixes,
        strong_headers=strong_headers,
        weak_headers=weak_headers,
        overrides=overrides,
    )


_DEFAULT_TIP_PROFILE = _build_tip_profile(None)

@dataclass(frozen=True)
class CandidateBlock:
    index: int
    text: str
    header: str | None = None


@dataclass(frozen=True)
class TipSpan:
    text: str
    block_index: int
    sentence_start: int | None = None
    sentence_end: int | None = None
    prev_sentence: str | None = None
    next_sentence: str | None = None
    header: str | None = None


@dataclass(frozen=True)
class TipJudgment:
    scope: str
    standalone: bool
    confidence: float
    generality_score: float | None
    normalized_text: str


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
    include_not_tips: bool = False,
    require_standalone: bool = True,
    overrides: ParsingOverrides | None = None,
) -> list[TipCandidate]:
    tips: list[TipCandidate] = []
    tip_counter = 0

    profile = _build_tip_profile(overrides)
    blocks = _split_blocks(text, profile)
    ingredient_tokens = _extract_ingredient_tokens(recipe_ingredients)

    for block_idx, block in enumerate(blocks):
        prev_block_text = blocks[block_idx - 1].text if block_idx > 0 else None
        next_block_text = blocks[block_idx + 1].text if block_idx + 1 < len(blocks) else None
        spans = _extract_spans_from_block(block, profile)
        for span in spans:
            repaired_text, repair_flags = _repair_span(
                span.text,
                prev_sentence=span.prev_sentence,
                next_sentence=span.next_sentence,
                prev_block=prev_block_text,
                next_block=next_block_text,
            )
            tip_prefix_strength = _tip_prefix_strength(repaired_text, profile)
            normalized = _normalize_tip_text(repaired_text, profile)
            if not normalized:
                continue
            judgment = _judge_tip(
                normalized,
                recipe_name=recipe_name,
                ingredient_tokens=ingredient_tokens,
                header_hint=span.header,
                tip_prefix_strength=tip_prefix_strength,
                source_section=source_section,
                profile=profile,
            )

            if not judgment.standalone and require_standalone:
                if include_not_tips:
                    judgment = TipJudgment(
                        scope="not_tip",
                        standalone=judgment.standalone,
                        confidence=judgment.confidence,
                        generality_score=judgment.generality_score,
                        normalized_text=judgment.normalized_text,
                    )
                else:
                    continue

            if judgment.scope == "recipe_specific" and not include_recipe_specific:
                continue
            if judgment.scope == "not_tip" and not include_not_tips:
                continue

            tags = TipTags()
            if judgment.scope != "not_tip":
                tags = guess_tags(
                    judgment.normalized_text,
                    recipe_name=recipe_name,
                    recipe_ingredients=recipe_ingredients,
                )

            tip = TipCandidate(
                text=judgment.normalized_text,
                source_text=repaired_text,
                scope=judgment.scope,
                standalone=judgment.standalone,
                generality_score=judgment.generality_score,
                tags=tags,
                source_recipe_id=recipe_id,
                source_recipe_title=recipe_name if recipe_name and recipe_name.strip() else None,
                provenance=_build_tip_provenance(
                    provenance,
                    tip_index=tip_counter,
                    source_section=source_section,
                    block_index=span.block_index,
                    sentence_start=span.sentence_start,
                    sentence_end=span.sentence_end,
                    span_repairs=repair_flags,
                    header_hint=span.header,
                ),
                confidence=judgment.confidence,
            )
            tips.append(tip)
            tip_counter += 1
    return tips


def extract_tips_from_candidate(
    candidate: RecipeCandidate,
    overrides: ParsingOverrides | None = None,
) -> list[TipCandidate]:
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
        overrides=overrides,
    )


def extract_tip_candidates_from_candidate(
    candidate: RecipeCandidate,
    overrides: ParsingOverrides | None = None,
) -> list[TipCandidate]:
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
        include_recipe_specific=True,
        include_not_tips=True,
        require_standalone=False,
        overrides=overrides,
    )


def extract_tip_candidates(
    text: str,
    *,
    recipe_name: str | None = None,
    recipe_id: str | None = None,
    recipe_ingredients: Sequence[str] | None = None,
    provenance: dict[str, Any] | None = None,
    source_section: str | None = None,
    overrides: ParsingOverrides | None = None,
) -> list[TipCandidate]:
    return extract_tips(
        text,
        recipe_name=recipe_name,
        recipe_id=recipe_id,
        recipe_ingredients=recipe_ingredients,
        provenance=provenance,
        source_section=source_section,
        include_recipe_specific=True,
        include_not_tips=True,
        require_standalone=False,
        overrides=overrides,
    )


def extract_recipe_specific_notes(
    candidate: RecipeCandidate,
    overrides: ParsingOverrides | None = None,
) -> list[str]:
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
        include_not_tips=False,
        require_standalone=True,
        overrides=overrides,
    )
    return [tip.text for tip in tips if tip.scope == "recipe_specific"]


def partition_tip_candidates(
    tips: Sequence[TipCandidate],
) -> tuple[list[TipCandidate], list[TipCandidate], list[TipCandidate]]:
    general = [tip for tip in tips if tip.scope == "general" and tip.standalone]
    recipe_specific = [tip for tip in tips if tip.scope == "recipe_specific"]
    not_tips = [tip for tip in tips if tip.scope == "not_tip"]
    return general, recipe_specific, not_tips


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


def _header_is_recipe_specific(header: str | None, profile: TipParsingProfile) -> bool:
    if not header:
        return False
    return _normalize_header(header) in profile.recipe_specific_headers


def _header_implies_tip(header: str | None, profile: TipParsingProfile) -> bool:
    if not header:
        return False
    return _normalize_header(header) in profile.callout_headers


def _header_strength(header: str | None, profile: TipParsingProfile) -> str | None:
    if not header:
        return None
    normalized = _normalize_header(header)
    if normalized in profile.recipe_specific_headers:
        return "recipe_specific"
    if normalized in profile.strong_headers:
        return "strong"
    if normalized in profile.weak_headers:
        return "weak"
    return None


def _tip_prefix_strength(text: str, profile: TipParsingProfile) -> str | None:
    match = profile.tip_prefix_re.match(text)
    if not match:
        return None
    prefix = _normalize_header(match.group("prefix"))
    if prefix in profile.weak_prefixes:
        return "weak"
    return "strong"


def _explicit_tip_signal(
    text: str,
    *,
    tip_prefix_strength: str | None,
    header_strength: str | None,
    profile: TipParsingProfile,
) -> bool:
    if tip_prefix_strength == "strong":
        return True
    if header_strength in {"strong", "recipe_specific"}:
        return True
    if _STRONG_ADVICE_RE.search(text):
        return True
    if _STRONG_IMPERATIVE_RE.match(text):
        return True
    if _AIM_TO_START_RE.match(text):
        return True
    if _DIAGNOSTIC_CUE_RE.search(text):
        return True
    if _BENEFIT_CUE_RE.search(text):
        return True
    if _SECOND_PERSON_RE.search(text) and _TIP_ACTION_RE.search(text):
        return True
    return False


def _is_narrative_like(text: str) -> bool:
    if _NARRATIVE_RE.search(text):
        return True
    if _FIRST_PERSON_RE.search(text):
        return True
    return False


def _split_blocks(text: str, profile: TipParsingProfile) -> list[CandidateBlock]:
    lines = [line.rstrip() for line in str(text).splitlines()]
    blocks: list[CandidateBlock] = []
    buffer: list[str] = []
    buffer_header: str | None = None
    pending_header: str | None = None

    def flush_buffer() -> None:
        nonlocal buffer, buffer_header
        if not buffer:
            buffer_header = None
            return
        block_text = "\n".join(buffer).strip()
        if block_text:
            blocks.append(
                CandidateBlock(index=len(blocks), text=block_text, header=buffer_header)
            )
        buffer = []
        buffer_header = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_buffer()
            continue

        prefix_match = profile.header_prefix_re.match(line)
        if prefix_match:
            flush_buffer()
            header = _normalize_header(prefix_match.group("header"))
            content = prefix_match.group("content").strip()
            if content:
                blocks.append(
                    CandidateBlock(index=len(blocks), text=content, header=header)
                )
            else:
                pending_header = header
            continue

        header_only_match = profile.header_only_re.match(line)
        if header_only_match:
            flush_buffer()
            pending_header = _normalize_header(header_only_match.group("header"))
            continue

        if not buffer:
            buffer_header = pending_header
            pending_header = None
        buffer.append(line)

    flush_buffer()
    return blocks


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    return sentences or [cleaned]


def _extract_spans_from_block(
    block: CandidateBlock,
    profile: TipParsingProfile,
) -> list[TipSpan]:
    block_text = block.text.strip()
    if not block_text:
        return []
    header_strength = _header_strength(block.header, profile)

    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    bullet_lines = [line for line in lines if _BULLET_PREFIX_RE.match(line)]
    if len(bullet_lines) >= 2:
        spans: list[TipSpan] = []
        for idx, line in enumerate(lines):
            if not _BULLET_PREFIX_RE.match(line):
                continue
            spans.append(
                TipSpan(
                    text=_strip_bullet_prefix(line),
                    block_index=block.index,
                    sentence_start=idx,
                    sentence_end=idx,
                    prev_sentence=lines[idx - 1] if idx > 0 else None,
                    next_sentence=lines[idx + 1] if idx + 1 < len(lines) else None,
                    header=block.header,
                )
            )
        return spans

    if _header_implies_tip(block.header, profile):
        return [
            TipSpan(
                text=block_text,
                block_index=block.index,
                sentence_start=0,
                sentence_end=0,
                prev_sentence=None,
                next_sentence=None,
                header=block.header,
            )
        ]

    sentences = _split_sentences(block_text)
    if not sentences:
        return []

    spans: list[TipSpan] = []
    current_start: int | None = None
    current_end: int | None = None
    for idx, sentence in enumerate(sentences):
        if (
            _tipness_score(sentence, header_strength=header_strength, profile=profile) >= 0.45
        ):
            if current_start is None:
                current_start = idx
                current_end = idx
            else:
                current_end = idx
        else:
            if current_start is not None:
                spans.append(
                    TipSpan(
                        text=" ".join(sentences[current_start : current_end + 1]),
                        block_index=block.index,
                        sentence_start=current_start,
                        sentence_end=current_end,
                        prev_sentence=sentences[current_start - 1]
                        if current_start > 0
                        else None,
                        next_sentence=sentences[current_end + 1]
                        if current_end + 1 < len(sentences)
                        else None,
                        header=block.header,
                    )
                )
                current_start = None
                current_end = None

    if current_start is not None:
        spans.append(
            TipSpan(
                text=" ".join(sentences[current_start : current_end + 1]),
                block_index=block.index,
                sentence_start=current_start,
                sentence_end=current_end,
                prev_sentence=sentences[current_start - 1] if current_start > 0 else None,
                next_sentence=sentences[current_end + 1]
                if current_end + 1 < len(sentences)
                else None,
                header=block.header,
            )
        )

    if spans:
        return spans

    if _tipness_score(block_text, header_strength=header_strength, profile=profile) >= 0.6:
        return [
            TipSpan(
                text=block_text,
                block_index=block.index,
                sentence_start=0,
                sentence_end=0,
                prev_sentence=None,
                next_sentence=None,
                header=block.header,
            )
        ]

    return []


def _repair_span(
    text: str,
    *,
    prev_sentence: str | None,
    next_sentence: str | None,
    prev_block: str | None,
    next_block: str | None,
) -> tuple[str, dict[str, bool]]:
    repaired = text.strip()
    flags = {"prepended": False, "appended": False}

    for _ in range(2):
        if _needs_prefix(repaired):
            candidate = prev_sentence or prev_block
            if candidate:
                repaired = f"{candidate.strip()} {repaired}"
                flags["prepended"] = True
            else:
                break
        if _needs_suffix(repaired):
            candidate = next_sentence or next_block
            if candidate:
                repaired = f"{repaired} {candidate.strip()}"
                flags["appended"] = True
            else:
                break

    return repaired, flags


def _needs_prefix(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in ".,;:":
        return True
    if _DEPENDENT_PREFIX_RE.match(stripped):
        return True
    return False


def _needs_suffix(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _END_PUNCT_RE.search(stripped):
        return False
    words = stripped.split()
    if len(words) <= 6 and _STRONG_IMPERATIVE_RE.match(stripped):
        return False
    if _ENDS_WITH_STOPWORD_RE.search(stripped):
        return True
    return True


def _is_standalone(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _DEPENDENT_PREFIX_RE.match(stripped):
        return False
    if _needs_suffix(stripped) or _needs_prefix(stripped):
        return False
    return True


def _normalize_tip_text(text: str, profile: TipParsingProfile) -> str:
    cleaned = _strip_tip_prefix(_strip_bullet_prefix(text.strip()), profile)
    cleaned = re.sub(r"^[\.,;:]+\s*", "", cleaned)
    cleaned = _DISCOURSE_PREFIX_RE.sub("", cleaned, count=1)
    return cleaned.strip()


def _judge_tip(
    text: str,
    *,
    recipe_name: str | None,
    ingredient_tokens: set[str],
    header_hint: str | None,
    tip_prefix_strength: str | None,
    source_section: str | None,
    profile: TipParsingProfile,
) -> TipJudgment:
    header_strength = _header_strength(header_hint, profile)
    tipness = _tipness_score(
        text,
        tip_prefix_strength=tip_prefix_strength,
        header_strength=header_strength,
        profile=profile,
    )
    standalone = _is_standalone(text)
    recipe_context = bool(recipe_name) and source_section != "standalone_block"
    explicit_advice = _explicit_tip_signal(
        text,
        tip_prefix_strength=tip_prefix_strength,
        header_strength=header_strength,
        profile=profile,
    )

    if _hard_reject(text, explicit_advice=explicit_advice, header_strength=header_strength):
        return TipJudgment(
            scope="not_tip",
            standalone=standalone,
            confidence=max(0.05, tipness),
            generality_score=None,
            normalized_text=text,
        )

    if source_section == "standalone_block" and not explicit_advice:
        return TipJudgment(
            scope="not_tip",
            standalone=standalone,
            confidence=tipness,
            generality_score=None,
            normalized_text=text,
        )

    threshold = 0.45
    if source_section == "standalone_block" and tip_prefix_strength is None:
        threshold = 0.55
    if header_strength in {"strong", "recipe_specific"} or tip_prefix_strength == "strong":
        threshold = 0.4

    if tipness < threshold and header_strength != "recipe_specific":
        return TipJudgment(
            scope="not_tip",
            standalone=standalone,
            confidence=tipness,
            generality_score=None,
            normalized_text=text,
        )

    generality = _generality_score(
        text,
        recipe_name=recipe_name,
        ingredient_tokens=ingredient_tokens,
    )
    ingredient_overlap = _ingredient_overlap_count(text, ingredient_tokens)

    word_count = len(text.split())
    has_diagnostic = bool(_DIAGNOSTIC_CUE_RE.search(text))
    has_general_cue = bool(_GENERAL_CUE_RE.search(text))

    if (
        header_strength == "recipe_specific"
        or _RECIPE_SPECIFIC_HEADER_RE.match(text)
        or _header_is_recipe_specific(header_hint, profile)
    ):
        scope = "recipe_specific"
    elif _RECIPE_SPECIFIC_PHRASE_RE.search(text):
        scope = "recipe_specific"
    elif recipe_context:
        if (
            explicit_advice
            and generality >= 0.85
            and (has_general_cue or has_diagnostic or header_strength == "strong")
            and word_count >= _MIN_GENERAL_WORDS
        ):
            scope = "general"
        else:
            scope = "recipe_specific"
    else:
        if not explicit_advice or generality < 0.6:
            scope = "not_tip"
        else:
            scope = "general"

    if recipe_context and scope == "general" and ingredient_overlap >= 1 and generality < 0.9:
        scope = "recipe_specific"

    if (
        scope == "general"
        and word_count < _MIN_GENERAL_WORDS
        and not has_diagnostic
        and tip_prefix_strength != "strong"
        and header_strength != "strong"
        and not _BENEFIT_CUE_RE.search(text)
        and not _STRONG_ADVICE_RE.search(text)
    ):
        scope = "recipe_specific" if recipe_context else "not_tip"

    return TipJudgment(
        scope=scope,
        standalone=standalone,
        confidence=tipness,
        generality_score=generality,
        normalized_text=text,
    )


def _tipness_score(
    text: str,
    *,
    tip_prefix_strength: str | None = None,
    header_strength: str | None = None,
    profile: TipParsingProfile,
) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    feats = signals.classify_block(stripped, overrides=profile.overrides)
    score = 0.0

    if tip_prefix_strength == "strong":
        score += 0.6
    elif tip_prefix_strength == "weak":
        score += 0.35
    if header_strength == "strong":
        score += 0.4
    elif header_strength == "weak":
        score += 0.2
    elif header_strength == "recipe_specific":
        score += 0.35

    if _STRONG_IMPERATIVE_RE.match(stripped):
        score += 0.35
    elif _TIP_ACTION_RE.search(stripped):
        score += 0.2
    if _STRONG_ADVICE_RE.search(stripped):
        score += 0.3
    if _ADVICE_CUE_RE.search(stripped):
        score += 0.2
    if _CONDITIONAL_CUE_RE.search(stripped):
        score += 0.1
    if _DIAGNOSTIC_CUE_RE.search(stripped):
        score += 0.35
    if _BENEFIT_CUE_RE.search(stripped):
        score += 0.3
    if _AIM_TO_START_RE.match(stripped):
        score += 0.2
    if feats.get("has_imperative_verb") and not _STRONG_IMPERATIVE_RE.match(stripped):
        score += 0.15

    if feats.get("is_instruction_likely") and tip_prefix_strength != "strong":
        score -= 0.15
    if feats.get("is_ingredient_likely"):
        score -= 0.4
    if feats.get("is_yield") or feats.get("is_time"):
        score -= 0.4
    if _is_narrative_like(stripped) and not _STRONG_ADVICE_RE.search(stripped):
        score -= 0.35

    return max(0.0, min(1.0, score))


def _hard_reject(
    text: str,
    *,
    explicit_advice: bool,
    header_strength: str | None,
) -> bool:
    stripped = text.strip()
    if (
        not explicit_advice
        and header_strength not in {"strong", "recipe_specific"}
        and _is_narrative_like(stripped)
    ):
        return True
    words = stripped.split()
    if len(words) < 6 and not _STRONG_IMPERATIVE_RE.match(stripped) and not explicit_advice:
        return True
    return False


def _generality_score(
    text: str,
    *,
    recipe_name: str | None,
    ingredient_tokens: set[str],
) -> float:
    score = 0.5
    lowered = text.lower()

    if _DIAGNOSTIC_CUE_RE.search(lowered):
        score += 0.2
    if _ADVICE_CUE_RE.search(lowered):
        score += 0.1
    if _STRONG_ADVICE_RE.search(lowered):
        score += 0.1
    if _STRONG_IMPERATIVE_RE.match(lowered):
        score += 0.15
    elif _TIP_ACTION_RE.search(lowered):
        score += 0.05
    if _BENEFIT_CUE_RE.search(lowered):
        score += 0.1

    if _RECIPE_SPECIFIC_PHRASE_RE.search(lowered):
        score -= 0.25

    if recipe_name:
        canonical = canonicalize_recipe_name(recipe_name)
        if canonical:
            tokens = [t for t in canonical.split() if t]
            if tokens:
                matches = sum(1 for token in tokens if token in lowered)
                if len(tokens) == 1 and matches >= 1:
                    token = tokens[0]
                    if token in ingredient_tokens:
                        score -= 0.05
                    else:
                        score -= 0.2
                elif len(tokens) > 1 and (matches >= 2 or canonical in lowered):
                    score -= 0.2

    if ingredient_tokens:
        overlap = sum(1 for token in ingredient_tokens if token in lowered)
        if overlap >= 3:
            score -= 0.25
        elif overlap >= 2:
            score -= 0.15

    return max(0.0, min(1.0, score))


def _ingredient_overlap_count(text: str, ingredient_tokens: set[str]) -> int:
    if not ingredient_tokens:
        return 0
    lowered = text.lower()
    return sum(1 for token in ingredient_tokens if token in lowered)


def _extract_ingredient_tokens(
    recipe_ingredients: Sequence[str] | None,
) -> set[str]:
    tokens: set[str] = set()
    if not recipe_ingredients:
        return tokens
    for ingredient in recipe_ingredients:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", str(ingredient)).lower()
        for part in cleaned.split():
            if not part or part.isdigit():
                continue
            if part in _INGREDIENT_STOPWORDS:
                continue
            if len(part) <= 2:
                continue
            tokens.add(part)
    return tokens


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


def _strip_tip_prefix(text: str, profile: TipParsingProfile) -> str:
    if profile.tip_header_only_re.match(text):
        return ""
    return profile.tip_prefix_re.sub("", text).strip()


def _strip_bullet_prefix(text: str) -> str:
    return _BULLET_PREFIX_RE.sub("", text).strip()


def _build_tip_provenance(
    base: dict[str, Any] | None,
    *,
    tip_index: int | None = None,
    source_section: str | None = None,
    block_index: int | None = None,
    sentence_start: int | None = None,
    sentence_end: int | None = None,
    span_repairs: dict[str, bool] | None = None,
    header_hint: str | None = None,
) -> dict[str, Any]:
    if base:
        provenance = copy.deepcopy(base)
    else:
        provenance = {}

    if tip_index is not None:
        provenance["tip_index"] = tip_index
    if source_section:
        provenance["tip_source_section"] = source_section
    if block_index is not None:
        provenance["tip_block_index"] = block_index
    if sentence_start is not None:
        provenance["tip_sentence_start"] = sentence_start
    if sentence_end is not None:
        provenance["tip_sentence_end"] = sentence_end
    if span_repairs:
        provenance["tip_span_repairs"] = span_repairs
    if header_hint:
        provenance["tip_header"] = header_hint

    return provenance


def _recipe_id_from_provenance(provenance: dict[str, Any]) -> str | None:
    if not provenance:
        return None
    candidate_id = provenance.get("@id") or provenance.get("id")
    if candidate_id:
        return str(candidate_id)
    return None
