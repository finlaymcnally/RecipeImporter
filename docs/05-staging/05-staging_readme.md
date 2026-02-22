---
summary: "Code-verified staging/output reference focused on current behavior, contracts, and regression-sensitive boundaries."
read_when:
  - When changing output paths, filenames, IDs, or report artifacts
  - When modifying draft-v1 conversion or Cookbook staging contract invariants
  - When debugging split-job merge output ordering/raw artifacts (use 05-staging_log.md for historical attempts)
---

# 05 Staging: System Reference

This file is the source of truth for current staging behavior.

Historical architecture versions, builds, and fix attempts live in `docs/05-staging/05-staging_log.md`.

## Why This Exists

Staging is the boundary between importer/parsing internals and persisted artifacts used by downstream tools (Cookbook staging import, Label Studio helpers, tagging, analytics). Small output-shape drift here causes expensive rework across the pipeline.

## What This Covers

- Where staged artifacts are written
- How IDs/provenance are generated and stabilized
- Cookbook staging contract invariants enforced in draft-v1 shaping
- Split-job merge behavior for PDF/EPUB inputs
- Current limitations and regression-sensitive paths
- Tests that should stay green when touching staging

## History and Prior Attempts

- Architecture versions, build notes, and fix attempts: `docs/05-staging/05-staging_log.md`
- If debugging starts looping, check the log first before trying a new approach.

## Where Staging Logic Lives

- `cookimport/staging/jsonld.py`
  - Intermediate conversion from `RecipeCandidate` to schema.org `Recipe` JSON-LD (+ `recipeimport:*` metadata).
- `cookimport/staging/draft_v1.py`
  - Final conversion to cookbook3 output shape (internal model label still `RecipeDraftV1`).
  - Applies staging safety normalization for ingredient lines.
- `cookimport/staging/writer.py`
  - Writes intermediate/final outputs, tips, topic candidates, chunks, raw artifacts, and report JSON.
  - Generates/stabilizes IDs where needed.
- `cookimport/staging/pdf_jobs.py`
  - Split-job helpers: range planning and post-merge recipe/tip ID reassignment by source order.
- `cookimport/cli_worker.py`
  - Main single-file stage flow uses writer functions.
- `cookimport/cli.py`
  - Multi-job merge flow for split PDF/EPUB runs; writes merged outputs and merges per-job raw artifacts.
- `cookimport/labelstudio/ingest.py`
  - Reuses same writer flow for processed output snapshots used in LS workflows.

## Canonical Naming Conventions (User-Facing)

From prior task docs, still valid in current CLI/docs:

- `RecipeSage` is an importer/source label, not the canonical intermediate format name.
- Intermediate outputs are described as `schema.org Recipe JSON`.
- Final outputs are described as `cookbook3`.
- `RecipeDraftV1` is an internal model identifier and can appear in code/tests, but user-facing text should prefer `cookbook3`.

## Output Layout and File Names (Current Behavior)

Per run, output root:

- `data/output/<timestamp>/`

Per workbook (slugified file stem):

- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `tips/<workbook_slug>/t{index}.json`
- `tips/<workbook_slug>/tips.md`
- `tips/<workbook_slug>/topic_candidates.json` (if any)
- `tips/<workbook_slug>/topic_candidates.md` (if any)
- `chunks/<workbook_slug>/c{index}.json` (if any)
- `chunks/<workbook_slug>/chunks.md` (if any)
- `raw/<importer>/<source_hash>/<location_id>.<ext>` (if any)
- `<workbook_slug>.excel_import_report.json` at run root

Code refs:

- `cookimport/cli.py:1515`
- `cookimport/cli_worker.py:198`
- `cookimport/staging/writer.py:275`
- `cookimport/staging/writer.py:308`
- `cookimport/staging/writer.py:331`
- `cookimport/staging/writer.py:396`
- `cookimport/staging/writer.py:611`
- `cookimport/staging/writer.py:668`
- `cookimport/staging/writer.py:686`

## ID and Provenance Behavior in Staging

### Recipe IDs

