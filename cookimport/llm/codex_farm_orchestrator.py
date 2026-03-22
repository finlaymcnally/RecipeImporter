from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
    classify_workspace_worker_command,
    detect_workspace_worker_boundary_violation,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)
from .phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    TaskManifestEntryV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from .recipe_workspace_tools import render_recipe_worker_cli_script
from .recipe_tagging_guide import build_recipe_tagging_guide
from .shard_prompt_targets import partition_contiguous_items, resolve_shard_count
from .worker_hint_sidecars import preview_text, write_worker_hint_markdown

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
_DEFAULT_RECIPE_SHARD_TARGET_RECIPES = 1
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
    pre_context_rows: tuple[tuple[int, str], ...]
    post_context_rows: tuple[tuple[int, str], ...]


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


@dataclass(frozen=True)
class _RecipeTaskPlan:
    task_id: str
    parent_shard_id: str
    manifest_entry: ShardManifestEntryV1

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


def _build_recipe_boundary_context_rows(
    *,
    state: _RecipeState,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    side: str,
    limit: int = 2,
) -> tuple[tuple[int, str], ...]:
    start = _coerce_int(state.heuristic_start)
    end = _coerce_int(state.heuristic_end)
    if start is None or end is None:
        return ()
    normalized_limit = max(0, int(limit))
    if normalized_limit <= 0:
        return ()
    if side == "before":
        indices = range(start - normalized_limit, start)
    else:
        indices = range(end + 1, end + normalized_limit + 1)
    rows: list[tuple[int, str]] = []
    for block_index in indices:
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        rows.append((int(block_index), str(block.get("text") or "").strip()))
    return tuple(rows)


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
    canonical_text = "\n".join(
        str(block.get("text") or "").strip() for block in included_blocks
    ).strip()
    return MergedRecipeRepairInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        canonical_text=canonical_text,
        evidence_rows=[
            (int(block.get("index", 0)), str(block.get("text") or "").strip())
            for block in included_blocks
        ],
        recipe_candidate_hint=compact_recipe_candidate_hint,
        tagging_guide=build_recipe_tagging_guide(
            recipe_text=canonical_text,
            recipe_candidate_hint=compact_recipe_candidate_hint,
        ),
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
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
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
    pre_context_rows = _build_recipe_boundary_context_rows(
        state=state,
        full_blocks_by_index=full_blocks_by_index,
        side="before",
    )
    post_context_rows = _build_recipe_boundary_context_rows(
        state=state,
        full_blocks_by_index=full_blocks_by_index,
        side="after",
    )
    return _PreparedRecipeInput(
        state=state,
        correction_input=correction_input,
        candidate_quality_hint=candidate_quality_hint,
        evidence_refs=evidence_refs,
        block_indices=block_indices,
        pre_context_rows=pre_context_rows,
        post_context_rows=post_context_rows,
    )


def _shard_target_recipe_count(run_settings: RunSettings) -> int:
    if run_settings.recipe_shard_target_recipes is None:
        return 1
    try:
        value = int(
            run_settings.recipe_shard_target_recipes
            or _DEFAULT_RECIPE_SHARD_TARGET_RECIPES
        )
    except (TypeError, ValueError):
        value = _DEFAULT_RECIPE_SHARD_TARGET_RECIPES
    return max(1, value)


def _requested_recipe_worker_count(run_settings: RunSettings) -> int | None:
    candidate = run_settings.recipe_worker_count
    if candidate is None:
        candidate = run_settings.recipe_prompt_target_count
    if candidate is None:
        return None
    try:
        value = int(candidate)
    except (TypeError, ValueError):
        return None
    return max(1, value)


def _recipe_worker_count(
    run_settings: RunSettings,
    *,
    shard_count: int,
) -> int:
    return resolve_phase_worker_count(
        requested_worker_count=_requested_recipe_worker_count(run_settings),
        shard_count=shard_count,
    )


def _build_recipe_shard_plan(
    *,
    shard_index: int,
    shard_prepared_inputs: Sequence[_PreparedRecipeInput],
) -> _RecipeShardPlan | None:
    shard_prepared_inputs_tuple = tuple(shard_prepared_inputs)
    if not shard_prepared_inputs_tuple:
        return None
    first_state = shard_prepared_inputs_tuple[0].state
    last_state = shard_prepared_inputs_tuple[-1].state
    first_recipe_index = _recipe_index_from_bundle_name(first_state.bundle_name)
    last_recipe_index = _recipe_index_from_bundle_name(last_state.bundle_name)
    shard_id = (
        f"recipe-shard-{shard_index:04d}-"
        f"r{first_recipe_index:04d}-r{last_recipe_index:04d}"
    )
    shard_recipe_ids = tuple(
        prepared.state.recipe_id for prepared in shard_prepared_inputs_tuple
    )
    tagging_guide = (
        dict(shard_prepared_inputs_tuple[0].correction_input.tagging_guide or {})
        if len(shard_prepared_inputs_tuple) == 1
        else build_recipe_tagging_guide()
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
            for prepared in shard_prepared_inputs_tuple
        ],
        tagging_guide=tagging_guide,
    )
    evidence_refs = tuple(
        ref
        for prepared in shard_prepared_inputs_tuple
        for ref in prepared.evidence_refs
    )
    return _RecipeShardPlan(
        shard_id=shard_id,
        states=tuple(prepared.state for prepared in shard_prepared_inputs_tuple),
        prepared_inputs=shard_prepared_inputs_tuple,
        evidence_refs=evidence_refs,
        shard_input=shard_input,
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
        default_items_per_shard=1,
    )
    plans: list[_RecipeShardPlan] = []
    for shard_index, shard_prepared_inputs_list in enumerate(
        partition_contiguous_items(
            prepared_inputs,
            shard_count=requested_shard_count,
        )
    ):
        plan = _build_recipe_shard_plan(
            shard_index=shard_index,
            shard_prepared_inputs=shard_prepared_inputs_list,
        )
        if plan is not None:
            plans.append(plan)
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
    for tag in [entry.label for entry in output.selected_tags]:
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


