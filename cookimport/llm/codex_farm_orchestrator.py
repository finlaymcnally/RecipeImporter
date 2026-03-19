from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.core.progress_messages import format_stage_progress
from cookimport.core.models import ConversionResult, RecipeCandidate, RecipeDraftV1
from cookimport.runs import RECIPE_MANIFEST_FILE_NAME
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1

from .codex_farm_contracts import (
    MergedRecipeRepairInput,
    MergedRecipeRepairOutput,
    RecipeCorrectionShardInput,
    RecipeCorrectionShardOutput,
    RecipeCorrectionShardRecipeInput,
    StructuralAuditResult,
    load_contract_json,
    serialize_merged_recipe_repair_input,
    serialize_recipe_correction_shard_input,
)
from .codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from .codex_farm_runner import (
    CodexFarmRunnerError,
)
from .codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    summarize_direct_telemetry_rows,
)
from .phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    resolve_phase_worker_count,
    ShardProposalV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
)
from .recipe_tagging_guide import build_recipe_tagging_guide
from .shard_prompt_targets import partition_contiguous_items, resolve_shard_count

logger = logging.getLogger(__name__)

SINGLE_CORRECTION_RECIPE_PIPELINE_ID = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
SINGLE_CORRECTION_STAGE_PIPELINE_ID = "recipe.correction.compact.v1"
_CODEX_FARM_RECIPE_MODE_ENV = "COOKIMPORT_CODEX_FARM_RECIPE_MODE"
_ELIGIBILITY_INGREDIENT_LEAD_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s+[A-Za-z]"
)
_ELIGIBILITY_INGREDIENT_UNIT_RE = re.compile(
    r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l|cloves?|sticks?|cans?|pinch)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"toast|transfer|whisk)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_YIELD_PREFIX_RE = re.compile(
    r"^\s*(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_TITLE_LIKE_RE = re.compile(r"^[A-Z][A-Z0-9'/:,\- ]{2,}$")
_AUDIT_PLACEHOLDER_TITLES = {
    "recipe",
    "recipe title",
    "recipe name",
    "title unavailable",
    "unknown recipe",
    "untitled recipe",
}
_AUDIT_PLACEHOLDER_STEP_TEXTS = {
    "",
    "n a",
    "na",
    "not provided",
    "not available",
    "no instruction provided",
    "see original recipe for details",
    "see original recipe",
    "refer to original recipe",
    "follow original recipe",
}
_ELIGIBILITY_CHAPTER_PAGE_HINT_KEYS = (
    "chapter_page_hint",
    "chapter_page_hints",
    "chapter_type",
    "chapter_kind",
    "section_type",
    "section_kind",
    "page_type",
    "page_kind",
    "page_region",
    "layout_region",
    "layout_type",
)
_ELIGIBILITY_TAG_LIST_KEYS = ("heuristic_tags", "reasoning_tags", "tags")
_ELIGIBILITY_CHAPTER_PAGE_NEGATIVE_HINT_TOKENS = (
    "chapter",
    "front_matter",
    "preface",
    "introduction",
    "table_of_contents",
    "toc",
    "index",
    "glossary",
    "appendix",
    "essay",
    "narrative",
    "prose",
    "reference",
    "sidebar",
    "table",
    "chart",
    "mixed_content",
)
_RECIPE_GUARDRAIL_REPORT_SCHEMA_VERSION = "recipe_codex_guardrail_report.v1"
_DEFAULT_RECIPE_SHARD_TARGET_RECIPES = 4
_STRICT_JSON_WATCHDOG_POLICY = "strict_json_no_tools_v1"


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


@dataclass
class CodexFarmApplyResult:
    updated_conversion_result: ConversionResult
    intermediate_overrides_by_recipe_id: dict[str, dict[str, Any]]
    final_overrides_by_recipe_id: dict[str, dict[str, Any]]
    llm_report: dict[str, Any]
    llm_raw_dir: Path


@dataclass
class _RecipeState:
    recipe: RecipeCandidate
    recipe_id: str
    bundle_name: str
    heuristic_start: int | None
    heuristic_end: int | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    single_correction_status: str = "pending"
    final_assembly_status: str = "pending"
    correction_output_status: str | None = None
    correction_output_reason: str | None = None
    structural_status: str = "ok"
    structural_reason_codes: list[str] = field(default_factory=list)
    correction_mapping_status: str | None = None
    correction_mapping_reason: str | None = None


@dataclass(frozen=True)
class _PreparedRecipeInput:
    state: _RecipeState
    correction_input: MergedRecipeRepairInput
    candidate_quality_hint: dict[str, Any]
    evidence_refs: tuple[str, ...]
    block_indices: tuple[int, ...]


@dataclass(frozen=True)
class _RecipeShardPlan:
    shard_id: str
    states: tuple[_RecipeState, ...]
    prepared_inputs: tuple[_PreparedRecipeInput, ...]
    evidence_refs: tuple[str, ...]
    shard_input: RecipeCorrectionShardInput


@dataclass(frozen=True)
class _DirectRecipeWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]

def _recipe_artifact_filename(recipe_id: str) -> str:
    rendered = sanitize_for_filename(str(recipe_id).strip())
    if not rendered:
        rendered = "recipe"
    return f"{rendered}.json"


def _json_bundle_filenames(path: Path) -> list[str]:
    return sorted(child.name for child in path.glob("*.json") if child.is_file())


def _recipe_index_from_bundle_name(bundle_name: str) -> int:
    match = re.match(r"r(\d+)", str(bundle_name or ""))
    if match is None:
        return 0
    return int(match.group(1))


def _build_blocks_for_recipe_state(
    *,
    state: _RecipeState,
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    start = _coerce_int(state.heuristic_start)
    end = _coerce_int(state.heuristic_end)
    if start is None or end is None:
        return []
    lo = min(start, end)
    hi = max(start, end)
    rows: list[dict[str, Any]] = []
    for block_index in range(lo, hi + 1):
        block = full_blocks_by_index.get(block_index)
        if block is not None:
            rows.append(block)
    return rows


def _build_recipe_correction_input(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
    included_blocks: list[dict[str, Any]],
) -> MergedRecipeRepairInput:
    recipe_candidate_hint = state.recipe.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    recipe_candidate_hint.pop("provenance", None)
    compact_recipe_candidate_hint = _compact_recipe_candidate_hint(recipe_candidate_hint)
    return MergedRecipeRepairInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        canonical_text="\n".join(
            str(block.get("text") or "").strip() for block in included_blocks
        ).strip(),
        evidence_rows=[
            (int(block.get("index", 0)), str(block.get("text") or "").strip())
            for block in included_blocks
        ],
        recipe_candidate_hint=compact_recipe_candidate_hint,
        tagging_guide=build_recipe_tagging_guide(),
        authority_notes=[
            "authoritative_source=recipe_span_blocks",
            "correct_intermediate_recipe_candidate",
            "emit_linkage_payload_for_deterministic_final_assembly",
        ],
    )


def _build_recipe_shard_recipe_input(
    *,
    correction_input: MergedRecipeRepairInput,
    candidate_quality_hint: Mapping[str, Any],
    warnings: Sequence[str],
) -> RecipeCorrectionShardRecipeInput:
    return RecipeCorrectionShardRecipeInput(
        recipe_id=correction_input.recipe_id,
        canonical_text=correction_input.canonical_text,
        evidence_rows=list(correction_input.evidence_rows),
        recipe_candidate_hint=dict(correction_input.recipe_candidate_hint),
        candidate_quality_hint=dict(candidate_quality_hint or {}),
        warnings=list(warnings),
    )


def _build_prepared_recipe_input(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
    included_blocks: list[dict[str, Any]],
) -> _PreparedRecipeInput:
    correction_input = _build_recipe_correction_input(
        state=state,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        included_blocks=included_blocks,
    )
    evidence_refs = tuple(
        str(block.get("block_id") or f"b{int(block.get('index', 0))}")
        for block in included_blocks
    )
    block_indices = tuple(int(block.get("index", 0)) for block in included_blocks)
    candidate_quality_hint = _build_recipe_candidate_quality_hint(
        included_blocks=included_blocks,
        recipe_candidate_hint=correction_input.recipe_candidate_hint,
    )
    return _PreparedRecipeInput(
        state=state,
        correction_input=correction_input,
        candidate_quality_hint=candidate_quality_hint,
        evidence_refs=evidence_refs,
        block_indices=block_indices,
    )


def _shard_target_recipe_count(run_settings: RunSettings) -> int:
    try:
        value = int(
            run_settings.recipe_shard_target_recipes
            or _DEFAULT_RECIPE_SHARD_TARGET_RECIPES
        )
    except (TypeError, ValueError):
        value = _DEFAULT_RECIPE_SHARD_TARGET_RECIPES
    return max(1, value)


def _recipe_worker_count(
    run_settings: RunSettings,
    *,
    shard_count: int,
) -> int:
    return resolve_phase_worker_count(
        requested_worker_count=run_settings.recipe_worker_count,
        shard_count=shard_count,
    )


