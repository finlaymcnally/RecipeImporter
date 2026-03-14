from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_jobs import (
    COMPACT_PASS4_JOB_FORMAT,
    LEGACY_PASS4_JOB_FORMAT,
    build_pass4_knowledge_jobs,
)


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


def test_build_pass4_jobs_compact_format_reduces_bundle_size(tmp_path: Path) -> None:
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
    non_recipe_blocks = [
        full_blocks[0],
        full_blocks[1],
        full_blocks[4],
        full_blocks[5],
        full_blocks[6],
        full_blocks[7],
    ]
    legacy_dir = tmp_path / "legacy"
    compact_dir = tmp_path / "compact"

    build_pass4_knowledge_jobs(
        full_blocks=full_blocks,
        non_recipe_blocks=non_recipe_blocks,
        workbook_slug="book",
        source_hash="hash123",
        out_dir=legacy_dir,
        context_blocks=2,
        job_format=LEGACY_PASS4_JOB_FORMAT,
    )
    build_pass4_knowledge_jobs(
        full_blocks=full_blocks,
        non_recipe_blocks=non_recipe_blocks,
        workbook_slug="book",
        source_hash="hash123",
        out_dir=compact_dir,
        context_blocks=2,
        job_format=COMPACT_PASS4_JOB_FORMAT,
    )

    legacy_payloads = _load_all_jobs(legacy_dir)
    compact_payloads = _load_all_jobs(compact_dir)
    legacy_payload = next(
        payload
        for payload in legacy_payloads
        if payload["chunk"]["block_start_index"] == 4
    )
    compact_payload = next(
        payload
        for payload in compact_payloads
        if payload["chunk"]["block_start_index"] == 4
    )

    legacy_bytes = len(json.dumps(legacy_payload, sort_keys=True).encode("utf-8"))
    compact_bytes = len(json.dumps(compact_payload, sort_keys=True).encode("utf-8"))

    assert compact_bytes < legacy_bytes * 0.75
    assert "recipe_spans" in legacy_payload["guardrails"]
    assert "context_recipe_block_indices" in compact_payload["guardrails"]
    assert compact_payload["guardrails"]["context_recipe_block_indices"] == [2, 3]
    assert "block_id" not in compact_payload["chunk"]["blocks"][0]
    assert "features_subset" not in compact_payload["context"]["blocks_before"][0]
    table_hint = compact_payload["chunk"]["blocks"][0]["table_hint"]
    assert "markdown" not in table_hint
