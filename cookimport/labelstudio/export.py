from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from cookimport.labelstudio.block_gold import (
    derive_block_gold_bundle,
    write_block_gold_rows,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.freeform_tasks import map_span_offsets_to_blocks
from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.labelstudio.row_gold import derive_row_gold_bundle, write_row_gold_rows
from cookimport.runs import RunManifest, RunSource, write_run_manifest

logger = logging.getLogger(__name__)
_RECIPE_HEADER_LABEL = "RECIPE_TITLE"
_SUPPORTED_SCOPE = "freeform-spans"


def _find_latest_manifest(output_root: Path, project_name: str) -> Path | None:
    search_roots = [output_root]
    parent_root = output_root.parent
    if parent_root not in search_roots:
        search_roots.append(parent_root)

    manifests: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        manifests.extend(root.glob("**/labelstudio/**/manifest.json"))

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


def _normalize_source_hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _normalize_source_file(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _slugify_source_file(source_file: str | None) -> str | None:
    normalized = _normalize_source_file(source_file)
    if not normalized:
        return None
    source_stem = Path(normalized.replace("\\", "/")).stem
    if not source_stem:
        return None
    return _slugify_name(source_stem)


def _infer_source_identity_from_export_payload(
    payload: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    source_hashes: set[str] = set()
    source_files: set[str] = set()
    for task in payload:
        if not isinstance(task, dict):
            continue
        data = task.get("data")
        if not isinstance(data, dict):
            continue
        normalized_hash = _normalize_source_hash(data.get("source_hash"))
        if normalized_hash:
            source_hashes.add(normalized_hash)
        normalized_file = _normalize_source_file(data.get("source_file"))
        if normalized_file:
            source_files.add(normalized_file)
    source_hash = next(iter(source_hashes)) if len(source_hashes) == 1 else None
    source_file = next(iter(source_files)) if len(source_files) == 1 else None
    return source_hash, source_file


def _load_run_manifest_source_identity(run_root: Path) -> tuple[str | None, str | None]:
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return None, None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    source = payload.get("source")
    if not isinstance(source, dict):
        return None, None
    return (
        _normalize_source_hash(source.get("source_hash")),
        _normalize_source_file(source.get("path")),
    )


def _find_existing_export_run_root_for_source(
    *,
    output_dir: Path,
    source_hash: str | None,
    source_file: str | None,
    preferred_slug: str | None,
) -> Path | None:
    if not output_dir.exists() or not output_dir.is_dir():
        return None

    normalized_hash = _normalize_source_hash(source_hash)
    normalized_file = _normalize_source_file(source_file)
    if not normalized_hash and not normalized_file:
        return None

    source_basename = (
        Path(normalized_file.replace("\\", "/")).name.casefold()
        if normalized_file
        else None
    )

    candidates: list[tuple[int, int, float, Path]] = []
    for candidate in output_dir.iterdir():
        if not candidate.is_dir():
            continue
        manifest_hash, manifest_file = _load_run_manifest_source_identity(candidate)
        score = 0
        if normalized_hash and manifest_hash == normalized_hash:
            score += 3
        if normalized_file and manifest_file:
            if manifest_file == normalized_file:
                score += 2
            elif (
                source_basename
                and Path(manifest_file.replace("\\", "/")).name.casefold()
                == source_basename
            ):
                score += 1
        if score <= 0:
            continue
        preferred_match = 1 if preferred_slug and candidate.name == preferred_slug else 0
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((score, preferred_match, mtime, candidate))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][3]


def _resolve_export_run_root(
    *,
    output_dir: Path,
    project_name: str,
    manifest_source_hash: str | None,
    manifest_source_file: str | None,
    export_payload: list[dict[str, Any]],
) -> Path:
    payload_source_hash, payload_source_file = _infer_source_identity_from_export_payload(
        export_payload
    )
    source_hash = payload_source_hash or _normalize_source_hash(manifest_source_hash)
    source_file = payload_source_file or _normalize_source_file(manifest_source_file)
    preferred_slug = _slugify_source_file(source_file)
    if preferred_slug:
        preferred_path = output_dir / preferred_slug
        if preferred_path.exists() and preferred_path.is_dir():
            return preferred_path

    existing_root = _find_existing_export_run_root_for_source(
        output_dir=output_dir,
        source_hash=source_hash,
        source_file=source_file,
        preferred_slug=preferred_slug,
    )
    if existing_root is not None:
        return existing_root

    if preferred_slug:
        return output_dir / preferred_slug
    return output_dir / _slugify_name(project_name)


def _select_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = task.get("annotations") or task.get("completions") or []
    if not annotations:
        return None
    annotations = [a for a in annotations if isinstance(a, dict)]
    if not annotations:
        return None
    annotations.sort(key=lambda item: item.get("id") or 0)
    return annotations[-1]


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_freeform_recipe_headers(
    span_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    """Return (deduped_recipe_headers, raw_recipe_header_rows)."""
    raw_recipe_headers = 0
    dedupe_keys: set[tuple[str, str, int, int]] = set()

    for row in span_rows:
        label_raw = row.get("label")
        if not isinstance(label_raw, str):
            continue
        if normalize_freeform_label(label_raw) != _RECIPE_HEADER_LABEL:
            continue
        raw_recipe_headers += 1

        touched_values = row.get("touched_block_indices")
        if not isinstance(touched_values, list):
            continue
        touched_indices: list[int] = []
        for value in touched_values:
            parsed = _parse_int(value)
            if parsed is None:
                continue
            touched_indices.append(parsed)
        if not touched_indices:
            continue

        dedupe_keys.add(
            (
                str(row.get("source_hash") or ""),
                str(row.get("source_file") or ""),
                min(touched_indices),
                max(touched_indices),
            )
        )

    return len(dedupe_keys), raw_recipe_headers


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_export_run_manifest(
    *,
    run_root: Path,
    task_scope: str,
    project_name: str,
    project_id: int | None,
    source_file: str | None,
    source_hash: str | None,
    importer_name: str | None,
    artifact_paths: dict[str, Path | str | None],
    notes: str | None = None,
) -> None:
    artifacts: dict[str, Any] = {
        "label_studio_project_name": project_name,
        "label_studio_project_id": project_id,
    }
    for key, value in artifact_paths.items():
        path_value = _path_for_manifest(run_root, value)
        if path_value:
            artifacts[key] = path_value
    manifest = RunManifest(
        run_kind="labelstudio_export",
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=source_file,
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config={"task_scope": task_scope},
        artifacts=artifacts,
        notes=notes,
    )
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to write run_manifest.json for Label Studio export at %s: %s",
            run_root,
            exc,
        )


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


def _infer_scope_from_project_payload(project: dict[str, Any]) -> str | None:
    explicit_scope = str(project.get("task_scope", "")).strip()
    if explicit_scope:
        return explicit_scope

    label_config = str(project.get("label_config", "") or "")
    if not label_config:
        return None
    if any(
        marker in label_config
        for marker in (
            "YIELD_LINE",
            "TIME_LINE",
            "RECIPE_NOTES",
            "RECIPE_VARIANT",
            "HOWTO_SECTION",
            "KNOWLEDGE",
        )
    ):
        return _SUPPORTED_SCOPE
    if (
        "RECIPE_TITLE" in label_config
        and "INGREDIENT_LINE" in label_config
        and "INSTRUCTION_LINE" in label_config
        and "NARRATIVE" in label_config
        and "VARIANT" not in label_config
        and "RECIPE_VARIANT" not in label_config
    ):
        return "canonical-blocks"
    if "mixed" in label_config and "value_usefulness" in label_config:
        return "pipeline"
    return None


def _infer_scope_from_export_payload(payload: list[dict[str, Any]]) -> str | None:
    seen_scopes: set[str] = set()
    for task in payload:
        if not isinstance(task, dict):
            continue
        data = task.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("segment_id"):
            seen_scopes.add(_SUPPORTED_SCOPE)
        if data.get("chunk_id"):
            seen_scopes.add("pipeline")
        if data.get("block_id"):
            seen_scopes.add("canonical-blocks")
    if len(seen_scopes) == 1:
        return next(iter(seen_scopes))
    if len(seen_scopes) > 1:
        return "mixed"
    return None


def _require_freeform_scope(scope: str | None, *, source: str) -> None:
    if scope in {None, "", _SUPPORTED_SCOPE}:
        return
    if scope == "mixed":
        raise RuntimeError(
            "Export payload mixes multiple Label Studio task scopes; "
            "export supports freeform-spans projects only."
        )
    raise RuntimeError(
        f"Label Studio scope '{scope}' detected in {source}; "
        "export supports freeform-spans projects only."
    )


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
    manifest_source_file: str | None = None
    manifest_source_hash: str | None = None
    manifest_importer: str | None = None

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

    if isinstance(manifest, dict):
        source_file_raw = str(manifest.get("source_file") or "").strip()
        source_hash_raw = str(manifest.get("source_hash") or "").strip()
        importer_raw = str(manifest.get("importer_name") or "").strip()
        manifest_source_file = source_file_raw or None
        manifest_source_hash = source_hash_raw or None
        manifest_importer = importer_raw or None
        manifest_scope = str(manifest.get("task_scope") or "").strip() or None
        _require_freeform_scope(manifest_scope, source="run manifest")

    project = client.find_project_by_title(project_name)
    if not project:
        raise FileNotFoundError(
            "Project not found in Label Studio for the supplied project name."
        )

    project_scope = _infer_scope_from_project_payload(project)
    _require_freeform_scope(project_scope, source=f"project '{project_name}'")

    if project_id is None:
        project_id = project.get("id")
    if not project_id:
        raise RuntimeError("Label Studio project lookup missing id.")

    export_payload = client.export_tasks(int(project_id))

    payload_scope = _infer_scope_from_export_payload(export_payload)
    _require_freeform_scope(payload_scope, source="export payload")

    if run_root is None:
        run_root = _resolve_export_run_root(
            output_dir=output_dir,
            project_name=project_name,
            manifest_source_hash=manifest_source_hash,
            manifest_source_file=manifest_source_file,
            export_payload=[row for row in export_payload if isinstance(row, dict)],
        )
    run_root.mkdir(parents=True, exist_ok=True)
    export_root = run_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    export_path = export_root / "labelstudio_export.json"
    export_path.write_text(
        json.dumps(export_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

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
            raw_touched_rows = map_span_offsets_to_blocks(
                source_map,
                start_offset,
                end_offset,
            )
            touched_rows: list[dict[str, Any]] = []
            for row in raw_touched_rows:
                if not isinstance(row, dict):
                    continue
                row_start = row.get("segment_start")
                row_end = row.get("segment_end")
                try:
                    row_start_i = int(row_start)
                    row_end_i = int(row_end)
                except (TypeError, ValueError):
                    row_start_i = None
                    row_end_i = None
                row_text = str(row.get("text") or "")
                if (
                    not row_text
                    and row_start_i is not None
                    and row_end_i is not None
                    and row_end_i > row_start_i
                ):
                    row_text = segment_text[row_start_i:row_end_i]
                touched_rows.append({**row, "text": row_text})
            touched_row_ids = [
                row.get("row_id")
                for row in touched_rows
                if isinstance(row, dict) and row.get("row_id")
            ]
            touched_row_indices = [
                int(row.get("row_index", row.get("block_index")))
                for row in touched_rows
                if isinstance(row, dict)
                and row.get("row_index", row.get("block_index")) is not None
            ]
            touched_block_ids = [
                row.get("source_block_id") or row.get("block_id")
                for row in touched_rows
                if isinstance(row, dict) and (row.get("source_block_id") or row.get("block_id"))
            ]
            touched_block_indices = [
                int(row.get("source_block_index", row.get("block_index")))
                for row in touched_rows
                if isinstance(row, dict)
                and row.get("source_block_index", row.get("block_index")) is not None
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
                    "touched_row_ids": touched_row_ids,
                    "touched_row_indices": touched_row_indices,
                    "touched_rows": touched_rows,
                    "touched_block_ids": touched_block_ids,
                    "touched_block_indices": touched_block_indices,
                    "touched_blocks": touched_rows,
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
    segment_manifest_rows = [segment_rows[key] for key in sorted(segment_rows.keys())]

    spans_path = export_root / "freeform_span_labels.jsonl"
    _write_jsonl(spans_path, span_rows)

    segment_manifest_path = export_root / "freeform_segment_manifest.jsonl"
    _write_jsonl(segment_manifest_path, segment_manifest_rows)

    row_gold_bundle = derive_row_gold_bundle(span_rows)
    row_gold_rows = list(row_gold_bundle.get("rows") or [])
    row_gold_conflicts = list(row_gold_bundle.get("conflicts") or [])
    row_gold_path = export_root / "row_gold_labels.jsonl"
    row_gold_conflicts_path = export_root / "row_gold_conflicts.jsonl"
    write_row_gold_rows(row_gold_path, row_gold_rows)
    write_row_gold_rows(row_gold_conflicts_path, row_gold_conflicts)

    block_gold_bundle = derive_block_gold_bundle(span_rows)
    block_gold_rows = list(block_gold_bundle.get("rows") or [])
    block_gold_path = export_root / "block_gold_labels.jsonl"
    write_block_gold_rows(block_gold_path, block_gold_rows)

    deduped_recipe_headers, raw_recipe_headers = _count_freeform_recipe_headers(span_rows)
    counts["recipe_headers"] = deduped_recipe_headers

    summary = {
        "project_name": project_name,
        "project_id": project_id,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "counts": counts,
        "recipe_counts": {
            "label": _RECIPE_HEADER_LABEL,
            "recipe_headers": deduped_recipe_headers,
            "recipe_headers_raw": raw_recipe_headers,
            "dedupe_key": "source_hash+source_file+start_block_index+end_block_index",
        },
        "block_gold": {
            "block_count": len(block_gold_rows),
            "multilabel_block_count": sum(
                1
                for row in block_gold_rows
                if len(list(row.get("labels") or [])) > 1
            ),
        },
        "row_gold": {
            "row_count": len(row_gold_rows),
            "multilabel_row_count": len(row_gold_conflicts),
        },
        "output": {
            "freeform_span_labels": str(spans_path),
            "freeform_segment_manifest": str(segment_manifest_path),
            "row_gold_labels": str(row_gold_path),
            "row_gold_conflicts": str(row_gold_conflicts_path),
            "block_gold_labels": str(block_gold_path),
            "export_payload": str(export_path),
        },
    }
    summary_path = export_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_export_run_manifest(
        run_root=run_root,
        task_scope=_SUPPORTED_SCOPE,
        project_name=project_name,
        project_id=int(project_id),
        source_file=manifest_source_file,
        source_hash=manifest_source_hash,
        importer_name=manifest_importer,
        artifact_paths={
            "summary_json": summary_path,
            "export_payload_json": export_path,
            "freeform_span_labels_jsonl": spans_path,
            "freeform_segment_manifest_jsonl": segment_manifest_path,
            "row_gold_labels_jsonl": row_gold_path,
            "row_gold_conflicts_jsonl": row_gold_conflicts_path,
            "block_gold_labels_jsonl": block_gold_path,
        },
        notes="Exported freeform span labels from Label Studio.",
    )

    return {
        "export_root": export_root,
        "summary": summary,
        "summary_path": summary_path,
    }
