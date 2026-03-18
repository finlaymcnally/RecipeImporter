from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.core.progress_messages import format_stage_counter_progress

from .codex_farm_runner import (
    CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1,
    CodexFarmRunner,
    as_pipeline_run_result_payload,
)

DEFAULT_PHASE_WORKER_CAP = 20


@dataclass(frozen=True)
class PhaseManifestV1:
    schema_version: str
    phase_key: str
    pipeline_id: str
    run_root: str
    worker_count: int
    shard_count: int
    assignment_strategy: str
    runtime_mode: str | None = None
    max_turns_per_shard: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShardManifestEntryV1:
    shard_id: str
    owned_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    input_payload: Any = field(default_factory=dict)
    input_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerAssignmentV1:
    worker_id: str
    shard_ids: tuple[str, ...]
    workspace_root: str


@dataclass(frozen=True)
class ShardProposalV1:
    shard_id: str
    worker_id: str
    status: str
    proposal_path: str | None
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerExecutionReportV1:
    worker_id: str
    shard_ids: tuple[str, ...]
    workspace_root: str
    status: str
    proposal_count: int
    failure_count: int
    runtime_mode_audit: dict[str, Any] | None = None
    runner_result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerAssignmentResultV1:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]


ProposalValidatorV1 = Callable[
    [ShardManifestEntryV1, dict[str, Any]],
    tuple[bool, Sequence[str], Mapping[str, Any] | None],
]


def resolve_phase_worker_count(
    *,
    requested_worker_count: Any,
    shard_count: int,
    default_cap: int = DEFAULT_PHASE_WORKER_CAP,
) -> int:
    normalized_shard_count = max(0, int(shard_count or 0))
    if normalized_shard_count <= 0:
        return 0
    try:
        normalized_cap = max(1, int(default_cap or 1))
    except (TypeError, ValueError):
        normalized_cap = DEFAULT_PHASE_WORKER_CAP
    if requested_worker_count is None or requested_worker_count == "":
        return min(normalized_shard_count, normalized_cap)
    try:
        parsed = int(requested_worker_count)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, normalized_shard_count))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")


def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _default_validate_proposal(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, Sequence[str], Mapping[str, Any] | None]:
    if not isinstance(payload, dict):
        return False, ("proposal_not_a_json_object",), None
    return True, (), {
        "owned_id_count": len(shard.owned_ids),
        "evidence_ref_count": len(shard.evidence_refs),
    }


