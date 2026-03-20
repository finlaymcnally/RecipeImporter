from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import RecipeCandidate
from cookimport.core.slug import slugify_name
from cookimport.llm.canonical_line_role_prompt import (
    build_canonical_line_role_file_prompt,
)
from cookimport.llm.codex_farm_contracts import (
    RecipeCorrectionShardInput,
    RecipeCorrectionShardRecipeInput,
    serialize_merged_recipe_repair_input,
    serialize_recipe_correction_shard_input,
)
from cookimport.llm.codex_farm_orchestrator import (
    _RecipeState,
    _build_recipe_candidate_quality_hint,
    _build_recipe_correction_input,
    render_recipe_direct_prompt,
)
from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.llm.codex_farm_knowledge_contracts import (
    knowledge_input_bundle_id,
    knowledge_input_chunk_id,
    knowledge_input_chunks,
)
from cookimport.llm.knowledge_prompt_builder import build_knowledge_direct_prompt
from cookimport.llm.phase_worker_runtime import resolve_phase_worker_count
from cookimport.llm.prompt_budget import (
    build_prompt_preview_budget_summary,
    write_prompt_preview_budget_summary,
)
from cookimport.llm.shard_prompt_targets import (
    partition_contiguous_items,
    resolve_shard_count,
)
from cookimport.llm.prompt_artifacts import (
    PROMPT_CALL_RECORD_SCHEMA_VERSION,
    PROMPT_LOG_SUMMARY_JSON_NAME,
    build_codex_farm_prompt_type_samples_markdown,
    write_prompt_log_summary,
)
from cookimport.parsing.canonical_line_roles import (
    CanonicalLineRolePrediction,
    LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
    build_line_role_debug_input_payload,
    build_line_role_model_input_payload,
)
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


