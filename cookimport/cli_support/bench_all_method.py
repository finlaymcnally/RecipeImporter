from __future__ import annotations

import importlib
import sys

from cookimport.cli_ui.run_settings_flow import _prompt_codex_shard_plan_menu
from cookimport.core.executor_fallback import preferred_multiprocessing_context

from .command_resolution import resolve_registered_command
from .bench_cache import _json_safe
from .stage import _path_for_manifest, _require_importer

runtime = sys.modules["cookimport.cli_support.bench"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _labelstudio_benchmark_command():
    return resolve_registered_command(
        "cookimport.cli_commands.labelstudio", "labelstudio_benchmark"
    )


def _bench_artifacts_module():
    return importlib.import_module("cookimport.cli_support.bench_artifacts")


def _bench_single_book_module():
    return importlib.import_module("cookimport.cli_support.bench_single_book")


def _benchmark_report_metric_bundle(*args, **kwargs):
    return _bench_single_book_module()._benchmark_report_metric_bundle(*args, **kwargs)


def _load_pred_run_recipe_context(*args, **kwargs):
    return _bench_artifacts_module()._load_pred_run_recipe_context(*args, **kwargs)


def _run_offline_benchmark_prediction_stage(*args, **kwargs):
    return _bench_artifacts_module()._run_offline_benchmark_prediction_stage(
        *args, **kwargs
    )


@dataclass(frozen=True)
class AllMethodTarget:
    gold_spans_path: Path
    source_file: Path
    source_file_name: str
    gold_display: str


@dataclass(frozen=True)
class AllMethodUnmatchedGold:
    gold_spans_path: Path
    reason: str
    source_hint: str | None
    gold_display: str


@dataclass(frozen=True)
class AllMethodVariant:
    slug: str
    run_settings: RunSettings
    dimensions: dict[str, Any]


@dataclass(frozen=True)
class _AllMethodSourceEstimate:
    estimated_seconds: float
    estimate_basis: str
    canonical_text_chars: int
    variant_count: int


@dataclass(frozen=True)
class _AllMethodSourceJobPlan:
    source_position: int
    source_group_key: str
    source_display_name: str
    source_slug: str
    source_file: Path
    gold_spans_path: Path
    variants: list[AllMethodVariant]
    shard_index: int
    shard_total: int
    estimated_seconds: float
    estimate_basis: str


@dataclass(frozen=True)
class _AllMethodGlobalWorkItem:
    global_dispatch_index: int
    source_position: int
    source_group_key: str
    source_slug: str
    source_file: Path
    source_file_name: str
    gold_spans_path: Path
    source_root: Path
    source_processed_root: Path
    canonical_alignment_cache_dir: Path
    config_index: int
    config_total: int
    source_shard_index: int
    source_shard_total: int
    source_estimated_seconds: float
    source_estimate_basis: str
    variant: AllMethodVariant


def _canonical_text_chars_for_all_method_target(target: AllMethodTarget) -> int:
    canonical_text_path = target.gold_spans_path.parent / "canonical_text.txt"
    if not canonical_text_path.exists() or not canonical_text_path.is_file():
        return 0
    try:
        return max(0, int(canonical_text_path.stat().st_size))
    except OSError:
        return 0


def _load_prior_all_method_source_runtime_seconds(
    *,
    prior_report_root: Path | None,
    target: AllMethodTarget,
) -> tuple[float | None, int | None]:
    if prior_report_root is None:
        return None, None
    report_path = prior_report_root / "all_method_benchmark_multi_source_report.json"
    if not report_path.exists() or not report_path.is_file():
        return None, None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(payload, dict):
        return None, None
    source_rows = payload.get("sources")
    if not isinstance(source_rows, list):
        return None, None
    source_path = str(target.source_file)
    source_name = target.source_file_name
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        row_source_path = str(row.get("source_file") or "").strip()
        row_source_name = str(row.get("source_file_name") or "").strip()
        if row_source_path != source_path and row_source_name != source_name:
            continue
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is None or source_seconds <= 0:
            continue
        prior_variants = _report_count(row.get("variant_count_completed"))
        return source_seconds, (prior_variants if prior_variants > 0 else None)
    return None, None


def _estimate_all_method_source_cost(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    prior_report_root: Path | None = None,
) -> _AllMethodSourceEstimate:
    variant_count = max(0, len(variants))
    canonical_text_chars = _canonical_text_chars_for_all_method_target(target)
    heuristic_seconds = max(
        1.0,
        (float(max(1, variant_count)) * 25.0) + (float(canonical_text_chars) / 1200.0),
    )
    prior_seconds, prior_variant_count = _load_prior_all_method_source_runtime_seconds(
        prior_report_root=prior_report_root,
        target=target,
    )
    if prior_seconds is not None:
        scale = 1.0
        if prior_variant_count is not None and prior_variant_count > 0 and variant_count > 0:
            scale = max(0.25, float(variant_count) / float(prior_variant_count))
        estimated = max(1.0, float(prior_seconds) * scale)
        basis = "prior_source_wall_seconds"
        if canonical_text_chars > 0:
            basis += "+canonical_text_chars"
        return _AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis=basis,
            canonical_text_chars=canonical_text_chars,
            variant_count=variant_count,
        )

    basis = "heuristic_variants"
    if canonical_text_chars > 0:
        basis += "+canonical_text_chars"
    return _AllMethodSourceEstimate(
        estimated_seconds=heuristic_seconds,
        estimate_basis=basis,
        canonical_text_chars=canonical_text_chars,
        variant_count=variant_count,
    )


def _split_all_method_source_variants(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    estimate: _AllMethodSourceEstimate,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[list[AllMethodVariant]]:
    _ = target
    if not variants:
        return [[]]
    total_variants = len(variants)
    threshold = max(1.0, float(shard_threshold_seconds))
    max_parts = max(1, _report_count(shard_max_parts))
    min_variants = max(1, _report_count(shard_min_variants))
    if max_parts <= 1:
        return [list(variants)]
    if total_variants < min_variants:
        return [list(variants)]
    if estimate.estimated_seconds < threshold:
        return [list(variants)]

    max_parts_by_variants = total_variants // min_variants
    if max_parts_by_variants < 2:
        return [list(variants)]
    shard_total = min(max_parts, max_parts_by_variants)
    if shard_total < 2:
        return [list(variants)]

    shards: list[list[AllMethodVariant]] = []
    base_size = total_variants // shard_total
    remainder = total_variants % shard_total
    cursor = 0
    for shard_index in range(shard_total):
        shard_size = base_size + (1 if shard_index < remainder else 0)
        next_cursor = cursor + shard_size
        shards.append(list(variants[cursor:next_cursor]))
        cursor = next_cursor
    if len(shards) <= 1:
        return [list(variants)]
    return shards


def _tail_pair_all_method_source_jobs(
    plans: list[_AllMethodSourceJobPlan],
) -> list[_AllMethodSourceJobPlan]:
    if len(plans) <= 2:
        return list(plans)
    ranked = sorted(
        plans,
        key=lambda plan: (
            -plan.estimated_seconds,
            plan.source_position,
            plan.shard_index,
            plan.source_slug,
        ),
    )
    left = 0
    right = len(ranked) - 1
    paired: list[_AllMethodSourceJobPlan] = []
    while left <= right:
        paired.append(ranked[left])
        left += 1
        if left <= right:
            paired.append(ranked[right])
            right -= 1
    return paired


def _plan_all_method_source_jobs(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[_AllMethodSourceJobPlan]:
    resolved_strategy = _normalize_all_method_source_scheduling(scheduling_strategy)
    resolved_shard_threshold_seconds = max(1.0, float(shard_threshold_seconds))
    resolved_shard_max_parts = max(1, _report_count(shard_max_parts))
    resolved_shard_min_variants = max(1, _report_count(shard_min_variants))

    slug_counts: dict[str, int] = {}
    plans: list[_AllMethodSourceJobPlan] = []
    for source_position, (target, variants) in enumerate(target_variants):
        estimate = _estimate_all_method_source_cost(
            target=target,
            variants=variants,
        )
        source_slug_base = slugify_name(target.source_file.stem)
        source_slug_count = slug_counts.get(source_slug_base, 0) + 1
        slug_counts[source_slug_base] = source_slug_count
        source_group_slug = (
            source_slug_base
            if source_slug_count == 1
            else f"{source_slug_base}__{source_slug_count:02d}"
        )
        shard_variants = _split_all_method_source_variants(
            target=target,
            variants=variants,
            estimate=estimate,
            shard_threshold_seconds=resolved_shard_threshold_seconds,
            shard_max_parts=resolved_shard_max_parts,
            shard_min_variants=resolved_shard_min_variants,
        )
        shard_total = max(1, len(shard_variants))
        for shard_index, shard in enumerate(shard_variants):
            shard_slug = (
                source_group_slug
                if shard_total == 1
                else (
                    f"{source_group_slug}__part_{shard_index + 1:02d}_of_{shard_total:02d}"
                )
            )
            shard_weight = (
                float(len(shard)) / float(len(variants))
                if variants
                else (1.0 / float(shard_total))
            )
            shard_estimated_seconds = max(
                1.0,
                float(estimate.estimated_seconds) * max(0.05, shard_weight),
            )
            plans.append(
                _AllMethodSourceJobPlan(
                    source_position=source_position,
                    source_group_key=source_group_slug,
                    source_display_name=target.source_file_name,
                    source_slug=shard_slug,
                    source_file=target.source_file,
                    gold_spans_path=target.gold_spans_path,
                    variants=list(shard),
                    shard_index=shard_index,
                    shard_total=shard_total,
                    estimated_seconds=shard_estimated_seconds,
                    estimate_basis=estimate.estimate_basis,
                )
            )

    if resolved_strategy == ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR:
        return _tail_pair_all_method_source_jobs(plans)
    return list(plans)


def _plan_all_method_global_work_items(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
    root_output_dir: Path,
    processed_output_root: Path,
    canonical_alignment_cache_root: Path,
) -> list[_AllMethodGlobalWorkItem]:
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=scheduling_strategy,
        shard_threshold_seconds=shard_threshold_seconds,
        shard_max_parts=shard_max_parts,
        shard_min_variants=shard_min_variants,
    )
    source_target_by_position: dict[int, AllMethodTarget] = {
        source_position: target
        for source_position, (target, _variants) in enumerate(target_variants)
    }
    source_config_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_next_config_index: dict[int, int] = defaultdict(int)
    resolved_cache_root = canonical_alignment_cache_root.expanduser()

    work_items: list[_AllMethodGlobalWorkItem] = []
    global_dispatch_index = 0
    for plan in source_job_plans:
        source_target = source_target_by_position[plan.source_position]
        source_root = root_output_dir / plan.source_group_key
        source_processed_root = processed_output_root / plan.source_group_key
        canonical_alignment_cache_dir = resolved_cache_root / plan.source_group_key
        source_config_total = max(
            0,
            _report_count(source_config_totals.get(plan.source_position)),
        )
        for variant in plan.variants:
            global_dispatch_index += 1
            source_config_index = source_next_config_index[plan.source_position] + 1
            source_next_config_index[plan.source_position] = source_config_index
            work_items.append(
                _AllMethodGlobalWorkItem(
                    global_dispatch_index=global_dispatch_index,
                    source_position=plan.source_position,
                    source_group_key=plan.source_group_key,
                    source_slug=plan.source_slug,
                    source_file=plan.source_file,
                    source_file_name=source_target.source_file_name,
                    gold_spans_path=plan.gold_spans_path,
                    source_root=source_root,
                    source_processed_root=source_processed_root,
                    canonical_alignment_cache_dir=canonical_alignment_cache_dir,
                    config_index=source_config_index,
                    config_total=source_config_total,
                    source_shard_index=plan.shard_index,
                    source_shard_total=plan.shard_total,
                    source_estimated_seconds=plan.estimated_seconds,
                    source_estimate_basis=plan.estimate_basis,
                    variant=variant,
                )
            )
    return work_items


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
    _core: ProgressDashboardCore = field(default_factory=ProgressDashboardCore, repr=False, compare=False)
    active_config_slugs_by_source: dict[int, dict[int, str]] = field(default_factory=dict)
    active_config_phases_by_source: dict[int, dict[int, str]] = field(default_factory=dict)
    task_message: str = ""
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

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

def _prune_empty_dirs(start: Path, *, stop_exclusive: Path | None = None) -> None:
    """Best-effort cleanup of empty directories after moving benchmark artifacts."""
    current = start
    while True:
        if stop_exclusive is not None and current == stop_exclusive:
            break
        try:
            current.rmdir()
        except OSError:
            break
        if current.parent == current:
            break
        current = current.parent


def _display_gold_export_path(path: Path, output_dir: Path) -> str:
    # Keep interactive gold selection readable: prefer the book folder name
    # over the full pulled-from-labelstudio relative path.
    if path.parent.name == "exports" and path.parent.parent.name:
        return path.parent.parent.name
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _display_benchmark_target_name(
    *,
    gold_display: str | None,
    source_file_name: str | None,
) -> str:
    concise_gold_display = str(gold_display or "").strip()
    if concise_gold_display:
        return concise_gold_display
    source_name = str(source_file_name or "").strip()
    if source_name:
        return Path(source_name).stem or source_name
    return "benchmark-target"


def _display_prediction_run_path(path: Path, output_dir: Path) -> str:
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)

def _resolve_all_method_targets(
    output_dir: Path,
) -> tuple[list[AllMethodTarget], list[AllMethodUnmatchedGold]]:
    from cookimport.bench.speed_suite import (
        match_gold_exports_to_inputs,
        resolve_repo_path,
    )

    candidates = _discover_freeform_gold_exports(output_dir)
    matched_rows, unmatched_rows = match_gold_exports_to_inputs(
        candidates,
        input_root=DEFAULT_INPUT,
        gold_root=output_dir,
        importable_files=_list_importable_files(DEFAULT_INPUT),
    )

    matched_targets = [
        AllMethodTarget(
            gold_spans_path=resolve_repo_path(
                row.gold_spans_path, repo_root=REPO_ROOT
            ),
            source_file=resolve_repo_path(row.source_file, repo_root=REPO_ROOT),
            source_file_name=Path(row.source_file).name,
            gold_display=_display_gold_export_path(
                resolve_repo_path(row.gold_spans_path, repo_root=REPO_ROOT),
                output_dir,
            ),
        )
        for row in matched_rows
    ]

    unmatched_targets: list[AllMethodUnmatchedGold] = []
    for row in unmatched_rows:
        gold_spans_raw = str(row.get("gold_spans_path") or "").strip()
        if not gold_spans_raw:
            continue
        gold_spans_path = resolve_repo_path(gold_spans_raw, repo_root=REPO_ROOT)
        source_hint_raw = row.get("source_hint")
        source_hint = (
            str(source_hint_raw).strip() if source_hint_raw is not None else None
        )
        if source_hint == "":
            source_hint = None
        unmatched_targets.append(
            AllMethodUnmatchedGold(
                gold_spans_path=gold_spans_path,
                reason=str(row.get("reason") or "Unmatched gold export."),
                source_hint=source_hint,
                gold_display=str(
                    row.get("gold_display")
                    or _display_gold_export_path(gold_spans_path, output_dir)
                ),
            )
        )

    return matched_targets, unmatched_targets


def _resolve_benchmark_gold_and_source(
    *,
    gold_spans: Path | None,
    source_file: Path | None,
    output_dir: Path,
    allow_cancel: bool = False,
) -> tuple[Path, Path] | None:
    def _abort(message: str) -> tuple[Path, Path] | None:
        if allow_cancel:
            typer.secho(message, fg=typer.colors.YELLOW)
            return None
        _fail(message)
        return None

    selected_gold = gold_spans
    if selected_gold is None:
        candidates = _discover_freeform_gold_exports(output_dir)
        if not candidates:
            return _abort(
                "No freeform gold exports found. Run `cookimport labelstudio-export` first."
            )
        selected_gold = _menu_select(
            "Select a freeform gold export:",
            menu_help=(
                "Choose the labeled freeform export to benchmark against. "
                "Newest exports are listed first."
            ),
            choices=[
                questionary.Choice(
                    _display_gold_export_path(path, output_dir),
                    value=path,
                )
                for path in candidates[:30]
            ],
        )
        if selected_gold in {None, BACK_ACTION}:
            return _abort("Benchmark cancelled.")
    if isinstance(selected_gold, str):
        selected_gold = Path(selected_gold)
    if not isinstance(selected_gold, Path):
        return _abort("Benchmark cancelled.")
    if not selected_gold.exists():
        return _abort(f"Gold spans file not found: {selected_gold}")

    selected_source = source_file
    inferred_source = None
    if selected_source is None:
        inferred_source = _infer_source_file_from_freeform_gold(selected_gold)
    if selected_source is None and inferred_source is not None:
        selected_source = inferred_source
    if selected_source is None:
        importable_files = _list_importable_files(DEFAULT_INPUT)
        if importable_files:
            source_choice = _menu_select(
                "Select source file to benchmark:",
                menu_help=(
                    "Choose the source file used to generate prediction tasks "
                    "for comparison to the selected gold export."
                ),
                choices=[
                    *[questionary.Choice(path.name, value=path) for path in importable_files],
                    questionary.Choice("Enter a custom path", value="custom"),
                ],
            )
            if source_choice in {None, BACK_ACTION}:
                return _abort("Benchmark cancelled.")
            if source_choice == "custom":
                source_path = _prompt_text("Enter source file path:")
                if not source_path:
                    return _abort("Benchmark cancelled.")
                selected_source = Path(source_path)
            else:
                selected_source = source_choice
        else:
            source_path = _prompt_text("Enter source file path:")
            if not source_path:
                return _abort("Benchmark cancelled.")
            selected_source = Path(source_path)
    if not selected_source.exists() or not selected_source.is_file():
        return _abort(f"Source file not found: {selected_source}")
    try:
        _require_importer(selected_source)
    except typer.Exit:
        if allow_cancel:
            return None
        raise

    return selected_gold, selected_source


def _all_method_variant_token(value: str | bool) -> str:
    if isinstance(value, bool):
        raw_value = "true" if value else "false"
    else:
        raw_value = str(value).strip().lower()
    token = raw_value.replace("-", "_")
    token = re.sub(r"[^a-z0-9_]+", "_", token)
    token = token.strip("_")
    return token or "na"


def _all_method_is_schema_like_json_source(source_file: Path) -> bool:
    try:
        if not source_file.exists() or not source_file.is_file():
            return False
        with source_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False

    if isinstance(payload, dict):
        recipes = payload.get("recipes")
        if isinstance(recipes, list) and recipes:
            recipe_like = 0
            for item in recipes:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type") or "").lower()
                if "recipe" in item_type:
                    recipe_like += 1
            if recipe_like > 0:
                return False

    return bool(collect_schemaorg_recipe_objects(payload))