def _build_recipe_shard_plans(
    *,
    prepared_inputs: Sequence[_PreparedRecipeInput],
    run_settings: RunSettings,
) -> list[_RecipeShardPlan]:
    requested_shard_count = resolve_shard_count(
        total_items=len(prepared_inputs),
        prompt_target_count=run_settings.recipe_prompt_target_count,
        items_per_shard=run_settings.recipe_shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    plans: list[_RecipeShardPlan] = []
    for shard_prepared_inputs_list in partition_contiguous_items(
        prepared_inputs,
        shard_count=requested_shard_count,
    ):
        shard_prepared_inputs = tuple(shard_prepared_inputs_list)
        if not shard_prepared_inputs:
            continue
        first_state = shard_prepared_inputs[0].state
        last_state = shard_prepared_inputs[-1].state
        first_recipe_index = _recipe_index_from_bundle_name(first_state.bundle_name)
        last_recipe_index = _recipe_index_from_bundle_name(last_state.bundle_name)
        shard_id = (
            f"recipe-shard-{len(plans):04d}-"
            f"r{first_recipe_index:04d}-r{last_recipe_index:04d}"
        )
        shard_recipe_ids = tuple(
            prepared.state.recipe_id for prepared in shard_prepared_inputs
        )
        shard_input = RecipeCorrectionShardInput(
            shard_id=shard_id,
            owned_recipe_ids=list(shard_recipe_ids),
            recipes=[
                _build_recipe_shard_recipe_input(
                    correction_input=prepared.correction_input,
                    candidate_quality_hint=prepared.candidate_quality_hint,
                    warnings=prepared.state.warnings,
                )
                for prepared in shard_prepared_inputs
            ],
            tagging_guide=build_recipe_tagging_guide(),
        )
        evidence_refs = tuple(
            ref
            for prepared in shard_prepared_inputs
            for ref in prepared.evidence_refs
        )
        plans.append(
            _RecipeShardPlan(
                shard_id=shard_id,
                states=tuple(prepared.state for prepared in shard_prepared_inputs),
                prepared_inputs=shard_prepared_inputs,
                evidence_refs=evidence_refs,
                shard_input=shard_input,
            )
        )
    return plans


def _compact_recipe_candidate_hint(recipe_candidate_hint: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(recipe_candidate_hint or {})
    compact: dict[str, Any] = {}

    name = str(payload.get("name") or "").strip()
    if name:
        compact["n"] = name

    ingredients = [
        str(item).strip()
        for item in payload.get("recipeIngredient") or []
        if str(item).strip()
    ]
    if ingredients:
        compact["i"] = ingredients

    steps = _compact_recipe_step_hints(payload.get("recipeInstructions") or [])
    if steps:
        compact["s"] = steps

    description = str(payload.get("description") or "").strip()
    if description:
        compact["d"] = description

    recipe_yield = str(payload.get("recipeYield") or "").strip()
    if recipe_yield:
        compact["y"] = recipe_yield

    tags = [str(item).strip() for item in payload.get("tags") or [] if str(item).strip()]
    if tags:
        compact["g"] = tags

    return compact


def _compact_recipe_step_hints(raw_steps: Sequence[Any]) -> list[str]:
    steps: list[str] = []
    for item in raw_steps:
        rendered = _coerce_compact_step_hint_text(item)
        if rendered:
            steps.append(rendered)
    return steps


def _coerce_compact_step_hint_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return str(value).strip()
    if isinstance(value, Mapping):
        for key in ("text", "name"):
            rendered = str(value.get(key) or "").strip()
            if rendered:
                return rendered
        return ""
    return ""


def _build_recipe_candidate_quality_hint(
    *,
    included_blocks: Sequence[Mapping[str, Any]],
    recipe_candidate_hint: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_lines = [
        str(block.get("text") or "").strip()
        for block in included_blocks
        if str(block.get("text") or "").strip()
    ]
    evidence_row_count = len(evidence_lines)
    evidence_ingredient_count = sum(
        1 for line in evidence_lines if _looks_like_ingredient_line(line)
    )
    evidence_step_count = sum(1 for line in evidence_lines if _looks_like_step_line(line))
    hint_ingredient_count = sum(
        1
        for item in recipe_candidate_hint.get("i") or []
        if str(item or "").strip()
    )
    hint_step_count = sum(
        1
        for item in recipe_candidate_hint.get("s") or []
        if str(item or "").strip()
    )
    title_hint = str(recipe_candidate_hint.get("n") or "").strip()
    suspicion_flags: list[str] = []
    if evidence_row_count <= 2:
        suspicion_flags.append("short_span")
    if evidence_ingredient_count == 0:
        suspicion_flags.append("source_no_ingredient_lines")
    if evidence_step_count == 0:
        suspicion_flags.append("source_no_instruction_lines")
    if hint_ingredient_count == 0:
        suspicion_flags.append("hint_no_ingredients")
    if hint_step_count == 0:
        suspicion_flags.append("hint_no_steps")
    if not title_hint:
        suspicion_flags.append("hint_no_title")
    elif (
        _ELIGIBILITY_TITLE_LIKE_RE.fullmatch(title_hint)
        and evidence_ingredient_count == 0
        and evidence_step_count == 0
    ):
        suspicion_flags.append("title_looks_sectional")
    return {
        "e": evidence_row_count,
        "ei": evidence_ingredient_count,
        "es": evidence_step_count,
        "hi": hint_ingredient_count,
        "hs": hint_step_count,
        "f": suspicion_flags,
    }


def _looks_like_ingredient_line(text: str) -> bool:
    rendered = str(text or "").strip()
    if not rendered:
        return False
    if _ELIGIBILITY_YIELD_PREFIX_RE.search(rendered):
        return False
    return bool(
        _ELIGIBILITY_INGREDIENT_LEAD_RE.search(rendered)
        or _ELIGIBILITY_INGREDIENT_UNIT_RE.search(rendered)
    )


def _looks_like_step_line(text: str) -> bool:
    rendered = str(text or "").strip()
    if not rendered:
        return False
    return bool(_ELIGIBILITY_INSTRUCTION_VERB_RE.search(rendered))


def _corrected_candidate_from_output(
    *,
    state: _RecipeState,
    output: MergedRecipeRepairOutput,
) -> RecipeCandidate:
    selected_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in list(state.recipe.tags) + [entry.label for entry in output.selected_tags]:
        rendered = str(tag or "").strip()
        if not rendered or rendered in seen_tags:
            continue
        seen_tags.add(rendered)
        selected_tags.append(rendered)
    return state.recipe.model_copy(
        update={
            "name": output.canonical_recipe.title,
            "ingredients": list(output.canonical_recipe.ingredients),
            "instructions": list(output.canonical_recipe.steps),
            "description": output.canonical_recipe.description,
            "recipe_yield": output.canonical_recipe.recipe_yield,
            "tags": selected_tags,
        },
        deep=True,
    )


def _build_recipe_correction_audit(
    *,
    state: _RecipeState,
    correction_input: MergedRecipeRepairInput,
    correction_output: MergedRecipeRepairOutput,
    corrected_candidate: RecipeCandidate | None,
    final_payload: dict[str, Any] | None,
    final_assembly_status: str,
    structural_audit: StructuralAuditResult,
    mapping_status: str | None,
    mapping_reason: str | None,
) -> dict[str, Any]:
    canonical_recipe = correction_output.canonical_recipe
    return {
        "schema_version": "recipe_correction_audit.v1",
        "recipe_id": state.recipe_id,
        "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
        "stage_pipeline_id": SINGLE_CORRECTION_STAGE_PIPELINE_ID,
        "input": {
            "block_count": len(correction_input.evidence_rows),
            "canonical_char_count": len(correction_input.canonical_text),
            "authority_notes": list(correction_input.authority_notes),
            "payload": serialize_merged_recipe_repair_input(correction_input),
        },
        "output": {
            "repair_status": correction_output.repair_status,
            "status_reason": correction_output.status_reason,
            "title": canonical_recipe.title if canonical_recipe is not None else None,
            "ingredient_count": (
                len(canonical_recipe.ingredients) if canonical_recipe is not None else 0
            ),
            "step_count": len(canonical_recipe.steps) if canonical_recipe is not None else 0,
            "selected_tags": [
                {
                    "category": tag.category,
                    "label": tag.label,
                    "confidence": tag.confidence,
                }
                for tag in correction_output.selected_tags
            ],
            "warning_count": len(correction_output.warnings),
            "ingredient_step_mapping": correction_output.ingredient_step_mapping,
            "ingredient_step_mapping_reason": correction_output.ingredient_step_mapping_reason,
            "payload": _serialize_recipe_correction_output(correction_output),
        },
        "deterministic_final_assembly": {
            "status": final_assembly_status,
            "corrected_candidate_title": (
                corrected_candidate.name if corrected_candidate is not None else None
            ),
            "final_step_count": len(list((final_payload or {}).get("steps") or [])),
            "mapping_status": mapping_status,
            "mapping_reason": mapping_reason,
        },
        "structural_audit": structural_audit.to_dict(),
    }


def _serialize_recipe_correction_output(
    output: MergedRecipeRepairOutput,
) -> dict[str, Any]:
    return output.model_dump(mode="json", by_alias=True)


def _serialize_recipe_correction_shard_output(
    output: RecipeCorrectionShardOutput,
) -> dict[str, Any]:
    return output.model_dump(mode="json", by_alias=True)


def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _validate_recipe_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, Sequence[str], Mapping[str, Any] | None]:
    try:
        shard_output = RecipeCorrectionShardOutput.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        return False, (f"invalid_shard_output:{exc}",), None

    validation_errors: list[str] = []
    if shard_output.shard_id != shard.shard_id:
        validation_errors.append("shard_id_mismatch")

    expected_ids = list(shard.owned_ids)
    actual_ids = [recipe.recipe_id for recipe in shard_output.recipes]
    duplicate_ids = sorted({recipe_id for recipe_id in actual_ids if actual_ids.count(recipe_id) > 1})
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    unexpected_ids = sorted(set(actual_ids) - set(expected_ids))
    if duplicate_ids:
        validation_errors.append("duplicate_recipe_ids")
    if missing_ids:
        validation_errors.append("missing_recipe_ids")
    if unexpected_ids:
        validation_errors.append("unexpected_recipe_ids")

    metadata = {
        "owned_recipe_ids": expected_ids,
        "actual_recipe_ids": actual_ids,
        "duplicate_recipe_ids": duplicate_ids,
        "missing_recipe_ids": missing_ids,
        "unexpected_recipe_ids": unexpected_ids,
        "recipe_count": len(actual_ids),
    }
    return not validation_errors, tuple(validation_errors), metadata


def _evaluate_recipe_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    payload = parsed_payload
    valid, validation_errors, validation_metadata = _validate_recipe_shard_output(
        shard,
        parsed_payload,
    )
    if valid:
        payload = _serialize_recipe_correction_shard_output(
            RecipeCorrectionShardOutput.model_validate(parsed_payload)
        )
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _preflight_recipe_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    payload = _coerce_mapping_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    recipe_rows = payload.get("r")
    if not owned_ids:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "recipe shard has no owned recipe ids",
        }
    if not isinstance(recipe_rows, list) or not recipe_rows:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "recipe shard has no model-facing recipes",
        }
    payload_shard_id = str(payload.get("sid") or "").strip()
    if payload_shard_id and payload_shard_id != shard.shard_id:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "recipe shard input `sid` does not match the manifest shard id",
        }
    recipe_ids: list[str] = []
    for recipe_row in recipe_rows:
        if not isinstance(recipe_row, Mapping):
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "recipe shard contains a non-object recipe payload",
            }
        recipe_id = str(recipe_row.get("rid") or "").strip()
        if not recipe_id:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "recipe shard contains a recipe without `rid`",
            }
        recipe_ids.append(recipe_id)
    if sorted(recipe_ids) != sorted(owned_ids):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "recipe shard owned ids do not match model-facing recipe ids",
        }
    return None


