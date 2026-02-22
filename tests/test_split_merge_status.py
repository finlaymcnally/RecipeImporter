from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from cookimport.cli import _merge_split_jobs
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate, TopicCandidate


def test_merge_split_jobs_reports_main_process_phases(tmp_path: Path) -> None:
    source_path = tmp_path / "source.epub"
    source_path.write_text("fake epub payload", encoding="utf-8")
    out_dir = tmp_path / "out"
    run_dt = dt.datetime(2026, 2, 15, 23, 0, 0)

    def make_job(job_index: int, start_spine: int) -> dict[str, object]:
        result = ConversionResult(
            recipes=[
                RecipeCandidate(
                    name=f"Recipe {job_index}",
                    provenance={"location": {"start_spine": start_spine, "start_block": 0}},
                )
            ],
            tips=[],
            tipCandidates=[],
            topicCandidates=[
                TopicCandidate(
                    text=f"Topic {job_index}",
                    provenance={"location": {"start_spine": start_spine}},
                )
            ],
            report=ConversionReport(
                totalStandaloneBlocks=1,
                totalStandaloneTopicBlocks=1,
            ),
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
    merged = _merge_split_jobs(
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
        assert match is not None
        parsed.append((int(match.group(1)), int(match.group(2)), message))

    assert parsed[0][0] == 1
    assert parsed[-1][2].endswith(": Merge done")
    assert parsed[-1][0] == len(parsed)
    assert all(total == parsed[0][1] for _, total, _ in parsed)
    assert any(message.endswith(": Writing topic candidates...") for _, _, message in parsed)
    assert any(message.endswith(": Writing report...") for _, _, message in parsed)
    assert any(message.endswith(": Merging raw artifacts...") for _, _, message in parsed)
