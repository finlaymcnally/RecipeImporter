---
summary: "Current test-suite structure and low-noise pytest behavior reference."
read_when:
  - When changing tests folder layout, marker groups, or pytest output defaults
  - When test output noise increases or compact output behavior regresses
---

# Testing README

This file is the source of truth for current test-suite structure and pytest output behavior.

Use `docs/12-testing/12-testing_log.md` for build/fix history and prior attempts.

## Scope

This section covers:

- test folder/domain organization,
- layout exceptions and support assets under `tests/`,
- marker-based focused runs,
- compact pytest output defaults,
- compact-output enforcement rules when callers override `addopts`.

## Current Layout and Entry Points

Primary test folders:

- `tests/analytics`
- `tests/bench`
- `tests/cli`
- `tests/core`
- `tests/ingestion`
- `tests/labelstudio`
- `tests/llm`
- `tests/parsing`
- `tests/staging`
- `tests/tagging`

Active layout exceptions and support assets:

- `tests/test_eval_freeform_practical_metrics.py` remains at `tests/` root and is marker-tagged as both `labelstudio` and `bench`.
- CLI output-structure coverage is split into:
  - `tests/cli/test_cli_output_structure_fast.py` (fast default-surface contract checks via settings/signatures, no full stage run),
  - `tests/cli/test_cli_output_structure_epub_fast.py` (fast mocked EPUB backend/report wiring checks),
  - `tests/cli/test_cli_output_structure_text_fast.py` (text-focused fast structure checks with `--llm-recipe-pipeline off`),
  - `tests/cli/test_cli_output_structure_slow.py` (real EPUB integration checks kept intentionally slow).
- PDF importer coverage is split into:
  - `tests/ingestion/test_pdf_importer.py` (fast unit/integration seams with mocked OCR paths),
  - `tests/ingestion/test_pdf_importer_ocr_slow.py` (real scanned-PDF OCR integration).
- Stats dashboard coverage is split into:
  - `tests/analytics/test_stats_dashboard.py` (fast renderer/schema/collector coverage),
  - `tests/analytics/test_stats_dashboard_slow.py` (browser pixel-overflow rerender harness).
- Label Studio benchmark-helper coverage is split into:
  - `tests/labelstudio/test_labelstudio_benchmark_smoke.py` (smoke-level real interactive single-offline benchmark wiring plus the real single-offline helper, with only `labelstudio_benchmark(...)` stubbed so no CodexFarm traffic occurs),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py` (import/eval/discovery/default contracts),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py` (interactive settings/menu/offline routing),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py` (prediction-run prompt/log/manifest helper contracts),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py` (single-offline orchestration and routing),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_artifacts.py` (single-offline comparison/starter-pack/runtime helpers),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_export_selection.py` (interactive export/project-selection flows),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_compare.py` (benchmark compare payload acceptance),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_execution.py` (benchmark prediction/eval artifact wiring),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_pipelined.py` (pipelined prediction/eval streaming behavior),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_artifacts.py` (prune/extractor validation behavior),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py` (progress/status/dashboard rendering contracts),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_targets.py` (all-method target discovery and variant construction),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_planning.py` (scheduler limits/planning/runtime math),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_global_queue.py` (global-queue execution and eval scheduling),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_prediction_reuse.py` (prediction reuse and adapter-forwarding behavior),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_run_reports.py` (all-method run reporting/timeouts/retries),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_multi_source.py` (multi-source batching and interactive all-method routing),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py` (single-profile matched-book flows).
  - Shared helper state for this cluster belongs in `tests/labelstudio/benchmark_helper_support.py`; do not rebuild a giant `benchmark_helper_cases.py`-style pseudo-mega-file.
- Label Studio prelabel coverage is split into:
  - `tests/labelstudio/test_labelstudio_prelabel.py` (block/span labeling + prompt template contracts),
  - `tests/labelstudio/test_labelstudio_prelabel_codex_cli.py` (codex CLI command/config/usage/account contracts).