def _build_preflight_rejected_run_result(
    *,
    prompt_text: str,
    output_schema_path: Path | None,
    working_dir: Path,
    reason_code: str,
    reason_detail: str,
) -> CodexExecRunResult:
    timestamp = _format_utc_now()
    return CodexExecRunResult(
        command=[],
        subprocess_exit_code=0,
        output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
        prompt_text=prompt_text,
        response_text=None,
        turn_failed_message=reason_detail,
        events=(),
        usage={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        source_working_dir=str(working_dir),
        execution_working_dir=None,
        execution_agents_path=None,
        duration_ms=0,
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
        supervision_state="preflight_rejected",
        supervision_reason_code=reason_code,
        supervision_reason_detail=reason_detail,
        supervision_retryable=False,
    )


def _build_recipe_watchdog_callback(
    *,
    live_status_path: Path,
    shard_id: str | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        decision: CodexExecSupervisionDecision | None = None
        if snapshot.command_execution_count > 0:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_command_execution_forbidden",
                reason_detail="strict JSON stage attempted tool use",
                retryable=False,
            )
        elif snapshot.reasoning_item_count >= 2 and not snapshot.has_final_agent_message:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_reasoning_without_output",
                reason_detail="strict JSON stage emitted repeated reasoning without a final answer",
                retryable=False,
            )
        _write_live_status(
            live_status_path,
            {
                "state": (
                    "watchdog_killed"
                    if isinstance(decision, CodexExecSupervisionDecision)
                    and decision.action == "terminate"
                    else "running"
                ),
                "elapsed_seconds": round(snapshot.elapsed_seconds, 3),
                "last_event_seconds_ago": (
                    round(snapshot.last_event_seconds_ago, 3)
                    if snapshot.last_event_seconds_ago is not None
                    else None
                ),
                "event_count": snapshot.event_count,
                "command_execution_count": snapshot.command_execution_count,
                "reasoning_item_count": snapshot.reasoning_item_count,
                "last_command": snapshot.last_command,
                "last_command_repeat_count": snapshot.last_command_repeat_count,
                "has_final_agent_message": snapshot.has_final_agent_message,
                "timeout_seconds": snapshot.timeout_seconds,
                "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
                "shard_id": shard_id,
                "reason_code": decision.reason_code if decision is not None else None,
                "reason_detail": decision.reason_detail if decision is not None else None,
                "retryable": decision.retryable if decision is not None else False,
            },
        )
        return decision

    return _callback


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
) -> None:
    _write_live_status(
        live_status_path,
        {
            "state": run_result.supervision_state or "completed",
            "reason_code": run_result.supervision_reason_code,
            "reason_detail": run_result.supervision_reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
        },
    )


def _write_live_status(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(dict(payload), path)


def _failure_reason_from_run_result(
    *,
    run_result: CodexExecRunResult,
    proposal_status: str,
) -> str:
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code)
    if str(run_result.supervision_state or "").strip() in {
        "preflight_rejected",
        "watchdog_killed",
    }:
        return str(run_result.supervision_state)
    return (
        "proposal_validation_failed"
        if proposal_status == "invalid"
        else "missing_output_file"
    )


