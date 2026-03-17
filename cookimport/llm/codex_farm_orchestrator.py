from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.core.models import ConversionResult, RecipeCandidate, RecipeDraftV1
from cookimport.runs import RECIPE_MANIFEST_FILE_NAME, stage_artifact_stem
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
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from .phase_worker_runtime import ShardManifestEntryV1, run_phase_workers_v1
from .recipe_tagging_guide import build_recipe_tagging_guide
from .shard_prompt_targets import resolve_items_per_shard

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
    structural_status: str = "ok"
    structural_reason_codes: list[str] = field(default_factory=list)
    correction_mapping_status: str | None = None
    correction_mapping_reason: str | None = None


@dataclass(frozen=True)
class _PreparedRecipeInput:
    state: _RecipeState
    correction_input: MergedRecipeRepairInput
    evidence_refs: tuple[str, ...]
    block_indices: tuple[int, ...]


@dataclass(frozen=True)
class _RecipeShardPlan:
    shard_id: str
    states: tuple[_RecipeState, ...]
    prepared_inputs: tuple[_PreparedRecipeInput, ...]
    evidence_refs: tuple[str, ...]
    shard_input: RecipeCorrectionShardInput


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
        recipe_candidate_hint=recipe_candidate_hint,
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
    warnings: Sequence[str],
) -> RecipeCorrectionShardRecipeInput:
    return RecipeCorrectionShardRecipeInput(
        recipe_id=correction_input.recipe_id,
        canonical_text=correction_input.canonical_text,
        evidence_rows=list(correction_input.evidence_rows),
        recipe_candidate_hint=dict(correction_input.recipe_candidate_hint),
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
    return _PreparedRecipeInput(
        state=state,
        correction_input=correction_input,
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


def _recipe_worker_count(run_settings: RunSettings) -> int:
    try:
        value = int(run_settings.recipe_worker_count or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _build_recipe_shard_plans(
    *,
    prepared_inputs: Sequence[_PreparedRecipeInput],
    run_settings: RunSettings,
    workbook_slug: str,
    source_hash: str,
) -> list[_RecipeShardPlan]:
    target_recipes = resolve_items_per_shard(
        total_items=len(prepared_inputs),
        prompt_target_count=run_settings.recipe_prompt_target_count,
        items_per_shard=run_settings.recipe_shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    plans: list[_RecipeShardPlan] = []
    for shard_index in range(0, len(prepared_inputs), target_recipes):
        shard_prepared_inputs = tuple(prepared_inputs[shard_index : shard_index + target_recipes])
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
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            owned_recipe_ids=list(shard_recipe_ids),
            recipes=[
                _build_recipe_shard_recipe_input(
                    correction_input=prepared.correction_input,
                    warnings=prepared.state.warnings,
                )
                for prepared in shard_prepared_inputs
            ],
            tagging_guide=build_recipe_tagging_guide(),
            authority_notes=[
                "authoritative_source=recipe_span_blocks",
                "correct_intermediate_recipe_candidates",
                "emit_linkage_payloads_for_deterministic_final_assembly",
                "preserve_owned_recipe_ids_exactly",
            ],
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
    corrected_candidate: RecipeCandidate,
    final_payload: dict[str, Any],
    structural_audit: StructuralAuditResult,
    mapping_status: str | None,
    mapping_reason: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "recipe_correction_audit.v1",
        "recipe_id": state.recipe_id,
        "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
        "stage_pipeline_id": SINGLE_CORRECTION_STAGE_PIPELINE_ID,
        "input": {
            "block_count": len(correction_input.evidence_rows),
            "canonical_char_count": len(correction_input.canonical_text),
            "authority_notes": list(correction_input.authority_notes),
        },
        "output": {
            "title": correction_output.canonical_recipe.title,
            "ingredient_count": len(correction_output.canonical_recipe.ingredients),
            "step_count": len(correction_output.canonical_recipe.steps),
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
        },
        "deterministic_final_assembly": {
            "corrected_candidate_title": corrected_candidate.name,
            "final_step_count": len(list(final_payload.get("steps") or [])),
            "mapping_status": mapping_status,
            "mapping_reason": mapping_reason,
        },
        "structural_audit": structural_audit.to_dict(),
    }


def _serialize_recipe_correction_output(
    output: MergedRecipeRepairOutput,
) -> dict[str, Any]:
    return output.model_dump(mode="json", by_alias=True)


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
        "runtime_mode": "phase_worker_runtime.v1",
        "worker_run_count": len(worker_runs),
        "worker_runs": worker_runs,
        "runtime_mode_audits": runtime_mode_audits,
        "phase_manifest": dict(phase_manifest),
        "promotion_report": dict(promotion_report),
        "telemetry_report": dict(telemetry),
    }


def _build_single_correction_manifest(
    *,
    run_settings: RunSettings,
    llm_raw_dir: Path,
    correction_in_dir: Path,
    correction_out_dir: Path,
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
            "recipe_llm_correct_and_link": getattr(
                state,
                "single_correction_status",
                "pending",
            ),
            "build_final_recipe": getattr(
                state,
                "final_assembly_status",
                "pending",
            ),
            "warnings": list(state.warnings),
            "errors": list(state.errors),
            "structural_status": state.structural_status,
            "structural_reason_codes": list(state.structural_reason_codes),
        }
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
            "recipe_correction_inputs": len(list(correction_in_dir.glob("*.json"))),
            "recipe_correction_ok": sum(
                1
                for state in states
                if getattr(state, "single_correction_status", None) == "ok"
            ),
            "recipe_correction_error": sum(
                1
                for state in states
                if getattr(state, "single_correction_status", None) == "error"
            ),
            "build_final_recipe_ok": sum(
                1
                for state in states
                if getattr(state, "final_assembly_status", None) == "ok"
            ),
            "build_final_recipe_error": sum(
                1
                for state in states
                if getattr(state, "final_assembly_status", None) == "error"
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
            "recipe_correction_in": str(correction_in_dir),
            "recipe_correction_out": str(correction_out_dir),
            "recipe_correction_audit_dir": str(correction_audit_dir),
            "recipe_manifest": str(manifest_path),
            "recipe_phase_runtime_dir": str(phase_runtime_dir) if phase_runtime_dir else None,
        },
        "process_runs": dict(process_runs),
        "phase_runtime": dict(phase_runtime_summary or {}),
        "failures": failures,
        "recipes": recipe_rows,
        "llm_raw_dir": str(llm_raw_dir),
    }


def _run_single_correction_recipe_pipeline(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    runner: CodexFarmRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmApplyResult:
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    correction_stage_dir = llm_raw_dir / stage_artifact_stem("recipe_llm_correct_and_link")
    correction_in_dir = correction_stage_dir / "in"
    correction_out_dir = correction_stage_dir / "out"
    correction_audit_dir = llm_raw_dir / "recipe_correction_audit"
    phase_runtime_dir = llm_raw_dir / "recipe_phase_runtime"
    for path in (correction_in_dir, correction_out_dir, correction_audit_dir, phase_runtime_dir):
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
            correction_in_dir=correction_in_dir,
            correction_out_dir=correction_out_dir,
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
    env = {
        "CODEX_FARM_ROOT": str(pipeline_root),
        _CODEX_FARM_RECIPE_MODE_ENV: run_settings.codex_farm_recipe_mode.value,
    }
    codex_runner: CodexFarmRunner = runner or SubprocessCodexFarmRunner(
        cmd=run_settings.codex_farm_cmd,
        progress_callback=progress_callback,
    )
    output_schema_paths: dict[str, str] = {}
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=run_settings.codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=(SINGLE_CORRECTION_STAGE_PIPELINE_ID,),
            env=env,
        )
        output_schema_paths["recipe_correction"] = str(
            resolve_codex_farm_output_schema_path(
                root_dir=pipeline_root,
                pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID,
            )
        )
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
            state.single_correction_status = "error"  # type: ignore[attr-defined]
            state.final_assembly_status = "error"  # type: ignore[attr-defined]
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
        _write_json(
            serialize_merged_recipe_repair_input(prepared_input.correction_input),
            correction_in_dir / state.bundle_name,
        )

    recipe_shards = _build_recipe_shard_plans(
        prepared_inputs=prepared_inputs,
        run_settings=run_settings,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
    )
    process_runs: dict[str, dict[str, Any]] = {}
    correction_started = time.perf_counter()
    phase_runtime_summary: dict[str, Any] = {}
    if recipe_shards:
        phase_manifest, worker_reports = run_phase_workers_v1(
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
            worker_count=_recipe_worker_count(run_settings),
            root_dir=pipeline_root,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            max_turns_per_shard=run_settings.recipe_shard_max_turns,
            proposal_validator=_validate_recipe_shard_output,
            settings={
                "llm_recipe_pipeline": run_settings.llm_recipe_pipeline.value,
                "recipe_worker_count": run_settings.recipe_worker_count,
                "recipe_shard_target_recipes": run_settings.recipe_shard_target_recipes,
                "recipe_shard_max_turns": run_settings.recipe_shard_max_turns,
            },
            runtime_metadata={
                "workbook_slug": workbook_slug,
                "compatibility_recipe_artifacts_dir": str(correction_stage_dir),
            },
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
    proposals_by_shard_id: dict[str, dict[str, Any]] = {}
    proposals_dir = phase_runtime_dir / "proposals"
    for proposal_path in sorted(proposals_dir.glob("*.json")):
        proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        shard_id = str(proposal_payload.get("shard_id") or proposal_path.stem)
        proposals_by_shard_id[shard_id] = proposal_payload

    for state in states:
        if getattr(state, "single_correction_status", None) == "error":
            continue
    for shard_plan in recipe_shards:
        proposal_payload = proposals_by_shard_id.get(shard_plan.shard_id)
        if proposal_payload is None:
            for state in shard_plan.states:
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
                state.errors.append("missing validated recipe shard proposal.")
            continue

        validation_errors = proposal_payload.get("validation_errors")
        if isinstance(validation_errors, list) and validation_errors:
            for state in shard_plan.states:
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
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
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
                state.errors.append(f"invalid recipe shard output: {exc}")
            continue

        outputs_by_recipe_id = {
            recipe_output.recipe_id: recipe_output for recipe_output in shard_output.recipes
        }
        for prepared in shard_plan.prepared_inputs:
            state = prepared.state
            correction_output = outputs_by_recipe_id.get(state.recipe_id)
            if correction_output is None:
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
                state.errors.append("recipe missing from validated shard output.")
                continue

            _write_json(
                _serialize_recipe_correction_output(correction_output),
                correction_out_dir / state.bundle_name,
            )

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
            audit_payload = _build_recipe_correction_audit(
                state=state,
                correction_input=correction_inputs_by_recipe_id[state.recipe_id],
                correction_output=correction_output,
                corrected_candidate=corrected_candidate,
                final_payload=final_payload,
                structural_audit=structural_audit,
                mapping_status=state.correction_mapping_status,
                mapping_reason=state.correction_mapping_reason,
            )
            _write_json(
                audit_payload,
                correction_audit_dir / _recipe_artifact_filename(state.recipe_id),
            )
            if structural_audit.status == "failed":
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
                state.errors.append(
                    "recipe correction output rejected: "
                    + "; ".join(structural_audit.reason_codes)
                )
                continue
            try:
                draft_model = RecipeDraftV1.model_validate(final_payload)
            except Exception as exc:  # noqa: BLE001
                state.single_correction_status = "error"  # type: ignore[attr-defined]
                state.final_assembly_status = "error"  # type: ignore[attr-defined]
                state.errors.append(
                    f"deterministic final assembly validation failed: {exc}"
                )
                continue

            state.single_correction_status = "ok"  # type: ignore[attr-defined]
            state.final_assembly_status = "ok"  # type: ignore[attr-defined]
            state.warnings.extend(list(correction_output.warnings))
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
    ]
    manifest_path = llm_raw_dir / RECIPE_MANIFEST_FILE_NAME
    manifest = _build_single_correction_manifest(
        run_settings=run_settings,
        llm_raw_dir=llm_raw_dir,
        correction_in_dir=correction_in_dir,
        correction_out_dir=correction_out_dir,
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
    target_recipes = resolve_items_per_shard(
        total_items=len(states),
        prompt_target_count=run_settings.recipe_prompt_target_count,
        items_per_shard=run_settings.recipe_shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    planned_tasks: list[dict[str, Any]] = []
    planned_shards: list[dict[str, Any]] = []
    shard_ids_by_recipe_id: dict[str, str] = {}
    for shard_index in range(0, len(states), target_recipes):
        shard_states = states[shard_index : shard_index + target_recipes]
        if not shard_states:
            continue
        shard_id = (
            f"recipe-shard-{len(planned_shards):04d}-"
            f"r{shard_index:04d}-r{shard_index + len(shard_states) - 1:04d}"
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
        "recipe_shard_target_recipes": target_recipes,
        "worker_count": _recipe_worker_count(run_settings),
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
    runner: CodexFarmRunner | None = None,
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
