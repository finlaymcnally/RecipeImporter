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

    assert payloads[0]["v"] == "2"
    assert payloads[0]["g"]["r"] == [2, 3]

    for payload in payloads:
        assert "c" in payload
        for chunk_payload in payload["c"]:
            chunk_blocks = chunk_payload["b"]
            chunk_indices = {block["i"] for block in chunk_blocks}
            assert 2 not in chunk_indices
            assert 3 not in chunk_indices
            assert "h" not in chunk_payload

    table_hints = [
        block.get("th")
        for payload in payloads
        for chunk_payload in payload["c"]
        for block in chunk_payload["b"]
        if block["i"] in {4, 5}
    ]
    assert any(isinstance(hint, dict) and hint.get("id") == "tbl_demo" for hint in table_hints)

    # Context may include recipe blocks; ensure we captured at least one.
    context_indices = {
        block["i"]
        for payload in payloads
        for block in payload["x"].get("p", [])
    }
    assert 2 in context_indices or 3 in context_indices
    context_recipe_indices = {
        index
        for payload in payloads
        for index in payload["g"]["r"]
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
    compact_payload = next(payload for payload in compact_payloads if payload["c"][0]["b"][0]["i"] == 4)

    assert compact_payload["g"]["r"] == [2, 3]
    assert "block_id" not in compact_payload["c"][0]["b"][0]
    assert "features_subset" not in compact_payload["x"]["p"][0]
    table_hint = compact_payload["c"][0]["b"][0]["th"]
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
    assert report.shards_written < report.chunks_written
    assert any(len(payload["c"]) >= 2 for payload in payloads)


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
    assert report.shards_written == 1
    assert len(payloads) == 1
    assert len(payloads[0]["c"]) == 2


def test_build_knowledge_jobs_forces_requested_prompt_target_and_warns_on_char_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id=f"chunk-{index}",
                lane=ChunkLane.KNOWLEDGE,
                title=f"Topic {index}",
                text="X" * 8000,
                blockIds=[index],
            )
            for index in range(10)
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    in_dir = tmp_path / "prompt-target"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Block {index} " + ("X" * 8000)}
            for index in range(10)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.10",
                category="knowledge",
                block_start_index=0,
                block_end_index=10,
                block_indices=list(range(10)),
                block_ids=[f"b{index}" for index in range(10)],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=0,
        target_prompt_count=5,
    )

    payloads = _load_all_jobs(in_dir)
    assert report.shards_written == 5
    assert len(payloads) == 5
    assert [len(payload["c"]) for payload in payloads] == [2] * 5
    assert report.planning_warnings
    assert any("forced shard count 5 produced 5 shard(s)" in warning for warning in report.planning_warnings)
    assert any("char limit" in warning for warning in report.planning_warnings)


def test_build_knowledge_jobs_forces_requested_prompt_target_and_warns_on_oversized_bundles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id=f"chunk-{index}",
                lane=ChunkLane.KNOWLEDGE,
                title=f"Topic {index}",
                text="X" * 5000,
                blockIds=[index],
            )
            for index in range(6)
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    in_dir = tmp_path / "prompt-target-overflow"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Block {index} " + ("X" * 5000)}
            for index in range(6)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.6",
                category="knowledge",
                block_start_index=0,
                block_end_index=6,
                block_indices=list(range(6)),
                block_ids=[f"b{index}" for index in range(6)],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=0,
        target_prompt_count=2,
    )

    payloads = _load_all_jobs(in_dir)
    assert report.shards_written == 2
    assert len(payloads) == 2
    assert [len(payload["c"]) for payload in payloads] == [3, 3]
    assert report.planning_warnings
    assert any("forced shard count 2 produced 2 shard(s)" in warning for warning in report.planning_warnings)
    assert any("char limit" in warning for warning in report.planning_warnings)


