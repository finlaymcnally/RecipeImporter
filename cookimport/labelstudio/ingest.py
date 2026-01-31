from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from cookimport.core.reporting import compute_file_hash
from cookimport.plugins import registry
from cookimport.labelstudio.chunking import (
    build_extracted_archive,
    chunk_atomic,
    chunk_records_to_tasks,
    chunk_structural,
    compute_coverage,
    normalize_display_text,
    sample_chunks,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.label_config import LABEL_CONFIG_XML


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _resolve_project_name(book_slug: str, run_dt: dt.datetime, project_name: str | None) -> str:
    if project_name:
        return project_name
    return f"{book_slug}-{run_dt.strftime('%Y%m%d')}"


def _find_latest_manifest(output_root: Path, project_name: str) -> Path | None:
    manifests = list(output_root.glob("**/labelstudio/**/manifest.json"))
    candidates = []
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("project_name") == project_name:
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def run_labelstudio_import(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str,
    project_name: str | None,
    chunk_level: str,
    overwrite: bool,
    resume: bool,
    label_studio_url: str,
    label_studio_api_key: str,
    limit: int | None,
    sample: int | None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d-%H%M%S")
    book_slug = _slugify_name(path.stem)
    run_root = output_dir / timestamp / "labelstudio" / book_slug
    run_root.mkdir(parents=True, exist_ok=True)

    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    result = importer.convert(path, None, progress_callback=progress_callback)

    archive = build_extracted_archive(result, result.raw_artifacts)
    file_hash = compute_file_hash(path)
    book_id = result.workbook or path.stem

    levels = {"structural", "atomic", "both"}
    if chunk_level not in levels:
        raise ValueError("chunk_level must be one of: structural, atomic, both")

    chunks = []
    if chunk_level in {"structural", "both"}:
        chunks.extend(
            chunk_structural(
                result,
                archive,
                source_file=path.name,
                book_id=book_id,
                pipeline_used=importer.name,
                file_hash=file_hash,
            )
        )
    if chunk_level in {"atomic", "both"}:
        chunks.extend(
            chunk_atomic(
                result,
                archive,
                source_file=path.name,
                book_id=book_id,
                pipeline_used=importer.name,
                file_hash=file_hash,
            )
        )

    if not chunks:
        raise RuntimeError("No chunks generated for labeling.")

    coverage = compute_coverage(archive, chunks)
    if coverage.extracted_chars == 0:
        raise RuntimeError(
            "No text extracted; this may be a scanned document that requires OCR."
        )

    chunks = sample_chunks(chunks, limit=limit, sample=sample)
    if not chunks:
        raise RuntimeError("No chunks generated after limit/sample filters.")

    tasks = chunk_records_to_tasks(chunks)

    project_title = _resolve_project_name(book_slug, run_dt, project_name)
    client = LabelStudioClient(label_studio_url, label_studio_api_key)

    existing_project = client.find_project_by_title(project_title)
    if overwrite and existing_project:
        client.delete_project(existing_project["id"])
        existing_project = None

    project = existing_project
    if project is None:
        project = client.create_project(
            project_title,
            LABEL_CONFIG_XML,
            description="Cookbook benchmarking project (auto-generated)",
        )

    project_id = project.get("id")
    if project_id is None:
        raise RuntimeError("Label Studio project creation failed (missing id).")

    existing_chunk_ids: set[str] = set()
    resume_source: str | None = None
    if resume and not overwrite:
        manifest_path = _find_latest_manifest(output_dir, project_title)
        if manifest_path and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_chunk_ids = set(payload.get("chunk_ids", []))
            resume_source = str(manifest_path)

    upload_tasks: list[dict[str, Any]] = []
    for task in tasks:
        chunk_id = task.get("data", {}).get("chunk_id")
        if chunk_id and chunk_id in existing_chunk_ids:
            continue
        upload_tasks.append(task)

    batch_size = 200
    uploaded_count = 0
    for start in range(0, len(upload_tasks), batch_size):
        batch = upload_tasks[start : start + batch_size]
        if not batch:
            continue
        client.import_tasks(project_id, batch)
        uploaded_count += len(batch)

    archive_path = run_root / "extracted_archive.json"
    archive_payload = [
        {
            "index": block.index,
            "text": block.text,
            "location": block.location,
            "source_kind": block.source_kind,
        }
        for block in archive
    ]
    archive_path.write_text(
        json.dumps(archive_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    extracted_text = "\n\n".join(block.text for block in archive if block.text)
    (run_root / "extracted_text.txt").write_text(
        normalize_display_text(extracted_text) + "\n", encoding="utf-8"
    )

    tasks_path = run_root / "label_studio_tasks.jsonl"
    tasks_path.write_text(
        "\n".join(json.dumps(task) for task in tasks) + "\n", encoding="utf-8"
    )

    coverage_path = run_root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "extracted_chars": coverage.extracted_chars,
                "chunked_chars": coverage.chunked_chars,
                "warnings": coverage.warnings,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = {
        "project_name": project_title,
        "project_id": project_id,
        "pipeline": importer.name,
        "source_file": str(path),
        "book_id": book_id,
        "run_timestamp": run_dt.isoformat(timespec="seconds"),
        "chunk_level": chunk_level,
        "task_count": len(tasks),
        "uploaded_task_count": uploaded_count,
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
        "coverage": {
            "extracted_chars": coverage.extracted_chars,
            "chunked_chars": coverage.chunked_chars,
            "warnings": coverage.warnings,
        },
        "resume_source": resume_source,
        "label_studio_url": label_studio_url,
    }

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    project_path = run_root / "project.json"
    project_path.write_text(
        json.dumps(project, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "project": project,
        "project_name": project_title,
        "project_id": project_id,
        "run_root": run_root,
        "tasks_total": len(tasks),
        "tasks_uploaded": uploaded_count,
        "manifest_path": manifest_path,
    }
