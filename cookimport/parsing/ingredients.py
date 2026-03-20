"""Ingredient line parsing with deterministic normalization and repair."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any, Mapping

from ingredient_parser import parse_ingredient
from ingredient_parser.dataclasses import IngredientAmount, ParsedIngredient

from cookimport.parsing.sections import is_ingredient_section_header_line

INGREDIENT_TEXT_FIX_BACKEND_NONE = "none"
INGREDIENT_TEXT_FIX_BACKEND_FTFY = "ftfy"
INGREDIENT_PRE_NORMALIZE_MODE_AGGRESSIVE_V1 = "aggressive_v1"
INGREDIENT_PACKAGING_MODE_OFF = "off"
INGREDIENT_PACKAGING_MODE_REGEX_V1 = "regex_v1"
INGREDIENT_PARSER_BACKEND_NLP = "ingredient_parser_nlp"
INGREDIENT_PARSER_BACKEND_QUANTULUM3 = "quantulum3_regex"
INGREDIENT_PARSER_BACKEND_HYBRID = "hybrid_nlp_then_quantulum3"
INGREDIENT_UNIT_CANONICALIZER_PINT = "pint"
INGREDIENT_MISSING_UNIT_POLICY_MEDIUM = "medium"
INGREDIENT_MISSING_UNIT_POLICY_NULL = "null"
INGREDIENT_MISSING_UNIT_POLICY_EACH = "each"

_INGREDIENT_TEXT_FIX_BACKEND_ALLOWED = {
    INGREDIENT_TEXT_FIX_BACKEND_NONE,
    INGREDIENT_TEXT_FIX_BACKEND_FTFY,
}
_INGREDIENT_PRE_NORMALIZE_MODE_ALLOWED = {
    INGREDIENT_PRE_NORMALIZE_MODE_AGGRESSIVE_V1,
}
_INGREDIENT_PACKAGING_MODE_ALLOWED = {
    INGREDIENT_PACKAGING_MODE_OFF,
    INGREDIENT_PACKAGING_MODE_REGEX_V1,
}
_INGREDIENT_PARSER_BACKEND_ALLOWED = {
    INGREDIENT_PARSER_BACKEND_NLP,
    INGREDIENT_PARSER_BACKEND_QUANTULUM3,
    INGREDIENT_PARSER_BACKEND_HYBRID,
}
_INGREDIENT_UNIT_CANONICALIZER_ALLOWED = {
    INGREDIENT_UNIT_CANONICALIZER_PINT,
}
_INGREDIENT_MISSING_UNIT_POLICY_ALLOWED = {
    INGREDIENT_MISSING_UNIT_POLICY_MEDIUM,
    INGREDIENT_MISSING_UNIT_POLICY_NULL,
    INGREDIENT_MISSING_UNIT_POLICY_EACH,
}

_OPTION_KEYS = (
    "ingredient_text_fix_backend",
    "ingredient_pre_normalize_mode",
    "ingredient_packaging_mode",
    "ingredient_parser_backend",
    "ingredient_unit_canonicalizer",
    "ingredient_missing_unit_policy",
)

_DEFAULT_OPTIONS: dict[str, str] = {
    "ingredient_text_fix_backend": INGREDIENT_TEXT_FIX_BACKEND_NONE,
    "ingredient_pre_normalize_mode": INGREDIENT_PRE_NORMALIZE_MODE_AGGRESSIVE_V1,
    "ingredient_packaging_mode": INGREDIENT_PACKAGING_MODE_OFF,
    "ingredient_parser_backend": INGREDIENT_PARSER_BACKEND_NLP,
    "ingredient_unit_canonicalizer": INGREDIENT_UNIT_CANONICALIZER_PINT,
    "ingredient_missing_unit_policy": INGREDIENT_MISSING_UNIT_POLICY_NULL,
}

_OPTION_ALLOWED: dict[str, set[str]] = {
    "ingredient_text_fix_backend": _INGREDIENT_TEXT_FIX_BACKEND_ALLOWED,
    "ingredient_pre_normalize_mode": _INGREDIENT_PRE_NORMALIZE_MODE_ALLOWED,
    "ingredient_packaging_mode": _INGREDIENT_PACKAGING_MODE_ALLOWED,
    "ingredient_parser_backend": _INGREDIENT_PARSER_BACKEND_ALLOWED,
    "ingredient_unit_canonicalizer": _INGREDIENT_UNIT_CANONICALIZER_ALLOWED,
    "ingredient_missing_unit_policy": _INGREDIENT_MISSING_UNIT_POLICY_ALLOWED,
}

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
    re.compile(r"\ba pinch of\b"),
    re.compile(r"\bpinch\b"),
)

_APPROXIMATE_TOKEN_HINTS = {
    "to taste",
    "as needed",
    "pinch",
}

_SIZE_ADJECTIVE_UNITS = {"small", "medium", "large"}
_SECTION_HEADER_KEYWORDS = {
    "marinade",
    "filling",
    "garnish",
    "topping",
    "sauce",
    "dressing",
    "crust",
    "glaze",
    "frosting",
    "batter",
    "seasoning",
    "rub",
    "brine",
    "assembly",
    "ingredients",
}
_DASH_TRANSLATION = str.maketrans({
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})

_PARENTHESES_PACKAGING_RE = re.compile(
    r"^\s*(?P<count>\d+(?:\.\d+)?(?:\s+\d+/\d+)?)\s*\((?P<pkg>[^)]+)\)\s*(?P<container>[A-Za-z][A-Za-z\-]*)s?\b\s+(?P<name>.+?)\s*$",
    re.IGNORECASE,
)
_MULTIPACK_PACKAGING_RE = re.compile(
    r"^\s*(?P<count>\d+(?:\.\d+)?)\s*[xX\u00d7]\s*(?P<pkg>\d+(?:\.\d+)?\s*[A-Za-z]+)\s*(?P<container>[A-Za-z][A-Za-z\-]*)s?\b\s+(?P<name>.+?)\s*$",
    re.IGNORECASE,
)

_UNIT_ALIAS_MAP = {
    "tsp": "teaspoon",
    "tsp.": "teaspoon",
    "tsps": "teaspoon",
    "tbsp": "tablespoon",
    "tbsp.": "tablespoon",
    "tbs": "tablespoon",
    "tbs.": "tablespoon",
    "oz": "ounce",
    "oz.": "ounce",
    "lb": "pound",
    "lbs": "pound",
    "lb.": "pound",
    "lbs.": "pound",
    "g": "gram",
    "kg": "kilogram",
    "ml": "milliliter",
    "l": "liter",
    "fl oz": "fluid ounce",
    "fl. oz.": "fluid ounce",
}

_APPROXIMATE_UNIT_NORMALIZATION_MAP = {
    "picoinch": "pinch",
}

_MEASUREMENT_UNIT_HINTS = {
    "cup",
    "cups",
    "teaspoon",
    "teaspoons",
    "tablespoon",
    "tablespoons",
    "ounce",
    "ounces",
    "gram",
    "grams",
    "kilogram",
    "kilograms",
    "milliliter",
    "milliliters",
    "liter",
    "liters",
    "pound",
    "pounds",
    "fluid",
}

_CONTAINER_UNITS = {
    "can",
    "cans",
    "tin",
    "tins",
    "jar",
    "jars",
    "clove",
    "cloves",
    "stalk",
    "stalks",
    "bunch",
    "bunches",
    "sprig",
    "sprigs",
    "package",
    "packages",
    "bag",
    "bags",
}

_SIZE_FROM_TEXT_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?(?:\s+\d+/\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s+(small|medium|large)\b",
    re.IGNORECASE,
)

_PINT_REGISTRY: Any | None = None


def normalize_ingredient_parser_options(
    payload: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return normalized parser options from run-config-like payload."""
    source = payload or {}
    normalized: dict[str, str] = {}
    for key in _OPTION_KEYS:
        normalized[key] = _normalize_option_value(
            source.get(key),
            allowed=_OPTION_ALLOWED[key],
            default=_DEFAULT_OPTIONS[key],
        )
    return normalized


