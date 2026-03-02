from __future__ import annotations

from cookimport.core.progress_dashboard import (
    ProgressCallbackAdapter,
    ProgressDashboardCore,
    ProgressQueueRow,
)
from cookimport.core.progress_messages import (
    format_worker_activity,
    format_worker_activity_reset,
)


def test_progress_dashboard_core_renders_expected_snapshot() -> None:
    dashboard = ProgressDashboardCore(overall_label="jobs")
    dashboard.set_overall(1, 3, label="jobs")
    dashboard.set_status_line(
        "overall jobs 1/3 | imported 0 | "
        "active_workers 0 | pending 2 | errors 0"
    )
    dashboard.set_current("split_text.txt")
    dashboard.set_task("stage task 1/3")
    dashboard.set_queue_rows(
        [
            ProgressQueueRow(
                marker="[>]",
                name="simple_text.txt",
                completed=1,
                total=1,
                ok=1,
                fail=0,
            )
        ]
    )
    dashboard.set_worker_lines(["worker 01: parsing"])

    assert dashboard.render() == (
        "overall jobs 1/3 | imported 0 | active_workers 0 | pending 2 | errors 0\n"
        "current: split_text.txt\n"
        "queue:\n"
        "  [>] simple_text.txt - 1 of 1 (ok 1, fail 0)\n"
        "task: stage task 1/3\n"
        "worker 01: parsing"
    )


def test_progress_callback_adapter_updates_status_and_workers() -> None:
    dashboard = ProgressDashboardCore(overall_label="task")
    adapter = ProgressCallbackAdapter(dashboard)

    changed = adapter.ingest_callback_message("stage running")
    assert changed is True
    assert adapter.snapshot_text() == "stage running"
    assert adapter.snapshot_workers() == (0, {})

    changed = adapter.ingest_callback_message("stage running")
    assert changed is False
    assert adapter.snapshot_text() == "stage running"

    dashboard.set_status_line(
        "overall jobs 0/1 | imported 0 | "
        "active_workers 1 | pending 1 | errors 0"
    )
    adapter.ingest_callback_message(format_worker_activity(1, 1, "Running job"))
    assert adapter.snapshot_text().splitlines() == [
        "overall jobs 0/1 | imported 0 | active_workers 1 | pending 1 | errors 0",
        "worker 01: Running job",
    ]
    assert adapter.snapshot_workers() == (1, {1: "Running job"})


def test_progress_callback_adapter_reset_clears_workers_only() -> None:
    dashboard = ProgressDashboardCore(overall_label="task")
    adapter = ProgressCallbackAdapter(dashboard)
    dashboard.set_status_line(
        "overall jobs 1/1 | imported 1 | "
        "active_workers 1 | pending 0 | errors 0"
    )
    adapter.ingest_callback_message(format_worker_activity(1, 2, "Running"))
    adapter.ingest_callback_message(format_worker_activity(2, 2, "Running"))

    assert adapter.snapshot_text().splitlines() == [
        "overall jobs 1/1 | imported 1 | active_workers 1 | pending 0 | errors 0",
        "worker 01: Running",
        "worker 02: Running",
    ]
    assert adapter.snapshot_workers() == (2, {1: "Running", 2: "Running"})

    changed = adapter.ingest_callback_message(format_worker_activity_reset())
    assert changed is True
    assert (
        adapter.snapshot_text()
        == "overall jobs 1/1 | imported 1 | "
        "active_workers 1 | pending 0 | errors 0"
    )
    assert adapter.snapshot_workers() == (0, {})