def _should_attempt_recipe_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
) -> bool:
    if proposal_status != "invalid":
        return False
    repairable_prefixes = ("invalid_shard_output:",)
    repairable_errors = {
        "response_json_invalid",
        "response_not_json_object",
        "shard_id_mismatch",
        "missing_recipe_ids",
        "duplicate_recipe_ids",
    }
    for error in validation_errors:
        if error in repairable_errors or str(error).startswith(repairable_prefixes):
            return True
    return False


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_recipe_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    pipeline_id: str,
    worker_id: str,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    live_status_path: Path,
) -> CodexExecRunResult:
    prompt_text = _build_recipe_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    shard_root = worker_root / "shards" / shard.shard_id
    (shard_root / "repair_prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "recipe",
            "pipeline_id": pipeline_id,
            "worker_id": worker_id,
            "sid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "authoritative_input": dict(shard.input_payload or {}),
            "previous_output": _truncate_recipe_repair_text(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="recipe correction repair shard",
        supervision_callback=_build_recipe_watchdog_callback(
            live_status_path=live_status_path,
            shard_id=shard.shard_id,
        ),
    )


def _build_recipe_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    owned_recipe_ids = ", ".join(str(recipe_id) for recipe_id in shard.owned_ids)
    missing_recipe_ids = ", ".join(
        str(recipe_id)
        for recipe_id in (validation_metadata.get("missing_recipe_ids") or [])
    )
    authoritative_input = json.dumps(
        dict(shard.input_payload or {}),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Repair the invalid recipe correction shard output.\n\n"
        "Rules:\n"
        "- Return strict JSON only.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        f"- `sid` must be `{shard.shard_id}`.\n"
        f"- Return exactly one recipe result for each owned recipe id: {owned_recipe_ids}\n"
        "- Use only owned recipe ids and do not invent extra recipes.\n"
        "- Preserve `not_a_recipe` and `fragmentary` when the candidate is truly unusable.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        f"Missing recipe ids: {missing_recipe_ids or '[none recorded]'}\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_recipe_repair_text(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _build_recipe_repair_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            row_payload["prompt_input_mode"] = "inline_repair"
            row_payload["request_input_file"] = None
            row_payload["request_input_file_bytes"] = None
    summary_payload = telemetry.get("summary") if isinstance(telemetry, dict) else None
    if isinstance(summary_payload, dict):
        summary_payload["prompt_input_mode"] = "inline_repair"
        summary_payload["request_input_file_bytes_total"] = None
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "inline_repair",
    }
    return payload


def _truncate_recipe_repair_text(text: str, *, max_chars: int = 20_000) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "\n...[truncated]"


def _aggregate_recipe_phase_process_run(
    *,
    phase_manifest: Mapping[str, Any],
    worker_reports: Sequence[Mapping[str, Any]],
    promotion_report: Mapping[str, Any],
    telemetry: Mapping[str, Any],
) -> dict[str, Any]:
    worker_runs = [
        dict(report.get("runner_result") or {})
        for report in worker_reports
        if isinstance(report.get("runner_result"), dict)
    ]
    runtime_mode_audits = [
        dict(report.get("runtime_mode_audit") or {})
        for report in worker_reports
        if isinstance(report.get("runtime_mode_audit"), dict)
    ]
    pipeline_id = str(phase_manifest.get("pipeline_id") or SINGLE_CORRECTION_STAGE_PIPELINE_ID)
    return {
        "pipeline_id": pipeline_id,
        "runtime_mode": str(
            phase_manifest.get("runtime_mode") or DIRECT_CODEX_EXEC_RUNTIME_MODE_V1
        ),
        "worker_run_count": len(worker_runs),
        "worker_runs": worker_runs,
        "runtime_mode_audits": runtime_mode_audits,
        "phase_manifest": dict(phase_manifest),
        "promotion_report": dict(promotion_report),
        "telemetry_report": dict(telemetry),
    }


def _recipe_result_rows_from_proposals(
    proposals: Sequence[ShardProposalV1],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        if proposal.status != "validated" or not isinstance(proposal.payload, dict):
            continue
        try:
            shard_output = RecipeCorrectionShardOutput.model_validate(proposal.payload)
        except Exception:  # noqa: BLE001
            continue
        for recipe_output in shard_output.recipes:
            rows[recipe_output.recipe_id] = {
                "repair_status": recipe_output.repair_status,
                "status_reason": recipe_output.status_reason,
            }
    return rows


def _load_pipeline_assets(*, pipeline_root: Path, pipeline_id: str) -> dict[str, Any]:
    pipeline_path = pipeline_root / "pipelines" / f"{pipeline_id}.json"
    if not pipeline_path.exists():
        fallback_root = Path(__file__).resolve().parents[2] / "llm_pipelines"
        fallback_path = fallback_root / "pipelines" / f"{pipeline_id}.json"
        if fallback_path.exists():
            pipeline_root = fallback_root
            pipeline_path = fallback_path
    pipeline_payload = json.loads(pipeline_path.read_text(encoding="utf-8"))
    prompt_template_rel = str(pipeline_payload.get("prompt_template_path") or "").strip()
    output_schema_rel = str(pipeline_payload.get("output_schema_path") or "").strip()
    prompt_template_path = pipeline_root / prompt_template_rel
    output_schema_path = pipeline_root / output_schema_rel
    return {
        "pipeline_payload": pipeline_payload,
        "prompt_template_text": prompt_template_path.read_text(encoding="utf-8"),
        "prompt_template_path": str(prompt_template_path),
        "output_schema_path": output_schema_path,
    }


def render_recipe_direct_prompt(
    *,
    pipeline_assets: Mapping[str, Any],
    input_text: str,
    input_path: Path,
) -> str:
    rendered = str(pipeline_assets.get("prompt_template_text") or "")
    rendered = rendered.replace("{{INPUT_TEXT}}", input_text)
    rendered = rendered.replace("{{ INPUT_TEXT }}", input_text)
    rendered = rendered.replace("{{INPUT_PATH}}", str(input_path))
    rendered = rendered.replace("{{ INPUT_PATH }}", str(input_path))
    return rendered


def _build_single_correction_manifest(
    *,
    run_settings: RunSettings,
    llm_raw_dir: Path,
    correction_audit_dir: Path,
    manifest_path: Path,
    states: list[_RecipeState],
    process_runs: dict[str, dict[str, Any]],
    output_schema_paths: dict[str, str],
    timing_seconds: float,
    recipe_shards: Sequence[_RecipeShardPlan] = (),
    phase_runtime_dir: Path | None = None,
    phase_runtime_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    recipe_rows: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for state in states:
        row = {
            "build_intermediate_det": "ok",
            "recipe_llm_correct_and_link": state.single_correction_status,
            "build_final_recipe": state.final_assembly_status,
            "warnings": list(state.warnings),
            "errors": list(state.errors),
            "structural_status": state.structural_status,
            "structural_reason_codes": list(state.structural_reason_codes),
        }
        if state.correction_output_status:
            row["correction_output_status"] = state.correction_output_status
        if state.correction_output_reason:
            row["correction_output_reason"] = state.correction_output_reason
        mapping_status = getattr(state, "correction_mapping_status", None)
        mapping_reason = getattr(state, "correction_mapping_reason", None)
        if mapping_status:
            row["mapping_status"] = mapping_status
        if mapping_reason:
            row["mapping_reason"] = mapping_reason
        recipe_rows[state.recipe_id] = row
        if state.errors:
            failures.append({"recipe_id": state.recipe_id, "errors": list(state.errors)})

    return {
        "enabled": True,
        "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
        "codex_farm_cmd": run_settings.codex_farm_cmd,
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": _effort_override_value(
            run_settings.codex_farm_reasoning_effort
        ),
        "codex_farm_root": run_settings.codex_farm_root,
        "codex_farm_workspace_root": run_settings.codex_farm_workspace_root,
        "counts": {
            "recipes_total": len(states),
            "build_intermediate_det_ok": len(states),
            "recipe_shards_total": len(recipe_shards),
            "recipe_workers_total": int(
                (phase_runtime_summary or {}).get("worker_count") or 0
            ),
            "recipe_correction_inputs": len(states),
            "recipe_correction_ok": sum(
                1
                for state in states
                if state.single_correction_status == "ok"
            ),
            "recipe_correction_error": sum(
                1
                for state in states
                if state.single_correction_status == "error"
            ),
            "recipe_correction_repaired": sum(
                1 for state in states if state.correction_output_status == "repaired"
            ),
            "recipe_correction_fragmentary": sum(
                1 for state in states if state.correction_output_status == "fragmentary"
            ),
            "recipe_correction_not_a_recipe": sum(
                1 for state in states if state.correction_output_status == "not_a_recipe"
            ),
            "build_final_recipe_ok": sum(
                1
                for state in states
                if state.final_assembly_status == "ok"
            ),
            "build_final_recipe_error": sum(
                1
                for state in states
                if state.final_assembly_status == "error"
            ),
            "build_final_recipe_skipped": sum(
                1 for state in states if state.final_assembly_status == "skipped"
            ),
        },
        "timing": {
            "recipe_correction_seconds": round(timing_seconds, 3),
        },
        "pipelines": {
            "recipe_correction": SINGLE_CORRECTION_STAGE_PIPELINE_ID,
        },
        "output_schema_paths": dict(output_schema_paths),
        "paths": {
            "recipe_correction_audit_dir": str(correction_audit_dir),
            "recipe_phase_input_dir": (
                str(phase_runtime_dir / "inputs") if phase_runtime_dir else None
            ),
            "recipe_phase_proposals_dir": (
                str(phase_runtime_dir / "proposals") if phase_runtime_dir else None
            ),
            "recipe_manifest": str(manifest_path),
            "recipe_phase_runtime_dir": str(phase_runtime_dir) if phase_runtime_dir else None,
        },
        "process_runs": dict(process_runs),
        "phase_runtime": dict(phase_runtime_summary or {}),
        "failures": failures,
        "recipes": recipe_rows,
        "llm_raw_dir": str(llm_raw_dir),
    }


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")


def _serialize_compact_prompt_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _render_events_jsonl(events: Sequence[dict[str, Any]]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _assign_recipe_workers_v1(
    *,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shards),
    )
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [
        WorkerAssignmentV1(
            worker_id=f"worker-{index + 1:03d}",
            shard_ids=tuple(bucket),
            workspace_root=str(run_root / "workers" / f"worker-{index + 1:03d}"),
        )
        for index, bucket in enumerate(buckets)
    ]


def _run_direct_recipe_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    pipeline_assets: Mapping[str, Any],
    shard_completed_callback: Callable[..., None] | None,
) -> _DirectRecipeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json([asdict(shard) for shard in assigned_shards], worker_root / "assigned_shards.json")

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []

    for shard in assigned_shards:
        input_path = in_dir / f"{shard.shard_id}.json"
        serialized_input = _serialize_compact_prompt_json(shard.input_payload)
        _write_worker_input(path=input_path, payload=shard.input_payload, input_text=serialized_input)
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        prompt_text = render_recipe_direct_prompt(
            pipeline_assets=pipeline_assets,
            input_text=serialized_input,
            input_path=input_path,
        )
        (shard_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        preflight_failure = _preflight_recipe_shard(shard)
        if preflight_failure is not None:
            run_result = _build_preflight_rejected_run_result(
                prompt_text=prompt_text,
                output_schema_path=output_schema_path,
                working_dir=worker_root,
                reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
                reason_detail=str(
                    preflight_failure.get("reason_detail") or "recipe shard failed preflight"
                ),
            )
            _write_live_status(
                shard_root / "live_status.json",
                {
                    "state": "preflight_rejected",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                    "watchdog_policy": _STRICT_JSON_WATCHDOG_POLICY,
                    "elapsed_seconds": 0.0,
                    "last_event_seconds_ago": None,
                    "command_execution_count": 0,
                    "reasoning_item_count": 0,
                },
            )
        else:
            run_result = runner.run_structured_prompt(
                prompt_text=prompt_text,
                input_payload=_coerce_mapping_dict(shard.input_payload),
                working_dir=worker_root,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                workspace_task_label="recipe correction shard",
                supervision_callback=_build_recipe_watchdog_callback(
                    live_status_path=shard_root / "live_status.json",
                    shard_id=shard.shard_id,
                ),
            )
        _finalize_live_status(
            shard_root / "live_status.json",
            run_result=run_result,
        )
        worker_runner_payload = run_result.to_payload(
            worker_id=assignment.worker_id,
            shard_id=shard.shard_id,
        )
        worker_runner_payload["pipeline_id"] = pipeline_id
        worker_runner_results.append(worker_runner_payload)
        stage_row = run_result.telemetry_row(
            worker_id=assignment.worker_id,
            shard_id=shard.shard_id,
        )
        stage_rows.append(stage_row)
        primary_runner_telemetry = worker_runner_payload.get("telemetry")
        primary_runner_rows = (
            primary_runner_telemetry.get("rows")
            if isinstance(primary_runner_telemetry, Mapping)
            else None
        )
        primary_runner_row = (
            primary_runner_rows[0]
            if isinstance(primary_runner_rows, list)
            and primary_runner_rows
            and isinstance(primary_runner_rows[0], dict)
            else None
        )
        (shard_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, shard_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), shard_root / "usage.json")
        _write_json(
            dict(stage_row.get("cost_breakdown") or {}),
            shard_root / "cost_breakdown.json",
        )
        _write_json(run_result.workspace_manifest(), shard_root / "workspace_manifest.json")

        payload, validation_errors, validation_metadata, proposal_status = (
            _evaluate_recipe_response(
                shard=shard,
                response_text=run_result.response_text,
            )
        )
        initial_proposal_status = proposal_status
        repair_attempted = False
        repair_status = "not_attempted"
        if _should_attempt_recipe_repair(
            proposal_status=proposal_status,
            validation_errors=validation_errors,
        ):
            repair_attempted = True
            repair_run_result = _run_recipe_repair_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=shard,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                original_response_text=str(run_result.response_text or ""),
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                live_status_path=shard_root / "repair_live_status.json",
            )
            _finalize_live_status(
                shard_root / "repair_live_status.json",
                run_result=repair_run_result,
            )
            repair_payload = _build_recipe_repair_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
                run_result=repair_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            worker_runner_results.append(dict(repair_payload))
            repair_rows = (
                repair_payload.get("telemetry", {}).get("rows")
                if isinstance(repair_payload.get("telemetry"), dict)
                else None
            )
            if isinstance(repair_rows, list):
                for row_payload in repair_rows:
                    if isinstance(row_payload, dict):
                        row_payload["is_repair_attempt"] = True
                        row_payload["repair_attempt_index"] = 1
                        stage_rows.append(dict(row_payload))
            (shard_root / "repair_events.jsonl").write_text(
                _render_events_jsonl(repair_run_result.events),
                encoding="utf-8",
            )
            _write_json(
                {"text": repair_run_result.response_text},
                shard_root / "repair_last_message.json",
            )
            _write_json(
                dict(repair_run_result.usage or {}),
                shard_root / "repair_usage.json",
            )
            _write_json(
                repair_run_result.workspace_manifest(),
                shard_root / "repair_workspace_manifest.json",
            )
            (
                repair_payload_candidate,
                repair_errors,
                repair_metadata,
                repair_proposal_status,
            ) = _evaluate_recipe_response(
                shard=shard,
                response_text=repair_run_result.response_text,
            )
            repair_status = (
                "repaired" if repair_proposal_status == "validated" else "failed"
            )
            if stage_rows:
                repair_row = stage_rows[-1]
                repair_row["proposal_status"] = repair_proposal_status
                repair_row["repair_attempted"] = True
                repair_row["repair_status"] = repair_status
            if isinstance(repair_rows, list) and repair_rows:
                repair_runner_row = repair_rows[0]
                if isinstance(repair_runner_row, dict):
                    repair_runner_row["proposal_status"] = repair_proposal_status
                    repair_runner_row["repair_attempted"] = True
                    repair_runner_row["repair_status"] = repair_status
            _write_json(
                {
                    "attempted": True,
                    "status": repair_status,
                    "original_validation_errors": list(validation_errors),
                    "repair_validation_errors": list(repair_errors),
                    "state": repair_run_result.supervision_state or "completed",
                    "reason_code": repair_run_result.supervision_reason_code,
                    "reason_detail": repair_run_result.supervision_reason_detail,
                    "retryable": repair_run_result.supervision_retryable,
                },
                shard_root / "repair_status.json",
            )
            if repair_proposal_status == "validated":
                payload = repair_payload_candidate
                validation_errors = repair_errors
                validation_metadata = dict(repair_metadata or {})
                proposal_status = "validated"
            else:
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "repair_validation_errors": list(repair_errors),
                }
        stage_row["proposal_status"] = (
            initial_proposal_status if repair_attempted else proposal_status
        )
        stage_row["final_proposal_status"] = proposal_status
        stage_row["repair_attempted"] = repair_attempted
        stage_row["repair_status"] = repair_status
        if primary_runner_row is not None:
            primary_runner_row["proposal_status"] = (
                initial_proposal_status if repair_attempted else proposal_status
            )
            primary_runner_row["final_proposal_status"] = proposal_status
            primary_runner_row["repair_attempted"] = repair_attempted
            primary_runner_row["repair_status"] = repair_status

        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "state": run_result.supervision_state or "completed",
                "reason_code": run_result.supervision_reason_code,
                "reason_detail": run_result.supervision_reason_detail,
                "retryable": run_result.supervision_retryable,
            },
            proposal_path,
        )
        _write_json(
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "state": run_result.supervision_state or "completed",
                "reason_code": run_result.supervision_reason_code,
                "reason_detail": run_result.supervision_reason_detail,
                "retryable": run_result.supervision_retryable,
            },
            shard_root / "status.json",
        )

        if proposal_status != "validated":
            worker_failure_count += 1
            reason = _failure_reason_from_run_result(
                run_result=run_result,
                proposal_status=proposal_status,
            )
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": reason,
                    "validation_errors": list(validation_errors),
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                }
            )
        else:
            worker_proposal_count += 1

        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=payload,
                validation_errors=validation_errors,
                metadata={
                    **dict(validation_metadata or {}),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                },
            )
        )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_summary = summarize_direct_telemetry_rows(stage_rows)
    worker_runner_payload = {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": worker_runner_results,
        "telemetry": {
            "rows": stage_rows,
            "summary": worker_summary,
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": output_schema_path is not None,
            "tool_affordances_requested": False,
        },
    }
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectRecipeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": output_schema_path is not None,
                "tool_affordances_requested": False,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
    )


