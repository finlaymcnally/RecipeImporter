from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar
from json import JSONDecodeError

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION: Literal["1"] = "1"


def _coerce_json_object_field(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be a JSON object or JSON object string") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must deserialize to a JSON object")
        return parsed
    raise ValueError(f"{field_name} must be a JSON object or JSON object string")


class BlockLite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    block_id: str | None = Field(default=None, alias="block_id")
    text: str
    page: int | None = None
    spine_index: int | None = None
    heading_level: int | None = None


class PatternHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hint_type: str
    start_block_index: int | None = None
    end_block_index: int | None = None
    note: str | None = None


class Pass1RecipeChunkingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    heuristic_start_block_index: int | None = Field(...)
    heuristic_end_block_index: int | None = Field(...)
    blocks_before: list[BlockLite] = Field(default_factory=list)
    blocks_candidate: list[BlockLite] = Field(default_factory=list)
    blocks_after: list[BlockLite] = Field(default_factory=list)
    pattern_hints: list[PatternHint] = Field(default_factory=list)


class Pass1RecipeChunkingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    is_recipe: bool
    start_block_index: int | None = Field(...)
    end_block_index: int | None = Field(...)
    title: str | None = Field(...)
    reasoning_tags: list[str] = Field(default_factory=list)
    excluded_block_ids: list[str] = Field(default_factory=list)


class Pass2SchemaOrgInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    canonical_text: str
    blocks: list[BlockLite] = Field(default_factory=list)
    normalized_evidence_text: str | None = None
    normalized_evidence_lines: list[str] = Field(default_factory=list)
    normalization_stats: dict[str, int] = Field(default_factory=dict)


class Pass2SchemaOrgOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    schemaorg_recipe: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)
    field_evidence: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("schemaorg_recipe", mode="before")
    @classmethod
    def _coerce_schemaorg_recipe(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "schemaorg_recipe")

    @field_validator("field_evidence", mode="before")
    @classmethod
    def _coerce_field_evidence(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "field_evidence")


class Pass3FinalDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    schemaorg_recipe: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)

    @field_validator("schemaorg_recipe", mode="before")
    @classmethod
    def _coerce_schemaorg_recipe(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "schemaorg_recipe")


class Pass3FinalDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    draft_v1: dict[str, Any]
    ingredient_step_mapping: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("draft_v1", mode="before")
    @classmethod
    def _coerce_draft_v1(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "draft_v1")

    @field_validator("ingredient_step_mapping", mode="before")
    @classmethod
    def _coerce_ingredient_step_mapping(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "ingredient_step_mapping")


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def load_contract_json(path: Path, model: type[_ModelT]) -> _ModelT:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return model.model_validate(payload)
