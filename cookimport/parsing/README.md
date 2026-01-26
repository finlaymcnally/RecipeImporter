# Parsing notes

- `signals.classify_block` accepts optional `ParsingOverrides` (from `.overrides.yaml`) to extend headers/verbs/units and toggle spaCy signals.
- Tip extraction honors `tipHeaders` and `tipPrefixes` overrides.
- Enable spaCy features with `COOKIMPORT_SPACY=1` or `enableSpacy` in overrides (if spaCy + model are installed).
