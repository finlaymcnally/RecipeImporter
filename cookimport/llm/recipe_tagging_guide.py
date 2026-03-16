from __future__ import annotations

from typing import Any


def build_recipe_tagging_guide() -> dict[str, Any]:
    """Return a compact fixed tagging guide for recipe correction prompts.

    This is intentionally small. It gives the model a stable vocabulary for broad
    tag categories without repeating a large cookbook-specific catalog on every
    recipe call.
    """

    return {
        "version": "recipe_tagging_guide.v1",
        "rules": [
            "Use only grounded tags that are obvious from the recipe text.",
            "Zero tags in a category is valid.",
            "Prefer short human-readable labels.",
            "Avoid near-duplicates inside one recipe.",
        ],
        "categories": [
            {
                "key": "dish_type",
                "description": "What kind of dish or recipe this is.",
                "examples": ["soup", "stew", "salad", "sandwich", "cake"],
            },
            {
                "key": "protein",
                "description": "Primary protein or centerpiece ingredient when clear.",
                "examples": ["chicken", "beef", "tofu", "shrimp", "beans"],
            },
            {
                "key": "produce",
                "description": "Primary fruit or vegetable when it strongly defines the dish.",
                "examples": ["mushroom", "tomato", "potato", "apple", "corn"],
            },
            {
                "key": "method",
                "description": "Main cooking method or preparation style.",
                "examples": ["roasted", "grilled", "braised", "stir fry", "pressure cooker"],
            },
            {
                "key": "equipment",
                "description": "Notable tool or vessel required by the recipe.",
                "examples": ["slow cooker", "instant pot", "sheet pan", "blender", "cast iron"],
            },
            {
                "key": "meal",
                "description": "Meal slot or serving context when obvious.",
                "examples": ["breakfast", "brunch", "lunch", "dinner", "dessert"],
            },
            {
                "key": "diet",
                "description": "Dietary fit stated directly or strongly implied by ingredients.",
                "examples": ["vegetarian", "vegan", "gluten free", "dairy free", "low carb"],
            },
            {
                "key": "occasion",
                "description": "Typical use case or social context when obvious from the recipe.",
                "examples": ["weeknight", "holiday", "party", "picnic", "make ahead"],
            },
            {
                "key": "flavor_profile",
                "description": "Dominant flavor or mood when strongly signaled by the recipe.",
                "examples": ["spicy", "smoky", "herby", "citrusy", "comfort food"],
            },
        ],
    }