_RECIPE_COMPACT_TOP_LEVEL_KEYS = frozenset({"v", "sid", "r"})
_RECIPE_COMPACT_RESULT_KEYS = frozenset({"v", "rid", "st", "sr", "cr", "m", "mr", "g", "w"})
_RECIPE_COMPACT_CANONICAL_KEYS = frozenset({"t", "i", "s", "d", "y"})
_RECIPE_COMPACT_MAPPING_KEYS = frozenset({"i", "s"})
_RECIPE_COMPACT_TAG_KEYS = frozenset({"c", "l", "f"})
_RECIPE_LEGACY_KEY_SUGGESTIONS = {
    "bundle_version": "v",
    "shard_id": "sid",
    "results": "r",
    "recipes": "r",
    "recipe_id": "rid",
    "repair_status": "st",
    "status_reason": "sr",
    "canonical_recipe": "cr",
    "ingredient_step_mapping": "m",
    "ingredient_step_mapping_reason": "mr",
    "selected_tags": "g",
    "warnings": "w",
    "not_a_recipe": "st=not_a_recipe",
    "fragmentary": "st=fragmentary",
    "notes": "sr or w",
    "title": "cr.t",
    "ingredients": "cr.i",
    "steps": "cr.s",
    "description": "cr.d",
    "recipeYield": "cr.y",
    "recipe_yield": "cr.y",
    "category": "c",
    "label": "l",
    "confidence": "f",
}


def _recipe_compact_contract_error(*, path: str, key: str) -> str:
    suggestion = _RECIPE_LEGACY_KEY_SUGGESTIONS.get(key)
    if suggestion:
        return (
            f"invalid_shard_output:{path} legacy key `{key}` is invalid for recipe "
            f"workspace output; use `{suggestion}`"
        )
    return f"invalid_shard_output:{path} unexpected key `{key}` is not permitted"


def _validate_recipe_compact_output_keys(payload: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    for key in sorted(str(name) for name in payload.keys() if str(name) not in _RECIPE_COMPACT_TOP_LEVEL_KEYS):
        errors.append(_recipe_compact_contract_error(path="root", key=key))
    rows = payload.get("r")
    if isinstance(rows, list):
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            row_path = f"r[{row_index}]"
            for key in sorted(
                str(name) for name in row.keys() if str(name) not in _RECIPE_COMPACT_RESULT_KEYS
            ):
                errors.append(_recipe_compact_contract_error(path=row_path, key=key))
            canonical_recipe = row.get("cr")
            if isinstance(canonical_recipe, Mapping):
                canonical_path = f"{row_path}.cr"
                for key in sorted(
                    str(name)
                    for name in canonical_recipe.keys()
                    if str(name) not in _RECIPE_COMPACT_CANONICAL_KEYS
                ):
                    errors.append(_recipe_compact_contract_error(path=canonical_path, key=key))
            mapping_rows = row.get("m")
            if isinstance(mapping_rows, list):
                for mapping_index, mapping_row in enumerate(mapping_rows):
                    if not isinstance(mapping_row, Mapping):
                        continue
                    mapping_path = f"{row_path}.m[{mapping_index}]"
                    for key in sorted(
                        str(name)
                        for name in mapping_row.keys()
                        if str(name) not in _RECIPE_COMPACT_MAPPING_KEYS
                    ):
                        errors.append(_recipe_compact_contract_error(path=mapping_path, key=key))
            tag_rows = row.get("g")
            if isinstance(tag_rows, list):
                for tag_index, tag_row in enumerate(tag_rows):
                    if not isinstance(tag_row, Mapping):
                        continue
                    tag_path = f"{row_path}.g[{tag_index}]"
                    for key in sorted(
                        str(name)
                        for name in tag_row.keys()
                        if str(name) not in _RECIPE_COMPACT_TAG_KEYS
                    ):
                        errors.append(_recipe_compact_contract_error(path=tag_path, key=key))
    return tuple(errors)


def _validate_recipe_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, Sequence[str], Mapping[str, Any] | None]:
    compact_contract_errors = _validate_recipe_compact_output_keys(payload)
    if compact_contract_errors:
        return False, compact_contract_errors, {
            "contract": "recipe.correction.compact.v1",
            "contract_errors": list(compact_contract_errors),
        }
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
    else:
        payload = None
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
    live_status_path: Path | None = None,
    live_status_paths: Sequence[Path] | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    stage_label: str = "strict JSON stage",
    allow_workspace_commands: bool = False,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_verdict = classify_workspace_worker_command(snapshot.last_command)
        last_command_boundary_violation = detect_workspace_worker_boundary_violation(
            snapshot.last_command,
        )
        if snapshot.command_execution_count > 0:
            if allow_workspace_commands:
                if last_command_boundary_violation is None:
                    command_execution_tolerated = True
                else:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label=stage_label,
                            last_command=snapshot.last_command,
                        ),
                        retryable=False,
                    )
                if decision is None and should_terminate_workspace_command_loop(snapshot=snapshot):
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_loop_without_output",
                        reason_detail=format_watchdog_command_loop_reason_detail(
                            stage_label=stage_label,
                            snapshot=snapshot,
                        ),
                        retryable=False,
                    )
            else:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_command_execution_forbidden",
                    reason_detail=format_watchdog_command_reason_detail(
                        stage_label=stage_label,
                        last_command=snapshot.last_command,
                    ),
                    retryable=False,
                )
        elif snapshot.reasoning_item_count >= 2 and not snapshot.has_final_agent_message:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_reasoning_without_output",
                reason_detail=f"{stage_label} emitted repeated reasoning without a final answer",
                retryable=False,
            )
        status_payload = {
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
            "command_execution_tolerated": command_execution_tolerated,
            "last_command_policy": last_command_verdict.policy,
            "last_command_policy_allowed": last_command_verdict.allowed,
            "last_command_policy_reason": last_command_verdict.reason,
            "last_command_boundary_violation_detected": (
                last_command_boundary_violation is not None
            ),
            "last_command_boundary_policy": (
                last_command_boundary_violation.policy
                if last_command_boundary_violation is not None
                else None
            ),
            "last_command_boundary_reason": (
                last_command_boundary_violation.reason
                if last_command_boundary_violation is not None
                else None
            ),
            "reasoning_item_count": snapshot.reasoning_item_count,
            "last_command": snapshot.last_command,
            "last_command_repeat_count": snapshot.last_command_repeat_count,
            "has_final_agent_message": snapshot.has_final_agent_message,
            "timeout_seconds": snapshot.timeout_seconds,
            "watchdog_policy": watchdog_policy,
            "shard_id": shard_id,
            "reason_code": decision.reason_code if decision is not None else None,
            "reason_detail": decision.reason_detail if decision is not None else None,
            "retryable": decision.retryable if decision is not None else False,
        }
        for path in target_paths:
            _write_live_status(path, status_payload)
        return decision

    return _callback


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
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
            "watchdog_policy": watchdog_policy,
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
        "- The first emitted character must be `{`.\n"
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


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _build_recipe_workspace_worker_prompt(
    *,
    tasks: Sequence[TaskManifestEntryV1],
) -> str:
    task_ids = [str(task.task_id).strip() for task in tasks if str(task.task_id).strip()]
    lines = [
        "You are a recipe correction worker in a bounded local workspace.",
        "",
        "Process the assigned shard files locally. The current working directory is already the workspace root.",
        "Do not inspect the repository or explore beyond this workspace.",
        "",
        "Required local loop:",
        "1. Open `worker_manifest.json`, then `current_task.json`, then `OUTPUT_CONTRACT.md`.",
        "2. If you need queue context, run `python3 tools/recipe_worker.py overview` or `python3 tools/recipe_worker.py show <task_id>` instead of dumping whole manifests by hand.",
        "3. For the current task, open `hints/<task_id>.md` first, then `in/<task_id>.json`.",
        "4. The cheapest paved road is batch-first: run `python3 tools/recipe_worker.py prepare-all --dest-dir scratch/` once, edit the needed `scratch/<task_id>.json` drafts, then run `python3 tools/recipe_worker.py finalize-all scratch/` once.",
        "5. Single-task fallback is still available: `python3 tools/recipe_worker.py show <task_id>`, then `check scratch/<task_id>.json`, then `finalize scratch/<task_id>.json`.",
        "6. Continue through the remaining `assigned_tasks.json` rows in order until every assigned task has an output file or you cannot proceed.",
        "7. Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local or in approved temp roots, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.",
        "",
        "Output contract for each `out/<task_id>.json`:",
        "- Write exactly one JSON object.",
        "- Copy the compact shape from `OUTPUT_CONTRACT.md` and `examples/*.json`.",
        "- Use compact keys only: top-level `v`, `sid`, `r`; per-recipe `v`, `rid`, `st`, `sr`, `cr`, `m`, `mr`, `g`, `w`.",
        "- `sid` must equal the task id exactly.",
        "- Return exactly one recipe result for each owned recipe id in the task input and no extras.",
        "- Legacy keys are invalid here, including `results`, `recipes`, `recipe_id`, `repair_status`, `canonical_recipe`, `not_a_recipe`, `fragmentary`, and `notes`.",
        "- Treat `hints/<task_id>.md` as guidance and `in/<task_id>.json` as the authoritative owned input.",
        "- Large batch heredocs are unnecessary here because `tools/recipe_worker.py finalize` and `finalize-all` are the approved write paths.",
        "",
        "Your final message is optional telemetry only. Do not paste shard outputs there. The authoritative result is the set of valid files written under `out/`.",
    ]
    if task_ids:
        lines.extend(
            [
                "",
                "Assigned task ids:",
                *[f"- {task_id}" for task_id in task_ids],
            ]
        )
    return "\n".join(lines)


