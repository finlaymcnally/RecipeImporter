from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.llm.knowledge_stage.planning import (
    _aggregate_knowledge_task_payloads,
    _build_knowledge_task_plans,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan


def test_build_knowledge_jobs_writes_packet_blocks_not_chunk_bundles(tmp_path: Path) -> None:
    out_dir = tmp_path / "knowledge"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Recipe title"},
            {"index": 1, "text": "1 cup flour"},
            {"index": 2, "text": "Heat matters."},
            {"index": 3, "text": "Cook slowly for control."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.2.3",
                category="other",
                block_start_index=2,
                block_end_index=3,
                block_indices=[2, 3],
                block_ids=["b2", "b3"],
            )
        ],
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=0,
                end_block_index=1,
                block_indices=[0, 1],
                source_block_ids=["b0", "b1"],
            )
        ],
        workbook_slug="fixturebook",
        out_dir=out_dir,
        context_blocks=1,
        prompt_target_count=1,
    )

    assert report.packets_written == 1
    payload = json.loads((out_dir / "fixturebook.kp0000.nr.json").read_text(encoding="utf-8"))
    assert payload["v"] == "1"
    assert payload["bid"] == "fixturebook.kp0000.nr"
    assert [block["i"] for block in payload["b"]] == [2, 3]
    assert payload["x"]["p"][0]["i"] == 1


def test_build_knowledge_jobs_bundles_packets_into_real_shards_when_target_count_is_low(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "knowledge"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Front matter"},
            {"index": 1, "text": "Technique one"},
            {"index": 2, "text": "Technique two"},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.1.1",
                category="other",
                block_start_index=1,
                block_end_index=1,
                block_indices=[1],
                block_ids=["b1"],
            ),
            NonRecipeSpan(
                span_id="nr.2.2",
                category="other",
                block_start_index=2,
                block_end_index=2,
                block_indices=[2],
                block_ids=["b2"],
            ),
        ],
        recipe_spans=[],
        workbook_slug="fixturebook",
        out_dir=out_dir,
        context_blocks=0,
        prompt_target_count=1,
    )

    assert report.packet_count_before_partition == 2
    assert report.packets_written == 2
    assert report.shards_written == 1
    assert set(report.packet_ids) == {"fixturebook.kp0000.nr", "fixturebook.kp0001.nr"}
    assert report.planning_warnings == []
    assert [entry.shard_id for entry in report.shard_entries] == ["fixturebook.ks0000.nr"]
    assert report.shard_entries[0].owned_ids == (
        "fixturebook.kp0000.nr",
        "fixturebook.kp0001.nr",
    )

    first_payload = json.loads((out_dir / "fixturebook.kp0000.nr.json").read_text(encoding="utf-8"))
    second_payload = json.loads((out_dir / "fixturebook.kp0001.nr.json").read_text(encoding="utf-8"))
    assert [block["i"] for block in first_payload["b"]] == [1]
    assert [block["i"] for block in second_payload["b"]] == [2]


def test_build_knowledge_jobs_keeps_all_packets_but_groups_them_when_prompt_target_is_below_packet_floor(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "knowledge"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "A" * 4000},
            {"index": 1, "text": "B" * 4000},
            {"index": 2, "text": "C" * 4000},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.0.3",
                category="other",
                block_start_index=0,
                block_end_index=3,
                block_indices=[0, 1, 2],
                block_ids=["b0", "b1", "b2"],
            )
        ],
        recipe_spans=[],
        workbook_slug="fixturebook",
        out_dir=out_dir,
        context_blocks=0,
        prompt_target_count=1,
    )

    assert report.packets_written == 3
    assert report.shards_written == 1
    assert sorted(path.name for path in out_dir.glob("*.json")) == [
        "fixturebook.kp0000.nr.json",
        "fixturebook.kp0001.nr.json",
        "fixturebook.kp0002.nr.json",
    ]
    assert report.planning_warnings == []
    assert [entry.shard_id for entry in report.shard_entries] == ["fixturebook.ks0000.nr"]
    assert report.shard_entries[0].owned_ids == (
        "fixturebook.kp0000.nr",
        "fixturebook.kp0001.nr",
        "fixturebook.kp0002.nr",
    )


