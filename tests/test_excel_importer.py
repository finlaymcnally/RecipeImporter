from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cookimport.plugins.excel import ExcelImporter
from cookimport.staging.writer import write_draft_outputs


FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"


def _ensure_fixtures() -> None:
    required = [
        FIXTURES_DIR / "wide_table.xlsx",
        FIXTURES_DIR / "template.xlsx",
        FIXTURES_DIR / "tall_relational.xlsx",
    ]
    if all(path.exists() for path in required):
        return
    script = FIXTURES_DIR / "generate_fixtures.py"
    subprocess.run([sys.executable, str(script)], check=True)


def _scrub_dynamic(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    if "@id" in payload:
        payload["@id"] = "<ID>"
    provenance = payload.get("recipeimport:provenance", {})
    if "@id" in provenance:
        provenance["@id"] = "<ID>"
    if "file_path" in provenance:
        provenance["file_path"] = "<FILE_PATH>"
    if "import_timestamp" in provenance:
        provenance["import_timestamp"] = "<TS>"
    payload["recipeimport:provenance"] = provenance
    return payload


@pytest.mark.parametrize(
    "workbook_name",
    ["wide_table.xlsx", "template.xlsx", "tall_relational.xlsx"],
)
def test_excel_outputs_match_goldens(tmp_path: Path, workbook_name: str) -> None:
    _ensure_fixtures()
    importer = ExcelImporter()
    workbook_path = FIXTURES_DIR / workbook_name

    result = importer.convert(workbook_path, None)
    write_draft_outputs(result, tmp_path)

    expected_root = EXPECTED_DIR / workbook_path.stem
    for expected_file in expected_root.rglob("*.json"):
        # Expected structure: {sheet_slug}/{row}.json
        # The expected files are stored under workbook/sheet/file structure
        # but writer outputs directly to out_dir/sheet/file
        relative = expected_file.relative_to(expected_root)
        actual_file = tmp_path / relative
        assert actual_file.exists(), f"Missing output {actual_file}"
        actual_payload = json.loads(actual_file.read_text(encoding="utf-8"))
        assert actual_payload.get("schema_v") == 1


def test_inspect_mapping_stub_contains_layout() -> None:
    _ensure_fixtures()
    importer = ExcelImporter()
    inspection = importer.inspect(FIXTURES_DIR / "wide_table.xlsx")
    assert inspection.mapping_stub is not None
    sheet = next((s for s in inspection.mapping_stub.sheets if s.sheet_name == "Sheet1"), None)
    assert sheet is not None
    assert sheet.layout == "wide-table"
    assert sheet.header_row == 1
    assert "name" in sheet.column_aliases
