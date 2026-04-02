from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    AuthoritativeRecipeSemantics,
    ConversionReport,
    ConversionResult,
    SourceBlock,
    SourceSupport,
)
from cookimport.core.reporting import compute_file_hash
from cookimport.core.slug import slugify_name
from cookimport.core.source_model import resolve_conversion_source_model, source_blocks_to_rows
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    CodexFarmNonrecipeFinalizeResult,
    run_codex_farm_nonrecipe_finalize,
)
from cookimport.llm.codex_farm_orchestrator import (
    CodexFarmApplyResult,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.parsing.label_source_of_truth import (
    LabelFirstStageResult,
    build_label_first_stage_result,
)
from cookimport.staging.nonrecipe_stage import (
    NonRecipeAuthorityContract,
    NonRecipeAuthorityResult,
    NonRecipeCandidateStatusResult,
    NonRecipeRoutingResult,
    NonRecipeStageResult,
    block_rows_for_nonrecipe_span,
    build_nonrecipe_authority_contract,
    build_nonrecipe_stage_result,
)
from cookimport.staging.recipe_ownership import (
    RecipeDivestment,
    RecipeOwnershipResult,
    apply_recipe_divestments,
    build_recipe_ownership_result,
)
from cookimport.staging.draft_v1 import build_authoritative_recipe_semantics


def _resolve_source_hash(result: ConversionResult, source_file: Path) -> str:
    for artifact in result.raw_artifacts:
        source_hash = getattr(artifact, "source_hash", None)
        if source_hash:
            return str(source_hash)
    try:
        return compute_file_hash(source_file)
    except Exception:  # noqa: BLE001
        return "unknown"


def _append_report_warning(report: ConversionReport | None, message: str) -> ConversionReport:
    if report is None:
        report = ConversionReport()
    warnings = list(report.warnings or [])
    warnings.append(str(message))
    report.warnings = warnings
    return report


def _block_rows_for_indices(
    full_blocks: Sequence[Mapping[str, Any]],
    block_indices: Sequence[int],
    category_by_index: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    if not block_indices:
        return []
    by_index: dict[int, dict[str, Any]] = {}
    for fallback_index, raw_block in enumerate(full_blocks):
        if not isinstance(raw_block, Mapping):
            continue
        try:
            block_index = int(raw_block.get("index"))
        except (TypeError, ValueError):
            block_index = fallback_index
        payload = dict(raw_block)
        payload["index"] = block_index
        if category_by_index is not None and block_index in category_by_index:
            payload["nonrecipe_final_category"] = category_by_index[block_index]
        by_index[block_index] = payload
    rows: list[dict[str, Any]] = []
    for block_index in block_indices:
        payload = by_index.get(int(block_index))
        if payload is None:
            continue
        rows.append(dict(payload))
    return rows


@dataclass(frozen=True, slots=True)
class ExtractedBookBundle:
    source_file: Path
    workbook_slug: str
    importer_name: str
    source_hash: str
    conversion_result: ConversionResult
    source_blocks: list[SourceBlock]
    source_support: list[SourceSupport]
    archive_blocks: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RecipeBoundaryResult:
    extracted_bundle: ExtractedBookBundle
    label_first_result: LabelFirstStageResult
    conversion_result: ConversionResult
    recipe_ownership_result: RecipeOwnershipResult
    recipe_owned_blocks: list[dict[str, Any]]
    outside_recipe_blocks: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RecipeRefineResult:
    recipe_boundary_result: RecipeBoundaryResult
    conversion_result: ConversionResult
    recipe_ownership_result: RecipeOwnershipResult
    authoritative_recipe_payloads_by_recipe_id: dict[str, AuthoritativeRecipeSemantics]
    llm_report: dict[str, Any]
    refinement_mode: str
    llm_apply_result: CodexFarmApplyResult | None = None


@dataclass(frozen=True, slots=True)
class NonrecipeRouteResult:
    recipe_boundary_result: RecipeBoundaryResult
    recipe_refine_result: RecipeRefineResult
    stage_result: NonRecipeStageResult
    routing: NonRecipeRoutingResult
    candidate_queue_nonrecipe_blocks: list[dict[str, Any]]
    excluded_final_other_blocks: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class NonrecipeFinalizeResult:
    nonrecipe_route_result: NonrecipeRouteResult
    recipe_refine_result: RecipeRefineResult
    stage_result: NonRecipeStageResult
    authority_contract: NonRecipeAuthorityContract
    authority: NonRecipeAuthorityResult
    candidate_status: NonRecipeCandidateStatusResult
    authoritative_nonrecipe_blocks: list[dict[str, Any]]
    late_output_nonrecipe_blocks: list[dict[str, Any]]
    unresolved_candidate_blocks: list[dict[str, Any]]
    llm_report: dict[str, Any] | None
    nonrecipe_finalize_write_report: Any | None = None
    nonrecipe_finalize_apply_result: CodexFarmNonrecipeFinalizeResult | None = None


def build_extracted_book_bundle(
    *,
    result: ConversionResult,
    source_file: Path,
    importer_name: str,
    full_blocks: list[dict[str, Any]] | None = None,
) -> ExtractedBookBundle:
    resolved_source_blocks, resolved_source_support = resolve_conversion_source_model(
        result,
        full_blocks=full_blocks,
    )
    archive_blocks = list(full_blocks) if full_blocks is not None else source_blocks_to_rows(
        resolved_source_blocks
    )
    return ExtractedBookBundle(
        source_file=source_file,
        workbook_slug=slugify_name(source_file.stem),
        importer_name=importer_name,
        source_hash=_resolve_source_hash(result, source_file),
        conversion_result=result,
        source_blocks=list(resolved_source_blocks),
        source_support=list(resolved_source_support),
        archive_blocks=list(archive_blocks),
    )


def run_recipe_boundary_stage(
    *,
    extracted_bundle: ExtractedBookBundle,
    run_settings: RunSettings,
    artifact_root: Path | None = None,
    live_llm_allowed: bool = False,
    progress_callback: Any | None = None,
) -> RecipeBoundaryResult:
    label_first_result = build_label_first_stage_result(
        conversion_result=extracted_bundle.conversion_result,
        source_file=extracted_bundle.source_file,
        importer_name=extracted_bundle.importer_name,
        run_settings=run_settings,
        artifact_root=artifact_root,
        full_blocks=list(extracted_bundle.archive_blocks),
        live_llm_allowed=live_llm_allowed,
        progress_callback=progress_callback,
    )
    result = label_first_result.updated_conversion_result
    if extracted_bundle.source_blocks and not result.source_blocks:
        result.source_blocks = list(extracted_bundle.source_blocks)
    if extracted_bundle.source_support and not result.source_support:
        result.source_support = list(extracted_bundle.source_support)
    recipe_ownership_result = build_recipe_ownership_result(
        full_blocks=extracted_bundle.archive_blocks,
        recipe_spans=label_first_result.recipe_spans,
        recipes=result.recipes,
        ownership_mode="recipe_boundary",
    )
    recipe_owned_blocks = _block_rows_for_indices(
        extracted_bundle.archive_blocks,
        recipe_ownership_result.owned_block_indices,
    )
    return RecipeBoundaryResult(
        extracted_bundle=extracted_bundle,
        label_first_result=label_first_result,
        conversion_result=result,
        recipe_ownership_result=recipe_ownership_result,
        recipe_owned_blocks=recipe_owned_blocks,
        outside_recipe_blocks=list(result.non_recipe_blocks),
    )


def run_recipe_refine_stage(
    *,
    recipe_boundary_result: RecipeBoundaryResult,
    run_settings: RunSettings,
    run_root: Path,
    run_config: Mapping[str, Any] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> RecipeRefineResult:
    del run_config

    result = recipe_boundary_result.conversion_result
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
    llm_apply_result: CodexFarmApplyResult | None = None
    authoritative_recipe_payloads_by_recipe_id: dict[str, AuthoritativeRecipeSemantics] = {}
    refinement_mode = "deterministic_only"
    recipe_divestments: list[RecipeDivestment] = []

    if run_settings.llm_recipe_pipeline.value != "off":
        try:
            llm_apply_result = run_codex_farm_recipe_pipeline(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=recipe_boundary_result.extracted_bundle.workbook_slug,
                full_blocks=list(recipe_boundary_result.extracted_bundle.archive_blocks),
                progress_callback=progress_callback,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value != "fallback":
                raise
            result.report = _append_report_warning(
                result.report,
                "LLM recipe pipeline failed; falling back to deterministic outputs: "
                f"{exc}",
            )
            llm_report = {
                "enabled": True,
                "pipeline": run_settings.llm_recipe_pipeline.value,
                "fallbackApplied": True,
                "fatalError": str(exc),
            }
            refinement_mode = "fallback_after_llm_failure"
        else:
            result = llm_apply_result.updated_conversion_result
            authoritative_recipe_payloads_by_recipe_id = dict(
                llm_apply_result.authoritative_recipe_payloads_by_recipe_id
            )
            recipe_divestments = list(llm_apply_result.recipe_divestments)
            llm_report = dict(llm_apply_result.llm_report)
            refinement_mode = "codex_recipe_refine"

    if not authoritative_recipe_payloads_by_recipe_id:
        authoritative_recipe_payloads_by_recipe_id = {}
        for recipe in result.recipes:
            semantics = build_authoritative_recipe_semantics(
                recipe,
                semantic_authority="deterministic_recipe_projection",
                ingredient_parser_options=run_settings.to_run_config_dict(),
                instruction_step_options=run_settings.to_run_config_dict(),
            )
            authoritative_recipe_payloads_by_recipe_id[semantics.recipe_id] = semantics

    recipe_ownership_result = apply_recipe_divestments(
        ownership_result=recipe_boundary_result.recipe_ownership_result,
        divestments=recipe_divestments,
        ownership_mode="recipe_boundary_with_explicit_divestment",
    )

    return RecipeRefineResult(
        recipe_boundary_result=recipe_boundary_result,
        conversion_result=result,
        recipe_ownership_result=recipe_ownership_result,
        authoritative_recipe_payloads_by_recipe_id=authoritative_recipe_payloads_by_recipe_id,
        llm_report=llm_report,
        refinement_mode=refinement_mode,
        llm_apply_result=llm_apply_result,
    )


def run_nonrecipe_route_stage(
    *,
    recipe_boundary_result: RecipeBoundaryResult,
    recipe_refine_result: RecipeRefineResult,
    overrides: Any | None = None,
) -> NonrecipeRouteResult:
    stage_result = build_nonrecipe_stage_result(
        full_blocks=recipe_boundary_result.extracted_bundle.archive_blocks,
        final_block_labels=recipe_boundary_result.label_first_result.block_labels,
        recipe_ownership_result=recipe_refine_result.recipe_ownership_result,
        overrides=overrides,
    )
    return NonrecipeRouteResult(
        recipe_boundary_result=recipe_boundary_result,
        recipe_refine_result=recipe_refine_result,
        stage_result=stage_result,
        routing=stage_result.routing,
        candidate_queue_nonrecipe_blocks=_block_rows_for_indices(
            recipe_boundary_result.extracted_bundle.archive_blocks,
            stage_result.routing.candidate_block_indices,
        ),
        excluded_final_other_blocks=[
            row
            for span in stage_result.routing.excluded_nonrecipe_spans
            for row in block_rows_for_nonrecipe_span(
                full_blocks=recipe_boundary_result.extracted_bundle.archive_blocks,
                span=span,
            )
        ],
    )


def run_nonrecipe_finalize_stage(
    *,
    nonrecipe_route_result: NonrecipeRouteResult,
    run_settings: RunSettings,
    run_root: Path,
    overrides: Any | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> NonrecipeFinalizeResult:
    recipe_boundary_result = nonrecipe_route_result.recipe_boundary_result
    recipe_refine_result = nonrecipe_route_result.recipe_refine_result
    stage_result = nonrecipe_route_result.stage_result
    llm_report: dict[str, Any] | None = None
    nonrecipe_finalize_write_report = None
    nonrecipe_finalize_apply_result: CodexFarmNonrecipeFinalizeResult | None = None

    if run_settings.llm_knowledge_pipeline.value != "off":
        try:
            nonrecipe_finalize_apply_result = run_codex_farm_nonrecipe_finalize(
                conversion_result=recipe_refine_result.conversion_result,
                nonrecipe_stage_result=stage_result,
                recipe_ownership_result=recipe_refine_result.recipe_ownership_result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=recipe_boundary_result.extracted_bundle.workbook_slug,
                overrides=overrides,
                full_blocks=list(recipe_boundary_result.extracted_bundle.archive_blocks),
                progress_callback=progress_callback,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value != "fallback":
                raise
            recipe_refine_result.conversion_result.report = _append_report_warning(
                recipe_refine_result.conversion_result.report,
                "LLM non-recipe finalize failed; continuing without knowledge artifacts: "
                f"{exc}",
            )
            llm_report = {
                "enabled": True,
                "pipeline": run_settings.llm_knowledge_pipeline.value,
                "fallbackApplied": True,
                "fatalError": str(exc),
            }
        else:
            stage_result = nonrecipe_finalize_apply_result.refined_stage_result
            llm_report = dict(nonrecipe_finalize_apply_result.llm_report)
            nonrecipe_finalize_write_report = nonrecipe_finalize_apply_result.write_report

    authority_contract = build_nonrecipe_authority_contract(
        full_blocks=recipe_boundary_result.extracted_bundle.archive_blocks,
        stage_result=stage_result,
    )
    unresolved_candidate_blocks = _block_rows_for_indices(
        recipe_boundary_result.extracted_bundle.archive_blocks,
        stage_result.candidate_status.unresolved_candidate_block_indices,
        stage_result.candidate_status.unresolved_candidate_route_by_index,
    )
    return NonrecipeFinalizeResult(
        nonrecipe_route_result=nonrecipe_route_result,
        recipe_refine_result=recipe_refine_result,
        stage_result=stage_result,
        authority_contract=authority_contract,
        authority=stage_result.authority,
        candidate_status=stage_result.candidate_status,
        authoritative_nonrecipe_blocks=list(authority_contract.final_blocks),
        late_output_nonrecipe_blocks=list(authority_contract.late_output_blocks),
        unresolved_candidate_blocks=unresolved_candidate_blocks,
        llm_report=llm_report,
        nonrecipe_finalize_write_report=nonrecipe_finalize_write_report,
        nonrecipe_finalize_apply_result=nonrecipe_finalize_apply_result,
    )