def _run_direct_recipe_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    runner: CodexExecRunner,
    worker_count: int,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    pipeline_assets: Mapping[str, Any],
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_recipe_workers_v1(
        run_root=run_root,
        shards=shards,
        worker_count=worker_count,
    )
    _write_jsonl(
        run_root / artifacts["shard_manifest"],
        [asdict(shard) for shard in shards],
    )
    _write_json(
        [asdict(assignment) for assignment in assignments],
        run_root / artifacts["worker_assignments"],
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    completed_shards = 0
    total_shards = len(shards)
    progress_lock = threading.Lock()
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }
    if progress_callback is not None and total_shards > 0:
        active_tasks = [
            assignment.shard_ids[0]
            for assignment in assignments
            if assignment.shard_ids
        ]
        progress_callback(
            format_stage_progress(
                "Running recipe correction... task 0/" + str(total_shards),
                stage_label="recipe pipeline",
                task_current=0,
                task_total=total_shards,
                running_workers=min(len(active_tasks), total_shards),
                worker_total=len(assignments),
                active_tasks=active_tasks[:total_shards],
            )
        )

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        nonlocal completed_shards
        if progress_callback is None:
            return
        with progress_lock:
            pending = pending_shards_by_worker.get(worker_id) or []
            if shard_id in pending:
                pending.remove(shard_id)
            completed_shards += 1
            remaining = max(0, total_shards - completed_shards)
            active_tasks = [
                worker_pending[0]
                for worker_pending in pending_shards_by_worker.values()
                if worker_pending
            ]
            progress_callback(
                format_stage_progress(
                    f"Running recipe correction... task {completed_shards}/{total_shards}",
                    stage_label="recipe pipeline",
                    task_current=completed_shards,
                    task_total=total_shards,
                    running_workers=min(len(active_tasks), remaining),
                    worker_total=len(assignments),
                    active_tasks=active_tasks[:remaining] if remaining > 0 else [],
                )
            )

    with ThreadPoolExecutor(
        max_workers=max(1, len(assignments)),
        thread_name_prefix="recipe-worker",
    ) as executor:
        futures_by_worker_id = {
            assignment.worker_id: executor.submit(
                _run_direct_recipe_worker_assignment_v1,
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                pipeline_assets=pipeline_assets,
                shard_completed_callback=_mark_shard_completed,
            )
            for assignment in assignments
        }
        for assignment in assignments:
            result = futures_by_worker_id[assignment.worker_id].result()
            worker_reports.append(result.report)
            all_proposals.extend(result.proposals)
            failures.extend(result.failures)
            stage_rows.extend(result.stage_rows)

    recipe_result_rows = _recipe_result_rows_from_proposals(all_proposals)
    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(1 for proposal in all_proposals if proposal.status == "missing_output"),
        "recipe_results": recipe_result_rows,
        "recipe_result_counts": {
            "repaired": sum(
                1
                for row in recipe_result_rows.values()
                if row.get("repair_status") == "repaired"
            ),
            "fragmentary": sum(
                1
                for row in recipe_result_rows.values()
                if row.get("repair_status") == "fragmentary"
            ),
            "not_a_recipe": sum(
                1
                for row in recipe_result_rows.values()
                if row.get("repair_status") == "not_a_recipe"
            ),
        },
    }
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
        "rows": stage_rows,
        "summary": summarize_direct_telemetry_rows(stage_rows),
    }
    _write_json(promotion_report, run_root / artifacts["promotion_report"])
    _write_json(telemetry, run_root / artifacts["telemetry"])
    _write_json(failures, run_root / artifacts["failures"])

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        max_turns_per_shard=1,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(asdict(manifest), run_root / artifacts["phase_manifest"])
    return manifest, worker_reports


