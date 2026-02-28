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
  - Writes intermediate/final outputs, section artifacts, tips, topic candidates, chunks, raw artifacts, and report JSON.
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
- `sections/<workbook_slug>/r{index}.sections.json`
- `sections/<workbook_slug>/sections.md` (default; skipped with `stage --no-write-markdown`)
- `tips/<workbook_slug>/t{index}.json`
- `tips/<workbook_slug>/tips.md` (default; skipped with `stage --no-write-markdown`)
- `tips/<workbook_slug>/topic_candidates.json` (if any)
- `tips/<workbook_slug>/topic_candidates.md` (if any; skipped with `stage --no-write-markdown`)
- `chunks/<workbook_slug>/c{index}.json` (if any)
- `chunks/<workbook_slug>/chunks.md` (if any; skipped with `stage --no-write-markdown`)
- `tables/<workbook_slug>/tables.jsonl` and `tables/<workbook_slug>/tables.md` (when `table_extraction=on`; `tables.md` skipped with `stage --no-write-markdown`)
- `knowledge/<workbook_slug>/snippets.jsonl` (if pass4 knowledge harvesting is enabled)
- `knowledge/<workbook_slug>/knowledge.md` (if pass4 knowledge harvesting is enabled)
- `knowledge/knowledge_index.json` (if any knowledge artifacts were written in the run)
- `.bench/<workbook_slug>/stage_block_predictions.json` (deterministic block-level benchmark evidence)
- `tags/<workbook_slug>/r{index}.tags.json` (if pass5 tags pipeline is enabled)
- `tags/<workbook_slug>/tagging_report.json` (if pass5 tags pipeline is enabled)
- `tags/tags_index.json` (if any pass5 tag artifacts were written in the run)
- `raw/<importer>/<source_hash>/<location_id>.<ext>` (if any)
- `raw/llm/<workbook_slug>/pass5_tags/in/*.json` + `out/*.json` + `pass5_tags_manifest.json` (if pass5 tags pipeline is enabled)
- `<workbook_slug>.excel_import_report.json` at run root
- `processing_timeseries.jsonl` at run root (stage status snapshots + CPU utilization samples)

Code pointers (prefer these over line numbers, which drift often):

- `cookimport/cli_worker.py` (`stage_one_file`) and `cookimport/cli.py` (`_merge_split_jobs`) assemble per-run output dirs and invoke staging writers.
- `cookimport/staging/writer.py` (`write_intermediate_outputs`, `write_draft_outputs`, `write_section_outputs`, `write_tip_outputs`, `write_topic_candidate_outputs`, `write_chunk_outputs`, `write_table_outputs`, `write_raw_artifacts`, `write_report`) implements the file layout above.

Stage-block `KNOWLEDGE` label contract:
- `stage_block_predictions.json` prefers pass4 snippet evidence when available.
- If pass4 knowledge harvesting is off (or snippets are absent), `KNOWLEDGE` labeling falls back to deterministic chunk-lane mapping so benchmark evidence stays complete.

## Intermediate JSON-LD Section Behavior

- `cookimport/staging/jsonld.py` now removes detected instruction section headers from literal step text.
- When multiple instruction sections are detected, `recipeInstructions` is emitted as `HowToSection` objects with `itemListElement` `HowToStep` entries.
- Ingredient section groupings are emitted in custom metadata:
  - `recipeimport:ingredientSections` with `name`, `key`, and grouped `recipeIngredient` lines.
- Final cookbook3 (`draft_v1`) shape is unchanged; this richer structure is intermediate-only.

## ID and Provenance Behavior in Staging

### Recipe IDs

