---
summary: "ExecPlan roadmap for decomposing the repo's largest handwritten modules without changing runtime semantics."
read_when:
  - When planning ownership splits for oversized analytics, bench, Label Studio, parsing, or LLM runtime modules
  - When deciding whether a giant file should stay a composition root or move helpers into sibling owner modules
---

# Decompose The Largest Hand-Written Modules Without Changing Runtime Semantics

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

The repo currently has several hand-written modules that are large enough to slow down safe edits, make ownership unclear, and force contributors to understand too many unrelated concerns before making one change. After this plan is implemented, the same commands and artifacts should still work, but the biggest files will each have one clearer job. A future contributor should be able to open a target module and answer “what does this file own?” in one sentence.

This is not a behavior-change plan. The goal is structural decomposition with stable runtime contracts. The proof is that the same domain tests still pass while the largest files shrink or become thin facades over smaller owner modules.

This roadmap is the broad source of truth for the whole decomposition effort. The narrower follow-on plan at [docs/plans/decomp2-finish-owner-module-decomposition.md](/home/mcnal/projects/recipeimport/docs/plans/decomp2-finish-owner-module-decomposition.md) does not replace this roadmap. It covers the currently active cleanup slice for the remaining transitional compatibility scaffolding and the still-oversized bench, line-role, direct-exec, and external-AI roots.

## Progress

