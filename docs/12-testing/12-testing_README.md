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

- `tests/analytics`
- `tests/bench`
- `tests/cli`
- `tests/core`
- `tests/ingestion`
- `tests/labelstudio`
- `tests/llm`
- `tests/parsing`
- `tests/staging`

Current layout exceptions and intentional split seams:

- `tests/test_eval_freeform_practical_metrics.py` intentionally stays at `tests/` root and is marked as both `labelstudio` and `bench`.
- CLI output-structure coverage is split into:
  - `tests/cli/test_cli_output_structure_fast.py`
  - `tests/cli/test_cli_output_structure_epub_fast.py`
  - `tests/cli/test_cli_output_structure_text_fast.py`
  - `tests/cli/test_cli_output_structure_slow.py`
- PDF importer coverage is split into:
  - `tests/ingestion/test_pdf_importer.py`
  - `tests/ingestion/test_pdf_importer_ocr_slow.py`
- Stats dashboard coverage is split into:
  - `tests/analytics/test_stats_dashboard.py`
  - `tests/analytics/test_stats_dashboard_slow.py`
- Label Studio benchmark coverage is intentionally spread across focused files instead of one helper mega-file:
  - smoke path: `tests/labelstudio/test_labelstudio_benchmark_smoke.py`
  - interactive/import/export/artifact flows: `..._interactive.py`, `..._import_eval.py`, `..._export_selection.py`, `..._artifacts.py`, `..._progress.py`
  - eval payload seams: `..._eval_payload_compare.py`, `..._eval_payload_execution.py`, `..._eval_payload_pipelined.py`, `..._eval_payload_artifacts.py`
  - scheduler seams: `..._scheduler_targets.py`, `..._scheduler_planning.py`, `..._scheduler_global_queue.py`, `..._scheduler_prediction_reuse.py`, `..._scheduler_run_reports.py`, `..._scheduler_multi_source.py`
  - single-offline and single-profile seams: `..._single_offline_run.py`, `..._single_offline_artifacts.py`, `..._single_profile.py`
- Shared Label Studio benchmark helper support belongs in `tests/labelstudio/benchmark_helper_support.py`; do not rebuild a large support pseudo-test module.
- Label Studio prelabel coverage is split into:
  - `tests/labelstudio/test_labelstudio_prelabel.py`
  - `tests/labelstudio/test_labelstudio_prelabel_codex_cli.py`
- Codex orchestrator coverage is split into:
  - `tests/llm/test_codex_farm_orchestrator.py`
  - `tests/llm/test_codex_farm_orchestrator_runner_transport.py`
  - `tests/llm/test_codex_farm_orchestrator_stage_integration.py`
- Bench CLI coverage is split into:
  - `tests/bench/test_bench.py`
  - `tests/bench/test_bench_speed_cli.py`
  - `tests/bench/test_bench_quality_cli.py`
- Step ingredient linking coverage is split into:
  - `tests/parsing/test_step_ingredient_linking.py`
  - `tests/parsing/test_step_ingredient_linking_semantic.py`
- Canonical line-role coverage is split into:
  - `tests/parsing/test_canonical_line_role_env.py` for fast env/helper guardrails
  - `tests/parsing/test_canonical_line_roles.py` for the heavy behavior suite
- tests that assert exact line-role shard ids, proposal filenames, or worker assignments must opt out of the default `line_role_prompt_target_count=5`; `codex_batch_size=1` alone no longer means one line per shard
- Small live Codex env/import helpers should keep one direct non-slow regression test even when broader slow integration coverage already exists.
- CLI path-resolution tests should prefer synthesizing the minimal artifact contract they need under `tmp_path` instead of depending on repo-local sample benchmark roots.

Support assets and test-runtime files:

- `tests/fixtures/*` holds fixture generators and binary fixture assets.
- `pytest.ini`, `tests/conftest.py`, `tests/paths.py`, `tests/README.md`, `tests/CONVENTIONS.md`, and `tests/AGENTS.md` are active test-runtime control surfaces.
- `tests/paths.py` is the shared root resolver for `REPO_ROOT`, `FIXTURES_DIR`, and `DOCS_EXAMPLES_DIR`.

## Marker and Run Contracts

Current contracts:

