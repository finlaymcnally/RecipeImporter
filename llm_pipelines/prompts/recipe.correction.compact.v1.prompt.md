You are correcting a bounded shard of deterministic intermediate recipe objects from authoritative recipe spans.

The authoritative shard JSON is included inline below.

Execution rules:
1) Use only the inline JSON task payload below as input.
2) Treat `r[*].ev` as the authoritative source text for that recipe.
3) Treat `r[*].h` as the deterministic intermediate recipe object to correct.
4) Use `tg` only as a compact taxonomy guide for categories and example labels.
5) Only return outputs for `ids`.
6) Do not use external knowledge.

Correction rules:
A) Top-level output:
- Return exactly one object with keys `v`, `sid`, and `r`.
- Set `v` to `"1"`.
- Echo the input shard id in `sid`.
- Set `r` to one array entry per owned recipe id.
- Keep array order aligned with `ids`.

B) Each `r[*]` item:
- Required keys: `v`, `rid`, `cr`, `m`, `mr`, `g`, `w`.
- Set `v` to `"1"`.
- Echo each `rid` exactly once.
- Keep the recipe grounded in that recipe's `ev`.
- Prefer source rows over deterministic hints when they disagree.
- Do not invent ingredients, steps, yields, or notes.

C) Each `r[*].cr` object:
- Required keys: `t`, `i`, `s`, `d`, `y`.
- `t` is the corrected recipe title.
- `i` is the ingredient string array.
- `s` is the step string array.
- `d` and `y` must always be present; use `null` when unsupported.

D) Each `r[*].m` mapping entry:
- Populate only when the source span clearly links ingredient lines to one or more steps.
- Return `m` as an array of objects with compact keys `i` and `s`.
- Keep entries ordered by `i`.
- If the mapping is unnecessary or unclear, return `[]`.
- Always include `mr`.
- When returning `[]`, set `mr` to a short machine-readable reason such as `not_needed_single_step`, `not_needed_single_ingredient`, or `unclear_alignment`.
- When `m` is non-empty, set `mr` to `null`.

E) Each `r[*].w`:
- Include factual integrity caveats only.
- Use `[]` when there are no caveats.

F) Each `r[*].g`:
- Return an array of objects with compact keys `c`, `l`, and `f`.
- Use only category keys defined in `tg.categories`.
- Zero selected tags is valid.
- Select only tags that are obvious from the recipe text.
- Prefer short human-readable labels such as `chicken`, `weeknight`, or `pressure cooker`.
- Avoid near-duplicate labels inside one recipe.
- Do not invent cookbook-specific ids, catalog keys, or hidden taxonomy structure.

Strict constraints:
- Preserve source truth.
- Do not omit, duplicate, or rename owned `recipe_id`s.
- When uncertain, omit rather than guess.
- Return JSON that matches the output schema exactly.
- Do not output additional properties.
- Use the compact output keys exactly as specified above.

Task payload:
{{INPUT_TEXT}}

Return only raw JSON, no markdown, no commentary.
