# Parsing notes

- `signals.classify_block` accepts optional `ParsingOverrides` (from `.overrides.yaml`) to extend headers/verbs/units and toggle spaCy signals.
- Tip extraction honors `tipHeaders` and `tipPrefixes` overrides.
- Tip extraction now requires an explicit advice anchor (strong tip header/prefix, imperative start, diagnostic/benefit cue) and a cooking anchor (dish/ingredient/technique/tool/cooking-method keywords) for standalone tips; first-person narrative is filtered unless paired with advice language. Standalone blocks are grouped into topic containers and split into atomic paragraphs/list items for extraction, with adjacent-atom context preserved in provenance.
- Enable spaCy features with `COOKIMPORT_SPACY=1` or `enableSpacy` in overrides (if spaCy + model are installed).