def _all_method_optional_module_available(module_name: str) -> bool:
    try:
        import importlib

        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_all_method_sweep_payloads(
    *,
    base_payload: dict[str, Any],
    include_deterministic_sweeps: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """Return (sweep_tag, payload) rows for all-method benchmark runs.

    Strategy: baseline + one-at-a-time sweeps + one combined "all_upgrades" payload.
    This exercises new deterministic knobs without a factorial explosion.
    """

    def _normalized(value: Any, default: str) -> str:
        cleaned = str(value if value is not None else default).strip().lower()
        return cleaned or default

    rows: list[tuple[str, dict[str, Any]]] = [("base", dict(base_payload))]
    if not include_deterministic_sweeps:
        return rows

    pysbd_ok = _all_method_optional_module_available("pysbd")
    quantulum_ok = _all_method_optional_module_available("quantulum3")
    pint_ok = _all_method_optional_module_available("pint")

    def add_one_at_a_time(
        *,
        key: str,
        values: Iterable[str],
        default: str,
        require: bool = True,
    ) -> None:
        if not require:
            return
        base_value = _normalized(base_payload.get(key), default)
        for value in values:
            normalized = _normalized(value, default)
            if normalized == base_value:
                continue
            payload = dict(base_payload)
            payload[key] = normalized
            rows.append((f"{key}={normalized}", payload))

    # Priority 2–6 deterministic knobs (non-LLM).
    add_one_at_a_time(
        key="multi_recipe_splitter",
        values=("off", "rules_v1"),
        default="rules_v1",
    )
    add_one_at_a_time(
        key="ingredient_missing_unit_policy",
        values=("null", "medium", "each"),
        default="null",
    )
    add_one_at_a_time(
        key="p6_yield_mode",
        values=("scored_v1",),
        default="scored_v1",
    )
    add_one_at_a_time(
        key="p6_time_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_unit_backend",
        values=("builtin_v1", "pint_v1"),
        default="builtin_v1",
        require=pint_ok,
    )

    upgrades: dict[str, str] = {
        "multi_recipe_splitter": "rules_v1",
        "ingredient_missing_unit_policy": "each",
        "p6_yield_mode": "scored_v1",
    }
    if quantulum_ok:
        upgrades["p6_time_backend"] = "hybrid_regex_quantulum3_v1"
        upgrades["p6_temperature_backend"] = "hybrid_regex_quantulum3_v1"
    if pint_ok:
        upgrades["p6_temperature_unit_backend"] = "pint_v1"

    combined = dict(base_payload)
    combined.update(upgrades)
    if combined != base_payload:
        rows.append(("all_upgrades", combined))

    return rows


def _build_all_method_variants(
    *,
    base_settings: RunSettings,
    source_file: Path,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[AllMethodVariant]:
    base_payload = _all_method_apply_baseline_contract(
        base_settings.to_run_config_dict()
    )
    variants: list[AllMethodVariant] = []
    source_ext = source_file.suffix.lower()

    webschema_source = source_ext in {".html", ".htm", ".jsonld"} or (
        source_ext == ".json" and _all_method_is_schema_like_json_source(source_file)
    )

    sweep_payloads = _build_all_method_sweep_payloads(
        base_payload=dict(base_payload),
        include_deterministic_sweeps=include_deterministic_sweeps,
    )
    dedupe_hashes: set[str] = set()

    def add_variant(
        *,
        slug: str,
        payload: dict[str, Any],
        dimensions: dict[str, Any],
        sweep_tag: str,
        apply_baseline_contract: bool = False,
    ) -> None:
        normalized_payload = (
            _all_method_apply_baseline_contract(payload)
            if apply_baseline_contract
            else dict(payload)
        )
        run_settings_payload = {
            key: value
            for key, value in normalized_payload.items()
            if key in RunSettings.model_fields
        }
        run_settings = RunSettings.from_dict(
            run_settings_payload,
            warn_context="all-method variant",
        )
        stable_hash = run_settings.stable_hash()
        if stable_hash in dedupe_hashes:
            return
        dedupe_hashes.add(stable_hash)
        if sweep_tag != "base":
            dimensions = dict(dimensions)
            dimensions["deterministic_sweep"] = sweep_tag
        variants.append(
            AllMethodVariant(
                slug=slug,
                run_settings=run_settings,
                dimensions=dimensions,
            )
        )
        if include_codex_farm:
            current_llm = str(
                normalized_payload.get("llm_recipe_pipeline") or "off"
            ).strip().lower()
            if current_llm == "off":
                if codex_variant_settings is None:
                    codex_payload = _all_method_apply_codex_contract_from_baseline(
                        normalized_payload
                    )
                    codex_slug_parts = [
                        "llm_recipe_"
                        + _all_method_variant_token(
                            RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                        )
                    ]
                    codex_dimensions = dict(dimensions)
                    codex_dimensions["llm_recipe_pipeline"] = (
                        RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                    )
                    codex_dimensions["line_role_pipeline"] = LINE_ROLE_PIPELINE_ROUTE_V2
                    codex_dimensions["llm_knowledge_pipeline"] = (
                        KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2
                    )
                    codex_dimensions["atomic_block_splitter"] = str(
                        codex_payload.get("atomic_block_splitter") or "off"
                    )
                else:
                    codex_slug_parts = _all_method_codex_surface_slug_parts(
                        codex_variant_settings
                    )
                    if not codex_slug_parts:
                        return
                    codex_payload = _all_method_apply_selected_codex_contract_from_baseline(
                        normalized_payload,
                        codex_variant_settings=codex_variant_settings,
                    )
                    codex_dimensions = dict(dimensions)
                    if codex_variant_settings.llm_recipe_pipeline.value != "off":
                        codex_dimensions["llm_recipe_pipeline"] = (
                            codex_variant_settings.llm_recipe_pipeline.value
                        )
                    if (
                        codex_variant_settings.line_role_pipeline.value
                        == LINE_ROLE_PIPELINE_ROUTE_V2
                    ):
                        codex_dimensions["line_role_pipeline"] = (
                            codex_variant_settings.line_role_pipeline.value
                        )
                    if codex_variant_settings.llm_knowledge_pipeline.value != "off":
                        codex_dimensions["llm_knowledge_pipeline"] = (
                            codex_variant_settings.llm_knowledge_pipeline.value
                        )
                    codex_dimensions["atomic_block_splitter"] = (
                        codex_variant_settings.atomic_block_splitter.value
                    )
                add_variant(
                    slug=f"{slug}__{'__'.join(codex_slug_parts)}",
                    payload=codex_payload,
                    dimensions=codex_dimensions,
                    sweep_tag=sweep_tag,
                    apply_baseline_contract=False,
                )

    def base_dimensions(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "multi_recipe_splitter": str(payload.get("multi_recipe_splitter", "rules_v1")),
            "ingredient_missing_unit_policy": str(payload.get("ingredient_missing_unit_policy", "null")),
            "p6_time_backend": str(payload.get("p6_time_backend", "regex_v1")),
            "p6_temperature_backend": str(payload.get("p6_temperature_backend", "regex_v1")),
            "p6_temperature_unit_backend": str(
                payload.get("p6_temperature_unit_backend", "builtin_v1")
            ),
            "p6_yield_mode": str(payload.get("p6_yield_mode", "scored_v1")),
            "pdf_ocr_policy": str(payload.get("pdf_ocr_policy", "auto")),
            "pdf_column_gap_ratio": float(payload.get("pdf_column_gap_ratio", 0.12)),
        }

    if source_ext != ".epub" and not webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
            multi_recipe = str(payload.get("multi_recipe_splitter") or "rules_v1").strip().lower()
            multi_recipe_suffix = (
                ""
                if multi_recipe in {"", "rules_v1"}
                else f"__multi_recipe_{_all_method_variant_token(multi_recipe)}"
            )
            add_variant(
                slug=(
                    f"source_{_all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                    f"{multi_recipe_suffix}"
                    f"{suffix}"
                ),
                payload=payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "source_extension": source_ext or "none",
                    **base_dimensions(payload),
                },
            )
        return variants

    if webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
            for schema_policy in ALL_METHOD_WEBSCHEMA_POLICIES:
                next_payload = dict(payload)
                next_payload["web_schema_policy"] = schema_policy
                add_variant(
                    slug=(
                        f"source_{_all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                        f"__webschema_policy_{_all_method_variant_token(schema_policy)}"
                        f"{suffix}"
                    ),
                    payload=next_payload,
                    sweep_tag=sweep_tag,
                    dimensions={
                        "source_extension": source_ext or "none",
                        "web_schema_policy": schema_policy,
                        **base_dimensions(next_payload),
                    },
                )
        return variants

    extractors = ALL_METHOD_EPUB_EXTRACTORS_DEFAULT
    if include_markdown_extractors:
        extractors = (
            *ALL_METHOD_EPUB_EXTRACTORS_DEFAULT,
            *ALL_METHOD_EPUB_EXTRACTORS_MARKDOWN_OPTIONAL,
        )

    for sweep_tag, payload in sweep_payloads:
        suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
        for extractor in extractors:
            if extractor == "unstructured":
                for parser_version, skip_headers_footers, preprocess_mode in product(
                    ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS,
                    ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS,
                    ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES,
                ):
                    next_payload = dict(payload)
                    next_payload.update(
                        {
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                        }
                    )
                    add_variant(
                        slug=(
                            f"extractor_{_all_method_variant_token(extractor)}"
                            f"__parser_{_all_method_variant_token(parser_version)}"
                            f"__skiphf_{_all_method_variant_token(skip_headers_footers)}"
                            f"__pre_{_all_method_variant_token(preprocess_mode)}"
                            f"{suffix}"
                        ),
                        payload=next_payload,
                        sweep_tag=sweep_tag,
                        dimensions={
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                            **base_dimensions(next_payload),
                        },
                    )
                continue

            next_payload = dict(payload)
            next_payload["epub_extractor"] = extractor
            add_variant(
                slug=f"extractor_{_all_method_variant_token(extractor)}{suffix}",
                payload=next_payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "epub_extractor": extractor,
                    **base_dimensions(next_payload),
                },
            )

    return variants


def _build_all_method_target_variants(
    *,
    targets: list[AllMethodTarget],
    base_settings: RunSettings,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[tuple[AllMethodTarget, list[AllMethodVariant]]]:
    return [
        (
            target,
            _build_all_method_variants(
                base_settings=base_settings,
                source_file=target.source_file,
                include_codex_farm=include_codex_farm,
                codex_variant_settings=codex_variant_settings,
                include_markdown_extractors=include_markdown_extractors,
                include_deterministic_sweeps=include_deterministic_sweeps,
            ),
        )
        for target in targets
    ]


def _resolve_all_method_codex_choice(include_codex_farm: bool) -> tuple[bool, str | None]:
    if not include_codex_farm:
        return False, None
    return True, None


def _normalize_compare_control_path_prefix(value: str | Path | None) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text == "/":
        return text
    return text.rstrip("/")


def _qualitysuite_compare_control_prefixes_for_path(path: Path) -> list[str]:
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        candidate = candidate

    prefixes: list[str] = []
    seen: set[str] = set()

    def _add(raw_value: str | Path | None) -> None:
        normalized = _normalize_compare_control_path_prefix(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        prefixes.append(normalized)

    _add(candidate)
    try:
        _add(candidate.relative_to(REPO_ROOT))
    except ValueError:
        pass
    return prefixes


def _qualitysuite_compare_control_filters_for_prefixes(
    prefixes: list[str],
) -> dict[str, Any]:
    clauses = [
        {"operator": "starts_with", "value": value}
        for value in prefixes
        if str(value or "").strip()
    ]
    filters: dict[str, Any] = {
        "quick_filters": {
            "official_full_golden_only": False,
            "exclude_ai_tests": False,
        },
    }
    if clauses:
        filters["column_filter_global_mode"] = "and"
        filters["column_filters"] = {
            "artifact_dir": {
                "mode": "or",
                "clauses": clauses,
            }
        }
    return filters


def _write_qualitysuite_agent_bridge_readme(
    *,
    bundle_dir: Path,
    index_file: Path,
    requests_file: Path,
    output_root: Path,
    golden_root: Path,
    scope_count: int,
    request_count: int,
) -> None:
    output_root_quoted = shlex.quote(str(output_root))
    golden_root_quoted = shlex.quote(str(golden_root))
    requests_file_quoted = shlex.quote(requests_file.name)
    lines = [
        "# Agent Compare-Control Bridge",
        "",
        "This folder links QualitySuite outputs to Compare & Control insights for AI-agent loops.",
        "",
        f"- Index: `{index_file.name}`",
        f"- Ready requests (JSONL): `{requests_file.name}`",
        f"- Scopes: `{scope_count}`",
        f"- Prepared agent requests: `{request_count}`",
        "",
        "Recommended agent flow:",
        "1. Read `qualitysuite_compare_control_index.json` and pick one scope/outcome insight file.",
        "2. If you need deeper drill-down, run the prepared JSONL requests through `compare-control agent`.",
        "3. Map responses back using each request `meta` payload (`scope_id`, `outcome_field`, `label`).",
        "",
    ]
    if request_count > 0:
        lines.extend(
            [
                "Run the prepared requests:",
                "```bash",
                (
                    "cookimport compare-control agent "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} \\"
                ),
                f"  < {requests_file_quoted} > agent_responses.jsonl",
                "```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No follow-up requests were generated. You can still run direct insights manually:",
                "```bash",
                (
                    "cookimport compare-control run --action insights "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} "
                    "--outcome-field strict_accuracy"
                ),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            (
                "Tip: Requests include `meta` tags (`scope_id`, `outcome_field`, `label`) "
                "so agents can route responses back to the right QualitySuite scope."
            ),
            "",
        ]
    )
    (bundle_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_qualitysuite_agent_bridge_bundle(
    *,
    bundle_dir: Path,
    bundle_type: str,
    scopes: list[dict[str, Any]],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
    extra_index: dict[str, Any] | None = None,
) -> tuple[Path | None, str | None]:
    from cookimport.analytics import compare_control_engine as engine

    try:
        records = engine.load_dashboard_records(
            output_root=output_root,
            golden_root=golden_root,
            since_days=since_days,
            scan_reports=False,
            scan_benchmark_reports=False,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Unable to load compare-control records: {exc}"

    bundle_dir.mkdir(parents=True, exist_ok=True)
    index_payload: dict[str, Any] = {
        "schema_version": QUALITYSUITE_AGENT_BRIDGE_SCHEMA_VERSION,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "bundle_type": bundle_type,
        "output_root": str(output_root),
        "golden_root": str(golden_root),
        "since_days": since_days,
        "records_loaded": len(records),
        "outcome_fields": list(QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS),
        "scopes": [],
    }
    if isinstance(extra_index, dict) and extra_index:
        index_payload.update(extra_index)

    request_rows: list[dict[str, Any]] = []

    for scope in scopes:
        scope_id = str(scope.get("scope_id") or "").strip()
        scope_label = str(scope.get("scope_label") or scope_id).strip() or scope_id
        if not scope_id:
            continue
        prefixes = [
            _normalize_compare_control_path_prefix(value)
            for value in (scope.get("path_prefixes") or [])
        ]
        prefixes = [value for value in prefixes if value]
        scope_entry: dict[str, Any] = {
            "scope_id": scope_id,
            "scope_label": scope_label,
            "path_prefixes": prefixes,
            "insights": [],
        }
        if isinstance(scope.get("metadata"), dict):
            scope_entry["metadata"] = dict(scope["metadata"])

        for outcome_field in QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS:
            query = {
                "outcome_field": outcome_field,
                "filters": _qualitysuite_compare_control_filters_for_prefixes(prefixes),
            }
            file_name = f"{scope_id}__{outcome_field}.json"
            insight_path = bundle_dir / file_name
            try:
                insight_payload = engine.generate_insights(records, query)
                wrapped = engine.success_payload(insight_payload)
                insight_path.write_text(
                    json.dumps(wrapped, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

                candidate_rows = int(insight_payload.get("candidate_rows") or 0)
                compare_field = str(insight_payload.get("compare_field") or "")
                highlights = insight_payload.get("highlights")
                highlight_count = len(highlights) if isinstance(highlights, list) else 0
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "candidate_rows": candidate_rows,
                        "compare_field": compare_field,
                        "highlight_count": highlight_count,
                    }
                )

                suggested_queries = insight_payload.get("suggested_queries")
                if isinstance(suggested_queries, list):
                    for query_index, item in enumerate(suggested_queries, start=1):
                        if not isinstance(item, dict):
                            continue
                        action = str(item.get("action") or "").strip().lower()
                        payload = item.get("payload")
                        if not action or not isinstance(payload, dict):
                            continue
                        request_rows.append(
                            {
                                "id": f"{scope_id}-{outcome_field}-{query_index}",
                                "action": action,
                                "payload": payload,
                                "meta": {
                                    "scope_id": scope_id,
                                    "outcome_field": outcome_field,
                                    "label": str(item.get("label") or "").strip(),
                                },
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                error_payload = engine.error_payload(
                    "qualitysuite_agent_bridge_insight_failed",
                    "Unable to generate insights for scope/outcome.",
                    {
                        "scope_id": scope_id,
                        "outcome_field": outcome_field,
                        "error": str(exc),
                    },
                )
                insight_path.write_text(
                    json.dumps(error_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "error": str(exc),
                    }
                )

        index_payload["scopes"].append(scope_entry)

    requests_file = bundle_dir / "agent_requests.jsonl"
    if request_rows:
        requests_file.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in request_rows) + "\n",
            encoding="utf-8",
        )
    else:
        requests_file.write_text("", encoding="utf-8")
    index_payload["agent_request_count"] = len(request_rows)
    index_payload["agent_requests_jsonl"] = requests_file.name
    index_file_name = "qualitysuite_compare_control_index.json"
    index_payload["agent_handoff"] = {
        "recommended_entrypoint": index_file_name,
        "recommended_flow": [
            "read_index",
            "inspect_scope_insights",
            "run_agent_requests_jsonl",
        ],
    }

    index_file = bundle_dir / index_file_name
    index_file.write_text(
        json.dumps(index_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_qualitysuite_agent_bridge_readme(
        bundle_dir=bundle_dir,
        index_file=index_file,
        requests_file=requests_file,
        output_root=output_root,
        golden_root=golden_root,
        scope_count=len(index_payload["scopes"]),
        request_count=len(request_rows),
    )
    return bundle_dir, None


def _write_qualitysuite_agent_bridge_bundle_for_run(
    *,
    run_root: Path,
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    summary_payload: dict[str, Any] = {}
    summary_path = run_root / "summary.json"
    if summary_path.exists():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary_payload = loaded
        except Exception:
            summary_payload = {}

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "run_overall",
            "scope_label": "Quality run overall",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(run_root),
            "metadata": {
                "run_root": str(run_root),
            },
        }
    ]
    experiments = summary_payload.get("experiments")
    if isinstance(experiments, list):
        for row in experiments:
            if not isinstance(row, dict):
                continue
            experiment_id = str(row.get("id") or "").strip()
            if not experiment_id:
                continue
            experiment_root = run_root / "experiments" / experiment_id
            target_path = experiment_root if experiment_root.exists() else run_root
            scopes.append(
                {
                    "scope_id": f"experiment_{experiment_id}",
                    "scope_label": f"Experiment {experiment_id}",
                    "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                        target_path
                    ),
                    "metadata": {
                        "experiment_id": experiment_id,
                        "status": str(row.get("status") or ""),
                        "run_settings_hash": str(row.get("run_settings_hash") or ""),
                    },
                }
            )

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=run_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_run",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "quality_run_dir": str(run_root),
            "quality_summary_path": str(summary_path),
        },
    )


