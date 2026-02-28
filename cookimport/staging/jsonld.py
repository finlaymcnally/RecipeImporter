from __future__ import annotations

from typing import Any, Mapping

from cookimport.core.models import HowToStep, RecipeCandidate
from cookimport.parsing.sections import (
    extract_ingredient_sections,
    extract_instruction_sections,
)
from cookimport.parsing.step_segmentation import (
    DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
    DEFAULT_INSTRUCTION_STEP_SEGMENTER,
    segment_instruction_steps,
    should_fallback_segment,
)


def _serialize_instruction_item(item: object) -> dict[str, Any]:
    if isinstance(item, HowToStep):
        return item.model_dump(by_alias=True, exclude_none=True)
    return {"@type": "HowToStep", "text": str(item)}


def _section_display_name(key: str, displays: dict[str, str]) -> str:
    display_name = displays.get(key)
    if display_name:
        return display_name
    return key.replace("_", " ").strip().title() or "Main"


def _resolve_instruction_step_segmentation_options(
    options: Mapping[str, Any] | None,
) -> tuple[str, str]:
    if not isinstance(options, Mapping):
        return (
            DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
            DEFAULT_INSTRUCTION_STEP_SEGMENTER,
        )

    policy = str(
        options.get(
            "instruction_step_segmentation_policy",
            DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
        )
    ).strip().lower().replace("-", "_")
    segmenter = str(
        options.get(
            "instruction_step_segmenter",
            DEFAULT_INSTRUCTION_STEP_SEGMENTER,
        )
    ).strip().lower().replace("-", "_")
    return (policy, segmenter)


def _group_instruction_steps(
    serialized_steps: list[dict[str, Any]],
    *,
    section_keys: list[str],
    section_display_by_key: dict[str, str],
) -> list[object]:
    if not serialized_steps:
        return []

    if len(section_keys) != len(serialized_steps):
        return serialized_steps

    ordered_unique_keys: list[str] = []
    for key in section_keys:
        if key not in ordered_unique_keys:
            ordered_unique_keys.append(key)

    if len(ordered_unique_keys) <= 1:
        return serialized_steps

    grouped: list[dict[str, Any]] = []
    current_key: str | None = None
    current_steps: list[dict[str, Any]] = []

    for step, key in zip(serialized_steps, section_keys):
        if key != current_key:
            if current_key is not None:
                grouped.append(
                    {
                        "@type": "HowToSection",
                        "name": _section_display_name(current_key, section_display_by_key),
                        "itemListElement": current_steps,
                    }
                )
            current_key = key
            current_steps = [step]
            continue
        current_steps.append(step)

    if current_key is not None:
        grouped.append(
            {
                "@type": "HowToSection",
                "name": _section_display_name(current_key, section_display_by_key),
                "itemListElement": current_steps,
            }
        )

    return grouped


