from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

_BUNDLE_VERSION: Literal["1"] = "1"


class BlockLite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    block_id: str | None = Field(default=None, alias="block_id")
    text: str
    page: int | None = None
    spine_index: int | None = None
    heading_level: int | None = None


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


class Pass2SchemaOrgOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    schemaorg_recipe: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)
    field_evidence: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class Pass3FinalDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    schemaorg_recipe: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)


class Pass3FinalDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    draft_v1: dict[str, Any]
    ingredient_step_mapping: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def load_contract_json(path: Path, model: type[_ModelT]) -> _ModelT:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return model.model_validate(payload)
