from __future__ import annotations

import json
import logging
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import format_stage_progress
from cookimport.core.models import ConversionResult, ParsingOverrides
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.runs import (
    KNOWLEDGE_MANIFEST_FILE_NAME,
    stage_artifact_stem,
)
from cookimport.staging.nonrecipe_stage import (
    NonRecipeStageResult,
    refine_nonrecipe_stage_result,
)

from .codex_farm_ids import sanitize_for_filename
from .codex_farm_knowledge_ingest import (
    normalize_knowledge_worker_payload,
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from .codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES,
)
from .codex_farm_knowledge_jobs import (
    build_knowledge_jobs,
)
from .codex_farm_knowledge_writer import KnowledgeWriteReport, write_knowledge_artifacts
from .codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    assess_final_agent_message,
    classify_workspace_worker_command,
    detect_workspace_worker_boundary_violation,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)
from .codex_farm_runner import (
    CodexFarmRunnerError,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from .knowledge_prompt_builder import build_knowledge_direct_prompt
from .phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    TaskManifestEntryV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from .worker_hint_sidecars import preview_text, write_worker_hint_markdown

logger = logging.getLogger(__name__)

COMPACT_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.compact.v1"
DEFAULT_KNOWLEDGE_PIPELINE_ID = COMPACT_KNOWLEDGE_PIPELINE_ID
_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD = 1
_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD = 6000
_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN = 4096
_KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW = 12000
_STRICT_JSON_WATCHDOG_POLICY = "strict_json_no_tools_v1"
_KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS = 3
_KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS = 1_000
_KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR = 4.0
_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES = 2
_KNOWLEDGE_WATCHDOG_RETRY_SILENCE_TIMEOUT_SECONDS = 90
_KNOWLEDGE_WATCHDOG_RETRY_TIMEOUT_SECONDS = 300
_KNOWLEDGE_WORKSPACE_OUTPUT_STABLE_PASSES = 2
_KNOWLEDGE_TASK_STATUS_FILE_NAME = "task_status.jsonl"
_KNOWLEDGE_STAGE_STATUS_FILE_NAME = "stage_status.json"
_KNOWLEDGE_TASK_STATUS_SCHEMA_VERSION = "knowledge_task_status.v1"
_KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION = "knowledge_stage_status.v1"
_KNOWLEDGE_SCRATCH_DIR_NAME = "scratch"
_KNOWLEDGE_POISONED_WORKER_MIN_FAILURES = 2
_KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS = 3
_KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_SUCCESS_RATE = 0.25
_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS = frozenset(
    {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
        "chunk_result_order_mismatch",
    }
)


def _build_knowledge_task_manifest_entry(
    shard: ShardManifestEntryV1,
) -> TaskManifestEntryV1:
    return TaskManifestEntryV1(
        task_id=shard.shard_id,
        task_kind="knowledge_review_shard",
        parent_shard_id=shard.shard_id,
        owned_ids=tuple(shard.owned_ids),
        input_payload=shard.input_payload,
        input_text=shard.input_text,
        metadata=dict(shard.metadata or {}),
    )


def _build_knowledge_task_plans(
    shard: ShardManifestEntryV1,
) -> tuple[_KnowledgeTaskPlan, ...]:
    payload = _coerce_dict(shard.input_payload)
    chunks = [dict(row) for row in (payload.get("c") or []) if isinstance(row, Mapping)]
    if not chunks:
        return ()
    task_count = len(chunks)
    chunk_block_indices_by_id = _coerce_dict((shard.metadata or {}).get("chunk_block_indices_by_id"))
    chunk_seed_stage_category_by_id = _coerce_dict((shard.metadata or {}).get("chunk_seed_stage_category_by_id"))
    chunk_lane_by_id = _coerce_dict((shard.metadata or {}).get("chunk_lane_by_id"))
    chunk_title_by_id = _coerce_dict((shard.metadata or {}).get("chunk_title_by_id"))
    chunk_has_heading_by_id = _coerce_dict((shard.metadata or {}).get("chunk_has_heading_by_id"))
    chunk_has_table_hint_by_id = _coerce_dict((shard.metadata or {}).get("chunk_has_table_hint_by_id"))
    chunk_knowledge_cue_by_id = _coerce_dict((shard.metadata or {}).get("chunk_knowledge_cue_by_id"))
    task_plans: list[_KnowledgeTaskPlan] = []
    for task_index, chunk_row in enumerate(chunks, start=1):
        chunk_id = str(chunk_row.get("cid") or "").strip()
        if not chunk_id:
            continue
        task_id = (
            shard.shard_id
            if task_count == 1
            else f"{shard.shard_id}.task-{task_index:03d}"
        )
        chunk_blocks = [dict(block) for block in (chunk_row.get("b") or []) if isinstance(block, Mapping)]
        evidence_refs = tuple(
            f"block:{int(block.get('i', 0))}"
            for block in chunk_blocks
            if block.get("i") is not None
        )
        task_payload = {
            **payload,
            "bid": task_id,
            "c": [dict(chunk_row)],
        }
        task_manifest = ShardManifestEntryV1(
            shard_id=task_id,
            owned_ids=(chunk_id,),
            evidence_refs=evidence_refs,
            input_payload=task_payload,
            metadata={
                **dict(shard.metadata or {}),
                "parent_shard_id": shard.shard_id,
                "task_id": task_id,
                "task_index": task_index,
                "task_count": task_count,
                "ordered_chunk_ids": [chunk_id],
                "chunk_count": 1,
                "owned_block_indices": list(chunk_block_indices_by_id.get(chunk_id) or []),
                "chunk_block_indices_by_id": {
                    chunk_id: list(chunk_block_indices_by_id.get(chunk_id) or [])
                },
                "chunk_seed_stage_category_by_id": (
                    {chunk_id: chunk_seed_stage_category_by_id.get(chunk_id)}
                    if chunk_id in chunk_seed_stage_category_by_id
                    else {}
                ),
                "chunk_lane_by_id": (
                    {chunk_id: chunk_lane_by_id.get(chunk_id)}
                    if chunk_id in chunk_lane_by_id
                    else {}
                ),
                "chunk_title_by_id": (
                    {chunk_id: chunk_title_by_id.get(chunk_id)}
                    if chunk_id in chunk_title_by_id
                    else {}
                ),
                "chunk_has_heading_by_id": (
                    {chunk_id: chunk_has_heading_by_id.get(chunk_id)}
                    if chunk_id in chunk_has_heading_by_id
                    else {}
                ),
                "chunk_has_table_hint_by_id": (
                    {chunk_id: chunk_has_table_hint_by_id.get(chunk_id)}
                    if chunk_id in chunk_has_table_hint_by_id
                    else {}
                ),
                "chunk_knowledge_cue_by_id": (
                    {chunk_id: chunk_knowledge_cue_by_id.get(chunk_id)}
                    if chunk_id in chunk_knowledge_cue_by_id
                    else {}
                ),
            },
        )
        task_plans.append(
            _KnowledgeTaskPlan(
                task_id=task_id,
                parent_shard_id=shard.shard_id,
                manifest_entry=task_manifest,
            )
        )
    return tuple(task_plans)


def _build_knowledge_task_runtime_manifest_entry(
    task_plan: _KnowledgeTaskPlan,
) -> TaskManifestEntryV1:
    task_manifest = task_plan.manifest_entry
    return TaskManifestEntryV1(
        task_id=task_plan.task_id,
        task_kind="knowledge_review_chunk_packet",
        parent_shard_id=task_plan.parent_shard_id,
        owned_ids=tuple(task_manifest.owned_ids),
        input_payload=task_manifest.input_payload,
        input_text=task_manifest.input_text,
        metadata=dict(task_manifest.metadata or {}),
    )


def _decorate_knowledge_workspace_task_runtime_entry(
    task_entry: TaskManifestEntryV1,
    *,
    task_sequence: int,
    task_total: int,
) -> TaskManifestEntryV1:
    task_id = str(task_entry.task_id).strip()
    metadata = dict(task_entry.metadata or {})
    metadata.update(
        {
            "input_path": str(Path("in") / f"{task_id}.json"),
            "hint_path": str(Path("hints") / f"{task_id}.md"),
            "result_path": str(Path("out") / f"{task_id}.json"),
            "task_sequence": int(task_sequence),
            "task_total": int(task_total),
            "lease_sequence": int(task_sequence),
            "lease_total": int(task_total),
            "workspace_processing_contract": "ordered_task_queue_v1",
        }
    )
    return replace(task_entry, metadata=metadata)


def _build_knowledge_workspace_task_runtime_entries(
    task_plans: Sequence[_KnowledgeTaskPlan],
) -> tuple[TaskManifestEntryV1, ...]:
    total = len(task_plans)
    return tuple(
        _decorate_knowledge_workspace_task_runtime_entry(
            _build_knowledge_task_runtime_manifest_entry(task_plan),
            task_sequence=index,
            task_total=total,
        )
        for index, task_plan in enumerate(task_plans, start=1)
    )


def _knowledge_task_runtime_entries_for_shard(
    *,
    shard: ShardManifestEntryV1,
    task_plans_by_shard_id: Mapping[str, Sequence[_KnowledgeTaskPlan]],
) -> tuple[TaskManifestEntryV1, ...]:
    task_plans = tuple(task_plans_by_shard_id.get(shard.shard_id) or ())
    if task_plans:
        return tuple(
            _build_knowledge_task_runtime_manifest_entry(task_plan)
            for task_plan in task_plans
        )
    return (_build_knowledge_task_manifest_entry(shard),)


def _progress_task_ids_for_knowledge_shard(
    *,
    shard_id: str,
    task_plans_by_shard_id: Mapping[str, Sequence[_KnowledgeTaskPlan]],
) -> tuple[str, ...]:
    task_ids = tuple(
        str(task_plan.task_id).strip()
        for task_plan in tuple(task_plans_by_shard_id.get(shard_id) or ())
        if str(task_plan.task_id).strip()
    )
    return task_ids or (str(shard_id).strip(),)


def _summarize_knowledge_task_packet_distribution(
    *,
    assignments: Sequence[WorkerAssignmentV1],
    task_plans_by_shard_id: Mapping[str, Sequence[_KnowledgeTaskPlan]],
) -> dict[str, Any]:
    worker_task_packet_counts: dict[str, int] = {}
    for assignment in assignments:
        worker_task_packet_counts[assignment.worker_id] = sum(
            len(
                _progress_task_ids_for_knowledge_shard(
                    shard_id=shard_id,
                    task_plans_by_shard_id=task_plans_by_shard_id,
                )
            )
            for shard_id in assignment.shard_ids
        )
    counts = list(worker_task_packet_counts.values())
    return {
        "bundle_policy": "shard_round_robin_with_task_packets_v1",
        "worker_task_packet_counts": dict(sorted(worker_task_packet_counts.items())),
        "max_task_packets_per_worker": max(counts) if counts else 0,
        "min_task_packets_per_worker": min(counts) if counts else 0,
    }


def _aggregate_knowledge_task_payloads(
    *,
    shard: ShardManifestEntryV1,
    task_payloads_by_task_id: Mapping[str, dict[str, Any] | None],
    task_validation_errors_by_task_id: Mapping[str, Sequence[str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_chunk_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    result_rows_by_chunk_id: dict[str, dict[str, Any]] = {}
    task_id_by_chunk_id: dict[str, str] = {}
    accepted_task_ids: list[str] = []
    for task_id, payload in task_payloads_by_task_id.items():
        rows = payload.get("r") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            continue
        accepted_task_ids.append(task_id)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            chunk_id = str(row.get("cid") or "").strip()
            if not chunk_id:
                continue
            result_rows_by_chunk_id[chunk_id] = dict(row)
            task_id_by_chunk_id[chunk_id] = str(task_id)
    output_rows: list[dict[str, Any]] = []
    missing_chunk_ids: list[str] = []
    for chunk_id in ordered_chunk_ids:
        row = result_rows_by_chunk_id.get(chunk_id)
        if row is None:
            missing_chunk_ids.append(chunk_id)
            continue
        output_rows.append(dict(row))
    all_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id in [*task_payloads_by_task_id.keys(), *task_validation_errors_by_task_id.keys()]
            if str(task_id).strip()
        }
    )
    fallback_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors or task_id not in accepted_task_ids
        }
    )
    metadata = {
        "task_count": len(all_task_ids),
        "accepted_task_count": len(accepted_task_ids),
        "accepted_task_ids": sorted(accepted_task_ids),
        "fallback_task_count": len(fallback_task_ids),
        "fallback_task_ids": fallback_task_ids,
        "missing_chunk_ids": missing_chunk_ids,
        "task_ids": all_task_ids,
        "task_validation_errors_by_task_id": {
            task_id: list(errors)
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors
        },
        "task_id_by_chunk_id": {
            chunk_id: task_id
            for chunk_id, task_id in sorted(task_id_by_chunk_id.items())
        },
    }
    return {
        "v": "2",
        "bid": shard.shard_id,
        "r": output_rows,
    }, metadata


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


