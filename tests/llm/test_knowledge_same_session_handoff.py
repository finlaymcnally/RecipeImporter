from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from cookimport.llm.editable_task_file import load_task_file, write_task_file
from cookimport.llm.knowledge_same_session_handoff import (
    advance_knowledge_same_session_handoff,
    describe_knowledge_same_session_doctor,
    describe_knowledge_same_session_status,
    initialize_knowledge_same_session_state,
    main as knowledge_same_session_main,
)
from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    build_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment(tmp_path: Path) -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root=str(tmp_path),
    )


def _shard(
    *,
    block_index: int = 8,
    text: str = "Use low heat and whisk steadily.",
) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [
                {
                    "i": block_index,
                    "id": f"book.ks0000.nr:{block_index}",
                    "t": text,
                }
            ],
        },
        metadata={"owned_block_indices": [block_index], "owned_block_count": 1},
    )


def _valid_classification_answer() -> dict[str, object]:
    return {
        "category": "knowledge",
        "grounding": {
            "tag_keys": ["saute"],
            "category_keys": ["cooking-method"],
        },
    }


def _proposal_candidate_answer() -> dict[str, object]:
    return {
        "category": "proposal_candidate",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
        },
    }


def _grouping_answer(
    *,
    proposal_decision: str = "not_applicable",
) -> dict[str, object]:
    answer: dict[str, object] = {
        "group_key": "heat-control",
        "topic_label": "Heat control",
        "proposal_decision": proposal_decision,
        "proposed_tag": None,
        "why_no_existing_tag": None,
        "retrieval_query": None,
    }
    if proposal_decision == "approved":
        answer.update(
            {
                "proposed_tag": {
                    "key": "rendering",
                    "display_name": "Rendering",
                    "category_key": "techniques",
                },
                "why_no_existing_tag": "The catalog has adjacent heat tags but no direct rendering tag.",
                "retrieval_query": "how to render chicken fat",
            }
        )
    elif proposal_decision == "rejected":
        answer["group_key"] = "broad-editorial"
        answer["topic_label"] = "Broad editorial"
    return answer


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


def _initialize_workspace_with_shards(
    tmp_path: Path,
    *,
    shards: list[ShardManifestEntryV1],
) -> tuple[Path, Path]:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(tmp_path),
        shards=shards,
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

    grouping_task["units"][0]["answer"] = _grouping_answer()
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
    assert output_payload["block_decisions"] == [
        {
            "block_index": 8,
            "category": "knowledge",
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
        }
    ]
    assert output_payload["idea_groups"] == [
        {"group_id": "g01", "topic_label": "Heat control", "block_indices": [8]}
    ]


def test_same_session_handoff_resolves_proposal_candidates_during_grouping(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = _proposal_candidate_answer()
    write_task_file(path=workspace_root / "task.json", payload=edited)

    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")

    assert classification_result["status"] == "advance_to_grouping"
    assert classification_result["same_session_repair_rewrite_count"] == 0
    assert classification_result["validation_errors"] == []
    assert grouping_task["stage_key"] == "knowledge_group"
    assert grouping_task["units"][0]["classification"]["category"] == "proposal_candidate"

    grouping_task["units"][0]["answer"] = _grouping_answer(proposal_decision="approved")
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert grouping_result["status"] == "completed_with_grouping"
    assert output_payload["block_decisions"] == [
        {
            "block_index": 8,
            "category": "knowledge",
            "grounding": {
                "tag_keys": [],
                "category_keys": ["techniques"],
                "proposed_tags": [
                    {
                        "key": "rendering",
                        "display_name": "Rendering",
                        "category_key": "techniques",
                    }
                ],
            },
        }
    ]
    assert output_payload["idea_groups"] == [
        {"group_id": "g01", "topic_label": "Heat control", "block_indices": [8]}
    ]


def test_same_session_handoff_rejects_category_only_grounding_and_enters_repair(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "knowledge",
        "grounding": {
            "tag_keys": [],
            "category_keys": ["techniques"],
        },
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    repair_task = load_task_file(workspace_root / "task.json")

    assert classification_result["status"] == "repair_required"
    assert "knowledge_grounding_existing_tag_required" in classification_result["validation_errors"]
    assert classification_result["same_session_repair_rewrite_count"] == 1
    assert repair_task["mode"] == "repair"
    assert repair_task["stage_key"] == "nonrecipe_classify"


def test_same_session_handoff_can_complete_without_grouping_when_all_rows_are_other(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [],
        },
    }
    write_task_file(path=workspace_root / "task.json", payload=edited)

    result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "completed_without_grouping"
    assert result["grouping_transition_count"] == 0
    assert output_payload["block_decisions"][0]["category"] == "other"
    assert output_payload["idea_groups"] == []


def test_same_session_handoff_rewrites_invalid_classification_into_repair_mode(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": ["saute"],
            "category_keys": ["techniques"],
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
    assert "helper_commands" not in repair_task
    assert repair_task["answer_schema"]["example_answers"][0]["category"] == "knowledge"
    assert repair_task["ontology"]["catalog_version"]

    repair_task["units"][0]["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=repair_task)
    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")
    grouping_task["units"][0]["answer"] = _grouping_answer()
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)
    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert classification_result["status"] == "advance_to_grouping"
    assert grouping_result["status"] == "completed_with_grouping"
    assert grouping_result["same_session_transition_count"] == 3
    assert grouping_result["same_session_repair_rewrite_count"] == 1


def test_same_session_handoff_keeps_prior_valid_classification_answers_after_repair(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace_with_shards(
        tmp_path,
        shards=[
            ShardManifestEntryV1(
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
                        },
                        {
                            "i": 9,
                            "id": "book.ks0000.nr:9",
                            "t": "Acid balances richness in dressings.",
                        },
                    ],
                },
                metadata={"owned_block_indices": [8, 9], "owned_block_count": 2},
            )
        ],
    )

    task_file = load_task_file(workspace_root / "task.json")
    valid_answer = _valid_classification_answer()
    task_file["units"][0]["answer"] = valid_answer
    task_file["units"][1]["answer"] = {
        "category": "other",
        "grounding": {
            "tag_keys": ["bright"],
            "category_keys": ["flavor-profile"],
            "proposed_tags": [],
        },
    }
    write_task_file(path=workspace_root / "task.json", payload=task_file)

    repair_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert repair_result["status"] == "repair_required"
    assert len(repair_task["units"]) == 1

    repair_task["units"][0]["answer"] = valid_answer
    write_task_file(path=workspace_root / "task.json", payload=repair_task)

    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")

    assert grouping_result["status"] == "advance_to_grouping"
    assert sorted(unit["unit_id"] for unit in grouping_task["units"]) == [
        "knowledge::8",
        "knowledge::9",
    ]


