from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

TASKFILE_TRANSPORT = "taskfile-v1"
INLINE_JSON_TRANSPORT = "inline-json-v1"

RECIPE_POLICY_STAGE_KEY = "recipe_refine"
LINE_ROLE_POLICY_STAGE_KEY = "line_role"
KNOWLEDGE_POLICY_STAGE_KEY = "knowledge"

KNOWLEDGE_CLASSIFY_STEP_KEY = "nonrecipe_classify"
KNOWLEDGE_GROUP_STEP_KEY = "knowledge_group"

FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE = "same_session_repair_rewrite"
FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP = "structured_repair_followup"
FOLLOWUP_KIND_FRESH_SESSION_RETRY = "fresh_session_retry"
FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT = "fresh_worker_replacement"
FOLLOWUP_KIND_WATCHDOG_RETRY = "watchdog_retry"

FOLLOWUP_SCOPE_WORKER_ASSIGNMENT = "worker_assignment"
FOLLOWUP_SCOPE_SEMANTIC_STEP = "semantic_step"
FOLLOWUP_SCOPE_SHARD_RESULT = "shard_result"


@dataclass(frozen=True)
class FollowupBudget:
    kind: str
    surface: str
    max_attempts: int
    scope: str


@dataclass(frozen=True)
class StageTransportPolicy:
    stage_key: str
    transport: str
    semantic_step_key: str | None
    allowed_followups: tuple[FollowupBudget, ...]


_POLICY_TABLE: dict[tuple[str, str, str | None], StageTransportPolicy] = {
    (
        RECIPE_POLICY_STAGE_KEY,
        INLINE_JSON_TRANSPORT,
        None,
    ): StageTransportPolicy(
        stage_key=RECIPE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=None,
        allowed_followups=(),
    ),
    (
        RECIPE_POLICY_STAGE_KEY,
        TASKFILE_TRANSPORT,
        None,
    ): StageTransportPolicy(
        stage_key=RECIPE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
        semantic_step_key=None,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
                surface="same_session_handoff",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_SESSION_RETRY,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
        ),
    ),
    (
        LINE_ROLE_POLICY_STAGE_KEY,
        TASKFILE_TRANSPORT,
        None,
    ): StageTransportPolicy(
        stage_key=LINE_ROLE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
        semantic_step_key=None,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
                surface="same_session_handoff",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_SESSION_RETRY,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
        ),
    ),
    (
        LINE_ROLE_POLICY_STAGE_KEY,
        INLINE_JSON_TRANSPORT,
        None,
    ): StageTransportPolicy(
        stage_key=LINE_ROLE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=None,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
                surface="structured_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_SHARD_RESULT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_WATCHDOG_RETRY,
                surface="structured_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_SHARD_RESULT,
            ),
        ),
    ),
    (
        KNOWLEDGE_POLICY_STAGE_KEY,
        TASKFILE_TRANSPORT,
        None,
    ): StageTransportPolicy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
        semantic_step_key=None,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_SESSION_RETRY,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
                surface="workspace_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_WORKER_ASSIGNMENT,
            ),
            FollowupBudget(
                kind=FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
                surface="structured_session",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_SHARD_RESULT,
            ),
        ),
    ),
    (
        KNOWLEDGE_POLICY_STAGE_KEY,
        TASKFILE_TRANSPORT,
        KNOWLEDGE_CLASSIFY_STEP_KEY,
    ): StageTransportPolicy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
                surface="same_session_handoff",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_SEMANTIC_STEP,
            ),
        ),
    ),
    (
        KNOWLEDGE_POLICY_STAGE_KEY,
        TASKFILE_TRANSPORT,
        KNOWLEDGE_GROUP_STEP_KEY,
    ): StageTransportPolicy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
                surface="same_session_handoff",
                max_attempts=1,
                scope=FOLLOWUP_SCOPE_SEMANTIC_STEP,
            ),
        ),
    ),
    (
        KNOWLEDGE_POLICY_STAGE_KEY,
        INLINE_JSON_TRANSPORT,
        KNOWLEDGE_CLASSIFY_STEP_KEY,
    ): StageTransportPolicy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
                surface="structured_session",
                max_attempts=3,
                scope=FOLLOWUP_SCOPE_SEMANTIC_STEP,
            ),
        ),
    ),
    (
        KNOWLEDGE_POLICY_STAGE_KEY,
        INLINE_JSON_TRANSPORT,
        KNOWLEDGE_GROUP_STEP_KEY,
    ): StageTransportPolicy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
        allowed_followups=(
            FollowupBudget(
                kind=FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
                surface="structured_session",
                max_attempts=3,
                scope=FOLLOWUP_SCOPE_SEMANTIC_STEP,
            ),
        ),
    ),
}


