from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import RecipeCandidate
from cookimport.core.slug import slugify_name
from cookimport.llm.canonical_line_role_prompt import build_canonical_line_role_prompt
from cookimport.llm.codex_farm_contracts import (
    RecipeCorrectionShardInput,
    RecipeCorrectionShardRecipeInput,
    serialize_merged_recipe_repair_input,
    serialize_recipe_correction_shard_input,
)
from cookimport.llm.codex_farm_orchestrator import (
    _RecipeState,
    _build_recipe_correction_input,
)
from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.llm.phase_worker_runtime import resolve_phase_worker_count
from cookimport.llm.prompt_budget import (
    build_prompt_preview_budget_summary,
    load_prompt_preview_live_stage_summaries,
    load_prompt_preview_stage_calibrations,
    write_prompt_preview_budget_summary,
)
from cookimport.llm.shard_prompt_targets import (
    DEFAULT_PHASE_PROMPT_TARGET_COUNT,
    resolve_items_per_shard,
)
from cookimport.llm.prompt_artifacts import (
    PROMPT_CALL_RECORD_SCHEMA_VERSION,
    build_codex_farm_prompt_type_samples_markdown,
)
from cookimport.parsing.canonical_line_roles import LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, RecipeSpan
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks
from cookimport.staging.nonrecipe_stage import build_nonrecipe_stage_result

_DEFAULT_RECIPE_PIPELINE_ID = "recipe.correction.compact.v1"
_DEFAULT_RECIPE_SURFACE = "codex-recipe-shard-v1"
_DEFAULT_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.compact.v1"
_DEFAULT_KNOWLEDGE_SURFACE = "codex-knowledge-shard-v1"
_DEFAULT_LINE_ROLE_PIPELINE_ID = "line-role.canonical.v1"
_DEFAULT_LINE_ROLE_SURFACE = "codex-line-role-shard-v1"
_DEFAULT_RECIPE_SHARD_TARGET_RECIPES = 3
_DEFAULT_KNOWLEDGE_SHARD_TARGET_CHUNKS = 12


@dataclass(frozen=True)
class PreviewShardAssignment:
    shard_id: str
    worker_id: str
    owned_ids: tuple[str, ...]
    call_ids: tuple[str, ...]
    prompt_chars: int
    task_prompt_chars: int


@dataclass(frozen=True)
class ExistingRunPreviewContext:
    processed_run_dir: Path
    source_file: str
    source_hash: str
    workbook_slug: str
    full_blocks: list[dict[str, Any]]
    recipe_spans: list[RecipeSpan]
    block_labels: list[AuthoritativeBlockLabel]
    recipe_drafts: list[dict[str, Any]]
    recipe_draft_by_span_id: dict[str, dict[str, Any]]
    final_draft_by_index: dict[int, dict[str, Any]]
    labeled_line_rows: list[dict[str, Any]]
    run_config: dict[str, Any]


