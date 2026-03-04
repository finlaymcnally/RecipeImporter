Interactive run-settings UI helpers.

- `run_settings_flow.py` asks `Use Codex Farm recipe pipeline for this run?` for interactive Import/Benchmark flows.
- `Yes` resolves `CodexFarm automatic top-tier` (winner-preferred when available).
- `No` resolves `Vanilla automatic top-tier`.
- `CodexFarm` profile keeps the winner-preferred resolver path (quality-suite winner settings first, otherwise built-in top-tier baseline), then harmonizes recipe pipeline knobs to `llm_recipe_pipeline=codex-farm-3pass-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`.
- `Vanilla` profile uses a deterministic built-in baseline with codex disabled and deterministic line-role enabled (`llm_recipe_pipeline=off`, `line_role_pipeline=deterministic-v1`, `atomic_block_splitter=atomic-v1`, plus EPUB `v1 + br_split_v1 + skip_headers=false`).
- `COOKIMPORT_TOP_TIER_PROFILE=codexfarm|vanilla` still overrides the interactive prompt.
- `toggle_editor.py` remains the full-screen row editor for manual run-settings editing utilities (arrow keys change values, `s` saves, `q`/`Esc` cancels).
