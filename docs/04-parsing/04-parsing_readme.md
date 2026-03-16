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

Additional parsing-package helpers used by importer-specific flows:

- `cookimport/parsing/html_schema_extract.py`
- `cookimport/parsing/html_text_extract.py`
- `cookimport/parsing/schemaorg_ingest.py`
- `cookimport/parsing/text_section_extract.py`

Unstructured adapter note:
- `unstructured_adapter.py` now performs deterministic multiline splitting for recipe-like `Title`/`NarrativeText`/`UncategorizedText`/`Text` blocks (in addition to `ListItem` newline splits), preserving provenance with `unstructured_stable_key` suffixes (`.s0`, `.s1`, ...) and `unstructured_split_reason`.

Parsing-adjacent module (not in the default stage recipe-path runtime):

- `cookimport/parsing/classifier.py` (heuristic line classifier retained for focused classifier experiments)

Major call sites:

- Recipe draft conversion: `cookimport/staging/draft_v1.py`
- EPUB segmentation + standalone tip/topic extraction: `cookimport/plugins/epub.py`
- PDF importer tip/topic extraction + block signal enrichment: `cookimport/plugins/pdf.py`
- Text importer tip/topic extraction + block signal enrichment: `cookimport/plugins/text.py`
- Excel importer recipe-level tip extraction: `cookimport/plugins/excel.py`
- Web/schema.org extraction helpers: `cookimport/plugins/webschema.py`
- Stage/bench orchestration of tip/chunk/table passes: `cookimport/cli.py`, `cookimport/cli_worker.py`
- Label Studio ingest chunk/table/tip orchestration: `cookimport/labelstudio/ingest.py`
- EPUB debug CLI diagnostics path: `cookimport/epubdebug/cli.py`
- JSON-LD section shaping (`HowToSection`, ingredient section metadata): `cookimport/staging/jsonld.py`
- Candidate confidence scoring using parsing signals: `cookimport/core/scoring.py`
- Knowledge-job bundle construction from parser chunks: `cookimport/llm/codex_farm_knowledge_jobs.py`
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
   - Knowledge job builders also consume parser chunks (`cookimport/llm/codex_farm_knowledge_jobs.py`)
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
  - `ingredient_pre_normalize_mode`: `aggressive_v1`
  - `ingredient_packaging_mode`: `off | regex_v1`
  - `ingredient_unit_canonicalizer`: `pint`
  - `ingredient_missing_unit_policy`: `null | each | medium`
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
- `temperature`, `temperature_unit`, `temperature_text`: convenience mirror fields for the first matched temperature expression

### Time behavior

- Backends:
  - `regex_v1` (default)
  - `quantulum3_v1` (optional dependency)
  - `hybrid_regex_quantulum3_v1` (regex fallback first)
- Handles seconds/minutes/hours/days and abbreviations (`mins`, `hrs`, `secs`).
- Ranges use midpoint (`20 to 30 minutes` => 25 minutes).
- Strategy notes:
  - `sum_all_v1` keeps the prior full-step aggregation behavior.
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
- Returns all matches in `temperature_items`; the convenience mirror fields keep the first match for single-value consumers.
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
- Shared detection currently uses the `shared_v1` detector path.
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
- Label-first Stage 2 reuse still needs provisional `within_recipe_span` hints before regrouped spans exist. If `_atomize_archive_blocks(...)` defaults every block to outside-span, canonical safety rules will over-downgrade real `RECIPE_TITLE`, `HOWTO_SECTION`, `INSTRUCTION_LINE`, and `RECIPE_VARIANT` rows to `OTHER`.

### Tests to read

- `tests/parsing/test_recipe_block_atomizer.py`

## Canonical Line Roles (`cookimport/parsing/canonical_line_roles.py`)

### What it does

- Assigns one canonical benchmark label per `AtomicLineCandidate` using deterministic rules first.
- Supports optional Codex fallback for unresolved or explicitly escalated candidates when `line_role_pipeline=codex-line-role-v1`.
- Emits `CanonicalLineRolePrediction` rows with `decided_by` provenance (`rule`, `codex`, `fallback`), reason tags, and explicit `escalation_reasons`.
- Prediction rows also carry `within_recipe_span` context (from atomized candidates), which benchmark Milestone-5 diagnostics reuse for slice metrics and knowledge-budget reporting.

