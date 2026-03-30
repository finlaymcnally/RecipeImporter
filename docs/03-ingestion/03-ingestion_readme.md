---
summary: "Code-verified ingestion runtime reference with architecture, behavior, contracts, and known limitations."
read_when:
  - Working on ingestion/importers, extraction, split jobs, or merge behavior
  - Debugging recipe ordering, ID reassignment, raw artifacts, or stage output mismatches
  - Reviewing current ingestion contracts before changing code
---

# Ingestion README

This is the source of truth for current ingestion behavior in `docs/03-ingestion`.

Historical anti-loop notes live in `docs/03-ingestion/03-ingestion_log.md`.

## Scope

Ingestion is source-first now.

Importers produce `ConversionResult` payloads whose authoritative fields are:
- `source_blocks`
- `source_support` (always non-authoritative)
- `raw_artifacts`
- `report`

Importers do not publish final recipe or non-recipe authority. In normal stage-backed flows they return:
- `recipes=[]`
- `chunks=[]`
- `non_recipe_blocks=[]`

The shared post-import stage session owns:
- recipe-boundary detection
- optional recipe Codex refinement
- non-recipe routing and final authority
- optional non-recipe finalize
- final writes for drafts, sections, tables, chunks, reports, and diagnostics

Primary folders:
- Input: `data/input`
- Output: `data/output/<YYYY-MM-DD_HH.MM.SS>/...`

## Current Runtime Owners

CLI and orchestration:
- `cookimport/cli_commands/stage.py`
- `cookimport/cli_support/stage.py`
- `cookimport/cli_worker.py`

Source-job planning and merge helpers:
- `cookimport/staging/job_planning.py`
- `cookimport/staging/pdf_jobs.py`
- `cookimport/core/source_model.py`

Shared post-import stage session:
- `cookimport/staging/import_session_flows/output_stage.py`
- `cookimport/staging/pipeline_runtime.py`
- `cookimport/staging/import_session_flows/authority.py`
- `cookimport/staging/writer.py`

Recipe-boundary and shared parsing seams used during ingestion:
- `cookimport/parsing/label_source_of_truth.py`
- `cookimport/parsing/recipe_span_grouping.py`
- `cookimport/parsing/sections.py`
- `cookimport/parsing/tables.py`
- `cookimport/parsing/chunks.py`
- `cookimport/parsing/tips.py`

Importer registry and active importers:
- `cookimport/plugins/registry.py`
- `cookimport/plugins/excel.py`
- `cookimport/plugins/epub.py`
- `cookimport/plugins/pdf.py`
- `cookimport/plugins/text.py`
- `cookimport/plugins/paprika.py`
- `cookimport/plugins/recipesage.py`
- `cookimport/plugins/webschema.py`

