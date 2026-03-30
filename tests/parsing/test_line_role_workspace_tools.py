from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cookimport.parsing.line_role_workspace_tools import (
    LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
    LINE_ROLE_WORKER_TOOL_FILENAME,
    build_line_role_repair_request_payload,
    build_line_role_seed_output,
    build_line_role_seed_output_for_workspace,
    build_line_role_workspace_shard_metadata,
    render_line_role_current_phase_brief,
    render_line_role_worker_script,
    validate_line_role_output_payload,
)


def _write_workspace_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    workspace_root = tmp_path / "worker-root"
    for dirname in ("in", "hints", "out", "work", "repair", "tools"):
        (workspace_root / dirname).mkdir(parents=True, exist_ok=True)

    shard_id = "line-role-canonical-0001-a000000-a000001"
    input_payload = {
        "v": 1,
        "shard_id": shard_id,
        "rows": [
            [0, "L1", "1 cup flour"],
            [1, "L2", "Mix well."],
        ],
    }
    metadata = build_line_role_workspace_shard_metadata(
        shard_id=shard_id,
        input_payload=input_payload,
        input_path=f"in/{shard_id}.json",
        hint_path=f"hints/{shard_id}.md",
        work_path=f"work/{shard_id}.json",
        result_path=f"out/{shard_id}.json",
        repair_path=f"repair/{shard_id}.json",
    )
    shard_row = {
        "shard_id": shard_id,
        "owned_ids": ["0", "1"],
        "metadata": metadata,
    }
    (workspace_root / "assigned_shards.json").write_text(
        json.dumps([shard_row], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "current_phase.json").write_text(
        json.dumps(shard_row, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "CURRENT_PHASE.md").write_text(
        render_line_role_current_phase_brief(shard_row),
        encoding="utf-8",
    )
    (workspace_root / "CURRENT_PHASE_FEEDBACK.md").write_text(
        "# Current Phase Feedback\n\nEdit the current work ledger.\n",
        encoding="utf-8",
    )
    (workspace_root / "in" / f"{shard_id}.json").write_text(
        json.dumps(input_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace_root / "hints" / f"{shard_id}.md").write_text(
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
    (workspace_root / "work" / f"{shard_id}.json").write_text(
        json.dumps(
            build_line_role_seed_output_for_workspace(workspace_root, shard_row),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root, shard_row


def test_line_role_workspace_seed_output_and_validation() -> None:
    shard_row = {
        "input_payload": {
            "rows": [
                [10, "L1", "Salt"],
                [11, "L2", "Stir."],
            ]
        }
    }

    payload = build_line_role_seed_output(shard_row)

    assert payload == {
        "rows": [
            {"atomic_index": 10},
            {"atomic_index": 11},
        ]
    }
    errors, metadata = validate_line_role_output_payload(shard_row, payload)
    assert errors == ()
    assert metadata["owned_row_count"] == 2
    assert metadata["returned_row_count"] == 2
    assert metadata["accepted_atomic_indices"] == []
    assert metadata["unresolved_atomic_indices"] == [10, 11]


def test_line_role_workspace_shard_metadata_sets_owned_paths() -> None:
    metadata = build_line_role_workspace_shard_metadata(
        shard_id="line-role-canonical-0001-a000000-a000001",
        input_payload={"rows": [[0, "L1", "Salt"]]},
        input_path="in/line-role-canonical-0001-a000000-a000001.json",
        hint_path="hints/line-role-canonical-0001-a000000-a000001.md",
        work_path="work/line-role-canonical-0001-a000000-a000001.json",
        result_path="out/line-role-canonical-0001-a000000-a000001.json",
        repair_path="repair/line-role-canonical-0001-a000000-a000001.json",
    )

    assert metadata["work_path"] == "work/line-role-canonical-0001-a000000-a000001.json"
    assert metadata["repair_path"] == "repair/line-role-canonical-0001-a000000-a000001.json"


def test_line_role_workspace_seed_output_can_load_rows_from_metadata_input_path(
    tmp_path: Path,
) -> None:
    workspace_root, shard_row = _write_workspace_fixture(tmp_path)

    payload = build_line_role_seed_output_for_workspace(workspace_root, shard_row)

    assert payload == {
        "rows": [
            {"atomic_index": 0, "label": "INGREDIENT_LINE"},
            {"atomic_index": 1, "label": "INSTRUCTION_LINE"},
        ]
    }


def test_line_role_current_phase_brief_stays_metadata_only(tmp_path: Path) -> None:
    workspace_root, shard_row = _write_workspace_fixture(tmp_path)

    current_phase_payload = json.loads(
        (workspace_root / "current_phase.json").read_text(encoding="utf-8")
    )
    assert "input_payload" not in current_phase_payload

    brief_text = render_line_role_current_phase_brief(shard_row)

    assert "Current Line-Role Phase" in brief_text
    assert "Work ledger:" in brief_text
    assert "assigned_shards.json` is queue/ownership context only." in brief_text
    assert "1 cup flour" not in brief_text


def test_line_role_workspace_helper_cli_check_phase_and_install_phase(
    tmp_path: Path,
) -> None:
    workspace_root, shard_row = _write_workspace_fixture(tmp_path)
    script_path = workspace_root / "tools" / LINE_ROLE_WORKER_TOOL_FILENAME
    shard_id = str(shard_row["shard_id"])

    overview = subprocess.run(
        [sys.executable, str(script_path), "overview"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert overview.returncode == 0
    assert shard_id in overview.stdout
    assert "current" in overview.stdout

    show = subprocess.run(
        [sys.executable, str(script_path), "show"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert show.returncode == 0
    assert f"shard_id: {shard_id}" in show.stdout
    assert f"result_path: out/{shard_id}.json" in show.stdout
    assert f"work_path: work/{shard_id}.json" in show.stdout

    check = subprocess.run(
        [sys.executable, str(script_path), "check-phase"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0
    assert f"OK {shard_id}" in check.stdout

    install = subprocess.run(
        [sys.executable, str(script_path), "install-phase"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0
    assert f"out/{shard_id}.json" in install.stdout
    installed_payload = json.loads(
        (workspace_root / "out" / f"{shard_id}.json").read_text(encoding="utf-8")
    )
    assert installed_payload["rows"][0]["label"] == "INGREDIENT_LINE"
    assert installed_payload["rows"][1]["label"] == "INSTRUCTION_LINE"
    current_phase_payload = json.loads(
        (workspace_root / "current_phase.json").read_text(encoding="utf-8")
    )
    assert current_phase_payload["status"] == "completed"


def test_line_role_workspace_helper_cli_check_phase_rejects_wrong_order(
    tmp_path: Path,
) -> None:
    workspace_root, shard_row = _write_workspace_fixture(tmp_path)
    script_path = workspace_root / "tools" / LINE_ROLE_WORKER_TOOL_FILENAME
    shard_id = str(shard_row["shard_id"])
    bad_payload_path = workspace_root / "work" / f"{shard_id}.json"
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
        [sys.executable, str(script_path), "check-phase"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert check.returncode == 1
    assert "row_order_mismatch" in check.stdout
    repair_payload = json.loads(
        (workspace_root / "repair" / f"{shard_id}.json").read_text(encoding="utf-8")
    )
    assert repair_payload["repair_mode"] == "line_role"
    assert repair_payload["accepted_atomic_indices"] == []
    assert repair_payload["unresolved_atomic_indices"] == [0, 1]
    assert repair_payload["frozen_rows"] == []


def test_line_role_repair_request_payload_freezes_accepted_rows_only() -> None:
    shard_row = {
        "shard_id": "line-role-canonical-0001-a000000-a000002",
        "input_payload": {
            "rows": [
                [0, "L1", "Salt"],
                [1, "L2", "Stir."],
                [2, "L9", "Sidebar note"],
            ]
        },
    }
    payload = {
        "rows": [
            {"atomic_index": 0, "label": "INGREDIENT_LINE"},
            {"atomic_index": 999, "label": "RECIPE_NOTES"},
            {"atomic_index": 2, "label": "RECIPE_NOTES"},
        ]
    }

    errors, metadata = validate_line_role_output_payload(shard_row, payload)

    assert "unowned_atomic_index" in metadata["row_errors_by_atomic_index"]["999"]
    assert metadata["accepted_atomic_indices"] == [0, 2]
    assert metadata["unresolved_atomic_indices"] == [1]
    repair_payload = build_line_role_repair_request_payload(
        shard_row=shard_row,
        metadata=metadata,
        validation_errors=errors,
    )
    assert repair_payload["accepted_atomic_indices"] == [0, 2]
    assert repair_payload["unresolved_atomic_indices"] == [1]
    assert repair_payload["rows"] == [[1, "L2", "Stir."]]
    assert repair_payload["frozen_rows"] == [
        {"atomic_index": 0, "label": "INGREDIENT_LINE"},
        {"atomic_index": 2, "label": "RECIPE_NOTES"},
    ]


def test_line_role_validation_rejects_changes_to_frozen_rows() -> None:
    shard_row = {
        "input_payload": {
            "rows": [
                [0, "L1", "Salt"],
                [1, "L2", "Stir."],
            ]
        }
    }
    frozen_rows = [
        {"atomic_index": 0, "label": "INGREDIENT_LINE"},
    ]

    errors, metadata = validate_line_role_output_payload(
        shard_row,
        {
            "rows": [
                {"atomic_index": 0, "label": "RECIPE_NOTES"},
                {"atomic_index": 1, "label": "INSTRUCTION_LINE"},
            ]
        },
        frozen_rows_by_atomic_index=frozen_rows,
    )

    assert "frozen_row_modified:0" in errors
    assert metadata["accepted_atomic_indices"] == [1]
    assert metadata["unresolved_atomic_indices"] == [0]
