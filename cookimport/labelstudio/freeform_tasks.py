from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Iterable, Sequence

from cookimport.labelstudio.block_tasks import build_block_id
from cookimport.labelstudio.models import ArchiveBlock

SEGMENT_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class SegmentTaskData:
    segment_id: str
    source_hash: str
    source_file: str
    book_id: str
    segment_index: int
    segment_text: str
    source_map: dict[str, Any]
    focus_block_range: str = ""
    context_before_block_range: str = ""
    context_after_block_range: str = ""
    focus_scope_hint: str = ""

    def to_task(self) -> dict[str, Any]:
        return {
            "data": {
                "segment_id": self.segment_id,
                "source_hash": self.source_hash,
                "source_file": self.source_file,
                "book_id": self.book_id,
                "segment_index": self.segment_index,
                "segment_text": self.segment_text,
                "source_map": self.source_map,
                "focus_block_range": self.focus_block_range,
                "context_before_block_range": self.context_before_block_range,
                "context_after_block_range": self.context_after_block_range,
                "focus_scope_hint": self.focus_scope_hint,
            }
        }


def build_segment_id(source_hash: str, start_block_index: int, end_block_index: int) -> str:
    return f"urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}"


def _coerce_archive(archive: Iterable[ArchiveBlock | dict[str, Any]]) -> list[ArchiveBlock]:
    blocks: list[ArchiveBlock] = []
    for item in archive:
        if isinstance(item, ArchiveBlock):
            blocks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        index = item.get("index")
        if index is None:
            index = item.get("block_index", len(blocks))
        location = item.get("location")
        if not isinstance(location, dict):
            location = {
                k: v
                for k, v in item.items()
                if k not in {"text", "index", "source_kind"}
            }
        source_kind = item.get("source_kind")
        blocks.append(
            ArchiveBlock(
                index=int(index),
                text=str(text),
                location=location,
                source_kind=source_kind,
            )
        )
    blocks.sort(key=lambda block: block.index)
    return blocks


def _segment_ranges(
    total_blocks: int, segment_blocks: int, segment_overlap: int
) -> list[tuple[int, int]]:
    if segment_blocks <= 0:
        raise ValueError("segment_blocks must be >= 1")
    if segment_overlap < 0:
        raise ValueError("segment_overlap must be >= 0")
    if segment_overlap >= segment_blocks:
        raise ValueError("segment_overlap must be smaller than segment_blocks")
    if total_blocks <= 0:
        return []

    step = segment_blocks - segment_overlap
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_blocks:
        end = min(total_blocks, start + segment_blocks)
        ranges.append((start, end))
        if end >= total_blocks:
            break
        start += step
    return ranges


def _collapse_block_index_ranges(indices: Sequence[int]) -> str:
    if not indices:
        return "none"
    ordered = sorted({int(value) for value in indices})
    ranges: list[str] = []
    start = ordered[0]
    end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
            continue
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")
        start = value
        end = value
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")
    return ", ".join(ranges)


