"""Shared helpers for formatting status/progress counter messages."""

from __future__ import annotations

import json
from typing import Any


_WORKER_ACTIVITY_PREFIX = "__worker_activity__ "
_STAGE_PROGRESS_PREFIX = "__stage_progress__ "


def _normalize_counter(current: int, total: int) -> tuple[int, int]:
    safe_total = max(0, int(total))
    if safe_total <= 0:
        return 0, 0
    safe_current = max(0, min(int(current), safe_total))
    return safe_current, safe_total


def _normalize_nonnegative_count(value: int) -> int:
    return max(0, int(value))


def _clean_string_list(values: list[Any]) -> list[str]:
    return [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]


def _clean_count_mapping(values: dict[str, Any]) -> dict[str, int]:
    cleaned: dict[str, int] = {}
    for key, value in values.items():
        cleaned_key = str(key).strip()
        if not cleaned_key:
            continue
        try:
            cleaned[cleaned_key] = _normalize_nonnegative_count(int(value))
        except (TypeError, ValueError):
            continue
    return cleaned


def format_task_counter(
    prefix: str,
    current: int,
    total: int,
    *,
    noun: str = "task",
) -> str:
    """Render '<prefix> <noun> X/Y' with clamped counter values."""
    safe_current, safe_total = _normalize_counter(current, total)
    message_prefix = prefix.strip()
    label = noun.strip() or "task"
    if message_prefix:
        return f"{message_prefix} {label} {safe_current}/{safe_total}"
    return f"{label} {safe_current}/{safe_total}"


def format_phase_counter(
    prefix: str,
    current: int,
    total: int,
    *,
    label: str | None = None,
) -> str:
    """Render '<prefix> phase X/Y' with an optional phase label suffix."""
    safe_current, safe_total = _normalize_counter(current, total)
    phase = f"phase {safe_current}/{safe_total}"
    message_prefix = prefix.strip()
    message = f"{message_prefix} {phase}".strip() if message_prefix else phase
    label_text = (label or "").strip()
    if label_text:
        return f"{message}: {label_text}"
    return message


def format_worker_activity(
    worker_index: int,
    worker_total: int,
    status: str,
) -> str:
    """Serialize per-worker runtime activity for spinner-side rendering."""
    safe_total = max(1, int(worker_total))
    safe_index = max(1, min(int(worker_index), safe_total))
    payload = {
        "type": "activity",
        "worker_index": safe_index,
        "worker_total": safe_total,
        "status": str(status).strip(),
    }
    return f"{_WORKER_ACTIVITY_PREFIX}{json.dumps(payload, sort_keys=True, ensure_ascii=True)}"


def format_worker_activity_reset() -> str:
    """Clear spinner-side worker activity summary state."""
    payload = {"type": "reset"}
    return f"{_WORKER_ACTIVITY_PREFIX}{json.dumps(payload, sort_keys=True, ensure_ascii=True)}"


