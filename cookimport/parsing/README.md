Parsing notes

`ingredients.py` wraps ingredient-parser-nlp and emits normalized ingredient dicts,
including quantity_kind exact/approximate/unquantified (approximate uses "to taste"/"for pan" cues).
`step_ingredients.py` assigns those ingredient lines to steps using token matching
with section-header grouping and weak-match caps.
`tips.py` extracts non-instruction guidance from headnotes/notes/standalone blocks and tags
them with recipe names, meats, vegetables, herbs, spices, dairy, grains, legumes, fruits,
sweeteners, oils/fats, techniques, and tools using a small taxonomy. It also classifies
tips as `general` or `recipe_specific`, skips recipe-specific notes (like “Why this recipe works”)
from the general tip export, and appends recipe-specific notes into DraftV1 `recipe.notes`.
