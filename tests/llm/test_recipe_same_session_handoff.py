from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from cookimport.llm import recipe_stage_shared as recipe_runtime
from cookimport.llm.editable_task_file import load_task_file, write_task_file
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1
from cookimport.llm.recipe_same_session_handoff import (
    advance_recipe_same_session_handoff,
    describe_recipe_same_session_doctor,
    describe_recipe_same_session_status,
    initialize_recipe_same_session_state,
    main as recipe_same_session_main,
)


def _assignment(tmp_path: Path) -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("recipe-shard-0000",),
        workspace_root=str(tmp_path),
    )


def _task_plan() -> recipe_runtime._RecipeTaskPlan:
    return recipe_runtime._RecipeTaskPlan(
        task_id="recipe-shard-0000.task-001",
        parent_shard_id="recipe-shard-0000",
        manifest_entry=ShardManifestEntryV1(
            shard_id="recipe-shard-0000.task-001",
            owned_ids=("urn:recipe:test:toast",),
            input_payload={
                "v": "1",
                "sid": "recipe-shard-0000.task-001",
                "r": [
                    {
                        "rid": "urn:recipe:test:toast",
                        "h": {
                            "n": "Toast",
                            "i": ["1 slice bread"],
                            "s": ["Toast the bread."],
                        },
                        "txt": "Toast\n1 slice bread\nToast the bread.",
                        "ev": [
                            [1, "Toast"],
                            [2, "1 slice bread"],
                            [3, "Toast the bread."],
                        ],
                    }
                ],
            },
            metadata={},
        ),
    )


def _valid_answer() -> dict[str, object]:
    return {
        "status": "repaired",
        "status_reason": None,
        "canonical_recipe": {
            "title": "Toast",
            "ingredients": ["1 slice bread"],
            "steps": ["Toast the bread."],
            "description": None,
            "recipe_yield": None,
        },
        "ingredient_step_mapping": [],
        "ingredient_step_mapping_reason": "not_needed_single_step",
        "selected_tags": [],
        "warnings": [],
    }


def _initialize_workspace(tmp_path: Path) -> tuple[Path, Path, recipe_runtime._RecipeTaskPlan]:
    task_plan = _task_plan()
    task_file = recipe_runtime._build_recipe_task_file(
        assignment=_assignment(tmp_path),
        runnable_tasks=[task_plan],
    )
    workspace_root = tmp_path / "worker-001"
    output_dir = workspace_root / "out"
    workspace_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_task_file(path=workspace_root / "task.json", payload=task_file)
    state_path = workspace_root / "_repo_control" / "recipe_same_session_state.json"
    initialize_recipe_same_session_state(
        state_path=state_path,
        assignment_id="worker-001",
        worker_id="worker-001",
        task_file=task_file,
        task_records=[
            {
                "unit_id": recipe_runtime._build_recipe_task_file_unit(task_plan=task_plan)["unit_id"],
                "task_id": task_plan.task_id,
                "parent_shard_id": task_plan.parent_shard_id,
                "result_path": recipe_runtime._recipe_task_result_path(task_plan),
                "manifest_entry": asdict(task_plan.manifest_entry),
            }
        ],
        output_dir=output_dir,
    )
    return workspace_root, state_path, task_plan


def test_recipe_same_session_handoff_rewrites_invalid_answer_into_repair_and_completes(
    tmp_path: Path,
) -> None:
    workspace_root, state_path, task_plan = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "status": "repaired",
        "canonical_recipe": None,
        "ingredient_step_mapping": [],
        "ingredient_step_mapping_reason": "not_needed_single_step",
        "selected_tags": [],
        "warnings": [],
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    repair_result = advance_recipe_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert repair_result["status"] == "repair_required"
    assert repair_task["mode"] == "repair"
    assert repair_result["same_session_repair_rewrite_count"] == 1
    assert "helper_commands" not in repair_task
    assert repair_task["answer_schema"]["example_answers"][0]["status"] == "repaired"

    repair_task["units"][0]["answer"] = _valid_answer()
    write_task_file(path=workspace_root / "task.json", payload=repair_task)
    completed_result = advance_recipe_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    output_payload = json.loads(
        (workspace_root / recipe_runtime._recipe_task_result_path(task_plan)).read_text(
            encoding="utf-8"
        )
    )
    assert completed_result["status"] == "completed"
    assert completed_result["completed_task_count"] == 1
    assert output_payload["r"][0]["st"] == "repaired"


def test_recipe_same_session_handoff_stops_after_one_failed_repair_pass(
    tmp_path: Path,
) -> None:
    workspace_root, state_path, _task_plan = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "status": "repaired",
        "canonical_recipe": None,
        "ingredient_step_mapping": [],
        "ingredient_step_mapping_reason": "not_needed_single_step",
        "selected_tags": [],
        "warnings": [],
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    repair_result = advance_recipe_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    assert repair_result["status"] == "repair_required"

    second_result = advance_recipe_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert second_result["status"] == "repair_exhausted"
    assert second_result["same_session_repair_rewrite_count"] == 1
    assert state_payload["final_status"] == "repair_exhausted"
    assert state_payload["same_session_repair_rewrite_count"] == 1


def test_recipe_same_session_status_and_doctor_report_next_action(
    tmp_path: Path,
) -> None:
    workspace_root, state_path, _task_plan = _initialize_workspace(tmp_path)

    status = describe_recipe_same_session_status(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    doctor = describe_recipe_same_session_doctor(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert status["recommended_command"] == "python3 -m cookimport.llm.recipe_same_session_handoff"
    assert status["answered_units"] == 0
    assert status["expected_outputs_total"] == 1
    assert doctor["diagnosis_code"] == "awaiting_answers"


def test_recipe_same_session_cli_status_autodiscovers_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root, _state_path, _task_plan = _initialize_workspace(tmp_path)

    monkeypatch.chdir(workspace_root)
    monkeypatch.delenv("RECIPEIMPORT_RECIPE_SAME_SESSION_STATE_PATH", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["recipe_same_session_handoff", "--status"],
    )

    exit_code = recipe_same_session_main()
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == 0
    assert payload["mode"] == "initial"
    assert payload["recommended_command"] == "python3 -m cookimport.llm.recipe_same_session_handoff"
