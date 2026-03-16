"""Extract time and temperature metadata from recipe instruction text.

This module keeps the current default parse behavior while exposing optional
Priority 6 strategies/backends through `InstructionParseOptions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

# Priority 6 selector names
TIME_BACKEND_REGEX_V1 = "regex_v1"
TIME_BACKEND_QUANTULUM3_V1 = "quantulum3_v1"
TIME_BACKEND_HYBRID_V1 = "hybrid_regex_quantulum3_v1"

TIME_TOTAL_STRATEGY_SUM_ALL_V1 = "sum_all_v1"
TIME_TOTAL_STRATEGY_MAX_V1 = "max_v1"
TIME_TOTAL_STRATEGY_SELECTIVE_SUM_V1 = "selective_sum_v1"

TEMPERATURE_BACKEND_REGEX_V1 = "regex_v1"
TEMPERATURE_BACKEND_QUANTULUM3_V1 = "quantulum3_v1"
TEMPERATURE_BACKEND_HYBRID_V1 = "hybrid_regex_quantulum3_v1"

TEMPERATURE_UNIT_BACKEND_BUILTIN_V1 = "builtin_v1"
TEMPERATURE_UNIT_BACKEND_PINT_V1 = "pint_v1"

OVENLIKE_MODE_KEYWORDS_V1 = "keywords_v1"
OVENLIKE_MODE_OFF = "off"

_ALLOWED_TIME_BACKENDS = {
    TIME_BACKEND_REGEX_V1,
    TIME_BACKEND_QUANTULUM3_V1,
    TIME_BACKEND_HYBRID_V1,
}
_ALLOWED_TIME_TOTAL_STRATEGIES = {
    TIME_TOTAL_STRATEGY_SUM_ALL_V1,
    TIME_TOTAL_STRATEGY_MAX_V1,
    TIME_TOTAL_STRATEGY_SELECTIVE_SUM_V1,
}
_ALLOWED_TEMPERATURE_BACKENDS = {
    TEMPERATURE_BACKEND_REGEX_V1,
    TEMPERATURE_BACKEND_QUANTULUM3_V1,
    TEMPERATURE_BACKEND_HYBRID_V1,
}
_ALLOWED_TEMPERATURE_UNIT_BACKENDS = {
    TEMPERATURE_UNIT_BACKEND_BUILTIN_V1,
    TEMPERATURE_UNIT_BACKEND_PINT_V1,
}
_ALLOWED_OVENLIKE_MODES = {
    OVENLIKE_MODE_KEYWORDS_V1,
    OVENLIKE_MODE_OFF,
}


@dataclass
class TimeItem:
    """A single time extraction from instruction text."""

    seconds: int
    original_text: str


@dataclass
class TemperatureItem:
    """A single temperature extraction from instruction text."""

    value: float
    unit: Literal["fahrenheit", "celsius"]
    value_f: int
    original_text: str
    is_oven_like: bool


@dataclass(frozen=True)
class InstructionParseOptions:
    """Configurable deterministic instruction parser behavior."""

    time_backend: str = TIME_BACKEND_REGEX_V1
    time_total_strategy: str = TIME_TOTAL_STRATEGY_SUM_ALL_V1
    temperature_backend: str = TEMPERATURE_BACKEND_REGEX_V1
    temperature_unit_backend: str = TEMPERATURE_UNIT_BACKEND_BUILTIN_V1
    ovenlike_mode: str = OVENLIKE_MODE_KEYWORDS_V1


@dataclass
class InstructionMetadata:
    """Extracted metadata from an instruction string."""

    total_time_seconds: int | None = None
    time_items: list[TimeItem] = field(default_factory=list)
    temperature: float | None = None
    temperature_unit: Literal["fahrenheit", "celsius"] | None = None
    temperature_text: str | None = None
    temperature_items: list[TemperatureItem] = field(default_factory=list)


@dataclass(frozen=True)
class _TimeMatch:
    item: TimeItem
    start: int
    end: int


# Time unit multipliers (to seconds)
_TIME_MULTIPLIERS = {
    "second": 1,
    "seconds": 1,
    "sec": 1,
    "secs": 1,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mins": 60,
    "hour": 3600,
    "hours": 3600,
    "hr": 3600,
    "hrs": 3600,
    "day": 86400,
    "days": 86400,
}

# Pattern for time extraction
# Matches: "30 minutes", "1-2 hours", "1 to 2 hours", "about 45 mins"
_TIME_PATTERN = re.compile(
    r"""
    (?:about\s+|approximately\s+|~\s*)?  # Optional approximate prefix
    (\d+)                                 # First number
    (?:\s*(?:-|to)\s*(\d+))?             # Optional range (e.g., "1-2" or "1 to 2")
    \s*
    (seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)  # Time unit
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Pattern for temperature extraction
# Matches: "400F", "400°F", "400 degrees F", "180°C", "350 degrees fahrenheit"
_TEMP_PATTERN = re.compile(
    r"""
    (\d+)                                 # Temperature value
    \s*°?\s*                              # Optional degree symbol
    (
        fahrenheit|celsius|               # Full words
        degrees?\s*(?:fahrenheit|celsius|f|c)|  # "degrees F" style
        f|c                               # Just F or C
    )
    (?!\w)                                # Not followed by word char (avoid matching "cup")
    """,
    re.IGNORECASE | re.VERBOSE,
)

