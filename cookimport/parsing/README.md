Parsing notes

`ingredients.py` wraps ingredient-parser-nlp and emits normalized ingredient dicts,
including quantity_kind exact/approximate/unquantified (approximate uses "to taste"/"for pan" cues).
`step_ingredients.py` assigns those ingredient lines to steps using token matching
with section-header grouping and weak-match caps.
`tips.py` extracts non-instruction guidance from headnotes/notes/standalone blocks and tags
them with recipe names, meats, vegetables, herbs, spices, dairy, grains, legumes, fruits,
sweeteners, oils/fats, techniques, and tools using a small taxonomy. Extraction is block-first
(paragraph/callout), then span repair pulls adjacent context to avoid fragments before scoring.
Tips are classified as `general`, `recipe_specific`, or `not_tip` and carry a `standalone` flag.
Recipe-specific notes (for example "Why this recipe works") stay out of the general tip export
and are appended into DraftV1 `recipe.notes`. Recipe-sourced tips default to `recipe_specific`
unless they read as strongly general; general tips are primarily sourced from non-recipe blocks,
and short standalone fragments are filtered unless diagnostic cues are present.
