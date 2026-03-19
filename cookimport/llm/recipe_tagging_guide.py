from __future__ import annotations

from typing import Any, Mapping


def build_recipe_tagging_guide() -> dict[str, Any]:
    """Return a compact fixed tagging guide for recipe correction prompts.

    This is intentionally small. It gives the model a stable vocabulary for broad
    tag categories without repeating a large cookbook-specific catalog on every
    recipe call.
    """

    return {
        "v": "recipe_tagging_guide.v2",
        "r": [
            "Use only grounded tags obvious from the recipe text.",
            "Zero tags in a category is valid.",
            "Prefer short human-readable labels.",
            "Avoid near-duplicates inside one recipe.",
        ],
        "c": [
            {
                "k": "dish_type",
                "x": ["soup", "stew", "salad", "sandwich", "cake"],
            },
            {
                "k": "protein",
                "x": ["chicken", "beef", "tofu", "shrimp", "beans"],
            },
            {
                "k": "produce",
                "x": ["mushroom", "tomato", "potato", "apple", "corn"],
            },
            {
                "k": "method",
                "x": ["roasted", "grilled", "braised", "stir fry", "pressure cooker"],
            },
            {
                "k": "equipment",
                "x": ["slow cooker", "instant pot", "sheet pan", "blender", "cast iron"],
            },
            {
                "k": "meal",
                "x": ["breakfast", "brunch", "lunch", "dinner", "dessert"],
            },
            {
                "k": "diet",
                "x": ["vegetarian", "vegan", "gluten free", "dairy free", "low carb"],
            },
            {
                "k": "occasion",
                "x": ["weeknight", "holiday", "party", "picnic", "make ahead"],
            },
            {
                "k": "flavor_profile",
                "x": ["spicy", "smoky", "herby", "citrusy", "comfort food"],
            },
        ],
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