- [x] (2026-04-01 23:18 America/Toronto) Read `docs/PLANS.md`, `docs/01-architecture/01-architecture_README.md`, `docs/AI_context.md`, and the subsystem docs for CLI, parsing, Label Studio, bench, analytics, and LLM.
- [x] (2026-04-01 23:18 America/Toronto) Measured large-file line counts and confirmed the largest current handwritten modules are concentrated in bench, line-role runtime, direct-exec runtime, recipe-stage shared code, analytics, Label Studio, and prompt tooling.
- [x] (2026-04-01 23:18 America/Toronto) Skimmed the largest files to identify whether each one is a real multi-responsibility file, an orchestration hub that should stay partially centralized, or an embedded asset that should move out of Python.
- [x] (2026-04-01 23:18 America/Toronto) Wrote the initial decomposition roadmap for the large-file set the user asked about.
- [x] (2026-04-01 23:53 America/Toronto) Completed Milestone 1 for dashboard assets: `cookimport/analytics/dashboard_renderers/assets/script_filters.js` and `assets/script_tables.js` are now the JS source of truth, while `script_filters.py` and `script_tables.py` became thin loaders.
- [x] (2026-04-01 23:53 America/Toronto) Landed the first analytics-wave helper extraction by moving benchmark manifest runtime/token enrichment into `cookimport/analytics/benchmark_manifest_runtime.py` and rewiring both `dashboard_collect.py` and `perf_report.py` to use it.
- [x] (2026-04-01 23:53 America/Toronto) Ran the targeted analytics proof set: `pytest tests/analytics/test_stats_dashboard.py tests/analytics/test_stats_dashboard_benchmark_semantics.py tests/analytics/test_stats_dashboard_collectors.py tests/analytics/test_perf_report.py` -> `77 passed`.
- [x] (2026-04-01 23:58 America/Toronto) Updated `docs/08-analytics/08-analytics_readme.md` and `cookimport/analytics/dashboard_renderers/README.md` so the new analytics helper owner and checked-in JS asset owners are documented where contributors will look first.
- [x] (2026-04-02 00:15 America/Toronto) Finished the ExecPlan maintenance pass by adding required docs front matter, refreshing the current-state notes, and recording the post-Milestone-1 size markers so `docs:list` and future contributors see the real current status.
- [x] (2026-04-02 00:34 America/Toronto) Completed the pending compare/control split for Milestone 2 by extracting `compare_control_constants.py`, `compare_control_errors.py`, `compare_control_fields.py`, `compare_control_filters.py`, and `compare_control_analysis.py`, leaving `compare_control_engine.py` as a 69-line public facade.
- [x] (2026-04-02 00:34 America/Toronto) Ran the Milestone 2 proof set in the project venv: `pytest tests/analytics/test_compare_control_engine.py -q`, `pytest tests/analytics/test_compare_control_cli.py -q`, and `./scripts/test-suite.sh domain analytics` -> `92 passed, 31 deselected`.
- [x] (2026-04-02 00:34 America/Toronto) Updated `docs/08-analytics/08-analytics_readme.md`, `cookimport/analytics/README.md`, and a task note so the new compare/control owners are documented where contributors will look first.
- [x] (2026-04-02 10:56 America/Toronto) Completed the prelabel and prompt-budget facade splits by keeping `prelabel.py` and `prompt_budget.py` import-stable while moving provider/prompt/mapping logic into `prelabel_codex.py`, `prelabel_parse.py`, `prelabel_mapping.py`, `prelabel_prompt.py`, and runtime/preview cost logic into `prompt_budget_runtime.py` plus `prompt_budget_preview.py`.
- [x] (2026-04-02 10:56 America/Toronto) Finished the next `prompt_artifacts.py` owner cut by extracting the manifest/CSV/attachment/runtime-context loader layer into `prompt_artifacts_loader.py`, leaving the public facade at 702 lines.
- [x] (2026-04-02 10:56 America/Toronto) Landed the first command-surface Label Studio split by moving interrupted benchmark finalization into `cookimport/cli_support/labelstudio_benchmark_recovery.py` and transient eval-output pruning/selective-retry summarization into `cookimport/cli_support/labelstudio_benchmark_artifacts.py`, reducing `cli_commands/labelstudio.py` to 3559 lines.
- [x] (2026-04-02 11:14 America/Toronto) Landed the first deep `recipe_stage_shared.py` owner cut by extracting worker-visible payload/schema helpers into `cookimport/llm/recipe_stage/task_file_contract.py` and prompt/jsonl/input/path helpers into `cookimport/llm/recipe_stage/worker_io.py`, reducing `recipe_stage_shared.py` to 1647 lines.
- [x] (2026-04-02 11:14 America/Toronto) Proved the recipe-stage split with `python -m py_compile cookimport/llm/recipe_stage_shared.py cookimport/llm/recipe_stage/task_file_contract.py cookimport/llm/recipe_stage/worker_io.py`, `pytest tests/llm/test_recipe_same_session_handoff.py tests/llm/test_recipe_phase_workers.py -q`, and `pytest tests/staging/test_pipeline_runtime.py -q`.
- [x] (2026-04-02 11:14 America/Toronto) Landed the next deep-runtime cuts by extracting inline-JSON packet/prompt/answer helpers out of `cookimport/llm/knowledge_stage/workspace_run.py` into `cookimport/llm/knowledge_stage/structured_session_contract.py`, and by moving the shared direct-exec protocol/live-snapshot/watchdog dataclasses from `cookimport/llm/codex_exec_runner.py` into `cookimport/llm/codex_exec_types.py`.
- [x] (2026-04-02 11:14 America/Toronto) Proved those runtime cuts in the project venv with `python -m py_compile cookimport/llm/knowledge_stage/workspace_run.py cookimport/llm/knowledge_stage/structured_session_contract.py cookimport/llm/codex_exec_runner.py cookimport/llm/codex_exec_types.py` and `.venv/bin/pytest tests/llm/test_codex_exec_runner.py tests/llm/test_codex_exec_runner_taskfile.py tests/llm/test_knowledge_orchestrator_runtime_leasing.py tests/llm/test_knowledge_stage_promotion.py tests/llm/test_knowledge_same_session_handoff.py -q`.
- [x] (2026-04-02 11:14 America/Toronto) Landed the next knowledge-runtime owner cut by extracting task-status tracking, stale follow-up finalization, and stage-status writing out of `cookimport/llm/knowledge_stage/recovery.py` into `cookimport/llm/knowledge_stage/recovery_status.py`, reducing `recovery.py` to 2092 lines.
- [x] (2026-04-02 11:14 America/Toronto) Proved the recovery-status split with `python -m py_compile cookimport/llm/knowledge_stage/runtime.py cookimport/llm/knowledge_stage/recovery.py cookimport/llm/knowledge_stage/recovery_status.py` and `.venv/bin/pytest tests/llm/test_knowledge_stage_bindings.py tests/llm/test_knowledge_orchestrator_runtime_leasing.py tests/llm/test_knowledge_orchestrator_runtime_progress.py tests/llm/test_knowledge_same_session_handoff.py tests/llm/test_knowledge_stage_promotion.py -q`.
- [x] (2026-04-02 12:52 America/Toronto) Landed the first large all-method bench split by moving benchmark target discovery into `cookimport/cli_support/bench_all_method_targets.py`, variant/codex matrix building into `bench_all_method_variants.py`, QualitySuite compare-control bridge writing into `bench_all_method_qualitysuite.py`, and dashboard/report helpers into `bench_all_method_reporting.py`, with shared dataclasses in `bench_all_method_types.py`. `bench_all_method.py` remained the public orchestration root and dropped from 9422 lines to 6874.
- [x] (2026-04-02 12:52 America/Toronto) Proved the all-method bench split with `python -m py_compile` across the extracted modules plus `.venv/bin/pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_targets.py tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py tests/labelstudio/test_labelstudio_benchmark_helpers_progress_dashboard.py tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_run_reports.py tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_run.py tests/bench/test_bench_quality_cli.py -q`.
- [x] (2026-04-02 12:52 America/Toronto) Landed the first external-AI cutdown package split by creating `cookimport/bench/external_ai_cutdown/` and moving run/output-root discovery into `discovery.py`, deterministic JSON/JSONL plus clipping/sampling helpers into `io.py`, and canonical-line/gold-span sampling helpers into `canonical_lines.py`. `scripts/benchmark_cutdown_for_external_ai.py` remained the public wrapper and dropped from 16488 lines to 16098.
- [x] (2026-04-02 12:52 America/Toronto) Proved the external-AI cutdown extraction with `python -m py_compile scripts/benchmark_cutdown_for_external_ai.py cookimport/bench/external_ai_cutdown/*.py` and `.venv/bin/pytest tests/bench/test_benchmark_cutdown_for_external_ai.py tests/bench/test_benchmark_cutdown_for_external_ai_high_level.py tests/bench/test_benchmark_cutdown_for_external_ai_starter_pack.py tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle.py tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle_runtime.py -q`.
- [x] (2026-04-04 11:57 America/Toronto) Moved this roadmap into `docs/plans/` and established [docs/plans/decomp2-finish-owner-module-decomposition.md](/home/mcnal/projects/recipeimport/docs/plans/decomp2-finish-owner-module-decomposition.md) as the focused follow-on plan for the remaining transitional cleanup.
- [x] (2026-04-04 12:19 America/Toronto) Landed the compatibility-removal slice from the focused finish plan: `bench_all_method_types.py`, `bench_all_method_targets.py`, `bench_all_method_variants.py`, `bench_all_method_reporting.py`, `bench_all_method_qualitysuite.py`, `codex_exec_workspace.py`, `canonical_line_roles/runtime.py`, and `runtime_recovery.py` now use explicit imports or narrow call-time hook resolution instead of `sys.modules[...]` plus `globals().update(...)`.
- [x] (2026-04-04 12:19 America/Toronto) Proved that cleanup slice with `python3 -m py_compile` on the touched owner modules, targeted bench/LLM/parsing pytest suites, and repo-preferred `./scripts/test-suite.sh domain bench` (`338 passed`), `./scripts/test-suite.sh domain llm` (`288 passed, 50 deselected`), and `./scripts/test-suite.sh domain parsing` (`245 passed, 172 deselected`).
- [x] (2026-04-04 13:02 America/Toronto) Landed the next bench-root cut from the focused finish plan by extracting scheduler/runtime planning, resource-guard sizing, and process-pool probe helpers into `cookimport/cli_support/bench_all_method_scheduler.py`, reducing `bench_all_method.py` from `6874` to `6396` lines while preserving the historical `cookimport.cli` monkeypatch seams through explicit call-time hook resolution.
- [x] (2026-04-04 13:16 America/Toronto) Extended `bench_all_method_scheduler.py` to own source-cost estimation, shard planning, and global work-item planning too, reducing `bench_all_method.py` further from `6396` to `6097` lines while keeping `_estimate_all_method_source_cost` patchable through the public root.
- [x] (2026-04-04 13:41 America/Toronto) Completed the next bench-root cleanup by converting `bench_cache.py` into an explicit owner for split-cache, prediction-reuse, eval-signature, and cached-eval helpers, then deleting the duplicate block from `bench_all_method.py`; the root dropped further from `6097` to `5442` lines and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 14:10 America/Toronto) Continued the deep LLM wave by extracting direct-exec telemetry/watchdog summaries into `cookimport/llm/codex_exec_telemetry.py`, moving direct-exec argv/fs-cage assembly into `cookimport/llm/codex_exec_command_builder.py`, and replacing `globals().update(...)` in `knowledge_stage/runtime.py` plus `knowledge_stage/recovery.py` with explicit imports. `codex_exec_runner.py` dropped to `3144` lines, the knowledge hidden-compatibility pattern is gone, and `./scripts/test-suite.sh domain llm` stayed green.
- [x] (2026-04-04 14:25 America/Toronto) Continued the parsing/runtime wave by replacing `sys.modules[...]` plus `globals().update(...)` in `canonical_line_roles/planning.py`, `policy.py`, and `validation.py` with explicit imports, then extracting the line-role taskfile/output-expansion block into `canonical_line_roles/runtime_taskfile.py`. `canonical_line_roles/runtime.py` dropped to `4991` lines and `./scripts/test-suite.sh domain parsing` stayed green.
- [x] (2026-04-04 15:06 America/Toronto) Resumed the external-AI cutdown package split by extracting prompt-log parsing/convenience rendering into `cookimport/bench/external_ai_cutdown/prompt_logs.py` and project-context metadata/digest rendering into `cookimport/bench/external_ai_cutdown/project_context.py`. The wrapper kept thin compatibility shims for `_prompt_category_sort_key` and the patch-sensitive `PROJECT_CONTEXT_REL_PATH` seam, `scripts/benchmark_cutdown_for_external_ai.py` dropped from `16098` to `15681` lines, the external-AI cutdown proof set passed (`62 passed`), and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 15:18 America/Toronto) Continued the external-AI cutdown split by extracting prompt/prediction/processed-output artifact-path resolution into `cookimport/bench/external_ai_cutdown/artifact_paths.py`. The script kept thin wrappers for tested helpers such as `_resolve_knowledge_prompt_path(...)`, dropped further from `15681` to `15486` lines, the external-AI cutdown proof set stayed green (`62 passed`), and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 15:31 America/Toronto) Continued the external-AI cutdown split by extracting deterministic `full_prompt_log.jsonl` reconstruction into `cookimport/bench/external_ai_cutdown/prompt_log_reconstruction.py` and recipe-span projection plus line-prediction views into `cookimport/bench/external_ai_cutdown/line_projection.py`. The wrapper kept thin tested helpers such as `_reconstruct_full_prompt_log(...)` and `_build_recipe_spans_from_full_prompt_rows(...)`, dropped further from `15486` to `14957` lines, the external-AI cutdown proof set stayed green (`62 passed`), and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 15:46 America/Toronto) Continued the external-AI cutdown split by extracting prompt-response warning/correction interpretation into `cookimport/bench/external_ai_cutdown/prompt_diagnostics.py` and wrong-label/preprocess compressed packet generation into `cookimport/bench/external_ai_cutdown/diagnostic_packets.py`. The wrapper kept thin tested/monkeypatched helpers such as `_summarize_prompt_warning_aggregate(...)` and `_build_preprocess_trace_failure_rows(...)`, dropped further from `14957` to `14538` lines, the external-AI cutdown proof set stayed green (`62 passed`), and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 16:00 America/Toronto) Continued the external-AI cutdown split by extracting alignment-health checks, projection-trace summaries, and shared prompt-row helper views into `cookimport/bench/external_ai_cutdown/projection_trace.py`. The wrapper kept thin helper wrappers such as `_build_projection_trace(...)` and `_prompt_row_stage_key(...)`, dropped further from `14538` to `14388` lines, the external-AI cutdown proof set stayed green (`62 passed`), and `./scripts/test-suite.sh domain bench` remained green.
- [x] (2026-04-04 16:05 America/Toronto) Continued the external-AI cutdown split by extracting per-run cutdown assembly plus existing-run record hydration into `cookimport/bench/external_ai_cutdown/run_cutdown.py`. The wrapper kept thin helper wrappers for `_build_run_cutdown(...)` and `_build_run_record_from_existing_run(...)`, dropped further from `14388` to `14012` lines, and the direct run-cutdown pytest slice, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [x] (2026-04-04 16:15 America/Toronto) Continued the external-AI cutdown split by extracting prompt-row excerpt/scoring helpers used by pair diagnostics into `cookimport/bench/external_ai_cutdown/prompt_case_views.py`. The wrapper kept thin helper wrappers for `_prompt_case_score(...)`, `_input_excerpt_for_prompt_row(...)`, and related prompt-row utilities, dropped further from `14012` to `13923` lines, and the direct pair-diagnostics pytest slice, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [x] (2026-04-04 16:33 America/Toronto) Continued the external-AI cutdown split by extracting pair diagnostics plus comparison-summary/trace aggregation into `cookimport/bench/external_ai_cutdown/comparison_diagnostics.py`. The wrapper kept thin helper wrappers for `_build_pair_diagnostics(...)`, `_build_comparison_summary(...)`, `_build_warning_and_trace_summary(...)`, `_aggregate_region_accuracy(...)`, and `_aggregate_confusion_deltas(...)`, dropped further from `13923` to `12865` lines, and the direct comparison pytest slice, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [x] (2026-04-04 16:46 America/Toronto) Continued the external-AI cutdown split by extracting starter-pack recipe selection, casebook rendering, packet assembly helpers, and starter-pack README rendering into `cookimport/bench/external_ai_cutdown/starter_pack.py`. The wrapper kept thin helper wrappers for `_select_starter_pack_recipe_cases(...)`, `_build_selected_recipe_packets(...)`, `_render_starter_pack_casebook(...)`, and `_write_starter_pack_readme(...)`, dropped further from `12865` to `12365` lines, and the direct starter-pack pytest slice, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [x] (2026-04-04 16:58 America/Toronto) Continued the external-AI cutdown split by extracting root README generation, flattened markdown assembly, aggregated root-summary writing, and in-place starter-pack flattened-summary writing into `cookimport/bench/external_ai_cutdown/root_rendering.py`. The wrapper kept thin helper wrappers for `_write_readme(...)`, `_flatten_output(...)`, `_write_root_summary_markdown(...)`, and `write_flattened_summary_for_existing_runs(...)`, dropped further from `12365` to `12180` lines, and the focused root-output pytest slices, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [x] (2026-04-04 17:12 America/Toronto) Continued the external-AI cutdown split by extracting the heavier starter-pack assembly root into `cookimport/bench/external_ai_cutdown/starter_pack_writer.py`. The wrapper kept a thin helper wrapper for `_write_starter_pack_v1(...)`, dropped further from `12180` to `11841` lines, and the focused starter-pack pytest slice, full external-AI proof set (`62 passed`), and `./scripts/test-suite.sh domain bench` (`338 passed`) all stayed green.
- [ ] Continue the decomposition in small atomic cuts, with Milestone 4 now actively in progress on the remaining deep runtime coordinators.
- [ ] Re-run the relevant domain suites after each milestone and the full targeted suite set at the end.