- Codex orchestrator coverage is split into:
  - `tests/llm/test_codex_farm_orchestrator.py` (orchestrator policy behavior),
  - `tests/llm/test_codex_farm_orchestrator_runner_transport.py` (subprocess runner + CLI transport contracts),
  - `tests/llm/test_codex_farm_orchestrator_stage_integration.py` (stage seam integration tests).
- Bench CLI coverage is split into:
  - `tests/bench/test_bench.py` (aggregate/noise/cost helper contracts),
  - `tests/bench/test_bench_speed_cli.py` (speed discover/run/compare CLI wiring),
  - `tests/bench/test_bench_quality_cli.py` (quality discover/run/compare/leaderboard CLI wiring).
- Step ingredient linking coverage is split into:
  - `tests/parsing/test_step_ingredient_linking.py` (core assignment/split logic),
  - `tests/parsing/test_step_ingredient_linking_semantic.py` (semantic/fuzzy/collective matching).
- `tests/fixtures/*` holds fixture generators and binary fixture assets used by tests.
- `tests/tagging_gold/*` holds tagging gold fixtures used by tagging tests.

Key test-runtime files:

- `pytest.ini`
- `tests/conftest.py`
- `tests/paths.py`
- `tests/README.md`
- `tests/CONVENTIONS.md`
- `tests/AGENTS.md`

Path helper contract:

- `tests/paths.py` is the shared root resolver for `REPO_ROOT`, `FIXTURES_DIR`, `TAGGING_GOLD_DIR`, and `DOCS_EXAMPLES_DIR`.

## Marker and Run Contracts

Current contracts:

- Marker assignment is centralized in `tests/conftest.py` (do not require touching every file for domain grouping).
- `_FILE_MARKERS` in `tests/conftest.py` currently maps every `test_*.py` filename, and unknown files would fall back to `core`.
- Domain markers declared in `pytest.ini` are: `analytics`, `bench`, `cli`, `core`, `ingestion`, `labelstudio`, `llm`, `parsing`, `staging`, `tagging`.
- `slow` and `smoke` slices are controlled centrally by `_SLOW_FILES` and `_SMOKE_FILES` in `tests/conftest.py`.
- Smoke slice exists for quick sanity (`pytest -m smoke`).
- Benchmark smoke now includes `tests/labelstudio/test_labelstudio_benchmark_smoke.py`, which runs the real interactive single-offline benchmark wiring while stubbing `labelstudio_benchmark(...)` itself so no token-spending CodexFarm path can execute.
- Domain-focused runs should work with marker filters and/or domain folders.
- Failure output should include concise pointers to relevant `docs/*_log.md` files.

Common run patterns:

- `. .venv/bin/activate && pytest -m smoke`
- `. .venv/bin/activate && pytest -m "ingestion and not slow" --collect-only`
- `. .venv/bin/activate && pytest tests/labelstudio -m "labelstudio and not slow" --collect-only`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_fast.py`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_epub_fast.py`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_text_fast.py`
- `. .venv/bin/activate && pytest tests/cli/test_cli_output_structure_slow.py`
- `. .venv/bin/activate && pytest tests/ingestion/test_pdf_importer.py`
- `. .venv/bin/activate && pytest tests/ingestion/test_pdf_importer_ocr_slow.py`
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py`
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard_slow.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_artifacts.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_export_selection.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_compare.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_execution.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_pipelined.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_artifacts.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_targets.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_planning.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_global_queue.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_prediction_reuse.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_run_reports.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_multi_source.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_prelabel.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_prelabel_codex_cli.py`
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator.py`
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator_runner_transport.py`
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator_stage_integration.py`
- `. .venv/bin/activate && pytest tests/bench/test_bench.py`
- `. .venv/bin/activate && pytest tests/bench/test_bench_speed_cli.py`
- `. .venv/bin/activate && pytest tests/bench/test_bench_quality_cli.py`
- `. .venv/bin/activate && pytest tests/parsing/test_step_ingredient_linking.py`
- `. .venv/bin/activate && pytest tests/parsing/test_step_ingredient_linking_semantic.py`
- `./scripts/test-suite.sh smoke`
- `./scripts/test-suite.sh fast`
- `./scripts/test-suite.sh domain <domain>`
- `./scripts/test-suite.sh all-fast`
- `./scripts/test-suite.sh full`
- `./scripts/test-suite.sh domain parsing --collect-only`

