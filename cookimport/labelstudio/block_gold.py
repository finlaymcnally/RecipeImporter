from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.labelstudio.howto_section import resolve_howto_label_sets_by_index
from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_block_gold_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_block_gold_rows(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def _new_blockization_profile() -> dict[str, Any]:
    return {
        "min_block_index": None,
        "max_block_index": None,
        "seen_block_indices": set(),
        "extraction_backends": set(),
        "unstructured_html_parser_versions": set(),
        "unstructured_preprocess_modes": set(),
        "unstructured_skip_headers_footers": set(),
    }


def _update_blockization_profile_index(profile: dict[str, Any], block_index: int | None) -> None:
    if block_index is None:
        return
    seen = profile["seen_block_indices"]
    if not isinstance(seen, set):
        return
    seen.add(block_index)
    min_index = profile.get("min_block_index")
    max_index = profile.get("max_block_index")
    if min_index is None or block_index < min_index:
        profile["min_block_index"] = block_index
    if max_index is None or block_index > max_index:
        profile["max_block_index"] = block_index


def _update_blockization_profile_feature(
    profile: dict[str, Any],
    *,
    key: str,
    value: Any,
) -> None:
    if value is None:
        return
    target = profile.get(key)
    if not isinstance(target, set):
        return
    text = str(value).strip()
    if not text:
        return
    target.add(text)


def _update_blockization_profile_from_gold_payload(
    profile: dict[str, Any],
    payload: dict[str, Any],
    *,
    indices: list[int],
) -> None:
    for block_index in indices:
        _update_blockization_profile_index(profile, block_index)

    touched_blocks = payload.get("touched_blocks")
    if not isinstance(touched_blocks, list):
        return
    for touched in touched_blocks:
        if not isinstance(touched, dict):
            continue
        _update_blockization_profile_index(
            profile,
            _coerce_int(touched.get("block_index")),
        )
        location = touched.get("location")
        if not isinstance(location, dict):
            continue
        features = location.get("features")
        if not isinstance(features, dict):
            continue
        _update_blockization_profile_feature(
            profile,
            key="extraction_backends",
            value=features.get("extraction_backend"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_html_parser_versions",
            value=features.get("unstructured_html_parser_version"),
        )
        _update_blockization_profile_feature(
            profile,
            key="unstructured_preprocess_modes",
            value=features.get("unstructured_preprocess_mode"),
        )
        if "unstructured_skip_headers_footers" in features:
            _update_blockization_profile_feature(
                profile,
                key="unstructured_skip_headers_footers",
                value=features.get("unstructured_skip_headers_footers"),
            )


def _serialize_blockization_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "labeled_block_count": len(profile.get("seen_block_indices", set())),
        "min_labeled_block_index": profile.get("min_block_index"),
        "max_labeled_block_index": profile.get("max_block_index"),
        "extraction_backends": sorted(profile.get("extraction_backends", set())),
        "unstructured_html_parser_versions": sorted(
            profile.get("unstructured_html_parser_versions", set())
        ),
        "unstructured_preprocess_modes": sorted(
            profile.get("unstructured_preprocess_modes", set())
        ),
        "unstructured_skip_headers_footers": sorted(
            profile.get("unstructured_skip_headers_footers", set())
        ),
    }


def extract_block_indices(payload: dict[str, Any]) -> list[int]:
    values = payload.get("touched_block_indices")
    items: list[Any]
    if isinstance(values, list):
        items = values
    else:
        touched_blocks = payload.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            return []
        items = [
            item.get("block_index")
            for item in touched_blocks
            if isinstance(item, dict) and item.get("block_index") is not None
        ]

    indices: list[int] = []
    for value in items:
        try:
            indices.append(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def _extract_gold_matching_metadata(payload: dict[str, Any]) -> tuple[list[str], list[int]]:
    stable_keys: list[str] = []
    spine_indices: list[int] = []
    touched_blocks = payload.get("touched_blocks")
    if not isinstance(touched_blocks, list):
        return stable_keys, spine_indices

    for touched in touched_blocks:
        if not isinstance(touched, dict):
            continue
        location = touched.get("location")
        if not isinstance(location, dict):
            continue
        features = location.get("features")
        if not isinstance(features, dict):
            continue
        stable_key = str(features.get("unstructured_stable_key") or "").strip()
        if stable_key:
            stable_keys.append(stable_key)
        spine_value = _coerce_int(features.get("spine_index"))
        if spine_value is not None:
            spine_indices.append(spine_value)
    return stable_keys, spine_indices


def _normalize_block_gold_labels(raw_labels: Any, *, block_index: int) -> list[str]:
    items = raw_labels if isinstance(raw_labels, list) else [raw_labels]
    labels: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        normalized = normalize_freeform_label(value)
        if normalized not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Unsupported freeform label in block gold payload: {value!r}"
            )
        labels.add(normalized)
    if not labels:
        raise ValueError(f"Block gold row has no usable labels: block_index={block_index}")
    return sorted(labels)


def block_gold_rows_to_assignments(
    rows: list[dict[str, Any]],
) -> dict[int, set[str]]:
    assignments: dict[int, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        block_index = _coerce_int(row.get("block_index"))
        if block_index is None:
            continue
        assignments[block_index] = set(
            _normalize_block_gold_labels(row.get("labels"), block_index=block_index)
        )
    return {
        block_index: set(labels)
        for block_index, labels in sorted(assignments.items())
    }


def derive_block_gold_bundle(
    span_rows: list[dict[str, Any]],
    *,
    profile_output: dict[str, Any] | None = None,
    index_metadata_output: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    assignments: dict[int, set[str]] = {}
    assignment_spans: dict[int, list[dict[str, Any]]] = {}
    block_metadata: dict[int, dict[str, Any]] = {}
    profile = _new_blockization_profile()

    for row_number, payload in enumerate(span_rows, start=1):
        if not isinstance(payload, dict):
            continue
        label_value = payload.get("label")
        if not isinstance(label_value, str) or not label_value.strip():
            continue
        normalized_label = normalize_freeform_label(label_value)
        if normalized_label not in _FREEFORM_LABEL_SET:
            raise ValueError(
                f"Unsupported freeform label in gold payload: {label_value!r}"
            )

        indices = extract_block_indices(payload)
        if not indices:
            continue

        span_id = str(payload.get("span_id") or f"row:{row_number}")
        selected_text = str(payload.get("selected_text") or "").strip()
        stable_keys, spine_indices = _extract_gold_matching_metadata(payload)
        _update_blockization_profile_from_gold_payload(
            profile,
            payload,
            indices=indices,
        )

        source_hash = str(payload.get("source_hash") or "").strip()
        source_file = str(payload.get("source_file") or "").strip()
        segment_id = str(payload.get("segment_id") or "").strip()
        book_id = str(payload.get("book_id") or "").strip()
        annotator = payload.get("annotator")
        annotated_at = payload.get("annotated_at")
        annotation_id = payload.get("annotation_id")
        result_id = payload.get("result_id")

        for block_index in indices:
            assignments.setdefault(block_index, set()).add(normalized_label)
            assignment_spans.setdefault(block_index, []).append(
                {
                    "span_id": span_id,
                    "label": normalized_label,
                    "source_hash": source_hash,
                    "source_file": source_file,
                    "segment_id": segment_id,
                    "book_id": book_id,
                    "annotator": annotator,
                    "annotated_at": annotated_at,
                    "annotation_id": annotation_id,
                    "result_id": result_id,
                }
            )

            metadata = block_metadata.setdefault(
                block_index,
                {
                    "source_hashes": set(),
                    "source_files": set(),
                    "segment_ids": set(),
                    "book_ids": set(),
                    "stable_keys": set(),
                    "spine_indices": set(),
                    "selected_text_samples": [],
                },
            )
            if source_hash:
                metadata["source_hashes"].add(source_hash)
            if source_file:
                metadata["source_files"].add(source_file)
            if segment_id:
                metadata["segment_ids"].add(segment_id)
            if book_id:
                metadata["book_ids"].add(book_id)
            metadata["stable_keys"].update(
                str(value).strip() for value in stable_keys if str(value).strip()
            )
            metadata["spine_indices"].update(spine_indices)
            if selected_text and selected_text not in metadata["selected_text_samples"]:
                metadata["selected_text_samples"].append(selected_text)

            if index_metadata_output is not None:
                index_metadata_output.setdefault(block_index, []).append(
                    {
                        "span_id": span_id,
                        "selected_text": selected_text,
                        "stable_keys": list(stable_keys),
                        "spine_indices": list(spine_indices),
                    }
                )

    if assignments:
        assignments = resolve_howto_label_sets_by_index(assignments)

    conflicts: list[dict[str, Any]] = []
    block_gold_rows: list[dict[str, Any]] = []
    for block_index, labels in sorted(assignments.items()):
        spans = list(assignment_spans.get(block_index, []))
        if len(labels) > 1:
            conflicts.append(
                {
                    "warning": "gold_block_has_multiple_labels",
                    "block_index": block_index,
                    "labels": sorted(labels),
                    "spans": spans,
                }
            )
        metadata = block_metadata.get(block_index) or {}
        source_hashes = sorted(metadata.get("source_hashes", set()))
        source_files = sorted(metadata.get("source_files", set()))
        segment_ids = sorted(metadata.get("segment_ids", set()))
        book_ids = sorted(metadata.get("book_ids", set()))
        stable_keys = sorted(metadata.get("stable_keys", set()))
        spine_index_values = sorted(metadata.get("spine_indices", set()))
        block_gold_rows.append(
            {
                "block_index": block_index,
                "labels": sorted(labels),
                "source_hash": source_hashes[0] if len(source_hashes) == 1 else "",
                "source_file": source_files[0] if len(source_files) == 1 else "",
                "segment_ids": segment_ids,
                "book_ids": book_ids,
                "stable_keys": stable_keys,
                "spine_indices": spine_index_values,
            }
        )

    if profile_output is not None:
        profile_output.clear()
        profile_output.update(_serialize_blockization_profile(profile))

    return {
        "rows": block_gold_rows,
        "assignments": {
            block_index: set(labels)
            for block_index, labels in sorted(assignments.items())
        },
        "conflicts": conflicts,
        "profile": _serialize_blockization_profile(profile),
    }


def load_gold_block_label_assignments(
    freeform_span_labels_jsonl_path: Path,
    *,
    conflict_output_path: Path | None = None,
    require_exhaustive: bool = True,
    profile_output: dict[str, Any] | None = None,
    index_metadata_output: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[int, set[str]]:
    span_rows = _read_jsonl(freeform_span_labels_jsonl_path)
    bundle = derive_block_gold_bundle(
        span_rows,
        profile_output=profile_output,
        index_metadata_output=index_metadata_output,
    )
    if not bundle["assignments"]:
        raise ValueError(
            f"Gold file contains no usable block labels: {freeform_span_labels_jsonl_path}"
        )
    conflicts = list(bundle["conflicts"])
    if conflicts and conflict_output_path is not None:
        write_block_gold_rows(conflict_output_path, conflicts)

    assignments = {
        block_index: set(labels)
        for block_index, labels in bundle["assignments"].items()
    }
    max_index = max(assignments)
    missing = [index for index in range(max_index + 1) if index not in assignments]
    if require_exhaustive and missing:
        diagnostics = list(conflicts)
        diagnostics.append(
            {
                "error": "gold_missing_block_labels",
                "missing_block_indices": missing,
            }
        )
        if conflict_output_path is not None:
            write_block_gold_rows(conflict_output_path, diagnostics)
        raise ValueError(
            "Gold is not exhaustive: missing labels for "
            f"{len(missing)} blocks (examples: {missing[:10]})."
        )

    return assignments
