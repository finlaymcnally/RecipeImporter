from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_label_atomic_lines_records_cohort_outlier_as_warning_not_retry(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
        10,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
        2.0,
    )
    cohort_state = canonical_line_roles_module._LineRoleCohortWatchdogState()  # noqa: SLF001
    for _ in range(3):
        cohort_state.record_validated_result(duration_ms=20, example_payload={"rows": []})
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        cohort_watchdog_state=cohort_state,
    )

    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.05,
            event_count=4,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "running_with_warnings"
    assert live_status["warning_codes"] == ["cohort_runtime_outlier"]
    assert live_status["reason_code"] is None


def test_label_atomic_lines_persists_cohort_outlier_warning_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
        10,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
        2.0,
    )
    cohort_state = canonical_line_roles_module._LineRoleCohortWatchdogState()  # noqa: SLF001
    for _ in range(3):
        cohort_state.record_validated_result(duration_ms=20, example_payload={"rows": []})
    live_status_path = tmp_path / "live_status.json"
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=live_status_path,
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        cohort_watchdog_state=cohort_state,
    )
    callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.05,
            event_count=4,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    canonical_line_roles_module._finalize_live_status(  # noqa: SLF001
        live_status_path,
        run_result=CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text="",
            response_text='{"status":"worker_completed"}',
            turn_failed_message=None,
            usage={"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
            source_working_dir=str(tmp_path),
            execution_working_dir=str(tmp_path),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="taskfile",
            supervision_state="completed",
        ),
        watchdog_policy="taskfile_v1",
    )

    warning_live_status = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert warning_live_status["state"] == "completed_with_warnings"
    assert warning_live_status["warning_codes"] == ["cohort_runtime_outlier"]


def test_label_atomic_lines_keeps_unrecovered_boundary_interrupt_visible(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:forbidden:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _ForbiddenWorkspaceRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=None,
                turn_failed_message="taskfile worker stage attempted forbidden tool use",
                events=(),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                source_working_dir=str(kwargs.get("working_dir")),
                execution_working_dir=str(kwargs.get("working_dir")),
                execution_agents_path=None,
                duration_ms=50,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                supervision_state="boundary_interrupted",
                supervision_reason_code="boundary_command_execution_forbidden",
                supervision_reason_detail=(
                    "taskfile worker stage attempted tool use: /bin/bash -lc 'pip install foo'"
                ),
                supervision_retryable=False,
            )

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_runner=_ForbiddenWorkspaceRunner(
                output_builder=lambda payload: {"rows": []}
            ),
            live_llm_allowed=True,
        )

    telemetry_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "telemetry.json"
        ).read_text(encoding="utf-8")
    )
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 0
    assert telemetry_payload["summary"]["watchdog_recovered_shard_count"] == 0

    status_path = next(
        path
        for path in (tmp_path / "line-role-pipeline" / "runtime").rglob("status.json")
        if "shards" in path.parts
    )
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["state"] == "boundary_interrupted"
    assert status_payload["reason_code"] == "boundary_command_execution_forbidden"
    assert status_payload["watchdog_retry_status"] == "not_attempted"


def test_label_atomic_lines_accepts_valid_workspace_outputs_without_final_message(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:authoritative:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    runner = _NoFinalWorkspaceMessageRunner(
        output_builder=lambda payload: {"rows": [{"atomic_index": 0, "label": "RECIPE_NOTES"}]}
    )

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"

    proposal_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "proposals").glob(
            "*.json"
        )
    )
    proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal_payload["validation_errors"] == []
    assert proposal_payload["repair_attempted"] is False

    worker_status_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "workers").rglob(
            "status.json"
        )
    )
    worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
    rows = worker_status["telemetry"]["rows"]
    assert rows
    assert rows[0]["final_agent_message_state"] == "absent"
    assert rows[0]["final_agent_message_reason"] is None


