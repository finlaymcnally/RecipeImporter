from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

LineRolePromptFormat = Literal["compact_v1"]
RecipeRegionStatus = Literal["recipe", "outside_recipe", "boundary_uncertain"]

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_REGION_GATE_TEMPLATE_PATH = (
    _PROMPT_ROOT / "canonical-line-role-recipe-region-gate-v1.prompt.md"
)
_STRUCTURE_TEMPLATE_PATH = _PROMPT_ROOT / "canonical-line-role-v1.prompt.md"
_REGION_GATE_FILE_PROMPT_TEMPLATE_PATH = (
    _PROMPT_ROOT / "line-role.recipe-region-gate.v1.prompt.md"
)
_STRUCTURE_FILE_PROMPT_TEMPLATE_PATH = (
    _PROMPT_ROOT / "line-role.recipe-structure-label.v1.prompt.md"
)

_REGION_GATE_TEMPLATE_FALLBACK = """You are deciding recipe-region membership for cookbook atomic lines.

TASK BOUNDARY
- Review one ordered slice of the book.
- `deterministic_label` is a weak hint only.
- Decide whether each line is part of an active recipe region.
- Do not invent a recipe region from an isolated title-like heading, chapter heading, blurb, testimonial, or front matter line.
- Never invent lines or labels.

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: {{SPAN_CODE_LEGEND}}
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Region status meaning:
- `recipe`: clearly belongs to an active recipe region
- `outside_recipe`: clearly not part of a recipe region
- `boundary_uncertain`: ambiguous edge line near a possible recipe boundary

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON object shaped like:
{"rows":[{"atomic_index": <int>, "region_status": "recipe|outside_recipe|boundary_uncertain"}]}

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `region_status` must be `recipe`, `outside_recipe`, or `boundary_uncertain`.
4) No markdown, no commentary, no extra keys.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
"""

_STRUCTURE_TEMPLATE_FALLBACK = """You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded recipe-structure correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat `region_code` as the recipe-region gate result for that row.
- Rows gated `O=outside_recipe` must stay within non-recipe labels only.
- Rows gated `B=boundary_uncertain` may use recipe labels only when local context clearly shows the line belongs inside a real recipe region.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Region codes: {{REGION_CODE_LEGEND}}
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Use `KNOWLEDGE` only for explicit explanatory/reference prose, not ordinary recipe structure.
- If a row is gated `outside_recipe`, do not emit `RECIPE_TITLE`, `RECIPE_VARIANT`, `HOWTO_SECTION`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, or `TIME_LINE`.

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

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
"""

_REGION_GATE_FILE_PROMPT_TEMPLATE_FALLBACK = """Execute the recipe-region gate task exactly.

Return strict JSON with this exact shape:
{"rows":[{"atomic_index":123,"region_status":"boundary_uncertain"}]}

Rules:
- Output only JSON.
- Use only the keys `rows`, `atomic_index`, and `region_status`.
- Keep row order exactly as requested by the task file.
- Read the task file already placed in the worker folder at `{{INPUT_PATH}}`.
- Use only that task file as evidence.

Task file path:
{{INPUT_PATH}}
"""

_STRUCTURE_FILE_PROMPT_TEMPLATE_FALLBACK = """Execute the recipe-structure labeling task exactly.

Return strict JSON with this exact shape:
{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Rules:
- Output only JSON.
- Use only the keys `rows`, `atomic_index`, and `label`.
- Keep row order exactly as requested by the task file.
- Read the task file already placed in the worker folder at `{{INPUT_PATH}}`.
- Use only that task file as evidence.

Task file path:
{{INPUT_PATH}}
"""

_FILE_BACKED_TEMPLATE_FALLBACK = """You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Read the shard JSON already placed in the worker folder at `{{INPUT_PATH}}`.
- Treat `rows[*].deterministic_label` as the first-pass label you are reviewing.
- Use local context from `prev_text`, `current_line`, and `next_text` to correct structure.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Task file contract:
- Top-level keys: `shard_id`, `phase_key`, `rows`.
- Each `rows[*]` object includes:
  - `atomic_index`: the required output id.
  - `block_id`: source block identifier.
  - `recipe_id`: recipe identifier when known, else null.
  - `within_recipe_span`: `true` in recipe, `false` outside recipe, `null` unknown.
  - `deterministic_label`: first-pass label to review.
  - `rule_tags`: deterministic heuristic tags.
  - `escalation_reasons`: why this row was escalated for review.
  - `prev_text`, `current_line`, `next_text`: local context window.

Compact legends used inside the task file:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: R=in_recipe, N=outside_recipe, U=unknown_recipe_status

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Use `KNOWLEDGE` only for explicit explanatory/reference prose, not ordinary recipe structure.
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.

Required output rows:
{{OWNED_ATOMIC_INDICES}}

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON object with this shape:
{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Hard output rules:
1) Return each required `atomic_index` exactly once.
2) Keep output order identical to the ordered `rows[*]` list in the task file.
3) Each `label` must be one of the allowed global labels listed above.
4) No markdown, no commentary, no extra keys.
"""

