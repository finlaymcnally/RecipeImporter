from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.llm.editable_task_file import (
    build_task_file,
    load_task_file,
    validate_edited_task_file,
)
from cookimport.llm.phase_worker_runtime import (
    ShardManifestEntryV1,
    WorkerAssignmentV1,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

from . import LineRoleRepairFailureError
from .contracts import CanonicalLineRolePrediction
from .planning import _LineRoleRuntimeResult, _coerce_mapping_dict


def _line_role_taskfile_row_id(index: int) -> str:
    return f"r{index + 1:02d}"


def _line_role_taskfile_unit_id(*, shard_id: str, row_id: str) -> str:
    return f"line::{shard_id}::{row_id}"


def _build_line_role_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
    debug_payload_by_shard_id: Mapping[str, Any],
    deterministic_baseline_by_shard_id: Mapping[
        str, Mapping[int, CanonicalLineRolePrediction]
    ],
) -> tuple[dict[str, Any], dict[str, str], dict[str, int]]:
    del debug_payload_by_shard_id, deterministic_baseline_by_shard_id
    units: list[dict[str, Any]] = []
    unit_to_shard_id: dict[str, str] = {}
    unit_to_atomic_index: dict[str, int] = {}
    for shard in shards:
        for index, row in enumerate(_coerce_mapping_dict(shard.input_payload).get("rows") or []):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            atomic_index = int(row[0])
            text = str((row[2] if len(row) >= 3 else row[1]) or "")
            row_id = _line_role_taskfile_row_id(index)
            unit_id = _line_role_taskfile_unit_id(shard_id=shard.shard_id, row_id=row_id)
            unit_to_shard_id[unit_id] = shard.shard_id
            unit_to_atomic_index[unit_id] = atomic_index
            units.append(
                {
                    "unit_id": unit_id,
                    "owned_id": row_id,
                    "evidence": {
                        "shard_id": shard.shard_id,
                        "row_id": row_id,
                        "text": text,
                    },
                    "answer": {},
                }
            )
    return (
        build_task_file(
            stage_key="line_role",
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
            units=units,
            answer_schema={
                "editable_pointer_pattern": "/units/*/answer",
                "required_keys": ["label"],
                "allowed_values": {
                    "label": [
                        "RECIPE_TITLE",
                        "INGREDIENT_LINE",
                        "INSTRUCTION_LINE",
                        "TIME_LINE",
                        "HOWTO_SECTION",
                        "YIELD_LINE",
                        "RECIPE_VARIANT",
                        "RECIPE_NOTES",
                        "NONRECIPE_CANDIDATE",
                        "NONRECIPE_EXCLUDE",
                    ],
                },
                "example_answers": [
                    {"label": "RECIPE_NOTES"},
                    {"label": "NONRECIPE_EXCLUDE"},
                ],
            },
        ),
        unit_to_shard_id,
        unit_to_atomic_index,
    )


def _line_role_incomplete_progress_summary_detail(
    message_text: str | None,
) -> str | None:
    cleaned = " ".join(str(message_text or "").strip().lower().split())
    if not cleaned:
        return None
    future_work_markers = (
        "haven't run `task-handoff`",
        "haven’t run `task-handoff`",
        "have not run `task-handoff`",
        "still needs labeling",
        "still need labeling",
        "rest of the shard still needs",
        "keep moving through the ledger",
        "after batching",
        "next steps",
        "time constraints",
        "partial progress",
        "current pause",
    )
    if not any(marker in cleaned for marker in future_work_markers):
        return None
    return (
        "taskfile worker ended with a partial-progress summary instead of finishing the task-file workflow. "
        "Progress summaries and deferred `task-handoff` are off-contract for line-role workers."
    )


def _expand_line_role_task_file_outputs(
    *,
    original_task_file: Mapping[str, Any],
    task_file_path: Path,
    unit_to_shard_id: Mapping[str, str],
    unit_to_atomic_index: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    try:
        edited_task_file = load_task_file(task_file_path)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}
    answers_by_unit_id, validation_errors, _validation_metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        allow_immutable_field_changes=True,
    )
    if validation_errors:
        return {}
    shard_rows: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not shard_id:
            continue
        evidence = dict(unit.get("evidence") or {})
        answer = dict((answers_by_unit_id or {}).get(unit_id) or {})
        atomic_index = unit_to_atomic_index.get(unit_id) if unit_to_atomic_index else None
        if atomic_index is None:
            atomic_index = int(evidence.get("atomic_index") or 0)
        shard_rows.setdefault(shard_id, []).append(
            (int(atomic_index), answer)
        )
    return {
        shard_id: {
            "rows": [
                {
                    "atomic_index": atomic_index,
                    "label": str(answer.get("label") or ""),
                }
                for atomic_index, answer in sorted(rows, key=lambda row: row[0])
            ]
        }
        for shard_id, rows in shard_rows.items()
    }


def _raise_if_line_role_runtime_incomplete(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    runtime_result: _LineRoleRuntimeResult | None,
    predictions_by_atomic_index: Mapping[int, CanonicalLineRolePrediction] | None = None,
) -> None:
    if runtime_result is None:
        return
    prediction_index = (
        predictions_by_atomic_index
        if predictions_by_atomic_index is not None
        else runtime_result.predictions_by_atomic_index
    )
    missing_atomic_indices = [
        int(candidate.atomic_index)
        for candidate in ordered_candidates
        if int(candidate.atomic_index) not in prediction_index
    ]
    if not missing_atomic_indices:
        return
    failed_shards: list[str] = []
    runtime_roots: list[str] = []
    for phase_result in runtime_result.phase_results:
        if phase_result.runtime_root is None:
            continue
        runtime_roots.append(str(phase_result.runtime_root))
        shard_status_path = phase_result.runtime_root / "shard_status.jsonl"
        if not shard_status_path.exists():
            continue
        for line in shard_status_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, Mapping):
                continue
            state = str(row.get("state") or "").strip()
            shard_id = str(row.get("shard_id") or "").strip()
            reason_code = str(
                (
                    (row.get("metadata") or {})
                    if isinstance(row.get("metadata"), Mapping)
                    else {}
                ).get("repair_status")
                or row.get("reason_code")
                or ""
            ).strip()
            if state in {"validated", "repair_recovered"}:
                continue
            detail = shard_id or "<unknown-shard>"
            if state:
                detail += f" state={state}"
            if reason_code:
                detail += f" repair_status={reason_code}"
            failed_shards.append(detail)
    detail_suffix = ""
    if failed_shards:
        detail_suffix = " Failed shards: " + "; ".join(failed_shards[:5]) + "."
    runtime_root_suffix = ""
    if runtime_roots:
        runtime_root_suffix = " Runtime roots: " + ", ".join(runtime_roots) + "."
    raise LineRoleRepairFailureError(
        "canonical line-role failed closed because one or more shards ended without a clean installed ledger."
        f" Missing atomic indices: {', '.join(str(value) for value in missing_atomic_indices)}."
        f"{detail_suffix}{runtime_root_suffix}"
    )
