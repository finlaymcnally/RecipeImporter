---
summary: "Code-verified ingestion runtime reference with architecture, behavior, contracts, and known limitations."
read_when:
  - Working on ingestion/importers, extraction, split jobs, or merge behavior
  - Debugging recipe ordering, ID reassignment, raw artifacts, or stage output mismatches
  - Reviewing current ingestion contracts before changing code
---

# Ingestion README

This is the source of truth for current ingestion behavior in `docs/03-ingestion`.

Historical architecture/build/fix-attempt notes are tracked in `docs/03-ingestion/03-ingestion_log.md`.

## Scope

Ingestion is the stage that converts source files into `ConversionResult` payloads that include:
- `recipes` (`RecipeCandidate`)
- `tips` and `tip_candidates`
- `topic_candidates`
- `non_recipe_blocks` (block-first formats)
- `raw_artifacts`
- `report`

Primary runtime entrypoint:
- `cookimport stage ...` in `cookimport/cli.py`

Primary folders:
- Input: `data/input`
- Output: `data/output/<YYYY-MM-DD_HH.MM.SS>/...`

## Where The Code Lives

Core orchestration:
- `cookimport/cli.py` (job planning, worker dispatch, split merge, report write, perf history append)
- `cookimport/cli_worker.py` (per-file and per-split worker execution)

Split planning and ID reassignment:
- `cookimport/staging/pdf_jobs.py`

Importer registry + importers:
- `cookimport/plugins/registry.py`
- `cookimport/plugins/excel.py`
- `cookimport/plugins/epub.py`
- `cookimport/plugins/pdf.py`
- `cookimport/plugins/text.py`
- `cookimport/plugins/paprika.py`
- `cookimport/plugins/recipesage.py`

