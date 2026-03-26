from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .knowledge_runtime_state import (
    KnowledgeArtifactState,
    KnowledgePacketAttemptType,
    KnowledgePacketLedger,
    KnowledgePacketRecord,
    KnowledgePacketState,
    KnowledgePacketTerminalOutcome,
    KnowledgeStageRollup,
    KnowledgeWorkerOutcomeCategory,
)

EXPECTED_KNOWLEDGE_STAGE_ARTIFACTS: tuple[str, ...] = (
    "shard_manifest.jsonl",
    "task_manifest.jsonl",
    "worker_assignments.json",
    "phase_manifest.json",
    "promotion_report.json",
    "telemetry.json",
    "failures.json",
    "proposals/*",
)

EXPECTED_BENCHMARK_ARTIFACTS: tuple[str, ...] = (
    "processing_timeseries_prediction.jsonl",
    "processing_timeseries_evaluation.jsonl",
    "prompt_budget_summary.json",
    "eval_report.json",
)


@dataclass(frozen=True, slots=True)
class KnowledgeRuntimeReplaySummary:
    knowledge_root: Path
    benchmark_root: Path | None
    shard_total: int
    ledger: KnowledgePacketLedger
    rollup: KnowledgeStageRollup


@dataclass(slots=True)
class _PacketArtifacts:
    worker_id: str | None = None
    worker_outcome: KnowledgeWorkerOutcomeCategory | None = None
    main_output_present: bool = False
    main_output_malformed: bool = False
    watchdog_retry_status: str | None = None
    watchdog_retry_stale: bool = False
    repair_status: str | None = None
    repair_stale: bool = False


def replay_knowledge_runtime(
    *,
    knowledge_root: Path,
    benchmark_root: Path | None = None,
) -> KnowledgeRuntimeReplaySummary:
    knowledge_root = Path(knowledge_root)
    benchmark_root = Path(benchmark_root) if benchmark_root is not None else None

    task_entries = _load_task_entries(knowledge_root / "task_manifest.jsonl")
    shard_total = _count_jsonl_rows(knowledge_root / "shard_manifest.jsonl")
    packet_artifacts = _collect_packet_artifacts(knowledge_root)

    ledger = KnowledgePacketLedger()
    for task_entry in task_entries:
        packet_id = str(task_entry.get("task_id") or "").strip()
        if not packet_id:
            continue
        parent_shard_id = str(task_entry.get("parent_shard_id") or packet_id).strip() or packet_id
        artifacts = packet_artifacts.get(packet_id, _PacketArtifacts())
        state, terminal_outcome, latest_attempt_type, latest_reason = _classify_packet_state(
            artifacts=artifacts,
        )
        ledger.add(
            KnowledgePacketRecord(
                packet_id=packet_id,
                parent_shard_id=parent_shard_id,
                owned_ids=_coerce_str_tuple(task_entry.get("owned_ids")),
                worker_id=artifacts.worker_id,
                state=state,
                terminal_outcome=terminal_outcome,
                latest_attempt_type=latest_attempt_type,
                latest_reason=latest_reason,
                main_output_present=artifacts.main_output_present,
                main_output_malformed=artifacts.main_output_malformed,
                watchdog_retry_status=artifacts.watchdog_retry_status,
                watchdog_retry_stale=artifacts.watchdog_retry_stale,
                repair_status=artifacts.repair_status,
                repair_stale=artifacts.repair_stale,
            )
        )

    worker_outcome_counts = _collect_worker_outcome_counts(knowledge_root)
    worker_output_count, malformed_worker_output_count = _count_worker_outputs(knowledge_root)
    stage_artifact_states = _classify_artifact_states(
        knowledge_root,
        EXPECTED_KNOWLEDGE_STAGE_ARTIFACTS,
    )
    benchmark_artifact_states = (
        _classify_artifact_states(benchmark_root, EXPECTED_BENCHMARK_ARTIFACTS)
        if benchmark_root is not None
        else {}
    )
    rollup = ledger.rollup(
        worker_outcome_counts=worker_outcome_counts,
        worker_output_count=worker_output_count,
        malformed_worker_output_count=malformed_worker_output_count,
        stage_artifact_states=stage_artifact_states,
        benchmark_artifact_states=benchmark_artifact_states,
    )
    return KnowledgeRuntimeReplaySummary(
        knowledge_root=knowledge_root,
        benchmark_root=benchmark_root,
        shard_total=shard_total,
        ledger=ledger,
        rollup=rollup,
    )


