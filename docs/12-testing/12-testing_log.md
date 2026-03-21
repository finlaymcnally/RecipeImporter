---
summary: "Testing architecture/build/fix-attempt log for suite structure and low-noise pytest behavior."
read_when:
  - When test-suite organization or pytest output behavior starts going in circles
  - When compact pytest output contracts, marker grouping, or path helpers are being changed
---

# Testing Log

Read `docs/12-testing/12-testing_README.md` first for current behavior.
This log keeps only the durable verification and decisions that still match the code.

## Current Verification Snapshot (2026-03-15)

Repository checks rerun against current code:

- `./scripts/test-suite.sh smoke`
  - `127 passed, 1223 deselected, 1 warning in 7.08s`
- `./.venv/bin/pytest tests/core/test_pytest_output_guidance.py`
  - `2 passed in 0.02s`
- Marker-map inspection via `tests/conftest.py`
  - `139` `test_*.py` files exist under `tests/`
  - `135` basenames are explicitly mapped in `_FILE_MARKERS`
  - Fallback-to-`core` currently applies to:
    - `test_benchmark_oracle_upload.py`
    - `test_cf_debug_cli.py`
    - `test_codex_decision_boundary.py`
    - `test_upload_bundle_v1_existing_output.py`
  - `_SLOW_FILES` contains `15` files
  - `_SMOKE_FILES` contains `21` files

Current contract confirmation:

