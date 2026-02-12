"""RecipeSignalPack: normalized signals extracted from a recipe for tagging."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RecipeSignalPack:
    recipe_id: str | None = None
    title: str = ""
    description: str = ""
    notes: str = ""
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    total_time_minutes: int | None = None
    yield_phrase: str | None = None
    max_oven_temp_f: int | None = None
    spice_level: int | None = None
    attention_level: str | None = None
    cleanup_level: str | None = None


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_text_for_matching(s: str) -> str:
    """Lower-case, strip accents, replace punctuation with spaces, collapse whitespace."""
    if not s:
        return ""
    # NFD decompose then strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = stripped.lower()
    no_punct = _PUNCT_RE.sub(" ", lower)
    return _MULTI_SPACE_RE.sub(" ", no_punct).strip()


def _seconds_to_minutes(seconds: Any) -> int | None:
    """Convert seconds (int/float) to minutes, returning None if invalid."""
    if seconds is None:
        return None
    try:
        val = int(seconds)
        if val > 0:
            return max(1, val // 60)
    except (TypeError, ValueError):
        pass
    return None


def _extract_ingredient_texts(steps: list[dict[str, Any]]) -> list[str]:
    """Pull raw_text from all ingredient lines across all steps."""
    texts: list[str] = []
    for step in steps:
        for line in step.get("ingredient_lines", []):
            raw = line.get("raw_text") or line.get("raw_ingredient_text") or ""
            if raw.strip():
                texts.append(raw.strip())
    return texts


def _extract_instruction_texts(steps: list[dict[str, Any]]) -> list[str]:
    """Pull instruction text from all steps."""
    texts: list[str] = []
    for step in steps:
        instr = step.get("instruction", "")
        if instr.strip():
            texts.append(instr.strip())
    return texts


def _extract_max_temp(steps: list[dict[str, Any]]) -> int | None:
    """Find the highest oven temperature in Fahrenheit across steps."""
    max_temp: int | None = None
    for step in steps:
        temp = step.get("temperature")
        unit = step.get("temperature_unit", "")
        if temp is not None and unit and "fahren" in unit.lower():
            t = int(temp)
            if max_temp is None or t > max_temp:
                max_temp = t
    return max_temp


def signals_from_draft_json(path: Path) -> RecipeSignalPack:
    """Extract a RecipeSignalPack from a cookbook3 draft JSON file."""
    with open(path) as f:
        data = json.load(f)

    recipe = data.get("recipe", {})
    steps = data.get("steps", [])

    cook_time_minutes = _seconds_to_minutes(recipe.get("cook_time_seconds"))

    return RecipeSignalPack(
        recipe_id=None,
        title=recipe.get("title") or "",
        description=recipe.get("description") or "",
        notes=recipe.get("notes") or "",
        ingredients=_extract_ingredient_texts(steps),
        instructions=_extract_instruction_texts(steps),
        prep_time_minutes=None,  # Not in draft v1; may be computed later
        cook_time_minutes=cook_time_minutes,
        total_time_minutes=cook_time_minutes,  # Best approximation from draft
        yield_phrase=recipe.get("yield_phrase"),
        max_oven_temp_f=_extract_max_temp(steps),
    )


def signals_from_dict(data: dict[str, Any]) -> RecipeSignalPack:
    """Build a RecipeSignalPack from a plain dictionary (for test fixtures)."""
    return RecipeSignalPack(
        recipe_id=data.get("recipe_id"),
        title=data.get("title", ""),
        description=data.get("description", ""),
        notes=data.get("notes", ""),
        ingredients=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        prep_time_minutes=data.get("prep_time_minutes"),
        cook_time_minutes=data.get("cook_time_minutes"),
        total_time_minutes=data.get("total_time_minutes"),
        yield_phrase=data.get("yield_phrase"),
        max_oven_temp_f=data.get("max_oven_temp_f"),
        spice_level=data.get("spice_level"),
        attention_level=data.get("attention_level"),
        cleanup_level=data.get("cleanup_level"),
    )
