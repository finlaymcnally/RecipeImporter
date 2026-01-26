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
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted. Tip snippets are written separately as `tips/{workbook}/t{index}.json` and include `sourceRecipeTitle`, `sourceText`, `scope` (`general`/`recipe_specific`/`not_tip`), `standalone`, `generalityScore`, and tag categories (including `dishes` and `cookingMethods`) when tied to a recipe. Each tips folder also includes `tips.md`, a markdown list of the tip `text` fields grouped by source block, annotated with `t{index}` ids plus anchor tags, and prefixed by any detected topic header line for quick review. Topic candidates captured before tip classification are written as `tips/{workbook}/topic_candidates.json` and `tips/{workbook}/topic_candidates.md` for evaluation/LLM prefiltering.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
- Draft V1 ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`) are lowercased on output.
- `ConversionResult.tipCandidates` stores all classified tip candidates (`general`, `recipe_specific`, `not_tip`), while `ConversionResult.tips` contains only standalone general tips for output.
- Recipe-derived tips default to `recipe_specific`; exported tips primarily come from non-recipe text unless a tip reads strongly general.
- Conversion reports include `runTimestamp` (local ISO-8601 time) for when the stage run started.
- Raw artifacts are preserved under `staging/raw/<importer>/<source_hash>/<location_id>.<ext>` for auditing (JSON snippets for structured sources, text/blocks for unstructured sources).
- Cookbook-specific parsing overrides live in the `parsingOverrides` section of mapping files or in `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.