def _notify_knowledge_progress(
    *,
    progress_callback: Callable[[str], None] | None,
    completed_tasks: int,
    total_tasks: int,
    running_tasks: int | None = None,
    worker_total: int | None = None,
    worker_running: int | None = None,
    worker_completed: int | None = None,
    worker_failed: int | None = None,
    followup_running: int | None = None,
    followup_completed: int | None = None,
    followup_total: int | None = None,
    followup_label: str | None = None,
    artifact_counts: dict[str, Any] | None = None,
    active_tasks: list[str] | None = None,
    detail_lines: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    total = max(0, int(total_tasks))
    completed = max(0, min(total, int(completed_tasks)))
    message = f"Running codex-farm non-recipe knowledge review... task {completed}/{total}"
    if running_tasks is not None:
        message = f"{message} | running {max(0, int(running_tasks))}"
    resolved_detail_lines = [
        str(value).strip()
        for value in (detail_lines or [])
        if str(value).strip()
    ]
    progress_callback(
        format_stage_progress(
            message,
            stage_label="non-recipe knowledge review",
            work_unit_label="task packet",
            task_current=completed,
            task_total=total,
            running_workers=running_tasks,
            worker_total=worker_total,
            worker_running=worker_running,
            worker_completed=worker_completed,
            worker_failed=worker_failed,
            followup_running=followup_running,
            followup_completed=followup_completed,
            followup_total=followup_total,
            followup_label=followup_label,
            artifact_counts=artifact_counts,
            last_activity_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            active_tasks=active_tasks,
            detail_lines=resolved_detail_lines,
        )
    )


@dataclass(slots=True)
class _KnowledgeWorkerProgressState:
    worker_id: str
    shard_ids: tuple[str, ...]
    pending_shard_ids: list[str]
    total_task_packets: int
    live_task_packets: int = 0
    terminal_task_ids: set[str] = field(default_factory=set)
    active_followup_label: str | None = None

    def visible_task_packets(self) -> int:
        return max(self.live_task_packets, len(self.terminal_task_ids))

    def render_worker_label(self) -> str | None:
        if self.active_followup_label:
            return None
        if len(self.terminal_task_ids) >= self.total_task_packets and not self.pending_shard_ids:
            return None
        shard_ids = self.pending_shard_ids or list(self.shard_ids)
        if not shard_ids:
            return None
        base_label = str(shard_ids[0]).strip() or self.worker_id
        extra_shard_count = max(0, len(shard_ids) - 1)
        if extra_shard_count > 0:
            base_label = f"{base_label} +{extra_shard_count} more"
        if self.total_task_packets <= 0:
            return base_label
        return (
            f"{base_label} "
            f"({self.visible_task_packets()}/{self.total_task_packets} task packets)"
        )

    def worker_session_completed(self) -> bool:
        return self.visible_task_packets() >= self.total_task_packets


@dataclass(slots=True)
class _KnowledgePhaseProgressState:
    progress_callback: Callable[[str], None] | None
    total_shards: int
    total_task_packets: int
    worker_total: int
    worker_order: tuple[str, ...]
    worker_states: dict[str, _KnowledgeWorkerProgressState]
    completed_shard_ids: set[str] = field(default_factory=set)
    running_followup_counts: dict[str, int] = field(default_factory=dict)
    completed_followup_counts: dict[str, int] = field(default_factory=dict)
    observed_followup_counts: dict[str, int] = field(default_factory=dict)
    last_snapshot_key: tuple[Any, ...] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, *, force: bool = False) -> None:
        with self.lock:
            self._emit_locked(force=force)

    def observe_workspace_outputs(
        self,
        *,
        worker_id: str,
        present_count: int,
        expected_count: int,
    ) -> None:
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None:
                return
            capped_total = worker_state.total_task_packets or max(0, int(expected_count))
            next_count = min(capped_total, max(0, int(present_count)))
            next_count = max(worker_state.live_task_packets, next_count)
            if next_count == worker_state.live_task_packets:
                return
            worker_state.live_task_packets = next_count
            self._emit_locked()

    def mark_task_packet_terminal(
        self,
        *,
        worker_id: str,
        task_id: str,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None or cleaned_task_id in worker_state.terminal_task_ids:
                return
            worker_state.terminal_task_ids.add(cleaned_task_id)
            self._emit_locked()

    def mark_task_packets_terminal(
        self,
        *,
        worker_id: str,
        task_ids: Sequence[str],
    ) -> None:
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None:
                return
            changed = False
            for task_id in task_ids:
                cleaned_task_id = str(task_id).strip()
                if not cleaned_task_id or cleaned_task_id in worker_state.terminal_task_ids:
                    continue
                worker_state.terminal_task_ids.add(cleaned_task_id)
                changed = True
            if changed:
                self._emit_locked()

    def mark_shard_completed(
        self,
        *,
        worker_id: str,
        shard_id: str,
    ) -> None:
        cleaned_shard_id = str(shard_id).strip()
        if not cleaned_shard_id:
            return
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is not None and cleaned_shard_id in worker_state.pending_shard_ids:
                worker_state.pending_shard_ids.remove(cleaned_shard_id)
            if cleaned_shard_id in self.completed_shard_ids:
                return
            self.completed_shard_ids.add(cleaned_shard_id)
            self._emit_locked()

    def set_followup_label(
        self,
        *,
        worker_id: str,
        label: str | None,
    ) -> None:
        cleaned_label = str(label or "").strip() or None
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None or worker_state.active_followup_label == cleaned_label:
                return
            worker_state.active_followup_label = cleaned_label
            self._emit_locked()

    def clear_followup_label(self, *, worker_id: str) -> None:
        self.set_followup_label(worker_id=worker_id, label=None)

    def begin_followup(
        self,
        *,
        worker_id: str,
        label: str,
        followup_kind: str,
    ) -> None:
        cleaned_label = str(label or "").strip() or None
        cleaned_kind = str(followup_kind or "").strip().lower() or "followup"
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None:
                return
            worker_state.active_followup_label = cleaned_label
            self.running_followup_counts[cleaned_kind] = (
                int(self.running_followup_counts.get(cleaned_kind) or 0) + 1
            )
            self.observed_followup_counts[cleaned_kind] = (
                int(self.observed_followup_counts.get(cleaned_kind) or 0) + 1
            )
            self._emit_locked()

    def end_followup(self, *, worker_id: str, followup_kind: str) -> None:
        cleaned_kind = str(followup_kind or "").strip().lower() or "followup"
        with self.lock:
            worker_state = self.worker_states.get(worker_id)
            if worker_state is None:
                return
            worker_state.active_followup_label = None
            current = int(self.running_followup_counts.get(cleaned_kind) or 0)
            if current <= 1:
                self.running_followup_counts.pop(cleaned_kind, None)
            else:
                self.running_followup_counts[cleaned_kind] = current - 1
            self.completed_followup_counts[cleaned_kind] = (
                int(self.completed_followup_counts.get(cleaned_kind) or 0) + 1
            )
            self._emit_locked()

    def _emit_locked(self, *, force: bool = False) -> None:
        active_tasks = [
            label
            for worker_id in self.worker_order
            for label in [self.worker_states[worker_id].render_worker_label()]
            if label is not None
        ]
        completed_task_packets = min(
            self.total_task_packets,
            sum(
                worker_state.visible_task_packets()
                for worker_state in self.worker_states.values()
            ),
        )
        running_workers = len(active_tasks)
        completed_workers = sum(
            1
            for worker_state in self.worker_states.values()
            if worker_state.worker_session_completed() and worker_state.render_worker_label() is None
        )
        detail_lines = [
            f"configured workers: {self.worker_total}",
            f"completed shards: {len(self.completed_shard_ids)}/{self.total_shards}",
            f"queued task packets: {max(0, self.total_task_packets - completed_task_packets)}",
        ]
        repair_running = int(self.running_followup_counts.get("repair") or 0)
        retry_running = int(self.running_followup_counts.get("retry") or 0)
        followup_running = sum(int(value) for value in self.running_followup_counts.values())
        followup_completed = sum(int(value) for value in self.completed_followup_counts.values())
        followup_total = sum(int(value) for value in self.observed_followup_counts.values())
        if repair_running > 0:
            detail_lines.append(f"repair calls running: {repair_running}")
        if retry_running > 0:
            detail_lines.append(f"retry calls running: {retry_running}")
        snapshot_key = (
            completed_task_packets,
            self.total_task_packets,
            running_workers,
            tuple(active_tasks),
            tuple(detail_lines),
        )
        if not force and snapshot_key == self.last_snapshot_key:
            return
        self.last_snapshot_key = snapshot_key
        _notify_knowledge_progress(
            progress_callback=self.progress_callback,
            completed_tasks=completed_task_packets,
            total_tasks=self.total_task_packets,
            running_tasks=running_workers,
            worker_total=self.worker_total,
            worker_running=running_workers,
            worker_completed=completed_workers,
            worker_failed=0,
            followup_running=followup_running,
            followup_completed=followup_completed,
            followup_total=followup_total,
            followup_label="repair/retry",
            artifact_counts={
                "repairs_running": repair_running,
                "retries_running": retry_running,
                "shards_completed": len(self.completed_shard_ids),
                "shards_total": self.total_shards,
            },
            active_tasks=active_tasks,
            detail_lines=detail_lines,
        )


def _format_knowledge_followup_label(
    *,
    parent_shard_id: str,
    attempt_label: str,
    task_id: str | None = None,
) -> str:
    cleaned_parent = str(parent_shard_id).strip()
    cleaned_attempt = str(attempt_label).strip()
    cleaned_task_id = str(task_id or "").strip()
    if cleaned_task_id and cleaned_task_id != cleaned_parent:
        return f"{cleaned_parent} {cleaned_attempt} {cleaned_task_id}".strip()
    return f"{cleaned_parent} {cleaned_attempt}".strip()


def _build_knowledge_workspace_progress_watchdog_callback(
    *,
    worker_id: str,
    progress_state: _KnowledgePhaseProgressState | None,
    expected_output_paths: Sequence[Path],
    live_status_path: Path,
    live_status_paths: Sequence[Path] | None = None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState | None = None,
    watchdog_policy: str | None = None,
    allow_workspace_commands: bool = False,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    watchdog_callback = _build_strict_json_watchdog_callback(
        live_status_path=live_status_path,
        live_status_paths=live_status_paths,
        cohort_watchdog_state=cohort_watchdog_state,
        watchdog_policy=watchdog_policy,
        allow_workspace_commands=allow_workspace_commands,
        expected_workspace_output_paths=expected_output_paths,
    )
    expected_count = len(expected_output_paths)

    def _callback(
        snapshot: CodexExecLiveSnapshot,
    ) -> CodexExecSupervisionDecision | None:
        if progress_state is not None:
            progress_state.observe_workspace_outputs(
                worker_id=worker_id,
                present_count=sum(1 for path in expected_output_paths if path.exists()),
                expected_count=expected_count,
            )
        return watchdog_callback(snapshot)

    return _callback


@dataclass(frozen=True, slots=True)
class CodexFarmNonrecipeKnowledgeReviewResult:
    llm_report: dict[str, Any]
    llm_raw_dir: Path
    manifest_path: Path
    refined_stage_result: NonRecipeStageResult
    write_report: KnowledgeWriteReport | None = None


@dataclass(frozen=True, slots=True)
class _DirectKnowledgeWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    worker_runner_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _KnowledgeTaskPlan:
    task_id: str
    parent_shard_id: str
    manifest_entry: ShardManifestEntryV1


@dataclass(slots=True)
class _KnowledgeCohortWatchdogState:
    durations_ms: list[int] = field(default_factory=list)
    successful_examples: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            durations_ms = list(self.durations_ms)
            examples = [
                dict(example_payload)
                for example_payload in self.successful_examples[-_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES :]
            ]
        median_duration_ms = (
            int(statistics.median(durations_ms))
            if durations_ms
            else None
        )
        return {
            "completed_successful_shards": len(durations_ms),
            "median_duration_ms": median_duration_ms,
            "successful_examples": examples,
        }

    def record_validated_result(
        self,
        *,
        duration_ms: int | None,
        example_payload: Mapping[str, Any] | None,
    ) -> None:
        normalized_duration_ms = int(duration_ms or 0)
        if normalized_duration_ms <= 0:
            return
        with self.lock:
            self.durations_ms.append(normalized_duration_ms)
            if isinstance(example_payload, Mapping):
                self.successful_examples.append(dict(example_payload))
                self.successful_examples = self.successful_examples[
                    -_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES :
                ]


@dataclass(frozen=True, slots=True)
class _KnowledgeFollowupDecision:
    allowed: bool
    reason_code: str | None = None
    reason_detail: str | None = None


@dataclass(slots=True)
class _KnowledgeRecoveryGovernor:
    lock: threading.Lock = field(default_factory=threading.Lock)
    worker_failure_signatures_by_id: dict[str, list[str]] = field(default_factory=dict)
    poisoned_workers: dict[str, dict[str, str]] = field(default_factory=dict)
    followup_attempts_by_kind: dict[str, int] = field(default_factory=dict)
    followup_successes_by_kind: dict[str, int] = field(default_factory=dict)
    repeated_failure_attempts_by_kind: dict[str, dict[str, int]] = field(default_factory=dict)

    def observe_main_failure(
        self,
        *,
        worker_id: str,
        failure_signature: str,
    ) -> dict[str, str] | None:
        cleaned_worker_id = str(worker_id).strip()
        cleaned_signature = str(failure_signature).strip()
        if not cleaned_worker_id or not cleaned_signature:
            return None
        with self.lock:
            poisoned = self.poisoned_workers.get(cleaned_worker_id)
            if poisoned is not None:
                return dict(poisoned)
            signatures = self.worker_failure_signatures_by_id.setdefault(cleaned_worker_id, [])
            signatures.append(cleaned_signature)
            recent_signatures = signatures[-_KNOWLEDGE_POISONED_WORKER_MIN_FAILURES :]
            if len(recent_signatures) < _KNOWLEDGE_POISONED_WORKER_MIN_FAILURES:
                return None
            if len(set(recent_signatures)) != 1:
                return None
            signature = recent_signatures[-1]
            poison_reason = _poison_reason_for_failure_signature(signature)
            if poison_reason is None:
                return None
            reason_code, reason_detail = poison_reason
            payload = {
                "reason_code": reason_code,
                "reason_detail": reason_detail,
            }
            self.poisoned_workers[cleaned_worker_id] = payload
            return dict(payload)

    def allow_followup(
        self,
        *,
        kind: str,
        worker_id: str,
        failure_signature: str,
        near_miss: bool = True,
    ) -> _KnowledgeFollowupDecision:
        cleaned_kind = str(kind).strip().lower()
        cleaned_worker_id = str(worker_id).strip()
        cleaned_signature = str(failure_signature).strip() or "unknown_failure"
        with self.lock:
            poisoned = self.poisoned_workers.get(cleaned_worker_id)
            if poisoned is not None:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code=f"{cleaned_kind}_skipped_poisoned_worker",
                    reason_detail=str(poisoned.get("reason_detail") or "").strip()
                    or "worker already classified as poisoned",
                )
            if cleaned_kind == "repair" and not near_miss:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code="repair_skipped_not_near_miss",
                    reason_detail=(
                        "packet failed closed because the validator errors were not a "
                        "small repairable near miss"
                    ),
                )
            attempts = int(self.followup_attempts_by_kind.get(cleaned_kind) or 0)
            successes = int(self.followup_successes_by_kind.get(cleaned_kind) or 0)
            success_rate = (successes / attempts) if attempts > 0 else 1.0
            repeated_failures = int(
                (
                    self.repeated_failure_attempts_by_kind.get(cleaned_kind, {}).get(
                        cleaned_signature
                    )
                )
                or 0
            )
            if (
                attempts >= _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS
                and success_rate < _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_SUCCESS_RATE
            ) or repeated_failures >= _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code=f"{cleaned_kind}_skipped_circuit_breaker",
                    reason_detail=(
                        "bounded recovery circuit breaker opened after repeated low-yield "
                        f"{cleaned_kind} attempts for failure class {cleaned_signature}"
                    ),
                )
        return _KnowledgeFollowupDecision(allowed=True)

    def record_followup_outcome(
        self,
        *,
        kind: str,
        failure_signature: str,
        recovered: bool,
    ) -> None:
        cleaned_kind = str(kind).strip().lower()
        cleaned_signature = str(failure_signature).strip() or "unknown_failure"
        if not cleaned_kind:
            return
        with self.lock:
            self.followup_attempts_by_kind[cleaned_kind] = (
                int(self.followup_attempts_by_kind.get(cleaned_kind) or 0) + 1
            )
            if recovered:
                self.followup_successes_by_kind[cleaned_kind] = (
                    int(self.followup_successes_by_kind.get(cleaned_kind) or 0) + 1
                )
            else:
                repeated = dict(self.repeated_failure_attempts_by_kind.get(cleaned_kind) or {})
                repeated[cleaned_signature] = int(repeated.get(cleaned_signature) or 0) + 1
                self.repeated_failure_attempts_by_kind[cleaned_kind] = repeated


def run_codex_farm_nonrecipe_knowledge_review(
    *,
    conversion_result: ConversionResult,
    nonrecipe_stage_result: NonRecipeStageResult,
    recipe_spans: list[RecipeSpan],
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    overrides: ParsingOverrides | None = None,
    runner: CodexExecRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmNonrecipeKnowledgeReviewResult:
    """Optional Stage 7 review over non-recipe chunks via codex-farm."""
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    manifest_path = llm_raw_dir / KNOWLEDGE_MANIFEST_FILE_NAME

    if run_settings.llm_knowledge_pipeline.value == "off":
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
        )

    knowledge_stage_dir = llm_raw_dir / stage_artifact_stem("nonrecipe_knowledge_review")
    knowledge_in_dir = knowledge_stage_dir / "in"
    knowledge_in_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id = _non_empty(
        run_settings.codex_farm_pipeline_knowledge,
        fallback=DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    seed_candidate_spans = list(
        nonrecipe_stage_result.seed_nonrecipe_spans
        or nonrecipe_stage_result.nonrecipe_spans
    )
    if not seed_candidate_spans:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=None,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_nonrecipe_spans",
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm non-recipe knowledge review: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    configured_runner_cmd = str(run_settings.codex_farm_cmd or "").strip()
    if runner is None:
        codex_runner: CodexExecRunner = SubprocessCodexExecRunner(
            cmd=configured_runner_cmd
            if Path(configured_runner_cmd).name == "fake-codex-farm.py"
            else "codex exec"
        )
    else:
        codex_runner = runner
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )
    output_schema_path: str | None = None
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=run_settings.codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=(pipeline_id,),
            env=env,
        )
        output_schema_path = str(
            resolve_codex_farm_output_schema_path(
                root_dir=pipeline_root,
                pipeline_id=pipeline_id,
            )
        )

    started = time.perf_counter()
    build_report = build_knowledge_jobs(
        full_blocks=full_blocks_payload,
        candidate_spans=seed_candidate_spans,
        recipe_spans=recipe_spans,
        workbook_slug=workbook_slug,
        source_hash=_resolve_source_hash(conversion_result),
        out_dir=knowledge_in_dir,
        context_blocks=run_settings.codex_farm_knowledge_context_blocks,
        target_prompt_count=run_settings.knowledge_prompt_target_count,
        target_chunks_per_shard=run_settings.knowledge_shard_target_chunks,
        overrides=overrides,
    )
    for warning in build_report.planning_warnings:
        logger.warning("Knowledge planning warning for %s: %s", workbook_slug, warning)

    if build_report.shards_written == 0:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="all_chunks_skipped",
            seed_nonrecipe_span_count=build_report.seed_nonrecipe_span_count,
            chunk_count_before_pruning=build_report.chunk_count_before_pruning,
            skipped_chunk_count=build_report.skipped_chunk_count,
            skipped_lane_counts=dict(build_report.skipped_lane_counts),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    worker_count = resolve_phase_worker_count(
        requested_worker_count=run_settings.knowledge_worker_count,
        shard_count=len(build_report.shard_entries),
    )
    configured_worker_total = (
        max(1, int(run_settings.knowledge_worker_count))
        if run_settings.knowledge_worker_count is not None
        else worker_count
    )
    phase_manifest = None
    worker_reports: list[dict[str, Any]] = []
    process_run_payload: dict[str, Any] | None = None
    try:
        phase_manifest, phase_worker_reports, process_run_payload = _run_direct_knowledge_workers_v1(
            phase_key="nonrecipe_knowledge_review",
            pipeline_id=pipeline_id,
            run_root=knowledge_stage_dir,
            shards=build_report.shard_entries,
            runner=codex_runner,
            worker_count=worker_count,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            output_schema_path=Path(output_schema_path) if output_schema_path else None,
            settings={
                "llm_knowledge_pipeline": run_settings.llm_knowledge_pipeline.value,
                "knowledge_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "knowledge_worker_count": run_settings.knowledge_worker_count,
                "knowledge_shard_target_chunks": run_settings.knowledge_shard_target_chunks,
                "knowledge_shard_max_turns": run_settings.knowledge_shard_max_turns,
                "codex_farm_pipeline_knowledge": pipeline_id,
            },
            runtime_metadata={
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "input_mode": "stage7_seed_nonrecipe_spans",
                "workspace_root": str(workspace_root) if workspace_root is not None else None,
            },
            progress_worker_total=configured_worker_total,
            progress_callback=progress_callback,
        )
        worker_reports = [
            {
                "worker_id": report.worker_id,
                "shard_ids": list(report.shard_ids),
                "status": report.status,
                "proposal_count": report.proposal_count,
                "failure_count": report.failure_count,
                "runtime_mode_audit": dict(report.runtime_mode_audit or {}),
                "workspace_root": report.workspace_root,
                "metadata": dict(report.metadata),
                "runner_result": dict(report.runner_result or {}),
            }
            for report in phase_worker_reports
        ]
    except KeyboardInterrupt:
        _mark_running_knowledge_status_files_interrupted(knowledge_stage_dir)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="interrupted",
            termination_cause="operator_interrupt",
            finalization_completeness="interrupted_before_finalization",
        )
        raise
    except CodexFarmRunnerError as exc:
        elapsed_seconds = round(time.perf_counter() - started, 3)
        llm_report = _build_runtime_failed_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            build_report=build_report,
            elapsed_seconds=elapsed_seconds,
            error=str(exc),
        )
        _write_json(llm_report, manifest_path)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="runtime_failed",
            termination_cause="runtime_error",
            finalization_completeness="complete",
        )
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    try:
        outputs, _ = read_validated_knowledge_outputs_from_proposals(
            knowledge_stage_dir / "proposals"
        )
        missing_chunk_ids = sorted(set(build_report.chunk_ids) - set(outputs))
        (
            block_category_updates,
            reviewer_categories_by_block,
            applied_chunk_ids_by_block,
            conflicts,
            ignored_block_indices,
        ) = _collect_block_category_updates(
            outputs=outputs,
            allowed_block_indices=(
                nonrecipe_stage_result.seed_block_category_by_index
                or nonrecipe_stage_result.block_category_by_index
            ),
        )
        refined_stage_result = refine_nonrecipe_stage_result(
            stage_result=nonrecipe_stage_result,
            full_blocks=full_blocks_payload,
            block_category_updates=block_category_updates,
            reviewer_categories_by_block=reviewer_categories_by_block,
            applied_chunk_ids_by_block=applied_chunk_ids_by_block,
            conflicts=conflicts,
            ignored_block_indices=ignored_block_indices,
        )

        write_report = write_knowledge_artifacts(
            run_root=run_root,
            workbook_slug=workbook_slug,
            outputs=outputs,
            full_blocks_by_index=full_blocks_by_index,
            chunk_lane_by_id=build_report.chunk_lane_by_id,
        )

        elapsed_seconds = round(time.perf_counter() - started, 3)
        promotion_report = _load_json_dict(knowledge_stage_dir / "promotion_report.json")
        telemetry = _load_json_dict(knowledge_stage_dir / "telemetry.json")
        useful_chunk_count = sum(1 for output in outputs.values() if bool(output.is_useful))
        review_rollup = _build_knowledge_review_rollup(
            promotion_report=promotion_report,
            build_report=build_report,
        )
        authority_mode = _derive_knowledge_authority_mode(
            refined_stage_result=refined_stage_result,
            review_rollup=review_rollup,
        )
        review_status = _derive_knowledge_review_status(review_rollup)
        refined_report = {
            **dict(refined_stage_result.refinement_report),
            "authority_mode": authority_mode,
            "review_status": review_status,
            "reviewed_shards_with_useful_chunks": review_rollup["reviewed_shards_with_useful_chunks"],
            "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
            "semantic_rejection_shard_count": review_rollup["semantic_rejection_shard_count"],
            "all_false_empty_shard_count": review_rollup["all_false_empty_shard_count"],
            "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
            "unreviewed_chunk_count": review_rollup["unreviewed_chunk_count"],
            "unreviewed_block_count": review_rollup["unreviewed_block_count"],
        }
        refined_stage_result = replace(
            refined_stage_result,
            refinement_report=refined_report,
        )
        review_summary = _build_review_summary(
            build_report=build_report,
            validated_output_count=len(outputs),
            planned_shard_count=(
                int(phase_manifest.shard_count)
                if phase_manifest is not None
                else build_report.shards_written
            ),
            review_rollup=review_rollup,
            promoted_useful_chunk_count=useful_chunk_count,
            promoted_snippet_count=write_report.snippets_written,
        )
        llm_report = {
            "enabled": True,
            "pipeline": run_settings.llm_knowledge_pipeline.value,
            "pipeline_id": pipeline_id,
            "input_mode": "stage7_seed_nonrecipe_spans",
            "authority_mode": authority_mode,
            "scored_effect": str(
                refined_stage_result.refinement_report.get("scored_effect")
                or "seed_only"
            ),
            "output_schema_path": output_schema_path,
            "counts": {
                "seed_nonrecipe_span_count": build_report.seed_nonrecipe_span_count,
                "chunks_built_before_pruning": build_report.chunk_count_before_pruning,
                "shards_written": build_report.shards_written,
                "chunks_written": build_report.chunks_written,
                "skipped_chunk_count": build_report.skipped_chunk_count,
                "outputs_parsed": len(outputs),
                "chunks_missing": len(missing_chunk_ids),
                "useful_chunks_promoted": useful_chunk_count,
                "snippets_written": write_report.snippets_written,
                "decisions_applied": len(block_category_updates),
                "changed_blocks": int(
                    refined_stage_result.refinement_report.get("changed_block_count") or 0
                ),
                "worker_count": (
                    int(phase_manifest.worker_count)
                    if phase_manifest is not None
                    else worker_count
                ),
                "validated_shards": int(promotion_report.get("validated_shards") or 0),
                "invalid_shards": int(promotion_report.get("invalid_shards") or 0),
                "missing_output_shards": int(promotion_report.get("missing_output_shards") or 0),
                "reviewed_shards_with_useful_chunks": review_rollup["reviewed_shards_with_useful_chunks"],
                "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
                "semantic_rejection_shard_count": review_rollup["semantic_rejection_shard_count"],
                "all_false_empty_shard_count": review_rollup["all_false_empty_shard_count"],
                "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
                "unreviewed_chunk_count": review_rollup["unreviewed_chunk_count"],
                "unreviewed_block_count": review_rollup["unreviewed_block_count"],
            },
            "timing": {"total_seconds": elapsed_seconds},
            "paths": {
                "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
                "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
                "knowledge_in_dir": str(knowledge_in_dir),
                "knowledge_phase_dir": str(knowledge_stage_dir),
                "snippets_path": str(write_report.snippets_path),
                "preview_path": str(write_report.preview_path),
                "manifest_path": str(manifest_path),
                **_runtime_artifact_paths(knowledge_stage_dir),
            },
            "missing_chunk_ids": missing_chunk_ids,
            "skipped_lane_counts": dict(build_report.skipped_lane_counts),
            "planning_warnings": list(build_report.planning_warnings),
            "review_summary": review_summary,
            "refinement_report": refined_report,
            "process_run": process_run_payload,
            "phase_worker_runtime": {
                "phase_key": "nonrecipe_knowledge_review",
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "worker_count": (
                    int(phase_manifest.worker_count)
                    if phase_manifest is not None
                    else worker_count
                ),
                "shard_count": (
                    int(phase_manifest.shard_count)
                    if phase_manifest is not None
                    else build_report.shards_written
                ),
                "assignment_strategy": (
                    str(phase_manifest.assignment_strategy)
                    if phase_manifest is not None
                    else "round_robin_v1"
                ),
                "task_packet_total": int(
                    (phase_manifest.runtime_metadata or {}).get("task_packet_total") or 0
                )
                if phase_manifest is not None
                else 0,
                "bundle_policy": str(
                    (phase_manifest.runtime_metadata or {}).get("bundle_policy") or ""
                ).strip()
                or "shard_round_robin_with_task_packets_v1",
                "worker_task_packet_counts": dict(
                    (phase_manifest.runtime_metadata or {}).get("worker_task_packet_counts")
                    or {}
                )
                if phase_manifest is not None
                else {},
                "max_task_packets_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("max_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "min_task_packets_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("min_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "telemetry": telemetry,
                "promotion_report": promotion_report,
                "worker_reports": worker_reports,
            },
            "review_status": review_status,
            "stage_status": (
                "completed_with_failures"
                if int(promotion_report.get("invalid_shards") or 0) > 0
                or int(promotion_report.get("missing_output_shards") or 0) > 0
                else "completed"
            ),
        }
        _write_json(llm_report, manifest_path)
    except KeyboardInterrupt:
        _mark_running_knowledge_status_files_interrupted(knowledge_stage_dir)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="interrupted",
            termination_cause="operator_interrupt",
            finalization_completeness="interrupted_before_finalization",
        )
        raise
    except Exception:
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="failed",
            termination_cause="unexpected_exception",
            finalization_completeness="stopped_before_finalization",
        )
        raise

    _write_knowledge_stage_status(
        stage_root=knowledge_stage_dir,
        manifest_path=manifest_path,
        stage_state=str(llm_report["stage_status"]),
        termination_cause="completed",
        finalization_completeness="complete",
    )

    return CodexFarmNonrecipeKnowledgeReviewResult(
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
        manifest_path=manifest_path,
        refined_stage_result=refined_stage_result,
        write_report=write_report,
    )


