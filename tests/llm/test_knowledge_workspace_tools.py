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
    render_knowledge_worker_script,
    install_workspace_draft,
    render_current_task_feedback_text,
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
    assert "PRAISE FOR THIS BOOK" not in valid_snippet["body"]
    assert valid_snippet["body"] != valid_snippet["evidence"][0]["quote"]
    assert invalid_snippet["body"] == invalid_quote_surface
    assert "milk sauces stay smooth" in invalid_quote_surface


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
                        "reason_code": "grounded_useful",
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
        [sys.executable, "tools/knowledge_worker.py", "complete-current"],
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
        [sys.executable, "tools/knowledge_worker.py", "check-current"],
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
        [sys.executable, "tools/knowledge_worker.py", "install-current"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert knowledge_tools_module._INSTALL_CURRENT_SUCCESS_NOTICE in install_result.stdout  # noqa: SLF001
