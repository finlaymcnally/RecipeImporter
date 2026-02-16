---
summary: "Quick code map for where new processing-pipeline options must be wired across CLI selectors, run config tracking, and freeform benchmark paths."
read_when:
  - "When adding a new RunSettings option and deciding exactly which files to edit"
  - "When an option appears in import runs but is missing from benchmark/freeform eval history"
---

# New Pipeline Option Contract

For every new option/feature added to the processing pipeline, all three are required:

1. Add it to the CLI run-settings selectors so it can be configured per run.
2. Track it in dashboard/history data by saving it in `.csv` under `run config`.
3. Apply it in both paths:
   - `import` (produce cookbook outputs)
   - `evaluate predictions vs freeform gold`

If any one of these is missing, the feature is incomplete.

# Pipeline Option Edit Map

For every new processing option, wire these locations together.

## 1) Define the option and make it selectable in CLI run settings

- `cookimport/config/run_settings.py`
  - Add the field on `RunSettings` with `_ui_meta(...)`.
  - Include it in `_SUMMARY_ORDER` if it should appear in run summaries.
  - Add it to `build_run_settings(...)`.
  - If the option changes split/parallel behavior, update `compute_effective_workers(...)` so run-config summaries/history reflect real execution.
- `cookimport/cli_ui/run_settings_flow.py`
  - `choose_run_settings(...)` is the selector entrypoint (global/last/edit).
- `cookimport/cli_ui/toggle_editor.py`
  - Uses `run_settings_ui_specs()` from `RunSettings`; new fields appear automatically.

## 2) Pass the option through CLI commands that launch processing

- `cookimport/cli.py`
  - Update validation/normalization helpers (for example `_normalize_epub_extractor(...)`) so direct CLI flags accept the new value.
  - Interactive import menu passes selected settings into `stage(...)` (`common_args`).
  - `stage(...)` builds canonical `RunSettings` and derives `run_config/hash/summary`.
  - If the option affects split planning, update `_plan_jobs(...)` so stage split ranges match extractor capabilities.
  - Interactive benchmark menu passes selected settings into `labelstudio_benchmark(...)`.
  - `labelstudio_benchmark(...)` forwards settings to prediction generation.
- `cookimport/labelstudio/ingest.py`
  - `generate_pred_run_artifacts(...)` accepts processing knobs and builds canonical `RunSettings`.
  - If the option affects split planning, update `_plan_parallel_convert_jobs(...)` to keep benchmark prediction import behavior aligned with stage.

## 3) Ensure dashboard/history tracking (`run config`) is preserved

- `cookimport/core/models.py`
  - `ConversionReport` carries `runConfig`, `runConfigHash`, `runConfigSummary`.
- `cookimport/cli_worker.py` and `cookimport/labelstudio/ingest.py`
  - Write run-config fields into per-file reports/manifests.
- `cookimport/analytics/perf_report.py`
  - `append_history_csv(...)` and `append_benchmark_csv(...)` persist `run_config_json/hash/summary`.
  - `_CSV_FIELDS` defines the history CSV schema columns.
- `cookimport/analytics/dashboard_collect.py`
  - Reads `run_config_json/hash/summary` from CSV (primary source).
- `cookimport/analytics/dashboard_render.py`
  - Renders run-config summary/hash in the dashboard tables.

## 4) Apply the option in both required execution paths

- Import path (produce cookbook outputs):
  - `cookimport/cli.py` `stage(...)` and downstream `cookimport/cli_worker.py`.
- Freeform evaluation path that generates predictions:
  - `cookimport/cli.py` `labelstudio_benchmark(...)`
  - `cookimport/labelstudio/ingest.py` `generate_pred_run_artifacts(...)`
  - `cookimport/cli.py` `_load_pred_run_recipe_context(...)` and `append_benchmark_csv(...)`

Note: `labelstudio-eval` eval-only mode scores an existing `pred_run`; it does not rerun the pipeline.
