from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_farm_knowledge_ingest import (
    classify_knowledge_validation_failure,
    normalize_knowledge_worker_payload,
    validate_knowledge_shard_output,
)
from .codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REASON_CODES,
    ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES,
)
from .phase_worker_runtime import ShardManifestEntryV1

_WORKER_SCRIPT_NAME = "knowledge_worker.py"
_DEFAULT_SCAFFOLD_REASON_CODE = "review_not_completed"
_STRONG_CUE_SCAFFOLD_REASON_CODE = "strong_cue_review_required"
_CURRENT_BATCH_FILE_NAME = "current_batch.json"
_CURRENT_BATCH_BRIEF_FILE_NAME = "CURRENT_BATCH.md"
_CURRENT_BATCH_FEEDBACK_FILE_NAME = "CURRENT_BATCH_FEEDBACK.md"
_CURRENT_TASK_BRIEF_FILE_NAME = "CURRENT_TASK.md"
_CURRENT_TASK_FEEDBACK_FILE_NAME = "CURRENT_TASK_FEEDBACK.md"
_KNOWLEDGE_MICRO_BATCH_MAX_TASKS = 8
_KNOWLEDGE_MICRO_BATCH_MAX_INPUT_BYTES = 48_000
_NO_CURRENT_BATCH_ACTIVE_TEXT = "No current batch is active. The queue is complete."
_NO_CURRENT_TASK_ACTIVE_TEXT = "No current task is active. The queue is complete."
_ACTIVE_BATCH_ASSIGNMENT_TEXT = (
    "This worker assignment is still active until the repo removes `current_batch.json` "
    "and says the queue is complete."
)
_ACTIVE_ASSIGNMENT_TEXT = (
    "This worker assignment is still active until the repo removes `current_task.json` "
    "and says the queue is complete."
)
_CHECK_BATCH_AFTER_EDIT_TEXT = (
    "Run `python3 tools/knowledge_worker.py check-batch` after editing the current batch drafts."
)
_NO_REPO_WRITTEN_FEEDBACK_TEXT = "No repo-written validation feedback exists yet for this task."
_NO_REPO_WRITTEN_BATCH_FEEDBACK_TEXT = (
    "No repo-written validation feedback exists yet for this batch."
)
_CHECK_CURRENT_AFTER_EDIT_TEXT = (
    "Run `python3 tools/knowledge_worker.py debug check-current` after editing the current draft."
)
_BATCH_VALIDATION_STATUS_OK_TEXT = "Batch validation status: OK."
_VALIDATION_STATUS_OK_TEXT = "Validation status: OK."
_BATCH_VALIDATOR_ACCEPTED_TEXT = "The validator accepted every task in this batch."
_INSTALL_BATCH_READY_TEXT = (
    "You may run `python3 tools/knowledge_worker.py install-batch` to install the longest "
    "valid prefix of this batch."
)
_REOPEN_BATCH_AFTER_INSTALL_TEXT = (
    "After `install-batch`, re-open `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md`. "
    "Open `current_batch.json` only if you need the next batch's machine-readable paths or task rows."
)
_CONTINUE_BATCH_IMMEDIATELY_TEXT = (
    "If another batch becomes active, continue with it immediately. Do not ask for "
    "permission to continue or stop at this checkpoint while later tasks remain."
)
_VALIDATOR_ACCEPTED_TEXT = "The validator accepted this task."
_INSTALL_CURRENT_READY_TEXT = (
    "You may run `python3 tools/knowledge_worker.py debug install-current` to write the final result path."
)
_REOPEN_AFTER_INSTALL_TEXT = (
    "After `debug install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and "
    "`CURRENT_TASK_FEEDBACK.md`."
)
_CONTINUE_IMMEDIATELY_TEXT = (
    "If another task becomes active, continue with that task immediately. Do not ask for "
    "permission to continue or stop at this checkpoint while later tasks remain."
)
_QUEUE_COMPLETE_TEXT = "If not, the queue is complete."
_INSTALL_BATCH_SUCCESS_NOTICE = (
    "re-open `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md`; open `current_batch.json` "
    "only if you need the next batch's machine-readable paths or task rows; if another "
    "batch becomes active, continue with it immediately. Do not ask for permission to "
    "continue while later tasks remain."
)
_INSTALL_CURRENT_SUCCESS_NOTICE = (
    "re-open `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`; if "
    "another task becomes active, continue with that task immediately. Do not ask for "
    "permission to continue while later tasks remain."
)


@dataclass(frozen=True)
class KnowledgeWorkspaceCheckResult:
    task_id: str
    task_row: dict[str, Any]
    input_payload: dict[str, Any]
    draft_path: Path
    result_path: Path
    payload: dict[str, Any]
    valid: bool
    errors: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeWorkspaceBatchCheckResult:
    batch_payload: dict[str, Any]
    task_results: tuple[KnowledgeWorkspaceCheckResult, ...]
    missing_task_ids: tuple[str, ...]
    valid: bool

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(
            str(task.get("task_id") or "").strip()
            for task in (self.batch_payload.get("tasks") or [])
            if isinstance(task, Mapping) and str(task.get("task_id") or "").strip()
        )

    @property
    def first_invalid_result(self) -> KnowledgeWorkspaceCheckResult | None:
        for task_result in self.task_results:
            if not task_result.valid:
                return task_result
        return None


