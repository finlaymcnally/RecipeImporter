from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cookimport.llm.recipe_workspace_tools import (
    build_recipe_worker_scaffold,
    check_current_recipe_worker_draft,
    finalize_recipe_worker_drafts,
    install_current_recipe_worker_draft,
    install_recipe_worker_draft,
    prepare_recipe_worker_drafts,
    render_recipe_worker_current_task_brief,
    render_recipe_worker_feedback_brief,
    render_recipe_worker_shard_packet,
    render_recipe_worker_cli_script,
    stamp_recipe_worker_drafts,
    validate_recipe_worker_draft,
    write_recipe_worker_current_task_sidecars,
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
            "scratch_draft_path": "scratch/recipe-shard-0000-r0000-r0001.task-001.json",
            "result_path": "out/recipe-shard-0000-r0000-r0001.task-001.json",
        },
    }


def test_render_recipe_worker_briefs_include_prewritten_draft_paths() -> None:
    task_row = _build_task_row()

    current_brief = render_recipe_worker_current_task_brief(
        task_row=task_row,
        task_rows=[task_row],
    )
    feedback_brief = render_recipe_worker_feedback_brief(
        task_rows=[task_row],
        current_task_id="recipe-shard-0000-r0000-r0001.task-001",
    )

    assert "scratch_draft_path: scratch/recipe-shard-0000-r0000-r0001.task-001.json" in current_brief
    assert "python3 tools/recipe_worker.py check-current" in current_brief
    assert "python3 tools/recipe_worker.py install-current" in current_brief
    assert "repo already prewrote `scratch/` drafts" in feedback_brief
    assert "draft: `scratch/recipe-shard-0000-r0000-r0001.task-001.json`" in feedback_brief
    assert "CURRENT_TASK.md" in feedback_brief


def test_render_recipe_worker_shard_packet_packs_queue_contract_and_draft_paths() -> None:
    task_row = _build_task_row()

    packet = render_recipe_worker_shard_packet(
        task_rows=[task_row],
        current_task_id="recipe-shard-0000-r0000-r0001.task-001",
    )

    assert "# Recipe Shard Packet" in packet
    assert "Read this file first." in packet
    assert "draft: `scratch/recipe-shard-0000-r0000-r0001.task-001.json`" in packet
    assert "hint fallback: `hints/recipe-shard-0000-r0000-r0001.task-001.md`" in packet
    assert "Open raw `hints/*.md`, `in/*.json`, `OUTPUT_CONTRACT.md`, `examples/*.json`, or `tools/recipe_worker.py` only if" in packet


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
    write_recipe_worker_current_task_sidecars(
        workspace_root=workspace_root,
        task_rows=[task_row],
    )

    written_paths = prepare_recipe_worker_drafts(
        workspace_root=workspace_root,
        dest_dir=Path("scratch"),
    )

    assert written_paths == [
        workspace_root / "scratch" / "recipe-shard-0000-r0000-r0001.task-001.json"
    ]
    manifest_path = workspace_root / "scratch" / "_prepared_drafts.json"
    assert manifest_path.exists()
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["current_task_id"] == "recipe-shard-0000-r0000-r0001.task-001"
    assert manifest_payload["draft_paths"] == [
        "scratch/recipe-shard-0000-r0000-r0001.task-001.json"
    ]
    assert manifest_payload["task_packets"][0]["draft_path"] == (
        "scratch/recipe-shard-0000-r0000-r0001.task-001.json"
    )

    installed_paths = finalize_recipe_worker_drafts(
        workspace_root=workspace_root,
        draft_paths=written_paths,
    )

    assert installed_paths == [
        workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
    ]