### Current safeguards

- Rule-first path handles low-ambiguity cases (`NOTE`, yield, ingredient-like, method headers, variants, and instruction lines).
- Compact all-caps title-like rows are disambiguated to `HOWTO_SECTION` when neighboring lines indicate an internal component/subsection flow and the next line is not a yield boundary.
- `YIELD_LINE` now has strict header validation (`MAKES`/`SERVES`/`YIELDS` prefix plus short header shape and quantity/count hint); non-header yield-like prose is sanitized to structural fallback (`INSTRUCTION_LINE` or `OTHER`) instead of forcing yield.
- `TIME_LINE` is only used for primary time metadata; non-primary `TIME_LINE` predictions are sanitized to `INSTRUCTION_LINE` (or `OTHER` outside recipe spans).
- Inside recipe spans, `KNOWLEDGE` is restricted and sanitized out unless prose + neighbor context supports it.
- Outside recipe spans, prose now defaults to `OTHER`; `KNOWLEDGE` is used only when explicit knowledge cues are present.
- When knowledge extraction is enabled, its block-classification artifact can further arbitrate outside-span `KNOWLEDGE` versus `OTHER` after line-role projection; this seam is binary only and does not override recipe-structural labels.
- Outside recipe spans, `HOWTO_SECTION` is hard-denied in the v1 safety policy.
- Outside recipe spans, `RECIPE_TITLE`/`RECIPE_VARIANT` now require compact-heading shape plus neighboring (±2 lines) structural evidence; otherwise they are downgraded to `OTHER`/`KNOWLEDGE`.
- Outside recipe spans, `INSTRUCTION_LINE`/`INGREDIENT_LINE` now require local recipe evidence (±2 lines) and are downgraded when evidence is missing.
- `RECIPE_TITLE` now requires supportive next-line context when available (yield boundary, ingredient/instruction flow, or recipe-structure cues) to reduce title-vs-howto/title-vs-narrative confusion.
- Short ingredient fragments (for example split quantity/name rows) now get neighbor-aware rescue to `INGREDIENT_LINE` when adjacent ingredient-dominant context supports it.
- Codex fallback uses strict JSON validation with the full global line-role label set available on every row; parse failures now attempt deterministic recovery and otherwise force `OTHER`, with parse-error artifacts written under `line-role-pipeline/prompts/parse_errors.json`.
- Title-like recovery no longer depends on per-row Codex allowlist expansion; atomizer/deterministic heuristics still influence non-LLM ownership logic.
- Strong deterministic `RECIPE_TITLE` outcomes are held on the rule path without any score-based fallback pressure.
- Outside-recipe-span score-based escalation is gone; codex escalation now remains inside-span-first and reason-driven.
- This seam is now reason-only. Current runtime artifacts expose label-driven grouping plus explicit `escalation_reasons` only; scalar `confidence`, `trust_score`, and `escalation_score` fields are no longer part of the contract.
- Reviewer/export surfaces should mirror that same contract. If a downstream bundle or debug packet still wants scalar uncertainty fields, that downstream surface is stale rather than the parsing contract being incomplete.
- Codex mode now applies an explicit line-role guardrail mode after sanitization: `off`, `preview`, or `enforce`.
- `preview` computes the same downgrade decisions as enforce mode but leaves accepted predictions unchanged; `enforce` applies partial downgrades or full-source fallback to deterministic baseline labels.
- Guardrail diagnostics are written under `line-role-pipeline/`:
  - `guardrail_report.json`
  - `guardrail_changed_rows.jsonl`
- Reviewer sidecars remain available when guardrail diagnostics exist:
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
- `cookimport/llm/codex_exec.py` (fail-closed retired transport only; active runtime line-role transport is CodexFarm through `canonical_line_roles.py`)
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

`ChunkLane.NARRATIVE` is an older lane value; reporting treats it as noise.

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