_OVEN_POSITIVE_HINTS = {
    "oven",
    "preheat",
    "bake",
    "roast",
    "broil",
}
_OVEN_NEGATIVE_HINTS = {
    "internal",
    "thermometer",
    "sous vide",
    "oil",
    "deep fry",
    "fry",
    "caramel",
    "candy",
}


def _normalize_selector(value: Any, *, allowed: set[str], default: str) -> str:
    normalized = str(value or default).strip().lower().replace("-", "_")
    if normalized in allowed:
        return normalized
    return default


def normalize_instruction_parse_options(
    payload: Mapping[str, Any] | InstructionParseOptions | None,
) -> InstructionParseOptions:
    """Return normalized parser options from run-config-like payload.

    Supports either direct option names or Priority 6-prefixed run-config keys.
    """
    if isinstance(payload, InstructionParseOptions):
        return InstructionParseOptions(
            time_backend=_normalize_selector(
                payload.time_backend,
                allowed=_ALLOWED_TIME_BACKENDS,
                default=TIME_BACKEND_REGEX_V1,
            ),
            time_total_strategy=_normalize_selector(
                payload.time_total_strategy,
                allowed=_ALLOWED_TIME_TOTAL_STRATEGIES,
                default=TIME_TOTAL_STRATEGY_SUM_ALL_V1,
            ),
            temperature_backend=_normalize_selector(
                payload.temperature_backend,
                allowed=_ALLOWED_TEMPERATURE_BACKENDS,
                default=TEMPERATURE_BACKEND_REGEX_V1,
            ),
            temperature_unit_backend=_normalize_selector(
                payload.temperature_unit_backend,
                allowed=_ALLOWED_TEMPERATURE_UNIT_BACKENDS,
                default=TEMPERATURE_UNIT_BACKEND_BUILTIN_V1,
            ),
            ovenlike_mode=_normalize_selector(
                payload.ovenlike_mode,
                allowed=_ALLOWED_OVENLIKE_MODES,
                default=OVENLIKE_MODE_KEYWORDS_V1,
            ),
        )

    source = payload or {}
    return InstructionParseOptions(
        time_backend=_normalize_selector(
            source.get("p6_time_backend", source.get("time_backend")),
            allowed=_ALLOWED_TIME_BACKENDS,
            default=TIME_BACKEND_REGEX_V1,
        ),
        time_total_strategy=_normalize_selector(
            source.get("p6_time_total_strategy", source.get("time_total_strategy")),
            allowed=_ALLOWED_TIME_TOTAL_STRATEGIES,
            default=TIME_TOTAL_STRATEGY_SUM_ALL_V1,
        ),
        temperature_backend=_normalize_selector(
            source.get("p6_temperature_backend", source.get("temperature_backend")),
            allowed=_ALLOWED_TEMPERATURE_BACKENDS,
            default=TEMPERATURE_BACKEND_REGEX_V1,
        ),
        temperature_unit_backend=_normalize_selector(
            source.get(
                "p6_temperature_unit_backend",
                source.get("temperature_unit_backend"),
            ),
            allowed=_ALLOWED_TEMPERATURE_UNIT_BACKENDS,
            default=TEMPERATURE_UNIT_BACKEND_BUILTIN_V1,
        ),
        ovenlike_mode=_normalize_selector(
            source.get("p6_ovenlike_mode", source.get("ovenlike_mode")),
            allowed=_ALLOWED_OVENLIKE_MODES,
            default=OVENLIKE_MODE_KEYWORDS_V1,
        ),
    )


