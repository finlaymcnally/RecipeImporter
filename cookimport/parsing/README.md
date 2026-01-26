# Parsing notes

- `signals.classify_block` accepts optional `ParsingOverrides` (from `.overrides.yaml`) to extend headers/verbs/units and toggle spaCy signals.
- Tip extraction honors `tipHeaders` and `tipPrefixes` overrides.
- Tip extraction now requires an explicit advice anchor (strong tip header/prefix, imperative start, diagnostic/benefit cue); first-person narrative is filtered unless paired with advice language.
- Enable spaCy features with `COOKIMPORT_SPACY=1` or `enableSpacy` in overrides (if spaCy + model are installed).
