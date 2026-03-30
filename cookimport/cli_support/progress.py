from __future__ import annotations

import sys

runtime = sys.modules["cookimport.cli_support"]

# Snapshot the fully initialized root support namespace so these moved
# flow/progress helpers can keep their historical unqualified references.
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

def _extract_progress_counter(message: str) -> tuple[int, int] | None:
    """Extract the right-most X/Y counter from a status message."""
    trimmed = message.strip()
    if not trimmed:
        return None

    # All-method dashboard snapshots include many counters; prefer the top-line
    # overall config counter so ETA tracks completed configs.
    first_line = trimmed.splitlines()[0].strip()
    if first_line.lower().startswith("overall source "):
        first_line_matches = list(_STATUS_COUNTER_PATTERN.finditer(first_line))
        for match in reversed(first_line_matches):
            try:
                current = int(match.group(1))
                total = int(match.group(2))
            except (TypeError, ValueError):
                continue
            if total <= 0:
                continue
            return max(0, min(current, total)), total

    matches = list(_STATUS_COUNTER_PATTERN.finditer(trimmed))
    for match in reversed(matches):
        try:
            current = int(match.group(1))
            total = int(match.group(2))
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        return max(0, min(current, total)), total
    return None

def _extract_progress_stage_label(message: str) -> str | None:
    """Extract a stable stage label from a progress message."""
    trimmed = str(message or "").strip()
    if not trimmed:
        return None
    first_line = trimmed.splitlines()[0].strip()
    if not first_line:
        return None
    if first_line.lower().startswith("overall source "):
        return first_line
    base = first_line.split("|", 1)[0].strip()
    if not base:
        return None
    base = _PROGRESS_STAGE_COUNTER_SUFFIX_RE.sub("", base).strip()
    return base or None

def _is_structured_progress_message(message: str) -> bool:
    cleaned = str(message or "").strip()
    return (
        parse_worker_activity(cleaned) is not None
        or parse_stage_progress(cleaned) is not None
    )

def _extract_active_tasks(message: str) -> list[str] | None:
    match = _STATUS_ACTIVE_TASKS_RE.search(str(message or ""))
    if match is None:
        return None
    raw = str(match.group(1)).strip()
    if not raw:
        return []
    values = [item.strip() for item in raw.split(",")]
    return [value for value in values if value]

def _extract_running_workers(message: str) -> int | None:
    match = _STATUS_RUNNING_WORKERS_RE.search(str(message or ""))
    if match is None:
        return None
    try:
        return max(0, int(match.group(1)))
    except (TypeError, ValueError):
        return None

