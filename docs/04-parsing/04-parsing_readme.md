---
summary: "Code-verified parsing reference focused on current behavior, contracts, and regression-sensitive modules."
read_when:
  - When changing ingredient parsing, instruction metadata extraction, step-ingredient linking, or EPUB recipe segmentation
  - When changing tip/topic extraction, knowledge chunking, or chunk lane mapping
  - When reconciling parsing docs against code/tests (use `04-parsing_log.md` for historical attempts)
---

# Parsing: Consolidated System Reference

This file is the source of truth for current parsing behavior.

Historical architecture versions, builds, and fix attempts now live in `docs/04-parsing/04-parsing_log.md`.

## What This Covers

- Ingredient parsing
- Instruction metadata parsing
- Ingredient-to-step linking
- EPUB recipe segmentation rules that affect parsing outcomes
- Tip candidate extraction and classification
- Topic candidate extraction
- Knowledge chunk generation, lane assignment, and highlight extraction
- Output artifacts and where they are written
- Current limitations / sharp edges

## History and Prior Attempts

- Architecture versions, build notes, and fix attempts: `docs/04-parsing/04-parsing_log.md`
- If debugging starts looping, check the log first before trying a new approach.

## Where The Parsing Code Lives

Core modules:

- `cookimport/parsing/ingredients.py`
- `cookimport/parsing/instruction_parser.py`
- `cookimport/parsing/step_ingredients.py`
- `cookimport/parsing/sections.py`
- `cookimport/parsing/tips.py`
- `cookimport/parsing/atoms.py`
- `cookimport/parsing/chunks.py`
- `cookimport/parsing/tables.py`
- `cookimport/parsing/signals.py`
- `cookimport/parsing/cleaning.py`
- `cookimport/parsing/tip_taxonomy.py`
- `cookimport/parsing/block_roles.py`
- `cookimport/parsing/markdown_blocks.py`
- `cookimport/parsing/epub_extractors.py`

Major call sites:

- Recipe draft conversion: `cookimport/staging/draft_v1.py`
- EPUB segmentation + standalone tip/topic extraction: `cookimport/plugins/epub.py`
- PDF/text/excel importers also feed tips/topics/chunks via shared parsing modules
- Output writing: `cookimport/staging/writer.py`

## End-to-End Data Flow (Current)

### Recipe path

1. Importer creates `RecipeCandidate` objects.
2. `cookimport/staging/draft_v1.py` converts each candidate:
   - ingredient lines parsed with `parse_ingredient_line`
   - steps parsed with `parse_instruction`
   - ingredient lines linked to steps with `assign_ingredient_lines_to_steps`
3. Unassigned ingredients get inserted into a prep step (`"Gather and prepare ingredients."`) at step 0.
4. Writer emits draft outputs.

### Tip/topic/chunk path

1. Importers generate `tip_candidates` and `topic_candidates`:
   - Recipe text: `extract_tip_candidates_from_candidate`
   - Standalone non-recipe blocks: atomized extraction in EPUB/PDF flows
2. `partition_tip_candidates` separates:
   - `general` + standalone tips
   - `recipe_specific`
   - `not_tip`
3. CLI/ingest path computes chunks:
   - Preferred: `chunks_from_non_recipe_blocks(non_recipe_blocks)`
   - Fallback: `chunks_from_topic_candidates(topic_candidates)`
4. Writer emits:
   - tips
   - topic candidates
   - chunks and chunk summary

## Ingredient Parsing (`cookimport/parsing/ingredients.py`)

### Main behavior

- Uses `ingredient-parser-nlp` (`parse_ingredient(..., string_units=True)`).
- Returns normalized dict with `quantity_kind` in:
  - `exact`
  - `approximate`
  - `unquantified`
  - `section_header`

### Important heuristics

- Section headers detected before and after parser call.
- Approximate phrases include `to taste`, `as needed`, `for serving`, `for frying`, and related patterns.
- Quantity ranges use midpoint then `ceil`:
  - `3-4` => `4.0`
  - `2-4` => `3.0`
- Split fractions like `3 / 4` are normalized before parse.

### Non-obvious implementation details

- If parsed amount has no unit, unit defaults to `"medium"`.
  - This is deliberate in current code/tests, but semantically imperfect.
- `warm_ingredient_parser()` exists to pre-load model quietly.
- File currently contains a duplicate `parse_ingredient_line` definition stub near top, then full implementation below. Runtime uses the later definition. It is harmless but technical debt.

### Tests to read

- `tests/test_ingredient_parser.py`

## Instruction Metadata Parsing (`cookimport/parsing/instruction_parser.py`)