def _parse_time_unit(unit: str) -> int:
    """Get the multiplier for a time unit string."""
    return _TIME_MULTIPLIERS.get(unit.lower(), 60)  # Default to minutes


def _normalize_temp_unit(unit_text: str) -> Literal["fahrenheit", "celsius"]:
    """Normalize temperature unit text to standard form."""
    text = unit_text.lower().strip()
    if "c" in text and "f" not in text:
        return "celsius"
    return "fahrenheit"


def _extract_times_regex(text: str) -> list[_TimeMatch]:
    """Extract all time durations from text using regex."""
    items: list[_TimeMatch] = []
    for match in _TIME_PATTERN.finditer(text):
        first_num = int(match.group(1))
        second_num = match.group(2)
        unit = match.group(3)
        multiplier = _parse_time_unit(unit)

        if second_num:
            # Range: take midpoint
            avg = (first_num + int(second_num)) / 2
            seconds = int(avg * multiplier)
        else:
            seconds = first_num * multiplier

        items.append(
            _TimeMatch(
                item=TimeItem(seconds=seconds, original_text=match.group(0).strip()),
                start=match.start(),
                end=match.end(),
            )
        )
    return items


def _load_quantulum_parser(*, required_for: str | None = None) -> Any | None:
    try:
        from quantulum3 import parser as quantulum_parser  # type: ignore[import-untyped]
    except Exception:
        if required_for:
            raise ValueError(
                f"Instruction parser backend '{required_for}' requires optional dependency "
                "'quantulum3'. Install with: pip install -e '.[priority6]'"
            ) from None
        return None
    return quantulum_parser


def _load_pint_registry(*, required_for: str | None = None) -> Any | None:
    try:
        from pint import UnitRegistry  # type: ignore[import-untyped]
    except Exception:
        if required_for:
            raise ValueError(
                f"Instruction parser backend '{required_for}' requires optional dependency "
                "'pint'. Install with: pip install -e '.[priority6]'"
            ) from None
        return None

    try:
        return UnitRegistry(autoconvert_offset_to_baseunit=True)
    except Exception:
        if required_for:
            raise ValueError(
                f"Instruction parser backend '{required_for}' could not initialize pint UnitRegistry."
            ) from None
        return None


def _extract_times_quantulum3(text: str, *, required_for: str | None = None) -> list[_TimeMatch]:
    parser = _load_quantulum_parser(required_for=required_for)
    if parser is None:
        return []

    try:
        quantities = parser.parse(text)
    except Exception:
        return []

    results: list[_TimeMatch] = []
    for quantity in quantities:
        unit = getattr(quantity, "unit", None)
        entity = getattr(unit, "entity", None)
        entity_name = str(getattr(entity, "name", "")).lower()
        if entity_name != "time":
            continue

        value = getattr(quantity, "value", None)
        if not isinstance(value, (int, float)):
            continue
        surface = str(getattr(quantity, "surface", "")).strip()
        if not surface:
            continue

        unit_name = str(getattr(unit, "name", "")).lower()
        multiplier = 1
        if "day" in unit_name:
            multiplier = 86400
        elif "hour" in unit_name:
            multiplier = 3600
        elif "minute" in unit_name:
            multiplier = 60

        seconds = int(float(value) * multiplier)
        span = getattr(quantity, "span", None)
        if isinstance(span, tuple) and len(span) == 2:
            try:
                start = int(span[0])
                end = int(span[1])
            except Exception:
                start = text.lower().find(surface.lower())
                end = start + len(surface) if start >= 0 else -1
        else:
            start = text.lower().find(surface.lower())
            end = start + len(surface) if start >= 0 else -1

        if start < 0 or end <= start:
            continue

        results.append(
            _TimeMatch(
                item=TimeItem(seconds=seconds, original_text=surface),
                start=start,
                end=end,
            )
        )

    results.sort(key=lambda entry: (entry.start, entry.end))
    return results


def _is_frequency_span(text: str, span: _TimeMatch) -> bool:
    prefix = text[max(0, span.start - 12) : span.start].lower()
    return bool(re.search(r"\bevery\s*$", prefix))


