from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .codex_farm_runner import CodexFarmPipelineRunResult
from .codex_farm_knowledge_contracts import (
    knowledge_input_block_index,
    knowledge_input_block_text,
    knowledge_input_blocks,
    knowledge_input_bundle_id,
)
from .knowledge_tag_catalog import load_knowledge_tag_catalog
from .recipe_tagging_guide import build_recipe_tagging_guide, recipe_tagging_guide_categories

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
        if (
            str(payload.get("stage_key") or "").strip() == "recipe_refine"
            and payload.get("recipe_id") is not None
            and "source_text" in payload
        ):
            return _default_recipe_refine_task_output(payload)
        recipes_payload = payload.get("recipes", payload.get("r"))
        shard_id = payload.get("shard_id", payload.get("sid"))
        if isinstance(recipes_payload, list):
            return {
                "v": "1",
                "sid": shard_id,
                "r": [
                    _default_recipe_correction_output(recipe_payload)
                    for recipe_payload in recipes_payload
                    if isinstance(recipe_payload, dict)
                ],
            }
        return _default_recipe_correction_output(payload)
    if pipeline_id in {
        "recipe.knowledge.v1",
        "recipe.knowledge.compact.v1",
        "recipe.knowledge.packet.v1",
    }:
        if not isinstance(payload, dict):
            raise ValueError("knowledge fake payload must be a JSON object")
        stage_key = str(payload.get("stage_key") or "").strip()
        if stage_key == "nonrecipe_classify" and isinstance(payload.get("rows"), list):
            return _default_structured_knowledge_classification_output(payload)
        if stage_key == "knowledge_group" and isinstance(payload.get("rows"), list):
            return _default_structured_knowledge_grouping_output(payload)
        if (
            stage_key in {"nonrecipe_finalize", "nonrecipe_classify"}
            and payload.get("block_index") is not None
        ):
            return _default_knowledge_classification_task_output(payload)
        if stage_key == "knowledge_group" and payload.get("block_index") is not None:
            return _default_knowledge_grouping_task_output(payload)
        blocks = knowledge_input_blocks(payload)
        first_block = blocks[0] if isinstance(blocks, list) and blocks else {}
        block_index = knowledge_input_block_index(first_block) or 0
        block_text = knowledge_input_block_text(first_block).strip()
        catalog = load_knowledge_tag_catalog()
        candidate_tag_keys = catalog.candidate_tag_keys_for_text(block_text)
        return {
            "packet_id": knowledge_input_bundle_id(payload),
            "block_decisions": [
                {
                    "block_index": int(knowledge_input_block_index(block) or 0),
                    "category": "knowledge",
                    "grounding": {
                        "tag_keys": candidate_tag_keys[:1],
                        "category_keys": [],
                        "proposed_tags": (
                            []
                            if candidate_tag_keys
                            else [
                                {
                                    "key": "fake-knowledge-concept",
                                    "display_name": "Fake Knowledge Concept",
                                    "category_key": "techniques",
                                }
                            ]
                        ),
                    },
                }
                for block in blocks
                if isinstance(block, dict)
            ],
            "idea_groups": [
                {
                    "group_id": "g01",
                    "topic_label": "Fake knowledge group",
                    "block_indices": [
                        int(knowledge_input_block_index(block) or 0)
                        for block in blocks
                        if isinstance(block, dict)
                    ],
                }
            ],
        }
    if pipeline_id == "line-role.canonical.v1":
        if isinstance(payload, dict) and (
            isinstance(payload.get("structured_packet_rows"), list)
            or isinstance(payload.get("rows"), list)
        ):
            return _default_structured_line_role_output(payload)
        if (
            isinstance(payload, dict)
            and str(payload.get("stage_key") or "").strip() == "line_role"
            and payload.get("atomic_index") is not None
        ):
            return {"label": "RECIPE_NOTES"}
        atomic_indices = _extract_atomic_indices(payload)
        return {
            "rows": [
                {"atomic_index": atomic_index, "label": "RECIPE_NOTES"}
                for atomic_index in atomic_indices
            ]
        }
    raise ValueError(f"Unsupported fake pipeline id: {pipeline_id}")


