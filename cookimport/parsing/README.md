# Parsing notes

- `signals.classify_block` accepts optional `ParsingOverrides` (from `.overrides.yaml`) to extend headers/verbs/units and toggle spaCy signals.
- Tip extraction honors `tipHeaders` and `tipPrefixes` overrides.
- Tip extraction now requires an explicit advice anchor (strong tip header/prefix, imperative start, diagnostic/benefit cue) and a cooking anchor (dish/ingredient/technique/tool/cooking-method keywords) for standalone tips; first-person narrative is filtered unless paired with advice language. Standalone blocks are grouped into topic containers and split into atomic paragraphs/list items for extraction, with adjacent-atom context preserved in provenance.
- Enable spaCy features with `COOKIMPORT_SPACY=1` or `enableSpacy` in overrides (if spaCy + model are installed).
- Ingredient parsing normalizes whitespace and repairs split fractions (e.g., `3 / 4` or line-broken `3\n/4`) before parsing.
- EPUB `markitdown` extractor path uses `markitdown_adapter.py` (`EPUB -> markdown`) plus `markdown_blocks.py` (deterministic markdown line parsing into `Block`s with `md_line_start/md_line_end` provenance).
- EPUB `unstructured` path now supports explicit HTML parser/preprocess options and BR-splitting pre-normalization via `epub_html_normalize.py`; inspect `raw_spine_xhtml_*.xhtml` and `norm_spine_xhtml_*.xhtml` raw artifacts when debugging.
