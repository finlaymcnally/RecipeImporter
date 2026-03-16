# Staging Conventions

Output-path and artifact contracts for staging writers and merge flows.

## Report Output Convention

- The canonical stage report output path is set by `cookimport/staging/writer.py`:
  - `<run_root>/<workbook_slug>.excel_import_report.json`
- `cookimport/core/reporting.py` includes an older `ReportBuilder` that writes under `reports/`; it is not part of the active runtime flow.
- When updating docs about report locations, verify `stage()` and split-merge paths in `cookimport/cli.py` before documenting.
- Report metadata fields that must be consistent across normal and split runs (for example `importerName`, `runConfig`, `runConfigHash`, `runConfigSummary`) must be set in both:
  - `cookimport/cli_worker.py` (single-file writer path)
  - `cookimport/cli.py:_merge_split_jobs` (split merge writer path)

## Stage Block Prediction Convention

- Stage-producing flows must write `.bench/<workbook_slug>/stage_block_predictions.json` using `cookimport/staging/writer.py:write_stage_block_predictions`.
- Benchmark/eval code depends on this artifact being present for single-file stage runs, split-merge stage runs, and processed-output writes from `cookimport/labelstudio/ingest.py`.
- `KNOWLEDGE` labels in stage evidence should prefer explicit knowledge snippets (`knowledge/<workbook_slug>/snippets.jsonl`) and fall back to deterministic chunk lanes when snippets are absent.


## Recipe Section Artifact Convention

- Stage-producing flows now write per-recipe section artifacts to:
  - `sections/<workbook_slug>/r{index}.sections.json`
  - `sections/<workbook_slug>/sections.md`
- Keep section artifact writes wired in both:
  - `cookimport/cli_worker.py` (single-file stage path)
  - `cookimport/cli.py:_merge_split_jobs` (split merge path)
  - `cookimport/labelstudio/ingest.py` (pred-run artifact path)
- Intermediate JSON-LD section contract:
  - instruction section-header lines are removed from literal step text,
  - `recipeInstructions` uses `HowToSection` only when multiple sections are present,
  - ingredient grouping metadata is emitted under `recipeimport:ingredientSections`.
- Final cookbook3 draft contract remains unchanged (no first-class section objects in final draft JSON).