def test_label_atomic_lines_writes_live_phase_plan_artifacts(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:phase-plan:0",
            block_index=0,
            atomic_index=0,
            text="Bright Cabbage Slaw",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"

    phase_plan_path = (
        tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "phase_plan.json"
    )
    phase_plan_summary_path = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "phase_plan_summary.json"
    )
    phase_manifest_path = (
        tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "phase_manifest.json"
    )

    assert phase_plan_path.exists()
    assert phase_plan_summary_path.exists()

    phase_plan = json.loads(phase_plan_path.read_text(encoding="utf-8"))
    phase_manifest = json.loads(phase_manifest_path.read_text(encoding="utf-8"))

    assert phase_plan["stage_key"] == "line_role"
    assert phase_plan["requested_shard_count"] == 1
    assert phase_plan["budget_native_shard_count"] == 1
    assert phase_plan["launch_shard_count"] == 1
    assert phase_plan["work_unit_label"] == "lines"
    assert phase_plan["work_unit_count"] == 1
    assert phase_plan["shards"][0]["work_unit_count"] == 1
    assert phase_manifest["runtime_metadata"]["phase_plan_path"].endswith("phase_plan.json")
    assert phase_manifest["runtime_metadata"]["phase_plan_summary_path"].endswith(
        "phase_plan_summary.json"
    )


def test_label_atomic_lines_near_miss_invalid_task_file_edit_fails_closed_without_second_model_pass(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:repair:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _missing_answer_builder(payload):
        edited = dict(payload or {})
        units = list(edited.get("units") or [])
        if units and isinstance(units[0], dict):
            first_unit = dict(units[0])
            first_unit["answer"] = {}
            units[0] = first_unit
        edited["units"] = units
        return edited

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_runner=FakeCodexExecRunner(output_builder=_missing_answer_builder),
            live_llm_allowed=True,
        )

    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["attempt_count"] == 1
    assert telemetry_payload["summary"]["repaired_shard_count"] == 0
    assert telemetry_payload["phases"][0]["runtime_artifacts"]["invalid_shard_count"] == 1

    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["repair_attempted"] is True
    assert proposal_payload["repair_status"] == "failed"
    assert proposal_payload["validation_errors"] == ["invalid_label:0:"]
    assert list((tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json"))

    runtime_telemetry = json.loads(
        (
            tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "telemetry.json"
        ).read_text(encoding="utf-8")
    )
    workspace_rows = [
        row
        for row in runtime_telemetry["rows"]
        if row.get("prompt_input_mode") == "taskfile"
    ]
    assert workspace_rows
    assert workspace_rows[0]["proposal_status"] == "invalid"
    assert workspace_rows[0]["final_proposal_status"] == "invalid"


def test_label_atomic_lines_fails_closed_when_task_file_missing_even_if_worker_leaves_stale_work_dir(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:work-ledger:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    class _WorkOnlyRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs):  # noqa: ANN003
            result = super().run_taskfile_worker(**kwargs)
            worker_root = Path(kwargs["working_dir"])
            (worker_root / "task.json").unlink()
            work_dir = worker_root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "stale.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {"atomic_index": 0, "label": "INGREDIENT_LINE"},
                            {"atomic_index": 999, "label": "RECIPE_NOTES"},
                        ]
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return result

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_batch_size=2,
            codex_runner=_WorkOnlyRunner(
                output_builder=lambda _payload: {
                    "rows": [
                        {"atomic_index": 0, "label": "RECIPE_NOTES"},
                        {"atomic_index": 1, "label": "RECIPE_NOTES"},
                    ]
                }
            ),
            live_llm_allowed=True,
        )

    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000001.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["repair_attempted"] is False
    assert proposal_payload["repair_status"] == "not_needed"
    assert proposal_payload["validation_errors"] == ["missing_output_file"]
    assert proposal_payload["validation_metadata"]["raw_output_missing"] is True