def _serialize_compact_prompt_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


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
    resolved_knowledge_prompt_target_count = (
        knowledge_prompt_target_count
        if knowledge_prompt_target_count is not None
        else _coerce_int(context.run_config.get("knowledge_prompt_target_count"))
    )
    resolved_line_role_prompt_target_count = (
        line_role_prompt_target_count
        if line_role_prompt_target_count is not None
        else _coerce_int(context.run_config.get("line_role_prompt_target_count"))
    )

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
        stage_plans["nonrecipe_knowledge_review"] = _build_direct_shard_phase_plan(
            stage_key="nonrecipe_knowledge_review",
            stage_label="Non-Recipe Knowledge Review",
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
            phase_plan=stage_plans["nonrecipe_knowledge_review"],
        )
        rows.extend(knowledge_rows)
        counts["knowledge_interaction_count"] = len(knowledge_rows)

    if str(line_role_pipeline or "").strip().lower() != "off":
        line_role_preview = _build_line_role_preview_rows(
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
        effective_line_role_workers = (
            line_role_worker_count
            if line_role_worker_count is not None
            else _coerce_int(context.run_config.get("line_role_worker_count"))
        )
        for phase_key, phase_payload in line_role_preview["phase_rows"].items():
            stage_plans[phase_key] = _build_direct_shard_phase_plan(
                stage_key=phase_key,
                stage_label=str(phase_payload["stage_label"]),
                stage_order=int(phase_payload["stage_order"]),
                surface_pipeline=line_role_pipeline,
                runtime_pipeline_id=str(phase_payload["runtime_pipeline_id"]),
                rows=list(phase_payload["rows"]),
                worker_count=effective_line_role_workers,
            )
            _annotate_rows_from_phase_plan(
                rows=list(phase_payload["rows"]),
                phase_plan=stage_plans[phase_key],
            )
            rows.extend(list(phase_payload["rows"]))
        counts["line_role_interaction_count"] = sum(
            len(phase_payload["rows"])
            for phase_payload in line_role_preview["phase_rows"].values()
        )

    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    full_prompt_log_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    write_prompt_log_summary(
        full_prompt_log_path=full_prompt_log_path,
        output_path=prompts_dir / PROMPT_LOG_SUMMARY_JSON_NAME,
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
            "prompt_log_summary_json": f"prompts/{PROMPT_LOG_SUMMARY_JSON_NAME}",
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
    recipe_inputs: list[dict[str, Any]] = []

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
                "candidate_quality_hint": _build_recipe_candidate_quality_hint(
                    included_blocks=included_blocks,
                    recipe_candidate_hint=input_payload.recipe_candidate_hint,
                ),
                "input_payload": serialized_input,
                "input_text": _serialize_compact_prompt_json(serialized_input),
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
    requested_shard_count = resolve_shard_count(
        total_items=len(recipe_inputs),
        prompt_target_count=prompt_target_count,
        items_per_shard=shard_target_recipes,
        default_items_per_shard=_DEFAULT_RECIPE_SHARD_TARGET_RECIPES,
    )
    rows: list[dict[str, Any]] = []
    for index, shard_rows in enumerate(
        partition_contiguous_items(
            recipe_inputs,
            shard_count=requested_shard_count,
        ),
        start=1,
    ):
        if not shard_rows:
            continue
        first_call_id = str(shard_rows[0].get("call_id") or f"recipe-shard-{index:04d}")
        shard_id = f"recipe-preview-shard-{index:04d}-{first_call_id}"
        shard_recipe_inputs: list[RecipeCorrectionShardRecipeInput] = []
        owned_recipe_ids: list[str] = []
        tagging_guide: dict[str, Any] = {}
        for row in shard_rows:
            payload = _coerce_dict(row.get("input_payload"))
            recipe_id = str(
                row.get("recipe_id") or payload.get("recipe_id") or payload.get("rid") or ""
            ).strip()
            if recipe_id:
                owned_recipe_ids.append(recipe_id)
            shard_recipe_inputs.append(
                RecipeCorrectionShardRecipeInput(
                    recipe_id=recipe_id,
                    canonical_text=str(
                        payload.get("canonical_text", payload.get("txt")) or ""
                    ),
                    evidence_rows=[
                        tuple(item)
                        for item in payload.get("evidence_rows", payload.get("ev")) or []
                        if isinstance(item, (list, tuple)) and len(item) == 2
                    ],
                    recipe_candidate_hint=_coerce_dict(
                        payload.get("recipe_candidate_hint", payload.get("h"))
                    ),
                    candidate_quality_hint=_coerce_dict(
                        row.get("candidate_quality_hint")
                    ),
                    warnings=[],
                )
            )
            if not tagging_guide:
                tagging_guide = _coerce_dict(payload.get("tagging_guide", payload.get("tg")))
        shard_payload = serialize_recipe_correction_shard_input(
            RecipeCorrectionShardInput(
                shard_id=shard_id,
                owned_recipe_ids=owned_recipe_ids,
                recipes=shard_recipe_inputs,
                tagging_guide=tagging_guide,
            )
        )
        input_path = in_dir / f"{shard_id}.json"
        serialized_input = _serialize_compact_prompt_json(shard_payload)
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
                rendered_prompt_override=render_recipe_direct_prompt(
                    pipeline_assets=pipeline_assets,
                    input_text=serialized_input,
                    input_path=input_path,
                ),
                prompt_input_mode_override="inline",
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
    stage_dir = out_dir / "raw" / "llm" / context.workbook_slug / "knowledge"
    in_dir = stage_dir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)

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
                stage_key="nonrecipe_knowledge_review",
                stage_label="Non-Recipe Knowledge Review",
                stage_order=4,
                stage_dir_name="knowledge",
                stage_artifact_stem="knowledge",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                task_prompt_text=build_knowledge_direct_prompt(input_payload),
                rendered_prompt_override=build_knowledge_direct_prompt(input_payload),
                prompt_input_mode_override="inline",
            )
        )
    return rows


