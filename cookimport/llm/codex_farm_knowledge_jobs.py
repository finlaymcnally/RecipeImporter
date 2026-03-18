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
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.llm.shard_prompt_targets import resolve_items_per_shard

from .codex_farm_knowledge_contracts import (
    KnowledgeCompactBundleChunkPayloadV2,
    KnowledgeCompactBundleJobInputV2,
    KnowledgeCompactChunkBlockV1,
    KnowledgeCompactContextBlockV1,
    KnowledgeCompactContextPayloadV1,
    KnowledgeCompactGuardrailsPayloadV1,
    KnowledgeChunkReviewHintsV1,
    KnowledgeCompactTableHintV1,
    KnowledgeHeuristicsPayloadV1,
    KnowledgeJobSourceV1,
    KnowledgeSourceSpanV1,
    KnowledgeTableHintV1,
    SpanV1,
)

_DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHUNKS = 12
_DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHARS = 14000
_DEFAULT_KNOWLEDGE_BUNDLE_MAX_GAP_BLOCKS = 10
_DEFAULT_KNOWLEDGE_LOW_SIGNAL_MAX_CHARS = 240
_LOW_SIGNAL_SKIP_KEY = "low_signal"


@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    shards_written: int
    chunks_written: int
    chunk_ids: list[str]
    chunk_lane_by_id: dict[str, str | None]
    skipped_chunk_count: int
    skipped_lane_counts: dict[str, int]
    shard_entries: list[ShardManifestEntryV1]

    @property
    def jobs_written(self) -> int:
        return self.shards_written


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeBundleChunk:
    payload: KnowledgeCompactBundleChunkPayloadV2
    absolute_indices: list[int]
    char_count: int
    has_table_content: bool
    source_span_id: str


