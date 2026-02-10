from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import datetime as dt

from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.canonical import derive_gold_spans, BLOCK_LABELS
from cookimport.labelstudio.freeform_tasks import map_span_offsets_to_blocks


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


def _extract_block_label(annotation: dict[str, Any]) -> str | None:
    results = annotation.get("result") or []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("from_name") != "block_label":
            continue
        value = item.get("value") or {}
        choices = value.get("choices") or []
        if choices:
            return choices[0]
    return None


def _resolve_annotator(annotation: dict[str, Any]) -> str | None:
    for key in ("completed_by", "updated_by", "created_by", "annotator"):
        value = annotation.get(key)
        if isinstance(value, dict):
            return value.get("email") or value.get("username") or str(value.get("id"))
        if value:
            return str(value)
    return None


def _resolve_annotation_time(annotation: dict[str, Any]) -> str | None:
    for key in ("completed_at", "updated_at", "created_at"):
        value = annotation.get(key)
        if value:
            return str(value)
    return None


def _parse_block_id(block_id: str) -> tuple[str | None, int | None]:
    parts = block_id.split(":")
    if len(parts) < 5:
        return None, None
    if parts[0] != "urn" or parts[1] != "cookimport" or parts[2] != "block":
        return None, None
    source_hash = parts[3]
    try:
        block_index = int(parts[4])
    except ValueError:
        block_index = None
    return source_hash, block_index


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


