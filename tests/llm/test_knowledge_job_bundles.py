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
    assert payloads[0]["bundle_version"] == "2"

    for payload in payloads:
        assert "chunks" in payload
        for chunk_payload in payload["chunks"]:
            chunk_blocks = chunk_payload["blocks"]
            chunk_indices = {block["block_index"] for block in chunk_blocks}
            assert 2 not in chunk_indices
            assert 3 not in chunk_indices
            assert "heuristics" in chunk_payload
            assert "suggested_lane" in chunk_payload["heuristics"]
            suggested_highlights = chunk_payload["heuristics"].get("suggested_highlights", [])
            assert isinstance(suggested_highlights, list)
            suggested_skip_reason = chunk_payload["heuristics"].get("suggested_skip_reason")
            assert suggested_skip_reason is None or isinstance(suggested_skip_reason, str)

    table_hints = [
        block.get("table_hint")
        for payload in payloads
        for chunk_payload in payload["chunks"]
        for block in chunk_payload["blocks"]
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
    compact_payload = next(payload for payload in compact_payloads if payload["chunks"][0]["block_start_index"] == 4)

    assert "context_recipe_block_indices" in compact_payload["guardrails"]
    assert compact_payload["guardrails"]["context_recipe_block_indices"] == [2, 3]
    assert "block_id" not in compact_payload["chunks"][0]["blocks"][0]
    assert "features_subset" not in compact_payload["context"]["blocks_before"][0]
    table_hint = compact_payload["chunks"][0]["blocks"][0]["table_hint"]
    assert "markdown" not in table_hint


def test_build_knowledge_jobs_bundles_neighboring_chunks_into_one_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0, 1],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Refrigerate leftovers promptly and warm gently.",
                blockIds=[2, 3],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    full_blocks = [
        {"index": 0, "text": "SAUCES"},
        {"index": 1, "text": "Always whisk constantly when adding butter."},
        {"index": 2, "text": "STORAGE"},
        {"index": 3, "text": "Refrigerate leftovers promptly and warm gently."},
    ]
    in_dir = tmp_path / "bundled"

    report = build_knowledge_jobs(
        full_blocks=full_blocks,
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.4",
                category="knowledge",
                block_start_index=0,
                block_end_index=4,
                block_indices=[0, 1, 2, 3],
                block_ids=[f"b{i}" for i in range(4)],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=1,
    )

    payloads = _load_all_jobs(in_dir)
    assert report.chunks_written >= 2
    assert report.jobs_written < report.chunks_written
    assert any(len(payload["chunks"]) >= 2 for payload in payloads)


def test_build_knowledge_jobs_bridges_small_gaps_between_neighboring_spans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(sequence, overrides=None):
        del overrides
        first_index = int(sequence[0]["index"])
        if first_index == 0:
            return [
                KnowledgeChunk(
                    id="chunk-0",
                    lane=ChunkLane.KNOWLEDGE,
                    title="Acidity",
                    text="Acid balances richness.",
                    blockIds=[0],
                )
            ]
        return [
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt sharpens flavor.",
                blockIds=[0],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    full_blocks = [
        {"index": 0, "text": "Acid balances richness."},
        {"index": 11, "text": "Salt sharpens flavor."},
    ]
    in_dir = tmp_path / "bridged"

    report = build_knowledge_jobs(
        full_blocks=full_blocks,
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.1",
                category="knowledge",
                block_start_index=0,
                block_end_index=1,
                block_indices=[0],
                block_ids=["b0"],
            ),
            NonRecipeSpan(
                span_id="nr.knowledge.11.12",
                category="knowledge",
                block_start_index=11,
                block_end_index=12,
                block_indices=[11],
                block_ids=["b11"],
            ),
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=1,
    )

    payloads = _load_all_jobs(in_dir)
    assert report.chunks_written == 2
    assert report.jobs_written == 1
    assert len(payloads) == 1
    assert len(payloads[0]["chunks"]) == 2


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
    assert report.chunks_written == 0
    assert report.skipped_chunk_count == 1
    assert report.skipped_lane_counts == {"noise": 1}
    assert sorted((tmp_path / "in").glob("*.json")) == []


def test_build_knowledge_jobs_skips_tiny_low_signal_knowledge_chunks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-low-signal",
                lane=ChunkLane.KNOWLEDGE,
                text="Short note.",
                blockIds=[0],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 4, "text": "Short note."},
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
    assert report.chunks_written == 0
    assert report.skipped_chunk_count == 1
    assert report.skipped_lane_counts == {"low_signal": 1}
    assert sorted((tmp_path / "in").glob("*.json")) == []