### Extracted fields per step

- `time_items`: list of detected durations
- `total_time_seconds`: sum of all detected times in that step
- `temperature`, `temperature_unit`, `temperature_text`: first matched temperature expression

### Time behavior

- Handles seconds/minutes/hours/days and abbreviations (`mins`, `hrs`, `secs`).
- Ranges use midpoint (`20 to 30 minutes` => 25 minutes).
- Multiple durations in one step are summed.

### Temperature behavior

- Handles `400F`, `350°F`, `375 degrees F`, `220 degrees celsius`.
- Returns first temperature match only.

### Known limitations

- Summing all durations can overcount if text includes optional/resting overlaps.
- Only first temperature is captured even if step has multiple.

### Tests to read

- `tests/test_instruction_parser.py`

## Step-Ingredient Linking (`cookimport/parsing/step_ingredients.py`)

## Core algorithm

Two-phase assignment:

1. Candidate collection across all step x ingredient pairs
2. Global resolution per ingredient

Matching order:

1. Exact alias matches
2. Semantic fallback (rule lemmatization + synonym variants)
3. Fuzzy fallback (RapidFuzz) only for still-unmatched ingredients

### Alias generation

- Uses `raw_ingredient_text` and cleaned `raw_text` variants.
- Includes full-token aliases plus head/tail single-token aliases.
- Alias scoring prefers more tokens, longer tokens, and `raw_ingredient_text` source.

### Verb context scoring

- `use` verbs: positive score
- `reference` verbs: negative score
- `split` signals (`half`, `remaining`, `reserved`, etc.) enable multi-step behavior only when strong conditions are met

### Section extraction and context

- `cookimport/parsing/sections.py` provides deterministic section extraction for:
  - ingredient headers (for example `For the gravy:`),
  - instruction headers (conservative heuristics; header-like short lines only).
- Section keys are normalized (`For the Gravy:` -> `gravy`) so ingredient/instruction sections align.
- In `assign_ingredient_lines_to_steps(...)`, optional section context can bias ambiguous matches:
  - near-tied candidates prefer same-section steps,
  - repeated ingredient names across components resolve by section when context is available.

### Assignment rules

- Default: one best step per ingredient.
- If multiple `use` candidates exist, earliest use step wins.
- Multi-step assignment allowed only with strong split language and >=2 use/split candidates.
- Max steps per ingredient is capped at 3.

### Fraction handling

- Split phrases (`half`, `third`, `quarter`, `remaining`) can produce step fractions.
- When split applied, step ingredient copy gets confidence penalty (`-0.05`, floored at 0).

### Special passes after global assignment

- `all ingredients` phrases can assign all non-header ingredients to a step.
  - when section context is present and the recipe has multiple sections, this scopes to ingredients in that same section.
- Section-header groups can add grouped ingredients to steps mentioning group aliases.
- Collective-term fallback for unmatched ingredients:
  - categories currently: `spices`, `herbs`, `seasonings`
  - prefers same-section steps when section context exists, then falls back globally

### Critical tradeoffs and known bad behavior

- Collective-term fallback is intentionally conservative but can misassign when the same collective term appears later for a different subcomponent.
- Weak single-token aliases are filtered against strong overlapping tokens in same step, but token-only matching can still be noisy on generic terms.
- Section detection for instructions is intentionally conservative; odd short lines can still be false negatives (left as literal steps) to avoid deleting real instructions.

### Tests to read

- `tests/parsing/test_step_ingredient_linking.py`
- `tests/parsing/test_recipe_sections.py`

## EPUB Segmentation Rules That Matter (`cookimport/plugins/epub.py`)

### Why this belongs in parsing docs

Recipe boundary detection directly controls which text reaches parsing/linking/tip systems.

### Current rules in `_find_recipe_end`

- Stops at strong section boundaries and next recipe starts.
- Keeps `Variation`/`Variations` blocks with current recipe.
- Explicitly keeps subsection headers inside recipe, including:
  - `For the X`
  - short `For X`

### Known historical fix

This was added to stop false recipe splits where component headers like `For the Frangipane` were treated as new recipe starts.

### Tests to read

- `tests/test_epub_importer.py`

## Tip Candidate Extraction (`cookimport/parsing/tips.py`)

### Scope labels

- `general`
- `recipe_specific`
- `not_tip`

### Extraction model (current)

- Split text into candidate blocks.
- Extract spans from each block.
- Repair clipped spans using neighboring sentence/block context.
- Judge each span by tipness + generality + context.
- Attach taxonomy tags.

Gates include:

