Run-configuration source of truth.
Detailed run-settings contracts live in `cookimport/config/CONVENTIONS.md`.

- `run_settings.py` defines canonical `RunSettings` used for interactive run selection, report `runConfig`, and analytics hashes/summaries.
- `last_run_store.py` persists per-operation last settings under `<output_dir_parent>/.history/last_run_settings_{import|benchmark}.json` (with legacy `<output_dir>/.history/...` read fallback).
- To add a new run knob: add one field on `RunSettings` with `ui_*` metadata, wire it into pipeline execution where needed, and keep tests in `tests/test_run_settings.py` passing.