- Marker assignment is centralized in `tests/conftest.py`; do not spread domain markers across individual test files.
- `_FILE_MARKERS` maps test filenames to domain markers. Unknown `test_*.py` files fall back to marker `core`.
- Markers declared in `pytest.ini` are: `analytics`, `bench`, `cli`, `core`, `ingestion`, `labelstudio`, `llm`, `parsing`, `staging`, `slow`, and `smoke`.
- `slow` and `smoke` routing is controlled centrally by `_SLOW_FILES` and `_SMOKE_FILES` in `tests/conftest.py`.
- If you add or rename a test file, update `_FILE_MARKERS` and then decide whether the file also belongs in `_SLOW_FILES` or `_SMOKE_FILES`.
- The `slow` slice is intentionally narrow and currently covers only the explicitly high-cost files in `tests/conftest.py`; do not widen it without measuring runtime first.
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py` is part of `slow`; routine `labelstudio` domain runs should not pay for full single-offline comparison/bundle/dashboard helper coverage.
- Routing-only interactive benchmark tests should stub `_interactive_single_offline_benchmark(...)` and assert the handoff arguments instead of re-exercising the helper internals from `test_labelstudio_benchmark_helpers_interactive.py`.
- Several historically named “fast” integration files are intentionally slow-marked because measured runtime is too high for routine loops: `tests/analytics/test_stats_dashboard.py`, `tests/ingestion/test_performance_features.py`, `tests/cli/test_cli_output_structure_epub_fast.py`, `tests/cli/test_cli_output_structure_text_fast.py`, and `tests/parsing/test_canonical_line_roles.py`.
- Historical filename hints are not enough to classify cost: measured hotspot files now include roughly `45s` for `tests/analytics/test_stats_dashboard.py`, `15s` for `tests/ingestion/test_performance_features.py`, `11s` each for the EPUB/text CLI output-structure files, and `24s` for `tests/parsing/test_canonical_line_roles.py`, so those files stay slow-marked despite their old names.
- Broad compact pytest runs are a poor hotspot profiler here; use one-file pytest invocations when measuring candidate slow files because the compact reporter suppresses most useful `--durations` detail in broad runs.
- Prefer moving proven heavy helper-internal suites into `_SLOW_FILES` before changing production code for test speed; production edits need a stronger reason than loop runtime alone.
- The benchmark smoke slice includes the real interactive single-offline benchmark path while stubbing `labelstudio_benchmark(...)` so smoke runs catch routing and artifact regressions without spending tokens.
- for shard-shape assertions, set `line_role_prompt_target_count=None` or an explicit `line_role_shard_target_lines`; otherwise current defaults will legally regroup several rows into one shard
- Before the Label Studio fast-slice cleanup, `tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py` was about `121s` and `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py` was about `79s`; keep interactive routing tests at the handoff boundary unless you intentionally want full helper coverage in the slow slice.
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
- Slow-slice drift is easy to reintroduce if files are classified by intuition instead of measurement.
- Path-sensitive tests regress easily when files move unless shared helpers in `tests/paths.py` are used consistently.
- Remaining `print(...)` usage in helper scripts such as fixture generators is intentional and should not be treated as pytest noise.

## Durable Guardrails

- 2026-02-22: domain-folder layout, centralized marker mapping, and low-noise pytest defaults became the durable baseline.
- 2026-03-04: mixed-cost and mixed-seam suites were split into focused files; keep fast files fast and isolate expensive EPUB, OCR, browser, and benchmark scheduler/eval coverage explicitly.
- 2026-03-05: broad default-surface tests should assert durable contracts, not freeze mutable product-policy snapshots.
- 2026-03-06: broad routine runs should use the wrapper script; raw broad pytest runs warn instead of silently normalizing that path.
- 2026-03-14: the benchmark smoke boundary is the real interactive single-offline flow with only `labelstudio_benchmark(...)` stubbed.
- 2026-03-15: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is a scoped deep-debug tool for one explicit file or nodeid, not a broad-run mode switch.
- 2026-03-15: benchmark-helper tests that only need local artifact wiring should stub the offline execute path directly, and mixed `RunSettings` payloads must be projected to live model fields before `RunSettings.from_dict(...)`.
- 2026-03-16: direct helper seams on live Codex paths need their own fast regression anchors; relying only on slow benchmark coverage leaves routine `fast` runs blind to simple import/env crashes.
- 2026-03-16: CLI tests like `tests/bench/test_benchmark_oracle_upload.py` should build a minimal `upload_bundle_v1` fixture under `tmp_path` rather than pinning to one checked-in benchmark directory.
