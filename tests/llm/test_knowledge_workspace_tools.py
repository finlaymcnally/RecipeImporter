from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import cookimport.llm.knowledge_workspace_tools as knowledge_tools_module
from cookimport.llm.knowledge_workspace_tools import (
    build_knowledge_workspace_contract_examples,
    check_workspace_draft,
    current_batch_task_draft_path,
    install_current_batch_drafts,
    render_knowledge_worker_script,
    install_workspace_draft,
    render_current_task_feedback_text,
    write_current_batch_and_task_sidecars,
    write_current_task_sidecars,
)


def test_contract_examples_prefer_representative_knowledge_chunk() -> None:
    tasks = [
        {
            "task_id": "task-001",
            "metadata": {},
            "input_payload": {
                "v": "2",
                "bid": "task-001",
                "c": [
                    {
                        "cid": "front-matter",
                        "b": [
                            {
                                "i": 1,
                                "t": "PRAISE FOR THIS BOOK",
                                "hl": 1,
                            }
                        ],
                    },
                    {
                        "cid": "knowledge-chunk",
                        "b": [
                            {
                                "i": 2,
                                "t": (
                                    "Keep the heat gentle and stir steadily so milk sauces stay "
                                    "smooth instead of tightening into curds."
                                ),
                            }
                        ],
                    },
                ],
            },
        }
    ]

    examples = build_knowledge_workspace_contract_examples(tasks=tasks)
    valid_row = next(
        row
        for row in examples["valid_semantic_packet.json"]["chunk_results"]
        if row["chunk_id"] == "knowledge-chunk"
    )
    invalid_row = next(
        row
        for row in examples["invalid_echo_packet.json"]["chunk_results"]
        if row["chunk_id"] == "knowledge-chunk"
    )

    valid_snippet = valid_row["snippets"][0]
    invalid_snippet = invalid_row["snippets"][0]
    invalid_quote_surface = " ".join(
        evidence["quote"] for evidence in invalid_snippet["evidence"]
    )

    assert valid_row["is_useful"] is True
    assert valid_row["reason_code"] == "technique_or_mechanism"
    assert "PRAISE FOR THIS BOOK" not in valid_snippet["body"]
    assert valid_snippet["body"] != valid_snippet["evidence"][0]["quote"]
    assert invalid_snippet["body"] == invalid_quote_surface
    assert "milk sauces stay smooth" in invalid_quote_surface
    assert examples["valid_all_other_low_utility_packet.json"]["chunk_results"][0]["reason_code"] == (
        "true_but_low_utility"
    )
    assert examples["valid_all_other_framing_packet.json"]["chunk_results"][0]["reason_code"] == (
        "book_framing_or_marketing"
    )


def test_scaffold_task_payload_marks_strong_cue_packets_as_review_required() -> None:
    task_row = {
        "task_id": "task-strong-cue",
        "owned_ids": ["chunk-001"],
        "metadata": {
            "strong_knowledge_cue": True,
        },
    }
    input_payload = {
        "v": "2",
        "bid": "task-strong-cue",
        "c": [
            {
                "cid": "chunk-001",
                "b": [{"i": 1, "t": "Use low heat and stir steadily."}],
            }
        ],
    }

    payload = knowledge_tools_module.scaffold_task_payload(
        task_row=task_row,
        input_payload=input_payload,
    )

    assert payload["chunk_results"][0]["reason_code"] == "strong_cue_review_required"


