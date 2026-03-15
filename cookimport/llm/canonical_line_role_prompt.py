from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

LineRolePromptFormat = Literal["legacy", "compact_v1"]

_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "canonical-line-role-v1.prompt.md"
)

_PROMPT_TEMPLATE_FALLBACK = """You are assigning canonical line-role labels to cookbook atomic lines.

TASK BOUNDARY
- This is line-role classification only.
- Never perform schema.org extraction.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Inside recipe spans, `KNOWLEDGE` is last resort and should be used only when the line is explicit prose.
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.

Few-shot examples:
1) Context: inside recipe, heading line
   Line: `FOR THE MALT COOKIES`
   Label: `HOWTO_SECTION`

2) Context: adjacent lines are ingredients
   Line: `Grapeseed oil`
   Label: `INGREDIENT_LINE`

3) Context: inside recipe
   Line: `SERVES 4`
   Label: `YIELD_LINE`

4) Context: recipe method
   Line: `Whisk in the cream and simmer for 2 to 3 minutes.`
   Label: `INSTRUCTION_LINE`

5) Context: inside recipe
   Line: `NOTE: Cooled hollandaise can break if reheated too fast.`
   Label: `RECIPE_NOTES`

6) Context: outside recipe span, narrative paragraph
   Line: `Copper pans conduct heat quickly and evenly, so temperature changes show up fast.`
   Label: `KNOWLEDGE`

7) Context: inside recipe, ingredient range
   Line: `4 to 6 chicken leg quarters`
   Label: `INGREDIENT_LINE`

8) Context: inside recipe, all-caps variant header
   Line: `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET`
   Label: `RECIPE_VARIANT`

9) Context: inside recipe, primary recipe heading
   Line: `A PORRIDGE OF LOVAGE STEMS`
   Label: `RECIPE_TITLE`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) No markdown, no commentary, no extra keys.

Target row format:
{{TARGET_ROW_FORMAT}}

Targets:
{{TARGETS_ROWS}}
"""


def build_canonical_line_role_prompt(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str] | None = None,
    prompt_format: LineRolePromptFormat = "legacy",
) -> str:
    if not targets:
        raise ValueError("targets cannot be empty")
    resolved_allowed = [str(label) for label in (allowed_labels or FREEFORM_LABELS)]
    resolved_format = _normalize_prompt_format(prompt_format)
    rendered_targets = _serialize_targets(
        targets,
        allowed_labels=resolved_allowed,
        prompt_format=resolved_format,
    )

    template = _load_prompt_template()
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{PRECEDENCE_ORDER}}",
        "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > "
        "INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > "
        "KNOWLEDGE > OTHER",
    )
    rendered = rendered.replace(
        "{{TARGET_ROW_FORMAT}}",
        _target_row_format_text(resolved_format),
    )
    rendered = rendered.replace("{{TARGETS_ROWS}}", rendered_targets)
    return rendered.strip() + "\n"


def serialize_line_role_targets_legacy(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
) -> str:
    del allowed_labels
    lines: list[str] = []
    for candidate in targets:
        lines.append(
            json.dumps(
                {
                    "atomic_index": int(candidate.atomic_index),
                    "within_recipe_span": bool(candidate.within_recipe_span),
                    "previous_line": str(candidate.prev_text or ""),
                    "current_line": str(candidate.text),
                    "next_line": str(candidate.next_text or ""),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def serialize_line_role_targets_compact(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
) -> str:
    del allowed_labels
    lines: list[str] = []
    for candidate in targets:
        lines.append(
            json.dumps(
                [
                    int(candidate.atomic_index),
                    1 if bool(candidate.within_recipe_span) else 0,
                    str(candidate.prev_text or ""),
                    str(candidate.text),
                    str(candidate.next_text or ""),
                ],
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def _serialize_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    prompt_format: LineRolePromptFormat,
) -> str:
    if prompt_format == "compact_v1":
        return serialize_line_role_targets_compact(
            targets,
            allowed_labels=allowed_labels,
        )
    return serialize_line_role_targets_legacy(
        targets,
        allowed_labels=allowed_labels,
    )


def _target_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    if prompt_format == "compact_v1":
        return (
            "One JSON array per line: "
            "[atomic_index, within_recipe_span_1_or_0, previous_line, current_line, "
            "next_line]"
        )
    return (
        "One JSON object per line with keys "
        "`atomic_index`, `within_recipe_span`, `previous_line`, "
        "`current_line`, and `next_line`."
    )


def _normalize_prompt_format(value: str) -> LineRolePromptFormat:
    normalized = str(value).strip().lower()
    if normalized == "compact_v1":
        return "compact_v1"
    return "legacy"


def _load_prompt_template() -> str:
    try:
        text = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return _PROMPT_TEMPLATE_FALLBACK
    normalized = text.strip()
    if not normalized:
        return _PROMPT_TEMPLATE_FALLBACK
    return normalized
