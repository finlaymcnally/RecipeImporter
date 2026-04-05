from __future__ import annotations

import sys


def _resolve_root_module():
    module = sys.modules.get("scripts.benchmark_cutdown_for_external_ai")
    if module is None:
        for candidate in sys.modules.values():
            module_file = getattr(candidate, "__file__", None)
            if str(module_file or "").endswith("scripts/benchmark_cutdown_for_external_ai.py"):
                module = candidate
                break
    if module is None:
        module = sys.modules.get("__main__")
    if module is None:
        raise RuntimeError("benchmark_cutdown_for_external_ai root module is not loaded")
    return module


class _RootProxy:
    def __getattr__(self, name: str):
        return getattr(_resolve_root_module(), name)


root = _RootProxy()
def _upload_bundle_nested_numeric(payload: root.Any, paths: tuple[tuple[str, ...], ...], *, integer: bool=False) -> int | float | None:
    for path in paths:
        current: root.Any = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if integer:
            value = root._coerce_int(current)
            if value is not None:
                return value
        else:
            value = root._coerce_float(current)
            if value is not None:
                return value
    return None

def _upload_bundle_call_inventory_stage_included(stage_key: str | None) -> bool:
    normalized = str(stage_key or '').strip()
    return bool(normalized) and (normalized == 'line_role' or normalized in root.LLM_STAGE_MAP)

def _upload_bundle_call_inventory_stage_rank(stage_key: str | None) -> int:
    normalized = str(stage_key or '').strip()
    if normalized == 'line_role':
        return -1
    return int(root.LLM_STAGE_MAP.get(normalized, {}).get('sort_order') or 99)

def _upload_bundle_extract_call_runtime(row: dict[str, root.Any]) -> dict[str, root.Any]:
    request_telemetry = row.get('request_telemetry')
    request_telemetry = request_telemetry if isinstance(request_telemetry, dict) else {}
    usage_payload = request_telemetry.get('usage_json')
    usage_payload = usage_payload if isinstance(usage_payload, dict) else {}
    duration_ms = root._upload_bundle_nested_numeric(request_telemetry, (('duration_ms',), ('duration',)), integer=True)
    tokens_input = root._upload_bundle_nested_numeric(request_telemetry, (('tokens_input',),), integer=True)
    if tokens_input is None:
        tokens_input = root._upload_bundle_nested_numeric(usage_payload, (('input_tokens',), ('prompt_tokens',), ('tokens_input',)), integer=True)
    tokens_cached_input = root._upload_bundle_nested_numeric(request_telemetry, (('tokens_cached_input',),), integer=True)
    if tokens_cached_input is None:
        tokens_cached_input = root._upload_bundle_nested_numeric(usage_payload, (('cached_input_tokens',),), integer=True)
    tokens_output = root._upload_bundle_nested_numeric(request_telemetry, (('tokens_output',),), integer=True)
    if tokens_output is None:
        tokens_output = root._upload_bundle_nested_numeric(usage_payload, (('output_tokens',), ('completion_tokens',), ('tokens_output',)), integer=True)
    tokens_reasoning = root._upload_bundle_nested_numeric(request_telemetry, (('tokens_reasoning',),), integer=True)
    if tokens_reasoning is None:
        tokens_reasoning = root._upload_bundle_nested_numeric(usage_payload, (('output_tokens_reasoning',), ('output_tokens_details', 'reasoning_tokens'), ('completion_tokens_details', 'reasoning_tokens')), integer=True)
    tokens_total = root._upload_bundle_nested_numeric(request_telemetry, (('tokens_total',),), integer=True)
    if tokens_total is None:
        tokens_total = root._upload_bundle_nested_numeric(usage_payload, (('total_tokens',), ('tokens_total',)), integer=True)
    if tokens_total is None and (tokens_input is not None or tokens_output is not None):
        tokens_total = int(tokens_input or 0) + int(tokens_output or 0)
    cost_usd = root._upload_bundle_nested_numeric(usage_payload, (('cost_usd',), ('total_cost_usd',), ('estimated_cost_usd',), ('estimated_cost',), ('cost', 'total_usd'), ('cost', 'usd')))
    if cost_usd is None:
        cost_usd = root._upload_bundle_nested_numeric(request_telemetry, (('cost_usd',), ('total_cost_usd',), ('estimated_cost_usd',), ('estimated_cost',), ('cost',)))
    return {'duration_ms': duration_ms, 'tokens_input': tokens_input, 'tokens_cached_input': tokens_cached_input, 'tokens_output': tokens_output, 'tokens_reasoning': tokens_reasoning, 'tokens_total': tokens_total, 'cost_usd': cost_usd, 'attempt_index': root._coerce_int(request_telemetry.get('attempt_index')), 'status': str(request_telemetry.get('status') or '').strip() or None}

def _upload_bundle_estimate_call_cost_usd(*, tokens_input: int | None, tokens_cached_input: int | None, tokens_output: int | None) -> float | None:
    if tokens_input is None and tokens_output is None:
        return None
    input_tokens = int(tokens_input or 0)
    cached_tokens = int(tokens_cached_input or 0)
    if cached_tokens < 0:
        cached_tokens = 0
    if cached_tokens > input_tokens:
        cached_tokens = input_tokens
    uncached_tokens = max(input_tokens - cached_tokens, 0)
    output_tokens = int(tokens_output or 0)
    pricing = root.UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING
    total_cost = uncached_tokens / 1000000.0 * float(pricing['input_per_1m']) + cached_tokens / 1000000.0 * float(pricing['cached_input_per_1m']) + output_tokens / 1000000.0 * float(pricing['output_per_1m'])
    return round(total_cost, 8)

