from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunSource(BaseModel):
    """Source identity used to tie related outputs together."""

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    source_hash: str | None = None
    importer_name: str | None = None


class RunManifest(BaseModel):
    """Small, stable manifest that explains what a run produced."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_kind: str
    run_id: str
    created_at: str
    source: RunSource | None = None
    run_config: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


def write_run_manifest(run_root: Path, manifest: RunManifest) -> Path:
    """Atomically write ``run_manifest.json`` under ``run_root``."""
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "run_manifest.json"
    tmp_path = run_root / "run_manifest.json.tmp"
    payload = manifest.model_dump(exclude_none=True)
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(manifest_path)
    return manifest_path


def load_run_manifest(path: Path) -> RunManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest payload must be an object: {path}")
    return RunManifest.model_validate(payload)
