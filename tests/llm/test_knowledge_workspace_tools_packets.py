from __future__ import annotations

import json
from pathlib import Path

import pytest

import cookimport.llm.knowledge_workspace_tools as knowledge_tools_module
from cookimport.llm.knowledge_workspace_tools import (
    build_knowledge_workspace_contract_examples,
    check_workspace_draft,
    install_workspace_draft,
    render_current_task_feedback_text,
    render_knowledge_worker_script,
)


def test_contract_examples_are_packet_shaped() -> None:
    tasks = [
        {
            "task_id": "task-001",
            "metadata": {},
            "input_payload": {
                "v": "1",
                "bid": "task-001",
                "b": [
                    {"i": 1, "t": "PRAISE FOR THIS BOOK", "hl": 1},
                    {
                        "i": 2,
                        "t": (
                            "Keep the heat gentle and stir steadily so milk sauces stay "
                            "smooth instead of tightening into curds."
                        ),
                    },
                ],
            },
        }
    ]

    examples = build_knowledge_workspace_contract_examples(tasks=tasks)
    valid_payload = examples["valid_semantic_packet.json"]
    invalid_payload = examples["invalid_echo_packet.json"]

    assert valid_payload["packet_id"] == "task-001"
    assert "chunk_results" not in valid_payload
    assert "chunk_results" not in invalid_payload
    assert "reason_code" not in json.dumps(valid_payload, sort_keys=True)
    assert [row["block_index"] for row in valid_payload["block_decisions"]] == [1, 2]


def test_scaffold_task_payload_returns_packet_shape() -> None:
    payload = knowledge_tools_module.scaffold_task_payload(
        task_row={
            "task_id": "task-strong-cue",
            "owned_ids": ["task-strong-cue"],
            "metadata": {"strong_knowledge_cue": True},
        },
        input_payload={
            "v": "1",
            "bid": "task-strong-cue",
            "b": [{"i": 1, "t": "Use low heat and stir steadily."}],
        },
    )

    assert payload == {
        "packet_id": "task-strong-cue",
        "block_decisions": [
            {
                "block_index": 1,
                "category": "other",
                "reviewer_category": "other",
            }
        ],
        "idea_groups": [],
    }


def test_install_workspace_draft_reports_packet_snippet_copy_guidance(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "worker"
    (workspace_root / "in").mkdir(parents=True)
    (workspace_root / "out").mkdir()
    (workspace_root / "scratch").mkdir()

    quote = (
        "Keep the heat gentle and stir steadily so milk sauces stay smooth instead "
        "of tightening into curds."
    )
    task_row = {
        "task_id": "task-001",
        "parent_shard_id": "task-001",
        "owned_ids": ["task-001"],
        "metadata": {
            "input_path": "in/task-001.json",
            "result_path": "out/task-001.json",
        },
    }
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "current_task.json").write_text(
        json.dumps(task_row, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "in" / "task-001.json").write_text(
        json.dumps({"v": "1", "bid": "task-001", "b": [{"i": 7, "t": quote}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    draft_path = workspace_root / "scratch" / "task-001.json"
    draft_path.write_text(
        json.dumps(
            {
                "packet_id": "task-001",
                "block_decisions": [
                    {
                        "block_index": 7,
                        "category": "knowledge",
                        "reviewer_category": "knowledge",
                    }
                ],
                "idea_groups": [
                    {
                        "group_id": "idea-1",
                        "topic_label": "Gentle heat keeps milk sauces smooth",
                        "block_indices": [7],
                        "snippets": [
                            {
                                "body": quote,
                                "evidence": [{"block_index": 7, "quote": quote}],
                            }
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    check_result = check_workspace_draft(workspace_root=workspace_root, draft_path=draft_path)
    assert check_result.valid is False
    assert check_result.errors == ("semantic_snippet_copies_evidence_quote",)

    feedback = render_current_task_feedback_text(
        task_row=task_row,
        check_result=check_result,
        current_draft_path=draft_path,
    )
    assert "Failure class: `snippet_copy_only`" in feedback
    assert "Run `check` again" in feedback

    with pytest.raises(ValueError, match="knowledge draft failed validation"):
        install_workspace_draft(workspace_root=workspace_root, draft_path=draft_path)


def test_generated_knowledge_worker_script_uses_packet_contract() -> None:
    script = render_knowledge_worker_script()

    assert "packet_id" in script
    assert "block_decisions" in script
    assert "idea_groups" in script