def _write_recipe_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
) -> None:
    payload = _coerce_dict(shard.input_payload)
    recipes = [row for row in (payload.get("r") or []) if isinstance(row, Mapping)]
    hint_rows = [
        row
        for row in (_coerce_dict(shard.metadata).get("worker_hint_recipes") or [])
        if isinstance(row, Mapping)
    ]
    recipes_by_id = {
        str(row.get("rid") or "").strip(): row
        for row in recipes
        if str(row.get("rid") or "").strip()
    }
    recipe_lines: list[str] = []
    for hint_row in hint_rows[:12]:
        recipe_id = str(hint_row.get("recipe_id") or "").strip() or "[unknown recipe]"
        input_row = recipes_by_id.get(recipe_id, {})
        title_hint = str(hint_row.get("title_hint") or "").strip() or str(_coerce_dict(input_row.get("h")).get("n") or "").strip() or "[no title hint]"
        flags = [str(flag).strip() for flag in (hint_row.get("quality_flags") or []) if str(flag).strip()]
        pre_context_rows = [
            f"{int(row.get('index', 0))}:{preview_text(row.get('text'), max_chars=60)}"
            for row in (hint_row.get("pre_context_rows") or [])[:2]
            if isinstance(row, Mapping)
        ]
        post_context_rows = [
            f"{int(row.get('index', 0))}:{preview_text(row.get('text'), max_chars=60)}"
            for row in (hint_row.get("post_context_rows") or [])[:2]
            if isinstance(row, Mapping)
        ]
        recipe_lines.append(
            f"`{recipe_id}` title hint `{preview_text(title_hint, max_chars=80)}` | evidence rows {int(hint_row.get('source_evidence_row_count') or 0)} | source ingredient-like {int(hint_row.get('source_ingredient_like_count') or 0)} | source instruction-like {int(hint_row.get('source_instruction_like_count') or 0)} | hint ingredients {int(hint_row.get('hint_ingredient_count') or 0)} | hint steps {int(hint_row.get('hint_step_count') or 0)} | flags `{', '.join(flags) or 'none'}` | before `{'; '.join(pre_context_rows) or 'none'}` | after `{'; '.join(post_context_rows) or 'none'}`"
        )
    write_worker_hint_markdown(
        path,
        title=f"Recipe correction hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only.",
            "Open this file first, then open the authoritative `in/<shard_id>.json` file.",
            "Choose `st=repaired` only when you can restate a real recipe. Choose `st=fragmentary` when recipe evidence exists but is too incomplete to normalize safely. Choose `st=not_a_recipe` when the owned text is not a recipe at all.",
            "When `st=repaired`, `cr` must be a complete canonical recipe object. When `st` is `fragmentary` or `not_a_recipe`, set `cr` to null and explain the judgment briefly in `sr`.",
            f"Owned recipe candidates in this shard: {len(recipes)}.",
        ],
        sections=[
            (
                "How to use this packet",
                [
                    "Treat immediate before/after context as a boundary clue only. The authoritative owned source rows still live in `in/<shard_id>.json`.",
                    "Do not force a repaired recipe when the source is better described as fragmentary or not_a_recipe.",
                    "Use tags only when they are obvious from the source text, and keep `g` empty otherwise.",
                    "Keep `m` and `mr` honest. If there is no meaningful ingredient-step mapping, leave `m` empty and say why in `mr`.",
                ],
            ),
            ("Recipe candidate summaries", recipe_lines or ["No recipe summaries available."]),
        ],
    )


