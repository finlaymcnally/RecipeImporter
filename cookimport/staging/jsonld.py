from __future__ import annotations

from typing import Any

from cookimport.core.models import HowToStep, RecipeCandidate


def _serialize_instructions(instructions: list[object]) -> list[object]:
    serialized: list[object] = []
    for item in instructions:
        if isinstance(item, HowToStep):
            serialized.append(item.model_dump(by_alias=True, exclude_none=True))
        else:
            serialized.append(item)
    return serialized


def recipe_candidate_to_jsonld(candidate: RecipeCandidate) -> dict[str, Any]:
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
    if candidate.instructions:
        payload["recipeInstructions"] = _serialize_instructions(candidate.instructions)
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