## Surprises & Discoveries

- Observation: some “large files” are not large because they own too much Python logic; they are large because they embed long JavaScript assets as Python triple-quoted strings.
  Evidence: `cookimport/analytics/dashboard_renderers/script_filters.py` and `cookimport/analytics/dashboard_renderers/script_tables.py` are basically `_JS_*` string assets rather than ordinary mixed-logic Python modules.

- Observation: `cookimport/labelstudio/ingest_flows/prediction_run.py` is large mostly because one top-level function owns too many phases.
  Evidence: the file exposes only a couple of top-level defs, with `generate_pred_run_artifacts(...)` acting as the dominant orchestrator.

- Observation: `cookimport/cli_support/bench_all_method.py` and `cookimport/cli_support/bench_single_book.py` are already living on top of a compatibility/facade pattern tied to `cookimport.cli_support.bench`.
  Evidence: both files import `sys.modules["cookimport.cli_support.bench"]` and then re-export runtime state through `globals().update(...)`.

- Observation: the biggest LLM files are not all “bad giant utility files.” Some are true runtime coordinators that should remain as composition roots after extraction.
  Evidence: `cookimport/llm/codex_exec_runner.py`, `cookimport/parsing/canonical_line_roles/runtime.py`, `cookimport/llm/knowledge_stage/workspace_run.py`, and `cookimport/llm/recipe_stage_shared.py` each mix a coordinator role with several extractable support layers.

- Observation: analytics currently duplicates similar manifest/token/runtime extraction logic across more than one large module.
  Evidence: `cookimport/analytics/dashboard_collect.py` and `cookimport/analytics/perf_report.py` both contain large token/runtime backfill helpers with similar responsibilities and naming.

- Observation: moving embedded dashboard assets out of Python made the intended ownership boundary immediately obvious because the retained Python seams collapsed to almost nothing.
  Evidence: `wc -l` now reports `5` lines each for `cookimport/analytics/dashboard_renderers/script_filters.py` and `script_tables.py`, while the owned JS payloads live in `assets/script_filters.js` and `assets/script_tables.js`.

- Observation: the compare/control split shrank the old public engine much more than expected once the error/filter/state seams were pulled out explicitly.
  Evidence: `wc -l` now reports `69` lines for `cookimport/analytics/compare_control_engine.py`, with `compare_control_fields.py`, `compare_control_filters.py`, and `compare_control_analysis.py` owning the extracted logic.

- Observation: the prelabel root needed explicit facade compatibility hooks after extraction because tests and callers monkeypatch the public `prelabel` module rather than the new owner modules directly.
  Evidence: `prelabel.py` now synchronizes prompt-template overrides and `run_codex_farm_json_prompt` into the extracted owner modules before delegating, which restored the existing patch/test surface without re-growing the old file.

- Observation: AST-assisted splits of prompt tooling and recipe-stage helpers were fast, but they surfaced missing cross-module imports, dropped decorators, and one package-level monkeypatch seam that runtime tests caught immediately.
  Evidence: the first post-split test pass failed on missing `@dataclass` for prompt descriptor types plus missing imports such as `_rows_for_stage`, `_clean_text`, and `_prompt_stage_metadata_from_row`; fixing those kept the structural split while preserving behavior.

- Observation: `bench_all_method.py` cannot safely freeze many helper imports because the benchmark helper tests monkeypatch the public module surface directly.
  Evidence: the first extracted `_resolve_benchmark_gold_and_source(...)` pass failed until the extracted target owner resolved patchable helpers from the public `cookimport.cli_support.bench_all_method` module at call time and the public root continued to re-export `_require_importer`.