def _resolve_quality_compare_scope_path(run_dir: Path, experiment_id: str) -> Path:
    experiment_clean = str(experiment_id or "").strip()
    if not experiment_clean:
        return run_dir
    experiment_root = run_dir / "experiments" / experiment_clean
    if experiment_root.exists() and experiment_root.is_dir():
        return experiment_root
    return run_dir


def _write_qualitysuite_agent_bridge_bundle_for_compare(
    *,
    comparison_root: Path,
    comparison_payload: dict[str, Any],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    baseline_run_dir = Path(
        str(comparison_payload.get("baseline_run_dir") or "").strip()
    ).expanduser()
    candidate_run_dir = Path(
        str(comparison_payload.get("candidate_run_dir") or "").strip()
    ).expanduser()
    baseline_experiment_id = str(
        comparison_payload.get("baseline_experiment_id") or ""
    ).strip()
    candidate_experiment_id = str(
        comparison_payload.get("candidate_experiment_id") or ""
    ).strip()

    baseline_scope_path = _resolve_quality_compare_scope_path(
        baseline_run_dir,
        baseline_experiment_id,
    )
    candidate_scope_path = _resolve_quality_compare_scope_path(
        candidate_run_dir,
        candidate_experiment_id,
    )

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "baseline",
            "scope_label": f"Baseline ({baseline_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                baseline_scope_path
            ),
            "metadata": {
                "run_dir": str(baseline_run_dir),
                "experiment_id": baseline_experiment_id,
            },
        },
        {
            "scope_id": "candidate",
            "scope_label": f"Candidate ({candidate_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                candidate_scope_path
            ),
            "metadata": {
                "run_dir": str(candidate_run_dir),
                "experiment_id": candidate_experiment_id,
            },
        },
    ]

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=comparison_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_compare",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "comparison_root": str(comparison_root),
            "comparison_verdict": str(
                (comparison_payload.get("overall") or {}).get("verdict") or ""
            ).upper(),
            "baseline_run_dir": str(baseline_run_dir),
            "candidate_run_dir": str(candidate_run_dir),
            "baseline_experiment_id": baseline_experiment_id,
            "candidate_experiment_id": candidate_experiment_id,
        },
    )


def _resolve_qualitysuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_quality_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench quality-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--qualitysuite-codex-farm-confirmation "
        f"{QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _resolve_speedsuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_speed_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench speed-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--speedsuite-codex-farm-confirmation "
        f"{SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _print_codex_decision(decision: Any) -> None:
    if bool(_BENCHMARK_SUPPRESS_SUMMARY.get()):
        return
    summary = (
        format_codex_execution_policy_summary(decision)
        if hasattr(decision, "requested_mode")
        else format_codex_command_summary(decision)
    )
    surface = getattr(decision, "surface", None)
    codex_requested = bool(getattr(decision, "codex_requested", False))
    color = (
        typer.colors.CYAN
        if (
            surface is not None
            and (
                bool(getattr(surface, "any_codex_enabled", False))
                or codex_requested
            )
        )
        else typer.colors.BRIGHT_BLACK
    )
    typer.secho(summary, fg=color)


def _resolve_all_method_markdown_extractors_choice() -> bool:
    requested = os.getenv(ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV, "").strip() == "1"
    return requested and markdown_epub_extractors_enabled()


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


def _system_total_memory_bytes() -> int | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        page_size = 0
        page_count = 0
    total = page_size * page_count
    if total > 0:
        return total

    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kib = int(parts[1])
                if kib > 0:
                    return kib * 1024
        except (OSError, ValueError):
            return None
    return None


