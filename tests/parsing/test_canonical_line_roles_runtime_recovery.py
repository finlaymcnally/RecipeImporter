from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

@pytest.mark.parametrize(
    ("diagnosis_code", "recoverable", "summary"),
    [
        ("completed", False, "same-session helper already completed this workspace"),
        (
            "answers_present_helper_not_run",
            True,
            "task.json contains saved answers but the same-session helper has not produced out/<shard_id>.json yet",
        ),
        (
            "ready_for_validation",
            True,
            "answers are present and the same-session helper still needs to validate and install out/<shard_id>.json",
        ),
        (
            "repair_ready_helper_not_run",
            True,
            "repair answers are present but the same-session helper has not installed out/<shard_id>.json yet",
        ),
        ("awaiting_answers", False, "task.json still has blank answer objects"),
        (
            "repair_answers_missing",
            False,
            "repair mode is active but corrected answers are still missing",
        ),
        ("unknown_code", False, None),
    ],
)
def test_line_role_recovery_guidance_maps_diagnosis_codes(
    diagnosis_code: str,
    recoverable: bool,
    summary: str | None,
) -> None:
    assert _line_role_recovery_guidance_for_diagnosis(diagnosis_code) == (
        recoverable,
        summary,
    )


def test_line_role_runtime_retries_one_fresh_session_after_preserved_progress(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:fresh:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=None,
            rule_tags=[],
        )
        for index in range(2)
    ]
    runner = _FreshSessionLineRoleRunner()

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    phase_manifest = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert len(predictions) == 2
    assert runner.workspace_run_calls == 2
    assert worker_status["fresh_session_retry_count"] == 1
    assert worker_status["fresh_session_retry_status"] == "completed"
    assert worker_status["telemetry"]["summary"]["workspace_worker_session_count"] == 2
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 2
    )


def test_line_role_runtime_does_not_retry_after_hard_boundary_failure(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:hard:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _FreshSessionLineRoleRunner(hard_boundary=True)

    with pytest.raises(canonical_line_roles_module.LineRoleRepairFailureError):
        label_atomic_lines(
            candidates,
            _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=runner,
            live_llm_allowed=True,
        )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))

    assert runner.workspace_run_calls == 1
    assert worker_status["fresh_session_retry_count"] == 0


def test_line_role_runtime_recovers_after_final_message_missing_output(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:final-message:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=None,
            rule_tags=[],
        )
        for index in range(2)
    ]
    runner = _FinalMessageMissingOutputRunner(set_answers_before_exit=True)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    recovery_assessment = json.loads(
        (worker_root / "final_message_recovery_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    shard_status = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "shards"
            / "line-role-canonical-0001-a000000-a000001"
            / "status.json"
        ).read_text(encoding="utf-8")
    )

    assert len(predictions) == 2
    assert runner.workspace_run_calls == 2
    assert worker_status["fresh_session_retry_count"] == 1
    assert worker_status["fresh_session_retry_status"] == "completed"
    assert worker_status["fresh_session_recovery_attempted"] is True
    assert worker_status["fresh_session_recovery_status"] == "recovered"
    assert (
        recovery_assessment["prior_session_reason_code"]
        == "workspace_final_message_missing_output"
    )
    assert recovery_assessment["assessment"]["recoverable_by_fresh_session"] is True
    assert recovery_assessment["assessment"]["diagnosis_code"] == (
        "answers_present_helper_not_run"
    )
    assert recovery_assessment["fresh_session_recovery_status"] == "recovered"
    assert shard_status["watchdog_retry_status"] == "not_attempted"
    assert shard_status["fresh_session_recovery_status"] == "recovered"
    assert not list(worker_root.rglob("watchdog_retry_status.json"))


def test_line_role_runtime_recovers_after_incomplete_progress_summary_with_answers_file(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:progress-summary:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=None,
            rule_tags=[],
        )
        for index in range(2)
    ]
    runner = _ProgressSummaryAnswersFileRunner()

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    recovery_assessment = json.loads(
        (worker_root / "final_message_recovery_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    shard_status = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "shards"
            / "line-role-canonical-0001-a000000-a000001"
            / "status.json"
        ).read_text(encoding="utf-8")
    )

    assert len(predictions) == 2
    assert runner.workspace_run_calls == 2
    assert worker_status["fresh_session_retry_count"] == 1
    assert worker_status["fresh_session_retry_status"] == "completed"
    assert worker_status["fresh_session_recovery_attempted"] is True
    assert worker_status["fresh_session_recovery_status"] == "recovered"
    assert (
        recovery_assessment["prior_session_reason_code"]
        == "workspace_final_message_incomplete_progress"
    )
    assert recovery_assessment["assessment"]["recoverable_by_fresh_session"] is True
    assert recovery_assessment["assessment"]["diagnosis_code"] == (
        "answers_file_present_not_applied"
    )
    assert (
        recovery_assessment["answers_file_progress"]["has_useful_progress"] is True
    )
    assert recovery_assessment["fresh_session_recovery_status"] == "recovered"
    assert shard_status["watchdog_retry_status"] == "not_attempted"
    assert shard_status["fresh_session_recovery_status"] == "recovered"


