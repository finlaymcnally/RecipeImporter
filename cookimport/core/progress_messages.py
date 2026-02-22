"""Shared helpers for formatting status/progress counter messages."""

from __future__ import annotations


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

