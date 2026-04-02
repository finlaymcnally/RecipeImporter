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
from ..codex_farm_contracts import MergedRecipeRepairInput, MergedRecipeRepairOutput, RecipeCorrectionShardInput, RecipeCorrectionShardOutput, RecipeCorrectionShardRecipeInput, StructuralAuditResult, load_contract_json, serialize_merged_recipe_repair_input, serialize_recipe_correction_shard_input
from ..codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from ..codex_farm_runner import CodexFarmRunnerError
from ..codex_exec_runner import DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, CodexExecLiveSnapshot, CodexExecRunResult, CodexExecRunner, CodexExecSupervisionDecision, SubprocessCodexExecRunner, classify_taskfile_worker_command, detect_taskfile_worker_boundary_violation, format_watchdog_command_reason_detail, format_watchdog_command_loop_reason_detail, is_single_file_workspace_command_drift_policy, should_terminate_workspace_command_loop, summarize_direct_telemetry_rows
from ..editable_task_file import TASK_FILE_NAME, build_repair_task_file, build_task_file, load_task_file, validate_edited_task_file, write_task_file
from ..phase_worker_runtime import PhaseManifestV1, ShardManifestEntryV1, ShardProposalV1, TaskManifestEntryV1, WorkerAssignmentV1, WorkerExecutionReportV1, resolve_phase_worker_count
from ..recipe_workspace_tools import build_recipe_worker_scaffold, recipe_worker_task_paths, validate_recipe_worker_draft
from ..recipe_tagging_guide import build_recipe_tagging_guide
from ..shard_survivability import attach_observed_telemetry_to_survivability_report, ShardSurvivabilityPreflightError, count_structural_output_tokens, count_tokens_for_model, evaluate_stage_survivability
from ..shard_prompt_targets import partition_contiguous_items, resolve_shard_count
from ..task_file_guardrails import build_task_file_guardrail, build_worker_session_guardrails, summarize_task_file_guardrails
from ..recipe_same_session_handoff import RECIPE_SAME_SESSION_STATE_ENV, initialize_recipe_same_session_state
from ..single_file_worker_commands import build_single_file_worker_surface
from ..taskfile_progress import decorate_active_worker_label, summarize_taskfile_health
from ..worker_hint_sidecars import preview_text, write_worker_hint_markdown
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

def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}

@dataclass(frozen=True)
class _RecipeTaskPlan:
    task_id: str
    parent_shard_id: str
    manifest_entry: ShardManifestEntryV1

def _build_recipe_task_file_unit(*, task_plan: _RecipeTaskPlan) -> dict[str, Any]:
    payload = _coerce_dict(task_plan.manifest_entry.input_payload)
    recipe_row = _coerce_dict((payload.get('r') or [{}])[0])
    recipe_id = str(recipe_row.get('rid') or '').strip() or task_plan.task_id
    hint_payload = _coerce_dict(recipe_row.get('h'))
    source_text = str(recipe_row.get('txt') or payload.get('txt') or '').strip()
    source_rows = [list(row) for row in recipe_row.get('ev') or payload.get('ev') or [] if isinstance(row, (list, tuple)) and len(row) >= 2]
    return {'unit_id': f'recipe::{recipe_id}', 'owned_id': recipe_id, 'evidence': {'recipe_id': recipe_id, 'source_text': source_text, 'source_rows': source_rows, 'hint': {'title': hint_payload.get('n'), 'ingredients': list(hint_payload.get('i') or []), 'steps': list(hint_payload.get('s') or []), 'quality_flags': list(hint_payload.get('q') or []), 'candidate_tags': list(hint_payload.get('tags') or [])}}, 'answer': {}}

def _recipe_task_file_helper_commands() -> dict[str, str]:
    return build_single_file_worker_surface(stage_key='recipe_refine').helper_commands

def _recipe_task_file_answer_schema() -> dict[str, Any]:
    return {'editable_pointer_pattern': '/units/*/answer', 'required_keys': ['status', 'canonical_recipe', 'ingredient_step_mapping', 'ingredient_step_mapping_reason', 'divested_block_indices', 'selected_tags', 'warnings'], 'allowed_values': {'status': ['repaired', 'fragmentary', 'not_a_recipe']}, 'example_answers': [{'status': 'repaired', 'status_reason': None, 'canonical_recipe': {'title': 'Toast', 'ingredients': ['1 slice bread'], 'steps': ['Toast the bread.'], 'description': None, 'recipe_yield': None}, 'ingredient_step_mapping': [], 'ingredient_step_mapping_reason': 'not_needed_single_step', 'divested_block_indices': [], 'selected_tags': [], 'warnings': []}]}

