# Parsing notes

- `signals.classify_block` accepts optional `ParsingOverrides` (from `.overrides.yaml`) to extend headers/verbs/units and toggle spaCy signals.
- Tip extraction honors `tipHeaders` and `tipPrefixes` overrides.
- Tip extraction now requires an explicit advice anchor (strong tip header/prefix, imperative start, diagnostic/benefit cue) and a cooking anchor (dish/ingredient/technique/tool/cooking-method keywords) for standalone tips; first-person narrative is filtered unless paired with advice language. Standalone blocks are grouped into topic containers and split into atomic paragraphs/list items for extraction, with adjacent-atom context preserved in provenance.
- Enable spaCy features with `COOKIMPORT_SPACY=1` or `enableSpacy` in overrides (if spaCy + model are installed).
- Ingredient parsing normalizes whitespace and repairs split fractions (e.g., `3 / 4` or line-broken `3\n/4`) before parsing.
- Instruction fallback segmentation now lives in `step_segmentation.py` (`instruction_step_segmentation_policy=off|auto|always`, `instruction_step_segmenter=heuristic_v1|pysbd_v1`) and is deterministic by default (`heuristic_v1`).
- Instruction metadata parsing now supports Priority 6 deterministic options via `InstructionParseOptions` (time backend/strategy, temperature backend/unit backend, oven-like classifier mode); parser output includes `temperature_items` plus legacy compatibility fields.
- `yield_extraction.py` centralizes deterministic yield selection/parsing with `p6_yield_mode=legacy_v1|scored_v1` and returns normalized draft fields (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`).
- Shared section detection now lives in `section_detector.py`; `sections.py` keeps the legacy public API but delegates detection internals to that shared backend. `section_detector_backend` defaults to `legacy` and can be switched to `shared_v1` in stage/benchmark run settings.
- Shared multi-recipe candidate splitting now lives in `multi_recipe_splitter.py`; Text/EPUB/PDF can use `multi_recipe_splitter=rules_v1` (or keep `legacy`/`off`) with optional `multi_recipe_split_trace` diagnostics.
- EPUB `markitdown` extractor path uses `markitdown_adapter.py` (`EPUB -> markdown`) plus `markdown_blocks.py` (deterministic markdown line parsing into `Block`s with `md_line_start/md_line_end` provenance).
- EPUB `unstructured` path now supports explicit HTML parser/preprocess options and BR-splitting pre-normalization via `epub_html_normalize.py`; inspect `raw_spine_xhtml_*.xhtml` and `norm_spine_xhtml_*.xhtml` raw artifacts when debugging.
- EPUB HTML extractors (`beautifulsoup` and `unstructured`) now run shared `epub_postprocess.py` cleanup after extraction (soft-hyphen/unicode cleanup, bullet stripping, BR/table line splitting, and pagebreak/nav noise suppression).
- EPUB extraction health metrics are computed in `epub_health.py` and written to raw artifact `epub_extraction_health.json`; warning keys are added to `ConversionReport.warnings` when suspicious patterns are detected.
- Deterministic cookbook noise controls now live in `pattern_flags.py` and are shared by EPUB/PDF for TOC-like exclusion, duplicate-title intro trims, overlap-duplicate rejection, and `pattern_diagnostics.json` warning/artifact emission.
