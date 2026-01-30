"""Recipe text classifier for categorizing text as ingredient, instruction, or other.

This module provides classification of recipe text lines using pattern-based
heuristics. The heuristics are tuned for typical recipe content and provide
reliable classification without ML dependencies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of classifying a text line."""

    text: str
    label: Literal["ingredient", "instruction", "other"]
    confidence: float
    scores: dict[str, float]


# Patterns for ingredient detection
QUANTITY_PATTERN = re.compile(
    r"""^
    \s*
    (?:
        (?:\d+\s*[-/]\s*)?\d+          # Numbers like 1, 1/2, 1-2
        |[¼½¾⅓⅔⅛⅜⅝⅞]                   # Unicode fractions
        |one|two|three|four|five|six|seven|eight|nine|ten
        |a\s+(?:few|handful|pinch|dash|splash)
    )
    \s*
    """,
    re.IGNORECASE | re.VERBOSE,
)

UNIT_PATTERN = re.compile(
    r"""
    (?:
        cups?|c\.|
        tablespoons?|tbsp?\.?|tbs?\.?|T\.|
        teaspoons?|tsp?\.?|t\.|
        ounces?|oz\.?|
        pounds?|lbs?\.?|
        grams?|g\.|
        kilograms?|kg\.?|
        milliliters?|ml\.?|
        liters?|l\.|
        pints?|pt\.?|
        quarts?|qt\.?|
        gallons?|gal\.?|
        sticks?|
        cans?|
        packages?|pkgs?\.?|
        bunche?s?|
        heads?|
        cloves?|
        slices?|
        pieces?|
        sprigs?|
        stalks?|
        leaves|
        medium|large|small|
        whole
    )
    (?:\s|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

COMMON_INGREDIENTS = re.compile(
    r"""
    (?:
        salt|pepper|sugar|flour|butter|oil|water|milk|cream|eggs?|
        garlic|onion|tomato|chicken|beef|pork|fish|rice|pasta|
        cheese|bread|lemon|lime|vinegar|wine|broth|stock|
        vanilla|cinnamon|cumin|paprika|oregano|basil|thyme|parsley|
        baking\s+(?:soda|powder)|yeast|honey|maple\s+syrup|
        soy\s+sauce|olive\s+oil|vegetable\s+oil|coconut\s+oil
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Ingredient phrases without quantities
INGREDIENT_PHRASE_PATTERN = re.compile(
    r"""^
    \s*
    (?:
        (?:fresh(?:ly)?|ground|chopped|minced|dried|frozen|canned)\s+\w+|
        \w+(?:\s+and\s+\w+)?\s+to\s+taste|
        (?:cooking|vegetable|olive|canola)\s+(?:oil|spray)|
        (?:kosher|sea|table)\s+salt|
        (?:black|white|cayenne)\s+pepper|
        (?:fresh|dried)\s+(?:herbs?|spices?)
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Patterns for instruction detection
INSTRUCTION_VERBS = re.compile(
    r"""^
    \s*
    (?:\d+[.)]\s*)?  # Optional step number
    (?:
        preheat|heat|bring|make|prepare|
        mix|stir|whisk|beat|blend|combine|fold|
        add|pour|place|put|set|arrange|
        cook|bake|roast|fry|grill|broil|sear|saute|sauté|
        simmer|boil|steam|braise|poach|
        chop|slice|dice|mince|cut|trim|peel|grate|shred|
        season|sprinkle|drizzle|brush|coat|cover|
        let|allow|leave|rest|cool|chill|refrigerate|freeze|
        remove|drain|strain|transfer|flip|turn|
        serve|garnish|top|finish|enjoy|
        repeat|continue|check|test|adjust|taste|
        meanwhile|next|then|finally|
        using|working|starting|beginning
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

INSTRUCTION_INDICATORS = re.compile(
    r"""
    (?:
        until\s+(?:golden|soft|tender|done|heated|melted|smooth)|
        for\s+\d+\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?)|
        at\s+\d+\s*(?:degrees?|°|F|C)|
        over\s+(?:medium|high|low)\s+heat|
        to\s+(?:a\s+)?(?:boil|simmer)|
        in\s+(?:a|the)\s+(?:oven|pan|pot|bowl|skillet|mixer)|
        degrees?\s*(?:F|C|fahrenheit|celsius)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Patterns for "other" (headings, narratives, etc.)
HEADER_PATTERN = re.compile(
    r"""^
    \s*
    (?:
        ingredients?|instructions?|directions?|method|steps?|
        preparation|prep\s+time|cook\s+time|total\s+time|
        serves?|servings?|yield|makes?|
        notes?|tips?|variations?|substitutions?|
        equipment|tools|
        nutrition(?:al)?\s*(?:info(?:rmation)?|facts?)?
    )
    \s*:?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

NARRATIVE_INDICATORS = re.compile(
    r"""
    (?:
        ^(?:this|my|our|the|i|we)\s+(?:recipe|dish)|
        (?:remember|recall|learned|taught|grandmother|mother|family)|
        (?:favorite|love|enjoy|delicious|amazing|wonderful)|
        (?:first\s+time|years?\s+ago|growing\s+up)|
        (?:perfect\s+for|great\s+for|ideal\s+for)|
        (?:origin(?:ally)?|tradition(?:ally)?|authentic)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_ingredient_like(text: str) -> tuple[bool, float]:
    """Check if text looks like an ingredient line.

    Returns:
        Tuple of (is_ingredient, confidence_score)
    """
    text = text.strip()
    if not text or len(text) < 2:
        return False, 0.0

    score = 0.0

    # Strong signals
    if QUANTITY_PATTERN.match(text):
        score += 0.4

    if UNIT_PATTERN.search(text):
        score += 0.3

    if COMMON_INGREDIENTS.search(text):
        score += 0.2

    # Ingredient phrases without quantities (e.g., "salt and pepper to taste")
    if INGREDIENT_PHRASE_PATTERN.match(text):
        score += 0.5

    # Weak signals
    words = text.split()
    if len(words) <= 6:  # Ingredients are typically short
        score += 0.1

    # Negative signals
    if text.endswith(".") and len(words) > 8:
        score -= 0.2  # Long sentences ending in period are likely not ingredients

    if INSTRUCTION_VERBS.match(text):
        score -= 0.3  # Starts with instruction verb

    return score >= 0.4, min(max(score, 0.0), 1.0)


def _is_instruction_like(text: str) -> tuple[bool, float]:
    """Check if text looks like an instruction line.

    Returns:
        Tuple of (is_instruction, confidence_score)
    """
    text = text.strip()
    if not text or len(text) < 5:
        return False, 0.0

    score = 0.0

    # Strong signals
    if INSTRUCTION_VERBS.match(text):
        score += 0.5

    if INSTRUCTION_INDICATORS.search(text):
        score += 0.3

    # Medium signals
    words = text.split()
    if len(words) >= 5 and text.endswith("."):
        score += 0.1  # Complete sentences are likely instructions

    # Step numbering
    if re.match(r"^\s*(?:\d+[.):]|\*|•|-)\s+\w", text):
        score += 0.1

    # Negative signals
    if QUANTITY_PATTERN.match(text) and len(words) <= 5:
        score -= 0.3  # Short lines starting with quantities are likely ingredients

    return score >= 0.4, min(max(score, 0.0), 1.0)


def _is_other(text: str) -> tuple[bool, float]:
    """Check if text is likely a header, narrative, or other non-recipe content.

    Returns:
        Tuple of (is_other, confidence_score)
    """
    text = text.strip()
    if not text:
        return True, 1.0

    score = 0.0

    # Strong signals for "other"
    if HEADER_PATTERN.match(text):
        return True, 0.9

    if NARRATIVE_INDICATORS.search(text):
        score += 0.4

    # Very short or very long text
    words = text.split()
    if len(words) <= 2 and not QUANTITY_PATTERN.match(text):
        score += 0.2  # Very short, likely a header or label

    if len(words) > 30:
        score += 0.2  # Very long, likely narrative

    return score >= 0.4, min(max(score, 0.0), 1.0)


def classify_lines(lines: list[str]) -> list[ClassificationResult]:
    """Classify text lines as ingredient, instruction, or other.

    Uses pattern-based heuristics tuned for recipe content.

    Args:
        lines: List of text lines to classify.

    Returns:
        List of ClassificationResult objects with labels and confidence scores.
    """
    results = []

    for line in lines:
        text = line.strip()

        # Check each category
        is_ing, ing_score = _is_ingredient_like(text)
        is_ins, ins_score = _is_instruction_like(text)
        is_oth, oth_score = _is_other(text)

        # Normalize scores
        total = ing_score + ins_score + oth_score
        if total > 0:
            ing_score /= total
            ins_score /= total
            oth_score /= total
        else:
            # Default to "other" if no signals
            oth_score = 1.0

        # Determine label based on highest score
        if is_ing and ing_score >= ins_score and ing_score >= oth_score:
            label = "ingredient"
            confidence = ing_score
        elif is_ins and ins_score >= ing_score and ins_score >= oth_score:
            label = "instruction"
            confidence = ins_score
        else:
            label = "other"
            confidence = oth_score

        results.append(
            ClassificationResult(
                text=line,
                label=label,
                confidence=confidence,
                scores={
                    "ingredient": ing_score,
                    "instruction": ins_score,
                    "other": oth_score,
                },
            )
        )

    return results


def classifier_available() -> bool:
    """Check if classifier is available. Always returns True for heuristic classifier."""
    return True