def _humanize_codex_pipeline_stage_label(pipeline_id: str) -> str:
    normalized = str(pipeline_id or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return "codex stage"
    if "recipe.correction" in lowered or "recipe_correction" in lowered or "correction" in lowered:
        return "recipe correction"
    if "knowledge" in lowered:
        return "non-recipe knowledge review"
    if "tags" in lowered:
        return "tag suggestions"
    return normalized

def _summarize_codex_progress_message(message: str) -> tuple[str, str | None]:
    trimmed = str(message or "").strip()
    match = _STATUS_CODEX_FARM_PIPELINE_PREFIX_RE.match(trimmed)
    if match is None:
        return trimmed, None

    raw_pipeline = str(match.group("pipeline") or "").strip()
    pipeline_id = raw_pipeline[:-1] if raw_pipeline.endswith(":") else raw_pipeline
    stage_label = _humanize_codex_pipeline_stage_label(pipeline_id)
    counter = _extract_progress_counter(trimmed)
    running = _extract_running_workers(trimmed)

    if counter is not None:
        current, total = counter
        parts = [
            f"codex-farm {stage_label}",
            f"task {current}/{total}",
        ]
        if running is not None and running > 0:
            parts.append(f"running {running}")
        return " | ".join(parts), stage_label

    suffix = trimmed[match.end() :].strip()
    if suffix.startswith(":"):
        suffix = suffix[1:].strip()
    if suffix:
        return f"codex-farm {stage_label}: {suffix}", stage_label
    return f"codex-farm {stage_label}", stage_label

def _format_seconds_per_task(seconds_per_task: float) -> str:
    formatted = f"{max(0.0, seconds_per_task):.1f}".rstrip("0").rstrip(".")
    return f"{formatted}s/task"

def _looks_like_all_method_dashboard_snapshot(message: str) -> bool:
    trimmed = str(message or "").strip()
    return bool(trimmed and trimmed.startswith("overall source ") and "\nqueue:" in trimmed)

def _extract_all_method_dashboard_metrics(message: str) -> dict[str, int]:
    trimmed = str(message or "").strip()
    if not _looks_like_all_method_dashboard_snapshot(trimmed):
        return {}
    for raw_line in trimmed.splitlines():
        line = raw_line.strip().lower()
        if not line.startswith("task:"):
            continue
        payload = line.split(":", 1)[1].strip()
        metrics: dict[str, int] = {}
        for part in payload.split("|"):
            segment = part.strip()
            if not segment:
                continue
            match = re.search(r"\b(active|pending|eval|wing)\s+(\d+)\b", segment)
            if match is None:
                continue
            key = match.group(1)
            value = max(0, int(match.group(2)))
            metrics[key] = value
        return metrics
    return {}

def _recent_rate_average_seconds_per_task(
    samples: deque[tuple[float, int]],
) -> float | None:
    if not samples:
        return None

    max_steps = max(1, len(_STATUS_ETA_RECENT_STEP_WEIGHTS))
    # Build a most-recent-first list of per-step durations from sampled deltas.
    recent_step_seconds: list[float] = []
    most_recent_step_seconds: float | None = None
    for elapsed_seconds, completed_units in reversed(samples):
        elapsed_value = float(elapsed_seconds)
        units_value = int(completed_units)
        if elapsed_value <= 0 or units_value <= 0:
            continue
        per_step_seconds = elapsed_value / float(units_value)
        if per_step_seconds <= 0:
            continue
        if most_recent_step_seconds is None:
            most_recent_step_seconds = per_step_seconds
        remaining_slots = max_steps - len(recent_step_seconds)
        if remaining_slots <= 0:
            break
        recent_step_seconds.extend([per_step_seconds] * min(remaining_slots, units_value))

    if not recent_step_seconds:
        return None

    weighted_total = 0.0
    weight_sum = 0.0
    for index, per_step_seconds in enumerate(recent_step_seconds):
        weight = float(_STATUS_ETA_RECENT_STEP_WEIGHTS[index])
        if weight <= 0:
            continue
        weighted_total += per_step_seconds * weight
        weight_sum += weight
    weighted_average = (
        weighted_total / weight_sum
        if weight_sum > 0
        else sum(recent_step_seconds) / float(len(recent_step_seconds))
    )
    if most_recent_step_seconds is None:
        return weighted_average
    if len(recent_step_seconds) <= 1:
        return most_recent_step_seconds
    blend = max(0.0, min(1.0, float(_STATUS_ETA_RECENT_INSTANT_BLEND)))
    if blend <= 0.0:
        return weighted_average
    if blend >= 1.0:
        return most_recent_step_seconds
    return (
        most_recent_step_seconds * blend
        + weighted_average * (1.0 - blend)
    )

def _parallel_bootstrap_eta_seconds(
    *,
    avg_seconds_per_task: float,
    remaining: int,
    parallelism: int | None,
) -> int:
    safe_remaining = max(0, int(remaining))
    if safe_remaining <= 0:
        return 0
    effective_parallelism = max(1, int(parallelism or 1))
    if effective_parallelism <= 1:
        return max(0, int(round(avg_seconds_per_task * safe_remaining)))
    remaining_waves = math.ceil(safe_remaining / float(effective_parallelism))
    return max(0, int(round(avg_seconds_per_task * remaining_waves)))

def _format_status_progress_message(
    message: str,
    *,
    elapsed_seconds: int,
    elapsed_threshold_seconds: int = _STATUS_ELAPSED_THRESHOLD_SECONDS,
    eta_seconds: int | None = None,
    avg_seconds_per_task: float | None = None,
) -> str:
    """Append ETA/throughput and elapsed time for long-running phases."""
    trimmed = message.strip()
    if not trimmed:
        return ""
    suffix_parts: list[str] = []
    if eta_seconds is not None:
        suffix_parts.append(f"eta {_format_processing_time(float(eta_seconds))}")
        if avg_seconds_per_task is not None and avg_seconds_per_task > 0:
            suffix_parts.append(f"avg {_format_seconds_per_task(avg_seconds_per_task)}")
    if elapsed_seconds >= max(0, elapsed_threshold_seconds):
        suffix_parts.append(f"{elapsed_seconds}s")
    if not suffix_parts:
        return trimmed
    suffix = f"({', '.join(suffix_parts)})"
    if "\n" not in trimmed:
        return f"{trimmed} {suffix}"
    lines = trimmed.splitlines()
    if not lines:
        return f"{trimmed} {suffix}"
    lines[0] = f"{lines[0]} {suffix}"
    return "\n".join(lines)

def _read_status_env_flag(name: str) -> str:
    return str(os.getenv(name, "") or "").strip().lower()

def _plain_progress_override_requested() -> bool | None:
    value = _read_status_env_flag(_STATUS_PLAIN_PROGRESS_ENV)
    if value in _STATUS_ENV_TRUE_VALUES:
        return True
    if value in _STATUS_ENV_FALSE_VALUES:
        return False
    return None

def _is_agent_execution_environment() -> bool:
    if _read_status_env_flag("CODEX_CI") in _STATUS_ENV_TRUE_VALUES:
        return True
    for key in _STATUS_AGENT_HINT_ENV_KEYS:
        if key == "CODEX_CI":
            continue
        if str(os.getenv(key, "") or "").strip():
            return True
    return False

def _should_default_plain_progress_for_agent() -> bool:
    # Agent PTY polling tends to duplicate spinner frames into noisy logs.
    return _is_agent_execution_environment()

def _enforce_live_labelstudio_benchmark_codex_guardrails(
    *,
    any_codex_enabled: bool,
    benchmark_codex_confirmation: str | None,
) -> None:
    if not any_codex_enabled:
        return
    if _INTERACTIVE_CLI_ACTIVE.get():
        return
    if _is_agent_execution_environment():
        _fail(
            "labelstudio-benchmark with live Codex-backed surfaces is blocked in "
            "agent-run environments. Use prompt preview or a fake-codex-farm rehearsal "
            "for zero-token validation, or have a human run the live benchmark manually "
            "outside the agent environment."
        )
    if (
        str(benchmark_codex_confirmation or "").strip()
        != BENCH_CODEX_FARM_CONFIRMATION_TOKEN
    ):
        _fail(
            "labelstudio-benchmark with live Codex-backed surfaces requires explicit "
            "positive user confirmation. Re-run with --benchmark-codex-confirmation "
            f"{BENCH_CODEX_FARM_CONFIRMATION_TOKEN} only after the user has explicitly "
            "approved this benchmark."
        )

def _enforce_live_bench_speed_codex_guardrails(*, include_codex_farm: bool) -> None:
    if not include_codex_farm:
        return
    if _is_agent_execution_environment():
        _fail(
            "bench speed-run with --include-codex-farm is blocked in agent-run "
            "environments. Have a human run the live Codex benchmark manually outside "
            "the agent environment after explicit user approval."
        )

def _normalize_live_status_slots(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = _LIVE_STATUS_SLOT_MAX_DEFAULT
    if normalized < 1:
        return _LIVE_STATUS_SLOT_MAX_DEFAULT
    return min(_LIVE_STATUS_SLOT_MAX_HARD_CAP, normalized)

def _read_live_status_slots_from_env() -> int:
    raw_value = _read_status_env_flag(_STATUS_LIVE_SLOTS_ENV)
    if raw_value == "":
        return _LIVE_STATUS_SLOT_MAX_DEFAULT
    return _normalize_live_status_slots(raw_value)

def _effective_live_status_slots() -> int:
    override = _BENCHMARK_LIVE_STATUS_SLOTS.get()
    if override is not None:
        return _normalize_live_status_slots(override)
    return _read_live_status_slots_from_env()

@contextmanager
def _acquire_live_status_slot(slot_limit: int) -> Iterable[bool]:
    global _LIVE_STATUS_SLOT_ACTIVE
    normalized_limit = _normalize_live_status_slots(slot_limit)
    acquired = False
    with _LIVE_STATUS_SLOT_LOCK:
        if _LIVE_STATUS_SLOT_ACTIVE < normalized_limit:
            _LIVE_STATUS_SLOT_ACTIVE += 1
            acquired = True
    try:
        yield acquired
    finally:
        if not acquired:
            return
        with _LIVE_STATUS_SLOT_LOCK:
            _LIVE_STATUS_SLOT_ACTIVE = max(0, _LIVE_STATUS_SLOT_ACTIVE - 1)

def _resolve_live_status_console(*, live_status_slots: int) -> Any:
    if live_status_slots <= 1:
        return console
    if not isinstance(console, Console):
        return console
    width_value = getattr(console, "width", None)
    width = width_value if isinstance(width_value, int) and width_value > 0 else None
    return Console(
        file=getattr(console, "file", None),
        force_terminal=bool(console.is_terminal),
        color_system=console.color_system,
        width=width,
        soft_wrap=bool(getattr(console, "soft_wrap", False)),
        markup=bool(getattr(console, "_markup", True)),
    )

def _format_processing_time(elapsed_seconds: float) -> str:
    total_seconds = max(0, int(round(elapsed_seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"

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

def _processing_timeseries_history_path(
    *,
    root: Path,
    scope: str,
    source_name: str | None = None,
) -> Path:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    scope_slug = slugify_name(scope) or "processing"
    source_slug = (
        slugify_name(Path(source_name).stem)
        if source_name is not None and str(source_name).strip()
        else ""
    )
    base_name = f"{timestamp}__{scope_slug}"
    if source_slug:
        base_name = f"{base_name}__{source_slug}"
    telemetry_dir = root / ".history" / "processing_timeseries"
    candidate = telemetry_dir / f"{base_name}.jsonl"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        candidate = telemetry_dir / f"{base_name}__{suffix}.jsonl"
        if not candidate.exists():
            return candidate
        suffix += 1

def _append_processing_timeseries_marker(
    *,
    telemetry_path: Path,
    event: str,
    payload: dict[str, Any],
) -> None:
    event_name = str(event or "").strip()
    if not event_name:
        return
    row = {
        "event": event_name,
        "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(
            timespec="milliseconds"
        ),
    }
    row.update(payload)
    try:
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with telemetry_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(row), sort_keys=True) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ignoring processing time-series marker write failure for %s: %s",
            telemetry_path,
            exc,
        )

def _run_with_progress_status(
    *,
    initial_status: str,
    progress_prefix: str,
    run: Callable[[Callable[[str], None]], _StatusReturn],
    elapsed_threshold_seconds: int = _STATUS_ELAPSED_THRESHOLD_SECONDS,
    tick_seconds: float = _STATUS_TICK_SECONDS,
    telemetry_path: Path | None = None,
    telemetry_heartbeat_seconds: float = PROCESSING_TIMESERIES_HEARTBEAT_SECONDS,
    force_live_status: bool | None = None,
) -> _StatusReturn:
    status_started_at = time.monotonic()
    live_status_slots = _effective_live_status_slots()
    supports_live_status = (
        bool(force_live_status)
        if force_live_status is not None
        else bool(console.is_terminal and not console.is_dumb_terminal)
    )
    if force_live_status is None:
        plain_override = _plain_progress_override_requested()
        if plain_override is True:
            supports_live_status = False
        elif plain_override is None and _should_default_plain_progress_for_agent():
            supports_live_status = False
    latest_message = ""
    latest_message_started = time.monotonic()
    latest_counter: tuple[int, int] | None = None
    latest_running_workers: int | None = None
    latest_worker_total: int | None = None
    latest_active_tasks: list[str] | None = None
    latest_codex_stage_label: str | None = None
    latest_stage_label: str | None = None
    latest_work_unit_label: str | None = None
    latest_stage_detail_lines: list[str] = []
    latest_worker_running: int | None = None
    latest_worker_completed: int | None = None
    latest_worker_failed: int | None = None
    latest_followup_running: int | None = None
    latest_followup_completed: int | None = None
    latest_followup_total: int | None = None
    latest_followup_label: str | None = None
    latest_artifact_counts: dict[str, int] = {}
    latest_last_activity_at: str | None = None
    status_dashboard = ProgressDashboardCore()
    worker_dashboard_adapter = ProgressCallbackAdapter(status_dashboard)
    status_dashboard.set_status_line(str(initial_status).strip() or str(progress_prefix).strip())
    rate_total: int | None = None
    rate_last_current: int | None = None
    rate_last_progress_at: float | None = None
    rate_sampled_seconds = 0.0
    rate_sampled_units = 0
    rate_recent_samples: deque[tuple[float, int]] = deque(
        maxlen=_STATUS_RATE_RECENT_WINDOW
    )
    all_method_metrics: dict[str, int] = {}
    state_lock = threading.Lock()
    stop_event = threading.Event()
    _PROGRESS_BLUE_STYLE = "blue"
    _PROGRESS_BLUE_ANSI = "\x1b[34m"
    _PROGRESS_ANSI_RESET = "\x1b[0m"
    timeseries_writer: _ProcessingTimeseriesWriter | None = None
    if telemetry_path is not None:
        telemetry_file = Path(telemetry_path).expanduser()
        if telemetry_file.exists():
            telemetry_file.unlink()
        timeseries_writer = _ProcessingTimeseriesWriter(
            path=telemetry_file,
            heartbeat_seconds=max(0.05, float(telemetry_heartbeat_seconds)),
        )

    _WORKER_PANEL_LABEL_RE = re.compile(
        r"^\s*(?:active\s+tasks|active\s+workers)\b",
        re.IGNORECASE,
    )
    _WORKER_PREFIX_RE = re.compile(
        r"^worker\s+\d+\s*:",
        re.IGNORECASE,
    )
    _ACTIVE_TASKS_RE = re.compile(
        r"\bactive\s*\[([^]]*)\]",
        re.IGNORECASE,
    )
    _CODEX_FARM_PIPELINE_PREFIX_RE = re.compile(
        r"^codex-farm\s+(?P<pipeline>\S+)",
        re.IGNORECASE,
    )
    _RUNNING_WORKERS_RE = re.compile(
        r"\brunning\s+(\d+)\b",
        re.IGNORECASE,
    )
    _CODEX_ERROR_COUNT_RE = re.compile(
        r"\berrors?\s+(\d+)\b",
        re.IGNORECASE,
    )
    _CODEX_FARM_PROGRESS_LINE_RE = re.compile(
        r"^codex-farm\s+",
        re.IGNORECASE,
    )

    def _extract_active_tasks(message: str) -> list[str] | None:
        match = _ACTIVE_TASKS_RE.search(str(message or ""))
        if match is None:
            return None
        raw = str(match.group(1)).strip()
        if not raw:
            return []
        values = [item.strip() for item in raw.split(",")]
        cleaned = [value for value in values if value]
        return cleaned[:max(1, 8)]

    def _extract_running_workers(message: str) -> int | None:
        match = _RUNNING_WORKERS_RE.search(str(message or ""))
        if match is None:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _humanize_codex_pipeline_stage_label(pipeline_id: str) -> str:
        normalized = str(pipeline_id or "").strip()
        lowered = normalized.lower()
        if not normalized:
            return "codex stage"
        if "recipe.correction" in lowered or "recipe_correction" in lowered or "correction" in lowered:
            return "recipe correction"
        if "knowledge" in lowered:
            return "non-recipe knowledge review"
        if "tags" in lowered:
            return "tag suggestions"
        return normalized

    def _summarize_codex_progress_message(message: str) -> tuple[str, str | None]:
        trimmed = str(message or "").strip()
        match = _CODEX_FARM_PIPELINE_PREFIX_RE.match(trimmed)
        if match is None:
            return trimmed, None

        raw_pipeline = str(match.group("pipeline") or "").strip()
        pipeline_id = raw_pipeline[:-1] if raw_pipeline.endswith(":") else raw_pipeline
        stage_label = _humanize_codex_pipeline_stage_label(pipeline_id)
        counter = _extract_progress_counter(trimmed)
        running = _extract_running_workers(trimmed)
        error_match = _CODEX_ERROR_COUNT_RE.search(trimmed)
        errors = int(error_match.group(1)) if error_match is not None else 0

        if counter is not None:
            current, total = counter
            parts = [
                f"codex-farm {stage_label}",
                f"task {current}/{total}",
            ]
            if running is not None and running > 0:
                parts.append(f"running {running}")
            if errors > 0:
                parts.append(f"errors {errors}")
            return " | ".join(parts), stage_label

        suffix = trimmed[match.end() :].strip()
        if suffix.startswith(":"):
            suffix = suffix[1:].strip()
        if suffix:
            return f"codex-farm {stage_label}: {suffix}", stage_label
        return f"codex-farm {stage_label}", stage_label

    def _render_artifact_counts_line(artifact_counts: Mapping[str, Any] | None) -> str | None:
        if not isinstance(artifact_counts, Mapping):
            return None
        parts: list[str] = []
        for key, value in sorted(artifact_counts.items()):
            cleaned_key = str(key or "").strip()
            try:
                cleaned_value = max(0, int(value))
            except (TypeError, ValueError):
                continue
            if not cleaned_key:
                continue
            parts.append(f"{cleaned_key.replace('_', ' ')} {cleaned_value}")
        if not parts:
            return None
        return "artifacts: " + " | ".join(parts)

    def _render_worker_summary_line(
        *,
        worker_running: int | None,
        worker_completed: int | None,
        worker_failed: int | None,
        worker_total: int | None,
    ) -> str | None:
        summary_parts: list[str] = []
        for label, value in (
            ("running", worker_running),
            ("completed", worker_completed),
            ("failed", worker_failed),
        ):
            if value is None:
                continue
            summary_parts.append(f"{max(0, int(value))} {label}")
        if worker_total is not None:
            summary_parts.append(f"{max(0, int(worker_total))} total")
        if not summary_parts:
            return None
        return "workers: " + ", ".join(summary_parts)

    def _render_followup_summary_line(
        *,
        followup_label: str | None,
        followup_running: int | None,
        followup_completed: int | None,
        followup_total: int | None,
    ) -> str | None:
        cleaned_label = str(followup_label or "").strip() or "follow-up"
        summary_parts: list[str] = [cleaned_label]
        if followup_completed is not None and followup_total is not None:
            summary_parts.append(
                f"{max(0, int(followup_completed))}/{max(0, int(followup_total))}"
            )
        if followup_running is not None:
            summary_parts.append(f"running {max(0, int(followup_running))}")
        if len(summary_parts) == 1 and cleaned_label == "follow-up":
            return None
        return "repo follow-up: " + " | ".join(summary_parts)

    def _inject_worker_summary_lines(snapshot: str) -> str:
        with state_lock:
            running_workers = latest_running_workers
            worker_total = latest_worker_total
            active_tasks = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
            work_unit_label = (
                str(latest_work_unit_label).strip()
                if latest_work_unit_label is not None
                else ""
            )
            codex_stage_label = (
                str(latest_codex_stage_label).strip()
                if latest_codex_stage_label is not None
                else ""
            )
            stage_label = (
                codex_stage_label
                or (
                    str(latest_stage_label).strip()
                    if latest_stage_label is not None
                    else ""
                )
            )
            detail_lines = list(latest_stage_detail_lines)
            worker_running = latest_worker_running
            worker_completed = latest_worker_completed
            worker_failed = latest_worker_failed
            followup_running = latest_followup_running
            followup_completed = latest_followup_completed
            followup_total = latest_followup_total
            followup_label = latest_followup_label
            artifact_counts = dict(latest_artifact_counts)
            task_counter = latest_counter
        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and not stage_label
            and not work_unit_label
            and not detail_lines
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
            and followup_running is None
            and followup_completed is None
            and followup_total is None
            and not followup_label
            and not artifact_counts
            and task_counter is None
        ):
            return snapshot

        lines = [line.strip() for line in str(snapshot or "").splitlines() if line.strip()]
        if not lines:
            return ""

        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and not detail_lines
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
            and followup_running is None
            and followup_completed is None
            and followup_total is None
            and not followup_label
            and not artifact_counts
            and task_counter is None
        ):
            return "\n".join(lines)

        if stage_label and not any(
            line.lower().startswith("stage:")
            for line in lines
        ):
            lines.insert(1, f"stage: {stage_label}")

        progress_lines: list[str] = []
        if task_counter is not None and not any(
            line.lower().startswith("progress:")
            for line in lines
        ):
            counter_current, counter_total = task_counter
            counter_label = work_unit_label or "task"
            progress_percent = 0
            if counter_total > 0:
                progress_percent = int(
                    round((float(counter_current) / float(counter_total)) * 100.0)
                )
            progress_lines.append(
                f"progress: {counter_label} {counter_current}/{counter_total} ({progress_percent}%)"
            )
            remaining_tasks = max(0, int(counter_total) - int(counter_current))
            if remaining_tasks > 0:
                remaining_label = (work_unit_label or "task").replace("_", " ")
                progress_lines.append(f"remaining {remaining_label}s: {remaining_tasks}")
        if progress_lines:
            insert_at = 2 if len(lines) > 1 and lines[1].lower().startswith("stage:") else 1
            for progress_line in reversed(progress_lines):
                lines.insert(insert_at, progress_line)

        summary_lines = [
            line
            for line in (
                _render_worker_summary_line(
                    worker_running=worker_running,
                    worker_completed=worker_completed,
                    worker_failed=worker_failed,
                    worker_total=worker_total,
                ),
                _render_followup_summary_line(
                    followup_label=followup_label,
                    followup_running=followup_running,
                    followup_completed=followup_completed,
                    followup_total=followup_total,
                ),
                _render_artifact_counts_line(artifact_counts),
            )
            if line
        ]
        if summary_lines or detail_lines:
            insert_at = 1 if lines else 0
            if len(lines) > 1 and lines[1].lower().startswith("stage:"):
                insert_at = 2
                if len(lines) > 2 and lines[2].lower().startswith("progress:"):
                    insert_at = 3
                    if len(lines) > 3 and lines[3].lower().startswith("remaining "):
                        insert_at = 4
            inserted_lines = [*summary_lines, *detail_lines]
            for detail_line in reversed(inserted_lines):
                if detail_line and detail_line not in lines:
                    lines.insert(insert_at, detail_line)

        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
        ):
            return "\n".join(lines)

        if any(
            _WORKER_PANEL_LABEL_RE.search(line)
            or _WORKER_PREFIX_RE.match(line)
            for line in lines
        ):
            return "\n".join(lines)

        typed_running_slots = (
            max(0, int(worker_running)) if worker_running is not None else None
        )
        running_slots = (
            typed_running_slots
            if typed_running_slots is not None
            else max(0, int(running_workers))
            if running_workers is not None
            else 0
        )
        configured_slots = max(0, int(worker_total)) if worker_total is not None else 0
        completed_slots = max(0, int(worker_completed or 0))
        failed_slots = max(0, int(worker_failed or 0))
        display_slots = max(
            configured_slots,
            len(active_tasks or []),
            max(0, int(running_workers or 0)),
            running_slots + completed_slots + failed_slots,
        )
        if running_slots <= 0:
            if running_workers is None and worker_total is None:
                running_slots = display_slots
            else:
                running_slots = 0
        else:
            running_slots = max(running_slots, 1)
        if (
            running_slots <= 0
            and completed_slots <= 0
            and failed_slots <= 0
            and configured_slots <= 0
            and not (active_tasks or [])
        ):
            return "\n".join(lines)

        worker_lines: list[str] = []
        slot_statuses: list[str] = []
        if active_tasks is not None:
            task_count = len(active_tasks)
            tasks_left: int | None = None
            if task_counter is not None:
                counter_current, counter_total = task_counter
                tasks_left = max(0, int(counter_total) - int(counter_current))
            if task_count > 0:
                active_tasks_label = (
                    f"active tasks ({task_count}"
                    + (f"/{running_slots}" if running_slots else "")
                )
                if tasks_left is not None:
                    active_tasks_label += f", {tasks_left} left"
                active_tasks_label += ")"
                worker_lines.append(
                    active_tasks_label
                )
            slot_statuses.extend(
                str(task).strip() or "[unknown task]"
                for task in active_tasks[:running_slots]
            )
            if len(slot_statuses) < running_slots:
                slot_statuses.extend(
                    ["processing (unresolved)"] * (running_slots - len(slot_statuses))
                )
        else:
            worker_lines.append(f"active workers: {running_slots}")
        slot_statuses.extend(["running"] * max(0, running_slots - len(slot_statuses)))
        slot_statuses.extend(["done"] * completed_slots)
        slot_statuses.extend(["failed"] * failed_slots)
        target_slots = max(display_slots, len(slot_statuses))
        if len(slot_statuses) < target_slots:
            slot_statuses.extend(["idle"] * (target_slots - len(slot_statuses)))
        active_slots = running_slots
        if not worker_lines:
            worker_lines.append(f"active workers: {active_slots}")
        if configured_slots > 0 and configured_slots != active_slots:
            worker_lines.append(f"configured workers: {configured_slots}")
        for index, status in enumerate(slot_statuses[:target_slots], start=1):
            worker_lines.append(f"worker {index:02d}: {status}")

        if running_slots <= 0 and not worker_lines:
            return "\n".join(lines)
        if running_slots <= 0 and worker_lines == ["active workers: 0"]:
            return "\n".join(lines)

        if not worker_lines:
            return "\n".join(lines)

        insert_at = len(lines)
        for index, line in enumerate(lines):
            if line.lower().startswith("task:"):
                insert_at = index + 1
                break
        merged = lines[:insert_at] + worker_lines + lines[insert_at:]
        return "\n".join(merged)

    def _format_boxed_progress(snapshot: str) -> str:
        def _wrap_panel_text(value: str, max_chars: int) -> list[str]:
            text = str(value or "")
            if max_chars <= 0:
                return [""]
            if not text:
                return [""]
            wrapped = textwrap.wrap(
                text,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
                drop_whitespace=False,
                replace_whitespace=False,
            )
            if wrapped:
                return wrapped
            if len(text) <= max_chars:
                return [text]
            return [text[:max_chars]]

        def _truncate_panel_text(value: str, max_chars: int) -> str:
            text = str(value or "")
            if max_chars <= 0:
                return ""
            if len(text) <= max_chars:
                return text
            if max_chars <= 3:
                return text[:max_chars]
            # Preserve trailing timing details (eta/avg/elapsed suffix) when long
            # status lines are clamped to terminal width.
            if text.endswith(")"):
                eta_start = text.rfind(" (eta ")
                suffix_start = eta_start + 1 if eta_start >= 0 else -1
                if suffix_start <= 0:
                    generic_suffix = text.rfind(" (")
                    if generic_suffix >= 0 and (len(text) - generic_suffix) <= 32:
                        suffix_start = generic_suffix + 1
                if suffix_start > 0:
                    suffix = text[suffix_start:]
                    suffix_budget = max_chars - 3
                    if suffix_budget > 0 and suffix:
                        if len(suffix) >= suffix_budget:
                            return "..." + suffix[-suffix_budget:]
                        prefix_budget = max_chars - len(suffix) - 3
                        if prefix_budget > 0:
                            return text[:prefix_budget] + "..." + suffix
            return text[: max_chars - 3] + "..."

        lines = [
            line.rstrip()
            for line in str(snapshot or "").splitlines()
            if line.strip()
        ]
        if not lines:
            return ""

        max_panel_width = 132
        terminal_width = getattr(console, "width", None)
        if isinstance(terminal_width, int) and terminal_width > 0:
            # Keep room for the spinner glyph + padding prefix Rich adds.
            max_panel_width = min(max_panel_width, max(28, terminal_width - 6))

        width = max(len(line) for line in lines)
        title = (progress_prefix or initial_status).strip() or "Progress"
        width = max(width, len(title))
        width = max(1, min(width, max_panel_width))
        wrapped_lines: list[str] = []
        for line in lines:
            wrapped_lines.extend(_wrap_panel_text(line, width))
        if not wrapped_lines:
            wrapped_lines = [""]
        header = f"| {_truncate_panel_text(title, width).center(width)} |"
        top_bottom = "+" + "-" * (width + 2) + "+"
        divider = "+" + "-" * (width + 2) + "+"
        body_lines = [
            f"| {_truncate_panel_text(line, width).ljust(width)} |"
            for line in wrapped_lines
        ]
        return "\n".join([top_bottom, header, divider, *body_lines, top_bottom])

    def _build_status_line(now: float | None = None) -> str:
        current = now if now is not None else time.monotonic()
        with state_lock:
            message = latest_message
            started_at = latest_message_started
            counter = latest_counter
            tracked_total = rate_total
            last_progress_at = rate_last_progress_at
            sampled_seconds = rate_sampled_seconds
            sampled_units = rate_sampled_units
            recent_avg = _recent_rate_average_seconds_per_task(rate_recent_samples)
            dashboard_metrics = dict(all_method_metrics)
            running_workers_hint = latest_running_workers
            worker_total_hint = latest_worker_total
            active_tasks_hint = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
        if not message:
            base = str(initial_status).strip() or str(progress_prefix).strip()
        else:
            elapsed = max(0, int(current - started_at))
            eta_seconds: int | None = None
            avg_seconds_per_task: float | None = None
            if (
                counter is not None
                and tracked_total is not None
                and counter[1] == tracked_total
            ):
                counter_current, counter_total = counter
                remaining = max(0, counter_total - counter_current)
                if recent_avg is not None:
                    avg_seconds_per_task = recent_avg
                elif sampled_units > 0 and sampled_seconds > 0:
                    avg_seconds_per_task = sampled_seconds / sampled_units
                elif counter_current > 0:
                    bootstrap_elapsed = max(0.0, current - status_started_at)
                    if bootstrap_elapsed >= _STATUS_ETA_BOOTSTRAP_MIN_SECONDS:
                        avg_seconds_per_task = bootstrap_elapsed / float(counter_current)
                if (
                    remaining > 0
                    and avg_seconds_per_task is not None
                    and avg_seconds_per_task > 0
                ):
                    active_parallelism = max(
                        0,
                        int(running_workers_hint or 0),
                        len(active_tasks_hint or []),
                    )
                    configured_parallelism = max(0, int(worker_total_hint or 0))
                    bootstrap_parallelism = active_parallelism or configured_parallelism or 1
                    if recent_avg is None and not (sampled_units > 0 and sampled_seconds > 0):
                        eta_seconds = _parallel_bootstrap_eta_seconds(
                            avg_seconds_per_task=avg_seconds_per_task,
                            remaining=remaining,
                            parallelism=bootstrap_parallelism,
                        )
                    else:
                        eta_seconds = int(round(avg_seconds_per_task * remaining))
                    active_hint = max(0, int(dashboard_metrics.get("active") or 0))
                    eval_hint = max(0, int(dashboard_metrics.get("eval") or 0))
                    if (
                        active_hint > 0
                        and eval_hint > 0
                        and last_progress_at is not None
                    ):
                        stalled_seconds = max(0.0, current - last_progress_at)
                        if stalled_seconds >= max(
                            _STATUS_ALL_METHOD_STALL_MIN_SECONDS,
                            avg_seconds_per_task * _STATUS_ALL_METHOD_STALL_MULTIPLIER,
                        ):
                            stalled_floor = stalled_seconds / float(active_hint)
                            if stalled_floor > avg_seconds_per_task:
                                eta_seconds = max(
                                    eta_seconds,
                                    int(round(stalled_floor * remaining)),
                                )
            decorated = _format_status_progress_message(
                message,
                elapsed_seconds=elapsed,
                elapsed_threshold_seconds=elapsed_threshold_seconds,
                eta_seconds=eta_seconds,
                avg_seconds_per_task=avg_seconds_per_task,
            )
            return f"{progress_prefix}: {decorated}".strip()
        return str(initial_status).strip() or str(progress_prefix).strip()

    def render_plain(now: float | None = None) -> str:
        status_dashboard.set_status_line(_build_status_line(now))
        return _inject_worker_summary_lines(status_dashboard.render())

    def render(now: float | None = None) -> str:
        snapshot = render_plain(now)
        if not snapshot:
            return ""
        escaped = rich_escape(snapshot)
        return (
            f"[{_PROGRESS_BLUE_STYLE}]"
            f"{_format_boxed_progress(escaped)}"
            f"[/{_PROGRESS_BLUE_STYLE}]"
        )

    def _emit_timeseries(
        *,
        event: str,
        force: bool = False,
        now: float | None = None,
    ) -> None:
        if timeseries_writer is None:
            return
        current = now if now is not None else time.monotonic()
        with state_lock:
            message = latest_message
            started_at = latest_message_started
            counter = latest_counter
            running_workers_hint = latest_running_workers
            worker_total_hint = latest_worker_total
            stage_label = latest_stage_label
            work_unit_label = latest_work_unit_label
            detail_lines = list(latest_stage_detail_lines)
            worker_running_hint = latest_worker_running
            worker_completed_hint = latest_worker_completed
            worker_failed_hint = latest_worker_failed
            followup_running_hint = latest_followup_running
            followup_completed_hint = latest_followup_completed
            followup_total_hint = latest_followup_total
            followup_label_hint = latest_followup_label
            artifact_counts_hint = dict(latest_artifact_counts)
            last_activity_at_hint = latest_last_activity_at
            active_tasks_hint = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
        worker_total, worker_statuses = worker_dashboard_adapter.snapshot_workers()
        elapsed_seconds = max(0.0, current - started_at)
        message_value = str(message or initial_status).strip() or str(initial_status).strip()
        counter_current: int | None = None
        counter_total: int | None = None
        if counter is not None:
            counter_current = max(0, int(counter[0]))
            counter_total = max(0, int(counter[1]))
        worker_active = sum(
            1
            for status in worker_statuses.values()
            if str(status).strip().lower() not in {"", "idle", "done", "skipped"}
        )
        if worker_total <= 0 and worker_total_hint is not None:
            worker_total = max(0, int(worker_total_hint))
        if worker_total <= 0 and running_workers_hint is not None:
            worker_total = max(0, int(running_workers_hint))
        if worker_active <= 0 and running_workers_hint is not None:
            worker_active = max(0, int(running_workers_hint))
        snapshot = message_value
        if counter_current is not None and counter_total is not None:
            snapshot = f"{snapshot} | task {counter_current}/{counter_total}"
        if worker_total > 0:
            snapshot = f"{snapshot} | workers {worker_total}"
        timeseries_writer.write_row(
            snapshot=snapshot,
            force=force,
            payload={
                "event": str(event or "").strip() or "update",
                "progress_prefix": progress_prefix,
                "message": message_value,
                "elapsed_seconds": elapsed_seconds,
                "stage_label": str(stage_label or "").strip() or None,
                "work_unit_label": str(work_unit_label or "").strip() or None,
                "task_current": counter_current,
                "task_total": counter_total,
                "worker_total": max(0, int(worker_total)),
                "worker_active": max(0, int(worker_active)),
                "worker_running": (
                    max(0, int(worker_running_hint))
                    if worker_running_hint is not None
                    else None
                ),
                "worker_completed": (
                    max(0, int(worker_completed_hint))
                    if worker_completed_hint is not None
                    else None
                ),
                "worker_failed": (
                    max(0, int(worker_failed_hint))
                    if worker_failed_hint is not None
                    else None
                ),
                "followup_running": (
                    max(0, int(followup_running_hint))
                    if followup_running_hint is not None
                    else None
                ),
                "followup_completed": (
                    max(0, int(followup_completed_hint))
                    if followup_completed_hint is not None
                    else None
                ),
                "followup_total": (
                    max(0, int(followup_total_hint))
                    if followup_total_hint is not None
                    else None
                ),
                "followup_label": str(followup_label_hint or "").strip() or None,
                "artifact_counts": artifact_counts_hint or None,
                "last_activity_at": str(last_activity_at_hint or "").strip() or None,
                "active_tasks": list(active_tasks_hint or []),
                "detail_lines": detail_lines,
                "worker_activity": {
                    str(key): str(value)
                    for key, value in sorted(worker_statuses.items())
                },
            },
        )

    last_plain_snapshot = ""

    def _update_progress_common(msg: str) -> tuple[bool, float]:
        nonlocal latest_message, latest_message_started
        nonlocal latest_counter, rate_total, rate_last_current, rate_last_progress_at
        nonlocal rate_sampled_seconds, rate_sampled_units
        nonlocal rate_recent_samples, all_method_metrics
        nonlocal latest_running_workers, latest_worker_total, latest_active_tasks
        nonlocal latest_codex_stage_label, latest_stage_label, latest_stage_detail_lines
        nonlocal latest_work_unit_label
        nonlocal latest_worker_running, latest_worker_completed, latest_worker_failed
        nonlocal latest_followup_running, latest_followup_completed, latest_followup_total
        nonlocal latest_followup_label, latest_artifact_counts, latest_last_activity_at
        now = time.monotonic()
        cleaned = msg.strip()
        is_worker_activity = parse_worker_activity(cleaned) is not None
        stage_progress = (
            None if is_worker_activity else parse_stage_progress(cleaned)
        )
        stage_detail_lines: list[str] | None = None
        structured_counter: tuple[int, int] | None = None
        structured_running_workers: int | None = None
        structured_worker_total: int | None = None
        structured_active_tasks: list[str] | None = None
        structured_work_unit_label: str | None = None
        structured_worker_running: int | None = None
        structured_worker_completed: int | None = None
        structured_worker_failed: int | None = None
        structured_followup_running: int | None = None
        structured_followup_completed: int | None = None
        structured_followup_total: int | None = None
        structured_followup_label: str | None = None
        structured_artifact_counts: dict[str, int] | None = None
        structured_last_activity_at: str | None = None
        current_stage_label: str | None = None
        stage_changed = False
        if stage_progress is not None:
            cleaned = str(stage_progress.get("message") or "").strip() or cleaned
            structured_work_unit_label = (
                str(stage_progress.get("work_unit_label") or "").strip() or None
            )
            task_current = stage_progress.get("task_current")
            task_total = stage_progress.get("task_total")
            if task_current is not None and task_total is not None:
                structured_counter = (int(task_current), int(task_total))
            running_hint = stage_progress.get("running_workers")
            if running_hint is not None:
                structured_running_workers = max(0, int(running_hint))
            worker_total_hint = stage_progress.get("worker_total")
            if worker_total_hint is not None:
                structured_worker_total = max(0, int(worker_total_hint))
            worker_running_hint = stage_progress.get("worker_running")
            if worker_running_hint is not None:
                structured_worker_running = max(0, int(worker_running_hint))
            worker_completed_hint = stage_progress.get("worker_completed")
            if worker_completed_hint is not None:
                structured_worker_completed = max(0, int(worker_completed_hint))
            worker_failed_hint = stage_progress.get("worker_failed")
            if worker_failed_hint is not None:
                structured_worker_failed = max(0, int(worker_failed_hint))
            followup_running_hint = stage_progress.get("followup_running")
            if followup_running_hint is not None:
                structured_followup_running = max(0, int(followup_running_hint))
            followup_completed_hint = stage_progress.get("followup_completed")
            if followup_completed_hint is not None:
                structured_followup_completed = max(0, int(followup_completed_hint))
            followup_total_hint = stage_progress.get("followup_total")
            if followup_total_hint is not None:
                structured_followup_total = max(0, int(followup_total_hint))
            structured_followup_label = (
                str(stage_progress.get("followup_label") or "").strip() or None
            )
            artifact_counts_hint = stage_progress.get("artifact_counts")
            if isinstance(artifact_counts_hint, dict):
                structured_artifact_counts = {
                    str(key).strip(): max(0, int(value))
                    for key, value in artifact_counts_hint.items()
                    if str(key).strip()
                }
            structured_last_activity_at = (
                str(stage_progress.get("last_activity_at") or "").strip() or None
            )
            active_tasks_hint = stage_progress.get("active_tasks")
            if isinstance(active_tasks_hint, list):
                structured_active_tasks = [
                    str(value).strip()
                    for value in active_tasks_hint
                    if str(value).strip()
                ]
            detail_hint = stage_progress.get("detail_lines")
            if isinstance(detail_hint, list):
                stage_detail_lines = [
                    str(value).strip()
                    for value in detail_hint
                    if str(value).strip()
                ]
            current_stage_label = (
                str(stage_progress.get("stage_label") or "").strip()
                or _extract_progress_stage_label(cleaned)
            )
        counter = None
        generic_counter = (
            structured_counter
            if structured_counter is not None
            else _extract_progress_counter(cleaned)
            if not is_worker_activity
            else None
        )
        generic_running_workers = (
            structured_running_workers
            if structured_running_workers is not None
            else _extract_running_workers(cleaned)
            if generic_counter is not None
            else None
        )
        is_codex_progress = (
            stage_progress is None
            and _CODEX_FARM_PROGRESS_LINE_RE.search(cleaned) is not None
        )
        if is_codex_progress:
            running_workers = _extract_running_workers(cleaned)
            active_tasks = _extract_active_tasks(cleaned)
            codex_stage_label: str | None
            if running_workers is not None:
                latest_running_workers = running_workers
            if active_tasks is not None:
                latest_active_tasks = active_tasks
            else:
                latest_active_tasks = None
            summarized, codex_stage_label = _summarize_codex_progress_message(cleaned)
            cleaned = summarized
            current_stage_label = codex_stage_label or _extract_progress_stage_label(cleaned)
            if current_stage_label != latest_stage_label:
                latest_worker_total = None
                latest_work_unit_label = None
                latest_stage_detail_lines = []
                latest_worker_running = None
                latest_worker_completed = None
                latest_worker_failed = None
                latest_followup_running = None
                latest_followup_completed = None
                latest_followup_total = None
                latest_followup_label = None
                latest_artifact_counts = {}
                latest_last_activity_at = None
            latest_stage_label = current_stage_label
            latest_codex_stage_label = codex_stage_label
            if current_stage_label == latest_stage_label:
                latest_running_workers = running_workers
        elif not is_worker_activity:
            current_stage_label = current_stage_label or _extract_progress_stage_label(cleaned)
            stage_changed = current_stage_label != latest_stage_label
            if stage_changed:
                latest_running_workers = None
                latest_worker_total = None
                latest_active_tasks = None
                latest_work_unit_label = None
                latest_stage_detail_lines = []
                latest_worker_running = None
                latest_worker_completed = None
                latest_worker_failed = None
                latest_followup_running = None
                latest_followup_completed = None
                latest_followup_total = None
                latest_followup_label = None
                latest_artifact_counts = {}
                latest_last_activity_at = None
            if generic_running_workers is not None:
                latest_running_workers = generic_running_workers
            elif stage_progress is not None:
                latest_running_workers = None
            if structured_worker_total is not None:
                latest_worker_total = structured_worker_total
            elif stage_progress is not None:
                latest_worker_total = None
            if structured_active_tasks is not None:
                latest_active_tasks = structured_active_tasks
            elif stage_progress is not None:
                latest_active_tasks = None
            if stage_progress is not None:
                latest_work_unit_label = structured_work_unit_label
                latest_worker_running = (
                    structured_worker_running
                    if structured_worker_running is not None
                    else structured_running_workers
                )
                latest_worker_completed = structured_worker_completed
                latest_worker_failed = structured_worker_failed
                latest_followup_running = structured_followup_running
                latest_followup_completed = structured_followup_completed
                latest_followup_total = structured_followup_total
                latest_followup_label = structured_followup_label
                latest_artifact_counts = dict(structured_artifact_counts or {})
                latest_last_activity_at = structured_last_activity_at
            elif stage_changed:
                latest_active_tasks = None
            if stage_detail_lines is not None:
                latest_stage_detail_lines = stage_detail_lines
            elif stage_progress is not None:
                latest_stage_detail_lines = []
            elif stage_changed:
                latest_stage_detail_lines = []
            latest_codex_stage_label = None
            latest_stage_label = current_stage_label
        # Route every callback through the shared adapter so callback+worker
        # activity both update the same dashboard state machine.
        changed = worker_dashboard_adapter.ingest_callback_message(cleaned)
        with state_lock:
            if not is_worker_activity:
                counter = (
                    structured_counter
                    if structured_counter is not None
                    else _extract_progress_counter(cleaned)
                )
                message_changed = cleaned != latest_message
                counter_changed = counter != latest_counter
                if message_changed or counter_changed:
                    changed = True
                if message_changed:
                    latest_message_started = now
                latest_message = cleaned
                latest_counter = counter
                if message_changed:
                    all_method_metrics = _extract_all_method_dashboard_metrics(cleaned)
                if counter is not None:
                    counter_current, counter_total = counter
                    should_reset = (
                        stage_changed
                        or rate_total is None
                        or rate_last_current is None
                        or rate_last_progress_at is None
                        or counter_total != rate_total
                        or counter_current < rate_last_current
                    )
                    if should_reset:
                        changed = True
                        rate_total = counter_total
                        rate_last_current = counter_current
                        rate_last_progress_at = now
                        rate_sampled_seconds = 0.0
                        rate_sampled_units = 0
                        rate_recent_samples.clear()
                    else:
                        delta = counter_current - rate_last_current
                        if delta > 0:
                            elapsed_since_progress = max(0.0, now - rate_last_progress_at)
                            if elapsed_since_progress > 0:
                                rate_sampled_seconds += elapsed_since_progress
                                rate_sampled_units += delta
                                rate_recent_samples.append((elapsed_since_progress, delta))
                            rate_last_current = counter_current
                            rate_last_progress_at = now
        status_dashboard.set_status_line(_build_status_line(now))
        return changed, now

    def _run_plain() -> _StatusReturn:
        nonlocal last_plain_snapshot
        console_file = getattr(console, "file", None)
        plain_tty = bool(
            console.is_terminal
            and not console.is_dumb_terminal
            and hasattr(console_file, "isatty")
            and console_file.isatty()
        )
        initial_snapshot = render_plain()

        def _snapshot_to_single_line(snapshot: str) -> str:
            parts = [line.strip() for line in snapshot.splitlines() if line.strip()]
            if not parts:
                return ""
            return " | ".join(parts)

        def _render_plain_snapshot(snapshot: str) -> None:
            nonlocal last_plain_snapshot
            line = _snapshot_to_single_line(snapshot)
            if not line:
                return
            with state_lock:
                if line == last_plain_snapshot:
                    return
                last_plain_snapshot = line
            if plain_tty:
                assert console_file is not None
                console_file.write(
                    f"\r\u001b[2K{_PROGRESS_BLUE_ANSI}{line}{_PROGRESS_ANSI_RESET}"
                )
                console_file.flush()
            else:
                typer.secho(line, fg=typer.colors.BLUE)

        if initial_snapshot:
            _render_plain_snapshot(initial_snapshot)
        _emit_timeseries(event="started", force=True)

        def tick() -> None:
            while True:
                with state_lock:
                    message_snapshot = latest_message
                    worker_snapshot = worker_dashboard_adapter.snapshot_workers()[0]
                interval = float(tick_seconds)
                if (
                    (worker_snapshot > 0 or "\n" in (message_snapshot or ""))
                    and interval >= 0.5
                ):
                    interval = max(interval, 5.0)
                if stop_event.wait(max(0.05, interval)):
                    return
                now = time.monotonic()
                snapshot = render_plain(now)
                _render_plain_snapshot(snapshot)

        ticker = threading.Thread(
            target=tick,
            name="cli-status-progress-ticker",
            daemon=True,
        )
        ticker.start()

        def update_progress(msg: str) -> None:
            nonlocal last_plain_snapshot
            changed, now = _update_progress_common(msg)
            if not changed:
                return
            snapshot = render_plain(now)
            _render_plain_snapshot(snapshot)
            _emit_timeseries(event="update", now=now)

        try:
            return run(update_progress)
        finally:
            stop_event.set()
            ticker.join(timeout=max(0.2, float(tick_seconds) * 2))
            if plain_tty:
                assert console_file is not None
                console_file.write("\n")
                console_file.flush()
            _emit_timeseries(event="finished", force=True)

    if not supports_live_status:
        return _run_plain()

    with _acquire_live_status_slot(live_status_slots) as live_slot_acquired:
        if not live_slot_acquired:
            return _run_plain()
        status_console = _resolve_live_status_console(
            live_status_slots=live_status_slots
        )
        live_spinner = (
            "bouncingBar"
            if "benchmark" in str(progress_prefix).strip().lower()
            else "dots"
        )
        with status_console.status(
            render(),
            spinner=live_spinner,
            spinner_style=_PROGRESS_BLUE_STYLE,
            refresh_per_second=4.0,
        ) as status:
            _emit_timeseries(event="started", force=True)

            def tick() -> None:
                while True:
                    with state_lock:
                        message_snapshot = latest_message
                        worker_snapshot = worker_dashboard_adapter.snapshot_workers()[0]
                    interval = float(tick_seconds)
                    if (
                        (worker_snapshot > 0 or "\n" in (message_snapshot or ""))
                        and interval >= 0.5
                    ):
                        interval = max(interval, 5.0)
                    if stop_event.wait(max(0.05, interval)):
                        return
                    now = time.monotonic()
                    status.update(render(now))
                    _emit_timeseries(event="tick", now=now)

            ticker = threading.Thread(
                target=tick,
                name="cli-status-progress-ticker",
                daemon=True,
            )
            ticker.start()

            def update_progress(msg: str) -> None:
                changed, now = _update_progress_common(msg)
                if not changed:
                    return
                status.update(render(now))
                _emit_timeseries(event="update", now=now)

            try:
                return run(update_progress)
            finally:
                stop_event.set()
                ticker.join(timeout=max(0.2, float(tick_seconds) * 2))
                _emit_timeseries(event="finished", force=True)

