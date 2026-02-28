"""Speed-suite execution for import and benchmark runtime scenarios."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import statistics
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.bench.speed_suite import SpeedSuite, SpeedTarget, resolve_repo_path
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_adapters import (
    build_benchmark_call_kwargs_from_run_settings,
    build_stage_call_kwargs_from_run_settings,
)
from cookimport.core.progress_messages import format_task_counter
from cookimport.paths import REPO_ROOT
from cookimport.runs import RunManifest, RunSource, write_run_manifest


class SpeedScenario(str, Enum):
    STAGE_IMPORT = "stage_import"
    BENCHMARK_CANONICAL_LEGACY = "benchmark_canonical_legacy"
    BENCHMARK_CANONICAL_PIPELINED = "benchmark_canonical_pipelined"
    BENCHMARK_ALL_METHOD_MULTI_SOURCE = "benchmark_all_method_multi_source"


SPEED_SUITE_ALL_MATCHED_TARGET_ID = "__all_matched__"
_SPEED_SUITE_ALL_MATCHED_TARGET_DIR = "_all_matched"


ProgressCallback = Callable[[str], None]


def run_speed_suite(
    suite: SpeedSuite,
    out_dir: Path,
    *,
    scenarios: list[SpeedScenario],
    warmups: int,
    repeats: int,
    max_targets: int | None = None,
    run_settings: RunSettings,
    include_codex_farm_requested: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if not scenarios:
        raise ValueError("At least one scenario is required.")

    run_started = dt.datetime.now()
    run_timestamp = run_started.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    selected_targets = list(suite.targets)
    if max_targets is not None:
        selected_targets = selected_targets[: max(0, max_targets)]
    if not selected_targets:
        raise ValueError("No speed targets selected for this run.")

    suite_payload = suite.model_dump()
    suite_payload["targets"] = [target.model_dump() for target in selected_targets]
    suite_payload["target_count_selected"] = len(selected_targets)
    suite_payload["target_count_total"] = len(suite.targets)
    (run_root / "suite_resolved.json").write_text(
        json.dumps(suite_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    sample_rows: list[dict[str, Any]] = []
    scenario_work_items: list[tuple[SpeedScenario, SpeedTarget | None]] = []
    for scenario in scenarios:
        if _scenario_runs_once_per_suite(scenario):
            scenario_work_items.append((scenario, None))
            continue
        for target in selected_targets:
            scenario_work_items.append((scenario, target))

    total_tasks = len(scenario_work_items) * (warmups + repeats)
    completed_tasks = 0

    def _notify(message: str) -> None:
        if progress_callback is None:
            return
        progress_callback(message)

    for scenario, scenario_target in scenario_work_items:
        target_id = (
            SPEED_SUITE_ALL_MATCHED_TARGET_ID
            if scenario_target is None
            else scenario_target.target_id
        )
        source_file_for_row = (
            None if scenario_target is None else scenario_target.source_file
        )
        gold_spans_for_row = (
            None if scenario_target is None else scenario_target.gold_spans_path
        )
        target_source = (
            None
            if scenario_target is None
            else resolve_repo_path(scenario_target.source_file, repo_root=REPO_ROOT)
        )
        target_gold = (
            None
            if scenario_target is None
            else resolve_repo_path(scenario_target.gold_spans_path, repo_root=REPO_ROOT)
        )

        for phase, phase_index in _iter_sample_phases(warmups=warmups, repeats=repeats):
            completed_tasks += 1
            task_prefix = format_task_counter(
                "Speed suite",
                completed_tasks,
                total_tasks,
                noun="task",
            )
            _notify(
                f"{task_prefix} [{target_id}] {scenario.value} "
                f"{phase} {phase_index}..."
            )

            sample_dir = (
                run_root
                / "scenario_runs"
                / (
                    _SPEED_SUITE_ALL_MATCHED_TARGET_DIR
                    if scenario_target is None
                    else scenario_target.target_id
                )
                / scenario.value
                / f"{phase}_{phase_index:02d}"
            )
            sample_dir.mkdir(parents=True, exist_ok=True)

            sample_started = time.monotonic()
            if scenario == SpeedScenario.STAGE_IMPORT:
                if target_source is None:
                    raise ValueError("stage_import scenario requires a concrete target.")
                metrics = _run_stage_import_sample(
                    source_file=target_source,
                    sample_dir=sample_dir,
                    run_settings=run_settings,
                )
            elif scenario == SpeedScenario.BENCHMARK_CANONICAL_LEGACY:
                if target_source is None or target_gold is None:
                    raise ValueError(
                        "benchmark_canonical_legacy scenario requires a concrete target."
                    )
                metrics = _run_benchmark_sample(
                    source_file=target_source,
                    gold_spans_path=target_gold,
                    sample_dir=sample_dir,
                    execution_mode="legacy",
                    run_settings=run_settings,
                )
            elif scenario == SpeedScenario.BENCHMARK_CANONICAL_PIPELINED:
                if target_source is None or target_gold is None:
                    raise ValueError(
                        "benchmark_canonical_pipelined scenario requires a concrete target."
                    )
                metrics = _run_benchmark_sample(
                    source_file=target_source,
                    gold_spans_path=target_gold,
                    sample_dir=sample_dir,
                    execution_mode="pipelined",
                    run_settings=run_settings,
                )
            elif scenario == SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE:
                metrics = _run_all_method_multi_source_sample(
                    targets=selected_targets,
                    sample_dir=sample_dir,
                    run_settings=run_settings,
                    include_codex_farm_requested=include_codex_farm_requested,
                )
            else:
                raise ValueError(f"Unsupported speed scenario: {scenario}")

            wall_seconds = max(0.0, time.monotonic() - sample_started)
            timing_payload = metrics.pop("timing", {})
            sample_rows.append(
                {
                    "target_id": target_id,
                    "source_file": source_file_for_row,
                    "gold_spans_path": gold_spans_for_row,
                    "scenario": scenario.value,
                    "phase": phase,
                    "phase_index": phase_index,
                    "wall_seconds": float(wall_seconds),
                    "timing": timing_payload,
                    "metrics": metrics,
                    "sample_dir": _relative_to_run_root(sample_dir, run_root),
                }
            )

    _write_samples_jsonl(run_root / "samples.jsonl", sample_rows)
    summary_payload = _build_summary_payload(
        suite=suite,
        selected_targets=selected_targets,
        scenarios=scenarios,
        warmups=warmups,
        repeats=repeats,
        run_timestamp=run_timestamp,
        run_settings=run_settings,
        sample_rows=sample_rows,
    )
    (run_root / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / "report.md").write_text(
        _format_speed_run_report(summary_payload),
        encoding="utf-8",
    )

    manifest = RunManifest(
        run_kind="bench_speed_suite",
        run_id=run_timestamp,
        created_at=run_started.isoformat(timespec="seconds"),
        source=RunSource(path=suite.name),
        run_config={
            "warmups": int(warmups),
            "repeats": int(repeats),
            "max_targets": max_targets,
            "scenarios": [scenario.value for scenario in scenarios],
            "sequence_matcher": run_settings.benchmark_sequence_matcher,
            "run_settings": run_settings.to_run_config_dict(),
            "run_settings_summary": run_settings.summary(),
            "run_settings_hash": run_settings.stable_hash(),
        },
        artifacts={
            "suite_resolved_json": "suite_resolved.json",
            "samples_jsonl": "samples.jsonl",
            "summary_json": "summary.json",
            "report_md": "report.md",
        },
        notes="Deterministic speed regression suite run.",
    )
    write_run_manifest(run_root, manifest)
    return run_root


def load_speed_run_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists() or not summary_path.is_file():
        raise FileNotFoundError(f"Missing speed run summary: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid speed run summary payload: {summary_path}")
    return payload


def parse_speed_scenarios(raw_value: str) -> list[SpeedScenario]:
    tokens = [token.strip() for token in raw_value.split(",")]
    selected: list[SpeedScenario] = []
    seen: set[SpeedScenario] = set()
    for token in tokens:
        if not token:
            continue
        try:
            scenario = SpeedScenario(token)
        except ValueError as exc:
            allowed = ", ".join(s.value for s in SpeedScenario)
            raise ValueError(
                f"Invalid speed scenario: {token!r}. Allowed values: {allowed}"
            ) from exc
        if scenario in seen:
            continue
        seen.add(scenario)
        selected.append(scenario)
    if not selected:
        raise ValueError("No speed scenarios selected.")
    return selected


def _scenario_runs_once_per_suite(scenario: SpeedScenario) -> bool:
    return scenario == SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE


def _iter_sample_phases(*, warmups: int, repeats: int) -> Iterable[tuple[str, int]]:
    for index in range(1, warmups + 1):
        yield ("warmup", index)
    for index in range(1, repeats + 1):
        yield ("repeat", index)


def _run_stage_import_sample(
    *,
    source_file: Path,
    sample_dir: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    import cookimport.cli as cli

    stage_output_root = sample_dir / "stage_output"
    stage_output_root.mkdir(parents=True, exist_ok=True)
    stage_kwargs = build_stage_call_kwargs_from_run_settings(
        run_settings,
        out=stage_output_root,
        mapping=None,
        overrides=None,
        limit=None,
        write_markdown=False,
    )
    with _suppress_cli_output():
        stage_run_root = cli.stage(
            path=source_file,
            **stage_kwargs,
        )
    report_path = _select_stage_report_path(stage_run_root)
    report_payload = _load_json_dict(report_path) if report_path is not None else {}
    timing_payload = _extract_timing_payload(report_payload)
    return {
        "total_seconds": _coerce_float(timing_payload.get("total_seconds")),
        "parsing_seconds": _coerce_float(timing_payload.get("parsing_seconds")),
        "writing_seconds": _coerce_float(timing_payload.get("writing_seconds")),
        "ocr_seconds": _coerce_float(timing_payload.get("ocr_seconds")),
        "stage_run_root": _path_for_payload(stage_run_root),
        "report_path": _path_for_payload(report_path),
        "timing": timing_payload,
    }


def _run_benchmark_sample(
    *,
    source_file: Path,
    gold_spans_path: Path,
    sample_dir: Path,
    execution_mode: str,
    run_settings: RunSettings,
) -> dict[str, Any]:
    import cookimport.cli as cli

    prediction_output_dir = sample_dir / "prediction_output"
    processed_output_dir = sample_dir / "processed_output"
    eval_output_dir = sample_dir / "eval_output"
    prediction_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_dir.mkdir(parents=True, exist_ok=True)
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
        run_settings,
        output_dir=prediction_output_dir,
        processed_output_dir=processed_output_dir,
        eval_output_dir=eval_output_dir,
        eval_mode="canonical-text",
        execution_mode=execution_mode,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    with _suppress_cli_output():
        with cli._benchmark_progress_overrides(
            progress_callback=None,
            suppress_summary=True,
            suppress_spinner=True,
        ):
            cli.labelstudio_benchmark(
                gold_spans=gold_spans_path,
                source_file=source_file,
                **benchmark_kwargs,
            )

    eval_report_path = eval_output_dir / "eval_report.json"
    if not eval_report_path.exists() or not eval_report_path.is_file():
        raise FileNotFoundError(f"Missing eval report: {eval_report_path}")
    report_payload = _load_json_dict(eval_report_path)
    timing_payload = _extract_timing_payload(report_payload)
    return {
        "total_seconds": _coerce_float(timing_payload.get("total_seconds")),
        "prediction_seconds": _coerce_float(timing_payload.get("prediction_seconds")),
        "evaluation_seconds": _coerce_float(timing_payload.get("evaluation_seconds")),
        "parsing_seconds": _coerce_float(timing_payload.get("parsing_seconds")),
        "writing_seconds": _coerce_float(timing_payload.get("writing_seconds")),
        "eval_output_dir": _path_for_payload(eval_output_dir),
        "eval_report_path": _path_for_payload(eval_report_path),
        "timing": timing_payload,
    }


def _run_all_method_multi_source_sample(
    *,
    targets: list[SpeedTarget],
    sample_dir: Path,
    run_settings: RunSettings,
    include_codex_farm_requested: bool,
) -> dict[str, Any]:
    import cookimport.cli as cli

    if not targets:
        raise ValueError("All-method speed scenario requires at least one target.")

    resolved_targets: list[cli.AllMethodTarget] = []
    for target in targets:
        source_file = resolve_repo_path(target.source_file, repo_root=REPO_ROOT)
        gold_spans_path = resolve_repo_path(target.gold_spans_path, repo_root=REPO_ROOT)
        resolved_targets.append(
            cli.AllMethodTarget(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display=target.target_id,
            )
        )

    include_codex_effective, _codex_warning = cli._resolve_all_method_codex_choice(
        include_codex_farm_requested
    )
    target_variants = cli._build_all_method_target_variants(
        targets=resolved_targets,
        base_settings=run_settings,
        include_codex_farm=include_codex_effective,
        include_markdown_extractors=False,
    )

    eval_output_dir = sample_dir / "eval_output"
    processed_output_dir = sample_dir / "processed_output"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_dir.mkdir(parents=True, exist_ok=True)
    all_method_root = eval_output_dir / "all-method-benchmark"
    all_method_processed_root = processed_output_dir / "all-method-benchmark"

    with _suppress_cli_output():
        with cli._benchmark_progress_overrides(
            progress_callback=None,
            suppress_summary=True,
            suppress_spinner=True,
        ):
            report_md_path = cli._run_all_method_benchmark_multi_source(
                target_variants=target_variants,
                unmatched_targets=[],
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_farm_effective=include_codex_effective,
                root_output_dir=all_method_root,
                processed_output_root=all_method_processed_root,
                overlap_threshold=0.5,
                force_source_match=False,
                scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
            )

    report_json_path = report_md_path.with_suffix(".json")
    if not report_json_path.exists() or not report_json_path.is_file():
        raise FileNotFoundError(f"Missing all-method report: {report_json_path}")

    report_payload = _load_json_dict(report_json_path)
    timing_payload_raw = report_payload.get("timing_summary")
    timing_payload = (
        dict(timing_payload_raw) if isinstance(timing_payload_raw, dict) else {}
    )
    total_seconds = _coerce_float(timing_payload.get("run_wall_seconds"))
    if total_seconds is None:
        total_seconds = _coerce_float(timing_payload.get("source_total_seconds"))

    return {
        "total_seconds": total_seconds,
        "source_total_seconds": _coerce_float(timing_payload.get("source_total_seconds")),
        "config_total_seconds": _coerce_float(timing_payload.get("config_total_seconds")),
        "source_schedule_strategy": str(
            report_payload.get("source_schedule_strategy") or ""
        ),
        "source_job_count_planned": _coerce_float(
            report_payload.get("source_job_count_planned")
        ),
        "source_parallelism_effective": _coerce_float(
            report_payload.get("source_parallelism_effective")
        ),
        "matched_target_count": _coerce_float(report_payload.get("matched_target_count")),
        "successful_source_count": _coerce_float(
            report_payload.get("successful_source_count")
        ),
        "eval_output_dir": _path_for_payload(all_method_root),
        "report_json_path": _path_for_payload(report_json_path),
        "timing": timing_payload,
    }


def _select_stage_report_path(stage_run_root: Path) -> Path | None:
    report_paths = sorted(stage_run_root.glob("*.excel_import_report.json"))
    if not report_paths:
        return None
    return report_paths[0]


def _build_summary_payload(
    *,
    suite: SpeedSuite,
    selected_targets: list[SpeedTarget],
    scenarios: list[SpeedScenario],
    warmups: int,
    repeats: int,
    run_timestamp: str,
    run_settings: RunSettings,
    sample_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    repeat_rows = [row for row in sample_rows if row.get("phase") == "repeat"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in repeat_rows:
        key = (str(row.get("target_id") or ""), str(row.get("scenario") or ""))
        grouped.setdefault(key, []).append(row)

    summary_rows: list[dict[str, Any]] = []
    for (target_id, scenario), rows in sorted(grouped.items()):
        first = rows[0]
        row_payload = {
            "target_id": target_id,
            "scenario": scenario,
            "source_file": first.get("source_file"),
            "gold_spans_path": first.get("gold_spans_path"),
            "repeat_count": len(rows),
            "warmup_count": warmups,
            "median_wall_seconds": _median_float(
                _collect_metric(rows, container="root", key="wall_seconds")
            ),
            "median_total_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="total_seconds")
            ),
            "median_prediction_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="prediction_seconds")
            ),
            "median_evaluation_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="evaluation_seconds")
            ),
            "median_parsing_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="parsing_seconds")
            ),
            "median_writing_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="writing_seconds")
            ),
            "median_ocr_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="ocr_seconds")
            ),
        }
        summary_rows.append(row_payload)

    scenario_rollups: list[dict[str, Any]] = []
    for scenario in scenarios:
        rows_for_scenario = [
            row for row in summary_rows if row.get("scenario") == scenario.value
        ]
        medians = [
            _coerce_float(row.get("median_total_seconds"))
            for row in rows_for_scenario
            if _coerce_float(row.get("median_total_seconds")) is not None
        ]
        scenario_rollups.append(
            {
                "scenario": scenario.value,
                "target_count": len(rows_for_scenario),
                "median_total_seconds_across_targets": _median_float(medians),
            }
        )

    run_settings_payload = run_settings.to_run_config_dict()
    return {
        "schema_version": 1,
        "run_timestamp": run_timestamp,
        "suite_name": suite.name,
        "suite_generated_at": suite.generated_at,
        "target_count_selected": len(selected_targets),
        "target_count_total": len(suite.targets),
        "scenario_count": len(scenarios),
        "scenarios": [scenario.value for scenario in scenarios],
        "warmups": int(warmups),
        "repeats": int(repeats),
        "sequence_matcher": run_settings.benchmark_sequence_matcher,
        "run_settings": run_settings_payload,
        "run_settings_summary": run_settings.summary(),
        "run_settings_hash": run_settings.stable_hash(),
        "sample_count": len(sample_rows),
        "summary_rows": summary_rows,
        "scenario_rollups": scenario_rollups,
    }


def _format_speed_run_report(summary_payload: dict[str, Any]) -> str:
    lines = [
        "# Speed Suite Report",
        "",
        f"- Run timestamp: {summary_payload.get('run_timestamp')}",
        f"- Suite: {summary_payload.get('suite_name')}",
        f"- Scenarios: {', '.join(summary_payload.get('scenarios') or [])}",
        f"- Targets: {summary_payload.get('target_count_selected')}",
        f"- Warmups: {summary_payload.get('warmups')}",
        f"- Repeats: {summary_payload.get('repeats')}",
        f"- Sequence matcher: {summary_payload.get('sequence_matcher')}",
        f"- Run settings hash: {summary_payload.get('run_settings_hash')}",
        "",
        "## Scenario Rollups",
        "",
    ]
    for rollup in summary_payload.get("scenario_rollups", []):
        scenario = str(rollup.get("scenario") or "")
        median_total = _coerce_float(rollup.get("median_total_seconds_across_targets"))
        rendered = (
            f"{median_total:.3f}s"
            if median_total is not None
            else "n/a"
        )
        lines.append(
            f"- `{scenario}` median total across targets: {rendered} "
            f"(targets={int(rollup.get('target_count') or 0)})"
        )

    lines.extend(["", "## Per Target", ""])
    for row in summary_payload.get("summary_rows", []):
        lines.append(
            "- "
            f"{row.get('target_id')} | {row.get('scenario')} | "
            f"median_total={_render_seconds(row.get('median_total_seconds'))} | "
            f"median_wall={_render_seconds(row.get('median_wall_seconds'))}"
        )
    lines.append("")
    return "\n".join(lines)


def _write_samples_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    payload = "\n".join(lines).rstrip()
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _collect_metric(
    rows: list[dict[str, Any]],
    *,
    container: str,
    key: str,
) -> list[float]:
    values: list[float] = []
    for row in rows:
        if container == "root":
            value = row.get(key)
        else:
            value = (row.get(container) or {}).get(key)
        numeric = _coerce_float(value)
        if numeric is not None:
            values.append(numeric)
    return values


def _extract_timing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    timing = payload.get("timing")
    if isinstance(timing, dict):
        return dict(timing)
    return {}


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return 0.0
    return numeric


def _median_float(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _render_seconds(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.3f}s"


def _relative_to_run_root(path: Path, run_root: Path) -> str:
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)


def _path_for_payload(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


@contextlib.contextmanager
def _suppress_cli_output() -> Iterable[None]:
    with contextlib.redirect_stdout(io.StringIO()):
        with contextlib.redirect_stderr(io.StringIO()):
            yield
