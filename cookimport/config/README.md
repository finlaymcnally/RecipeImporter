Run-configuration source of truth.
Detailed run-settings contracts live in `cookimport/config/CONVENTIONS.md`.

- `run_settings.py` defines canonical `RunSettings` used for interactive run selection, report `runConfig`, and analytics hashes/summaries.
  - Includes deterministic instruction fallback segmentation knobs (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) shared by stage + benchmark prediction paths.
  - Includes Priority 6 parsing knobs (`p6_time_*`, `p6_temperature_*`, `p6_ovenlike_mode`, `p6_yield_mode`, `p6_emit_metadata_debug`) shared by stage + benchmark prediction paths.
- `run_settings_adapters.py` is the single mapping layer from `RunSettings` to concrete `stage(...)` and `labelstudio_benchmark(...)` kwargs used by interactive flows, speed suite, and import entrypoints.
- `prediction_identity.py` narrows stage-specific reuse identities so prediction caches ignore runtime-only knobs but still miss when output-shaping settings change.
- `last_run_store.py` persists quality-suite winner settings under canonical `history_root_for_output(<output_dir>)/qualitysuite_winner_run_settings.json` (repo-local default: `.history/...`), with legacy read fallback for `<output_dir>/.history/...` and prior `<output_dir parent>/.history/...` locations.
- To add a new run knob: add one field on `RunSettings` with `ui_*` metadata, wire it into pipeline execution where needed, and keep tests in `tests/llm/test_run_settings.py` passing.
