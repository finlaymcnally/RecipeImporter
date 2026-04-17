from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .knowledge_tag_catalog import load_knowledge_tag_catalog

_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "recipe.knowledge.packet.v1.prompt.md"
)

_INPUT_JSON_START = "<BEGIN_INPUT_JSON>"
_INPUT_JSON_END = "<END_INPUT_JSON>"


def _compact_owned_row(row: Mapping[str, Any], *, ordinal: int) -> str:
    row_id = f"r{ordinal + 1:02d}"
    row_index = int(row.get("i", row.get("row_index")) or 0)
    text = str(row.get("t", row.get("text")) or "")
    return f"{row_id} | {row_index} | {text}"


def _compact_context_row(row: Mapping[str, Any]) -> str:
    row_index = int(row.get("i", row.get("row_index")) or 0)
    text = str(row.get("t", row.get("text")) or "")
    return f"{row_index} | {text}"


def _compact_prompt_payload(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(input_payload)
    compact_payload: dict[str, Any] = {
        "v": payload.get("v"),
        "bid": str(payload.get("bid") or payload.get("packet_id") or "").strip(),
        "rows": [
            _compact_owned_row(row, ordinal=index)
            for index, row in enumerate(payload.get("b") or [])
            if isinstance(row, Mapping)
        ],
    }
    context = dict(payload.get("x") or {}) if isinstance(payload.get("x"), Mapping) else {}
    context_before_rows = [
        _compact_context_row(row)
        for row in (context.get("p") or [])
        if isinstance(row, Mapping)
    ]
    if context_before_rows:
        compact_payload["context_before_rows"] = context_before_rows
    context_after_rows = [
        _compact_context_row(row)
        for row in (context.get("n") or [])
        if isinstance(row, Mapping)
    ]
    if context_after_rows:
        compact_payload["context_after_rows"] = context_after_rows
    guardrails = dict(payload.get("g") or {}) if isinstance(payload.get("g"), Mapping) else {}
    recipe_neighbor_row_indices = [
        int(value)
        for value in (guardrails.get("r") or [])
        if value is not None
    ]
    if recipe_neighbor_row_indices:
        compact_payload["recipe_neighbor_row_indices"] = recipe_neighbor_row_indices
    if isinstance(payload.get("ontology"), Mapping):
        compact_payload["ontology"] = dict(payload["ontology"])
    return compact_payload


def build_knowledge_direct_prompt(input_payload: Mapping[str, Any]) -> str:
    rendered_input = _compact_prompt_payload(input_payload)
    rendered_input.setdefault("ontology", load_knowledge_tag_catalog().task_scope_payload())
    template_text = (
        _load_template_text()
        .replace("{{INPUT_PATH}}", "<BEGIN_INPUT_JSON>...<END_INPUT_JSON>")
        .strip()
    )
    serialized_input = json.dumps(
        rendered_input,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        f"{template_text}\n\n"
        "Use the following JSON as the complete and only task input. "
        "Do not run shell commands or inspect files.\n\n"
        f"{_INPUT_JSON_START}\n"
        f"{serialized_input}\n"
        f"{_INPUT_JSON_END}\n"
    )


def extract_knowledge_prompt_input_payload(prompt_text: str) -> dict[str, Any] | None:
    text = str(prompt_text or "")
    start = text.find(_INPUT_JSON_START)
    end = text.find(_INPUT_JSON_END)
    if start < 0 or end < 0 or end <= start:
        return None
    raw_payload = text[start + len(_INPUT_JSON_START) : end].strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _load_template_text() -> str:
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