def test_knowledge_task_planning_splits_multi_packet_shard_into_packet_tasks() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.kp0000.nr", "book.kp0001.nr"),
        input_payload={
            "sid": "book.ks0000.nr",
            "p": [
                {
                    "v": "1",
                    "bid": "book.kp0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                {
                    "v": "1",
                    "bid": "book.kp0001.nr",
                    "b": [{"i": 5, "t": "Use low heat."}],
                },
            ],
        },
        metadata={"owned_packet_ids": ["book.kp0000.nr", "book.kp0001.nr"]},
    )

    task_plans = _build_knowledge_task_plans(shard)

    assert [task_plan.task_id for task_plan in task_plans] == [
        "book.kp0000.nr",
        "book.kp0001.nr",
    ]
    assert all(task_plan.parent_shard_id == "book.ks0000.nr" for task_plan in task_plans)
    assert task_plans[0].manifest_entry.owned_ids == ("book.kp0000.nr",)
    assert task_plans[1].manifest_entry.owned_ids == ("book.kp0001.nr",)
    assert task_plans[0].manifest_entry.metadata["task_count"] == 2
    assert task_plans[0].manifest_entry.metadata["task_index"] == 1
    assert task_plans[1].manifest_entry.metadata["task_index"] == 2
    assert task_plans[0].manifest_entry.input_payload["bid"] == "book.kp0000.nr"
    assert task_plans[1].manifest_entry.input_payload["bid"] == "book.kp0001.nr"


def test_knowledge_task_aggregation_preserves_packet_order_and_missing_ids() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.kp0000.nr", "book.kp0001.nr"),
        input_payload={
            "sid": "book.ks0000.nr",
            "p": [
                {"v": "1", "bid": "book.kp0000.nr", "b": [{"i": 4, "t": "Whisk constantly."}]},
                {"v": "1", "bid": "book.kp0001.nr", "b": [{"i": 5, "t": "Use low heat."}]},
            ],
        },
    )

    payload, metadata = _aggregate_knowledge_task_payloads(
        shard=shard,
        task_payloads_by_task_id={
            "book.kp0001.nr": {
                "packet_id": "book.kp0001.nr",
                "block_decisions": [{"block_index": 5, "category": "other"}],
                "idea_groups": [],
            },
            "book.kp0000.nr": {
                "packet_id": "book.kp0000.nr",
                "block_decisions": [{"block_index": 4, "category": "knowledge"}],
                "idea_groups": [
                    {
                        "group_id": "idea-1",
                        "topic_label": "Whisking matters",
                        "block_indices": [4],
                        "snippets": [
                            {
                                "body": "Whisking keeps the sauce smooth.",
                                "evidence": [{"block_index": 4, "quote": "Whisk constantly."}],
                            }
                        ],
                    }
                ],
            },
        },
        task_validation_errors_by_task_id={"book.kp0001.nr": (), "book.kp0000.nr": ()},
    )

    assert payload["shard_id"] == "book.ks0000.nr"
    assert [packet["packet_id"] for packet in payload["packet_results"]] == [
        "book.kp0000.nr",
        "book.kp0001.nr",
    ]
    assert metadata["accepted_task_ids"] == ["book.kp0000.nr", "book.kp0001.nr"]
    assert metadata["missing_packet_ids"] == []

    partial_payload, partial_metadata = _aggregate_knowledge_task_payloads(
        shard=shard,
        task_payloads_by_task_id={
            "book.kp0000.nr": {
                "packet_id": "book.kp0000.nr",
                "block_decisions": [{"block_index": 4, "category": "other"}],
                "idea_groups": [],
            }
        },
        task_validation_errors_by_task_id={"book.kp0001.nr": ("schema_invalid",)},
    )

    assert [packet["packet_id"] for packet in partial_payload["packet_results"]] == [
        "book.kp0000.nr"
    ]
    assert partial_metadata["missing_packet_ids"] == ["book.kp0001.nr"]
    assert partial_metadata["fallback_task_ids"] == ["book.kp0001.nr"]
