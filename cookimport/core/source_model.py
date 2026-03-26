from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import ConversionResult, SourceBlock, SourceSupport

_RAW_OUTPUT_CATEGORY = "rawArtifacts"
_BLOCK_ID_RE = re.compile(r"^(?:b|block:)(\d+)$")
_SOURCE_BLOCK_KNOWN_KEYS = {
    "block_id",
    "blockId",
    "order_index",
    "orderIndex",
    "index",
    "text",
    "source_text",
    "sourceText",
    "location",
    "features",
    "provenance",
}
_LOCATION_KEYS = {
    "page",
    "pages",
    "line_index",
    "row_index",
    "sheet",
    "spine_index",
    "spine_item",
    "start_line",
    "end_line",
    "bbox",
    "path",
    "html_path",
    "table_id",
    "table_row_index",
}


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _default_block_id(order_index: int) -> str:
    return f"b{int(order_index)}"


def _coerce_source_block(item: SourceBlock | Mapping[str, Any], fallback_index: int) -> SourceBlock:
    if isinstance(item, SourceBlock):
        payload = item.model_dump(mode="python")
    else:
        payload = dict(item)
    order_index = _coerce_int(
        payload.get("order_index", payload.get("orderIndex", payload.get("index", fallback_index)))
    )
    if order_index is None:
        order_index = fallback_index
    block_id = str(payload.get("block_id") or payload.get("blockId") or "").strip() or _default_block_id(
        order_index
    )
    source_text = payload.get("source_text", payload.get("sourceText"))
    text = payload.get("text")
    if text is None:
        text = source_text or ""
    location = payload.get("location")
    if not isinstance(location, dict):
        location = {
            key: payload[key]
            for key in sorted(_LOCATION_KEYS)
            if key in payload and payload[key] is not None
        }
    features = payload.get("features")
    if not isinstance(features, dict):
        features = {
            key: value
            for key, value in payload.items()
            if key not in _SOURCE_BLOCK_KNOWN_KEYS and value is not None
        }
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return SourceBlock.model_validate(
        {
            "block_id": block_id,
            "order_index": order_index,
            "text": text,
            "source_text": source_text,
            "location": location,
            "features": features,
            "provenance": provenance,
        }
    )


def normalize_source_blocks(
    blocks: Sequence[SourceBlock | Mapping[str, Any]],
) -> list[SourceBlock]:
    normalized: list[SourceBlock] = []
    for fallback_index, item in enumerate(blocks):
        block = _coerce_source_block(item, fallback_index)
        if not str(block.text or "").strip():
            continue
        normalized.append(block)
    normalized.sort(key=lambda item: (int(item.order_index), str(item.block_id)))
    return normalized


def normalize_source_support(
    items: Sequence[SourceSupport | Mapping[str, Any]],
) -> list[SourceSupport]:
    normalized: list[SourceSupport] = []
    for item in items:
        if isinstance(item, SourceSupport):
            support = item
        else:
            support = SourceSupport.model_validate(dict(item))
        metadata = dict(support.metadata)
        metadata["authoritative"] = False
        normalized.append(support.model_copy(update={"metadata": metadata}))
    return normalized


def source_blocks_to_rows(
    blocks: Sequence[SourceBlock | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in normalize_source_blocks(blocks):
        row: dict[str, Any] = {
            "index": int(block.order_index),
            "block_id": str(block.block_id),
            "text": str(block.text),
            "location": dict(block.location),
            "features": dict(block.features),
            "provenance": dict(block.provenance),
        }
        if block.source_text is not None and block.source_text != block.text:
            row["source_text"] = str(block.source_text)
        for source in (block.location, block.features):
            for key, value in source.items():
                if key not in row:
                    row[key] = value
        rows.append(row)
    rows.sort(key=lambda item: int(item.get("index", 0)))
    return rows


def source_support_to_payload(
    items: Sequence[SourceSupport | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        support.model_dump(mode="json", by_alias=True)
        for support in normalize_source_support(items)
    ]


def resolve_conversion_source_model(
    result: ConversionResult,
    *,
    full_blocks: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[SourceBlock], list[SourceSupport]]:
    if result.source_blocks:
        return (
            normalize_source_blocks(result.source_blocks),
            normalize_source_support(result.source_support),
        )
    if full_blocks:
        return (normalize_source_blocks(full_blocks), normalize_source_support(result.source_support))
    raise ValueError("Stage input is missing canonical source blocks.")


def write_source_model_artifacts(
    run_root: Path,
    workbook_slug: str,
    blocks: Sequence[SourceBlock | Mapping[str, Any]],
    support: Sequence[SourceSupport | Mapping[str, Any]],
    *,
    output_stats: Any | None = None,
) -> dict[str, Path]:
    source_dir = run_root / "raw" / "source" / workbook_slug
    source_dir.mkdir(parents=True, exist_ok=True)
    source_blocks_path = source_dir / "source_blocks.jsonl"
    source_support_path = source_dir / "source_support.json"
    block_rows = [
        block.model_dump(mode="json", by_alias=True)
        for block in normalize_source_blocks(blocks)
    ]
    support_rows = source_support_to_payload(support)
    if block_rows:
        source_blocks_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in block_rows) + "\n",
            encoding="utf-8",
        )
    else:
        source_blocks_path.write_text("", encoding="utf-8")
    source_support_path.write_text(
        json.dumps(support_rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if output_stats is not None:
        output_stats.record_path(_RAW_OUTPUT_CATEGORY, source_blocks_path)
        output_stats.record_path(_RAW_OUTPUT_CATEGORY, source_support_path)
    return {
        "source_blocks_path": source_blocks_path,
        "source_support_path": source_support_path,
    }


def offset_source_blocks(
    blocks: Sequence[SourceBlock | Mapping[str, Any]],
    offset: int,
) -> list[SourceBlock]:
    if offset <= 0:
        return normalize_source_blocks(blocks)
    updated: list[SourceBlock] = []
    for block in normalize_source_blocks(blocks):
        order_index = int(block.order_index) + offset
        updated.append(
            block.model_copy(
                update={
                    "order_index": order_index,
                    "block_id": _default_block_id(order_index),
                }
            )
        )
    return updated


def offset_source_support(
    items: Sequence[SourceSupport | Mapping[str, Any]],
    offset: int,
) -> list[SourceSupport]:
    if offset <= 0:
        return normalize_source_support(items)
    updated: list[SourceSupport] = []
    for support in normalize_source_support(items):
        referenced_block_ids: list[str] = []
        for block_id in support.referenced_block_ids:
            match = _BLOCK_ID_RE.match(str(block_id).strip())
            if not match:
                referenced_block_ids.append(str(block_id))
                continue
            referenced_block_ids.append(_default_block_id(int(match.group(1)) + offset))
        updated.append(
            support.model_copy(update={"referenced_block_ids": referenced_block_ids})
        )
    return updated
