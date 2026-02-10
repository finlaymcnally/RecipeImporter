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


def build_freeform_span_tasks(
    archive: Iterable[ArchiveBlock | dict[str, Any]],
    source_hash: str,
    source_file: str,
    book_id: str,
    segment_blocks: int,
    segment_overlap: int,
) -> list[dict[str, Any]]:
    blocks = _coerce_archive(archive)
    ranges = _segment_ranges(len(blocks), segment_blocks, segment_overlap)
    tasks: list[dict[str, Any]] = []

    for segment_index, (start, end) in enumerate(ranges):
        segment_blocks_slice = blocks[start:end]
        if not segment_blocks_slice:
            continue
        start_block_index = segment_blocks_slice[0].index
        end_block_index = segment_blocks_slice[-1].index
        segment_id = build_segment_id(source_hash, start_block_index, end_block_index)
        segment_text, source_blocks = _build_segment_text(
            segment_blocks_slice, source_hash=source_hash
        )
        source_map = {
            "separator": SEGMENT_SEPARATOR,
            "start_block_index": start_block_index,
            "end_block_index": end_block_index,
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
        source_blocks = source_map.get("blocks")
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
