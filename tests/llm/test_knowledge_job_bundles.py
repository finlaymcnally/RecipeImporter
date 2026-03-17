from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.core.models import ChunkLane, KnowledgeChunk
from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan


def _load_all_jobs(in_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    for path in sorted(in_dir.glob("*.json")):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


def test_build_knowledge_jobs_writes_seed_nonrecipe_spans_and_is_idempotent(tmp_path: Path) -> None:
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

    job_paths = sorted(in_dir.glob("*.json"))
    assert job_paths, "Expected knowledge job bundles to be written."

    first_bytes = {path.name: path.read_bytes() for path in job_paths}
    payloads = _load_all_jobs(in_dir)

    assert "context_recipe_block_indices" in payloads[0]["guardrails"]

    for payload in payloads:
        chunk_blocks = payload["chunk"]["blocks"]
        chunk_indices = {block["block_index"] for block in chunk_blocks}
        assert 2 not in chunk_indices
        assert 3 not in chunk_indices

        assert "heuristics" in payload
        assert "suggested_lane" in payload["heuristics"]
        suggested_highlights = payload["heuristics"].get("suggested_highlights", [])
        assert isinstance(suggested_highlights, list)
        suggested_skip_reason = payload["heuristics"].get("suggested_skip_reason")
        assert suggested_skip_reason is None or isinstance(suggested_skip_reason, str)

    table_hints = [
        block.get("table_hint")
        for payload in payloads
        for block in payload["chunk"]["blocks"]
        if block["block_index"] in {4, 5}
    ]
    assert any(isinstance(hint, dict) and hint.get("table_id") == "tbl_demo" for hint in table_hints)

    # Context may include recipe blocks; ensure we captured at least one.
    context_indices = {
        block["block_index"]
        for payload in payloads
        for block in payload["context"].get("blocks_before", [])
    }
    assert 2 in context_indices or 3 in context_indices
    context_recipe_indices = {
        index
        for payload in payloads
        for index in payload["guardrails"]["context_recipe_block_indices"]
    }
    assert 2 in context_recipe_indices or 3 in context_recipe_indices

    # Idempotence: rerun yields identical JSON bytes.
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
    second_bytes = {path.name: path.read_bytes() for path in sorted(in_dir.glob("*.json"))}
    assert first_bytes == second_bytes


def test_build_knowledge_jobs_writes_compact_bundle_shape(tmp_path: Path) -> None:
    full_blocks = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "Narrative intro."},
        {"index": 2, "text": "Toast"},
        {"index": 3, "text": "1 slice bread"},
        {
            "index": 4,
            "text": "Technique: Whisk constantly to prevent curdling.",
            "page": 8,
            "spine_index": 2,
            "features": {"is_header_likely": False, "block_role": "body"},
            "table_hint": {
                "table_id": "tbl_demo",
                "caption": "Sauce Troubleshooting",
                "markdown": "| Symptom | Fix |\n| --- | --- |\n| Curdled | Whisk gently |",
                "row_index_in_table": 0,
            },
        },
        {"index": 5, "text": "Use low heat and add acid slowly."},
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
    compact_dir = tmp_path / "compact"

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
        out_dir=compact_dir,
        context_blocks=2,
    )

    compact_payloads = _load_all_jobs(compact_dir)
    compact_payload = next(
        payload
        for payload in compact_payloads
        if payload["chunk"]["block_start_index"] == 4
    )

    assert "context_recipe_block_indices" in compact_payload["guardrails"]
    assert compact_payload["guardrails"]["context_recipe_block_indices"] == [2, 3]
    assert "block_id" not in compact_payload["chunk"]["blocks"][0]
    assert "features_subset" not in compact_payload["context"]["blocks_before"][0]
    table_hint = compact_payload["chunk"]["blocks"][0]["table_hint"]
    assert "markdown" not in table_hint


def test_build_knowledge_jobs_skips_noise_lane_chunks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-noise",
                lane=ChunkLane.NOISE,
                text="Advertisement copy.",
                blockIds=[4],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 4, "text": "Advertisement copy."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.4.5",
                category="knowledge",
                block_start_index=4,
                block_end_index=5,
                block_indices=[4],
                block_ids=["b4"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=tmp_path / "in",
    )

    assert report.jobs_written == 0
    assert report.skipped_chunk_count == 1
    assert report.skipped_lane_counts == {"noise": 1}
    assert sorted((tmp_path / "in").glob("*.json")) == []
