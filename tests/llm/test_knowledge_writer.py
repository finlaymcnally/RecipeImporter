from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_models import KnowledgeBundleOutputV2
from cookimport.llm.codex_farm_knowledge_writer import write_knowledge_artifacts


def test_write_knowledge_artifacts_writes_group_json_and_preview(tmp_path: Path) -> None:
    outputs = {
        "book.ks0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.ks0000.nr",
                "d": [{"i": 4, "c": "knowledge", "rc": "knowledge"}],
                "g": [{"gid": "g01", "l": "Heat control", "bi": [4]}],
            }
        )
    }

    report = write_knowledge_artifacts(
        run_root=tmp_path,
        workbook_slug="book",
        outputs=outputs,
        full_blocks_by_index={4: {"text": "Use low heat and whisk steadily."}},
    )

    assert report.groups_written == 1
    assert report.snippets_written == 0
    assert report.snippets_path is None
    assert report.snippet_records == []
    assert report.group_records[0]["knowledge_group_id"] == "book.ks0000.nr.g01"
    assert report.preview_path.exists()
    assert "Heat control" in report.preview_path.read_text(encoding="utf-8")


def test_write_knowledge_artifacts_fails_on_missing_block_index(tmp_path: Path) -> None:
    outputs = {
        "book.ks0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.ks0000.nr",
                "d": [{"i": 4, "c": "knowledge", "rc": "knowledge"}],
                "g": [{"gid": "g01", "l": "Heat control", "bi": [4]}],
            }
        )
    }

    with pytest.raises(ValueError, match="had no block indices|missing block index"):
        write_knowledge_artifacts(
            run_root=tmp_path,
            workbook_slug="book",
            outputs=outputs,
            full_blocks_by_index={},
        )
