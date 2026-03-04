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
