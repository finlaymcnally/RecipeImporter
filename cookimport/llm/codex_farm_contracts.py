from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path
import re
from typing import Any, Literal, TypeVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

_BUNDLE_VERSION: Literal["1"] = "1"
_NULL_HEX_PAIR_RE = re.compile(r"\x00([0-9a-fA-F]{2})")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_CONTROL_CHAR_TRANSLATION = str.maketrans({chr(index): " " for index in range(32)})
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_json_text(raw: str) -> str:
    normalized = _NULL_HEX_PAIR_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        raw,
    )
    normalized = normalized.translate(_CONTROL_CHAR_TRANSLATION)
    normalized = _TRAILING_COMMA_RE.sub(r"\1", normalized)
    return normalized.strip()


def _sanitize_text_fragment(raw: Any) -> str:
    rendered = str(raw or "")
    if not rendered:
        return ""
    normalized = _NULL_HEX_PAIR_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        rendered,
    )
    normalized = normalized.translate(_CONTROL_CHAR_TRANSLATION)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def _repair_json_structure(raw: str) -> str:
    start = raw.find("{")
    if start < 0:
        return raw
    end = max(raw.rfind("}"), raw.rfind("]"))
    candidate = raw[start : end + 1] if end >= start else raw[start:]

    stack: list[str] = []
    output: list[str] = []
    in_string = False
    escaping = False

    for char in candidate:
        if in_string:
            output.append(char)
            if escaping:
                escaping = False
            elif char == "\\":
                escaping = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            output.append(char)
            continue
        if char in "{[":
            stack.append(char)
            output.append(char)
            continue
        if char in "}]":
            expected_open = "{" if char == "}" else "["
            if stack and stack[-1] == expected_open:
                stack.pop()
                output.append(char)
            continue
        output.append(char)

    if in_string:
        output.append('"')
    for open_char in reversed(stack):
        output.append("}" if open_char == "{" else "]")
    return "".join(output).strip()


