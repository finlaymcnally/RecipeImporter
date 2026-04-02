---
summary: "Current test-suite structure and low-noise pytest behavior reference."
read_when:
  - When changing tests folder layout, marker groups, or pytest output defaults
  - When test output noise increases or compact output behavior regresses
---

# Testing README

This file is the source of truth for the current test-suite structure and pytest behavior.

Use `docs/12-testing/12-testing_log.md` for durable history and verification notes.

## Scope

This section covers:

- test folder/domain organization,
- active split-file exceptions under `tests/`,
- marker-based runs and wrapper usage,
- compact pytest output defaults,
- the current deep-debug escape hatch.

## Current Layout and Entry Points

Primary test folders:

- `tests/architecture`
- `tests/analytics`
- `tests/bench`
- `tests/cli`
- `tests/core`
- `tests/ingestion`
- `tests/labelstudio`
- `tests/llm`
- `tests/parsing`
- `tests/staging`

Layout and routing notes:

- `tests/test_eval_freeform_practical_metrics.py` intentionally stays at `tests/` root and is marked as both `labelstudio` and `bench`.
- `tests/architecture/` exists as a real folder, but there is no dedicated `architecture` pytest marker yet; those tests currently fall back to marker `core` unless they are run by explicit path.
- Do not assume folder name and `-m <domain>` coverage are identical. `tests/conftest.py` is the marker authority, and some newer focused files still use the fallback-to-`core` path.
- When a split area starts regrowing into one long mixed-concern test, split by seam before adding more assertions.

Active intentional split seams:

- CLI output-structure coverage is split into:
  - `tests/cli/test_cli_output_structure_fast.py`
  - `tests/cli/test_cli_output_structure_epub_fast.py`
  - `tests/cli/test_cli_output_structure_text_fast.py`
  - `tests/cli/test_cli_output_structure_slow.py`
- PDF importer coverage is split into:
  - `tests/ingestion/test_pdf_importer.py`
  - `tests/ingestion/test_pdf_importer_ocr_slow.py`
- Stats dashboard coverage is split into:
  - `tests/analytics/test_stats_dashboard_schema.py`
  - `tests/analytics/test_stats_dashboard_collectors.py`
  - `tests/analytics/test_stats_dashboard.py` for renderer/browser-harness coverage
  - `tests/analytics/test_stats_dashboard_benchmark_semantics.py`
  - `tests/analytics/test_stats_dashboard_csv.py`
  - `tests/analytics/test_stats_dashboard_slow.py`
- Label Studio benchmark coverage is intentionally spread across focused files instead of one helper mega-file:
  - smoke path: `tests/labelstudio/test_labelstudio_benchmark_smoke.py`
  - interactive/import/export/artifact flows: `..._interactive.py`, `..._import_eval.py`, `..._export_selection.py`, `..._artifacts.py`, `..._progress.py`, `..._progress_dashboard.py`
  - eval payload seams: `..._eval_payload_compare.py`, `..._eval_payload_execution.py`, `..._eval_payload_pipelined.py`, `..._eval_payload_artifacts.py`
  - scheduler seams: `..._scheduler_targets.py`, `..._scheduler_planning.py`, `..._scheduler_global_queue.py`, `..._scheduler_prediction_reuse.py`, `..._scheduler_run_reports.py`
  - single-book and single-profile seams: `..._single_book_run.py`, `..._single_book_artifacts.py`, `..._single_profile.py`
- Shared Label Studio benchmark helper support belongs in `tests/labelstudio/benchmark_helper_support.py`; do not rebuild a large support pseudo-test module.
- Large split suites should put reusable builders in local `*_support.py` modules (`tests/analytics/stats_dashboard_support.py`, `tests/bench/benchmark_cutdown_support.py`, `tests/labelstudio/labelstudio_ingest_parallel_support.py`, `tests/parsing/canonical_line_role_support.py`) instead of copying helpers across collected files.
- Label Studio prelabel coverage is split into:
  - `tests/labelstudio/test_labelstudio_prelabel.py`
  - `tests/labelstudio/test_labelstudio_prelabel_codex_cli.py`
- Codex orchestrator coverage is split into:
  - `tests/llm/test_codex_farm_orchestrator.py`
  - `tests/llm/test_codex_farm_orchestrator_repair.py`
  - `tests/llm/test_codex_farm_orchestrator_watchdog.py`
  - `tests/llm/test_codex_farm_orchestrator_runner_transport.py`
  - `tests/llm/test_codex_farm_orchestrator_stage_integration.py`
