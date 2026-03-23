from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import ChunkLane, KnowledgeChunk, ParsingOverrides
from cookimport.parsing.chunks import (
    chunks_from_non_recipe_blocks,
    summarize_chunk_utility_profile,
)
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import (
    NonRecipeSpan,
    block_rows_for_nonrecipe_span,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1

from .codex_farm_knowledge_contracts import (
    KnowledgeCompactBundleChunkPayloadV2,
    KnowledgeCompactBundleJobInputV2,
    KnowledgeCompactChunkBlockV1,
    KnowledgeCompactContextBlockV1,
    KnowledgeCompactContextPayloadV1,
    KnowledgeCompactGuardrailsPayloadV1,
    KnowledgeCompactTableHintV1,
    KnowledgeTableHintV1,
    SpanV1,
)


@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    seed_nonrecipe_span_count: int
    review_eligible_nonrecipe_span_count: int
    chunk_count_before_pruning: int
    shards_written: int
    chunks_written: int
    review_eligible_block_count: int
    chunk_ids: list[str]
    chunk_lane_by_id: dict[str, str | None]
    skipped_chunk_count: int
    skipped_lane_counts: dict[str, int]
    planning_warnings: list[str]
    shard_entries: list[ShardManifestEntryV1]


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeBundleChunk:
    payload: KnowledgeCompactBundleChunkPayloadV2
    absolute_indices: list[int]
    char_count: int
    has_table_content: bool
    has_heading: bool
    seed_stage_category: str | None
    suggested_lane: str | None
    title: str | None
    knowledge_cue: bool
    utility_profile: dict[str, Any]
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
    overrides: ParsingOverrides | None = None,
    skip_suggested_lanes: Sequence[str] = (),
) -> KnowledgeJobBuildReport:
    """Write knowledge-stage job bundles to out_dir and return a build report.

    Notes:
    - Uses deterministic chunking over review-eligible Stage 7 non-recipe spans.
    - Chunk blocks come only from review-eligible non-recipe spans; context may overlap recipes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sorted(out_dir.glob("*.json")):
        stale_path.unlink()
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
    bundle_counter = 0
    normalized_skip_lanes = {
        str(value or "").strip().lower()
        for value in skip_suggested_lanes
        if str(value or "").strip()
    }
    chunk_count_before_pruning = 0
    skipped_chunk_count = 0
    skipped_lane_counts: dict[str, int] = {}
    planning_warnings: list[str] = []
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
            chunk_count_before_pruning += 1
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
            payload, absolute_indices = _build_chunk_payload(
                chunk_id=chunk_id,
                chunk=chunk,
                absolute_indices=absolute_indices,
                full_blocks_by_index=full_blocks_by_index,
                table_hints_by_index=table_hints_by_index,
            )
            utility_profile = summarize_chunk_utility_profile(chunk)
            all_prepared_chunks.append(
                _PreparedKnowledgeBundleChunk(
                    payload=payload,
                    absolute_indices=absolute_indices,
                    char_count=sum(len(block.text) for block in payload.blocks),
                    has_table_content=any(block.table_hint is not None for block in payload.blocks),
                    has_heading=any(block.heading_level is not None for block in payload.blocks),
                    seed_stage_category=str(stage_span.category or "").strip() or None,
                    suggested_lane=str(suggested_lane or "").strip() or None,
                    title=str(chunk.title or "").strip() or None,
                    knowledge_cue=_chunk_has_strong_knowledge_cue(
                        chunk=chunk,
                        payload=payload,
                        seed_stage_category=str(stage_span.category or "").strip() or None,
                        utility_profile=utility_profile,
                    ),
                    utility_profile=utility_profile,
                    source_span_id=stage_span.span_id,
                )
            )
            chunk_ids.append(chunk_id)
            chunk_lane_by_id[chunk_id] = (
                str(chunk.lane.value) if isinstance(chunk.lane, ChunkLane) else suggested_lane
            )
            chunk_counter += 1
    planning_warnings: list[str] = []
    for prepared_chunk in sorted(
        all_prepared_chunks,
        key=lambda chunk: chunk.absolute_indices[0],
    ):
        bundle_id = f"{workbook_slug}.ks{bundle_counter:04d}.nr"
        bundle_payload = _build_bundle_job_payload(
            bundle_id=bundle_id,
            prepared_chunks=[prepared_chunk],
            full_blocks_by_index=full_blocks_by_index,
            recipe_spans_payload=recipe_spans_payload,
            context_blocks=context_blocks,
        )
        bundle_payload_json = bundle_payload.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_defaults=True,
        )
        bundle_payload_json.setdefault("v", "2")
        _write_json(
            bundle_payload_json,
            out_dir / f"{bundle_id}.json",
        )
        owned_chunk_ids = (prepared_chunk.payload.chunk_id,)
        owned_block_indices = tuple(sorted(int(index) for index in prepared_chunk.absolute_indices))
        source_span_id = str(prepared_chunk.source_span_id).strip()
        source_span_ids = (source_span_id,) if source_span_id else ()
        shard_entries.append(
            ShardManifestEntryV1(
                shard_id=bundle_id,
                owned_ids=owned_chunk_ids,
                evidence_refs=tuple(f"block:{index}" for index in owned_block_indices),
                input_payload=bundle_payload_json,
                metadata={
                    "ordered_chunk_ids": list(owned_chunk_ids),
                    "owned_block_indices": list(owned_block_indices),
                    "source_span_ids": list(source_span_ids),
                    "chunk_count": 1,
                    "char_count": int(prepared_chunk.char_count),
                    "table_heavy": bool(prepared_chunk.has_table_content),
                    "context_blocks": max(0, int(context_blocks)),
                    "chunk_block_indices_by_id": {
                        prepared_chunk.payload.chunk_id: list(prepared_chunk.absolute_indices)
                    },
                    "chunk_seed_stage_category_by_id": (
                        {
                            prepared_chunk.payload.chunk_id: prepared_chunk.seed_stage_category
                        }
                        if prepared_chunk.seed_stage_category is not None
                        else {}
                    ),
                    "chunk_lane_by_id": (
                        {prepared_chunk.payload.chunk_id: prepared_chunk.suggested_lane}
                        if prepared_chunk.suggested_lane is not None
                        else {}
                    ),
                    "chunk_title_by_id": (
                        {prepared_chunk.payload.chunk_id: prepared_chunk.title}
                        if prepared_chunk.title is not None
                        else {}
                    ),
                    "chunk_has_heading_by_id": {
                        prepared_chunk.payload.chunk_id: bool(prepared_chunk.has_heading)
                    },
                    "chunk_has_table_hint_by_id": {
                        prepared_chunk.payload.chunk_id: bool(prepared_chunk.has_table_content)
                    },
                    "chunk_knowledge_cue_by_id": {
                        prepared_chunk.payload.chunk_id: bool(prepared_chunk.knowledge_cue)
                    },
                    "chunk_utility_positive_cues_by_id": {
                        prepared_chunk.payload.chunk_id: list(
                            prepared_chunk.utility_profile.get("positive_cues") or []
                        )
                    },
                    "chunk_utility_negative_cues_by_id": {
                        prepared_chunk.payload.chunk_id: list(
                            prepared_chunk.utility_profile.get("negative_cues") or []
                        )
                    },
                    "chunk_utility_borderline_by_id": {
                        prepared_chunk.payload.chunk_id: bool(
                            prepared_chunk.utility_profile.get("borderline")
                        )
                    },
                    "chunk_strong_negative_utility_cue_by_id": {
                        prepared_chunk.payload.chunk_id: bool(
                            prepared_chunk.utility_profile.get("strong_negative_cue")
                        )
                    },
                },
            )
        )
        bundle_counter += 1

    return KnowledgeJobBuildReport(
        seed_nonrecipe_span_count=len(candidate_spans),
        review_eligible_nonrecipe_span_count=len(candidate_spans),
        chunk_count_before_pruning=chunk_count_before_pruning,
        shards_written=bundle_counter,
        chunks_written=len(chunk_ids),
        review_eligible_block_count=len(
            {
                index
                for chunk in all_prepared_chunks
                for index in chunk.absolute_indices
            }
        ),
        chunk_ids=chunk_ids,
        chunk_lane_by_id=chunk_lane_by_id,
        skipped_chunk_count=skipped_chunk_count,
        skipped_lane_counts=skipped_lane_counts,
        planning_warnings=planning_warnings,
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
    absolute_indices: Sequence[int],
    full_blocks_by_index: dict[int, dict[str, Any]],
    table_hints_by_index: Mapping[int, KnowledgeTableHintV1],
) -> tuple[KnowledgeCompactBundleChunkPayloadV2, list[int]]:
    if not chunk.block_ids:
        raise ValueError(f"Chunk {chunk_id} has no block_ids; cannot build job bundle.")

    suggested_lane: str | None
    if isinstance(chunk.lane, ChunkLane):
        suggested_lane = chunk.lane.value
    else:
        suggested_lane = str(chunk.lane) if chunk.lane is not None else None

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
            blocks=chunk_blocks_payload,
        ),
        absolute_indices,
    )


def _build_bundle_job_payload(
    *,
    bundle_id: str,
    prepared_chunks: Sequence[_PreparedKnowledgeBundleChunk],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    recipe_spans_payload: list[SpanV1],
    context_blocks: int,
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

    context_payload = KnowledgeCompactContextPayloadV1(
        blocks_before=blocks_before,
        blocks_after=blocks_after,
    )
    guardrails_payload = KnowledgeCompactGuardrailsPayloadV1(
        context_recipe_block_indices=context_recipe_block_indices,
    )
    return KnowledgeCompactBundleJobInputV2(
        bundle_id=bundle_id,
        chunks=[chunk.payload for chunk in prepared_chunks],
        context=(
            context_payload
            if context_payload.blocks_before or context_payload.blocks_after
            else None
        ),
        guardrails=(
            guardrails_payload
            if guardrails_payload.context_recipe_block_indices
            else None
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


def _chunk_has_strong_knowledge_cue(
    *,
    chunk: KnowledgeChunk,
    payload: KnowledgeCompactBundleChunkPayloadV2,
    seed_stage_category: str | None,
    utility_profile: Mapping[str, Any] | None,
) -> bool:
    normalized_seed_category = str(seed_stage_category or "").strip().lower()
    block_char_count = sum(len(str(block.text or "").strip()) for block in payload.blocks)
    profile = dict(utility_profile or {})
    positive_cues = {
        str(cue).strip()
        for cue in (profile.get("positive_cues") or [])
        if str(cue).strip()
    }
    strong_negative_cue = bool(profile.get("strong_negative_cue"))
    borderline = bool(profile.get("borderline"))
    high_precision_positive_cues = {
        "reference_table_shape",
        "diagnostic_or_sensory",
        "storage_or_safety",
        "failure_prevention",
    }
    if (
        strong_negative_cue
        and borderline
        and positive_cues
        and not high_precision_positive_cues.intersection(positive_cues)
    ):
        return False
    if bool(profile.get("strong_positive_cue")):
        return True
    if any(block.table_hint is not None for block in payload.blocks):
        return True
    if normalized_seed_category == "knowledge" and block_char_count >= 20 and positive_cues:
        return True
    if {"storage_or_safety", "failure_prevention", "diagnostic_or_sensory"}.intersection(
        positive_cues
    ):
        return True
    title_candidates: list[str] = []
    title = str(chunk.title or "").strip()
    if title:
        title_candidates.append(title)
    title_candidates.extend(
        str(block.text or "").strip()
        for block in payload.blocks
        if block.heading_level is not None and str(block.text or "").strip()
    )
    return bool(positive_cues) and any(
        _looks_like_reference_heading(text) for text in title_candidates
    )


def _looks_like_reference_heading(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    keywords = (
        "how ",
        "how to ",
        "how salt affects",
        "how acid affects",
        "how fat affects",
        "how heat affects",
        "how it works",
        "why it works",
        "storage",
        "storing",
        "substitution",
        "substitutions",
        "troubleshooting",
        "smoke point",
        "smoke points",
        "temperature guide",
        "temperature chart",
        "conversion",
        "conversions",
        "reference",
        "technique",
        "techniques",
        "safety",
    )
    return any(keyword in normalized for keyword in keywords)


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
