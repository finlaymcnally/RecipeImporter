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

- `cookimport/parsing/__init__.py` (public parsing utility exports)
- `cookimport/parsing/ingredients.py`
- `cookimport/parsing/instruction_parser.py`
- `cookimport/parsing/yield_extraction.py`
- `cookimport/parsing/step_segmentation.py`
- `cookimport/parsing/step_ingredients.py`
- `cookimport/parsing/section_detector.py`
- `cookimport/parsing/multi_recipe_splitter.py`
- `cookimport/parsing/sections.py`
- `cookimport/parsing/tips.py`
- `cookimport/parsing/atoms.py`
- `cookimport/parsing/chunks.py`
- `cookimport/parsing/tables.py`
- `cookimport/parsing/signals.py`
- `cookimport/parsing/cleaning.py`
- `cookimport/parsing/tip_taxonomy.py`
- `cookimport/parsing/block_roles.py`
- `cookimport/parsing/recipe_block_atomizer.py`
- `cookimport/parsing/canonical_line_roles.py`
- `cookimport/parsing/markdown_blocks.py`
- `cookimport/parsing/epub_extractors.py`
- `cookimport/parsing/epub_table_rows.py`
- `cookimport/parsing/epub_html_normalize.py`
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/parsing/markitdown_adapter.py`
- `cookimport/parsing/epub_postprocess.py`
- `cookimport/parsing/epub_health.py`
- `cookimport/parsing/patterns.py`
- `cookimport/parsing/pattern_flags.py`
- `cookimport/parsing/spacy_support.py`

Unstructured adapter note:
- `unstructured_adapter.py` now performs deterministic multiline splitting for recipe-like `Title`/`NarrativeText`/`UncategorizedText`/`Text` blocks (in addition to `ListItem` newline splits), preserving provenance with `unstructured_stable_key` suffixes (`.s0`, `.s1`, ...) and `unstructured_split_reason`.

Parsing-adjacent module (not in current stage recipe-path runtime):

- `cookimport/parsing/classifier.py` (heuristic line classifier used by tagging tests)

Major call sites:

- Recipe draft conversion: `cookimport/staging/draft_v1.py`
- EPUB segmentation + standalone tip/topic extraction: `cookimport/plugins/epub.py`
- PDF importer tip/topic extraction + block signal enrichment: `cookimport/plugins/pdf.py`
- Text importer tip/topic extraction + block signal enrichment: `cookimport/plugins/text.py`
- Excel importer recipe-level tip extraction: `cookimport/plugins/excel.py`
- Stage/bench orchestration of tip/chunk/table passes: `cookimport/cli.py`, `cookimport/cli_worker.py`
- Label Studio ingest chunk/table/tip orchestration: `cookimport/labelstudio/ingest.py`
- EPUB debug CLI diagnostics path: `cookimport/epubdebug/cli.py`
- JSON-LD section shaping (`HowToSection`, ingredient section metadata): `cookimport/staging/jsonld.py`
- Candidate confidence scoring using parsing signals: `cookimport/core/scoring.py`
- Pass4 knowledge-job bundle construction from parser chunks: `cookimport/llm/codex_farm_knowledge_jobs.py`
- Output writing: `cookimport/staging/writer.py`

## End-to-End Data Flow (Current)

### Recipe path

1. Importer creates `RecipeCandidate` objects.
2. `cookimport/staging/draft_v1.py` converts each candidate:
   - optional deterministic fallback step segmentation runs first (`instruction_step_segmentation_policy=off|auto|always`, backend `heuristic_v1|pysbd_v1`)
   - ingredient lines parsed with `parse_ingredient_line`
   - steps parsed with `parse_instruction`
   - yield phrase selection/parsing runs through `derive_yield_fields(...)` (`p6_yield_mode`)
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
   - Table-aware enrichment and artifact writing are driven by `extract_and_annotate_tables(...)` in CLI + Label Studio ingest paths
   - Pass4 knowledge job builders also consume parser chunks (`cookimport/llm/codex_farm_knowledge_jobs.py`)
4. Writer emits:
   - tips
   - topic candidates
   - chunks and chunk summary

## Ingredient Parsing (`cookimport/parsing/ingredients.py`)

### Main behavior

- Uses `ingredient-parser-nlp` (`parse_ingredient(..., string_units=True)`).
- Supports optional run-setting backends/normalizers:
  - `ingredient_parser_backend`: `ingredient_parser_nlp | quantulum3_regex | hybrid_nlp_then_quantulum3`
  - `ingredient_text_fix_backend`: `none | ftfy`
  - `ingredient_pre_normalize_mode`: `legacy | aggressive_v1`
  - `ingredient_packaging_mode`: `off | regex_v1`
  - `ingredient_unit_canonicalizer`: `legacy | pint`
  - `ingredient_missing_unit_policy`: `null | each | legacy_medium`
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

- Default missing-unit policy is now explicit and defaults to `null` (no implicit `"medium"` unit).
- Packaging-mode regex hoist (`ingredient_packaging_mode=regex_v1`) moves package-size hints into `note` for lines like `1 (14-ounce) can tomatoes`.
- Post-parse repair is deterministic: it preserves `raw_text`, repairs invalid quantity/unit/name combinations, and keeps fallback ingredient names instead of dropping lines.
- `warm_ingredient_parser()` exists to pre-load model quietly.

### Tests to read

- `tests/parsing/test_ingredient_parser.py`

## Instruction Metadata Parsing (`cookimport/parsing/instruction_parser.py`)

### Extracted fields per step

- `time_items`: list of detected durations
- `total_time_seconds`: strategy-selected rollup for that step (`sum_all_v1`, `max_v1`, `selective_sum_v1`)
- `temperature_items`: all matched temperatures with normalized unit/value and `is_oven_like` flag
- `temperature`, `temperature_unit`, `temperature_text`: compatibility fields that mirror the first matched temperature expression

### Time behavior

- Backends:
  - `regex_v1` (default)
  - `quantulum3_v1` (optional dependency)
  - `hybrid_regex_quantulum3_v1` (regex fallback first)
- Handles seconds/minutes/hours/days and abbreviations (`mins`, `hrs`, `secs`).
- Ranges use midpoint (`20 to 30 minutes` => 25 minutes).
- Strategy notes:
  - `sum_all_v1` keeps legacy behavior.
  - `max_v1` keeps only longest duration in a step.
  - `selective_sum_v1` skips obvious frequency spans (`every 5 minutes`) and collapses `or` alternatives.

### Temperature behavior

- Backends:
  - `regex_v1` (default)
  - `quantulum3_v1` (optional dependency)
  - `hybrid_regex_quantulum3_v1` (regex fallback first)
- Unit conversion backends:
  - `builtin_v1` (default)
  - `pint_v1` (optional dependency; validation guard)
- Handles `400F`, `350°F`, `375 degrees F`, `220 degrees celsius`.
- Returns all matches in `temperature_items`; compatibility fields keep first match for legacy callers.
- Oven-like classification is deterministic (`p6_ovenlike_mode=keywords_v1|off`) and is used by staging to derive recipe-level `max_oven_temp_f`.

### Known limitations

- Regex-first extraction can miss niche phrasing where optional parser backends may perform better.
- Yield unit-name singularization in scored mode is heuristic and intentionally lightweight.

### Tests to read

- `tests/parsing/test_instruction_parser.py`
- `tests/parsing/test_yield_extraction.py`

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

- `cookimport/parsing/section_detector.py` is the shared deterministic detector used by importers and parser section helpers.
- `cookimport/parsing/sections.py` keeps the historical public API and delegates detection internals to `section_detector.py`.
- Shared detection currently supports two run-setting backends:
  - `legacy` (default, prior behavior)
  - `shared_v1` (new shared detector path)
- `sections.py` provides deterministic section extraction for:
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

### Extraction backend plumbing that affects parsing inputs

- `cookimport/parsing/epub_extractors.py` defines the `beautifulsoup` / `unstructured` / `markdown` backend adapters.
- `cookimport/parsing/markitdown_adapter.py` handles the `markitdown` backend conversion (`EPUB -> markdown`), then `cookimport/parsing/markdown_blocks.py` converts markdown to deterministic `Block` objects.
- `cookimport/parsing/epub_html_normalize.py` pre-normalizes XHTML before unstructured partitioning.
- `cookimport/parsing/unstructured_adapter.py` maps unstructured elements to deterministic blocks + diagnostics metadata.
- `cookimport/parsing/epub_table_rows.py` preserves EPUB `<tr>` rows as structured cell arrays plus visible `|`-delimited row text so downstream table detection does not have to guess column boundaries.
  - BeautifulSoup-based EPUB extraction preserves empty cells instead of collapsing them away.
  - Unstructured-based EPUB extraction expands `metadata.text_as_html` tables into explicit row blocks when that HTML is available, instead of trying to recover columns from already-flattened text.
- `cookimport/parsing/epub_postprocess.py` and `cookimport/parsing/epub_health.py` are shared guardrails after HTML-based extraction.
- `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py` both read `run_settings.section_detector_backend` and can route field extraction through the shared detector when set to `shared_v1`.
- obvious conversion/reference titles now carry a narrow recipe-likeness penalty so Food Lab-style tables can stay in non-recipe flow and reach `tables.py` instead of being trapped as fake recipes.

## Deterministic Pattern Flags (`cookimport/parsing/pattern_flags.py`)

### Scope

- Shared deterministic detector/action helper used by EPUB and PDF importers before candidate extraction and during overlap resolution.

### Current behavior

- Detects TOC-like contiguous clusters and duplicate title-intro flows from block text only (no LLM dependency).
- Returns structured diagnostics (`PatternDiagnostics`) with:
  - `block_flags`
  - cluster summaries/scores
  - duplicate-title pair metadata
  - pre-candidate `excluded_indices`
- Provides action helpers:
  - `apply_candidate_start_trims(...)`
  - `resolve_overlap_duplicate_candidates(...)`
  - `pattern_warning_lines(...)` for stable report warning strings.

### Where outputs are consumed

- EPUB/PDF add `pattern_flags`/`pattern_actions` to candidate provenance location metadata.
- `cookimport/core/scoring.py` applies deterministic penalties from those flags and records reasons in scoring debug output.

### Known historical fix

This was added to stop false recipe splits where component headers like `For the Frangipane` were treated as new recipe starts.

### Tests to read

- `tests/ingestion/test_epub_importer.py`
- `tests/ingestion/test_epub_extraction_quickwins.py`
- `tests/parsing/test_epub_html_normalize.py`
- `tests/ingestion/test_unstructured_adapter.py`
- `tests/parsing/test_markdown_blocks.py`

## Shared Multi-Recipe Splitter (`cookimport/parsing/multi_recipe_splitter.py`)

### Scope

- Shared deterministic splitter for one candidate span that may contain multiple recipes.
- Used by Text, EPUB, and PDF importers when `multi_recipe_splitter=rules_v1`.

### Backends

- `legacy`: importer-local behavior (existing text split path, EPUB/PDF no post-candidate split).
- `off`: passthrough; no split attempt.
- `rules_v1`: title-like boundary detection + section coverage thresholds + local recipe-signal guard.

### Guardrails and thresholds

- `For the X` false-boundary suppression reuses `detect_sections_from_lines(...)` in `section_detector.py` when `multi_recipe_for_the_guardrail` is enabled.
- Coverage thresholds (`multi_recipe_min_ingredient_lines`, `multi_recipe_min_instruction_lines`) use ingredient/instruction signal lines (content and section-header signals) so short recipe units with clear headers remain splittable.
- Optional trace payload records accepted/rejected boundaries and guardrail-blocked indices when `multi_recipe_trace=true`.

### Tests to read

- `tests/parsing/test_multi_recipe_splitter.py`
- `tests/ingestion/test_text_importer.py`
- `tests/ingestion/test_epub_importer.py`
- `tests/ingestion/test_pdf_importer.py`

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

- `tests/parsing/test_tip_extraction.py`
- `tests/parsing/test_tip_recipe_notes.py`
- `tests/staging/test_tip_writer.py`

## Atomization (`cookimport/parsing/atoms.py`)

### What it does

- Splits block text into paragraph/list-item atoms.
- Adds adjacency context (`context_prev`, `context_next`).
- Preserves container metadata (start/end/header).

### Why it matters

- Tip/topic provenance carries atom context, used in downstream debugging and review.

### Tests to read

- `tests/core/test_atoms.py`

## Recipe Block Atomization (`cookimport/parsing/recipe_block_atomizer.py`)

### What it does

- Splits merged recipe blocks into atomic line candidates for canonical line-label benchmark work.
- Emits serializable `AtomicLineCandidate` rows with deterministic `atomic_index`, adjacency context (`prev_text`, `next_text`), candidate labels, and rule tags.
- `atomic_block_splitter=atomic-v1` enables boundary-first splitting; `atomic_block_splitter=off` keeps one candidate per source block (no sub-line splitting).

### Current rules

- Boundary-first splitting for `NOTE:`, yield prefixes (`MAKES`/`SERVES`/`YIELDS`), method headings (`TO MAKE`, `FOR THE`, `FOR SERVING`), and inline numbered steps.
- Yield-first segments are split so trailing quantity-led ingredient runs become separate candidates.
- Quantity-run splitting now keeps instruction-like prose whole and blocks broken dual-unit fragments (`2 cups/` + `475 g ...`) from being atomized into fake ingredient rows.
- Quantity ranges like `4 to 6 chicken leg quarters` are treated as ingredient-like candidates, not yield.
- Short quantity-led lines (for example `1 fresh bay leaf`, `8 thin slices ...`) now stay ingredient-like with deterministic negative guards for time/instructional fragments.
- Heading-like title rows now emit `RECIPE_TITLE` candidates (`title_like`) before generic fallback labels.
- Note-like prose rows now emit `RECIPE_NOTES` candidates (`note_like_prose`) before instruction heuristics.
- Yield regex intentionally excludes bare `serving` to avoid splitting prose lines like `before serving`.

### Tests to read

- `tests/parsing/test_recipe_block_atomizer.py`

## Canonical Line Roles (`cookimport/parsing/canonical_line_roles.py`)

### What it does

- Assigns one canonical benchmark label per `AtomicLineCandidate` using deterministic rules first.
- Supports optional Codex fallback for unresolved or low-confidence candidates when `line_role_pipeline=codex-line-role-v1`.
- Emits `CanonicalLineRolePrediction` rows with `decided_by` provenance (`rule`, `codex`, `fallback`) and reason tags.
- Prediction rows also carry `within_recipe_span` context (from atomized candidates), which benchmark Milestone-5 diagnostics reuse for slice metrics and knowledge-budget reporting.

### Current safeguards

- Rule-first path handles low-ambiguity cases (`NOTE`, yield, ingredient-like, method headers, variants, and instruction lines).
- Compact all-caps title-like rows are disambiguated to `HOWTO_SECTION` when neighboring lines indicate an internal component/subsection flow and the next line is not a yield boundary.
- `YIELD_LINE` now has strict header validation (`MAKES`/`SERVES`/`YIELDS` prefix plus short header shape and quantity/count hint); non-header yield-like prose is sanitized to structural fallback (`INSTRUCTION_LINE` or `OTHER`) instead of forcing yield.
- `TIME_LINE` is only used for primary time metadata; non-primary `TIME_LINE` predictions are sanitized to `INSTRUCTION_LINE` (or `OTHER` outside recipe spans).
- Inside recipe spans, `KNOWLEDGE` is restricted and sanitized out unless prose + neighbor context supports it.
- Outside recipe spans, prose now defaults to `OTHER`; `KNOWLEDGE` is used only when explicit knowledge cues are present.
- When pass4 knowledge harvest is enabled, its block-classification artifact can further arbitrate outside-span `KNOWLEDGE` versus `OTHER` after line-role projection; this seam is binary only and does not override recipe-structural labels.
- Outside recipe spans, `HOWTO_SECTION` is hard-denied in the v1 safety policy.
- Outside recipe spans, `RECIPE_TITLE`/`RECIPE_VARIANT` now require compact-heading shape plus neighboring (±2 lines) structural evidence; otherwise they are downgraded to `OTHER`/`KNOWLEDGE`.
- Outside recipe spans, `INSTRUCTION_LINE`/`INGREDIENT_LINE` now require local recipe evidence (±2 lines) and are downgraded when evidence is missing.
- `RECIPE_TITLE` now requires supportive next-line context when available (yield boundary, ingredient/instruction flow, or recipe-structure cues) to reduce title-vs-howto/title-vs-narrative confusion.
- Short ingredient fragments (for example split quantity/name rows) now get neighbor-aware rescue to `INGREDIENT_LINE` when adjacent ingredient-dominant context supports it.
- Codex fallback uses strict JSON validation with the full global line-role label set available on every row; parse failures now attempt deterministic recovery and otherwise force `OTHER`, with parse-error artifacts written under `line-role-pipeline/prompts/parse_errors.json`.
- Title-like recovery no longer depends on per-row Codex allowlist expansion; atomizer/deterministic heuristics still influence non-LLM ownership logic.
- Low-confidence deterministic `RECIPE_TITLE` outcomes are held on the rule path (not escalated away to codex).
- Outside-span low-confidence escalation is disabled by default; codex escalation remains inside-span-first (optional override: `COOKIMPORT_LINE_ROLE_OUTSIDE_SPAN_LOW_CONFIDENCE_ESCALATION=1`).
- Codex mode now applies an explicit line-role guardrail mode after sanitization: `off`, `preview`, or `enforce`.
- `preview` computes the same downgrade decisions as enforce mode but leaves accepted predictions unchanged; `enforce` applies partial downgrades or full-source fallback to deterministic baseline labels.
- Guardrail diagnostics are written under `line-role-pipeline/`:
  - `guardrail_report.json`
  - `guardrail_changed_rows.jsonl`
- Legacy compatibility sidecars remain available when guardrail diagnostics exist:
  - `do_no_harm_diagnostics.json`
  - `do_no_harm_changed_rows.jsonl`
- Codex fallback batches now run with bounded in-flight concurrency (parser default `4` per book; explicit env override via `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT`; ingest callers can pass `codex_max_inflight`) and merge back deterministically by atomic index/prompt order.
- Prompt logging internals are thread-safe for concurrent codex batch workers (`prompt_*.txt`, `response_*.txt`, `parsed_*.json`, and dedup log writes).
- Codex call failures now use bounded retry/backoff before fallback (`3` attempts, exponential backoff base `1.5s`).
- Canonical line-role predictions are cached on disk by source hash + run-settings hash + candidate fingerprint; reruns can reuse cache and skip codex calls (`COOKIMPORT_LINE_ROLE_CACHE_ROOT` overrides cache location).
- Codex canonical line-role batches now emit progress callbacks as `task X/Y | running N`, so benchmark/import spinners can display ETA during this stage.
- Canonical line-role deterministic labeling now also emits `task X/Y` progress callbacks, so ETA appears in this stage even before/without codex batch escalation.

### Related modules

- `cookimport/llm/canonical_line_role_prompt.py`
- `cookimport/llm/codex_exec.py` (fail-closed compatibility only; active runtime line-role transport is CodexFarm through `canonical_line_roles.py`)
- `llm_pipelines/prompts/canonical-line-role-v1.prompt.md`

### Tests to read

- `tests/parsing/test_canonical_line_roles.py`

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

- Table rows in `non_recipe_blocks` are tagged with `features.table_id` + `features.table_row_index` during normal stage/prediction runs.
- `detect_tables_from_non_recipe_blocks(...)` trusts structured EPUB row metadata first, then falls back to visible delimiters / flattening heuristics for older or non-EPUB sources.
- Flattened reference-table salvage is intentionally narrow:
  - target headings are conversions, weights, temperatures, equivalencies, and similar reference sections,
  - salvaged tables should carry lower confidence / notes instead of pretending they were clean structured-table detections.
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
- Regex/header/unit/verb primitives are defined in `cookimport/parsing/patterns.py`.
- spaCy loading + POS feature extraction live in `cookimport/parsing/spacy_support.py`.

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

## Heuristic Classifier (Parsing-Adjacent) (`cookimport/parsing/classifier.py`)

- Provides standalone line-level `ingredient`/`instruction`/`other` classification helpers.
- This module is currently test-scoped and not on the default stage recipe conversion path.
- Useful when debugging/iterating on heuristic classifier behavior outside draft-v1 assignment.

### Tests to read

- `tests/tagging/test_classifier.py`

## Output Artifacts and Paths

Timestamp root uses `YYYY-MM-DD_HH.MM.SS`.

Under a run output folder:

- Tips: `data/output/<timestamp>/tips/<workbook_stem>/t{index}.json`
- Tip summary: `data/output/<timestamp>/tips/<workbook_stem>/tips.md`
- Topic candidates: `data/output/<timestamp>/tips/<workbook_stem>/topic_candidates.json`
- Topic candidates summary: `data/output/<timestamp>/tips/<workbook_stem>/topic_candidates.md`
- Chunks: `data/output/<timestamp>/chunks/<workbook_stem>/c{index}.json`
- Chunk summary: `data/output/<timestamp>/chunks/<workbook_stem>/chunks.md`
- Tables: `data/output/<timestamp>/tables/<workbook_stem>/tables.jsonl` and `tables.md`

## Practical Change Workflow (Recommended)

1. If progress stalls or repeats, read `docs/04-parsing/04-parsing_log.md` first.
2. For step linking, inspect `debug=True` output (`candidates`, `assignments`, group/all-ingredients annotations).
3. Verify with focused tests:
   - `tests/parsing/test_step_ingredient_linking.py`
   - `tests/parsing/test_ingredient_parser.py`
   - `tests/parsing/test_instruction_parser.py`
   - `tests/parsing/test_tip_extraction.py`
   - `tests/parsing/test_chunks.py`
   - `tests/parsing/test_tables.py`
   - `tests/parsing/test_cleaning_epub.py`
   - `tests/parsing/test_epub_html_normalize.py`
   - `tests/parsing/test_markdown_blocks.py`
   - `tests/ingestion/test_epub_importer.py`
   - `tests/ingestion/test_epub_extraction_quickwins.py`
   - `tests/ingestion/test_unstructured_adapter.py`
4. Run end-to-end spot check through `cookimport.cli stage` and inspect generated `tips.md` and `chunks.md`.
5. Keep deterministic behavior as default; new ML/LLM options should remain opt-in with deterministic fallback preserved.

## Quick Reference: Most Sensitive Files

- Step linking logic and regressions: `cookimport/parsing/step_ingredients.py`
- EPUB boundary regressions: `cookimport/plugins/epub.py`
- Tip scope drift: `cookimport/parsing/tips.py`
- Lane drift and chunk boundary shifts: `cookimport/parsing/chunks.py`
- Output formatting/selection confusion: `cookimport/staging/writer.py`

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

Durable parsing contract:
- `KnowledgeChunk.block_ids` remain sequence-relative (pass4 bundle builders depend on this).
- Adjacency checks for same-topic consolidation use `provenance.absolute_block_range` (inclusive rule: `left_end + 1 == right_start`).
- Table chunks (`provenance.table_ids`) are excluded from all merge phases:
  - `merge_small_chunks`
  - `consolidate_adjacent_knowledge_chunks`

Anti-loop note:
- Do not reinterpret `block_ids` as absolute source indices to "fix" adjacency; that breaks pass4 index mapping contracts.

### 2026-02-25_16.42.42 section-aware step linking + duplicate-safe ingredient identity

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

## Merged Parsing Contracts (2026-02-25 archival batch)

### 2026-02-25_16.24.52 deterministic table extraction + table-aware chunking + pass4 hints

Durable parsing contract:
- Deterministic table extraction lives in `cookimport/parsing/tables.py`:
  - row detection supports pipe/tab/multispace separators plus structured EPUB row metadata (`features.epub_table_cells`),
  - grouped runs are annotated onto non-recipe blocks (`features.table_id`, `features.table_row_index`, `table_hint`).
- EPUB HTML extraction preserves empty cells and row order in `cookimport/parsing/epub_table_rows.py`; both BeautifulSoup row builders and the unstructured adapter now emit `epub_table_row` blocks with `|`-delimited visible text plus `features.epub_table_cells`.
- Chunking remains table-aware:
  - no max-char split in the middle of a single detected table,
  - chunks with `provenance.table_ids` are forced to the `knowledge` lane.
- Pass4 receives table structure as hints only (`table_hint`) while keeping evidence text verbatim.

Known caveat preserved:
- Already-collapsed reference prose may still need narrow salvage heuristics; `tables.py` now includes a low-confidence flattened-reference fallback, but broad free-text reconstruction is intentionally out of scope.

### 2026-02-25_16.39.01 adjacent same-topic chunk consolidation

Durable parsing contract:
- Consolidation is adjacent-only and deterministic left-to-right; no reordering/non-adjacent merges.
- True adjacency is checked with absolute source ranges (`provenance.absolute_block_range`), not filtered-list adjacency.
- Topic similarity stays conservative:
  - heading-context match first,
  - tag-overlap fallback only when heading context is missing.
- Kill switch remains available for isolation/debugging:
  - `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0`

### 2026-02-25_16.45.50 multi-component recipe sections and section-aware step linking

Durable parsing contract:
- `cookimport/parsing/sections.py` is the section extraction boundary for ingredient + instruction headers.
- Step-linking uses section context for near-tie resolution and fallback-pass scoping when multiple sections exist.
- Duplicate ingredient lines are tracked internally by ingredient index during assignment to avoid text-collision regressions.

Cross-boundary note:
- Final cookbook3 output remains schema-stable; section structure is exposed through additive staging surfaces (`sections/...` artifacts and intermediate JSON-LD `HowToSection`).

## 2026-02-27 Merged Understandings: Parsing Docs Retirement and Coverage

Merged source notes:
- `docs/understandings/2026-02-27_19.46.23-parsing-docs-stale-content-retirement.md`
- `docs/understandings/2026-02-27_19.50.31-parsing-doc-module-callsite-coverage-audit.md`

Current-contract additions:
- Keep historical notes only for still-live parser features (unstructured tuning, postprocess/health, section-aware linking, chunk/table integration).
- Keep removed race-backend and dead task-path references retired.
- Parsing docs should explicitly include helper modules (`markitdown_adapter.py`, `patterns.py`, `spacy_support.py`) and cross-boundary call sites (`plugins/*`, CLI worker paths, Label Studio ingest, staging/jsonld, scoring).
- `cookimport/parsing/classifier.py` is parsing-adjacent but currently test-scoped for tagging tests, not default stage recipe runtime.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_22.24.26 priority4 current state audit
- Source: `docs/understandings/2026-02-27_22.24.26-priority4-current-state-audit.md`
- Summary: Priority-4 current-state audit: ingredient parser remains legacy and options are not wired yet.

### 2026-02-27_22.24.37 priority6 current time temp yield state
- Source: `docs/understandings/2026-02-27_22.24.37-priority6-current-time-temp-yield-state.md`
- Summary: Priority-6 discovery: parser/staging are still baseline-only, with fragmented yield extraction and no Priority 6 run-setting surface.

### 2026-02-27_22.27.26 priority5 current step segmentation status
- Source: `docs/understandings/2026-02-27_22.27.26-priority5-current-step-segmentation-status.md`
- Summary: Priority-5 discovery: instruction fallback segmentation is not implemented yet, and staging/bench wiring points that must change are now mapped.

### 2026-02-27_22.37.08 priority6 rebuild validation audit
- Source: `docs/understandings/2026-02-27_22.37.08-priority6-rebuild-validation-audit.md`
- Summary: Priority-6 revalidation audit: parser/staging/yield/run-settings contracts remain baseline-only and justify the active ExecPlan scope.

### 2026-02-27_22.38.32 priority5 wiring refresh audit
- Source: `docs/understandings/2026-02-27_22.38.32-priority5-wiring-refresh-audit.md`
- Summary: Priority-5 refresh audit: instruction fallback segmentation is still unimplemented, and the exact stage/run-settings/bench wiring points remain mapped.

### 2026-02-27_22.41.18 priority2 shared backend header preservation and test double signature
- Source: `docs/understandings/2026-02-27_22.41.18-priority2-shared-backend-header-preservation-and-test-double-signature.md`
- Summary: Priority-2 implementation discovery: shared section backend must preserve standalone component headers, and ingest tests should accept additive importer kwargs.

### 2026-02-27_23.05.12 priority6 latest tree gap revalidation
- Source: `docs/understandings/2026-02-27_23.05.12-priority6-latest-tree-gap-revalidation.md`
- Summary: Priority 6 latest-tree revalidation: parser, staging, and run settings still expose baseline behavior only.

### 2026-02-27_23.22.41 priority6 runtime wiring map
- Source: `docs/understandings/2026-02-27_23.22.41-priority6-runtime-wiring-map.md`
- Summary: Priority 6 wiring map: run settings flow into stage/pred-run via run_config, then draft_v1 consumes parser/yield options from that shared payload.

### 2026-02-27_23.39.38 priority6 wiring and ovenlike audit
- Source: `docs/understandings/2026-02-27_23.39.38-priority6-wiring-and-ovenlike-audit.md`
- Summary: Priority 6 wiring audit found selector-forwarding gaps in ingest/pred-run/manifests and refined oven-like temperature suppression logic to a tighter local negative-hint window.

Current-contract additions from this audit:
- If `p6_*` selectors are expected, confirm they are present in:
  - benchmark call kwargs,
  - ingest signatures + `build_run_settings(...)`,
  - pred-run helper forwarding,
  - benchmark prediction-stage and eval run manifests.
- `max_oven_temp_f` extraction is intentionally context-sensitive:
  - broad positive oven context is allowed,
  - negative hints are applied in a local window near the matched temperature,
  - distant `internal` mentions should not suppress nearby preheat/bake temperatures.

## 2026-02-27 tasks consolidation (migrated from `docs/tasks`)

Merged task files (creation order in `docs/tasks`):
- `priority-4.md`
- `priority-5.md`
- `priority-6.md`

Current parsing contracts added/confirmed by those task files:
- Priority 4 ingredient parsing hardening is implemented with explicit missing-unit policy controls. Default behavior is now `ingredient_missing_unit_policy=null` (no implicit `medium`), with explicit compatibility mode `legacy_medium`.
- Priority 5 fallback instruction segmentation is implemented and wired end-to-end with `instruction_step_segmentation_policy=off|auto|always` plus backend `instruction_step_segmenter=heuristic_v1|pysbd_v1`. Draft-v1, intermediate JSON-LD, and section artifacts use the same effective instruction shaping.
- Priority 6 time/temperature/yield upgrades are implemented with additive parser metadata and run-config selectors (`p6_*`), including richer `temperature_items`, strategy-based time rollups, centralized yield parsing, and staged `max_oven_temp_f` derivation.

Known anti-loop reminders from the merged task docs:
- For Priority 5 regressions, check auto-threshold behavior and numbered-step fragment handling before changing sentence split regexes.
- For Priority 6 reproducibility, verify `p6_*` selectors are present in benchmark/stage run-config surfaces and threaded through Label Studio ingest signatures.
- For Priority 4 section-header regressions (`Garnish`-style one-word headers), inspect header heuristics before blaming parser backend output.

## 2026-02-28 task consolidation (`docs/tasks` pattern detector rollout context)

Merged task file:
- `2026-02-28_12.19.18-deterministic-pattern-detector-and-codex-hints.md`

Parsing-side contract reminders from this rollout:
- `cookimport/parsing/pattern_flags.py` is the shared deterministic boundary for TOC-like detection, duplicate-title intro detection, overlap candidate resolution, and stable warning-line generation.
- Current deterministic penalty constants were held stable during rollout (`toc=0.18`, `duplicate_title=0.09`, `overlap_duplicate=0.26`) after targeted regression checks.
- `pattern_hints` exposure to pass1 is advisory metadata only and remains run-settings-gated/default-off (`codex_farm_pass1_pattern_hints_enabled=false`); parsing/import behavior must remain deterministic-first.

## 2026-02-28 merged understandings (pattern detector and hint-surface status)

Merged source notes:
- `docs/understandings/2026-02-28_12.16.27-pattern-detectors-and-heads-up-integration-points.md`
- `docs/understandings/2026-02-28_12.44.31-pattern-detector-plan-doc-lag-discovery.md`

Current parsing-contract additions:
- Deterministic pattern suppression belongs at importer candidate boundary (post extraction, pre candidate detection) and currently uses shared logic in `cookimport/parsing/pattern_flags.py`.
- Candidate rejection path remains non-destructive: rejected pattern-heavy candidates are preserved as non-recipe blocks.
- Existing EPUB extraction-health signals (duplicate-line rates and warning keys) are diagnostics, not standalone suppression behavior.
- Codex heads-up integration is telemetry-ready, and pass1 `pattern_hints` remains default-off and metadata-only behind `codex_farm_pass1_pattern_hints_enabled`.
- Practical workflow rule: when plan/docs claim pattern-detector work is pending, verify runtime/tests first because this feature set is already largely shipped.

## 2026-03-03 merged understandings digest (atomizer split order + canonical line-role guardrail)

Merged source notes:
- `docs/understandings/2026-03-02_23.37.00-recipe-block-atomizer-split-order.md`
- `docs/understandings/2026-03-03_00.29.00-canonical-line-role-outside-span-prose-guardrail.md`

Current parsing contracts to keep:
- Recipe-block atomization is most stable with this deterministic order:
  1) split on explicit boundary markers (`NOTE:`, yield lines, `TO MAKE`/`FOR THE`, inline numbered step starts),
  2) split yield-leading segments on later quantity starts,
  3) split remaining quantity-run segments.
- For canonical line-role labeling, evaluate outside-recipe prose before generic instruction-sentence fallback.
- If a line is prose-like and outside recipe span, prefer `KNOWLEDGE` instead of `INSTRUCTION_LINE`.
- This ordering preserves recipe-span precision while avoiding narrative false positives in canonical benchmark labeling.

## 2026-03-03 merged understanding digest (canonical title/note remediation)

Merged source note:
- `docs/understandings/2026-03-03_16.38.03-canonical-line-role-title-note-fix-implementation.md`

Current parsing contracts to keep:
- Title-like headings should keep `RECIPE_TITLE` reachable through atomizer hints and deterministic/Codex ownership logic without relying on per-row Codex allowlists.
- Deterministic title hits should not be escalated away when confidence is low.
- Note-like prose should not be pre-classified as `INSTRUCTION_LINE` by broad punctuation-only sentence rules.
- Bare `serving` in prose is not treated as a yield boundary marker.


## 2026-03-03 merged understandings digest (docs/understandings cleanup)

This section consolidates notes that were previously in `docs/understandings`.
Detailed chronology and preserved deep notes are in `04-parsing_log.md`.

Merged source notes (chronological):
- `2026-03-03_16.23.15-line-role-title-note-regression-root-cause.md`: Why SeaAndSmoke single-offline codex run can improve strict accuracy but crater macro-F1: line-role title/note failure modes.
- `2026-03-03_16.38.03-canonical-line-role-title-note-fix-implementation.md`: Canonical line-role fix implementation notes: title allowlist reachability, deterministic title hold, note-vs-instruction heuristic tightening, and serving/yield split guard.
- `2026-03-03_19.21.23-canonical-next-error-buckets.md`: Post-fix canonical line-role diagnosis: next highest-impact buckets are ingredient recall misses, title-vs-howto overcalls, and quantity-fragment atomization artifacts.
- `2026-03-03_19.45.44-canonical-quantity-split-and-subheading-context-guards.md`: Canonical line-role quality gains came from blocking instruction-prose quantity splitting and using neighbor context to treat compact title-like rows as HOWTO_SECTION when they are internal subsections.

## 2026-03-03 docs/tasks consolidation batch (canonical line-role title/note and next-bucket fixes)

Merged source task files (timestamp/file order):
- `docs/tasks/2026-03-03_16.31.29-canonical-line-role-title-notes-fixes.md`
- `docs/tasks/2026-03-03_19.21.23-canonical-line-role-recall-subheading-fragment-guards.md`

Current parsing contracts added/confirmed:
- `RECIPE_TITLE` must remain reachable from title-like atomizer signals and canonical ownership logic for title-like lines.
- Low-confidence deterministic title hits stay on deterministic path in codex mode (do not escalate-away a good title hit).
- Note-like prose has explicit `RECIPE_NOTES` routing; broad punctuation-only instruction fallback is narrowed.
- Yield boundary regex for prose guard stays `servings` (not bare `serving`) to avoid false yield-tail splits in note prose.
- Quantity-split safeguards in atomizer keep instruction prose/dual-unit rows intact to prevent quantity-fragment ingredient false positives.
- Short quantity-led ingredient detection remains widened with negative guards (time/prose negatives) to recover lost ingredient recall without broad false-positive growth.
- Compact title-like rows may resolve to `HOWTO_SECTION` when neighbor context indicates internal subsection flow.

Benchmark evidence preserved from merged task docs:
- Baseline vs rerun (`2026-03-03_18.31.00` -> `2026-03-03_19.41.28_seaandsmoke-next-buckets`):
  - `strict_accuracy`: `0.5916 -> 0.7731`
  - `macro_f1_excluding_other`: `0.4684 -> 0.5768`
  - `INGREDIENT_LINE -> OTHER`: `68 -> 18`
  - `HOWTO_SECTION -> RECIPE_TITLE`: `36 -> 5`
  - `INSTRUCTION_LINE -> INGREDIENT_LINE`: `26 -> 0`
  - `RECIPE_TITLE` recall: `0.9524 -> 0.9524`

Anti-loop reminders from this task batch:
- If title recall drops to zero again, inspect title heuristics and low-confidence escalation behavior before prompt-only tuning.
- If instruction->ingredient confusion reappears, inspect atomizer quantity splitting order/guards before changing canonical label thresholds.

## 2026-03-04 merged understandings digest (canonical line-role milestone 2 closure)

Merged source note:
- `2026-03-04_00.16.32-feedback-milestone2-gap-closure.md`

Current parsing contracts reinforced:
- `RECIPE_TITLE` detection in canonical line-role now requires contextual support when available; compact title-like rows without supportive next-line structure should not be auto-promoted.
- `YIELD_LINE` detection now requires strict yield-header validation; prose fragments with yield-ish words must demote to structural fallback labels.
- Yield fallback routing remains context-aware (`INSTRUCTION_LINE` / `RECIPE_NOTES` / `OTHER`) with ingredient rescue preserved for obvious ingredient rows.
- Regression anchors for this closure:
  - `test_label_atomic_lines_non_header_yield_phrase_demotes_to_instruction`
  - `test_label_atomic_lines_title_like_line_without_supportive_next_line_is_not_title`

## 2026-03-04 merged understandings digest (canonical line-role codex throughput seams)

Merged source note:
- `docs/understandings/2026-03-04_07.34.26-canonical-line-role-codex-latency-shape-and-speedup-seams.md`

Current parsing contract reinforced:
- Canonical line-role codex escalation is latency-bound by codex round trips, not CPU-bound.
- Throughput gains should focus on bounded batch concurrency, retry/backoff, deterministic merge ordering, and cache reuse keyed by source/settings/candidate fingerprints.
- Prompt/log artifact writing must remain thread-safe under concurrent batch execution.

Anti-loop reminder:
- Low CPU during slow codex labeling is expected for network-latency-bound runs; tune concurrency/caching before local CPU optimizations.

## 2026-03-04 docs/tasks merge digest (canonical line-role codex parallel/cache contract)

Merged source task file:
- `docs/tasks/2026-03-04_07.35.17-canonical-line-role-codex-parallel-cache.md`

Current parsing contracts reinforced:
- Canonical line-role codex escalation supports bounded per-book in-flight concurrency (parser default `4`; ingest prediction-generation defaults now map to `8` for non-split jobs and `4` for split-gated jobs unless env override is set).
- Merge ordering after concurrent batch completion remains deterministic by atomic index/prompt order.
- Retry/backoff handles transient codex failures before fallback classification.
- Cache reuse is keyed conservatively (source hash + settings + candidate fingerprint) and must validate candidate shape/index alignment before reuse.
- Failure mode remains fail-safe: exhausted retries fall back without aborting entire run.

Operational note:
- This optimization primarily targets latency-bound codex round trips; CPU-bound tuning is secondary for this path.

## 2026-03-04 docs/tasks consolidation (canonical line-role codex throughput + shared inflight defaults)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_07.29.55-canonical-line-role-codex-batch-parallel-cache.md`
- `docs/tasks/2026-03-04_08.50.26-shared-line-role-inflight-default-propagation.md`

Current parsing contracts reinforced:
- Codex escalation in `label_atomic_lines(...)` is no longer serial-only; it supports bounded per-book in-flight batches (default `4`) with deterministic output merge.
- Prompt artifact/log writing in codex batch execution must remain thread-safe and deterministic.
- Transient codex failures are retried with bounded backoff before fallback behavior is used.
- Canonical line-role cache reuse is keyed by source hash + run-settings + candidate fingerprint to avoid stale mismatches.
- Shared prediction-generation seam now owns canonical line-role codex inflight defaults:
  - non-split jobs default to `8`,
  - split-gated jobs default to `4`,
  - explicit `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT` remains highest priority.
- Interactive benchmark wrapper-specific inflight env wiring is historical/superseded by shared ingest propagation.

Regression anchors from merged tasks:
- `tests/parsing/test_canonical_line_roles.py`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_artifacts.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py`

## 2026-03-06 merged understandings digest (line-role telemetry second-pass mismatch)

Merged source note:
- `docs/understandings/2026-03-06_01.19.07-line-role-telemetry-second-pass.md`

Current parsing contracts reinforced:
- `joined_line_table.jsonl` should attach line-role prediction metadata conservatively:
  - exact normalized index+text match first,
  - then exact-text sequence alignment,
  - ambiguous duplicate short texts should stay unmatched rather than inherit the wrong prediction metadata.
- `AtomicLineCandidate` and `CanonicalLineRolePrediction` no longer carry `candidate_labels`.
- Historical benchmark artifacts from older runs can still contain candidate-label fields, but current parsing code does not emit or depend on them.

Anti-loop reminder:
- When `joined_line_table.jsonl` and `line_role_predictions.jsonl` disagree, separate exporter matching errors from already-invalid source prediction rows before changing analytics or cutdown tooling.

## 2026-03-13 merged understandings digest (table extraction status + EPUB table recovery path)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-13_22.36.37-data-table-knowledge-status.md`
- `docs/understandings/2026-03-13_22.40.48-thefoodlab-benchmark-table-expectation.md`
- `docs/understandings/2026-03-13_22.44.17-epub-table-flattening-fix-directions.md`
- `docs/understandings/2026-03-13_23.02.22-epub-table-structure-and-reference-gating.md`

Current parsing contracts reinforced:
- The old data-table knowledge plan is effectively shipped in the active codebase:
  - deterministic detection and annotation in `cookimport/parsing/tables.py`,
  - table-aware chunking in `cookimport/parsing/chunks.py`,
  - table artifacts plus pass4 `table_hint` propagation through stage/prediction/LLM flows.
- Historical “Food Lab has no tables” runs under `data/golden/benchmark-vs-golden/` were not proof of a writer failure:
  - those saved manifests had table extraction disabled,
  - and the extracted conversion pages were also badly flattened.
- Best-first EPUB table recovery is upstream structure preservation, not downstream guesswork:
  - preserve row/cell structure at extraction time,
  - prefer `metadata.text_as_html` table rows when available,
  - let `tables.py` trust deterministic row structure instead of reparsing flattened prose.
- Table detection also depends on non-recipe gating, not only row preservation:
  - Food Lab conversion charts had to stop scoring as recipe candidates,
  - a narrow reference-title penalty was part of getting those charts into `nonRecipeBlocks`, where table detection can see them.
- Preserving structure plus the reference-title reject produced the expected improvement in the recorded Food Lab reruns:
  - `data/output/2026-03-13_22.59.32` wrote 3 unrelated tables,
  - `data/output/2026-03-13_23.01.23` wrote 6 tables including the conversion/reference targets.
- Preserved verification evidence from the landing pass:
  - focused pytest slice passed (`57 passed, 7 warnings in 4.02s`),
  - the successful Food Lab rerun is `data/output/2026-03-13_23.01.23`.

Anti-loop reminder:
- If EPUB tables go missing, inspect extractor structure and recipe-likeness gating before adding more salvage heuristics to `tables.py`.

## 2026-03-14 to 2026-03-15 merged understandings digest (canonical line-role heuristic gaps)

Merged source notes:
- `docs/understandings/2026-03-14_18.05.56-canonical-line-role-ingredient-miss-chain.md`
- `docs/understandings/2026-03-15_15.34.54-line-role-other-shortlist-distinction.md`

Current parsing contracts reinforced:
- Canonical line-role labeling is driven by `cookimport/parsing/recipe_block_atomizer.py` plus `cookimport/parsing/canonical_line_roles.py`, not by `ingredients.py::parse_ingredient_line` or `instruction_parser.py::parse_instruction`.
- The old stale pre-LLM recipe-span / per-row shortlist issue is historical:
  - prediction runs now rebuild candidates after the recipe Codex update,
  - the old candidate-label shortlist plumbing is gone,
  - current failures are heuristic misses, not hard LLM allowlist collapse.
- The remaining debugging target is strong heuristic tagging inside `recipe_block_atomizer.py` even when `within_recipe_span=True`. Verified examples that still deserve attention:
  - `1 large jalapeño, seeds and veins removed if desired, thinly sliced`
  - `1-pound loaf day-old country or sourdough bread`
  - `Shaved Carrot Salad with Ginger and Lime`
  - `Toss the croutons with the olive oil to coat them evenly...`
  - `Variations`

Anti-loop reminder:
- When canonical line-role misses obvious recipe lines, debug the atomizer heuristics and span ownership first. Do not assume the main ingredient/instruction parsers are in that path.