def _build_noop_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    stage_status: str,
    seed_nonrecipe_span_count: int = 0,
    chunk_count_before_pruning: int = 0,
    skipped_chunk_count: int = 0,
    skipped_lane_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    authority_mode = (
        "knowledge_not_run_no_nonrecipe_spans"
        if stage_status == "no_nonrecipe_spans"
        else "knowledge_not_run_all_chunks_skipped"
    )
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_seed_nonrecipe_spans",
        "authority_mode": authority_mode,
        "scored_effect": "seed_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "chunks_built_before_pruning": int(chunk_count_before_pruning),
            "shards_written": 0,
            "chunks_written": 0,
            "skipped_chunk_count": int(skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": 0,
            "useful_chunks_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "missing_output_shards": 0,
            "reviewed_shards_with_useful_chunks": 0,
            "reviewed_shards_all_other": 0,
            "semantic_rejection_shard_count": 0,
            "all_false_empty_shard_count": 0,
            "unreviewed_shard_count": 0,
            "unreviewed_chunk_count": 0,
            "unreviewed_block_count": 0,
        },
        "timing": {"total_seconds": 0.0},
        "paths": {
            "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
            "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": [],
        "skipped_lane_counts": dict(skipped_lane_counts or {}),
        "review_summary": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "chunk_count_before_pruning": int(chunk_count_before_pruning),
            "planned_chunk_count": 0,
            "reviewed_chunk_count": 0,
            "skipped_chunk_count": int(skipped_chunk_count),
            "skipped_noise_chunk_count": int((skipped_lane_counts or {}).get("noise") or 0),
            "skipped_low_signal_chunk_count": int((skipped_lane_counts or {}).get("low_signal") or 0),
            "planned_shard_count": 0,
            "reviewed_shard_count": 0,
            "validated_output_chunk_count": 0,
            "validated_shard_count": 0,
            "invalid_shard_count": 0,
            "missing_output_shard_count": 0,
            "reviewed_shards_with_useful_chunks": 0,
            "reviewed_shards_all_other": 0,
            "semantic_rejection_shard_count": 0,
            "all_false_empty_shard_count": 0,
            "unreviewed_shard_count": 0,
            "unreviewed_chunk_count": 0,
            "unreviewed_block_count": 0,
            "promoted_useful_chunk_count": 0,
            "promoted_snippet_count": 0,
        },
        "review_status": "complete",
        "stage_status": stage_status,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_knowledge_review",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": 0,
            "worker_reports": [],
        },
    }


def _build_runtime_failed_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    build_report: Any,
    elapsed_seconds: float,
    error: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "stage7_seed_nonrecipe_spans",
        "authority_mode": "knowledge_not_run_runtime_failed",
        "scored_effect": "seed_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(build_report.seed_nonrecipe_span_count),
            "chunks_built_before_pruning": int(build_report.chunk_count_before_pruning),
            "shards_written": int(build_report.shards_written),
            "chunks_written": int(build_report.chunks_written),
            "skipped_chunk_count": int(build_report.skipped_chunk_count),
            "outputs_parsed": 0,
            "chunks_missing": int(build_report.chunks_written),
            "useful_chunks_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "missing_output_shards": int(build_report.shards_written),
            "reviewed_shards_with_useful_chunks": 0,
            "reviewed_shards_all_other": 0,
            "semantic_rejection_shard_count": 0,
            "all_false_empty_shard_count": 0,
            "unreviewed_shard_count": int(build_report.shards_written),
            "unreviewed_chunk_count": int(build_report.chunks_written),
            "unreviewed_block_count": 0,
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {
            "seed_nonrecipe_spans_path": str(run_root / "08_nonrecipe_spans.json"),
            "final_knowledge_outputs_path": str(run_root / "09_knowledge_outputs.json"),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_chunk_ids": list(build_report.chunk_ids),
        "skipped_lane_counts": dict(build_report.skipped_lane_counts),
        "planning_warnings": list(build_report.planning_warnings),
        "review_summary": _build_review_summary(
            build_report=build_report,
            validated_output_count=0,
            planned_shard_count=int(build_report.shards_written),
            review_rollup={
                "validated_shard_count": 0,
                "invalid_shard_count": 0,
                "missing_output_shard_count": int(build_report.shards_written),
                "reviewed_shards_with_useful_chunks": 0,
                "reviewed_shards_all_other": 0,
                "semantic_rejection_shard_count": 0,
                "all_false_empty_shard_count": 0,
                "meaningfully_reviewed_shard_count": 0,
                "unreviewed_shard_count": int(build_report.shards_written),
                "unreviewed_chunk_count": int(build_report.chunks_written),
                "unreviewed_block_count": 0,
            },
            promoted_useful_chunk_count=0,
            promoted_snippet_count=0,
        ),
        "review_status": "unreviewed",
        "stage_status": "runtime_failed",
        "error": error,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_knowledge_review",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": int(build_report.shards_written),
            "worker_reports": [],
        },
    }


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _build_review_summary(
    *,
    build_report: Any,
    validated_output_count: int,
    planned_shard_count: int,
    review_rollup: Mapping[str, Any] | None,
    promoted_useful_chunk_count: int,
    promoted_snippet_count: int,
) -> dict[str, int]:
    skipped_lane_counts = dict(getattr(build_report, "skipped_lane_counts", {}) or {})
    counts = dict(review_rollup or {})
    planned_chunk_count = int(getattr(build_report, "chunks_written", 0) or 0)
    unreviewed_chunk_count = int(counts.get("unreviewed_chunk_count") or 0)
    return {
        "seed_nonrecipe_span_count": int(
            getattr(build_report, "seed_nonrecipe_span_count", 0) or 0
        ),
        "chunk_count_before_pruning": int(
            getattr(build_report, "chunk_count_before_pruning", 0) or 0
        ),
        "planned_chunk_count": planned_chunk_count,
        "reviewed_chunk_count": max(0, planned_chunk_count - unreviewed_chunk_count),
        "skipped_chunk_count": int(getattr(build_report, "skipped_chunk_count", 0) or 0),
        "skipped_noise_chunk_count": int(skipped_lane_counts.get("noise") or 0),
        "skipped_low_signal_chunk_count": int(skipped_lane_counts.get("low_signal") or 0),
        "planned_shard_count": int(planned_shard_count),
        "reviewed_shard_count": int(counts.get("meaningfully_reviewed_shard_count") or 0),
        "validated_output_chunk_count": int(validated_output_count),
        "validated_shard_count": int(counts.get("validated_shard_count") or 0),
        "invalid_shard_count": int(counts.get("invalid_shard_count") or 0),
        "missing_output_shard_count": int(counts.get("missing_output_shard_count") or 0),
        "reviewed_shards_with_useful_chunks": int(
            counts.get("reviewed_shards_with_useful_chunks") or 0
        ),
        "reviewed_shards_all_other": int(counts.get("reviewed_shards_all_other") or 0),
        "semantic_rejection_shard_count": int(
            counts.get("semantic_rejection_shard_count") or 0
        ),
        "all_false_empty_shard_count": int(counts.get("all_false_empty_shard_count") or 0),
        "unreviewed_shard_count": int(counts.get("unreviewed_shard_count") or 0),
        "unreviewed_chunk_count": unreviewed_chunk_count,
        "unreviewed_block_count": int(counts.get("unreviewed_block_count") or 0),
        "promoted_useful_chunk_count": int(promoted_useful_chunk_count),
        "promoted_snippet_count": int(promoted_snippet_count),
    }


def _build_knowledge_review_rollup(
    *,
    promotion_report: Mapping[str, Any] | None,
    build_report: Any,
) -> dict[str, int]:
    report = dict(promotion_report or {})
    validated_shard_count = int(report.get("validated_shards") or 0)
    invalid_shard_count = int(report.get("invalid_shards") or 0)
    missing_output_shard_count = int(report.get("missing_output_shards") or 0)
    reviewed_shards_with_useful_chunks = int(
        report.get("reviewed_shards_with_useful_chunks") or 0
    )
    reviewed_shards_all_other = int(report.get("reviewed_shards_all_other") or 0)
    semantic_rejection_shard_count = int(
        report.get("semantic_rejection_shard_count") or 0
    )
    all_false_empty_shard_count = int(report.get("all_false_empty_shard_count") or 0)
    unreviewed_chunk_count = int(
        report.get("unreviewed_chunk_count")
        or (
            int(getattr(build_report, "chunks_written", 0) or 0)
            if missing_output_shard_count > 0 and not report
            else 0
        )
    )
    unreviewed_block_count = int(report.get("unreviewed_block_count") or 0)
    return {
        "validated_shard_count": validated_shard_count,
        "invalid_shard_count": invalid_shard_count,
        "missing_output_shard_count": missing_output_shard_count,
        "reviewed_shards_with_useful_chunks": reviewed_shards_with_useful_chunks,
        "reviewed_shards_all_other": reviewed_shards_all_other,
        "semantic_rejection_shard_count": semantic_rejection_shard_count,
        "all_false_empty_shard_count": all_false_empty_shard_count,
        "meaningfully_reviewed_shard_count": (
            reviewed_shards_with_useful_chunks + reviewed_shards_all_other
        ),
        "unreviewed_shard_count": invalid_shard_count + missing_output_shard_count,
        "unreviewed_chunk_count": unreviewed_chunk_count,
        "unreviewed_block_count": unreviewed_block_count,
    }


def _derive_knowledge_review_status(review_rollup: Mapping[str, Any]) -> str:
    reviewed_shard_count = int(review_rollup.get("meaningfully_reviewed_shard_count") or 0)
    unreviewed_shard_count = int(review_rollup.get("unreviewed_shard_count") or 0)
    if reviewed_shard_count <= 0 and unreviewed_shard_count > 0:
        return "unreviewed"
    if unreviewed_shard_count > 0:
        return "partial"
    return "complete"


def _derive_knowledge_authority_mode(
    *,
    refined_stage_result: NonRecipeStageResult,
    review_rollup: Mapping[str, Any],
) -> str:
    if int(refined_stage_result.refinement_report.get("changed_block_count") or 0) > 0:
        return "knowledge_refined_final"
    review_status = _derive_knowledge_review_status(review_rollup)
    if review_status == "unreviewed":
        return "knowledge_unreviewed_seed_kept"
    if review_status == "partial":
        return "knowledge_partially_reviewed_seed_kept"
    return "knowledge_reviewed_seed_kept"


def _runtime_artifact_paths(knowledge_stage_dir: Path) -> dict[str, str]:
    return {
        "stage_status_path": str(knowledge_stage_dir / _KNOWLEDGE_STAGE_STATUS_FILE_NAME),
        "phase_manifest_path": str(knowledge_stage_dir / "phase_manifest.json"),
        "shard_manifest_path": str(knowledge_stage_dir / "shard_manifest.jsonl"),
        "task_status_path": str(knowledge_stage_dir / _KNOWLEDGE_TASK_STATUS_FILE_NAME),
        "worker_assignments_path": str(knowledge_stage_dir / "worker_assignments.json"),
        "promotion_report_path": str(knowledge_stage_dir / "promotion_report.json"),
        "telemetry_path": str(knowledge_stage_dir / "telemetry.json"),
        "failures_path": str(knowledge_stage_dir / "failures.json"),
        "proposals_dir": str(knowledge_stage_dir / "proposals"),
    }


def _run_direct_knowledge_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    runner: CodexExecRunner,
    worker_count: int,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    progress_worker_total: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1], dict[str, Any]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "task_manifest": "task_manifest.jsonl",
        "task_status": _KNOWLEDGE_TASK_STATUS_FILE_NAME,
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_workers_v1(
        run_root=run_root,
        shards=shards,
        worker_count=worker_count,
    )
    task_plans_by_shard_id = {
        shard.shard_id: _build_knowledge_task_plans(shard)
        for shard in shards
    }
    task_entries = [
        task_entry
        for shard in shards
        for task_entry in _knowledge_task_runtime_entries_for_shard(
            shard=shard,
            task_plans_by_shard_id=task_plans_by_shard_id,
        )
    ]
    _write_jsonl(
        run_root / artifacts["shard_manifest"],
        [asdict(shard) for shard in shards],
    )
    _write_jsonl(
        run_root / artifacts["task_manifest"],
        [asdict(task_entry) for task_entry in task_entries],
    )
    _write_json(
        [asdict(assignment) for assignment in assignments],
        run_root / artifacts["worker_assignments"],
    )
    task_status_tracker = _build_knowledge_task_status_tracker(
        path=run_root / artifacts["task_status"],
        task_entries=task_entries,
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    total_shards = len(shards)
    total_task_packets = sum(
        len(_progress_task_ids_for_knowledge_shard(
            shard_id=shard.shard_id,
            task_plans_by_shard_id=task_plans_by_shard_id,
        ))
        for shard in shards
    )
    packet_distribution = _summarize_knowledge_task_packet_distribution(
        assignments=assignments,
        task_plans_by_shard_id=task_plans_by_shard_id,
    )
    displayed_worker_total = (
        max(0, int(progress_worker_total))
        if progress_worker_total is not None
        else worker_count
    )
    progress_state = _KnowledgePhaseProgressState(
        progress_callback=progress_callback,
        total_shards=total_shards,
        total_task_packets=total_task_packets,
        worker_total=displayed_worker_total,
        worker_order=tuple(assignment.worker_id for assignment in assignments),
        worker_states={
            assignment.worker_id: _KnowledgeWorkerProgressState(
                worker_id=assignment.worker_id,
                shard_ids=assignment.shard_ids,
                pending_shard_ids=list(assignment.shard_ids),
                total_task_packets=sum(
                    len(
                        _progress_task_ids_for_knowledge_shard(
                            shard_id=shard_id,
                            task_plans_by_shard_id=task_plans_by_shard_id,
                        )
                    )
                    for shard_id in assignment.shard_ids
                ),
            )
            for assignment in assignments
        },
    )
    progress_state.emit(force=True)
    cohort_watchdog_state = _KnowledgeCohortWatchdogState()
    recovery_governor = _KnowledgeRecoveryGovernor()
    interruption_requested = threading.Event()

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        progress_state.mark_shard_completed(worker_id=worker_id, shard_id=shard_id)

    runtime_metadata_payload = {
        **dict(runtime_metadata or {}),
        "task_packet_total": total_task_packets,
        **packet_distribution,
    }
    manifest = _write_knowledge_runtime_summary_artifacts(
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=run_root,
        artifacts=artifacts,
        assignments=assignments,
        shards=shards,
        settings=settings,
        runtime_metadata=runtime_metadata_payload,
        worker_reports=worker_reports,
        all_proposals=all_proposals,
        failures=failures,
        stage_rows=stage_rows,
    )
    executor = ThreadPoolExecutor(
        max_workers=max(1, len(assignments)),
        thread_name_prefix="knowledge-worker",
    )
    try:
        futures_by_worker_id = {
            assignment.worker_id: executor.submit(
                _run_direct_knowledge_worker_assignment_v1,
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                cohort_watchdog_state=cohort_watchdog_state,
                recovery_governor=recovery_governor,
                shard_completed_callback=_mark_shard_completed,
                progress_state=progress_state,
                task_status_tracker=task_status_tracker,
                interruption_requested=interruption_requested,
            )
            for assignment in assignments
        }
        try:
            for assignment in assignments:
                result = futures_by_worker_id[assignment.worker_id].result()
                worker_reports.append(result.report)
                all_proposals.extend(result.proposals)
                failures.extend(result.failures)
                stage_rows.extend(result.stage_rows)
        except KeyboardInterrupt:
            interruption_requested.set()
            task_status_tracker.mark_interrupted()
            _mark_running_knowledge_status_files_interrupted(run_root)
            _write_knowledge_runtime_summary_artifacts(
                phase_key=phase_key,
                pipeline_id=pipeline_id,
                run_root=run_root,
                artifacts=artifacts,
                assignments=assignments,
                shards=shards,
                settings=settings,
                runtime_metadata=runtime_metadata_payload,
                worker_reports=worker_reports,
                all_proposals=all_proposals,
                failures=failures,
                stage_rows=stage_rows,
            )
            for future in futures_by_worker_id.values():
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    finally:
        if not interruption_requested.is_set():
            executor.shutdown(wait=True, cancel_futures=False)
    manifest = _write_knowledge_runtime_summary_artifacts(
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=run_root,
        artifacts=artifacts,
        assignments=assignments,
        shards=shards,
        settings=settings,
        runtime_metadata=runtime_metadata_payload,
        worker_reports=worker_reports,
        all_proposals=all_proposals,
        failures=failures,
        stage_rows=stage_rows,
    )
    process_run_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=[
            dict(report.runner_result or {})
            for report in worker_reports
            if isinstance(report.runner_result, Mapping)
        ],
        stage_rows=stage_rows,
    )
    return manifest, worker_reports, process_run_payload