def _structured_knowledge_row_id(row: Mapping[str, Any]) -> str:
    return str(row.get("row_id") or "").strip()


def _structured_knowledge_row_text(row: Mapping[str, Any]) -> str:
    return str(row.get("text") or "").strip()


def _default_structured_knowledge_classification_output(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    catalog = load_knowledge_tag_catalog()
    rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, Mapping)]
    return {
        "rows": [
            {
                "row_id": _structured_knowledge_row_id(row),
                "category": "knowledge",
                "grounding": {
                    "tag_keys": catalog.candidate_tag_keys_for_text(
                        _structured_knowledge_row_text(row)
                    )[:1],
                    "category_keys": [],
                    "proposed_tags": (
                        []
                        if catalog.candidate_tag_keys_for_text(
                            _structured_knowledge_row_text(row)
                        )
                        else [
                            {
                                "key": "fake-knowledge-concept",
                                "display_name": "Fake Knowledge Concept",
                                "category_key": "techniques",
                            }
                        ]
                    ),
                },
            }
            for row in rows
        ]
    }


def _default_structured_knowledge_grouping_output(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, Mapping)]
    return {
        "rows": [
            {
                "row_id": _structured_knowledge_row_id(row),
                "group_key": "heat-control",
                "topic_label": "Fake knowledge group",
            }
            for row in rows
        ]
    }


def _default_structured_line_role_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (
            payload.get("structured_packet_rows")
            or payload.get("rows")
            or []
        )
        if isinstance(row, Mapping)
    ]
    output_rows: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            continue
        output_rows.append({"row_id": row_id, "label": "RECIPE_NOTES"})
    return {"rows": output_rows}