def _compute_total_time_seconds(
    text: str,
    spans: list[_TimeMatch],
    *,
    strategy: str,
) -> int | None:
    if not spans:
        return None

    if strategy == TIME_TOTAL_STRATEGY_SUM_ALL_V1:
        return sum(entry.item.seconds for entry in spans)

    if strategy == TIME_TOTAL_STRATEGY_MAX_V1:
        return max(entry.item.seconds for entry in spans)

    # selective_sum_v1: keep sequential durations, collapse obvious alternatives,
    # skip frequency spans like "every 5 minutes".
    filtered = [entry for entry in spans if not _is_frequency_span(text, entry)]
    if not filtered:
        filtered = list(spans)

    groups: list[list[_TimeMatch]] = []
    for entry in filtered:
        if not groups:
            groups.append([entry])
            continue

        prev = groups[-1][-1]
        between = text[prev.end : entry.start].lower()
        if re.search(r"\b(or|alternatively|otherwise|instead)\b", between):
            groups[-1].append(entry)
            continue
        groups.append([entry])

    total = 0
    for group in groups:
        total += max(item.item.seconds for item in group)
    return total


def _temperature_value_f(
    value: float,
    *,
    unit: Literal["fahrenheit", "celsius"],
    unit_backend: str,
) -> int:
    if unit_backend == TEMPERATURE_UNIT_BACKEND_PINT_V1:
        # Validation-only requirement: pint must be installed for this backend.
        _load_pint_registry(required_for=TEMPERATURE_UNIT_BACKEND_PINT_V1)

    if unit == "fahrenheit":
        return int(round(value))
    return int(round(celsius_to_fahrenheit(value)))


def _is_oven_like_context(text: str, *, start: int, end: int, mode: str) -> bool:
    if mode == OVENLIKE_MODE_OFF:
        return False

    # Keep a broad positive window so "preheat oven to 400F" is caught even when
    # the cue is a few words away, but require negative cues to be close to the
    # matched temperature so distant "internal temp" mentions do not suppress it.
    context = text[max(0, start - 48) : min(len(text), end + 48)].lower()
    negative_context = text[max(0, start - 16) : min(len(text), end + 16)].lower()
    if any(hint in negative_context for hint in _OVEN_NEGATIVE_HINTS):
        return False
    return any(hint in context for hint in _OVEN_POSITIVE_HINTS)


def _extract_temperature_items_regex(
    text: str,
    *,
    unit_backend: str,
    ovenlike_mode: str,
) -> list[TemperatureItem]:
    items: list[TemperatureItem] = []
    for match in _TEMP_PATTERN.finditer(text):
        value = float(match.group(1))
        unit = _normalize_temp_unit(match.group(2))
        value_f = _temperature_value_f(value, unit=unit, unit_backend=unit_backend)
        items.append(
            TemperatureItem(
                value=value,
                unit=unit,
                value_f=value_f,
                original_text=match.group(0).strip(),
                is_oven_like=_is_oven_like_context(
                    text,
                    start=match.start(),
                    end=match.end(),
                    mode=ovenlike_mode,
                ),
            )
        )
    return items


def _normalize_quantulum_temp_unit(unit_name: str) -> Literal["fahrenheit", "celsius"] | None:
    lowered = unit_name.lower()
    if "fahrenheit" in lowered or lowered in {"f", "degf", "degree fahrenheit"}:
        return "fahrenheit"
    if "celsius" in lowered or lowered in {"c", "degc", "degree celsius"}:
        return "celsius"
    if "centigrade" in lowered:
        return "celsius"
    return None


def _extract_temperature_items_quantulum3(
    text: str,
    *,
    unit_backend: str,
    ovenlike_mode: str,
    required_for: str | None = None,
) -> list[TemperatureItem]:
    parser = _load_quantulum_parser(required_for=required_for)
    if parser is None:
        return []

    try:
        quantities = parser.parse(text)
    except Exception:
        return []

    items: list[TemperatureItem] = []
    for quantity in quantities:
        value = getattr(quantity, "value", None)
        if not isinstance(value, (int, float)):
            continue

        unit_payload = getattr(quantity, "unit", None)
        unit_name = str(getattr(unit_payload, "name", "")).strip()
        entity_name = str(getattr(getattr(unit_payload, "entity", None), "name", "")).lower()
        normalized_unit = _normalize_quantulum_temp_unit(unit_name)
        if normalized_unit is None and entity_name != "temperature":
            continue
        if normalized_unit is None:
            continue

        surface = str(getattr(quantity, "surface", "")).strip()
        if not surface:
            continue

        span = getattr(quantity, "span", None)
        if isinstance(span, tuple) and len(span) == 2:
            try:
                start = int(span[0])
                end = int(span[1])
            except Exception:
                start = text.lower().find(surface.lower())
                end = start + len(surface) if start >= 0 else -1
        else:
            start = text.lower().find(surface.lower())
            end = start + len(surface) if start >= 0 else -1

        if start < 0 or end <= start:
            continue

        value_float = float(value)
        value_f = _temperature_value_f(
            value_float,
            unit=normalized_unit,
            unit_backend=unit_backend,
        )
        items.append(
            TemperatureItem(
                value=value_float,
                unit=normalized_unit,
                value_f=value_f,
                original_text=surface,
                is_oven_like=_is_oven_like_context(
                    text,
                    start=start,
                    end=end,
                    mode=ovenlike_mode,
                ),
            )
        )

    return items


