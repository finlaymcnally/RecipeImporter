from __future__ import annotations

import re
from typing import Any, Mapping

_TAG_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "dish_type",
        "examples": [
            "toast",
            "salad",
            "soup",
            "stew",
            "sandwich",
            "pasta",
            "rice",
            "cake",
        ],
    },
    {
        "key": "protein",
        "examples": [
            "chicken",
            "beef",
            "pork",
            "fish",
            "shrimp",
            "egg",
            "tofu",
            "beans",
        ],
    },
    {
        "key": "produce",
        "examples": [
            "tomato",
            "potato",
            "mushroom",
            "corn",
            "apple",
            "lemon",
            "greens",
            "onion",
        ],
    },
    {
        "key": "method",
        "examples": [
            "roasted",
            "grilled",
            "braised",
            "fried",
            "sauteed",
            "toasted",
            "baked",
            "poached",
        ],
    },
    {
        "key": "equipment",
        "examples": [
            "sheet pan",
            "cast iron",
            "blender",
            "grill",
            "oven",
            "skillet",
            "slow cooker",
            "pressure cooker",
        ],
    },
    {
        "key": "meal",
        "examples": [
            "breakfast",
            "brunch",
            "lunch",
            "dinner",
            "dessert",
            "snack",
        ],
    },
    {
        "key": "diet",
        "examples": [
            "vegetarian",
            "vegan",
            "gluten free",
            "dairy free",
            "low carb",
            "high protein",
        ],
    },
    {
        "key": "occasion",
        "examples": [
            "weeknight",
            "holiday",
            "party",
            "picnic",
            "make ahead",
            "date night",
        ],
    },
    {
        "key": "flavor_profile",
        "examples": [
            "spicy",
            "smoky",
            "herby",
            "citrusy",
            "savory",
            "sweet",
            "tangy",
            "rich",
        ],
    },
    {
        "key": "time_profile",
        "examples": [
            "quick",
            "slow cooked",
            "weeknight",
            "make ahead",
        ],
    },
)

_TAG_MATCH_ALIASES: dict[str, tuple[str, ...]] = {
    "toasted": ("toast", "toasted"),
    "fried": ("fry", "fried"),
    "sauteed": ("saute", "sauteed"),
    "baked": ("bake", "baked"),
    "roasted": ("roast", "roasted"),
    "poached": ("poach", "poached"),
    "egg": ("egg", "eggs"),
    "greens": ("greens", "lettuce", "kale", "spinach"),
    "gluten free": ("gluten free", "gluten-free"),
    "dairy free": ("dairy free", "dairy-free"),
    "high protein": ("high protein", "high-protein"),
    "slow cooked": ("slow cooked", "slow-cooked", "slow cooker"),
}


def _build_recipe_tag_match_text(
    *,
    recipe_text: str,
    recipe_candidate_hint: Mapping[str, Any] | None,
) -> str:
    payload = dict(recipe_candidate_hint or {})
    fields: list[str] = [str(recipe_text or "")]
    for key in ("n", "d", "y"):
        rendered = str(payload.get(key) or "").strip()
        if rendered:
            fields.append(rendered)
    for key in ("i", "s", "g"):
        values = payload.get(key) or []
        if isinstance(values, list):
            fields.extend(str(value).strip() for value in values if str(value).strip())
    return " ".join(fields).lower()


def _label_matches_text(label: str, text: str) -> bool:
    normalized_label = str(label or "").strip().lower()
    if not normalized_label or not text:
        return False
    match_terms = _TAG_MATCH_ALIASES.get(normalized_label, (normalized_label,))
    for term in match_terms:
        token = str(term or "").strip().lower()
        if not token:
            continue
        if " " in token:
            if token in text:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text):
            return True
    return False


def _suggest_recipe_tags(
    *,
    recipe_text: str,
    recipe_candidate_hint: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    combined_text = _build_recipe_tag_match_text(
        recipe_text=recipe_text,
        recipe_candidate_hint=recipe_candidate_hint,
    )
    suggestions: list[dict[str, Any]] = []
    for category in _TAG_CATALOG:
        matched = [
            label
            for label in category["examples"]
            if _label_matches_text(label, combined_text)
        ]
        if matched:
            suggestions.append({"k": category["key"], "l": matched})
    return suggestions


def build_recipe_tagging_guide(
    *,
    recipe_text: str = "",
    recipe_candidate_hint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact tagging guide for recipe correction prompts."""

    return {
        "v": "recipe_tagging_guide.v3",
        "r": [
            "Use only grounded tags obvious from the recipe text.",
            "Zero tags in a category is valid.",
            "Prefer short human-readable labels.",
            "Avoid near-duplicates inside one recipe.",
            "Prefer `s` suggested labels first when they fit cleanly.",
            "You may emit a grounded label not listed in `s` when the source clearly supports it.",
        ],
        "c": [{"k": category["key"], "x": list(category["examples"])} for category in _TAG_CATALOG],
        "s": _suggest_recipe_tags(
            recipe_text=recipe_text,
            recipe_candidate_hint=recipe_candidate_hint,
        ),
    }


def recipe_tagging_guide_categories(guide: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = dict(guide or {})
    categories = payload.get("c")
    if not isinstance(categories, list):
        categories = payload.get("categories")
    normalized: list[dict[str, Any]] = []
    if not isinstance(categories, list):
        return normalized
    for item in categories:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("k") or item.get("key") or "").strip()
        examples = item.get("x")
        if not isinstance(examples, list):
            examples = item.get("examples")
        if not key or not isinstance(examples, list):
            continue
        normalized.append(
            {
                "key": key,
                "examples": [str(example).strip() for example in examples if str(example).strip()],
            }
        )
    return normalized
