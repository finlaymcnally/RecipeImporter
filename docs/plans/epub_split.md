# Split large EPUBs into worker jobs and merge into one cohesive workbook

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large `.epub` can fully utilize multiple workers by being split into “spine-range jobs” (contiguous ranges of reading-order documents). For example, a big EPUB with 80 spine items and 4 workers can run as 4 jobs over spine items 0–19, 20–39, 40–59, and 60–79. The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs.

The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large EPUB and seeing parallel job progress plus a single workbook output folder when the run completes. The merged outputs must have stable sequential recipe IDs as if the EPUB had been processed in one pass.

## Progress

- [ ] (2026-02-01 00:00Z) Read the existing PDF job splitting implementation and identify reusable job planning, worker entrypoint, temp output layout, and merge helpers.
- [ ] Add EPUB inspection fields needed to plan spine-range jobs (spine item count).
- [ ] Extend `cookimport/plugins/epub.py` so `convert` can process a spine slice (plus optional overlap) and so blocks/candidates record absolute spine indices in provenance.
- [ ] Extend CLI job planning to split EPUBs into spine-range jobs (behind a threshold flag) and schedule those jobs in the existing process pool.
- [ ] Implement EPUB merge logic in the main process that combines job results, rewrites recipe IDs to a single global sequence, merges raw artifacts, and writes one workbook output folder.
- [ ] Add tests for job planning, slice filtering, and merged ID rewriting (no real EPUB required; synthetic objects are acceptable).
- [ ] Update docs and CLI help strings, and add a note describing the temporary `.job_parts` behavior for split EPUBs.
- [ ] Validate on a real large EPUB: confirm parallel job progress and one cohesive output folder; document measured speedup and any accuracy changes.

## Surprises & Discoveries

- Observation: (fill during implementation)
  Evidence: (short command output or failing test snippet)

## Decision Log

- Decision: (fill during implementation)
  Rationale: (why this path was chosen)
  Date/Author: (YYYY-MM-DD / who)

## Outcomes & Retrospective

- (Fill at milestone completion and at the end: what improved, what broke, what remains, and lessons learned.)

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `concurrent.futures.ProcessPoolExecutor`, and calls a worker entrypoint (commonly `cookimport/cli_worker.py:stage_one_file`) per unit of work. Plugins are chosen via `cookimport/plugins/registry.py` and implement `detect`, `inspect`, and `convert`. Converting unstructured sources typically produces a linear sequence of `Block` objects which are segmented into `RecipeCandidate`, `TipCandidate`, and `TopicCandidate` objects, along with raw artifacts and a report.

This repository already contains a “job splitting + merge” pattern for PDFs: a large file is split into multiple jobs, each job processes a slice, the main process merges results into one workbook output, and recipe identifiers are rewritten to a single stable global sequence (`...:c0`, `...:c1`, …). This ExecPlan extends that same pattern to EPUB files to achieve the same benefit for large cookbooks.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python in parallel on multiple CPU cores.
- “Job”: one unit of work submitted to the worker pool. For an EPUB split run, each job is a contiguous slice of the EPUB’s reading order.
- “EPUB spine item”: an entry in the EPUB’s OPF “spine”, which defines the reading order. In practice this corresponds to an HTML/XHTML “chapter” file inside the EPUB container.
- “Spine-range job”: a job defined by `[start_spine_index, end_spine_index)` (0-based, end exclusive).
- “Overlap”: extra spine items included on each side of a job slice to preserve segmentation context near boundaries. Overlap is used only for context; the job returns only recipes whose start location falls within the job’s owned range to avoid duplicates.
- “Owned range”: the non-overlapped spine range that a job is responsible for contributing to the final merged output.

Assumptions this plan relies on (verify in code before editing):

- `cookimport/plugins/epub.py` exists and uses EbookLib / BeautifulSoup / lxml for parsing.
- The PDF split implementation already introduced: (a) a representation of per-file jobs, (b) a `.job_parts` output convention for split files, (c) a merge step in the main process that rewrites recipe IDs and merges raw artifacts, and (d) a serial fallback if `ProcessPoolExecutor` cannot be created (for example due to `PermissionError` in restricted environments).
- `RecipeCandidate` (and related models) carry provenance that can be extended to include spine indices and block indices so that ordering and filtering are deterministic.

