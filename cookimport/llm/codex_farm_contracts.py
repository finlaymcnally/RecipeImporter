from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_BUNDLE_VERSION: Literal["1"] = "1"
_NULL_HEX_PAIR_RE = re.compile(r"\x00([0-9a-fA-F]{2})")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_CONTROL_CHAR_TRANSLATION = str.maketrans({chr(index): " " for index in range(32)})
_WHITESPACE_RE = re.compile(r"\s+")
_PASS2_EXTRACTIVE_MISMATCH_RE = re.compile(
    r"pass2 (?:ingredient|instruction)\[\d+\] not found in canonical_text",
    re.IGNORECASE,
)
_PLACEHOLDER_TITLES = {
    "recipe",
    "recipe title",
    "recipe name",
    "title unavailable",
    "unknown recipe",
    "untitled recipe",
}
_PLACEHOLDER_STEP_TEXTS = {
    "",
    "n/a",
    "na",
    "not provided",
    "not available",
    "no instruction provided",
    "see original recipe for details",
    "see original recipe",
    "refer to original recipe",
    "follow original recipe",
}
_PASS2_DEGRADING_WARNING_BUCKETS = {
    "missing_instructions",
    "split_line_boundary",
    "ingredient_fragment",
    "page_or_layout_artifact",
}
_PASS2_SOFT_REASON_CODES = {
    "warning_bucket:page_or_layout_artifact",
}


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
                item.get("ingredient_index"),
                f"{field_name}[{index}].ingredient_index",
            )
            step_indexes = _coerce_nonnegative_int_list(
                item.get("step_indexes"),
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


class Pass2SchemaOrgCompactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    evidence_rows: list[tuple[int, str]] = Field(default_factory=list)


class Pass2SchemaOrgOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    schemaorg_recipe: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)
    field_evidence: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _recover_auxiliary_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload["extracted_ingredients"] = _sanitize_text_list_field(
            payload.get("extracted_ingredients"),
            "extracted_ingredients",
        )
        payload["extracted_instructions"] = _sanitize_text_list_field(
            payload.get("extracted_instructions"),
            "extracted_instructions",
        )
        warnings = _string_list(payload.get("warnings"))
        try:
            payload["field_evidence"] = _coerce_json_object_field(
                payload.get("field_evidence"),
                "field_evidence",
            )
        except ValueError:
            payload["field_evidence"] = {}
            warning = (
                "pass2 recovered malformed field_evidence; replaced with empty object."
            )
            if warning not in warnings:
                warnings.append(warning)
        payload["warnings"] = warnings
        return payload

    @field_validator("schemaorg_recipe", mode="before")
    @classmethod
    def _coerce_schemaorg_recipe(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "schemaorg_recipe")


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


class Pass3FinalDraftCompactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    recipe_metadata: dict[str, Any]
    extracted_ingredients: list[str] = Field(default_factory=list)
    extracted_instructions: list[str] = Field(default_factory=list)

    @field_validator("recipe_metadata", mode="before")
    @classmethod
    def _coerce_recipe_metadata(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "recipe_metadata")


class Pass3FinalDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    draft_v1: dict[str, Any]
    ingredient_step_mapping: dict[str, Any]
    ingredient_step_mapping_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("draft_v1", mode="before")
    @classmethod
    def _coerce_draft_v1(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "draft_v1")

    @field_validator("ingredient_step_mapping", mode="before")
    @classmethod
    def _coerce_ingredient_step_mapping(cls, value: Any) -> dict[str, Any]:
        return _coerce_ingredient_step_mapping_field(value, "ingredient_step_mapping")


class MergedCanonicalRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    ingredients: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    description: str | None = None
    recipe_yield: str | None = Field(default=None, alias="recipeYield")

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
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    workbook_slug: str
    source_hash: str
    canonical_text: str
    evidence_rows: list[tuple[int, str]] = Field(default_factory=list)
    recipe_candidate_hint: dict[str, Any] = Field(default_factory=dict)
    draft_hint: dict[str, Any] = Field(default_factory=dict)
    authority_notes: list[str] = Field(default_factory=list)

    @field_validator("canonical_text", mode="before")
    @classmethod
    def _normalize_canonical_text(cls, value: Any) -> str:
        return _sanitize_text_fragment(value)

    @field_validator("recipe_candidate_hint", "draft_hint", mode="before")
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


class MergedRecipeRepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    recipe_id: str
    canonical_recipe: MergedCanonicalRecipe
    ingredient_step_mapping: dict[str, Any]
    ingredient_step_mapping_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("canonical_recipe", mode="before")
    @classmethod
    def _coerce_canonical_recipe(cls, value: Any) -> dict[str, Any]:
        return _coerce_json_object_field(value, "canonical_recipe")

    @field_validator("ingredient_step_mapping", mode="before")
    @classmethod
    def _coerce_ingredient_step_mapping(cls, value: Any) -> dict[str, Any]:
        return _coerce_ingredient_step_mapping_field(value, "ingredient_step_mapping")


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


def classify_pass2_structural_audit(
    *,
    output: Pass2SchemaOrgOutput,
    guard_warnings: list[str],
    transport_verification: dict[str, Any] | None,
) -> StructuralAuditResult:
    reason_codes: list[str] = []
    verification_payload = (
        transport_verification if isinstance(transport_verification, dict) else {}
    )
    if str(verification_payload.get("status") or "").strip().lower() not in {"", "ok"}:
        reason_codes.extend(_string_list(verification_payload.get("reason_codes")))

    title = str(output.schemaorg_recipe.get("name") or "").strip()
    if _is_placeholder_recipe_title(title):
        reason_codes.append("placeholder_title")

    normalized_instructions = _normalized_nonempty_texts(output.extracted_instructions)
    if not normalized_instructions:
        reason_codes.append("missing_instructions")
    elif all(_is_placeholder_instruction(text) for text in normalized_instructions):
        reason_codes.append("placeholder_instructions_only")

    if any(_PASS2_EXTRACTIVE_MISMATCH_RE.search(str(warning or "")) for warning in guard_warnings):
        reason_codes.append("extractive_text_not_in_transport_span")

    warning_buckets = {
        bucket
        for warning in [*output.warnings, *guard_warnings]
        if isinstance(warning, str)
        for bucket in [_pass2_warning_bucket(warning)]
        if bucket is not None
    }
    for bucket in sorted(warning_buckets):
        if bucket in _PASS2_DEGRADING_WARNING_BUCKETS:
            reason_codes.append(f"warning_bucket:{bucket}")

    return _build_structural_audit(
        reason_codes=reason_codes,
        soft_reason_codes=_PASS2_SOFT_REASON_CODES,
    )


def classify_pass3_structural_audit(
    *,
    draft_payload: dict[str, Any],
    pass2_output: Pass2SchemaOrgOutput | None,
    ingredient_step_mapping: dict[str, Any] | None,
    ingredient_step_mapping_reason: str | None,
    pass2_reason_codes: list[str] | None,
) -> StructuralAuditResult:
    reason_codes: list[str] = []
    pass2_reason_codes = pass2_reason_codes or []

    recipe_payload = draft_payload.get("recipe")
    title = ""
    if isinstance(recipe_payload, dict):
        title = str(recipe_payload.get("title") or "").strip()
    if _is_placeholder_recipe_title(title):
        reason_codes.append("placeholder_title")

    steps = draft_payload.get("steps")
    if not isinstance(steps, list):
        reason_codes.append("missing_steps")
        return _build_structural_audit(reason_codes=reason_codes, soft_reason_codes=set())

    rendered_steps: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        instruction = str(step.get("instruction") or "").strip()
        if instruction:
            rendered_steps.append(instruction)
    if not rendered_steps:
        reason_codes.append("missing_steps")
    elif all(_is_placeholder_instruction(step) for step in rendered_steps):
        reason_codes.append("placeholder_steps_only")

    if pass2_output is not None:
        if any(
            reason in {"missing_instructions", "placeholder_instructions_only"}
            for reason in pass2_reason_codes
        ):
            reason_codes.append("upstream_missing_instruction_evidence")

        blocked_snippets = _blocked_schema_snippets(pass2_output)
        extracted_instruction_set = {
            _normalize_text(str(item))
            for item in pass2_output.extracted_instructions
            if _normalize_text(str(item))
        }
        for step in rendered_steps:
            normalized_step = _normalize_text(step)
            if not normalized_step:
                continue
            if any(
                blocked == normalized_step
                or blocked in normalized_step
                or normalized_step in blocked
                for blocked in blocked_snippets
            ) and normalized_step not in extracted_instruction_set:
                reason_codes.append("step_matches_schema_description")
                break

        mapping_payload = (
            ingredient_step_mapping if isinstance(ingredient_step_mapping, dict) else {}
        )
        rendered_mapping_reason = str(ingredient_step_mapping_reason or "").strip()
        nonempty_ingredients = [
            str(item).strip()
            for item in pass2_output.extracted_ingredients
            if str(item).strip()
        ]
        if (
            not mapping_payload
            and not rendered_mapping_reason
            and len(nonempty_ingredients) >= 2
            and len(rendered_steps) >= 2
        ):
            reason_codes.append("empty_mapping_without_reason")

    return _build_structural_audit(reason_codes=reason_codes, soft_reason_codes=set())


