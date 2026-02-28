from __future__ import annotations

import json

from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1
from cookimport.staging.writer import write_draft_outputs


def _candidate_for_priority6() -> RecipeCandidate:
    return RecipeCandidate(
        name="Priority 6 Roast",
        recipe_yield="Serves 4",
        ingredients=["1 chicken"],
        instructions=[
            "Preheat oven to 400F.",
            "Bake for 20 minutes or 30 minutes.",
            "Check internal temperature reaches 165F.",
        ],
    )


def test_draft_v1_priority6_emits_scored_yield_and_max_oven_temp() -> None:
    draft = recipe_candidate_to_draft_v1(
        _candidate_for_priority6(),
        instruction_step_options={
            "p6_yield_mode": "scored_v1",
            "p6_time_total_strategy": "selective_sum_v1",
        },
    )

    recipe = draft["recipe"]
    assert recipe["yield_units"] == 4
    assert recipe["yield_phrase"] == "Serves 4"
    assert recipe["yield_unit_name"] == "serving"
    assert recipe["max_oven_temp_f"] == 400
    assert recipe["cook_time_seconds"] == 1800

    temperature_items = [
        item
        for step in draft["steps"]
        for item in step.get("temperature_items", [])
    ]
    assert temperature_items
    assert any(item["is_oven_like"] for item in temperature_items)
    assert any(not item["is_oven_like"] for item in temperature_items)


def test_draft_v1_priority6_time_strategy_keeps_legacy_sum_default() -> None:
    baseline = recipe_candidate_to_draft_v1(
        _candidate_for_priority6(),
        instruction_step_options={"p6_time_total_strategy": "sum_all_v1"},
    )
    selective = recipe_candidate_to_draft_v1(
        _candidate_for_priority6(),
        instruction_step_options={"p6_time_total_strategy": "selective_sum_v1"},
    )

    assert baseline["recipe"]["cook_time_seconds"] == 3000
    assert selective["recipe"]["cook_time_seconds"] == 1800


def test_draft_v1_priority6_debug_payload_opt_in() -> None:
    draft = recipe_candidate_to_draft_v1(
        _candidate_for_priority6(),
        instruction_step_options={
            "p6_emit_metadata_debug": True,
            "p6_yield_mode": "scored_v1",
        },
    )

    assert "_p6_debug" in draft
    assert draft["_p6_debug"]["max_oven_temp_f"] == 400
    assert draft["_p6_debug"]["yield_debug"]["yield_mode"] == "scored_v1"


def test_write_draft_outputs_writes_priority6_debug_sidecar(tmp_path) -> None:
    result = ConversionResult(
        recipes=[_candidate_for_priority6()],
        report=ConversionReport(),
        workbook="priority6",
        workbookPath="priority6.txt",
    )
    out_dir = tmp_path / "final drafts" / "priority6"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_draft_outputs(
        result,
        out_dir,
        instruction_step_options={
            "p6_emit_metadata_debug": True,
            "p6_yield_mode": "scored_v1",
        },
    )

    draft_payload = json.loads((out_dir / "r0.json").read_text(encoding="utf-8"))
    assert "_p6_debug" not in draft_payload

    sidecar_path = tmp_path / ".bench" / "priority6" / "p6_metadata_debug.jsonl"
    assert sidecar_path.exists()
    rows = [json.loads(line) for line in sidecar_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["recipe_id"]
    assert rows[0]["p6"]["yield_debug"]["yield_mode"] == "scored_v1"

