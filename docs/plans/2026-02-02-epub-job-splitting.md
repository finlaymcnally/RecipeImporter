# Split EPUB Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, large EPUB files can be split into spine-range jobs when `cookimport stage` runs with multiple workers. The user still receives one cohesive workbook output (one set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple part outputs. The observable behavior is that an EPUB import with `--workers > 1` shows multiple jobs with spine ranges, then merges into a single workbook with sequential recipe IDs.

## Progress

- [x] (2026-02-02 03:00Z) Drafted ExecPlan for EPUB job splitting and merge.
- [x] (2026-02-02 03:18Z) Implemented EPUB spine-range support in the importer and provenance.
- [x] (2026-02-02 03:28Z) Added job planning/worker/merge support for EPUB splits using the existing PDF job split infrastructure.
- [x] (2026-02-02 03:36Z) Updated tests, docs, and short folder notes for the new behavior.

## Surprises & Discoveries

- Observation: The EPUB importer currently treats all spine items as a single linear block stream, and block indices reset per run, so split jobs need an explicit spine index to preserve global ordering during merges.
  Evidence: `cookimport/plugins/epub.py` builds blocks in `_extract_docpack` and uses `start_block`/`end_block` for provenance, with no spine metadata.

## Decision Log

- Decision: Split EPUBs by spine item ranges and store `start_spine`/`end_spine` in provenance locations to preserve global ordering across merged jobs.
  Rationale: Spine items are the natural unit of EPUB structure and can be counted cheaply during inspection; location metadata provides a stable ordering key even when block indices are local to each job.
  Date/Author: 2026-02-02 / Codex

- Decision: Reuse the existing PDF job planning and merge helpers by generalizing them for non-PDF importers, keeping PDF wrappers intact for backward compatibility.
  Rationale: Avoids re-implementing split/merge logic and keeps tests for PDF splitting valid.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

EPUB imports now support spine-range job splitting when `--workers > 1`, with merged outputs and sequential recipe IDs. The CLI plans EPUB jobs using spine counts, workers can process spine ranges in parallel, and the merge step rewrites IDs while combining tips, chunks, and raw artifacts. Tests were added for EPUB ID reassignment, and documentation now covers the new flag and `.job_parts` behavior. Remaining work: consider a future improvement to detect recipes spanning spine boundaries if that becomes a practical issue.

## Context and Orientation

The bulk ingestion workflow lives in `cookimport/cli.py` (`stage` command). It plans work items (jobs), executes them in a `ProcessPoolExecutor`, and merges results for split PDFs via `_merge_pdf_jobs`. Split jobs use `cookimport/cli_worker.py:stage_pdf_job` to run a page range and write raw artifacts into a temporary `.job_parts/` folder that the main process merges back into `raw/` after the merge finishes.

The EPUB importer is `cookimport/plugins/epub.py`. It reads the EPUB spine, converts HTML to linear `Block` objects, segments blocks into recipes, and writes provenance locations with `start_block`/`end_block` indices. There is no spine index in the provenance today, so split jobs would lose global ordering unless we add spine metadata.

The job range logic currently lives in `cookimport/staging/pdf_jobs.py` via `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids`. We will generalize those helpers to allow EPUB splitting while keeping the PDF functions intact as wrappers.

## Plan of Work

First, extend `cookimport/core/models.py` and the EPUB inspector to record spine counts. Add a `spine_count` field (alias `spineCount`) to `SheetInspection`. Update `EpubImporter.inspect` to set `spine_count` using the EPUB spine length (via ebooklib or the zip fallback) so the CLI can decide when to split.

Next, update the EPUB importer to accept `start_spine` and `end_spine` range parameters and only parse the specified spine slice. In `cookimport/plugins/epub.py`, thread these parameters through `convert` and `_extract_docpack` into both the ebooklib and zip extraction paths. When parsing each spine item, annotate each generated `Block` with a `spine_index` feature. When building recipe provenance, compute `start_spine`/`end_spine` from the candidate blocks and include those values in the location dictionary. This gives merged jobs a stable ordering key. Keep the rest of the extraction logic unchanged.

Then generalize the job planning and merge helpers. In `cookimport/staging/pdf_jobs.py`, introduce a generic range planner and a generic ID reassigner that accept an importer name. Keep `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids` as wrappers. Update the sort key helper to consider `start_spine` (and `startSpine` if present) ahead of `start_block` when ordering recipes.

Update the CLI to plan EPUB jobs and merge them using the same merge flow as PDF jobs. Add a new CLI flag such as `--epub-spine-items-per-job` (default 10) and a `_resolve_epub_spine_count` helper to read the count from inspection. Extend `JobSpec` to track EPUB ranges (`start_spine`/`end_spine`) and choose the correct worker entrypoint (`stage_epub_job` vs `stage_pdf_job`) based on the range kind. Add `stage_epub_job` in `cookimport/cli_worker.py` mirroring the PDF job flow: run the range, write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, clear `result.raw_artifacts`, and return a mergeable payload with timing. Finally, add a new merge helper in `cookimport/cli.py` (or generalize `_merge_pdf_jobs`) that can merge EPUB jobs by calling the generalized ID reassigner with importer name `epub` and then writing outputs exactly as the PDF merge does.

