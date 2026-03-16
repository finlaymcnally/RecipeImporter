from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionResult, RecipeCandidate, RecipeDraftV1
from cookimport.runs import RECIPE_MANIFEST_FILE_NAME, stage_artifact_stem
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1

from .codex_farm_contracts import (
    MergedCanonicalRecipe,
    MergedRecipeRepairInput,
    MergedRecipeRepairOutput,
    Pass2SchemaOrgOutput,
    StructuralAuditResult,
    classify_pass3_structural_audit,
    load_contract_json,
)
from .codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from .codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)

logger = logging.getLogger(__name__)

SINGLE_CORRECTION_RECIPE_PIPELINE_ID = "codex-farm-single-correction-v1"
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
    start_block_index: int | None = None
    end_block_index: int | None = None
    pass1_raw_start_block_index: int | None = None
    pass1_raw_end_block_index: int | None = None
    pass1_span_loss_metrics: dict[str, Any] | None = None
    pass1_degradation_reasons: list[str] = field(default_factory=list)
    pass1_eligibility_status: str | None = None
    pass1_eligibility_action: str | None = None
    pass1_eligibility_score: int | None = None
    pass1_eligibility_score_components: dict[str, Any] | None = None
    pass1_eligibility_reasons: list[str] = field(default_factory=list)
    excluded_block_ids: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    canonical_text: str = ""
    pass2_effective_indices: list[int] = field(default_factory=list)
    pass2_payload_indices: list[int] = field(default_factory=list)
    pass3_fallback_reason: str | None = None
    pass2_output: Pass2SchemaOrgOutput | None = None
    pass2_degradation_reasons: list[str] = field(default_factory=list)
    pass2_degradation_severity: str | None = None
    pass2_promotion_policy: str | None = None
    pass3_execution_mode: str | None = None
    pass3_routing_reason: str | None = None
    pass3_mapping_status: str | None = None
    pass3_mapping_reason: str | None = None
    pass3_utility_signal: dict[str, Any] | None = None
    structural_status: str = "ok"
    structural_reason_codes: list[str] = field(default_factory=list)


def _recipe_artifact_filename(recipe_id: str) -> str:
    rendered = sanitize_for_filename(str(recipe_id).strip())
    if not rendered:
        rendered = "recipe"
    return f"{rendered}.json"


def _json_bundle_filenames(path: Path) -> list[str]:
    return sorted(child.name for child in path.glob("*.json") if child.is_file())


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
    run_settings: RunSettings,
) -> MergedRecipeRepairInput:
    deterministic_draft = recipe_candidate_to_draft_v1(
        state.recipe,
        ingredient_parser_options=run_settings.to_run_config_dict(),
        instruction_step_options=run_settings.to_run_config_dict(),
    )
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
        recipe_candidate_hint=state.recipe.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        ),
        draft_hint=dict(deterministic_draft),
        authority_notes=[
            "authoritative_source=recipe_span_blocks",
            "correct_intermediate_recipe_candidate",
            "emit_linkage_payload_for_deterministic_final_assembly",
        ],
    )


