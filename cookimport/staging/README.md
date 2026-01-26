# Staging Module

Handles output file generation in two formats plus tip snippets:

- **Intermediate (JSON-LD):** `jsonld.py` converts `RecipeCandidate` to RecipeSage JSON-LD format with raw unparsed data
- **Final (DraftV1):** `draft_v1.py` converts to structured format with parsed ingredients linked to steps
- **Writer:** `writer.py` provides `write_intermediate_outputs()`, `write_draft_outputs()`, and `write_tip_outputs()` functions
  - Outputs are flattened under the per-file folder as `r{index}.json[ld]` (no sheet subfolders).
  - When a candidate lacks `row_index` provenance (text/PDF/EPUB), `writer.py` falls back to `location.chunk_index` for stable IDs.
- **Tips:** `writer.py` writes `t{index}.json` for non-instruction tips/knowledge snippets under `tips/{workbook_slug}/`, plus `tips.md` listing tip text with their `t{index}` ids, anchor tags, and any detected topic headers for quick review.
  - Tips derived from recipes include `sourceRecipeId` and `sourceRecipeTitle` for quick lookup, plus `scope`, `standalone`, `generalityScore`, `sourceText`, and tag categories (`dishes`, ingredient groups, `techniques`, `cookingMethods`, `tools`) for filtering and traceability.
  - `topic_candidates.json` and `topic_candidates.md` capture standalone topic chunks before tip classification for evaluation and LLM prefiltering.
- **Raw artifacts:** `writer.py` writes raw snippets under `raw/{importer}/{source_hash}/` with per-recipe `location_id` filenames for audit trails.

## Step-level ingredient linking

Draft V1 step mapping uses `cookimport.parsing.step_ingredients.assign_ingredient_lines_to_steps`.
It matches ingredient names against instruction text with word-boundary token checks,
groups ingredients under section headers (for example, "Sauce"), and excludes headers
from step output. Single-token matches are capped per step unless an "all ingredients"
phrase is detected.

## Variants extraction

Draft V1 extracts instruction lines starting with "variant"/"variation" into `recipe.variants`
and omits them from step instructions.

Ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`)
are lowercased when writing Draft V1.
