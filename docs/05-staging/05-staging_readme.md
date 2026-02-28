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
  - Applies deterministic fallback instruction-step segmentation from run settings before section extraction/step parsing.
- `cookimport/staging/writer.py`
  - Writes intermediate/final outputs, section artifacts, tips, topic candidates, chunks, raw artifacts, and report JSON.
  - Generates/stabilizes IDs where needed.
- `cookimport/staging/stage_block_predictions.py`
  - Builds deterministic block-level benchmark evidence labels (`stage_block_predictions.v1`) from staged recipes + archive blocks + knowledge hints.
- `cookimport/staging/pdf_jobs.py`
  - Split-job helpers: range planning and post-merge recipe/tip ID reassignment by source order.
- `cookimport/cli_worker.py`
  - Main single-file stage flow uses writer functions.
- `cookimport/cli.py`
  - Multi-job merge flow for split PDF/EPUB runs; offsets split block provenance, writes merged outputs, merges per-job raw artifacts, and emits run-level manifest/index artifacts.
- `cookimport/runs/manifest.py`
  - Defines/stores `run_manifest.json` written by stage/pred-run flows for source identity + artifact indexing.
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
- `.bench/<workbook_slug>/p6_metadata_debug.jsonl` (optional Priority 6 parser/yield diagnostics; only when `p6_emit_metadata_debug=true`)
- `tags/<workbook_slug>/r{index}.tags.json` (if pass5 tags pipeline is enabled)
- `tags/<workbook_slug>/tagging_report.json` (if pass5 tags pipeline is enabled)
- `tags/tags_index.json` (if any pass5 tag artifacts were written in the run)
- `raw/<importer>/<source_hash>/<location_id>.<ext>` (if any)
  - includes `recipe_scoring_debug.jsonl` when importers emit candidate gate decisions
- `raw/llm/<workbook_slug>/pass5_tags/in/*.json` + `out/*.json` + `pass5_tags_manifest.json` (if pass5 tags pipeline is enabled)
- `<workbook_slug>.excel_import_report.json` at run root
- `processing_timeseries.jsonl` at run root (stage status snapshots + CPU utilization samples)
- `run_manifest.json` at run root (source identity + artifact index for this stage run)

Report contract note:
- `<workbook_slug>.excel_import_report.json` can include `recipeLikeness` summary (backend/version, thresholds, tier counts, score stats, rejected count).

Outside run root (`data/output/.history/`):

- `performance_history.csv` is appended after stage runs when perf summary generation succeeds.

Code pointers (prefer these over line numbers, which drift often):

- `cookimport/cli_worker.py` (`stage_one_file`) and `cookimport/cli.py` (`_merge_split_jobs`) assemble per-run output dirs and invoke staging writers.
- `cookimport/staging/writer.py` (`write_intermediate_outputs`, `write_draft_outputs`, `write_section_outputs`, `write_tip_outputs`, `write_topic_candidate_outputs`, `write_chunk_outputs`, `write_table_outputs`, `write_raw_artifacts`, `write_stage_block_predictions`, `write_report`) implements the file layout above.
- `cookimport/cli.py` (`_write_knowledge_index_best_effort`, `_write_stage_run_manifest`) and `cookimport/tagging/orchestrator.py` (`run_stage_tagging_pass`) add run-level index/manifest artifacts.

Stage-block `KNOWLEDGE` label contract:
- `stage_block_predictions.json` prefers pass4 snippet evidence when available.
- If pass4 knowledge harvesting is off (or snippets are absent), `KNOWLEDGE` labeling falls back to deterministic chunk-lane mapping so benchmark evidence stays complete.

