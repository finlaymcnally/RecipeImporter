You are correcting one deterministic intermediate recipe object from one authoritative recipe span.

Input payload JSON (inline, authoritative):
BEGIN_INPUT_JSON
{{INPUT_TEXT}}
END_INPUT_JSON

Execution rules:
1) Use only the JSON payload above as input.
2) Treat `evidence_rows` as the authoritative source text.
3) Treat `recipe_candidate_hint` as the intermediate recipe object to correct.
4) If `draft_hint` is present, treat it as a downstream deterministic preview only.
5) Use `tagging_guide` only as a compact taxonomy guide for categories and example labels.
6) Do not use external knowledge.

Correction rules:
A) `canonical_recipe`:
- Return one corrected canonical recipe object as a nested JSON object, not a quoted JSON string.
- Required shape: `title`, `ingredients`, `steps`.
- Optional fields: `description`, `recipeYield`.
- Always emit `description` and `recipeYield`; use `null` when unsupported by the source span.
- Keep the recipe grounded in `evidence_rows`.
- Prefer the source rows over the deterministic hints when they disagree.
- Do not invent ingredients, steps, yields, or notes.

B) `ingredient_step_mapping`:
- Populate only when the source span clearly links ingredient lines to one or more steps.
- Return `ingredient_step_mapping` as an array of objects with `ingredient_index` and `step_indexes`, not a quoted JSON string.
- Keep entries ordered by `ingredient_index`.
- If the mapping is unnecessary or unclear, return `[]`.
- Always include `ingredient_step_mapping_reason`.
- When returning `[]`, set `ingredient_step_mapping_reason` to a short machine-readable reason such as `not_needed_single_step`, `not_needed_single_ingredient`, or `unclear_alignment`.
- When `ingredient_step_mapping` is non-empty, set `ingredient_step_mapping_reason` to `null`.

C) `warnings`:
- Include factual integrity caveats only.
- Use `[]` when there are no caveats.

D) `selected_tags`:
- Return an array of objects with `category`, `label`, and `confidence`.
- Use only category keys defined in `tagging_guide.categories`.
- Zero selected tags is valid.
- Select only tags that are obvious from the recipe text.
- Prefer short human-readable labels such as `chicken`, `weeknight`, or `pressure cooker`.
- Avoid near-duplicate labels inside one recipe.
- Do not invent cookbook-specific ids, catalog keys, or hidden taxonomy structure.

Strict constraints:
- Preserve source truth.
- When uncertain, omit rather than guess.
- Return JSON that matches the output schema exactly.
- Do not output additional properties.
- Set `bundle_version` to "1".
- Echo the input `recipe_id` exactly.

Return only raw JSON, no markdown, no commentary.
