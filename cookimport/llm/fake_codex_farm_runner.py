from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

OutputBuilder = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class FakeCodexFarmRunner:
    """Test runner that writes deterministic codex-farm-shaped output files."""

    output_builders: Mapping[str, OutputBuilder] | None = None
    calls: list[str] = field(default_factory=list)

    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],  # noqa: ARG002 - parity with subprocess runner
    ) -> None:
        self.calls.append(pipeline_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        builder = (self.output_builders or {}).get(pipeline_id)
        for in_path in sorted(in_dir.glob("*.json")):
            payload = json.loads(in_path.read_text(encoding="utf-8"))
            output = builder(payload) if builder is not None else _default_output(pipeline_id, payload)
            out_path = out_dir / in_path.name
            out_path.write_text(
                json.dumps(output, indent=2, sort_keys=True),
                encoding="utf-8",
            )


def _default_output(pipeline_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if pipeline_id == "recipe.chunking.v1":
        return {
            "bundle_version": "1",
            "recipe_id": payload.get("recipe_id"),
            "is_recipe": True,
            "start_block_index": payload.get("heuristic_start_block_index"),
            "end_block_index": payload.get("heuristic_end_block_index"),
            "title": None,
            "reasoning_tags": ["fake-runner"],
            "excluded_block_ids": [],
        }
    if pipeline_id == "recipe.schemaorg.v1":
        canonical_text = str(payload.get("canonical_text") or "").strip()
        first_line = canonical_text.splitlines()[0].strip() if canonical_text else ""
        recipe_name = first_line or str(payload.get("recipe_id") or "Untitled Recipe")
        return {
            "bundle_version": "1",
            "recipe_id": payload.get("recipe_id"),
            "schemaorg_recipe": {
                "@context": "http://schema.org",
                "@type": "Recipe",
                "name": recipe_name,
            },
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": {},
            "warnings": [],
        }
    if pipeline_id == "recipe.final.v1":
        return {
            "bundle_version": "1",
            "recipe_id": payload.get("recipe_id"),
            "draft_v1": {
                "schema_v": 1,
                "source": None,
                "recipe": {"title": str(payload.get("recipe_id") or "Untitled Recipe")},
                "steps": [
                    {
                        "instruction": "See original recipe for details.",
                        "ingredient_lines": [],
                    }
                ],
            },
            "ingredient_step_mapping": {},
            "warnings": [],
        }
    raise ValueError(f"Unsupported fake pipeline id: {pipeline_id}")
