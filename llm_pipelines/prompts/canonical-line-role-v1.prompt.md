You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat the deterministic label as a strong prior, not a neutral starting guess.
- Treat `span_code` as a weak provenance hint only. It may be unknown and it is not authoritative recipe-boundary truth.
- Do not run shell commands, Python, or any other tools.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: R=in_recipe, N=outside_recipe, U=unknown_recipe_status
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- Never label a quantity/unit ingredient line as `KNOWLEDGE`.
- Never label an imperative instruction sentence as `KNOWLEDGE`.
- Use `KNOWLEDGE` only for explicit explanatory/reference prose, not ordinary recipe structure.
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `KNOWLEDGE` or `OTHER`, not `INSTRUCTION_LINE`.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or method families, not for generic how-to or cookbook lesson headings.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- If `span_code` is `N` (outside recipe), default to `OTHER` unless the line clearly teaches reusable cooking explanation/reference prose; only use recipe-structure labels when nearby rows in the same slice show immediate recipe-local evidence.
- If a row is plausible under its current deterministic label, leave it there.
- Only use `HOWTO_SECTION` when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the entire line is a short heading-shaped header.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `KNOWLEDGE` or `OTHER`.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `KNOWLEDGE` or `OTHER`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay `KNOWLEDGE` when surrounding rows are explanatory prose.
- First-person narrative or memoir prose is usually `OTHER`, not recipe structure.
- Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`, not `KNOWLEDGE`.

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

6) Context: explanatory cookbook prose
   Line: `Copper pans conduct heat quickly and evenly, so temperature changes show up fast.`
   Label: `KNOWLEDGE`

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
    Label: `KNOWLEDGE`

11) Context: front matter or navigation heading
    Line: `Acknowledgments`
    Label: `OTHER`

12) Context: broad outside-recipe action-verb advice
   Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
   Label: `OTHER`

13) Context: general teaching/setup prose, not a recipe step
   Line: `Think about making a grilled cheese sandwich.`
   Label: `OTHER`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `KNOWLEDGE`

15) Context: outside recipe, memoir or narrative prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `OTHER`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) No markdown, no commentary, no extra keys.
5) Final answer must be the JSON array only.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
