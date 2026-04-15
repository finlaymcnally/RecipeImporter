from __future__ import annotations

from cookimport.bench.qualitysuite.shared import *  # noqa: F401,F403
from cookimport.bench.qualitysuite import planning as _planning
from cookimport.bench.qualitysuite import shared as _shared
from cookimport.bench.pairwise_flips import resolve_existing_line_role_flips_jsonl_path

globals().update(
    {name: getattr(_shared, name) for name in dir(_shared) if not name.startswith("__")}
)
globals().update(
    {
        name: getattr(_planning, name)
        for name in dir(_planning)
        if not name.startswith("__")
    }
)


def _resolve_selected_targets(suite: QualitySuite) -> list[Any]:
    by_id = {target.target_id: target for target in suite.targets}
    selected_targets = []
    for target_id in suite.selected_target_ids:
        if target_id not in by_id:
            continue
        selected_targets.append(by_id[target_id])
    return selected_targets


def _target_source_extension(target: Any) -> str:
    explicit_extension = str(getattr(target, "source_extension", "") or "").strip().lower()
    if explicit_extension:
        if explicit_extension in {"__none__", "none", "null"}:
            return ""
        if not explicit_extension.startswith("."):
            explicit_extension = f".{explicit_extension}"
        if explicit_extension == ".":
            return ""
        return explicit_extension

    source_file = str(getattr(target, "source_file", "") or "").strip()
    if not source_file:
        return ""
    return Path(source_file).suffix.lower()


