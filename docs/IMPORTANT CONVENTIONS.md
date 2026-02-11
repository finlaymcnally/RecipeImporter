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
- Raw artifacts are preserved under `<output_root>/<timestamp>/raw/<importer>/<source_hash>/<location_id>.<ext>` for auditing (JSON snippets for structured sources, text/blocks for unstructured sources).
- PDF page-range jobs and EPUB spine-range jobs (when a large source is split across workers) write temporary raw artifacts to `<output_root>/.job_parts/<workbook_slug>/job_<index>/raw/...` and the main process merges them back into `<output_root>/<timestamp>/raw/` after the merge completes. Temporary `.job_parts` folders may remain only if a merge fails.
- Cookbook-specific parsing overrides live in the `parsingOverrides` section of mapping files or in `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.
- `labelstudio-import` run artifacts are written under `<output_dir>/<timestamp>/labelstudio/<book_slug>/`, including `extracted_archive.json`, `label_studio_tasks.jsonl`, and export outputs under `exports/` (pipeline `golden_set_tip_eval.jsonl`, canonical `canonical_block_labels.jsonl` + `canonical_gold_spans.jsonl`).
- Interactive CLI (`cookimport` with no subcommand) uses `cookimport.json` setting `output_dir` for stage/inspect artifacts (default `data/output/`), while interactive Label Studio import/export/benchmark artifacts are rooted under `data/golden/`.
- Non-interactive `cookimport labelstudio-import`, `cookimport labelstudio-export`, and `cookimport labelstudio-benchmark` default `--output-dir` to `data/golden/` (override with `--output-dir` when needed).
- Run folder timestamps are standardized as `YYYY-MM-DD_HH.MM.SS` (for example `2026-02-10_23.21.33`) across stage outputs, Label Studio import/export run folders, and benchmark eval folders.
- Freeform Label Studio tasks use stable `segment_id = urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}` and include `source_map.blocks` with per-block character offsets (`segment_start`/`segment_end`) so exported span offsets can map back to source blocks deterministically.
- Freeform span exports write `freeform_span_labels.jsonl` and `freeform_segment_manifest.jsonl` under `exports/`; each span row includes label, start/end offsets, selected text, and touched block IDs/indices.
- Freeform span taxonomy treats broad advice as `TIP`, recipe-specific annotations as `NOTES`, and recipe alternatives as `VARIANT`; freeform evaluation normalizes legacy aliases (`KNOWLEDGE` -> `TIP`, `NOTE` -> `NOTES`, `NARRATIVE` -> `OTHER`).
- `cookimport labelstudio-benchmark` is the guided end-to-end flow for scoring pipeline predictions against a selected freeform gold export; it selects/infers source + gold, runs prediction import, and by default writes everything under `data/golden/eval-vs-pipeline/<timestamp>/` (eval reports plus `prediction-run/` artifacts).
- Freeform eval reports keep strict span-level metrics and now include an `app_aligned` diagnostics block (deduped predictions, supported-label-only views, relaxed overlap, and any-overlap coverage) to better reflect cookbook app-visible behavior.
- Freeform eval reports also include `classification_only` diagnostics for label alignment without strict boundary matching (same-label any-overlap, best-overlap label match, label confusion by gold label).
- Freeform eval source matching is strict by default (hash/file identity must align), but `cookimport labelstudio-eval freeform-spans` and `cookimport labelstudio-benchmark` accept `--force-source-match` to compare spans anyway across renamed/truncated variants (for example `foo.epub` vs `fooCUTDOWN.epub`).
- `cookimport labelstudio-benchmark` is not an offline-only eval; it always runs a prediction `run_labelstudio_import(...)` first, which creates/fetches a Label Studio project and uploads tasks to `/api/projects/{id}/import` before evaluation.
- Label Studio write operations are explicitly gated: non-interactive `labelstudio-import`/`labelstudio-benchmark` require `--allow-labelstudio-write`, and interactive menu flows require an explicit upload confirmation prompt.
- `cookimport labelstudio-benchmark` also emits upload/review-ready processed cookbook outputs under `data/output/<timestamp>/` during the same run (override with `--processed-output-dir`).
- Freeform benchmark gold discovery checks both `data/output/**/exports/freeform_span_labels.jsonl` and `data/golden/**/exports/freeform_span_labels.jsonl`.
- `labelstudio-benchmark` prediction import supports the same PDF/EPUB split-job parallelization controls as stage imports (`workers`, split workers, pages/spine per job).
- Split-job `labelstudio-import`/`labelstudio-benchmark` merges must rebase block-index fields (`start_block`, `end_block`, `block_index`) by cumulative prior-job block counts so freeform/canonical eval remains on one global block coordinate space.
- Label Studio import/benchmark progress callbacks now include post-merge phases (archive/hash, processed-output writes, chunk/task generation, and upload batch counts), so long runs should keep advancing status text instead of staying on `Merged split job results.`.
- Parsing chunk lanes are treated as `knowledge` or `noise` for active output behavior; narrative-like prose is routed to `noise` to align with freeform golden-set taxonomy.
- Interactive CLI menu selects (`C3imp` / `cookimport` without subcommands) treat `Backspace` as a one-level "back" action during menu navigation.
- Typer command functions that are also called directly from interactive helpers must use Python defaults (for example via `typing.Annotated[..., typer.Option(...)]`) so direct calls do not receive `OptionInfo` placeholders.
