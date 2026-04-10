from __future__ import annotations
import csv
import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, cast
from cookimport.core.slug import slugify_name
from cookimport.runs import KNOWLEDGE_MANIFEST_FILE_NAME, RECIPE_MANIFEST_FILE_NAME, stage_label, stage_artifact_stem
from cookimport.runs.stage_names import canonical_stage_key
from .prompt_artifacts_loader import _resolve_recipe_id, _render_prompt_text, _collect_inserted_context_blocks, _telemetry_row_sort_key, _iter_process_run_payloads, _resolve_codex_exec_csv_paths, _load_codex_exec_rows_for_manifest, _load_run_assets_for_process_run, _collect_prompt_attachments, _resolve_saved_artifact_path, _parse_prompt_index_from_name, _load_prompt_rows, _load_json_sequence, _load_phase_runtime_index, _resolve_runtime_context, _prompt_row_sort_key, _upsert_text_section, _resolve_stage_run_root_for_prompt_exports, _copy_prompt_artifact_file
PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION = 'prompt_run_descriptor.v1'
PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION = 'prompt_stage_descriptor.v1'
PROMPT_CALL_RECORD_SCHEMA_VERSION = 'prompt_call_record.v1'
PROMPT_LOG_SUMMARY_SCHEMA_VERSION = 'prompt_log_summary.v1'
PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION = 'prompt_activity_trace.v1'
PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION = 'prompt_activity_trace_summary.v1'
PROMPT_LOG_SUMMARY_JSON_NAME = 'prompt_log_summary.json'
PROMPT_TYPE_SAMPLES_MD_NAME = 'prompt_type_samples_from_full_prompt_log.md'
ACTIVITY_TRACES_DIR_NAME = 'activity_traces'
ACTIVITY_TRACE_SUMMARY_JSONL_NAME = 'activity_trace_summary.jsonl'
ACTIVITY_TRACE_SUMMARY_MD_NAME = 'activity_trace_summary.md'
_CODEXFARM_STAGE_SPECS: tuple[dict[str, Any], ...] = ({'stage_key': 'recipe_refine', 'stage_order': 1, 'stage_label': stage_label('recipe_refine'), 'stage_artifact_stem': stage_artifact_stem('recipe_refine'), 'default_pipeline_id': 'recipe.correction.compact.v1', 'manifest_name': RECIPE_MANIFEST_FILE_NAME}, {'stage_key': 'nonrecipe_finalize', 'stage_order': 4, 'stage_label': stage_label('nonrecipe_finalize'), 'stage_artifact_stem': stage_artifact_stem('nonrecipe_finalize'), 'default_pipeline_id': 'recipe.knowledge.packet.v1', 'manifest_name': KNOWLEDGE_MANIFEST_FILE_NAME})
_CODEXFARM_STAGE_SPEC_BY_KEY: dict[str, dict[str, Any]] = {str(spec['stage_key']): spec for spec in _CODEXFARM_STAGE_SPECS}
_PROMPT_STAGE_LABELS_BY_KEY = {**{str(spec['stage_key']): str(spec['stage_label']) for spec in _CODEXFARM_STAGE_SPECS}, 'recipe_correction': stage_label('recipe_refine'), 'knowledge': stage_label('nonrecipe_finalize')}
_TEXT_ATTACHMENT_SUFFIXES = {'.json', '.jsonl', '.md', '.txt', '.yaml', '.yml', '.csv'}
_ACTIVITY_TRACE_MAX_ENTRIES = 25
_ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT = 3
__all__ = ['ACTIVITY_TRACES_DIR_NAME', 'ACTIVITY_TRACE_SUMMARY_JSONL_NAME', 'ACTIVITY_TRACE_SUMMARY_MD_NAME', 'PROMPT_CALL_RECORD_SCHEMA_VERSION', 'PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION', 'PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION', 'PROMPT_LOG_SUMMARY_JSON_NAME', 'PROMPT_LOG_SUMMARY_SCHEMA_VERSION', 'PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION', 'PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION', 'PROMPT_TYPE_SAMPLES_MD_NAME', 'build_codex_farm_activity_trace_summaries', 'PromptCallRecord', 'PromptRunDescriptorDiscoverer', 'PromptRunDescriptor', 'PromptStageDescriptor', 'build_codex_farm_prompt_response_log', 'build_prompt_response_log', 'build_codex_farm_prompt_type_samples_markdown', 'discover_prompt_run_descriptors', 'discover_codex_exec_prompt_run_descriptors', 'render_prompt_artifacts_from_descriptors', 'summarize_prompt_log', 'write_prompt_log_summary']
from .prompt_artifacts_discovery import PromptCallRecord, PromptStageDescriptor, PromptRunDescriptor, PromptRunDescriptorDiscoverer, _load_json_dict, _load_json_value, _safe_read_text, _resolve_artifact_path, _parse_json_text, _files_in_dir, _clean_text, _coerce_dict, _coerce_int, _coerce_bool, _parse_json_string_list, _timestamp_utc_for_path, _clean_prompt_stage_text, _derive_prompt_stage_key_from_pipeline_id, _fallback_prompt_stage_key, _prompt_stage_label_from_key, _build_prompt_stage_metadata, _prompt_stage_metadata_from_row, _resolve_process_run_payload_for_stage, _resolve_manifest_pipeline_id_for_stage, _resolve_stage_in_out_dirs, _runtime_stage_dir_name, discover_codex_exec_prompt_run_descriptors, discover_prompt_run_descriptors
from .prompt_artifacts_activity import _load_jsonl_events, _load_message_text, _activity_excerpt, _activity_path_excerpt, _extract_visible_reasoning_text, _summarize_activity_entry_lines, _build_activity_trace_from_events, _export_prompt_activity_trace, _resolve_prompt_local_activity_trace_path, _load_exported_activity_trace_payload, _effective_activity_trace_payload, _extract_reasoning_excerpt, build_codex_farm_activity_trace_summaries

def summarize_prompt_log(*, full_prompt_log_path: Path) -> dict[str, Any] | None:
    if not full_prompt_log_path.exists() or not full_prompt_log_path.is_file():
        return None
    by_stage: dict[str, dict[str, Any]] = {}
    unique_runtime_shard_keys: set[tuple[str, str]] = set()
    total_rows = 0
    rows_without_runtime_shard_id = 0
    try:
        lines = full_prompt_log_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, Mapping):
            continue
        total_rows += 1
        stage_key = canonical_stage_key(str(row.get('stage_key') or '').strip()) or 'unknown'
        stage_payload = by_stage.setdefault(stage_key, {'stage_key': stage_key, 'stage_label': _PROMPT_STAGE_LABELS_BY_KEY.get(stage_key, stage_key.replace('_', ' ').title()), 'stage_artifact_stem': str(row.get('stage_artifact_stem') or '').strip() or stage_artifact_stem(stage_key), 'row_count': 0, 'runtime_shard_count': 0, 'runtime_worker_count': 0, 'runtime_owned_id_count': 0, 'rows_without_runtime_shard_id': 0, '_runtime_shard_ids': set(), '_runtime_worker_ids': set(), '_runtime_owned_ids': set()})
        stage_payload['row_count'] += 1
        runtime_shard_id = str(row.get('runtime_shard_id') or '').strip()
        if runtime_shard_id:
            cast(set[str], stage_payload['_runtime_shard_ids']).add(runtime_shard_id)
            unique_runtime_shard_keys.add((stage_key, runtime_shard_id))
        else:
            rows_without_runtime_shard_id += 1
            stage_payload['rows_without_runtime_shard_id'] += 1
        runtime_worker_id = str(row.get('runtime_worker_id') or '').strip()
        if runtime_worker_id:
            cast(set[str], stage_payload['_runtime_worker_ids']).add(runtime_worker_id)
        runtime_owned_ids = row.get('runtime_owned_ids')
        if isinstance(runtime_owned_ids, list):
            for owned_id in runtime_owned_ids:
                owned_id_text = str(owned_id or '').strip()
                if owned_id_text:
                    cast(set[str], stage_payload['_runtime_owned_ids']).add(owned_id_text)
    if total_rows <= 0:
        return None
    for stage_payload in by_stage.values():
        stage_payload['runtime_shard_count'] = len(stage_payload.pop('_runtime_shard_ids'))
        stage_payload['runtime_worker_count'] = len(stage_payload.pop('_runtime_worker_ids'))
        stage_payload['runtime_owned_id_count'] = len(stage_payload.pop('_runtime_owned_ids'))
    runtime_shard_count = len(unique_runtime_shard_keys)
    runtime_shard_count_status = 'missing'
    if runtime_shard_count > 0:
        runtime_shard_count_status = 'complete' if rows_without_runtime_shard_id == 0 else 'partial'
    summary = {'schema_version': PROMPT_LOG_SUMMARY_SCHEMA_VERSION, 'full_prompt_log_rows': total_rows, 'runtime_shard_count': runtime_shard_count, 'runtime_shard_count_status': runtime_shard_count_status, 'rows_without_runtime_shard_id': rows_without_runtime_shard_id, 'by_stage': by_stage}
    _augment_prompt_log_summary_with_sidecar_stages(summary=summary, full_prompt_log_path=full_prompt_log_path)
    return summary


def _candidate_run_roots_for_prompt_summary(*, full_prompt_log_path: Path) -> list[Path]:
    candidates: list[Path] = []
    prompts_dir = full_prompt_log_path.parent
    if prompts_dir.name == 'prompts':
        candidates.append(prompts_dir.parent)
    candidates.append(prompts_dir)
    seen: set[Path] = set()
    resolved_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        resolved_candidates.append(candidate)
    return resolved_candidates


def _augment_prompt_log_summary_with_sidecar_stages(*, summary: dict[str, Any], full_prompt_log_path: Path) -> None:
    by_stage = summary.get('by_stage')
    if not isinstance(by_stage, dict):
        return
    for run_root in _candidate_run_roots_for_prompt_summary(full_prompt_log_path=full_prompt_log_path):
        telemetry_summary_path = run_root / 'line-role-pipeline' / 'telemetry_summary.json'
        if not telemetry_summary_path.exists() or not telemetry_summary_path.is_file():
            continue
        telemetry_summary = _load_json_dict(telemetry_summary_path) or {}
        stage_payload = by_stage.setdefault('line_role', {'stage_key': 'line_role', 'stage_label': stage_label('line_role'), 'stage_artifact_stem': stage_artifact_stem('line_role'), 'row_count': 0, 'runtime_shard_count': 0, 'runtime_worker_count': 0, 'runtime_owned_id_count': 0, 'rows_without_runtime_shard_id': 0})
        stage_payload.setdefault('stage_key', 'line_role')
        stage_payload.setdefault('stage_label', stage_label('line_role'))
        stage_payload.setdefault('stage_artifact_stem', stage_artifact_stem('line_role'))
        stage_payload.setdefault('row_count', 0)
        stage_payload.setdefault('runtime_shard_count', 0)
        stage_payload.setdefault('runtime_worker_count', 0)
        stage_payload.setdefault('runtime_owned_id_count', 0)
        stage_payload.setdefault('rows_without_runtime_shard_id', 0)
        stage_payload['artifact_presence'] = 'rows_and_sidecar' if int(stage_payload.get('row_count') or 0) > 0 else 'sidecar_only'
        stage_payload['artifact_evidence_path'] = str(telemetry_summary_path)
        sidecar_mode = _clean_text(telemetry_summary.get('mode'))
        if sidecar_mode is not None:
            stage_payload['artifact_evidence_mode'] = sidecar_mode
        break

