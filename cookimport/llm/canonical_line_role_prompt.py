from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_LABELS
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    build_atomic_index_lookup,
    get_atomic_line_neighbor_texts,
)

LineRolePromptFormat = Literal["compact_v1"]

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_INLINE_TEMPLATE_PATH = _PROMPT_ROOT / "canonical-line-role-v1.prompt.md"
_FILE_PROMPT_TEMPLATE_PATH = _PROMPT_ROOT / "line-role.canonical.v1.prompt.md"

_INLINE_TEMPLATE_FALLBACK = """You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat the deterministic label as a strong prior, not a neutral starting guess.
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
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `KNOWLEDGE` or `OTHER`, not `INSTRUCTION_LINE`.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or method families, not for generic how-to or cookbook lesson headings.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- If `span_code` is `N` (outside recipe), default to `OTHER` unless the line clearly teaches reusable cooking explanation/reference prose; only use recipe-structure labels when nearby rows in the same slice show immediate recipe-local evidence.
- If a row is plausible under its current deterministic label, leave it there.
- Only use `HOWTO_SECTION` when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the entire line is a short heading-shaped header.
- A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `KNOWLEDGE` or `OTHER`.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `KNOWLEDGE` or `OTHER`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay `KNOWLEDGE` when surrounding rows are explanatory prose.
- First-person narrative or memoir prose is usually `OTHER`, not recipe structure.
- Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`, not `KNOWLEDGE`.
- Use optional `review_exclusion_reason` only on rows labeled `OTHER` when the text is overwhelmingly obvious junk that should skip knowledge review.
- Allowed `review_exclusion_reason` values: `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- If outside-recipe prose seems useful but not recipe-local, keep it `OTHER` and leave `review_exclusion_reason` empty so the knowledge stage can review it.
- Publisher signup/download prompts and endorsement quote clusters are usually overwhelming obvious junk and may use `review_exclusion_reason`.

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

10) Context: cookbook concept heading introducing explanatory prose
    Line: `Cooking Acids`
    Label: `KNOWLEDGE`

11) Context: front matter or navigation heading
    Line: `Acknowledgments`
    Label: `OTHER`

12) Context: broad outside-recipe action-verb advice
   Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
   Label: `OTHER`

13) Context: general teaching/setup prose, not a recipe step
   Line: `Think about making a grilled cheese sandwich.`
   Label: `OTHER`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `KNOWLEDGE`

15) Context: outside recipe, memoir or narrative prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `OTHER`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>", "review_exclusion_reason": "<OPTIONAL_REASON>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) The only allowed keys are `atomic_index`, `label`, and optional `review_exclusion_reason`.

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
    by_atomic_index: Mapping[int, AtomicLineCandidate] | None = None,
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
            by_atomic_index=by_atomic_index,
        ),
    )
    rendered = rendered.replace("{{TARGETS_ROWS}}", rendered_targets)
    return rendered.strip() + "\n"


def build_line_role_label_code_by_label(
    labels: Sequence[str] | None = None,
) -> dict[str, str]:
    resolved_labels = [str(label) for label in (labels or FREEFORM_LABELS)]
    return _build_label_code_by_label(resolved_labels)


def serialize_line_role_model_row(
    *,
    atomic_index: int,
    deterministic_label: str,
    current_line: str,
    label_code_by_label: Mapping[str, str] | None = None,
) -> list[Any]:
    resolved_codes = (
        dict(label_code_by_label)
        if label_code_by_label is not None
        else build_line_role_label_code_by_label()
    )
    normalized_label = str(deterministic_label or "").strip().upper() or "OTHER"
    return [
        int(atomic_index),
        resolved_codes.get(
            normalized_label,
            resolved_codes.get("OTHER", "L0"),
        ),
        str(current_line),
    ]


def build_canonical_line_role_file_prompt(
    *,
    input_path: Path,
    input_payload: Mapping[str, Any] | None = None,
) -> str:
    label_code_legend = _render_label_code_legend(
        build_line_role_label_code_by_label()
    )
    authoritative_rows = _render_authoritative_rows_for_prompt(input_payload)
    template = _load_prompt_template(
        template_path=_FILE_PROMPT_TEMPLATE_PATH,
        fallback=(
            "You are reviewing deterministic canonical line-role labels for cookbook atomic lines.\n\n"
            "Task boundary:\n"
            "- This is a grounded label-correction pass over one ordered contiguous slice of the book.\n"
            "- The authoritative owned shard rows are embedded below.\n"
            "- Reference-only neighboring context may also be embedded below to help you judge boundary rows.\n"
            "- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.\n"
            "- Use only the embedded packet text as evidence.\n"
            "- Do not run shell commands, Python, or any other tools.\n"
            "- Do not describe your plan, reasoning, or heuristics.\n"
            "- Your first response must be the final JSON object.\n"
            "- Treat each row's `label_code` as the deterministic first-pass label you are reviewing, not final truth.\n"
            "- Treat the deterministic label as a strong prior, not a neutral starting guess.\n"
            "- Never invent lines or labels.\n\n"
            "Return strict JSON as a JSON object with one `rows` array:\n"
            '{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>","review_exclusion_reason":"<OPTIONAL_REASON>"}]}\n\n'
            "Task file shape:\n"
            '{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[[122,"Earlier context"]],"rows":[[123,"L4","1 cup flour"]],"context_after_rows":[[124,"Later context"]]}\n\n'
            "Rules:\n"
            "- Output only JSON.\n"
            "- Use only the keys `rows`, `atomic_index`, `label`, and optional `review_exclusion_reason`.\n"
            "- Return one result for every owned input row in `rows`.\n"
            "- Keep output order exactly as requested by the task file's `rows` array.\n"
            "- Treat the task file as one ordered contiguous slice of the book.\n"
            "- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and compact owned `rows` tuples.\n"
            "- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring rows shaped like `[atomic_index, current_line]`.\n"
            "- Never label reference-only neighboring rows and never include their `atomic_index` values in output JSON.\n"
            "- Each row is `[atomic_index, label_code, current_line]`.\n"
            "- Label codes: {{LABEL_CODE_LEGEND}}.\n"
            "- Use each row's tuple slot 2 (`current_line`) as the line to label.\n"
            "- Use neighboring rows in `rows[*]` for local context when needed.\n"
            "- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.\n"
            "- Recompute labels from the task file rows themselves; do not copy example labels from this prompt.\n"
            "- Label distinctions that matter:\n"
            "  - `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.\n"
            "  - `INSTRUCTION_LINE`: imperative action sentences, even when they include time.\n"
            "  - `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.\n"
            "  - `HOWTO_SECTION`: recipe-internal subsection headings that split one recipe into component ingredient lists or step families, such as `FOR THE SAUCE`, `FOR THE DRESSING`, `TO FINISH`, or `FOR SERVING`.\n"
            "  - `RECIPE_VARIANT`: alternate recipe names, variant headers, or short local alternate-version runs inside one recipe.\n"
            "  - `KNOWLEDGE`: explanatory/reference prose, not ordinary recipe structure.\n"
            "  - `OTHER`: navigation, memoir, marketing, dedications, table of contents, or decorative matter.\n"
            "  - `review_exclusion_reason`: use only on `OTHER` rows when the text is overwhelmingly obvious junk that should skip knowledge review; allowed values are `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.\n"
            "- Negative rules:\n"
            "  - Never label a quantity/unit ingredient line as `KNOWLEDGE`.\n"
            "  - Never label an imperative instruction sentence as `KNOWLEDGE`.\n"
            "  - If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.\n"
            "  - `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.\n"
            "  - Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.\n"
            "  - If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `KNOWLEDGE` or `OTHER`, not `INSTRUCTION_LINE`.\n"
            "  - `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.\n"
            "  - If the shard rows are outside recipe context, default to `OTHER` unless the row clearly teaches reusable cooking explanation/reference prose; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.\n"
            "  - If a row is plausible under its current deterministic label, leave it there.\n"
            "  - Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.\n"
            "  - A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.\n"
            "  - A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the whole line is a short heading-shaped header.\n"
            "  - A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.\n"
            "  - Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `KNOWLEDGE` or `OTHER`.\n"
            "  - If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `KNOWLEDGE` or `OTHER`, not `HOWTO_SECTION`.\n"
            "  - Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay `KNOWLEDGE` when surrounding rows are explanatory prose.\n"
            "  - First-person narrative or memoir prose is usually `OTHER`, not recipe structure.\n"
            "  - Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`, not `KNOWLEDGE`.\n"
            "  - Publisher signup/download prompts and endorsement quote clusters are usually overwhelming obvious junk and may use `review_exclusion_reason`.\n"
            "  - Dedications, front matter, and table-of-contents entries are usually `OTHER`.\n\n"
            "{{PACKET_CONTEXT_BLOCK}}"
            "{{REFERENCE_CONTEXT_BLOCK}}"
            "Authoritative owned shard rows (each row is [atomic_index, label_code, current_line]):\n"
            "<BEGIN_AUTHORITATIVE_ROWS>\n"
            "{{AUTHORITATIVE_ROWS}}\n"
            "<END_AUTHORITATIVE_ROWS>\n"
        ),
    )
    rendered = template.replace("{{INPUT_PATH}}", str(input_path))
    rendered = rendered.replace("{{LABEL_CODE_LEGEND}}", label_code_legend)
    rendered = rendered.replace(
        "{{PACKET_CONTEXT_BLOCK}}",
        _render_packet_context_block(input_payload),
    )
    rendered = rendered.replace(
        "{{REFERENCE_CONTEXT_BLOCK}}",
        _render_reference_context_block(input_payload),
    )
    rendered = rendered.replace("{{AUTHORITATIVE_ROWS}}", authoritative_rows)
    return rendered.strip() + "\n"


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


def _render_authoritative_rows_for_prompt(
    input_payload: Mapping[str, Any] | None,
) -> str:
    rows = list((dict(input_payload or {})).get("rows") or [])
    rendered_rows: list[str] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            rendered_rows.append(json.dumps(list(row), ensure_ascii=False))
        elif isinstance(row, Mapping):
            rendered_rows.append(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
            )
    return "\n".join(rendered_rows) if rendered_rows else "[no shard rows available]"


def _render_reference_context_block(
    input_payload: Mapping[str, Any] | None,
) -> str:
    payload = dict(input_payload or {})
    context_before_rows = list(payload.get("context_before_rows") or [])
    context_after_rows = list(payload.get("context_after_rows") or [])
    if not context_before_rows and not context_after_rows:
        return ""

    def _render_rows(rows: Sequence[Any]) -> str:
        rendered_rows: list[str] = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                rendered_rows.append(json.dumps(list(row), ensure_ascii=False))
            elif isinstance(row, Mapping):
                rendered_rows.append(
                    json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
                )
        return "\n".join(rendered_rows) if rendered_rows else "[none]"

    lines = [
        "Reference-only neighboring context:",
        "- These neighboring rows are for context only. Do not label them.",
        "- Never include any `atomic_index` from neighboring context in output JSON.",
        "- `context_before_rows` and `context_after_rows` use `[atomic_index, current_line]` tuples.",
        "<BEGIN_CONTEXT_BEFORE_ROWS>",
        _render_rows(context_before_rows),
        "<END_CONTEXT_BEFORE_ROWS>",
        "<BEGIN_CONTEXT_AFTER_ROWS>",
        _render_rows(context_after_rows),
        "<END_CONTEXT_AFTER_ROWS>",
        "",
    ]
    return "\n".join(lines)


def _render_packet_context_block(input_payload: Mapping[str, Any] | None) -> str:
    payload = dict(input_payload or {})
    summary = str(payload.get("packet_summary") or "").strip()
    default_posture = str(payload.get("default_posture") or "").strip()
    packet_mode = str(payload.get("packet_mode") or "").strip()
    context_confidence = str(payload.get("context_confidence") or "").strip()
    flip_policy = [
        str(item).strip()
        for item in (payload.get("flip_policy") or [])
        if str(item).strip()
    ]
    strong_signals = [
        str(item).strip()
        for item in (payload.get("strong_signals") or [])
        if str(item).strip()
    ]
    weak_signals = [
        str(item).strip()
        for item in (payload.get("weak_signals") or [])
        if str(item).strip()
    ]
    example_files = [
        str(item).strip()
        for item in (payload.get("example_files") or [])
        if str(item).strip()
    ]
    howto_availability = str(payload.get("howto_section_availability") or "").strip()
    howto_policy = str(payload.get("howto_section_policy") or "").strip()
    raw_howto_evidence_count = payload.get("howto_section_evidence_count")
    try:
        howto_evidence_count = int(raw_howto_evidence_count)
    except (TypeError, ValueError):
        howto_evidence_count = 0
    if not any(
        (
            summary,
            default_posture,
            packet_mode,
            context_confidence,
            flip_policy,
            strong_signals,
            weak_signals,
            example_files,
            howto_availability,
            howto_policy,
            howto_evidence_count,
        )
    ):
        return ""
    lines = ["Packet-local guidance:"]
    if summary:
        lines.append(f"- Packet summary: {summary}")
    if packet_mode or context_confidence:
        lines.append(
            "- Packet mode: "
            f"{packet_mode or 'unknown'}"
            + (
                f" (confidence: {context_confidence})"
                if context_confidence
                else ""
            )
        )
    if default_posture:
        lines.append(f"- Default posture: {default_posture}")
    if howto_availability:
        lines.append(
            "- HOWTO_SECTION availability: "
            f"{howto_availability} (evidence rows: {howto_evidence_count})"
        )
    if howto_policy:
        lines.append(f"- HOWTO_SECTION policy: {howto_policy}")
    for item in flip_policy:
        lines.append(f"- Flip policy: {item}")
    for item in strong_signals:
        lines.append(f"- Strong signal: {item}")
    for item in weak_signals:
        lines.append(f"- Weak signal: {item}")
    if example_files:
        lines.append("- Repo-written contrast examples: " + ", ".join(example_files))
    return "\n".join(lines) + "\n\n"


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
    by_atomic_index: Mapping[int, AtomicLineCandidate] | None,
) -> str:
    allowed_labels = {str(label).strip().upper() for label in FREEFORM_LABELS}
    resolved_by_atomic_index = (
        dict(by_atomic_index)
        if by_atomic_index is not None
        else build_atomic_index_lookup(targets)
    )
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
        prev_text, next_text = get_atomic_line_neighbor_texts(
            candidate,
            by_atomic_index=resolved_by_atomic_index,
        )
        rows.append(
            "ctx:"
            f"{atomic_index}|prev={_escape_compact_text(_context_text(prev_text))}"
            f"|line={_escape_compact_text(_context_text(candidate.text))}"
            f"|next={_escape_compact_text(_context_text(next_text))}"
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
