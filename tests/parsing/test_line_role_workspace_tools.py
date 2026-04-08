from __future__ import annotations

import json
from pathlib import Path

from cookimport.parsing.line_role_workspace_tools import (
    build_line_role_workspace_scaffold,
    build_line_role_workspace_scaffold_for_workspace,
    build_line_role_workspace_shard_metadata,
    validate_line_role_output_payload,
)


def test_line_role_workspace_scaffold_and_validation() -> None:
    shard_row = {
        "input_payload": {
            "rows": [
                [10, "L1", "Salt"],
                [11, "L2", "Stir."],
            ]
        }
    }

    payload = build_line_role_workspace_scaffold(shard_row)

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
    assert metadata["owned_row_count"] == 1


def test_line_role_validation_accepts_ordered_label_vector() -> None:
    shard_row = {
        "input_payload": {
            "rows": [
                [10, "L1", "Salt"],
                [11, "L2", "Stir."],
            ]
        }
    }

    errors, metadata = validate_line_role_output_payload(
        shard_row,
        {"labels": ["INGREDIENT_LINE", "INSTRUCTION_LINE"]},
    )

    assert errors == ()
    assert metadata["ordered_label_vector"] == {
        "applied": True,
        "returned_label_count": 2,
        "expected_row_count": 2,
    }
    assert metadata["accepted_atomic_indices"] == [10, 11]
    assert metadata["unresolved_atomic_indices"] == []


def test_line_role_workspace_scaffold_can_load_rows_from_metadata_input_path(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "worker-root"
    workspace_root.mkdir(parents=True, exist_ok=True)
    shard_id = "line-role-canonical-0001-a000000-a000001"
    input_path = workspace_root / "in" / f"{shard_id}.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps({"rows": [[0, "1 cup flour"], [1, "Mix well."]]}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    shard_row = {
        "shard_id": shard_id,
        "metadata": {
            "input_path": f"in/{shard_id}.json",
        },
    }

    payload = build_line_role_workspace_scaffold_for_workspace(workspace_root, shard_row)

    assert payload == {
        "rows": [
            {"atomic_index": 0},
            {"atomic_index": 1},
        ]
    }


def test_line_role_validation_rejects_unowned_and_frozen_rows() -> None:
    shard_row = {
        "input_payload": {
            "rows": [
                [0, "L1", "Salt"],
                [1, "L2", "Stir."],
                [2, "L3", "Serve."],
            ]
        }
    }

    errors, metadata = validate_line_role_output_payload(
        shard_row,
        {
            "rows": [
                {"atomic_index": 0, "label": "RECIPE_NOTES"},
                {"atomic_index": 999, "label": "RECIPE_NOTES"},
                {"atomic_index": 2, "label": "RECIPE_NOTES"},
            ]
        },
        frozen_rows_by_atomic_index=[{"atomic_index": 0, "label": "INGREDIENT_LINE"}],
    )

    assert "row_order_mismatch" in errors
    assert "frozen_row_modified:0" in errors
    assert metadata["accepted_atomic_indices"] == [2]
    assert metadata["unresolved_atomic_indices"] == [0, 1]
    assert "unowned_atomic_index" in metadata["row_errors_by_atomic_index"]["999"]
