from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from cookimport.core.reporting import compute_file_hash
from cookimport.plugins import registry
from cookimport.labelstudio.block_tasks import (
    build_block_tasks,
    load_task_ids_from_jsonl,
    sample_block_tasks,
)
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    compute_freeform_task_coverage,
    sample_freeform_tasks,
)
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
from cookimport.labelstudio.label_config_blocks import build_block_label_config
from cookimport.labelstudio.label_config_freeform import build_freeform_label_config


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _dedupe_project_name(base_name: str, existing_titles: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in existing_titles:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _resolve_project_name(path: Path, project_name: str | None, client: LabelStudioClient) -> str:
    if project_name:
        return project_name

    base_name = path.stem.strip() or _slugify_name(path.stem)
    existing_titles = {
        str(project.get("title", ""))
        for project in client.list_projects()
        if isinstance(project, dict) and project.get("title")
    }
    return _dedupe_project_name(base_name, existing_titles)


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


def _compute_block_task_coverage(
    archive: list[Any], tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    extracted_chars = sum(len(getattr(block, "text", "") or "") for block in archive)
    chunked_chars = 0
    for task in tasks:
        data = task.get("data") if isinstance(task, dict) else {}
        if isinstance(data, dict):
            chunked_chars += len(str(data.get("block_text") or ""))
    warnings: list[str] = []
    if extracted_chars == 0:
        warnings.append("No text extracted; OCR may be required for scanned documents.")
    elif chunked_chars < extracted_chars * 0.9:
        warnings.append(
            f"Chunk coverage low: {chunked_chars} of {extracted_chars} characters represented."
        )
    return {
        "extracted_chars": extracted_chars,
        "chunked_chars": chunked_chars,
        "warnings": warnings,
    }


def _task_id_key(task_scope: str) -> str:
    if task_scope == "canonical-blocks":
        return "block_id"
    if task_scope == "freeform-spans":
        return "segment_id"
    return "chunk_id"


def run_labelstudio_import(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str,
    project_name: str | None,
    chunk_level: str,
    task_scope: str,
    context_window: int,
    segment_blocks: int = 40,
    segment_overlap: int = 5,
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

    scopes = {"pipeline", "canonical-blocks", "freeform-spans"}
    if task_scope not in scopes:
        raise ValueError(
            "task_scope must be one of: pipeline, canonical-blocks, freeform-spans"
        )

    tasks: list[dict[str, Any]] = []
    task_ids: list[str] = []
    coverage_payload: dict[str, Any]
    label_config = LABEL_CONFIG_XML
    chunk_ids: list[str] | None = None
    block_ids: list[str] | None = None
    segment_ids: list[str] | None = None

    if task_scope == "pipeline":
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
        coverage_payload = {
            "extracted_chars": coverage.extracted_chars,
            "chunked_chars": coverage.chunked_chars,
            "warnings": coverage.warnings,
        }
        if coverage.extracted_chars == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )

        chunks = sample_chunks(chunks, limit=limit, sample=sample)
        if not chunks:
            raise RuntimeError("No chunks generated after limit/sample filters.")

        tasks = chunk_records_to_tasks(chunks, source_hash=file_hash)
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        task_ids = list(chunk_ids)
    elif task_scope == "canonical-blocks":
        if chunk_level != "both" and progress_callback is not None:
            progress_callback("canonical-blocks ignores --chunk-level")
        if not archive:
            raise RuntimeError("No extracted blocks available for canonical labeling.")
        tasks_all = build_block_tasks(
            archive,
            source_hash=file_hash,
            source_file=path.name,
            context_window=context_window,
        )
        if not tasks_all:
            raise RuntimeError("No block tasks generated for labeling.")
        coverage_payload = _compute_block_task_coverage(archive, tasks_all)
        if coverage_payload["extracted_chars"] == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )
        tasks = sample_block_tasks(tasks_all, limit=limit, sample=sample)
        if not tasks:
            raise RuntimeError("No block tasks generated after limit/sample filters.")
        label_config = build_block_label_config()
        block_ids = [task.get("data", {}).get("block_id") for task in tasks if task]
        task_ids = [block_id for block_id in block_ids if block_id]
    else:
        if chunk_level != "both" and progress_callback is not None:
            progress_callback("freeform-spans ignores --chunk-level")
        if not archive:
            raise RuntimeError("No extracted blocks available for freeform labeling.")
        tasks_all = build_freeform_span_tasks(
            archive=archive,
            source_hash=file_hash,
            source_file=path.name,
            book_id=book_id,
            segment_blocks=segment_blocks,
            segment_overlap=segment_overlap,
        )
        if not tasks_all:
            raise RuntimeError("No freeform span tasks generated for labeling.")
        coverage_payload = compute_freeform_task_coverage(archive, tasks_all)
        if coverage_payload["extracted_chars"] == 0:
            raise RuntimeError(
                "No text extracted; this may be a scanned document that requires OCR."
            )
        tasks = sample_freeform_tasks(tasks_all, limit=limit, sample=sample)
        if not tasks:
            raise RuntimeError(
                "No freeform span tasks generated after limit/sample filters."
            )
        label_config = build_freeform_label_config()
        segment_ids = [task.get("data", {}).get("segment_id") for task in tasks if task]
        task_ids = [segment_id for segment_id in segment_ids if segment_id]

    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    project_title = _resolve_project_name(path, project_name, client)

    existing_project = client.find_project_by_title(project_title)
    if overwrite and existing_project:
        client.delete_project(existing_project["id"])
        existing_project = None

    project = existing_project
    if project is None:
        project = client.create_project(
            project_title,
            label_config,
            description="Cookbook benchmarking project (auto-generated)",
        )

    project_id = project.get("id")
    if project_id is None:
        raise RuntimeError("Label Studio project creation failed (missing id).")

    existing_task_ids: set[str] = set()
    resume_source: str | None = None
    if resume and not overwrite:
        manifest_path = _find_latest_manifest(output_dir, project_title)
        if manifest_path and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            resume_scope = payload.get("task_scope", "pipeline")
            if resume_scope != task_scope:
                raise RuntimeError(
                    f"Existing project uses task_scope={resume_scope}; "
                    "use a matching task_scope or a new project name."
                )
            resume_source = str(manifest_path)
            existing_task_ids = set(
                payload.get("segment_ids")
                or []
            ) or set(
                payload.get("block_ids")
                or payload.get("chunk_ids")
                or payload.get("task_ids")
                or []
            )
            tasks_path = manifest_path.parent / "label_studio_tasks.jsonl"
            if not existing_task_ids and tasks_path.exists():
                existing_task_ids = load_task_ids_from_jsonl(
                    tasks_path, _task_id_key(task_scope)
                )

    upload_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_id_key = _task_id_key(task_scope)
        task_id = task.get("data", {}).get(task_id_key)
        if task_id and task_id in existing_task_ids:
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
            coverage_payload,
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
        "chunk_level": chunk_level if task_scope == "pipeline" else None,
        "task_scope": task_scope,
        "context_window": context_window if task_scope == "canonical-blocks" else None,
        "segment_blocks": segment_blocks if task_scope == "freeform-spans" else None,
        "segment_overlap": segment_overlap if task_scope == "freeform-spans" else None,
        "task_count": len(tasks),
        "uploaded_task_count": uploaded_count,
        "task_ids": task_ids,
        "chunk_ids": chunk_ids,
        "block_ids": block_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
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
