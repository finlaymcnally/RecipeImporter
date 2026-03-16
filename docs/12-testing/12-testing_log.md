---
summary: "Testing architecture/build/fix-attempt log for suite structure and low-noise pytest behavior."
read_when:
  - When test-suite organization or pytest output behavior starts going in circles
  - When compact pytest output contracts, marker grouping, or path helpers are being changed
---

# Testing Log

Read `docs/12-testing/12-testing_README.md` first for current behavior.
Use this log for historical decisions, verification evidence, and anti-loop notes.

## Current Verification Snapshot (2026-02-27_19.50)

Repository checks rerun against current code:

- `. .venv/bin/activate && pytest -m smoke`
  - `39 passed, 662 deselected, 2 warnings in 2.59s`
- `. .venv/bin/activate && pytest -m "ingestion and not slow" --collect-only`
  - `41/701 tests collected (660 deselected) in 2.16s`
- `. .venv/bin/activate && pytest tests/labelstudio -m "labelstudio and not slow" --collect-only`
  - `8/193 tests collected (185 deselected) in 2.06s`

Current contract confirmation:

- Marker assignment and smoke/slow slices are still centralized in `tests/conftest.py`.
- `_FILE_MARKERS` currently covers all `74/74` `test_*.py` filenames; no unmapped files were found.
- Fallback behavior remains: unmapped test filenames would receive marker `core`.
- Compact output is still enforced from `pytest_configure(...)` even when callers pass `-o addopts=''`.
- Verbose opt-out is now scoped: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` only enables full verbosity for one explicit file or nodeid, while broad directory/marker runs stay compact.
- Domain folders remain the primary layout, with one intentional root-level cross-domain module: `tests/test_eval_freeform_practical_metrics.py`.
- Support data surfaces under tests remain active: `tests/fixtures/*` and `tests/tagging_gold/*`.
- Shared path helper constants in `tests/paths.py` remain active (`REPO_ROOT`, `FIXTURES_DIR`, `TAGGING_GOLD_DIR`, `DOCS_EXAMPLES_DIR`).

## 2026-03-04_01.03.03 CLI output-structure split for faster default CLI test loops

Problem captured:
- `tests/cli/test_cli_output_structure.py` bundled text + EPUB structure checks in one file, and the file-level slow classification made routine CLI structure loops heavier than needed.
- Stage default now enables codex-farm recipe correction (`llm_recipe_pipeline=codex-farm-3pass-v1`), so unscoped structure tests can drift into expensive paths.

Changes made:
- Split the file into:
  - `tests/cli/test_cli_output_structure_fast.py` for fast default-surface contract checks via settings/signatures.
  - `tests/cli/test_cli_output_structure_text_fast.py` for text-focused output-structure assertions and explicit `--llm-recipe-pipeline off`.
  - `tests/cli/test_cli_output_structure_slow.py` for EPUB-heavy extractor/backend coverage.
- Updated `tests/conftest.py` marker map for new filenames.
- Updated `_SLOW_FILES` to mark only `test_cli_output_structure_slow.py` as slow.

Verification:
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_fast.py`
  - `4 passed, 1 warning in 1.79s`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_text_fast.py`
  - `5 passed, 1 warning in 19.26s`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_slow.py`
  - `5 passed, 1 warning in 21.33s`
- `. .venv/bin/activate && pytest -m "cli and not slow" --collect-only`
  - fast CLI structure tests are included from `test_cli_output_structure_fast.py` and `test_cli_output_structure_text_fast.py`; slow EPUB structure tests are excluded.

## 2026-03-04_01.15.04 slow-marker recalibration + stats dashboard fast/slow split

Problem captured:
- `_SLOW_FILES` had many stale entries; several files were now sub-3s runs but still forced into `-m slow`.
- `tests/analytics/test_stats_dashboard.py` contained one browser pixel harness (~5s) mixed with otherwise fast dashboard tests.

Changes made:
- Split dashboard pixel harness into `tests/analytics/test_stats_dashboard_slow.py`.
- Kept the remaining dashboard suite in `tests/analytics/test_stats_dashboard.py`.
- Recalibrated `_SLOW_FILES` to high-cost files only:
  - `test_cli_output_structure_slow.py`
  - `test_codex_farm_orchestrator.py`
  - `test_labelstudio_benchmark_helpers.py`
  - `test_stats_dashboard_slow.py`

Verification:
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py`
  - `70 passed in 9.65s`
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard_slow.py`
  - `1 passed in 5.39s`
- `. .venv/bin/activate && pytest -m slow --collect-only -q`
  - collects only the four high-cost files listed above.

## 2026-03-04_01.22.00 labelstudio benchmark-helper modular split (eval vs scheduler vs single-profile)

Problem captured:
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` still mixed large benchmark concerns in one file, making focused runs harder.
- Fast triage needed explicit seams for:
  - benchmark eval payload contract assertions,
  - all-method scheduler internals,
  - single-profile matched-book orchestration flows.

Changes made:
- Split tests into dedicated modules:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py` (26 tests),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py` (66 tests),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py` (7 tests).
- Kept remaining general flows in `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (75 tests).
- Updated `tests/conftest.py` marker mapping for all new files.
- Re-scoped slow labeling to heavy benchmark-helper modules:
  - `test_labelstudio_benchmark_helpers_eval_payload.py`
  - `test_labelstudio_benchmark_helpers_scheduler.py`

Verification:
- `. .venv/bin/activate && pytest --collect-only -q tests/labelstudio/test_labelstudio_benchmark_helpers*.py`
  - `75 + 26 + 66 + 7` tests collected across split modules.
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py::test_labelstudio_benchmark_direct_call_uses_real_defaults tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py::test_build_all_method_variants_non_epub_single_variant tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py::test_interactive_benchmark_single_profile_all_matched_mode_routes_to_runner`
  - `3 passed, 1 warning in 2.19s`
- `. .venv/bin/activate && pytest -m slow --collect-only -q tests/labelstudio`
  - slow scope now isolates eval-payload + scheduler helper modules.

## 2026-03-04_01.25.56 codex orchestrator modular split (policy vs runner transport vs stage seam)

Problem captured:
- `tests/llm/test_codex_farm_orchestrator.py` mixed three concerns in one module:
  - orchestrator policy behavior,
  - subprocess runner/transport contracts,
  - stage seam integration.

Changes made:
- Split into dedicated modules:
  - `tests/llm/test_codex_farm_orchestrator.py` (policy),
  - `tests/llm/test_codex_farm_orchestrator_runner_transport.py` (runner transport),
  - `tests/llm/test_codex_farm_orchestrator_stage_integration.py` (stage seam).
- Updated `tests/conftest.py` marker map for new files.
- Added runner-transport split module to `slow` slice; stage seam split module remains non-slow for focused fast checks.

Verification:
- `. .venv/bin/activate && pytest --collect-only -q tests/llm/test_codex_farm_orchestrator.py tests/llm/test_codex_farm_orchestrator_runner_transport.py tests/llm/test_codex_farm_orchestrator_stage_integration.py`
  - `16 + 15 + 3` tests collected.
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator.py::test_orchestrator_gates_pass3_when_pass2_degraded_missing_instruction_evidence tests/llm/test_codex_farm_orchestrator_runner_transport.py::test_subprocess_runner_reports_missing_binary tests/llm/test_codex_farm_orchestrator_stage_integration.py::test_orchestrator_runs_three_passes_and_writes_manifest`
  - `3 passed, 1 warning in 2.15s`.
- `. .venv/bin/activate && pytest -m slow --collect-only -q tests/llm`
  - collects policy + runner transport modules; stage seam module is excluded.

## 2026-03-04_01.33.59 modular split pass for prelabel, step-linking, and bench CLI tests

Problem captured:
- Three large files still mixed distinct seams, slowing focused triage loops:
  - `tests/labelstudio/test_labelstudio_prelabel.py` (prompt/span contracts mixed with codex CLI account/config/provider contracts),
  - `tests/parsing/test_step_ingredient_linking.py` (core assignment logic mixed with semantic/fuzzy/collective matching),
  - `tests/bench/test_bench.py` (bench helper/noise/cost tests mixed with speed/quality CLI wiring tests).

Changes made:
- Split prelabel tests into:
  - `tests/labelstudio/test_labelstudio_prelabel.py` (17 tests, prompt/span/task contracts),
  - `tests/labelstudio/test_labelstudio_prelabel_codex_cli.py` (19 tests, codex CLI contracts).
- Split step ingredient linking tests into:
  - `tests/parsing/test_step_ingredient_linking.py` (16 tests, core assignment/split heuristics),
  - `tests/parsing/test_step_ingredient_linking_semantic.py` (15 tests, semantic/fuzzy/collective matching).
- Split bench tests into:
  - `tests/bench/test_bench.py` (11 tests, aggregate/noise/cost/offline-determinism helpers),
  - `tests/bench/test_bench_speed_cli.py` (9 tests, speed discover/run/compare CLI wiring),
  - `tests/bench/test_bench_quality_cli.py` (11 tests, quality discover/run/compare/leaderboard wiring).
- Updated `tests/conftest.py` marker map for all four new files.

Verification:
- `. .venv/bin/activate && pytest --collect-only -q tests/labelstudio/test_labelstudio_prelabel.py tests/labelstudio/test_labelstudio_prelabel_codex_cli.py tests/parsing/test_step_ingredient_linking.py tests/parsing/test_step_ingredient_linking_semantic.py tests/bench/test_bench.py tests/bench/test_bench_speed_cli.py tests/bench/test_bench_quality_cli.py`
  - collects `17 + 19 + 16 + 15 + 11 + 9 + 11`.
- `. .venv/bin/activate && pytest tests/bench/test_bench.py::test_aggregate_metrics_empty tests/bench/test_bench_speed_cli.py::test_bench_speed_run_wires_runner tests/bench/test_bench_quality_cli.py::test_bench_quality_run_wires_runner tests/labelstudio/test_labelstudio_prelabel.py::test_prelabel_prompt_uses_file_templates tests/labelstudio/test_labelstudio_prelabel_codex_cli.py::test_codex_provider_retries_plain_codex_with_exec tests/parsing/test_step_ingredient_linking.py::test_split_language_allows_multi_step tests/parsing/test_step_ingredient_linking_semantic.py::test_synonym_green_onion_match`
  - `7 passed, 1 warning in 2.17s`.
- `. .venv/bin/activate && pytest -m 'bench and not slow' --collect-only -q tests/bench/test_bench.py tests/bench/test_bench_speed_cli.py tests/bench/test_bench_quality_cli.py`
  - collects `11 + 9 + 11`.
- `. .venv/bin/activate && pytest -m 'labelstudio and llm and not slow' --collect-only -q tests/labelstudio/test_labelstudio_prelabel.py tests/labelstudio/test_labelstudio_prelabel_codex_cli.py`
  - collects `17 + 19`.

## 2026-03-04_01.36.47 labelstudio benchmark-helper progress/status split

Problem captured:
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` still bundled progress/status/dashboard rendering contracts with general interactive/export flows.
- This made it harder to run only live progress rendering tests when triaging all-method dashboard behavior.

Changes made:
- Moved progress/status/dashboard tests into:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py` (20 tests).
- Kept remaining general flows in:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (55 tests).
- Updated `tests/conftest.py` marker mapping for the new split file.

Verification:
- `. .venv/bin/activate && pytest --collect-only -q tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py`
  - collects `55 + 20`.
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py::test_labelstudio_import_prints_processing_time tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py::test_run_with_progress_status_uses_eval_tail_floor_for_all_method_eta`
  - `2 passed, 1 warning in 3.79s`.
- `. .venv/bin/activate && pytest -m 'labelstudio and bench and not slow' --collect-only -q tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py`
  - collects `55 + 20`.

## Durable History (Still Relevant)

### 2026-02-22_22.58.41 - modular low-noise tests

Problem captured:
- Test runs were easy to over-scope and output-heavy for AI-driven workflows.

Decisions still active:
- Centralized marker grouping in `tests/conftest.py`.
- Low-noise pytest defaults in `pytest.ini`.
- Concise failure hints pointing to domain logs.

Anti-loop note:
- Keep marker logic centralized; avoid per-file marker churn.

### 2026-02-22_23.06.30 - tests folder domain reorg

Problem captured:
- Flat `tests/` root made focused runs and navigation noisy.

Decisions still active:
- Domain subfolders under `tests/` are the required layout.
- Shared `tests/paths.py` remains the path-stability helper for nested tests.

Anti-loop note:
- If path-sensitive tests regress after moves, verify `tests/paths.py` usage before changing test logic.

### 2026-02-22_23.24.59 - trim test output noise

Problem captured:
- Non-informational formatting and success-path prints bloated output.

Decisions still active:
- Suppress pass/skip glyph output via `pytest_report_teststatus(...)`.
- Keep `console_output_style = classic` for compact terminal output.
- Keep success-path `print(...)` out of normal test modules.

Guardrail:
- Assertion strings that validate product status/progress contracts are intentional and should not be removed as noise.

### 2026-02-22_23.35.12 - enforce compact output on addopts override

Problem captured:
- `pytest -o addopts='' -vv ...` bypassed compact defaults.

Decisions still active:
- Enforce compact terminal settings in `pytest_configure(...)` independent of `addopts`.
- Keep `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` as the deep-debug escape hatch, but only for one explicit test file or nodeid.

Anti-loop note:
- If full verbosity is needed, scope the rerun first. Do not weaken compact defaults just because broad runs ignore the env var now.

### 2026-03-15_22.26.06 scoped pytest verbose-output guardrail

Source task file:
- `docs/tasks/2026-03-15_22.26.06-pytest-verbose-output-guardrails.md`

Problem captured:
- Agents kept exporting `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` during routine loops, which effectively erased the compact pytest contract for broad runs.

Durable decisions:
- Broad runs, marker runs, and directory runs stay compact even when `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is set.
- Full verbose output is now reserved for one explicit test file or nodeid where the operator is clearly doing a narrow deep-debug rerun.
- Failure guidance should prefer a compact scoped rerun before suggesting full verbose mode.

Verification preserved:
- `. .venv/bin/activate && pytest tests/core/test_pytest_output_guidance.py`

Anti-loop note:
- If someone says “the env var doesn’t work anymore,” check whether they tried to use it on a broad run. That is now intentional.

### 2026-02-27_19.44.54 testing docs pruning current contracts

Problem captured:
- Testing docs retained stale task-link references and old flat-path examples.

Durable decisions:
- Keep low-noise pytest and marker-centralization history.
- Remove stale path/count evidence that no longer helps operate current layout.

### 2026-02-27_19.50.34 testing docs code-coverage audit

Problem captured:
- Testing docs under-described active support surfaces and fallback marker behavior.

Durable decisions:
- Keep root-level cross-domain module, support asset folders, and `tests/paths.py` constants documented.
- Keep explicit marker fallback (`core`) and full filename-coverage contract documented.

### 2026-03-04 understandings consolidation (CLI output-structure coverage split)

Merged source notes:
- `docs/understandings/2026-03-04_01.03.03-cli-output-structure-fast-slow-split.md`
- `docs/understandings/2026-03-04_01.04.31-cli-output-structure-fast-default-surface-contract.md`

Problem captured:
- Mixed fast text checks and slow EPUB/codex-sensitive checks in one CLI structure surface made routine test loops unnecessarily slow and drift-prone after top-tier default changes.

Durable decisions/outcomes:
- Split CLI output-structure tests into fast and slow files.
- Keep fast contract checks focused on defaults/signatures/settings-loader surfaces, not full stage executions.
- Keep slow integration checks explicitly isolated so standard CLI loops can remain deterministic and fast.

Anti-loop reminder:
- When defaults change, prefer updating fast default-surface assertions over adding new heavyweight stage runs to fast test paths.

### 2026-03-04 docs/tasks consolidation (CLI output-structure split)

Merged source task file:
- `docs/tasks/2026-03-04_01.08.41-cli-output-structure-test-split.md`

Problem captured:
- `tests/cli/test_cli_output_structure.py` mixed fast and slow checks, making routine CLI loops slower and more drift-prone after top-tier default changes.

Durable decisions/outcomes:
- Split into three files by execution profile:
  - fast defaults/contracts,
  - text-fast structure checks,
  - slow EPUB-heavy checks.
- Updated marker mapping and `_SLOW_FILES` classification so only EPUB-heavy coverage is slow.

Verification evidence preserved from task:
- `pytest tests/cli/test_cli_output_structure_fast.py` -> `4 passed, 1 warning in 1.79s`
- `pytest tests/cli/test_cli_output_structure_text_fast.py` -> `5 passed, 1 warning in 19.26s`
- `pytest tests/cli/test_cli_output_structure_slow.py` -> `5 passed, 1 warning in 21.33s`
- `pytest -m "cli and not slow" --collect-only` confirms fast inclusion + slow exclusion.

Anti-loop reminder:
- Avoid collapsing these files back into one mixed-cost module unless you re-prove fast-loop performance/coverage tradeoffs.

## 2026-03-04 understandings merge ledger (source files retired)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.15.04-slow-marker-recalibration-and-dashboard-pixel-split.md`
- `docs/understandings/2026-03-04_01.22.00-labelstudio-benchmark-helper-modular-seams.md`
- `docs/understandings/2026-03-04_01.25.56-codex-orchestrator-test-modular-seams.md`
- `docs/understandings/2026-03-04_01.33.59-prelabel-steplinking-bench-test-modular-seams.md`
- `docs/understandings/2026-03-04_01.36.47-labelstudio-benchmark-helper-progress-seam.md`

Merge note:
- Detailed outcomes for each note were already captured in the same-timestamp sections above in this log.
- This ledger is the source-retirement mapping so the removed `docs/understandings/*` files remain traceable from one place.

## 2026-03-04 docs/tasks merge ledger (source files retired)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.15.04-slow-marker-recalibration-and-dashboard-split.md`
- `docs/tasks/2026-03-04_01.22.00-labelstudio-benchmark-helper-modular-split.md`
- `docs/tasks/2026-03-04_01.25.56-codex-orchestrator-test-modular-split.md`
- `docs/tasks/2026-03-04_01.33.59-prelabel-steplinking-bench-test-modular-split.md`
- `docs/tasks/2026-03-04_01.36.47-labelstudio-benchmark-helper-progress-split.md`

### 2026-03-04_01.15.04 slow-marker recalibration + dashboard split

Problem captured:
- `-m slow` was polluted by files that no longer represented high runtime cost.
- Dashboard had one expensive pixel/browser harness mixed into an otherwise fast file.

Durable outcomes:
- Pixel/browser overflow harness isolated to `tests/analytics/test_stats_dashboard_slow.py`.
- `_SLOW_FILES` trimmed to genuinely expensive files.
- Marker-map coverage stayed complete (`missing 0`, `extra 0`).

Verification evidence retained:
- `test_stats_dashboard.py`: `70 passed in 9.65s`.
- `test_stats_dashboard_slow.py`: `1 passed in 5.39s`.
- `pytest -m slow --collect-only -q` narrowed to four high-cost files.

### 2026-03-04_01.22.00 labelstudio benchmark-helper modular split

Problem captured:
- One mixed file blocked targeted debugging and clean slow/fast boundaries.

Durable outcomes:
- Split into `..._eval_payload.py`, `..._scheduler.py`, `..._single_profile.py` with base module retained.
- Slow scope narrowed to eval + scheduler modules.
- Collection and targeted split tests remained stable.

Verification evidence retained:
- Collect counts: `75 + 26 + 66 + 7`.
- Targeted seam check: `3 passed`.

### 2026-03-04_01.25.56 codex orchestrator modular split

Problem captured:
- Policy/transport/stage seam tests were coupled in one file.

Durable outcomes:
- Split into policy (`test_codex_farm_orchestrator.py`), runner transport, and stage integration modules.
- Slow slice includes policy + runner transport; stage seam stays non-slow.

Verification evidence retained:
- Collect counts: `16 + 15 + 3`.
- Representative seam tests: `3 passed`.

### 2026-03-04_01.33.59 modular split pass (prelabel, step-linking, bench)

Problem captured:
- Three large files mixed unrelated seams, expanding collection/triage cost.

Durable outcomes:
- Prelabel split into prompt/span vs codex CLI modules.
- Step-linking split into core vs semantic/fuzzy/collective modules.
- Bench split into core helper vs speed CLI vs quality CLI modules.
- Marker-map updates preserved domain marker behavior.

Verification evidence retained:
- Collection totals: `17 + 19 + 16 + 15 + 11 + 9 + 11`.
- Representative cross-seam run: `7 passed`.

### 2026-03-04_01.36.47 benchmark-helper progress/status split

Problem captured:
- Progress/status/dashboard tests were still bundled with general helper flows.

Durable outcomes:
- Progress seam moved to `test_labelstudio_benchmark_helpers_progress.py`.
- Base helper file kept general non-progress flows.
- Marker-map coverage added for new file.

Verification evidence retained:
- Collect counts: `55 + 20`.
- Representative run: `2 passed`.

Anti-loop reminders:
- If focused runs become broad, inspect seam boundaries and marker maps before changing business logic.
- If slow runs regress, remeasure runtimes first rather than re-expanding slow by default.

### 2026-03-05_22.29.01 default-surface test cleanup

Problem captured:
- Some fast default-surface tests treated the current AI-on defaults as a sacred product contract instead of checking sync and intent.

Durable outcomes:
- `tests/llm/test_run_settings.py` now checks serialization/hash/summary consistency against current model values instead of snapshotting the whole AI-on default policy.
- `tests/cli/test_cli_output_structure_fast.py` now checks loader/signature sync with `RunSettings` where appropriate.
- Explicit safe-opt-in assertions were kept for `labelstudio_benchmark`, where `off` defaults are the real contract.

Verification evidence retained:
- `. .venv/bin/activate && pytest tests/llm/test_run_settings.py tests/cli/test_cli_output_structure_fast.py`
- Result: `16 passed`

### 2026-03-05_22.35.25 c3imp preset-test cleanup

Problem captured:
- Some interactive-menu tests were checking named preset behavior correctly, but duplicated the preset values inline instead of asserting against the preset builders.

Durable outcomes:
- `tests/cli/test_c3imp_interactive_menu.py` now compares selected settings to `run_settings_flow` preset-builder / harmonizer outputs for codexfarm and vanilla branches.
- Explicit preset-flow coverage was kept; only the duplicated literal-value assertions were removed.

Verification evidence retained:
- `. .venv/bin/activate && pytest tests/llm/test_run_settings.py tests/cli/test_cli_output_structure_fast.py tests/cli/test_c3imp_interactive_menu.py`
- Result: `37 passed`

## 2026-03-04 to 2026-03-05 migrated understanding ledger (runtime offender remediation + policy-safe assertions)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_12.38.59-pytest-runtime-offender-remediation.md`
- `docs/understandings/2026-03-05_22.00.42-test-suite-impact-audit-verification.md`
- `docs/understandings/2026-03-05_22.29.01-default-surface-test-cleanup.md`
- `docs/understandings/2026-03-05_22.35.25-c3imp-preset-test-cleanup.md`

Problem cluster captured:
- Some hot tests were still paying real orchestration/browser wait costs, while other tests were overfitting transient product policy instead of asserting durable contracts.

Durable decisions and outcomes:
- Biggest runtime wins came from removing real stage orchestration where tests only needed output/report contract shape. Mocked fast-stage helpers and serial executor forcing are now part of the intended fast-test toolbox.
- Slow-path integrations remain intentionally isolated:
  - real EPUB backend checks,
  - OCR-heavy PDF checks,
  - browser pixel-overflow dashboard checks.
- Low-level `COOKIMPORT_ALLOW_LLM` kill-switch concerns were partially overstated in audit work because pytest already sets that env var and many cited tests use fake runners or monkeypatched subprocess seams rather than live Codex.
- Default-policy cleanup rule:
  - broad `RunSettings` tests should assert serialization/current-model sync,
  - command-specific tests can still assert explicit safe defaults where the product contract really is narrower.
- `c3imp` preset tests stay useful when they compare against preset builders/harmonizers rather than hardcoded copied settings blobs.

Verification preserved:
- `tests/llm/test_run_settings.py` + `tests/cli/test_cli_output_structure_fast.py`: cleanup pass kept those files green while removing policy snapshot assertions.
- `tests/cli/test_c3imp_interactive_menu.py` stayed green after switching preset assertions to builder/harmonizer comparison.

Anti-loop notes:
- If a test breaks only because product defaults changed, first ask whether the test is asserting policy or contract.
- If a fast test starts paying worker/bootstrap cost again, inspect whether it really needs orchestration fidelity or only artifact-shape fidelity.

## 2026-03-04 docs/tasks consolidation batch (pytest runtime offenders)

### 2026-03-04_01.59.29 runtime offender report

Source task:
- `docs/tasks/2026-03-04_01.59.29-pytest-runtime-offenders-fast-slow.md`

Problem captured:
- Needed a measured file-level and case-level view of what was actually dominating fast and slow pytest slices before splitting or optimizing modules.

Durable evidence preserved:
- Fast suite wall time: `160.331s` (`pytest --maxfail=0 -m "not slow"`)
- Slow suite wall time: `63.613s` (`pytest --maxfail=0 -m "slow"`)
- Post-remediation spot checks retained from the report:
  - `tests/ingestion/test_performance_features.py`: `43.24s -> 10.83s`
  - `tests/cli/test_cli_output_structure_text_fast.py`: `21.22s -> 7.20s`
  - `tests/bench/test_quality_suite_runner.py` top cases: `12.64 / 10.52 -> 6.61 / 9.35`
  - `tests/analytics/test_stats_dashboard.py`: `18.04s -> 13.75s`
  - `tests/analytics/test_stats_dashboard_slow.py`: `27.98s -> 5.05s`

Anti-loop note:
- Reuse this offender report pattern before doing another broad test-suite refactor; otherwise it is easy to optimize the wrong file.

### 2026-03-04_12.38.59 runtime offender remediation

Source task:
- `docs/tasks/2026-03-04_12.38.59-pytest-runtime-offender-remediation.md`

Problem captured:
- A small set of modules dominated wall-clock runtime in both fast and slow slices.

Durable outcomes:
- Reduced runtime for the hot offenders where possible.
- Split heavy modules where clean speedups were not practical.
- Kept marker mapping accurate in `tests/conftest.py`.
- Updated touched docs to match the new module split boundaries.

Verification sweep retained from task:
- Focused tests across ingestion, CLI structure, QualitySuite runner, analytics dashboard, Label Studio benchmark helpers, and split-merge status.
- Consolidated sweep included:
  - `tests/fast_stage_pipeline.py`
  - `tests/ingestion/test_performance_features.py`
  - `tests/bench/test_quality_suite_runner.py` targeted auto-parallel cases
  - `tests/cli/test_cli_output_structure_text_fast.py`
  - `tests/cli/test_cli_output_structure_epub_fast.py`
  - `tests/cli/test_cli_output_structure_slow.py`
  - `tests/ingestion/test_pdf_importer.py`
  - `tests/ingestion/test_pdf_importer_ocr_slow.py`
  - `tests/analytics/test_stats_dashboard.py`
  - `tests/analytics/test_stats_dashboard_slow.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py`
  - `tests/staging/test_split_merge_status.py`

Anti-loop note:
- If runtime grows in one of these areas, inspect whether a regression reintroduced real orchestration / browser waits before splitting more files.

## 2026-03-06 migrated understanding ledger (wrapper enforcement and raw-pytest warnings)

### 2026-03-06_15.05.00 test wrapper enforcement and raw pytest warning

Source:
- `docs/understandings/2026-03-06_15.05.00-test-wrapper-enforcement-and-raw-pytest-warning.md`

Problem captured:
- Routine broad pytest invocations kept bypassing the repo wrapper despite local guidance to use `./scripts/test-suite.sh` / `make test-*` for normal loops.

Durable findings:
- `scripts/test-suite.sh` now exports `COOKIMPORT_TEST_SUITE=1` so pytest can distinguish wrapper-driven runs from ad hoc raw invocations.
- `tests/conftest.py` emits a one-line reminder only for broad raw pytest runs, specifically:
  - directory runs,
  - multi-file cross-domain batches without a marker filter.
- Narrow single-file raw pytest runs remain quiet so targeted diagnostic reruns stay practical.

Anti-loop note:
- If agents start treating every raw pytest invocation as “bad,” tighten the warning heuristic instead of suppressing wrapper guidance entirely.

## 2026-03-13_22.25.00 remaining Label Studio benchmark-helper mega-test breakup

Problem captured:
- The earlier helper split removed one top-level monolith, but large benchmark-helper files still remained:
  - `test_labelstudio_benchmark_helpers_scheduler.py`,
  - `test_labelstudio_benchmark_helpers_eval_payload.py`,
  - and a giant non-test support module, `benchmark_helper_cases.py`.

Changes made:
- Split scheduler coverage into smaller phase-oriented modules.
- Split eval-payload coverage into compare, execution, pipelined, and artifact-focused modules.
- Replaced the giant `benchmark_helper_cases.py` support file with `benchmark_helper_support.py` plus direct focused pytest modules.
- Updated marker/docs wiring so the new file layout is the documented and supported shape.

Verification preserved:
- `pytest --collect-only -q <new benchmark-helper files>` succeeded after the split.
- Representative targeted pytest slices against the new scheduler/eval modules passed.
- The largest remaining Label Studio files after the change were outside this specific helper cluster, which means future cleanup should target those separately instead of rebuilding this one.

Anti-loop note:
- Do not “solve” benchmark-helper sprawl by hiding dozens of test bodies inside a non-test support module. If the support file gets huge, the split is not done.

## 2026-03-14_14.50.52 single-offline benchmark test hardening

Problem captured:
- The single-offline metadata crash was covered only indirectly by larger benchmark-helper tests, so a planner-boundary regression could reappear without a cheap targeted failure.

Changes made:
- Added a narrow `_interactive_single_offline_variants()` regression test that fails immediately if persistence-only metadata leaks back into `RunSettings.from_dict(...)`.
- Added an interactive CLI-path regression for `labelstudio_benchmark -> single_offline` with codex recipe selection, while keeping the path fully offline by stubbing `labelstudio_benchmark` in-process.

Verification preserved:
- Focused helper regression slice passed:
  - `pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py -k 'codex_enabled_runs_only_codexfarm or preserves_selected_codex_recipe_pipeline or variants_ignore_persistence_only_metadata'`
- Focused interactive regression slice passed:
  - `pytest tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py -k 'single_offline_mode_skips_credentials or single_offline_codex_pipeline_plans_paired_runs_without_credentials'`

Anti-loop note:
- Keep single-offline benchmark regressions offline and stubbed. If a test has to invoke real CodexFarm work or prompt for credentials just to cover planner metadata boundaries, the test is scoped too broadly.

## 2026-03-14_15.58.29 benchmark smoke boundary

Source:
- `docs/understandings/2026-03-14_15.58.29-benchmark-smoke-boundary.md`

Problem captured:
- A unit-only benchmark smoke would miss menu-routing and runtime handoff failures, but a live benchmark smoke would spend tokens and introduce external failure modes that make smoke runs unusable.

Durable decisions:
- The repo’s durable benchmark smoke boundary is:
  - run the real `_interactive_mode()` path,
  - keep the real `_interactive_single_offline_benchmark(...)` helper,
  - stub only `labelstudio_benchmark(...)`.
- The stub should still emit the minimal `eval_report.json` and `run_manifest.json` artifacts so output-path and comparison wiring are exercised.
- This boundary is intentionally broad enough to catch:
  - menu-routing regressions,
  - run-settings handoff regressions,
  - paired-variant planning crashes,
  - output-path and comparison-artifact failures.

Anti-loop note:
- If smoke coverage is missing single-offline regressions, widen only up to the real interactive single-offline flow. Do not jump straight to live benchmark execution.

## 2026-03-15 migrated understanding ledger (plan-mode guardrail and strict fixture contracts)

### 2026-03-15_16.08.34 benchmark helper plan mode versus live Codex guardrail

Source:
- `docs/understandings/2026-03-15_16.08.34-benchmark-test-plan-mode-vs-live-codex-guardrail.md`

Problem captured:
- Benchmark helper tests that only needed local artifact wiring were still trying to exercise live Codex-backed benchmark execution even after agent environments intentionally blocked those runs.

Durable decisions:
- Use `codex_execution_policy=plan` for helper tests that only need scratch paths, manifest wiring, or other local benchmark artifacts.
- Once a test moves to plan mode, update expectations to the plan contract:
  - no live `llm_manifest_json`
  - no upload bundle
  - plan artifact path present
  - plan-oriented manifest metadata instead of execute-only outputs

Anti-loop note:
- If a helper test fails only because live benchmark Codex execution is blocked, change the test mode before weakening the runtime guardrail.

### 2026-03-15_17.15.45 strict RunSettings fixtures and split-merge status

Source:
- `docs/understandings/2026-03-15_17.15.45-strict-runsettings-fixtures-and-split-merge-status.md`

Problem captured:
- Strict `RunSettings.from_dict(...)` validation and split-merge callback behavior made older loose fixtures and status assertions fail in confusing ways.

Durable decisions:
- Build test fixtures from live `RunSettings` model fields only, or project mixed payloads before `from_dict(...)`.
- Keep split-merge status assertions split between top-level merge-phase milestones and plain forwarded session messages.
- Preserve a single `OutputStats` accumulator through split merge so moved raw `full_text.json` artifacts stay counted in output stats parity checks.

Anti-loop note:
- If strict fixture failures or split-merge status mismatches reappear, debug payload projection and callback-shape assumptions before loosening validation or dropping assertions.
