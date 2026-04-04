from __future__ import annotations

import importlib
import datetime as dt
import json
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from cookimport.cli_support import (
    ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION,
    ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
    ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION,
    BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
    BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV,
    BENCHMARK_EVAL_PROFILE_TOP_N_ENV,
    logger,
)
from cookimport.core.progress_dashboard import ProgressDashboardCore, ProgressQueueRow
from cookimport.core.slug import slugify_name
from .bench_all_method_types import (
    AllMethodTarget,
    AllMethodVariant,
    _AllMethodSourceJobPlan,
)
from .stage import _path_for_manifest


def _bench_all_method_module():
    return importlib.import_module("cookimport.cli_support.bench_all_method")


@dataclass
class _AllMethodSourceDashboardRow:
    source_name: str
    total_configs: int
    status: str = "pending"
    completed_configs: int = 0
    successful_configs: int = 0
    failed_configs: int = 0


@dataclass
class _AllMethodProgressDashboard:
    rows: list[_AllMethodSourceDashboardRow]
    total_planned_configs: int
    current_source_index: int | None = None
    current_config_index: int = 0
    current_config_total: int = 0
    current_config_slug: str = ""
    _core: ProgressDashboardCore = field(
        default_factory=ProgressDashboardCore, repr=False, compare=False
    )
    active_config_slugs_by_source: dict[int, dict[int, str]] = field(
        default_factory=dict
    )
    active_config_phases_by_source: dict[int, dict[int, str]] = field(
        default_factory=dict
    )
    task_message: str = ""
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    @classmethod
    def from_target_variants(
        cls,
        target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    ) -> "_AllMethodProgressDashboard":
        rows = [
            _AllMethodSourceDashboardRow(
                source_name=target.source_file_name,
                total_configs=max(0, len(variants)),
            )
            for target, variants in target_variants
        ]
        total_planned_configs = sum(row.total_configs for row in rows)
        return cls(rows=rows, total_planned_configs=total_planned_configs)

    def _completed_sources(self) -> int:
        return sum(1 for row in self.rows if row.status in {"done", "failed"})

    def _completed_configs(self) -> int:
        return sum(max(0, row.completed_configs) for row in self.rows)

    def _running_source_indices(self) -> list[int]:
        return [
            index
            for index, row in enumerate(self.rows)
            if str(row.status).strip().lower() == "running"
        ]

    def _set_focus_source_state(self, source_index: int | None) -> None:
        if source_index is None or source_index < 0 or source_index >= len(self.rows):
            self.current_source_index = None
            self.current_config_index = 0
            self.current_config_total = 0
            self.current_config_slug = ""
            return
        row = self.rows[source_index]
        self.current_source_index = source_index
        self.current_config_total = max(0, row.total_configs)
        active_for_source = self.active_config_slugs_by_source.get(source_index, {})
        if active_for_source:
            active_index = min(active_for_source)
            self.current_config_index = active_index
            self.current_config_slug = active_for_source.get(active_index, "")
            return
        if row.completed_configs >= row.total_configs:
            self.current_config_index = 0
            self.current_config_slug = ""
            return
        self.current_config_index = min(
            max(0, row.total_configs),
            max(1, row.completed_configs + 1),
        )
        self.current_config_slug = ""

    def start_source(self, source_index: int) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "running"
            self.active_config_slugs_by_source.setdefault(source_index, {})
            self.active_config_phases_by_source.setdefault(source_index, {})
            self._set_focus_source_state(source_index)

    def finish_source(self, source_index: int, *, failed: bool = False) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "failed" if failed else "done"
            self.active_config_slugs_by_source.pop(source_index, None)
            self.active_config_phases_by_source.pop(source_index, None)
            if self.current_source_index == source_index:
                running_indices = self._running_source_indices()
                if running_indices:
                    self._set_focus_source_state(running_indices[0])
                else:
                    self._set_focus_source_state(None)

    def start_config(
        self,
        *,
        source_index: int,
        config_index: int,
        config_total: int,
        config_slug: str,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            self.current_source_index = source_index
            self.current_config_index = max(0, config_index)
            self.current_config_total = max(0, config_total)
            self.current_config_slug = str(config_slug or "").strip()
            if self.current_config_index > 0:
                active_for_source = self.active_config_slugs_by_source.setdefault(
                    source_index,
                    {},
                )
                active_for_source[self.current_config_index] = self.current_config_slug
                phase_for_source = self.active_config_phases_by_source.setdefault(
                    source_index,
                    {},
                )
                phase_for_source[self.current_config_index] = "prep"
            row = self.rows[source_index]
            row.status = "running"

    def complete_config(
        self,
        *,
        source_index: int,
        success: bool,
        config_index: int | None = None,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.completed_configs = min(
                row.total_configs,
                max(0, row.completed_configs + 1),
            )
            if success:
                row.successful_configs = min(
                    row.total_configs,
                    max(0, row.successful_configs + 1),
                )
            else:
                row.failed_configs = min(
                    row.total_configs,
                    max(0, row.failed_configs + 1),
                )
            active_for_source = self.active_config_slugs_by_source.setdefault(
                source_index,
                {},
            )
            phase_for_source = self.active_config_phases_by_source.setdefault(
                source_index,
                {},
            )
            if config_index is not None:
                safe_index = max(0, config_index)
                active_for_source.pop(safe_index, None)
                phase_for_source.pop(safe_index, None)
            if not active_for_source:
                self.active_config_slugs_by_source.pop(source_index, None)
                self.active_config_phases_by_source.pop(source_index, None)
            if self.current_source_index == source_index:
                self._set_focus_source_state(source_index)

    @staticmethod
    def _normalize_config_phase(phase: str) -> str:
        normalized = str(phase or "").strip().lower()
        if normalized in {"split_wait", "split wait"}:
            return "split_wait"
        if normalized in {"split_active", "split active"}:
            return "split_active"
        if normalized in {"prep", "post", "evaluate"}:
            return normalized
        return "prep"

    @staticmethod
    def _format_config_phase_label(phase: str) -> str:
        normalized = _AllMethodProgressDashboard._normalize_config_phase(phase)
        if normalized == "split_wait":
            return "split wait"
        if normalized == "split_active":
            return "split active"
        return normalized

    def set_config_phase(
        self,
        *,
        source_index: int,
        config_index: int,
        phase: str,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            safe_index = max(0, config_index)
            if safe_index <= 0:
                return
            active_for_source = self.active_config_slugs_by_source.get(source_index, {})
            if safe_index not in active_for_source:
                return
            phase_for_source = self.active_config_phases_by_source.setdefault(
                source_index,
                {},
            )
            phase_for_source[safe_index] = self._normalize_config_phase(phase)

    def set_task(self, message: str) -> None:
        with self._lock:
            cleaned = str(message or "").strip().replace("\n", " ")
            self.task_message = cleaned

    def _iter_queue_rows(self) -> Iterable[_AllMethodSourceDashboardRow]:
        if len(self.rows) <= 10:
            for row in self.rows:
                yield row
            return
        if self.current_source_index is None:
            visible_indices = set(range(0, 6))
        else:
            start = max(0, self.current_source_index - 2)
            end = min(len(self.rows), start + 6)
            visible_indices = set(range(start, end))
        visible_indices.update({len(self.rows) - 2, len(self.rows) - 1})
        for index, row in enumerate(self.rows):
            if index in visible_indices:
                yield row

    def _queue_rows(self) -> list[ProgressQueueRow]:
        marker_by_status = {
            "pending": "[ ]",
            "running": "[>]",
            "done": "[x]",
            "failed": "[!]",
        }
        rows = list(self.rows) if len(self.rows) <= 10 else list(self._iter_queue_rows())
        queue_rows = [
            ProgressQueueRow(
                marker=marker_by_status.get(row.status, "[ ]"),
                name=str(row.source_name),
                completed=max(0, row.completed_configs),
                total=max(0, row.total_configs),
                ok=max(0, row.successful_configs),
                fail=max(0, row.failed_configs),
            )
            for row in rows
        ]
        if len(self.rows) > 10:
            rendered_ids = {id(row) for row in rows}
            hidden_count = sum(1 for row in self.rows if id(row) not in rendered_ids)
            if hidden_count > 0:
                queue_rows.append(
                    ProgressQueueRow(
                        marker="...",
                        name=f"{hidden_count} additional sources hidden",
                        completed=0,
                        total=0,
                        ok=0,
                        fail=0,
                    )
                )
        return queue_rows

    def render(self) -> str:
        with self._lock:
            source_total = len(self.rows)
            source_done = self._completed_sources()
            config_done = self._completed_configs()
            detail_lines: list[str] = []
            active_source_count = len(self._running_source_indices())
            if active_source_count > 0:
                detail_lines.append(f"active sources: {active_source_count}")

            if (
                self.current_source_index is not None
                and 0 <= self.current_source_index < len(self.rows)
            ):
                current_row = self.rows[self.current_source_index]
                detail_lines.append(
                    (
                        "current source: "
                        f"{current_row.source_name} "
                        f"({current_row.completed_configs} of {current_row.total_configs} configs; "
                        f"ok {current_row.successful_configs}, fail {current_row.failed_configs})"
                    )
                )
            if self.current_config_total > 0 and self.current_source_index is not None:
                phase_items = self.active_config_phases_by_source.get(
                    self.current_source_index,
                    {},
                )
                active_items = sorted(
                    self.active_config_slugs_by_source.get(
                        self.current_source_index,
                        {},
                    ).items()
                )
                if active_items:
                    if len(active_items) == 1:
                        active_index, active_slug = active_items[0]
                        slug = active_slug or "<pending>"
                        detail_lines.append(
                            (
                                f"current config {active_index}/{self.current_config_total}: "
                                f"{slug}"
                            )
                        )
                    else:
                        first_active = active_items[0][0]
                        last_active = active_items[-1][0]
                        detail_lines.append(
                            f"current configs {first_active}-{last_active}/"
                            f"{self.current_config_total} ({len(active_items)} active)"
                        )
                        detail_lines.append("active config workers:")
                        for active_index, active_slug in active_items:
                            phase = self._format_config_phase_label(
                                phase_items.get(active_index, "prep")
                            )
                            slug = active_slug or "<pending>"
                            if len(slug) > 120:
                                slug = f"{slug[:117]}..."
                            detail_lines.append(
                                f"  config {active_index:02d}: {phase} | {slug}"
                            )
                elif 0 <= self.current_source_index < len(self.rows):
                    current_row = self.rows[self.current_source_index]
                    if current_row.completed_configs < current_row.total_configs:
                        queued_index = min(
                            current_row.total_configs,
                            max(1, current_row.completed_configs + 1),
                        )
                        detail_lines.append(
                            f"current config {queued_index}/{self.current_config_total}: <queued>"
                        )
            status_line = (
                "overall "
                f"source {source_done}/{source_total} | "
                f"config {config_done}/{max(0, self.total_planned_configs)}"
            )
            self._core.set_status_line(status_line)
            self._core.set_extra_lines(detail_lines)
            self._core.set_task(self.task_message)
            self._core.set_queue_rows(self._queue_rows())
            return self._core.render()


def _report_metric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _report_optional_metric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median_metric(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _row_dimension_str(
    row: dict[str, Any],
    key: str,
) -> str | None:
    dimensions = row.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    value = dimensions.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_timing_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in (
        "total_seconds",
        "prediction_seconds",
        "evaluation_seconds",
        "artifact_write_seconds",
        "history_append_seconds",
        "parsing_seconds",
        "writing_seconds",
        "ocr_seconds",
    ):
        numeric = _report_optional_metric(payload.get(key))
        if numeric is None:
            continue
        normalized[key] = max(0.0, numeric)
    checkpoints: dict[str, float] = {}
    raw_checkpoints = payload.get("checkpoints")
    if isinstance(raw_checkpoints, dict):
        for raw_key, raw_value in raw_checkpoints.items():
            numeric = _report_optional_metric(raw_value)
            if numeric is None:
                continue
            checkpoints[str(raw_key)] = max(0.0, numeric)
    normalized["checkpoints"] = checkpoints
    return normalized


def _timing_with_updates(
    base: Any,
    *,
    checkpoints: dict[str, float] | None = None,
    **updates: float | None,
) -> dict[str, Any]:
    normalized = _normalize_timing_payload(base)
    normalized_checkpoints = normalized.get("checkpoints")
    if not isinstance(normalized_checkpoints, dict):
        normalized_checkpoints = {}
    if checkpoints:
        for key, value in checkpoints.items():
            numeric = _report_optional_metric(value)
            if numeric is None:
                continue
            normalized_checkpoints[str(key)] = max(0.0, numeric)
    normalized["checkpoints"] = normalized_checkpoints
    for key, value in updates.items():
        numeric = _report_optional_metric(value)
        if numeric is None:
            continue
        normalized[key] = max(0.0, numeric)
    return normalized


def _evaluation_telemetry_load_seconds(
    evaluation_telemetry: Any,
) -> tuple[float | None, float | None]:
    if not isinstance(evaluation_telemetry, dict):
        return None, None
    subphases = evaluation_telemetry.get("subphases")
    if not isinstance(subphases, dict):
        return None, None
    prediction_load = _report_optional_metric(subphases.get("load_prediction_seconds"))
    gold_load = _report_optional_metric(subphases.get("load_gold_seconds"))
    return prediction_load, gold_load


def _evaluation_telemetry_checkpoints(
    evaluation_telemetry: Any,
) -> dict[str, float]:
    checkpoints: dict[str, float] = {}
    if not isinstance(evaluation_telemetry, dict):
        return checkpoints

    total_seconds = _report_optional_metric(evaluation_telemetry.get("total_seconds"))
    if total_seconds is not None:
        checkpoints["evaluate_total_seconds"] = max(0.0, total_seconds)

    def _collect_block(block_key: str, prefix: str) -> None:
        raw_block = evaluation_telemetry.get(block_key)
        if not isinstance(raw_block, dict):
            return
        for raw_key, raw_value in raw_block.items():
            numeric = _report_optional_metric(raw_value)
            if numeric is None:
                continue
            key_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw_key).strip()).strip("_")
            if not key_suffix:
                continue
            checkpoint_key = f"{prefix}_{key_suffix}".lower()
            checkpoints[checkpoint_key] = max(0.0, numeric)

    _collect_block("subphases", "evaluate")
    _collect_block("resources", "evaluate_resource")
    _collect_block("work_units", "evaluate_work")
    return checkpoints


def _benchmark_eval_profile_min_seconds() -> float | None:
    raw_value = str(os.getenv(BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV) or "").strip()
    if not raw_value:
        return None
    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r (expected float seconds).",
            BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV,
            raw_value,
        )
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _benchmark_eval_profile_top_n() -> int:
    raw_value = str(os.getenv(BENCHMARK_EVAL_PROFILE_TOP_N_ENV) or "").strip()
    if not raw_value:
        return 60
    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r (expected positive integer).",
            BENCHMARK_EVAL_PROFILE_TOP_N_ENV,
            raw_value,
        )
        return 60
    return max(1, parsed)


