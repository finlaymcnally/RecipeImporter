from __future__ import annotations

import tests.llm.codex_farm_orchestrator_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_orchestrator_runs_single_correction_pipeline_and_writes_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    result.recipes[0].tags = ["seed_tag_should_not_survive"]
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )
    runner = _ValidRecipeWorkspaceRunner(
        output_builder=lambda payload: {
            **_build_valid_recipe_task_output(dict(payload or {})),
            "r": [
                {
                    **_build_valid_recipe_task_output(dict(payload or {}))["r"][0],
                    "m": [
                        {"i": 0, "s": [0]},
                        {"i": 1, "s": [1]},
                    ],
                    "mr": None,
                    "g": [
                        {
                            "c": "meal",
                            "l": "breakfast",
                            "f": 0.83,
                        },
                        {
                            "c": "method",
                            "l": "toasted",
                            "f": 0.79,
                        },
                    ],
                }
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "taskfile"
    task_file = exec_runner_module.load_task_file(
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "task.json"
    )
    assert task_file["units"][0]["owned_id"] == "urn:recipe:test:toast"
    authoritative_payload = apply_result.authoritative_recipe_payloads_by_recipe_id[
        "urn:recipe:test:toast"
    ]
    assert authoritative_payload.title == "Toast"
    assert authoritative_payload.tags == ["breakfast", "toasted"]
    assert authoritative_payload.ingredient_step_mapping == {"0": [0], "1": [1]}
    final_payload = authoritative_recipe_semantics_to_draft_v1(authoritative_payload)
    assert [line["raw_text"] for line in final_payload["steps"][0]["ingredient_lines"]] == [
        "1 slice bread"
    ]
    assert [line["raw_text"] for line in final_payload["steps"][1]["ingredient_lines"]] == [
        "1 tablespoon butter"
    ]

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    promotion_report = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "promotion_report.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["pipeline"] == SINGLE_CORRECTION_RECIPE_PIPELINE_ID
    assert manifest["pipelines"] == {
        "recipe_correction": SINGLE_CORRECTION_STAGE_PIPELINE_ID
    }
    assert manifest["counts"]["recipe_shards_total"] == 1
    assert manifest["counts"]["recipe_workers_total"] == 1
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert manifest["counts"]["recipe_build_final_ok"] == 1
    assert manifest["counts"]["final_recipe_authority_promoted"] == 1
    assert sorted(manifest["process_runs"].keys()) == ["recipe_correction"]
    assert manifest["recipes"]["urn:recipe:test:toast"]["final_recipe_authority_status"] == "promoted"
    assert (
        promotion_report["recipe_results"]["urn:recipe:test:toast"][
            "final_recipe_authority_eligibility"
        ]
        == "promotable"
    )
    correction_input = task_file["units"][0]["evidence"]
    assert "draft_hint" not in correction_input
    assert correction_input["hint"] == {
        "title": "Toast",
        "ingredients": ["1 slice bread", "1 tablespoon butter"],
        "steps": [
            "Toast the bread until golden.",
            "Spread with butter and serve hot.",
        ],
        "candidate_tags": [],
        "quality_flags": [],
    }
    assert correction_input["recipe_id"] == "urn:recipe:test:toast"
    assert not (apply_result.llm_raw_dir / "recipe_correction").exists()
    assert apply_result.updated_conversion_result.recipes[0].tags == [
        "breakfast",
        "toasted",
    ]
    assert apply_result.updated_conversion_result.recipes[0].name == "Toast"
    assert (apply_result.llm_raw_dir / "recipe_phase_runtime" / "phase_manifest.json").is_file()


def test_recipe_workspace_watchdog_allows_orientation_and_helper_scripts(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=20,
            command_execution_count=8,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"pwd\n"
                "find . -maxdepth 2 -type f | head -n 5 >/dev/null\n"
                "cat <<'EOF' > scratch/helper.sh\n"
                "jq -M -c '{v: \\\"1\\\"}' in/task-001.json > out/task-001.json\n"
                "EOF\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_recipe_workspace_watchdog_allows_jq_fallback_operator_output_command(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=20,
            command_execution_count=8,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"jq '{rows: .rows | map({atomic_index: .[0], "
                "label: ({\\\"L0\\\":\\\"RECIPE_TITLE\\\"}[.[1]] // \\\"UNKNOWN\\\")})}' "
                "in/task-001.json > out/task-001.json\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_recipe_workspace_watchdog_allows_bounded_python_transform(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=20,
            command_execution_count=8,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"python3 -c "
                "'from pathlib import Path; "
                "Path(\\\"out/task-001.json\\\").write_text(Path(\\\"in/task-001.json\\\").read_text())'\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_recipe_workspace_watchdog_allows_bounded_python_heredoc_scratch_edit(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=20,
            command_execution_count=8,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"python3 - <<'PY'\n"
                "from pathlib import Path\n"
                "import json\n"
                "base = Path('scratch')\n"
                "doc = json.loads((base / 'task-001.json').read_text())\n"
                "doc['r'][0]['st'] = 'fragmentary'\n"
                "doc['r'][0]['sr'] = 'recipe evidence is too incomplete'\n"
                "doc['r'][0]['cr'] = None\n"
                "doc['r'][0]['mr'] = 'not_applicable_fragmentary'\n"
                "doc['r'][0]['w'] = ['incomplete_recipe_source']\n"
                "(base / 'task-001.json').write_text(json.dumps(doc, indent=2) + '\\n')\n"
                "yield_text = '3/4 cup'\n"
                "PY\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_recipe_workspace_watchdog_marks_forbidden_boundary_command_nonretryable(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=20,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc 'pip install foo'",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "boundary_command_execution_forbidden"
    assert decision.retryable is False


def test_recipe_workspace_watchdog_allows_execution_root_startup_command(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "runtime" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        stage_label="taskfile worker stage",
        allow_workspace_commands=True,
        execution_workspace_root=source_root,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command=(
                f'/bin/bash -lc "cd {execution_root} && cat task.json >/dev/null"'
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
            source_working_dir=str(source_root),
            execution_working_dir=str(execution_root),
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False
    assert live_status["execution_working_dir"] == str(execution_root)


def test_execution_plan_uses_semantic_single_correction_stages(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    plan = build_codex_farm_recipe_execution_plan(
        conversion_result=result,
        run_settings=settings,
        workbook_slug="book",
    )

    assert plan["pipeline"] == SINGLE_CORRECTION_RECIPE_PIPELINE_ID
    assert len(plan["planned_shards"]) == 1
    stages = plan["planned_tasks"][0]["planned_stages"]
    assert [stage["stage_key"] for stage in stages] == [
        "recipe_build_intermediate",
        "recipe_refine",
        "recipe_build_final",
    ]
    assert stages[1]["pipeline_id"] == SINGLE_CORRECTION_STAGE_PIPELINE_ID


def test_execution_plan_balances_recipe_shards_to_prompt_target(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_multi_recipe_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
        recipe_prompt_target_count=2,
        recipe_worker_count=2,
    )

    plan = build_codex_farm_recipe_execution_plan(
        conversion_result=result,
        run_settings=settings,
        workbook_slug="book",
    )

    assert [shard["shard_id"] for shard in plan["planned_shards"]] == [
        "recipe-shard-0000-r0000-r0001",
        "recipe-shard-0001-r0002-r0002",
    ]
    assert [shard["recipe_count"] for shard in plan["planned_shards"]] == [2, 1]
    assert [task["shard_id"] for task in plan["planned_tasks"]] == [
        "recipe-shard-0000-r0000-r0001",
        "recipe-shard-0000-r0000-r0001",
        "recipe-shard-0001-r0002-r0002",
    ]
    assert plan["worker_count"] == 2


def test_execute_source_job_skips_codex_farm_when_pipeline_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    out = tmp_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    fake_result = _build_conversion_result(source)

    orchestrator_called = {"value": False}

    def _fake_orchestrator(**_kwargs):
        orchestrator_called["value"] = True
        raise AssertionError("orchestrator should not run when llm pipeline is off")

    def _fake_import(*_args, **_kwargs):
        return fake_result.model_copy(deep=True), TimingStats(), MappingConfig()

    monkeypatch.setattr(
        "cookimport.staging.pipeline_runtime.run_codex_farm_recipe_pipeline",
        _fake_orchestrator,
    )
    monkeypatch.setattr("cookimport.cli_worker._run_import", _fake_import)
    monkeypatch.setattr(
        "cookimport.cli_worker.registry.best_importer_for_path",
        lambda _path: (SimpleNamespace(name="text"), 1.0),
    )

    response = execute_source_job(
        JobSpec(file_path=source, job_index=0, job_count=1),
        out,
        MappingConfig(),
        dt.datetime.now(),
        run_config=RunSettings(llm_recipe_pipeline="off").to_run_config_dict(),
    )

    assert response["status"] == "success"
    assert orchestrator_called["value"] is False


def test_orchestrator_keeps_not_a_recipe_proposal_in_reports_but_skips_promotion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )
    runner = _ValidRecipeWorkspaceRunner(
        output_builder=lambda payload: {
            **_build_valid_recipe_task_output(dict(payload or {})),
            "r": [
                {
                    **_build_valid_recipe_task_output(dict(payload or {}))["r"][0],
                    "st": "not_a_recipe",
                    "sr": "reference_table",
                    "cr": None,
                    "mr": "not_applicable_not_a_recipe",
                    "db": [1, 2, 3, 4, 5],
                    "g": [],
                    "w": ["candidate_rejected"],
                }
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = "urn:recipe:test:toast"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    promotion_report = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "promotion_report.json"
        ).read_text(encoding="utf-8")
    )
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    audit = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_correction_audit"
            / "urn_recipe_test_toast.json"
        ).read_text(encoding="utf-8")
    )

    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
    assert [divestment.block_indices for divestment in apply_result.recipe_divestments] == [
        [1, 2, 3, 4, 5]
    ]
    assert apply_result.updated_conversion_result.recipes == []
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert manifest["counts"]["recipe_build_final_ok"] == 0
    assert manifest["counts"]["recipe_build_final_skipped"] == 1
    assert manifest["counts"]["final_recipe_authority_not_promoted"] == 1
    assert manifest["recipes"][recipe_id]["correction_output_status"] == "not_a_recipe"
    assert manifest["recipes"][recipe_id]["correction_output_reason"] == "reference_table"
    assert manifest["recipes"][recipe_id]["final_recipe_authority_status"] == "not_promoted"
    assert (
        manifest["recipes"][recipe_id]["final_recipe_authority_reason"]
        == "valid_task_outcome_not_a_recipe"
    )
    assert (
        promotion_report["recipe_results"][recipe_id]["final_recipe_authority_eligibility"]
        == "non_promotable"
    )
    assert proposal["payload"]["r"][0]["st"] == "not_a_recipe"
    assert proposal["payload"]["r"][0]["db"] == [1, 2, 3, 4, 5]
    assert audit["output"]["repair_status"] == "not_a_recipe"
    assert audit["deterministic_final_assembly"]["status"] == "skipped"
    assert audit["task_outcome"]["final_recipe_authority_eligibility"] == "non_promotable"
    assert audit["final_recipe_authority"]["status"] == "not_promoted"


def test_orchestrator_keeps_fragmentary_proposal_visible_but_non_promoted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )
    runner = _ValidRecipeWorkspaceRunner(
        output_builder=lambda payload: {
            **_build_valid_recipe_task_output(dict(payload or {})),
            "r": [
                {
                    **_build_valid_recipe_task_output(dict(payload or {}))["r"][0],
                    "st": "fragmentary",
                    "sr": "incomplete_recipe_source",
                    "cr": None,
                    "mr": "not_applicable_fragmentary",
                    "db": [],
                    "g": [],
                    "w": ["incomplete_recipe_source"],
                }
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = "urn:recipe:test:toast"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    promotion_report = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "promotion_report.json"
        ).read_text(encoding="utf-8")
    )
    audit = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_correction_audit"
            / "urn_recipe_test_toast.json"
        ).read_text(encoding="utf-8")
    )

    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
    assert apply_result.recipe_divestments == []
    assert apply_result.updated_conversion_result.recipes == []
    assert manifest["recipes"][recipe_id]["correction_output_status"] == "fragmentary"
    assert manifest["recipes"][recipe_id]["publish_status"] == "withheld_partial"
    assert manifest["recipes"][recipe_id]["final_recipe_authority_status"] == "not_promoted"
    assert (
        manifest["recipes"][recipe_id]["final_recipe_authority_reason"]
        == "valid_task_outcome_fragmentary"
    )
    assert (
        promotion_report["recipe_results"][recipe_id]["final_recipe_authority_eligibility"]
        == "non_promotable"
    )
    assert audit["task_outcome"]["status"] == "fragmentary"
    assert audit["final_recipe_authority"]["status"] == "not_promoted"
    assert apply_result.recipe_authority_decisions_by_recipe_id[recipe_id].publish_status == (
        "withheld_partial"
    )
    assert apply_result.recipe_authority_decisions_by_recipe_id[recipe_id].ownership_action == (
        "retain"
    )


def test_orchestrator_withholds_repaired_recipe_when_final_assembly_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )
    runner = _ValidRecipeWorkspaceRunner(
        output_builder=lambda payload: _build_valid_recipe_task_output(dict(payload or {}))
    )

    original_model_validate = recipe_module.RecipeDraftV1.model_validate

    def _boom(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("recipe", {}).get("title") == "Toast":
            raise ValueError("forced final assembly failure")
        return original_model_validate(value, *args, **kwargs)

    monkeypatch.setattr(recipe_module.RecipeDraftV1, "model_validate", _boom)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = "urn:recipe:test:toast"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )

    assert apply_result.updated_conversion_result.recipes == []
    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
    assert sorted(apply_result.recipe_evidence_payloads_by_recipe_id) == [recipe_id]
    assert manifest["counts"]["withheld_invalid_recipe_count"] == 1
    assert manifest["recipes"][recipe_id]["publish_status"] == "withheld_invalid"
    assert apply_result.recipe_authority_decisions_by_recipe_id[recipe_id].publish_status == (
        "withheld_invalid"
    )
    assert apply_result.recipe_authority_decisions_by_recipe_id[recipe_id].semantic_outcome == (
        "recipe"
    )


def test_orchestrator_rejects_complex_empty_mapping_without_reason_and_skips_promotion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        assert payload is not None
        recipe_row = (
            payload["authoritative_input"]["r"][0]
            if payload.get("repair_mode") == "recipe"
            else payload["r"][0]
        )
        return {
            "v": "1",
            "sid": (
                payload["authoritative_input"]["sid"]
                if payload.get("repair_mode") == "recipe"
                else payload.get("sid")
            ),
            "r": [
                {
                    "v": "1",
                    "rid": recipe_row["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": "Toast",
                        "i": ["1 slice bread", "1 tablespoon butter"],
                        "s": [
                            "Toast the bread until golden.",
                            "Spread with butter and serve hot.",
                        ],
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": None,
                    "db": [],
                    "g": [],
                    "w": [],
                }
            ],
        }

    runner = FakeCodexExecRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
    assert proposal["payload"] is None
    assert proposal["repair_attempted"] is True
    assert manifest["counts"]["recipe_correction_ok"] == 0
    assert manifest["counts"]["recipe_correction_error"] == 1
    assert manifest["counts"]["recipe_build_final_ok"] == 0
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_refine"] == "error"
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_build_final"] == "error"


def test_orchestrator_rejects_multi_ingredient_single_step_empty_mapping_without_reason(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        assert payload is not None
        recipe_row = (
            payload["authoritative_input"]["r"][0]
            if payload.get("repair_mode") == "recipe"
            else payload["r"][0]
        )
        return {
            "v": "1",
            "sid": (
                payload["authoritative_input"]["sid"]
                if payload.get("repair_mode") == "recipe"
                else payload.get("sid")
            ),
            "r": [
                {
                    "v": "1",
                    "rid": recipe_row["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": "Blue Cheese Dressing",
                        "i": [
                            "5 ounces blue cheese",
                            "1/2 cup creme fraiche",
                            "1 tablespoon vinegar",
                        ],
                        "s": [
                            "Whisk everything together. Taste and adjust. Chill before serving."
                        ],
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": None,
                    "db": [],
                    "g": [],
                    "w": [],
                }
            ],
        }

    runner = FakeCodexExecRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    assert proposal["payload"] is None
    assert proposal["repair_attempted"] is True
    assert manifest["counts"]["recipe_correction_error"] == 1
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_refine"] == "error"
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_build_final"] == "error"
    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
