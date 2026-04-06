from __future__ import annotations

from cookimport.llm.repair_recovery_policy import (
    INLINE_JSON_TRANSPORT,
    KNOWLEDGE_CLASSIFY_STEP_KEY,
    KNOWLEDGE_GROUP_STEP_KEY,
    KNOWLEDGE_POLICY_STAGE_KEY,
    LINE_ROLE_POLICY_STAGE_KEY,
    RECIPE_POLICY_STAGE_KEY,
    TASKFILE_TRANSPORT,
    get_stage_transport_policy,
    inline_repair_policy_summary,
    should_attempt_taskfile_fresh_session_retry,
    should_attempt_taskfile_fresh_worker_replacement,
    structured_repair_followup_limit,
    taskfile_recovery_policy_summary,
)


def test_policy_table_matches_current_stage_transport_matrix() -> None:
    assert taskfile_recovery_policy_summary(stage_key=RECIPE_POLICY_STAGE_KEY) == {
        "fresh_session_retry_limit": 1,
        "fresh_worker_replacement_limit": 1,
    }
    assert taskfile_recovery_policy_summary(stage_key=LINE_ROLE_POLICY_STAGE_KEY) == {
        "fresh_session_retry_limit": 1,
        "fresh_worker_replacement_limit": 1,
    }
    assert taskfile_recovery_policy_summary(stage_key=KNOWLEDGE_POLICY_STAGE_KEY) == {
        "fresh_session_retry_limit": 1,
        "fresh_worker_replacement_limit": 1,
    }
    assert inline_repair_policy_summary(stage_key=LINE_ROLE_POLICY_STAGE_KEY) == {
        "structured_repair_followup_limit": 1
    }
    assert inline_repair_policy_summary(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
    ) == {"structured_repair_followup_limit": 3}
    assert inline_repair_policy_summary(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
    ) == {"structured_repair_followup_limit": 3}


def test_policy_rows_are_step_specific_for_knowledge_inline() -> None:
    classify_policy = get_stage_transport_policy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
    )
    grouping_policy = get_stage_transport_policy(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
    )

    assert classify_policy.semantic_step_key == KNOWLEDGE_CLASSIFY_STEP_KEY
    assert grouping_policy.semantic_step_key == KNOWLEDGE_GROUP_STEP_KEY
    assert structured_repair_followup_limit(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
    ) == 3
    assert structured_repair_followup_limit(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
    ) == 3


def test_taskfile_retry_helper_uses_shared_budget_and_reason_taxonomy() -> None:
    assert should_attempt_taskfile_fresh_session_retry(
        stage_key=RECIPE_POLICY_STAGE_KEY,
        retry_attempt_count=0,
        same_session_completed=False,
        final_status=None,
        hard_boundary_failure=False,
        session_completed_successfully=True,
        useful_progress=True,
    ) == (True, "preserved_progress_without_completion")
    assert should_attempt_taskfile_fresh_session_retry(
        stage_key=LINE_ROLE_POLICY_STAGE_KEY,
        retry_attempt_count=1,
        same_session_completed=False,
        final_status=None,
        hard_boundary_failure=False,
        session_completed_successfully=True,
        useful_progress=True,
    ) == (False, "fresh_session_retry_budget_spent")
    assert should_attempt_taskfile_fresh_session_retry(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        retry_attempt_count=0,
        same_session_completed=False,
        final_status="repair_exhausted",
        hard_boundary_failure=False,
        session_completed_successfully=True,
        useful_progress=True,
    ) == (False, "same_session_repair_exhausted")


def test_taskfile_replacement_helper_uses_shared_budget_and_reason_taxonomy() -> None:
    assert should_attempt_taskfile_fresh_worker_replacement(
        stage_key=RECIPE_POLICY_STAGE_KEY,
        replacement_attempt_count=0,
        same_session_completed=False,
        retryable_exception_reason="codex_exec_timeout",
    ) == (True, "codex_exec_timeout")
    assert should_attempt_taskfile_fresh_worker_replacement(
        stage_key=LINE_ROLE_POLICY_STAGE_KEY,
        replacement_attempt_count=1,
        same_session_completed=False,
        catastrophic_run_result_reason="watchdog_boundary_violation",
    ) == (False, "fresh_worker_replacement_budget_spent")
    assert should_attempt_taskfile_fresh_worker_replacement(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        replacement_attempt_count=0,
        same_session_completed=True,
        catastrophic_run_result_reason="watchdog_killed",
    ) == (False, "same_session_already_completed")


def test_taskfile_and_inline_policy_rows_can_be_opened_directly() -> None:
    recipe_policy = get_stage_transport_policy(
        stage_key=RECIPE_POLICY_STAGE_KEY,
        transport=TASKFILE_TRANSPORT,
    )
    line_role_inline_policy = get_stage_transport_policy(
        stage_key=LINE_ROLE_POLICY_STAGE_KEY,
        transport=INLINE_JSON_TRANSPORT,
    )

    assert recipe_policy.stage_key == RECIPE_POLICY_STAGE_KEY
    assert recipe_policy.transport == TASKFILE_TRANSPORT
    assert line_role_inline_policy.stage_key == LINE_ROLE_POLICY_STAGE_KEY
    assert line_role_inline_policy.transport == INLINE_JSON_TRANSPORT
