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
from .phase_worker_runtime import ShardManifestEntryV1

_WORKER_SCRIPT_NAME = "knowledge_worker.py"
_DEFAULT_SCAFFOLD_REASON_CODE = "review_not_completed"
_CURRENT_TASK_BRIEF_FILE_NAME = "CURRENT_TASK.md"
_CURRENT_TASK_FEEDBACK_FILE_NAME = "CURRENT_TASK_FEEDBACK.md"
_NO_CURRENT_TASK_ACTIVE_TEXT = "No current task is active. The queue is complete."
_ACTIVE_ASSIGNMENT_TEXT = (
    "This worker assignment is still active until the repo removes `current_task.json` "
    "and says the queue is complete."
)
_NO_REPO_WRITTEN_FEEDBACK_TEXT = "No repo-written validation feedback exists yet for this task."
_CHECK_CURRENT_AFTER_EDIT_TEXT = (
    "Run `python3 tools/knowledge_worker.py check-current` after editing the current draft."
)
_VALIDATION_STATUS_OK_TEXT = "Validation status: OK."
_VALIDATOR_ACCEPTED_TEXT = "The validator accepted this task packet."
_INSTALL_CURRENT_READY_TEXT = (
    "You may run `python3 tools/knowledge_worker.py install-current` to write the final result path."
)
_REOPEN_AFTER_INSTALL_TEXT = (
    "After `install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and "
    "`CURRENT_TASK_FEEDBACK.md`."
)
_CONTINUE_IMMEDIATELY_TEXT = (
    "If another task becomes active, continue with that task immediately. Do not ask for "
    "permission to continue or stop at this checkpoint while later tasks remain."
)
_QUEUE_COMPLETE_TEXT = "If not, the queue is complete."
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
    chunk_knowledge_cue_by_id = _coerce_dict(metadata.get("chunk_knowledge_cue_by_id"))
    strong_knowledge_cue = any(
        bool(chunk_knowledge_cue_by_id.get(chunk_id))
        for chunk_id in owned_ids
    )
    inventory_metadata = dict(metadata)
    inventory_metadata["strong_knowledge_cue"] = strong_knowledge_cue
    inventory_metadata["owned_chunk_count"] = len(owned_ids)
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


