from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cookimport.parsing.line_role_workspace_tools import (
    LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
    LINE_ROLE_WORKER_TOOL_FILENAME,
    build_line_role_scratch_draft_path,
    build_line_role_seed_output,
    build_line_role_workspace_task_metadata,
    render_line_role_worker_script,
    validate_line_role_output_payload,
)


def _write_workspace_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    workspace_root = tmp_path / "worker-root"
    (workspace_root / "in").mkdir(parents=True, exist_ok=True)
    (workspace_root / "hints").mkdir(parents=True, exist_ok=True)
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    (workspace_root / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace_root / "tools").mkdir(parents=True, exist_ok=True)

    task_id = "line-role-canonical-0001-a000000-a000001.task-001"
    input_payload = {
        "v": 1,
        "shard_id": task_id,
        "parent_shard_id": "line-role-canonical-0001-a000000-a000001",
        "context_before_rows": [],
        "rows": [
            [0, "L1", "1 cup flour"],
            [1, "L2", "Mix well."],
        ],
        "context_after_rows": [],
    }
    metadata = build_line_role_workspace_task_metadata(
        task_id=task_id,
        parent_shard_id="line-role-canonical-0001-a000000-a000001",
        input_payload=input_payload,
        input_path=f"in/{task_id}.json",
        hint_path=f"hints/{task_id}.md",
        result_path=f"out/{task_id}.json",
    )
    task_row = {
        "task_id": task_id,
        "task_kind": "line_role_label_packet",
        "parent_shard_id": "line-role-canonical-0001-a000000-a000001",
        "owned_ids": ["0", "1"],
        "input_payload": input_payload,
        "metadata": metadata,
    }
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "assigned_shards.json").write_text(
        json.dumps(
            [{"shard_id": "line-role-canonical-0001-a000000-a000001"}],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace_root / "current_task.json").write_text(
        json.dumps(task_row, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "in" / f"{task_id}.json").write_text(
        json.dumps(input_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "hints" / f"{task_id}.md").write_text(
        "# line-role hints\n",
        encoding="utf-8",
    )
    (workspace_root / "OUTPUT_CONTRACT.md").write_text(
        LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
        encoding="utf-8",
    )
    (workspace_root / "tools" / LINE_ROLE_WORKER_TOOL_FILENAME).write_text(
        render_line_role_worker_script(),
        encoding="utf-8",
    )
    (workspace_root / build_line_role_scratch_draft_path(task_id)).write_text(
        json.dumps(build_line_role_seed_output(task_row), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace_root, task_row


def test_line_role_workspace_seed_output_and_validation() -> None:
    task_row = {
        "input_payload": {
            "rows": [
                [10, "L1", "Salt"],
                [11, "L2", "Stir."],
            ]
        }
    }

    payload = build_line_role_seed_output(task_row)

    assert payload == {
        "rows": [
            {"atomic_index": 10, "label": "INGREDIENT_LINE"},
            {"atomic_index": 11, "label": "INSTRUCTION_LINE"},
        ]
    }
    errors, metadata = validate_line_role_output_payload(task_row, payload)
    assert errors == ()
    assert metadata["owned_row_count"] == 2
    assert metadata["returned_row_count"] == 2


def test_line_role_workspace_task_metadata_defaults_scratch_draft_path() -> None:
    metadata = build_line_role_workspace_task_metadata(
        task_id="line-role-canonical-0001-a000000-a000001.task-001",
        parent_shard_id="line-role-canonical-0001-a000000-a000001",
        input_payload={"rows": [[0, "L1", "Salt"]]},
        input_path="in/line-role-canonical-0001-a000000-a000001.task-001.json",
        hint_path="hints/line-role-canonical-0001-a000000-a000001.task-001.md",
        result_path="out/line-role-canonical-0001-a000000-a000001.task-001.json",
    )

    assert metadata["scratch_draft_path"] == (
        "scratch/line-role-canonical-0001-a000000-a000001.task-001.json"
    )


def test_line_role_workspace_helper_cli_prepare_all_check_and_finalize_all(
    tmp_path: Path,
) -> None:
    workspace_root, task_row = _write_workspace_fixture(tmp_path)
    script_path = workspace_root / "tools" / LINE_ROLE_WORKER_TOOL_FILENAME
    task_id = str(task_row["task_id"])
    draft_path = workspace_root / "scratch" / f"{task_id}.json"

    overview = subprocess.run(
        [sys.executable, str(script_path), "overview"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert overview.returncode == 0
    assert task_id in overview.stdout
    assert "current" in overview.stdout

    show = subprocess.run(
        [sys.executable, str(script_path), "show"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert show.returncode == 0
    assert f"task_id: {task_id}" in show.stdout
    assert f"result_path: out/{task_id}.json" in show.stdout
    assert f"scratch_draft_path: scratch/{task_id}.json" in show.stdout

    prepare = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "prepare-all",
            "--dest-dir",
            "scratch",
        ],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert prepare.returncode == 0
    assert draft_path.exists()
    assert "prepared 1 draft under scratch" in prepare.stdout

    check = subprocess.run(
        [sys.executable, str(script_path), "check", f"scratch/{task_id}.json"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0
    assert f"OK {task_id}" in check.stdout

    finalize = subprocess.run(
        [sys.executable, str(script_path), "finalize-all", "scratch"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert finalize.returncode == 0
    assert "installed 1 task output from scratch" in finalize.stdout
    installed_payload = json.loads(
        (workspace_root / "out" / f"{task_id}.json").read_text(encoding="utf-8")
    )
    assert installed_payload["rows"][0]["label"] == "INGREDIENT_LINE"
    assert installed_payload["rows"][1]["label"] == "INSTRUCTION_LINE"


def test_line_role_workspace_helper_cli_check_rejects_wrong_order(
    tmp_path: Path,
) -> None:
    workspace_root, task_row = _write_workspace_fixture(tmp_path)
    script_path = workspace_root / "tools" / LINE_ROLE_WORKER_TOOL_FILENAME
    task_id = str(task_row["task_id"])
    bad_payload_path = workspace_root / "scratch" / f"{task_id}.json"
    bad_payload_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"atomic_index": 1, "label": "INSTRUCTION_LINE"},
                    {"atomic_index": 0, "label": "INGREDIENT_LINE"},
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    check = subprocess.run(
        [sys.executable, str(script_path), "check", f"scratch/{task_id}.json"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert check.returncode == 1
    assert "row_order_mismatch" in check.stdout
