Interactive run-settings UI helpers.

- `run_settings_flow.py` asks `Use Codex Farm recipe pipeline for this run?` for interactive Import/Benchmark flows.
- `Yes` resolves `CodexFarm automatic top-tier` (winner-preferred when available).
- `Yes` also prompts for codex AI settings for that run:
  - `Codex Farm model override (blank for pipeline default)`
  - `Codex Farm reasoning effort override` (`Pipeline default`, `none`, `minimal`, `low`, `medium`, `high`, `xhigh`)
- `No` resolves `Vanilla automatic top-tier`.
- `CodexFarm` profile keeps the winner-preferred resolver path (quality-suite winner settings first, otherwise built-in top-tier baseline), then harmonizes recipe pipeline knobs to `llm_recipe_pipeline=codex-farm-3pass-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`.
  - Built-in codex fallback baseline pins `codex_farm_pass1_pattern_hints_enabled=false`.
  - Built-in codex fallback baseline pins `codex_farm_pass3_skip_pass2_ok=true`.
  - Winner-provided `codex_farm_pass1_pattern_hints_enabled` is preserved (not overwritten by harmonization).
  - Winner-provided `codex_farm_pass3_skip_pass2_ok` is preserved (not overwritten by harmonization).
- `Vanilla` profile uses a deterministic built-in baseline with codex disabled and deterministic line-role enabled (`llm_recipe_pipeline=off`, `line_role_pipeline=deterministic-v1`, `atomic_block_splitter=atomic-v1`, plus EPUB `v1 + br_split_v1 + skip_headers=false`).
  - Vanilla baseline explicitly pins `codex_farm_pass1_pattern_hints_enabled=false` (inert while recipe codex pipeline is off).
  - Vanilla baseline explicitly pins `codex_farm_pass3_skip_pass2_ok=true` (inert while recipe codex pipeline is off).
- `COOKIMPORT_TOP_TIER_PROFILE=codexfarm|vanilla` still overrides the interactive prompt.
