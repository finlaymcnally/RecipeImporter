from __future__ import annotations

import sys

from cookimport.bench.row_gold_lines import (
    load_row_gold_line_labels,
    resolve_row_gold_path_from_eval_report,
)


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
def _upload_bundle_collect_confusion_delta_counts(comparison_pairs: list[dict[str, root.Any]]) -> root.Counter[tuple[str, str]]:
    counter: root.Counter[tuple[str, str]] = root.Counter()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        confusion_payload = pair.get('confusion_matrix')
        if not isinstance(confusion_payload, dict):
            continue
        delta_matrix = confusion_payload.get('delta_codex_minus_baseline')
        if not isinstance(delta_matrix, dict):
            continue
        for gold_label, pred_counts in delta_matrix.items():
            if not isinstance(gold_label, str) or not isinstance(pred_counts, dict):
                continue
            for pred_label, count_raw in pred_counts.items():
                if not isinstance(pred_label, str):
                    continue
                count = root._coerce_int(count_raw)
                if count is None or count == 0:
                    continue
                counter[gold_label, pred_label] += count
    return counter

def _upload_bundle_load_run_per_label_metrics(run_dir: root.Path) -> dict[str, dict[str, root.Any]]:
    eval_report_path = run_dir / 'eval_report.json'
    if not eval_report_path.is_file():
        return {}
    try:
        eval_report = root._load_json(eval_report_path)
    except Exception:
        return {}
    per_label = eval_report.get('per_label')
    if not isinstance(per_label, dict):
        return {}
    output: dict[str, dict[str, root.Any]] = {}
    for label, row in per_label.items():
        if not isinstance(label, str) or not isinstance(row, dict):
            continue
        output[label] = {'precision': root._coerce_float(row.get('precision')), 'recall': root._coerce_float(row.get('recall')), 'f1': root._coerce_float(row.get('f1')), 'gold_total': root._coerce_int(row.get('gold_total')), 'pred_total': root._coerce_int(row.get('pred_total'))}
    return output

def _upload_bundle_resolve_manifest_path(*, run_dir: root.Path, value: root.Any) -> root.Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = root.Path(value.strip())
    resolved = candidate if candidate.is_absolute() else run_dir / candidate
    if resolved.exists() and resolved.is_file():
        return resolved
    return None

def _upload_bundle_resolve_gold_spans_path(*, run_dir: root.Path, run_manifest: dict[str, root.Any]) -> root.Path | None:
    artifacts = run_manifest.get('artifacts')
    if isinstance(artifacts, dict):
        from_artifacts = root._upload_bundle_resolve_manifest_path(run_dir=run_dir, value=artifacts.get('gold_spans_jsonl'))
        if from_artifacts is not None:
            return from_artifacts
    run_config = run_manifest.get('run_config')
    if isinstance(run_config, dict):
        from_run_config = root._upload_bundle_resolve_manifest_path(run_dir=run_dir, value=run_config.get('gold_spans'))
        if from_run_config is not None:
            return from_run_config
    eval_report_path = run_dir / 'eval_report.json'
    if eval_report_path.is_file():
        eval_report = root._upload_bundle_load_json_object(eval_report_path)
        canonical = eval_report.get('canonical') if isinstance(eval_report, dict) else None
        if isinstance(canonical, dict):
            from_eval_report = root._upload_bundle_resolve_manifest_path(run_dir=run_dir, value=canonical.get('canonical_span_labels_path'))
            if from_eval_report is not None:
                return from_eval_report
        from_eval_report = root._upload_bundle_resolve_manifest_path(run_dir=run_dir, value=eval_report.get('gold_spans_path') if isinstance(eval_report, dict) else None)
        if from_eval_report is not None:
            return from_eval_report
    return None

def _upload_bundle_load_gold_line_labels_from_eval_report(run_dir: root.Path) -> dict[int, set[str]]:
    eval_report_path = run_dir / 'eval_report.json'
    if not eval_report_path.is_file():
        return {}
    eval_report = root._upload_bundle_load_json_object(eval_report_path)
    if not isinstance(eval_report, dict):
        return {}
    row_gold_path = resolve_row_gold_path_from_eval_report(eval_report)
    if row_gold_path is None:
        return {}
    _lines, labels_by_line = load_row_gold_line_labels(
        row_gold_path,
        strict_empty_to_other=True,
    )
    output: dict[int, set[str]] = {}
    for raw_index, labels in labels_by_line.items():
        index = root._coerce_int(raw_index)
        if index is None:
            continue
        if isinstance(labels, (list, tuple, set)):
            resolved_labels = {str(label).strip() for label in labels if str(label).strip()}
        else:
            resolved_labels = {str(labels).strip()} if str(labels).strip() else set()
        if not resolved_labels:
            resolved_labels = {'OTHER'}
        output[int(index)] = resolved_labels
    return output

