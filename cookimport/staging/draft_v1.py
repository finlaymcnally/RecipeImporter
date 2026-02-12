from __future__ import annotations

import re
from typing import Any

from cookimport.core.models import HowToStep, RecipeCandidate
from cookimport.parsing.ingredients import parse_ingredient_line
from cookimport.parsing.instruction_parser import parse_instruction
from cookimport.parsing.tips import extract_recipe_specific_notes
from cookimport.parsing.step_ingredients import assign_ingredient_lines_to_steps

_VARIANT_HEADER_RE = re.compile(r"^\s*variations?\s*:?\s*$|^\s*variants?\s*:?\s*$", re.IGNORECASE)
_VARIANT_PREFIX_RE = re.compile(r"^\s*variations?\b|^\s*variants?\b", re.IGNORECASE)
_SECTION_HEADER_RE = re.compile(
    r"^\s*(ingredients?|instructions?|directions?|method|preparation|notes?|tips?|serving)\s*:?\s*$",
    re.IGNORECASE,
)
_LOWERCASE_FIELDS = ("raw_text", "raw_ingredient_text", "raw_unit_text", "preparation", "note")
_MISSING_INGREDIENT_LABEL = "__missing_ingredient__"

def _to_positive_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 0:
            return number
    return None


def _fallback_ingredient_label(parsed: dict[str, Any]) -> str:
    for key in ("raw_ingredient_text", "raw_text"):
        value = parsed.get(key)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return _MISSING_INGREDIENT_LABEL


def _sanitize_staging_line(line: dict[str, Any]) -> dict[str, Any] | None:
    quantity_kind = line.get("quantity_kind")
    if quantity_kind == "section_header":
        return None

    sanitized = dict(line)

    linked_recipe_id = sanitized.get("linked_recipe_id")
    has_linked_recipe = isinstance(linked_recipe_id, str) and bool(linked_recipe_id.strip())
    input_qty = _to_positive_number(sanitized.get("input_qty"))

    if has_linked_recipe:
        sanitized["ingredient_id"] = None
        sanitized["input_unit_id"] = None
        sanitized["input_qty"] = input_qty
        if input_qty is None:
            sanitized["quantity_kind"] = "exact"
        return sanitized

    if quantity_kind not in {"exact", "approximate", "unquantified"}:
        quantity_kind = "unquantified"

    if quantity_kind == "unquantified":
        sanitized["input_qty"] = None
        sanitized["input_unit_id"] = None
    else:
        if input_qty is None:
            quantity_kind = "unquantified"
            sanitized["input_qty"] = None
            sanitized["input_unit_id"] = None
        else:
            sanitized["input_qty"] = input_qty
            # Units are unresolved at export time; raw_unit_text carries source data.
            sanitized["input_unit_id"] = None

    sanitized["quantity_kind"] = quantity_kind
    sanitized["ingredient_id"] = _fallback_ingredient_label(sanitized)
    return sanitized


def _sanitize_staging_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for line in lines:
        normalized = _sanitize_staging_line(line)
        if normalized is not None:
            sanitized.append(normalized)
    return sanitized


def _convert_ingredient(text: str) -> dict[str, Any]:
    """Parse and convert an ingredient string to structured output."""
    parsed = parse_ingredient_line(text)
    for key in _LOWERCASE_FIELDS:
        value = parsed.get(key)
        if isinstance(value, str):
            parsed[key] = value.lower()

    quantity_kind = parsed.get("quantity_kind")
    input_qty = _to_positive_number(parsed.get("input_qty"))
    if quantity_kind == "section_header":
        pass
    elif quantity_kind == "unquantified":
        input_qty = None
    elif input_qty is None:
        # Staging contract requires exact/approximate lines to include a positive qty.
        quantity_kind = "unquantified"
    parsed["quantity_kind"] = quantity_kind
    parsed["input_qty"] = input_qty

    # Unresolved units should be null and reviewed in staging via raw_unit_text.
    parsed["input_unit_id"] = None

    # Staging requires a non-empty string placeholder when unresolved.
    parsed["ingredient_id"] = _fallback_ingredient_label(parsed)

    return parsed


def _convert_instruction(instruction: str | HowToStep) -> str:
    if isinstance(instruction, HowToStep):
        return instruction.text
    return str(instruction)


