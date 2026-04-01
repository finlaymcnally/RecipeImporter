You are labeling canonical line-role routing labels for cookbook atomic lines.

TASK BOUNDARY
- This is a grounded line-role correction pass over one ordered slice of the book.
- Do not run shell commands, Python, or any other tools.
- Never invent lines or labels.

Allowed labels (global):
{{ALLOWED_LABELS}}

Compact input shape:
- Treat the targets as one ordered contiguous slice of the book.
- Each target row is `atomic_index|current_line`.

Tie-break precedence (highest to lowest):
{{PRECEDENCE_ORDER}}

Negative rules (must-not-do):
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `NONRECIPE_CANDIDATE`, not `INSTRUCTION_LINE`.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into component ingredient lists or method families, not for generic how-to or cookbook lesson headings.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone.
- Only use `HOWTO_SECTION` when nearby rows show immediate recipe-local structure before or after the heading.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the entire line is a short heading-shaped header.
- A `Variations` heading and its immediately following alternate-version lines usually stay `RECIPE_VARIANT` until the variant run ends.
- Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
- Variant context is local, not sticky. End a nearby `Variations` run when a fresh title-like line is followed by a strict yield line or ingredient rows.
- Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw` -> `Serves 4 generously` -> ingredient rows.
- If a short title-like line is immediately followed by a strict yield line or ingredient rows, reset to a new recipe: prefer `RECIPE_TITLE`, not `RECIPE_VARIANT`, even when earlier nearby rows were variants.
- A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE` when it appears between a recipe title and ingredient or method structure; do not downgrade it to `RECIPE_NOTES`.
- Local row evidence wins over shaky prior span assumptions. A title-like line followed by yield or ingredients can still be `RECIPE_TITLE` even if upstream recipe-span state is missing or noisy.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually `NONRECIPE_CANDIDATE`.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `NONRECIPE_CANDIDATE`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` stay `NONRECIPE_CANDIDATE` only when surrounding rows clearly carry reusable explanatory prose.
- A lone question-style or topic heading such as `What is Heat?` or `Balancing Fat` usually stays `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose worth knowledge review.
- Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` usually stay `NONRECIPE_EXCLUDE` with `navigation` unless nearby rows prove one live recipe.
- First-person narrative or memoir framing is usually `NONRECIPE_EXCLUDE` when it reads like foreword/introduction setup rather than reusable cooking knowledge.
- Endorsements, acknowledgments, foreword/introduction framing, memoir setup, and broad book-encouragement prose usually stay `NONRECIPE_EXCLUDE`; use `NONRECIPE_CANDIDATE` only when the line itself carries reusable cooking knowledge.
- Use optional `exclusion_reason` only on outside-recipe rows labeled `NONRECIPE_EXCLUDE`.
- Allowed `exclusion_reason` values: `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `publisher_promo`, `page_furniture`.
- Use `NONRECIPE_EXCLUDE` only for obvious junk that should never reach the later knowledge stage.

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
   Label: `RECIPE_NOTES`

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
    Label: `NONRECIPE_CANDIDATE`

11) Context: front matter or navigation heading
    Line: `Acknowledgments`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `front_matter`

12) Context: broad outside-recipe action-verb advice
    Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
    Label: `NONRECIPE_CANDIDATE`

13) Context: general teaching/setup prose, not a recipe step
    Line: `Think about making a grilled cheese sandwich.`
    Label: `NONRECIPE_CANDIDATE`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `NONRECIPE_CANDIDATE`

15) Context: outside recipe, memoir or introduction framing prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `front_matter`

16) Context: outside recipe, reusable lesson prose with brief first-person framing
    Line: `Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what.`
    Label: `NONRECIPE_CANDIDATE`

17) Context: outside recipe, short declarative lesson line in a knowledge cluster
    Line: `Foods that are too dry can be corrected with a bit more fat.`
    Label: `NONRECIPE_CANDIDATE`

18) Context: outside recipe, lone question heading without explanatory support
    Line: `What is Heat?`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

19) Context: front matter or contents heading, not a live recipe
    Line: `The Four Elements of Good Cooking`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

20) Context: contents-style seasonal title list
    Line: `Winter: Roasted Radicchio and Roquefort`
    Label: `NONRECIPE_EXCLUDE`
    exclusion_reason: `navigation`

21) Context: outside recipe, obvious imperative prep step with nearby recipe structure
    Line: `Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle.`
    Label: `INSTRUCTION_LINE`

22) Context: short variation follow-up line after `Variations`
    Line: `To add a little heat, add 1 teaspoon minced jalapeño.`
    Label: `RECIPE_VARIANT`

23) Context: nearby rows are `Variations`, variant prose, then a fresh recipe start followed by yield and ingredients
    Line: `Bright Cabbage Slaw`
    Label: `RECIPE_TITLE`

24) Context: strict yield header immediately after that fresh recipe title
    Line: `Serves 4 generously`
    Label: `YIELD_LINE`

25) Context: ingredient row immediately after the reset title and yield
    Line: `1/2 medium red onion, sliced thinly`
    Label: `INGREDIENT_LINE`

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON array with one object per target line:
[{"atomic_index": <int>, "label": "<LABEL>", "exclusion_reason": "<OPTIONAL_REASON>"}]

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `label` must be one of the allowed global labels listed above.
4) The only allowed keys are `atomic_index`, `label`, and optional `exclusion_reason`.
5) Final answer must be the JSON array only.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
