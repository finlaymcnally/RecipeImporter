from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport import cli
from cookimport import cli_worker


def install_fake_source_job_pipeline(
    monkeypatch: Any,
    *,
    importer_name: str = "text",
    emit_epub_backend_artifacts: bool = False,
) -> None:
    """Replace the source-job worker and merge path with tiny deterministic writers."""

    def _fake_execute_source_job(
        job: Any,  # noqa: ANN401
        out: Path,
        mapping_config: Any,  # noqa: ANN401
        run_dt: Any,  # noqa: ANN401
        progress_queue: Any | None = None,  # noqa: ANN401
        display_name: str | None = None,
        epub_extractor: str | None = None,
        run_config: dict[str, Any] | None = None,
        run_config_hash: str | None = None,
        run_config_summary: str | None = None,
    ) -> dict[str, Any]:
        _ = out, mapping_config, progress_queue, display_name, epub_extractor
        file_path = job.file_path
        return {
            "file": file_path.name,
            "status": "success",
            "recipes": 1,
            "duration": 0.01,
            "timing": {
                "total_seconds": 0.01,
                "parsing_seconds": 0.004,
                "writing_seconds": 0.006,
            },
            "importer_name": importer_name,
            "job_index": job.job_index,
            "job_count": job.job_count,
            "start_page": job.start_page,
            "end_page": job.end_page,
            "start_spine": job.start_spine,
            "end_spine": job.end_spine,
            "result": None,
            "worker_label": "MainProcess (1)",
            "run_dt": run_dt,
            "run_config": dict(run_config or {}),
            "run_config_hash": str(run_config_hash or ("0" * 64)),
            "run_config_summary": str(run_config_summary or ""),
        }

    def _fake_merge_source_jobs(
        file_path: Path,
        job_results: list[dict[str, Any]],
        out: Path,
        mapping_config: Any,  # noqa: ANN401
        limit: int | None,
        run_dt: Any,  # noqa: ANN401
        *,
        importer_name: str | None = None,
        run_config: dict[str, Any] | None = None,
        run_config_hash: str | None = None,
        run_config_summary: str | None = None,
        write_markdown: bool = True,
        status_callback: Any | None = None,  # noqa: ANN401
    ) -> dict[str, Any]:
        _ = mapping_config, limit, status_callback
        workbook_slug = file_path.stem
        resolved_importer_name = (
            importer_name or job_results[0].get("importer_name") or "text"
        )
        final_dir = out / "final drafts" / workbook_slug
        intermediate_dir = out / "intermediate drafts" / workbook_slug
        sections_dir = out / "sections" / workbook_slug
        raw_dir = out / "raw" / resolved_importer_name / workbook_slug

        final_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        sections_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        (final_dir / "r0.draft-v1.json").write_text("{}", encoding="utf-8")
        (intermediate_dir / "r0.recipe.jsonld").write_text("{}", encoding="utf-8")
        (sections_dir / "r0.sections.json").write_text("[]", encoding="utf-8")
        (raw_dir / "raw.json").write_text("{}", encoding="utf-8")
        config_payload = dict(run_config or {})
        if emit_epub_backend_artifacts and resolved_importer_name == "epub":
            extractor = str(config_payload.get("epub_extractor") or "").strip()
            report_payload_extractor = extractor or "unstructured"
            raw_epub_dir = out / "raw" / "epub" / "fixture-hash"
            raw_epub_dir.mkdir(parents=True, exist_ok=True)
            if report_payload_extractor == "unstructured":
                (raw_epub_dir / "unstructured_elements.jsonl").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                (raw_epub_dir / "raw_spine_xhtml_001.xhtml").write_text(
                    "<html/>",
                    encoding="utf-8",
                )
                (raw_epub_dir / "norm_spine_xhtml_001.xhtml").write_text(
                    "<html/>",
                    encoding="utf-8",
                )
            if report_payload_extractor == "markitdown":
                (raw_epub_dir / "markitdown_markdown.md").write_text(
                    "# md\n",
                    encoding="utf-8",
                )
                config_payload.setdefault("effective_workers", 1)
            if report_payload_extractor == "markdown":
                (raw_epub_dir / "markdown_blocks.jsonl").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                config_payload.setdefault("epub_extractor_requested", "markdown")
                config_payload.setdefault("epub_extractor_effective", "markdown")
        if write_markdown:
            (sections_dir / "sections.md").write_text("# sections\n", encoding="utf-8")

        report_payload = {
            "runTimestamp": run_dt.isoformat(timespec="seconds"),
            "sourceFile": str(file_path),
            "importerName": resolved_importer_name,
            "totalRecipes": 1,
            "timing": {
                "total_seconds": 0.01,
                "parsing_seconds": 0.004,
                "writing_seconds": 0.006,
            },
            "runConfig": config_payload,
            "runConfigHash": str(run_config_hash or ("0" * 64)),
            "runConfigSummary": str(run_config_summary or ""),
            "outputStats": {
                "files": {
                    "total": {"count": 4, "bytes": 20},
                    "finalDrafts": {"count": 1, "bytes": 2},
                    "intermediateDrafts": {"count": 1, "bytes": 2},
                    "sections": {"count": 1, "bytes": 2},
                    "rawArtifacts": {"count": 1, "bytes": 2},
                }
            },
        }
        if emit_epub_backend_artifacts and resolved_importer_name == "epub":
            report_payload["epubBackend"] = str(
                config_payload.get("epub_extractor_effective")
                or config_payload.get("epub_extractor")
                or "unstructured"
            )
        report_path = out / f"{workbook_slug}.excel_import_report.json"
        report_path.write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "file": file_path.name,
            "status": "success",
            "recipes": 1,
            "duration": 0.01,
        }

    monkeypatch.setattr(cli_worker, "execute_source_job", _fake_execute_source_job)
    monkeypatch.setattr(cli, "_merge_source_jobs", _fake_merge_source_jobs)
    monkeypatch.setattr(
        "cookimport.cli_commands.stage._merge_source_jobs",
        _fake_merge_source_jobs,
    )


def install_fake_source_job_stage(
    monkeypatch: Any,
    *,
    importer_name: str = "text",
    emit_epub_backend_artifacts: bool = False,
) -> None:
    install_fake_source_job_pipeline(
        monkeypatch,
        importer_name=importer_name,
        emit_epub_backend_artifacts=emit_epub_backend_artifacts,
    )