- Observation: the scheduler/runtime slice had the same public-root patchability requirement as the earlier target-resolution split.
  Evidence: scheduler and quality-suite tests patch `cookimport.cli._system_total_memory_bytes`, `cookimport.cli._probe_all_method_process_pool_executor`, `cookimport.cli._run_all_method_prediction_once`, and `cookimport.cli.ProcessPoolExecutor`, so the new `bench_all_method_scheduler.py` owner must resolve those exports at call time instead of capturing local copies.

- Observation: the planning layer used the same pattern once source-estimation logic moved under the scheduler owner.
  Evidence: planning/global-queue tests monkeypatch `cookimport.cli._estimate_all_method_source_cost`, so `_plan_all_method_source_jobs(...)` now resolves that estimator from the public root at call time before computing shard plans.

- Observation: `bench_cache.py` had already become the de facto owner for cache/reuse helpers before it was a clean explicit owner.
  Evidence: the file already duplicated the single-book split-cache, prediction-reuse key, artifact-copy, and eval-signature helpers that were still also defined in `bench_all_method.py`, so the right next cut was to finish `bench_cache.py` rather than introduce another helper module.

- Observation: once this roadmap moved under `docs/plans/`, it needed an explicit relationship statement so contributors would not treat the newer finish plan as a competing source of truth.
  Evidence: both plans now live side-by-side under `docs/plans/`, and the newer one is intentionally a focused continuation of this roadmap rather than a replacement.

- Observation: `recipe_stage/__init__.py` could not keep its old eager-import surface once `recipe_stage_shared.py` began importing extracted owner modules beneath the package.
  Evidence: importing `cookimport.llm.recipe_stage.task_file_contract` through the old package bootstrap caused a partial-init cycle, so the package now uses lazy forwarding to preserve the old public alias surface without reintroducing the cycle.

- Observation: the next safe knowledge-stage split was not another orchestrator function but the structured-session contract block embedded inside `workspace_run.py`.
  Evidence: packet builders, structured prompts, answer merge/apply helpers, and same-session packet metadata were pure stage-local helpers with no subprocess coupling, so moving them into `knowledge_stage/structured_session_contract.py` reduced `workspace_run.py` to 1918 lines without changing the worker loop.

- Observation: the next safe `recovery.py` cut was the status/finalization layer, but it exposed the same stale-monkeypatch pattern seen earlier in recipe and knowledge survivability tests.
  Evidence: after extracting task-status and stage-status helpers into `knowledge_stage/recovery_status.py`, the progress suite failed only when an earlier test monkeypatched `_build_knowledge_shard_survivability_report`; resolving the builder from `_shared` at runtime fixed the order-dependent leak.

- Observation: the same stale-monkeypatch pattern showed up again once the line-role runtime stopped copying the package namespace into itself.
  Evidence: after replacing `globals().update(...)` in `canonical_line_roles/runtime.py`, the parsing and LLM suites failed until the runtime resolved test-sensitive constants and `_build_line_role_shard_survivability_report` from the package surface explicitly at call time.

- Observation: the remaining knowledge-stage cleanup was still hiding in the coordinator roots rather than the already-extracted owner files.
  Evidence: `knowledge_stage/runtime.py` and `knowledge_stage/recovery.py` still cloned `_shared` into their globals until this slice replaced that pattern with explicit imports and preserved only the small re-export surface that tests instantiate directly.

- Observation: the next direct-exec root cut had to preserve runner-local monkeypatch seams even after the pure command-builder logic moved out.
  Evidence: the fs-cage tests patch `cookimport.llm.codex_exec_runner.Path.home`, `_resolve_recipeimport_codex_home`, and `_build_taskfile_worker_fs_cage_command`, so the new `codex_exec_command_builder.py` owner works behind thin root wrappers rather than replacing the runner surface outright.

- Observation: the line-role compatibility cleanup was broader than `runtime.py` and `runtime_recovery.py`; the earlier extracted planning/policy/validation owners were still in the transitional state.
  Evidence: `rg` still found `sys.modules["cookimport.parsing.canonical_line_roles"]` plus `globals().update(...)` in `planning.py`, `policy.py`, and `validation.py` until this slice replaced them with explicit named imports.

- Observation: the line-role runtime still had an obvious taskfile-owner seam after the compatibility cleanup.
  Evidence: task-file construction, task-file output expansion, final-message partial-progress detection, and incomplete-ledger surfacing all lived in one top-of-file block, already had focused tests, and moved cleanly into `runtime_taskfile.py` while the root kept the re-export surface.

- Observation: the repo-wide architecture guard that failed after the analytics refactor was unrelated to this work.
  Evidence: `tests/architecture/test_ai_readiness_boundaries.py::test_second_wave_owner_roots_stay_small_and_explicit` still fails because `cookimport/config/run_settings.py` is already 1372 lines, which exceeds that test's pre-existing 1225-line threshold.

## Decision Log

- Decision: use one consolidated roadmap rather than one ExecPlan per file.
  Rationale: these files are coupled by subsystem. Separate plans would duplicate context and hide cross-file ordering constraints, especially for analytics and the LLM runtime surface.
  Date/Author: 2026-04-01 / Codex

- Decision: treat embedded dashboard JavaScript files differently from oversized Python logic files.
  Rationale: for `script_filters.py` and `script_tables.py`, the right fix is to move the string assets into owned `.js` files or generated asset files, not to invent more Python wrapper layers.
  Date/Author: 2026-04-01 / Codex

- Decision: preserve composition roots for the direct-exec, line-role, knowledge, recipe-stage, and prediction-run flows.
  Rationale: those areas need one obvious top-level entrypoint. The problem is that the roots currently also own parsing, validation, prompt building, workspace plumbing, reporting, and retry logic that can be extracted behind them.
  Date/Author: 2026-04-01 / Codex

- Decision: make analytics decomposition start with shared read-only helper extraction before touching dashboard or compare/control behavior.
  Rationale: the safest win is to remove duplicated manifest/token/runtime enrichment code from `dashboard_collect.py` and `perf_report.py`. That reduces size and future drift without changing any user-facing analytics surface.
  Date/Author: 2026-04-01 / Codex

- Decision: do not chase a strict universal line-count cap during this work.
  Rationale: some coordinators should remain moderately large. The real target is one-file-one-story. As a practical guideline, ordinary owner modules should usually end below about 1,500 lines, and designated coordinators should usually end below about 2,000 lines unless a documented exception remains.
  Date/Author: 2026-04-01 / Codex

- Decision: implement in four waves ordered by risk and coupling: dashboard assets, analytics/helpers, Label Studio and bench surfaces, then LLM runtime coordinators.
  Rationale: this order produces earlier size wins with lower regression risk and defers the deepest coordinator surgery until the smaller seams and test coverage are already in place.
  Date/Author: 2026-04-01 / Codex

- Decision: preserve `script_filters.py` and `script_tables.py` as import-stable thin wrappers instead of deleting those Python modules outright.
  Rationale: current tests and renderer assembly already point at those module names. Keeping them tiny preserves the import surface while moving the real JS source into checked-in asset files.
  Date/Author: 2026-04-01 / Codex

- Decision: extract only the shared analytics benchmark-manifest runtime/token helper layer in the first analytics slice.
  Rationale: this removes real duplication from both `dashboard_collect.py` and `perf_report.py` without yet disturbing compare/control semantics or wider dashboard behavior.
  Date/Author: 2026-04-01 / Codex

- Decision: keep this roadmap marked in-progress rather than rewriting it as a completed retrospective.
  Rationale: Milestone 1 is complete and Milestone 2 is only partially complete, but the bench, Label Studio, and deep LLM decomposition waves are still real planned work. The finished document should therefore be a current execution roadmap, not a false "done" record.
  Date/Author: 2026-04-02 / Codex

