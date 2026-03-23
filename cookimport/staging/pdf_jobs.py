from __future__ import annotations

import math
from typing import Any

from cookimport.core.models import RecipeCandidate
from cookimport.core.reporting import generate_recipe_id


def plan_job_ranges(
    unit_count: int,
    workers: int,
    units_per_job: int,
) -> list[tuple[int, int]]:
    if unit_count <= 0:
        return []
    if workers <= 1 or units_per_job <= 0 or unit_count <= units_per_job:
        return [(0, unit_count)]

    job_count = min(workers, math.ceil(unit_count / units_per_job))
    if job_count <= 1:
        return [(0, unit_count)]

    units_per_split = math.ceil(unit_count / job_count)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < unit_count:
        end = min(start + units_per_split, unit_count)
        ranges.append((start, end))
        start = end
    return ranges


def plan_pdf_page_ranges(
    page_count: int,
    workers: int,
    pages_per_job: int,
) -> list[tuple[int, int]]:
    return plan_job_ranges(page_count, workers, pages_per_job)


def reassign_recipe_ids(
    recipes: list[RecipeCandidate],
    *,
    file_hash: str,
    importer_name: str,
) -> tuple[list[RecipeCandidate], dict[str, str]]:
    indexed = list(enumerate(recipes))
    indexed.sort(key=lambda item: _recipe_sort_key(item[1], item[0]))

    id_map: dict[str, str] = {}
    ordered: list[RecipeCandidate] = []
    for new_index, (_, recipe) in enumerate(indexed):
        provenance = recipe.provenance or {}
        old_id = recipe.identifier or provenance.get("@id") or provenance.get("id")
        new_id = generate_recipe_id(importer_name, file_hash, f"c{new_index}")
        if old_id:
            id_map[str(old_id)] = new_id
        recipe.identifier = new_id
        provenance["@id"] = new_id
        if "id" in provenance:
            provenance["id"] = new_id
        location = provenance.get("location")
        if not isinstance(location, dict):
            location = {}
            provenance["location"] = location
        location["chunk_index"] = new_index
        if "chunkIndex" in location:
            location["chunkIndex"] = new_index
        recipe.provenance = provenance
        ordered.append(recipe)

    return ordered, id_map


def reassign_pdf_recipe_ids(
    recipes: list[RecipeCandidate],
    *,
    file_hash: str,
) -> tuple[list[RecipeCandidate], dict[str, str]]:
    return reassign_recipe_ids(
        recipes,
        file_hash=file_hash,
        importer_name="pdf",
    )


def _recipe_sort_key(recipe: RecipeCandidate, fallback_index: int) -> tuple[int, int, int, int]:
    location = recipe.provenance.get("location") if isinstance(recipe.provenance, dict) else None
    start_spine = _coerce_int(_lookup_location_value(location, "start_spine", "startSpine"))
    start_page = _coerce_int(_lookup_location_value(location, "start_page", "startPage"))
    start_block = _coerce_int(_lookup_location_value(location, "start_block", "startBlock"))

    if start_spine is not None:
        return (0, start_spine, start_block or 0, fallback_index)
    if start_page is not None:
        return (1, start_page, start_block or 0, fallback_index)
    if start_block is not None:
        return (2, start_block, 0, fallback_index)
    return (3, 0, 0, fallback_index)


def _lookup_location_value(location: Any, *keys: str) -> Any:
    if not isinstance(location, dict):
        return None
    for key in keys:
        if key in location:
            return location[key]
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