- Advice/action cues
- Cooking anchors
- Narrative rejection signals
- Header/prefix strength (strong vs weak callouts)

### Header/prefix behavior

- Strong tip prefixes (e.g., `Tip:`) can push borderline spans toward tip classification.
- Weak callouts (e.g., `Note:`) are weaker signals.
- Recipe-specific headers (`Why this recipe works`, `Chef's note`, etc.) bias toward `recipe_specific`.
- `ParsingOverrides` can extend tip headers/prefixes.

### Important output distinction

- `tip_candidates` keep all scopes.
- `results.tips` is intended for exported standalone general tips.
- `write_tip_outputs` writes only tips where:
  - scope is `general`
  - `standalone` is true

### Topic candidate behavior

- `build_topic_candidate` wraps text + tags + provenance.
- Standalone block flow (EPUB/PDF) atomizes content and emits topic candidates for each atom.

### Tests to read

- `tests/test_tip_extraction.py`
- `tests/test_tip_recipe_notes.py`
- `tests/test_tip_writer.py`

## Atomization (`cookimport/parsing/atoms.py`)

### What it does

- Splits block text into paragraph/list-item atoms.
- Adds adjacency context (`context_prev`, `context_next`).
- Preserves container metadata (start/end/header).

### Why it matters

- Tip/topic provenance carries atom context, used in downstream debugging and review.

### Tests to read

- `tests/test_atoms.py`

## Knowledge Chunking (`cookimport/parsing/chunks.py`)

### Pipeline

`process_blocks_to_chunks`:

1. `chunk_non_recipe_blocks`
2. `merge_small_chunks`
3. `assign_lanes`
4. `extract_highlights`
5. `consolidate_adjacent_knowledge_chunks` (adjacent same-topic knowledge only)

### Chunk construction

- Heading-driven boundaries first.
- Optional callout boundaries.
- Format-mode boundaries (prose/list shifts).
- Max-char boundary.
- Stop headings (index, acknowledgments, etc.) can be excluded.

### Table-aware behavior

- When stage run setting `table_extraction=on` is enabled, table rows in `non_recipe_blocks` are tagged with `features.table_id` + `features.table_row_index`.
- `chunk_non_recipe_blocks` treats same-`table_id` runs as atomic for max-char splitting (it does not split in the middle of a detected table).
- Chunks carrying `provenance.table_ids` are forced to `knowledge` lane so table facts are not dropped as noise.
- Table chunks are never merged with non-table chunks, in either `merge_small_chunks` or adjacent-chunk consolidation.

### Adjacent consolidation behavior

- Runs after highlights so heading context + merged tags can be used as topic signals.
- Only considers adjacent `knowledge` chunks.
- Requires contiguous absolute block ranges (`left_end + 1 == right_start`, inclusive-range convention).
- Same-topic rule is conservative: same heading context first; tag-only fallback is allowed only when heading context is missing.
- Chunk-size cap uses the active chunk profile max chars.
- Kill switch: set `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0` to disable this pass for debugging/regression isolation.

### Lane assignment

Current effective lanes:

- `knowledge`
- `noise`

`ChunkLane.NARRATIVE` is legacy; reporting treats it as noise.

### Highlight extraction

- Only runs on `knowledge` chunks.
- Reuses tip candidate extractor on chunk text.
- Converts non-`not_tip` candidates into chunk highlights.
- Computes `tip_density` and merged tags.

### Known tradeoffs and bad behavior

- Lane scoring is heuristic; borderline narrative/knowledge chunks will oscillate when heuristics are tuned.
- Default fallback in ambiguous cases tends toward `knowledge`, which can admit low-value chunks.
- Highlight self-containedness requires length/punctuation; short useful cues may be kept but marked non-self-contained.

### Tests to read

- `tests/parsing/test_chunks.py`

## Signals and Cleaning (Support Modules)

## Signals (`cookimport/parsing/signals.py`)

- Lightweight block classifier: ingredient likelihood, instruction likelihood, headers, yield/time flags.
- Supports `ParsingOverrides` for headers, verbs, units.
- Optional spaCy enrichment gated by env var (`COOKIMPORT_SPACY`) or override.

### Caveat

Heuristics are intentionally simple; downstream logic should not assume high-precision NLP quality from signals alone.

## Cleaning (`cookimport/parsing/cleaning.py`)

- Mojibake fixups
- Unicode normalization (NFKC)
- Whitespace normalization
- Hyphenation repair across line breaks
- EPUB-specific normalization path (`normalize_epub_text`) removes soft hyphens/zero-width chars and normalizes unicode fractions/punctuation for ingredient detection stability.