def _upload_bundle_normalize_match_text(value: root.Any) -> str:
    return ' '.join(str(value or '').strip().lower().split())

def _upload_bundle_extract_text_values(value: root.Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                rows.append(text)
            continue
        if not isinstance(item, dict):
            continue
        for key in ('text', 'name', 'value', 'raw', 'label'):
            text = str(item.get(key) or '').strip()
            if text:
                rows.append(text)
                break
    return rows

def _upload_bundle_blocks_from_evidence_rows(value: root.Any) -> tuple[dict[int, str], list[int]]:
    if not isinstance(value, list):
        return ({}, [])
    blocks_by_index: dict[int, str] = {}
    ordered_indices: list[int] = []
    for row in value:
        index: int | None = None
        text = ''
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            index = root._coerce_int(row[0])
            text = str(row[1] or '')
        elif isinstance(row, dict):
            index = root._coerce_int(row.get('index'))
            text = str(row.get('text') or '')
        if index is None or index < 0:
            continue
        blocks_by_index[int(index)] = text
        ordered_indices.append(int(index))
    return (blocks_by_index, sorted(set(ordered_indices)))

def _upload_bundle_collect_text_matches(*, targets: list[str], blocks_by_index: dict[int, str]) -> set[int]:
    normalized_targets = [root._upload_bundle_normalize_match_text(value) for value in targets if root._upload_bundle_normalize_match_text(value)]
    if not normalized_targets:
        return set()
    matched: set[int] = set()
    for index, block_text in blocks_by_index.items():
        normalized_block = root._upload_bundle_normalize_match_text(block_text)
        if not normalized_block:
            continue
        for target in normalized_targets:
            if len(target) < 4:
                continue
            if target in normalized_block or (len(normalized_block) >= 20 and normalized_block in target):
                matched.add(int(index))
                break
    return matched

def _upload_bundle_pick_title_block(*, title: str, candidate_indices: list[int], blocks_by_index: dict[int, str]) -> int | None:
    normalized_title = root._upload_bundle_normalize_match_text(title)
    if not normalized_title:
        return candidate_indices[0] if candidate_indices else None
    for index in candidate_indices:
        normalized_block = root._upload_bundle_normalize_match_text(blocks_by_index.get(index))
        if not normalized_block:
            continue
        if normalized_title in normalized_block or normalized_block in normalized_title:
            return int(index)
    return candidate_indices[0] if candidate_indices else None

def _upload_bundle_project_correction_recipe_labels(*, correction_input: dict[str, root.Any], correction_output: dict[str, root.Any]) -> dict[int, str]:
    blocks_by_index, ordered_indices = root._upload_bundle_blocks_from_evidence_rows(correction_input.get('evidence_rows'))
    if not blocks_by_index:
        return {}
    canonical_recipe = correction_output.get('canonical_recipe')
    if not isinstance(canonical_recipe, dict):
        canonical_recipe = {}
    ingredient_indices = root._upload_bundle_collect_text_matches(targets=root._upload_bundle_extract_text_values(canonical_recipe.get('ingredients')), blocks_by_index=blocks_by_index)
    instruction_indices = root._upload_bundle_collect_text_matches(targets=root._upload_bundle_extract_text_values(canonical_recipe.get('steps')), blocks_by_index=blocks_by_index)
    notes_indices = root._upload_bundle_collect_text_matches(targets=[str(canonical_recipe.get('description') or '')], blocks_by_index=blocks_by_index)
    labels_by_index: dict[int, str] = {}
    for index in ingredient_indices:
        labels_by_index[int(index)] = 'INGREDIENT_LINE'
    for index in instruction_indices:
        labels_by_index[int(index)] = 'INSTRUCTION_LINE'
    for index in notes_indices:
        labels_by_index.setdefault(int(index), 'RECIPE_NOTES')
    title_index = root._upload_bundle_pick_title_block(title=str(canonical_recipe.get('title') or ''), candidate_indices=ordered_indices, blocks_by_index=blocks_by_index)
    if title_index is not None:
        labels_by_index[int(title_index)] = 'RECIPE_TITLE'
    yield_values = [str(canonical_recipe.get('recipe_yield') or '')]
    normalized_yields = [root._upload_bundle_normalize_match_text(value) for value in yield_values if root._upload_bundle_normalize_match_text(value)]
    time_values: list[str] = []
    normalized_times = [root._upload_bundle_normalize_match_text(value) for value in time_values if root._upload_bundle_normalize_match_text(value)]
    for index in ordered_indices:
        block_text = blocks_by_index.get(index, '')
        normalized_block = root._upload_bundle_normalize_match_text(block_text)
        if not normalized_block:
            continue
        if root._UPLOAD_BUNDLE_YIELD_LINE_RE.search(block_text) and (not normalized_yields or any((value in normalized_block for value in normalized_yields))):
            labels_by_index[index] = 'YIELD_LINE'
            continue
        if root._UPLOAD_BUNDLE_TIME_LINE_RE.search(block_text) or root._UPLOAD_BUNDLE_TIME_VALUE_RE.search(block_text):
            if not normalized_times or any((value in normalized_block for value in normalized_times)):
                labels_by_index.setdefault(index, 'TIME_LINE')
    return labels_by_index

def _upload_bundle_project_final_recipe_labels(*, correction_input: dict[str, root.Any], correction_output: dict[str, root.Any] | None, final_output: dict[str, root.Any] | None) -> dict[int, str]:
    blocks_by_index, ordered_indices = root._upload_bundle_blocks_from_evidence_rows(correction_input.get('evidence_rows'))
    if not blocks_by_index:
        return {}
    labels_by_index: dict[int, str] = {}
    title_value = ''
    ingredient_targets: list[str] = []
    instruction_targets: list[str] = []
    if isinstance(final_output, dict):
        draft_payload = final_output.get('draft_v1')
        if isinstance(draft_payload, dict):
            recipe_payload = draft_payload.get('recipe')
            if isinstance(recipe_payload, dict):
                title_value = str(recipe_payload.get('title') or '')
            steps_payload = draft_payload.get('steps')
            if isinstance(steps_payload, list):
                for step_row in steps_payload:
                    if not isinstance(step_row, dict):
                        continue
                    instruction_text = str(step_row.get('instruction') or '').strip()
                    if instruction_text:
                        instruction_targets.append(instruction_text)
                    ingredient_lines = step_row.get('ingredient_lines')
                    ingredient_targets.extend(root._upload_bundle_extract_text_values(ingredient_lines))
    if not title_value and isinstance(correction_output, dict):
        canonical_recipe = correction_output.get('canonical_recipe')
        if isinstance(canonical_recipe, dict):
            title_value = str(canonical_recipe.get('title') or '')
        if not ingredient_targets:
            ingredient_targets = root._upload_bundle_extract_text_values(canonical_recipe.get('ingredients') if isinstance(canonical_recipe, dict) else None)
        if not instruction_targets:
            instruction_targets = root._upload_bundle_extract_text_values(canonical_recipe.get('steps') if isinstance(canonical_recipe, dict) else None)
    for index in root._upload_bundle_collect_text_matches(targets=ingredient_targets, blocks_by_index=blocks_by_index):
        labels_by_index[int(index)] = 'INGREDIENT_LINE'
    for index in root._upload_bundle_collect_text_matches(targets=instruction_targets, blocks_by_index=blocks_by_index):
        labels_by_index[int(index)] = 'INSTRUCTION_LINE'
    title_index = root._upload_bundle_pick_title_block(title=title_value, candidate_indices=ordered_indices, blocks_by_index=blocks_by_index)
    if title_index is not None:
        labels_by_index[int(title_index)] = 'RECIPE_TITLE'
    return labels_by_index

def _upload_bundle_collect_stage_reports_for_run(*, run_dir: root.Path, gold_cache: dict[root.Path, dict[int, set[str]]]) -> dict[str, dict[str, root.Any]]:
    run_manifest_path = run_dir / 'run_manifest.json'
    if not run_manifest_path.is_file():
        return {}
    run_manifest = root._upload_bundle_load_json_object(run_manifest_path)
    if not run_manifest:
        return {}
    pred_run_dir = root._resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return {}
    gold_spans_path = root._upload_bundle_resolve_gold_spans_path(run_dir=run_dir, run_manifest=run_manifest)
    if gold_spans_path is None:
        return {}
    gold_labels = gold_cache.get(gold_spans_path)
    if gold_labels is None:
        try:
            gold_labels = root.load_gold_block_labels(gold_spans_path, require_exhaustive=False)
        except Exception:
            gold_labels = root._upload_bundle_load_gold_line_labels_from_eval_report(run_dir)
            if not gold_labels:
                return {}
        gold_cache[gold_spans_path] = gold_labels
    if not gold_labels:
        return {}
    gold_indices = sorted((int(index) for index in gold_labels.keys()))
    default_prediction = {index: 'OTHER' for index in gold_indices}
    raw_llm_dir = pred_run_dir / 'raw' / 'llm'
    llm_run_dirs = sorted((path for path in raw_llm_dir.glob('*') if path.is_dir()))
    if not llm_run_dirs and raw_llm_dir.is_dir():
        llm_run_dirs = [raw_llm_dir]
    if not llm_run_dirs:
        return {}
    correction_inputs: dict[str, dict[str, root.Any]] = {}
    correction_outputs: dict[str, dict[str, root.Any]] = {}
    final_outputs: dict[str, dict[str, root.Any]] = {}
    for llm_run_dir in llm_run_dirs:
        correction_in_dir = llm_run_dir / root.stage_artifact_stem('recipe_refine') / 'in'
        correction_out_dir = llm_run_dir / root.stage_artifact_stem('recipe_refine') / 'out'
        final_out_dir = llm_run_dir / root.stage_artifact_stem('recipe_build_final') / 'out'
        for path in sorted(correction_in_dir.glob('*.json')):
            payload = root._upload_bundle_load_json_object(path)
            recipe_id = str(payload.get('recipe_id') or '').strip()
            if recipe_id:
                correction_inputs[recipe_id] = payload
        for path in sorted(correction_out_dir.glob('*.json')):
            payload = root._upload_bundle_load_json_object(path)
            recipe_id = str(payload.get('recipe_id') or '').strip()
            if recipe_id:
                correction_outputs[recipe_id] = payload
        for path in sorted(final_out_dir.glob('*.json')):
            payload = root._upload_bundle_load_json_object(path)
            recipe_id = str(payload.get('recipe_id') or '').strip()
            if recipe_id:
                final_outputs[recipe_id] = payload
    reports: dict[str, dict[str, root.Any]] = {}
    correction_prediction = dict(default_prediction)
    correction_label_hits = 0
    for recipe_id, correction_output in correction_outputs.items():
        correction_input = correction_inputs.get(recipe_id)
        if not isinstance(correction_input, dict):
            continue
        projected_labels = root._upload_bundle_project_correction_recipe_labels(correction_input=correction_input, correction_output=correction_output)
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in correction_prediction:
                continue
            correction_prediction[index] = str(label)
            if str(label) != 'OTHER':
                correction_label_hits += 1
    if correction_label_hits > 0:
        try:
            reports['recipe_refine'] = root.compute_block_metrics(gold_labels, correction_prediction)
        except Exception:
            reports['recipe_refine'] = {}
    final_prediction = dict(default_prediction)
    final_label_hits = 0
    recipe_ids = sorted(set(correction_inputs.keys()) | set(correction_outputs.keys()) | set(final_outputs.keys()))
    for recipe_id in recipe_ids:
        correction_input = correction_inputs.get(recipe_id)
        if not isinstance(correction_input, dict):
            continue
        projected_labels = root._upload_bundle_project_final_recipe_labels(correction_input=correction_input, correction_output=correction_outputs.get(recipe_id), final_output=final_outputs.get(recipe_id))
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in final_prediction:
                continue
            final_prediction[index] = str(label)
            if str(label) != 'OTHER':
                final_label_hits += 1
    if final_label_hits > 0:
        try:
            reports['recipe_build_final'] = root.compute_block_metrics(gold_labels, final_prediction)
        except Exception:
            reports['recipe_build_final'] = {}
    return reports

def _upload_bundle_collect_stage_per_label_metrics(*, comparison_pairs: list[dict[str, root.Any]], run_dir_by_id: dict[str, root.Path]) -> dict[str, root.Any]:
    codex_run_ids: set[str] = set()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get('codex_run')
        if not isinstance(codex_run, dict):
            continue
        run_id = str(codex_run.get('run_id') or '').strip()
        if run_id:
            codex_run_ids.add(run_id)
    gold_cache: dict[root.Path, dict[int, set[str]]] = {}
    reports_by_run: dict[str, dict[str, dict[str, root.Any]]] = {}
    for run_id in sorted(codex_run_ids):
        run_dir = run_dir_by_id.get(run_id)
        if run_dir is None:
            reports_by_run[run_id] = {}
            continue
        reports_by_run[run_id] = root._upload_bundle_collect_stage_reports_for_run(run_dir=run_dir, gold_cache=gold_cache)
    output: dict[str, root.Any] = {}
    for stage_key in ('recipe_refine', 'recipe_build_final'):
        labels_agg: dict[str, dict[str, root.Any]] = {}
        runs_scored = 0
        for run_id in sorted(codex_run_ids):
            report = (reports_by_run.get(run_id) or {}).get(stage_key)
            if not isinstance(report, dict):
                continue
            per_label = report.get('per_label')
            if not isinstance(per_label, dict):
                continue
            runs_scored += 1
            for label, row in per_label.items():
                if not isinstance(label, str) or not isinstance(row, dict):
                    continue
                agg_row = labels_agg.setdefault(label, {'label': label, '_precision': [], '_recall': [], '_f1': [], 'gold_total_sum': 0, 'pred_total_sum': 0})
                agg_row['_precision'].append(root._coerce_float(row.get('precision')))
                agg_row['_recall'].append(root._coerce_float(row.get('recall')))
                agg_row['_f1'].append(root._coerce_float(row.get('f1')))
                agg_row['gold_total_sum'] = int(agg_row['gold_total_sum']) + int(root._coerce_int(row.get('gold_total')) or 0)
                agg_row['pred_total_sum'] = int(agg_row['pred_total_sum']) + int(root._coerce_int(row.get('pred_total')) or 0)
        labels_rows: dict[str, dict[str, root.Any]] = {}
        for label, row in labels_agg.items():
            labels_rows[label] = {'label': label, 'precision_avg': root._average_float(row['_precision']), 'recall_avg': root._average_float(row['_recall']), 'f1_avg': root._average_float(row['_f1']), 'gold_total_sum': int(row['gold_total_sum']), 'pred_total_sum': int(row['pred_total_sum']), 'runs_scored': int(runs_scored)}
        output[stage_key] = {'available': runs_scored > 0, 'runs_scored': int(runs_scored), 'labels': labels_rows, 'unavailable_reason': '' if runs_scored > 0 else f'{stage_key} stage outputs could not be projected/scored from discovered prediction-run codex artifacts'}
    return output

def _upload_bundle_build_per_label_metrics(*, comparison_pairs: list[dict[str, root.Any]], run_dir_by_id: dict[str, root.Path]) -> list[dict[str, root.Any]]:
    confusion_counter = root._upload_bundle_collect_confusion_delta_counts(comparison_pairs)
    per_run_cache: dict[str, dict[str, dict[str, root.Any]]] = {}

    def _metrics_for_run(run_id: str) -> dict[str, dict[str, root.Any]]:
        if run_id in per_run_cache:
            return per_run_cache[run_id]
        run_dir = run_dir_by_id.get(run_id)
        if run_dir is None:
            per_run_cache[run_id] = {}
            return {}
        metrics = root._upload_bundle_load_run_per_label_metrics(run_dir)
        per_run_cache[run_id] = metrics
        return metrics
    aggregated: dict[str, dict[str, root.Any]] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get('codex_run')
        baseline_run = pair.get('baseline_run')
        codex_run_id = str(codex_run.get('run_id') or '') if isinstance(codex_run, dict) else ''
        baseline_run_id = str(baseline_run.get('run_id') or '') if isinstance(baseline_run, dict) else ''
        codex_metrics = _metrics_for_run(codex_run_id)
        baseline_metrics = _metrics_for_run(baseline_run_id)
        labels = sorted(set(codex_metrics.keys()) | set(baseline_metrics.keys()))
        for label in labels:
            row = aggregated.setdefault(label, {'label': label, 'pair_count_with_metrics': 0, '_codex_precision': [], '_baseline_precision': [], '_delta_precision': [], '_codex_recall': [], '_baseline_recall': [], '_delta_recall': [], '_codex_f1': [], '_baseline_f1': [], '_delta_f1': [], 'gold_total_sum': 0, 'pred_total_sum': 0})
            codex_row = codex_metrics.get(label, {})
            baseline_row = baseline_metrics.get(label, {})
            codex_precision = root._coerce_float(codex_row.get('precision'))
            baseline_precision = root._coerce_float(baseline_row.get('precision'))
            codex_recall = root._coerce_float(codex_row.get('recall'))
            baseline_recall = root._coerce_float(baseline_row.get('recall'))
            codex_f1 = root._coerce_float(codex_row.get('f1'))
            baseline_f1 = root._coerce_float(baseline_row.get('f1'))
            if codex_precision is not None or baseline_precision is not None or codex_recall is not None or (baseline_recall is not None) or (codex_f1 is not None) or (baseline_f1 is not None):
                row['pair_count_with_metrics'] = int(row['pair_count_with_metrics']) + 1
            row['_codex_precision'].append(codex_precision)
            row['_baseline_precision'].append(baseline_precision)
            row['_delta_precision'].append(root._delta(codex_precision, baseline_precision))
            row['_codex_recall'].append(codex_recall)
            row['_baseline_recall'].append(baseline_recall)
            row['_delta_recall'].append(root._delta(codex_recall, baseline_recall))
            row['_codex_f1'].append(codex_f1)
            row['_baseline_f1'].append(baseline_f1)
            row['_delta_f1'].append(root._delta(codex_f1, baseline_f1))
            row['gold_total_sum'] = int(row['gold_total_sum']) + int(root._coerce_int(codex_row.get('gold_total')) or root._coerce_int(baseline_row.get('gold_total')) or 0)
            row['pred_total_sum'] = int(row['pred_total_sum']) + int(root._coerce_int(codex_row.get('pred_total')) or root._coerce_int(baseline_row.get('pred_total')) or 0)
    output_rows: list[dict[str, root.Any]] = []
    labels_all = sorted(set(aggregated.keys()))
    for label in labels_all:
        row = aggregated[label]
        outbound = [{'pred_label': pred_label, 'delta_count': count} for (gold_label, pred_label), count in confusion_counter.items() if gold_label == label]
        inbound = [{'gold_label': gold_label, 'delta_count': count} for (gold_label, pred_label), count in confusion_counter.items() if pred_label == label]
        outbound.sort(key=lambda item: (-abs(int(item['delta_count'])), str(item['pred_label'])))
        inbound.sort(key=lambda item: (-abs(int(item['delta_count'])), str(item['gold_label'])))
        output_rows.append({'label': label, 'pair_count_with_metrics': int(row['pair_count_with_metrics']), 'gold_total_sum': int(row['gold_total_sum']), 'pred_total_sum': int(row['pred_total_sum']), 'codex_precision_avg': root._average_float(row['_codex_precision']), 'baseline_precision_avg': root._average_float(row['_baseline_precision']), 'delta_precision_avg': root._average_float(row['_delta_precision']), 'codex_recall_avg': root._average_float(row['_codex_recall']), 'baseline_recall_avg': root._average_float(row['_baseline_recall']), 'delta_recall_avg': root._average_float(row['_delta_recall']), 'codex_f1_avg': root._average_float(row['_codex_f1']), 'baseline_f1_avg': root._average_float(row['_baseline_f1']), 'delta_f1_avg': root._average_float(row['_delta_f1']), 'confusion_delta_outbound_total': sum((int(item['delta_count']) for item in outbound)), 'confusion_delta_inbound_total': sum((int(item['delta_count']) for item in inbound)), 'top_confusion_outbound': outbound[:5], 'top_confusion_inbound': inbound[:5]})
    output_rows.sort(key=lambda row: (-abs(root._float_or_zero(row.get('delta_f1_avg'))), -abs(root._float_or_zero(row.get('delta_recall_avg'))), str(row.get('label') or '')))
    return output_rows