def _build_recipe_workspace_contract_examples(
    *,
    tasks: Sequence[_RecipeTaskPlan],
) -> dict[str, dict[str, Any]]:
    sample_task = tasks[0] if tasks else None
    sample_task_id = "recipe-task-example"
    sample_recipe_id = "recipe-id-example"
    sample_title = "Example Recipe"
    sample_ingredients = ["1 example ingredient"]
    sample_steps = ["Do the example step."]
    if sample_task is not None:
        payload = _coerce_dict(sample_task.manifest_entry.input_payload)
        sample_task_id = str(sample_task.task_id or sample_task_id)
        recipe_rows = [row for row in (payload.get("r") or []) if isinstance(row, Mapping)]
        if recipe_rows:
            recipe_row = dict(recipe_rows[0])
            sample_recipe_id = str(recipe_row.get("rid") or sample_recipe_id)
            hint_payload = _coerce_dict(recipe_row.get("h"))
            sample_title = str(hint_payload.get("n") or sample_title)
            sample_ingredients = [
                str(item).strip()
                for item in (hint_payload.get("i") or [])
                if str(item).strip()
            ] or sample_ingredients
            sample_steps = [
                str(item).strip()
                for item in (hint_payload.get("s") or [])
                if str(item).strip()
            ] or sample_steps
    return {
        "valid_repaired_task_output.json": {
            "v": "1",
            "sid": sample_task_id,
            "r": [
                {
                    "v": "1",
                    "rid": sample_recipe_id,
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": sample_title,
                        "i": sample_ingredients,
                        "s": sample_steps,
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": "not_needed_single_step",
                    "g": [],
                    "w": [],
                }
            ],
        },
        "valid_fragmentary_task_output.json": {
            "v": "1",
            "sid": sample_task_id,
            "r": [
                {
                    "v": "1",
                    "rid": sample_recipe_id,
                    "st": "fragmentary",
                    "sr": "recipe evidence exists but the owned text is too incomplete to normalize safely",
                    "cr": None,
                    "m": [],
                    "mr": "not_applicable_fragmentary",
                    "g": [],
                    "w": ["incomplete_recipe_source"],
                }
            ],
        },
        "valid_not_a_recipe_task_output.json": {
            "v": "1",
            "sid": sample_task_id,
            "r": [
                {
                    "v": "1",
                    "rid": sample_recipe_id,
                    "st": "not_a_recipe",
                    "sr": "owned text is not a recipe",
                    "cr": None,
                    "m": [],
                    "mr": "not_applicable_not_a_recipe",
                    "g": [],
                    "w": [],
                }
            ],
        },
    }


def _build_recipe_workspace_contract_markdown(
    *,
    examples: Mapping[str, Mapping[str, Any]],
) -> str:
    repaired_example = json.dumps(
        dict(examples.get("valid_repaired_task_output.json") or {}),
        indent=2,
        sort_keys=True,
    )
    fragmentary_example = json.dumps(
        dict(examples.get("valid_fragmentary_task_output.json") or {}),
        indent=2,
        sort_keys=True,
    )
    not_a_recipe_example = json.dumps(
        dict(examples.get("valid_not_a_recipe_task_output.json") or {}),
        indent=2,
        sort_keys=True,
    )
    return "\n".join(
        [
            "# Recipe Workspace Output Contract",
            "",
            "Write one JSON object per task to `out/<task_id>.json`.",
            "",
            "Compact keys only:",
            "- Top level: `v` bundle version, `sid` task id, `r` recipe-result array.",
            "- Per recipe row: `rid` recipe id, `st` status, `sr` short reason, `cr` canonical recipe, `m` ingredient-step mapping, `mr` mapping reason, `g` selected tags, `w` warnings.",
            "- Canonical recipe `cr`: `t` title, `i` ingredients, `s` steps, `d` description, `y` yield.",
            "",
            "Status rules:",
            "- `st=repaired`: `cr` must be a full canonical recipe object.",
            "- `st=fragmentary`: recipe evidence exists but is too incomplete to normalize safely; set `cr` to null and explain why in `sr`.",
            "- `st=not_a_recipe`: the owned text is not a recipe; set `cr` to null and explain briefly in `sr`.",
            "",
            "Hard invariants:",
            "- `sid` must equal the current task id exactly.",
            "- Return exactly one row for each owned `rid` in `in/<task_id>.json` and no extras.",
            "- Copy the shape from the examples, then replace the example ids with the task-local `sid` and `rid` values.",
            "",
            "Forbidden legacy keys:",
            "- Never write `results`, `recipes`, `recipe_id`, `repair_status`, `status_reason`, `canonical_recipe`, `ingredient_step_mapping`, `selected_tags`, `warnings`, `not_a_recipe`, `fragmentary`, or `notes`.",
            "",
            "Valid repaired example:",
            repaired_example,
            "",
            "Valid fragmentary example:",
            fragmentary_example,
            "",
            "Valid not_a_recipe example:",
            not_a_recipe_example,
            "",
            "Machine-readable copies of these examples also live under `examples/`.",
        ]
    ) + "\n"


def _write_recipe_workspace_contract_sidecars(
    *,
    worker_root: Path,
    tasks: Sequence[_RecipeTaskPlan],
) -> None:
    examples = _build_recipe_workspace_contract_examples(tasks=tasks)
    examples_dir = worker_root / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    (worker_root / "OUTPUT_CONTRACT.md").write_text(
        _build_recipe_workspace_contract_markdown(examples=examples),
        encoding="utf-8",
    )
    for filename, payload in examples.items():
        (examples_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _write_recipe_workspace_helper_tools(*, worker_root: Path) -> None:
    tools_dir = worker_root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "recipe_worker.py").write_text(
        render_recipe_worker_cli_script(),
        encoding="utf-8",
    )


def _distribute_recipe_session_value(value: Any, task_count: int) -> list[int]:
    normalized_task_count = max(1, int(task_count))
    total = int(value or 0)
    base, remainder = divmod(total, normalized_task_count)
    return [base + (1 if index < remainder else 0) for index in range(normalized_task_count)]