def classify_worker_outcome(
    *,
    state: str | None,
    reason_code: str | None,
) -> KnowledgeWorkerOutcomeCategory:
    normalized_state = str(state or "").strip()
    normalized_reason = str(reason_code or "").strip()
    if normalized_state == "completed" and normalized_reason == "workspace_outputs_stabilized":
        return KnowledgeWorkerOutcomeCategory.COMPLETED_OUTPUTS_STABILIZED
    if normalized_state == "completed":
        return KnowledgeWorkerOutcomeCategory.COMPLETED_PROCESS_EXIT
    if normalized_state == "watchdog_killed" and normalized_reason == "watchdog_command_execution_forbidden":
        return KnowledgeWorkerOutcomeCategory.WATCHDOG_COMMAND_FORBIDDEN
    if normalized_state == "watchdog_killed":
        return KnowledgeWorkerOutcomeCategory.WATCHDOG_KILLED_OTHER
    if normalized_state == "running":
        return KnowledgeWorkerOutcomeCategory.RUNNING
    return KnowledgeWorkerOutcomeCategory.UNKNOWN


def _count_jsonl_rows(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _load_task_entries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _collect_packet_artifacts(knowledge_root: Path) -> dict[str, _PacketArtifacts]:
    packet_artifacts: dict[str, _PacketArtifacts] = {}
    workers_root = knowledge_root / "workers"
    if not workers_root.exists():
        return packet_artifacts
    assigned_ids_by_worker_id = _load_worker_assignment_ids(
        knowledge_root / "worker_assignments.json"
    )
    for worker_root in sorted(path for path in workers_root.iterdir() if path.is_dir()):
        worker_id = worker_root.name
        worker_outcome = _load_worker_outcome(worker_root / "live_status.json")
        assigned_ids = assigned_ids_by_worker_id.get(worker_id) or _load_assigned_shard_ids(
            worker_root / "assigned_shards.json"
        )
        for shard_id in assigned_ids:
            packet_artifacts.setdefault(shard_id, _PacketArtifacts()).worker_id = worker_id
            packet_artifacts[shard_id].worker_outcome = worker_outcome
        for output_path in sorted((worker_root / "out").glob("*.json")):
            task_id = output_path.stem
            entry = packet_artifacts.setdefault(task_id, _PacketArtifacts())
            entry.worker_id = entry.worker_id or worker_id
            entry.worker_outcome = entry.worker_outcome or worker_outcome
            entry.main_output_present = True
            entry.main_output_malformed = _is_malformed_json_file(output_path)
        for shard_root in sorted((worker_root / "shards").glob("*")):
            if not shard_root.is_dir():
                continue
            task_id = shard_root.name
            entry = packet_artifacts.setdefault(task_id, _PacketArtifacts())
            entry.worker_id = entry.worker_id or worker_id
            entry.worker_outcome = entry.worker_outcome or worker_outcome
            watchdog_retry_root = shard_root / "watchdog_retry"
            if watchdog_retry_root.exists():
                status_payload = _load_json_dict(watchdog_retry_root / "status.json")
                if status_payload is not None:
                    status = str(status_payload.get("status") or "").strip()
                    entry.watchdog_retry_status = status or None
                else:
                    live_status_payload = _load_json_dict(watchdog_retry_root / "live_status.json")
                    if _follow_up_live_status_is_stale(live_status_payload):
                        entry.watchdog_retry_stale = True
            repair_payload = _load_json_dict(shard_root / "repair_status.json")
            if repair_payload is not None:
                status = str(repair_payload.get("status") or "").strip()
                entry.repair_status = status or None
            else:
                repair_live_status = _load_json_dict(shard_root / "repair_live_status.json")
                if _follow_up_live_status_is_stale(repair_live_status):
                    entry.repair_stale = True
    return packet_artifacts


def _follow_up_live_status_is_stale(payload: Mapping[str, Any] | None) -> bool:
    if not payload:
        return False
    state = str(payload.get("state") or "").strip()
    return state in {"running", "pending"}


def _load_worker_assignment_ids(path: Path) -> dict[str, tuple[str, ...]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        return {}
    assignments: dict[str, tuple[str, ...]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        worker_id = str(row.get("worker_id") or "").strip()
        shard_ids = tuple(
            str(value).strip()
            for value in (row.get("shard_ids") or [])
            if str(value).strip()
        )
        if worker_id and shard_ids:
            assignments[worker_id] = shard_ids
    return assignments


def _load_assigned_shard_ids(path: Path) -> tuple[str, ...]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        return ()
    shard_ids: list[str] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        shard_id = str(row.get("shard_id") or row.get("task_id") or "").strip()
        if shard_id:
            shard_ids.append(shard_id)
    return tuple(shard_ids)


def _count_worker_outputs(knowledge_root: Path) -> tuple[int, int]:
    output_paths = sorted((knowledge_root / "workers").glob("*/out/*.json"))
    malformed_count = sum(1 for path in output_paths if _is_malformed_json_file(path))
    return len(output_paths), malformed_count


def _collect_worker_outcome_counts(knowledge_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for live_status_path in sorted((knowledge_root / "workers").glob("*/live_status.json")):
        category = _load_worker_outcome(live_status_path)
        counts[category.value] = counts.get(category.value, 0) + 1
    return counts


def _load_worker_outcome(path: Path) -> KnowledgeWorkerOutcomeCategory:
    payload = _load_json_dict(path) or {}
    return classify_worker_outcome(
        state=str(payload.get("state") or "").strip() or None,
        reason_code=str(payload.get("reason_code") or "").strip() or None,
    )


def _classify_artifact_states(root: Path | None, expected_artifacts: tuple[str, ...]) -> dict[str, str]:
    if root is None:
        return {}
    states: dict[str, str] = {}
    for artifact_key in expected_artifacts:
        if artifact_key.endswith("/*"):
            target = root / artifact_key[:-2]
            present = target.exists() and target.is_dir() and any(target.iterdir())
        else:
            target = root / artifact_key
            present = target.exists()
        states[artifact_key] = (
            KnowledgeArtifactState.PRESENT.value
            if present
            else KnowledgeArtifactState.MISSING.value
        )
    return states


def _classify_packet_state(
    *,
    artifacts: _PacketArtifacts,
) -> tuple[
    KnowledgePacketState,
    KnowledgePacketTerminalOutcome | None,
    KnowledgePacketAttemptType | None,
    str | None,
]:
    if artifacts.repair_stale:
        return (
            KnowledgePacketState.FOLLOW_UP_STALE,
            None,
            KnowledgePacketAttemptType.REPAIR,
            "repair follow-up exists without terminal repair_status.json",
        )
    if artifacts.repair_status == "repaired":
        return (
            KnowledgePacketState.REPAIR_RECOVERED,
            KnowledgePacketTerminalOutcome.REPAIR_RECOVERED,
            KnowledgePacketAttemptType.REPAIR,
            "repair_status.json recorded repaired",
        )
    if artifacts.repair_status is not None:
        return (
            KnowledgePacketState.REPAIR_FAILED,
            KnowledgePacketTerminalOutcome.REPAIR_FAILED,
            KnowledgePacketAttemptType.REPAIR,
            f"repair_status.json recorded {artifacts.repair_status}",
        )
    if artifacts.watchdog_retry_stale:
        return (
            KnowledgePacketState.FOLLOW_UP_STALE,
            None,
            KnowledgePacketAttemptType.WATCHDOG_RETRY,
            "watchdog retry exists without terminal status.json",
        )
    if artifacts.watchdog_retry_status == "validated":
        return (
            KnowledgePacketState.RETRY_RECOVERED,
            KnowledgePacketTerminalOutcome.RETRY_RECOVERED,
            KnowledgePacketAttemptType.WATCHDOG_RETRY,
            "watchdog_retry/status.json recorded validated",
        )
    if artifacts.watchdog_retry_status is not None:
        return (
            KnowledgePacketState.RETRY_FAILED,
            KnowledgePacketTerminalOutcome.RETRY_FAILED,
            KnowledgePacketAttemptType.WATCHDOG_RETRY,
            f"watchdog_retry/status.json recorded {artifacts.watchdog_retry_status}",
        )
    if artifacts.main_output_malformed:
        return (
            KnowledgePacketState.MAIN_OUTPUT_MALFORMED,
            None,
            KnowledgePacketAttemptType.MAIN_WORKER,
            "worker out/*.json was malformed JSON",
        )
    if artifacts.main_output_present:
        return (
            KnowledgePacketState.MAIN_OUTPUT_WRITTEN,
            None,
            KnowledgePacketAttemptType.MAIN_WORKER,
            "worker out/*.json existed and parsed as JSON",
        )
    if artifacts.worker_outcome in {
        KnowledgeWorkerOutcomeCategory.WATCHDOG_COMMAND_FORBIDDEN,
        KnowledgeWorkerOutcomeCategory.WATCHDOG_KILLED_OTHER,
    }:
        return (
            KnowledgePacketState.MISSING_OUTPUT,
            KnowledgePacketTerminalOutcome.MISSING_OUTPUT,
            KnowledgePacketAttemptType.MAIN_WORKER,
            "assigned worker terminated before writing packet output",
        )
    return (
        KnowledgePacketState.PENDING,
        None,
        None,
        None,
    )


def _is_malformed_json_file(path: Path) -> bool:
    payload = _load_json(path)
    return payload is None


def _load_json(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    return dict(payload) if isinstance(payload, Mapping) else None
