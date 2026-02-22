from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_farm_knowledge_ingest import read_pass4_knowledge_outputs


def test_read_pass4_outputs_parses_known_good_fixture(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "job.json").write_text(
        json.dumps(
            {
                "bundle_version": "1",
                "chunk_id": "book.c0000.nr",
                "is_useful": True,
                "snippets": [
                    {
                        "title": "Prevent curdling",
                        "body": "Whisk constantly and use low heat.",
                        "tags": ["technique"],
                        "evidence": [{"block_index": 4, "quote": "whisk constantly"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    outputs = read_pass4_knowledge_outputs(out_dir)
    assert set(outputs) == {"book.c0000.nr"}
    assert outputs["book.c0000.nr"].snippets[0].evidence[0].block_index == 4


def test_read_pass4_outputs_rejects_missing_evidence_with_filename_context(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    bad_path = out_dir / "bad.json"
    bad_path.write_text(
        json.dumps(
            {
                "bundle_version": "1",
                "chunk_id": "book.c0001.nr",
                "is_useful": True,
                "snippets": [
                    {
                        "title": None,
                        "body": "Whisk constantly.",
                        "tags": [],
                        "evidence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        read_pass4_knowledge_outputs(out_dir)
    assert "bad.json" in str(excinfo.value)
