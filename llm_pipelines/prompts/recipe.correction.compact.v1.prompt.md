You are correcting a bounded shard of deterministic intermediate recipe objects from authoritative recipe spans.

Input payload JSON (inline, authoritative):
BEGIN_INPUT_JSON
{{INPUT_TEXT}}
END_INPUT_JSON

Execution rules:
1) Use only the JSON payload above as input.
2) Treat `recipes[*].evidence_rows` as the authoritative source text for that `recipe_id`.
3) Treat `recipes[*].recipe_candidate_hint` as the deterministic intermediate recipe object to correct.
4) Use `tagging_guide` only as a compact taxonomy guide for categories and example labels.
5) Only return outputs for `owned_recipe_ids`.
6) Do not use external knowledge.

Correction rules:
A) `recipes`:
- Return one array entry per owned `recipe_id`.
- Keep array order aligned with `owned_recipe_ids`.
- Echo each `recipe_id` exactly once.

B) Each `recipes[*].canonical_recipe`:
- Return one corrected canonical recipe object as a nested JSON object, not a quoted JSON string.
- Required shape: `title`, `ingredients`, `steps`.
- Optional fields: `description`, `recipeYield`.
- Always emit `description` and `recipeYield`; use `null` when unsupported by the source span.
- Keep the recipe grounded in that recipe's `evidence_rows`.
- Prefer source rows over deterministic hints when they disagree.
- Do not invent ingredients, steps, yields, or notes.

C) Each `recipes[*].ingredient_step_mapping`:
- Populate only when the source span clearly links ingredient lines to one or more steps.
- Return `ingredient_step_mapping` as an array of objects with `ingredient_index` and `step_indexes`, not a quoted JSON string.
- Keep entries ordered by `ingredient_index`.
- If the mapping is unnecessary or unclear, return `[]`.
- Always include `ingredient_step_mapping_reason`.
- When returning `[]`, set `ingredient_step_mapping_reason` to a short machine-readable reason such as `not_needed_single_step`, `not_needed_single_ingredient`, or `unclear_alignment`.
- When `ingredient_step_mapping` is non-empty, set `ingredient_step_mapping_reason` to `null`.

D) Each `recipes[*].warnings`:
- Include factual integrity caveats only.
- Use `[]` when there are no caveats.

E) Each `recipes[*].selected_tags`:
- Return an array of objects with `category`, `label`, and `confidence`.
- Use only category keys defined in `tagging_guide.categories`.
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
- Set `bundle_version` to "1".
- Echo the input `shard_id` exactly.

Return only raw JSON, no markdown, no commentary.
