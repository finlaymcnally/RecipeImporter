from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Mapping, Sequence

import tiktoken

TASK_FILE_GUARDRAIL_SUMMARY_SCHEMA_VERSION = "task_file_guardrails.v1"
TASK_FILE_SIZE_WARNING_THRESHOLD_BYTES = 16 * 1024
TASK_FILE_SIZE_WARNING_THRESHOLD_ESTIMATED_TOKENS = 4096


def render_task_file_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"


@lru_cache(maxsize=1)
def _task_file_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def build_task_file_guardrail(
    *,
    payload: Mapping[str, Any],
    assignment_id: str | None = None,
    worker_id: str | None = None,
) -> dict[str, Any]:
    rendered = render_task_file_text(payload)
    estimated_tokens = len(_task_file_encoding().encode(rendered))
    warning_codes: list[str] = []
    if len(rendered.encode("utf-8")) >= TASK_FILE_SIZE_WARNING_THRESHOLD_BYTES:
        warning_codes.append("task_file_bytes_threshold_exceeded")
    if estimated_tokens >= TASK_FILE_SIZE_WARNING_THRESHOLD_ESTIMATED_TOKENS:
        warning_codes.append("task_file_token_threshold_exceeded")
    return {
        "schema_version": TASK_FILE_GUARDRAIL_SUMMARY_SCHEMA_VERSION,
        "assignment_id": str(assignment_id or "").strip() or None,
        "worker_id": str(worker_id or "").strip() or None,
        "task_file_name": "task.json",
        "task_file_bytes": len(rendered.encode("utf-8")),
        "task_file_chars": len(rendered),
        "task_file_lines": len(rendered.splitlines()),
        "task_file_estimated_tokens": estimated_tokens,
        "warning_threshold_bytes": TASK_FILE_SIZE_WARNING_THRESHOLD_BYTES,
        "warning_threshold_estimated_tokens": (
            TASK_FILE_SIZE_WARNING_THRESHOLD_ESTIMATED_TOKENS
        ),
        "warning_codes": warning_codes,
        "warning_count": len(warning_codes),
        "status": "warning" if warning_codes else "ok",
    }


def summarize_task_file_guardrails(
    guardrails: Sequence[Mapping[str, Any] | None],
) -> dict[str, Any]:
    assignment_rows = [
        dict(row)
        for row in guardrails
        if isinstance(row, Mapping)
    ]
    warning_rows = [
        row for row in assignment_rows if int(row.get("warning_count") or 0) > 0
    ]
    largest_assignment = None
    if assignment_rows:
        largest_assignment = max(
            assignment_rows,
            key=lambda row: (
                int(row.get("task_file_estimated_tokens") or 0),
                int(row.get("task_file_bytes") or 0),
            ),
        )
    return {
        "schema_version": TASK_FILE_GUARDRAIL_SUMMARY_SCHEMA_VERSION,
        "warning_threshold_bytes": TASK_FILE_SIZE_WARNING_THRESHOLD_BYTES,
        "warning_threshold_estimated_tokens": (
            TASK_FILE_SIZE_WARNING_THRESHOLD_ESTIMATED_TOKENS
        ),
        "assignment_count": len(assignment_rows),
        "warning_count": len(warning_rows),
        "max_task_file_bytes": max(
            (int(row.get("task_file_bytes") or 0) for row in assignment_rows),
            default=0,
        ),
        "max_task_file_chars": max(
            (int(row.get("task_file_chars") or 0) for row in assignment_rows),
            default=0,
        ),
        "max_task_file_estimated_tokens": max(
            (int(row.get("task_file_estimated_tokens") or 0) for row in assignment_rows),
            default=0,
        ),
        "largest_assignment": dict(largest_assignment) if largest_assignment else None,
        "warning_assignments": [dict(row) for row in warning_rows],
    }


def build_worker_session_guardrails(
    *,
    planned_happy_path_worker_cap: int,
    actual_happy_path_worker_sessions: int,
    repair_worker_session_count: int = 0,
    repair_followup_call_count: int = 0,
) -> dict[str, Any]:
    planned_cap = max(0, int(planned_happy_path_worker_cap or 0))
    actual_sessions = max(0, int(actual_happy_path_worker_sessions or 0))
    repair_sessions = max(0, int(repair_worker_session_count or 0))
    repair_calls = max(0, int(repair_followup_call_count or 0))
    cap_exceeded = actual_sessions > planned_cap
    return {
        "planned_happy_path_worker_cap": planned_cap,
        "actual_happy_path_worker_sessions": actual_sessions,
        "repair_worker_session_count": repair_sessions,
        "repair_followup_call_count": repair_calls,
        "total_worker_sessions_including_repair": actual_sessions + repair_sessions,
        "happy_path_within_cap": not cap_exceeded,
        "cap_exceeded": cap_exceeded,
        "status": "exceeded" if cap_exceeded else "within_cap",
    }