def test_build_knowledge_jobs_warns_when_requested_shard_count_exceeds_chunk_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Acidity",
                text="Acid balances richness.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Salt",
                text="Salt sharpens flavor.",
                blockIds=[1],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    in_dir = tmp_path / "requested-shards-exceed-chunks"
    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Acid balances richness."},
            {"index": 1, "text": "Salt sharpens flavor."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.2",
                category="knowledge",
                block_start_index=0,
                block_end_index=2,
                block_indices=[0, 1],
                block_ids=["b0", "b1"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=0,
        target_prompt_count=5,
    )

    payloads = _load_all_jobs(in_dir)
    assert report.shards_written == 2
    assert len(payloads) == 2
    assert all(len(payload["c"]) == 1 for payload in payloads)
    assert any(
        "requested 5 shard(s), but only 2 non-empty shard(s) were possible from 2 chunk(s)"
        in warning
        for warning in report.planning_warnings
    )


def test_build_knowledge_jobs_omits_chunk_hint_objects_from_model_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-weak-knowledge",
                lane=ChunkLane.KNOWLEDGE,
                text=(
                    "This short explanatory paragraph mentions seasoning in passing without "
                    "tables, headings, or explicit tip structure, so the reviewer should see "
                    "the text without an overconfident deterministic lane. It keeps describing "
                    "the same idea in plain prose, but it never becomes a structured table, a "
                    "tip list, or a clearly signposted technique section, so the transport "
                    "should avoid turning that mild deterministic guess into model-facing fact."
                ),
                blockIds=[0],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    build_knowledge_jobs(
        full_blocks=[
            {
                "index": 4,
                "text": (
                    "This short explanatory paragraph mentions seasoning in passing without "
                    "tables, headings, or explicit tip structure, so the reviewer should see "
                    "the text without an overconfident deterministic lane. It keeps describing "
                    "the same idea in plain prose, but it never becomes a structured table, a "
                    "tip list, or a clearly signposted technique section, so the transport "
                    "should avoid turning that mild deterministic guess into model-facing fact."
                ),
            },
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

    payload = _load_all_jobs(tmp_path / "in")[0]
    assert "h" not in payload["c"][0]


def test_build_knowledge_jobs_keeps_noise_lane_chunks_for_llm_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-noise",
                lane=ChunkLane.NOISE,
                text=(
                    "Advertisement copy that a deterministic lane might label as noise, but "
                    "the LLM stage should still review it because semantic pruning is not trusted."
                ),
                blockIds=[0],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {
                "index": 4,
                "text": (
                    "Advertisement copy that a deterministic lane might label as noise, but "
                    "the LLM stage should still review it because semantic pruning is not trusted."
                ),
            },
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

    assert report.shards_written == 1
    assert report.chunks_written == 1
    assert report.skipped_chunk_count == 0
    assert report.skipped_lane_counts == {}
    payload = _load_all_jobs(tmp_path / "in")[0]
    assert payload["c"][0]["cid"] == "book.c0000.nr"


def test_build_knowledge_jobs_keeps_tiny_knowledge_chunks_for_llm_review(
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

    assert report.shards_written == 1
    assert report.chunks_written == 1
    assert report.skipped_chunk_count == 0
    assert report.skipped_lane_counts == {}
    payload = _load_all_jobs(tmp_path / "in")[0]
    assert payload["c"][0]["cid"] == "book.c0000.nr"


def test_build_knowledge_jobs_keeps_heading_menu_fragments_for_llm_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-heading-menu",
                lane=ChunkLane.KNOWLEDGE,
                title="Recipes and Recommendations",
                text="Recipes and Recommendations\nRoast Chicken\nPan Sauce\nBraised Lamb",
                blockIds=[0, 1, 2, 3],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 10, "text": "Recipes and Recommendations"},
            {"index": 11, "text": "Roast Chicken"},
            {"index": 12, "text": "Pan Sauce"},
            {"index": 13, "text": "Braised Lamb"},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.10.14",
                category="knowledge",
                block_start_index=10,
                block_end_index=14,
                block_indices=[10, 11, 12, 13],
                block_ids=["b10", "b11", "b12", "b13"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=tmp_path / "in",
    )

    assert report.shards_written == 1
    assert report.chunks_written == 1
    assert report.skipped_chunk_count == 0
    assert report.skipped_lane_counts == {}
    payload = _load_all_jobs(tmp_path / "in")[0]
    assert payload["c"][0]["cid"] == "book.c0000.nr"


def test_build_knowledge_jobs_does_not_mark_mixed_memoir_chunk_as_strong_knowledge_cue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-mixed-memoir",
                lane=ChunkLane.NOISE,
                text=(
                    "I set out to write this book after years of cooking with friends. "
                    "Salting meat early gives the salt time to diffuse into the muscle, "
                    "which helps it retain moisture. This book will change the way you cook."
                ),
                blockIds=[0, 1, 2],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "I set out to write this book after years of cooking with friends."},
            {
                "index": 1,
                "text": (
                    "Salting meat early gives the salt time to diffuse into the muscle, "
                    "which helps it retain moisture."
                ),
            },
            {"index": 2, "text": "This book will change the way you cook."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.other.0.3",
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
        out_dir=tmp_path / "in",
        context_blocks=0,
    )

    metadata = report.shard_entries[0].metadata
    assert metadata["chunk_utility_positive_cues_by_id"]["book.c0000.nr"] == [
        "actionable_technique",
    ]
    assert metadata["chunk_utility_negative_cues_by_id"]["book.c0000.nr"] == [
        "memoir_or_voice",
        "book_framing_or_marketing",
    ]
    assert metadata["chunk_utility_borderline_by_id"]["book.c0000.nr"] is True
    assert metadata["chunk_strong_negative_utility_cue_by_id"]["book.c0000.nr"] is True
    assert metadata["chunk_knowledge_cue_by_id"]["book.c0000.nr"] is False
