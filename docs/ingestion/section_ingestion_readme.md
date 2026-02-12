---
summary: "Ingestion pipeline reference: importers, job splitting, merge behavior, and known limitations."
read_when:
  - Working on ingestion/importers or job splitting
  - Debugging extraction or merge issues
  - Needing a single-source overview of the ingestion section
---

# Ingestion Section Reference

This document consolidates all prior `docs/ingestion/*` notes and ExecPlans into one reference. It is meant to be the single source of truth for how ingestion works, where the code lives, why key choices were made, and what is known to be imperfect.

## Scope and Inputs/Outputs

Ingestion is the stage that reads source files and converts them into `RecipeCandidate` objects, along with tips, topics, raw artifacts, and reports.

- Input folder: `data/input`
- Output folder: `data/output` (timestamped run root)
- Outputs produced per file: `intermediate drafts/`, `final drafts/`, `tips/`, `topics/`, `chunks/`, `raw/`, and a report JSON.

## Code Map (Where Things Live)

- CLI entrypoint and orchestration: `cookimport/cli.py`
- Worker execution: `cookimport/cli_worker.py`
- Importer registry: `cookimport/plugins/registry.py`
- Importer implementations:
- `cookimport/plugins/excel.py`
- `cookimport/plugins/epub.py`
- `cookimport/plugins/pdf.py`
- `cookimport/plugins/text.py`
- `cookimport/plugins/paprika.py`
- `cookimport/plugins/recipesage.py`
- OCR implementation: `cookimport/ocr/doctr_engine.py`
- Job planning and ID reassignment helpers (split jobs): `cookimport/staging/pdf_jobs.py`
- Output writers: `cookimport/staging/writer.py`
- Core models: `cookimport/core/models.py`
- Shared parsing utilities: `cookimport/parsing/`

## Stage/Worker Flow

The `stage` CLI prepares jobs and dispatches them to workers, then merges split results in the main process.

- `cookimport/cli.py` plans jobs (one per file, or multiple page-range jobs for large PDFs), spins a `ProcessPoolExecutor`, and calls either `cookimport/cli_worker.py:stage_one_file` (non-split) or `cookimport/cli_worker.py:stage_pdf_job` (split).
- Progress updates flow through a `multiprocessing.Manager().Queue()` into the live dashboard, with range labels for split jobs.
- `stage_one_file` resolves the importer, optionally runs `importer.inspect`, runs `importer.convert`, applies limits, builds chunks, enriches the report, and writes outputs via `cookimport/staging/writer.py`.
- `stage_pdf_job` runs a page-range conversion, writes raw artifacts into `.job_parts/<workbook_slug>/job_<index>/raw/`, and returns a mergeable `ConversionResult` payload to the main process.
- `cookimport/plugins/pdf.py:PdfImporter.convert` accepts a page range and initially assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}` before merge rewrites them to a global sequence.
- `cookimport/ocr/doctr_engine.py:ocr_pdf` accepts `start_page` and `end_page` (exclusive) and returns absolute page numbers (1-based).

## Supported Formats and Behaviors

| Format | Importer | Status | Notes |
| --- | --- | --- | --- |
| Excel (.xlsx) | `excel.py` | Complete | Wide/Tall/Template layout detection |
| EPUB (.epub) | `epub.py` | Complete | Spine extraction, block-based segmentation |
| PDF (.pdf) | `pdf.py` | Complete | Column clustering, OCR fallback |
| Text (.txt, .md) | `text.py` | Complete | Multi-recipe splitting, YAML frontmatter |
| Word (.docx) | `text.py` | Complete | Table extraction, paragraph parsing |
| Paprika (.paprikarecipes) | `paprika.py` | Complete | ZIP of gzip JSON |
| RecipeSage (.json) | `recipesage.py` | Complete | Schema validation + normalization |
| Images (.png, .jpg) | `pdf.py` | Planned | Will reuse PDF OCR pipeline |
| Web scraping | - | Deferred | Not currently prioritized |

## Importer Details (What and Why)

### Excel (`cookimport/plugins/excel.py`)

Layouts detected:
- Wide: one recipe per row with columns for name/ingredients/instructions.
- Tall: one recipe spans multiple rows (key-value pairs).
- Template: fixed labeled cells (for example `Recipe Name:` in `A1`, value in `B1`).

Key behaviors:
- Header row detection via column name matching.
- Combined column support (for example a single `Recipe` column containing both name and ingredients).
- Merged cell handling.
- Mapping stub generation for user customization.

### EPUB (`cookimport/plugins/epub.py`)

Extraction flow:
1. Parse EPUB spine (ordered reading documents).
2. Convert HTML to linear `Block` objects (paragraphs, headings, list items).
3. Enrich blocks with signals (ingredient, instruction, yield, headings).
4. Segment blocks into recipe candidates via anchors.

Segmentation heuristics:
- Yield anchoring: `Serves 4`, `Makes 12` anchor recipe starts.
- Ingredient header detection: `Ingredients:` marks section boundaries.
- Title backtracking: look backwards from anchors to find titles.

Observed cookbook-specific behaviors:
- Section boundaries vary by cookbook style.
- ATK-style cookbooks rely heavily on yield-based segmentation.
- Variation/Variant sections should stay with the parent recipe.

Provenance and ordering:
- Blocks carry `spine_index` so merged job results can be ordered globally.
- Provenance locations include `start_spine`/`end_spine` for ordering and ID reassignment.

### PDF (`cookimport/plugins/pdf.py`)

Extraction flow:
1. Extract text with PyMuPDF (line-level with coordinates).
2. Cluster lines into columns based on x-position gaps.
3. Sort within columns top-to-bottom, then run the same block pipeline as EPUB.

Column detection:
- Gap threshold around 50+ points indicates a column break.
- Falls back to single-column if no clear gaps.

OCR fallback:
- Uses docTR (CRNN + ResNet) for scanned pages.
- Triggered when text extraction yields minimal content.
- Returns lines with bounding boxes and confidence scores.

Provenance and ordering:
- Provenance locations include `start_page` to preserve global ordering during merges.

### Text and Word (`cookimport/plugins/text.py`)

Supported inputs:
- Plain text (.txt)
- Markdown (.md) with YAML frontmatter
- Word documents (.docx), including tables

Multi-recipe splitting:
- Headerless files split on `Serves` / `Yield` / `Makes` lines.
- Headered files split on `#` or `##` headings.

