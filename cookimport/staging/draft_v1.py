from __future__ import annotations

import re
import uuid
from typing import Any

from cookimport.core.models import HowToStep, RecipeCandidate
from cookimport.parsing.ingredients import parse_ingredient_line
from cookimport.parsing.tips import extract_recipe_specific_notes
from cookimport.parsing.step_ingredients import assign_ingredient_lines_to_steps

_VARIANT_PREFIX_RE = re.compile(r"^\s*variations?\b|^\s*variants?\b", re.IGNORECASE)
_LOWERCASE_FIELDS = ("raw_text", "raw_ingredient_text", "raw_unit_text", "preparation", "note")


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _convert_ingredient(text: str) -> dict[str, Any]:
    """Parse and convert an ingredient string to structured output."""
    parsed = parse_ingredient_line(text)
    for key in _LOWERCASE_FIELDS:
        value = parsed.get(key)
        if isinstance(value, str):
            parsed[key] = value.lower()
    return {
        "ingredient_id": _generate_uuid(),
        **parsed,
    }


def _convert_instruction(instruction: str | HowToStep) -> str:
    if isinstance(instruction, HowToStep):
        return instruction.text
    return str(instruction)

def _split_variants(instructions: list[str]) -> tuple[list[str], list[str]]:
    variants: list[str] = []
    remaining: list[str] = []
    for instruction in instructions:
        text = instruction.strip()
        if _VARIANT_PREFIX_RE.match(text):
            variants.append(text)
        else:
            remaining.append(instruction)
    return variants, remaining


def recipe_candidate_to_draft_v1(candidate: RecipeCandidate) -> dict[str, Any]:
    """Convert a RecipeCandidate into RecipeDraftV1 format."""
    
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

    for idx, text in enumerate(instruction_texts):
        step_ingredients = step_ingredient_lines[idx] if idx < len(step_ingredient_lines) else []

        steps_data.append(
            {
                "instruction": text,
                "ingredient_lines": step_ingredients,
            }
        )

    return {
        "schema_v": 1,
        "recipe": recipe_meta,
        "steps": steps_data,
    }
