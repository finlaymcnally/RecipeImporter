from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_FILE_PROMPT_TEMPLATE_PATH = _PROMPT_ROOT / "line-role.canonical.v1.prompt.md"
_SHARED_CONTRACT_TEMPLATE_PATH = _PROMPT_ROOT / "line-role.shared-contract.v1.md"
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

_SHARED_CONTRACT_FALLBACK = """Label distinctions that matter:
- `RECIPE_TITLE`: fresh recipe names that start a new recipe, especially when the next rows turn into yield, ingredients, or method.
- `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.
- `INSTRUCTION_LINE`: recipe-local imperative action sentences, even when they include time.
- `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or step families.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- `YIELD_LINE`: stand-alone yield or serving lines such as `SERVES 4` or `Makes about 1/2 cup`.
- `RECIPE_VARIANT`: alternate recipe names, variant headers, or short local alternate-version runs inside one recipe.
- `RECIPE_NOTES`: recipe-local prose that belongs with the current recipe but is not ingredient or instruction structure.
- `NONRECIPE_CANDIDATE`: outside-recipe material that is not recipe-local and should be sent to knowledge later.
- `NONRECIPE_EXCLUDE`: obvious outside-recipe junk that should never reach knowledge.

Negative rules:
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, do not call it `INSTRUCTION_LINE`.
- Outside recipe, broad coaching, exhortation, or rhetorical setup usually stays `NONRECIPE_EXCLUDE`; use `NONRECIPE_CANDIDATE` only when the row itself states portable cooking knowledge that would still help a cook if quoted alone.
- If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone.
- If the shard rows are outside recipe context, decide in two steps: first discard obvious fluff as `NONRECIPE_EXCLUDE`, then use `NONRECIPE_CANDIDATE` only for rows that clearly stand on their own as portable cooking knowledge.
- Nearby lesson rows can help you understand context, but they do not rescue a weak row into `NONRECIPE_CANDIDATE` when that row itself is just coaching, setup, rhetoric, or author voice.
- Only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.
- Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the whole line is a short heading-shaped header.
- A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
- Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
- Variant context is local, not sticky. End a nearby `Variations` run when a fresh title-like line is followed by a strict yield line or ingredient rows.
- Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw` -> `Serves 4 generously` -> `1/2 medium red onion, sliced thinly`.
- If a short title-like line is immediately followed by a strict yield line or ingredient rows, reset to a new recipe: prefer `RECIPE_TITLE`, not `RECIPE_VARIANT`, even when earlier nearby rows were variants.
- A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE` when it appears between a recipe title and ingredient or method structure; do not downgrade it to `RECIPE_NOTES`.
- Local row evidence wins over shaky prior span assumptions. A title-like line followed by yield or ingredients can still be `RECIPE_TITLE` even if upstream recipe-span state is missing or noisy.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually outside-recipe labels.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `NONRECIPE_CANDIDATE`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` stay `NONRECIPE_CANDIDATE` only when surrounding rows clearly carry reusable explanatory prose.
- A lone question-style or topic heading such as `What is Heat?` or `Balancing Fat` usually stays `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose worth knowledge review.
- Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.
- Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` usually stay `NONRECIPE_EXCLUDE` unless nearby rows prove one live recipe.
- Endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.
- Obvious praise blurbs, foreword or preface setup, book-thesis or manifesto framing, and `this book will teach you ...` jacket-copy promises usually stay `NONRECIPE_EXCLUDE`, not `NONRECIPE_CANDIDATE`.
- First-person narrative or memoir framing is usually `NONRECIPE_EXCLUDE` when it reads like foreword/introduction setup rather than reusable cooking knowledge.
- Endorsements, acknowledgments, foreword/introduction framing, memoir setup, and broad book-encouragement prose usually stay `NONRECIPE_EXCLUDE`; use `NONRECIPE_CANDIDATE` only when the line itself carries reusable cooking knowledge.
- Dedications, acknowledgments, author biography, restaurant backstory, travel scenes, childhood food memories, and chef-origin stories usually stay `NONRECIPE_EXCLUDE` even when they mention real dishes, ingredients, or kitchen lessons.
- Broad encouragement or manifesto prose such as `you can become a great cook`, `keep reading and I'll teach you how`, or `trust your palate` usually stays `NONRECIPE_EXCLUDE`, not `NONRECIPE_CANDIDATE`.
- Short split coaching fragments such as `Taste. It will need salt.` or `Trust your palate.` usually stay `NONRECIPE_EXCLUDE` unless nearby rows make them part of a concrete standalone lesson rather than book voice or encouragement.
- Do not rescue a memoir or intro paragraph into `NONRECIPE_CANDIDATE` just because it contains one true cooking claim near the end. If the row still reads mainly like story, framing, or inspiration, keep it `NONRECIPE_EXCLUDE`.
- Use `NONRECIPE_CANDIDATE` only when the row itself would be worth retrieving later as a standalone cooking concept without needing the memoir, chapter setup, or book-thesis wrapper around it.
- Mixed anecdote-plus-moral rows usually stay `NONRECIPE_EXCLUDE`. If a later row states the reusable lesson directly and can stand on its own, that later row may be `NONRECIPE_CANDIDATE`.

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

12) Context: broad outside-recipe action-verb advice
    Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
    Label: `NONRECIPE_CANDIDATE`

13) Context: general teaching/setup prose, rhetorical framing, not a recipe step
    Line: `Think about making a grilled cheese sandwich.`
    Label: `NONRECIPE_EXCLUDE`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `NONRECIPE_CANDIDATE`

15) Context: outside recipe, memoir or introduction framing prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `NONRECIPE_EXCLUDE`

16) Context: outside recipe, reusable lesson prose with brief first-person framing
    Line: `Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what.`
    Label: `NONRECIPE_CANDIDATE`

17) Context: outside recipe, short declarative lesson line in a knowledge cluster
    Line: `Foods that are too dry can be corrected with a bit more fat.`
    Label: `NONRECIPE_CANDIDATE`

18) Context: outside recipe, lone question heading without explanatory support
    Line: `What is Heat?`
    Label: `NONRECIPE_EXCLUDE`

19) Context: front matter or contents heading, not a live recipe
    Line: `The Four Elements of Good Cooking`
    Label: `NONRECIPE_EXCLUDE`

20) Context: contents-style seasonal title list
    Line: `Winter: Roasted Radicchio and Roquefort`
    Label: `NONRECIPE_EXCLUDE`

21) Context: outside recipe, publisher-style promise or thesis framing
    Line: `This book will teach you the four elements of good cooking.`
    Label: `NONRECIPE_EXCLUDE`

22) Context: outside recipe, obvious imperative prep step with nearby recipe structure
    Line: `Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle.`
    Label: `INSTRUCTION_LINE`

23) Context: short variation follow-up line after `Variations`
    Line: `To add a little heat, add 1 teaspoon minced jalapeño.`
    Label: `RECIPE_VARIANT`

24) Context: nearby rows are `Variations`, variant prose, then a fresh recipe start followed by yield and ingredients
    Line: `Bright Cabbage Slaw`
    Label: `RECIPE_TITLE`

25) Context: strict yield header immediately after that fresh recipe title
    Line: `Serves 4 generously`
    Label: `YIELD_LINE`

26) Context: ingredient row immediately after the reset title and yield
    Line: `1/2 medium red onion, sliced thinly`
    Label: `INGREDIENT_LINE`

27) Context: outside recipe, memoir anecdote with an embedded cooking takeaway
    Line: `After years of cooking, I finally understood why that bowl of polenta needed more salt.`
    Label: `NONRECIPE_EXCLUDE`

28) Context: outside recipe, explicit standalone lesson stated after the anecdote
    Line: `Taste constantly as you cook, and adjust seasoning before serving.`
    Label: `NONRECIPE_CANDIDATE`

29) Context: outside recipe, broad book promise or encouragement prose
    Line: `Keep reading and I'll teach you how to cook with confidence.`
    Label: `NONRECIPE_EXCLUDE`

30) Context: outside recipe, short split coaching fragment without standalone reference value
    Line: `Taste. It will need salt.`
    Label: `NONRECIPE_EXCLUDE`
"""