- Knowledge-stage coverage is intentionally split by seam:
  - `tests/llm/test_knowledge_orchestrator_contracts.py` for owner/facade and contract coverage
  - `tests/llm/test_knowledge_orchestrator_runtime_progress.py` and `tests/llm/test_knowledge_orchestrator_runtime_leasing.py` for focused runtime behavior
  - `tests/llm/test_knowledge_runtime_replay.py` for replay and saved-artifact coverage
  - `tests/llm/test_knowledge_stage_bindings.py` for fast binding/unresolved-name guards
- `tests/llm/test_llm_module_bindings.py` now provides one broad offline import/unresolved-global audit across `cookimport.llm.*`; keep it cheap and let focused files like `test_knowledge_stage_bindings.py` cover package-local failure modes in more detail.
- Direct Codex exec runner coverage is split into:
  - `tests/llm/test_codex_exec_runner.py` for helper/classification coverage
  - `tests/llm/test_codex_exec_runner_taskfile.py` for sterile workspace preparation and subprocess/taskfile runtime coverage
- workspace/direct-exec runtime tests must not inherit the host Codex profile; keep them on temp paths and only override the suite-level temp `CODEX_HOME` fixture when the test is asserting explicit home-resolution behavior
- Bench CLI coverage is split into:
  - `tests/bench/test_bench.py`
  - `tests/bench/test_bench_speed_cli.py`
  - `tests/bench/test_bench_quality_cli.py`
- Step ingredient linking coverage is split into:
  - `tests/parsing/test_step_ingredient_linking.py`
  - `tests/parsing/test_step_ingredient_linking_semantic.py`
- Canonical line-role coverage is split into:
  - `tests/parsing/test_canonical_line_role_env.py` for fast env/helper guardrails
  - `tests/parsing/test_canonical_line_roles_recipe_span.py` for short in-span rule regressions
  - `tests/parsing/test_canonical_line_roles.py` for non-Codex baseline labeling behavior and regression fixtures
  - `tests/parsing/test_canonical_line_roles_codex.py` for Codex override/acceptance regressions
  - `tests/parsing/test_canonical_line_roles_prompting.py` for prompt/cache/telemetry/progress seams
  - `tests/parsing/test_canonical_line_roles_taskfile.py` for workspace-watchdog and command-policy behavior
  - `tests/parsing/test_canonical_line_roles_runtime.py` for fail-closed/artifact/runtime contract behavior
  - `tests/parsing/test_canonical_line_roles_runtime_recovery.py` for retry/recovery behavior
- Benchmark cutdown coverage for the external-AI bundle tool is split into:
  - `tests/bench/test_benchmark_cutdown_for_external_ai.py` for the base smoke/main path
  - `tests/bench/test_benchmark_cutdown_for_external_ai_starter_pack.py` for starter-pack selection/output seams
  - `tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle.py` for upload-bundle synthesis/details
  - `tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle_runtime.py` for upload-bundle runtime telemetry and knowledge-layout seams
  - `tests/bench/test_benchmark_cutdown_for_external_ai_high_level.py` for high-level bundle aggregation limits
- QualitySuite runner coverage is split into:
  - `tests/bench/test_quality_suite_runner.py` for base runtime/result contracts
  - `tests/bench/test_quality_suite_runner_resume.py` for resume/reject-fast seams
  - `tests/bench/test_quality_suite_runner_parallelism.py` for worker, WSL, scheduler, and schema/runtime knob coverage
  - `tests/bench/test_quality_suite_runner_race.py` for race-prune and exhaustive-fallback behavior
- Label Studio ingest parallel coverage is split into:
  - `tests/labelstudio/test_labelstudio_ingest_parallel.py` for import planning/upload flow seams
  - `tests/labelstudio/test_labelstudio_ingest_parallel_prediction_run.py` for prediction-run/prelabel/line-role authority seams
- Label Studio benchmark artifact coverage is split into:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py` for prompt-log/artifact status seams
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_prompt_budget.py` for prompt-budget/runtime summary seams
- Label Studio benchmark progress coverage is split into:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py` for ETA/timeseries/basic progress helpers
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress_dashboard.py` for live dashboard and worker-rendering behavior
- tests that assert exact line-role shard ids, proposal filenames, or worker assignments must opt out of the default `line_role_prompt_target_count=5`; `codex_batch_size=1` alone no longer means one line per shard
- Small live Codex env/import helpers should keep one direct non-slow regression test even when broader slow integration coverage already exists.
- Split LLM stage packages should keep one direct unresolved-name/binding guard close to the package when the main smoke path would only hit the seam after a long offline run or a live Codex stage.
- CLI path-resolution tests should prefer synthesizing the minimal artifact contract they need under `tmp_path` instead of depending on repo-local sample benchmark roots.
- Bench Oracle / follow-up / `cf-debug` tests should prefer tiny synthetic `upload_bundle_v1` fixtures under `tmp_path`; copying large checked-in benchmark roots is reserved for an explicit slow realism slice only.
- Benchmark Oracle upload coverage is split into:
  - `tests/bench/test_benchmark_oracle_upload.py` for prompt/model/command/browser assembly seams
  - `tests/bench/test_benchmark_oracle_upload_background.py` for background upload/session/audit seams
