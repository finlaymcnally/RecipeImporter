from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from cookimport.cli import _merge_source_jobs
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.core.models import ConversionReport, ConversionResult


def test_merge_source_jobs_reports_main_process_phases(tmp_path: Path) -> None:
    source_path = tmp_path / "source.epub"
    source_path.write_text("fake epub payload", encoding="utf-8")
    out_dir = tmp_path / "out"
    run_dt = dt.datetime(2026, 2, 15, 23, 0, 0)

    def make_job(job_index: int, start_spine: int) -> dict[str, object]:
        result = ConversionResult(
            recipes=[],
            sourceBlocks=[
                {
                    "blockId": "b0",
                    "orderIndex": 0,
                    "text": f"Recipe {job_index}",
                    "location": {"spine_index": start_spine},
                }
            ],
            report=ConversionReport(totalStandaloneBlocks=1),
            workbook=source_path.stem,
            workbookPath=str(source_path),
        )
        return {
            "file": source_path.name,
            "status": "success",
            "job_index": job_index,
            "job_count": 2,
            "start_spine": start_spine,
            "end_spine": start_spine + 1,
            "timing": {"parsing_seconds": 0.05},
            "result": result,
        }

    statuses: list[str] = []
    merged = _merge_source_jobs(
        source_path,
        [make_job(0, 0), make_job(1, 1)],
        out_dir,
        mapping_config=None,
        limit=None,
        run_dt=run_dt,
        importer_name="epub",
        status_callback=statuses.append,
    )

    assert merged["status"] == "success"
    assert statuses

    phase_pattern = re.compile(r"^merge phase (\d+)/(\d+): .+")
    parsed = []
    for message in statuses:
        match = phase_pattern.match(message)
        if match is None:
            continue
        parsed.append((int(match.group(1)), int(match.group(2)), message))

    assert parsed
    assert parsed[0][0] == 1
    assert parsed[-1][2].endswith(": Merge done")
    assert parsed[-1][0] == len(parsed)
    assert all(total == parsed[0][1] for _, total, _ in parsed)
    assert any(message.endswith(": Writing report...") for _, _, message in parsed)
    assert any(message.endswith(": Merging raw artifacts...") for _, _, message in parsed)
    assert any(
        message.endswith(": Building authoritative stage outputs...")
        for _, _, message in parsed
    )
    normalized_statuses = [
        str((payload or {}).get("message") or message).strip()
        for message in statuses
        for payload in [parse_stage_progress(message)]
    ]
    assert "Generating deterministic non-recipe chunks..." in normalized_statuses
    assert any(status.startswith("Writing outputs... task 0/") for status in normalized_statuses)


def _output_stats_category_for_path(relative_path: Path) -> str | None:
    if not relative_path.parts:
        return None
    if relative_path.name == "08_nonrecipe_row_route.json":
        return "nonRecipe"
    if relative_path.name == "08_nonrecipe_exclusions.jsonl":
        return "nonRecipe"
    if relative_path.name == "09_nonrecipe_row_authority.json":
        return "nonRecipe"
    if relative_path.name == "09_nonrecipe_knowledge_groups.json":
        return "knowledge"
    if relative_path.name == "09_nonrecipe_finalize_status.json":
        return "knowledge"
    top = relative_path.parts[0]
    if top == "intermediate drafts":
        return "intermediateDrafts"
    if top == "final drafts":
        return "finalDrafts"
    if top == "sections":
        return "sections"
    if top == "chunks":
        return "chunks"
    if top == "tables":
        return "tables"
    if top == "knowledge":
        return "knowledge"
    if top == "recipe_authority":
        return "recipeAuthority"
    if top == "raw":
        return "rawArtifacts"
    if top == ".bench":
        return "benchArtifacts"
    return None


def _scan_output_stats(run_root: Path) -> dict[str, dict[str, int]]:
    scanned: dict[str, dict[str, int]] = {}
    for path in run_root.rglob("*"):
        if not path.is_file():
            continue
        category = _output_stats_category_for_path(path.relative_to(run_root))
        if category is None:
            continue
        record = scanned.setdefault(category, {"count": 0, "bytes": 0})
        record["count"] += 1
        record["bytes"] += path.stat().st_size
    return scanned