DOCX tables:
- Header row maps to recipe fields.
- Each row becomes a recipe.
- Supports `Ingredients` and `Instructions` columns.

### Paprika (`cookimport/plugins/paprika.py`)

Format:
- `.paprikarecipes` is a ZIP containing gzip-compressed JSON files.

Extraction:
- Iterate ZIP entries, gunzip, parse JSON, normalize to `RecipeCandidate`.

### RecipeSage (`cookimport/plugins/recipesage.py`)

Format:
- JSON export where recipes already follow schema.org Recipe JSON closely.

Behavior:
- Mostly pass-through with schema validation, provenance injection, and normalization.

## Shared Text Processing (`cookimport/parsing/`)

Cleaning (`cleaning.py`):
- Unicode NFKC normalization.
- Mojibake repair (common encoding issues).
- Whitespace standardization.
- Hyphenation repair (split words across lines).

Signals (`signals.py`): block-level feature detection.
- Heading signals: `is_heading`, `heading_level`.
- Section markers: `is_ingredient_header`, `is_instruction_header`.
- Metadata: `is_yield`, `is_time`.
- Ingredient cues: `starts_with_quantity`, `has_unit`.
- Content classification: `is_instruction_likely`, `is_ingredient_likely`.

Patterns (`patterns.py`): shared regexes for quantities, units, time phrases, and yield phrases.

## Additional Ingestion/Output Conventions