def write_prompt_log_summary(*, full_prompt_log_path: Path, output_path: Path | None=None) -> Path | None:
    summary = summarize_prompt_log(full_prompt_log_path=full_prompt_log_path)
    if summary is None:
        return None
    target_path = output_path if output_path is not None else full_prompt_log_path.with_name(PROMPT_LOG_SUMMARY_JSON_NAME)
    target_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return target_path


def _structured_session_sidecar_path(*, response_path: Path, suffix: str, extension: str) -> Path | None:
    stem = response_path.stem
    if '_response_' in stem:
        prefix, tail = stem.split('_response_', 1)
        sibling_stem = f'{prefix}_{suffix}_{tail}'
    elif stem.startswith('response_'):
        sibling_stem = f'{suffix}_{stem[len("response_"):]}'
    elif stem.endswith('_response'):
        sibling_stem = f'{stem[:-len("_response")]}_{suffix}'
    else:
        return None
    candidate = response_path.with_name(f'{sibling_stem}{extension}')
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _resolve_structured_session_root(*, runtime_stage_root: Path | None, runtime_context: Mapping[str, Any] | None) -> Path | None:
    if runtime_stage_root is None or not isinstance(runtime_context, Mapping):
        return None
    runtime_shard_id = _clean_text(runtime_context.get('runtime_shard_id'))
    runtime_worker_id = _clean_text(runtime_context.get('runtime_worker_id'))
    if runtime_shard_id is None or runtime_worker_id is None:
        return None
    session_root = runtime_stage_root / 'workers' / runtime_worker_id / 'shards' / runtime_shard_id / 'structured_session'
    if not session_root.exists() or not session_root.is_dir():
        return None
    return session_root