def build_line_role_label_code_by_label(
    labels: Sequence[str] | None = None,
) -> dict[str, str]:
    resolved_labels = [
        str(label) for label in (labels or _DEFAULT_ALLOWED_LABELS)
    ]
    return _build_label_code_by_label(resolved_labels)


def build_line_role_shared_contract_block() -> str:
    return _load_prompt_template(
        template_path=_SHARED_CONTRACT_TEMPLATE_PATH,
        fallback=_SHARED_CONTRACT_FALLBACK,
    ).strip()


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
            "Return strict JSON as a JSON object with one ordered `rows` array:\n"
            '{"rows":[{"row_id":"r01","label":"<ALLOWED_LABEL>"}]}\n\n'
            "Task file shape:\n"
            '{"v":2,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[{"block_index":209,"text":"Earlier context"}],"rows":[{"row_id":"r01","block_index":210,"text":"1 cup flour"}],"context_after_rows":[{"block_index":211,"text":"Later context"}]}\n\n'
            "Rules:\n"
            "- Output only JSON.\n"
            "- Your final answer must be that JSON object and nothing else.\n"
            "- Use only the top-level key `rows`.\n"
            "- Return exactly one answer row for every owned input row in `rows`.\n"
            "- The task file `rows` array stores ordered row objects with `row_id`, `block_index`, and `text`.\n"
            "- Keep answer rows aligned with the task file's `rows` array and its `row_id` values.\n"
            "- Every owned `row_id` must appear exactly once in the answer.\n"
            "- Finish the full owned-row list; do not stop early.\n"
            "- Treat the task file as one ordered contiguous slice of the book.\n"
            "- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and owned `rows` arrays.\n"
            "- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring row objects with `block_index` and `text`.\n"
            "- Never label reference-only neighboring rows.\n"
            "- Do not label `context_before_rows` or `context_after_rows`; they are for interpretation only.\n"
            "- Use each owned row object's `text` string as the line to label.\n"
            "- Use neighboring row objects in `rows[*]` for local context when needed.\n"
            "- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.\n"
            "- Each output row must contain only `row_id` and `label`.\n"
            "- Return one JSON object with only the top-level key `rows`.\n"
            "\n"
            "Shared labeling contract:\n"
            "{{SHARED_CONTRACT_BLOCK}}\n"
            "\n"
            "{{PACKET_CONTEXT_BLOCK}}"
            "{{REFERENCE_CONTEXT_BLOCK}}"
            "Authoritative owned shard rows:\n"
            "<BEGIN_AUTHORITATIVE_ROWS>\n"
            "{{AUTHORITATIVE_ROWS}}\n"
            "<END_AUTHORITATIVE_ROWS>\n"
        ),
    )
    rendered = template.replace("{{INPUT_PATH}}", str(input_path))
    rendered = rendered.replace("{{LABEL_CODE_LEGEND}}", label_code_legend)
    rendered = rendered.replace(
        "{{SHARED_CONTRACT_BLOCK}}",
        build_line_role_shared_contract_block(),
    )
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