def _build_recipe_workspace_task_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    runtime_task_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path,
    worker_prompt_path: Path,
    task_count: int,
    task_index: int,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    telemetry = payload.get("telemetry")
    row_payload = None
    if isinstance(telemetry, Mapping):
        rows = telemetry.get("rows")
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            if isinstance(first_row, Mapping):
                row_payload = dict(first_row)
    request_input_file_str = str(request_input_file)
    request_input_file_bytes = (
        request_input_file.stat().st_size if request_input_file.exists() else None
    )
    worker_prompt_file_str = str(worker_prompt_path)
    if row_payload is not None:
        share_fields = (
            "duration_ms",
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "visible_input_tokens",
            "visible_output_tokens",
            "wrapper_overhead_tokens",
        )
        for field_name in share_fields:
            shares = _distribute_recipe_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        row_payload["tokens_total"] = (
            int(row_payload.get("tokens_input") or 0)
            + int(row_payload.get("tokens_cached_input") or 0)
            + int(row_payload.get("tokens_output") or 0)
            + int(row_payload.get("tokens_reasoning") or 0)
        )
        row_payload["prompt_input_mode"] = "workspace_worker"
        row_payload["request_input_file"] = request_input_file_str
        row_payload["request_input_file_bytes"] = request_input_file_bytes
        row_payload["worker_prompt_file"] = worker_prompt_file_str
        row_payload["worker_session_task_count"] = task_count
        row_payload["worker_session_primary_row"] = task_index == 0
        row_payload["runtime_task_id"] = runtime_task_id
        row_payload["runtime_parent_shard_id"] = shard_id
        if task_index > 0:
            row_payload["command_execution_count"] = 0
            row_payload["command_execution_commands"] = []
            row_payload["reasoning_item_count"] = 0
            row_payload["reasoning_item_types"] = []
            row_payload["codex_event_count"] = 0
            row_payload["codex_event_types"] = []
            row_payload["output_preview"] = None
            row_payload["output_preview_chars"] = 0
        telemetry["rows"] = [row_payload]
        telemetry["summary"] = summarize_direct_telemetry_rows([row_payload])
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "workspace_worker",
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "worker_prompt_file": worker_prompt_file_str,
        "runtime_task_id": runtime_task_id,
        "runtime_parent_shard_id": shard_id,
    }
    return payload


def _aggregate_recipe_worker_runner_payload(
    *,
    pipeline_id: str,
    worker_runs: Sequence[Mapping[str, Any]],
    stage_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in stage_rows if isinstance(row, Mapping)]
    uses_workspace_worker = any(
        str(
            ((payload.get("process_payload") or {}) if isinstance(payload, Mapping) else {}).get(
                "prompt_input_mode"
            )
            or ""
        ).strip()
        == "workspace_worker"
        for payload in worker_runs
        if isinstance(payload, Mapping)
    )
    return {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": [dict(payload) for payload in worker_runs],
        "telemetry": {
            "rows": rows,
            "summary": summarize_direct_telemetry_rows(rows),
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": not uses_workspace_worker,
            "tool_affordances_requested": uses_workspace_worker,
        },
    }


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


def _build_recipe_task_plans(
    shard: ShardManifestEntryV1,
) -> tuple[_RecipeTaskPlan, ...]:
    payload = _coerce_dict(shard.input_payload)
    recipes = [dict(row) for row in (payload.get("r") or []) if isinstance(row, Mapping)]
    hint_rows = [
        dict(row)
        for row in (_coerce_dict(shard.metadata).get("worker_hint_recipes") or [])
        if isinstance(row, Mapping)
    ]
    hint_by_recipe_id = {
        str(row.get("recipe_id") or "").strip(): row
        for row in hint_rows
        if str(row.get("recipe_id") or "").strip()
    }
    if not recipes:
        return ()
    task_count = len(recipes)
    task_plans: list[_RecipeTaskPlan] = []
    for task_index, recipe_row in enumerate(recipes, start=1):
        recipe_id = str(recipe_row.get("rid") or "").strip()
        if not recipe_id:
            continue
        task_id = (
            shard.shard_id
            if task_count == 1
            else f"{shard.shard_id}.task-{task_index:03d}"
        )
        task_payload = {
            **payload,
            "sid": task_id,
            "ids": [recipe_id],
            "r": [dict(recipe_row)],
        }
        task_manifest = ShardManifestEntryV1(
            shard_id=task_id,
            owned_ids=(recipe_id,),
            evidence_refs=tuple(shard.evidence_refs),
            input_payload=task_payload,
            metadata={
                **dict(shard.metadata or {}),
                "parent_shard_id": shard.shard_id,
                "task_id": task_id,
                "task_index": task_index,
                "task_count": task_count,
                "recipe_ids": [recipe_id],
                "recipe_count": 1,
                "worker_hint_recipes": (
                    [dict(hint_by_recipe_id[recipe_id])]
                    if recipe_id in hint_by_recipe_id
                    else []
                ),
            },
        )
        task_plans.append(
            _RecipeTaskPlan(
                task_id=task_id,
                parent_shard_id=shard.shard_id,
                manifest_entry=task_manifest,
            )
        )
    return tuple(task_plans)


def _build_recipe_task_runtime_manifest_entry(
    task_plan: _RecipeTaskPlan,
) -> TaskManifestEntryV1:
    task_manifest = task_plan.manifest_entry
    metadata = dict(task_manifest.metadata or {})
    metadata.setdefault("input_path", f"in/{task_plan.task_id}.json")
    metadata.setdefault("hint_path", f"hints/{task_plan.task_id}.md")
    metadata.setdefault("result_path", f"out/{task_plan.task_id}.json")
    return TaskManifestEntryV1(
        task_id=task_plan.task_id,
        task_kind="recipe_correction_recipe",
        parent_shard_id=task_plan.parent_shard_id,
        owned_ids=tuple(task_manifest.owned_ids),
        input_payload=task_manifest.input_payload,
        input_text=task_manifest.input_text,
        metadata=metadata,
    )