def write_prompt_preview_for_existing_run(
    *,
    run_path: Path,
    out_dir: Path,
    repo_root: Path,
    llm_recipe_pipeline: str = _DEFAULT_RECIPE_SURFACE,
    llm_knowledge_pipeline: str = _DEFAULT_KNOWLEDGE_SURFACE,
    line_role_pipeline: str = _DEFAULT_LINE_ROLE_SURFACE,
    codex_farm_root: Path | None = None,
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = 0,
    atomic_block_splitter: str = "atomic-v1",
    recipe_worker_count: int | None = None,
    recipe_prompt_target_count: int | None = None,
    recipe_shard_target_recipes: int | None = None,
    knowledge_worker_count: int | None = None,
    knowledge_prompt_target_count: int | None = None,
    knowledge_shard_target_chunks: int | None = None,
    line_role_worker_count: int | None = None,
    line_role_prompt_target_count: int | None = None,
    line_role_shard_target_lines: int | None = None,
) -> Path:
    context = _load_existing_run_preview_context(run_path=run_path)
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    resolved_recipe_prompt_target_count = (
        recipe_prompt_target_count
        if recipe_prompt_target_count is not None
        else _coerce_int(context.run_config.get("recipe_prompt_target_count"))
    )
    if resolved_recipe_prompt_target_count is None:
        resolved_recipe_prompt_target_count = DEFAULT_PHASE_PROMPT_TARGET_COUNT
    resolved_knowledge_prompt_target_count = (
        knowledge_prompt_target_count
        if knowledge_prompt_target_count is not None
        else _coerce_int(context.run_config.get("knowledge_prompt_target_count"))
    )
    if resolved_knowledge_prompt_target_count is None:
        resolved_knowledge_prompt_target_count = DEFAULT_PHASE_PROMPT_TARGET_COUNT
    resolved_line_role_prompt_target_count = (
        line_role_prompt_target_count
        if line_role_prompt_target_count is not None
        else _coerce_int(context.run_config.get("line_role_prompt_target_count"))
    )
    if resolved_line_role_prompt_target_count is None:
        resolved_line_role_prompt_target_count = DEFAULT_PHASE_PROMPT_TARGET_COUNT

    pipeline_root = (
        codex_farm_root.expanduser().resolve(strict=False)
        if codex_farm_root is not None
        else (repo_root / "llm_pipelines").resolve(strict=False)
    )
    rows: list[dict[str, Any]] = []
    stage_plans: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}

    if str(llm_recipe_pipeline or "").strip().lower() != "off":
        recipe_rows = _build_recipe_preview_rows(
            context=context,
            out_dir=out_dir,
            pipeline_root=pipeline_root,
            surface_pipeline=llm_recipe_pipeline,
            model_override=codex_farm_model,
            reasoning_effort_override=codex_farm_reasoning_effort,
            prompt_target_count=resolved_recipe_prompt_target_count,
            shard_target_recipes=recipe_shard_target_recipes
            if recipe_shard_target_recipes is not None
            else _coerce_int(context.run_config.get("recipe_shard_target_recipes")),
        )
        stage_plans["recipe_llm_correct_and_link"] = _build_direct_shard_phase_plan(
            stage_key="recipe_llm_correct_and_link",
            stage_label="Recipe Correction",
            stage_order=1,
            surface_pipeline=llm_recipe_pipeline,
            runtime_pipeline_id=_DEFAULT_RECIPE_PIPELINE_ID,
            rows=recipe_rows,
            worker_count=recipe_worker_count
            if recipe_worker_count is not None
            else _coerce_int(context.run_config.get("recipe_worker_count")),
        )
        _annotate_rows_from_phase_plan(
            rows=recipe_rows,
            phase_plan=stage_plans["recipe_llm_correct_and_link"],
        )
        rows.extend(recipe_rows)
        counts["recipe_interaction_count"] = len(recipe_rows)

    if str(llm_knowledge_pipeline or "").strip().lower() != "off":
        knowledge_rows = _build_knowledge_preview_rows(
            context=context,
            out_dir=out_dir,
            pipeline_root=pipeline_root,
            surface_pipeline=llm_knowledge_pipeline,
            model_override=codex_farm_model,
            reasoning_effort_override=codex_farm_reasoning_effort,
            context_blocks=codex_farm_knowledge_context_blocks,
            target_prompt_count=resolved_knowledge_prompt_target_count,
            target_chunks_per_shard=knowledge_shard_target_chunks
            if knowledge_shard_target_chunks is not None
            else _coerce_int(context.run_config.get("knowledge_shard_target_chunks")),
        )
        stage_plans["extract_knowledge_optional"] = _build_direct_shard_phase_plan(
            stage_key="extract_knowledge_optional",
            stage_label="Knowledge Harvest",
            stage_order=4,
            surface_pipeline=llm_knowledge_pipeline,
            runtime_pipeline_id=_DEFAULT_KNOWLEDGE_PIPELINE_ID,
            rows=knowledge_rows,
            worker_count=knowledge_worker_count
            if knowledge_worker_count is not None
            else _coerce_int(context.run_config.get("knowledge_worker_count")),
        )
        _annotate_rows_from_phase_plan(
            rows=knowledge_rows,
            phase_plan=stage_plans["extract_knowledge_optional"],
        )
        rows.extend(knowledge_rows)
        counts["knowledge_interaction_count"] = len(knowledge_rows)

    if str(line_role_pipeline or "").strip().lower() != "off":
        line_role_rows = _build_line_role_preview_rows(
            context=context,
            out_dir=out_dir,
            pipeline_root=pipeline_root,
            surface_pipeline=line_role_pipeline,
            model_override=codex_farm_model,
            reasoning_effort_override=codex_farm_reasoning_effort,
            atomic_block_splitter=atomic_block_splitter,
            prompt_target_count=resolved_line_role_prompt_target_count,
            shard_target_lines=line_role_shard_target_lines,
        )
        stage_plans["line_role"] = _build_direct_shard_phase_plan(
            stage_key="line_role",
            stage_label="Line Role Labeling",
            stage_order=2,
            surface_pipeline=line_role_pipeline,
            runtime_pipeline_id=_DEFAULT_LINE_ROLE_PIPELINE_ID,
            rows=line_role_rows,
            worker_count=line_role_worker_count
            if line_role_worker_count is not None
            else _coerce_int(context.run_config.get("line_role_worker_count")),
        )
        _annotate_rows_from_phase_plan(
            rows=line_role_rows,
            phase_plan=stage_plans["line_role"],
        )
        rows.extend(line_role_rows)
        counts["line_role_interaction_count"] = len(line_role_rows)

    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    full_prompt_log_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _write_prompt_request_response_log(rows=rows, output_path=prompts_dir / "prompt_request_response_log.txt")
    _write_stage_prompt_files(rows=rows, prompts_dir=prompts_dir)
    build_codex_farm_prompt_type_samples_markdown(
        full_prompt_log_path=full_prompt_log_path,
        output_path=prompts_dir / "prompt_type_samples_from_full_prompt_log.md",
        examples_per_pass=3,
    )
    budget_summary = build_prompt_preview_budget_summary(
        prompt_rows=rows,
        preview_dir=out_dir,
        phase_plans=stage_plans,
        live_stage_summaries=load_prompt_preview_live_stage_summaries(
            processed_run_dir=context.processed_run_dir,
            workbook_slug=context.workbook_slug,
        ),
        stage_calibrations=(
            load_prompt_preview_stage_calibrations(repo_root=repo_root)
            if _path_is_within_repo_data_root(
                path=context.processed_run_dir,
                repo_root=repo_root,
            )
            else {}
        ),
    )
    budget_json_path, budget_md_path = write_prompt_preview_budget_summary(
        out_dir,
        budget_summary,
    )

    manifest = {
        "schema_version": "codex_prompt_preview.v2",
        "resolved_processed_run_dir": str(context.processed_run_dir),
        "source_file": context.source_file,
        "source_hash": context.source_hash,
        "workbook_slug": context.workbook_slug,
        "surfaces": {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "llm_knowledge_pipeline": llm_knowledge_pipeline,
            "line_role_pipeline": line_role_pipeline,
        },
        "codex_farm_root": str(pipeline_root),
        "codex_farm_model": codex_farm_model,
        "codex_farm_reasoning_effort": codex_farm_reasoning_effort,
        "codex_farm_context_blocks": int(codex_farm_context_blocks),
        "codex_farm_knowledge_context_blocks": int(codex_farm_knowledge_context_blocks),
        "atomic_block_splitter": atomic_block_splitter,
        "preview_settings": {
            "recipe_worker_count": recipe_worker_count,
            "recipe_prompt_target_count": resolved_recipe_prompt_target_count,
            "recipe_shard_target_recipes": recipe_shard_target_recipes,
            "knowledge_worker_count": knowledge_worker_count,
            "knowledge_prompt_target_count": resolved_knowledge_prompt_target_count,
            "knowledge_shard_target_chunks": knowledge_shard_target_chunks,
            "line_role_worker_count": line_role_worker_count,
            "line_role_prompt_target_count": resolved_line_role_prompt_target_count,
            "line_role_shard_target_lines": line_role_shard_target_lines,
        },
        "counts": counts,
        "phase_plans": stage_plans,
        "warnings": budget_summary.get("warnings") or [],
        "artifacts": {
            "full_prompt_log_jsonl": "prompts/full_prompt_log.jsonl",
            "prompt_request_response_log_txt": "prompts/prompt_request_response_log.txt",
            "prompt_type_samples_from_full_prompt_log_md": (
                "prompts/prompt_type_samples_from_full_prompt_log.md"
            ),
            "prompt_preview_budget_summary_json": str(budget_json_path.relative_to(out_dir)),
            "prompt_preview_budget_summary_md": str(budget_md_path.relative_to(out_dir)),
        },
    }
    manifest_path = out_dir / "prompt_preview_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _load_existing_run_preview_context(*, run_path: Path) -> ExistingRunPreviewContext:
    processed_run_dir = _resolve_processed_run_dir(run_path=run_path)
    report_path = _single_path(processed_run_dir.glob("*.excel_import_report.json"))
    report_payload = _read_json(report_path)
    run_config = _coerce_dict(report_payload.get("runConfig"))
    source_file = str(report_payload.get("sourceFile") or "unknown").strip() or "unknown"

    full_text_path = _single_path(processed_run_dir.glob("raw/*/*/full_text.json"))
    full_text_payload = _read_json(full_text_path)
    raw_blocks = full_text_payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError(f"Expected non-empty blocks in {full_text_path}")
    full_blocks: list[dict[str, Any]] = []
    for block_index, block in enumerate(raw_blocks):
        if not isinstance(block, Mapping):
            continue
        payload = dict(block)
        payload["index"] = block_index
        payload["block_id"] = f"block:{block_index}"
        payload["source_full_text_index"] = block.get("index")
        full_blocks.append(payload)
    if not full_blocks:
        raise ValueError(f"No usable blocks found in {full_text_path}")

    workbook_slug = _discover_workbook_slug(processed_run_dir=processed_run_dir)
    labeled_line_rows = _load_labeled_line_rows(
        processed_run_dir=processed_run_dir,
        workbook_slug=workbook_slug,
    )
    full_blocks_from_labeled_lines = _full_blocks_from_labeled_lines(
        labeled_line_rows=labeled_line_rows
    )
    if (
        full_blocks_from_labeled_lines
        and len(full_blocks_from_labeled_lines) > len(full_blocks)
    ):
        full_blocks = full_blocks_from_labeled_lines
    block_labels_payload = _read_json(
        processed_run_dir
        / "group_recipe_spans"
        / workbook_slug
        / "authoritative_block_labels.json"
    )
    block_labels = [
        _normalize_authoritative_block_label(row)
        for row in block_labels_payload.get("block_labels") or []
        if isinstance(row, dict)
    ]
    recipe_spans_payload = _read_json(
        processed_run_dir / "group_recipe_spans" / workbook_slug / "recipe_spans.json"
    )
    recipe_spans = [
        _normalize_recipe_span(row)
        for row in recipe_spans_payload.get("recipe_spans") or []
        if isinstance(row, dict)
    ]

    recipe_drafts = _load_recipe_drafts(processed_run_dir=processed_run_dir, workbook_slug=workbook_slug)
    recipe_draft_by_span_id: dict[str, dict[str, Any]] = {}
    for draft in recipe_drafts:
        span_id = (
            _coerce_dict(draft.get("recipeimport:provenance"))
            .get("location", {})
            .get("recipe_span_id")
        )
        if isinstance(span_id, str) and span_id.strip():
            recipe_draft_by_span_id[span_id.strip()] = draft

    final_draft_by_index = _load_final_draft_by_index(
        processed_run_dir=processed_run_dir,
        workbook_slug=workbook_slug,
    )
    source_hash = _discover_source_hash(
        report_payload=report_payload,
        recipe_drafts=recipe_drafts,
    )
    return ExistingRunPreviewContext(
        processed_run_dir=processed_run_dir,
        source_file=source_file,
        source_hash=source_hash,
        workbook_slug=workbook_slug,
        full_blocks=full_blocks,
        recipe_spans=recipe_spans,
        block_labels=block_labels,
        recipe_drafts=recipe_drafts,
        recipe_draft_by_span_id=recipe_draft_by_span_id,
        final_draft_by_index=final_draft_by_index,
        labeled_line_rows=labeled_line_rows,
        run_config=run_config,
    )