Shared ingestion parsing primitives:
- `cookimport/parsing/cleaning.py`
- `cookimport/parsing/signals.py`
- `cookimport/parsing/patterns.py`
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/parsing/block_roles.py`

Writers + output structure:
- `cookimport/staging/writer.py`

Models/contracts:
- `cookimport/core/models.py`

OCR:
- `cookimport/ocr/doctr_engine.py`

## End-To-End Runtime Flow

### 1) Stage command setup (`cookimport/cli.py:stage`)

- Sets EPUB extractor/runtime options via env vars from run settings:
  - `C3IMP_EPUB_EXTRACTOR`
  - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
  - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
  - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
- Creates run output directory using timestamp format `%Y-%m-%d_%H.%M.%S`.
- Builds `base_mapping` once and always passes it to workers.
- Normalizes optional LLM recipe settings (`llm_recipe_pipeline`, `codex_farm_*`) into `RunSettings` and threads them into workers/merge.
- Plans jobs with `_plan_jobs(...)`.
- Executes with `ProcessPoolExecutor`; on `PermissionError`, falls back to serial execution.

Important detail:
- Because `base_mapping` is always passed, worker `_run_import(...)` usually does not call `importer.inspect(...)` in non-split conversion path. Inspection is still used during split planning.

### 2) Job planning (`cookimport/cli.py:_plan_jobs`)

Per file:
- PDF split considered when:
  - suffix is `.pdf`
  - `pdf_split_workers > 1`
  - `pdf_pages_per_job > 0`
  - inspect returns page count
- EPUB split considered when:
  - suffix is `.epub`
  - `epub_split_workers > 1`
  - `epub_spine_items_per_job > 0`
  - inspect returns spine count
- Otherwise one non-split `JobSpec`.

Range generation:
- PDF uses `plan_pdf_page_ranges(...)`.
- EPUB uses generic `plan_job_ranges(...)`.
- Split only happens if range count > 1.

### 3) Worker execution (`cookimport/cli_worker.py`)

Non-split file:
- `stage_one_file(...)`
- Runs importer conversion
- Applies optional `--limit` to recipes and tips
- If `llm_recipe_pipeline != off`, runs the 3-pass codex-farm orchestrator before chunking/writes and captures `report.llmCodexFarm`
- Builds chunks from `non_recipe_blocks` or topic fallback
- Writes intermediate/final/tips/topics/chunks/raw/report

Split job:
- `stage_pdf_job(...)` or `stage_epub_job(...)`
- Runs ranged conversion
- Writes only raw artifacts into temporary:
  - `<run_out>/.job_parts/<workbook_slug>/job_<index>/raw/...`
- Clears `result.raw_artifacts` before returning payload
- Returns mergeable job result dict (contains `result` and timing)

### 4) Main-process merge for split files (`cookimport/cli.py:_merge_split_jobs`)

- Waits until all jobs for a source file return.
- If any job failed: merge skipped, error report written, `.job_parts` left for debugging.
- If all succeed:
  - Sorts job payloads by start range (`start_spine` then fallback / `start_page` path)
  - Concatenates recipes/tip candidates/topic candidates/non-recipe blocks
  - Reassigns recipe IDs globally (single sequence) via `reassign_recipe_ids(...)`
  - Rebuilds merged `raw/<importer>/<source_hash>/full_text.json` from split-job `full_text` artifacts and rebases block indices
  - If `llm_recipe_pipeline != off`, runs the same 3-pass codex-farm orchestrator on the merged result before chunking/writes
  - Re-partitions tips from merged `tip_candidates`
  - Rebuilds chunks once from merged non-recipe/topic data
  - Emits phase-by-phase main-process status updates (merge payloads, IDs, chunk build, write phases, raw merge)
  - Writes normal outputs once
  - Moves raw artifacts from `.job_parts/.../raw` into run `raw/...`
  - Removes `.job_parts/<workbook_slug>` on successful merge

Merge performance detail:
- Topic candidate output writing can involve thousands of records; file-hash lookup now caches by source file metadata so merged runs do not re-hash the same source file for every candidate.

Raw collision behavior:
- If target raw filename already exists during merge move, prefixed as `job_<index>_<name>` (and suffixed with counter if still colliding).

## Split Merge Ordering And ID Rules

ID and ordering rules are centralized in `cookimport/staging/pdf_jobs.py`:
- `_recipe_sort_key(...)` ordering precedence:
  1. `location.start_spine` (+ `start_block`)
  2. `location.start_page` (+ `start_block`)
  3. `location.start_block`
  4. fallback index
- `reassign_recipe_ids(...)` rewrites recipe IDs to `...:c0`, `...:c1`, ...
- Also updates:
  - recipe provenance `@id` / `id`
  - `location.chunk_index` (and camel alias)
  - `tip.source_recipe_id`
  - tip provenance `@id` / `id` if they point to remapped recipe IDs

This applies to both split PDF and split EPUB merges.

## Importer Families (Convergence Model)

From code and historical notes:
- Block-first importers: EPUB, PDF
  - Build ordered `Block` streams
  - Segment candidate ranges from block anchors
  - Preserve non-recipe blocks for chunking
- Recipe-record-first importers: Text, Excel
  - Build `RecipeCandidate` records from rows/text sections
- Structured-import-first: Paprika, RecipeSage
  - Map near-structured exports into `RecipeCandidate`

Convergence point:
- All importers return `ConversionResult`.
- Final recipe normalization converges in `write_draft_outputs(...)` where `recipe_candidate_to_draft_v1(...)` runs shared parsing/linking transforms.
- Knowledge chunking happens after conversion from `non_recipe_blocks` (or topic fallback).

## Format Support Matrix (Current)

- Excel (`.xlsx`, `.xlsm`): `cookimport/plugins/excel.py`
- EPUB (`.epub`): `cookimport/plugins/epub.py`
- PDF (`.pdf`): `cookimport/plugins/pdf.py`
- Text (`.txt`, `.md`) and DOCX (`.docx`): `cookimport/plugins/text.py`
- Paprika (`.paprikarecipes`, and directory merge mode): `cookimport/plugins/paprika.py`
- RecipeSage (`.json` with expected structure): `cookimport/plugins/recipesage.py`

Not implemented as dedicated importers today:
- Image files (`.png`, `.jpg`) are not directly detected by current importers.
- Web scraping flow is not part of current ingestion runtime.

## Importer Details

### Excel (`cookimport/plugins/excel.py`)

Inspection detects layouts:
- `wide-table`
- `template`
- `tall`

Behavior highlights:
- Header alias detection for name/ingredients/instructions/etc.
- Merged-cell support through merged-cell maps.
- Mapping stub generation with per-sheet metadata.
- Stable recipe IDs include file hash + sheet slug + row index.
- Raw artifacts include per-row extraction records plus aggregate `full_rows` when available.

### EPUB (`cookimport/plugins/epub.py`)

Extractor modes:
- Default: `unstructured`
- Alternates: `legacy`, `markdown`, `auto`, `markitdown` (legacy compatibility mode)
- Control path:
  - CLI: `--epub-extractor`
  - Env: `C3IMP_EPUB_EXTRACTOR`
  - Unstructured tuning env:
    - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION` (`v1|v2`)
    - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS` (bool)
    - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE` (`none|br_split_v1|semantic_v1`)

