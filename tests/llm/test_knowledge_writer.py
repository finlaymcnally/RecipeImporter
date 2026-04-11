from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_models import KnowledgeBundleOutputV2
from cookimport.llm.codex_farm_knowledge_writer import write_knowledge_artifacts


def test_write_knowledge_artifacts_writes_shared_group_grounding_and_preview(
    tmp_path: Path,
) -> None:
    outputs = {
        "book.ks0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.ks0000.nr",
                "d": [
                    {
                        "i": 4,
                        "c": "knowledge",
                        "gr": {"tk": ["emulsify"], "ck": ["techniques"]},
                    }
                ],
                "g": [
                    {
                        "gid": "g01",
                        "l": "Heat control",
                        "bi": [4],
                        "gr": {"tk": ["emulsify"], "ck": ["techniques"]},
                    }
                ],
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
    assert report.group_records[0]["knowledge_group_id"] == "book.ks0000.nr.g01"
    assert report.group_records[0]["shared_grounding"] == {
        "tag_keys": ["emulsify"],
        "category_keys": ["techniques"],
        "proposed_tags": [],
    }
    assert "shared_tag_keys: emulsify" in report.preview_path.read_text(encoding="utf-8")


def test_write_knowledge_artifacts_fails_on_missing_block_index(tmp_path: Path) -> None:
    outputs = {
        "book.ks0000.nr": KnowledgeBundleOutputV2.model_validate(
            {
                "bid": "book.ks0000.nr",
                "d": [
                    {
                        "i": 4,
                        "c": "knowledge",
                        "gr": {"tk": ["emulsify"], "ck": ["techniques"]},
                    }
                ],
                "g": [
                    {
                        "gid": "g01",
                        "l": "Heat control",
                        "bi": [4],
                        "gr": {"tk": ["emulsify"], "ck": ["techniques"]},
                    }
                ],
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
