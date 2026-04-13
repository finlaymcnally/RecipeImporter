---
summary: "Code-verified staging/output reference focused on current behavior, contracts, and regression-sensitive boundaries."
read_when:
  - When changing output paths, filenames, IDs, or report artifacts
  - When modifying draft-v1 conversion or Cookbook staging contract invariants
  - When debugging split-job merge output ordering/raw artifacts
---

# 05 Staging: System Reference

This file is the source of truth for current staging behavior.

## Why This Exists

Staging is the boundary between importer/parsing internals and persisted artifacts used by downstream tools (Cookbook staging import, Label Studio helpers, tagging, analytics). Small output-shape drift here causes expensive rework across the pipeline.

## What This Covers

- Where staged artifacts are written
- How IDs/provenance are generated and stabilized
- Cookbook staging contract invariants enforced in draft-v1 shaping
- Split-job merge behavior for PDF/EPUB inputs
- Current limitations and regression-sensitive paths
- Tests that should stay green when touching staging

## Where Staging Logic Lives

- `cookimport/staging/jsonld.py`
  - Intermediate conversion from canonical recipe semantics into schema.org `Recipe` JSON-LD (+ `recipeimport:*` metadata), with `RecipeCandidate` still acting as the source-adapter for non-semantic fields such as image and publication metadata.
- `cookimport/staging/draft_v1.py`
  - Final conversion from canonical recipe semantics to cookbook3 output shape (internal model label still `RecipeDraftV1`).
  - Applies staging safety normalization for ingredient lines.
  - Builds the canonical `AuthoritativeRecipeSemantics` payload from a deterministic recipe or recipe-Codex correction result, then projects cookbook3 from that payload without re-running semantic note/variant/link decisions later in writer code.
- `cookimport/staging/nonrecipe_authority_contract.py`
  - Canonical non-recipe contract/result types, including the strict-authority vs late-output split now read by stage and Label Studio flows.
- `cookimport/staging/nonrecipe_seed.py`, `nonrecipe_routing.py`, `nonrecipe_authority.py`, `nonrecipe_finalize_status.py`
  - Small owners for seed spans, review-queue routing, final authority, late-output/scoring views, and reviewed/unreviewed bookkeeping.
- `cookimport/staging/nonrecipe_stage.py`
  - Thin public seam that assembles the owner modules above into the non-recipe route/final-authority runtime result.
- `cookimport/staging/recipe_ownership.py`
  - Canonical recipe-owned block contract/result types, explicit divestment helpers, and the persisted `recipe_block_ownership.json` artifact shape.
- `cookimport/staging/pipeline_runtime.py`
  - Defines the stage-owned runtime bundles now used by `import_session.py`: `ExtractedBookBundle`, `RecipeBoundaryResult`, `RecipeRefineResult`, `NonrecipeRouteResult`, and `NonrecipeFinalizeResult`.
  - Keeps the five-stage authority order explicit; the writer now emits split non-recipe seed-routing, final-authority, and review-status artifacts instead of one mixed file.
- `cookimport/staging/writer.py`
  - Writes recipe-authority artifacts, intermediate/final outputs, non-recipe route/finalize artifacts, section artifacts, chunks, raw artifacts, and report JSON.
  - Generates/stabilizes IDs where needed.
- `cookimport/staging/recipe_block_evidence.py`, `knowledge_block_evidence.py`, `block_label_resolution.py`
  - Owned builders for recipe-local evidence, final non-recipe knowledge evidence, and block-label priority resolution. `recipe_block_evidence.py` is now exact-or-unresolved: it uses exact grounded matches plus explicit unresolved metadata instead of fuzzy/scored back-projection for title, variant, yield, and time evidence.
- `cookimport/staging/stage_block_predictions.py`
  - Thin assembly layer for deterministic block-level benchmark evidence labels (`stage_block_predictions.v1`).
- `cookimport/staging/pdf_jobs.py`
  - Split-job helpers: range planning and post-merge recipe ID reassignment by source order.
- `cookimport/cli_worker.py`
  - Main single-file stage flow uses writer functions.
