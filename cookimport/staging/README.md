# Staging Module

Handles output file generation in two formats plus tip snippets:
Durable output-path and section/report contracts live in `cookimport/staging/CONVENTIONS.md`.

- **Intermediate (schema.org Recipe JSON):** `jsonld.py` converts `RecipeCandidate` to schema.org Recipe JSON with `recipeimport:*` metadata extensions
- **Final (cookbook3):** `draft_v1.py` converts to the structured cookbook3 format (internal model name: `RecipeDraftV1`) with parsed ingredients linked to steps
  - Output is shaped for Cookbook staging import semantics: unresolved `ingredient_id` values are non-empty placeholders, unresolved `input_unit_id` values are `null`, and ingredient line quantity rules are normalized to staging constraints.
- **Writer:** `writer.py` provides `write_intermediate_outputs()`, `write_draft_outputs()`, and `write_tip_outputs()` functions
  - Outputs are flattened under the per-file folder as `r{index}.json[ld]` (no sheet subfolders).
  - When a candidate lacks `row_index` provenance (text/PDF/EPUB), `writer.py` falls back to `location.chunk_index` for stable IDs.
  - Writer helpers can optionally collect per-output file counts/bytes for inclusion in conversion reports (`outputStats`).
  - Split-merge stage runs now finalize raw-artifact moves before report write so `outputStats` includes moved raw files and merged `raw/.../full_text.json`.
  - Stage writes deterministic benchmark evidence at `.bench/<workbook_slug>/stage_block_predictions.json` for block-level freeform scoring.
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
