from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner
import pytest

from cookimport import cli
from cookimport.cli import app
from cookimport.core.executor_fallback import ProcessThreadExecutorResolution
from tests.fast_stage_pipeline import install_fake_source_job_stage
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


@pytest.fixture(autouse=True)
def _use_fake_epub_stage_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_source_job_stage(
        monkeypatch,
        importer_name="epub",
        emit_epub_backend_artifacts=True,
    )
    monkeypatch.setattr(
        "cookimport.cli_commands.stage.resolve_process_thread_executor",
        lambda **_kwargs: ProcessThreadExecutorResolution(
            backend="serial",
            executor=None,
            messages=(),
        ),
    )


def _timestamp_dir(output_dir: Path) -> Path:
    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    return timestamp_dirs[0]


def test_epub_report_includes_extractor_setting(tmp_path: Path) -> None:
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


def test_stage_markitdown_epub_writes_backend_and_markdown_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = TESTS_FIXTURES_DIR / "sample.epub"
    if not source_file.exists():
        pytest.skip("sample.epub not found")
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    monkeypatch.setattr(
        "cookimport.plugins.epub.convert_path_to_markdown",
        lambda _path: "# recipe\n",
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
    assert list((timestamp_dir / "raw" / "epub").glob("**/markitdown_markdown.md"))


def test_stage_markdown_epub_writes_backend_and_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert list((timestamp_dir / "raw" / "epub").glob("**/markdown_blocks.jsonl"))
