from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArchiveBlock:
    index: int
    text: str
    location: dict[str, Any] = field(default_factory=dict)
    source_kind: str | None = None


@dataclass
class ChunkRecord:
    chunk_id: str
    chunk_level: str
    chunk_type: str
    text_raw: str
    text_display: str
    source_file: str
    book_id: str
    pipeline_used: str
    location: dict[str, Any] = field(default_factory=dict)
    context_before: str | None = None
    context_after: str | None = None
    chunk_type_hint: str | None = None
    text_hash: str | None = None


@dataclass
class CoverageReport:
    extracted_chars: int
    chunked_chars: int
    warnings: list[str] = field(default_factory=list)