Block extraction:
- Reads spine in order (ebooklib primary, zip fallback)
- Supports range slicing via `start_spine`, `end_spine` (end exclusive) for `unstructured`/`legacy`/`markdown`
- `markitdown` converts the whole EPUB to markdown first; it does not support spine-range split jobs
- Adds `spine_index` feature to blocks for deterministic merge ordering
- Skips nav/TOC spine docs when identified via OPF `properties="nav"` or nav/toc signatures in HTML.
- Applies shared post-extraction cleanup for `unstructured`/`legacy`/`markdown` (`cookimport/parsing/epub_postprocess.py`) before segmentation.
- `auto` mode is resolved once per EPUB in stage/benchmark orchestration and persisted as `raw/epub/<source_hash>/epub_extractor_auto.json`.
- Stage/processed report JSON now promotes auto-selection as first-class fields (not just raw artifact):
  - `epubAutoSelection`: full auto race payload (candidates, sample indices, selected backend/reason).
  - `epubAutoSelectedScore`: average score for the selected candidate backend.
  - non-auto runs omit these fields.

MarkItDown-specific behavior:
- Uses `markitdown` with plugins disabled (`MarkItDown(enable_plugins=False)`)
- Converts markdown to blocks with `md_line_start` / `md_line_end` provenance and `extraction_backend=markitdown`
- Emits optional raw artifact `markitdown_markdown.md`
- Whole-book conversion only: spine-range split jobs are intentionally disabled for this extractor in both stage and benchmark prediction planners.

Markdown-specific behavior:
- Converts each spine HTML document to markdown (Pandoc when available, else `markdownify`) and parses deterministic markdown blocks.
- Emits diagnostics artifact `markdown_blocks.jsonl` with line-level provenance (`markdown_line_start`/`markdown_line_end`) and stable keys.
- Includes converter metadata in extractor diagnostics (`pandoc_used`, converter name/error, markdownify version).

Candidate segmentation:
- Yield-driven anchors and title backtracking heuristics
- Produces candidate provenance with `start_spine` / `end_spine` when available

Unstructured-specific behavior:
- Normalizes spine XHTML via `normalize_epub_html_for_unstructured(...)` before partitioning.
- Uses `partition_html_to_blocks(...)` adapter
- Normalizer removes obvious pagebreak/nav/script/style noise tags before partitioning.
- Shared signal enrichment runs after extractor-agnostic EPUB postprocessing.
- Assigns deterministic `block_role` via `assign_block_roles(...)`
- Emits optional raw artifact `unstructured_elements.jsonl` (diagnostics rows)
- Emits spine-debug XHTML artifacts:
  - `raw_spine_xhtml_0000.xhtml` (per spine, raw source XHTML)
  - `norm_spine_xhtml_0000.xhtml` (per spine, normalized XHTML passed to Unstructured)

#### Extractor Architecture Clarification (preserved)

Current behavior is one mutually exclusive extractor choice per run:

- `EPUB -> [unstructured | legacy | markdown | markitdown] -> block stream -> shared segmentation/extraction`

This is intentionally not:

- `EPUB -> optional markitdown pre-pass -> (legacy|unstructured)`

`markitdown` is its own extractor path, not a preprocessing toggle.

#### Extractor-Specific Block Semantics (merged deep reference)