def _upload_bundle_iter_unique_run_dirs(*, run_dirs: list[root.Path] | None=None, run_dir_by_id: dict[str, root.Path] | None=None) -> list[root.Path]:
    candidates: list[root.Path] = []
    if isinstance(run_dirs, list):
        candidates.extend([item for item in run_dirs if isinstance(item, root.Path)])
    if isinstance(run_dir_by_id, dict):
        candidates.extend([item for item in run_dir_by_id.values() if isinstance(item, root.Path)])
    unique: list[root.Path] = []
    seen: set[str] = set()
    for run_dir in candidates:
        key = str(run_dir.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(run_dir)
    return unique

def _upload_bundle_normalize_runtime_stage_key(stage_key: str | None) -> str:
    rendered = str(stage_key or '').strip()
    if rendered == 'recipe_correction':
        return 'recipe_refine'
    if rendered == 'knowledge':
        return 'nonrecipe_finalize'
    return rendered

def _upload_bundle_collect_call_runtime_map(*, run_dirs: list[root.Path] | None=None, run_dir_by_id: dict[str, root.Path] | None=None) -> dict[tuple[str, str, str, str, str], dict[str, root.Any]]:
    runtime_by_key: dict[tuple[str, str, str, str, str], dict[str, root.Any]] = {}
    for run_dir in root._upload_bundle_iter_unique_run_dirs(run_dirs=run_dirs, run_dir_by_id=run_dir_by_id):
        run_manifest_path = run_dir / 'run_manifest.json'
        if not run_manifest_path.is_file():
            continue
        run_manifest = root._upload_bundle_load_json_object(run_manifest_path)
        manifest_run_id = str(run_manifest.get('run_id') or run_dir.name).strip() or run_dir.name
        source_payload = run_manifest.get('source') if isinstance(run_manifest.get('source'), dict) else {}
        source_path = source_payload.get('path') if isinstance(source_payload, dict) else None
        source_hash = source_payload.get('source_hash') if isinstance(source_payload, dict) else None
        source_file = root._source_file_name(source_path if isinstance(source_path, str) else None)
        source_key = root._source_key(source_hash if isinstance(source_hash, str) else None, source_file)
        full_prompt_path = root._resolve_full_prompt_log_path(run_dir, run_manifest)
        if full_prompt_path is None or not full_prompt_path.is_file():
            continue
        for prompt_row in root._iter_jsonl(full_prompt_path):
            stage_key = root._prompt_row_stage_key(prompt_row)
            call_id = str(prompt_row.get('call_id') or '').strip()
            recipe_id = root._prompt_row_recipe_id(prompt_row)
            if not root._upload_bundle_call_inventory_stage_included(stage_key) or not call_id:
                continue
            row_run_id = str(prompt_row.get('run_id') or manifest_run_id).strip() or manifest_run_id
            key = (source_key, row_run_id, recipe_id, stage_key, call_id)
            runtime_payload = root._upload_bundle_extract_call_runtime(prompt_row)
            existing = runtime_by_key.get(key)
            if existing is None:
                runtime_by_key[key] = runtime_payload
                continue
            existing_attempt = root._coerce_int(existing.get('attempt_index')) or -1
            next_attempt = root._coerce_int(runtime_payload.get('attempt_index')) or -1
            if next_attempt >= existing_attempt:
                runtime_by_key[key] = runtime_payload
    return runtime_by_key

def _upload_bundle_telemetry_call_count(summary: dict[str, root.Any]) -> int | None:
    call_count = root._coerce_int(summary.get('call_count'))
    if call_count is not None:
        return max(int(call_count), 0)
    status_counts = summary.get('status_counts')
    if isinstance(status_counts, dict):
        raw_values = [root._coerce_int(value) for value in status_counts.values()]
        if any((value is not None for value in raw_values)):
            return int(sum((int(value or 0) for value in raw_values)))
    matched_rows = root._coerce_int(summary.get('matched_rows'))
    if matched_rows is not None:
        return max(int(matched_rows), 0)
    return None

def _upload_bundle_token_share_fields(*, by_stage: dict[str, dict[str, root.Any]], total_tokens: int | None) -> dict[str, float | None]:
    fields: dict[str, float | None] = {}
    for stage_key in sorted(by_stage, key=root._prompt_category_sort_key):
        share_key = f'{stage_key}_token_share'
        stage_payload = by_stage.get(stage_key)
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        stage_tokens = root._coerce_int(stage_payload.get('total_tokens'))
        if total_tokens is None or total_tokens <= 0 or stage_tokens is None or (stage_tokens < 0):
            fields[share_key] = None
            continue
        fields[share_key] = round(float(stage_tokens) / float(total_tokens), 4)
    return fields

def _upload_bundle_load_prompt_budget_summary(*, run_dir: root.Path, pred_run_dir: root.Path | None, pred_manifest: dict[str, root.Any]) -> dict[str, root.Any] | None:
    candidate = root._resolve_prompt_budget_summary_path(run_dir=run_dir, pred_run_dir=pred_run_dir, pred_manifest=pred_manifest)
    if isinstance(candidate, root.Path):
        if not candidate.is_file():
            return None
        payload = root._upload_bundle_load_json_object(candidate)
        if isinstance(payload.get('by_stage'), dict):
            return payload
    return None

def _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(*, run_dirs: list[root.Path] | None=None, run_dir_by_id: dict[str, root.Path] | None=None) -> dict[str, root.Any] | None:
    aggregate_by_stage: dict[str, dict[str, root.Any]] = {}
    used_prompt_budget_summary = False
    for run_dir in root._upload_bundle_iter_unique_run_dirs(run_dirs=run_dirs, run_dir_by_id=run_dir_by_id):
        run_manifest_path = run_dir / 'run_manifest.json'
        if not run_manifest_path.is_file():
            continue
        run_manifest = root._upload_bundle_load_json_object(run_manifest_path)
        pred_run_dir = root._resolve_prediction_run_dir(run_dir, run_manifest)
        pred_manifest_path = pred_run_dir / 'manifest.json' if pred_run_dir is not None else None
        pred_manifest = root._upload_bundle_load_json_object(pred_manifest_path) if isinstance(pred_manifest_path, root.Path) and pred_manifest_path.is_file() else {}
        prompt_budget_summary = root._upload_bundle_load_prompt_budget_summary(run_dir=run_dir, pred_run_dir=pred_run_dir, pred_manifest=pred_manifest)
        if isinstance(prompt_budget_summary, dict):
            by_stage_payload = prompt_budget_summary.get('by_stage')
            if isinstance(by_stage_payload, dict) and by_stage_payload:
                used_prompt_budget_summary = True
                for pass_name, pass_payload in sorted(by_stage_payload.items()):
                    if not isinstance(pass_payload, dict):
                        continue
                    normalized_stage_key = root._upload_bundle_normalize_runtime_stage_key(pass_name)
                    bucket = aggregate_by_stage.setdefault(normalized_stage_key, {'call_count': 0, 'calls_known': False, 'duration_total_ms': 0, 'duration_known': False, 'tokens_total': 0, 'tokens_known': False})
                    call_count = root._coerce_int(pass_payload.get('call_count'))
                    if call_count is not None:
                        bucket['call_count'] += max(int(call_count), 0)
                        bucket['calls_known'] = True
                    duration_total_ms = root._coerce_int(pass_payload.get('duration_total_ms'))
                    if duration_total_ms is not None:
                        bucket['duration_total_ms'] += max(int(duration_total_ms), 0)
                        bucket['duration_known'] = True
                    tokens_total = root._coerce_int(pass_payload.get('tokens_total'))
                    if tokens_total is not None:
                        bucket['tokens_total'] += max(int(tokens_total), 0)
                        bucket['tokens_known'] = True
                continue
        if pred_run_dir is None or not isinstance(pred_manifest_path, root.Path) or (not pred_manifest_path.is_file()):
            continue
        llm_payload = pred_manifest.get('llm_codex_farm') if isinstance(pred_manifest, dict) else {}
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        knowledge_payload = llm_payload.get('knowledge')
        knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
        process_runs = llm_payload.get('process_runs')
        process_runs = process_runs if isinstance(process_runs, dict) else {}
        process_payload_by_stage = {'recipe_correction': process_runs.get('recipe_correction') or process_runs.get('recipe_refine'), 'nonrecipe_finalize': process_runs.get('nonrecipe_finalize') or (knowledge_payload.get('process_run') if isinstance(knowledge_payload.get('process_run'), dict) else None)}
        for stage_key, pass_payload in process_payload_by_stage.items():
            pass_payload = pass_payload if isinstance(pass_payload, dict) else {}
            telemetry_report = pass_payload.get('telemetry_report')
            telemetry_report = telemetry_report if isinstance(telemetry_report, dict) else {}
            summary = telemetry_report.get('summary')
            if not isinstance(summary, dict):
                continue
            normalized_stage_key = root._upload_bundle_normalize_runtime_stage_key(stage_key)
            bucket = aggregate_by_stage.setdefault(normalized_stage_key, {'call_count': 0, 'calls_known': False, 'duration_total_ms': 0, 'duration_known': False, 'tokens_total': 0, 'tokens_known': False})
            call_count = root._upload_bundle_telemetry_call_count(summary)
            if call_count is not None:
                bucket['call_count'] += max(int(call_count), 0)
                bucket['calls_known'] = True
            duration_total_ms = root._coerce_int(summary.get('duration_total_ms'))
            if duration_total_ms is None:
                duration_avg_ms = root._coerce_float(summary.get('duration_avg_ms'))
                if duration_avg_ms is not None and call_count is not None and (int(call_count) > 0):
                    duration_total_ms = int(round(float(duration_avg_ms) * int(call_count)))
            if duration_total_ms is not None:
                bucket['duration_total_ms'] += max(int(duration_total_ms), 0)
                bucket['duration_known'] = True
            tokens_total = root._coerce_int(summary.get('tokens_total'))
            if tokens_total is not None:
                bucket['tokens_total'] += max(int(tokens_total), 0)
                bucket['tokens_known'] = True
    if not aggregate_by_stage:
        return None
    by_stage: dict[str, dict[str, root.Any]] = {}
    for pass_name in sorted(aggregate_by_stage.keys()):
        bucket = aggregate_by_stage.get(pass_name)
        if not isinstance(bucket, dict):
            continue
        call_count = int(bucket.get('call_count') or 0)
        calls_known = bool(bucket.get('calls_known'))
        duration_known = bool(bucket.get('duration_known'))
        tokens_known = bool(bucket.get('tokens_known'))
        duration_total_ms = int(bucket.get('duration_total_ms') or 0) if duration_known else None
        by_stage[pass_name] = {'call_count': call_count if calls_known else 0, 'calls_with_runtime': call_count if calls_known and duration_known else 0, 'calls_with_cost': 0, 'calls_with_estimated_cost': 0, 'avg_duration_ms': round(float(duration_total_ms) / float(call_count), 3) if duration_total_ms is not None and calls_known and (call_count > 0) else None, 'total_tokens': int(bucket.get('tokens_total') or 0) if tokens_known else None, 'total_cost_usd': None, 'total_estimated_cost_usd': None, 'cost_coverage_ratio': 0.0, 'estimated_cost_coverage_ratio': 0.0}
    total_calls = int(sum((int(payload.get('call_count') or 0) for payload in by_stage.values())))
    total_calls_with_runtime = int(sum((int(payload.get('calls_with_runtime') or 0) for payload in by_stage.values())))
    duration_totals = [int(bucket.get('duration_total_ms') or 0) for bucket in aggregate_by_stage.values() if bool(bucket.get('duration_known'))]
    total_duration_ms = int(sum(duration_totals)) if duration_totals else None
    token_totals = [root._coerce_int(payload.get('total_tokens')) for payload in by_stage.values() if root._coerce_int(payload.get('total_tokens')) is not None]
    total_tokens = int(sum(token_totals)) if token_totals else None
    summary = {'call_count': total_calls, 'calls_with_runtime': total_calls_with_runtime, 'calls_with_cost': 0, 'calls_with_estimated_cost': 0, 'total_duration_ms': total_duration_ms, 'avg_duration_ms': round(float(total_duration_ms) / float(total_calls_with_runtime), 3) if total_duration_ms is not None and total_calls_with_runtime > 0 else None, 'total_tokens': total_tokens, 'total_cost_usd': None, 'total_estimated_cost_usd': None, 'cost_coverage_ratio': 0.0, 'estimated_cost_coverage_ratio': 0.0, 'cost_signal': {'available': False, 'calls_with_cost': 0, 'coverage_ratio': 0.0, 'unavailable_reason': 'prediction-run telemetry summaries do not expose per-call observed cost fields'}, 'estimated_cost_signal': {'available': False, 'calls_with_estimated_cost': 0, 'coverage_ratio': 0.0, 'method': '', 'pricing_used': dict(root.UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING), 'note': 'No per-call token telemetry available; aggregate stage totals cannot be reliably cost-estimated per call.'}, 'by_stage': by_stage, 'runtime_source': 'prediction_run_prompt_budget_summary' if used_prompt_budget_summary else 'prediction_run_manifest_telemetry'}
    summary.update(root._upload_bundle_token_share_fields(by_stage=by_stage, total_tokens=total_tokens))
    return {'summary': summary, 'by_source': [], 'top_slowest_calls': [], 'top_token_calls': [], 'top_cost_calls': [], 'top_estimated_cost_calls': []}

def _upload_bundle_runtime_inventory_needs_fallback(*, row_summary: dict[str, root.Any], fallback_summary: dict[str, root.Any]) -> bool:
    row_calls_with_runtime = int(root._coerce_int(row_summary.get('calls_with_runtime')) or 0)
    fallback_calls_with_runtime = int(root._coerce_int(fallback_summary.get('calls_with_runtime')) or 0)
    if fallback_calls_with_runtime > row_calls_with_runtime:
        return True
    row_total_tokens = root._coerce_int(row_summary.get('total_tokens'))
    fallback_total_tokens = root._coerce_int(fallback_summary.get('total_tokens'))
    if row_total_tokens is None and fallback_total_tokens is not None:
        return True
    row_stage_count = len(row_summary.get('by_stage') or {})
    fallback_stage_count = len(fallback_summary.get('by_stage') or {})
    if fallback_stage_count > row_stage_count:
        return True
    row_call_count = int(root._coerce_int(row_summary.get('call_count')) or 0)
    fallback_call_count = int(root._coerce_int(fallback_summary.get('call_count')) or 0)
    if fallback_call_count > row_call_count and (fallback_total_tokens is not None or fallback_calls_with_runtime > 0):
        return True
    row_by_stage = row_summary.get('by_stage')
    row_by_stage = row_by_stage if isinstance(row_by_stage, dict) else {}
    fallback_by_stage = fallback_summary.get('by_stage')
    fallback_by_stage = fallback_by_stage if isinstance(fallback_by_stage, dict) else {}
    for stage_key, fallback_stage in fallback_by_stage.items():
        if not isinstance(fallback_stage, dict):
            continue
        row_stage = row_by_stage.get(stage_key)
        row_stage = row_stage if isinstance(row_stage, dict) else {}
        row_stage_call_count = int(root._coerce_int(row_stage.get('call_count')) or 0)
        fallback_stage_call_count = int(root._coerce_int(fallback_stage.get('call_count')) or 0)
        row_stage_runtime = int(root._coerce_int(row_stage.get('calls_with_runtime')) or 0)
        fallback_stage_runtime = int(root._coerce_int(fallback_stage.get('calls_with_runtime')) or 0)
        row_stage_tokens = root._coerce_int(row_stage.get('total_tokens'))
        fallback_stage_tokens = root._coerce_int(fallback_stage.get('total_tokens'))
        if fallback_stage_runtime > row_stage_runtime:
            return True
        if row_stage_tokens is None and fallback_stage_tokens is not None:
            return True
        if fallback_stage_tokens is not None and row_stage_tokens is not None and (fallback_stage_tokens > row_stage_tokens) and (fallback_stage_call_count >= row_stage_call_count):
            return True
    return False

def _upload_bundle_stage_total_duration_ms(stage_payload: dict[str, root.Any]) -> int | None:
    calls_with_runtime = int(root._coerce_int(stage_payload.get('calls_with_runtime')) or 0)
    avg_duration_ms = root._coerce_float(stage_payload.get('avg_duration_ms'))
    if calls_with_runtime <= 0 or avg_duration_ms is None:
        return None
    return int(round(avg_duration_ms * float(calls_with_runtime)))

def _upload_bundle_merge_runtime_stage_summary(*, row_stage: dict[str, root.Any], fallback_stage: dict[str, root.Any]) -> dict[str, root.Any]:
    merged: dict[str, root.Any] = {}
    row_call_count = int(root._coerce_int(row_stage.get('call_count')) or 0)
    fallback_call_count = int(root._coerce_int(fallback_stage.get('call_count')) or 0)
    row_calls_with_runtime = int(root._coerce_int(row_stage.get('calls_with_runtime')) or 0)
    fallback_calls_with_runtime = int(root._coerce_int(fallback_stage.get('calls_with_runtime')) or 0)
    row_total_tokens = root._coerce_int(row_stage.get('total_tokens'))
    fallback_total_tokens = root._coerce_int(fallback_stage.get('total_tokens'))
    row_total_duration_ms = root._upload_bundle_stage_total_duration_ms(row_stage)
    fallback_total_duration_ms = root._upload_bundle_stage_total_duration_ms(fallback_stage)
    merged['call_count'] = max(row_call_count, fallback_call_count)
    merged['calls_with_runtime'] = max(row_calls_with_runtime, fallback_calls_with_runtime)
    merged['calls_with_cost'] = int(root._coerce_int(row_stage.get('calls_with_cost')) or 0)
    merged['calls_with_estimated_cost'] = int(root._coerce_int(row_stage.get('calls_with_estimated_cost')) or 0)
    if fallback_total_tokens is not None and (row_total_tokens is None or fallback_total_tokens > row_total_tokens):
        merged['total_tokens'] = fallback_total_tokens
    else:
        merged['total_tokens'] = row_total_tokens
    merged_total_duration_ms: int | None
    if fallback_total_duration_ms is not None and (row_total_duration_ms is None or fallback_total_duration_ms > row_total_duration_ms):
        merged_total_duration_ms = fallback_total_duration_ms
    else:
        merged_total_duration_ms = row_total_duration_ms
    merged['avg_duration_ms'] = round(float(merged_total_duration_ms) / float(merged['calls_with_runtime']), 3) if merged_total_duration_ms is not None and merged['calls_with_runtime'] > 0 else None
    row_total_cost = root._coerce_float(row_stage.get('total_cost_usd'))
    fallback_total_cost = root._coerce_float(fallback_stage.get('total_cost_usd'))
    merged['total_cost_usd'] = row_total_cost if row_total_cost is not None else fallback_total_cost
    row_total_estimated_cost = root._coerce_float(row_stage.get('total_estimated_cost_usd'))
    fallback_total_estimated_cost = root._coerce_float(fallback_stage.get('total_estimated_cost_usd'))
    merged['total_estimated_cost_usd'] = row_total_estimated_cost if row_total_estimated_cost is not None else fallback_total_estimated_cost
    merged['cost_coverage_ratio'] = round(merged['calls_with_cost'] / merged['call_count'], 6) if merged['call_count'] > 0 else 0.0
    merged['estimated_cost_coverage_ratio'] = round(merged['calls_with_estimated_cost'] / merged['call_count'], 6) if merged['call_count'] > 0 else 0.0
    return merged

def _upload_bundle_merge_runtime_inventory_with_fallback(*, row_inventory: dict[str, root.Any], fallback_inventory: dict[str, root.Any]) -> dict[str, root.Any]:
    merged = dict(fallback_inventory)
    row_summary = row_inventory.get('summary')
    row_summary = row_summary if isinstance(row_summary, dict) else {}
    fallback_summary = fallback_inventory.get('summary')
    fallback_summary = fallback_summary if isinstance(fallback_summary, dict) else {}
    row_by_stage = row_summary.get('by_stage')
    row_by_stage = row_by_stage if isinstance(row_by_stage, dict) else {}
    fallback_by_stage = fallback_summary.get('by_stage')
    fallback_by_stage = fallback_by_stage if isinstance(fallback_by_stage, dict) else {}
    merged_by_stage: dict[str, dict[str, root.Any]] = {}
    stage_keys = sorted(fallback_by_stage, key=root._prompt_category_sort_key) if fallback_by_stage else sorted(row_by_stage, key=root._prompt_category_sort_key)
    for stage_key in stage_keys:
        row_stage = row_by_stage.get(stage_key)
        row_stage = row_stage if isinstance(row_stage, dict) else {}
        fallback_stage = fallback_by_stage.get(stage_key)
        fallback_stage = fallback_stage if isinstance(fallback_stage, dict) else {}
        merged_by_stage[stage_key] = root._upload_bundle_merge_runtime_stage_summary(row_stage=row_stage, fallback_stage=fallback_stage)
    merged_summary = dict(fallback_summary)
    merged_summary['by_stage'] = merged_by_stage
    merged_summary['call_count'] = int(sum((int(payload.get('call_count') or 0) for payload in merged_by_stage.values())))
    merged_summary['calls_with_runtime'] = int(sum((int(payload.get('calls_with_runtime') or 0) for payload in merged_by_stage.values())))
    merged_summary['calls_with_cost'] = int(sum((int(payload.get('calls_with_cost') or 0) for payload in merged_by_stage.values())))
    merged_summary['calls_with_estimated_cost'] = int(sum((int(payload.get('calls_with_estimated_cost') or 0) for payload in merged_by_stage.values())))
    duration_totals = [stage_total for payload in merged_by_stage.values() for stage_total in [root._upload_bundle_stage_total_duration_ms(payload)] if stage_total is not None]
    merged_summary['total_duration_ms'] = int(sum(duration_totals)) if duration_totals else None
    merged_summary['avg_duration_ms'] = round(float(merged_summary['total_duration_ms']) / float(merged_summary['calls_with_runtime']), 3) if merged_summary['total_duration_ms'] is not None and merged_summary['calls_with_runtime'] > 0 else None
    token_totals = [root._coerce_int(payload.get('total_tokens')) for payload in merged_by_stage.values() if root._coerce_int(payload.get('total_tokens')) is not None]
    merged_summary['total_tokens'] = int(sum(token_totals)) if token_totals else None
    cost_totals = [root._coerce_float(payload.get('total_cost_usd')) for payload in merged_by_stage.values() if root._coerce_float(payload.get('total_cost_usd')) is not None]
    merged_summary['total_cost_usd'] = round(float(sum(cost_totals)), 8) if cost_totals else None
    estimated_cost_totals = [root._coerce_float(payload.get('total_estimated_cost_usd')) for payload in merged_by_stage.values() if root._coerce_float(payload.get('total_estimated_cost_usd')) is not None]
    merged_summary['total_estimated_cost_usd'] = round(float(sum(estimated_cost_totals)), 8) if estimated_cost_totals else None
    merged_summary['cost_coverage_ratio'] = round(merged_summary['calls_with_cost'] / merged_summary['call_count'], 6) if merged_summary['call_count'] > 0 else 0.0
    merged_summary['estimated_cost_coverage_ratio'] = round(merged_summary['calls_with_estimated_cost'] / merged_summary['call_count'], 6) if merged_summary['call_count'] > 0 else 0.0
    merged_summary['cost_signal'] = dict(row_summary.get('cost_signal')) if isinstance(row_summary.get('cost_signal'), dict) else dict(fallback_summary.get('cost_signal') or {})
    merged_summary['estimated_cost_signal'] = dict(row_summary.get('estimated_cost_signal')) if isinstance(row_summary.get('estimated_cost_signal'), dict) else dict(fallback_summary.get('estimated_cost_signal') or {})
    merged_summary['cost_signal']['available'] = merged_summary['calls_with_cost'] > 0
    merged_summary['cost_signal']['calls_with_cost'] = merged_summary['calls_with_cost']
    merged_summary['cost_signal']['coverage_ratio'] = merged_summary['cost_coverage_ratio']
    if merged_summary['calls_with_cost'] > 0:
        merged_summary['cost_signal']['unavailable_reason'] = ''
    merged_summary['estimated_cost_signal']['available'] = merged_summary['calls_with_estimated_cost'] > 0
    merged_summary['estimated_cost_signal']['calls_with_estimated_cost'] = merged_summary['calls_with_estimated_cost']
    merged_summary['estimated_cost_signal']['coverage_ratio'] = merged_summary['estimated_cost_coverage_ratio']
    fallback_runtime_source = str(fallback_summary.get('runtime_source') or '').strip()
    merged_summary['runtime_source'] = f'call_inventory_rows_plus_{fallback_runtime_source}' if fallback_runtime_source else 'call_inventory_rows_plus_fallback'
    merged_summary.update(root._upload_bundle_token_share_fields(by_stage=merged_by_stage, total_tokens=root._coerce_int(merged_summary.get('total_tokens'))))
    merged['summary'] = merged_summary
    for key in ('top_slowest_calls', 'top_token_calls', 'top_cost_calls', 'top_estimated_cost_calls'):
        merged[key] = list(row_inventory.get(key) or [])
    row_by_source = row_inventory.get('by_source')
    if isinstance(row_by_source, list) and row_by_source:
        merged['by_source'] = row_by_source
    return merged

def _upload_bundle_build_call_runtime_inventory(*, call_inventory_rows: list[dict[str, root.Any]], run_dir_by_id: dict[str, root.Path], run_dirs: list[root.Path] | None=None) -> dict[str, root.Any]:
    runtime_by_key = root._upload_bundle_collect_call_runtime_map(run_dirs=run_dirs, run_dir_by_id=run_dir_by_id)
    telemetry_fallback = root._upload_bundle_build_call_runtime_inventory_from_prediction_manifest(run_dirs=run_dirs, run_dir_by_id=run_dir_by_id)
    enriched_rows: list[dict[str, root.Any]] = []
    for row in call_inventory_rows:
        source_key = str(row.get('source_key') or '').strip()
        run_id = str(row.get('run_id') or '').strip()
        recipe_id = str(row.get('recipe_id') or '').strip()
        stage_key = root._prompt_row_stage_key(row)
        call_id = str(row.get('call_id') or '').strip()
        runtime = runtime_by_key.get((source_key, run_id, recipe_id, stage_key, call_id))
        if not isinstance(runtime, dict):
            runtime = runtime_by_key.get(('', run_id, recipe_id, stage_key, call_id))
        if not isinstance(runtime, dict):
            runtime = {}
            for runtime_key, runtime_payload in runtime_by_key.items():
                if not isinstance(runtime_key, tuple) or len(runtime_key) != 5 or (not isinstance(runtime_payload, dict)):
                    continue
                _runtime_source_key, runtime_run_id, runtime_recipe_id, runtime_stage_key, runtime_call_id = runtime_key
                if str(runtime_run_id) == run_id and str(runtime_recipe_id) == recipe_id and (str(runtime_stage_key) == stage_key) and (str(runtime_call_id) == call_id):
                    runtime = runtime_payload
                    break
        observed_cost_usd = root._coerce_float(runtime.get('cost_usd'))
        estimated_cost_usd = observed_cost_usd if observed_cost_usd is not None else root._upload_bundle_estimate_call_cost_usd(tokens_input=root._coerce_int(runtime.get('tokens_input')), tokens_cached_input=root._coerce_int(runtime.get('tokens_cached_input')), tokens_output=root._coerce_int(runtime.get('tokens_output')))
        enriched_rows.append({**row, 'duration_ms': root._coerce_int(runtime.get('duration_ms')), 'tokens_input': root._coerce_int(runtime.get('tokens_input')), 'tokens_cached_input': root._coerce_int(runtime.get('tokens_cached_input')), 'tokens_output': root._coerce_int(runtime.get('tokens_output')), 'tokens_reasoning': root._coerce_int(runtime.get('tokens_reasoning')), 'tokens_total': root._coerce_int(runtime.get('tokens_total')), 'cost_usd': observed_cost_usd, 'estimated_cost_usd': estimated_cost_usd, 'cost_source': 'observed_telemetry' if observed_cost_usd is not None else 'estimated_from_tokens_default_pricing' if estimated_cost_usd is not None else None, 'retry_attempt': root._coerce_int(runtime.get('attempt_index')), 'runtime_status': runtime.get('status')})
    if not enriched_rows and telemetry_fallback is not None:
        return telemetry_fallback
    duration_values = [root._coerce_int(row.get('duration_ms')) for row in enriched_rows if root._coerce_int(row.get('duration_ms')) is not None]
    token_totals = [root._coerce_int(row.get('tokens_total')) for row in enriched_rows if root._coerce_int(row.get('tokens_total')) is not None]
    cost_values = [root._coerce_float(row.get('cost_usd')) for row in enriched_rows if root._coerce_float(row.get('cost_usd')) is not None]
    estimated_cost_values = [root._coerce_float(row.get('estimated_cost_usd')) for row in enriched_rows if root._coerce_float(row.get('estimated_cost_usd')) is not None]
    calls_with_cost = len(cost_values)
    cost_coverage_ratio = round(calls_with_cost / len(enriched_rows), 6) if enriched_rows else 0.0
    calls_with_estimated_cost = len(estimated_cost_values)
    estimated_cost_coverage_ratio = round(calls_with_estimated_cost / len(enriched_rows), 6) if enriched_rows else 0.0
    by_stage: dict[str, dict[str, root.Any]] = {}
    stage_keys = sorted({root._prompt_row_stage_key(row) for row in enriched_rows if root._prompt_row_stage_key(row)}, key=root._prompt_category_sort_key)
    for stage_key in stage_keys:
        stage_rows = [row for row in enriched_rows if root._prompt_row_stage_key(row) == stage_key]
        stage_duration = [root._coerce_int(row.get('duration_ms')) for row in stage_rows if root._coerce_int(row.get('duration_ms')) is not None]
        stage_tokens = [root._coerce_int(row.get('tokens_total')) for row in stage_rows if root._coerce_int(row.get('tokens_total')) is not None]
        stage_cost = [root._coerce_float(row.get('cost_usd')) for row in stage_rows if root._coerce_float(row.get('cost_usd')) is not None]
        stage_estimated_cost = [root._coerce_float(row.get('estimated_cost_usd')) for row in stage_rows if root._coerce_float(row.get('estimated_cost_usd')) is not None]
        stage_calls_with_cost = len(stage_cost)
        stage_calls_with_estimated_cost = len(stage_estimated_cost)
        by_stage[stage_key] = {'call_count': len(stage_rows), 'calls_with_runtime': len(stage_duration), 'calls_with_cost': stage_calls_with_cost, 'calls_with_estimated_cost': stage_calls_with_estimated_cost, 'avg_duration_ms': round(sum(stage_duration) / len(stage_duration), 3) if stage_duration else None, 'total_tokens': int(sum(stage_tokens)) if stage_tokens else None, 'total_cost_usd': round(float(sum(stage_cost)), 8) if stage_cost else None, 'total_estimated_cost_usd': round(float(sum(stage_estimated_cost)), 8) if stage_estimated_cost else None, 'cost_coverage_ratio': round(stage_calls_with_cost / len(stage_rows), 6) if stage_rows else 0.0, 'estimated_cost_coverage_ratio': round(stage_calls_with_estimated_cost / len(stage_rows), 6) if stage_rows else 0.0}
    top_slowest = sorted([row for row in enriched_rows if root._coerce_int(row.get('duration_ms')) is not None], key=lambda row: (-int(root._coerce_int(row.get('duration_ms')) or 0), str(row.get('run_id') or ''), str(row.get('call_id') or '')))[:12]
    top_token = sorted([row for row in enriched_rows if root._coerce_int(row.get('tokens_total')) is not None], key=lambda row: (-int(root._coerce_int(row.get('tokens_total')) or 0), str(row.get('run_id') or ''), str(row.get('call_id') or '')))[:12]
    top_cost = sorted([row for row in enriched_rows if root._coerce_float(row.get('cost_usd')) is not None], key=lambda row: (-float(root._coerce_float(row.get('cost_usd')) or 0.0), str(row.get('run_id') or ''), str(row.get('call_id') or '')))[:12]
    top_estimated_cost = sorted([row for row in enriched_rows if root._coerce_float(row.get('estimated_cost_usd')) is not None], key=lambda row: (-float(root._coerce_float(row.get('estimated_cost_usd')) or 0.0), str(row.get('run_id') or ''), str(row.get('call_id') or '')))[:12]
    total_tokens = int(sum(token_totals)) if token_totals else None
    summary = {'call_count': len(enriched_rows), 'calls_with_runtime': len(duration_values), 'calls_with_cost': calls_with_cost, 'calls_with_estimated_cost': calls_with_estimated_cost, 'total_duration_ms': int(sum(duration_values)) if duration_values else None, 'avg_duration_ms': round(sum(duration_values) / len(duration_values), 3) if duration_values else None, 'total_tokens': total_tokens, 'total_cost_usd': round(float(sum(cost_values)), 8) if cost_values else None, 'total_estimated_cost_usd': round(float(sum(estimated_cost_values)), 8) if estimated_cost_values else None, 'cost_coverage_ratio': cost_coverage_ratio, 'estimated_cost_coverage_ratio': estimated_cost_coverage_ratio, 'cost_signal': {'available': calls_with_cost > 0, 'calls_with_cost': calls_with_cost, 'coverage_ratio': cost_coverage_ratio, 'unavailable_reason': '' if calls_with_cost > 0 else 'request telemetry does not include recognized cost fields (cost_usd/total_cost_usd/estimated_cost_usd)'}, 'estimated_cost_signal': {'available': calls_with_estimated_cost > 0, 'calls_with_estimated_cost': calls_with_estimated_cost, 'coverage_ratio': estimated_cost_coverage_ratio, 'method': 'observed_or_default_token_pricing_estimate' if calls_with_estimated_cost > 0 else '', 'pricing_used': dict(root.UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING), 'note': 'Estimated costs use default token pricing and are not billing truth.' if calls_with_estimated_cost > 0 else 'No token-based estimate available because token telemetry is missing.'}, 'by_stage': by_stage, 'runtime_source': 'call_inventory_rows'}
    summary.update(root._upload_bundle_token_share_fields(by_stage=by_stage, total_tokens=total_tokens))
    by_source_buckets: dict[str, dict[str, root.Any]] = {}
    for row in enriched_rows:
        source_key = str(row.get('source_key') or '').strip()
        source_file = str(row.get('source_file') or '').strip()
        if not source_key:
            source_key = source_file.lower() if source_file else 'unknown_source'
        bucket = by_source_buckets.setdefault(source_key, {'source_key': source_key, 'source_file': source_file or None, 'call_count': 0, 'calls_with_runtime': 0, 'calls_with_cost': 0, 'calls_with_estimated_cost': 0, 'duration_total_ms': 0, 'duration_known': False, 'tokens_total': 0, 'tokens_known': False, 'cost_total_usd': 0.0, 'cost_known': False, 'estimated_cost_total_usd': 0.0, 'estimated_cost_known': False, 'by_stage': root.defaultdict(lambda: {'call_count': 0, 'calls_with_runtime': 0, 'calls_with_cost': 0, 'calls_with_estimated_cost': 0, 'duration_total_ms': 0, 'duration_known': False, 'tokens_total': 0, 'tokens_known': False, 'cost_total_usd': 0.0, 'cost_known': False, 'estimated_cost_total_usd': 0.0, 'estimated_cost_known': False})})
        bucket['call_count'] += 1
        stage_key = root._prompt_row_stage_key(row) or 'unknown'
        stage_bucket = bucket['by_stage'][stage_key]
        stage_bucket['call_count'] += 1
        duration_ms = root._coerce_int(row.get('duration_ms'))
        if duration_ms is not None:
            bucket['calls_with_runtime'] += 1
            bucket['duration_total_ms'] += int(duration_ms)
            bucket['duration_known'] = True
            stage_bucket['calls_with_runtime'] += 1
            stage_bucket['duration_total_ms'] += int(duration_ms)
            stage_bucket['duration_known'] = True
        tokens_total_row = root._coerce_int(row.get('tokens_total'))
        if tokens_total_row is not None:
            bucket['tokens_total'] += int(tokens_total_row)
            bucket['tokens_known'] = True
            stage_bucket['tokens_total'] += int(tokens_total_row)
            stage_bucket['tokens_known'] = True
        cost_usd = root._coerce_float(row.get('cost_usd'))
        if cost_usd is not None:
            bucket['calls_with_cost'] += 1
            bucket['cost_total_usd'] += float(cost_usd)
            bucket['cost_known'] = True
            stage_bucket['calls_with_cost'] += 1
            stage_bucket['cost_total_usd'] += float(cost_usd)
            stage_bucket['cost_known'] = True
        estimated_cost_usd_row = root._coerce_float(row.get('estimated_cost_usd'))
        if estimated_cost_usd_row is not None:
            bucket['calls_with_estimated_cost'] += 1
            bucket['estimated_cost_total_usd'] += float(estimated_cost_usd_row)
            bucket['estimated_cost_known'] = True
            stage_bucket['calls_with_estimated_cost'] += 1
            stage_bucket['estimated_cost_total_usd'] += float(estimated_cost_usd_row)
            stage_bucket['estimated_cost_known'] = True
    by_source_rows: list[dict[str, root.Any]] = []
    for source_key, bucket in by_source_buckets.items():
        call_count = int(bucket.get('call_count') or 0)
        calls_with_runtime = int(bucket.get('calls_with_runtime') or 0)
        calls_with_cost = int(bucket.get('calls_with_cost') or 0)
        calls_with_estimated_cost = int(bucket.get('calls_with_estimated_cost') or 0)
        stage_rows: dict[str, root.Any] = {}
        by_stage_payload = bucket.get('by_stage')
        if isinstance(by_stage_payload, dict):
            for stage_key in sorted(by_stage_payload.keys(), key=root._prompt_category_sort_key):
                stage_bucket = by_stage_payload.get(stage_key)
                if not isinstance(stage_bucket, dict):
                    continue
                stage_call_count = int(stage_bucket.get('call_count') or 0)
                stage_calls_with_runtime = int(stage_bucket.get('calls_with_runtime') or 0)
                stage_rows[stage_key] = {'call_count': stage_call_count, 'calls_with_runtime': stage_calls_with_runtime, 'calls_with_cost': int(stage_bucket.get('calls_with_cost') or 0), 'calls_with_estimated_cost': int(stage_bucket.get('calls_with_estimated_cost') or 0), 'total_duration_ms': int(stage_bucket.get('duration_total_ms') or 0) if bool(stage_bucket.get('duration_known')) else None, 'avg_duration_ms': round(float(int(stage_bucket.get('duration_total_ms') or 0)) / float(stage_calls_with_runtime), 3) if bool(stage_bucket.get('duration_known')) and stage_calls_with_runtime > 0 else None, 'total_tokens': int(stage_bucket.get('tokens_total') or 0) if bool(stage_bucket.get('tokens_known')) else None, 'total_cost_usd': round(float(stage_bucket.get('cost_total_usd') or 0.0), 8) if bool(stage_bucket.get('cost_known')) else None, 'total_estimated_cost_usd': round(float(stage_bucket.get('estimated_cost_total_usd') or 0.0), 8) if bool(stage_bucket.get('estimated_cost_known')) else None}
        by_source_rows.append({'source_key': source_key, 'source_file': bucket.get('source_file'), 'call_count': call_count, 'calls_with_runtime': calls_with_runtime, 'calls_with_cost': calls_with_cost, 'calls_with_estimated_cost': calls_with_estimated_cost, 'total_duration_ms': int(bucket.get('duration_total_ms') or 0) if bool(bucket.get('duration_known')) else None, 'avg_duration_ms': round(float(int(bucket.get('duration_total_ms') or 0)) / float(calls_with_runtime), 3) if bool(bucket.get('duration_known')) and calls_with_runtime > 0 else None, 'total_tokens': int(bucket.get('tokens_total') or 0) if bool(bucket.get('tokens_known')) else None, 'total_cost_usd': round(float(bucket.get('cost_total_usd') or 0.0), 8) if bool(bucket.get('cost_known')) else None, 'total_estimated_cost_usd': round(float(bucket.get('estimated_cost_total_usd') or 0.0), 8) if bool(bucket.get('estimated_cost_known')) else None, 'cost_coverage_ratio': round(calls_with_cost / call_count, 6) if call_count > 0 else 0.0, 'estimated_cost_coverage_ratio': round(calls_with_estimated_cost / call_count, 6) if call_count > 0 else 0.0, 'by_stage': stage_rows})
    by_source_rows.sort(key=lambda row: (-root._float_or_zero(row.get('total_estimated_cost_usd')), -root._float_or_zero(row.get('total_cost_usd')), -int(root._coerce_int(row.get('call_count')) or 0), str(row.get('source_key') or '')))
    row_inventory = {'summary': summary, 'by_source': by_source_rows, 'top_slowest_calls': top_slowest, 'top_token_calls': top_token, 'top_cost_calls': top_cost, 'top_estimated_cost_calls': top_estimated_cost}
    if telemetry_fallback is None:
        return row_inventory
    fallback_summary = telemetry_fallback.get('summary') if isinstance(telemetry_fallback.get('summary'), dict) else {}
    if root._upload_bundle_runtime_inventory_needs_fallback(row_summary=summary, fallback_summary=fallback_summary):
        return root._upload_bundle_merge_runtime_inventory_with_fallback(row_inventory=row_inventory, fallback_inventory=telemetry_fallback)
    return row_inventory

def _upload_bundle_quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if q <= 0:
        return float(values[0])
    if q >= 1:
        return float(values[-1])
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)

