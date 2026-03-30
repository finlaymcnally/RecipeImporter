from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class KnowledgePacketAttemptType(_StrEnum):
    MAIN_WORKER = "main_worker"
    WATCHDOG_RETRY = "watchdog_retry"
    RETRY_SPLIT = "retry_split"
    REPAIR = "repair"


class KnowledgePacketState(_StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    MAIN_OUTPUT_WRITTEN = "main_output_written"
    MAIN_OUTPUT_MALFORMED = "main_output_malformed"
    FOLLOW_UP_STALE = "follow_up_stale"
    RETRY_RECOVERED = "retry_recovered"
    RETRY_FAILED = "retry_failed"
    REPAIR_RECOVERED = "repair_recovered"
    REPAIR_FAILED = "repair_failed"
    VALIDATED = "validated"
    WORKER_EXITED_WITH_PACKET_STILL_LEASED = "worker_exited_with_packet_still_leased"
    PACKET_RESULT_VALIDATION_BLOCKED = "packet_result_validation_blocked"
    REPAIR_PACKET_EXHAUSTED = "repair_packet_exhausted"
    QUEUE_COMPLETED_WITHOUT_PROMOTED_OUTPUT = "queue_completed_without_promoted_output"
    PROCESS_EXITED_WITHOUT_FINAL_PACKET_STATE = (
        "process_exited_without_final_packet_state"
    )
    WATCHDOG_KILLED = "watchdog_killed"
    INVALID_OUTPUT = "invalid_output"
    NO_FINAL_OUTPUT = "no_final_output"
    CANCELLED_DUE_TO_INTERRUPT = "cancelled_due_to_interrupt"


class KnowledgePacketTerminalOutcome(_StrEnum):
    RETRY_RECOVERED = "retry_recovered"
    RETRY_FAILED = "retry_failed"
    REPAIR_RECOVERED = "repair_recovered"
    REPAIR_FAILED = "repair_failed"
    VALIDATED = "validated"
    WORKER_EXITED_WITH_PACKET_STILL_LEASED = "worker_exited_with_packet_still_leased"
    PACKET_RESULT_VALIDATION_BLOCKED = "packet_result_validation_blocked"
    REPAIR_PACKET_EXHAUSTED = "repair_packet_exhausted"
    QUEUE_COMPLETED_WITHOUT_PROMOTED_OUTPUT = "queue_completed_without_promoted_output"
    PROCESS_EXITED_WITHOUT_FINAL_PACKET_STATE = (
        "process_exited_without_final_packet_state"
    )
    WATCHDOG_KILLED = "watchdog_killed"
    INVALID_OUTPUT = "invalid_output"
    NO_FINAL_OUTPUT = "no_final_output"
    CANCELLED_DUE_TO_INTERRUPT = "cancelled_due_to_interrupt"


class KnowledgeWorkerOutcomeCategory(_StrEnum):
    COMPLETED_OUTPUTS_STABILIZED = "completed_outputs_stabilized"
    COMPLETED_PROCESS_EXIT = "completed_process_exit"
    WATCHDOG_COMMAND_FORBIDDEN = "watchdog_command_forbidden"
    WATCHDOG_KILLED_OTHER = "watchdog_killed_other"
    RUNNING = "running"
    UNKNOWN = "unknown"


class KnowledgeFollowUpKind(_StrEnum):
    WATCHDOG_RETRY = "watchdog_retry"
    REPAIR = "repair"


class KnowledgeArtifactState(_StrEnum):
    PRESENT = "present"
    MISSING = "missing"


KNOWLEDGE_PACKET_EXPLICIT_NO_FINAL_OUTPUT_REASON_CODES: tuple[str, ...] = (
    KnowledgePacketTerminalOutcome.WORKER_EXITED_WITH_PACKET_STILL_LEASED.value,
    KnowledgePacketTerminalOutcome.PACKET_RESULT_VALIDATION_BLOCKED.value,
    KnowledgePacketTerminalOutcome.REPAIR_PACKET_EXHAUSTED.value,
    KnowledgePacketTerminalOutcome.QUEUE_COMPLETED_WITHOUT_PROMOTED_OUTPUT.value,
    KnowledgePacketTerminalOutcome.PROCESS_EXITED_WITHOUT_FINAL_PACKET_STATE.value,
)


def knowledge_reason_is_explicit_no_final_output(reason_code: object) -> bool:
    return str(reason_code or "").strip() in (
        KNOWLEDGE_PACKET_EXPLICIT_NO_FINAL_OUTPUT_REASON_CODES
    )


@dataclass(frozen=True, slots=True)
class KnowledgePacketRecord:
    packet_id: str
    parent_shard_id: str
    owned_ids: tuple[str, ...] = ()
    worker_id: str | None = None
    state: KnowledgePacketState = KnowledgePacketState.PENDING
    terminal_outcome: KnowledgePacketTerminalOutcome | None = None
    latest_attempt_type: KnowledgePacketAttemptType | None = None
    latest_reason: str | None = None
    main_output_present: bool = False
    main_output_malformed: bool = False
    watchdog_retry_status: str | None = None
    watchdog_retry_stale: bool = False
    repair_status: str | None = None
    repair_stale: bool = False


@dataclass(frozen=True, slots=True)
class KnowledgeStageRollup:
    packet_total: int
    packet_state_counts: dict[str, int]
    terminal_outcome_counts: dict[str, int]
    worker_outcome_counts: dict[str, int]
    follow_up_attempt_counts: dict[str, int]
    stale_follow_up_count: int
    worker_output_count: int
    malformed_worker_output_count: int
    stage_artifact_states: dict[str, str]
    benchmark_artifact_states: dict[str, str]

    @property
    def missing_stage_artifacts(self) -> tuple[str, ...]:
        return tuple(
            key
            for key, value in self.stage_artifact_states.items()
            if value == KnowledgeArtifactState.MISSING.value
        )

    @property
    def missing_benchmark_artifacts(self) -> tuple[str, ...]:
        return tuple(
            key
            for key, value in self.benchmark_artifact_states.items()
            if value == KnowledgeArtifactState.MISSING.value
        )


@dataclass(slots=True)
class KnowledgePacketLedger:
    packets_by_id: dict[str, KnowledgePacketRecord] = field(default_factory=dict)

    def add(self, record: KnowledgePacketRecord) -> None:
        packet_id = str(record.packet_id).strip()
        if not packet_id:
            raise ValueError("packet_id must be non-empty")
        self.packets_by_id[packet_id] = record

    def state_counts(self) -> dict[str, int]:
        counts = Counter(record.state.value for record in self.packets_by_id.values())
        return dict(sorted(counts.items()))

    def terminal_outcome_counts(self) -> dict[str, int]:
        counts = Counter(
            record.terminal_outcome.value
            for record in self.packets_by_id.values()
            if record.terminal_outcome is not None
        )
        return dict(sorted(counts.items()))

    def follow_up_attempt_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for record in self.packets_by_id.values():
            if record.watchdog_retry_status is not None or record.watchdog_retry_stale:
                counts[KnowledgeFollowUpKind.WATCHDOG_RETRY.value] += 1
            if record.repair_status is not None or record.repair_stale:
                counts[KnowledgeFollowUpKind.REPAIR.value] += 1
        return dict(sorted(counts.items()))

    def stale_follow_up_count(self) -> int:
        count = 0
        for record in self.packets_by_id.values():
            if record.watchdog_retry_stale:
                count += 1
            if record.repair_stale:
                count += 1
        return count

    def rollup(
        self,
        *,
        worker_outcome_counts: Mapping[str, int] | None = None,
        worker_output_count: int = 0,
        malformed_worker_output_count: int = 0,
        stage_artifact_states: Mapping[str, str] | None = None,
        benchmark_artifact_states: Mapping[str, str] | None = None,
    ) -> KnowledgeStageRollup:
        return KnowledgeStageRollup(
            packet_total=len(self.packets_by_id),
            packet_state_counts=self.state_counts(),
            terminal_outcome_counts=self.terminal_outcome_counts(),
            worker_outcome_counts=dict(sorted(dict(worker_outcome_counts or {}).items())),
            follow_up_attempt_counts=self.follow_up_attempt_counts(),
            stale_follow_up_count=self.stale_follow_up_count(),
            worker_output_count=max(0, int(worker_output_count)),
            malformed_worker_output_count=max(0, int(malformed_worker_output_count)),
            stage_artifact_states=dict(sorted(dict(stage_artifact_states or {}).items())),
            benchmark_artifact_states=dict(sorted(dict(benchmark_artifact_states or {}).items())),
        )
