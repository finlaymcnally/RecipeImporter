# Run Settings Conventions

Run-settings contracts for `cookimport/config/` and all call sites that consume `RunSettings`.

## Run Settings Source of Truth

- `cookimport/config/run_settings.py` is the canonical definition of per-run knobs (`RunSettings`), UI metadata, summary rendering, and stable hash generation.
- `cookimport/config/run_settings_adapters.py` is the canonical mapping from `RunSettings` to `stage(...)` / `labelstudio_benchmark(...)` kwargs; avoid duplicating field-by-field mapping in CLI or speed-suite callers.
- When a run-setting value changes split capability (for example `epub_extractor=markitdown`), update both split planners (`cookimport/cli.py:_plan_jobs`, `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs`) and `compute_effective_workers(...)` together.
- EPUB unstructured tuning knobs (`epub_unstructured_html_parser_version`, `epub_unstructured_skip_headers_footers`, `epub_unstructured_preprocess_mode`) are part of canonical run settings and must propagate in both stage and benchmark prediction paths; do not wire them only in one flow.
- Ingredient parser knobs (`ingredient_text_fix_backend`, `ingredient_pre_normalize_mode`, `ingredient_packaging_mode`, `ingredient_parser_backend`, `ingredient_unit_canonicalizer`, `ingredient_missing_unit_policy`) must propagate through stage and benchmark prediction-generation imports and be consumed by draft conversion (`cookimport/staging/draft_v1.py` -> `cookimport/parsing/ingredients.py`).
- EPUB extractor auto mode is removed from stage/prediction flows; accepted choices are explicit only: `unstructured`, `beautifulsoup`, `markdown`, `markitdown`.
- Stored run-settings migration must coerce older `epub_extractor=auto` payloads to `unstructured` and `epub_extractor=legacy` payloads to `beautifulsoup` with warnings so older snapshots stay loadable.
- Run-config persistence still includes both `epub_extractor_requested` and `epub_extractor_effective`; in current explicit-choice mode they should match for new runs.
- Runtime env overrides for EPUB extraction options in prediction/stage helper flows must be scoped and restored after conversion; do not leak `C3IMP_EPUB_*` values across runs/tests.
- `stage(...)` should pass per-file effective extractor choices explicitly to workers (`stage_one_file` / `stage_epub_job`) instead of depending on persistent process-wide `C3IMP_EPUB_EXTRACTOR`.
- `cookimport/cli_ui/run_settings_flow.py` is the only interactive run-profile chooser; keep it limited to the two automatic top-tier profile families (`codexfarm`, `vanilla`) so import and benchmark stay in lock-step.
- Quality-suite winner persistence lives in `history_root_for_output(output_dir)/qualitysuite_winner_run_settings.json` via `cookimport/config/last_run_store.py` (repo-local default `.history/...`; older `<output_dir>/.history/...` and prior `<output_dir parent>/.history/...` paths remain read-only fallback for migration).
- Schema evolution contract for stored run settings: missing keys default, unknown keys are ignored (warn once), and corrupt payloads degrade to `None` (treated as no saved run settings).
- codex-farm knobs (`llm_recipe_pipeline`, `llm_knowledge_pipeline`, `llm_tags_pipeline`, `codex_farm_cmd`, `codex_farm_model`, `codex_farm_reasoning_effort`, `codex_farm_root`, `codex_farm_workspace_root`, `codex_farm_pipeline_pass1`, `codex_farm_pipeline_pass2`, `codex_farm_pipeline_pass3`, `codex_farm_pipeline_pass4_knowledge`, `codex_farm_pipeline_pass5_tags`, `codex_farm_context_blocks`, `codex_farm_knowledge_context_blocks`, `tag_catalog_json`, `codex_farm_failure_mode`) must be wired through stage and benchmark prediction-generation paths, and persisted in run-config surfaces (manifest/report/history).
- benchmark line-role knobs (`atomic_block_splitter`, `line_role_pipeline`) must be wired through benchmark prediction generation, persisted in run manifests/reports/cutdown summaries, and kept separate from `llm_recipe_pipeline` intent.
- `table_extraction` is a run setting (`off|on`) that gates deterministic table detection/export (`tables/<workbook>/tables.jsonl` + `tables.md`), table-aware chunking, and optional pass4 `chunk.blocks[*].table_hint` enrichment; keep these surfaces in sync when changing table behavior.
- Chunk-consolidation contract: table chunks (`provenance.table_ids` present) must never merge with non-table chunks (or other table chunks) in either `merge_small_chunks` or adjacent-topic consolidation. Debug/rollback knob for consolidation remains `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0`.
- `llm_recipe_pipeline` accepts `off|codex-farm-3pass-v1` without environment gating; CLI/pred-run normalization should enforce only enum validity.
- codex-farm orchestration should pass explicit `--root`/`--workspace-root` when those run settings are provided, and `llm_manifest.json` should record the effective pass pipeline ids.
- pass5 tags artifacts are stage-run scoped and should stay in:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/tags_index.json`
  - `raw/llm/<workbook_slug>/pass5_tags/{in,out}/*.json` + `raw/llm/<workbook_slug>/pass5_tags_manifest.json`
- Default local codex-farm recipe pass prompts live in `llm_pipelines/prompts/recipe.{chunking,schemaorg,final}.v1.prompt.md`; text-only tuning should happen there without touching orchestration code.
- For local codex-farm packs, pipeline JSON `prompt_template_path` / `output_schema_path` entries are the source of truth; avoid keeping duplicate filename schemes in `llm_pipelines/prompts/` that are not referenced by those pipeline specs.
- New processing-option contract (do all, or the feature is incomplete):
  - add option to `RunSettings` + interactive selectors,
  - pass it through both run-producing command paths (`stage` and benchmark prediction generation),
  - persist it in report/manifest + history CSV run-config fields,
  - expose it in dashboard collector/renderer surfaces.
- Pipeline option edit-map references:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/core/models.py`
  - `cookimport/analytics/perf_report.py`
  - `cookimport/analytics/dashboard_collect.py`
  - `cookimport/analytics/dashboard_render.py`
