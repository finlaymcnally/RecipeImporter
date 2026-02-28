from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

from cookimport.plugins.excel import ExcelImporter, _extract_sections_from_blob
from cookimport.staging.writer import write_draft_outputs
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR


FIXTURES_DIR = TESTS_FIXTURES_DIR
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
    expected_files = sorted(expected_root.rglob("*.json"))
    actual_files = sorted(tmp_path.glob("*.json"))
    assert len(actual_files) == len(expected_files)
    for actual_file in actual_files:
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


def test_excel_importer_rejects_low_likeness_rows(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["Name", "Ingredients", "Instructions"])
    sheet.append(["Pan Toast", "2 slices bread\n1 tbsp butter", "Toast bread.\nServe."])
    sheet.append(["Editor Notes", "", ""])
    source = tmp_path / "mixed.xlsx"
    workbook.save(source)

    result = ExcelImporter().convert(source, None)

    assert len(result.recipes) == 1
    assert result.recipes[0].name == "Pan Toast"
    assert result.recipes[0].recipe_likeness is not None
    assert result.recipes[0].confidence == result.recipes[0].recipe_likeness.score
    assert result.non_recipe_blocks
    assert any(
        block.get("features", {}).get("source") == "rejected_recipe_candidate"
        for block in result.non_recipe_blocks
    )
    assert result.report.recipe_likeness is not None
    assert result.report.recipe_likeness["rejectedCandidateCount"] >= 1
    assert any(
        artifact.location_id == "recipe_scoring_debug"
        for artifact in result.raw_artifacts
    )


def test_excel_blob_section_extraction_keeps_for_component_headers() -> None:
    sections = _extract_sections_from_blob(
        "\n".join(
            [
                "Ingredients",
                "For the filling:",
                "2 apples",
                "Instructions",
                "For the filling:",
                "Cook apples until soft.",
            ]
        ),
        mapping=None,
    )
    assert sections["ingredients"] == ["For the filling", "2 apples"]
    assert sections["instructions"] == ["For the filling", "Cook apples until soft."]