def _runtime_context_identity_present(runtime_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(runtime_context, Mapping):
        return False
    runtime_shard_id = _clean_text(runtime_context.get('runtime_shard_id'))
    runtime_worker_id = _clean_text(runtime_context.get('runtime_worker_id'))
    return runtime_shard_id is not None or runtime_worker_id is not None


def _has_observed_runtime_call_evidence(*, runtime_stage_root: Path | None, runtime_context: Mapping[str, Any] | None) -> bool:
    if runtime_stage_root is None or not isinstance(runtime_context, Mapping):
        return False
    runtime_worker_id = _clean_text(runtime_context.get('runtime_worker_id'))
    if runtime_worker_id is None:
        return False
    worker_root = runtime_stage_root / 'workers' / runtime_worker_id
    evidence_paths = [
        worker_root / 'task.json',
        worker_root / 'prompt.txt',
        worker_root / 'usage.json',
        worker_root / 'events.jsonl',
        worker_root / 'last_message.json',
        worker_root / 'worker_manifest.json',
        worker_root / 'live_status.json',
    ]
    runtime_shard_id = _clean_text(runtime_context.get('runtime_shard_id'))
    if runtime_shard_id is not None:
        shard_root = worker_root / 'shards' / runtime_shard_id
        evidence_paths.extend(
            [
                shard_root / 'prompt.txt',
                shard_root / 'live_status.json',
            ]
        )
    return any(path.exists() and path.is_file() for path in evidence_paths)


def _load_structured_session_turn_artifacts(*, session_root: Path | None) -> list[dict[str, Any]]:
    if session_root is None:
        return []
    lineage_payload = _load_json_dict(session_root / 'session_lineage.json') or {}
    turns = lineage_payload.get('turns')
    if not isinstance(turns, list):
        return []
    rows: list[dict[str, Any]] = []
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        prompt_path = _resolve_artifact_path(session_root, turn.get('prompt_path'))
        response_path = _resolve_artifact_path(session_root, turn.get('response_path'))
        packet_path = _resolve_artifact_path(session_root, turn.get('packet_path'))
        if prompt_path is None or response_path is None:
            continue
        prompt_text = _safe_read_text(prompt_path)
        response_text = _safe_read_text(response_path)
        packet_text = _safe_read_text(packet_path) if packet_path is not None else ''
        usage_path = _structured_session_sidecar_path(
            response_path=response_path,
            suffix='usage',
            extension='.json',
        )
        events_path = _structured_session_sidecar_path(
            response_path=response_path,
            suffix='events',
            extension='.jsonl',
        )
        last_message_path = _structured_session_sidecar_path(
            response_path=response_path,
            suffix='last_message',
            extension='.json',
        )
        workspace_manifest_path = _structured_session_sidecar_path(
            response_path=response_path,
            suffix='workspace_manifest',
            extension='.json',
        )
        usage_payload = _load_json_dict(usage_path) if isinstance(usage_path, Path) else {}
        if not isinstance(usage_payload, dict):
            usage_payload = {}
        rows.append(
            {
                'turn_index': _coerce_int(turn.get('turn_index')) or (len(rows) + 1),
                'turn_kind': _clean_text(turn.get('turn_kind')) or f'turn_{len(rows) + 1}',
                'packet_path': packet_path,
                'packet_text': packet_text,
                'parsed_input': _parse_json_text(packet_text),
                'prompt_path': prompt_path,
                'prompt_text': prompt_text,
                'response_path': response_path,
                'response_text': response_text,
                'parsed_response': _parse_json_text(response_text),
                'usage_path': usage_path,
                'usage_payload': usage_payload,
                'events_path': events_path,
                'last_message_path': last_message_path,
                'workspace_manifest_path': workspace_manifest_path,
                'timestamp_utc': (
                    _timestamp_utc_for_path(response_path)
                    or _timestamp_utc_for_path(prompt_path)
                    or _timestamp_utc_for_path(packet_path)
                ),
            }
        )
    return rows

def build_codex_farm_prompt_type_samples_markdown(*, full_prompt_log_path: Path, output_path: Path, examples_per_pass: int=3) -> Path | None:
    if examples_per_pass <= 0:
        return None
    if not full_prompt_log_path.exists() or not full_prompt_log_path.is_file():
        return None
    samples_by_stage: dict[str, list[dict[str, Any]]] = {}
    stage_metadata_by_key: dict[str, dict[str, Any]] = {}
    stage_first_seen: dict[str, int] = {}
    try:
        with full_prompt_log_path.open('r', encoding='utf-8') as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                stage_metadata = _prompt_stage_metadata_from_row(row)
                stage_group_key = str(stage_metadata.get('heading_key') or '').strip()
                if not stage_group_key:
                    continue
                if stage_group_key not in samples_by_stage:
                    samples_by_stage[stage_group_key] = []
                    stage_metadata_by_key[stage_group_key] = dict(stage_metadata)
                    stage_first_seen[stage_group_key] = len(stage_first_seen)
                if len(samples_by_stage[stage_group_key]) >= examples_per_pass:
                    continue
                prompt_text: str | None = None
                request_messages = row.get('request_messages')
                if isinstance(request_messages, list) and request_messages:
                    first_message = request_messages[0]
                    if isinstance(first_message, dict):
                        content = first_message.get('content')
                        if isinstance(content, str):
                            prompt_text = content
                if prompt_text is None:
                    rendered_prompt_text = row.get('rendered_prompt_text')
                    if isinstance(rendered_prompt_text, str):
                        prompt_text = rendered_prompt_text
                if prompt_text is None:
                    user_prompt = row.get('user_prompt')
                    if isinstance(user_prompt, str):
                        prompt_text = user_prompt
                prompt_text = str(prompt_text or '')
                activity_trace_payload = _effective_activity_trace_payload(row=row, prompts_dir=full_prompt_log_path.parent)
                activity_trace_path: str | None = None
                activity_trace_available = False
                activity_trace_command_count: int | None = None
                activity_trace_agent_message_count: int | None = None
                activity_trace_reasoning_count: int | None = None
                activity_trace_excerpt_lines: list[str] = []
                if isinstance(activity_trace_payload, dict):
                    trace_path = activity_trace_payload.get('path')
                    if isinstance(trace_path, str) and trace_path.strip():
                        activity_trace_path = trace_path.strip()
                    activity_trace_available = bool(activity_trace_payload.get('available'))
                    command_count = activity_trace_payload.get('command_count')
                    if isinstance(command_count, int):
                        activity_trace_command_count = command_count
                    agent_message_count = activity_trace_payload.get('agent_message_count')
                    if isinstance(agent_message_count, int):
                        activity_trace_agent_message_count = agent_message_count
                    reasoning_count = activity_trace_payload.get('reasoning_event_count')
                    if isinstance(reasoning_count, int):
                        activity_trace_reasoning_count = reasoning_count
                    raw_entries = activity_trace_payload.get('entries')
                    if isinstance(raw_entries, list):
                        activity_trace_excerpt_lines = _summarize_activity_entry_lines([entry for entry in raw_entries if isinstance(entry, Mapping)])
                call_id = str(row.get('call_id') or '').strip() or '<unknown>'
                recipe_id = str(row.get('recipe_id') or '').strip() or '<unknown>'
                samples_by_stage[stage_group_key].append({'call_id': call_id, 'recipe_id': recipe_id, 'prompt': prompt_text.rstrip('\n'), 'activity_trace_available': activity_trace_available, 'activity_trace_path': activity_trace_path, 'activity_trace_command_count': activity_trace_command_count, 'activity_trace_agent_message_count': activity_trace_agent_message_count, 'activity_trace_reasoning_count': activity_trace_reasoning_count, 'activity_trace_excerpt_lines': activity_trace_excerpt_lines})
    except OSError:
        return None
    if not any(samples_by_stage.values()):
        return None
    generated_timestamp = dt.datetime.now().strftime('%Y-%m-%d_%H.%M.%S')
    lines: list[str] = ['# Codex Exec Prompt Samples (Literal)', '', f'Generated: {generated_timestamp}', 'Source:', f'- {full_prompt_log_path}', '', 'Notes:', '- Samples are verbatim from `request_messages[0].content` when available.', '- Includes full inline JSON payloads exactly as emitted.', f'- Up to {examples_per_pass} examples per discovered prompt stage.', '']
    occupied_stage_orders = {int(metadata.get('stage_order') or 999) for metadata in stage_metadata_by_key.values()}
    render_entries: list[tuple[str, dict[str, Any], list[dict[str, Any]], int]] = []
    for stage_group_key, metadata in stage_metadata_by_key.items():
        render_entries.append((stage_group_key, metadata, samples_by_stage.get(stage_group_key, []), stage_first_seen.get(stage_group_key, 0)))
    for stage_spec in _CODEXFARM_STAGE_SPECS:
        stage_key = str(stage_spec['stage_key'])
        stage_order = int(stage_spec.get('stage_order') or 999)
        if stage_order in occupied_stage_orders:
            continue
        placeholder_metadata = _build_prompt_stage_metadata(stage_key=stage_key, pipeline_id=_clean_prompt_stage_text(stage_spec.get('default_pipeline_id')))
        render_entries.append((str(placeholder_metadata.get('heading_key') or stage_key), placeholder_metadata, [], 999 + stage_order))
    render_entries.sort(key=lambda entry: (int(entry[1].get('stage_order') or 999), entry[3], entry[0]))
    for stage_group_key, metadata, stage_samples, _ in render_entries:
        stage_label = str(metadata.get('label') or 'Prompt Stage')
        lines.append(f'## {stage_group_key} ({stage_label})')
        lines.append('')
        pipeline_id = _clean_prompt_stage_text(metadata.get('pipeline_id'))
        if pipeline_id is not None:
            lines.append(f'- pipeline_id: `{pipeline_id}`')
            lines.append('')
        if not stage_samples:
            lines.append('_No rows captured for this stage._')
            lines.append('')
            continue
        for index, sample in enumerate(stage_samples, start=1):
            lines.append(f'### Example {index}')
            lines.append(f'call_id: `{sample['call_id']}`')
            lines.append(f'recipe_id: `{sample['recipe_id']}`')
            lines.append('')
            lines.append('```text')
            lines.append(sample['prompt'])
            lines.append('```')
            lines.append('')
            lines.append('Activity Trace:')
            activity_trace_available = bool(sample.get('activity_trace_available'))
            activity_trace_path = sample.get('activity_trace_path')
            activity_trace_command_count = sample.get('activity_trace_command_count')
            activity_trace_agent_message_count = sample.get('activity_trace_agent_message_count')
            activity_trace_reasoning_count = sample.get('activity_trace_reasoning_count')
            activity_trace_excerpt_lines = list(sample.get('activity_trace_excerpt_lines') or [])
            if activity_trace_path:
                lines.append(f'- path: `{activity_trace_path}`')
            if isinstance(activity_trace_command_count, int):
                lines.append(f'- command_count: `{activity_trace_command_count}`')
            if isinstance(activity_trace_agent_message_count, int):
                lines.append(f'- agent_message_count: `{activity_trace_agent_message_count}`')
            if isinstance(activity_trace_reasoning_count, int):
                lines.append(f'- reasoning_event_count: `{activity_trace_reasoning_count}`')
            if activity_trace_excerpt_lines:
                lines.append('- sample entries:')
                for excerpt_line in activity_trace_excerpt_lines:
                    lines.append(f'  - {excerpt_line}')
            elif not activity_trace_available:
                lines.append('- _No exported activity trace available for this sample._')
            lines.append('')
    try:
        output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError:
        return None
    return output_path

def _build_line_role_prompt_rows(*, pred_run: Path, eval_output_dir: Path, repo_root: Path) -> tuple[list[dict[str, Any]], str] | tuple[list[dict[str, Any]], None]:
    stage_run_root = _resolve_stage_run_root_for_prompt_exports(pred_run=pred_run)
    if stage_run_root is None:
        return ([], None)
    stage_prompt_dir = stage_run_root / 'line-role-pipeline' / 'prompts'
    if not stage_prompt_dir.exists() or not stage_prompt_dir.is_dir():
        return ([], None)
    prompts_dir = eval_output_dir / 'prompts'
    prompts_dir.mkdir(parents=True, exist_ok=True)
    export_dir = prompts_dir / 'line-role-pipeline'
    export_dir.mkdir(parents=True, exist_ok=True)
    telemetry_summary_path = stage_run_root / 'line-role-pipeline' / 'telemetry_summary.json'
    telemetry_summary = _load_json_dict(telemetry_summary_path) or {}
    phases = telemetry_summary.get('phases')
    phases_by_key: dict[str, dict[str, Any]] = {}
    if isinstance(phases, list):
        for phase_payload in phases:
            if not isinstance(phase_payload, dict):
                continue
            phase_key = _clean_text(phase_payload.get('phase_key'))
            if phase_key is not None:
                phases_by_key[phase_key] = phase_payload
    if telemetry_summary_path.exists() and telemetry_summary_path.is_file():
        _copy_prompt_artifact_file(source=telemetry_summary_path, target=export_dir / 'telemetry_summary.json')
    pred_run_manifest = _load_json_dict(pred_run / 'run_manifest.json') or {}
    pred_run_source = pred_run_manifest.get('source') if isinstance(pred_run_manifest.get('source'), dict) else {}
    source_file = None
    if isinstance(pred_run_source, dict):
        source_file = _clean_text(pred_run_source.get('path'))
    rows: list[dict[str, Any]] = []
    detail_lines: list[str] = []
    phase_specs = [{'phase_key': 'line_role', 'prompt_stem': 'line_role_prompt', 'stage_key': 'line_role', 'stage_label': 'Line Role', 'stage_artifact_stem': 'line_role', 'stage_order': 2}]
    for spec in phase_specs:
        phase_key = spec['phase_key']
        phase_prompt_dir = stage_prompt_dir / phase_key
        if not phase_prompt_dir.exists() or not phase_prompt_dir.is_dir():
            continue
        phase_export_dir = export_dir / phase_key
        phase_export_dir.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(phase_prompt_dir.iterdir(), key=lambda path: path.name):
            if source_path.is_file():
                _copy_prompt_artifact_file(source=source_path, target=phase_export_dir / source_path.name)
        runtime_stage_root = stage_run_root / 'line-role-pipeline' / 'runtime' / phase_key
        runtime_index = _load_phase_runtime_index(runtime_stage_root)
        phase_payload = phases_by_key.get(phase_key) or {}
        phase_batches = phase_payload.get('batches')
        batches_by_prompt_index: dict[int, dict[str, Any]] = {}
        if isinstance(phase_batches, list):
            for batch in phase_batches:
                if not isinstance(batch, dict):
                    continue
                prompt_index = _coerce_int(batch.get('prompt_index'))
                if prompt_index is not None:
                    batches_by_prompt_index[prompt_index] = batch
        detail_lines.extend([f'=== CATEGORY {spec['stage_key']} ({spec['stage_label']}) | stage_dir: line-role-pipeline/{phase_key} ===', f'source_dir: {phase_prompt_dir}', ''])
        prompt_glob = f'{spec['prompt_stem']}_*.txt'
        for prompt_file in sorted(phase_prompt_dir.glob(prompt_glob), key=lambda path: path.name):
            if f'{spec['prompt_stem']}_response_' in prompt_file.name or f'{spec['prompt_stem']}_parsed_' in prompt_file.name:
                continue
            prompt_index = _parse_prompt_index_from_name(prompt_file.name)
            if prompt_index is None:
                continue
            response_file = phase_prompt_dir / f'{spec['prompt_stem']}_response_{prompt_index:04d}.txt'
            parsed_file = phase_prompt_dir / f'{spec['prompt_stem']}_parsed_{prompt_index:04d}.json'
            exported_prompt_file = phase_export_dir / prompt_file.name
            exported_response_file = phase_export_dir / response_file.name
            exported_parsed_file = phase_export_dir / parsed_file.name
            prompt_text = _safe_read_text(prompt_file)
            response_text = _safe_read_text(response_file) if response_file.exists() else ''
            parsed_response = _load_json_value(parsed_file)
            if parsed_response is None:
                parsed_response = _parse_json_text(response_text)
            runtime_context = _resolve_runtime_context(runtime_index=runtime_index, prompt_index=prompt_index)
            runtime_telemetry_row = dict(runtime_context.get('runtime_telemetry_row')) if isinstance(runtime_context.get('runtime_telemetry_row'), dict) else {}
            input_file = Path(str(runtime_context.get('request_input_file'))) if _clean_text(runtime_context.get('request_input_file')) is not None else None
            debug_input_file = Path(str(runtime_context.get('debug_input_file'))) if _clean_text(runtime_context.get('debug_input_file')) is not None else None
            input_payload = _load_json_value(input_file) if input_file is not None else None
            input_text = _safe_read_text(input_file) if input_file is not None else ''
            debug_input_payload = _load_json_value(debug_input_file) if debug_input_file is not None else None
            debug_input_text = _safe_read_text(debug_input_file) if debug_input_file is not None else ''
            exported_input_file = None
            exported_debug_input_file = None
            if input_file is not None and input_file.exists():
                exported_input_file = phase_export_dir / 'in' / input_file.name
                _copy_prompt_artifact_file(source=input_file, target=exported_input_file)
            if debug_input_file is not None and debug_input_file.exists():
                exported_debug_input_file = phase_export_dir / 'debug' / debug_input_file.name
                _copy_prompt_artifact_file(source=debug_input_file, target=exported_debug_input_file)
            batch_payload = batches_by_prompt_index.get(prompt_index, {})
            attempts = batch_payload.get('attempts')
            attempt_payload = attempts[0] if isinstance(attempts, list) and attempts else {}
            process_run_payload = attempt_payload.get('process_run') if isinstance(attempt_payload, dict) else {}
            if not isinstance(process_run_payload, dict):
                process_run_payload = {}
            process_payload = process_run_payload.get('process_payload')
            if not isinstance(process_payload, dict):
                process_payload = {}
            pipeline_id = _clean_text(process_run_payload.get('pipeline_id')) or _clean_text(process_payload.get('pipeline_id')) or _clean_text((runtime_index or {}).get('pipeline_id')) or _clean_text(telemetry_summary.get('codex_farm_pipeline_id')) or 'line-role.canonical.v1'
            model_value = _clean_text(process_payload.get('codex_model'))
            reasoning_effort_value = _clean_text(process_payload.get('codex_reasoning_effort'))
            output_schema_path = _clean_text(process_run_payload.get('output_schema_path')) or _clean_text(process_payload.get('output_schema_path'))
            response_format_payload: dict[str, Any] | None = None
            if output_schema_path is not None:
                output_schema_payload = _load_json_dict(Path(output_schema_path))
                if isinstance(output_schema_payload, dict):
                    response_format_payload = {'type': 'json_schema', 'json_schema': output_schema_payload}
            usage_payload = attempt_payload.get('usage') if isinstance(attempt_payload, dict) and isinstance(attempt_payload.get('usage'), dict) else {}
            if not isinstance(usage_payload, dict):
                usage_payload = {}
            timestamp_utc = _timestamp_utc_for_path(prompt_file)
            call_id = f'{spec['prompt_stem']}_{prompt_index:04d}'
            structured_session_turns = _load_structured_session_turn_artifacts(
                session_root=_resolve_structured_session_root(
                    runtime_stage_root=runtime_stage_root,
                    runtime_context=runtime_context,
                )
            )
            if structured_session_turns:
                for turn_artifact in structured_session_turns:
                    turn_prompt_text = str(turn_artifact.get('prompt_text') or '')
                    turn_packet_text = str(turn_artifact.get('packet_text') or '')
                    turn_response_text = str(turn_artifact.get('response_text') or '')
                    turn_parsed_input = turn_artifact.get('parsed_input')
                    turn_parsed_response = turn_artifact.get('parsed_response')
                    turn_index = _coerce_int(turn_artifact.get('turn_index')) or 0
                    turn_kind = _clean_text(turn_artifact.get('turn_kind')) or f'turn_{turn_index or 0}'
                    turn_call_id = f"{runtime_context.get('runtime_shard_id') or call_id}__turn_{turn_index:02d}_{turn_kind}"
                    turn_request_messages = [{'role': 'user', 'content': turn_prompt_text}]
                    turn_usage_payload = dict(turn_artifact.get('usage_payload')) if isinstance(turn_artifact.get('usage_payload'), Mapping) else {}
                    turn_tokens_input = _coerce_int(turn_usage_payload.get('input_tokens')) or _coerce_int(turn_usage_payload.get('tokens_input'))
                    turn_tokens_cached_input = _coerce_int(turn_usage_payload.get('cached_input_tokens')) or _coerce_int(turn_usage_payload.get('tokens_cached_input'))
                    turn_tokens_output = _coerce_int(turn_usage_payload.get('output_tokens')) or _coerce_int(turn_usage_payload.get('tokens_output'))
                    turn_tokens_reasoning = _coerce_int(turn_usage_payload.get('reasoning_tokens')) or _coerce_int(turn_usage_payload.get('tokens_reasoning'))
                    turn_tokens_total = _coerce_int(turn_usage_payload.get('tokens_total'))
                    if turn_tokens_total is None:
                        turn_tokens_total = sum(value or 0 for value in (turn_tokens_input, turn_tokens_cached_input, turn_tokens_output, turn_tokens_reasoning))
                    turn_response_path = turn_artifact.get('response_path')
                    turn_request_telemetry = {
                        'status': 'ok' if turn_response_text.strip() else None,
                        'duration_ms': None,
                        'attempt_index': turn_index,
                        'prompt_index': prompt_index,
                        'candidate_count': _coerce_int(batch_payload.get('candidate_count')),
                        'requested_atomic_indices': list(batch_payload.get('requested_atomic_indices') or []),
                        'returncode': None,
                        'response_present': bool(turn_response_text.strip()),
                        'turn_failed_message': None,
                        'tokens_input': turn_tokens_input,
                        'tokens_cached_input': turn_tokens_cached_input,
                        'tokens_output': turn_tokens_output,
                        'tokens_reasoning': turn_tokens_reasoning,
                        'tokens_total': turn_tokens_total,
                        'worker_id': runtime_context.get('runtime_worker_id'),
                        'shard_id': runtime_context.get('runtime_shard_id'),
                        'owned_ids': list(runtime_context.get('runtime_owned_ids') or []),
                        'events_path': str(turn_artifact.get('events_path')) if isinstance(turn_artifact.get('events_path'), Path) else None,
                        'last_message_path': str(turn_artifact.get('last_message_path')) if isinstance(turn_artifact.get('last_message_path'), Path) else None,
                        'usage_path': str(turn_artifact.get('usage_path')) if isinstance(turn_artifact.get('usage_path'), Path) else None,
                        'live_status_path': None,
                        'workspace_manifest_path': str(turn_artifact.get('workspace_manifest_path')) if isinstance(turn_artifact.get('workspace_manifest_path'), Path) else None,
                        'stdout_path': None,
                        'stderr_path': None,
                    }
                    turn_row_payload = {
                        'run_id': eval_output_dir.name,
                        'schema_version': PROMPT_CALL_RECORD_SCHEMA_VERSION,
                        'call_id': turn_call_id,
                        'timestamp_utc': _clean_text(turn_artifact.get('timestamp_utc')) or timestamp_utc,
                        'recipe_id': f'{phase_key}_{prompt_index:04d}',
                        'source_file': source_file,
                        'pipeline_id': pipeline_id,
                        'stage_key': spec['stage_key'],
                        'stage_heading_key': spec['stage_key'],
                        'stage_label': spec['stage_label'],
                        'stage_artifact_stem': spec['stage_artifact_stem'],
                        'stage_dir_name': 'line-role-pipeline',
                        'stage_order': spec['stage_order'],
                        'process_run_id': _clean_text(process_payload.get('run_id')),
                        'model': model_value,
                        'prompt_input_mode': f'structured_session_{turn_kind}',
                        'request_payload_source': 'structured_session_prompt_artifact',
                        'request_messages': turn_request_messages,
                        'system_prompt': None,
                        'developer_prompt': None,
                        'user_prompt': turn_prompt_text,
                        'rendered_prompt_text': turn_prompt_text,
                        'rendered_messages': turn_request_messages,
                        'prompt_templates': {'prompt_template_text': None, 'prompt_template_path': None},
                        'template_vars': {'INPUT_PATH': str(turn_artifact.get('packet_path')) if isinstance(turn_artifact.get('packet_path'), Path) else None, 'INPUT_TEXT': turn_packet_text or None},
                        'inserted_context_blocks': _collect_inserted_context_blocks(turn_parsed_input),
                        'request': {'messages': turn_request_messages, 'tools': [], 'response_format': response_format_payload, 'model': model_value, 'reasoning_effort': reasoning_effort_value, 'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'pipeline_id': pipeline_id, 'sandbox': None, 'ask_for_approval': None, 'web_search': None, 'output_schema_path': output_schema_path},
                        'request_input_payload': turn_parsed_input,
                        'request_input_text': turn_packet_text or None,
                        'debug_input_payload': None,
                        'debug_input_text': None,
                        'task_prompt_text': turn_packet_text or None,
                        'tools': [],
                        'response_format': response_format_payload,
                        'decoding_params': {'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'reasoning_effort': reasoning_effort_value},
                        'raw_response': {'output_text': turn_response_text or None, 'output_file': str(turn_response_path) if isinstance(turn_response_path, Path) else None},
                        'parsed_response': turn_parsed_response,
                        'request_input_file': str(turn_artifact.get('packet_path')) if isinstance(turn_artifact.get('packet_path'), Path) else None,
                        'debug_input_file': None,
                        'request_telemetry': turn_request_telemetry,
                        'runtime_shard_id': runtime_context.get('runtime_shard_id'),
                        'runtime_worker_id': runtime_context.get('runtime_worker_id'),
                        'runtime_owned_ids': list(runtime_context.get('runtime_owned_ids') or []),
                        'runtime_turn_index': turn_index,
                        'runtime_turn_kind': turn_kind,
                        'activity_trace': None,
                    }
                    activity_trace_payload = _export_prompt_activity_trace(row_payload=turn_row_payload, prompts_dir=prompts_dir, repo_root=repo_root)
                    turn_row_payload['activity_trace'] = activity_trace_payload
                    if isinstance(activity_trace_payload, dict):
                        turn_request_telemetry['activity_trace_path'] = activity_trace_payload.get('path')
                    rows.append(turn_row_payload)
                    _append_structured_session_turn_to_category_log(
                        category=detail_lines,
                        stage_key=spec['stage_key'],
                        turn_kind=turn_kind,
                        turn_index=turn_index,
                        turn_prompt_text=turn_prompt_text,
                        turn_packet_text=turn_packet_text,
                        turn_response_text=turn_response_text,
                        turn_packet_path=turn_artifact.get('packet_path') if isinstance(turn_artifact.get('packet_path'), Path) else None,
                        turn_response_path=turn_response_path if isinstance(turn_response_path, Path) else None,
                    )
                continue
            detail_lines.append(f'INPUT {spec['stage_key']} => {prompt_file.name}')
            if exported_input_file is not None:
                detail_lines.append(f'task_file: {exported_input_file}')
            if exported_debug_input_file is not None:
                detail_lines.append(f'debug_task_file: {exported_debug_input_file}')
            detail_lines.append('-' * 80)
            detail_lines.append(prompt_text)
            detail_lines.append('-' * 80)
            detail_lines.append('')
            if response_file.exists():
                detail_lines.append(f'OUTPUT {spec['stage_key']} => {response_file.name}')
                detail_lines.append('-' * 80)
                detail_lines.append(response_text)
                detail_lines.append('-' * 80)
                detail_lines.append('')
            if parsed_file.exists():
                detail_lines.append(f'PARSED {spec['stage_key']} => {parsed_file.name}')
                detail_lines.append('-' * 80)
                detail_lines.append(_safe_read_text(parsed_file))
                detail_lines.append('-' * 80)
                detail_lines.append('')
            request_messages = [{'role': 'user', 'content': prompt_text}]
            row_payload = {'run_id': eval_output_dir.name, 'schema_version': PROMPT_CALL_RECORD_SCHEMA_VERSION, 'call_id': call_id, 'timestamp_utc': timestamp_utc, 'recipe_id': f'{phase_key}_{prompt_index:04d}', 'source_file': source_file, 'pipeline_id': pipeline_id, 'stage_key': spec['stage_key'], 'stage_heading_key': spec['stage_key'], 'stage_label': spec['stage_label'], 'stage_artifact_stem': spec['stage_artifact_stem'], 'stage_dir_name': 'line-role-pipeline', 'stage_order': spec['stage_order'], 'process_run_id': _clean_text(process_payload.get('run_id')), 'model': model_value, 'prompt_input_mode': _clean_text(runtime_telemetry_row.get('prompt_input_mode')) or 'path', 'request_payload_source': 'line_role_saved_prompt_text', 'request_messages': request_messages, 'system_prompt': None, 'developer_prompt': None, 'user_prompt': prompt_text, 'rendered_prompt_text': prompt_text, 'rendered_messages': request_messages, 'prompt_templates': {'prompt_template_text': None, 'prompt_template_path': None}, 'template_vars': {'INPUT_PATH': str(exported_input_file) if exported_input_file is not None else None, 'INPUT_TEXT': input_text or None}, 'inserted_context_blocks': [], 'request': {'messages': request_messages, 'tools': [], 'response_format': response_format_payload, 'model': model_value, 'reasoning_effort': reasoning_effort_value, 'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'pipeline_id': pipeline_id, 'sandbox': None, 'ask_for_approval': None, 'web_search': None, 'output_schema_path': output_schema_path}, 'request_input_payload': input_payload, 'request_input_text': input_text or None, 'debug_input_payload': debug_input_payload, 'debug_input_text': debug_input_text or None, 'task_prompt_text': input_text or None, 'tools': [], 'response_format': response_format_payload, 'decoding_params': {'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'reasoning_effort': reasoning_effort_value}, 'raw_response': {'output_text': response_text or None, 'output_file': str(exported_response_file) if response_file.exists() else None}, 'parsed_response': parsed_response, 'request_input_file': str(exported_input_file) if exported_input_file is not None else None, 'debug_input_file': str(exported_debug_input_file) if exported_debug_input_file is not None else None, 'request_telemetry': {'status': _clean_text(process_payload.get('status')) or _clean_text(runtime_telemetry_row.get('status')), 'duration_ms': _coerce_int(runtime_telemetry_row.get('duration_ms')), 'attempt_index': _coerce_int(attempt_payload.get('attempt_index')), 'prompt_index': prompt_index, 'candidate_count': _coerce_int(batch_payload.get('candidate_count')), 'requested_atomic_indices': list(batch_payload.get('requested_atomic_indices') or []), 'returncode': _coerce_int(attempt_payload.get('returncode')), 'response_present': _coerce_bool(attempt_payload.get('response_present')), 'turn_failed_message': _clean_text(attempt_payload.get('turn_failed_message')) or _clean_text(runtime_telemetry_row.get('turn_failed_message')), 'tokens_input': _coerce_int(usage_payload.get('tokens_input')) or _coerce_int(runtime_telemetry_row.get('tokens_input')), 'tokens_cached_input': _coerce_int(usage_payload.get('tokens_cached_input')) or _coerce_int(runtime_telemetry_row.get('tokens_cached_input')), 'tokens_output': _coerce_int(usage_payload.get('tokens_output')) or _coerce_int(runtime_telemetry_row.get('tokens_output')), 'tokens_reasoning': _coerce_int(usage_payload.get('tokens_reasoning')) or _coerce_int(runtime_telemetry_row.get('tokens_reasoning')), 'tokens_total': _coerce_int(usage_payload.get('tokens_total')) or _coerce_int(runtime_telemetry_row.get('tokens_total')), 'worker_id': runtime_context.get('runtime_worker_id'), 'shard_id': runtime_context.get('runtime_shard_id'), 'owned_ids': list(runtime_context.get('runtime_owned_ids') or []), 'events_path': _clean_text(runtime_telemetry_row.get('events_path')) or _clean_text(process_payload.get('events_path')), 'last_message_path': _clean_text(runtime_telemetry_row.get('last_message_path')) or _clean_text(process_payload.get('last_message_path')), 'usage_path': _clean_text(runtime_telemetry_row.get('usage_path')) or _clean_text(process_payload.get('usage_path')), 'live_status_path': _clean_text(runtime_telemetry_row.get('live_status_path')) or _clean_text(process_payload.get('live_status_path')), 'workspace_manifest_path': _clean_text(runtime_telemetry_row.get('workspace_manifest_path')) or _clean_text(process_payload.get('workspace_manifest_path')), 'stdout_path': _clean_text(runtime_telemetry_row.get('stdout_path')) or _clean_text(process_payload.get('stdout_path')), 'stderr_path': _clean_text(runtime_telemetry_row.get('stderr_path')) or _clean_text(process_payload.get('stderr_path'))}, 'runtime_shard_id': runtime_context.get('runtime_shard_id'), 'runtime_worker_id': runtime_context.get('runtime_worker_id'), 'runtime_owned_ids': list(runtime_context.get('runtime_owned_ids') or []), 'activity_trace': None}
            activity_trace_payload = _export_prompt_activity_trace(row_payload=row_payload, prompts_dir=prompts_dir, repo_root=repo_root)
            row_payload['activity_trace'] = activity_trace_payload
            if isinstance(activity_trace_payload, dict) and isinstance(row_payload.get('request_telemetry'), dict):
                row_payload['request_telemetry']['activity_trace_path'] = activity_trace_payload.get('path')
            if parsed_file.exists():
                row_payload['parsed_response_file'] = str(exported_parsed_file)
            rows.append(row_payload)
    if not rows:
        return ([], None)
    category_path = prompts_dir / 'prompt_line_role.txt'
    category_path.write_text('\n'.join(detail_lines).rstrip() + '\n', encoding='utf-8')
    return (rows, str(category_path))

def _append_line_role_prompt_artifacts(*, pred_run: Path, eval_output_dir: Path, repo_root: Path) -> Path | None:
    prompts_dir = eval_output_dir / 'prompts'
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_response_log_path = prompts_dir / 'prompt_request_response_log.txt'
    full_prompt_log_path = prompts_dir / 'full_prompt_log.jsonl'
    prompt_type_samples_path = prompts_dir / PROMPT_TYPE_SAMPLES_MD_NAME
    category_manifest_path = prompts_dir / 'prompt_category_logs_manifest.txt'
    line_role_rows, category_path = _build_line_role_prompt_rows(pred_run=pred_run, eval_output_dir=eval_output_dir, repo_root=repo_root)
    if not line_role_rows:
        return None
    existing_rows = [row for row in _load_prompt_rows(full_prompt_log_path) if str(row.get('stage_key') or '') != 'line_role']
    merged_rows = sorted(existing_rows + line_role_rows, key=_prompt_row_sort_key)
    full_prompt_log_path.write_text(''.join((json.dumps(row, ensure_ascii=False) + '\n' for row in merged_rows)), encoding='utf-8')
    section_lines: list[str] = []
    for row in line_role_rows:
        call_id = str(row.get('call_id') or '')
        stage_key = str(row.get('stage_key') or 'line_role')
        request_input_file = _clean_text(row.get('request_input_file'))
        debug_input_file = _clean_text(row.get('debug_input_file'))
        raw_response = row.get('raw_response')
        response_file = _clean_text(raw_response.get('output_file')) if isinstance(raw_response, dict) else None
        rendered_prompt_text = str(row.get('rendered_prompt_text') or '')
        response_text = str(raw_response.get('output_text') or '') if isinstance(raw_response, dict) else ''
        section_lines.append(f'INPUT {stage_key} => {call_id}')
        if request_input_file is not None:
            section_lines.append(f'path: {request_input_file}')
        if debug_input_file is not None:
            section_lines.append(f'debug_path: {debug_input_file}')
        section_lines.append('-' * 80)
        section_lines.append(rendered_prompt_text)
        section_lines.append('-' * 80)
        section_lines.append('')
        if response_text:
            section_lines.append(f'OUTPUT {stage_key} => {call_id}')
            if response_file is not None:
                section_lines.append(f'path: {response_file}')
            section_lines.append('-' * 80)
            section_lines.append(response_text)
            section_lines.append('-' * 80)
            section_lines.append('')
    _upsert_text_section(path=prompt_response_log_path, start_marker='=== LINE_ROLE INTERACTIONS :: BEGIN ===', end_marker='=== LINE_ROLE INTERACTIONS :: END ===', body='\n'.join(section_lines).rstrip())
    manifest_lines: list[str] = []
    if category_manifest_path.exists() and category_manifest_path.is_file():
        manifest_lines = [line.strip() for line in category_manifest_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if category_path is not None and category_path not in manifest_lines:
        manifest_lines.append(category_path)
        stage_order_by_manifest_path = {str(prompts_dir / 'prompt_recipe_refine.txt'): 1, str(prompts_dir / 'prompt_line_role.txt'): 2, str(prompts_dir / 'prompt_nonrecipe_finalize.txt'): 4}
        manifest_lines.sort(key=lambda path: (stage_order_by_manifest_path.get(path, 999), path))
        category_manifest_path.write_text('\n'.join(manifest_lines).rstrip() + '\n', encoding='utf-8')
    build_codex_farm_prompt_type_samples_markdown(full_prompt_log_path=full_prompt_log_path, output_path=prompt_type_samples_path, examples_per_pass=3)
    return prompt_response_log_path

def _append_structured_session_turn_to_category_log(
    *,
    category: list[str],
    stage_key: str,
    turn_kind: str,
    turn_index: int,
    turn_prompt_text: str,
    turn_packet_text: str,
    turn_response_text: str,
    turn_packet_path: Path | None,
    turn_response_path: Path | None,
) -> None:
    category.append(
        f"--- STRUCTURED SESSION TURN {turn_index:02d} ({stage_key} / {turn_kind}) ---"
    )
    category.append(f"PROMPT {stage_key} => {turn_kind}")
    category.append("-" * 80)
    category.append(turn_prompt_text)
    category.append("-" * 80)
    category.append("")
    if turn_packet_text:
        category.append(f"PACKET {stage_key} => {turn_kind}")
        if isinstance(turn_packet_path, Path):
            category.append(f"path: {turn_packet_path}")
        category.append("-" * 80)
        category.append(turn_packet_text)
        category.append("-" * 80)
        category.append("")
    if turn_response_text:
        category.append(f"OUTPUT {stage_key} => {turn_kind}")
        if isinstance(turn_response_path, Path):
            category.append(f"path: {turn_response_path}")
        category.append("-" * 80)
        category.append(turn_response_text)
        category.append("-" * 80)
        category.append("")

def render_prompt_artifacts_from_descriptors(*, pred_run: Path, eval_output_dir: Path, repo_root: Path, run_descriptors: Sequence[PromptRunDescriptor]) -> Path | None:
    if not run_descriptors:
        return None
    prompts_dir = eval_output_dir / 'prompts'
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_response_log_path = prompts_dir / 'prompt_request_response_log.txt'
    full_prompt_log_path = prompts_dir / 'full_prompt_log.jsonl'
    prompt_type_samples_path = prompts_dir / PROMPT_TYPE_SAMPLES_MD_NAME
    pred_run_manifest = _load_json_dict(pred_run / 'run_manifest.json') or {}
    pred_run_source = pred_run_manifest.get('source') if isinstance(pred_run_manifest.get('source'), dict) else {}
    source_file = None
    if isinstance(pred_run_source, dict):
        source_file_raw = pred_run_source.get('path')
        if isinstance(source_file_raw, str) and source_file_raw.strip():
            source_file = source_file_raw.strip()
    benchmark_run_id = eval_output_dir.name
    full_prompt_log_rows = 0
    lines: list[str] = []
    category_lines: dict[str, list[str]] = {}
    category_has_payload: dict[str, bool] = {}
    category_stage_metadata: dict[str, dict[str, Any]] = {}
    with full_prompt_log_path.open('w', encoding='utf-8') as full_prompt_log_handle:
        for run_descriptor in sorted(run_descriptors, key=lambda row: row.run_dir.name):
            run_dir = run_descriptor.run_dir
            manifest_payload_by_name = run_descriptor.manifest_payload_by_name
            manifest_path_by_name = run_descriptor.manifest_path_by_name
            if not manifest_payload_by_name:
                lines.append(f'=== SKIP: missing pass manifests in {run_dir} ===')
                continue
            lines.append(f'=== CODexFarm run: {run_dir.name} ===')
            if manifest_path_by_name:
                lines.append('manifests:')
                for manifest_name in sorted(manifest_path_by_name):
                    lines.append(f'- {manifest_path_by_name[manifest_name]}')
            primary_manifest = manifest_payload_by_name.get(RECIPE_MANIFEST_FILE_NAME, {})
            llm_enabled = primary_manifest.get('enabled')
            if llm_enabled is not None:
                lines.append(f'enabled: {llm_enabled}')
            if run_descriptor.codex_farm_pipeline:
                lines.append(f'pipeline: {run_descriptor.codex_farm_pipeline}')
            if run_descriptor.codex_farm_model:
                lines.append(f'codex_farm_model: {run_descriptor.codex_farm_model}')
            codex_reasoning_effort = run_descriptor.codex_farm_reasoning_effort
            lines.append('')
            telemetry_rows_by_manifest_name: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
            telemetry_csv_by_manifest_name: dict[str, dict[str, str]] = {}
            for manifest_name, manifest_payload in manifest_payload_by_name.items():
                rows_by_run_id, csv_by_run_id = _load_codex_exec_rows_for_manifest(manifest_payload, repo_root=repo_root)
                telemetry_rows_by_manifest_name[manifest_name] = rows_by_run_id
                telemetry_csv_by_manifest_name[manifest_name] = csv_by_run_id
            process_run_stages = [stage for stage in run_descriptor.stages if isinstance(stage.process_run_payload, dict)]
            if process_run_stages:
                lines.append('--- PROCESS RUN PAYLOAD SNIPPETS ---')
                for stage in process_run_stages:
                    lines.append(f'--- process_run[{stage.stage_key}] ({stage.manifest_name}) ---')
                    try:
                        lines.append(json.dumps(stage.process_run_payload, indent=2, sort_keys=True))
                    except Exception:
                        lines.append(str(stage.process_run_payload))
                lines.append('')
            for stage in run_descriptor.stages:
                category_key = stage.stage_key
                category_lines.setdefault(category_key, [])
                category_has_payload.setdefault(category_key, False)
                runtime_stage_root = None
                if stage.stage_key == 'recipe_refine':
                    runtime_stage_root = run_dir / 'recipe_phase_runtime'
                elif stage.stage_key == 'nonrecipe_finalize':
                    runtime_stage_root = run_dir / stage_artifact_stem(stage.stage_key)
                runtime_index = _load_phase_runtime_index(runtime_stage_root) if isinstance(runtime_stage_root, Path) else {}
                pass_assets = _load_run_assets_for_process_run(process_run_payload=stage.process_run_payload, repo_root=repo_root)
                process_run_id = _clean_text(pass_assets.get('run_id'))
                telemetry_rows_by_run_id = telemetry_rows_by_manifest_name.get(stage.manifest_name, {})
                telemetry_csv_by_run_id = telemetry_csv_by_manifest_name.get(stage.manifest_name, {})
                pass_telemetry_rows = telemetry_rows_by_run_id.get(process_run_id, {}) if process_run_id is not None else {}
                stage_metadata = {'stage_order': stage.stage_order, 'pipeline_id': stage.pipeline_id, 'stage_key': stage.stage_key, 'heading_key': stage.stage_heading_key, 'label': stage.stage_label, 'artifact_stem': stage.stage_artifact_stem, 'path_root': stage.stage_dir_name}
                category_stage_metadata[category_key] = dict(stage_metadata)
                category = category_lines[category_key]
                category.append(f'=== CATEGORY {stage.stage_key} ({stage.stage_heading_key} / {stage.stage_label}) | stage_dir: {stage.stage_dir_name} | run: {run_dir.name} ===')
                if stage.manifest_path is not None:
                    category.append(f'manifest: {stage.manifest_path}')
                if stage.pipeline_id is not None:
                    category.append(f'pipeline_id: {stage.pipeline_id}')
                category.append('')
                input_files = _files_in_dir(stage.input_dir)
                lines.append(f'--- {stage.stage_key.upper()} INPUT FILES ---')
                lines.append(f'source_dir: {stage.input_dir}')
                category.append(f'--- {stage.stage_key.upper()} PROMPT INPUT FILES ---')
                category.append(f'source_dir: {stage.input_dir}')
                for prompt_file in input_files:
                    category_has_payload[category_key] = True
                    lines.append(f'INPUT {stage.stage_key} => {prompt_file.name}')
                    lines.append('-' * 80)
                    prompt_text = _safe_read_text(prompt_file)
                    lines.append(prompt_text)
                    lines.append('-' * 80)
                    lines.append('')
                    category.append(f'INPUT {stage.stage_key} => {prompt_file.name}')
                    category.append('-' * 80)
                    category.append(prompt_text)
                    category.append('-' * 80)
                    category.append('')
                    payload = _parse_json_text(prompt_text)
                    attachment_paths = _collect_prompt_attachments(payload, prompt_file=prompt_file, pred_run=pred_run)
                    if attachment_paths:
                        category.append(f'--- ATTACHMENT FILES REFERENCED BY {prompt_file.name} ---')
                        for attachment_path in attachment_paths:
                            category.append(f'ATTACHMENT {stage.stage_key} => {attachment_path}')
                            category.append('-' * 80)
                            category.append(_safe_read_text(attachment_path))
                            category.append('-' * 80)
                            category.append('')
                output_files = _files_in_dir(stage.output_dir)
                lines.append(f'--- {stage.stage_key.upper()} RESPONSE FILES ---')
                lines.append(f'source_dir: {stage.output_dir}')
                category.append(f'--- {stage.stage_key.upper()} PROMPT RESPONSE FILES ---')
                category.append(f'source_dir: {stage.output_dir}')
                for response_file in output_files:
                    category_has_payload[category_key] = True
                    lines.append(f'OUTPUT {stage.stage_key} => {response_file.name}')
                    lines.append('-' * 80)
                    response_text = _safe_read_text(response_file)
                    lines.append(response_text)
                    lines.append('-' * 80)
                    lines.append('')
                    category.append(f'OUTPUT {stage.stage_key} => {response_file.name}')
                    category.append('-' * 80)
                    category.append(response_text)
                    category.append('-' * 80)
                    category.append('')
                lines.append('')
                category.append('')
                file_names = sorted({file.name for file in input_files} | {file.name for file in output_files})
                output_by_name = {file.name: file for file in output_files}
                input_by_name = {file.name: file for file in input_files}
                for file_name in file_names:
                    input_file = input_by_name.get(file_name)
                    output_file = output_by_name.get(file_name)
                    input_text = _safe_read_text(input_file) if input_file is not None else ''
                    output_text = _safe_read_text(output_file) if output_file is not None else ''
                    telemetry_row = pass_telemetry_rows.get(file_name)
                    if telemetry_row is None and input_file is not None:
                        telemetry_row = pass_telemetry_rows.get(input_file.name)
                    if telemetry_row is None and output_file is not None:
                        telemetry_row = pass_telemetry_rows.get(output_file.name)
                    telemetry_prompt_text = str(telemetry_row.get('prompt_text')) if isinstance(telemetry_row, dict) and telemetry_row.get('prompt_text') is not None else ''
                    telemetry_timestamp_utc = None
                    telemetry_output_path = None
                    if isinstance(telemetry_row, dict):
                        telemetry_timestamp_utc = _clean_text(telemetry_row.get('finished_at_utc')) or _clean_text(telemetry_row.get('logged_at_utc'))
                        output_path_text = _clean_text(telemetry_row.get('output_path'))
                        if output_path_text is not None:
                            telemetry_output_path = Path(output_path_text)
                    if not output_text and telemetry_output_path is not None:
                        output_text = _safe_read_text(telemetry_output_path)
                    parsed_input = _parse_json_text(input_text)
                    parsed_output = _parse_json_text(output_text)
                    call_stem = input_file.stem if input_file is not None else output_file.stem if output_file is not None else Path(file_name).stem
                    recipe_id = _resolve_recipe_id(parsed_input=parsed_input, parsed_output=parsed_output, fallback_name=file_name)
                    runtime_context = _resolve_runtime_context(runtime_index=runtime_index, shard_id=_clean_text(_coerce_dict(parsed_input).get('bid')) or _clean_text(_coerce_dict(parsed_input).get('bundle_id')) or _clean_text(_coerce_dict(parsed_input).get('shard_id')) or _clean_text(_coerce_dict(parsed_output).get('bid')) or _clean_text(_coerce_dict(parsed_output).get('bundle_id')) or _clean_text(_coerce_dict(parsed_output).get('shard_id')) or (call_stem if stage.stage_key == 'nonrecipe_finalize' else None), owned_id=recipe_id)
                    runtime_telemetry_row = dict(runtime_context.get('runtime_telemetry_row')) if isinstance(runtime_context.get('runtime_telemetry_row'), dict) else {}
                    if telemetry_row is None and runtime_telemetry_row:
                        telemetry_row = runtime_telemetry_row
                    if telemetry_timestamp_utc is None and runtime_telemetry_row:
                        telemetry_timestamp_utc = _clean_text(runtime_telemetry_row.get('finished_at_utc')) or _clean_text(runtime_telemetry_row.get('logged_at_utc'))
                    if telemetry_output_path is None and runtime_telemetry_row:
                        output_path_text = _clean_text(runtime_telemetry_row.get('output_path'))
                        if output_path_text is not None:
                            telemetry_output_path = Path(output_path_text)
                    timestamp_utc = telemetry_timestamp_utc or _timestamp_utc_for_path(output_file) or _timestamp_utc_for_path(input_file)
                    rendered_prompt_text = _render_prompt_text(template_text=pass_assets.get('prompt_template_text') if isinstance(pass_assets, dict) else None, input_text=input_text, input_file=input_file or stage.input_dir / file_name)
                    request_payload_source = 'reconstructed_from_prompt_template'
                    if telemetry_prompt_text:
                        rendered_prompt_text = telemetry_prompt_text
                        request_payload_source = 'telemetry_csv'
                    elif runtime_telemetry_row.get('prompt_text'):
                        rendered_prompt_text = str(runtime_telemetry_row.get('prompt_text'))
                        request_payload_source = 'runtime_telemetry'
                    request_messages = [{'role': 'user', 'content': rendered_prompt_text}]
                    response_format_payload: dict[str, Any] | None = None
                    output_schema_payload = pass_assets.get('output_schema_payload')
                    if isinstance(output_schema_payload, dict):
                        response_format_payload = {'type': 'json_schema', 'json_schema': output_schema_payload}
                    effective_pipeline_payload = pass_assets.get('effective_pipeline_payload')
                    model_value = None
                    if isinstance(effective_pipeline_payload, dict):
                        model_candidate = str(effective_pipeline_payload.get('codex_model') or '').strip()
                        if model_candidate:
                            model_value = model_candidate
                    if model_value is None and run_descriptor.codex_farm_model:
                        model_value = run_descriptor.codex_farm_model
                    telemetry_model = _clean_text(telemetry_row.get('model')) if isinstance(telemetry_row, dict) else None
                    if telemetry_model is not None:
                        model_value = telemetry_model
                    effective_reasoning_effort = _clean_text(effective_pipeline_payload.get('codex_reasoning_effort')) if isinstance(effective_pipeline_payload, dict) else None
                    telemetry_reasoning_effort = _clean_text(telemetry_row.get('reasoning_effort')) if isinstance(telemetry_row, dict) else None
                    reasoning_effort_value = telemetry_reasoning_effort or codex_reasoning_effort or effective_reasoning_effort
                    telemetry_sandbox = _clean_text(telemetry_row.get('sandbox')) if isinstance(telemetry_row, dict) else None
                    fallback_sandbox = _clean_text(effective_pipeline_payload.get('codex_sandbox')) if isinstance(effective_pipeline_payload, dict) else None
                    sandbox_value = telemetry_sandbox or fallback_sandbox
                    telemetry_ask_for_approval = _coerce_bool(telemetry_row.get('ask_for_approval')) if isinstance(telemetry_row, dict) else None
                    fallback_ask_for_approval = _coerce_bool(effective_pipeline_payload.get('codex_ask_for_approval')) if isinstance(effective_pipeline_payload, dict) else None
                    ask_for_approval_value = telemetry_ask_for_approval if telemetry_ask_for_approval is not None else fallback_ask_for_approval
                    telemetry_web_search = _coerce_bool(telemetry_row.get('web_search')) if isinstance(telemetry_row, dict) else None
                    fallback_web_search = _coerce_bool(effective_pipeline_payload.get('codex_web_search')) if isinstance(effective_pipeline_payload, dict) else None
                    web_search_value = telemetry_web_search if telemetry_web_search is not None else fallback_web_search
                    telemetry_output_schema_path = _clean_text(telemetry_row.get('output_schema_path')) if isinstance(telemetry_row, dict) else None
                    telemetry_task_id = _clean_text(telemetry_row.get('task_id')) if isinstance(telemetry_row, dict) else None
                    request_payload: dict[str, Any] = {'messages': request_messages, 'tools': [], 'response_format': response_format_payload, 'model': model_value, 'reasoning_effort': reasoning_effort_value, 'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'pipeline_id': stage.pipeline_id, 'sandbox': sandbox_value, 'ask_for_approval': ask_for_approval_value, 'web_search': web_search_value, 'output_schema_path': telemetry_output_schema_path}
                    template_vars: dict[str, Any] = {'INPUT_PATH': str(input_file) if input_file is not None else None, 'INPUT_TEXT': input_text}
                    prompt_templates = {'prompt_template_text': pass_assets.get('prompt_template_text'), 'prompt_template_path': pass_assets.get('prompt_source_path')}
                    structured_session_turns = _load_structured_session_turn_artifacts(session_root=_resolve_structured_session_root(runtime_stage_root=runtime_stage_root, runtime_context=runtime_context))
                    if structured_session_turns:
                        for turn_artifact in structured_session_turns:
                            turn_prompt_text = str(turn_artifact.get('prompt_text') or '')
                            turn_packet_text = str(turn_artifact.get('packet_text') or '')
                            turn_response_text = str(turn_artifact.get('response_text') or '')
                            turn_parsed_input = turn_artifact.get('parsed_input')
                            turn_parsed_response = turn_artifact.get('parsed_response')
                            turn_index = _coerce_int(turn_artifact.get('turn_index')) or 0
                            turn_kind = _clean_text(turn_artifact.get('turn_kind')) or f'turn_{turn_index or 0}'
                            turn_call_id = f"{runtime_context.get('runtime_shard_id') or call_stem}__turn_{turn_index:02d}_{turn_kind}"
                            turn_request_messages = [{'role': 'user', 'content': turn_prompt_text}]
                            turn_usage_payload = (
                                dict(turn_artifact.get('usage_payload'))
                                if isinstance(turn_artifact.get('usage_payload'), Mapping)
                                else {}
                            )
                            turn_tokens_input = _coerce_int(turn_usage_payload.get('input_tokens'))
                            turn_tokens_cached_input = _coerce_int(turn_usage_payload.get('cached_input_tokens'))
                            turn_tokens_output = _coerce_int(turn_usage_payload.get('output_tokens'))
                            turn_tokens_reasoning = _coerce_int(turn_usage_payload.get('reasoning_tokens'))
                            turn_tokens_total = sum(
                                value or 0
                                for value in (
                                    turn_tokens_input,
                                    turn_tokens_cached_input,
                                    turn_tokens_output,
                                    turn_tokens_reasoning,
                                )
                            )
                            turn_output_preview = turn_response_text[:400] if turn_response_text else None
                            turn_response_path = turn_artifact.get('response_path')
                            turn_request_telemetry = {
                                'csv_path': telemetry_csv_by_run_id.get(process_run_id) if process_run_id is not None else None,
                                'task_id': turn_call_id,
                                'worker_id': runtime_context.get('runtime_worker_id'),
                                'thread_id': None,
                                'status': 'ok' if turn_response_text.strip() else None,
                                'duration_ms': None,
                                'attempt_index': turn_index,
                                'execution_attempt_index': turn_index,
                                'lease_claim_index': None,
                                'input_path': str(turn_artifact.get('packet_path')) if isinstance(turn_artifact.get('packet_path'), Path) else None,
                                'output_path': str(turn_response_path) if isinstance(turn_response_path, Path) else None,
                                'prompt_chars': len(turn_prompt_text),
                                'prompt_sha256': None,
                                'output_bytes': turn_response_path.stat().st_size if isinstance(turn_response_path, Path) and turn_response_path.exists() else None,
                                'output_sha256': None,
                                'output_payload_present': bool(turn_response_text.strip()),
                                'output_preview_chars': len(turn_output_preview) if turn_output_preview is not None else 0,
                                'output_preview_truncated': bool(turn_output_preview is not None and len(turn_output_preview) < len(turn_response_text)),
                                'output_preview': turn_output_preview,
                                'tokens_input': turn_tokens_input,
                                'tokens_cached_input': turn_tokens_cached_input,
                                'tokens_output': turn_tokens_output,
                                'tokens_reasoning': turn_tokens_reasoning,
                                'tokens_total': turn_tokens_total,
                                'usage_json': turn_usage_payload,
                                'model': model_value,
                                'reasoning_effort': reasoning_effort_value,
                                'sandbox': sandbox_value,
                                'ask_for_approval': ask_for_approval_value,
                                'web_search': web_search_value,
                                'output_schema_path': telemetry_output_schema_path,
                                'worker_id': runtime_context.get('runtime_worker_id'),
                                'shard_id': runtime_context.get('runtime_shard_id'),
                                'owned_ids': list(runtime_context.get('runtime_owned_ids') or []),
                                'events_path': str(turn_artifact.get('events_path')) if isinstance(turn_artifact.get('events_path'), Path) else None,
                                'last_message_path': str(turn_artifact.get('last_message_path')) if isinstance(turn_artifact.get('last_message_path'), Path) else None,
                                'usage_path': str(turn_artifact.get('usage_path')) if isinstance(turn_artifact.get('usage_path'), Path) else None,
                                'live_status_path': None,
                                'workspace_manifest_path': str(turn_artifact.get('workspace_manifest_path')) if isinstance(turn_artifact.get('workspace_manifest_path'), Path) else None,
                                'stdout_path': None,
                                'stderr_path': None,
                            }
                            turn_row_payload = {
                                'run_id': benchmark_run_id,
                                'schema_version': PROMPT_CALL_RECORD_SCHEMA_VERSION,
                                'call_id': turn_call_id,
                                'timestamp_utc': turn_artifact.get('timestamp_utc') or timestamp_utc,
                                'recipe_id': recipe_id,
                                'source_file': source_file,
                                'pipeline_id': stage.pipeline_id,
                                'stage_key': stage.stage_key,
                                'stage_heading_key': stage.stage_heading_key,
                                'stage_label': stage.stage_label,
                                'stage_artifact_stem': stage.stage_artifact_stem,
                                'stage_dir_name': stage.stage_dir_name,
                                'stage_order': stage.stage_order,
                                'process_run_id': process_run_id,
                                'model': model_value,
                                'prompt_input_mode': f'structured_session_{turn_kind}',
                                'request_payload_source': 'structured_session_prompt_artifact',
                                'request_messages': turn_request_messages,
                                'system_prompt': None,
                                'developer_prompt': None,
                                'user_prompt': turn_prompt_text,
                                'rendered_prompt_text': turn_prompt_text,
                                'rendered_messages': turn_request_messages,
                                'prompt_templates': prompt_templates,
                                'template_vars': {'INPUT_PATH': str(turn_artifact.get('packet_path')) if isinstance(turn_artifact.get('packet_path'), Path) else None, 'INPUT_TEXT': turn_packet_text},
                                'inserted_context_blocks': _collect_inserted_context_blocks(turn_parsed_input),
                                'request': {'messages': turn_request_messages, 'tools': [], 'response_format': response_format_payload, 'model': model_value, 'reasoning_effort': reasoning_effort_value, 'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'pipeline_id': stage.pipeline_id, 'sandbox': sandbox_value, 'ask_for_approval': ask_for_approval_value, 'web_search': web_search_value, 'output_schema_path': telemetry_output_schema_path},
                                'request_input_payload': turn_parsed_input,
                                'tools': [],
                                'response_format': response_format_payload,
                                'decoding_params': {'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'reasoning_effort': reasoning_effort_value},
                                'raw_response': {'output_text': turn_response_text, 'output_file': str(turn_response_path) if isinstance(turn_response_path, Path) else None},
                                'parsed_response': turn_parsed_response,
                                'request_input_file': str(turn_artifact.get('packet_path')) if isinstance(turn_artifact.get('packet_path'), Path) else None,
                                'request_telemetry': turn_request_telemetry,
                                'runtime_shard_id': runtime_context.get('runtime_shard_id'),
                                'runtime_worker_id': runtime_context.get('runtime_worker_id'),
                                'runtime_owned_ids': list(runtime_context.get('runtime_owned_ids') or []),
                                'runtime_turn_index': turn_index,
                                'runtime_turn_kind': turn_kind,
                                'activity_trace': None,
                            }
                            activity_trace_payload = _export_prompt_activity_trace(row_payload=turn_row_payload, prompts_dir=prompts_dir, repo_root=repo_root)
                            turn_row_payload['activity_trace'] = activity_trace_payload
                            if isinstance(activity_trace_payload, dict):
                                turn_request_telemetry['activity_trace_path'] = activity_trace_payload.get('path')
                            full_prompt_log_handle.write(json.dumps(PromptCallRecord(schema_version=PROMPT_CALL_RECORD_SCHEMA_VERSION, row=turn_row_payload).to_row(), ensure_ascii=False) + '\n')
                            full_prompt_log_rows += 1
                            category_has_payload[category_key] = True
                            _append_structured_session_turn_to_category_log(
                                category=category,
                                stage_key=stage.stage_key,
                                turn_kind=turn_kind,
                                turn_index=turn_index,
                                turn_prompt_text=turn_prompt_text,
                                turn_packet_text=turn_packet_text,
                                turn_response_text=turn_response_text,
                                turn_packet_path=turn_artifact.get('packet_path') if isinstance(turn_artifact.get('packet_path'), Path) else None,
                                turn_response_path=turn_response_path if isinstance(turn_response_path, Path) else None,
                            )
                        continue
                    if (
                        request_payload_source == 'reconstructed_from_prompt_template'
                        and _runtime_context_identity_present(runtime_context)
                        and not _has_observed_runtime_call_evidence(
                            runtime_stage_root=runtime_stage_root,
                            runtime_context=runtime_context,
                        )
                    ):
                        continue
                    request_telemetry: dict[str, Any] | None = None
                    if isinstance(telemetry_row, dict):
                        usage_payload = _parse_json_text(str(telemetry_row.get('usage_json') or ''))
                        request_telemetry = {'csv_path': telemetry_csv_by_run_id.get(process_run_id) if process_run_id is not None else None, 'task_id': telemetry_task_id, 'worker_id': _clean_text(telemetry_row.get('worker_id')), 'thread_id': _clean_text(telemetry_row.get('thread_id')), 'status': _clean_text(telemetry_row.get('status')), 'duration_ms': _coerce_int(telemetry_row.get('duration_ms')), 'attempt_index': _coerce_int(telemetry_row.get('attempt_index')), 'execution_attempt_index': _coerce_int(telemetry_row.get('execution_attempt_index')), 'lease_claim_index': _coerce_int(telemetry_row.get('lease_claim_index')), 'input_path': _clean_text(telemetry_row.get('input_path')), 'output_path': _clean_text(telemetry_row.get('output_path')), 'prompt_chars': _coerce_int(telemetry_row.get('prompt_chars')), 'prompt_sha256': _clean_text(telemetry_row.get('prompt_sha256')), 'output_bytes': _coerce_int(telemetry_row.get('output_bytes')), 'output_sha256': _clean_text(telemetry_row.get('output_sha256')), 'output_payload_present': _coerce_bool(telemetry_row.get('output_payload_present')), 'output_preview_chars': _coerce_int(telemetry_row.get('output_preview_chars')), 'output_preview_truncated': _coerce_bool(telemetry_row.get('output_preview_truncated')), 'output_preview': telemetry_row.get('output_preview'), 'tokens_input': _coerce_int(telemetry_row.get('tokens_input')), 'tokens_cached_input': _coerce_int(telemetry_row.get('tokens_cached_input')), 'tokens_output': _coerce_int(telemetry_row.get('tokens_output')), 'tokens_reasoning': _coerce_int(telemetry_row.get('tokens_reasoning')), 'tokens_total': _coerce_int(telemetry_row.get('tokens_total')), 'usage_json': usage_payload, 'model': telemetry_model, 'reasoning_effort': telemetry_reasoning_effort, 'sandbox': telemetry_sandbox, 'ask_for_approval': telemetry_ask_for_approval, 'web_search': telemetry_web_search, 'output_schema_path': telemetry_output_schema_path, 'worker_id': runtime_context.get('runtime_worker_id'), 'shard_id': runtime_context.get('runtime_shard_id'), 'owned_ids': list(runtime_context.get('runtime_owned_ids') or []), 'events_path': _clean_text(telemetry_row.get('events_path')), 'last_message_path': _clean_text(telemetry_row.get('last_message_path')), 'usage_path': _clean_text(telemetry_row.get('usage_path')), 'live_status_path': _clean_text(telemetry_row.get('live_status_path')), 'workspace_manifest_path': _clean_text(telemetry_row.get('workspace_manifest_path')), 'stdout_path': _clean_text(telemetry_row.get('stdout_path')), 'stderr_path': _clean_text(telemetry_row.get('stderr_path'))}
                    row_payload = {'run_id': benchmark_run_id, 'schema_version': PROMPT_CALL_RECORD_SCHEMA_VERSION, 'call_id': call_stem, 'timestamp_utc': timestamp_utc, 'recipe_id': recipe_id, 'source_file': source_file, 'pipeline_id': stage.pipeline_id, 'stage_key': stage.stage_key, 'stage_heading_key': stage.stage_heading_key, 'stage_label': stage.stage_label, 'stage_artifact_stem': stage.stage_artifact_stem, 'stage_dir_name': stage.stage_dir_name, 'stage_order': stage.stage_order, 'process_run_id': process_run_id, 'model': model_value, 'request_payload_source': request_payload_source, 'request_messages': request_messages, 'system_prompt': None, 'developer_prompt': None, 'user_prompt': rendered_prompt_text, 'rendered_prompt_text': rendered_prompt_text, 'rendered_messages': request_messages, 'prompt_templates': prompt_templates, 'template_vars': template_vars, 'inserted_context_blocks': _collect_inserted_context_blocks(parsed_input), 'request': request_payload, 'request_input_payload': parsed_input, 'tools': [], 'response_format': response_format_payload, 'decoding_params': {'temperature': None, 'top_p': None, 'max_output_tokens': None, 'seed': None, 'reasoning_effort': reasoning_effort_value}, 'raw_response': {'output_text': output_text, 'output_file': str(output_file) if output_file is not None else str(telemetry_output_path) if telemetry_output_path is not None else None}, 'parsed_response': parsed_output, 'request_input_file': str(input_file) if input_file is not None else None, 'request_telemetry': request_telemetry, 'runtime_shard_id': runtime_context.get('runtime_shard_id'), 'runtime_worker_id': runtime_context.get('runtime_worker_id'), 'runtime_owned_ids': list(runtime_context.get('runtime_owned_ids') or []), 'activity_trace': None}
                    activity_trace_payload = _export_prompt_activity_trace(row_payload=row_payload, prompts_dir=prompts_dir, repo_root=repo_root)
                    row_payload['activity_trace'] = activity_trace_payload
                    if isinstance(activity_trace_payload, dict) and isinstance(request_telemetry, dict):
                        request_telemetry['activity_trace_path'] = activity_trace_payload.get('path')
                    full_prompt_log_handle.write(json.dumps(PromptCallRecord(schema_version=PROMPT_CALL_RECORD_SCHEMA_VERSION, row=row_payload).to_row(), ensure_ascii=False) + '\n')
                    full_prompt_log_rows += 1
    if not lines:
        full_prompt_log_path.unlink(missing_ok=True)
        prompt_type_samples_path.unlink(missing_ok=True)
        return None
    prompt_response_log_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    category_manifest_lines: list[str] = []
    category_sort_keys = sorted(category_stage_metadata.keys(), key=lambda key: (int(category_stage_metadata.get(key, {}).get('stage_order') or 999), key))
    for category_key in category_sort_keys:
        if not category_has_payload.get(category_key):
            continue
        metadata = category_stage_metadata.get(category_key) or {}
        category_path = prompts_dir / f'prompt_{slugify_name(category_key)}.txt'
        category_path.write_text('\n'.join(category_lines.get(category_key, [])) + '\n', encoding='utf-8')
        category_manifest_lines.append(str(category_path))
    if category_manifest_lines:
        (prompts_dir / 'prompt_category_logs_manifest.txt').write_text('\n'.join(category_manifest_lines) + '\n', encoding='utf-8')
    if full_prompt_log_rows <= 0:
        full_prompt_log_path.unlink(missing_ok=True)
        prompt_type_samples_path.unlink(missing_ok=True)
    else:
        build_codex_farm_prompt_type_samples_markdown(full_prompt_log_path=full_prompt_log_path, output_path=prompt_type_samples_path, examples_per_pass=3)
    return prompt_response_log_path

def build_codex_farm_prompt_response_log(*, pred_run: Path, eval_output_dir: Path, repo_root: Path | None=None, run_descriptors: Sequence[PromptRunDescriptor] | None=None) -> Path | None:
    return build_prompt_response_log(pred_run=pred_run, eval_output_dir=eval_output_dir, repo_root=repo_root, run_descriptors=run_descriptors, discoverers=(discover_codex_exec_prompt_run_descriptors,))

def build_prompt_response_log(*, pred_run: Path, eval_output_dir: Path, repo_root: Path | None=None, run_descriptors: Sequence[PromptRunDescriptor] | None=None, discoverers: Sequence[PromptRunDescriptorDiscoverer] | None=None) -> Path | None:
    resolved_repo_root = repo_root.resolve(strict=False) if isinstance(repo_root, Path) else Path.cwd().resolve()
    prompts_dir = eval_output_dir / 'prompts'
    activity_traces_dir = prompts_dir / ACTIVITY_TRACES_DIR_NAME
    if activity_traces_dir.exists() and activity_traces_dir.is_dir():
        shutil.rmtree(activity_traces_dir)
    discovered = list(run_descriptors) if run_descriptors is not None else discover_prompt_run_descriptors(pred_run=pred_run, discoverers=discoverers)
    prompt_log_path = render_prompt_artifacts_from_descriptors(pred_run=pred_run, eval_output_dir=eval_output_dir, repo_root=resolved_repo_root, run_descriptors=discovered)
    line_role_prompt_log_path = _append_line_role_prompt_artifacts(pred_run=pred_run, eval_output_dir=eval_output_dir, repo_root=resolved_repo_root)
    full_prompt_log_path = prompts_dir / 'full_prompt_log.jsonl'
    prompt_log_summary_path = prompts_dir / PROMPT_LOG_SUMMARY_JSON_NAME
    activity_trace_summary_jsonl_path = prompts_dir / ACTIVITY_TRACE_SUMMARY_JSONL_NAME
    activity_trace_summary_md_path = prompts_dir / ACTIVITY_TRACE_SUMMARY_MD_NAME
    if full_prompt_log_path.exists() and full_prompt_log_path.is_file():
        write_prompt_log_summary(full_prompt_log_path=full_prompt_log_path, output_path=prompt_log_summary_path)
        build_codex_farm_activity_trace_summaries(full_prompt_log_path=full_prompt_log_path, output_jsonl_path=activity_trace_summary_jsonl_path, output_md_path=activity_trace_summary_md_path)
    else:
        prompt_log_summary_path.unlink(missing_ok=True)
        activity_trace_summary_jsonl_path.unlink(missing_ok=True)
        activity_trace_summary_md_path.unlink(missing_ok=True)
    return prompt_log_path or line_role_prompt_log_path
