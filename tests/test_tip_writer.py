from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    TipCandidate,
    TipTags,
    TopicCandidate,
)
from cookimport.staging.writer import write_tip_outputs, write_topic_candidate_outputs


def test_write_tip_outputs(tmp_path: Path):
    tip = TipCandidate(
        text="Use a hot skillet for best searing.",
        tags=TipTags(
            dishes=["steak"],
            meats=["beef"],
            techniques=["rest"],
            cookingMethods=["sear"],
            tools=["skillet"],
        ),
        source_recipe_title="Perfect Steak",
        provenance={"sheet": "tips"},
    )
    result = ConversionResult(
        recipes=[],
        tips=[tip],
        topicCandidates=[
            TopicCandidate(text="Cast iron seasoning care matters."),
        ],
        report=ConversionReport(),
        workbook="tips",
        workbookPath=str(tmp_path / "tips.txt"),
    )

    out_dir = tmp_path / "tips"
    write_tip_outputs(result, out_dir)
    write_topic_candidate_outputs(result, out_dir)

    tip_file = out_dir / "t0.json"
    assert tip_file.exists()
    summary_file = out_dir / "tips.md"
    assert summary_file.exists()
    topic_json = out_dir / "topic_candidates.json"
    topic_md = out_dir / "topic_candidates.md"
    assert topic_json.exists()
    assert topic_md.exists()

    payload = json.loads(tip_file.read_text(encoding="utf-8"))
    assert payload["text"] == "Use a hot skillet for best searing."
    assert payload["tags"]["dishes"] == ["steak"]
    assert payload["sourceRecipeTitle"] == "Perfect Steak"
    assert "id" in payload
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "Use a hot skillet for best searing." in summary_text
    assert "t0" in summary_text
    assert "dish: steak" in summary_text
    assert "methods: sear" in summary_text
