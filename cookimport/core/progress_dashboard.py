"""Shared, thread-safe progress dashboard state and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence
import threading

from cookimport.core.progress_messages import parse_worker_activity


def _normalize_count(value: int | float | str) -> int:
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, as_int)


@dataclass(frozen=True)
class ProgressQueueRow:
    marker: str
    name: str
    completed: int
    total: int
    ok: int
    fail: int

    def line(self) -> str:
        marker = str(self.marker or "").strip()
        if marker.startswith("..."):
            return f"{marker} {str(self.name).strip()}"
        return (
            f"{self.marker} {str(self.name).strip()} - "
            f"{max(0, int(self.completed))} of {max(0, int(self.total))} "
            f"(ok {max(0, int(self.ok))}, fail {max(0, int(self.fail))})"
        )


@dataclass(frozen=True)
class ProgressSnapshot:
    status_line: str
    overall_label: str
    overall_done: int
    overall_total: int
    current_label: str
    task_message: str
    extra_lines: list[str] = field(default_factory=list)
    queue_rows: list[ProgressQueueRow] = field(default_factory=list)
    worker_lines: list[str] = field(default_factory=list)


class ProgressDashboardCore:
    """Thread-safe rendering state for status dashboards."""

    def __init__(self, *, overall_label: str = "task") -> None:
        self._lock = threading.RLock()
        self._overall_label = str(overall_label or "task").strip() or "task"
        self._overall_done = 0
        self._overall_total = 0
        self._status_line: str | None = None
        self._current_label = ""
        self._task_message = ""
        self._extra_lines: list[str] = []
        self._queue_rows: list[ProgressQueueRow] = []
        self._worker_lines: list[str] = []

    def set_overall(self, done: int, total: int, *, label: str | None = None) -> None:
        with self._lock:
            self._overall_done = _normalize_count(done)
            self._overall_total = _normalize_count(total)
            if label is not None:
                self._overall_label = str(label or "").strip() or "task"

    def set_current(self, label: str) -> None:
        with self._lock:
            self._current_label = str(label or "").strip()

    def set_status_line(self, status_line: str | None) -> None:
        with self._lock:
            self._status_line = None if status_line is None else str(status_line)

    def set_task(self, message: str) -> None:
        with self._lock:
            self._task_message = str(message or "").strip().replace("\n", " ")

    def set_extra_lines(self, lines: Sequence[str]) -> None:
        with self._lock:
            normalized = [str(line).rstrip() for line in lines if str(line).strip()]
            self._extra_lines = normalized

    def set_queue_rows(self, rows: Sequence[ProgressQueueRow]) -> None:
        with self._lock:
            self._queue_rows = [row for row in rows if isinstance(row, ProgressQueueRow)]

    def set_worker_lines(self, lines: Sequence[str]) -> None:
        with self._lock:
            normalized = [str(line).rstrip() for line in lines if str(line).strip()]
            self._worker_lines = normalized

    def clear_workers(self) -> None:
        with self._lock:
            self._worker_lines = []

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            return ProgressSnapshot(
                status_line=self._status_line,
                overall_label=self._overall_label,
                overall_done=self._overall_done,
                overall_total=self._overall_total,
                current_label=self._current_line(),
                task_message=self._task_message,
                extra_lines=list(self._extra_lines),
                queue_rows=list(self._queue_rows),
                worker_lines=list(self._worker_lines),
            )

    def _current_line(self) -> str:
        return self._current_label.strip()

    def render(self) -> str:
        snapshot = self.snapshot()
        return _render_progress_snapshot(snapshot)


class ProgressCallbackAdapter:
    """Translate callback payloads into dashboard state updates."""

    def __init__(self, dashboard: ProgressDashboardCore) -> None:
        self.dashboard = dashboard
        self._worker_total = 0
        self._worker_status: dict[int, str] = {}

    def ingest_callback_message(self, message: str) -> bool:
        cleaned = str(message or "").strip()
        payload = parse_worker_activity(cleaned)
        if payload is None:
            previous = self.dashboard.snapshot().status_line
            next_status = cleaned
            if (previous or "").strip() != next_status:
                self.dashboard.set_status_line(next_status)
                return True
            return False

        payload_type = str(payload.get("type") or "").strip().lower()
        if payload_type == "reset":
            changed = bool(self._worker_status) or self._worker_total > 0
            self._worker_total = 0
            self._worker_status = {}
            self.dashboard.set_worker_lines([])
            return changed

        if payload_type != "activity":
            return False

        worker_total = _normalize_count(payload.get("worker_total", 0))
        worker_index = _normalize_count(payload.get("worker_index", 0))
        status = str(payload.get("status") or "").strip()

        if worker_total <= 0:
            worker_total = 1
        if worker_index <= 0:
            worker_index = 1
        if worker_index > worker_total:
            worker_index = worker_total

        had_previous = self._worker_total > 0 or bool(self._worker_status)
        if self._worker_total != worker_total:
            had_previous = True
            self._worker_total = worker_total
            self._worker_status = {
                index: value
                for index, value in self._worker_status.items()
                if 1 <= index <= worker_total
            }

        previous_status = (self._worker_status.get(worker_index) or "").strip()
        if previous_status != status:
            had_previous = True
            self._worker_status[worker_index] = status

        if not had_previous:
            self._worker_total = max(1, worker_total)

        worker_lines: list[str] = []
        for index in range(1, max(1, self._worker_total) + 1):
            worker_status = str(self._worker_status.get(index, "idle") or "idle").strip()
            if len(worker_status) > 120:
                worker_status = f"{worker_status[:117]}..."
            worker_lines.append(f"worker {index:02d}: {worker_status}")
        self.dashboard.set_worker_lines(worker_lines)
        return had_previous

    def snapshot_workers(self) -> tuple[int, dict[int, str]]:
        return self._worker_total, dict(self._worker_status)

    def snapshot_text(self) -> str:
        return self.dashboard.render()


def _render_progress_snapshot(snapshot: ProgressSnapshot) -> str:
    lines: list[str] = []

    status_line = snapshot.status_line
    if status_line is None:
        status_line = (
            f"overall {snapshot.overall_label} "
            f"{snapshot.overall_done}/{snapshot.overall_total}"
        )
    if status_line.strip():
        lines.append(status_line.strip())

    current_label = snapshot.current_label.strip()
    if current_label:
        lines.append(f"current: {current_label}")

    if snapshot.extra_lines:
        lines.extend(snapshot.extra_lines)

    if snapshot.queue_rows:
        lines.append("queue:")
        for row in snapshot.queue_rows:
            lines.append(f"  {row.line()}")

    if snapshot.task_message.strip():
        lines.append(f"task: {snapshot.task_message}")

    if snapshot.worker_lines:
        lines.extend(snapshot.worker_lines)

    return "\n".join(lines)