def _build_recipe_preview_rows(
    *,
    context: ExistingRunPreviewContext,
    out_dir: Path,
    pipeline_root: Path,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    prompt_target_count: int | None,
    shard_target_recipes: int | None,
) -> list[dict[str, Any]]:
    pipeline_assets = _load_pipeline_assets(
        pipeline_root=pipeline_root,
        pipeline_id=_DEFAULT_RECIPE_PIPELINE_ID,
    )
    stage_dir = (
        out_dir / "raw" / "llm" / context.workbook_slug / "recipe_llm_correct_and_link"
    )
    in_dir = stage_dir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)

    full_blocks_by_index = {
        int(block["index"]): block for block in context.full_blocks if isinstance(block, dict)
    }
    existing_input_dir = (
        context.processed_run_dir
        / "raw"
        / "llm"
        / context.workbook_slug
        / "recipe_correction"
        / "in"
    )
    recipe_inputs: list[dict[str, Any]] = []
    if existing_input_dir.is_dir():
        for existing_input_path in sorted(existing_input_dir.glob("*.json"), key=lambda path: path.name):
            serialized_input = existing_input_path.read_text(encoding="utf-8")
            input_payload = _read_json(existing_input_path)
            recipe_id = str(
                input_payload.get("recipe_id")
                or input_payload.get("identifier")
                or existing_input_path.stem
            ).strip() or existing_input_path.stem
            recipe_inputs.append(
                {
                    "call_id": existing_input_path.stem,
                    "recipe_id": recipe_id,
                    "input_payload": input_payload,
                    "input_text": serialized_input,
                }
            )
        if recipe_inputs:
            return _build_recipe_shard_preview_rows(
                context=context,
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                in_dir=in_dir,
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                prompt_target_count=prompt_target_count,
                shard_target_recipes=shard_target_recipes,
                recipe_inputs=recipe_inputs,
            )

    for recipe_index, draft in enumerate(context.recipe_drafts):
        provenance = _coerce_dict(draft.get("recipeimport:provenance"))
        location = _coerce_dict(provenance.get("location"))
        start_block = _coerce_int(location.get("start_block"))
        end_block = _coerce_int(location.get("end_block"))
        if start_block is None or end_block is None:
            continue
        included_blocks = [
            full_blocks_by_index[index]
            for index in range(min(start_block, end_block), max(start_block, end_block) + 1)
            if index in full_blocks_by_index
        ]
        if not included_blocks:
            continue
        recipe_id = str(
            draft.get("identifier")
            or draft.get("@id")
            or f"urn:recipe-preview:{context.workbook_slug}:{recipe_index}"
        ).strip()
        input_payload = _build_recipe_correction_input(
            state=_recipe_state_from_draft(
                draft=draft,
                recipe_id=recipe_id,
                recipe_index=recipe_index,
                start_block=start_block,
                end_block=end_block,
            ),
            workbook_slug=context.workbook_slug,
            source_hash=context.source_hash,
            included_blocks=included_blocks,
        )
        serialized_input = serialize_merged_recipe_repair_input(input_payload)
        recipe_inputs.append(
            {
                "call_id": f"r{recipe_index}",
                "recipe_id": recipe_id,
                "input_payload": serialized_input,
                "input_text": json.dumps(serialized_input, indent=2, sort_keys=True) + "\n",
            }
        )
    return _build_recipe_shard_preview_rows(
        context=context,
        source_file=context.source_file,
        pipeline_assets=pipeline_assets,
        in_dir=in_dir,
        surface_pipeline=surface_pipeline,
        model_override=model_override,
        reasoning_effort_override=reasoning_effort_override,
        prompt_target_count=prompt_target_count,
        shard_target_recipes=shard_target_recipes,
        recipe_inputs=recipe_inputs,
    )


def _build_recipe_shard_preview_rows(
    *,
    context: ExistingRunPreviewContext,
    source_file: str,
    pipeline_assets: Mapping[str, Any],
    in_dir: Path,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    prompt_target_count: int | None,
    shard_target_recipes: int | None,
    recipe_inputs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    effective_target = resolve_items_per_shard(
        total_items=len(recipe_inputs),
        prompt_target_count=prompt_target_count,
        items_per_shard=shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    rows: list[dict[str, Any]] = []
    for index, shard_rows in enumerate(_batch(list(recipe_inputs), size=effective_target), start=1):
        if not shard_rows:
            continue
        first_call_id = str(shard_rows[0].get("call_id") or f"recipe-shard-{index:04d}")
        shard_id = f"recipe-preview-shard-{index:04d}-{first_call_id}"
        shard_recipe_inputs: list[RecipeCorrectionShardRecipeInput] = []
        owned_recipe_ids: list[str] = []
        authority_notes: list[str] = []
        tagging_guide: dict[str, Any] = {}
        for row in shard_rows:
            payload = _coerce_dict(row.get("input_payload"))
            recipe_id = str(row.get("recipe_id") or payload.get("recipe_id") or "").strip()
            if recipe_id:
                owned_recipe_ids.append(recipe_id)
            shard_recipe_inputs.append(
                RecipeCorrectionShardRecipeInput(
                    recipe_id=recipe_id,
                    canonical_text=str(payload.get("canonical_text") or ""),
                    evidence_rows=[
                        tuple(item)
                        for item in payload.get("evidence_rows") or []
                        if isinstance(item, (list, tuple)) and len(item) == 2
                    ],
                    recipe_candidate_hint=_coerce_dict(payload.get("recipe_candidate_hint")),
                    warnings=[],
                )
            )
            if not tagging_guide:
                tagging_guide = _coerce_dict(payload.get("tagging_guide"))
            if not authority_notes:
                authority_notes = [
                    str(note).strip()
                    for note in payload.get("authority_notes") or []
                    if str(note).strip()
                ]
        shard_payload = serialize_recipe_correction_shard_input(
            RecipeCorrectionShardInput(
                shard_id=shard_id,
                workbook_slug=context.workbook_slug,
                source_hash=context.source_hash,
                owned_recipe_ids=owned_recipe_ids,
                recipes=shard_recipe_inputs,
                tagging_guide=tagging_guide,
                authority_notes=authority_notes,
            )
        )
        input_path = in_dir / f"{shard_id}.json"
        serialized_input = json.dumps(shard_payload, indent=2, sort_keys=True) + "\n"
        input_path.write_text(serialized_input, encoding="utf-8")
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=owned_recipe_ids[0] if owned_recipe_ids else input_path.stem,
                source_file=source_file,
                pipeline_assets=dict(pipeline_assets),
                input_payload=shard_payload,
                input_text=serialized_input,
                input_path=input_path,
                stage_key="recipe_llm_correct_and_link",
                stage_label="Recipe Correction",
                stage_order=1,
                stage_dir_name="recipe_llm_correct_and_link",
                stage_artifact_stem="recipe_correction",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                task_prompt_text=serialized_input,
            )
        )
    return rows