def _extract_freeform_spans(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        labels = value.get("labels")
        if not isinstance(labels, list) or not labels:
            continue
        start = value.get("start")
        end = value.get("end")
        if start is None or end is None:
            continue
        try:
            start_offset = int(start)
            end_offset = int(end)
        except (TypeError, ValueError):
            continue
        selected_text = value.get("text") or ""
        to_name = item.get("to_name")
        result_id = item.get("id")
        for label in labels:
            spans.append(
                {
                    "label": str(label),
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "selected_text": str(selected_text),
                    "to_name": str(to_name) if to_name else None,
                    "result_id": str(result_id) if result_id else None,
                }
            )
    return spans


def _build_freeform_span_id(
    *,
    source_hash: str,
    segment_id: str,
    label: str,
    start_offset: int,
    end_offset: int,
    selected_text: str,
) -> str:
    digest_input = (
        f"{source_hash}|{segment_id}|{label}|{start_offset}|{end_offset}|{selected_text}"
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
    return f"urn:cookimport:freeform_span:{source_hash}:{digest}"


def run_labelstudio_export(
    *,
    project_name: str,
    output_dir: Path,
    label_studio_url: str,
    label_studio_api_key: str,
    run_dir: Path | None,
    export_scope: str,
) -> dict[str, Any]:
    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    manifest_path: Path | None = None
    manifest: dict[str, Any] | None = None
    project_id: int | None = None
    run_root = run_dir

    scopes = {"pipeline", "canonical-blocks", "freeform-spans"}
    if export_scope not in scopes:
        raise ValueError(
            "export_scope must be one of: pipeline, canonical-blocks, freeform-spans"
        )

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

    if manifest and manifest.get("task_scope"):
        task_scope = manifest.get("task_scope")
        if task_scope != export_scope:
            raise RuntimeError(
                f"Run manifest uses task_scope={task_scope}; "
                f"use --export-scope {task_scope} or point to a matching --run-dir."
            )

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

    if export_scope == "freeform-spans":
        span_rows: list[dict[str, Any]] = []
        segment_rows: dict[str, dict[str, Any]] = {}
        counts = {"labeled": 0, "missing": 0, "skipped": 0}

        for task in export_payload:
            if not isinstance(task, dict):
                continue
            data = task.get("data")
            if not isinstance(data, dict):
                continue
            segment_id = data.get("segment_id")
            if not segment_id:
                continue
            source_hash = str(data.get("source_hash") or "unknown")
            source_file = str(data.get("source_file") or "unknown")
            book_id = str(data.get("book_id") or "unknown")
            segment_text = str(data.get("segment_text") or "")
            source_map = data.get("source_map")
            if not isinstance(source_map, dict):
                source_map = {}

            segment_rows[str(segment_id)] = {
                "segment_id": str(segment_id),
                "source_hash": source_hash,
                "source_file": source_file,
                "book_id": book_id,
                "segment_index": data.get("segment_index"),
                "segment_text_length": len(segment_text),
                "source_map": source_map,
            }

            annotation = _select_annotation(task)
            if annotation is None:
                counts["missing"] += 1
                continue
            freeform_spans = _extract_freeform_spans(annotation)
            if not freeform_spans:
                counts["skipped"] += 1
                continue

            for span in freeform_spans:
                start_offset = int(span["start_offset"])
                end_offset = int(span["end_offset"])
                label = str(span["label"])
                if start_offset < 0 or end_offset <= start_offset:
                    counts["skipped"] += 1
                    continue
                if end_offset > len(segment_text):
                    counts["skipped"] += 1
                    continue
                touched_blocks = map_span_offsets_to_blocks(
                    source_map, start_offset, end_offset
                )
                touched_block_ids = [
                    block.get("block_id")
                    for block in touched_blocks
                    if isinstance(block, dict) and block.get("block_id")
                ]
                touched_block_indices = [
                    int(block.get("block_index"))
                    for block in touched_blocks
                    if isinstance(block, dict) and block.get("block_index") is not None
                ]
                selected_text = str(span.get("selected_text") or "")
                span_rows.append(
                    {
                        "span_id": _build_freeform_span_id(
                            source_hash=source_hash,
                            segment_id=str(segment_id),
                            label=label,
                            start_offset=start_offset,
                            end_offset=end_offset,
                            selected_text=selected_text,
                        ),
                        "segment_id": str(segment_id),
                        "source_hash": source_hash,
                        "source_file": source_file,
                        "book_id": book_id,
                        "label": label,
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                        "selected_text": selected_text,
                        "segment_text_length": len(segment_text),
                        "touched_block_ids": touched_block_ids,
                        "touched_block_indices": touched_block_indices,
                        "touched_blocks": touched_blocks,
                        "annotator": _resolve_annotator(annotation),
                        "annotated_at": _resolve_annotation_time(annotation),
                        "annotation_id": annotation.get("id"),
                        "result_id": span.get("result_id"),
                    }
                )
                counts["labeled"] += 1

        span_rows.sort(
            key=lambda item: (
                item.get("source_hash") or "",
                item.get("segment_id") or "",
                int(item.get("start_offset") or 0),
                int(item.get("end_offset") or 0),
                item.get("label") or "",
                item.get("span_id") or "",
            )
        )
        segment_manifest_rows = [
            segment_rows[key] for key in sorted(segment_rows.keys())
        ]

        spans_path = export_root / "freeform_span_labels.jsonl"
        _write_jsonl(spans_path, span_rows)

        segment_manifest_path = export_root / "freeform_segment_manifest.jsonl"
        _write_jsonl(segment_manifest_path, segment_manifest_rows)

        summary = {
            "project_name": project_name,
            "project_id": project_id,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "counts": counts,
            "output": {
                "freeform_span_labels": str(spans_path),
                "freeform_segment_manifest": str(segment_manifest_path),
                "export_payload": str(export_path),
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

    if export_scope == "canonical-blocks":
        block_labels: list[dict[str, Any]] = []
        counts = {"labeled": 0, "missing": 0, "skipped": 0}

        for task in export_payload:
            if not isinstance(task, dict):
                continue
            data = task.get("data", {})
            block_id = data.get("block_id")
            if not block_id:
                continue
            annotation = _select_annotation(task)
            if annotation is None:
                counts["missing"] += 1
                continue
            label = _extract_block_label(annotation)
            if label not in BLOCK_LABELS:
                counts["skipped"] += 1
                continue
            source_hash = data.get("source_hash")
            block_index = data.get("block_index")
            source_file = data.get("source_file")
            parsed_hash, parsed_index = _parse_block_id(block_id)
            if source_hash is None:
                source_hash = parsed_hash
            if block_index is None:
                block_index = parsed_index
            if source_hash is None or block_index is None or not source_file:
                counts["skipped"] += 1
                continue
            block_labels.append(
                {
                    "block_id": block_id,
                    "source_hash": str(source_hash),
                    "source_file": str(source_file),
                    "block_index": int(block_index),
                    "label": label,
                    "annotator": _resolve_annotator(annotation),
                    "annotated_at": _resolve_annotation_time(annotation),
                }
            )
            counts["labeled"] += 1

        labels_path = export_root / "canonical_block_labels.jsonl"
        _write_jsonl(labels_path, block_labels)

        gold_spans = derive_gold_spans(block_labels)
        spans_path = export_root / "canonical_gold_spans.jsonl"
        _write_jsonl(spans_path, gold_spans)

        summary = {
            "project_name": project_name,
            "project_id": project_id,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "counts": counts,
            "output": {
                "canonical_block_labels": str(labels_path),
                "canonical_gold_spans": str(spans_path),
                "export_payload": str(export_path),
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