def _run_single_correction_recipe_pipeline(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    runner: CodexExecRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmApplyResult:
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    correction_audit_dir = llm_raw_dir / "recipe_correction_audit"
    phase_runtime_dir = llm_raw_dir / "recipe_phase_runtime"
    phase_input_dir = phase_runtime_dir / "inputs"
    for path in (correction_audit_dir, phase_runtime_dir, phase_input_dir):
        path.mkdir(parents=True, exist_ok=True)

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm recipe pipeline: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}
    source_hash = _resolve_source_hash(conversion_result)
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    if not states:
        manifest_path = llm_raw_dir / RECIPE_MANIFEST_FILE_NAME
        manifest = _build_single_correction_manifest(
            run_settings=run_settings,
            llm_raw_dir=llm_raw_dir,
            correction_audit_dir=correction_audit_dir,
            manifest_path=manifest_path,
            states=[],
            process_runs={},
            output_schema_paths={},
            timing_seconds=0.0,
            recipe_shards=[],
            phase_runtime_dir=None,
            phase_runtime_summary={},
        )
        _write_json(manifest, manifest_path)
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={
                "enabled": True,
                "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
                "counts": manifest["counts"],
                "timing": manifest["timing"],
                "process_runs": {},
                "phase_runtime": {},
                "llmRawDir": str(llm_raw_dir),
            },
            llm_raw_dir=llm_raw_dir,
        )

    pipeline_root = _resolve_pipeline_root(run_settings)
    pipeline_assets = _load_pipeline_assets(
        pipeline_root=pipeline_root,
        pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID,
    )
    env = {
        "CODEX_FARM_ROOT": str(pipeline_root),
        _CODEX_FARM_RECIPE_MODE_ENV: run_settings.codex_farm_recipe_mode.value,
    }
    if runner is None:
        raw_runner_cmd = str(run_settings.codex_farm_cmd or "").strip()
        direct_runner_cmd = (
            raw_runner_cmd if Path(raw_runner_cmd).name == "fake-codex-farm.py" else "codex exec"
        )
        codex_runner = SubprocessCodexExecRunner(cmd=direct_runner_cmd)
    else:
        codex_runner = runner
    output_schema_paths: dict[str, str] = {}
    resolved_output_schema_path = Path(pipeline_assets["output_schema_path"])
    output_schema_paths["recipe_correction"] = str(resolved_output_schema_path)
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )

    correction_inputs_by_recipe_id: dict[str, MergedRecipeRepairInput] = {}
    prepared_inputs: list[_PreparedRecipeInput] = []
    for state in states:
        included_blocks = _build_blocks_for_recipe_state(
            state=state,
            full_blocks_by_index=full_blocks_by_index,
        )
        if not included_blocks:
            state.single_correction_status = "error"
            state.final_assembly_status = "error"
            state.errors.append("recipe span has no authoritative blocks.")
            continue
        prepared_input = _build_prepared_recipe_input(
            state=state,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            included_blocks=included_blocks,
        )
        correction_inputs_by_recipe_id[state.recipe_id] = prepared_input.correction_input
        prepared_inputs.append(prepared_input)

    recipe_shards = _build_recipe_shard_plans(
        prepared_inputs=prepared_inputs,
        run_settings=run_settings,
    )
    for recipe_shard in recipe_shards:
        payload = serialize_recipe_correction_shard_input(recipe_shard.shard_input)
        (phase_input_dir / f"{recipe_shard.shard_id}.json").write_text(
            _serialize_compact_prompt_json(payload),
            encoding="utf-8",
        )
    process_runs: dict[str, dict[str, Any]] = {}
    correction_started = time.perf_counter()
    phase_runtime_summary: dict[str, Any] = {}
    if recipe_shards:
        phase_manifest, worker_reports = _run_direct_recipe_workers_v1(
            phase_key="recipe_llm_correct_and_link",
            pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID,
            run_root=phase_runtime_dir,
            shards=[
                ShardManifestEntryV1(
                    shard_id=plan.shard_id,
                    owned_ids=tuple(state.recipe_id for state in plan.states),
                    evidence_refs=plan.evidence_refs,
                    input_payload=serialize_recipe_correction_shard_input(plan.shard_input),
                    metadata={
                        "recipe_ids": [state.recipe_id for state in plan.states],
                        "bundle_names": [state.bundle_name for state in plan.states],
                        "recipe_count": len(plan.states),
                    },
                )
                for plan in recipe_shards
            ],
            runner=codex_runner,
            worker_count=_recipe_worker_count(
                run_settings,
                shard_count=len(recipe_shards),
            ),
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            output_schema_path=resolved_output_schema_path,
            settings={
                "llm_recipe_pipeline": run_settings.llm_recipe_pipeline.value,
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "recipe_worker_count": run_settings.recipe_worker_count,
                "recipe_prompt_target_count": run_settings.recipe_prompt_target_count,
                "recipe_shard_target_recipes": run_settings.recipe_shard_target_recipes,
            },
            runtime_metadata={
                "workbook_slug": workbook_slug,
                "recipe_phase_input_dir": str(phase_input_dir),
            },
            pipeline_assets=pipeline_assets,
            progress_callback=progress_callback,
        )
        phase_manifest_payload = json.loads(
            (phase_runtime_dir / "phase_manifest.json").read_text(encoding="utf-8")
        )
        promotion_report = json.loads(
            (phase_runtime_dir / "promotion_report.json").read_text(encoding="utf-8")
        )
        telemetry = json.loads(
            (phase_runtime_dir / "telemetry.json").read_text(encoding="utf-8")
        )
        worker_reports_payload = [asdict(report) for report in worker_reports]
        phase_runtime_summary = {
            "worker_count": phase_manifest.worker_count,
            "shard_count": phase_manifest.shard_count,
            "phase_manifest": phase_manifest_payload,
            "promotion_report": promotion_report,
            "telemetry": telemetry,
            "worker_reports": worker_reports_payload,
        }
        process_runs["recipe_correction"] = _aggregate_recipe_phase_process_run(
            phase_manifest=phase_manifest_payload,
            worker_reports=worker_reports_payload,
            promotion_report=promotion_report,
            telemetry=telemetry,
        )
    correction_seconds = time.perf_counter() - correction_started

    updated_result = conversion_result.model_copy(deep=True)
    updated_recipes_by_id: dict[str, RecipeCandidate] = {
        str(recipe.identifier or ""): recipe
        for recipe in updated_result.recipes
    }
    intermediate_overrides: dict[str, dict[str, Any]] = {}
    final_overrides: dict[str, dict[str, Any]] = {}
    explicitly_rejected_recipe_ids: set[str] = set()
    proposals_by_shard_id: dict[str, dict[str, Any]] = {}
    proposals_dir = phase_runtime_dir / "proposals"
    for proposal_path in sorted(proposals_dir.glob("*.json")):
        proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        shard_id = str(proposal_payload.get("shard_id") or proposal_path.stem)
        proposals_by_shard_id[shard_id] = proposal_payload

    for state in states:
        if state.single_correction_status == "error":
            continue
    for shard_plan in recipe_shards:
        proposal_payload = proposals_by_shard_id.get(shard_plan.shard_id)
        if proposal_payload is None:
            for state in shard_plan.states:
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append("missing validated recipe shard proposal.")
            continue

        validation_errors = proposal_payload.get("validation_errors")
        if isinstance(validation_errors, list) and validation_errors:
            for state in shard_plan.states:
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append(
                    "invalid recipe shard proposal: " + ", ".join(str(item) for item in validation_errors)
                )
            continue

        try:
            shard_output = RecipeCorrectionShardOutput.model_validate(
                proposal_payload.get("payload") or {}
            )
        except Exception as exc:  # noqa: BLE001
            for state in shard_plan.states:
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append(f"invalid recipe shard output: {exc}")
            continue

        outputs_by_recipe_id = {
            recipe_output.recipe_id: recipe_output for recipe_output in shard_output.recipes
        }
        for prepared in shard_plan.prepared_inputs:
            state = prepared.state
            correction_output = outputs_by_recipe_id.get(state.recipe_id)
            if correction_output is None:
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append("recipe missing from validated shard output.")
                continue
            state.correction_output_status = correction_output.repair_status
            state.correction_output_reason = correction_output.status_reason
            state.warnings.extend(list(correction_output.warnings))

            if correction_output.repair_status != "repaired":
                explicitly_rejected_recipe_ids.add(state.recipe_id)
                state.single_correction_status = "ok"
                state.final_assembly_status = "skipped"
                _write_json(
                    _build_recipe_correction_audit(
                        state=state,
                        correction_input=correction_inputs_by_recipe_id[state.recipe_id],
                        correction_output=correction_output,
                        corrected_candidate=None,
                        final_payload=None,
                        final_assembly_status="skipped",
                        structural_audit=StructuralAuditResult(
                            status="ok",
                            severity="none",
                            reason_codes=[],
                        ),
                        mapping_status=None,
                        mapping_reason=None,
                    ),
                    correction_audit_dir / _recipe_artifact_filename(state.recipe_id),
                )
                continue

            corrected_candidate = _corrected_candidate_from_output(
                state=state,
                output=correction_output,
            )
            final_payload = recipe_candidate_to_draft_v1(
                corrected_candidate,
                ingredient_parser_options=run_settings.to_run_config_dict(),
                instruction_step_options=run_settings.to_run_config_dict(),
                ingredient_step_mapping_override=correction_output.ingredient_step_mapping,
                ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason,
            )
            structural_audit = _classify_recipe_correction_structural_audit(
                correction_output=correction_output,
                draft_payload=final_payload,
            )
            _merge_structural_audit(state=state, audit=structural_audit)
            (
                state.correction_mapping_status,
                state.correction_mapping_reason,
            ) = _classify_recipe_correction_mapping_status(
                draft_payload=final_payload,
                correction_output=correction_output,
                ingredient_step_mapping=correction_output.ingredient_step_mapping,
                ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason,
            )
            if structural_audit.status == "failed":
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append(
                    "recipe correction output rejected: "
                    + "; ".join(structural_audit.reason_codes)
                )
                _write_json(
                    _build_recipe_correction_audit(
                        state=state,
                        correction_input=correction_inputs_by_recipe_id[state.recipe_id],
                        correction_output=correction_output,
                        corrected_candidate=corrected_candidate,
                        final_payload=final_payload,
                        final_assembly_status="error",
                        structural_audit=structural_audit,
                        mapping_status=state.correction_mapping_status,
                        mapping_reason=state.correction_mapping_reason,
                    ),
                    correction_audit_dir / _recipe_artifact_filename(state.recipe_id),
                )
                continue
            try:
                draft_model = RecipeDraftV1.model_validate(final_payload)
            except Exception as exc:  # noqa: BLE001
                state.single_correction_status = "error"
                state.final_assembly_status = "error"
                state.errors.append(
                    f"deterministic final assembly validation failed: {exc}"
                )
                _write_json(
                    _build_recipe_correction_audit(
                        state=state,
                        correction_input=correction_inputs_by_recipe_id[state.recipe_id],
                        correction_output=correction_output,
                        corrected_candidate=corrected_candidate,
                        final_payload=final_payload,
                        final_assembly_status="error",
                        structural_audit=structural_audit,
                        mapping_status=state.correction_mapping_status,
                        mapping_reason=state.correction_mapping_reason,
                    ),
                    correction_audit_dir / _recipe_artifact_filename(state.recipe_id),
                )
                continue

            state.single_correction_status = "ok"
            state.final_assembly_status = "ok"
            _write_json(
                _build_recipe_correction_audit(
                    state=state,
                    correction_input=correction_inputs_by_recipe_id[state.recipe_id],
                    correction_output=correction_output,
                    corrected_candidate=corrected_candidate,
                    final_payload=final_payload,
                    final_assembly_status="ok",
                    structural_audit=structural_audit,
                    mapping_status=state.correction_mapping_status,
                    mapping_reason=state.correction_mapping_reason,
                ),
                correction_audit_dir / _recipe_artifact_filename(state.recipe_id),
            )
            intermediate_overrides[state.recipe_id] = corrected_candidate.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            final_overrides[state.recipe_id] = draft_model.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            updated_recipes_by_id[state.recipe_id] = corrected_candidate

    updated_result.recipes = [
        updated_recipes_by_id.get(str(recipe.identifier or ""), recipe)
        for recipe in updated_result.recipes
        if str(recipe.identifier or "") not in explicitly_rejected_recipe_ids
    ]
    manifest_path = llm_raw_dir / RECIPE_MANIFEST_FILE_NAME
    manifest = _build_single_correction_manifest(
        run_settings=run_settings,
        llm_raw_dir=llm_raw_dir,
        correction_audit_dir=correction_audit_dir,
        manifest_path=manifest_path,
        states=states,
        process_runs=process_runs,
        output_schema_paths=output_schema_paths,
        timing_seconds=correction_seconds,
        recipe_shards=recipe_shards,
        phase_runtime_dir=phase_runtime_dir if recipe_shards else None,
        phase_runtime_summary=phase_runtime_summary,
    )
    _write_json(manifest, manifest_path)
    return CodexFarmApplyResult(
        updated_conversion_result=updated_result,
        intermediate_overrides_by_recipe_id=intermediate_overrides,
        final_overrides_by_recipe_id=final_overrides,
        llm_report={
            "enabled": True,
            "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
            "counts": manifest["counts"],
            "timing": manifest["timing"],
            "process_runs": manifest["process_runs"],
            "output_schema_paths": dict(output_schema_paths),
            "phase_runtime": dict(phase_runtime_summary),
            "llmRawDir": str(llm_raw_dir),
        },
        llm_raw_dir=llm_raw_dir,
    )