def test_same_session_handoff_completes_after_one_grouping_pass(
    tmp_path: Path,
) -> None:
    block_count = KNOWLEDGE_GROUP_TASK_MAX_UNITS + 1
    workspace_root, state_path = _initialize_workspace_with_shards(
        tmp_path,
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [
                        {
                            "i": block_index,
                            "id": f"book.ks0000.nr:{block_index}",
                            "t": f"Knowledge block {block_index}",
                        }
                        for block_index in range(block_count)
                    ],
                },
                metadata={
                    "owned_block_indices": list(range(block_count)),
                    "owned_block_count": block_count,
                },
            )
        ],
    )

    classification_task = load_task_file(workspace_root / "task.json")
    for unit in classification_task["units"]:
        unit["answer"] = _valid_classification_answer()
    write_task_file(path=workspace_root / "task.json", payload=classification_task)

    first_grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    first_grouping_task = load_task_file(workspace_root / "task.json")

    assert first_grouping_result["status"] == "advance_to_grouping"
    assert first_grouping_result["grouping_transition_count"] == 1
    assert first_grouping_task["grouping_batch"]["current_batch_index"] == 1
    assert first_grouping_task["grouping_batch"]["total_batches"] == 1
    assert len(first_grouping_task["units"]) == block_count

    for unit in first_grouping_task["units"]:
        unit["answer"] = _grouping_answer()
    write_task_file(path=workspace_root / "task.json", payload=first_grouping_task)

    final_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert final_result["status"] == "completed_with_grouping"
    assert final_result["grouping_validation_count"] == 1
    assert final_result["grouping_transition_count"] == 1
    assert len(output_payload["block_decisions"]) == block_count
    assert output_payload["idea_groups"] == [
        {
            "group_id": "g01",
            "topic_label": "Heat control",
            "block_indices": list(range(block_count)),
        }
    ]


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
    grouping_task["units"][0]["answer"] = _grouping_answer()
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


def test_knowledge_same_session_cli_status_autodiscovers_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root, _state_path = _initialize_workspace(tmp_path)

    monkeypatch.chdir(workspace_root)
    monkeypatch.delenv("RECIPEIMPORT_KNOWLEDGE_SAME_SESSION_STATE_PATH", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["knowledge_same_session_handoff", "--status"],
    )

    exit_code = knowledge_same_session_main()
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == 0
    assert payload["mode"] == "initial"
    assert payload["stage_key"] == "nonrecipe_classify"


def test_knowledge_same_session_status_and_doctor_report_next_action(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    status = describe_knowledge_same_session_status(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    doctor = describe_knowledge_same_session_doctor(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert status["recommended_command"] == "python3 -m cookimport.llm.knowledge_same_session_handoff"
    assert status["expected_outputs_total"] == 1
    assert doctor["diagnosis_code"] == "awaiting_answers"
