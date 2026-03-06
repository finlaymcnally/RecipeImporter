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
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (general interactive/export/discovery flows),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py` (benchmark eval/payload contracts),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py` (progress/status/dashboard rendering contracts),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py` (all-method scheduler internals),
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py` (single-profile matched-book flows).
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
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py`
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

## Compact Output Behavior

Current compact-output behavior:

- Default pytest runs avoid per-test dot/progress floods.
- Success-path print noise is removed from normal test modules.
- Compact mode remains enforced even with `-o addopts=''` unless explicit verbose opt-out is requested.
- `pytest -v/-vv` is clamped back to compact mode unless opt-out is enabled.
- Failure hints are emitted once at run end (not per failure) by `pytest_terminal_summary(...)`/`pytest_sessionfinish(...)`.

Verbose opt-out contract:

- Set `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` to restore full verbose output behavior for deep debugging.

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
- 2026-02-22: compact-output enforcement on `addopts` override landed and remains opt-out via `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.

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
