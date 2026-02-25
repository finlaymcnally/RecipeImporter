from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import ChunkLane, KnowledgeChunk, ParsingOverrides
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks

from .codex_farm_knowledge_contracts import (
    KnowledgeBlockV1,
    KnowledgeContextPayloadV1,
    KnowledgeGuardrailsPayloadV1,
    KnowledgeHeuristicsPayloadV1,
    KnowledgeJobSourceV1,
    KnowledgeChunkPayloadV1,
    KnowledgeTableHintV1,
    Pass4KnowledgeJobInputV1,
    SpanV1,
)
from .non_recipe_spans import Span


@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    jobs_written: int
    chunk_ids: list[str]
    chunk_lane_by_id: dict[str, str | None]
    recipe_spans: list[Span]


def build_pass4_knowledge_jobs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    non_recipe_blocks: Sequence[Mapping[str, Any]],
    workbook_slug: str,
    source_hash: str,
    out_dir: Path,
    context_blocks: int = 12,
    overrides: ParsingOverrides | None = None,
) -> KnowledgeJobBuildReport:
    """Write pass4 knowledge job bundles to out_dir and return a build report.

    Notes:
    - Uses deterministic chunking/highlights as hints only; no filtering by lane.
    - Chunk blocks come only from non-recipe blocks; context may overlap recipes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    if not full_blocks_by_index:
        raise ValueError("Cannot build pass4 knowledge jobs: empty full_blocks.")

    non_recipe_sorted = _sorted_blocks_by_index(non_recipe_blocks)
    non_recipe_indices = {int(block["index"]) for block in non_recipe_sorted}
    table_hints_by_index = _table_hints_by_index(non_recipe_sorted)

    recipe_spans = _recipe_spans_from_indices(
        recipe_indices=[
            idx for idx in sorted(full_blocks_by_index) if idx not in non_recipe_indices
        ]
    )
    recipe_spans_payload = [SpanV1(start=span.start, end=span.end) for span in recipe_spans]

    sequences = _split_contiguous_sequences(non_recipe_sorted)
    chunk_ids: list[str] = []
    chunk_lane_by_id: dict[str, str | None] = {}
    chunk_counter = 0

    for sequence in sequences:
        chunks = chunks_from_non_recipe_blocks(sequence, overrides=overrides)
        for chunk in chunks:
            chunk_id = f"{workbook_slug}.c{chunk_counter:04d}.nr"
            payload = _build_job_payload(
                chunk_id=chunk_id,
                workbook_slug=workbook_slug,
                source_hash=source_hash,
                chunk=chunk,
                sequence=sequence,
                full_blocks_by_index=full_blocks_by_index,
                table_hints_by_index=table_hints_by_index,
                recipe_spans_payload=recipe_spans_payload,
                context_blocks=context_blocks,
            )
            _write_json(payload.model_dump(mode="json", by_alias=True), out_dir / f"{chunk_id}.json")
            chunk_ids.append(chunk_id)
            chunk_lane_by_id[chunk_id] = (
                str(chunk.lane.value) if isinstance(chunk.lane, ChunkLane) else None
            )
            chunk_counter += 1

    return KnowledgeJobBuildReport(
        jobs_written=len(chunk_ids),
        chunk_ids=chunk_ids,
        chunk_lane_by_id=chunk_lane_by_id,
        recipe_spans=recipe_spans,
    )


def _prepare_full_blocks_by_index(
    blocks: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        by_index[index] = payload
    return by_index


def _sorted_blocks_by_index(blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _split_contiguous_sequences(blocks_sorted: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    sequences: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_index: int | None = None
    for block in blocks_sorted:
        index = int(block["index"])
        if previous_index is None or index == previous_index + 1:
            current.append(block)
        else:
            if current:
                sequences.append(current)
            current = [block]
        previous_index = index
    if current:
        sequences.append(current)
    return sequences


def _recipe_spans_from_indices(*, recipe_indices: Sequence[int]) -> list[Span]:
    if not recipe_indices:
        return []
    sorted_indices = sorted(set(int(idx) for idx in recipe_indices))
    spans: list[Span] = []
    start = sorted_indices[0]
    previous = start
    for idx in sorted_indices[1:]:
        if idx == previous + 1:
            previous = idx
            continue
        spans.append(Span(start, previous + 1))
        start = idx
        previous = idx
    spans.append(Span(start, previous + 1))
    return spans


def _build_job_payload(
    *,
    chunk_id: str,
    workbook_slug: str,
    source_hash: str,
    chunk: KnowledgeChunk,
    sequence: Sequence[dict[str, Any]],
    full_blocks_by_index: dict[int, dict[str, Any]],
    table_hints_by_index: Mapping[int, KnowledgeTableHintV1],
    recipe_spans_payload: list[SpanV1],
    context_blocks: int,
) -> Pass4KnowledgeJobInputV1:
    if not chunk.block_ids:
        raise ValueError(f"Chunk {chunk_id} has no block_ids; cannot build job bundle.")

    absolute_indices = _absolute_indices_for_chunk(chunk, sequence=sequence)
    block_start_index = absolute_indices[0]
    block_end_index = absolute_indices[-1] + 1

    blocks_payload = [
        _to_knowledge_block(
            full_blocks_by_index.get(idx) or {},
            fallback_index=idx,
            table_hint=table_hints_by_index.get(idx),
        )
        for idx in absolute_indices
    ]

    before_indices = range(max(0, block_start_index - context_blocks), block_start_index)
    after_indices = range(block_end_index, block_end_index + max(0, int(context_blocks)))
    blocks_before = [
        _to_knowledge_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
            table_hint=table_hints_by_index.get(idx),
        )
        for idx in before_indices
        if idx in full_blocks_by_index
    ]
    blocks_after = [
        _to_knowledge_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
            table_hint=table_hints_by_index.get(idx),
        )
        for idx in after_indices
        if idx in full_blocks_by_index
    ]

    suggested_lane: str | None
    if isinstance(chunk.lane, ChunkLane):
        suggested_lane = chunk.lane.value
    else:
        suggested_lane = str(chunk.lane) if chunk.lane is not None else None

    suggested_highlights = [
        str(highlight.text).strip()
        for highlight in (chunk.highlights or [])
        if str(highlight.text).strip()
    ][:12]

    suggested_skip_reason: str | None = None
    if suggested_lane in {ChunkLane.NOISE.value, ChunkLane.NARRATIVE.value}:
        suggested_skip_reason = f"lane={suggested_lane}"

    return Pass4KnowledgeJobInputV1(
        source=KnowledgeJobSourceV1(workbook_slug=workbook_slug, source_hash=source_hash),
        chunk=KnowledgeChunkPayloadV1(
            chunk_id=chunk_id,
            block_start_index=int(block_start_index),
            block_end_index=int(block_end_index),
            blocks=blocks_payload,
        ),
        context=KnowledgeContextPayloadV1(
            blocks_before=blocks_before,
            blocks_after=blocks_after,
        ),
        heuristics=KnowledgeHeuristicsPayloadV1(
            suggested_lane=suggested_lane,
            suggested_highlights=suggested_highlights,
            suggested_skip_reason=suggested_skip_reason,
        ),
        guardrails=KnowledgeGuardrailsPayloadV1(
            recipe_spans=recipe_spans_payload,
            must_use_evidence=True,
        ),
    )


def _absolute_indices_for_chunk(
    chunk: KnowledgeChunk,
    *,
    sequence: Sequence[dict[str, Any]],
) -> list[int]:
    indices: list[int] = []
    for relative_id in chunk.block_ids:
        try:
            relative_index = int(relative_id)
        except (TypeError, ValueError):
            continue
        if relative_index < 0 or relative_index >= len(sequence):
            continue
        absolute = _coerce_int(sequence[relative_index].get("index"))
        if absolute is None:
            continue
        indices.append(absolute)
    if not indices:
        raise ValueError("Chunk had no valid absolute indices after mapping block_ids.")
    indices.sort()
    return indices


def _to_knowledge_block(
    block: Mapping[str, Any],
    *,
    fallback_index: int,
    table_hint: KnowledgeTableHintV1 | None = None,
) -> KnowledgeBlockV1:
    features = block.get("features")
    if not isinstance(features, Mapping):
        features = {}
    index = _coerce_int(block.get("index"))
    if index is None:
        index = int(fallback_index)
    block_id = block.get("block_id") or block.get("id")
    if not isinstance(block_id, str) or not block_id.strip():
        block_id = f"b{index}"
    page = _coerce_int(block.get("page"))
    spine_index = _coerce_int(block.get("spine_index"))
    if spine_index is None:
        spine_index = _coerce_int(features.get("spine_index"))
    heading_level = _coerce_int(block.get("heading_level"))
    if heading_level is None:
        heading_level = _coerce_int(features.get("heading_level"))
    return KnowledgeBlockV1(
        block_index=index,
        block_id=str(block_id).strip(),
        text=str(block.get("text") or ""),
        page=page,
        spine_index=spine_index,
        heading_level=heading_level,
        features_subset=_features_subset(features),
        table_hint=table_hint,
    )


def _features_subset(features: Mapping[str, Any]) -> dict[str, Any]:
    subset: dict[str, Any] = {}
    for key in ("is_header_likely", "block_role", "table_id", "table_row_index"):
        value = features.get(key)
        if isinstance(value, (str, int, float, bool)):
            subset[key] = value
    return subset


def _table_hints_by_index(
    non_recipe_blocks_sorted: Sequence[Mapping[str, Any]],
) -> dict[int, KnowledgeTableHintV1]:
    table_hints: dict[int, KnowledgeTableHintV1] = {}
    for block in non_recipe_blocks_sorted:
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        table_hint = _normalize_table_hint(block)
        if table_hint is None:
            continue
        table_hints[index] = table_hint
    return table_hints


def _normalize_table_hint(block: Mapping[str, Any]) -> KnowledgeTableHintV1 | None:
    raw_hint = block.get("table_hint")
    if isinstance(raw_hint, Mapping):
        table_id = str(raw_hint.get("table_id") or "").strip()
        if not table_id:
            return None
        caption = str(raw_hint.get("caption") or "").strip() or None
        markdown = str(raw_hint.get("markdown") or "").strip() or None
        row_index = _coerce_int(raw_hint.get("row_index_in_table"))
        return KnowledgeTableHintV1(
            table_id=table_id,
            caption=caption,
            markdown=markdown,
            row_index_in_table=row_index,
        )

    features = block.get("features")
    if not isinstance(features, Mapping):
        features = {}
    table_id = str(
        block.get("table_id")
        or features.get("table_id")
        or ""
    ).strip()
    if not table_id:
        return None
    caption = str(features.get("table_caption") or "").strip() or None
    row_index = _coerce_int(
        block.get("table_row_index")
        if block.get("table_row_index") is not None
        else features.get("table_row_index")
    )
    return KnowledgeTableHintV1(
        table_id=table_id,
        caption=caption,
        markdown=None,
        row_index_in_table=row_index,
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
