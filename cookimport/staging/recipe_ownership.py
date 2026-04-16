from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from cookimport.core.models import RecipeCandidate
from cookimport.parsing.label_source_of_truth import RecipeSpan

_SCHEMA_VERSION = "recipe_row_ownership.v1"


class RecipeOwnershipInvariantError(ValueError):
    """Raised when recipe/nonrecipe ownership invariants are violated."""


@dataclass(frozen=True, slots=True, init=False)
class RecipeOwnershipEntry:
    recipe_id: str
    recipe_span_id: str
    owned_row_indices: list[int]
    divested_row_indices: list[int]

    def __init__(
        self,
        *,
        recipe_id: str,
        recipe_span_id: str,
        owned_row_indices: list[int] | None = None,
        divested_row_indices: list[int] | None = None,
    ) -> None:
        object.__setattr__(self, "recipe_id", recipe_id)
        object.__setattr__(self, "recipe_span_id", recipe_span_id)
        object.__setattr__(
            self,
            "owned_row_indices",
            list(owned_row_indices or []),
        )
        object.__setattr__(
            self,
            "divested_row_indices",
            list(divested_row_indices or []),
        )


@dataclass(frozen=True, slots=True, init=False)
class RecipeDivestment:
    recipe_id: str
    row_indices: list[int]
    reason: str

    def __init__(
        self,
        *,
        recipe_id: str,
        reason: str,
        row_indices: list[int] | None = None,
    ) -> None:
        object.__setattr__(self, "recipe_id", recipe_id)
        object.__setattr__(
            self,
            "row_indices",
            list(row_indices or []),
        )
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True, init=False)
class RecipeOwnershipResult:
    ownership_mode: str
    recipe_entries: list[RecipeOwnershipEntry]
    row_owner_by_index: dict[int, str]
    owned_row_indices: list[int]
    divested_row_indices: list[int]
    available_to_nonrecipe_row_indices: list[int]
    all_row_indices: list[int]

    def __init__(
        self,
        *,
        ownership_mode: str,
        recipe_entries: list[RecipeOwnershipEntry],
        row_owner_by_index: dict[int, str] | None = None,
        owned_row_indices: list[int] | None = None,
        divested_row_indices: list[int] | None = None,
        available_to_nonrecipe_row_indices: list[int] | None = None,
        all_row_indices: list[int] | None = None,
    ) -> None:
        object.__setattr__(self, "ownership_mode", ownership_mode)
        object.__setattr__(self, "recipe_entries", list(recipe_entries))
        object.__setattr__(
            self,
            "row_owner_by_index",
            dict(row_owner_by_index or {}),
        )
        object.__setattr__(
            self,
            "owned_row_indices",
            list(owned_row_indices or []),
        )
        object.__setattr__(
            self,
            "divested_row_indices",
            list(divested_row_indices or []),
        )
        object.__setattr__(
            self,
            "available_to_nonrecipe_row_indices",
            list(available_to_nonrecipe_row_indices or []),
        )
        object.__setattr__(
            self,
            "all_row_indices",
            list(all_row_indices or []),
        )

    def recipe_entry_by_recipe_id(self, recipe_id: str) -> RecipeOwnershipEntry | None:
        for entry in self.recipe_entries:
            if str(entry.recipe_id) == str(recipe_id):
                return entry
        return None

    def is_row_recipe_owned(self, row_index: int) -> bool:
        return int(row_index) in self.row_owner_by_index

    def assert_row_is_available_to_nonrecipe(self, row_index: int) -> None:
        normalized = int(row_index)
        if normalized in self.row_owner_by_index:
            owner = self.row_owner_by_index[normalized]
            raise RecipeOwnershipInvariantError(
                f"Row {normalized} is recipe-owned by '{owner}' and may not enter nonrecipe routing."
            )

    def assert_row_is_recipe_owned(self, row_index: int) -> None:
        normalized = int(row_index)
        if normalized not in self.row_owner_by_index:
            raise RecipeOwnershipInvariantError(
                f"Row {normalized} is not recipe-owned."
            )