def test_install_workspace_draft_reports_actionable_snippet_copy_guidance(
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
        "owned_ids": ["chunk-001"],
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
        json.dumps(
            {
                "v": "2",
                "bid": "task-001",
                "c": [
                    {
                        "cid": "chunk-001",
                        "b": [
                            {
                                "i": 7,
                                "t": quote,
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
    draft_path = workspace_root / "scratch" / "task-001.json"
    draft_path.write_text(
        json.dumps(
            {
                "packet_id": "task-001",
                "chunk_results": [
                    {
                        "chunk_id": "chunk-001",
                        "is_useful": True,
                        "block_decisions": [
                            {
                                "block_index": 7,
                                "category": "knowledge",
                                "reviewer_category": "knowledge",
                            }
                        ],
                        "snippets": [
                            {
                                "body": quote,
                                "evidence": [
                                    {
                                        "block_index": 7,
                                        "quote": quote,
                                    }
                                ],
                            }
                        ],
                        "reason_code": "technique_or_mechanism",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    check_result = check_workspace_draft(
        workspace_root=workspace_root,
        draft_path=draft_path,
    )
    assert check_result.valid is False
    assert "semantic_snippet_echoes_full_chunk" in check_result.errors

    feedback = render_current_task_feedback_text(
        task_row=task_row,
        check_result=check_result,
        current_draft_path=draft_path,
    )
    assert "copied evidence" in feedback
    assert "Run `check` again" in feedback

    with pytest.raises(ValueError) as exc_info:
        install_workspace_draft(
            workspace_root=workspace_root,
            draft_path=draft_path,
        )

    error_text = str(exc_info.value)
    assert "Chunk `chunk-001` snippet `0` copied evidence" in error_text
    assert "Keep each `evidence[].quote` verbatim" in error_text
    assert "Run `check` again" in error_text


def test_generated_knowledge_worker_cli_stays_in_sync_with_repo_feedback_contract(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "worker"
    for dirname in ("in", "out", "scratch", "tools"):
        (workspace_root / dirname).mkdir(parents=True, exist_ok=True)

    task_row = {
        "task_id": "task-001",
        "parent_shard_id": "task-001",
        "owned_ids": ["chunk-001"],
        "metadata": {
            "task_sequence": 1,
            "task_total": 2,
            "input_path": "in/task-001.json",
            "hint_path": "hints/task-001.md",
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
        json.dumps(
            {
                "v": "2",
                "bid": "task-001",
                "c": [
                    {
                        "cid": "chunk-001",
                        "b": [{"i": 7, "t": "Keep the heat gentle and stir steadily."}],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace_root / "tools" / "knowledge_worker.py").write_text(
        render_knowledge_worker_script(),
        encoding="utf-8",
    )
    draft_display_path = Path("scratch/current_task.json")
    write_current_task_sidecars(
        workspace_root=workspace_root,
        task_row=task_row,
        current_draft_path=draft_display_path,
    )

    complete_result = subprocess.run(
        [sys.executable, "tools/knowledge_worker.py", "debug", "complete-current"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "wrote current scaffold" in complete_result.stdout

    pending_feedback = (workspace_root / "CURRENT_TASK_FEEDBACK.md").read_text(encoding="utf-8")
    expected_pending_feedback = render_current_task_feedback_text(
        task_row=task_row,
        current_draft_path=draft_display_path,
    )
    assert pending_feedback == expected_pending_feedback

    draft_path = workspace_root / draft_display_path
    check_result = check_workspace_draft(
        workspace_root=workspace_root,
        draft_path=draft_path,
    )
    assert check_result.valid is True

    check_current_result = subprocess.run(
        [sys.executable, "tools/knowledge_worker.py", "debug", "check-current"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "OK task-001" in check_current_result.stdout

    valid_feedback = (workspace_root / "CURRENT_TASK_FEEDBACK.md").read_text(encoding="utf-8")
    expected_valid_feedback = render_current_task_feedback_text(
        task_row=task_row,
        check_result=check_result,
        current_draft_path=draft_display_path,
    )
    assert valid_feedback == expected_valid_feedback

    install_result = subprocess.run(
        [sys.executable, "tools/knowledge_worker.py", "debug", "install-current"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert knowledge_tools_module._INSTALL_CURRENT_SUCCESS_NOTICE in install_result.stdout  # noqa: SLF001


def test_install_current_batch_drafts_accepts_valid_prefix_and_advances_sidecars(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "worker"
    for dirname in ("in", "out", "scratch"):
        (workspace_root / dirname).mkdir(parents=True, exist_ok=True)

    task_rows = []
    for index, task_id in enumerate(("task-001", "task-002"), start=1):
        task_rows.append(
            {
                "task_id": task_id,
                "parent_shard_id": "parent-001",
                "owned_ids": [f"chunk-{index:03d}"],
                "metadata": {
                    "task_sequence": index,
                    "task_total": 2,
                    "input_path": f"in/{task_id}.json",
                    "hint_path": f"hints/{task_id}.md",
                    "result_path": f"out/{task_id}.json",
                },
            }
        )
        (workspace_root / "in" / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "v": "2",
                    "bid": task_id,
                    "c": [
                        {
                            "cid": f"chunk-{index:03d}",
                            "b": [{"i": index, "t": f"Tip {index}."}],
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps(task_rows, indent=2) + "\n",
        encoding="utf-8",
    )
    write_current_batch_and_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
        current_index=0,
        current_draft_path=Path("scratch/current_task.json"),
    )

    valid_payload = {
        "packet_id": "task-001",
        "chunk_results": [
            {
                "chunk_id": "chunk-001",
                "is_useful": False,
                "block_decisions": [
                    {
                        "block_index": 1,
                        "category": "other",
                        "reviewer_category": "other",
                    }
                ],
                "snippets": [],
                "reason_code": "not_cooking_knowledge",
            }
        ],
    }
    invalid_payload = {
        "packet_id": "task-002",
        "chunk_results": [],
    }
    current_batch_task_draft_path(workspace_root=workspace_root, task_id="task-001").parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    current_batch_task_draft_path(workspace_root=workspace_root, task_id="task-001").write_text(
        json.dumps(valid_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    current_batch_task_draft_path(workspace_root=workspace_root, task_id="task-002").write_text(
        json.dumps(invalid_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    batch_result, installed_task_ids = install_current_batch_drafts(
        workspace_root=workspace_root,
    )

    assert batch_result.valid is False
    assert installed_task_ids == ("task-001",)
    assert json.loads((workspace_root / "out" / "task-001.json").read_text(encoding="utf-8")) == valid_payload
    assert not (workspace_root / "out" / "task-002.json").exists()
    assert json.loads((workspace_root / "current_task.json").read_text(encoding="utf-8"))["task_id"] == "task-002"
    current_batch = json.loads((workspace_root / "current_batch.json").read_text(encoding="utf-8"))
    assert [task["task_id"] for task in current_batch["tasks"]] == ["task-002"]
