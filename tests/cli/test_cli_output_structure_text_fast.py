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

_BASE_FAST_STAGE_ARGS = [
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
def _use_fake_stage_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_source_job_stage(monkeypatch, importer_name="text")
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


def test_stage_output_structure(tmp_path):
    source_file = TESTS_FIXTURES_DIR / "simple_text.txt"
    output_dir = tmp_path / "output"

    result = runner.invoke(
        app,
        ["stage", str(source_file), "--out", str(output_dir), *_BASE_FAST_STAGE_ARGS],
    )

    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)
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

    final_drafts = timestamp_dir / "final drafts"
    assert final_drafts.exists()
    assert final_drafts.is_dir()

    file_slug = "simple_text"
    final_draft_slug = final_drafts / file_slug
    assert final_draft_slug.exists()
    assert final_draft_slug.is_dir()

    json_files = list(final_draft_slug.rglob("*.json"))
    assert len(json_files) > 0

    intermediate_drafts = timestamp_dir / "intermediate drafts"
    assert intermediate_drafts.exists()

    intermediate_draft_slug = intermediate_drafts / file_slug
    assert intermediate_draft_slug.exists()
    assert intermediate_draft_slug.is_dir()

    jsonld_files = list(intermediate_draft_slug.rglob("*.jsonld"))
    assert len(jsonld_files) > 0

    reports_dir = timestamp_dir / "reports"
    assert not reports_dir.exists()
    report_path = timestamp_dir / f"{file_slug}.excel_import_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["importerName"] == "text"
    assert report["runConfig"]["workers"] >= 1
    assert "bucket1_fixed_behavior_version" in report["runConfig"]
    assert report["runConfig"]["epub_extractor"] == "unstructured"
    assert report["runConfig"]["epub_unstructured_html_parser_version"] == "v1"
    assert report["runConfig"]["epub_unstructured_skip_headers_footers"] is True
    assert report["runConfig"]["epub_unstructured_preprocess_mode"] == "br_split_v1"
    assert "section_detector_backend" not in report["runConfig"]
    assert report["runConfig"]["multi_recipe_splitter"] == "rules_v1"
    assert "multi_recipe_trace" not in report["runConfig"]
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

    assert not (timestamp_dir / "tips").exists()

    sections_dir = timestamp_dir / "sections" / file_slug
    assert sections_dir.exists()
    assert (sections_dir / "r0.sections.json").exists()
    assert (sections_dir / "sections.md").exists()

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
            *_BASE_FAST_STAGE_ARGS,
            "--no-write-markdown",
        ],
    )
    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)
    file_slug = "simple_text"

    assert (timestamp_dir / "sections" / file_slug / "r0.sections.json").exists()
    assert not (timestamp_dir / "sections" / file_slug / "sections.md").exists()
    assert not (timestamp_dir / "tips").exists()
    assert not list(timestamp_dir.rglob("*.md"))


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
            *_BASE_FAST_STAGE_ARGS,
            "--section-detector-backend",
            "shared_v1",
        ],
    )
    assert result.exit_code == 0

    timestamp_dir = _timestamp_dir(output_dir)
    report_path = timestamp_dir / "simple_text.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "section_detector_backend" not in report["runConfig"]
    assert "bucket1_fixed_behavior_version" in report["runConfig"]


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
            *_BASE_FAST_STAGE_ARGS,
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

    timestamp_dir = _timestamp_dir(output_dir)
    report_path = timestamp_dir / "simple_text.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runConfig"]["multi_recipe_splitter"] == "rules_v1"
    assert "multi_recipe_trace" not in report["runConfig"]
    assert report["runConfig"]["multi_recipe_min_ingredient_lines"] == 2
    assert report["runConfig"]["multi_recipe_min_instruction_lines"] == 3
    assert report["runConfig"]["multi_recipe_for_the_guardrail"] is False


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
            *_BASE_FAST_STAGE_ARGS,
            "--epub-extractor",
            "markdown",
        ],
    )
    assert result.exit_code != 0
    assert "policy-locked off for now" in result.output
