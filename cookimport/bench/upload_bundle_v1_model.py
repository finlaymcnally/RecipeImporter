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

    def as_context_dict(self) -> dict[str, Any]:
        """Compatibility view for legacy script internals."""

        return {
            "run_index_payload": self.run_index_payload,
            "comparison_summary_payload": self.comparison_summary_payload,
            "process_manifest_payload": self.process_manifest_payload,
            "per_recipe_payload": self.per_recipe_payload,
            "starter_manifest_payload": self.starter_manifest_payload,
            "starter_pack_present": self.starter_pack_present,
            "run_rows": self.run_rows,
            "comparison_pairs": self.comparison_pairs,
            "changed_line_rows": self.changed_line_rows,
            "pair_breakdown_rows": self.pair_breakdown_rows,
            "recipe_triage_rows": self.recipe_triage_rows,
            "call_inventory_rows": self.call_inventory_rows,
            "selected_packets": self.selected_packets,
            "run_dir_by_id": self.run_dir_by_id,
            "run_dirs_by_id": self.run_dirs_by_id,
            "run_dir_by_output_subdir": self.run_dir_by_output_subdir,
            "discovered_run_dirs": self.discovered_run_dirs,
            "advertised_counts": self.advertised_counts,
            "topology": self.topology,
            "diagnostic_families": self.diagnostic_families,
            "adapter_metadata": self.adapter_metadata,
        }
