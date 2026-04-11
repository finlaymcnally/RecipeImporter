from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from cookimport.llm.repair_recovery_policy import (
    FOLLOWUP_KIND_FRESH_SESSION_RETRY,
    FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
    FOLLOWUP_KIND_WATCHDOG_RETRY,
    INLINE_JSON_TRANSPORT,
    KNOWLEDGE_CLASSIFY_STEP_KEY,
    KNOWLEDGE_GROUP_STEP_KEY,
    KNOWLEDGE_POLICY_STAGE_KEY,
    LINE_ROLE_POLICY_STAGE_KEY,
    RECIPE_POLICY_STAGE_KEY,
    TASKFILE_TRANSPORT,
    build_followup_budget_summary,
)
from cookimport.llm.knowledge_runtime_replay import replay_knowledge_runtime
from cookimport.llm.knowledge_runtime_state import (
    KNOWLEDGE_PACKET_EXPLICIT_NO_FINAL_OUTPUT_REASON_CODES,
    knowledge_reason_is_explicit_no_final_output,
)
from cookimport.runs.stage_names import (
    NONRECIPE_FINALIZE_STAGE_KEY,
    NONRECIPE_ROUTE_STAGE_KEY,
    RECIPE_BUILD_FINAL_STAGE_KEY,
    RECIPE_BUILD_INTERMEDIATE_STAGE_KEY,
    RECIPE_REFINE_STAGE_KEY,
    LABEL_DETERMINISTIC_STAGE_KEY,
    LABEL_REFINE_STAGE_KEY,
    RECIPE_BOUNDARY_STAGE_KEY,
    recipe_stage_keys_for_pipeline,
    stage_artifact_stem,
    stage_family,
    stage_label,
    stage_order,
)
from cookimport.staging.output_names import (
    LINE_ROLE_AUTHORITATIVE_BLOCK_LABELS_FILE_NAME,
    LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME,
    LINE_ROLE_LABEL_DIFFS_FILE_NAME,
    LINE_ROLE_PIPELINE_DIR_NAME,
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_EXCLUSIONS_FILE_NAME,
    NONRECIPE_FINALIZE_STATUS_FILE_NAME,
    NONRECIPE_ROUTE_FILE_NAME,
)


