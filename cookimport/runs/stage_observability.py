from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from cookimport.llm.knowledge_runtime_replay import replay_knowledge_runtime
from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.staging.writer import (
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME,
    NONRECIPE_REVIEW_STATUS_FILE_NAME,
    NONRECIPE_SEED_ROUTING_FILE_NAME,
)


STAGE_OBSERVABILITY_SCHEMA_VERSION = "stage_observability.v1"
RECIPE_MANIFEST_FILE_NAME = "recipe_manifest.json"
KNOWLEDGE_MANIFEST_FILE_NAME = "knowledge_manifest.json"
KNOWLEDGE_STAGE_STATUS_FILE_NAME = "stage_status.json"
KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION = "knowledge_stage_status.v1"
KNOWLEDGE_STAGE_SUMMARY_FILE_NAME = "knowledge_stage_summary.json"
KNOWLEDGE_STAGE_SUMMARY_SCHEMA_VERSION = "knowledge_stage_summary.v1"
RECIPE_STAGE_SUMMARY_FILE_NAME = "recipe_stage_summary.json"
RECIPE_STAGE_SUMMARY_SCHEMA_VERSION = "recipe_stage_summary.v1"
LINE_ROLE_STAGE_SUMMARY_FILE_NAME = "line_role_stage_summary.json"
LINE_ROLE_STAGE_SUMMARY_SCHEMA_VERSION = "line_role_stage_summary.v1"

_KNOWLEDGE_STAGE_ARTIFACT_KEYS: tuple[str, ...] = (
    "phase_manifest.json",
    "shard_manifest.jsonl",
    "task_manifest.jsonl",
    "task_status.jsonl",
    "worker_assignments.json",
    "promotion_report.json",
    "telemetry.json",
    "failures.json",
    "knowledge_manifest.json",
    "proposals/*",
)
_KNOWLEDGE_PACKET_TERMINAL_STATES = frozenset(
    {
        "validated",
        "retry_recovered",
        "retry_failed",
        "repair_recovered",
        "repair_failed",
        "missing_output",
        "watchdog_killed",
        "invalid_output",
        "cancelled_due_to_interrupt",
    }
)
_KNOWLEDGE_FOLLOWUP_STATUS_FIELDS: tuple[tuple[str, str], ...] = (
    ("watchdog_retry", "watchdog_retry_status"),
    ("retry_split", "retry_status"),
    ("repair", "repair_status"),
)
_KNOWLEDGE_FOLLOWUP_ACCEPTED_STATUSES: dict[str, frozenset[str]] = {
    "watchdog_retry": frozenset({"recovered", "failed"}),
    "retry_split": frozenset({"recovered", "failed"}),
    "repair": frozenset({"repaired", "failed"}),
}
_KNOWLEDGE_FOLLOWUP_RECOVERED_STATUSES: dict[str, frozenset[str]] = {
    "watchdog_retry": frozenset({"recovered"}),
    "retry_split": frozenset({"recovered"}),
    "repair": frozenset({"repaired"}),
}
_KNOWLEDGE_FOLLOWUP_FAILED_STATUSES: dict[str, frozenset[str]] = {
    "watchdog_retry": frozenset({"failed"}),
    "retry_split": frozenset({"failed"}),
    "repair": frozenset({"failed"}),
}


class StageWorkbookObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workbook_slug: str
    pipeline_id: str | None = None
    manifest_path: str | None = None
    stage_dir: str | None = None
    input_dir: str | None = None
    output_dir: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class ObservedStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str
    stage_label: str
    stage_artifact_stem: str
    stage_family: str
    stage_order: int
    workbooks: list[StageWorkbookObservation] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class StageObservabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = STAGE_OBSERVABILITY_SCHEMA_VERSION
    run_kind: str
    run_id: str
    created_at: str
    stages: list[ObservedStage] = Field(default_factory=list)


_STAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "label_det": {
        "label": "Deterministic Labels",
        "artifact_stem": "label_det",
        "family": "label_stage",
        "order": 5,
    },
    "label_llm_correct": {
        "label": "Label LLM Correction",
        "artifact_stem": "label_llm_correct",
        "family": "label_stage",
        "order": 6,
    },
    "group_recipe_spans": {
        "label": "Group Recipe Spans",
        "artifact_stem": "group_recipe_spans",
        "family": "label_stage",
        "order": 7,
    },
    "classify_nonrecipe": {
        "label": "Classify Non-Recipe",
        "artifact_stem": "classify_nonrecipe",
        "family": "deterministic",
        "order": 8,
    },
    "build_intermediate_det": {
        "label": "Build Intermediate Recipe",
        "artifact_stem": "build_intermediate_det",
        "family": "recipe_deterministic",
        "order": 10,
    },
    "recipe_llm_correct_and_link": {
        "label": "Recipe LLM Correction",
        "artifact_stem": "recipe_correction",
        "family": "recipe_llm",
        "order": 20,
    },
    "build_final_recipe": {
        "label": "Build Final Recipe",
        "artifact_stem": "build_final_recipe",
        "family": "recipe_deterministic",
        "order": 30,
    },
    "nonrecipe_knowledge_review": {
        "label": "Non-Recipe Knowledge Review",
        "artifact_stem": "knowledge",
        "family": "knowledge_llm",
        "order": 40,
    },
    "line_role": {
        "label": "Canonical Line Role",
        "artifact_stem": "line_role",
        "family": "line_role_llm",
        "order": 35,
    },
    "write_outputs": {
        "label": "Write Outputs",
        "artifact_stem": "write_outputs",
        "family": "deterministic",
        "order": 90,
    },
}