- Decision: keep `compare_control_engine.py` as the public facade and split compare/control by responsibility rather than by call site.
  Rationale: CLI code, tests, and bench helpers already import the engine module directly. A facade keeps those imports stable while the real owners become legible: constants/errors, field normalization/catalog, filters, and statistics/insights.
  Date/Author: 2026-04-02 / Codex

- Decision: keep `recipe_stage_shared.py` as a shrinking runtime coordinator while moving extracted owners under `cookimport/llm/recipe_stage/`.
  Rationale: recipe runtime still needs one obvious coordination seam, but task-file schema/descriptor helpers and prompt/jsonl/input/path writers are independent responsibilities with clear destination modules under the recipe-stage owner package.
  Date/Author: 2026-04-02 / Codex

- Decision: move only the direct-exec contract dataclasses/protocols out of `codex_exec_runner.py` before touching the subprocess and telemetry stacks.
  Rationale: the transport root still needs to re-export those names for tests and downstream stages, but the contract types themselves do not need the process implementation and can move safely ahead of higher-blast-radius runtime surgery.
  Date/Author: 2026-04-02 / Codex

- Decision: split `knowledge_stage/recovery.py` by responsibility rather than by retry subtype.
  Rationale: task-status tracking, stale follow-up cleanup, and stage-status writing are deterministic bookkeeping responsibilities that do not need the watchdog/repair decision logic, so they form a clean stage-local owner seam in `recovery_status.py`.
  Date/Author: 2026-04-02 / Codex

- Decision: keep this roadmap and the newer finish plan together rather than deleting one.
  Rationale: this file is the broad, cross-subsystem decomposition roadmap and historical record; the newer file is a narrower implementation contract for the remaining cleanup slice. Keeping both avoids losing context while still giving contributors a focused next-work plan.
  Date/Author: 2026-04-04 / Codex

## Outcomes & Retrospective

Current outcome: the repo now has a concrete, partially executed roadmap instead of an ad hoc “split giant files someday” intention. Milestone 1 is landed, Milestone 2 is complete, and Milestone 4 is underway: compare/control field normalization, filter logic, and statistics/insights live in explicit owner modules, prompt tooling now uses explicit facade splits, recipe-stage task-file/schema plus worker-I/O helpers now live under `cookimport/llm/recipe_stage/`, the knowledge structured-session contract and recovery bookkeeping each now have their own owner modules, the direct-exec transport now keeps its shared watchdog/live-snapshot contract types in a dedicated file, and bench scheduler/runtime plus source-planning logic and deterministic reuse/cache helpers now have their own owners under `cookimport/cli_support/`.

Latest outcome: the transitional compatibility layer is no longer present in the current extracted owner modules for bench helpers, the direct-exec workspace owner, or the line-role runtime/recovery split. Those files now reveal their true dependencies explicitly and keep patchability behind named hook lookups instead of hidden module snapshot copies.

Latest bench-side outcome: the external-AI wrapper now also keeps high-level upload-bundle parsing, final-size trim policy, group-packet assembly, and knowledge-summary/locator shaping in `high_level_artifacts.py` alongside the earlier owner splits. `scripts/benchmark_cutdown_for_external_ai.py` has dropped further to `11045` lines.

Latest decomp4 outcome: the remaining coordinator-root follow-through also landed. `bench_all_method_runtime.py` and `bench_all_method_interactive.py` now own the last large all-method coordinator bands, `runtime_workers.py` owns the remaining line-role worker/structured/direct-worker orchestration band, and `stage_reports.py`, `runtime_inventory.py`, plus `regression_sampling.py` own the next dominant external-AI upload-bundle families. The corresponding roots dropped again to `bench_all_method.py=473`, `runtime.py=1375`, and `benchmark_cutdown_for_external_ai.py=8543`.

Remaining gap: this roadmap no longer has an active decomposition closure gap. Any later follow-up should be treated as a new bounded plan rather than as unfinished work from this roadmap.
Current size markers after the latest wave: `prompt_artifacts.py` is now `702` lines, `prompt_budget.py` is `131`, `prelabel.py` is `427`, `cli_commands/labelstudio.py` is `3559`, `recipe_stage_shared.py` is `1647`, `knowledge_stage/workspace_run.py` is `1918`, `knowledge_stage/recovery.py` is `2092`, `codex_exec_runner.py` is `2068`, `runtime.py` is `1375`, `bench_all_method.py` is `473`, and `benchmark_cutdown_for_external_ai.py` is `8543`.

Expected final outcome: the largest files become either thin facades, explicit composition roots, or asset wrappers; subsystem docs point at the new ownership seams; and no targeted file remains giant solely because unrelated helpers kept accreting in place.

## Context and Orientation

The relevant large-file set for this plan is:

1. `cookimport/cli_support/bench_all_method.py`
2. `cookimport/parsing/canonical_line_roles/runtime.py`
3. `cookimport/llm/codex_exec_runner.py`
4. `cookimport/llm/recipe_stage_shared.py`
5. `cookimport/cli_commands/labelstudio.py`
6. `cookimport/analytics/dashboard_renderers/script_filters.py`
7. `cookimport/llm/prompt_artifacts.py`
8. `cookimport/analytics/dashboard_renderers/script_tables.py`
9. `scripts/benchmark_cutdown_for_external_ai.py`

While researching this plan, several adjacent large files also surfaced as follow-on candidates because they are likely to move in the same refactor waves:

- `cookimport/analytics/compare_control_engine.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/perf_report.py`
- `cookimport/labelstudio/prelabel.py`
- `cookimport/labelstudio/ingest_flows/prediction_run.py`
- `cookimport/llm/prompt_budget.py`
- `cookimport/llm/knowledge_stage/recovery.py`
- `cookimport/llm/knowledge_stage/workspace_run.py`
- `cookimport/parsing/canonical_line_roles/policy.py`
- `cookimport/cli_support/bench_single_book.py`

The architectural constraints that matter while decomposing are simple.

First, deterministic code remains the authority boundary. These splits must not invent new fuzzy semantics or move semantic authority out of the existing runtime owners.

Second, stage, Label Studio, benchmark, analytics, and prompt tooling already reuse common artifacts. Splits should move helper ownership without creating duplicate artifact readers or subtly different fallback logic.

Third, this repo already prefers explicit owner packages such as `cookimport/cli_commands/`, `cookimport/cli_support/`, `cookimport/analytics/dashboard_renderers/`, `cookimport/labelstudio/ingest_flows/`, `cookimport/llm/knowledge_stage/`, and `cookimport/parsing/canonical_line_roles/`. New modules should follow those ownership boundaries instead of creating generic “utils” files.

## Decomposition Decisions By File

### 1. `cookimport/cli_support/bench_all_method.py`

This file should be decomposed now. It currently mixes target discovery, variant construction, scheduling/cost estimation, progress rendering, QualitySuite bridge artifact writing, CodexFarm confirmation logic, evaluation telemetry summarization, and reporting helpers.

The end state should keep `bench_all_method.py` as a composition root and move the real owners into sibling modules under `cookimport/cli_support/`:

- `bench_all_method_targets.py` for gold/source resolution and target objects.
- `bench_all_method_variants.py` for variant matrix building and variant naming.
- `bench_all_method_scheduler.py` for source estimates, job plans, and worker-slot planning.
- `bench_all_method_qualitysuite.py` for bridge bundle writing and compare-control prefix logic.
- `bench_all_method_reporting.py` for dashboard row shaping, metric summarization, and markdown/report helpers.

Do not leave these as private imports from the legacy `cookimport.cli_support.bench` runtime blob forever. As part of this work, replace `globals().update(...)` dependencies with explicit imports where practical so ownership becomes legible.

### 2. `cookimport/parsing/canonical_line_roles/runtime.py`

This file should be decomposed, but it should remain the line-role runtime composition root. It currently owns too many independent responsibilities: same-session state inspection, catastrophic retry decisions, task-file building, output expansion, watchdog logic, taskfile assignment runtime, structured-resume assignment runtime, progress notification, preflight rejection, command classification, and validation/telemetry aggregation.

