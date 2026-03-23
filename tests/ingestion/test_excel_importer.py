from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

from cookimport.plugins.excel import ExcelImporter, _extract_sections_from_blob
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR


FIXTURES_DIR = TESTS_FIXTURES_DIR


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


@pytest.mark.parametrize(
    "workbook_name",
    ["wide_table.xlsx", "template.xlsx", "tall_relational.xlsx"],
)
def test_excel_convert_builds_source_blocks_for_fixture_layouts(
    workbook_name: str,
) -> None:
    _ensure_fixtures()
    importer = ExcelImporter()
    workbook_path = FIXTURES_DIR / workbook_name

    result = importer.convert(workbook_path, None)
    artifact_ids = {artifact.location_id for artifact in result.raw_artifacts}

    assert result.recipes == []
    assert result.source_blocks
    assert len(result.source_support) == len(result.source_blocks)
    assert "full_rows" in artifact_ids
    assert result.report.total_recipes == 0


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


def test_excel_importer_keeps_all_rows_in_source_blocks(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["Name", "Ingredients", "Instructions"])
    sheet.append(["Pan Toast", "2 slices bread\n1 tbsp butter", "Toast bread.\nServe."])
    sheet.append(["Editor Notes", "", ""])
    source = tmp_path / "mixed.xlsx"
    workbook.save(source)

    result = ExcelImporter().convert(source, None)
    joined_text = "\n".join(block.text for block in result.source_blocks)

    assert result.recipes == []
    assert "Pan Toast" in joined_text
    assert "Editor Notes" in joined_text
    assert any(item.kind == "excel_row" for item in result.source_support)
    assert not any(
        artifact.location_id == "recipe_scoring_debug" for artifact in result.raw_artifacts
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
