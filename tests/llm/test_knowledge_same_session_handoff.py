from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from cookimport.llm.editable_task_file import load_task_file, write_task_file
from cookimport.llm.knowledge_same_session_handoff import (
    advance_knowledge_same_session_handoff,
    initialize_knowledge_same_session_state,
)
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment(tmp_path: Path) -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root=str(tmp_path),
    )


def _shard() -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [
                {
                    "i": 8,
                    "id": "book.ks0000.nr:8",
                    "t": "Use low heat and whisk steadily.",
                }
            ],
        },
        metadata={"owned_block_indices": [8], "owned_block_count": 1},
    )


def _valid_classification_answer() -> dict[str, object]:
    return {
        "category": "knowledge",
        "reviewer_category": "knowledge",
        "retrieval_concept": "Heat control",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [
                {
                    "key": "heat-control",
                    "display_name": "Heat control",
                    "category_key": "techniques",
                }
            ],
        },
    }


def _initialize_workspace(tmp_path: Path) -> tuple[Path, Path]:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(tmp_path),
        shards=[_shard()],
    )
    workspace_root = tmp_path / "worker-001"
    output_dir = workspace_root / "out"
    workspace_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_task_file(path=workspace_root / "task.json", payload=classification_task_file)
    state_path = workspace_root / "_repo_control" / "knowledge_same_session_state.json"
    initialize_knowledge_same_session_state(
        state_path=state_path,
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        unit_to_shard_id=unit_to_shard_id,
        output_dir=output_dir,
    )
    return workspace_root, state_path


def test_same_session_handoff_advances_from_classification_to_grouping_and_completes(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=edited)

    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")

    assert classification_result["status"] == "advance_to_grouping"
    assert grouping_task["stage_key"] == "knowledge_group"
    assert classification_result["classification_validation_count"] == 1
    assert classification_result["grouping_transition_count"] == 1

    grouping_task["units"][0]["answer"] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
    }
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert grouping_result["status"] == "completed_with_grouping"
    assert grouping_result["same_session_transition_count"] == 2
    assert grouping_result["grouping_validation_count"] == 1
    assert output_payload["packet_id"] == "book.ks0000.nr"
    assert output_payload["block_decisions"][0]["category"] == "knowledge"
    assert output_payload["idea_groups"] == [
        {"group_id": "g01", "topic_label": "Heat control", "block_indices": [8]}
    ]


def test_same_session_handoff_rewrites_invalid_classification_into_repair_mode(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "reviewer_category": "other",
        "retrieval_concept": "Heat control",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    repair_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert repair_result["status"] == "repair_required"
    assert repair_task["mode"] == "repair"
    assert repair_task["stage_key"] == "nonrecipe_classify"
    assert repair_result["same_session_repair_rewrite_count"] == 1
    assert repair_result["classification_validation_count"] == 1

    repair_task["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=repair_task)
    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")
    grouping_task["units"][0]["answer"] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
    }
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)
    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert classification_result["status"] == "advance_to_grouping"
    assert grouping_result["status"] == "completed_with_grouping"
    assert grouping_result["same_session_transition_count"] == 3
    assert grouping_result["same_session_repair_rewrite_count"] == 1


def test_same_session_handoff_treats_task_file_contract_tampering_as_repairable_failure(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["stage_key"] = "tampered"
    edited["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=edited)

    result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert result["status"] == "repair_required"
    assert result["same_session_repair_rewrite_count"] == 1
    assert "immutable_field_changed" in result["validation_errors"]
    assert repair_task["mode"] == "repair"
    assert repair_task["stage_key"] == "nonrecipe_classify"
    assert repair_task["units"][0]["previous_answer"] == _valid_classification_answer()


def test_same_session_grouping_handoff_treats_task_file_contract_tampering_as_repairable_failure(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=edited)
    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    assert classification_result["status"] == "advance_to_grouping"

    grouping_task = load_task_file(workspace_root / "task.json")
    grouping_task["stage_key"] = "tampered"
    grouping_task["units"][0]["answer"] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
    }
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert grouping_result["status"] == "repair_required"
    assert grouping_result["same_session_repair_rewrite_count"] == 1
    assert "immutable_field_changed" in grouping_result["validation_errors"]
    assert repair_task["mode"] == "repair"
    assert repair_task["stage_key"] == "knowledge_group"


def test_same_session_grouping_handoff_stops_after_one_failed_repair_pass(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=edited)
    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    assert classification_result["status"] == "advance_to_grouping"

    grouping_task = load_task_file(workspace_root / "task.json")
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    repair_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    assert repair_result["status"] == "repair_required"

    second_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert second_result["status"] == "repair_exhausted"
    assert second_result["same_session_repair_rewrite_count"] == 1
    assert state_payload["final_status"] == "repair_exhausted"
    assert state_payload["same_session_repair_rewrite_count"] == 1
