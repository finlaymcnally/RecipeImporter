---
summary: "Testing architecture/build/fix-attempt log for suite structure and low-noise pytest behavior."
read_when:
  - When test-suite organization or pytest output behavior starts going in circles
  - When compact pytest output contracts, marker grouping, or path helpers are being changed
---

# Testing Log

Read `docs/12-testing/12-testing_README.md` first for current behavior.
This log keeps only the durable verification and decisions that still match the code.

## Current Verification Snapshot (2026-03-30)

Repository inspection against current code:

- `166` `test_*.py` files exist under `tests/`.
- Physical test folders are now `architecture`, `analytics`, `bench`, `cli`, `core`, `ingestion`, `labelstudio`, `llm`, `parsing`, and `staging`, plus the intentional root-level cross-domain file `tests/test_eval_freeform_practical_metrics.py`.
- `pytest.ini` still declares the current marker surface: `analytics`, `bench`, `cli`, `core`, `heavy_side_effects`, `ingestion`, `labelstudio`, `llm`, `parsing`, `staging`, `slow`, and `smoke`.
- `tests/conftest.py` still centralizes `_FILE_MARKERS`, `_SLOW_FILES`, `_SMOKE_FILES`, compact output enforcement, wrapper guidance, heavy-side-effect gating, and the suite-level temp `CODEX_HOME` fixture.
- `_FILE_MARKERS` has `149` entries, `144` of which currently match live test files.
- Fallback-to-`core` still covers several live focused suites, including:
  - the `tests/architecture/` boundary tests,
  - focused bench/CLI helpers such as `test_benchmark_oracle_upload.py`, `test_cf_debug_cli.py`, `test_codex_decision_boundary.py`, `test_oracle_followup.py`, and `test_upload_bundle_v1_existing_output.py`,
  - focused LLM and staging/runtime suites such as `test_codex_exec_runner.py`, `test_prompt_preview.py`, `test_phase_worker_runtime.py`, `test_recipe_phase_workers.py`, `test_nonrecipe_stage.py`, and `test_stage_observability.py`.
- `_SLOW_FILES` currently covers `20` live files.
- `_SMOKE_FILES` currently covers `23` live files.

Current contract confirmation:

