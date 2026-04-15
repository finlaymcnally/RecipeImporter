from __future__ import annotations

import inspect
import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import (
    build_knowledge_jobs,
    resolve_default_knowledge_packet_char_budgets,
)
from cookimport.llm.knowledge_stage.stage_plan import build_knowledge_stage_phase_plan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan
from tests.nonrecipe_stage_helpers import make_recipe_ownership_result


def _ownership(*, all_indices: list[int], owned_indices: list[int] | None = None) -> object:
    return make_recipe_ownership_result(
        owned_by_recipe_id={"urn:recipe:test:r0": list(owned_indices or [])},
        all_block_indices=all_indices,
    )


def test_build_knowledge_jobs_exposes_only_live_planner_controls(tmp_path: Path) -> None:
    assert list(inspect.signature(build_knowledge_jobs).parameters) == [
        "full_blocks",
        "candidate_spans",
        "recipe_ownership_result",
        "workbook_slug",
        "out_dir",
        "context_blocks",
        "prompt_target_count",
        "input_char_budget",
        "output_char_budget",
        "group_task_max_units",
    ]

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Recipe title"},
            {"index": 1, "text": "1 cup flour"},
            {"index": 2, "text": "Heat matters."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.2.3",
                category="knowledge",
                block_start_index=2,
                block_end_index=3,
                block_indices=[2],
                block_ids=["b2"],
            )
        ],
        recipe_ownership_result=_ownership(all_indices=[0, 1, 2], owned_indices=[0, 1]),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=1,
        prompt_target_count=1,
    )

    assert report.packets_written == 1
    assert report.shards_written == 1
    assert report.requested_shard_count == 1
    assert (
        report.packet_input_char_budget,
        report.packet_output_char_budget,
    ) == resolve_default_knowledge_packet_char_budgets(
        input_char_budget=None,
        output_char_budget=None,
    )
    payload = json.loads(
        (tmp_path / "knowledge" / "fixturebook.ks0000.nr.json").read_text(encoding="utf-8")
    )
    assert payload["bid"] == "fixturebook.ks0000.nr"
    assert [block["i"] for block in payload["b"]] == [2]


def test_build_knowledge_jobs_uses_prompt_target_as_shard_count(tmp_path: Path) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Technique {index}"}
            for index in range(5)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                block_start_index=index,
                block_end_index=index + 1,
                block_indices=[index],
                block_ids=[f"b{index}"],
            )
            for index in range(5)
        ],
        recipe_ownership_result=_ownership(all_indices=list(range(5))),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
        prompt_target_count=2,
    )

    assert report.packet_count_before_partition == 1
    assert report.requested_shard_count == 2
    assert report.packets_written == 2
    assert report.packet_ids == ["fixturebook.ks0000.nr", "fixturebook.ks0001.nr"]
    assert [entry.shard_id for entry in report.shard_entries] == [
        "fixturebook.ks0000.nr",
        "fixturebook.ks0001.nr",
    ]
    assert [entry.metadata["owned_block_indices"] for entry in report.shard_entries] == [
        [0, 1, 2],
        [3, 4],
    ]


def test_build_knowledge_jobs_splits_by_explicit_char_budgets_when_no_target_count_is_set(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": ("Technique " + str(index) + " ") * 12}
            for index in range(4)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                block_start_index=index,
                block_end_index=index + 1,
                block_indices=[index],
                block_ids=[f"b{index}"],
            )
            for index in range(4)
        ],
        recipe_ownership_result=_ownership(all_indices=list(range(4))),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
        input_char_budget=320,
        output_char_budget=220,
    )

    assert report.packets_written == 4
    assert report.requested_shard_count == 4
    assert report.packet_input_char_budget == 320
    assert report.packet_output_char_budget == 220
    assert [entry.metadata["owned_block_indices"] for entry in report.shard_entries] == [
        [0],
        [1],
        [2],
        [3],
    ]
    assert all(entry.metadata["input_char_budget"] == 320 for entry in report.shard_entries)
    assert all(entry.metadata["output_char_budget"] == 220 for entry in report.shard_entries)


