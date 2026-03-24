from __future__ import annotations

from cookimport.staging.import_session import *  # noqa: F401,F403
from cookimport.staging import import_session as _import_session

globals().update(
    {
        name: getattr(_import_session, name)
        for name in dir(_import_session)
        if not name.startswith("__")
    }
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