def _write_knowledge_runtime_summary_artifacts(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    artifacts: Mapping[str, str],
    assignments: Sequence[WorkerAssignmentV1],
    shards: Sequence[ShardManifestEntryV1],
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    worker_reports: Sequence[WorkerExecutionReportV1],
    all_proposals: Sequence[ShardProposalV1],
    failures: Sequence[Mapping[str, Any]],
    stage_rows: Sequence[Mapping[str, Any]],
) -> PhaseManifestV1:
    def _proposal_has_validation_error(
        proposal: ShardProposalV1,
        *,
        error_code: str,
    ) -> bool:
        target_error = str(error_code).strip()
        if not target_error:
            return False
        direct_errors = {
            str(error).strip()
            for error in (proposal.validation_errors or ())
            if str(error).strip()
        }
        if target_error in direct_errors:
            return True
        task_aggregation = _coerce_dict((proposal.metadata or {}).get("task_aggregation"))
        task_errors_by_task_id = task_aggregation.get("task_validation_errors_by_task_id")
        if not isinstance(task_errors_by_task_id, Mapping):
            return False
        for task_errors in task_errors_by_task_id.values():
            if any(str(error).strip() == target_error for error in (task_errors or ())):
                return True
        return False

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(1 for proposal in all_proposals if proposal.status == "missing_output"),
        "reviewed_shards_with_useful_chunks": sum(
            1
            for proposal in all_proposals
            if proposal.status == "validated"
            and bool((proposal.metadata or {}).get("reviewed_with_useful_chunks"))
        ),
        "reviewed_shards_all_other": sum(
            1
            for proposal in all_proposals
            if proposal.status == "validated"
            and bool((proposal.metadata or {}).get("reviewed_all_other"))
        ),
        "semantic_rejection_shard_count": sum(
            1
            for proposal in all_proposals
            if proposal.status == "invalid"
            and (
                _proposal_has_validation_error(
                    proposal,
                    error_code="semantic_all_false_empty_shard",
                )
                or bool((proposal.metadata or {}).get("semantic_rejection"))
            )
        ),
        "all_false_empty_shard_count": sum(
            1
            for proposal in all_proposals
            if _proposal_has_validation_error(
                proposal,
                error_code="semantic_all_false_empty_shard",
            )
        ),
        "unreviewed_chunk_count": sum(
            int((proposal.metadata or {}).get("owned_chunk_count") or 0)
            for proposal in all_proposals
            if proposal.status != "validated"
        ),
        "unreviewed_block_count": sum(
            int((proposal.metadata or {}).get("owned_block_count") or 0)
            for proposal in all_proposals
            if proposal.status != "validated"
        ),
    }
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
        "rows": [dict(row) for row in stage_rows],
        "summary": _summarize_direct_rows(stage_rows),
    }
    _write_json(promotion_report, run_root / artifacts["promotion_report"])
    _write_json(telemetry, run_root / artifacts["telemetry"])
    _write_json([dict(row) for row in failures], run_root / artifacts["failures"])

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        max_turns_per_shard=1,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(asdict(manifest), run_root / artifacts["phase_manifest"])
    return manifest


def _assign_workers_v1(
    *,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shards),
    )
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [
        WorkerAssignmentV1(
            worker_id=f"worker-{index + 1:03d}",
            shard_ids=tuple(bucket),
            workspace_root=str(run_root / "workers" / f"worker-{index + 1:03d}"),
        )
        for index, bucket in enumerate(buckets)
    ]


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")


