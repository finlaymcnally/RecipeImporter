"""Shared helpers for formatting status/progress counter messages."""

from __future__ import annotations

import json
from typing import Any


_WORKER_ACTIVITY_PREFIX = "__worker_activity__ "


def _normalize_counter(current: int, total: int) -> tuple[int, int]:
    safe_total = max(0, int(total))
    if safe_total <= 0:
        return 0, 0
    safe_current = max(0, min(int(current), safe_total))
    return safe_current, safe_total


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
