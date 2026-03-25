from __future__ import annotations

FREEFORM_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
    "KNOWLEDGE",
    "OTHER",
)

_LABEL_RESOLUTION_PRIORITY: tuple[str, ...] = (
    "RECIPE_VARIANT",
    "RECIPE_TITLE",
    "YIELD_LINE",
    "TIME_LINE",
    "HOWTO_SECTION",
    "INGREDIENT_LINE",
    "RECIPE_NOTES",
    "INSTRUCTION_LINE",
    "KNOWLEDGE",
)

_RECIPE_LOCAL_LABELS: set[str] = {
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
}


def resolve_stage_block_label(labels: list[str]) -> str:
    if not labels:
        return "OTHER"

    label_set = set(labels)
    if "KNOWLEDGE" in label_set and any(
        recipe_label in label_set for recipe_label in _RECIPE_LOCAL_LABELS
    ):
        label_set.remove("KNOWLEDGE")

    for label in _LABEL_RESOLUTION_PRIORITY:
        if label in label_set:
            return label
    return "OTHER"