def _render_authoritative_rows_for_prompt(
    input_payload: Mapping[str, Any] | None,
) -> str:
    rows = list((dict(input_payload or {})).get("rows") or [])
    rendered_rows: list[str] = []
    for index, row in enumerate(rows):
        if isinstance(row, (list, tuple)):
            if len(row) >= 3:
                block_index = int(row[1])
                text = str(row[2] or "")
            else:
                block_index = int(row[0])
                text = str(row[1] or "")
            rendered_rows.append(
                json.dumps(
                    {
                        "row_id": f"r{index + 1:02d}",
                        "block_index": block_index,
                        "text": text,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        elif isinstance(row, Mapping):
            row_dict = dict(row)
            rendered_rows.append(
                json.dumps(
                    {
                        "row_id": str(row_dict.get("row_id") or f"r{index + 1:02d}"),
                        "block_index": int(row_dict.get("block_index") or index),
                        "text": str(
                            row_dict.get("current_line")
                            or row_dict.get("text")
                            or ""
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
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
                if len(row) >= 3:
                    block_index = int(row[1])
                    text = str(row[2] or "")
                else:
                    block_index = int(row[0])
                    text = str(row[1] or "")
                rendered_rows.append(
                    json.dumps(
                        {"block_index": block_index, "text": text},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            elif isinstance(row, Mapping):
                row_dict = dict(row)
                rendered_rows.append(
                    json.dumps(
                        {
                            "block_index": int(
                                row_dict.get("block_index")
                                or row_dict.get("atomic_index")
                                or 0
                            ),
                            "text": str(
                                row_dict.get("current_line")
                                or row_dict.get("text")
                                or ""
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
        return "\n".join(rendered_rows) if rendered_rows else "[none]"

    lines = [
        "Reference-only neighboring context:",
        "- These neighboring rows are for context only. Do not label them.",
        "- Neighboring context rows are rendered as row objects with `block_index` and `text`.",
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


def _load_prompt_template(*, template_path: Path, fallback: str) -> str:
    try:
        text = template_path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    normalized = text.strip()
    if not normalized:
        return fallback
    return normalized
