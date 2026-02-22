from __future__ import annotations

import re

_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_for_filename(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "recipe"


def ensure_recipe_id(
    existing: str | None,
    *,
    workbook_slug: str,
    recipe_index: int,
) -> str:
    if isinstance(existing, str):
        cleaned = existing.strip()
        if cleaned:
            return cleaned
    safe_slug = sanitize_for_filename(workbook_slug)
    return f"urn:recipeimport:llm:{safe_slug}:r{recipe_index}"


def bundle_filename(recipe_id: str, *, recipe_index: int) -> str:
    safe = sanitize_for_filename(recipe_id)
    return f"r{recipe_index:04d}_{safe}.json"