Add tests and docs. Create a small unit test for the generalized range planner and for the EPUB ID reassignment ordering (using synthetic `RecipeCandidate` objects with `start_spine` in provenance). Update `docs/architecture/README.md` and `docs/ingestion/README.md` to mention EPUB job splitting and the new CLI flag. Update `docs/IMPORTANT CONVENTIONS.md` to note that EPUB split jobs also write raw artifacts into `.job_parts/` during merges. Add a short note in `cookimport/README.md` (or another existing short doc in the folder) describing the EPUB job split behavior and the new flag. If any new understanding is needed, add a brief note under `docs/understandings/`.

## Concrete Steps

All commands are run from `/home/mcnal/projects/recipeimport`.

1) Update models and EPUB inspection.

   - Edit `cookimport/core/models.py` to add `spine_count` to `SheetInspection` with alias `spineCount`.
   - Edit `cookimport/plugins/epub.py` to populate `spine_count` in `inspect` using spine length.

2) Add EPUB range support and provenance metadata.

   - Add `start_spine`/`end_spine` parameters to `EpubImporter.convert` and `_extract_docpack`.
   - In `_extract_docpack_with_ebooklib` and `_extract_docpack_with_zip`, iterate spine items with indices and filter by range.
   - Pass the spine index into `_parse_soup_to_blocks` and store it in block features.
   - When building candidate provenance, compute and store `start_spine`/`end_spine` in the location dict.

3) Generalize job planning and ID reassignment.

   - In `cookimport/staging/pdf_jobs.py`, add a generic range planner and a generic `reassign_recipe_ids` helper. Keep the existing PDF wrapper functions.
   - Extend the recipe sort key to consider `start_spine` before `start_block`.

4) Extend CLI/worker job splitting.

   - Add CLI flag `--epub-spine-items-per-job` to `cookimport/cli.py` and plan EPUB jobs when `workers > 1` and spine count exceeds the threshold.
   - Extend `JobSpec` to track EPUB spine ranges and to display `spine` ranges in the worker panel.
   - Add `stage_epub_job` in `cookimport/cli_worker.py` and call it for EPUB split jobs.
   - Generalize `_merge_pdf_jobs` into a shared helper that accepts importer name and range metadata, then call it for PDF and EPUB merges.

5) Tests and docs.

   - Add unit tests for EPUB ID reassignment ordering (e.g., `tests/test_epub_job_merge.py`).
   - Update `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` with the new EPUB split behavior.
   - Update `cookimport/README.md` with a short note about the new EPUB split flag.

## Validation and Acceptance

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 10 data/input/<large.epub>` should show multiple worker lines with spine ranges (for example, `book.epub [spine 1-10]`) and a merge message `Merging N jobs for book.epub...`.
- The output folder should contain a single workbook under `intermediate drafts/`, `final drafts/`, and `tips/`, plus a single report JSON for that EPUB.
- Recipe identifiers in the final output should be sequential (`...:c0`, `...:c1`, ...), and any recipe-specific tips should reference the updated IDs.
- Raw artifacts should be merged into `raw/` from `.job_parts/` and the `.job_parts/` folder should be removed after a successful merge.
- `pytest tests/test_epub_job_merge.py tests/test_pdf_job_merge.py` should pass; the EPUB test should fail before these changes and pass after.

## Idempotence and Recovery

The changes are safe to rerun because each staging run writes to a new timestamped output folder. If a merge fails, the temporary `.job_parts/` folder remains for debugging; re-running the command will create a new output folder and a new merge attempt without mutating previous outputs.

## Artifacts and Notes

Expected log excerpt for an EPUB split run:

    Processing 1 file(s) as 3 job(s) using 4 workers...
    worker-1: cookbook.epub [spine 1-10] - Parsing recipes...
    worker-2: cookbook.epub [spine 11-20] - Parsing recipes...
    Merging 3 jobs for cookbook.epub...
    ✔ cookbook.epub: 120 recipes, 18 tips (merge 5.12s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - Add `SheetInspection.spine_count: int | None` with alias `spineCount`.
- `cookimport/plugins/epub.py`
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None)`
  - `_extract_docpack(path, start_spine: int | None = None, end_spine: int | None = None)`
  - Store `spine_index` in block features and add `start_spine`/`end_spine` to provenance location.
- `cookimport/staging/pdf_jobs.py`
  - Add `plan_job_ranges` and `reassign_recipe_ids(importer_name=...)` helpers; keep existing PDF wrappers.
  - Update recipe sort key to consider `start_spine`.
- `cookimport/cli_worker.py`
  - Add `stage_epub_job` with the same mergeable payload format as `stage_pdf_job`.
- `cookimport/cli.py`
  - Add `--epub-spine-items-per-job` flag, EPUB job planning, and shared merge helper for split jobs.

Change note: 2026-02-02 — Initial ExecPlan created for EPUB job splitting.
Change note: 2026-02-02 — Updated progress, outcomes, and plan details after implementing EPUB job splitting and tests/docs.
