from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .manifest import RunManifest, RunSource, write_run_manifest


def build_eval_run_manifest(
    *,
    run_root: Path,
    run_kind: str,
    source_path: str | None,
    source_hash: str | None,
    importer_name: str | None,
    run_config: dict[str, Any],
    artifacts: dict[str, Any],
    notes: str | None = None,
    created_at: str | None = None,
) -> RunManifest:
    created_at_value = created_at or dt.datetime.now().isoformat(timespec="seconds")
    return RunManifest(
        run_kind=run_kind,
        run_id=run_root.name,
        created_at=created_at_value,
        source=RunSource(
            path=source_path,
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes=notes,
    )


def write_eval_run_manifest(
    *,
    run_root: Path,
    run_kind: str,
    source_path: str | None,
    source_hash: str | None,
    importer_name: str | None,
    run_config: dict[str, Any],
    artifacts: dict[str, Any],
    notes: str | None = None,
    created_at: str | None = None,
) -> Path:
    manifest = build_eval_run_manifest(
        run_root=run_root,
        run_kind=run_kind,
        source_path=source_path,
        source_hash=source_hash,
        importer_name=importer_name,
        run_config=run_config,
        artifacts=artifacts,
        notes=notes,
        created_at=created_at,
    )
    return write_run_manifest(run_root, manifest)