_REGION_GATE_FILE_BACKED_TEMPLATE_FALLBACK = """You are deciding recipe-region membership for cookbook atomic lines.

TASK BOUNDARY
- Review one ordered slice of the book by reading the shard JSON at `{{INPUT_PATH}}`.
- `rows[*].deterministic_label` is a weak hint only.
- Decide whether each line is part of an active recipe region.
- Use local context from `prev_text`, `current_line`, and `next_text`.
- Do not invent a recipe region from an isolated title-like heading, chapter heading, blurb, testimonial, or front matter line.
- Never invent lines or labels.

Compact legends used inside the task file:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: R=in_recipe, N=outside_recipe, U=unknown_recipe_status

Task file contract:
- Top-level keys: `shard_id`, `phase_key`, `rows`.
- Each `rows[*]` object includes `atomic_index`, `deterministic_label`, `rule_tags`,
  `escalation_reasons`, `prev_text`, `current_line`, and `next_text`.

Region status meaning:
- `recipe`: clearly belongs to an active recipe region
- `outside_recipe`: clearly not part of a recipe region
- `boundary_uncertain`: ambiguous edge line near a possible recipe boundary

Required output rows:
{{OWNED_ATOMIC_INDICES}}

RETURN FORMAT (STRICT JSON ONLY)
Return exactly one JSON object with this shape:
{"rows":[{"atomic_index":123,"region_status":"boundary_uncertain"}]}

Hard output rules:
1) Return each required `atomic_index` exactly once.
2) Keep output order identical to the ordered `rows[*]` list in the task file.
3) Each `region_status` must be `recipe`, `outside_recipe`, or `boundary_uncertain`.
4) No markdown, no commentary, no extra keys.
"""


def build_recipe_region_gate_prompt(
    targets: Sequence[AtomicLineCandidate],
    *,
    prompt_format: LineRolePromptFormat = "compact_v1",
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
) -> str:
    if not targets:
        raise ValueError("targets cannot be empty")
    resolved_format = _normalize_prompt_format(prompt_format)
    label_code_by_label = _build_label_code_by_label(FREEFORM_LABELS)
    rendered_targets = serialize_recipe_region_gate_targets(
        targets,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        label_code_by_label=label_code_by_label,
    )
    template = _load_prompt_template(
        template_path=_REGION_GATE_TEMPLATE_PATH,
        fallback=_REGION_GATE_TEMPLATE_FALLBACK,
    )
    rendered = template.replace(
        "{{LABEL_CODE_LEGEND}}",
        _render_label_code_legend(label_code_by_label),
    )
    rendered = rendered.replace(
        "{{SPAN_CODE_LEGEND}}",
        "R=in_recipe, N=outside_recipe, U=unknown_recipe_status",
    )
    rendered = rendered.replace(
        "{{TARGET_ROW_FORMAT}}",
        _region_gate_row_format_text(resolved_format),
    )
    rendered = rendered.replace(
        "{{LOCAL_CONTEXT_ROWS}}",
        _render_local_context_rows(
            targets,
            deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
            escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        ),
    )
    rendered = rendered.replace("{{TARGETS_ROWS}}", rendered_targets)
    return rendered.strip() + "\n"