def build_workspace_inventory_task_row(
    task_row: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(task_row)
    metadata = dict(_coerce_dict(row.get("metadata")))
    task_id = str(row.get("task_id") or "").strip()
    parent_shard_id = str(row.get("parent_shard_id") or task_id).strip() or task_id
    owned_ids = [
        str(value).strip()
        for value in (row.get("owned_ids") or [])
        if str(value).strip()
    ]
    inventory_metadata = dict(metadata)
    inventory_metadata["owned_packet_count"] = len(owned_ids)
    return {
        "task_id": task_id,
        "task_kind": str(row.get("task_kind") or "").strip() or None,
        "parent_shard_id": parent_shard_id,
        "owned_ids": owned_ids,
        "metadata": inventory_metadata,
    }


def load_workspace_task_rows(*, workspace_root: Path) -> list[dict[str, Any]]:
    assigned_tasks_path = Path(workspace_root) / "assigned_tasks.json"
    if not assigned_tasks_path.exists():
        return []
    payload = _load_json(assigned_tasks_path)
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def load_current_task_row(*, workspace_root: Path) -> dict[str, Any] | None:
    current_task_path = Path(workspace_root) / "current_task.json"
    if not current_task_path.exists():
        return None
    payload = _load_json(current_task_path)
    return dict(payload) if isinstance(payload, Mapping) else None


def load_current_batch_payload(*, workspace_root: Path) -> dict[str, Any] | None:
    current_batch_path = Path(workspace_root) / _CURRENT_BATCH_FILE_NAME
    if not current_batch_path.exists():
        return None
    payload = _load_json(current_batch_path)
    return dict(payload) if isinstance(payload, Mapping) else None


def current_batch_draft_dir(*, workspace_root: Path) -> Path:
    return Path(workspace_root) / "scratch" / "current_batch"


def current_batch_task_draft_path(*, workspace_root: Path, task_id: str) -> Path:
    cleaned_task_id = str(task_id or "").strip()
    if not cleaned_task_id:
        raise ValueError("task_id is required for a batch draft path")
    return current_batch_draft_dir(workspace_root=workspace_root) / f"{cleaned_task_id}.json"


def _task_block_spans(*, input_payload: Mapping[str, Any]) -> list[str]:
    block_spans: list[str] = []
    for packet in _packet_rows(input_payload):
        packet_id = str(packet.get("bid") or "").strip() or "[unknown packet]"
        block_indices = [
            int(block.get("i"))
            for block in packet.get("b") or []
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        if not block_indices:
            block_spans.append(f"{packet_id}:[no blocks]")
            continue
        block_spans.append(f"{packet_id}:{block_indices[0]}..{block_indices[-1]}")
    return block_spans


def _task_input_bytes(*, workspace_root: Path, task_row: Mapping[str, Any]) -> int:
    metadata = _coerce_dict(task_row.get("metadata"))
    input_path = str(metadata.get("input_path") or "").strip()
    if not input_path:
        return 0
    resolved_path = Path(workspace_root) / input_path
    if resolved_path.exists():
        return resolved_path.stat().st_size
    try:
        payload = load_task_input_payload(workspace_root=workspace_root, task_row=task_row)
    except Exception:  # noqa: BLE001
        return 0
    return len(json.dumps(payload, sort_keys=True))


def build_current_batch_payload(
    *,
    workspace_root: Path,
    task_rows: Sequence[Mapping[str, Any]],
    current_index: int = 0,
) -> dict[str, Any] | None:
    rows = [dict(row) for row in task_rows if isinstance(row, Mapping)]
    if current_index < 0 or current_index >= len(rows):
        return None
    batch_rows: list[dict[str, Any]] = []
    total_input_bytes = 0
    for row in rows[current_index:]:
        row_input_bytes = _task_input_bytes(workspace_root=workspace_root, task_row=row)
        would_exceed_count = len(batch_rows) >= _KNOWLEDGE_MICRO_BATCH_MAX_TASKS
        would_exceed_bytes = (
            batch_rows
            and total_input_bytes + row_input_bytes > _KNOWLEDGE_MICRO_BATCH_MAX_INPUT_BYTES
        )
        if would_exceed_count or would_exceed_bytes:
            break
        batch_rows.append(row)
        total_input_bytes += row_input_bytes
    if not batch_rows:
        batch_rows.append(rows[current_index])
        total_input_bytes = _task_input_bytes(
            workspace_root=workspace_root,
            task_row=batch_rows[0],
        )
    total_task_count = len(rows)
    batch_tasks: list[dict[str, Any]] = []
    for offset, row in enumerate(batch_rows, start=1):
        metadata = _coerce_dict(row.get("metadata"))
        task_id = str(row.get("task_id") or "").strip() or "[unknown task]"
        batch_tasks.append(
            {
                "task_id": task_id,
                "queue_position": int(metadata.get("task_sequence") or current_index + offset),
                "task_total": int(metadata.get("task_total") or total_task_count),
                "input_path": str(metadata.get("input_path") or "").strip() or None,
                "hint_path": str(metadata.get("hint_path") or "").strip() or None,
                "result_path": str(metadata.get("result_path") or "").strip() or None,
                "draft_path": str(
                    _workspace_display_path(
                        workspace_root=workspace_root,
                        path=current_batch_task_draft_path(
                            workspace_root=workspace_root,
                            task_id=task_id,
                        ),
                    )
                ),
                "owned_packet_ids": [
                    str(value).strip()
                    for value in (row.get("owned_ids") or [])
                    if str(value).strip()
                ],
            }
        )
    batch_start_position = int(_coerce_dict(batch_rows[0].get("metadata")).get("task_sequence") or current_index + 1)
    batch_end_position = int(_coerce_dict(batch_rows[-1].get("metadata")).get("task_sequence") or current_index + len(batch_rows))
    return {
        "version": 1,
        "batch_contract": "knowledge_micro_batch_v1",
        "batch_task_count": len(batch_tasks),
        "batch_start_position": batch_start_position,
        "batch_end_position": batch_end_position,
        "task_total": total_task_count,
        "batch_remaining_after_batch": max(total_task_count - batch_end_position, 0),
        "draft_dir": str(
            _workspace_display_path(
                workspace_root=workspace_root,
                path=current_batch_draft_dir(workspace_root=workspace_root),
            )
        ),
        "tasks": batch_tasks,
    }


def _first_batch_task(
    batch_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(batch_payload, Mapping):
        return None
    for task in batch_payload.get("tasks") or []:
        if isinstance(task, Mapping):
            return dict(task)
    return None


def render_current_task_brief_text(
    *,
    workspace_root: Path,
    task_row: Mapping[str, Any] | None,
) -> str:
    if task_row is None:
        return (
            "# Current Knowledge Task\n\n"
            "No current task is active in this workspace.\n"
            "Every assigned task that the repo accepted has already been validated.\n"
        )
    row = dict(task_row)
    metadata = _coerce_dict(row.get("metadata"))
    task_id = str(row.get("task_id") or "").strip() or "[unknown task]"
    parent_shard_id = str(row.get("parent_shard_id") or task_id).strip() or task_id
    owned_ids = [
        str(value).strip()
        for value in (row.get("owned_ids") or [])
        if str(value).strip()
    ]
    input_payload = load_task_input_payload(workspace_root=workspace_root, task_row=row)
    block_spans: list[str] = []
    for packet in _packet_rows(input_payload):
        packet_id = str(packet.get("bid") or "").strip() or "[unknown packet]"
        block_indices = [
            int(block.get("i"))
            for block in packet.get("b") or []
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        if not block_indices:
            block_spans.append(f"{packet_id}:[no blocks]")
            continue
        block_spans.append(f"{packet_id}:{block_indices[0]}..{block_indices[-1]}")
    task_sequence = int(metadata.get("task_sequence") or 0)
    task_total = int(metadata.get("task_total") or 0)
    remaining_after_current = (
        max(task_total - task_sequence, 0)
        if task_sequence > 0 and task_total > 0
        else None
    )
    lines = [
        "# Current Knowledge Task",
        "",
        f"Task id: `{task_id}`",
        f"Parent shard: `{parent_shard_id}`",
        (
            f"Queue position: `{task_sequence}` of `{task_total}`"
            if task_sequence > 0 and task_total > 0
            else "Queue position: unknown"
        ),
        f"Owned packet ids: `{', '.join(owned_ids) or '[none]'}`",
        f"Input file: `{metadata.get('input_path') or '?'}`",
        f"Hint file: `{metadata.get('hint_path') or '?'}`",
        f"Result file: `{metadata.get('result_path') or '?'}`",
        f"Owned block spans: `{', '.join(block_spans) or '[none]'}`",
        (
            f"Remaining tasks after this one: `{remaining_after_current}`"
            if remaining_after_current is not None
            else "Remaining tasks after this one: unknown"
        ),
        "Return top-level `block_decisions` plus `idea_groups`; the worker contract is packet-based.",
        "Every kept `knowledge` block must appear in exactly one idea group.",
        "Keep snippets short and grounded. Evidence quotes stay verbatim; snippet bodies should not copy them.",
        "",
        "Keep only durable cooking leverage. Technically true but low-value prose should stay `other`.",
        "This assignment stays active until the repo removes `current_task.json` and rewrites the current-task sidecars to say the queue is complete.",
        "A successful `debug install-current` is only a handoff to the next repo-owned current task, not a stopping point.",
        "When `CURRENT_BATCH.md` / `current_batch.json` are present, treat the batch files as the normal path and use this single-task surface only for narrow recovery/debugging.",
        "",
        "Recommended loop:",
        "1. Read the hint and input files named above.",
        "2. Run `python3 tools/knowledge_worker.py debug complete-current` to write the default draft to `scratch/current_task.json`.",
        "3. Edit the draft until the snippet bodies are short grounded claims, not copied evidence surfaces.",
        "4. Run `python3 tools/knowledge_worker.py debug check-current`.",
        "5. Run `python3 tools/knowledge_worker.py debug install-current` only after `debug check-current` says OK.",
        "6. After `debug install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`. If another task becomes active, continue with that task immediately. Do not stop to summarize progress or ask for permission to continue while later tasks remain.",
        "",
        "Do not process later tasks before this task passes the repo-owned checker.",
    ]
    return "\n".join(lines) + "\n"


def render_current_batch_brief_text(
    *,
    batch_payload: Mapping[str, Any] | None,
) -> str:
    if batch_payload is None:
        return (
            "# Current Knowledge Batch\n\n"
            "No current batch is active in this workspace.\n"
            "Every assigned task that the repo accepted has already been validated.\n"
        )
    batch_tasks = [
        dict(task)
        for task in (batch_payload.get("tasks") or [])
        if isinstance(task, Mapping)
    ]
    batch_ids = [
        str(task.get("task_id") or "").strip()
        for task in batch_tasks
        if str(task.get("task_id") or "").strip()
    ]
    first_task = _first_batch_task(batch_payload)
    lines = [
        "# Current Knowledge Batch",
        "",
        (
            f"Batch queue span: `{batch_payload.get('batch_start_position')}` to "
            f"`{batch_payload.get('batch_end_position')}` of `{batch_payload.get('task_total')}`"
        ),
        f"Batch task ids: `{', '.join(batch_ids) or '[none]'}`",
        f"Batch task count: `{batch_payload.get('batch_task_count') or 0}`",
        f"Batch draft dir: `{batch_payload.get('draft_dir') or 'scratch/current_batch'}`",
        f"Remaining tasks after this batch: `{batch_payload.get('batch_remaining_after_batch') or 0}`",
        "",
        "Keep only durable cooking leverage. Technically true but low-value prose should stay `other`.",
        "This assignment stays active until the repo removes `current_batch.json` and rewrites the batch sidecars to say the queue is complete.",
        "A successful `install-batch` is only a handoff to the next repo-owned current batch, not a stopping point.",
        "",
        "Recommended loop:",
        "1. Read `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md` first. Open `current_batch.json` only when you need the next batch's machine-readable paths or task rows, and open the named hint/input files only when the batch summary is insufficient.",
        "2. Run `python3 tools/knowledge_worker.py complete-batch` to prewrite the default drafts under `scratch/current_batch/`.",
        "3. Edit the batch drafts until the snippet bodies are short grounded claims, not copied evidence surfaces.",
        "   If you automate, automate only the active batch drafts named in `current_batch.json` and `scratch/current_batch/`. Do not loop over `assigned_tasks.json`, `current_task.json`, or `out/`.",
        "4. Run `python3 tools/knowledge_worker.py check-batch`.",
        "5. Run `python3 tools/knowledge_worker.py install-batch` after the batch checker says OK, or to install the longest valid prefix if an already-edited later draft still needs repair.",
        "6. After `install-batch`, re-open `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md`. Open `current_batch.json` only when you need the next batch's machine-readable paths or task rows. If another batch becomes active, continue with it immediately. Do not stop to summarize progress or ask for permission to continue while later tasks remain.",
        "",
        "Single-task `CURRENT_TASK*` files and `python3 tools/knowledge_worker.py debug ...` recovery commands remain available only for narrow recovery/debugging on the first task in this batch.",
    ]
    if first_task is not None:
        lines.extend(
            [
                "",
                "First task to work now:",
                f"- Task id: `{first_task.get('task_id') or '[unknown task]'}`",
                (
                    f"- Queue position: `{first_task.get('queue_position')}` of "
                    f"`{first_task.get('task_total')}`"
                ),
                f"- Draft path: `{first_task.get('draft_path') or '?'}`",
                f"- Result path: `{first_task.get('result_path') or '?'}`",
                (
                    f"- Owned packet ids: `{', '.join(first_task.get('owned_packet_ids') or []) or '[none]'}`"
                ),
                "- Return `block_decisions` plus `idea_groups`; do not fall back to chunk-era result shapes.",
            ]
        )
    return "\n".join(lines) + "\n"


def _remaining_after_current_text(task_row: Mapping[str, Any]) -> str:
    metadata = _coerce_dict(task_row.get("metadata"))
    task_sequence = int(metadata.get("task_sequence") or 0)
    task_total = int(metadata.get("task_total") or 0)
    if task_sequence > 0 and task_total > 0:
        return f"Remaining tasks after this one: `{max(task_total - task_sequence, 0)}`."
    return "Remaining tasks after this one: unknown."


def _render_pending_current_task_feedback_lines(
    *,
    task_row: Mapping[str, Any],
    current_draft_path: Path | None = None,
) -> list[str]:
    task_id = str(task_row.get("task_id") or "").strip() or "[unknown task]"
    draft_note = (
        f"Expected draft path: `{current_draft_path}`."
        if current_draft_path is not None
        else "No draft path is configured."
    )
    return [
        "# Current Task Feedback",
        "",
        f"Task id: `{task_id}`",
        _NO_REPO_WRITTEN_FEEDBACK_TEXT,
        _remaining_after_current_text(task_row),
        _ACTIVE_ASSIGNMENT_TEXT,
        draft_note,
        _CHECK_CURRENT_AFTER_EDIT_TEXT,
    ]


def _render_valid_current_task_feedback_lines(
    *,
    task_row: Mapping[str, Any],
    draft_path: Path | str | None,
    result_path: Path | str | None,
) -> list[str]:
    task_id = str(task_row.get("task_id") or "").strip() or "[unknown task]"
    draft_display = f"{draft_path}" if draft_path else "unknown."
    result_display = f"{result_path}" if result_path else "unknown."
    return [
        "# Current Task Feedback",
        "",
        f"Task id: `{task_id}`",
        _VALIDATION_STATUS_OK_TEXT,
        f"Draft path: `{draft_display}`",
        f"Install target: `{result_display}`",
        _VALIDATOR_ACCEPTED_TEXT,
        _INSTALL_CURRENT_READY_TEXT,
        _REOPEN_AFTER_INSTALL_TEXT,
        _CONTINUE_IMMEDIATELY_TEXT,
        _QUEUE_COMPLETE_TEXT,
    ]


def render_current_task_feedback_text(
    *,
    task_row: Mapping[str, Any] | None,
    check_result: KnowledgeWorkspaceCheckResult | None = None,
    current_draft_path: Path | None = None,
) -> str:
    if task_row is None:
        return "# Current Task Feedback\n\n" + _NO_CURRENT_TASK_ACTIVE_TEXT + "\n"
    if check_result is None:
        return (
            "\n".join(
                _render_pending_current_task_feedback_lines(
                    task_row=task_row,
                    current_draft_path=current_draft_path,
                )
            )
            + "\n"
        )
    classification = _coerce_dict(check_result.metadata.get("failure_classification"))
    classification_code = str(classification.get("reason_code") or "").strip() or "validation_failed"
    classification_detail = str(classification.get("reason_detail") or "").strip()
    if check_result.valid:
        metadata_result_path = str(
            _coerce_dict(task_row.get("metadata")).get("result_path") or ""
        ).strip()
        return (
            "\n".join(
                _render_valid_current_task_feedback_lines(
                    task_row=task_row,
                    draft_path=(
                        current_draft_path
                        if current_draft_path is not None
                        else check_result.draft_path
                        if check_result.draft_path
                        else None
                    ),
                    result_path=metadata_result_path or check_result.result_path,
                )
            )
            + "\n"
        )
    task_id = str(task_row.get("task_id") or "").strip() or "[unknown task]"
    explanation_lines = _render_validation_error_help(
        validation_errors=check_result.errors,
        validation_metadata=check_result.metadata,
        input_payload=check_result.input_payload,
        payload=check_result.payload,
    )
    lines = [
        "# Current Task Feedback",
        "",
        f"Task id: `{task_id}`",
        "Validation status: FAILED.",
        f"Failure class: `{classification_code}`",
    ]
    if classification_detail:
        lines.append(classification_detail)
    lines.extend(
        [
            "",
            "Validator errors:",
            *[f"- `{error}`" for error in check_result.errors],
            "",
            "How to fix it:",
            *[f"- {line}" for line in explanation_lines],
        ]
    )
    return "\n".join(lines) + "\n"


def render_current_batch_feedback_text(
    *,
    batch_payload: Mapping[str, Any] | None,
    batch_check_result: KnowledgeWorkspaceBatchCheckResult | None = None,
) -> str:
    if batch_payload is None:
        return "# Current Batch Feedback\n\n" + _NO_CURRENT_BATCH_ACTIVE_TEXT + "\n"
    batch_tasks = [
        dict(task)
        for task in (batch_payload.get("tasks") or [])
        if isinstance(task, Mapping)
    ]
    batch_task_ids = [
        str(task.get("task_id") or "").strip()
        for task in batch_tasks
        if str(task.get("task_id") or "").strip()
    ]
    if batch_check_result is None:
        validated_before_batch = max(
            int(batch_payload.get("batch_start_position") or 1) - 1,
            0,
        )
        task_total = int(batch_payload.get("task_total") or len(batch_tasks))
        first_task = _first_batch_task(batch_payload)
        lines = [
            "# Current Batch Feedback",
            "",
            f"Batch task ids: `{', '.join(batch_task_ids) or '[none]'}`",
            _NO_REPO_WRITTEN_BATCH_FEEDBACK_TEXT,
            (
                "Assignment progress: "
                f"`{validated_before_batch}` of `{task_total}` validated; "
                f"`{max(task_total - validated_before_batch, 0)}` remain."
            ),
            _ACTIVE_BATCH_ASSIGNMENT_TEXT,
            "Every task still needs a packet-level judgment over `block_decisions` and `idea_groups` until the repo-owned checker accepts it.",
        ]
        if first_task is not None:
            lines.extend(
                [
                    "Current first task:",
                    f"- `{first_task.get('task_id') or '[unknown task]'}`",
                    f"- Draft: `{first_task.get('draft_path') or '?'}`",
                    f"- Hint: `{first_task.get('hint_path') or '?'}`",
                    f"- Input: `{first_task.get('input_path') or '?'}`",
                ]
            )
        lines.append(_CHECK_BATCH_AFTER_EDIT_TEXT)
        return "\n".join(lines) + "\n"
    if batch_check_result.valid:
        lines = [
            "# Current Batch Feedback",
            "",
            f"Batch task ids: `{', '.join(batch_task_ids) or '[none]'}`",
            _BATCH_VALIDATION_STATUS_OK_TEXT,
            _BATCH_VALIDATOR_ACCEPTED_TEXT,
            _INSTALL_BATCH_READY_TEXT,
            _REOPEN_BATCH_AFTER_INSTALL_TEXT,
            _CONTINUE_BATCH_IMMEDIATELY_TEXT,
            _QUEUE_COMPLETE_TEXT,
            "",
            "Validated draft files:",
        ]
        lines.extend(
            f"- `{task_result.task_id}` -> `{task_result.draft_path}`"
            for task_result in batch_check_result.task_results
        )
        return "\n".join(lines) + "\n"
    first_invalid_result = batch_check_result.first_invalid_result
    lines = [
        "# Current Batch Feedback",
        "",
        f"Batch task ids: `{', '.join(batch_task_ids) or '[none]'}`",
        "Batch validation status: FAILED.",
    ]
    if batch_check_result.missing_task_ids:
        lines.extend(
            [
                "",
                "Missing batch drafts:",
                *[f"- `{task_id}`" for task_id in batch_check_result.missing_task_ids],
            ]
        )
    if first_invalid_result is not None:
        task_row = next(
            (
                task
                for task in batch_tasks
                if str(task.get("task_id") or "").strip() == first_invalid_result.task_id
            ),
            {"task_id": first_invalid_result.task_id},
        )
        classification = _coerce_dict(first_invalid_result.metadata.get("failure_classification"))
        classification_code = str(classification.get("reason_code") or "").strip()
        classification_detail = str(classification.get("reason_detail") or "").strip()
        lines.extend(
            [
                "",
                f"First failing task: `{first_invalid_result.task_id}`",
                *(
                    [f"Failure class: `{classification_code}`"]
                    if classification_code
                    else []
                ),
                *([classification_detail] if classification_detail else []),
                "Validator errors:",
                *[f"- `{error}`" for error in first_invalid_result.errors],
                "",
                "How to fix it:",
                *[
                    f"- {line}"
                    for line in _render_validation_error_help(
                        validation_errors=first_invalid_result.errors,
                        validation_metadata=first_invalid_result.metadata,
                        input_payload=first_invalid_result.input_payload,
                        payload=first_invalid_result.payload,
                    )
                ],
                "",
                f"Current failing draft: `{task_row.get('draft_path') or '?'}`",
                f"Hint file: `{task_row.get('hint_path') or '?'}`",
                f"Input file: `{task_row.get('input_path') or '?'}`",
            ]
        )
    validated_task_ids = {
        task_result.task_id
        for task_result in batch_check_result.task_results
        if task_result.valid
    }
    if validated_task_ids:
        lines.extend(
            [
                "",
                "Already-valid drafts in this batch:",
                *[f"- `{task_id}`" for task_id in sorted(validated_task_ids)],
            ]
        )
    return "\n".join(lines) + "\n"


def write_current_task_sidecars(
    *,
    workspace_root: Path,
    task_row: Mapping[str, Any] | None,
    check_result: KnowledgeWorkspaceCheckResult | None = None,
    current_draft_path: Path | None = None,
) -> None:
    workspace_root = Path(workspace_root)
    current_task_path = workspace_root / "current_task.json"
    brief_path = workspace_root / _CURRENT_TASK_BRIEF_FILE_NAME
    feedback_path = workspace_root / _CURRENT_TASK_FEEDBACK_FILE_NAME
    if task_row is None:
        if current_task_path.exists():
            current_task_path.unlink()
        brief_path.write_text(
            render_current_task_brief_text(workspace_root=workspace_root, task_row=None),
            encoding="utf-8",
        )
        feedback_path.write_text(
            render_current_task_feedback_text(task_row=None),
            encoding="utf-8",
        )
        return
    current_task_path.write_text(
        json.dumps(dict(task_row), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    brief_path.write_text(
        render_current_task_brief_text(
            workspace_root=workspace_root,
            task_row=task_row,
        ),
        encoding="utf-8",
    )
    feedback_path.write_text(
        render_current_task_feedback_text(
            task_row=task_row,
            check_result=check_result,
            current_draft_path=current_draft_path,
        ),
        encoding="utf-8",
    )


def write_current_batch_sidecars(
    *,
    workspace_root: Path,
    batch_payload: Mapping[str, Any] | None,
    batch_check_result: KnowledgeWorkspaceBatchCheckResult | None = None,
) -> None:
    workspace_root = Path(workspace_root)
    current_batch_path = workspace_root / _CURRENT_BATCH_FILE_NAME
    brief_path = workspace_root / _CURRENT_BATCH_BRIEF_FILE_NAME
    feedback_path = workspace_root / _CURRENT_BATCH_FEEDBACK_FILE_NAME
    if batch_payload is None:
        if current_batch_path.exists():
            current_batch_path.unlink()
        brief_path.write_text(
            render_current_batch_brief_text(batch_payload=None),
            encoding="utf-8",
        )
        feedback_path.write_text(
            render_current_batch_feedback_text(batch_payload=None),
            encoding="utf-8",
        )
        return
    current_batch_path.write_text(
        json.dumps(dict(batch_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    brief_path.write_text(
        render_current_batch_brief_text(batch_payload=batch_payload),
        encoding="utf-8",
    )
    feedback_path.write_text(
        render_current_batch_feedback_text(
            batch_payload=batch_payload,
            batch_check_result=batch_check_result,
        ),
        encoding="utf-8",
    )


def write_current_batch_and_task_sidecars(
    *,
    workspace_root: Path,
    task_rows: Sequence[Mapping[str, Any]],
    current_index: int,
    batch_check_result: KnowledgeWorkspaceBatchCheckResult | None = None,
    current_check_result: KnowledgeWorkspaceCheckResult | None = None,
    current_draft_path: Path | None = None,
) -> dict[str, Any] | None:
    workspace_root = Path(workspace_root)
    batch_payload = build_current_batch_payload(
        workspace_root=workspace_root,
        task_rows=task_rows,
        current_index=current_index,
    )
    write_current_batch_sidecars(
        workspace_root=workspace_root,
        batch_payload=batch_payload,
        batch_check_result=batch_check_result,
    )
    current_task_row = (
        dict(task_rows[current_index])
        if 0 <= current_index < len(task_rows)
        else None
    )
    write_current_task_sidecars(
        workspace_root=workspace_root,
        task_row=current_task_row,
        check_result=current_check_result,
        current_draft_path=current_draft_path,
    )
    return batch_payload


def current_task_draft_path(*, workspace_root: Path) -> Path:
    return Path(workspace_root) / "scratch" / "current_task.json"


def _workspace_display_path(*, workspace_root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    resolved_path = Path(path)
    try:
        return resolved_path.relative_to(workspace_root)
    except ValueError:
        return resolved_path


def resolve_current_task_row(*, workspace_root: Path) -> dict[str, Any]:
    task_row = load_current_task_row(workspace_root=workspace_root)
    if task_row is None:
        raise ValueError("no current task is active in this workspace")
    return task_row


def scaffold_current_task_payload(*, workspace_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    task_row = resolve_current_task_row(workspace_root=workspace_root)
    input_payload = load_task_input_payload(workspace_root=workspace_root, task_row=task_row)
    return task_row, scaffold_task_payload(task_row=task_row, input_payload=input_payload)


def write_current_task_scaffold(*, workspace_root: Path, dest_path: Path | None = None) -> Path:
    workspace_root = Path(workspace_root)
    task_row, payload = scaffold_current_task_payload(workspace_root=workspace_root)
    resolved_dest = Path(dest_path) if dest_path is not None else current_task_draft_path(
        workspace_root=workspace_root
    )
    if not resolved_dest.is_absolute():
        resolved_dest = workspace_root / resolved_dest
    resolved_dest.parent.mkdir(parents=True, exist_ok=True)
    resolved_dest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_current_task_sidecars(
        workspace_root=workspace_root,
        task_row=task_row,
        current_draft_path=_workspace_display_path(
            workspace_root=workspace_root,
            path=resolved_dest,
        ),
    )
    return resolved_dest


def write_current_batch_scaffolds(*, workspace_root: Path) -> list[Path]:
    workspace_root = Path(workspace_root)
    batch_payload = load_current_batch_payload(workspace_root=workspace_root)
    if batch_payload is None:
        raise ValueError("no current batch is active in this workspace")
    task_rows_by_id = {
        str(row.get("task_id") or "").strip(): dict(row)
        for row in load_workspace_task_rows(workspace_root=workspace_root)
        if str(row.get("task_id") or "").strip()
    }
    written_paths: list[Path] = []
    for task in batch_payload.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            continue
        task_row = task_rows_by_id.get(task_id)
        if task_row is None:
            raise ValueError(f"unknown batch task {task_id!r}")
        draft_path = current_batch_task_draft_path(
            workspace_root=workspace_root,
            task_id=task_id,
        )
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        payload = scaffold_task_payload(
            task_row=task_row,
            input_payload=load_task_input_payload(
                workspace_root=workspace_root,
                task_row=task_row,
            ),
        )
        draft_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written_paths.append(draft_path)
    write_current_batch_sidecars(
        workspace_root=workspace_root,
        batch_payload=batch_payload,
    )
    return written_paths


def check_current_batch_drafts(
    *,
    workspace_root: Path,
) -> KnowledgeWorkspaceBatchCheckResult:
    workspace_root = Path(workspace_root)
    batch_payload = load_current_batch_payload(workspace_root=workspace_root)
    if batch_payload is None:
        raise ValueError("no current batch is active in this workspace")
    task_rows_by_id = {
        str(row.get("task_id") or "").strip(): dict(row)
        for row in load_workspace_task_rows(workspace_root=workspace_root)
        if str(row.get("task_id") or "").strip()
    }
    task_results: list[KnowledgeWorkspaceCheckResult] = []
    missing_task_ids: list[str] = []
    for task in batch_payload.get("tasks") or []:
        if not isinstance(task, Mapping):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            continue
        task_row = task_rows_by_id.get(task_id)
        if task_row is None:
            missing_task_ids.append(task_id)
            continue
        draft_path = current_batch_task_draft_path(
            workspace_root=workspace_root,
            task_id=task_id,
        )
        if not draft_path.exists():
            missing_task_ids.append(task_id)
            continue
        task_results.append(
            check_workspace_draft(
                workspace_root=workspace_root,
                draft_path=draft_path,
            )
        )
    batch_check_result = KnowledgeWorkspaceBatchCheckResult(
        batch_payload=dict(batch_payload),
        task_results=tuple(task_results),
        missing_task_ids=tuple(missing_task_ids),
        valid=(not missing_task_ids and all(task_result.valid for task_result in task_results)),
    )
    write_current_batch_sidecars(
        workspace_root=workspace_root,
        batch_payload=batch_payload,
        batch_check_result=batch_check_result,
    )
    return batch_check_result


def install_current_batch_drafts(
    *,
    workspace_root: Path,
) -> tuple[KnowledgeWorkspaceBatchCheckResult, tuple[str, ...]]:
    workspace_root = Path(workspace_root)
    batch_check_result = check_current_batch_drafts(workspace_root=workspace_root)
    installed_task_ids: list[str] = []
    for task_result in batch_check_result.task_results:
        if not task_result.valid:
            break
        task_result.result_path.parent.mkdir(parents=True, exist_ok=True)
        task_result.result_path.write_text(
            json.dumps(task_result.payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        installed_task_ids.append(task_result.task_id)
    advance_workspace_sidecars_from_outputs(workspace_root=workspace_root)
    return batch_check_result, tuple(installed_task_ids)


def render_overview_text(*, workspace_root: Path) -> str:
    task_rows = load_workspace_task_rows(workspace_root=workspace_root)
    current_task = load_current_task_row(workspace_root=workspace_root)
    current_task_id = str((current_task or {}).get("task_id") or "").strip()
    if not task_rows:
        return "No assigned tasks.\n"
    lines = []
    if current_task_id:
        lines.append(f"current_task: {current_task_id}")
    for index, row in enumerate(task_rows, start=1):
        task_id = str(row.get("task_id") or "").strip() or "[unknown task]"
        metadata = _coerce_dict(row.get("metadata"))
        prefix = "* " if task_id == current_task_id else "  "
        lines.append(
            (
                f"{prefix}{index}. {task_id}"
                f" | input={metadata.get('input_path') or '?'}"
                f" | hint={metadata.get('hint_path') or '?'}"
                f" | result={metadata.get('result_path') or '?'}"
            )
        )
    return "\n".join(lines) + "\n"


def render_task_text(*, workspace_root: Path, task_id: str) -> str:
    task_row = resolve_task_row(workspace_root=workspace_root, task_id=task_id)
    input_payload = load_task_input_payload(workspace_root=workspace_root, task_row=task_row)
    metadata = _coerce_dict(task_row.get("metadata"))
    packet_id = str(input_payload.get("bid") or input_payload.get("packet_id") or "").strip()
    block_rows = [
        dict(block)
        for block in (input_payload.get("b") or [])
        if isinstance(block, Mapping) and block.get("i") is not None
    ]
    block_indices = [int(block.get("i")) for block in block_rows]
    lines = [
        f"task_id: {task_row['task_id']}",
        f"parent_shard_id: {task_row.get('parent_shard_id') or task_row['task_id']}",
        f"task_sequence: {metadata.get('task_sequence') or '?'} / {metadata.get('task_total') or '?'}",
        f"input_path: {metadata.get('input_path') or '?'}",
        f"hint_path: {metadata.get('hint_path') or '?'}",
        f"result_path: {metadata.get('result_path') or '?'}",
        f"owned_packet_id: {packet_id or '[none]'}",
    ]
    if block_indices:
        lines.append(f"packet_blocks: {block_indices[0]}..{block_indices[-1]}")
    else:
        lines.append("packet_blocks: [none]")
    return "\n".join(lines) + "\n"


def scaffold_task_payload(*, task_row: Mapping[str, Any], input_payload: Mapping[str, Any]) -> dict[str, Any]:
    task_id = str(task_row.get("task_id") or "").strip()
    block_decisions = []
    for packet in _packet_rows(input_payload):
        for block in packet.get("b") or []:
            if not isinstance(block, Mapping) or block.get("i") is None:
                continue
            block_decisions.append(
                {
                    "block_index": int(block.get("i")),
                    "category": "other",
                    "reviewer_category": "other",
                }
            )
    return {
        "packet_id": task_id,
        "block_decisions": block_decisions,
        "idea_groups": [],
    }


def build_knowledge_workspace_contract_examples(
    *,
    tasks: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    sample_task_row, sample_input_payload, sample_packet_id = _resolve_sample_task(tasks)
    valid_example = scaffold_task_payload(
        task_row=sample_task_row,
        input_payload=sample_input_payload,
    )
    evidence_rows, source_text = _sample_evidence_rows(sample_input_payload)
    evidence_block_indices = {
        int(row.get("block_index"))
        for row in evidence_rows
        if row.get("block_index") is not None
    }
    if evidence_rows and evidence_block_indices:
        valid_example["block_decisions"] = [
            {
                "block_index": int(block.get("i")),
                "category": (
                    "knowledge"
                    if int(block.get("i")) in evidence_block_indices
                    else "other"
                ),
                "reviewer_category": (
                    "knowledge"
                    if int(block.get("i")) in evidence_block_indices
                    else "other"
                ),
            }
            for block in (sample_input_payload.get("b") or [])
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        valid_example["idea_groups"] = [
            {
                "group_id": "idea-1",
                "topic_label": _short_grounded_snippet(source_text),
                "block_indices": sorted(evidence_block_indices),
                "snippets": [
                    {
                        "body": _short_grounded_snippet(source_text),
                        "evidence": evidence_rows,
                    }
                ],
            }
        ]
    invalid_example = json.loads(json.dumps(valid_example))
    if invalid_example.get("idea_groups"):
        invalid_example["idea_groups"][0]["snippets"][0]["body"] = source_text
    low_utility_example = {
        "packet_id": "utility-contrast-low-value",
        "block_decisions": [
            {
                "block_index": 41,
                "category": "other",
                "reviewer_category": "other",
            }
        ],
        "idea_groups": [],
    }
    framing_example = {
        "packet_id": "utility-contrast-framing",
        "block_decisions": [
            {
                "block_index": 51,
                "category": "other",
                "reviewer_category": "front_matter",
            },
            {
                "block_index": 52,
                "category": "other",
                "reviewer_category": "endorsement_or_marketing",
            },
        ],
        "idea_groups": [],
    }
    heading_example = {
        "packet_id": "utility-contrast-heading-body",
        "block_decisions": [
            {
                "block_index": 71,
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
            {
                "block_index": 72,
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
        ],
        "idea_groups": [
            {
                "group_id": "idea-1",
                "topic_label": "Salt seasons earlier and more evenly",
                "block_indices": [71, 72],
                "snippets": [
                    {
                        "body": "Salt helps food taste more like itself and seasons it more evenly when applied early.",
                        "evidence": [
                            {
                                "block_index": 72,
                                "quote": "Salt helps food taste more like itself and seasons it more evenly when applied early.",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    navigation_example = {
        "packet_id": "utility-contrast-navigation",
        "block_decisions": [
            {
                "block_index": 61,
                "category": "other",
                "reviewer_category": "chapter_taxonomy",
            }
        ],
        "idea_groups": [],
    }
    return {
        "valid_semantic_packet.json": valid_example,
        "invalid_echo_packet.json": invalid_example,
        "valid_all_other_low_utility_packet.json": low_utility_example,
        "valid_all_other_framing_packet.json": framing_example,
        "valid_heading_with_useful_body_packet.json": heading_example,
        "valid_all_other_navigation_packet.json": navigation_example,
    }


def build_knowledge_workspace_contract_markdown(
    *,
    examples: Mapping[str, Mapping[str, Any]],
) -> str:
    valid_example = json.dumps(
        dict(examples.get("valid_semantic_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    invalid_example = json.dumps(
        dict(examples.get("invalid_echo_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    low_utility_example = json.dumps(
        dict(examples.get("valid_all_other_low_utility_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    framing_example = json.dumps(
        dict(examples.get("valid_all_other_framing_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    heading_example = json.dumps(
        dict(examples.get("valid_heading_with_useful_body_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    navigation_example = json.dumps(
        dict(examples.get("valid_all_other_navigation_packet.json") or {}),
        indent=2,
        sort_keys=True,
    )
    return "\n".join(
        [
            "# Knowledge Workspace Output Contract",
            "",
            "Write one semantic task-result JSON object per task to `out/<task_id>.json`.",
            "Keep only durable cooking leverage. The positive class is not broad factuality; it is information worth preserving because it improves future cooking decisions, diagnosis, or technique.",
            "",
            "Required top-level keys:",
            "- `packet_id`: must equal the task row `task_id` exactly.",
            "- `block_decisions`: cover every owned block index exactly once and in order.",
            "- `idea_groups`: group only the kept `knowledge` blocks into one or more related ideas.",
            "",
            "Per idea group:",
            "- `group_id`: a stable packet-local id such as `g01`.",
            "- `topic_label`: a short human-readable label for the related idea.",
            "- `block_indices`: packet-owned `knowledge` block indices only, kept in order.",
            "- `snippets`: grounded reusable claims only; each snippet needs evidence rows with `block_index` plus verbatim `quote`.",
            "",
            "Category rules:",
            f"- Final `category` values are only `{ALLOWED_KNOWLEDGE_FINAL_CATEGORIES[0]}` or `{ALLOWED_KNOWLEDGE_FINAL_CATEGORIES[1]}`.",
            "- Optional `reviewer_category` values are `knowledge`, `chapter_taxonomy`, `decorative_heading`, `front_matter`, `toc_navigation`, `endorsement_or_marketing`, `memoir_or_scene_setting`, `reference_back_matter`, or `other`.",
            "- If final `category` is `knowledge`, `reviewer_category` must also be `knowledge`.",
            "- Every `knowledge` block must belong to exactly one idea group.",
            "- No `other` block may appear inside an idea group.",
            "",
            "Utility questions:",
            "- Would saving this materially improve a cook's future decisions, diagnosis, or technique?",
            "- Does it explain cause and effect, sensory judgment, troubleshooting, ingredient behavior, substitution, storage, safety, or durable technique?",
            "- If the text is technically true but generic or low-value, keep it `other`.",
            "- If a short conceptual heading directly introduces useful explanatory blocks in the same packet, keep that heading with the useful body rather than demoting it to decoration.",
            "",
            "Snippet rules:",
            "- Good snippet: a short grounded claim such as `Use low heat to prevent curdling.` supported by one or two short evidence quotes.",
            "- Bad snippet: a whole-block dump, a full-packet echo, or a long stitched quote list copied from the evidence surface.",
            "",
            "Workflow:",
            "- Start from `CURRENT_BATCH.md`, `current_batch.json`, and `CURRENT_BATCH_FEEDBACK.md`.",
            "- Use `python3 tools/knowledge_worker.py complete-batch` to prewrite the current batch drafts under `scratch/current_batch/`.",
            "- If you automate, automate only the active batch drafts named in `current_batch.json` and `scratch/current_batch/`; do not script directly against `assigned_tasks.json`, `current_task.json`, or `out/`.",
            "- Run `python3 tools/knowledge_worker.py check-batch` before every final batch install step; copied evidence text in `snippets[].body` is invalid.",
            "- The normal path is `install-batch`, which writes the longest valid prefix of the current batch to the declared `out/<task_id>.json` files.",
            "- The single-task `CURRENT_TASK*` files plus `python3 tools/knowledge_worker.py debug complete-current|check-current|install-current` remain available only for targeted recovery/debugging on the first active task.",
            "- The lower-level `python3 tools/knowledge_worker.py debug scaffold|check|install|show|overview` commands remain available for targeted debugging. Reading `tools/knowledge_worker.py` source is discouraged and usually wasted motion, but queue/output bypass is the hard failure boundary.",
            "",
            "Valid example:",
            valid_example,
            "",
            "Valid all-`other` low-utility example:",
            low_utility_example,
            "",
            "Valid all-`other` framing example:",
            framing_example,
            "",
            "Valid heading-plus-useful-body example:",
            heading_example,
            "",
            "Valid all-`other` navigation example:",
            navigation_example,
            "",
            "Intentionally invalid echo example:",
            invalid_example,
            "",
            "Machine-readable copies of these examples also live under `examples/`.",
        ]
    ) + "\n"


def write_knowledge_workspace_sidecars(
    *,
    worker_root: Path,
    tasks: Sequence[Mapping[str, Any]],
) -> None:
    examples = build_knowledge_workspace_contract_examples(tasks=tasks)
    examples_dir = worker_root / "examples"
    tools_dir = worker_root / "tools"
    examples_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)
    (worker_root / "OUTPUT_CONTRACT.md").write_text(
        build_knowledge_workspace_contract_markdown(examples=examples),
        encoding="utf-8",
    )
    for filename, payload in examples.items():
        (examples_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (tools_dir / _WORKER_SCRIPT_NAME).write_text(
        render_knowledge_worker_script(),
        encoding="utf-8",
    )


def resolve_task_row(*, workspace_root: Path, task_id: str) -> dict[str, Any]:
    cleaned_task_id = str(task_id or "").strip()
    if not cleaned_task_id:
        raise ValueError("task id is required")
    for row in load_workspace_task_rows(workspace_root=workspace_root):
        row_task_id = str(row.get("task_id") or "").strip()
        if row_task_id == cleaned_task_id:
            return row
    raise ValueError(f"unknown task id: {cleaned_task_id}")


def load_task_input_payload(*, workspace_root: Path, task_row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _coerce_dict(task_row.get("metadata"))
    input_path = str(metadata.get("input_path") or "").strip()
    if not input_path:
        raise ValueError(f"task {task_row.get('task_id')!r} is missing metadata.input_path")
    payload = _load_json(Path(workspace_root) / input_path)
    if not isinstance(payload, Mapping):
        raise ValueError(f"task {task_row.get('task_id')!r} input payload must be a JSON object")
    return dict(payload)


def check_workspace_draft(
    *,
    workspace_root: Path,
    draft_path: Path,
) -> KnowledgeWorkspaceCheckResult:
    draft_payload = _load_json(draft_path)
    if not isinstance(draft_payload, Mapping):
        raise ValueError(f"{draft_path} must contain one JSON object")
    task_id = _infer_task_id(dict(draft_payload))
    if not task_id:
        raise ValueError(f"{draft_path} does not declare `packet_id` or `bid`")
    task_row = resolve_task_row(workspace_root=workspace_root, task_id=task_id)
    input_payload = load_task_input_payload(workspace_root=workspace_root, task_row=task_row)
    shard = build_workspace_task_shard(task_row=task_row, input_payload=input_payload)
    valid, errors, metadata = validate_knowledge_shard_output(shard, dict(draft_payload))
    metadata = dict(metadata)
    metadata["failure_classification"] = classify_knowledge_validation_failure(
        validation_errors=errors,
        validation_metadata=metadata,
    )
    try:
        normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(
            dict(draft_payload)
        )
    except Exception:
        normalized_payload = None
        normalization_metadata = None
    if normalized_payload is not None:
        metadata.setdefault("normalized_payload", normalized_payload)
    if normalization_metadata is not None:
        metadata.setdefault("normalization_metadata", normalization_metadata)
    result_path = _resolve_result_path(workspace_root=workspace_root, task_row=task_row)
    return KnowledgeWorkspaceCheckResult(
        task_id=task_id,
        task_row=task_row,
        input_payload=input_payload,
        draft_path=Path(draft_path),
        result_path=result_path,
        payload=dict(draft_payload),
        valid=bool(valid),
        errors=tuple(errors),
        metadata=metadata,
    )


def install_workspace_draft(
    *,
    workspace_root: Path,
    draft_path: Path,
) -> KnowledgeWorkspaceCheckResult:
    check_result = check_workspace_draft(
        workspace_root=workspace_root,
        draft_path=draft_path,
    )
    if not check_result.valid:
        raise ValueError(_format_workspace_validation_failure(check_result))
    check_result.result_path.parent.mkdir(parents=True, exist_ok=True)
    check_result.result_path.write_text(
        json.dumps(check_result.payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return check_result


def check_current_task_draft(
    *,
    workspace_root: Path,
    draft_path: Path | None = None,
) -> KnowledgeWorkspaceCheckResult:
    workspace_root = Path(workspace_root)
    task_row = resolve_current_task_row(workspace_root=workspace_root)
    resolved_draft_path = Path(draft_path) if draft_path is not None else current_task_draft_path(
        workspace_root=workspace_root
    )
    if not resolved_draft_path.is_absolute():
        resolved_draft_path = workspace_root / resolved_draft_path
    check_result = check_workspace_draft(
        workspace_root=workspace_root,
        draft_path=resolved_draft_path,
    )
    write_current_task_sidecars(
        workspace_root=workspace_root,
        task_row=task_row,
        check_result=check_result,
        current_draft_path=_workspace_display_path(
            workspace_root=workspace_root,
            path=resolved_draft_path,
        ),
    )
    return check_result


def install_current_task_draft(
    *,
    workspace_root: Path,
    draft_path: Path | None = None,
) -> KnowledgeWorkspaceCheckResult:
    workspace_root = Path(workspace_root)
    task_row = resolve_current_task_row(workspace_root=workspace_root)
    resolved_draft_path = Path(draft_path) if draft_path is not None else current_task_draft_path(
        workspace_root=workspace_root
    )
    if not resolved_draft_path.is_absolute():
        resolved_draft_path = workspace_root / resolved_draft_path
    check_result = install_workspace_draft(
        workspace_root=workspace_root,
        draft_path=resolved_draft_path,
    )
    write_current_task_sidecars(
        workspace_root=workspace_root,
        task_row=task_row,
        check_result=check_result,
        current_draft_path=_workspace_display_path(
            workspace_root=workspace_root,
            path=resolved_draft_path,
        ),
    )
    advance_workspace_sidecars_from_outputs(workspace_root=workspace_root)
    return check_result


def advance_workspace_sidecars_from_outputs(*, workspace_root: Path) -> int:
    workspace_root = Path(workspace_root)
    task_rows = load_workspace_task_rows(workspace_root=workspace_root)
    current_index = 0
    current_check_result: KnowledgeWorkspaceCheckResult | None = None
    while current_index < len(task_rows):
        task_row = dict(task_rows[current_index])
        metadata = _coerce_dict(task_row.get("metadata"))
        result_path = str(metadata.get("result_path") or "").strip()
        if not result_path:
            break
        resolved_result_path = workspace_root / result_path
        if not resolved_result_path.exists():
            break
        try:
            check_result = check_workspace_draft(
                workspace_root=workspace_root,
                draft_path=resolved_result_path,
            )
        except Exception:  # noqa: BLE001
            break
        if not check_result.valid:
            current_check_result = check_result
            break
        current_index += 1
        current_check_result = None
    write_current_batch_and_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
        current_index=current_index,
        current_check_result=current_check_result,
        current_draft_path=current_task_draft_path(workspace_root=workspace_root),
    )
    return current_index


def _format_workspace_validation_failure(
    check_result: KnowledgeWorkspaceCheckResult,
) -> str:
    guidance_lines = _render_validation_error_help(
        validation_errors=check_result.errors,
        validation_metadata=check_result.metadata,
        input_payload=check_result.input_payload,
        payload=check_result.payload,
    )
    lines = [
        "knowledge draft failed validation:",
        f"- Errors: {', '.join(check_result.errors) or 'validation_failed'}",
    ]
    lines.extend(f"- {line}" for line in guidance_lines)
    return "\n".join(lines)


def _render_validation_error_help(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    input_payload: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> list[str]:
    error_set = {
        str(error).strip()
        for error in validation_errors
        if str(error).strip()
    }
    metadata = _coerce_dict(validation_metadata)
    help_lines: list[str] = []

    if (
        "semantic_snippet_echoes_packet_surface" in error_set
        or "semantic_snippet_copies_evidence_quote" in error_set
    ):
        help_lines.append(
            "Keep each `evidence[].quote` verbatim, but rewrite `snippets[].body` into a shorter grounded claim in your own words."
        )
        help_lines.extend(
            _render_snippet_copy_detail_lines(
                validation_metadata=metadata,
                input_payload=input_payload,
                payload=payload,
            )
        )
    if "semantic_snippet_body_not_grounded_text" in error_set:
        non_grounded_group_ids = [
            str(group_id).strip()
            for group_id in (metadata.get("non_grounded_idea_group_ids") or [])
            if str(group_id).strip()
        ]
        if non_grounded_group_ids:
            help_lines.append(
                "These idea groups need real grounded prose in `snippets[].body`: "
                + ", ".join(f"`{group_id}`" for group_id in non_grounded_group_ids)
                + "."
            )
        else:
            help_lines.append(
                "Use plain-language snippet bodies that state a reusable claim supported by the evidence."
            )
    if "missing_owned_block_decisions" in error_set or "unexpected_block_decisions" in error_set:
        help_lines.append(
            "Cover every owned block exactly once in top-level `block_decisions`, with no extras."
        )
    if "block_decision_order_mismatch" in error_set:
        help_lines.append(
            "Keep `block_decisions` in the same order as the owned packet blocks."
        )
    if "knowledge_block_missing_group" in error_set:
        help_lines.append(
            "Every block marked `knowledge` must appear in exactly one `idea_groups[*].block_indices` list."
        )
    if "knowledge_block_group_conflict" in error_set:
        help_lines.append(
            "Do not place the same knowledge block into more than one idea group."
        )
    if "group_contains_other_block" in error_set:
        help_lines.append(
            "Only blocks marked `knowledge` may appear in `idea_groups[*].block_indices`."
        )
    if "snippet_evidence_wrong_chunk_surface" in error_set:
        help_lines.append(
            "Each snippet may cite only block indices from its own owned packet surface."
        )
    if "snippet_evidence_out_of_surface" in error_set:
        help_lines.append(
            "Do not cite block indices outside the task's owned surface."
        )
    if "bundle_id_mismatch" in error_set:
        help_lines.append(
            "`packet_id` must exactly match the current task row's `task_id`."
        )
    if not help_lines:
        help_lines.append(
            "Re-open `OUTPUT_CONTRACT.md`, compare against `examples/`, and fix only the fields named in the validator errors."
        )
    help_lines.append("Run `check` again and wait for `OK ...` before `install`.")
    return list(dict.fromkeys(line for line in help_lines if line.strip()))


def _render_snippet_copy_detail_lines(
    *,
    validation_metadata: Mapping[str, Any] | None,
    input_payload: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> list[str]:
    metadata = _coerce_dict(validation_metadata)
    normalized_payload = metadata.get("normalized_payload")
    canonical_payload = (
        dict(normalized_payload)
        if isinstance(normalized_payload, Mapping)
        else dict(payload)
        if isinstance(payload, Mapping)
        else {}
    )
    idea_groups_by_id = {
        str(group.get("gid") or "").strip(): group
        for group in (canonical_payload.get("g") or [])
        if isinstance(group, Mapping) and str(group.get("gid") or "").strip()
    }
    source_text_by_block_index = {
        int(block.get("i")): str(block.get("t") or "").strip()
        for block in ((input_payload or {}).get("b") or [])
        if isinstance(block, Mapping)
        and block.get("i") is not None
        and str(block.get("t") or "").strip()
    }

    lines: list[str] = []
    copied_group_ids = [
        str(group_id).strip()
        for group_id in (metadata.get("copied_quote_idea_group_ids") or [])
        if str(group_id).strip()
    ]
    for group_id in copied_group_ids:
        group_payload = idea_groups_by_id.get(group_id) or {}
        snippet_rows = [
            snippet
            for snippet in (group_payload.get("s") or [])
            if isinstance(snippet, Mapping)
        ]
        quote_preview = _trim_preview(
            " ".join(
                str(evidence.get("q") or "").strip()
                for snippet in snippet_rows
                for evidence in (snippet.get("e") or [])
                if isinstance(evidence, Mapping) and str(evidence.get("q") or "").strip()
            )
        )
        lines.append(
            f"Idea group `{group_id}` copied too much evidence text"
            + (
                f": `{quote_preview}`. Keep that quote in `evidence`, but shorten the body."
                if quote_preview
                else ". Keep the evidence quote, but shorten the body."
            )
        )
    echoed_group_ids = [
        str(group_id).strip()
        for group_id in (metadata.get("echoed_idea_group_ids") or [])
        if str(group_id).strip()
    ]
    for group_id in echoed_group_ids:
        group_payload = idea_groups_by_id.get(group_id) or {}
        group_surface = _trim_preview(
            " ".join(
                source_text_by_block_index.get(int(block_index), "")
                for block_index in (group_payload.get("bi") or [])
                if block_index is not None
            )
        )
        line = f"Idea group `{group_id}` body is too close to the full owned packet surface."
        if group_surface:
            line += f" Source surface: `{group_surface}`."
        line += " Leave the longer wording in evidence quotes only and keep the body to one short claim."
        lines.append(line)
    return list(dict.fromkeys(line for line in lines if line.strip()))


def _trim_preview(value: str, *, max_chars: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def build_workspace_task_shard(
    *,
    task_row: Mapping[str, Any],
    input_payload: Mapping[str, Any],
) -> ShardManifestEntryV1:
    task_id = str(task_row.get("task_id") or "").strip()
    metadata = dict(_coerce_dict(task_row.get("metadata")))
    packet_id = str(input_payload.get("bid") or input_payload.get("packet_id") or task_id).strip()
    owned_block_indices = [
        int(block.get("i"))
        for block in (input_payload.get("b") or [])
        if isinstance(block, Mapping) and block.get("i") is not None
    ]
    metadata.setdefault("packet_id", packet_id)
    if owned_block_indices:
        metadata.setdefault("owned_block_indices", owned_block_indices)
    return ShardManifestEntryV1(
        shard_id=task_id,
        owned_ids=(packet_id,),
        input_payload=dict(input_payload),
        metadata=metadata,
    )


def render_knowledge_worker_script() -> str:
    no_current_batch_active_text = json.dumps(_NO_CURRENT_BATCH_ACTIVE_TEXT)
    active_batch_assignment_text = json.dumps(_ACTIVE_BATCH_ASSIGNMENT_TEXT)
    no_repo_written_batch_feedback_text = json.dumps(_NO_REPO_WRITTEN_BATCH_FEEDBACK_TEXT)
    check_batch_after_edit_text = json.dumps(_CHECK_BATCH_AFTER_EDIT_TEXT)
    batch_validation_status_ok_text = json.dumps(_BATCH_VALIDATION_STATUS_OK_TEXT)
    batch_validator_accepted_text = json.dumps(_BATCH_VALIDATOR_ACCEPTED_TEXT)
    install_batch_ready_text = json.dumps(_INSTALL_BATCH_READY_TEXT)
    reopen_batch_after_install_text = json.dumps(_REOPEN_BATCH_AFTER_INSTALL_TEXT)
    continue_batch_immediately_text = json.dumps(_CONTINUE_BATCH_IMMEDIATELY_TEXT)
    install_batch_success_notice = json.dumps(_INSTALL_BATCH_SUCCESS_NOTICE)
    no_current_task_active_text = json.dumps(_NO_CURRENT_TASK_ACTIVE_TEXT)
    active_assignment_text = json.dumps(_ACTIVE_ASSIGNMENT_TEXT)
    no_repo_written_feedback_text = json.dumps(_NO_REPO_WRITTEN_FEEDBACK_TEXT)
    check_current_after_edit_text = json.dumps(_CHECK_CURRENT_AFTER_EDIT_TEXT)
    validation_status_ok_text = json.dumps(_VALIDATION_STATUS_OK_TEXT)
    validator_accepted_text = json.dumps(_VALIDATOR_ACCEPTED_TEXT)
    install_current_ready_text = json.dumps(_INSTALL_CURRENT_READY_TEXT)
    reopen_after_install_text = json.dumps(_REOPEN_AFTER_INSTALL_TEXT)
    continue_immediately_text = json.dumps(_CONTINUE_IMMEDIATELY_TEXT)
    queue_complete_text = json.dumps(_QUEUE_COMPLETE_TEXT)
    install_current_success_notice = json.dumps(_INSTALL_CURRENT_SUCCESS_NOTICE)
    allowed_final_categories = json.dumps(ALLOWED_KNOWLEDGE_FINAL_CATEGORIES)
    allowed_reviewer_categories = json.dumps(ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES)
    allowed_reason_codes = json.dumps(ALLOWED_KNOWLEDGE_REASON_CODES)
    return (
        textwrap.dedent(
            """
        #!/usr/bin/env python3
        from __future__ import annotations

        import argparse
        import json
        import re
        import sys
        from pathlib import Path

        ALLOWED_FINAL_CATEGORIES = tuple({allowed_final_categories})
        ALLOWED_REVIEWER_CATEGORIES = tuple({allowed_reviewer_categories})
        ALLOWED_REASON_CODES = tuple({allowed_reason_codes})
        SEMANTIC_CATEGORY_ALIAS_DEFAULTS = {
            "content": ("knowledge", "knowledge"),
            "noise": ("other", "endorsement_or_marketing"),
            "heading": ("other", "decorative_heading"),
        }
        USEFUL_REASON_CODES = {
            "technique_or_mechanism",
            "diagnostic_or_troubleshooting",
            "reference_or_definition",
            "substitution_storage_or_safety",
        }
        NON_USEFUL_REASON_CODES = {
            "book_framing_or_marketing",
            "memoir_or_scene_setting",
            "navigation_or_chapter_taxonomy",
            "decorative_heading_only",
            "true_but_low_utility",
            "not_cooking_knowledge",
            "review_not_completed",
            "strong_cue_review_required",
        }
        DEFAULT_SCAFFOLD_REASON_CODE = "review_not_completed"
        STRONG_CUE_SCAFFOLD_REASON_CODE = "strong_cue_review_required"
        CURRENT_BATCH_FILE_NAME = "current_batch.json"
        CURRENT_BATCH_BRIEF_FILE_NAME = "CURRENT_BATCH.md"
        CURRENT_BATCH_FEEDBACK_FILE_NAME = "CURRENT_BATCH_FEEDBACK.md"
        CURRENT_TASK_BRIEF_FILE_NAME = "CURRENT_TASK.md"
        CURRENT_TASK_FEEDBACK_FILE_NAME = "CURRENT_TASK_FEEDBACK.md"
        KNOWLEDGE_MICRO_BATCH_MAX_TASKS = 4
        KNOWLEDGE_MICRO_BATCH_MAX_INPUT_BYTES = 24000
        NO_CURRENT_BATCH_ACTIVE_TEXT = {no_current_batch_active_text}
        ACTIVE_BATCH_ASSIGNMENT_TEXT = {active_batch_assignment_text}
        NO_REPO_WRITTEN_BATCH_FEEDBACK_TEXT = {no_repo_written_batch_feedback_text}
        CHECK_BATCH_AFTER_EDIT_TEXT = {check_batch_after_edit_text}
        BATCH_VALIDATION_STATUS_OK_TEXT = {batch_validation_status_ok_text}
        BATCH_VALIDATOR_ACCEPTED_TEXT = {batch_validator_accepted_text}
        INSTALL_BATCH_READY_TEXT = {install_batch_ready_text}
        REOPEN_BATCH_AFTER_INSTALL_TEXT = {reopen_batch_after_install_text}
        CONTINUE_BATCH_IMMEDIATELY_TEXT = {continue_batch_immediately_text}
        INSTALL_BATCH_SUCCESS_NOTICE = {install_batch_success_notice}
        NO_CURRENT_TASK_ACTIVE_TEXT = {no_current_task_active_text}
        ACTIVE_ASSIGNMENT_TEXT = {active_assignment_text}
        NO_REPO_WRITTEN_FEEDBACK_TEXT = {no_repo_written_feedback_text}
        CHECK_CURRENT_AFTER_EDIT_TEXT = {check_current_after_edit_text}
        VALIDATION_STATUS_OK_TEXT = {validation_status_ok_text}
        VALIDATOR_ACCEPTED_TEXT = {validator_accepted_text}
        INSTALL_CURRENT_READY_TEXT = {install_current_ready_text}
        REOPEN_AFTER_INSTALL_TEXT = {reopen_after_install_text}
        CONTINUE_IMMEDIATELY_TEXT = {continue_immediately_text}
        QUEUE_COMPLETE_TEXT = {queue_complete_text}
        INSTALL_CURRENT_SUCCESS_NOTICE = {install_current_success_notice}

        def _workspace_root() -> Path:
            return Path(__file__).resolve().parent.parent

        def _load_json(path: Path):
            return json.loads(path.read_text(encoding="utf-8"))

        def _coerce_dict(value):
            return dict(value) if isinstance(value, dict) else {}

        def _task_rows():
            path = _workspace_root() / "assigned_tasks.json"
            if not path.exists():
                return []
            payload = _load_json(path)
            if not isinstance(payload, list):
                return []
            return [dict(row) for row in payload if isinstance(row, dict)]

        def _current_task():
            path = _workspace_root() / "current_task.json"
            if not path.exists():
                return None
            payload = _load_json(path)
            return dict(payload) if isinstance(payload, dict) else None

        def _current_batch():
            path = _workspace_root() / CURRENT_BATCH_FILE_NAME
            if not path.exists():
                return None
            payload = _load_json(path)
            return dict(payload) if isinstance(payload, dict) else None

        def _current_batch_required():
            payload = _current_batch()
            if payload is None:
                raise ValueError("no current batch is active in this workspace")
            return payload

        def _current_task_required():
            payload = _current_task()
            if payload is None:
                raise ValueError("no current task is active in this workspace")
            return payload

        def _current_batch_draft_dir():
            return _workspace_root() / "scratch" / "current_batch"

        def _current_batch_task_draft_path(task_id: str):
            cleaned_task_id = str(task_id or "").strip()
            if not cleaned_task_id:
                raise ValueError("task_id is required for a batch draft path")
            return _current_batch_draft_dir() / f"{cleaned_task_id}.json"

        def _current_task_draft_path():
            return _workspace_root() / "scratch" / "current_task.json"

        def _current_batch_brief_path():
            return _workspace_root() / CURRENT_BATCH_BRIEF_FILE_NAME

        def _current_batch_feedback_path():
            return _workspace_root() / CURRENT_BATCH_FEEDBACK_FILE_NAME

        def _current_brief_path():
            return _workspace_root() / CURRENT_TASK_BRIEF_FILE_NAME

        def _current_feedback_path():
            return _workspace_root() / CURRENT_TASK_FEEDBACK_FILE_NAME

        def _task_row(task_id: str):
            for row in _task_rows():
                if str(row.get("task_id") or "").strip() == task_id:
                    return row
            raise ValueError(f"unknown task id: {task_id}")

        def _task_input_payload(task_row):
            metadata = _coerce_dict(task_row.get("metadata"))
            input_path = str(metadata.get("input_path") or "").strip()
            if not input_path:
                raise ValueError(f"task {task_row.get('task_id')!r} is missing metadata.input_path")
            payload = _load_json(_workspace_root() / input_path)
            if not isinstance(payload, dict):
                raise ValueError("task input payload must be a JSON object")
            return dict(payload)

        def _packet_rows(input_payload):
            blocks = input_payload.get("b")
            if not isinstance(blocks, list):
                return []
            packet_id = str(input_payload.get("bid") or input_payload.get("packet_id") or "").strip()
            return [
                {
                    "bid": packet_id,
                    "b": [dict(block) for block in blocks if isinstance(block, dict)],
                }
            ]

        def _owned_packet_ids(input_payload):
            return [
                str(packet.get("bid") or "").strip()
                for packet in _packet_rows(input_payload)
                if str(packet.get("bid") or "").strip()
            ]

        def _resolve_result_path(task_row):
            metadata = _coerce_dict(task_row.get("metadata"))
            result_path = str(metadata.get("result_path") or "").strip()
            if not result_path:
                raise ValueError(f"task {task_row.get('task_id')!r} is missing metadata.result_path")
            return _workspace_root() / result_path

        def _workspace_display_path(path: Path | None):
            if path is None:
                return None
            try:
                return path.relative_to(_workspace_root())
            except ValueError:
                return path

        def _task_input_bytes(task_row):
            metadata = _coerce_dict(task_row.get("metadata"))
            input_path = str(metadata.get("input_path") or "").strip()
            if not input_path:
                return 0
            resolved_path = _workspace_root() / input_path
            if resolved_path.exists():
                return resolved_path.stat().st_size
            try:
                return len(json.dumps(_task_input_payload(task_row), sort_keys=True))
            except Exception:
                return 0

        def _task_block_spans(input_payload):
            block_spans = []
            for packet in _packet_rows(input_payload):
                packet_id = str(packet.get("bid") or "").strip() or "[unknown packet]"
                block_indices = [
                    int(block.get("i"))
                    for block in packet.get("b") or []
                    if isinstance(block, dict) and block.get("i") is not None
                ]
                if not block_indices:
                    block_spans.append(f"{packet_id}:[no blocks]")
                    continue
                block_spans.append(f"{packet_id}:{block_indices[0]}..{block_indices[-1]}")
            return block_spans

        def _build_current_batch_payload(start_index=0):
            rows = _task_rows()
            if start_index < 0 or start_index >= len(rows):
                return None
            batch_rows = []
            total_input_bytes = 0
            for row in rows[start_index:]:
                row_input_bytes = _task_input_bytes(row)
                would_exceed_count = len(batch_rows) >= KNOWLEDGE_MICRO_BATCH_MAX_TASKS
                would_exceed_bytes = (
                    batch_rows
                    and total_input_bytes + row_input_bytes > KNOWLEDGE_MICRO_BATCH_MAX_INPUT_BYTES
                )
                if would_exceed_count or would_exceed_bytes:
                    break
                batch_rows.append(row)
                total_input_bytes += row_input_bytes
            if not batch_rows:
                batch_rows.append(rows[start_index])
                total_input_bytes = _task_input_bytes(batch_rows[0])
            total_task_count = len(rows)
            batch_tasks = []
            for offset, row in enumerate(batch_rows, start=1):
                metadata = _coerce_dict(row.get("metadata"))
                task_id = str(row.get("task_id") or "").strip() or "[unknown task]"
                batch_tasks.append(
                    {
                        "task_id": task_id,
                        "queue_position": int(metadata.get("task_sequence") or start_index + offset),
                        "task_total": int(metadata.get("task_total") or total_task_count),
                        "input_path": str(metadata.get("input_path") or "").strip() or None,
                        "hint_path": str(metadata.get("hint_path") or "").strip() or None,
                        "result_path": str(metadata.get("result_path") or "").strip() or None,
                        "draft_path": str(_workspace_display_path(_current_batch_task_draft_path(task_id))),
                        "owned_packet_ids": [
                            str(value).strip()
                            for value in (row.get("owned_ids") or [])
                            if str(value).strip()
                        ],
                    }
                )
            batch_start_position = int(_coerce_dict(batch_rows[0].get("metadata")).get("task_sequence") or start_index + 1)
            batch_end_position = int(_coerce_dict(batch_rows[-1].get("metadata")).get("task_sequence") or start_index + len(batch_rows))
            return {
                "version": 1,
                "batch_contract": "knowledge_micro_batch_v1",
                "batch_task_count": len(batch_tasks),
                "batch_start_position": batch_start_position,
                "batch_end_position": batch_end_position,
                "task_total": total_task_count,
                "batch_remaining_after_batch": max(total_task_count - batch_end_position, 0),
                "draft_dir": str(_workspace_display_path(_current_batch_draft_dir())),
                "tasks": batch_tasks,
            }

        def _write_current_batch_sidecars(batch_payload, batch_feedback_lines=None):
            current_batch_path = _workspace_root() / CURRENT_BATCH_FILE_NAME
            brief_path = _current_batch_brief_path()
            feedback_path = _current_batch_feedback_path()
            if batch_payload is None:
                if current_batch_path.exists():
                    current_batch_path.unlink()
                brief_path.write_text(
                    "# Current Knowledge Batch\\n\\nNo current batch is active in this workspace.\\nEvery assigned task that the repo accepted has already been validated.\\n",
                    encoding="utf-8",
                )
                feedback_path.write_text(
                    "# Current Batch Feedback\\n\\n" + NO_CURRENT_BATCH_ACTIVE_TEXT + "\\n",
                    encoding="utf-8",
                )
                return
            current_batch_path.write_text(
                json.dumps(batch_payload, indent=2, sort_keys=True) + "\\n",
                encoding="utf-8",
            )
            batch_ids = [
                str(task.get("task_id") or "").strip()
                for task in (batch_payload.get("tasks") or [])
                if isinstance(task, dict) and str(task.get("task_id") or "").strip()
            ]
            first_task = next(
                (
                    dict(task)
                    for task in (batch_payload.get("tasks") or [])
                    if isinstance(task, dict)
                ),
                None,
            )
            brief_lines = [
                "# Current Knowledge Batch",
                "",
                f"Batch queue span: `{batch_payload.get('batch_start_position')}` to `{batch_payload.get('batch_end_position')}` of `{batch_payload.get('task_total')}`",
                f"Batch task ids: `{', '.join(batch_ids) or '[none]'}`",
                f"Batch task count: `{batch_payload.get('batch_task_count') or 0}`",
                f"Batch draft dir: `{batch_payload.get('draft_dir') or 'scratch/current_batch'}`",
                f"Remaining tasks after this batch: `{batch_payload.get('batch_remaining_after_batch') or 0}`",
                "",
                "Keep only durable cooking leverage. Technically true but low-value prose should stay `other`.",
                "Use `complete-batch`, edit the drafts under `scratch/current_batch/`, then `check-batch` and `install-batch`.",
                "Re-open `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md` after each install; open `current_batch.json` only when you need machine-readable paths or task rows.",
                "Single-task `CURRENT_TASK*` files remain available only for narrow recovery on the first active task.",
            ]
            if first_task is not None:
                brief_lines.extend(
                    [
                        "",
                        "First task to work now:",
                        f"- Task id: `{first_task.get('task_id') or '[unknown task]'}`",
                        f"- Draft path: `{first_task.get('draft_path') or '?'}`",
                        f"- Result path: `{first_task.get('result_path') or '?'}`",
                        f"- Owned packet ids: `{', '.join(first_task.get('owned_packet_ids') or []) or '[none]'}`",
                        "- Return `block_decisions` plus `idea_groups`; do not fall back to chunk-era result shapes.",
                    ]
                )
            brief_path.write_text("\\n".join(brief_lines) + "\\n", encoding="utf-8")
            if batch_feedback_lines is None:
                first_task = first_task or {}
                batch_feedback_lines = [
                    "# Current Batch Feedback",
                    "",
                    f"Batch task ids: `{', '.join(batch_ids) or '[none]'}`",
                    NO_REPO_WRITTEN_BATCH_FEEDBACK_TEXT,
                    ACTIVE_BATCH_ASSIGNMENT_TEXT,
                    "Every task still needs a packet-level judgment over `block_decisions` and `idea_groups` until the checker accepts it.",
                    "Current first task:",
                    f"- `{first_task.get('task_id') or '[unknown task]'}`",
                    f"- Draft: `{first_task.get('draft_path') or '?'}`",
                    f"- Hint: `{first_task.get('hint_path') or '?'}`",
                    f"- Input: `{first_task.get('input_path') or '?'}`",
                ]
                batch_feedback_lines.append(CHECK_BATCH_AFTER_EDIT_TEXT)
            feedback_path.write_text("\\n".join(batch_feedback_lines) + "\\n", encoding="utf-8")

        def _advance_sidecars_from_outputs():
            rows = _task_rows()
            current_index = 0
            while current_index < len(rows):
                row = rows[current_index]
                output_path = _resolve_result_path(row)
                if not output_path.exists():
                    break
                payload = _load_json(output_path)
                if not isinstance(payload, dict):
                    break
                errors, _metadata = _validate(row, _task_input_payload(row), payload)
                if errors:
                    break
                current_index += 1
            _write_current_batch_sidecars(_build_current_batch_payload(current_index))

        def _infer_task_id(payload):
            if not isinstance(payload, dict):
                return ""
            for key in ("packet_id", "bid"):
                value = str(payload.get(key) or "").strip()
                if value:
                    return value
            return ""

        def _normalize_text(value):
            return re.sub(r"\\s+", " ", str(value or "").strip()).lower()

        def _contains_grounded_text(value):
            return bool(re.search(r"[A-Za-z]", str(value or "")))

        def _looks_like_verbatim_surface_echo(normalized_body, normalized_surface, *, min_surface_chars, min_body_chars):
            if not normalized_body or not normalized_surface:
                return False
            if len(normalized_surface) < min_surface_chars:
                return False
            if len(normalized_body) < max(min_body_chars, int(len(normalized_surface) * 0.85)):
                return False
            return (
                normalized_body == normalized_surface
                or normalized_body in normalized_surface
                or normalized_surface in normalized_body
            )

        def _normalize_payload(payload):
            if "packet_id" in payload or "block_decisions" in payload or "idea_groups" in payload:
                working = json.loads(json.dumps(payload))
                for decision in working.get("block_decisions") or []:
                    if not isinstance(decision, dict):
                        continue
                    category = str(decision.get("category") or "").strip()
                    if category in SEMANTIC_CATEGORY_ALIAS_DEFAULTS:
                        normalized_category, default_reviewer = SEMANTIC_CATEGORY_ALIAS_DEFAULTS[category]
                        decision["category"] = normalized_category
                        reviewer_category = str(decision.get("reviewer_category") or "").strip()
                        if not reviewer_category:
                            decision["reviewer_category"] = default_reviewer
                return working
            if str(payload.get("v") or "").strip() != "3":
                raise ValueError("draft must use semantic packet keys or canonical packet keys")
            block_decisions = []
            for decision in payload.get("d") or []:
                if not isinstance(decision, dict):
                    raise ValueError("canonical block decisions must be objects")
                block_decisions.append(
                    {
                        "block_index": decision.get("i"),
                        "category": decision.get("c"),
                        "reviewer_category": decision.get("rc"),
                    }
                )
            idea_groups = []
            for group in payload.get("g") or []:
                if not isinstance(group, dict):
                    raise ValueError("canonical idea groups must be objects")
                snippets = []
                for snippet in group.get("s") or []:
                    if not isinstance(snippet, dict):
                        raise ValueError("canonical snippets must be objects")
                    snippets.append(
                        {
                            "body": snippet.get("b"),
                            "evidence": [
                                {
                                    "block_index": evidence.get("i"),
                                    "quote": evidence.get("q"),
                                }
                                for evidence in (snippet.get("e") or [])
                                if isinstance(evidence, dict)
                            ],
                        }
                    )
                idea_groups.append(
                    {
                        "group_id": group.get("gid"),
                        "topic_label": group.get("l"),
                        "block_indices": list(group.get("bi") or []),
                        "snippets": snippets,
                    }
                )
            return {
                "packet_id": payload.get("bid"),
                "block_decisions": block_decisions,
                "idea_groups": idea_groups,
            }

        def _scaffold(task_row, input_payload):
            block_decisions = []
            for block in input_payload.get("b") or []:
                if not isinstance(block, dict) or block.get("i") is None:
                    continue
                block_decisions.append(
                    {
                        "block_index": int(block.get("i")),
                        "category": "other",
                        "reviewer_category": "other",
                    }
                )
            return {
                "packet_id": str(task_row.get("task_id") or "").strip(),
                "block_decisions": block_decisions,
                "idea_groups": [],
            }

        def _validate(task_row, input_payload, payload):
            normalized = _normalize_payload(payload)
            errors = []
            metadata = {}
            task_id = str(task_row.get("task_id") or "").strip()
            packet_id = str(normalized.get("packet_id") or "").strip()
            if packet_id != task_id:
                errors.append("bundle_id_mismatch")

            expected_block_indices = [
                int(block.get("i"))
                for block in (input_payload.get("b") or [])
                if isinstance(block, dict) and block.get("i") is not None
            ]
            block_text_by_index = {
                int(block.get("i")): str(block.get("t") or "").strip()
                for block in (input_payload.get("b") or [])
                if isinstance(block, dict)
                and block.get("i") is not None
                and str(block.get("t") or "").strip()
            }
            all_allowed_block_indices = set(expected_block_indices)

            block_decisions = normalized.get("block_decisions")
            if not isinstance(block_decisions, list):
                raise ValueError("block_decisions must be a list")
            observed_block_indices = []
            seen_block_indices = set()
            decision_category_by_block = {}
            for decision in block_decisions:
                if not isinstance(decision, dict):
                    raise ValueError("block_decisions entries must be objects")
                block_index = int(decision.get("block_index"))
                category = str(decision.get("category") or "").strip()
                reviewer_category = str(decision.get("reviewer_category") or "").strip() or None
                if category not in ALLOWED_FINAL_CATEGORIES:
                    raise ValueError(f"invalid final category: {category!r}")
                if reviewer_category is not None and reviewer_category not in ALLOWED_REVIEWER_CATEGORIES:
                    raise ValueError(f"invalid reviewer category: {reviewer_category!r}")
                if category == "knowledge" and reviewer_category not in (None, "knowledge"):
                    raise ValueError("reviewer_category must be 'knowledge' when category is 'knowledge'")
                if category == "other" and reviewer_category == "knowledge":
                    raise ValueError("reviewer_category 'knowledge' is invalid when category is 'other'")
                if block_index in seen_block_indices:
                    raise ValueError(f"block_decisions repeats block_index {block_index}")
                seen_block_indices.add(block_index)
                observed_block_indices.append(block_index)
                decision_category_by_block[block_index] = category
                if block_index not in all_allowed_block_indices:
                    errors.append("unexpected_block_decisions")
            missing_block_indices = [
                block_index
                for block_index in expected_block_indices
                if block_index not in seen_block_indices
            ]
            if missing_block_indices:
                errors.append("missing_owned_block_decisions")
                metadata["missing_owned_block_indices"] = missing_block_indices
            if observed_block_indices != expected_block_indices and not missing_block_indices:
                errors.append("block_decision_order_mismatch")

            idea_groups = normalized.get("idea_groups")
            if not isinstance(idea_groups, list):
                raise ValueError("idea_groups must be a list")
            non_grounded_group_ids = []
            copied_quote_group_ids = []
            echoed_group_ids = []
            knowledge_group_count_by_block = {}
            group_contains_other_blocks = {}
            for group in idea_groups:
                if not isinstance(group, dict):
                    raise ValueError("idea_groups entries must be objects")
                group_id = str(group.get("group_id") or "").strip()
                topic_label = str(group.get("topic_label") or "").strip()
                block_indices = [int(value) for value in (group.get("block_indices") or [])]
                snippets = group.get("snippets")
                if not group_id:
                    raise ValueError("idea_groups.group_id is required")
                if not topic_label:
                    raise ValueError("idea_groups.topic_label is required")
                if not block_indices:
                    raise ValueError("idea_groups.block_indices must be non-empty")
                if len(set(block_indices)) != len(block_indices):
                    raise ValueError("idea_groups must not repeat block indices")
                if not isinstance(snippets, list) or not snippets:
                    raise ValueError("idea_groups.snippets must be a non-empty list")
                wrong_group_blocks = [
                    block_index
                    for block_index in block_indices
                    if decision_category_by_block.get(block_index) != "knowledge"
                ]
                if wrong_group_blocks:
                    errors.append("group_contains_other_block")
                    group_contains_other_blocks[group_id] = sorted(set(wrong_group_blocks))
                group_surface = " ".join(
                    block_text_by_index.get(block_index, "")
                    for block_index in block_indices
                ).strip()
                normalized_group_surface = _normalize_text(group_surface)
                for block_index in block_indices:
                    if decision_category_by_block.get(block_index) == "knowledge":
                        knowledge_group_count_by_block[block_index] = (
                            knowledge_group_count_by_block.get(block_index, 0) + 1
                        )
                for snippet in snippets:
                    if not isinstance(snippet, dict):
                        raise ValueError("snippets entries must be objects")
                    body = str(snippet.get("body") or "").strip()
                    evidence = snippet.get("evidence")
                    if not isinstance(evidence, list) or not evidence:
                        raise ValueError("snippet evidence must be non-empty")
                    if not _contains_grounded_text(body):
                        non_grounded_group_ids.append(group_id)
                    evidence_surface_parts = []
                    snippet_block_indices = []
                    for evidence_row in evidence:
                        if not isinstance(evidence_row, dict):
                            raise ValueError("evidence rows must be objects")
                        block_index = int(evidence_row.get("block_index"))
                        quote = str(evidence_row.get("quote") or "").strip()
                        if not quote:
                            raise ValueError("evidence quote is required")
                        if block_index not in all_allowed_block_indices:
                            errors.append("snippet_evidence_out_of_surface")
                        evidence_surface_parts.append(quote)
                        snippet_block_indices.append(block_index)
                    normalized_body = _normalize_text(body)
                    normalized_evidence_surface = _normalize_text(" ".join(evidence_surface_parts))
                    if _looks_like_verbatim_surface_echo(
                        normalized_body,
                        normalized_evidence_surface,
                        min_surface_chars=80,
                        min_body_chars=80,
                    ):
                        copied_quote_group_ids.append(group_id)
                    if _looks_like_verbatim_surface_echo(
                        normalized_body,
                        normalized_group_surface,
                        min_surface_chars=160,
                        min_body_chars=120,
                    ):
                        echoed_group_ids.append(group_id)

            knowledge_block_indices = [
                block_index
                for block_index in expected_block_indices
                if decision_category_by_block.get(block_index) == "knowledge"
            ]
            missing_group_blocks = [
                block_index
                for block_index in knowledge_block_indices
                if knowledge_group_count_by_block.get(block_index, 0) == 0
            ]
            duplicate_group_blocks = [
                block_index
                for block_index, count in sorted(knowledge_group_count_by_block.items())
                if count > 1
            ]
            if missing_group_blocks:
                errors.append("knowledge_block_missing_group")
                metadata["knowledge_blocks_missing_group"] = missing_group_blocks
            if duplicate_group_blocks:
                errors.append("knowledge_block_group_conflict")
                metadata["knowledge_blocks_with_multiple_groups"] = duplicate_group_blocks
            if group_contains_other_blocks:
                metadata["group_contains_other_blocks"] = group_contains_other_blocks
            if non_grounded_group_ids:
                errors.append("semantic_snippet_body_not_grounded_text")
                metadata["non_grounded_idea_group_ids"] = sorted(set(non_grounded_group_ids))
            if copied_quote_group_ids:
                errors.append("semantic_snippet_copies_evidence_quote")
                metadata["copied_quote_idea_group_ids"] = sorted(set(copied_quote_group_ids))
            if echoed_group_ids:
                errors.append("semantic_snippet_echoes_packet_surface")
                metadata["echoed_idea_group_ids"] = sorted(set(echoed_group_ids))
            return tuple(dict.fromkeys(errors)), metadata

        def _write_payload(payload, dest_path):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")

        def _trim_preview(value, max_chars=120):
            cleaned = re.sub(r"\\s+", " ", str(value or "").strip())
            if len(cleaned) <= max_chars:
                return cleaned
            return cleaned[: max_chars - 3].rstrip() + "..."

        def _render_error_help(errors, metadata=None):
            error_set = {str(error).strip() for error in errors if str(error).strip()}
            metadata = _coerce_dict(metadata)
            help_lines = []
            if "semantic_snippet_echoes_packet_surface" in error_set or "semantic_snippet_copies_evidence_quote" in error_set:
                help_lines.append(
                    "Keep each `evidence[].quote` verbatim, but rewrite `snippets[].body` into a shorter grounded claim in your own words."
                )
                for group_id in metadata.get("copied_quote_idea_group_ids") or []:
                    help_lines.append(
                        f"Idea group `{group_id}` copied too much evidence text. Keep the quote in `evidence`, but shorten the body."
                    )
                for group_id in metadata.get("echoed_idea_group_ids") or []:
                    help_lines.append(
                        f"Idea group `{group_id}` body is too close to the full owned packet surface. Leave the longer wording in evidence quotes only."
                    )
            if "semantic_snippet_body_not_grounded_text" in error_set:
                help_lines.append(
                    "Use plain-language snippet bodies that state a reusable claim supported by the evidence."
                )
            if "missing_owned_block_decisions" in error_set or "unexpected_block_decisions" in error_set:
                help_lines.append(
                    "Cover every owned block exactly once in top-level `block_decisions`, with no extras."
                )
            if "block_decision_order_mismatch" in error_set:
                help_lines.append(
                    "Keep `block_decisions` in the same order as the owned packet blocks."
                )
            if "knowledge_block_missing_group" in error_set:
                help_lines.append(
                    "Every block marked `knowledge` must appear in exactly one `idea_groups[*].block_indices` list."
                )
            if "knowledge_block_group_conflict" in error_set:
                help_lines.append(
                    "Do not place the same knowledge block into more than one idea group."
                )
            if "group_contains_other_block" in error_set:
                help_lines.append(
                    "Only blocks marked `knowledge` may appear in `idea_groups[*].block_indices`."
                )
            if not help_lines:
                help_lines.append(
                    "Re-open `OUTPUT_CONTRACT.md`, compare against `examples/`, and fix only the fields named in the validator errors."
                )
            help_lines.append("Run `check` again and wait for `OK ...` before `install`.")
            return list(dict.fromkeys(help_lines))

        def _format_invalid_message(task_id, draft_name, errors, metadata=None):
            lines = [f"INVALID {task_id} ({draft_name}): {', '.join(errors)}"]
            lines.extend(f"- {line}" for line in _render_error_help(errors, metadata))
            return "\\n".join(lines) + "\\n"

        def _remaining_after_current_text(task_row):
            metadata = _coerce_dict(task_row.get("metadata"))
            task_sequence = int(metadata.get("task_sequence") or 0)
            task_total = int(metadata.get("task_total") or 0)
            if task_sequence > 0 and task_total > 0:
                return f"Remaining tasks after this one: `{max(task_total - task_sequence, 0)}`."
            return "Remaining tasks after this one: unknown."

        def _pending_feedback_lines(task_row, draft_path):
            task_id = str((task_row or {}).get("task_id") or "").strip() or "[unknown task]"
            return [
                "# Current Task Feedback",
                "",
                f"Task id: `{task_id}`",
                NO_REPO_WRITTEN_FEEDBACK_TEXT,
                _remaining_after_current_text(task_row),
                ACTIVE_ASSIGNMENT_TEXT,
                f"Expected draft path: `{draft_path}`.",
                CHECK_CURRENT_AFTER_EDIT_TEXT,
            ]

        def _valid_feedback_lines(task_row, *, draft_path, result_path):
            task_id = str((task_row or {}).get("task_id") or "").strip() or "[unknown task]"
            return [
                "# Current Task Feedback",
                "",
                f"Task id: `{task_id}`",
                VALIDATION_STATUS_OK_TEXT,
                f"Draft path: `{draft_path}`",
                f"Install target: `{result_path}`",
                VALIDATOR_ACCEPTED_TEXT,
                INSTALL_CURRENT_READY_TEXT,
                REOPEN_AFTER_INSTALL_TEXT,
                CONTINUE_IMMEDIATELY_TEXT,
                QUEUE_COMPLETE_TEXT,
            ]

        def _write_current_feedback(task_row, *, draft_path, errors=None, validation_metadata=None, valid=None):
            display_draft_path = str(draft_path)
            if valid is None:
                lines = _pending_feedback_lines(task_row, display_draft_path)
            elif valid:
                lines = _valid_feedback_lines(
                    task_row,
                    draft_path=display_draft_path,
                    result_path=_resolve_result_path(task_row).relative_to(_workspace_root()),
                )
            else:
                task_id = str((task_row or {}).get("task_id") or "").strip() or "[unknown task]"
                lines = [
                    "# Current Task Feedback",
                    "",
                    f"Task id: `{task_id}`",
                ]
                lines.extend(
                    [
                        "Validation status: FAILED.",
                        "",
                        "Validator errors:",
                        *[f"- `{error}`" for error in (errors or ())],
                        "",
                        "How to fix it:",
                        *[f"- {line}" for line in _render_error_help(errors or (), validation_metadata)],
                    ]
                )
            _current_feedback_path().write_text("\\n".join(lines) + "\\n", encoding="utf-8")

        def _next_task_row():
            current = _current_task()
            rows = _task_rows()
            if current is None:
                return rows[0] if rows else None
            current_task_id = str(current.get("task_id") or "").strip()
            for index, row in enumerate(rows):
                if str(row.get("task_id") or "").strip() != current_task_id:
                    continue
                if index + 1 < len(rows):
                    return rows[index + 1]
                return None
            return rows[0] if rows else None

        def _command_overview(_args):
            sys.stdout.write(_render_overview())
            return 0

        def _render_overview():
            rows = _task_rows()
            current = _current_task()
            current_task_id = str((current or {}).get("task_id") or "").strip()
            if not rows:
                return "No assigned tasks.\\n"
            lines = []
            if current_task_id:
                lines.append(f"current_task: {current_task_id}")
            for index, row in enumerate(rows, start=1):
                task_id = str(row.get("task_id") or "").strip() or "[unknown task]"
                metadata = _coerce_dict(row.get("metadata"))
                prefix = "* " if task_id == current_task_id else "  "
                lines.append(
                    f"{prefix}{index}. {task_id} | input={metadata.get('input_path') or '?'} | hint={metadata.get('hint_path') or '?'} | result={metadata.get('result_path') or '?'}"
                )
            return "\\n".join(lines) + "\\n"

        def _command_show(args):
            row = _task_row(args.task_id)
            input_payload = _task_input_payload(row)
            metadata = _coerce_dict(row.get("metadata"))
            packet_summaries = []
            for packet in _packet_rows(input_payload):
                packet_id = str(packet.get("bid") or "").strip() or "[unknown packet]"
                block_indices = [
                    int(block.get("i"))
                    for block in packet.get("b") or []
                    if isinstance(block, dict) and block.get("i") is not None
                ]
                if block_indices:
                    packet_summaries.append(f"{packet_id}:{block_indices[0]}..{block_indices[-1]}")
                else:
                    packet_summaries.append(f"{packet_id}:[no blocks]")
            sys.stdout.write(
                "\\n".join(
                    [
                        f"task_id: {row.get('task_id')}",
                        f"parent_shard_id: {row.get('parent_shard_id') or row.get('task_id')}",
                        f"task_sequence: {metadata.get('task_sequence') or '?'} / {metadata.get('task_total') or '?'}",
                        f"input_path: {metadata.get('input_path') or '?'}",
                        f"hint_path: {metadata.get('hint_path') or '?'}",
                        f"result_path: {metadata.get('result_path') or '?'}",
                        f"owned_packet_ids: {', '.join(_owned_packet_ids(input_payload)) or '[none]'}",
                        f"packet_blocks: {', '.join(packet_summaries) or '[none]'}",
                    ]
                )
                + "\\n"
            )
            return 0

        def _command_current(_args):
            brief_path = _current_brief_path()
            if brief_path.exists():
                sys.stdout.write(brief_path.read_text(encoding="utf-8"))
                return 0
            row = _current_task_required()
            sys.stdout.write(f"task_id: {row.get('task_id')}\\n")
            return 0

        def _command_current_batch(_args):
            brief_path = _current_batch_brief_path()
            if brief_path.exists():
                sys.stdout.write(brief_path.read_text(encoding="utf-8"))
                return 0
            payload = _current_batch_required()
            sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\\n")
            return 0

        def _command_next(_args):
            row = _next_task_row()
            if row is None:
                sys.stdout.write("No later task is queued after the current task.\\n")
                return 0
            sys.stdout.write(f"{row.get('task_id')}\\n")
            return 0

        def _command_next_batch(_args):
            batch_payload = _current_batch()
            rows = _task_rows()
            if not batch_payload or not rows:
                sys.stdout.write("No later batch is queued after the current batch.\\n")
                return 0
            current_ids = [
                str(task.get("task_id") or "").strip()
                for task in (batch_payload.get("tasks") or [])
                if isinstance(task, dict) and str(task.get("task_id") or "").strip()
            ]
            if not current_ids:
                sys.stdout.write("No later batch is queued after the current batch.\\n")
                return 0
            last_index = 0
            for index, row in enumerate(rows):
                if str(row.get("task_id") or "").strip() == current_ids[-1]:
                    last_index = index + 1
                    break
            next_batch = _build_current_batch_payload(last_index)
            if next_batch is None:
                sys.stdout.write("No later batch is queued after the current batch.\\n")
                return 0
            next_ids = [
                str(task.get("task_id") or "").strip()
                for task in (next_batch.get("tasks") or [])
                if isinstance(task, dict) and str(task.get("task_id") or "").strip()
            ]
            sys.stdout.write("\\n".join(next_ids) + "\\n")
            return 0

        def _command_show_batch(_args):
            payload = _current_batch_required()
            sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\\n")
            return 0

        def _command_scaffold(args):
            row = _task_row(args.task_id)
            payload = _scaffold(row, _task_input_payload(row))
            rendered = json.dumps(payload, indent=2, sort_keys=True) + "\\n"
            if args.dest:
                dest = Path(args.dest)
                if not dest.is_absolute():
                    dest = _workspace_root() / dest
                _write_payload(payload, dest)
                sys.stdout.write(f"wrote scaffold to {dest.relative_to(_workspace_root()) if dest.is_relative_to(_workspace_root()) else dest}\\n")
            else:
                sys.stdout.write(rendered)
            return 0

        def _command_complete_current(args):
            row = _current_task_required()
            payload = _scaffold(row, _task_input_payload(row))
            dest = Path(args.dest) if args.dest else _current_task_draft_path()
            if not dest.is_absolute():
                dest = _workspace_root() / dest
            _write_payload(payload, dest)
            _write_current_feedback(row, draft_path=dest.relative_to(_workspace_root()) if dest.is_relative_to(_workspace_root()) else dest)
            sys.stdout.write(
                f"wrote current scaffold to {dest.relative_to(_workspace_root()) if dest.is_relative_to(_workspace_root()) else dest}\\n"
            )
            return 0

        def _command_complete_batch(_args):
            batch_payload = _current_batch_required()
            written_paths = []
            for task in batch_payload.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id") or "").strip()
                if not task_id:
                    continue
                row = _task_row(task_id)
                dest = _current_batch_task_draft_path(task_id)
                _write_payload(_scaffold(row, _task_input_payload(row)), dest)
                written_paths.append(str(_workspace_display_path(dest)))
            _write_current_batch_sidecars(batch_payload)
            sys.stdout.write(
                f"wrote {len(written_paths)} batch scaffold(s) under {batch_payload.get('draft_dir') or 'scratch/current_batch'}\\n"
            )
            return 0

        def _checked_result(args):
            draft_path = Path(args.json_path)
            if not draft_path.is_absolute():
                draft_path = _workspace_root() / draft_path
            payload = _load_json(draft_path)
            if not isinstance(payload, dict):
                raise ValueError("draft must contain one JSON object")
            task_id = _infer_task_id(payload)
            if not task_id:
                raise ValueError("draft must declare `packet_id` or `bid`")
            row = _task_row(task_id)
            errors, metadata = _validate(row, _task_input_payload(row), payload)
            return draft_path, row, payload, errors, metadata

        def _checked_current_result(args):
            row = _current_task_required()
            draft_path = Path(args.json_path) if args.json_path else _current_task_draft_path()
            if not draft_path.is_absolute():
                draft_path = _workspace_root() / draft_path
            payload = _load_json(draft_path)
            if not isinstance(payload, dict):
                raise ValueError("draft must contain one JSON object")
            task_id = _infer_task_id(payload)
            if task_id and task_id != str(row.get("task_id") or "").strip():
                raise ValueError(
                    f"draft packet_id {task_id!r} does not match current task {row.get('task_id')!r}"
                )
            errors, metadata = _validate(row, _task_input_payload(row), payload)
            return draft_path, row, payload, errors, metadata

        def _command_check(args):
            draft_path, row, _payload, errors, metadata = _checked_result(args)
            if errors:
                sys.stderr.write(
                    _format_invalid_message(row.get("task_id"), draft_path.name, errors, metadata)
                )
                return 1
            sys.stdout.write(f"OK {row.get('task_id')} ({draft_path.name})\\n")
            return 0

        def _command_check_current(args):
            draft_path, row, _payload, errors, metadata = _checked_current_result(args)
            display_path = draft_path.relative_to(_workspace_root()) if draft_path.is_relative_to(_workspace_root()) else draft_path
            if errors:
                _write_current_feedback(
                    row,
                    draft_path=display_path,
                    errors=errors,
                    validation_metadata=metadata,
                    valid=False,
                )
                sys.stderr.write(
                    _format_invalid_message(row.get("task_id"), draft_path.name, errors, metadata)
                )
                return 1
            _write_current_feedback(row, draft_path=display_path, valid=True)
            sys.stdout.write(f"OK {row.get('task_id')} ({draft_path.name})\\n")
            return 0

        def _command_check_batch(_args):
            batch_payload = _current_batch_required()
            missing_task_ids = []
            invalid_rows = []
            validated_rows = []
            for task in batch_payload.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id") or "").strip()
                if not task_id:
                    continue
                draft_path = _current_batch_task_draft_path(task_id)
                if not draft_path.exists():
                    missing_task_ids.append(task_id)
                    continue
                payload = _load_json(draft_path)
                row = _task_row(task_id)
                errors, metadata = _validate(row, _task_input_payload(row), payload)
                if errors:
                    invalid_rows.append((task_id, draft_path, payload, errors, metadata))
                else:
                    validated_rows.append((task_id, draft_path))
            if not missing_task_ids and not invalid_rows:
                _write_current_batch_sidecars(
                    batch_payload,
                    batch_feedback_lines=[
                        "# Current Batch Feedback",
                        "",
                        f"Batch task ids: `{', '.join(task_id for task_id, _draft_path in validated_rows)}`",
                        BATCH_VALIDATION_STATUS_OK_TEXT,
                        BATCH_VALIDATOR_ACCEPTED_TEXT,
                        INSTALL_BATCH_READY_TEXT,
                        REOPEN_BATCH_AFTER_INSTALL_TEXT,
                        CONTINUE_BATCH_IMMEDIATELY_TEXT,
                        QUEUE_COMPLETE_TEXT,
                    ],
                )
                sys.stdout.write(
                    f"OK batch ({', '.join(task_id for task_id, _draft_path in validated_rows)})\\n"
                )
                return 0
            feedback_lines = [
                "# Current Batch Feedback",
                "",
                f"Batch task ids: `{', '.join(str(task.get('task_id') or '').strip() for task in (batch_payload.get('tasks') or []) if isinstance(task, dict) and str(task.get('task_id') or '').strip())}`",
                "Batch validation status: FAILED.",
            ]
            if missing_task_ids:
                feedback_lines.extend(["", "Missing batch drafts:"])
                feedback_lines.extend(f"- `{task_id}`" for task_id in missing_task_ids)
            if invalid_rows:
                task_id, draft_path, _payload, errors, metadata = invalid_rows[0]
                feedback_lines.extend(
                    [
                        "",
                        f"First failing task: `{task_id}`",
                        "Validator errors:",
                        *[f"- `{error}`" for error in errors],
                        "",
                        "How to fix it:",
                        *[f"- {line}" for line in _render_error_help(errors, metadata)],
                        "",
                        f"Current failing draft: `{_workspace_display_path(draft_path)}`",
                    ]
                )
            _write_current_batch_sidecars(batch_payload, batch_feedback_lines=feedback_lines)
            if invalid_rows:
                task_id, draft_path, _payload, errors, metadata = invalid_rows[0]
                sys.stderr.write(_format_invalid_message(task_id, draft_path.name, errors, metadata))
            else:
                sys.stderr.write(
                    "batch drafts are incomplete: "
                    + ", ".join(missing_task_ids)
                    + "\\n"
                )
            return 1

        def _command_install(args):
            draft_path, row, payload, errors, metadata = _checked_result(args)
            if errors:
                sys.stderr.write(
                    _format_invalid_message(row.get("task_id"), draft_path.name, errors, metadata)
                )
                return 1
            result_path = _resolve_result_path(row)
            _write_payload(payload, result_path)
            sys.stdout.write(
                f"installed {draft_path.name} -> {result_path.relative_to(_workspace_root())}\\n"
            )
            return 0

        def _command_install_current(args):
            draft_path, row, payload, errors, metadata = _checked_current_result(args)
            display_path = draft_path.relative_to(_workspace_root()) if draft_path.is_relative_to(_workspace_root()) else draft_path
            if errors:
                _write_current_feedback(
                    row,
                    draft_path=display_path,
                    errors=errors,
                    validation_metadata=metadata,
                    valid=False,
                )
                sys.stderr.write(
                    _format_invalid_message(row.get("task_id"), draft_path.name, errors, metadata)
                )
                return 1
            result_path = _resolve_result_path(row)
            _write_payload(payload, result_path)
            _write_current_feedback(row, draft_path=display_path, valid=True)
            sys.stdout.write(
                f"installed {draft_path.name} -> {result_path.relative_to(_workspace_root())}\\n"
            )
            sys.stdout.write(
                INSTALL_CURRENT_SUCCESS_NOTICE + "\\n"
            )
            _advance_sidecars_from_outputs()
            return 0

        def _command_install_batch(_args):
            batch_payload = _current_batch_required()
            installed_task_ids = []
            for task in batch_payload.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id") or "").strip()
                if not task_id:
                    continue
                draft_path = _current_batch_task_draft_path(task_id)
                if not draft_path.exists():
                    break
                payload = _load_json(draft_path)
                row = _task_row(task_id)
                errors, metadata = _validate(row, _task_input_payload(row), payload)
                if errors:
                    _write_current_batch_sidecars(
                        batch_payload,
                        batch_feedback_lines=[
                            "# Current Batch Feedback",
                            "",
                            f"First failing task: `{task_id}`",
                            "Batch validation status: FAILED.",
                            "Validator errors:",
                            *[f"- `{error}`" for error in errors],
                            "",
                            "How to fix it:",
                            *[f"- {line}" for line in _render_error_help(errors, metadata)],
                        ],
                    )
                    if installed_task_ids:
                        _advance_sidecars_from_outputs()
                        sys.stdout.write(
                            f"installed {len(installed_task_ids)} batch task(s) before stopping at {task_id}\\n"
                        )
                        sys.stdout.write(INSTALL_BATCH_SUCCESS_NOTICE + "\\n")
                        return 0
                    sys.stderr.write(_format_invalid_message(task_id, draft_path.name, errors, metadata))
                    return 1
                result_path = _resolve_result_path(row)
                _write_payload(payload, result_path)
                installed_task_ids.append(task_id)
            _advance_sidecars_from_outputs()
            sys.stdout.write(
                f"installed {len(installed_task_ids)} batch task(s)\\n"
            )
            sys.stdout.write(INSTALL_BATCH_SUCCESS_NOTICE + "\\n")
            return 0

        def _command_explain_failure(_args):
            feedback_path = _current_feedback_path()
            if not feedback_path.exists():
                row = _current_task()
                _write_current_feedback(
                    row or {},
                    draft_path=_current_task_draft_path().relative_to(_workspace_root()),
                )
            sys.stdout.write(feedback_path.read_text(encoding="utf-8"))
            return 0

        def build_parser():
            parser = argparse.ArgumentParser(description="Knowledge workspace helper")
            subparsers = parser.add_subparsers(dest="command", required=True)

            current_batch = subparsers.add_parser("current-batch", help="Show the repo-written current batch brief")
            current_batch.set_defaults(func=_command_current_batch)

            complete_batch = subparsers.add_parser("complete-batch", help="Write the default scaffolds for the current batch")
            complete_batch.set_defaults(func=_command_complete_batch)

            check_batch = subparsers.add_parser("check-batch", help="Validate the current batch drafts")
            check_batch.set_defaults(func=_command_check_batch)

            install_batch = subparsers.add_parser("install-batch", help="Validate and install the current batch drafts")
            install_batch.set_defaults(func=_command_install_batch)

            explain_failure = subparsers.add_parser("explain-failure", help="Show the current task feedback sidecar")
            explain_failure.set_defaults(func=_command_explain_failure)

            debug = subparsers.add_parser(
                "debug",
                help="Recovery/debug helper surface for task-level inspection and fallback commands",
            )
            debug_subparsers = debug.add_subparsers(dest="debug_command", required=True)

            overview = debug_subparsers.add_parser("overview", help="Show the ordered task queue")
            overview.set_defaults(func=_command_overview)

            current = debug_subparsers.add_parser("current", help="Show the repo-written current task brief")
            current.set_defaults(func=_command_current)

            next_batch = debug_subparsers.add_parser("next-batch", help="Show the next queued batch task ids")
            next_batch.set_defaults(func=_command_next_batch)

            next_task = debug_subparsers.add_parser("next", help="Show the next queued task id after the current task")
            next_task.set_defaults(func=_command_next)

            show_batch = debug_subparsers.add_parser("show-batch", help="Show the current batch payload")
            show_batch.set_defaults(func=_command_show_batch)

            show = debug_subparsers.add_parser("show", help="Show one task row")
            show.add_argument("task_id")
            show.set_defaults(func=_command_show)

            scaffold = debug_subparsers.add_parser("scaffold", help="Write a semantic task scaffold")
            scaffold.add_argument("task_id")
            scaffold.add_argument("--dest")
            scaffold.set_defaults(func=_command_scaffold)

            complete_current = debug_subparsers.add_parser("complete-current", help="Write the default scaffold for the current task")
            complete_current.add_argument("--dest")
            complete_current.set_defaults(func=_command_complete_current)

            check = debug_subparsers.add_parser("check", help="Validate a draft task result")
            check.add_argument("json_path")
            check.set_defaults(func=_command_check)

            check_current = debug_subparsers.add_parser("check-current", help="Validate the current task draft")
            check_current.add_argument("json_path", nargs="?")
            check_current.set_defaults(func=_command_check_current)

            install = debug_subparsers.add_parser("install", help="Validate and install a draft task result")
            install.add_argument("json_path")
            install.set_defaults(func=_command_install)

            install_current = debug_subparsers.add_parser("install-current", help="Validate and install the current task draft")
            install_current.add_argument("json_path", nargs="?")
            install_current.set_defaults(func=_command_install_current)
            return parser

        def main(argv=None):
            parser = build_parser()
            args = parser.parse_args(argv)
            try:
                return int(args.func(args))
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"ERROR: {exc}\\n")
                return 2

        if __name__ == "__main__":
            raise SystemExit(main())
        """
        )
        .lstrip()
        .replace("{no_current_batch_active_text}", no_current_batch_active_text)
        .replace("{active_batch_assignment_text}", active_batch_assignment_text)
        .replace("{no_repo_written_batch_feedback_text}", no_repo_written_batch_feedback_text)
        .replace("{check_batch_after_edit_text}", check_batch_after_edit_text)
        .replace("{batch_validation_status_ok_text}", batch_validation_status_ok_text)
        .replace("{batch_validator_accepted_text}", batch_validator_accepted_text)
        .replace("{install_batch_ready_text}", install_batch_ready_text)
        .replace("{reopen_batch_after_install_text}", reopen_batch_after_install_text)
        .replace("{continue_batch_immediately_text}", continue_batch_immediately_text)
        .replace("{install_batch_success_notice}", install_batch_success_notice)
        .replace("{no_current_task_active_text}", no_current_task_active_text)
        .replace("{active_assignment_text}", active_assignment_text)
        .replace("{no_repo_written_feedback_text}", no_repo_written_feedback_text)
        .replace("{check_current_after_edit_text}", check_current_after_edit_text)
        .replace("{validation_status_ok_text}", validation_status_ok_text)
        .replace("{validator_accepted_text}", validator_accepted_text)
        .replace("{install_current_ready_text}", install_current_ready_text)
        .replace("{reopen_after_install_text}", reopen_after_install_text)
        .replace("{continue_immediately_text}", continue_immediately_text)
        .replace("{queue_complete_text}", queue_complete_text)
        .replace("{install_current_success_notice}", install_current_success_notice)
        .replace("{allowed_final_categories}", allowed_final_categories)
        .replace("{allowed_reviewer_categories}", allowed_reviewer_categories)
        .replace("{allowed_reason_codes}", allowed_reason_codes)
    )


def _resolve_sample_task(
    tasks: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    best_candidate: tuple[int, dict[str, Any], dict[str, Any], str] | None = None
    for row in tasks:
        if not isinstance(row, Mapping):
            continue
        task_row = dict(row)
        metadata = _coerce_dict(task_row.get("metadata"))
        input_path = str(metadata.get("input_path") or "").strip()
        input_payload = task_row.get("input_payload")
        resolved_input_payload: dict[str, Any] | None = None
        if isinstance(input_payload, Mapping):
            resolved_input_payload = dict(input_payload)
        elif input_path:
            try:
                payload = _load_json(Path(input_path))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, Mapping):
                resolved_input_payload = dict(payload)
        if resolved_input_payload is None:
            continue
        sample_packet_id, sample_score = _select_representative_sample_packet_id(
            resolved_input_payload
        )
        if not sample_packet_id:
            continue
        candidate = (
            sample_score,
            task_row,
            resolved_input_payload,
            sample_packet_id,
        )
        if best_candidate is None or candidate[0] > best_candidate[0]:
            best_candidate = candidate
    if best_candidate is not None:
        return best_candidate[1], best_candidate[2], best_candidate[3]
    fallback_payload = _built_in_sample_input_payload()
    return (
        {
            "task_id": "knowledge-task-example",
            "metadata": {},
        },
        fallback_payload,
        str(fallback_payload.get("bid") or "knowledge-packet-example"),
    )


def _built_in_sample_input_payload() -> dict[str, Any]:
    return {
        "v": "1",
        "bid": "knowledge-task-example",
        "b": [
            {
                "i": 1,
                "t": (
                    "Keep the heat gentle and stir steadily so milk sauces stay smooth "
                    "instead of tightening into curds."
                ),
            }
        ],
    }


def _select_representative_sample_packet_id(
    input_payload: Mapping[str, Any],
) -> tuple[str, int]:
    packet_id = str(input_payload.get("bid") or input_payload.get("packet_id") or "").strip()
    evidence_rows, source_text = _sample_evidence_rows(input_payload)
    if not packet_id or not evidence_rows or len(source_text) < 80:
        return "", -1
    block_rows = [
        dict(block)
        for block in (input_payload.get("b") or [])
        if isinstance(block, Mapping)
    ]
    non_heading_block_count = sum(
        1 for block in block_rows if not _looks_like_heading_block(block)
    )
    total_word_count = sum(
        len(str(block.get("t") or "").split())
        for block in block_rows
        if str(block.get("t") or "").strip()
    )
    has_sentence_punctuation = any(
        any(marker in str(block.get("t") or "") for marker in (".", ";", ":"))
        for block in block_rows
    )
    score = (
        min(len(source_text), 220)
        + non_heading_block_count * 80
        + min(total_word_count, 40)
        + (25 if has_sentence_punctuation else 0)
    )
    return packet_id, score


def _sample_evidence_rows(input_payload: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    block_rows = [
        dict(block)
        for block in (input_payload or {}).get("b") or []
        if isinstance(block, Mapping) and block.get("i") is not None
    ]
    preferred_rows = [
        block
        for block in block_rows
        if str(block.get("t") or "").strip() and not _looks_like_heading_block(block)
    ]
    candidate_rows = preferred_rows or block_rows
    evidence_rows: list[dict[str, Any]] = []
    total_chars = 0
    for block in candidate_rows:
        quote = str(block.get("t") or "").strip()
        if not quote:
            continue
        evidence_rows.append(
            {
                "block_index": int(block.get("i")),
                "quote": quote,
            }
        )
        total_chars += len(quote)
        if total_chars >= 90 or len(evidence_rows) >= 2:
            break
    source_text = " ".join(
        str(row.get("quote") or "").strip()
        for row in evidence_rows
        if str(row.get("quote") or "").strip()
    ).strip()
    return evidence_rows, source_text


def _looks_like_heading_block(block: Mapping[str, Any]) -> bool:
    text = str(block.get("t") or "").strip()
    if not text:
        return True
    word_count = len(text.split())
    alpha_chars = "".join(ch for ch in text if ch.isalpha())
    if block.get("hl") is not None and word_count <= 12:
        return True
    if word_count <= 5:
        return True
    if alpha_chars and alpha_chars.upper() == alpha_chars and word_count <= 12:
        return True
    lowered = text.lower()
    return bool(
        word_count <= 8
        and lowered.startswith(
            (
                "contents",
                "praise for",
                "acknowledg",
                "introduction",
                "about the author",
            )
        )
    )


def _resolve_result_path(*, workspace_root: Path, task_row: Mapping[str, Any]) -> Path:
    metadata = _coerce_dict(task_row.get("metadata"))
    result_path = str(metadata.get("result_path") or "").strip()
    if not result_path:
        raise ValueError(f"task {task_row.get('task_id')!r} is missing metadata.result_path")
    return Path(workspace_root) / result_path


def _infer_task_id(payload: Mapping[str, Any]) -> str:
    for key in ("packet_id", "bid"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _packet_rows(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    packets = input_payload.get("p")
    if isinstance(packets, list):
        return [dict(packet) for packet in packets if isinstance(packet, Mapping)]
    blocks = input_payload.get("b")
    if not isinstance(blocks, list):
        return []
    packet_id = str(input_payload.get("bid") or input_payload.get("packet_id") or "packet").strip()
    return [{"bid": packet_id, "b": [dict(block) for block in blocks if isinstance(block, Mapping)]}]


def _owned_packet_ids(input_payload: Mapping[str, Any]) -> list[str]:
    return [
        str(packet.get("bid") or "").strip()
        for packet in _packet_rows(input_payload)
        if str(packet.get("bid") or "").strip()
    ]


def _render_validation_error_help(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None = None,
    input_payload: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> list[str]:
    error_set = {
        str(error).strip()
        for error in validation_errors
        if str(error).strip()
    }
    metadata = _coerce_dict(validation_metadata)
    help_lines: list[str] = []
    if (
        "semantic_snippet_echoes_packet_surface" in error_set
        or "semantic_snippet_copies_evidence_quote" in error_set
    ):
        help_lines.append(
            "Keep each `evidence[].quote` verbatim, but rewrite `snippets[].body` into a shorter grounded claim in your own words."
        )
        help_lines.extend(
            _render_snippet_copy_detail_lines(
                validation_metadata=metadata,
                input_payload=input_payload,
                payload=payload,
            )
        )
    if "semantic_snippet_body_not_grounded_text" in error_set:
        non_grounded_group_ids = [
            str(group_id).strip()
            for group_id in (metadata.get("non_grounded_idea_group_ids") or [])
            if str(group_id).strip()
        ]
        if non_grounded_group_ids:
            help_lines.append(
                "These idea groups need real grounded prose in `snippets[].body`: "
                + ", ".join(f"`{group_id}`" for group_id in non_grounded_group_ids)
                + "."
            )
        else:
            help_lines.append(
                "Use plain-language snippet bodies that make a reusable claim supported by the evidence rows."
            )
    if "missing_owned_block_decisions" in error_set or "unexpected_block_decisions" in error_set:
        help_lines.append(
            "Cover every owned block exactly once in top-level `block_decisions`, with no extras."
        )
    if "block_decision_order_mismatch" in error_set:
        help_lines.append(
            "Keep `block_decisions` in the same order as the owned packet blocks."
        )
    if "knowledge_block_missing_group" in error_set:
        help_lines.append(
            "Every block marked `knowledge` must appear in exactly one `idea_groups[*].block_indices` list."
        )
    if "knowledge_block_group_conflict" in error_set:
        help_lines.append(
            "Do not place the same knowledge block into more than one idea group."
        )
    if "group_contains_other_block" in error_set:
        help_lines.append(
            "Only blocks marked `knowledge` may appear in `idea_groups[*].block_indices`."
        )
    if "snippet_evidence_out_of_surface" in error_set:
        help_lines.append("Do not cite block indices outside the task's owned surface.")
    if "bundle_id_mismatch" in error_set:
        help_lines.append("`packet_id` must exactly match the current task row's `task_id`.")
    if not help_lines:
        help_lines.append(
            "Re-open `OUTPUT_CONTRACT.md`, compare against `examples/`, and fix only the fields named in the validator errors."
        )
    help_lines.append("Run `check` again and wait for `OK ...` before `install`.")
    return list(dict.fromkeys(line for line in help_lines if line.strip()))


def _short_grounded_snippet(source_text: str) -> str:
    cleaned = " ".join(str(source_text or "").strip().split())
    if not cleaned:
        return "Use low heat to prevent curdling."
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    candidate = sentence or cleaned
    if _normalize_for_guidance(candidate) == _normalize_for_guidance(cleaned):
        words = candidate.split()
        if len(words) >= 10:
            candidate = " ".join(words[: max(6, min(11, len(words) // 2 + 1))])
        elif len(cleaned) > 72:
            candidate = cleaned[:72].rstrip(" ,;:")
    if len(candidate) > 90:
        candidate = candidate[:87].rstrip(" ,;:")
    if not candidate.endswith("."):
        candidate += "."
    return candidate


def _normalize_for_guidance(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
