Interactive run-settings UI helpers.

- `run_settings_flow.py` resolves one automatic `top-tier default` profile for interactive Import/Benchmark flows.
- Resolution order: saved quality-suite winner profile first, otherwise built-in top-tier baseline (quality-first EPUB stack + codex/line-role/atomic enabled).
- Regardless of source, interactive flow harmonizes recipe pipeline knobs to top-tier (`llm_recipe_pipeline=codex-farm-3pass-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`) to avoid stale off/off winner snapshots.
- `toggle_editor.py` remains the full-screen row editor for manual run-settings editing utilities (arrow keys change values, `s` saves, `q`/`Esc` cancels).
