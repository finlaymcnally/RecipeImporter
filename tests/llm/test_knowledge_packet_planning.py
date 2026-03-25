from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
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
        source_hash="fixture",
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


def test_build_knowledge_jobs_keeps_one_shard_per_packet_when_target_count_is_too_low(
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
        source_hash="fixture",
        out_dir=out_dir,
        context_blocks=0,
        prompt_target_count=1,
    )

    assert report.packet_count_before_partition == 2
    assert report.packets_written == 2
    assert report.shards_written == 2
    assert set(report.packet_ids) == {"fixturebook.kp0000.nr", "fixturebook.kp0001.nr"}
    assert report.planning_warnings == [
        "knowledge prompt target count requested fewer shards than the packet floor; "
        "keeping one shard per packet so no review packet is dropped."
    ]

    first_payload = json.loads((out_dir / "fixturebook.kp0000.nr.json").read_text(encoding="utf-8"))
    second_payload = json.loads((out_dir / "fixturebook.kp0001.nr.json").read_text(encoding="utf-8"))
    assert [block["i"] for block in first_payload["b"]] == [1]
    assert [block["i"] for block in second_payload["b"]] == [2]


def test_build_knowledge_jobs_keeps_all_packets_when_prompt_target_is_below_packet_floor(
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
        source_hash="fixture",
        out_dir=out_dir,
        context_blocks=0,
        prompt_target_count=1,
    )

    assert report.packets_written == 3
    assert report.shards_written == 3
    assert sorted(path.name for path in out_dir.glob("*.json")) == [
        "fixturebook.kp0000.nr.json",
        "fixturebook.kp0001.nr.json",
        "fixturebook.kp0002.nr.json",
    ]
    assert report.planning_warnings == [
        "knowledge prompt target count requested fewer shards than the packet floor; "
        "keeping one shard per packet so no review packet is dropped."
    ]
