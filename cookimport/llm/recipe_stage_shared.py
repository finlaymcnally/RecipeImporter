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
from cookimport.core.models import AuthoritativeRecipeSemantics, ConversionResult, RecipeCandidate, RecipeDraftV1
from cookimport.runs import RECIPE_MANIFEST_FILE_NAME
from cookimport.staging.recipe_ownership import RecipeDivestment
from cookimport.staging.draft_v1 import authoritative_recipe_semantics_to_draft_v1, build_authoritative_recipe_semantics
from .codex_farm_contracts import MergedRecipeRepairInput, MergedRecipeRepairOutput, RecipeCorrectionShardInput, RecipeCorrectionShardOutput, RecipeCorrectionShardRecipeInput, StructuralAuditResult, load_contract_json, serialize_merged_recipe_repair_input, serialize_recipe_correction_shard_input
from .codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from .codex_farm_runner import CodexFarmRunnerError
from .codex_exec_runner import DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, CodexExecLiveSnapshot, CodexExecRunResult, CodexExecRunner, CodexExecSupervisionDecision, SubprocessCodexExecRunner, classify_taskfile_worker_command, detect_taskfile_worker_boundary_violation, format_watchdog_command_reason_detail, format_watchdog_command_loop_reason_detail, is_single_file_workspace_command_drift_policy, should_terminate_workspace_command_loop, summarize_direct_telemetry_rows
from .editable_task_file import TASK_FILE_NAME, build_repair_task_file, build_task_file, load_task_file, validate_edited_task_file, write_task_file
from .phase_worker_runtime import PhaseManifestV1, ShardManifestEntryV1, ShardProposalV1, TaskManifestEntryV1, WorkerAssignmentV1, WorkerExecutionReportV1, resolve_phase_worker_count
from .recipe_workspace_tools import build_recipe_worker_scaffold, recipe_worker_task_paths, validate_recipe_worker_draft
from .recipe_tagging_guide import build_recipe_tagging_guide
from .shard_survivability import attach_observed_telemetry_to_survivability_report, ShardSurvivabilityPreflightError, count_structural_output_tokens, count_tokens_for_model, evaluate_stage_survivability
from .shard_prompt_targets import partition_contiguous_items, resolve_shard_count
from .task_file_guardrails import build_task_file_guardrail, build_worker_session_guardrails, summarize_task_file_guardrails
from .recipe_same_session_handoff import RECIPE_SAME_SESSION_STATE_ENV, initialize_recipe_same_session_state
from .single_file_worker_commands import build_single_file_worker_surface
from .taskfile_progress import decorate_active_worker_label, summarize_taskfile_health
from .worker_hint_sidecars import preview_text, write_worker_hint_markdown
from .recipe_stage.task_file_contract import _RecipeTaskPlan, _build_recipe_task_file_unit, _recipe_task_file_helper_commands, _recipe_task_file_answer_schema, _build_recipe_task_file, _recipe_artifact_filename, _build_recipe_task_runtime_manifest_entry, _recipe_task_result_path, _write_recipe_task_payload, _build_recipe_task_file_worker_prompt
from .recipe_stage.worker_io import _write_jsonl, _serialize_compact_prompt_json, _write_worker_input, _relative_path, _recipe_same_session_state_path, _recipe_task_file_useful_progress, _recipe_hard_boundary_failure, _recipe_retryable_runner_exception_reason, _recipe_catastrophic_run_result_reason, _should_attempt_recipe_fresh_worker_replacement, _should_attempt_recipe_fresh_session_retry, _write_recipe_worker_hint, _distribute_recipe_session_value, _build_recipe_workspace_task_runner_payload, _build_recipe_workspace_session_runner_payload, _aggregate_recipe_worker_runner_payload, _render_events_jsonl
logger = logging.getLogger(__name__)
SINGLE_CORRECTION_RECIPE_PIPELINE_ID = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
SINGLE_CORRECTION_STAGE_PIPELINE_ID = 'recipe.correction.compact.v1'
_CODEX_FARM_RECIPE_MODE_ENV = 'COOKIMPORT_CODEX_FARM_RECIPE_MODE'
_ELIGIBILITY_INGREDIENT_LEAD_RE = re.compile('^\\s*(?:\\d+\\s+\\d+/\\d+|\\d+/\\d+|\\d+(?:\\.\\d+)?)\\s+[A-Za-z]')
_ELIGIBILITY_INGREDIENT_UNIT_RE = re.compile('\\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|g|kg|ml|l|cloves?|sticks?|cans?|pinch)\\b', re.IGNORECASE)
_ELIGIBILITY_INSTRUCTION_VERB_RE = re.compile('^\\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|toast|transfer|whisk)\\b', re.IGNORECASE)
_ELIGIBILITY_YIELD_PREFIX_RE = re.compile('^\\s*(?:makes|serves?|servings|yields?)\\b', re.IGNORECASE)
_ELIGIBILITY_TITLE_LIKE_RE = re.compile("^[A-Z][A-Z0-9'/:,\\- ]{2,}$")
_AUDIT_PLACEHOLDER_TITLES = {'recipe', 'recipe title', 'recipe name', 'title unavailable', 'unknown recipe', 'untitled recipe'}
_AUDIT_PLACEHOLDER_STEP_TEXTS = {'', 'n a', 'na', 'not provided', 'not available', 'no instruction provided', 'see original recipe for details', 'see original recipe', 'refer to original recipe', 'follow original recipe'}
_ELIGIBILITY_CHAPTER_PAGE_HINT_KEYS = ('chapter_page_hint', 'chapter_page_hints', 'chapter_type', 'chapter_kind', 'section_type', 'section_kind', 'page_type', 'page_kind', 'page_region', 'layout_region', 'layout_type')
_ELIGIBILITY_TAG_LIST_KEYS = ('heuristic_tags', 'reasoning_tags', 'tags')
_ELIGIBILITY_CHAPTER_PAGE_NEGATIVE_HINT_TOKENS = ('chapter', 'front_matter', 'preface', 'introduction', 'table_of_contents', 'toc', 'index', 'glossary', 'appendix', 'essay', 'narrative', 'prose', 'reference', 'sidebar', 'table', 'chart', 'mixed_content')
_RECIPE_GUARDRAIL_REPORT_SCHEMA_VERSION = 'recipe_codex_guardrail_report.v1'
_STRICT_JSON_WATCHDOG_POLICY = 'strict_json_no_tools_v1'
_RECIPE_SAME_SESSION_STATE_FILE_NAME = 'recipe_same_session_state.json'

def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, 'value', value)
    cleaned = str(resolved).strip()
    return cleaned or None

@dataclass
class CodexFarmApplyResult:
    updated_conversion_result: ConversionResult
    authoritative_recipe_payloads_by_recipe_id: dict[str, AuthoritativeRecipeSemantics]
    llm_report: dict[str, Any]
    llm_raw_dir: Path
    recipe_divestments: list[RecipeDivestment] = field(default_factory=list)

@dataclass
class _RecipeState:
    recipe: RecipeCandidate
    recipe_id: str
    bundle_name: str
    heuristic_start: int | None
    heuristic_end: int | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    single_correction_status: str = 'pending'
    final_assembly_status: str = 'pending'
    correction_output_status: str | None = None
    correction_output_reason: str | None = None
    structural_status: str = 'ok'
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

def _json_bundle_filenames(path: Path) -> list[str]:
    return sorted((child.name for child in path.glob('*.json') if child.is_file()))

def _recipe_index_from_bundle_name(bundle_name: str) -> int:
    match = re.match('r(\\d+)', str(bundle_name or ''))
    if match is None:
        return 0
    return int(match.group(1))