def _report_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _render_all_method_report_md(report_payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# All Method Benchmark Report",
        "",
        f"- Created at: {report_payload.get('created_at', '')}",
        f"- Source file: {report_payload.get('source_file', '')}",
        f"- Gold spans: {report_payload.get('gold_spans_path', '')}",
        f"- Eval mode: {report_payload.get('eval_mode', BENCHMARK_EVAL_MODE_CANONICAL_TEXT)}",
        f"- Scheduler scope: {report_payload.get('scheduler_scope', 'per_source')}",
        f"- Total configurations: {report_payload.get('variant_count', 0)}",
        f"- Successful configurations: {report_payload.get('successful_variants', 0)}",
        f"- Failed configurations: {report_payload.get('failed_variants', 0)}",
        (
            "- Evaluation signatures unique / runs executed: "
            f"{_report_count(report_payload.get('evaluation_signatures_unique'))}/"
            f"{_report_count(report_payload.get('evaluation_runs_executed'))}"
        ),
        (
            "- Evaluation results reused in-run/cross-run: "
            f"{_report_count(report_payload.get('evaluation_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('evaluation_results_reused_cross_run'))}"
        ),
        (
            "- Prediction signatures unique / runs executed / reused in-run/cross-run: "
            f"{_report_count(report_payload.get('prediction_signatures_unique'))}/"
            f"{_report_count(report_payload.get('prediction_runs_executed'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_cross_run'))}"
        ),
        (
            "- Split/convert input groups / reuse candidates / safe / blocked: "
            f"{_report_count(report_payload.get('split_convert_input_groups'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_safe_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_blocked_by_prediction_variance'))}"
        ),
        (
            "- Failed-config retries requested/executed/recovered: "
            f"{_report_count(report_payload.get('retry_failed_configs_requested'))}/"
            f"{_report_count(report_payload.get('retry_passes_executed'))}/"
            f"{_report_count(report_payload.get('retry_recovered_configs'))}"
        ),
        (
            "- Codex Farm permutations requested/effective: "
            f"{report_payload.get('include_codex_farm_requested', False)}/"
            f"{report_payload.get('include_codex_farm_effective', False)}"
        ),
        "",
    ]

    winner = report_payload.get("winner_by_f1")
    if isinstance(winner, dict) and winner:
        lines.extend(
            [
                "## Winner",
                "",
                (
                    f"- {winner.get('config_dir', '')} "
                    f"(precision={_report_metric(winner.get('precision')):.3f}, "
                    f"recall={_report_metric(winner.get('recall')):.3f}, "
                    f"f1={_report_metric(winner.get('f1')):.3f})"
                ),
                "",
            ]
        )

    timing_summary = report_payload.get("timing_summary")
    if isinstance(timing_summary, dict):
        lines.extend(
            [
                "## Timing Summary",
                "",
                (
                    "- Source wall time: "
                    f"{_report_metric(timing_summary.get('source_wall_seconds')):.2f}s"
                ),
                (
                    "- Total successful config runtime: "
                    f"{_report_metric(timing_summary.get('config_total_seconds')):.2f}s"
                ),
            ]
        )
        average_seconds = _report_optional_metric(
            timing_summary.get("config_average_seconds")
        )
        if average_seconds is not None:
            lines.append(f"- Average config runtime: {average_seconds:.2f}s")
        median_seconds = _report_optional_metric(
            timing_summary.get("config_median_seconds")
        )
        if median_seconds is not None:
            lines.append(f"- Median config runtime: {median_seconds:.2f}s")
        slowest_config = str(timing_summary.get("slowest_config_dir") or "").strip()
        slowest_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if slowest_config and slowest_seconds is not None:
            lines.append(
                f"- Slowest config: {slowest_config} ({slowest_seconds:.2f}s)"
            )
        lines.append("")

    scheduler = report_payload.get("scheduler")
    if isinstance(scheduler, dict):
        lines.extend(
            [
                "## Scheduler Summary",
                "",
                (
                    "- Scheduler mode: "
                    f"{scheduler.get('mode', 'fixed')} "
                    f"(smart enabled={bool(scheduler.get('smart_scheduler_enabled', False))})"
                ),
                (
                    "- Inflight configured/effective: "
                    f"{_report_count(scheduler.get('configured_inflight_pipelines'))}/"
                    f"{_report_count(scheduler.get('effective_inflight_pipelines'))}"
                ),
                (
                    "- Split slots / wing target: "
                    f"{_report_count(scheduler.get('split_phase_slots'))}/"
                    f"{_report_count(scheduler.get('wing_backlog_target'))}"
                ),
                (
                    "- Eval-tail headroom mode configured/effective: "
                    f"{scheduler.get('eval_tail_headroom_mode', 'auto')} "
                    f"{_report_count(scheduler.get('eval_tail_headroom_configured'))}/"
                    f"{_report_count(scheduler.get('eval_tail_headroom_effective'))}"
                ),
                (
                    "- Max active during eval / effective inflight: "
                    f"{_report_count(scheduler.get('max_active_during_eval'))}/"
                    f"{_report_count(scheduler.get('effective_inflight_pipelines'))}"
                ),
                (
                    "- Split worker cap per active config (cpu/memory): "
                    f"{_report_count(scheduler.get('split_worker_cap_per_config'))}/"
                    f"{_report_count(scheduler.get('split_worker_cap_by_cpu'))}/"
                    f"{_report_count(scheduler.get('split_worker_cap_by_memory'))}"
                ),
                (
                    "- Config timeout / retry limit: "
                    f"{('off' if scheduler.get('config_timeout_seconds') is None else str(_report_count(scheduler.get('config_timeout_seconds'))) + 's')}/"
                    f"{_report_count(scheduler.get('failed_retry_limit'))}"
                ),
                (
                    "- Retry passes executed / recovered configs: "
                    f"{_report_count(scheduler.get('retry_passes_executed'))}/"
                    f"{_report_count(scheduler.get('retry_recovered_configs'))}"
                ),
                (
                    "- Heavy slot utilization: "
                    f"{_report_metric(scheduler.get('heavy_slot_utilization_pct')):.1f}% "
                    f"(busy { _report_metric(scheduler.get('heavy_slot_busy_seconds')):.2f}s / "
                    f"capacity {_report_metric(scheduler.get('heavy_slot_capacity_seconds')):.2f}s)"
                ),
                (
                    "- Wing backlog avg/max: "
                    f"{_report_metric(scheduler.get('avg_wing_backlog')):.2f}/"
                    f"{_report_count(scheduler.get('max_wing_backlog'))}"
                ),
                (
                    "- Heavy idle gap while pending: "
                    f"{_report_metric(scheduler.get('idle_gap_seconds')):.2f}s"
                ),
                (
                    "- Max active/eval pipelines observed: "
                    f"{_report_count(scheduler.get('max_active_pipelines_observed'))}/"
                    f"{_report_count(scheduler.get('max_eval_active_observed'))}"
                ),
                "",
            ]
        )
        timeseries_path = str(scheduler.get("timeseries_path") or "").strip()
        if timeseries_path:
            lines.extend(
                [
                    (
                        "- Scheduler time-series: "
                        f"{timeseries_path} "
                        f"({ _report_count(scheduler.get('timeseries_row_count')) } rows, "
                        f"poll { _report_metric(scheduler.get('snapshot_poll_seconds')):.2f}s, "
                        f"heartbeat { _report_metric(scheduler.get('timeseries_heartbeat_seconds')):.2f}s)"
                    ),
                    (
                        "- CPU utilization samples/source: "
                        f"{ _report_count(scheduler.get('cpu_utilization_samples')) }/"
                        f"{scheduler.get('cpu_utilization_source', 'unavailable')}"
                    ),
                    "",
                ]
            )

    lines.extend(
        [
            "## Ranked Configurations",
            "",
        ]
    )

    variants = report_payload.get("variants")
    if not isinstance(variants, list) or not variants:
        lines.append("- No variant results were recorded.")
        lines.append("")
        return "\n".join(lines)

    for row in variants:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        config_dir = str(row.get("config_dir") or "").strip() or "<unknown>"
        if status != "ok":
            lines.append(f"- {config_dir}: FAILED ({row.get('error', 'unknown error')})")
            continue
        rank_value = row.get("rank")
        rank_prefix = f"{rank_value}. " if rank_value is not None else ""
        eval_source = str(row.get("evaluation_result_source") or "").strip()
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        timing_suffix = f", time={row_seconds:.2f}s" if row_seconds is not None else ""
        eval_source_suffix = f", eval_source={eval_source}" if eval_source else ""
        lines.append(
            (
                f"- {rank_prefix}{config_dir} "
                f"(precision={_report_metric(row.get('precision')):.3f}, "
                f"recall={_report_metric(row.get('recall')):.3f}, "
                f"f1={_report_metric(row.get('f1')):.3f}, "
                f"practical_f1={_report_metric(row.get('practical_f1')):.3f}"
                f"{timing_suffix}{eval_source_suffix}) "
                f"[hash={row.get('run_config_hash', '')}]"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_all_method_multi_source_report_md(report_payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# All Method Benchmark Multi-Source Report",
        "",
        f"- Created at: {report_payload.get('created_at', '')}",
        f"- Eval mode: {report_payload.get('eval_mode', BENCHMARK_EVAL_MODE_CANONICAL_TEXT)}",
        f"- Scheduler scope: {report_payload.get('scheduler_scope', 'per_source')}",
        f"- Matched targets: {report_payload.get('matched_target_count', 0)}",
        f"- Unmatched targets: {report_payload.get('unmatched_target_count', 0)}",
        (
            "- Source parallelism configured/effective: "
            f"{_report_count(report_payload.get('source_parallelism_configured'))}/"
            f"{_report_count(report_payload.get('source_parallelism_effective'))}"
        ),
        (
            "- Source scheduling strategy: "
            f"{report_payload.get('source_schedule_strategy', ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY)}"
        ),
        (
            "- Planned source jobs: "
            f"{_report_count(report_payload.get('source_job_count_planned'))}"
        ),
        (
            "- Source sharding threshold/max-parts/min-variants: "
            f"{_report_metric(report_payload.get('source_shard_threshold_seconds')):.1f}/"
            f"{_report_count(report_payload.get('source_shard_max_parts'))}/"
            f"{_report_count(report_payload.get('source_shard_min_variants'))}"
        ),
        f"- Planned config runs: {report_payload.get('total_config_runs_planned', 0)}",
        f"- Completed config runs: {report_payload.get('total_config_runs_completed', 0)}",
        f"- Successful config runs: {report_payload.get('total_config_runs_successful', 0)}",
        (
            "- Global queue planned/completed/failed configs: "
            f"{_report_count(report_payload.get('global_queue_planned_configs'))}/"
            f"{_report_count(report_payload.get('global_queue_completed_configs'))}/"
            f"{_report_count(report_payload.get('global_queue_failed_configs'))}"
        ),
        (
            "- Evaluation signatures unique / runs executed: "
            f"{_report_count(report_payload.get('evaluation_signatures_unique'))}/"
            f"{_report_count(report_payload.get('evaluation_runs_executed'))}"
        ),
        (
            "- Evaluation results reused in-run/cross-run: "
            f"{_report_count(report_payload.get('evaluation_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('evaluation_results_reused_cross_run'))}"
        ),
        (
            "- Prediction signatures unique / runs executed / reused in-run/cross-run: "
            f"{_report_count(report_payload.get('prediction_signatures_unique'))}/"
            f"{_report_count(report_payload.get('prediction_runs_executed'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_cross_run'))}"
        ),
        (
            "- Split/convert input groups / reuse candidates / safe / blocked: "
            f"{_report_count(report_payload.get('split_convert_input_groups'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_safe_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_blocked_by_prediction_variance'))}"
        ),
        (
            "- Config timeout / failed-config retry limit: "
            f"{('off' if report_payload.get('config_timeout_seconds') is None else str(_report_count(report_payload.get('config_timeout_seconds'))) + 's')}/"
            f"{_report_count(report_payload.get('retry_failed_configs_requested'))}"
        ),
    ]
    cache_root = str(report_payload.get("canonical_alignment_cache_root") or "").strip()
    if cache_root:
        lines.append(f"- Canonical alignment cache root: {cache_root}")

    timing_summary = report_payload.get("timing_summary")
    if isinstance(timing_summary, dict):
        lines.extend(
            [
                (
                    "- Run wall time: "
                    f"{_report_metric(timing_summary.get('run_wall_seconds')):.2f}s"
                ),
                (
                    "- Sum source wall times: "
                    f"{_report_metric(timing_summary.get('source_total_seconds')):.2f}s"
                ),
            ]
        )
        source_average = _report_optional_metric(
            timing_summary.get("source_average_seconds")
        )
        if source_average is not None:
            lines.append(f"- Average source runtime: {source_average:.2f}s")
        config_average = _report_optional_metric(
            timing_summary.get("config_average_seconds")
        )
        if config_average is not None:
            lines.append(f"- Average config runtime: {config_average:.2f}s")
        slowest_source_name = str(timing_summary.get("slowest_source") or "").strip()
        slowest_source_seconds = _report_optional_metric(
            timing_summary.get("slowest_source_seconds")
        )
        if slowest_source_name and slowest_source_seconds is not None:
            lines.append(
                f"- Slowest source: {slowest_source_name} ({slowest_source_seconds:.2f}s)"
            )
        slowest_config_name = str(timing_summary.get("slowest_config") or "").strip()
        slowest_config_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if slowest_config_name and slowest_config_seconds is not None:
            lines.append(
                f"- Slowest config: {slowest_config_name} ({slowest_config_seconds:.2f}s)"
            )
    scheduler_summary = report_payload.get("scheduler_summary")
    if isinstance(scheduler_summary, dict):
        lines.extend(
            [
                (
                    "- Scheduler mode: "
                    f"{scheduler_summary.get('mode', 'fixed')} "
                    f"(sources { _report_count(scheduler_summary.get('source_count'))})"
                ),
                (
                    "- Scheduler effective inflight / split slots / wing target: "
                    f"{_report_count(scheduler_summary.get('effective_inflight_pipelines'))}/"
                    f"{_report_count(scheduler_summary.get('split_phase_slots'))}/"
                    f"{_report_count(scheduler_summary.get('wing_backlog_target'))}"
                ),
                (
                    "- Scheduler eval-tail headroom mode configured/effective: "
                    f"{scheduler_summary.get('eval_tail_headroom_mode', 'auto')} "
                    f"{_report_count(scheduler_summary.get('eval_tail_headroom_configured'))}/"
                    f"{_report_count(scheduler_summary.get('eval_tail_headroom_effective'))}"
                ),
                (
                    "- Scheduler max active during eval: "
                    f"{_report_count(scheduler_summary.get('max_active_during_eval'))}"
                ),
                (
                    "- Scheduler split worker cap per active config (cpu/memory): "
                    f"{_report_count(scheduler_summary.get('split_worker_cap_per_config'))}/"
                    f"{_report_count(scheduler_summary.get('split_worker_cap_by_cpu'))}/"
                    f"{_report_count(scheduler_summary.get('split_worker_cap_by_memory'))}"
                ),
                (
                    "- Scheduler heavy utilization: "
                    f"{_report_metric(scheduler_summary.get('heavy_slot_utilization_pct')):.1f}% "
                    f"(busy {_report_metric(scheduler_summary.get('heavy_slot_busy_seconds')):.2f}s / "
                    f"capacity {_report_metric(scheduler_summary.get('heavy_slot_capacity_seconds')):.2f}s)"
                ),
                (
                    "- Scheduler wing avg/max: "
                    f"{_report_metric(scheduler_summary.get('avg_wing_backlog')):.2f}/"
                    f"{_report_count(scheduler_summary.get('max_wing_backlog'))}"
                ),
                (
                    "- Scheduler heavy idle gap while pending: "
                    f"{_report_metric(scheduler_summary.get('idle_gap_seconds')):.2f}s"
                ),
                (
                    "- Scheduler max active/eval pipelines observed: "
                    f"{_report_count(scheduler_summary.get('max_active_pipelines_observed'))}/"
                    f"{_report_count(scheduler_summary.get('max_eval_active_observed'))}"
                ),
                (
                    "- Scheduler timeout / retry limit: "
                    f"{('off' if scheduler_summary.get('config_timeout_seconds') is None else str(_report_count(scheduler_summary.get('config_timeout_seconds'))) + 's')}/"
                    f"{_report_count(scheduler_summary.get('failed_retry_limit'))}"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Per-Source Results",
            "",
        ]
    )

    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        lines.extend(["- No source runs were recorded.", ""])
    else:
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            source_file = str(row.get("source_file") or "").strip() or "<unknown>"
            if status != "ok":
                lines.append(
                    f"- {source_file}: FAILED ({row.get('error', 'unknown error')})"
                )
                continue
            winner_metrics = row.get("winner_metrics")
            precision = _report_metric(
                winner_metrics.get("precision")
                if isinstance(winner_metrics, dict)
                else None
            )
            recall = _report_metric(
                winner_metrics.get("recall")
                if isinstance(winner_metrics, dict)
                else None
            )
            f1 = _report_metric(
                winner_metrics.get("f1")
                if isinstance(winner_metrics, dict)
                else None
            )
            source_timing = row.get("timing_summary")
            source_timing_suffix = ""
            if isinstance(source_timing, dict):
                source_seconds = _report_optional_metric(
                    source_timing.get("source_wall_seconds")
                )
                slowest_config = str(source_timing.get("slowest_config_dir") or "").strip()
                slowest_seconds = _report_optional_metric(
                    source_timing.get("slowest_config_seconds")
                )
                if source_seconds is not None:
                    source_timing_suffix += f", runtime={source_seconds:.2f}s"
                if slowest_config and slowest_seconds is not None:
                    source_timing_suffix += (
                        f", slowest={slowest_config} ({slowest_seconds:.2f}s)"
                    )
            shard_total = max(1, _report_count(row.get("source_shard_total")))
            if shard_total > 1:
                source_timing_suffix += f", shards={shard_total}"
            lines.append(
                (
                    f"- {source_file}: ok "
                    f"(winner precision={precision:.3f}, "
                    f"recall={recall:.3f}, f1={f1:.3f}{source_timing_suffix}) "
                    f"[report={row.get('report_path', '')}]"
                )
            )
        lines.append("")

    lines.extend(["## Unmatched Gold Exports", ""])
    unmatched_rows = report_payload.get("unmatched")
    if not isinstance(unmatched_rows, list) or not unmatched_rows:
        lines.extend(["- None", ""])
    else:
        for row in unmatched_rows:
            if not isinstance(row, dict):
                continue
            source_hint_text = str(row.get("source_hint") or "none")
            lines.append(
                (
                    f"- {row.get('gold_display', row.get('gold_spans_path', ''))}: "
                    f"{row.get('reason', '')} (source hint: {source_hint_text})"
                )
            )
        lines.append("")

    return "\n".join(lines)


def _write_all_method_source_reports_from_global_rows(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    source_job_plans: list[_AllMethodSourceJobPlan],
    root_output_dir: Path,
    processed_output_root: Path,
    successful_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    eval_signature_cache_dir: Path,
    scheduler_summary: dict[str, Any],
    retry_failed_configs_requested: int,
    retry_passes_executed: int,
    retry_recovered_configs: int,
) -> list[dict[str, Any]]:
    bench_all_method = _bench_all_method_module()
    grouped_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in successful_rows + failed_rows:
        grouped_rows[_report_count(row.get("source_position"))].append(dict(row))

    source_plans_by_position: dict[int, list[_AllMethodSourceJobPlan]] = defaultdict(list)
    for plan in source_job_plans:
        source_plans_by_position[plan.source_position].append(plan)

    source_rows: list[dict[str, Any]] = []
    for source_position, (target, variants) in enumerate(target_variants):
        plan_rows = sorted(
            source_plans_by_position.get(source_position, []),
            key=lambda plan: (plan.shard_index, plan.source_slug),
        )
        source_group_key = (
            plan_rows[0].source_group_key
            if plan_rows
            else slugify_name(target.source_file.stem)
        )
        source_rows_for_position = sorted(
            grouped_rows.get(source_position, []),
            key=lambda row: _report_count(
                row.get("source_config_index", row.get("config_index"))
            ),
        )
        cleaned_rows: list[dict[str, Any]] = []
        for row in source_rows_for_position:
            cleaned = {
                key: value
                for key, value in row.items()
                if not str(key).startswith("_")
            }
            cleaned_rows.append(cleaned)

        successful_source_rows = [
            row
            for row in cleaned_rows
            if str(row.get("status") or "").strip().lower() == "ok"
        ]
        failed_source_rows = [
            row
            for row in cleaned_rows
            if str(row.get("status") or "").strip().lower() != "ok"
        ]
        successful_source_rows.sort(
            key=lambda row: (
                _report_metric(row.get("f1")),
                _report_metric(row.get("practical_f1")),
                _report_metric(row.get("precision")),
                _report_metric(row.get("recall")),
            ),
            reverse=True,
        )
        for rank, row in enumerate(successful_source_rows, start=1):
            row["rank"] = rank
        final_rows = successful_source_rows + failed_source_rows

        evaluation_signatures_unique = len(
            {
                str(row.get("eval_signature") or "").strip()
                for row in successful_source_rows
                if str(row.get("eval_signature") or "").strip()
            }
        )
        evaluation_runs_executed = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "executed"
        )
        evaluation_results_reused_in_run = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "reused_in_run"
        )
        evaluation_results_reused_cross_run = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "reused_cross_run"
        )
        prediction_reuse_summary = bench_all_method._all_method_prediction_reuse_summary(
            successful_source_rows
        )

        successful_timing: list[tuple[dict[str, Any], float]] = []
        for row in successful_source_rows:
            row_timing = _normalize_timing_payload(row.get("timing"))
            row_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if row_total_seconds is None:
                row_total_seconds = _report_optional_metric(row.get("duration_seconds"))
            if row_total_seconds is None:
                continue
            row["timing"] = _timing_with_updates(
                row_timing, total_seconds=row_total_seconds
            )
            successful_timing.append((row, row_total_seconds))

        total_config_seconds = sum(seconds for _row, seconds in successful_timing)
        average_config_seconds = (
            total_config_seconds / len(successful_timing) if successful_timing else None
        )
        median_config_seconds = _median_metric(
            [seconds for _row, seconds in successful_timing]
        )
        slowest_config_row = (
            max(successful_timing, key=lambda item: item[1])[0]
            if successful_timing
            else None
        )
        slowest_config_seconds = (
            max(seconds for _row, seconds in successful_timing)
            if successful_timing
            else None
        )

        source_wall_seconds = _report_metric(
            sum(
                _report_optional_metric(
                    _normalize_timing_payload(row.get("timing")).get(
                        "all_method_prediction_wall_seconds"
                    )
                )
                or 0.0
                for row in final_rows
            )
        )
        if source_wall_seconds <= 0.0:
            source_wall_seconds = total_config_seconds

        winner = successful_source_rows[0] if successful_source_rows else None
        report_payload: dict[str, Any] = {
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "source_file": str(target.source_file),
            "gold_spans_path": str(target.gold_spans_path),
            "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            "variant_count": len(variants),
            "successful_variants": len(successful_source_rows),
            "failed_variants": len(failed_source_rows),
            "evaluation_signatures_unique": evaluation_signatures_unique,
            "evaluation_runs_executed": evaluation_runs_executed,
            "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
            "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
            "prediction_signatures_unique": _report_count(
                prediction_reuse_summary.get("prediction_signatures_unique")
            ),
            "prediction_runs_executed": _report_count(
                prediction_reuse_summary.get("prediction_runs_executed")
            ),
            "prediction_results_reused_in_run": _report_count(
                prediction_reuse_summary.get("prediction_results_reused_in_run")
            ),
            "prediction_results_reused_cross_run": _report_count(
                prediction_reuse_summary.get("prediction_results_reused_cross_run")
            ),
            "split_convert_input_groups": _report_count(
                prediction_reuse_summary.get("split_convert_input_groups")
            ),
            "split_convert_reuse_candidates": _report_count(
                prediction_reuse_summary.get("split_convert_reuse_candidates")
            ),
            "split_convert_reuse_safe_candidates": _report_count(
                prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
            ),
            "split_convert_reuse_blocked_by_prediction_variance": _report_count(
                prediction_reuse_summary.get(
                    "split_convert_reuse_blocked_by_prediction_variance"
                )
            ),
            "prediction_reuse_key_schema_version": (
                ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
            ),
            "split_convert_input_key_schema_version": (
                ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
            ),
            "evaluation_signature_cache_dir": str(eval_signature_cache_dir),
            "retry_failed_configs_requested": retry_failed_configs_requested,
            "retry_passes_executed": retry_passes_executed,
            "retry_recovered_configs": retry_recovered_configs,
            "include_codex_farm_requested": include_codex_farm_requested,
            "include_codex_farm_effective": include_codex_farm_effective,
            "timing_summary": {
                "source_wall_seconds": source_wall_seconds,
                "config_total_seconds": total_config_seconds,
                "config_average_seconds": average_config_seconds,
                "config_median_seconds": median_config_seconds,
                "slowest_config_dir": (
                    str(slowest_config_row.get("config_dir"))
                    if isinstance(slowest_config_row, dict)
                    else None
                ),
                "slowest_config_seconds": slowest_config_seconds,
            },
            "scheduler": dict(scheduler_summary),
            "variants": final_rows,
            "winner_by_f1": winner,
            "scheduler_scope": "global_config_queue",
        }

        source_root = root_output_dir / source_group_key
        source_root.mkdir(parents=True, exist_ok=True)
        report_json_path = source_root / "all_method_benchmark_report.json"
        report_json_path.write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        report_md_path = source_root / "all_method_benchmark_report.md"
        report_md_path.write_text(
            _render_all_method_report_md(report_payload),
            encoding="utf-8",
        )

        source_shard_payload = [
            {
                "status": "ok",
                "source_slug": plan.source_slug,
                "source_shard_index": plan.shard_index + 1,
                "source_shard_total": max(1, _report_count(plan.shard_total)),
                "source_estimated_seconds": plan.estimated_seconds,
                "source_estimate_basis": plan.estimate_basis,
                "variant_count_planned": len(plan.variants),
                "variant_count_completed": len(
                    [
                        row
                        for row in cleaned_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                    ]
                ),
                "variant_count_successful": len(
                    [
                        row
                        for row in successful_source_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                    ]
                ),
                "evaluation_signatures_unique": len(
                    {
                        str(row.get("eval_signature") or "").strip()
                        for row in successful_source_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                        and str(row.get("eval_signature") or "").strip()
                    }
                ),
                "evaluation_runs_executed": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "executed"
                ),
                "evaluation_results_reused_in_run": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "reused_in_run"
                ),
                "evaluation_results_reused_cross_run": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "reused_cross_run"
                ),
                "report_path": _path_for_manifest(root_output_dir, report_md_path) or "",
                "report_json_path": _path_for_manifest(root_output_dir, report_json_path)
                or "",
                "error": "",
                "timing_summary": {},
            }
            for plan in plan_rows
        ]
        error_messages = [
            str(row.get("error") or "").strip()
            for row in failed_source_rows
            if str(row.get("error") or "").strip()
        ]
        winner_metrics = {}
        if isinstance(winner, dict):
            winner_metrics = {
                "precision": _report_metric(winner.get("precision")),
                "recall": _report_metric(winner.get("recall")),
                "f1": _report_metric(winner.get("f1")),
            }
        source_rows.append(
            {
                "status": "ok" if not failed_source_rows else "failed",
                "source_position": source_position,
                "source_group_key": source_group_key,
                "source_shard_index": 1,
                "source_shard_total": max(1, len(plan_rows)),
                "source_estimated_seconds": _report_metric(
                    sum(float(plan.estimated_seconds) for plan in plan_rows)
                ),
                "source_estimate_basis": (
                    "+".join(
                        sorted(
                            {
                                str(plan.estimate_basis).strip()
                                for plan in plan_rows
                                if str(plan.estimate_basis).strip()
                            }
                        )
                    )
                    or "unknown"
                ),
                "source_file": str(target.source_file),
                "source_file_name": target.source_file_name,
                "gold_spans_path": str(target.gold_spans_path),
                "gold_display": target.gold_display,
                "source_slug": source_group_key,
                "report_path": _path_for_manifest(root_output_dir, report_md_path) or "",
                "report_json_path": _path_for_manifest(root_output_dir, report_json_path)
                or "",
                "report_paths": [_path_for_manifest(root_output_dir, report_md_path) or ""],
                "report_json_paths": [
                    _path_for_manifest(root_output_dir, report_json_path) or ""
                ],
                "variant_count_planned": len(variants),
                "variant_count_completed": len(cleaned_rows),
                "variant_count_successful": len(successful_source_rows),
                "evaluation_signatures_unique": evaluation_signatures_unique,
                "evaluation_runs_executed": evaluation_runs_executed,
                "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
                "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
                "prediction_signatures_unique": _report_count(
                    prediction_reuse_summary.get("prediction_signatures_unique")
                ),
                "prediction_runs_executed": _report_count(
                    prediction_reuse_summary.get("prediction_runs_executed")
                ),
                "prediction_results_reused_in_run": _report_count(
                    prediction_reuse_summary.get("prediction_results_reused_in_run")
                ),
                "prediction_results_reused_cross_run": _report_count(
                    prediction_reuse_summary.get("prediction_results_reused_cross_run")
                ),
                "split_convert_input_groups": _report_count(
                    prediction_reuse_summary.get("split_convert_input_groups")
                ),
                "split_convert_reuse_candidates": _report_count(
                    prediction_reuse_summary.get("split_convert_reuse_candidates")
                ),
                "split_convert_reuse_safe_candidates": _report_count(
                    prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
                ),
                "split_convert_reuse_blocked_by_prediction_variance": _report_count(
                    prediction_reuse_summary.get(
                        "split_convert_reuse_blocked_by_prediction_variance"
                    )
                ),
                "winner_metrics": winner_metrics,
                "timing_summary": dict(report_payload.get("timing_summary") or {}),
                "scheduler": dict(scheduler_summary),
                "source_shards": source_shard_payload,
                "error": " | ".join(error_messages),
            }
        )
    _ = processed_output_root
    return source_rows
