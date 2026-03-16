from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable

from rapidfuzz import fuzz

from cookimport.core.models import HowToStep
from cookimport.parsing.sections import normalize_section_key

_WORD_RE = re.compile(r"[a-z0-9]+")

_LEMMA_OVERRIDES = {
    "floured": "flour",
    "flouring": "flour",
    "flours": "flour",
    "baked": "bake",
    "baking": "baking",
    "boiled": "boil",
    "boiling": "boil",
    "braised": "braise",
    "braising": "braise",
    "fried": "fry",
    "frying": "fry",
    "minced": "mince",
    "mincing": "mince",
    "diced": "dice",
    "dicing": "dice",
    "chopped": "chop",
    "chopping": "chop",
    "sliced": "slice",
    "slicing": "slice",
    "grated": "grate",
    "grating": "grate",
    "grilled": "grill",
    "grilling": "grill",
    "roasted": "roast",
    "roasting": "roast",
    "seared": "sear",
    "searing": "sear",
    "smoked": "smoke",
    "smoking": "smoke",
    "steamed": "steam",
    "steaming": "steam",
    "toasted": "toast",
    "toasting": "toast",
    "shredded": "shred",
    "shredding": "shred",
    "peeled": "peel",
    "peeling": "peel",
    "crushed": "crush",
    "crushing": "crush",
    "zested": "zest",
    "zesting": "zest",
    "juiced": "juice",
    "juicing": "juice",
    "ground": "grind",
    "beaten": "beat",
    "beating": "beat",
    "icing": "icing",
    "seasoned": "season",
    "seasoning": "seasoning",
    "spring": "spring",
    "stuffing": "stuffing",
    "topping": "topping",
    "frosting": "frosting",
    "pudding": "pudding",
}

# Synonyms should use lemmatized tokens (singular, base forms).
_SYNONYM_GROUPS: tuple[tuple[tuple[str, ...], ...], ...] = (
    (("scallion",), ("green", "onion"), ("spring", "onion")),
    (("powder", "sugar"), ("confectioner", "sugar"), ("icing", "sugar")),
    (("baking", "soda"), ("bicarbonate", "of", "soda")),
    (("eggplant",), ("aubergine",)),
    (("zucchini",), ("courgette",)),
    (("arugula",), ("rocket",)),
    (("bell", "pepper"), ("capsicum",)),
    (("chickpea",), ("garbanzo", "bean")),
)

_SYNONYM_MAP: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {}
for _group in _SYNONYM_GROUPS:
    for _phrase in _group:
        _SYNONYM_MAP[_phrase] = tuple(p for p in _group if p != _phrase)

_MAX_SYNONYM_VARIANTS = 6

_FUZZY_MIN_SCORE = 85
_FUZZY_MIN_TOKEN_LEN = 5
_GENERIC_FUZZY_TOKENS = {
    "oil",
    "salt",
    "pepper",
    "water",
    "sugar",
    "flour",
    "butter",
    "egg",
    "eggs",
    "milk",
}

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

# Ingredient category definitions for collective term matching
# Maps category name to (collective_terms, ingredient_keywords)
_INGREDIENT_CATEGORIES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "spices": (
        frozenset({"spices", "spice"}),
        frozenset({
            "cinnamon", "ginger", "cloves", "clove", "nutmeg", "paprika", "cumin",
            "coriander", "cardamom", "turmeric", "cayenne", "allspice", "saffron",
            "anise", "fennel", "caraway", "fenugreek", "mace", "chili", "chilli",
        }),
    ),
    "herbs": (
        frozenset({"herbs", "herb", "fresh herbs"}),
        frozenset({
            "basil", "thyme", "oregano", "parsley", "cilantro", "dill", "mint",
            "rosemary", "sage", "tarragon", "chives", "bay", "marjoram", "chervil",
        }),
    ),
    "seasonings": (
        frozenset({"seasonings", "seasoning"}),
        frozenset({
            "salt", "pepper", "cinnamon", "ginger", "cloves", "nutmeg", "paprika",
            "cumin", "garlic", "onion",
        }),
    ),
}

_SECTION_DROP_LEADING = {"for", "the"}
_SECTION_DROP_TRAILING = {"ingredients"}
_SECTION_SCORE_TIE_EPSILON = 0.2
_INTERNAL_INGREDIENT_INDEX_KEY = "__ingredient_index"


@dataclass(frozen=True)
class Alias:
    tokens: tuple[str, ...]
    source: str

    @property
    def score(self) -> tuple[int, int, int]:
        return (len(self.tokens), sum(len(token) for token in self.tokens), int(self.source == "raw_ingredient_text"))


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


@dataclass(frozen=True)
class StepCandidate:
    """A candidate match between an ingredient and a step."""
    ingredient_index: int
    step_index: int
    alias: Alias
    match_kind: str              # "exact", "semantic", or "fuzzy"
    similarity_score: float      # 0-1.0 similarity (1.0 for exact/semantic)
    match_strength: str           # "strong" or "weak"
    verb_signal: str              # "use", "reference", "split", "neutral"
    context_score: float
    surrounding_tokens: tuple[str, ...]  # For debug
    split_fraction: float | None = None  # e.g., 0.5 for "half"
    split_word: str | None = None


@dataclass
class IngredientAssignment:
    """Final assignment of an ingredient to one or more steps."""
    ingredient_index: int
    assigned_steps: list[int]
    reason: str                   # For debug/explainability
    step_fractions: dict[int, float] | None = None  # step_idx -> fraction (e.g., 0.5)


# Verb classification constants
_USE_VERBS = frozenset({
    "add", "mix", "stir", "fold", "sprinkle", "pour", "whisk", "combine",
    "toss", "season", "top", "drizzle", "incorporate", "blend", "beat",
    "cream", "melt", "dissolve", "rub", "coat", "brush", "scatter",
    "garnish", "finish", "place", "put", "drop", "spoon", "layer", "spread",
    "roll",
    # Cooking verbs where you're adding ingredient to pan/pot - active use
    "fry", "saute", "sear", "brown", "grill", "roast", "bake",
})