The end state should keep `runtime.py` as the entrypoint that wires the phase together, while moving stable logic into sibling owner files in `cookimport/parsing/canonical_line_roles/`:

- `runtime_recovery.py` for same-session completion inspection, fresh-session retry, fresh-worker replacement, and final-message recovery.
- `runtime_taskfile.py` for task-file payload building and taskfile worker assignment flow.
- `runtime_structured.py` for structured packet/resume assignment flow.
- `runtime_progress.py` for progress heartbeat, interval policy, and user-facing status aggregation.
- `runtime_preflight.py` for preflight checks, rejected-run construction, and watchdog callback builders.
- `runtime_commands.py` for command-classification and command-policy helpers.

`runtime.py` should still expose the public entrypoints `label_atomic_lines(...)` and `label_atomic_lines_with_baseline(...)`.

### 3. `cookimport/llm/codex_exec_runner.py`

This file should be decomposed, but it should remain the direct-exec transport composition root. It currently mixes public types, workspace preparation, prompt/path rewriting, helper-shim installation, filesystem-cage construction, subprocess streaming, event parsing, telemetry summarization, token-usage status, and final-message assessment.

The safe split is:

- `codex_exec_types.py` for the dataclasses and protocols that do not need the subprocess implementation.
- `codex_exec_workspace.py` for workspace creation, manifest writing, prompt/path rewriting, and workspace sync.
- `codex_exec_taskfile_env.py` for helper-import and single-file shim setup.
- `codex_exec_fs_cage.py` for Linux namespace and preserved-toolchain logic.
- `codex_exec_subprocess.py` for process spawning, stream reading, termination, and live snapshots.
- `codex_exec_telemetry.py` for event parsing, recent-command assessment, token-usage summarization, and message extraction.

`codex_exec_runner.py` should continue to own `SubprocessCodexExecRunner`, `FakeCodexExecRunner`, and the public transport entrypoints, but should delegate almost everything except orchestration.

### 4. `cookimport/llm/recipe_stage_shared.py`

This file should be decomposed now. The architecture docs already say the repo moved recipe-stage ownership into `cookimport/llm/recipe_stage/` and left a large private implementation behind this file. That means this file is explicitly known debt, not accidental bloat.

The desired split is:

- `recipe_stage/task_file_contract.py` for task-file payload shape, helper command descriptors, and compact answer schema.
- `recipe_stage/planning.py` for worker-count resolution, shard-count resolution, and shard-plan creation.
- `recipe_stage/prompt_inputs.py` for candidate hints, boundary context rows, and correction input building.
- `recipe_stage/validation.py` for compact-output validation, response evaluation, and preflight rejection.
- `recipe_stage/live_status.py` for live-status loading, writing, and supervision field aggregation.
- `recipe_stage/worker_io.py` for prompt serialization, JSONL writing, worker input writing, and local path helpers.
- `recipe_stage/promotion.py` for result-row construction and authority-eligibility classification.

The thin retained surface should be the recipe-stage runtime seam that coordinates those helpers. Do not create a second giant “shared2” file.

### 5. `cookimport/cli_commands/labelstudio.py`

This file should be decomposed modestly, not exploded. It is a command registration module, so some size is expected. The current file is too large because the registration function also owns interruption recovery, output pruning, benchmark selective-retry summaries, and a large number of option-normalization imports.

The safe split is:

- keep `cli_commands/labelstudio.py` as the Typer registration/composition root;
- move benchmark interruption and resume-finalization helpers into `cookimport/cli_support/labelstudio_benchmark_recovery.py`;
- move benchmark output pruning and artifact-retention policy into `cookimport/cli_support/labelstudio_benchmark_artifacts.py`;
- if the option-normalization imports are still overwhelming after that, introduce a small `cookimport/cli_support/labelstudio_option_adapters.py` file that groups the benchmark-specific normalization and default-resolution helpers.

The command callbacks should still live in the command module unless a callback becomes independently reusable.

### 6. `cookimport/analytics/dashboard_renderers/script_filters.py`

This file should be decomposed, but not into more Python. It is effectively a bundled frontend asset. The correct destination is a real JavaScript source file under the dashboard renderer ownership area.

The target shape is:

- `cookimport/analytics/dashboard_renderers/assets/script_filters.js` as the owned JS source.
- a tiny Python loader module, or a shared asset-loader helper, that reads the JS text when rendering the dashboard.

If the dashboard build prefers checked-in Python constants for packaging reasons, then the fallback is to generate the Python string from the `.js` source in one deterministic build step. The `.js` file should still be the source of truth.

### 7. `cookimport/llm/prompt_artifacts.py`

This file should be decomposed now. It currently mixes descriptor discovery, manifest and process-run loading, prompt attachment loading, activity-trace extraction, rendering of markdown samples, CSV row loading, runtime-context inference, and exported trace writing.

The target split is:

- `prompt_artifacts_discovery.py` for run/stage/call descriptor discovery.
- `prompt_artifacts_loader.py` for manifest, JSON/JSONL, CSV, message, and attachment loading.
- `prompt_artifacts_activity.py` for activity-trace extraction, event summarization, and exported trace payloads.
- `prompt_artifacts_render.py` for markdown sample rendering and summary output writing.

Keep `prompt_artifacts.py` as the public facade that exposes the stable top-level helpers used elsewhere in the repo.

### 8. `cookimport/analytics/dashboard_renderers/script_tables.py`

This has the same classification as `script_filters.py`. It is an embedded frontend asset, not a Python logic file that needs more helper extraction.

Move the owned JavaScript into:

- `cookimport/analytics/dashboard_renderers/assets/script_tables.js`

and keep only the minimal Python loading/render seam. If the asset loader already exists after `script_filters.py` is handled, reuse it rather than creating a second path.

### 9. `scripts/benchmark_cutdown_for_external_ai.py`

This file should be decomposed now, and the long-term owner should be a proper bench package, not a permanently giant script. It currently mixes CLI argument parsing, run discovery, JSON/JSONL I/O, prompt-log sampling, canonical-line building, wrong-label view construction, recipe-stage output parsing, warning aggregation, upload-bundle adaptation, group-packet budgeting, and final package writing.

The target shape is:

- `scripts/benchmark_cutdown_for_external_ai.py` becomes a thin CLI wrapper.
- `cookimport/bench/external_ai_cutdown/discovery.py` owns run discovery and output-root selection.
- `cookimport/bench/external_ai_cutdown/artifact_paths.py` owns prompt/prediction/processed-output artifact-path resolution.
- `cookimport/bench/external_ai_cutdown/io.py` owns deterministic JSON/JSONL/GZip helpers and clipping helpers.
- `cookimport/bench/external_ai_cutdown/prompt_log_reconstruction.py` owns deterministic `full_prompt_log.jsonl` reconstruction from staged `raw/llm` artifacts.
- `cookimport/bench/external_ai_cutdown/line_projection.py` owns recipe-span projection and line-prediction views.
- `cookimport/bench/external_ai_cutdown/prompt_diagnostics.py` owns prompt-response warning/correction interpretation.
- `cookimport/bench/external_ai_cutdown/diagnostic_packets.py` owns wrong-label/preprocess compressed packet generation.
- `cookimport/bench/external_ai_cutdown/projection_trace.py` owns alignment-health checks, projection-trace summaries, and shared prompt-row helper views.
- `cookimport/bench/external_ai_cutdown/project_context.py` owns project-context metadata extraction and digest rendering.
- `cookimport/bench/external_ai_cutdown/prompt_logs.py` owns prompt-log parsing and sampling.
- `cookimport/bench/external_ai_cutdown/canonical_lines.py` owns canonical-line and gold-span views.
- `cookimport/bench/external_ai_cutdown/recipe_stage.py` owns recipe-stage output parsing and recipe-span normalization.
- `cookimport/bench/external_ai_cutdown/upload_bundle.py` owns upload-bundle adaptation, group-packet budgeting, and final package writing.

