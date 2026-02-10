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
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted. Tip snippets are written separately as `tips/{workbook}/t{index}.json` and include `sourceRecipeTitle`, `sourceText`, `scope` (`general`/`recipe_specific`/`not_tip`), `standalone`, `generalityScore`, and tag categories (including `dishes` and `cookingMethods`) when tied to a recipe. Each tips folder also includes `tips.md`, a markdown list of the tip `text` fields grouped by source block, annotated with `t{index}` ids plus anchor tags, and prefixed by any detected topic header line for quick review. Topic candidates captured before tip classification are written as `tips/{workbook}/topic_candidates.json` and `tips/{workbook}/topic_candidates.md`; these are atom-level snippets with container headers and adjacent-atom context recorded under `provenance.atom` and `provenance.location`.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
- Draft V1 ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`) are lowercased on output.
- `ConversionResult.tipCandidates` stores all classified tip candidates (`general`, `recipe_specific`, `not_tip`), while `ConversionResult.tips` contains only standalone general tips for output.
- Recipe-derived tips default to `recipe_specific`; exported tips primarily come from non-recipe text unless a tip reads strongly general.
- Conversion reports include `runTimestamp` (local ISO-8601 time) for when the stage run started.
- Conversion reports include `outputStats` with per-output file counts/bytes (and largest files) to help debug slow writes.
- Performance summaries append one row per file to `data/output/.history/performance_history.csv` after each run.
- Raw artifacts are preserved under `staging/raw/<importer>/<source_hash>/<location_id>.<ext>` for auditing (JSON snippets for structured sources, text/blocks for unstructured sources).
- PDF page-range jobs and EPUB spine-range jobs (when a large source is split across workers) write raw artifacts to `staging/.job_parts/<workbook_slug>/job_<index>/raw/...` and the main process merges them back into `staging/raw/` after the merge completes. Temporary `.job_parts` folders may remain only if a merge fails.
- Cookbook-specific parsing overrides live in the `parsingOverrides` section of mapping files or in `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.
- Label Studio benchmark artifacts are written under `data/output/<timestamp>/labelstudio/<book_slug>/`, including `extracted_archive.json`, `label_studio_tasks.jsonl`, and export outputs under `exports/` (pipeline `golden_set_tip_eval.jsonl`, canonical `canonical_block_labels.jsonl` + `canonical_gold_spans.jsonl`).
- Freeform Label Studio tasks use stable `segment_id = urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}` and include `source_map.blocks` with per-block character offsets (`segment_start`/`segment_end`) so exported span offsets can map back to source blocks deterministically.
- Freeform span exports write `freeform_span_labels.jsonl` and `freeform_segment_manifest.jsonl` under `exports/`; each span row includes label, start/end offsets, selected text, and touched block IDs/indices.
- Freeform span taxonomy treats broad advice as `TIP`, recipe-specific annotations as `NOTES`, and recipe alternatives as `VARIANT`; freeform evaluation normalizes legacy aliases (`KNOWLEDGE` -> `TIP`, `NOTE` -> `NOTES`).
- `cookimport labelstudio-benchmark` is the guided end-to-end flow for scoring pipeline predictions against a selected freeform gold export; it selects/infers source + gold, runs prediction import, and writes `eval-vs-pipeline` artifacts.