- When one test starts mixing giant fixture setup, one command/helper invocation, and several unrelated output families, split it into file-local builders plus narrower tests before adding more assertions. Prefer domain-local support modules and helper functions over a new repo-wide fixture framework.

Support assets and test-runtime files:

- `tests/fixtures/*` holds fixture generators and binary fixture assets.
- `pytest.ini`, `tests/conftest.py`, `tests/paths.py`, `tests/README.md`, `tests/CONVENTIONS.md`, and `tests/AGENTS.md` are active test-runtime control surfaces.
- `tests/paths.py` is the shared root resolver for `REPO_ROOT`, `FIXTURES_DIR`, and `DOCS_EXAMPLES_DIR`.
- `tests/conftest.py` also forces a writable temp Codex home for pytest runs so routine tests do not write into the host machine's real profile.

## Marker and Run Contracts

Current contracts:

- Marker assignment is centralized in `tests/conftest.py`; do not spread domain markers across individual test files.
- `_FILE_MARKERS` maps test filenames to domain markers. Unknown `test_*.py` files fall back to marker `core`.
- Markers declared in `pytest.ini` are: `analytics`, `bench`, `cli`, `core`, `heavy_side_effects`, `ingestion`, `labelstudio`, `llm`, `parsing`, `staging`, `slow`, and `smoke`.
- `slow` and `smoke` routing is controlled centrally by `_SLOW_FILES` and `_SMOKE_FILES` in `tests/conftest.py`.
- If you add or rename a test file, update `_FILE_MARKERS` and then decide whether the file also belongs in `_SLOW_FILES` or `_SMOKE_FILES`.
- The marker map is not a perfect mirror of the folder tree right now. Check `tests/conftest.py` before assuming a new file participates in the domain slice you expect.
- The `slow` slice is intentionally narrow and currently covers only the explicitly high-cost files in `tests/conftest.py`; do not widen it without measuring runtime first.
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_run.py` is part of `slow`; routine `labelstudio` domain runs should not pay for full single-book comparison/bundle/dashboard helper coverage.
- Routing-only interactive benchmark tests should stub `_interactive_single_book_benchmark(...)` and assert the handoff arguments instead of re-exercising the helper internals from `test_labelstudio_benchmark_helpers_interactive.py`.
- Several historically named `..._fast.py` integration files are intentionally slow-marked because measured runtime is still too high for routine loops.
- Broad compact pytest runs are a poor hotspot profiler here; use one-file pytest invocations when measuring candidate slow files because the compact reporter suppresses most useful `--durations` detail in broad runs.
- Prefer moving proven heavy helper-internal suites into `_SLOW_FILES` before changing production code for test speed; production edits need a stronger reason than loop runtime alone.
- Bench-side Oracle upload tests that only care about command or metadata shape should clamp the background audit poll constants inside the test so they do not pay the default production wait window.
- The benchmark smoke slice includes the real interactive single-book benchmark path while stubbing `labelstudio_benchmark(...)` so smoke runs catch routing and artifact regressions without spending tokens.
- Benchmark smoke now has a second boundary: offline simulated whole-run single-book vanilla and codex-shaped flows should execute the real `labelstudio_benchmark(...)` runtime while stubbing only leaf prediction-generation/evaluation seams, so routine smoke runs catch benchmark-helper `NameError` regressions without spending live LLM tokens.
- `tests/core/test_benchmark_undefined_names.py` now has two benchmark guards: Ruff `F821` for the explicit benchmark command surface, and a bootstrapped `LOAD_GLOBAL` audit for split benchmark modules (`bench_artifacts`, `bench_all_method`, `bench_cache`, `bench_single_book`, `bench_single_profile`, `bench_oracle`, `bench_compare`) after `cli_support.bench` finishes wiring them together.
- That same file now also keeps a small interactive-CLI unresolved-global audit for the no-subcommand flow owners (`interactive_flow`, `settings_flow`, and `cli_commands.stage`) so direct command-module binding mistakes fail before manual CLI use.
- That file now also runs a broader auto-discovered audit across `cookimport.cli_support.*` and `cookimport.cli_commands.*`, so newly split CLI modules inherit the same unresolved-name guard without a second maintenance checklist.
- Label Studio benchmark-helper tests now have two safety layers:
  - low-level heavy helpers fail fast under pytest unless the test opts in with `@pytest.mark.heavy_side_effects` plus `allow_heavy_test_side_effects`
  - `tests/labelstudio/benchmark_helper_support.py` provides shared lightweight benchmark publishers for routine single-book, single-profile, and smoke coverage
- `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py` should keep one direct regression for `_append_processing_timeseries_marker(...)` with `Path` payloads; benchmark smoke does not guarantee that telemetry-marker branch executes before a live CLI run does.
- Split benchmark helper bindings that can break during `cli_support.bench` bootstrap should keep a direct fast regression in `tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py` or another non-slow helper file; do not rely only on the slow single-book helper suite for missing-import/name coverage.
- Tests that only care about benchmark computation or routing should use those lightweight publishers instead of patching `_write_benchmark_upload_bundle(...)`, `_refresh_dashboard_after_history_write(...)`, and `_start_benchmark_bundle_oracle_upload_background(...)` one by one.
- for shard-shape assertions, set `line_role_prompt_target_count=None` or an explicit `line_role_shard_target_lines`; otherwise current defaults will legally regroup several rows into one shard
- Broad routine runs should go through `./scripts/test-suite.sh` or the equivalent `make test-*` targets. `scripts/test-suite.sh` exports `COOKIMPORT_TEST_SUITE=1` so pytest can tell wrapper-driven runs from ad hoc broad raw invocations.

Common run patterns:

- `./scripts/test-suite.sh smoke`
- `./scripts/test-suite.sh fast`
- `./scripts/test-suite.sh domain parsing`
- `./scripts/test-suite.sh all-fast`
- `./scripts/test-suite.sh full`
- `. .venv/bin/activate && pytest tests/core/test_pytest_output_guidance.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_smoke.py`
- `. .venv/bin/activate && pytest --collect-only -q tests/labelstudio/test_labelstudio_benchmark_helpers_*.py`

For routine agent loops, prefer the wrapper script or `make` aliases over broad raw `pytest`.

## Compact Output Behavior

Current compact-output behavior:

- Default pytest runs avoid per-test dot/progress floods.
- Success-path print noise is removed from normal test modules.
- Compact mode is enforced from `tests/conftest.py` even when callers override `addopts`.
- `pytest -v` and `pytest -vv` are clamped back to compact mode unless the scoped verbose escape hatch applies.
- Failure hints are emitted once at run end and prefer a compact scoped rerun before suggesting deep-debug mode.

Verbose escape hatch:

- Set `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` only for one explicit test file or nodeid when a compact scoped rerun still needs traceback or capture details.
- Broad runs, directory runs, and marker runs stay compact even if `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is set.