def test_label_atomic_lines_fails_closed_when_task_file_missing_without_helper_ledgers(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:seed-only:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _NoOutputRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs):  # noqa: ANN003
            result = super().run_taskfile_worker(**kwargs)
            worker_root = Path(kwargs["working_dir"])
            (worker_root / "task.json").unlink()
            return result

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_runner=_NoOutputRunner(
                output_builder=lambda _payload: {
                    "rows": [{"atomic_index": 0, "label": "INGREDIENT_LINE"}]
                }
            ),
            live_llm_allowed=True,
        )
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == ["missing_output_file"]
    assert proposal_payload["validation_metadata"]["raw_output_missing"] is True


def test_label_atomic_lines_ignores_stale_repair_request_when_task_file_missing(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:repair-success:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous repair success line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    class _StaleRepairRequestRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs):  # noqa: ANN003
            result = super().run_taskfile_worker(**kwargs)
            worker_root = Path(kwargs["working_dir"])
            (worker_root / "task.json").unlink()
            repair_dir = worker_root / "repair"
            repair_dir.mkdir(parents=True, exist_ok=True)
            (repair_dir / "line-role-canonical-0001-a000000-a000001.json").write_text(
                json.dumps(
                    {
                        "frozen_rows": [
                            {"atomic_index": 0, "label": "RECIPE_NOTES"},
                            {"atomic_index": 1, "label": "RECIPE_NOTES"},
                        ]
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return result

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_batch_size=2,
            codex_runner=_StaleRepairRequestRunner(
                output_builder=lambda _payload: {
                    "rows": [
                        {"atomic_index": 0, "label": "RECIPE_NOTES"},
                        {"atomic_index": 1, "label": "RECIPE_NOTES"},
                    ]
                }
            ),
            live_llm_allowed=True,
        )

    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000001.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["repair_attempted"] is False
    assert proposal_payload["repair_status"] == "not_needed"
    assert proposal_payload["validation_errors"] == ["missing_output_file"]
    assert proposal_payload["validation_metadata"]["raw_output_missing"] is True
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["repaired_shard_count"] == 0
    shard_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert shard_status_rows[0]["state"] == "invalid_output"
    repair_status_payload = json.loads(
        next((tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json")).read_text(
            encoding="utf-8"
        )
    )
    assert repair_status_payload["status"] == "not_needed"
    assert repair_status_payload["repair_request_path"] is not None


def test_label_atomic_lines_ignores_stale_repair_state_file_when_task_file_missing(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:repair-failure:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous repair failure line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    class _RepairStateOnlyRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs):  # noqa: ANN003
            result = super().run_taskfile_worker(**kwargs)
            worker_root = Path(kwargs["working_dir"])
            (worker_root / "task.json").unlink()
            repair_dir = worker_root / "repair"
            repair_dir.mkdir(parents=True, exist_ok=True)
            (
                repair_dir / "line-role-canonical-0001-a000000-a000001.status.json"
            ).write_text(
                json.dumps(
                    {
                        "status": "repair_requested",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return result

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_batch_size=2,
            codex_runner=_RepairStateOnlyRunner(
                output_builder=lambda _payload: {
                    "rows": [
                        {"atomic_index": 0, "label": "RECIPE_NOTES"},
                        {"atomic_index": 1, "label": "RECIPE_NOTES"},
                    ]
                }
            ),
            live_llm_allowed=True,
        )

    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000001.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["repair_attempted"] is False
    assert proposal_payload["repair_status"] == "not_needed"
    assert proposal_payload["payload"] is None
    assert proposal_payload["validation_errors"] == ["missing_output_file"]
    assert proposal_payload["validation_metadata"]["raw_output_missing"] is True
    shard_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert shard_status_rows[0]["state"] == "invalid_output"
    repair_status_payload = json.loads(
        next((tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json")).read_text(
            encoding="utf-8"
        )
    )
    assert repair_status_payload["status"] == "not_needed"
    assert repair_status_payload["repair_state_path"] is not None


def test_label_atomic_lines_rejects_uniform_shard_output_and_fails_closed(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:0",
            block_index=0,
            atomic_index=0,
            text="SERVES 4",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:1",
            block_index=1,
            atomic_index=1,
            text="1 cup flour",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:2",
            block_index=2,
            atomic_index=2,
            text="Stir until smooth.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:3",
            block_index=3,
            atomic_index=3,
            text="NOTE: Keep warm.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]
    def _output_builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        return {
            "rows": [
                {"atomic_index": int(row[0]), "label": "INGREDIENT_LINE"}
                for row in rows
            ]
        }

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=FakeCodexExecRunner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "INGREDIENT_LINE",
        "INGREDIENT_LINE",
        "INGREDIENT_LINE",
        "INGREDIENT_LINE",
    ]

    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["attempt_count"] == 1

    proposal_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "proposals").glob(
            "*.json"
        )
    )
    proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal_payload["repair_attempted"] is False
    assert proposal_payload["validation_errors"] == []
    assert proposal_payload["validation_metadata"]["row_resolution"]["unresolved_row_count"] == 0


def test_validate_line_role_payload_semantics_reports_uniform_diagnostic_against_diverse_baseline() -> None:
    baseline = {
        0: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b0",
            block_index=0,
            atomic_index=0,
            text="A",
            within_recipe_span=True,
            label="INGREDIENT_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
        1: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b1",
            block_index=1,
            atomic_index=1,
            text="B",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
        2: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b2",
            block_index=2,
            atomic_index=2,
            text="C",
            within_recipe_span=True,
            label="RECIPE_NOTES",
            decided_by="rule",
            reason_tags=[],
        ),
        3: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b3",
            block_index=3,
            atomic_index=3,
            text="D",
            within_recipe_span=True,
            label="YIELD_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
    }

    semantic_errors, semantic_metadata = canonical_line_roles_module._validate_line_role_payload_semantics(  # noqa: SLF001
        payload={
            "rows": [
                {"atomic_index": 0, "label": "INGREDIENT_LINE"},
                {"atomic_index": 1, "label": "INGREDIENT_LINE"},
                {"atomic_index": 2, "label": "INGREDIENT_LINE"},
                {"atomic_index": 3, "label": "INGREDIENT_LINE"},
            ]
        },
        shard=ShardManifestEntryV1(
            shard_id="semantic-guard-fixture",
            owned_ids=("0", "1", "2", "3"),
            input_payload={"rows": [[0, "A"], [1, "B"], [2, "C"], [3, "D"]]},
        ),
        deterministic_baseline_by_atomic_index=baseline,
    )

    assert semantic_metadata["guard_applied"] is True
    assert semantic_metadata["semantic_profile"]["outside_recipe_only"] is False
    assert semantic_metadata["semantic_response_label_counts"] == {"INGREDIENT_LINE": 4}
    assert semantic_errors == ()


def test_label_atomic_lines_invalid_task_file_ledgers_fail_closed_without_structured_repair(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:repair-task:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous repair line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(4)
    ]

    def _blank_answers_builder(payload):
        edited = dict(payload or {})
        units = []
        for unit in edited.get("units") or []:
            if not isinstance(unit, dict):
                continue
            unit_payload = dict(unit)
            unit_payload["answer"] = {}
            units.append(unit_payload)
        edited["units"] = units
        return edited

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_prompt_target_count=1,
                line_role_worker_count=1,
            ),
            artifact_root=tmp_path,
            codex_batch_size=4,
            codex_runner=FakeCodexExecRunner(output_builder=_blank_answers_builder),
            live_llm_allowed=True,
        )

    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000003.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["repair_attempted"] is True
    assert proposal_payload["repair_status"] == "failed"
    assert proposal_payload["validation_errors"] == [
        "invalid_label:0:",
        "invalid_label:1:",
        "invalid_label:2:",
        "invalid_label:3:",
    ]
    assert proposal_payload["validation_metadata"]["row_resolution"]["unresolved_row_count"] == 4
    assert list((tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json"))


def test_label_atomic_lines_codex_cache_reuses_across_runtime_only_setting_changes(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:runtime",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    runner = _line_role_runner({0: "RECIPE_NOTES"})
    first = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", workers=1, codex_farm_cmd="codex-a"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=runner,
        live_llm_allowed=True,
    )
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "taskfile"
    assert runner.calls[0]["output_schema_path"] is None
    assert first[0].decided_by == "codex"
    second = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", workers=9, codex_farm_cmd="codex-b"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert second[0].label == first[0].label


def test_label_atomic_lines_inline_json_repairs_in_place(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:structured:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _StructuredRepairRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(output_builder=self._build_output)

        def _build_output(self, payload):  # noqa: ANN001
            rows = payload.get("rows") if isinstance(payload, dict) else []
            structured_packet_rows = (
                payload.get("structured_packet_rows") if isinstance(payload, dict) else []
            )
            atomic_indices: list[int] = []
            row_ids: list[str] = []
            for row in rows:
                if isinstance(row, dict) and row.get("atomic_index") is not None:
                    atomic_indices.append(int(row.get("atomic_index")))
                elif isinstance(row, (list, tuple)) and row:
                    atomic_indices.append(int(row[0]))
            for row in structured_packet_rows or []:
                if isinstance(row, dict) and str(row.get("row_id") or "").strip():
                    row_ids.append(str(row.get("row_id")))
            label = "NOT_A_REAL_LABEL" if len(self.calls) == 1 else "RECIPE_NOTES"
            return {
                "rows": [
                    {"row_id": row_ids[index], "label": label}
                    for index, _atomic_index in enumerate(atomic_indices)
                    if index < len(row_ids)
                ]
            }

    runner = _StructuredRepairRunner()
    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
            line_role_codex_exec_style="inline-json-v1",
        ),
        artifact_root=tmp_path,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert [call["mode"] for call in runner.calls] == [
        "structured_prompt",
        "structured_prompt_resume",
    ]


def test_label_atomic_lines_inline_json_prompt_avoids_literal_example_copy_failure(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:structured:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Front matter line {index}",
            within_recipe_span=False,
            rule_tags=["front_matter_navigation"],
        )
        for index in range(3)
    ]

    class _LiteralExampleCopyRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(output_builder=self._build_output)

        def _build_output(self, payload):  # noqa: ANN001
            prompt_text = str(self.calls[-1].get("prompt_text") or "")
            if (
                '{"rows":[{"row_id":"r01","label":"RECIPE_NOTES"},'
                '{"row_id":"r02","label":"NONRECIPE_EXCLUDE"}]}'
                in prompt_text
            ):
                return {
                    "rows": [
                        {"row_id": "r01", "label": "RECIPE_NOTES"},
                        {"row_id": "r02", "label": "NONRECIPE_EXCLUDE"},
                    ]
                }
            structured_packet_rows = (
                payload.get("structured_packet_rows") if isinstance(payload, dict) else []
            )
            return {
                "rows": [
                    {
                        "row_id": str(row.get("row_id")),
                        "label": "NONRECIPE_EXCLUDE",
                    }
                    for row in structured_packet_rows or []
                    if isinstance(row, dict) and str(row.get("row_id") or "").strip()
                ]
            }

    runner = _LiteralExampleCopyRunner()
    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
            line_role_codex_exec_style="inline-json-v1",
        ),
        artifact_root=tmp_path,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]
    assert [call["mode"] for call in runner.calls] == ["structured_prompt"]
    assert runner.calls[0]["persist_session"] is True
    assert runner.calls[0]["resume_last"] is False

    lineage_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "workers").rglob(
            "session_lineage.json"
        )
    )
    lineage_payload = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert lineage_payload["turn_count"] == 1
    assert [turn["turn_kind"] for turn in lineage_payload["turns"]] == ["initial"]