- Marker assignment and slow/smoke slices are still centralized in `tests/conftest.py`.
- Compact output is still enforced from `pytest_configure(...)` even when callers override `addopts`.
- `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is now intentionally narrow: one explicit file or nodeid only.
- Broad raw pytest runs are nudged toward `./scripts/test-suite.sh` or `make test-*`.
- Domain folders remain the primary layout, with one intentional root-level cross-domain module: `tests/test_eval_freeform_practical_metrics.py`.
- Support data surfaces under `tests/fixtures/*`, `tests/tagging_gold/*`, and `tests/paths.py` remain active.

### 2026-03-20 split LLM runtime tests by seam and tighten assertions

Still-active outcomes:

- direct Codex exec workspace/runtime coverage now lives in `tests/llm/test_codex_exec_runner_workspace.py`, while pure helper/classifier coverage stays in `tests/llm/test_codex_exec_runner.py`
- knowledge worker-runtime/progress coverage now lives in `tests/llm/test_codex_farm_knowledge_orchestrator_runtime.py`, while the large base orchestrator file keeps broader behavior/integration coverage
- centralized marker routing in `tests/conftest.py` knows about both new files, so `-m llm` treats them as LLM tests instead of silently falling back to `core`
- moved runtime tests now assert the exact contracts they name: sterile execution cwd, worker-manifest entry files, synced workspace outputs, packet totals, packet-lease finalization, and worker/session telemetry shapes
- runtime tests that create sterile workspaces must patch the direct-exec home resolver to `tmp_path` rather than inheriting the host machine's `~/.codex-recipe` tree

Anti-loop note:

- if a “focused” runtime test still needs one of the large base files to import unrelated helpers or machine-local Codex-home state, the split probably happened by file length instead of by seam

## Durable Decisions Still In Effect

### 2026-02-22 low-noise pytest + domain layout

Still-active outcomes:

- Domain folders under `tests/` are the default layout.
- `tests/paths.py` remains the shared path-stability helper.
- Compact pytest output is enforced from config and hooks, not just from `pytest.ini`.
- Failure hints point to the matching `docs/*_log.md` file instead of printing more noise during the run.

Anti-loop note:

- If path-sensitive tests break after moving files, check `tests/paths.py` usage before changing test logic.

### 2026-03-04 split high-cost mixed modules by seam

Still-active outcomes:

- CLI output structure remains split into fast/default, fast/EPUB-mocked, fast/text, and slow/EPUB-heavy files.
- Dashboard browser overflow coverage remains isolated in `tests/analytics/test_stats_dashboard_slow.py`.
- Label Studio benchmark coverage remains split by seam instead of returning to one mega-module.
- Codex orchestrator, prelabel, step-linking, and bench CLI coverage remain split into focused modules.
- Shared helper state for the benchmark-helper cluster belongs in `tests/labelstudio/benchmark_helper_support.py`, not a new giant support file.

Anti-loop note:

- If targeted runs get broad or slow again, inspect module boundaries before changing marker policy.

### 2026-03-05 default-surface assertions should test contracts, not drifting policy

Still-active outcomes:

- Broad `RunSettings` tests should assert serialization/sync behavior, not freeze every current default.
- Command-specific tests may still assert narrower defaults when the command contract really is narrower.
- Interactive preset tests should compare against preset builders/harmonizers rather than copied literal settings blobs.

Anti-loop note:

- When a default changes, first ask whether the broken test was checking contract or product policy.

### 2026-03-06 wrapper-first routine runs

Still-active outcomes:

- Routine loops should prefer `./scripts/test-suite.sh` or `make test-*`.
- `COOKIMPORT_TEST_SUITE=1` is the signal that the wrapper path is being used.
- Broad raw pytest warnings are intentional; narrow one-file reruns are still a supported quiet path.

Anti-loop note:

- If raw-pytest guidance starts firing in the wrong places, fix the gate in `tests/conftest.py` instead of adding more doc-only warnings.

### 2026-03-14 single-book benchmark smoke boundary

Still-active outcomes:

- Single-offline benchmark regressions should be guarded both by narrow helper tests and by an interactive smoke test.
- `tests/labelstudio/test_labelstudio_benchmark_smoke.py` is intentionally offline: it runs the real interactive path but stubs `labelstudio_benchmark(...)`.
- Smoke coverage should include menu routing, run-settings handoff, variant planning, and artifact sanity without requiring live CodexFarm or Label Studio credentials.

Anti-loop note:

- If the smoke path needs live credentials to catch a regression, the smoke boundary has become too wide.

### 2026-03-15 scoped verbose-output guardrail

Still-active outcomes:

- Broad runs, marker runs, and directory runs stay compact even when `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is set.
- Full verbose output is reserved for a single explicit file or nodeid after a compact scoped rerun.
- `tests/core/test_pytest_output_guidance.py` is the regression check for this behavior.

Anti-loop note:

- If someone says the env var "stopped working," verify whether they tried to use it on a broad run. That behavior is intentional.

### 2026-03-15 measured fast-slice cleanup hotspots

Still-active outcomes:

- broad non-slow runtimes were dominated by a small set of integration-heavy files rather than by domain count alone
- broad compact pytest runs were not useful enough for hotspot timing because the compact reporter suppressed most `--durations` output; one-file invocations were the reliable measurement path
- measured hotspot files before reclassification were:
  - `tests/analytics/test_stats_dashboard.py` about `45s`
  - `tests/ingestion/test_performance_features.py` about `15s`
  - `tests/cli/test_cli_output_structure_epub_fast.py` about `11s`
  - `tests/cli/test_cli_output_structure_text_fast.py` about `11s`
  - `tests/parsing/test_canonical_line_roles.py` about `24s`
- after moving those files into `_SLOW_FILES`, routine non-slow domain times dropped to about:
  - analytics `7s`
  - ingestion `10s`
  - cli `8s`
  - parsing `3s`
- broad non-slow pytest finished in about `70.34s` after the cleanup, with unrelated existing failures still present
- the heavy coverage stayed available in the explicit slow slice instead of being deleted or mocked away broadly

Anti-loop note:

- do not re-open slow-slice arguments from filenames alone; rerun timing first

### 2026-03-15 Label Studio fast-slice hotspot split

Still-active outcomes:

- `./scripts/test-suite.sh domain labelstudio` is one single-process pytest invocation, so extra cores do not help unless the test strategy changes
- pre-cleanup measurements showed:
  - full non-slow `tests/labelstudio`: about `227.82s`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py`: about `121s`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_run.py`: about `79s`
  - progress/import-eval/artifact helper files were single-digit seconds
- the heavy cost came from routing tests still reaching the real `_interactive_single_book_benchmark(...)` helper and paying for comparison, bundle, and dashboard work
- the durable split is:
  - keep full single-book helper coverage in the slow slice
  - keep routing-only interactive tests at the helper boundary with stubs

Anti-loop note:

- if the `labelstudio` domain gets slow again, inspect whether routing tests stopped stubbing the single-book helper before changing global pytest policy

### 2026-03-16 fast Codex-helper regression anchors and synthetic benchmark fixtures

Still-active outcomes:

- live Codex env/helper seams need one direct non-slow regression test even when broader slow-path coverage already exists
- `tests/parsing/test_canonical_line_role_env.py` is the example to copy for tiny live-path helpers: catch import/env breakage in the fast suite before a benchmark run hits it
- `tests/bench/test_benchmark_oracle_upload.py` should synthesize a minimal `upload_bundle_v1` under `tmp_path` instead of relying on one repo-local benchmark root

Anti-loop note:

- if a test only needs a resolvable artifact contract, build the smallest valid fixture locally instead of depending on historical checked-in run directories

### 2026-03-17 line-role shard-shape test guardrail

Still-active outcomes:

- `RunSettings.line_role_prompt_target_count` now defaults to `5`, so small line-role workloads can be regrouped into one shard even when `codex_batch_size=1`
- tests that care about exact shard ids, worker assignments, or proposal filenames must explicitly opt out of that default by setting `line_role_prompt_target_count=None` or a concrete `line_role_shard_target_lines`

Anti-loop note:

- if a per-line shard test suddenly starts seeing grouped shards, inspect prompt-target defaults before debugging the planner

### 2026-03-18 pack/schema regressions had to guard current LLM transport truth, not legacy prompt markers

Still-active outcomes:

- `tests/llm/test_llm_pipeline_pack_assets.py` now needs recursive nested-schema coverage because the live knowledge schema broke on a missing nested `required` key (`rc`) that top-level checks would not catch
- `tests/llm/test_llm_pipeline_pack.py` must assert transport expectations per pipeline:
  - recipe is inline now
  - file-backed `{{INPUT_PATH}}` markers are not a universal pack contract anymore

Anti-loop note:

- if one pack test starts failing after a transport change, first ask whether the test froze a legacy cross-pipeline assumption before "fixing" the runtime back toward the old contract
