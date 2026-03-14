from __future__ import annotations

import re
from typing import Any, Mapping

from cookimport.core.models import HowToStep, RecipeCandidate, RecipeComment
from cookimport.parsing.ingredients import (
    normalize_ingredient_parser_options,
    parse_ingredient_line,
)
from cookimport.parsing.instruction_parser import (
    max_oven_temp_f_from_temperature_items,
    normalize_instruction_parse_options,
    parse_instruction,
)
from cookimport.parsing.sections import extract_instruction_sections, normalize_section_key
from cookimport.parsing.step_segmentation import (
    DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
    DEFAULT_INSTRUCTION_STEP_SEGMENTER,
    segment_instruction_steps,
)
from cookimport.parsing.yield_extraction import derive_yield_fields
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
_UNTITLED_RECIPE_TITLE = "Untitled Recipe"
_MAX_RECIPE_LINE_MULTIPLIER = 100.0
_DEFAULT_SECTION_KEY = "main"
_TITLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_TITLE_PROSE_CUE_RE = re.compile(
    r"\b(?:i|my|me|we|our|chapter|preface|introduction)\b",
    re.IGNORECASE,
)


def _normalize_nonempty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def apply_line_role_spans_to_recipes(
    *,
    conversion_result: Any,
    spans: list[Any],
) -> dict[str, Any]:
    """Apply projected canonical line-role spans onto recipe draft fields."""
    recipes = getattr(conversion_result, "recipes", None)
    if not isinstance(recipes, list):
        return {"recipes_applied": 0, "recipe_count": 0}

    grouped: dict[int, list[Any]] = {}
    for span in spans:
        recipe_index = _coerce_span_int(span, "recipe_index")
        if recipe_index is None:
            continue
        if recipe_index < 0 or recipe_index >= len(recipes):
            continue
        grouped.setdefault(recipe_index, []).append(span)

    recipes_applied = 0
    for recipe_index, rows in grouped.items():
        recipe = recipes[recipe_index]
        ordered = sorted(rows, key=lambda row: _coerce_span_int(row, "line_index") or 0)

        yield_lines = _select_line_role_span_texts(ordered, "YIELD_LINE")
        ingredient_lines = _select_line_role_span_texts(ordered, "INGREDIENT_LINE")
        instruction_lines = _select_line_role_span_texts(
            ordered, "HOWTO_SECTION", "INSTRUCTION_LINE"
        )
        note_lines = _select_line_role_span_texts(ordered, "RECIPE_NOTES")
        current_name = str(getattr(recipe, "name", "") or "").strip()
        current_name_is_credible = _looks_credible_recipe_name(current_name)
        title_line = _select_guarded_title_span_text(ordered, "RECIPE_TITLE")
        variant_line = _select_guarded_title_span_text(ordered, "RECIPE_VARIANT")

        touched = False
        if title_line and (not current_name_is_credible or title_line != current_name):
            recipe.name = title_line
            touched = True
        elif variant_line and not current_name_is_credible:
            recipe.name = variant_line
            touched = True
        if yield_lines:
            recipe.recipe_yield = yield_lines[0]
            touched = True
        if ingredient_lines:
            recipe.ingredients = ingredient_lines
            touched = True
        if instruction_lines:
            recipe.instructions = instruction_lines
            touched = True
        if note_lines:
            recipe.comments = [RecipeComment(text=text) for text in note_lines]
            touched = True
        if touched:
            recipes_applied += 1

    return {"recipes_applied": recipes_applied, "recipe_count": len(recipes)}


def _coerce_span_int(span: Any, key: str) -> int | None:
    value = _coerce_span_value(span, key)
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_span_value(span: Any, key: str) -> Any:
    if isinstance(span, Mapping):
        return span.get(key)
    return getattr(span, key, None)


