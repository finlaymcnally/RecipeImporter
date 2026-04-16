# Staging Module

Handles output file generation for recipe drafts plus section/chunk/non-recipe artifacts:
Durable output-path and section/report contracts live in `cookimport/staging/CONVENTIONS.md`.

- **Intermediate (schema.org Recipe JSON):** `jsonld.py` converts `RecipeCandidate` to schema.org Recipe JSON with `recipeimport:*` metadata extensions
- **Final (cookbook3):** `draft_v1.py` converts to the structured cookbook3 format (internal model name: `RecipeDraftV1`) with parsed ingredients linked to steps
  - The canonical handoff is now `AuthoritativeRecipeSemantics`: recipe correction or deterministic fallback builds one payload with title/ingredients/instructions/notes/variants/tags/linking first, then staging projects cookbook3 from that payload.
  - Output is shaped for Cookbook staging import semantics: unresolved `ingredient_id` values are non-empty placeholders, unresolved `input_unit_id` values are `null`, and ingredient line quantity rules are normalized to staging constraints.
  - Ingredient parsing behavior in draft conversion is run-config aware (`ingredient_*` run settings are threaded from stage/prediction imports into `parse_ingredient_line`).
  - Instruction fallback segmentation is run-config aware (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) before section extraction and step parsing.
  - Priority 6 parsing/yield options are run-config aware (`p6_*` settings): step parsing can emit `temperature_items`, recipe-level `max_oven_temp_f`, strategy-based `cook_time_seconds` fallback, and centralized yield fields.
