# Split PDF Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large PDF can fully utilize multiple workers by being split into page-range jobs (for example, a 200 page PDF with 4 workers runs as four jobs over pages 1–50, 51–100, 101–150, and 151–200). The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs. The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large PDF and seeing parallel job progress plus a single workbook output folder when the run completes.

## Progress

- [x] (2026-02-02 00:00Z) Drafted initial ExecPlan with proposed job splitting + merge design.
- [x] (2026-02-02 02:05Z) Implemented job planning for PDF page splits in `cookimport/cli.py`.
- [x] (2026-02-02 02:12Z) Added page-range support to `cookimport/plugins/pdf.py` and propagated OCR/text paths.
- [x] (2026-02-02 02:35Z) Added job-level worker entrypoint and merge logic for multi-job PDFs.
- [x] (2026-02-02 02:55Z) Updated docs + conventions and added unit tests for job planning and ID rewriting.

## Surprises & Discoveries

- Observation: `cookimport/cli.py` always passes a `MappingConfig` to workers even when no mapping file is provided, so the current `stage_one_file` path never runs `importer.inspect` automatically.
  Evidence: `cookimport/cli.py` sets `base_mapping = mapping_override or MappingConfig()` and always passes it into `stage_one_file`.
- Observation: `ProcessPoolExecutor` can raise `PermissionError` in restricted environments (e.g., during CLI tests), preventing worker startup.
  Evidence: CLI test run failed with `PermissionError: [Errno 13] Permission denied` during ProcessPool initialization.

## Decision Log

- Decision: Merge multi-job PDF outputs in the main process and rewrite recipe IDs to a single global sequence (`c0..cN`) so IDs remain stable regardless of whether a PDF was split.
  Rationale: This avoids ID collisions across jobs and keeps stable IDs consistent with the existing full-file ordering scheme.
  Date/Author: 2026-02-02 / Codex

- Decision: Keep the existing worker path for files that are not split, so normal multi-file runs still write outputs in parallel.
  Rationale: Avoids moving all output writing to the main process and preserves current performance.
  Date/Author: 2026-02-02 / Codex

- Decision: Use a single configurable threshold (`--pdf-pages-per-job`, default 50) to decide when to split and how many jobs to create (capped by worker count).
  Rationale: Matches the example (200 pages / 4 workers → 4 jobs of 50 pages) while keeping the CLI surface minimal.
  Date/Author: 2026-02-02 / Codex

- Decision: Fall back to serial execution if `ProcessPoolExecutor` cannot be created (PermissionError).
  Rationale: Keeps staging usable in restricted environments while preserving parallelism when available.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

Implemented PDF job splitting and merge flow so large PDFs can run in parallel while
producing a single cohesive workbook output. The CLI now plans jobs, workers can
process page ranges, and the main process merges results, rewrites IDs, and merges
raw artifacts. Documentation and unit tests were updated to cover the new behavior.

Lessons learned: isolating raw artifacts in job-specific folders kept merge payloads
light and made the final merge deterministic.

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `ProcessPoolExecutor`, and calls `cookimport/cli_worker.py:stage_one_file` per file. `stage_one_file` selects an importer from `cookimport/plugins/registry.py`, runs `importer.convert(...)` to produce a `ConversionResult`, generates knowledge chunks, enriches a `ConversionReport`, and writes outputs via `cookimport/staging/writer.py`.

