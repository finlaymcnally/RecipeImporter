from pathlib import Path
import shutil
from typer.testing import CliRunner
from cookimport.cli import app

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

    # Expected: output/timestamp/reports/
    reports_dir = timestamp_dir / "reports"
    assert reports_dir.exists()
    assert (reports_dir / f"{file_slug}.excel_import_report.json").exists()

    # Expected: output/timestamp/tips/simple_text/
    tips_dir = timestamp_dir / "tips" / file_slug
    assert tips_dir.exists()
    tip_files = list(tips_dir.rglob("t*.json"))
    assert len(tip_files) > 0