def _extract_first_json_object(raw: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _coerce_json_object_field(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        candidates: list[str] = []
        raw_text = value.strip()
        if raw_text:
            candidates.append(raw_text)
        normalized_text = _normalize_json_text(raw_text)
        if normalized_text and normalized_text not in candidates:
            candidates.append(normalized_text)
        repaired_text = _repair_json_structure(normalized_text)
        if repaired_text and repaired_text not in candidates:
            candidates.append(repaired_text)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        for candidate in candidates:
            extracted = _extract_first_json_object(candidate)
            if extracted is not None:
                return extracted

        raise ValueError(f"{field_name} must be a JSON object or JSON object string")
    raise ValueError(f"{field_name} must be a JSON object or JSON object string")


def _coerce_nonnegative_int(value: Any, field_name: str) -> int:
    try:
        rendered = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if rendered < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return rendered


def _coerce_nonnegative_int_list(value: Any, field_name: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of non-negative integers")
    rows: list[int] = []
    seen: set[int] = set()
    for item in value:
        rendered = _coerce_nonnegative_int(item, field_name)
        if rendered in seen:
            continue
        seen.add(rendered)
        rows.append(rendered)
    return rows


def _normalize_ingredient_step_mapping_payload(
    value: Any,
    field_name: str,
) -> dict[str, list[int]]:
    if value is None:
        return {}
    if isinstance(value, dict):
        rows: dict[str, list[int]] = {}
        for raw_key, raw_steps in value.items():
            ingredient_index = _coerce_nonnegative_int(
                raw_key,
                f"{field_name} ingredient index",
            )
            rows[str(ingredient_index)] = _coerce_nonnegative_int_list(
                raw_steps,
                f"{field_name}[{ingredient_index}]",
            )
        return rows
    if isinstance(value, list):
        rows: dict[str, list[int]] = {}
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(
                    f"{field_name}[{index}] must be an object with ingredient_index and step_indexes"
                )
            ingredient_index = _coerce_nonnegative_int(
                item.get("ingredient_index", item.get("i")),
                f"{field_name}[{index}].ingredient_index",
            )
            step_indexes = _coerce_nonnegative_int_list(
                item.get("step_indexes", item.get("s")),
                f"{field_name}[{index}].step_indexes",
            )
            key = str(ingredient_index)
            existing = rows.get(key, [])
            seen = set(existing)
            merged = list(existing)
            for step_index in step_indexes:
                if step_index in seen:
                    continue
                seen.add(step_index)
                merged.append(step_index)
            rows[key] = merged
        return rows
    raise ValueError(
        f"{field_name} must be an object, mapping-entry array, or JSON string of either"
    )


def _coerce_ingredient_step_mapping_field(value: Any, field_name: str) -> dict[str, list[int]]:
    if isinstance(value, dict | list) or value is None:
        return _normalize_ingredient_step_mapping_payload(value, field_name)
    if isinstance(value, str):
        candidates: list[str] = []
        raw_text = value.strip()
        if raw_text:
            candidates.append(raw_text)
        normalized_text = _normalize_json_text(raw_text)
        if normalized_text and normalized_text not in candidates:
            candidates.append(normalized_text)
        repaired_text = _repair_json_structure(normalized_text)
        if repaired_text and repaired_text not in candidates:
            candidates.append(repaired_text)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except JSONDecodeError:
                continue
            if isinstance(parsed, dict | list):
                return _normalize_ingredient_step_mapping_payload(parsed, field_name)
        raise ValueError(
            f"{field_name} must be an object, mapping-entry array, or JSON string of either"
        )
    raise ValueError(
        f"{field_name} must be an object, mapping-entry array, or JSON string of either"
    )


def _sanitize_text_list_field(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    rows: list[str] = []
    for item in value:
        cleaned = _sanitize_text_fragment(item)
        if cleaned:
            rows.append(cleaned)
    return rows


def _repaired_recipe_requires_empty_mapping_reason(
    *,
    canonical_recipe: "MergedCanonicalRecipe" | None,
    ingredient_step_mapping: Mapping[str, Any] | None,
    ingredient_step_mapping_reason: str | None,
) -> bool:
    if canonical_recipe is None:
        return False
    if ingredient_step_mapping:
        return False
    if str(ingredient_step_mapping_reason or "").strip():
        return False
    return len(canonical_recipe.ingredients) >= 2 or len(canonical_recipe.steps) >= 2


class MergedCanonicalRecipe(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str = Field(alias="t")
    ingredients: list[str] = Field(default_factory=list, alias="i")
    steps: list[str] = Field(default_factory=list, alias="s")
    description: str | None = Field(default=None, alias="d")
    recipe_yield: str | None = Field(
        default=None,
        alias="y",
        validation_alias=AliasChoices("recipe_yield", "recipeYield", "y"),
    )

    @field_validator("title", "description", "recipe_yield", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _sanitize_text_fragment(value)

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def _normalize_text_list_fields(cls, value: Any, info: Any) -> list[str]:
        return _sanitize_text_list_field(value, info.field_name)


class MergedRecipeRepairInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["1"] = Field(default=_BUNDLE_VERSION, alias="v")
    recipe_id: str = Field(alias="rid")
    workbook_slug: str = Field(alias="wb")
    source_hash: str = Field(alias="sh")
    canonical_text: str = Field(alias="txt")
    evidence_rows: list[tuple[int, str]] = Field(default_factory=list, alias="ev")
    draft_hint: dict[str, Any] = Field(default_factory=dict, alias="dh")
    tagging_guide: dict[str, Any] = Field(default_factory=dict, alias="tg")
    authority_notes: list[str] = Field(default_factory=list, alias="an")

    @field_validator("canonical_text", mode="before")
    @classmethod
    def _normalize_canonical_text(cls, value: Any) -> str:
        return _sanitize_text_fragment(value)

    @field_validator("draft_hint", "tagging_guide", mode="before")
    @classmethod
    def _coerce_hint_objects(cls, value: Any, info: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value or {}, info.field_name)

    @field_validator("authority_notes", mode="before")
    @classmethod
    def _normalize_authority_notes(cls, value: Any) -> list[str]:
        return _sanitize_text_list_field(value, "authority_notes")


def serialize_merged_recipe_repair_input(
    payload: "MergedRecipeRepairInput",
) -> dict[str, Any]:
    serialized = payload.model_dump(mode="json", by_alias=True)
    if not serialized.get("draft_hint"):
        serialized.pop("draft_hint", None)
    return serialized


class RecipeCorrectionShardRecipeInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipe_id: str = Field(alias="rid")
    canonical_text: str = Field(alias="txt")
    evidence_rows: list[tuple[int, str]] = Field(default_factory=list, alias="ev")
    warnings: list[str] = Field(default_factory=list, alias="w")

    @field_validator("canonical_text", mode="before")
    @classmethod
    def _normalize_canonical_text(cls, value: Any) -> str:
        return _sanitize_text_fragment(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_warnings(cls, value: Any) -> list[str]:
        return _sanitize_text_list_field(value, "warnings")


class RecipeCorrectionShardInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["1"] = Field(default=_BUNDLE_VERSION, alias="v")
    shard_id: str = Field(alias="sid")
    owned_recipe_ids: list[str] = Field(default_factory=list, alias="ids")
    recipes: list[RecipeCorrectionShardRecipeInput] = Field(default_factory=list, alias="r")
    tagging_guide: dict[str, Any] = Field(default_factory=dict, alias="tg")

    @field_validator("owned_recipe_ids", mode="before")
    @classmethod
    def _normalize_owned_recipe_ids(cls, value: Any) -> list[str]:
        return _sanitize_text_list_field(value, "owned_recipe_ids")

    @field_validator("tagging_guide", mode="before")
    @classmethod
    def _coerce_tagging_guide(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value or {}, "tagging_guide")


def serialize_recipe_correction_shard_input(
    payload: "RecipeCorrectionShardInput",
) -> dict[str, Any]:
    serialized = payload.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_defaults=True,
    )
    serialized.setdefault("v", "1")
    return serialized


class MergedRecipeRepairOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["1"] = Field(default=_BUNDLE_VERSION, alias="v")
    recipe_id: str = Field(alias="rid")
    repair_status: Literal["repaired", "fragmentary", "not_a_recipe"] = Field(
        default="repaired",
        alias="st",
    )
    status_reason: str | None = Field(default=None, alias="sr")
    canonical_recipe: MergedCanonicalRecipe | None = Field(alias="cr")
    ingredient_step_mapping: dict[str, Any] = Field(alias="m")
    ingredient_step_mapping_reason: str | None = Field(default=None, alias="mr")
    divested_block_indices: list[int] = Field(alias="db")
    selected_tags: list["RecipeSelectedTag"] = Field(default_factory=list, alias="g")
    warnings: list[str] = Field(default_factory=list, alias="w")

    @field_validator(
        "recipe_id",
        "status_reason",
        "ingredient_step_mapping_reason",
        mode="before",
    )
    @classmethod
    def _normalize_recipe_output_text_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _sanitize_text_fragment(value)

    @field_validator("canonical_recipe", mode="before")
    @classmethod
    def _coerce_canonical_recipe(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return _coerce_json_object_field(value, "canonical_recipe")

    @field_validator("ingredient_step_mapping", mode="before")
    @classmethod
    def _coerce_ingredient_step_mapping(cls, value: Any) -> dict[str, Any]:
        return _coerce_ingredient_step_mapping_field(value, "ingredient_step_mapping")

    @field_validator("divested_block_indices", mode="before")
    @classmethod
    def _coerce_divested_block_indices(cls, value: Any) -> list[int]:
        return _coerce_nonnegative_int_list(value, "divested_block_indices")

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_output_warnings(cls, value: Any) -> list[str]:
        return _sanitize_text_list_field(value, "warnings")

    @model_validator(mode="after")
    def _validate_status_shape(self) -> "MergedRecipeRepairOutput":
        if self.repair_status == "repaired" and self.canonical_recipe is None:
            raise ValueError("canonical_recipe is required when repair_status is repaired")
        if self.repair_status == "repaired" and _repaired_recipe_requires_empty_mapping_reason(
            canonical_recipe=self.canonical_recipe,
            ingredient_step_mapping=self.ingredient_step_mapping,
            ingredient_step_mapping_reason=self.ingredient_step_mapping_reason,
        ):
            raise ValueError(
                "ingredient_step_mapping_reason is required when repaired recipes with 2+ "
                "ingredients or 2+ steps return an empty ingredient_step_mapping"
            )
        return self


class RecipeCorrectionShardOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["1"] = Field(default=_BUNDLE_VERSION, alias="v")
    shard_id: str = Field(alias="sid")
    recipes: list[MergedRecipeRepairOutput] = Field(default_factory=list, alias="r")


class RecipeSelectedTag(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    category: str = Field(alias="c")
    label: str = Field(alias="l")
    confidence: float | None = Field(default=None, alias="f")

    @field_validator("category", "label", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        text = _sanitize_text_fragment(value)
        if not text:
            raise ValueError("tag fields must be non-empty strings")
        return text

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def load_contract_json(path: Path, model: type[_ModelT]) -> _ModelT:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return model.model_validate(payload)


@dataclass(frozen=True)
class StructuralAuditResult:
    status: Literal["ok", "degraded", "failed"]
    severity: Literal["none", "soft", "hard"]
    reason_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "reason_codes": list(self.reason_codes),
        }
