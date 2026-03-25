from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.cli_worker import execute_source_job
from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.core.timing import TimingStats
from cookimport.llm import codex_farm_orchestrator as recipe_module
from cookimport.llm import codex_exec_runner as exec_runner_module
from cookimport.llm.codex_farm_orchestrator import (
    SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    SINGLE_CORRECTION_STAGE_PIPELINE_ID,
    _preflight_recipe_shard,
    build_codex_farm_recipe_execution_plan,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    FakeCodexExecRunner,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.staging.draft_v1 import authoritative_recipe_semantics_to_draft_v1
from cookimport.staging.job_planning import JobSpec


def _build_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread", "1 tablespoon butter"],
                recipeInstructions=[
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                provenance={"location": {"start_block": 1, "end_block": 5}},
            )
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "1 tablespoon butter"},
                        {"index": 4, "text": "Toast the bread until golden."},
                        {"index": 5, "text": "Spread with butter and serve hot."},
                    ],
                    "block_count": 6,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_run_settings(pack_root: Path, *, llm_recipe_pipeline: str) -> RunSettings:
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    return RunSettings.model_validate(
        {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_context_blocks": 3,
            "codex_farm_failure_mode": "fail",
            "codex_farm_recipe_mode": "extract",
        }
    )


def _build_valid_recipe_task_output(task_payload: dict[str, object]) -> dict[str, object]:
    recipe_row = task_payload["r"][0]
    return {
        "v": "1",
        "sid": task_payload["sid"],
        "r": [
            {
                "v": "1",
                "rid": recipe_row["rid"],
                "st": "repaired",
                "sr": None,
                "cr": {
                    "t": recipe_row["h"]["n"],
                    "i": recipe_row["h"]["i"],
                    "s": recipe_row["h"]["s"],
                    "d": None,
                    "y": None,
                },
                "m": [],
                "mr": "unclear_alignment",
                "g": [],
                "w": [],
            }
        ],
    }


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
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid"),
            "r": [
                {
                    "v": "1",
                    "rid": payload["r"][0]["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": "Toast",
                        "i": [
                            "1 slice bread",
                            "1 tablespoon butter",
                        ],
                        "s": [
                            "Toast the bread until golden.",
                            "Spread with butter and serve hot.",
                        ],
                        "d": None,
                        "y": None,
                    },
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
                    "w": [],
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
    assert runner.calls[0]["mode"] == "workspace_worker"
    worker_input = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "workers"
            / "worker-001"
            / "in"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    assert worker_input["r"][0]["rid"] == "urn:recipe:test:toast"
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
    assert manifest["counts"]["build_final_recipe_ok"] == 1
    assert manifest["counts"]["final_recipe_authority_promoted"] == 1
    assert sorted(manifest["process_runs"].keys()) == ["recipe_correction"]
    assert manifest["recipes"]["urn:recipe:test:toast"]["final_recipe_authority_status"] == "promoted"
    assert (
        promotion_report["recipe_results"]["urn:recipe:test:toast"][
            "final_recipe_authority_eligibility"
        ]
        == "promotable"
    )
    correction_input = worker_input
    assert "draft_hint" not in correction_input
    assert correction_input["r"][0]["h"] == {
        "n": "Toast",
        "i": ["1 slice bread", "1 tablespoon butter"],
        "s": [
            "Toast the bread until golden.",
            "Spread with butter and serve hot.",
        ],
        "g": ["seed_tag_should_not_survive"],
    }
    assert correction_input["tg"]["v"] == "recipe_tagging_guide.v3"
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
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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


def test_recipe_workspace_watchdog_marks_forbidden_workspace_command_retryable(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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
    assert decision.reason_code == "watchdog_command_execution_forbidden"
    assert decision.retryable is True


def test_recipe_workspace_watchdog_allows_execution_root_startup_command(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "runtime" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
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
                f'/bin/bash -lc "cd {execution_root} && cat worker_manifest.json '
                'current_task.json OUTPUT_CONTRACT.md >/dev/null"'
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


def test_recipe_workspace_queue_controller_advances_current_task_sidecars_from_written_outputs(
    tmp_path: Path,
) -> None:
    worker_root = tmp_path / "worker-001"
    (worker_root / "out").mkdir(parents=True, exist_ok=True)
    task_rows = (
        {
            "task_id": "task-001",
            "task_kind": "recipe_correction_recipe",
            "parent_shard_id": "shard-001",
            "owned_ids": ["urn:recipe:test:toast"],
            "input_payload": {
                "v": "1",
                "sid": "task-001",
                "ids": ["urn:recipe:test:toast"],
                "r": [{"rid": "urn:recipe:test:toast", "h": {"n": "Toast", "i": ["1 slice bread"], "s": ["Toast the bread."]}}],
            },
            "metadata": {
                "hint_path": "hints/task-001.md",
                "input_path": "in/task-001.json",
                "scratch_draft_path": "scratch/task-001.json",
                "result_path": "out/task-001.json",
            },
        },
        {
            "task_id": "task-002",
            "task_kind": "recipe_correction_recipe",
            "parent_shard_id": "shard-001",
            "owned_ids": ["urn:recipe:test:tea"],
            "input_payload": {
                "v": "1",
                "sid": "task-002",
                "ids": ["urn:recipe:test:tea"],
                "r": [{"rid": "urn:recipe:test:tea", "h": {"n": "Tea", "i": ["1 cup water"], "s": ["Boil the water."]}}],
            },
            "metadata": {
                "hint_path": "hints/task-002.md",
                "input_path": "in/task-002.json",
                "scratch_draft_path": "scratch/task-002.json",
                "result_path": "out/task-002.json",
            },
        },
    )
    controller = recipe_module._RecipeWorkspaceTaskQueueController(  # noqa: SLF001
        worker_root=worker_root,
        task_rows=task_rows,
    )

    assert json.loads((worker_root / "current_task.json").read_text(encoding="utf-8"))["task_id"] == "task-001"

    (worker_root / "out" / "task-001.json").write_text(
        json.dumps(
            {
                "v": "1",
                "sid": "task-001",
                "r": [
                    {
                        "v": "1",
                        "rid": "urn:recipe:test:toast",
                        "st": "repaired",
                        "sr": None,
                        "cr": {
                            "t": "Toast",
                            "i": ["1 slice bread"],
                            "s": ["Toast the bread."],
                            "d": None,
                            "y": None,
                        },
                        "m": [],
                        "mr": "not_needed_single_step",
                        "g": [],
                        "w": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first_observation = controller.observe_current_output()

    assert first_observation["advanced"] is True
    assert json.loads((worker_root / "current_task.json").read_text(encoding="utf-8"))["task_id"] == "task-002"
    assert "task-002" in (worker_root / "CURRENT_TASK.md").read_text(encoding="utf-8")

    (worker_root / "out" / "task-002.json").write_text(
        json.dumps(
            {
                "v": "1",
                "sid": "task-002",
                "r": [
                    {
                        "v": "1",
                        "rid": "urn:recipe:test:tea",
                        "st": "repaired",
                        "sr": None,
                        "cr": {
                            "t": "Tea",
                            "i": ["1 cup water"],
                            "s": ["Boil the water."],
                            "d": None,
                            "y": None,
                        },
                        "m": [],
                        "mr": "not_needed_single_step",
                        "g": [],
                        "w": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    second_observation = controller.observe_current_output()

    assert second_observation["advanced"] is True
    assert not (worker_root / "current_task.json").exists()
    assert "No current task is active" in (worker_root / "CURRENT_TASK.md").read_text(encoding="utf-8")


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
        "build_intermediate_det",
        "recipe_llm_correct_and_link",
        "build_final_recipe",
    ]
    assert stages[1]["pipeline_id"] == SINGLE_CORRECTION_STAGE_PIPELINE_ID


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
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid"),
            "r": [
                {
                    "v": "1",
                    "rid": payload["r"][0]["rid"],
                    "st": "not_a_recipe",
                    "sr": "reference_table",
                    "cr": None,
                    "m": [],
                    "mr": "not_applicable_not_a_recipe",
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
    assert apply_result.updated_conversion_result.recipes == []
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert manifest["counts"]["build_final_recipe_ok"] == 0
    assert manifest["counts"]["build_final_recipe_skipped"] == 1
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
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid"),
            "r": [
                {
                    "v": "1",
                    "rid": payload["r"][0]["rid"],
                    "st": "fragmentary",
                    "sr": "incomplete_recipe_source",
                    "cr": None,
                    "m": [],
                    "mr": "not_applicable_fragmentary",
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
    assert apply_result.updated_conversion_result.recipes == []
    assert manifest["recipes"][recipe_id]["correction_output_status"] == "fragmentary"
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

    assert [call["mode"] for call in runner.calls] == ["workspace_worker", "structured_prompt"]
    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}
    assert proposal["payload"] is None
    assert proposal["repair_attempted"] is True
    assert manifest["counts"]["recipe_correction_ok"] == 0
    assert manifest["counts"]["recipe_correction_error"] == 1
    assert manifest["counts"]["build_final_recipe_ok"] == 0
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_llm_correct_and_link"] == "error"
    assert manifest["recipes"]["urn:recipe:test:toast"]["build_final_recipe"] == "error"


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

    assert [call["mode"] for call in runner.calls] == ["workspace_worker", "structured_prompt"]
    assert proposal["payload"] is None
    assert proposal["repair_attempted"] is True
    assert manifest["counts"]["recipe_correction_error"] == 1
    assert manifest["recipes"]["urn:recipe:test:toast"]["recipe_llm_correct_and_link"] == "error"
    assert manifest["recipes"]["urn:recipe:test:toast"]["build_final_recipe"] == "error"
    assert apply_result.authoritative_recipe_payloads_by_recipe_id == {}


def test_orchestrator_repairs_near_miss_invalid_recipe_shard_once(
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
        if payload.get("repair_mode") == "recipe":
            authoritative_input = payload["authoritative_input"]
            recipe_row = authoritative_input["r"][0]
            return {
                "v": "1",
                "sid": authoritative_input["sid"],
                "r": [
                    {
                        "v": "1",
                        "rid": recipe_row["rid"],
                        "st": "repaired",
                        "sr": None,
                        "cr": {
                            "t": recipe_row["h"]["n"],
                            "i": recipe_row["h"]["i"],
                            "s": recipe_row["h"]["s"],
                            "d": None,
                            "y": None,
                        },
                        "m": [],
                        "mr": "repair_pass",
                        "g": [],
                        "w": [],
                    }
                ],
            }
        return {
            "v": "1",
            "sid": payload.get("sid"),
            "r": [],
        }

    runner = FakeCodexExecRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.calls) == 2
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert "Authoritative shard input:" in runner.calls[1]["prompt_text"]
    assert "Missing recipe ids: urn:recipe:test:toast" in runner.calls[1]["prompt_text"]

    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    repair_status = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "workers"
            / "worker-001"
            / "shards"
            / "recipe-shard-0000-r0000-r0000"
            / "repair_status.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "repaired"
    assert proposal["validation_errors"] == []
    assert repair_status["status"] == "repaired"
    assert repair_status["state"] == "completed"
    assert (
        apply_result.authoritative_recipe_payloads_by_recipe_id[
            "urn:recipe:test:toast"
        ].title
        == "Toast"
    )


def test_preflight_recipe_shard_rejects_missing_model_facing_recipes() -> None:
    shard = ShardManifestEntryV1(
        shard_id="recipe-shard-0000-r0000-r0000",
        owned_ids=("urn:recipe:test:toast",),
        input_payload={"v": "1", "sid": "recipe-shard-0000-r0000-r0000", "r": []},
    )

    assert _preflight_recipe_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "recipe shard has no model-facing recipes",
    }


def test_orchestrator_marks_watchdog_killed_recipe_shards_in_summary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _WatchdogRunner(FakeCodexExecRunner):
        def _watchdog_result(
            self,
            result,
            *,
            supervision_callback=None,
            timeout_seconds=None,
        ):  # noqa: ANN001
            if supervision_callback is not None:
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=2,
                        command_execution_count=1,
                        reasoning_item_count=0,
                        last_command="python -c 'print(1)'",
                        last_command_repeat_count=1,
                        has_final_agent_message=False,
                        timeout_seconds=timeout_seconds,
                    )
                )
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message="strict JSON stage attempted tool use",
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "python -c 'print(1)'",
                        },
                    },
                ),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
                source_working_dir=result.source_working_dir,
                execution_working_dir=result.execution_working_dir,
                execution_agents_path=result.execution_agents_path,
                duration_ms=result.duration_ms,
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="strict JSON stage attempted tool use",
                supervision_retryable=False,
            )

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=_WatchdogRunner(
            output_builder=lambda payload: {
                "v": "1",
                "sid": payload.get("sid") if payload is not None else None,
                "r": [],
            }
        ),
    )

    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert "watchdog_kills_detected" in process_summary["pathological_flags"]
    assert "command_execution_detected" in process_summary["pathological_flags"]

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    assert status_payload["status"] == "invalid"
    assert status_payload["state"] == "watchdog_killed"
    assert status_payload["reason_code"] == "watchdog_command_execution_forbidden"

    live_status_payload = json.loads(
        (shard_root / "live_status.json").read_text(encoding="utf-8")
    )
    assert live_status_payload["state"] == "watchdog_killed"
    assert live_status_payload["reason_code"] == "watchdog_command_execution_forbidden"


def _run_retryable_watchdog_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _RetryingWatchdogRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            working_dir = Path(kwargs["working_dir"])
            for output_path in (working_dir / "out").glob("*.json"):
                output_path.unlink()
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=2,
                        command_execution_count=1,
                        reasoning_item_count=0,
                        last_command=(
                            "/bin/bash -lc \"python3 - <<'PY'\n"
                            "from pathlib import Path\n"
                            "(Path('scratch') / 'task-001.json').read_text()\n"
                            "PY\""
                        ),
                        last_command_repeat_count=1,
                        has_final_agent_message=False,
                        timeout_seconds=kwargs.get("timeout_seconds"),
                    )
                )
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message="workspace worker attempted a forbidden command",
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "python3 - <<'PY' ...",
                        },
                    },
                ),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
                source_working_dir=result.source_working_dir,
                execution_working_dir=result.execution_working_dir,
                execution_agents_path=result.execution_agents_path,
                duration_ms=result.duration_ms,
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="workspace worker attempted a forbidden command",
                supervision_retryable=True,
            )

    runner = _RetryingWatchdogRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid") if payload is not None else None,
            "r": [
                {
                    "v": "1",
                    "rid": payload["authoritative_input"]["r"][0]["rid"]
                    if payload and payload.get("retry_mode") == "recipe_watchdog"
                    else payload["r"][0]["rid"],
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
                    "mr": "retry_pass",
                    "g": [],
                    "w": [],
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

    assert [call["mode"] for call in runner.calls] == [
        "workspace_worker",
        "structured_prompt",
    ]
    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 0
    assert process_summary["watchdog_recovered_shard_count"] == 1

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    proposal_payload = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    retry_status = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "workers"
            / "worker-001"
            / "shards"
            / "recipe-shard-0000-r0000-r0000"
            / "watchdog_retry"
            / "status.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "runner": runner,
        "apply_result": apply_result,
        "process_summary": process_summary,
        "status_payload": status_payload,
        "proposal_payload": proposal_payload,
        "retry_status": retry_status,
    }


def test_orchestrator_recovers_retryable_watchdog_killed_recipe_shard(
    tmp_path: Path,
) -> None:
    fixture = _run_retryable_watchdog_fixture(tmp_path)
    runner = fixture["runner"]
    process_summary = fixture["process_summary"]

    assert [call["mode"] for call in runner.calls] == [
        "workspace_worker",
        "structured_prompt",
    ]
    assert process_summary["watchdog_killed_shard_count"] == 0
    assert process_summary["watchdog_recovered_shard_count"] == 1


def test_orchestrator_persists_recovered_watchdog_shard_status_artifacts(
    tmp_path: Path,
) -> None:
    fixture = _run_retryable_watchdog_fixture(tmp_path)
    status_payload = fixture["status_payload"]
    proposal_payload = fixture["proposal_payload"]
    retry_status = fixture["retry_status"]

    assert status_payload["status"] == "validated"
    assert status_payload["watchdog_retry_status"] == "recovered"
    assert status_payload["state"] == "completed"
    assert status_payload["reason_code"] == "watchdog_retry_recovered"
    assert status_payload["raw_supervision_state"] == "watchdog_killed"
    assert status_payload["final_supervision_state"] == "completed"
    assert proposal_payload["watchdog_retry_status"] == "recovered"
    assert retry_status["status"] == "validated"


def _run_packed_watchdog_retry_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    result.recipes.append(
        RecipeCandidate(
            name="Tea",
            identifier="urn:recipe:test:tea",
            recipeIngredient=["1 cup water", "1 tea bag"],
            recipeInstructions=["Boil the water.", "Steep the tea bag."],
            provenance={"location": {"start_block": 6, "end_block": 9}},
        )
    )
    result.raw_artifacts[0].content["blocks"].extend(
        [
            {"index": 6, "text": "Tea"},
            {"index": 7, "text": "1 cup water"},
            {"index": 8, "text": "1 tea bag"},
            {"index": 9, "text": "Boil the water. Steep the tea bag."},
        ]
    )
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    ).model_copy(update={"recipe_worker_count": 1})

    class _PackedRetryRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            result = super().run_workspace_worker(**kwargs)
            out_dir = Path(str(kwargs["working_dir"])) / "out"
            for output_path in out_dir.glob("*.json"):
                output_path.unlink()
            return CodexExecRunResult(
                command=list(result.command),
                subprocess_exit_code=1,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message="workspace worker attempted a forbidden command",
                events=result.events
                + (
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "cmd_startup",
                            "type": "command_execution",
                            "command": "/bin/bash -lc 'pip install nope'",
                            "exit_code": 1,
                        },
                    },
                ),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
                source_working_dir=result.source_working_dir,
                execution_working_dir=result.execution_working_dir,
                execution_agents_path=result.execution_agents_path,
                duration_ms=result.duration_ms,
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                workspace_mode=result.workspace_mode,
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="workspace worker attempted a forbidden command",
                supervision_retryable=True,
            )

    runner = _PackedRetryRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid") if payload is not None else None,
            "r": [
                {
                    "v": "1",
                    "rid": recipe_payload["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": recipe_payload.get("h", {}).get("n") or recipe_payload["rid"],
                        "i": recipe_payload.get("h", {}).get("i", []),
                        "s": recipe_payload.get("h", {}).get("s", []),
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": "packed_retry_pass",
                    "g": [],
                    "w": [],
                }
                for recipe_payload in (
                    payload["authoritative_input"]["r"]
                    if payload and payload.get("retry_mode") == "recipe_watchdog"
                    else payload.get("r", [])
                )
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

    assert [call["mode"] for call in runner.calls] == [
        "workspace_worker",
        "structured_prompt",
        "structured_prompt",
    ]
    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["structured_followup_call_count"] == 2
    assert process_summary["watchdog_killed_shard_count"] == 0
    assert process_summary["watchdog_recovered_shard_count"] == 2

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    retry_status = json.loads(
        (shard_root / "watchdog_retry" / "status.json").read_text(encoding="utf-8")
    )
    return {
        "runner": runner,
        "process_summary": process_summary,
        "status_payload": status_payload,
        "retry_status": retry_status,
    }


def test_orchestrator_uses_one_packed_watchdog_retry_for_early_multi_task_worker_death(
    tmp_path: Path,
) -> None:
    fixture = _run_packed_watchdog_retry_fixture(tmp_path)
    runner = fixture["runner"]
    process_summary = fixture["process_summary"]

    assert [call["mode"] for call in runner.calls] == [
        "workspace_worker",
        "structured_prompt",
        "structured_prompt",
    ]
    assert process_summary["structured_followup_call_count"] == 2
    assert process_summary["watchdog_killed_shard_count"] == 0
    assert process_summary["watchdog_recovered_shard_count"] == 2


def test_orchestrator_marks_packed_watchdog_retry_mode_in_status_artifacts(
    tmp_path: Path,
) -> None:
    fixture = _run_packed_watchdog_retry_fixture(tmp_path)
    status_payload = fixture["status_payload"]
    retry_status = fixture["retry_status"]

    assert status_payload["status"] == "validated"
    assert status_payload["watchdog_retry_status"] == "recovered"
    assert status_payload["watchdog_retry_mode"] == "shard_packed"
    assert retry_status["status"] == "validated"
    assert retry_status["watchdog_retry_mode"] == "shard_packed"