def _split_variants(instructions: list[str]) -> tuple[list[str], list[str]]:
    """
    Extract variant instructions from the instruction list.

    Handles two patterns:
    1. Single lines starting with "Variation:" or "Variant:"
    2. Multi-block variations where a header (e.g., "Variation") is followed
       by content lines (often with bullet points) until a new section starts.
    """
    variants: list[str] = []
    remaining: list[str] = []
    in_variant_section = False

    for instruction in instructions:
        text = instruction.strip()

        # Check if this is a standalone variation header (header-only line)
        if _VARIANT_HEADER_RE.match(text):
            in_variant_section = True
            # Don't add the header itself to variants, just start collecting
            continue

        # Check if we hit a new section header that ends the variant section
        if in_variant_section and _SECTION_HEADER_RE.match(text):
            in_variant_section = False
            remaining.append(instruction)
            continue

        # If in variant section, add content to variants
        if in_variant_section:
            variants.append(text)
            continue

        # Check if line starts with variation prefix (inline variant)
        if _VARIANT_PREFIX_RE.match(text):
            variants.append(text)
            continue

        remaining.append(instruction)

    return variants, remaining


def recipe_candidate_to_draft_v1(candidate: RecipeCandidate) -> dict[str, Any]:
    """Convert a RecipeCandidate into cookbook3 format (internal model: RecipeDraftV1)."""
    
    # 1. Prepare Recipe object
    notes_parts = []
    if candidate.source_url:
        notes_parts.append(f"Source: {candidate.source_url}")
    if candidate.tags:
        notes_parts.append(f"Tags: {', '.join(candidate.tags)}")
    recipe_notes = extract_recipe_specific_notes(candidate)
    if recipe_notes:
        notes_parts.extend(recipe_notes)
    notes_val = "\n".join(notes_parts) if notes_parts else None

    recipe_meta: dict[str, Any] = {
        "title": candidate.name,
        "description": candidate.description,
        "notes": notes_val,
        "yield_units": 1, # Default
        "yield_phrase": candidate.recipe_yield,
        "yield_unit_name": None,
        "yield_detail": None,
        "confidence": candidate.confidence,
    }

    # 2. Prepare Steps & Ingredients
    # Strategy: Assign ingredients to steps with deterministic matching.
    
    # Convert all ingredients
    all_ingredient_lines = [
        _convert_ingredient(ing) for ing in candidate.ingredients
    ]

    # Convert all instructions
    steps_data: list[dict[str, Any]] = []

    raw_instructions = candidate.instructions
    if not raw_instructions:
        # If no instructions, create a dummy one so output has a step.
        raw_instructions = ["See original recipe for details."]

    instruction_texts = [_convert_instruction(instr) for instr in raw_instructions]
    variants, instruction_texts = _split_variants(instruction_texts)
    if variants:
        recipe_meta["variants"] = variants

    if not instruction_texts:
        instruction_texts = ["See original recipe for details."]

    step_ingredient_lines = assign_ingredient_lines_to_steps(
        instruction_texts,
        all_ingredient_lines,
    )

    total_step_time_seconds = 0
    for idx, text in enumerate(instruction_texts):
        step_ingredients_raw = step_ingredient_lines[idx] if idx < len(step_ingredient_lines) else []
        step_ingredients = _sanitize_staging_lines(step_ingredients_raw)

        # Extract time/temperature metadata from instruction text
        instr_meta = parse_instruction(text)
        step_entry: dict[str, Any] = {
            "instruction": text,
            "ingredient_lines": step_ingredients,
        }
        if instr_meta.total_time_seconds is not None:
            step_entry["time_seconds"] = instr_meta.total_time_seconds
            total_step_time_seconds += instr_meta.total_time_seconds
        if instr_meta.temperature is not None:
            step_entry["temperature"] = instr_meta.temperature
            step_entry["temperature_unit"] = instr_meta.temperature_unit

        steps_data.append(step_entry)

    # Find any ingredients that weren't assigned to any step
    assigned_texts: set[str] = set()
    for step in steps_data:
        for line in step.get("ingredient_lines", []):
            assigned_texts.add(line.get("raw_ingredient_text", ""))

    unassigned_raw = [
        line for line in all_ingredient_lines
        if line.get("raw_ingredient_text", "") not in assigned_texts
        and line.get("quantity_kind") != "section_header"
    ]
    unassigned = _sanitize_staging_lines(unassigned_raw)

    # If there are unassigned ingredients, insert a prep step at the beginning
    if unassigned:
        prep_step: dict[str, Any] = {
            "instruction": "Gather and prepare ingredients.",
            "ingredient_lines": unassigned,
        }
        steps_data.insert(0, prep_step)

    # Compute cook_time from step times if not already present
    if total_step_time_seconds > 0 and not candidate.cook_time:
        recipe_meta["cook_time_seconds"] = total_step_time_seconds

    return {
        "schema_v": 1,
        "source": candidate.source,
        "recipe": recipe_meta,
        "steps": steps_data,
    }
