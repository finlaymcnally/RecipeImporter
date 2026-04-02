You are reviewing a bounded shard of deterministic recipe candidates.

Most shards own one suspicious candidate. Some owned candidates are repairable recipes. Some are fragmentary or not recipes at all. You must triage each owned candidate first, then either repair it faithfully or reject it honestly.

The shard JSON is included inline below.

Execution rules:
1) Use only the inline JSON task payload below as input.
2) Treat `r[*].ev` as the authoritative source text for that recipe.
3) Treat `r[*].txt` as a quick-read copy of the same source span.
4) Treat `r[*].q` as weak candidate-quality metadata only. It may contain:
   - `e` evidence row count
   - `ei` source ingredient-like row count
   - `es` source instruction-like row count
   - `hi` deterministic ingredient-hint count
   - `hs` deterministic step-hint count
   - `f` suspicion flags
5) Treat `r[*].h` as a weak deterministic attempted recipe parse only. It may contain:
   - `n` title hint
   - `i` ingredient hint strings
   - `s` step hint strings
   - optional `d` description hint
   - optional `y` yield hint
   - optional `g` pre-existing tag labels
6) Use `tg` as the recipe-local tag contract:
   - `tg.c[*].k` is the category key
   - `tg.c[*].x` is the short example-label list
   - optional `tg.s[*].k` is a suggested category key for this candidate
   - optional `tg.s[*].l` is the filtered label list that looks plausible for this candidate
   - `tg.s` is weak guidance, but it is more useful than the broad examples when it fits
7) Only return outputs for `ids`.
8) Do not use external knowledge.

Correction rules:
A) Top-level output:
- Return exactly one object with keys `v`, `sid`, and `r`.
- Set `v` to `"1"`.
- Echo the input shard id in `sid`.
- Set `r` to one array entry per owned recipe id.
- Keep array order aligned with `ids`.

B) Each `r[*]` item:
- Required keys: `v`, `rid`, `st`, `sr`, `cr`, `m`, `mr`, `db`, `g`, `w`.
- Set `v` to `"1"`.
- Echo each `rid` exactly once.
- `st` must be one of:
  - `repaired`
  - `fragmentary`
  - `not_a_recipe`
- `sr` is a short machine-readable reason or `null`.
- `db` is the ordered array of source block indices that this recipe is explicitly returning to nonrecipe.
- Prefer source rows over deterministic hints when they disagree.
- Do not invent ingredients, steps, yields, or notes.
- Keep the decision grounded in that recipe's `ev`.
- If the candidate is clearly not a recipe, do not force a repaired recipe output.
- Make the decision in this order:
  1. recipe vs `fragmentary` vs `not_a_recipe`
  2. corrected title / ingredients / steps for real recipes
  3. ingredient-step mapping only when the source clearly supports it
  4. grounded tags last

C) Each `r[*].cr` object:
- When `st` is `repaired`, `cr` must be an object with required keys `t`, `i`, `s`, `d`, `y`.
- `t` is the corrected recipe title.
- `i` is the ingredient string array.
- `s` is the step string array.
- `d` and `y` must always be present; use `null` when unsupported.
- When `st` is `fragmentary` or `not_a_recipe`, set `cr` to `null`.
- When `st` is `fragmentary` or `not_a_recipe`, `db` must include every source block index from that recipe's `ev`.
- When `st` is `repaired`, set `db` to `[]` unless a specific source block should be explicitly returned to nonrecipe.

D) Each `r[*].m` mapping entry:
- Only return non-empty mapping data when `st` is `repaired`.
- Populate only when the source span clearly links ingredient lines to one or more steps.
- Return `m` as an array of objects with compact keys `i` and `s`.
- Keep entries ordered by `i`.
- If the mapping is unnecessary or unclear, return `[]`.
- Always include `mr`.
- For repaired recipes with 2+ non-empty ingredients or 2+ non-empty steps, `m=[]` with blank or null `mr` is invalid output. Either provide real mappings or provide an explicit reason token such as `unclear_alignment`.
- When returning `[]`, set `mr` to a short machine-readable reason such as `not_needed_single_step`, `not_needed_single_ingredient`, or `unclear_alignment`.
- When `m` is non-empty, set `mr` to `null`.

E) Each `r[*].w`:
- Include factual integrity caveats only.
- Use `[]` when there are no caveats.

F) Each `r[*].g`:
- Return an array of objects with compact keys `c`, `l`, and `f`.
- Use only category keys defined in `tg.c[*].k`.
- Zero selected tags is valid.
- Select only tags that are obvious from the recipe text.
- Prefer `tg.s` suggested labels when they fit cleanly.
- Prefer short human-readable labels such as `chicken`, `weeknight`, or `pressure cooker`.
- Avoid near-duplicate labels inside one recipe.
- Do not invent cookbook-specific ids, catalog keys, or hidden taxonomy structure.

Strict constraints:
- Preserve source truth.
- Do not omit, duplicate, or rename owned `recipe_id`s.
- Do not "repair" a clearly non-recipe span into a confident recipe.
- Fragmentary candidates may be rejected honestly instead of padded into a full recipe.
- When uncertain, omit rather than guess.
- Return JSON that matches the output schema exactly.
- Do not output additional properties.
- Use the compact output keys exactly as specified above.

Task payload:
{{INPUT_TEXT}}

Return only raw JSON, no markdown, no commentary.