@dataclass(slots=True)
class _KnowledgeTaskStatusTracker:
    path: Path
    rows_by_task_id: dict[str, dict[str, Any]]
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._write_locked()

    def start_attempt(
        self,
        *,
        task_id: str,
        worker_id: str,
        attempt_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None or bool(row.get("terminal")):
                return
            cleaned_attempt_type = str(attempt_type).strip() or None
            row["worker_id"] = str(worker_id).strip() or None
            row["active_attempt_type"] = cleaned_attempt_type
            row["last_attempt_type"] = cleaned_attempt_type
            row["attempt_state"] = "running"
            if cleaned_attempt_type == "main_worker":
                row["state"] = "leased"
            merged_metadata = dict(row.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            row["metadata"] = merged_metadata
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_main_output_written(
        self,
        *,
        task_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None or bool(row.get("terminal")):
                return
            row["state"] = "main_output_written"
            merged_metadata = dict(row.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            row["metadata"] = merged_metadata
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_terminal(
        self,
        *,
        task_id: str,
        worker_id: str,
        terminal_state: str,
        attempt_type: str,
        proposal_status: str | None,
        validation_errors: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        terminal_reason_code: str | None = None,
        terminal_reason_detail: str | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None:
                return
            row["worker_id"] = str(worker_id).strip() or None
            row["state"] = str(terminal_state).strip() or "unknown"
            row["terminal"] = True
            row["active_attempt_type"] = None
            row["last_attempt_type"] = str(attempt_type).strip() or None
            row["attempt_state"] = "completed"
            row["proposal_status"] = str(proposal_status).strip() if proposal_status is not None else None
            row["validation_errors"] = [
                str(error).strip()
                for error in validation_errors
                if str(error).strip()
            ]
            row["metadata"] = dict(metadata or {})
            row["terminal_reason_code"] = str(terminal_reason_code).strip() or None
            row["terminal_reason_detail"] = str(terminal_reason_detail).strip() or None
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_interrupted(self) -> None:
        with self.lock:
            changed = False
            interrupted_at = _format_utc_now()
            for row in self.rows_by_task_id.values():
                if bool(row.get("terminal")):
                    continue
                row["state"] = "cancelled_due_to_interrupt"
                row["terminal"] = True
                row["attempt_state"] = "cancelled"
                row["last_attempt_type"] = row.get("active_attempt_type") or row.get("last_attempt_type")
                row["active_attempt_type"] = None
                metadata = dict(row.get("metadata") or {})
                metadata["interruption_cause"] = "operator_interrupt"
                row["metadata"] = metadata
                row["terminal_reason_code"] = "cancelled_stage_interrupt"
                row["terminal_reason_detail"] = "stage interrupted before this packet reached a terminal outcome"
                row["updated_at_utc"] = interrupted_at
                changed = True
            if changed:
                self._write_locked()

    def state_counts(self) -> dict[str, int]:
        with self.lock:
            counts: dict[str, int] = {}
            for row in self.rows_by_task_id.values():
                state = str(row.get("state") or "").strip()
                if not state:
                    continue
                counts[state] = counts.get(state, 0) + 1
            return counts

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for task_id in sorted(self.rows_by_task_id):
                handle.write(json.dumps(self.rows_by_task_id[task_id], sort_keys=True))
                handle.write("\n")
        tmp_path.replace(self.path)


def _build_knowledge_task_status_tracker(
    *,
    path: Path,
    task_entries: Sequence[TaskManifestEntryV1],
) -> _KnowledgeTaskStatusTracker:
    created_at = _format_utc_now()
    rows_by_task_id: dict[str, dict[str, Any]] = {}
    for task_entry in task_entries:
        task_id = str(task_entry.task_id).strip()
        if not task_id:
            continue
        rows_by_task_id[task_id] = {
            "schema_version": _KNOWLEDGE_TASK_STATUS_SCHEMA_VERSION,
            "task_id": task_id,
            "task_kind": str(task_entry.task_kind).strip() or None,
            "parent_shard_id": str(task_entry.parent_shard_id).strip() or None,
            "owned_ids": [str(value) for value in task_entry.owned_ids],
            "worker_id": None,
            "state": "pending",
            "terminal": False,
            "active_attempt_type": None,
            "last_attempt_type": None,
            "attempt_state": "pending",
            "proposal_status": None,
            "validation_errors": [],
            "metadata": dict(task_entry.metadata or {}),
            "terminal_reason_code": None,
            "terminal_reason_detail": None,
            "updated_at_utc": created_at,
        }
    return _KnowledgeTaskStatusTracker(path=path, rows_by_task_id=rows_by_task_id)


def _load_task_status_state_counts(path: Path) -> dict[str, int]:
    if not path.exists() or not path.is_file():
        return {}
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        state = str(payload.get("state") or "").strip()
        if not state:
            continue
        counts[state] = counts.get(state, 0) + 1
    return counts


def _knowledge_artifact_dir_has_files(path: Path) -> bool:
    return path.exists() and path.is_dir() and any(child.is_file() for child in path.iterdir())


def _collect_knowledge_pre_kill_failure_counts(stage_root: Path) -> dict[str, Any]:
    worker_terminal_states: dict[str, int] = {}
    worker_reason_codes: dict[str, int] = {}
    for live_status_path in stage_root.rglob("*live_status.json"):
        payload = _load_json_dict(live_status_path)
        if not payload:
            continue
        state = str(payload.get("state") or "").strip()
        reason_code = str(payload.get("reason_code") or "").strip()
        if state:
            worker_terminal_states[state] = worker_terminal_states.get(state, 0) + 1
        if reason_code:
            worker_reason_codes[reason_code] = worker_reason_codes.get(reason_code, 0) + 1
    task_state_counts = _load_task_status_state_counts(stage_root / _KNOWLEDGE_TASK_STATUS_FILE_NAME)
    return {
        "worker_terminal_states": worker_terminal_states,
        "worker_reason_codes": worker_reason_codes,
        "task_terminal_states": task_state_counts,
    }


def _finalize_stale_followup_attempt(
    *,
    followup_kind: str,
    live_status_path: Path,
    status_path: Path,
    terminal_reason_code: str,
    terminal_reason_detail: str,
) -> bool:
    payload = _load_json_dict(live_status_path)
    if not payload or str(payload.get("state") or "").strip() not in {"running", "pending"}:
        return False
    finished_at = _format_utc_now()
    payload["state"] = str(terminal_reason_code).strip() or "superseded_by_terminal_packet"
    payload["reason_code"] = str(terminal_reason_code).strip() or None
    payload["reason_detail"] = str(terminal_reason_detail).strip() or None
    payload["retryable"] = False
    payload["finished_at_utc"] = finished_at
    _write_json(dict(payload), live_status_path)
    status_payload: dict[str, Any] = {
        "status": str(terminal_reason_code).strip() or "superseded_by_terminal_packet",
        "state": str(terminal_reason_code).strip() or "superseded_by_terminal_packet",
        "reason_code": str(terminal_reason_code).strip() or None,
        "reason_detail": str(terminal_reason_detail).strip() or None,
        "retryable": False,
    }
    if str(followup_kind).strip() == "repair":
        status_payload["attempted"] = True
    _write_json(status_payload, status_path)
    return True


def _finalize_terminal_followups_for_task_root(
    task_root: Path,
    *,
    terminal_reason_code: str,
    terminal_reason_detail: str,
) -> None:
    _finalize_stale_followup_attempt(
        followup_kind="watchdog_retry",
        live_status_path=task_root / "watchdog_retry" / "live_status.json",
        status_path=task_root / "watchdog_retry" / "status.json",
        terminal_reason_code=terminal_reason_code,
        terminal_reason_detail=terminal_reason_detail,
    )
    _finalize_stale_followup_attempt(
        followup_kind="repair",
        live_status_path=task_root / "repair_live_status.json",
        status_path=task_root / "repair_status.json",
        terminal_reason_code=terminal_reason_code,
        terminal_reason_detail=terminal_reason_detail,
    )


def _mark_running_knowledge_status_files_interrupted(stage_root: Path) -> None:
    for live_status_path in stage_root.rglob("*live_status.json"):
        if live_status_path.name == "repair_live_status.json":
            _finalize_stale_followup_attempt(
                followup_kind="repair",
                live_status_path=live_status_path,
                status_path=live_status_path.parent / "repair_status.json",
                terminal_reason_code="cancelled_stage_interrupt",
                terminal_reason_detail="stage interrupted before repair completed",
            )
            continue
        if live_status_path.name != "live_status.json":
            continue
        parent_name = live_status_path.parent.name
        grandparent_name = live_status_path.parent.parent.name if live_status_path.parent.parent else ""
        if parent_name == "watchdog_retry" or grandparent_name == "retry_shards":
            _finalize_stale_followup_attempt(
                followup_kind="watchdog_retry",
                live_status_path=live_status_path,
                status_path=live_status_path.parent / "status.json",
                terminal_reason_code="cancelled_stage_interrupt",
                terminal_reason_detail="stage interrupted before follow-up completed",
            )
            continue
        payload = _load_json_dict(live_status_path)
        if not payload or str(payload.get("state") or "").strip() != "running":
            continue
        payload["state"] = "cancelled_due_to_interrupt"
        payload["reason_code"] = "operator_interrupt"
        payload["reason_detail"] = "stage interrupted before this attempt completed"
        payload["retryable"] = False
        payload["finished_at_utc"] = _format_utc_now()
        _write_json(dict(payload), live_status_path)


def _write_knowledge_stage_status(
    *,
    stage_root: Path,
    manifest_path: Path,
    stage_state: str,
    termination_cause: str,
    finalization_completeness: str,
) -> None:
    artifact_paths = {
        "phase_manifest.json": stage_root / "phase_manifest.json",
        "shard_manifest.jsonl": stage_root / "shard_manifest.jsonl",
        "task_manifest.jsonl": stage_root / "task_manifest.jsonl",
        "task_status.jsonl": stage_root / _KNOWLEDGE_TASK_STATUS_FILE_NAME,
        "worker_assignments.json": stage_root / "worker_assignments.json",
        "promotion_report.json": stage_root / "promotion_report.json",
        "telemetry.json": stage_root / "telemetry.json",
        "failures.json": stage_root / "failures.json",
        "knowledge_manifest.json": manifest_path,
        "proposals/*": stage_root / "proposals",
    }
    interrupted_before_finalization = finalization_completeness == "interrupted_before_finalization"
    artifact_states: dict[str, str] = {}
    for artifact_key, path in artifact_paths.items():
        present = (
            _knowledge_artifact_dir_has_files(path)
            if artifact_key == "proposals/*"
            else path.exists()
        )
        if present:
            artifact_states[artifact_key] = "present"
        elif interrupted_before_finalization:
            artifact_states[artifact_key] = "skipped_due_to_interrupt"
        else:
            artifact_states[artifact_key] = "unexpectedly_missing"
    _write_json(
        {
            "schema_version": _KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION,
            "stage_key": "nonrecipe_knowledge_review",
            "stage_state": str(stage_state).strip() or None,
            "termination_cause": str(termination_cause).strip() or None,
            "finalization_completeness": str(finalization_completeness).strip() or None,
            "artifact_states": artifact_states,
            "pre_kill_failure_counts": _collect_knowledge_pre_kill_failure_counts(stage_root),
        },
        stage_root / _KNOWLEDGE_STAGE_STATUS_FILE_NAME,
    )


def _terminal_knowledge_task_state(
    *,
    proposal_status: str,
    supervision_state: str | None,
    watchdog_retry_status: str = "not_attempted",
    retry_status: str = "not_attempted",
    repair_status: str = "not_attempted",
) -> str:
    if proposal_status == "validated":
        if repair_status == "repaired":
            return "repair_recovered"
        if retry_status == "recovered" or watchdog_retry_status == "recovered":
            return "retry_recovered"
        return "validated"
    if repair_status == "failed":
        return "repair_failed"
    if retry_status == "failed" or watchdog_retry_status == "failed":
        return "retry_failed"
    if str(supervision_state or "").strip() == "watchdog_killed":
        return "watchdog_killed"
    if proposal_status == "missing_output":
        return "missing_output"
    return "invalid_output"


def _terminal_knowledge_attempt_type(
    *,
    watchdog_retry_status: str = "not_attempted",
    retry_status: str = "not_attempted",
    repair_status: str = "not_attempted",
) -> str:
    if repair_status != "not_attempted":
        return "repair"
    if retry_status != "not_attempted":
        return "retry_split"
    if watchdog_retry_status != "not_attempted":
        return "watchdog_retry"
    return "main_worker"


def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _build_knowledge_workspace_worker_prompt(
    *,
    tasks: Sequence[TaskManifestEntryV1],
) -> str:
    final_categories_text = "`, `".join(ALLOWED_KNOWLEDGE_FINAL_CATEGORIES)
    reviewer_categories_text = "`, `".join(ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES)
    task_ids = [str(task.task_id).strip() for task in tasks if str(task.task_id).strip()]
    lines = [
        "You are a non-recipe knowledge review worker in a bounded local workspace.",
        "",
        "Process the repo-written ordered packet queue in `assigned_tasks.json`. The current working directory is already the workspace root.",
        "Do not inspect the repository or explore beyond this workspace.",
        "",
        "Required local loop:",
        "1. Open `worker_manifest.json`, then open `assigned_tasks.json`.",
        "2. `assigned_tasks.json` is authoritative for this worker. Process its task rows in order. Do not wait for the repo to mutate other lease files mid-session.",
        "3. Each task row tells you the packet id plus `metadata.input_path`, `metadata.hint_path`, and `metadata.result_path`. Open those named files directly instead of exploring the workspace or dumping the whole queue back to yourself.",
        "4. Workspace-local shell commands are allowed when they materially help, but keep them bounded to the worker root. Use `scratch/` or short-lived local temp files such as `/tmp` for helper files, prefer a short direct `python3` helper or one targeted query against the current task row's named files, and use each task row's `metadata.result_path` only for the final packet result.",
        "5. Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.",
        "6. Write one completed semantic packet result file per assigned task row. Finish the whole ordered queue before stopping.",
        "7. Do not invent extra packets, skip owned chunks, or write outside the listed `metadata.result_path` files.",
        "8. Do not invent your own batch scheduler, dump the whole `assigned_tasks.json` inventory back to yourself, or run extra shell checks against finished files in `out/` unless a listed task result is clearly incomplete or invalid while you are still writing it.",
        "",
        "Semantic packet result contract for each assigned result path:",
        "- Write exactly one JSON object.",
        "- Use semantic field names, not the compact canonical bundle envelope.",
        "- Top level keys: `packet_id`, `chunk_results`.",
        "- `packet_id` must equal the current task row's `task_id`.",
        "- `chunk_results` must contain exactly one result row for each owned chunk in the current task row and no extras.",
        "- Each result row uses `chunk_id`, `is_useful`, `block_decisions`, `snippets`, and optional `reason_code`.",
        "- Each block decision uses `block_index`, `category`, and optional `reviewer_category`.",
        f"- `category` must be exactly one of `{final_categories_text}`.",
        (
            f"- `reviewer_category` may be omitted or must be one of "
            f"`{reviewer_categories_text}`."
        ),
        "- If `category` is `knowledge`, `reviewer_category` must be `knowledge`.",
        (
            "- Never invent category labels such as `content`, `noise`, or `heading`; "
            "those values are invalid."
        ),
        "- Each snippet uses `body` and `evidence`; each evidence row uses `block_index` and `quote`.",
        (
            "- Keep each snippet body as a short grounded extraction, not a whole-block dump, "
            "full-chunk echo, or stitched quote list."
        ),
        "- Keep all block decisions and snippet evidence on the current task row's own block indices only.",
        "- If a chunk is not useful, still include its result row with `is_useful: false` and an empty snippet list.",
        "- Treat each task row's `metadata.hint_path` file as guidance and its `metadata.input_path` file as the authoritative owned input.",
        "- The repo will write the final canonical `v` / `bid` / `r` packet artifact after it accepts your semantic result.",
        "",
        "Do not return the packet outputs in your final message. The authoritative result is the set of files written to the repo-declared local result paths.",
    ]
    if task_ids:
        lines.extend(
            [
                "",
                "Assigned packet ids in required processing order:",
                *[f"- {task_id}" for task_id in task_ids],
            ]
        )
    return "\n".join(lines)


def _write_knowledge_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
) -> None:
    payload = _coerce_dict(shard.input_payload)
    chunks = list(payload.get("c") or [])
    nearby_recipe_blocks: list[int] = []
    for value in (_coerce_dict(payload.get("g")).get("r") or []):
        try:
            nearby_recipe_blocks.append(int(value))
        except (TypeError, ValueError):
            continue
    chunk_summaries: list[str] = []
    heading_only_count = 0
    prose_chunk_count = 0
    for chunk in chunks[:12]:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = str(chunk.get("cid") or "").strip() or "[unknown chunk]"
        blocks = [block for block in (chunk.get("b") or []) if isinstance(block, Mapping)]
        block_indices = [int(block.get("i", 0)) for block in blocks]
        heading_levels = [int(block.get("hl", 0)) for block in blocks if block.get("hl") is not None]
        previews = [preview_text(block.get("t"), max_chars=70) for block in blocks[:3]]
        all_short = bool(blocks) and all(len(str(block.get("t") or "").split()) <= 6 for block in blocks)
        has_heading = bool(heading_levels)
        profile = "mixed"
        if has_heading and all_short:
            profile = "heading_or_navigation_candidate"
            heading_only_count += 1
        elif any(len(str(block.get("t") or "").split()) >= 12 for block in blocks):
            profile = "prose_or_reference_candidate"
            prose_chunk_count += 1
        chunk_summaries.append(
            f"`{chunk_id}` blocks `{block_indices[0] if block_indices else '?'}..{block_indices[-1] if block_indices else '?'}` profile `{profile}` preview `{ ' / '.join(previews) or '[empty]' }`"
        )
    write_worker_hint_markdown(
        path,
        title=f"Knowledge review hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only.",
            "Open this file first, then open the authoritative `in/<shard_id>.json` file.",
            f"Chunk count: {len(chunks)}. Heading-heavy chunks: {heading_only_count}. Longer prose/reference chunks: {prose_chunk_count}.",
            (
                "Nearby recipe guardrail block indices: "
                + (", ".join(str(value) for value in nearby_recipe_blocks[:12]) if nearby_recipe_blocks else "none")
                + "."
            ),
        ],
        sections=[
            (
                "How to use this packet",
                [
                    "Use the hint file to understand whether this bundle looks like front matter, navigation, headings, or real reusable technique/reference text.",
                    "Use only chunk-local block text from `in/<shard_id>.json` as evidence in the final output.",
                    "A short chunk can still be real knowledge if it is genuinely technical or reference-like.",
                ],
            ),
            ("Chunk previews", chunk_summaries or ["No chunk previews available."]),
        ],
    )


def _distribute_knowledge_session_value(value: Any, task_count: int) -> list[int]:
    normalized_task_count = max(1, int(task_count))
    total = int(value or 0)
    base, remainder = divmod(total, normalized_task_count)
    return [base + (1 if index < remainder else 0) for index in range(normalized_task_count)]


def _build_knowledge_workspace_task_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    runtime_task_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path,
    worker_prompt_path: Path,
    task_count: int,
    task_index: int,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    telemetry = payload.get("telemetry")
    row_payload = None
    if isinstance(telemetry, Mapping):
        rows = telemetry.get("rows")
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            if isinstance(first_row, Mapping):
                row_payload = dict(first_row)
    request_input_file_str = str(request_input_file)
    request_input_file_bytes = (
        request_input_file.stat().st_size if request_input_file.exists() else None
    )
    worker_prompt_file_str = str(worker_prompt_path)
    if row_payload is not None:
        share_fields = (
            "duration_ms",
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "visible_input_tokens",
            "visible_output_tokens",
            "wrapper_overhead_tokens",
        )
        for field_name in share_fields:
            shares = _distribute_knowledge_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        row_payload["tokens_total"] = (
            int(row_payload.get("tokens_input") or 0)
            + int(row_payload.get("tokens_cached_input") or 0)
            + int(row_payload.get("tokens_output") or 0)
            + int(row_payload.get("tokens_reasoning") or 0)
        )
        row_payload["prompt_input_mode"] = "workspace_worker"
        row_payload["request_input_file"] = request_input_file_str
        row_payload["request_input_file_bytes"] = request_input_file_bytes
        row_payload["worker_prompt_file"] = worker_prompt_file_str
        row_payload["worker_session_task_count"] = task_count
        row_payload["worker_session_primary_row"] = task_index == 0
        row_payload["runtime_task_id"] = runtime_task_id
        row_payload["runtime_parent_shard_id"] = shard_id
        if task_index > 0:
            row_payload["command_execution_count"] = 0
            row_payload["command_execution_commands"] = []
            row_payload["reasoning_item_count"] = 0
            row_payload["reasoning_item_types"] = []
            row_payload["codex_event_count"] = 0
            row_payload["codex_event_types"] = []
            row_payload["output_preview"] = None
            row_payload["output_preview_chars"] = 0
        telemetry["rows"] = [row_payload]
        telemetry["summary"] = _summarize_direct_rows([row_payload])
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": _run_result_process_status(run_result),
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "workspace_worker",
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "worker_prompt_file": worker_prompt_file_str,
        "runtime_task_id": runtime_task_id,
        "runtime_parent_shard_id": shard_id,
    }
    return payload


def _build_knowledge_inline_attempt_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    prompt_input_mode: str,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            row_payload["prompt_input_mode"] = prompt_input_mode
            row_payload["request_input_file"] = None
            row_payload["request_input_file_bytes"] = None
    summary_payload = telemetry.get("summary") if isinstance(telemetry, dict) else None
    if isinstance(summary_payload, dict):
        summary_payload["prompt_input_mode"] = prompt_input_mode
        summary_payload["request_input_file_bytes_total"] = None
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": _run_result_process_status(run_result),
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": prompt_input_mode,
    }
    return payload


def _run_knowledge_workspace_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    task_plans_by_shard_id = {
        shard.shard_id: _build_knowledge_task_plans(shard)
        for shard in assigned_shards
    }
    if any(task_plans for task_plans in task_plans_by_shard_id.values()):
        return _run_knowledge_workspace_worker_assignment_taskized_v1(
            run_root=run_root,
            assignment=assignment,
            artifacts=artifacts,
            assigned_shards=assigned_shards,
            task_plans_by_shard_id=task_plans_by_shard_id,
            worker_root=worker_root,
            in_dir=in_dir,
            hints_dir=hints_dir,
            shard_dir=shard_dir,
            logs_dir=logs_dir,
            runner=runner,
            pipeline_id=pipeline_id,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            output_schema_path=output_schema_path,
            cohort_watchdog_state=cohort_watchdog_state,
            recovery_governor=recovery_governor,
            shard_completed_callback=shard_completed_callback,
            progress_state=progress_state,
            task_status_tracker=task_status_tracker,
            interruption_requested=interruption_requested,
        )
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    runnable_shards: list[ShardManifestEntryV1] = []

    for shard in assigned_shards:
        input_path = in_dir / f"{shard.shard_id}.json"
        hint_path = hints_dir / f"{shard.shard_id}.md"
        _write_worker_input(path=input_path, payload=shard.input_payload, input_text=shard.input_text)
        _write_knowledge_worker_hint(path=hint_path, shard=shard)
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        shard_prompt_text = build_knowledge_direct_prompt(_coerce_dict(shard.input_payload))
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            runnable_shards.append(shard)
            continue
        (shard_root / "prompt.txt").write_text(shard_prompt_text, encoding="utf-8")
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text=shard_prompt_text,
            output_schema_path=output_schema_path,
            working_dir=worker_root,
            reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
            reason_detail=str(
                preflight_failure.get("reason_detail") or "knowledge shard failed preflight"
            ),
        )
        _write_live_status(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
            proposal_path,
        )
        _write_json(
            {
                "error": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
            },
            shard_root / "proposal.json",
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "watchdog_retry_attempted": False,
                    "watchdog_retry_status": "not_attempted",
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                },
            )
        )
        if task_status_tracker is not None:
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state="preflight_rejected",
                attempt_type="preflight",
                proposal_status="missing_output",
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                },
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    if runnable_shards:
        workspace_prompt_tasks = _build_knowledge_workspace_task_runtime_entries(
            tuple(
                _KnowledgeTaskPlan(
                    task_id=shard.shard_id,
                    parent_shard_id=shard.shard_id,
                    manifest_entry=shard,
                )
                for shard in runnable_shards
            )
        )
        worker_prompt_text = _build_knowledge_workspace_worker_prompt(
            tasks=workspace_prompt_tasks
        )
        worker_prompt_path = worker_root / "prompt.txt"
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            (shard_root / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
        if task_status_tracker is not None:
            for task_entry in workspace_prompt_tasks:
                task_metadata = dict(task_entry.metadata or {})
                task_status_tracker.start_attempt(
                    task_id=task_entry.task_id,
                    worker_id=assignment.worker_id,
                    attempt_type="main_worker",
                    metadata={
                        "lease_sequence": int(task_metadata.get("lease_sequence") or 0),
                        "lease_total": int(task_metadata.get("lease_total") or len(workspace_prompt_tasks)),
                        "input_path": task_metadata.get("input_path"),
                        "hint_path": task_metadata.get("hint_path"),
                        "result_path": task_metadata.get("result_path"),
                        "workspace_processing_contract": task_metadata.get(
                            "workspace_processing_contract"
                        ),
                    },
                )
        run_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="knowledge worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                expected_workspace_output_paths=[
                    out_dir / f"{shard.shard_id}.json" for shard in runnable_shards
                ],
                workspace_output_observer=(
                    None
                    if progress_state is None
                    else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                        progress_state.observe_workspace_outputs(
                            worker_id=_worker_id,
                            present_count=present_count,
                            expected_count=expected_count,
                        )
                    )
                ),
            ),
        )
        _finalize_live_status(
            worker_live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
        _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")

        task_count = len(runnable_shards)
        for task_index, shard in enumerate(runnable_shards):
            shard_root = shard_dir / shard.shard_id
            input_path = in_dir / f"{shard.shard_id}.json"
            output_path = out_dir / f"{shard.shard_id}.json"
            response_text = (
                output_path.read_text(encoding="utf-8")
                if output_path.exists()
                else None
            )
            runner_payload = _build_knowledge_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
                runtime_task_id=shard.shard_id,
                run_result=run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=task_index,
            )
            worker_runner_results.append(dict(runner_payload))
            telemetry = runner_payload.get("telemetry")
            row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
            if isinstance(row_payloads, list):
                for row_payload in row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            primary_row = stage_rows[-1] if stage_rows else None
            primary_runner_row = (
                row_payloads[0]
                if isinstance(row_payloads, list)
                and row_payloads
                and isinstance(row_payloads[0], dict)
                else None
            )
            if interruption_requested is not None and interruption_requested.is_set():
                break
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_knowledge_response(
                    shard=shard,
                    response_text=response_text,
                )
            )
            active_response_text = str(response_text or "")
            active_run_result = run_result
            final_success_run_result = run_result
            initial_proposal_status = proposal_status
            main_failure_signature = _knowledge_failure_signature(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
            )
            if proposal_status != "validated":
                poisoned_worker_reason = recovery_governor.observe_main_failure(
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if poisoned_worker_reason is not None:
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "poisoned_worker_reason_code": poisoned_worker_reason["reason_code"],
                        "poisoned_worker_reason_detail": poisoned_worker_reason["reason_detail"],
                    }
            watchdog_retry_attempted = False
            watchdog_retry_status = "not_attempted"
            watchdog_retry_skip_reason_code: str | None = None
            watchdog_retry_skip_reason_detail: str | None = None
            watchdog_retry_examples: list[dict[str, Any]] = []
            retry_followup_decision = _KnowledgeFollowupDecision(allowed=False)
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_attempt_knowledge_watchdog_retry(run_result=run_result)
            ):
                retry_followup_decision = recovery_governor.allow_followup(
                    kind="retry",
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if not retry_followup_decision.allowed:
                    watchdog_retry_status = "skipped"
                    watchdog_retry_skip_reason_code = retry_followup_decision.reason_code
                    watchdog_retry_skip_reason_detail = retry_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    }
                elif bool(_classify_knowledge_watchdog_retry_size(shard=shard).get("oversized")):
                    watchdog_retry_size = _classify_knowledge_watchdog_retry_size(shard=shard)
                    watchdog_retry_status = "oversized_skipped"
                    watchdog_retry_skip_reason_code = str(
                        watchdog_retry_size.get("reason_code") or "watchdog_retry_oversized_skipped"
                    )
                    watchdog_retry_skip_reason_detail = str(
                        watchdog_retry_size.get("reason_detail") or ""
                    )
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "watchdog_retry_chunk_count": int(watchdog_retry_size.get("chunk_count") or 0),
                        "watchdog_retry_char_count": int(watchdog_retry_size.get("char_count") or 0),
                    }
                else:
                    watchdog_retry_attempted = True
                    watchdog_retry_examples = (
                        cohort_watchdog_state.snapshot().get("successful_examples") or []
                    )
                    watchdog_retry_root = shard_root / "watchdog_retry"
                    watchdog_retry_root.mkdir(parents=True, exist_ok=True)
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="watchdog retry",
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="watchdog_retry",
                        )
                    try:
                        watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=shard,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            reason_code=str(run_result.supervision_reason_code or ""),
                            reason_detail=str(run_result.supervision_reason_detail or ""),
                            successful_examples=watchdog_retry_examples,
                            live_status_path=watchdog_retry_root / "live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    _finalize_live_status(
                        watchdog_retry_root / "live_status.json",
                        run_result=watchdog_retry_run_result,
                    )
                    watchdog_retry_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=shard.shard_id,
                        run_result=watchdog_retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_watchdog_retry",
                    )
                    worker_runner_results.append(dict(watchdog_retry_payload))
                    watchdog_retry_runner_rows = (
                        watchdog_retry_payload.get("telemetry", {}).get("rows")
                        if isinstance(watchdog_retry_payload.get("telemetry"), dict)
                        else None
                    )
                    watchdog_retry_row = None
                    if isinstance(watchdog_retry_runner_rows, list):
                        for row_payload in watchdog_retry_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_watchdog_retry_attempt"] = True
                            row_payload["watchdog_retry_attempt_index"] = 1
                            watchdog_retry_row = dict(row_payload)
                            stage_rows.append(watchdog_retry_row)
                    (watchdog_retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(watchdog_retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": watchdog_retry_run_result.response_text},
                        watchdog_retry_root / "last_message.json",
                    )
                    _write_json(
                        dict(watchdog_retry_run_result.usage or {}),
                        watchdog_retry_root / "usage.json",
                    )
                    _write_json(
                        watchdog_retry_run_result.workspace_manifest(),
                        watchdog_retry_root / "workspace_manifest.json",
                    )
                    (
                        payload,
                        validation_errors,
                        validation_metadata,
                        proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=shard,
                        response_text=watchdog_retry_run_result.response_text,
                    )
                    if watchdog_retry_row is not None:
                        watchdog_retry_row["proposal_status"] = proposal_status
                    if isinstance(watchdog_retry_runner_rows, list) and watchdog_retry_runner_rows:
                        first_watchdog_retry_runner_row = watchdog_retry_runner_rows[0]
                        if isinstance(first_watchdog_retry_runner_row, dict):
                            first_watchdog_retry_runner_row["proposal_status"] = proposal_status
                    _write_json(
                        {
                            "status": proposal_status,
                            "validation_errors": list(validation_errors),
                            "validation_metadata": dict(validation_metadata or {}),
                            "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                            "watchdog_retry_reason_code": run_result.supervision_reason_code,
                            "watchdog_retry_reason_detail": run_result.supervision_reason_detail,
                            "state": watchdog_retry_run_result.supervision_state or "completed",
                            "reason_code": watchdog_retry_run_result.supervision_reason_code,
                            "reason_detail": watchdog_retry_run_result.supervision_reason_detail,
                            "retryable": watchdog_retry_run_result.supervision_retryable,
                        },
                        watchdog_retry_root / "status.json",
                    )
                    watchdog_retry_status = (
                        "recovered" if proposal_status == "validated" else "failed"
                    )
                    recovery_governor.record_followup_outcome(
                        kind="retry",
                        failure_signature=main_failure_signature,
                        recovered=proposal_status == "validated",
                    )
                    active_run_result = watchdog_retry_run_result
                    active_response_text = str(watchdog_retry_run_result.response_text or "")
                    final_success_run_result = watchdog_retry_run_result
            retry_attempted = False
            retry_status = "not_attempted"
            retry_child_shard_ids: list[str] = []
            retry_failure_rows: list[dict[str, Any]] = []
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_retry_knowledge_shard_split(
                    shard=shard,
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    response_text=active_response_text,
                )
            ):
                retry_attempted = True
                retry_shards = _split_failed_knowledge_shard_for_retry(
                    shard,
                    max_retry_chunk_count=_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD,
                    max_retry_chars=_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD,
                )
                retry_child_shard_ids = [retry_shard.shard_id for retry_shard in retry_shards]
                retry_results_by_shard_id: dict[str, dict[str, Any]] = {}
                retry_all_validated = bool(retry_shards)
                for retry_index, retry_shard in enumerate(retry_shards, start=1):
                    retry_root = shard_root / "retry_shards" / retry_shard.shard_id
                    retry_root.mkdir(parents=True, exist_ok=True)
                    retry_input_path = retry_root / "input.json"
                    _write_worker_input(
                        path=retry_input_path,
                        payload=retry_shard.input_payload,
                        input_text=retry_shard.input_text,
                    )
                    retry_prompt_text = build_knowledge_direct_prompt(
                        _coerce_dict(retry_shard.input_payload)
                    )
                    (retry_root / "prompt.txt").write_text(retry_prompt_text, encoding="utf-8")
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="retry",
                                task_id=retry_shard.shard_id,
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="retry_split",
                        )
                    try:
                        retry_run_result = runner.run_structured_prompt(
                            prompt_text=retry_prompt_text,
                            input_payload=_coerce_dict(retry_shard.input_payload),
                            working_dir=worker_root,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            workspace_task_label="knowledge review retry shard",
                            supervision_callback=_build_strict_json_watchdog_callback(
                                live_status_path=retry_root / "live_status.json",
                            ),
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    _finalize_live_status(
                        retry_root / "live_status.json",
                        run_result=retry_run_result,
                    )
                    retry_payload_wrapper = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=retry_shard.shard_id,
                        run_result=retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_retry",
                    )
                    worker_runner_results.append(dict(retry_payload_wrapper))
                    retry_runner_rows = (
                        retry_payload_wrapper.get("telemetry", {}).get("rows")
                        if isinstance(retry_payload_wrapper.get("telemetry"), dict)
                        else None
                    )
                    retry_row = None
                    if isinstance(retry_runner_rows, list):
                        for row_payload in retry_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_retry_attempt"] = True
                            row_payload["retry_attempt_index"] = retry_index
                            row_payload["retry_parent_shard_id"] = shard.shard_id
                            retry_row = dict(row_payload)
                            stage_rows.append(retry_row)
                    (retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": retry_run_result.response_text},
                        retry_root / "last_message.json",
                    )
                    _write_json(dict(retry_run_result.usage or {}), retry_root / "usage.json")
                    _write_json(
                        retry_run_result.workspace_manifest(),
                        retry_root / "workspace_manifest.json",
                    )
                    (
                        retry_payload_candidate,
                        retry_errors,
                        retry_metadata,
                        retry_proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=retry_shard,
                        response_text=retry_run_result.response_text,
                    )
                    if retry_row is not None:
                        retry_row["proposal_status"] = retry_proposal_status
                    if isinstance(retry_runner_rows, list) and retry_runner_rows:
                        first_retry_runner_row = retry_runner_rows[0]
                        if isinstance(first_retry_runner_row, dict):
                            first_retry_runner_row["proposal_status"] = retry_proposal_status
                    _write_json(
                        {
                            "status": retry_proposal_status,
                            "validation_errors": list(retry_errors),
                            "validation_metadata": dict(retry_metadata or {}),
                            "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                            "retry_parent_shard_id": shard.shard_id,
                            "state": retry_run_result.supervision_state or "completed",
                            "reason_code": retry_run_result.supervision_reason_code,
                            "reason_detail": retry_run_result.supervision_reason_detail,
                            "retryable": retry_run_result.supervision_retryable,
                        },
                        retry_root / "status.json",
                    )
                    if retry_proposal_status != "validated" or retry_payload_candidate is None:
                        retry_all_validated = False
                        retry_failure_rows.append(
                            {
                                "shard_id": retry_shard.shard_id,
                                "proposal_status": retry_proposal_status,
                                "validation_errors": list(retry_errors),
                                "validation_metadata": dict(retry_metadata or {}),
                            }
                        )
                        continue
                    retry_results_by_shard_id[retry_shard.shard_id] = retry_payload_candidate
                if retry_all_validated:
                    combined_retry_rows: list[dict[str, Any]] = []
                    for retry_shard in retry_shards:
                        retry_payload_candidate = (
                            retry_results_by_shard_id.get(retry_shard.shard_id) or {}
                        )
                        chunk_rows = retry_payload_candidate.get("r")
                        if isinstance(chunk_rows, list):
                            combined_retry_rows.extend(
                                dict(row) for row in chunk_rows if isinstance(row, Mapping)
                            )
                    combined_retry_payload = {
                        "v": "2",
                        "bid": shard.shard_id,
                        "r": combined_retry_rows,
                    }
                    (
                        payload,
                        validation_errors,
                        validation_metadata,
                        proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=shard,
                        response_text=json.dumps(combined_retry_payload, sort_keys=True),
                    )
                    if proposal_status == "validated":
                        retry_status = "recovered"
                    else:
                        retry_status = "failed"
                        retry_failure_rows.append(
                            {
                                "shard_id": shard.shard_id,
                                "proposal_status": proposal_status,
                                "validation_errors": list(validation_errors),
                                "validation_metadata": dict(validation_metadata or {}),
                            }
                        )
                else:
                    retry_status = "failed"
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "retry_failures": retry_failure_rows,
                    }

            repair_attempted = False
            repair_status = "not_attempted"
            repair_skip_reason_code: str | None = None
            repair_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and proposal_status == "invalid"
            ):
                current_failure_signature = _knowledge_failure_signature(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=active_run_result,
                )
                repair_followup_decision = recovery_governor.allow_followup(
                    kind="repair",
                    worker_id=assignment.worker_id,
                    failure_signature=current_failure_signature,
                    near_miss=_is_knowledge_near_miss(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                    ),
                )
                if not repair_followup_decision.allowed:
                    repair_status = "skipped"
                    repair_skip_reason_code = repair_followup_decision.reason_code
                    repair_skip_reason_detail = repair_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    }
                else:
                    repair_attempted = True
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="repair",
                            ),
                            followup_kind="repair",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="repair",
                        )
                    try:
                        repair_run_result = _run_knowledge_repair_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=shard,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            original_response_text=active_response_text,
                            validation_errors=validation_errors,
                            validation_metadata=validation_metadata,
                            live_status_path=shard_root / "repair_live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="repair",
                            )
                    _finalize_live_status(
                        shard_root / "repair_live_status.json",
                        run_result=repair_run_result,
                    )
                    repair_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=shard.shard_id,
                        run_result=repair_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_repair",
                    )
                    worker_runner_results.append(dict(repair_payload))
                    repair_runner_rows = (
                        repair_payload.get("telemetry", {}).get("rows")
                        if isinstance(repair_payload.get("telemetry"), dict)
                        else None
                    )
                    repair_row = None
                    if isinstance(repair_runner_rows, list):
                        for row_payload in repair_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_repair_attempt"] = True
                            row_payload["repair_attempt_index"] = 1
                            repair_row = dict(row_payload)
                            stage_rows.append(repair_row)
                    (shard_root / "repair_events.jsonl").write_text(
                        _render_events_jsonl(repair_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": repair_run_result.response_text},
                        shard_root / "repair_last_message.json",
                    )
                    _write_json(
                        dict(repair_run_result.usage or {}),
                        shard_root / "repair_usage.json",
                    )
                    _write_json(
                        repair_run_result.workspace_manifest(),
                        shard_root / "repair_workspace_manifest.json",
                    )
                    repair_payload_candidate, repair_errors, repair_metadata, repair_proposal_status = (
                        _evaluate_knowledge_response(
                            shard=shard,
                            response_text=repair_run_result.response_text,
                        )
                    )
                    repair_status = (
                        "repaired" if repair_proposal_status == "validated" else "failed"
                    )
                    recovery_governor.record_followup_outcome(
                        kind="repair",
                        failure_signature=current_failure_signature,
                        recovered=repair_proposal_status == "validated",
                    )
                    if repair_row is not None:
                        repair_row["proposal_status"] = repair_proposal_status
                        repair_row["repair_attempted"] = True
                        repair_row["repair_status"] = repair_status
                    if isinstance(repair_runner_rows, list) and repair_runner_rows:
                        repair_runner_row = repair_runner_rows[0]
                        if isinstance(repair_runner_row, dict):
                            repair_runner_row["proposal_status"] = repair_proposal_status
                            repair_runner_row["repair_attempted"] = True
                            repair_runner_row["repair_status"] = repair_status
                    _write_json(
                        {
                            "attempted": True,
                            "status": repair_status,
                            "original_validation_errors": list(validation_errors),
                            "repair_validation_errors": list(repair_errors),
                            "state": repair_run_result.supervision_state or "completed",
                            "reason_code": repair_run_result.supervision_reason_code,
                            "reason_detail": repair_run_result.supervision_reason_detail,
                            "retryable": repair_run_result.supervision_retryable,
                        },
                        shard_root / "repair_status.json",
                    )
                    if repair_proposal_status == "validated":
                        payload = repair_payload_candidate
                        validation_errors = repair_errors
                        validation_metadata = dict(repair_metadata or {})
                        proposal_status = "validated"
                        final_success_run_result = repair_run_result
                    else:
                        validation_metadata = {
                            **dict(validation_metadata or {}),
                            "repair_validation_errors": list(repair_errors),
                        }
            if primary_row is not None:
                primary_row["proposal_status"] = (
                    initial_proposal_status
                    if watchdog_retry_attempted or retry_attempted or repair_attempted
                    else proposal_status
                )
                primary_row["final_proposal_status"] = proposal_status
                primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_row["watchdog_retry_status"] = watchdog_retry_status
                primary_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_row["retry_attempted"] = retry_attempted
                primary_row["retry_status"] = retry_status
                primary_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
                primary_row["repair_attempted"] = repair_attempted
                primary_row["repair_status"] = repair_status
                primary_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            if primary_runner_row is not None:
                primary_runner_row["proposal_status"] = (
                    initial_proposal_status
                    if watchdog_retry_attempted or retry_attempted or repair_attempted
                    else proposal_status
                )
                primary_runner_row["final_proposal_status"] = proposal_status
                primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
                primary_runner_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_runner_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_runner_row["retry_attempted"] = retry_attempted
                primary_runner_row["retry_status"] = retry_status
                primary_runner_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
                primary_runner_row["repair_attempted"] = repair_attempted
                primary_runner_row["repair_status"] = repair_status
                primary_runner_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_runner_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            _write_json(
                {
                    "shard_id": shard.shard_id,
                    "worker_id": assignment.worker_id,
                    "payload": payload,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": retry_attempted,
                    "retry_status": retry_status,
                    "retry_child_shard_ids": list(retry_child_shard_ids),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                },
                proposal_path,
            )
            _write_json(
                payload
                if payload is not None
                else {
                    "error": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                },
                shard_root / "proposal.json",
            )
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": retry_attempted,
                    "retry_status": retry_status,
                    "retry_child_shard_ids": list(retry_child_shard_ids),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                },
                shard_root / "status.json",
            )
            if task_status_tracker is not None:
                task_status_tracker.mark_terminal(
                    task_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    terminal_state=_terminal_knowledge_task_state(
                        proposal_status=proposal_status,
                        supervision_state=run_result.supervision_state,
                        watchdog_retry_status=watchdog_retry_status,
                        retry_status=retry_status,
                        repair_status=repair_status,
                    ),
                    attempt_type=_terminal_knowledge_attempt_type(
                        watchdog_retry_status=watchdog_retry_status,
                        retry_status=retry_status,
                        repair_status=repair_status,
                    ),
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    metadata={
                        "watchdog_retry_status": watchdog_retry_status,
                        "retry_status": retry_status,
                        "repair_status": repair_status,
                    },
                    terminal_reason_code=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=active_run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[0],
                    terminal_reason_detail=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=active_run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[1],
                )
            _finalize_terminal_followups_for_task_root(
                shard_root,
                terminal_reason_code="superseded_by_terminal_packet",
                terminal_reason_detail="packet reached a terminal state before older follow-up work could finish",
            )
            if proposal_status != "validated":
                worker_failure_count += 1
                worker_failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        ),
                        "validation_errors": list(validation_errors),
                        "state": run_result.supervision_state or "completed",
                        "reason_code": run_result.supervision_reason_code,
                    }
                )
            else:
                worker_proposal_count += 1
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status=proposal_status,
                    proposal_path=_relative_path(run_root, proposal_path),
                    payload=payload,
                    validation_errors=validation_errors,
                    metadata={
                        **dict(validation_metadata or {}),
                        "watchdog_retry_attempted": watchdog_retry_attempted,
                        "watchdog_retry_status": watchdog_retry_status,
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "retry_attempted": retry_attempted,
                        "retry_status": retry_status,
                        "retry_child_shard_ids": list(retry_child_shard_ids),
                        "repair_attempted": repair_attempted,
                        "repair_status": repair_status,
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    },
                )
            )
            if progress_state is not None:
                progress_state.mark_task_packet_terminal(
                    worker_id=assignment.worker_id,
                    task_id=shard.shard_id,
                )
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
            if proposal_status == "validated":
                cohort_watchdog_state.record_validated_result(
                    duration_ms=final_success_run_result.duration_ms,
                    example_payload=_build_knowledge_watchdog_example(
                        shard=shard,
                        payload=payload,
                    ),
                )

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "scratch_dir": _relative_path(
                    run_root,
                    worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME,
                ),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


