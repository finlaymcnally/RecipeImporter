from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cookimport.core.slug import slugify_name
from cookimport.llm.canonical_line_role_prompt import build_canonical_line_role_prompt
from cookimport.llm.codex_farm_contracts import (
    MergedRecipeRepairInput,
    serialize_merged_recipe_repair_input,
)
from cookimport.llm.codex_farm_knowledge_jobs import (
    COMPACT_KNOWLEDGE_JOB_FORMAT,
    build_knowledge_jobs,
)
from cookimport.llm.prompt_artifacts import (
    PROMPT_CALL_RECORD_SCHEMA_VERSION,
    build_codex_farm_prompt_type_samples_markdown,
)
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, RecipeSpan
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks
from cookimport.staging.nonrecipe_stage import build_nonrecipe_stage_result

_DEFAULT_RECIPE_PIPELINE_ID = "recipe.correction.compact.v1"
_DEFAULT_RECIPE_SURFACE = "codex-farm-single-correction-v1"
_DEFAULT_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.compact.v1"
_DEFAULT_KNOWLEDGE_SURFACE = "codex-farm-knowledge-v1"
_DEFAULT_LINE_ROLE_PIPELINE_ID = "line-role.canonical.v1"
_DEFAULT_LINE_ROLE_SURFACE = "codex-line-role-v1"


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
    codex_farm_knowledge_context_blocks: int = 2,
    atomic_block_splitter: str = "atomic-v1",
) -> Path:
    context = _load_existing_run_preview_context(run_path=run_path)
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    pipeline_root = (
        codex_farm_root.expanduser().resolve(strict=False)
        if codex_farm_root is not None
        else (repo_root / "llm_pipelines").resolve(strict=False)
    )
    rows: list[dict[str, Any]] = []
    counts = {
        "recipe_prompt_count": 0,
        "knowledge_prompt_count": 0,
        "line_role_prompt_count": 0,
    }

    if str(llm_recipe_pipeline or "").strip().lower() != "off":
        rows.extend(
            _build_recipe_preview_rows(
                context=context,
                out_dir=out_dir,
                pipeline_root=pipeline_root,
                surface_pipeline=llm_recipe_pipeline,
                model_override=codex_farm_model,
                reasoning_effort_override=codex_farm_reasoning_effort,
            )
        )
        counts["recipe_prompt_count"] = sum(
            1 for row in rows if str(row.get("stage_key")) == "recipe_llm_correct_and_link"
        )

    if str(llm_knowledge_pipeline or "").strip().lower() != "off":
        knowledge_rows = _build_knowledge_preview_rows(
            context=context,
            out_dir=out_dir,
            pipeline_root=pipeline_root,
            surface_pipeline=llm_knowledge_pipeline,
            model_override=codex_farm_model,
            reasoning_effort_override=codex_farm_reasoning_effort,
            context_blocks=codex_farm_knowledge_context_blocks,
        )
        rows.extend(knowledge_rows)
        counts["knowledge_prompt_count"] = len(knowledge_rows)

    if str(line_role_pipeline or "").strip().lower() != "off":
        line_role_rows = _build_line_role_preview_rows(
            context=context,
            out_dir=out_dir,
            pipeline_root=pipeline_root,
            surface_pipeline=line_role_pipeline,
            model_override=codex_farm_model,
            reasoning_effort_override=codex_farm_reasoning_effort,
            atomic_block_splitter=atomic_block_splitter,
        )
        rows.extend(line_role_rows)
        counts["line_role_prompt_count"] = len(line_role_rows)

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

    manifest = {
        "schema_version": "codex_prompt_preview.v1",
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
        "counts": counts,
        "artifacts": {
            "full_prompt_log_jsonl": "prompts/full_prompt_log.jsonl",
            "prompt_request_response_log_txt": "prompts/prompt_request_response_log.txt",
            "prompt_type_samples_from_full_prompt_log_md": (
                "prompts/prompt_type_samples_from_full_prompt_log.md"
            ),
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
    rows: list[dict[str, Any]] = []
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
        input_payload = MergedRecipeRepairInput(
            recipe_id=recipe_id,
            workbook_slug=context.workbook_slug,
            source_hash=context.source_hash,
            canonical_text="\n".join(
                str(block.get("text") or "").strip() for block in included_blocks
            ).strip(),
            evidence_rows=[
                (int(block["index"]), str(block.get("text") or "").strip())
                for block in included_blocks
            ],
            recipe_candidate_hint=_recipe_candidate_hint_from_draft(draft),
            authority_notes=[
                "authoritative_source=recipe_span_blocks",
                "correct_intermediate_recipe_candidate",
                "emit_linkage_payload_for_deterministic_final_assembly",
            ],
        )
        serialized_input = serialize_merged_recipe_repair_input(input_payload)
        input_path = in_dir / f"r{recipe_index}.json"
        input_path.write_text(
            json.dumps(serialized_input, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=recipe_id,
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                input_payload=serialized_input,
                input_path=input_path,
                stage_key="recipe_llm_correct_and_link",
                stage_label="Recipe Correction",
                stage_order=1,
                stage_dir_name="recipe_llm_correct_and_link",
                stage_artifact_stem="recipe_correction",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
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
) -> list[dict[str, Any]]:
    pipeline_assets = _load_pipeline_assets(
        pipeline_root=pipeline_root,
        pipeline_id=_DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    stage_dir = out_dir / "raw" / "llm" / context.workbook_slug / "extract_knowledge_optional"
    in_dir = stage_dir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    nonrecipe_stage_result = build_nonrecipe_stage_result(
        full_blocks=context.full_blocks,
        final_block_labels=context.block_labels,
        recipe_spans=context.recipe_spans,
    )
    build_knowledge_jobs(
        full_blocks=context.full_blocks,
        knowledge_spans=nonrecipe_stage_result.knowledge_spans,
        recipe_spans=context.recipe_spans,
        workbook_slug=context.workbook_slug,
        source_hash=context.source_hash,
        out_dir=in_dir,
        context_blocks=context_blocks,
        job_format=COMPACT_KNOWLEDGE_JOB_FORMAT,
    )
    rows: list[dict[str, Any]] = []
    for input_path in sorted(in_dir.glob("*.json"), key=lambda path: path.name):
        input_payload = _read_json(input_path)
        chunk_payload = _coerce_dict(input_payload.get("chunk"))
        chunk_id = str(
            chunk_payload.get("chunk_id")
            or input_payload.get("chunk_id")
            or input_path.stem
        ).strip()
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=chunk_id,
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                input_payload=input_payload,
                input_path=input_path,
                stage_key="extract_knowledge_optional",
                stage_label="Knowledge Harvest",
                stage_order=4,
                stage_dir_name="extract_knowledge_optional",
                stage_artifact_stem="knowledge",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
            )
        )
    return rows


def _build_line_role_preview_rows(
    *,
    context: ExistingRunPreviewContext,
    out_dir: Path,
    pipeline_root: Path,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
    atomic_block_splitter: str,
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
    unresolved_candidates = _select_line_role_preview_candidates(
        candidates=candidates,
        labeled_line_rows=context.labeled_line_rows,
    )
    for prompt_index, batch_candidates in enumerate(
        _batch(unresolved_candidates, size=40),
        start=1,
    ):
        if not batch_candidates:
            continue
        prompt_text = build_canonical_line_role_prompt(batch_candidates)
        input_payload = {"prompt": prompt_text}
        input_path = in_dir / f"line_role_prompt_{prompt_index or len(rows) + 1:04d}.json"
        input_path.write_text(
            json.dumps(input_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows.append(
            _prompt_row(
                call_id=input_path.stem,
                recipe_id=str(batch_candidates[0].recipe_id or input_path.stem),
                source_file=context.source_file,
                pipeline_assets=pipeline_assets,
                input_payload=input_payload,
                input_path=input_path,
                stage_key="line_role",
                stage_label="Line Role Labeling",
                stage_order=2,
                stage_dir_name="line-role-pipeline",
                stage_artifact_stem="line_role",
                surface_pipeline=surface_pipeline,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
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


def _select_line_role_preview_candidates(
    *,
    candidates: list[AtomicLineCandidate],
    labeled_line_rows: list[dict[str, Any]],
) -> list[AtomicLineCandidate]:
    if not candidates:
        return []
    if not labeled_line_rows:
        return list(candidates)
    unresolved_atomic_indices = {
        int(row.get("atomic_index"))
        for row in labeled_line_rows
        if _line_role_row_needs_codex(row)
    }
    selected = [
        candidate
        for candidate in candidates
        if int(candidate.atomic_index) in unresolved_atomic_indices
    ]
    return selected or list(candidates)


def _line_role_row_needs_codex(row: Mapping[str, Any]) -> bool:
    decided_by = str(row.get("decided_by") or "").strip().lower()
    escalation_reasons = row.get("escalation_reasons") or []
    if decided_by and decided_by != "rule":
        return True
    if isinstance(escalation_reasons, list) and escalation_reasons:
        return True
    return False


def _prompt_row(
    *,
    call_id: str,
    recipe_id: str,
    source_file: str,
    pipeline_assets: dict[str, Any],
    input_payload: dict[str, Any],
    input_path: Path,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    stage_dir_name: str,
    stage_artifact_stem: str,
    surface_pipeline: str,
    model_override: str | None,
    reasoning_effort_override: str | None,
) -> dict[str, Any]:
    template_text = str(pipeline_assets.get("prompt_template_text") or "")
    rendered_prompt = _render_prompt_text(
        template_text=template_text,
        input_text=json.dumps(input_payload, ensure_ascii=False, indent=2),
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
            "INPUT_TEXT": json.dumps(input_payload, ensure_ascii=False, indent=2),
        },
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
        "request_input_file": str(input_path),
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
        "thinking_trace": None,
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


def _recipe_candidate_hint_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    recipe_instructions = draft.get("recipeInstructions")
    if not isinstance(recipe_instructions, list):
        recipe_instructions = []
    return {
        "identifier": draft.get("identifier") or draft.get("@id"),
        "name": draft.get("name"),
        "recipeIngredient": list(draft.get("recipeIngredient") or []),
        "recipeInstructions": list(recipe_instructions),
        "description": draft.get("description"),
        "recipeYield": draft.get("recipeYield"),
    }


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