def build_recipe_structure_label_prompt(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    region_status_by_atomic_index: Mapping[int, RecipeRegionStatus] | None = None,
) -> str:
    if not targets:
        raise ValueError("targets cannot be empty")
    resolved_allowed = [str(label) for label in (allowed_labels or FREEFORM_LABELS)]
    resolved_format = _normalize_prompt_format(prompt_format)
    label_code_by_label = _build_label_code_by_label(resolved_allowed)
    rendered_targets = serialize_recipe_structure_targets(
        targets,
        allowed_labels=resolved_allowed,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        region_status_by_atomic_index=region_status_by_atomic_index,
        label_code_by_label=label_code_by_label,
    )
    template = _load_prompt_template(
        template_path=_STRUCTURE_TEMPLATE_PATH,
        fallback=_STRUCTURE_TEMPLATE_FALLBACK,
    )
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{LABEL_CODE_LEGEND}}",
        _render_label_code_legend(label_code_by_label),
    )
    rendered = rendered.replace(
        "{{REGION_CODE_LEGEND}}",
        "R=recipe, O=outside_recipe, B=boundary_uncertain",
    )
    rendered = rendered.replace(
        "{{PRECEDENCE_ORDER}}",
        "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > "
        "INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > "
        "KNOWLEDGE > OTHER",
    )
    rendered = rendered.replace(
        "{{TARGET_ROW_FORMAT}}",
        _structure_row_format_text(resolved_format),
    )
    rendered = rendered.replace(
        "{{LOCAL_CONTEXT_ROWS}}",
        _render_local_context_rows(
            targets,
            deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
            escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        ),
    )
    rendered = rendered.replace("{{TARGETS_ROWS}}", rendered_targets)
    return rendered.strip() + "\n"


def build_canonical_line_role_prompt(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    region_status_by_atomic_index: Mapping[int, RecipeRegionStatus] | None = None,
) -> str:
    return build_recipe_structure_label_prompt(
        targets,
        allowed_labels=allowed_labels,
        prompt_format=prompt_format,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        region_status_by_atomic_index=region_status_by_atomic_index,
    )


def build_recipe_region_gate_file_prompt(
    *,
    input_path: Path,
    owned_atomic_indices: Sequence[int] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
) -> str:
    del owned_atomic_indices
    del prompt_format
    template = _load_prompt_template(
        template_path=_REGION_GATE_FILE_PROMPT_TEMPLATE_PATH,
        fallback=_REGION_GATE_FILE_PROMPT_TEMPLATE_FALLBACK,
    )
    return template.replace("{{INPUT_PATH}}", str(input_path)).strip() + "\n"


def build_canonical_line_role_file_prompt(
    *,
    input_path: Path,
    owned_atomic_indices: Sequence[int] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
) -> str:
    del owned_atomic_indices
    del prompt_format
    template = _load_prompt_template(
        template_path=_STRUCTURE_FILE_PROMPT_TEMPLATE_PATH,
        fallback=_STRUCTURE_FILE_PROMPT_TEMPLATE_FALLBACK,
    )
    return template.replace("{{INPUT_PATH}}", str(input_path)).strip() + "\n"


def build_canonical_line_role_file_prompt(
    *,
    input_path: Path,
    owned_atomic_indices: Sequence[int],
    allowed_labels: Sequence[str] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
) -> str:
    if not owned_atomic_indices:
        raise ValueError("owned_atomic_indices cannot be empty")
    resolved_allowed = [str(label) for label in (allowed_labels or FREEFORM_LABELS)]
    resolved_format = _normalize_prompt_format(prompt_format)
    del resolved_format
    label_code_by_label = _build_label_code_by_label(resolved_allowed)
    rendered = _FILE_BACKED_TEMPLATE_FALLBACK.replace(
        "{{INPUT_PATH}}",
        str(input_path),
    )
    rendered = rendered.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{LABEL_CODE_LEGEND}}",
        _render_label_code_legend(label_code_by_label),
    )
    rendered = rendered.replace(
        "{{PRECEDENCE_ORDER}}",
        "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > "
        "INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > "
        "KNOWLEDGE > OTHER",
    )
    rendered = rendered.replace(
        "{{OWNED_ATOMIC_INDICES}}",
        ", ".join(str(int(value)) for value in owned_atomic_indices),
    )
    return rendered.strip() + "\n"


def build_recipe_region_gate_file_prompt(
    *,
    input_path: Path,
    owned_atomic_indices: Sequence[int],
    prompt_format: LineRolePromptFormat = "compact_v1",
) -> str:
    if not owned_atomic_indices:
        raise ValueError("owned_atomic_indices cannot be empty")
    resolved_format = _normalize_prompt_format(prompt_format)
    del resolved_format
    rendered = _REGION_GATE_FILE_BACKED_TEMPLATE_FALLBACK.replace(
        "{{INPUT_PATH}}",
        str(input_path),
    )
    rendered = rendered.replace(
        "{{LABEL_CODE_LEGEND}}",
        _render_label_code_legend(_build_label_code_by_label(FREEFORM_LABELS)),
    )
    rendered = rendered.replace(
        "{{OWNED_ATOMIC_INDICES}}",
        ", ".join(str(int(value)) for value in owned_atomic_indices),
    )
    return rendered.strip() + "\n"