- `cookimport/cli_commands/stage.py`
  - Stage command owner for multi-job merge flow; offsets split block provenance, writes merged outputs, merges per-job raw artifacts, and emits run-level manifest/index artifacts with helpers from `cookimport/cli_support/stage.py`.
  - The hidden stage CLI surface stays aligned with `RunSettings` operator/internal knobs, including `knowledge_inline_repair_transcript_mode`, so adapter-built stage kwargs can bind directly to the registered command.
- `cookimport/runs/manifest.py`
  - Defines/stores `run_manifest.json` written by stage/pred-run flows for source identity + artifact indexing.
- `cookimport/labelstudio/ingest_flows/prediction_run.py` and `cookimport/labelstudio/ingest_flows/upload.py`
  - Label Studio ingest owner modules for prediction-run generation and upload.
- `cookimport/labelstudio/ingest_support.py`
  - Shared helper surface used by `ingest_flows/` and mirrored back through the public ingest facade for tests.
- `cookimport/staging/import_session.py`
  - Honest top-level re-export for the shared stage-session entrypoint/result types.
- `cookimport/staging/deterministic_prep.py`
  - Shared deterministic prep bundle owner for benchmark and stage reuse. It builds or reloads repo-level shared cache entries under `.cache/cookimport/book-cache/deterministic-prep/<source_hash>/<prep_key>/`, writes a human-readable manifest plus serialized deterministic `ConversionResult`, and can reconstruct a cached `RecipeBoundaryResult` for later execution.
  - Cached boundary reload now rebuilds archive block rows from the saved source model (`raw/source/<workbook_slug>/source_blocks.jsonl`, mirrored in `conversion_result.sourceBlocks`) and uses importer raw `full_text.json` only as fallback; merged split-book ownership must stay aligned to source-model coordinates, not arbitrary raw importer offsets.
  - Stage runs now check that shared cache before doing fresh source-job work, resume directly from cached recipe-boundary state on a hit, and persist a new deterministic prep bundle back into the shared cache after a cold stage run completes.
  - Its shard-recommendation helper now forwards prompt-preview survivability KPIs back to interactive benchmark planning, including per-step average token pressure and a small book-level deterministic summary derived from the cached boundary result.
- `cookimport/staging/import_session_contracts.py`
  - Shared public result dataclass/types used by `import_session_flows/` and the public session facade.
- `cookimport/staging/import_session_flows/`
  - `output_stage.py` owns the active shared stage-session implementation, but it now reads late outputs from the canonical non-recipe authority contract instead of re-deciding that boundary inline. It also exposes a boundary-resume entrypoint so benchmark callers can restart from a cached deterministic recipe-boundary result instead of rerunning label-first prep. `authority.py` owns authoritative label artifact writes: deterministic runs still publish `label_deterministic` / `label_refine`, while Codex-backed line-role runs publish the visible authority mirror under `line-role-pipeline/`.

Progress telemetry note:

- `cookimport/staging/import_session_flows/output_stage.py` emits structured stage-progress snapshots for label-first authority building, knowledge chunk generation, and multi-step output writing, so stage/benchmark spinners and `processing_timeseries.jsonl` retain more than a single status line during those phases.
- The shared stage session now runs through explicit five-stage runtime objects before writing: `extract`, `recipe-boundary`, `recipe-refine`, `nonrecipe-route`, `nonrecipe-finalize`.
- `stage_observability.json` now sorts those semantic stages to match that dependency order using readable 10-step slots instead of historical slot numbers, so Codex-backed `line_role` appears at 10, deterministic label stages at 20/30, `recipe_boundary` at 40, recipe stages at 50/60/70, `nonrecipe_route` at 80, `nonrecipe_finalize` at 90, and `write_outputs` at 100.

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

