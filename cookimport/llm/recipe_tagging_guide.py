from __future__ import annotations

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

def build_recipe_tagging_guide() -> dict[str, Any]:
    """Return a compact tagging guide for recipe correction prompts."""
    return {
        "v": "recipe_tagging_guide.v4",
        "r": [
            "Use only grounded tags obvious from the recipe text.",
            "Zero tags in a category is valid.",
            "Prefer short human-readable labels.",
            "Avoid near-duplicates inside one recipe.",
            "Do not treat example labels as a required shortlist.",
            "You may emit a grounded label not shown in the examples when the source clearly supports it.",
        ],
        "c": [{"k": category["key"], "x": list(category["examples"])} for category in _TAG_CATALOG],
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
