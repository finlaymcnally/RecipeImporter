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
- Verbose opt-out is still only `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.
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
- Keep explicit opt-out via `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.

Anti-loop note:
- If full verbosity is needed, use the env opt-out instead of weakening compact defaults.

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