def _run_knowledge_workspace_worker_assignment_taskized_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    task_plans_by_shard_id: Mapping[str, tuple[_KnowledgeTaskPlan, ...]],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    runnable_shards: list[ShardManifestEntryV1] = []
    runnable_tasks: list[_KnowledgeTaskPlan] = []

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            task_plans = task_plans_by_shard_id.get(shard.shard_id, ())
            if task_plans:
                runnable_shards.append(shard)
                runnable_tasks.extend(task_plans)
            continue
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text="knowledge worker preflight rejected",
            output_schema_path=output_schema_path,
            working_dir=worker_root,
            reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
            reason_detail=str(preflight_failure.get("reason_detail") or "knowledge shard failed preflight"),
        )
        _write_live_status(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
            proposal_path,
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "watchdog_retry_attempted": False,
                    "watchdog_retry_status": "not_attempted",
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                },
            )
        )
        if task_status_tracker is not None:
            for task_id in _progress_task_ids_for_knowledge_shard(
                shard_id=shard.shard_id,
                task_plans_by_shard_id=task_plans_by_shard_id,
            ):
                task_status_tracker.mark_terminal(
                    task_id=task_id,
                    worker_id=assignment.worker_id,
                    terminal_state="preflight_rejected",
                    attempt_type="preflight",
                    proposal_status="missing_output",
                    validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                    metadata={
                        "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                    },
                )
        if progress_state is not None:
            progress_state.mark_task_packets_terminal(
                worker_id=assignment.worker_id,
                task_ids=_progress_task_ids_for_knowledge_shard(
                    shard_id=shard.shard_id,
                    task_plans_by_shard_id=task_plans_by_shard_id,
                ),
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    workspace_task_entries = _build_knowledge_workspace_task_runtime_entries(runnable_tasks)
    _write_json(
        [asdict(task_entry) for task_entry in workspace_task_entries],
        worker_root / "assigned_tasks.json",
    )
    (worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME).mkdir(parents=True, exist_ok=True)
    for task in runnable_tasks:
        task_manifest = task.manifest_entry
        _write_worker_input(
            in_dir / f"{task_manifest.shard_id}.json",
            payload=task_manifest.input_payload,
            input_text=task_manifest.input_text,
        )
        _write_knowledge_worker_hint(
            path=hints_dir / f"{task_manifest.shard_id}.md",
            shard=task_manifest,
        )

    if runnable_shards and runnable_tasks:
        worker_prompt_text = _build_knowledge_workspace_worker_prompt(
            tasks=workspace_task_entries
        )
        worker_prompt_path = worker_root / "prompt.txt"
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        for shard in runnable_shards:
            (shard_dir / shard.shard_id / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
        if task_status_tracker is not None:
            for task_entry in workspace_task_entries:
                task_metadata = dict(task_entry.metadata or {})
                task_status_tracker.start_attempt(
                    task_id=task_entry.task_id,
                    worker_id=assignment.worker_id,
                    attempt_type="main_worker",
                    metadata={
                        "lease_sequence": int(task_metadata.get("lease_sequence") or 0),
                        "lease_total": int(task_metadata.get("lease_total") or len(workspace_task_entries)),
                        "input_path": task_metadata.get("input_path"),
                        "hint_path": task_metadata.get("hint_path"),
                        "result_path": task_metadata.get("result_path"),
                        "workspace_processing_contract": task_metadata.get(
                            "workspace_processing_contract"
                        ),
                    },
                )
        run_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="knowledge worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                expected_workspace_output_paths=[
                    out_dir / f"{task.task_id}.json" for task in runnable_tasks
                ],
                workspace_output_observer=(
                    None
                    if progress_state is None
                    else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                        progress_state.observe_workspace_outputs(
                            worker_id=_worker_id,
                            present_count=present_count,
                            expected_count=expected_count,
                        )
                    )
                ),
            ),
        )
        _finalize_live_status(
            worker_live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
        _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
        if task_status_tracker is not None:
            for task_entry in workspace_task_entries:
                task_metadata = dict(task_entry.metadata or {})
                result_path = str(task_metadata.get("result_path") or "").strip()
                if not result_path:
                    continue
                output_path = worker_root / result_path
                if output_path.exists():
                    task_status_tracker.mark_main_output_written(
                        task_id=task_entry.task_id,
                        metadata={
                            "leased_packet_result_path": result_path,
                        },
                    )

        task_count = len(runnable_tasks)
        task_payloads_by_shard_id: dict[str, dict[str, dict[str, Any]]] = {}
        task_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        task_watchdog_retry_status_by_shard_id: dict[str, dict[str, str]] = {}
        task_watchdog_retry_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_status_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        for task_index, task in enumerate(runnable_tasks):
            task_manifest = task.manifest_entry
            parent_shard_id = task.parent_shard_id
            task_root = shard_dir / task_manifest.shard_id
            task_root.mkdir(parents=True, exist_ok=True)
            input_path = in_dir / f"{task_manifest.shard_id}.json"
            output_path = out_dir / f"{task_manifest.shard_id}.json"
            response_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
            runner_payload = _build_knowledge_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                runtime_task_id=task_manifest.shard_id,
                run_result=run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=task_index,
            )
            worker_runner_results.append(dict(runner_payload))
            telemetry = runner_payload.get("telemetry")
            row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
            if isinstance(row_payloads, list):
                for row_payload in row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            primary_row = stage_rows[-1] if stage_rows else None
            primary_runner_row = (
                row_payloads[0]
                if isinstance(row_payloads, list)
                and row_payloads
                and isinstance(row_payloads[0], dict)
                else None
            )
            if interruption_requested is not None and interruption_requested.is_set():
                break
            payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                shard=task_manifest,
                response_text=response_text,
            )
            initial_proposal_status = proposal_status
            active_response_text = response_text
            main_failure_signature = _knowledge_failure_signature(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
            )
            if proposal_status != "validated":
                poisoned_worker_reason = recovery_governor.observe_main_failure(
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if poisoned_worker_reason is not None:
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "poisoned_worker_reason_code": poisoned_worker_reason["reason_code"],
                        "poisoned_worker_reason_detail": poisoned_worker_reason["reason_detail"],
                    }
            watchdog_retry_attempted = False
            watchdog_retry_status = "not_attempted"
            watchdog_retry_skip_reason_code: str | None = None
            watchdog_retry_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_attempt_knowledge_watchdog_retry(run_result=run_result)
            ):
                retry_followup_decision = recovery_governor.allow_followup(
                    kind="retry",
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if not retry_followup_decision.allowed:
                    watchdog_retry_status = "skipped"
                    watchdog_retry_skip_reason_code = retry_followup_decision.reason_code
                    watchdog_retry_skip_reason_detail = retry_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    }
                else:
                    watchdog_retry_attempted = True
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=parent_shard_id,
                                attempt_label="watchdog retry",
                                task_id=task_manifest.shard_id,
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=task_manifest.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="watchdog_retry",
                        )
                    try:
                        watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=task_manifest,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            reason_code=str(run_result.supervision_reason_code or ""),
                            reason_detail=str(run_result.supervision_reason_detail or ""),
                            successful_examples=cohort_watchdog_state.snapshot().get("successful_examples") or [],
                            live_status_path=task_root / "watchdog_retry" / "live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    retry_root = task_root / "watchdog_retry"
                    _finalize_live_status(
                        retry_root / "live_status.json",
                        run_result=watchdog_retry_run_result,
                    )
                    retry_payload_wrapper = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=parent_shard_id,
                        run_result=watchdog_retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_watchdog_retry",
                    )
                    retry_payload_wrapper["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                    retry_payload_wrapper["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                    worker_runner_results.append(dict(retry_payload_wrapper))
                    retry_rows = (
                        retry_payload_wrapper.get("telemetry", {}).get("rows")
                        if isinstance(retry_payload_wrapper.get("telemetry"), dict)
                        else None
                    )
                    if isinstance(retry_rows, list):
                        for row_payload in retry_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["watchdog_retry_attempted"] = True
                            row_payload["runtime_task_id"] = task_manifest.shard_id
                            row_payload["runtime_parent_shard_id"] = parent_shard_id
                            stage_rows.append(dict(row_payload))
                    (retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(watchdog_retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json({"text": watchdog_retry_run_result.response_text}, retry_root / "last_message.json")
                    _write_json(dict(watchdog_retry_run_result.usage or {}), retry_root / "usage.json")
                    _write_json(watchdog_retry_run_result.workspace_manifest(), retry_root / "workspace_manifest.json")
                    payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                        shard=task_manifest,
                        response_text=watchdog_retry_run_result.response_text,
                    )
                    watchdog_retry_status = "recovered" if proposal_status == "validated" else "failed"
                    recovery_governor.record_followup_outcome(
                        kind="retry",
                        failure_signature=main_failure_signature,
                        recovered=proposal_status == "validated",
                    )
                    _write_json(
                        {
                            "status": proposal_status,
                            "watchdog_retry_reason_code": run_result.supervision_reason_code,
                            "validation_errors": list(validation_errors),
                            "validation_metadata": dict(validation_metadata or {}),
                        },
                        retry_root / "status.json",
                    )
                    active_response_text = watchdog_retry_run_result.response_text
                    task_watchdog_retry_status_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = watchdog_retry_status
                if watchdog_retry_skip_reason_code:
                    task_watchdog_retry_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = watchdog_retry_skip_reason_code

            repair_attempted = False
            repair_status = "not_attempted"
            repair_skip_reason_code: str | None = None
            repair_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and proposal_status == "invalid"
            ):
                current_failure_signature = _knowledge_failure_signature(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=run_result,
                )
                repair_followup_decision = recovery_governor.allow_followup(
                    kind="repair",
                    worker_id=assignment.worker_id,
                    failure_signature=current_failure_signature,
                    near_miss=_is_knowledge_near_miss(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                    ),
                )
                if not repair_followup_decision.allowed:
                    repair_status = "skipped"
                    repair_skip_reason_code = repair_followup_decision.reason_code
                    repair_skip_reason_detail = repair_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    }
                else:
                    repair_attempted = True
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=parent_shard_id,
                                attempt_label="repair",
                                task_id=task_manifest.shard_id,
                            ),
                            followup_kind="repair",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=task_manifest.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="repair",
                        )
                    try:
                        repair_run_result = _run_knowledge_repair_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=task_manifest,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            original_response_text=active_response_text,
                            validation_errors=validation_errors,
                            validation_metadata=validation_metadata,
                            live_status_path=task_root / "repair_live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="repair",
                            )
                    _finalize_live_status(
                        task_root / "repair_live_status.json",
                        run_result=repair_run_result,
                    )
                    repair_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=parent_shard_id,
                        run_result=repair_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_repair",
                    )
                    repair_payload["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                    repair_payload["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                    worker_runner_results.append(dict(repair_payload))
                    repair_runner_rows = (
                        repair_payload.get("telemetry", {}).get("rows")
                        if isinstance(repair_payload.get("telemetry"), dict)
                        else None
                    )
                    if isinstance(repair_runner_rows, list):
                        for row_payload in repair_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["repair_attempted"] = True
                            row_payload["runtime_task_id"] = task_manifest.shard_id
                            row_payload["runtime_parent_shard_id"] = parent_shard_id
                            stage_rows.append(dict(row_payload))
                    (task_root / "repair_events.jsonl").write_text(
                        _render_events_jsonl(repair_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json({"text": repair_run_result.response_text}, task_root / "repair_last_message.json")
                    _write_json(dict(repair_run_result.usage or {}), task_root / "repair_usage.json")
                    _write_json(repair_run_result.workspace_manifest(), task_root / "repair_workspace_manifest.json")
                    payload, repair_errors, repair_metadata, repair_proposal_status = _evaluate_knowledge_response(
                        shard=task_manifest,
                        response_text=repair_run_result.response_text,
                    )
                    repair_status = "repaired" if repair_proposal_status == "validated" else "failed"
                    recovery_governor.record_followup_outcome(
                        kind="repair",
                        failure_signature=current_failure_signature,
                        recovered=repair_proposal_status == "validated",
                    )
                    validation_errors = repair_errors
                    validation_metadata = dict(repair_metadata or {})
                    proposal_status = repair_proposal_status
                    _write_json(
                        {
                            "attempted": True,
                            "status": repair_status,
                            "repair_validation_errors": list(repair_errors),
                            "state": repair_run_result.supervision_state or "completed",
                            "reason_code": repair_run_result.supervision_reason_code,
                            "reason_detail": repair_run_result.supervision_reason_detail,
                            "retryable": repair_run_result.supervision_retryable,
                        },
                        task_root / "repair_status.json",
                    )
                    task_repair_status_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = repair_status
                    task_repair_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = tuple(repair_errors if repair_status == "failed" else ())
                if repair_skip_reason_code:
                    task_repair_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = repair_skip_reason_code

            if primary_row is not None:
                primary_row["proposal_status"] = (
                    initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
                )
                primary_row["final_proposal_status"] = proposal_status
                primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_row["watchdog_retry_status"] = watchdog_retry_status
                primary_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_row["repair_attempted"] = repair_attempted
                primary_row["repair_status"] = repair_status
                primary_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            if primary_runner_row is not None:
                primary_runner_row["proposal_status"] = (
                    initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
                )
                primary_runner_row["final_proposal_status"] = proposal_status
                primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
                primary_runner_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_runner_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_runner_row["repair_attempted"] = repair_attempted
                primary_runner_row["repair_status"] = repair_status
                primary_runner_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_runner_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            task_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = tuple(validation_errors)
            if task_status_tracker is not None:
                task_status_tracker.mark_terminal(
                    task_id=task_manifest.shard_id,
                    worker_id=assignment.worker_id,
                    terminal_state=_terminal_knowledge_task_state(
                        proposal_status=proposal_status,
                        supervision_state=run_result.supervision_state,
                        watchdog_retry_status=watchdog_retry_status,
                        repair_status=repair_status,
                    ),
                    attempt_type=_terminal_knowledge_attempt_type(
                        watchdog_retry_status=watchdog_retry_status,
                        repair_status=repair_status,
                    ),
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    metadata={
                        "watchdog_retry_status": watchdog_retry_status,
                        "repair_status": repair_status,
                    },
                    terminal_reason_code=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[0],
                    terminal_reason_detail=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[1],
                )
            _finalize_terminal_followups_for_task_root(
                task_root,
                terminal_reason_code="superseded_by_terminal_packet",
                terminal_reason_detail="packet reached a terminal state before older follow-up work could finish",
            )
            if progress_state is not None:
                progress_state.mark_task_packet_terminal(
                    worker_id=assignment.worker_id,
                    task_id=task_manifest.shard_id,
                )
            if payload is not None and proposal_status == "validated":
                task_payloads_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = payload

        for shard in runnable_shards:
            if interruption_requested is not None and interruption_requested.is_set():
                break
            shard_root = shard_dir / shard.shard_id
            task_payloads = task_payloads_by_shard_id.get(shard.shard_id, {})
            task_errors = task_validation_errors_by_shard_id.get(shard.shard_id, {})
            task_watchdog_statuses = task_watchdog_retry_status_by_shard_id.get(shard.shard_id, {})
            task_watchdog_skip_reasons = task_watchdog_retry_skip_reason_by_shard_id.get(shard.shard_id, {})
            task_repair_statuses = task_repair_status_by_shard_id.get(shard.shard_id, {})
            task_repair_skip_reasons = task_repair_skip_reason_by_shard_id.get(shard.shard_id, {})
            task_repair_errors = task_repair_validation_errors_by_shard_id.get(shard.shard_id, {})
            payload, aggregation_metadata = _aggregate_knowledge_task_payloads(
                shard=shard,
                task_payloads_by_task_id=task_payloads,
                task_validation_errors_by_task_id=task_errors,
            )
            payload_candidate, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                shard=shard,
                response_text=json.dumps(payload, sort_keys=True),
            )
            watchdog_retry_attempted = bool(task_watchdog_statuses)
            watchdog_retry_status = (
                "recovered"
                if any(status == "recovered" for status in task_watchdog_statuses.values())
                else ("failed" if watchdog_retry_attempted else "not_attempted")
            )
            watchdog_retry_skip_reason_code = (
                sorted({reason for reason in task_watchdog_skip_reasons.values() if reason})[0]
                if task_watchdog_skip_reasons
                else None
            )
            watchdog_retry_skip_reason_detail = (
                f"task-level skip reasons: {dict(sorted(task_watchdog_skip_reasons.items()))}"
                if task_watchdog_skip_reasons
                else None
            )
            repair_attempted = any(
                str(status).strip() != "not_attempted"
                for status in task_repair_statuses.values()
            )
            repair_status = (
                "repaired"
                if any(str(status).strip() == "repaired" for status in task_repair_statuses.values())
                else ("failed" if repair_attempted else "not_attempted")
            )
            repair_skip_reason_code = (
                sorted({reason for reason in task_repair_skip_reasons.values() if reason})[0]
                if task_repair_skip_reasons
                else None
            )
            repair_skip_reason_detail = (
                f"task-level skip reasons: {dict(sorted(task_repair_skip_reasons.items()))}"
                if task_repair_skip_reasons
                else None
            )
            validation_metadata = {
                "task_aggregation": aggregation_metadata,
                **dict(validation_metadata or {}),
            }
            if task_watchdog_statuses:
                validation_metadata["task_watchdog_retry_status_by_task_id"] = {
                    task_id: status
                    for task_id, status in sorted(task_watchdog_statuses.items())
                }
            if task_watchdog_skip_reasons:
                validation_metadata["task_watchdog_retry_skip_reason_by_task_id"] = {
                    task_id: reason_code
                    for task_id, reason_code in sorted(task_watchdog_skip_reasons.items())
                }
            if task_repair_statuses:
                validation_metadata["task_repair_status_by_task_id"] = {
                    task_id: status
                    for task_id, status in sorted(task_repair_statuses.items())
                }
            if task_repair_skip_reasons:
                validation_metadata["task_repair_skip_reason_by_task_id"] = {
                    task_id: reason_code
                    for task_id, reason_code in sorted(task_repair_skip_reasons.items())
                }
            repair_validation_errors = sorted(
                {
                    str(error).strip()
                    for errors in task_repair_errors.values()
                    for error in errors
                    if str(error).strip()
                }
            )
            if repair_validation_errors:
                validation_metadata["repair_validation_errors"] = repair_validation_errors
            final_payload = payload_candidate if proposal_status == "validated" else None
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            _write_json(
                {
                    "shard_id": shard.shard_id,
                    "worker_id": assignment.worker_id,
                    "payload": final_payload,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "retry_child_shard_ids": [],
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                },
                proposal_path,
            )
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "retry_child_shard_ids": [],
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                },
                shard_root / "status.json",
            )
            if proposal_status != "validated":
                worker_failure_count += 1
                worker_failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        ),
                        "validation_errors": list(validation_errors),
                        "state": run_result.supervision_state or "completed",
                        "reason_code": run_result.supervision_reason_code,
                    }
                )
            else:
                worker_proposal_count += 1
                cohort_watchdog_state.record_validated_result(
                    duration_ms=run_result.duration_ms,
                    example_payload=_build_knowledge_watchdog_example(
                        shard=shard,
                        payload=final_payload,
                    ),
                )
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status=proposal_status,
                    proposal_path=_relative_path(run_root, proposal_path),
                    payload=final_payload,
                    validation_errors=validation_errors,
                    metadata={
                        **dict(validation_metadata or {}),
                        "watchdog_retry_attempted": watchdog_retry_attempted,
                        "watchdog_retry_status": watchdog_retry_status,
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "retry_attempted": False,
                        "retry_status": "not_attempted",
                        "retry_child_shard_ids": [],
                        "repair_attempted": repair_attempted,
                        "repair_status": repair_status,
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    },
                )
            )
            if progress_state is not None:
                progress_state.mark_task_packets_terminal(
                    worker_id=assignment.worker_id,
                    task_ids=_progress_task_ids_for_knowledge_shard(
                        shard_id=shard.shard_id,
                        task_plans_by_shard_id=task_plans_by_shard_id,
                    ),
                )
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