def _build_knowledge_preview_rows(
    *,
    context: ExistingRunPreviewContext,
    out_dir: Path,
    pipeline_root: Path,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    context_blocks: int,
    target_prompt_count: int | None,
    target_chunks_per_shard: int | None,
) -> list[dict[str, Any]]:
    pipeline_assets = _load_pipeline_assets(
        pipeline_root=pipeline_root,
        pipeline_id=_DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    stage_dir = out_dir / "raw" / "llm" / context.workbook_slug / "extract_knowledge_optional"
    in_dir = stage_dir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    existing_input_dir = (
        context.processed_run_dir
        / "raw"
        / "llm"
        / context.workbook_slug
        / "knowledge"
        / "in"
    )
    if existing_input_dir.is_dir():
        rows: list[dict[str, Any]] = []
        for existing_input_path in sorted(existing_input_dir.glob("*.json"), key=lambda path: path.name):
            serialized_input = existing_input_path.read_text(encoding="utf-8")
            input_payload = _read_json(existing_input_path)
            input_path = in_dir / existing_input_path.name
            input_path.write_text(serialized_input, encoding="utf-8")
            chunk_id = _knowledge_preview_row_id(
                input_payload=input_payload,
                fallback=existing_input_path.stem,
            )
            rows.append(
                _prompt_row(
                    call_id=input_path.stem,
                    recipe_id=chunk_id,
                    source_file=context.source_file,
                    pipeline_assets=pipeline_assets,
                    input_payload=input_payload,
                    input_text=serialized_input,
                    input_path=input_path,
                    stage_key="extract_knowledge_optional",
                    stage_label="Knowledge Harvest",
                    stage_order=4,
                    stage_dir_name="extract_knowledge_optional",
                    stage_artifact_stem="knowledge",
                    surface_pipeline=surface_pipeline,
                    model_override=model_override,
                    reasoning_effort_override=reasoning_effort_override,
                    task_prompt_text=serialized_input,
                )
            )
        if rows:
            return rows

    nonrecipe_stage_result = build_nonrecipe_stage_result(
        full_blocks=context.full_blocks,
        final_block_labels=context.block_labels,
        recipe_spans=context.recipe_spans,
    )
    build_knowledge_jobs(
        full_blocks=context.full_blocks,
        candidate_spans=(
            nonrecipe_stage_result.seed_nonrecipe_spans
            or nonrecipe_stage_result.nonrecipe_spans
        ),
        recipe_spans=context.recipe_spans,
        workbook_slug=context.workbook_slug,
        source_hash=context.source_hash,
        out_dir=in_dir,
        context_blocks=context_blocks,
        target_prompt_count=target_prompt_count,
        target_chunks_per_shard=target_chunks_per_shard,
    )
    rows: list[dict[str, Any]] = []
    for input_path in sorted(in_dir.glob("*.json"), key=lambda path: path.name):
        serialized_input = input_path.read_text(encoding="utf-8")
        input_payload = _read_json(input_path)
        chunk_id = _knowledge_preview_row_id(
            input_payload=input_payload,
            fallback=input_path.stem,
        )
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=chunk_id,
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                input_payload=input_payload,
                input_text=serialized_input,
                input_path=input_path,
                stage_key="extract_knowledge_optional",
                stage_label="Knowledge Harvest",
                stage_order=4,
                stage_dir_name="extract_knowledge_optional",
                stage_artifact_stem="knowledge",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                task_prompt_text=serialized_input,
            )
        )
    return rows


def _knowledge_preview_row_id(
    *,
    input_payload: Mapping[str, Any],
    fallback: str,
) -> str:
    chunks_payload = input_payload.get("chunks")
    if isinstance(chunks_payload, list) and chunks_payload:
        first_chunk = _coerce_dict(chunks_payload[0])
        first_chunk_id = str(first_chunk.get("chunk_id") or "").strip()
        last_chunk = _coerce_dict(chunks_payload[-1])
        last_chunk_id = str(last_chunk.get("chunk_id") or "").strip()
        if first_chunk_id and last_chunk_id and first_chunk_id != last_chunk_id:
            return f"{first_chunk_id}..{last_chunk_id}"
        if first_chunk_id:
            return first_chunk_id
    return str(input_payload.get("bundle_id") or fallback).strip() or fallback


def _build_line_role_preview_rows(
    *,
    context: ExistingRunPreviewContext,
    out_dir: Path,
    pipeline_root: Path,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    atomic_block_splitter: str,
    prompt_target_count: int | None,
    shard_target_lines: int | None,
) -> list[dict[str, Any]]:
    pipeline_assets = _load_pipeline_assets(
        pipeline_root=pipeline_root,
        pipeline_id=_DEFAULT_LINE_ROLE_PIPELINE_ID,
    )
    stage_dir = out_dir / "line-role-pipeline"
    in_dir = stage_dir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    candidates = _build_line_role_candidates(
        full_blocks=context.full_blocks,
        recipe_spans=context.recipe_spans,
        recipe_draft_by_span_id=context.recipe_draft_by_span_id,
        labeled_line_rows=context.labeled_line_rows,
        atomic_block_splitter=atomic_block_splitter,
    )
    rows: list[dict[str, Any]] = []
    deterministic_labels_by_atomic_index = _line_role_preview_deterministic_labels(
        labeled_line_rows=context.labeled_line_rows,
    )
    escalation_reasons_by_atomic_index = _line_role_preview_escalation_reasons(
        labeled_line_rows=context.labeled_line_rows,
    )
    effective_target_lines = (
        resolve_items_per_shard(
            total_items=len(candidates),
            prompt_target_count=prompt_target_count,
            items_per_shard=shard_target_lines,
            default_items_per_shard=LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
        )
        if candidates
        else LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT
    )
    for prompt_index, batch_candidates in enumerate(
        _batch(candidates, size=effective_target_lines),
        start=1,
    ):
        if not batch_candidates:
            continue
        prompt_text = build_canonical_line_role_prompt(
            batch_candidates,
            deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
            escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        )
        input_path = in_dir / f"line_role_prompt_{prompt_index or len(rows) + 1:04d}.json"
        input_path.write_text(prompt_text, encoding="utf-8")
        shard_payload = {
            "shard_id": (
                f"line-role-shard-{prompt_index:04d}-"
                f"a{int(batch_candidates[0].atomic_index):06d}-"
                f"a{int(batch_candidates[-1].atomic_index):06d}"
            ),
            "phase_key": "line_role",
            "rows": [
                {
                    "atomic_index": int(candidate.atomic_index),
                    "block_id": str(candidate.block_id),
                    "block_index": int(candidate.block_index),
                    "recipe_id": candidate.recipe_id,
                    "within_recipe_span": bool(candidate.within_recipe_span),
                    "text": str(candidate.text),
                    "deterministic_label": deterministic_labels_by_atomic_index.get(
                        int(candidate.atomic_index),
                        "OTHER",
                    ),
                    "escalation_reasons": list(
                        escalation_reasons_by_atomic_index.get(int(candidate.atomic_index), [])
                    ),
                }
                for candidate in batch_candidates
            ],
        }
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=str(batch_candidates[0].recipe_id or input_path.stem),
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                input_payload=shard_payload,
                input_text=prompt_text,
                input_path=input_path,
                stage_key="line_role",
                stage_label="Line Role Labeling",
                stage_order=2,
                stage_dir_name="line-role-pipeline",
                stage_artifact_stem="line_role",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                task_prompt_text=prompt_text,
            )
        )
    return rows


