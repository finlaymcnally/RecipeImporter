from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .codex_farm_runner import CodexFarmRunner, as_pipeline_run_result_payload


@dataclass(frozen=True)
class PhaseManifestV1:
    schema_version: str
    phase_key: str
    pipeline_id: str
    run_root: str
    worker_count: int
    shard_count: int
    assignment_strategy: str
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


ProposalValidatorV1 = Callable[
    [ShardManifestEntryV1, dict[str, Any]],
    tuple[bool, Sequence[str], Mapping[str, Any] | None],
]


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


def _assign_workers(
    *,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = max(1, min(int(worker_count or 1), max(len(shards), 1)))
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
    max_turns_per_shard: int | None = None,
    proposal_validator: ProposalValidatorV1 | None = None,
    settings: Mapping[str, Any] | None = None,
    runtime_metadata: Mapping[str, Any] | None = None,
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

    for assignment in assignments:
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
            runtime_audit_mode="structured_loop_agentic_v1",
        )
        runner_payload = as_pipeline_run_result_payload(runner_result)
        _write_json(worker_root / "status.json", runner_payload or {})

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
                failures.append(failure)
                all_proposals.append(
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
                failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": "proposal_validation_failed",
                        "validation_errors": list(validation_errors),
                    }
                )
            else:
                worker_proposal_count += 1
            all_proposals.append(
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

        worker_reports.append(
            WorkerExecutionReportV1(
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
            )
        )

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
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        max_turns_per_shard=max_turns_per_shard,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(run_root / artifacts["phase_manifest"], asdict(manifest))
    return manifest, worker_reports