def render_current_task_brief_text(
    *,
    workspace_root: Path,
    task_row: Mapping[str, Any] | None,
) -> str:
    if task_row is None:
        return (
            "# Current Knowledge Task\n\n"
            "No current task is active in this workspace.\n"
            "Every assigned task packet that the repo accepted has already been validated.\n"
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
    for chunk in _chunk_rows(input_payload):
        chunk_id = str(chunk.get("cid") or "").strip() or "[unknown chunk]"
        block_indices = [
            int(block.get("i"))
            for block in chunk.get("b") or []
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        if not block_indices:
            block_spans.append(f"{chunk_id}:[no blocks]")
            continue
        block_spans.append(f"{chunk_id}:{block_indices[0]}..{block_indices[-1]}")
    strong_knowledge_cue = bool(metadata.get("strong_knowledge_cue"))
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
        f"Owned chunk ids: `{', '.join(owned_ids) or '[none]'}`",
        f"Input file: `{metadata.get('input_path') or '?'}`",
        f"Hint file: `{metadata.get('hint_path') or '?'}`",
        f"Result file: `{metadata.get('result_path') or '?'}`",
        f"Owned block spans: `{', '.join(block_spans) or '[none]'}`",
        (
            f"Remaining tasks after this one: `{remaining_after_current}`"
            if remaining_after_current is not None
            else "Remaining tasks after this one: unknown"
        ),
        (
            "Strong cue: yes. An all-`other` answer is high risk here unless the owned text is clearly not reusable knowledge."
            if strong_knowledge_cue
            else "Strong cue: no. It is acceptable to keep everything `other` if the owned text is clearly non-knowledge."
        ),
        "",
        "This assignment stays active until the repo removes `current_task.json` and rewrites the current-task sidecars to say the queue is complete.",
        "A successful `install-current` is only a handoff to the next repo-owned current task, not a stopping point.",
        "",
        "Recommended loop:",
        "1. Read the hint and input files named above.",
        "2. Run `python3 tools/knowledge_worker.py complete-current` to write the default draft to `scratch/current_task.json`.",
        "3. Edit the draft until the snippet bodies are short grounded claims, not copied evidence surfaces.",
        "4. Run `python3 tools/knowledge_worker.py check-current`.",
        "5. Run `python3 tools/knowledge_worker.py install-current` only after `check-current` says OK.",
        "6. After `install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`. If another task becomes active, continue with that task immediately. Do not stop to summarize progress or ask for permission to continue while later tasks remain.",
        "",
        "Do not process later tasks before this task passes the repo-owned checker.",
    ]
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
    lines = [
        f"task_id: {task_row['task_id']}",
        f"parent_shard_id: {task_row.get('parent_shard_id') or task_row['task_id']}",
        f"task_sequence: {metadata.get('task_sequence') or '?'} / {metadata.get('task_total') or '?'}",
        f"input_path: {metadata.get('input_path') or '?'}",
        f"hint_path: {metadata.get('hint_path') or '?'}",
        f"result_path: {metadata.get('result_path') or '?'}",
        f"owned_chunk_ids: {', '.join(_owned_chunk_ids(input_payload)) or '[none]'}",
    ]
    block_summary = []
    for chunk in _chunk_rows(input_payload):
        chunk_id = str(chunk.get("cid") or "").strip() or "[unknown chunk]"
        block_indices = [
            int(block.get("i"))
            for block in chunk.get("b") or []
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        if block_indices:
            block_summary.append(f"{chunk_id}:{block_indices[0]}..{block_indices[-1]}")
        else:
            block_summary.append(f"{chunk_id}:[no blocks]")
    lines.append(f"chunk_blocks: {', '.join(block_summary) or '[none]'}")
    return "\n".join(lines) + "\n"


def scaffold_task_payload(*, task_row: Mapping[str, Any], input_payload: Mapping[str, Any]) -> dict[str, Any]:
    task_id = str(task_row.get("task_id") or "").strip()
    chunk_results = []
    for chunk in _chunk_rows(input_payload):
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        block_decisions = []
        for block in chunk.get("b") or []:
            if not isinstance(block, Mapping) or block.get("i") is None:
                continue
            block_decisions.append(
                {
                    "block_index": int(block.get("i")),
                    "category": "other",
                    "reviewer_category": "other",
                }
            )
        chunk_results.append(
            {
                "chunk_id": chunk_id,
                "is_useful": False,
                "block_decisions": block_decisions,
                "snippets": [],
                "reason_code": _DEFAULT_SCAFFOLD_REASON_CODE,
            }
        )
    return {
        "packet_id": task_id,
        "chunk_results": chunk_results,
    }


def build_knowledge_workspace_contract_examples(
    *,
    tasks: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    sample_task_row, sample_input_payload, sample_chunk_id = _resolve_sample_task(tasks)
    valid_example = scaffold_task_payload(
        task_row=sample_task_row,
        input_payload=sample_input_payload,
    )
    first_valid_chunk = next(
        (
            chunk_result
            for chunk_result in (valid_example.get("chunk_results") or [])
            if isinstance(chunk_result, dict)
            and str(chunk_result.get("chunk_id") or "").strip() == sample_chunk_id
        ),
        None,
    )
    if isinstance(first_valid_chunk, dict):
        chunk_row = next(
            (
                chunk
                for chunk in _chunk_rows(sample_input_payload)
                if str(chunk.get("cid") or "").strip() == sample_chunk_id
            ),
            None,
        )
        evidence_rows, source_text = _sample_evidence_rows(chunk_row)
        evidence_block_indices = {
            int(row.get("block_index"))
            for row in evidence_rows
            if row.get("block_index") is not None
        }
        if evidence_rows and evidence_block_indices:
            valid_example_body = _short_grounded_snippet(source_text)
            first_valid_chunk["is_useful"] = True
            first_valid_chunk["block_decisions"] = [
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
                for block in (chunk_row or {}).get("b") or []
                if isinstance(block, Mapping) and block.get("i") is not None
            ]
            first_valid_chunk["snippets"] = [
                {
                    "body": valid_example_body,
                    "evidence": evidence_rows,
                }
            ]
            first_valid_chunk["reason_code"] = "grounded_useful"
    invalid_example = json.loads(json.dumps(valid_example))
    first_chunk = next(
        (
            chunk_result
            for chunk_result in (invalid_example.get("chunk_results") or [])
            if isinstance(chunk_result, dict)
            and str(chunk_result.get("chunk_id") or "").strip() == sample_chunk_id
        ),
        None,
    )
    if isinstance(first_chunk, dict):
        chunk_row = next(
            (
                chunk
                for chunk in _chunk_rows(sample_input_payload)
                if str(chunk.get("cid") or "").strip() == sample_chunk_id
            ),
            None,
        )
        evidence_rows, source_text = _sample_evidence_rows(chunk_row)
        evidence_block_indices = {
            int(row.get("block_index"))
            for row in evidence_rows
            if row.get("block_index") is not None
        }
        if evidence_rows and evidence_block_indices:
            first_chunk["is_useful"] = True
            first_chunk["block_decisions"] = [
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
                for block in (chunk_row or {}).get("b") or []
                if isinstance(block, Mapping) and block.get("i") is not None
            ]
            first_chunk["snippets"] = [
                {
                    "body": source_text,
                    "evidence": evidence_rows,
                }
            ]
            first_chunk["reason_code"] = "grounded_useful"
    return {
        "valid_semantic_packet.json": valid_example,
        "invalid_echo_packet.json": invalid_example,
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
    return "\n".join(
        [
            "# Knowledge Workspace Output Contract",
            "",
            "Write one semantic packet-result JSON object per task to `out/<task_id>.json`.",
            "",
            "Required top-level keys:",
            "- `packet_id`: must equal the task row `task_id` exactly.",
            "- `chunk_results`: one row per owned chunk in task order and no extras.",
            "",
            "Per chunk-result row:",
            "- `chunk_id`: the owned chunk id from `in/<task_id>.json`.",
            "- `is_useful`: `true` only when the chunk keeps at least one `knowledge` block and at least one grounded snippet.",
            "- `block_decisions`: cover every owned block index exactly once and in order.",
            "- `snippets`: grounded reusable claims only; each snippet needs evidence rows with `block_index` plus verbatim `quote`.",
            "- Optional `reason_code`: a short internal note such as `grounded_useful` or `all_other`.",
            "",
            "Category rules:",
            "- Final `category` values are only `knowledge` or `other`.",
            "- Optional `reviewer_category` values are `knowledge`, `chapter_taxonomy`, `decorative_heading`, `front_matter`, `toc_navigation`, `endorsement_or_marketing`, `memoir_or_scene_setting`, `reference_back_matter`, or `other`.",
            "- If final `category` is `knowledge`, `reviewer_category` must also be `knowledge`.",
            "",
            "Snippet rules:",
            "- Good snippet: a short grounded claim such as `Use low heat to prevent curdling.` supported by one or two short evidence quotes.",
            "- Bad snippet: a whole-block dump, a full-chunk echo, or a long stitched quote list copied from the evidence surface.",
            "",
            "Workflow:",
            "- Start from `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`.",
            "- Use `python3 tools/knowledge_worker.py scaffold <task_id> --dest scratch/<task_id>.json` if you want a prefilled envelope.",
            "- Run `python3 tools/knowledge_worker.py check <json_path>` before every final install step; copied evidence text in `snippets[].body` is invalid.",
            "- A task is not finished until `check` passes. Direct writes to `out/<task_id>.json` without a passing `check` are incomplete work.",
            "- Run `python3 tools/knowledge_worker.py install <json_path>` only after `check` says OK.",
            "- The lower-level `scaffold`, `check`, and `install` verbs remain available for targeted debugging.",
            "",
            "Valid example:",
            valid_example,
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
    return check_result


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

    if "semantic_snippet_echoes_full_chunk" in error_set:
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
        non_grounded_chunk_ids = [
            str(chunk_id).strip()
            for chunk_id in (metadata.get("non_grounded_snippet_chunk_ids") or [])
            if str(chunk_id).strip()
        ]
        if non_grounded_chunk_ids:
            help_lines.append(
                "These chunks need real grounded prose in `snippets[].body`: "
                + ", ".join(f"`{chunk_id}`" for chunk_id in non_grounded_chunk_ids)
                + "."
            )
        else:
            help_lines.append(
                "Use plain-language snippet bodies that state a reusable claim supported by the evidence."
            )
    if "missing_owned_chunk_results" in error_set or "unexpected_chunk_results" in error_set:
        help_lines.append(
            "Return exactly one `chunk_results` row for each owned chunk in the input file, in order and with no extras."
        )
    if "chunk_result_order_mismatch" in error_set:
        help_lines.append(
            "Keep `chunk_results` in the same order as the owned chunks in the input payload."
        )
    if "block_decision_coverage_mismatch" in error_set:
        help_lines.append(
            "Cover every owned block exactly once in `block_decisions`, using the input order."
        )
    if "snippet_evidence_wrong_chunk_surface" in error_set:
        help_lines.append(
            "Each snippet may cite only block indices from its own chunk result."
        )
    if "snippet_evidence_out_of_surface" in error_set:
        help_lines.append(
            "Do not cite block indices outside the task's owned surface."
        )
    if "bundle_id_mismatch" in error_set:
        help_lines.append(
            "`packet_id` must exactly match the current task row's `task_id`."
        )
    if "semantic_all_false_empty_shard" in error_set:
        help_lines.append(
            "This packet has strong knowledge cues. Keep at least one `knowledge` block and one grounded snippet unless the owned text is clearly non-knowledge."
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
    chunk_results_by_id = {
        str(chunk_result.get("cid") or "").strip(): chunk_result
        for chunk_result in _canonical_chunk_results(canonical_payload)
        if str(chunk_result.get("cid") or "").strip()
    }
    source_text_by_chunk_id = {
        str(chunk.get("cid") or "").strip(): " ".join(
            str(block.get("t") or "").strip()
            for block in chunk.get("b") or []
            if isinstance(block, Mapping) and str(block.get("t") or "").strip()
        ).strip()
        for chunk in _chunk_rows(input_payload or {})
        if str(chunk.get("cid") or "").strip()
    }

    lines: list[str] = []
    evidence_surface_rows = metadata.get("evidence_surface_echoes_by_chunk_id")
    if isinstance(evidence_surface_rows, Mapping):
        for chunk_id, details in evidence_surface_rows.items():
            chunk_id_text = str(chunk_id).strip()
            chunk_result = chunk_results_by_id.get(chunk_id_text) or {}
            snippets = chunk_result.get("s") or []
            for detail in details or []:
                if not isinstance(detail, Mapping):
                    continue
                snippet_index = int(detail.get("snippet_index") or 0)
                snippet_row = (
                    snippets[snippet_index]
                    if isinstance(snippets, list) and 0 <= snippet_index < len(snippets)
                    else {}
                )
                evidence_rows = [
                    evidence
                    for evidence in (snippet_row.get("e") or [])
                    if isinstance(evidence, Mapping)
                ]
                block_indices = [
                    int(value)
                    for value in (detail.get("block_indices") or [])
                    if value is not None
                ]
                quote_preview = _trim_preview(
                    " ".join(
                        str(evidence.get("q") or "").strip()
                        for evidence in evidence_rows
                        if str(evidence.get("q") or "").strip()
                    )
                )
                lines.append(
                    "Chunk "
                    f"`{chunk_id_text}` snippet `{snippet_index}` copied evidence"
                    + (
                        f" from block(s) `{', '.join(str(value) for value in block_indices)}`"
                        if block_indices
                        else ""
                    )
                    + (
                        f": `{quote_preview}`. Keep that quote in `evidence`, but shorten the body."
                        if quote_preview
                        else ". Keep the evidence quote, but shorten the body."
                    )
                )
    echoed_chunk_ids = [
        str(chunk_id).strip()
        for chunk_id in (metadata.get("echoed_full_chunk_ids") or [])
        if str(chunk_id).strip()
    ]
    for chunk_id in echoed_chunk_ids:
        source_preview = _trim_preview(source_text_by_chunk_id.get(chunk_id) or "")
        line = (
            f"Chunk `{chunk_id}` body is too close to the full owned chunk surface."
        )
        if source_preview:
            line += f" Source surface: `{source_preview}`."
        line += " Leave the longer wording in evidence quotes only and keep the body to one short claim."
        lines.append(line)
    return list(dict.fromkeys(line for line in lines if line.strip()))


def _canonical_chunk_results(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    raw_rows = payload.get("r")
    if isinstance(raw_rows, list):
        return [dict(row) for row in raw_rows if isinstance(row, Mapping)]
    raw_semantic_rows = payload.get("chunk_results")
    if not isinstance(raw_semantic_rows, list):
        return []
    canonical_rows: list[dict[str, Any]] = []
    for row in raw_semantic_rows:
        if not isinstance(row, Mapping):
            continue
        canonical_rows.append(
            {
                "cid": row.get("chunk_id"),
                "s": [
                    {
                        "b": snippet.get("body"),
                        "e": [
                            {
                                "i": evidence.get("block_index"),
                                "q": evidence.get("quote"),
                            }
                            for evidence in (snippet.get("evidence") or [])
                            if isinstance(evidence, Mapping)
                        ],
                    }
                    for snippet in (row.get("snippets") or [])
                    if isinstance(snippet, Mapping)
                ],
            }
        )
    return canonical_rows


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
    chunk_rows = _chunk_rows(input_payload)
    ordered_chunk_ids = _owned_chunk_ids(input_payload)
    if ordered_chunk_ids:
        metadata.setdefault("ordered_chunk_ids", ordered_chunk_ids)
    chunk_block_indices_by_id: dict[str, list[int]] = {}
    owned_block_indices: list[int] = []
    for chunk in chunk_rows:
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        block_indices = [
            int(block.get("i"))
            for block in chunk.get("b") or []
            if isinstance(block, Mapping) and block.get("i") is not None
        ]
        chunk_block_indices_by_id[chunk_id] = block_indices
        owned_block_indices.extend(block_indices)
    if chunk_block_indices_by_id:
        metadata.setdefault("chunk_block_indices_by_id", chunk_block_indices_by_id)
    if owned_block_indices:
        metadata.setdefault("owned_block_indices", owned_block_indices)
    return ShardManifestEntryV1(
        shard_id=task_id,
        owned_ids=tuple(ordered_chunk_ids),
        input_payload=dict(input_payload),
        metadata=metadata,
    )


def render_knowledge_worker_script() -> str:
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

        ALLOWED_FINAL_CATEGORIES = ("knowledge", "other")
        ALLOWED_REVIEWER_CATEGORIES = (
            "knowledge",
            "chapter_taxonomy",
            "decorative_heading",
            "front_matter",
            "toc_navigation",
            "endorsement_or_marketing",
            "memoir_or_scene_setting",
            "reference_back_matter",
            "other",
        )
        SEMANTIC_CATEGORY_ALIAS_DEFAULTS = {
            "content": ("knowledge", "knowledge"),
            "noise": ("other", "endorsement_or_marketing"),
            "heading": ("other", "decorative_heading"),
        }
        DEFAULT_SCAFFOLD_REASON_CODE = "review_not_completed"
        CURRENT_TASK_BRIEF_FILE_NAME = "CURRENT_TASK.md"
        CURRENT_TASK_FEEDBACK_FILE_NAME = "CURRENT_TASK_FEEDBACK.md"
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

        def _current_task_required():
            payload = _current_task()
            if payload is None:
                raise ValueError("no current task is active in this workspace")
            return payload

        def _current_task_draft_path():
            return _workspace_root() / "scratch" / "current_task.json"

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

        def _chunk_rows(input_payload):
            chunks = input_payload.get("c")
            if not isinstance(chunks, list):
                return []
            return [dict(chunk) for chunk in chunks if isinstance(chunk, dict)]

        def _owned_chunk_ids(input_payload):
            return [
                str(chunk.get("cid") or "").strip()
                for chunk in _chunk_rows(input_payload)
                if str(chunk.get("cid") or "").strip()
            ]

        def _resolve_result_path(task_row):
            metadata = _coerce_dict(task_row.get("metadata"))
            result_path = str(metadata.get("result_path") or "").strip()
            if not result_path:
                raise ValueError(f"task {task_row.get('task_id')!r} is missing metadata.result_path")
            return _workspace_root() / result_path

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

        def _copied_surface_covers_most_of_chunk(*, copied_surface_text, full_chunk_text):
            if not copied_surface_text or not full_chunk_text:
                return False
            if len(full_chunk_text) < 160:
                return False
            return len(copied_surface_text) >= max(120, int(len(full_chunk_text) * 0.85))

        def _chunk_block_texts_by_id(input_payload):
            resolved = {}
            for chunk in _chunk_rows(input_payload):
                chunk_id = str(chunk.get("cid") or "").strip()
                if not chunk_id:
                    continue
                block_texts = {}
                for block in chunk.get("b") or []:
                    if not isinstance(block, dict) or block.get("i") is None:
                        continue
                    text = str(block.get("t") or "").strip()
                    if text:
                        block_texts[int(block.get("i"))] = text
                if block_texts:
                    resolved[chunk_id] = block_texts
            return resolved

        def _normalize_payload(payload):
            if "packet_id" in payload:
                working = json.loads(json.dumps(payload))
                for chunk_result in working.get("chunk_results") or []:
                    if not isinstance(chunk_result, dict):
                        continue
                    for decision in chunk_result.get("block_decisions") or []:
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
            if str(payload.get("v") or "").strip() != "2":
                raise ValueError("draft must use semantic keys or canonical bundle keys")
            chunk_results = []
            for chunk_result in payload.get("r") or []:
                if not isinstance(chunk_result, dict):
                    raise ValueError("canonical chunk results must be objects")
                block_decisions = []
                for decision in chunk_result.get("d") or []:
                    if not isinstance(decision, dict):
                        raise ValueError("canonical block decisions must be objects")
                    block_decisions.append(
                        {
                            "block_index": decision.get("i"),
                            "category": decision.get("c"),
                            "reviewer_category": decision.get("rc"),
                        }
                    )
                snippets = []
                for snippet in chunk_result.get("s") or []:
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
                chunk_results.append(
                    {
                        "chunk_id": chunk_result.get("cid"),
                        "is_useful": chunk_result.get("u"),
                        "block_decisions": block_decisions,
                        "snippets": snippets,
                    }
                )
            return {
                "packet_id": payload.get("bid"),
                "chunk_results": chunk_results,
            }

        def _scaffold(task_row, input_payload):
            chunk_results = []
            for chunk in _chunk_rows(input_payload):
                chunk_id = str(chunk.get("cid") or "").strip()
                if not chunk_id:
                    continue
                block_decisions = []
                for block in chunk.get("b") or []:
                    if not isinstance(block, dict) or block.get("i") is None:
                        continue
                    block_decisions.append(
                        {
                            "block_index": int(block.get("i")),
                            "category": "other",
                            "reviewer_category": "other",
                        }
                    )
                chunk_results.append(
                    {
                        "chunk_id": chunk_id,
                        "is_useful": False,
                        "block_decisions": block_decisions,
                        "snippets": [],
                        "reason_code": DEFAULT_SCAFFOLD_REASON_CODE,
                    }
                )
            return {
                "packet_id": str(task_row.get("task_id") or "").strip(),
                "chunk_results": chunk_results,
            }

        def _validate(task_row, input_payload, payload):
            normalized = _normalize_payload(payload)
            errors = []
            metadata = {}
            task_id = str(task_row.get("task_id") or "").strip()
            packet_id = str(normalized.get("packet_id") or "").strip()
            if packet_id != task_id:
                errors.append("bundle_id_mismatch")
            chunk_rows = _chunk_rows(input_payload)
            expected_chunk_ids = [
                str(chunk.get("cid") or "").strip()
                for chunk in chunk_rows
                if str(chunk.get("cid") or "").strip()
            ]
            chunk_results = normalized.get("chunk_results")
            if not isinstance(chunk_results, list):
                raise ValueError("chunk_results must be a list")
            observed_chunk_ids = []
            chunk_results_by_id = {}
            for row in chunk_results:
                if not isinstance(row, dict):
                    raise ValueError("chunk_results entries must be objects")
                chunk_id = str(row.get("chunk_id") or "").strip()
                if not chunk_id:
                    raise ValueError("chunk_result.chunk_id is required")
                if chunk_id in chunk_results_by_id:
                    raise ValueError(f"chunk_results repeats chunk_id {chunk_id!r}")
                observed_chunk_ids.append(chunk_id)
                chunk_results_by_id[chunk_id] = row
            missing_chunk_ids = [chunk_id for chunk_id in expected_chunk_ids if chunk_id not in chunk_results_by_id]
            unexpected_chunk_ids = [chunk_id for chunk_id in observed_chunk_ids if chunk_id not in expected_chunk_ids]
            if missing_chunk_ids:
                errors.append("missing_owned_chunk_results")
            if unexpected_chunk_ids:
                errors.append("unexpected_chunk_results")
            if not missing_chunk_ids and not unexpected_chunk_ids and observed_chunk_ids != expected_chunk_ids:
                errors.append("chunk_result_order_mismatch")

            chunk_block_texts = _chunk_block_texts_by_id(input_payload)
            all_allowed_block_indices = {
                int(block_index)
                for block_texts in chunk_block_texts.values()
                for block_index in block_texts
            }
            non_grounded_chunk_ids = []
            echoed_chunk_ids = []
            evidence_surface_echoes_by_chunk_id = {}

            for chunk in chunk_rows:
                chunk_id = str(chunk.get("cid") or "").strip()
                if not chunk_id or chunk_id not in chunk_results_by_id:
                    continue
                row = chunk_results_by_id[chunk_id]
                block_decisions = row.get("block_decisions")
                snippets = row.get("snippets")
                if not isinstance(block_decisions, list):
                    raise ValueError("block_decisions must be a list")
                if not isinstance(snippets, list):
                    raise ValueError("snippets must be a list")
                expected_block_indices = [
                    int(block.get("i"))
                    for block in chunk.get("b") or []
                    if isinstance(block, dict) and block.get("i") is not None
                ]
                seen_block_indices = set()
                observed_block_indices = []
                knowledge_decision_count = 0
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
                    if category == "knowledge":
                        knowledge_decision_count += 1
                if observed_block_indices != expected_block_indices:
                    errors.append("block_decision_coverage_mismatch")
                for block_index in observed_block_indices:
                    if block_index not in all_allowed_block_indices:
                        errors.append("block_decision_out_of_surface")
                        break

                snippet_count = 0
                copied_block_indices = set()
                copied_snippet_count = 0
                source_text = " ".join(
                    str(chunk_block_texts.get(chunk_id, {}).get(block_index) or "").strip()
                    for block_index in expected_block_indices
                    if str(chunk_block_texts.get(chunk_id, {}).get(block_index) or "").strip()
                ).strip()
                normalized_source_text = _normalize_text(source_text)
                for snippet_index, snippet in enumerate(snippets):
                    if not isinstance(snippet, dict):
                        raise ValueError("snippets entries must be objects")
                    body = str(snippet.get("body") or "").strip()
                    evidence = snippet.get("evidence")
                    if not isinstance(evidence, list) or not evidence:
                        raise ValueError("snippet evidence must be non-empty")
                    if not _contains_grounded_text(body):
                        non_grounded_chunk_ids.append(chunk_id)
                    evidence_surface_parts = []
                    snippet_block_indices = set()
                    for evidence_row in evidence:
                        if not isinstance(evidence_row, dict):
                            raise ValueError("evidence rows must be objects")
                        block_index = int(evidence_row.get("block_index"))
                        quote = str(evidence_row.get("quote") or "").strip()
                        if not quote:
                            raise ValueError("evidence quote is required")
                        if block_index not in all_allowed_block_indices:
                            errors.append("snippet_evidence_out_of_surface")
                        if block_index not in expected_block_indices:
                            errors.append("snippet_evidence_wrong_chunk_surface")
                        evidence_surface_parts.append(quote)
                        snippet_block_indices.add(block_index)
                    snippet_count += 1
                    normalized_body = _normalize_text(body)
                    normalized_evidence_surface = _normalize_text(" ".join(evidence_surface_parts))
                    if (
                        normalized_source_text
                        and len(normalized_source_text) >= 160
                        and len(normalized_body) >= max(120, int(len(normalized_source_text) * 0.85))
                        and sorted(snippet_block_indices) == expected_block_indices
                        and _looks_like_verbatim_surface_echo(
                            normalized_body,
                            normalized_source_text,
                            min_surface_chars=160,
                            min_body_chars=120,
                        )
                    ):
                        echoed_chunk_ids.append(chunk_id)
                    if _looks_like_verbatim_surface_echo(
                        normalized_body,
                        normalized_evidence_surface,
                        min_surface_chars=80,
                        min_body_chars=80,
                    ):
                        echoed_chunk_ids.append(chunk_id)
                        copied_snippet_count += 1
                        copied_block_indices.update(snippet_block_indices)
                        evidence_surface_echoes_by_chunk_id.setdefault(chunk_id, []).append(
                            {
                                "snippet_index": snippet_index,
                                "block_indices": sorted(snippet_block_indices),
                                "quote_preview": _trim_preview(" ".join(evidence_surface_parts)),
                            }
                        )
                copied_surface_text = " ".join(
                    str(chunk_block_texts.get(chunk_id, {}).get(block_index) or "").strip()
                    for block_index in expected_block_indices
                    if block_index in copied_block_indices and str(chunk_block_texts.get(chunk_id, {}).get(block_index) or "").strip()
                ).strip()
                if (
                    copied_snippet_count >= 2
                    and _copied_surface_covers_most_of_chunk(
                        copied_surface_text=_normalize_text(copied_surface_text),
                        full_chunk_text=normalized_source_text,
                    )
                ):
                    echoed_chunk_ids.append(chunk_id)

                is_useful = bool(row.get("is_useful"))
                if is_useful and knowledge_decision_count <= 0:
                    raise ValueError("useful chunk results must include at least one knowledge block decision")
                if is_useful and snippet_count <= 0:
                    raise ValueError("useful chunk results must include at least one snippet")
                if not is_useful and knowledge_decision_count > 0:
                    raise ValueError("non-useful chunk results must not include knowledge block decisions")
                if not is_useful and snippet_count > 0:
                    raise ValueError("non-useful chunk results must not include snippets")

            if non_grounded_chunk_ids:
                errors.append("semantic_snippet_body_not_grounded_text")
                metadata["non_grounded_chunk_ids"] = sorted(set(non_grounded_chunk_ids))
            if echoed_chunk_ids:
                errors.append("semantic_snippet_echoes_full_chunk")
                metadata["echoed_full_chunk_ids"] = sorted(set(echoed_chunk_ids))
            if evidence_surface_echoes_by_chunk_id:
                metadata["evidence_surface_echoes_by_chunk_id"] = evidence_surface_echoes_by_chunk_id
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
            if "semantic_snippet_echoes_full_chunk" in error_set:
                help_lines.append(
                    "Keep each `evidence[].quote` verbatim, but rewrite `snippets[].body` into a shorter grounded claim in your own words."
                )
                for chunk_id, details in (_coerce_dict(metadata.get("evidence_surface_echoes_by_chunk_id"))).items():
                    for detail in details or []:
                        if not isinstance(detail, dict):
                            continue
                        snippet_index = int(detail.get("snippet_index") or 0)
                        block_indices = [
                            int(value)
                            for value in (detail.get("block_indices") or [])
                            if value is not None
                        ]
                        quote_preview = str(detail.get("quote_preview") or "").strip()
                        help_lines.append(
                            "Chunk "
                            f"`{chunk_id}` snippet `{snippet_index}` copied evidence"
                            + (
                                f" from block(s) `{', '.join(str(value) for value in block_indices)}`"
                                if block_indices
                                else ""
                            )
                            + (
                                f": `{quote_preview}`. Keep that quote in `evidence`, but shorten the body."
                                if quote_preview
                                else ". Keep the evidence quote, but shorten the body."
                            )
                        )
                for chunk_id in metadata.get("echoed_full_chunk_ids") or []:
                    help_lines.append(
                        f"Chunk `{chunk_id}` body is too close to the full owned chunk surface. Leave the longer wording in evidence quotes only."
                    )
            if "semantic_snippet_body_not_grounded_text" in error_set:
                help_lines.append(
                    "Use plain-language snippet bodies that state a reusable claim supported by the evidence."
                )
            if "missing_owned_chunk_results" in error_set or "unexpected_chunk_results" in error_set:
                help_lines.append(
                    "Return exactly one `chunk_results` row for each owned chunk in the input file, in order and with no extras."
                )
            if "chunk_result_order_mismatch" in error_set:
                help_lines.append(
                    "Keep `chunk_results` in the same order as the owned chunks in the input payload."
                )
            if "block_decision_coverage_mismatch" in error_set:
                help_lines.append(
                    "Cover every owned block exactly once in `block_decisions`, using the input order."
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
            chunk_summaries = []
            for chunk in _chunk_rows(input_payload):
                chunk_id = str(chunk.get("cid") or "").strip() or "[unknown chunk]"
                block_indices = [
                    int(block.get("i"))
                    for block in chunk.get("b") or []
                    if isinstance(block, dict) and block.get("i") is not None
                ]
                if block_indices:
                    chunk_summaries.append(f"{chunk_id}:{block_indices[0]}..{block_indices[-1]}")
                else:
                    chunk_summaries.append(f"{chunk_id}:[no blocks]")
            sys.stdout.write(
                "\\n".join(
                    [
                        f"task_id: {row.get('task_id')}",
                        f"parent_shard_id: {row.get('parent_shard_id') or row.get('task_id')}",
                        f"task_sequence: {metadata.get('task_sequence') or '?'} / {metadata.get('task_total') or '?'}",
                        f"input_path: {metadata.get('input_path') or '?'}",
                        f"hint_path: {metadata.get('hint_path') or '?'}",
                        f"result_path: {metadata.get('result_path') or '?'}",
                        f"owned_chunk_ids: {', '.join(_owned_chunk_ids(input_payload)) or '[none]'}",
                        f"chunk_blocks: {', '.join(chunk_summaries) or '[none]'}",
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

        def _command_next(_args):
            row = _next_task_row()
            if row is None:
                sys.stdout.write("No later task is queued after the current task.\\n")
                return 0
            sys.stdout.write(f"{row.get('task_id')}\\n")
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

            overview = subparsers.add_parser("overview", help="Show the ordered task queue")
            overview.set_defaults(func=_command_overview)

            current = subparsers.add_parser("current", help="Show the repo-written current task brief")
            current.set_defaults(func=_command_current)

            next_task = subparsers.add_parser("next", help="Show the next queued task id after the current task")
            next_task.set_defaults(func=_command_next)

            show = subparsers.add_parser("show", help="Show one task row")
            show.add_argument("task_id")
            show.set_defaults(func=_command_show)

            scaffold = subparsers.add_parser("scaffold", help="Write a semantic packet scaffold")
            scaffold.add_argument("task_id")
            scaffold.add_argument("--dest")
            scaffold.set_defaults(func=_command_scaffold)

            complete_current = subparsers.add_parser("complete-current", help="Write the default scaffold for the current task")
            complete_current.add_argument("--dest")
            complete_current.set_defaults(func=_command_complete_current)

            check = subparsers.add_parser("check", help="Validate a draft packet")
            check.add_argument("json_path")
            check.set_defaults(func=_command_check)

            check_current = subparsers.add_parser("check-current", help="Validate the current task draft")
            check_current.add_argument("json_path", nargs="?")
            check_current.set_defaults(func=_command_check_current)

            install = subparsers.add_parser("install", help="Validate and install a draft packet")
            install.add_argument("json_path")
            install.set_defaults(func=_command_install)

            install_current = subparsers.add_parser("install-current", help="Validate and install the current task draft")
            install_current.add_argument("json_path", nargs="?")
            install_current.set_defaults(func=_command_install_current)

            explain_failure = subparsers.add_parser("explain-failure", help="Show the current task feedback sidecar")
            explain_failure.set_defaults(func=_command_explain_failure)
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
        sample_chunk_id, sample_score = _select_representative_sample_chunk_id(
            resolved_input_payload
        )
        if not sample_chunk_id:
            continue
        candidate = (
            sample_score,
            task_row,
            resolved_input_payload,
            sample_chunk_id,
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
        str(((fallback_payload.get("c") or [{}])[0]).get("cid") or "knowledge-chunk-example"),
    )


def _built_in_sample_input_payload() -> dict[str, Any]:
    return {
        "v": "2",
        "bid": "knowledge-task-example",
        "c": [
            {
                "cid": "knowledge-chunk-example",
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
        ],
    }


def _select_representative_sample_chunk_id(
    input_payload: Mapping[str, Any],
) -> tuple[str, int]:
    best_chunk_id = ""
    best_score = -1
    for chunk in _chunk_rows(input_payload):
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        evidence_rows, source_text = _sample_evidence_rows(chunk)
        if not evidence_rows or len(source_text) < 80:
            continue
        block_rows = [
            dict(block)
            for block in (chunk.get("b") or [])
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
        if best_chunk_id and score <= best_score:
            continue
        best_chunk_id = chunk_id
        best_score = score
    return best_chunk_id, best_score


def _sample_evidence_rows(chunk_row: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    block_rows = [
        dict(block)
        for block in (chunk_row or {}).get("b") or []
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


def _chunk_rows(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    chunks = input_payload.get("c")
    if not isinstance(chunks, list):
        return []
    return [dict(chunk) for chunk in chunks if isinstance(chunk, Mapping)]


def _owned_chunk_ids(input_payload: Mapping[str, Any]) -> list[str]:
    return [
        str(chunk.get("cid") or "").strip()
        for chunk in _chunk_rows(input_payload)
        if str(chunk.get("cid") or "").strip()
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
    if "semantic_snippet_echoes_full_chunk" in error_set:
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
        non_grounded_chunk_ids = [
            str(chunk_id).strip()
            for chunk_id in (metadata.get("non_grounded_snippet_chunk_ids") or [])
            if str(chunk_id).strip()
        ]
        if non_grounded_chunk_ids:
            help_lines.append(
                "These chunks need real grounded prose in `snippets[].body`: "
                + ", ".join(f"`{chunk_id}`" for chunk_id in non_grounded_chunk_ids)
                + "."
            )
        else:
            help_lines.append(
                "Use plain-language snippet bodies that make a reusable claim supported by the evidence rows."
            )
    if "missing_owned_chunk_results" in error_set or "unexpected_chunk_results" in error_set:
        help_lines.append(
            "Return exactly one `chunk_results` row for each owned chunk in `in/<task_id>.json`, in order and with no extras."
        )
    if "chunk_result_order_mismatch" in error_set:
        help_lines.append(
            "Keep `chunk_results` in the same order as the owned chunks in the input payload."
        )
    if "block_decision_coverage_mismatch" in error_set:
        help_lines.append(
            "Cover every owned block exactly once in `block_decisions`, using the input order."
        )
    if "snippet_evidence_wrong_chunk_surface" in error_set:
        help_lines.append(
            "Each snippet may cite only block indices from its own chunk result."
        )
    if "snippet_evidence_out_of_surface" in error_set:
        help_lines.append("Do not cite block indices outside the task's owned surface.")
    if "bundle_id_mismatch" in error_set:
        help_lines.append("`packet_id` must exactly match the current task row's `task_id`.")
    if "semantic_all_false_empty_shard" in error_set:
        help_lines.append(
            "This task has strong knowledge cues. Re-read the hint and owned blocks before keeping everything `other`."
        )
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
