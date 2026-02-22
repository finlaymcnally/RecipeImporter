from __future__ import annotations

from cookimport.core.progress_messages import format_phase_counter, format_task_counter


def test_format_task_counter_clamps_current_and_total() -> None:
    assert format_task_counter("Running", -3, 5) == "Running task 0/5"
    assert format_task_counter("Running", 12, 5, noun="item") == "Running item 5/5"
    assert format_task_counter("Running", 1, 0) == "Running task 0/0"


def test_format_phase_counter_adds_optional_label() -> None:
    assert (
        format_phase_counter("merge", 2, 9, label="Writing tips...")
        == "merge phase 2/9: Writing tips..."
    )
    assert format_phase_counter("", 1, 3) == "phase 1/3"
