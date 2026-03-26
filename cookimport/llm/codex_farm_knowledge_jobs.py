from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import (
    NonRecipeSpan,
    block_rows_for_nonrecipe_span,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.llm.shard_prompt_targets import (
    partition_contiguous_items,
    resolve_shard_count,
)

from .codex_farm_knowledge_contracts import (
    KnowledgePacketBlockV1,
    KnowledgePacketContextBlockV1,
    KnowledgePacketContextPayloadV1,
    KnowledgePacketGuardrailsPayloadV1,
    KnowledgePacketJobInputV1,
    KnowledgeShardJobInputV1,
    KnowledgeTableHintV1,
    SpanV1,
)

@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    seed_nonrecipe_span_count: int
    review_eligible_nonrecipe_span_count: int
    packet_count_before_partition: int
    shards_written: int
    packets_written: int
    review_eligible_block_count: int
    packet_ids: list[str]
    planning_warnings: list[str]
    shard_entries: list[ShardManifestEntryV1]
    skipped_packet_count: int = 0
    skipped_packet_reason_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgePacket:
    packet_id: str
    blocks: list[KnowledgePacketBlockV1]
    absolute_indices: list[int]
    char_count: int
    has_table_content: bool
    has_heading: bool
    source_span_ids: tuple[str, ...]


def build_knowledge_jobs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    candidate_spans: Sequence[NonRecipeSpan],
    recipe_spans: Sequence[RecipeSpan],
    workbook_slug: str,
    out_dir: Path,
    context_blocks: int = 2,
    prompt_target_count: int | None = None,
) -> KnowledgeJobBuildReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sorted(out_dir.glob("*.json")):
        stale_path.unlink()

    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    if not full_blocks_by_index:
        raise ValueError("Cannot build knowledge jobs: empty full_blocks.")

    recipe_spans_payload = [
        SpanV1(start=int(span.start_block_index), end=int(span.end_block_index))
        for span in recipe_spans
    ]
    planning_warnings: list[str] = []
    ordered_review_rows: list[dict[str, Any]] = []
    source_span_ids_by_index: dict[int, list[str]] = {}

    for stage_span in candidate_spans:
        sequence = block_rows_for_nonrecipe_span(
            full_blocks=full_blocks,
            span=stage_span,
        )
        if not sequence:
            continue
        for row in sequence:
            index = _coerce_int(row.get("index"))
            if index is None:
                continue
            ordered_review_rows.append(dict(row))
            source_span_ids_by_index.setdefault(index, []).append(str(stage_span.span_id).strip())

    ordered_review_rows = sorted(
        ordered_review_rows,
        key=lambda row: int(row.get("index") or 0),
    )
    table_hints_by_index = _table_hints_by_index(ordered_review_rows)
    requested_shard_count = resolve_shard_count(
        total_items=len(ordered_review_rows),
        prompt_target_count=prompt_target_count,
        items_per_shard=None,
        default_items_per_shard=max(1, len(ordered_review_rows) or 1),
    )
    row_partitions = partition_contiguous_items(
        ordered_review_rows,
        shard_count=requested_shard_count,
    )
    prepared_packets: list[_PreparedKnowledgePacket] = []
    for shard_index, shard_rows in enumerate(row_partitions, start=0):
        absolute_indices = [
            int(row["index"])
            for row in shard_rows
            if _coerce_int(row.get("index")) is not None
        ]
        if not absolute_indices:
            continue
        shard_id = f"{workbook_slug}.ks{shard_index:04d}.nr"
        blocks = [
            _to_knowledge_packet_block(
                full_blocks_by_index.get(index) or {},
                fallback_index=index,
                table_hint=table_hints_by_index.get(index),
            )
            for index in absolute_indices
        ]
        prepared_packets.append(
            _PreparedKnowledgePacket(
                packet_id=shard_id,
                blocks=blocks,
                absolute_indices=absolute_indices,
                char_count=sum(len(str(block.text or "").strip()) for block in blocks),
                has_table_content=any(block.table_hint is not None for block in blocks),
                has_heading=any(block.heading_level is not None for block in blocks),
                source_span_ids=tuple(
                    dict.fromkeys(
                        span_id
                        for index in absolute_indices
                        for span_id in source_span_ids_by_index.get(index, ())
                    )
                ),
            )
        )

    sorted_packets = prepared_packets
    shard_entries: list[ShardManifestEntryV1] = []
    for packet in sorted_packets:
        bundle_payload = _build_packet_job_payload(
            packet=packet,
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
        bundle_payload_json.setdefault("v", "1")
        _write_json(
            bundle_payload_json,
            out_dir / f"{packet.packet_id}.json",
        )
        shard_entries.append(
            ShardManifestEntryV1(
                shard_id=packet.packet_id,
                owned_ids=(packet.packet_id,),
                evidence_refs=tuple(f"block:{index}" for index in packet.absolute_indices),
                input_payload=bundle_payload_json,
                metadata={
                    "packet_id": packet.packet_id,
                    "packet_count": 1,
                    "owned_packet_ids": [packet.packet_id],
                    "owned_packet_count": 1,
                    "owned_block_indices": list(packet.absolute_indices),
                    "owned_block_count": len(packet.absolute_indices),
                    "source_span_ids": list(packet.source_span_ids),
                    "char_count": packet.char_count,
                    "table_heavy": packet.has_table_content,
                    "has_heading": packet.has_heading,
                    "context_blocks": max(0, int(context_blocks)),
                    "task_count": 1,
                    "task_index": 1,
                },
            )
        )
    written_packets: list[_PreparedKnowledgePacket] = list(sorted_packets)

    return KnowledgeJobBuildReport(
        seed_nonrecipe_span_count=len(candidate_spans),
        review_eligible_nonrecipe_span_count=len(candidate_spans),
        packet_count_before_partition=len(sorted_packets),
        shards_written=len(shard_entries),
        packets_written=len(written_packets),
        review_eligible_block_count=len(
            {
                index
                for packet in written_packets
                for index in packet.absolute_indices
            }
        ),
        packet_ids=[packet.packet_id for packet in written_packets],
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


def _build_packet_job_payload(
    *,
    packet: _PreparedKnowledgePacket,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    recipe_spans_payload: list[SpanV1],
    context_blocks: int,
) -> KnowledgePacketJobInputV1:
    packet_start_index = min(packet.absolute_indices)
    packet_end_index = max(packet.absolute_indices) + 1
    before_indices = range(max(0, packet_start_index - context_blocks), packet_start_index)
    after_indices = range(packet_end_index, packet_end_index + max(0, int(context_blocks)))
    context_recipe_block_indices = sorted(
        idx
        for idx in [*before_indices, *after_indices]
        if _index_in_recipe_spans(idx, recipe_spans_payload)
    )
    blocks_before = [
        _to_knowledge_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in before_indices
        if idx in full_blocks_by_index
    ]
    blocks_after = [
        _to_knowledge_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in after_indices
        if idx in full_blocks_by_index
    ]
    context_payload = KnowledgePacketContextPayloadV1(
        blocks_before=blocks_before,
        blocks_after=blocks_after,
    )
    guardrails_payload = KnowledgePacketGuardrailsPayloadV1(
        context_recipe_block_indices=context_recipe_block_indices,
    )
    return KnowledgePacketJobInputV1(
        packet_id=packet.packet_id,
        blocks=packet.blocks,
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


def _index_in_recipe_spans(index: int, recipe_spans_payload: Sequence[SpanV1]) -> bool:
    return any(int(span.start) <= index < int(span.end) for span in recipe_spans_payload)


def _to_knowledge_packet_block(
    block: Mapping[str, Any],
    *,
    fallback_index: int,
    table_hint: KnowledgeTableHintV1 | None = None,
) -> KnowledgePacketBlockV1:
    index = _coerce_int(block.get("index"))
    if index is None:
        index = int(fallback_index)
    compact_table_hint = None
    if table_hint is not None:
        compact_table_hint = {
            "id": table_hint.table_id,
            "c": table_hint.caption,
            "r": table_hint.row_index_in_table,
        }
    return KnowledgePacketBlockV1(
        i=index,
        t=str(block.get("text") or ""),
        hl=_resolve_heading_level(block),
        th=compact_table_hint,
    )


def _to_knowledge_context_block(
    block: Mapping[str, Any],
    *,
    fallback_index: int,
) -> KnowledgePacketContextBlockV1:
    index = _coerce_int(block.get("index"))
    if index is None:
        index = int(fallback_index)
    return KnowledgePacketContextBlockV1(
        i=index,
        t=str(block.get("text") or ""),
        hl=_resolve_heading_level(block),
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
