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
def _resolve_recipe_id(*, parsed_input: Any, parsed_output: Any, fallback_name: str) -> str | None:
    for payload in (parsed_input, parsed_output):
        if isinstance(payload, dict):
            candidate = str(payload.get('recipe_id') or '').strip()
            if candidate:
                return candidate
    stem = Path(fallback_name).stem
    candidate_from_name = re.sub('^r\\d+_', '', stem).strip()
    return candidate_from_name or None

def _render_prompt_text(*, template_text: str | None, input_text: str, input_file: Path) -> str:
    template = str(template_text or '')
    if not template.strip():
        return input_text
    rendered = template.replace('{{INPUT_TEXT}}', input_text)
    rendered = rendered.replace('{{ INPUT_TEXT }}', input_text)
    rendered = rendered.replace('{{INPUT_PATH}}', str(input_file))
    rendered = rendered.replace('{{ INPUT_PATH }}', str(input_file))
    return rendered

def _collect_inserted_context_blocks(parsed_input: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed_input, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for key in ('blocks_before', 'blocks_candidate', 'blocks_after', 'blocks'):
        blocks = parsed_input.get(key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get('block_id') or '').strip() or None
            index_value = block.get('index')
            try:
                index = int(index_value) if index_value is not None else None
            except (TypeError, ValueError):
                index = None
            dedupe_key = (str(block_id or ''), index)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append({'source_key': key, 'block_id': block_id, 'index': index, 'text': block.get('text')})
    return rows

def _telemetry_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
    execution_attempt = _coerce_int(row.get('execution_attempt_index'))
    if execution_attempt is None:
        execution_attempt = _coerce_int(row.get('attempt_index')) or 0
    lease_claim_index = _coerce_int(row.get('lease_claim_index')) or 0
    finished_at = str(row.get('finished_at_utc') or row.get('logged_at_utc') or '')
    task_id = str(row.get('task_id') or '')
    return (execution_attempt, lease_claim_index, finished_at, task_id)

def _iter_process_run_payloads(manifest_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    process_runs = manifest_payload.get('process_runs')
    if isinstance(process_runs, dict):
        for pass_payload in process_runs.values():
            if isinstance(pass_payload, dict):
                rows.append(pass_payload)
    process_run = manifest_payload.get('process_run')
    if isinstance(process_run, dict):
        rows.append(process_run)
    llm_report = manifest_payload.get('llm_report')
    if isinstance(llm_report, dict):
        report_process_run = llm_report.get('process_run')
        if isinstance(report_process_run, dict):
            rows.append(report_process_run)
    return rows

def _resolve_codex_exec_csv_paths(manifest_payload: dict[str, Any], *, repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for process_run_payload in _iter_process_run_payloads(manifest_payload):
        telemetry_payload = process_run_payload.get('telemetry')
        if not isinstance(telemetry_payload, dict):
            continue
        csv_path_raw = telemetry_payload.get('csv_path')
        if isinstance(csv_path_raw, str) and csv_path_raw.strip():
            candidates.append(Path(csv_path_raw.strip()))
    candidates.append((repo_root / 'var' / 'codex_exec_activity.csv').resolve())
    rows: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.exists() and candidate.is_file():
            rows.append(candidate)
    return rows

def _load_codex_exec_rows_for_manifest(manifest_payload: dict[str, Any], *, repo_root: Path) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, str]]:
    run_ids: set[str] = set()
    for process_run_payload in _iter_process_run_payloads(manifest_payload):
        run_id = _clean_text(process_run_payload.get('run_id'))
        if run_id:
            run_ids.add(run_id)
    if not run_ids:
        return ({}, {})
    rows_by_run_and_input: dict[str, dict[str, dict[str, Any]]] = {run_id: {} for run_id in run_ids}
    csv_source_by_run_id: dict[str, str] = {}
    for csv_path in _resolve_codex_exec_csv_paths(manifest_payload, repo_root=repo_root):
        try:
            with csv_path.open('r', encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle)
                for raw_row in reader:
                    run_id = _clean_text(raw_row.get('run_id'))
                    if run_id is None or run_id not in run_ids:
                        continue
                    input_path = _clean_text(raw_row.get('input_path'))
                    if input_path is None:
                        continue
                    input_name = Path(input_path).name
                    if not input_name:
                        continue
                    row = {str(key): value for key, value in raw_row.items()}
                    existing = rows_by_run_and_input[run_id].get(input_name)
                    if existing is None or _telemetry_row_sort_key(row) >= _telemetry_row_sort_key(existing):
                        rows_by_run_and_input[run_id][input_name] = row
                        csv_source_by_run_id[run_id] = str(csv_path)
        except OSError:
            continue
    return (rows_by_run_and_input, csv_source_by_run_id)

def _load_run_assets_for_process_run(*, process_run_payload: dict[str, Any] | None, repo_root: Path) -> dict[str, Any]:
    if not isinstance(process_run_payload, dict):
        return {}
    run_id = str(process_run_payload.get('run_id') or '').strip()
    if not run_id:
        return {}
    run_assets_dir = (repo_root / 'var' / 'run_assets' / run_id).resolve()
    if not run_assets_dir.exists() or not run_assets_dir.is_dir():
        return {'run_id': run_id}
    assets_manifest = _load_json_dict(run_assets_dir / 'manifest.json') or {}
    prompt_template_text = _safe_read_text(run_assets_dir / 'prompt.template.txt')
    output_schema_payload = _load_json_dict(run_assets_dir / 'output.schema.json')
    effective_pipeline_payload = _load_json_dict(run_assets_dir / 'effective_pipeline.json')
    pipeline_source_payload = _load_json_dict(run_assets_dir / 'pipeline.source.json')
    source_metadata = assets_manifest.get('source_metadata')
    prompt_source_path = None
    output_schema_source_path = None
    if isinstance(source_metadata, dict):
        prompt_source_path = str(source_metadata.get('prompt_source_path') or '').strip() or None
        output_schema_source_path = str(source_metadata.get('output_schema_source_path') or '').strip() or None
    return {'run_id': run_id, 'run_assets_dir': str(run_assets_dir), 'prompt_template_text': prompt_template_text, 'prompt_source_path': prompt_source_path, 'output_schema_source_path': output_schema_source_path, 'output_schema_payload': output_schema_payload, 'effective_pipeline_payload': effective_pipeline_payload, 'pipeline_source_payload': pipeline_source_payload}

def _collect_prompt_attachments(payload: Any, *, prompt_file: Path, pred_run: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def _walk(node: Any, current_key: str | None=None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(value, str(key))
            return
        if isinstance(node, list):
            for value in node:
                _walk(value, current_key)
            return
        if not isinstance(node, str):
            return
        key = (current_key or '').strip().lower()
        if 'path' not in key and 'file' not in key:
            return
        raw_value = node.strip()
        if not raw_value or '\n' in raw_value or re.match('^[a-z]+://', raw_value):
            return
        candidate = Path(raw_value)
        candidates: list[Path] = []
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.append((prompt_file.parent / candidate).resolve())
            candidates.append((pred_run / candidate).resolve())
        for resolved in candidates:
            if resolved.exists() and resolved.is_file() and (resolved.suffix.lower() in _TEXT_ATTACHMENT_SUFFIXES):
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
                break
    _walk(payload)
    return found

def _resolve_saved_artifact_path(*, raw_path: str | None, repo_root: Path) -> Path | None:
    cleaned = _clean_text(raw_path)
    if cleaned is None:
        return None
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = (repo_root / candidate).resolve()
    resolved = candidate.resolve(strict=False)
    if resolved.exists() and resolved.is_file():
        return resolved
    return None

def _parse_prompt_index_from_name(name: str) -> int | None:
    match = re.search('(\\d+)', str(name or ''))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None

def _load_prompt_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows

def _load_json_sequence(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]

def _load_phase_runtime_index(stage_root: Path) -> dict[str, Any]:
    phase_manifest = _load_json_dict(stage_root / 'phase_manifest.json') or {}
    if not phase_manifest:
        return {}
    worker_assignments = _load_json_sequence(stage_root / 'worker_assignments.json')
    shard_rows = _load_prompt_rows(stage_root / 'shard_manifest.jsonl')
    worker_by_shard_id: dict[str, str] = {}
    for assignment in worker_assignments:
        worker_id = _clean_text(assignment.get('worker_id'))
        if worker_id is None:
            continue
        for shard_id in assignment.get('shard_ids') or []:
            rendered_shard_id = _clean_text(shard_id)
            if rendered_shard_id is not None:
                worker_by_shard_id[rendered_shard_id] = worker_id
    shard_by_id: dict[str, dict[str, Any]] = {}
    shard_by_owned_id: dict[str, dict[str, Any]] = {}
    shard_by_prompt_index: dict[int, dict[str, Any]] = {}
    telemetry_by_shard_id: dict[str, dict[str, Any]] = {}
    telemetry_payload = _load_json_dict(stage_root / 'telemetry.json') or {}
    telemetry_rows = telemetry_payload.get('rows') if isinstance(telemetry_payload.get('rows'), list) else []
    for row in telemetry_rows:
        if not isinstance(row, dict):
            continue
        shard_id = _clean_text(row.get('task_id'))
        if shard_id is not None:
            telemetry_by_shard_id[shard_id] = dict(row)
    for row in shard_rows:
        shard_id = _clean_text(row.get('shard_id'))
        if shard_id is None:
            continue
        normalized = {'shard_id': shard_id, 'owned_ids': [str(item).strip() for item in row.get('owned_ids') or [] if str(item).strip()], 'worker_id': worker_by_shard_id.get(shard_id), 'input_file': None, 'debug_input_file': None, 'telemetry_row': telemetry_by_shard_id.get(shard_id), 'metadata': dict(row.get('metadata') or {}) if isinstance(row.get('metadata'), dict) else {}}
        worker_id = normalized.get('worker_id')
        if worker_id:
            input_file = stage_root / 'workers' / str(worker_id) / 'in' / f'{shard_id}.json'
            if input_file.exists() and input_file.is_file():
                normalized['input_file'] = str(input_file)
            debug_input_file = stage_root / 'workers' / str(worker_id) / 'debug' / f'{shard_id}.json'
            if debug_input_file.exists() and debug_input_file.is_file():
                normalized['debug_input_file'] = str(debug_input_file)
        shard_by_id[shard_id] = normalized
        for owned_id in normalized['owned_ids']:
            shard_by_owned_id[owned_id] = normalized
        prompt_index = _coerce_int(normalized['metadata'].get('prompt_index'))
        if prompt_index is not None:
            shard_by_prompt_index[prompt_index] = normalized
    return {'pipeline_id': _clean_text(phase_manifest.get('pipeline_id')), 'shard_by_id': shard_by_id, 'shard_by_owned_id': shard_by_owned_id, 'shard_by_prompt_index': shard_by_prompt_index, 'telemetry_by_shard_id': telemetry_by_shard_id}

def _resolve_runtime_context(*, runtime_index: Mapping[str, Any] | None, shard_id: str | None=None, owned_id: str | None=None, prompt_index: int | None=None) -> dict[str, Any]:
    if not isinstance(runtime_index, Mapping):
        return {}
    shard_row = None
    if shard_id:
        shard_row = (runtime_index.get('shard_by_id') or {}).get(shard_id)
    if shard_row is None and owned_id:
        shard_row = (runtime_index.get('shard_by_owned_id') or {}).get(owned_id)
    if shard_row is None and prompt_index is not None:
        shard_row = (runtime_index.get('shard_by_prompt_index') or {}).get(prompt_index)
    if not isinstance(shard_row, Mapping):
        return {}
    return {'runtime_pipeline_id': runtime_index.get('pipeline_id'), 'runtime_shard_id': shard_row.get('shard_id'), 'runtime_worker_id': shard_row.get('worker_id'), 'runtime_owned_ids': list(shard_row.get('owned_ids') or []), 'request_input_file': shard_row.get('input_file'), 'debug_input_file': shard_row.get('debug_input_file'), 'runtime_telemetry_row': dict(shard_row.get('telemetry_row')) if isinstance(shard_row.get('telemetry_row'), Mapping) else None}

def _prompt_row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (_coerce_int(row.get('stage_order')) or 999, str(row.get('stage_key') or ''), str(row.get('call_id') or ''))

def _upsert_text_section(*, path: Path, start_marker: str, end_marker: str, body: str) -> None:
    text = path.read_text(encoding='utf-8') if path.exists() and path.is_file() else ''
    start_index = text.find(start_marker)
    end_index = text.find(end_marker)
    section_text = f'{start_marker}\n{body.rstrip()}\n{end_marker}\n'
    if start_index >= 0 and end_index >= 0 and (end_index >= start_index):
        end_index += len(end_marker)
        if end_index < len(text) and text[end_index:end_index + 1] == '\n':
            end_index += 1
        updated = text[:start_index].rstrip()
        if updated:
            updated += '\n\n'
        updated += section_text
        suffix = text[end_index:].lstrip('\n')
        if suffix:
            updated += '\n' + suffix
        path.write_text(updated.rstrip() + '\n', encoding='utf-8')
        return
    updated = text.rstrip()
    if updated:
        updated += '\n\n'
    updated += section_text
    path.write_text(updated.rstrip() + '\n', encoding='utf-8')

def _resolve_stage_run_root_for_prompt_exports(*, pred_run: Path) -> Path | None:
    candidate = pred_run.resolve(strict=False)
    if candidate.is_dir() and ((candidate / 'raw' / 'llm').is_dir() or (candidate / 'line-role-pipeline' / 'prompts').is_dir()):
        return candidate
    prediction_run_manifest = _load_json_dict(pred_run / 'run_manifest.json')
    prediction_artifacts = prediction_run_manifest.get('artifacts') if isinstance(prediction_run_manifest, dict) else None
    if not isinstance(prediction_artifacts, dict):
        return None
    for artifact_key in ('stage_run_dir', 'processed_output_run_dir'):
        resolved = _resolve_artifact_path(pred_run, prediction_artifacts.get(artifact_key))
        if resolved is None or not resolved.exists() or (not resolved.is_dir()):
            continue
        if (resolved / 'raw' / 'llm').is_dir() or (resolved / 'line-role-pipeline' / 'prompts').is_dir():
            return resolved
    return None

def _copy_prompt_artifact_file(*, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except Exception:
        target.write_text(_safe_read_text(source), encoding='utf-8')
