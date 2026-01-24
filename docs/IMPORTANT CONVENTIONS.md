---
summary: "Project-wide coding and organization conventions for the import tooling."
read_when:
  - Before starting any new implementation
  - When organizing output folders or defining new models
---

# Important Conventions

- The import tooling lives in the Python package `cookimport/`, with the CLI entrypoint exposed as the `cookimport` script via `pyproject.toml`.
- Core shared models are defined in `cookimport/core/models.py`, and staging JSON-LD helpers live in `cookimport/staging/`.
- Staging output folders use workbook stems (no file extension) for `intermediate drafts/<workbook>/...`, `final drafts/<workbook>/...`, and report names, while provenance still records the full filename.
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted. Tip snippets are written separately as `tips/{workbook}/t{index}.json` and include `sourceRecipeTitle`, `sourceText`, `scope` (`general`/`recipe_specific`/`not_tip`), `standalone`, and `generalityScore` when tied to a recipe.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
- Draft V1 ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`) are lowercased on output.
- `ConversionResult.tipCandidates` stores all classified tip candidates (`general`, `recipe_specific`, `not_tip`), while `ConversionResult.tips` contains only standalone general tips for output.
- Recipe-derived tips default to `recipe_specific`; exported tips primarily come from non-recipe text unless a tip reads strongly general.
- Conversion reports include `runTimestamp` (local ISO-8601 time) for when the stage run started.
