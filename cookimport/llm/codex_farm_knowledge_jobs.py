from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.staging.nonrecipe_stage import (
    NonRecipeSpan,
    block_rows_for_nonrecipe_span,
)
from cookimport.staging.recipe_ownership import RecipeOwnershipResult
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.llm.shard_prompt_targets import (
    coerce_positive_int,
    partition_contiguous_items,
)

from .codex_farm_knowledge_contracts import (
    KnowledgePacketBlockV1,
    KnowledgePacketContextBlockV1,
    KnowledgePacketContextPayloadV1,
    KnowledgePacketGuardrailsPayloadV1,
    KnowledgePacketJobInputV1,
    KnowledgeShardJobInputV1,
    KnowledgeTableHintV1,
)

_DEFAULT_KNOWLEDGE_GROUP_TASK_MAX_UNITS = 40
@dataclass(frozen=True, slots=True)
class KnowledgeJobBuildReport:
    seed_nonrecipe_span_count: int
    candidate_nonrecipe_span_count: int
    packet_count_before_partition: int
    requested_shard_count: int
    shards_written: int
    packets_written: int
    candidate_block_count: int
    packet_ids: list[str]
    planning_warnings: list[str]
    shard_entries: list[ShardManifestEntryV1]
    skipped_packet_count: int = 0
    skipped_packet_reason_counts: dict[str, int] = field(default_factory=dict)
    packet_input_char_budget: int | None = None
    packet_output_char_budget: int | None = None


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgePacket:
    packet_id: str
    blocks: list[KnowledgePacketBlockV1]
    absolute_indices: list[int]
    char_count: int
    has_table_content: bool
    has_heading: bool
    source_span_ids: tuple[str, ...]
    estimated_pass1_input_chars: int
    estimated_pass1_output_chars: int
    estimated_pass2_input_chars: int
    estimated_pass2_output_chars: int


_DEFAULT_KNOWLEDGE_PACKET_INPUT_CHAR_BUDGET = 18_000
_DEFAULT_KNOWLEDGE_PACKET_OUTPUT_CHAR_BUDGET = 6_000
_PASS1_ROW_OUTPUT_ESTIMATE_CHARS = 48
_PASS2_ROW_OUTPUT_ESTIMATE_CHARS = 88
_PACKET_BASE_OUTPUT_ESTIMATE_CHARS = 96
_PACKET_BASE_INPUT_OVERHEAD_CHARS = 160


def build_knowledge_jobs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    candidate_spans: Sequence[NonRecipeSpan],
    recipe_ownership_result: RecipeOwnershipResult,
    workbook_slug: str,
    out_dir: Path,
    context_blocks: int = 2,
    prompt_target_count: int | None = None,
    input_char_budget: int | None = None,
    output_char_budget: int | None = None,
    group_task_max_units: int = _DEFAULT_KNOWLEDGE_GROUP_TASK_MAX_UNITS,
) -> KnowledgeJobBuildReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sorted(out_dir.glob("*.json")):
        stale_path.unlink()

    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    if not full_blocks_by_index:
        raise ValueError("Cannot build knowledge jobs: empty full_blocks.")
    owned_block_indices = set(recipe_ownership_result.owned_block_indices)
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
    resolved_input_char_budget = _resolve_budget(
        value=input_char_budget,
        default=_DEFAULT_KNOWLEDGE_PACKET_INPUT_CHAR_BUDGET,
    )
    resolved_output_char_budget = _resolve_budget(
        value=output_char_budget,
        default=_DEFAULT_KNOWLEDGE_PACKET_OUTPUT_CHAR_BUDGET,
    )
    budget_row_partitions = _partition_rows_by_budget(
        rows=ordered_review_rows,
        input_char_budget=resolved_input_char_budget,
        output_char_budget=resolved_output_char_budget,
        group_task_max_units=group_task_max_units,
    )
    packet_count_before_partition = len(budget_row_partitions)
    configured_prompt_target = coerce_positive_int(prompt_target_count)
    if configured_prompt_target is None:
        row_partitions = list(budget_row_partitions)
        requested_shard_count = len(row_partitions)
    else:
        requested_shard_count = min(
            max(1, int(configured_prompt_target)),
            len(ordered_review_rows),
        )
        if packet_count_before_partition > requested_shard_count:
            planning_warnings.append(
                "knowledge_prompt_target_count is using the requested final shard count "
                f"of {requested_shard_count}; packet-budget planning would have split "
                f"the queue into {packet_count_before_partition} shards."
            )
        row_partitions = _repartition_rows_to_target_count(
            rows=ordered_review_rows,
            target_count=requested_shard_count,
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
                estimated_pass1_input_chars=_estimate_pass1_input_chars(
                    absolute_indices=absolute_indices,
                    full_blocks_by_index=full_blocks_by_index,
                    owned_block_indices=owned_block_indices,
                    context_blocks=context_blocks,
                ),
                estimated_pass1_output_chars=_estimate_pass1_output_chars(
                    owned_row_count=len(absolute_indices)
                ),
                estimated_pass2_input_chars=_estimate_pass2_input_chars(
                    absolute_indices=absolute_indices,
                    full_blocks_by_index=full_blocks_by_index,
                ),
                estimated_pass2_output_chars=_estimate_pass2_output_chars(
                    owned_row_count=len(absolute_indices),
                    group_task_max_units=group_task_max_units,
                ),
            )
        )

    sorted_packets = prepared_packets
    shard_entries: list[ShardManifestEntryV1] = []
    for packet in sorted_packets:
        bundle_payload = _build_packet_job_payload(
            packet=packet,
            full_blocks_by_index=full_blocks_by_index,
            owned_block_indices=owned_block_indices,
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
                    "estimated_pass1_input_chars": packet.estimated_pass1_input_chars,
                    "estimated_pass1_output_chars": packet.estimated_pass1_output_chars,
                    "estimated_pass2_input_chars": packet.estimated_pass2_input_chars,
                    "estimated_pass2_output_chars": packet.estimated_pass2_output_chars,
                    "estimated_input_chars_max": max(
                        packet.estimated_pass1_input_chars,
                        packet.estimated_pass2_input_chars,
                    ),
                    "estimated_output_chars_max": max(
                        packet.estimated_pass1_output_chars,
                        packet.estimated_pass2_output_chars,
                    ),
                    "input_char_budget": resolved_input_char_budget,
                    "output_char_budget": resolved_output_char_budget,
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
        candidate_nonrecipe_span_count=len(candidate_spans),
        packet_count_before_partition=packet_count_before_partition,
        requested_shard_count=requested_shard_count,
        shards_written=len(shard_entries),
        packets_written=len(written_packets),
        candidate_block_count=len(
            {
                index
                for packet in written_packets
                for index in packet.absolute_indices
            }
        ),
        packet_ids=[packet.packet_id for packet in written_packets],
        planning_warnings=planning_warnings,
        shard_entries=shard_entries,
        packet_input_char_budget=resolved_input_char_budget,
        packet_output_char_budget=resolved_output_char_budget,
    )