def test_stamp_recipe_worker_drafts_rewrites_fragmentary_payloads(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    task_row = _build_task_row()
    (workspace_root / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps([task_row], indent=2),
        encoding="utf-8",
    )
    draft_path = workspace_root / "scratch" / "recipe-shard-0000-r0000-r0001.task-001.json"
    draft_path.write_text(
        json.dumps(build_recipe_worker_scaffold(task_row=task_row), indent=2),
        encoding="utf-8",
    )

    stamped_paths = stamp_recipe_worker_drafts(
        workspace_root=workspace_root,
        draft_paths=[draft_path],
        status="fragmentary",
        status_reason="insufficient source detail",
        warnings=["incomplete_recipe_source"],
    )

    assert stamped_paths == [draft_path]
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    assert payload == {
        "v": "1",
        "sid": "recipe-shard-0000-r0000-r0001.task-001",
        "r": [
            {
                "v": "1",
                "rid": "urn:recipe:test:toast",
                "st": "fragmentary",
                "sr": "insufficient source detail",
                "cr": None,
                "m": [],
                "mr": "not_applicable_fragmentary",
                "g": [],
                "w": ["incomplete_recipe_source"],
            }
        ],
    }


def test_install_current_recipe_worker_draft_advances_current_task(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    (workspace_root / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    first_task = _build_task_row()
    second_task = json.loads(json.dumps(_build_task_row()))
    second_task["task_id"] = "recipe-shard-0000-r0000-r0001.task-002"
    second_task["owned_ids"] = ["urn:recipe:test:tea"]
    second_task["input_payload"]["sid"] = "recipe-shard-0000-r0000-r0001.task-002"
    second_task["input_payload"]["ids"] = ["urn:recipe:test:tea"]
    second_task["input_payload"]["r"][0]["rid"] = "urn:recipe:test:tea"
    second_task["input_payload"]["r"][0]["h"]["n"] = "Tea"
    second_task["input_payload"]["r"][0]["h"]["i"] = ["1 cup water", "1 tea bag"]
    second_task["input_payload"]["r"][0]["h"]["s"] = ["Boil water.", "Steep the tea."]
    second_task["metadata"]["input_path"] = "in/recipe-shard-0000-r0000-r0001.task-002.json"
    second_task["metadata"]["hint_path"] = "hints/recipe-shard-0000-r0000-r0001.task-002.md"
    second_task["metadata"]["scratch_draft_path"] = "scratch/recipe-shard-0000-r0000-r0001.task-002.json"
    second_task["metadata"]["result_path"] = "out/recipe-shard-0000-r0000-r0001.task-002.json"
    task_rows = [first_task, second_task]
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps(task_rows, indent=2),
        encoding="utf-8",
    )
    write_recipe_worker_current_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
    )
    prepare_recipe_worker_drafts(
        workspace_root=workspace_root,
        dest_dir=Path("scratch"),
        task_rows=task_rows,
    )

    current_row, checked_draft_path = check_current_recipe_worker_draft(
        workspace_root=workspace_root,
    )
    assert current_row["task_id"] == "recipe-shard-0000-r0000-r0001.task-001"
    assert checked_draft_path.name == "recipe-shard-0000-r0000-r0001.task-001.json"

    _draft_path, output_path, next_task_id = install_current_recipe_worker_draft(
        workspace_root=workspace_root,
    )

    assert output_path == (
        workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
    )
    assert next_task_id == "recipe-shard-0000-r0000-r0001.task-002"
    current_task_payload = json.loads(
        (workspace_root / "current_task.json").read_text(encoding="utf-8")
    )
    assert current_task_payload["task_id"] == "recipe-shard-0000-r0000-r0001.task-002"
    assert "task_id: recipe-shard-0000-r0000-r0001.task-002" in (
        workspace_root / "CURRENT_TASK.md"
    ).read_text(encoding="utf-8")
    assert "No repo-written validation feedback exists yet for this task." in (
        workspace_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8")


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

    current_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "current"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Current Recipe Task" in current_result.stdout
    assert "check-current" in current_result.stdout

    next_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "next"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "No later task is queued" in next_result.stdout

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
    assert "manifest scratch/_prepared_drafts.json" in prepare_result.stdout

    stamp_result = subprocess.run(
        [
            sys.executable,
            "tools/recipe_worker.py",
            "stamp-status",
            "fragmentary",
            "insufficient source detail",
            str(draft_path),
        ],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "updated 1 draft to fragmentary" in stamp_result.stdout

    check_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "check", str(draft_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OK recipe-shard-0000-r0000-r0001.task-001" in check_result.stdout

    check_current_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "check-current"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OK recipe-shard-0000-r0000-r0001.task-001" in check_current_result.stdout
    assert "Validation status: OK." in (
        workspace_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8")

    install_current_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "install-current"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "out/recipe-shard-0000-r0000-r0001.task-001.json" in install_current_result.stdout
    assert (
        "Queue complete. No current task is active." in install_current_result.stdout
        or "re-open `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`"
        in install_current_result.stdout
    )

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
    installed_payload = json.loads(
        (
            workspace_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json"
        ).read_text(encoding="utf-8")
    )
    assert installed_payload["r"][0]["st"] == "fragmentary"


def test_recipe_worker_cli_install_current_advances_queue(tmp_path: Path) -> None:
    workspace_root = tmp_path / "worker-001"
    (workspace_root / "tools").mkdir(parents=True, exist_ok=True)
    (workspace_root / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace_root / "out").mkdir(parents=True, exist_ok=True)
    first_task = _build_task_row()
    second_task = json.loads(json.dumps(_build_task_row()))
    second_task["task_id"] = "recipe-shard-0000-r0000-r0001.task-002"
    second_task["owned_ids"] = ["urn:recipe:test:tea"]
    second_task["input_payload"]["sid"] = "recipe-shard-0000-r0000-r0001.task-002"
    second_task["input_payload"]["ids"] = ["urn:recipe:test:tea"]
    second_task["input_payload"]["r"][0]["rid"] = "urn:recipe:test:tea"
    second_task["metadata"]["input_path"] = "in/recipe-shard-0000-r0000-r0001.task-002.json"
    second_task["metadata"]["hint_path"] = "hints/recipe-shard-0000-r0000-r0001.task-002.md"
    second_task["metadata"]["scratch_draft_path"] = "scratch/recipe-shard-0000-r0000-r0001.task-002.json"
    second_task["metadata"]["result_path"] = "out/recipe-shard-0000-r0000-r0001.task-002.json"
    task_rows = [first_task, second_task]
    (workspace_root / "assigned_tasks.json").write_text(
        json.dumps(task_rows, indent=2),
        encoding="utf-8",
    )
    write_recipe_worker_current_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
    )
    prepare_recipe_worker_drafts(
        workspace_root=workspace_root,
        dest_dir=Path("scratch"),
        task_rows=task_rows,
    )
    (workspace_root / "tools" / "recipe_worker.py").write_text(
        render_recipe_worker_cli_script(),
        encoding="utf-8",
    )

    install_current_result = subprocess.run(
        [sys.executable, "tools/recipe_worker.py", "install-current"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "installed scratch/recipe-shard-0000-r0000-r0001.task-001.json -> out/recipe-shard-0000-r0000-r0001.task-001.json" in install_current_result.stdout
    assert "re-open `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md`" in install_current_result.stdout
    current_task_payload = json.loads(
        (workspace_root / "current_task.json").read_text(encoding="utf-8")
    )
    assert current_task_payload["task_id"] == "recipe-shard-0000-r0000-r0001.task-002"