## EPUB Postprocess and Health (`cookimport/parsing/epub_postprocess.py`, `cookimport/parsing/epub_health.py`)

- `postprocess_epub_blocks(...)` runs after `beautifulsoup`/`unstructured`/`markdown` extraction to do shared structural cleanup:
  - split BR-collapsed/table/list multi-line blocks into deterministic per-line blocks
  - strip leading bullet markers
  - drop obvious noise blocks (pagebreak markers/nav leftovers)
- `compute_epub_extraction_health(...)` computes extraction sanity metrics and warning keys (`epub_*`) that are attached to EPUB conversion reports.

### Caveat

Mojibake replacements are heuristic and can be lossy in edge encodings.

## Output Artifacts and Paths

Timestamp root uses `YYYY-MM-DD_HH.MM.SS`.

Under a run output folder:

- Tips: `data/output/<timestamp>/tips/<workbook_stem>/t{index}.json`
- Tip summary: `data/output/<timestamp>/tips/<workbook_stem>/tips.md`
- Topic candidates: `data/output/<timestamp>/tips/<workbook_stem>/topic_candidates.json`
- Topic candidates summary: `data/output/<timestamp>/tips/<workbook_stem>/topic_candidates.md`
- Chunks: `data/output/<timestamp>/chunks/<workbook_stem>/c{index}.json`
- Chunk summary: `data/output/<timestamp>/chunks/<workbook_stem>/chunks.md`
- Tables (when `table_extraction=on`): `data/output/<timestamp>/tables/<workbook_stem>/tables.jsonl` and `tables.md`

## Practical Change Workflow (Recommended)

1. If progress stalls or repeats, read `docs/04-parsing/04-parsing_log.md` first.
2. For step linking, inspect `debug=True` output (`candidates`, `assignments`, group/all-ingredients annotations).
3. Verify with focused tests:
   - `tests/test_step_ingredient_linking.py`
   - `tests/test_ingredient_parser.py`
   - `tests/test_instruction_parser.py`
   - `tests/test_tip_extraction.py`
   - `tests/test_chunks.py`
   - `tests/test_epub_importer.py`
4. Run end-to-end spot check through `cookimport.cli stage` and inspect generated `tips.md` and `chunks.md`.
5. Keep deterministic behavior as default; new ML/LLM options should remain opt-in with deterministic fallback preserved.

## Quick Reference: Most Sensitive Files

- Step linking logic and regressions: `cookimport/parsing/step_ingredients.py`
- EPUB boundary regressions: `cookimport/plugins/epub.py`
- Tip scope drift: `cookimport/parsing/tips.py`
- Lane drift and chunk boundary shifts: `cookimport/parsing/chunks.py`
- Output formatting/selection confusion: `cookimport/staging/writer.py`

## Merged Task Specs (2026-02-19 quick wins)

### 2026-02-19_14.22.11 EPUB common-issues quick wins

Durable parsing-side contract from the quick-win pass:

- Shared EPUB text normalization now handles high-frequency extraction noise classes:
  - soft hyphen and zero-width cleanup,
  - Unicode fraction and punctuation normalization,
  - whitespace stability needed for ingredient/segment heuristics.
- Shared postprocess pass is used after extractor block generation to reduce structural noise:
  - BR-collapsed block splitting into deterministic line blocks,
  - bullet-prefix stripping,
  - nav/TOC and obvious pagebreak noise suppression.
- EPUB extraction health metrics/warnings (`epub_*`) are generated and persisted as diagnostics for downstream triage.

Decision boundaries that should stay explicit:

- Shared postprocess/health pass is intentionally focused on HTML-style extractor outputs (`legacy`, `unstructured`, `markdown`).
- `markitdown` remains intentionally outside this exact postprocess path and should not be silently forced through incompatible cleanup logic.
- Debug extraction tooling should keep parity by calling the same postprocess stage used in importer flow.

## Merged Task Specs (Feb 2026 archival)

### 2026-02-16 unstructured tuning pass

Durable parsing-side contract:
- EPUB HTML pre-normalization before unstructured extraction is explicit and mode-driven (`none`, `br_split_v1`, `semantic_v1`).
- Unstructured parser options (`html_parser_version`, `skip_headers_footers`, preprocess mode) are run settings and must be propagated consistently across stage + prediction generation.
- Debug parity requires writing both raw and normalized spine XHTML artifacts during unstructured runs.

Known caveat preserved:
- Parser `v2` requires `body.Document` / `div.Page` shaped inputs; adapter compatibility shim is required for normal EPUB XHTML.

### 2026-02-19 EPUB common-issues quick wins

