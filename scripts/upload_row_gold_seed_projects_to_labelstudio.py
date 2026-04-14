#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.ingest_support import (
    _strip_task_annotations,
    _task_annotation_pairs_for_upload,
    _task_id_value,
)
from cookimport.labelstudio.label_config_freeform import build_freeform_label_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create fresh row-gold Label Studio projects from migrated "
            "row_seed_tasks.jsonl exports."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/golden/pulled-from-labelstudio"),
        help="Pulled Label Studio export root.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Limit upload to one or more book slugs under the root.",
    )
    parser.add_argument(
        "--project-suffix",
        default="source_rows_gold",
        help="Suffix appended to the original project title.",
    )
    parser.add_argument(
        "--label-studio-url",
        default=os.getenv("LABEL_STUDIO_URL") or "http://localhost:8080",
        help="Label Studio base URL. Defaults to LABEL_STUDIO_URL or localhost.",
    )
    parser.add_argument(
        "--label-studio-api-key",
        default=os.getenv("LABEL_STUDIO_API_KEY"),
        help="Label Studio API key. Defaults to LABEL_STUDIO_API_KEY.",
    )
    parser.add_argument(
        "--upload-batch-size",
        type=int,
        default=200,
        help="Task upload batch size.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help=(
            "Keep an existing replacement project with the same target title "
            "instead of deleting and recreating it."
        ),
    )
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _resolve_original_project_name(book_root: Path) -> str:
    candidates = (
        book_root / "run_manifest.json",
        book_root / "exports" / "summary.json",
    )
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        payload = _read_json(candidate)
        if candidate.name == "run_manifest.json":
            artifacts = payload.get("artifacts")
            if isinstance(artifacts, dict):
                value = artifacts.get("label_studio_project_name")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            value = payload.get("project_name")
            if isinstance(value, str) and value.strip():
                return value.strip()
            continue
        value = payload.get("project_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError(f"Could not resolve original project title for {book_root.name}")


def _build_target_project_name(original_name: str, suffix: str) -> str:
    normalized_suffix = str(suffix or "").strip()
    if not normalized_suffix:
        raise ValueError("project suffix must not be empty")
    full_name = f"{original_name} {normalized_suffix}"
    if len(full_name) <= 50:
        return full_name
    reserved = len(normalized_suffix) + 1
    available = 50 - reserved
    if available < 8:
        raise ValueError(
            "project suffix leaves too little room for a deterministic title"
        )
    truncated_original = original_name[:available].rstrip(" _-")
    if len(truncated_original) > available - 1:
        truncated_original = truncated_original[: available - 1].rstrip(" _-")
    return f"{truncated_original} {normalized_suffix}"


def _convert_seed_task_to_annotation_task(task: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    data = task.get("data")
    if isinstance(data, dict):
        converted["data"] = dict(data)
    annotations: list[dict[str, Any]] = []
    if isinstance(task.get("annotations"), list):
        for annotation in task["annotations"]:
            if isinstance(annotation, dict):
                annotations.append(annotation)
    if not annotations:
        predictions = task.get("predictions")
        if isinstance(predictions, list):
            for prediction in predictions:
                if not isinstance(prediction, dict):
                    continue
                result = prediction.get("result")
                if not isinstance(result, list) or not result:
                    continue
                annotation: dict[str, Any] = {
                    "result": result,
                    "ground_truth": False,
                    "meta": {
                        "seed_source": "row_seed_tasks.jsonl",
                    },
                }
                model_version = prediction.get("model_version")
                if model_version:
                    annotation["meta"]["seed_model_version"] = str(model_version)
                annotations.append(annotation)
    if annotations:
        converted["annotations"] = annotations
    return converted


def _upload_tasks_as_annotations(
    *,
    client: LabelStudioClient,
    project_id: int,
    tasks: list[dict[str, Any]],
    upload_batch_size: int,
) -> dict[str, Any]:
    if upload_batch_size < 1:
        raise ValueError("upload_batch_size must be a positive integer")
    inline_annotation_fallback = False
    inline_annotation_fallback_error: str | None = None
    post_import_annotation_pairs: list[tuple[str, dict[str, Any]]] = []
    post_import_annotations_created = 0
    uploaded_count = 0

    for start in range(0, len(tasks), upload_batch_size):
        batch = tasks[start : start + upload_batch_size]
        if not batch:
            continue
        if inline_annotation_fallback:
            client.import_tasks(
                project_id,
                [_strip_task_annotations(task) for task in batch],
            )
            post_import_annotation_pairs.extend(_task_annotation_pairs_for_upload(batch))
        else:
            try:
                client.import_tasks(project_id, batch)
            except Exception as exc:  # noqa: BLE001
                inline_annotation_fallback = True
                inline_annotation_fallback_error = str(exc)
                client.import_tasks(
                    project_id,
                    [_strip_task_annotations(task) for task in batch],
                )
                post_import_annotation_pairs.extend(_task_annotation_pairs_for_upload(batch))
        uploaded_count += len(batch)

    if post_import_annotation_pairs:
        remote_tasks = client.list_project_tasks(project_id)
        remote_task_ids: dict[str, int] = {}
        for remote_task in remote_tasks:
            if not isinstance(remote_task, dict):
                continue
            task_id = _task_id_value(remote_task)
            if not task_id:
                continue
            remote_id = remote_task.get("id")
            try:
                remote_task_ids[task_id] = int(remote_id)
            except (TypeError, ValueError):
                continue
        missing_task_ids: list[str] = []
        for task_id, annotation in post_import_annotation_pairs:
            remote_task_id = remote_task_ids.get(task_id)
            if remote_task_id is None:
                missing_task_ids.append(task_id)
                continue
            client.create_annotation(remote_task_id, annotation)
            post_import_annotations_created += 1
        if missing_task_ids:
            preview = ", ".join(missing_task_ids[:8])
            raise RuntimeError(
                "Post-import annotation creation could not resolve task ids for "
                f"{preview}"
            )

    return {
        "uploaded_task_count": uploaded_count,
        "inline_annotation_fallback": inline_annotation_fallback,
        "inline_annotation_fallback_error": inline_annotation_fallback_error,
        "post_import_annotations_created": post_import_annotations_created,
    }


def _count_seeded_annotations(tasks: list[dict[str, Any]]) -> int:
    count = 0
    for task in tasks:
        annotations = task.get("annotations")
        if not isinstance(annotations, list):
            continue
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            result = annotation.get("result")
            if isinstance(result, list):
                count += len(result)
    return count


def _iter_book_roots(root: Path, only: set[str]) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Missing pulled-from-labelstudio root: {root}")
    candidates = [path for path in root.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: path.name)
    if not only:
        return candidates
    return [path for path in candidates if path.name in only]


def main() -> int:
    args = _parse_args()
    if not args.label_studio_api_key:
        raise RuntimeError(
            "Label Studio API key missing. Use --label-studio-api-key or "
            "LABEL_STUDIO_API_KEY."
        )
    client = LabelStudioClient(args.label_studio_url, args.label_studio_api_key)
    label_config = build_freeform_label_config()

    selected = _iter_book_roots(args.root, set(args.only))
    if not selected:
        raise RuntimeError("No pulled gold-set folders matched the selection.")

    project_summaries: list[dict[str, Any]] = []
    for book_root in selected:
        tasks_path = book_root / "exports" / "row_seed_tasks.jsonl"
        summary_path = book_root / "exports" / "row_gold_labelstudio_project.json"
        if not tasks_path.exists() or not tasks_path.is_file():
            raise RuntimeError(f"Missing row seed tasks: {tasks_path}")
        original_project_name = _resolve_original_project_name(book_root)
        target_project_name = _build_target_project_name(
            original_project_name,
            args.project_suffix,
        )
        seed_tasks = _read_jsonl(tasks_path)
        annotation_tasks = [
            _convert_seed_task_to_annotation_task(task)
            for task in seed_tasks
        ]
        existing_project = client.find_project_by_title(target_project_name)
        if existing_project and not args.keep_existing:
            existing_id = existing_project.get("id")
            if existing_id is not None:
                client.delete_project(int(existing_id))
            existing_project = None
        project = existing_project
        if project is None:
            project = client.create_project(
                target_project_name,
                label_config,
                description=(
                    "Row-authoritative gold replacement imported from "
                    "migrated row_seed_tasks.jsonl."
                ),
            )
        project_id = project.get("id")
        if project_id is None:
            raise RuntimeError(
                f"Label Studio project creation failed for {target_project_name}"
            )
        project = client.update_project(
            int(project_id),
            {
                "show_annotation_history": True,
            },
        )
        upload_summary = _upload_tasks_as_annotations(
            client=client,
            project_id=int(project_id),
            tasks=annotation_tasks,
            upload_batch_size=args.upload_batch_size,
        )
        payload = {
            "book_slug": book_root.name,
            "original_project_name": original_project_name,
            "row_gold_project_name": target_project_name,
            "row_gold_project_id": int(project_id),
            "row_seed_tasks_path": str(tasks_path),
            "task_count": len(annotation_tasks),
            "seeded_annotation_count": _count_seeded_annotations(annotation_tasks),
            "show_annotation_history": bool(project.get("show_annotation_history")),
            **upload_summary,
        }
        _write_json(summary_path, payload)
        project_summaries.append(payload)
        print(
            f"{book_root.name}: created {target_project_name} "
            f"(id={int(project_id)}, tasks={len(annotation_tasks)})"
        )

    batch_summary = {
        "label_studio_url": args.label_studio_url,
        "project_suffix": args.project_suffix,
        "project_count": len(project_summaries),
        "projects": project_summaries,
    }
    batch_summary_path = args.root / "source_rows_labelstudio_upload_summary.json"
    _write_json(batch_summary_path, batch_summary)
    print(f"Wrote batch summary: {batch_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