If any of those assumptions are false, update this plan’s Decision Log with the chosen adaptation and ensure all sections remain self-contained.

## Plan of Work

This work mirrors the PDF splitting approach: plan jobs in the CLI, teach the EPUB importer to process only a slice, have workers produce mergeable partial results without writing the full workbook outputs, then merge in the main process and write one cohesive output.

### Milestone 1: Reuse and generalize the existing job framework for a new “epub spine slice” job kind

By the end of this milestone you will know exactly which functions and data structures the PDF split system uses for job planning, worker execution, temp output folders, and merging, and you will have a clear place to add EPUB job support.

Work:

Read the files involved in the PDF split flow and write down the exact names and signatures you will reuse. Specifically locate:

- Where jobs are planned (likely inside `cookimport/cli.py` or a helper module).
- How a job is represented (a dataclass or Pydantic model holding job metadata such as kind, slice bounds, and output temp paths).
- The worker entrypoint for a job and what it returns to the parent process (a “JobResult” or similar).
- The merge function and how it rewrites recipe IDs and merges raw artifacts into the final output.

Decision to make and record:

- Whether to add EPUB support by introducing a new job kind (recommended), or by generalizing “slice jobs” into a single abstraction used by both PDF and EPUB. Prefer the smallest change that preserves readability and testability.

### Milestone 2: Add EPUB inspection data needed for splitting (spine item count)

By the end of this milestone, the CLI can cheaply determine how many spine items an EPUB contains without performing the full conversion.

Work:

- In `cookimport/plugins/epub.py`, implement or extend `EpubImporter.inspect(path)` so it returns a count of spine items (document items in reading order).
- Decide where to store this in inspection models:
  - If your PDF split already added `SheetInspection.page_count`, extend the same inspection model with a new optional `spine_item_count` field (preferred for symmetry).
  - If inspection models do not have a natural place for this, add a new field to the top-level `WorkbookInspection` such as `epub_spine_item_count`. Record the choice in the Decision Log.

Implementation detail (what “spine item count” should mean):

- Open the EPUB using EbookLib and compute the number of document items in the spine reading order.
- Count only document content (HTML/XHTML) items that will actually produce blocks; ignore images, stylesheets, and non-document items.
- The count must be deterministic and stable across runs, because the split planner will use it.

Proof:

- `cookimport inspect some.epub` (or whatever command triggers inspection) shows the spine count in the inspection output or report artifacts.
- A small unit test can call `EpubImporter.inspect` on a minimal EPUB fixture and assert the count is correct.

### Milestone 3: Teach the EPUB importer to convert a spine slice with overlap and stable provenance

By the end of this milestone, `EpubImporter.convert` can run on a subset of spine items and produce results whose provenance includes absolute spine indices (so merge ordering and slice filtering are deterministic).

Work:

- Extend `cookimport/plugins/epub.py:EpubImporter.convert` to accept optional keyword arguments:
  - `start_spine: int | None = None`
  - `end_spine: int | None = None`
  - `owned_start_spine: int | None = None`
  - `owned_end_spine: int | None = None`

Interpretation:

- The importer processes the “slice range” `[start_spine, end_spine)` (this may include overlap).
- The importer filters its produced recipe candidates (and any recipe-specific tip candidates) to only those whose start location lies within the “owned range” `[owned_start_spine, owned_end_spine)`.
- If no slice is provided, behavior is unchanged (full EPUB conversion).

How to implement without breaking existing behavior:

- Identify where EPUB content is enumerated today. Usually this looks like: iterate over spine items in reading order, parse each HTML/XHTML file into blocks, append blocks to one list, then run segmentation.
- Modify enumeration so that, when a slice is provided, you only iterate spine items within `[start_spine, end_spine)`. Critically, preserve the absolute spine index (0-based in full EPUB) as `spine_index` on every block’s provenance location.
- Ensure the block-level provenance also contains a stable per-spine-item block index (for example `block_index_within_spine`) so ordering within a spine item is stable. If a global block index already exists, keep it, but make sure it remains deterministic for sliced runs.

