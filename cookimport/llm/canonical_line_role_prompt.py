from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "canonical-line-role-v1.prompt.md"
)

_PROMPT_TEMPLATE_FALLBACK = """You are assigning canonical line-role labels to cookbook lines.

IMPORTANT
- This task is line-role classification only.
- Do not do schema.org extraction.
- Output strict JSON only.

Allowed labels:
{{ALLOWED_LABELS}}

Tie-break precedence:
{{PRECEDENCE_ORDER}}

Must-not rules:
- Never label a quantity/unit ingredient line as KNOWLEDGE.
- Never label an imperative instruction sentence as KNOWLEDGE.
- Inside recipe spans, KNOWLEDGE is a last resort.

Few-shot examples:
1) FOR THE MALT COOKIES -> HOWTO_SECTION
2) Grapeseed oil (ingredient context) -> INGREDIENT_LINE
3) SERVES 4 -> YIELD_LINE
4) Whisk in butter and cook 2 minutes. -> INSTRUCTION_LINE
5) NOTE: Cooled hollandaise can break if reheated too fast. -> RECIPE_NOTES
6) Outside recipe span: "Copper pans conduct heat quickly and evenly." -> KNOWLEDGE

Output format:
[{"atomic_index": <int>, "label": "<LABEL>"}]

Hard rules:
1) Return each requested atomic_index exactly once.
2) Keep the same order as requested targets.
3) Each label must be one of the target's candidate_labels.

Targets:
{{TARGETS_JSONL}}
"""


def build_canonical_line_role_prompt(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str] | None = None,
) -> str:
    if not targets:
        raise ValueError("targets cannot be empty")
    resolved_allowed = [str(label) for label in (allowed_labels or FREEFORM_LABELS)]
    allowed_set = {label for label in resolved_allowed}
    lines: list[str] = []
    for candidate in targets:
        candidate_allowlist = [
            str(label)
            for label in candidate.candidate_labels
            if str(label) in allowed_set
        ]
        if not candidate_allowlist:
            candidate_allowlist = list(resolved_allowed)
        lines.append(
            json.dumps(
                {
                    "atomic_index": int(candidate.atomic_index),
                    "within_recipe_span": bool(candidate.within_recipe_span),
                    "previous_line": str(candidate.prev_text or ""),
                    "current_line": str(candidate.text),
                    "next_line": str(candidate.next_text or ""),
                    "candidate_labels": candidate_allowlist,
                },
                ensure_ascii=False,
            )
        )

    template = _load_prompt_template()
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{PRECEDENCE_ORDER}}",
        "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > "
        "INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > "
        "KNOWLEDGE > OTHER",
    )
    rendered = rendered.replace("{{TARGETS_JSONL}}", "\n".join(lines))
    return rendered.strip() + "\n"


def _load_prompt_template() -> str:
    try:
        text = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return _PROMPT_TEMPLATE_FALLBACK
    normalized = text.strip()
    if not normalized:
        return _PROMPT_TEMPLATE_FALLBACK
    return normalized

