from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label

_BLOCK_SEPARATOR = "\n\n"
_CANONICAL_SCHEMA_VERSION = "canonical_gold.v1"


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _extract_segment_rows(
    export_payload: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    segment_rows: dict[str, dict[str, Any]] = {}
    for task in export_payload:
        if not isinstance(task, dict):
            continue
        data = task.get("data")
        if not isinstance(data, dict):
            continue
        segment_id = str(data.get("segment_id") or "").strip()
        if not segment_id:
            continue
        segment_text = str(data.get("segment_text") or "")
        source_hash = str(data.get("source_hash") or "")
        source_file = str(data.get("source_file") or "")
        source_map = data.get("source_map")
        if not isinstance(source_map, dict):
            source_map = {}
        blocks = source_map.get("blocks")
        if not isinstance(blocks, list):
            blocks = []
        segment_rows[segment_id] = {
            "segment_id": segment_id,
            "segment_text": segment_text,
            "source_hash": source_hash,
            "source_file": source_file,
            "blocks": [row for row in blocks if isinstance(row, dict)],
        }
    return segment_rows


def _pick_block_text(counter: Counter[str]) -> str:
    if not counter:
        return ""
    best_text = ""
    best_count = -1
    for text, count in counter.items():
        if count > best_count:
            best_text = text
            best_count = count
            continue
        if count == best_count and len(text) > len(best_text):
            best_text = text
    return best_text


def _build_canonical_blocks(
    *,
    segment_rows: dict[str, dict[str, Any]],
    block_separator: str,
) -> tuple[str, list[dict[str, Any]], dict[int, dict[str, Any]], list[str]]:
    block_text_candidates: dict[int, Counter[str]] = defaultdict(Counter)

    for segment in segment_rows.values():
        segment_text = str(segment.get("segment_text") or "")
        blocks = segment.get("blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_index = _coerce_int(block.get("block_index"))
            if block_index is None:
                continue
            segment_start = _coerce_int(block.get("segment_start"))
            segment_end = _coerce_int(block.get("segment_end"))
            if segment_start is None or segment_end is None:
                continue
            if segment_start < 0 or segment_end <= segment_start:
                continue
            if segment_end > len(segment_text):
                continue
            block_text = segment_text[segment_start:segment_end]
            block_text_candidates[block_index][block_text] += 1

    warnings: list[str] = []
    sorted_indices = sorted(block_text_candidates.keys())
    canonical_parts: list[str] = []
    block_rows: list[dict[str, Any]] = []
    block_lookup: dict[int, dict[str, Any]] = {}
    cursor = 0

    for position, block_index in enumerate(sorted_indices):
        counter = block_text_candidates.get(block_index, Counter())
        block_text = _pick_block_text(counter)
        if len(counter) > 1:
            warnings.append(
                f"block_index={block_index} had {len(counter)} text variants; used majority text."
            )
        start_char = cursor
        end_char = start_char + len(block_text)
        text_hash = hashlib.sha256(block_text.encode("utf-8")).hexdigest()
        row = {
            "block_index": block_index,
            "start_char": start_char,
            "end_char": end_char,
            "text_len": len(block_text),
            "text_sha256": text_hash,
        }
        block_rows.append(row)
        block_lookup[block_index] = {
            "start_char": start_char,
            "end_char": end_char,
            "text": block_text,
            "text_sha256": text_hash,
        }
        canonical_parts.append(block_text)
        if position < len(sorted_indices) - 1:
            canonical_parts.append(block_separator)
            cursor = end_char + len(block_separator)
        else:
            cursor = end_char

    canonical_text = "".join(canonical_parts)
    return canonical_text, block_rows, block_lookup, warnings


def _build_canonical_span_id(
    *,
    source_hash: str,
    origin_span_id: str,
    label: str,
    start_char: int,
    end_char: int,
    part_index: int,
) -> str:
    payload = (
        f"{source_hash}|{origin_span_id}|{label}|{start_char}|{end_char}|{part_index}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"urn:cookimport:canonical_span:{source_hash}:{digest}"


def _build_canonical_spans(
    *,
    span_rows: list[dict[str, Any]],
    segment_rows: dict[str, dict[str, Any]],
    block_lookup: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    output_rows: list[dict[str, Any]] = []
    seen_rows: set[tuple[str, int, int, str, str]] = set()

    for span in span_rows:
        segment_id = str(span.get("segment_id") or "")
        source_hash = str(span.get("source_hash") or "")
        source_file = str(span.get("source_file") or "")
        origin_span_id = str(span.get("span_id") or "")
        label = normalize_freeform_label(str(span.get("label") or ""))
        start_offset = _coerce_int(span.get("start_offset"))
        end_offset = _coerce_int(span.get("end_offset"))
        if start_offset is None or end_offset is None:
            continue
        if end_offset <= start_offset:
            continue

        segment = segment_rows.get(segment_id)
        segment_text = str(segment.get("segment_text") or "") if segment else ""

        touched_blocks = span.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            touched_blocks = []
        part_index = 0
        for block in touched_blocks:
            if not isinstance(block, dict):
                continue
            block_index = _coerce_int(block.get("block_index"))
            segment_start = _coerce_int(block.get("segment_start"))
            segment_end = _coerce_int(block.get("segment_end"))
            if (
                block_index is None
                or segment_start is None
                or segment_end is None
                or segment_end <= segment_start
            ):
                continue
            overlap_start = max(start_offset, segment_start)
            overlap_end = min(end_offset, segment_end)
            if overlap_end <= overlap_start:
                continue
            canonical_block = block_lookup.get(block_index)
            if canonical_block is None:
                warnings.append(
                    "missing_canonical_block_for_span_part:"
                    f" span_id={origin_span_id} block_index={block_index}"
                )
                continue
            local_start = overlap_start - segment_start
            local_end = overlap_end - segment_start
            canonical_start = int(canonical_block["start_char"]) + local_start
            canonical_end = int(canonical_block["start_char"]) + local_end
            if canonical_end <= canonical_start:
                continue
            selected_text = ""
            if (
                segment_text
                and overlap_start >= 0
                and overlap_end <= len(segment_text)
            ):
                selected_text = segment_text[overlap_start:overlap_end]
            if not selected_text:
                selected_text = str(span.get("selected_text") or "")

            dedupe_key = (
                label,
                canonical_start,
                canonical_end,
                source_hash,
                source_file,
            )
            if dedupe_key in seen_rows:
                continue
            seen_rows.add(dedupe_key)
            output_rows.append(
                {
                    "span_id": _build_canonical_span_id(
                        source_hash=source_hash or "unknown",
                        origin_span_id=origin_span_id or "unknown",
                        label=label,
                        start_char=canonical_start,
                        end_char=canonical_end,
                        part_index=part_index,
                    ),
                    "origin_span_id": origin_span_id,
                    "segment_id": segment_id,
                    "source_hash": source_hash,
                    "source_file": source_file,
                    "book_id": str(span.get("book_id") or ""),
                    "label": label,
                    "start_char": canonical_start,
                    "end_char": canonical_end,
                    "selected_text": selected_text,
                    "block_index": block_index,
                    "annotator": span.get("annotator"),
                    "annotated_at": span.get("annotated_at"),
                    "annotation_id": span.get("annotation_id"),
                    "result_id": span.get("result_id"),
                }
            )
            part_index += 1
    output_rows.sort(
        key=lambda row: (
            str(row.get("source_hash") or ""),
            _coerce_int(row.get("start_char")) or 0,
            _coerce_int(row.get("end_char")) or 0,
            str(row.get("label") or ""),
            str(row.get("span_id") or ""),
        )
    )
    return output_rows, warnings


def _validate_canonical_spans(
    *,
    canonical_text: str,
    canonical_span_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for row in canonical_span_rows:
        start_char = _coerce_int(row.get("start_char"))
        end_char = _coerce_int(row.get("end_char"))
        if start_char is None or end_char is None:
            continue
        if start_char < 0 or end_char <= start_char or end_char > len(canonical_text):
            errors.append(
                {
                    "error": "canonical_span_out_of_bounds",
                    "span_id": row.get("span_id"),
                    "start_char": start_char,
                    "end_char": end_char,
                    "canonical_char_count": len(canonical_text),
                }
            )
            continue
        expected = str(row.get("selected_text") or "")
        actual = canonical_text[start_char:end_char]
        if expected != actual:
            errors.append(
                {
                    "error": "canonical_span_text_mismatch",
                    "span_id": row.get("span_id"),
                    "start_char": start_char,
                    "end_char": end_char,
                    "expected_text": expected,
                    "actual_text": actual,
                }
            )
    return errors


def _build_manifest(
    *,
    span_rows: list[dict[str, Any]],
    canonical_text: str,
    canonical_block_rows: list[dict[str, Any]],
    canonical_span_rows: list[dict[str, Any]],
    block_separator: str,
    warnings: list[str],
    span_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    source_hashes = {
        str(row.get("source_hash") or "").strip()
        for row in span_rows
        if str(row.get("source_hash") or "").strip()
    }
    source_files = {
        str(row.get("source_file") or "").strip()
        for row in span_rows
        if str(row.get("source_file") or "").strip()
    }
    return {
        "schema_version": _CANONICAL_SCHEMA_VERSION,
        "source_hash": sorted(source_hashes)[0] if len(source_hashes) == 1 else "",
        "source_file": sorted(source_files)[0] if len(source_files) == 1 else "",
        "block_separator": block_separator,
        "block_count": len(canonical_block_rows),
        "canonical_char_count": len(canonical_text),
        "canonical_span_count": len(canonical_span_rows),
        "canonical_span_error_count": len(span_errors),
        "warnings": sorted(set(warnings)),
    }


def build_canonical_gold_bundle(
    *,
    export_payload: list[dict[str, Any]],
    span_rows: list[dict[str, Any]],
    block_separator: str = _BLOCK_SEPARATOR,
) -> dict[str, Any]:
    segment_rows = _extract_segment_rows(export_payload)
    canonical_text, canonical_block_rows, block_lookup, block_warnings = (
        _build_canonical_blocks(
            segment_rows=segment_rows,
            block_separator=block_separator,
        )
    )
    canonical_span_rows, span_warnings = _build_canonical_spans(
        span_rows=span_rows,
        segment_rows=segment_rows,
        block_lookup=block_lookup,
    )
    canonical_span_errors = _validate_canonical_spans(
        canonical_text=canonical_text,
        canonical_span_rows=canonical_span_rows,
    )
    warnings = list(block_warnings) + list(span_warnings)
    manifest = _build_manifest(
        span_rows=span_rows,
        canonical_text=canonical_text,
        canonical_block_rows=canonical_block_rows,
        canonical_span_rows=canonical_span_rows,
        block_separator=block_separator,
        warnings=warnings,
        span_errors=canonical_span_errors,
    )
    return {
        "canonical_text": canonical_text,
        "canonical_block_map_rows": canonical_block_rows,
        "canonical_span_rows": canonical_span_rows,
        "canonical_span_errors": canonical_span_errors,
        "canonical_manifest": manifest,
    }


def write_canonical_gold_bundle(
    *,
    export_root: Path,
    bundle: dict[str, Any],
) -> dict[str, Path]:
    export_root.mkdir(parents=True, exist_ok=True)
    canonical_text_path = export_root / "canonical_text.txt"
    canonical_block_map_path = export_root / "canonical_block_map.jsonl"
    canonical_span_labels_path = export_root / "canonical_span_labels.jsonl"
    canonical_span_errors_path = export_root / "canonical_span_label_errors.jsonl"
    canonical_manifest_path = export_root / "canonical_manifest.json"

    canonical_text = str(bundle.get("canonical_text") or "")
    canonical_text_path.write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        canonical_block_map_path,
        [
            row
            for row in bundle.get("canonical_block_map_rows", [])
            if isinstance(row, dict)
        ],
    )
    _write_jsonl(
        canonical_span_labels_path,
        [row for row in bundle.get("canonical_span_rows", []) if isinstance(row, dict)],
    )
    _write_jsonl(
        canonical_span_errors_path,
        [
            row
            for row in bundle.get("canonical_span_errors", [])
            if isinstance(row, dict)
        ],
    )

    canonical_manifest = dict(bundle.get("canonical_manifest") or {})
    canonical_manifest["output"] = {
        "canonical_text": str(canonical_text_path),
        "canonical_block_map": str(canonical_block_map_path),
        "canonical_span_labels": str(canonical_span_labels_path),
        "canonical_span_label_errors": str(canonical_span_errors_path),
    }
    canonical_manifest_path.write_text(
        json.dumps(canonical_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "canonical_text_path": canonical_text_path,
        "canonical_block_map_path": canonical_block_map_path,
        "canonical_span_labels_path": canonical_span_labels_path,
        "canonical_span_errors_path": canonical_span_errors_path,
        "canonical_manifest_path": canonical_manifest_path,
    }


def ensure_canonical_gold_artifacts(
    *,
    export_root: Path,
) -> dict[str, Path]:
    canonical_text_path = export_root / "canonical_text.txt"
    canonical_block_map_path = export_root / "canonical_block_map.jsonl"
    canonical_span_labels_path = export_root / "canonical_span_labels.jsonl"
    canonical_span_errors_path = export_root / "canonical_span_label_errors.jsonl"
    canonical_manifest_path = export_root / "canonical_manifest.json"

    if (
        canonical_text_path.exists()
        and canonical_block_map_path.exists()
        and canonical_span_labels_path.exists()
        and canonical_manifest_path.exists()
    ):
        return {
            "canonical_text_path": canonical_text_path,
            "canonical_block_map_path": canonical_block_map_path,
            "canonical_span_labels_path": canonical_span_labels_path,
            "canonical_span_errors_path": canonical_span_errors_path,
            "canonical_manifest_path": canonical_manifest_path,
        }

    export_payload_path = export_root / "labelstudio_export.json"
    if not export_payload_path.exists() or not export_payload_path.is_file():
        raise FileNotFoundError(
            "Missing Label Studio export payload required for canonical gold build: "
            f"{export_payload_path}"
        )
    freeform_span_path = export_root / "freeform_span_labels.jsonl"
    if not freeform_span_path.exists() or not freeform_span_path.is_file():
        raise FileNotFoundError(
            "Missing freeform span labels required for canonical gold build: "
            f"{freeform_span_path}"
        )

    payload_raw = json.loads(export_payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload_raw, list):
        raise ValueError(
            "Label Studio export payload must be a JSON list: "
            f"{export_payload_path}"
        )
    export_payload = [row for row in payload_raw if isinstance(row, dict)]
    span_rows = _read_jsonl(freeform_span_path)

    bundle = build_canonical_gold_bundle(
        export_payload=export_payload,
        span_rows=span_rows,
    )
    return write_canonical_gold_bundle(export_root=export_root, bundle=bundle)