def _corrected_candidate_from_output(
    *,
    state: _RecipeState,
    output: MergedRecipeRepairOutput,
) -> RecipeCandidate:
    return state.recipe.model_copy(
        update={
            "name": output.canonical_recipe.title,
            "ingredients": list(output.canonical_recipe.ingredients),
            "instructions": list(output.canonical_recipe.steps),
            "description": output.canonical_recipe.description,
            "recipe_yield": output.canonical_recipe.recipe_yield,
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
        mapping_status = getattr(state, "pass3_mapping_status", None)
        mapping_reason = getattr(state, "pass3_mapping_reason", None)
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
        },
        "process_runs": dict(process_runs),
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
    for path in (correction_in_dir, correction_out_dir, correction_audit_dir):
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
                "llmRawDir": str(llm_raw_dir),
            },
            llm_raw_dir=llm_raw_dir,
        )

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
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
        correction_input = _build_recipe_correction_input(
            state=state,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            included_blocks=included_blocks,
            run_settings=run_settings,
        )
        correction_inputs_by_recipe_id[state.recipe_id] = correction_input
        _write_json(
            correction_input.model_dump(mode="json", by_alias=True),
            correction_in_dir / state.bundle_name,
        )

    process_runs: dict[str, dict[str, Any]] = {}
    correction_started = time.perf_counter()
    correction_run = codex_runner.run_pipeline(
        SINGLE_CORRECTION_STAGE_PIPELINE_ID,
        correction_in_dir,
        correction_out_dir,
        env,
        root_dir=pipeline_root,
        workspace_root=workspace_root,
        model=codex_model,
        reasoning_effort=codex_reasoning_effort,
    )
    correction_payload = as_pipeline_run_result_payload(correction_run)
    if correction_payload is not None:
        process_runs["recipe_correction"] = correction_payload
    correction_seconds = time.perf_counter() - correction_started

    updated_result = conversion_result.model_copy(deep=True)
    updated_recipes_by_id: dict[str, RecipeCandidate] = {
        str(recipe.identifier or ""): recipe
        for recipe in updated_result.recipes
    }
    final_overrides: dict[str, dict[str, Any]] = {}
    for state in states:
        if getattr(state, "single_correction_status", None) == "error":
            continue
        out_path = correction_out_dir / state.bundle_name
        if not out_path.exists():
            state.single_correction_status = "error"  # type: ignore[attr-defined]
            state.final_assembly_status = "error"  # type: ignore[attr-defined]
            state.errors.append("missing recipe correction output bundle.")
            continue
        try:
            correction_output = load_contract_json(out_path, MergedRecipeRepairOutput)
        except Exception as exc:  # noqa: BLE001
            state.single_correction_status = "error"  # type: ignore[attr-defined]
            state.final_assembly_status = "error"  # type: ignore[attr-defined]
            state.errors.append(f"invalid recipe correction output: {exc}")
            continue

        corrected_candidate = _corrected_candidate_from_output(
            state=state,
            output=correction_output,
        )
        derived_schemaorg_recipe = _derive_schemaorg_from_canonical_recipe(
            correction_output.canonical_recipe
        )
        derived_pass2_output = Pass2SchemaOrgOutput(
            recipe_id=state.recipe_id,
            schemaorg_recipe=derived_schemaorg_recipe,
            extracted_ingredients=list(correction_output.canonical_recipe.ingredients),
            extracted_instructions=list(correction_output.canonical_recipe.steps),
            field_evidence={},
            warnings=list(correction_output.warnings),
        )
        final_payload = recipe_candidate_to_draft_v1(
            corrected_candidate,
            ingredient_parser_options=run_settings.to_run_config_dict(),
            instruction_step_options=run_settings.to_run_config_dict(),
            ingredient_step_mapping_override=correction_output.ingredient_step_mapping,
            ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason,
        )
        structural_audit = classify_pass3_structural_audit(
            draft_payload=final_payload,
            pass2_output=derived_pass2_output,
            ingredient_step_mapping=correction_output.ingredient_step_mapping,
            ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason,
            pass2_reason_codes=[],
        )
        _merge_structural_audit(state=state, audit=structural_audit)
        (
            state.pass3_mapping_status,
            state.pass3_mapping_reason,
        ) = _classify_pass3_mapping_status(
            draft_payload=final_payload,
            pass2_output=derived_pass2_output,
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
            mapping_status=state.pass3_mapping_status,
            mapping_reason=state.pass3_mapping_reason,
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
            state.errors.append(f"deterministic final assembly validation failed: {exc}")
            continue

        state.single_correction_status = "ok"  # type: ignore[attr-defined]
        state.final_assembly_status = "ok"  # type: ignore[attr-defined]
        state.warnings.extend(list(correction_output.warnings))
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
    )
    _write_json(manifest, manifest_path)
    return CodexFarmApplyResult(
        updated_conversion_result=updated_result,
        intermediate_overrides_by_recipe_id={},
        final_overrides_by_recipe_id=final_overrides,
        llm_report={
            "enabled": True,
            "pipeline": SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
            "counts": manifest["counts"],
            "timing": manifest["timing"],
            "process_runs": manifest["process_runs"],
            "output_schema_paths": dict(output_schema_paths),
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
    for recipe_index, state in enumerate(states):
        planned_tasks.append(
            {
                "recipe_id": state.recipe_id,
                "recipe_index": recipe_index,
                "bundle_name": state.bundle_name,
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


def _derive_schemaorg_from_canonical_recipe(
    canonical_recipe: MergedCanonicalRecipe,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@type": "Recipe",
        "name": canonical_recipe.title,
        "recipeIngredient": list(canonical_recipe.ingredients),
        "recipeInstructions": list(canonical_recipe.steps),
    }
    if canonical_recipe.description:
        payload["description"] = canonical_recipe.description
    if canonical_recipe.recipe_yield:
        payload["recipeYield"] = canonical_recipe.recipe_yield
    return payload


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


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
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


def _classify_pass3_mapping_status(
    *,
    draft_payload: dict[str, Any],
    pass2_output: Pass2SchemaOrgOutput | None,
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

    ingredient_count = (
        sum(1 for item in pass2_output.extracted_ingredients if str(item).strip())
        if pass2_output is not None
        else 0
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
