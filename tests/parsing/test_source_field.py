from __future__ import annotations

import json
from pathlib import Path
from cookimport.core.models import ConversionResult, RecipeCandidate, ConversionReport
from cookimport.staging.writer import write_draft_outputs

def test_source_field_is_populated_in_draft(tmp_path):
    # Setup
    recipe = RecipeCandidate(
        name="Test Recipe",
        ingredients=["1 item"],
        instructions=["Step 1"],
        source=None  # Explicitly None
    )
    
    report = ConversionReport()
    result = ConversionResult(
        recipes=[recipe],
        report=report,
        workbook="test_book",
        workbookPath="/path/to/test_book.epub"
    )
    
    out_dir = tmp_path / "output"
    
    # Execute
    write_draft_outputs(result, out_dir)
    
    # Verify
    output_file = out_dir / "r0.json"
    assert output_file.exists()
    
    with open(output_file, "r") as f:
        data = json.load(f)
        
    assert data["source"] == "test_book.epub"

def test_source_field_prefers_existing_value(tmp_path):
    # Setup
    recipe = RecipeCandidate(
        name="Test Recipe",
        ingredients=["1 item"],
        instructions=["Step 1"],
        source="explicit_source.txt"
    )
    
    report = ConversionReport()
    result = ConversionResult(
        recipes=[recipe],
        report=report,
        workbook="test_book",
        workbookPath="/path/to/test_book.epub"
    )
    
    out_dir = tmp_path / "output"
    
    # Execute
    write_draft_outputs(result, out_dir)
    
    # Verify
    output_file = out_dir / "r0.json"
    with open(output_file, "r") as f:
        data = json.load(f)
        
    assert data["source"] == "explicit_source.txt"
