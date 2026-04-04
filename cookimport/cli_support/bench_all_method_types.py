from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings


@dataclass(frozen=True)
class AllMethodTarget:
    gold_spans_path: Path
    source_file: Path
    source_file_name: str
    gold_display: str


@dataclass(frozen=True)
class AllMethodUnmatchedGold:
    gold_spans_path: Path
    reason: str
    source_hint: str | None
    gold_display: str


@dataclass(frozen=True)
class AllMethodVariant:
    slug: str
    run_settings: RunSettings
    dimensions: dict[str, Any]


@dataclass(frozen=True)
class _AllMethodSourceEstimate:
    estimated_seconds: float
    estimate_basis: str
    canonical_text_chars: int
    variant_count: int


@dataclass(frozen=True)
class _AllMethodSourceJobPlan:
    source_position: int
    source_group_key: str
    source_display_name: str
    source_slug: str
    source_file: Path
    gold_spans_path: Path
    variants: list[AllMethodVariant]
    shard_index: int
    shard_total: int
    estimated_seconds: float
    estimate_basis: str


@dataclass(frozen=True)
class _AllMethodGlobalWorkItem:
    global_dispatch_index: int
    source_position: int
    source_group_key: str
    source_slug: str
    source_file: Path
    source_file_name: str
    gold_spans_path: Path
    source_root: Path
    source_processed_root: Path
    canonical_alignment_cache_dir: Path
    config_index: int
    config_total: int
    source_shard_index: int
    source_shard_total: int
    source_estimated_seconds: float
    source_estimate_basis: str
    variant: AllMethodVariant