Filtering rule (prevents duplicates when overlap is used):

- Define a function that determines the “start location” of a `RecipeCandidate`. Prefer the earliest block that the candidate claims as its provenance location.
- A candidate belongs to the job if:
  - `owned_start_spine <= candidate.provenance.location.spine_index < owned_end_spine`.
- Apply the same rule to recipe-specific tips if they are anchored to a recipe start location or if they reference a source recipe ID; in ambiguous cases keep tips and let the merge step re-partition them, but ensure no duplicate recipe-specific tips survive the merge.

Edge cases to handle:

- Empty slice: if `start_spine >= end_spine`, return an empty `ConversionResult` with a warning in the report.
- Single-spine EPUB: splitting should not occur; slice conversion still works but produces little benefit.

Proof:

- A targeted unit test can build synthetic blocks with spine indices and prove that slice conversion yields candidates whose provenance spine indices are in the owned range.
- A manual run on a real EPUB with `--workers 1` and an explicit slice (temporary CLI flag or a direct call in a small dev script) produces reasonable partial outputs.

### Milestone 4: Plan EPUB spine-range jobs in the CLI and run them in the worker pool

By the end of this milestone, `cookimport stage` can split a single large EPUB into multiple spine-range jobs, submit them to workers, and collect job results.

Work:

- In `cookimport/cli.py`, extend the existing job planning helper to recognize `.epub` inputs and produce EPUB jobs when all of the following are true:
  - `--workers > 1`
  - The importer selected for the file is the EPUB importer.
  - `spine_item_count` is greater than a threshold derived from a new CLI flag (see below).

Add new CLI flags (name them to match the existing PDF flag style):

- `--epub-spine-items-per-job` (integer, default 20; must be > 0)
  - This controls when splitting happens and the approximate size of each job.
- `--epub-spine-overlap-items` (integer, default 1; can be 0)
  - This controls how many spine items of overlap are included on each side of a job slice for context.

Job planning algorithm (deterministic and simple):

- Let `S = spine_item_count`.
- If `S <= epub_spine_items_per_job` or `workers == 1`, create a single non-split job for the file.
- Otherwise:
  - Let `job_count = min(workers, ceil(S / epub_spine_items_per_job))`.
  - Let `range_size = ceil(S / job_count)`.
  - For `job_index` from 0 to `job_count-1`:
    - `owned_start = job_index * range_size`
    - `owned_end = min(S, owned_start + range_size)`
    - `slice_start = max(0, owned_start - overlap)`
    - `slice_end = min(S, owned_end + overlap)`
    - Create an EPUB job with these four bounds and the `job_index`.
- Ensure the final job list covers `[0, S)` in owned ranges with no gaps and no overlaps (owned ranges), even though slice ranges will overlap.

Worker execution:

- Reuse the existing worker entrypoint pattern from the PDF split flow. Add EPUB job support by:
  - Passing `start_spine`, `end_spine`, `owned_start_spine`, `owned_end_spine` into `EpubImporter.convert`.
  - Writing raw artifacts into a job temp folder under `.job_parts` and returning a small payload (do not return all raw artifacts over IPC if they are large).
  - Returning job metadata: file path, job index, owned range, slice range, duration, counts.

Resilience:

- Preserve the existing serial fallback: if `ProcessPoolExecutor` cannot be created, process as a single non-split job (log a warning that parallelism is disabled).

