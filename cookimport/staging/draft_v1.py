from __future__ import annotations

import uuid
from typing import Any

from cookimport.core.models import HowToStep, RecipeCandidate


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _convert_ingredient(text: str) -> dict[str, Any]:
    return {
        "ingredient_id": _generate_uuid(),
        "quantity_kind": "unquantified",
        "input_qty": None,
        "input_unit_id": None,
        "note": None,
        "raw_text": text,
        "is_optional": False,
    }


def _convert_instruction(instruction: str | HowToStep) -> str:
    if isinstance(instruction, HowToStep):
        return instruction.text
    return str(instruction)


def recipe_candidate_to_draft_v1(candidate: RecipeCandidate) -> dict[str, Any]:
    """Convert a RecipeCandidate into RecipeDraftV1 format."""
    
    # 1. Prepare Recipe object
    notes_parts = []
    if candidate.source_url:
        notes_parts.append(f"Source: {candidate.source_url}")
    if candidate.tags:
        notes_parts.append(f"Tags: {', '.join(candidate.tags)}")
    notes_val = "\n".join(notes_parts) if notes_parts else None

    recipe_meta = {
        "title": candidate.name,
        "description": candidate.description,
        "notes": notes_val,
        "yield_units": 1, # Default
        "yield_phrase": candidate.recipe_yield,
        "yield_unit_name": None,
        "yield_detail": None,
    }

    # 2. Prepare Steps & Ingredients
    # Strategy: Attach all ingredients to the first step.
    
    # Convert all ingredients
    all_ingredient_lines = [
        _convert_ingredient(ing) for ing in candidate.ingredients
    ]

    # Convert all instructions
    steps_data: list[dict[str, Any]] = []
    
    raw_instructions = candidate.instructions
    if not raw_instructions:
        # If no instructions, create a dummy one to hold ingredients
        raw_instructions = ["See original recipe for details."]

    for idx, instr in enumerate(raw_instructions):
        text = _convert_instruction(instr)
        step_ingredients = []
        
        # Attach all ingredients to the first step
        if idx == 0:
            step_ingredients = all_ingredient_lines
            
        steps_data.append({
            "instruction": text,
            "ingredient_lines": step_ingredients
        })

    return {
        "schema_v": 1,
        "recipe": recipe_meta,
        "steps": steps_data,
    }