def get_stage_transport_policy(
    *,
    stage_key: str,
    transport: str,
    semantic_step_key: str | None = None,
) -> StageTransportPolicy:
    cleaned_stage_key = str(stage_key or "").strip()
    cleaned_transport = str(transport or "").strip()
    cleaned_step_key = str(semantic_step_key or "").strip() or None
    policy = _POLICY_TABLE.get((cleaned_stage_key, cleaned_transport, cleaned_step_key))
    if policy is not None:
        return policy
    if cleaned_step_key is not None:
        policy = _POLICY_TABLE.get((cleaned_stage_key, cleaned_transport, None))
        if policy is not None:
            return policy
    raise KeyError(
        f"no repair/recovery policy for stage={cleaned_stage_key!r} "
        f"transport={cleaned_transport!r} semantic_step={cleaned_step_key!r}"
    )


def get_followup_limit(
    *,
    stage_key: str,
    transport: str,
    kind: str,
    semantic_step_key: str | None = None,
) -> int:
    policy = get_stage_transport_policy(
        stage_key=stage_key,
        transport=transport,
        semantic_step_key=semantic_step_key,
    )
    cleaned_kind = str(kind or "").strip()
    for budget in policy.allowed_followups:
        if budget.kind == cleaned_kind:
            return int(budget.max_attempts)
    return 0


def taskfile_fresh_session_retry_limit(*, stage_key: str) -> int:
    return get_followup_limit(
        stage_key=stage_key,
        transport=TASKFILE_TRANSPORT,
        kind=FOLLOWUP_KIND_FRESH_SESSION_RETRY,
    )


def taskfile_fresh_worker_replacement_limit(*, stage_key: str) -> int:
    return get_followup_limit(
        stage_key=stage_key,
        transport=TASKFILE_TRANSPORT,
        kind=FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
    )


def taskfile_same_session_repair_rewrite_limit(
    *,
    stage_key: str,
    semantic_step_key: str | None = None,
) -> int:
    return get_followup_limit(
        stage_key=stage_key,
        transport=TASKFILE_TRANSPORT,
        kind=FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
        semantic_step_key=semantic_step_key,
    )


def structured_repair_followup_limit(
    *,
    stage_key: str,
    transport: str = INLINE_JSON_TRANSPORT,
    semantic_step_key: str | None = None,
) -> int:
    return get_followup_limit(
        stage_key=stage_key,
        transport=transport,
        kind=FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
        semantic_step_key=semantic_step_key,
    )


def taskfile_recovery_policy_summary(*, stage_key: str) -> dict[str, int]:
    return {
        "fresh_session_retry_limit": taskfile_fresh_session_retry_limit(
            stage_key=stage_key
        ),
        "fresh_worker_replacement_limit": taskfile_fresh_worker_replacement_limit(
            stage_key=stage_key
        ),
    }


def inline_repair_policy_summary(
    *,
    stage_key: str,
    semantic_step_key: str | None = None,
) -> dict[str, int]:
    return {
        "structured_repair_followup_limit": structured_repair_followup_limit(
            stage_key=stage_key,
            semantic_step_key=semantic_step_key,
        )
    }