This keeps bench tooling aligned with the rest of the bench package instead of leaving a giant script as the main owner forever.

## Follow-On Candidates That Should Move In The Same Waves

These files were not the original ask, but they should be considered part of the same decomposition campaign because they are adjacent owners or duplicate logic.

`cookimport/analytics/dashboard_collect.py`, `cookimport/analytics/perf_report.py`, and `cookimport/analytics/compare_control_engine.py` should move together in the analytics wave. The right first step is a shared analytics helper layer for token/runtime extraction and manifest enrichment, then a split of compare/control into field catalog, normalization, and statistical analysis helpers.

`cookimport/labelstudio/ingest_flows/prediction_run.py` should move in the Label Studio wave. Keep `generate_pred_run_artifacts(...)` as the public prediction-run entrypoint, but move its internal phases into owner modules such as `prediction_run_convert.py`, `prediction_run_processed_outputs.py`, `prediction_run_tasks.py`, and `prediction_run_progress.py`.

`cookimport/labelstudio/prelabel.py` should move in the same wave. Split it into Codex config/account discovery, provider execution, output parsing, and task-span/block mapping. The likely owners are `prelabel_codex.py`, `prelabel_provider.py`, `prelabel_parse.py`, and `prelabel_mapping.py`, with `prelabel.py` remaining the facade/orchestrator.

`cookimport/llm/prompt_budget.py`, `cookimport/llm/knowledge_stage/recovery.py`, and `cookimport/llm/knowledge_stage/workspace_run.py` should move in the deep LLM wave. `prompt_budget.py` should separate preview token estimation from runtime summary aggregation. The knowledge-stage files should keep one workspace-run composition root and one recovery/status owner file, but move task-file validation, structured-session packet transforms, and follow-up finalization into smaller sibling modules.

## Milestones

### Milestone 1: Move embedded dashboard JavaScript out of Python

At the end of this milestone, `script_filters.py` and `script_tables.py` are no longer giant triple-quoted assets. The dashboard still renders the same behavior, but the JS lives in owned `.js` files, and the Python renderer only loads or emits those assets.

This is the safest first milestone because it changes ownership shape without changing Python behavior. The proof is dashboard tests passing and a simple grep showing that the giant `_JS_*` strings are gone or tiny.

Status: completed on 2026-04-01. The checked-in source of truth now lives in `cookimport/analytics/dashboard_renderers/assets/script_filters.js` and `cookimport/analytics/dashboard_renderers/assets/script_tables.js`, loaded through `script_file_assets.py`.

### Milestone 2: Extract shared analytics readers and split compare/control

At the end of this milestone, `dashboard_collect.py` and `perf_report.py` no longer each carry their own large manifest/token/runtime enrichment stacks, and `compare_control_engine.py` no longer has to own field normalization, field-catalog building, and statistics in one file.

Do this before the bench and Label Studio waves so later readers can reuse one stable analytics helper layer.

Status: completed on 2026-04-02. The shared benchmark-manifest runtime/token layer lives in `cookimport/analytics/benchmark_manifest_runtime.py`, and compare/control is now split across `compare_control_fields.py`, `compare_control_filters.py`, and `compare_control_analysis.py`, with `compare_control_engine.py` retained as the import-stable public facade.

### Milestone 3: Shrink bench and Label Studio orchestration files

At the end of this milestone, `bench_all_method.py`, `labelstudio.py`, `prediction_run.py`, `prelabel.py`, and the external-AI cutdown script have explicit owner modules for discovery, artifact writing, scheduling, and package generation. Their retained root files should read like orchestrators rather than junk drawers.

This milestone should also remove or reduce the current hidden dependence on `cookimport.cli_support.bench` runtime-global re-exporting where possible.

### Milestone 4: Split prompt tooling and deep LLM runtime coordinators

At the end of this milestone, `prompt_artifacts.py`, `prompt_budget.py`, `recipe_stage_shared.py`, `codex_exec_runner.py`, `canonical_line_roles/runtime.py`, and the knowledge-stage runtime files are all split into composition roots plus explicit helper owners. The public runtime entrypoints stay stable, but the files become navigable.

This is the highest-risk milestone and should be done last, with focused tests after each extraction rather than one huge rewrite.

## Plan of Work

Start with the asset-like files because they are easiest to de-risk. Add a dashboard asset-loader helper under `cookimport/analytics/dashboard_renderers/` if one does not already exist. Move `script_filters.py` and `script_tables.py` JS content into real `.js` files and keep the Python side as tiny loaders or emitters. Run the analytics dashboard tests immediately after that move.

Next, create an analytics shared helper module that owns read-only manifest enrichment and token/runtime extraction. Move duplicate helper logic out of `dashboard_collect.py` and `perf_report.py` into that shared layer first. Only after the shared helpers exist should `compare_control_engine.py` be split into field-catalog, normalization, and stats helpers. This order reduces duplicate code before renaming or moving compare/control pieces.

Then tackle the bench and Label Studio wave. For `bench_all_method.py`, extract targets, variants, scheduler, bridge bundle writing, and reporting in that order. For `labelstudio/ingest_flows/prediction_run.py`, identify each internal phase of `generate_pred_run_artifacts(...)` and give it a small owner module. For `labelstudio/prelabel.py`, split the stable low-level helpers first: account/model discovery, command shaping, provider execution, and output parsing. Keep the top-level user-facing entrypoints stable until the leaf helpers are in place. Convert the external-AI cutdown script last within this wave, because once the bench helper modules exist the script can reuse those stable readers rather than continuing to carry custom copies.

Finish with the deep LLM wave. Start with `prompt_artifacts.py` and `prompt_budget.py`, because they are read-side tooling and easier to verify. Then continue the already-intended recipe-stage split by moving code out of `recipe_stage_shared.py` into `cookimport/llm/recipe_stage/`. After that, extract the direct-exec workspace, FS-cage, subprocess, and telemetry layers out of `codex_exec_runner.py`. Once the shared transport helpers exist, split `canonical_line_roles/runtime.py` and the knowledge-stage runtime files along taskfile/structured/recovery/progress seams. Keep one composition root per stage and do not create ambiguous “misc” helper modules.

For every wave, keep imports explicit. Avoid repeating the current pattern where a root runtime module bulk-injects names through `globals().update(...)` and makes the true owner impossible to locate. If compatibility needs a transitional re-export, make it temporary and documented inside the new owner module.

## Concrete Steps

All commands below are run from `/home/mcnal/projects/recipeimport`.

Prepare the local environment first:

    test -x .venv/bin/python || python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .[dev]

Before each milestone, measure the target files again so the shrink is visible:

    rg --files cookimport scripts | \
      rg '(\.py|\.js)$' | \
      xargs -r wc -l | \
      sort -nr | head -n 40

After Milestone 1, run the analytics-focused tests:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain analytics
    .venv/bin/pytest tests/analytics/test_stats_dashboard.py -q

After Milestone 2, run the analytics and compare/control tests:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain analytics
    .venv/bin/pytest tests/analytics/test_compare_control_engine.py -q
    .venv/bin/pytest tests/analytics/test_compare_control_cli.py -q

After Milestone 3, run the bench and Label Studio tests:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain bench
    ./scripts/test-suite.sh domain labelstudio
    .venv/bin/pytest tests/labelstudio/test_labelstudio_ingest_parallel_prediction_run.py -q

After Milestone 4, run the LLM, parsing, and staging tests:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain llm
    ./scripts/test-suite.sh domain parsing
    ./scripts/test-suite.sh domain staging