def build_recipe_ownership_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    recipe_spans: Sequence[RecipeSpan],
    recipes: Sequence[RecipeCandidate],
    ownership_mode: str = "recipe_boundary",
) -> RecipeOwnershipResult:
    all_row_indices = _sorted_row_indices(full_blocks)
    all_row_index_set = set(all_row_indices)
    span_rows = list(recipe_spans)
    recipe_rows = list(recipes)
    if len(span_rows) != len(recipe_rows):
        raise RecipeOwnershipInvariantError(
            "Recipe ownership could not be built because recipe spans and recipes do not align "
            f"({len(span_rows)} spans vs {len(recipe_rows)} recipes)."
        )

    entries: list[RecipeOwnershipEntry] = []
    row_owner_by_index: dict[int, str] = {}
    for span, recipe in zip(span_rows, recipe_rows, strict=True):
        recipe_id = _require_recipe_id(recipe)
        explicit_recipe_span_id = _recipe_span_id_from_recipe(recipe)
        recipe_span_id = explicit_recipe_span_id or span.span_id
        if explicit_recipe_span_id is not None and recipe_span_id != span.span_id:
            raise RecipeOwnershipInvariantError(
                "Recipe ownership could not be built because recipe span ids do not align "
                f"({recipe_id}: recipe has '{recipe_span_id}' but boundary has '{span.span_id}')."
            )
        owned_row_indices = _normalize_index_list(span.row_indices)
        missing = [index for index in owned_row_indices if index not in all_row_index_set]
        if missing:
            raise RecipeOwnershipInvariantError(
                f"Recipe '{recipe_id}' claimed unknown owned row indices: {missing}."
            )
        for row_index in owned_row_indices:
            prior_owner = row_owner_by_index.get(row_index)
            if prior_owner is not None and prior_owner != recipe_id:
                raise RecipeOwnershipInvariantError(
                    f"Row {row_index} was claimed by both '{prior_owner}' and '{recipe_id}'."
                )
            row_owner_by_index[row_index] = recipe_id
        entries.append(
            RecipeOwnershipEntry(
                recipe_id=recipe_id,
                recipe_span_id=recipe_span_id,
                owned_row_indices=owned_row_indices,
                divested_row_indices=[],
            )
        )

    return _finalize_recipe_ownership(
        ownership_mode=ownership_mode,
        recipe_entries=entries,
        all_row_indices=all_row_indices,
    )


def apply_recipe_divestments(
    *,
    ownership_result: RecipeOwnershipResult,
    divestments: Sequence[RecipeDivestment],
    ownership_mode: str = "recipe_boundary_with_explicit_divestment",
) -> RecipeOwnershipResult:
    if not divestments:
        if ownership_result.ownership_mode == ownership_mode:
            return ownership_result
        return RecipeOwnershipResult(
            ownership_mode=ownership_mode,
            recipe_entries=list(ownership_result.recipe_entries),
            row_owner_by_index=dict(ownership_result.row_owner_by_index),
            owned_row_indices=list(ownership_result.owned_row_indices),
            divested_row_indices=list(ownership_result.divested_row_indices),
            available_to_nonrecipe_row_indices=list(
                ownership_result.available_to_nonrecipe_row_indices
            ),
            all_row_indices=list(ownership_result.all_row_indices),
        )

    updates_by_recipe_id = {
        entry.recipe_id: {
            "owned": list(entry.owned_row_indices),
            "divested": list(entry.divested_row_indices),
        }
        for entry in ownership_result.recipe_entries
    }
    row_owner_by_index = dict(ownership_result.row_owner_by_index)
    known_recipe_ids = set(updates_by_recipe_id)

    for divestment in divestments:
        recipe_id = str(divestment.recipe_id).strip()
        if recipe_id not in known_recipe_ids:
            raise RecipeOwnershipInvariantError(
                f"Unknown recipe divestment owner '{recipe_id}'."
            )
        normalized_indices = _normalize_index_list(divestment.row_indices)
        for row_index in normalized_indices:
            owner = row_owner_by_index.get(row_index)
            if owner != recipe_id:
                raise RecipeOwnershipInvariantError(
                    f"Recipe '{recipe_id}' cannot divest row {row_index}; current owner is "
                    f"{owner!r}."
                )
            row_owner_by_index.pop(row_index, None)
            owned = updates_by_recipe_id[recipe_id]["owned"]
            if row_index in owned:
                owned.remove(row_index)
            divested_list = updates_by_recipe_id[recipe_id]["divested"]
            if row_index not in divested_list:
                divested_list.append(row_index)

    updated_entries = [
        RecipeOwnershipEntry(
            recipe_id=entry.recipe_id,
            recipe_span_id=entry.recipe_span_id,
            owned_row_indices=sorted(updates_by_recipe_id[entry.recipe_id]["owned"]),
            divested_row_indices=sorted(updates_by_recipe_id[entry.recipe_id]["divested"]),
        )
        for entry in ownership_result.recipe_entries
    ]
    return _finalize_recipe_ownership(
        ownership_mode=ownership_mode,
        recipe_entries=updated_entries,
        all_row_indices=list(ownership_result.all_row_indices),
    )


def recipe_ownership_to_payload(
    ownership_result: RecipeOwnershipResult,
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "ownership_mode": ownership_result.ownership_mode,
        "owned_row_indices": list(ownership_result.owned_row_indices),
        "divested_row_indices": list(ownership_result.divested_row_indices),
        "available_to_nonrecipe_row_indices": list(
            ownership_result.available_to_nonrecipe_row_indices
        ),
        "row_owner_by_index": {
            str(index): recipe_id
            for index, recipe_id in sorted(ownership_result.row_owner_by_index.items())
        },
        "recipes": [
            {
                "recipe_id": entry.recipe_id,
                "recipe_span_id": entry.recipe_span_id,
                "owned_row_indices": list(entry.owned_row_indices),
                "divested_row_indices": list(entry.divested_row_indices),
            }
            for entry in ownership_result.recipe_entries
        ],
    }


