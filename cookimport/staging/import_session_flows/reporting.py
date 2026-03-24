from __future__ import annotations

from typing import Callable

from cookimport.core.progress_messages import (
    format_stage_counter_progress,
    format_stage_progress,
)


def _notify_stage_progress(
    progress_callback: Callable[[str], None] | None,
    *,
    message: str,
    stage_label: str,
    task_current: int | None = None,
    task_total: int | None = None,
    detail_lines: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    if task_current is not None and task_total is not None:
        progress_callback(
            format_stage_counter_progress(
                message,
                task_current,
                task_total,
                stage_label=stage_label,
                detail_lines=detail_lines,
            )
        )
        return
    progress_callback(
        format_stage_progress(
            message,
            stage_label=stage_label,
            detail_lines=detail_lines,
        )
    )