Design intent:

- keep routine AI-assisted test runs low-noise and token-efficient,
- keep deeper diagnostics explicit and narrow.

## Known Risks and Sharp Edges

- Marker mapping is keyed by basename, so duplicate `test_*.py` filenames in different folders would collide.
- Folder names and marker routing can drift if `_FILE_MARKERS` is not kept current; when a `-m <domain>` run surprises you, inspect `tests/conftest.py` before changing the test.
- Slow-slice drift is easy to reintroduce if files are classified by intuition instead of measurement.
- Path-sensitive tests regress easily when files move unless shared helpers in `tests/paths.py` are used consistently.
- Remaining `print(...)` usage in helper scripts such as fixture generators is intentional and should not be treated as pytest noise.

## Durable Guardrails

- Keep domain-folder layout, centralized marker routing, and low-noise pytest defaults as the baseline.
- Keep expensive EPUB, OCR, browser, scheduler, and benchmark-helper paths isolated in explicit slow files instead of broadening routine slices.
- Broad tests should assert durable contracts, not mutable product-policy snapshots.
- Broad routine runs should go through `./scripts/test-suite.sh` or the matching `make test-*` wrappers; raw broad `pytest` runs should stay a warned escape hatch, not the default path.
- `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is a scoped deep-debug tool for one explicit file or nodeid, not a broad-run mode switch.
- Benchmark smoke should keep both boundaries: the real interactive single-book route with `labelstudio_benchmark(...)` stubbed, and the offline simulated whole-run single-book path with only leaf prediction/eval seams stubbed.
- Split benchmark/CLI helper stacks need both unresolved-name audits and direct fast regression anchors; do not rely only on slow end-to-end helper coverage.
- Bench Oracle, Oracle follow-up, and `cf-debug` tests should use tiny synthetic `upload_bundle_v1` fixtures under `tmp_path` unless a slow realism slice explicitly needs a larger artifact tree.
- For shard-shape assertions, opt out of the default `line_role_prompt_target_count=5` when the test needs exact per-line planning.
- LLM pack/schema tests should assert current transport and schema truth per pipeline instead of freezing one legacy shared assumption.
- Knowledge/runtime telemetry assertions must distinguish row-level from session-level counters; `taskfile_row_count` and `taskfile_session_count` are intentionally different shapes.
