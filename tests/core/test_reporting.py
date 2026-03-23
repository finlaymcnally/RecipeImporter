from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.core.reporting import (
    build_authoritative_stage_report,
    finalize_report_totals,
)


def _simple_result() -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
    )


def test_build_authoritative_stage_report_strips_legacy_totals() -> None:
    base_report = ConversionReport(
        total_recipes=9,
        total_standalone_blocks=5,
        warnings=["keep me"],
        errors=["still here"],
        epub_backend="unstructured",
        recipe_likeness={"counts": {"accept": 9}},
    )

    report = build_authoritative_stage_report(base_report)

    assert report.total_recipes == 0
    assert report.total_standalone_blocks == 0
    assert report.warnings == ["keep me"]
    assert report.errors == ["still here"]
    assert report.epub_backend == "unstructured"
    assert report.recipe_likeness == {"counts": {"accept": 9}}


def test_finalize_report_totals_writes_mismatch_only_for_prepopulated_counts(
    tmp_path: Path,
) -> None:
    diagnostics_path = tmp_path / "report_totals_mismatch.json"
    result = _simple_result()

    implicit_report = ConversionReport()
    diagnostics = finalize_report_totals(
        implicit_report,
        result,
        diagnostics_path=diagnostics_path,
    )
    assert diagnostics is None
    assert not diagnostics_path.exists()
    assert implicit_report.total_recipes == 1

    prepopulated_report = ConversionReport(total_recipes=9)
    diagnostics = finalize_report_totals(
        prepopulated_report,
        result,
        diagnostics_path=diagnostics_path,
    )
    assert diagnostics is not None
    assert diagnostics_path.exists()
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "report_totals_mismatch.v1"
    assert payload["prepopulated"] is True
    assert payload["before"]["totalRecipes"] == 9
    assert payload["expected"]["totalRecipes"] == 1
    assert "totalRecipes" in payload["mismatched_fields"]
