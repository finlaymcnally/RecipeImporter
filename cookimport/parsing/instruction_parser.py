"""Extract time and temperature metadata from recipe instruction text.

Inspired by jlucaspains/sharp-recipe-parser, this module extracts structured
data from instruction strings like "Bake at 400F for 30 minutes".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TimeItem:
    """A single time extraction from instruction text."""

    seconds: int
    original_text: str


@dataclass
class InstructionMetadata:
    """Extracted metadata from an instruction string."""

    total_time_seconds: int | None = None
    time_items: list[TimeItem] = field(default_factory=list)
    temperature: float | None = None
    temperature_unit: Literal["fahrenheit", "celsius"] | None = None
    temperature_text: str | None = None


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


def _parse_time_unit(unit: str) -> int:
    """Get the multiplier for a time unit string."""
    return _TIME_MULTIPLIERS.get(unit.lower(), 60)  # Default to minutes


def _normalize_temp_unit(unit_text: str) -> Literal["fahrenheit", "celsius"]:
    """Normalize temperature unit text to standard form."""
    text = unit_text.lower().strip()
    if "c" in text and "f" not in text:
        return "celsius"
    return "fahrenheit"


def _extract_times(text: str) -> list[TimeItem]:
    """Extract all time durations from text."""
    items: list[TimeItem] = []
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

        items.append(TimeItem(seconds=seconds, original_text=match.group(0).strip()))

    return items


def _extract_temperature(text: str) -> tuple[float | None, Literal["fahrenheit", "celsius"] | None, str | None]:
    """Extract temperature from text.

    Returns (value, unit, original_text) or (None, None, None) if not found.
    """
    match = _TEMP_PATTERN.search(text)
    if not match:
        return None, None, None

    value = float(match.group(1))
    unit = _normalize_temp_unit(match.group(2))
    return value, unit, match.group(0).strip()


def parse_instruction(text: str) -> InstructionMetadata:
    """Extract time and temperature metadata from an instruction string.

    Args:
        text: An instruction string like "Bake at 400F for 30 minutes"

    Returns:
        InstructionMetadata with extracted values, or empty metadata if nothing found.

    Examples:
        >>> meta = parse_instruction("Bake at 400F for 30 minutes")
        >>> meta.temperature
        400.0
        >>> meta.temperature_unit
        'fahrenheit'
        >>> meta.total_time_seconds
        1800
    """
    time_items = _extract_times(text)
    total_time = sum(item.seconds for item in time_items) if time_items else None

    temp_value, temp_unit, temp_text = _extract_temperature(text)

    return InstructionMetadata(
        total_time_seconds=total_time,
        time_items=time_items,
        temperature=temp_value,
        temperature_unit=temp_unit,
        temperature_text=temp_text,
    )


def parse_instructions(steps: list[str]) -> list[tuple[str, InstructionMetadata]]:
    """Parse multiple instruction steps.

    Args:
        steps: List of instruction text strings.

    Returns:
        List of (text, metadata) tuples for each step.
    """
    return [(step, parse_instruction(step)) for step in steps]


def fahrenheit_to_celsius(f: float) -> float:
    """Convert Fahrenheit to Celsius, rounded to whole number."""
    return round((f - 32) * 5 / 9)


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit, rounded to whole number."""
    return round(c * 9 / 5 + 32)
