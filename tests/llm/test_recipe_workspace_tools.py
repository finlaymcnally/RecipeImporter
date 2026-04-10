from __future__ import annotations

import json

from cookimport.llm.recipe_workspace_tools import (
    build_recipe_worker_scaffold,
    recipe_worker_task_paths,
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
                    "txt": "Toast\n1 slice bread\nToast the bread.",
                    "ev": [
                        [1, "Toast"],
                        [2, "1 slice bread"],
                        [3, "Toast the bread."],
                    ],
                    "w": [],
                }
            ],
        },
        "metadata": {
            "input_path": "in/recipe-shard-0000-r0000-r0001.task-001.json",
            "hint_path": "hints/recipe-shard-0000-r0000-r0001.task-001.md",
            "result_path": "out/recipe-shard-0000-r0000-r0001.task-001.json",
        },
    }


def _build_complex_task_row() -> dict[str, object]:
    task_row = json.loads(json.dumps(_build_task_row()))
    task_row["owned_ids"] = ["urn:recipe:test:tea"]
    task_row["input_payload"]["ids"] = ["urn:recipe:test:tea"]
    task_row["input_payload"]["r"][0]["rid"] = "urn:recipe:test:tea"
    task_row["input_payload"]["r"][0]["txt"] = (
        "Tea\n1 cup water\n1 tea bag\nBoil water.\nSteep the tea bag."
    )
    task_row["input_payload"]["r"][0]["ev"] = [
        [5, "Tea"],
        [6, "1 cup water"],
        [7, "1 tea bag"],
        [8, "Boil water."],
        [9, "Steep the tea bag."],
    ]
    return task_row


def _build_multi_ingredient_single_step_task_row() -> dict[str, object]:
    task_row = json.loads(json.dumps(_build_task_row()))
    task_row["owned_ids"] = ["urn:recipe:test:dressing"]
    task_row["input_payload"]["ids"] = ["urn:recipe:test:dressing"]
    task_row["input_payload"]["r"][0]["rid"] = "urn:recipe:test:dressing"
    task_row["input_payload"]["r"][0]["txt"] = (
        "Blue Cheese Dressing\n"
        "5 ounces blue cheese\n"
        "1/2 cup creme fraiche\n"
        "1 tablespoon vinegar\n"
        "Whisk everything together. Taste and adjust. Chill before serving."
    )
    task_row["input_payload"]["r"][0]["ev"] = [
        [1, "Blue Cheese Dressing"],
        [2, "5 ounces blue cheese"],
        [3, "1/2 cup creme fraiche"],
        [4, "1 tablespoon vinegar"],
        [5, "Whisk everything together. Taste and adjust. Chill before serving."],
    ]
    return task_row


def test_recipe_worker_task_paths_prefers_metadata_and_keeps_defaults() -> None:
    task_row = _build_task_row()

    assert recipe_worker_task_paths(task_row) == {
        "input_path": "in/recipe-shard-0000-r0000-r0001.task-001.json",
        "hint_path": "hints/recipe-shard-0000-r0000-r0001.task-001.md",
        "result_path": "out/recipe-shard-0000-r0000-r0001.task-001.json",
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
            "mr": "not_needed_single_step",
            "db": [],
            "g": [],
            "w": [],
        }
    ]


def test_build_recipe_worker_scaffold_fail_closed_when_hint_is_incomplete() -> None:
    task_row = _build_task_row()
    task_row["input_payload"]["r"][0]["txt"] = "Toast"
    task_row["input_payload"]["r"][0]["ev"] = [[1, "Toast"]]

    scaffold = build_recipe_worker_scaffold(task_row=task_row)

    assert scaffold["r"] == [
        {
            "v": "1",
            "rid": "urn:recipe:test:toast",
            "st": "fragmentary",
            "sr": "insufficient_source_detail",
            "cr": None,
            "m": [],
            "mr": "not_applicable_fragmentary",
            "db": [],
            "g": [],
            "w": [],
        }
    ]


def test_build_recipe_worker_scaffold_still_supports_legacy_hint_rows() -> None:
    task_row = _build_task_row()
    task_row["input_payload"]["r"][0] = {
        "rid": "urn:recipe:test:toast",
        "h": {
            "n": "Toast",
            "i": ["1 slice bread"],
            "s": ["Toast the bread."],
        },
    }

    scaffold = build_recipe_worker_scaffold(task_row=task_row)

    assert scaffold["r"][0]["st"] == "repaired"
    assert scaffold["r"][0]["cr"]["t"] == "Toast"


def test_validate_recipe_worker_draft_rejects_unexpected_keys_and_wrong_owned_ids() -> None:
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
                "db": [],
                "g": [],
                "w": [],
            }
        ],
    }

    errors = validate_recipe_worker_draft(task_row=_build_task_row(), payload=payload)

    assert any("root unexpected key `results`" in error for error in errors)
    assert any("r[0] unexpected key `recipe_id`" in error for error in errors)
    assert any("missing owned recipe ids: urn:recipe:test:toast" in error for error in errors)
    assert any("unexpected recipe ids:" in error for error in errors)


def test_build_recipe_worker_scaffold_prewrites_mapping_reason_for_complex_recipe() -> None:
    task_row = _build_complex_task_row()
    payload = build_recipe_worker_scaffold(task_row=task_row)

    assert validate_recipe_worker_draft(task_row=task_row, payload=payload) == []


def test_build_recipe_worker_scaffold_prewrites_mapping_reason_for_multi_ingredient_single_step_recipe() -> None:
    task_row = _build_multi_ingredient_single_step_task_row()
    payload = build_recipe_worker_scaffold(task_row=task_row)

    assert validate_recipe_worker_draft(task_row=task_row, payload=payload) == []


def test_validate_recipe_worker_draft_requires_mapping_reason_for_complex_repaired_recipe() -> None:
    task_row = _build_complex_task_row()
    payload = build_recipe_worker_scaffold(task_row=task_row)
    payload["r"][0]["mr"] = ""

    errors = validate_recipe_worker_draft(task_row=task_row, payload=payload)

    assert any("must explain an empty mapping" in error for error in errors)