def _knowledge_preview_row_id(
    *,
    input_payload: Mapping[str, Any],
    fallback: str,
) -> str:
    chunks_payload = knowledge_input_chunks(input_payload)
    if chunks_payload:
        first_chunk_id = knowledge_input_chunk_id(chunks_payload[0])
        last_chunk_id = knowledge_input_chunk_id(chunks_payload[-1])
        if first_chunk_id and last_chunk_id and first_chunk_id != last_chunk_id:
            return f"{first_chunk_id}..{last_chunk_id}"
        if first_chunk_id:
            return first_chunk_id
    return knowledge_input_bundle_id(input_payload) or fallback


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
) -> dict[str, dict[str, Any]]:
    line_role_assets = _load_pipeline_assets(
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
    requested_shard_count = (
        resolve_shard_count(
            total_items=len(candidates),
            prompt_target_count=prompt_target_count,
            items_per_shard=shard_target_lines,
            default_items_per_shard=LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
        )
        if candidates
        else LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT
    )
    line_role_rows: list[dict[str, Any]] = []
    debug_in_dir = out_dir / "line-role-pipeline" / "debug_in"
    debug_in_dir.mkdir(parents=True, exist_ok=True)
    for prompt_index, batch_candidates in enumerate(
        partition_contiguous_items(
            candidates,
            shard_count=requested_shard_count,
        ),
        start=1,
    ):
        if not batch_candidates:
            continue
        input_path = in_dir / f"line_role_input_{prompt_index:04d}.json"
        shard_id = (
            f"line-role-canonical-{prompt_index:04d}-"
            f"a{int(batch_candidates[0].atomic_index):06d}-"
            f"a{int(batch_candidates[-1].atomic_index):06d}"
        )
        deterministic_baseline = {
            int(candidate.atomic_index): CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=deterministic_labels_by_atomic_index.get(
                    int(candidate.atomic_index),
                    "OTHER",
                ),
                decided_by="rule",
                reason_tags=[],
                escalation_reasons=list(
                    escalation_reasons_by_atomic_index.get(
                        int(candidate.atomic_index),
                        (),
                    )
                ),
            )
            for candidate in batch_candidates
        }
        shard_payload = build_line_role_model_input_payload(
            shard_id=shard_id,
            candidates=batch_candidates,
            deterministic_baseline=deterministic_baseline,
        )
        debug_payload = build_line_role_debug_input_payload(
            shard_id=shard_id,
            candidates=batch_candidates,
            deterministic_baseline=deterministic_baseline,
        )
        input_text = json.dumps(shard_payload, ensure_ascii=False, indent=2)
        debug_input_path = debug_in_dir / f"line_role_input_{prompt_index:04d}.json"
        debug_input_text = json.dumps(debug_payload, ensure_ascii=False, indent=2)
        input_path.write_text(input_text, encoding="utf-8")
        debug_input_path.write_text(debug_input_text, encoding="utf-8")
        prompt_text = build_canonical_line_role_file_prompt(
            input_path=input_path,
            input_payload=shard_payload,
        )
        line_role_rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=str(batch_candidates[0].recipe_id or input_path.stem),
                source_file=context.source_file,
                pipeline_assets=line_role_assets,
                input_payload=shard_payload,
                input_text=input_text,
                input_path=input_path,
                debug_input_payload=debug_payload,
                debug_input_text=debug_input_text,
                debug_input_path=debug_input_path,
                stage_key="line_role",
                stage_label="Line Role",
                stage_order=2,
                stage_dir_name="line-role-pipeline",
                stage_artifact_stem="line_role",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
                task_prompt_text=input_text,
                rendered_prompt_override=prompt_text,
                prompt_input_mode_override="inline",
            )
        )
    return {
        "phase_rows": {
            "line_role": {
                "stage_label": "Line Role",
                "stage_order": 2,
                "runtime_pipeline_id": _DEFAULT_LINE_ROLE_PIPELINE_ID,
                "rows": line_role_rows,
            },
        }
    }


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
        )
    del recipe_spans
    del recipe_draft_by_span_id
    rows: list[dict[str, Any]] = []
    for block in sorted(full_blocks, key=lambda row: int(row["index"])):
        batch = atomize_blocks(
            [block],
            recipe_id=None,
            within_recipe_span=None,
            atomic_block_splitter=atomic_block_splitter,
        )
        for candidate in batch:
            rows.append(
                {
                    "recipe_id": candidate.recipe_id,
                    "block_id": candidate.block_id,
                    "block_index": int(candidate.block_index),
                    "text": candidate.text,
                    "within_recipe_span": candidate.within_recipe_span,
                    "rule_tags": list(candidate.rule_tags),
                }
            )

    output: list[AtomicLineCandidate] = []
    for atomic_index, row in enumerate(rows):
        output.append(
            AtomicLineCandidate(
                recipe_id=row["recipe_id"],
                block_id=str(row["block_id"]),
                block_index=int(row["block_index"]),
                atomic_index=atomic_index,
                text=str(row["text"]),
                within_recipe_span=row["within_recipe_span"],
                rule_tags=list(row["rule_tags"]),
            )
        )
    return output


