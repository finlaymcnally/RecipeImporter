You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

Task boundary:
- This is a grounded label-correction pass over one ordered contiguous slice of the book.
- The authoritative owned shard rows are embedded below.
- Reference-only neighboring context may also be embedded below to help you judge boundary rows.
- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.
- Use only the embedded packet text as evidence.
- Do not run shell commands, Python, or any other tools.
- Do not describe your plan, reasoning, or heuristics.
- Your first response must be the final JSON object.
- Treat each row's `label_code` as the deterministic first-pass label you are reviewing, not final truth.
- Treat the deterministic label as a weak hint only. Recompute from the row text and local context; do not preserve or prefer a label just because it came from the deterministic seed.
- Never invent lines or labels.

Return strict JSON as a JSON object with one `rows` array:
{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>","review_exclusion_reason":"<OPTIONAL_REASON>"}]}

Task file shape:
{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[[122,"Earlier context"]],"rows":[[123,"L4","1 cup flour"]],"context_after_rows":[[124,"Later context"]]}

Rules:
- Output only JSON.
- Your final answer must be that JSON object and nothing else.
- Use only the keys `rows`, `atomic_index`, `label`, and optional `review_exclusion_reason`.
- Return one result for every owned input row in `rows`.
- Keep output order exactly as requested by the task file's `rows` array.
- Treat the task file as one ordered contiguous slice of the book.
- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and compact owned `rows` tuples.
- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring rows shaped like `[atomic_index, current_line]`.
- Never label reference-only neighboring rows and never include their `atomic_index` values in output JSON.
- Each row is `[atomic_index, label_code, current_line]`.
- Label codes: {{LABEL_CODE_LEGEND}}.
- Convert each `label_code` into the correct full label string; never return label codes in output.
- Use each row's tuple slot 2 (`current_line`) as the line to label.
- Use neighboring rows in `rows[*]` for local context when needed.
- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.
- Recompute labels from the task file rows themselves; do not copy example labels from this prompt.
- Label distinctions that matter:
  - `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.
  - `INSTRUCTION_LINE`: imperative action sentences, even when they include time.
  - `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.
  - `HOWTO_SECTION`: recipe-internal subsection headings that split one recipe into component ingredient lists or step families, such as `FOR THE SAUCE`, `FOR THE DRESSING`, `TO FINISH`, or `FOR SERVING`.
  - `RECIPE_VARIANT`: alternate recipe names, variant headers, or short local alternate-version runs inside one recipe.
  - `KNOWLEDGE`: recipe-local explanatory/reference prose, not ordinary recipe structure.
  - `OTHER`: navigation, memoir, marketing, dedications, table of contents, or decorative matter.
- Negative rules:
  - Never label a quantity/unit ingredient line as `KNOWLEDGE`.
  - Never label an imperative instruction sentence as `KNOWLEDGE`.
  - If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
  - `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
  - Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
  - If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer review-eligible `OTHER`, not `INSTRUCTION_LINE`.
  - Outside recipes, useful lesson prose still stays review-eligible `OTHER`; the later knowledge stage decides semantic `KNOWLEDGE` versus `OTHER`.
  - Short declarative teaching lines about reusable cooking rules should still stay review-eligible `OTHER` in this stage.
  - `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
  - If the shard rows are outside recipe context, default to review-eligible `OTHER`; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.
  - If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone; do not use the deterministic seed as the tie-breaker.
  - Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.
  - A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
  - A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the whole line is a short heading-shaped header.
  - A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
  - Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
  - Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually review-eligible `OTHER`.
  - If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer review-eligible `OTHER`, not `HOWTO_SECTION`.
  - Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay review-eligible `OTHER` when surrounding rows are explanatory prose.
  - A lone question-style topic heading such as `What is Heat?` should stay `OTHER` unless nearby rows clearly teach that concept.
  - Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` stay `OTHER` until nearby rows prove one live recipe.
  - First-person narrative or memoir prose is usually `OTHER`, not recipe structure.
  - Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`; only overwhelming obvious junk should also get `review_exclusion_reason`.
- Dedications, front matter, and table-of-contents entries are usually `OTHER`.
- Use optional `review_exclusion_reason` only on rows labeled `OTHER` when the text is overwhelmingly obvious junk that should skip knowledge review.
- Allowed `review_exclusion_reason` values: `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- If outside-recipe prose seems useful but not recipe-local, keep it `OTHER` and leave `review_exclusion_reason` empty so the knowledge stage can review it.
- Publisher signup/download prompts and endorsement quote clusters are usually overwhelming obvious junk and may use `review_exclusion_reason`.

{{PACKET_CONTEXT_BLOCK}}

{{REFERENCE_CONTEXT_BLOCK}}

Authoritative owned shard rows (each row is [atomic_index, label_code, current_line]):
<BEGIN_AUTHORITATIVE_ROWS>
{{AUTHORITATIVE_ROWS}}
<END_AUTHORITATIVE_ROWS>