def recipe_ownership_from_payload(
    payload: Mapping[str, Any],
    *,
    full_blocks: Sequence[Mapping[str, Any]],
) -> RecipeOwnershipResult:
    recipes_payload = payload.get("recipes")
    if not isinstance(recipes_payload, Sequence):
        raise RecipeOwnershipInvariantError("Recipe ownership payload is missing 'recipes'.")
    entries: list[RecipeOwnershipEntry] = []
    for row in recipes_payload:
        if not isinstance(row, Mapping):
            continue
        entries.append(
            RecipeOwnershipEntry(
                recipe_id=str(row.get("recipe_id") or "").strip(),
                recipe_span_id=str(row.get("recipe_span_id") or "").strip(),
                owned_row_indices=_normalize_index_list(
                    row.get("owned_row_indices") or row.get("owned_block_indices") or []
                ),
                divested_row_indices=_normalize_index_list(
                    row.get("divested_row_indices") or row.get("divested_block_indices") or []
                ),
            )
        )
    return _finalize_recipe_ownership(
        ownership_mode=str(payload.get("ownership_mode") or "recipe_boundary"),
        recipe_entries=entries,
        all_row_indices=_sorted_row_indices(full_blocks),
    )


def _finalize_recipe_ownership(
    *,
    ownership_mode: str,
    recipe_entries: Sequence[RecipeOwnershipEntry],
    all_row_indices: Sequence[int],
) -> RecipeOwnershipResult:
    normalized_entries = [
        RecipeOwnershipEntry(
            recipe_id=str(entry.recipe_id).strip(),
            recipe_span_id=str(entry.recipe_span_id).strip(),
            owned_row_indices=_normalize_index_list(entry.owned_row_indices),
            divested_row_indices=_normalize_index_list(entry.divested_row_indices),
        )
        for entry in recipe_entries
    ]
    row_owner_by_index: dict[int, str] = {}
    divested_row_indices: set[int] = set()
    for entry in normalized_entries:
        for row_index in entry.divested_row_indices:
            divested_row_indices.add(row_index)
        for row_index in entry.owned_row_indices:
            if row_index in divested_row_indices:
                raise RecipeOwnershipInvariantError(
                    f"Row {row_index} cannot be both owned and divested."
                )
            prior_owner = row_owner_by_index.get(row_index)
            if prior_owner is not None and prior_owner != entry.recipe_id:
                raise RecipeOwnershipInvariantError(
                    f"Row {row_index} was claimed by both '{prior_owner}' and '{entry.recipe_id}'."
                )
            row_owner_by_index[row_index] = entry.recipe_id
    all_indices = sorted({int(index) for index in all_row_indices})
    owned_row_indices = sorted(row_owner_by_index)
    available_to_nonrecipe = [index for index in all_indices if index not in row_owner_by_index]
    return RecipeOwnershipResult(
        ownership_mode=str(ownership_mode).strip() or "recipe_boundary",
        recipe_entries=list(normalized_entries),
        row_owner_by_index=row_owner_by_index,
        owned_row_indices=owned_row_indices,
        divested_row_indices=sorted(divested_row_indices),
        available_to_nonrecipe_row_indices=available_to_nonrecipe,
        all_row_indices=all_indices,
    )


def _sorted_row_indices(full_blocks: Sequence[Mapping[str, Any]]) -> list[int]:
    indices: set[int] = set()
    for fallback_index, block in enumerate(full_blocks):
        if not isinstance(block, Mapping):
            continue
        raw_index = block.get("index", fallback_index)
        try:
            indices.add(int(raw_index))
        except (TypeError, ValueError):
            indices.add(int(fallback_index))
    return sorted(indices)


def _normalize_index_list(raw_indices: Sequence[Any]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_value in raw_indices:
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise RecipeOwnershipInvariantError(
                f"Recipe ownership block indices must be integers; got {raw_value!r}."
            ) from exc
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return sorted(normalized)


def _require_recipe_id(recipe: RecipeCandidate) -> str:
    recipe_id = str(getattr(recipe, "identifier", None) or "").strip()
    if recipe_id:
        return recipe_id
    provenance = recipe.provenance if isinstance(recipe.provenance, Mapping) else {}
    for key in ("@id", "id"):
        raw_value = provenance.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    raise RecipeOwnershipInvariantError(
        f"Recipe '{getattr(recipe, 'name', '')}' is missing an identifier."
    )


def _recipe_span_id_from_recipe(recipe: RecipeCandidate) -> str | None:
    provenance = recipe.provenance if isinstance(recipe.provenance, Mapping) else {}
    location = provenance.get("location") if isinstance(provenance, Mapping) else None
    if isinstance(location, Mapping):
        recipe_span_id = str(location.get("recipe_span_id") or "").strip()
        if recipe_span_id:
            return recipe_span_id
    return None
