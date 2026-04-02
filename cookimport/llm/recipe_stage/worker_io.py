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

def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write('\n')

def _serialize_compact_prompt_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n'

def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding='utf-8')
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding='utf-8')
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')

def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)

def _recipe_same_session_state_path(worker_root: Path) -> Path:
    return worker_root / '_repo_control' / _RECIPE_SAME_SESSION_STATE_FILE_NAME

def _recipe_task_file_useful_progress(*, task_file_path: Path, original_task_file: Mapping[str, Any], same_session_state_payload: Mapping[str, Any]) -> bool:
    if not task_file_path.exists():
        return False
    if int(same_session_state_payload.get('same_session_transition_count') or 0) > 0:
        return True
    try:
        edited_task_file = load_task_file(task_file_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    _answers_by_unit_id, _errors, metadata = validate_edited_task_file(original_task_file=original_task_file, edited_task_file=edited_task_file, allow_immutable_field_changes=True)
    return bool(int(metadata.get('changed_unit_count') or 0) > 0)

def _recipe_hard_boundary_failure(run_result: CodexExecRunResult) -> bool:
    if str(run_result.supervision_state or '').strip() == 'watchdog_killed':
        return True
    reason_code = str(run_result.supervision_reason_code or '').strip()
    return reason_code.startswith('watchdog_') or 'boundary' in reason_code

def _recipe_retryable_runner_exception_reason(exc: CodexFarmRunnerError) -> str | None:
    message = ' '.join(str(exc or '').strip().lower().split())
    if not message:
        return None
    if 'timed out' in message:
        return 'codex_exec_timeout'
    if 'killed' in message or 'terminated' in message or 'interrupt' in message:
        return 'codex_exec_killed'
    return None

def _recipe_catastrophic_run_result_reason(run_result: CodexExecRunResult) -> str | None:
    if not _recipe_hard_boundary_failure(run_result):
        return None
    reason_code = str(run_result.supervision_reason_code or '').strip()
    if reason_code:
        return reason_code
    if str(run_result.supervision_state or '').strip() == 'watchdog_killed':
        return 'watchdog_killed'
    return 'catastrophic_worker_failure'

def _should_attempt_recipe_fresh_worker_replacement(*, run_result: CodexExecRunResult | None=None, exc: CodexFarmRunnerError | None=None, replacement_attempt_count: int, same_session_state_payload: Mapping[str, Any]) -> tuple[bool, str]:
    if int(replacement_attempt_count) >= 1:
        return (False, 'fresh_worker_replacement_budget_spent')
    if bool(same_session_state_payload.get('completed')):
        return (False, 'same_session_already_completed')
    if exc is not None:
        retry_reason = _recipe_retryable_runner_exception_reason(exc)
        if retry_reason is None:
            return (False, 'runner_exception_not_retryable')
        return (True, retry_reason)
    if run_result is not None:
        retry_reason = _recipe_catastrophic_run_result_reason(run_result)
        if retry_reason is None:
            return (False, 'worker_session_not_catastrophic')
        return (True, retry_reason)
    return (False, 'fresh_worker_replacement_not_applicable')

def _should_attempt_recipe_fresh_session_retry(*, run_result: CodexExecRunResult, task_file_path: Path, original_task_file: Mapping[str, Any], same_session_state_payload: Mapping[str, Any]) -> tuple[bool, str]:
    retry_limit = int(same_session_state_payload.get('fresh_session_retry_limit') or 0)
    retry_count = int(same_session_state_payload.get('fresh_session_retry_count') or 0)
    if retry_limit <= retry_count:
        return (False, 'fresh_session_retry_budget_spent')
    if bool(same_session_state_payload.get('completed')):
        return (False, 'same_session_already_completed')
    if str(same_session_state_payload.get('final_status') or '').strip() == 'repair_exhausted':
        return (False, 'same_session_repair_exhausted')
    if _recipe_hard_boundary_failure(run_result):
        return (False, 'hard_boundary_failure')
    if not run_result.completed_successfully():
        return (False, 'worker_session_not_clean')
    if not _recipe_task_file_useful_progress(task_file_path=task_file_path, original_task_file=original_task_file, same_session_state_payload=same_session_state_payload):
        return (False, 'no_preserved_progress')
    return (True, 'preserved_progress_without_completion')

def _write_recipe_worker_hint(*, path: Path, shard: ShardManifestEntryV1) -> None:
    payload = _coerce_dict(shard.input_payload)
    recipes = [row for row in payload.get('r') or [] if isinstance(row, Mapping)]
    hint_rows = [row for row in _coerce_dict(shard.metadata).get('worker_hint_recipes') or [] if isinstance(row, Mapping)]
    recipes_by_id = {str(row.get('rid') or '').strip(): row for row in recipes if str(row.get('rid') or '').strip()}
    recipe_lines: list[str] = []
    for hint_row in hint_rows[:12]:
        recipe_id = str(hint_row.get('recipe_id') or '').strip() or '[unknown recipe]'
        input_row = recipes_by_id.get(recipe_id, {})
        title_hint = str(hint_row.get('title_hint') or '').strip() or str(_coerce_dict(input_row.get('h')).get('n') or '').strip() or '[no title hint]'
        flags = [str(flag).strip() for flag in hint_row.get('quality_flags') or [] if str(flag).strip()]
        pre_context_rows = [f'{int(row.get('index', 0))}:{preview_text(row.get('text'), max_chars=60)}' for row in (hint_row.get('pre_context_rows') or [])[:2] if isinstance(row, Mapping)]
        post_context_rows = [f'{int(row.get('index', 0))}:{preview_text(row.get('text'), max_chars=60)}' for row in (hint_row.get('post_context_rows') or [])[:2] if isinstance(row, Mapping)]
        recipe_lines.append(f'`{recipe_id}` title hint `{preview_text(title_hint, max_chars=80)}` | evidence rows {int(hint_row.get('source_evidence_row_count') or 0)} | source ingredient-like {int(hint_row.get('source_ingredient_like_count') or 0)} | source instruction-like {int(hint_row.get('source_instruction_like_count') or 0)} | hint ingredients {int(hint_row.get('hint_ingredient_count') or 0)} | hint steps {int(hint_row.get('hint_step_count') or 0)} | flags `{', '.join(flags) or 'none'}` | before `{'; '.join(pre_context_rows) or 'none'}` | after `{'; '.join(post_context_rows) or 'none'}`')
    write_worker_hint_markdown(path, title=f'Recipe correction hints for {shard.shard_id}', summary_lines=['This sidecar is worker guidance only.', 'Open this file first, then open the authoritative `in/<shard_id>.json` file.', 'Choose `st=repaired` only when you can restate a real recipe. Choose `st=fragmentary` when recipe evidence exists but is too incomplete to normalize safely. Choose `st=not_a_recipe` when the owned text is not a recipe at all.', 'When `st=repaired`, `cr` must be a complete canonical recipe object. When `st` is `fragmentary` or `not_a_recipe`, set `cr` to null and explain the judgment briefly in `sr`.', f'Owned recipe candidates in this shard: {len(recipes)}.'], sections=[('How to use this packet', ['Treat immediate before/after context as a boundary clue only. The authoritative owned source rows still live in `in/<shard_id>.json`.', 'Do not force a repaired recipe when the source is better described as fragmentary or not_a_recipe.', 'Use tags only when they are obvious from the source text, and keep `g` empty otherwise.', 'Keep `m` and `mr` honest. If there is no meaningful ingredient-step mapping, leave `m` empty and say why in `mr`.']), ('Recipe candidate summaries', recipe_lines or ['No recipe summaries available.'])])

def _distribute_recipe_session_value(value: Any, task_count: int) -> list[int]:
    normalized_task_count = max(1, int(task_count))
    total = int(value or 0)
    base, remainder = divmod(total, normalized_task_count)
    return [base + (1 if index < remainder else 0) for index in range(normalized_task_count)]

def _build_recipe_workspace_task_runner_payload(*, pipeline_id: str, worker_id: str, shard_id: str, runtime_task_id: str, run_result: CodexExecRunResult, model: str | None, reasoning_effort: str | None, request_input_file: Path, worker_prompt_path: Path, worker_root: Path, task_count: int, task_index: int) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload['pipeline_id'] = pipeline_id
    telemetry = payload.get('telemetry')
    row_payload = None
    if isinstance(telemetry, Mapping):
        rows = telemetry.get('rows')
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            if isinstance(first_row, Mapping):
                row_payload = dict(first_row)
    request_input_file_str = str(request_input_file)
    request_input_file_bytes = request_input_file.stat().st_size if request_input_file.exists() else None
    worker_prompt_file_str = str(worker_prompt_path)
    if row_payload is not None:
        share_fields = ('duration_ms', 'tokens_input', 'tokens_cached_input', 'tokens_output', 'tokens_reasoning', 'visible_input_tokens', 'visible_output_tokens', 'wrapper_overhead_tokens')
        for field_name in share_fields:
            shares = _distribute_recipe_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        row_payload['tokens_total'] = int(row_payload.get('tokens_input') or 0) + int(row_payload.get('tokens_cached_input') or 0) + int(row_payload.get('tokens_output') or 0) + int(row_payload.get('tokens_reasoning') or 0)
        row_payload['prompt_input_mode'] = 'taskfile'
        row_payload['request_input_file'] = request_input_file_str
        row_payload['request_input_file_bytes'] = request_input_file_bytes
        row_payload['worker_prompt_file'] = worker_prompt_file_str
        row_payload['worker_session_task_count'] = task_count
        row_payload['worker_session_primary_row'] = task_index == 0
        row_payload['runtime_task_id'] = runtime_task_id
        row_payload['runtime_parent_shard_id'] = shard_id
        row_payload['events_path'] = str(worker_root / 'events.jsonl')
        row_payload['last_message_path'] = str(worker_root / 'last_message.json')
        row_payload['usage_path'] = str(worker_root / 'usage.json')
        row_payload['live_status_path'] = str(worker_root / 'live_status.json')
        row_payload['workspace_manifest_path'] = str(worker_root / 'workspace_manifest.json')
        row_payload['stdout_path'] = None
        row_payload['stderr_path'] = None
        if task_index > 0:
            row_payload['command_execution_count'] = 0
            row_payload['command_execution_commands'] = []
            row_payload['reasoning_item_count'] = 0
            row_payload['reasoning_item_types'] = []
            row_payload['codex_event_count'] = 0
            row_payload['codex_event_types'] = []
            row_payload['output_preview'] = None
            row_payload['output_preview_chars'] = 0
        telemetry['rows'] = [row_payload]
        telemetry['summary'] = summarize_direct_telemetry_rows([row_payload])
    payload['process_payload'] = {'pipeline_id': pipeline_id, 'status': 'done' if run_result.subprocess_exit_code == 0 else 'failed', 'codex_model': model, 'codex_reasoning_effort': reasoning_effort, 'prompt_input_mode': 'taskfile', 'request_input_file': request_input_file_str, 'request_input_file_bytes': request_input_file_bytes, 'worker_prompt_file': worker_prompt_file_str, 'runtime_task_id': runtime_task_id, 'runtime_parent_shard_id': shard_id, 'events_path': str(worker_root / 'events.jsonl'), 'last_message_path': str(worker_root / 'last_message.json'), 'usage_path': str(worker_root / 'usage.json'), 'live_status_path': str(worker_root / 'live_status.json'), 'workspace_manifest_path': str(worker_root / 'workspace_manifest.json'), 'stdout_path': None, 'stderr_path': None}
    return payload

def _build_recipe_workspace_session_runner_payload(*, pipeline_id: str, worker_id: str, primary_shard_id: str, run_result: CodexExecRunResult, model: str | None, reasoning_effort: str | None, worker_prompt_path: Path, worker_root: Path, task_count: int, parent_shard_ids: Sequence[str], repair_task_count: int) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=primary_shard_id)
    payload['pipeline_id'] = pipeline_id
    telemetry = payload.get('telemetry')
    row_payload = None
    if isinstance(telemetry, Mapping):
        rows = telemetry.get('rows')
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            if isinstance(first_row, Mapping):
                row_payload = dict(first_row)
    worker_prompt_file = str(worker_prompt_path)
    runtime_parent_shard_ids = [str(value).strip() for value in parent_shard_ids if str(value).strip()]
    if row_payload is not None:
        row_payload['prompt_input_mode'] = 'taskfile'
        row_payload['worker_prompt_file'] = worker_prompt_file
        row_payload['worker_session_task_count'] = int(task_count)
        row_payload['worker_session_primary_row'] = True
        row_payload['assigned_task_count'] = int(task_count)
        row_payload['repair_task_count'] = int(repair_task_count)
        row_payload['runtime_parent_shard_id'] = primary_shard_id
        row_payload['runtime_parent_shard_ids'] = runtime_parent_shard_ids
        row_payload['events_path'] = str(worker_root / 'events.jsonl')
        row_payload['last_message_path'] = str(worker_root / 'last_message.json')
        row_payload['usage_path'] = str(worker_root / 'usage.json')
        row_payload['live_status_path'] = str(worker_root / 'live_status.json')
        row_payload['workspace_manifest_path'] = str(worker_root / 'workspace_manifest.json')
        row_payload['stdout_path'] = None
        row_payload['stderr_path'] = None
        telemetry['rows'] = [row_payload]
        telemetry['summary'] = summarize_direct_telemetry_rows([row_payload])
    payload['process_payload'] = {'pipeline_id': pipeline_id, 'status': 'done' if run_result.subprocess_exit_code == 0 else 'failed', 'codex_model': model, 'codex_reasoning_effort': reasoning_effort, 'prompt_input_mode': 'taskfile', 'worker_prompt_file': worker_prompt_file, 'worker_session_task_count': int(task_count), 'assigned_task_count': int(task_count), 'repair_task_count': int(repair_task_count), 'runtime_parent_shard_id': primary_shard_id, 'runtime_parent_shard_ids': runtime_parent_shard_ids, 'events_path': str(worker_root / 'events.jsonl'), 'last_message_path': str(worker_root / 'last_message.json'), 'usage_path': str(worker_root / 'usage.json'), 'live_status_path': str(worker_root / 'live_status.json'), 'workspace_manifest_path': str(worker_root / 'workspace_manifest.json'), 'stdout_path': None, 'stderr_path': None}
    return payload

def _aggregate_recipe_worker_runner_payload(*, pipeline_id: str, worker_runs: Sequence[Mapping[str, Any]], stage_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in stage_rows if isinstance(row, Mapping)]
    uses_taskfile_contract = any((str((payload.get('process_payload') or {} if isinstance(payload, Mapping) else {}).get('prompt_input_mode') or '').strip() == 'taskfile' for payload in worker_runs if isinstance(payload, Mapping)))
    return {'runner_kind': 'codex_exec_direct', 'runtime_mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'pipeline_id': pipeline_id, 'worker_runs': [dict(payload) for payload in worker_runs], 'telemetry': {'rows': rows, 'summary': summarize_direct_telemetry_rows(rows)}, 'runtime_mode_audit': {'mode': DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'status': 'ok', 'output_schema_enforced': not uses_taskfile_contract, 'tool_affordances_requested': uses_taskfile_contract}}

def _render_events_jsonl(events: Sequence[dict[str, Any]]) -> str:
    if not events:
        return ''
    return ''.join((json.dumps(event, sort_keys=True) + '\n' for event in events))
