from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cookimport.cli import app


runner = CliRunner()


def test_debug_epub_extract_variants_writes_expected_artifacts(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "sample.epub"
    if not source.exists():
        pytest.skip("sample.epub not found")

    out_dir = tmp_path / "epub-debug"
    result = runner.invoke(
        app,
        [
            "debug-epub-extract",
            str(source),
            "--out",
            str(out_dir),
            "--spine",
            "0",
            "--variants",
        ],
    )
    assert result.exit_code == 0

    run_dirs = [
        path
        for path in out_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["spine_index"] == 0
    variants = summary["variants"]
    assert len(variants) == 4

    for variant in variants:
        variant_dir = run_dir / variant["variant"]
        assert (variant_dir / "normalized_spine.xhtml").exists()
        if variant.get("error"):
            assert (variant_dir / "error.txt").exists()
            continue
        assert (variant_dir / "blocks.jsonl").exists()
        assert (variant_dir / "unstructured_elements.jsonl").exists()
