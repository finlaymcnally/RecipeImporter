"""Bench suite models and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class BenchItem(BaseModel):
    """A single benchmark item mapping a source file to its gold export."""

    item_id: str
    source_path: str  # repo-relative
    gold_dir: str  # repo-relative path to dir containing exports/
    force_source_match: bool = False
    notes: str | None = None


class BenchSuite(BaseModel):
    """A collection of benchmark items."""

    name: str
    items: list[BenchItem]


def load_suite(path: Path) -> BenchSuite:
    """Load a bench suite from a JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BenchSuite(**payload)


def validate_suite(suite: BenchSuite, repo_root: Path) -> list[str]:
    """Validate that suite references exist on disk. Returns list of errors."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    if not suite.items:
        errors.append("Suite has no items.")

    for item in suite.items:
        if item.item_id in seen_ids:
            errors.append(f"Duplicate item_id: {item.item_id}")
        seen_ids.add(item.item_id)

        source = repo_root / item.source_path
        if not source.exists():
            errors.append(f"[{item.item_id}] Source file not found: {item.source_path}")

        gold_dir = repo_root / item.gold_dir
        span_labels = gold_dir / "exports" / "freeform_span_labels.jsonl"
        if not span_labels.exists():
            errors.append(
                f"[{item.item_id}] Gold span labels not found: "
                f"{item.gold_dir}/exports/freeform_span_labels.jsonl"
            )

        segment_manifest = gold_dir / "exports" / "freeform_segment_manifest.jsonl"
        if not segment_manifest.exists():
            errors.append(
                f"[{item.item_id}] Gold segment manifest not found: "
                f"{item.gold_dir}/exports/freeform_segment_manifest.jsonl"
            )

    return errors