- Intermediate writer ensures candidate IDs exist (`@id`) before JSON-LD write.
- Fallback stable pattern when unresolved: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`.
- If `candidate.identifier` exists, it is used.

Code pointers:

- `cookimport/staging/writer.py` (`_ensure_candidate_id`, `write_intermediate_outputs`, `write_draft_outputs`)

### Tip/topic IDs

- Tip fallback ID pattern: `urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{row_index}:{tip_index}`.
- Topic fallback ID pattern: `urn:recipeimport:topic:{file_hash}:{sheet_slug}:tc{row_index}:{topic_index}`.

Code pointers:

- `cookimport/staging/writer.py` (`_ensure_tip_id`, `_ensure_topic_id`)

### Row index fallback rule (important for non-tabular sources)

Row index resolution checks provenance keys in this order:

1. `row_index` / `rowIndex` / `row`
2. `location.row_index` / `location.rowIndex` / `location.row`
3. `location.chunk_index` / `location.chunkIndex` / `location.chunk`

This fallback is what keeps stable-ish IDs for text/PDF/EPUB when row semantics do not exist.

Code pointer:

- `cookimport/staging/writer.py` (`_resolve_row_index`)

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

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

### Additional draft-v1 behaviors that affect downstream consumers

- Ingredient text fields are lowercased in final draft output:
  - `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note`
- Variant extraction removes instruction lines that are variation headers/prefixes and stores them under `recipe.variants`.
- If no instructions remain, fallback step is injected: `See original recipe for details.`
- Unassigned ingredients create prep step at beginning: `Gather and prepare ingredients.`
- Step time metadata from instruction parser is rolled up to `cook_time_seconds` when recipe cook time is missing.
- Blank recipe titles are normalized to `Untitled Recipe`.
- Blank `source` values are normalized to `null` to satisfy staging schema min-length rules.

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

## Split-Job Merge Behavior (PDF/EPUB)

When PDFs/EPUBs are split into jobs, merge flow:

1. Collects all job results.
2. Sorts jobs by start range.
3. Reassigns recipe IDs in source order (`start_spine` first, then `start_page`, then `start_block`).
4. Updates tip references (`source_recipe_id`, provenance IDs) via remap.
5. Writes merged outputs through standard writer functions.
6. Moves raw artifacts from temporary `.job_parts/<workbook_slug>/job_{i}/raw/...` into final `raw/...` path.
7. Writes report JSON after raw merge so `outputStats` includes moved raw artifacts (plus merged `raw/.../full_text.json`) without a post-write directory scan.

### Split-merge outputStats invariants (merged 2026-02-27)

When touching split merge, keep this ordering and accounting contract:

- record merged `raw/.../full_text.json` in output stats when written,
- record each moved raw destination during `_merge_raw_artifacts(...)`,
- write report after raw merge completes.

Guardrail test:
- `tests/staging/test_split_merge_status.py::test_merge_split_jobs_output_stats_match_fresh_directory_walk`
  compares report `outputStats` against a fresh categorized directory walk.

Main-process merge status callback contract:

- Status text is phase-counted as `merge phase X/Y: <label>`.
- Phase totals are deterministic for a run and include optional chunk-write phase when chunk sources exist.

Code pointers:

- `cookimport/cli.py` (`_merge_split_jobs`, `_merge_raw_artifacts`)
- `cookimport/staging/pdf_jobs.py` (`reassign_recipe_ids`)

## Current limitations / things we know are not great yet

1. Duplicate ingredient text can be undercounted in unassigned detection
- `recipe_candidate_to_draft_v1()` tracks assigned ingredients by `raw_ingredient_text` set membership.
- If duplicate lines share same text, one assignment can make another appear assigned.
- Code pointer: `cookimport/staging/draft_v1.py` (unassigned ingredient detection after step assignment).

2. Lowercasing is lossy by design
- Improves normalization but may remove intentional capitalization in ingredient text fields.
- This is currently tested behavior, not an accidental bug.

3. Split-job raw artifact filename collisions are auto-prefixed
- Merge may rename colliding files with `job_{index}_...` prefixes.
- Good for loss avoidance, but file names can differ run-to-run when collisions happen.
- Code pointers: `cookimport/cli.py` (`_merge_raw_artifacts`, `_prefix_collision`).

4. Timestamp output folder granularity is seconds
- Two invocations in the same second could collide on output directory name.
- Current behavior uses `%Y-%m-%d_%H.%M.%S`.
- Code pointer: `cookimport/cli.py` (run root timestamp uses `%Y-%m-%d_%H.%M.%S` in multiple stage entrypoints).

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