def build_knowledge_jobs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    candidate_spans: Sequence[NonRecipeSpan],
    recipe_spans: Sequence[RecipeSpan],
    workbook_slug: str,
    source_hash: str,
    out_dir: Path,
    context_blocks: int = 2,
    target_prompt_count: int | None = None,
    target_chunks_per_shard: int | None = None,
    overrides: ParsingOverrides | None = None,
    skip_suggested_lanes: Sequence[str] = ("noise",),
) -> KnowledgeJobBuildReport:
    """Write knowledge-stage job bundles to out_dir and return a build report.

    Notes:
    - Uses deterministic chunking/highlights as hints over seed Stage 7 non-recipe spans.
    - Chunk blocks come only from seed non-recipe spans; context may overlap recipes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sorted(out_dir.glob("*.json")):
        stale_path.unlink()
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    if not full_blocks_by_index:
        raise ValueError("Cannot build knowledge jobs: empty full_blocks.")
    source_spans_by_id = {
        str(span.span_id): KnowledgeSourceSpanV1(
            span_id=str(span.span_id),
            seed_category=str(span.category or "other"),
            block_start_index=int(span.block_start_index),
            block_end_index=int(span.block_end_index),
            block_indices=[int(index) for index in span.block_indices],
        )
        for span in candidate_spans
    }

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
    bundle_counter = 0
    normalized_skip_lanes = {
        str(value or "").strip().lower()
        for value in skip_suggested_lanes
        if str(value or "").strip()
    }
    skipped_chunk_count = 0
    skipped_lane_counts: dict[str, int] = {}
    all_prepared_chunks: list[_PreparedKnowledgeBundleChunk] = []
    shard_entries: list[ShardManifestEntryV1] = []

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
            absolute_indices = _absolute_indices_for_chunk(chunk, sequence=sequence)
            if _should_skip_low_signal_knowledge_chunk(
                chunk,
                absolute_indices=absolute_indices,
                full_blocks_by_index=full_blocks_by_index,
                table_hints_by_index=table_hints_by_index,
            ):
                skipped_chunk_count += 1
                skipped_lane_counts[_LOW_SIGNAL_SKIP_KEY] = (
                    int(skipped_lane_counts.get(_LOW_SIGNAL_SKIP_KEY) or 0) + 1
                )
                chunk_counter += 1
                continue
            payload, absolute_indices = _build_chunk_payload(
                chunk_id=chunk_id,
                chunk=chunk,
                stage_span=stage_span,
                absolute_indices=absolute_indices,
                full_blocks_by_index=full_blocks_by_index,
                table_hints_by_index=table_hints_by_index,
            )
            all_prepared_chunks.append(
                _PreparedKnowledgeBundleChunk(
                    payload=payload,
                    absolute_indices=absolute_indices,
                    char_count=sum(len(block.text) for block in payload.blocks),
                    has_table_content=any(block.table_hint is not None for block in payload.blocks),
                    source_span_id=stage_span.span_id,
                )
            )
            chunk_ids.append(chunk_id)
            chunk_lane_by_id[chunk_id] = (
                str(chunk.lane.value) if isinstance(chunk.lane, ChunkLane) else suggested_lane
            )
            chunk_counter += 1
    for bundle_chunks in _bundle_prepared_chunks(
        sorted(all_prepared_chunks, key=lambda chunk: chunk.absolute_indices[0]),
        target_bundle_count=target_prompt_count,
        max_chunks_per_bundle=target_chunks_per_shard,
    ):
        bundle_id = f"{workbook_slug}.ks{bundle_counter:04d}.nr"
        bundle_payload = _build_bundle_job_payload(
            bundle_id=bundle_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            prepared_chunks=bundle_chunks,
            full_blocks_by_index=full_blocks_by_index,
            recipe_spans_payload=recipe_spans_payload,
            context_blocks=context_blocks,
            source_spans_by_id=source_spans_by_id,
        )
        bundle_payload_json = bundle_payload.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        _write_json(
            bundle_payload_json,
            out_dir / f"{bundle_id}.json",
        )
        owned_chunk_ids = tuple(chunk.payload.chunk_id for chunk in bundle_chunks)
        owned_block_indices = tuple(
            sorted(
                {
                    int(index)
                    for chunk in bundle_chunks
                    for index in chunk.absolute_indices
                }
            )
        )
        source_span_ids = tuple(
            sorted(
                {
                    str(chunk.source_span_id).strip()
                    for chunk in bundle_chunks
                    if str(chunk.source_span_id).strip()
                }
            )
        )
        shard_entries.append(
            ShardManifestEntryV1(
                shard_id=bundle_id,
                owned_ids=owned_chunk_ids,
                evidence_refs=tuple(f"block:{index}" for index in owned_block_indices),
                input_payload=bundle_payload_json,
                metadata={
                    "owned_block_indices": list(owned_block_indices),
                    "source_span_ids": list(source_span_ids),
                    "chunk_count": len(owned_chunk_ids),
                    "char_count": sum(chunk.char_count for chunk in bundle_chunks),
                    "table_heavy": any(chunk.has_table_content for chunk in bundle_chunks),
                    "context_blocks": max(0, int(context_blocks)),
                },
            )
        )
        bundle_counter += 1

    return KnowledgeJobBuildReport(
        shards_written=bundle_counter,
        chunks_written=len(chunk_ids),
        chunk_ids=chunk_ids,
        chunk_lane_by_id=chunk_lane_by_id,
        skipped_chunk_count=skipped_chunk_count,
        skipped_lane_counts=skipped_lane_counts,
        shard_entries=shard_entries,
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


def _build_chunk_payload(
    *,
    chunk_id: str,
    chunk: KnowledgeChunk,
    stage_span: NonRecipeSpan,
    absolute_indices: Sequence[int],
    full_blocks_by_index: dict[int, dict[str, Any]],
    table_hints_by_index: Mapping[int, KnowledgeTableHintV1],
) -> tuple[KnowledgeCompactBundleChunkPayloadV2, list[int]]:
    if not chunk.block_ids:
        raise ValueError(f"Chunk {chunk_id} has no block_ids; cannot build job bundle.")

    block_start_index = absolute_indices[0]
    block_end_index = absolute_indices[-1] + 1

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
    return (
        KnowledgeCompactBundleChunkPayloadV2(
            chunk_id=chunk_id,
            block_start_index=int(block_start_index),
            block_end_index=int(block_end_index),
            source_span_id=str(stage_span.span_id),
            blocks=chunk_blocks_payload,
            heuristics=KnowledgeHeuristicsPayloadV1(
                suggested_lane=suggested_lane,
                suggested_highlights=suggested_highlights[:6],
                suggested_skip_reason=suggested_skip_reason,
            ),
            review_hints=_build_review_hints(
                chunk=chunk,
                chunk_blocks_payload=chunk_blocks_payload,
            ),
        ),
        absolute_indices,
    )


def _build_bundle_job_payload(
    *,
    bundle_id: str,
    workbook_slug: str,
    source_hash: str,
    prepared_chunks: Sequence[_PreparedKnowledgeBundleChunk],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    recipe_spans_payload: list[SpanV1],
    context_blocks: int,
    source_spans_by_id: Mapping[str, KnowledgeSourceSpanV1],
) -> KnowledgeCompactBundleJobInputV2:
    if not prepared_chunks:
        raise ValueError(f"Bundle {bundle_id} has no prepared chunks.")

    bundle_start_index = min(chunk.absolute_indices[0] for chunk in prepared_chunks)
    bundle_end_index = max(chunk.absolute_indices[-1] for chunk in prepared_chunks) + 1
    before_indices = range(max(0, bundle_start_index - context_blocks), bundle_start_index)
    after_indices = range(bundle_end_index, bundle_end_index + max(0, int(context_blocks)))
    context_recipe_block_indices = sorted(
        idx
        for idx in [*before_indices, *after_indices]
        if _index_in_recipe_spans(idx, recipe_spans_payload)
    )
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

    return KnowledgeCompactBundleJobInputV2(
        source=KnowledgeJobSourceV1(workbook_slug=workbook_slug, source_hash=source_hash),
        bundle_id=bundle_id,
        source_spans=[
            source_spans_by_id[source_span_id]
            for source_span_id in dict.fromkeys(
                str(chunk.source_span_id) for chunk in prepared_chunks
            )
            if source_span_id in source_spans_by_id
        ],
        chunks=[chunk.payload for chunk in prepared_chunks],
        context=KnowledgeCompactContextPayloadV1(
            blocks_before=blocks_before,
            blocks_after=blocks_after,
        ),
        guardrails=KnowledgeCompactGuardrailsPayloadV1(
            context_recipe_block_indices=context_recipe_block_indices,
            must_use_evidence=True,
        ),
    )


def _build_review_hints(
    *,
    chunk: KnowledgeChunk,
    chunk_blocks_payload: Sequence[KnowledgeCompactChunkBlockV1],
) -> KnowledgeChunkReviewHintsV1:
    text_form = _review_text_form(chunk_blocks_payload)
    suggested_lane = (
        chunk.lane.value if isinstance(chunk.lane, ChunkLane) else str(chunk.lane or "").strip()
    ).lower()
    if suggested_lane == ChunkLane.KNOWLEDGE.value:
        semantic_hint = "instructional"
    elif suggested_lane == ChunkLane.NARRATIVE.value:
        semantic_hint = "narrative_or_front_matter"
    elif text_form == "heading_like":
        semantic_hint = "heading_or_taxonomy"
    else:
        semantic_hint = "mixed"
    return KnowledgeChunkReviewHintsV1(
        text_form=text_form,
        semantic_hint=semantic_hint,
    )


def _review_text_form(
    chunk_blocks_payload: Sequence[KnowledgeCompactChunkBlockV1],
) -> str:
    if any(block.table_hint is not None for block in chunk_blocks_payload):
        return "table_like"
    heading_like_blocks = [
        block
        for block in chunk_blocks_payload
        if block.heading_level is not None or _looks_heading_like_text(block.text)
    ]
    if heading_like_blocks and len(heading_like_blocks) == len(chunk_blocks_payload):
        return "heading_like"
    prose_blocks = [
        block for block in chunk_blocks_payload if len(str(block.text or "").strip()) >= 80
    ]
    if prose_blocks or len(chunk_blocks_payload) > 1:
        return "prose_like"
    return "mixed"


def _looks_heading_like_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if len(stripped) <= 60 and stripped.upper() == stripped and any(char.isalpha() for char in stripped):
        return True
    return len(stripped.split()) <= 6 and stripped.endswith(":")


def _bundle_prepared_chunks(
    chunks: Sequence[_PreparedKnowledgeBundleChunk],
    *,
    target_bundle_count: int | None = None,
    max_chunks_per_bundle: int | None = _DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHUNKS,
    max_bundle_chars: int = _DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHARS,
    max_gap_blocks: int = _DEFAULT_KNOWLEDGE_BUNDLE_MAX_GAP_BLOCKS,
) -> list[list[_PreparedKnowledgeBundleChunk]]:
    if not chunks:
        return []
    effective_max_chunks = resolve_items_per_shard(
        total_items=len(chunks),
        prompt_target_count=target_bundle_count,
        items_per_shard=max_chunks_per_bundle,
        default_items_per_shard=_DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHUNKS,
    )
    effective_max_bundle_chars = _DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHARS
    effective_max_gap_blocks = _DEFAULT_KNOWLEDGE_BUNDLE_MAX_GAP_BLOCKS
    if target_bundle_count is not None:
        total_chars = sum(chunk.char_count for chunk in chunks)
        effective_max_bundle_chars = max(
            _DEFAULT_KNOWLEDGE_BUNDLE_MAX_CHARS,
            int(total_chars) + 1,
        )
        effective_max_gap_blocks = 10**9

    bundles: list[list[_PreparedKnowledgeBundleChunk]] = []
    current: list[_PreparedKnowledgeBundleChunk] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if current:
            bundles.append(current)
            current = []
            current_chars = 0

    for chunk in chunks:
        chunk_is_isolated = chunk.has_table_content or chunk.char_count >= effective_max_bundle_chars
        would_exceed_chunk_cap = bool(current) and len(current) >= effective_max_chunks
        would_exceed_char_cap = (
            bool(current)
            and current_chars + chunk.char_count > effective_max_bundle_chars
        )
        current_has_table = any(existing.has_table_content for existing in current)
        current_is_local = (
            not current
            or _chunk_gap_size(current[-1], chunk) <= max(0, int(effective_max_gap_blocks))
        )

        if chunk_is_isolated:
            flush()
            bundles.append([chunk])
            continue

        if (
            would_exceed_chunk_cap
            or would_exceed_char_cap
            or current_has_table
            or not current_is_local
        ):
            flush()

        current.append(chunk)
        current_chars += chunk.char_count

    flush()
    return bundles


def _chunk_gap_size(
    left: _PreparedKnowledgeBundleChunk,
    right: _PreparedKnowledgeBundleChunk,
) -> int:
    return max(0, int(right.absolute_indices[0]) - int(left.absolute_indices[-1]) - 1)


def _should_skip_low_signal_knowledge_chunk(
    chunk: KnowledgeChunk,
    *,
    absolute_indices: Sequence[int],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    table_hints_by_index: Mapping[int, KnowledgeTableHintV1],
) -> bool:
    lane = chunk.lane.value if isinstance(chunk.lane, ChunkLane) else str(chunk.lane or "")
    if str(lane).strip().lower() != ChunkLane.KNOWLEDGE.value:
        return False
    if _chunk_has_table_content(
        chunk,
        absolute_indices=absolute_indices,
        table_hints_by_index=table_hints_by_index,
    ):
        return False
    if _chunk_has_heading_context(
        chunk,
        absolute_indices=absolute_indices,
        full_blocks_by_index=full_blocks_by_index,
    ):
        return False
    if (chunk.highlight_count or 0) > 0 or bool(chunk.highlights):
        return False
    text = str(chunk.text or "").strip()
    if not text or len(text) > _DEFAULT_KNOWLEDGE_LOW_SIGNAL_MAX_CHARS:
        return False
    return True


def _chunk_has_heading_context(
    chunk: KnowledgeChunk,
    *,
    absolute_indices: Sequence[int],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> bool:
    if str(chunk.title or "").strip():
        return True
    if any(str(part or "").strip() for part in (chunk.section_path or [])):
        return True
    return any(
        _resolve_heading_level(full_blocks_by_index.get(int(index)) or {}) is not None
        for index in absolute_indices
    )


def _chunk_has_table_content(
    chunk: KnowledgeChunk,
    *,
    absolute_indices: Sequence[int],
    table_hints_by_index: Mapping[int, KnowledgeTableHintV1],
) -> bool:
    if any(int(index) in table_hints_by_index for index in absolute_indices):
        return True
    provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
    table_ids = provenance.get("table_ids")
    return isinstance(table_ids, list) and any(str(value or "").strip() for value in table_ids)


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
