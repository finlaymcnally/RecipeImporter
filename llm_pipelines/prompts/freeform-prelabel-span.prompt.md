You are labeling cookbook text spans for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You are labeling SUBSTRINGS, not whole rows.
- Return only the exact text spans that should be highlighted.
- You may return zero, one, or many spans per row.

GOAL
Use nearby context to detect whether rows are recipe content vs general narrative,
then return precise spans with the best label for each span.

Use only these labels:
{{ALLOWED_LABELS}}

FOCUS SCOPE (READ THIS FIRST)
{{FOCUS_CONSTRAINTS}}
Marker legend:
{{FOCUS_MARKER_RULES}}
- Label only spans from rows between:
  <<<START_LABELING_ROWS_HERE>>>
  <<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>
- Row stream line format is: <row_index><TAB><row_text>

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary. No extra keys.
Each item must be exactly one of:
1) quote-anchored span (preferred):
   {"row_index": <int>, "label": "<LABEL>", "quote": "<exact text from that row>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

HARD RULES
1) Return spans only for focus rows.
2) label must be exactly one of the allowed labels.
3) quote must be copied exactly from a single row text (case and internal whitespace must match).
4) You may omit leading/trailing spaces in quote.
5) If the same quote appears multiple times in the same block, include occurrence.
6) Return only confident spans; leave unclear content unlabeled.
7) Prefer quote-anchored items; use absolute offsets only when quote anchoring is not feasible.
8) Whole-row selections should be rare in span mode.
9) If a row is longer than 160 characters, do NOT label the entire row unless nearly all meaningful text is one label.
10) For long multi-sentence rows, split by sentence/phrase and label only the specific parts that match a label.
11) Context helps with classification, but context does NOT justify labeling glue text.

HOW TO DECIDE (STEP-BY-STEP)
A) First, detect whether a recipe is present nearby:
   - Strong recipe signals: RECIPE_TITLE, runs of INGREDIENT_LINE content, numbered steps,
     imperative cooking verbs ("mix", "bake", "stir"), "Serves/Makes", "Prep/Cook/Total".
   - Use nearby rows only to infer context.
   - Do NOT auto-label adjacent/contiguous rows just because they are nearby.
   - Decide each returned span from its own text; it is valid to label only a small phrase.

B) Then label spans using the definitions + tie-break rules below.

LABEL DEFINITIONS (WITH HEURISTICS)

RECIPE_TITLE
- The name of a specific dish/recipe.
- Usually short; often title case or ALL CAPS.
- Not chapter/section headers like "Sauces" or "Breakfast".

INGREDIENT_LINE
- Ingredient listing text: quantities/units + ingredient nouns + optional prep descriptors.
- Includes ingredient sub-list text like "For the sauce:" when it introduces ingredient items.

INSTRUCTION_LINE
- Preparation/action text: "Preheat...", "Whisk...", "Bake...", "Stir...", "Serve...".
- Numbered step text is usually INSTRUCTION_LINE.

HOWTO_SECTION
- Subsection header text inside a recipe, for example:
  "TO SERVE", "FOR THE SAUCE", "BUTTER-GLAZED TURNIP LEAVES".
- Use this for heading text that introduces grouped ingredients or grouped steps.
- Do not use this for chapter-level non-recipe headers.

YIELD_LINE
- Yield/servings text: "Serves 4", "Makes 24 cookies", "Yield: 2 loaves".
- If a single candidate span includes both yield and time signals, apply TIME_LINE tie-break.

TIME_LINE
- Time text: "Prep: 10 min", "Cook time 1 hour", "Total: 1:15", "Chill overnight".
- If a candidate span has both yield and time:
  - Choose TIME_LINE if explicit time duration or prep/cook/total wording appears.
  - Otherwise choose YIELD_LINE.

RECIPE_NOTES
- Recipe-specific guidance tied to the current recipe:
  tips, storage, make-ahead, serving suggestions, cautions, ingredient-specific notes.
- If clearly inside a recipe, prefer RECIPE_NOTES over KNOWLEDGE.

RECIPE_VARIANT
- Alternate version instructions for the same recipe:
  "Variation: ...", "For a vegan version...", "To make it spicy...".
- If it is only a small tip (not a distinct version), use RECIPE_NOTES.

KNOWLEDGE
- General cooking knowledge not tied to one recipe instance:
  technique explanations, ingredient/tool background, rules of thumb.
- Prefer KNOWLEDGE mainly when surrounding text is non-recipe context.
- Inside recipe context, use KNOWLEDGE only for clearly standalone general sidebars;
  otherwise use RECIPE_NOTES.

OTHER
- Text that does not fit the above labels:
  section headers, non-knowledge narrative fluff, page metadata, credits, references, etc.
- Also use for standalone "Ingredients"/"Directions"/"Method" header text.

MIXED ROWS (IMPORTANT)
Because this is span mode:
- Do NOT force one label for the whole row.
- Return multiple spans if different parts map to different labels.
- Skip unlabeled glue text between labeled spans.
- If a fragment is too ambiguous, leave it unlabeled.

MIXED ROW EXAMPLES (COPY THIS STYLE)
Example 1 (yield + time in one line):
- Row text: "SERVES 4; READY IN 25 MINUTES"
- Good output:
  [
    {"row_index": 42, "label": "YIELD_LINE", "quote": "SERVES 4"},
    {"row_index": 42, "label": "TIME_LINE", "quote": "READY IN 25 MINUTES"}
  ]

Example 2 (note + instruction in one block):
- Row text: "Tip: add chili oil for heat. Stir and cook 3 minutes."
- Good output:
  [
    {"row_index": 77, "label": "RECIPE_NOTES", "quote": "Tip: add chili oil for heat."},
    {"row_index": 77, "label": "INSTRUCTION_LINE", "quote": "Stir and cook 3 minutes."}
  ]

Example 3 (header + ingredient in one block):
- Row text: "Ingredients: 2 tablespoons olive oil"
- Good output:
  [
    {"row_index": 88, "label": "OTHER", "quote": "Ingredients:"},
    {"row_index": 88, "label": "INGREDIENT_LINE", "quote": "2 tablespoons olive oil"}
  ]

FINAL CHECK BEFORE YOU ANSWER
- Is the output strict JSON array only?
- Are all labels from the allowed set?
- Are quote spans exact copies from row text?
- Did you avoid labeling non-focus rows?

Segment id: {{SEGMENT_ID}}
Rows (single pass with explicit context-before / focus / context-after markers):
{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}