def _target_format_counts(targets: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        extension = _target_source_extension(target)
        key = extension or _SOURCE_EXTENSION_NONE
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


class QualityExperimentResult(BaseModel):
    """Normalized experiment result row used by quality summaries and compare."""

    id: str
    status: str
    error: str | None = None
    run_settings_hash: str | None = None
    run_settings_summary: str | None = None
    # Optional: when line-role pipeline artifacts exist under the experiment root,
    # capture a tiny, human-friendly summary plus file pointers.
    line_role_artifacts: dict[str, Any] | None = None
    strict_precision_macro: float | None = None
    strict_recall_macro: float | None = None
    strict_f1_macro: float | None = None
    practical_precision_macro: float | None = None
    practical_recall_macro: float | None = None
    practical_f1_macro: float | None = None
    source_success_rate: float | None = None
    sources_planned: int = 0
    sources_successful: int = 0
    configs_planned: int = 0
    configs_completed: int = 0
    configs_successful: int = 0
    evaluation_signatures_unique: int = 0
    evaluation_runs_executed: int = 0
    evaluation_results_reused_in_run: int = 0
    evaluation_results_reused_cross_run: int = 0
    source_group_count: int = 0
    source_group_with_multiple_shards: int = 0
    report_json_path: str | None = None
    report_md_path: str | None = None

def load_quality_run_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists() or not summary_path.is_file():
        raise FileNotFoundError(f"Missing quality run summary: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid quality run summary payload: {summary_path}")
    return payload

def _summarize_experiment_report(
    *,
    experiment_root: Path,
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    source_groups = _aggregate_source_groups(
        experiment_root=experiment_root,
        report_payload=report_payload,
    )
    strict_precision_values = [
        row["strict_precision"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_precision"] is not None
    ]
    strict_recall_values = [
        row["strict_recall"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_recall"] is not None
    ]
    strict_f1_values = [
        row["strict_f1"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_f1"] is not None
    ]
    practical_precision_values = [
        row["practical_precision"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_precision"] is not None
    ]
    practical_recall_values = [
        row["practical_recall"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_recall"] is not None
    ]
    practical_f1_values = [
        row["practical_f1"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_f1"] is not None
    ]

    sources_planned = _coerce_int(report_payload.get("matched_target_count"))
    if sources_planned <= 0:
        sources_planned = len(source_groups)
    sources_successful = sum(1 for row in source_groups if row["status"] == "ok")
    source_success_rate = (
        float(sources_successful) / float(sources_planned)
        if sources_planned > 0
        else None
    )

    configs_planned = _coerce_int(report_payload.get("total_config_runs_planned"))
    configs_completed = _coerce_int(report_payload.get("total_config_runs_completed"))
    configs_successful = _coerce_int(report_payload.get("total_config_runs_successful"))

    failed_groups = [row for row in source_groups if row["status"] != "ok"]
    status = "ok"
    error = None
    if sources_planned <= 0 or sources_successful <= 0:
        status = "incomplete"
        error = "No successful source groups were evaluated."
    elif failed_groups:
        status = "incomplete"
        error = f"{len(failed_groups)} source group(s) failed."
    elif configs_planned > 0 and configs_successful < configs_planned:
        status = "incomplete"
        error = (
            f"Config success is incomplete ({configs_successful}/{configs_planned})."
        )

    return {
        "status": status,
        "error": error,
        "strict_precision_macro": _mean_or_none(strict_precision_values),
        "strict_recall_macro": _mean_or_none(strict_recall_values),
        "strict_f1_macro": _mean_or_none(strict_f1_values),
        "practical_precision_macro": _mean_or_none(practical_precision_values),
        "practical_recall_macro": _mean_or_none(practical_recall_values),
        "practical_f1_macro": _mean_or_none(practical_f1_values),
        "source_success_rate": source_success_rate,
        "sources_planned": sources_planned,
        "sources_successful": sources_successful,
        "configs_planned": configs_planned,
        "configs_completed": configs_completed,
        "configs_successful": configs_successful,
        "evaluation_signatures_unique": _coerce_int(
            report_payload.get("evaluation_signatures_unique")
        ),
        "evaluation_runs_executed": _coerce_int(
            report_payload.get("evaluation_runs_executed")
        ),
        "evaluation_results_reused_in_run": _coerce_int(
            report_payload.get("evaluation_results_reused_in_run")
        ),
        "evaluation_results_reused_cross_run": _coerce_int(
            report_payload.get("evaluation_results_reused_cross_run")
        ),
        "source_group_count": len(source_groups),
        "source_group_with_multiple_shards": sum(
            1 for row in source_groups if row["shard_count"] > 1
        ),
    }

def _aggregate_source_groups(
    *,
    experiment_root: Path,
    report_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list):
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        source_group_key = str(row.get("source_group_key") or "").strip()
        if not source_group_key:
            source_group_key = str(row.get("source_file_name") or "").strip()
        if not source_group_key:
            source_group_key = str(row.get("source_file") or "").strip()
        if not source_group_key:
            continue
        grouped.setdefault(source_group_key, []).append(row)

    aggregated: list[dict[str, Any]] = []
    for source_group_key, rows in sorted(grouped.items()):
        shard_candidates: list[tuple[float, dict[str, Any], str | None]] = []
        row_status = "ok"
        row_errors: list[str] = []
        max_shard_total = 1

        for row in rows:
            status = str(row.get("status") or "").strip().lower()
            if status != "ok":
                row_status = "failed"
                error_text = str(row.get("error") or "").strip()
                if error_text:
                    row_errors.append(error_text)
            max_shard_total = max(max_shard_total, _coerce_int(row.get("source_shard_total"), minimum=1))
            for report_json_path in _candidate_report_json_paths(row):
                report_payload_for_source = _load_source_report(
                    experiment_root=experiment_root,
                    report_json_path=report_json_path,
                )
                if report_payload_for_source is None:
                    continue
                winner = report_payload_for_source.get("winner_by_f1")
                if not isinstance(winner, dict):
                    continue
                strict_f1 = _coerce_float(winner.get("f1"))
                if strict_f1 is None:
                    continue
                shard_candidates.append((strict_f1, winner, report_json_path))

        chosen_winner: dict[str, Any] | None = None
        if shard_candidates:
            shard_candidates.sort(key=lambda row: row[0], reverse=True)
            chosen_winner = shard_candidates[0][1]
            max_shard_total = max(max_shard_total, len(shard_candidates))
        else:
            fallback_row = rows[0]
            winner_metrics = fallback_row.get("winner_metrics")
            if isinstance(winner_metrics, dict):
                chosen_winner = dict(winner_metrics)

        strict_precision = _coerce_float(
            chosen_winner.get("precision") if isinstance(chosen_winner, dict) else None
        )
        strict_recall = _coerce_float(
            chosen_winner.get("recall") if isinstance(chosen_winner, dict) else None
        )
        strict_f1 = _coerce_float(
            chosen_winner.get("f1") if isinstance(chosen_winner, dict) else None
        )
        practical_precision = _coerce_float(
            chosen_winner.get("practical_precision")
            if isinstance(chosen_winner, dict)
            else None
        )
        practical_recall = _coerce_float(
            chosen_winner.get("practical_recall")
            if isinstance(chosen_winner, dict)
            else None
        )
        practical_f1 = _coerce_float(
            chosen_winner.get("practical_f1")
            if isinstance(chosen_winner, dict)
            else None
        )

        aggregated.append(
            {
                "source_group_key": source_group_key,
                "status": row_status,
                "error": " | ".join(row_errors) if row_errors else None,
                "strict_precision": strict_precision,
                "strict_recall": strict_recall,
                "strict_f1": strict_f1,
                "practical_precision": practical_precision,
                "practical_recall": practical_recall,
                "practical_f1": practical_f1,
                "shard_count": max_shard_total,
            }
        )

    return aggregated

def _candidate_report_json_paths(row: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    list_payload = row.get("report_json_paths")
    if isinstance(list_payload, list):
        for item in list_payload:
            rendered = str(item or "").strip()
            if rendered:
                paths.append(rendered)
    single_payload = str(row.get("report_json_path") or "").strip()
    if single_payload:
        paths.append(single_payload)

    deduped: list[str] = []
    seen: set[str] = set()
    for path_value in paths:
        if path_value in seen:
            continue
        seen.add(path_value)
        deduped.append(path_value)
    return deduped

def _load_source_report(
    *,
    experiment_root: Path,
    report_json_path: str,
) -> dict[str, Any] | None:
    candidate = Path(report_json_path)
    if not candidate.is_absolute():
        candidate = experiment_root / candidate
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload

def _build_summary_payload(
    *,
    suite: QualitySuite,
    run_timestamp: str,
    experiments: list[_ResolvedExperiment],
    results: list[QualityExperimentResult],
) -> dict[str, Any]:
    result_rows = [result.model_dump(mode="json") for result in results]
    selected_targets = _resolve_selected_targets(suite)
    format_counts = _target_format_counts(list(suite.targets))
    selected_format_counts = _target_format_counts(selected_targets)
    run_settings_by_id = {
        experiment.id: {
            "run_settings": experiment.run_settings.to_run_config_dict(),
            "run_settings_summary": experiment.run_settings.summary(),
            "run_settings_hash": experiment.run_settings.stable_hash(),
            "requested_run_settings": (
                experiment.requested_run_settings.to_run_config_dict()
            ),
            "requested_run_settings_summary": (
                experiment.requested_run_settings.summary()
            ),
            "requested_run_settings_hash": (
                experiment.requested_run_settings.stable_hash()
            ),
        }
        for experiment in experiments
    }

    return {
        "schema_version": 1,
        "run_timestamp": run_timestamp,
        "suite_name": suite.name,
        "suite_generated_at": suite.generated_at,
        "selection_algorithm_version": str(suite.selection.get("algorithm_version") or ""),
        "target_count_total": len(suite.targets),
        "target_count_selected": len(selected_targets),
        "format_counts": format_counts,
        "selected_format_counts": selected_format_counts,
        "experiment_count": len(results),
        "successful_experiments": sum(1 for row in results if row.status == "ok"),
        "incomplete_experiments": sum(1 for row in results if row.status == "incomplete"),
        "failed_experiments": sum(1 for row in results if row.status == "failed"),
        "experiments": result_rows,
        "run_settings_by_experiment": run_settings_by_id,
    }

def _format_quality_run_report(summary_payload: dict[str, Any]) -> str:
    def _render_format_counts(value: Any) -> str:
        if not isinstance(value, dict) or not value:
            return "n/a"
        rendered_parts = []
        for key in sorted(value):
            rendered_parts.append(f"{key}={value[key]}")
        return ", ".join(rendered_parts)

    lines = [
        "# Quality Suite Report",
        "",
        f"- Run timestamp: {summary_payload.get('run_timestamp')}",
        f"- Suite: {summary_payload.get('suite_name')}",
        f"- Targets selected: {summary_payload.get('target_count_selected')}",
        f"- Selected formats: {_render_format_counts(summary_payload.get('selected_format_counts'))}",
        f"- Matched formats: {_render_format_counts(summary_payload.get('format_counts'))}",
        f"- Experiments: {summary_payload.get('experiment_count')}",
        f"- Successful: {summary_payload.get('successful_experiments')}",
        f"- Incomplete: {summary_payload.get('incomplete_experiments')}",
        f"- Failed: {summary_payload.get('failed_experiments')}",
        "- Codex decision: "
        f"{((summary_payload.get('codex_execution_policy') or {}).get('codex_execution_summary') or 'n/a')}",
        "",
        "## Experiments",
        "",
    ]
    for row in summary_payload.get("experiments", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "- "
            f"{row.get('id')} | status={row.get('status')} | "
            f"strict_f1_macro={_render_metric(row.get('strict_f1_macro'))} | "
            f"practical_f1_macro={_render_metric(row.get('practical_f1_macro'))} | "
            f"source_success_rate={_render_metric(row.get('source_success_rate'))} | "
            f"settings_hash={row.get('run_settings_hash') or 'n/a'}"
        )
        report_md_path = str(row.get("report_md_path") or "").strip()
        report_json_path = str(row.get("report_json_path") or "").strip()
        if report_md_path or report_json_path:
            report_bits = []
            if report_md_path:
                report_bits.append(f"md={report_md_path}")
            if report_json_path:
                report_bits.append(f"json={report_json_path}")
            lines.append(f"  report: {', '.join(report_bits)}")
        error_text = str(row.get("error") or "").strip()
        if error_text:
            lines.append(f"  error: {error_text}")
        artifacts = row.get("line_role_artifacts")
        if isinstance(artifacts, dict):
            eval_dir_count = _coerce_int(artifacts.get("line_role_eval_dir_count"))
            lines.append(f"  line-role: eval_dirs={eval_dir_count}")
            gate_counts = artifacts.get("gate_verdict_counts")
            if isinstance(gate_counts, dict) and gate_counts:
                rendered = ", ".join(f"{k}={gate_counts[k]}" for k in sorted(gate_counts))
                lines.append(f"  line-role gates: {rendered}")
            examples = artifacts.get("examples")
            if isinstance(examples, list) and examples:
                example = examples[0] if isinstance(examples[0], dict) else None
                if isinstance(example, dict):
                    line_role_dir = str(example.get("line_role_dir") or "").strip()
                    if line_role_dir:
                        lines.append(f"  line-role sample: {line_role_dir}")
                    joined = str(example.get("joined_line_table_jsonl") or "").strip()
                    flips = str(
                        example.get("line_role_flips_vs_reference_jsonl")
                        or example.get("line_role_flips_vs_baseline_jsonl")
                        or ""
                    ).strip()
                    slice_path = str(example.get("slice_metrics_json") or "").strip()
                    routing_path = str(example.get("routing_summary_json") or "").strip()
                    gates_path = str(example.get("regression_gates_json") or "").strip()
                    if joined or flips or slice_path or routing_path or gates_path:
                        artifact_bits = []
                        if joined:
                            artifact_bits.append(f"joined={joined}")
                        if flips:
                            artifact_bits.append(f"flips={flips}")
                        if slice_path:
                            artifact_bits.append(f"slices={slice_path}")
                        if routing_path:
                            artifact_bits.append(f"routing={routing_path}")
                        if gates_path:
                            artifact_bits.append(f"gates={gates_path}")
                        lines.append(f"  line-role artifacts (sample): {', '.join(artifact_bits)}")
                    slice_summary = example.get("slice_metrics_summary")
                    if isinstance(slice_summary, dict) and slice_summary:
                        # Keep report short: just show line counts for each slice.
                        slice_counts = ", ".join(
                            f"{name}={_coerce_int((slice_summary.get(name) or {}).get('line_count'))}"
                            for name in sorted(slice_summary)
                        )
                        lines.append(f"  line-role slices (sample): {slice_counts}")
                    routing = example.get("routing_summary")
                    if isinstance(routing, dict) and routing:
                        candidate = _coerce_int(routing.get("outside_recipe_candidate_count"))
                        excluded = _coerce_int(routing.get("outside_recipe_excluded_count"))
                        structured = _coerce_int(routing.get("outside_recipe_structured_count"))
                        lines.append(
                            "  routing (sample): "
                            f"candidate={candidate}, excluded={excluded}, outside_recipe_structured={structured}"
                        )
    lines.append("")
    return "\n".join(lines)

def _relative_to_run_root(path: Path, run_root: Path) -> str:
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)

def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.mean(values))

def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, numeric)

def _coerce_int(value: Any, *, minimum: int = 0) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, numeric)

def _render_metric(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.4f}"

def _load_json_object_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload

def _summarize_line_role_artifacts(
    *,
    experiment_root: Path,
    run_root: Path,
    max_examples: int = 8,
) -> dict[str, Any] | None:
    """Best-effort detector for line-role pipeline artifacts under an experiment root.

    This must never raise: QualitySuite should still complete/report even when the
    line-role pipeline was not enabled or artifacts are partially missing.
    """
    if max_examples < 1:
        max_examples = 1

    # In labelstudio-benchmark runs these artifacts live under:
    # <eval_output_dir>/line-role-pipeline/<artifact>
    slice_metric_paths = list(
        experiment_root.glob("**/line-role-pipeline/slice_metrics.json")
    )
    if not slice_metric_paths:
        return None

    line_role_dirs = sorted({path.parent for path in slice_metric_paths}, key=str)
    example_dirs = line_role_dirs[: max_examples]

    def _rel(path: Path) -> str:
        return _relative_to_run_root(path, run_root)

    examples: list[dict[str, Any]] = []
    gate_verdict_counts: dict[str, int] = {}
    for line_role_dir in example_dirs:
        joined_path = line_role_dir / "joined_line_table.jsonl"
        flips_path = resolve_existing_line_role_flips_jsonl_path(line_role_dir)
        slice_path = line_role_dir / "slice_metrics.json"
        routing_path = line_role_dir / "routing_summary.json"
        gates_path = line_role_dir / "regression_gates.json"

        slice_payload = _load_json_object_or_none(slice_path) or {}
        routing_payload = _load_json_object_or_none(routing_path) or {}
        gates_payload = _load_json_object_or_none(gates_path) or {}

        gates_verdict = str(
            ((gates_payload.get("overall") or {}).get("verdict")) or ""
        ).strip().upper()
        if gates_verdict:
            gate_verdict_counts[gates_verdict] = gate_verdict_counts.get(gates_verdict, 0) + 1

        slices_summary: dict[str, Any] = {}
        slices_payload = slice_payload.get("slices")
        if isinstance(slices_payload, dict):
            for slice_name in sorted(slices_payload):
                slice_row = slices_payload.get(slice_name)
                if not isinstance(slice_row, dict):
                    continue
                slices_summary[str(slice_name)] = {
                    "line_count": _coerce_int(slice_row.get("line_count")),
                    "overall_line_accuracy": _coerce_float(
                        slice_row.get("overall_line_accuracy")
                    ),
                    "macro_f1_excluding_other": _coerce_float(
                        slice_row.get("macro_f1_excluding_other")
                    ),
                }

        examples.append(
            {
                "line_role_dir": _rel(line_role_dir),
                "joined_line_table_jsonl": _rel(joined_path) if joined_path.exists() else None,
                "line_role_flips_vs_reference_jsonl": (
                    _rel(flips_path)
                    if flips_path is not None and flips_path.exists()
                    else None
                ),
                "slice_metrics_json": _rel(slice_path) if slice_path.exists() else None,
                "routing_summary_json": _rel(routing_path) if routing_path.exists() else None,
                "regression_gates_json": _rel(gates_path) if gates_path.exists() else None,
                "regression_gates_verdict": gates_verdict or None,
                "slice_metrics_summary": slices_summary,
                "routing_summary": {
                    "inside_recipe_line_count": _coerce_int(
                        routing_payload.get("inside_recipe_line_count")
                    ),
                    "outside_recipe_line_count": _coerce_int(
                        routing_payload.get("outside_recipe_line_count")
                    ),
                    "unknown_recipe_status_line_count": _coerce_int(
                        routing_payload.get("unknown_recipe_status_line_count")
                    ),
                    "recipe_local_label_count": _coerce_int(
                        routing_payload.get("recipe_local_label_count")
                    ),
                    "outside_recipe_structured_count": _coerce_int(
                        routing_payload.get("outside_recipe_structured_count")
                    ),
                    "outside_recipe_candidate_count": _coerce_int(
                        routing_payload.get("outside_recipe_candidate_count")
                    ),
                    "outside_recipe_excluded_count": _coerce_int(
                        routing_payload.get("outside_recipe_excluded_count")
                    ),
                }
                if routing_payload
                else {},
            }
        )

    return {
        "schema_version": "quality_line_role_artifacts.v1",
        "line_role_eval_dir_count": len(line_role_dirs),
        "examples": examples,
        "gate_verdict_counts": dict(sorted(gate_verdict_counts.items())),
    }
