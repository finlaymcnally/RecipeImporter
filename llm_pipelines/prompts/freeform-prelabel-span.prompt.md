You are labeling cookbook text spans for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You are labeling SUBSTRINGS, not whole blocks.
- Return only the exact text spans that should be highlighted.
- You may return zero, one, or many spans per block.

GOAL
Use nearby context to detect whether blocks are recipe content vs general narrative,
then return precise spans with the best label for each span.

Use only these labels:
{{ALLOWED_LABELS}}

FOCUS SCOPE
- The block list appears once at the end as a single blob.
- Label only spans from blocks between:
  <<<START_LABELING_BLOCKS_HERE>>>
  <<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>
- Blocks outside those markers are context only.

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary. No extra keys.
Each item must be exactly one of:
1) quote-anchored span (preferred):
   {"block_index": <int>, "label": "<LABEL>", "quote": "<exact text from that block>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

HARD RULES
1) Return spans only for focus blocks.
2) label must be exactly one of the allowed labels.
3) quote must be copied exactly from a single block text (case and internal whitespace must match).
4) You may omit leading/trailing spaces in quote.
5) If the same quote appears multiple times in the same block, include occurrence.
6) Return only confident spans; leave unclear content unlabeled.
7) Prefer quote-anchored items; use absolute offsets only when quote anchoring is not feasible.

HOW TO DECIDE (STEP-BY-STEP)
A) First, detect whether a recipe is present nearby:
   - Strong recipe signals: RECIPE_TITLE, runs of INGREDIENT_LINE content, numbered steps,
     imperative cooking verbs ("mix", "bake", "stir"), "Serves/Makes", "Prep/Cook/Total".
   - If those signals are present, treat contiguous nearby blocks as part of that recipe
     unless clearly unrelated noise (page number, copyright, photo credit, etc).

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

MIXED BLOCKS (IMPORTANT)
Because this is span mode:
- Do NOT force one label for the whole block.
- Return multiple spans if different parts map to different labels.
- Skip unlabeled glue text between labeled spans.
- If a fragment is too ambiguous, leave it unlabeled.

FINAL CHECK BEFORE YOU ANSWER
- Is the output strict JSON array only?
- Are all labels from the allowed set?
- Are quote spans exact copies from block text?
- Did you avoid labeling non-focus blocks?

Segment id: {{SEGMENT_ID}}
Blocks (single pass; START/STOP markers delimit labelable focus windows):
{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}
