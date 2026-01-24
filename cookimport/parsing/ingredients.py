"""Ingredient line parsing using Ingredient Parser."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

from ingredient_parser import parse_ingredient
from ingredient_parser.dataclasses import ParsedIngredient, IngredientAmount


_APPROXIMATE_PATTERNS = (
    re.compile(r"\bto taste\b"),
    re.compile(r"\bas needed\b"),
    re.compile(r"\bas desired\b"),
    re.compile(r"\bas required\b"),
    re.compile(r"\bfor serving\b"),
    re.compile(r"\bfor garnish\b"),
    re.compile(r"\bfor greasing\b"),
    re.compile(r"\bfor frying\b"),
    re.compile(r"\bfor the pan\b"),
    re.compile(r"\bfor pan\b"),
    re.compile(r"\bto grease\b"),
    re.compile(r"\bto oil\b"),
    re.compile(r"\boil\b.*\bpan\b"),
)


def parse_ingredient_line(text: str) -> dict[str, Any]:
    """Parse an ingredient string into structured components.

    Uses the Ingredient Parser library (https://github.com/strangetom/ingredient-parser, https://ingredient-parser.readthedocs.io/en/latest/) for NLP-based parsing, then
    normalizes the output for our schema.

    Args:
        text: Raw ingredient string like "3 stalks celery, sliced"

    Returns:
        Dict with:
            quantity_kind: "exact", "approximate", "unquantified", or "section_header"
            input_qty: float or None
            input_unit_id: str (always blank, for future use)
            ingredient_id: str (always blank, for future use)
            raw_unit_text: str or None (the parsed unit text)
            raw_ingredient_text: str or None (the ingredient name)
            preparation: str or None
            note: str or None
            raw_text: str (original input)
            is_optional: bool
            confidence: float (average confidence, 0.0 if unparseable)
    """
    text = text.strip()
    if not text:
        return _empty_result(text)

    # Check for section header before parsing
    if _is_section_header_heuristic(text):
        return _section_header_result(text)

    try:
        parsed = parse_ingredient(text, string_units=True)
    except Exception:
        # If parsing fails completely, return unquantified with raw text
        return _fallback_result(text)

    # Check if parsed result looks like a section header
    if _is_section_header_from_parsed(text, parsed):
        return _section_header_result(text)

    # Extract structured data
    return _build_result(text, parsed)


def _is_section_header_heuristic(text: str) -> bool:
    """Quick heuristic check for obvious section headers before parsing.

    Matches patterns like:
    - ALL CAPS single words: "FILLING", "MARINADE", "GARNISH"
    - ALL CAPS with colon: "FOR THE SAUCE:"
    - Title case section names: "For the Filling"
    - Known section keywords: "Garnish", "Marinade", etc.
    """
    stripped = text.strip().rstrip(":")

    # Single word, all caps, no numbers
    if re.match(r"^[A-Z][A-Z\s]{0,20}$", stripped) and not any(c.isdigit() for c in stripped):
        words = stripped.split()
        if len(words) <= 3:
            return True

    # "For the X" pattern
    if re.match(r"^[Ff]or [Tt]he \w+", stripped):
        return True

    # Known section header keywords (single word, title case)
    section_keywords = {
        "marinade", "filling", "garnish", "topping", "sauce",
        "dressing", "crust", "glaze", "frosting", "batter",
        "seasoning", "rub", "brine", "assembly", "ingredients",
        "topping", "coating", "stuffing", "drizzle",
    }
    if stripped.lower() in section_keywords:
        return True

    return False


def _is_section_header_from_parsed(text: str, parsed: ParsedIngredient) -> bool:
    """Detect section headers from parsed result.

    Section headers typically have:
    - No amounts
    - Short text (1-3 words)
    - ALL CAPS or title-like formatting
    - No commas or typical ingredient punctuation
    """
    # Has amounts? Not a header
    if parsed.amount:
        return False

    # Has preparation or comment? Probably an ingredient
    if parsed.preparation or parsed.comment:
        return False

    # Get the name text
    if not parsed.name:
        return False

    name_text = parsed.name[0].text if parsed.name else ""

    # Check word count
    words = name_text.split()
    if len(words) > 3:
        return False

    # ALL CAPS is a strong signal
    if name_text.isupper() and len(name_text) > 1:
        return True

    # Single word, title case, no special chars
    if len(words) == 1 and name_text[0].isupper() and name_text.isalpha():
        # Common section headers
        section_keywords = {
            "marinade", "filling", "garnish", "topping", "sauce",
            "dressing", "crust", "glaze", "frosting", "batter",
            "seasoning", "rub", "brine", "assembly", "ingredients",
        }
        if name_text.lower() in section_keywords:
            return True

    return False


def _normalize_quantity(amount: IngredientAmount) -> float | None:
    """Convert quantity to float, handling ranges and fractions.

    For ranges (e.g., "3-4"), returns midpoint rounded up.
    For fractions, converts to float.
    """
    qty = amount.quantity
    qty_max = amount.quantity_max

    if qty is None:
        return None

    # Convert to float
    qty_float = _to_float(qty)
    if qty_float is None:
        return None

    # Handle ranges: midpoint, round up
    if amount.RANGE and qty_max is not None:
        qty_max_float = _to_float(qty_max)
        if qty_max_float is not None and qty_max_float != qty_float:
            midpoint = (qty_float + qty_max_float) / 2
            return float(math.ceil(midpoint))

    return qty_float


def _to_float(value: Any) -> float | None:
    """Convert a quantity value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, str):
        try:
            return float(Fraction(value))
        except (ValueError, ZeroDivisionError):
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _extract_unit(amount: IngredientAmount) -> str | None:
    """Extract unit as string.

    If no unit is present (count-based ingredients like "1 pepper"),
    defaults to "medium" as a sensible placeholder.
    """
    unit = amount.unit
    if unit is None:
        return "medium"  # Default for count-based ingredients
    if isinstance(unit, str):
        return unit if unit else "medium"
    # pint.Unit object
    unit_str = str(unit) if unit else None
    return unit_str if unit_str else "medium"