def serialize_recipe_region_gate_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    label_code_by_label: Mapping[str, str] | None = None,
) -> str:
    resolved_label_codes = (
        dict(label_code_by_label)
        if label_code_by_label is not None
        else _build_label_code_by_label(FREEFORM_LABELS)
    )
    lines: list[str] = []
    for candidate in targets:
        atomic_index = int(candidate.atomic_index)
        deterministic_label = _prompt_deterministic_label(
            deterministic_labels_by_atomic_index.get(atomic_index)
            if deterministic_labels_by_atomic_index is not None
            else None,
            allowed_labels={str(label).strip().upper() for label in FREEFORM_LABELS},
        )
        escalation_reasons = (
            escalation_reasons_by_atomic_index.get(atomic_index)
            if escalation_reasons_by_atomic_index is not None
            else ()
        )
        lines.append(
            _serialize_compact_target_row(
                atomic_index=atomic_index,
                second_code=resolved_label_codes.get(
                    deterministic_label,
                    resolved_label_codes.get("OTHER", "L0"),
                ),
                third_code=_span_code(candidate.within_recipe_span),
                hint_codes=_render_hint_codes(
                    candidate.rule_tags,
                    escalation_reasons,
                ),
                current_line=str(candidate.text),
            )
        )
    return "\n".join(lines)


def serialize_recipe_structure_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    region_status_by_atomic_index: Mapping[int, RecipeRegionStatus] | None = None,
    label_code_by_label: Mapping[str, str] | None = None,
    reason_code_by_reason: Mapping[str, str] | None = None,
) -> str:
    allowed_label_set = {str(label).strip().upper() for label in allowed_labels}
    resolved_label_codes = (
        dict(label_code_by_label)
        if label_code_by_label is not None
        else _build_label_code_by_label(allowed_labels)
    )
    del reason_code_by_reason
    lines: list[str] = []
    for candidate in targets:
        atomic_index = int(candidate.atomic_index)
        deterministic_label = _prompt_deterministic_label(
            deterministic_labels_by_atomic_index.get(atomic_index)
            if deterministic_labels_by_atomic_index is not None
            else None,
            allowed_labels=allowed_label_set,
        )
        escalation_reasons = (
            escalation_reasons_by_atomic_index.get(atomic_index)
            if escalation_reasons_by_atomic_index is not None
            else ()
        )
        lines.append(
            _serialize_compact_target_row(
                atomic_index=atomic_index,
                second_code=resolved_label_codes.get(
                    deterministic_label,
                    resolved_label_codes.get("OTHER", "L0"),
                ),
                third_code=_region_code(
                    region_status_by_atomic_index.get(atomic_index)
                    if region_status_by_atomic_index is not None
                    else None
                ),
                hint_codes=_render_hint_codes(
                    candidate.rule_tags,
                    escalation_reasons,
                ),
                current_line=str(candidate.text),
            )
        )
    return "\n".join(lines)


def serialize_line_role_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    region_status_by_atomic_index: Mapping[int, RecipeRegionStatus] | None = None,
    label_code_by_label: Mapping[str, str] | None = None,
    reason_code_by_reason: Mapping[str, str] | None = None,
) -> str:
    return serialize_recipe_structure_targets(
        targets,
        allowed_labels=allowed_labels,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        region_status_by_atomic_index=region_status_by_atomic_index,
        label_code_by_label=label_code_by_label,
        reason_code_by_reason=reason_code_by_reason,
    )


def _region_gate_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One pipe-delimited row per line: "
        "atomic_index|label_code|span_code|hint_codes|current_line. "
        "Grounding windows are separate rows shaped like "
        "`ctx:<atomic_index>|prev=...|line=...|next=...` for selected ambiguous lines."
    )


def _structure_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One pipe-delimited row per line: "
        "atomic_index|label_code|region_code|hint_codes|current_line. "
        "Grounding windows are separate rows shaped like "
        "`ctx:<atomic_index>|prev=...|line=...|next=...` for selected ambiguous lines."
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


def _render_label_code_legend(code_by_label: Mapping[str, str]) -> str:
    return ", ".join(f"{code}={label}" for label, code in code_by_label.items())


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