- **Writer:** `writer.py` provides the staged output writers for intermediate/final drafts, sections, chunks, tables, raw artifacts, benchmark evidence, and reports.
  - `import_session.py` is the shared stage-backed post-conversion runner used by single-file stage, split-merge stage, and benchmark-backed processed outputs.
  - `pipeline_runtime.py` now gives that runner explicit five-stage runtime objects: `extract`, `recipe-boundary`, `recipe-refine`, `nonrecipe-route`, and `nonrecipe-finalize`.
  - `job_planning.py` is the source-job planner shared by stage and Label Studio; stage now always runs one-or-more planned jobs through `cli_worker.execute_source_job(...)` and merges them before `import_session.py` runs once.
  - `recipe_boundary/<workbook_slug>/recipe_spans.json` now contains accepted spans only; `span_decisions.json` carries both accepted and rejected grouping decisions so titleless pseudo-recipes and empty title-only shells stay debuggable without becoming recipes. New writes use row-native `*_row_index` / `row_indices` keys, while reload still accepts older block-named payloads.
  - `recipe_ownership.py` is the stage-owned recipe block contract. Writer now emits `recipe_authority/<workbook_slug>/recipe_row_ownership.json`, and `recipe-refine` may only shrink that contract through explicit divestment recorded there. Live recipe task outputs now carry divested block indices explicitly, so rejected/trimmed recipe spans re-enter nonrecipe through one inspected path instead of provenance drift.
  - `recipe_authority_decisions.py` is the small owner for the per-recipe decision ledger written to `recipe_authority/<workbook_slug>/recipe_authority_decisions.json`. It records semantic outcome, publish status, and ownership action so fragmentary or invalid-but-retained recipe outcomes stay visible without being mispublished.
  - Accepted recipe-boundary spans also normalize any bridged/nonrecipe gap labels to `RECIPE_NOTES` before ownership is built; nonrecipe routing only receives unowned blocks or explicitly divested ones.
  - When recipe-refine divests a block that still carries a recipe-local line-role label such as `RECIPE_NOTES`, nonrecipe routing now normalizes that handoff to `NONRECIPE_CANDIDATE` instead of failing the route contract.
  - `nonrecipe_stage.py` is now the thin non-recipe route/finalize public seam. The actual owners are `nonrecipe_authority_contract.py`, `nonrecipe_seed.py`, `nonrecipe_routing.py`, `nonrecipe_authority.py`, and `nonrecipe_finalize_status.py`, and strict final authority now stays on the stage runtime (`authoritative_nonrecipe_blocks`) before writer emits `08_nonrecipe_route.json`, `09_nonrecipe_authority.json`, and `09_nonrecipe_finalize_status.json`.
  - Live non-recipe route/finalize now runs on source-row units when `LabelFirstStageResult.source_rows` is present. The stage still keeps source-block summaries for recipe ownership and reporting, but row-facing `knowledge` / `other` authority now lives in `authoritative_row_category_by_index`, and mixed rows from one source block are no longer flattened to one final answer.
  - `nonrecipe_authority.py` now projects accepted route-time exclusions directly to final `other`, so an excluded block cannot leak back into final `knowledge` through later refinement/projection maps.
  - Rejected pseudo-recipe row labels such as `RECIPE_TITLE` or `RECIPE_NOTES` are normalized back to `NONRECIPE_CANDIDATE` before nonrecipe routing, matching the existing block-level recipe-boundary demotion contract.
  - The non-recipe route/finalize split now keeps a route-first candidate queue separate from obvious-junk exclusions; `writer.py` exposes the excluded subset in `08_nonrecipe_exclusions.jsonl` while keeping the public final taxonomy at `knowledge` / `other`.
  - Outside-recipe `NONRECIPE_EXCLUDE` from line-role is no longer gated by deterministic support heuristics. If line-role accepts the exclusion, staging projects that accepted decision directly to final `other`.
  - Internal reviewer categories such as `chapter_taxonomy` stay inside the refinement report; staged outputs still expose only final `knowledge` or `other`.
  - Outputs are flattened under the per-file folder as `r{index}.json[ld]` (no sheet subfolders).
  - When a candidate lacks `row_index` provenance (text/PDF/EPUB), `writer.py` falls back to `location.chunk_index` for stable IDs.
  - Writer helpers can optionally collect per-output file counts/bytes for inclusion in conversion reports (`outputStats`).
  - Optional I/O pacing for write-heavy runs is env-gated: `COOKIMPORT_IO_PACE_EVERY_WRITES` + `COOKIMPORT_IO_PACE_SLEEP_MS`.
  - Writer applies one shared effective instruction-shaping path for final draft, intermediate JSON-LD, and `sections` artifacts so step boundaries stay aligned across outputs.
  - Split-merge stage runs now finalize raw-artifact moves before report write so `outputStats` includes moved raw files and merged `raw/.../full_text.json`.
  - Stage writes deterministic benchmark evidence at `.bench/<workbook_slug>/semantic_row_predictions.json` as a row-native scorer payload, with `semantic_row_predictions.py` acting as the assembly root over `recipe_row_evidence.py`, `knowledge_row_evidence.py`, and `row_label_resolution.py`.
  - Withheld recipe-owned blocks can now stay explicit in stage evidence as `unresolved_recipe_owned_*` metadata when there is not enough safe recipe-local evidence to score them as normal published recipe blocks.
  - Published recipe evidence is now exact-or-unresolved for title, variant, yield, and time mapping. When repo code cannot ground one of those fields back to a source block exactly, `semantic_row_predictions.json` records `unresolved_recipe_exact_evidence` instead of guessing.
  - Stage-block `KNOWLEDGE` ownership now comes from the final non-recipe authority; optional knowledge snippets stay as reviewer evidence, while knowledge-stage `block_decisions` can change the final scored ownership.
  - If a block ever carries both recipe-local evidence and final `KNOWLEDGE`, staging now raises an invariant violation instead of silently resolving the overlap.
  - When `p6_emit_metadata_debug` is enabled, writer strips `_p6_debug` from final draft JSON and writes `.bench/<workbook_slug>/p6_metadata_debug.jsonl` for side-by-side parser/yield diagnostics.
  - Writer now emits `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` before intermediate/final drafts so bad recipe outputs can be debugged from one semantic artifact instead of merging override lanes mentally.
- **Chunks:** `writer.py` writes `chunks/{workbook_slug}/c{index}.json` plus optional `chunks.md` when the late-output non-recipe block set produces chunkable material.
  - When non-recipe finalize runs and produces reviewed authority, chunks follow `NonrecipeFinalizeResult.late_output_nonrecipe_blocks`. When non-recipe finalize is off or falls back, that same late-output surface holds the surviving routed candidate queue instead.
- **Raw artifacts:** `writer.py` writes raw snippets under `raw/{importer}/{source_hash}/` with per-recipe `location_id` filenames for audit trails.

## Step-level ingredient linking

cookbook3 step mapping uses `cookimport.parsing.step_ingredients.assign_ingredient_lines_to_steps`.
It matches ingredient names against instruction text with word-boundary token checks,
groups ingredients under section headers (for example, "Sauce"), and excludes headers
from step output. Single-token matches are capped per step unless an "all ingredients"
phrase is detected.

## Variants extraction

cookbook3 extracts instruction lines starting with "variant"/"variation" into `recipe.variants`
and omits them from step instructions.

Ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`)
are lowercased when writing cookbook3.
