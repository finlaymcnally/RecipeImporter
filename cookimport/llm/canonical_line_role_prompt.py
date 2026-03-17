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

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Escalation reason codes: {{REASON_CODE_LEGEND}}
- Recipe atomic index ranges for this batch: {{RECIPE_ATOMIC_RANGES}}
- Any atomic index outside those ranges is outside recipe.

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
    label_code_by_label = _build_label_code_by_label(resolved_allowed)
    reason_code_by_reason = _build_reason_code_by_reason(
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
    )
    rendered_targets = _serialize_targets(
        targets,
        allowed_labels=resolved_allowed,
        prompt_format=resolved_format,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        label_code_by_label=label_code_by_label,
        reason_code_by_reason=reason_code_by_reason,
    )

    template = _load_prompt_template()
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{LABEL_CODE_LEGEND}}",
        _render_label_code_legend(label_code_by_label),
    )
    rendered = rendered.replace(
        "{{REASON_CODE_LEGEND}}",
        _render_reason_code_legend(reason_code_by_reason),
    )
    rendered = rendered.replace(
        "{{RECIPE_ATOMIC_RANGES}}",
        _render_recipe_atomic_ranges(targets),
    )
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
    label_code_by_label: Mapping[str, str] | None = None,
    reason_code_by_reason: Mapping[str, str] | None = None,
) -> str:
    allowed_label_set = {str(label).strip() for label in allowed_labels}
    resolved_label_codes = (
        dict(label_code_by_label)
        if label_code_by_label is not None
        else _build_label_code_by_label(allowed_labels)
    )
    resolved_reason_codes = (
        dict(reason_code_by_reason)
        if reason_code_by_reason is not None
        else _build_reason_code_by_reason(
            escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        )
    )
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
        reason_codes = ",".join(
            resolved_reason_codes[reason]
            for reason in escalation_reasons
            if reason in resolved_reason_codes
        ) or "-"
        row: list[object] = [
            atomic_index,
            resolved_label_codes.get(
                deterministic_label,
                resolved_label_codes.get("OTHER", "L0"),
            ),
            reason_codes,
            str(candidate.text),
        ]
        local_context = _local_context(candidate, escalation_reasons=escalation_reasons)
        if local_context is not None:
            row.append(local_context)
        lines.append(
            json.dumps(row, ensure_ascii=False)
        )
    return "\n".join(lines)


def _serialize_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    prompt_format: LineRolePromptFormat,
    deterministic_labels_by_atomic_index: Mapping[int, str] | None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None,
    label_code_by_label: Mapping[str, str],
    reason_code_by_reason: Mapping[str, str],
) -> str:
    del prompt_format
    return serialize_line_role_targets(
        targets,
        allowed_labels=allowed_labels,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        label_code_by_label=label_code_by_label,
        reason_code_by_reason=reason_code_by_reason,
    )


def _target_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One JSON array per line. Base shape: "
        '[atomic_index, label_code, reason_codes, current_line]. '
        "Optional local-context shape: "
        '[atomic_index, label_code, reason_codes, current_line, [previous_line, next_line]]. '
        'Use "-" for empty reason_codes.'
    )


def _build_label_code_by_label(labels: Sequence[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw_label in labels:
        normalized = str(raw_label or "").strip().upper()
        if not normalized or normalized in output:
            continue
        output[normalized] = f"L{len(output)}"
    if "OTHER" not in output:
        output["OTHER"] = f"L{len(output)}"
    return output


def _build_reason_code_by_reason(
    *,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None,
) -> dict[str, str]:
    output: dict[str, str] = {}
    if escalation_reasons_by_atomic_index is None:
        return output
    for atomic_index in sorted(int(value) for value in escalation_reasons_by_atomic_index):
        reasons = _prompt_escalation_reasons(
            escalation_reasons_by_atomic_index.get(atomic_index)
        )
        for reason in reasons:
            if reason in output:
                continue
            output[reason] = f"R{len(output)}"
    return output


def _render_label_code_legend(code_by_label: Mapping[str, str]) -> str:
    return ", ".join(f"{code}={label}" for label, code in code_by_label.items())


def _render_reason_code_legend(code_by_reason: Mapping[str, str]) -> str:
    if not code_by_reason:
        return "none"
    return ", ".join(f"{code}={reason}" for reason, code in code_by_reason.items())


def _render_recipe_atomic_ranges(targets: Sequence[AtomicLineCandidate]) -> str:
    recipe_indices = sorted(
        int(candidate.atomic_index) for candidate in targets if bool(candidate.within_recipe_span)
    )
    if not recipe_indices:
        return "none"
    ranges: list[str] = []
    start = recipe_indices[0]
    end = recipe_indices[0]
    for atomic_index in recipe_indices[1:]:
        if atomic_index == end + 1:
            end = atomic_index
            continue
        ranges.append(f"{start}-{end}" if start != end else str(start))
        start = end = atomic_index
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ", ".join(ranges)


def _local_context(
    candidate: AtomicLineCandidate,
    *,
    escalation_reasons: Sequence[str],
) -> list[str] | None:
    if not escalation_reasons or not bool(candidate.within_recipe_span):
        return None
    previous_line = str(candidate.prev_text or "")
    next_line = str(candidate.next_text or "")
    if not previous_line and not next_line:
        return None
    return [previous_line, next_line]


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
