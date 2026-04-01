You are labeling canonical line-role route labels for cookbook atomic lines.

Task boundary:
- This is a grounded label-correction pass over one ordered contiguous slice of the book.
- The authoritative owned shard rows are embedded below.
- Reference-only neighboring context may also be embedded below to help you judge boundary rows.
- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.
- Use only the embedded raw shard rows and neighboring context as evidence.
- Do not run shell commands, Python, or any other tools.
- Do not describe your plan, reasoning, or heuristics.
- Your first response must be the final JSON object.
- Never invent lines or labels.

Return strict JSON as a JSON object with one `rows` array:
{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>","exclusion_reason":"<OPTIONAL_REASON>"}]}

Task file shape:
{"v":2,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[[122,"Earlier context"]],"rows":[[123,"1 cup flour"]],"context_after_rows":[[124,"Later context"]]}

Rules:
- Output only JSON.
- Your final answer must be that JSON object and nothing else.
- Use only the keys `rows`, `atomic_index`, `label`, and optional `exclusion_reason`.
- Return one result for every owned input row in `rows`.
- Keep output order exactly as requested by the task file's `rows` array.
- Treat the task file as one ordered contiguous slice of the book.
- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and owned `rows` tuples.
- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring rows shaped like `[atomic_index, current_line]`.
- Never label reference-only neighboring rows and never include their `atomic_index` values in output JSON.
- Each row is `[atomic_index, current_line]`.
- Use the second tuple item as the line to label.
- Use neighboring rows in `rows[*]` for local context when needed.
- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.
- Label distinctions that matter:
  - `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.
  - `INSTRUCTION_LINE`: imperative action sentences, even when they include time.
  - `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.
  - `HOWTO_SECTION`: recipe-internal subsection headings that split one recipe into component ingredient lists or step families.
  - `RECIPE_VARIANT`: alternate recipe names, variant headers, or short local alternate-version runs inside one recipe.
  - `RECIPE_NOTES`: recipe-local prose that belongs with the current recipe but is not ingredient or instruction structure.
  - `NONRECIPE_CANDIDATE`: outside-recipe material that is not recipe-local and should be sent to knowledge later.
  - `NONRECIPE_EXCLUDE`: obvious outside-recipe junk that should never reach knowledge.
  - `exclusion_reason`: use only on `NONRECIPE_EXCLUDE` rows; allowed values are `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- Negative rules:
  - If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
  - `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
  - Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
  - If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `NONRECIPE_CANDIDATE`, not `INSTRUCTION_LINE`.
  - If the shard rows are outside recipe context, default to `NONRECIPE_CANDIDATE`; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.
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
  - Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.
  - Use optional `exclusion_reason` only on rows labeled `NONRECIPE_EXCLUDE` when the text is overwhelmingly obvious junk.

{{PACKET_CONTEXT_BLOCK}}

{{REFERENCE_CONTEXT_BLOCK}}

Authoritative owned shard rows (each row is [atomic_index, current_line]):
<BEGIN_AUTHORITATIVE_ROWS>
{{AUTHORITATIVE_ROWS}}
<END_AUTHORITATIVE_ROWS>
