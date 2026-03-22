from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cookimport.llm.recipe_workspace_tools import (
    build_recipe_worker_scaffold,
    finalize_recipe_worker_drafts,
    install_recipe_worker_draft,
    prepare_recipe_worker_drafts,
    render_recipe_worker_cli_script,
    validate_recipe_worker_draft,
)


def _build_task_row() -> dict[str, object]:
    return {
        "task_id": "recipe-shard-0000-r0000-r0001.task-001",
        "task_kind": "recipe_correction_recipe",
        "parent_shard_id": "recipe-shard-0000-r0000-r0001",
        "owned_ids": ["urn:recipe:test:toast"],
        "input_payload": {
            "v": "1",
            "sid": "recipe-shard-0000-r0000-r0001.task-001",
            "ids": ["urn:recipe:test:toast"],
            "r": [
                {
                    "rid": "urn:recipe:test:toast",
                    "h": {
                        "n": "Toast",
                        "i": ["1 slice bread"],
                        "s": ["Toast the bread."],
                    },
                }
            ],
        },
        "metadata": {
            "input_path": "in/recipe-shard-0000-r0000-r0001.task-001.json",
            "hint_path": "hints/recipe-shard-0000-r0000-r0001.task-001.md",
            "result_path": "out/recipe-shard-0000-r0000-r0001.task-001.json",
        },
    }


def test_build_recipe_worker_scaffold_uses_exact_task_and_recipe_ids() -> None:
    scaffold = build_recipe_worker_scaffold(task_row=_build_task_row())

    assert scaffold["sid"] == "recipe-shard-0000-r0000-r0001.task-001"
    assert scaffold["r"] == [
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
            "mr": None,
            "g": [],
            "w": [],
        }
    ]


def test_validate_recipe_worker_draft_rejects_legacy_keys_and_wrong_owned_ids() -> None:
    payload = {
        "v": "1",
        "sid": "recipe-shard-0000-r0000-r0001.task-001",
        "results": [],
        "r": [
            {
                "v": "1",
                "recipe_id": "urn:recipe:test:wrong",
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
                "mr": None,
                "g": [],
                "w": [],
            }
        ],
    }

    errors = validate_recipe_worker_draft(task_row=_build_task_row(), payload=payload)

    assert any("root legacy key `results`" in error for error in errors)
    assert any("legacy key `recipe_id`" in error for error in errors)
    assert any("missing owned recipe ids: urn:recipe:test:toast" in error for error in errors)
    assert any("unexpected recipe ids:" in error for error in errors)


def test_install_recipe_worker_draft_writes_declared_result_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    task_row = _build_task_row()
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2),
        encoding="utf-8",
    )
    draft_path = workspace_root / "scratch.json"
    draft_path.write_text(
        json.dumps(build_recipe_worker_scaffold(task_row=task_row), indent=2),
        encoding="utf-8",
    )

    installed_path = install_recipe_worker_draft(
        workspace_root=workspace_root,
        draft_path=draft_path,
    )

    assert installed_path == (
        workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
    )
    installed_payload = json.loads(installed_path.read_text(encoding="utf-8"))
    assert installed_payload["sid"] == "recipe-shard-0000-r0000-r0001.task-001"


def test_prepare_and_finalize_recipe_worker_drafts_batch(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    task_row = _build_task_row()
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2),
        encoding="utf-8",
    )

    written_paths = prepare_recipe_worker_drafts(
        workspace_root=workspace_root,
        dest_dir=Path("scratch"),
    )

    assert written_paths == [
        workspace_root / "scratch" / "recipe-shard-0000-r0000-r0001.task-001.json"
    ]

    installed_paths = finalize_recipe_worker_drafts(
        workspace_root=workspace_root,
        draft_paths=written_paths,
    )

    assert installed_paths == [
        workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
    ]


def test_recipe_worker_cli_prepare_all_check_and_finalize_all(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    (workspace_root / "tools").mkdir(parents=True, exist_ok=True)
    (workspace_root / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    task_row = _build_task_row()
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2),
        encoding="utf-8",
    )
    (workspace_root / "current_task.json").write_text(
        json.dumps(task_row, indent=2),
        encoding="utf-8",
    )
    (workspace_root / "tools" / "recipe_worker.py").write_text(
        render_recipe_worker_cli_script(),
        encoding="utf-8",
    )

    overview_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "overview"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "recipe-shard-0000-r0000-r0001.task-001 current" in overview_result.stdout

    prepare_result = subprocess.run(
        [
            sys.executable,
            "tools/recipe_worker.py",
            "prepare-all",
            "--dest-dir",
            "scratch",
        ],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    draft_path = workspace_root / "scratch" / "recipe-shard-0000-r0000-r0001.task-001.json"
    assert draft_path.exists()
    assert "prepared 1 draft under scratch" in prepare_result.stdout

    check_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "check", str(draft_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OK recipe-shard-0000-r0000-r0001.task-001" in check_result.stdout

    finalize_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "finalize-all", "scratch"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "installed 1 task output from scratch" in finalize_result.stdout
    assert (
        workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
    ).exists()