def parse_ingredient_line(
    text: str,
    *,
    ingredient_text_fix_backend: str = INGREDIENT_TEXT_FIX_BACKEND_NONE,
    ingredient_pre_normalize_mode: str = INGREDIENT_PRE_NORMALIZE_MODE_AGGRESSIVE_V1,
    ingredient_packaging_mode: str = INGREDIENT_PACKAGING_MODE_OFF,
    ingredient_parser_backend: str = INGREDIENT_PARSER_BACKEND_NLP,
    ingredient_unit_canonicalizer: str = INGREDIENT_UNIT_CANONICALIZER_PINT,
    ingredient_missing_unit_policy: str = INGREDIENT_MISSING_UNIT_POLICY_NULL,
) -> dict[str, Any]:
    """Parse one ingredient line into normalized staging fields."""
    original_text = text.strip()
    if not original_text:
        return _empty_result(original_text)

    options = normalize_ingredient_parser_options(
        {
            "ingredient_text_fix_backend": ingredient_text_fix_backend,
            "ingredient_pre_normalize_mode": ingredient_pre_normalize_mode,
            "ingredient_packaging_mode": ingredient_packaging_mode,
            "ingredient_parser_backend": ingredient_parser_backend,
            "ingredient_unit_canonicalizer": ingredient_unit_canonicalizer,
            "ingredient_missing_unit_policy": ingredient_missing_unit_policy,
        }
    )

    if _is_section_header_heuristic(original_text):
        return _section_header_result(original_text)

    working_text = original_text
    if options["ingredient_text_fix_backend"] == INGREDIENT_TEXT_FIX_BACKEND_FTFY:
        working_text = _apply_ftfy_text_fix(working_text)

    working_text = normalize_fraction_and_range_spacing(
        normalize_parentheses_space(dash_fold(working_text))
    )

    packaging_note: str | None = None
    if options["ingredient_packaging_mode"] == INGREDIENT_PACKAGING_MODE_REGEX_V1:
        working_text, packaging_note = extract_packaging_note(working_text)

    parsed_result = _parse_with_selected_backend(
        normalized_text=working_text,
        raw_text=original_text,
        backend=options["ingredient_parser_backend"],
    )

    repaired = _repair_result(
        parsed_result,
        raw_text=original_text,
        normalized_text=working_text,
        ingredient_unit_canonicalizer=options["ingredient_unit_canonicalizer"],
        ingredient_missing_unit_policy=options["ingredient_missing_unit_policy"],
    )

    if packaging_note:
        repaired["note"] = _merge_notes(_clean_text(repaired.get("note")), packaging_note)

    repaired["quantity_kind"] = _determine_quantity_kind(
        input_qty=repaired.get("input_qty"),
        raw_text=original_text,
        note=_clean_text(repaired.get("note")),
        preparation=_clean_text(repaired.get("preparation")),
    )
    repaired["raw_text"] = original_text
    return repaired


