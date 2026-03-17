from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import ChunkLane, KnowledgeChunk, ParsingOverrides
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import (
    NonRecipeSpan,
    block_rows_for_nonrecipe_span,
)

from .codex_farm_knowledge_contracts import (
    KnowledgeCompactChunkBlockV1,
    KnowledgeCompactChunkPayloadV1,
    KnowledgeCompactContextBlockV1,
    KnowledgeCompactContextPayloadV1,
    KnowledgeCompactGuardrailsPayloadV1,
    KnowledgeCompactTableHintV1,
    KnowledgeHeuristicsPayloadV1,
    KnowledgeJobSourceV1,
    KnowledgeCompactJobInputV1,
    KnowledgeTableHintV1,
    SpanV1,
)


@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    jobs_written: int
    chunk_ids: list[str]
    chunk_lane_by_id: dict[str, str | None]
    skipped_chunk_count: int
    skipped_lane_counts: dict[str, int]


def build_knowledge_jobs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    candidate_spans: Sequence[NonRecipeSpan],
    recipe_spans: Sequence[RecipeSpan],
    workbook_slug: str,
    source_hash: str,
    out_dir: Path,
    context_blocks: int = 2,
    overrides: ParsingOverrides | None = None,
    skip_suggested_lanes: Sequence[str] = ("noise",),
) -> KnowledgeJobBuildReport:
    """Write knowledge-stage job bundles to out_dir and return a build report.

    Notes:
    - Uses deterministic chunking/highlights as hints over seed Stage 7 non-recipe spans.
    - Chunk blocks come only from seed non-recipe spans; context may overlap recipes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    if not full_blocks_by_index:
        raise ValueError("Cannot build knowledge jobs: empty full_blocks.")

    recipe_spans_payload = [
        SpanV1(
            start=int(span.start_block_index),
            end=int(span.end_block_index),
        )
        for span in recipe_spans
    ]
    chunk_ids: list[str] = []
    chunk_lane_by_id: dict[str, str | None] = {}
    chunk_counter = 0
    normalized_skip_lanes = {
        str(value or "").strip().lower()
        for value in skip_suggested_lanes
        if str(value or "").strip()
    }
    skipped_chunk_count = 0
    skipped_lane_counts: dict[str, int] = {}

    for stage_span in candidate_spans:
        sequence = block_rows_for_nonrecipe_span(
            full_blocks=full_blocks,
            span=stage_span,
        )
        if not sequence:
            continue
        table_hints_by_index = _table_hints_by_index(sequence)
        chunks = chunks_from_non_recipe_blocks(sequence, overrides=overrides)
        for chunk in chunks:
            chunk_id = f"{workbook_slug}.c{chunk_counter:04d}.nr"
            suggested_lane: str | None
            if isinstance(chunk.lane, ChunkLane):
                suggested_lane = chunk.lane.value
            else:
                suggested_lane = str(chunk.lane) if chunk.lane is not None else None
            normalized_lane = str(suggested_lane or "").strip().lower()
            if normalized_lane and normalized_lane in normalized_skip_lanes:
                skipped_chunk_count += 1
                skipped_lane_counts[normalized_lane] = (
                    int(skipped_lane_counts.get(normalized_lane) or 0) + 1
                )
                chunk_counter += 1
                continue
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
            _write_json(
                payload.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_defaults=True,
                    exclude_none=True,
                ),
                out_dir / f"{chunk_id}.json",
            )
            chunk_ids.append(chunk_id)
            chunk_lane_by_id[chunk_id] = (
                str(chunk.lane.value) if isinstance(chunk.lane, ChunkLane) else suggested_lane
            )
            chunk_counter += 1

    return KnowledgeJobBuildReport(
        jobs_written=len(chunk_ids),
        chunk_ids=chunk_ids,
        chunk_lane_by_id=chunk_lane_by_id,
        skipped_chunk_count=skipped_chunk_count,
        skipped_lane_counts=skipped_lane_counts,
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
) -> KnowledgeCompactJobInputV1:
    if not chunk.block_ids:
        raise ValueError(f"Chunk {chunk_id} has no block_ids; cannot build job bundle.")

    absolute_indices = _absolute_indices_for_chunk(chunk, sequence=sequence)
    block_start_index = absolute_indices[0]
    block_end_index = absolute_indices[-1] + 1

    before_indices = range(max(0, block_start_index - context_blocks), block_start_index)
    after_indices = range(block_end_index, block_end_index + max(0, int(context_blocks)))
    context_recipe_block_indices = sorted(
        idx
        for idx in [*before_indices, *after_indices]
        if _index_in_recipe_spans(idx, recipe_spans_payload)
    )

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

    chunk_blocks_payload = [
        _to_knowledge_compact_chunk_block(
            full_blocks_by_index.get(idx) or {},
            fallback_index=idx,
            table_hint=table_hints_by_index.get(idx),
        )
        for idx in absolute_indices
    ]
    blocks_before = [
        _to_knowledge_compact_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in before_indices
        if idx in full_blocks_by_index
    ]
    blocks_after = [
        _to_knowledge_compact_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in after_indices
        if idx in full_blocks_by_index
    ]
    return KnowledgeCompactJobInputV1(
        source=KnowledgeJobSourceV1(workbook_slug=workbook_slug, source_hash=source_hash),
        chunk=KnowledgeCompactChunkPayloadV1(
            chunk_id=chunk_id,
            block_start_index=int(block_start_index),
            block_end_index=int(block_end_index),
            blocks=chunk_blocks_payload,
        ),
        context=KnowledgeCompactContextPayloadV1(
            blocks_before=blocks_before,
            blocks_after=blocks_after,
        ),
        heuristics=KnowledgeHeuristicsPayloadV1(
            suggested_lane=suggested_lane,
            suggested_highlights=suggested_highlights[:6],
            suggested_skip_reason=suggested_skip_reason,
        ),
        guardrails=KnowledgeCompactGuardrailsPayloadV1(
            context_recipe_block_indices=context_recipe_block_indices,
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


def _index_in_recipe_spans(index: int, recipe_spans_payload: Sequence[SpanV1]) -> bool:
    return any(int(span.start) <= index < int(span.end) for span in recipe_spans_payload)


def _to_knowledge_compact_chunk_block(
    block: Mapping[str, Any],
    *,
    fallback_index: int,
    table_hint: KnowledgeTableHintV1 | None = None,
) -> KnowledgeCompactChunkBlockV1:
    index = _coerce_int(block.get("index"))
    if index is None:
        index = int(fallback_index)
    compact_table_hint: KnowledgeCompactTableHintV1 | None = None
    if table_hint is not None:
        compact_table_hint = KnowledgeCompactTableHintV1(
            table_id=table_hint.table_id,
            caption=table_hint.caption,
            row_index_in_table=table_hint.row_index_in_table,
        )
    return KnowledgeCompactChunkBlockV1(
        block_index=index,
        text=str(block.get("text") or ""),
        heading_level=_resolve_heading_level(block),
        table_hint=compact_table_hint,
    )


def _to_knowledge_compact_context_block(
    block: Mapping[str, Any],
    *,
    fallback_index: int,
) -> KnowledgeCompactContextBlockV1:
    index = _coerce_int(block.get("index"))
    if index is None:
        index = int(fallback_index)
    return KnowledgeCompactContextBlockV1(
        block_index=index,
        text=str(block.get("text") or ""),
        heading_level=_resolve_heading_level(block),
    )


def _resolve_heading_level(block: Mapping[str, Any]) -> int | None:
    features = block.get("features")
    if not isinstance(features, Mapping):
        features = {}
    heading_level = _coerce_int(block.get("heading_level"))
    if heading_level is None:
        heading_level = _coerce_int(features.get("heading_level"))
    return heading_level


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