def _upload_bundle_build_line_role_escalation_summary(*, source_root: root.Path, run_dir_by_id: dict[str, root.Path], run_dirs: list[root.Path] | None=None) -> dict[str, root.Any]:
    file_paths: list[root.Path] = []
    for run_dir in root._upload_bundle_iter_unique_run_dirs(run_dirs=run_dirs, run_dir_by_id=run_dir_by_id):
        candidate = run_dir / 'line-role-pipeline' / 'line_role_predictions.jsonl'
        if candidate.is_file():
            file_paths.append(candidate)
    if not file_paths:
        return {'available': False, 'line_role_prediction_files': [], 'reason': 'line-role-pipeline/line_role_predictions.jsonl not found in discovered run roots'}
    decided_by_counts: root.Counter[str] = root.Counter()
    label_counts: root.Counter[str] = root.Counter()
    explicit_escalation_examples: list[dict[str, root.Any]] = []
    explicit_escalation_by_label: root.Counter[str] = root.Counter()
    explicit_escalation_by_decided_by: root.Counter[str] = root.Counter()
    explicit_escalation_reason_counts: root.Counter[str] = root.Counter()
    total_rows = 0
    for path in sorted(file_paths):
        for row in root._iter_jsonl(path):
            total_rows += 1
            label = str(row.get('label') or '').strip().upper() or 'OTHER'
            decided_by = str(row.get('decided_by') or '').strip().lower() or 'unknown'
            escalation_reasons = root._coerce_str_list(row.get('escalation_reasons'))
            label_counts[label] += 1
            decided_by_counts[decided_by] += 1
            for reason in escalation_reasons:
                explicit_escalation_reason_counts[reason] += 1
            if escalation_reasons:
                explicit_escalation_by_label[label] += 1
                explicit_escalation_by_decided_by[decided_by] += 1
                explicit_escalation_examples.append({'run_id': str(row.get('run_id') or ''), 'recipe_id': str(row.get('recipe_id') or ''), 'line_index': root._coerce_int(row.get('line_index')), 'atomic_index': root._coerce_int(row.get('atomic_index')), 'label': label, 'decided_by': decided_by, 'escalation_reasons': escalation_reasons, 'text_excerpt': root._excerpt(str(row.get('text') or ''), max_len=220)})
    explicit_escalation_examples.sort(key=lambda row: (str(row.get('recipe_id') or ''), int(root._coerce_int(row.get('line_index')) or 0)))
    relative_paths = [str(path.relative_to(source_root).as_posix()) for path in sorted(file_paths) if path.is_relative_to(source_root)]
    return {'available': True, 'line_role_prediction_files': relative_paths, 'row_count': total_rows, 'decided_by_counts': root._counter_to_sorted_dict(decided_by_counts), 'label_counts': root._counter_to_sorted_dict(label_counts), 'selective_escalation_signal': {'explicit_escalation_row_count': int(sum(explicit_escalation_by_label.values())), 'explicit_escalation_ratio': round(sum(explicit_escalation_by_label.values()) / total_rows, 6) if total_rows > 0 else 0.0, 'explicit_escalation_by_label': root._counter_to_sorted_dict(explicit_escalation_by_label), 'explicit_escalation_by_decided_by': root._counter_to_sorted_dict(explicit_escalation_by_decided_by), 'explicit_escalation_reasons': root._counter_to_sorted_dict(explicit_escalation_reason_counts)}, 'explicit_escalation_examples': explicit_escalation_examples[:24]}