EPUB extraction helpers:
- `cookimport/parsing/epub_extractors.py`
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/parsing/markitdown_adapter.py`
- `cookimport/parsing/markdown_blocks.py`
- `cookimport/parsing/epub_html_normalize.py`
- `cookimport/parsing/epub_postprocess.py`
- `cookimport/parsing/epub_health.py`

OCR:
- `cookimport/ocr/doctr_engine.py`

## End-To-End Runtime Flow

### 1) Stage command setup

`cookimport stage ...`:
- creates the run directory using `%Y-%m-%d_%H.%M.%S`
- builds `RunSettings`
- loads mapping and parsing overrides
- sets EPUB extractor env vars for worker execution
- plans one or more source jobs with `plan_source_jobs(...)`
- runs jobs with process-first worker fanout and fallback order `ProcessPoolExecutor -> subprocess-backed workers -> ThreadPoolExecutor -> serial`
- writes `processing_timeseries.jsonl` while the run is active

### 2) Source-job planning

`cookimport/staging/job_planning.py` decides whether a source stays whole-file or splits.

Current split rules:
- PDF can split by page range when `pdf_split_workers > 1` and `pdf_pages_per_job > 0`
- EPUB can split by spine range when `epub_split_workers > 1`, `epub_spine_items_per_job > 0`, and the extractor is not `markitdown`
- `markitdown` is whole-book only

If range planning produces only one range, runtime stays in the same single-job shape as non-split files.

### 3) Worker execution

`cookimport/cli_worker.py:execute_source_job(...)`:
- resolves the best importer from the registry
- runs importer conversion for either the whole source or the planned page/spine range
- writes only raw artifacts under:
  - `<run_out>/.job_parts/<workbook_slug>/job_<index>/raw/...`
- clears `result.raw_artifacts` before returning the payload to the main process

### 4) Main-process merge

`cookimport/cli_support/stage.py:_merge_source_jobs(...)` waits for every job belonging to one source file, then:
- sorts successful job payloads by source order
- offsets and concatenates `source_blocks`
- rebases and concatenates `source_support`
- rebuilds merged `raw/<importer>/<source_hash>/full_text.json`
- runs the shared post-import stage session once on the merged source model
- moves raw artifacts from `.job_parts/.../raw` into run `raw/...`
- deletes `.job_parts/<workbook_slug>` on success

If any job fails:
- merge is skipped for that source
- an error report is written
- `.job_parts` is intentionally left behind for debugging

Raw collision rule:
- if a merged raw filename already exists, the mover prefixes `job_<index>_...` and adds a numeric suffix if needed

## Shared Post-Import Stage Session

`execute_stage_import_session_from_result(...)` in `cookimport/staging/import_session_flows/output_stage.py` owns the current five-stage runtime:

1. `extract`
- normalizes the canonical source model through `build_extracted_book_bundle(...)`

2. `recipe-boundary`
- runs label-first boundary detection through `build_label_first_stage_result(...)`
- writes deterministic label artifacts under `label_deterministic/...`
- writes grouped recipe-boundary diagnostics under `recipe_boundary/...`
- writes `label_refine/...` only when a non-`off` line-role pipeline is active

3. `recipe-refine`
- keeps deterministic projections when `llm_recipe_pipeline=off`
- otherwise runs the recipe Codex path
- writes authoritative recipe semantics to `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`

4. `nonrecipe-route`
- builds the route-first candidate/exclusion ledger from final block labels and accepted recipe spans

5. `nonrecipe-finalize`
- if `llm_knowledge_pipeline=off`, final non-recipe authority stays deterministic and chunks are generated from the late-output non-recipe block set
- if `llm_knowledge_pipeline` is enabled, Codex non-recipe finalize owns the final knowledge grouping path and chunk writing is skipped
- `ConversionResult.non_recipe_blocks` keeps only strict final non-recipe authority

After those stages, the session writes:
- source-model artifacts
- non-recipe authority artifacts
- recipe authority payloads
- intermediate drafts
- final drafts
- sections
- tables
- chunks when present
- raw artifacts
- stage-block predictions
- final report

## Split/Merge Ordering Rules

Split-job ordering is source-first:
- job payloads sort by `start_spine` or `start_page`
- merged `source_blocks` keep that order after rebasing
- merged `source_support` is rewritten onto the merged block ids
- final recipe ids are assigned later by the shared stage session after accepted recipe spans exist

## Importer Families

All active importers converge at the same source-first contract.

Block-first:
- EPUB
- PDF

Record-first:
- Text / DOCX
- Excel

Structured-export-first:
- Paprika
- RecipeSage
- Web Schema

Durable rule:
- importer-specific extraction is allowed
- canonical handoff is still `ConversionResult` with source-first fields
- downstream staging owns recipe and non-recipe authority

## Format Support Matrix

Supported:
- Excel: `.xlsx`, `.xlsm`
- EPUB: `.epub`
- PDF: `.pdf`
- Text: `.txt`, `.md`, `.markdown`
- DOCX: `.docx`
- Paprika: `.paprikarecipes`, plus Paprika directory merge mode
- RecipeSage: `.json` with RecipeSage export shape
- Web Schema: `.html`, `.htm`, `.jsonld`, and schema-like `.json`

Not implemented as dedicated importers:
- image files such as `.png` / `.jpg`
- live web scraping

## Importer Details

### Excel

`cookimport/plugins/excel.py`:
- detects `wide-table`, `template`, and `tall` layouts
- builds canonical `source_blocks` from sheet rows
- keeps merged-cell and header-alias handling in importer-specific extraction

### EPUB

`cookimport/plugins/epub.py` supports four explicit extractor modes:
- `unstructured`
- `beautifulsoup`
- `markdown`
- `markitdown`

Important current rules:
- `unstructured` is the default
- `markdown` and `markitdown` are policy-locked unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`
- `markitdown` is whole-book only and cannot take spine-range jobs
- EPUB writes extractor diagnostics plus `epub_extraction_health.json`
- deterministic pattern filtering writes `pattern_diagnostics.json`
- optional splitter diagnostics write `multi_recipe_split_trace.json`
- HTML-table rows preserve structured cell metadata for downstream table recovery

### PDF

`cookimport/plugins/pdf.py`:
- supports `start_page` / `end_page` range execution
- extracts text through PyMuPDF
- can OCR through docTR when policy allows
- writes `full_text.json`, `pattern_diagnostics.json`, and optional `multi_recipe_split_trace.json`

PDF ordering is still heuristic:
- blocks are ordered by page, inferred column, `y0`, then `x0`

### Text + DOCX

`cookimport/plugins/text.py`:
- handles `.txt`, `.md`, `.markdown`, and `.docx`
- keeps markdown/frontmatter handling in importer space
- supports `multi_recipe_splitter=off|rules_v1`
- synthesizes canonical `source_blocks` from lines, paragraphs, and DOCX table rows