`unstructured`:
- Calls `partition_html_to_blocks(...)` through `cookimport/parsing/unstructured_adapter.py`.
- Emits one `Block` per normalized unstructured element text.
- Carries `unstructured_*` traceability fields (`category`, `element_index`, stable key, parent linkage, etc.).
- Maps heading/list semantics from unstructured categories (`Title` and `ListItem` handling).
- Supports spine-range split jobs.

`legacy`:
- Parses spine XHTML via BeautifulSoup and scans block-level tags (`p`, `div`, `h1..h6`, `li`, `td`, `th`, `blockquote`).
- Skips container tags with nested block tags to avoid parent+child duplicate emission.
- Emits one block per leaf block-level element with `extraction_backend=legacy`.
- Supports spine-range split jobs.

`markdown`:
- Converts per-spine XHTML/HTML to markdown using Pandoc when present, with deterministic fallback to `markdownify`.
- Parses markdown lines into heading/list/paragraph blocks with markdown line provenance.
- Supports spine-range split jobs.

`markitdown`:
- Converts full EPUB to markdown first, then parses markdown lines into blocks.
- Carries markdown line provenance (`md_line_start`, `md_line_end`) plus `source_location_id`.
- Emits `markitdown_markdown.md` raw artifact.
- Does not support spine-range split jobs.

Shared join point after any extractor:
- `assign_block_roles(blocks)` and shared candidate detection/extraction (`_detect_candidates`, `_extract_fields`) are reused.
- Extractor differences mainly affect block boundaries/metadata, not a separate downstream recipe engine.

Boundary note for `markitdown`:
- Recipe boundaries still come from standard EPUB candidate logic (`_detect_candidates`, `_backtrack_for_title`, `_find_recipe_end`).
- `markitdown` changes boundaries indirectly by changing block shape; it does not run a custom boundary detector.

Quick selection guidance:
- Start with `unstructured` for general ingestion and richer traceability.
- Use `legacy` when simpler HTML-tag parsing behavior is preferred.
- Use `markdown` when per-spine HTML conversion plus deterministic markdown parsing yields cleaner block boundaries.
- Use `markitdown` when source XHTML is noisy and markdown normalization yields better block boundaries.
- Use `auto` when you want deterministic scoring over sampled spines and a recorded backend-selection rationale.

### PDF (`cookimport/plugins/pdf.py`)

Range support:
- `start_page`, `end_page` supported in importer convert path (end exclusive)

Extraction path:
- PyMuPDF text extraction with layout features and column reconstruction
- OCR fallback via docTR when PDF appears scanned and OCR available
- OCR run respects page range and returns absolute page numbering in blocks

Candidate and provenance behavior:
- Candidate IDs initially `urn:recipeimport:pdf:<hash>:c<i>` before global merge rewrite (split case)
- Provenance location includes `start_page`, `end_page`, `start_block`, `end_block`
- Raw artifacts include:
  - `full_text` extracted block dump
  - per-candidate block dumps (`locationId` like `c<i>`)

Column ordering details:
- Column boundaries inferred from x-gap threshold (`page_width * 0.12`)
- Full-width blocks forced into column 0
- Ordering key: `(page_num, column_id, y0, x0)`

### Text + DOCX (`cookimport/plugins/text.py`)

Supported formats:
- `.txt`, `.md`, `.docx`

Behavior highlights:
- Markdown/YAML frontmatter handling
- Multi-recipe splitting by headings, yield markers, numbered titles, delimiter lines
- Section extraction (`Ingredients`, `Instructions`, `Notes`) from text blobs
- DOCX table parsing with header alias detection (header row inferred in first rows)

### Paprika (`cookimport/plugins/paprika.py`)

Behavior highlights:
- Reads `.paprikarecipes` zip entries (gzip-compressed JSON)
- Directory mode can merge zip export + html export views
- Merge prefers zip text content; can adopt selected HTML-derived structured fields

### RecipeSage (`cookimport/plugins/recipesage.py`)

Behavior highlights:
- Detects expected export shape (`recipes` + `@type` hints)
- Validates each recipe through `RecipeCandidate`
- Adds provenance and stable IDs where missing
- Stores full export as raw artifact (`full_export`)

## Shared Parsing Components Used During Ingestion