def _build_recipe_task_file(*, assignment: WorkerAssignmentV1, runnable_tasks: Sequence[_RecipeTaskPlan]) -> dict[str, Any]:
    return build_task_file(stage_key='recipe_refine', assignment_id=assignment.worker_id, worker_id=assignment.worker_id, units=[_build_recipe_task_file_unit(task_plan=task_plan) for task_plan in runnable_tasks], helper_commands=_recipe_task_file_helper_commands(), workflow=build_single_file_worker_surface(stage_key='recipe_refine').workflow, next_action='Review the task with task-summary/task-show-unit, edit answer objects in task.json, optionally use task-template plus task-apply, then run task-handoff.', answer_schema=_recipe_task_file_answer_schema())

def _recipe_artifact_filename(recipe_id: str) -> str:
    rendered = sanitize_for_filename(str(recipe_id).strip())
    if not rendered:
        rendered = 'recipe'
    return f'{rendered}.json'

def _build_recipe_task_runtime_manifest_entry(task_plan: _RecipeTaskPlan) -> TaskManifestEntryV1:
    task_manifest = task_plan.manifest_entry
    metadata = dict(task_manifest.metadata or {})
    metadata.setdefault('input_path', f'in/{task_plan.task_id}.json')
    metadata.setdefault('hint_path', f'hints/{task_plan.task_id}.md')
    metadata.setdefault('result_path', f'out/{task_plan.task_id}.json')
    return TaskManifestEntryV1(task_id=task_plan.task_id, task_kind='recipe_correction_recipe', parent_shard_id=task_plan.parent_shard_id, owned_ids=tuple(task_manifest.owned_ids), input_payload=task_manifest.input_payload, input_text=task_manifest.input_text, metadata=metadata)

def _recipe_task_result_path(task_plan: _RecipeTaskPlan) -> Path:
    metadata = _coerce_dict(task_plan.manifest_entry.metadata)
    result_path = str(metadata.get('result_path') or f'out/{task_plan.task_id}.json').strip()
    return Path(result_path)

def _write_recipe_task_payload(*, output_path: Path, payload: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + '\n', encoding='utf-8')

def _build_recipe_task_file_worker_prompt(*, task_count: int, repair_mode: bool, fresh_session_resume: bool=False) -> str:
    lines = ['You are a recipe correction worker in a bounded local workspace.', '', 'Resume from the existing `task.json` and current workspace state.' if fresh_session_resume else f'Start with `task-summary`. If you need the payload for specific units, use `task-show-unit <unit_id>` or `task-show-unanswered --limit 5`. Then edit only `/units/*/answer` in `{TASK_FILE_NAME}`, save the same file, and run `task-handoff`.', '`task.json` already contains the full job for this worker. You do not need extra manifests, queue state, or hidden context before editing it.', 'The helper is the only repo-side handoff seam. It validates the edited file and either completes the assignment or rewrites `task.json` into repair mode for the same session.', 'If you briefly reread part of the file or make a small local false start, correct it and continue.', 'Do not rewrite immutable metadata or evidence fields.', 'Do not invent helper ledgers, queue files, or alternate output files.', 'The repo will expand accepted answers into final artifacts after the helper validates them.']
    if repair_mode:
        lines.extend(['', 'Repair mode:', '- only the units in this file failed the previous validation pass', '- each failed unit includes immutable `previous_answer` and `validation_feedback`', '- fix only the named problems and keep all other immutable fields unchanged'])
    else:
        lines.extend(['', f'This worker session owns {task_count} recipe task units.'])
    lines.extend(['', 'Worker contract:', '- Start with `task.json`.', '- Prefer `task-summary` before opening raw file contents.', '- If the file is large, inspect only the units you need with `task-show-unit <unit_id>` or `task-show-unanswered --limit 5`.', '- If you need orientation first, run `task-status`.', '- If the workspace feels inconsistent, run `task-doctor` before inventing shell scripts.', '- Edit only the `answer` object inside each unit.', '- If you want a repo-owned batch write path, run `task-template answers.json`, fill only the answer payloads, then run `task-apply answers.json`.', '- After each edit pass, run `task-handoff` from the workspace root.', '- If the helper reports `repair_required`, reopen the rewritten `task.json` immediately, fix only the named issues, and run the helper again.', '- Stop only after the helper reports `completed`.', '- Do not dump `task.json` with `cat` or `sed`, do not use `ls` or `find` just to orient yourself, and do not write ad hoc inline Python, Node, or heredoc rewrites against `task.json`.', '- Other than repo-owned helper commands and tiny temp-file helpers, avoid shell on the happy path.', '', 'Recipe answer rules:', '- `status` must be one of `repaired`, `fragmentary`, or `not_a_recipe`.', '- When `status=repaired`, provide `canonical_recipe.title`, `ingredients`, and `steps`.', '- Use `ingredient_step_mapping` only for real ingredient-to-step links.', '- `divested_block_indices` must list any owned evidence block indices that no longer belong to the recipe.', '- When `status=fragmentary` or `status=not_a_recipe`, divest every owned evidence block.', '- Keep `selected_tags` as a short list of obvious semantic tag labels.', '- Keep `warnings` concise.'])
    return '\n'.join(lines)