def _build_line_role_candidates(
    *,
    full_blocks: list[dict[str, Any]],
    recipe_spans: list[RecipeSpan],
    recipe_draft_by_span_id: dict[str, dict[str, Any]],
    labeled_line_rows: list[dict[str, Any]],
    atomic_block_splitter: str,
) -> list[AtomicLineCandidate]:
    if labeled_line_rows:
        return _build_line_role_candidates_from_labeled_lines(
            labeled_line_rows=labeled_line_rows,
            recipe_spans=recipe_spans,
        )

    recipe_id_by_block_index: dict[int, str] = {}
    for span in recipe_spans:
        draft = recipe_draft_by_span_id.get(span.span_id)
        recipe_id = None
        if isinstance(draft, dict):
            recipe_id = str(draft.get("identifier") or draft.get("@id") or "").strip() or None
        for block_index in span.block_indices:
            if recipe_id is not None:
                recipe_id_by_block_index[int(block_index)] = recipe_id

    span_block_indices = {
        int(block_index)
        for span in recipe_spans
        for block_index in span.block_indices
    }
    rows: list[dict[str, Any]] = []
    for block in sorted(full_blocks, key=lambda row: int(row["index"])):
        block_index = int(block["index"])
        batch = atomize_blocks(
            [block],
            recipe_id=recipe_id_by_block_index.get(block_index),
            within_recipe_span=block_index in span_block_indices,
            atomic_block_splitter=atomic_block_splitter,
        )
        for candidate in batch:
            rows.append(
                {
                    "recipe_id": candidate.recipe_id,
                    "block_id": candidate.block_id,
                    "block_index": int(candidate.block_index),
                    "text": candidate.text,
                    "within_recipe_span": bool(candidate.within_recipe_span),
                    "rule_tags": list(candidate.rule_tags),
                }
            )

    output: list[AtomicLineCandidate] = []
    for atomic_index, row in enumerate(rows):
        prev_text = rows[atomic_index - 1]["text"] if atomic_index > 0 else None
        next_text = rows[atomic_index + 1]["text"] if atomic_index + 1 < len(rows) else None
        output.append(
            AtomicLineCandidate(
                recipe_id=row["recipe_id"],
                block_id=str(row["block_id"]),
                block_index=int(row["block_index"]),
                atomic_index=atomic_index,
                text=str(row["text"]),
                within_recipe_span=bool(row["within_recipe_span"]),
                prev_text=prev_text,
                next_text=next_text,
                rule_tags=list(row["rule_tags"]),
            )
        )
    return output


def _build_line_role_candidates_from_labeled_lines(
    *,
    labeled_line_rows: list[dict[str, Any]],
    recipe_spans: list[RecipeSpan],
) -> list[AtomicLineCandidate]:
    recipe_block_indices = {
        int(block_index)
        for span in recipe_spans
        for block_index in span.block_indices
    }
    ordered_rows = sorted(
        (dict(row) for row in labeled_line_rows if isinstance(row, Mapping)),
        key=lambda row: int(row.get("atomic_index", 0)),
    )
    output: list[AtomicLineCandidate] = []
    for position, row in enumerate(ordered_rows):
        block_index = int(row.get("source_block_index", row.get("block_index", 0)))
        prev_text = (
            str(ordered_rows[position - 1].get("text") or "")
            if position > 0
            else None
        )
        next_text = (
            str(ordered_rows[position + 1].get("text") or "")
            if position + 1 < len(ordered_rows)
            else None
        )
        output.append(
            AtomicLineCandidate(
                recipe_id=None,
                block_id=str(row.get("source_block_id") or f"block:{block_index}"),
                block_index=block_index,
                atomic_index=int(row.get("atomic_index", position)),
                text=str(row.get("text") or ""),
                within_recipe_span=block_index in recipe_block_indices,
                prev_text=prev_text,
                next_text=next_text,
                rule_tags=[
                    str(tag)
                    for tag in row.get("reason_tags") or []
                    if str(tag or "").strip()
                ],
            )
        )
    return output


def _line_role_preview_deterministic_labels(
    *,
    labeled_line_rows: list[dict[str, Any]],
) -> dict[int, str]:
    labels_by_atomic_index: dict[int, str] = {}
    for row in labeled_line_rows:
        atomic_index = _coerce_int(row.get("atomic_index"))
        if atomic_index is None:
            continue
        label = str(
            row.get("deterministic_label")
            or row.get("label")
            or row.get("final_label")
            or "OTHER"
        ).strip()
        labels_by_atomic_index[atomic_index] = label or "OTHER"
    return labels_by_atomic_index


def _line_role_preview_escalation_reasons(
    *,
    labeled_line_rows: list[dict[str, Any]],
) -> dict[int, list[str]]:
    reasons_by_atomic_index: dict[int, list[str]] = {}
    for row in labeled_line_rows:
        atomic_index = _coerce_int(row.get("atomic_index"))
        if atomic_index is None:
            continue
        rendered_reasons: list[str] = []
        for reason in row.get("escalation_reasons") or []:
            text = str(reason or "").strip()
            if text:
                rendered_reasons.append(text)
        reasons_by_atomic_index[atomic_index] = rendered_reasons
    return reasons_by_atomic_index