### Paprika

`cookimport/plugins/paprika.py`:
- reads `.paprikarecipes` zip entries
- supports directory mode that merges zip export data with adjacent HTML export views

### RecipeSage

`cookimport/plugins/recipesage.py`:
- detects RecipeSage export shape
- validates exported rows
- keeps source-first handoff by synthesizing canonical blocks instead of emitting final recipes directly

### Web Schema

`cookimport/plugins/webschema.py`:
- is local-file only
- prefers schema.org recipe objects when available
- uses `web_schema_policy` to decide schema-first vs heuristic fallback behavior
- guards `.json` detection so RecipeSage exports win first

## Output Structure And Contracts

Typical stage outputs under `data/output/<timestamp>/` now include:
- `label_deterministic/<workbook_slug>/...`
- `label_refine/<workbook_slug>/...` when line-role correction runs
- `recipe_boundary/<workbook_slug>/...`
- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`
- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `sections/<workbook_slug>/r{index}.sections.json`
- `chunks/<workbook_slug>/...` when deterministic chunk output exists
- `tables/<workbook_slug>/tables.jsonl`
- `knowledge/<workbook_slug>/...` when knowledge outputs exist
- `raw/source/<workbook_slug>/source_blocks.jsonl`
- `raw/source/<workbook_slug>/source_support.json`
- `raw/<importer>/<source_hash>/...`
- `08_nonrecipe_route.json`
- `08_nonrecipe_exclusions.jsonl`
- `09_nonrecipe_authority.json`
- `09_nonrecipe_knowledge_groups.json`
- `09_nonrecipe_finalize_status.json`
- `.bench/<workbook_slug>/stage_block_predictions.json`
- `<workbook_slug>.excel_import_report.json`
- `processing_timeseries.jsonl`
- `run_manifest.json`
- `run_summary.json`
- `run_summary.md`
- `stage_observability.json`

Report fields that matter for ingestion debugging:
- `runTimestamp`
- `importerName`
- optional `epubBackend`
- timing
- warnings and errors
- `runConfig`
- `runConfigHash`
- `runConfigSummary`
- `llmCodexFarm`
- optional `outputStats`

## Config Surfaces That Still Matter

Frequently touched stage options:
- `--workers`
- `--pdf-split-workers`
- `--epub-split-workers`
- `--pdf-pages-per-job`
- `--epub-spine-items-per-job`
- `--write-markdown/--no-write-markdown`
- `--mapping`
- `--overrides`
- `--pdf-ocr-policy`
- `--ocr-device`
- `--ocr-batch-size`
- `--pdf-column-gap-ratio`
- `--epub-extractor`
- `--epub-unstructured-html-parser-version`
- `--epub-unstructured-skip-headers-footers`
- `--epub-unstructured-preprocess-mode`
- `--web-schema-extractor`
- `--web-schema-normalizer`
- `--web-html-text-extractor`
- `--web-schema-policy`
- `--web-schema-min-confidence`
- `--web-schema-min-ingredients`
- `--web-schema-min-instruction-steps`
- `--multi-recipe-splitter`
- `--multi-recipe-trace/--no-multi-recipe-trace`
- `--multi-recipe-min-ingredient-lines`
- `--multi-recipe-min-instruction-lines`
- `--multi-recipe-for-the-guardrail/--no-multi-recipe-for-the-guardrail`
- `--recipe-scorer-backend`
- `--recipe-score-gold-min`
- `--recipe-score-silver-min`
- `--recipe-score-bronze-min`
- `--recipe-score-min-ingredient-lines`
- `--recipe-score-min-instruction-lines`
- `--llm-recipe-pipeline`
- `--llm-knowledge-pipeline`
- `--codex-farm-failure-mode`

Relevant run-setting values:
- `multi_recipe_splitter=off|rules_v1`
- `llm_recipe_pipeline=off|codex-recipe-shard-v1`
- `llm_knowledge_pipeline=off|codex-knowledge-candidate-v2`

## What We Know Is Still Risky

1. EPUB split boundaries still have no overlap context.
- If a recipe crosses a spine split, boundary quality can drop.

2. PDF ordering is still heuristic.
- Unusual layouts can scramble column order and hurt later boundary detection.

3. OCR noise still creates structured false positives.
- Bad OCR can look ingredient-like or instruction-like enough to survive into later stages.

4. `.job_parts` leftovers are usually failure evidence, not a normal steady-state artifact.
- Treat them as merge/interruption diagnostics first.

5. Importer fixes are often the wrong first seam.
- If source blocks look reasonable but outputs are wrong, inspect recipe-boundary, non-recipe routing, or nonrecipe-finalize behavior before making importers “smarter.”