def _run_direct_knowledge_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    hints_dir = worker_root / "hints"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME).mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json([asdict(shard) for shard in assigned_shards], worker_root / "assigned_shards.json")
    task_plans = tuple(
        task_plan
        for shard in assigned_shards
        for task_plan in _build_knowledge_task_plans(shard)
    )
    _write_json(
        [asdict(task_entry) for task_entry in _build_knowledge_workspace_task_runtime_entries(task_plans)],
        worker_root / "assigned_tasks.json",
    )
    return _run_knowledge_workspace_worker_assignment_v1(
        run_root=run_root,
        assignment=assignment,
        artifacts=artifacts,
        assigned_shards=assigned_shards,
        worker_root=worker_root,
        in_dir=in_dir,
        hints_dir=hints_dir,
        shard_dir=shard_dir,
        logs_dir=logs_dir,
        runner=runner,
        pipeline_id=pipeline_id,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema_path=output_schema_path,
        cohort_watchdog_state=cohort_watchdog_state,
        recovery_governor=recovery_governor,
        shard_completed_callback=shard_completed_callback,
        progress_state=progress_state,
        task_status_tracker=task_status_tracker,
        interruption_requested=interruption_requested,
    )


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_knowledge_response_json_object(
    response_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned_response_text = str(response_text or "").strip()
    candidate_texts: list[tuple[str, dict[str, Any]]] = [(cleaned_response_text, {})]
    if cleaned_response_text.endswith("EOF"):
        trimmed = cleaned_response_text.removesuffix("EOF").rstrip()
        if trimmed:
            candidate_texts.append((trimmed, {"response_trailing_eof_trimmed": True}))
    salvaged_object_text, salvage_metadata = _salvage_knowledge_json_object_suffix(
        cleaned_response_text
    )
    if salvaged_object_text is not None:
        candidate_texts.append((salvaged_object_text, dict(salvage_metadata or {})))
    last_json_error: json.JSONDecodeError | None = None
    for candidate_text, candidate_metadata in candidate_texts:
        try:
            parsed_payload = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            last_json_error = exc
            continue
        if not isinstance(parsed_payload, dict):
            raise TypeError(type(parsed_payload).__name__)
        return dict(parsed_payload), dict(candidate_metadata or {})
    if last_json_error is not None:
        raise last_json_error
    raise json.JSONDecodeError("Expected JSON object", cleaned_response_text, 0)


def _evaluate_knowledge_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload, response_parse_metadata = _load_knowledge_response_json_object(
            cleaned_response_text
        )
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    except TypeError as exc:
        return (
            None,
            ("response_not_json_object",),
            {"response_type": str(exc)},
            "invalid",
        )
    try:
        payload, normalization_metadata = normalize_knowledge_worker_payload(parsed_payload)
    except Exception as exc:  # noqa: BLE001
        return None, ("schema_invalid",), {"parse_error": str(exc)}, "invalid"
    valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
        shard,
        payload,
    )
    validation_metadata = {
        **dict(validation_metadata or {}),
        **dict(response_parse_metadata or {}),
        **dict(normalization_metadata or {}),
    }
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _preflight_knowledge_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    payload = _coerce_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    chunks = payload.get("c")
    if not owned_ids:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no owned chunk ids",
        }
    if not isinstance(chunks, list) or not chunks:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no model-facing chunks",
        }
    chunk_ids: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains a non-object chunk payload",
            }
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains a chunk without `cid`",
            }
        chunk_ids.append(chunk_id)
    if sorted(chunk_ids) != sorted(owned_ids):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard owned ids do not match chunk payload ids",
        }
    return None


def _build_preflight_rejected_run_result(
    *,
    prompt_text: str,
    output_schema_path: Path | None,
    working_dir: Path,
    reason_code: str,
    reason_detail: str,
) -> CodexExecRunResult:
    timestamp = _format_utc_now()
    return CodexExecRunResult(
        command=[],
        subprocess_exit_code=0,
        output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
        prompt_text=prompt_text,
        response_text=None,
        turn_failed_message=reason_detail,
        events=(),
        usage={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        source_working_dir=str(working_dir),
        execution_working_dir=None,
        execution_agents_path=None,
        duration_ms=0,
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
        supervision_state="preflight_rejected",
        supervision_reason_code=reason_code,
        supervision_reason_detail=reason_detail,
        supervision_retryable=False,
    )


def _build_strict_json_watchdog_callback(
    *,
    live_status_path: Path | None = None,
    live_status_paths: Sequence[Path] | None = None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    allow_workspace_commands: bool = False,
    silence_timeout_seconds: float | None = None,
    expected_workspace_output_paths: Sequence[Path] | None = None,
    workspace_output_observer: Callable[[int, int], None] | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)
    workspace_output_paths = [Path(path) for path in (expected_workspace_output_paths or [])]
    last_complete_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    workspace_output_stable_passes = 0

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        nonlocal last_complete_workspace_signature
        nonlocal workspace_output_stable_passes
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_verdict = classify_workspace_worker_command(snapshot.last_command)
        last_command_boundary_violation = detect_workspace_worker_boundary_violation(
            snapshot.last_command,
        )
        final_agent_message_state = str(snapshot.final_agent_message_state or "absent")
        cohort_snapshot = (
            cohort_watchdog_state.snapshot()
            if cohort_watchdog_state is not None
            else {}
        )
        cohort_completed_successful_shards = int(
            cohort_snapshot.get("completed_successful_shards") or 0
        )
        cohort_median_duration_ms = cohort_snapshot.get("median_duration_ms")
        cohort_elapsed_ratio = None
        if int(cohort_median_duration_ms or 0) > 0:
            cohort_elapsed_ratio = round(
                (snapshot.elapsed_seconds * 1000.0) / float(cohort_median_duration_ms),
                3,
            )
        workspace_output_status = _summarize_workspace_output_paths(workspace_output_paths)
        if workspace_output_observer is not None:
            workspace_output_observer(
                int(workspace_output_status["present_count"]),
                int(workspace_output_status["expected_count"]),
            )
        if workspace_output_status["complete"]:
            current_signature = tuple(workspace_output_status["signature"])
            if current_signature == last_complete_workspace_signature:
                workspace_output_stable_passes += 1
            else:
                last_complete_workspace_signature = current_signature
                workspace_output_stable_passes = 1
        else:
            last_complete_workspace_signature = None
            workspace_output_stable_passes = 0
        if (
            allow_workspace_commands
            and workspace_output_status["complete"]
            and workspace_output_stable_passes >= _KNOWLEDGE_WORKSPACE_OUTPUT_STABLE_PASSES
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="workspace_outputs_stabilized",
                reason_detail=(
                    "knowledge workspace worker wrote every assigned output file and the "
                    "files stabilized across consecutive supervision snapshots"
                ),
                retryable=False,
                supervision_state="completed",
            )
        if snapshot.command_execution_count > 0:
            if decision is None and allow_workspace_commands:
                if last_command_boundary_violation is None:
                    command_execution_tolerated = True
                else:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="workspace worker stage",
                            last_command=snapshot.last_command,
                        ),
                        retryable=True,
                    )
                if decision is None and should_terminate_workspace_command_loop(snapshot=snapshot):
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_loop_without_output",
                        reason_detail=format_watchdog_command_loop_reason_detail(
                            stage_label="workspace worker stage",
                            snapshot=snapshot,
                        ),
                        retryable=True,
                    )
            elif decision is None:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_command_execution_forbidden",
                    reason_detail=format_watchdog_command_reason_detail(
                        stage_label="strict JSON stage",
                        last_command=snapshot.last_command,
                    ),
                    retryable=True,
                )
        elif not allow_workspace_commands and final_agent_message_state == "malformed":
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_malformed_final_output",
                reason_detail=(
                    snapshot.final_agent_message_reason
                    or "strict JSON stage emitted malformed pseudo-final output"
                ),
                retryable=True,
            )
        elif snapshot.reasoning_item_count >= 2 and final_agent_message_state != "json_object":
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_reasoning_without_output",
                reason_detail="strict JSON stage emitted repeated reasoning without a final answer",
                retryable=True,
            )
        elif (
            silence_timeout_seconds is not None
            and snapshot.last_event_seconds_ago is not None
            and snapshot.last_event_seconds_ago >= float(silence_timeout_seconds)
            and final_agent_message_state != "json_object"
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_no_activity_timeout",
                reason_detail=(
                    "strict JSON stage emitted no new activity for "
                    f"{int(float(silence_timeout_seconds))} seconds without reaching final output"
                ),
                retryable=True,
            )
        elif (
            cohort_completed_successful_shards >= _KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0) >= _KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS
            and (snapshot.elapsed_seconds * 1000.0)
            >= (float(cohort_median_duration_ms) * _KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR)
            and final_agent_message_state != "json_object"
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_cohort_runtime_outlier",
                reason_detail=(
                    "strict JSON stage exceeded sibling median runtime without reaching final output"
                ),
                retryable=True,
            )
        status_payload = {
            "state": (
                "completed"
                if isinstance(decision, CodexExecSupervisionDecision)
                and decision.action == "terminate"
                and str(decision.supervision_state or "").strip() == "completed"
                else "watchdog_killed"
                if isinstance(decision, CodexExecSupervisionDecision)
                and decision.action == "terminate"
                else "running"
            ),
            "elapsed_seconds": round(snapshot.elapsed_seconds, 3),
            "last_event_seconds_ago": (
                round(snapshot.last_event_seconds_ago, 3)
                if snapshot.last_event_seconds_ago is not None
                else None
            ),
            "event_count": snapshot.event_count,
            "command_execution_count": snapshot.command_execution_count,
            "command_execution_tolerated": command_execution_tolerated,
            "last_command_policy": last_command_verdict.policy,
            "last_command_policy_allowed": last_command_verdict.allowed,
            "last_command_policy_reason": last_command_verdict.reason,
            "last_command_boundary_violation_detected": (
                last_command_boundary_violation is not None
            ),
            "last_command_boundary_policy": (
                last_command_boundary_violation.policy
                if last_command_boundary_violation is not None
                else None
            ),
            "last_command_boundary_reason": (
                last_command_boundary_violation.reason
                if last_command_boundary_violation is not None
                else None
            ),
            "reasoning_item_count": snapshot.reasoning_item_count,
            "last_command": snapshot.last_command,
            "last_command_repeat_count": snapshot.last_command_repeat_count,
            "has_final_agent_message": snapshot.has_final_agent_message,
            "final_agent_message_state": final_agent_message_state,
            "final_agent_message_reason": snapshot.final_agent_message_reason,
            "timeout_seconds": snapshot.timeout_seconds,
            "silence_timeout_seconds": (
                round(float(silence_timeout_seconds), 3)
                if silence_timeout_seconds is not None
                else None
            ),
            "watchdog_policy": watchdog_policy,
            "shard_id": shard_id,
            "cohort_completed_successful_shards": cohort_completed_successful_shards,
            "cohort_median_duration_ms": cohort_median_duration_ms,
            "cohort_elapsed_ratio": cohort_elapsed_ratio,
            "workspace_output_expected_count": workspace_output_status["expected_count"],
            "workspace_output_present_count": workspace_output_status["present_count"],
            "workspace_output_complete": workspace_output_status["complete"],
            "workspace_output_missing_files": workspace_output_status["missing_files"],
            "workspace_output_stable_passes": workspace_output_stable_passes,
            "reason_code": decision.reason_code if decision is not None else None,
            "reason_detail": decision.reason_detail if decision is not None else None,
            "retryable": decision.retryable if decision is not None else False,
        }
        for path in target_paths:
            _write_live_status(path, status_payload)
        return decision

    return _callback


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
) -> None:
    final_agent_message = assess_final_agent_message(run_result.response_text)
    state = str(run_result.supervision_state or "completed").strip() or "completed"
    reason_code = run_result.supervision_reason_code
    reason_detail = run_result.supervision_reason_detail
    if state == "completed" and not str(reason_code or "").strip():
        reason_code = "process_exited_without_watchdog_intervention"
        reason_detail = (
            str(reason_detail or "").strip()
            or "worker process exited without watchdog intervention"
        )
    _write_live_status(
        live_status_path,
        {
            "state": state,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": watchdog_policy,
            "has_final_agent_message": final_agent_message.state != "absent",
            "final_agent_message_state": final_agent_message.state,
            "final_agent_message_reason": final_agent_message.reason,
        },
    )


def _write_live_status(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(dict(payload), path)


def _failure_reason_from_run_result(
    *,
    run_result: CodexExecRunResult,
    proposal_status: str,
) -> str:
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code)
    if str(run_result.supervision_state or "").strip() in {
        "preflight_rejected",
        "watchdog_killed",
    }:
        return str(run_result.supervision_state)
    return (
        "proposal_validation_failed"
        if proposal_status == "invalid"
        else "missing_output_file"
    )