Stage-block label resolution contract:
- `stage_block_predictions.py` labels blocks from recipe-local text matches (title, ingredients, instructions, notes, variant/yield/time lines).
- `stage_block_predictions.py` emits `HOWTO_SECTION` for deterministic ingredient/instruction section-header hits (`extract_ingredient_sections`, `extract_instruction_sections`) when nearby recipe-structure signals are present.
- `RECIPE_NOTES` evidence merges schema `comment` rows with recipe-specific notes deterministically extracted from `description` (`extract_recipe_specific_notes`).
- If ingredient/instruction exact/fuzzy matching misses, it falls back to extracted archive `block_role` hints (`ingredient_line`, `instruction_line`).
- Multi-label conflicts resolve by fixed priority (`RECIPE_VARIANT` > `RECIPE_TITLE` > `YIELD_LINE` > `TIME_LINE` > `HOWTO_SECTION` > `INGREDIENT_LINE` > `RECIPE_NOTES` > `INSTRUCTION_LINE` > `KNOWLEDGE`).
- If a block has both `KNOWLEDGE` and recipe-local labels, recipe-local label wins.
- Recipe-local stage labeling can derive block ranges from provenance line ranges (`start_line`/`end_line`) when explicit block ranges are absent (for example text-import paths).

## Intermediate JSON-LD Section Behavior

- `cookimport/staging/jsonld.py` now removes detected instruction section headers from literal step text.
- `cookimport/staging/jsonld.py`, `cookimport/staging/draft_v1.py`, and `write_section_outputs(...)` now consume the same effective instruction segmentation settings (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) so step boundaries stay aligned across outputs.
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
- Non-linked output lines allow only `quantity_kind` values `exact`, `approximate`, or `unquantified`.
- Non-linked `exact`/`approximate` lines require positive `input_qty`; otherwise they are downgraded to `unquantified`.
- Non-linked `unquantified` lines must have `input_qty = null` and `input_unit_id = null`.
- Blank `linked_recipe_id` values are cleared so lines do not violate one-of reference rules.
- Linked-recipe lines force `ingredient_id = null` and `input_unit_id = null`.
- Linked-recipe multipliers keep positive `input_qty` values and cap them at `100`; missing/non-positive values normalize to `null`.
- Linked-recipe lines normalize invalid/missing `quantity_kind` values to `exact`.
- For unresolved units, `input_unit_id` is always set to `null` (raw unit text retained in `raw_unit_text`).
- For unresolved non-linked ingredients, `ingredient_id` must be non-empty string; fallback uses `raw_ingredient_text`, then `raw_text`, then sentinel `__missing_ingredient__`.
- Ingredient parsing now consumes run-config parser knobs (`ingredient_*` settings), so missing-unit policy/backend/packaging options selected for stage/prediction imports directly affect final draft ingredient lines.
- Instruction fallback segmentation now consumes run-config knobs (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) before section extraction and variant splitting.
- Priority 6 parser/yield options now consume run-config `p6_*` knobs (time strategy/backend, temperature extraction/unit conversion, oven-like mode, yield mode).

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

### Additional draft-v1 behaviors that affect downstream consumers

- Ingredient text fields are lowercased in final draft output:
  - `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note`