def _serialize_compact_target_row(
    *,
    atomic_index: int,
    second_code: str,
    third_code: str,
    hint_codes: str,
    current_line: str,
) -> str:
    return (
        f"{int(atomic_index)}|{str(second_code)}|{str(third_code)}|"
        f"{_escape_compact_text(hint_codes)}|{_escape_compact_text(current_line)}"
    )


def _span_code(within_recipe_span: bool | None) -> str:
    if within_recipe_span is True:
        return "R"
    if within_recipe_span is False:
        return "N"
    return "U"


def _region_code(region_status: RecipeRegionStatus | str | None) -> str:
    normalized = str(region_status or "").strip().lower()
    if normalized == "recipe":
        return "R"
    if normalized == "outside_recipe":
        return "O"
    return "B"


def _render_hint_codes(
    rule_tags: Sequence[str] | None,
    escalation_reasons: Sequence[str] | None,
) -> str:
    seen: list[str] = []
    for values in (rule_tags or (), escalation_reasons or ()):
        for raw_value in values:
            normalized = _normalize_hint_code(raw_value)
            if not normalized or normalized in seen:
                continue
            seen.append(normalized)
            if len(seen) >= 4:
                return ",".join(seen)
    return ",".join(seen) if seen else "-"


def _normalize_hint_code(raw_value: str | None) -> str:
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return ""
    aliases = {
        "title_like": "title",
        "ingredient_like": "ingredient",
        "instruction_like": "instruction",
        "instruction_with_time": "instruction_time",
        "yield_prefix": "yield",
        "note_prefix": "note",
        "note_like_prose": "note_prose",
        "howto_heading": "howto",
        "variant_heading": "variant",
        "time_metadata": "time",
        "outside_recipe": "outside",
        "outside_recipe_span": "outside",
        "recipe_span_fallback": "in_recipe",
        "explicit_prose": "prose",
        "deterministic_unresolved": "needs_review",
        "fallback_decision": "fallback",
        "outside_span_structured_label": "outside_structure",
        "recipe_region_gate_outside_recipe": "gated_outside",
        "recipe_region_gate_boundary_uncertain": "gated_boundary",
        "recipe_region_gate_recipe": "gated_recipe",
    }
    if normalized in aliases:
        return aliases[normalized]
    cleaned = normalized.replace("-", "_").replace(" ", "_")
    cleaned = "".join(
        char for char in cleaned if char.isalnum() or char == "_"
    ).strip("_")
    return cleaned[:18]


def _render_local_context_rows(
    targets: Sequence[AtomicLineCandidate],
    *,
    deterministic_labels_by_atomic_index: Mapping[int, str] | None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None,
) -> str:
    allowed_labels = {str(label).strip().upper() for label in FREEFORM_LABELS}
    rows: list[str] = []
    for candidate in targets:
        atomic_index = int(candidate.atomic_index)
        deterministic_label = _prompt_deterministic_label(
            deterministic_labels_by_atomic_index.get(atomic_index)
            if deterministic_labels_by_atomic_index is not None
            else None,
            allowed_labels=allowed_labels,
        )
        escalation_reasons = (
            escalation_reasons_by_atomic_index.get(atomic_index)
            if escalation_reasons_by_atomic_index is not None
            else ()
        )
        if not _should_render_context_window(
            candidate,
            deterministic_label=deterministic_label,
            escalation_reasons=escalation_reasons,
        ):
            continue
        rows.append(
            "ctx:"
            f"{atomic_index}|prev={_escape_compact_text(_context_text(candidate.prev_text))}"
            f"|line={_escape_compact_text(_context_text(candidate.text))}"
            f"|next={_escape_compact_text(_context_text(candidate.next_text))}"
        )
    return "\n".join(rows) if rows else "(none)"


def _should_render_context_window(
    candidate: AtomicLineCandidate,
    *,
    deterministic_label: str,
    escalation_reasons: Sequence[str],
) -> bool:
    if escalation_reasons:
        return True
    if candidate.within_recipe_span is not True:
        return True
    return deterministic_label in {
        "OTHER",
        "KNOWLEDGE",
        "RECIPE_TITLE",
        "RECIPE_VARIANT",
        "HOWTO_SECTION",
        "RECIPE_NOTES",
    }


def _context_text(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "_"


def _escape_compact_text(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _load_prompt_template(*, template_path: Path, fallback: str) -> str:
    try:
        text = template_path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    normalized = text.strip()
    if not normalized:
        return fallback
    return normalized