def _prompt_row(
    *,
    call_id: str,
    recipe_id: str,
    source_file: str,
    pipeline_assets: dict[str, Any],
    input_payload: dict[str, Any],
    input_path: Path,
    input_text: str | None = None,
    task_prompt_text: str | None = None,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    stage_dir_name: str,
    stage_artifact_stem: str,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
) -> dict[str, Any]:
    serialized_input = input_text
    if serialized_input is None:
        serialized_input = json.dumps(input_payload, ensure_ascii=False, indent=2)
    template_text = str(pipeline_assets.get("prompt_template_text") or "")
    rendered_prompt = _render_prompt_text(
        template_text=template_text,
        input_text=serialized_input,
        input_path=input_path,
    )
    effective_pipeline_payload = _coerce_dict(pipeline_assets.get("pipeline_payload"))
    output_schema_payload = _coerce_dict(pipeline_assets.get("output_schema_payload"))
    model_value = model_override or str(effective_pipeline_payload.get("codex_model") or "").strip() or None
    reasoning_effort_value = (
        reasoning_effort_override
        or str(effective_pipeline_payload.get("codex_reasoning_effort") or "").strip()
        or None
    )
    response_format = None
    if output_schema_payload:
        response_format = {"type": "json_schema", "json_schema": output_schema_payload}
    return {
        "schema_version": PROMPT_CALL_RECORD_SCHEMA_VERSION,
        "call_id": call_id,
        "recipe_id": recipe_id,
        "source_file": source_file,
        "pipeline_id": str(effective_pipeline_payload.get("pipeline_id") or ""),
        "surface_pipeline": surface_pipeline,
        "stage_key": stage_key,
        "stage_heading_key": stage_key,
        "stage_label": stage_label,
        "stage_artifact_stem": stage_artifact_stem,
        "stage_dir_name": stage_dir_name,
        "stage_order": stage_order,
        "model": model_value,
        "request_payload_source": "preview_from_existing_run",
        "request_messages": [{"role": "user", "content": rendered_prompt}],
        "user_prompt": rendered_prompt,
        "rendered_prompt_text": rendered_prompt,
        "rendered_messages": [{"role": "user", "content": rendered_prompt}],
        "prompt_templates": {
            "prompt_template_text": template_text,
            "prompt_template_path": pipeline_assets.get("prompt_template_path"),
        },
        "template_vars": {
            "INPUT_PATH": str(input_path),
            "INPUT_TEXT": serialized_input,
        },
        "prompt_input_mode": str(effective_pipeline_payload.get("prompt_input_mode") or "path"),
        "request": {
            "messages": [{"role": "user", "content": rendered_prompt}],
            "tools": [],
            "response_format": response_format,
            "model": model_value,
            "reasoning_effort": reasoning_effort_value,
            "temperature": None,
            "top_p": None,
            "max_output_tokens": None,
            "seed": None,
            "pipeline_id": str(effective_pipeline_payload.get("pipeline_id") or ""),
            "sandbox": effective_pipeline_payload.get("codex_sandbox"),
            "ask_for_approval": effective_pipeline_payload.get("codex_ask_for_approval"),
            "web_search": effective_pipeline_payload.get("codex_web_search"),
            "output_schema_path": pipeline_assets.get("output_schema_path"),
        },
        "request_input_payload": input_payload,
        "request_input_text": serialized_input,
        "request_input_file": str(input_path),
        "task_prompt_text": task_prompt_text,
        "runtime_phase_key": stage_key,
        "response_format": response_format,
        "decoding_params": {
            "temperature": None,
            "top_p": None,
            "max_output_tokens": None,
            "seed": None,
            "reasoning_effort": reasoning_effort_value,
        },
        "raw_response": {"output_text": None, "output_file": None},
        "parsed_response": None,
        "request_telemetry": None,
        "thinking_trace": None,
    }


def _build_recipe_phase_plan(
    *,
    context: ExistingRunPreviewContext,
    rows: Sequence[dict[str, Any]],
    pipeline_assets: Mapping[str, Any],
    surface_pipeline: str,
    worker_count: int | None,
    prompt_target_count: int | None,
    shard_target_recipes: int | None,
) -> dict[str, Any]:
    effective_target = resolve_items_per_shard(
        total_items=len(rows),
        prompt_target_count=prompt_target_count,
        items_per_shard=shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    shard_specs: list[dict[str, Any]] = []
    for index, recipe_rows in enumerate(_batch(list(rows), size=effective_target), start=1):
        if not recipe_rows:
            continue
        first_call_id = str(recipe_rows[0].get("call_id") or f"recipe-shard-{index:04d}")
        shard_id = f"recipe-preview-shard-{index:04d}-{first_call_id}"
        recipe_inputs: list[RecipeCorrectionShardRecipeInput] = []
        owned_recipe_ids: list[str] = []
        for row in recipe_rows:
            payload = _coerce_dict(row.get("request_input_payload"))
            recipe_id = str(row.get("recipe_id") or payload.get("recipe_id") or row.get("call_id") or "").strip()
            owned_recipe_ids.append(recipe_id)
            recipe_inputs.append(
                RecipeCorrectionShardRecipeInput(
                    recipe_id=recipe_id,
                    canonical_text=str(payload.get("canonical_text") or ""),
                    evidence_rows=[
                        tuple(item)
                        for item in payload.get("evidence_rows") or []
                        if isinstance(item, (list, tuple)) and len(item) == 2
                    ],
                    recipe_candidate_hint=_coerce_dict(payload.get("recipe_candidate_hint")),
                    warnings=[],
                )
            )
        base_payload = _coerce_dict(recipe_rows[0].get("request_input_payload"))
        shard_payload = serialize_recipe_correction_shard_input(
            RecipeCorrectionShardInput(
                shard_id=shard_id,
                workbook_slug=context.workbook_slug,
                source_hash=context.source_hash,
                owned_recipe_ids=owned_recipe_ids,
                recipes=recipe_inputs,
                tagging_guide=_coerce_dict(base_payload.get("tagging_guide")),
                authority_notes=[
                    str(note).strip()
                    for note in base_payload.get("authority_notes") or []
                    if str(note).strip()
                ],
            )
        )
        rendered_prompt = _render_prompt_text(
            template_text=str(pipeline_assets.get("prompt_template_text") or ""),
            input_text=json.dumps(shard_payload, ensure_ascii=False, indent=2),
            input_path=Path(f"<preview>/{shard_id}.json"),
        )
        shard_specs.append(
            {
                "shard_id": shard_id,
                "owned_ids": owned_recipe_ids,
                "call_ids": [str(row.get("call_id") or "") for row in recipe_rows],
                "prompt_chars": len(rendered_prompt),
                "task_prompt_chars": len(json.dumps(shard_payload, ensure_ascii=False, indent=2)),
            }
        )
    return _finalize_phase_plan(
        stage_key="recipe_llm_correct_and_link",
        stage_label="Recipe Correction",
        stage_order=1,
        surface_pipeline=surface_pipeline,
        runtime_pipeline_id=_DEFAULT_RECIPE_PIPELINE_ID,
        worker_count=worker_count,
        shard_specs=shard_specs,
    )


def _build_direct_shard_phase_plan(
    *,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    surface_pipeline: str,
    runtime_pipeline_id: str,
    rows: Sequence[dict[str, Any]],
    worker_count: int | None,
) -> dict[str, Any]:
    shard_specs: list[dict[str, Any]] = []
    for row in rows:
        payload = _coerce_dict(row.get("request_input_payload"))
        owned_ids = _preview_owned_ids_for_row(stage_key=stage_key, row=row)
        shard_specs.append(
            {
                "shard_id": str(
                    payload.get("shard_id")
                    or payload.get("bundle_id")
                    or row.get("call_id")
                    or ""
                ).strip()
                or str(row.get("call_id") or ""),
                "owned_ids": owned_ids,
                "call_ids": [str(row.get("call_id") or "")],
                "prompt_chars": len(str(row.get("rendered_prompt_text") or "")),
                "task_prompt_chars": len(
                    str(row.get("task_prompt_text") or row.get("request_input_text") or "")
                ),
            }
        )
    return _finalize_phase_plan(
        stage_key=stage_key,
        stage_label=stage_label,
        stage_order=stage_order,
        surface_pipeline=surface_pipeline,
        runtime_pipeline_id=runtime_pipeline_id,
        worker_count=worker_count,
        shard_specs=shard_specs,
    )


def _finalize_phase_plan(
    *,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    surface_pipeline: str,
    runtime_pipeline_id: str,
    worker_count: int | None,
    shard_specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    requested_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shard_specs),
    )
    normalized_shards: list[PreviewShardAssignment] = []
    worker_ids = _assign_preview_workers(
        requested_worker_count=requested_workers,
        shard_count=len(shard_specs),
    )
    for index, shard in enumerate(shard_specs):
        normalized_shards.append(
            PreviewShardAssignment(
                shard_id=str(shard.get("shard_id") or f"{stage_key}-shard-{index + 1:04d}"),
                worker_id=worker_ids[index],
                owned_ids=tuple(str(item) for item in shard.get("owned_ids") or [] if str(item)),
                call_ids=tuple(str(item) for item in shard.get("call_ids") or [] if str(item)),
                prompt_chars=max(0, int(shard.get("prompt_chars") or 0)),
                task_prompt_chars=max(0, int(shard.get("task_prompt_chars") or 0)),
            )
        )
    worker_count_effective = len({shard.worker_id for shard in normalized_shards}) or 0
    return {
        "schema_version": "prompt_preview_phase_plan.v1",
        "stage_key": stage_key,
        "stage_label": stage_label,
        "stage_order": stage_order,
        "surface_pipeline": surface_pipeline,
        "runtime_pipeline_id": runtime_pipeline_id,
        "worker_count_requested": requested_workers,
        "worker_count": worker_count_effective,
        "fresh_agent_count": worker_count_effective,
        "interaction_count": sum(len(shard.call_ids) for shard in normalized_shards),
        "shard_count": len(normalized_shards),
        "owned_id_count": sum(len(shard.owned_ids) for shard in normalized_shards),
        "shards_per_worker": _int_distribution(
            [
                sum(1 for shard in normalized_shards if shard.worker_id == worker_id)
                for worker_id in sorted({shard.worker_id for shard in normalized_shards})
            ]
        ),
        "owned_ids_per_shard": _int_distribution(
            [len(shard.owned_ids) for shard in normalized_shards]
        ),
        "first_turn_payload_chars": _int_distribution(
            [shard.prompt_chars for shard in normalized_shards]
        ),
        "task_payload_chars": _int_distribution(
            [shard.task_prompt_chars for shard in normalized_shards]
        ),
        "workers": [
            {
                "worker_id": worker_id,
                "shard_count": sum(1 for shard in normalized_shards if shard.worker_id == worker_id),
                "shard_ids": [
                    shard.shard_id
                    for shard in normalized_shards
                    if shard.worker_id == worker_id
                ],
            }
            for worker_id in sorted({shard.worker_id for shard in normalized_shards})
        ],
        "shards": [
            {
                "shard_id": shard.shard_id,
                "worker_id": shard.worker_id,
                "owned_ids": list(shard.owned_ids),
                "call_ids": list(shard.call_ids),
                "prompt_chars": shard.prompt_chars,
                "task_prompt_chars": shard.task_prompt_chars,
            }
            for shard in normalized_shards
        ],
    }


