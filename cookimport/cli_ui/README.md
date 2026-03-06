Interactive run-settings UI helpers.

- `run_settings_flow.py` asks `Use Codex Farm recipe pipeline for this run?` for interactive Import/Benchmark flows.
- `Yes` resolves `CodexFarm automatic top-tier` (winner-preferred when available).
- `Yes` also prompts for codex AI settings for that run:
  - `Codex Farm model override` (menu-only: `Pipeline default`, optional `Keep current override`, discovered models, fallback `gpt-5.3-codex`)
  - `Codex Farm reasoning effort override` (`Pipeline default` plus only the efforts supported by the selected discovered model when that metadata is available)
- `No` resolves `Vanilla automatic top-tier`.
- `CodexFarm` profile keeps the winner-preferred resolver path (quality-suite winner settings first, otherwise built-in top-tier baseline), then harmonizes the full top-tier contract:
  - `llm_recipe_pipeline=codex-farm-3pass-v1`, `llm_knowledge_pipeline=codex-farm-knowledge-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`
  - parsing stack pinned to `unstructured + v1 + semantic_v1 + skip_headers=true`
  - deterministic parsing knobs pinned to `section_detector_backend=shared_v1`, `multi_recipe_splitter=rules_v1`, `instruction_step_segmentation_policy=always`, `instruction_step_segmenter=heuristic_v1`, `pdf_ocr_policy=off`
  - compact codex pass ids pinned to `recipe.schemaorg.compact.v1` and `recipe.final.compact.v1`
  - codex routing pins `codex_farm_pass1_pattern_hints_enabled=false`, `codex_farm_pass3_skip_pass2_ok=true`
- `Vanilla` profile uses the same top-tier deterministic parsing stack with codex disabled and deterministic line-role enabled (`llm_recipe_pipeline=off`, `llm_knowledge_pipeline=off`, `llm_tags_pipeline=off`, `line_role_pipeline=deterministic-v1`, `atomic_block_splitter=atomic-v1`).
- `COOKIMPORT_TOP_TIER_PROFILE=codexfarm|vanilla` still overrides the interactive prompt.