def format_stage_progress(
    message: str,
    *,
    stage_label: str | None = None,
    work_unit_label: str | None = None,
    task_current: int | None = None,
    task_total: int | None = None,
    running_workers: int | None = None,
    worker_total: int | None = None,
    worker_running: int | None = None,
    worker_completed: int | None = None,
    worker_failed: int | None = None,
    followup_running: int | None = None,
    followup_completed: int | None = None,
    followup_total: int | None = None,
    followup_label: str | None = None,
    artifact_counts: dict[str, Any] | None = None,
    last_activity_at: str | None = None,
    active_tasks: list[str] | None = None,
    detail_lines: list[str] | None = None,
) -> str:
    """Serialize a structured stage-progress snapshot for shared status renderers."""
    cleaned_message = str(message or "").strip()
    payload: dict[str, Any] = {
        "type": "stage_progress",
        "message": cleaned_message,
    }
    cleaned_stage_label = str(stage_label or "").strip()
    if cleaned_stage_label:
        payload["stage_label"] = cleaned_stage_label
    cleaned_work_unit_label = str(work_unit_label or "").strip()
    if cleaned_work_unit_label:
        payload["work_unit_label"] = cleaned_work_unit_label
    if task_current is not None and task_total is not None:
        safe_current, safe_total = _normalize_counter(task_current, task_total)
        payload["task_current"] = safe_current
        payload["task_total"] = safe_total
    if running_workers is not None:
        payload["running_workers"] = _normalize_nonnegative_count(running_workers)
    if worker_total is not None:
        payload["worker_total"] = _normalize_nonnegative_count(worker_total)
    if worker_running is not None:
        payload["worker_running"] = _normalize_nonnegative_count(worker_running)
    if worker_completed is not None:
        payload["worker_completed"] = _normalize_nonnegative_count(worker_completed)
    if worker_failed is not None:
        payload["worker_failed"] = _normalize_nonnegative_count(worker_failed)
    if followup_running is not None:
        payload["followup_running"] = _normalize_nonnegative_count(followup_running)
    if followup_completed is not None:
        payload["followup_completed"] = _normalize_nonnegative_count(followup_completed)
    if followup_total is not None:
        payload["followup_total"] = _normalize_nonnegative_count(followup_total)
    cleaned_followup_label = str(followup_label or "").strip()
    if cleaned_followup_label:
        payload["followup_label"] = cleaned_followup_label
    if artifact_counts is not None:
        cleaned_artifact_counts = _clean_count_mapping(artifact_counts)
        if cleaned_artifact_counts:
            payload["artifact_counts"] = cleaned_artifact_counts
    cleaned_last_activity_at = str(last_activity_at or "").strip()
    if cleaned_last_activity_at:
        payload["last_activity_at"] = cleaned_last_activity_at
    if active_tasks is not None:
        payload["active_tasks"] = _clean_string_list(active_tasks)
    if detail_lines is not None:
        payload["detail_lines"] = _clean_string_list(detail_lines)
    return f"{_STAGE_PROGRESS_PREFIX}{json.dumps(payload, sort_keys=True, ensure_ascii=True)}"


def format_stage_counter_progress(
    prefix: str,
    current: int,
    total: int,
    *,
    noun: str = "task",
    stage_label: str | None = None,
    running_workers: int | None = None,
    worker_total: int | None = None,
    active_tasks: list[str] | None = None,
    detail_lines: list[str] | None = None,
) -> str:
    """Serialize a task-counter status line plus optional structured stage metadata."""
    return format_stage_progress(
        format_task_counter(prefix, current, total, noun=noun),
        stage_label=stage_label,
        task_current=current,
        task_total=total,
        running_workers=running_workers,
        worker_total=worker_total,
        active_tasks=active_tasks,
        detail_lines=detail_lines,
    )


def parse_worker_activity(message: str) -> dict[str, Any] | None:
    """Parse serialized worker activity payloads from progress callbacks."""
    trimmed = message.strip()
    if not trimmed.startswith(_WORKER_ACTIVITY_PREFIX):
        return None
    raw_payload = trimmed[len(_WORKER_ACTIVITY_PREFIX) :].strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload_type = str(payload.get("type") or "").strip().lower()
    if payload_type == "reset":
        return {"type": "reset"}
    if payload_type != "activity":
        return None
    try:
        worker_total = max(1, int(payload.get("worker_total")))
        worker_index = int(payload.get("worker_index"))
    except (TypeError, ValueError):
        return None
    if worker_index < 1:
        return None
    worker_index = min(worker_index, worker_total)
    status = str(payload.get("status") or "").strip()
    return {
        "type": "activity",
        "worker_index": worker_index,
        "worker_total": worker_total,
        "status": status,
    }


