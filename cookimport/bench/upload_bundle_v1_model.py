from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UploadBundleSourceModel:
    """Topology-neutral semantic input used by upload_bundle_v1 rendering."""

    source_root: Path
    run_index_payload: dict[str, Any]
    comparison_summary_payload: dict[str, Any]
    process_manifest_payload: dict[str, Any]
    per_recipe_payload: dict[str, Any]
    starter_manifest_payload: dict[str, Any]
    starter_pack_present: bool
    run_rows: list[dict[str, Any]]
    comparison_pairs: list[dict[str, Any]]
    changed_line_rows: list[dict[str, Any]]
    pair_breakdown_rows: list[dict[str, Any]]
    recipe_triage_rows: list[dict[str, Any]]
    call_inventory_rows: list[dict[str, Any]]
    selected_packets: list[dict[str, Any]]
    run_dir_by_id: dict[str, Path]
    run_dirs_by_id: dict[str, list[Path]]
    run_dir_by_output_subdir: dict[str, Path]
    discovered_run_dirs: list[Path]
    advertised_counts: dict[str, int | None]
    topology: dict[str, Any] = field(default_factory=dict)
    diagnostic_families: dict[str, str] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)