def _aggregate_recipe_task_payloads(
    *,
    shard: ShardManifestEntryV1,
    task_payloads_by_task_id: Mapping[str, dict[str, Any] | None],
    task_validation_errors_by_task_id: Mapping[str, Sequence[str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_recipe_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    recipe_rows_by_id: dict[str, dict[str, Any]] = {}
    task_id_by_recipe_id: dict[str, str] = {}
    accepted_task_ids: list[str] = []
    for task_id, payload in task_payloads_by_task_id.items():
        rows = payload.get("r") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            continue
        accepted_task_ids.append(task_id)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            recipe_id = str(row.get("rid") or "").strip()
            if not recipe_id:
                continue
            recipe_rows_by_id[recipe_id] = dict(row)
            task_id_by_recipe_id[recipe_id] = str(task_id)
    output_rows: list[dict[str, Any]] = []
    missing_recipe_ids: list[str] = []
    for recipe_id in ordered_recipe_ids:
        recipe_row = recipe_rows_by_id.get(recipe_id)
        if recipe_row is None:
            missing_recipe_ids.append(recipe_id)
            continue
        output_rows.append(dict(recipe_row))
    all_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id in [*task_payloads_by_task_id.keys(), *task_validation_errors_by_task_id.keys()]
            if str(task_id).strip()
        }
    )
    fallback_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors or task_id not in accepted_task_ids
        }
    )
    metadata = {
        "task_count": len(all_task_ids),
        "accepted_task_count": len(accepted_task_ids),
        "accepted_task_ids": sorted(accepted_task_ids),
        "fallback_task_count": len(fallback_task_ids),
        "fallback_task_ids": fallback_task_ids,
        "missing_recipe_ids": missing_recipe_ids,
        "task_ids": all_task_ids,
        "task_validation_errors_by_task_id": {
            task_id: list(errors)
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors
        },
        "task_id_by_recipe_id": {
            recipe_id: task_id
            for recipe_id, task_id in sorted(task_id_by_recipe_id.items())
        },
    }
    return {
        "v": "1",
        "sid": shard.shard_id,
        "r": output_rows,
    }, metadata