For fast-feedback agent workflows, use these `scripts/test-suite.sh` modes by default. Avoid raw `pytest` routine loops; the unchunked full path can exceed 5 minutes and should be used only intentionally.
`make test-smoke`, `make test-fast`, `make test-domain DOMAIN=<domain>`, `make test-all-fast`, and `make test-full` are the same wrapper entry points when a shorter command helps.

## Compact Output Behavior

Current compact-output behavior:

- Default pytest runs avoid per-test dot/progress floods.
- Success-path print noise is removed from normal test modules.
- Compact mode remains enforced even with `-o addopts=''` unless explicit verbose opt-out is requested.
- `pytest -v/-vv` is clamped back to compact mode unless scoped verbose opt-out is enabled.
- Failure hints are emitted once at run end (not per failure) by `pytest_terminal_summary(...)`/`pytest_sessionfinish(...)`, and they now prefer a compact scoped rerun before suggesting deep-debug mode.

Verbose opt-out contract:

- Set `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` only for one explicit test file or nodeid when a compact rerun still needs full traceback/capture details.
- Broad runs, marker runs, and directory runs stay compact even if `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is set.

Design intent:

- Keep routine AI-assisted test runs low-noise and token-efficient.
- Keep deeper diagnostics explicitly opt-in.

## Known Risks and Sharp Edges

- Overly strict compact-mode enforcement can surprise contributors expecting manual `-v/-vv` alone to restore classic pytest output.
- Marker mapping is keyed by basename (`test_*.py` filename), so duplicate names across different folders would collide.
- Path-sensitive tests can regress when files move unless shared helpers in `tests/paths.py` are used consistently.
- Remaining `print(...)` usage in manual helper scripts (for example `tests/fixtures/generate_scanned_pdf.py`) is intentional and should not be treated as test-runner noise.

## Active Guardrails (Historical Outcomes Still In Effect)

- 2026-02-22: low-noise defaults and centralized marker mapping introduced and are still active.
- 2026-02-22: tests were reorganized into domain folders; `tests/paths.py` remains the path-stability helper.
- 2026-02-22: success-path test stdout noise was trimmed; only intentional helper-script prints remain.
- 2026-02-22: compact-output enforcement on `addopts` override landed and now remains scoped opt-out only: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is honored for one explicit file or nodeid, not for broad directory/marker runs.

## 2026-02-27 Merged Understandings: Testing Docs Prune + Coverage Audit

Merged source notes:
- `docs/understandings/2026-02-27_19.44.54-testing-doc-pruning-current-contracts.md`
- `docs/understandings/2026-02-27_19.50.34-testing-doc-code-coverage-audit.md`

Current-contract additions:
- Keep docs aligned to current domain-folder layout plus intentional root-level cross-domain module (`tests/test_eval_freeform_practical_metrics.py`).
- Keep support-asset folders (`tests/fixtures/*`, `tests/tagging_gold/*`) and `tests/paths.py` constants documented as active test contract surfaces.
- Keep marker fallback semantics documented: unmapped test files default to marker `core`.
- Keep stale `docs/tasks/*` links and old flat-path examples retired.

Anti-loop rule:
- Before changing testing docs/contracts, verify `tests/conftest.py` marker mapping and compact-output enforcement behavior first.

## 2026-03-04 merged understandings digest (CLI output-structure fast/slow split)

Merged source notes:
- `2026-03-04_01.03.03-cli-output-structure-fast-slow-split.md`
- `2026-03-04_01.04.31-cli-output-structure-fast-default-surface-contract.md`

Current testing contracts reinforced:
- CLI output-structure coverage is intentionally split into:
  - fast default/shape checks (`tests/cli/test_cli_output_structure_fast.py`),
  - slower EPUB-heavy integration checks (`tests/cli/test_cli_output_structure_slow.py`).
- Fast structure tests must avoid codex runtime drift by asserting defaults/signatures/settings loaders rather than triggering full codex-backed stage runs.
- Slow-path coverage should remain explicitly marked/isolated so routine CLI test loops stay fast (`-m "cli and not slow"`).

Anti-loop reminder:
- If CLI structure tests slow down after default changes, move default-contract assertions into fast signature/settings tests before broadening slow integration scope.

## 2026-03-04 docs/tasks merge digest (CLI output-structure test split)

Merged source task file:
- `docs/tasks/2026-03-04_01.08.41-cli-output-structure-test-split.md`

Current testing contract reinforced:
- CLI output-structure coverage remains split by cost/signal:
  - `test_cli_output_structure_fast.py` for default-contract/surface checks,
  - `test_cli_output_structure_epub_fast.py` for mocked EPUB backend/report contracts,
  - `test_cli_output_structure_text_fast.py` for fast structure checks,
  - `test_cli_output_structure_slow.py` for EPUB-heavy checks.
- Slow marker assignment should stay narrow (only slow EPUB-heavy file), so `-m "cli and not slow"` remains a fast operator loop.

## 2026-03-13 docs/tasks merge digest (remaining benchmark-helper mega-test breakup)

Current testing contract reinforced:
- Label Studio benchmark-helper coverage stays split by behavior instead of regrouping around one giant scheduler/eval helper file.
- `tests/labelstudio/benchmark_helper_support.py` is intentionally a small support module. Shared writers/helpers live there, but real test bodies should stay in focused `test_labelstudio_benchmark_helpers_*` files.
- If a benchmark-helper refactor leaves the top-level files smaller but recreates a 3k-4k line support module, that is still a maintainability regression.

## 2026-03-14 merged docs/tasks digest (single-offline benchmark regression coverage)

Current testing contract reinforced:
- Single-offline benchmark regressions need two guard layers:
  - one narrow helper-level test on `_interactive_single_offline_variants()` for persistence-metadata boundaries,
  - one interactive CLI-path test that stays fully offline by stubbing `labelstudio_benchmark`.
- Broader benchmark-helper suites can still catch these bugs, but they are too indirect to be the only guard for variant-planner crashes or credential-prompt regressions.

Anti-loop reminder:
- When CLI defaults evolve, prefer extending fast signature/settings assertions before adding expensive integration paths to default loops.

## 2026-03-04 merged understandings digest (slow-slice recalibration + modular test seams)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.15.04-slow-marker-recalibration-and-dashboard-pixel-split.md`
- `docs/understandings/2026-03-04_01.22.00-labelstudio-benchmark-helper-modular-seams.md`
- `docs/understandings/2026-03-04_01.25.56-codex-orchestrator-test-modular-seams.md`
- `docs/understandings/2026-03-04_01.33.59-prelabel-steplinking-bench-test-modular-seams.md`
- `docs/understandings/2026-03-04_01.36.47-labelstudio-benchmark-helper-progress-seam.md`

Current testing contracts reinforced:
- `_SLOW_FILES` should stay narrowly scoped to genuinely expensive files; fast files should not be dragged into `-m slow` by historical classifications.
- Dashboard browser pixel-overflow coverage is intentionally isolated in `tests/analytics/test_stats_dashboard_slow.py`; fast dashboard logic stays in `tests/analytics/test_stats_dashboard.py`.
- Large mixed modules should stay split by functional seam:
  - labelstudio benchmark helper: general vs eval payload vs scheduler vs single-profile vs progress,
  - codex orchestrator: policy vs runner transport vs stage integration,
  - prelabel: prompt/span contracts vs codex CLI contracts,
  - step-linking: core heuristics vs semantic/fuzzy/collective,
  - bench CLI: helper/noise/cost vs speed wiring vs quality wiring.
- Split modules may share base-module helper state through controlled non-test-global injection to avoid fixture duplication.

Anti-loop reminders:
- If targeted test runs become broad again, check module split boundaries before changing marker policies.
- If slow runs regrow, remeasure file runtime first; do not promote files to slow by assumption.

## 2026-03-04 docs/tasks merge digest (slow-slice recalibration + modular test seams)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.15.04-slow-marker-recalibration-and-dashboard-split.md`
- `docs/tasks/2026-03-04_01.22.00-labelstudio-benchmark-helper-modular-split.md`
- `docs/tasks/2026-03-04_01.25.56-codex-orchestrator-test-modular-split.md`
- `docs/tasks/2026-03-04_01.33.59-prelabel-steplinking-bench-test-modular-split.md`
- `docs/tasks/2026-03-04_01.36.47-labelstudio-benchmark-helper-progress-split.md`

Current testing contracts reinforced:
- Keep `slow` marker scope cost-based and narrow; avoid historical over-classification of now-fast suites.
- Dashboard browser pixel harness stays isolated in `tests/analytics/test_stats_dashboard_slow.py`, with fast dashboard checks kept in `test_stats_dashboard.py`.
- Maintain concern-based test modularization for focused loops:
  - labelstudio benchmark helper split into base/eval/scheduler/single-profile/progress seams,
  - codex orchestrator split into policy/runner transport/stage integration seams,
  - prelabel split into prompt/span vs codex CLI seams,
  - step-linking split into core vs semantic/fuzzy/collective seams,
  - bench CLI split into core helper vs speed wiring vs quality wiring seams.
- Keep `tests/conftest.py` marker mapping complete for each new split file; avoid duplicate basename collisions.

Known gotchas retained:
- Split modules intentionally import shared non-test globals from base modules; copying dunder globals can trigger pytest import-file mismatch.
- Browser/pixel harnesses are environment-sensitive and belong in the slow slice unless runtime profile changes materially.

## 2026-03-06 merged understandings digest (default-policy assertions + runtime offenders)

Current testing contracts reinforced:
- Do not freeze mutable product policy into broad default-surface tests.
  - `RunSettings` tests should assert serialization/sync contracts.
  - CLI tests should assert explicit safe defaults only where the command contract is intentionally narrower (for example `labelstudio_benchmark`).
- Interactive preset tests should compare against preset builders/harmonizers, not duplicated literal settings blobs.
- Fast-suite runtime wins that are now part of the intended test shape:
  - mock stage pipeline work when a test only needs output/report contract shape,
  - force serial executor resolution in hot-path tests that do not exercise worker orchestration,
  - isolate real EPUB/OCR/browser-wait coverage into explicit slow files,
  - clamp or poll browser timing instead of relying on long fixed waits.

## 2026-03-04 docs/tasks merge digest (pytest runtime offenders and remediation)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.59.29-pytest-runtime-offenders-fast-slow.md`
- `docs/tasks/2026-03-04_12.38.59-pytest-runtime-offender-remediation.md`

Current testing contracts reinforced:
- Runtime work should start from measured offender reports, not intuition. The March 4 baseline recorded:
  - fast suite (`-m "not slow"`) wall time `160.331s`,
  - slow suite (`-m "slow"`) wall time `63.613s`.
- Runtime wins came from narrowing high-cost seams, not from broad marker churn:
  - heavy artifact-shape tests should mock stage/orchestration work,
  - real EPUB/OCR/browser flows belong in explicit slow modules,
  - expensive mixed modules should be split when targeted speedups are not practical.
- The top March 4 remediation results that are now part of the intended suite shape:
  - `tests/ingestion/test_performance_features.py`: `43.24s -> 10.83s`
  - `tests/cli/test_cli_output_structure_text_fast.py`: `21.22s -> 7.20s`
  - `tests/analytics/test_stats_dashboard_slow.py`: `27.98s -> 5.05s`
  - `tests/analytics/test_stats_dashboard.py`: `18.04s -> 13.75s`
- Marker mapping in `tests/conftest.py` remains the control plane for fast/slow routing; do not “fix” runtime by casually reclassifying files without first remeasuring them.

Anti-loop reminder:
- When a suite gets slow again, profile the file/case offenders first. Reclassifying tests into `slow` without measurement tends to hide regressions instead of solving them.

## 2026-03-06 merged understandings digest (wrapper-first routine runs)

Merged source note:
- `2026-03-06_15.05.00-test-wrapper-enforcement-and-raw-pytest-warning.md`

Current testing contracts reinforced:
- Routine agent test loops should go through `./scripts/test-suite.sh` or the equivalent `make test-*` wrappers rather than broad raw `pytest`.
- `scripts/test-suite.sh` exports `COOKIMPORT_TEST_SUITE=1` so pytest can tell wrapper-driven runs from ad hoc raw invocations.
- `tests/conftest.py` should warn only for broad raw pytest runs:
  - directory runs,
  - multi-file cross-domain batches without a marker filter.
- Narrow single-file raw pytest remains a supported quiet path for targeted diagnosis.

Anti-loop reminder:
- If review logs show repeated broad raw pytest runs again, fix the wrapper signal or the warning gate before adding more policy text to individual tests.

## 2026-03-14 merged understandings digest (single-offline benchmark guardrail layers)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-14_14.50.52-single-offline-test-coverage-seam.md`
- `docs/understandings/2026-03-14_15.58.29-benchmark-smoke-boundary.md`

Current testing contracts reinforced:
- Single-offline benchmark regressions need two complementary guardrails:
  - one narrow `_interactive_single_offline_variants()` regression test for persistence-metadata projection failures,
  - one interactive CLI-path regression that stays offline by stubbing `labelstudio_benchmark(...)`.
- The durable benchmark smoke boundary is broader than a unit test but narrower than a live benchmark run:
  - run the real `_interactive_mode()` path,
  - let it call the real `_interactive_single_offline_benchmark(...)`,
  - stub only `labelstudio_benchmark(...)` to a local artifact writer.
- That smoke boundary is intentionally responsible for menu routing, run-settings handoff, variant planning, output-path, and comparison-artifact sanity without ever invoking real CodexFarm work or credential prompts.

Anti-loop reminder:
- If a benchmark smoke test needs live CodexFarm work or Label Studio credentials to catch a single-offline regression, the smoke boundary has been set too wide.

## 2026-03-15 merged understandings digest (plan-mode benchmark tests and strict fixture contracts)

Merged source notes:
- `docs/understandings/2026-03-15_16.08.34-benchmark-test-plan-mode-vs-live-codex-guardrail.md`
- `docs/understandings/2026-03-15_17.15.45-strict-runsettings-fixtures-and-split-merge-status.md`

Current testing contracts reinforced:
- Benchmark/helper tests that only validate local artifact wiring should use `codex_execution_policy=plan` once agent environments block live benchmark Codex execution. Plan-mode assertions must check plan artifacts and plan-oriented manifest fields, not live-execution outputs such as `llm_manifest_json` or upload bundles.
- Mixed payload fixtures must project to live `RunSettings` fields before calling `RunSettings.from_dict(...)`; retired compatibility keys should not linger in tests just because manifests persist broader `run_config_*` data.
- Split-merge status assertions need two layers:
  - merge-phase milestone messages
  - plain forwarded session callback lines
- `OutputStats` parity tests must keep one accumulator through split-merge so moved raw `full_text.json` artifacts remain counted.

Anti-loop reminder:
- If a test only needs wiring/manifest coverage, moving it to plan mode is usually the right fix. Do not fight the live Codex guardrail just to exercise local artifact plumbing.
