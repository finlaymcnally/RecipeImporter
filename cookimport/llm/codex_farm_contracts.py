from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION: Literal["1"] = "1"
_NULL_HEX_PAIR_RE = re.compile(r"\x00([0-9a-fA-F]{2})")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_CONTROL_CHAR_TRANSLATION = str.maketrans({chr(index): " " for index in range(32)})


def _normalize_json_text(raw: str) -> str:
    normalized = _NULL_HEX_PAIR_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        raw,
    )
    normalized = normalized.translate(_CONTROL_CHAR_TRANSLATION)
    normalized = _TRAILING_COMMA_RE.sub(r"\1", normalized)
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
