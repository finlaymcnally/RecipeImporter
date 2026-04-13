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


def _classification_answer(category: str) -> dict[str, object]:
    return {"category": category}


def _grouping_answer(
    *,
    group_id: str = "g01",
    topic_label: str = "Heat control",
) -> dict[str, object]:
    return {
        "group_id": group_id,
        "topic_label": topic_label,
        "grounding": {
            "tag_keys": ["saute"],
            "category_keys": ["cooking-method"],
            "proposed_tags": [],
        },
        "why_no_existing_tag": None,
        "retrieval_query": None,
    }


def _group_span_answer(
    *,
    start_row_id: str = "r01",
    end_row_id: str = "r01",
    group_id: str = "g01",
    topic_label: str = "Heat control",
) -> dict[str, object]:
    answer = _grouping_answer(group_id=group_id, topic_label=topic_label)
    return {
        "groups": [
            {
                "group_id": answer["group_id"],
                "start_row_id": start_row_id,
                "end_row_id": end_row_id,
                "topic_label": answer["topic_label"],
                "grounding": answer["grounding"],
                "why_no_existing_tag": answer["why_no_existing_tag"],
                "retrieval_query": answer["retrieval_query"],
            }
        ]
    }


def _initialize_workspace(tmp_path: Path) -> tuple[Path, Path]:
    return _initialize_workspace_with_shards(tmp_path, shards=[_shard()])


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


def test_same_session_handoff_advances_to_grouping_and_projects_group_grounding(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    edited = deepcopy(task_file)
    edited["units"][0]["answer"] = _classification_answer("keep_for_review")
    write_task_file(path=workspace_root / "task.json", payload=edited)

    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    grouping_task = load_task_file(workspace_root / "task.json")

    assert classification_result["status"] == "advance_to_grouping"
    assert classification_result["classification_validation_count"] == 1
    assert grouping_task["stage_key"] == "knowledge_group"
    assert grouping_task["units"][0]["evidence"]["rows"][0]["classification"] == {
        "category": "keep_for_review"
    }

    grouping_task["units"][0]["answer"] = _group_span_answer()
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert grouping_result["status"] == "completed_with_grouping"
    assert grouping_result["grouping_validation_count"] == 1
    assert output_payload == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {
                "block_index": 8,
                "category": "knowledge",
                "grounding": {
                    "tag_keys": ["saute"],
                    "category_keys": ["cooking-method"],
                    "proposed_tags": [],
                },
            }
        ],
        "idea_groups": [
            {
                "group_id": "g01",
                "topic_label": "Heat control",
                "block_indices": [8],
                "grounding": {
                    "tag_keys": ["saute"],
                    "category_keys": ["cooking-method"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            }
        ],
    }


def test_same_session_handoff_completes_without_grouping_when_all_rows_are_other(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    task_file["units"][0]["answer"] = _classification_answer("other")
    write_task_file(path=workspace_root / "task.json", payload=task_file)

    result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "completed_without_grouping"
    assert result["final_output_shard_count"] == 1
    assert output_payload["block_decisions"] == [
        {
            "block_index": 8,
            "category": "other",
            "grounding": {
                "tag_keys": [],
                "category_keys": [],
                "proposed_tags": [],
            },
        }
    ]
    assert output_payload["idea_groups"] == []


def test_same_session_handoff_rewrites_invalid_grouping_answers_as_repair(
    tmp_path: Path,
) -> None:
    workspace_root, state_path = _initialize_workspace(tmp_path)

    task_file = load_task_file(workspace_root / "task.json")
    task_file["units"][0]["answer"] = _classification_answer("keep_for_review")
    write_task_file(path=workspace_root / "task.json", payload=task_file)
    classification_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )

    assert classification_result["status"] == "advance_to_grouping"

    grouping_task = load_task_file(workspace_root / "task.json")
    grouping_task["units"][0]["answer"] = {
        "groups": [
            {
                "group_id": "",
                "start_row_id": "r01",
                "end_row_id": "r01",
                "topic_label": "",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": [],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            }
        ]
    }
    write_task_file(path=workspace_root / "task.json", payload=grouping_task)

    repair_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    repair_task = load_task_file(workspace_root / "task.json")

    assert repair_result["status"] == "repair_required"
    assert repair_result["same_session_repair_rewrite_count"] == 1
    assert "knowledge_block_missing_group" in repair_result["validation_errors"]
    assert repair_task["mode"] == "repair"
    assert repair_task["stage_key"] == "knowledge_group"


def test_same_session_handoff_advances_across_multiple_grouping_batches(
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
        unit["answer"] = _classification_answer("keep_for_review")
    write_task_file(path=workspace_root / "task.json", payload=classification_task)

    first_grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    first_grouping_task = load_task_file(workspace_root / "task.json")

    assert first_grouping_result["status"] == "advance_to_grouping"
    assert first_grouping_task["grouping_batch"]["current_batch_index"] == 1
    assert first_grouping_task["grouping_batch"]["total_batches"] == 2
    assert len(first_grouping_task["units"]) == 1
    assert len(first_grouping_task["units"][0]["evidence"]["rows"]) == KNOWLEDGE_GROUP_TASK_MAX_UNITS

    first_grouping_task["units"][0]["answer"] = {
        "groups": [
            {
                "group_id": "g01",
                "start_row_id": "r01",
                "end_row_id": f"r{KNOWLEDGE_GROUP_TASK_MAX_UNITS:02d}",
                "topic_label": "Heat control",
                "grounding": {
                    "tag_keys": ["saute"],
                    "category_keys": ["cooking-method"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            }
        ]
    }
    write_task_file(path=workspace_root / "task.json", payload=first_grouping_task)

    second_grouping_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    second_grouping_task = load_task_file(workspace_root / "task.json")

    assert second_grouping_result["status"] == "advance_to_grouping"
    assert second_grouping_result["grouping_transition_count"] == 2
    assert second_grouping_task["grouping_batch"]["current_batch_index"] == 2
    assert second_grouping_task["grouping_batch"]["total_batches"] == 2
    assert len(second_grouping_task["units"]) == 1
    assert len(second_grouping_task["units"][0]["evidence"]["rows"]) == 1

    second_grouping_task["units"][0]["answer"] = _group_span_answer()
    write_task_file(path=workspace_root / "task.json", payload=second_grouping_task)

    final_result = advance_knowledge_same_session_handoff(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    output_payload = json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert final_result["status"] == "completed_with_grouping"
    assert final_result["grouping_validation_count"] == 2
    assert len(output_payload["block_decisions"]) == block_count
    assert output_payload["idea_groups"] == [
        {
            "group_id": "g01",
            "topic_label": "Heat control",
            "block_indices": list(range(block_count)),
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
            "why_no_existing_tag": None,
            "retrieval_query": None,
        }
    ]


def test_knowledge_same_session_cli_status_autodiscovers_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root, _state_path = _initialize_workspace(tmp_path)

    monkeypatch.chdir(workspace_root)
    monkeypatch.delenv("RECIPEIMPORT_KNOWLEDGE_SAME_SESSION_STATE_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["knowledge_same_session_handoff", "--status"])

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
