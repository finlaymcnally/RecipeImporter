from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_models import KnowledgeChunkResultV2
from cookimport.llm.codex_farm_knowledge_writer import write_knowledge_artifacts


def test_write_knowledge_artifacts_writes_jsonl_and_md(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "book.c0000.nr": KnowledgeChunkResultV2.model_validate(
            {
                "chunk_id": "book.c0000.nr",
                "is_useful": True,
                "block_decisions": [
                    {"block_index": 4, "category": "knowledge"},
                ],
                "snippets": [
                    {
                        "body": "Whisk constantly and use low heat.",
                        "evidence": [{"block_index": 4, "quote": "whisk constantly"}],
                    }
                ],
            }
        )
    }
    blocks = {
        4: {"index": 4, "text": "Technique: To prevent curdling, whisk constantly."},
    }

    report = write_knowledge_artifacts(
        run_root=run_root,
        workbook_slug="book",
        outputs=outputs,
        full_blocks_by_index=blocks,
        chunk_lane_by_id={"book.c0000.nr": "knowledge"},
    )

    assert report.snippets_written == 1
    assert report.snippets_path.exists()
    assert report.preview_path.exists()
    assert report.snippet_records[0]["snippet_id"] == "book.c0000.nr.s00"

    jsonl = report.snippets_path.read_text(encoding="utf-8")
    assert "book.c0000.nr.s00" in jsonl
    md = report.preview_path.read_text(encoding="utf-8")
    assert "Snippet 1" in md
    assert "block 4" in md


def test_write_knowledge_artifacts_fails_on_missing_block_index(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "book.c0000.nr": KnowledgeChunkResultV2.model_validate(
            {
                "chunk_id": "book.c0000.nr",
                "is_useful": True,
                "block_decisions": [
                    {"block_index": 999, "category": "knowledge"},
                ],
                "snippets": [
                    {
                        "body": "Whisk constantly.",
                        "evidence": [{"block_index": 999, "quote": "whisk"}],
                    }
                ],
            }
        )
    }

    with pytest.raises(ValueError, match="missing block index"):
        write_knowledge_artifacts(
            run_root=run_root,
            workbook_slug="book",
            outputs=outputs,
            full_blocks_by_index={},
        )