def _resolve_focus_slice_bounds(
    *,
    segment_length: int,
    segment_blocks: int,
    segment_focus_blocks: int,
) -> tuple[int, int]:
    if segment_length <= 0:
        return (0, 0)
    focus_count = min(segment_focus_blocks, segment_length)
    if focus_count >= segment_length:
        return (0, segment_length)
    preferred_context_before = max(0, (segment_blocks - segment_focus_blocks) // 2)
    max_context_before = segment_length - focus_count
    context_before = min(preferred_context_before, max_context_before)
    start = max(0, context_before)
    end = start + focus_count
    return (start, end)


def resolve_segment_overlap_for_target(
    *,
    total_blocks: int,
    segment_blocks: int,
    requested_overlap: int,
    target_task_count: int | None,
    segment_focus_blocks: int | None = None,
) -> int:
    if segment_blocks <= 0:
        raise ValueError("segment_blocks must be >= 1")
    if requested_overlap < 0:
        raise ValueError("requested_overlap must be >= 0")
    if requested_overlap >= segment_blocks:
        raise ValueError("requested_overlap must be smaller than segment_blocks")
    min_overlap_for_focus = 0
    if segment_focus_blocks is not None:
        if segment_focus_blocks < 1:
            raise ValueError("segment_focus_blocks must be >= 1")
        if segment_focus_blocks > segment_blocks:
            raise ValueError("segment_focus_blocks must be <= segment_blocks")
        # Keep focus windows contiguous across tasks: step <= focus.
        min_overlap_for_focus = max(0, segment_blocks - segment_focus_blocks)
    requested_overlap_effective = max(requested_overlap, min_overlap_for_focus)
    if target_task_count is None or total_blocks <= 0:
        return requested_overlap_effective
    if target_task_count < 1:
        raise ValueError("target_task_count must be >= 1")

    requested_count = len(
        _segment_ranges(total_blocks, segment_blocks, requested_overlap_effective)
    )
    prefer_higher_task_count = target_task_count >= requested_count

    best_overlap = requested_overlap_effective
    best_count = requested_count
    best_diff = abs(requested_count - target_task_count)
    best_requested_distance = abs(requested_overlap_effective - requested_overlap)

    for overlap in range(min_overlap_for_focus, segment_blocks):
        count = len(_segment_ranges(total_blocks, segment_blocks, overlap))
        diff = abs(count - target_task_count)
        if diff < best_diff:
            best_overlap = overlap
            best_count = count
            best_diff = diff
            best_requested_distance = abs(overlap - requested_overlap)
            continue
        if diff > best_diff:
            continue

        if prefer_higher_task_count and count > best_count:
            best_overlap = overlap
            best_count = count
            best_requested_distance = abs(overlap - requested_overlap)
            continue
        if not prefer_higher_task_count and count < best_count:
            best_overlap = overlap
            best_count = count
            best_requested_distance = abs(overlap - requested_overlap)
            continue
        if count != best_count:
            continue

        requested_distance = abs(overlap - requested_overlap)
        if requested_distance < best_requested_distance:
            best_overlap = overlap
            best_count = count
            best_requested_distance = requested_distance
            continue
        if requested_distance == best_requested_distance and overlap < best_overlap:
            best_overlap = overlap
            best_count = count
            best_requested_distance = requested_distance

    return best_overlap


def _build_segment_text(
    blocks: list[ArchiveBlock], *, source_hash: str
) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    source_blocks: list[dict[str, Any]] = []
    cursor = 0

    for idx, block in enumerate(blocks):
        text = block.text or ""
        start_offset = cursor
        end_offset = start_offset + len(text)
        source_blocks.append(
            {
                "block_id": build_block_id(source_hash, block.index),
                "block_index": block.index,
                "segment_start": start_offset,
                "segment_end": end_offset,
                "location": block.location,
                "source_kind": block.source_kind,
            }
        )
        parts.append(text)
        cursor = end_offset
        if idx < len(blocks) - 1:
            cursor += len(SEGMENT_SEPARATOR)

    return SEGMENT_SEPARATOR.join(parts), source_blocks


def _build_context_prompt_blocks(
    blocks: Sequence[ArchiveBlock], *, source_hash: str
) -> list[dict[str, Any]]:
    prompt_blocks: list[dict[str, Any]] = []
    for block in blocks:
        prompt_blocks.append(
            {
                "block_id": build_block_id(source_hash, block.index),
                "block_index": block.index,
                "text": block.text or "",
                "location": block.location,
                "source_kind": block.source_kind,
            }
        )
    return prompt_blocks


def build_freeform_span_tasks(
    archive: Iterable[ArchiveBlock | dict[str, Any]],
    source_hash: str,
    source_file: str,
    book_id: str,
    segment_blocks: int,
    segment_overlap: int,
    segment_focus_blocks: int | None = None,
) -> list[dict[str, Any]]:
    if segment_focus_blocks is None:
        segment_focus_blocks = segment_blocks
    if segment_focus_blocks <= 0:
        raise ValueError("segment_focus_blocks must be >= 1")
    if segment_focus_blocks > segment_blocks:
        raise ValueError("segment_focus_blocks must be <= segment_blocks")

    blocks = _coerce_archive(archive)
    ranges = _segment_ranges(len(blocks), segment_blocks, segment_overlap)
    tasks: list[dict[str, Any]] = []

    for segment_index, (start, end) in enumerate(ranges):
        segment_blocks_slice = blocks[start:end]
        if not segment_blocks_slice:
            continue
        focus_start_offset, focus_end_offset = _resolve_focus_slice_bounds(
            segment_length=len(segment_blocks_slice),
            segment_blocks=segment_blocks,
            segment_focus_blocks=segment_focus_blocks,
        )
        start_block_index = segment_blocks_slice[0].index
        end_block_index = segment_blocks_slice[-1].index
        segment_id = build_segment_id(source_hash, start_block_index, end_block_index)
        focus_blocks_slice = segment_blocks_slice[focus_start_offset:focus_end_offset]
        segment_text, source_blocks = _build_segment_text(
            focus_blocks_slice, source_hash=source_hash
        )
        context_before_blocks = _build_context_prompt_blocks(
            segment_blocks_slice[:focus_start_offset],
            source_hash=source_hash,
        )
        context_after_blocks = _build_context_prompt_blocks(
            segment_blocks_slice[focus_end_offset:],
            source_hash=source_hash,
        )
        focus_indices = [block.index for block in focus_blocks_slice]
        context_before_indices = [
            block.index for block in segment_blocks_slice[:focus_start_offset]
        ]
        context_after_indices = [block.index for block in segment_blocks_slice[focus_end_offset:]]
        focus_block_range = _collapse_block_index_ranges(focus_indices)
        context_before_block_range = _collapse_block_index_ranges(context_before_indices)
        context_after_block_range = _collapse_block_index_ranges(context_after_indices)
        if context_before_block_range == "none" and context_after_block_range == "none":
            focus_scope_hint = (
                f"Label all blocks in this task ({focus_block_range}); no extra context-only "
                "blocks are present."
            )
        else:
            focus_scope_hint = (
                f"Label only blocks {focus_block_range}. Context only: "
                f"before {context_before_block_range}; after {context_after_block_range}."
            )
        source_map = {
            "separator": SEGMENT_SEPARATOR,
            "start_block_index": start_block_index,
            "end_block_index": end_block_index,
            "focus_start_block_index": focus_indices[0],
            "focus_end_block_index": focus_indices[-1],
            "focus_block_indices": focus_indices,
            "focus_block_range": focus_block_range,
            "context_before_block_indices": context_before_indices,
            "context_after_block_indices": context_after_indices,
            "context_before_block_range": context_before_block_range,
            "context_after_block_range": context_after_block_range,
            "context_before_blocks": context_before_blocks,
            "context_after_blocks": context_after_blocks,
            "blocks": source_blocks,
        }
        task_data = SegmentTaskData(
            segment_id=segment_id,
            source_hash=source_hash,
            source_file=source_file,
            book_id=book_id,
            segment_index=segment_index,
            segment_text=segment_text,
            source_map=source_map,
            focus_block_range=focus_block_range,
            context_before_block_range=context_before_block_range,
            context_after_block_range=context_after_block_range,
            focus_scope_hint=focus_scope_hint,
        )
        tasks.append(task_data.to_task())

    return tasks


def sample_freeform_tasks(
    tasks: Sequence[dict[str, Any]], *, limit: int | None, sample: int | None
) -> list[dict[str, Any]]:
    if sample is not None and sample > 0:
        rng = random.Random(0)
        if sample >= len(tasks):
            return list(tasks)
        return rng.sample(list(tasks), sample)
    if limit is not None and limit > 0:
        return list(tasks)[:limit]
    return list(tasks)


def map_span_offsets_to_blocks(
    source_map: dict[str, Any], start_offset: int, end_offset: int
) -> list[dict[str, Any]]:
    if end_offset <= start_offset:
        return []
    source_blocks = source_map.get("blocks")
    if not isinstance(source_blocks, list):
        return []

    touched: list[dict[str, Any]] = []
    for item in source_blocks:
        if not isinstance(item, dict):
            continue
        block_start = item.get("segment_start")
        block_end = item.get("segment_end")
        try:
            block_start_i = int(block_start)
            block_end_i = int(block_end)
        except (TypeError, ValueError):
            continue
        if end_offset <= block_start_i or start_offset >= block_end_i:
            continue
        touched.append(item)
    return touched


def compute_freeform_task_coverage(
    archive: Iterable[ArchiveBlock | dict[str, Any]], tasks: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    blocks = _coerce_archive(archive)
    extracted_chars = sum(len(block.text or "") for block in blocks)

    block_text_lengths = {block.index: len(block.text or "") for block in blocks}
    covered_block_indices: set[int] = set()
    for task in tasks:
        data = task.get("data") if isinstance(task, dict) else {}
        if not isinstance(data, dict):
            continue
        source_map = data.get("source_map")
        if not isinstance(source_map, dict):
            continue
        for key in ("blocks", "context_before_blocks", "context_after_blocks"):
            source_blocks = source_map.get(key)
            if not isinstance(source_blocks, list):
                continue
            for item in source_blocks:
                if not isinstance(item, dict):
                    continue
                block_index = item.get("block_index")
                try:
                    covered_block_indices.add(int(block_index))
                except (TypeError, ValueError):
                    continue

    chunked_chars = sum(block_text_lengths.get(index, 0) for index in covered_block_indices)
    warnings: list[str] = []
    if extracted_chars == 0:
        warnings.append("No text extracted; OCR may be required for scanned documents.")
    elif chunked_chars < extracted_chars * 0.9:
        warnings.append(
            f"Chunk coverage low: {chunked_chars} of {extracted_chars} characters represented."
        )

    return {
        "extracted_chars": extracted_chars,
        "chunked_chars": chunked_chars,
        "warnings": warnings,
    }
