# Staging Module

Handles output file generation in two formats:

- **Intermediate (JSON-LD):** `jsonld.py` converts `RecipeCandidate` to RecipeSage JSON-LD format with raw unparsed data
- **Final (DraftV1):** `draft_v1.py` converts to structured format with parsed ingredients linked to steps
- **Writer:** `writer.py` provides `write_intermediate_outputs()` and `write_draft_outputs()` functions
  - Outputs are flattened under the per-file folder as `r{index}.json[ld]` (no sheet subfolders).
  - When a candidate lacks `row_index` provenance (text/PDF/EPUB), `writer.py` falls back to `location.chunk_index` for stable IDs.

## Step-level ingredient linking

Draft V1 step mapping uses `cookimport.parsing.step_ingredients.assign_ingredient_lines_to_steps`.
It matches ingredient names against instruction text with word-boundary token checks,
groups ingredients under section headers (for example, "Sauce"), and excludes headers
from step output. Single-token matches are capped per step unless an "all ingredients"
phrase is detected.