def _build_blocks_for_recipe_state(*, state: _RecipeState, full_blocks_by_index: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
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

def _build_recipe_boundary_context_rows(*, state: _RecipeState, full_blocks_by_index: Mapping[int, Mapping[str, Any]], side: str, limit: int=2) -> tuple[tuple[int, str], ...]:
    start = _coerce_int(state.heuristic_start)
    end = _coerce_int(state.heuristic_end)
    if start is None or end is None:
        return ()
    normalized_limit = max(0, int(limit))
    if normalized_limit <= 0:
        return ()
    if side == 'before':
        indices = range(start - normalized_limit, start)
    else:
        indices = range(end + 1, end + normalized_limit + 1)
    rows: list[tuple[int, str]] = []
    for block_index in indices:
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        rows.append((int(block_index), str(block.get('text') or '').strip()))
    return tuple(rows)

def _build_recipe_correction_input(*, state: _RecipeState, workbook_slug: str, source_hash: str, included_blocks: list[dict[str, Any]]) -> MergedRecipeRepairInput:
    recipe_candidate_hint = state.recipe.model_dump(mode='json', by_alias=True, exclude_none=True)
    recipe_candidate_hint.pop('provenance', None)
    compact_recipe_candidate_hint = _compact_recipe_candidate_hint(recipe_candidate_hint)
    canonical_text = '\n'.join((str(block.get('text') or '').strip() for block in included_blocks)).strip()
    return MergedRecipeRepairInput(recipe_id=state.recipe_id, workbook_slug=workbook_slug, source_hash=source_hash, canonical_text=canonical_text, evidence_rows=[(int(block.get('index', 0)), str(block.get('text') or '').strip()) for block in included_blocks], recipe_candidate_hint=compact_recipe_candidate_hint, tagging_guide=build_recipe_tagging_guide(recipe_text=canonical_text, recipe_candidate_hint=compact_recipe_candidate_hint), authority_notes=['authoritative_source=recipe_span_blocks', 'correct_intermediate_recipe_candidate', 'emit_linkage_payload_for_deterministic_final_assembly'])

def _build_recipe_shard_recipe_input(*, correction_input: MergedRecipeRepairInput, candidate_quality_hint: Mapping[str, Any], warnings: Sequence[str]) -> RecipeCorrectionShardRecipeInput:
    return RecipeCorrectionShardRecipeInput(recipe_id=correction_input.recipe_id, canonical_text=correction_input.canonical_text, evidence_rows=list(correction_input.evidence_rows), recipe_candidate_hint=dict(correction_input.recipe_candidate_hint), candidate_quality_hint=dict(candidate_quality_hint or {}), warnings=list(warnings))

def _build_prepared_recipe_input(*, state: _RecipeState, workbook_slug: str, source_hash: str, included_blocks: list[dict[str, Any]], full_blocks_by_index: Mapping[int, Mapping[str, Any]]) -> _PreparedRecipeInput:
    correction_input = _build_recipe_correction_input(state=state, workbook_slug=workbook_slug, source_hash=source_hash, included_blocks=included_blocks)
    evidence_refs = tuple((str(block.get('block_id') or f'b{int(block.get('index', 0))}') for block in included_blocks))
    block_indices = tuple((int(block.get('index', 0)) for block in included_blocks))
    candidate_quality_hint = _build_recipe_candidate_quality_hint(included_blocks=included_blocks, recipe_candidate_hint=correction_input.recipe_candidate_hint)
    pre_context_rows = _build_recipe_boundary_context_rows(state=state, full_blocks_by_index=full_blocks_by_index, side='before')
    post_context_rows = _build_recipe_boundary_context_rows(state=state, full_blocks_by_index=full_blocks_by_index, side='after')
    return _PreparedRecipeInput(state=state, correction_input=correction_input, candidate_quality_hint=candidate_quality_hint, evidence_refs=evidence_refs, block_indices=block_indices, pre_context_rows=pre_context_rows, post_context_rows=post_context_rows)

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

def _recipe_worker_count(run_settings: RunSettings, *, shard_count: int) -> int:
    return resolve_phase_worker_count(requested_worker_count=_requested_recipe_worker_count(run_settings), shard_count=shard_count)

def _build_recipe_shard_plan(*, shard_index: int, shard_prepared_inputs: Sequence[_PreparedRecipeInput]) -> _RecipeShardPlan | None:
    shard_prepared_inputs_tuple = tuple(shard_prepared_inputs)
    if not shard_prepared_inputs_tuple:
        return None
    first_state = shard_prepared_inputs_tuple[0].state
    last_state = shard_prepared_inputs_tuple[-1].state
    first_recipe_index = _recipe_index_from_bundle_name(first_state.bundle_name)
    last_recipe_index = _recipe_index_from_bundle_name(last_state.bundle_name)
    shard_id = f'recipe-shard-{shard_index:04d}-r{first_recipe_index:04d}-r{last_recipe_index:04d}'
    shard_recipe_ids = tuple((prepared.state.recipe_id for prepared in shard_prepared_inputs_tuple))
    tagging_guide = dict(shard_prepared_inputs_tuple[0].correction_input.tagging_guide or {}) if len(shard_prepared_inputs_tuple) == 1 else build_recipe_tagging_guide()
    shard_input = RecipeCorrectionShardInput(shard_id=shard_id, owned_recipe_ids=list(shard_recipe_ids), recipes=[_build_recipe_shard_recipe_input(correction_input=prepared.correction_input, candidate_quality_hint=prepared.candidate_quality_hint, warnings=prepared.state.warnings) for prepared in shard_prepared_inputs_tuple], tagging_guide=tagging_guide)
    evidence_refs = tuple((ref for prepared in shard_prepared_inputs_tuple for ref in prepared.evidence_refs))
    return _RecipeShardPlan(shard_id=shard_id, states=tuple((prepared.state for prepared in shard_prepared_inputs_tuple)), prepared_inputs=shard_prepared_inputs_tuple, evidence_refs=evidence_refs, shard_input=shard_input)

def _build_recipe_shard_plans(*, prepared_inputs: Sequence[_PreparedRecipeInput], run_settings: RunSettings) -> list[_RecipeShardPlan]:
    requested_shard_count = _resolve_recipe_shard_count(total_items=len(prepared_inputs), run_settings=run_settings)
    plans: list[_RecipeShardPlan] = []
    for shard_index, shard_prepared_inputs_list in enumerate(partition_contiguous_items(prepared_inputs, shard_count=requested_shard_count)):
        plan = _build_recipe_shard_plan(shard_index=shard_index, shard_prepared_inputs=shard_prepared_inputs_list)
        if plan is not None:
            plans.append(plan)
    return plans

def _resolve_recipe_shard_count(*, total_items: int, run_settings: RunSettings) -> int:
    return resolve_shard_count(total_items=total_items, prompt_target_count=run_settings.recipe_prompt_target_count, items_per_shard=None, default_items_per_shard=1)

def _compact_recipe_candidate_hint(recipe_candidate_hint: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(recipe_candidate_hint or {})
    compact: dict[str, Any] = {}
    name = str(payload.get('name') or '').strip()
    if name:
        compact['n'] = name
    ingredients = [str(item).strip() for item in payload.get('recipeIngredient') or [] if str(item).strip()]
    if ingredients:
        compact['i'] = ingredients
    steps = _compact_recipe_step_hints(payload.get('recipeInstructions') or [])
    if steps:
        compact['s'] = steps
    description = str(payload.get('description') or '').strip()
    if description:
        compact['d'] = description
    recipe_yield = str(payload.get('recipeYield') or '').strip()
    if recipe_yield:
        compact['y'] = recipe_yield
    tags = [str(item).strip() for item in payload.get('tags') or [] if str(item).strip()]
    if tags:
        compact['g'] = tags
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
        return ''
    if isinstance(value, str):
        return str(value).strip()
    if isinstance(value, Mapping):
        for key in ('text', 'name'):
            rendered = str(value.get(key) or '').strip()
            if rendered:
                return rendered
        return ''
    return ''

def _build_recipe_candidate_quality_hint(*, included_blocks: Sequence[Mapping[str, Any]], recipe_candidate_hint: Mapping[str, Any]) -> dict[str, Any]:
    evidence_lines = [str(block.get('text') or '').strip() for block in included_blocks if str(block.get('text') or '').strip()]
    evidence_row_count = len(evidence_lines)
    evidence_ingredient_count = sum((1 for line in evidence_lines if _looks_like_ingredient_line(line)))
    evidence_step_count = sum((1 for line in evidence_lines if _looks_like_step_line(line)))
    hint_ingredient_count = sum((1 for item in recipe_candidate_hint.get('i') or [] if str(item or '').strip()))
    hint_step_count = sum((1 for item in recipe_candidate_hint.get('s') or [] if str(item or '').strip()))
    title_hint = str(recipe_candidate_hint.get('n') or '').strip()
    suspicion_flags: list[str] = []
    if evidence_row_count <= 2:
        suspicion_flags.append('short_span')
    if evidence_ingredient_count == 0:
        suspicion_flags.append('source_no_ingredient_lines')
    if evidence_step_count == 0:
        suspicion_flags.append('source_no_instruction_lines')
    if hint_ingredient_count == 0:
        suspicion_flags.append('hint_no_ingredients')
    if hint_step_count == 0:
        suspicion_flags.append('hint_no_steps')
    if not title_hint:
        suspicion_flags.append('hint_no_title')
    elif _ELIGIBILITY_TITLE_LIKE_RE.fullmatch(title_hint) and evidence_ingredient_count == 0 and (evidence_step_count == 0):
        suspicion_flags.append('title_looks_sectional')
    return {'e': evidence_row_count, 'ei': evidence_ingredient_count, 'es': evidence_step_count, 'hi': hint_ingredient_count, 'hs': hint_step_count, 'f': suspicion_flags}

def _looks_like_ingredient_line(text: str) -> bool:
    rendered = str(text or '').strip()
    if not rendered:
        return False
    if _ELIGIBILITY_YIELD_PREFIX_RE.search(rendered):
        return False
    return bool(_ELIGIBILITY_INGREDIENT_LEAD_RE.search(rendered) or _ELIGIBILITY_INGREDIENT_UNIT_RE.search(rendered))

def _looks_like_step_line(text: str) -> bool:
    rendered = str(text or '').strip()
    if not rendered:
        return False
    return bool(_ELIGIBILITY_INSTRUCTION_VERB_RE.search(rendered))

def _corrected_candidate_from_output(*, state: _RecipeState, output: MergedRecipeRepairOutput) -> RecipeCandidate:
    selected_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in [entry.label for entry in output.selected_tags]:
        rendered = str(tag or '').strip()
        if not rendered or rendered in seen_tags:
            continue
        seen_tags.add(rendered)
        selected_tags.append(rendered)
    return state.recipe.model_copy(update={'name': output.canonical_recipe.title, 'ingredients': list(output.canonical_recipe.ingredients), 'instructions': list(output.canonical_recipe.steps), 'description': output.canonical_recipe.description, 'recipe_yield': output.canonical_recipe.recipe_yield, 'tags': selected_tags}, deep=True)

def _build_recipe_correction_audit(*, state: _RecipeState, correction_input: MergedRecipeRepairInput, correction_output: MergedRecipeRepairOutput, corrected_candidate: RecipeCandidate | None, final_payload: dict[str, Any] | None, final_assembly_status: str, structural_audit: StructuralAuditResult, mapping_status: str | None, mapping_reason: str | None) -> dict[str, Any]:
    canonical_recipe = correction_output.canonical_recipe
    final_recipe_authority_eligibility, final_recipe_authority_eligibility_reason = _classify_recipe_authority_eligibility(correction_output.repair_status)
    final_recipe_authority_status, final_recipe_authority_reason = _classify_final_recipe_authority_status(correction_output_status=correction_output.repair_status, final_assembly_status=final_assembly_status)
    return {'schema_version': 'recipe_correction_audit.v1', 'recipe_id': state.recipe_id, 'pipeline': SINGLE_CORRECTION_RECIPE_PIPELINE_ID, 'stage_pipeline_id': SINGLE_CORRECTION_STAGE_PIPELINE_ID, 'input': {'block_count': len(correction_input.evidence_rows), 'canonical_char_count': len(correction_input.canonical_text), 'authority_notes': list(correction_input.authority_notes), 'payload': serialize_merged_recipe_repair_input(correction_input)}, 'output': {'repair_status': correction_output.repair_status, 'status_reason': correction_output.status_reason, 'title': canonical_recipe.title if canonical_recipe is not None else None, 'ingredient_count': len(canonical_recipe.ingredients) if canonical_recipe is not None else 0, 'step_count': len(canonical_recipe.steps) if canonical_recipe is not None else 0, 'selected_tags': [{'category': tag.category, 'label': tag.label, 'confidence': tag.confidence} for tag in correction_output.selected_tags], 'warning_count': len(correction_output.warnings), 'ingredient_step_mapping': correction_output.ingredient_step_mapping, 'ingredient_step_mapping_reason': correction_output.ingredient_step_mapping_reason, 'payload': _serialize_recipe_correction_output(correction_output)}, 'task_outcome': {'status': correction_output.repair_status, 'reason': correction_output.status_reason, 'final_recipe_authority_eligibility': final_recipe_authority_eligibility, 'final_recipe_authority_reason': final_recipe_authority_eligibility_reason, 'valid_task_outcome': True}, 'deterministic_final_assembly': {'status': final_assembly_status, 'corrected_candidate_title': corrected_candidate.name if corrected_candidate is not None else None, 'final_step_count': len(list((final_payload or {}).get('steps') or [])), 'mapping_status': mapping_status, 'mapping_reason': mapping_reason}, 'final_recipe_authority': {'status': final_recipe_authority_status, 'reason': final_recipe_authority_reason}, 'structural_audit': structural_audit.to_dict()}

def _serialize_recipe_correction_output(output: MergedRecipeRepairOutput) -> dict[str, Any]:
    return output.model_dump(mode='json', by_alias=True)

def _serialize_recipe_correction_shard_output(output: RecipeCorrectionShardOutput) -> dict[str, Any]:
    return output.model_dump(mode='json', by_alias=True)

def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
_RECIPE_COMPACT_TOP_LEVEL_KEYS = frozenset({'v', 'sid', 'r'})
_RECIPE_COMPACT_RESULT_KEYS = frozenset({'v', 'rid', 'st', 'sr', 'cr', 'm', 'mr', 'db', 'g', 'w'})
_RECIPE_COMPACT_CANONICAL_KEYS = frozenset({'t', 'i', 's', 'd', 'y'})
_RECIPE_COMPACT_MAPPING_KEYS = frozenset({'i', 's'})
_RECIPE_COMPACT_TAG_KEYS = frozenset({'c', 'l', 'f'})
_RECIPE_LEGACY_KEY_SUGGESTIONS = {'bundle_version': 'v', 'shard_id': 'sid', 'results': 'r', 'recipes': 'r', 'recipe_id': 'rid', 'repair_status': 'st', 'status_reason': 'sr', 'canonical_recipe': 'cr', 'ingredient_step_mapping': 'm', 'ingredient_step_mapping_reason': 'mr', 'divested_block_indices': 'db', 'selected_tags': 'g', 'warnings': 'w', 'not_a_recipe': 'st=not_a_recipe', 'fragmentary': 'st=fragmentary', 'notes': 'sr or w', 'title': 'cr.t', 'ingredients': 'cr.i', 'steps': 'cr.s', 'description': 'cr.d', 'recipeYield': 'cr.y', 'recipe_yield': 'cr.y', 'category': 'c', 'label': 'l', 'confidence': 'f'}

def _recipe_compact_contract_error(*, path: str, key: str) -> str:
    suggestion = _RECIPE_LEGACY_KEY_SUGGESTIONS.get(key)
    if suggestion:
        return f'invalid_shard_output:{path} legacy key `{key}` is invalid for recipe workspace output; use `{suggestion}`'
    return f'invalid_shard_output:{path} unexpected key `{key}` is not permitted'

def _validate_recipe_compact_output_keys(payload: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    for key in sorted((str(name) for name in payload.keys() if str(name) not in _RECIPE_COMPACT_TOP_LEVEL_KEYS)):
        errors.append(_recipe_compact_contract_error(path='root', key=key))
    rows = payload.get('r')
    if isinstance(rows, list):
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            row_path = f'r[{row_index}]'
            for key in sorted((str(name) for name in row.keys() if str(name) not in _RECIPE_COMPACT_RESULT_KEYS)):
                errors.append(_recipe_compact_contract_error(path=row_path, key=key))
            canonical_recipe = row.get('cr')
            if isinstance(canonical_recipe, Mapping):
                canonical_path = f'{row_path}.cr'
                for key in sorted((str(name) for name in canonical_recipe.keys() if str(name) not in _RECIPE_COMPACT_CANONICAL_KEYS)):
                    errors.append(_recipe_compact_contract_error(path=canonical_path, key=key))
            mapping_rows = row.get('m')
            if isinstance(mapping_rows, list):
                for mapping_index, mapping_row in enumerate(mapping_rows):
                    if not isinstance(mapping_row, Mapping):
                        continue
                    mapping_path = f'{row_path}.m[{mapping_index}]'
                    for key in sorted((str(name) for name in mapping_row.keys() if str(name) not in _RECIPE_COMPACT_MAPPING_KEYS)):
                        errors.append(_recipe_compact_contract_error(path=mapping_path, key=key))
            tag_rows = row.get('g')
            if isinstance(tag_rows, list):
                for tag_index, tag_row in enumerate(tag_rows):
                    if not isinstance(tag_row, Mapping):
                        continue
                    tag_path = f'{row_path}.g[{tag_index}]'
                    for key in sorted((str(name) for name in tag_row.keys() if str(name) not in _RECIPE_COMPACT_TAG_KEYS)):
                        errors.append(_recipe_compact_contract_error(path=tag_path, key=key))
    return tuple(errors)

def _validate_recipe_shard_output(shard: ShardManifestEntryV1, payload: dict[str, Any]) -> tuple[bool, Sequence[str], Mapping[str, Any] | None]:
    compact_contract_errors = _validate_recipe_compact_output_keys(payload)
    if compact_contract_errors:
        return (False, compact_contract_errors, {'contract': 'recipe.correction.compact.v1', 'contract_errors': list(compact_contract_errors)})
    try:
        shard_output = RecipeCorrectionShardOutput.model_validate(payload)
    except Exception as exc:
        return (False, (f'invalid_shard_output:{exc}',), None)
    validation_errors: list[str] = []
    if shard_output.shard_id != shard.shard_id:
        validation_errors.append('shard_id_mismatch')
    expected_ids = list(shard.owned_ids)
    actual_ids = [recipe.recipe_id for recipe in shard_output.recipes]
    duplicate_ids = sorted({recipe_id for recipe_id in actual_ids if actual_ids.count(recipe_id) > 1})
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    unexpected_ids = sorted(set(actual_ids) - set(expected_ids))
    if duplicate_ids:
        validation_errors.append('duplicate_recipe_ids')
    if missing_ids:
        validation_errors.append('missing_recipe_ids')
    if unexpected_ids:
        validation_errors.append('unexpected_recipe_ids')
    metadata = {'owned_recipe_ids': expected_ids, 'actual_recipe_ids': actual_ids, 'duplicate_recipe_ids': duplicate_ids, 'missing_recipe_ids': missing_ids, 'unexpected_recipe_ids': unexpected_ids, 'recipe_count': len(actual_ids)}
    return (not validation_errors, tuple(validation_errors), metadata)

def _evaluate_recipe_response(*, shard: ShardManifestEntryV1, response_text: str | None) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = 'validated'
    cleaned_response_text = str(response_text or '').strip()
    if not cleaned_response_text:
        return (None, ('missing_output_file',), {}, 'missing_output')
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return (None, ('response_json_invalid',), {'parse_error': str(exc)}, 'invalid')
    if not isinstance(parsed_payload, dict):
        return (None, ('response_not_json_object',), {'response_type': type(parsed_payload).__name__}, 'invalid')
    payload = parsed_payload
    valid, validation_errors, validation_metadata = _validate_recipe_shard_output(shard, parsed_payload)
    if valid:
        payload = _serialize_recipe_correction_shard_output(RecipeCorrectionShardOutput.model_validate(parsed_payload))
    else:
        payload = None
    proposal_status = 'validated' if valid else 'invalid'
    return (payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status)

def _preflight_recipe_shard(shard: ShardManifestEntryV1) -> dict[str, Any] | None:
    payload = _coerce_mapping_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    recipe_rows = payload.get('r')
    if not owned_ids:
        return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard has no owned recipe ids'}
    if not isinstance(recipe_rows, list) or not recipe_rows:
        return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard has no model-facing recipes'}
    payload_shard_id = str(payload.get('sid') or '').strip()
    if payload_shard_id and payload_shard_id != shard.shard_id:
        return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard input `sid` does not match the manifest shard id'}
    recipe_ids: list[str] = []
    for recipe_row in recipe_rows:
        if not isinstance(recipe_row, Mapping):
            return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard contains a non-object recipe payload'}
        recipe_id = str(recipe_row.get('rid') or '').strip()
        if not recipe_id:
            return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard contains a recipe without `rid`'}
        recipe_ids.append(recipe_id)
    if sorted(recipe_ids) != sorted(owned_ids):
        return {'reason_code': 'preflight_invalid_shard_payload', 'reason_detail': 'recipe shard owned ids do not match model-facing recipe ids'}
    return None

def _build_preflight_rejected_run_result(*, prompt_text: str, output_schema_path: Path | None, working_dir: Path, reason_code: str, reason_detail: str) -> CodexExecRunResult:
    timestamp = _format_utc_now()
    return CodexExecRunResult(command=[], subprocess_exit_code=0, output_schema_path=str(output_schema_path) if output_schema_path is not None else None, prompt_text=prompt_text, response_text=None, turn_failed_message=reason_detail, events=(), usage={'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0, 'reasoning_tokens': 0}, source_working_dir=str(working_dir), execution_working_dir=None, execution_agents_path=None, duration_ms=0, started_at_utc=timestamp, finished_at_utc=timestamp, supervision_state='preflight_rejected', supervision_reason_code=reason_code, supervision_reason_detail=reason_detail, supervision_retryable=False)

def _build_recipe_watchdog_callback(*, live_status_path: Path | None=None, live_status_paths: Sequence[Path] | None=None, shard_id: str | None=None, watchdog_policy: str=_STRICT_JSON_WATCHDOG_POLICY, stage_label: str='strict JSON stage', allow_workspace_commands: bool=False, execution_workspace_root: Path | None=None) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend((Path(path) for path in live_status_paths))
    persistent_warning_codes: list[str] = []
    persistent_warning_details: list[str] = []
    last_single_file_command_count = 0

    def _record_warning(code: str, detail: str) -> None:
        if code not in persistent_warning_codes:
            persistent_warning_codes.append(code)
        if detail and detail not in persistent_warning_details:
            persistent_warning_details.append(detail)

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        nonlocal last_single_file_command_count
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        allowed_absolute_roots = [path for path in (execution_workspace_root, snapshot.source_working_dir, snapshot.execution_working_dir) if path is not None and str(path).strip()] or None
        last_command_verdict = classify_taskfile_worker_command(snapshot.last_command, allowed_absolute_roots=allowed_absolute_roots, single_file_worker_policy=allow_workspace_commands, single_file_stage_key='recipe_refine')
        last_command_boundary_violation = detect_taskfile_worker_boundary_violation(snapshot.last_command, allowed_absolute_roots=allowed_absolute_roots)
        if snapshot.command_execution_count > 0:
            if allow_workspace_commands:
                if last_command_boundary_violation is None:
                    command_execution_tolerated = True
                else:
                    decision = CodexExecSupervisionDecision.terminate(reason_code='boundary_command_execution_forbidden', reason_detail=format_watchdog_command_reason_detail(stage_label=stage_label, last_command=snapshot.last_command), retryable=False, supervision_state='boundary_interrupted')
                new_command_observed = int(snapshot.command_execution_count or 0) > last_single_file_command_count
                if new_command_observed:
                    last_single_file_command_count = int(snapshot.command_execution_count or 0)
                if decision is None and new_command_observed and is_single_file_workspace_command_drift_policy(last_command_verdict.policy):
                    drift_detail = str(last_command_verdict.reason or '').strip() or 'single-file worker drifted off the helper-first task-file contract'
                    _record_warning('single_file_shell_drift', drift_detail)
                if decision is None and should_terminate_workspace_command_loop(snapshot=snapshot):
                    _record_warning('command_loop_without_output', format_watchdog_command_loop_reason_detail(stage_label=stage_label, snapshot=snapshot))
            else:
                decision = CodexExecSupervisionDecision.terminate(reason_code='watchdog_command_execution_forbidden', reason_detail=format_watchdog_command_reason_detail(stage_label=stage_label, last_command=snapshot.last_command), retryable=False)
        elif snapshot.reasoning_item_count >= 2 and (not snapshot.has_final_agent_message):
            if allow_workspace_commands:
                _record_warning('reasoning_without_output', f'{stage_label} emitted repeated reasoning without a final answer')
            else:
                decision = CodexExecSupervisionDecision.terminate(reason_code='watchdog_reasoning_without_output', reason_detail=f'{stage_label} emitted repeated reasoning without a final answer', retryable=allow_workspace_commands)
        status_payload = {'state': str(decision.supervision_state or 'boundary_interrupted').strip() if isinstance(decision, CodexExecSupervisionDecision) and decision.action == 'terminate' else 'running_with_warnings' if persistent_warning_codes else 'running', 'elapsed_seconds': round(snapshot.elapsed_seconds, 3), 'last_event_seconds_ago': round(snapshot.last_event_seconds_ago, 3) if snapshot.last_event_seconds_ago is not None else None, 'event_count': snapshot.event_count, 'command_execution_count': snapshot.command_execution_count, 'command_execution_tolerated': command_execution_tolerated, 'last_command_policy': last_command_verdict.policy, 'last_command_policy_allowed': last_command_verdict.allowed, 'last_command_policy_reason': last_command_verdict.reason, 'last_command_boundary_violation_detected': last_command_boundary_violation is not None, 'last_command_boundary_policy': last_command_boundary_violation.policy if last_command_boundary_violation is not None else None, 'last_command_boundary_reason': last_command_boundary_violation.reason if last_command_boundary_violation is not None else None, 'reasoning_item_count': snapshot.reasoning_item_count, 'last_command': snapshot.last_command, 'last_command_repeat_count': snapshot.last_command_repeat_count, 'live_activity_summary': snapshot.live_activity_summary, 'has_final_agent_message': snapshot.has_final_agent_message, 'timeout_seconds': snapshot.timeout_seconds, 'source_working_dir': snapshot.source_working_dir, 'execution_working_dir': snapshot.execution_working_dir, 'watchdog_policy': watchdog_policy, 'shard_id': shard_id, 'warning_codes': list(persistent_warning_codes), 'warning_details': list(persistent_warning_details), 'warning_count': len(persistent_warning_codes), 'reason_code': decision.reason_code if decision is not None else None, 'reason_detail': decision.reason_detail if decision is not None else None, 'retryable': decision.retryable if decision is not None else False}
        for path in target_paths:
            _write_live_status(path, status_payload)
        return decision
    return _callback

def _finalize_live_status(live_status_path: Path, *, run_result: CodexExecRunResult, watchdog_policy: str=_STRICT_JSON_WATCHDOG_POLICY) -> None:
    existing_payload = _load_live_status(live_status_path)
    state = run_result.supervision_state or 'completed'
    if state == 'completed' and existing_payload.get('warning_count'):
        state = 'completed_with_warnings'
    _write_live_status(live_status_path, {'state': state, 'reason_code': run_result.supervision_reason_code, 'reason_detail': run_result.supervision_reason_detail, 'retryable': run_result.supervision_retryable, 'duration_ms': run_result.duration_ms, 'started_at_utc': run_result.started_at_utc, 'finished_at_utc': run_result.finished_at_utc, 'watchdog_policy': watchdog_policy, 'warning_codes': list(existing_payload.get('warning_codes') or []), 'warning_details': list(existing_payload.get('warning_details') or []), 'warning_count': int(existing_payload.get('warning_count') or 0)})

def _write_live_status(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(dict(payload), path)

def _load_live_status(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}

def _failure_reason_from_run_result(*, run_result: CodexExecRunResult, proposal_status: str) -> str:
    if str(run_result.supervision_reason_code or '').strip():
        return str(run_result.supervision_reason_code)
    if str(run_result.supervision_state or '').strip() in {'preflight_rejected', 'watchdog_killed'}:
        return str(run_result.supervision_state)
    return 'proposal_validation_failed' if proposal_status == 'invalid' else 'missing_output_file'

def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def _final_recipe_supervision_fields(*, run_result: CodexExecRunResult, proposal_status: str, repair_status: str='not_attempted') -> dict[str, Any]:
    raw_state = str(run_result.supervision_state or 'completed').strip() or 'completed'
    raw_reason_code = str(run_result.supervision_reason_code or '').strip() or None
    raw_reason_detail = str(run_result.supervision_reason_detail or '').strip() or None
    final_state = raw_state
    final_reason_code = raw_reason_code
    final_reason_detail = raw_reason_detail
    finalization_path = 'raw_supervision'
    if raw_state == 'watchdog_killed' and proposal_status == 'validated':
        final_state = 'completed'
        if repair_status == 'repaired':
            final_reason_code = 'recipe_repair_recovered'
            final_reason_detail = 'recipe shard validated after follow-up repair'
            finalization_path = 'repair_recovered'
        else:
            final_reason_code = 'workspace_outputs_recovered'
            final_reason_detail = 'recipe shard validated despite the raw workspace session stop'
            finalization_path = 'validated_after_watchdog'
    return {'raw_supervision_state': raw_state, 'raw_supervision_reason_code': raw_reason_code, 'raw_supervision_reason_detail': raw_reason_detail, 'final_supervision_state': final_state, 'final_supervision_reason_code': final_reason_code, 'final_supervision_reason_detail': final_reason_detail, 'finalization_path': finalization_path}

def _aggregate_recipe_phase_process_run(*, phase_manifest: Mapping[str, Any], worker_reports: Sequence[Mapping[str, Any]], promotion_report: Mapping[str, Any], telemetry: Mapping[str, Any]) -> dict[str, Any]:
    worker_runs = [dict(report.get('runner_result') or {}) for report in worker_reports if isinstance(report.get('runner_result'), dict)]
    runtime_mode_audits = [dict(report.get('runtime_mode_audit') or {}) for report in worker_reports if isinstance(report.get('runtime_mode_audit'), dict)]
    pipeline_id = str(phase_manifest.get('pipeline_id') or SINGLE_CORRECTION_STAGE_PIPELINE_ID)
    return {'pipeline_id': pipeline_id, 'runtime_mode': str(phase_manifest.get('runtime_mode') or DIRECT_CODEX_EXEC_RUNTIME_MODE_V1), 'worker_run_count': len(worker_runs), 'worker_runs': worker_runs, 'runtime_mode_audits': runtime_mode_audits, 'phase_manifest': dict(phase_manifest), 'promotion_report': dict(promotion_report), 'telemetry_report': dict(telemetry)}

def _collect_recipe_locally_finalized_skip_rows(proposals: Sequence[ShardProposalV1]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    seen_recipe_ids: set[str] = set()
    for proposal in proposals:
        if proposal.status != 'validated' or not isinstance(proposal.payload, Mapping):
            continue
        proposal_metadata = _coerce_dict(proposal.metadata)
        aggregation_metadata = _coerce_dict(proposal_metadata.get('task_aggregation'))
        task_id_by_recipe_id = {str(recipe_id).strip(): str(task_id).strip() for recipe_id, task_id in _coerce_dict(aggregation_metadata.get('task_id_by_recipe_id')).items() if str(recipe_id).strip() and str(task_id).strip()}
        task_statuses = {str(task_id).strip(): _coerce_dict(status_payload) for task_id, status_payload in _coerce_dict(proposal_metadata.get('task_status_by_task_id')).items() if str(task_id).strip()}
        recipe_rows = {str(row.get('rid') or '').strip(): row for row in proposal.payload.get('r') or [] if isinstance(row, Mapping) and str(row.get('rid') or '').strip()}
        for recipe_id, task_id in sorted(task_id_by_recipe_id.items()):
            if recipe_id in seen_recipe_ids:
                continue
            task_status = task_statuses.get(task_id, {})
            dispatch = str(task_status.get('llm_dispatch') or '').strip()
            if dispatch != 'handled_locally_skip_llm':
                continue
            recipe_row = recipe_rows.get(recipe_id, {})
            rows.append({'recipe_id': recipe_id, 'task_id': task_id, 'shard_id': proposal.shard_id, 'worker_id': proposal.worker_id, 'repair_status': str(recipe_row.get('st') or '').strip() or None, 'status_reason': str(recipe_row.get('sr') or '').strip() or None, 'task_status': str(task_status.get('task_status') or '').strip() or None, 'llm_dispatch': dispatch, 'llm_dispatch_reason': str(task_status.get('llm_dispatch_reason') or '').strip() or None})
            seen_recipe_ids.add(recipe_id)
    return tuple(rows)

def _recipe_result_rows_from_proposals(proposals: Sequence[ShardProposalV1]) -> dict[str, dict[str, Any]]:
    locally_finalized_rows = {str(row.get('recipe_id') or '').strip(): dict(row) for row in _collect_recipe_locally_finalized_skip_rows(proposals) if str(row.get('recipe_id') or '').strip()}
    rows: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        if proposal.status != 'validated' or not isinstance(proposal.payload, dict):
            continue
        try:
            shard_output = RecipeCorrectionShardOutput.model_validate(proposal.payload)
        except Exception:
            continue
        for recipe_output in shard_output.recipes:
            final_recipe_authority_eligibility, final_recipe_authority_reason = _classify_recipe_authority_eligibility(recipe_output.repair_status)
            rows[recipe_output.recipe_id] = {'repair_status': recipe_output.repair_status, 'status_reason': recipe_output.status_reason, 'final_recipe_authority_eligibility': final_recipe_authority_eligibility, 'final_recipe_authority_reason': final_recipe_authority_reason}
            local_skip_row = locally_finalized_rows.get(recipe_output.recipe_id)
            if local_skip_row is not None:
                rows[recipe_output.recipe_id]['llm_dispatch'] = 'handled_locally_skip_llm'
                rows[recipe_output.recipe_id]['llm_dispatch_reason'] = str(local_skip_row.get('llm_dispatch_reason') or '').strip()
                rows[recipe_output.recipe_id]['llm_dispatch_task_id'] = str(local_skip_row.get('task_id') or '').strip()
    return rows

def _classify_recipe_authority_eligibility(repair_status: str | None) -> tuple[str, str]:
    status = str(repair_status or '').strip()
    if status == 'repaired':
        return ('promotable', 'repair_status_repaired')
    if status == 'fragmentary':
        return ('non_promotable', 'repair_status_fragmentary')
    if status == 'not_a_recipe':
        return ('non_promotable', 'repair_status_not_a_recipe')
    return ('unknown', 'repair_status_unknown')

def _classify_final_recipe_authority_status(*, correction_output_status: str | None, final_assembly_status: str) -> tuple[str, str]:
    status = str(correction_output_status or '').strip()
    assembly_status = str(final_assembly_status or '').strip()
    if status == 'repaired' and assembly_status == 'ok':
        return ('promoted', 'repaired_recipe_promoted')
    if status in {'fragmentary', 'not_a_recipe'}:
        return ('not_promoted', f'valid_task_outcome_{status}')
    if assembly_status == 'error':
        if status == 'repaired':
            return ('error', 'repaired_recipe_final_assembly_error')
        return ('error', 'recipe_task_outcome_error')
    if assembly_status == 'skipped':
        return ('not_promoted', 'promotion_skipped')
    return ('pending', 'promotion_pending')

def _load_pipeline_assets(*, pipeline_root: Path, pipeline_id: str) -> dict[str, Any]:
    pipeline_path = pipeline_root / 'pipelines' / f'{pipeline_id}.json'
    if not pipeline_path.exists():
        fallback_root = Path(__file__).resolve().parents[2] / 'llm_pipelines'
        fallback_path = fallback_root / 'pipelines' / f'{pipeline_id}.json'
        if fallback_path.exists():
            pipeline_root = fallback_root
            pipeline_path = fallback_path
    pipeline_payload = json.loads(pipeline_path.read_text(encoding='utf-8'))
    prompt_template_rel = str(pipeline_payload.get('prompt_template_path') or '').strip()
    output_schema_rel = str(pipeline_payload.get('output_schema_path') or '').strip()
    prompt_template_path = pipeline_root / prompt_template_rel
    output_schema_path = pipeline_root / output_schema_rel
    return {'pipeline_payload': pipeline_payload, 'prompt_template_text': prompt_template_path.read_text(encoding='utf-8'), 'prompt_template_path': str(prompt_template_path), 'output_schema_path': output_schema_path}

def render_recipe_direct_prompt(*, pipeline_assets: Mapping[str, Any], input_text: str, input_path: Path) -> str:
    rendered = str(pipeline_assets.get('prompt_template_text') or '')
    rendered = rendered.replace('{{INPUT_TEXT}}', input_text)
    rendered = rendered.replace('{{ INPUT_TEXT }}', input_text)
    rendered = rendered.replace('{{INPUT_PATH}}', str(input_path))
    rendered = rendered.replace('{{ INPUT_PATH }}', str(input_path))
    return rendered

def _build_recipe_shard_survivability_report(*, recipe_shards: Sequence[_RecipeShardPlan], phase_input_dir: Path, pipeline_assets: Mapping[str, Any], model_name: str | None, requested_shard_count: int | None) -> dict[str, Any]:
    shard_estimates: list[dict[str, Any]] = []
    resolved_model_name = str(model_name or '').strip()
    for recipe_shard in recipe_shards:
        serialized_input = _serialize_compact_prompt_json(serialize_recipe_correction_shard_input(recipe_shard.shard_input))
        input_path = phase_input_dir / f'{recipe_shard.shard_id}.json'
        prompt_text = render_recipe_direct_prompt(pipeline_assets=pipeline_assets, input_text=serialized_input, input_path=input_path)
        shard_estimates.append({'shard_id': recipe_shard.shard_id, 'owned_unit_count': len(recipe_shard.states), 'estimated_input_tokens': count_tokens_for_model(prompt_text, model_name=resolved_model_name), 'estimated_output_tokens': count_structural_output_tokens(pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID, input_payload=serialize_recipe_correction_shard_input(recipe_shard.shard_input), model_name=resolved_model_name), 'metadata': {'recipe_ids': [state.recipe_id for state in recipe_shard.states]}})
    return evaluate_stage_survivability(stage_key='recipe_refine', shard_estimates=shard_estimates, requested_shard_count=requested_shard_count or len(recipe_shards), stage_label_override='Recipe Refine')

def _build_single_correction_manifest(*, run_settings: RunSettings, llm_raw_dir: Path, correction_audit_dir: Path, manifest_path: Path, states: list[_RecipeState], process_runs: dict[str, dict[str, Any]], output_schema_paths: dict[str, str], timing_seconds: float, recipe_shards: Sequence[_RecipeShardPlan]=(), phase_runtime_dir: Path | None=None, phase_runtime_summary: Mapping[str, Any] | None=None) -> dict[str, Any]:
    recipe_rows: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for state in states:
        final_recipe_authority_status, final_recipe_authority_reason = _classify_final_recipe_authority_status(correction_output_status=state.correction_output_status, final_assembly_status=state.final_assembly_status)
        row = {'recipe_build_intermediate': 'ok', 'recipe_refine': state.single_correction_status, 'recipe_build_final': state.final_assembly_status, 'final_recipe_authority_status': final_recipe_authority_status, 'final_recipe_authority_reason': final_recipe_authority_reason, 'warnings': list(state.warnings), 'errors': list(state.errors), 'structural_status': state.structural_status, 'structural_reason_codes': list(state.structural_reason_codes)}
        if state.correction_output_status:
            row['correction_output_status'] = state.correction_output_status
        if state.correction_output_reason:
            row['correction_output_reason'] = state.correction_output_reason
        mapping_status = getattr(state, 'correction_mapping_status', None)
        mapping_reason = getattr(state, 'correction_mapping_reason', None)
        if mapping_status:
            row['mapping_status'] = mapping_status
        if mapping_reason:
            row['mapping_reason'] = mapping_reason
        recipe_rows[state.recipe_id] = row
        if state.errors:
            failures.append({'recipe_id': state.recipe_id, 'errors': list(state.errors)})
    return {'enabled': True, 'pipeline': SINGLE_CORRECTION_RECIPE_PIPELINE_ID, 'codex_farm_cmd': run_settings.codex_farm_cmd, 'codex_farm_model': run_settings.codex_farm_model, 'codex_farm_reasoning_effort': _effort_override_value(run_settings.codex_farm_reasoning_effort), 'codex_farm_root': run_settings.codex_farm_root, 'codex_farm_workspace_root': run_settings.codex_farm_workspace_root, 'counts': {'recipes_total': len(states), 'recipe_build_intermediate_ok': len(states), 'recipe_shards_total': len(recipe_shards), 'recipe_workers_total': int((phase_runtime_summary or {}).get('worker_count') or 0), 'recipe_correction_handled_locally_skip_llm': int((((phase_runtime_summary or {}).get('promotion_report') or {}).get('handled_locally_skip_llm') or {}).get('count') or 0), 'recipe_correction_inputs': len(states), 'recipe_correction_ok': sum((1 for state in states if state.single_correction_status == 'ok')), 'recipe_correction_error': sum((1 for state in states if state.single_correction_status == 'error')), 'recipe_correction_repaired': sum((1 for state in states if state.correction_output_status == 'repaired')), 'recipe_correction_fragmentary': sum((1 for state in states if state.correction_output_status == 'fragmentary')), 'recipe_correction_not_a_recipe': sum((1 for state in states if state.correction_output_status == 'not_a_recipe')), 'recipe_build_final_ok': sum((1 for state in states if state.final_assembly_status == 'ok')), 'recipe_build_final_error': sum((1 for state in states if state.final_assembly_status == 'error')), 'recipe_build_final_skipped': sum((1 for state in states if state.final_assembly_status == 'skipped')), 'final_recipe_authority_promoted': sum((1 for state in states if _classify_final_recipe_authority_status(correction_output_status=state.correction_output_status, final_assembly_status=state.final_assembly_status)[0] == 'promoted')), 'final_recipe_authority_not_promoted': sum((1 for state in states if _classify_final_recipe_authority_status(correction_output_status=state.correction_output_status, final_assembly_status=state.final_assembly_status)[0] == 'not_promoted')), 'final_recipe_authority_error': sum((1 for state in states if _classify_final_recipe_authority_status(correction_output_status=state.correction_output_status, final_assembly_status=state.final_assembly_status)[0] == 'error'))}, 'timing': {'recipe_correction_seconds': round(timing_seconds, 3)}, 'pipelines': {'recipe_correction': SINGLE_CORRECTION_STAGE_PIPELINE_ID}, 'output_schema_paths': dict(output_schema_paths), 'paths': {'recipe_correction_audit_dir': str(correction_audit_dir), 'recipe_phase_input_dir': str(phase_runtime_dir / 'inputs') if phase_runtime_dir else None, 'recipe_phase_proposals_dir': str(phase_runtime_dir / 'proposals') if phase_runtime_dir else None, 'recipe_manifest': str(manifest_path), 'recipe_phase_runtime_dir': str(phase_runtime_dir) if phase_runtime_dir else None}, 'process_runs': dict(process_runs), 'phase_runtime': dict(phase_runtime_summary or {}), 'failures': failures, 'recipes': recipe_rows, 'llm_raw_dir': str(llm_raw_dir)}

def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}

def _assign_recipe_workers_v1(*, run_root: Path, shards: Sequence[ShardManifestEntryV1], worker_count: int) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(requested_worker_count=worker_count, shard_count=len(shards))
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [WorkerAssignmentV1(worker_id=f'worker-{index + 1:03d}', shard_ids=tuple(bucket), workspace_root=str(run_root / 'workers' / f'worker-{index + 1:03d}')) for index, bucket in enumerate(buckets)]

def _build_recipe_task_plans(shard: ShardManifestEntryV1) -> tuple[_RecipeTaskPlan, ...]:
    payload = _coerce_dict(shard.input_payload)
    recipes = [dict(row) for row in payload.get('r') or [] if isinstance(row, Mapping)]
    hint_rows = [dict(row) for row in _coerce_dict(shard.metadata).get('worker_hint_recipes') or [] if isinstance(row, Mapping)]
    hint_by_recipe_id = {str(row.get('recipe_id') or '').strip(): row for row in hint_rows if str(row.get('recipe_id') or '').strip()}
    if not recipes:
        return ()
    task_count = len(recipes)
    task_plans: list[_RecipeTaskPlan] = []
    for task_index, recipe_row in enumerate(recipes, start=1):
        recipe_id = str(recipe_row.get('rid') or '').strip()
        if not recipe_id:
            continue
        task_id = shard.shard_id if task_count == 1 else f'{shard.shard_id}.task-{task_index:03d}'
        task_payload = {**payload, 'sid': task_id, 'ids': [recipe_id], 'r': [dict(recipe_row)]}
        task_manifest = ShardManifestEntryV1(shard_id=task_id, owned_ids=(recipe_id,), evidence_refs=tuple(shard.evidence_refs), input_payload=task_payload, metadata={**dict(shard.metadata or {}), 'parent_shard_id': shard.shard_id, 'task_id': task_id, 'task_index': task_index, 'task_count': task_count, 'recipe_ids': [recipe_id], 'recipe_count': 1, 'worker_hint_recipes': [dict(hint_by_recipe_id[recipe_id])] if recipe_id in hint_by_recipe_id else []})
        task_plans.append(_RecipeTaskPlan(task_id=task_id, parent_shard_id=shard.shard_id, manifest_entry=task_manifest))
    return tuple(task_plans)

def _aggregate_recipe_task_payloads(*, shard: ShardManifestEntryV1, task_payloads_by_task_id: Mapping[str, dict[str, Any] | None], task_validation_errors_by_task_id: Mapping[str, Sequence[str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_recipe_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    recipe_rows_by_id: dict[str, dict[str, Any]] = {}
    task_id_by_recipe_id: dict[str, str] = {}
    accepted_task_ids: list[str] = []
    for task_id, payload in task_payloads_by_task_id.items():
        rows = payload.get('r') if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            continue
        accepted_task_ids.append(task_id)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            recipe_id = str(row.get('rid') or '').strip()
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
    all_task_ids = sorted({str(task_id).strip() for task_id in [*task_payloads_by_task_id.keys(), *task_validation_errors_by_task_id.keys()] if str(task_id).strip()})
    fallback_task_ids = sorted({str(task_id).strip() for task_id, errors in task_validation_errors_by_task_id.items() if errors or task_id not in accepted_task_ids})
    metadata = {'task_count': len(all_task_ids), 'accepted_task_count': len(accepted_task_ids), 'accepted_task_ids': sorted(accepted_task_ids), 'fallback_task_count': len(fallback_task_ids), 'fallback_task_ids': fallback_task_ids, 'missing_recipe_ids': missing_recipe_ids, 'task_ids': all_task_ids, 'task_validation_errors_by_task_id': {task_id: list(errors) for task_id, errors in task_validation_errors_by_task_id.items() if errors}, 'task_id_by_recipe_id': {recipe_id: task_id for recipe_id, task_id in sorted(task_id_by_recipe_id.items())}}
    return ({'v': '1', 'sid': shard.shard_id, 'r': output_rows}, metadata)

def _build_deterministic_terminal_recipe_task_payload(*, task_row: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = build_recipe_worker_scaffold(task_row=task_row)
    result_rows = [row for row in payload.get('r') or [] if isinstance(row, Mapping)]
    if not result_rows:
        return None
    statuses = {str(row.get('st') or '').strip() for row in result_rows}
    if not statuses or 'repaired' in statuses:
        return None
    validation_errors = validate_recipe_worker_draft(task_row=task_row, payload=payload)
    if validation_errors:
        raise ValueError('deterministic terminal recipe scaffold failed validation: ' + '; '.join(validation_errors))
    return payload

def _build_task_validation_feedback(*, validation_errors: Sequence[str], error_details: Sequence[Mapping[str, Any]] | None=None, repair_instruction: str) -> dict[str, Any]:
    return {'error_codes': [str(error).strip() for error in validation_errors if str(error).strip()], 'error_details': [{'path': str(row.get('path') or '/answer'), 'code': str(row.get('code') or 'validation_error'), 'message': str(row.get('message') or 'validation failed')} for row in error_details or [] if isinstance(row, Mapping)], 'repair_instruction': repair_instruction}

def _recipe_answer_to_compact_payload(*, task_plan: _RecipeTaskPlan, answer_payload: Mapping[str, Any]) -> dict[str, Any]:
    recipe_row = _coerce_dict((_coerce_dict(task_plan.manifest_entry.input_payload).get('r') or [{}])[0])
    recipe_id = str(recipe_row.get('rid') or '').strip() or str(task_plan.manifest_entry.owned_ids[0])
    canonical_recipe = dict(answer_payload.get('canonical_recipe')) if isinstance(answer_payload.get('canonical_recipe'), Mapping) else None
    mapping_rows: list[dict[str, Any]] = []
    for mapping_row in answer_payload.get('ingredient_step_mapping') or []:
        if not isinstance(mapping_row, Mapping):
            continue
        ingredient_indexes = [int(value) for value in mapping_row.get('ingredient_indexes') or [] if str(value).strip()]
        step_indexes = [int(value) for value in mapping_row.get('step_indexes') or [] if str(value).strip()]
        for ingredient_index in ingredient_indexes:
            mapping_rows.append({'i': ingredient_index, 's': step_indexes})
    divested_block_indices = [int(value) for value in answer_payload.get('divested_block_indices') or [] if str(value).strip()]
    return {'v': '1', 'sid': task_plan.task_id, 'r': [{'v': '1', 'rid': recipe_id, 'st': str(answer_payload.get('status') or '').strip(), 'sr': answer_payload.get('status_reason'), 'cr': {'t': canonical_recipe.get('title'), 'i': list(canonical_recipe.get('ingredients') or []), 's': list(canonical_recipe.get('steps') or []), 'd': canonical_recipe.get('description'), 'y': canonical_recipe.get('recipe_yield')} if canonical_recipe is not None else None, 'm': mapping_rows, 'mr': answer_payload.get('ingredient_step_mapping_reason'), 'db': divested_block_indices, 'g': [{'c': 'selected', 'l': str(tag).strip()} for tag in answer_payload.get('selected_tags') or [] if str(tag).strip()], 'w': [str(value).strip() for value in answer_payload.get('warnings') or [] if str(value).strip()]}]}

def _validate_recipe_output_divestments(*, prepared: _PreparedRecipeInput, correction_output: MergedRecipeRepairOutput) -> list[RecipeDivestment]:
    owned_block_indices = [int(index) for index in prepared.block_indices]
    owned_block_index_set = set(owned_block_indices)
    requested_divestments = [int(index) for index in correction_output.divested_block_indices]
    unexpected = [index for index in requested_divestments if index not in owned_block_index_set]
    if unexpected:
        raise ValueError(f'recipe output divested unknown block indices {unexpected}; owned block indices are {owned_block_indices}')
    if correction_output.repair_status != 'repaired':
        missing = [index for index in owned_block_indices if index not in requested_divestments]
        if missing:
            raise ValueError(f'recipe outputs with status {correction_output.repair_status!r} must divest every owned block; missing {missing}')
    elif owned_block_indices and len(requested_divestments) == len(owned_block_indices):
        raise ValueError("recipe outputs with status 'repaired' cannot divest every owned block")
    if not requested_divestments:
        return []
    return [RecipeDivestment(recipe_id=prepared.state.recipe_id, block_indices=requested_divestments, reason=str(correction_output.status_reason or correction_output.repair_status).strip() or 'explicit_recipe_divestment')]

def _evaluate_recipe_task_file_answers(*, original_task_file: Mapping[str, Any], edited_task_file_path: Path, runnable_tasks: Sequence[_RecipeTaskPlan]) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, ...]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    task_by_unit_id = {f'recipe::{str((_coerce_dict((_coerce_dict(task_plan.manifest_entry.input_payload).get('r') or [{}])[0]).get('rid') or '').strip() or task_plan.task_id)}': task_plan for task_plan in runnable_tasks}
    edited_task_file = load_task_file(edited_task_file_path)
    answers_by_unit_id, contract_errors, contract_metadata = validate_edited_task_file(original_task_file=original_task_file, edited_task_file=edited_task_file)
    payloads_by_task_id: dict[str, dict[str, Any]] = {}
    errors_by_task_id: dict[str, tuple[str, ...]] = {}
    previous_answers_by_unit_id: dict[str, dict[str, Any]] = {}
    feedback_by_unit_id: dict[str, dict[str, Any]] = {}
    if contract_errors:
        feedback = _build_task_validation_feedback(validation_errors=contract_errors, error_details=contract_metadata.get('error_details'), repair_instruction='Restore immutable fields and edit only `/units/*/answer`.')
        for unit_id, task_plan in task_by_unit_id.items():
            errors_by_task_id[task_plan.task_id] = tuple(contract_errors)
            previous_answers_by_unit_id[unit_id] = {}
            feedback_by_unit_id[unit_id] = dict(feedback)
        return (payloads_by_task_id, errors_by_task_id, previous_answers_by_unit_id, feedback_by_unit_id)
    resolved_answers = answers_by_unit_id or {}
    for unit_id, task_plan in task_by_unit_id.items():
        answer_payload = dict(resolved_answers.get(unit_id) or {})
        previous_answers_by_unit_id[unit_id] = dict(answer_payload)
        response_payload = _recipe_answer_to_compact_payload(task_plan=task_plan, answer_payload=answer_payload)
        payload, validation_errors, validation_metadata, proposal_status = _evaluate_recipe_response(shard=task_plan.manifest_entry, response_text=json.dumps(response_payload, sort_keys=True))
        if proposal_status == 'validated' and payload is not None:
            payloads_by_task_id[task_plan.task_id] = payload
            continue
        errors_by_task_id[task_plan.task_id] = tuple(validation_errors)
        feedback_by_unit_id[unit_id] = _build_task_validation_feedback(validation_errors=validation_errors, repair_instruction='Fix the named recipe answer fields and keep ownership exact.', error_details=[{'path': '/answer', 'code': str(error).strip() or 'validation_error', 'message': str(error).strip() or 'validation failed'} for error in validation_errors])
    return (payloads_by_task_id, errors_by_task_id, previous_answers_by_unit_id, feedback_by_unit_id)

def _empty_recipe_workspace_run_result(*, working_dir: Path, prompt_text: str) -> CodexExecRunResult:
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    return CodexExecRunResult(command=['codex', 'exec'], subprocess_exit_code=0, output_schema_path=None, prompt_text=prompt_text, response_text=None, turn_failed_message=None, events=(), usage={}, stderr_text=None, stdout_text=None, source_working_dir=str(working_dir), execution_working_dir=str(working_dir), execution_agents_path=None, duration_ms=0, started_at_utc=timestamp, finished_at_utc=timestamp, workspace_mode='taskfile', supervision_state='completed', supervision_reason_code=None, supervision_reason_detail=None, supervision_retryable=False)

def _recipe_task_records_for_runnable_tasks(runnable_tasks: Sequence[_RecipeTaskPlan]) -> list[dict[str, Any]]:
    return [{'unit_id': _build_recipe_task_file_unit(task_plan=task_plan)['unit_id'], 'task_id': task_plan.task_id, 'parent_shard_id': task_plan.parent_shard_id, 'result_path': _recipe_task_result_path(task_plan), 'manifest_entry': asdict(task_plan.manifest_entry)} for task_plan in runnable_tasks]

def _build_recipe_runner_exception_result(*, exc: CodexFarmRunnerError, prompt_text: str, working_dir: Path, retryable_reason: str | None) -> CodexExecRunResult:
    return CodexExecRunResult(command=['codex', 'exec'], subprocess_exit_code=1, output_schema_path=None, prompt_text=prompt_text, response_text=None, turn_failed_message=str(exc), events=(), usage={'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0, 'reasoning_tokens': 0}, stderr_text=str(exc), stdout_text=None, source_working_dir=str(working_dir), execution_working_dir=str(working_dir), execution_agents_path=None, duration_ms=0, started_at_utc=_format_utc_now(), finished_at_utc=_format_utc_now(), workspace_mode='taskfile', supervision_state='worker_exception', supervision_reason_code=retryable_reason or 'codex_exec_runner_exception', supervision_reason_detail=str(exc), supervision_retryable=retryable_reason is not None)

def _reset_recipe_workspace_for_fresh_worker_replacement(*, worker_root: Path, assignment: WorkerAssignmentV1, runnable_tasks: Sequence[_RecipeTaskPlan], original_task_file: Mapping[str, Any]) -> dict[str, Any]:
    for artifact_name in ('events.jsonl', 'last_message.json', 'usage.json', 'workspace_manifest.json', 'prompt_resume.txt', 'prompt_fresh_worker_replacement.txt'):
        artifact_path = worker_root / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()
    for task in runnable_tasks:
        output_path = worker_root / _recipe_task_result_path(task)
        if output_path.exists():
            output_path.unlink()
    state_path = _recipe_same_session_state_path(worker_root)
    replacement_state = initialize_recipe_same_session_state(state_path=state_path, assignment_id=assignment.worker_id, worker_id=assignment.worker_id, task_file=original_task_file, task_records=_recipe_task_records_for_runnable_tasks(runnable_tasks), output_dir=worker_root / 'out')
    write_task_file(path=worker_root / TASK_FILE_NAME, payload=original_task_file)
    return replacement_state

def _build_recipe_fresh_worker_replacement_prompt(*, task_count: int) -> str:
    return 'The previous recipe correction worker session was stopped before completion. Start over from the fresh `task.json` that the repo has restored in this workspace. Do not rely on prior partial outputs or shell state.\n\n' + _build_recipe_task_file_worker_prompt(task_count=task_count, repair_mode=False)

def _run_recipe_taskfile_assignment_v1(*, run_root: Path, assignment: WorkerAssignmentV1, artifacts: Mapping[str, str], assigned_shards: Sequence[ShardManifestEntryV1], worker_root: Path, in_dir: Path, hints_dir: Path, shard_dir: Path, logs_dir: Path, runner: CodexExecRunner, pipeline_id: str, env: Mapping[str, str], model: str | None, reasoning_effort: str | None, output_schema_path: Path | None, settings: Mapping[str, Any], shard_completed_callback: Callable[..., None] | None) -> _DirectRecipeWorkerResult:
    out_dir = worker_root / 'out'
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    processable_shards: list[ShardManifestEntryV1] = []
    runnable_shards: list[ShardManifestEntryV1] = []
    all_tasks: list[_RecipeTaskPlan] = []
    runnable_tasks: list[_RecipeTaskPlan] = []
    task_payloads_by_task_id: dict[str, dict[str, Any]] = {}
    task_validation_errors_by_task_id: dict[str, tuple[str, ...]] = {}
    task_status_by_task_id: dict[str, dict[str, Any]] = {}
    task_parent_shard_by_task_id: dict[str, str] = {}
    worker_prompt_path = worker_root / 'prompt.txt'
    worker_prompt_text = ''
    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_recipe_shard(shard)
        if preflight_failure is not None:
            preflight_result = _build_preflight_rejected_run_result(prompt_text='recipe correction worker preflight rejected', output_schema_path=output_schema_path, working_dir=worker_root, reason_code=str(preflight_failure.get('reason_code') or 'preflight_rejected'), reason_detail=str(preflight_failure.get('reason_detail') or 'recipe shard failed preflight'))
            _write_live_status(shard_root / 'live_status.json', {'state': 'preflight_rejected', 'reason_code': preflight_result.supervision_reason_code, 'reason_detail': preflight_result.supervision_reason_detail, 'retryable': preflight_result.supervision_retryable, 'watchdog_policy': 'taskfile_v1', 'elapsed_seconds': 0.0, 'last_event_seconds_ago': None, 'command_execution_count': 0, 'reasoning_item_count': 0})
            proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
            preflight_error = str(preflight_failure.get('reason_code') or 'preflight_rejected')
            _write_json({'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': None, 'validation_errors': [preflight_error], 'validation_metadata': {}, 'repair_attempted': False, 'repair_status': 'not_attempted', 'state': 'preflight_rejected', 'reason_code': preflight_error, 'reason_detail': str(preflight_failure.get('reason_detail') or ''), 'retryable': False}, proposal_path)
            _write_json({'status': 'missing_output', 'validation_errors': [preflight_error], 'validation_metadata': {}, 'runtime_mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'repair_attempted': False, 'repair_status': 'not_attempted', 'state': 'preflight_rejected', 'reason_code': preflight_error, 'reason_detail': str(preflight_failure.get('reason_detail') or ''), 'retryable': False}, shard_root / 'status.json')
            worker_failure_count += 1
            worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': 'preflight_rejected', 'validation_errors': [preflight_error], 'state': 'preflight_rejected', 'reason_code': preflight_error})
            worker_proposals.append(ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status='missing_output', proposal_path=_relative_path(run_root, proposal_path), payload=None, validation_errors=(preflight_error,), metadata={'repair_attempted': False, 'repair_status': 'not_attempted', 'state': 'preflight_rejected', 'reason_code': preflight_error, 'reason_detail': str(preflight_failure.get('reason_detail') or ''), 'retryable': False}))
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
            continue
        task_plans = _build_recipe_task_plans(shard)
        if not task_plans:
            continue
        processable_shards.append(shard)
        all_tasks.extend(task_plans)
        shard_has_runnable_task = False
        for task_plan in task_plans:
            task_id = task_plan.task_id
            task_parent_shard_by_task_id[task_id] = shard.shard_id
            task_row = asdict(_build_recipe_task_runtime_manifest_entry(task_plan))
            deterministic_payload = _build_deterministic_terminal_recipe_task_payload(task_row=task_row)
            if deterministic_payload is not None:
                task_payloads_by_task_id[task_id] = deterministic_payload
                task_validation_errors_by_task_id[task_id] = ()
                task_status_by_task_id[task_id] = {'task_status': 'handled_locally_skip_llm', 'llm_dispatch': 'handled_locally_skip_llm', 'llm_dispatch_reason': 'deterministic_terminal_scaffold', 'repair_attempted': False, 'repair_status': 'not_needed'}
                _write_recipe_task_payload(output_path=worker_root / recipe_worker_task_paths(task_row)['result_path'], payload=deterministic_payload)
                continue
            task_status_by_task_id[task_id] = {'task_status': 'assigned_to_worker', 'llm_dispatch': 'task_file_worker', 'llm_dispatch_reason': 'llm_required', 'repair_attempted': False, 'repair_status': 'not_attempted'}
            runnable_tasks.append(task_plan)
            shard_has_runnable_task = True
        if shard_has_runnable_task:
            runnable_shards.append(shard)
    run_result = _empty_recipe_workspace_run_result(working_dir=worker_root, prompt_text=worker_prompt_text)
    task_file_guardrail: dict[str, Any] | None = None
    repair_worker_session_count = 0
    fresh_session_retry_count = 0
    fresh_session_retry_status = 'not_attempted'
    same_session_state_payload: dict[str, Any] = {}
    fresh_worker_replacement_count = 0
    fresh_worker_replacement_status = 'not_attempted'
    fresh_worker_replacement_metadata: dict[str, Any] = {}
    if runnable_tasks:
        task_file_path = worker_root / TASK_FILE_NAME
        original_task_file = _build_recipe_task_file(assignment=assignment, runnable_tasks=runnable_tasks)
        task_file_guardrail = build_task_file_guardrail(payload=original_task_file, assignment_id=assignment.worker_id, worker_id=assignment.worker_id)
        state_path = _recipe_same_session_state_path(worker_root)
        initialize_recipe_same_session_state(state_path=state_path, assignment_id=assignment.worker_id, worker_id=assignment.worker_id, task_file=original_task_file, task_records=_recipe_task_records_for_runnable_tasks(runnable_tasks), output_dir=worker_root / 'out')
        write_task_file(path=task_file_path, payload=original_task_file)
        worker_prompt_text = _build_recipe_task_file_worker_prompt(task_count=len(runnable_tasks), repair_mode=False)
        worker_prompt_path.write_text(worker_prompt_text, encoding='utf-8')
        for shard in runnable_shards:
            (shard_dir / shard.shard_id / 'prompt.txt').write_text(worker_prompt_text, encoding='utf-8')
        worker_live_status_path = worker_root / 'live_status.json'
        shard_live_status_paths = [shard_dir / shard.shard_id / 'live_status.json' for shard in runnable_shards]
        base_watchdog_callback = _build_recipe_watchdog_callback(live_status_path=worker_live_status_path, live_status_paths=shard_live_status_paths, watchdog_policy='taskfile_v1', stage_label='taskfile worker stage', allow_workspace_commands=True, execution_workspace_root=worker_root)

        def _run_workspace_attempt(*, prompt_text: str, workspace_task_label: str) -> tuple[CodexExecRunResult, CodexFarmRunnerError | None, dict[str, Any]]:
            attempt_exception: CodexFarmRunnerError | None = None
            try:
                current_run_result = runner.run_taskfile_worker(prompt_text=prompt_text, working_dir=worker_root, env={**dict(env), RECIPE_SAME_SESSION_STATE_ENV: str(state_path)}, model=model, reasoning_effort=reasoning_effort, completed_termination_grace_seconds=float(settings.get('completed_termination_grace_seconds') or 15.0), workspace_task_label=workspace_task_label, supervision_callback=base_watchdog_callback)
            except CodexFarmRunnerError as exc:
                attempt_exception = exc
                current_run_result = _build_recipe_runner_exception_result(exc=exc, prompt_text=prompt_text, working_dir=worker_root, retryable_reason=_recipe_retryable_runner_exception_reason(exc))
            _finalize_live_status(worker_live_status_path, run_result=current_run_result, watchdog_policy='taskfile_v1')
            for live_status_path in shard_live_status_paths:
                _finalize_live_status(live_status_path, run_result=current_run_result, watchdog_policy='taskfile_v1')
            (worker_root / 'events.jsonl').write_text(_render_events_jsonl(current_run_result.events), encoding='utf-8')
            _write_json({'text': current_run_result.response_text}, worker_root / 'last_message.json')
            _write_json(dict(current_run_result.usage or {}), worker_root / 'usage.json')
            _write_json(current_run_result.workspace_manifest(), worker_root / 'workspace_manifest.json')
            return (current_run_result, attempt_exception, _load_json_dict_safely(state_path))
        run_result, initial_runner_exception, same_session_state_payload = _run_workspace_attempt(prompt_text=worker_prompt_text, workspace_task_label='recipe correction worker session')
        worker_session_runs: list[dict[str, Any]] = [{'run_result': run_result, 'prompt_path': worker_prompt_path, 'fresh_session_resume': False, 'fresh_worker_replacement': False, 'fresh_worker_replacement_reason_code': None}]
        should_replace_worker, replacement_reason = _should_attempt_recipe_fresh_worker_replacement(run_result=None if initial_runner_exception is not None else run_result, exc=initial_runner_exception, replacement_attempt_count=fresh_worker_replacement_count, same_session_state_payload=same_session_state_payload)
        fresh_worker_replacement_metadata = {'fresh_worker_replacement_attempted': bool(should_replace_worker), 'fresh_worker_replacement_status': 'attempted' if should_replace_worker else 'skipped', 'fresh_worker_replacement_count': 0, 'fresh_worker_replacement_reason_code': replacement_reason if should_replace_worker else None, 'fresh_worker_replacement_error_summary': str(initial_runner_exception) if initial_runner_exception is not None else str(run_result.supervision_reason_detail or '').strip() or None, 'fresh_worker_replacement_skipped_reason': None if should_replace_worker else replacement_reason}
        if should_replace_worker:
            fresh_worker_replacement_count = 1
            fresh_worker_replacement_status = 'attempted'
            same_session_state_payload = _reset_recipe_workspace_for_fresh_worker_replacement(worker_root=worker_root, assignment=assignment, runnable_tasks=runnable_tasks, original_task_file=original_task_file)
            replacement_prompt_path = worker_root / 'prompt_fresh_worker_replacement.txt'
            replacement_prompt_text = _build_recipe_fresh_worker_replacement_prompt(task_count=len(runnable_tasks))
            replacement_prompt_path.write_text(replacement_prompt_text, encoding='utf-8')
            run_result, _replacement_exception, same_session_state_payload = _run_workspace_attempt(prompt_text=replacement_prompt_text, workspace_task_label='recipe correction worker replacement session')
            worker_session_runs.append({'run_result': run_result, 'prompt_path': replacement_prompt_path, 'fresh_session_resume': False, 'fresh_worker_replacement': True, 'fresh_worker_replacement_reason_code': replacement_reason})
        should_retry, retry_reason = _should_attempt_recipe_fresh_session_retry(run_result=run_result, task_file_path=task_file_path, original_task_file=original_task_file, same_session_state_payload=same_session_state_payload)
        if should_retry:
            fresh_session_retry_count = 1
            fresh_session_retry_status = 'attempted'
            same_session_state_payload['fresh_session_retry_count'] = 1
            same_session_state_payload['fresh_session_retry_status'] = 'attempted'
            fresh_session_retry_history = list(same_session_state_payload.get('fresh_session_retry_history') or [])
            fresh_session_retry_history.append({'attempt': 1, 'reason_code': retry_reason, 'reason_detail': 'clean first session preserved useful workspace state without completion'})
            same_session_state_payload['fresh_session_retry_history'] = fresh_session_retry_history
            _write_json(same_session_state_payload, state_path)
            current_task_file = load_task_file(task_file_path)
            resume_prompt_path = worker_root / 'prompt_resume.txt'
            resume_prompt_text = _build_recipe_task_file_worker_prompt(task_count=len(runnable_tasks), repair_mode=str(current_task_file.get('mode') or '') == 'repair', fresh_session_resume=True)
            resume_prompt_path.write_text(resume_prompt_text, encoding='utf-8')
            run_result, _resume_exception, same_session_state_payload = _run_workspace_attempt(prompt_text=resume_prompt_text, workspace_task_label='recipe correction worker fresh-session recovery')
            worker_session_runs.append({'run_result': run_result, 'prompt_path': resume_prompt_path, 'fresh_session_resume': True, 'fresh_worker_replacement': False, 'fresh_worker_replacement_reason_code': None})
            same_session_state_payload = _load_json_dict_safely(state_path)
            fresh_session_retry_status = 'completed' if bool(same_session_state_payload.get('completed')) else 'failed'
            same_session_state_payload['fresh_session_retry_count'] = 1
            same_session_state_payload['fresh_session_retry_status'] = fresh_session_retry_status
            same_session_state_payload['fresh_session_retry_history'] = [{**(dict(row) if isinstance(row, Mapping) else {}), **({'result_completed': bool(same_session_state_payload.get('completed')), 'result_final_status': same_session_state_payload.get('final_status')} if index == len(fresh_session_retry_history) - 1 else {})} for index, row in enumerate(fresh_session_retry_history)]
            _write_json(same_session_state_payload, state_path)
        else:
            fresh_session_retry_status = 'not_attempted'
        for session_row in worker_session_runs:
            session_run_result = session_row['run_result']
            session_prompt_path = session_row['prompt_path']
            fresh_session_resume = bool(session_row.get('fresh_session_resume'))
            fresh_worker_replacement = bool(session_row.get('fresh_worker_replacement'))
            fresh_worker_replacement_reason_code = session_row.get('fresh_worker_replacement_reason_code')
            worker_runner_payload = _build_recipe_workspace_session_runner_payload(pipeline_id=pipeline_id, worker_id=assignment.worker_id, primary_shard_id=runnable_shards[0].shard_id if runnable_shards else assignment.shard_ids[0] if assignment.shard_ids else assignment.worker_id, run_result=session_run_result, model=model, reasoning_effort=reasoning_effort, worker_prompt_path=session_prompt_path, worker_root=worker_root, task_count=len(runnable_tasks), parent_shard_ids=[shard.shard_id for shard in runnable_shards], repair_task_count=0)
            telemetry_rows = worker_runner_payload.get('telemetry', {}).get('rows') if isinstance(worker_runner_payload.get('telemetry'), Mapping) else None
            if isinstance(telemetry_rows, list):
                for row_payload in telemetry_rows:
                    if isinstance(row_payload, dict):
                        row_payload['fresh_session_resume'] = fresh_session_resume
                        row_payload['fresh_worker_replacement'] = fresh_worker_replacement
                        row_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
                        stage_rows.append(dict(row_payload))
            process_payload = worker_runner_payload.get('process_payload')
            if isinstance(process_payload, dict):
                process_payload['fresh_session_resume'] = fresh_session_resume
                process_payload['fresh_worker_replacement'] = fresh_worker_replacement
                process_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
            worker_runner_payload['fresh_session_resume'] = fresh_session_resume
            worker_runner_payload['fresh_worker_replacement'] = fresh_worker_replacement
            worker_runner_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
            worker_runner_results.append(dict(worker_runner_payload))
        task_payloads_by_task_id.update({str(task_id): dict(payload) for task_id, payload in dict(same_session_state_payload.get('task_payloads_by_task_id') or {}).items() if isinstance(payload, Mapping)})
        task_validation_errors_by_task_id.update({str(task_id): tuple((str(error).strip() for error in errors or [] if str(error).strip())) for task_id, errors in dict(same_session_state_payload.get('task_validation_errors_by_task_id') or {}).items()})
        for task_id, status_payload in dict(same_session_state_payload.get('task_status_by_task_id') or {}).items():
            if isinstance(status_payload, Mapping):
                task_status_by_task_id.setdefault(str(task_id), {}).update(dict(status_payload))
        for task in runnable_tasks:
            task_root = worker_root / 'shards' / task.task_id
            task_root.mkdir(parents=True, exist_ok=True)
            task_status_payload = dict(task_status_by_task_id.get(task.task_id) or {})
            _write_json({'task_id': task.task_id, 'repair_status': task_status_payload.get('repair_status'), 'validation_errors': list(task_status_payload.get('validation_errors') or [])}, task_root / 'repair_status.json')
        if not task_payloads_by_task_id and (not same_session_state_payload.get('completed')):
            first_pass_payloads, first_pass_errors, _previous_answers_by_unit_id, _feedback_by_unit_id = _evaluate_recipe_task_file_answers(original_task_file=original_task_file, edited_task_file_path=task_file_path, runnable_tasks=runnable_tasks)
            task_payloads_by_task_id.update(first_pass_payloads)
            for task in runnable_tasks:
                if task.task_id in first_pass_payloads:
                    _write_recipe_task_payload(output_path=worker_root / _recipe_task_result_path(task), payload=first_pass_payloads[task.task_id])
                    task_validation_errors_by_task_id[task.task_id] = ()
                    task_status_by_task_id.setdefault(task.task_id, {}).update({'task_status': 'validated', 'repair_attempted': False, 'repair_status': 'not_needed', 'validation_errors': []})
                else:
                    failed_validation_errors = list(first_pass_errors.get(task.task_id) or ())
                    task_validation_errors_by_task_id[task.task_id] = tuple(failed_validation_errors)
                    task_status_by_task_id.setdefault(task.task_id, {}).update({'task_status': 'invalid', 'repair_attempted': False, 'repair_status': 'not_attempted', 'validation_errors': failed_validation_errors})
        if fresh_worker_replacement_count > 0:
            recovered_task_count = sum((1 for task in runnable_tasks if task.task_id in task_payloads_by_task_id))
            fresh_worker_replacement_status = 'recovered' if recovered_task_count > 0 or bool(same_session_state_payload.get('completed')) else 'exhausted'
            fresh_worker_replacement_metadata = {**fresh_worker_replacement_metadata, 'fresh_worker_replacement_attempted': True, 'fresh_worker_replacement_status': fresh_worker_replacement_status, 'fresh_worker_replacement_count': fresh_worker_replacement_count, 'fresh_worker_replacement_skipped_reason': None}
    for shard in processable_shards:
        shard_root = shard_dir / shard.shard_id
        shard_task_ids = [task_plan.task_id for task_plan in _build_recipe_task_plans(shard)]
        task_payloads = {task_id: payload for task_id, payload in task_payloads_by_task_id.items() if task_parent_shard_by_task_id.get(task_id) == shard.shard_id}
        task_errors = {task_id: errors for task_id, errors in task_validation_errors_by_task_id.items() if task_parent_shard_by_task_id.get(task_id) == shard.shard_id}
        payload, aggregation_metadata = _aggregate_recipe_task_payloads(shard=shard, task_payloads_by_task_id=task_payloads, task_validation_errors_by_task_id=task_errors)
        payload_candidate, validation_errors, validation_metadata, proposal_status = _evaluate_recipe_response(shard=shard, response_text=json.dumps(payload, sort_keys=True))
        shard_task_statuses = {task_id: dict(task_status_by_task_id.get(task_id) or {}) for task_id in shard_task_ids}
        repair_attempted = any((bool((status_payload or {}).get('repair_attempted')) for status_payload in shard_task_statuses.values()))
        repair_status = 'repaired' if any((str((status_payload or {}).get('repair_status') or '').strip() == 'repaired' for status_payload in shard_task_statuses.values())) else 'failed' if repair_attempted else 'not_attempted'
        validation_metadata = {'task_aggregation': aggregation_metadata, **dict(validation_metadata or {}), 'task_status_by_task_id': {task_id: {key: value for key, value in status_payload.items() if key in {'task_status', 'llm_dispatch', 'llm_dispatch_reason', 'repair_attempted', 'repair_status', 'validation_errors'}} for task_id, status_payload in sorted(shard_task_statuses.items())}}
        if fresh_worker_replacement_metadata:
            validation_metadata['fresh_worker_replacement'] = dict(fresh_worker_replacement_metadata)
        repair_validation_errors = sorted({str(error).strip() for status_payload in shard_task_statuses.values() for error in (status_payload or {}).get('validation_errors') or [] if str(error).strip()})
        if repair_validation_errors:
            validation_metadata['repair_validation_errors'] = repair_validation_errors
        supervision_fields = _final_recipe_supervision_fields(run_result=run_result, proposal_status=proposal_status, repair_status=repair_status)
        final_payload = payload_candidate if proposal_status == 'validated' else None
        proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
        _write_json({'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': final_payload, 'validation_errors': list(validation_errors), 'validation_metadata': dict(validation_metadata or {}), 'repair_attempted': repair_attempted, 'repair_status': repair_status, 'state': supervision_fields['final_supervision_state'], 'reason_code': supervision_fields['final_supervision_reason_code'], 'reason_detail': supervision_fields['final_supervision_reason_detail'], 'retryable': run_result.supervision_retryable, **supervision_fields}, proposal_path)
        _write_json({'status': proposal_status, 'validation_errors': list(validation_errors), 'validation_metadata': dict(validation_metadata or {}), 'runtime_mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'repair_attempted': repair_attempted, 'repair_status': repair_status, 'state': supervision_fields['final_supervision_state'], 'reason_code': supervision_fields['final_supervision_reason_code'], 'reason_detail': supervision_fields['final_supervision_reason_detail'], 'retryable': run_result.supervision_retryable, **supervision_fields}, shard_root / 'status.json')
        if proposal_status != 'validated':
            worker_failure_count += 1
            reason = str(supervision_fields['final_supervision_reason_code'] or _failure_reason_from_run_result(run_result=run_result, proposal_status=proposal_status))
            worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': reason, 'validation_errors': list(validation_errors), 'state': supervision_fields['final_supervision_state'], 'reason_code': supervision_fields['final_supervision_reason_code']})
        else:
            worker_proposal_count += 1
        worker_proposals.append(ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status=proposal_status, proposal_path=_relative_path(run_root, proposal_path), payload=final_payload, validation_errors=validation_errors, metadata={**dict(validation_metadata or {}), 'repair_attempted': repair_attempted, 'repair_status': repair_status, 'state': supervision_fields['final_supervision_state'], 'reason_code': supervision_fields['final_supervision_reason_code'], 'reason_detail': supervision_fields['final_supervision_reason_detail'], 'retryable': run_result.supervision_retryable, **dict(fresh_worker_replacement_metadata), **supervision_fields}))
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
    worker_runner_payload = _aggregate_recipe_worker_runner_payload(pipeline_id=pipeline_id, worker_runs=worker_runner_results, stage_rows=stage_rows)
    worker_summary = worker_runner_payload.get('telemetry', {}).get('summary')
    if isinstance(worker_summary, dict):
        worker_summary['task_file_guardrails'] = summarize_task_file_guardrails([task_file_guardrail])
        worker_session_guardrails = build_worker_session_guardrails(planned_happy_path_worker_cap=3, actual_happy_path_worker_sessions=int(worker_summary.get('taskfile_session_count') or 0), repair_worker_session_count=repair_worker_session_count)
        worker_summary['worker_session_guardrails'] = worker_session_guardrails
        worker_summary['planned_happy_path_worker_cap'] = int(worker_session_guardrails['planned_happy_path_worker_cap'])
        worker_summary['actual_happy_path_worker_sessions'] = int(worker_session_guardrails['actual_happy_path_worker_sessions'])
        worker_summary['repair_worker_session_count'] = int(worker_session_guardrails['repair_worker_session_count'])
    worker_runner_payload['fresh_worker_replacement_count'] = fresh_worker_replacement_count
    worker_runner_payload['fresh_worker_replacement_status'] = fresh_worker_replacement_status
    if fresh_worker_replacement_metadata:
        worker_runner_payload.update(dict(fresh_worker_replacement_metadata))
    _write_json(worker_runner_payload, worker_root / 'status.json')
    return _DirectRecipeWorkerResult(report=WorkerExecutionReportV1(worker_id=assignment.worker_id, shard_ids=assignment.shard_ids, workspace_root=_relative_path(run_root, worker_root), status='ok' if worker_failure_count == 0 else 'partial_failure', proposal_count=worker_proposal_count, failure_count=worker_failure_count, runtime_mode_audit={'mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'status': 'ok', 'output_schema_enforced': False, 'tool_affordances_requested': True}, runner_result=worker_runner_payload, metadata={'in_dir': _relative_path(run_root, in_dir), 'hints_dir': _relative_path(run_root, hints_dir), 'out_dir': _relative_path(run_root, out_dir), 'shards_dir': _relative_path(run_root, shard_dir), 'log_dir': _relative_path(run_root, logs_dir), 'task_file_guardrail': dict(task_file_guardrail or {}), 'repair_worker_session_count': repair_worker_session_count, 'fresh_session_retry_count': fresh_session_retry_count, 'fresh_session_retry_status': fresh_session_retry_status, 'fresh_worker_replacement_count': fresh_worker_replacement_count, 'fresh_worker_replacement_status': fresh_worker_replacement_status, **dict(fresh_worker_replacement_metadata)}), proposals=tuple(worker_proposals), failures=tuple(worker_failures), stage_rows=tuple(stage_rows))

def _run_direct_recipe_worker_assignment_v1(*, run_root: Path, assignment: WorkerAssignmentV1, artifacts: Mapping[str, str], shard_by_id: Mapping[str, ShardManifestEntryV1], runner: CodexExecRunner, pipeline_id: str, env: Mapping[str, str], model: str | None, reasoning_effort: str | None, output_schema_path: Path | None, settings: Mapping[str, Any], pipeline_assets: Mapping[str, Any], shard_completed_callback: Callable[..., None] | None) -> _DirectRecipeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    runner_env = dict(env)
    in_dir = worker_root / 'in'
    hints_dir = worker_root / 'hints'
    shard_dir = worker_root / 'shards'
    logs_dir = worker_root / 'logs'
    in_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    (worker_root / 'assigned_shards.json').unlink(missing_ok=True)
    return _run_recipe_taskfile_assignment_v1(run_root=run_root, assignment=assignment, artifacts=artifacts, assigned_shards=assigned_shards, worker_root=worker_root, in_dir=in_dir, hints_dir=hints_dir, shard_dir=shard_dir, logs_dir=logs_dir, runner=runner, pipeline_id=pipeline_id, env=runner_env, model=model, reasoning_effort=reasoning_effort, output_schema_path=output_schema_path, settings=settings, shard_completed_callback=shard_completed_callback)

def _run_direct_recipe_workers_v1(*, phase_key: str, pipeline_id: str, run_root: Path, shards: Sequence[ShardManifestEntryV1], runner: CodexExecRunner, worker_count: int, env: Mapping[str, str], model: str | None, reasoning_effort: str | None, output_schema_path: Path | None, settings: Mapping[str, Any], runtime_metadata: Mapping[str, Any], pipeline_assets: Mapping[str, Any], progress_callback: Callable[[str], None] | None=None) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1]]:
    artifacts = {'phase_manifest': 'phase_manifest.json', 'shard_manifest': 'shard_manifest.jsonl', 'task_manifest': 'task_manifest.jsonl', 'worker_assignments': 'worker_assignments.json', 'promotion_report': 'promotion_report.json', 'telemetry': 'telemetry.json', 'failures': 'failures.json', 'proposals_dir': 'proposals'}
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_recipe_workers_v1(run_root=run_root, shards=shards, worker_count=worker_count)
    _write_jsonl(run_root / artifacts['shard_manifest'], [asdict(shard) for shard in shards])
    _write_jsonl(run_root / artifacts['task_manifest'], [asdict(_build_recipe_task_runtime_manifest_entry(task_plan)) for shard in shards for task_plan in _build_recipe_task_plans(shard)])
    _write_json([asdict(assignment) for assignment in assignments], run_root / artifacts['worker_assignments'])
    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    completed_shards = 0
    total_shards = len(shards)
    progress_lock = threading.Lock()
    last_progress_snapshot: tuple[Any, ...] | None = None
    task_ids_by_worker: dict[str, tuple[str, ...]] = {assignment.worker_id: tuple((task_plan.task_id for shard_id in assignment.shard_ids for task_plan in _build_recipe_task_plans(shard_by_id[shard_id]))) for assignment in assignments}
    total_tasks = sum((len(task_ids) for task_ids in task_ids_by_worker.values()))
    pending_shards_by_worker = {assignment.worker_id: list(assignment.shard_ids) for assignment in assignments}
    worker_roots_by_id = {assignment.worker_id: run_root / 'workers' / assignment.worker_id for assignment in assignments}

    def _recipe_worker_followup_status(*, worker_id: str) -> tuple[int, int, int]:
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        for task_id in task_ids_by_worker.get(worker_id, ()):
            task_root = run_root / 'workers' / worker_id / 'shards' / task_id
            repair_prompt_path = task_root / 'repair_prompt.txt'
            repair_status_path = task_root / 'repair_status.json'
            if repair_prompt_path.exists():
                repair_attempted += 1
            if repair_status_path.exists():
                repair_completed += 1
            elif repair_prompt_path.exists():
                repair_running += 1
        return (repair_attempted, repair_completed, repair_running)

    def _render_recipe_progress_label(*, worker_id: str, completed_task_ids: set[str]) -> str | None:
        remaining_task_ids = [task_id for task_id in task_ids_by_worker.get(worker_id, ()) if task_id not in completed_task_ids]
        if remaining_task_ids:
            first_task_id = remaining_task_ids[0]
            remaining = max(0, len(remaining_task_ids) - 1)
            if remaining <= 0:
                return first_task_id
            return f'{first_task_id} (+{remaining} more)'
        return None

    def _emit_progress_locked(*, force: bool=False) -> None:
        nonlocal last_progress_snapshot
        if progress_callback is None:
            return
        if total_tasks <= 0 and total_shards <= 0:
            return
        worker_health = summarize_taskfile_health(worker_roots_by_id=worker_roots_by_id)
        completed_task_ids: set[str] = set()
        for assignment in assignments:
            out_dir = run_root / 'workers' / assignment.worker_id / 'out'
            if not out_dir.exists():
                continue
            for output_path in out_dir.glob('*.json'):
                completed_task_ids.add(output_path.stem)
        completed_tasks = min(total_tasks, len(completed_task_ids))
        active_tasks = [label for assignment in assignments for label in [decorate_active_worker_label(_render_recipe_progress_label(worker_id=assignment.worker_id, completed_task_ids=completed_task_ids), worker_health.live_activity_summary_by_worker_id.get(assignment.worker_id), worker_health.attention_suffix_by_worker_id.get(assignment.worker_id))] if label is not None]
        running_workers = len(active_tasks)
        completed_workers = max(0, len(assignments) - running_workers)
        if total_tasks > 0:
            message = f'Running recipe correction... task {completed_tasks}/{total_tasks}'
            repair_attempted = 0
            repair_completed = 0
            repair_running = 0
            finalize_workers = 0
            proposal_count = 0
            proposals_dir = run_root / artifacts['proposals_dir']
            if proposals_dir.exists():
                proposal_count = len(list(proposals_dir.glob('*.json')))
            for assignment in assignments:
                worker_repair_attempted, worker_repair_completed, worker_repair_running = _recipe_worker_followup_status(worker_id=assignment.worker_id)
                repair_attempted += worker_repair_attempted
                repair_completed += worker_repair_completed
                repair_running += worker_repair_running
                if not any((task_id not in completed_task_ids for task_id in task_ids_by_worker.get(assignment.worker_id, ()))) and (pending_shards_by_worker.get(assignment.worker_id) or []):
                    finalize_workers += 1
            detail_lines = [f'configured workers: {len(assignments)}', f'completed shards: {completed_shards}/{total_shards}', f'queued recipe tasks: {max(0, total_tasks - completed_tasks)}']
            if finalize_workers > 0:
                detail_lines.append(f'workers finalizing shards: {finalize_workers}')
            if repair_attempted > 0:
                detail_lines.append(f'recipe repair attempts: {repair_completed}/{repair_attempted}')
            if repair_running > 0:
                detail_lines.append(f'repair calls running: {repair_running}')
            if worker_health.warning_worker_count > 0:
                detail_lines.append(f'watchdog warnings: {worker_health.warning_worker_count}')
            if worker_health.stalled_worker_count > 0:
                detail_lines.append(f'stalled workers: {worker_health.stalled_worker_count}')
            if worker_health.attention_lines:
                detail_lines.append('attention: ' + '; '.join(worker_health.attention_lines))
            snapshot = (completed_tasks, total_tasks, completed_shards, total_shards, running_workers, tuple(active_tasks), tuple(detail_lines), completed_workers, repair_attempted, repair_completed, repair_running, finalize_workers, proposal_count, worker_health.last_activity_at)
            if not force and snapshot == last_progress_snapshot:
                return
            last_progress_snapshot = snapshot
            progress_callback(format_stage_progress(message, stage_label='recipe pipeline', work_unit_label='recipe task', task_current=completed_tasks, task_total=total_tasks, running_workers=running_workers, worker_total=len(assignments), worker_running=running_workers, worker_completed=completed_workers, worker_failed=0, followup_running=finalize_workers + repair_running, followup_completed=completed_shards, followup_total=total_shards, followup_label='shard finalization', artifact_counts={'proposal_count': proposal_count, 'repair_attempted': repair_attempted, 'repair_completed': repair_completed, 'repair_running': repair_running, 'shards_completed': completed_shards, 'shards_total': total_shards}, last_activity_at=worker_health.last_activity_at or datetime.now(timezone.utc).isoformat(timespec='seconds'), active_tasks=active_tasks, detail_lines=detail_lines))
            return
        active_shards = [assignment.shard_ids[0] for assignment in assignments if assignment.shard_ids]
        snapshot = (completed_shards, total_shards, tuple(active_shards))
        if not force and snapshot == last_progress_snapshot:
            return
        last_progress_snapshot = snapshot
        progress_callback(format_stage_progress(f'Running recipe correction... task {completed_shards}/{total_shards}', stage_label='recipe pipeline', work_unit_label='recipe shard', task_current=completed_shards, task_total=total_shards, running_workers=min(len(active_shards), max(0, total_shards - completed_shards)), worker_total=len(assignments), worker_running=min(len(active_shards), max(0, total_shards - completed_shards)), worker_completed=max(0, len(assignments) - min(len(active_shards), max(0, total_shards - completed_shards))), worker_failed=0, active_tasks=active_shards[:max(0, total_shards - completed_shards)]))
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
    with ThreadPoolExecutor(max_workers=max(1, len(assignments)), thread_name_prefix='recipe-worker') as executor:
        futures_by_worker_id = {assignment.worker_id: executor.submit(_run_direct_recipe_worker_assignment_v1, run_root=run_root, assignment=assignment, artifacts=artifacts, shard_by_id=shard_by_id, runner=runner, pipeline_id=pipeline_id, env=env, model=model, reasoning_effort=reasoning_effort, output_schema_path=output_schema_path, settings=settings, pipeline_assets=pipeline_assets, shard_completed_callback=_mark_shard_completed) for assignment in assignments}
        pending_futures = {future: assignment for assignment in assignments for future in [futures_by_worker_id[assignment.worker_id]]}
        while pending_futures:
            done_futures, _ = wait(pending_futures.keys(), timeout=0.2, return_when=FIRST_COMPLETED)
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
    handled_locally_skip_llm_rows = _collect_recipe_locally_finalized_skip_rows(all_proposals)
    promotion_report = {'schema_version': 'phase_worker_runtime.promotion_report.v1', 'phase_key': phase_key, 'pipeline_id': pipeline_id, 'validated_shards': sum((1 for proposal in all_proposals if proposal.status == 'validated')), 'invalid_shards': sum((1 for proposal in all_proposals if proposal.status == 'invalid')), 'missing_output_shards': sum((1 for proposal in all_proposals if proposal.status == 'missing_output')), 'recipe_results': recipe_result_rows, 'recipe_result_counts': {'repaired': sum((1 for row in recipe_result_rows.values() if row.get('repair_status') == 'repaired')), 'fragmentary': sum((1 for row in recipe_result_rows.values() if row.get('repair_status') == 'fragmentary')), 'not_a_recipe': sum((1 for row in recipe_result_rows.values() if row.get('repair_status') == 'not_a_recipe'))}, 'handled_locally_skip_llm': {'count': len(handled_locally_skip_llm_rows), 'status_counts': {'fragmentary': sum((1 for row in handled_locally_skip_llm_rows if row.get('repair_status') == 'fragmentary')), 'not_a_recipe': sum((1 for row in handled_locally_skip_llm_rows if row.get('repair_status') == 'not_a_recipe'))}, 'recipes': [dict(row) for row in handled_locally_skip_llm_rows]}, 'task_counts': {status: sum((1 for proposal in all_proposals for status_payload in [_coerce_dict(_coerce_dict(proposal.metadata).get('task_status_by_task_id'))] for task_row in status_payload.values() if str(_coerce_dict(task_row).get('task_status') or '').strip() == status)) for status in ('handled_locally_skip_llm', 'assigned_to_worker', 'validated', 'validated_after_repair', 'failed_after_repair', 'missing_output', 'queue_not_reached')}}
    telemetry = {'schema_version': 'phase_worker_runtime.telemetry.v1', 'phase_key': phase_key, 'pipeline_id': pipeline_id, 'runtime_mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'worker_count': len(assignments), 'shard_count': len(shards), 'proposal_count': sum((report.proposal_count for report in worker_reports)), 'failure_count': len(failures), 'fresh_agent_count': len(assignments) + sum((int(dict(report.metadata or {}).get('fresh_worker_replacement_count') or 0) for report in worker_reports)), 'rows': stage_rows, 'summary': summarize_direct_telemetry_rows(stage_rows)}
    task_file_guardrails = summarize_task_file_guardrails([dict(report.metadata or {}).get('task_file_guardrail') if isinstance(report.metadata, Mapping) else None for report in worker_reports])
    worker_session_guardrails = build_worker_session_guardrails(planned_happy_path_worker_cap=len(assignments) * 3, actual_happy_path_worker_sessions=int(telemetry['summary'].get('taskfile_session_count') or 0), repair_worker_session_count=sum((int((dict(report.metadata or {}).get('repair_worker_session_count') if isinstance(report.metadata, Mapping) else 0) or 0) for report in worker_reports)))
    telemetry['summary']['task_file_guardrails'] = task_file_guardrails
    telemetry['summary']['worker_session_guardrails'] = worker_session_guardrails
    telemetry['summary']['planned_happy_path_worker_cap'] = int(worker_session_guardrails['planned_happy_path_worker_cap'])
    telemetry['summary']['actual_happy_path_worker_sessions'] = int(worker_session_guardrails['actual_happy_path_worker_sessions'])
    telemetry['summary']['repair_worker_session_count'] = int(worker_session_guardrails['repair_worker_session_count'])
    _write_json(promotion_report, run_root / artifacts['promotion_report'])
    _write_json(telemetry, run_root / artifacts['telemetry'])
    _write_json(failures, run_root / artifacts['failures'])
    runtime_metadata_payload = {**dict(runtime_metadata or {}), 'task_file_guardrails': task_file_guardrails, 'worker_session_guardrails': worker_session_guardrails, 'fresh_session_retry_count': sum((int(dict(report.metadata or {}).get('fresh_session_retry_count') or 0) for report in worker_reports)), 'fresh_worker_replacement_count': sum((int(dict(report.metadata or {}).get('fresh_worker_replacement_count') or 0) for report in worker_reports))}
    manifest = PhaseManifestV1(schema_version='phase_worker_runtime.phase_manifest.v1', phase_key=phase_key, pipeline_id=pipeline_id, run_root=str(run_root), worker_count=len(assignments), shard_count=len(shards), assignment_strategy='round_robin_v1', runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, max_turns_per_shard=1, settings=dict(settings or {}), artifact_paths=dict(artifacts), runtime_metadata=runtime_metadata_payload)
    _write_json(asdict(manifest), run_root / artifacts['phase_manifest'])
    if bool(worker_session_guardrails.get('cap_exceeded')):
        raise CodexFarmRunnerError(f'Recipe happy-path worker sessions exceeded the planned cap: planned={worker_session_guardrails['planned_happy_path_worker_cap']} actual={worker_session_guardrails['actual_happy_path_worker_sessions']}.')
    return (manifest, worker_reports)

def _run_single_correction_recipe_pipeline(*, conversion_result: ConversionResult, run_settings: RunSettings, run_root: Path, workbook_slug: str, runner: CodexExecRunner | None=None, full_blocks: list[dict[str, Any]] | None=None, progress_callback: Callable[[str], None] | None=None) -> CodexFarmApplyResult:
    llm_raw_dir = run_root / 'raw' / 'llm' / sanitize_for_filename(workbook_slug)
    correction_audit_dir = llm_raw_dir / 'recipe_correction_audit'
    phase_runtime_dir = llm_raw_dir / 'recipe_phase_runtime'
    phase_input_dir = phase_runtime_dir / 'inputs'
    for path in (correction_audit_dir, phase_runtime_dir, phase_input_dir):
        path.mkdir(parents=True, exist_ok=True)
    full_blocks_payload = _prepare_full_blocks(full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result))
    if not full_blocks_payload:
        raise CodexFarmRunnerError('Cannot run codex-farm recipe pipeline: no full_text blocks available.')
    full_blocks_by_index = {int(block['index']): block for block in full_blocks_payload}
    source_hash = _resolve_source_hash(conversion_result)
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    if not states:
        manifest_path = llm_raw_dir / RECIPE_MANIFEST_FILE_NAME
        manifest = _build_single_correction_manifest(run_settings=run_settings, llm_raw_dir=llm_raw_dir, correction_audit_dir=correction_audit_dir, manifest_path=manifest_path, states=[], process_runs={}, output_schema_paths={}, timing_seconds=0.0, recipe_shards=[], phase_runtime_dir=None, phase_runtime_summary={})
        _write_json(manifest, manifest_path)
        return CodexFarmApplyResult(updated_conversion_result=conversion_result, authoritative_recipe_payloads_by_recipe_id={}, llm_report={'enabled': True, 'pipeline': SINGLE_CORRECTION_RECIPE_PIPELINE_ID, 'counts': manifest['counts'], 'timing': manifest['timing'], 'process_runs': {}, 'phase_runtime': {}, 'llmRawDir': str(llm_raw_dir)}, llm_raw_dir=llm_raw_dir, recipe_divestments=[])
    pipeline_root = _resolve_pipeline_root(run_settings)
    pipeline_assets = _load_pipeline_assets(pipeline_root=pipeline_root, pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID)
    env = {'CODEX_FARM_ROOT': str(pipeline_root), _CODEX_FARM_RECIPE_MODE_ENV: run_settings.codex_farm_recipe_mode.value}
    if runner is None:
        raw_runner_cmd = str(run_settings.codex_farm_cmd or '').strip()
        direct_runner_cmd = raw_runner_cmd if Path(raw_runner_cmd).name == 'fake-codex-farm.py' else 'codex exec'
        codex_runner = SubprocessCodexExecRunner(cmd=direct_runner_cmd)
    else:
        codex_runner = runner
    output_schema_paths: dict[str, str] = {}
    resolved_output_schema_path = Path(pipeline_assets['output_schema_path'])
    output_schema_paths['recipe_correction'] = str(resolved_output_schema_path)
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(run_settings.codex_farm_reasoning_effort)
    correction_inputs_by_recipe_id: dict[str, MergedRecipeRepairInput] = {}
    prepared_inputs: list[_PreparedRecipeInput] = []
    for state in states:
        included_blocks = _build_blocks_for_recipe_state(state=state, full_blocks_by_index=full_blocks_by_index)
        if not included_blocks:
            state.single_correction_status = 'error'
            state.final_assembly_status = 'error'
            state.errors.append('recipe span has no authoritative blocks.')
            continue
        prepared_input = _build_prepared_recipe_input(state=state, workbook_slug=workbook_slug, source_hash=source_hash, included_blocks=included_blocks, full_blocks_by_index=full_blocks_by_index)
        correction_inputs_by_recipe_id[state.recipe_id] = prepared_input.correction_input
        prepared_inputs.append(prepared_input)
    recipe_shards = _build_recipe_shard_plans(prepared_inputs=prepared_inputs, run_settings=run_settings)
    for recipe_shard in recipe_shards:
        payload = serialize_recipe_correction_shard_input(recipe_shard.shard_input)
        (phase_input_dir / f'{recipe_shard.shard_id}.json').write_text(_serialize_compact_prompt_json(payload), encoding='utf-8')
    process_runs: dict[str, dict[str, Any]] = {}
    correction_started = time.perf_counter()
    phase_runtime_summary: dict[str, Any] = {}
    if recipe_shards:
        survivability_report = _build_recipe_shard_survivability_report(recipe_shards=recipe_shards, phase_input_dir=phase_input_dir, pipeline_assets=pipeline_assets, model_name=codex_model, requested_shard_count=run_settings.recipe_prompt_target_count)
        _write_json(survivability_report, phase_runtime_dir / 'shard_survivability_report.json')
        if str(survivability_report.get('survivability_verdict') or '') != 'safe':
            raise ShardSurvivabilityPreflightError(survivability_report)
        phase_manifest, worker_reports = _run_direct_recipe_workers_v1(phase_key='recipe_refine', pipeline_id=SINGLE_CORRECTION_STAGE_PIPELINE_ID, run_root=phase_runtime_dir, shards=[ShardManifestEntryV1(shard_id=plan.shard_id, owned_ids=tuple((state.recipe_id for state in plan.states)), evidence_refs=plan.evidence_refs, input_payload=serialize_recipe_correction_shard_input(plan.shard_input), metadata={'recipe_ids': [state.recipe_id for state in plan.states], 'bundle_names': [state.bundle_name for state in plan.states], 'recipe_count': len(plan.states), 'worker_hint_recipes': [{'recipe_id': prepared.state.recipe_id, 'bundle_name': prepared.state.bundle_name, 'title_hint': str(prepared.correction_input.recipe_candidate_hint.get('n') or '').strip(), 'quality_flags': list(prepared.candidate_quality_hint.get('f') or []), 'source_evidence_row_count': int(prepared.candidate_quality_hint.get('e') or 0), 'source_ingredient_like_count': int(prepared.candidate_quality_hint.get('ei') or 0), 'source_instruction_like_count': int(prepared.candidate_quality_hint.get('es') or 0), 'hint_ingredient_count': int(prepared.candidate_quality_hint.get('hi') or 0), 'hint_step_count': int(prepared.candidate_quality_hint.get('hs') or 0), 'pre_context_rows': [{'index': int(index), 'text': text} for index, text in prepared.pre_context_rows], 'post_context_rows': [{'index': int(index), 'text': text} for index, text in prepared.post_context_rows]} for prepared in plan.prepared_inputs]}) for plan in recipe_shards], runner=codex_runner, worker_count=_recipe_worker_count(run_settings, shard_count=len(recipe_shards)), env=env, model=codex_model, reasoning_effort=codex_reasoning_effort, output_schema_path=resolved_output_schema_path, settings={'llm_recipe_pipeline': run_settings.llm_recipe_pipeline.value, 'runtime_mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'recipe_worker_count': run_settings.recipe_worker_count, 'recipe_prompt_target_count': run_settings.recipe_prompt_target_count}, runtime_metadata={'workbook_slug': workbook_slug, 'recipe_phase_input_dir': str(phase_input_dir)}, pipeline_assets=pipeline_assets, progress_callback=progress_callback)
        phase_manifest_payload = json.loads((phase_runtime_dir / 'phase_manifest.json').read_text(encoding='utf-8'))
        promotion_report = json.loads((phase_runtime_dir / 'promotion_report.json').read_text(encoding='utf-8'))
        telemetry = json.loads((phase_runtime_dir / 'telemetry.json').read_text(encoding='utf-8'))
        survivability_report = attach_observed_telemetry_to_survivability_report(survivability_report, telemetry_rows=telemetry.get('rows') if isinstance(telemetry, Mapping) else None)
        _write_json(survivability_report, phase_runtime_dir / 'shard_survivability_report.json')
        worker_reports_payload = [asdict(report) for report in worker_reports]
        phase_runtime_summary = {'worker_count': phase_manifest.worker_count, 'shard_count': phase_manifest.shard_count, 'phase_manifest': phase_manifest_payload, 'promotion_report': promotion_report, 'telemetry': telemetry, 'worker_reports': worker_reports_payload}
        process_runs['recipe_correction'] = _aggregate_recipe_phase_process_run(phase_manifest=phase_manifest_payload, worker_reports=worker_reports_payload, promotion_report=promotion_report, telemetry=telemetry)
    correction_seconds = time.perf_counter() - correction_started
    updated_result = conversion_result.model_copy(deep=True)
    updated_recipes_by_id: dict[str, RecipeCandidate] = {str(recipe.identifier or ''): recipe for recipe in updated_result.recipes}
    authoritative_recipe_payloads: dict[str, AuthoritativeRecipeSemantics] = {}
    intermediate_overrides: dict[str, dict[str, Any]] = {}
    final_overrides: dict[str, dict[str, Any]] = {}
    explicitly_rejected_recipe_ids: set[str] = set()
    recipe_divestments: list[RecipeDivestment] = []
    proposals_by_shard_id: dict[str, dict[str, Any]] = {}
    proposals_dir = phase_runtime_dir / 'proposals'
    for proposal_path in sorted(proposals_dir.glob('*.json')):
        proposal_payload = json.loads(proposal_path.read_text(encoding='utf-8'))
        shard_id = str(proposal_payload.get('shard_id') or proposal_path.stem)
        proposals_by_shard_id[shard_id] = proposal_payload
    for state in states:
        if state.single_correction_status == 'error':
            continue
    for shard_plan in recipe_shards:
        proposal_payload = proposals_by_shard_id.get(shard_plan.shard_id)
        if proposal_payload is None:
            for state in shard_plan.states:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append('missing validated recipe shard proposal.')
            continue
        validation_errors = proposal_payload.get('validation_errors')
        if isinstance(validation_errors, list) and validation_errors:
            for state in shard_plan.states:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append('invalid recipe shard proposal: ' + ', '.join((str(item) for item in validation_errors)))
            continue
        try:
            shard_output = RecipeCorrectionShardOutput.model_validate(proposal_payload.get('payload') or {})
        except Exception as exc:
            for state in shard_plan.states:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append(f'invalid recipe shard output: {exc}')
            continue
        outputs_by_recipe_id = {recipe_output.recipe_id: recipe_output for recipe_output in shard_output.recipes}
        for prepared in shard_plan.prepared_inputs:
            state = prepared.state
            correction_output = outputs_by_recipe_id.get(state.recipe_id)
            if correction_output is None:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append('recipe missing from validated shard output.')
                continue
            state.correction_output_status = correction_output.repair_status
            state.correction_output_reason = correction_output.status_reason
            state.warnings.extend(list(correction_output.warnings))
            try:
                output_divestments = _validate_recipe_output_divestments(prepared=prepared, correction_output=correction_output)
            except ValueError as exc:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append(f'invalid recipe divestment contract: {exc}')
                continue
            if correction_output.repair_status != 'repaired':
                recipe_divestments.extend(output_divestments)
                explicitly_rejected_recipe_ids.add(state.recipe_id)
                state.single_correction_status = 'ok'
                state.final_assembly_status = 'skipped'
                _write_json(_build_recipe_correction_audit(state=state, correction_input=correction_inputs_by_recipe_id[state.recipe_id], correction_output=correction_output, corrected_candidate=None, final_payload=None, final_assembly_status='skipped', structural_audit=StructuralAuditResult(status='ok', severity='none', reason_codes=[]), mapping_status=None, mapping_reason=None), correction_audit_dir / _recipe_artifact_filename(state.recipe_id))
                continue
            recipe_divestments.extend(output_divestments)
            corrected_candidate = _corrected_candidate_from_output(state=state, output=correction_output)
            authoritative_payload = build_authoritative_recipe_semantics(corrected_candidate, semantic_authority=SINGLE_CORRECTION_RECIPE_PIPELINE_ID, ingredient_parser_options=run_settings.to_run_config_dict(), instruction_step_options=run_settings.to_run_config_dict(), ingredient_step_mapping_override=correction_output.ingredient_step_mapping, ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason)
            final_payload = authoritative_recipe_semantics_to_draft_v1(authoritative_payload, ingredient_parser_options=run_settings.to_run_config_dict(), instruction_step_options=run_settings.to_run_config_dict())
            structural_audit = _classify_recipe_correction_structural_audit(correction_output=correction_output, draft_payload=final_payload)
            _merge_structural_audit(state=state, audit=structural_audit)
            state.correction_mapping_status, state.correction_mapping_reason = _classify_recipe_correction_mapping_status(draft_payload=final_payload, correction_output=correction_output, ingredient_step_mapping=correction_output.ingredient_step_mapping, ingredient_step_mapping_reason=correction_output.ingredient_step_mapping_reason)
            try:
                draft_model = RecipeDraftV1.model_validate(final_payload)
            except Exception as exc:
                state.single_correction_status = 'error'
                state.final_assembly_status = 'error'
                state.errors.append(f'deterministic final assembly validation failed: {exc}')
                _write_json(_build_recipe_correction_audit(state=state, correction_input=correction_inputs_by_recipe_id[state.recipe_id], correction_output=correction_output, corrected_candidate=corrected_candidate, final_payload=final_payload, final_assembly_status='error', structural_audit=structural_audit, mapping_status=state.correction_mapping_status, mapping_reason=state.correction_mapping_reason), correction_audit_dir / _recipe_artifact_filename(state.recipe_id))
                continue
            state.single_correction_status = 'ok'
            state.final_assembly_status = 'ok'
            _write_json(_build_recipe_correction_audit(state=state, correction_input=correction_inputs_by_recipe_id[state.recipe_id], correction_output=correction_output, corrected_candidate=corrected_candidate, final_payload=final_payload, final_assembly_status='ok', structural_audit=structural_audit, mapping_status=state.correction_mapping_status, mapping_reason=state.correction_mapping_reason), correction_audit_dir / _recipe_artifact_filename(state.recipe_id))
            intermediate_overrides[state.recipe_id] = corrected_candidate.model_dump(mode='json', by_alias=True, exclude_none=True)
            authoritative_recipe_payloads[state.recipe_id] = authoritative_payload
            final_overrides[state.recipe_id] = draft_model.model_dump(mode='json', by_alias=True, exclude_none=True)
            updated_recipes_by_id[state.recipe_id] = corrected_candidate
    updated_result.recipes = [updated_recipes_by_id.get(str(recipe.identifier or ''), recipe) for recipe in updated_result.recipes if str(recipe.identifier or '') not in explicitly_rejected_recipe_ids]
    manifest_path = llm_raw_dir / RECIPE_MANIFEST_FILE_NAME
    manifest = _build_single_correction_manifest(run_settings=run_settings, llm_raw_dir=llm_raw_dir, correction_audit_dir=correction_audit_dir, manifest_path=manifest_path, states=states, process_runs=process_runs, output_schema_paths=output_schema_paths, timing_seconds=correction_seconds, recipe_shards=recipe_shards, phase_runtime_dir=phase_runtime_dir if recipe_shards else None, phase_runtime_summary=phase_runtime_summary)
    _write_json(manifest, manifest_path)
    return CodexFarmApplyResult(updated_conversion_result=updated_result, authoritative_recipe_payloads_by_recipe_id=authoritative_recipe_payloads, llm_report={'enabled': True, 'pipeline': SINGLE_CORRECTION_RECIPE_PIPELINE_ID, 'counts': manifest['counts'], 'timing': manifest['timing'], 'process_runs': manifest['process_runs'], 'output_schema_paths': dict(output_schema_paths), 'phase_runtime': dict(phase_runtime_summary), 'llmRawDir': str(llm_raw_dir)}, llm_raw_dir=llm_raw_dir, recipe_divestments=recipe_divestments)

def _build_single_correction_execution_plan(*, conversion_result: ConversionResult, run_settings: RunSettings, workbook_slug: str) -> dict[str, Any]:
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    planned_tasks: list[dict[str, Any]] = []
    planned_shards: list[dict[str, Any]] = []
    shard_ids_by_recipe_id: dict[str, str] = {}
    requested_shard_count = _resolve_recipe_shard_count(total_items=len(states), run_settings=run_settings)
    shard_groups = partition_contiguous_items(states, shard_count=requested_shard_count)
    for shard_index, shard_states in enumerate(shard_groups):
        shard_states_list = list(shard_states)
        if not shard_states_list:
            continue
        shard_id = f'recipe-shard-{shard_index:04d}-r{_recipe_index_from_bundle_name(shard_states_list[0].bundle_name):04d}-r{_recipe_index_from_bundle_name(shard_states_list[-1].bundle_name):04d}'
        recipe_ids = [state.recipe_id for state in shard_states_list]
        for recipe_id in recipe_ids:
            shard_ids_by_recipe_id[recipe_id] = shard_id
        planned_shards.append({'shard_id': shard_id, 'recipe_ids': recipe_ids, 'recipe_count': len(recipe_ids)})
    for recipe_index, state in enumerate(states):
        planned_tasks.append({'recipe_id': state.recipe_id, 'recipe_index': recipe_index, 'bundle_name': state.bundle_name, 'shard_id': shard_ids_by_recipe_id.get(state.recipe_id), 'planned_stages': [{'stage_key': 'recipe_build_intermediate', 'kind': 'deterministic'}, {'stage_key': 'recipe_refine', 'kind': 'llm', 'pipeline_id': SINGLE_CORRECTION_STAGE_PIPELINE_ID}, {'stage_key': 'recipe_build_final', 'kind': 'deterministic'}]})
    return {'enabled': True, 'pipeline': SINGLE_CORRECTION_RECIPE_PIPELINE_ID, 'recipe_count': len(states), 'recipe_prompt_target_count': run_settings.recipe_prompt_target_count, 'worker_count': _recipe_worker_count(run_settings, shard_count=len(planned_shards)), 'planned_shards': planned_shards, 'pipelines': {'recipe_correction': SINGLE_CORRECTION_STAGE_PIPELINE_ID}, 'codex_farm_model': run_settings.codex_farm_model, 'codex_farm_reasoning_effort': _effort_override_value(run_settings.codex_farm_reasoning_effort), 'planned_tasks': planned_tasks}

def run_codex_farm_recipe_pipeline(*, conversion_result: ConversionResult, run_settings: RunSettings, run_root: Path, workbook_slug: str, runner: CodexExecRunner | None=None, full_blocks: list[dict[str, Any]] | None=None, progress_callback: Callable[[str], None] | None=None) -> CodexFarmApplyResult:
    if run_settings.llm_recipe_pipeline.value == 'off':
        return CodexFarmApplyResult(updated_conversion_result=conversion_result, authoritative_recipe_payloads_by_recipe_id={}, llm_report={'enabled': False, 'pipeline': 'off'}, llm_raw_dir=run_root / 'raw' / 'llm' / sanitize_for_filename(workbook_slug), recipe_divestments=[])
    return _run_single_correction_recipe_pipeline(conversion_result=conversion_result, run_settings=run_settings, run_root=run_root, workbook_slug=workbook_slug, runner=runner, full_blocks=full_blocks, progress_callback=progress_callback)

def build_codex_farm_recipe_execution_plan(*, conversion_result: ConversionResult, run_settings: RunSettings, workbook_slug: str, full_blocks: list[dict[str, Any]] | None=None) -> dict[str, Any]:
    if run_settings.llm_recipe_pipeline.value == 'off':
        return {'enabled': False, 'pipeline': 'off', 'recipe_count': len(conversion_result.recipes), 'planned_tasks': []}
    return _build_single_correction_execution_plan(conversion_result=conversion_result, run_settings=run_settings, workbook_slug=workbook_slug)

def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')

def _load_json_dict_safely(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}
_STRUCTURAL_STATUS_PRECEDENCE = {'ok': 0, 'degraded': 1, 'failed': 2}

def _merge_structural_audit(*, state: _RecipeState, audit: StructuralAuditResult) -> None:
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
        root = Path(__file__).resolve().parents[2] / 'llm_pipelines'
    required = ('pipelines', 'prompts', 'schemas')
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(f'Invalid codex-farm pipeline root {root}: missing {', '.join(missing)}.')
    return root

def _non_empty(value: Any, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ''
    return rendered or fallback

def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get('file_hash') or provenance.get('fileHash')
        if source_hash:
            return str(source_hash)
    return 'unknown'

def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _recipe_location(recipe: RecipeCandidate) -> dict[str, Any]:
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    location = provenance.get('location')
    if not isinstance(location, dict):
        location = {}
        provenance['location'] = location
        recipe.provenance = provenance
    return location

def _build_states(result: ConversionResult, *, workbook_slug: str) -> list[_RecipeState]:
    states: list[_RecipeState] = []
    for index, recipe in enumerate(result.recipes):
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        recipe_id = ensure_recipe_id(recipe.identifier or provenance.get('@id') or provenance.get('id'), workbook_slug=workbook_slug, recipe_index=index)
        recipe.identifier = recipe_id
        if not isinstance(recipe.provenance, dict):
            recipe.provenance = {}
        recipe.provenance['@id'] = recipe_id
        if 'id' in recipe.provenance:
            recipe.provenance['id'] = recipe_id
        location = _recipe_location(recipe)
        start_raw = location.get('start_block') if 'start_block' in location else location.get('startBlock')
        end_raw = location.get('end_block') if 'end_block' in location else location.get('endBlock')
        heuristic_start = _coerce_int(start_raw)
        heuristic_end = _coerce_int(end_raw)
        states.append(_RecipeState(recipe=recipe, recipe_id=recipe_id, bundle_name=bundle_filename(recipe_id, recipe_index=index), heuristic_start=heuristic_start, heuristic_end=heuristic_end))
    return states

def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    artifacts = sorted(result.raw_artifacts, key=lambda item: 0 if str(item.location_id) == 'full_text' else 1)
    for artifact in artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get('blocks')
        if isinstance(blocks, list) and blocks:
            candidate_rows: list[Any] = blocks
        elif str(artifact.location_id) == 'full_text':
            lines = content.get('lines')
            candidate_rows = lines if isinstance(lines, list) else []
        else:
            candidate_rows = []
        for raw_block in candidate_rows:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get('index'))
            if index is None:
                continue
            if index in by_index:
                continue
            payload = dict(raw_block)
            payload['index'] = index
            payload['text'] = str(payload.get('text') or '')
            by_index[index] = payload
    return [by_index[index] for index in sorted(by_index)]

def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get('index'))
        if index is None:
            continue
        payload = dict(block)
        payload['index'] = index
        block_id = payload.get('block_id') or payload.get('id')
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f'b{index}'
        payload['block_id'] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item['index']))
    return prepared

def _normalize_mapping_reason_token(value: str | None) -> str:
    rendered = str(value or '').strip().lower()
    rendered = re.sub('[^a-z0-9]+', '_', rendered)
    return rendered.strip('_')

def _classify_recipe_correction_mapping_status(*, draft_payload: dict[str, Any], correction_output: MergedRecipeRepairOutput, ingredient_step_mapping: dict[str, Any] | None, ingredient_step_mapping_reason: str | None) -> tuple[str, str | None]:
    mapping_payload = ingredient_step_mapping if isinstance(ingredient_step_mapping, dict) else {}
    rendered_reason = str(ingredient_step_mapping_reason or '').strip() or None
    if mapping_payload:
        return ('mapped', rendered_reason)
    if rendered_reason:
        normalized_reason = _normalize_mapping_reason_token(rendered_reason)
        if any((token in normalized_reason for token in ('not_needed', 'not_applicable', 'single_step', 'single_ingredient', 'single_action', 'already_ordered'))):
            return ('not_needed', rendered_reason)
        return ('unclear', rendered_reason)
    ingredient_count = sum((1 for item in correction_output.canonical_recipe.ingredients if str(item).strip()))
    steps_payload = draft_payload.get('steps')
    step_count = sum((1 for step in steps_payload if isinstance(step, dict) and str(step.get('instruction') or '').strip())) if isinstance(steps_payload, list) else 0
    if ingredient_count >= 2 and step_count >= 2:
        return ('missing_reason', None)
    return ('not_needed_implicit', None)

def _classify_recipe_correction_structural_audit(*, correction_output: MergedRecipeRepairOutput, draft_payload: dict[str, Any]) -> StructuralAuditResult:
    reason_codes: list[str] = []
    title = str(correction_output.canonical_recipe.title or '').strip()
    if _is_placeholder_recipe_title(title):
        reason_codes.append('placeholder_title')
    steps_payload = draft_payload.get('steps')
    if not isinstance(steps_payload, list):
        reason_codes.append('missing_steps')
        return _build_structural_audit(reason_codes)
    rendered_steps: list[str] = []
    for step in steps_payload:
        if not isinstance(step, dict):
            continue
        instruction = str(step.get('instruction') or '').strip()
        if instruction:
            rendered_steps.append(instruction)
    if not rendered_steps:
        reason_codes.append('missing_steps')
    elif all((_is_placeholder_instruction(step) for step in rendered_steps)):
        reason_codes.append('placeholder_steps_only')
    blocked_description = _normalize_audit_text(str(correction_output.canonical_recipe.description or ''))
    extracted_instruction_set = {_normalize_audit_text(str(item)) for item in correction_output.canonical_recipe.steps if _normalize_audit_text(str(item))}
    if len(blocked_description) >= 20:
        for step in rendered_steps:
            normalized_step = _normalize_audit_text(step)
            if normalized_step and normalized_step not in extracted_instruction_set and (blocked_description == normalized_step or blocked_description in normalized_step or normalized_step in blocked_description):
                reason_codes.append('step_matches_schema_description')
                break
    mapping_payload = correction_output.ingredient_step_mapping
    rendered_mapping_reason = str(correction_output.ingredient_step_mapping_reason or '').strip()
    nonempty_ingredients = [str(item).strip() for item in correction_output.canonical_recipe.ingredients if str(item).strip()]
    if not mapping_payload and (not rendered_mapping_reason) and (len(nonempty_ingredients) >= 2) and (len(rendered_steps) >= 2):
        reason_codes.append('empty_mapping_without_reason')
    return _build_structural_audit(reason_codes)

def _build_structural_audit(reason_codes: list[str]) -> StructuralAuditResult:
    normalized = _unique_reason_codes(reason_codes)
    if not normalized:
        return StructuralAuditResult(status='ok', severity='none', reason_codes=[])
    return StructuralAuditResult(status='degraded', severity='soft', reason_codes=normalized)

def _unique_reason_codes(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or '').strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        rows.append(rendered)
    return rows

def _normalize_audit_text(value: str) -> str:
    rendered = str(value or '').strip().lower()
    rendered = re.sub('[^a-z0-9]+', ' ', rendered)
    return re.sub('\\s+', ' ', rendered).strip()

def _is_placeholder_instruction(value: str) -> bool:
    return _normalize_audit_text(value) in _AUDIT_PLACEHOLDER_STEP_TEXTS

def _is_placeholder_recipe_title(value: str) -> bool:
    return _normalize_audit_text(value) in _AUDIT_PLACEHOLDER_TITLES