- Core shared models are in `cookimport/core/models.py`; staging JSON-LD and writer helpers are under `cookimport/staging/`.
- Stage run folders use workbook stems (no extension) for:
- `intermediate drafts/<workbook>/...`
- `final drafts/<workbook>/...`
- report name `<workbook_slug>.excel_import_report.json`
- Provenance still records the original source filename (including extension).
- Recipe outputs are flattened per source file (no sheet subfolders):
- `intermediate drafts/<workbook>/r{index}.jsonld`
- `final drafts/<workbook>/r{index}.json`
- Stable IDs are provenance-derived:
- Excel paths use `row_index`/`rowIndex`
- non-tabular paths use `location.chunk_index`
- Stage conversion reports are written at run root (not `reports/`) and include:
- `runTimestamp` (local ISO-8601 run start time)
- `outputStats` (counts/bytes and largest-output diagnostics)
- Performance summaries append one row per imported file to `data/output/.history/performance_history.csv`.
- Raw artifacts are preserved at `<output_root>/<timestamp>/raw/<importer>/<source_hash>/<location_id>.<ext>`.
- For split PDF/EPUB jobs, workers write temporary raw artifacts under `<output_root>/.job_parts/<workbook_slug>/job_<index>/raw/...`; merge moves them into the main run root, and `.job_parts` should remain only if merge fails.
- Cookbook-specific parsing overrides come from mapping `parsingOverrides` or `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.

## Job Splitting and Merge (PDF + EPUB)

Large PDFs and EPUBs can be split into range-based jobs when staging with `--workers > 1`. The worker pool processes slices in parallel, then the main process merges results into a single workbook output per file.

Key behaviors (both PDF and EPUB):
- Jobs are planned in the CLI using inspection metadata (`page_count` for PDF, `spine_count` for EPUB).
- Workers run a range-specific conversion and return a compact result payload (raw artifacts are written to disk and removed from the payload).
- The main process merges results, rewrites recipe IDs to a single global sequence (`...:c0`, `...:c1`, ...), updates tips and provenance IDs, and writes outputs once.
- Temporary raw artifacts live under `.job_parts/<workbook>/job_<index>/raw` and are merged into `raw/` when the merge completes. The `.job_parts` folder is removed after a successful merge and left in place if a merge fails for debugging.

### PDF Split Jobs

- Threshold flag: `--pdf-pages-per-job` (default defined in CLI; check `--help`).
- Range kind: `start_page` (inclusive), `end_page` (exclusive), 0-based.
- OCR and text extraction honor the page range so each job processes only its slice.
- Ordering for merge uses provenance `start_page` and falls back to block order.
- Split PDF jobs return `ConversionResult` payloads without raw artifacts. The main process merges recipes, tips, topics, and non-recipe blocks, then recomputes tips and chunks before writing outputs.
- Recipe IDs are rewritten to a global `c0..cN` sequence ordered by `provenance.location.start_page` (falling back to `start_block`). Tip `sourceRecipeId` references are updated via the same mapping.
- Raw artifacts are written under `.job_parts/<workbook_slug>/job_<index>/raw/` during job execution, then moved into `raw/` with filename prefixing on collisions once the merge completes.

### EPUB Split Jobs

- Threshold flag: `--epub-spine-items-per-job` (default defined in CLI; check `--help`).
- Range kind: `start_spine` (inclusive), `end_spine` (exclusive), 0-based spine indices.
- Blocks carry absolute `spine_index` to make ordering deterministic across jobs.
- Ordering for merge uses `start_spine` and falls back to block order.
- EPUB split jobs rely on linear `start_block`/`end_block` indices and absolute `spine_index` to preserve a stable global ordering key across jobs.

### Merge and ID Reassignment

- Merging happens in the main process after all jobs for a file complete.
- Recipes are sorted by provenance location (`start_spine` or `start_page`, then block order) before IDs are rewritten.
- All recipe-specific tips and provenance `id`/`@id` fields are updated to the rewritten IDs.
- Tip partitioning and chunk generation are recomputed once for the merged results to ensure consistency.

### Worker Fallback and Progress

- If `ProcessPoolExecutor` cannot be created (for example `PermissionError` in restricted environments), the CLI falls back to serial execution.
- Progress UI counts jobs (not just files) and displays ranges like `pages 1-50` or `spine 1-10` on worker lines.
- Merge progress is reported explicitly (`Merging N jobs for <file>...`).
- Split EPUB/PDF jobs finish in workers, but the main process performs the merge. The CLI surfaces a `MainProcess` status line during merges and advances the job progress before merge work begins so the UI reflects ongoing activity.

## Known Limitations and Gotchas

- EPUB split jobs do not currently detect recipes that span spine boundaries; segmentation at the boundary can split a recipe. Future improvement would require cross-spine context or overlap handling.
- PDF column clustering is essential because PyMuPDF default ordering is tiled (left-to-right across a page). If clustering fails, multi-column recipes can be mis-ordered.
- OCR can misread `l` and `I` as quantities; this shows up as false ingredient lines.
- `cookimport/cli.py` always passes a `MappingConfig` to workers, so `importer.inspect` is not invoked automatically in the non-split path. Job planning explicitly calls inspect when it needs counts.
- Split job raw artifacts are merged on the main process; name collisions are resolved by prefixing filenames with the job index.

## Historical Notes (Why Things Look This Way)

- 2026-02-02: PDF page-range splitting and merge were implemented with serial fallback and global ID rewriting.
- 2026-02-02: EPUB spine-range splitting reuses the PDF split framework and adds `start_spine` ordering to provenance.
- 2026-02-01: An earlier EPUB split plan included overlap and owned-range filtering, but the implemented version uses spine ranges without overlap. If boundary errors become significant, revisit overlap-based ownership.

## Quick Debug Checklist

- Confirm the file is detected by the correct importer via `cookimport/plugins/registry.py`.
- For split jobs, verify `page_count` or `spine_count` appears in inspection results and that the expected range flags are present in CLI logs.
- If outputs are duplicated, check `.job_parts` for leftover job folders and verify the merge completed.
- If recipe IDs are inconsistent, confirm the merge step rewrote IDs and updated tip references.
- For PDF layout issues, inspect column clustering heuristics and OCR fallback behavior.