def _resolve_budget(*, value: int | None, default: int) -> int:
    if value is None:
        return int(default)
    return max(1, int(value))


def _estimate_row_input_chars(row: Mapping[str, Any]) -> int:
    text = str(row.get("text") or "").strip()
    return len(text) + 48


def _estimate_row_output_chars(*, row_count: int, per_row_chars: int) -> int:
    return _PACKET_BASE_OUTPUT_ESTIMATE_CHARS + (max(0, int(row_count)) * per_row_chars)


def _grouping_batch_output_row_count(
    *,
    owned_row_count: int,
    group_task_max_units: int,
) -> int:
    return min(max(0, int(owned_row_count)), max(1, int(group_task_max_units)))


def _partition_rows_by_budget(
    *,
    rows: Sequence[Mapping[str, Any]],
    input_char_budget: int,
    output_char_budget: int,
    group_task_max_units: int,
) -> list[list[dict[str, Any]]]:
    partitions: list[list[dict[str, Any]]] = []
    current_rows: list[dict[str, Any]] = []
    current_input_chars = _PACKET_BASE_INPUT_OVERHEAD_CHARS
    for row in rows:
        row_payload = dict(row)
        row_input_chars = _estimate_row_input_chars(row_payload)
        next_count = len(current_rows) + 1
        next_input_chars = current_input_chars + row_input_chars
        next_output_chars = max(
            _estimate_row_output_chars(
                row_count=next_count,
                per_row_chars=_PASS1_ROW_OUTPUT_ESTIMATE_CHARS,
            ),
            _estimate_row_output_chars(
                row_count=_grouping_batch_output_row_count(
                    owned_row_count=next_count,
                    group_task_max_units=group_task_max_units,
                ),
                per_row_chars=_PASS2_ROW_OUTPUT_ESTIMATE_CHARS,
            ),
        )
        if (
            current_rows
            and (
                next_input_chars > input_char_budget
                or next_output_chars > output_char_budget
            )
        ):
            partitions.append(current_rows)
            current_rows = [row_payload]
            current_input_chars = _PACKET_BASE_INPUT_OVERHEAD_CHARS + row_input_chars
            continue
        current_rows.append(row_payload)
        current_input_chars = next_input_chars
    if current_rows:
        partitions.append(current_rows)
    return partitions