def taskfile_structured_repair_policy_summary(
    *,
    stage_key: str,
    semantic_step_key: str | None = None,
) -> dict[str, int]:
    return {
        "structured_repair_followup_limit": structured_repair_followup_limit(
            stage_key=stage_key,
            transport=TASKFILE_TRANSPORT,
            semantic_step_key=semantic_step_key,
        )
    }


def build_followup_budget_summary(
    *,
    stage_key: str,
    transport: str,
    semantic_step_key: str | None = None,
    spent_attempts_by_kind: Mapping[str, Any] | None = None,
    allowed_attempts_multiplier_by_kind: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = get_stage_transport_policy(
        stage_key=stage_key,
        transport=transport,
        semantic_step_key=semantic_step_key,
    )
    spent_counts = (
        dict(spent_attempts_by_kind) if isinstance(spent_attempts_by_kind, Mapping) else {}
    )
    allowed_attempts_multipliers = (
        dict(allowed_attempts_multiplier_by_kind)
        if isinstance(allowed_attempts_multiplier_by_kind, Mapping)
        else {}
    )
    budgets: dict[str, dict[str, Any]] = {}
    for budget in policy.allowed_followups:
        spent_attempts = max(0, int(spent_counts.get(budget.kind) or 0))
        allowed_attempts = max(0, int(budget.max_attempts))
        multiplier_value = allowed_attempts_multipliers.get(budget.kind)
        allowed_attempts *= (
            max(0, int(multiplier_value or 0))
            if multiplier_value is not None
            else 1
        )
        budgets[budget.kind] = {
            "followup_kind": budget.kind,
            "followup_surface": budget.surface,
            "budget_scope": budget.scope,
            "allowed_attempts": allowed_attempts,
            "spent_attempts": spent_attempts,
            "remaining_attempts": max(allowed_attempts - spent_attempts, 0),
        }
    return {
        "stage_key": policy.stage_key,
        "transport": policy.transport,
        "semantic_step_key": policy.semantic_step_key,
        "budgets": budgets,
    }


def should_attempt_taskfile_fresh_worker_replacement(
    *,
    stage_key: str,
    replacement_attempt_count: int,
    same_session_completed: bool,
    retryable_exception_reason: str | None = None,
    catastrophic_run_result_reason: str | None = None,
) -> tuple[bool, str]:
    replacement_limit = taskfile_fresh_worker_replacement_limit(stage_key=stage_key)
    if int(replacement_attempt_count) >= replacement_limit:
        return False, "fresh_worker_replacement_budget_spent"
    if bool(same_session_completed):
        return False, "same_session_already_completed"
    cleaned_exception_reason = str(retryable_exception_reason or "").strip()
    if cleaned_exception_reason:
        return True, cleaned_exception_reason
    cleaned_run_result_reason = str(catastrophic_run_result_reason or "").strip()
    if cleaned_run_result_reason:
        return True, cleaned_run_result_reason
    if retryable_exception_reason is not None:
        return False, "runner_exception_not_retryable"
    if catastrophic_run_result_reason is not None:
        return False, "worker_session_not_catastrophic"
    return False, "fresh_worker_replacement_not_applicable"


def should_attempt_taskfile_fresh_session_retry(
    *,
    stage_key: str,
    retry_attempt_count: int,
    same_session_completed: bool,
    final_status: str | None,
    hard_boundary_failure: bool,
    session_completed_successfully: bool,
    useful_progress: bool,
) -> tuple[bool, str]:
    retry_limit = taskfile_fresh_session_retry_limit(stage_key=stage_key)
    if retry_limit <= int(retry_attempt_count):
        return False, "fresh_session_retry_budget_spent"
    if bool(same_session_completed):
        return False, "same_session_already_completed"
    if str(final_status or "").strip() == "repair_exhausted":
        return False, "same_session_repair_exhausted"
    if bool(hard_boundary_failure):
        return False, "hard_boundary_failure"
    if not bool(session_completed_successfully):
        return False, "worker_session_not_clean"
    if not bool(useful_progress):
        return False, "no_preserved_progress"
    return True, "preserved_progress_without_completion"