def _build_line_role_candidates_from_labeled_lines(
    *,
    labeled_line_rows: list[dict[str, Any]],
) -> list[AtomicLineCandidate]:
    ordered_rows = sorted(
        (dict(row) for row in labeled_line_rows if isinstance(row, Mapping)),
        key=lambda row: int(row.get("atomic_index", 0)),
    )
    output: list[AtomicLineCandidate] = []
    for position, row in enumerate(ordered_rows):
        block_index = int(row.get("source_block_index", row.get("block_index", 0)))
        output.append(
            AtomicLineCandidate(
                recipe_id=None,
                block_id=str(row.get("source_block_id") or f"block:{block_index}"),
                block_index=block_index,
                atomic_index=int(row.get("atomic_index", position)),
                text=str(row.get("text") or ""),
                within_recipe_span=row.get("within_recipe_span_hint"),
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


    return selected


def _prompt_row(
    *,
    call_id: str,
    recipe_id: str,
    source_file: str,
    pipeline_assets: dict[str, Any],
    input_payload: dict[str, Any],
    input_path: Path,
    input_text: str | None = None,
    debug_input_payload: dict[str, Any] | None = None,
    debug_input_text: str | None = None,
    debug_input_path: Path | None = None,
    task_prompt_text: str | None = None,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    stage_dir_name: str,
    stage_artifact_stem: str,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    rendered_prompt_override: str | None = None,
    prompt_input_mode_override: str | None = None,
) -> dict[str, Any]:
    serialized_input = input_text
    if serialized_input is None:
        serialized_input = json.dumps(input_payload, ensure_ascii=False, indent=2)
    template_text = str(pipeline_assets.get("prompt_template_text") or "")
    rendered_prompt = (
        str(rendered_prompt_override)
        if rendered_prompt_override is not None
        else _render_prompt_text(
            template_text=template_text,
            input_text=serialized_input,
            input_path=input_path,
        )
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
    row = {
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
        "prompt_input_mode": (
            str(prompt_input_mode_override).strip()
            if prompt_input_mode_override is not None
            else str(effective_pipeline_payload.get("prompt_input_mode") or "path")
        ),
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
    if debug_input_payload is not None:
        row["debug_input_payload"] = debug_input_payload
    if debug_input_text is not None:
        row["debug_input_text"] = debug_input_text
    if debug_input_path is not None:
        row["debug_input_file"] = str(debug_input_path)
    return row


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
                    or payload.get("bid")
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
    if stage_key == "nonrecipe_knowledge_review":
        return [
            knowledge_input_chunk_id(chunk)
            for chunk in knowledge_input_chunks(payload)
            if knowledge_input_chunk_id(chunk)
        ]
    if stage_key == "line_role" or stage_key.startswith("line_role_"):
        rows = payload.get("rows")
        if isinstance(rows, list):
            owned_ids: list[str] = []
            for entry in rows:
                atomic_index = None
                if isinstance(entry, Mapping):
                    atomic_index = _coerce_dict(entry).get("atomic_index")
                elif isinstance(entry, list | tuple) and entry:
                    atomic_index = entry[0]
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
        source_classification = _classify_predictive_source(processed_run_dir=candidate)
        if source_classification != "predictive_safe":
            raise ValueError(
                _predictive_source_resolution_error(
                    run_path=run_path,
                    source_description=str(candidate),
                    source_classification=source_classification,
                )
            )
        return candidate

    for _, stage_dir in _resolved_manifest_stage_dirs(
        manifest_paths=_candidate_manifest_paths(root=candidate),
    ):
        if (stage_dir / "intermediate drafts").is_dir():
            return stage_dir
    raise ValueError(
        "Could not resolve a predictive-safe processed stage run from "
        f"{run_path}. Predictive prompt preview only accepts deterministic/vanilla "
        "artifacts and refuses Codex-backed or ambiguous processed runs."
    )


def _candidate_manifest_paths(*, root: Path) -> list[Path]:
    rows: list[Path] = []
    if root.is_file() and root.name in {"run_manifest.json", "manifest.json"}:
        return [root]
    if root.is_dir():
        for pattern in ("**/run_manifest.json", "**/manifest.json"):
            rows.extend(sorted(root.glob(pattern)))
    return rows


def _resolved_manifest_stage_dirs(
    *,
    manifest_paths: Sequence[Path],
) -> list[tuple[int, Path]]:
    resolved_rows: list[tuple[int, Path]] = []
    for manifest_path in manifest_paths:
        payload = _read_json(manifest_path)
        artifacts = _coerce_dict(payload.get("artifacts"))
        for key in ("processed_output_run_dir", "stage_run_dir"):
            resolved = artifacts.get(key)
            if not isinstance(resolved, str) or not resolved.strip():
                continue
            stage_dir = Path(resolved.strip()).expanduser().resolve(strict=False)
            if _classify_predictive_source(
                processed_run_dir=stage_dir,
                manifest_payload=payload,
            ) != "predictive_safe":
                continue
            resolved_rows.append(
                (
                    _score_predictive_manifest(
                        manifest_path=manifest_path,
                        manifest_payload=payload,
                    ),
                    stage_dir,
                )
            )
    resolved_rows.sort(key=lambda item: item[0], reverse=True)
    return resolved_rows


def _score_predictive_manifest(
    *,
    manifest_path: Path,
    manifest_payload: Mapping[str, Any],
) -> int:
    score = 0
    path_text = str(manifest_path).lower()
    run_config = _coerce_dict(
        manifest_payload.get("run_config") or manifest_payload.get("runConfig")
    )
    recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "").strip().lower()
    knowledge_pipeline = str(run_config.get("llm_knowledge_pipeline") or "").strip().lower()
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "").strip().lower()
    codex_enabled = any(
        pipeline not in {"", "off", "deterministic-v1"}
        for pipeline in (recipe_pipeline, knowledge_pipeline, line_role_pipeline)
    )
    vanilla_like = (
        recipe_pipeline in {"", "off"}
        and knowledge_pipeline in {"", "off"}
        and line_role_pipeline in {"", "off", "deterministic-v1"}
    )
    if "/vanilla/" in path_text:
        score += 100
    if vanilla_like:
        score += 50
    if codex_enabled:
        score -= 25
    if "/codexfarm/" in path_text:
        score -= 50
    return score


def _classify_predictive_source(
    *,
    processed_run_dir: Path,
    manifest_payload: Mapping[str, Any] | None = None,
) -> str:
    run_config = _load_processed_run_config(
        processed_run_dir=processed_run_dir,
        manifest_payload=manifest_payload,
    )
    if run_config:
        if _run_config_is_predictive_safe(run_config):
            return "predictive_safe"
        if _run_config_is_codex_backed(run_config):
            return "codex_backed"
    path_text = str(processed_run_dir).lower()
    if "/vanilla/" in path_text:
        return "predictive_safe"
    if "/codexfarm/" in path_text:
        return "codex_backed"
    if _processed_run_has_codex_artifacts(processed_run_dir):
        return "codex_backed"
    return "predictive_safe"


def _load_processed_run_config(
    *,
    processed_run_dir: Path,
    manifest_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(manifest_payload, Mapping):
        manifest_config = _coerce_dict(
            manifest_payload.get("run_config") or manifest_payload.get("runConfig")
        )
        if manifest_config:
            return manifest_config
    report_paths = sorted(processed_run_dir.glob("*.excel_import_report.json"))
    for report_path in report_paths:
        try:
            report_payload = _read_json(report_path)
        except Exception:  # noqa: BLE001
            continue
        run_config = _coerce_dict(report_payload.get("runConfig"))
        if run_config:
            return run_config
    return {}


def _run_config_is_codex_backed(run_config: Mapping[str, Any]) -> bool:
    recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "").strip().lower()
    knowledge_pipeline = str(run_config.get("llm_knowledge_pipeline") or "").strip().lower()
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "").strip().lower()
    return any(
        pipeline not in {"", "off", "deterministic-v1"}
        for pipeline in (recipe_pipeline, knowledge_pipeline, line_role_pipeline)
    )


def _run_config_is_predictive_safe(run_config: Mapping[str, Any]) -> bool:
    recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "").strip().lower()
    knowledge_pipeline = str(run_config.get("llm_knowledge_pipeline") or "").strip().lower()
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "").strip().lower()
    return (
        recipe_pipeline in {"", "off"}
        and knowledge_pipeline in {"", "off"}
        and line_role_pipeline in {"", "off", "deterministic-v1"}
    )


