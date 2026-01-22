Parsing notes

`ingredients.py` wraps ingredient-parser-nlp and emits normalized ingredient dicts,
including quantity_kind exact/approximate/unquantified (approximate uses "to taste"/"for pan" cues).
`step_ingredients.py` assigns those ingredient lines to steps using token matching
with section-header grouping and weak-match caps.