def build_structural_pipeline_output(
    pipeline_id: str,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    """Return the repo's structural best-guess output shape for a pipeline payload."""
    return _default_output(pipeline_id, payload)


def _extract_atomic_indices(payload: dict[str, Any] | str) -> list[int]:
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            indices: list[int] = []
            for row in rows:
                value = None
                if isinstance(row, dict):
                    value = row.get("atomic_index")
                elif isinstance(row, list | tuple) and row:
                    value = row[0]
                if value is None:
                    continue
                indices.append(int(value))
            if indices:
                return indices

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
    if not atomic_indices:
        atomic_indices = [
            int(value)
            for value in re.findall(r"(?m)^(\d+)\|", prompt_text)
        ]
    return atomic_indices


def _default_recipe_correction_output(payload: dict[str, Any]) -> dict[str, Any]:
    canonical_text = str(payload.get("canonical_text", payload.get("txt")) or "").strip()
    evidence_rows = payload.get("evidence_rows", payload.get("ev"))
    recipe_hint = payload.get("recipe_candidate_hint", payload.get("h")) or {}
    first_line = canonical_text.splitlines()[0].strip() if canonical_text else ""
    if not first_line and isinstance(evidence_rows, list):
        for row in evidence_rows:
            if not isinstance(row, list | tuple) or len(row) < 2:
                continue
            first_line = str(row[1] or "").strip()
            if first_line:
                break
    recipe_name = (
        str((recipe_hint or {}).get("n") or (recipe_hint or {}).get("name") or "").strip()
        or first_line
        or str(payload.get("recipe_id", payload.get("rid")) or "Untitled Recipe")
    )
    recipe_lines = [line.strip() for line in canonical_text.splitlines() if line.strip()]
    if len(recipe_lines) <= 1 and isinstance(evidence_rows, list):
        recipe_lines = [
            str(row[1] or "").strip()
            for row in evidence_rows
            if isinstance(row, list | tuple) and len(row) >= 2 and str(row[1] or "").strip()
        ]
    body_lines = recipe_lines[1:] if len(recipe_lines) > 1 else recipe_lines[:]
    ingredients = list((recipe_hint or {}).get("i") or (recipe_hint or {}).get("recipeIngredient") or body_lines[:1])
    steps = list((recipe_hint or {}).get("s") or (recipe_hint or {}).get("recipeInstructions") or (body_lines[1:] if len(body_lines) > 1 else body_lines[:1]))
    selected_tags = _select_recipe_tags(payload)
    return {
        "v": "1",
        "rid": payload.get("recipe_id", payload.get("rid")),
        "st": "repaired",
        "sr": None,
        "cr": {
            "t": recipe_name,
            "d": None,
            "y": None,
            "i": ingredients,
            "s": steps,
        },
        "m": [],
        "mr": "unclear_alignment",
        "db": [],
        "g": selected_tags,
        "w": [],
    }


def _default_recipe_refine_task_output(payload: dict[str, Any]) -> dict[str, Any]:
    recipe_hint = payload.get("hint") or {}
    if not isinstance(recipe_hint, dict):
        recipe_hint = {}
    ingredient_count = len(
        [item for item in recipe_hint.get("ingredients", []) if str(item or "").strip()]
    )
    step_count = len(
        [item for item in recipe_hint.get("steps", []) if str(item or "").strip()]
    )
    if step_count <= 1:
        mapping_reason = "not_needed_single_step"
    elif ingredient_count <= 1:
        mapping_reason = "not_needed_single_ingredient"
    else:
        mapping_reason = "unclear_alignment"
    return {
        "status": "repaired",
        "status_reason": None,
        "canonical_recipe": {
            "title": recipe_hint.get("title"),
            "ingredients": list(recipe_hint.get("ingredients") or []),
            "steps": list(recipe_hint.get("steps") or []),
            "description": None,
            "recipe_yield": None,
        },
        "ingredient_step_mapping": [],
        "ingredient_step_mapping_reason": mapping_reason,
        "divested_block_indices": [],
        "selected_tags": [
            {
                "category": tag.get("c"),
                "label": tag.get("l"),
                "confidence": tag.get("f"),
            }
            for tag in _select_recipe_tags(payload)
            if isinstance(tag, dict)
        ],
        "warnings": [],
    }


def _default_knowledge_classification_task_output(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    catalog = load_knowledge_tag_catalog()
    candidate_tag_keys = [
        str(value).strip()
        for value in (payload.get("candidate_tag_keys") or [])
        if str(value).strip()
    ]
    if not candidate_tag_keys:
        candidate_tag_keys = catalog.candidate_tag_keys_for_text(text)
    if candidate_tag_keys:
        return {
            "category": "knowledge",
            "grounding": {
                "tag_keys": candidate_tag_keys[:1],
                "category_keys": [],
                "proposed_tags": [],
            },
        }
    return {
        "category": "knowledge",
        "grounding": {
            "tag_keys": [],
            "category_keys": [],
            "proposed_tags": [
                {
                    "key": "heat-control",
                    "display_name": "Heat control",
                    "category_key": "techniques",
                }
            ],
        },
    }


def _default_knowledge_grouping_task_output(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip().lower()
    if "heat" in text:
        return {
            "group_key": "heat-control",
            "topic_label": "Heat control",
        }
    return {
        "group_key": "fake-knowledge-group",
        "topic_label": "Fake knowledge group",
    }


def _select_recipe_tags(payload: dict[str, Any]) -> list[dict[str, Any]]:
    guide = payload.get("tagging_guide", payload.get("tg"))
    if not isinstance(guide, dict):
        guide = build_recipe_tagging_guide()
    categories = recipe_tagging_guide_categories(guide)
    if not categories:
        return []

    recipe_hint = payload.get("recipe_candidate_hint", payload.get("h")) or {}
    combined_text = " ".join(
        [
            str(payload.get("canonical_text", payload.get("txt")) or ""),
            json.dumps(recipe_hint, sort_keys=True),
        ]
    ).lower()
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for category in categories:
        key = str(category.get("key") or "").strip()
        examples = category.get("examples")
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
            selected.append({"c": key, "l": rendered, "f": 0.74})
            break
    return selected