- Intermediate writer ensures candidate IDs exist (`@id`) before JSON-LD write.
- Fallback stable pattern when unresolved: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`.
- If `candidate.identifier` exists, it is used.

Code refs:

- `cookimport/staging/writer.py:209`
- `cookimport/staging/writer.py:275`

### Tip/topic IDs

- Tip fallback ID pattern: `urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{row_index}:{tip_index}`.
- Topic fallback ID pattern: `urn:recipeimport:topic:{file_hash}:{sheet_slug}:tc{row_index}:{topic_index}`.

Code refs:

- `cookimport/staging/writer.py:227`
- `cookimport/staging/writer.py:247`

### Row index fallback rule (important for non-tabular sources)

Row index resolution checks provenance keys in this order:

1. `row_index` / `rowIndex` / `row`
2. `location.row_index` / `location.rowIndex` / `location.row`
3. `location.chunk_index` / `location.chunkIndex` / `location.chunk`

This fallback is what keeps stable-ish IDs for text/PDF/EPUB when row semantics do not exist.

Code ref:

- `cookimport/staging/writer.py:180`

## Draft-v1 (Cookbook3) Contract Shaping

`recipe_candidate_to_draft_v1()` is where staging contract safety is enforced.

### Ingredient line normalization rules

Current enforced behavior:

- `section_header` lines are dropped from output lines.
- Allowed output `quantity_kind`: `exact`, `approximate`, `unquantified`.
- `exact`/`approximate` lines require positive `input_qty`; otherwise they are downgraded to `unquantified`.
- `unquantified` lines must have `input_qty = null` and `input_unit_id = null`.
- Blank `linked_recipe_id` values are cleared so lines do not violate one-of reference rules.
- Recipe-line multipliers (`linked_recipe_id` + `input_qty`) are capped at `100` to satisfy Cookbook staging validation.
- For unresolved units, `input_unit_id` is always set to `null` (raw unit text retained in `raw_unit_text`).
- For unresolved ingredients, `ingredient_id` must be non-empty string; fallback uses `raw_ingredient_text`, then `raw_text`, then sentinel `__missing_ingredient__`.

Code refs:

- `cookimport/staging/draft_v1.py:39`
- `cookimport/staging/draft_v1.py:79`
- `cookimport/staging/draft_v1.py:94`
- `cookimport/staging/draft_v1.py:108`

### Additional draft-v1 behaviors that affect downstream consumers

- Ingredient text fields are lowercased in final draft output:
  - `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note`
- Variant extraction removes instruction lines that are variation headers/prefixes and stores them under `recipe.variants`.
- If no instructions remain, fallback step is injected: `See original recipe for details.`
- Unassigned ingredients create prep step at beginning: `Gather and prepare ingredients.`
- Step time metadata from instruction parser is rolled up to `cook_time_seconds` when recipe cook time is missing.
- Blank recipe titles are normalized to `Untitled Recipe`.
- Blank `source` values are normalized to `null` to satisfy staging schema min-length rules.

Code refs:

- `cookimport/staging/draft_v1.py:15`
- `cookimport/staging/draft_v1.py:118`
- `cookimport/staging/draft_v1.py:129`
- `cookimport/staging/draft_v1.py:166`

## Split-Job Merge Behavior (PDF/EPUB)

When PDFs/EPUBs are split into jobs, merge flow:

1. Collects all job results.
2. Sorts jobs by start range.
3. Reassigns recipe IDs in source order (`start_spine` first, then `start_page`, then `start_block`).
4. Updates tip references (`source_recipe_id`, provenance IDs) via remap.
5. Writes merged outputs through standard writer functions.
6. Moves raw artifacts from temporary `.job_parts/<workbook_slug>/job_{i}/raw/...` into final `raw/...` path.

Main-process merge status callback contract:

- Status text is phase-counted as `merge phase X/Y: <label>`.
- Phase totals are deterministic for a run and include optional chunk-write phase when chunk sources exist.

Code refs:

- `cookimport/cli.py:1260`
- `cookimport/cli.py:1203`
- `cookimport/staging/pdf_jobs.py:38`
- `cookimport/staging/pdf_jobs.py:76`

## Current limitations / things we know are not great yet

1. Duplicate ingredient text can be undercounted in unassigned detection
- `recipe_candidate_to_draft_v1()` tracks assigned ingredients by `raw_ingredient_text` set membership.
- If duplicate lines share same text, one assignment can make another appear assigned.
- Code ref: `cookimport/staging/draft_v1.py:236`.

2. Lowercasing is lossy by design
- Improves normalization but may remove intentional capitalization in ingredient text fields.
- This is currently tested behavior, not an accidental bug.

3. Split-job raw artifact filename collisions are auto-prefixed
- Merge may rename colliding files with `job_{index}_...` prefixes.
- Good for loss avoidance, but file names can differ run-to-run when collisions happen.
- Code ref: `cookimport/cli.py:1230`.

4. Timestamp output folder granularity is seconds
- Two invocations in the same second could collide on output directory name.
- Current behavior uses `%Y-%m-%d_%H.%M.%S`.
- Code ref: `cookimport/cli.py:1538`.

## Test coverage tied to staging contracts

Core tests to keep green when touching staging:

- `tests/test_cli_output_structure.py`
- `tests/test_draft_v1_staging_alignment.py`
- `tests/test_draft_v1_lowercase.py`
- `tests/test_draft_v1_variants.py`
- `tests/test_tip_writer.py`
- `tests/test_source_field.py`
- `tests/test_pdf_job_merge.py`
- `tests/test_epub_job_merge.py`

## Practical “change checklist” for future work

When editing staging behavior, confirm:

1. Path layout and naming in CLI help/docs still match writes.
2. Draft ingredient-line invariants remain staging-safe.
3. Unresolved ID handling remains placeholder/null pattern.
4. Split-job merge still preserves deterministic order and tip references.
5. Tips/topic candidates/chunks/raw/report outputs still land in expected paths.
6. Output stats reporting remains attached to report (`outputStats`) when files are written.

## Related docs

- Ingestion details feeding staging: `docs/03-ingestion/03-ingestion_readme.md`
- Parsing behavior feeding staging normalization: `docs/04-parsing/04-parsing_readme.md`
- Metrics and report surfaces consuming staging outputs: `docs/08-analytics/08-analytics_readme.md`

## Additional Cookbook Contract Edge Cases (Merged 2026-02-20_12.46.28)

These invariants are easy to miss because outputs can look structurally valid while still failing Cookbook staging validation:

- `source` must be `null` when blank; empty string is rejected.
- For linked-recipe ingredient lines:
  - blank `linked_recipe_id` must normalize to `null`,
  - `input_qty` must remain `> 0` and `<= 100`,
  - `input_unit_id` should remain `null`.

Treat these as mandatory shaping rules in `recipe_candidate_to_draft_v1(...)`, not optional cleanup.