def _select_line_role_span_texts(rows: list[Any], *labels: str) -> list[str]:
    allowed = {label for label in labels}
    selected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        label = str(_coerce_span_value(row, "label") or "").strip().upper()
        if label not in allowed:
            continue
        text = str(_coerce_span_value(row, "text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        selected.append(text)
    return selected


def _coerce_span_bool(span: Any, key: str) -> bool:
    value = _coerce_span_value(span, key)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_title_boundary_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    words = _TITLE_WORD_RE.findall(stripped)
    if len(words) >= 10 and any(ch in stripped for ch in ",.;:"):
        return True
    if _TITLE_PROSE_CUE_RE.search(stripped) and len(words) >= 6:
        return True
    return False


def _looks_credible_recipe_name(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or stripped == _UNTITLED_RECIPE_TITLE:
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    if _SECTION_HEADER_RE.match(stripped):
        return False
    words = _TITLE_WORD_RE.findall(stripped)
    if not (2 <= len(words) <= 12):
        return False
    if _looks_title_boundary_prose(stripped):
        return False
    return True


def _span_has_recipe_boundary_signal(row: Any) -> bool:
    if not _coerce_span_bool(row, "within_recipe_span"):
        return False
    label = str(_coerce_span_value(row, "label") or "").strip().upper()
    return label in {
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "HOWTO_SECTION",
        "YIELD_LINE",
        "TIME_LINE",
    }


def _is_guarded_title_span_candidate(
    row: Any,
    *,
    rows: list[Any],
    position: int,
    kind: str,
) -> bool:
    text = str(_coerce_span_value(row, "text") or "").strip()
    if not text or not _coerce_span_bool(row, "within_recipe_span"):
        return False
    if kind == "variant" and not _VARIANT_PREFIX_RE.match(text):
        return False
    if kind == "title" and (
        text[-1:] in {".", "!", "?"}
        or _SECTION_HEADER_RE.match(text)
        or _looks_title_boundary_prose(text)
    ):
        return False

    upper = min(len(rows), position + (4 if kind == "title" else 3) + 1)
    for check in range(position + 1, upper):
        if _span_has_recipe_boundary_signal(rows[check]):
            return True
    if kind == "variant":
        lower = max(0, position - 2)
        for check in range(lower, position):
            if _span_has_recipe_boundary_signal(rows[check]):
                return True
    return False


def _select_guarded_title_span_text(rows: list[Any], label: str) -> str | None:
    kind = "variant" if label == "RECIPE_VARIANT" else "title"
    for position, row in enumerate(rows):
        if str(_coerce_span_value(row, "label") or "").strip().upper() != label:
            continue
        text = str(_coerce_span_value(row, "text") or "").strip()
        if not text:
            continue
        if _is_guarded_title_span_candidate(
            row,
            rows=rows,
            position=position,
            kind=kind,
        ):
            return text
    return None

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

    linked_recipe_id = _normalize_nonempty_text(sanitized.get("linked_recipe_id"))
    sanitized["linked_recipe_id"] = linked_recipe_id
    has_linked_recipe = linked_recipe_id is not None
    input_qty = _to_positive_number(sanitized.get("input_qty"))

    if has_linked_recipe:
        sanitized["ingredient_id"] = None
        sanitized["input_unit_id"] = None
        if input_qty is not None and input_qty > _MAX_RECIPE_LINE_MULTIPLIER:
            input_qty = _MAX_RECIPE_LINE_MULTIPLIER
        sanitized["input_qty"] = input_qty
        if quantity_kind not in {"exact", "approximate", "unquantified"} or input_qty is None:
            sanitized["quantity_kind"] = "exact"
        else:
            sanitized["quantity_kind"] = quantity_kind
        return sanitized

    sanitized["linked_recipe_id"] = None
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


def _convert_ingredient(
    text: str,
    *,
    parser_options: Mapping[str, str],
) -> dict[str, Any]:
    """Parse and convert an ingredient string to structured output."""
    parsed = parse_ingredient_line(
        text,
        ingredient_text_fix_backend=parser_options["ingredient_text_fix_backend"],
        ingredient_pre_normalize_mode=parser_options["ingredient_pre_normalize_mode"],
        ingredient_packaging_mode=parser_options["ingredient_packaging_mode"],
        ingredient_parser_backend=parser_options["ingredient_parser_backend"],
        ingredient_unit_canonicalizer=parser_options["ingredient_unit_canonicalizer"],
        ingredient_missing_unit_policy=parser_options["ingredient_missing_unit_policy"],
    )
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


def _resolve_instruction_step_segmentation_options(
    options: Mapping[str, Any] | None,
) -> tuple[str, str]:
    from cookimport.config.codex_decision import bucket1_fixed_behavior

    fixed_behavior = bucket1_fixed_behavior()
    if not isinstance(options, Mapping):
        return (
            fixed_behavior.instruction_step_segmentation_policy,
            fixed_behavior.instruction_step_segmenter,
        )

    policy = str(
        options.get(
            "instruction_step_segmentation_policy",
            fixed_behavior.instruction_step_segmentation_policy,
        )
    ).strip().lower().replace("-", "_")
    segmenter = str(
        options.get(
            "instruction_step_segmenter",
            fixed_behavior.instruction_step_segmenter,
        )
    ).strip().lower().replace("-", "_")
    return (policy, segmenter)


def _resolve_p6_emit_metadata_debug(options: Mapping[str, Any] | None) -> bool:
    if not isinstance(options, Mapping):
        return False
    value = options.get("p6_emit_metadata_debug", False)
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _derive_ingredient_section_keys(ingredient_lines: list[dict[str, Any]]) -> list[str]:
    """Derive per-line section keys from parsed ingredient lines."""
    section_keys: list[str] = []
    active_key = _DEFAULT_SECTION_KEY
    for line in ingredient_lines:
        if line.get("quantity_kind") == "section_header":
            label = line.get("raw_ingredient_text") or line.get("raw_text") or ""
            active_key = normalize_section_key(str(label)) or active_key
            section_keys.append(active_key)
            continue
        section_keys.append(active_key)
    return section_keys


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


def recipe_candidate_to_draft_v1(
    candidate: RecipeCandidate,
    *,
    ingredient_parser_options: Mapping[str, Any] | None = None,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a RecipeCandidate into cookbook3 format (internal model: RecipeDraftV1)."""

    recipe_title = candidate.name.strip() if candidate.name else ""
    if not recipe_title:
        recipe_title = _UNTITLED_RECIPE_TITLE

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

    yield_fields = derive_yield_fields(candidate, payload=instruction_step_options)
    yield_debug = yield_fields.pop("_p6_yield_debug", None)

    recipe_meta: dict[str, Any] = {
        "title": recipe_title,
        "description": candidate.description,
        "notes": notes_val,
        "confidence": candidate.confidence,
        **yield_fields,
    }

    # 2. Prepare Steps & Ingredients
    # Strategy: Assign ingredients to steps with deterministic matching.
    
    # Convert all ingredients
    parser_options = normalize_ingredient_parser_options(ingredient_parser_options)
    all_ingredient_lines = [
        _convert_ingredient(ing, parser_options=parser_options)
        for ing in candidate.ingredients
    ]

    # Convert all instructions
    steps_data: list[dict[str, Any]] = []

    raw_instructions = candidate.instructions
    if not raw_instructions:
        # If no instructions, create a dummy one so output has a step.
        raw_instructions = ["See original recipe for details."]

    instruction_texts = [_convert_instruction(instr) for instr in raw_instructions]
    segmentation_policy, segmentation_backend = _resolve_instruction_step_segmentation_options(
        instruction_step_options
    )
    instruction_texts = segment_instruction_steps(
        instruction_texts,
        policy=segmentation_policy,
        backend=segmentation_backend,
    )
    variants, instruction_texts = _split_variants(instruction_texts)
    if variants:
        recipe_meta["variants"] = variants

    instruction_sections = extract_instruction_sections(instruction_texts)
    instruction_texts = instruction_sections.lines_no_headers
    step_section_key_by_step = instruction_sections.section_key_by_line

    if not instruction_texts:
        instruction_texts = ["See original recipe for details."]
        step_section_key_by_step = [_DEFAULT_SECTION_KEY]

    ingredient_section_key_by_line = _derive_ingredient_section_keys(all_ingredient_lines)

    step_ingredient_lines, assignment_debug = assign_ingredient_lines_to_steps(
        instruction_texts,
        all_ingredient_lines,
        ingredient_section_key_by_line=ingredient_section_key_by_line,
        step_section_key_by_step=step_section_key_by_step,
        debug=True,
    )

    instruction_parse_options = normalize_instruction_parse_options(instruction_step_options)
    emit_p6_metadata_debug = _resolve_p6_emit_metadata_debug(instruction_step_options)
    p6_step_debug: list[dict[str, Any]] = []
    total_step_time_seconds = 0
    max_oven_temp_f: int | None = None
    for idx, text in enumerate(instruction_texts):
        step_ingredients_raw = step_ingredient_lines[idx] if idx < len(step_ingredient_lines) else []
        step_ingredients = _sanitize_staging_lines(step_ingredients_raw)

        # Extract time/temperature metadata from instruction text
        instr_meta = parse_instruction(text, options=instruction_parse_options)
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
        if instr_meta.temperature_items:
            step_entry["temperature_items"] = [
                {
                    "value": item.value,
                    "unit": item.unit,
                    "value_f": item.value_f,
                    "original_text": item.original_text,
                    "is_oven_like": item.is_oven_like,
                }
                for item in instr_meta.temperature_items
            ]

        step_max = max_oven_temp_f_from_temperature_items(instr_meta.temperature_items)
        if step_max is not None:
            if max_oven_temp_f is None:
                max_oven_temp_f = step_max
            else:
                max_oven_temp_f = max(max_oven_temp_f, step_max)

        if emit_p6_metadata_debug:
            p6_step_debug.append(
                {
                    "step_index": idx,
                    "instruction": text,
                    "time_seconds": instr_meta.total_time_seconds,
                    "time_items": [
                        {
                            "seconds": item.seconds,
                            "original_text": item.original_text,
                        }
                        for item in instr_meta.time_items
                    ],
                    "temperature_items": step_entry.get("temperature_items", []),
                }
            )

        steps_data.append(step_entry)

    # Find any ingredients that weren't assigned to any step
    assigned_indices = {
        assignment.ingredient_index
        for assignment in assignment_debug.assignments
        if assignment.assigned_steps
    }

    unassigned_raw = [
        line for idx, line in enumerate(all_ingredient_lines)
        if idx not in assigned_indices
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
    if max_oven_temp_f is not None:
        recipe_meta["max_oven_temp_f"] = max_oven_temp_f

    payload: dict[str, Any] = {
        "schema_v": 1,
        "source": _normalize_nonempty_text(candidate.source),
        "recipe": recipe_meta,
        "steps": steps_data,
    }
    if emit_p6_metadata_debug:
        payload["_p6_debug"] = {
            "time_backend": instruction_parse_options.time_backend,
            "time_total_strategy": instruction_parse_options.time_total_strategy,
            "temperature_backend": instruction_parse_options.temperature_backend,
            "temperature_unit_backend": instruction_parse_options.temperature_unit_backend,
            "ovenlike_mode": instruction_parse_options.ovenlike_mode,
            "yield_debug": yield_debug,
            "max_oven_temp_f": max_oven_temp_f,
            "steps": p6_step_debug,
        }
    return payload