def _select_time_matches(
    text: str,
    *,
    backend: str,
) -> list[_TimeMatch]:
    if backend == TIME_BACKEND_REGEX_V1:
        return _extract_times_regex(text)
    if backend == TIME_BACKEND_QUANTULUM3_V1:
        return _extract_times_quantulum3(text, required_for=backend)
    if backend == TIME_BACKEND_HYBRID_V1:
        regex_items = _extract_times_regex(text)
        quantulum_items = _extract_times_quantulum3(text, required_for=backend)
        return regex_items or quantulum_items
    return _extract_times_regex(text)


def _select_temperature_items(
    text: str,
    *,
    backend: str,
    unit_backend: str,
    ovenlike_mode: str,
) -> list[TemperatureItem]:
    if backend == TEMPERATURE_BACKEND_REGEX_V1:
        return _extract_temperature_items_regex(
            text,
            unit_backend=unit_backend,
            ovenlike_mode=ovenlike_mode,
        )
    if backend == TEMPERATURE_BACKEND_QUANTULUM3_V1:
        return _extract_temperature_items_quantulum3(
            text,
            unit_backend=unit_backend,
            ovenlike_mode=ovenlike_mode,
            required_for=backend,
        )
    if backend == TEMPERATURE_BACKEND_HYBRID_V1:
        regex_items = _extract_temperature_items_regex(
            text,
            unit_backend=unit_backend,
            ovenlike_mode=ovenlike_mode,
        )
        quantulum_items = _extract_temperature_items_quantulum3(
            text,
            unit_backend=unit_backend,
            ovenlike_mode=ovenlike_mode,
            required_for=backend,
        )
        return regex_items or quantulum_items
    return _extract_temperature_items_regex(
        text,
        unit_backend=unit_backend,
        ovenlike_mode=ovenlike_mode,
    )


def max_oven_temp_f_from_temperature_items(items: Sequence[TemperatureItem]) -> int | None:
    """Return highest Fahrenheit temp across oven-like temperatures, if any."""
    values = [item.value_f for item in items if item.is_oven_like]
    if not values:
        return None
    return max(values)


def parse_instruction(
    text: str,
    *,
    options: Mapping[str, Any] | InstructionParseOptions | None = None,
) -> InstructionMetadata:
    """Extract time and temperature metadata from an instruction string.

    Current defaults:
    - time backend: regex_v1
    - time strategy: sum_all_v1
    - temperature backend: regex_v1
    """
    resolved_options = normalize_instruction_parse_options(options)

    time_spans = _select_time_matches(text, backend=resolved_options.time_backend)
    total_time = _compute_total_time_seconds(
        text,
        time_spans,
        strategy=resolved_options.time_total_strategy,
    )

    temperature_items = _select_temperature_items(
        text,
        backend=resolved_options.temperature_backend,
        unit_backend=resolved_options.temperature_unit_backend,
        ovenlike_mode=resolved_options.ovenlike_mode,
    )

    first_temperature: TemperatureItem | None = (
        temperature_items[0] if temperature_items else None
    )

    return InstructionMetadata(
        total_time_seconds=total_time,
        time_items=[entry.item for entry in time_spans],
        temperature=first_temperature.value if first_temperature else None,
        temperature_unit=first_temperature.unit if first_temperature else None,
        temperature_text=first_temperature.original_text if first_temperature else None,
        temperature_items=temperature_items,
    )


def parse_instructions(
    steps: list[str],
    *,
    options: Mapping[str, Any] | InstructionParseOptions | None = None,
) -> list[tuple[str, InstructionMetadata]]:
    """Parse multiple instruction steps."""
    return [(step, parse_instruction(step, options=options)) for step in steps]


def fahrenheit_to_celsius(f: float) -> float:
    """Convert Fahrenheit to Celsius, rounded to whole number."""
    return round((f - 32) * 5 / 9)


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit, rounded to whole number."""
    return round(c * 9 / 5 + 32)