_REFERENCE_VERBS = frozenset({
    "cook", "return", "remove", "transfer", "flip", "check", "pierce",
    "set", "let", "allow", "cool", "rest", "heat", "reheat",
    "simmer", "boil", "reduce", "caramelize", "crisp",
})

# Split signals that can appear before OR after the ingredient
_SPLIT_SIGNAL_AFTER = frozenset({
    "remaining", "reserved", "leftover", "divided", "aside",
})

# Split signals that should only be detected BEFORE the ingredient
_SPLIT_SIGNAL_BEFORE = frozenset({
    "reserve", "half", "portion", "divide", "save", "back",
})

# Combined convenience view
_SPLIT_SIGNAL_WORDS = _SPLIT_SIGNAL_AFTER | _SPLIT_SIGNAL_BEFORE

# Fraction words for quantity splitting
_FRACTION_WORDS: dict[str, float] = {
    "half": 0.5,
    "quarter": 0.25,
    "third": 1/3,
}

# "remaining" gets the complement of previously assigned fractions
_REMAINING_WORDS = frozenset({"remaining", "rest", "reserved", "leftover"})

_MAX_STEPS_PER_INGREDIENT = 3  # Cap to prevent runaway
_SPLIT_CONFIDENCE_PENALTY = 0.05
_STRONG_SPLIT_WORDS = frozenset(set(_FRACTION_WORDS.keys()) | set(_REMAINING_WORDS))


def _classify_verb_context(
    step_tokens: list[str],
    match_start: int,
    match_end: int,
) -> tuple[str, float, float | None, str | None]:
    """
    Look at 1-3 tokens before ingredient match to determine verb context.

    Returns (signal, score_adjustment, split_fraction, split_word) where signal is one of:
    - "use": active use verb like "add", "mix", "stir"
    - "reference": mention without active use like "cook", "let rest"
    - "split": language indicating partial use like "reserve", "remaining"
    - "neutral": no clear signal

    split_fraction is the detected fraction (e.g., 0.5 for "half") or None.
    split_word is the triggering token (e.g., "half", "remaining") or None.
    """
    # Look at up to 3 tokens before the match
    context_start = max(0, match_start - 3)
    context_tokens = step_tokens[context_start:match_start]

    # Detect split - only when split word DIRECTLY modifies this ingredient
    # Pattern: "half the croutons" or "remaining croutons" but NOT "remaining croutons, squash"
    # Check 1 token before, or 2 tokens before if token-1 is an article
    _ARTICLES = {"the", "a", "an", "some", "any"}

    split_fraction: float | None = None
    split_signal_found = False
    split_word: str | None = None

    # Get tokens before match
    token_1_before = step_tokens[match_start - 1] if match_start >= 1 else None
    token_2_before = step_tokens[match_start - 2] if match_start >= 2 else None

    # Check for split word at position -1 (immediately before)
    if token_1_before in _SPLIT_SIGNAL_WORDS:
        split_signal_found = True
        split_word = token_1_before
        if token_1_before in _FRACTION_WORDS:
            split_fraction = _FRACTION_WORDS[token_1_before]
        elif token_1_before in _REMAINING_WORDS:
            split_fraction = -1.0
    # Check for split word at position -2 if position -1 is an article
    elif token_1_before in _ARTICLES and token_2_before in _SPLIT_SIGNAL_WORDS:
        split_signal_found = True
        split_word = token_2_before
        if token_2_before in _FRACTION_WORDS:
            split_fraction = _FRACTION_WORDS[token_2_before]
        elif token_2_before in _REMAINING_WORDS:
            split_fraction = -1.0

    if split_signal_found:
        return ("split", 8.0, split_fraction, split_word)

    # Check split signals after ingredient (1 token)
    token_1_after = step_tokens[match_end] if match_end < len(step_tokens) else None
    if token_1_after in _SPLIT_SIGNAL_AFTER:
        if token_1_after in _REMAINING_WORDS:
            split_fraction = -1.0
        return ("split", 8.0, split_fraction, token_1_after)

    # Check for use verbs (immediate context preferred)
    for token in context_tokens:
        if token in _USE_VERBS:
            return ("use", 10.0, split_fraction, None)

    # Check for reference verbs
    for token in context_tokens:
        if token in _REFERENCE_VERBS:
            return ("reference", -5.0, split_fraction, None)

    return ("neutral", 0.0, split_fraction, None)


def _find_match_position(step_tokens: list[str], alias_tokens: tuple[str, ...]) -> tuple[int, int] | None:
    """Find the start and end position of alias tokens in step tokens."""
    if not alias_tokens or len(alias_tokens) > len(step_tokens):
        return None
    for start in range(len(step_tokens) - len(alias_tokens) + 1):
        if step_tokens[start : start + len(alias_tokens)] == list(alias_tokens):
            return (start, start + len(alias_tokens))
    return None