def _resolve_all_method_split_worker_cap(
    *,
    split_phase_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    slots = max(1, _report_count(split_phase_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_worker_cap_by_cpu = max(1, cpu_budget_per_source // slots)

    memory_total_bytes = _system_total_memory_bytes()
    split_worker_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        workers_by_memory_per_source = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )
        split_worker_cap_by_memory = max(1, workers_by_memory_per_source // slots)

    split_worker_cap = split_worker_cap_by_cpu
    if split_worker_cap_by_memory is not None:
        split_worker_cap = min(split_worker_cap, split_worker_cap_by_memory)

    return split_worker_cap, {
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
        "split_worker_cap_by_cpu": split_worker_cap_by_cpu,
        "split_worker_cap_by_memory": split_worker_cap_by_memory,
        "split_worker_cap_per_config": split_worker_cap,
    }


def _resolve_all_method_split_phase_slot_cap(
    *,
    requested_split_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    requested = max(1, _report_count(requested_split_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    slot_cap_by_cpu = max(1, cpu_budget_per_source)

    memory_total_bytes = _system_total_memory_bytes()
    slot_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        slot_cap_by_memory = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )

    effective_slots = min(requested, slot_cap_by_cpu)
    if slot_cap_by_memory is not None:
        effective_slots = min(effective_slots, slot_cap_by_memory)
    effective_slots = max(1, effective_slots)
    cap_mode = "resource_guard" if effective_slots < requested else "configured"

    return effective_slots, {
        "requested_split_phase_slots": requested,
        "effective_split_phase_slots": effective_slots,
        "split_phase_slot_mode": cap_mode,
        "split_phase_slot_cap_by_cpu": slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": slot_cap_by_memory,
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
    }


def _resolve_all_method_scheduler_admission(
    *,
    counts: dict[str, int],
    pending_count: int,
    total_variants: int,
    configured_inflight_pipelines: int,
    split_phase_slots: int,
    wing_backlog_target: int,
    max_active_during_eval: int,
    adaptive_overcommit_limit: int,
    adaptive_max_guard_target: int,
    smart_scheduler_enabled: bool,
    cpu_utilization_pct: float | None = None,
) -> _AllMethodSchedulerAdmissionDecision:
    total = max(1, _report_count(total_variants))
    split_slots = max(1, _report_count(split_phase_slots))
    configured_inflight = max(1, min(total, _report_count(configured_inflight_pipelines)))
    wing_target_base = max(1, _report_count(wing_backlog_target))
    max_active_eval = max(configured_inflight, min(total, _report_count(max_active_during_eval)))
    overcommit_cap = max(0, _report_count(adaptive_overcommit_limit))
    guard_cap = max(
        split_slots + wing_target_base,
        min(total, _report_count(adaptive_max_guard_target)),
    )
    guard_base = min(total, split_slots + wing_target_base)
    pending = max(0, _report_count(pending_count))
    evaluate_active = max(0, _report_count(counts.get("evaluate_active")))
    split_wait = max(0, _report_count(counts.get("split_wait")))
    heavy_active = max(0, _report_count(counts.get("heavy_active")))
    prep_active = max(0, _report_count(counts.get("prep_active")))
    wing_backlog = max(0, _report_count(counts.get("wing_backlog")))
    eval_tail_open = evaluate_active > 0 and pending > 0
    cpu_hot = (
        cpu_utilization_pct is not None
        and float(cpu_utilization_pct) >= ALL_METHOD_ADAPTIVE_CPU_HOT_PCT
    )

    active_cap = max_active_eval if eval_tail_open and smart_scheduler_enabled else configured_inflight
    guard_target = guard_base
    wing_target = wing_target_base
    reason = "base"
    pressure_boost = 0
    saturation_clamp = False
    cpu_hot_clamp = False

    if not smart_scheduler_enabled:
        return _AllMethodSchedulerAdmissionDecision(
            active_cap=max(1, min(total, active_cap)),
            guard_target=max(1, min(total, guard_target)),
            wing_target=max(1, min(total, wing_target)),
            reason=reason,
            pressure_boost=pressure_boost,
            saturation_clamp=saturation_clamp,
            cpu_hot_clamp=cpu_hot_clamp,
        )

    heavy_gap = max(0, split_slots - heavy_active)
    backlog_starved = pending > 0 and (
        heavy_gap > 0 or (split_wait == 0 and prep_active < split_slots)
    )
    if backlog_starved and not cpu_hot:
        available_overcommit = 0
        if eval_tail_open:
            available_overcommit = max(
                0,
                min(overcommit_cap, max_active_eval - active_cap),
            )
        pressure_boost = min(available_overcommit, max(1, heavy_gap))
        if pressure_boost > 0:
            active_cap += pressure_boost
        wing_boost = max(1, heavy_gap)
        wing_target = min(total, wing_target_base + wing_boost)
        guard_target = min(
            guard_cap,
            split_slots + wing_target + pressure_boost,
        )
        reason = "pressure_boost"

    saturated_backlog_threshold = max(
        wing_target_base + split_slots,
        wing_target_base * ALL_METHOD_ADAPTIVE_SATURATION_BACKLOG_MULTIPLIER,
    )
    if wing_backlog >= saturated_backlog_threshold and heavy_active >= split_slots:
        saturation_clamp = True
        wing_target = wing_target_base
        guard_target = guard_base
        active_cap = min(active_cap, max_active_eval if eval_tail_open else configured_inflight)
        reason = "saturation_clamp"

    if cpu_hot and active_cap > configured_inflight:
        cpu_hot_clamp = True
        active_cap = max(configured_inflight, active_cap - 1)
        reason = "cpu_hot_clamp"

    return _AllMethodSchedulerAdmissionDecision(
        active_cap=max(1, min(total, active_cap)),
        guard_target=max(1, min(total, guard_target)),
        wing_target=max(1, min(total, wing_target)),
        reason=reason,
        pressure_boost=max(0, pressure_boost),
        saturation_clamp=saturation_clamp,
        cpu_hot_clamp=cpu_hot_clamp,
    )


def _resolve_all_method_source_parallelism(
    *,
    total_sources: int,
    requested: int | None = None,
) -> int:
    total = max(1, _report_count(total_sources))
    default_parallel_sources = min(
        _all_method_default_parallel_sources_from_cpu(),
        total,
    )
    requested_parallel_sources = _report_count(requested)
    if requested_parallel_sources <= 0:
        return default_parallel_sources
    cpu_cap = max(1, _report_count(os.cpu_count()))
    return max(1, min(requested_parallel_sources, total, cpu_cap))


def _create_all_method_process_pool_executor(*, max_workers: int):
    context = preferred_multiprocessing_context()
    if context is None:
        try:
            start_method = multiprocessing.get_start_method(allow_none=True)
        except TypeError:
            start_method = multiprocessing.get_start_method()
        if not start_method:
            try:
                start_methods = multiprocessing.get_all_start_methods()
            except Exception:  # noqa: BLE001
                start_methods = []
            start_method = start_methods[0] if start_methods else None
        if str(start_method or "").strip() == "fork":
            try:
                available_methods = multiprocessing.get_all_start_methods()
            except Exception:  # noqa: BLE001
                available_methods = []
            if "spawn" in available_methods:
                try:
                    context = multiprocessing.get_context("spawn")
                except Exception:  # noqa: BLE001
                    context = None
    if context is None:
        return ProcessPoolExecutor(max_workers=max_workers)
    try:
        return ProcessPoolExecutor(max_workers=max_workers, mp_context=context)
    except TypeError:
        return ProcessPoolExecutor(max_workers=max_workers)


def _probe_all_method_process_pool_executor() -> tuple[bool, str | None]:
    """Return whether process-based config workers are usable in this runtime."""
    try:
        with _create_all_method_process_pool_executor(max_workers=1) as executor:
            future = executor.submit(int, 1)
            future.result(timeout=5)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _probe_all_method_process_worker_picklable() -> tuple[bool, str | None]:
    """Ensure the benchmark config worker can be pickled when process pooling is active."""
    try:
        pickle.dumps(_run_all_method_prediction_once)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _resolve_all_method_scheduler_limits(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
) -> tuple[int, int]:
    total = max(1, _report_count(total_variants))

    inflight_default = min(ALL_METHOD_MAX_INFLIGHT_DEFAULT, total)
    if max_inflight_pipelines is None:
        inflight = inflight_default
    else:
        requested_inflight = _report_count(max_inflight_pipelines)
        if requested_inflight <= 0:
            inflight = inflight_default
        else:
            inflight = max(1, min(requested_inflight, total))

    split_default = min(ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT, inflight)
    if max_concurrent_split_phases is None:
        split_slots = split_default
    else:
        requested_split_slots = _report_count(max_concurrent_split_phases)
        if requested_split_slots <= 0:
            split_slots = split_default
        else:
            split_slots = max(1, min(requested_split_slots, inflight))

    return inflight, split_slots


@dataclass(frozen=True)
class _AllMethodSchedulerRuntime:
    configured_inflight_pipelines: int
    split_phase_slots_requested: int
    split_phase_slots: int
    split_phase_slot_mode: str
    split_phase_slot_cap_by_cpu: int
    split_phase_slot_cap_by_memory: int | None
    wing_backlog_target: int
    eval_tail_headroom_configured: int
    eval_tail_headroom_effective: int
    eval_tail_headroom_mode: str
    smart_scheduler_enabled: bool
    max_active_during_eval: int
    effective_inflight_pipelines: int
    adaptive_overcommit_limit: int
    adaptive_max_guard_target: int
    source_parallelism_effective: int
    cpu_budget_per_source: int
    cpu_budget_total: int


@dataclass(frozen=True)
class _AllMethodSchedulerAdmissionDecision:
    active_cap: int
    guard_target: int
    wing_target: int
    reason: str
    pressure_boost: int
    saturation_clamp: bool
    cpu_hot_clamp: bool


def _resolve_all_method_config_timeout_seconds(
    config_timeout_seconds: int | None,
) -> int | None:
    if config_timeout_seconds is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    parsed = _coerce_non_negative_int(config_timeout_seconds)
    if parsed is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    if parsed == 0:
        return None
    return parsed


def _resolve_all_method_retry_failed_configs(retry_failed_configs: int | None) -> int:
    if retry_failed_configs is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    parsed = _coerce_non_negative_int(retry_failed_configs)
    if parsed is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    return parsed


def _resolve_all_method_scheduler_runtime(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
    source_parallelism_effective: int | None = None,
) -> _AllMethodSchedulerRuntime:
    inflight, split_slots_requested = _resolve_all_method_scheduler_limits(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
    )
    total = max(1, _report_count(total_variants))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1
    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_slots, split_slot_guard = _resolve_all_method_split_phase_slot_cap(
        requested_split_slots=split_slots_requested,
        source_parallelism_effective=source_parallelism,
    )
    wing_default = max(1, split_slots)
    wing_target_requested = _report_count(wing_backlog_target)
    wing_target = wing_target_requested if wing_target_requested > 0 else wing_default
    wing_target = max(1, min(total, wing_target))

    eval_tail_requested = _report_count(max_eval_tail_pipelines)
    eval_tail_mode = "configured" if eval_tail_requested > 0 else "auto"
    if eval_tail_requested > 0:
        eval_tail_configured = max(0, eval_tail_requested)
    else:
        eval_tail_configured = max(0, cpu_budget_per_source - inflight)

    # Eval-tail headroom is bounded to per-source CPU budget and available variants.
    eval_tail_effective = max(
        0,
        min(
            eval_tail_configured,
            cpu_budget_per_source,
            max(0, total - inflight),
        ),
    )
    smart_enabled = (
        True if smart_scheduler is None else _coerce_bool_setting(smart_scheduler, default=True)
    )

    max_active_during_eval = inflight
    if smart_enabled:
        max_active_during_eval = min(total, inflight + eval_tail_effective)
    adaptive_overcommit_limit = max(
        0,
        min(split_slots, max(0, max_active_during_eval - inflight)),
    )
    adaptive_max_guard_target = min(
        total,
        split_slots + wing_target + adaptive_overcommit_limit,
    )

    return _AllMethodSchedulerRuntime(
        configured_inflight_pipelines=inflight,
        split_phase_slots_requested=split_slots_requested,
        split_phase_slots=split_slots,
        split_phase_slot_mode=str(split_slot_guard.get("split_phase_slot_mode") or "configured"),
        split_phase_slot_cap_by_cpu=_report_count(
            split_slot_guard.get("split_phase_slot_cap_by_cpu")
        ),
        split_phase_slot_cap_by_memory=(
            _report_count(split_slot_guard.get("split_phase_slot_cap_by_memory"))
            if split_slot_guard.get("split_phase_slot_cap_by_memory") is not None
            else None
        ),
        wing_backlog_target=wing_target,
        eval_tail_headroom_configured=eval_tail_configured,
        eval_tail_headroom_effective=eval_tail_effective,
        eval_tail_headroom_mode=eval_tail_mode,
        smart_scheduler_enabled=smart_enabled,
        max_active_during_eval=max_active_during_eval,
        effective_inflight_pipelines=max_active_during_eval if smart_enabled else inflight,
        adaptive_overcommit_limit=adaptive_overcommit_limit,
        adaptive_max_guard_target=adaptive_max_guard_target,
        source_parallelism_effective=source_parallelism,
        cpu_budget_per_source=cpu_budget_per_source,
        cpu_budget_total=cpu_budget_total,
    )


def _all_method_extract_alignment_guardrail_fields(
    report_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    report = report_payload if isinstance(report_payload, dict) else {}
    return {
        "alignment_cache_enabled": bool(report.get("alignment_cache_enabled")),
        "alignment_cache_hit": bool(report.get("alignment_cache_hit")),
        "alignment_cache_load_seconds": _report_metric(report.get("alignment_cache_load_seconds")),
        "alignment_cache_write_seconds": _report_metric(report.get("alignment_cache_write_seconds")),
        "alignment_sequence_matcher_impl": str(report.get("alignment_sequence_matcher_impl") or ""),
        "alignment_sequence_matcher_mode": str(report.get("alignment_sequence_matcher_mode") or ""),
        "alignment_sequence_matcher_requested_mode": str(
            report.get("alignment_sequence_matcher_requested_mode") or ""
        ),
        "alignment_sequence_matcher_forced_mode": str(
            report.get("alignment_sequence_matcher_forced_mode") or ""
        ),
    }


def _all_method_build_matcher_guardrails(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executed_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
        and str(row.get("evaluation_result_source") or "").strip().lower() == "executed"
    ]
    eval_wall_sum = 0.0
    prediction_wall_sum = 0.0
    cache_enabled_count = 0
    cache_hit_count = 0
    matcher_mode_counts: dict[str, int] = {}

    for row in executed_rows:
        timing = _normalize_timing_payload(row.get("timing"))
        checkpoints = timing.get("checkpoints")
        if not isinstance(checkpoints, dict):
            checkpoints = {}
        eval_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_eval_wall_seconds")),
        )
        prediction_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_prediction_wall_seconds")),
        )
        cache_enabled = bool(row.get("alignment_cache_enabled"))
        if cache_enabled:
            cache_enabled_count += 1
            if bool(row.get("alignment_cache_hit")):
                cache_hit_count += 1
        matcher_mode = str(row.get("alignment_sequence_matcher_mode") or "").strip()
        if matcher_mode:
            matcher_mode_counts[matcher_mode] = matcher_mode_counts.get(matcher_mode, 0) + 1

    eval_to_prediction_ratio = (
        (eval_wall_sum / prediction_wall_sum) if prediction_wall_sum > 0 else 0.0
    )
    cache_hit_rate = (
        (float(cache_hit_count) / float(cache_enabled_count))
        if cache_enabled_count > 0
        else 1.0
    )
    warnings: list[str] = []
    if eval_to_prediction_ratio > ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:
        warnings.append(
            "Eval wall share exceeded guardrail: "
            f"{eval_to_prediction_ratio:.3f} > {ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:.3f}"
        )
    if cache_enabled_count > 0 and cache_hit_rate < ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:
        warnings.append(
            "Canonical alignment cache hit-rate dropped below guardrail: "
            f"{cache_hit_rate:.3f} < {ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:.3f}"
        )
    if matcher_mode_counts and not any(
        mode == "dmp" for mode in matcher_mode_counts
    ):
        warnings.append("Matcher guardrail expected dmp mode for canonical alignment.")

    return {
        "executed_evaluation_rows": len(executed_rows),
        "eval_wall_seconds_sum": eval_wall_sum,
        "prediction_wall_seconds_sum": prediction_wall_sum,
        "eval_to_prediction_wall_ratio": eval_to_prediction_ratio,
        "cache_enabled_count": cache_enabled_count,
        "cache_hit_count": cache_hit_count,
        "cache_hit_rate": cache_hit_rate,
        "matcher_mode_counts": matcher_mode_counts,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _all_method_config_dir_name(config_index: int, variant: AllMethodVariant) -> str:
    config_hash = variant.run_settings.short_hash()
    return f"config_{config_index:03d}_{config_hash}_{variant.slug}"


def _all_method_failed_row(
    *,
    config_index: int,
    config_dir_name: str,
    variant: AllMethodVariant,
    error: str,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "failed",
        "error": str(error),
        "run_config_hash": "",
        "run_config_summary": "",
        "dimensions": dict(variant.dimensions),
    }
    numeric_elapsed = _report_optional_metric(elapsed_seconds)
    if numeric_elapsed is not None:
        row["timing"] = _timing_with_updates(
            {},
            total_seconds=max(0.0, numeric_elapsed),
        )
    return row


def _stable_json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _all_method_prediction_reuse_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    return {
        "schema_version": ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "prediction_identity": build_all_method_prediction_identity_payload(
            run_settings
        ),
    }


def _all_method_split_convert_input_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    return {
        "schema_version": ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "inputs": selected_inputs,
    }


def _build_all_method_prediction_reuse_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_prediction_reuse_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _build_all_method_split_convert_input_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_split_convert_input_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_key_payload(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in SINGLE_BOOK_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    normalized_pipeline = str(pipeline or "auto").strip().lower()
    return {
        "schema_version": SINGLE_BOOK_SPLIT_CACHE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "source_hash": str(source_hash or "").strip() or None,
        "pipeline": normalized_pipeline or "auto",
        "inputs": selected_inputs,
    }


def _build_single_book_split_cache_key(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _single_book_split_cache_key_payload(
            source_file=source_file,
            source_hash=source_hash,
            pipeline=pipeline,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_entry_path(
    *,
    cache_root: Path,
    split_cache_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(split_cache_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_root / f"{safe_key}.json"


def _single_book_split_cache_lock_path(
    cache_path: Path,
) -> Path:
    return cache_path.with_suffix(
        f"{cache_path.suffix}{SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX}"
    )


def _load_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("single_book_split_cache_key") or "").strip()
    if cached_key != str(expected_key or "").strip():
        return None
    conversion_payload = payload.get("conversion_result")
    if not isinstance(conversion_payload, dict):
        return None
    return payload


def _write_single_book_split_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_single_book_split_cache_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_single_book_split_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS,
    poll_seconds: float = SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_single_book_split_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_single_book_split_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _all_method_prediction_reuse_cache_entry_path(
    *,
    cache_dir: Path,
    prediction_reuse_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(prediction_reuse_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_dir / f"{safe_key}.json"


def _load_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("prediction_reuse_key") or "").strip()
    if cached_key != str(expected_key):
        return None
    config_dir = str(payload.get("config_dir") or "").strip()
    source_eval_output_dir = str(payload.get("source_eval_output_dir") or "").strip()
    if not config_dir and not source_eval_output_dir:
        return None
    return payload


def _write_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_all_method_prediction_reuse_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_all_method_prediction_reuse_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = ALL_METHOD_PREDICTION_REUSE_WAIT_SECONDS,
    poll_seconds: float = ALL_METHOD_PREDICTION_REUSE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_all_method_prediction_reuse_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_all_method_prediction_reuse_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _path_is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:  # noqa: BLE001
        return False


def _copytree_with_hardlink_fallback(
    *,
    source_dir: Path,
    target_dir: Path,
) -> None:
    try:
        shutil.copytree(source_dir, target_dir, copy_function=os.link)
    except Exception:  # noqa: BLE001
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)


def _copy_all_method_prediction_artifacts_for_reuse(
    *,
    source_config_dir: str,
    target_config_dir: str,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    source_eval_output_dir: Path | None = None,
    source_scratch_output_dir: Path | None = None,
    source_processed_output_dir: Path | None = None,
) -> float | None:
    source_dir = str(source_config_dir or "").strip()
    target_dir = str(target_config_dir or "").strip()
    if not target_dir:
        return None
    if source_dir and source_dir == target_dir and source_eval_output_dir is None:
        return None

    if source_eval_output_dir is not None:
        resolved_source_eval_output_dir = Path(source_eval_output_dir).expanduser()
    else:
        if not source_dir:
            return None
        resolved_source_eval_output_dir = root_output_dir / source_dir
    target_eval_output_dir = root_output_dir / target_dir
    if resolved_source_eval_output_dir.resolve(
        strict=False
    ) == target_eval_output_dir.resolve(strict=False):
        return None
    source_prediction_records = resolved_source_eval_output_dir / "prediction-records.jsonl"
    if (
        not resolved_source_eval_output_dir.exists()
        or not resolved_source_eval_output_dir.is_dir()
        or not source_prediction_records.exists()
        or not source_prediction_records.is_file()
    ):
        return None

    if source_scratch_output_dir is not None:
        source_scratch_dir = Path(source_scratch_output_dir).expanduser()
    elif source_dir:
        source_scratch_dir = scratch_root / source_dir
    else:
        source_scratch_dir = Path("__missing_prediction_reuse_scratch__")
    target_scratch_dir = scratch_root / target_dir
    if source_processed_output_dir is not None:
        source_processed_dir = Path(source_processed_output_dir).expanduser()
    elif source_dir:
        source_processed_dir = processed_output_root / source_dir
    else:
        source_processed_dir = Path("__missing_prediction_reuse_processed__")
    target_processed_dir = processed_output_root / target_dir

    def _reset_tree(target_dir_path: Path) -> None:
        if target_dir_path.exists():
            shutil.rmtree(target_dir_path)

    copy_started = time.monotonic()
    _reset_tree(target_eval_output_dir)
    _reset_tree(target_scratch_dir)
    _reset_tree(target_processed_dir)
    _copytree_with_hardlink_fallback(
        source_dir=resolved_source_eval_output_dir,
        target_dir=target_eval_output_dir,
    )
    if source_scratch_dir.exists() and source_scratch_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_scratch_dir,
            target_dir=target_scratch_dir,
        )
    if source_processed_dir.exists() and source_processed_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_processed_dir,
            target_dir=target_processed_dir,
        )
    return max(0.0, time.monotonic() - copy_started)


def _all_method_eval_signature_prediction_rows(
    *,
    prediction_record_path: Path,
) -> list[dict[str, Any]]:
    prediction_records = list(read_prediction_records(prediction_record_path))
    if not prediction_records:
        raise ValueError(f"Prediction record file is empty: {prediction_record_path}")
    signature_rows: list[dict[str, Any]] = []
    for record in prediction_records:
        signature_rows.append(
            {
                "example_index": int(record.example_index),
                "prediction": _json_safe(record.prediction),
            }
        )
    signature_rows.sort(
        key=lambda row: (
            int(row.get("example_index", 0)),
            _stable_json_sha256(row.get("prediction", {})),
        )
    )
    return signature_rows


def _all_method_gold_fingerprint(gold_spans_path: Path) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {"gold_spans_path": str(gold_spans_path)}
    if gold_spans_path.exists() and gold_spans_path.is_file():
        try:
            fingerprint["gold_spans_sha256"] = compute_file_hash(gold_spans_path)
        except Exception:  # noqa: BLE001
            fingerprint["gold_spans_sha256"] = None

    gold_export_root = gold_spans_path.parent
    for artifact_name in (
        "canonical_text.txt",
        "canonical_span_labels.jsonl",
        "canonical_manifest.json",
    ):
        artifact_path = gold_export_root / artifact_name
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        key = f"{artifact_name.replace('.', '_')}_sha256"
        try:
            fingerprint[key] = compute_file_hash(artifact_path)
        except Exception:  # noqa: BLE001
            fingerprint[key] = None
    return fingerprint


def _build_all_method_eval_signature(
    *,
    gold_spans_path: Path,
    prediction_record_path: Path,
    eval_mode: str,
    sequence_matcher: str,
    schema_version: str = ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION,
) -> str:
    signature_payload = {
        "schema_version": str(schema_version or ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION),
        "eval_mode": str(eval_mode or BENCHMARK_EVAL_MODE_CANONICAL_TEXT),
        "sequence_matcher": str(sequence_matcher or "dmp"),
        "gold_fingerprint": _all_method_gold_fingerprint(gold_spans_path),
        "prediction_rows": _all_method_eval_signature_prediction_rows(
            prediction_record_path=prediction_record_path
        ),
    }
    return _stable_json_sha256(signature_payload)


def _group_all_method_rows_by_eval_signature(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        eval_signature = str(row.get("eval_signature") or "").strip()
        if not eval_signature:
            continue
        grouped_rows[eval_signature].append(row)
    for eval_signature in list(grouped_rows):
        grouped_rows[eval_signature].sort(
            key=lambda row: _report_count(row.get("config_index"))
        )
    return dict(grouped_rows)


def _all_method_prediction_reuse_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    successful_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    prediction_signatures_unique = len(
        {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in successful_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
    )
    prediction_runs_executed = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower() == "executed"
    )
    prediction_results_reused_in_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_in_run"
    )
    prediction_results_reused_cross_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_cross_run"
    )

    split_convert_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in successful_rows:
        split_key = str(row.get("prediction_split_convert_input_key") or "").strip()
        if not split_key:
            continue
        split_convert_groups[split_key].append(row)
    split_convert_input_groups = len(split_convert_groups)
    split_convert_reuse_candidates = sum(
        max(0, len(group_rows) - 1) for group_rows in split_convert_groups.values()
    )
    split_convert_reuse_safe_candidates = 0
    split_convert_reuse_blocked_by_prediction_variance = 0
    for group_rows in split_convert_groups.values():
        if len(group_rows) <= 1:
            continue
        candidate_count = len(group_rows) - 1
        prediction_keys = {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in group_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
        if len(prediction_keys) <= 1:
            split_convert_reuse_safe_candidates += candidate_count
        else:
            split_convert_reuse_blocked_by_prediction_variance += candidate_count

    return {
        "prediction_signatures_unique": prediction_signatures_unique,
        "prediction_runs_executed": prediction_runs_executed,
        "prediction_results_reused_in_run": prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": prediction_results_reused_cross_run,
        "split_convert_input_groups": split_convert_input_groups,
        "split_convert_reuse_candidates": split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": (
            split_convert_reuse_blocked_by_prediction_variance
        ),
    }


def _resolve_all_method_eval_signature_cache_dir(
    *,
    root_output_dir: Path,
    alignment_cache_dir: Path | None,
) -> Path:
    if alignment_cache_dir is None:
        return root_output_dir / ".cache" / "eval_signature_results"

    resolved_alignment_dir = alignment_cache_dir.expanduser()
    if resolved_alignment_dir.name == "canonical_alignment":
        return resolved_alignment_dir.parent / "eval_signature_results"
    if resolved_alignment_dir.parent.name == "canonical_alignment":
        return (
            resolved_alignment_dir.parent.parent
            / "eval_signature_results"
            / resolved_alignment_dir.name
        )
    return resolved_alignment_dir.parent / "eval_signature_results"


def _resolve_all_method_prediction_reuse_cache_dir(*, root_output_dir: Path) -> Path:
    env_override = str(
        os.getenv(ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    return root_output_dir / ".prediction_reuse_cache"


def _load_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    expected_signature: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION:
        return None
    cached_signature = str(payload.get("eval_signature") or "").strip()
    if cached_signature != str(expected_signature):
        return None
    report_payload = payload.get("report")
    if not isinstance(report_payload, dict):
        return None
    return payload


def _write_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _materialize_all_method_cached_eval_outputs(
    *,
    eval_output_dir: Path,
    report_payload: dict[str, Any],
    report_md_text: str | None,
) -> tuple[Path, Path]:
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = eval_output_dir / "eval_report.json"
    report_md_path = eval_output_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    rendered_md = str(report_md_text or "").strip()
    if not rendered_md:
        rendered_md = (
            "# Benchmark Eval Report (Cached)\n\n"
            "Evaluation report reused from all-method signature cache."
        )
    report_md_path.write_text(rendered_md, encoding="utf-8")
    return report_json_path, report_md_path


def _resolve_all_method_prediction_record_path(
    *,
    root_output_dir: Path,
    row: dict[str, Any],
) -> Path | None:
    raw_value = str(row.get("prediction_record_jsonl") or "").strip()
    if not raw_value:
        return None
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = root_output_dir / candidate
    return candidate


def _run_all_method_prediction_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variant: AllMethodVariant,
    config_index: int,
    total_variants: int,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    max_concurrent_split_phases: int,
    split_phase_gate_dir: Path,
    scheduler_events_dir: Path,
    alignment_cache_dir: Path | None,
    prediction_reuse_cache_dir: Path | None = None,
    split_worker_cap_per_config: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    config_started = time.monotonic()
    config_dir_name = _all_method_config_dir_name(config_index, variant)
    eval_output_dir = root_output_dir / config_dir_name
    scratch_output_dir = scratch_root / config_dir_name
    processed_output_dir = processed_output_root / config_dir_name
    prediction_record_path = eval_output_dir / "prediction-records.jsonl"
    prediction_reuse_key = _build_all_method_prediction_reuse_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_split_convert_input_key = _build_all_method_split_convert_input_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_result_source = "executed"
    prediction_reuse_scope = "executed"
    prediction_representative_config_dir = config_dir_name
    reused_prediction = False

    split_slots = max(1, _report_count(max_concurrent_split_phases))
    split_status_label = format_task_counter(
        "Config",
        config_index,
        max(1, _report_count(total_variants)),
        noun="config",
    )
    source_slug = slugify_name(source_file.stem)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    scheduler_event_path = scheduler_events_dir / f"config_{config_index:03d}.jsonl"
    if scheduler_event_path.exists():
        scheduler_event_path.unlink()

    def _emit_scheduler_event(
        event_name: str,
        **payload: Any,
    ) -> None:
        event = str(event_name or "").strip()
        if not event:
            return
        row = {
            "event": event,
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": time.monotonic(),
            "config_index": config_index,
            "config_slug": variant.slug,
            "config_dir": config_dir_name,
            "source_slug": source_slug,
        }
        row.update(payload)
        try:
            with scheduler_event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler event write failure for %s: %s",
                scheduler_event_path,
                exc,
            )

    def _scheduler_event_callback(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        event_name = str(payload.get("event") or "").strip()
        if not event_name:
            return
        event_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "config_index", "config_slug", "source_slug"}
        }
        _emit_scheduler_event(event_name, **event_payload)

    def _discard_progress(_message: str) -> None:
        return

    def _prediction_failed_row(error: str, *, elapsed_seconds: float) -> dict[str, Any]:
        row = _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=error,
            elapsed_seconds=elapsed_seconds,
        )
        row["prediction_result_source"] = "failed"
        row["prediction_reuse_scope"] = "failed"
        row["prediction_representative_config_dir"] = config_dir_name
        row["prediction_reuse_key"] = prediction_reuse_key
        row["prediction_split_convert_input_key"] = prediction_split_convert_input_key
        return row

    def _reset_target_prediction_dirs() -> None:
        if eval_output_dir.exists():
            shutil.rmtree(eval_output_dir)
        if scratch_output_dir.exists():
            shutil.rmtree(scratch_output_dir)
        if processed_output_dir.exists():
            shutil.rmtree(processed_output_dir)

    benchmark_progress_callback = progress_callback or _discard_progress
    _emit_scheduler_event("config_started")

    requested_workers = max(1, _report_count(variant.run_settings.workers))
    requested_pdf_split_workers = max(1, _report_count(variant.run_settings.pdf_split_workers))
    requested_epub_split_workers = max(1, _report_count(variant.run_settings.epub_split_workers))
    effective_split_worker_cap = (
        max(1, _report_count(split_worker_cap_per_config))
        if split_worker_cap_per_config is not None
        else None
    )
    effective_workers = requested_workers
    effective_pdf_split_workers = requested_pdf_split_workers
    effective_epub_split_workers = requested_epub_split_workers
    if effective_split_worker_cap is not None:
        effective_workers = min(effective_workers, effective_split_worker_cap)
        effective_pdf_split_workers = min(
            effective_pdf_split_workers,
            effective_split_worker_cap,
        )
        effective_epub_split_workers = min(
            effective_epub_split_workers,
            effective_split_worker_cap,
        )

    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir
        if prediction_reuse_cache_dir is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    ).expanduser()
    prediction_reuse_cache_path = _all_method_prediction_reuse_cache_entry_path(
        cache_dir=prediction_reuse_cache_dir,
        prediction_reuse_key=prediction_reuse_key,
    )
    prediction_reuse_lock_path = prediction_reuse_cache_path.with_suffix(
        f"{prediction_reuse_cache_path.suffix}{ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX}"
    )
    lock_acquired = False

    def _execute_prediction_run() -> str | None:
        _reset_target_prediction_dirs()
        try:
            with _benchmark_split_phase_overrides(
                split_phase_slots=split_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                split_phase_status_label=split_status_label,
            ):
                with _benchmark_progress_overrides(
                    progress_callback=benchmark_progress_callback,
                    suppress_summary=True,
                    suppress_spinner=True,
                    suppress_output_prune=True,
                ):
                    with _benchmark_scheduler_event_overrides(
                        scheduler_event_callback=_scheduler_event_callback
                    ):
                        benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
                            variant.run_settings,
                            output_dir=scratch_output_dir,
                            processed_output_dir=processed_output_dir,
                            eval_output_dir=eval_output_dir,
                            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                            no_upload=True,
                            write_markdown=False,
                            write_label_studio_tasks=False,
                        )
                        benchmark_kwargs["allow_codex"] = codex_surfaces_enabled(
                            variant.run_settings.to_run_config_dict()
                        )
                        benchmark_kwargs.update(
                            {
                                "source_file": source_file,
                                "workers": effective_workers,
                                "pdf_split_workers": effective_pdf_split_workers,
                                "epub_split_workers": effective_epub_split_workers,
                            }
                        )
                        prediction_generation_kwargs = {
                            "path": benchmark_kwargs["source_file"],
                            "output_dir": benchmark_kwargs["output_dir"],
                            "pipeline": benchmark_kwargs.get("pipeline", "auto"),
                            "segment_blocks": 40,
                            "segment_overlap": 5,
                            "limit": None,
                            "sample": None,
                            "workers": benchmark_kwargs["workers"],
                            "pdf_split_workers": benchmark_kwargs["pdf_split_workers"],
                            "epub_split_workers": benchmark_kwargs["epub_split_workers"],
                            "pdf_pages_per_job": benchmark_kwargs["pdf_pages_per_job"],
                            "epub_spine_items_per_job": benchmark_kwargs[
                                "epub_spine_items_per_job"
                            ],
                            "epub_extractor": benchmark_kwargs["epub_extractor"],
                            "epub_unstructured_html_parser_version": benchmark_kwargs[
                                "epub_unstructured_html_parser_version"
                            ],
                            "epub_unstructured_skip_headers_footers": benchmark_kwargs[
                                "epub_unstructured_skip_headers_footers"
                            ],
                            "epub_unstructured_preprocess_mode": benchmark_kwargs[
                                "epub_unstructured_preprocess_mode"
                            ],
                            "ocr_device": benchmark_kwargs["ocr_device"],
                            "pdf_ocr_policy": benchmark_kwargs["pdf_ocr_policy"],
                            "ocr_batch_size": benchmark_kwargs["ocr_batch_size"],
                            "pdf_column_gap_ratio": benchmark_kwargs[
                                "pdf_column_gap_ratio"
                            ],
                            "warm_models": benchmark_kwargs["warm_models"],
                            "section_detector_backend": benchmark_kwargs[
                                "section_detector_backend"
                            ],
                            "multi_recipe_splitter": benchmark_kwargs[
                                "multi_recipe_splitter"
                            ],
                            "multi_recipe_trace": benchmark_kwargs["multi_recipe_trace"],
                            "multi_recipe_min_ingredient_lines": benchmark_kwargs[
                                "multi_recipe_min_ingredient_lines"
                            ],
                            "multi_recipe_min_instruction_lines": benchmark_kwargs[
                                "multi_recipe_min_instruction_lines"
                            ],
                            "multi_recipe_for_the_guardrail": benchmark_kwargs[
                                "multi_recipe_for_the_guardrail"
                            ],
                            "instruction_step_segmentation_policy": benchmark_kwargs[
                                "instruction_step_segmentation_policy"
                            ],
                            "instruction_step_segmenter": benchmark_kwargs[
                                "instruction_step_segmenter"
                            ],
                            "web_schema_extractor": benchmark_kwargs[
                                "web_schema_extractor"
                            ],
                            "web_schema_normalizer": benchmark_kwargs[
                                "web_schema_normalizer"
                            ],
                            "web_html_text_extractor": benchmark_kwargs[
                                "web_html_text_extractor"
                            ],
                            "web_schema_policy": benchmark_kwargs["web_schema_policy"],
                            "web_schema_min_confidence": benchmark_kwargs[
                                "web_schema_min_confidence"
                            ],
                            "web_schema_min_ingredients": benchmark_kwargs[
                                "web_schema_min_ingredients"
                            ],
                            "web_schema_min_instruction_steps": benchmark_kwargs[
                                "web_schema_min_instruction_steps"
                            ],
                            "ingredient_text_fix_backend": benchmark_kwargs[
                                "ingredient_text_fix_backend"
                            ],
                            "ingredient_pre_normalize_mode": benchmark_kwargs[
                                "ingredient_pre_normalize_mode"
                            ],
                            "ingredient_packaging_mode": benchmark_kwargs[
                                "ingredient_packaging_mode"
                            ],
                            "ingredient_parser_backend": benchmark_kwargs[
                                "ingredient_parser_backend"
                            ],
                            "ingredient_unit_canonicalizer": benchmark_kwargs[
                                "ingredient_unit_canonicalizer"
                            ],
                            "ingredient_missing_unit_policy": benchmark_kwargs[
                                "ingredient_missing_unit_policy"
                            ],
                            "p6_time_backend": benchmark_kwargs["p6_time_backend"],
                            "p6_time_total_strategy": benchmark_kwargs[
                                "p6_time_total_strategy"
                            ],
                            "p6_temperature_backend": benchmark_kwargs[
                                "p6_temperature_backend"
                            ],
                            "p6_temperature_unit_backend": benchmark_kwargs[
                                "p6_temperature_unit_backend"
                            ],
                            "p6_ovenlike_mode": benchmark_kwargs["p6_ovenlike_mode"],
                            "p6_yield_mode": benchmark_kwargs["p6_yield_mode"],
                            "p6_emit_metadata_debug": benchmark_kwargs[
                                "p6_emit_metadata_debug"
                            ],
                            "recipe_scorer_backend": benchmark_kwargs[
                                "recipe_scorer_backend"
                            ],
                            "recipe_score_gold_min": benchmark_kwargs[
                                "recipe_score_gold_min"
                            ],
                            "recipe_score_silver_min": benchmark_kwargs[
                                "recipe_score_silver_min"
                            ],
                            "recipe_score_bronze_min": benchmark_kwargs[
                                "recipe_score_bronze_min"
                            ],
                            "recipe_score_min_ingredient_lines": benchmark_kwargs[
                                "recipe_score_min_ingredient_lines"
                            ],
                            "recipe_score_min_instruction_lines": benchmark_kwargs[
                                "recipe_score_min_instruction_lines"
                            ],
                            "llm_recipe_pipeline": benchmark_kwargs[
                                "llm_recipe_pipeline"
                            ],
                            "llm_knowledge_pipeline": benchmark_kwargs[
                                "llm_knowledge_pipeline"
                            ],
                            "knowledge_packet_input_char_budget": benchmark_kwargs[
                                "knowledge_packet_input_char_budget"
                            ],
                            "knowledge_packet_output_char_budget": benchmark_kwargs[
                                "knowledge_packet_output_char_budget"
                            ],
                            "atomic_block_splitter": benchmark_kwargs[
                                "atomic_block_splitter"
                            ],
                            "line_role_pipeline": benchmark_kwargs["line_role_pipeline"],
                            "codex_farm_cmd": benchmark_kwargs["codex_farm_cmd"],
                            "codex_farm_model": benchmark_kwargs.get("codex_farm_model"),
                            "codex_farm_reasoning_effort": benchmark_kwargs.get(
                                "codex_farm_reasoning_effort"
                            ),
                            "codex_farm_root": benchmark_kwargs.get("codex_farm_root"),
                            "codex_farm_workspace_root": benchmark_kwargs.get(
                                "codex_farm_workspace_root"
                            ),
                            "codex_farm_pipeline_knowledge": benchmark_kwargs[
                                "codex_farm_pipeline_knowledge"
                            ],
                            "codex_farm_context_blocks": benchmark_kwargs[
                                "codex_farm_context_blocks"
                            ],
                            "codex_farm_knowledge_context_blocks": benchmark_kwargs[
                                "codex_farm_knowledge_context_blocks"
                            ],
                            "codex_farm_recipe_mode": benchmark_kwargs[
                                "codex_farm_recipe_mode"
                            ],
                            "codex_farm_failure_mode": benchmark_kwargs[
                                "codex_farm_failure_mode"
                            ],
                            "allow_codex": benchmark_kwargs["allow_codex"],
                            "codex_execution_policy": "execute",
                            "processed_output_root": benchmark_kwargs[
                                "processed_output_dir"
                            ],
                            "write_markdown": benchmark_kwargs["write_markdown"],
                            "write_label_studio_tasks": benchmark_kwargs[
                                "write_label_studio_tasks"
                            ],
                            "scheduler_event_callback": _scheduler_event_callback,
                            "progress_callback": benchmark_progress_callback,
                            "run_manifest_kind": "bench_pred_run",
                        }
                        _run_offline_benchmark_prediction_stage(
                            prediction_generation_kwargs=prediction_generation_kwargs,
                            eval_output_dir=eval_output_dir,
                            predictions_out_path=prediction_record_path,
                            suppress_spinner=True,
                            external_progress_callback=benchmark_progress_callback,
                        )
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None

    def _try_materialize_reused_prediction(
        cache_entry: dict[str, Any] | None,
    ) -> bool:
        nonlocal prediction_result_source
        nonlocal prediction_reuse_scope
        nonlocal prediction_representative_config_dir
        nonlocal reused_prediction
        if not isinstance(cache_entry, dict):
            return False
        source_config_dir = str(cache_entry.get("config_dir") or "").strip()
        source_eval_output_dir: Path | None = None
        source_scratch_output_dir: Path | None = None
        source_processed_output_dir: Path | None = None
        source_eval_raw = str(cache_entry.get("source_eval_output_dir") or "").strip()
        source_scratch_raw = str(
            cache_entry.get("source_scratch_output_dir") or ""
        ).strip()
        source_processed_raw = str(
            cache_entry.get("source_processed_output_dir") or ""
        ).strip()
        if source_eval_raw:
            source_eval_output_dir = Path(source_eval_raw).expanduser()
        if source_scratch_raw:
            source_scratch_output_dir = Path(source_scratch_raw).expanduser()
        if source_processed_raw:
            source_processed_output_dir = Path(source_processed_raw).expanduser()
        if not source_config_dir and source_eval_output_dir is None:
            return False
        if source_config_dir == config_dir_name:
            if source_eval_output_dir is None:
                return False
            if source_eval_output_dir.resolve(strict=False) == eval_output_dir.resolve(
                strict=False
            ):
                return False
        copy_seconds = _copy_all_method_prediction_artifacts_for_reuse(
            source_config_dir=source_config_dir,
            target_config_dir=config_dir_name,
            root_output_dir=root_output_dir,
            scratch_root=scratch_root,
            processed_output_root=processed_output_root,
            source_eval_output_dir=source_eval_output_dir,
            source_scratch_output_dir=source_scratch_output_dir,
            source_processed_output_dir=source_processed_output_dir,
        )
        if copy_seconds is None:
            return False
        reuse_scope = "in_run"
        if source_eval_output_dir is not None and not _path_is_within_root(
            source_eval_output_dir,
            root_output_dir,
        ):
            reuse_scope = "cross_run"
        prediction_result_source = (
            "reused_cross_run" if reuse_scope == "cross_run" else "reused_in_run"
        )
        prediction_reuse_scope = reuse_scope
        prediction_representative_config_dir = (
            source_config_dir
            or (str(source_eval_output_dir) if source_eval_output_dir is not None else "")
            or config_dir_name
        )
        reused_prediction = True
        _emit_scheduler_event(
            (
                "prediction_reused_cross_run"
                if prediction_result_source == "reused_cross_run"
                else "prediction_reused_in_run"
            ),
            source_config_dir=source_config_dir,
            reuse_copy_seconds=copy_seconds,
            prediction_result_source=prediction_result_source,
            prediction_reuse_scope=prediction_reuse_scope,
        )
        return True

    try:
        cache_entry = _load_all_method_prediction_reuse_cache_entry(
            cache_path=prediction_reuse_cache_path,
            expected_key=prediction_reuse_key,
        )
        if not _try_materialize_reused_prediction(cache_entry):
            lock_acquired = _acquire_all_method_prediction_reuse_lock(
                prediction_reuse_lock_path
            )
            if lock_acquired:
                cache_entry = _load_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                )
                if not _try_materialize_reused_prediction(cache_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
            else:
                waited_entry = _wait_for_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                    lock_path=prediction_reuse_lock_path,
                )
                if not _try_materialize_reused_prediction(waited_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
    finally:
        if lock_acquired:
            _release_all_method_prediction_reuse_lock(prediction_reuse_lock_path)

    if prediction_result_source == "executed":
        cache_payload = {
            "schema_version": ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "prediction_reuse_key": prediction_reuse_key,
            "prediction_split_convert_input_key": prediction_split_convert_input_key,
            "source_file": str(source_file),
            "config_index": config_index,
            "config_dir": config_dir_name,
            "source_eval_output_dir": str(eval_output_dir),
            "source_scratch_output_dir": str(scratch_output_dir),
            "source_processed_output_dir": str(processed_output_dir),
        }
        try:
            _write_all_method_prediction_reuse_cache_entry(
                cache_path=prediction_reuse_cache_path,
                payload=cache_payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring all-method prediction reuse cache write failure for %s: %s",
                prediction_reuse_cache_path,
                exc,
            )

    if not prediction_record_path.exists():
        missing_error = f"Missing prediction-records.jsonl in {eval_output_dir}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=missing_error,
        )
        return _prediction_failed_row(
            missing_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    try:
        prediction_records = list(read_prediction_records(prediction_record_path))
    except Exception as exc:  # noqa: BLE001
        parse_error = f"Failed to parse prediction records for {config_dir_name}: {exc}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=parse_error,
        )
        return _prediction_failed_row(
            parse_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    if not prediction_records:
        empty_error = f"Prediction records are empty for {config_dir_name}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=empty_error,
        )
        return _prediction_failed_row(
            empty_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    config_wall_seconds = max(0.0, time.monotonic() - config_started)
    report_timing: dict[str, Any] = {}
    run_manifest_path = eval_output_dir / "run_manifest.json"
    if run_manifest_path.exists() and run_manifest_path.is_file():
        try:
            run_manifest_payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            run_manifest_payload = {}
        if isinstance(run_manifest_payload, dict):
            artifacts_payload = run_manifest_payload.get("artifacts")
            if isinstance(artifacts_payload, dict):
                report_timing = _normalize_timing_payload(artifacts_payload.get("timing"))

    # Test doubles sometimes write timing only via eval_report.json.
    if not report_timing:
        report_json_path = eval_output_dir / "eval_report.json"
        if report_json_path.exists() and report_json_path.is_file():
            try:
                report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                report_payload = {}
            if isinstance(report_payload, dict):
                report_timing = _normalize_timing_payload(report_payload.get("timing"))

    prediction_phase_seconds = _report_optional_metric(
        report_timing.get("prediction_seconds")
    )
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    if reused_prediction:
        prediction_phase_seconds = 0.0
        report_total_seconds = config_wall_seconds
    if prediction_phase_seconds is None and report_total_seconds is not None:
        prediction_phase_seconds = report_total_seconds
    if prediction_phase_seconds is None:
        prediction_phase_seconds = config_wall_seconds
    prediction_checkpoints: dict[str, float] = {
        "all_method_prediction_wall_seconds": config_wall_seconds,
        "all_method_config_wall_seconds": config_wall_seconds,
        "all_method_prediction_reused_in_run": 1.0 if reused_prediction else 0.0,
    }
    if reused_prediction:
        prediction_checkpoints["all_method_prediction_reuse_copy_seconds"] = (
            config_wall_seconds
        )
    config_timing = _timing_with_updates(
        report_timing,
        prediction_seconds=prediction_phase_seconds,
        evaluation_seconds=0.0,
        total_seconds=(
            report_total_seconds if report_total_seconds is not None else config_wall_seconds
        ),
        checkpoints=prediction_checkpoints,
    )

    pred_context = _load_pred_run_recipe_context(eval_output_dir)
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "ok",
        "error": "",
        "run_config_hash": pred_context.run_config_hash or variant.run_settings.stable_hash(),
        "run_config_summary": pred_context.run_config_summary
        or variant.run_settings.summary(),
        "prediction_record_jsonl": _path_for_manifest(
            root_output_dir,
            prediction_record_path,
        ),
        "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
        "duration_seconds": config_wall_seconds,
        "timing": config_timing,
        "dimensions": dict(variant.dimensions),
        "prediction_result_source": prediction_result_source,
        "prediction_reuse_scope": prediction_reuse_scope,
        "prediction_representative_config_dir": prediction_representative_config_dir,
        "prediction_reuse_key": prediction_reuse_key,
        "prediction_split_convert_input_key": prediction_split_convert_input_key,
    }
    _emit_scheduler_event(
        "config_finished",
        status="ok",
        duration_seconds=config_wall_seconds,
        prediction_result_source=prediction_result_source,
    )
    return row


def _run_all_method_evaluate_prediction_record_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    prediction_record_path: Path,
    eval_output_dir: Path,
    processed_output_dir: Path,
    sequence_matcher: str,
    epub_extractor: str | None,
    overlap_threshold: float,
    force_source_match: bool,
    alignment_cache_dir: Path | None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    evaluation_started = time.monotonic()

    def _discard_progress(_message: str) -> None:
        return

    benchmark_progress_callback = progress_callback or _discard_progress
    scratch_output_dir = eval_output_dir / ".scratch-eval-only"
    if scratch_output_dir.exists():
        shutil.rmtree(scratch_output_dir)
    for artifact_name in ("eval_report.json", "eval_report.md"):
        artifact_path = eval_output_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()

    fail_message_token = _LAST_FAIL_MESSAGE.set(None)
    try:
        with _benchmark_progress_overrides(
            progress_callback=benchmark_progress_callback,
            suppress_summary=True,
            suppress_spinner=True,
            suppress_output_prune=True,
        ):
            _labelstudio_benchmark_command()(
                gold_spans=gold_spans_path,
                source_file=source_file,
                output_dir=scratch_output_dir,
                processed_output_dir=processed_output_dir,
                eval_output_dir=eval_output_dir,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
                epub_extractor=(epub_extractor or "unstructured"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                no_upload=True,
                predictions_in=prediction_record_path,
                alignment_cache_dir=alignment_cache_dir,
            )
    except typer.Exit as exc:
        exit_code = getattr(exc, "exit_code", 1)
        failure_message = _LAST_FAIL_MESSAGE.get()
        error_message = (
            failure_message
            if failure_message
            else f"labelstudio_benchmark exited with code {exit_code}"
        )
        return {
            "status": "failed",
            "error": error_message,
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": str(exc),
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    finally:
        _LAST_FAIL_MESSAGE.reset(fail_message_token)

    report_json_path = eval_output_dir / "eval_report.json"
    if not report_json_path.exists() or not report_json_path.is_file():
        return {
            "status": "failed",
            "error": f"Missing eval_report.json in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    try:
        report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": f"Failed to parse eval report in {eval_output_dir}: {exc}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    if not isinstance(report_payload, dict):
        return {
            "status": "failed",
            "error": f"Eval report payload is invalid in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }

    evaluation_wall_seconds = max(0.0, time.monotonic() - evaluation_started)
    report_timing = _normalize_timing_payload(report_payload.get("timing"))
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    normalized_timing = _timing_with_updates(
        report_timing,
        total_seconds=(
            report_total_seconds
            if report_total_seconds is not None
            else evaluation_wall_seconds
        ),
        checkpoints={"all_method_eval_wall_seconds": evaluation_wall_seconds},
    )
    report_payload["timing"] = normalized_timing
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = eval_output_dir / "eval_report.md"
    report_md_text = (
        report_md_path.read_text(encoding="utf-8")
        if report_md_path.exists() and report_md_path.is_file()
        else ""
    )
    metric_bundle = _benchmark_report_metric_bundle(report_payload)
    return {
        "status": "ok",
        "error": "",
        **metric_bundle,
        "timing": normalized_timing,
        "report": report_payload,
        "report_md_text": report_md_text,
        "eval_report_json_path": report_json_path,
        "eval_report_md_path": report_md_path,
        "duration_seconds": evaluation_wall_seconds,
    }


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
        prediction_reuse_summary = _all_method_prediction_reuse_summary(
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
            row["timing"] = _timing_with_updates(row_timing, total_seconds=row_total_seconds)
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
            str(row.get("error") or "").strip() for row in failed_source_rows if str(row.get("error") or "").strip()
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


def _run_all_method_benchmark_global_queue(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    run_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)

    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    resolved_canonical_cache_root = (
        canonical_alignment_cache_root.expanduser()
        if canonical_alignment_cache_root is not None
        else _resolve_all_method_canonical_alignment_cache_root(
            root_output_dir=root_output_dir
        )
    )
    resolved_prediction_reuse_cache_root = (
        prediction_reuse_cache_root.expanduser()
        if prediction_reuse_cache_root is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    resolved_dashboard_output_root = (
        dashboard_output_root.expanduser()
        if dashboard_output_root is not None
        else None
    )

    total_targets = len(target_variants)
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
    )
    work_items = _plan_all_method_global_work_items(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        canonical_alignment_cache_root=resolved_canonical_cache_root,
    )
    total_planned_config_runs = len(work_items)
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        max(1, total_targets),
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=max(1, total_targets),
        requested=max_parallel_sources,
    )

    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=max(1, total_planned_config_runs),
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=1,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=1,
    )

    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(item.variant.run_settings.workers)),
                max(1, _report_count(item.variant.run_settings.pdf_split_workers)),
                max(1, _report_count(item.variant.run_settings.epub_split_workers)),
            )
            for item in work_items
        ],
        default=1,
    )

    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    status_lock = threading.RLock()
    source_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_active: dict[int, int] = defaultdict(int)
    source_completed: dict[int, int] = defaultdict(int)
    source_failed_seen: dict[int, bool] = defaultdict(bool)

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        with status_lock:
            if progress_callback is not None:
                if dashboard is not None:
                    dashboard.set_task(cleaned)
                    _notify_progress_callback(progress_callback, dashboard.render())
                else:
                    _notify_progress_callback(progress_callback, cleaned)
                return
            typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = run_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, counts["wing_backlog"])
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - run_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    item_by_global_index: dict[int, _AllMethodGlobalWorkItem] = {
        item.global_dispatch_index: item for item in work_items
    }
    variant_rows: list[dict[str, Any]] = []

    def _annotate_prediction_row(
        *,
        item: _AllMethodGlobalWorkItem,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(row)
        payload["global_dispatch_index"] = item.global_dispatch_index
        payload["source_position"] = item.source_position
        payload["source_group_key"] = item.source_group_key
        payload["source_slug"] = item.source_group_key
        payload["source_file"] = str(item.source_file)
        payload["source_file_name"] = item.source_file_name
        payload["gold_spans_path"] = str(item.gold_spans_path)
        payload["source_config_index"] = item.config_index
        payload["source_config_total"] = item.config_total
        payload["source_shard_index"] = item.source_shard_index + 1
        payload["source_shard_total"] = max(1, _report_count(item.source_shard_total))
        payload["source_estimated_seconds"] = item.source_estimated_seconds
        payload["source_estimate_basis"] = item.source_estimate_basis
        payload["_source_root"] = str(item.source_root)
        payload["_source_processed_root"] = str(item.source_processed_root)
        payload["_canonical_alignment_cache_dir"] = str(item.canonical_alignment_cache_dir)
        return payload

    def _latest_rows_by_dispatch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            dispatch_index = _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            latest_by_index[dispatch_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _mark_item_started(item: _AllMethodGlobalWorkItem, *, dashboard_tracking: bool) -> None:
        if not dashboard_tracking or dashboard is None:
            return
        source_position = item.source_position
        if source_active[source_position] <= 0:
            dashboard.start_source(source_position)
        source_active[source_position] += 1
        dashboard.start_config(
            source_index=source_position,
            config_index=item.config_index,
            config_total=max(1, item.config_total),
            config_slug=item.variant.slug,
        )

    def _mark_item_finished(
        item: _AllMethodGlobalWorkItem,
        *,
        success: bool,
        dashboard_tracking: bool,
    ) -> None:
        source_position = item.source_position
        source_active[source_position] = max(0, source_active[source_position] - 1)
        source_completed[source_position] += 1
        if not success:
            source_failed_seen[source_position] = True
        if not dashboard_tracking or dashboard is None:
            return
        dashboard.complete_config(
            source_index=source_position,
            success=success,
            config_index=item.config_index,
        )
        expected_total = max(0, _report_count(source_totals.get(source_position)))
        if (
            expected_total > 0
            and source_active[source_position] == 0
            and source_completed[source_position] >= expected_total
        ):
            dashboard.finish_source(
                source_position,
                failed=bool(source_failed_seen[source_position]),
            )

    def _run_serial_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for item in items:
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {item.variant.slug} [{item.source_file_name}] | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=item.gold_spans_path,
                source_file=item.source_file,
                variant=item.variant,
                config_index=item.global_dispatch_index,
                total_variants=max(1, total_planned_config_runs),
                root_output_dir=item.source_root,
                scratch_root=item.source_root / ".scratch",
                processed_output_root=item.source_processed_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=item.canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            row = _annotate_prediction_row(item=item, row=row)
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            _mark_item_finished(
                item,
                success=success,
                dashboard_tracking=dashboard_tracking,
            )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current

        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_items(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[_AllMethodGlobalWorkItem, float]] = {}
        worker_limit = min(effective_inflight_pipelines, max(1, len(items)))
        scheduler_base_target = min(
            max(1, total_planned_config_runs),
            effective_split_phase_slots + effective_wing_backlog_target,
        )
        scheduler_smart_enabled = bool(effective_smart_scheduler)

        try:
            executor = (
                _create_all_method_process_pool_executor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            item: _AllMethodGlobalWorkItem,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(item.global_dispatch_index, None)
            scheduler_event_offsets.pop(item.global_dispatch_index, None)
            _mark_item_finished(item, success=success, dashboard_tracking=dashboard_tracking)
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            item = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=item.gold_spans_path,
                    source_file=item.source_file,
                    variant=item.variant,
                    config_index=item.global_dispatch_index,
                    total_variants=max(1, total_planned_config_runs),
                    root_output_dir=item.source_root,
                    scratch_root=item.source_root / ".scratch",
                    processed_output_root=item.source_processed_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=item.canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=item.global_dispatch_index,
                    config_dir_name=_all_method_config_dir_name(
                        item.global_dispatch_index,
                        item.variant,
                    ),
                    variant=item.variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                return True

            futures[future] = (item, time.monotonic())
            scheduler_phase_by_config[item.global_dispatch_index] = "prep"
            scheduler_event_offsets[item.global_dispatch_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_planned_config_runs),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    item.global_dispatch_index
                    for item, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception:
                        scheduler_smart_enabled = False
                counts = _compute_scheduler_counts(
                    {
                        item.global_dispatch_index
                        for item, _submitted in futures.values()
                    }
                )
                if dashboard_tracking and dashboard is not None:
                    for active_item, _submitted in futures.values():
                        dashboard.set_config_phase(
                            source_index=active_item.source_position,
                            config_index=active_item.config_index,
                            phase=scheduler_phase_by_config.get(
                                active_item.global_dispatch_index,
                                "prep",
                            ),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            item.global_dispatch_index
                            for item, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    item, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=item.global_dispatch_index,
                            config_dir_name=_all_method_config_dir_name(
                                item.global_dispatch_index,
                                item.variant,
                            ),
                            variant=item.variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, _AllMethodGlobalWorkItem, float]] = []
                for future, (item, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, item, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1].global_dispatch_index)
                for timed_out_future, item, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=item.global_dispatch_index,
                        config_dir_name=_all_method_config_dir_name(
                            item.global_dispatch_index,
                            item.variant,
                        ),
                        variant=item.variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if futures:
                    requeued = sorted(
                        [item for item, _submitted in futures.values()],
                        key=lambda item: item.global_dispatch_index,
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                shutdown_fn = getattr(executor, "shutdown", None)
                if callable(shutdown_fn):
                    try:
                        shutdown_fn(wait=False, cancel_futures=True)
                    except TypeError:
                        shutdown_fn(wait=False)
                try:
                    executor = _create_all_method_process_pool_executor(
                        max_workers=worker_limit
                    )
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_items(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            shutdown_fn = getattr(executor, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    shutdown_fn(wait=True, cancel_futures=False)
                except TypeError:
                    shutdown_fn(wait=True)

    _run_parallel_items(work_items, dashboard_tracking=True)
    variant_rows = _latest_rows_by_dispatch(variant_rows)
    initial_failed_indices = [
        _report_count(
            row.get("global_dispatch_index", row.get("config_index"))
        )
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                item_by_global_index[index]
                for index in remaining_failed_indices
                if index in item_by_global_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_items(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_dispatch(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(
                        row.get("global_dispatch_index", row.get("config_index"))
                    )
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )

    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )

    scheduler_utilization_pct = (
        (scheduler_busy_seconds / scheduler_capacity_seconds) * 100.0
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_avg_wing_backlog = (
        scheduler_wing_area_seconds / scheduler_capacity_seconds
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_summary: dict[str, Any] = {
        "mode": "smart" if bool(effective_smart_scheduler) else "fixed",
        "source_count": max(1, total_targets),
        "configured_inflight_pipelines": configured_inflight_pipelines,
        "effective_inflight_pipelines": effective_inflight_pipelines,
        "split_phase_slots_requested": requested_split_phase_slots,
        "split_phase_slots": effective_split_phase_slots,
        "split_phase_slot_mode": split_phase_slot_mode,
        "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
        "wing_backlog_target": effective_wing_backlog_target,
        "split_worker_cap_per_config": split_worker_cap_per_config,
        "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
        "split_worker_cap_by_memory": split_worker_guard.get("split_worker_cap_by_memory"),
        "eval_tail_headroom_mode": eval_tail_headroom_mode,
        "eval_tail_headroom_configured": configured_eval_tail_headroom,
        "eval_tail_headroom_effective": effective_eval_tail_headroom,
        "max_active_during_eval": max_active_during_eval,
        "adaptive_overcommit_limit": adaptive_overcommit_limit,
        "adaptive_max_guard_target": adaptive_max_guard_target,
        "source_parallelism_effective": 1,
        "cpu_budget_per_source": scheduler_cpu_budget_per_source,
        "cpu_budget_total": scheduler_cpu_budget_total,
        "max_eval_tail_pipelines": effective_eval_tail_headroom,
        "smart_tail_buffer_slots": (
            effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
        ),
        "smart_scheduler_enabled": bool(effective_smart_scheduler),
        "config_timeout_seconds": effective_config_timeout_seconds,
        "failed_retry_limit": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "heavy_slot_capacity_seconds": scheduler_capacity_seconds,
        "heavy_slot_busy_seconds": scheduler_busy_seconds,
        "heavy_slot_utilization_pct": scheduler_utilization_pct,
        "avg_wing_backlog": scheduler_avg_wing_backlog,
        "max_wing_backlog": scheduler_max_wing_backlog,
        "idle_gap_seconds": scheduler_idle_gap_seconds,
        "max_active_pipelines_observed": scheduler_max_active_pipelines,
        "max_eval_active_observed": scheduler_max_eval_active,
        "adaptive_admission_adjustments": scheduler_admission_adjustments,
        "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
        "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
        "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
        "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
        "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
        "timeseries_path": str(scheduler_timeseries_path),
        "timeseries_row_count": scheduler_timeseries_rows_written,
        "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
        "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
        "cpu_utilization_source": scheduler_cpu_source,
        "cpu_utilization_samples": scheduler_cpu_samples_collected,
        "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        "scheduler_scope": "global_config_queue",
    }

    variant_rows = _latest_rows_by_dispatch(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=resolved_canonical_cache_root / "__global__",
    )

    for row in prediction_success_rows:
        source_root_raw = str(row.get("_source_root") or "").strip()
        if not source_root_raw:
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Source root is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=Path(source_root_raw),
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        gold_spans_path = Path(str(row.get("gold_spans_path") or "").strip())
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(
            _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            for row in item[1]
        ),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            ),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue

        source_root = Path(str(representative_row.get("_source_root") or ""))
        source_processed_root = Path(
            str(representative_row.get("_source_processed_root") or "")
        )
        canonical_alignment_cache_dir = Path(
            str(representative_row.get("_canonical_alignment_cache_dir") or "")
        )
        representative_eval_output_dir = source_root / representative_config_dir
        representative_processed_output_dir = source_processed_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=source_root,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )
        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=Path(str(representative_row.get("gold_spans_path") or "")),
                source_file=Path(str(representative_row.get("source_file") or "")),
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(representative_row.get("source_file") or ""),
                    "gold_spans_path": str(representative_row.get("gold_spans_path") or ""),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0
        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(
                    result_row.get("global_dispatch_index", result_row.get("config_index"))
                )
                == _report_count(
                    representative_row.get(
                        "global_dispatch_index",
                        representative_row.get("config_index"),
                    )
                )
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0
            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                source_root,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                source_root,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    source_rows = _write_all_method_source_reports_from_global_rows(
        target_variants=target_variants,
        source_job_plans=source_job_plans,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        successful_rows=successful_rows,
        failed_rows=failed_rows,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        eval_signature_cache_dir=eval_signature_cache_dir,
        scheduler_summary=scheduler_summary,
        retry_failed_configs_requested=effective_retry_failed_configs,
        retry_passes_executed=retry_passes_executed,
        retry_recovered_configs=retry_recovered_configs,
    )

    successful_source_count = sum(
        1 for row in source_rows if str(row.get("status", "")).lower() == "ok"
    )
    total_completed_config_runs = sum(
        _report_count(row.get("variant_count_completed")) for row in source_rows
    )
    total_successful_config_runs = sum(
        _report_count(row.get("variant_count_successful")) for row in source_rows
    )
    total_failed_config_runs = max(
        0,
        total_completed_config_runs - total_successful_config_runs,
    )
    total_evaluation_signatures_unique = sum(
        _report_count(row.get("evaluation_signatures_unique")) for row in source_rows
    )
    total_evaluation_runs_executed = sum(
        _report_count(row.get("evaluation_runs_executed")) for row in source_rows
    )
    total_evaluation_results_reused_in_run = sum(
        _report_count(row.get("evaluation_results_reused_in_run"))
        for row in source_rows
    )
    total_evaluation_results_reused_cross_run = sum(
        _report_count(row.get("evaluation_results_reused_cross_run"))
        for row in source_rows
    )
    total_prediction_signatures_unique = sum(
        _report_count(row.get("prediction_signatures_unique")) for row in source_rows
    )
    total_prediction_runs_executed = sum(
        _report_count(row.get("prediction_runs_executed")) for row in source_rows
    )
    total_prediction_results_reused_in_run = sum(
        _report_count(row.get("prediction_results_reused_in_run"))
        for row in source_rows
    )
    total_prediction_results_reused_cross_run = sum(
        _report_count(row.get("prediction_results_reused_cross_run"))
        for row in source_rows
    )
    total_split_convert_input_groups = sum(
        _report_count(row.get("split_convert_input_groups")) for row in source_rows
    )
    total_split_convert_reuse_candidates = sum(
        _report_count(row.get("split_convert_reuse_candidates")) for row in source_rows
    )
    total_split_convert_reuse_safe_candidates = sum(
        _report_count(row.get("split_convert_reuse_safe_candidates"))
        for row in source_rows
    )
    total_split_convert_reuse_blocked = sum(
        _report_count(row.get("split_convert_reuse_blocked_by_prediction_variance"))
        for row in source_rows
    )
    run_wall_seconds = max(0.0, time.monotonic() - run_started)

    source_timing_values: list[tuple[dict[str, Any], float]] = []
    config_total_seconds = 0.0
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is not None:
            source_timing_values.append((row, source_seconds))
        config_seconds = _report_optional_metric(
            timing_summary.get("config_total_seconds")
        )
        if config_seconds is not None:
            config_total_seconds += config_seconds
    source_total_seconds = sum(seconds for _row, seconds in source_timing_values)
    source_average_seconds = (
        source_total_seconds / len(source_timing_values) if source_timing_values else None
    )
    config_average_seconds = (
        config_total_seconds / total_successful_config_runs
        if total_successful_config_runs > 0
        else None
    )
    slowest_source_row = (
        max(source_timing_values, key=lambda item: item[1])[0]
        if source_timing_values
        else None
    )
    slowest_source_seconds = (
        max(seconds for _row, seconds in source_timing_values)
        if source_timing_values
        else None
    )
    slowest_config_name: str | None = None
    slowest_config_seconds: float | None = None
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        candidate_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if candidate_seconds is None:
            continue
        candidate_dir = str(timing_summary.get("slowest_config_dir") or "").strip()
        if not candidate_dir:
            continue
        candidate_name = f"{row.get('source_slug', '')}/{candidate_dir}".strip("/")
        if slowest_config_seconds is None or candidate_seconds > slowest_config_seconds:
            slowest_config_seconds = candidate_seconds
            slowest_config_name = candidate_name

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "matched_target_count": total_targets,
        "unmatched_target_count": len(unmatched_targets),
        "scheduler_scope": "global_config_queue",
        "source_schedule_strategy": resolved_source_scheduling,
        "source_shard_threshold_seconds": resolved_source_shard_threshold_seconds,
        "source_shard_max_parts": resolved_source_shard_max_parts,
        "source_shard_min_variants": resolved_source_shard_min_variants,
        "source_job_count_planned": len(source_job_plans),
        "source_schedule_plan": [
            {
                "dispatch_index": dispatch_index + 1,
                "source_position": plan.source_position + 1,
                "source_group_key": plan.source_group_key,
                "source_file": str(plan.source_file),
                "source_file_name": plan.source_display_name,
                "source_slug": plan.source_slug,
                "source_shard_index": plan.shard_index + 1,
                "source_shard_total": max(1, _report_count(plan.shard_total)),
                "variant_count": len(plan.variants),
                "estimated_seconds": plan.estimated_seconds,
                "estimate_basis": plan.estimate_basis,
            }
            for dispatch_index, plan in enumerate(source_job_plans)
        ],
        "global_queue_schedule_plan": [
            {
                "dispatch_index": item.global_dispatch_index,
                "source_position": item.source_position + 1,
                "source_group_key": item.source_group_key,
                "source_file": str(item.source_file),
                "source_file_name": item.source_file_name,
                "source_slug": item.source_slug,
                "source_shard_index": item.source_shard_index + 1,
                "source_shard_total": max(1, _report_count(item.source_shard_total)),
                "source_config_index": item.config_index,
                "source_config_total": item.config_total,
                "variant_slug": item.variant.slug,
                "estimated_seconds": item.source_estimated_seconds,
                "estimate_basis": item.source_estimate_basis,
            }
            for item in work_items
        ],
        "source_parallelism_configured": source_parallelism_configured,
        "source_parallelism_effective": source_parallelism_effective,
        "total_config_runs_planned": total_planned_config_runs,
        "total_config_runs_completed": total_completed_config_runs,
        "total_config_runs_successful": total_successful_config_runs,
        "global_queue_planned_configs": total_planned_config_runs,
        "global_queue_completed_configs": total_completed_config_runs,
        "global_queue_failed_configs": total_failed_config_runs,
        "evaluation_signatures_unique": total_evaluation_signatures_unique,
        "evaluation_runs_executed": total_evaluation_runs_executed,
        "evaluation_results_reused_in_run": total_evaluation_results_reused_in_run,
        "evaluation_results_reused_cross_run": total_evaluation_results_reused_cross_run,
        "prediction_signatures_unique": total_prediction_signatures_unique,
        "prediction_runs_executed": total_prediction_runs_executed,
        "prediction_results_reused_in_run": total_prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": total_prediction_results_reused_cross_run,
        "split_convert_input_groups": total_split_convert_input_groups,
        "split_convert_reuse_candidates": total_split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": total_split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": total_split_convert_reuse_blocked,
        "prediction_reuse_key_schema_version": (
            ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
        ),
        "split_convert_input_key_schema_version": (
            ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
        ),
        "successful_source_count": successful_source_count,
        "failed_source_count": total_targets - successful_source_count,
        "config_timeout_seconds": effective_config_timeout_seconds,
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "canonical_alignment_cache_root": str(resolved_canonical_cache_root),
        "prediction_reuse_cache_root": str(resolved_prediction_reuse_cache_root),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
        "timing_summary": {
            "run_wall_seconds": run_wall_seconds,
            "source_total_seconds": source_total_seconds,
            "source_average_seconds": source_average_seconds,
            "config_total_seconds": config_total_seconds,
            "config_average_seconds": config_average_seconds,
            "slowest_source": (
                str(slowest_source_row.get("source_file", ""))
                if isinstance(slowest_source_row, dict)
                else None
            ),
            "slowest_source_seconds": slowest_source_seconds,
            "slowest_config": slowest_config_name,
            "slowest_config_seconds": slowest_config_seconds,
        },
        "scheduler_summary": dict(scheduler_summary),
        "sources": source_rows,
        "unmatched": [
            {
                "gold_spans_path": str(unmatched.gold_spans_path),
                "gold_display": unmatched.gold_display,
                "reason": unmatched.reason,
                "source_hint": unmatched.source_hint,
            }
            for unmatched in unmatched_targets
        ],
    }

    history_csv_path = history_csv_for_output(
        processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    _refresh_dashboard_after_history_write(
        csv_path=history_csv_path,
        output_root=resolved_dashboard_output_root,
        golden_root=golden_root,
        dashboard_out_dir=(
            history_root_for_output(resolved_dashboard_output_root) / "dashboard"
            if resolved_dashboard_output_root is not None
            else None
        ),
        reason="all-method benchmark global queue batch append",
    )

    report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
    report_md_path.write_text(
        _render_all_method_multi_source_report_md(report_payload),
        encoding="utf-8",
    )

    completion_color = (
        typer.colors.GREEN
        if successful_source_count == total_targets
        and total_successful_config_runs == total_planned_config_runs
        else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"sources {successful_source_count}/{total_targets}, "
            f"configs {total_successful_config_runs}/{total_planned_config_runs}."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path


def _run_all_method_benchmark_multi_source(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    _normalize_all_method_scheduler_scope(scheduler_scope)
    return _run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=unmatched_targets,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        golden_root=golden_root,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
        progress_callback=progress_callback,
        dashboard=dashboard,
        max_parallel_sources=max_parallel_sources,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        config_timeout_seconds=config_timeout_seconds,
        retry_failed_configs=retry_failed_configs,
        source_scheduling=source_scheduling,
        source_shard_threshold_seconds=source_shard_threshold_seconds,
        source_shard_max_parts=source_shard_max_parts,
        source_shard_min_variants=source_shard_min_variants,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        canonical_alignment_cache_root=canonical_alignment_cache_root,
        prediction_reuse_cache_root=prediction_reuse_cache_root,
        dashboard_output_root=dashboard_output_root,
        require_process_workers=require_process_workers,
    )


def _run_all_method_benchmark(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variants: list[AllMethodVariant],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    dashboard_source_index: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    refresh_dashboard_after_source: bool = True,
    source_parallelism_effective: int | None = 1,
    canonical_alignment_cache_dir_override: Path | None = None,
    prediction_reuse_cache_dir_override: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    source_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = root_output_dir / ".scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_dir = (
        canonical_alignment_cache_dir_override
        if canonical_alignment_cache_dir_override is not None
        else (root_output_dir / ".cache" / "canonical_alignment")
    )
    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir_override.expanduser()
        if prediction_reuse_cache_dir_override is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    total_variants = len(variants)
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_source_parallelism = scheduler_runtime.source_parallelism_effective
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=source_parallelism_effective,
    )
    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(variant.run_settings.workers)),
                max(1, _report_count(variant.run_settings.pdf_split_workers)),
                max(1, _report_count(variant.run_settings.epub_split_workers)),
            )
            for variant in variants
        ],
        default=1,
    )
    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        if progress_callback is not None:
            if _is_structured_progress_message(cleaned):
                _notify_progress_callback(progress_callback, cleaned)
                return
            if dashboard is not None:
                dashboard.set_task(cleaned)
                _notify_progress_callback(progress_callback, dashboard.render())
                return
            _notify_progress_callback(progress_callback, cleaned)
            return
        typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    variant_rows: list[dict[str, Any]] = []
    indexed_variants = list(enumerate(variants, start=1))
    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_smart_enabled = bool(effective_smart_scheduler)
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = source_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Ignoring malformed scheduler event in %s: %s",
                            event_path,
                            line[:160],
                        )
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(
            scheduler_max_wing_backlog,
            counts["wing_backlog"],
        )
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - source_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler time-series write failure for %s: %s",
                scheduler_timeseries_path,
                exc,
            )
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    def _compute_scheduler_metrics_from_event_files(
        *,
        source_end_monotonic: float,
    ) -> dict[str, float | int] | None:
        rows: list[tuple[float, str, int]] = []
        for event_path in sorted(scheduler_events_dir.glob("config_*.jsonl")):
            try:
                lines = event_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_name = str(payload.get("event") or "").strip()
                if not event_name:
                    continue
                event_time = _report_optional_metric(payload.get("monotonic_seconds"))
                event_index = _report_count(payload.get("config_index"))
                if event_time is None or event_index <= 0:
                    continue
                rows.append((event_time, event_name, event_index))
        if not rows:
            return None

        rows.sort(key=lambda item: item[0])
        phases: dict[int, str] = {}
        started_configs: set[int] = set()
        capacity_seconds = 0.0
        busy_seconds = 0.0
        idle_gap_seconds = 0.0
        wing_area_seconds = 0.0
        max_wing_backlog = 0
        max_active_pipelines = 0
        max_eval_active = 0

        def _counts() -> dict[str, int]:
            heavy_active = 0
            split_wait = 0
            prep_active = 0
            post_active = 0
            evaluate_active = 0
            for phase in phases.values():
                if phase == "split_active":
                    heavy_active += 1
                elif phase == "split_wait":
                    split_wait += 1
                elif phase == "post":
                    post_active += 1
                elif phase == "evaluate":
                    evaluate_active += 1
                elif phase == "done":
                    continue
                else:
                    prep_active += 1
            wing_backlog = split_wait + prep_active
            active = (
                heavy_active
                + split_wait
                + prep_active
                + post_active
                + evaluate_active
            )
            return {
                "heavy_active": heavy_active,
                "evaluate_active": evaluate_active,
                "wing_backlog": wing_backlog,
                "active": active,
            }

        previous_time = rows[0][0]
        for event_time, event_name, event_index in rows:
            delta = max(0.0, event_time - previous_time)
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += delta
            wing_area_seconds += float(counts["wing_backlog"]) * delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])
            previous_time = event_time

            mapped_phase = _scheduler_phase_for_event(event_name)
            if event_name == "config_started":
                started_configs.add(event_index)
            if mapped_phase is not None:
                phases[event_index] = mapped_phase
            if event_name == "config_finished":
                phases[event_index] = "done"

        tail_delta = max(0.0, source_end_monotonic - previous_time)
        if tail_delta > 0:
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * tail_delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * tail_delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += tail_delta
            wing_area_seconds += float(counts["wing_backlog"]) * tail_delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])

        return {
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "idle_gap_seconds": idle_gap_seconds,
            "wing_backlog_area_seconds": wing_area_seconds,
            "max_wing_backlog": max_wing_backlog,
            "max_active_pipelines_observed": max_active_pipelines,
            "max_eval_active_observed": max_eval_active,
        }

    def _finalize_scheduler_metrics() -> dict[str, Any]:
        event_metrics = _compute_scheduler_metrics_from_event_files(
            source_end_monotonic=time.monotonic()
        )
        capacity_seconds = scheduler_capacity_seconds
        busy_seconds = scheduler_busy_seconds
        idle_gap_seconds = scheduler_idle_gap_seconds
        wing_area_seconds = scheduler_wing_area_seconds
        max_wing_backlog = scheduler_max_wing_backlog
        max_active = scheduler_max_active_pipelines
        max_eval_active = scheduler_max_eval_active
        if isinstance(event_metrics, dict):
            capacity_seconds = _report_metric(
                event_metrics.get("heavy_slot_capacity_seconds")
            )
            busy_seconds = _report_metric(event_metrics.get("heavy_slot_busy_seconds"))
            idle_gap_seconds = _report_metric(event_metrics.get("idle_gap_seconds"))
            wing_area_seconds = _report_metric(event_metrics.get("wing_backlog_area_seconds"))
            max_wing_backlog = max(
                max_wing_backlog,
                _report_count(event_metrics.get("max_wing_backlog")),
            )
            max_active = max(
                max_active,
                _report_count(event_metrics.get("max_active_pipelines_observed")),
            )
            max_eval_active = max(
                max_eval_active,
                _report_count(event_metrics.get("max_eval_active_observed")),
            )
        utilization_pct = (
            (busy_seconds / capacity_seconds) * 100.0
            if capacity_seconds > 0
            else 0.0
        )
        avg_wing_backlog = (
            wing_area_seconds / capacity_seconds
            if capacity_seconds > 0
            else 0.0
        )
        return {
            "mode": "smart" if scheduler_smart_enabled else "fixed",
            "configured_inflight_pipelines": configured_inflight_pipelines,
            "effective_inflight_pipelines": effective_inflight_pipelines,
            "split_phase_slots_requested": requested_split_phase_slots,
            "split_phase_slots": effective_split_phase_slots,
            "split_phase_slot_mode": split_phase_slot_mode,
            "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
            "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
            "split_worker_cap_per_config": split_worker_cap_per_config,
            "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
            "split_worker_cap_by_memory": split_worker_guard.get(
                "split_worker_cap_by_memory"
            ),
            "wing_backlog_target": effective_wing_backlog_target,
            "eval_tail_headroom_mode": eval_tail_headroom_mode,
            "eval_tail_headroom_configured": configured_eval_tail_headroom,
            "eval_tail_headroom_effective": effective_eval_tail_headroom,
            "max_active_during_eval": max_active_during_eval,
            "adaptive_overcommit_limit": adaptive_overcommit_limit,
            "adaptive_max_guard_target": adaptive_max_guard_target,
            "source_parallelism_effective": scheduler_source_parallelism,
            "cpu_budget_per_source": scheduler_cpu_budget_per_source,
            "cpu_budget_total": scheduler_cpu_budget_total,
            "max_eval_tail_pipelines": effective_eval_tail_headroom,
            "smart_tail_buffer_slots": (
                effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
            ),
            "smart_scheduler_enabled": bool(effective_smart_scheduler),
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "heavy_slot_utilization_pct": utilization_pct,
            "avg_wing_backlog": avg_wing_backlog,
            "max_wing_backlog": max_wing_backlog,
            "idle_gap_seconds": idle_gap_seconds,
            "max_active_pipelines_observed": max_active,
            "max_eval_active_observed": max_eval_active,
            "adaptive_admission_adjustments": scheduler_admission_adjustments,
            "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
            "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
            "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
            "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
            "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
            "timeseries_path": str(scheduler_timeseries_path),
            "timeseries_row_count": scheduler_timeseries_rows_written,
            "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
            "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
            "cpu_utilization_source": scheduler_cpu_source,
            "cpu_utilization_samples": scheduler_cpu_samples_collected,
            "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        }

    def _shutdown_parallel_executor(
        executor: Any,
        *,
        terminate_workers: bool,
    ) -> None:
        if terminate_workers:
            worker_map = getattr(executor, "_processes", None)
            if isinstance(worker_map, dict):
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        if process.is_alive():
                            process.terminate()
                    except Exception:
                        continue
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        process.join(timeout=1.0)
                        if process.is_alive() and hasattr(process, "kill"):
                            process.kill()
                    except Exception:
                        continue
        shutdown_fn = getattr(executor, "shutdown", None)
        if not callable(shutdown_fn):
            return
        try:
            shutdown_fn(wait=not terminate_workers, cancel_futures=terminate_workers)
        except TypeError:
            shutdown_fn(wait=not terminate_workers)
        except Exception:
            return

    def _latest_rows_by_config(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            config_index = _report_count(row.get("config_index"))
            latest_by_index[config_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _run_serial_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for config_index, variant in items:
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {variant.slug} | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                variant=variant,
                config_index=config_index,
                total_variants=max(1, total_variants),
                root_output_dir=root_output_dir,
                scratch_root=scratch_root,
                processed_output_root=processed_output_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        f"Completed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: {variant.slug}"
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_smart_enabled
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current
        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[int, AllMethodVariant, float]] = {}
        worker_limit = min(effective_inflight_pipelines, len(items))
        scheduler_base_target = min(
            total_variants,
            effective_split_phase_slots + effective_wing_backlog_target,
        )

        try:
            executor = (
                _create_all_method_process_pool_executor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            config_index: int,
            variant: AllMethodVariant,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(config_index, None)
            scheduler_event_offsets.pop(config_index, None)
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                            f"{variant.slug}"
                        )
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            config_index, variant = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=gold_spans_path,
                    source_file=source_file,
                    variant=variant,
                    config_index=config_index,
                    total_variants=max(1, total_variants),
                    root_output_dir=root_output_dir,
                    scratch_root=scratch_root,
                    processed_output_root=processed_output_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=config_index,
                    config_dir_name=_all_method_config_dir_name(config_index, variant),
                    variant=variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(
                    config_index=config_index,
                    variant=variant,
                    row=row,
                )
                return True

            futures[future] = (config_index, variant, time.monotonic())
            scheduler_phase_by_config[config_index] = "prep"
            scheduler_event_offsets[config_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_variants),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    config_index for config_index, _variant, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception as exc:  # noqa: BLE001
                        if scheduler_smart_enabled:
                            scheduler_smart_enabled = False
                            _emit_status(
                                (
                                    "Smart scheduler telemetry failed "
                                    f"({exc}); falling back to fixed queue refill."
                                ),
                                color=typer.colors.YELLOW,
                            )
                counts = _compute_scheduler_counts(
                    {
                        config_index
                        for config_index, _variant, _submitted in futures.values()
                    }
                )
                if (
                    dashboard_tracking
                    and dashboard is not None
                    and dashboard_source_index is not None
                ):
                    for active_index in sorted(active_indices):
                        dashboard.set_config_phase(
                            source_index=dashboard_source_index,
                            config_index=active_index,
                            phase=scheduler_phase_by_config.get(active_index, "prep"),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            config_index
                            for config_index, _variant, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    config_index, variant, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=config_index,
                            config_dir_name=_all_method_config_dir_name(config_index, variant),
                            variant=variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, int, AllMethodVariant, float]] = []
                for future, (config_index, variant, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, config_index, variant, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1])
                for timed_out_future, config_index, variant, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=config_index,
                        config_dir_name=_all_method_config_dir_name(config_index, variant),
                        variant=variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if futures:
                    requeued = sorted(
                        [
                            (config_index, variant)
                            for config_index, variant, _submitted in futures.values()
                        ],
                        key=lambda item: item[0],
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                _shutdown_parallel_executor(executor, terminate_workers=True)
                try:
                    executor = _create_all_method_process_pool_executor(
                        max_workers=worker_limit
                    )
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_variants(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            _shutdown_parallel_executor(executor, terminate_workers=False)

    _run_parallel_variants(indexed_variants, dashboard_tracking=True)
    variant_rows = _latest_rows_by_config(variant_rows)
    initial_failed_indices = [
        _report_count(row.get("config_index"))
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        variant_by_index = {config_index: variant for config_index, variant in indexed_variants}
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                (config_index, variant_by_index[config_index])
                for config_index in remaining_failed_indices
                if config_index in variant_by_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_variants(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_config(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(row.get("config_index"))
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )
    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )
    scheduler_summary = _finalize_scheduler_metrics()
    scheduler_summary["config_timeout_seconds"] = effective_config_timeout_seconds
    scheduler_summary["failed_retry_limit"] = effective_retry_failed_configs
    scheduler_summary["retry_passes_executed"] = retry_passes_executed
    scheduler_summary["retry_recovered_configs"] = retry_recovered_configs

    variant_rows = _latest_rows_by_config(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    prediction_reuse_summary = _all_method_prediction_reuse_summary(
        prediction_success_rows
    )

    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=canonical_alignment_cache_dir,
    )

    for row in prediction_success_rows:
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(_report_count(row.get("config_index")) for row in item[1]),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(row.get("config_index")),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        representative_eval_output_dir = root_output_dir / representative_config_dir
        representative_processed_output_dir = processed_output_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )

        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(source_file),
                    "gold_spans_path": str(gold_spans_path),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0

        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(result_row.get("config_index"))
                == _report_count(representative_row.get("config_index"))
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0

            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                root_output_dir,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                root_output_dir,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    failed_rows.sort(key=lambda row: _report_count(row.get("config_index")))
    successful_rows.sort(
        key=lambda row: (
            _report_metric(row.get("f1")),
            _report_metric(row.get("practical_f1")),
            _report_metric(row.get("precision")),
            _report_metric(row.get("recall")),
        ),
        reverse=True,
    )
    for rank, row in enumerate(successful_rows, start=1):
        row["rank"] = rank

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    successful_timing: list[tuple[dict[str, Any], float]] = []
    for row in successful_rows:
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        if row_total_seconds is None:
            row_total_seconds = _report_optional_metric(row.get("duration_seconds"))
        if row_total_seconds is None:
            continue
        row["timing"] = _timing_with_updates(
            row_timing,
            total_seconds=row_total_seconds,
        )
        successful_timing.append((row, row_total_seconds))

    source_wall_seconds = max(0.0, time.monotonic() - source_started)
    total_config_seconds = sum(seconds for _row, seconds in successful_timing)
    average_config_seconds = (
        total_config_seconds / len(successful_timing) if successful_timing else None
    )
    median_config_seconds = _median_metric(
        [seconds for _row, seconds in successful_timing]
    )
    slowest_config_row = (
        max(successful_timing, key=lambda item: item[1])[0] if successful_timing else None
    )
    slowest_config_seconds = (
        max(seconds for _row, seconds in successful_timing) if successful_timing else None
    )

    winner = successful_rows[0] if successful_rows else None
    final_rows = successful_rows + failed_rows

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source_file),
        "gold_spans_path": str(gold_spans_path),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "scheduler_scope": "per_source",
        "variant_count": total_variants,
        "successful_variants": len(successful_rows),
        "failed_variants": len(failed_rows),
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
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "prediction_reuse_cache_dir": str(prediction_reuse_cache_dir),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
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
        "scheduler": scheduler_summary,
        "variants": final_rows,
        "winner_by_f1": winner,
    }

    report_json_path = root_output_dir / "all_method_benchmark_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_report.md"
    report_md_path.write_text(
        _render_all_method_report_md(report_payload),
        encoding="utf-8",
    )

    if refresh_dashboard_after_source:
        history_csv_path = history_csv_for_output(
            processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        resolved_dashboard_output_root = (
            dashboard_output_root.expanduser()
            if dashboard_output_root is not None
            else None
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            output_root=resolved_dashboard_output_root,
            golden_root=golden_root,
            dashboard_out_dir=(
                history_root_for_output(resolved_dashboard_output_root) / "dashboard"
                if resolved_dashboard_output_root is not None
                else None
            ),
            reason="all-method benchmark source batch append",
        )

    completion_color = (
        typer.colors.GREEN if len(failed_rows) == 0 else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"{len(successful_rows)}/{total_variants} configs evaluated successfully."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        if successful_rows:
            typer.secho("Top configurations by strict F1:", fg=typer.colors.CYAN)
            for row in successful_rows[:3]:
                typer.echo(
                    (
                        f"  {row.get('rank')}) {row.get('config_dir')} "
                        f"p={_report_metric(row.get('precision')):.3f} "
                        f"r={_report_metric(row.get('recall')):.3f} "
                        f"f1={_report_metric(row.get('f1')):.3f}"
                    )
                )
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path

def _interactive_all_method_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    golden_root: Path | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
) -> None:
    resolved_golden_root = golden_root or DEFAULT_GOLDEN
    scope_choice = _menu_select(
        "Select all method benchmark scope:",
        menu_help=(
            "Choose one gold/source pair (current behavior) or fan out "
            "across all freeform gold exports that match importable data/input files."
        ),
        choices=[
            questionary.Choice("Single golden set", value="single"),
            questionary.Choice(
                "All golden sets with matching input files",
                value="all_matched",
            ),
        ],
    )
    if scope_choice in {None, BACK_ACTION}:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    scope_all_matched = scope_choice == "all_matched"
    if scope_all_matched:
        targets, unmatched_targets = _resolve_all_method_targets(resolved_golden_root)
        if not targets:
            typer.secho(
                "No matched golden sets were found in data/input. Nothing to benchmark.",
                fg=typer.colors.YELLOW,
            )
            if unmatched_targets:
                typer.secho(
                    f"Skipped golden sets: {len(unmatched_targets)}",
                    fg=typer.colors.YELLOW,
                )
                for unmatched in unmatched_targets[:5]:
                    source_hint_text = unmatched.source_hint or "none"
                    typer.echo(
                        f"  - {unmatched.gold_display}: {unmatched.reason} "
                        f"(source hint: {source_hint_text})"
                    )
                if len(unmatched_targets) > 5:
                    typer.echo(
                        f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                    )
            return
    else:
        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=None,
            source_file=None,
            output_dir=resolved_golden_root,
            allow_cancel=True,
        )
        if resolved_inputs is None:
            return
        selected_gold, selected_source = resolved_inputs
        targets = [
            AllMethodTarget(
                gold_spans_path=selected_gold,
                source_file=selected_source,
                source_file_name=selected_source.name,
                gold_display=_display_gold_export_path(selected_gold, resolved_golden_root),
            )
        ]
        unmatched_targets = []

    include_markdown_extractors = _resolve_all_method_markdown_extractors_choice()
    include_deterministic_sweeps = _prompt_confirm(
        (
            "Try deterministic option sweeps too? (section detector, multi-recipe splitting, "
            "ingredient missing-unit policy, instruction step segmentation, time/temp/yield)"
        ),
        default=True,
    )
    if include_deterministic_sweeps is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    if include_deterministic_sweeps:
        missing: list[str] = []
        if not _all_method_optional_module_available("pysbd"):
            missing.append("pysbd (instruction step segmenter)")
        if not _all_method_optional_module_available("quantulum3"):
            missing.append("quantulum3 (time/temp backends)")
        if not _all_method_optional_module_available("pint"):
            missing.append("pint (temperature units)")
        if missing:
            typer.secho(
                "Deterministic sweeps note: optional deps missing, some variants will be skipped: "
                + ", ".join(missing),
                fg=typer.colors.BRIGHT_BLACK,
            )
    base_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=selected_benchmark_settings,
        include_codex_farm=False,
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_base_runs = sum(len(variants) for _target, variants in base_target_variants)
    if total_base_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return

    if include_markdown_extractors:
        typer.secho(
            (
                "All method includes markdown + markitdown extractor variants "
                f"(enabled via {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 and "
                f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1)."
            ),
            fg=typer.colors.YELLOW,
        )
    else:
        if markdown_epub_extractors_enabled():
            typer.secho(
                (
                    "All method excludes markdown + markitdown extractor variants by default. "
                    f"Set {ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                (
                    "Markdown + markitdown extractors are policy-locked off. "
                    f"Set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable "
                    "them, then set "
                    f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them in all method."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )

    if scope_all_matched:
        typer.secho(
            f"Matched golden sets: {len(targets)}",
            fg=typer.colors.CYAN,
        )
        skipped_color = typer.colors.YELLOW if unmatched_targets else typer.colors.BRIGHT_BLACK
        typer.secho(
            f"Skipped golden sets: {len(unmatched_targets)}",
            fg=skipped_color,
        )
        typer.secho(
            (
                "All method benchmark will run "
                f"{total_base_runs} configurations across {len(targets)} matched golden sets "
                "(Codex Farm excluded)."
            ),
            fg=typer.colors.CYAN,
        )
        if unmatched_targets:
            typer.secho("Skipped golden set samples:", fg=typer.colors.BRIGHT_BLACK)
            for unmatched in unmatched_targets[:5]:
                source_hint_text = unmatched.source_hint or "none"
                typer.echo(
                    f"  - {unmatched.gold_display}: {unmatched.reason} "
                    f"(source hint: {source_hint_text})"
                )
            if len(unmatched_targets) > 5:
                typer.echo(
                    f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                )
    else:
        selected_source = targets[0].source_file
        typer.secho(
            f"All method benchmark will run {total_base_runs} configurations (Codex Farm excluded).",
            fg=typer.colors.CYAN,
        )
        if selected_source.suffix.lower() == ".epub":
            typer.secho(
                (
                    "Dimensions: epub_extractor + unstructured parser/skip_headers/preprocess, "
                    "plus deterministic option sweeps when enabled."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                "Dimensions: non-EPUB source uses global benchmark run settings (plus sweeps when enabled).",
                fg=typer.colors.BRIGHT_BLACK,
            )
    typer.secho(
        "CodexFarm process selection is available for all-method runs.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        "All method benchmark uses canonical-text eval mode (extractor-independent).",
        fg=typer.colors.BRIGHT_BLACK,
    )

    all_method_codex_defaults_payload = {
        key: value
        for key, value in selected_benchmark_settings.model_dump(
            mode="json", exclude_none=True
        ).items()
        if key in RunSettings.model_fields
    }
    all_method_codex_defaults_payload.update(
        {
            "llm_recipe_pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "line_role_pipeline": LINE_ROLE_PIPELINE_ROUTE_V2,
            "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
            "atomic_block_splitter": str(
                all_method_codex_defaults_payload.get("atomic_block_splitter") or "off"
            ),
        }
    )
    all_method_codex_settings = choose_interactive_codex_surfaces(
        selected_settings=RunSettings.from_dict(
            all_method_codex_defaults_payload,
            warn_context="interactive all-method codex defaults",
        ),
        back_action=BACK_ACTION,
        surface_options=("recipe", "line_role", "knowledge"),
        prompt_codex_shard_plan_menu=_prompt_codex_shard_plan_menu,
    )
    if all_method_codex_settings is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    include_codex_requested = _all_method_settings_enable_any_codex(
        all_method_codex_settings
    )
    include_codex_effective, codex_warning = _resolve_all_method_codex_choice(
        include_codex_requested
    )
    if codex_warning:
        typer.secho(codex_warning, fg=typer.colors.YELLOW)

    benchmark_settings_for_variants = selected_benchmark_settings
    if include_codex_effective:
        _ensure_codex_farm_cmd_available(selected_benchmark_settings.codex_farm_cmd)
        all_method_codex_settings = choose_codex_ai_settings(
            selected_settings=all_method_codex_settings,
            menu_select=_menu_select,
            back_action=BACK_ACTION,
        )
        if all_method_codex_settings is None:
            typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
            return
        benchmark_settings_for_variants = all_method_codex_settings

    selected_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=benchmark_settings_for_variants,
        include_codex_farm=include_codex_effective,
        codex_variant_settings=(
            benchmark_settings_for_variants if include_codex_effective else None
        ),
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_selected_runs = sum(
        len(variants) for _target, variants in selected_target_variants
    )
    if total_selected_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return
    total_sources_selected = max(1, len(selected_target_variants))
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        total_sources_selected,
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=total_sources_selected,
        requested=max_parallel_sources,
    )
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_selected_runs,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    resolved_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    resolved_split_phase_slots = scheduler_runtime.split_phase_slots
    resolved_wing_backlog_target = scheduler_runtime.wing_backlog_target
    resolved_eval_tail_headroom_configured = (
        scheduler_runtime.eval_tail_headroom_configured
    )
    resolved_eval_tail_headroom_effective = (
        scheduler_runtime.eval_tail_headroom_effective
    )
    resolved_eval_tail_mode = scheduler_runtime.eval_tail_headroom_mode
    resolved_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    resolved_max_active_during_eval = scheduler_runtime.max_active_during_eval
    resolved_effective_inflight_pipelines = (
        scheduler_runtime.effective_inflight_pipelines
    )
    resolved_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    resolved_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    resolved_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_scheduler_scope = _normalize_all_method_scheduler_scope(scheduler_scope)
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    timeout_display = (
        f"{resolved_config_timeout_seconds}s"
        if resolved_config_timeout_seconds is not None
        else "off"
    )
    scheduler_mode = "smart" if resolved_smart_scheduler else "fixed"
    typer.secho(
        (
            "Scheduler: "
            f"scope={resolved_scheduler_scope}, "
            f"source parallel={source_parallelism_effective} "
            f"(configured {source_parallelism_configured}, "
            f"default {_all_method_default_parallel_sources_from_cpu()}), "
            f"source scheduling={resolved_source_scheduling}, "
            "source sharding threshold/max_parts/min_variants="
            f"{resolved_source_shard_threshold_seconds:.1f}/"
            f"{resolved_source_shard_max_parts}/"
            f"{resolved_source_shard_min_variants}, "
            f"mode={scheduler_mode}, "
            f"configured inflight={resolved_inflight_pipelines} "
            f"(default {ALL_METHOD_MAX_INFLIGHT_DEFAULT}), "
            f"effective inflight={resolved_effective_inflight_pipelines}, "
            f"split slots={resolved_split_phase_slots} "
            f"(default {ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT}), "
            f"eval headroom ({resolved_eval_tail_mode}) configured/effective="
            f"{resolved_eval_tail_headroom_configured}/"
            f"{resolved_eval_tail_headroom_effective}, "
            f"max active during eval={resolved_max_active_during_eval}, "
            f"cpu budget/source={resolved_cpu_budget_per_source}, "
            f"config timeout={timeout_display} "
            f"(default {ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT}s), "
            f"failed retries={resolved_retry_failed_configs} "
            f"(default {ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT}), "
            f"wing backlog={resolved_wing_backlog_target} "
            "(default split slots)"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    if scope_all_matched:
        proceed_prompt = (
            f"Proceed with {total_selected_runs} benchmark runs across "
            f"{len(targets)} matched golden sets?"
        )
    else:
        proceed_prompt = f"Proceed with {total_selected_runs} benchmark runs?"
    proceed = _prompt_confirm(
        proceed_prompt,
        default=False,
    )
    if proceed is not True:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    all_method_root = benchmark_eval_output / "all-method-benchmark"
    all_method_processed_root = (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
    )
    all_method_canonical_cache_root = _resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=all_method_root
    )
    typer.secho(
        (
            "All method canonical alignment cache root: "
            f"{all_method_canonical_cache_root}"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    status_initial = "Running all method benchmark..."
    status_prefix = "All method benchmark"

    if scope_all_matched:
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            selected_target_variants
        )
        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=all_method_root / PROCESSING_TIMESERIES_FILENAME,
            run=lambda update_progress: _run_all_method_benchmark_multi_source(
                target_variants=selected_target_variants,
                unmatched_targets=unmatched_targets,
                include_codex_farm_requested=include_codex_requested,
                include_codex_farm_effective=include_codex_effective,
                root_output_dir=all_method_root,
                processed_output_root=all_method_processed_root,
                golden_root=resolved_golden_root,
                overlap_threshold=0.5,
                force_source_match=False,
                progress_callback=update_progress,
                dashboard=dashboard,
                max_parallel_sources=max_parallel_sources,
                max_inflight_pipelines=resolved_inflight_pipelines,
                max_concurrent_split_phases=resolved_split_phase_slots,
                max_eval_tail_pipelines=max_eval_tail_pipelines,
                config_timeout_seconds=resolved_config_timeout_seconds,
                retry_failed_configs=resolved_retry_failed_configs,
                source_scheduling=resolved_source_scheduling,
                source_shard_threshold_seconds=resolved_source_shard_threshold_seconds,
                source_shard_max_parts=resolved_source_shard_max_parts,
                source_shard_min_variants=resolved_source_shard_min_variants,
                wing_backlog_target=resolved_wing_backlog_target,
                smart_scheduler=resolved_smart_scheduler,
                scheduler_scope=resolved_scheduler_scope,
                canonical_alignment_cache_root=all_method_canonical_cache_root,
                dashboard_output_root=processed_output_root,
            ),
        )
        typer.secho(
            f"All method benchmark summary report: {report_md_path}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"All method processing telemetry: {all_method_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    else:
        single_target = targets[0]
        single_variants = selected_target_variants[0][1]
        single_root = all_method_root / slugify_name(single_target.source_file.stem)
        single_processed_root = all_method_processed_root / slugify_name(
            single_target.source_file.stem
        )
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            [(single_target, single_variants)]
        )

        def _run_single_source(update_progress: Callable[[str], None]) -> Path:
            dashboard.start_source(0)
            dashboard.set_task(f"Running source 1/1: {single_target.source_file_name}")
            update_progress(dashboard.render())
            try:
                report_path = _run_all_method_benchmark(
                    gold_spans_path=single_target.gold_spans_path,
                    source_file=single_target.source_file,
                    variants=single_variants,
                    include_codex_farm_requested=include_codex_requested,
                    include_codex_farm_effective=include_codex_effective,
                    root_output_dir=single_root,
                    processed_output_root=single_processed_root,
                    golden_root=resolved_golden_root,
                    overlap_threshold=0.5,
                    force_source_match=False,
                    progress_callback=update_progress,
                    dashboard=dashboard,
                    dashboard_source_index=0,
                    max_inflight_pipelines=resolved_inflight_pipelines,
                    max_concurrent_split_phases=resolved_split_phase_slots,
                    max_eval_tail_pipelines=max_eval_tail_pipelines,
                    config_timeout_seconds=resolved_config_timeout_seconds,
                    retry_failed_configs=resolved_retry_failed_configs,
                    wing_backlog_target=resolved_wing_backlog_target,
                    smart_scheduler=resolved_smart_scheduler,
                    source_parallelism_effective=source_parallelism_effective,
                    canonical_alignment_cache_dir_override=(
                        all_method_canonical_cache_root
                        / slugify_name(single_target.source_file.stem)
                    ),
                    dashboard_output_root=processed_output_root,
                )
            except Exception:
                dashboard.finish_source(0, failed=True)
                dashboard.set_task("Source failed.")
                update_progress(dashboard.render())
                raise
            dashboard.finish_source(0, failed=False)
            dashboard.set_task("Source complete.")
            update_progress(dashboard.render())
            return report_path

        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=single_root / PROCESSING_TIMESERIES_FILENAME,
            run=_run_single_source,
        )
        typer.secho(f"All method benchmark report: {report_md_path}", fg=typer.colors.CYAN)
        typer.secho(
            f"All method processing telemetry: {single_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )

    typer.secho(
        f"All method processed outputs: {all_method_processed_root}",
        fg=typer.colors.CYAN,
    )

def _all_method_apply_baseline_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_baseline_contract(payload)


def _all_method_apply_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_codex_contract_from_baseline(baseline_payload)


def _all_method_apply_selected_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
    *,
    codex_variant_settings: RunSettings,
) -> dict[str, Any]:
    codex_payload = dict(baseline_payload)
    codex_config = codex_variant_settings.to_run_config_dict()
    for key in (
        "llm_recipe_pipeline",
        "llm_knowledge_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
    ):
        if key in codex_config:
            codex_payload[key] = codex_config[key]
    return codex_payload


INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK = "single_book"
INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS = "selected_matched_books"
INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS = "all_matched_books"


def _all_method_codex_surface_slug_parts(
    codex_variant_settings: RunSettings,
) -> list[str]:
    parts: list[str] = []
    recipe_pipeline = codex_variant_settings.llm_recipe_pipeline.value
    if recipe_pipeline != "off":
        parts.append(f"llm_recipe_{_all_method_variant_token(recipe_pipeline)}")
    if codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2:
        parts.append(
            f"line_role_{_all_method_variant_token(codex_variant_settings.line_role_pipeline.value)}"
        )
    knowledge_pipeline = codex_variant_settings.llm_knowledge_pipeline.value
    if knowledge_pipeline != "off":
        parts.append(
            f"llm_knowledge_{_all_method_variant_token(knowledge_pipeline)}"
        )
    return parts


def _all_method_settings_enable_any_codex(
    codex_variant_settings: RunSettings | None,
) -> bool:
    if codex_variant_settings is None:
        return False
    return any(
        (
            codex_variant_settings.llm_recipe_pipeline.value != "off",
            codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2,
            codex_variant_settings.llm_knowledge_pipeline.value != "off",
        )
    )