- Marker assignment and slow/smoke slices are still centralized in `tests/conftest.py`.
- Compact output is still enforced from `pytest_configure(...)` even when callers override `addopts`.
- `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is now intentionally narrow: one explicit file or nodeid only.
- Broad raw pytest runs are nudged toward `./scripts/test-suite.sh` or `make test-*`.
- Domain folders remain the primary layout, with one intentional root-level cross-domain module and one real-but-unmarked `tests/architecture/` folder.
- Support data surfaces under `tests/fixtures/*` and `tests/paths.py` remain active.
- Some marker entries in `tests/conftest.py` still point at removed or renamed files, so docs should treat that file as the authority but not assume it is perfectly synchronized with the tree.

### Runtime suites should split by seam, not by raw file length

Still-active outcomes:

- the highest-value refactors were long single tests that combined broad synthetic setup, one command/helper call, and several unrelated assertion families in the same function
- the durable cleanup style is:
  - local fixture builders
  - local helper extraction
  - narrow assertion groups with one dominant reason to fail
- shared support should stay small and domain-local when possible, for example `tests/labelstudio/benchmark_helper_support.py`; do not turn this into a repo-wide mega-fixture framework
- rerunning the full touched domain after each split is part of the contract now, because these refactors kept flushing out real shared bugs and stale expectations:
  - fake structured-retry snapshot/runtime bugs
  - generated helper-template drift
  - stale worker/runtime expectations after runtime contract changes
- once the biggest monoliths are split, the hotspot frontier moves quickly; use fresh measurements instead of assuming yesterday's largest file is still the best target

Anti-loop note:

- if a test is miserable to read or extend because it proves bundle creation, transport/runtime behavior, and five output surfaces at once, split the test by contract before adding more assertions

### Split runtime coverage should keep direct live-path guards fast

Still-active outcomes:

- direct Codex exec workspace/runtime coverage now lives in `tests/llm/test_codex_exec_runner_workspace.py`, while pure helper/classifier coverage stays in `tests/llm/test_codex_exec_runner.py`
- knowledge-stage runtime coverage is now intentionally spread across `tests/llm/test_knowledge_orchestrator_runtime_progress.py`, `tests/llm/test_knowledge_orchestrator_runtime_leasing.py`, `tests/llm/test_knowledge_runtime_replay.py`, and `tests/llm/test_knowledge_stage_bindings.py`
- centralized marker routing is still the intended owner for those splits, even though the marker map now lags some newer files
- moved runtime tests now assert the exact contracts they name: sterile execution cwd, worker-manifest entry files, synced workspace outputs, packet totals, packet-lease finalization, and worker/session telemetry shapes
- runtime tests that create sterile workspaces must stay on temp Codex homes rather than inheriting the host machine's real profile

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

### High-cost suites stay isolated by seam

Still-active outcomes:

- CLI output structure remains split into fast/default, fast/EPUB-mocked, fast/text, and slow/EPUB-heavy files.
- Dashboard browser overflow coverage remains isolated in `tests/analytics/test_stats_dashboard_slow.py`.
- Label Studio benchmark coverage remains split by seam instead of returning to one mega-module.
- Codex orchestrator, prelabel, step-linking, and bench CLI coverage remain split into focused modules.
- Shared helper state for the benchmark-helper cluster belongs in `tests/labelstudio/benchmark_helper_support.py`, not a new giant support file.

Anti-loop note:

- If targeted runs get broad or slow again, inspect module boundaries before changing marker policy.

### Default-surface assertions should test contracts, not drifting policy

Still-active outcomes:

- Broad `RunSettings` tests should assert serialization/sync behavior, not freeze every current default.
- Command-specific tests may still assert narrower defaults when the command contract really is narrower.
- Interactive preset tests should compare against preset builders/harmonizers rather than copied literal settings blobs.

Anti-loop note:

- When a default changes, first ask whether the broken test was checking contract or product policy.

### Wrapper-first routine runs remain the default

Still-active outcomes:

- Routine loops should prefer `./scripts/test-suite.sh` or `make test-*`.
- `COOKIMPORT_TEST_SUITE=1` is the signal that the wrapper path is being used.
- Broad raw pytest warnings are intentional; narrow one-file reruns are still a supported quiet path.

Anti-loop note:

- If raw-pytest guidance starts firing in the wrong places, fix the gate in `tests/conftest.py` instead of adding more doc-only warnings.

### Single-book benchmark smoke keeps two layers

Still-active outcomes:

- Single-offline benchmark regressions should be guarded both by narrow helper tests and by an interactive smoke test.
- `tests/labelstudio/test_labelstudio_benchmark_smoke.py` is intentionally offline: it runs the real interactive path but stubs `labelstudio_benchmark(...)`.
- Smoke coverage should include menu routing, run-settings handoff, variant planning, and artifact sanity without requiring live CodexFarm or Label Studio credentials.

Anti-loop note:

- If the smoke path needs live credentials to catch a regression, the smoke boundary has become too wide.

### Scoped verbose-output guardrail remains narrow

Still-active outcomes:

- Broad runs, marker runs, and directory runs stay compact even when `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is set.
- Full verbose output is reserved for a single explicit file or nodeid after a compact scoped rerun.
- `tests/core/test_pytest_output_guidance.py` is the regression check for this behavior.

Anti-loop note:

- If someone says the env var "stopped working," verify whether they tried to use it on a broad run. That behavior is intentional.

### Slow-slice decisions should be measurement-led, not filename-led

Still-active outcomes:

- broad non-slow runtimes are dominated by a small set of integration-heavy files rather than by domain count alone
- compact broad pytest runs are poor hotspot profilers because the compact reporter suppresses most useful `--durations` detail
- one-file invocations are the reliable measurement path when deciding whether a file belongs in `_SLOW_FILES`
- the heavy coverage stayed available in the explicit slow slice instead of being deleted or mocked away broadly

Anti-loop note:

- do not re-open slow-slice arguments from filenames alone; rerun timing first

### Label Studio routing tests must stop at the helper boundary

Still-active outcomes:

- `./scripts/test-suite.sh domain labelstudio` is one single-process pytest invocation, so extra cores do not help unless the test strategy changes
- the heavy cost came from routing tests still reaching the real `_interactive_single_book_benchmark(...)` helper and paying for comparison, bundle, and dashboard work
- the durable split is:
  - keep full single-book helper coverage in the slow slice
  - keep routing-only interactive tests at the helper boundary with stubs

Anti-loop note:

- if the `labelstudio` domain gets slow again, inspect whether routing tests stopped stubbing the single-book helper before changing global pytest policy

### Fast Codex-helper anchors and synthetic benchmark fixtures remain required

Still-active outcomes:

- live Codex env/helper seams need one direct non-slow regression test even when broader slow-path coverage already exists
- `tests/parsing/test_canonical_line_role_env.py` is the example to copy for tiny live-path helpers: catch import/env breakage in the fast suite before a benchmark run hits it
- `tests/bench/test_benchmark_oracle_upload.py` should synthesize a minimal `upload_bundle_v1` under `tmp_path` instead of relying on one repo-local benchmark root

Anti-loop note:

- if a test only needs a resolvable artifact contract, build the smallest valid fixture locally instead of depending on historical checked-in run directories

### Line-role shard-shape assertions still need explicit opt-out

Still-active outcomes:

- `RunSettings.line_role_prompt_target_count` now defaults to `5`, so small line-role workloads can be regrouped into one shard even when `codex_batch_size=1`
- tests that care about exact shard ids, worker assignments, or proposal filenames must explicitly opt out of that default by setting `line_role_prompt_target_count=None` or a concrete `line_role_shard_target_lines`

Anti-loop note:

- if a per-line shard test suddenly starts seeing grouped shards, inspect prompt-target defaults before debugging the planner

### Pack/schema tests must guard current transport truth

Still-active outcomes:

- `tests/llm/test_llm_pipeline_pack_assets.py` now needs recursive nested-schema coverage because the live knowledge schema broke on a missing nested `required` key (`rc`) that top-level checks would not catch
- `tests/llm/test_llm_pipeline_pack.py` must assert transport expectations per pipeline:
  - recipe is inline now
  - file-backed `{{INPUT_PATH}}` markers are not a universal pack contract anymore

Anti-loop note:

- if one pack test starts failing after a transport change, first ask whether the test froze a legacy cross-pipeline assumption before "fixing" the runtime back toward the old contract
