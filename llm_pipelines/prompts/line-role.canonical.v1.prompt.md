You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

Task boundary:
- This is a grounded label-correction pass over one ordered contiguous slice of the book.
- The authoritative shard rows are embedded below.
- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.
- Use only the embedded shard rows as evidence.
- Do not run shell commands, Python, or any other tools.
- Do not describe your plan, reasoning, or heuristics.
- Your first response must be the final JSON object.
- Treat each row's `label_code` as the deterministic first-pass label you are reviewing, not final truth.
- Treat the deterministic label as a strong prior, not a neutral starting guess.
- Never invent lines or labels.

Return strict JSON as a JSON object with one `rows` array:
{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>"}]}

Task file shape:
{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","rows":[[123,"L4","1 cup flour"]]}

Rules:
- Output only JSON.
- Your final answer must be that JSON object and nothing else.
- Use only the keys `rows`, `atomic_index`, and `label`.
- Return one result for every input row.
- Keep row order exactly as requested by the task file.
- Treat the task file as one ordered contiguous slice of the book.
- The task file has one version marker `v`, one `shard_id`, and compact `rows` tuples.
- Each row is `[atomic_index, label_code, current_line]`.
- Label codes: {{LABEL_CODE_LEGEND}}.
- Convert each `label_code` into the correct full label string; never return label codes in output.
- Use each row's tuple slot 2 (`current_line`) as the line to label.
- Use neighboring rows in `rows[*]` for local context when needed.
- Recompute labels from the task file rows themselves; do not copy example labels from this prompt.
- Label distinctions that matter:
  - `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.
  - `INSTRUCTION_LINE`: imperative action sentences, even when they include time.
  - `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.
  - `HOWTO_SECTION`: recipe-internal subsection headings that split one recipe into component ingredient lists or step families, such as `FOR THE SAUCE`, `FOR THE DRESSING`, `TO FINISH`, or `FOR SERVING`.
  - `RECIPE_VARIANT`: alternate recipe names or variant headers inside a recipe.
  - `KNOWLEDGE`: explanatory/reference prose, not ordinary recipe structure.
  - `OTHER`: navigation, memoir, marketing, dedications, table of contents, or decorative matter.
- Negative rules:
  - Never label a quantity/unit ingredient line as `KNOWLEDGE`.
  - Never label an imperative instruction sentence as `KNOWLEDGE`.
  - If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
  - `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
  - Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
  - If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `KNOWLEDGE` or `OTHER`, not `INSTRUCTION_LINE`.
  - If the shard rows are outside recipe context, default to `KNOWLEDGE` or `OTHER`; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.
  - If a row is plausible under its current deterministic label, leave it there.
  - Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.
  - A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
  - Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `KNOWLEDGE` or `OTHER`.
  - If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `KNOWLEDGE` or `OTHER`, not `HOWTO_SECTION`.
  - Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay `KNOWLEDGE` when surrounding rows are explanatory prose.
  - First-person narrative or memoir prose is usually `OTHER`, not recipe structure.
  - Dedications, front matter, and table-of-contents entries are usually `OTHER`.

{{PACKET_CONTEXT_BLOCK}}

Authoritative shard rows (each row is [atomic_index, label_code, current_line]):
<BEGIN_AUTHORITATIVE_ROWS>
{{AUTHORITATIVE_ROWS}}
<END_AUTHORITATIVE_ROWS>