def _build_recipe_instructions(
    candidate: RecipeCandidate,
    *,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> list[object]:
    if not candidate.instructions:
        return []

    raw_items = list(candidate.instructions)
    raw_texts = [item.text if isinstance(item, HowToStep) else str(item) for item in raw_items]
    segmentation_policy, segmentation_backend = _resolve_instruction_step_segmentation_options(
        instruction_step_options
    )
    should_segment = (
        segmentation_policy == "always"
        or (
            segmentation_policy == "auto"
            and should_fallback_segment(raw_texts)
        )
    )

    if should_segment:
        segmented_texts = segment_instruction_steps(
            raw_texts,
            policy=segmentation_policy,
            backend=segmentation_backend,
        )
        sectioned = extract_instruction_sections(segmented_texts)
        serialized_steps = [
            _serialize_instruction_item(text)
            for text in sectioned.lines_no_headers
        ]
        return _group_instruction_steps(
            serialized_steps,
            section_keys=sectioned.section_key_by_line,
            section_display_by_key=sectioned.section_display_by_key,
        )

    sectioned = extract_instruction_sections(raw_texts)
    header_indices = {hit.original_index for hit in sectioned.header_hits}
    serialized_steps = [
        _serialize_instruction_item(item)
        for index, item in enumerate(raw_items)
        if index not in header_indices
    ]
    return _group_instruction_steps(
        serialized_steps,
        section_keys=sectioned.section_key_by_line,
        section_display_by_key=sectioned.section_display_by_key,
    )


def _build_ingredient_sections(candidate: RecipeCandidate) -> list[dict[str, Any]]:
    if not candidate.ingredients:
        return []

    sectioned = extract_ingredient_sections(candidate.ingredients)
    if not sectioned.header_hits:
        return []

    section_lines: dict[str, list[str]] = {}
    for line, key in zip(sectioned.lines_no_headers, sectioned.section_key_by_line):
        section_lines.setdefault(key, []).append(line)

    ordered_keys: list[str] = []
    for key in sectioned.section_key_by_line:
        if key not in ordered_keys:
            ordered_keys.append(key)

    payload: list[dict[str, Any]] = []
    for key in ordered_keys:
        lines = section_lines.get(key, [])
        if not lines:
            continue
        payload.append(
            {
                "name": _section_display_name(key, sectioned.section_display_by_key),
                "key": key,
                "recipeIngredient": lines,
            }
        )

    return payload


def recipe_candidate_to_jsonld(
    candidate: RecipeCandidate,
    *,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a RecipeCandidate into schema.org Recipe JSON (+ recipeimport metadata)."""
    payload: dict[str, Any] = {
        "@context": ["https://schema.org", {"recipeimport": "https://recipeimport.local/ns#"}],
        "@type": "Recipe",
    }

    candidate_id = candidate.provenance.get("@id") or candidate.provenance.get("id")
    if candidate_id:
        payload["@id"] = candidate_id

    payload["name"] = candidate.name
    if candidate.identifier:
        payload["identifier"] = candidate.identifier
    if candidate.date_published:
        payload["datePublished"] = candidate.date_published
    if candidate.description:
        payload["description"] = candidate.description
    if candidate.recipe_yield:
        payload["recipeYield"] = candidate.recipe_yield
    if candidate.ingredients:
        payload["recipeIngredient"] = candidate.ingredients

    instructions_payload = _build_recipe_instructions(
        candidate,
        instruction_step_options=instruction_step_options,
    )
    if instructions_payload:
        payload["recipeInstructions"] = instructions_payload

    ingredient_sections = _build_ingredient_sections(candidate)
    if ingredient_sections:
        payload["recipeimport:ingredientSections"] = ingredient_sections

    if candidate.tags:
        payload["keywords"] = ", ".join(candidate.tags)
    if candidate.image:
        payload["image"] = candidate.image
    if candidate.recipe_category:
        payload["recipeCategory"] = candidate.recipe_category
    if candidate.recipe_cuisine:
        payload["recipeCuisine"] = candidate.recipe_cuisine
    if candidate.cooking_method:
        payload["cookingMethod"] = candidate.cooking_method
    if candidate.suitable_for_diet:
        payload["suitableForDiet"] = candidate.suitable_for_diet
    if candidate.author:
        payload["author"] = candidate.author
    if candidate.publisher:
        payload["publisher"] = candidate.publisher
    if candidate.date_modified:
        payload["dateModified"] = candidate.date_modified
    if candidate.credit_text:
        payload["creditText"] = candidate.credit_text
    if candidate.source_url:
        payload["url"] = candidate.source_url
    if candidate.is_based_on:
        payload["isBasedOn"] = candidate.is_based_on
    if candidate.tools:
        payload["tool"] = candidate.tools
    if candidate.supplies:
        payload["supply"] = candidate.supplies
    if candidate.nutrition:
        payload["nutrition"] = candidate.nutrition
    if candidate.video:
        payload["video"] = candidate.video
    if candidate.prep_time:
        payload["prepTime"] = candidate.prep_time
    if candidate.cook_time:
        payload["cookTime"] = candidate.cook_time
    if candidate.total_time:
        payload["totalTime"] = candidate.total_time
    if candidate.comments:
        payload["comment"] = [
            comment.model_dump(by_alias=True, exclude_none=True)
            for comment in candidate.comments
        ]
    if candidate.aggregate_rating:
        payload["aggregateRating"] = candidate.aggregate_rating.model_dump(
            by_alias=True, exclude_none=True
        )
    if candidate.confidence is not None:
        payload["recipeimport:confidence"] = candidate.confidence
    if candidate.provenance:
        payload["recipeimport:provenance"] = candidate.provenance

    return payload