The PDF importer lives in `cookimport/plugins/pdf.py`. It currently processes the entire document in one pass and assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}`. OCR is optional and implemented in `cookimport/ocr/doctr_engine.py:ocr_pdf`, which already accepts `start_page` and `end_page` (exclusive).

For this change we introduce a “job” as the new unit of work. A job is either an entire file (non-split) or a page-range slice of a PDF (split). Each job executes `PdfImporter.convert` on its page range. After all jobs for a file complete, their results are merged, IDs are re-assigned in global order, and a single output folder is written.

## Plan of Work

First, add job planning logic to `cookimport/cli.py`. Create a small helper (either inside `cli.py` or a new module such as `cookimport/cli_jobs.py`) that inspects each file to decide whether it should be split. For PDF files, retrieve a page count via `PdfImporter.inspect` (add a `page_count` field to `SheetInspection` in `cookimport/core/models.py`, and populate it in `PdfImporter.inspect`). If `page_count > --pdf-pages-per-job` and `workers > 1`, generate page ranges sized at `ceil(page_count / job_count)` where `job_count = min(workers, ceil(page_count / pdf_pages_per_job))`. Each range is `[start_page, end_page)` with 0-based indexing. Non-PDFs and PDFs that do not meet the threshold stay as single jobs.

Second, extend `PdfImporter.convert` to accept optional `start_page` and `end_page` parameters. When a range is provided, the OCR path should call `ocr_pdf(path, start_page=..., end_page=...)`, and the text extraction path should iterate pages only over that range, passing the absolute page index into `_extract_blocks_from_page`. Update progress messages to reflect `page_num + 1` and the total pages in the slice. Add a warning to the report if the requested slice is empty (start >= end). Ensure the rest of the extraction pipeline (candidate segmentation, tips, topics, raw artifacts) works unchanged on the subset of blocks.

Third, refactor `cookimport/cli_worker.py` so it can run a page-range job and return a mergeable payload without writing full outputs. Extract a helper (for example `run_import`) that executes the import, timing, and report enrichment but returns a `ConversionResult`. For split jobs, write only raw artifacts to a job-specific temporary directory (for example `{out}/.job_parts/{workbook_slug}/job_{index}/raw/...`) and clear `result.raw_artifacts` before returning to reduce inter-process payload size. For non-split files, keep the existing `stage_one_file` behavior so outputs are written in the worker.

Fourth, add a merge step in `cookimport/cli.py` for files that were split into multiple jobs. Collect `JobResult` payloads, sort them by `start_page`, and merge their `ConversionResult` lists (recipes, tip candidates, topic candidates, non-recipe blocks). Recompute `tips` using `partition_tip_candidates` so it matches the merged tip candidate list. Then rewrite recipe identifiers and provenance to a global sequence:

- Sort merged recipes by their provenance `location.start_page` (fall back to `location.start_block` or the merge order).
- For each recipe at global index `i`, set `candidate.identifier = generate_recipe_id("pdf", file_hash, f"c{i}")`, update `candidate.provenance["@id"]` (and `id` if present), and set `candidate.provenance["location"]["chunk_index"] = i`.
- Build a mapping from old IDs to new IDs. Update `TipCandidate.source_recipe_id` and any `tip.provenance["@id"]` or `tip.provenance["id"]` that match old IDs.

After IDs are updated, apply the CLI `--limit` (once, at the merged level), regenerate knowledge chunks using `chunks_from_non_recipe_blocks` or `chunks_from_topic_candidates`, and build a fresh `ConversionReport` with totals and `enrich_report_with_stats`. Write the merged outputs using `write_intermediate_outputs`, `write_draft_outputs`, `write_tip_outputs`, `write_topic_candidate_outputs`, `write_chunk_outputs`, and `write_report` into the normal output directories. Finally, merge raw artifacts by moving job raw folders into the final `{out}/raw/...` tree; if name collisions occur, prefix the filename with the job index to preserve uniqueness. Remove the temporary `.job_parts` folder once the merge succeeds.

Fifth, update the progress UI. The overall progress bar should count total jobs, not just files, and the worker status lines should include the page range (for example `cookbook.pdf [pages 1-50]`). After a file’s jobs finish and merge begins, log a line like `Merging 4 jobs for cookbook.pdf...` so users understand the second phase.

Finally, add tests and docs. Create unit tests for page-range slicing and merged-ID rewriting (in a new `tests/test_pdf_job_merge.py` or similar) using synthetic `ConversionResult` objects so we do not require real PDFs. Update `docs/architecture/README.md` and `docs/ingestion/README.md` to describe PDF job splitting and the merge step, and add a short note in a relevant folder (likely `cookimport/README.md` or a new short doc in `cookimport/`) explaining how job splitting behaves. If the output structure introduces a `.job_parts` temp folder, document it in `docs/IMPORTANT CONVENTIONS.md`.

## Concrete Steps

All commands assume the working directory `/home/mcnal/projects/recipeimport`.

1) Inspect current CLI/worker/PDF surfaces (if not already done):

    rg -n "stage_one_file|ProcessPoolExecutor|PdfImporter" cookimport

2) Implement model + PDF changes:

    - Edit `cookimport/core/models.py` to add `page_count: int | None = Field(default=None, alias="pageCount")` to `SheetInspection`.
    - Edit `cookimport/plugins/pdf.py` to populate `page_count` in `inspect`, and add `start_page`/`end_page` support in `convert` plus the OCR/text extraction paths.

3) Implement job planning + merging:

    - Edit `cookimport/cli.py` to add `--pdf-pages-per-job` and job planning helpers, and to schedule job futures differently for split vs non-split files.
    - Edit `cookimport/cli_worker.py` to add a job-capable entrypoint (and refactor shared logic as needed) that returns mergeable payloads and writes raw artifacts to a job temp folder.
    - Add merge helpers in `cookimport/cli.py` or a new module (for example `cookimport/staging/merge.py`).

4) Tests (use local venv):

    - Create/activate `.venv` if needed, then install dev deps:

        python -m venv .venv
        . .venv/bin/activate
        python -m pip install --upgrade pip
        pip install -e .[dev]

    - Run targeted tests:

        pytest tests/test_pdf_job_merge.py tests/test_cli_output_structure.py

5) Docs updates:

    - Edit `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` as described in Plan of Work.
    - Add/adjust a short, folder-local note describing the new job split behavior.

## Validation and Acceptance

Acceptance is met when the following manual scenario works and outputs are cohesive:

1) Run `cookimport stage --workers 4 --pdf-pages-per-job 50 data/input/<large.pdf>` and observe the worker panel showing multiple jobs with page ranges.
2) In the output folder (`data/output/{timestamp}`), verify that only one workbook slug exists under `intermediate drafts/`, `final drafts/`, and `tips/`, with sequential `r{index}.json(ld)` numbering and a single report JSON file.
3) Confirm that recipe `identifier` values are sequential (`...:c0`, `...:c1`, …) across the merged output, and that any recipe-specific tips reference the updated recipe IDs.
4) Verify raw artifacts exist under `raw/pdf/{hash}/...` with no filename collisions (job prefixing is acceptable if needed).

If automated tests are added, they should fail before this change and pass after. Specifically, the new merge test must assert that merged recipe IDs and tip `sourceRecipeId` values are updated to the global sequence.

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging; re-run the command to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error report so the run still completes for other files.

## Artifacts and Notes

Expected log lines during a split run (example):

    Processing 1 file(s) as 4 job(s) using 4 workers...
    worker-1: cookbook.pdf [pages 1-50] - Parsing recipes...
    worker-2: cookbook.pdf [pages 51-100] - Parsing recipes...
    Merging 4 jobs for cookbook.pdf...
    ✔ cookbook.pdf: 128 recipes, 14 tips (merge 6.42s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - `SheetInspection.page_count: int | None` (alias `pageCount`).
- `cookimport/plugins/pdf.py`
  - `PdfImporter.convert(path, mapping, progress_callback, start_page: int | None = None, end_page: int | None = None)`
  - Use `ocr_pdf(path, start_page=..., end_page=...)` for OCR path; iterate `fitz` pages in `[start_page, end_page)` for non-OCR.
- `cookimport/cli_worker.py`
  - New job entrypoint returning a `JobResult` containing `ConversionResult` (with raw artifacts cleared), job metadata, and duration.
- `cookimport/cli.py`
  - Job planning helper, CLI options for `--pdf-pages-per-job`, and merge orchestration.
- `cookimport/staging/writer.py`
  - No interface changes; reuse existing write helpers for merged output.

Change note: 2026-02-02 — Initial ExecPlan created in response to the request to plan before implementation.
Change note: 2026-02-02 — Updated progress, outcomes, and documented completion of PDF job splitting implementation (including serial fallback note).