Proof:

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 some_large.epub` shows multiple worker status lines that include spine ranges.
- The staging run finishes without writing multiple workbook roots (merge happens next milestone).

### Milestone 5: Merge EPUB job results into a single cohesive workbook and write outputs once

By the end of this milestone, split EPUB runs produce exactly one workbook output folder with stable IDs and consistent reports.

Work:

- Add or extend the main-process merge step for “split files” to support EPUB jobs. Follow the same high-level strategy as PDF merge:
  - Collect all `JobResult` objects for a given EPUB file.
  - Sort jobs by `owned_start_spine`.
  - Merge their `ConversionResult` payloads into one merged `ConversionResult` for the file.
  - Rewrite recipe identifiers to a single global sequence so IDs do not depend on splitting.
  - Merge raw artifacts from `.job_parts` into the final raw folder and remove `.job_parts` on success.
  - Write intermediate drafts, final drafts, tips, topics, chunks, and the report using existing writer helpers.

Merging details to make deterministic:

- Ordering for merged recipes:
  - Sort by `(recipe.provenance.location.spine_index, recipe.provenance.location.start_block_index)` if those fields exist.
  - If only block ordering exists, ensure it is stable and derived from spine ordering.
- ID rewriting:
  - Use the existing EPUB ID scheme if one exists, but rewrite to sequential suffixes (`c0..cN`) in merged order.
  - Build an `old_id -> new_id` mapping and update all references:
    - recipe-specific tips’ `source_recipe_id` (or equivalent field)
    - any provenance `@id` or `id` values that embed or reference the old recipe identifier
- Tip recomputation:
  - If the pipeline partitions tips after extraction, run that partitioning on the merged candidates once, in the main process, so “general vs recipe-specific” is consistent.

Raw artifacts:

- For split jobs, the worker should write raw artifacts to:
  - `{out}/.job_parts/{workbook_slug}/job_{job_index}/raw/...`
- The merge step should merge these into the final raw artifact tree, preferring deterministic naming. If collisions occur, prefix the filename with `job_{job_index}_`.

Output writing policy (important for consistency):

- For split EPUBs, only the main process writes the final workbook outputs (intermediate drafts, final drafts, tips, report).
- For non-split files (including non-split EPUBs), preserve the existing “worker writes outputs” behavior to avoid slowing normal multi-file parallel runs.

Proof:

- A split EPUB run produces:
  - One workbook slug under `intermediate drafts/`, `final drafts/`, `tips/`, and a single report JSON.
  - Sequential recipe identifiers in the merged output.
  - No `.job_parts` directory remaining after success (unless configured to keep for debugging).

### Milestone 6: Tests and documentation

By the end of this milestone, the behavior is protected by tests and discoverable to users.

Tests to add (prefer unit tests that do not require real EPUB files):

- Job planning test:
  - Given `spine_item_count=80`, `workers=4`, `items_per_job=20`, `overlap=1`, assert you get 4 jobs with owned ranges `[0,20) [20,40) [40,60) [60,80)` and slice ranges expanded by 1 on both sides where possible.
- Slice filtering test:
  - Create synthetic `RecipeCandidate` objects with provenance spine indices spanning the overlap boundary, ensure the filter keeps only those in the owned range.
- Merge ID rewrite test:
  - Create two or more synthetic job results containing recipes and recipe-specific tips referencing the old IDs; after merge, assert IDs are sequential and tip references were updated.

Documentation updates:

- Update CLI help for new flags.
- Update the same docs that describe PDF splitting to mention EPUB splitting and the “spine-range job” concept.
- Document `.job_parts` for EPUB (location, what it contains, and when it is removed).

Proof:

- `pytest -q` passes and includes at least one new test file covering EPUB splitting.
- The docs mention how to tune `--epub-spine-items-per-job` and warn that overly aggressive worker counts can increase RAM usage (important for users on smaller machines).

## Concrete Steps

All commands are run from the repository root.

1) Find the EPUB importer and current conversion flow.

    rg -n "class .*Epub|EpubImporter|epub\\.py" cookimport/plugins
    rg -n "def inspect\\(|def convert\\(" cookimport/plugins/epub.py

2) Find the existing job splitting framework (from the PDF work) and identify extension points.

    rg -n "Job|job_parts|pdf-pages-per-job|merge" cookimport/cli.py cookimport/cli_worker.py cookimport -S

3) Implement inspection spine count.

    - Edit `cookimport/plugins/epub.py` to compute spine count in `inspect`.
    - Edit `cookimport/core/models.py` (or the relevant inspection model file) to store spine count in the inspection result.

4) Implement slice conversion with overlap and owned-range filtering.

    - Edit `cookimport/plugins/epub.py:EpubImporter.convert` to accept the new keyword args and limit iteration to the slice range.
    - Ensure block provenance includes absolute `spine_index` and a stable within-spine block index.

5) Add CLI flags and plan EPUB jobs.

    - Edit `cookimport/cli.py` to add `--epub-spine-items-per-job` and `--epub-spine-overlap-items`.
    - Extend the job planner to create EPUB jobs using the algorithm described above.

6) Add worker execution support.

    - Edit `cookimport/cli_worker.py` to accept EPUB jobs and pass slice bounds into `EpubImporter.convert`.
    - For EPUB slice jobs, write raw artifacts to `.job_parts/...` and return a light payload.

7) Add merge support.

    - Edit the merge logic (where PDF merge happens) to handle EPUB jobs:
      merge results, rewrite IDs, update references, merge raw artifacts, write final outputs.

8) Run tests and add missing ones.

    pytest -q

9) Manual verification on a large EPUB.

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub

    Expected high-signal log lines (example, wording may differ):

      Processing 1 file(s) as 4 job(s) using 4 workers...
      worker-1: cookbook.epub [spine 0-21; owned 0-20]
      worker-2: cookbook.epub [spine 19-41; owned 20-40]
      Merging 4 jobs for cookbook.epub...
      ✔ cookbook.epub: N recipes, M tips (merge X.XXs)

## Validation and Acceptance

Acceptance is met when all of the following are true:

1) Split run produces parallel job progress and one cohesive output folder.

- Running:

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/<large.epub>

  shows multiple concurrent jobs with spine ranges, followed by a merge message.

- The output directory contains exactly one workbook slug for that EPUB under:
  - `intermediate drafts/`
  - `final drafts/`
  - `tips/`
  - and a single report file.

2) Merged identifiers are stable and sequential.

- Recipe identifiers in the final merged output are sequential (`...:c0`, `...:c1`, …) and do not depend on whether splitting occurred.
- Any recipe-specific tips reference the rewritten recipe IDs.

3) Overlap does not produce duplicates.

- The final merged output contains no duplicate recipes caused by overlap slices.

4) Serial fallback works.

- If `ProcessPoolExecutor` cannot be created (for example due to `PermissionError`), the CLI logs a warning and processes the EPUB as one non-split job, still producing a valid workbook output.

5) Tests cover the new behavior.

- New tests fail before the change and pass after. At minimum:
  - job planning ranges
  - owned-range filtering
  - merge ID rewriting and reference updates

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging. Re-run to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error record, while allowing other files in the same run to complete.

If splitting causes unexpected extraction regressions on a particular EPUB, users can disable splitting by running with `--workers 1` or by setting `--epub-spine-items-per-job` to a very large number so the file is not split.

## Artifacts and Notes

Keep the following evidence snippets here as you implement:

- A short `pytest` transcript showing new tests passing.
- A run transcript showing split job progress and a merge line.
- A tiny excerpt of one merged recipe JSON showing `identifier` rewritten to `...:c{n}` and a recipe-specific tip referencing the new ID.

Example (replace with real output):

    pytest -q
    ... 128 passed

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub
    Processing 1 file(s) as 4 job(s) using 4 workers...
    Merging 4 jobs for large.epub...
    ✔ large.epub: 312 recipes, 28 tips

## Interfaces and Dependencies

You must end with these concrete interfaces (update names to match the existing job framework you reuse):

- `cookimport/plugins/epub.py`
  - `EpubImporter.inspect(path) -> WorkbookInspection` (or equivalent) must populate an integer spine item count field.
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None, owned_start_spine: int | None = None, owned_end_spine: int | None = None) -> ConversionResult`
  - Every produced `Block` must carry absolute `spine_index` in provenance location (field name to be chosen and documented in Decision Log).
- `cookimport/cli.py`
  - New CLI flags: `--epub-spine-items-per-job`, `--epub-spine-overlap-items`.
  - Job planner must create an “epub spine slice” job kind when conditions are met.
  - Merge orchestration must recognize EPUB split jobs and write one workbook output in the main process.
- `cookimport/cli_worker.py`
  - Worker entrypoint must accept EPUB slice jobs and return a mergeable job payload while writing raw artifacts into `.job_parts` for those jobs.
- Tests
  - At least one new test file covering EPUB job planning and merge ID rewriting.

Change note: 2026-02-01 — Initial ExecPlan created to extend the existing PDF split/merge job framework to `.epub` spine slicing with overlap filtering and deterministic merging.
