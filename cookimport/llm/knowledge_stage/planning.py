from __future__ import annotations

import sys

runtime = sys.modules["cookimport.llm.knowledge_stage"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)

@dataclass(frozen=True)
class _KnowledgeWorkspaceStageCommandViolation:
    policy: str
    reason_code: str
    reason: str
    enforce: bool = True


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _build_knowledge_task_manifest_entry(
    shard: ShardManifestEntryV1,
) -> TaskManifestEntryV1:
    return TaskManifestEntryV1(
        task_id=shard.shard_id,
        task_kind="knowledge_review_packet_task",
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
    blocks = [dict(row) for row in (payload.get("b") or []) if isinstance(row, Mapping)]
    if not blocks:
        return ()
    task_id = str(shard.shard_id).strip()
    owned_block_indices = [
        int(block.get("i"))
        for block in blocks
        if isinstance(block, Mapping) and block.get("i") is not None
    ]
    task_payload = {
        **payload,
        "bid": task_id,
    }
    task_manifest = ShardManifestEntryV1(
        shard_id=task_id,
        owned_ids=tuple(shard.owned_ids),
        evidence_refs=tuple(shard.evidence_refs),
        input_payload=task_payload,
        input_text=shard.input_text,
        metadata={
            **dict(shard.metadata or {}),
            "parent_shard_id": shard.shard_id,
            "task_id": task_id,
            "task_index": 1,
            "task_count": 1,
            "packet_count": 1,
            "owned_block_indices": owned_block_indices,
        },
    )
    return (
        _KnowledgeTaskPlan(
            task_id=task_id,
            parent_shard_id=shard.shard_id,
            manifest_entry=task_manifest,
        ),
    )


def _build_knowledge_task_runtime_manifest_entry(
    task_plan: _KnowledgeTaskPlan,
) -> TaskManifestEntryV1:
    task_manifest = task_plan.manifest_entry
    return TaskManifestEntryV1(
        task_id=task_plan.task_id,
        task_kind="knowledge_review_packet_task",
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
            "workspace_processing_contract": "ordered_task_micro_batch_v1",
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
        "bundle_policy": "shard_round_robin_packet_bundle_tasks_v1",
        "task_total": sum(counts),
        "worker_task_counts": dict(sorted(worker_task_packet_counts.items())),
        "max_tasks_per_worker": max(counts) if counts else 0,
        "min_tasks_per_worker": min(counts) if counts else 0,
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
    accepted_task_ids: list[str] = []
    accepted_payload: dict[str, Any] | None = None
    for task_id, payload in task_payloads_by_task_id.items():
        if not isinstance(payload, Mapping):
            continue
        accepted_task_ids.append(task_id)
        accepted_payload = dict(payload)
        break
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
        "missing_packet_ids": [] if accepted_payload is not None else [shard.shard_id],
        "task_ids": all_task_ids,
        "task_validation_errors_by_task_id": {
            task_id: list(errors)
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors
        },
        "task_id_by_packet_id": {
            shard.shard_id: accepted_task_ids[0]
            for _ in [0]
            if accepted_task_ids
        },
    }
    return dict(accepted_payload or {"packet_id": shard.shard_id, "block_decisions": [], "idea_groups": []}), metadata


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
            work_unit_label="task",
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
            f"({self.visible_task_packets()}/{self.total_task_packets} tasks)"
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
            f"queued tasks: {max(0, self.total_task_packets - completed_task_packets)}",
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