- `cleaning.normalize_text(...)` applies normalization and cleanup.
- `cleaning.normalize_epub_text(...)` adds EPUB-targeted cleanup (soft hyphens, zero-width chars, unicode fractions/punctuation).
- `signals.enrich_block(...)` adds block-level features:
  - heading flags
  - section markers
  - yield/time detection
  - ingredient/instruction likelihood
- `patterns.py` holds shared regexes for quantities/units/time/yield.
- EPUB extraction health metrics are computed in `cookimport/parsing/epub_health.py` and written as raw artifact `epub_extraction_health.json`; warning keys are appended to report warnings when thresholds trip.

Unstructured adapter traceability fields per block:
- `unstructured_element_id`
- `unstructured_element_index`
- `unstructured_stable_key`
- `unstructured_category`
- `unstructured_category_depth`
- `unstructured_parent_id`
- `source_location_id`

Block role labels (`block_roles.py`):
- `recipe_title`
- `ingredient_line`
- `instruction_line`
- `tip_like`
- `narrative`
- `metadata`
- `section_heading`
- `other`

## Output Structure And Contracts

For a run at `data/output/<timestamp>/`:
- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `tips/<workbook_slug>/...`
- `chunks/<workbook_slug>/...` (when generated)
- `raw/<importer>/<source_hash>/<location_id>.<ext>`
- `<workbook_slug>.excel_import_report.json`

Reporting/perf:
- Report has `runTimestamp`, `importerName`, timing, warnings/errors, sample stats.
- Report now includes `runConfig` for run-level knobs (including `epub_extractor`, unstructured parser/preprocess flags, worker counts, OCR settings, split sizes, and optional mapping/overrides paths).
- Report can include `outputStats` (counts/bytes/largest files by category).
- Stage appends per-file summary rows into:
  - `data/output/.history/performance_history.csv`

Provenance and IDs:
- Provenance stores original source filename (with extension).
- Writer fills missing IDs deterministically from provenance/hash context.
- Split-merge rewrites IDs to global sequence for stable merged ordering.

## Config Surfaces Relevant To Ingestion

Stage CLI options (key ones):
- `--workers`
- `--pdf-split-workers`
- `--epub-split-workers`
- `--pdf-pages-per-job`
- `--epub-spine-items-per-job`
- `--ocr-device`
- `--ocr-batch-size`
- `--mapping`
- `--overrides`
- `--epub-extractor`
- `--epub-unstructured-html-parser-version`
- `--epub-unstructured-skip-headers-footers`
- `--epub-unstructured-preprocess-mode`

Overrides and mapping:
- Mapping model supports `parsingOverrides` alias (`parsing_overrides` field in code).
- Override file resolution can use sidecars like `*.overrides.yaml` / `*.overrides.json`.

## What We Know Is Bad / Risky

1. EPUB boundary splits remain imperfect.
- Split EPUB jobs do not currently carry overlap context across spine boundaries.
- Recipe segmentation can break when a recipe crosses split edge.

2. PDF ordering is only heuristic.
- Column detection is gap-based and brittle on unusual layouts.
- If boundaries are wrong, block order and recipe segmentation degrade.

3. OCR ambiguity remains a source of false positives.
- OCR confusions can create ingredient-like noise lines.

4. Mapping/inspect behavior is unintuitive.
- Stage always builds a `MappingConfig` and passes it to workers.
- This means non-split conversion path often skips importer `inspect(...)` inside worker import flow.
- Planning still calls inspect for range counts.

5. `.job_parts` semantics are easy to misread.
- Successful split merge removes `.job_parts/<workbook_slug>`.
- Leftover `.job_parts` usually indicates merge interruption/failure or abandoned run.

## Test Coverage Pointers

Files most relevant to ingestion behavior:
- `tests/test_pdf_job_merge.py`
- `tests/test_epub_job_merge.py`
- `tests/test_pdf_importer.py`
- `tests/test_epub_importer.py`
- `tests/test_text_importer.py`
- `tests/test_excel_importer.py`
- `tests/test_paprika_importer.py`
- `tests/test_paprika_merge.py`
- `tests/test_recipesage_importer.py`
- `tests/test_unstructured_adapter.py` (29 tests)

