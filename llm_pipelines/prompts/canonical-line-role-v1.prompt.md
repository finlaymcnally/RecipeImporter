You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded recipe-structure correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat `region_code` as the recipe-region gate result for that row.
- Rows gated `O=outside_recipe` must stay within non-recipe labels only.
- Rows gated `B=boundary_uncertain` may use recipe labels only when local context clearly shows the line belongs inside a real recipe region.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Region codes: {{REGION_CODE_LEGEND}}
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Use `KNOWLEDGE` only for explicit explanatory/reference prose, not ordinary recipe structure.
- If a row is gated `outside_recipe`, do not emit `RECIPE_TITLE`, `RECIPE_VARIANT`, `HOWTO_SECTION`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, or `TIME_LINE`.

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) No markdown, no commentary, no extra keys.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