- Variant extraction removes instruction lines that are variation headers/prefixes and stores them under `recipe.variants`.
- If no instructions remain, fallback step is injected: `See original recipe for details.`
- Unassigned ingredients create prep step at beginning: `Gather and prepare ingredients.`
- Step time metadata from instruction parser is rolled up to `cook_time_seconds` when recipe cook time is missing.
- Step temperatures now preserve `temperature_items` arrays when available (legacy `temperature`/`temperature_unit` fields remain for compatibility).
- Recipe-level `max_oven_temp_f` is emitted from oven-like step temperature metadata when available.
- Yield fields (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`) now come from centralized deterministic yield extraction (`legacy_v1` passthrough or `scored_v1`).
- When `p6_emit_metadata_debug=true`, draft conversion emits `_p6_debug` internally and writer strips it from final `r{index}.json` while writing `.bench/<workbook_slug>/p6_metadata_debug.jsonl`.
- Blank recipe titles are normalized to `Untitled Recipe`.
- Blank `source` values are normalized to `null` to satisfy staging schema min-length rules.

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

## Split-Job Merge Behavior (PDF/EPUB)

When PDFs/EPUBs are split into jobs, merge flow:

1. Collects all job results.
2. Sorts jobs by start range.
3. When split jobs include `full_text` raw artifacts, builds merged `raw/.../full_text.json` block payload and offsets per-job block indices in recipe/tip/topic/non-recipe provenance to global coordinates.
4. Reassigns recipe IDs in source order (`start_spine` first, then `start_page`, then `start_block`).
5. Updates tip references (`source_recipe_id`, provenance IDs) via remap.
6. Writes merged outputs through standard writer functions.
7. Writes stage-block predictions using merged archive blocks so block labels align with global block indices.
8. Moves raw artifacts from temporary `.job_parts/<workbook_slug>/job_{i}/raw/...` into final `raw/...` path.
   - Per-job `recipe_scoring_debug.jsonl` collisions are preserved via deterministic `job_{index}_...` prefixing.
9. Writes report JSON after raw merge so `outputStats` includes moved raw artifacts (plus merged `raw/.../full_text.json`) without a post-write directory scan.

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

## Run manifest contract

`run_manifest.json` is a required stage-run index written after stage outputs finish.

- Includes source identity (`path`, optional `source_hash`, detected `importer_name`).
- Includes run config snapshot used for the run.
- Includes artifact pointers for reports, stage-block predictions, knowledge/tag indexes, and processing telemetry when present.
- Used by parity tests and downstream tooling to compare stage and pred-run provenance/config.

Code pointers:
- `cookimport/cli.py` (`_write_stage_run_manifest`, `_write_run_manifest_best_effort`)
- `cookimport/runs/manifest.py` (`RunManifest`, `write_run_manifest`)

## Current limitations / things we know are not great yet

1. Lowercasing is lossy by design
- Improves normalization but may remove intentional capitalization in ingredient text fields.
- This is currently tested behavior, not an accidental bug.

2. Split-job raw artifact filename collisions are auto-prefixed
- Merge may rename colliding files with `job_{index}_...` prefixes.
- Good for loss avoidance, but file names can differ run-to-run when collisions happen.
- Code pointers: `cookimport/cli.py` (`_merge_raw_artifacts`, `_prefix_collision`).

3. Timestamp output folder granularity is seconds
- Two invocations in the same second could collide on output directory name.
- Current behavior uses `%Y-%m-%d_%H.%M.%S`.
- Code pointer: `cookimport/cli.py` (run root timestamp uses `%Y-%m-%d_%H.%M.%S` in multiple stage entrypoints).

## Test coverage tied to staging contracts

Core tests to keep green when touching staging:

- `tests/cli/test_cli_output_structure.py`
- `tests/staging/test_draft_v1_staging_alignment.py`
- `tests/staging/test_draft_v1_lowercase.py`
- `tests/staging/test_draft_v1_variants.py`
- `tests/staging/test_tip_writer.py`
- `tests/staging/test_split_merge_status.py`
- `tests/staging/test_section_outputs.py`
- `tests/staging/test_stage_block_predictions.py`
- `tests/staging/test_run_manifest_parity.py`
- `tests/parsing/test_source_field.py`
- `tests/ingestion/test_pdf_job_merge.py`
- `tests/ingestion/test_epub_job_merge.py`

## Practical “change checklist” for future work

When editing staging behavior, confirm:

1. Path layout and naming in CLI help/docs still match writes.
2. Draft ingredient-line invariants remain staging-safe.
3. Unresolved ID handling remains placeholder/null pattern.
4. Split-job merge still preserves deterministic order and tip references.
5. Tips/topic candidates/chunks/raw/report outputs still land in expected paths.
6. Output stats reporting remains attached to report (`outputStats`) when files are written.
7. `run_manifest.json` still captures source identity + artifact paths for this run.

## Related docs

- Ingestion details feeding staging: `docs/03-ingestion/03-ingestion_readme.md`
- Parsing behavior feeding staging normalization: `docs/04-parsing/04-parsing_readme.md`
- Metrics and report surfaces consuming staging outputs: `docs/08-analytics/08-analytics_readme.md`

## Additional Cookbook Contract Edge Cases (Merged 2026-02-20_12.46.28)

These invariants are easy to miss because outputs can look structurally valid while still failing Cookbook staging validation:

- `source` must be `null` when blank; empty string is rejected.
- For linked-recipe ingredient lines:
  - blank `linked_recipe_id` must normalize to `null`,
  - positive `input_qty` values are capped at `100` (missing/non-positive values normalize to `null`),
  - `input_unit_id` and `ingredient_id` should remain `null`.

Treat these as mandatory shaping rules in `recipe_candidate_to_draft_v1(...)`, not optional cleanup.

## 2026-02-27 Merged Understandings: Staging Docs Contract Refresh

Merged source notes:
- `docs/understandings/2026-02-27_19.47.49-staging-doc-prune-current-contracts.md`
- `docs/understandings/2026-02-27_19.53.48-staging-doc-code-coverage-refresh.md`

Current-contract additions:
- Stage docs must include `run_manifest.json` as a required stage artifact.
- Stage-block documentation should cover builder behavior in `cookimport/staging/stage_block_predictions.py` (text matching, fallback roles, deterministic conflict priority), not only artifact paths.
- Split-merge docs should explicitly include block-index offset handling and merged `raw/.../full_text.json` normalization so Label Studio alignment remains valid.
- Ingredient-under-count limitation text was retired: current draft conversion tracks unassigned ingredients by `ingredient_index` from assignment debug data.
- Linked-recipe quantity docs should reflect current sanitize behavior: positive values are capped at `100`, missing/non-positive values normalize to `null`.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_20.39.35 recipe notes label intent vs stage comments source
- Source: `docs/understandings/2026-02-27_20.39.35-recipe-notes-label-intent-vs-stage-comments-source.md`
- Summary: RECIPE_NOTES is intended for recipe-local tips/notes, but stage block predictions currently source it only from recipe.comment fields.

### 2026-02-27_20.44.19 stage block recipe notes description source enabled
- Source: `docs/understandings/2026-02-27_20.44.19-stage-block-recipe-notes-description-source-enabled.md`
- Summary: Stage block prediction now sources RECIPE_NOTES from both schema comments and description-derived recipe-specific notes.

### 2026-02-27_22.43.10 priority4 ingredient options wiring path
- Source: `docs/understandings/2026-02-27_22.43.10-priority4-ingredient-options-wiring-path.md`
- Summary: Priority-4 discovery: ingredient parser settings must be threaded at draft-write time, not importer convert time.

### 2026-02-27_23.17.42 priority5 shared instruction shaping path
- Source: `docs/understandings/2026-02-27_23.17.42-priority5-shared-instruction-shaping-path.md`
- Summary: Priority-5 implementation note: stage draft/jsonld/sections must all consume one shared effective instruction-shaping path, wired from RunSettings through stage + pred-run flows.

### 2026-02-28_00.42.17 howto section auto-emission gap audit
- Source: `docs/understandings/2026-02-28_00.42.17-howto-section-auto-emission-gap-audit.md`
- Summary: Captured remaining gap for emitting `HOWTO_SECTION` labels in importer-side stage-block predictions (before auto-emission was implemented).

### 2026-02-28_00.54.00 stage block howto emission range and remap notes
- Source: `docs/understandings/2026-02-28_00.54.00-stage-block-howto-emission-range-and-remap-notes.md`
- Summary: Documented the fix shape for line-range provenance mapping and prediction-side `HOWTO_SECTION` remap parity required for benchmark-safe auto-emission.

## 2026-02-28 task consolidation (migrated from `docs/tasks`)

### 2026-02-28_00.42.17 deterministic importer-side `HOWTO_SECTION` auto-emission
- Source task: `docs/tasks/2026-02-28_00.42.17-howto-section-importer-auto-emission.md`
- Current staging contract:
  - `cookimport/staging/stage_block_predictions.py` emits `HOWTO_SECTION` deterministically from ingredient/instruction section-header evidence.
  - Recipe-local labeling now falls back from block ranges to provenance line ranges (`start_line`/`end_line`) when needed, so text-import recipes are no longer forced to all-`OTHER`.
  - Conflict priority preserves `HOWTO_SECTION` when header lines also match structural ingredient/instruction heuristics.
- Benchmark parity note:
  - Scoring-side `HOWTO_SECTION` remap is handled in benchmark evaluators before metrics (`docs/07-bench/07-bench_README.md`), so staging can emit richer labels without shifting structural metric semantics.
- Durable gotcha:
  - Per-label benchmark counters can show `HOWTO_SECTION.pred_total == 0` in structural reports because predictions are resolved to ingredient/instruction classes before scoring by design.