def _collect_all_candidates(
    step_texts: list[str],
    alias_map: dict[int, list[Alias]],
    *,
    lemmatize: bool = False,
    match_kind: str = "exact",
) -> list[StepCandidate]:
    """
    Scan all steps × all ingredients and build StepCandidate for each match.

    Returns flat list of all candidates with metadata for scoring.
    """
    candidates: list[StepCandidate] = []

    for step_index, step_text in enumerate(step_texts):
        step_tokens = _tokenize(step_text, lemmatize=lemmatize)
        if not step_tokens:
            continue

        for ingredient_index, aliases in alias_map.items():
            best_alias = _find_best_alias_match(step_tokens, aliases)
            if best_alias is None:
                continue

            # Find match position for context analysis
            match_pos = _find_match_position(step_tokens, best_alias.tokens)
            if match_pos is None:
                continue

            match_start, match_end = match_pos
            match_strength = "strong" if len(best_alias.tokens) > 1 else "weak"

            # Classify verb context
            verb_signal, context_score, split_fraction, split_word = _classify_verb_context(
                step_tokens, match_start, match_end
            )

            # Capture surrounding tokens for debug
            context_start = max(0, match_start - 3)
            context_end = min(len(step_tokens), match_end + 3)
            surrounding = tuple(step_tokens[context_start:context_end])

            candidates.append(StepCandidate(
                ingredient_index=ingredient_index,
                step_index=step_index,
                alias=best_alias,
                match_kind=match_kind,
                similarity_score=1.0,
                match_strength=match_strength,
                verb_signal=verb_signal,
                context_score=context_score,
                surrounding_tokens=surrounding,
                split_fraction=split_fraction,
                split_word=split_word,
            ))

    return candidates


def _classify_step_verb_context(step_tokens: list[str]) -> tuple[str, float]:
    if any(token in _USE_VERBS for token in step_tokens):
        return ("use", 10.0)
    if any(token in _REFERENCE_VERBS for token in step_tokens):
        return ("reference", -5.0)
    return ("neutral", 0.0)


