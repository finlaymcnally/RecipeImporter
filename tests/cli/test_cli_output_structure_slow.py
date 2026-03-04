import json

import pytest
from typer.testing import CliRunner

from cookimport.cli import app
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR

runner = CliRunner()

_BASE_STAGE_ARGS = [
    "--workers",
    "1",
    "--pdf-split-workers",
    "1",
    "--epub-split-workers",
    "1",
    "--llm-recipe-pipeline",
    "off",
]


def _timestamp_dir(output_dir):
    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    return timestamp_dirs[0]


def test_epub_report_includes_extractor_setting(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
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
            *_BASE_STAGE_ARGS,
            "--epub-extractor",
            "beautifulsoup",
        ],
    )
    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)
    report_path = timestamp_dir / "sample.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["importerName"] == "epub"
    assert report["runConfig"]["epub_extractor"] == "beautifulsoup"
    assert isinstance(report.get("runConfigHash"), str)
    assert len(report["runConfigHash"]) == 64
    assert "epub_extractor=beautifulsoup" in str(report.get("runConfigSummary", ""))


def test_epub_report_tracks_unstructured_option_flags(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
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
            *_BASE_STAGE_ARGS,
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

    timestamp_dir = _timestamp_dir(output_dir)
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
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
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
            *_BASE_STAGE_ARGS,
            "--epub-split-workers",
            "4",
            "--epub-extractor",
            "markitdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)

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
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
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
            *_BASE_STAGE_ARGS,
            "--epub-extractor",
            "markdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)

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


def test_stage_rejects_auto_epub_extractor(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
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
            *_BASE_STAGE_ARGS,
            "--epub-split-workers",
            "2",
            "--epub-extractor",
            "auto",
        ],
    )
    assert result.exit_code != 0
    assert not any(
        path.is_dir() and not path.name.startswith(".") for path in output_dir.glob("*")
    )
