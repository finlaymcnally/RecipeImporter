from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
import json
import random

from cookimport.labelstudio.models import ArchiveBlock


def build_block_id(source_hash: str, block_index: int) -> str:
    return f"urn:cookimport:block:{source_hash}:{block_index}"


@dataclass(frozen=True)
class BlockTaskData:
    block_id: str
    source_hash: str
    source_file: str
    block_index: int
    block_text: str
    context_before: str
    context_after: str
    location: dict[str, Any]
    source_kind: str | None = None

    def to_task(self) -> dict[str, Any]:
        return {
            "data": {
                "block_id": self.block_id,
                "source_hash": self.source_hash,
                "source_file": self.source_file,
                "block_index": self.block_index,
                "block_text": self.block_text,
                "context_before": self.context_before,
                "context_after": self.context_after,
                "location": self.location,
                "source_kind": self.source_kind,
            }
        }


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
            location = {k: v for k, v in item.items() if k not in {"text", "index"}}
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


def build_block_tasks(
    archive: Iterable[ArchiveBlock | dict[str, Any]],
    source_hash: str,
    source_file: str,
    context_window: int,
) -> list[dict[str, Any]]:
    if context_window < 0:
        raise ValueError("context_window must be >= 0")
    blocks = _coerce_archive(archive)
    tasks: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        before_blocks = blocks[max(0, idx - context_window) : idx]
        after_blocks = blocks[idx + 1 : idx + 1 + context_window]
        context_before = "\n".join(b.text for b in before_blocks if b.text)
        context_after = "\n".join(b.text for b in after_blocks if b.text)
        block_id = build_block_id(source_hash, block.index)
        task_data = BlockTaskData(
            block_id=block_id,
            source_hash=source_hash,
            source_file=source_file,
            block_index=block.index,
            block_text=block.text,
            context_before=context_before,
            context_after=context_after,
            location=block.location,
            source_kind=block.source_kind,
        )
        tasks.append(task_data.to_task())
    return tasks


def sample_block_tasks(
    tasks: Sequence[dict[str, Any]],
    *,
    limit: int | None,
    sample: int | None,
) -> list[dict[str, Any]]:
    if sample is not None and sample > 0:
        rng = random.Random(0)
        if sample >= len(tasks):
            return list(tasks)
        return rng.sample(list(tasks), sample)
    if limit is not None and limit > 0:
        return list(tasks)[:limit]
    return list(tasks)


def load_task_ids_from_jsonl(path: Path, data_key: str) -> set[str]:
    if not path.exists():
        return set()
    task_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        task_id = data.get(data_key)
        if task_id:
            task_ids.add(str(task_id))
    return task_ids