STAGE_OBSERVABILITY_SCHEMA_VERSION = "stage_observability.v1"
RECIPE_MANIFEST_FILE_NAME = "recipe_manifest.json"
KNOWLEDGE_MANIFEST_FILE_NAME = "knowledge_manifest.json"
KNOWLEDGE_STAGE_STATUS_FILE_NAME = "stage_status.json"
KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION = "knowledge_stage_status.v1"
KNOWLEDGE_STAGE_SUMMARY_FILE_NAME = "knowledge_stage_summary.json"
KNOWLEDGE_STAGE_SUMMARY_SCHEMA_VERSION = "knowledge_stage_summary.v10"
RECIPE_STAGE_SUMMARY_FILE_NAME = "recipe_stage_summary.json"
RECIPE_STAGE_SUMMARY_SCHEMA_VERSION = "recipe_stage_summary.v8"
LINE_ROLE_STAGE_SUMMARY_FILE_NAME = "line_role_stage_summary.json"
LINE_ROLE_STAGE_SUMMARY_SCHEMA_VERSION = "line_role_stage_summary.v6"
_LINE_ROLE_TERMINAL_PACKET_STATES = frozenset(
    {
        "validated",
        "repair_recovered",
        "repair_failed",
        "invalid_output",
    }
)
_LINE_ROLE_FAILED_PACKET_STATES = frozenset(
    {
        "repair_failed",
        "invalid_output",
    }
)

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
    "knowledge_tag_proposals.jsonl",
    "proposals/*",
)
_KNOWLEDGE_PACKET_TERMINAL_STATES = frozenset(
    {
        "validated",
        "retry_recovered",
        "retry_failed",
        "repair_recovered",
        "repair_failed",
        "no_final_output",
        "watchdog_killed",
        "invalid_output",
        *KNOWLEDGE_PACKET_EXPLICIT_NO_FINAL_OUTPUT_REASON_CODES,
        "cancelled_due_to_interrupt",
    }
)
_KNOWLEDGE_FAILED_PACKET_STATES = frozenset(
    {
        "invalid_output",
        "retry_failed",
        "repair_failed",
        "no_final_output",
        "watchdog_killed",
        *KNOWLEDGE_PACKET_EXPLICIT_NO_FINAL_OUTPUT_REASON_CODES,
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
    attention_summary: dict[str, Any] | None = None
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


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def _runtime_guardrail_payload(
    *,
    phase_manifest_payload: Mapping[str, Any] | None,
    telemetry_payload: Mapping[str, Any] | None,
    key: str,
) -> dict[str, Any] | None:
    runtime_metadata = (
        phase_manifest_payload.get("runtime_metadata")
        if isinstance(phase_manifest_payload, Mapping)
        else None
    )
    if isinstance(runtime_metadata, Mapping):
        candidate = runtime_metadata.get(key)
        if isinstance(candidate, Mapping):
            return dict(candidate)
    telemetry_summary = (
        telemetry_payload.get("summary")
        if isinstance(telemetry_payload, Mapping)
        else None
    )
    if isinstance(telemetry_summary, Mapping):
        candidate = telemetry_summary.get(key)
        if isinstance(candidate, Mapping):
            return dict(candidate)
    return None


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
        "knowledge_tag_proposals.jsonl": stage_root / "knowledge_tag_proposals.jsonl",
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
        declared_state = declared.get(artifact_key)
        if declared_state == "skipped_due_to_interrupt":
            states[artifact_key] = "skipped_due_to_interrupt"
            continue
        if _knowledge_stage_artifact_present(path, artifact_key):
            states[artifact_key] = "present"
            continue
        if interrupted_before_finalization:
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


def _int_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _sorted_int_map(payload: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for key, value in payload.items():
        cleaned = str(key or "").strip()
        if not cleaned:
            continue
        normalized[cleaned] = _int_count(value)
    return dict(sorted(normalized.items()))


def _build_attention_summary(
    *,
    zero_target_counts: Mapping[str, Any] | None = None,
    context_counts: Mapping[str, Any] | None = None,
    reason_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_zero_target_counts = _sorted_int_map(zero_target_counts)
    payload: dict[str, Any] = {
        "needs_attention": any(
            _int_count(value) > 0 for value in normalized_zero_target_counts.values()
        ),
        "zero_target_counts": normalized_zero_target_counts,
    }
    normalized_context_counts = _sorted_int_map(context_counts)
    if normalized_context_counts:
        payload["context_counts"] = normalized_context_counts
    normalized_reason_counts: dict[str, Any] = {}
    if isinstance(reason_counts, Mapping):
        for key, value in reason_counts.items():
            cleaned = str(key or "").strip()
            if not cleaned:
                continue
            if isinstance(value, Mapping):
                normalized_reason_counts[cleaned] = _sorted_int_map(value)
            else:
                normalized_reason_counts[cleaned] = _int_count(value)
    if normalized_reason_counts:
        payload["reason_counts"] = dict(sorted(normalized_reason_counts.items()))
    return payload


def _line_role_run_root(stage_root: Path) -> Path:
    try:
        return stage_root.parents[2]
    except IndexError:
        return stage_root


def _load_all_label_llm_rows(run_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    label_root = run_root / "label_refine"
    if not label_root.exists() or not label_root.is_dir():
        return rows
    for workbook_dir in sorted(path for path in label_root.iterdir() if path.is_dir()):
        rows.extend(_load_jsonl_dicts(workbook_dir / "labeled_lines.jsonl"))
    return rows


def _load_line_role_authoritative_rows(run_root: Path) -> list[dict[str, Any]]:
    authoritative_path = (
        run_root
        / LINE_ROLE_PIPELINE_DIR_NAME
        / LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME
    )
    if authoritative_path.exists():
        return _load_jsonl_dicts(authoritative_path)
    return _load_all_label_llm_rows(run_root)


def _build_label_llm_attention_summary(workbook_dir: Path) -> dict[str, Any]:
    labeled_line_rows = _load_jsonl_dicts(workbook_dir / "labeled_lines.jsonl")
    fallback_line_count = sum(
        1
        for row in labeled_line_rows
        if str(row.get("decided_by") or "").strip() == "fallback"
    )
    context_counts = {
        "line_total": len(labeled_line_rows),
        "codex_line_count": sum(
            1 for row in labeled_line_rows if str(row.get("decided_by") or "").strip() == "codex"
        ),
        "rule_line_count": sum(
            1 for row in labeled_line_rows if str(row.get("decided_by") or "").strip() == "rule"
        ),
    }
    return _build_attention_summary(
        zero_target_counts={
            "fallback_line_count": fallback_line_count,
        },
        context_counts=context_counts,
    )


def _build_recipe_boundary_attention_summary(workbook_dir: Path) -> dict[str, Any]:
    span_decisions_payload = _load_json_dict(workbook_dir / "span_decisions.json") or {}
    span_decisions = span_decisions_payload.get("span_decisions")
    if not isinstance(span_decisions, list):
        span_decisions = []
    accepted_count = 0
    rejected_count = 0
    rejection_reason_counts: Counter[str] = Counter()
    for row in span_decisions:
        if not isinstance(row, Mapping):
            continue
        decision = str(row.get("decision") or "").strip()
        if decision == "accepted_recipe_span":
            accepted_count += 1
            continue
        if decision == "rejected_pseudo_recipe_span":
            rejected_count += 1
            rejection_reason = str(row.get("rejection_reason") or "").strip()
            if rejection_reason:
                rejection_reason_counts[rejection_reason] += 1
    return _build_attention_summary(
        zero_target_counts={
            "rejected_pseudo_recipe_span_count": rejected_count,
        },
        context_counts={
            "accepted_recipe_span_count": accepted_count,
            "span_decision_count": accepted_count + rejected_count,
        },
        reason_counts={
            "span_rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        },
    )


def _build_nonrecipe_route_attention_summary(run_root: Path) -> dict[str, Any]:
    exclusion_rows = _load_jsonl_dicts(run_root / NONRECIPE_EXCLUSIONS_FILE_NAME)
    return _build_attention_summary(
        zero_target_counts={},
        context_counts={
            "excluded_row_count": len(exclusion_rows),
        },
        reason_counts={},
    )


def _recipe_build_final_attention_summary(workbook_dir: Path) -> dict[str, Any]:
    manifest_payload = _load_json_dict(workbook_dir / RECIPE_MANIFEST_FILE_NAME) or {}
    counts = manifest_payload.get("counts")
    if not isinstance(counts, Mapping):
        counts = {}
    return _build_attention_summary(
        zero_target_counts={
            "recipe_correction_error_count": counts.get("recipe_correction_error"),
            "final_recipe_not_promoted_count": counts.get(
                "final_recipe_authority_not_promoted"
            ),
            "final_recipe_error_count": counts.get("final_recipe_authority_error"),
        },
        context_counts={
            "final_recipe_promoted_count": counts.get("final_recipe_authority_promoted"),
            "recipe_build_final_ok_count": counts.get("recipe_build_final_ok"),
            "recipe_build_final_skipped_count": counts.get("recipe_build_final_skipped"),
        },
    )


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


def _knowledge_row_is_no_final_output(row: Mapping[str, Any]) -> bool:
    reason_code = str(row.get("terminal_reason_code") or "").strip()
    if knowledge_reason_is_explicit_no_final_output(reason_code):
        return True
    if reason_code.startswith("watchdog_"):
        return True
    state = str(row.get("state") or "").strip()
    return state in {"no_final_output", "watchdog_killed"}


def build_knowledge_stage_summary(stage_root: Path) -> dict[str, Any]:
    phase_manifest_payload = _load_json_dict(stage_root / "phase_manifest.json") or {}
    knowledge_manifest_payload = _load_json_dict(stage_root.parent / KNOWLEDGE_MANIFEST_FILE_NAME) or {}
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
    no_final_output_shard_count = sum(
        1 for row in task_rows if _knowledge_row_is_no_final_output(row)
    )
    no_final_output_reason_code_counts = dict(
        sorted(
            Counter(
                str(row.get("terminal_reason_code") or "").strip() or str(row.get("state") or "").strip()
                for row in task_rows
                if _knowledge_row_is_no_final_output(row)
            ).items()
        )
    )
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
    worker_status_rows = _load_worker_status_rows(stage_root)
    salvage_counts = _collect_salvage_counts(stage_root)
    telemetry_payload = _load_json_dict(stage_root / "telemetry.json") or {}
    telemetry_summary = (
        telemetry_payload.get("summary")
        if isinstance(telemetry_payload.get("summary"), Mapping)
        else {}
    )
    packet_economics = (
        dict(telemetry_summary.get("packet_economics") or {})
        if isinstance(telemetry_summary.get("packet_economics"), Mapping)
        else {}
    )
    repair_recovery_policy = (
        telemetry_summary.get("repair_recovery_policy")
        if isinstance(telemetry_summary.get("repair_recovery_policy"), Mapping)
        else None
    )
    if not isinstance(repair_recovery_policy, Mapping):
        same_session_mode = (
            int(packet_economics.get("same_session_transition_count_total") or 0) > 0
        )
        if same_session_mode:
            repair_recovery_policy = {
                "active_transport": TASKFILE_TRANSPORT,
                "worker_assignment": build_followup_budget_summary(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    transport=TASKFILE_TRANSPORT,
                    spent_attempts_by_kind={
                        FOLLOWUP_KIND_FRESH_SESSION_RETRY: _sum_worker_status_int(
                            worker_status_rows,
                            "fresh_session_retry_count",
                        ),
                        FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: _sum_worker_status_int(
                            worker_status_rows,
                            "fresh_worker_replacement_count",
                        ),
                        FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                            packet_economics.get("repair_packet_count_total") or 0
                        ),
                    },
                    allowed_attempts_multiplier_by_kind={
                        FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: max(
                            len(task_rows),
                            int(packet_economics.get("packet_count_total") or 0),
                        ),
                    },
                ),
                "semantic_steps": {
                    KNOWLEDGE_CLASSIFY_STEP_KEY: build_followup_budget_summary(
                        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                        transport=TASKFILE_TRANSPORT,
                        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                        spent_attempts_by_kind={
                            FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: int(
                                packet_economics.get(
                                    "classification_same_session_repair_rewrite_count_total"
                                )
                                or 0
                            ),
                        },
                    ),
                    KNOWLEDGE_GROUP_STEP_KEY: build_followup_budget_summary(
                        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                        transport=TASKFILE_TRANSPORT,
                        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                        spent_attempts_by_kind={
                            FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: int(
                                packet_economics.get(
                                    "grouping_same_session_repair_rewrite_count_total"
                                )
                                or 0
                            ),
                        },
                    ),
                },
            }
        else:
            repair_recovery_policy = {
                "active_transport": INLINE_JSON_TRANSPORT,
                "semantic_steps": {
                    KNOWLEDGE_CLASSIFY_STEP_KEY: build_followup_budget_summary(
                        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                        transport=INLINE_JSON_TRANSPORT,
                        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                        spent_attempts_by_kind={
                            FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                                packet_economics.get(
                                    "classification_repair_packet_count_total"
                                )
                                or 0
                            ),
                        },
                        allowed_attempts_multiplier_by_kind=(
                            {
                                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                                    packet_economics.get(
                                        "classification_step_count_total"
                                    )
                                    or 0
                                ),
                            }
                            if int(
                                packet_economics.get("classification_step_count_total")
                                or 0
                            )
                            > 0
                            else None
                        ),
                    ),
                    KNOWLEDGE_GROUP_STEP_KEY: build_followup_budget_summary(
                        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                        transport=INLINE_JSON_TRANSPORT,
                        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                        spent_attempts_by_kind={
                            FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                                packet_economics.get(
                                    "grouping_repair_packet_count_total"
                                )
                                or 0
                            ),
                        },
                        allowed_attempts_multiplier_by_kind=(
                            {
                                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                                    packet_economics.get("grouping_step_count_total")
                                    or 0
                                ),
                            }
                            if int(packet_economics.get("grouping_step_count_total") or 0)
                            > 0
                            else None
                        ),
                    ),
                },
            }
    replay_summary = replay_knowledge_runtime(knowledge_root=stage_root)
    packet_total = len(task_rows) if task_rows else int(replay_summary.rollup.packet_total)
    failed_followup_total = sum(_int_count(value) for value in followup_failed_counts.values())
    manifest_counts = (
        knowledge_manifest_payload.get("counts")
        if isinstance(knowledge_manifest_payload.get("counts"), Mapping)
        else {}
    )
    manifest_grounding_counts = (
        knowledge_manifest_payload.get("grounding_counts")
        if isinstance(knowledge_manifest_payload.get("grounding_counts"), Mapping)
        else {}
    )
    grounding_counts = {
        "kept_knowledge_block_count": int(manifest_counts.get("kept_knowledge_block_count") or 0),
        "retrieval_gate_rejected_block_count": int(
            manifest_counts.get("retrieval_gate_rejected_block_count") or 0
        ),
        "kept_for_review_block_count": int(
            manifest_counts.get("kept_for_review_block_count") or 0
        ),
        "knowledge_group_count": int(
            manifest_counts.get("knowledge_group_count") or 0
        ),
        "knowledge_group_split_count": int(
            manifest_counts.get("knowledge_group_split_count") or 0
        ),
        "knowledge_groups_using_existing_tags": int(
            manifest_counts.get("knowledge_groups_using_existing_tags") or 0
        ),
        "knowledge_groups_using_proposed_tags": int(
            manifest_counts.get("knowledge_groups_using_proposed_tags") or 0
        ),
        "knowledge_blocks_grounded_to_existing_tags": int(
            manifest_counts.get("knowledge_blocks_grounded_to_existing_tags") or 0
        ),
        "knowledge_blocks_using_proposed_tags": int(
            manifest_counts.get("knowledge_blocks_using_proposed_tags") or 0
        ),
        "tag_proposal_count": int(manifest_counts.get("tag_proposal_count") or 0),
        "group_resolution_details": list(
            manifest_grounding_counts.get("group_resolution_details")
            or manifest_counts.get("group_resolution_details")
            or []
        ),
    }
    summary = {
        "authoritative": bool(status_payload),
        "schema_version": KNOWLEDGE_STAGE_SUMMARY_SCHEMA_VERSION,
        "status_schema_version": (
            str(status_payload.get("schema_version") or "").strip()
            or KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION
        ),
        "stage_key": (
            str(status_payload.get("stage_key") or "").strip()
            or "nonrecipe_finalize"
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
            "no_final_output_shard_count": no_final_output_shard_count,
            "no_final_output_reason_code_counts": no_final_output_reason_code_counts,
            "llm_review_total": packet_total,
            "topline": {
                "validated": int(packet_state_counts.get("validated") or 0),
                "retry_recovered": int(packet_state_counts.get("retry_recovered") or 0),
                "repair_recovered": int(packet_state_counts.get("repair_recovered") or 0),
                "failed": sum(
                    int(packet_state_counts.get(key) or 0) for key in _KNOWLEDGE_FAILED_PACKET_STATES
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
        "repair_recovery_policy": dict(repair_recovery_policy or {}),
        "salvage": salvage_counts,
        "packet_economics": packet_economics,
        "grounding_counts": grounding_counts,
        "pre_kill_failure_counts": dict(pre_kill_failure_counts),
        "pre_kill_failures_observed": _count_nested_positive_values(pre_kill_failure_counts) > 0,
    }
    worker_session_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest_payload,
        telemetry_payload=telemetry_payload,
        key="worker_session_guardrails",
    )
    if worker_session_guardrails is not None:
        summary["worker_session_guardrails"] = worker_session_guardrails
    task_file_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest_payload,
        telemetry_payload=telemetry_payload,
        key="task_file_guardrails",
    )
    if task_file_guardrails is not None:
        summary["task_file_guardrails"] = task_file_guardrails
    summary["attention_summary"] = _build_attention_summary(
        zero_target_counts={
            "invalid_shard_count": packet_state_counts.get("invalid_output"),
            "no_final_output_shard_count": no_final_output_shard_count,
            "failed_packet_count": summary["packets"]["topline"].get("failed"),
            "cancelled_due_to_interrupt_packet_count": summary["packets"]["topline"].get(
                "cancelled_due_to_interrupt"
            ),
            "unreviewed_shard_count": salvage_counts.get("unreviewed_shard_count"),
            "unreviewed_packet_count": salvage_counts.get("unreviewed_packet_count"),
            "unreviewed_block_count": salvage_counts.get("unreviewed_block_count"),
            "failed_followup_count": failed_followup_total,
            "pre_kill_failure_count": _count_nested_positive_values(pre_kill_failure_counts),
        },
        context_counts={
            "packet_total": packet_total,
            "llm_review_total": packet_total,
            "validated_packet_count": packet_state_counts.get("validated"),
            "retry_recovered_packet_count": packet_state_counts.get("retry_recovered"),
            "repair_recovered_packet_count": packet_state_counts.get("repair_recovered"),
            "owned_row_count_total": packet_economics.get("owned_row_count_total"),
            "repair_packet_count_total": packet_economics.get("repair_packet_count_total"),
        },
        reason_counts={
            "terminal_reason_code_counts": terminal_reason_code_counts,
            "no_final_output_reason_code_counts": no_final_output_reason_code_counts,
            "followup_failed_counts": followup_failed_counts,
        },
    )
    return summary


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


def _load_worker_status_rows(stage_root: Path) -> list[dict[str, Any]]:
    return [
        _load_json_dict(path) or {}
        for path in sorted(stage_root.glob("workers/*/status.json"))
    ]


def _sum_worker_status_int(
    worker_status_rows: list[dict[str, Any]],
    key: str,
) -> int:
    return sum(int((row or {}).get(key) or 0) for row in worker_status_rows)


def _first_mapping(
    value: Any,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return dict(fallback or {})


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


def _line_role_stage_state_totals(
    *,
    shard_status_counts: Mapping[str, int],
    packet_state_counts: Mapping[str, int],
) -> tuple[int, int]:
    completed_from_status_files = sum(int(count or 0) for count in shard_status_counts.values())
    failed_from_status_files = sum(
        int(count or 0)
        for status, count in shard_status_counts.items()
        if status not in {"validated"}
    )
    completed_from_packet_ledger = sum(
        int(count or 0)
        for state, count in packet_state_counts.items()
        if state in _LINE_ROLE_TERMINAL_PACKET_STATES
    )
    failed_from_packet_ledger = sum(
        int(count or 0)
        for state, count in packet_state_counts.items()
        if state in _LINE_ROLE_FAILED_PACKET_STATES
    )
    return (
        max(completed_from_status_files, completed_from_packet_ledger),
        max(failed_from_status_files, failed_from_packet_ledger),
    )


def _recipe_active_transport(
    *,
    phase_manifest: Mapping[str, Any],
    telemetry_payload: Mapping[str, Any],
) -> str:
    settings_payload = (
        phase_manifest.get("settings") if isinstance(phase_manifest, Mapping) else None
    )
    if isinstance(settings_payload, Mapping):
        configured_transport = str(
            settings_payload.get("recipe_codex_exec_style") or ""
        ).strip()
        if configured_transport in {INLINE_JSON_TRANSPORT, TASKFILE_TRANSPORT}:
            return configured_transport
    runtime_metadata = (
        phase_manifest.get("runtime_metadata")
        if isinstance(phase_manifest, Mapping)
        else None
    )
    if isinstance(runtime_metadata, Mapping):
        configured_transport = str(runtime_metadata.get("transport") or "").strip()
        if configured_transport in {INLINE_JSON_TRANSPORT, TASKFILE_TRANSPORT}:
            return configured_transport
    telemetry_summary = (
        telemetry_payload.get("summary")
        if isinstance(telemetry_payload.get("summary"), Mapping)
        else {}
    )
    repair_recovery_policy = telemetry_summary.get("repair_recovery_policy")
    if isinstance(repair_recovery_policy, Mapping):
        configured_transport = str(repair_recovery_policy.get("transport") or "").strip()
        if configured_transport in {INLINE_JSON_TRANSPORT, TASKFILE_TRANSPORT}:
            return configured_transport
    telemetry_rows = (
        telemetry_payload.get("rows")
        if isinstance(telemetry_payload.get("rows"), list)
        else []
    )
    for row in telemetry_rows:
        if not isinstance(row, Mapping):
            continue
        configured_transport = str(
            row.get("codex_transport") or row.get("transport") or ""
        ).strip()
        if configured_transport in {INLINE_JSON_TRANSPORT, TASKFILE_TRANSPORT}:
            return configured_transport
        if str(row.get("prompt_input_mode") or "").strip() == "inline":
            return INLINE_JSON_TRANSPORT
    prompt_input_mode_counts = (
        telemetry_summary.get("prompt_input_mode_counts")
        if isinstance(telemetry_summary.get("prompt_input_mode_counts"), Mapping)
        else {}
    )
    if prompt_input_mode_counts.get("inline"):
        return INLINE_JSON_TRANSPORT
    return TASKFILE_TRANSPORT


def _codex_policy_fields_from_summary_payload(
    summary_payload: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("codex_transport", "codex_policy_mode"):
        value = str(summary_payload.get(key) or "").strip()
        if value:
            payload[key] = value
    shell_tool_enabled = summary_payload.get("codex_shell_tool_enabled")
    if shell_tool_enabled is not None:
        payload["codex_shell_tool_enabled"] = bool(shell_tool_enabled)
    for key in (
        "codex_transport_counts",
        "codex_policy_mode_counts",
        "codex_shell_tool_enabled_counts",
    ):
        counts = summary_payload.get(key)
        if isinstance(counts, Mapping):
            payload[key] = dict(sorted(dict(counts).items()))
    return payload


def build_recipe_stage_summary(stage_root: Path) -> dict[str, Any]:
    phase_manifest = _load_json_dict(stage_root / "phase_manifest.json") or {}
    promotion_report = _load_json_dict(stage_root / "promotion_report.json") or {}
    telemetry_payload = _load_json_dict(stage_root / "telemetry.json") or {}
    recipe_manifest = _load_json_dict(stage_root.parent / RECIPE_MANIFEST_FILE_NAME) or {}
    recipe_manifest_counts = recipe_manifest.get("counts")
    if not isinstance(recipe_manifest_counts, Mapping):
        recipe_manifest_counts = {}
    worker_state_counts, worker_reason_code_counts = _collect_worker_status_counts(stage_root)
    worker_status_rows = _load_worker_status_rows(stage_root)
    shard_status_paths = sorted(stage_root.glob("workers/*/shards/*/status.json"))
    shard_status_counts = _count_status_values(shard_status_paths)
    failed_shard_total = sum(
        count
        for status, count in shard_status_counts.items()
        if status not in {"validated"}
    )
    active_transport = _recipe_active_transport(
        phase_manifest=phase_manifest,
        telemetry_payload=telemetry_payload,
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
    recipe_result_counts = promotion_report.get("recipe_result_counts")
    if not isinstance(recipe_result_counts, Mapping):
        recipe_result_counts = {}
    handled_locally_skip_llm = promotion_report.get("handled_locally_skip_llm")
    if not isinstance(handled_locally_skip_llm, Mapping):
        handled_locally_skip_llm = {}
    summary = {
        "schema_version": RECIPE_STAGE_SUMMARY_SCHEMA_VERSION,
        "stage_key": "recipe_refine",
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
            "label": (
                "task_followup"
                if active_transport == TASKFILE_TRANSPORT
                else "shard_finalization"
            ),
            "handled_locally_skip_llm_count": int(
                handled_locally_skip_llm.get("count") or 0
            ),
            "repair_attempted_count": repair_attempted,
            "repair_completed_count": repair_completed,
            "repair_running_count": repair_running,
            "proposal_count": proposal_count,
        },
        "repair_recovery_policy": (
            build_followup_budget_summary(
                stage_key=RECIPE_POLICY_STAGE_KEY,
                transport=TASKFILE_TRANSPORT,
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: _sum_worker_status_int(
                        worker_status_rows,
                        "repair_worker_session_count",
                    ),
                    FOLLOWUP_KIND_FRESH_SESSION_RETRY: _sum_worker_status_int(
                        worker_status_rows,
                        "fresh_session_retry_count",
                    ),
                    FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: _sum_worker_status_int(
                        worker_status_rows,
                        "fresh_worker_replacement_count",
                    ),
                },
            )
            if active_transport == TASKFILE_TRANSPORT
            else build_followup_budget_summary(
                stage_key=RECIPE_POLICY_STAGE_KEY,
                transport=INLINE_JSON_TRANSPORT,
                spent_attempts_by_kind={},
            )
        ),
        "important_artifacts": important_artifacts,
    }
    worker_session_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest,
        telemetry_payload=telemetry_payload,
        key="worker_session_guardrails",
    )
    if worker_session_guardrails is not None:
        summary["worker_session_guardrails"] = worker_session_guardrails
    task_file_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest,
        telemetry_payload=telemetry_payload,
        key="task_file_guardrails",
    )
    if task_file_guardrails is not None:
        summary["task_file_guardrails"] = task_file_guardrails
    summary["attention_summary"] = _build_attention_summary(
        zero_target_counts={
            "invalid_shard_count": promotion_report.get("invalid_shards"),
            "missing_output_shard_count": promotion_report.get("missing_output_shards"),
            "fragmentary_recipe_count": recipe_result_counts.get("fragmentary"),
            "not_a_recipe_recipe_count": recipe_result_counts.get("not_a_recipe"),
            "recipe_correction_error_count": recipe_manifest_counts.get("recipe_correction_error"),
            "final_recipe_not_promoted_count": recipe_manifest_counts.get(
                "final_recipe_authority_not_promoted"
            ),
            "final_recipe_error_count": recipe_manifest_counts.get(
                "final_recipe_authority_error"
            ),
            "repair_attempted_count": repair_attempted,
        },
        context_counts={
            "recipe_total": recipe_manifest_counts.get("recipes_total"),
            "repaired_recipe_count": recipe_result_counts.get("repaired"),
            "promoted_recipe_count": recipe_manifest_counts.get(
                "final_recipe_authority_promoted"
            ),
            "handled_locally_skip_llm_count": handled_locally_skip_llm.get("count"),
            "repair_completed_count": repair_completed,
        },
        reason_counts={
            "recipe_result_counts": recipe_result_counts,
            "handled_locally_skip_llm_status_counts": (
                handled_locally_skip_llm.get("status_counts")
                if isinstance(handled_locally_skip_llm.get("status_counts"), Mapping)
                else {}
            ),
        },
    )
    return summary


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
    promotion_report = _load_json_dict(stage_root / "promotion_report.json") or {}
    telemetry_payload = _load_json_dict(stage_root / "telemetry.json") or {}
    task_rows = _load_jsonl_dicts(stage_root / "shard_status.jsonl")
    line_rows = _load_jsonl_dicts(stage_root / "canonical_line_table.jsonl")
    labeled_line_rows = _load_line_role_authoritative_rows(_line_role_run_root(stage_root))
    worker_state_counts, worker_reason_code_counts = _collect_worker_status_counts(stage_root)
    worker_status_rows = _load_worker_status_rows(stage_root)
    shard_status_paths = sorted(stage_root.glob("workers/*/shards/*/status.json"))
    shard_status_counts = _count_status_values(shard_status_paths)
    packet_state_counts = _count_value_rows(task_rows, "state")
    packet_terminal_outcome_counts = _count_value_rows(task_rows, "terminal_outcome")
    packet_attempt_type_counts = _count_value_rows(task_rows, "last_attempt_type")
    completed_shard_total_for_stage_state, failed_shard_total_for_stage_state = (
        _line_role_stage_state_totals(
            shard_status_counts=shard_status_counts,
            packet_state_counts=packet_state_counts,
        )
    )
    repair_attempted, repair_completed, repair_running = _repair_rollup(stage_root)
    proposal_count = len(list(stage_root.glob("proposals/*.json")))
    planned_task_total = _count_jsonl_rows(stage_root / "shard_manifest.jsonl")
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
        "shard_status_jsonl": "shard_status.jsonl",
        "worker_assignments_json": "worker_assignments.json",
        "promotion_report_json": "promotion_report.json",
        "telemetry_json": "telemetry.json",
        "failures_json": "failures.json",
        "proposals_dir": "proposals",
    }
    llm_authoritative_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("llm_authoritative_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    unresolved_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("unresolved_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    suspicious_packet_count = sum(
        1
        for row in task_rows
        if bool(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_shard"))
    )
    suspicious_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_row_count") or 0)
        for row in task_rows
        if isinstance(row, dict)
    )
    active_transport = TASKFILE_TRANSPORT
    telemetry_summary = (
        telemetry_payload.get("summary")
        if isinstance(telemetry_payload.get("summary"), Mapping)
        else {}
    )
    prompt_input_mode_counts = (
        telemetry_summary.get("prompt_input_mode_counts")
        if isinstance(telemetry_summary.get("prompt_input_mode_counts"), Mapping)
        else {}
    )
    codex_policy_fields = _codex_policy_fields_from_summary_payload(telemetry_summary)
    task_row_transport_counts = _count_metadata_value_rows(task_rows, "transport")
    if task_row_transport_counts.get(INLINE_JSON_TRANSPORT):
        active_transport = INLINE_JSON_TRANSPORT
    elif any(
        str(mode).startswith("structured_session")
        for mode in prompt_input_mode_counts.keys()
    ) or int(telemetry_summary.get("structured_followup_call_count") or 0) > 0:
        active_transport = INLINE_JSON_TRANSPORT
    elif any(
        str(row.get("last_attempt_type") or "").strip().startswith("structured_session")
        for row in task_rows
    ):
        active_transport = INLINE_JSON_TRANSPORT
    structured_repair_followup_call_count = int(
        telemetry_summary.get("structured_repair_followup_call_count")
        or prompt_input_mode_counts.get("structured_session_repair")
        or prompt_input_mode_counts.get("inline_repair")
        or 0
    )
    watchdog_retry_call_count = int(
        telemetry_summary.get("watchdog_retry_call_count")
        or prompt_input_mode_counts.get("inline_watchdog_retry")
        or 0
    )
    inline_shard_budget_count = max(planned_task_total, len(task_rows), completed_task_total, 1)
    summary = {
        "schema_version": LINE_ROLE_STAGE_SUMMARY_SCHEMA_VERSION,
        "stage_key": "line_role",
        "stage_state": _stage_summary_state(
            planned_total=planned_shard_total,
            completed_total=completed_shard_total_for_stage_state,
            failed_total=failed_shard_total_for_stage_state,
        ),
        "lines": {
            "canonical_line_total": len(line_rows),
            "llm_authoritative_row_count": llm_authoritative_row_count,
            "unresolved_row_count": unresolved_row_count,
            "suspicious_row_count": suspicious_row_count,
        },
        "shards": {
            "shard_total": max(planned_task_total, len(task_rows), completed_task_total),
            "planned_total": planned_task_total,
            "completed_output_total": completed_task_total,
            "state_counts": packet_state_counts,
            "terminal_outcome_counts": packet_terminal_outcome_counts,
            "attempt_type_counts": packet_attempt_type_counts,
            "suspicious_shard_count": suspicious_packet_count,
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
        "repair_recovery_policy": (
            build_followup_budget_summary(
                stage_key=LINE_ROLE_POLICY_STAGE_KEY,
                transport=INLINE_JSON_TRANSPORT,
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: structured_repair_followup_call_count,
                    FOLLOWUP_KIND_WATCHDOG_RETRY: watchdog_retry_call_count,
                },
                allowed_attempts_multiplier_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: inline_shard_budget_count,
                    FOLLOWUP_KIND_WATCHDOG_RETRY: inline_shard_budget_count,
                },
            )
            if active_transport == INLINE_JSON_TRANSPORT
            else build_followup_budget_summary(
                stage_key=LINE_ROLE_POLICY_STAGE_KEY,
                transport=TASKFILE_TRANSPORT,
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: _sum_worker_status_int(
                        worker_status_rows,
                        "same_session_repair_rewrite_count",
                    ),
                    FOLLOWUP_KIND_FRESH_SESSION_RETRY: _sum_worker_status_int(
                        worker_status_rows,
                        "fresh_session_retry_count",
                    ),
                    FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: _sum_worker_status_int(
                        worker_status_rows,
                        "fresh_worker_replacement_count",
                    ),
                },
            )
        ),
        "important_artifacts": important_artifacts,
        **codex_policy_fields,
    }
    worker_session_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest,
        telemetry_payload=telemetry_payload,
        key="worker_session_guardrails",
    )
    if worker_session_guardrails is not None:
        summary["worker_session_guardrails"] = worker_session_guardrails
    task_file_guardrails = _runtime_guardrail_payload(
        phase_manifest_payload=phase_manifest,
        telemetry_payload=telemetry_payload,
        key="task_file_guardrails",
    )
    if task_file_guardrails is not None:
        summary["task_file_guardrails"] = task_file_guardrails
    summary["attention_summary"] = _build_attention_summary(
        zero_target_counts={
            "invalid_shard_count": promotion_report.get("invalid_shards"),
            "missing_output_shard_count": promotion_report.get("missing_output_shards"),
            "unresolved_row_count": unresolved_row_count,
            "suspicious_shard_count": suspicious_packet_count,
            "suspicious_row_count": suspicious_row_count,
            "repair_attempted_count": repair_attempted,
            "watchdog_retry_shard_count": packet_attempt_type_counts.get("watchdog_retry"),
        },
        context_counts={
            "canonical_line_total": len(line_rows),
            "llm_authoritative_row_count": llm_authoritative_row_count,
            "repair_completed_count": repair_completed,
            "repair_running_count": repair_running,
        },
        reason_counts={
            "terminal_outcome_counts": packet_terminal_outcome_counts,
        },
    )
    return summary


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
    del workbook_dir
    pipeline_id = str(recipe_manifest_payload.get("pipeline") or "").strip() or None
    return tuple(recipe_stage_keys_for_pipeline(pipeline_id))