def stage_label(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("label") or stage_key.replace("_", " ").title())


def stage_artifact_stem(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("artifact_stem") or stage_key)


def stage_order(stage_key: str) -> int:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    try:
        return int(definition.get("order") or 999)
    except (TypeError, ValueError):
        return 999


def stage_family(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("family") or "stage")


def recipe_stage_keys_for_pipeline(pipeline_id: str | None) -> tuple[str, ...]:
    normalized = str(pipeline_id or "").strip()
    if normalized == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1:
        return (
            "build_intermediate_det",
            "recipe_llm_correct_and_link",
            "build_final_recipe",
        )
    return ()


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_json_value(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return rows
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
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


def _relative_to(run_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)


def _path_from_manifest(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return Path(cleaned)


def _has_json_payloads(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(child.is_file() for child in path.iterdir())


def _knowledge_stage_artifact_paths(stage_root: Path) -> dict[str, Path]:
    workbook_root = stage_root.parent
    return {
        "phase_manifest.json": stage_root / "phase_manifest.json",
        "shard_manifest.jsonl": stage_root / "shard_manifest.jsonl",
        "task_manifest.jsonl": stage_root / "task_manifest.jsonl",
        "task_status.jsonl": stage_root / "task_status.jsonl",
        "worker_assignments.json": stage_root / "worker_assignments.json",
        "promotion_report.json": stage_root / "promotion_report.json",
        "telemetry.json": stage_root / "telemetry.json",
        "failures.json": stage_root / "failures.json",
        "knowledge_manifest.json": workbook_root / KNOWLEDGE_MANIFEST_FILE_NAME,
        "proposals/*": stage_root / "proposals",
    }


def _knowledge_stage_artifact_present(path: Path, artifact_key: str) -> bool:
    if artifact_key == "proposals/*":
        return _has_json_payloads(path)
    return path.exists() and path.is_file()


def classify_knowledge_stage_artifacts(
    stage_root: Path,
    *,
    declared_states: Mapping[str, Any] | None = None,
    finalization_completeness: str | None = None,
) -> dict[str, str]:
    declared = {
        str(key): str(value).strip()
        for key, value in dict(declared_states or {}).items()
        if str(key).strip()
    }
    finalization = str(finalization_completeness or "").strip().lower()
    interrupted_before_finalization = finalization == "interrupted_before_finalization"
    states: dict[str, str] = {}
    for artifact_key, path in _knowledge_stage_artifact_paths(stage_root).items():
        if _knowledge_stage_artifact_present(path, artifact_key):
            states[artifact_key] = "present"
            continue
        declared_state = declared.get(artifact_key)
        if declared_state == "skipped_due_to_interrupt" or interrupted_before_finalization:
            states[artifact_key] = "skipped_due_to_interrupt"
            continue
        states[artifact_key] = "unexpectedly_missing"
    return states


def _count_nested_positive_values(payload: Any) -> int:
    if isinstance(payload, Mapping):
        return sum(_count_nested_positive_values(value) for value in payload.values())
    if isinstance(payload, list):
        return sum(_count_nested_positive_values(value) for value in payload)
    try:
        return max(0, int(payload))
    except (TypeError, ValueError):
        return 0


def _count_value_rows(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value:
            counts[value] += 1
    return dict(sorted(counts.items()))


def _count_metadata_value_rows(
    rows: list[dict[str, Any]],
    metadata_key: str,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        value = str(metadata.get(metadata_key) or "").strip()
        if value:
            counts[value] += 1
    return dict(sorted(counts.items()))


def _count_followup_statuses(
    task_rows: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    attempt_counts: Counter[str] = Counter()
    accepted_counts: Counter[str] = Counter()
    recovered_counts: Counter[str] = Counter()
    failed_counts: Counter[str] = Counter()
    for row in task_rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        for followup_kind, metadata_key in _KNOWLEDGE_FOLLOWUP_STATUS_FIELDS:
            status = str(metadata.get(metadata_key) or "").strip()
            if not status or status == "not_attempted":
                continue
            attempt_counts[followup_kind] += 1
            if status in _KNOWLEDGE_FOLLOWUP_ACCEPTED_STATUSES[followup_kind]:
                accepted_counts[followup_kind] += 1
            if status in _KNOWLEDGE_FOLLOWUP_RECOVERED_STATUSES[followup_kind]:
                recovered_counts[followup_kind] += 1
            if status in _KNOWLEDGE_FOLLOWUP_FAILED_STATUSES[followup_kind]:
                failed_counts[followup_kind] += 1
    return (
        dict(sorted(attempt_counts.items())),
        dict(sorted(accepted_counts.items())),
        dict(sorted(recovered_counts.items())),
        dict(sorted(failed_counts.items())),
    )


def _collect_followup_skip_reason_counts(task_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in task_rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        for key in (
            "watchdog_retry_skip_reason_code",
            "retry_skip_reason_code",
            "repair_skip_reason_code",
        ):
            value = str(metadata.get(key) or "").strip()
            if value:
                counts[value] += 1
    return dict(sorted(counts.items()))


def _collect_followup_runtime_counts(
    stage_root: Path,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    status_counts: Counter[str] = Counter()
    stale_counts: Counter[str] = Counter()
    cancelled_counts: Counter[str] = Counter()
    cancelled_reason_counts: Counter[str] = Counter()
    followup_specs = (
        (
            "watchdog_retry",
            ("workers/*/shards/*/watchdog_retry/status.json",),
            ("workers/*/shards/*/watchdog_retry/live_status.json",),
        ),
        (
            "repair",
            ("workers/*/shards/*/repair_status.json",),
            ("workers/*/shards/*/repair_live_status.json",),
        ),
    )
    for followup_kind, status_patterns, live_patterns in followup_specs:
        for pattern in status_patterns:
            for status_path in sorted(stage_root.glob(pattern)):
                payload = _load_json_dict(status_path) or {}
                status = str(payload.get("status") or payload.get("state") or "").strip()
                if status:
                    status_counts[followup_kind] += 1
                reason_code = str(payload.get("reason_code") or "").strip()
                if status.startswith(("cancelled", "superseded")) or reason_code.startswith(
                    ("cancelled", "superseded")
                ):
                    cancelled_counts[followup_kind] += 1
                    if reason_code:
                        cancelled_reason_counts[reason_code] += 1
        for pattern in live_patterns:
            for live_path in sorted(stage_root.glob(pattern)):
                payload = _load_json_dict(live_path) or {}
                state = str(payload.get("state") or "").strip()
                if state in {"running", "pending"}:
                    stale_counts[followup_kind] += 1
    return (
        dict(sorted(status_counts.items())),
        dict(sorted(stale_counts.items())),
        dict(sorted(cancelled_counts.items())),
        dict(sorted(cancelled_reason_counts.items())),
    )


def _collect_worker_status_counts(
    stage_root: Path,
) -> tuple[dict[str, int], dict[str, int]]:
    state_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for live_status_path in sorted(stage_root.glob("workers/*/live_status.json")):
        payload = _load_json_dict(live_status_path) or {}
        state = str(payload.get("state") or "").strip()
        if state:
            state_counts[state] += 1
        reason_code = str(payload.get("reason_code") or "").strip()
        if reason_code:
            reason_counts[reason_code] += 1
    return dict(sorted(state_counts.items())), dict(sorted(reason_counts.items()))


def _collect_salvage_counts(stage_root: Path) -> dict[str, Any]:
    success_count = 0
    failure_count = 0
    kind_counts: Counter[str] = Counter()
    proposal_paths = sorted(stage_root.glob("workers/*/shards/*/proposal.json"))
    for proposal_path in proposal_paths:
        payload = _load_json_dict(proposal_path) or {}
        status = str(payload.get("status") or "").strip()
        validation_metadata = payload.get("validation_metadata")
        if not isinstance(validation_metadata, Mapping):
            continue
        salvage_kinds: list[str] = []
        if bool(validation_metadata.get("response_trailing_eof_trimmed")):
            salvage_kinds.append("trailing_eof_trimmed")
        if bool(validation_metadata.get("response_shell_wrapper_noise_trimmed")):
            salvage_kinds.append("shell_wrapper_noise_trimmed")
        if not salvage_kinds:
            continue
        for salvage_kind in salvage_kinds:
            kind_counts[salvage_kind] += 1
        if status == "validated":
            success_count += 1
        else:
            failure_count += 1
    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "kind_counts": dict(sorted(kind_counts.items())),
    }


def build_knowledge_stage_summary(stage_root: Path) -> dict[str, Any]:
    status_path = stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME
    status_payload = _load_json_dict(status_path) or {}
    pre_kill_failure_counts = status_payload.get("pre_kill_failure_counts")
    if not isinstance(pre_kill_failure_counts, Mapping):
        pre_kill_failure_counts = {}
    finalization_completeness = (
        str(status_payload.get("finalization_completeness") or "").strip() or None
    )
    artifact_states = classify_knowledge_stage_artifacts(
        stage_root,
        declared_states=(
            status_payload.get("artifact_states")
            if isinstance(status_payload.get("artifact_states"), Mapping)
            else None
        ),
        finalization_completeness=finalization_completeness,
    )
    task_rows = _load_jsonl_dicts(stage_root / "task_status.jsonl")
    packet_state_counts = _count_value_rows(task_rows, "state")
    packet_attempt_type_counts = _count_value_rows(task_rows, "last_attempt_type")
    terminal_reason_code_counts = _count_value_rows(task_rows, "terminal_reason_code")
    deterministic_bypass_reason_code_counts: Counter[str] = Counter()
    for row in task_rows:
        if str(row.get("last_attempt_type") or "").strip() != "deterministic_bypass":
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        reason_code = str(metadata.get("deterministic_bypass_reason_code") or "").strip()
        if reason_code:
            deterministic_bypass_reason_code_counts[reason_code] += 1
    terminal_outcome_counts = {
        state: count
        for state, count in packet_state_counts.items()
        if state in _KNOWLEDGE_PACKET_TERMINAL_STATES
    }
    followup_attempt_counts, followup_accepted_counts, followup_recovered_counts, followup_failed_counts = (
        _count_followup_statuses(task_rows)
    )
    followup_skip_reason_counts = _collect_followup_skip_reason_counts(task_rows)
    followup_status_counts, stale_followup_counts, cancelled_followup_counts, cancelled_reason_counts = (
        _collect_followup_runtime_counts(stage_root)
    )
    circuit_breaker_reason_counts = {
        reason_code: count
        for reason_code, count in followup_skip_reason_counts.items()
        if "circuit_breaker" in reason_code
    }
    worker_state_counts, worker_reason_code_counts = _collect_worker_status_counts(stage_root)
    salvage_counts = _collect_salvage_counts(stage_root)
    replay_summary = replay_knowledge_runtime(knowledge_root=stage_root)
    packet_total = len(task_rows) if task_rows else int(replay_summary.rollup.packet_total)
    deterministic_bypass_total = int(packet_attempt_type_counts.get("deterministic_bypass") or 0)
    return {
        "authoritative": bool(status_payload),
        "schema_version": KNOWLEDGE_STAGE_SUMMARY_SCHEMA_VERSION,
        "status_schema_version": (
            str(status_payload.get("schema_version") or "").strip()
            or KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION
        ),
        "stage_key": (
            str(status_payload.get("stage_key") or "").strip()
            or "nonrecipe_knowledge_review"
        ),
        "stage_state": str(status_payload.get("stage_state") or "").strip() or None,
        "termination_cause": str(status_payload.get("termination_cause") or "").strip() or None,
        "finalization_completeness": finalization_completeness,
        "artifact_states": {
            key: artifact_states[key]
            for key in _KNOWLEDGE_STAGE_ARTIFACT_KEYS
            if key in artifact_states
        },
        "packets": {
            "packet_total": packet_total,
            "parent_shard_total": int(replay_summary.shard_total),
            "state_counts": packet_state_counts,
            "terminal_outcome_counts": dict(sorted(terminal_outcome_counts.items())),
            "attempt_type_counts": packet_attempt_type_counts,
            "terminal_reason_code_counts": terminal_reason_code_counts,
            "deterministic_bypass_total": deterministic_bypass_total,
            "llm_review_total": max(packet_total - deterministic_bypass_total, 0),
            "deterministic_bypass_reason_code_counts": dict(
                sorted(deterministic_bypass_reason_code_counts.items())
            ),
            "topline": {
                "validated": int(packet_state_counts.get("validated") or 0),
                "retry_recovered": int(packet_state_counts.get("retry_recovered") or 0),
                "repair_recovered": int(packet_state_counts.get("repair_recovered") or 0),
                "deterministic_bypass": deterministic_bypass_total,
                "failed": sum(
                    int(packet_state_counts.get(key) or 0)
                    for key in (
                        "invalid_output",
                        "retry_failed",
                        "repair_failed",
                        "missing_output",
                        "watchdog_killed",
                    )
                ),
                "cancelled_due_to_interrupt": int(
                    packet_state_counts.get("cancelled_due_to_interrupt") or 0
                ),
            },
        },
        "workers": {
            "state_counts": worker_state_counts,
            "reason_code_counts": worker_reason_code_counts,
            "outcome_counts": dict(sorted(replay_summary.rollup.worker_outcome_counts.items())),
            "output_count": int(replay_summary.rollup.worker_output_count),
            "malformed_output_count": int(replay_summary.rollup.malformed_worker_output_count),
        },
        "followups": {
            "attempt_counts": followup_attempt_counts,
            "accepted_counts": followup_accepted_counts,
            "recovered_counts": followup_recovered_counts,
            "failed_counts": followup_failed_counts,
            "status_file_counts": followup_status_counts,
            "skip_reason_counts": followup_skip_reason_counts,
            "stale_count": sum(int(value) for value in stale_followup_counts.values()),
            "stale_counts": stale_followup_counts,
            "cancelled_count": sum(int(value) for value in cancelled_followup_counts.values()),
            "cancelled_counts": cancelled_followup_counts,
            "cancelled_reason_counts": cancelled_reason_counts,
            "circuit_breaker_activation_count": sum(
                int(value) for value in circuit_breaker_reason_counts.values()
            ),
            "circuit_breaker_reason_counts": circuit_breaker_reason_counts,
        },
        "salvage": salvage_counts,
        "pre_kill_failure_counts": dict(pre_kill_failure_counts),
        "pre_kill_failures_observed": _count_nested_positive_values(pre_kill_failure_counts) > 0,
    }


def summarize_knowledge_stage_artifacts(stage_root: Path) -> dict[str, Any]:
    return build_knowledge_stage_summary(stage_root)


def write_knowledge_stage_summary(
    *,
    stage_root: Path,
    summary: Mapping[str, Any] | None = None,
) -> Path:
    target_path = stage_root / KNOWLEDGE_STAGE_SUMMARY_FILE_NAME
    payload = dict(summary or build_knowledge_stage_summary(stage_root))
    target_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target_path


def _count_jsonl_rows(path: Path) -> int:
    return len(_load_jsonl_dicts(path))


def _count_status_values(paths: list[Path]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        payload = _load_json_dict(path) or {}
        status = str(payload.get("status") or "").strip()
        if status:
            counts[status] += 1
    return dict(sorted(counts.items()))


def _repair_rollup(stage_root: Path) -> tuple[int, int, int]:
    attempted_paths = sorted(stage_root.glob("workers/*/shards/*/repair_prompt.txt"))
    completed_paths = sorted(stage_root.glob("workers/*/shards/*/repair_status.json"))
    running_count = 0
    for prompt_path in attempted_paths:
        status_path = prompt_path.parent / "repair_status.json"
        if status_path.exists():
            continue
        running_count += 1
    return len(attempted_paths), len(completed_paths), running_count


def _stage_summary_state(
    *,
    planned_total: int,
    completed_total: int,
    failed_total: int,
) -> str:
    if planned_total > 0 and completed_total >= planned_total:
        if failed_total >= planned_total:
            return "failed"
        if failed_total > 0:
            return "partial_failure"
        return "completed"
    if completed_total > 0 or failed_total > 0:
        return "partial"
    return "not_started"


def build_recipe_stage_summary(stage_root: Path) -> dict[str, Any]:
    phase_manifest = _load_json_dict(stage_root / "phase_manifest.json") or {}
    worker_state_counts, worker_reason_code_counts = _collect_worker_status_counts(stage_root)
    shard_status_paths = sorted(stage_root.glob("workers/*/shards/*/status.json"))
    shard_status_counts = _count_status_values(shard_status_paths)
    failed_shard_total = sum(
        count
        for status, count in shard_status_counts.items()
        if status not in {"validated"}
    )
    repair_attempted, repair_completed, repair_running = _repair_rollup(stage_root)
    proposal_count = len(list(stage_root.glob("proposals/*.json")))
    planned_task_total = _count_jsonl_rows(stage_root / "task_manifest.jsonl")
    completed_task_total = len(list(stage_root.glob("workers/*/out/*.json")))
    planned_shard_total = max(
        0,
        int(phase_manifest.get("shard_count") or 0),
        len(shard_status_paths),
    )
    completed_shard_total = len(shard_status_paths)
    important_artifacts = {
        "phase_manifest_json": "phase_manifest.json",
        "task_manifest_jsonl": "task_manifest.jsonl",
        "worker_assignments_json": "worker_assignments.json",
        "promotion_report_json": "promotion_report.json",
        "failures_json": "failures.json",
        "proposals_dir": "proposals",
    }
    return {
        "schema_version": RECIPE_STAGE_SUMMARY_SCHEMA_VERSION,
        "stage_key": "recipe_llm_correct_and_link",
        "stage_state": _stage_summary_state(
            planned_total=planned_shard_total,
            completed_total=completed_shard_total,
            failed_total=failed_shard_total,
        ),
        "work_units": {
            "label": "recipe_task",
            "planned_total": planned_task_total,
            "completed_total": completed_task_total,
        },
        "parent_shards": {
            "planned_total": planned_shard_total,
            "completed_total": completed_shard_total,
            "status_counts": shard_status_counts,
        },
        "workers": {
            "configured_total": int(phase_manifest.get("worker_count") or 0),
            "state_counts": worker_state_counts,
            "reason_code_counts": worker_reason_code_counts,
        },
        "followups": {
            "label": "shard_finalization",
            "repair_attempted_count": repair_attempted,
            "repair_completed_count": repair_completed,
            "repair_running_count": repair_running,
            "proposal_count": proposal_count,
        },
        "important_artifacts": important_artifacts,
    }


def write_recipe_stage_summary(
    *,
    stage_root: Path,
    summary: Mapping[str, Any] | None = None,
) -> Path:
    target_path = stage_root / RECIPE_STAGE_SUMMARY_FILE_NAME
    payload = dict(summary or build_recipe_stage_summary(stage_root))
    target_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target_path


def build_line_role_stage_summary(stage_root: Path) -> dict[str, Any]:
    phase_manifest = _load_json_dict(stage_root / "phase_manifest.json") or {}
    task_rows = _load_jsonl_dicts(stage_root / "task_status.jsonl")
    line_rows = _load_jsonl_dicts(stage_root / "canonical_line_table.jsonl")
    worker_state_counts, worker_reason_code_counts = _collect_worker_status_counts(stage_root)
    shard_status_paths = sorted(stage_root.glob("workers/*/shards/*/status.json"))
    shard_status_counts = _count_status_values(shard_status_paths)
    failed_shard_total = sum(
        count
        for status, count in shard_status_counts.items()
        if status not in {"validated"}
    )
    repair_attempted, repair_completed, repair_running = _repair_rollup(stage_root)
    proposal_count = len(list(stage_root.glob("proposals/*.json")))
    planned_task_total = _count_jsonl_rows(stage_root / "task_manifest.jsonl")
    completed_task_total = len(list(stage_root.glob("workers/*/out/*.json")))
    planned_shard_total = max(
        0,
        int(phase_manifest.get("shard_count") or 0),
        len(shard_status_paths),
    )
    completed_shard_total = len(shard_status_paths)
    important_artifacts = {
        "phase_manifest_json": "phase_manifest.json",
        "canonical_line_table_jsonl": "canonical_line_table.jsonl",
        "task_manifest_jsonl": "task_manifest.jsonl",
        "task_status_jsonl": "task_status.jsonl",
        "worker_assignments_json": "worker_assignments.json",
        "promotion_report_json": "promotion_report.json",
        "telemetry_json": "telemetry.json",
        "failures_json": "failures.json",
        "proposals_dir": "proposals",
    }
    packet_state_counts = _count_value_rows(task_rows, "state")
    packet_terminal_outcome_counts = _count_value_rows(task_rows, "terminal_outcome")
    packet_attempt_type_counts = _count_value_rows(task_rows, "last_attempt_type")
    llm_authoritative_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("llm_authoritative_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    fallback_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("fallback_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    suspicious_packet_count = sum(
        1
        for row in task_rows
        if bool(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_packet"))
    )
    suspicious_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    return {
        "schema_version": LINE_ROLE_STAGE_SUMMARY_SCHEMA_VERSION,
        "stage_key": "line_role",
        "stage_state": _stage_summary_state(
            planned_total=planned_shard_total,
            completed_total=completed_shard_total,
            failed_total=failed_shard_total,
        ),
        "lines": {
            "canonical_line_total": len(line_rows),
            "llm_authoritative_row_count": llm_authoritative_row_count,
            "fallback_row_count": fallback_row_count,
            "suspicious_row_count": suspicious_row_count,
        },
        "packets": {
            "packet_total": max(planned_task_total, len(task_rows), completed_task_total),
            "planned_total": planned_task_total,
            "completed_output_total": completed_task_total,
            "state_counts": packet_state_counts,
            "terminal_outcome_counts": packet_terminal_outcome_counts,
            "attempt_type_counts": packet_attempt_type_counts,
            "suspicious_packet_count": suspicious_packet_count,
        },
        "parent_shards": {
            "planned_total": planned_shard_total,
            "completed_total": completed_shard_total,
            "status_counts": shard_status_counts,
        },
        "workers": {
            "configured_total": int(phase_manifest.get("worker_count") or 0),
            "state_counts": worker_state_counts,
            "reason_code_counts": worker_reason_code_counts,
        },
        "followups": {
            "label": "shard_finalization",
            "repair_attempted_count": repair_attempted,
            "repair_completed_count": repair_completed,
            "repair_running_count": repair_running,
            "proposal_count": proposal_count,
        },
        "important_artifacts": important_artifacts,
    }


def write_line_role_stage_summary(
    *,
    stage_root: Path,
    summary: Mapping[str, Any] | None = None,
) -> Path:
    target_path = stage_root / LINE_ROLE_STAGE_SUMMARY_FILE_NAME
    payload = dict(summary or build_line_role_stage_summary(stage_root))
    target_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target_path


def _recipe_stage_key_map(
    *,
    recipe_manifest_payload: Mapping[str, Any],
    workbook_dir: Path,
) -> tuple[str, ...]:
    pipeline_id = str(recipe_manifest_payload.get("pipeline") or "").strip() or None
    candidate_keys = list(recipe_stage_keys_for_pipeline(pipeline_id))
    if pipeline_id == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1:
        return tuple(candidate_keys)
    if "final" in candidate_keys and not (workbook_dir / "final").exists():
        candidate_keys = [key for key in candidate_keys if key != "final"]
    return tuple(candidate_keys)


def build_stage_observability_report(
    *,
    run_root: Path,
    run_kind: str,
    created_at: str,
    run_config: Mapping[str, Any] | None = None,
) -> StageObservabilityReport:
    stage_rows: dict[str, ObservedStage] = {}

    raw_llm_root = run_root / "raw" / "llm"
    if raw_llm_root.exists() and raw_llm_root.is_dir():
        for workbook_dir in sorted(path for path in raw_llm_root.iterdir() if path.is_dir()):
            workbook_slug = workbook_dir.name
            recipe_manifest_path = workbook_dir / RECIPE_MANIFEST_FILE_NAME
            recipe_manifest_payload = _load_json_dict(recipe_manifest_path) or {}
            recipe_pipeline_id = str(recipe_manifest_payload.get("pipeline") or "").strip() or None
            recipe_paths = recipe_manifest_payload.get("paths")
            if not isinstance(recipe_paths, Mapping):
                recipe_paths = {}
            for key in _recipe_stage_key_map(
                recipe_manifest_payload=recipe_manifest_payload,
                workbook_dir=workbook_dir,
            ):
                if key == "recipe_llm_correct_and_link":
                    stage_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_runtime_dir")
                    ) or (workbook_dir / "recipe_phase_runtime")
                    input_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_input_dir")
                    ) or (stage_dir / "inputs")
                    output_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_proposals_dir")
                    ) or (stage_dir / "proposals")
                else:
                    stage_dir = workbook_dir / stage_artifact_stem(key)
                    input_dir = stage_dir / "in"
                    output_dir = stage_dir / "out"
                if (
                    key == "recipe_llm_correct_and_link"
                    and not stage_dir.exists()
                    and not input_dir.exists()
                    and not output_dir.exists()
                ):
                    continue
                if key not in {
                    "build_intermediate_det",
                    "build_final_recipe",
                } and not stage_dir.exists() and not input_dir.exists() and not output_dir.exists():
                    continue
                stage_rows.setdefault(
                    key,
                    ObservedStage(
                        stage_key=key,
                        stage_label=stage_label(key),
                        stage_artifact_stem=stage_artifact_stem(key),
                        stage_family=stage_family(key),
                        stage_order=stage_order(key),
                    ),
                )
                workbook_observation = StageWorkbookObservation(
                    workbook_slug=workbook_slug,
                    pipeline_id=recipe_pipeline_id,
                    manifest_path=_relative_to(run_root, recipe_manifest_path)
                    if recipe_manifest_path.exists()
                    else None,
                    stage_dir=_relative_to(run_root, stage_dir) if stage_dir.exists() else None,
                    input_dir=_relative_to(run_root, input_dir) if input_dir.exists() else None,
                    output_dir=_relative_to(run_root, output_dir) if output_dir.exists() else None,
                )
                stage_rows[key].workbooks.append(workbook_observation)

            knowledge_manifest_path = workbook_dir / KNOWLEDGE_MANIFEST_FILE_NAME
            knowledge_manifest_payload = _load_json_dict(knowledge_manifest_path) or {}
            knowledge_paths = knowledge_manifest_payload.get("paths")
            if not isinstance(knowledge_paths, Mapping):
                knowledge_paths = {}
            knowledge_dir = workbook_dir / stage_artifact_stem("nonrecipe_knowledge_review")
            knowledge_input_dir = _path_from_manifest(
                knowledge_paths.get("knowledge_in_dir")
            ) or (knowledge_dir / "in")
            knowledge_output_dir = _path_from_manifest(
                knowledge_paths.get("proposals_dir")
            ) or (knowledge_dir / "proposals")
            if knowledge_manifest_path.exists() or knowledge_dir.exists():
                key = "nonrecipe_knowledge_review"
                stage_rows.setdefault(
                    key,
                    ObservedStage(
                        stage_key=key,
                        stage_label=stage_label(key),
                        stage_artifact_stem=stage_artifact_stem(key),
                        stage_family=stage_family(key),
                        stage_order=stage_order(key),
                    ),
                )
                stage_rows[key].workbooks.append(
                    StageWorkbookObservation(
                        workbook_slug=workbook_slug,
                        pipeline_id=str(knowledge_manifest_payload.get("pipeline_id") or "").strip()
                        or None,
                        manifest_path=_relative_to(run_root, knowledge_manifest_path)
                        if knowledge_manifest_path.exists()
                        else None,
                        stage_dir=_relative_to(run_root, knowledge_dir) if knowledge_dir.exists() else None,
                        input_dir=_relative_to(run_root, knowledge_input_dir)
                        if knowledge_input_dir.exists()
                        else None,
                        output_dir=_relative_to(run_root, knowledge_output_dir)
                        if knowledge_output_dir.exists()
                        else None,
                        artifact_paths={
                            "stage_status_json": _relative_to(
                                run_root,
                                knowledge_dir / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
                            )
                            or ""
                        }
                        if (knowledge_dir / KNOWLEDGE_STAGE_STATUS_FILE_NAME).exists()
                        else {},
                    )
                )


    write_outputs_paths: dict[str, str] = {}
    for stage_key in ("label_det", "label_llm_correct", "group_recipe_spans"):
        stage_dir = run_root / stage_artifact_stem(stage_key)
        if not stage_dir.exists() or not stage_dir.is_dir():
            continue
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
            ),
        )
        for workbook_dir in sorted(path for path in stage_dir.iterdir() if path.is_dir()):
            artifact_paths = {
                path.name: _relative_to(run_root, path)
                for path in sorted(workbook_dir.iterdir())
                if path.is_file()
            }
            stage_rows[stage_key].workbooks.append(
                StageWorkbookObservation(
                    workbook_slug=workbook_dir.name,
                    stage_dir=_relative_to(run_root, workbook_dir),
                    artifact_paths={
                        key: value
                        for key, value in artifact_paths.items()
                        if value is not None
                    },
                )
            )
    nonrecipe_seed_routing_path = run_root / NONRECIPE_SEED_ROUTING_FILE_NAME
    nonrecipe_review_exclusions_path = run_root / NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME
    if nonrecipe_seed_routing_path.exists() or nonrecipe_review_exclusions_path.exists():
        stage_key = "classify_nonrecipe"
        artifact_paths = {}
        if nonrecipe_seed_routing_path.exists():
            artifact_paths["nonrecipe_seed_routing_json"] = (
                _relative_to(run_root, nonrecipe_seed_routing_path) or ""
            )
        if nonrecipe_review_exclusions_path.exists():
            artifact_paths["nonrecipe_review_exclusions_jsonl"] = (
                _relative_to(run_root, nonrecipe_review_exclusions_path) or ""
            )
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
                artifact_paths=artifact_paths,
            ),
        )
    nonrecipe_authority_path = run_root / NONRECIPE_AUTHORITY_FILE_NAME
    nonrecipe_review_status_path = run_root / NONRECIPE_REVIEW_STATUS_FILE_NAME
    if nonrecipe_authority_path.exists() or nonrecipe_review_status_path.exists():
        stage_key = "nonrecipe_knowledge_review"
        artifact_paths = {}
        if nonrecipe_authority_path.exists():
            artifact_paths["nonrecipe_authority_json"] = (
                _relative_to(run_root, nonrecipe_authority_path) or ""
            )
        if nonrecipe_review_status_path.exists():
            artifact_paths["nonrecipe_review_status_json"] = (
                _relative_to(run_root, nonrecipe_review_status_path) or ""
            )
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
                artifact_paths=artifact_paths,
            ),
        )
    line_role_stage_dir = run_root / "line-role-pipeline" / "runtime" / "line_role"
    if line_role_stage_dir.exists() and line_role_stage_dir.is_dir():
        stage_key = "line_role"
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
            ),
        )
        stage_rows[stage_key].workbooks.append(
            StageWorkbookObservation(
                workbook_slug=run_root.name,
                stage_dir=_relative_to(run_root, line_role_stage_dir),
                output_dir=_relative_to(run_root, line_role_stage_dir / "proposals")
                if (line_role_stage_dir / "proposals").exists()
                else None,
                artifact_paths={
                    key: value
                    for key, value in {
                        "phase_manifest_json": _relative_to(
                            run_root, line_role_stage_dir / "phase_manifest.json"
                        ),
                        "canonical_line_table_jsonl": _relative_to(
                            run_root, line_role_stage_dir / "canonical_line_table.jsonl"
                        ),
                        "task_manifest_jsonl": _relative_to(
                            run_root, line_role_stage_dir / "task_manifest.jsonl"
                        ),
                        "task_status_jsonl": _relative_to(
                            run_root, line_role_stage_dir / "task_status.jsonl"
                        ),
                        "telemetry_json": _relative_to(
                            run_root, line_role_stage_dir / "telemetry.json"
                        ),
                    }.items()
                    if value
                },
            )
        )
    for artifact_key, path_name in (
        ("intermediate_drafts_dir", "intermediate drafts"),
        ("final_drafts_dir", "final drafts"),
        ("chunks_dir", "chunks"),
        ("knowledge_dir", "knowledge"),
        ("bench_dir", ".bench"),
        ("reports_glob", "*.excel_import_report.json"),
    ):
        if "*" in path_name:
            matches = sorted(run_root.glob(path_name))
            if matches:
                write_outputs_paths[artifact_key] = str(path_name)
            continue
        target = run_root / path_name
        if target.exists():
            write_outputs_paths[artifact_key] = path_name
    if write_outputs_paths or (run_config is not None and run_kind == "stage"):
        stage_rows.setdefault(
            "write_outputs",
            ObservedStage(
                stage_key="write_outputs",
                stage_label=stage_label("write_outputs"),
                stage_artifact_stem=stage_artifact_stem("write_outputs"),
                stage_family=stage_family("write_outputs"),
                stage_order=stage_order("write_outputs"),
                artifact_paths=write_outputs_paths,
            ),
        )

    report = StageObservabilityReport(
        run_kind=run_kind,
        run_id=run_root.name,
        created_at=created_at,
        stages=sorted(
            stage_rows.values(),
            key=lambda row: (row.stage_order, row.stage_key),
        ),
    )
    return report


