from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_models import KnowledgeBundleOutputV2
from cookimport.llm.codex_farm_knowledge_writer import write_knowledge_artifacts


def test_write_knowledge_artifacts_writes_jsonl_and_md(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "book.kp0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.kp0000.nr",
                "d": [
                    {"i": 4, "c": "knowledge"},
                ],
                "g": [
                    {
                        "gid": "idea-1",
                        "l": "Whisk gently over low heat",
                        "bi": [4],
                        "s": [
                            {
                                "b": "Whisk constantly and use low heat.",
                                "e": [{"i": 4, "q": "whisk constantly"}],
                            }
                        ],
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
    )

    assert report.snippets_written == 1
    assert report.snippets_path.exists()
    assert report.preview_path.exists()
    assert report.snippet_records[0]["snippet_id"] == "book.kp0000.nr.idea-1.s00"

    jsonl = report.snippets_path.read_text(encoding="utf-8")
    assert "book.kp0000.nr.idea-1.s00" in jsonl
    md = report.preview_path.read_text(encoding="utf-8")
    assert "Whisk gently over low heat" in md
    assert "block 4" in md


def test_write_knowledge_artifacts_fails_on_missing_block_index(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "book.kp0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.kp0000.nr",
                "d": [
                    {"i": 999, "c": "knowledge"},
                ],
                "g": [
                    {
                        "gid": "idea-1",
                        "l": "Whisk constantly",
                        "bi": [999],
                        "s": [
                            {
                                "b": "Whisk constantly.",
                                "e": [{"i": 999, "q": "whisk"}],
                            }
                        ],
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