def _assign_preview_workers(*, requested_worker_count: int, shard_count: int) -> list[str]:
    effective_workers = max(1, min(requested_worker_count, max(shard_count, 1)))
    return [f"worker-{(index % effective_workers) + 1:03d}" for index in range(shard_count)]


def _preview_owned_ids_for_row(*, stage_key: str, row: Mapping[str, Any]) -> list[str]:
    payload = _coerce_dict(row.get("request_input_payload"))
    if stage_key == "recipe_llm_correct_and_link":
        owned_recipe_ids = payload.get("owned_recipe_ids")
        if isinstance(owned_recipe_ids, list):
            return [str(item).strip() for item in owned_recipe_ids if str(item).strip()]
    if stage_key == "extract_knowledge_optional":
        chunks = payload.get("chunks")
        if isinstance(chunks, list):
            return [
                str(_coerce_dict(chunk).get("chunk_id") or "").strip()
                for chunk in chunks
                if str(_coerce_dict(chunk).get("chunk_id") or "").strip()
            ]
    if stage_key == "line_role":
        rows = payload.get("rows")
        if isinstance(rows, list):
            owned_ids: list[str] = []
            for entry in rows:
                atomic_index = _coerce_dict(entry).get("atomic_index")
                if atomic_index is None:
                    continue
                rendered = str(atomic_index).strip()
                if rendered:
                    owned_ids.append(rendered)
            return owned_ids
    recipe_id = str(row.get("recipe_id") or "").strip()
    return [recipe_id] if recipe_id else []


def _annotate_rows_from_phase_plan(
    *,
    rows: Sequence[dict[str, Any]],
    phase_plan: Mapping[str, Any],
) -> None:
    shard_lookup: dict[str, dict[str, Any]] = {}
    for shard in phase_plan.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        for call_id in shard.get("call_ids") or []:
            shard_lookup[str(call_id)] = shard
    for row in rows:
        shard = shard_lookup.get(str(row.get("call_id") or ""))
        if shard is None:
            continue
        row["runtime_shard_id"] = shard.get("shard_id")
        row["runtime_worker_id"] = shard.get("worker_id")
        row["runtime_owned_ids"] = list(shard.get("owned_ids") or [])
        row["request_telemetry"] = {
            "source": "prompt_preview_phase_plan",
            "worker_id": shard.get("worker_id"),
            "shard_id": shard.get("shard_id"),
            "owned_ids": list(shard.get("owned_ids") or []),
        }


def _int_distribution(values: Sequence[int]) -> dict[str, int | float]:
    normalized = [int(value) for value in values if int(value) >= 0]
    if not normalized:
        return {"count": 0, "min": 0, "max": 0, "avg": 0.0}
    return {
        "count": len(normalized),
        "min": min(normalized),
        "max": max(normalized),
        "avg": round(sum(normalized) / len(normalized), 3),
    }


def _resolve_processed_run_dir(*, run_path: Path) -> Path:
    candidate = run_path.expanduser().resolve(strict=False)
    if (candidate / "intermediate drafts").is_dir():
        return candidate

    for manifest_path in _candidate_manifest_paths(root=candidate):
        payload = _read_json(manifest_path)
        artifacts = _coerce_dict(payload.get("artifacts"))
        for key in ("processed_output_run_dir", "stage_run_dir"):
            resolved = artifacts.get(key)
            if isinstance(resolved, str) and resolved.strip():
                stage_dir = Path(resolved.strip()).expanduser().resolve(strict=False)
                if (stage_dir / "intermediate drafts").is_dir():
                    return stage_dir
    raise ValueError(
        f"Could not resolve a processed stage run from {run_path}. "
        "Point at a processed run dir or a benchmark run root with a run manifest."
    )


def _candidate_manifest_paths(*, root: Path) -> list[Path]:
    rows: list[Path] = []
    if root.is_file() and root.name in {"run_manifest.json", "manifest.json"}:
        return [root]
    if root.is_dir():
        for pattern in ("**/run_manifest.json", "**/manifest.json"):
            rows.extend(sorted(root.glob(pattern)))
    return rows


