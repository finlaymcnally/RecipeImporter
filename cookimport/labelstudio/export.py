from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import datetime as dt

from cookimport.labelstudio.client import LabelStudioClient


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


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _select_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = task.get("annotations") or task.get("completions") or []
    if not annotations:
        return None
    annotations = [a for a in annotations if isinstance(a, dict)]
    if not annotations:
        return None
    annotations.sort(key=lambda item: item.get("id") or 0)
    return annotations[-1]


def _extract_labels(annotation: dict[str, Any]) -> dict[str, Any]:
    labels = {"content_type": None, "value_usefulness": None, "tags": []}
    results = annotation.get("result") or []
    for item in results:
        if not isinstance(item, dict):
            continue
        from_name = item.get("from_name")
        value = item.get("value") or {}
        choices = value.get("choices") or []
        if from_name == "content_type" and choices:
            labels["content_type"] = choices[0]
        elif from_name == "value_usefulness" and choices:
            labels["value_usefulness"] = choices[0]
        elif from_name == "tags" and choices:
            labels["tags"] = choices
    return labels


def _map_to_tip_label(labels: dict[str, Any]) -> str | None:
    content_type = labels.get("content_type")
    value_usefulness = labels.get("value_usefulness")
    if content_type in {"mixed", "unclear"}:
        return None
    if content_type == "tip" and value_usefulness != "useless":
        return "tip"
    if content_type in {"recipe", "step", "ingredient", "fluff", "other"}:
        return "not_tip"
    return None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def run_labelstudio_export(
    *,
    project_name: str,
    output_dir: Path,
    label_studio_url: str,
    label_studio_api_key: str,
    run_dir: Path | None,
) -> dict[str, Any]:
    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    manifest_path: Path | None = None
    manifest: dict[str, Any] | None = None
    project_id: int | None = None
    run_root = run_dir

    if run_dir is not None:
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_id = manifest.get("project_id")

    if project_id is None:
        manifest_path = _find_latest_manifest(output_dir, project_name)
        if manifest_path and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_id = manifest.get("project_id")
            run_root = manifest_path.parent

    project = None
    if project_id is None:
        project = client.find_project_by_title(project_name)
        if not project:
            raise FileNotFoundError(
                "Unable to locate manifest.json and project not found in Label Studio."
            )
        project_id = project.get("id")
        if not project_id:
            raise RuntimeError("Label Studio project lookup missing id.")

    if run_root is None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        run_root = output_dir / timestamp / "labelstudio" / _slugify_name(project_name)
        run_root.mkdir(parents=True, exist_ok=True)

    export_root = run_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    export_payload = client.export_tasks(project_id)
    export_path = export_root / "labelstudio_export.json"
    export_path.write_text(
        json.dumps(export_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    labeled_chunks: list[dict[str, Any]] = []
    golden_set: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    counts = {"labeled": 0, "missing": 0, "skipped": 0}

    for task in export_payload:
        if not isinstance(task, dict):
            continue
        data = task.get("data", {})
        chunk_id = data.get("chunk_id")
        if not chunk_id:
            continue
        annotation = _select_annotation(task)
        if annotation is None:
            counts["missing"] += 1
            continue
        labels = _extract_labels(annotation)
        labeled_chunks.append(
            {
                "chunk_id": chunk_id,
                "data": data,
                "labels": labels,
            }
        )
        counts["labeled"] += 1

        if data.get("chunk_level") != "atomic":
            continue
        tip_label = _map_to_tip_label(labels)
        if tip_label is None:
            skipped.append(
                {
                    "id": chunk_id,
                    "text": data.get("text_display") or data.get("text_raw"),
                    "labels": labels,
                }
            )
            counts["skipped"] += 1
            continue
        golden_set.append(
            {
                "id": chunk_id,
                "text": data.get("text_display") or data.get("text_raw"),
                "anchors": {},
                "label": tip_label,
                "notes": f"value_usefulness={labels.get('value_usefulness')}; tags={labels.get('tags')}",
            }
        )

    labeled_path = export_root / "labeled_chunks.jsonl"
    _write_jsonl(labeled_path, labeled_chunks)

    golden_path = export_root / "golden_set_tip_eval.jsonl"
    _write_jsonl(golden_path, golden_set)

    skipped_path = export_root / "skipped.jsonl"
    if skipped:
        _write_jsonl(skipped_path, skipped)

    summary = {
        "project_name": project_name,
        "project_id": project_id,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "counts": counts,
        "output": {
            "labeled_chunks": str(labeled_path),
            "golden_set": str(golden_path),
            "skipped": str(skipped_path) if skipped else None,
        },
    }
    summary_path = export_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "export_root": export_root,
        "summary": summary,
        "summary_path": summary_path,
    }
