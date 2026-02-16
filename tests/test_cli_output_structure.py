from pathlib import Path
import json
import shutil
from typer.testing import CliRunner
from cookimport.cli import app
import pytest

runner = CliRunner()

def test_stage_output_structure(tmp_path):
    # Setup
    fixtures_dir = Path(__file__).parent / "fixtures"
    source_file = fixtures_dir / "simple_text.txt"
    output_dir = tmp_path / "output"
    
    # Execute
    result = runner.invoke(app, ["stage", str(source_file), "--out", str(output_dir)])
    
    # Verify
    assert result.exit_code == 0
    
    # Find the timestamped directory
    timestamp_dirs = list(output_dir.glob("*"))
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    
    # Check for new structure
    # Expected: output/timestamp/final drafts/simple_text/
    final_drafts = timestamp_dir / "final drafts"
    assert final_drafts.exists()
    assert final_drafts.is_dir()
    
    file_slug = "simple_text"
    final_draft_slug = final_drafts / file_slug
    assert final_draft_slug.exists()
    assert final_draft_slug.is_dir()
    
    # Check for content in final drafts
    json_files = list(final_draft_slug.rglob("*.json"))
    assert len(json_files) > 0
    
    # Expected: output/timestamp/intermediate drafts/simple_text/
    intermediate_drafts = timestamp_dir / "intermediate drafts"
    assert intermediate_drafts.exists()
    
    intermediate_draft_slug = intermediate_drafts / file_slug
    assert intermediate_draft_slug.exists()
    assert intermediate_draft_slug.is_dir()
    
    # Check for content in intermediate drafts
    jsonld_files = list(intermediate_draft_slug.rglob("*.jsonld"))
    assert len(jsonld_files) > 0

    # Expected: output/timestamp/{file_slug}.excel_import_report.json (Report in root)
    reports_dir = timestamp_dir / "reports"
    assert not reports_dir.exists()
    report_path = timestamp_dir / f"{file_slug}.excel_import_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["importerName"] == "text"
    assert report["runConfig"]["workers"] >= 1
    assert report["runConfig"]["epub_extractor"] == "unstructured"

    # Expected: output/timestamp/tips/simple_text/
    tips_dir = timestamp_dir / "tips" / file_slug
    assert tips_dir.exists()
    list(tips_dir.rglob("t*.json"))

    # Expected: output/timestamp/raw/text/<hash>/
    raw_dir = timestamp_dir / "raw" / "text"
    assert raw_dir.exists()
    assert list(raw_dir.rglob("*.json"))


def test_epub_report_includes_extractor_setting(tmp_path):
    fixtures_dir = Path(__file__).parent / "fixtures"
    source_file = fixtures_dir / "sample.epub"
    if not source_file.exists():
        pytest.skip("sample.epub not found")

    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_dir),
            "--workers",
            "1",
            "--epub-split-workers",
            "1",
            "--epub-extractor",
            "legacy",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = list(output_dir.glob("*"))
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["importerName"] == "epub"
    assert report["runConfig"]["epub_extractor"] == "legacy"