@contextmanager
def _benchmark_progress_overrides(
    *,
    progress_callback: Callable[[str], None] | None = None,
    suppress_summary: bool = False,
    suppress_spinner: bool = False,
    suppress_dashboard_refresh: bool = False,
    suppress_output_prune: bool = False,
    live_status_slots: int | None = None,
) -> Iterable[None]:
    progress_token = _BENCHMARK_PROGRESS_CALLBACK.set(progress_callback)
    summary_token = _BENCHMARK_SUPPRESS_SUMMARY.set(bool(suppress_summary))
    spinner_token = _BENCHMARK_SUPPRESS_SPINNER.set(bool(suppress_spinner))
    dashboard_refresh_token = _BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.set(
        bool(suppress_dashboard_refresh)
    )
    output_prune_token = _BENCHMARK_SUPPRESS_OUTPUT_PRUNE.set(
        bool(suppress_output_prune)
    )
    live_slots_token = _BENCHMARK_LIVE_STATUS_SLOTS.set(
        _normalize_live_status_slots(live_status_slots)
        if live_status_slots is not None
        else None
    )
    try:
        yield
    finally:
        _BENCHMARK_PROGRESS_CALLBACK.reset(progress_token)
        _BENCHMARK_SUPPRESS_SUMMARY.reset(summary_token)
        _BENCHMARK_SUPPRESS_SPINNER.reset(spinner_token)
        _BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.reset(dashboard_refresh_token)
        _BENCHMARK_SUPPRESS_OUTPUT_PRUNE.reset(output_prune_token)
        _BENCHMARK_LIVE_STATUS_SLOTS.reset(live_slots_token)