def warm_ingredient_parser() -> None:
    """Proactively load ingredient parser models."""
    try:
        parse_ingredient("1 cup water")
    except Exception:
        pass


def dash_fold(text: str) -> str:
    """Normalize common unicode dash variants to '-'."""
    return text.translate(_DASH_TRANSLATION)


def normalize_parentheses_space(text: str) -> str:
    """Normalize spacing around parentheses deterministically."""
    normalized = re.sub(r"\s*\(\s*", " (", text)
    normalized = re.sub(r"\s*\)\s*", ") ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_fraction_and_range_spacing(text: str) -> str:
    """Normalize split fractions and numeric range spacing."""
    normalized = _normalize_ingredient_text(text)
    normalized = re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", normalized)
    normalized = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", normalized)
    return normalized


def extract_packaging_note(text: str) -> tuple[str, str | None]:
    """Hoist packaging-size hints while preserving container-unit semantics."""
    for pattern in (_PARENTHESES_PACKAGING_RE, _MULTIPACK_PACKAGING_RE):
        match = pattern.match(text)
        if match is None:
            continue
        groups = match.groupdict()
        name = _clean_text(groups.get("name"))
        pkg = _clean_text(groups.get("pkg"))
        count = _clean_text(groups.get("count"))
        container = _clean_text(groups.get("container"))
        if not (name and pkg and count and container):
            continue
        rewritten = f"{count} {container} {name}".strip()
        if rewritten == text.strip():
            continue
        return rewritten, f"pkg: {pkg}"
    return text, None


def canonicalize_unit_with_pint(raw_unit_text: str) -> str:
    """Canonicalize measurement units with pint when available."""
    lowered = raw_unit_text.strip().lower()
    if lowered in _CONTAINER_UNITS:
        return raw_unit_text.strip()

    normalized_alias = _UNIT_ALIAS_MAP.get(lowered, lowered)
    registry = _load_pint_registry()
    if registry is None:
        return normalized_alias

    try:
        parsed = registry.parse_expression(normalized_alias)
        units = getattr(parsed, "units", None)
        if units is None:
            return normalized_alias
        rendered = str(units).replace("_", " ").strip()
    except Exception:
        return normalized_alias

    if not rendered or rendered == "dimensionless":
        return normalized_alias
    return rendered


def _normalize_option_value(
    value: Any,
    *,
    allowed: set[str],
    default: str,
) -> str:
    normalized = str(value or default).strip().lower()
    if normalized in allowed:
        return normalized
    return default


def _parse_with_selected_backend(
    *,
    normalized_text: str,
    raw_text: str,
    backend: str,
) -> dict[str, Any]:
    if backend == INGREDIENT_PARSER_BACKEND_QUANTULUM3:
        return _parse_with_quantulum3_backend(normalized_text, raw_text)

    nlp_result = _parse_with_nlp_backend(normalized_text, raw_text)
    if backend == INGREDIENT_PARSER_BACKEND_HYBRID and _result_needs_backend_fallback(
        nlp_result
    ):
        quantulum_result = _parse_with_quantulum3_backend(normalized_text, raw_text)
        if not _result_needs_backend_fallback(quantulum_result):
            return quantulum_result
    return nlp_result


def _parse_with_nlp_backend(normalized_text: str, raw_text: str) -> dict[str, Any]:
    try:
        parsed = parse_ingredient(normalized_text, string_units=True)
    except Exception:
        return _fallback_result(raw_text)

    if _is_section_header_from_parsed(raw_text, parsed):
        return _section_header_result(raw_text)
    return _build_result_from_parsed(raw_text, parsed)


def _parse_with_quantulum3_backend(normalized_text: str, raw_text: str) -> dict[str, Any]:
    quantulum_parser = _load_quantulum_parser()
    if quantulum_parser is None:
        return _fallback_result(raw_text)

    try:
        quantities = quantulum_parser.parse(normalized_text)
    except Exception:
        quantities = []

    if not quantities:
        return _fallback_result(raw_text)

    first_quantity = quantities[0]
    quantity_value = getattr(first_quantity, "value", None)
    numeric_quantity: float | None = None
    if isinstance(quantity_value, (int, float)):
        numeric_quantity = float(quantity_value)

    unit_payload = getattr(first_quantity, "unit", None)
    unit_name = _clean_text(getattr(unit_payload, "name", None))

    remaining = normalized_text
    span = getattr(first_quantity, "span", None)
    if isinstance(span, tuple) and len(span) == 2:
        start, end = span
        try:
            remaining = f"{normalized_text[: int(start)]} {normalized_text[int(end):]}"
        except Exception:
            remaining = normalized_text
    else:
        surface = _clean_text(getattr(first_quantity, "surface", None))
        if surface:
            remaining = remaining.replace(surface, "", 1)

    name = _clean_text(remaining.strip(" ,;-:"))
    if not name:
        name = _fallback_name_from_text(raw_text)

    return {
        "quantity_kind": "exact" if numeric_quantity is not None else "unquantified",
        "input_qty": numeric_quantity,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": unit_name,
        "raw_ingredient_text": name,
        "preparation": None,
        "note": None,
        "raw_text": raw_text,
        "is_optional": False,
        "confidence": 0.4,
    }


def _build_result_from_parsed(text: str, parsed: ParsedIngredient) -> dict[str, Any]:
    input_item = None
    name_confidence = 0.0
    if parsed.name:
        input_item = parsed.name[0].text
        name_confidence = parsed.name[0].confidence

    input_qty = None
    raw_unit_text = None
    amount_confidence = 0.0

    if parsed.amount:
        primary_amount = parsed.amount[0]
        if hasattr(primary_amount, "amounts") and primary_amount.amounts:
            primary_amount = primary_amount.amounts[0]

        input_qty = _normalize_quantity(primary_amount)
        raw_unit_text = _extract_unit(primary_amount)
        amount_confidence = float(getattr(primary_amount, "confidence", 0.0) or 0.0)

    preparation = None
    prep_confidence = 0.0
    if parsed.preparation:
        preparation = parsed.preparation.text
        prep_confidence = parsed.preparation.confidence

    note = None
    note_confidence = 0.0
    if parsed.comment:
        note = parsed.comment.text
        note_confidence = parsed.comment.confidence

    confidences = [
        confidence
        for confidence in (name_confidence, amount_confidence, prep_confidence, note_confidence)
        if confidence > 0
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "quantity_kind": "exact" if input_qty is not None else "unquantified",
        "input_qty": input_qty,
        "input_unit_id": "",
        "ingredient_id": "",
        "raw_unit_text": raw_unit_text,
        "raw_ingredient_text": input_item,
        "preparation": preparation,
        "note": note,
        "raw_text": text,
        "is_optional": False,
        "confidence": round(float(avg_confidence), 3),
    }


def _repair_result(
    result: dict[str, Any],
    *,
    raw_text: str,
    normalized_text: str,
    ingredient_unit_canonicalizer: str,
    ingredient_missing_unit_policy: str,
) -> dict[str, Any]:
    repaired = dict(result)

    note = _clean_text(repaired.get("note"))
    preparation = _clean_text(repaired.get("preparation"))
    name = _clean_text(repaired.get("raw_ingredient_text"))
    raw_unit_text = _clean_text(repaired.get("raw_unit_text"))

    input_qty, qty_note = _coerce_quantity_value(repaired.get("input_qty"))
    note = _merge_notes(note, qty_note)

    if input_qty is None and raw_unit_text and (not name or len(name) < 2):
        name = raw_unit_text
        raw_unit_text = None

    if raw_unit_text:
        raw_unit_text = _normalize_unit_text(raw_unit_text)
        raw_unit_text = canonicalize_unit_with_pint(raw_unit_text)
        raw_unit_text = _normalize_approximate_unit_text(raw_unit_text)

    if (
        input_qty is None
        and raw_unit_text
        and raw_unit_text.lower() in _APPROXIMATE_TOKEN_HINTS
    ):
        note = _merge_notes(note, raw_unit_text.lower())
        raw_unit_text = None

    if raw_unit_text and raw_unit_text.lower() in _SIZE_ADJECTIVE_UNITS:
        note = _merge_notes(note, raw_unit_text.lower())
        raw_unit_text = None

    size_adjective = _extract_size_adjective(raw_text)
    if size_adjective:
        note = _merge_notes(note, size_adjective)

    if input_qty is not None and not raw_unit_text:
        if ingredient_missing_unit_policy == INGREDIENT_MISSING_UNIT_POLICY_EACH:
            raw_unit_text = "each"
        elif ingredient_missing_unit_policy == INGREDIENT_MISSING_UNIT_POLICY_MEDIUM:
            raw_unit_text = "medium"

    if not name or len(name) < 2:
        name = _fallback_name_from_text(normalized_text) or _fallback_name_from_text(raw_text)

    if not name:
        name = raw_text.strip() or None

    is_optional = False
    for value in (note, preparation, raw_text):
        if value and "optional" in value.lower():
            is_optional = True
            break

    confidence = repaired.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.0

    repaired.update(
        {
            "input_qty": input_qty,
            "input_unit_id": "",
            "ingredient_id": "",
            "raw_unit_text": raw_unit_text,
            "raw_ingredient_text": name,
            "preparation": preparation,
            "note": note,
            "is_optional": is_optional,
            "confidence": round(float(confidence), 3),
        }
    )
    return repaired


def _coerce_quantity_value(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None
    if isinstance(value, Fraction):
        return float(value), None

    text = _clean_text(value)
    if not text:
        return None, None

    try:
        return float(Fraction(text)), None
    except (ValueError, ZeroDivisionError):
        pass

    lowered = text.lower()
    if lowered in _APPROXIMATE_TOKEN_HINTS:
        return None, lowered
    return None, text


def _extract_size_adjective(raw_text: str) -> str | None:
    match = _SIZE_FROM_TEXT_RE.match(raw_text)
    if match is None:
        return None
    return _clean_text(match.group(1))


def _normalize_unit_text(unit_text: str) -> str:
    normalized = unit_text.strip().lower().replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return _UNIT_ALIAS_MAP.get(normalized, normalized)


def _normalize_approximate_unit_text(unit_text: str) -> str:
    normalized = unit_text.strip().lower()
    return _APPROXIMATE_UNIT_NORMALIZATION_MAP.get(normalized, normalized)


def _fallback_name_from_text(text: str) -> str | None:
    cleaned = _clean_text(text)
    if not cleaned:
        return None

    stripped = re.sub(
        r"^\s*(?:about\s+)?\d+(?:\.\d+)?(?:\s+\d+/\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"^\s*[xX\u00d7]\s*\d+(?:\.\d+)?\s*[A-Za-z]+\s*",
        "",
        stripped,
    )
    stripped = stripped.strip(" ,;-:")

    if not stripped:
        return cleaned

    tokens = stripped.split()
    if tokens and tokens[0].lower() in _MEASUREMENT_UNIT_HINTS and len(tokens) > 1:
        stripped = " ".join(tokens[1:])

    return stripped.strip() or cleaned


def _result_needs_backend_fallback(result: dict[str, Any]) -> bool:
    if result.get("quantity_kind") == "section_header":
        return False
    name = _clean_text(result.get("raw_ingredient_text"))
    if not name or len(name) < 2:
        return True
    quantity_kind = _clean_text(result.get("quantity_kind")) or ""
    if quantity_kind == "exact" and result.get("input_qty") is None:
        return True
    return False


def _apply_ftfy_text_fix(text: str) -> str:
    try:
        from ftfy import fix_text  # type: ignore
    except Exception:
        return text
    try:
        fixed = fix_text(text)
    except Exception:
        return text
    return str(fixed or text)


def _load_quantulum_parser() -> Any | None:
    try:
        from quantulum3 import parser as quantulum_parser  # type: ignore
    except Exception:
        return None
    return quantulum_parser


def _load_pint_registry() -> Any | None:
    global _PINT_REGISTRY
    if _PINT_REGISTRY is not None:
        return _PINT_REGISTRY

    try:
        from pint import UnitRegistry  # type: ignore
    except Exception:
        return None

    try:
        _PINT_REGISTRY = UnitRegistry(autoconvert_offset_to_baseunit=True)
    except Exception:
        _PINT_REGISTRY = None
    return _PINT_REGISTRY


def _is_section_header_heuristic(text: str) -> bool:
    if is_ingredient_section_header_line(text):
        return True
    candidate = text.strip().rstrip(":")
    if " " not in candidate and candidate.lower() in _SECTION_HEADER_KEYWORDS:
        return True
    return False


def _is_section_header_from_parsed(text: str, parsed: ParsedIngredient) -> bool:
    if parsed.amount:
        return False

    if parsed.preparation or parsed.comment:
        return False

    if not parsed.name:
        return False

    name_text = parsed.name[0].text if parsed.name else ""
    words = name_text.split()
    if len(words) > 3:
        return False

    if name_text.isupper() and len(name_text) > 1:
        return True

    if len(words) == 1 and name_text and name_text.isalpha():
        if name_text.lower() in _SECTION_HEADER_KEYWORDS:
            return True

    return False


def _normalize_quantity(amount: IngredientAmount) -> float | None:
    qty = amount.quantity
    qty_max = amount.quantity_max

    if qty is None:
        return None

    qty_float = _to_float(qty)
    if qty_float is None:
        return None

    if amount.RANGE and qty_max is not None:
        qty_max_float = _to_float(qty_max)
        if qty_max_float is not None and qty_max_float != qty_float:
            midpoint = (qty_float + qty_max_float) / 2
            return float(math.ceil(midpoint))

    return qty_float


def _to_float(value: Any) -> float | None:
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


def _normalize_ingredient_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", normalized)


def _extract_unit(amount: IngredientAmount) -> str | None:
    unit = amount.unit
    if unit is None:
        return None
    if isinstance(unit, str):
        stripped = unit.strip()
        return stripped if stripped else None
    unit_str = str(unit).strip()
    return unit_str if unit_str else None


def _empty_result(text: str) -> dict[str, Any]:
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
        "raw_ingredient_text": _fallback_name_from_text(text) or text,
        "preparation": None,
        "note": None,
        "raw_text": text,
        "is_optional": False,
        "confidence": 0.0,
    }


def _section_header_result(text: str) -> dict[str, Any]:
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


def _merge_notes(existing: str | None, extra: str | None) -> str | None:
    left = _clean_text(existing)
    right = _clean_text(extra)
    if not left:
        return right
    if not right:
        return left
    if left.lower() == right.lower():
        return left
    return f"{left}; {right}"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text)