def _path_is_within_repo_data_root(*, path: Path, repo_root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to((repo_root / "data").resolve(strict=False))
    except ValueError:
        return False
    return True


def _load_pipeline_assets(*, pipeline_root: Path, pipeline_id: str) -> dict[str, Any]:
    pipeline_path = pipeline_root / "pipelines" / f"{pipeline_id}.json"
    pipeline_payload = _read_json(pipeline_path)
    prompt_template_rel = str(pipeline_payload.get("prompt_template_path") or "").strip()
    prompt_template_path = pipeline_root / prompt_template_rel
    output_schema_rel = str(pipeline_payload.get("output_schema_path") or "").strip()
    output_schema_path = pipeline_root / output_schema_rel
    return {
        "pipeline_payload": pipeline_payload,
        "prompt_template_text": prompt_template_path.read_text(encoding="utf-8"),
        "prompt_template_path": str(prompt_template_path),
        "output_schema_payload": _read_json(output_schema_path),
        "output_schema_path": str(output_schema_path),
    }


def _render_prompt_text(*, template_text: str, input_text: str, input_path: Path) -> str:
    rendered = str(template_text or "")
    rendered = rendered.replace("{{INPUT_TEXT}}", input_text)
    rendered = rendered.replace("{{ INPUT_TEXT }}", input_text)
    rendered = rendered.replace("{{INPUT_PATH}}", str(input_path))
    rendered = rendered.replace("{{ INPUT_PATH }}", str(input_path))
    return rendered


def _write_prompt_request_response_log(*, rows: list[dict[str, Any]], output_path: Path) -> None:
    lines: list[str] = []
    for row in rows:
        stage_key = str(row.get("stage_key") or "unknown")
        stage_label = str(row.get("stage_label") or "Prompt Stage")
        lines.append(f"=== {stage_key} ({stage_label}) :: {row.get('call_id')} ===")
        lines.append(str(row.get("rendered_prompt_text") or ""))
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_stage_prompt_files(*, rows: list[dict[str, Any]], prompts_dir: Path) -> None:
    grouped: dict[str, list[str]] = {}
    for row in rows:
        stage_key = slugify_name(str(row.get("stage_key") or "prompt_stage"))
        grouped.setdefault(stage_key, [])
        grouped[stage_key].append(
            f"=== {row.get('call_id')} ===\n{str(row.get('rendered_prompt_text') or '')}\n"
        )
    for stage_key, texts in grouped.items():
        (prompts_dir / f"prompt_{stage_key}.txt").write_text(
            "\n".join(texts),
            encoding="utf-8",
        )


def _discover_workbook_slug(*, processed_run_dir: Path) -> str:
    intermediate_root = processed_run_dir / "intermediate drafts"
    subdirs = sorted(path for path in intermediate_root.iterdir() if path.is_dir())
    if len(subdirs) != 1:
        raise ValueError(f"Expected exactly one workbook dir under {intermediate_root}")
    return subdirs[0].name


def _load_recipe_drafts(*, processed_run_dir: Path, workbook_slug: str) -> list[dict[str, Any]]:
    draft_dir = processed_run_dir / "intermediate drafts" / workbook_slug
    rows: list[tuple[int, dict[str, Any]]] = []
    for path in sorted(draft_dir.glob("r*.jsonld"), key=_recipe_sort_key):
        rows.append((_recipe_sort_key(path), _read_json(path)))
    return [payload for _index, payload in rows]


def _load_final_draft_by_index(
    *,
    processed_run_dir: Path,
    workbook_slug: str,
) -> dict[int, dict[str, Any]]:
    draft_dir = processed_run_dir / "final drafts" / workbook_slug
    rows: dict[int, dict[str, Any]] = {}
    for path in sorted(draft_dir.glob("r*.json"), key=_recipe_sort_key):
        rows[_recipe_sort_key(path)] = _read_json(path)
    return rows


def _recipe_sort_key(path: Path) -> int:
    match = re.match(r"r(\d+)", path.stem)
    if match is None:
        return 0
    return int(match.group(1))


def _load_labeled_line_rows(
    *,
    processed_run_dir: Path,
    workbook_slug: str,
) -> list[dict[str, Any]]:
    path = processed_run_dir / "label_det" / workbook_slug / "labeled_lines.jsonl"
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _full_blocks_from_labeled_lines(
    *,
    labeled_line_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not labeled_line_rows:
        return []
    grouped_text_by_index: dict[int, list[str]] = {}
    block_id_by_index: dict[int, str] = {}
    for row in labeled_line_rows:
        block_index = _coerce_int(row.get("source_block_index"))
        if block_index is None:
            continue
        grouped_text_by_index.setdefault(block_index, [])
        text = str(row.get("text") or "").strip()
        if text:
            grouped_text_by_index[block_index].append(text)
        block_id = str(row.get("source_block_id") or f"block:{block_index}").strip()
        block_id_by_index[block_index] = block_id or f"block:{block_index}"
    return [
        {
            "index": block_index,
            "block_id": block_id_by_index.get(block_index, f"block:{block_index}"),
            "text": " ".join(grouped_text_by_index.get(block_index, [])).strip(),
        }
        for block_index in sorted(grouped_text_by_index)
    ]


def _discover_source_hash(
    *,
    report_payload: dict[str, Any],
    recipe_drafts: list[dict[str, Any]],
) -> str:
    llm_payload = _coerce_dict(report_payload.get("llmCodexFarm"))
    source_hash = llm_payload.get("source_hash")
    if isinstance(source_hash, str) and source_hash.strip():
        return source_hash.strip()
    for draft in recipe_drafts:
        provenance = _coerce_dict(draft.get("recipeimport:provenance"))
        candidate = provenance.get("source_hash")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "unknown"


def _recipe_state_from_draft(
    *,
    draft: dict[str, Any],
    recipe_id: str,
    recipe_index: int,
    start_block: int,
    end_block: int,
) -> _RecipeState:
    recipe = RecipeCandidate.model_validate(
        {
            "name": draft.get("name") or "Untitled Recipe",
            "identifier": recipe_id,
            "recipeIngredient": list(draft.get("recipeIngredient") or []),
            "recipeInstructions": list(draft.get("recipeInstructions") or []),
            "description": draft.get("description"),
            "recipeYield": draft.get("recipeYield"),
            "provenance": _coerce_dict(draft.get("recipeimport:provenance")),
        }
    )
    return _RecipeState(
        recipe=recipe,
        recipe_id=recipe_id,
        bundle_name=f"r{recipe_index}",
        heuristic_start=start_block,
        heuristic_end=end_block,
    )


def _normalize_authoritative_block_label(row: Mapping[str, Any]) -> AuthoritativeBlockLabel:
    return AuthoritativeBlockLabel.model_validate(
        {
            "source_block_id": row.get("source_block_id"),
            "source_block_index": row.get("source_block_index"),
            "supporting_atomic_indices": row.get("supporting_atomic_indices") or [],
            "deterministic_label": row.get("deterministic_label"),
            "final_label": row.get("final_label"),
            "decided_by": row.get("decided_by"),
            "reason_tags": row.get("reason_tags") or [],
            "escalation_reasons": row.get("escalation_reasons") or [],
        }
    )


def _normalize_recipe_span(row: Mapping[str, Any]) -> RecipeSpan:
    return RecipeSpan.model_validate(
        {
            "span_id": row.get("span_id"),
            "start_block_index": row.get("start_block_index"),
            "end_block_index": row.get("end_block_index"),
            "block_indices": row.get("block_indices") or [],
            "source_block_ids": row.get("source_block_ids") or [],
            "start_atomic_index": row.get("start_atomic_index"),
            "end_atomic_index": row.get("end_atomic_index"),
            "atomic_indices": row.get("atomic_indices") or [],
            "title_block_index": row.get("title_block_index"),
            "title_atomic_index": row.get("title_atomic_index"),
            "warnings": row.get("warnings") or [],
            "escalation_reasons": row.get("escalation_reasons") or [],
            "decision_notes": row.get("decision_notes") or [],
        }
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _single_path(paths: Any) -> Path:
    rows = list(paths)
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one matching path, found {len(rows)}: {rows}")
    return rows[0]


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _batch(rows: list[AtomicLineCandidate], *, size: int) -> list[list[AtomicLineCandidate]]:
    batch_size = max(1, int(size))
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


__all__ = ["write_prompt_preview_for_existing_run"]
