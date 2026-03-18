from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .codex_farm_runner import CodexFarmPipelineRunResult
from .recipe_tagging_guide import build_recipe_tagging_guide

OutputBuilder = Callable[[dict[str, Any] | str], dict[str, Any]]


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
        runtime_mode: str | None = None,  # noqa: ARG002 - parity with subprocess runner
        process_worker_count: int | None = None,  # noqa: ARG002 - parity with subprocess runner
    ) -> CodexFarmPipelineRunResult:
        self.calls.append(pipeline_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        builder = (self.output_builders or {}).get(pipeline_id)
        for in_path in sorted(in_dir.glob("*.json")):
            raw_text = in_path.read_text(encoding="utf-8")
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                payload = raw_text
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
            runtime_mode_audit=(
                {"mode": runtime_mode, "status": "ok"}
                if runtime_mode
                else None
            ),
        )


def _default_output(pipeline_id: str, payload: dict[str, Any] | str) -> dict[str, Any]:
    if pipeline_id == "recipe.correction.compact.v1":
        if not isinstance(payload, dict):
            raise ValueError("recipe correction fake payload must be a JSON object")
        if isinstance(payload.get("recipes"), list):
            return {
                "bundle_version": "1",
                "shard_id": payload.get("shard_id"),
                "recipes": [
                    _default_recipe_correction_output(recipe_payload)
                    for recipe_payload in payload.get("recipes") or []
                    if isinstance(recipe_payload, dict)
                ],
            }
        return _default_recipe_correction_output(payload)
    if pipeline_id in {"recipe.knowledge.v1", "recipe.knowledge.compact.v1"}:
        if not isinstance(payload, dict):
            raise ValueError("knowledge fake payload must be a JSON object")
        chunks = payload.get("chunks") or []
        chunk_results = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = chunk.get("chunk_id")
            chunk_blocks = chunk.get("blocks") or []
            first_block = (
                chunk_blocks[0] if isinstance(chunk_blocks, list) and chunk_blocks else {}
            )
            block_index = first_block.get("block_index", 0)
            block_text = str(first_block.get("text") or "").strip()
            quote = block_text[:80].strip() or "evidence"
            chunk_results.append(
                {
                    "cid": chunk_id,
                    "u": True,
                    "d": [
                        {
                            "i": int(block.get("block_index", 0)),
                            "c": "knowledge",
                        }
                        for block in chunk_blocks
                        if isinstance(block, dict)
                    ],
                    "s": [
                        {
                            "t": None,
                            "b": "Fake knowledge snippet.",
                            "g": ["fake-runner"],
                            "e": [
                                {
                                    "i": block_index,
                                    "q": quote,
                                }
                            ],
                        }
                    ],
                }
            )
        return {
            "v": "2",
            "bid": payload.get("bundle_id"),
            "r": chunk_results,
        }
    if pipeline_id == "line-role.canonical.v1":
        prompt_text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
        atomic_indices = [
            int(value)
            for value in re.findall(r'"atomic_index"\s*:\s*(\d+)', prompt_text)
        ]
        if not atomic_indices:
            atomic_indices = [
                int(value)
                for value in re.findall(r"(?m)^\[(\d+),", prompt_text)
            ]
        return {
            "rows": [
                {"atomic_index": atomic_index, "label": "OTHER"}
                for atomic_index in atomic_indices
            ]
        }
    raise ValueError(f"Unsupported fake pipeline id: {pipeline_id}")


def build_structural_pipeline_output(
    pipeline_id: str,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    """Return the repo's structural best-guess output shape for a pipeline payload."""
    return _default_output(pipeline_id, payload)


def _default_recipe_correction_output(payload: dict[str, Any]) -> dict[str, Any]:
    canonical_text = str(payload.get("canonical_text") or "").strip()
    evidence_rows = payload.get("evidence_rows")
    first_line = canonical_text.splitlines()[0].strip() if canonical_text else ""
    if not first_line and isinstance(evidence_rows, list):
        for row in evidence_rows:
            if not isinstance(row, list | tuple) or len(row) < 2:
                continue
            first_line = str(row[1] or "").strip()
            if first_line:
                break
    recipe_name = first_line or str(payload.get("recipe_id") or "Untitled Recipe")
    recipe_lines = [line.strip() for line in canonical_text.splitlines() if line.strip()]
    if len(recipe_lines) <= 1 and isinstance(evidence_rows, list):
        recipe_lines = [
            str(row[1] or "").strip()
            for row in evidence_rows
            if isinstance(row, list | tuple) and len(row) >= 2 and str(row[1] or "").strip()
        ]
    body_lines = recipe_lines[1:] if len(recipe_lines) > 1 else recipe_lines[:]
    ingredients = body_lines[:1]
    steps = body_lines[1:] if len(body_lines) > 1 else body_lines[:1]
    selected_tags = _select_recipe_tags(payload)
    return {
        "bundle_version": "1",
        "recipe_id": payload.get("recipe_id"),
        "canonical_recipe": {
            "title": recipe_name,
            "description": None,
            "recipeYield": None,
            "ingredients": ingredients,
            "steps": steps,
        },
        "ingredient_step_mapping": [],
        "ingredient_step_mapping_reason": "unclear_alignment",
        "selected_tags": selected_tags,
        "warnings": [],
    }


def _select_recipe_tags(payload: dict[str, Any]) -> list[dict[str, Any]]:
    guide = payload.get("tagging_guide")
    if not isinstance(guide, dict):
        guide = build_recipe_tagging_guide()
    categories = guide.get("categories")
    if not isinstance(categories, list):
        return []

    combined_text = " ".join(
        [
            str(payload.get("canonical_text") or ""),
            json.dumps(payload.get("recipe_candidate_hint") or {}, sort_keys=True),
        ]
    ).lower()
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for category in categories:
        if not isinstance(category, dict):
            continue
        key = str(category.get("key") or "").strip()
        examples = category.get("examples")
        if not key or not isinstance(examples, list):
            continue
        for example in examples:
            rendered = str(example or "").strip()
            if not rendered:
                continue
            tokens = {token.strip().lower() for token in rendered.replace("-", " ").split() if token.strip()}
            if not any(len(token) >= 3 and token in combined_text for token in tokens):
                continue
            candidate = (key, rendered.lower())
            if candidate in seen:
                continue
            seen.add(candidate)
            selected.append(
                {
                    "category": key,
                    "label": rendered,
                    "confidence": 0.74,
                }
            )
            break
    return selected
