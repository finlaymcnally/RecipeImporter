from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import ConversionReport, ConversionResult, TipCandidate, TipTags
from cookimport.staging.writer import write_tip_outputs


def test_write_tip_outputs(tmp_path: Path):
    tip = TipCandidate(
        text="Use a hot skillet for best searing.",
        tags=TipTags(recipes=["steak"]),
        provenance={"sheet": "tips"},
    )
    result = ConversionResult(
        recipes=[],
        tips=[tip],
        report=ConversionReport(),
        workbook="tips",
        workbookPath=str(tmp_path / "tips.txt"),
    )

    out_dir = tmp_path / "tips"
    write_tip_outputs(result, out_dir)

    tip_file = out_dir / "t0.json"
    assert tip_file.exists()

    payload = json.loads(tip_file.read_text(encoding="utf-8"))
    assert payload["text"] == "Use a hot skillet for best searing."
    assert payload["tags"]["recipes"] == ["steak"]
    assert "id" in payload
