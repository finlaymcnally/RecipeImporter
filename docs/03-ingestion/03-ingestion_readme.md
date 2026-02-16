---
summary: "Comprehensive, code-verified ingestion reference with architecture, behavior, historical attempts, and known limitations."
read_when:
  - Working on ingestion/importers, extraction, split jobs, or merge behavior
  - Debugging recipe ordering, ID reassignment, raw artifacts, or stage output mismatches
  - Reconciling historical ingestion decisions to avoid retrying already-failed approaches
---

# Ingestion README

This is the consolidated source of truth for `docs/03-ingestion` as of 2026-02-16.

It combines and supersedes:
- `docs/03-ingestion/2026-02-12_10.17.19-import-pipeline-convergence.md`
- `docs/03-ingestion/2026-02-12-unstructured-epub-adapter.md`
- `docs/03-ingestion/03-ingestion_README.md`

It is intentionally detailed to preserve prior exploration context and prevent repeated dead-end loops.

## Document Chronology (Source Merge Order)

Order below is based on source document filenames/timestamps and last consolidation date:
1. `2026-02-12_10.17.19-import-pipeline-convergence.md`
2. `2026-02-12-unstructured-epub-adapter.md`
3. `03-ingestion_README.md` (later consolidation pass, modified on 2026-02-15)
4. This file `03-ingestion_readme.md` (code-verified consolidation on 2026-02-16)

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

- Sets EPUB extractor mode via `C3IMP_EPUB_EXTRACTOR` from `--epub-extractor`.
- Creates run output directory using timestamp format `%Y-%m-%d_%H.%M.%S`.
- Builds `base_mapping` once and always passes it to workers.
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
- Alternates: `legacy`, `markitdown`
- Control path:
  - CLI: `--epub-extractor`
  - Env: `C3IMP_EPUB_EXTRACTOR`

Block extraction:
- Reads spine in order (ebooklib primary, zip fallback)
- Supports range slicing via `start_spine`, `end_spine` (end exclusive) for `unstructured`/`legacy`
- `markitdown` converts the whole EPUB to markdown first; it does not support spine-range split jobs
- Adds `spine_index` feature to blocks for deterministic merge ordering

MarkItDown-specific behavior:
- Uses `markitdown` with plugins disabled (`MarkItDown(enable_plugins=False)`)
- Converts markdown to blocks with `md_line_start` / `md_line_end` provenance and `extraction_backend=markitdown`
- Emits optional raw artifact `markitdown_markdown.md`

Candidate segmentation:
- Yield-driven anchors and title backtracking heuristics
- Produces candidate provenance with `start_spine` / `end_spine` when available

Unstructured-specific behavior:
- Uses `partition_html_to_blocks(...)` adapter
- Enriches blocks with shared `signals.enrich_block(...)`
- Assigns deterministic `block_role` via `assign_block_roles(...)`
- Emits optional raw artifact `unstructured_elements.jsonl` (diagnostics rows)

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
- `signals.enrich_block(...)` adds block-level features:
  - heading flags
  - section markers
  - yield/time detection
  - ingredient/instruction likelihood
- `patterns.py` holds shared regexes for quantities/units/time/yield.

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
- Report now includes `runConfig` for the run-level knobs (for example `epub_extractor`, worker counts, OCR settings, split sizes, and optional mapping/overrides paths).
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

## Historical Attempts (Preserve To Avoid Rework Loops)

### 2026-02-12 10:17:19: Pipeline convergence note

Established and still true:
- Importers differ early (block-first vs record-first vs structured-first).
- They converge at `ConversionResult` and downstream writer pipeline.
- Chunking is fed from non-recipe/topic paths post-convert.

Do not re-litigate unless code changed:
- “Should we force all importers into same early extraction model?”
- Existing design intentionally allows importer-specific extraction while standardizing handoff contract.

### 2026-02-12: Unstructured EPUB adapter note

Established and still true:
- Unstructured is default EPUB extractor.
- Adapter emits traceability metadata and diagnostics JSONL artifact.
- Deterministic role assignment exists and is covered by unit tests.

Do not re-litigate unless objective evidence appears:
- “Need to revert default to legacy parser globally.”
- Current default was chosen to retain richer semantic signals and traceability.

### 2026-02-15: Prior ingestion README consolidation

Preserved decisions:
- Split-job merge architecture for PDF + EPUB.
- Main-process merge + ID rewrite strategy.
- Serial fallback for environments blocking multiprocessing.
- Raw artifact merge from temporary `.job_parts` workspace.

Known incomplete idea intentionally not implemented:
- Earlier EPUB split plan considered overlap + owned-range filtering.
- Implemented version uses straightforward spine ranges without overlap.
- If boundary errors become frequent, revisit overlap as a targeted fix, not a broad redesign.

### 2026-02-15_22.06.34: Split-merge and ID rewrite discovery map

Merged source:
- `docs/understandings/2026-02-15_22.06.34-ingestion-split-merge-and-id-rewrite-map.md`

Preserved operational details:
- Split workers write raw artifacts under `.job_parts/<workbook>/job_<index>/raw/...` and return merge payloads.
- Main-process merge sorts by source range, rewrites recipe IDs globally (`c0..cN`), then rebuilds tips/chunks once.
- Raw merge collisions are renamed with `job_<index>_...` prefixes so artifacts are not dropped.
- `.job_parts` is expected to be removed on successful merge; leftover `.job_parts` is usually merge-failure/interruption evidence and should be treated as debug signal.
- Stage builds and passes `base_mapping` for workers; worker `inspect()` is mainly a split-planning concern, not the normal non-split conversion initialization path.

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
- `tests/test_unstructured_adapter.py` (26 tests)

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
