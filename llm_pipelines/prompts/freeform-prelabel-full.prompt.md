You are labeling cookbook text ROWS for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You must assign exactly ONE label to EACH row.
- Downstream will highlight the ENTIRE row for the label you choose.
  So do NOT try to label substrings. Choose the best single label for the whole block.

GOAL
For each row, choose the label that best describes what the row IS, using local context
(neighboring rows) to determine whether we are inside a recipe or in general/narrative text.

FOCUS SCOPE
{{FOCUS_CONSTRAINTS}}
Focus rows to label (context rows may be broader):
{{FOCUS_BLOCK_JSON_LINES}}

RETURN FORMAT (STRICT)
Return STRICT JSON ONLY. No markdown, no commentary, no extra keys.
Output format exactly:
[{"row_index": <int>, "label": "<LABEL>"}]

HARD RULES
1) Return labels only for focus rows.
2) Keep the SAME ORDER as the focus rows listed above.
3) Include each focus row_index exactly once.
4) label must be exactly one of:
   {{ALLOWED_LABELS}}
{{UNCERTAINTY_HINT}}

HOW TO DECIDE (STEP-BY-STEP)
A) First, detect whether a recipe is present nearby:
  - Strong recipe signals: RECIPE_TITLE, a run of INGREDIENT_LINE rows, numbered steps,
     imperative cooking verbs ("mix", "bake", "stir"), "Serves/Makes", "Prep/Cook/Total".
   - If those signals are present, treat contiguous nearby blocks as part of that recipe
     unless they are clearly unrelated noise (page number, copyright, photo credit, etc).

B) Then label each block using the definitions + tie-break rules below.

LABEL DEFINITIONS (WITH HEURISTICS)

RECIPE_TITLE
- The NAME of a specific dish/recipe (usually short).
- Often Title Case or ALL CAPS; may include descriptors like "Classic...", "Quick...".
- NOT this: chapter/section headers ("Sauces", "Breakfast"), running headers/footers,
  "Ingredients", "Directions", "Method", "Notes" by themselves.

INGREDIENT_LINE
- A line (or row mostly composed of lines) listing ingredients, typically with:
  - a quantity and/or unit (1, 1/2, 200 g, tbsp, cup, oz, ml),
  - an ingredient noun (flour, butter, garlic),
  - optional prep descriptors (chopped, minced, room temperature).
- Also includes ingredient sub-lists that are still ingredients (e.g., "For the sauce: ...").
- If the row is a MIX of ingredients and instructions, label OTHER (see "Mixed rows").

INSTRUCTION_LINE
- A preparation step: actions to perform, often imperative verbs and sentences:
  "Preheat...", "Whisk...", "Bake...", "Stir...", "Serve..."
- Numbered steps ("1.", "Step 2") are instructions.
- Also includes short imperative fragments ("Let rest 10 minutes.").

HOWTO_SECTION
- A recipe subsection header inside a recipe, for example:
  "TO SERVE", "FOR THE SAUCE", "BUTTER-GLAZED TURNIP LEAVES".
- Use this when the highlighted text is a section heading rather than an ingredient or action sentence.
- Do not use this for chapter-level headers outside a recipe.

YIELD_LINE
- Statements about servings or yield / amount produced:
  "Serves 4", "Makes 24 cookies", "Yield: 2 loaves", "Feeds a crowd", "About 1 quart".
- If yield is embedded with time in the SAME row, use the tie-break rule under TIME_LINE.

TIME_LINE
- Statements about time durations, prep/cook/total/chill/rest times:
  "Prep: 10 min", "Cook time 1 hour", "Total: 1:15", "Chill overnight".
- If a single row contains BOTH time and yield:
  - Choose TIME_LINE if any explicit time durations or "prep/cook/total" appear.
  - Otherwise choose YIELD_LINE.

RECIPE_NOTES
- Extra notes specific to the CURRENT recipe (not a distinct alternate version):
- tips, storage, make-ahead, serving suggestions, substitutions that do not define a new variant,
  warnings ("do not overmix"), sourcing for an ingredient used above, etc.
- Often introduced by: "Note:", "Notes:", "Tip:", "Chef's note:", "Serving suggestion:".
- IMPORTANT: If we are clearly inside a recipe, prefer RECIPE_NOTES instead of KNOWLEDGE.

RECIPE_VARIANT
- An alternate version of the recipe that changes ingredients/method in a defined way:
  "Variation: ...", "Variations: ...", "For a vegan version...", "To make it spicy...", "Option B..."
- If it is a small tip and not a distinct version, use RECIPE_NOTES instead.

KNOWLEDGE
- General cooking knowledge NOT tied to a specific recipe instance:
  technique explanations, ingredient/tool background, how-to guidance, rules of thumb.
  Example: "Searing builds flavor by...", "How to choose ripe avocados..."
- Use KNOWLEDGE mainly when the surrounding text is NOT a recipe (chapter intro, technique section).
- If it appears inside a recipe section, only use KNOWLEDGE if it is clearly a standalone
  general sidebar; otherwise use RECIPE_NOTES.

OTHER
- Anything that does not fit the above labels, including:
- chapter titles/section headers, narrative fluff unrelated to cooking knowledge,
- page numbers, headers/footers, copyright, photo credits,
- indexes, tables of contents, references,
- "Ingredients"/"Directions"/"Method" headers by themselves,
- mixed-content blocks where no single recipe label dominates.

MIXED ROWS (IMPORTANT)
Because you can only choose ONE label per row:
- If the row is mostly ingredient lines -> INGREDIENT_LINE.
- If the row is mostly instruction steps -> INSTRUCTION_LINE.
- If it is truly mixed (e.g., ingredients + instructions interleaved, or recipe + narrative) -> OTHER.

FINAL CHECK BEFORE YOU ANSWER
- Did you label every provided row_index exactly once?
- Are labels exactly from the allowed set?
- Is the output STRICT JSON only (no trailing commas, no comments)?

Segment id: {{SEGMENT_ID}}
Rows:
{{BLOCKS_JSON_LINES}}
