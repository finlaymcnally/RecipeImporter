from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    build_atomic_index_lookup,
    get_atomic_line_neighbor_texts,
)

LineRolePromptFormat = Literal["compact_v1"]

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_INLINE_TEMPLATE_PATH = _PROMPT_ROOT / "canonical-line-role-v1.prompt.md"
_FILE_PROMPT_TEMPLATE_PATH = _PROMPT_ROOT / "line-role.canonical.v1.prompt.md"
_DEFAULT_ALLOWED_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
    "NONRECIPE_CANDIDATE",
    "NONRECIPE_EXCLUDE",
)

_INLINE_TEMPLATE_FALLBACK = """You are labeling canonical line-role routing labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Do not run shell commands, Python, or any other tools.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input shape:
- Treat the targets as one ordered contiguous slice of the book.
- Each target row is `atomic_index|current_line`.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `NONRECIPE_CANDIDATE`, not `INSTRUCTION_LINE`.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or method families, not for generic how-to or cookbook lesson headings.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone.
- Only use `HOWTO_SECTION` when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the entire line is a short heading-shaped header.
- A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
- Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
- Variant context is local, not sticky. Do not let a nearby `Variations` run swallow a fresh recipe start.
- If a short title-like line is immediately followed by a strict yield line or ingredient rows, prefer `RECIPE_TITLE`, not `RECIPE_VARIANT`, even when earlier nearby rows were variants.
- A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE` when it appears between a recipe title and ingredient or method structure; do not downgrade it to `RECIPE_NOTES`.
- Local row evidence wins over shaky prior span assumptions. A title-like line followed by yield or ingredients can still be `RECIPE_TITLE` even if upstream recipe-span state is missing or noisy.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `NONRECIPE_CANDIDATE`.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `NONRECIPE_CANDIDATE`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` stay `NONRECIPE_CANDIDATE` only when surrounding rows clearly carry reusable explanatory prose.
- A lone question-style or topic heading such as `What is Heat?` or `Balancing Fat` usually stays `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose worth knowledge review.
- Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` usually stay `NONRECIPE_EXCLUDE` with `navigation` unless nearby rows prove one live recipe.
- First-person narrative or memoir framing is usually `NONRECIPE_EXCLUDE` when it reads like foreword/introduction setup rather than reusable cooking knowledge.
- Endorsements, acknowledgments, foreword/introduction framing, memoir setup, and broad book-encouragement prose usually stay `NONRECIPE_EXCLUDE`; use `NONRECIPE_CANDIDATE` only when the line itself carries reusable cooking knowledge.
- Use optional `exclusion_reason` only on outside-recipe rows labeled `NONRECIPE_EXCLUDE`.
- Allowed `exclusion_reason` values: `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- Use `NONRECIPE_EXCLUDE` only for obvious junk that should never reach the later knowledge stage.

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

6) Context: inside recipe explanatory prose
   Line: `Copper pans conduct heat quickly and evenly, so temperature changes show up fast.`
   Label: `RECIPE_NOTES`

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
    Label: `NONRECIPE_CANDIDATE`

11) Context: front matter or navigation heading
    Line: `Acknowledgments`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `front_matter`

12) Context: broad outside-recipe action-verb advice
   Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
   Label: `NONRECIPE_CANDIDATE`

13) Context: general teaching/setup prose, not a recipe step
   Line: `Think about making a grilled cheese sandwich.`
   Label: `NONRECIPE_CANDIDATE`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `NONRECIPE_CANDIDATE`

15) Context: outside recipe, memoir or introduction framing prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `front_matter`

16) Context: outside recipe, reusable lesson prose with brief first-person framing
    Line: `Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what.`
    Label: `NONRECIPE_CANDIDATE`

17) Context: outside recipe, short declarative lesson line in a knowledge cluster
    Line: `Foods that are too dry can be corrected with a bit more fat.`
    Label: `NONRECIPE_CANDIDATE`

18) Context: outside recipe, lone question heading without explanatory support
    Line: `What is Heat?`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

19) Context: front matter or contents heading, not a live recipe
    Line: `The Four Elements of Good Cooking`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

20) Context: contents-style seasonal title list
    Line: `Winter: Roasted Radicchio and Roquefort`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

21) Context: outside recipe, obvious imperative prep step with nearby recipe structure
    Line: `Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle.`
    Label: `INSTRUCTION_LINE`

22) Context: short variation follow-up line after `Variations`
    Line: `To add a little heat, add 1 teaspoon minced jalapeño.`
    Label: `RECIPE_VARIANT`

23) Context: fresh recipe start after nearby variants, followed by yield and ingredients
    Line: `Lemon Vinaigrette`
    Label: `RECIPE_TITLE`

24) Context: strict yield header between a recipe title and ingredients
    Line: `Makes about 1/2 cup`
    Label: `YIELD_LINE`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>", "exclusion_reason": "<OPTIONAL_REASON>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) The only allowed keys are `atomic_index`, `label`, and optional `exclusion_reason`.
5) Final answer must be the JSON array only.

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
    resolved_allowed = [
        str(label) for label in (allowed_labels or _DEFAULT_ALLOWED_LABELS)
    ]
    resolved_format = _normalize_prompt_format(prompt_format)
    rendered_targets = serialize_line_role_targets(
        targets,
        allowed_labels=resolved_allowed,
        deterministic_labels_by_atomic_index=deterministic_labels_by_atomic_index,
        escalation_reasons_by_atomic_index=escalation_reasons_by_atomic_index,
    )
    template = _load_prompt_template(
        template_path=_INLINE_TEMPLATE_PATH,
        fallback=_INLINE_TEMPLATE_FALLBACK,
    )
    rendered = template.replace("{{ALLOWED_LABELS}}", ", ".join(resolved_allowed))
    rendered = rendered.replace(
        "{{PRECEDENCE_ORDER}}",
        "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > "
        "INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > "
        "NONRECIPE_EXCLUDE > NONRECIPE_CANDIDATE",
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
    resolved_labels = [
        str(label) for label in (labels or _DEFAULT_ALLOWED_LABELS)
    ]
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
            "You are labeling canonical line-role route labels for cookbook atomic lines.\n\n"
            "Task boundary:\n"
            "- This is a grounded label-correction pass over one ordered contiguous slice of the book.\n"
            "- The authoritative owned shard rows are embedded below.\n"
            "- Reference-only neighboring context may also be embedded below to help you judge boundary rows.\n"
            "- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.\n"
            "- Use only the embedded raw shard rows and neighboring context as evidence.\n"
            "- Do not run shell commands, Python, or any other tools.\n"
            "- Do not describe your plan, reasoning, or heuristics.\n"
            "- Your first response must be the final JSON object.\n"
            "- Never invent lines or labels.\n\n"
            "Return strict JSON as a JSON object with one `rows` array:\n"
            '{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>","exclusion_reason":"<OPTIONAL_REASON>"}]}\n\n'
            "Task file shape:\n"
            '{"v":2,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[[122,"Earlier context"]],"rows":[[123,"1 cup flour"]],"context_after_rows":[[124,"Later context"]]}\n\n'
            "Rules:\n"
            "- Output only JSON.\n"
            "- Your final answer must be that JSON object and nothing else.\n"
            "- Use only the keys `rows`, `atomic_index`, `label`, and optional `exclusion_reason`.\n"
            "- Return one result for every owned input row in `rows`.\n"
            "- Keep output order exactly as requested by the task file's `rows` array.\n"
            "- Treat the task file as one ordered contiguous slice of the book.\n"
            "- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and owned `rows` tuples.\n"
            "- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring rows shaped like `[atomic_index, current_line]`.\n"
            "- Never label reference-only neighboring rows and never include their `atomic_index` values in output JSON.\n"
            "- Each row is `[atomic_index, current_line]`.\n"
            "- Use the second tuple item as the line to label.\n"
            "- Use neighboring rows in `rows[*]` for local context when needed.\n"
            "- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.\n"
            "- Label distinctions that matter:\n"
            "  - `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.\n"
            "  - `INSTRUCTION_LINE`: imperative action sentences, even when they include time.\n"
            "  - `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.\n"
            "  - `HOWTO_SECTION`: recipe-internal subsection headings that split one recipe into component ingredient lists or step families.\n"
            "  - `RECIPE_VARIANT`: alternate recipe names, variant headers, or short local alternate-version runs inside one recipe.\n"
            "  - `RECIPE_NOTES`: recipe-local prose that belongs with the current recipe but is not ingredient or instruction structure.\n"
            "  - `NONRECIPE_CANDIDATE`: outside-recipe material that is not recipe-local and should be sent to knowledge later.\n"
            "  - `NONRECIPE_EXCLUDE`: obvious outside-recipe junk that should never reach knowledge.\n"
            "  - `exclusion_reason`: use only on `NONRECIPE_EXCLUDE` rows; allowed values are `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.\n"
            "- Negative rules:\n"
            "  - If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.\n"
            "  - `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.\n"
            "  - Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.\n"
            "  - If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `NONRECIPE_CANDIDATE`, not `INSTRUCTION_LINE`.\n"
            "  - If the shard rows are outside recipe context, default to `NONRECIPE_CANDIDATE`; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.\n"
            "  - Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.\n"
            "  - A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.\n"
            "  - A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the whole line is a short heading-shaped header.\n"
            "  - A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.\n"
            "  - Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.\n"
            "  - Variant context is local, not sticky. Do not let a nearby `Variations` run swallow a fresh recipe start.\n"
            "  - If a short title-like line is immediately followed by a strict yield line or ingredient rows, prefer `RECIPE_TITLE`, not `RECIPE_VARIANT`, even when earlier nearby rows were variants.\n"
            "  - A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE` when it appears between a recipe title and ingredient or method structure; do not downgrade it to `RECIPE_NOTES`.\n"
            "  - Local row evidence wins over shaky prior span assumptions. A title-like line followed by yield or ingredients can still be `RECIPE_TITLE` even if upstream recipe-span state is missing or noisy.\n"
            "  - Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually outside-recipe labels.\n"
            "  - If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `NONRECIPE_CANDIDATE`, not `HOWTO_SECTION`.\n"
            "  - Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.\n"
            "  - Use optional `exclusion_reason` only on rows labeled `NONRECIPE_EXCLUDE` when the text is overwhelmingly obvious junk.\n"
            "\n"
            "{{PACKET_CONTEXT_BLOCK}}"
            "{{REFERENCE_CONTEXT_BLOCK}}"
            "Authoritative owned shard rows (each row is [atomic_index, current_line]):\n"
            "<BEGIN_AUTHORITATIVE_ROWS>\n"
            "{{AUTHORITATIVE_ROWS}}\n"
            "<END_AUTHORITATIVE_ROWS>\n"
        ),
    )
    rendered = template.replace("{{INPUT_PATH}}", str(input_path))
    rendered = rendered.replace("{{LABEL_CODE_LEGEND}}", label_code_legend)
    rendered = rendered.replace(
        "{{PACKET_CONTEXT_BLOCK}}",
        _render_shard_context_block(input_payload),
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
) -> str:
    del allowed_labels, deterministic_labels_by_atomic_index, escalation_reasons_by_atomic_index
    lines: list[str] = []
    for candidate in targets:
        lines.append(
            _serialize_compact_target_row(
                atomic_index=int(candidate.atomic_index),
                current_line=str(candidate.text),
            )
        )
    return "\n".join(lines)


def _line_role_row_format_text(prompt_format: LineRolePromptFormat) -> str:
    del prompt_format
    return (
        "One pipe-delimited row per line: "
        "atomic_index|current_line. "
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


def _render_shard_context_block(input_payload: Mapping[str, Any] | None) -> str:
    del input_payload
    return ""


def _build_label_code_by_label(labels: Sequence[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw_label in labels:
        normalized = str(raw_label or "").strip().upper()
        if not normalized or normalized in output:
            continue
        output[normalized] = f"L{len(output)}"
    return output


def _render_label_code_legend(code_by_label: Mapping[str, str]) -> str:
    return ", ".join(f"{code}={label}" for label, code in code_by_label.items())


def _normalize_prompt_format(value: str) -> LineRolePromptFormat:
    del value
    return "compact_v1"


def _serialize_compact_target_row(
    *,
    atomic_index: int,
    current_line: str,
) -> str:
    return f"{int(atomic_index)}|{_escape_compact_text(current_line)}"


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
    del deterministic_labels_by_atomic_index, escalation_reasons_by_atomic_index
    resolved_by_atomic_index = (
        dict(by_atomic_index)
        if by_atomic_index is not None
        else build_atomic_index_lookup(targets)
    )
    rows: list[str] = []
    for candidate in targets:
        if not _should_render_context_window(candidate):
            continue
        prev_text, next_text = get_atomic_line_neighbor_texts(
            candidate,
            by_atomic_index=resolved_by_atomic_index,
        )
        rows.append(
            "ctx:"
            f"{int(candidate.atomic_index)}|prev={_escape_compact_text(_context_text(prev_text))}"
            f"|line={_escape_compact_text(_context_text(candidate.text))}"
            f"|next={_escape_compact_text(_context_text(next_text))}"
        )
    return "\n".join(rows) if rows else "(none)"


def _should_render_context_window(
    candidate: AtomicLineCandidate,
) -> bool:
    del candidate
    return True


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