def _terminal_reason_for_knowledge_task(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    run_result: CodexExecRunResult,
    retry_skip_reason_code: str | None = None,
    retry_skip_reason_detail: str | None = None,
    repair_skip_reason_code: str | None = None,
    repair_skip_reason_detail: str | None = None,
) -> tuple[str | None, str | None]:
    if str(repair_skip_reason_code or "").strip():
        return str(repair_skip_reason_code).strip(), str(repair_skip_reason_detail or "").strip() or None
    if str(retry_skip_reason_code or "").strip():
        return str(retry_skip_reason_code).strip(), str(retry_skip_reason_detail or "").strip() or None
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code).strip(), str(run_result.supervision_reason_detail or "").strip() or None
    metadata = dict(validation_metadata or {})
    if proposal_status == "validated":
        return "validated", None
    if validation_errors:
        return str(validation_errors[0]).strip(), str(
            metadata.get("parse_error")
            or metadata.get("semantic_rejection_reason")
            or ""
        ).strip() or None
    return str(proposal_status).strip() or None, None


def _summarize_workspace_output_paths(paths: Sequence[Path]) -> dict[str, Any]:
    expected_count = len(paths)
    if expected_count <= 0:
        return {
            "expected_count": 0,
            "present_count": 0,
            "complete": False,
            "missing_files": [],
            "signature": (),
        }
    present_count = 0
    missing_files: list[str] = []
    signature: list[tuple[str, int, int]] = []
    complete = True
    for path in paths:
        path_obj = Path(path)
        if not path_obj.exists() or not path_obj.is_file():
            complete = False
            missing_files.append(path_obj.name)
            continue
        try:
            stat_result = path_obj.stat()
        except OSError:
            complete = False
            missing_files.append(path_obj.name)
            continue
        if int(stat_result.st_size or 0) <= 0:
            complete = False
            missing_files.append(path_obj.name)
            continue
        try:
            payload = json.loads(path_obj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            complete = False
            missing_files.append(path_obj.name)
            continue
        if not isinstance(payload, Mapping):
            complete = False
            missing_files.append(path_obj.name)
            continue
        present_count += 1
        signature.append((path_obj.name, int(stat_result.st_size), int(stat_result.st_mtime_ns)))
    return {
        "expected_count": expected_count,
        "present_count": present_count,
        "complete": complete and present_count == expected_count,
        "missing_files": sorted(missing_files),
        "signature": tuple(signature),
    }


def _run_result_process_status(run_result: CodexExecRunResult) -> str:
    return "done" if run_result.completed_successfully() else "failed"


def _classify_knowledge_watchdog_retry_size(
    *,
    shard: ShardManifestEntryV1,
) -> dict[str, Any]:
    metadata = dict(shard.metadata or {})
    chunk_count = max(0, int(metadata.get("chunk_count") or len(shard.owned_ids)))
    char_count = max(0, int(metadata.get("char_count") or 0))
    oversized = (
        chunk_count > 1
        and (
            chunk_count > _KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD
            or char_count > _KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD
        )
    )
    if not oversized:
        return {
            "oversized": False,
            "reason_code": None,
            "reason_detail": None,
            "chunk_count": chunk_count,
            "char_count": char_count,
        }
    return {
        "oversized": True,
        "reason_code": "watchdog_retry_oversized_skipped",
        "reason_detail": (
            "skipped monolithic strict JSON watchdog retry because the shard owns "
            "multiple chunks and exceeds the retry-safe size policy "
            f"(chunk_count={chunk_count}, char_count={char_count}, "
            f"limits={_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD} chunk / "
            f"{_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD} chars)"
        ),
        "chunk_count": chunk_count,
        "char_count": char_count,
    }


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _salvage_knowledge_json_object_suffix(
    response_text: str,
) -> tuple[str | None, dict[str, Any]]:
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text.startswith("{"):
        return None, {}
    decoder = json.JSONDecoder()
    try:
        parsed_payload, end_index = decoder.raw_decode(cleaned_response_text)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(parsed_payload, dict):
        return None, {}
    trailing_text = cleaned_response_text[end_index:].strip()
    if not trailing_text or not _looks_like_salvageable_wrapper_noise(trailing_text):
        return None, {}
    return cleaned_response_text[:end_index], {
        "response_shell_wrapper_noise_trimmed": True,
        "response_shell_wrapper_noise_preview": trailing_text[:120],
    }


def _looks_like_salvageable_wrapper_noise(trailing_text: str) -> bool:
    cleaned = str(trailing_text or "").strip()
    if not cleaned:
        return False
    if "{" in cleaned or "[" in cleaned:
        return False
    wrapper_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not wrapper_lines:
        return False
    return all(
        line == "EOF"
        or line.startswith(("EOF ", "$ ", "# ", "> ", "sh:", "bash:", "/bin/bash:", "done", "exit"))
        for line in wrapper_lines
    )


def _poison_reason_for_failure_signature(
    failure_signature: str,
) -> tuple[str, str] | None:
    normalized = str(failure_signature or "").strip()
    if normalized in {"invalid_json", "schema_invalid"}:
        return (
            "poisoned_worker_uniform_malformed_outputs",
            "worker repeatedly produced malformed or schema-invalid packet outputs",
        )
    if normalized in {"semantic_invalid", "semantic_low_trust"}:
        return (
            "poisoned_worker_uniform_low_trust_outputs",
            "worker repeatedly produced low-trust outputs that failed semantic validation",
        )
    if normalized in {"watchdog_boundary", "watchdog_command_loop"}:
        return (
            "poisoned_worker_repeated_boundary_failures",
            "worker repeatedly died on the same watchdog boundary failure before producing usable packets",
        )
    if normalized == "missing_output":
        return (
            "poisoned_worker_zero_output",
            "worker repeatedly produced no usable packet output",
        )
    return None


def _knowledge_failure_signature(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    run_result: CodexExecRunResult | None = None,
) -> str:
    if proposal_status == "validated":
        return "validated"
    errors = {str(error).strip() for error in validation_errors if str(error).strip()}
    metadata = dict(validation_metadata or {})
    reason_code = str(
        ((run_result.supervision_reason_code) if run_result is not None else "") or ""
    ).strip()
    if proposal_status == "missing_output" or "missing_output_file" in errors:
        return "missing_output"
    if reason_code == "watchdog_command_execution_forbidden":
        return "watchdog_boundary"
    if reason_code == "watchdog_command_loop_without_output":
        return "watchdog_command_loop"
    if "response_json_invalid" in errors or "response_not_json_object" in errors:
        return "invalid_json"
    if "schema_invalid" in errors:
        return "schema_invalid"
    if any(error.startswith("semantic_") for error in errors):
        return "semantic_invalid"
    if metadata.get("non_grounded_snippet_chunk_ids") or metadata.get("echoed_full_chunk_ids"):
        return "semantic_low_trust"
    if errors.intersection(
        {
            "missing_owned_chunk_results",
            "unexpected_chunk_results",
            "chunk_result_order_mismatch",
        }
    ):
        return "coverage_mismatch"
    return "invalid_output"


def _is_knowledge_near_miss(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    errors = {str(error).strip() for error in validation_errors if str(error).strip()}
    if not errors or len(errors) > 2:
        return False
    if not errors.issubset(_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS):
        return False
    metadata = dict(validation_metadata or {})
    if metadata.get("semantic_rejection"):
        return False
    if metadata.get("non_grounded_snippet_chunk_ids") or metadata.get("echoed_full_chunk_ids"):
        return False
    return True


def _should_attempt_knowledge_watchdog_retry(
    *,
    run_result: CodexExecRunResult,
) -> bool:
    if str(run_result.supervision_state or "").strip() != "watchdog_killed":
        return False
    if not run_result.supervision_retryable:
        return False
    return str(run_result.supervision_reason_code or "").strip() in {
        "watchdog_command_execution_forbidden",
        "watchdog_command_loop_without_output",
        "watchdog_reasoning_without_output",
        "watchdog_cohort_runtime_outlier",
    }


def _build_knowledge_watchdog_example(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    result_rows = payload.get("r")
    if not isinstance(result_rows, list):
        return None
    compact_rows = [
        dict(row_payload)
        for row_payload in result_rows[:2]
        if isinstance(row_payload, Mapping)
    ]
    if not compact_rows:
        return None
    return {
        "shard_id": shard.shard_id,
        "owned_ids": list(shard.owned_ids),
        "output": {
            "v": str(payload.get("v") or "2"),
            "bid": str(payload.get("bid") or shard.shard_id),
            "r": compact_rows,
        },
    }


def _is_pathological_knowledge_response_text(
    response_text: str,
    *,
    owned_chunk_count: int,
    returned_chunk_count: int,
) -> bool:
    cleaned = str(response_text or "")
    if not cleaned.strip():
        return False
    if re.search(rf"\s{{{_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN},}}", cleaned):
        return True
    effective_rows = max(1, int(returned_chunk_count or 0))
    chars_per_row = len(cleaned) / effective_rows
    if (
        int(owned_chunk_count or 0) > effective_rows
        and chars_per_row >= _KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW
    ):
        return True
    return False


def _should_retry_knowledge_shard_split(
    *,
    shard: ShardManifestEntryV1,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    response_text: str | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    if len(shard.owned_ids) <= 1:
        return False
    errors = {str(error) for error in validation_errors}
    if not errors.intersection(
        {
            "missing_owned_chunk_results",
            "unexpected_chunk_results",
            "response_json_invalid",
            "response_not_json_object",
        }
    ):
        return False
    returned_chunk_count = int(validation_metadata.get("result_chunk_count") or 0)
    if "missing_owned_chunk_results" in errors and returned_chunk_count < len(shard.owned_ids):
        return True
    return _is_pathological_knowledge_response_text(
        str(response_text or ""),
        owned_chunk_count=len(shard.owned_ids),
        returned_chunk_count=returned_chunk_count,
    )


def _split_failed_knowledge_shard_for_retry(
    shard: ShardManifestEntryV1,
    *,
    max_retry_chunk_count: int,
    max_retry_chars: int,
) -> tuple[ShardManifestEntryV1, ...]:
    payload = _coerce_dict(shard.input_payload)
    chunks = payload.get("c")
    if not isinstance(chunks, list):
        return ()
    normalized_max_chunks = max(1, int(max_retry_chunk_count or 1))
    normalized_max_chars = max(1, int(max_retry_chars or 1))
    retry_shards: list[ShardManifestEntryV1] = []
    current_group: list[dict[str, Any]] = []
    current_group_chars = 0

    def _flush_group(group: list[dict[str, Any]]) -> None:
        if not group:
            return
        retry_index = len(retry_shards) + 1
        retry_shard_id = f"{shard.shard_id}.retry{retry_index:02d}"
        retry_payload: dict[str, Any] = {
            "v": str(payload.get("v") or "2"),
            "bid": retry_shard_id,
            "c": [dict(chunk_payload) for chunk_payload in group],
        }
        if "x" in payload:
            retry_payload["x"] = payload["x"]
        if "g" in payload:
            retry_payload["g"] = payload["g"]
        owned_ids = tuple(
            str(chunk_payload.get("cid") or "").strip()
            for chunk_payload in group
            if str(chunk_payload.get("cid") or "").strip()
        )
        owned_block_indices = sorted(
            {
                int(block.get("i"))
                for chunk_payload in group
                for block in (chunk_payload.get("b") or [])
                if isinstance(block, Mapping) and block.get("i") is not None
            }
        )
        char_count = sum(
            len(str(block.get("t") or ""))
            for chunk_payload in group
            for block in (chunk_payload.get("b") or [])
            if isinstance(block, Mapping)
        )
        retry_shards.append(
            ShardManifestEntryV1(
                shard_id=retry_shard_id,
                owned_ids=owned_ids,
                evidence_refs=tuple(f"block:{index}" for index in owned_block_indices),
                input_payload=retry_payload,
                metadata={
                    **dict(shard.metadata or {}),
                    "ordered_chunk_ids": list(owned_ids),
                    "owned_block_indices": list(owned_block_indices),
                    "chunk_count": len(owned_ids),
                    "char_count": char_count,
                    "retry_parent_shard_id": shard.shard_id,
                    **_subset_knowledge_shard_metadata(
                        metadata=shard.metadata,
                        owned_ids=owned_ids,
                    ),
                },
            )
        )

    for raw_chunk in chunks:
        if not isinstance(raw_chunk, Mapping):
            continue
        chunk_payload = dict(raw_chunk)
        chunk_char_count = sum(
            len(str(block.get("t") or ""))
            for block in (chunk_payload.get("b") or [])
            if isinstance(block, Mapping)
        )
        if current_group and (
            len(current_group) >= normalized_max_chunks
            or current_group_chars + chunk_char_count > normalized_max_chars
        ):
            _flush_group(current_group)
            current_group = []
            current_group_chars = 0
        current_group.append(chunk_payload)
        current_group_chars += chunk_char_count
    _flush_group(current_group)
    return tuple(retry_shards)


def _subset_knowledge_shard_metadata(
    *,
    metadata: Mapping[str, Any] | None,
    owned_ids: Sequence[str],
) -> dict[str, Any]:
    source = dict(metadata or {})
    owned_id_set = {str(chunk_id).strip() for chunk_id in owned_ids if str(chunk_id).strip()}
    subset: dict[str, Any] = {}
    for key in (
        "chunk_block_indices_by_id",
        "chunk_seed_stage_category_by_id",
        "chunk_lane_by_id",
        "chunk_title_by_id",
        "chunk_has_heading_by_id",
        "chunk_has_table_hint_by_id",
        "chunk_knowledge_cue_by_id",
    ):
        raw_mapping = source.get(key)
        if not isinstance(raw_mapping, Mapping):
            continue
        subset[key] = {
            str(chunk_id): value
            for chunk_id, value in raw_mapping.items()
            if str(chunk_id).strip() in owned_id_set
        }
    return subset


def _should_attempt_knowledge_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
) -> bool:
    if proposal_status != "invalid":
        return False
    repairable_errors = {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
    }
    return bool(set(validation_errors).intersection(repairable_errors))


def _run_knowledge_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    (worker_root / "shards" / shard.shard_id / "repair_prompt.txt").write_text(
        prompt_text,
        encoding="utf-8",
    )
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "knowledge",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "authoritative_input": _coerce_dict(shard.input_payload),
            "previous_output": _truncate_for_repair(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge repair shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _run_knowledge_watchdog_retry_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_watchdog_retry_prompt(
        shard=shard,
        reason_code=reason_code,
        reason_detail=reason_detail,
        successful_examples=successful_examples,
    )
    retry_root = worker_root / "shards" / shard.shard_id / "watchdog_retry"
    retry_root.mkdir(parents=True, exist_ok=True)
    (retry_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "retry_mode": "knowledge_watchdog",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "retry_reason": {
                "code": reason_code,
                "detail": reason_detail,
            },
            "successful_examples": [dict(example_payload) for example_payload in successful_examples],
            "authoritative_input": _coerce_dict(shard.input_payload),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=_KNOWLEDGE_WATCHDOG_RETRY_TIMEOUT_SECONDS,
        workspace_task_label="knowledge watchdog retry shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(
                live_status_path=live_status_path,
                silence_timeout_seconds=_KNOWLEDGE_WATCHDOG_RETRY_SILENCE_TIMEOUT_SECONDS,
            )
            if live_status_path is not None
            else None
        ),
    )


def _build_knowledge_watchdog_retry_prompt(
    *,
    shard: ShardManifestEntryV1,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
) -> str:
    owned_ids = ", ".join(str(chunk_id) for chunk_id in shard.owned_ids)
    example_rows = [
        json.dumps(dict(example_payload), ensure_ascii=False, sort_keys=True)
        for example_payload in successful_examples[:_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES]
        if isinstance(example_payload, Mapping)
    ]
    examples_block = (
        "\n".join(example_rows)
        if example_rows
        else "[no sibling examples available]"
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Retry the strict JSON knowledge shard after the previous attempt was stopped.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- The first emitted character must be `{`.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return exactly one result row for each owned chunk id.\n"
        f"- Owned chunk ids: {owned_ids}\n"
        "- Preserve chunk-local evidence and do not invent synthetic ids.\n\n"
        f"Previous stop reason: {reason_code or '[unknown]'}\n"
        f"Reason detail: {reason_detail or '[none recorded]'}\n\n"
        "Successful sibling examples:\n"
        "<BEGIN_SUCCESSFUL_SIBLING_EXAMPLES>\n"
        f"{examples_block}\n"
        "<END_SUCCESSFUL_SIBLING_EXAMPLES>\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n"
    )


def _build_knowledge_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    owned_ids = ", ".join(str(chunk_id) for chunk_id in shard.owned_ids)
    missing_ids = ", ".join(
        str(chunk_id)
        for chunk_id in (validation_metadata.get("missing_owned_chunk_ids") or [])
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Repair the invalid knowledge shard output.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- The first emitted character must be `{`.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return exactly one result row for each owned chunk id.\n"
        f"- Owned chunk ids: {owned_ids}\n"
        "- Preserve chunk-local evidence and do not invent synthetic ids.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        f"Missing owned chunk ids: {missing_ids or '[none recorded]'}\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_for_repair(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _truncate_for_repair(text: str, *, max_chars: int = 20_000) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "\n...[truncated]"


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _summarize_direct_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _aggregate_worker_runner_payload(
    *,
    pipeline_id: str,
    worker_runs: list[Mapping[str, Any]],
    stage_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for worker_run in worker_runs:
        telemetry = worker_run.get("telemetry")
        if not isinstance(telemetry, Mapping):
            continue
        worker_rows = telemetry.get("rows")
        if isinstance(worker_rows, list):
            rows.extend([dict(row) for row in worker_rows if isinstance(row, Mapping)])
    if stage_rows is not None:
        rows = [dict(row) for row in stage_rows if isinstance(row, Mapping)]
    uses_workspace_worker = any(
        str(
            ((payload.get("process_payload") or {}) if isinstance(payload, Mapping) else {}).get(
                "prompt_input_mode"
            )
            or ""
        ).strip()
        == "workspace_worker"
        for payload in worker_runs
        if isinstance(payload, Mapping)
    )
    return {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": [dict(payload) for payload in worker_runs],
        "telemetry": {
            "rows": rows,
            "summary": _summarize_direct_rows(rows),
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": not uses_workspace_worker,
            "tool_affordances_requested": uses_workspace_worker,
        },
    }

def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            by_index[index] = dict(raw_block)
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
        )
    return root


def _non_empty(value: object, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_block_category_updates(
    *,
    outputs: Mapping[str, Any],
    allowed_block_indices: Mapping[int, str],
) -> tuple[
    dict[int, str],
    dict[int, str],
    dict[int, list[str]],
    list[dict[str, Any]],
    list[int],
]:
    normalized_allowed = {
        int(block_index): str(category or "other")
        for block_index, category in allowed_block_indices.items()
    }
    decisions_by_block: dict[int, list[tuple[str, str, str | None]]] = {}
    ignored_block_indices: list[int] = []
    for chunk_id, output in outputs.items():
        for decision in output.block_decisions:
            block_index = int(decision.block_index)
            if block_index not in normalized_allowed:
                ignored_block_indices.append(block_index)
                continue
            decisions_by_block.setdefault(block_index, []).append(
                (
                    str(chunk_id),
                    str(decision.category),
                    str(decision.reviewer_category or "").strip() or None,
                )
            )

    block_category_updates: dict[int, str] = {}
    reviewer_categories_by_block: dict[int, str] = {}
    applied_chunk_ids_by_block: dict[int, list[str]] = {}
    conflicts: list[dict[str, Any]] = []
    for block_index, decision_rows in sorted(decisions_by_block.items()):
        categories = {category for _, category, _ in decision_rows}
        if len(categories) > 1:
            conflicts.append(
                {
                    "block_index": int(block_index),
                    "seed_category": normalized_allowed.get(block_index),
                    "decisions": [
                        {
                            "chunk_id": chunk_id,
                            "category": category,
                            "reviewer_category": reviewer_category,
                        }
                        for chunk_id, category, reviewer_category in decision_rows
                    ],
                    "resolution": "kept_seed_category",
                }
            )
            continue
        block_category_updates[block_index] = next(iter(categories))
        reviewer_categories = [
            reviewer_category
            for _, _, reviewer_category in decision_rows
            if reviewer_category is not None
        ]
        if reviewer_categories:
            reviewer_categories_by_block[block_index] = reviewer_categories[0]
        applied_chunk_ids_by_block[block_index] = [
            chunk_id for chunk_id, _, _ in decision_rows
        ]
    return (
        block_category_updates,
        reviewer_categories_by_block,
        applied_chunk_ids_by_block,
        conflicts,
        ignored_block_indices,
    )