When changing split/merge logic, update at least the split merge tests plus importer-specific tests.

## Fast Debug Checklist

1. Confirm importer selection:
- `registry.best_importer_for_path(path)` resolves expected importer.

2. Confirm split planning actually happened:
- Check page/spine count from inspect and resulting range count > 1.

3. Confirm merge executed:
- Watch for “Merging N jobs for <file>...” in stage output.

4. Inspect temporary artifacts:
- If merge failed, inspect `.job_parts/<workbook_slug>/job_<index>/raw/...`.

5. Validate ID rewrite:
- Ensure merged output recipe IDs are globally ordered and tip `source_recipe_id` points at rewritten IDs.

6. Validate ordering metadata:
- EPUB: check `start_spine` / block order.
- PDF: check `start_page` / block order and column IDs.

7. Validate chunk source:
- `non_recipe_blocks` preferred; topic fallback if non-recipe absent.

## Practical Change Guidance

If working in this area, keep these invariants:
- Keep importer-specific extraction logic flexible.
- Keep `ConversionResult` contract stable.
- Preserve deterministic ordering keys used for merge and ID assignment.
- Preserve raw artifact traceability and avoid silent data loss during merge moves.
- Treat `.job_parts` cleanup behavior as diagnostic signal, not noise.

## EPUB Extractor Wiring Addendum (Merged 2026-02-19/2026-02-20 understandings)

### Shared postprocess and health join points

- `_extract_docpack(...)` in `cookimport/plugins/epub.py` is the extractor join point.
- `legacy`, `unstructured`, and `markdown` backends run shared cleanup (`postprocess_epub_blocks(...)`) before signal enrichment.
- `markitdown` intentionally skips shared HTML postprocess and only gets normal signal enrichment.
- Conversion-level health is attached in `EpubImporter.convert(...)`:
  - writes raw artifact `epub_extraction_health.json`,
  - appends stable warning keys into `ConversionReport.warnings`.

### Spine metadata contract

- Spine metadata contract uses typed records (`EpubSpineItem(path, media_type, item_id, properties)`) rather than tuple slots.
- This keeps nav/TOC skip behavior aligned between ebooklib and zip-fallback spine readers.

### Auto extractor resolution + env scope

- `auto` should resolve once in parent orchestration (`stage` and benchmark prediction generation), then workers receive the concrete backend (`legacy|unstructured|markdown`).
- Stage path persists per-file auto rationale to `raw/epub/<source_hash>/epub_extractor_auto.json` and passes effective extractor explicitly to worker calls.
- Prediction-generation helper flows should apply `C3IMP_EPUB_*` overrides in scoped contexts and restore previous env values after conversion to avoid run/test leakage.

### Probe-path initialization rule (critical)

- `select_epub_extractor_auto(...)` probes via direct calls to `EpubImporter._extract_docpack(...)`; this path does not run `convert(...)`.
- Any runtime state consumed by `_extract_docpack(...)` must be initialized in `EpubImporter.__init__` (or safely defaulted), not only inside `convert(...)`.
- Known regression: missing `self._overrides` caused real stage `--epub-extractor auto` failures (`'EpubImporter' object has no attribute '_overrides'`).
- Regression anchor:
  - `tests/test_epub_auto_select.py::test_select_epub_extractor_auto_real_importer_supports_direct_probe`

## Merged Task Specs (2026-02-22 spinner visibility)

### 2026-02-22_14.08.34 elapsed ticker + post-candidate progress phases

Long-running conversion phases after candidate extraction can look frozen if callback text never changes.
Current contract from the spinner visibility pass:

- Shared callback-driven status wrappers append elapsed-time suffixes (for example `(17s)`) when a phase message stays unchanged past threshold.
- The elapsed ticker contract is shared across CLI wrappers used by Label Studio import/decorate and benchmark flows.
- Importer callbacks now continue after `candidate X/Y` with explicit post-candidate phase updates in EPUB/PDF flows (for example knowledge-block analysis and finalization steps).

Operational boundary:

- These are visibility-only progress message changes; extraction semantics and output artifact contracts are unchanged.