def parse_stage_progress(message: str) -> dict[str, Any] | None:
    """Parse serialized stage-progress payloads from progress callbacks."""
    trimmed = message.strip()
    if not trimmed.startswith(_STAGE_PROGRESS_PREFIX):
        return None
    raw_payload = trimmed[len(_STAGE_PROGRESS_PREFIX) :].strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload_type = str(payload.get("type") or "").strip().lower()
    if payload_type != "stage_progress":
        return None

    message_text = str(payload.get("message") or "").strip()
    stage_label = str(payload.get("stage_label") or "").strip()
    work_unit_label = str(payload.get("work_unit_label") or "").strip() or None

    task_current: int | None = None
    task_total: int | None = None
    if payload.get("task_current") is not None or payload.get("task_total") is not None:
        try:
            normalized = _normalize_counter(
                int(payload.get("task_current")),
                int(payload.get("task_total")),
            )
        except (TypeError, ValueError):
            return None
        task_current, task_total = normalized

    running_workers: int | None = None
    if payload.get("running_workers") is not None:
        try:
            running_workers = _normalize_nonnegative_count(int(payload.get("running_workers")))
        except (TypeError, ValueError):
            return None

    worker_total: int | None = None
    if payload.get("worker_total") is not None:
        try:
            worker_total = _normalize_nonnegative_count(int(payload.get("worker_total")))
        except (TypeError, ValueError):
            return None

    worker_running: int | None = None
    if payload.get("worker_running") is not None:
        try:
            worker_running = _normalize_nonnegative_count(int(payload.get("worker_running")))
        except (TypeError, ValueError):
            return None

    worker_completed: int | None = None
    if payload.get("worker_completed") is not None:
        try:
            worker_completed = _normalize_nonnegative_count(int(payload.get("worker_completed")))
        except (TypeError, ValueError):
            return None

    worker_failed: int | None = None
    if payload.get("worker_failed") is not None:
        try:
            worker_failed = _normalize_nonnegative_count(int(payload.get("worker_failed")))
        except (TypeError, ValueError):
            return None

    followup_running: int | None = None
    if payload.get("followup_running") is not None:
        try:
            followup_running = _normalize_nonnegative_count(int(payload.get("followup_running")))
        except (TypeError, ValueError):
            return None

    followup_completed: int | None = None
    if payload.get("followup_completed") is not None:
        try:
            followup_completed = _normalize_nonnegative_count(int(payload.get("followup_completed")))
        except (TypeError, ValueError):
            return None

    followup_total: int | None = None
    if payload.get("followup_total") is not None:
        try:
            followup_total = _normalize_nonnegative_count(int(payload.get("followup_total")))
        except (TypeError, ValueError):
            return None

    followup_label = str(payload.get("followup_label") or "").strip() or None

    artifact_counts_raw = payload.get("artifact_counts")
    artifact_counts: dict[str, int] | None = None
    if artifact_counts_raw is not None:
        if not isinstance(artifact_counts_raw, dict):
            return None
        artifact_counts = {}
        for key, value in artifact_counts_raw.items():
            cleaned_key = str(key).strip()
            if not cleaned_key:
                continue
            try:
                artifact_counts[cleaned_key] = _normalize_nonnegative_count(int(value))
            except (TypeError, ValueError):
                return None

    last_activity_at = str(payload.get("last_activity_at") or "").strip() or None

    active_tasks_raw = payload.get("active_tasks")
    active_tasks: list[str] | None = None
    if active_tasks_raw is not None:
        if not isinstance(active_tasks_raw, list):
            return None
        active_tasks = _clean_string_list(active_tasks_raw)

    detail_lines_raw = payload.get("detail_lines")
    detail_lines: list[str] | None = None
    if detail_lines_raw is not None:
        if not isinstance(detail_lines_raw, list):
            return None
        detail_lines = _clean_string_list(detail_lines_raw)

    return {
        "type": "stage_progress",
        "message": message_text,
        "stage_label": stage_label,
        "work_unit_label": work_unit_label,
        "task_current": task_current,
        "task_total": task_total,
        "running_workers": running_workers,
        "worker_total": worker_total,
        "worker_running": worker_running,
        "worker_completed": worker_completed,
        "worker_failed": worker_failed,
        "followup_running": followup_running,
        "followup_completed": followup_completed,
        "followup_total": followup_total,
        "followup_label": followup_label,
        "artifact_counts": artifact_counts,
        "last_activity_at": last_activity_at,
        "active_tasks": active_tasks,
        "detail_lines": detail_lines,
    }