def _build_single_correction_execution_plan(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    workbook_slug: str,
) -> dict[str, Any]:
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    requested_shard_count = resolve_shard_count(
        total_items=len(states),
        prompt_target_count=run_settings.recipe_prompt_target_count,
        items_per_shard=run_settings.recipe_shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    planned_tasks: list[dict[str, Any]] = []
    planned_shards: list[dict[str, Any]] = []
    shard_ids_by_recipe_id: dict[str, str] = {}
    for shard_states in partition_contiguous_items(
        states,
        shard_count=requested_shard_count,
    ):
        if not shard_states:
            continue
        shard_id = (
            f"recipe-shard-{len(planned_shards):04d}-"
            f"r{_recipe_index_from_bundle_name(shard_states[0].bundle_name):04d}-"
            f"r{_recipe_index_from_bundle_name(shard_states[-1].bundle_name):04d}"
        )
        recipe_ids = [state.recipe_id for state in shard_states]
        for recipe_id in recipe_ids:
            shard_ids_by_recipe_id[recipe_id] = shard_id
        planned_shards.append(
            {
                "shard_id": shard_id,
                "recipe_ids": recipe_ids,
                "recipe_count": len(recipe_ids),
            }
        )

    for recipe_index, state in enumerate(states):
        planned_tasks.append(
            {
                "recipe_id": state.recipe_id,
                "recipe_index": recipe_index,
                "bundle_name": state.bundle_name,
                "shard_id": shard_ids_by_recipe_id.get(state.recipe_id),
                "planned_stages": [
                    {"stage_key": "build_intermediate_det", "kind": "deterministic"},
                    {
                        "stage_key": "recipe_llm_correct_and_link",
                        "kind": "llm",
                        "pipeline_id": SINGLE_CORRECTION_STAGE_PIPELINE_ID,
                    },
                    {"stage_key": "build_final_recipe", "kind": "deterministic"},
                ],
            }
        )
    return {
        "enabled": True,
        "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
        "recipe_count": len(states),
        "recipe_prompt_target_count": run_settings.recipe_prompt_target_count,
        "recipe_shard_target_recipes": _shard_target_recipe_count(run_settings),
        "worker_count": _recipe_worker_count(
            run_settings,
            shard_count=len(planned_shards),
        ),
        "planned_shards": planned_shards,
        "pipelines": {"recipe_correction": SINGLE_CORRECTION_STAGE_PIPELINE_ID},
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": _effort_override_value(
            run_settings.codex_farm_reasoning_effort
        ),
        "planned_tasks": planned_tasks,
    }


