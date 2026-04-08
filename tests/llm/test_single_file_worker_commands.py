from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.editable_task_file import build_task_file, write_task_file
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1
from cookimport.llm.single_file_worker_commands import (
    build_single_file_worker_surface,
    main as single_file_command_main,
)


def _classification_task_file(tmp_path: Path) -> dict[str, object]:
    task_file, _unit_to_shard = build_knowledge_classification_task_file(
        assignment=WorkerAssignmentV1(
            worker_id="worker-001",
            shard_ids=("book.ks0000.nr",),
            workspace_root=str(tmp_path),
        ),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [
                        {"i": 4, "t": "Whisk constantly."},
                        {"i": 5, "t": "Low heat keeps eggs smooth."},
                    ],
                },
                input_text=None,
                metadata={},
            )
        ],
    )
    return task_file


def _valid_classification_answer() -> dict[str, object]:
    return {
        "category": "knowledge",
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


def test_task_summary_reports_direct_batch_progress_for_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_task_file(path=tmp_path / "task.json", payload=_classification_task_file(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert single_file_command_main(["task-summary"]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["current_unit_id"] == "knowledge::4"
    assert summary["required_answer_keys"] == ["category", "grounding"]
    assert "workflow" not in summary
    assert "helper_commands" not in summary
    assert "answer_schema_summary" not in summary


def test_queue_helpers_are_unavailable_for_direct_batch_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_task_file(path=tmp_path / "task.json", payload=_classification_task_file(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="open task.json directly"):
        single_file_command_main(["task-show-current"])
    with pytest.raises(SystemExit, match="open task.json directly"):
        single_file_command_main(["task-next"])
    with pytest.raises(SystemExit, match="edit task.json directly"):
        single_file_command_main(
            ["task-answer-current", json.dumps(_valid_classification_answer())]
        )


def test_task_template_and_apply_are_unavailable_for_recipe_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_file = build_task_file(
        stage_key="recipe_refine",
        assignment_id="worker-001",
        worker_id="worker-001",
        units=[
            {
                "unit_id": "line::0",
                "owned_id": "0",
                "evidence": {"atomic_index": 0, "text": "Line 0"},
                "answer": {},
            }
        ],
        helper_commands=build_single_file_worker_surface(stage_key="recipe_refine").helper_commands,
        workflow=build_single_file_worker_surface(stage_key="recipe_refine").workflow,
        answer_schema={
            "required_keys": ["label"],
            "example_answers": [{"label": "RECIPE_NOTES"}],
        },
    )
    write_task_file(path=tmp_path / "task.json", payload=task_file)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="edit task.json directly"):
        single_file_command_main(["task-template", "answers.json"])
    with pytest.raises(SystemExit, match="edit task.json directly"):
        single_file_command_main(["task-apply", "answers.json"])


def test_task_apply_is_unavailable_for_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_task_file(path=tmp_path / "task.json", payload=_classification_task_file(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="edit task.json directly"):
        single_file_command_main(["task-apply", "answers.json"])


def test_single_file_shims_redirect_task_dump_listing_and_inline_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_task_file(path=tmp_path / "task.json", payload=_classification_task_file(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert single_file_command_main(["--shim", "cat", "task.json"]) == 0
    assert capsys.readouterr().err == ""

    assert single_file_command_main(["--shim", "ls"]) == 0
    assert capsys.readouterr().err == ""

    assert (
        single_file_command_main(
            [
                "--shim",
                "python3",
                "-c",
                'from pathlib import Path; Path("task.json").write_text("{}")',
            ]
        )
        == 0
    )
    assert "Edit task.json directly" in capsys.readouterr().err
