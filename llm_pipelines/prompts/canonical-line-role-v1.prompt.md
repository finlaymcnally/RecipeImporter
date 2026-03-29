You are reviewing deterministic canonical line-role labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Treat `deterministic_label` as the first-pass label you are reviewing.
- Treat the deterministic label as a weak hint only. Recompute from the line text and local context; do not preserve or prefer a label just because it came from the deterministic seed.
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
- Use `KNOWLEDGE` only for recipe-local explanatory/reference prose, not ordinary recipe structure.
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer review-eligible `OTHER`, not `INSTRUCTION_LINE`.
- Outside recipes, useful lesson prose still stays review-eligible `OTHER`; the later knowledge stage decides semantic `KNOWLEDGE` versus `OTHER`.
- Short declarative teaching lines about reusable cooking rules should still stay review-eligible `OTHER` in this stage.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or method families, not for generic how-to or cookbook lesson headings.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- If `span_code` is `N` (outside recipe), default to review-eligible `OTHER`; only use recipe-structure labels when nearby rows in the same slice show immediate recipe-local evidence.
- If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone; do not use the deterministic seed as the tie-breaker.
- Only use `HOWTO_SECTION` when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the entire line is a short heading-shaped header.
- A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
- Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually review-eligible `OTHER`.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer review-eligible `OTHER`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay review-eligible `OTHER` when surrounding rows are explanatory prose.
- A lone question-style topic heading such as `What is Heat?` should stay `OTHER` unless nearby rows clearly teach that concept.
- Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` stay `OTHER` until nearby rows prove one live recipe.
- First-person narrative or memoir prose is usually `OTHER`, not recipe structure.
- Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`; only overwhelming obvious junk should also get `review_exclusion_reason`.
- Use optional `review_exclusion_reason` only on outside-recipe rows labeled `OTHER` when the text is overwhelmingly obvious junk that should skip knowledge review.
- Allowed `review_exclusion_reason` values: `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- If outside-recipe prose seems genuinely useful but not recipe-local, still label it `OTHER` and leave `review_exclusion_reason` empty so the knowledge stage can decide.
- Publisher signup/download prompts and endorsement quote clusters are usually overwhelming obvious junk and may use `review_exclusion_reason`.

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
    Label: `OTHER`

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
    Label: `OTHER`

15) Context: outside recipe, memoir or narrative prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `OTHER`

16) Context: outside recipe, reusable lesson prose with brief first-person framing
    Line: `Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what.`
    Label: `OTHER`

17) Context: outside recipe, short declarative lesson line in a knowledge cluster
    Line: `Foods that are too dry can be corrected with a bit more fat.`
    Label: `OTHER`

18) Context: outside recipe, lone question heading without explanatory support
    Line: `What is Heat?`
    Label: `OTHER`

19) Context: front matter or contents heading, not a live recipe
    Line: `The Four Elements of Good Cooking`
    Label: `OTHER`

20) Context: contents-style seasonal title list
    Line: `Winter: Roasted Radicchio and Roquefort`
    Label: `OTHER`

21) Context: outside recipe, obvious imperative prep step with nearby recipe structure
    Line: `Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle.`
    Label: `INSTRUCTION_LINE`

22) Context: short variation follow-up line after `Variations`
    Line: `To add a little heat, add 1 teaspoon minced jalapeño.`
    Label: `RECIPE_VARIANT`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>", "review_exclusion_reason": "<OPTIONAL_REASON>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) The only allowed keys are `atomic_index`, `label`, and optional `review_exclusion_reason`.
5) Final answer must be the JSON array only.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