At the end, re-measure the largest files and spot-check that the targeted roots are now composition roots rather than giant helper bins:

    rg --files cookimport scripts | \
      rg '(\.py|\.js)$' | \
      xargs -r wc -l | \
      sort -nr | head -n 40

    rg -n "globals\\(\\)\\.update|sys\\.modules\\[\"cookimport\\.cli_support\\.bench\"\\]" \
      cookimport/cli_support

Do not run Codex-backed book processing, CodexFarm-enabled benchmarks, or any heavyweight benchmark publication flow while executing this plan unless the user explicitly approves that run. The decomposition is fully verifiable through deterministic tests and static artifact checks.

## Validation and Acceptance

The plan is complete when all of the following are true.

The targeted large files either became thinner composition roots or were replaced by real owner assets. The repo still passes the relevant domain suites. The public command and artifact contracts stay the same. The subsystem docs no longer point new contributors at files that stopped being the real owner.

More specifically:

- `bench_all_method.py`, `recipe_stage_shared.py`, `prompt_artifacts.py`, and the external-AI cutdown script should each lose at least one major responsibility cluster to named owner modules.
- `codex_exec_runner.py`, `canonical_line_roles/runtime.py`, and the knowledge-stage runtime should each retain one obvious orchestration role while shedding workspace, recovery, prompt-building, or telemetry helper clusters into sibling owners.
- `script_filters.py` and `script_tables.py` should no longer be giant embedded JS blobs in Python.
- analytics token/runtime enrichment logic should have one shared owner rather than parallel copies in multiple large modules.
- no new “misc”, “helpers”, or “utils” dumping-ground module should become the next giant file.

## Idempotence and Recovery

This work is safe to do incrementally. Each extraction should be an atomic move plus import rewiring plus tests. If a split goes sideways, revert only that small extraction commit and keep the rest of the roadmap intact.

When moving code out of a giant file, prefer this sequence:

1. copy the helper into the new owner module without changing behavior;
2. switch the old file to import and call the new owner;
3. run focused tests;
4. delete the old duplicate implementation only after the import path is stable.

If a milestone reveals a missing test seam, add the narrowest regression test before continuing the decomposition. Do not batch multiple risky extractions before proving the first one.

## Artifacts and Notes

Initial rough size markers that motivated this plan:

    9421  cookimport/cli_support/bench_all_method.py
    5639  cookimport/parsing/canonical_line_roles/runtime.py
    5363  cookimport/llm/codex_exec_runner.py
    5079  cookimport/llm/recipe_stage_shared.py
    3814  cookimport/cli_commands/labelstudio.py
    3365  cookimport/llm/prompt_artifacts.py
    16488 scripts/benchmark_cutdown_for_external_ai.py

Embedded asset note:

    cookimport/analytics/dashboard_renderers/script_filters.py
    cookimport/analytics/dashboard_renderers/script_tables.py

These are primarily JavaScript payloads, so the right shrink is “move to real JS assets,” not “split into more Python wrappers.”

Current post-Milestone-1 and Milestone-2-slice markers:

    5     cookimport/analytics/dashboard_renderers/script_filters.py
    5     cookimport/analytics/dashboard_renderers/script_tables.py
    641   cookimport/analytics/benchmark_manifest_runtime.py
    1836  cookimport/analytics/dashboard_collect.py
    1606  cookimport/analytics/perf_report.py
    69    cookimport/analytics/compare_control_engine.py
    664   cookimport/analytics/compare_control_fields.py
    305   cookimport/analytics/compare_control_filters.py
    1702  cookimport/analytics/compare_control_analysis.py

Current post-Milestone-4-slice markers:

    3559  cookimport/cli_commands/labelstudio.py
    5089  cookimport/llm/codex_exec_runner.py
    128   cookimport/llm/codex_exec_types.py
    702   cookimport/llm/prompt_artifacts.py
    375   cookimport/llm/prompt_artifacts_loader.py
    2092  cookimport/llm/knowledge_stage/recovery.py
    736   cookimport/llm/knowledge_stage/recovery_status.py
    1918  cookimport/llm/knowledge_stage/workspace_run.py
    434   cookimport/llm/knowledge_stage/structured_session_contract.py
    1647  cookimport/llm/recipe_stage_shared.py
    110   cookimport/llm/recipe_stage/task_file_contract.py
    270   cookimport/llm/recipe_stage/worker_io.py

These current counts show the analytics wave worked as intended: the asset move stayed tiny, the shared manifest helper stayed shared, and compare/control became a thin facade plus named owner modules instead of one 2805-line analytics blob.

## Interfaces and Dependencies

Use existing subsystem owner directories as the destination for new code. The decomposition should stay within these homes:

- CLI support owners under `cookimport/cli_support/`
- line-role owners under `cookimport/parsing/canonical_line_roles/`
- recipe-stage owners under `cookimport/llm/recipe_stage/`
- knowledge-stage owners under `cookimport/llm/knowledge_stage/`
- analytics owners under `cookimport/analytics/` and `cookimport/analytics/dashboard_renderers/`
- Label Studio flow owners under `cookimport/labelstudio/` and `cookimport/labelstudio/ingest_flows/`
- bench tooling owners under `cookimport/bench/`

Do not introduce generic cross-domain dumping grounds. When a helper is specific to one stage or one product surface, keep it under that stage or surface.

Change note: 2026-04-01 23:18 America/Toronto. Created the initial large-file decomposition roadmap after reading the current architecture and subsystem docs plus skimming the oversized file set. The reason for this revision was the user’s request for an ExecPlan covering the known massive files and deciding where decomposition actually makes sense.

Change note: 2026-04-01 23:53 America/Toronto. Updated the plan after implementing Milestone 1 and the first analytics helper extraction slice. The reason for this revision was to keep the living document accurate about what actually landed, what tests passed, and what remains for later waves.

Change note: 2026-04-02 00:15 America/Toronto. Finished the documentation pass for this ExecPlan by adding required front matter, recording the analytics doc updates, and refreshing the current-state size notes. The reason for this revision was to make the roadmap compliant with the docs index and accurate about the present implementation state without pretending the later roadmap waves are already done.

Change note: 2026-04-02 00:34 America/Toronto. Updated the roadmap after completing the pending Milestone 2 compare/control split, recording the new owner modules, proof commands, and current size markers. The reason for this revision was to keep the living document accurate now that the analytics wave is no longer waiting on `compare_control_engine.py`.

Change note: 2026-04-02 11:14 America/Toronto. Updated the roadmap after the first deep recipe-stage owner cut, documenting the new `task_file_contract.py` and `worker_io.py` modules, the lazy package-bootstrap adjustment, the focused proof runs, and the new `recipe_stage_shared.py` size marker. The reason for this revision was to keep the living document accurate now that Milestone 4 is active instead of purely planned.

Change note: 2026-04-02 11:14 America/Toronto. Updated the roadmap after the next Milestone-4 runtime slices, documenting `knowledge_stage/structured_session_contract.py`, `codex_exec_types.py`, the focused venv proof run, and the new `workspace_run.py` / `codex_exec_runner.py` size markers. The reason for this revision was to keep the living document accurate as the deep-runtime wave progressed beyond the first recipe-stage cut.

Change note: 2026-04-02 11:14 America/Toronto. Updated the roadmap after extracting `knowledge_stage/recovery_status.py`, recording the focused knowledge proof run, the survivability monkeypatch fix in `runtime.py`, and the new `recovery.py` size marker. The reason for this revision was to keep the living document accurate as the knowledge-runtime ownership split continued.

Change note: 2026-04-04 12:19 America/Toronto. Updated the roadmap after the focused finish-plan compatibility cleanup landed for the current extracted bench, direct-exec, and line-role owner modules. The reason for this revision was to keep the broad roadmap accurate now that the hidden namespace-copy pattern is gone from those owner modules and the remaining work is root shrink plus the external-AI wrapper split.
