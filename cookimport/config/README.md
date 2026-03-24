Run-configuration source of truth.
Detailed run-settings contracts live in `cookimport/config/CONVENTIONS.md`.

- `run_settings.py` defines canonical `RunSettings` used for interactive run selection, report `runConfig`, and analytics hashes/summaries.
  - `run_settings_types.py` now owns the enum/pipeline/helper cluster so `run_settings.py` stays focused on the model, validators, and contract registration.
  - `run_settings_contracts.py` is now the contract/projection owner for `operator`, `benchmark_lab`, and `raw/full` payload views.
  - `run_settings.py` configures the ordered field list and public/internal surface metadata that `run_settings_contracts.py` projects; the contracts module no longer imports `RunSettings` directly.
  - `run_settings_ui.py` now owns `RunSettingUiSpec` plus UI metadata projection, and `run_settings_builders.py` owns the large `build_run_settings(...)` constructor so the model file stays focused on the schema itself.
  - Includes deterministic instruction fallback segmentation knobs (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) shared by stage + benchmark prediction paths.
  - Includes Priority 6 parsing knobs (`p6_time_*`, `p6_temperature_*`, `p6_ovenlike_mode`, `p6_yield_mode`, `p6_emit_metadata_debug`) shared by stage + benchmark prediction paths.
- `codex_decision.py` is the shared Codex policy layer for top-tier profile patches, paired benchmark Codex/vanilla contracts, command-boundary approval checks, and persisted decision metadata.
- `run_settings_adapters.py` is the single mapping layer from `RunSettings` to concrete `stage(...)` and `labelstudio_benchmark(...)` kwargs used by interactive flows, speed suite, and import entrypoints.
  - It intentionally merges operator, benchmark-lab, internal, and fixed-behavior slices instead of treating the full schema as one flat public contract.
- `prediction_identity.py` narrows stage-specific reuse identities so prediction caches ignore runtime-only knobs but still miss when output-shaping settings change.
- `last_run_store.py` persists quality-suite winner settings under canonical `history_root_for_output(<output_dir>)/qualitysuite_winner_run_settings.json`.
  - Winner files are disposable cache for the current contract: loads read the canonical file shape only, and stale payloads are ignored instead of being migrated.
- To add a new run knob: add one field on `RunSettings` with `ui_*` metadata, wire it into pipeline execution where needed, and keep tests in `tests/llm/test_run_settings.py` passing.