def test_line_role_cache_path_changes_when_line_role_pipeline_changes(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:path",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    off_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("off"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )
    codex_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("codex-line-role-route-v2"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )

    assert off_path is not None
    assert codex_path is not None
    assert off_path != codex_path


def test_label_atomic_lines_codex_shards_keep_deterministic_output_order(
    tmp_path,
) -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(4):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:parallel:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES", 3: "RECIPE_NOTES"}),
        live_llm_allowed=True,
    )
    assert [row.atomic_index for row in predictions] == [0, 1, 2, 3]
    assert all(row.label == "RECIPE_NOTES" for row in predictions)

    prompt_dir = tmp_path / "line-role-pipeline" / "prompts"
    dedup_lines = (
        prompt_dir / "line_role" / "codex_prompt_log.dedup.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert len(dedup_lines) == 4
    assert all("\tline_role_prompt_" in line for line in dedup_lines)


def _run_single_prompt_surface_fixture(tmp_path: Path) -> dict[str, object]:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:compact:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )
    return {
        "predictions": predictions,
        "prompt_root": tmp_path / "line-role-pipeline",
    }


def test_label_atomic_lines_uses_single_line_role_prompt_surface(tmp_path) -> None:
    fixture = _run_single_prompt_surface_fixture(tmp_path)
    predictions = fixture["predictions"]
    prompt_root = fixture["prompt_root"]
    assert isinstance(prompt_root, Path)

    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    prompt_text = (
        prompt_root
        / "prompts"
        / "line_role"
        / "line_role_prompt_0001.txt"
    ).read_text(encoding="utf-8")
    assert "You are processing canonical line-role shards inside one local worker workspace. Each shard owns one ordered row ledger." in prompt_text
    assert "Open `task.json` directly" in prompt_text
    assert "`task.json` already contains the full assignment." in prompt_text
    assert "Title, variant, yield, and section calls are sequence-sensitive." in prompt_text
    assert "read the nearby rows directly in the ordered `task.json` ledger" in prompt_text
    assert "`task-show-unit <unit_id>` and `task-show-unanswered --limit 5` exist as fallback-only helpers." in prompt_text
    assert "Ordinary local reads of `task.json` and `AGENTS.md` are allowed." in prompt_text
    assert "If you briefly reread part of the file or make a small local false start" in prompt_text
    assert "Stay inside this workspace" in prompt_text
    assert "The task file already contains the immutable row evidence and the editable answer slots." in prompt_text
    assert "Do not modify immutable evidence fields." in prompt_text
    assert "`HOWTO_SECTION` is book-optional" in prompt_text
    assert "Balancing Fat" in prompt_text
    worker_prompt_text = (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "shards"
        / "line-role-canonical-0001-a000000-a000000"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert "You are processing canonical line-role shards inside one local worker workspace. Each shard owns one ordered row ledger." in worker_prompt_text
    assert "task.json" in worker_prompt_text
    assert "assigned_shards.json" not in worker_prompt_text


def test_label_atomic_lines_workspace_manifest_matches_current_contract(
    tmp_path,
) -> None:
    fixture = _run_single_prompt_surface_fixture(tmp_path)
    prompt_root = fixture["prompt_root"]
    assert isinstance(prompt_root, Path)

    worker_manifest_payload = json.loads(
        (
            prompt_root
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "worker_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert worker_manifest_payload["entry_files"] == ["task.json"]
    assert worker_manifest_payload["single_file_worker_runtime"] is True
    assert worker_manifest_payload["current_phase_file"] is None
    assert worker_manifest_payload["current_phase_brief_file"] is None
    assert worker_manifest_payload["current_phase_feedback_file"] is None
    assert worker_manifest_payload["output_contract_file"] is None
    assert worker_manifest_payload["examples_dir"] is None
    assert worker_manifest_payload["tools_dir"] is None
    assert worker_manifest_payload["hints_dir"] is None
    assert worker_manifest_payload["input_dir"] is None
    assert worker_manifest_payload["output_dir"] is None
    assert worker_manifest_payload["scratch_dir"] is None
    assert worker_manifest_payload["work_dir"] is None
    assert worker_manifest_payload["repair_dir"] is None
    assert worker_manifest_payload["task_file"] == "task.json"
    assert worker_manifest_payload["mirrored_example_files"] == []
    assert worker_manifest_payload["mirrored_tool_files"] == []
    assert worker_manifest_payload["mirrored_scratch_files"] == []
    assert (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "_repo_control"
        / "original_task.json"
    ).exists()
    task_file_payload = load_task_file(
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "task.json"
    )
    assert task_file_payload["stage_key"] == "line_role"
    assert task_file_payload["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert "helper_commands" not in task_file_payload
    assert task_file_payload["units"][0]["evidence"] == {
        "shard_id": "line-role-canonical-0001-a000000-a000000",
        "row_id": "r01",
        "text": "Ambiguous line 0",
    }
    assigned_shards_payload = json.loads(
        (
            prompt_root
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "assigned_shards.json"
        ).read_text(encoding="utf-8")
    )
    assert assigned_shards_payload[0]["metadata"]["input_path"].startswith("in/")
    assert assigned_shards_payload[0]["metadata"]["hint_path"].startswith("hints/")
    assert assigned_shards_payload[0]["metadata"]["result_path"].startswith("out/")
    assert assigned_shards_payload[0]["metadata"]["owned_row_count"] == 1
    assert assigned_shards_payload[0]["metadata"]["atomic_index_start"] == 0
    assert assigned_shards_payload[0]["metadata"]["atomic_index_end"] == 0


def test_label_atomic_lines_workspace_mirrors_hint_and_input_artifacts(
    tmp_path,
) -> None:
    fixture = _run_single_prompt_surface_fixture(tmp_path)
    prompt_root = fixture["prompt_root"]
    assert isinstance(prompt_root, Path)

    worker_hint_text = (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "hints"
        / "line-role-canonical-0001-a000000-a000000.md"
    ).read_text(encoding="utf-8")
    assert "Static reminders" in worker_hint_text
    assert "Focus" in worker_hint_text
    assert "There is no deterministic answer key in this workspace." in worker_hint_text
    assert "Obvious praise blurbs, foreword/preface setup, manifesto or `this book will teach you` framing" in worker_hint_text
    assert "`endorsement`, `publisher_promo`, or `front_matter`" in worker_hint_text
    worker_input_text = (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "in"
        / "line-role-canonical-0001-a000000-a000000.json"
    ).read_text(encoding="utf-8")
    worker_input_payload = json.loads(worker_input_text)
    assert set(worker_input_payload) == {"v", "shard_id", "rows"}
    assert worker_input_payload["rows"] == [[0, "Ambiguous line 0"]]
    input_payload = json.loads(
        (
            prompt_root
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "in"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    debug_payload = json.loads(
        (
            prompt_root
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "debug"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert input_payload["rows"][0][1] == "Ambiguous line 0"
    assert debug_payload["rows"][0]["current_line"] == "Ambiguous line 0"
    assert "prev_text" not in debug_payload["rows"][0]
    assert "next_text" not in debug_payload["rows"][0]
    assert not (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "OUTPUT_CONTRACT.md"
    ).exists()
    assert not (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "examples"
    ).exists()
    assert not (
        prompt_root
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "tools"
    ).exists()


def test_label_atomic_lines_writes_one_shard_owned_ledger_without_line_role_tasks(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:task:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=None,
            rule_tags=[],
        )
        for index in range(4)
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_prompt_target_count=1,
        ),
        artifact_root=tmp_path,
        codex_batch_size=4,
        codex_runner=_line_role_runner({index: "NONRECIPE_CANDIDATE" for index in range(4)}),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == ["NONRECIPE_CANDIDATE"] * 4
    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    assert not (worker_root / "assigned_tasks.json").exists()
    task_file_payload = load_task_file(worker_root / "task.json")
    assert task_file_payload["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert "helper_commands" not in task_file_payload
    assert task_file_payload["answer_schema"]["example_answers"][0]["label"] == "RECIPE_NOTES"
    assert all(
        set(unit["evidence"]) == {
            "shard_id",
            "row_id",
            "text",
        }
        for unit in task_file_payload["units"]
    )
    assigned_shards = json.loads(
        (worker_root / "assigned_shards.json").read_text(encoding="utf-8")
    )
    assert [row["shard_id"] for row in assigned_shards] == [
        "line-role-canonical-0001-a000000-a000003"
    ]
    assert assigned_shards[0]["metadata"]["owned_row_count"] == 4
    assert sorted(path.name for path in (worker_root / "out").glob("*.json")) == [
        "line-role-canonical-0001-a000000-a000003.json",
    ]
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000003.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == []
    assert len(proposal_payload["payload"]["rows"]) == 4
    assert proposal_payload["validation_metadata"]["row_resolution"]["unresolved_row_count"] == 0


def test_label_atomic_lines_writes_canonical_line_table_and_shard_status(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:line-table:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Line {index}",
            within_recipe_span=bool(index == 0),
            rule_tags=["recipe_span_fallback"] if index == 0 else [],
        )
        for index in range(2)
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_worker_count=1,
            line_role_prompt_target_count=1,
        ),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=_line_role_runner({0: "RECIPE_NOTES", 1: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == ["RECIPE_NOTES", "NONRECIPE_CANDIDATE"]
    runtime_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    line_table_rows = [
        json.loads(line)
        for line in (runtime_root / "canonical_line_table.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["line_id"] for row in line_table_rows] == ["0", "1"]
    assert [row["current_line"] for row in line_table_rows] == ["Line 0", "Line 1"]
    shard_status_rows = [
        json.loads(line)
        for line in (runtime_root / "shard_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(row["state"] == "validated" for row in shard_status_rows)
    assert sum(row["metadata"]["llm_authoritative_row_count"] for row in shard_status_rows) == 2
    assert sum(row["metadata"]["unresolved_row_count"] for row in shard_status_rows) == 0


def test_label_atomic_lines_resume_existing_valid_shard_outputs_without_rerunning_worker(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:resume:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Resume line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    first_runner = _line_role_runner({0: "RECIPE_NOTES", 1: "RECIPE_NOTES"})
    first_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=first_runner,
        live_llm_allowed=True,
    )
    assert [prediction.label for prediction in first_predictions] == ["RECIPE_NOTES", "RECIPE_NOTES"]
    assert any(call["mode"] == "taskfile" for call in first_runner.calls)

    second_runner = _line_role_runner({0: "RECIPE_TITLE", 1: "RECIPE_TITLE"})
    second_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=second_runner,
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in second_predictions] == ["RECIPE_NOTES", "RECIPE_NOTES"]
    assert second_runner.calls == []
    shard_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert shard_status_rows[0]["last_attempt_type"] == "resume_existing_output"
    assert shard_status_rows[0]["metadata"]["resumed_from_existing_output"] is True


def test_line_role_taskfile_worker_invalid_task_file_answer_fails_closed_without_promoting_it(
    tmp_path,
) -> None:
    def _invalid_task_file_builder(payload):
        edited = dict(payload or {})
        units = edited.get("units") or []
        if units and isinstance(units[0], dict):
            first_unit = dict(units[0])
            first_unit["answer"] = {"label": "NOT_A_LABEL"}
            units = [first_unit, *units[1:]]
        edited["units"] = units
        return edited

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            [
                AtomicLineCandidate(
                    recipe_id="recipe:0",
                    block_id="block:task-invalid:0",
                    block_index=0,
                    atomic_index=0,
                    text="Ambiguous line 0",
                    within_recipe_span=True,
                    rule_tags=["recipe_span_fallback"],
                )
            ],
            _settings("codex-line-role-route-v2", line_role_worker_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=FakeCodexExecRunner(
                output_builder=_invalid_task_file_builder
            ),
            live_llm_allowed=True,
        )
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == [
        "invalid_label:0:NOT_A_LABEL",
    ]
    assert proposal_payload["payload"] is None
    assert proposal_payload["validation_metadata"]["row_resolution"]["unresolved_atomic_indices"] == [0]
