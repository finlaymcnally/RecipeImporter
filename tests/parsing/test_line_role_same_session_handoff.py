from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from cookimport.llm.editable_task_file import load_task_file, write_task_file
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1
from cookimport.parsing.canonical_line_roles.runtime import _build_line_role_task_file
from cookimport.parsing.canonical_line_roles.same_session_handoff import (
    advance_line_role_same_session_handoff,
    describe_line_role_same_session_doctor,
    describe_line_role_same_session_status,
    initialize_line_role_same_session_state,
    main as line_role_same_session_main,
)


def _assignment(tmp_path: Path) -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("line-role-shard-0000",),
        workspace_root=str(tmp_path),
    )


def _shard() -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="line-role-shard-0000",
        owned_ids=("7",),
        input_payload={"rows": [[7, "Variation"]]},
        metadata={},
    )


def _initialize_workspace(tmp_path: Path) -> tuple[Path, Path]:
    shard = _shard()
    task_file, unit_to_shard_id = _build_line_role_task_file(
        assignment=_assignment(tmp_path),
        shards=[shard],
        debug_payload_by_shard_id={shard.shard_id: {"rows": [{"atomic_index": 7, "block_id": "b7"}]}},
        deterministic_baseline_by_shard_id={},
    )
    workspace_root = tmp_path / "worker-001"
    output_dir = workspace_root / "out"
    workspace_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_task_file(path=workspace_root / "task.json", payload=task_file)
    state_path = workspace_root / "_repo_control" / "line_role_same_session_state.json"
    initialize_line_role_same_session_state(
        state_path=state_path,
        assignment_id="worker-001",
        worker_id="worker-001",
        task_file=task_file,
        unit_to_shard_id=unit_to_shard_id,
        shards=[asdict(shard)],
        output_dir=output_dir,
    )
    return workspace_root, state_path


def test_line_role_same_session_handoff_repairs_invalid_exclusion_reason_and_completes(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "label": "NONRECIPE_EXCLUDE",
        "exclusion_reason": "nonrecipe",
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    repair_result = advance_line_role_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert repair_result["status"] == "repair_required"
    assert repair_task["mode"] == "repair"
    assert repair_result["same_session_repair_rewrite_count"] == 1
    assert repair_task["helper_commands"]["status"] == "task-status"
    assert repair_task["answer_schema"]["example_answers"][0]["label"] == "RECIPE_NOTES"

    repair_task["units"][0]["answer"] = {
        "label": "NONRECIPE_EXCLUDE",
        "exclusion_reason": "navigation",
    }
    write_task_file(path=workspace_root / "task.json", payload=repair_task)
    completed_result = advance_line_role_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "line-role-shard-0000.json").read_text(encoding="utf-8")
    )

    assert completed_result["status"] == "completed"
    assert completed_result["completed_shard_count"] == 1
    assert output_payload["rows"] == [
        {"atomic_index": 7, "label": "NONRECIPE_EXCLUDE", "exclusion_reason": "navigation"}
    ]


def test_line_role_same_session_handoff_stops_after_one_failed_repair_pass(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "label": "NONRECIPE_EXCLUDE",
        "exclusion_reason": "nonrecipe",
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    repair_result = advance_line_role_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    assert repair_result["status"] == "repair_required"

    second_result = advance_line_role_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert second_result["status"] == "repair_exhausted"
    assert second_result["same_session_repair_rewrite_count"] == 1
    assert state_payload["final_status"] == "repair_exhausted"
    assert state_payload["same_session_repair_rewrite_count"] == 1


def test_line_role_same_session_status_and_doctor_report_next_action(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    status = describe_line_role_same_session_status(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    doctor = describe_line_role_same_session_doctor(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert status["recommended_command"] == (
        "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff"
    )
    assert status["expected_outputs_total"] == 1
    assert doctor["diagnosis_code"] == "awaiting_answers"


def test_line_role_same_session_cli_status_autodiscovers_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root, _state_path = _initialize_workspace(tmp_path)

    monkeypatch.chdir(workspace_root)
    monkeypatch.delenv("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["line_role_same_session_handoff", "--status"],
    )

    exit_code = line_role_same_session_main()
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == 0
    assert payload["mode"] == "initial"
    assert payload["stage_key"] == "line_role"