def _is_fuzzy_eligible(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False
    if all(token in _GENERIC_FUZZY_TOKENS for token in tokens):
        return False
    if len(tokens) == 1 and len(tokens[0]) < _FUZZY_MIN_TOKEN_LEN:
        return False
    return True


def _collect_fuzzy_candidates(
    step_texts: list[str],
    alias_map: dict[int, list[Alias]],
) -> list[StepCandidate]:
    candidates: list[StepCandidate] = []

    for step_index, step_text in enumerate(step_texts):
        step_tokens = _tokenize(step_text, lemmatize=True)
        if not step_tokens:
            continue
        normalized_step = " ".join(step_tokens)
        verb_signal, context_score = _classify_step_verb_context(step_tokens)
        surrounding = tuple(step_tokens)

        for ingredient_index, aliases in alias_map.items():
            best_alias: Alias | None = None
            best_score = 0.0
            for alias in aliases:
                if not _is_fuzzy_eligible(alias.tokens):
                    continue
                alias_text = " ".join(alias.tokens)
                score = fuzz.partial_ratio(
                    alias_text,
                    normalized_step,
                    score_cutoff=_FUZZY_MIN_SCORE,
                )
                if score > best_score:
                    best_score = score
                    best_alias = alias

            if best_alias is None:
                continue

            match_strength = "strong" if len(best_alias.tokens) > 1 else "weak"

            candidates.append(StepCandidate(
                ingredient_index=ingredient_index,
                step_index=step_index,
                alias=best_alias,
                match_kind="fuzzy",
                similarity_score=best_score / 100.0,
                match_strength=match_strength,
                verb_signal=verb_signal,
                context_score=context_score,
                surrounding_tokens=surrounding,
                split_fraction=None,
                split_word=None,
            ))

    return candidates


def _score_candidate(candidate: StepCandidate) -> float:
    """
    Compute a score for a candidate to determine assignment priority.

    Formula:
    - Base: alias score (token count, char length, source preference)
    - + verb signal bonus/penalty (already in context_score)
    - + match strength bonus
    - - step index tiebreaker (prefer earlier steps)
    """
    alias_score = candidate.alias.score
    # Convert tuple score to float: weight by (100*tokens + chars + source_bonus)
    base_score = alias_score[0] * 100 + alias_score[1] + alias_score[2] * 10

    # Add context score (includes verb signal adjustment)
    score = base_score + candidate.context_score

    # Similarity bonus (fuzzy uses real score; exact/semantic are constant)
    score += candidate.similarity_score * 50.0

    # Match strength bonus
    if candidate.match_strength == "strong":
        score += 5.0

    # Step tiebreaker: prefer earlier steps
    score -= candidate.step_index * 0.1

    return score


def _resolve_line_section_key(keys: list[str] | None, index: int) -> str | None:
    if keys is None:
        return None
    if index < 0 or index >= len(keys):
        return None
    value = str(keys[index]).strip()
    if not value:
        return None
    return value


def _resolve_assignments(
    candidates: list[StepCandidate],
    ingredient_count: int,
    ingredient_lines: list[dict[str, Any]],
    *,
    ingredient_section_key_by_line: list[str] | None = None,
    step_section_key_by_step: list[str] | None = None,
) -> list[IngredientAssignment]:
    """
    Resolve which steps each ingredient should be assigned to.

    Default: Pick single best step ("best step wins")
    Exception: Allow multi-step only if split/reserve language detected
    """
    from collections import defaultdict

    # Group candidates by ingredient
    by_ingredient: dict[int, list[StepCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_ingredient[candidate.ingredient_index].append(candidate)

    # First pass: determine best step for each ingredient, tracking fractions
    preliminary_assignments: dict[int, tuple[list[int], str, dict[int, float] | None]] = {}

    for ingredient_index in range(ingredient_count):
        ingredient_candidates = by_ingredient.get(ingredient_index, [])
        exact_candidates = [c for c in ingredient_candidates if c.match_kind == "exact"]
        if exact_candidates:
            ingredient_candidates = exact_candidates
        else:
            semantic_candidates = [c for c in ingredient_candidates if c.match_kind == "semantic"]
            if semantic_candidates:
                ingredient_candidates = semantic_candidates

        if not ingredient_candidates:
            preliminary_assignments[ingredient_index] = ([], "no matches", None)
            continue

        if len(ingredient_candidates) == 1:
            candidate = ingredient_candidates[0]
            step_fractions = None
            if candidate.split_fraction is not None and candidate.split_fraction > 0:
                step_fractions = {candidate.step_index: candidate.split_fraction}
            preliminary_assignments[ingredient_index] = (
                [candidate.step_index],
                "single match",
                step_fractions,
            )
            continue

        # Multiple candidates - check for multi-step eligibility
        # Count candidates with use or split signals
        use_or_split = [c for c in ingredient_candidates if c.verb_signal in ("use", "split")]
        has_strong_split = any(
            c.verb_signal == "split" and c.split_word in _STRONG_SPLIT_WORDS
            for c in ingredient_candidates
        )

        if len(use_or_split) >= 2 and has_strong_split:
            # Allow multi-step assignment
            sorted_candidates = sorted(use_or_split, key=_score_candidate, reverse=True)
            selected = sorted_candidates[:_MAX_STEPS_PER_INGREDIENT]
            assigned_steps = sorted([c.step_index for c in selected])

            # Calculate fractions for split ingredients
            step_fractions = _calculate_split_fractions(selected, assigned_steps)

            preliminary_assignments[ingredient_index] = (
                assigned_steps,
                f"multi-step (strong split language): {len(assigned_steps)} steps",
                step_fractions,
            )
        else:
            # Pick single best candidate
            # But prefer earlier step when multiple "use" verb candidates exist
            scored_candidates = [
                (candidate, _score_candidate(candidate))
                for candidate in ingredient_candidates
            ]
            best, best_score = max(scored_candidates, key=lambda item: item[1])
            ingredient_section_key = _resolve_line_section_key(
                ingredient_section_key_by_line, ingredient_index
            )

            # Section-aware tie-breaker:
            # If scores are near-tied, prefer the candidate in the same section.
            if ingredient_section_key and step_section_key_by_step is not None:
                same_section = [
                    (candidate, score)
                    for candidate, score in scored_candidates
                    if _resolve_line_section_key(step_section_key_by_step, candidate.step_index)
                    == ingredient_section_key
                ]
                if same_section:
                    best_same, best_same_score = max(
                        same_section,
                        key=lambda item: item[1],
                    )
                    if (best_score - best_same_score) <= _SECTION_SCORE_TIE_EPSILON:
                        best, best_score = best_same, best_same_score

            # Check if there's an earlier candidate with "use" verb that should win
            use_verb_candidates = [c for c in ingredient_candidates if c.verb_signal == "use"]
            if len(use_verb_candidates) > 1 and best.verb_signal == "use":
                # Multiple use verbs: prefer earliest (first introduction of ingredient)
                use_pool = use_verb_candidates
                if ingredient_section_key and step_section_key_by_step is not None:
                    same_section_use = [
                        candidate
                        for candidate in use_verb_candidates
                        if _resolve_line_section_key(
                            step_section_key_by_step, candidate.step_index
                        )
                        == ingredient_section_key
                    ]
                    if same_section_use:
                        use_pool = same_section_use

                earliest_use = min(use_pool, key=lambda c: c.step_index)
                prefer_same_section_pool = use_pool is not use_verb_candidates
                if (
                    prefer_same_section_pool
                    and earliest_use.step_index != best.step_index
                ) or (
                    not prefer_same_section_pool
                    and earliest_use.step_index < best.step_index
                ):
                    best = earliest_use
                    reason = f"earliest use verb wins (step {best.step_index})"
                    if prefer_same_section_pool:
                        reason = (
                            f"earliest use verb wins in same section "
                            f"(step {best.step_index})"
                        )
                    preliminary_assignments[ingredient_index] = (
                        [best.step_index],
                        reason,
                        None,
                    )
                    continue

            preliminary_assignments[ingredient_index] = (
                [best.step_index],
                f"best step wins (score={best_score:.1f})",
                None,
            )

    # Second pass: filter out weak (single-token) matches that overlap with strong matches
    # Group by step to find overlapping tokens
    step_to_strong_tokens: dict[int, set[str]] = defaultdict(set)

    for ingredient_index, (assigned_steps, reason, _fractions) in preliminary_assignments.items():
        if not assigned_steps:
            continue
        ing_candidates = by_ingredient.get(ingredient_index, [])
        for candidate in ing_candidates:
            if candidate.step_index in assigned_steps and candidate.match_strength == "strong":
                step_to_strong_tokens[candidate.step_index].update(candidate.alias.tokens)

    # Now filter: weak matches whose tokens are covered by strong matches in same step
    assignments: list[IngredientAssignment] = []
    for ingredient_index in range(ingredient_count):
        assigned_steps, reason, step_fractions = preliminary_assignments[ingredient_index]
        if not assigned_steps:
            assignments.append(IngredientAssignment(
                ingredient_index=ingredient_index,
                assigned_steps=[],
                reason=reason,
            ))
            continue

        # Check if this is a weak match that overlaps with a strong match
        ing_candidates = by_ingredient.get(ingredient_index, [])
        best_candidate = next(
            (c for c in ing_candidates if c.step_index == assigned_steps[0]),
            None
        )
        if best_candidate and best_candidate.match_strength == "weak":
            # Check if tokens overlap with strong matches in same step
            for step_idx in assigned_steps:
                strong_tokens = step_to_strong_tokens.get(step_idx, set())
                if set(best_candidate.alias.tokens) & strong_tokens:
                    # This weak match overlaps with a strong match - exclude it
                    assignments.append(IngredientAssignment(
                        ingredient_index=ingredient_index,
                        assigned_steps=[],
                        reason="excluded: overlaps strong match",
                    ))
                    break
            else:
                # No overlap found, keep the assignment
                assignments.append(IngredientAssignment(
                    ingredient_index=ingredient_index,
                    assigned_steps=assigned_steps,
                    reason=reason,
                    step_fractions=step_fractions,
                ))
        else:
            assignments.append(IngredientAssignment(
                ingredient_index=ingredient_index,
                assigned_steps=assigned_steps,
                reason=reason,
                step_fractions=step_fractions,
            ))

    return assignments


def _calculate_split_fractions(
    candidates: list[StepCandidate],
    assigned_steps: list[int],
) -> dict[int, float] | None:
    """
    Calculate the fraction of ingredient to assign to each step.

    For "half" + "remaining" pattern: 0.5 each
    For explicit fractions: use those values
    """
    if len(assigned_steps) < 2:
        return None

    # Build step -> fraction map from candidates
    step_to_candidate = {c.step_index: c for c in candidates}

    # Collect known fractions
    known_fractions: dict[int, float] = {}
    remaining_steps: list[int] = []

    for step_idx in assigned_steps:
        candidate = step_to_candidate.get(step_idx)
        if candidate and candidate.split_fraction is not None:
            if candidate.split_fraction == -1.0:  # "remaining" sentinel
                remaining_steps.append(step_idx)
            else:
                known_fractions[step_idx] = candidate.split_fraction

    # If no fractions detected, return None (no quantity splitting)
    if not known_fractions and not remaining_steps:
        return None

    # Calculate remaining fraction
    used_fraction = sum(known_fractions.values())
    leftover = 1.0 - used_fraction

    # Distribute remaining among "remaining" steps
    if remaining_steps:
        per_remaining = leftover / len(remaining_steps)
        for step_idx in remaining_steps:
            known_fractions[step_idx] = per_remaining

    # If we still don't have fractions for all steps, distribute evenly
    if len(known_fractions) < len(assigned_steps):
        missing_steps = [s for s in assigned_steps if s not in known_fractions]
        if missing_steps:
            # Recalculate to ensure fractions sum to 1.0
            per_step = 1.0 / len(assigned_steps)
            return {s: per_step for s in assigned_steps}

    return known_fractions if known_fractions else None


def _build_final_step_lines(
    assignments: list[IngredientAssignment],
    ingredient_lines: list[dict[str, Any]],
    step_count: int,
) -> list[list[dict[str, Any]]]:
    """
    Create per-step ingredient lists from assignments.

    Deep-copies ingredients and maintains original ingredient order within each step.
    When split fractions are detected, adjusts the quantity accordingly.
    """
    # Build step -> (ingredient_index, fraction, split_penalty) mapping
    step_ingredients: dict[int, list[tuple[int, float | None, bool]]] = {i: [] for i in range(step_count)}

    for assignment in assignments:
        is_split = len(assignment.assigned_steps) > 1
        for step_idx in assignment.assigned_steps:
            if 0 <= step_idx < step_count:
                fraction = None
                if assignment.step_fractions:
                    fraction = assignment.step_fractions.get(step_idx)
                step_ingredients[step_idx].append((assignment.ingredient_index, fraction, is_split))

    # Sort ingredient indices within each step to maintain original order
    for step_idx in step_ingredients:
        step_ingredients[step_idx].sort(key=lambda x: x[0])

    # Build final result with deep copies and fraction-adjusted quantities
    results: list[list[dict[str, Any]]] = []
    for step_idx in range(step_count):
        step_lines: list[dict[str, Any]] = []
        for ing_idx, fraction, is_split in step_ingredients[step_idx]:
            line = ingredient_lines[ing_idx]
            if line.get("quantity_kind") != "section_header":
                line_copy = copy.deepcopy(line)
                line_copy[_INTERNAL_INGREDIENT_INDEX_KEY] = ing_idx
                # Apply fraction to quantity if detected
                if fraction is not None and "input_qty" in line_copy:
                    original_qty = line_copy.get("input_qty")
                    if original_qty is not None and isinstance(original_qty, (int, float)):
                        line_copy["input_qty"] = original_qty * fraction
                if is_split:
                    confidence = line_copy.get("confidence")
                    if isinstance(confidence, (int, float)):
                        line_copy["confidence"] = max(
                            0.0,
                            round(confidence - _SPLIT_CONFIDENCE_PENALTY, 3),
                        )
                step_lines.append(line_copy)
        results.append(step_lines)

    return results


@dataclass
class DebugInfo:
    """Debug information from ingredient assignment."""
    candidates: list[StepCandidate]
    assignments: list[IngredientAssignment]
    group_assignments: dict[int, list[int]]  # step_idx -> ingredient indices from groups
    all_ingredients_steps: list[int]  # step indices with "all ingredients" phrase


def assign_ingredient_lines_to_steps(
    steps: list[str | HowToStep],
    ingredient_lines: list[dict[str, Any]],
    *,
    ingredient_section_key_by_line: list[str] | None = None,
    step_section_key_by_step: list[str] | None = None,
    debug: bool = False,
) -> list[list[dict[str, Any]]] | tuple[list[list[dict[str, Any]]], DebugInfo]:
    """
    Return a per-step list of ingredient lines in original order.

    Uses a two-phase algorithm:
    1. Candidate Detection: Scan all steps, collect all candidate matches with metadata
    2. Global Resolution: For each ingredient, pick single best step (or multi-step if split language)

    Args:
        steps: List of step texts or HowToStep objects
        ingredient_lines: List of ingredient dicts with raw_ingredient_text, quantity_kind, etc.
        ingredient_section_key_by_line: Optional section keys per ingredient line.
            Accepts either:
            - len == len(ingredient_lines), or
            - len == number of non-header ingredient lines.
        step_section_key_by_step: Optional section keys per step (len == len(steps)).
        debug: If True, return (results, DebugInfo) tuple with assignment trace

    Returns:
        Per-step list of ingredient dicts, or (results, debug_info) if debug=True
    """
    step_texts = [_coerce_step_text(step) for step in steps]
    if not step_texts:
        if debug:
            return [], DebugInfo([], [], {}, [])
        return []
    if not ingredient_lines:
        empty_result = [[] for _ in step_texts]
        if debug:
            return empty_result, DebugInfo([], [], {}, [])
        return empty_result

    groups = _build_groups(ingredient_lines)
    alias_map = _build_alias_map(ingredient_lines)
    non_header_indices = [
        idx
        for idx, line in enumerate(ingredient_lines)
        if line.get("quantity_kind") != "section_header"
    ]
    normalized_ingredient_section_keys = _normalize_ingredient_section_keys(
        ingredient_lines,
        ingredient_section_key_by_line,
    )
    normalized_step_section_keys = _normalize_step_section_keys(
        len(step_texts),
        step_section_key_by_step,
    )
    has_section_scope = _has_multiple_section_scope(
        normalized_ingredient_section_keys,
        normalized_step_section_keys,
    )

    # Debug tracking
    group_assignments: dict[int, list[int]] = {}
    all_ingredients_steps: list[int] = []

    # Phase 1: Collect all candidates using two-phase algorithm
    candidates = _collect_all_candidates(step_texts, alias_map, match_kind="exact")

    matched_indices = {candidate.ingredient_index for candidate in candidates}
    semantic_targets = set(alias_map.keys()) - matched_indices
    if semantic_targets:
        semantic_alias_map = _build_alias_map(
            ingredient_lines,
            lemmatize=True,
            apply_synonyms=True,
            include_indices=semantic_targets,
        )
        semantic_candidates = _collect_all_candidates(
            step_texts,
            semantic_alias_map,
            lemmatize=True,
            match_kind="semantic",
        )
        candidates.extend(semantic_candidates)

    matched_indices = {candidate.ingredient_index for candidate in candidates}
    fuzzy_targets = set(alias_map.keys()) - matched_indices
    if fuzzy_targets:
        fuzzy_alias_map = _build_alias_map(
            ingredient_lines,
            lemmatize=True,
            apply_synonyms=True,
            include_indices=fuzzy_targets,
        )
        fuzzy_candidates = _collect_fuzzy_candidates(step_texts, fuzzy_alias_map)
        candidates.extend(fuzzy_candidates)

    # Phase 2: Resolve assignments (best step wins, with multi-step exception for split language)
    assignments = _resolve_assignments(
        candidates,
        len(ingredient_lines),
        ingredient_lines,
        ingredient_section_key_by_line=normalized_ingredient_section_keys,
        step_section_key_by_step=normalized_step_section_keys,
    )

    # Build initial results from two-phase assignments
    results = _build_final_step_lines(assignments, ingredient_lines, len(step_texts))

    # Now handle special cases: section header groups and "all ingredients" phrases
    # These override/supplement the two-phase results
    for step_idx, step_text in enumerate(step_texts):
        step_tokens = _tokenize(step_text)
        normalized_step = " ".join(step_tokens)
        if not step_tokens:
            continue

        # "All ingredients" phrase overrides everything for this step
        if _has_all_ingredients_phrase(normalized_step):
            all_ingredients_steps.append(step_idx)
            include_indices = list(non_header_indices)
            if has_section_scope:
                step_section_key = _resolve_line_section_key(
                    normalized_step_section_keys,
                    step_idx,
                )
                scoped_indices = _indices_for_section(
                    include_indices,
                    normalized_ingredient_section_keys,
                    step_section_key,
                )
                if scoped_indices:
                    include_indices = scoped_indices
            results[step_idx] = _build_step_lines(include_indices, ingredient_lines)
            continue

        # Section header group matching adds to results (doesn't replace)
        for group in groups:
            if _step_mentions_group(step_tokens, group.aliases):
                if step_idx not in group_assignments:
                    group_assignments[step_idx] = []
                group_assignments[step_idx].extend(group.indices)

                # Merge group indices into this step's results
                existing_indices = {
                    idx
                    for idx in (_result_line_index(result_line) for result_line in results[step_idx])
                    if idx is not None
                }
                for ing_idx in group.indices:
                    if ing_idx not in existing_indices:
                        line = ingredient_lines[ing_idx]
                        if line.get("quantity_kind") != "section_header":
                            line_copy = copy.deepcopy(line)
                            line_copy[_INTERNAL_INGREDIENT_INDEX_KEY] = ing_idx
                            results[step_idx].append(line_copy)

        # Re-sort by original ingredient order
        results[step_idx] = _sort_step_lines_by_index(results[step_idx], ingredient_lines)

    # Fallback pass: assign unmatched ingredients via collective term matching
    # Find which ingredients are not yet assigned to any step
    assigned_indices = _collect_assigned_indices(results, ingredient_lines)

    unassigned_indices = [
        idx for idx in non_header_indices
        if idx not in assigned_indices
    ]

    # For each unassigned ingredient, check if it belongs to a category and
    # if any step mentions that category's collective term
    for ing_idx in unassigned_indices:
        line = ingredient_lines[ing_idx]
        raw_text = line.get("raw_ingredient_text") or line.get("raw_text") or ""
        category = _get_ingredient_category(raw_text)
        if not category:
            continue

        step_candidates = list(range(len(step_texts)))
        if has_section_scope:
            ingredient_key = _resolve_line_section_key(
                normalized_ingredient_section_keys,
                ing_idx,
            )
            if ingredient_key:
                same_section_steps = [
                    step_idx
                    for step_idx in step_candidates
                    if _resolve_line_section_key(normalized_step_section_keys, step_idx)
                    == ingredient_key
                ]
                if same_section_steps:
                    remaining_steps = [
                        step_idx
                        for step_idx in step_candidates
                        if step_idx not in same_section_steps
                    ]
                    step_candidates = same_section_steps + remaining_steps

        # Find the first step that mentions this category's collective term
        for step_idx in step_candidates:
            step_text = step_texts[step_idx]
            if _step_has_collective_term(step_text, category):
                # Add ingredient to this step if not already there
                existing_indices = {
                    idx
                    for idx in (_result_line_index(result_line) for result_line in results[step_idx])
                    if idx is not None
                }
                if ing_idx not in existing_indices:
                    line_copy = copy.deepcopy(line)
                    line_copy[_INTERNAL_INGREDIENT_INDEX_KEY] = ing_idx
                    results[step_idx].append(line_copy)
                break

    # Final re-sort for any steps that got new ingredients
    for step_idx in range(len(results)):
        results[step_idx] = _sort_step_lines_by_index(results[step_idx], ingredient_lines)

    cleaned_results = _strip_internal_ingredient_indices(results)

    if debug:
        debug_info = DebugInfo(
            candidates=candidates,
            assignments=assignments,
            group_assignments=group_assignments,
            all_ingredients_steps=all_ingredients_steps,
        )
        return cleaned_results, debug_info

    return cleaned_results


def _normalize_ingredient_section_keys(
    ingredient_lines: list[dict[str, Any]],
    section_keys: list[str] | None,
) -> list[str] | None:
    if section_keys is None:
        return None
    normalized = [str(value).strip() for value in section_keys]
    if not normalized:
        return None

    if len(normalized) == len(ingredient_lines):
        return [_normalize_key(value) or "main" for value in normalized]

    non_header_indices = [
        idx
        for idx, line in enumerate(ingredient_lines)
        if line.get("quantity_kind") != "section_header"
    ]
    if len(normalized) != len(non_header_indices):
        return None

    expanded: list[str] = []
    current_key = "main"
    cursor = 0
    for idx, line in enumerate(ingredient_lines):
        if line.get("quantity_kind") == "section_header":
            label = line.get("raw_ingredient_text") or line.get("raw_text") or ""
            header_key = _normalize_key(str(label))
            if header_key:
                current_key = header_key
            expanded.append(current_key)
            continue
        value = normalized[cursor]
        cursor += 1
        resolved = _normalize_key(value) or current_key
        current_key = resolved
        expanded.append(resolved)
    return expanded


def _normalize_step_section_keys(
    step_count: int,
    section_keys: list[str] | None,
) -> list[str] | None:
    if section_keys is None:
        return None
    if len(section_keys) != step_count:
        return None
    normalized = [_normalize_key(str(value)) for value in section_keys]
    return [value or "main" for value in normalized]


def _normalize_key(value: str) -> str:
    key = normalize_section_key(value)
    if key:
        return key
    return value.strip().lower()


def _has_multiple_section_scope(
    ingredient_keys: list[str] | None,
    step_keys: list[str] | None,
) -> bool:
    ingredient_unique = {key for key in (ingredient_keys or []) if key}
    step_unique = {key for key in (step_keys or []) if key}
    return len(ingredient_unique) > 1 and len(step_unique) > 1


def _indices_for_section(
    indices: list[int],
    ingredient_section_keys: list[str] | None,
    section_key: str | None,
) -> list[int]:
    if ingredient_section_keys is None or not section_key:
        return []
    return [
        idx
        for idx in indices
        if _resolve_line_section_key(ingredient_section_keys, idx) == section_key
    ]


def _result_line_index(line: dict[str, Any]) -> int | None:
    value = line.get(_INTERNAL_INGREDIENT_INDEX_KEY)
    if isinstance(value, int):
        return value
    return None


def _sort_step_lines_by_index(
    step_lines: list[dict[str, Any]],
    ingredient_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        step_lines,
        key=lambda line: _result_line_index(line) if _result_line_index(line) is not None else len(ingredient_lines),
    )


def _collect_assigned_indices(
    results: list[list[dict[str, Any]]],
    ingredient_lines: list[dict[str, Any]],
) -> set[int]:
    assigned: set[int] = set()
    for step_lines in results:
        for line in step_lines:
            idx = _result_line_index(line)
            if idx is not None:
                assigned.add(idx)
                continue
            # Fallback for external callers that pass prebuilt lines without index tags.
            for origin_idx, origin in enumerate(ingredient_lines):
                if origin.get("raw_ingredient_text") == line.get("raw_ingredient_text"):
                    assigned.add(origin_idx)
                    break
    return assigned


def _strip_internal_ingredient_indices(
    results: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    cleaned: list[list[dict[str, Any]]] = []
    for step_lines in results:
        cleaned_step: list[dict[str, Any]] = []
        for line in step_lines:
            line_copy = dict(line)
            line_copy.pop(_INTERNAL_INGREDIENT_INDEX_KEY, None)
            cleaned_step.append(line_copy)
        cleaned.append(cleaned_step)
    return cleaned


def _coerce_step_text(step: str | HowToStep) -> str:
    if isinstance(step, HowToStep):
        return step.text
    return str(step) if step is not None else ""


def _undouble_consonant(token: str) -> str:
    if len(token) >= 2 and token[-1] == token[-2] and token[-1] not in "aeiou":
        return token[:-1]
    return token


def _lemmatize_token(token: str) -> str:
    if not token or token.isdigit() or len(token) <= 3:
        return token
    override = _LEMMA_OVERRIDES.get(token)
    if override:
        return override
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ing") and len(token) > 5:
        return _undouble_consonant(token[:-3])
    if token.endswith("ed") and len(token) > 4:
        return _undouble_consonant(token[:-2])
    if token.endswith("es") and len(token) > 4 and token.endswith(("ches", "shes")):
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _lemmatize_tokens(tokens: Iterable[str]) -> list[str]:
    return [_lemmatize_token(token) for token in tokens]


def _expand_synonym_variants(tokens: tuple[str, ...]) -> list[tuple[str, ...]]:
    if not tokens or not _SYNONYM_MAP:
        return [tokens]
    variants: set[tuple[str, ...]] = {tokens}
    queue: list[tuple[str, ...]] = [tokens]
    while queue and len(variants) < _MAX_SYNONYM_VARIANTS:
        current = queue.pop()
        for phrase, replacements in _SYNONYM_MAP.items():
            phrase_len = len(phrase)
            if phrase_len == 0 or phrase_len > len(current):
                continue
            for start in range(len(current) - phrase_len + 1):
                if current[start : start + phrase_len] != phrase:
                    continue
                for replacement in replacements:
                    candidate = current[:start] + replacement + current[start + phrase_len :]
                    if candidate in variants:
                        continue
                    variants.add(candidate)
                    if len(variants) >= _MAX_SYNONYM_VARIANTS:
                        break
                    queue.append(candidate)
                if len(variants) >= _MAX_SYNONYM_VARIANTS:
                    break
            if len(variants) >= _MAX_SYNONYM_VARIANTS:
                break
    return list(variants)


def _add_alias_variants(
    aliases: list[Alias],
    seen: set[tuple[str, ...]],
    tokens: tuple[str, ...],
    source: str,
    *,
    apply_synonyms: bool = False,
) -> None:
    if not tokens:
        return
    if tokens not in seen:
        aliases.append(Alias(tokens=tokens, source=source))
        seen.add(tokens)
    if not apply_synonyms:
        return
    for variant in _expand_synonym_variants(tokens):
        if variant in seen:
            continue
        aliases.append(Alias(tokens=variant, source=f"{source}_synonym"))
        seen.add(variant)


def _tokenize(text: str, *, lemmatize: bool = False) -> list[str]:
    if not text:
        return []
    tokens = _WORD_RE.findall(text.lower())
    if lemmatize:
        return _lemmatize_tokens(tokens)
    return tokens


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


def _build_aliases(
    line: dict[str, Any],
    *,
    lemmatize: bool = False,
    apply_synonyms: bool = False,
) -> list[Alias]:
    aliases: list[Alias] = []
    seen: set[tuple[str, ...]] = set()

    raw_ingredient_text = line.get("raw_ingredient_text") or ""
    input_tokens = _filter_alias_tokens(_tokenize(raw_ingredient_text), drop_units=False)
    if lemmatize:
        input_tokens = _lemmatize_tokens(input_tokens)
    if input_tokens:
        alias_tokens = tuple(input_tokens)
        _add_alias_variants(
            aliases,
            seen,
            alias_tokens,
            "raw_ingredient_text",
            apply_synonyms=apply_synonyms,
        )

    raw_text = line.get("raw_text") or ""
    if raw_text:
        raw_tokens = _filter_alias_tokens(
            _tokenize(_clean_raw_text(raw_text)),
            drop_units=True,
        )
        if lemmatize:
            raw_tokens = _lemmatize_tokens(raw_tokens)
        if raw_tokens:
            alias_tokens = tuple(raw_tokens)
            _add_alias_variants(
                aliases,
                seen,
                alias_tokens,
                "raw_text",
                apply_synonyms=apply_synonyms,
            )

    if len(input_tokens) > 1:
        # Add head alias (first token) - e.g., "sage" for "sage leaves"
        head = (input_tokens[0],)
        _add_alias_variants(
            aliases,
            seen,
            head,
            "head",
            apply_synonyms=apply_synonyms,
        )

        # Add tail alias (last token) - e.g., "leaves" for "sage leaves"
        tail = (input_tokens[-1],)
        _add_alias_variants(
            aliases,
            seen,
            tail,
            "tail",
            apply_synonyms=apply_synonyms,
        )

    return aliases


def _build_alias_map(
    ingredient_lines: list[dict[str, Any]],
    *,
    lemmatize: bool = False,
    apply_synonyms: bool = False,
    include_indices: set[int] | None = None,
) -> dict[int, list[Alias]]:
    alias_map: dict[int, list[Alias]] = {}
    for idx, line in enumerate(ingredient_lines):
        if line.get("quantity_kind") == "section_header":
            continue
        if include_indices is not None and idx not in include_indices:
            continue
        alias_map[idx] = _build_aliases(
            line,
            lemmatize=lemmatize,
            apply_synonyms=apply_synonyms,
        )
    return alias_map


def _build_groups(ingredient_lines: list[dict[str, Any]]) -> list[IngredientGroup]:
    groups: list[IngredientGroup] = []
    current_group: IngredientGroup | None = None

    for idx, line in enumerate(ingredient_lines):
        if line.get("quantity_kind") == "section_header":
            label = line.get("raw_ingredient_text") or line.get("raw_text") or ""
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


def _get_ingredient_category(ingredient_text: str) -> str | None:
    """Determine if an ingredient belongs to a category like 'spices' or 'herbs'.

    Returns the category name if found, None otherwise.
    """
    lower = ingredient_text.lower()
    tokens = set(_WORD_RE.findall(lower))
    for category, (_, keywords) in _INGREDIENT_CATEGORIES.items():
        if tokens & keywords:
            return category
    return None


def _step_has_collective_term(step_text: str, category: str) -> bool:
    """Check if a step mentions a collective term for an ingredient category.

    E.g., for category 'spices', checks if step contains 'spices' or 'spice'.
    """
    if category not in _INGREDIENT_CATEGORIES:
        return False
    collective_terms, _ = _INGREDIENT_CATEGORIES[category]
    lower = step_text.lower()
    for term in collective_terms:
        # Match as whole word
        if re.search(rf"\b{re.escape(term)}\b", lower):
            return True
    return False


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
    lines: list[dict[str, Any]] = []
    for idx, line in enumerate(ingredient_lines):
        if idx not in include_set or line.get("quantity_kind") == "section_header":
            continue
        line_copy = copy.deepcopy(line)
        line_copy[_INTERNAL_INGREDIENT_INDEX_KEY] = idx
        lines.append(line_copy)
    return lines
