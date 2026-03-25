from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan


def _load_all_jobs(in_dir: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(in_dir.glob("*.json"))
    ]


def test_build_knowledge_jobs_writes_seed_nonrecipe_packets_and_is_idempotent(
    tmp_path: Path,
) -> None:
    full_blocks = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "A beautiful gorgeous stunning book."},
        {"index": 2, "text": "Toast"},
        {"index": 3, "text": "1 slice bread"},
        {
            "index": 4,
            "text": "Technique: To prevent curdling, whisk constantly.",
            "table_hint": {
                "table_id": "tbl_demo",
                "caption": "Sauce Troubleshooting",
                "markdown": "| Symptom | Fix |\n| --- | --- |\n| Curdled | Whisk gently |",
                "row_index_in_table": 0,
            },
        },
        {
            "index": 5,
            "text": "Use low heat and add acid slowly.",
            "table_hint": {
                "table_id": "tbl_demo",
                "caption": "Sauce Troubleshooting",
                "markdown": "| Symptom | Fix |\n| --- | --- |\n| Curdled | Whisk gently |",
                "row_index_in_table": 1,
            },
        },
        {"index": 6, "text": "More notes."},
        {"index": 7, "text": "End."},
    ]
    knowledge_spans = [
        NonRecipeSpan(
            span_id="nr.knowledge.4.8",
            category="knowledge",
            block_start_index=4,
            block_end_index=8,
            block_indices=[4, 5, 6, 7],
            block_ids=["b4", "b5", "b6", "b7"],
        )
    ]
    in_dir = tmp_path / "in"

    report = build_knowledge_jobs(
        full_blocks=full_blocks,
        candidate_spans=knowledge_spans,
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=2,
                end_block_index=4,
                block_indices=[2, 3],
                source_block_ids=["b2", "b3"],
            )
        ],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=2,
    )

    job_paths = sorted(in_dir.glob("*.json"))
    assert job_paths, "Expected knowledge job packets to be written."
    assert report.packets_written == 3
    assert report.shards_written == 3
    assert report.packet_ids == [
        "book.kp0000.nr",
        "book.kp0001.nr",
        "book.kp0002.nr",
    ]

    first_bytes = {path.name: path.read_bytes() for path in job_paths}
    payloads = _load_all_jobs(in_dir)

    assert all(payload["v"] == "1" for payload in payloads)
    assert all("c" not in payload for payload in payloads)
    assert [[block["i"] for block in payload["b"]] for payload in payloads] == [
        [4],
        [5],
        [6, 7],
    ]

    for payload in payloads:
        packet_indices = {block["i"] for block in payload["b"]}
        assert 2 not in packet_indices
        assert 3 not in packet_indices

    table_hints = [
        block.get("th")
        for payload in payloads
        for block in payload["b"]
        if block["i"] in {4, 5}
    ]
    assert all(isinstance(hint, dict) and hint.get("id") == "tbl_demo" for hint in table_hints)
    assert all("markdown" not in hint for hint in table_hints)

    context_indices = {
        block["i"]
        for payload in payloads
        for block in payload["x"].get("p", [])
    }
    assert 2 in context_indices or 3 in context_indices
    context_recipe_indices = {
        index
        for payload in payloads
        for index in (payload.get("g") or {}).get("r", [])
    }
    assert 2 in context_recipe_indices or 3 in context_recipe_indices

    build_knowledge_jobs(
        full_blocks=full_blocks,
        candidate_spans=knowledge_spans,
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=2,
                end_block_index=4,
                block_indices=[2, 3],
                source_block_ids=["b2", "b3"],
            )
        ],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=2,
    )
    second_bytes = {
        path.name: path.read_bytes() for path in sorted(in_dir.glob("*.json"))
    }
    assert first_bytes == second_bytes


def test_build_knowledge_jobs_partitions_large_spans_by_block_cap(tmp_path: Path) -> None:
    out_dir = tmp_path / "knowledge"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Block {index}"}
            for index in range(12)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.0.12",
                category="other",
                block_start_index=0,
                block_end_index=12,
                block_indices=list(range(12)),
                block_ids=[f"b{index}" for index in range(12)],
            )
        ],
        recipe_spans=[],
        workbook_slug="fixturebook",
        source_hash="fixture",
        out_dir=out_dir,
        context_blocks=0,
    )

    payloads = _load_all_jobs(out_dir)
    assert report.packets_written == 2
    assert report.shards_written == 2
    assert [[block["i"] for block in payload["b"]] for payload in payloads] == [
        list(range(10)),
        [10, 11],
    ]


def test_build_knowledge_jobs_metadata_is_packet_native(tmp_path: Path) -> None:
    out_dir = tmp_path / "knowledge"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 4, "text": "Keep the heat gentle."},
            {"index": 5, "text": "Whisk constantly."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.4.6",
                category="other",
                block_start_index=4,
                block_end_index=6,
                block_indices=[4, 5],
                block_ids=["b4", "b5"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=out_dir,
        context_blocks=0,
    )

    assert report.skipped_packet_count == 0
    assert report.skipped_packet_reason_counts == {}

    metadata = report.shard_entries[0].metadata
    assert metadata["packet_id"] == "book.kp0000.nr"
    assert metadata["owned_block_indices"] == [4, 5]
    assert metadata["packet_block_count"] == 2
    assert metadata["source_span_ids"] == ["nr.4.6"]
    assert metadata["task_count"] == 1
    assert metadata["task_index"] == 1
    assert "packet_char_count" in metadata
    assert not any(key.startswith("chunk_") for key in metadata)


def test_build_knowledge_jobs_warns_when_prompt_target_is_below_packet_floor(
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
        workbook_slug="book",
        source_hash="hash123",
        out_dir=out_dir,
        context_blocks=0,
        prompt_target_count=1,
    )

    assert report.packets_written == 3
    assert report.shards_written == 1
    assert report.planning_warnings == []
    assert [entry.shard_id for entry in report.shard_entries] == ["book.ks0000.nr"]
    assert report.shard_entries[0].owned_ids == (
        "book.kp0000.nr",
        "book.kp0001.nr",
        "book.kp0002.nr",
    )
