Parsing notes

`ingredients.py` wraps ingredient-parser-nlp and emits normalized ingredient dicts.
`step_ingredients.py` assigns those ingredient lines to steps using token matching
with section-header grouping and weak-match caps.