def test_default_knowledge_packet_budgets_are_rebased_on_survivability() -> None:
    input_budget, output_budget = resolve_default_knowledge_packet_char_budgets(
        input_char_budget=None,
        output_char_budget=None,
    )

    assert input_budget == 264_000
    assert output_budget == 72_000


def test_build_knowledge_jobs_treats_prompt_target_count_as_hard_cap(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": ("Technique " + str(index) + " ") * 12}
            for index in range(4)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                block_start_index=index,
                block_end_index=index + 1,
                block_indices=[index],
                block_ids=[f"b{index}"],
            )
            for index in range(4)
        ],
        recipe_ownership_result=_ownership(all_indices=list(range(4))),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
        prompt_target_count=1,
        input_char_budget=320,
        output_char_budget=220,
    )

    assert report.packet_count_before_partition == 4
    assert report.requested_shard_count == 1
    assert report.shards_written == 1
    assert report.packets_written == 1
    assert report.packet_ids == ["fixturebook.ks0000.nr"]
    assert [entry.metadata["owned_block_indices"] for entry in report.shard_entries] == [
        [0, 1, 2, 3]
    ]
    assert report.planning_warnings == [
        "knowledge_prompt_target_count is using the requested final shard count "
        "of 1; packet-budget planning would have split the queue into 4 shards."
    ]


def test_build_knowledge_stage_phase_plan_centralizes_worker_and_survivability_fields(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Technique {index}"}
            for index in range(4)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                block_start_index=index,
                block_end_index=index + 1,
                block_indices=[index],
                block_ids=[f"b{index}"],
            )
            for index in range(4)
        ],
        recipe_ownership_result=_ownership(all_indices=list(range(4))),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
        prompt_target_count=2,
    )

    phase_plan = build_knowledge_stage_phase_plan(
        build_report=report,
        pipeline_id="recipe.knowledge.packet.v1",
        surface_pipeline="codex-knowledge-candidate-v2",
        worker_count=2,
        worker_id_by_shard_id={
            "fixturebook.ks0000.nr": "worker-001",
            "fixturebook.ks0001.nr": "worker-002",
        },
        survivability_report={
            "minimum_safe_shard_count": 1,
            "binding_limit": "output",
            "survivability_verdict": "safe",
            "shards": [],
        },
    )

    assert phase_plan["requested_shard_count"] == 2
    assert phase_plan["budget_native_shard_count"] == 1
    assert phase_plan["launch_shard_count"] == 2
    assert phase_plan["minimum_safe_shard_count"] == 1
    assert [shard["worker_id"] for shard in phase_plan["shards"]] == [
        "worker-001",
        "worker-002",
    ]


def test_build_knowledge_jobs_caps_grouping_output_budget_by_group_task_max_units(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Technique {index}"}
            for index in range(80)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                block_start_index=index,
                block_end_index=index + 1,
                block_indices=[index],
                block_ids=[f"b{index}"],
            )
            for index in range(80)
        ],
        recipe_ownership_result=_ownership(all_indices=list(range(80))),
        workbook_slug="fixturebook",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
        input_char_budget=50_000,
        output_char_budget=6_000,
        group_task_max_units=40,
    )

    assert report.packet_count_before_partition == 1
    assert report.shards_written == 1
    assert report.shard_entries[0].metadata["estimated_pass1_output_chars"] == 3_936
    assert report.shard_entries[0].metadata["estimated_pass2_output_chars"] == 3_616


def test_build_knowledge_jobs_keeps_review_order_inside_each_shard(tmp_path: Path) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 4, "text": "Whisk constantly."},
            {"index": 5, "text": "Use low heat."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.4.6",
                category="knowledge",
                block_start_index=4,
                block_end_index=6,
                block_indices=[4, 5],
                block_ids=["b4", "b5"],
            )
        ],
        recipe_ownership_result=_ownership(all_indices=[4, 5]),
        workbook_slug="book",
        out_dir=tmp_path / "knowledge",
        context_blocks=0,
    )

    payload = json.loads((tmp_path / "knowledge" / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert report.shards_written == 1
    assert [block["i"] for block in payload["b"]] == [4, 5]
