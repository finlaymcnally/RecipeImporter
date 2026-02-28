from pathlib import Path
import json
import shutil
from typer.testing import CliRunner
from cookimport.cli import app
import pytest
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR

runner = CliRunner()

def test_stage_output_structure(tmp_path):
    # Setup
    fixtures_dir = TESTS_FIXTURES_DIR
    source_file = fixtures_dir / "simple_text.txt"
    output_dir = tmp_path / "output"
    
    # Execute
    result = runner.invoke(app, ["stage", str(source_file), "--out", str(output_dir)])
    
    # Verify
    assert result.exit_code == 0
    
    # Find the timestamped directory
    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    processing_timeseries = timestamp_dir / "processing_timeseries.jsonl"
    assert processing_timeseries.exists()
    timeseries_rows = [
        json.loads(line)
        for line in processing_timeseries.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert timeseries_rows
    assert timeseries_rows[-1]["event"] == "finished"
    assert any("cpu_utilization_pct" in row for row in timeseries_rows)
    
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
    assert report["runConfig"]["epub_unstructured_html_parser_version"] == "v1"
    assert report["runConfig"]["epub_unstructured_skip_headers_footers"] is False
    assert report["runConfig"]["epub_unstructured_preprocess_mode"] == "br_split_v1"
    assert report["runConfig"]["section_detector_backend"] == "legacy"
    assert report["runConfig"]["multi_recipe_splitter"] == "legacy"
    assert report["runConfig"]["multi_recipe_trace"] is False
    assert report["runConfig"]["multi_recipe_min_ingredient_lines"] == 1
    assert report["runConfig"]["multi_recipe_min_instruction_lines"] == 1
    assert report["runConfig"]["multi_recipe_for_the_guardrail"] is True
    assert isinstance(report.get("runConfigHash"), str)
    assert len(report["runConfigHash"]) == 64
    assert "workers=" in str(report.get("runConfigSummary", ""))
    run_manifest_path = timestamp_dir / "run_manifest.json"
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest["run_kind"] == "stage"
    assert run_manifest["run_id"] == timestamp_dir.name
    assert run_manifest["artifacts"]["reports"] == [f"{file_slug}.excel_import_report.json"]

    # Expected: output/timestamp/tips/simple_text/
    tips_dir = timestamp_dir / "tips" / file_slug
    assert tips_dir.exists()
    list(tips_dir.rglob("t*.json"))

    # Expected: output/timestamp/sections/simple_text/
    sections_dir = timestamp_dir / "sections" / file_slug
    assert sections_dir.exists()
    assert (sections_dir / "r0.sections.json").exists()
    assert (sections_dir / "sections.md").exists()

    # Expected: output/timestamp/raw/text/<hash>/
    raw_dir = timestamp_dir / "raw" / "text"
    assert raw_dir.exists()
    assert list(raw_dir.rglob("*.json"))

    history_csv = output_dir.parent / ".history" / "performance_history.csv"
    assert history_csv.exists()


def test_stage_no_write_markdown_skips_markdown_sidecars(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "simple_text.txt"
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
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
            "--no-write-markdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    file_slug = "simple_text"

    assert (timestamp_dir / "sections" / file_slug / "r0.sections.json").exists()
    assert not (timestamp_dir / "sections" / file_slug / "sections.md").exists()
    assert not (timestamp_dir / "tips" / file_slug / "tips.md").exists()
    assert not (timestamp_dir / "tips" / file_slug / "topic_candidates.md").exists()
    assert not list(timestamp_dir.rglob("*.md"))


def test_epub_report_includes_extractor_setting(tmp_path):
    fixtures_dir = TESTS_FIXTURES_DIR
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
            "beautifulsoup",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["importerName"] == "epub"
    assert report["runConfig"]["epub_extractor"] == "beautifulsoup"
    assert isinstance(report.get("runConfigHash"), str)
    assert len(report["runConfigHash"]) == 64
    assert "epub_extractor=beautifulsoup" in str(report.get("runConfigSummary", ""))


def test_stage_report_includes_section_detector_backend_setting(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "simple_text.txt"
    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_dir),
            "--section-detector-backend",
            "shared_v1",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    report_path = timestamp_dir / "simple_text.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["section_detector_backend"] == "shared_v1"


def test_stage_report_includes_multi_recipe_splitter_settings(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "simple_text.txt"
    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_dir),
            "--multi-recipe-splitter",
            "rules_v1",
            "--multi-recipe-trace",
            "--multi-recipe-min-ingredient-lines",
            "2",
            "--multi-recipe-min-instruction-lines",
            "3",
            "--no-multi-recipe-for-the-guardrail",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    report_path = timestamp_dir / "simple_text.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["multi_recipe_splitter"] == "rules_v1"
    assert report["runConfig"]["multi_recipe_trace"] is True
    assert report["runConfig"]["multi_recipe_min_ingredient_lines"] == 2
    assert report["runConfig"]["multi_recipe_min_instruction_lines"] == 3
    assert report["runConfig"]["multi_recipe_for_the_guardrail"] is False


def test_epub_report_tracks_unstructured_option_flags(tmp_path):
    fixtures_dir = TESTS_FIXTURES_DIR
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
            "unstructured",
            "--epub-unstructured-html-parser-version",
            "v2",
            "--epub-unstructured-skip-headers-footers",
            "--epub-unstructured-preprocess-mode",
            "br_split_v1",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["epub_extractor"] == "unstructured"
    assert report["runConfig"]["epub_unstructured_html_parser_version"] == "v2"
    assert report["runConfig"]["epub_unstructured_skip_headers_footers"] is True
    assert report["runConfig"]["epub_unstructured_preprocess_mode"] == "br_split_v1"

    raw_epub_dir = timestamp_dir / "raw" / "epub"
    assert list(raw_epub_dir.glob("**/unstructured_elements.jsonl"))
    assert list(raw_epub_dir.glob("**/raw_spine_xhtml_*.xhtml"))
    assert list(raw_epub_dir.glob("**/norm_spine_xhtml_*.xhtml"))


def test_stage_markitdown_epub_writes_backend_and_markdown_artifact(tmp_path, monkeypatch):
    fixtures_dir = TESTS_FIXTURES_DIR
    source_file = fixtures_dir / "sample.epub"
    if not source_file.exists():
        pytest.skip("sample.epub not found")
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")

    monkeypatch.setattr(
        "cookimport.plugins.epub.convert_path_to_markdown",
        lambda _path: (
            "# MarkItDown Recipe\n\n"
            "## Ingredients\n"
            "- 1 cup flour\n"
            "- 1 cup milk\n"
        ),
    )

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
            "4",
            "--epub-extractor",
            "markitdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]

    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["epub_extractor"] == "markitdown"
    assert report["runConfig"]["effective_workers"] == 1
    assert report["epubBackend"] == "markitdown"

    markdown_artifacts = list(
        (timestamp_dir / "raw" / "epub").glob("**/markitdown_markdown.md")
    )
    assert markdown_artifacts


def test_stage_markdown_epub_writes_backend_and_diagnostics(tmp_path, monkeypatch):
    fixtures_dir = TESTS_FIXTURES_DIR
    source_file = fixtures_dir / "sample.epub"
    if not source_file.exists():
        pytest.skip("sample.epub not found")
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")

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
            "markdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]

    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["epub_extractor"] == "markdown"
    assert report["runConfig"]["epub_extractor_requested"] == "markdown"
    assert report["runConfig"]["epub_extractor_effective"] == "markdown"
    assert report["epubBackend"] == "markdown"
    assert "epubAutoSelection" not in report
    assert "epubAutoSelectedScore" not in report

    markdown_diag = list((timestamp_dir / "raw" / "epub").glob("**/markdown_blocks.jsonl"))
    assert markdown_diag


def test_stage_rejects_policy_locked_markdown_extractor(tmp_path, monkeypatch):
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    source_file = TESTS_FIXTURES_DIR / "simple_text.txt"
    output_dir = tmp_path / "output"

    result = runner.invoke(
        app,
        [
            "stage",
            str(source_file),
            "--out",
            str(output_dir),
            "--epub-extractor",
            "markdown",
        ],
    )
    assert result.exit_code != 0
    assert "policy-locked off for now" in result.output


def test_stage_rejects_auto_epub_extractor(tmp_path):
    fixtures_dir = TESTS_FIXTURES_DIR
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
            "2",
            "--epub-extractor",
            "auto",
        ],
    )
    assert result.exit_code != 0
    assert not any(path.is_dir() and not path.name.startswith(".") for path in output_dir.glob("*"))