Durable parsing-side contract:
- Shared EPUB text normalization (`normalize_epub_text`) handles soft hyphens, zero-width chars, and unicode punctuation/fraction cleanup.
- Shared postprocess (`postprocess_epub_blocks`) performs BR/list/table line cleanup and bullet stripping for HTML-style extractor outputs.
- Extraction health metrics (`compute_epub_extraction_health`) are warning-oriented guardrails and should remain non-blocking.

Known-bad loops to avoid:
- Do not fork postprocess behavior per extractor backend unless there is extractor-specific evidence.
- Keep debug extraction flows aligned with importer postprocess behavior to avoid false regression diagnosis.

## Merged Understandings Batch (2026-02-25 parsing contracts)

### 2026-02-25_16.39.07 chunk consolidation absolute-adjacency + table guard

Merged source:
- `docs/understandings/2026-02-25_16.39.07-chunk-consolidation-absolute-adjacency-and-table-guard.md`

Durable parsing contract:
- `KnowledgeChunk.block_ids` remain sequence-relative (pass4 bundle builders depend on this).
- Adjacency checks for same-topic consolidation use `provenance.absolute_block_range` (inclusive rule: `left_end + 1 == right_start`).
- Table chunks (`provenance.table_ids`) are excluded from all merge phases:
  - `merge_small_chunks`
  - `consolidate_adjacent_knowledge_chunks`

Anti-loop note:
- Do not reinterpret `block_ids` as absolute source indices to "fix" adjacency; that breaks pass4 index mapping contracts.

### 2026-02-25_16.42.42 section-aware step linking + duplicate-safe ingredient identity

Merged source:
- `docs/understandings/2026-02-25_16.42.42-step-linking-section-context-and-duplicate-indexing.md`

Durable parsing contract:
- Section context inputs are optional in `assign_ingredient_lines_to_steps(...)`:
  - `ingredient_section_key_by_line`
  - `step_section_key_by_step`
- Global matching still runs first, but near ties prefer same-section candidates.
- Section scope also applies to the high-impact fallback passes when multiple sections exist:
  - `all ingredients` phrases
  - collective-term fallback (`spices`, `herbs`, `seasonings`)
- Duplicate ingredient text is tracked internally by original ingredient index during assignment so repeated identical lines do not collapse.

Anti-loop note:
- Text-equality identity for ingredient lines is insufficient when duplicate lines are intentional; keep index-based internal identity through assignment.

## Merged Task Specs (2026-02-25 docs/tasks archival batch)

### 2026-02-25_16.24.52 deterministic table extraction + table-aware chunking + pass4 hints

Merged source:
- `docs/tasks/knowledge-tables.md`

Durable parsing contract:
- Deterministic table extraction lives in `cookimport/parsing/tables.py`:
  - row detection supports pipe/tab/multispace separators,
  - grouped runs are annotated onto non-recipe blocks (`features.table_id`, `features.table_row_index`, `table_hint`).
- Chunking remains table-aware:
  - no max-char split in the middle of a single detected table,
  - chunks with `provenance.table_ids` are forced to the `knowledge` lane.
- Pass4 receives table structure as hints only (`table_hint`) while keeping evidence text verbatim.

Known caveat preserved:
- Current fixture books may still produce empty detected table sets if extractor output flattened separators; this is expected and should not be treated as parser crash.

### 2026-02-25_16.39.01 adjacent same-topic chunk consolidation

Merged source:
- `docs/tasks/combine-knowledge-chunks.md`

Durable parsing contract:
- Consolidation is adjacent-only and deterministic left-to-right; no reordering/non-adjacent merges.
- True adjacency is checked with absolute source ranges (`provenance.absolute_block_range`), not filtered-list adjacency.
- Topic similarity stays conservative:
  - heading-context match first,
  - tag-overlap fallback only when heading context is missing.
- Kill switch remains available for isolation/debugging:
  - `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0`

### 2026-02-25_16.45.50 multi-component recipe sections and section-aware step linking

Merged source:
- `docs/tasks/Sub-grouping-recipe-steps.md`

Durable parsing contract:
- `cookimport/parsing/sections.py` is the section extraction boundary for ingredient + instruction headers.
- Step-linking uses section context for near-tie resolution and fallback-pass scoping when multiple sections exist.
- Duplicate ingredient lines are tracked internally by ingredient index during assignment to avoid text-collision regressions.

Cross-boundary note:
- Final cookbook3 output remains schema-stable; section structure is exposed through additive staging surfaces (`sections/...` artifacts and intermediate JSON-LD `HowToSection`).
