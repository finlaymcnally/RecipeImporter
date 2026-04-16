from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import (
    build_knowledge_jobs,
    resolve_default_knowledge_packet_char_budgets,
)
from cookimport.staging.nonrecipe_stage import NonRecipeSpan
from tests.nonrecipe_stage_helpers import make_recipe_ownership_result


def _load_jobs(in_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(in_dir.glob("*.json"))
    ]


def test_build_knowledge_jobs_writes_one_shard_ledger_per_planned_shard(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Preface"},
            {"index": 1, "text": "Toast"},
            {"index": 2, "text": "1 slice bread"},
            {"index": 3, "text": "Keep the heat gentle."},
            {"index": 4, "text": "Whisk constantly."},
            {"index": 5, "text": "Cool leftovers quickly."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.3.6",
                category="knowledge",
                row_start_index=3,
                row_end_index=6,
                row_indices=[3, 4, 5],
                row_ids=["b3", "b4", "b5"],
            )
        ],
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={"urn:recipe:test:r0": [1, 2]},
            all_block_indices=[0, 1, 2, 3, 4, 5],
        ),
        workbook_slug="book",
        out_dir=tmp_path / "in",
        context_blocks=2,
    )

    payloads = _load_jobs(tmp_path / "in")
    assert report.shards_written == 1
    assert report.packets_written == 1
    assert report.packet_ids == ["book.ks0000.nr"]
    assert [entry.shard_id for entry in report.shard_entries] == ["book.ks0000.nr"]
    assert [block["i"] for block in payloads[0]["b"]] == [3, 4, 5]
    assert "x" not in payloads[0]
    assert payloads[0]["g"]["r"] == [1, 2]


def test_build_knowledge_jobs_preserves_budget_native_packets_when_requested_count_is_only_a_cap(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Technique {index}"}
            for index in range(6)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id=f"nr.{index}.{index + 1}",
                category="knowledge",
                row_start_index=index,
                row_end_index=index + 1,
                row_indices=[index],
                row_ids=[f"b{index}"],
            )
            for index in range(6)
        ],
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={},
            all_block_indices=list(range(6)),
        ),
        workbook_slug="book",
        out_dir=tmp_path / "in",
        context_blocks=0,
        prompt_target_count=2,
    )

    payloads = _load_jobs(tmp_path / "in")
    assert report.shards_written == 1
    assert report.packets_written == 1
    assert [entry.shard_id for entry in report.shard_entries] == ["book.ks0000.nr"]
    assert [[block["i"] for block in payload["b"]] for payload in payloads] == [
        [0, 1, 2, 3, 4, 5]
    ]

def test_build_knowledge_jobs_is_idempotent(
    tmp_path: Path,
) -> None:
    kwargs = {
        "full_blocks": [
            {"index": 4, "text": "Use low heat."},
            {"index": 5, "text": "Whisk steadily."},
        ],
        "candidate_spans": [
            NonRecipeSpan(
                span_id="nr.4.6",
                category="knowledge",
                row_start_index=4,
                row_end_index=6,
                row_indices=[4, 5],
                row_ids=["b4", "b5"],
            )
        ],
        "recipe_ownership_result": make_recipe_ownership_result(
            owned_by_recipe_id={},
            all_block_indices=[4, 5],
        ),
        "workbook_slug": "book",
        "out_dir": tmp_path / "in",
        "context_blocks": 0,
    }

    first = build_knowledge_jobs(**kwargs)
    first_bytes = {
        path.name: path.read_bytes()
        for path in sorted((tmp_path / "in").glob("*.json"))
    }
    second = build_knowledge_jobs(**kwargs)
    second_bytes = {
        path.name: path.read_bytes()
        for path in sorted((tmp_path / "in").glob("*.json"))
    }

    assert first.shards_written == second.shards_written == 1
    assert first_bytes == second_bytes


def test_build_knowledge_jobs_metadata_is_shard_owned(
    tmp_path: Path,
) -> None:
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 7, "text": "Salt in layers."},
            {"index": 8, "text": "Rest dough before shaping."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.7.9",
                category="knowledge",
                row_start_index=7,
                row_end_index=9,
                row_indices=[7, 8],
                row_ids=["b7", "b8"],
            )
        ],
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={},
            all_block_indices=[7, 8],
        ),
        workbook_slug="book",
        out_dir=tmp_path / "in",
        context_blocks=0,
    )

    metadata = report.shard_entries[0].metadata
    assert metadata["packet_id"] == "book.ks0000.nr"
    assert metadata["packet_count"] == 1
    assert metadata["owned_block_indices"] == [7, 8]
    assert metadata["owned_block_count"] == 2
    assert metadata["source_span_ids"] == ["nr.7.9"]
    assert (
        metadata["input_char_budget"],
        metadata["output_char_budget"],
    ) == resolve_default_knowledge_packet_char_budgets(
        input_char_budget=None,
        output_char_budget=None,
    )
    assert metadata["estimated_input_chars_max"] >= metadata["estimated_pass2_input_chars"]
    assert metadata["estimated_output_chars_max"] >= metadata["estimated_pass2_output_chars"]