def _phase_progress_stage_label(value: str | None, *, fallback: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned:
        return cleaned
    return fallback.replace("_", " ").strip() or "phase work"


def _phase_progress_task_label(shard_ids: Sequence[str]) -> str:
    if not shard_ids:
        return "[idle]"
    first = str(shard_ids[0]).strip() or "[unknown shard]"
    remaining = max(0, len(shard_ids) - 1)
    if remaining <= 0:
        return first
    return f"{first} (+{remaining} more)"


def _assign_workers(
    *,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
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


def _run_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexFarmRunner,
    pipeline_id: str,
    root_dir: Path | None,
    env: Mapping[str, str] | None,
    model: str | None,
    reasoning_effort: str | None,
    runtime_mode: str,
    process_worker_count: int | None,
    validator: ProposalValidatorV1,
) -> WorkerAssignmentResultV1:
    worker_root = Path(assignment.workspace_root)
    sandbox_root = worker_root / "sandbox"
    in_dir = worker_root / "in"
    out_dir = worker_root / "out"
    logs_dir = worker_root / "logs"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json(
        worker_root / "assigned_shards.json",
        [asdict(shard) for shard in assigned_shards],
    )
    for shard in assigned_shards:
        _write_worker_input(
            in_dir / f"{shard.shard_id}.json",
            payload=shard.input_payload,
            input_text=shard.input_text,
        )

    runner_result = runner.run_pipeline(
        pipeline_id,
        in_dir,
        out_dir,
        dict(env or {}),
        root_dir=root_dir,
        workspace_root=worker_root,
        model=model,
        reasoning_effort=reasoning_effort,
        runtime_mode=runtime_mode,
        process_worker_count=process_worker_count,
    )
    runner_payload = as_pipeline_run_result_payload(runner_result)
    _write_json(worker_root / "status.json", runner_payload or {})

    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_failure_count = 0
    worker_proposal_count = 0
    for shard in assigned_shards:
        out_path = out_dir / f"{shard.shard_id}.json"
        if not out_path.exists():
            worker_failure_count += 1
            failure = {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "missing_output_file",
                "expected_output_path": _relative_path(run_root, out_path),
            }
            worker_failures.append(failure)
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status="missing_output",
                    proposal_path=None,
                    validation_errors=("missing_output_file",),
                )
            )
            continue
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        valid, validation_errors, validation_metadata = validator(shard, payload)
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            proposal_path,
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            },
        )
        proposal_status = "validated" if valid else "invalid"
        if not valid:
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": "proposal_validation_failed",
                    "validation_errors": list(validation_errors),
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
                validation_errors=tuple(str(item) for item in validation_errors),
                metadata=dict(validation_metadata or {}),
            )
        )

    return WorkerAssignmentResultV1(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit=(
                dict(runner_payload.get("runtime_mode_audit") or {})
                if isinstance(runner_payload, dict)
                else None
            ),
            runner_result=runner_payload,
            metadata={
                "sandbox_root": _relative_path(run_root, sandbox_root),
                "in_dir": _relative_path(run_root, in_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
    )


def run_phase_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    runner: CodexFarmRunner,
    worker_count: int,
    root_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    runtime_mode: str = CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1,
    process_worker_count: int | None = 1,
    max_turns_per_shard: int | None = None,
    proposal_validator: ProposalValidatorV1 | None = None,
    settings: Mapping[str, Any] | None = None,
    runtime_metadata: Mapping[str, Any] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    progress_message_prefix: str | None = None,
    progress_stage_label: str | None = None,
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1]]:
    run_root = run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    validator = proposal_validator or _default_validate_proposal
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_workers(run_root=run_root, shards=shards, worker_count=worker_count)

    _write_jsonl(
        run_root / artifacts["shard_manifest"],
        [asdict(shard) for shard in shards],
    )
    _write_json(
        run_root / artifacts["worker_assignments"],
        [asdict(assignment) for assignment in assignments],
    )

    all_proposals: list[ShardProposalV1] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    failures: list[dict[str, Any]] = []
    total_shards = len(shards)
    displayed_worker_total = len(assignments)
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }
    completed_shards = 0

    def _emit_progress() -> None:
        if progress_callback is None or total_shards <= 0:
            return
        active_tasks = [
            _phase_progress_task_label(pending)
            for assignment in assignments
            for pending in [pending_shards_by_worker.get(assignment.worker_id) or []]
            if pending
        ]
        running_workers = len(active_tasks)
        detail_lines = [
            f"configured workers: {displayed_worker_total}",
            f"queued shards: {max(0, total_shards - completed_shards)}",
        ]
        progress_callback(
            format_stage_counter_progress(
                str(progress_message_prefix or "Running phase workers...").strip(),
                completed_shards,
                total_shards,
                stage_label=_phase_progress_stage_label(
                    progress_stage_label,
                    fallback=phase_key,
                ),
                running_workers=running_workers,
                worker_total=displayed_worker_total,
                active_tasks=active_tasks if active_tasks else [],
                detail_lines=detail_lines,
            )
        )

    _emit_progress()

    if assignments:
        with ThreadPoolExecutor(
            max_workers=len(assignments),
            thread_name_prefix="phase-worker",
        ) as executor:
            futures = {
                executor.submit(
                    _run_worker_assignment_v1,
                    run_root=run_root,
                    assignment=assignment,
                    artifacts=artifacts,
                    shard_by_id=shard_by_id,
                    runner=runner,
                    pipeline_id=pipeline_id,
                    root_dir=root_dir,
                    env=env,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    runtime_mode=runtime_mode,
                    process_worker_count=process_worker_count,
                    validator=validator,
                ): assignment
                for assignment in assignments
            }
            reports_by_worker_id: dict[str, WorkerExecutionReportV1] = {}
            proposals_by_worker_id: dict[str, tuple[ShardProposalV1, ...]] = {}
            failures_by_worker_id: dict[str, tuple[dict[str, Any], ...]] = {}
            for future in as_completed(futures):
                assignment = futures[future]
                result = future.result()
                reports_by_worker_id[assignment.worker_id] = result.report
                proposals_by_worker_id[assignment.worker_id] = result.proposals
                failures_by_worker_id[assignment.worker_id] = result.failures
                completed_shards += len(assignment.shard_ids)
                pending_shards_by_worker[assignment.worker_id] = []
                _emit_progress()
            for assignment in assignments:
                result_report = reports_by_worker_id[assignment.worker_id]
                worker_reports.append(result_report)
                all_proposals.extend(proposals_by_worker_id[assignment.worker_id])
                failures.extend(failures_by_worker_id[assignment.worker_id])

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(
            1 for proposal in all_proposals if proposal.status == "missing_output"
        ),
    }
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": runtime_mode,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
    }
    _write_json(run_root / artifacts["promotion_report"], promotion_report)
    _write_json(run_root / artifacts["telemetry"], telemetry)
    _write_json(run_root / artifacts["failures"], failures)

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        runtime_mode=runtime_mode,
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        max_turns_per_shard=(
            1 if runtime_mode == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1 else max_turns_per_shard
        ),
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(run_root / artifacts["phase_manifest"], asdict(manifest))
    return manifest, worker_reports