- `08_nonrecipe_route.json`
- `08_nonrecipe_exclusions.jsonl`
- `09_nonrecipe_authority.json`
- `09_nonrecipe_knowledge_groups.json`
- `09_nonrecipe_finalize_status.json`
- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`
- `recipe_authority/<workbook_slug>/recipe_block_ownership.json`
- `label_deterministic/<workbook_slug>/labeled_lines.jsonl` and `block_labels.json` on deterministic/vanilla runs
- `label_refine/<workbook_slug>/labeled_lines.jsonl` and `block_labels.json` on deterministic-backed refine runs
- `line-role-pipeline/authoritative_labeled_lines.jsonl`
- `line-role-pipeline/authoritative_block_labels.json`
- `line-role-pipeline/label_diffs.jsonl`
- `recipe_boundary/<workbook_slug>/recipe_spans.json`
- `recipe_boundary/<workbook_slug>/span_decisions.json`
- `recipe_boundary/<workbook_slug>/authoritative_block_labels.json`
- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `sections/<workbook_slug>/r{index}.sections.json`
- `sections/<workbook_slug>/sections.md` (default; skipped with `stage --no-write-markdown`)
- `chunks/<workbook_slug>/c{index}.json` (if any; deterministic fallback when non-recipe finalize is off)
- `chunks/<workbook_slug>/chunks.md` (same condition as `c{index}.json`)
- `tables/<workbook_slug>/tables.jsonl` and `tables/<workbook_slug>/tables.md` (always written for stage/prediction runs; `tables.md` skipped with `stage --no-write-markdown`)
- `knowledge/<workbook_slug>/knowledge.md` (if optional knowledge extraction is enabled and wrote reviewer-facing knowledge output)
- `knowledge/knowledge_index.json` (if any knowledge artifacts were written in the run)
- `.bench/<workbook_slug>/stage_block_predictions.json` (deterministic block-level benchmark evidence)
- `.bench/<workbook_slug>/p6_metadata_debug.jsonl` (internal-only Priority 6 diagnostics; Bucket 1 no longer exposes `p6_emit_metadata_debug` as a normal run setting)
- `raw/<importer>/<source_hash>/<location_id>.<ext>` (if any)
  - includes `recipe_scoring_debug.jsonl` when importers emit candidate gate decisions
- `raw/llm/<workbook_slug>/recipe_correction_audit/*.json` (when recipe Codex correction ran)
- `raw/llm/<workbook_slug>/recipe_phase_runtime/inputs/*.json` + `raw/llm/<workbook_slug>/recipe_phase_runtime/proposals/*.json` (when recipe Codex correction ran)
- `raw/llm/<workbook_slug>/recipe_manifest.json`
- `raw/llm/<workbook_slug>/nonrecipe_finalize/{in,out}/*.json` + `knowledge_manifest.json` (if knowledge harvesting is enabled)
- `<workbook_slug>.excel_import_report.json` at run root
- `processing_timeseries.jsonl` at run root (stage status snapshots + CPU utilization samples)
- `stage_observability.json` at run root (canonical semantic stage index for the run)
- `run_summary.json` at run root (machine-readable per-run digest: books, major settings, codex-farm mode, topline metrics)
- `run_summary.md` at run root (human-readable quick digest; written only when `stage --write-markdown` is enabled)
- `run_manifest.json` at run root (source identity + artifact index for this stage run)
- prediction-run helpers should keep shared manifest knobs aligned with `stage` defaults unless a caller overrides them explicitly. In particular, the pred-run path now inherits the same default `codex_farm_knowledge_context_blocks=0` value so stage/pred manifest parity stays stable.

Label-first metadata note:

- deterministic `label_deterministic` / `label_refine`, Codex-backed `line-role-pipeline` authority mirrors, and `recipe_boundary` now publish explicit `decided_by`, `reason_tags`, and `escalation_reasons` on authoritative line/block/span artifacts.
- `recipe_boundary/<workbook_slug>/recipe_spans.json` is the accepted authoritative span list only.
- `span_decisions.json` is the compact reviewer/debug rollup for both accepted recipe spans and rejected pseudo-recipe runs, including explicit `decision` and `rejection_reason` fields.
- Accepted grouped spans now already satisfy the stricter coherent-recipe rule: title anchor plus ingredient evidence plus instruction evidence. `build_conversion_result_from_label_spans(...)` no longer performs ordinary late recipe-body demotion; an impossible accepted projection is surfaced only as an invariant warning.

Report contract note:
- `<workbook_slug>.excel_import_report.json` can include `recipeLikeness` summary (backend/version, thresholds, tier counts, score stats, rejected count).
- `*.report_totals_mismatch_diagnostics.json` is no longer a routine stage artifact; it is written only when explicitly prepopulated report totals disagree with authoritative final stage counts.
- When that mismatch artifact fires on processed-output or stage-session paths, the common failure mode is authority drift rather than arithmetic error: importer-populated `ConversionReport` totals are being compared against stage-owned final totals after enrichment.
- The durable fix direction is to compare authoritative-with-authoritative only: start stage sessions from a fresh `ConversionReport`, or preserve inherited importer totals under a separate legacy/debug namespace instead of mixing them into the final report contract.

Outside run root (`.history/` for repo-local output roots):

- `performance_history.csv` is appended after stage runs when perf summary generation succeeds.
- For external output roots (for example `/tmp/out`), history remains `<output_root parent>/.history/performance_history.csv`.

Code pointers (prefer these over line numbers, which drift often):

- `cookimport/cli_worker.py` (`execute_source_job`) writes per-job raw artifacts, and `cookimport/cli_commands/stage.py` (`stage`) plus `cookimport/cli_support/stage.py` (`_merge_source_jobs`) assemble the merged book and invoke staging writers once.
- `cookimport/staging/writer.py` (`write_intermediate_outputs`, `write_draft_outputs`, `write_section_outputs`, `write_chunk_outputs`, `write_table_outputs`, `write_raw_artifacts`, `write_stage_block_predictions`, `write_report`) implements the file layout above.
- `cookimport/cli_commands/stage.py` plus `cookimport/cli_support/stage.py` (`_write_knowledge_index_best_effort`, `_write_stage_run_summary`, `_write_stage_run_manifest`) add run-level index/summary/manifest artifacts.
- `cookimport/runs/stage_observability.py` is the canonical run-level stage model/writer used by summaries and manifests.

Tags embedding note:
- `final drafts/<workbook_slug>/r{index}.json` can now contain `recipe.tags` as a flat accepted tag list.
- `intermediate drafts/<workbook_slug>/r{index}.jsonld` uses matching schema.org `keywords`.
- Those tags now come directly from recipe correction plus deterministic normalization.

Recipe-authority note:
- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` is the canonical semantic handoff from Stage 3 into staging writes.
- `recipe_authority/<workbook_slug>/recipe_authority_decisions.json` is the canonical per-recipe decision ledger for semantic outcome, publish status, and ownership action. This is where retained-but-withheld recipe outcomes stay explicit instead of being flattened into nonrecipe.
- `recipe_authority/<workbook_slug>/recipe_block_ownership.json` is the canonical block-ownership handoff from Stage 2/3 into nonrecipe routing, knowledge packet planning, and stage-block scoring.
- `recipe-refine` may only shrink that ownership through explicit divestment in the same artifact; recipe provenance is descriptive metadata, not a second ownership source.
- live recipe Codex outputs now carry explicit divested block indices (`db` in the compact shard contract), and `run_recipe_refine_stage(...)` applies those records before any nonrecipe routing or knowledge planning sees the workbook.
- When recipe Codex is enabled and validates, its promoted correction payload becomes the semantic owner for title, description, ingredients, instructions, notes, yield phrase, variants, tags, and ingredient-step links.
- `fragmentary` recipe outcomes no longer auto-divest their entire owned surface. They stay recipe-owned unless the worker explicitly hands blocks back through `db`.
- A repaired recipe that fails deterministic final draft validation is now a withheld-invalid recipe outcome: stage keeps the repaired semantic payload for recipe-local evidence, drops the recipe from published `cookbook3`, and records that decision in `recipe_authority_decisions.json`.
- Recipe Codex task outcomes now stay explicit even when they do not promote. `recipe_phase_runtime/promotion_report.json` records whether a validated recipe task result is `promotable` or `non_promotable`, and also exposes `handled_locally_skip_llm` when repo-authored fragmentary / non-recipe scaffolds were finalized without a worker round-trip. `recipe_manifest.json` mirrors the topline local-skip count, while `recipe_correction_audit/*.json` still records whether final recipe authority was actually `promoted` or intentionally `not_promoted`.
- Recipe, non-recipe, and line-role live Codex roots now also keep `phase_plan.json` plus `phase_plan_summary.json` beside `phase_manifest.json`. Those planning artifacts are the durable source for requested shards vs survivability recommendation vs budget-native packetization vs actual launch count.
- When recipe Codex is off or falls back, `pipeline_runtime.py` still emits the same payload shape deterministically so writer contracts stay uniform.
- `write_intermediate_outputs(...)`, `write_draft_outputs(...)`, and `write_section_outputs(...)` now project from that payload first; active stage-backed runtime code no longer threads legacy override dicts as a parallel authority lane, and `CodexFarmApplyResult` no longer publishes recipe override maps as part of the live stage contract.

Stage-block `KNOWLEDGE` label contract:
- `stage_block_predictions.json` now uses only the explicit final non-recipe authority recorded in `09_nonrecipe_authority.json`.
- recipe-local block ownership comes from `recipe_authority/<workbook_slug>/recipe_block_ownership.json`, not from recipe provenance ranges rebuilt later from recipe payloads.
- `08_nonrecipe_route.json` is the deterministic `nonrecipe-route` artifact. It keeps candidate/exclude routing, exclusion reasons, block ids, and previews, but it does not publish final semantic category guesses.
- `08_nonrecipe_route.json` may contain only blocks that were unowned at boundary time or explicitly divested later; recipe-owned blocks are forbidden input, not just low-priority output.
- The nonrecipe router consumes authoritative block labels, not repair heuristics: `NONRECIPE_CANDIDATE` feeds the knowledge queue, `NONRECIPE_EXCLUDE` becomes immediate final `other`, and malformed authoritative labels are hard errors.
- One explicit divestment bridge remains active at that seam: if recipe refine divests a block that still carries a recipe-local authoritative label such as `RECIPE_NOTES`, the nonrecipe router normalizes it to `NONRECIPE_CANDIDATE` so the block can re-enter outside-recipe review instead of failing contract validation. Recipe-boundary coherence rejects now do the same thing earlier: incoherent recipe-shaped spans hand back to `NONRECIPE_CANDIDATE`, never `NONRECIPE_EXCLUDE`.
- `build_nonrecipe_authority_result(...)` now hard-enforces that excluded block indices stay final `other` even if a later refine/projection map tries to leak them back into final `knowledge`.
- `09_nonrecipe_authority.json` is the only final-truth artifact for outside-recipe `knowledge` versus `other`. It contains only authoritative spans, categories, and block indices.
- `09_nonrecipe_knowledge_groups.json` is the explicit promoted-group artifact for packet-reviewed related ideas. It is reviewer/debug context, not the category-authority file.
- `09_nonrecipe_finalize_status.json` is the runtime-status artifact for finalized and unresolved candidate rows. It keeps unresolved candidate metadata out of the authority file while still making incompleteness visible.
- `08_nonrecipe_exclusions.jsonl` is the row-level explanation ledger for the upstream obvious-junk veto. When knowledge input looks too large or a row seems to have disappeared before review, inspect this file before changing scorer math or knowledge prompts.
- Knowledge groups are now the primary semantic artifact from the always-on second pass. Pass 1 only decides `keep_for_review` versus `other`; pass 2 assigns one shared grounding story per group, and staging projects that group grounding back onto each kept row's final `KNOWLEDGE` decision.
- Candidate rows that remain unresolved now stay explicit in benchmark/Label Studio metadata as `unresolved_candidate_*`; semantic scoring excludes them instead of flattening them into `OTHER`.
- `NonrecipeFinalizeResult.authoritative_nonrecipe_blocks` is the strict final outside-recipe authority carried through the stage runtime.
- Table extraction and deterministic knowledge-off chunk generation use `NonrecipeFinalizeResult.late_output_nonrecipe_blocks`. When non-recipe finalize runs and produces reviewed authority, that late-output list is the authoritative outside-recipe rows; when non-recipe finalize is off or falls back, it is the surviving outside-recipe candidate queue.
- Final semantic `KNOWLEDGE` evidence still comes only from `09_nonrecipe_authority.json`.

Stage-block label resolution contract:
- `stage_block_predictions.py` labels blocks from recipe-local text matches (title, ingredients, instructions, notes, variant/yield/time lines).
- `recipe_block_evidence.py` owns those recipe-local matches, including the conservative fallback order for withheld recipes: retained semantic payload first, then recipe-boundary labels, then explicit unresolved recipe-owned metadata. `knowledge_block_evidence.py` owns final `KNOWLEDGE` evidence plus unresolved review metadata, and `block_label_resolution.py` is the only label-priority resolver.
- knowledge packet inputs now omit recipe-owned block text entirely; nearby owned indices may survive only as guardrail metadata in the LLM payload.
- `stage_block_predictions.py` now requires nearby recipe-boundary evidence before promoting `RECIPE_TITLE` or `RECIPE_VARIANT`, so isolated headings or memoir-style prose transitions do not become recipe headers in stage evidence.
- `stage_block_predictions.py` emits `HOWTO_SECTION` for deterministic ingredient/instruction section-header hits (`extract_ingredient_sections`, `extract_instruction_sections`) when nearby recipe-structure signals are present.
- `RECIPE_NOTES` evidence merges schema `comment` rows with recipe-specific notes deterministically extracted from `description` (`extract_recipe_specific_notes`).
- If ingredient/instruction exact/fuzzy matching misses, it falls back to extracted archive `block_role` hints (`ingredient_line`, `instruction_line`).
- Multi-label conflicts resolve by fixed priority (`RECIPE_VARIANT` > `RECIPE_TITLE` > `YIELD_LINE` > `TIME_LINE` > `HOWTO_SECTION` > `INGREDIENT_LINE` > `RECIPE_NOTES` > `INSTRUCTION_LINE` > `KNOWLEDGE`).
- If a block has both `KNOWLEDGE` and recipe-local labels, staging now raises an invariant violation instead of silently letting recipe-local win.
- Stage-block predictions now also expose `unresolved_recipe_owned_*` metadata when a block is still recipe-owned but the run does not have enough safe recipe-local evidence to score it as a normal published recipe block. Benchmark scoring excludes those rows instead of flattening them into `OTHER`.
- Recipe-local stage labeling can derive block ranges from provenance line ranges (`start_line`/`end_line`) when explicit block ranges are absent (for example text-import paths).

## Intermediate JSON-LD Section Behavior

- `cookimport/staging/jsonld.py` now removes detected instruction section headers from literal step text.
- `cookimport/staging/jsonld.py`, `cookimport/staging/draft_v1.py`, and `write_section_outputs(...)` now consume the same fixed Bucket 1 fallback segmentation behavior so step boundaries stay aligned across outputs.
- When multiple instruction sections are detected, `recipeInstructions` is emitted as `HowToSection` objects with `itemListElement` `HowToStep` entries.
- Ingredient section groupings are emitted in custom metadata:
  - `recipeimport:ingredientSections` with `name`, `key`, and grouped `recipeIngredient` lines.
- Final cookbook3 (`draft_v1`) shape is unchanged; this richer structure is intermediate-only.
- If `candidate.tags` exists, intermediate JSON-LD emits it as `keywords`.

## ID and Provenance Behavior in Staging

### Recipe IDs

- Intermediate writer ensures candidate IDs exist (`@id`) before JSON-LD write.
- Fallback stable pattern when unresolved: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`.
- If `candidate.identifier` exists, it is used.

Code pointers:

- `cookimport/staging/writer.py` (`_ensure_candidate_id`, `write_intermediate_outputs`, `write_draft_outputs`)

### Tip/topic staging note

- Active stage runs no longer write importer-owned tip/topic artifacts. EPUB/PDF importers hand off only source-first blocks plus support proposals, and later stage ownership decides recipe versus non-recipe semantics.

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
- Instruction fallback segmentation now consumes the fixed Bucket 1 segmentation contract before section extraction and variant splitting.
- Priority 6 parser/yield options now consume run-config `p6_*` knobs (time strategy/backend, temperature extraction/unit conversion, oven-like mode, yield mode).

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

### Additional draft-v1 behaviors that affect downstream consumers

- `write_draft_outputs(...)` now writes only the canonical draft-v1 shape; top-level alias fields such as `name`, `ingredients`, and `instructions` are no longer added to final drafts.
- Ingredient text fields are lowercased in final draft output:
  - `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note`
- Variant extraction removes instruction lines that are variation headers/prefixes and stores them under `recipe.variants`.
- Recipe tags now live structurally on `recipe.tags`; draft shaping no longer uses `recipe.notes` as the primary tag carrier.
- If no instructions remain, fallback step is injected: `See original recipe for details.`
- Unassigned ingredients create prep step at beginning: `Gather and prepare ingredients.`
- Step time metadata from instruction parser is rolled up to `cook_time_seconds` when recipe cook time is missing.
- Step temperatures now preserve `temperature_items` arrays when available, alongside the existing `temperature`/`temperature_unit` convenience fields.
- Recipe-level `max_oven_temp_f` is emitted from oven-like step temperature metadata when available.
- Yield fields (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`) now come from centralized deterministic yield extraction (`scored_v1` or passthrough).
- When internal Priority 6 debug is enabled, draft conversion emits `_p6_debug` internally and writer strips it from final `r{index}.json` while writing `.bench/<workbook_slug>/p6_metadata_debug.jsonl`.
- Blank recipe titles are normalized to `Untitled Recipe`.
- Blank `source` values are normalized to `null` to satisfy staging schema min-length rules.
- `apply_line_role_spans_to_recipes(...)` now keeps an already-credible `recipe.name` unless projected `RECIPE_TITLE` / `RECIPE_VARIANT` spans also have nearby ingredient/instruction/yield/time structure, preventing late section-header overwrite from canonical line-role projections.

Code pointer:

- `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`)

## Split-Job Merge Behavior (PDF/EPUB)

When PDFs/EPUBs are split into jobs, merge flow:

1. Collects all job results.
2. Sorts jobs by start range.
3. When split jobs include `full_text` raw artifacts, builds merged `raw/.../full_text.json` block payload and offsets per-job block indices in recipe/non-recipe provenance to global coordinates.
4. Reassigns recipe IDs in source order (`start_spine` first, then `start_page`, then `start_block`).
5. Runs the shared stage-session write path against the merged source/archive blocks.
6. Writes stage-block predictions using merged archive blocks so block labels align with global block indices.
7. Moves raw artifacts from temporary `.job_parts/<workbook_slug>/job_{i}/raw/...` into final `raw/...` path.
   - Per-job `recipe_scoring_debug.jsonl` collisions are preserved via deterministic `job_{index}_...` prefixing.
8. Writes report JSON after raw merge so `outputStats` includes moved raw artifacts (plus merged `raw/.../full_text.json`) without a post-write directory scan.

### Split-merge outputStats invariants (merged 2026-02-27)

When touching split merge, keep this ordering and accounting contract:

- record merged `raw/.../full_text.json` in output stats when written,
- record each moved raw destination during `_merge_raw_artifacts(...)`,
- write report after raw merge completes.

Guardrail test:
- `tests/staging/test_split_merge_status.py::test_merge_source_jobs_output_stats_match_fresh_directory_walk`
  compares report `outputStats` against a fresh categorized directory walk.

Main-process merge status callback contract:

- Top-level merge milestones are phase-counted as `merge phase X/Y: <label>`.
- Session-level staging callbacks (for example `Generating deterministic non-recipe chunks...`, `Writing outputs...`) are forwarded as plain status lines between merge phases.
- Phase totals are deterministic for emitted merge-phase rows; chunk generation remains a forwarded session status, not an extra merge-phase counter.
- Stage live status panels now use shared slot gating (`COOKIMPORT_LIVE_STATUS_SLOTS`, default `1`); when no live slot is available, stage falls back to plain status lines instead of raising a live-display error.

Code pointers:

- `cookimport/cli_support/stage.py` (`_merge_source_jobs`, `_merge_raw_artifacts`)
- `cookimport/staging/pdf_jobs.py` (`reassign_recipe_ids`)

## Run manifest contract

`run_manifest.json` is a required stage-run index written after stage outputs finish.

- Includes source identity (`path`, optional `source_hash`, detected `importer_name`).
- Includes run config snapshot used for the run.
- Includes artifact pointers for reports, stage-block predictions, knowledge/tag indexes, processing telemetry, and worker-resolution telemetry when present.
- Used by parity tests and downstream tooling to compare stage and pred-run provenance/config.

Worker-resolution artifact:

- `stage_worker_resolution.json` is written at run root with:
  - `process_workers_required`
  - `backend_effective` (`process`, `subprocess`, `thread`, or `serial`)
  - `messages` (fallback/probe details)
- `run_manifest.json` includes `artifacts.stage_worker_resolution_json` when this file exists.

Code pointers:
- `cookimport/cli_support/stage.py` (`_write_stage_run_manifest`, `_write_run_manifest_best_effort`)
- `cookimport/runs/manifest.py` (`RunManifest`, `write_run_manifest`)

## Current limitations / things we know are not great yet

1. Lowercasing is lossy by design
- Improves normalization but may remove intentional capitalization in ingredient text fields.
- This is currently tested behavior, not an accidental bug.

2. Split-job raw artifact filename collisions are auto-prefixed
- Merge may rename colliding files with `job_{index}_...` prefixes.
- Good for loss avoidance, but file names can differ run-to-run when collisions happen.
- Code pointers: `cookimport/cli_support/stage.py` (`_merge_raw_artifacts`, `_prefix_collision`).

3. Timestamp output folder granularity is seconds
- Two invocations in the same second could collide on output directory name.
- Current behavior uses `%Y-%m-%d_%H.%M.%S`.
- Code pointer: `cookimport/cli.py` (run root timestamp uses `%Y-%m-%d_%H.%M.%S` in multiple stage entrypoints).

## Test coverage tied to staging contracts

Core tests to keep green when touching staging:

- `tests/cli/test_cli_output_structure_text_fast.py`
- `tests/cli/test_cli_output_structure_epub_fast.py`
- `tests/cli/test_cli_output_structure_slow.py`
- `tests/staging/test_draft_v1_staging_alignment.py`
- `tests/staging/test_draft_v1_lowercase.py`
- `tests/staging/test_draft_v1_variants.py`
- `tests/staging/test_import_session.py`
- `tests/staging/test_nonrecipe_stage.py`
- `tests/staging/test_split_merge_status.py`
- `tests/staging/test_section_outputs.py`
- `tests/staging/test_stage_block_predictions.py`
- `tests/staging/test_stage_observability.py`
- `tests/staging/test_run_manifest_parity.py`
- `tests/parsing/test_source_field.py`
- `tests/ingestion/test_pdf_job_merge.py`
- `tests/ingestion/test_epub_job_merge.py`

## Practical “change checklist” for future work

When editing staging behavior, confirm:

1. Path layout and naming in CLI help/docs still match writes.
2. Draft ingredient-line invariants remain staging-safe.
3. Unresolved ID handling remains placeholder/null pattern.
4. Split-job merge still preserves deterministic order, block-index offsets, and raw-artifact accounting.
5. Non-recipe/chunks/raw/report outputs still land in expected paths.
6. Output stats reporting remains attached to report (`outputStats`) when files are written.
7. `run_manifest.json` still captures source identity + artifact paths for this run.

## Related docs

- Ingestion details feeding staging: `docs/03-ingestion/03-ingestion_readme.md`
- Parsing behavior feeding staging normalization: `docs/04-parsing/04-parsing_readme.md`
- Metrics and report surfaces consuming staging outputs: `docs/08-analytics/08-analytics_readme.md`
