from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .codex_farm_runner import CodexFarmPipelineRunResult

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
        *,
        root_dir: Path | None = None,  # noqa: ARG002 - parity with subprocess runner
        workspace_root: Path | None = None,  # noqa: ARG002 - parity with subprocess runner
        model: str | None = None,  # noqa: ARG002 - parity with subprocess runner
        reasoning_effort: str | None = None,  # noqa: ARG002 - parity with subprocess runner
    ) -> CodexFarmPipelineRunResult:
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
        return CodexFarmPipelineRunResult(
            pipeline_id=pipeline_id,
            run_id=None,
            subprocess_exit_code=0,
            process_exit_code=0,
            output_schema_path=None,
            process_payload=None,
            telemetry_report=None,
            autotune_report=None,
            telemetry=None,
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
            "schemaorg_recipe": json.dumps(
                {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": recipe_name,
                },
                sort_keys=True,
            ),
            "extracted_ingredients": [],
            "extracted_instructions": [],
            "field_evidence": "{}",
            "warnings": [],
        }
    if pipeline_id == "recipe.final.v1":
        return {
            "bundle_version": "1",
            "recipe_id": payload.get("recipe_id"),
            "draft_v1": json.dumps(
                {
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
                sort_keys=True,
            ),
            "ingredient_step_mapping": "{}",
            "warnings": [],
        }
    if pipeline_id == "recipe.knowledge.v1":
        chunk = payload.get("chunk") or {}
        chunk_id = chunk.get("chunk_id")
        chunk_blocks = chunk.get("blocks") or []
        first_block = chunk_blocks[0] if isinstance(chunk_blocks, list) and chunk_blocks else {}
        block_index = first_block.get("block_index", 0)
        block_text = str(first_block.get("text") or "").strip()
        quote = block_text[:80].strip() or "evidence"
        return {
            "bundle_version": "1",
            "chunk_id": chunk_id,
            "is_useful": True,
            "snippets": [
                {
                    "title": None,
                    "body": "Fake knowledge snippet.",
                    "tags": ["fake-runner"],
                    "evidence": [
                        {
                            "block_index": block_index,
                            "quote": quote,
                        }
                    ],
                }
            ],
        }
    if pipeline_id == "recipe.tags.v1":
        recipe_id = str(payload.get("recipe_id") or "").strip() or "recipe"
        missing_categories = payload.get("missing_categories") or []
        candidates_by_category = payload.get("candidates_by_category") or {}
        combined_text = " ".join(
            [
                str(payload.get("title") or ""),
                str(payload.get("description") or ""),
                str(payload.get("notes") or ""),
                " ".join(str(line) for line in (payload.get("ingredients") or [])),
                " ".join(str(line) for line in (payload.get("instructions") or [])),
            ]
        ).lower()
        selected_tags: list[dict[str, Any]] = []
        for category in missing_categories:
            candidates = candidates_by_category.get(category) or []
            chosen = _choose_tag_candidate(candidates, combined_text=combined_text)
            if chosen is None:
                continue
            selected_tags.append(
                {
                    "tag_key_norm": chosen["tag_key_norm"],
                    "category_key_norm": str(category),
                    "confidence": 0.74,
                    "evidence": chosen["evidence"],
                }
            )
        return {
            "bundle_version": "1",
            "recipe_id": recipe_id,
            "selected_tags": selected_tags,
            "new_tag_proposals": [],
        }
    raise ValueError(f"Unsupported fake pipeline id: {pipeline_id}")


def _choose_tag_candidate(
    candidates: list[dict[str, Any]],
    *,
    combined_text: str,
) -> dict[str, str] | None:
    for candidate in candidates:
        tag_key = str(candidate.get("tag_key_norm") or "").strip()
        display_name = str(candidate.get("display_name") or "").strip()
        if not tag_key:
            continue
        evidence_hint = display_name or tag_key
        keywords = {
            token.strip().lower()
            for token in evidence_hint.replace("-", " ").split()
            if token.strip()
        }
        for keyword in keywords:
            if len(keyword) >= 3 and keyword in combined_text:
                return {
                    "tag_key_norm": tag_key,
                    "evidence": f"Matched keyword '{keyword}' in recipe text.",
                }
    if candidates:
        first = candidates[0]
        tag_key = str(first.get("tag_key_norm") or "").strip()
        if tag_key:
            return {
                "tag_key_norm": tag_key,
                "evidence": "Fallback to first shortlist candidate.",
            }
    return None
