from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_WORKER_PROGRESS_HEARTBEAT_SECONDS = 1.0
DEFAULT_WORKSPACE_WORKER_STALL_SECONDS = 45.0
DEFAULT_WORKSPACE_WORKER_ATTENTION_LIMIT = 2


@dataclass(frozen=True)
class WorkspaceWorkerHealthSnapshot:
    worker_id: str
    state: str
    reason_code: str | None
    warning_codes: tuple[str, ...]
    warning_count: int
    last_event_seconds_ago: float | None
    elapsed_seconds: float | None
    has_final_agent_message: bool
    live_activity_summary: str | None
    workspace_output_complete: bool | None
    workspace_output_missing_files: tuple[str, ...]
    attention_suffix: str | None
    attention_summary: str | None
    attention_rank: int
    stalled: bool
    last_activity_at: str | None


@dataclass(frozen=True)
class WorkspaceWorkerHealthSummary:
    snapshots_by_worker_id: dict[str, WorkspaceWorkerHealthSnapshot]
    attention_suffix_by_worker_id: dict[str, str]
    live_activity_summary_by_worker_id: dict[str, str]
    warning_worker_count: int
    stalled_worker_count: int
    attention_lines: tuple[str, ...]
    last_activity_at: str | None


def _load_live_status(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return 0.0
    return parsed


def _clean_warning_codes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    cleaned = [
        str(code).strip()
        for code in value
        if str(code).strip()
    ]
    return tuple(cleaned)


def _isoformat_utc_seconds(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def _classify_attention(
    *,
    worker_id: str,
    payload: Mapping[str, Any],
    stall_after_seconds: float,
) -> tuple[str | None, str | None, int, bool]:
    state = str(payload.get("state") or "").strip().lower()
    warning_codes = set(_clean_warning_codes(payload.get("warning_codes")))
    reason_code = str(payload.get("reason_code") or "").strip().lower()
    last_event_seconds_ago = _safe_float(payload.get("last_event_seconds_ago"))
    final_message_missing_output_deadline_reached = bool(
        payload.get("final_message_missing_output_deadline_reached")
    )

    if (
        reason_code == "workspace_final_message_missing_output"
        or final_message_missing_output_deadline_reached
    ):
        return (
            "final message, no output",
            f"{worker_id} final message without output",
            0,
            True,
        )
    if reason_code == "boundary_command_execution_forbidden":
        return ("boundary violation", f"{worker_id} boundary violation", 1, True)
    if "command_loop_without_output" in warning_codes:
        return (
            "command loop",
            f"{worker_id} command loop without output",
            2,
            True,
        )
    if "reasoning_without_output" in warning_codes:
        return ("reasoning only", f"{worker_id} reasoning without output", 3, True)
    if "cohort_runtime_outlier" in warning_codes:
        return ("runtime outlier", f"{worker_id} runtime outlier", 4, True)
    if "inline_python_heredoc_used" in warning_codes:
        return ("inline python", f"{worker_id} used inline python", 5, True)
    if "single_file_shell_drift" in warning_codes:
        return ("shell drift", f"{worker_id} single-file shell drift", 6, True)
    if (
        state.startswith("running")
        and last_event_seconds_ago is not None
        and last_event_seconds_ago >= max(1.0, float(stall_after_seconds))
    ):
        quiet_seconds = int(round(last_event_seconds_ago))
        return (
            f"quiet {quiet_seconds}s",
            f"{worker_id} quiet for {quiet_seconds}s",
            7,
            True,
        )
    if warning_codes:
        return ("watchdog warning", f"{worker_id} watchdog warning", 8, False)
    if state == "running_with_warnings":
        return ("watchdog warning", f"{worker_id} watchdog warning", 9, False)
    return None, None, 99, False


def summarize_taskfile_health(
    *,
    worker_roots_by_id: Mapping[str, Path],
    stall_after_seconds: float = DEFAULT_WORKSPACE_WORKER_STALL_SECONDS,
    attention_limit: int = DEFAULT_WORKSPACE_WORKER_ATTENTION_LIMIT,
) -> WorkspaceWorkerHealthSummary:
    now = datetime.now(timezone.utc)
    snapshots_by_worker_id: dict[str, WorkspaceWorkerHealthSnapshot] = {}
    attention_suffix_by_worker_id: dict[str, str] = {}
    live_activity_summary_by_worker_id: dict[str, str] = {}
    warning_worker_count = 0
    stalled_worker_count = 0
    last_activity_candidates: list[datetime] = []
    attention_rows: list[tuple[int, str, str]] = []

    for worker_id, worker_root in worker_roots_by_id.items():
        live_status = _load_live_status(Path(worker_root) / "live_status.json")
        if not live_status:
            continue
        warning_codes = _clean_warning_codes(live_status.get("warning_codes"))
        warning_count = int(live_status.get("warning_count") or len(warning_codes) or 0)
        last_event_seconds_ago = _safe_float(live_status.get("last_event_seconds_ago"))
        elapsed_seconds = _safe_float(live_status.get("elapsed_seconds"))
        live_activity_summary = str(live_status.get("live_activity_summary") or "").strip() or None
        last_activity_at: str | None = None
        if last_event_seconds_ago is not None:
            last_activity_at = _isoformat_utc_seconds(
                now - timedelta(seconds=last_event_seconds_ago)
            )
            last_activity_candidates.append(
                now - timedelta(seconds=last_event_seconds_ago)
            )
        attention_suffix, attention_summary, attention_rank, stalled = _classify_attention(
            worker_id=worker_id,
            payload=live_status,
            stall_after_seconds=stall_after_seconds,
        )
        if attention_suffix:
            attention_suffix_by_worker_id[worker_id] = attention_suffix
        if live_activity_summary:
            live_activity_summary_by_worker_id[worker_id] = live_activity_summary
        if attention_summary:
            attention_rows.append((attention_rank, worker_id, attention_summary))
        if warning_count > 0:
            warning_worker_count += 1
        if stalled:
            stalled_worker_count += 1
        snapshot = WorkspaceWorkerHealthSnapshot(
            worker_id=worker_id,
            state=str(live_status.get("state") or "").strip(),
            reason_code=str(live_status.get("reason_code") or "").strip() or None,
            warning_codes=warning_codes,
            warning_count=warning_count,
            last_event_seconds_ago=last_event_seconds_ago,
            elapsed_seconds=elapsed_seconds,
            has_final_agent_message=bool(live_status.get("has_final_agent_message")),
            live_activity_summary=live_activity_summary,
            workspace_output_complete=(
                bool(live_status.get("workspace_output_complete"))
                if live_status.get("workspace_output_complete") is not None
                else None
            ),
            workspace_output_missing_files=tuple(
                str(value).strip()
                for value in (live_status.get("workspace_output_missing_files") or [])
                if str(value).strip()
            ),
            attention_suffix=attention_suffix,
            attention_summary=attention_summary,
            attention_rank=attention_rank,
            stalled=stalled,
            last_activity_at=last_activity_at,
        )
        snapshots_by_worker_id[worker_id] = snapshot

    attention_lines = tuple(
        row[2]
        for row in sorted(attention_rows)[: max(0, int(attention_limit))]
    )
    latest_last_activity_at = (
        _isoformat_utc_seconds(max(last_activity_candidates))
        if last_activity_candidates
        else None
    )
    return WorkspaceWorkerHealthSummary(
        snapshots_by_worker_id=snapshots_by_worker_id,
        attention_suffix_by_worker_id=attention_suffix_by_worker_id,
        live_activity_summary_by_worker_id=live_activity_summary_by_worker_id,
        warning_worker_count=warning_worker_count,
        stalled_worker_count=stalled_worker_count,
        attention_lines=attention_lines,
        last_activity_at=latest_last_activity_at,
    )


def decorate_active_worker_label(
    label: str | None,
    activity_summary: str | None,
    suffix: str | None,
) -> str | None:
    cleaned_label = str(label or "").strip()
    cleaned_activity_summary = str(activity_summary or "").strip()
    cleaned_suffix = str(suffix or "").strip()
    if not cleaned_label:
        return None
    if cleaned_activity_summary:
        cleaned_label = f"{cleaned_label} | {cleaned_activity_summary}"
    if not cleaned_suffix:
        return cleaned_label
    return f"{cleaned_label} [{cleaned_suffix}]"


def start_taskfile_progress_heartbeat(
    *,
    emit_progress: Callable[[], None],
    thread_name: str,
    interval_seconds: float = DEFAULT_WORKSPACE_WORKER_PROGRESS_HEARTBEAT_SECONDS,
) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    safe_interval = max(0.2, float(interval_seconds))

    def _loop() -> None:
        while not stop_event.wait(safe_interval):
            try:
                emit_progress()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Ignoring taskfile worker progress heartbeat failure in %s: %s",
                    thread_name,
                    exc,
                )

    thread = threading.Thread(
        target=_loop,
        name=thread_name,
        daemon=True,
    )
    thread.start()
    return stop_event, thread
