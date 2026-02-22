from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import build_pass4_knowledge_jobs


def _load_all_jobs(in_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    for path in sorted(in_dir.glob("*.json")):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


def test_build_pass4_jobs_writes_only_non_recipe_blocks_and_is_idempotent(tmp_path: Path) -> None:
    full_blocks = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "A beautiful gorgeous stunning book."},
        {"index": 2, "text": "Toast"},
        {"index": 3, "text": "1 slice bread"},
        {"index": 4, "text": "Technique: To prevent curdling, whisk constantly."},
        {"index": 5, "text": "Use low heat and add acid slowly."},
        {"index": 6, "text": "More notes."},
        {"index": 7, "text": "End."},
    ]
    # Recipe span is [2,4): indices 2 and 3 are recipe blocks.
    non_recipe_blocks = [
        {"index": 0, "text": "Preface", "features": {"is_header_likely": True}},
        {"index": 1, "text": "A beautiful gorgeous stunning book."},
        {"index": 4, "text": "Technique: To prevent curdling, whisk constantly."},
        {"index": 5, "text": "Use low heat and add acid slowly."},
        {"index": 6, "text": "More notes."},
        {"index": 7, "text": "End."},
    ]
    in_dir = tmp_path / "in"

    build_pass4_knowledge_jobs(
        full_blocks=full_blocks,
        non_recipe_blocks=non_recipe_blocks,
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=2,
    )

    job_paths = sorted(in_dir.glob("*.json"))
    assert job_paths, "Expected pass4 knowledge job bundles to be written."

    first_bytes = {path.name: path.read_bytes() for path in job_paths}
    payloads = _load_all_jobs(in_dir)

    assert {span["start"] for span in payloads[0]["guardrails"]["recipe_spans"]} == {2}
    assert {span["end"] for span in payloads[0]["guardrails"]["recipe_spans"]} == {4}

    for payload in payloads:
        chunk_blocks = payload["chunk"]["blocks"]
        chunk_indices = {block["block_index"] for block in chunk_blocks}
        assert 2 not in chunk_indices
        assert 3 not in chunk_indices

        assert "heuristics" in payload
        assert "suggested_lane" in payload["heuristics"]
        assert "suggested_highlights" in payload["heuristics"]
        assert "suggested_skip_reason" in payload["heuristics"]

    # Context may include recipe blocks; ensure we captured at least one.
    context_indices = {
        block["block_index"]
        for payload in payloads
        for block in payload["context"]["blocks_before"]
    }
    assert 2 in context_indices or 3 in context_indices

    # Idempotence: rerun yields identical JSON bytes.
    build_pass4_knowledge_jobs(
        full_blocks=full_blocks,
        non_recipe_blocks=non_recipe_blocks,
        workbook_slug="book",
        source_hash="hash123",
        out_dir=in_dir,
        context_blocks=2,
    )
    second_bytes = {path.name: path.read_bytes() for path in sorted(in_dir.glob("*.json"))}
    assert first_bytes == second_bytes
