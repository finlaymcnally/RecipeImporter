# Staging Module

Handles output file generation in two formats plus tip snippets:
Durable output-path and section/report contracts live in `cookimport/staging/CONVENTIONS.md`.

- **Intermediate (schema.org Recipe JSON):** `jsonld.py` converts `RecipeCandidate` to schema.org Recipe JSON with `recipeimport:*` metadata extensions
- **Final (cookbook3):** `draft_v1.py` converts to the structured cookbook3 format (internal model name: `RecipeDraftV1`) with parsed ingredients linked to steps
  - The final builder now accepts an explicit `ingredient_step_mapping_override`, so recipe Codex can correct the intermediate `RecipeCandidate` once and let staging rebuild cookbook3 deterministically from that corrected candidate plus linkage payload.
  - Output is shaped for Cookbook staging import semantics: unresolved `ingredient_id` values are non-empty placeholders, unresolved `input_unit_id` values are `null`, and ingredient line quantity rules are normalized to staging constraints.
  - Ingredient parsing behavior in draft conversion is run-config aware (`ingredient_*` run settings are threaded from stage/prediction imports into `parse_ingredient_line`).
  - Instruction fallback segmentation is run-config aware (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) before section extraction and step parsing.
  - Priority 6 parsing/yield options are run-config aware (`p6_*` settings): step parsing can emit `temperature_items`, recipe-level `max_oven_temp_f`, strategy-based `cook_time_seconds` fallback, and centralized yield fields.
- **Writer:** `writer.py` provides `write_intermediate_outputs()`, `write_draft_outputs()`, and `write_tip_outputs()` functions
  - `import_session.py` is the shared stage-backed post-conversion runner used by single-file stage, split-merge stage, and benchmark-backed processed outputs.
  - `group_recipe_spans/<workbook_slug>/recipe_spans.json` now contains accepted spans only; `span_decisions.json` carries both accepted and rejected grouping decisions so titleless pseudo-recipes and empty title-only shells stay debuggable without becoming recipes.
  - `nonrecipe_stage.py` is the Stage 7 non-recipe authority seam: it records deterministic seed ownership, and the knowledge stage can refine the final `knowledge` versus `other` result before writer emits `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`.
  - Stage 7 now also keeps an internal split between review-eligible `other` blocks and obvious-junk `other` blocks excluded upstream by line-role; `writer.py` exposes the excluded subset in `08_nonrecipe_review_exclusions.jsonl` while keeping the public final taxonomy at `knowledge` / `other`.
  - Internal reviewer categories such as `chapter_taxonomy` stay inside the refinement report; staged outputs still expose only final `knowledge` or `other`.
  - Outputs are flattened under the per-file folder as `r{index}.json[ld]` (no sheet subfolders).
  - When a candidate lacks `row_index` provenance (text/PDF/EPUB), `writer.py` falls back to `location.chunk_index` for stable IDs.
  - Writer helpers can optionally collect per-output file counts/bytes for inclusion in conversion reports (`outputStats`).
  - Optional I/O pacing for write-heavy runs is env-gated: `COOKIMPORT_IO_PACE_EVERY_WRITES` + `COOKIMPORT_IO_PACE_SLEEP_MS`.
  - Writer applies one shared effective instruction-shaping path for final draft, intermediate JSON-LD, and `sections` artifacts so step boundaries stay aligned across outputs.
  - Split-merge stage runs now finalize raw-artifact moves before report write so `outputStats` includes moved raw files and merged `raw/.../full_text.json`.
  - Stage writes deterministic benchmark evidence at `.bench/<workbook_slug>/stage_block_predictions.json` for block-level freeform scoring.
  - Stage-block `KNOWLEDGE` ownership now comes from the final non-recipe authority; optional knowledge snippets stay as reviewer evidence, while knowledge-stage `block_decisions` can change the final scored ownership.
  - When `p6_emit_metadata_debug` is enabled, writer strips `_p6_debug` from final draft JSON and writes `.bench/<workbook_slug>/p6_metadata_debug.jsonl` for side-by-side parser/yield diagnostics.
- **Tips:** `writer.py` writes `t{index}.json` for non-instruction tips/knowledge snippets under `tips/{workbook_slug}/`, plus `tips.md` listing tip text with their `t{index}` ids, anchor tags, and any detected topic headers for quick review.
  - Tips derived from recipes include `sourceRecipeId` and `sourceRecipeTitle` for quick lookup, plus `scope`, `standalone`, `generalityScore`, `sourceText`, and tag categories (`dishes`, ingredient groups, `techniques`, `cookingMethods`, `tools`) for filtering and traceability.
  - `topic_candidates.json` and `topic_candidates.md` capture atom-level standalone snippets (paragraphs/list items) before tip classification, with container headers and adjacent-atom context in provenance for evaluation and LLM prefiltering.
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