@contextmanager
def _benchmark_split_phase_overrides(
    *,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | None = None,
    split_phase_status_label: str | None = None,
) -> Iterable[None]:
    slots_token = _BENCHMARK_SPLIT_PHASE_SLOTS.set(split_phase_slots)
    gate_dir_token = _BENCHMARK_SPLIT_PHASE_GATE_DIR.set(
        str(split_phase_gate_dir) if split_phase_gate_dir is not None else None
    )
    label_token = _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.set(
        str(split_phase_status_label or "").strip() or None
    )
    try:
        yield
    finally:
        _BENCHMARK_SPLIT_PHASE_SLOTS.reset(slots_token)
        _BENCHMARK_SPLIT_PHASE_GATE_DIR.reset(gate_dir_token)
        _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.reset(label_token)

@contextmanager
def _benchmark_scheduler_event_overrides(
    *,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Iterable[None]:
    callback_token = _BENCHMARK_SCHEDULER_EVENT_CALLBACK.set(
        scheduler_event_callback
    )
    try:
        yield
    finally:
        _BENCHMARK_SCHEDULER_EVENT_CALLBACK.reset(callback_token)

__all__ = ['_extract_progress_counter', '_extract_progress_stage_label', '_is_structured_progress_message', '_extract_active_tasks', '_extract_running_workers', '_humanize_codex_pipeline_stage_label', '_summarize_codex_progress_message', '_format_seconds_per_task', '_looks_like_all_method_dashboard_snapshot', '_extract_all_method_dashboard_metrics', '_recent_rate_average_seconds_per_task', '_parallel_bootstrap_eta_seconds', '_format_status_progress_message', '_read_status_env_flag', '_plain_progress_override_requested', '_is_agent_execution_environment', '_should_default_plain_progress_for_agent', '_enforce_live_labelstudio_benchmark_codex_guardrails', '_enforce_live_bench_speed_codex_guardrails', '_normalize_live_status_slots', '_read_live_status_slots_from_env', '_effective_live_status_slots', '_acquire_live_status_slot', '_resolve_live_status_console', '_format_processing_time', '_read_linux_cpu_totals', '_processing_timeseries_history_path', '_append_processing_timeseries_marker', '_run_with_progress_status', '_benchmark_progress_overrides', '_benchmark_split_phase_overrides', '_benchmark_scheduler_event_overrides']
