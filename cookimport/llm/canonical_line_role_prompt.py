from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

LineRolePromptFormat = Literal["compact_v1"]

_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "canonical-line-role-v1.prompt.md"
)

_PROMPT_TEMPLATE_FALLBACK = """You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is line-role label correction only.
- Treat `deterministic_label` as the first-pass label you are reviewing.
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
    prompt_format: LineRolePromptFormat = "compact_v1",
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
) -> str:
    if not targets:
        raise ValueError("targets cannot be empty")
    resolved_allowed = [str(label) for label in (allowed_labels or FREEFORM_LABELS)]
    resolved_format = _normalize_prompt_format(prompt_format)
    rendered_targets = _serialize_targets(
        targets,
        allowed_labels=resolved_allowed,
        prompt_format=resolved_format,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
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


def serialize_line_role_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
) -> str:
    allowed_label_set = {str(label).strip() for label in allowed_labels}
    lines: list[str] = []
    for candidate in targets:
        atomic_index = int(candidate.atomic_index)
        deterministic_label = _prompt_deterministic_label(
            deterministic_labels_by_atomic_index.get(atomic_index)
            if deterministic_labels_by_atomic_index is not None
            else None,
            allowed_labels=allowed_label_set,
        )
        escalation_reasons = _prompt_escalation_reasons(
            escalation_reasons_by_atomic_index.get(atomic_index)
            if escalation_reasons_by_atomic_index is not None
            else None
        )
        lines.append(
            json.dumps(
                {
                    "atomic_index": atomic_index,
                    "within_recipe_span": 1 if bool(candidate.within_recipe_span) else 0,
                    "deterministic_label": deterministic_label,
                    "escalation_reasons": escalation_reasons,
                    "previous_line": _neighbor_text(candidate, candidate.prev_text),
                    "current_line": str(candidate.text),
                    "next_line": _neighbor_text(candidate, candidate.next_text),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def _serialize_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    prompt_format: LineRolePromptFormat,
    deterministic_labels_by_atomic_index: Mapping[int, str] | None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None,
) -> str:
    del prompt_format
    return serialize_line_role_targets(
        targets,
        allowed_labels=allowed_labels,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
    )


def _target_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One JSON object per line: "
        '{"atomic_index": <int>, "within_recipe_span": <0|1>, '
        '"deterministic_label": "<LABEL>", "escalation_reasons": ["<REASON>", ...], '
        '"previous_line": "<text>", "current_line": "<text>", "next_line": "<text>"}'
    )


def _neighbor_text(candidate: AtomicLineCandidate, value: str | None) -> str:
    if not bool(candidate.within_recipe_span):
        return ""
    return str(value or "")


def _normalize_prompt_format(value: str) -> LineRolePromptFormat:
    del value
    return "compact_v1"


def _prompt_deterministic_label(
    raw_label: str | None,
    *,
    allowed_labels: set[str],
) -> str:
    normalized = str(raw_label or "").strip().upper() or "OTHER"
    if normalized not in allowed_labels:
        return "OTHER"
    return normalized


def _prompt_escalation_reasons(
    reasons: Sequence[str] | None,
) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for reason in reasons or ():
        rendered = str(reason or "").strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        output.append(rendered)
    return output


def _load_prompt_template() -> str:
    try:
        text = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return _PROMPT_TEMPLATE_FALLBACK
    normalized = text.strip()
    if not normalized:
        return _PROMPT_TEMPLATE_FALLBACK
    return normalized