def test_line_role_runtime_treats_authoritative_same_session_completion_as_clean_success(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:authoritative-complete:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _AuthoritativeCompletionRunner(emit_shell_drift=True)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_live_status = json.loads(
        (worker_root / "live_status.json").read_text(encoding="utf-8")
    )
    shard_status = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in worker_root.rglob("status.json")
        if "shards" in path.parts
    )
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(predictions) == 1
    assert runner.workspace_run_calls == 1
    assert worker_live_status["state"] == "completed_with_warnings"
    assert "single_file_shell_drift" in worker_live_status["warning_codes"]
    assert worker_live_status["reason_code"] in {None, ""}
    assert shard_status["finalization_path"] == "session_completed"
    assert shard_status["raw_supervision_reason_code"] is None
    assert telemetry_payload["summary"]["watchdog_recovered_shard_count"] == 0
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 0


def test_line_role_runtime_treats_helper_completed_visibility_lag_as_clean_success(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:helper-visibility-lag:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _HelperCompletionVisibilityLagRunner()

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_live_status = json.loads(
        (worker_root / "live_status.json").read_text(encoding="utf-8")
    )
    shard_status = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in worker_root.rglob("status.json")
        if "shards" in path.parts
    )
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(predictions) == 1
    assert runner.workspace_run_calls == 1
    assert worker_live_status["state"] == "completed"
    assert worker_live_status["reason_code"] in {None, ""}
    assert shard_status["finalization_path"] == "session_completed"
    assert shard_status["reason_code"] in {None, ""}
    assert shard_status["watchdog_retry_status"] == "not_attempted"
    assert shard_status.get("fresh_session_recovery_attempted") in {None, False}
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 0
    assert telemetry_payload["summary"]["watchdog_recovered_shard_count"] == 0


def test_line_role_runtime_overrides_missing_output_kill_when_assessment_proves_completion(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:override-complete:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _KilledAfterHelperCompletionRunner()

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_live_status = json.loads(
        (worker_root / "live_status.json").read_text(encoding="utf-8")
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    recovery_assessment = json.loads(
        (worker_root / "final_message_recovery_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    shard_status = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in worker_root.rglob("status.json")
        if "shards" in path.parts
    )
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(predictions) == 1
    assert runner.workspace_run_calls == 1
    assert worker_live_status["state"] == "completed"
    assert worker_live_status["reason_code"] in {None, ""}
    assert worker_status["fresh_session_recovery_status"] == "authoritative_completion"
    assert recovery_assessment["authoritative_completion_override_applied"] is True
    assert shard_status["finalization_path"] == "session_completed"
    assert shard_status["raw_supervision_reason_code"] is None
    assert shard_status["reason_code"] in {None, ""}
    assert telemetry_payload["summary"]["watchdog_recovered_shard_count"] == 0
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 0


def test_line_role_runtime_skips_final_message_recovery_when_answers_are_missing(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:missing-answers:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _FinalMessageMissingOutputRunner(set_answers_before_exit=False)

    with pytest.raises(canonical_line_roles_module.LineRoleRepairFailureError):
        label_atomic_lines(
            candidates,
            _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=runner,
            live_llm_allowed=True,
        )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    recovery_assessment = json.loads(
        (worker_root / "final_message_recovery_assessment.json").read_text(
            encoding="utf-8"
        )
    )

    assert runner.workspace_run_calls == 1
    assert worker_status["fresh_session_retry_count"] == 0
    assert worker_status["fresh_session_recovery_attempted"] is False
    assert worker_status["fresh_session_recovery_status"] == "skipped"
    assert worker_status["fresh_session_recovery_skipped_reason"] == (
        "diagnosis_awaiting_answers"
    )
    assert recovery_assessment["assessment"]["recoverable_by_fresh_session"] is False
    assert recovery_assessment["assessment"]["diagnosis_code"] == "awaiting_answers"


def test_line_role_runtime_skips_final_message_recovery_when_shared_budget_is_spent(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:budget-spent:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]
    runner = _FinalMessageMissingOutputRunner(
        set_answers_before_exit=True,
        spend_retry_budget=True,
    )

    with pytest.raises(canonical_line_roles_module.LineRoleRepairFailureError):
        label_atomic_lines(
            candidates,
            _settings("codex-line-role-route-v2", line_role_prompt_target_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=runner,
            live_llm_allowed=True,
        )

    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    recovery_assessment = json.loads(
        (worker_root / "final_message_recovery_assessment.json").read_text(
            encoding="utf-8"
        )
    )

    assert runner.workspace_run_calls == 1
    assert worker_status["fresh_session_retry_count"] == 0
    assert worker_status["fresh_session_recovery_status"] == "skipped"
    assert worker_status["fresh_session_recovery_skipped_reason"] == (
        "fresh_session_retry_budget_spent"
    )
    assert worker_status["shared_retry_budget_spent"] is True
    assert recovery_assessment["assessment"]["recoverable_by_fresh_session"] is False
    assert recovery_assessment["shared_retry_budget_spent"] is True