def build_stage_observability_report(
    *,
    run_root: Path,
    run_kind: str,
    created_at: str,
    run_config: Mapping[str, Any] | None = None,
    artifact_scan_root: Path | None = None,
) -> StageObservabilityReport:
    stage_rows: dict[str, ObservedStage] = {}
    observed_root = artifact_scan_root or run_root

    raw_llm_root = observed_root / "raw" / "llm"
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
                if key == "recipe_refine":
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
                    key == "recipe_refine"
                    and not stage_dir.exists()
                    and not input_dir.exists()
                    and not output_dir.exists()
                ):
                    continue
                if key not in {
                    "recipe_build_intermediate",
                    "recipe_build_final",
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
                attention_summary = (
                    _recipe_build_final_attention_summary(workbook_dir)
                    if key == "recipe_build_final" and recipe_manifest_path.exists()
                    else None
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
                    attention_summary=attention_summary,
                )
                stage_rows[key].workbooks.append(workbook_observation)

            knowledge_manifest_path = workbook_dir / KNOWLEDGE_MANIFEST_FILE_NAME
            knowledge_manifest_payload = _load_json_dict(knowledge_manifest_path) or {}
            knowledge_paths = knowledge_manifest_payload.get("paths")
            if not isinstance(knowledge_paths, Mapping):
                knowledge_paths = {}
            knowledge_dir = workbook_dir / stage_artifact_stem("nonrecipe_finalize")
            knowledge_input_dir = _path_from_manifest(
                knowledge_paths.get("knowledge_in_dir")
            ) or (knowledge_dir / "in")
            knowledge_output_dir = _path_from_manifest(
                knowledge_paths.get("proposals_dir")
            ) or (knowledge_dir / "proposals")
            if knowledge_manifest_path.exists() or knowledge_dir.exists():
                key = "nonrecipe_finalize"
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
    for stage_key in ("label_deterministic", "label_refine", "recipe_boundary"):
        stage_dir = observed_root / stage_artifact_stem(stage_key)
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
            attention_summary = None
            if stage_key == "label_refine":
                attention_summary = _build_label_llm_attention_summary(workbook_dir)
            elif stage_key == "recipe_boundary":
                attention_summary = _build_recipe_boundary_attention_summary(workbook_dir)
            stage_rows[stage_key].workbooks.append(
                StageWorkbookObservation(
                    workbook_slug=workbook_dir.name,
                    stage_dir=_relative_to(run_root, workbook_dir),
                    attention_summary=attention_summary,
                    artifact_paths={
                        key: value
                        for key, value in artifact_paths.items()
                        if value is not None
                    },
                )
            )
    nonrecipe_route_path = observed_root / NONRECIPE_ROUTE_FILE_NAME
    nonrecipe_exclusions_path = observed_root / NONRECIPE_EXCLUSIONS_FILE_NAME
    if nonrecipe_route_path.exists() or nonrecipe_exclusions_path.exists():
        stage_key = "nonrecipe_route"
        artifact_paths = {}
        if nonrecipe_route_path.exists():
            artifact_paths["nonrecipe_route_json"] = (
                _relative_to(run_root, nonrecipe_route_path) or ""
            )
        if nonrecipe_exclusions_path.exists():
            artifact_paths["nonrecipe_exclusions_jsonl"] = (
                _relative_to(run_root, nonrecipe_exclusions_path) or ""
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
        stage_rows[stage_key].workbooks = [
            StageWorkbookObservation(
                workbook_slug=observed_root.name,
                attention_summary=_build_nonrecipe_route_attention_summary(observed_root),
            )
        ]
    nonrecipe_authority_path = observed_root / NONRECIPE_AUTHORITY_FILE_NAME
    nonrecipe_finalize_status_path = observed_root / NONRECIPE_FINALIZE_STATUS_FILE_NAME
    if nonrecipe_authority_path.exists() or nonrecipe_finalize_status_path.exists():
        stage_key = "nonrecipe_finalize"
        artifact_paths = {}
        if nonrecipe_authority_path.exists():
            artifact_paths["nonrecipe_authority_json"] = (
                _relative_to(run_root, nonrecipe_authority_path) or ""
            )
        if nonrecipe_finalize_status_path.exists():
            artifact_paths["nonrecipe_finalize_status_json"] = (
                _relative_to(run_root, nonrecipe_finalize_status_path) or ""
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
    line_role_stage_dir = observed_root / "line-role-pipeline" / "runtime" / "line_role"
    if line_role_stage_dir.exists() and line_role_stage_dir.is_dir():
        stage_key = "line_role"
        line_role_root = observed_root / LINE_ROLE_PIPELINE_DIR_NAME
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
                workbook_slug=observed_root.name,
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
                        "shard_manifest_jsonl": _relative_to(
                            run_root, line_role_stage_dir / "shard_manifest.jsonl"
                        ),
                        "shard_status_jsonl": _relative_to(
                            run_root, line_role_stage_dir / "shard_status.jsonl"
                        ),
                        "telemetry_json": _relative_to(
                            run_root, line_role_stage_dir / "telemetry.json"
                        ),
                        "authoritative_labeled_lines_jsonl": _relative_to(
                            run_root,
                            line_role_root / LINE_ROLE_AUTHORITATIVE_LABELED_LINES_FILE_NAME,
                        ),
                        "authoritative_block_labels_json": _relative_to(
                            run_root,
                            line_role_root / LINE_ROLE_AUTHORITATIVE_BLOCK_LABELS_FILE_NAME,
                        ),
                        "label_diffs_jsonl": _relative_to(
                            run_root,
                            line_role_root / LINE_ROLE_LABEL_DIFFS_FILE_NAME,
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
            matches = sorted(observed_root.glob(path_name))
            if matches:
                write_outputs_paths[artifact_key] = str(path_name)
            continue
        target = observed_root / path_name
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
            "nonrecipe_finalize",
            "recipe_refine",
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
            if stage_key == "nonrecipe_finalize":
                summary_payload = build_knowledge_stage_summary(stage_root=stage_dir)
                summary_path = write_knowledge_stage_summary(
                    stage_root=stage_dir,
                    summary=summary_payload,
                )
                artifact_key = "knowledge_stage_summary_json"
            elif stage_key == "recipe_refine":
                summary_payload = build_recipe_stage_summary(stage_root=stage_dir)
                summary_path = write_recipe_stage_summary(
                    stage_root=stage_dir,
                    summary=summary_payload,
                )
                artifact_key = "recipe_stage_summary_json"
            else:
                summary_payload = build_line_role_stage_summary(stage_root=stage_dir)
                summary_path = write_line_role_stage_summary(
                    stage_root=stage_dir,
                    summary=summary_payload,
                )
                artifact_key = "line_role_stage_summary_json"
            artifact_paths = workbook_payload.get("artifact_paths")
            if not isinstance(artifact_paths, dict):
                artifact_paths = {}
            artifact_paths[artifact_key] = _relative_to(run_root, summary_path) or str(
                summary_path
            )
            workbook_payload["artifact_paths"] = artifact_paths
            workbook_payload["attention_summary"] = dict(
                summary_payload.get("attention_summary") or {}
            )
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