def _predictive_source_resolution_error(
    *,
    run_path: Path,
    source_description: str,
    source_classification: str,
) -> str:
    reason = {
        "codex_backed": "it is Codex-backed",
        "unknown": "it is not clearly deterministic/vanilla",
    }.get(source_classification, "it is not predictive-safe")
    return (
        "Could not resolve a predictive-safe processed stage run from "
        f"{run_path}. The resolved source {source_description} is rejected because "
        f"{reason}. Predictive prompt preview only accepts deterministic/vanilla "
        "artifacts and refuses Codex-backed or ambiguous processed runs."
    )


def _processed_run_has_codex_artifacts(processed_run_dir: Path) -> bool:
    if (processed_run_dir / "prompts" / "full_prompt_log.jsonl").is_file():
        return True
    if (processed_run_dir / "line-role-pipeline" / "telemetry_summary.json").is_file():
        return True
    raw_llm_root = processed_run_dir / "raw" / "llm"
    if not raw_llm_root.is_dir():
        return False
    for workbook_dir in raw_llm_root.iterdir():
        if not workbook_dir.is_dir():
            continue
        if (workbook_dir / "recipe_phase_runtime" / "workers").is_dir():
            return True
        if (workbook_dir / "knowledge" / "workers").is_dir():
            return True
        if (workbook_dir / "recipe_manifest.json").is_file():
            return True
        if (workbook_dir / "knowledge_manifest.json").is_file():
            return True
    return False


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
