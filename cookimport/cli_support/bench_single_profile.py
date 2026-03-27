from __future__ import annotations

import sys

from .command_resolution import resolve_registered_command

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


@dataclass
class _SingleProfileBookDashboardRow:
    source_name: str
    total_configs: int
    status: str = "pending"
    completed_configs: int = 0
    successful_configs: int = 0
    failed_configs: int = 0
    current_variant_index: int = 0
    current_variant_total: int = 0
    current_variant_slug: str = ""
    current_stage_label: str = ""
    current_message: str = ""
    work_unit_label: str = ""
    current_counter: tuple[int, int] | None = None
    worker_total: int = 0
    worker_statuses: dict[int, str] = field(default_factory=dict)
    worker_running: int = 0
    worker_completed: int = 0
    worker_failed: int = 0
    followup_running: int = 0
    followup_completed: int = 0
    followup_total: int = 0
    followup_label: str = ""
    phase_started_at: float | None = None
    rate_total: int | None = None
    rate_last_current: int | None = None
    rate_last_progress_at: float | None = None
    rate_sampled_seconds: float = 0.0
    rate_sampled_units: int = 0
    rate_recent_samples: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(maxlen=_STATUS_RATE_RECENT_WINDOW),
        repr=False,
        compare=False,
    )

    @property
    def short_name(self) -> str:
        stem = Path(self.source_name).stem.strip()
        return stem or self.source_name


