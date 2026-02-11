from __future__ import annotations

from pathlib import Path

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.labelstudio.ingest import (
    _merge_parallel_results,
    _plan_parallel_convert_jobs,
)


def test_plan_parallel_convert_jobs_pdf_splits(monkeypatch) -> None:
    path = Path("sample.pdf")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_pdf_page_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=4,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
    )

    assert len(jobs) == 3
    assert jobs[0]["start_page"] == 0
    assert jobs[1]["start_page"] == 40
    assert jobs[2]["start_page"] == 80
    assert jobs[0]["start_spine"] is None


def test_merge_parallel_results_combines_and_reorders(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_text("source", encoding="utf-8")

    job_a = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Later",
                identifier="old-later",
                provenance={"location": {"start_page": 9, "start_block": 20}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-a",
                location_id="loc-a",
                extension="json",
                content={"x": 1},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    job_b = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Earlier",
                identifier="old-earlier",
                provenance={"location": {"start_page": 1, "start_block": 1}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-b",
                location_id="loc-b",
                extension="json",
                content={"x": 2},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    merged = _merge_parallel_results(
        source,
        "pdf",
        [
            {"job_index": 1, "start_page": 8, "result": job_a},
            {"job_index": 0, "start_page": 0, "result": job_b},
        ],
    )

    assert len(merged.recipes) == 2
    assert merged.recipes[0].name == "Earlier"
    assert merged.recipes[1].name == "Later"
    assert merged.recipes[0].identifier != "old-earlier"
    assert merged.recipes[1].identifier != "old-later"
    assert len(merged.raw_artifacts) == 2