def _build_result(text: str, parsed: ParsedIngredient) -> dict[str, Any]:
    """Build the result dict from parsed ingredient."""
    # Extract name
    input_item = None
    name_confidence = 0.0
    if parsed.name:
        input_item = parsed.name[0].text
        name_confidence = parsed.name[0].confidence

    # Extract first amount (primary quantity)
    input_qty = None
    input_unit_id = None
    amount_confidence = 0.0

    if parsed.amount:
        primary_amount = parsed.amount[0]
        # Handle CompositeIngredientAmount
        if hasattr(primary_amount, "amounts"):
            # Use the first sub-amount
            if primary_amount.amounts:
                primary_amount = primary_amount.amounts[0]

        input_qty = _normalize_quantity(primary_amount)
        input_unit_id = _extract_unit(primary_amount)
        amount_confidence = getattr(primary_amount, "confidence", 0.0)

    # Extract preparation
    preparation = None
    prep_confidence = 0.0
    if parsed.preparation:
        preparation = parsed.preparation.text
        prep_confidence = parsed.preparation.confidence

    # Extract comment/note
    note = None
    note_confidence = 0.0
    if parsed.comment:
        note = parsed.comment.text
        note_confidence = parsed.comment.confidence

    # Detect if optional
    is_optional = False
    if note and "optional" in note.lower():
        is_optional = True
    if preparation and "optional" in preparation.lower():
        is_optional = True

    # Calculate average confidence
    confidences = [c for c in [name_confidence, amount_confidence, prep_confidence, note_confidence] if c > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Determine quantity kind
    quantity_kind = _determine_quantity_kind(
        input_qty=input_qty,
        raw_text=text,
        note=note,
        preparation=preparation,
    )

    return {
        "quantity_kind": quantity_kind,
        "input_qty": input_qty,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": input_unit_id,
        "raw_ingredient_text": input_item,
        "preparation": preparation,
        "note": note,
        "raw_text": text,
        "is_optional": is_optional,
        "confidence": round(avg_confidence, 3),
    }


def _empty_result(text: str) -> dict[str, Any]:
    """Return result for empty input."""
    return {
        "quantity_kind": "unquantified",
        "input_qty": None,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": None,
        "raw_ingredient_text": None,
        "preparation": None,
        "note": None,
        "raw_text": text,
        "is_optional": False,
        "confidence": 0.0,
    }


def _fallback_result(text: str) -> dict[str, Any]:
    """Return result when parsing fails."""
    return {
        "quantity_kind": _determine_quantity_kind(
            input_qty=None,
            raw_text=text,
            note=None,
            preparation=None,
        ),
        "input_qty": None,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": None,
        "raw_ingredient_text": text,  # Use raw text as item name
        "preparation": None,
        "note": None,
        "raw_text": text,
        "is_optional": False,
        "confidence": 0.0,
    }


def _section_header_result(text: str) -> dict[str, Any]:
    """Return result for section headers."""
    return {
        "quantity_kind": "section_header",
        "input_qty": None,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": None,
        "raw_ingredient_text": text.strip().rstrip(":"),
        "preparation": None,
        "note": None,
        "raw_text": text,
        "is_optional": False,
        "confidence": 0.0,
    }


def _determine_quantity_kind(
    input_qty: float | None,
    raw_text: str,
    note: str | None,
    preparation: str | None,
) -> str:
    if input_qty is not None:
        return "exact"
    if _has_approximate_hint(raw_text, note, preparation):
        return "approximate"
    return "unquantified"


def _has_approximate_hint(
    raw_text: str,
    note: str | None,
    preparation: str | None,
) -> bool:
    parts = [raw_text]
    if note:
        parts.append(note)
    if preparation:
        parts.append(preparation)
    combined = " ".join(part.strip() for part in parts if part).lower()
    if not combined:
        return False
    return any(pattern.search(combined) for pattern in _APPROXIMATE_PATTERNS)