@dataclass
class _SingleProfileProgressDashboard:
    rows: list[_SingleProfileBookDashboardRow]
    total_planned_configs: int
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def _completed_sources(self) -> int:
        return sum(1 for row in self.rows if row.status in {"done", "failed"})

    def _completed_configs(self) -> int:
        return sum(max(0, row.completed_configs) for row in self.rows)

    @staticmethod
    def _truncate_cell(value: str, width: int) -> str:
        text = str(value or "").strip()
        if width <= 0:
            return ""
        if len(text) <= width:
            return text.ljust(width)
        if width <= 3:
            return text[:width]
        return f"{text[: max(1, width - 3)]}...".ljust(width)

    def _book_column_width(self, book_count: int) -> int:
        if book_count <= 0:
            return 12
        max_table_width = 118
        label_width = 7
        overhead = label_width + (3 * book_count) + 2
        available = max(8, max_table_width - overhead)
        return max(8, min(24, available // max(1, book_count)))

    def _render_grid_row(
        self,
        label: str,
        cells: Sequence[str],
        *,
        label_width: int,
        col_width: int,
    ) -> str:
        rendered_cells = [
            self._truncate_cell(cell, col_width)
            for cell in cells
        ]
        return (
            f"{str(label or '').strip()[:label_width].ljust(label_width)} | "
            + " | ".join(rendered_cells)
        ).rstrip()

    @staticmethod
    def _compact_work_unit_label(label: str) -> str:
        cleaned = str(label or "").strip().lower()
        if not cleaned:
            return "t"
        if "packet" in cleaned:
            return "pkt"
        if "recipe" in cleaned and "task" in cleaned:
            return "rt"
        if "task" in cleaned:
            return "t"
        letters = "".join(ch for ch in cleaned if ch.isalpha())
        if not letters:
            return "t"
        return letters[: min(3, len(letters))]

    @staticmethod
    def _estimate_eta_seconds(row: _SingleProfileBookDashboardRow, now: float) -> int | None:
        counter = row.current_counter
        if counter is None:
            return None
        current, total = counter
        remaining = max(0, total - current)
        if remaining <= 0:
            return 0
        avg_seconds_per_task = _recent_rate_average_seconds_per_task(
            row.rate_recent_samples
        )
        if avg_seconds_per_task is None and row.rate_sampled_units > 0 and row.rate_sampled_seconds > 0:
            avg_seconds_per_task = row.rate_sampled_seconds / float(row.rate_sampled_units)
        if (
            avg_seconds_per_task is None
            and current > 0
            and row.phase_started_at is not None
        ):
            bootstrap_elapsed = max(0.0, now - row.phase_started_at)
            if bootstrap_elapsed >= _STATUS_ETA_BOOTSTRAP_MIN_SECONDS:
                avg_seconds_per_task = bootstrap_elapsed / float(current)
        if avg_seconds_per_task is None or avg_seconds_per_task <= 0:
            return None
        if row.rate_sampled_units <= 0 or row.rate_sampled_seconds <= 0:
            bootstrap_parallelism = max(
                1,
                len(row.worker_statuses),
                row.worker_total,
            )
            return _parallel_bootstrap_eta_seconds(
                avg_seconds_per_task=avg_seconds_per_task,
                remaining=remaining,
                parallelism=bootstrap_parallelism,
            )
        return max(0, int(round(avg_seconds_per_task * remaining)))

    def start_source(self, source_index: int) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            self.rows[source_index].status = "running"

    def finish_source(self, source_index: int, *, failed: bool = False) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "failed" if failed else "done"
            row.current_stage_label = "failed" if failed else "done"
            row.current_message = row.current_stage_label
            row.work_unit_label = ""
            row.current_counter = None
            row.worker_total = 0
            row.worker_statuses = {}
            row.worker_running = 0
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""

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
            row = self.rows[source_index]
            row.status = "running"
            row.current_variant_index = max(0, config_index)
            row.current_variant_total = max(0, config_total)
            row.current_variant_slug = str(config_slug or "").strip()
            row.current_stage_label = "queued"
            row.current_message = row.current_variant_slug or "queued"
            row.work_unit_label = ""
            row.current_counter = None
            row.worker_total = 0
            row.worker_statuses = {}
            row.worker_running = 0
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""
            row.phase_started_at = time.monotonic()
            row.rate_total = None
            row.rate_last_current = None
            row.rate_last_progress_at = None
            row.rate_sampled_seconds = 0.0
            row.rate_sampled_units = 0
            row.rate_recent_samples.clear()

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
            if config_index is not None and row.current_variant_index == max(0, config_index):
                row.current_counter = None
                row.worker_total = 0
                row.worker_statuses = {}
                row.worker_running = 0
                row.worker_completed = 0
                row.worker_failed = 0
                row.followup_running = 0
                row.followup_completed = 0
                row.followup_total = 0
                row.followup_label = ""
                row.current_stage_label = "done" if success else "failed"
                row.current_message = row.current_stage_label

    def ingest_progress(
        self,
        *,
        source_index: int,
        message: str,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            payload = parse_worker_activity(cleaned)
            stage_progress = None if payload is not None else parse_stage_progress(cleaned)
            now = time.monotonic()
            if payload is not None:
                payload_type = str(payload.get("type") or "").strip().lower()
                if payload_type == "reset":
                    row.worker_total = 0
                    row.worker_statuses = {}
                    row.worker_running = 0
                    row.worker_completed = 0
                    row.worker_failed = 0
                    return
                if payload_type == "activity":
                    worker_total = max(1, int(payload.get("worker_total", 1)))
                    worker_index = max(1, int(payload.get("worker_index", 1)))
                    status = str(payload.get("status") or "").strip()
                    row.worker_total = worker_total
                    row.worker_statuses[worker_index] = status or "processing"
                    row.worker_running = max(
                        row.worker_running,
                        sum(
                            1
                            for value in row.worker_statuses.values()
                            if str(value).strip().lower() not in {"", "idle", "done", "failed", "skipped"}
                        ),
                    )
                    return

            structured_counter: tuple[int, int] | None = None
            if stage_progress is not None:
                cleaned = str(stage_progress.get("message") or "").strip() or cleaned
                row.work_unit_label = str(stage_progress.get("work_unit_label") or "").strip()
                task_current = stage_progress.get("task_current")
                task_total = stage_progress.get("task_total")
                if task_current is not None and task_total is not None:
                    structured_counter = (int(task_current), int(task_total))

            row.status = "running"
            row.current_message = cleaned
            row.phase_started_at = row.phase_started_at or now

            counter = (
                structured_counter
                if structured_counter is not None
                else _extract_progress_counter(cleaned)
            )
            if counter is None:
                row.current_counter = None
                row.rate_total = None
                row.rate_last_current = None
                row.rate_last_progress_at = None
                row.rate_sampled_seconds = 0.0
                row.rate_sampled_units = 0
                row.rate_recent_samples.clear()
            else:
                current_value, total_value = counter
                should_reset = (
                    row.rate_total is None
                    or row.rate_last_current is None
                    or row.rate_last_progress_at is None
                    or total_value != row.rate_total
                    or current_value < row.rate_last_current
                )
                if should_reset:
                    row.rate_total = total_value
                    row.rate_last_current = current_value
                    row.rate_last_progress_at = now
                    row.rate_sampled_seconds = 0.0
                    row.rate_sampled_units = 0
                    row.rate_recent_samples.clear()
                else:
                    delta = current_value - row.rate_last_current
                    if delta > 0:
                        elapsed_since_progress = max(0.0, now - row.rate_last_progress_at)
                        if elapsed_since_progress > 0:
                            row.rate_sampled_seconds += elapsed_since_progress
                            row.rate_sampled_units += delta
                            row.rate_recent_samples.append((elapsed_since_progress, delta))
                        row.rate_last_current = current_value
                        row.rate_last_progress_at = now
                row.current_counter = counter

            if stage_progress is not None:
                stage_label = (
                    str(stage_progress.get("stage_label") or "").strip()
                    or _extract_progress_stage_label(cleaned)
                    or "running"
                )
                previous_stage_label = row.current_stage_label
                active_tasks = stage_progress.get("active_tasks")
                running_workers = stage_progress.get("running_workers")
                worker_total_hint = stage_progress.get("worker_total")
                worker_running_hint = stage_progress.get("worker_running")
                worker_completed_hint = stage_progress.get("worker_completed")
                worker_failed_hint = stage_progress.get("worker_failed")
                followup_running_hint = stage_progress.get("followup_running")
                followup_completed_hint = stage_progress.get("followup_completed")
                followup_total_hint = stage_progress.get("followup_total")
                followup_label_hint = stage_progress.get("followup_label")
                row.current_stage_label = stage_label
                row.worker_statuses = {}
                running_slots = (
                    max(0, int(worker_running_hint))
                    if worker_running_hint is not None
                    else max(0, int(running_workers))
                    if running_workers is not None
                    else 0
                )
                completed_slots = max(0, int(worker_completed_hint or 0))
                failed_slots = max(0, int(worker_failed_hint or 0))
                if isinstance(active_tasks, list):
                    for worker_index, task in enumerate(active_tasks, start=1):
                        task_text = str(task).strip()
                        if task_text:
                            row.worker_statuses[worker_index] = task_text
                while len(row.worker_statuses) < running_slots:
                    row.worker_statuses[len(row.worker_statuses) + 1] = "running"
                for _ in range(completed_slots):
                    row.worker_statuses[len(row.worker_statuses) + 1] = "done"
                for _ in range(failed_slots):
                    row.worker_statuses[len(row.worker_statuses) + 1] = "failed"
                worker_total = max(0, len(row.worker_statuses))
                if worker_total_hint is not None:
                    worker_total = max(worker_total, max(0, int(worker_total_hint)))
                row.worker_total = worker_total
                row.worker_running = running_slots
                row.worker_completed = completed_slots
                row.worker_failed = failed_slots
                row.followup_running = max(0, int(followup_running_hint or 0))
                row.followup_completed = max(0, int(followup_completed_hint or 0))
                row.followup_total = max(0, int(followup_total_hint or 0))
                row.followup_label = str(followup_label_hint or "").strip()
                if stage_label != previous_stage_label:
                    row.rate_total = None
                    row.rate_last_current = None
                    row.rate_last_progress_at = None
                    row.rate_sampled_seconds = 0.0
                    row.rate_sampled_units = 0
                    row.rate_recent_samples.clear()
                return

            if cleaned.lower().startswith("codex-farm "):
                summary, stage_label = _summarize_codex_progress_message(cleaned)
                row.current_message = summary
                row.current_stage_label = stage_label or "codex-farm"
                row.work_unit_label = ""
                active_tasks = _extract_active_tasks(cleaned)
                running_workers = _extract_running_workers(cleaned)
                if active_tasks is not None:
                    row.worker_statuses = {
                        worker_index: task
                        for worker_index, task in enumerate(active_tasks, start=1)
                    }
                else:
                    row.worker_statuses = {}
                worker_total = len(row.worker_statuses)
                if running_workers is not None:
                    worker_total = max(worker_total, running_workers)
                row.worker_total = max(0, worker_total)
                row.worker_running = max(0, int(running_workers or 0))
                row.worker_completed = 0
                row.worker_failed = 0
                row.followup_running = 0
                row.followup_completed = 0
                row.followup_total = 0
                row.followup_label = ""
                return

            stage_text = cleaned.split("|", 1)[0].strip()
            if counter is not None and stage_text:
                stage_text = stage_text.rsplit(" task ", 1)[0].strip()
            row.current_stage_label = stage_text or "running"
            row.work_unit_label = ""
            running_workers = _extract_running_workers(cleaned)
            row.worker_total = max(0, running_workers or 0)
            row.worker_statuses = {}
            row.worker_running = max(0, int(running_workers or 0))
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""

    def render(self) -> str:
        with self._lock:
            source_total = len(self.rows)
            source_done = self._completed_sources()
            config_done = self._completed_configs()
            lines = [
                (
                    "overall "
                    f"source {source_done}/{source_total} | "
                    f"config {config_done}/{max(0, self.total_planned_configs)}"
                )
            ]
            if not self.rows:
                return "\n".join(lines)

            col_width = self._book_column_width(len(self.rows))
            label_width = 7
            now = time.monotonic()
            lines.append("books:")
            lines.append(
                self._render_grid_row(
                    "book",
                    [row.short_name for row in self.rows],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "state",
                    [
                        (
                            "queued"
                            if row.status == "pending"
                            else ("failed" if row.status == "failed" else row.current_stage_label or row.status)
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "prog",
                    [
                        (
                            f"{self._compact_work_unit_label(row.work_unit_label)}{counter[0]}/{counter[1]} v{row.completed_configs}/{row.total_configs}"
                            if (counter := row.current_counter) is not None
                            else f"v{row.completed_configs}/{row.total_configs} ok{row.successful_configs} f{row.failed_configs}"
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "eta",
                    [
                        (
                            "--"
                            if row.status != "running"
                            else (
                                _format_processing_time(float(eta_seconds))
                                if (eta_seconds := self._estimate_eta_seconds(row, now)) is not None
                                else "--"
                            )
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            if any(
                row.followup_running > 0
                or row.followup_total > 0
                or row.followup_completed > 0
                or row.followup_label
                for row in self.rows
            ):
                lines.append(
                    self._render_grid_row(
                        "repo",
                        [
                            (
                                " | ".join(
                                    [
                                        item
                                        for item in (
                                            str(row.followup_label or "").strip() or "follow-up",
                                            (
                                                f"{row.followup_completed}/{row.followup_total}"
                                                if row.followup_total > 0
                                                else None
                                            ),
                                            (
                                                f"run {row.followup_running}"
                                                if row.followup_running > 0
                                                else None
                                            ),
                                        )
                                        if item
                                    ]
                                )
                                if (
                                    row.followup_running > 0
                                    or row.followup_total > 0
                                    or row.followup_completed > 0
                                    or row.followup_label
                                )
                                else "--"
                            )
                            for row in self.rows
                        ],
                        label_width=label_width,
                        col_width=col_width,
                    )
                )

            max_worker_rows = max(
                [
                    max(0, row.worker_total, len(row.worker_statuses))
                    for row in self.rows
                ],
                default=0,
            )
            for worker_index in range(1, max_worker_rows + 1):
                worker_cells = []
                for row in self.rows:
                    worker_text = str(row.worker_statuses.get(worker_index) or "").strip()
                    if not worker_text and worker_index <= row.worker_total:
                        worker_text = "busy"
                    worker_cells.append(worker_text or "--")
                lines.append(
                    self._render_grid_row(
                        f"w{worker_index:02d}",
                        worker_cells,
                        label_width=label_width,
                        col_width=col_width,
                    )
                )
            return "\n".join(lines)


@dataclass(frozen=True)
class _SingleProfileTargetComputationResult:
    target: AllMethodTarget
    failure_reason: str | None
    target_eval_output: Path
    comparison_json_path: Path | None


@dataclass(frozen=True)
class _SingleProfileTargetPublicationResult:
    target: AllMethodTarget
    upload_bundle_dir: Path | None
    publication_error: str | None = None


@dataclass(frozen=True)
class _SingleProfileBenchmarkComputationResult:
    completed_results: list[_SingleProfileTargetComputationResult]
    single_profile_root: Path
    single_profile_processed_root: Path
    total_targets: int
    refresh_dashboard: bool


@dataclass(frozen=True)
class _SingleProfileBenchmarkPublicationResult:
    target_results: list[_SingleProfileTargetPublicationResult]
    group_upload_bundle_dir: Path | None = None


def _publish_single_profile_benchmark_result(
    result: _SingleProfileBenchmarkComputationResult,
    *,
    golden_root: Path,
    processed_output_root: Path,
) -> _SingleProfileBenchmarkPublicationResult:
    target_publications: list[_SingleProfileTargetPublicationResult] = []
    for target_result in result.completed_results:
        try:
            upload_bundle_dir = _write_benchmark_upload_bundle(
                source_root=target_result.target_eval_output,
                output_dir=target_result.target_eval_output / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
                suppress_summary=False,
            )
            target_publications.append(
                _SingleProfileTargetPublicationResult(
                    target=target_result.target,
                    upload_bundle_dir=upload_bundle_dir,
                )
            )
        except typer.Exit as exc:
            exit_code = int(getattr(exc, "exit_code", 1))
            target_publications.append(
                _SingleProfileTargetPublicationResult(
                    target=target_result.target,
                    upload_bundle_dir=None,
                    publication_error=f"upload bundle exit code {exit_code}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            target_publications.append(
                _SingleProfileTargetPublicationResult(
                    target=target_result.target,
                    upload_bundle_dir=None,
                    publication_error=f"upload bundle error: {exc}",
                )
            )

    group_upload_bundle_dir: Path | None = None
    if result.total_targets > 1:
        group_upload_bundle_dir = _write_benchmark_upload_bundle(
            source_root=result.single_profile_root,
            output_dir=result.single_profile_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
            suppress_summary=False,
            high_level_only=True,
            target_bundle_size_bytes=BENCHMARK_GROUP_UPLOAD_BUNDLE_TARGET_BYTES,
        )
        if group_upload_bundle_dir is not None:
            _start_benchmark_bundle_oracle_upload_background(
                bundle_dir=group_upload_bundle_dir,
                scope="single_profile_group",
            )

    if result.refresh_dashboard:
        history_csv_path = history_csv_for_output(
            result.single_profile_processed_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            output_root=processed_output_root,
            golden_root=golden_root,
            dashboard_out_dir=history_root_for_output(processed_output_root) / "dashboard",
            reason="single-profile benchmark variant batch append",
        )

    return _SingleProfileBenchmarkPublicationResult(
        target_results=target_publications,
        group_upload_bundle_dir=group_upload_bundle_dir,
    )


def _make_single_profile_benchmark_publisher(
    *,
    golden_root: Path,
    processed_output_root: Path,
) -> Callable[
    [_SingleProfileBenchmarkComputationResult],
    _SingleProfileBenchmarkPublicationResult,
]:
    return lambda result: _publish_single_profile_benchmark_result(
        result,
        golden_root=golden_root,
        processed_output_root=processed_output_root,
    )

def _interactive_single_profile_all_matched_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    golden_root: Path | None = None,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    allow_subset_selection: bool = False,
    publisher: Callable[
        [_SingleProfileBenchmarkComputationResult],
        _SingleProfileBenchmarkPublicationResult,
    ]
    | None = None,
) -> bool:
    """Run one benchmark profile across matched gold/source pairs."""
    resolved_golden_root = golden_root or DEFAULT_GOLDEN

    def _friendly_single_profile_failure_reason(reason: object) -> str:
        text = str(reason or "").strip()
        if not text or "stderr_summary=" not in text:
            return text
        pipeline_match = re.search(r"codex-farm failed for (\S+)", text)
        pipeline_id = (
            str(pipeline_match.group(1)).strip() if pipeline_match is not None else None
        )
        summary = text.split("stderr_summary=", 1)[1].strip()
        if summary.endswith(")"):
            summary = summary[:-1].rstrip()
        if pipeline_id:
            return f"codex-farm {pipeline_id}: {summary}"
        return summary

    all_targets, unmatched_targets = _resolve_all_method_targets(resolved_golden_root)
    if not all_targets:
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
        return False

    targets = list(all_targets)
    if allow_subset_selection and len(targets) > 1:
        selected_indices: set[int] = set()
        while True:
            selected_count = len(selected_indices)
            choices: list[Any] = [
                questionary.Choice("Run all matched books", value="__run_all__"),
            ]
            if selected_count > 0:
                choices.append(
                    questionary.Choice(
                        f"Run selected books ({selected_count})",
                        value="__run_selected__",
                    )
                )
            for index, target in enumerate(targets, start=1):
                target_index = index - 1
                marker = "x" if target_index in selected_indices else " "
                choices.append(
                    questionary.Choice(
                        f"[{marker}] {index:02d}) {_display_benchmark_target_name(gold_display=target.gold_display, source_file_name=target.source_file_name)}",
                        value=target_index,
                    )
                )

            selection = _menu_select(
                "Choose matched books for this single-profile benchmark:",
                menu_help=(
                    "Toggle book rows, then choose run selected books. "
                    "Or run all matched books directly."
                ),
                choices=choices,
            )
            if selection in {None, BACK_ACTION}:
                typer.secho("Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
                return False
            if selection == "__run_all__":
                break
            if selection == "__run_selected__":
                targets = [targets[i] for i in sorted(selected_indices)]
                break
            if not isinstance(selection, int):
                continue
            if selection < 0 or selection >= len(targets):
                continue
            if selection in selected_indices:
                selected_indices.remove(selection)
            else:
                selected_indices.add(selection)

    if not targets:
        typer.secho("No books selected. Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
        return False

    variants = _interactive_single_book_variants(selected_benchmark_settings)
    if not variants:
        typer.secho("No single-profile benchmark variants were planned.", fg=typer.colors.YELLOW)
        return False
    runs_per_target = len(variants)
    total_planned_runs = len(targets) * runs_per_target
    variant_labels = ", ".join(slug for slug, _settings in variants)

    typer.secho(
        f"Matched golden sets: {len(all_targets)}",
        fg=typer.colors.CYAN,
    )
    if allow_subset_selection:
        typer.secho(f"Selected matched books: {len(targets)}", fg=typer.colors.CYAN)
    typer.secho(
        f"Single-profile benchmark variants per book: {variant_labels}",
        fg=typer.colors.CYAN,
    )
    if runs_per_target > 1:
        typer.secho(
            "Codex selected: each book will run vanilla first, then codexfarm.",
            fg=typer.colors.BRIGHT_BLACK,
        )
    skipped_color = typer.colors.YELLOW if unmatched_targets else typer.colors.BRIGHT_BLACK
    typer.secho(
        f"Skipped golden sets: {len(unmatched_targets)}",
        fg=skipped_color,
    )
    scope_label = (
        "selected matched books"
        if allow_subset_selection
        else "matched golden sets"
    )
    typer.secho(
        (
            "Single-profile benchmark will run "
            f"{total_planned_runs} configurations across {len(targets)} {scope_label}."
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

    proceed = _prompt_confirm(
        (
            f"Proceed with {total_planned_runs} benchmark runs across "
            f"{len(targets)} {scope_label}?"
        ),
        default=False,
    )
    if proceed is not True:
        typer.secho("Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
        return False

    single_profile_root = benchmark_eval_output / "single-profile-benchmark"
    single_profile_processed_root = (
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
    )

    variant_call_defaults: dict[str, dict[str, Any]] = {}
    for variant_slug, variant_settings in variants:
        variant_call_defaults[variant_slug] = build_benchmark_call_kwargs_from_run_settings(
            variant_settings,
            output_dir=_golden_benchmark_root(),
            eval_output_dir=single_profile_root,
            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            no_upload=True,
            write_markdown=write_markdown,
            write_label_studio_tasks=write_label_studio_tasks,
        )
        variant_call_defaults[variant_slug]["allow_codex"] = codex_surfaces_enabled(
            variant_settings.to_run_config_dict()
        )

    failures: list[tuple[AllMethodTarget, str]] = []
    total_targets = len(targets)
    parallel_books_cap = 3
    worker_scale_numerator = 8
    worker_scale_denominator = 10
    max_parallel_targets = (
        min(parallel_books_cap, total_targets) if total_targets > 1 else 1
    )
    split_phase_slots: int | None = None
    split_phase_gate_dir: Path | None = None
    scaled_worker_overrides: dict[str, int] = {}
    status_initial = "Running single-profile benchmark..."
    status_prefix = "Single-profile benchmark"
    single_profile_dashboard: _SingleProfileProgressDashboard | None = None
    dashboard_emit_lock = threading.RLock()

    def _scale_parallel_workers(raw_value: Any) -> int:
        try:
            baseline = max(1, int(raw_value))
        except (TypeError, ValueError):
            baseline = 1
        return max(
            1, (baseline * worker_scale_numerator) // worker_scale_denominator
        )

    if max_parallel_targets > 1:
        split_phase_slots = 1
        split_phase_gate_dir = single_profile_root / ".split_phase_slots"
        split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
        single_profile_dashboard = _SingleProfileProgressDashboard(
            rows=[
                _SingleProfileBookDashboardRow(
                    source_name=target.source_file_name,
                    total_configs=max(1, runs_per_target),
                )
                for target in targets
            ],
            total_planned_configs=max(1, total_planned_runs),
        )
        scheduler_variant_slug = variants[0][0]
        scheduler_kwargs = variant_call_defaults.get(scheduler_variant_slug, {})
        for key in ("workers", "pdf_split_workers", "epub_split_workers"):
            scaled_worker_overrides[key] = _scale_parallel_workers(scheduler_kwargs.get(key))
        typer.secho(
            (
                "Single-profile scheduler: "
                f"parallel books={max_parallel_targets}, "
                "per-book worker scaling=80%, "
                "split conversion slots=1."
            ),
            fg=typer.colors.BRIGHT_BLACK,
        )

    def _emit_single_profile_dashboard(
        update_progress: Callable[[str], None] | None,
        *,
        task_message: str | None = None,
    ) -> None:
        if update_progress is None or single_profile_dashboard is None:
            return
        with dashboard_emit_lock:
            update_progress(single_profile_dashboard.render())

    def _run_single_profile_target(
        index: int,
        target: AllMethodTarget,
        update_progress: Callable[[str], None] | None = None,
    ) -> _SingleProfileTargetComputationResult:
        target_slug = f"{index:02d}_{slugify_name(target.source_file.stem)}"
        target_eval_output = single_profile_root / target_slug
        target_processed_output = single_profile_processed_root / target_slug
        source_index = index - 1
        variant_eval_outputs: dict[str, Path] = {}
        variant_errors: list[str] = []
        source_file_for_comparison: str | None = None
        if single_profile_dashboard is not None:
            single_profile_dashboard.start_source(source_index)
            _emit_single_profile_dashboard(
                update_progress,
                task_message=(
                    f"{format_task_counter('Running', index, max(1, total_targets), noun='book')}: "
                    f"{target.source_file_name}"
                ),
            )

        def _finish_source_progress(*, failed: bool, status: str) -> None:
            if single_profile_dashboard is None:
                return
            single_profile_dashboard.finish_source(source_index, failed=failed)
            _emit_single_profile_dashboard(update_progress, task_message=status)

        for variant_index, (variant_slug, _variant_settings) in enumerate(
            variants, start=1
        ):
            variant_kwargs = dict(variant_call_defaults.get(variant_slug, {}))
            variant_eval_output = (
                target_eval_output / variant_slug
                if runs_per_target > 1
                else target_eval_output
            )
            variant_processed_output = (
                target_processed_output / variant_slug
                if runs_per_target > 1
                else target_processed_output
            )
            variant_kwargs.update(
                {
                    "gold_spans": target.gold_spans_path,
                    "source_file": target.source_file,
                    "eval_output_dir": variant_eval_output,
                    "processed_output_dir": variant_processed_output,
                }
            )
            if scaled_worker_overrides:
                variant_kwargs.update(scaled_worker_overrides)
            if single_profile_dashboard is not None:
                single_profile_dashboard.start_config(
                    source_index=source_index,
                    config_index=variant_index,
                    config_total=max(1, runs_per_target),
                    config_slug=variant_slug,
                )
                _emit_single_profile_dashboard(
                    update_progress,
                    task_message=(
                        f"{format_task_counter('Running', variant_index, max(1, runs_per_target), noun='variant')} "
                        f"({variant_slug}) | book {index}/{max(1, total_targets)}: {target.source_file_name}"
                    ),
                )
            split_status_label = None
            if split_phase_slots is not None:
                split_status_label = (
                    f"Single-profile split gate {index}/{total_targets}: "
                    f"{target.source_file_name}"
                )
                if runs_per_target > 1:
                    split_status_label = (
                        f"Single-profile split gate {index}/{total_targets} "
                        f"variant {variant_index}/{runs_per_target} "
                        f"({variant_slug}): {target.source_file_name}"
                    )

            def _variant_progress(message: str) -> None:
                cleaned = str(message or "").strip()
                if not cleaned:
                    return
                if single_profile_dashboard is not None:
                    single_profile_dashboard.ingest_progress(
                        source_index=source_index,
                        message=cleaned,
                    )
                _emit_single_profile_dashboard(
                    update_progress,
                )

            try:
                with _benchmark_split_phase_overrides(
                    split_phase_slots=split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    split_phase_status_label=split_status_label,
                ):
                    with _benchmark_progress_overrides(
                        progress_callback=(
                            _variant_progress if single_profile_dashboard is not None else None
                        ),
                        suppress_summary=single_profile_dashboard is not None,
                        suppress_spinner=single_profile_dashboard is not None,
                        suppress_dashboard_refresh=single_profile_dashboard is not None,
                        live_status_slots=(
                            None
                            if single_profile_dashboard is not None
                            else (2 if max_parallel_targets > 1 else None)
                        ),
                    ):
                        _labelstudio_benchmark_command()(**variant_kwargs)
                variant_eval_outputs[variant_slug] = variant_eval_output
                source_file = _load_single_book_source_path(variant_eval_output)
                if source_file and not source_file_for_comparison:
                    source_file_for_comparison = source_file
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=True,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Completed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: {target.source_file_name}"
                        ),
                    )
            except typer.Exit as exc:
                exit_code = int(getattr(exc, "exit_code", 1))
                variant_errors.append(f"{variant_slug}=exit code {exit_code}")
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=False,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Failed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: "
                            f"{target.source_file_name} (exit code {exit_code})"
                        ),
                    )
            except Exception as exc:  # noqa: BLE001
                formatted_error = _friendly_single_profile_failure_reason(exc)
                variant_errors.append(f"{variant_slug}={formatted_error}")
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=False,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Failed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: "
                            f"{target.source_file_name} ({formatted_error})"
                        ),
                    )

        comparison_json_path: Path | None = None
        if (
            runs_per_target > 1
            and "vanilla" in variant_eval_outputs
            and "codexfarm" in variant_eval_outputs
        ):
            comparison_paths = _write_single_book_comparison_artifacts(
                run_timestamp=benchmark_eval_output.name,
                session_root=target_eval_output,
                source_file=source_file_for_comparison or str(target.source_file),
                codex_eval_output_dir=variant_eval_outputs["codexfarm"],
                vanilla_eval_output_dir=variant_eval_outputs["vanilla"],
                write_markdown=write_markdown,
                write_starter_pack=False,
            )
            if comparison_paths is not None:
                comparison_json_path = comparison_paths[0]

        failure_reason = "; ".join(variant_errors) if variant_errors else None
        _finish_source_progress(
            failed=failure_reason is not None,
            status=(
                f"{'Failed' if failure_reason is not None else 'Completed'} "
                f"{format_task_counter('', index, max(1, total_targets), noun='book')}: "
                f"{target.source_file_name}"
            ),
        )
        return _SingleProfileTargetComputationResult(
            target=target,
            failure_reason=failure_reason,
            target_eval_output=target_eval_output,
            comparison_json_path=comparison_json_path,
        )

    target_index_pairs = list(enumerate(targets, start=1))
    for index, target in target_index_pairs:
        typer.secho(
            (
                f"Single-profile benchmark {index}/{total_targets}: "
                f"{target.source_file_name}"
                f"{' (vanilla + codexfarm)' if runs_per_target > 1 else ''}"
            ),
            fg=typer.colors.CYAN,
        )

    if max_parallel_targets == 1:
        completed_results = [
            _run_single_profile_target(index, target)
            for index, target in target_index_pairs
        ]
    else:
        def _run_parallel_targets_with_shared_status(
            update_progress: Callable[[str], None],
        ) -> list[_SingleProfileTargetComputationResult]:
            _emit_single_profile_dashboard(
                update_progress,
                task_message=(
                    f"Queued {format_task_counter('', 0, max(1, total_targets), noun='book')}"
                ),
            )
            completed: list[_SingleProfileTargetComputationResult] = []
            with ThreadPoolExecutor(max_workers=max_parallel_targets) as executor:
                futures = [
                    executor.submit(
                        _run_single_profile_target,
                        index,
                        target,
                        update_progress,
                    )
                    for index, target in target_index_pairs
                ]
                for future in as_completed(futures):
                    completed.append(future.result())
            return completed

        completed_results = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=single_profile_root / PROCESSING_TIMESERIES_FILENAME,
            run=_run_parallel_targets_with_shared_status,
        )

    computation = _SingleProfileBenchmarkComputationResult(
        completed_results=completed_results,
        single_profile_root=single_profile_root,
        single_profile_processed_root=single_profile_processed_root,
        total_targets=total_targets,
        refresh_dashboard=single_profile_dashboard is not None,
    )
    if publisher is None:
        publisher = _make_single_profile_benchmark_publisher(
            golden_root=resolved_golden_root,
            processed_output_root=processed_output_root,
        )
    publication = publisher(computation)
    publication_by_target = {
        target_result.target: target_result for target_result in publication.target_results
    }

    for target_result in completed_results:
        target = target_result.target
        failure_reason = target_result.failure_reason
        comparison_json_path = target_result.comparison_json_path
        publication_target = publication_by_target.get(target)
        upload_bundle_dir = (
            publication_target.upload_bundle_dir
            if publication_target is not None
            else None
        )
        if upload_bundle_dir is not None:
            typer.secho(
                f"External-AI upload bundle: {upload_bundle_dir}",
                fg=typer.colors.CYAN,
            )
        if comparison_json_path is not None:
            typer.secho(
                f"Codex-vs-vanilla comparison: {comparison_json_path}",
                fg=typer.colors.CYAN,
            )
        if publication_target is not None and publication_target.publication_error:
            failure_reason = (
                f"{failure_reason}; {publication_target.publication_error}"
                if failure_reason
                else publication_target.publication_error
            )
        if failure_reason is None:
            continue
        failures.append((target, failure_reason))
        typer.secho(
            (
                f"Single-profile benchmark failed for "
                f"{target.source_file_name}: {failure_reason}; continuing."
            ),
            fg=typer.colors.YELLOW,
        )

    if publication.group_upload_bundle_dir is not None:
        typer.secho(
            f"External-AI group upload bundle: {publication.group_upload_bundle_dir}",
            fg=typer.colors.CYAN,
        )

    succeeded = total_targets - len(failures)
    summary_color = typer.colors.GREEN if not failures else typer.colors.YELLOW
    typer.secho(
        (
            "Single-profile all-matched benchmark complete: "
            f"{succeeded}/{total_targets} succeeded."
        ),
        fg=summary_color,
    )
    typer.secho(
        f"Single-profile benchmark outputs: {single_profile_root}",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        f"Single-profile processed outputs: {single_profile_processed_root}",
        fg=typer.colors.CYAN,
    )
    if failures:
        typer.secho("Failed golden set samples:", fg=typer.colors.YELLOW)
        for failed_target, reason in failures[:5]:
            typer.echo(
                f"  - {failed_target.gold_display}: {reason} "
                f"(source: {failed_target.source_file_name})"
            )
        if len(failures) > 5:
            typer.echo(f"  - ... {len(failures) - 5} additional failures")
    return True