def _run_recipe_workspace_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    shard_completed_callback: Callable[..., None] | None,
) -> _DirectRecipeWorkerResult:
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    runnable_shards: list[ShardManifestEntryV1] = []
    runnable_tasks: list[_RecipeTaskPlan] = []
    runnable_tasks_by_shard_id: dict[str, tuple[_RecipeTaskPlan, ...]] = {}
    worker_prompt_path = worker_root / "prompt.txt"
    worker_prompt_text = ""

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_recipe_shard(shard)
        if preflight_failure is None:
            task_plans = _build_recipe_task_plans(shard)
            if task_plans:
                runnable_shards.append(shard)
                runnable_tasks_by_shard_id[shard.shard_id] = task_plans
                runnable_tasks.extend(task_plans)
            continue
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text="recipe correction worker preflight rejected",
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
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            proposal_path,
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                    "state": "preflight_rejected",
                    "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                    "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                    "retryable": False,
                },
            )
        )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    _write_json(
        [asdict(_build_recipe_task_runtime_manifest_entry(task)) for task in runnable_tasks],
        worker_root / "assigned_tasks.json",
    )
    if runnable_tasks:
        _write_recipe_workspace_contract_sidecars(
            worker_root=worker_root,
            tasks=runnable_tasks,
        )
        _write_recipe_workspace_helper_tools(worker_root=worker_root)
    for task in runnable_tasks:
        task_manifest = task.manifest_entry
        input_path = in_dir / f"{task_manifest.shard_id}.json"
        hint_path = hints_dir / f"{task_manifest.shard_id}.md"
        serialized_input = _serialize_compact_prompt_json(task_manifest.input_payload)
        _write_worker_input(
            path=input_path,
            payload=task_manifest.input_payload,
            input_text=serialized_input,
        )
        _write_recipe_worker_hint(path=hint_path, shard=task_manifest)

    if runnable_shards and runnable_tasks:
        worker_prompt_text = _build_recipe_workspace_worker_prompt(
            tasks=[
                _build_recipe_task_runtime_manifest_entry(task)
                for task in runnable_tasks
            ]
        )
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            (shard_root / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        run_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="recipe correction worker session",
            supervision_callback=_build_recipe_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                watchdog_policy="workspace_worker_v1",
                stage_label="workspace worker stage",
                allow_workspace_commands=True,
            ),
        )
        _finalize_live_status(
            worker_live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
        _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")

        task_count = len(runnable_tasks)
        task_payloads_by_shard_id: dict[str, dict[str, dict[str, Any]]] = {}
        task_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        task_repair_status_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        for task_index, task in enumerate(runnable_tasks):
            task_manifest = task.manifest_entry
            parent_shard_id = task.parent_shard_id
            task_root = shard_dir / task_manifest.shard_id
            task_root.mkdir(parents=True, exist_ok=True)
            input_path = in_dir / f"{task_manifest.shard_id}.json"
            output_path = out_dir / f"{task_manifest.shard_id}.json"
            response_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
            worker_runner_payload = _build_recipe_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                runtime_task_id=task_manifest.shard_id,
                run_result=run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=task_index,
            )
            worker_runner_results.append(worker_runner_payload)
            worker_rows = (
                worker_runner_payload.get("telemetry", {}).get("rows")
                if isinstance(worker_runner_payload.get("telemetry"), dict)
                else None
            )
            if isinstance(worker_rows, list):
                for row_payload in worker_rows:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_recipe_response(
                    shard=task_manifest,
                    response_text=response_text,
                )
            )
            initial_proposal_status = proposal_status
            stage_row = stage_rows[-1]
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
                    shard=task_manifest,
                    env=env,
                    output_schema_path=output_schema_path,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    original_response_text=str(response_text or ""),
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    live_status_path=task_root / "repair_live_status.json",
                )
                _finalize_live_status(
                    task_root / "repair_live_status.json",
                    run_result=repair_run_result,
                )
                repair_payload = _build_recipe_repair_runner_payload(
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    shard_id=parent_shard_id,
                    run_result=repair_run_result,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
                repair_payload["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                repair_payload["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
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
                            row_payload["runtime_task_id"] = task_manifest.shard_id
                            row_payload["runtime_parent_shard_id"] = parent_shard_id
                            stage_rows.append(dict(row_payload))
                (task_root / "repair_events.jsonl").write_text(
                    _render_events_jsonl(repair_run_result.events),
                    encoding="utf-8",
                )
                _write_json(
                    {"text": repair_run_result.response_text},
                    task_root / "repair_last_message.json",
                )
                _write_json(
                    dict(repair_run_result.usage or {}),
                    task_root / "repair_usage.json",
                )
                _write_json(
                    repair_run_result.workspace_manifest(),
                    task_root / "repair_workspace_manifest.json",
                )
                (
                    repair_payload_candidate,
                    repair_errors,
                    repair_metadata,
                    repair_proposal_status,
                ) = _evaluate_recipe_response(
                    shard=task_manifest,
                    response_text=repair_run_result.response_text,
                )
                repair_status = (
                    "repaired" if repair_proposal_status == "validated" else "failed"
                )
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
                    task_root / "repair_status.json",
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
                task_repair_status_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = repair_status
                task_repair_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = tuple(
                    repair_errors if repair_status == "failed" else ()
                )
            stage_row["proposal_status"] = (
                initial_proposal_status if repair_attempted else proposal_status
            )
            stage_row["final_proposal_status"] = proposal_status
            stage_row["repair_attempted"] = repair_attempted
            stage_row["repair_status"] = repair_status
            task_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = tuple(validation_errors)
            if payload is not None and proposal_status == "validated":
                task_payloads_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = payload

        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            task_payloads = task_payloads_by_shard_id.get(shard.shard_id, {})
            task_errors = task_validation_errors_by_shard_id.get(shard.shard_id, {})
            task_repair_statuses = task_repair_status_by_shard_id.get(shard.shard_id, {})
            task_repair_errors = task_repair_validation_errors_by_shard_id.get(
                shard.shard_id, {}
            )
            payload, aggregation_metadata = _aggregate_recipe_task_payloads(
                shard=shard,
                task_payloads_by_task_id=task_payloads,
                task_validation_errors_by_task_id=task_errors,
            )
            payload_candidate, validation_errors, validation_metadata, proposal_status = (
                _evaluate_recipe_response(
                    shard=shard,
                    response_text=json.dumps(payload, sort_keys=True),
                )
            )
            repair_attempted = any(
                str(status).strip() != "not_attempted"
                for status in task_repair_statuses.values()
            )
            repair_status = (
                "repaired"
                if any(str(status).strip() == "repaired" for status in task_repair_statuses.values())
                else ("failed" if repair_attempted else "not_attempted")
            )
            validation_metadata = {
                "task_aggregation": aggregation_metadata,
                **dict(validation_metadata or {}),
            }
            repair_validation_errors = sorted(
                {
                    str(error).strip()
                    for errors in task_repair_errors.values()
                    for error in errors
                    if str(error).strip()
                }
            )
            if task_repair_statuses:
                validation_metadata["task_repair_status_by_task_id"] = {
                    task_id: status
                    for task_id, status in sorted(task_repair_statuses.items())
                }
            if repair_validation_errors:
                validation_metadata["repair_validation_errors"] = repair_validation_errors
            final_payload = payload_candidate if proposal_status == "validated" else None
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            _write_json(
                {
                    "shard_id": shard.shard_id,
                    "worker_id": assignment.worker_id,
                    "payload": final_payload,
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
                    payload=final_payload,
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

    worker_runner_payload = _aggregate_recipe_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows,
    )
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
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
    )


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
    hints_dir = worker_root / "hints"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json([asdict(shard) for shard in assigned_shards], worker_root / "assigned_shards.json")
    _write_json(
        [
            asdict(_build_recipe_task_runtime_manifest_entry(task_plan))
            for shard in assigned_shards
            for task_plan in _build_recipe_task_plans(shard)
        ],
        worker_root / "assigned_tasks.json",
    )
    return _run_recipe_workspace_worker_assignment_v1(
        run_root=run_root,
        assignment=assignment,
        artifacts=artifacts,
        assigned_shards=assigned_shards,
        worker_root=worker_root,
        in_dir=in_dir,
        hints_dir=hints_dir,
        shard_dir=shard_dir,
        logs_dir=logs_dir,
        runner=runner,
        pipeline_id=pipeline_id,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema_path=output_schema_path,
        shard_completed_callback=shard_completed_callback,
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
        "task_manifest": "task_manifest.jsonl",
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
    _write_jsonl(
        run_root / artifacts["task_manifest"],
        [
            asdict(_build_recipe_task_runtime_manifest_entry(task_plan))
            for shard in shards
            for task_plan in _build_recipe_task_plans(shard)
        ],
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
    last_progress_snapshot: tuple[Any, ...] | None = None
    task_ids_by_worker: dict[str, tuple[str, ...]] = {
        assignment.worker_id: tuple(
            task_plan.task_id
            for shard_id in assignment.shard_ids
            for task_plan in _build_recipe_task_plans(shard_by_id[shard_id])
        )
        for assignment in assignments
    }
    total_tasks = sum(len(task_ids) for task_ids in task_ids_by_worker.values())
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }

    def _recipe_worker_followup_status(
        *,
        worker_id: str,
    ) -> tuple[int, int, int]:
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        for task_id in task_ids_by_worker.get(worker_id, ()):
            task_root = run_root / "workers" / worker_id / "shards" / task_id
            repair_prompt_path = task_root / "repair_prompt.txt"
            repair_status_path = task_root / "repair_status.json"
            if repair_prompt_path.exists():
                repair_attempted += 1
            if repair_status_path.exists():
                repair_completed += 1
            elif repair_prompt_path.exists():
                repair_running += 1
        return repair_attempted, repair_completed, repair_running

    def _render_recipe_progress_label(
        *,
        worker_id: str,
        completed_task_ids: set[str],
    ) -> str | None:
        remaining_task_ids = [
            task_id
            for task_id in task_ids_by_worker.get(worker_id, ())
            if task_id not in completed_task_ids
        ]
        if remaining_task_ids:
            first_task_id = remaining_task_ids[0]
            remaining = max(0, len(remaining_task_ids) - 1)
            if remaining <= 0:
                return first_task_id
            return f"{first_task_id} (+{remaining} more)"
        return None

    def _emit_progress_locked(*, force: bool = False) -> None:
        nonlocal last_progress_snapshot
        if progress_callback is None:
            return
        if total_tasks <= 0 and total_shards <= 0:
            return
        completed_task_ids: set[str] = set()
        for assignment in assignments:
            out_dir = run_root / "workers" / assignment.worker_id / "out"
            if not out_dir.exists():
                continue
            for output_path in out_dir.glob("*.json"):
                completed_task_ids.add(output_path.stem)
        completed_tasks = min(total_tasks, len(completed_task_ids))
        active_tasks = [
            label
            for assignment in assignments
            for label in [
                _render_recipe_progress_label(
                    worker_id=assignment.worker_id,
                    completed_task_ids=completed_task_ids,
                )
            ]
            if label is not None
        ]
        running_workers = len(active_tasks)
        completed_workers = max(0, len(assignments) - running_workers)
        if total_tasks > 0:
            message = f"Running recipe correction... task {completed_tasks}/{total_tasks}"
            repair_attempted = 0
            repair_completed = 0
            repair_running = 0
            finalize_workers = 0
            proposal_count = 0
            proposals_dir = run_root / artifacts["proposals_dir"]
            if proposals_dir.exists():
                proposal_count = len(list(proposals_dir.glob("*.json")))
            for assignment in assignments:
                worker_repair_attempted, worker_repair_completed, worker_repair_running = (
                    _recipe_worker_followup_status(worker_id=assignment.worker_id)
                )
                repair_attempted += worker_repair_attempted
                repair_completed += worker_repair_completed
                repair_running += worker_repair_running
                if not any(
                    task_id not in completed_task_ids
                    for task_id in task_ids_by_worker.get(assignment.worker_id, ())
                ) and (pending_shards_by_worker.get(assignment.worker_id) or []):
                    finalize_workers += 1
            detail_lines = [
                f"configured workers: {len(assignments)}",
                f"completed shards: {completed_shards}/{total_shards}",
                f"queued recipe tasks: {max(0, total_tasks - completed_tasks)}",
            ]
            if finalize_workers > 0:
                detail_lines.append(f"workers finalizing shards: {finalize_workers}")
            if repair_attempted > 0:
                detail_lines.append(
                    f"recipe repair attempts: {repair_completed}/{repair_attempted}"
                )
            if repair_running > 0:
                detail_lines.append(f"repair calls running: {repair_running}")
            snapshot = (
                completed_tasks,
                total_tasks,
                completed_shards,
                total_shards,
                running_workers,
                tuple(active_tasks),
                tuple(detail_lines),
                completed_workers,
                repair_attempted,
                repair_completed,
                repair_running,
                finalize_workers,
                proposal_count,
            )
            if not force and snapshot == last_progress_snapshot:
                return
            last_progress_snapshot = snapshot
            progress_callback(
                format_stage_progress(
                    message,
                    stage_label="recipe pipeline",
                    work_unit_label="recipe task",
                    task_current=completed_tasks,
                    task_total=total_tasks,
                    running_workers=running_workers,
                    worker_total=len(assignments),
                    worker_running=running_workers,
                    worker_completed=completed_workers,
                    worker_failed=0,
                    followup_running=finalize_workers + repair_running,
                    followup_completed=completed_shards,
                    followup_total=total_shards,
                    followup_label="shard finalization",
                    artifact_counts={
                        "proposal_count": proposal_count,
                        "repair_attempted": repair_attempted,
                        "repair_completed": repair_completed,
                        "repair_running": repair_running,
                        "shards_completed": completed_shards,
                        "shards_total": total_shards,
                    },
                    last_activity_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    active_tasks=active_tasks,
                    detail_lines=detail_lines,
                )
            )
            return
        active_shards = [
            assignment.shard_ids[0]
            for assignment in assignments
            if assignment.shard_ids
        ]
        snapshot = (
            completed_shards,
            total_shards,
            tuple(active_shards),
        )
        if not force and snapshot == last_progress_snapshot:
            return
        last_progress_snapshot = snapshot
        progress_callback(
            format_stage_progress(
                f"Running recipe correction... task {completed_shards}/{total_shards}",
                stage_label="recipe pipeline",
                work_unit_label="recipe shard",
                task_current=completed_shards,
                task_total=total_shards,
                running_workers=min(len(active_shards), max(0, total_shards - completed_shards)),
                worker_total=len(assignments),
                worker_running=min(len(active_shards), max(0, total_shards - completed_shards)),
                worker_completed=max(
                    0,
                    len(assignments)
                    - min(len(active_shards), max(0, total_shards - completed_shards)),
                ),
                worker_failed=0,
                active_tasks=active_shards[: max(0, total_shards - completed_shards)],
            )
        )

    if progress_callback is not None and (total_tasks > 0 or total_shards > 0):
        _emit_progress_locked(force=True)

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        nonlocal completed_shards
        if progress_callback is None:
            return
        with progress_lock:
            pending = pending_shards_by_worker.get(worker_id) or []
            if shard_id in pending:
                pending.remove(shard_id)
            completed_shards += 1
            _emit_progress_locked()

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
        pending_futures = {
            future: assignment
            for assignment in assignments
            for future in [futures_by_worker_id[assignment.worker_id]]
        }
        while pending_futures:
            done_futures, _ = wait(
                pending_futures.keys(),
                timeout=0.2,
                return_when=FIRST_COMPLETED,
            )
            with progress_lock:
                _emit_progress_locked()
            if not done_futures:
                continue
            for future in done_futures:
                assignment = pending_futures.pop(future)
                result = future.result()
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
            full_blocks_by_index=full_blocks_by_index,
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
                        "worker_hint_recipes": [
                            {
                                "recipe_id": prepared.state.recipe_id,
                                "bundle_name": prepared.state.bundle_name,
                                "title_hint": str(prepared.correction_input.recipe_candidate_hint.get("n") or "").strip(),
                                "quality_flags": list(prepared.candidate_quality_hint.get("f") or []),
                                "source_evidence_row_count": int(prepared.candidate_quality_hint.get("e") or 0),
                                "source_ingredient_like_count": int(prepared.candidate_quality_hint.get("ei") or 0),
                                "source_instruction_like_count": int(prepared.candidate_quality_hint.get("es") or 0),
                                "hint_ingredient_count": int(prepared.candidate_quality_hint.get("hi") or 0),
                                "hint_step_count": int(prepared.candidate_quality_hint.get("hs") or 0),
                                "pre_context_rows": [
                                    {"index": int(index), "text": text}
                                    for index, text in prepared.pre_context_rows
                                ],
                                "post_context_rows": [
                                    {"index": int(index), "text": text}
                                    for index, text in prepared.post_context_rows
                                ],
                            }
                            for prepared in plan.prepared_inputs
                        ],
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
    planned_tasks: list[dict[str, Any]] = []
    planned_shards: list[dict[str, Any]] = []
    shard_ids_by_recipe_id: dict[str, str] = {}
    requested_shard_count = resolve_shard_count(
        total_items=len(states),
        prompt_target_count=run_settings.recipe_prompt_target_count,
        items_per_shard=run_settings.recipe_shard_target_recipes,
        default_items_per_shard=1,
    )
    shard_groups = partition_contiguous_items(
        states,
        shard_count=requested_shard_count,
    )
    for shard_index, shard_states in enumerate(shard_groups):
        shard_states_list = list(shard_states)
        if not shard_states_list:
            continue
        shard_id = (
            f"recipe-shard-{shard_index:04d}-"
            f"r{_recipe_index_from_bundle_name(shard_states_list[0].bundle_name):04d}-"
            f"r{_recipe_index_from_bundle_name(shard_states_list[-1].bundle_name):04d}"
        )
        recipe_ids = [state.recipe_id for state in shard_states_list]
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
        status="degraded",
        severity="soft",
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