def _split_budget_partitions_to_target_count(
    *,
    row_partitions: Sequence[Sequence[Mapping[str, Any]]],
    target_count: int,
) -> list[list[dict[str, Any]]]:
    partitions = [
        [dict(row) for row in partition if isinstance(row, Mapping)]
        for partition in row_partitions
        if partition
    ]
    while len(partitions) < max(1, int(target_count or 1)):
        split_index = max(
            range(len(partitions)),
            key=lambda index: len(partitions[index]),
            default=-1,
        )
        if split_index < 0 or len(partitions[split_index]) <= 1:
            break
        largest = partitions.pop(split_index)
        midpoint = max(1, len(largest) // 2)
        partitions.insert(split_index, largest[:midpoint])
        partitions.insert(split_index + 1, largest[midpoint:])
    return partitions


def _repartition_rows_to_target_count(
    *,
    rows: Sequence[Mapping[str, Any]],
    target_count: int,
) -> list[list[dict[str, Any]]]:
    normalized_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not normalized_rows:
        return []
    return [
        [dict(row) for row in partition]
        for partition in partition_contiguous_items(
            normalized_rows,
            shard_count=max(1, int(target_count or 1)),
        )
        if partition
    ]


def _estimate_pass1_input_chars(
    *,
    absolute_indices: Sequence[int],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    owned_block_indices: set[int],
    context_blocks: int,
) -> int:
    if not absolute_indices:
        return _PACKET_BASE_INPUT_OVERHEAD_CHARS
    packet_start_index = min(absolute_indices)
    packet_end_index = max(absolute_indices) + 1
    before_indices = range(max(0, packet_start_index - context_blocks), packet_start_index)
    after_indices = range(packet_end_index, packet_end_index + max(0, int(context_blocks)))
    context_indices = [
        idx
        for idx in [*before_indices, *after_indices]
        if idx in full_blocks_by_index
        and not _row_or_source_block_is_recipe_owned(
            idx,
            full_blocks_by_index=full_blocks_by_index,
            owned_block_indices=owned_block_indices,
        )
    ]
    owned_chars = sum(
        _estimate_row_input_chars(full_blocks_by_index.get(index) or {})
        for index in absolute_indices
    )
    context_chars = sum(
        len(str((full_blocks_by_index.get(index) or {}).get("text") or "").strip()) + 24
        for index in context_indices
    )
    return _PACKET_BASE_INPUT_OVERHEAD_CHARS + owned_chars + context_chars


def _estimate_pass1_output_chars(*, owned_row_count: int) -> int:
    return _estimate_row_output_chars(
        row_count=owned_row_count,
        per_row_chars=_PASS1_ROW_OUTPUT_ESTIMATE_CHARS,
    )


def _estimate_pass2_input_chars(
    *,
    absolute_indices: Sequence[int],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> int:
    return _PACKET_BASE_INPUT_OVERHEAD_CHARS + sum(
        _estimate_row_input_chars(full_blocks_by_index.get(index) or {})
        for index in absolute_indices
    )


def _estimate_pass2_output_chars(
    *,
    owned_row_count: int,
    group_task_max_units: int,
) -> int:
    return _estimate_row_output_chars(
        row_count=_grouping_batch_output_row_count(
            owned_row_count=owned_row_count,
            group_task_max_units=group_task_max_units,
        ),
        per_row_chars=_PASS2_ROW_OUTPUT_ESTIMATE_CHARS,
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
    owned_block_indices: set[int],
    context_blocks: int,
) -> KnowledgePacketJobInputV1:
    packet_start_index = min(packet.absolute_indices)
    packet_end_index = max(packet.absolute_indices) + 1
    before_indices = range(max(0, packet_start_index - context_blocks), packet_start_index)
    after_indices = range(packet_end_index, packet_end_index + max(0, int(context_blocks)))
    context_recipe_block_indices = sorted(
        idx
        for idx in [*before_indices, *after_indices]
        if _row_or_source_block_is_recipe_owned(
            idx,
            full_blocks_by_index=full_blocks_by_index,
            owned_block_indices=owned_block_indices,
        )
    )
    blocks_before = [
        _to_knowledge_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in before_indices
        if idx in full_blocks_by_index
        and not _row_or_source_block_is_recipe_owned(
            idx,
            full_blocks_by_index=full_blocks_by_index,
            owned_block_indices=owned_block_indices,
        )
    ]
    blocks_after = [
        _to_knowledge_context_block(
            full_blocks_by_index[idx],
            fallback_index=idx,
        )
        for idx in after_indices
        if idx in full_blocks_by_index
        and not _row_or_source_block_is_recipe_owned(
            idx,
            full_blocks_by_index=full_blocks_by_index,
            owned_block_indices=owned_block_indices,
        )
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


def _row_or_source_block_is_recipe_owned(
    index: int,
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    owned_block_indices: set[int],
) -> bool:
    if int(index) in owned_block_indices:
        return True
    payload = full_blocks_by_index.get(int(index), {})
    try:
        source_block_index = int(payload.get("source_block_index"))
    except (TypeError, ValueError):
        return False
    return source_block_index in owned_block_indices


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