def test_merge_source_jobs_output_stats_match_fresh_directory_walk(tmp_path: Path) -> None:
    source_path = tmp_path / "source.epub"
    source_path.write_text("fake epub payload", encoding="utf-8")
    out_dir = tmp_path / "out"
    run_dt = dt.datetime(2026, 2, 16, 9, 15, 0)

    def make_job(job_index: int, start_spine: int) -> dict[str, object]:
        result = ConversionResult(
            recipes=[],
            sourceBlocks=[
                {
                    "blockId": "b0",
                    "orderIndex": 0,
                    "text": f"Recipe {job_index}",
                    "location": {"spine_index": start_spine},
                }
            ],
            report=ConversionReport(totalStandaloneBlocks=1),
            workbook=source_path.stem,
            workbookPath=str(source_path),
        )
        return {
            "file": source_path.name,
            "status": "success",
            "job_index": job_index,
            "job_count": 2,
            "start_spine": start_spine,
            "end_spine": start_spine + 1,
            "timing": {"parsing_seconds": 0.05},
            "result": result,
        }

    workbook_slug = source_path.stem
    for job_index, block_text in enumerate(("job 0 block", "job 1 block")):
        job_raw_root = (
            out_dir
            / ".job_parts"
            / workbook_slug
            / f"job_{job_index}"
            / "raw"
            / "epub"
            / f"hash-{job_index}"
        )
        job_raw_root.mkdir(parents=True, exist_ok=True)
        (job_raw_root / "full_text.json").write_text(
            json.dumps(
                {
                    "blocks": [
                        {"index": 0, "text": block_text},
                    ]
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (job_raw_root / "artifact.txt").write_text(
            f"raw artifact from job {job_index}",
            encoding="utf-8",
        )

    merged = _merge_source_jobs(
        source_path,
        [make_job(0, 0), make_job(1, 1)],
        out_dir,
        mapping_config=None,
        limit=None,
        run_dt=run_dt,
        importer_name="epub",
    )

    assert merged["status"] == "success"
    report_path = out_dir / "source.excel_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["totalRecipes"] == 0
    output_stats = report.get("outputStats") or {}
    report_files = output_stats.get("files") or {}

    scanned_files = _scan_output_stats(out_dir)
    for category, expected in scanned_files.items():
        assert report_files[category]["count"] == expected["count"]
        assert report_files[category]["bytes"] == expected["bytes"]

    expected_total_count = sum(entry["count"] for entry in scanned_files.values())
    expected_total_bytes = sum(entry["bytes"] for entry in scanned_files.values())
    assert report_files["total"]["count"] == expected_total_count
    assert report_files["total"]["bytes"] == expected_total_bytes
    assert report_files["rawArtifacts"]["count"] >= 4


def test_merge_source_jobs_preserves_recipe_scoring_debug_artifacts(tmp_path: Path) -> None:
    source_path = tmp_path / "source.epub"
    source_path.write_text("fake epub payload", encoding="utf-8")
    out_dir = tmp_path / "out"
    run_dt = dt.datetime(2026, 2, 16, 11, 45, 0)

    def make_job(job_index: int, start_spine: int) -> dict[str, object]:
        result = ConversionResult(
            recipes=[],
            sourceBlocks=[
                {
                    "blockId": "b0",
                    "orderIndex": 0,
                    "text": f"Recipe {job_index}",
                    "location": {"spine_index": start_spine},
                }
            ],
            report=ConversionReport(),
            workbook=source_path.stem,
            workbookPath=str(source_path),
        )
        return {
            "file": source_path.name,
            "status": "success",
            "job_index": job_index,
            "job_count": 2,
            "start_spine": start_spine,
            "end_spine": start_spine + 1,
            "timing": {"parsing_seconds": 0.05},
            "result": result,
        }

    workbook_slug = source_path.stem
    for job_index in (0, 1):
        job_raw_root = (
            out_dir
            / ".job_parts"
            / workbook_slug
            / f"job_{job_index}"
            / "raw"
            / "epub"
            / "shared-hash"
        )
        job_raw_root.mkdir(parents=True, exist_ok=True)
        (job_raw_root / "recipe_scoring_debug.jsonl").write_text(
            json.dumps({"job": job_index}) + "\n",
            encoding="utf-8",
        )

    merged = _merge_source_jobs(
        source_path,
        [make_job(0, 0), make_job(1, 1)],
        out_dir,
        mapping_config=None,
        limit=None,
        run_dt=run_dt,
        importer_name="epub",
    )

    assert merged["status"] == "success"
    debug_files = sorted(
        (
            out_dir
            / "raw"
            / "epub"
            / "shared-hash"
        ).glob("*recipe_scoring_debug*.jsonl")
    )
    assert len(debug_files) == 2
    contents = [path.read_text(encoding="utf-8").strip() for path in debug_files]
    assert any('"job": 0' in content for content in contents)
    assert any('"job": 1' in content for content in contents)