def write_stage_observability_report(
    *,
    run_root: Path,
    report: StageObservabilityReport,
) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    report_path = run_root / "stage_observability.json"
    tmp_path = run_root / "stage_observability.json.tmp"
    payload = report.model_dump(exclude_none=True)
    for stage_payload in payload.get("stages", []):
        if not isinstance(stage_payload, dict):
            continue
        stage_key = str(stage_payload.get("stage_key") or "").strip()
        if stage_key not in {
            "nonrecipe_knowledge_review",
            "recipe_llm_correct_and_link",
            "line_role",
        }:
            continue
        workbooks = stage_payload.get("workbooks")
        if not isinstance(workbooks, list):
            continue
        for workbook_payload in workbooks:
            if not isinstance(workbook_payload, dict):
                continue
            stage_dir_value = workbook_payload.get("stage_dir")
            stage_dir = run_root / str(stage_dir_value) if isinstance(stage_dir_value, str) else None
            if stage_dir is None or not stage_dir.exists() or not stage_dir.is_dir():
                continue
            if stage_key == "nonrecipe_knowledge_review":
                summary_path = write_knowledge_stage_summary(stage_root=stage_dir)
                artifact_key = "knowledge_stage_summary_json"
            elif stage_key == "recipe_llm_correct_and_link":
                summary_path = write_recipe_stage_summary(stage_root=stage_dir)
                artifact_key = "recipe_stage_summary_json"
            else:
                summary_path = write_line_role_stage_summary(stage_root=stage_dir)
                artifact_key = "line_role_stage_summary_json"
            artifact_paths = workbook_payload.get("artifact_paths")
            if not isinstance(artifact_paths, dict):
                artifact_paths = {}
            artifact_paths[artifact_key] = _relative_to(run_root, summary_path) or str(
                summary_path
            )
            workbook_payload["artifact_paths"] = artifact_paths
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(report_path)
    return report_path


def load_stage_observability_report(path: Path) -> StageObservabilityReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Stage observability payload must be an object: {path}")
    return StageObservabilityReport.model_validate(payload)
