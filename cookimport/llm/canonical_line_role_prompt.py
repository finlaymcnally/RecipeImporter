from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

LineRolePromptFormat = Literal["compact_v1"]

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_INLINE_TEMPLATE_PATH = _PROMPT_ROOT / "canonical-line-role-v1.prompt.md"
_FILE_PROMPT_TEMPLATE_PATH = _PROMPT_ROOT / "line-role.canonical.v1.prompt.md"

_INLINE_TEMPLATE_FALLBACK = """You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat `span_code` as a weak provenance hint only. It may be unknown and it is not authoritative recipe-boundary truth.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: R=in_recipe, N=outside_recipe, U=unknown_recipe_status
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Use `KNOWLEDGE` only for explicit explanatory/reference prose, not ordinary recipe structure.
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

6) Context: explanatory cookbook prose
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

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

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
    rendered_targets = serialize_line_role_targets(
        targets,
        allowed_labels=resolved_allowed,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
        label_code_by_label=label_code_by_label,
    )
    template = _load_prompt_template(
        template_path=_INLINE_TEMPLATE_PATH,
        fallback=_INLINE_TEMPLATE_FALLBACK,
    )
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
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
        "{{TARGET_ROW_FORMAT}}",
        _line_role_row_format_text(resolved_format),
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


def build_canonical_line_role_file_prompt(
    *,
    input_path: Path,
    owned_atomic_indices: Sequence[int],
    allowed_labels: Sequence[str] | None = None,
    prompt_format: LineRolePromptFormat = "compact_v1",
) -> str:
    if not owned_atomic_indices:
        raise ValueError("owned_atomic_indices cannot be empty")
    del allowed_labels
    del prompt_format
    template = _load_prompt_template(
        template_path=_FILE_PROMPT_TEMPLATE_PATH,
        fallback=(
            "Execute the line-role labeling task exactly.\n\n"
            "Return strict JSON with this exact shape:\n"
            '{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}\n\n'
            "Rules:\n"
            "- Output only JSON.\n"
            "- Use only the keys `rows`, `atomic_index`, and `label`.\n"
            "- Keep row order exactly as requested by the task file.\n"
            "- Read the task file already placed in the worker folder at `{{INPUT_PATH}}`.\n"
            "- Use only that task file as evidence.\n\n"
            "Task file path:\n"
            "{{INPUT_PATH}}\n"
        ),
    )
    return template.replace("{{INPUT_PATH}}", str(input_path)).strip() + "\n"


def serialize_line_role_targets(
    targets: Sequence[AtomicLineCandidate],
    *,
    allowed_labels: Sequence[str],
    deterministic_labels_by_atomic_index: Mapping[int, str] | None = None,
    escalation_reasons_by_atomic_index: Mapping[int, Sequence[str]] | None = None,
    label_code_by_label: Mapping[str, str] | None = None,
) -> str:
    allowed_label_set = {str(label).strip().upper() for label in allowed_labels}
    resolved_label_codes = (
        dict(label_code_by_label)
        if label_code_by_label is not None
        else _build_label_code_by_label(allowed_labels)
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
        escalation_reasons = (
            escalation_reasons_by_atomic_index.get(atomic_index)
            if escalation_reasons_by_atomic_index is not None
            else ()
        )
        lines.append(
            _serialize_compact_target_row(
                atomic_index=atomic_index,
                label_code=resolved_label_codes.get(
                    deterministic_label,
                    resolved_label_codes.get("OTHER", "L0"),
                ),
                span_code=_span_code(candidate.within_recipe_span),
                hint_codes=_render_hint_codes(
                    candidate.rule_tags,
                    escalation_reasons,
                ),
                current_line=str(candidate.text),
            )
        )
    return "\n".join(lines)


def _line_role_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One pipe-delimited row per line: "
        "atomic_index|label_code|span_code|hint_codes|current_line. "
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
    label_code: str,
    span_code: str,
    hint_codes: str,
    current_line: str,
) -> str:
    return (
        f"{int(atomic_index)}|{str(label_code)}|{str(span_code)}|"
        f"{_escape_compact_text(hint_codes)}|{_escape_compact_text(current_line)}"
    )


def _span_code(within_recipe_span: bool | None) -> str:
    if within_recipe_span is True:
        return "R"
    if within_recipe_span is False:
        return "N"
    return "U"


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
