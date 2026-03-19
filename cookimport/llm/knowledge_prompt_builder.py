from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "recipe.knowledge.compact.v1.prompt.md"
)

_INPUT_JSON_START = "<BEGIN_INPUT_JSON>"
_INPUT_JSON_END = "<END_INPUT_JSON>"


def build_knowledge_direct_prompt(input_payload: Mapping[str, Any]) -> str:
    template_text = (
        _load_template_text()
        .replace("{{INPUT_PATH}}", "<BEGIN_INPUT_JSON>...<END_INPUT_JSON>")
        .strip()
    )
    serialized_input = json.dumps(
        dict(input_payload),
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