def run_codex_farm_recipe_pipeline(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    runner: CodexExecRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmApplyResult:
    if run_settings.llm_recipe_pipeline.value == "off":
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug),
        )
    return _run_single_correction_recipe_pipeline(
        conversion_result=conversion_result,
        run_settings=run_settings,
        run_root=run_root,
        workbook_slug=workbook_slug,
        runner=runner,
        full_blocks=full_blocks,
        progress_callback=progress_callback,
    )

def build_codex_farm_recipe_execution_plan(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    workbook_slug: str,
    full_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if run_settings.llm_recipe_pipeline.value == "off":
        return {
            "enabled": False,
            "pipeline": "off",
            "recipe_count": len(conversion_result.recipes),
            "planned_tasks": [],
        }
    return _build_single_correction_execution_plan(
        conversion_result=conversion_result,
        run_settings=run_settings,
        workbook_slug=workbook_slug,
    )


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


_STRUCTURAL_STATUS_PRECEDENCE = {"ok": 0, "degraded": 1, "failed": 2}


def _merge_structural_audit(
    *,
    state: _RecipeState,
    audit: StructuralAuditResult,
) -> None:
    for reason_code in audit.reason_codes:
        if reason_code not in state.structural_reason_codes:
            state.structural_reason_codes.append(reason_code)
    current_rank = _STRUCTURAL_STATUS_PRECEDENCE.get(state.structural_status, 0)
    new_rank = _STRUCTURAL_STATUS_PRECEDENCE.get(audit.status, 0)
    if new_rank > current_rank:
        state.structural_status = audit.status


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root



def _non_empty(value: Any, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recipe_location(recipe: RecipeCandidate) -> dict[str, Any]:
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    location = provenance.get("location")
    if not isinstance(location, dict):
        location = {}
        provenance["location"] = location
        recipe.provenance = provenance
    return location


def _build_states(
    result: ConversionResult,
    *,
    workbook_slug: str,
) -> list[_RecipeState]:
    states: list[_RecipeState] = []
    for index, recipe in enumerate(result.recipes):
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        recipe_id = ensure_recipe_id(
            recipe.identifier or provenance.get("@id") or provenance.get("id"),
            workbook_slug=workbook_slug,
            recipe_index=index,
        )
        recipe.identifier = recipe_id
        if not isinstance(recipe.provenance, dict):
            recipe.provenance = {}
        recipe.provenance["@id"] = recipe_id
        if "id" in recipe.provenance:
            recipe.provenance["id"] = recipe_id
        location = _recipe_location(recipe)
        start_raw = (
            location.get("start_block")
            if "start_block" in location
            else location.get("startBlock")
        )
        end_raw = (
            location.get("end_block")
            if "end_block" in location
            else location.get("endBlock")
        )
        heuristic_start = _coerce_int(start_raw)
        heuristic_end = _coerce_int(end_raw)
        states.append(
            _RecipeState(
                recipe=recipe,
                recipe_id=recipe_id,
                bundle_name=bundle_filename(recipe_id, recipe_index=index),
                heuristic_start=heuristic_start,
                heuristic_end=heuristic_end,
            )
        )
    return states


def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    artifacts = sorted(
        result.raw_artifacts,
        key=lambda item: 0 if str(item.location_id) == "full_text" else 1,
    )
    for artifact in artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if isinstance(blocks, list) and blocks:
            candidate_rows: list[Any] = blocks
        elif str(artifact.location_id) == "full_text":
            # Older cached prediction payloads may persist line rows without
            # `full_text.blocks`; synthesize minimal blocks from line indices.
            lines = content.get("lines")
            candidate_rows = lines if isinstance(lines, list) else []
        else:
            candidate_rows = []
        for raw_block in candidate_rows:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            payload = dict(raw_block)
            payload["index"] = index
            payload["text"] = str(payload.get("text") or "")
            by_index[index] = payload
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared



def _normalize_mapping_reason_token(value: str | None) -> str:
    rendered = str(value or "").strip().lower()
    rendered = re.sub(r"[^a-z0-9]+", "_", rendered)
    return rendered.strip("_")


def _classify_recipe_correction_mapping_status(
    *,
    draft_payload: dict[str, Any],
    correction_output: MergedRecipeRepairOutput,
    ingredient_step_mapping: dict[str, Any] | None,
    ingredient_step_mapping_reason: str | None,
) -> tuple[str, str | None]:
    mapping_payload = (
        ingredient_step_mapping if isinstance(ingredient_step_mapping, dict) else {}
    )
    rendered_reason = str(ingredient_step_mapping_reason or "").strip() or None
    if mapping_payload:
        return "mapped", rendered_reason
    if rendered_reason:
        normalized_reason = _normalize_mapping_reason_token(rendered_reason)
        if any(
            token in normalized_reason
            for token in (
                "not_needed",
                "not_applicable",
                "single_step",
                "single_ingredient",
                "single_action",
                "already_ordered",
            )
        ):
            return "not_needed", rendered_reason
        return "unclear", rendered_reason

    ingredient_count = sum(
        1 for item in correction_output.canonical_recipe.ingredients if str(item).strip()
    )
    steps_payload = draft_payload.get("steps")
    step_count = (
        sum(
            1
            for step in steps_payload
            if isinstance(step, dict) and str(step.get("instruction") or "").strip()
        )
        if isinstance(steps_payload, list)
        else 0
    )
    if ingredient_count >= 2 and step_count >= 2:
        return "missing_reason", None
    return "not_needed_implicit", None


def _classify_recipe_correction_structural_audit(
    *,
    correction_output: MergedRecipeRepairOutput,
    draft_payload: dict[str, Any],
) -> StructuralAuditResult:
    reason_codes: list[str] = []
    title = str(correction_output.canonical_recipe.title or "").strip()
    if _is_placeholder_recipe_title(title):
        reason_codes.append("placeholder_title")

    steps_payload = draft_payload.get("steps")
    if not isinstance(steps_payload, list):
        reason_codes.append("missing_steps")
        return _build_structural_audit(reason_codes)

    rendered_steps: list[str] = []
    for step in steps_payload:
        if not isinstance(step, dict):
            continue
        instruction = str(step.get("instruction") or "").strip()
        if instruction:
            rendered_steps.append(instruction)
    if not rendered_steps:
        reason_codes.append("missing_steps")
    elif all(_is_placeholder_instruction(step) for step in rendered_steps):
        reason_codes.append("placeholder_steps_only")

    blocked_description = _normalize_audit_text(
        str(correction_output.canonical_recipe.description or "")
    )
    extracted_instruction_set = {
        _normalize_audit_text(str(item))
        for item in correction_output.canonical_recipe.steps
        if _normalize_audit_text(str(item))
    }
    if len(blocked_description) >= 20:
        for step in rendered_steps:
            normalized_step = _normalize_audit_text(step)
            if (
                normalized_step
                and normalized_step not in extracted_instruction_set
                and (
                    blocked_description == normalized_step
                    or blocked_description in normalized_step
                    or normalized_step in blocked_description
                )
            ):
                reason_codes.append("step_matches_schema_description")
                break

    mapping_payload = correction_output.ingredient_step_mapping
    rendered_mapping_reason = str(
        correction_output.ingredient_step_mapping_reason or ""
    ).strip()
    nonempty_ingredients = [
        str(item).strip()
        for item in correction_output.canonical_recipe.ingredients
        if str(item).strip()
    ]
    if (
        not mapping_payload
        and not rendered_mapping_reason
        and len(nonempty_ingredients) >= 2
        and len(rendered_steps) >= 2
    ):
        reason_codes.append("empty_mapping_without_reason")

    return _build_structural_audit(reason_codes)


def _build_structural_audit(reason_codes: list[str]) -> StructuralAuditResult:
    normalized = _unique_reason_codes(reason_codes)
    if not normalized:
        return StructuralAuditResult(status="ok", severity="none", reason_codes=[])
    return StructuralAuditResult(
        status="failed",
        severity="hard",
        reason_codes=normalized,
    )


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


def _normalize_audit_text(value: str) -> str:
    rendered = str(value or "").strip().lower()
    rendered = re.sub(r"[^a-z0-9]+", " ", rendered)
    return re.sub(r"\s+", " ", rendered).strip()


def _is_placeholder_instruction(value: str) -> bool:
    return _normalize_audit_text(value) in _AUDIT_PLACEHOLDER_STEP_TEXTS


def _is_placeholder_recipe_title(value: str) -> bool:
    return _normalize_audit_text(value) in _AUDIT_PLACEHOLDER_TITLES