def _build_structural_audit(
    *,
    reason_codes: list[str],
    soft_reason_codes: set[str],
) -> StructuralAuditResult:
    normalized = _unique_reason_codes(reason_codes)
    if not normalized:
        return StructuralAuditResult(status="ok", severity="none", reason_codes=[])
    if all(reason in soft_reason_codes for reason in normalized):
        return StructuralAuditResult(
            status="degraded",
            severity="soft",
            reason_codes=normalized,
        )
    return StructuralAuditResult(
        status="failed",
        severity="hard",
        reason_codes=normalized,
    )


def _string_list(value: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        items = []
    for item in items:
        rendered = str(item or "").strip()
        if rendered:
            rows.append(rendered)
    return rows


def _unique_reason_codes(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or "").strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        rows.append(rendered)
    return rows


def _normalize_text(value: str) -> str:
    rendered = str(value or "").strip().lower()
    rendered = re.sub(r"[^a-z0-9]+", " ", rendered)
    return re.sub(r"\s+", " ", rendered).strip()


def _normalized_nonempty_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _normalize_text(str(value))
        if normalized:
            result.append(normalized)
    return result


def _is_placeholder_instruction(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True
    return normalized in _PLACEHOLDER_STEP_TEXTS


def _is_placeholder_recipe_title(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True
    return normalized in _PLACEHOLDER_TITLES


def _pass2_warning_bucket(text: str) -> str | None:
    lowered = _normalize_text(text).replace(" ", "_")
    if not lowered:
        return None
    if "missing_instruction" in lowered:
        return "missing_instructions"
    if "split_line_boundary" in lowered or "split_line" in lowered:
        return "split_line_boundary"
    if "ingredient_fragment" in lowered:
        return "ingredient_fragment"
    if "ocr" in lowered or "page_artifact" in lowered or "page_marker" in lowered:
        return "page_or_layout_artifact"
    return None


def _blocked_schema_snippets(output: Pass2SchemaOrgOutput) -> set[str]:
    blocked_snippets: set[str] = set()
    description = output.schemaorg_recipe.get("description")
    if isinstance(description, str):
        normalized = _normalize_text(description)
        if len(normalized) >= 20:
            blocked_snippets.add(normalized)

    comment_payload = output.schemaorg_recipe.get("comment")
    if isinstance(comment_payload, str):
        normalized = _normalize_text(comment_payload)
        if len(normalized) >= 20:
            blocked_snippets.add(normalized)
    elif isinstance(comment_payload, list):
        for item in comment_payload:
            if isinstance(item, str):
                normalized = _normalize_text(item)
            elif isinstance(item, dict):
                normalized = _normalize_text(str(item.get("text") or ""))
            else:
                normalized = ""
            if len(normalized) >= 20:
                blocked_snippets.add(normalized)
    return blocked_snippets
