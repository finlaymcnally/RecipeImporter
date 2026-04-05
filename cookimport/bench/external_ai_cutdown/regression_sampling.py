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
def _upload_bundle_safe_run_subdir(value: str) -> str:
    rendered = root.re.sub('[^0-9A-Za-z._-]+', '_', str(value or '').strip())
    return rendered or 'run'

def _upload_bundle_derive_run_diagnostic_statuses(*, run_dir: root.Path, run_id: str, output_subdir: str, append_virtual_payload_row: root.Any) -> dict[str, str]:
    statuses: dict[str, str] = {}
    if not run_dir.is_dir():
        return statuses
    run_manifest_path = run_dir / 'run_manifest.json'
    if not run_manifest_path.is_file():
        return statuses
    try:
        run_manifest = root._load_json(run_manifest_path)
    except Exception:
        return statuses
    run_config = run_manifest.get('run_config')
    run_config = run_config if isinstance(run_config, dict) else {}
    llm_recipe_pipeline = str(run_config.get('llm_recipe_pipeline') or '').strip().lower()
    codex_enabled = llm_recipe_pipeline not in {'', 'off', 'none'}
    full_prompt_rows: list[dict[str, root.Any]] = []
    recipe_spans: list[dict[str, root.Any]] = []
    full_prompt_log_path = root._resolve_full_prompt_log_path(run_dir, run_manifest)
    if full_prompt_log_path is not None and full_prompt_log_path.is_file():
        full_prompt_rows = root._iter_jsonl(full_prompt_log_path)
        if full_prompt_rows:
            recipe_spans = root._build_recipe_spans_from_full_prompt_rows(full_prompt_rows)
    derived_dir = f'{root.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/runs/{root._upload_bundle_safe_run_subdir(output_subdir or run_id)}'
    wrong_context_name = root.WRONG_LABEL_FULL_CONTEXT_FILE_NAME.replace('.gz', '')
    preprocess_name = root.PREPROCESS_TRACE_FAILURES_FILE_NAME.replace('.gz', '')
    if codex_enabled:
        if full_prompt_log_path is not None and full_prompt_log_path.is_file():
            try:
                prompt_warning_aggregate = root._summarize_prompt_warning_aggregate(full_prompt_log_path)
                append_virtual_payload_row(path=f'{derived_dir}/{root.PROMPT_WARNING_AGGREGATE_FILE_NAME}', content_type='json', content_json=prompt_warning_aggregate)
                statuses[root.PROMPT_WARNING_AGGREGATE_FILE_NAME] = 'written'
            except Exception:
                statuses[root.PROMPT_WARNING_AGGREGATE_FILE_NAME] = 'derivation_error'
            try:
                line_view = root._build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)
                projection_trace = root._build_projection_trace(line_view=line_view, full_prompt_rows=full_prompt_rows)
                projection_trace['recipe_span_count'] = len(recipe_spans)
                projection_trace['recipe_spans'] = recipe_spans
                append_virtual_payload_row(path=f'{derived_dir}/{root.PROJECTION_TRACE_FILE_NAME}', content_type='json', content_json=projection_trace)
                statuses[root.PROJECTION_TRACE_FILE_NAME] = 'written'
            except Exception:
                statuses[root.PROJECTION_TRACE_FILE_NAME] = 'derivation_error'
        else:
            statuses[root.PROMPT_WARNING_AGGREGATE_FILE_NAME] = 'missing_full_prompt_log'
            statuses[root.PROJECTION_TRACE_FILE_NAME] = 'missing_full_prompt_log'
    wrong_label_total_rows = root._jsonl_row_count(run_dir / 'wrong_label_lines.jsonl')
    if wrong_label_total_rows <= 0:
        statuses[root.WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = 'not_applicable'
        statuses[root.PREPROCESS_TRACE_FAILURES_FILE_NAME] = 'not_applicable'
        return statuses
    try:
        wrong_label_rows = root._build_wrong_label_full_context_rows(run_dir=run_dir, recipe_spans=recipe_spans, excerpt_limit=root.DEFAULT_EXCERPT_LIMIT)
    except Exception:
        wrong_label_rows = []
    if wrong_label_rows:
        append_virtual_payload_row(path=f'{derived_dir}/{wrong_context_name}', content_type='jsonl', content_jsonl_rows=wrong_label_rows)
        statuses[root.WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = 'written'
    else:
        statuses[root.WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = 'not_applicable'
    if not codex_enabled:
        statuses[root.PREPROCESS_TRACE_FAILURES_FILE_NAME] = 'not_applicable'
        return statuses
    try:
        preprocess_rows, preprocess_status = root._build_preprocess_trace_failure_rows(run_dir=run_dir, run_manifest=run_manifest, full_prompt_rows=full_prompt_rows, excerpt_limit=root.DEFAULT_EXCERPT_LIMIT)
    except Exception:
        preprocess_rows = []
        preprocess_status = 'derivation_error'
    if preprocess_status == 'ready' and preprocess_rows:
        append_virtual_payload_row(path=f'{derived_dir}/{preprocess_name}', content_type='jsonl', content_jsonl_rows=preprocess_rows)
        statuses[root.PREPROCESS_TRACE_FAILURES_FILE_NAME] = 'written'
    else:
        statuses[root.PREPROCESS_TRACE_FAILURES_FILE_NAME] = preprocess_status if preprocess_status != 'ready' else 'not_applicable'
    return statuses

def _upload_bundle_matches_recipe_target(recipe_id: str, target: str) -> bool:
    recipe_text = recipe_id.strip().lower()
    target_text = target.strip().lower()
    if not recipe_text or not target_text:
        return False
    if recipe_text == target_text:
        return True
    if recipe_text.endswith(f':{target_text}'):
        return True
    return recipe_text.endswith(target_text)

def _upload_bundle_regression_casebook_signal_key(row: dict[str, root.Any]) -> tuple[int, int, int, int, str]:
    return (-int(root._coerce_int(row.get('outside_span_wrong_line_count')) or 0), -int(root._coerce_int(row.get('changed_lines_codex_vs_baseline')) or 0), -int(root._coerce_int(row.get('recipe_error_count')) or 0), -int(root._coerce_int(row.get('recipe_warning_count')) or 0), str(row.get('recipe_id') or ''))

def _upload_bundle_build_regression_casebook(*, recipe_triage_rows: list[dict[str, root.Any]], changed_line_rows: list[dict[str, root.Any]]) -> dict[str, root.Any]:
    requested_targets = ['c6', 'c9', 'c12', 'c3']
    selected_rows: list[dict[str, root.Any]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    sorted_worst = sorted(recipe_triage_rows, key=lambda row: (root._float_or_zero(row.get('delta_codex_minus_baseline')), -int(root._coerce_int(row.get('changed_lines_codex_vs_baseline')) or 0), str(row.get('recipe_id') or '')))
    negative_delta_rows = [row for row in sorted_worst if (root._coerce_float(row.get('delta_codex_minus_baseline')) or 0.0) < 0.0]
    signal_rows = sorted(recipe_triage_rows, key=root._upload_bundle_regression_casebook_signal_key)
    for target in requested_targets:
        for row in sorted_worst:
            recipe_id = str(row.get('recipe_id') or '')
            if not root._upload_bundle_matches_recipe_target(recipe_id, target):
                continue
            key = root._recipe_row_key(row)
            if key in selected_keys:
                continue
            row_copy = dict(row)
            row_copy['selection_reason'] = f'targeted_regression_id:{target}'
            selected_rows.append(row_copy)
            selected_keys.add(key)
            break
    fill_source = negative_delta_rows
    fill_reason = 'top_negative_delta_fill'
    suggested_target_source = 'top_negative_delta_recipes'
    if not fill_source:
        fill_source = signal_rows
        fill_reason = 'top_signal_fill'
        suggested_target_source = 'top_signal_recipes'
    for row in fill_source:
        key = root._recipe_row_key(row)
        if key in selected_keys:
            continue
        row_copy = dict(row)
        row_copy['selection_reason'] = fill_reason
        selected_rows.append(row_copy)
        selected_keys.add(key)
        if len(selected_rows) >= 10:
            break
    if len(selected_rows) < 10 and fill_reason != 'top_signal_fill':
        for row in signal_rows:
            key = root._recipe_row_key(row)
            if key in selected_keys:
                continue
            row_copy = dict(row)
            row_copy['selection_reason'] = 'top_signal_fill'
            selected_rows.append(row_copy)
            selected_keys.add(key)
            if len(selected_rows) >= 10:
                break
    selected_rows = selected_rows[:10]
    packets = root._build_selected_recipe_packets(selected_recipe_rows=selected_rows, changed_line_rows=changed_line_rows, default_recipe_stages=root._upload_bundle_recipe_stages_for_row(recipe_pipeline_id='codex-recipe-shard-v1', correction_call_id=None))
    found_targets = [str(row.get('recipe_id') or '') for row in selected_rows if any((root._upload_bundle_matches_recipe_target(str(row.get('recipe_id') or ''), target) for target in requested_targets))]
    missing_targets = [target for target in requested_targets if not any((root._upload_bundle_matches_recipe_target(recipe_id, target) for recipe_id in found_targets))]
    suggested_targets: list[str] = []
    suggested_rows = fill_source if fill_reason == 'top_signal_fill' else negative_delta_rows
    if not suggested_rows:
        suggested_rows = signal_rows
        suggested_target_source = 'top_signal_recipes'
    for row in suggested_rows:
        recipe_id = str(row.get('recipe_id') or '').strip()
        if not recipe_id or recipe_id in suggested_targets:
            continue
        suggested_targets.append(recipe_id)
        if len(suggested_targets) >= 4:
            break
    return {'requested_targets': requested_targets, 'found_targets': found_targets, 'missing_targets': missing_targets, 'target_request_status': 'all_found' if requested_targets and (not missing_targets) else 'partial' if found_targets else 'none_found', 'suggested_targets': suggested_targets, 'suggested_target_source': suggested_target_source, 'packet_count': len(packets), 'packets': packets}

def _upload_bundle_changed_line_bucket(row: dict[str, root.Any]) -> str:
    gold_label = str(row.get('gold_label') or '')
    baseline_label = str(row.get('vanilla_pred') or row.get('baseline_pred') or '')
    codex_label = str(row.get('codex_pred') or '')
    baseline_correct = bool(gold_label) and baseline_label == gold_label
    codex_correct = bool(gold_label) and codex_label == gold_label
    if baseline_correct and (not codex_correct):
        return 'new_error'
    if not baseline_correct and codex_correct:
        return 'fixed_error'
    if not baseline_correct and (not codex_correct):
        return 'both_wrong_shift'
    return 'other_changed'

def _upload_bundle_build_changed_line_stratified_sample(changed_line_rows: list[dict[str, root.Any]], *, per_bucket_limit: int=40) -> dict[str, root.Any]:
    grouped: dict[str, list[dict[str, root.Any]]] = root.defaultdict(list)
    confusion_counts: root.Counter[str] = root.Counter()
    for row in changed_line_rows:
        bucket = root._upload_bundle_changed_line_bucket(row)
        grouped[bucket].append(row)
        gold_label = str(row.get('gold_label') or '')
        codex_label = str(row.get('codex_pred') or '')
        confusion_counts[f'{gold_label}->{codex_label}'] += 1
    samples: dict[str, list[dict[str, root.Any]]] = {}
    counts_by_bucket: dict[str, int] = {}
    for bucket_name in sorted(grouped):
        rows = sorted(grouped[bucket_name], key=lambda row: (str(row.get('recipe_id') or ''), int(root._coerce_int(row.get('line_index')) or 0), str(row.get('gold_label') or '')))
        counts_by_bucket[bucket_name] = len(rows)
        sampled_rows: list[dict[str, root.Any]] = []
        for row in rows[:max(per_bucket_limit, 0)]:
            sampled_rows.append({'source_key': str(row.get('source_key') or ''), 'codex_run_id': str(row.get('codex_run_id') or ''), 'baseline_run_id': str(row.get('baseline_run_id') or ''), 'recipe_id': str(row.get('recipe_id') or ''), 'line_index': int(root._coerce_int(row.get('line_index')) or 0), 'span_region': str(row.get('span_region') or ''), 'gold_label': str(row.get('gold_label') or ''), 'baseline_pred': str(row.get('vanilla_pred') or row.get('baseline_pred') or ''), 'codex_pred': str(row.get('codex_pred') or ''), 'current_line': str(row.get('current_line') or ''), 'previous_line': str(row.get('previous_line') or ''), 'next_line': str(row.get('next_line') or '')})
        samples[bucket_name] = sampled_rows
    return {'total_rows': len(changed_line_rows), 'counts_by_bucket': counts_by_bucket, 'top_error_buckets': [{'bucket': bucket, 'count': count} for bucket, count in confusion_counts.most_common(20)], 'samples_by_bucket': samples}

def _upload_bundle_sort_recipe_triage_rows(recipe_triage_rows: list[dict[str, root.Any]]) -> list[dict[str, root.Any]]:

    def _sort_key(row: dict[str, root.Any]) -> tuple[root.Any, ...]:
        changed_lines = int(root._coerce_int(row.get('changed_lines_codex_vs_baseline')) or 0)
        outside_span_wrong_line_count = int(root._coerce_int(row.get('outside_span_wrong_line_count')) or 0)
        delta_abs = abs(root._float_or_zero(row.get('delta_codex_minus_baseline')))
        warning_count = int(root._coerce_int(row.get('correction_warning_count')) or 0) + int(root._coerce_int(row.get('recipe_warning_count')) or 0) + int(root._coerce_int(row.get('final_recipe_warning_count')) or 0)
        line_total = int(root._coerce_int(row.get('line_total')) or 0)
        empty_mapping_only = bool(row.get('final_recipe_empty_mapping') or row.get('correction_empty_mapping')) and changed_lines <= 0 and (outside_span_wrong_line_count <= 0) and (delta_abs <= 0.0) and (warning_count <= 0)
        has_turn1_signal = changed_lines > 0 or outside_span_wrong_line_count > 0 or delta_abs > 0.0 or (warning_count > 0)
        return (-int(has_turn1_signal), int(empty_mapping_only), -changed_lines, -outside_span_wrong_line_count, -delta_abs, -warning_count, -line_total, str(row.get('recipe_id') or ''), str(row.get('source_key') or ''), str(row.get('codex_run_id') or ''))
    return sorted([row for row in recipe_triage_rows if isinstance(row, dict)], key=_sort_key)

def _upload_bundle_build_triage_packet_rows(recipe_triage_rows: list[dict[str, root.Any]]) -> list[dict[str, root.Any]]:
    rows: list[dict[str, root.Any]] = []
    for rank, row in enumerate(root._upload_bundle_sort_recipe_triage_rows(recipe_triage_rows), start=1):
        rows.append({'schema_version': root.UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION, 'triage_rank': rank, 'source_key': str(row.get('source_key') or ''), 'codex_run_id': str(row.get('codex_run_id') or row.get('run_id') or ''), 'baseline_run_id': str(row.get('baseline_run_id') or ''), 'recipe_id': str(row.get('recipe_id') or ''), 'short_title': str(row.get('short_title') or ''), 'line_total': int(root._coerce_int(row.get('line_total')) or 0), 'changed_lines_codex_vs_baseline': int(root._coerce_int(row.get('changed_lines_codex_vs_baseline')) or 0), 'baseline_accuracy': root._coerce_float(row.get('baseline_accuracy')), 'codex_accuracy': root._coerce_float(row.get('codex_accuracy')), 'delta_codex_minus_baseline': root._coerce_float(row.get('delta_codex_minus_baseline')), 'build_intermediate_status': str(row.get('build_intermediate_status') or ''), 'correction_status': str(row.get('correction_status') or ''), 'build_final_status': str(row.get('build_final_status') or ''), 'correction_warning_count': int(root._coerce_int(row.get('correction_warning_count')) or 0), 'final_recipe_warning_count': int(root._coerce_int(row.get('final_recipe_warning_count')) or 0), 'final_recipe_empty_mapping': bool(row.get('final_recipe_empty_mapping')), 'build_final_execution_mode': str(row.get('build_final_execution_mode') or ''), 'build_final_routing_reason': str(row.get('build_final_routing_reason') or ''), 'build_final_fallback_reason': str(row.get('build_final_fallback_reason') or ''), 'transport_mismatch': bool(row.get('transport_mismatch'))})
    return rows

def _upload_bundle_triage_packet_row_has_signal(row: dict[str, root.Any]) -> bool:
    return bool(int(root._coerce_int(row.get('changed_lines_codex_vs_baseline')) or 0) > 0 or int(root._coerce_int(row.get('outside_span_wrong_line_count')) or 0) > 0 or root._coerce_float(row.get('delta_codex_minus_baseline')) is not None or (int(root._coerce_int(row.get('line_total')) or 0) > 0) or (int(root._coerce_int(row.get('correction_warning_count')) or 0) > 0) or (int(root._coerce_int(row.get('final_recipe_warning_count')) or 0) > 0))

def _upload_bundle_select_triage_packet_sample_rows(triage_packet_rows: list[dict[str, root.Any]], *, pair_count: int=0, active_recipe_span_breakout: dict[str, root.Any] | None=None, limit: int=40) -> tuple[list[dict[str, root.Any]], str]:
    signal_rows = [row for row in triage_packet_rows if isinstance(row, dict) and root._upload_bundle_triage_packet_row_has_signal(row)]
    if signal_rows:
        return (signal_rows[:limit], '')
    active_recipe_span_breakout = active_recipe_span_breakout if isinstance(active_recipe_span_breakout, dict) else {}
    if int(pair_count) <= 0:
        recipe_span_count = int(root._coerce_int(active_recipe_span_breakout.get('recipe_span_count')) or 0)
        if recipe_span_count > 0:
            return ([], 'No comparison pair was available, so recipe-local triage rows were not built. Recipe spans were discovered in the single run, so use `analysis.active_recipe_span_breakout`, `analysis.recipe_pipeline_context`, and `analysis.stage_observability_summary` first.')
        return ([], 'No comparison pair was available, so recipe-local triage rows were not built. Use `analysis.recipe_pipeline_context`, `analysis.stage_observability_summary`, and per-run summaries first.')
    return ([], 'No triage rows had recipe-local signal. This usually means active recipe spans were not discovered, so use `analysis.turn1_summary`, `analysis.active_recipe_span_breakout`, `analysis.top_confusion_deltas`, and `analysis.changed_lines_stratified_sample` first.')
