---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Use this file for LLM debugging history that still applies to the current codebase.

## 2026-03-06_00.30.31 codex-farm recoverable warning routing during shared progress

Problem captured:
- Recoverable codex-farm partial-output failures were logged as terminal warnings even when the caller was using a shared progress callback/dashboard, so benchmark PTYs filled with multiline auth/retry noise.

Durable decisions/actions:
- `SubprocessCodexFarmRunner` now keeps detailed recoverable-failure diagnostics in debug logs/artifacts, but emits only one short progress callback message during callback-driven runs.
- Non-callback runs still log the warning normally so direct CLI/manual runs keep visible diagnostics.

## 2026-03-03_23.50.00 codex-farm no-last-agent-message partial-output recovery

Problem captured:
- Codex-farm sometimes exits non-zero with `Warning: no last agent message; wrote empty content ...`, which was aborting entire pass execution even when only a small subset of chunks failed.

Durable decisions/actions:
- `SubprocessCodexFarmRunner` now treats that specific signature as recoverable when failure categories are limited to `nonzero_exit_no_payload`.
- Runner logs a warning and returns process metadata so orchestrators can continue and handle missing per-bundle outputs via existing fallback/error paths.
- Other codex-farm failures still raise `CodexFarmRunnerError` unchanged.

## 2026-02-28_10.35.22 codex-farm autotune payload ingest

Source files:
- `docs/tasks/2026-02-28_10.35.22-codex-farm-autotune-payload-ingest.md`
- `docs/understandings/2026-02-28_10.35.22-codex-farm-run-autotune-consumption-boundary.md`

Problem captured:
- CodexFarm added `run autotune --json` with caller-ready flag overrides and unified diffs, but recipeimport did not consume or persist this output in pass metadata.

Durable decisions/actions:
- `SubprocessCodexFarmRunner` now does a best-effort `run autotune --run-id <id> --json` follow-up after successful `process` calls and stores the payload under `autotune_report`.
- `process_runs` / `process_run` serialization now includes `autotune_report` alongside `telemetry_report` and compact CSV `telemetry` slices.
- Autotune fetch is non-fatal: command missing/unsupported or parse failures are ignored and `autotune_report` remains `null`.

Evidence captured:
- `tests/llm/test_codex_farm_orchestrator.py`: `13 passed`
- `tests/llm/test_codex_farm_knowledge_orchestrator.py`: `1 passed`
- `tests/tagging/test_tagging.py -k "llm or codex or pass5 or tags"`: `4 passed, 19 deselected`

Anti-loop note:
- If `autotune_report` is unexpectedly null, verify CodexFarm binary version first (`run autotune` command availability) before changing runner serialization.

## 2026-02-28_10.28.23 codex-farm telemetry-report v2 alignment

Source files:
- `docs/tasks/2026-02-28_10.28.23-codex-farm-telemetry-v2-alignment.md`
- `docs/understandings/2026-02-28_10.28.23-codex-farm-telemetry-report-v2-alignment.md`

Problem captured:
- CodexFarm upgraded caller telemetry contract to `process --json.telemetry_report` schema v2 (`insights`, `tuning_playbook`), but recipeimport only exposed compact CSV telemetry slices as first-class fields.

Durable decisions/actions:
- `CodexFarmPipelineRunResult` now carries `telemetry_report` as a top-level field extracted from `process --json` payload.
- Serialized pass metadata (`process_runs` / `process_run`) now includes `telemetry_report` directly, without requiring callers to parse nested `process_payload`.
- Existing CSV telemetry slices remain under `telemetry` as non-fatal row-level fallback/context.

Evidence captured:
- `tests/llm/test_codex_farm_orchestrator.py`: `13 passed`
- `tests/llm/test_codex_farm_knowledge_orchestrator.py`: `1 passed`
- `tests/tagging/test_tagging.py -k "llm or codex or pass5 or tags"`: `4 passed, 19 deselected`

Anti-loop note:
- If telemetry v2 fields appear missing, first verify CodexFarm invocation is not forcing `--no-telemetry-report` before changing recipeimport runner parsing.

## 2026-02-28_10.15.00 codex-farm telemetry contract ingest

Merged source file:
- Former `docs/tasks/2026-02-28_10.15.00-codex-farm-telemetry-contract-ingest.md` (removed after merge).

Problem captured:
- `process --json` metadata was too thin for prompt-tuning loops; recipeimport needed to ingest Codex Farm `codex_exec_activity` telemetry (retry context, Heads Up usage, failures, output/event summaries) while keeping run artifacts bounded.

Durable decisions/actions:
- `SubprocessCodexFarmRunner` now returns structured process metadata plus best-effort telemetry slices keyed by `run_id` + `pipeline_id`.
- Recipe pass artifacts persist telemetry under `process_runs.pass1|pass2|pass3`; pass4/pass5 persist under `process_run`.
- Telemetry rows are compacted (bounded slices + summary counters) instead of embedding full raw CSV rows, because source rows can carry large prompt/output text fields.
- Telemetry ingestion is non-fatal: unreadable/missing CSV data is recorded as warnings and does not fail conversion.
- CSV discovery follows codex-farm process semantics (`--data-dir` when present, otherwise `<cwd>/var`).

Evidence captured:
- `tests/llm/test_codex_farm_orchestrator.py`: `13 passed`
- `tests/llm/test_codex_farm_knowledge_orchestrator.py`: `1 passed`
- `tests/tagging/test_tagging.py -k "llm or codex or pass5 or tags"`: `4 passed`

Anti-loop note:
- If telemetry fields are missing, verify run-id and pipeline-id join inputs first (`process --json` payload + resolved pipeline id) before modifying report writers.

## 2026-02-28_09.49.32 codex-farm caller output-schema enforcement

Merged source file:
- Former `docs/tasks/2026-02-28_09.49.32-codex-farm-output-schema-enforcement.md` (removed after merge).

Problem captured:
- Caller subprocess runs were not explicitly passing `--output-schema`, so schema-gate behavior depended entirely on pack defaults and offered weaker guardrails for external caller contract drift.

Durable decisions/actions:
- `SubprocessCodexFarmRunner.run_pipeline(...)` now resolves the pipeline definition under `<pack>/pipelines/**.json`, reads `output_schema_path`, and passes it to `codex-farm process --output-schema ... --json`.
- Resolution is strict:
  - missing pipeline definition for the requested `pipeline_id` => fail-fast;
  - duplicate pipeline definitions for the same `pipeline_id` => fail-fast;
  - missing `output_schema_path` or missing schema file => fail-fast.
- Resolution behavior is cached per `(root_dir, pipeline_id)` for repeated pass calls in a run.
- When `process --json` yields payload JSON, runner now requires `output_schema_path` and verifies it matches the expected override path.
- Recipe pass manifests/reports now expose `output_schema_paths`; pass4/pass5 reports expose `output_schema_path`.

Evidence captured:
- `tests/llm/test_codex_farm_orchestrator.py`:
  - `test_subprocess_runner_passes_root_and_workspace_flags`
  - `test_subprocess_runner_fails_before_process_when_output_schema_missing`
  - plus existing codex-runner coverage in the same file

Anti-loop note:
- If codex subprocess outputs look shape-invalid despite pack schemas, inspect `cookimport/llm/codex_farm_runner.py:_resolve_pipeline_output_schema_path(...)` and captured command args before touching prompts/contracts.

## 2026-02-28_09.26.29 codex-farm connection contract alignment

Merged source file:
- Former `docs/tasks/2026-02-28_09.26.29-codex-farm-connection-contract-alignment.md` (removed after merge).

Problem captured:
- Caller-side Codex Farm integration drifted from `shared/CodexFarm/CONNECTION_INSTRUCTIONS.md` for model discovery, pipeline discovery, and failure diagnostics.

Durable decisions/actions:
- Interactive run-settings Codex model picker now reads discovered models via `codex-farm models list --json` (best-effort fallback when unavailable).
- Recipe/pass4/pass5 subprocess paths now prevalidate configured pipeline ids using `codex-farm pipelines list --root <pack> --json` when using subprocess runner.
- Subprocess runner now parses `process --json` output and, on failure with `run_id`, fetches first-error context from `codex-farm run errors --run-id <run_id> --json`.
- Pipeline prevalidation is strict for subprocess-backed execution only; injected fake/test runners remain unblocked.
- Failure diagnostics enforce parseable `process --json`, but successful non-JSON/empty stdout remains tolerated for test-double compatibility.

Evidence captured:
- `tests/llm/test_codex_farm_orchestrator.py`
- `tests/llm/test_codex_farm_knowledge_orchestrator.py`
- `tests/tagging/test_tagging.py` (`llm/codex/pass5` subset)
- `tests/cli/test_c3imp_interactive_menu.py` (codex model/reasoning chooser subset)

Anti-loop note:
- If model picker options and runtime pipeline failures disagree with Codex Farm CLI output, inspect `cookimport/llm/codex_farm_runner.py` helpers first before changing prompt/config surfaces.

## 2026-02-28_04.05.00 codex-farm always-on interactive defaults and ungated normalizers

Source task file:
- `docs/tasks/2026-02-28_04.05.00-codex-farm-always-on-in-interactive-and-normalizers.md`

Problem captured:
- Interactive and normalization behavior still had codex-gate drift and codex-off defaults that no longer matched desired workflow.

Durable decisions/actions:
- Removed recipe codex-farm env gating from:
  - `RunSettings.from_dict(...)`
  - `cookimport/cli.py:_normalize_llm_recipe_pipeline(...)`
  - `cookimport/labelstudio/ingest.py:_normalize_llm_recipe_pipeline(...)`
- Interactive defaults now prefer codex-enabled execution:
  - `Use Codex Farm recipe pipeline for this run?` defaults to `Yes`.
  - `Include Codex Farm permutations?` defaults to `Yes`.
- `run_settings_ui_specs()` always exposes `llm_recipe_pipeline=off|codex-farm-3pass-v1`.
- `COOKIMPORT_ALLOW_CODEX_FARM` is retained as legacy compatibility surface only (no behavior gate).

Evidence captured:
- `tests/llm/test_run_settings.py`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py` (`llm_recipe_pipeline_normalizer` coverage)
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (`resolve_all_method_codex_choice` coverage)
- `tests/cli/test_cli_llm_flags.py`
- `tests/cli/test_c3imp_interactive_menu.py` (`choose_run_settings` coverage)

Anti-loop note:
- If codex appears "disabled," inspect effective run artifacts (`run_manifest`, run settings snapshot) before assuming gating logic still exists.

## 2026-02-28_03.37.51 unlock interactive llm recipe pipeline option

Source task file:
- `docs/tasks/2026-02-28_03.37.51-unlock-interactive-llm-recipe-pipeline-option.md`

Problem captured:
- Interactive `Change run settings...` could hide `llm_recipe_pipeline=codex-farm-3pass-v1` even when runtime paths accepted codex values.

Durable decisions/actions:
- `run_settings_ui_specs()` now surfaces codex-farm recipe choice directly in interactive editor choices.
- Locked/unlocked UI forks were removed so editor behavior and runtime normalization stay in parity.

Evidence captured:
- `cookimport/config/run_settings.py`
- `tests/llm/test_run_settings.py` (`run_settings_ui_specs` choice assertions)

Anti-loop note:
- If editor choices and runtime behavior diverge, treat `run_settings_ui_specs()` as canonical UI source and update tests first.

## 2026-02-28_02.48.43 setup codex-farm CLI for EPUB benchmark runs

Source task file:
- `docs/tasks/2026-02-28_02.48.43-setup-codex-farm-cli-for-epub-benchmarks.md`

Problem captured:
- Benchmark/stage codex paths were enabled in settings surfaces but could still fail immediately when external `codex-farm` binary resolution was missing.

Durable decisions/actions:
- Keep `codex_farm_cmd` configurable and prefer absolute executable paths for repeatable runs.
- Keep pipeline-pack rooting explicit when using this repo’s packs (`codex_farm_root=<repo>/llm_pipelines` plus pass1/2/3 pipeline ids).
- Treat missing binary cases as explicit fail-fast invocation errors, not silent fallback.

Anti-loop note:
- If codex passes never start, verify command path resolution (`codex_farm_cmd`) before editing prompt assets or run-settings normalization.

## 2026-02-28_02.31.09 enable codex-farm in benchmarks (historical env-gated phase)

Source task file:
- `docs/tasks/2026-02-28_02.31.09-enable-codex-farm-in-benchmarks.md`

Problem captured:
- Bench all-method runs could not include codex recipe-pipeline variants even when requested; `include_codex_farm` was threaded but no-op.

Durable decisions/actions:
- Implemented codex as a real all-method variant dimension and surfaced explicit bench flags:
  - `bench speed-run --include-codex-farm`
  - `bench quality-run --include-codex-farm`
- Kept deterministic sweep expansion opt-in (`include_deterministic_sweeps=False` baseline) to avoid accidental grid blowups.
- Historical note: this task used `COOKIMPORT_ALLOW_CODEX_FARM` as rollout gate; superseded by ungated normalization in `2026-02-28_04.05.00`.

Evidence captured:
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- `tests/cli/test_cli_llm_flags.py`

Anti-loop note:
- When codex permutations are missing from all-method grids, inspect effective `include_codex_farm` first; do not assume deterministic sweep flags imply codex inclusion.

## 2026-02-27_19.51.50 docs parity audit for runtime + nearby LLM code

Problem captured:
- `docs/10-llm/10-llm_README.md` covered core pass4/pass5 files but missed several runtime-adjacent modules that materially shape behavior (prediction-run entrypoints, pass4 helper contracts/ingest/writer, pass5 provider validation layer).

Decisions/actions captured:
- Expanded `10-llm_README.md` runtime-surface inventory to include:
  - entrypoint + prediction-run wrappers (`cookimport/entrypoint.py`, `cookimport/labelstudio/ingest.py`, `cookimport/bench/pred_run.py`)
  - pass4 helper modules (`codex_farm_knowledge_contracts/models/ingest/writer`, `non_recipe_spans`)
  - pass5 provider + standalone tagging CLI modules (`cookimport/tagging/codex_farm_tags_provider.py`, `cookimport/tagging/cli.py`)
  - stage evidence/report plumbing that consumes pass4 artifacts (`cookimport/staging/stage_block_predictions.py`, `cookimport/staging/writer.py`, `cookimport/core/models.py`)
  - shared codex-farm runner/id helper modules used by pass4/pass5
- Clarified prediction-run boundary: prediction generation wires recipe-pass settings only; pass4/pass5 remain stage-only.
- Added explicit note that speed-regression runner forces all LLM pipelines off for deterministic timing baselines.

Verification/evidence captured:
- Re-verified current docs statements against active code paths:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py`
  - `cookimport/entrypoint.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/bench/pred_run.py`
  - `cookimport/bench/speed_runner.py`
  - `cookimport/llm/codex_farm_orchestrator.py`
  - `cookimport/llm/codex_farm_contracts.py`
  - `cookimport/llm/codex_farm_ids.py`
  - `cookimport/llm/codex_farm_runner.py`
  - `cookimport/llm/codex_farm_knowledge_orchestrator.py`
  - `cookimport/llm/codex_farm_knowledge_jobs.py`
  - `cookimport/llm/codex_farm_knowledge_contracts.py`
  - `cookimport/llm/codex_farm_knowledge_models.py`
  - `cookimport/llm/codex_farm_knowledge_ingest.py`
  - `cookimport/llm/codex_farm_knowledge_writer.py`
  - `cookimport/llm/non_recipe_spans.py`
  - `cookimport/staging/stage_block_predictions.py`
  - `cookimport/staging/writer.py`
  - `cookimport/core/models.py`
  - `cookimport/tagging/cli.py`
  - `cookimport/tagging/orchestrator.py`
  - `cookimport/tagging/llm_second_pass.py`
  - `cookimport/tagging/codex_farm_tags_provider.py`

## 2026-02-27_19.45.57 docs cleanup to remove stale LLM history noise

Problem captured:
- `docs/10-llm/10-llm_README.md` and this log had large merged-task archives that duplicated old task files and hid current runtime boundaries.

Decisions/actions captured:
- Pruned retired task-merge chronology that no longer maps cleanly to active runtime behavior.
- Kept only durable, code-verified contracts still relevant for debugging today.
- Marked `cookimport/llm/client.py`, `cookimport/llm/prompts.py`, and `cookimport/llm/repair.py` as legacy/non-runtime for stage/pred-run flows.

Verification/evidence captured:
- Re-verified docs against active code paths:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/llm/codex_farm_orchestrator.py`
  - `cookimport/llm/codex_farm_knowledge_orchestrator.py`
  - `cookimport/tagging/orchestrator.py`

## 2026-02-23_11.39.45 recipe codex-farm policy lock (historical; superseded 2026-02-28_04.05.00)

Problem captured:
- Recipe codex-farm parsing correction must remain disabled until benchmark quality materially improves.

Decisions/actions captured:
- Locked recipe pipeline normalization to `off` in:
  - `cookimport/cli.py:_normalize_llm_recipe_pipeline`
  - `cookimport/labelstudio/ingest.py:_normalize_llm_recipe_pipeline`
- Updated `RunSettings.from_dict` to coerce legacy non-`off` persisted values back to `off` with warning text.
- Run-settings UI contract remains `off`-only for recipe pipeline selection.

Verification/evidence preserved:
- `pytest tests/cli/test_cli_llm_flags.py tests/llm/test_run_settings.py tests/labelstudio/test_labelstudio_ingest_parallel.py::test_llm_recipe_pipeline_normalizer_rejects_codex_farm_enablement`

Rollback path preserved:
- If policy changes, update both normalizers plus run-settings enum/UI filtering in one change.

## 2026-02-25_16.21.30 pass4 table-hint parity across stage/split/processed outputs

Problem captured:
- Pass4 table hints can disappear when non-split, split-merge, and processed-output paths diverge.

Decisions/actions preserved:
- Keep table annotation before chunking in all key paths:
  - `cookimport/cli_worker.py:stage_one_file`
  - `cookimport/cli.py:_merge_split_jobs`
  - `cookimport/labelstudio/ingest.py:_write_processed_outputs`
- Keep pass4 hint mapping by absolute non-recipe indices in `cookimport/llm/codex_farm_knowledge_jobs.py`.

Anti-loop note:
- Debug stage/merge parity first when hints are missing; do not start by changing pass4 prompt/schema assets.

## 2026-02-25_16.24.24 pass5 stage-tagging outputs and failure mode

Problem captured:
- Missing `tags/` artifacts were often misdiagnosed as tagging quality issues instead of wiring/gating failures.

Decisions/actions preserved:
- Pass5 runs after stage writes final drafts and reads from `final drafts/<workbook_slug>/`.
- Output contract:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/tags_index.json`
- Raw codex-farm IO stays under `raw/llm/<workbook_slug>/pass5_tags/`.
- `codex_farm_failure_mode` controls hard-stop (`fail`) vs warn-and-continue (`fallback`).

## 2026-02-25_19.20.00 deterministic knowledge fallback when pass4 is off

Problem captured:
- Stage evidence previously risked `KNOWLEDGE=0` when pass4 was disabled, despite deterministic knowledge-lane chunks.

Decisions/actions preserved:
- Prefer pass4 snippet provenance when available.
- When pass4 is off or missing snippets, backfill stage knowledge labels from deterministic `ChunkLane.KNOWLEDGE` chunk-to-block mapping.

Anti-loop note:
- If `KNOWLEDGE=0` appears with pass4 disabled, treat it as a wiring regression.

## 2026-02-27_19.45.57 docs runtime-scope cleanup

Problem captured:
- LLM docs had large archive sections that implied broader active runtime use than current code executes.

Durable decisions/actions:
- Keep docs focused on active stage pass4/pass5 behavior and current recipe pipeline enablement boundaries.
- Keep recipe pass implementation files documented as shipped code, but clearly label runtime lock state.
- Keep prediction-run boundary explicit (recipe-pass settings only).

Anti-loop note:
- If LLM behavior appears inconsistent, verify effective run-settings normalization path first (`run_settings` + CLI + Label Studio ingest) before editing pass assets.

## 2026-02-27_19.51.50 provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.51.50-llm-docs-parity-runtime-surface-map.md`

Current status:
- Its module-parity findings are retained in this log and reflected in `10-llm_README.md`.

## 2026-02-28 migrated understandings batch (LLM ops and external model tooling)

### 2026-02-28_03.17.29 Codex Farm opt-in command pattern

Source: `docs/understandings/2026-02-28_03.17.29-codex-farm-opt-in-command-pattern.md`

Problem captured:
- Need command-level Codex Farm access without changing deterministic default runtime policy.

Durable pattern preserved:
- Keep `llm_recipe_pipeline` default `off` globally.
- Enable Codex Farm only via explicit command/profile selection.
- Prefer absolute `codex_farm_cmd` in run settings/overrides to avoid PATH-dependent failures.

### 2026-02-28_03.19.48 interactive Codex Farm gate and launcher

Source: `docs/understandings/2026-02-28_03.19.48-interactive-codex-farm-gate-and-launcher.md`

Findings preserved:
- Interactive `cookimport` already routes through run-settings `llm_recipe_pipeline` selection; no special separate interactive-only Codex Farm code path is required.
- Historical note: this finding predated ungated recipe normalization and is now superseded by the 2026-02-28_04.05.00 change.

Durable pattern:
- Use a dedicated launcher (`scripts/interactive-with-codex-farm.sh`) for opt-in sessions so default interactive behavior stays unchanged/off.

## 2026-02-28 migrated understanding ledger (03:47-04:01 LLM batch)

### 2026-02-28_03.47.42 codex-farm prompt tightening priorities

Problem captured:
- Prompt set produced valid outputs but lacked deterministic tie-break and schema-safety specificity, increasing variance risk.

Durable priorities preserved:
- Highest leverage prompt hardening order: pass2, pass3, then pass1; pass4/pass5 lower leverage.
- Cross-pass wording upgrades should emphasize:
  - omit unknown fields instead of guessing,
  - explicit evidence requirements,
  - stable ordering constraints,
  - no extra keys/type drift beyond schema contract.

Anti-loop note:
- For output variance, tighten prompt contract language before changing model/provider wiring.

### 2026-02-28_04.01.52 codex toggle versus effective run setting

Source: `docs/understandings/2026-02-28_04.01.52-codex-toggle-vs-effective-run-setting.md`

Problem captured:
- User-observed codex toggle in menu did not match persisted benchmark artifacts for run `2026-02-28_03.54.15`.

Findings preserved:
- Artifacts and benchmark settings snapshot for that run recorded `llm_recipe_pipeline=off` and `llm_codex_farm.enabled=false`.
- `run_settings.py` and `run_settings_flow.py` changed shortly after the run (`2026-02-28 04:00:04` and `2026-02-28 04:00:51` local timestamp), so source-at-head and run-time behavior can diverge.
- Practical debugging rule: use run-time artifacts/manifests as source-of-truth for what executed.

Anti-loop note:
- Do not infer historical run behavior only from current branch files when run-time normalization logic was edited immediately after the run.

## 2026-02-28 migrated understanding ledger (04:05-09:17 Codex gate alignment + connection contract)

### 2026-02-28_04.05.20 codex-farm gate surface map

Source: `docs/understandings/2026-02-28_04.05.20-codex-farm-gate-surface-map.md`

Verification captured:
- Post-change verification confirmed codex visibility/effectiveness can diverge when one gate surface is edited in isolation.
- Critical surfaces:
  - `RunSettings.from_dict(...)`
  - `run_settings_ui_specs()`
  - `cli._normalize_llm_recipe_pipeline(...)`
  - `cli._resolve_all_method_codex_choice(...)`
- Prompt defaults (`Use Codex Farm...`, `Include Codex Farm permutations?`) are separate from normalization logic and must be reviewed independently.

Durable implication:
- Any future codex policy flip must update all four surfaces in one change set to avoid "prompt says on, effective run says off" regressions.

### 2026-02-28_04.11.09 docs-task merge codex gating drift

Source: `docs/understandings/2026-02-28_04.11.09-docs-task-merge-codex-gating-drift.md`

Problem captured:
- Consolidated docs carried mixed claims (historical env gate vs current ungated runtime), creating debugging ambiguity.

Durable decisions:
- README text remains current-state source-of-truth (ungated runtime).
- Env-gated behavior stays `_log`-only as explicitly historical context.
- Keep `COOKIMPORT_ALLOW_CODEX_FARM` documented as legacy no-op compatibility surface.

Anti-loop note:
- When docs disagree on codex gating, trust current normalizer code and persisted run artifacts before resurrecting gate logic.

### 2026-02-28_09.17.26 codex-farm connection contract check

Source: `docs/understandings/2026-02-28_09.17.26-codex-farm-connection-contract-check.md`

Scope captured:
- Runner command contract validated for `process --json` execution and optional model/reasoning/root/workspace flags.

Findings preserved:
- Model list sourcing currently depends on local cache helper, not CLI JSON listing command.
- Pipeline IDs remain static run-setting fields; there is no runtime `pipelines list --json` consumption path.
- Error path surfaces `CodexFarmRunnerError` without `run_id` follow-up diagnostics.
- Local health checks against configured codex binary succeeded (`doctor`, `models list --json`, `pipelines list --root ... --json`).

Known-gap note:
- Connection works, but caller-guide parity for discovery/diagnostics remains incomplete and should be treated as explicit integration debt.

## 2026-02-28 migrated understanding ledger (09:26-10:13 codex-farm connection, schema boundary, telemetry join path)

### 2026-02-28_09.26.29 codex-farm connection contract aligned

Source: `docs/understandings/2026-02-28_09.26.29-codex-farm-connection-contract-aligned.md`

Problem captured:
- Caller integration drifted from Codex Farm connection guidance for model discovery, pipeline validation, and failure diagnostics.

Findings preserved:
- Interactive model picker now consumes live CLI-discovered model data (`models list --json`) instead of static assumptions.
- Recipe/pass4/pass5 subprocess paths validate configured pipeline IDs via `pipelines list --root ... --json` before execution.
- Failure handling now inspects `process --json` payload and uses `run_id` to fetch first-error details from `run errors --run-id ... --json`.

Anti-loop note:
- If model picker choices and runtime pipeline failures disagree, debug runner discovery/validation helpers before changing run-settings UI surfaces.

### 2026-02-28_09.50.17 codex-farm output schema resolution point

Source: `docs/understandings/2026-02-28_09.50.17-codex-farm-output-schema-resolution-point.md`

Problem captured:
- Schema enforcement logic was at risk of being duplicated in multiple orchestrators, creating drift across pass families.

Findings preserved:
- The shared subprocess runner boundary is the correct single insertion point for `--output-schema` enforcement.
- Pipeline metadata lookup by `pipeline_id` (pack JSON definitions) is required to avoid filename-coupled schema wiring.
- Returned process payload should be checked at this same boundary for `output_schema_path` parity.

Anti-loop note:
- If schema behavior diverges between recipe/pass4/pass5, inspect runner command assembly first; avoid per-orchestrator hotfixes.

### 2026-02-28_10.03.37 codex-exec telemetry consumption boundary (historical pre-ingest snapshot)

Source: `docs/understandings/2026-02-28_10.03.37-codex-exec-telemetry-consumption-boundary.md`

Problem captured:
- There was confusion about whether new codex-exec telemetry fields were already wired into recipeimport runtime/analytics.

Findings preserved:
- At that timestamp, runtime consumed only `process --json` safety fields and did not ingest full `codex_exec_activity.csv` signal families.
- Analytics contracts in this repo were based on performance-history inputs, not codex-exec CSV fields.
- This snapshot is intentionally preserved as historical boundary context and is superseded by later ingest implementation.

Anti-loop note:
- When reviewing older run artifacts, do not assume modern telemetry fields should exist before the 2026-02-28_10.13.48 ingest work.

### 2026-02-28_10.13.48 codex-farm run-id telemetry ingestion path

Source: `docs/understandings/2026-02-28_10.13.48-codex-farm-runid-telemetry-ingestion-path.md`

Problem captured:
- Prompt-tuning and failure triage needed run-scoped Codex Farm telemetry beyond thin process payload metadata.

Findings preserved:
- `run_id` from `process --json` is the stable join key into `codex_exec_activity.csv` rows for the pipeline run.
- Runner now persists compact telemetry slices by pass:
  - recipe manifest/report: `process_runs.pass1|pass2|pass3`
  - pass4 knowledge report: `process_run`
  - pass5 tags report: `process_run`
- CSV lookup follows codex-farm CLI semantics (`--data-dir` override first, fallback `<cwd>/var/codex_exec_activity.csv`).
- Ingestion is non-fatal and warnings are preserved when telemetry rows are unavailable.

Anti-loop note:
- If telemetry is missing, validate `run_id` and `pipeline_id` join inputs before changing payload models or report writers.

## 2026-02-28 docs/tasks consolidation batch (Codex Farm telemetry/report/autotune ingest)

### 2026-02-28_10.08.00 codex-farm telemetry contract ingest

Source task file:
- `docs/tasks/2026-02-28_10.08.00-codex-farm-telemetry-contract-ingest.md`

Problem captured:
- Process metadata was too thin for prompt-tuning loops; runner did not ingest rich `codex_exec_activity.csv` signals.

Durable decisions/outcomes:
- Added structured runner return payload (`CodexFarmPipelineRunResult`) for subprocess runs.
- Added best-effort telemetry CSV ingestion keyed by `run_id + pipeline_id`.
- Persisted compact telemetry to recipe/pass4/pass5 artifacts under `process_runs`/`process_run` without copying full CSV row payloads.
- Kept telemetry ingestion non-fatal with warnings when CSV is missing/unreadable.

Evidence preserved:
- `pytest -o addopts='' tests/llm/test_codex_farm_orchestrator.py -q` (`13 passed`)
- `pytest -o addopts='' tests/llm/test_codex_farm_knowledge_orchestrator.py -q` (`1 passed`)
- `pytest -o addopts='' tests/tagging/test_tagging.py -k "llm or codex or pass5 or tags" -q` (`4 passed`)

### 2026-02-28_10.22.31 telemetry ingest implementation summary merge

Source task file:
- `docs/tasks/2026-02-28_10.22.31-codex-farm-telemetry-implementation-summary.md`

Implementation surfaces preserved:
- Runner + fake runner contract parity updates.
- Orchestrator/report serialization updates across recipe pass, pass4 knowledge, and pass5 tags.
- Deterministic test coverage for telemetry persistence and process payload shape.

Anti-loop note:
- If one pass has telemetry and another does not, compare shared runner payload serialization path first before editing pass-specific report writers.

### 2026-02-28_10.28.23 telemetry_report schema-v2 alignment

Source task file:
- `docs/tasks/2026-02-28_10.28.23-codex-farm-telemetry-v2-alignment.md`

Problem captured:
- Embedded `process --json.telemetry_report` (schema-v2) existed but was not exposed as first-class pass metadata.

Durable decisions/outcomes:
- Elevated embedded `telemetry_report` to top-level structured runner payload field.
- Preserved compact CSV telemetry slices as supplemental row-level context (did not replace them).
- Kept compatibility with older Codex Farm builds where `telemetry_report` can be absent.

### 2026-02-28_10.35.22 autotune payload ingest

Source task file:
- `docs/tasks/2026-02-28_10.35.22-codex-farm-autotune-payload-ingest.md`

Problem captured:
- Caller-ready `run autotune --json` guidance was not captured in recipeimport artifacts.

Durable decisions/outcomes:
- Runner now attempts best-effort `run autotune --run-id <id> --json` after successful process calls.
- Payload is persisted as `autotune_report` in the same shared `process_runs`/`process_run` metadata surfaces.
- Missing command/support remains non-fatal and leaves `autotune_report=null`.

Anti-loop note:
- Do not treat null `autotune_report` as conversion failure; check Codex Farm binary support/version first.

## 2026-03-02 docs/tasks merge ledger (codex-farm progress callback contract)

### 2026-03-01_21.37.45 codex-farm spinner progress bridge

Source task file:
- `docs/tasks/2026-03-01_21.37.45-codex-farm-spinner-progress-bridge.md`

Problem captured:
- Stage and benchmark flows only showed coarse codex phase text because subprocess calls waited for full process completion before surfacing status.

Durable decisions:
- `SubprocessCodexFarmRunner` now streams `process --progress-events` stderr lines and forwards callback-safe `task X/Y` status updates.
- Stage and benchmark call sites now pass existing callback/spinner handlers into recipe/pass4 orchestrators.
- If installed codex-farm does not support `--progress-events`, runner retries once without the flag and continues with phase-only status.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator.py -q`

Anti-loop note:
- Keep progress-event parsing in the subprocess runner boundary; do not duplicate per-call-site parsing logic.

### 2026-03-02_01.02.14 remove volatile active-file tails from codex progress text

Source task file:
- `docs/tasks/2026-03-02_01.02.14-codex-farm-progress-active-noise.md`

Problem captured:
- Progress messages included `active <filename>` suffixes that changed almost every tick, generating low-signal plain-progress noise and defeating exact-message dedupe.

Durable decisions:
- Keep stable counter-bearing callback text (`task X/Y`, running count, error count).
- Remove volatile `active ...` suffix from emitted codex progress status strings.
- Preserve existing dedupe behavior so same-counter updates collapse correctly.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/llm/test_codex_farm_orchestrator.py -q`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py::test_run_with_progress_status_defaults_to_plain_for_agent_env -q`

Anti-loop note:
- If progress noise returns, inspect runner-emitted status text first; do not patch spinner renderer dedupe logic before validating message stability.

## 2026-03-02 migrated understanding ledger (schemaorg 403 triage + pass2/pass3 string contract)

Chronological migration from `docs/understandings`; source files are retired after this merge.

### 2026-03-02_00.37.59 codex-farm schemaorg 403 forbidden failure

Source: `docs/understandings/2026-03-02_00.37.59-codex-farm-schemaorg-403-forbidden.md`

Problem captured:
- Offline benchmark prediction generation with `llm_recipe_pipeline=codex-farm-3pass-v1` reached pass2 (`recipe.schemaorg.v1`) and failed with subprocess exit code `1` for all tasks.

Root cause retained:
- Underlying Codex websocket call returned `403 Forbidden` (`wss://chatgpt.com/backend-api/codex/responses`) in this environment, causing codex subprocess failure before useful pass output was produced.

Durable triage guidance:
- `codex-farm run errors --run-id ... --json` can under-report first-cause details.
- Use run forensics bundles as primary source for root-cause traces:
  - `var/forensics/runs/<run_id>/<task_id>/attempt-*/stderr_tail.txt`
  - `var/forensics/runs/<run_id>/<task_id>/attempt-*/metadata.json`

Anti-loop note:
- If pass2 failures are universal and immediate, check auth/connectivity for Codex backend first before changing pass2 prompt/schema contracts.

### 2026-03-02_07.03.58 recipeimport pass2/pass3 JSON-string contracts

Source: `docs/understandings/2026-03-02_07.03.58-recipeimport-pass2-pass3-json-string-contracts.md`

Problem captured:
- Pass2/pass3 payload shape drift caused schema-validation failures before downstream parsing.

Durable decisions:
- Top-level pass2/pass3 contract fields are JSON strings under strict object schemas (`additionalProperties: false` + string-only top-level fields):
  - pass2: `schemaorg_recipe`, `field_evidence`
  - pass3: `draft_v1`, `ingredient_step_mapping`
- `cookimport/llm/codex_farm_contracts.py` includes coercion so object-form inputs can be normalized into JSON strings for validation.
- Prompt contracts and fake runner defaults were aligned to emit these fields as serialized JSON strings.

Anti-loop note:
- If pass2/pass3 validate failures recur, verify field-type coercion and prompt output shape before widening schemas.

### 2026-03-02_08.18.23 inline prompt input mode

Source task file:
- `docs/tasks/2026-03-02_08.18.23-codexfarm-self-contained-inline-prompts.md`

Problem captured:
- Prompt templates and orchestration asked CodexFarm agents to fetch payloads from paths, creating hidden dependency and inconsistent run environments.

Decisions/outcomes:
- Add runtime support for `{{INPUT_TEXT}}` in CodexFarm template rendering before changing recipeimport prompts.
- Keep `{{INPUT_PATH}}` support as non-breaking compatibility.
- Introduce/use a template mode (`prompt_input_mode`) and enforce inline linting expectations so inline passes are explicit.
- Move `recipe` prompts to inline blocks with `BEGIN_INPUT_JSON` / `END_INPUT_JSON` framing.
- Update llm pack tests and assets to validate both modes during migration.

Critical history preserved:
- This migration was initially blocked by the repo split (CodexFarm code lives outside recipeimport), so only the integration surface should be edited inside this repo after CodexFarm runtime support is present.

Current rule:
- Treat inline mode as preferred for prompt clarity and portability, but never drop path-mode support until all dependent runtime packs are migrated.

## 2026-03-03 migrated understanding ledger (full prompt log payload source)

### 2026-03-02_23.30.23 codexfarm full-prompt log payload provenance

Source:
- `docs/understandings/2026-03-02_23.30.23-codexfarm-full-prompt-log-payload-source.md`

Problem captured:
- Prompt-log consumers could not reliably tell whether rows were exact request captures or reconstructed text, which made benchmark/cutdown audits ambiguous.

Durable decision:
- Keep `full_prompt_log.jsonl` as per-call source-of-truth artifact.
- Persist explicit provenance marker `request_payload_source` (`telemetry_csv` vs `reconstructed_from_prompt_template`).
- Preserve per-call `request_telemetry` metadata for downstream audit/debug.

Anti-loop note:
- If prompt-log trust is questioned, inspect `request_payload_source` before changing cutdown sampling or prompt rendering code.


## 2026-03-03 migrated understanding ledger (codexfarm transport/prompt-plan alignment)


### 2026-03-03_09.19.33 codexfarm-prompt-log-layout

Source:
- `docs/understandings/2026-03-03_09.19.33_codexfarm_prompt_log_layout.md`

Summary:
- Where CodexFarm literal prompt text is stored and how to sample by pass

Preserved notes:

```md
summary: "Where CodexFarm literal prompt text is stored and how to sample by pass"
read_when:
  - "When validating what exact prompt text was sent to CodexFarm"
  - "When comparing pass1/pass2/pass3 instruction wrappers"
---

Literal prompt text is stored in:
- `data/golden/.../codexfarm/codexfarm/full_prompt_log.jsonl`

Key field:
- `request_messages[0].content` (exact user message sent to model)

Pass mapping:
- `pass1`: chunking boundary refinement wrapper
- `pass2`: schema.org extraction wrapper
- `pass3`: final draft wrapper

Quick extraction pattern:
- `jq -sr --arg pass "pass1" 'first(.[] | select(.pass==$pass) | .request_messages[0].content)' full_prompt_log.jsonl`

```

### 2026-03-03_09.27.30 codexfarm-prompt-samples-autogen-hook

Source:
- `docs/understandings/2026-03-03_09.27.30-codexfarm-prompt-samples-autogen-hook.md`

Summary:
- Benchmark CodexFarm prompt sample markdown is best generated in the existing prompt-log builder

Preserved notes:

```md
summary: "Benchmark CodexFarm prompt sample markdown is best generated in the existing prompt-log builder"
read_when:
  - "When adding or debugging benchmark CodexFarm prompt-debug artifacts"
  - "When deciding where to auto-generate human-readable prompt samples"
---

Discovery:
- The benchmark codex artifact builder already centralizes prompt reconstruction and full per-call capture in `cookimport/cli.py::_build_codex_farm_prompt_response_log`.
- This function is where `full_prompt_log.jsonl` is written and where pass/category text artifacts are emitted, so it is the correct single hook for generating a readable sample markdown from canonical rows.

Outcome:
- Added auto-generation of `prompt_type_samples_from_full_prompt_log.md` from `full_prompt_log.jsonl` in that same builder.
- The generated file includes up to 3 literal prompt samples per pass (`pass1`, `pass2`, `pass3`).

```

### 2026-03-03_09.58.02 codexfarm-nonbenchmark-prompt-log-hook

Source:
- `docs/understandings/2026-03-03_09.58.02-codexfarm-nonbenchmark-prompt-log-hook.md`

Summary:
- CodexFarm prompt logs/samples are now generated for stage and labelstudio-import, with pass-specific manifest resolution for pass1..pass5.

Preserved notes:

```md
summary: "CodexFarm prompt logs/samples are now generated for stage and labelstudio-import, with pass-specific manifest resolution for pass1..pass5."
read_when:
  - "When adding or debugging CodexFarm prompt-debug artifacts outside benchmark flows"
  - "When pass4/pass5 prompt logs appear missing or incomplete"
---

## What changed

- Prompt-log generation now runs in non-benchmark CodexFarm flows too:
  - `stage(...)` calls `_build_codex_farm_prompt_response_log(pred_run=run_root, eval_output_dir=run_root)` near run-finalization.
  - `labelstudio_import(...)` calls the same helper after `run_labelstudio_import(...)` returns.
- Stage run manifest writing now includes CodexFarm artifact pointers when `run_root/codexfarm/` exists.

## Pass manifest resolution contract

- pass1/pass2/pass3: `raw/llm/<workbook>/llm_manifest.json`
- pass4: `raw/llm/<workbook>/pass4_knowledge_manifest.json`
- pass5: `raw/llm/<workbook>/pass5_tags_manifest.json`

The helper now reads whichever pass manifests exist, instead of requiring `llm_manifest.json`.

## Telemetry/provenance detail

- Telemetry CSV lookup now supports both legacy `process_runs[pass*]` and single `process_run` payloads (including nested `llm_report.process_run` in pass5 manifests).
- Prompt rows preserve the same source precedence (`telemetry_csv` when prompt text exists, otherwise reconstructed from prompt templates/input JSON).

```

### 2026-03-03_10.19.30 proplan2-vs-runtime-surface-audit

Source:
- `docs/understandings/2026-03-03_10.19.30-proplan2-vs-runtime-surface-audit.md`

Summary:
- Audit notes for Proplan2 against current codex-farm/line-role runtime contracts.

Preserved notes:

```md
summary: "Audit notes for Proplan2 against current codex-farm/line-role runtime contracts."
read_when:
  - "When revising docs/plans/Proplan2.md to match current code seams"
  - "When changing codex-farm pass contracts, llm_recipe_pipeline enums, or benchmark line-role wiring"
---

Key runtime seams discovered:
- Recipe codex-farm orchestration is implemented in `cookimport/llm/codex_farm_orchestrator.py` via `run_codex_farm_recipe_pipeline(...)`, using pass dirs `pass1_chunking`, `pass2_schemaorg`, `pass3_final`.
- `llm_recipe_pipeline` currently accepts only `off|codex-farm-3pass-v1` in `cookimport/config/run_settings.py`; normalization hard-forces unknown values back to `off`.
- Canonical line-role pipeline already exists and is wired separately via `line_role_pipeline` in `cookimport/parsing/canonical_line_roles.py` and `cookimport/labelstudio/ingest.py`.
- Final draft generation already has deterministic fallback (`recipe_candidate_to_draft_v1`) and codex override path (`draft_overrides_by_recipe_id`) in `cookimport/staging/writer.py`.

Important plan/code mismatches:
- Proplan2 says orchestrator symbols are unknown, but current repo already has explicit symbol names and tests for them.
- Proplan2 proposes new pass2/pass3 payload fields without calling out required parallel updates in `llm_pipelines` prompt/schema/definition files and `cookimport/llm/codex_farm_contracts.py`.
- Proplan2 describes adding a new line-role shadow path under `cookimport/llm/`, but an active benchmark line-role subsystem already exists outside this module and should likely be extended instead.
- Proplan2 suggests `run_summary.json`/`run_summary.md` updates for counters; those summaries are stage-run artifacts, while benchmark prediction runs rely on prediction manifests + `llm_manifest.json` under raw LLM artifacts.

Process-policy mismatch to resolve before implementation:
- Root AGENTS policy currently says do not turn on Codex Farm / LLM-based parsing for data import until explicitly ready; any Proplan2 implementation needs explicit user confirmation to proceed against that policy.

```

### 2026-03-03_10.41.10 codexfarm-transport-mismatch-and-pass3-fallback-boundary

Source:
- `docs/understandings/2026-03-03_10.41.10-codexfarm-transport-mismatch-and-pass3-fallback-boundary.md`

Summary:
- CodexFarm orchestrator now records pass1/pass2 transport drift explicitly and uses deterministic pass3 fallback for low-quality bundles.

Preserved notes:

```md
summary: "CodexFarm orchestrator now records pass1/pass2 transport drift explicitly and uses deterministic pass3 fallback for low-quality bundles."
read_when:
  - "When debugging pass2 missing blocks or pass3 low-quality draft regressions"
  - "When auditing llm_manifest transport/evidence/fallback counters"
---

- Transport discovery: effective pass1 indices can include missing block indices, while pass2 payload only serializes existing blocks. This can silently drift without explicit audit checks.
- Runtime contract added: per-recipe `transport_audit/*.json` files now encode effective-vs-payload mismatch details, and `llm_manifest.json` exposes aggregate mismatch counters.
- Fallback discovery: pass3 outputs can satisfy schema but still be low quality (description/headnote text copied into `steps[].instruction`).
- Runtime contract added: pass3 now falls back per recipe to deterministic `recipe_candidate_to_draft_v1(...)` built from pass2 structured outputs when pass3 is missing/invalid/low-quality.

```

### 2026-03-03_10.54.45 execplan-audit-og-vs-implemented

Source:
- `docs/understandings/2026-03-03_10.54.45-execplan-audit-og-vs-implemented.md`

Summary:
- Audit notes comparing OG Proplan2 intent, implemented codex-farm changes, and completed execplan claims.

Preserved notes:

```md
summary: "Audit notes comparing OG Proplan2 intent, implemented codex-farm changes, and completed execplan claims."
read_when:
  - "When validating Proplan2 completion status against code"
  - "When checking which milestones remain unimplemented versus OG expectations"
---

- Confirmed implemented in code: transport audits + mismatch counters, additive evidence normalization sidecars, and recipe-scoped deterministic pass3 fallback.
- Confirmed implemented in tests: targeted orchestrator and normalizer cases for mismatch detection, normalization artifacts, and low-quality pass3 fallback behavior.
- Outstanding versus OG milestone intent: benchmark replay/promotion milestone remains incomplete (dev-slice and full Sea replay outcomes absent).
- Minor contract/process gap: OG says pass2 contract changes should update contracts + pipeline/schema/prompt assets together; implementation updated Python input contract + prompt but not pipeline/schema JSON for pass2 (likely low runtime risk because new fields are pass2 input-only).
- Artifact naming drift from OG wording: OG examples used `<recipe_id>.json`; implementation writes bundle-keyed filenames in `transport_audit/*.json` and `evidence_normalization/*.json`.

```

### 2026-03-03_11.01.27 ogplan-non-m5-alignment-pass

Source:
- `docs/understandings/2026-03-03_11.01.27-ogplan-non-m5-alignment-pass.md`

Summary:
- Non-milestone-5 OG Proplan2 alignment pass updated transport failure-mode semantics, artifact keying, and pred-run token-field compatibility.

Preserved notes:

```md
summary: "Non-milestone-5 OG Proplan2 alignment pass updated transport failure-mode semantics, artifact keying, and pred-run token-field compatibility."
read_when:
  - "When reviewing codex-farm transport mismatch behavior under fail vs fallback"
  - "When debugging labelstudio_eval benchmark CSV appends with legacy pred_context test doubles"
---

- Transport mismatch handling now maps to failure mode at recipe scope: in `fallback` mode the recipe is marked as pass3 fallback with reason `transport mismatch`; in `fail` mode it remains a recipe-level error without process-wide crash.
- Transport audit and evidence normalization sidecar files now use sanitized recipe-id filenames rather than bundle filenames.
- `labelstudio_eval` and `labelstudio_benchmark` benchmark CSV writes now access token usage fields via `getattr(..., None)`, keeping compatibility when tests monkeypatch prediction context objects without token attributes.

```

### 2026-03-03_11.06.42 ogplan-vs-runtime-gap-review

Source:
- `docs/understandings/2026-03-03_11.06.42-ogplan-vs-runtime-gap-review.md`

Summary:
- Review findings for Proplan2 OG intent vs implemented codex-farm runtime and completed execplan claims.

Preserved notes:

```md
summary: "Review findings for Proplan2 OG intent vs implemented codex-farm runtime and completed execplan claims."
read_when:
  - "When validating whether Proplan2 milestones were fully implemented"
  - "When checking transport audit semantics and benchmark-promotion completion status"
---

OG Proplan2 milestones 1/2/4 are implemented in `cookimport/llm/codex_farm_orchestrator.py`, `cookimport/llm/evidence_normalizer.py`, and related tests.

Milestone 5 remains incomplete: completed plan still marks benchmark replay + promotion decision as pending.

Transport audit is only partially aligned with OG wording: `_build_transport_audit` records payload/effective block-id lists but mismatch detection only compares counts for block IDs (not value equality), so “compare block IDs/count” is only fully enforced for counts and index divergence.

```

### 2026-03-03_11.11.55 transport-audit-block-id-value-comparison

Source:
- `docs/understandings/2026-03-03_11.11.55-transport-audit-block-id-value-comparison.md`

Summary:
- Transport audit now compares effective vs payload block-id values, not just counts and index alignment.

Preserved notes:

```md
summary: "Transport audit now compares effective vs payload block-id values, not just counts and index alignment."
read_when:
  - "When auditing pass1/pass2 transport mismatch reasons in codex-farm recipe pipeline"
  - "When transport_audit mismatch reports should capture block-id value drift"
---

`_build_transport_audit` previously derived `effective_block_ids` as synthetic `b{idx}` values, so mismatch checks only guaranteed index/count drift detection.

Runtime now computes effective block IDs from `full_blocks_by_index` and `_build_transport_audit` adds explicit value equality comparison (`effective_block_ids_vs_payload_block_ids_values`) in addition to existing index/count checks.

Regression coverage: `tests/llm/test_codex_farm_orchestrator.py::test_build_transport_audit_detects_block_id_value_mismatch`.

```

### 2026-03-03_11.20.30 seaandsmoke-code-packet-runtime-seams

Source:
- `docs/understandings/2026-03-03_11.20.30-seaandsmoke-code-packet-runtime-seams.md`

Summary:
- Code packet seam map for pass1->pass2 handoff, EPUB unstructured preprocessing, canonical projection/join, and pass3 mapping/override boundaries.

Preserved notes:

```md
summary: "Code packet seam map for pass1->pass2 handoff, EPUB unstructured preprocessing, canonical projection/join, and pass3 mapping/override boundaries."
read_when:
  - "When preparing code-only exports for external review of codex recipe pipeline seams"
  - "When clarifying whether pass3 ingredient_step_mapping directly overrides canonical line labels"
---

- Pass1->Pass2 block handoff lives in `cookimport/llm/codex_farm_orchestrator.py`: `run_codex_farm_recipe_pipeline(...)` computes pass2 input from `_included_indices_for_state(...)`, then records parity via `_build_transport_audit(...)`.
- EPUB unstructured preprocessing/splitting spans three layers: HTML normalization (`cookimport/parsing/epub_html_normalize.py`), Unstructured partition-to-block conversion (`cookimport/parsing/unstructured_adapter.py`), and EPUB spine extraction orchestration (`cookimport/plugins/epub.py`).
- Canonical projection/join surfaces split across benchmark eval alignment (`cookimport/bench/eval_canonical_text.py`) and cutdown join tables (`cookimport/bench/cutdown_export.py`), with line-role span projection helper in `cookimport/labelstudio/canonical_line_projection.py`.
- `Pass3FinalDraftOutput` includes `ingredient_step_mapping` contract field (`cookimport/llm/codex_farm_contracts.py`), but this runtime path does not directly use that mapping to overwrite canonical line labels; label override policy is handled in canonical line-role logic (`cookimport/parsing/canonical_line_roles.py`).

```

### 2026-03-03_12.16.08 ogplan-proplan2-code-alignment-review

Source:
- `docs/understandings/2026-03-03_12.16.08-ogplan-proplan2-code-alignment-review.md`

Summary:
- Gap check between OG Proplan2 intent, current code, and completed Proplan2 claims.

Preserved notes:

```md
summary: "Gap check between OG Proplan2 intent, current code, and completed Proplan2 claims."
read_when:
  - "When validating whether docs/plans/Proplan2.md completion claims are reflected in runtime code"
  - "When auditing remaining OG milestone gaps for codex_farm orchestrator work"
---

- Milestones 1/2/4 are implemented in runtime code: transport audit + mismatch guards, additive evidence normalization, and deterministic pass3 fallback.
- Claimed dev-slice manifest path in completed plan (`docs/plans/2026-03-03_10.40.28-seaandsmoke-dev-slice-c0-c6-c8-c9.json`) is missing from the repository.
- Milestone 5 is still incomplete by plan state and repo evidence: no recorded dev-slice/full-SEA benchmark replay outcomes or promotion decision in `docs/plans/Proplan2.md`.
- Targeted tests for implemented milestones pass; known unrelated failing test remains `tests/llm/test_codex_farm_orchestrator.py::test_subprocess_runner_emits_progress_callback_from_progress_events` (`task 0/2` dedupe assertion).

```

### 2026-03-03_12.43.42 pro3-execplan-codebase-fit-gaps

Source:
- `docs/understandings/2026-03-03_12.43.42-pro3-execplan-codebase-fit-gaps.md`

Summary:
- Pro3 ExecPlan aligns with active codex-farm seams but has stale milestone state and unresolved path placeholders that reduce self-contained execution reliability.

Preserved notes:

```md
summary: "Pro3 ExecPlan aligns with active codex-farm seams but has stale milestone state and unresolved path placeholders that reduce self-contained execution reliability."
read_when:
  - "When revising docs/plans/OGplan/Pro3.md before implementation"
  - "When checking codex-farm transport/fallback work that overlaps already-shipped Proplan2 milestones"
---

- Pro3 intent still matches real seams: pass1->pass2 transport (`cookimport/llm/codex_farm_orchestrator.py`), pass3 fallback quality gates, outside-span trace joins (`scripts/benchmark_cutdown_for_external_ai.py`), and line-role projection (`cookimport/labelstudio/canonical_line_projection.py`).
- Several Pro3 checklist items are already implemented in runtime/tests (transport mismatch guard + per-recipe fallback + evidence normalization), so plan `Progress` should be updated to avoid duplicate implementation work.
- Self-contained gaps: unresolved `<bridge_builder_file>` placeholder, wrong path `cookimport/parsing/canonical_line_projection.py` (actual is under `cookimport/labelstudio`), and planned `tests/debug/...` path does not match existing test tree.
- Boundary contract remains mixed across modules: orchestrator currently treats `end_block_index` as exclusive for pass2 selection, while bridge replay logic treats `end_block_index` as inclusive for line assignment; Pro3 should explicitly reconcile this across both paths.

```

### 2026-03-03_13.05.30 pro3-transport-gating-outside-span-policy

Source:
- `docs/understandings/2026-03-03_13.05.30-pro3-transport-gating-outside-span-policy.md`

Summary:
- Pro3 implementation seam note: inclusive transport helper + pass2 degradation gating + outside-span prompt-join policy.

Preserved notes:

```md
summary: "Pro3 implementation seam note: inclusive transport helper + pass2 degradation gating + outside-span prompt-join policy."
read_when:
  - "When debugging pass1/pass2 span-count mismatches after Pro3 transport helper rollout"
  - "When a codex-farm run skips pass3 due pass2 degradation reasons"
  - "When outside-span bridge diagnostics appear to have borrowed unrelated prompt context"
---

- `codex_farm_transport.build_pass2_transport_selection(...)` is now the authoritative pass1->pass2 selection path, and it uses explicit inclusive semantics (`start <= idx <= end`) with audit metadata (`end_index_semantics: inclusive`).
- `run_codex_farm_recipe_pipeline(...)` now marks pass2 rows as `degraded` with explicit reasons before pass3 assembly; degraded rows skip pass3 LLM calls and resolve via deterministic fallback.
- Deterministic fallback no longer starts from pass2 schema recipe material; it starts from `state.recipe` and only applies guarded pass2 enrichments when evidence is non-empty/non-placeholder.
- `benchmark_cutdown_for_external_ai.py` outside-span trace joins now block fallback prompt-row borrowing and emit explicit outside statuses (`outside_span_archive_only`, `outside_span_unattributed`, etc.).

```

## 2026-03-03 docs/tasks consolidation batch (Proplan2 completion + milestone-5 outcome)

### 2026-03-03_12.45.00 Proplan2 code-aligned CodexFarm repair plan

Source task file:
- `docs/tasks/Proplan2.md`

Problem captured:
- Codex recipe correction needed transport-level observability and deterministic fallback protections before any benchmark-promotion decision could be trusted.

Durable decisions/outcomes:
- Implemented transport audits at recipe scope with mismatch counters surfaced in `llm_manifest.json`.
- Added additive evidence normalization (`normalized_evidence_*`) without replacing authoritative pass2 source fields (`canonical_text` + `blocks`).
- Added recipe-scoped deterministic pass3 fallback for missing/invalid/low-quality pass3 bundles.
- Kept benchmark taxonomy measurement on existing line-role subsystem instead of introducing a second LLM label path.
- Preserved policy boundary: codex recipe correction remains explicit opt-in and was not promoted to default.

Milestone-5 evidence preserved in task:
- Full Sea paired replay: `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codex_vs_vanilla_comparison.json`
  - `strict_accuracy`: codex `0.282353` vs vanilla `0.384874` (delta `-0.102521`)
  - `macro_f1_excluding_other`: codex `0.346740` vs vanilla `0.404162` (delta `-0.057421`)
- Dev-slice (`c0,c6,c8,c9`) cutdown aggregate:
  - source: `.../2026-03-03_12.12.49_cutdown_md/per_recipe_or_per_span_breakdown.json`
  - codex `0.287671` vs vanilla `0.410959` (delta `-0.123288`)
- Transport mismatch counter on that replay: `transport_mismatches=0`.

Anti-loop note:
- A clean transport audit does not imply metric promotion readiness; keep transport-fix verification and benchmark-promotion criteria as separate gates.


## 2026-03-03 docs/understandings consolidation batch

The entries below were merged from `docs/understandings` in timestamp order before source-file cleanup.

### 2026-03-03_13.10.03-pro3-ogplan-vs-code-audit

Source:
- `docs/understandings/2026-03-03_13.10.03-pro3-ogplan-vs-code-audit.md`

Summary:
- Audit note for Pro3 OG plan vs runtime implementation and completed ExecPlan claims.

Preserved source note:

````md
---
summary: "Audit note for Pro3 OG plan vs runtime implementation and completed ExecPlan claims."
read_when:
  - "When validating Pro3 completion claims against code behavior."
  - "When deciding whether remaining Pro3 work is implementation or documentation-only."
---

# Pro3 OG Plan vs Code Audit (2026-03-03)

Scope reviewed:
- `docs/plans/OGplan/Pro3.md` (original intent)
- runtime modules and tests listed in Pro3
- `docs/plans/Pro3.md` (completed ExecPlan)

Key discovery:
- Core Pro3 mechanics are implemented and verified in code/tests (transport helper, pass2 degradation gating, fallback re-anchor, outside-span prompt-join hardening, URN span flag preservation, replay script).
- Follow-up at 2026-03-03 13:22 America/Toronto closed the remaining metric gap: per-recipe `pass1_span_loss_metrics` now emits raw-vs-clamped span counts and loss ratio in `llm_manifest.json`.

Why it matters:
- Pro3 completion status is now aligned with OG intent for both behavior and observability.

````

### 2026-03-03_13.22.30-pro3-pass1-span-loss-metrics-surface

Source:
- `docs/understandings/2026-03-03_13.22.30-pro3-pass1-span-loss-metrics-surface.md`

Summary:
- Pro3 span-loss observability now records raw-vs-clamped pass1 span metrics per recipe.

Preserved source note:

````md
---
summary: "Pro3 span-loss observability now records raw-vs-clamped pass1 span metrics per recipe."
read_when:
  - "When auditing pass1 midpoint clamp impact in codex-farm manifests."
  - "When OG Pro3 review asks whether raw-vs-clamped span-loss metrics are implemented."
---

# Pro3 pass1 span-loss metrics surface

`run_codex_farm_recipe_pipeline` now stores pass1 raw boundaries before midpoint clamping and emits per-recipe `pass1_span_loss_metrics` in `llm_manifest.json`.

Metric payload records raw/clamped start+end, raw/clamped span counts, lost-block count, and loss ratio. This closes the OG Pro3 observability gap where clamping impact existed behaviorally but was not surfaced as a first-class manifest field.

````

### 2026-03-03_13.51.55-pro3-overlap-clamp-and-pass3-placeholder-repair

Source:
- `docs/understandings/2026-03-03_13.51.55-pro3-overlap-clamp-and-pass3-placeholder-repair.md`

Summary:
- Quality-first Pro3 follow-up: overlap-only pass1 clamp and pass3 placeholder-step repair from pass2 evidence.

Preserved source note:

````md
---
summary: "Quality-first Pro3 follow-up: overlap-only pass1 clamp and pass3 placeholder-step repair from pass2 evidence."
read_when:
  - "When codex runs show large pass1 clamped block loss and many pass2 missing-instructions degradations."
  - "When pass3 outputs collapse to placeholder-only instructions despite usable pass2 extracted instructions."
---

# Pro3 quality-first follow-up

Observed Sea single-offline runs showed large pass1 clamp loss and high pass3 fallback rates. Two targeted changes landed:

1. Pass1 boundary clamping now resolves actual overlap between recipe spans and splits overlap windows at midpoint, instead of enforcing heuristic midpoint partitions that could aggressively shrink evidence windows.
2. Pass3 placeholder-only drafts are now repaired from pass2 extracted instructions (when non-placeholder instruction evidence exists) before low-quality rejection.

Outcome in code contracts:
- Transport/audit invariants remain strict.
- Clamping still prevents overlap but is less destructive to pass1-selected evidence.
- Placeholder collapse no longer forces avoidable pass3 fallback when pass2 evidence is usable.

````

### 2026-03-03_14.27.12-seaandsmoke-codexfarm-failure-root-causes

Source:
- `docs/understandings/2026-03-03_14.27.12-seaandsmoke-codexfarm-failure-root-causes.md`

Summary:
- Root-cause diagnosis of codexfarm fallback-heavy behavior in SeaAndSmokeCUTDOWN single-offline run 2026-03-03_13.37.54.

Preserved source note:

````md
---
summary: "Root-cause diagnosis of codexfarm fallback-heavy behavior in SeaAndSmokeCUTDOWN single-offline run 2026-03-03_13.37.54."
read_when:
  - When codexfarm recipe runs show high pass3 fallback counts
  - When pass2 reports missing_instructions despite apparent recipe evidence
  - When codex-vs-vanilla benchmark quality regresses
---

# Findings

- Run inspected: `data/golden/benchmark-vs-golden/2026-03-03_13.37.54/single-offline-benchmark/seaandsmokecutdown`.
- CodexFarm run had `pass2_degraded=7`, `pass3_fallback=14`, `pass3_ok=4` in `llm_manifest.json`.

## Root cause A: pass1 clamp dropped evidence aggressively

- `pass1_span_loss_metrics` shows large clamped losses on 16/18 recipes (194 blocks total lost).
- Raw pass1 spans were mostly non-overlapping, but clamped spans still shrank for almost every recipe.
- The degraded recipes (`c2,c4,c6,c7,c8,c12,c16`) all had `missing_instructions`; several had instruction blocks just beyond the clamped end.
- Example: `c8` raw span `356..402` was clamped to `356..379` (lost 23 blocks), and dropped lines include explicit cooking instructions (`TO SERVE`, processing/heat/reduce steps).

## Root cause B: pass3 output-shape mismatch triggered placeholder rejection

- All 7 pass3 low-quality rejections were `draft_v1 step instructions are placeholder-only`.
- For those recipes, pass3 `draft_v1` payload was often schema-like (`instructions` or `recipeInstructions`) instead of draft shape (`steps`).
- Because `steps` was absent, normalization injected placeholder step text (`See original recipe for details.`), then low-quality guardrails rejected it.
- This happened even when pass2 already had strong instruction evidence (e.g., `c0` had 7 extracted instructions).

## Secondary contributing factor

- Run config had `line_role_pipeline=off`, so line-label benchmark scoring did not receive direct LLM line-role assistance.
- This does not explain fallback behavior, but it explains why label metrics did not benefit from a separate LLM line-role path.

# Fix targets

- Keep pass1 clamping overlap-only (do not shrink non-overlapping spans).
- Repair pass3 placeholder-only steps from pass2 extracted instructions before rejection.
- Continue capturing `pass1_span_loss_metrics` and track `pass2_degraded` + `pass3_fallback` deltas in follow-up benchmark runs.

````

### 2026-03-03_14.57.52-codex-contract-json-repair-for-stringified-objects

Source:
- `docs/understandings/2026-03-03_14.57.52-codex-contract-json-repair-for-stringified-objects.md`

Summary:
- Codex farm contract parsing can fail on malformed stringified JSON objects; bounded repair recovers common artifacts.

Preserved source note:

````md
---
summary: "Codex farm contract parsing can fail on malformed stringified JSON objects; bounded repair recovers common artifacts."
read_when:
  - "When pass2/pass3 bundles fail with schemaorg_recipe or draft_v1 JSON-object validation errors"
  - "When llm_manifest shows pass2_errors from invalid pass2 output despite usable extracted fields"
---

# Discovery

In the SeaAndSmokeCUTDOWN single-offline run `2026-03-03_14.34.08`, several pass2 and one pass3 output bundle carried object fields as malformed JSON strings (instead of proper objects). Typical artifacts included:

- missing/mismatched closing `]` / `}`
- raw control bytes in string content (including `\x00`)
- null-hex artifacts like `\x00e9` in words (e.g. `saut\x00e9`)
- extra text around otherwise valid JSON object content

These caused `Pass2SchemaOrgOutput` / `Pass3FinalDraftOutput` validation to fail before orchestration quality gates could run.

# What Changed

`cookimport/llm/codex_farm_contracts.py` now applies bounded repair when object fields are provided as strings:

1. normalize common artifacts (control-byte cleanup, `\x00hh` repair, trailing-comma cleanup)
2. rebalance JSON bracket/brace structure with quote-aware scanning
3. attempt first-object extraction via `JSONDecoder.raw_decode` if full parse still fails

If repaired payload still cannot deserialize to an object, validation still fails.

# Verified

- `pytest tests/llm/test_codex_farm_contracts.py` (new malformed-string cases)
- `pytest tests/llm/test_codex_farm_orchestrator.py`
- direct replay load of previously failing artifacts from `2026-03-03_14.34.08` now validates for pass2 `c1,c3,c5,c6,c16` and pass3 `c4`.

````

### 2026-03-03_15.25.41-pass3-schema-v-missing-legacy-draft-shapes

Source:
- `docs/understandings/2026-03-03_15.25.41-pass3-schema-v-missing-legacy-draft-shapes.md`

Summary:
- Pass3 schema_v validation fallbacks were driven by legacy draft_v1 object shapes, not empty evidence.

Preserved source note:

````md
---
summary: "Pass3 schema_v validation fallbacks were driven by legacy draft_v1 object shapes, not empty evidence."
read_when:
  - "When llm_manifest shows many pass3 fallbacks with draft_v1 schema_v missing."
  - "When pass3 output contains name/instructions or schema.org payloads instead of RecipeDraftV1."
---

# Discovery

In SeaAndSmoke single-offline run `2026-03-03_15.07.45`, the dominant pass3 fallback class (`schema_v` missing) came from `draft_v1` payload shape drift.

Observed pass3 `draft_v1` payload variants:

- legacy recipe shape (`name`, `ingredients`, `instructions`)
- schema.org-only shape (`name`, `recipeInstructions`, `recipeIngredient`)
- pass2-like shape (`schemaorg_recipe`, `extracted_instructions`)

These payloads often still contained usable title/instruction evidence, but failed strict `RecipeDraftV1` validation because `schema_v`/`recipe.title`/`steps[].instruction` were not arranged in draft-v1 form.

# Decision

Normalize/coerce pass3 `draft_v1` payloads in orchestrator before validation:

- default `schema_v` to `1` when missing/invalid
- derive `recipe.title` from recipe/title/name/schemaorg name fields
- derive `steps` from existing `steps`, `instructions`, `recipeInstructions`, `extracted_instructions`, or `schemaorg_recipe.recipeInstructions`

Strict quality gates and deterministic fallback policy remain unchanged.

````

### 2026-03-03_15.40.00-pass2-missing-instructions-root-cause-report

Source:
- `docs/understandings/2026-03-03_15.40.00-pass2-missing-instructions-root-cause-report.md`

Summary:
- Root-cause report for pass2 missing_instructions degradation in SeaAndSmokeCUTDOWN codexfarm run (2026-03-03_13.37.54).

Preserved source note:

````md
---
summary: "Root-cause report for pass2 missing_instructions degradation in SeaAndSmokeCUTDOWN codexfarm run (2026-03-03_13.37.54)."
read_when:
  - "Investigating codex-farm runs where pass2_degraded or pass3_fallback are high"
  - "Comparing pre-fix midpoint clamp behavior to overlap-only clamp behavior"
---

# Pass2 Missing-Instructions Root Cause Report

## Scope
- Run timestamp: `2026-03-03_13.37.54`
- Benchmark: `single-offline-benchmark/seaandsmokecutdown`
- Variant: `codexfarm`
- Manifest: `data/golden/benchmark-vs-golden/2026-03-03_13.37.54/single-offline-benchmark/seaandsmokecutdown/codexfarm/prediction-run/raw/llm/seaandsmokecutdown/llm_manifest.json`

## Executive Summary
Pass2 degraded 7 recipes because `extracted_instructions` was empty for those recipe bundles, producing degradation reason `missing_instructions`. The orchestrator then marks those recipes degraded and forces recipe-level fallback before pass3. Most of the degraded bundles had strong evidence-loss from pass1 clamping in this run, and one also had OCR/page-artifact warning signals.

## Confirmed Signals
- `counts.pass2_degraded = 7`
- `counts.pass3_fallback = 14`
- `pass3 fallback reasons` distribution:
  - `7x` pass3 low-quality rejection: placeholder-only steps
  - `6x` pass2 degraded: missing_instructions
  - `1x` pass2 degraded: missing_instructions + `warning_bucket:ocr_or_page_artifact`

## Why `pass2_degraded=7` Happened
In this run, the 7 degraded pass2 inputs were dominated by title/story/ingredients/`SERVES` content, with no usable instruction lines in canonical evidence. Pass2 warnings repeatedly state variants of "No explicit ... instructions are present in the evidence/source".

The degraded recipe IDs were:
- `...:c2`
- `...:c4`
- `...:c6`
- `...:c7`
- `...:c8`
- `...:c12`
- `...:c16`

## Evidence-Loss Correlation (Pass1 Clamp)
This run used the older midpoint-cross clamp behavior (warning text in manifest: `pass1 boundaries clamped to prevent overlap/cross-midpoint drift.`). Span-loss metrics for degraded recipes show substantial truncation:

- `c2` raw `133-172` -> clamped `133-156` (lost `16` blocks)
- `c8` raw `356-402` -> clamped `356-379` (lost `23` blocks)
- `c12` raw `490-512` -> clamped `490-498` (lost `14` blocks)

Aggregate comparison in this run:
- degraded recipes average clamped loss: `13.86` blocks
- pass2-ok recipes average clamped loss: `8.82` blocks

This is correlational, but consistent with instruction evidence being truncated out of pass2 input for affected bundles.

## OCR/Page-Artifact Contribution
One degraded recipe (`c8`) included `warning_bucket:ocr_or_page_artifact`, alongside split/page-marker artifacts in evidence. This likely further reduced instruction extraction reliability for that bundle.

## Orchestrator Behavior (By Design)
The fail-safe is behaving as implemented:
1. If pass2 has no instructions, `_pass2_degradation_reasons` adds `missing_instructions`.
2. Any pass2 degradation marks recipe as `degraded` and sets pass3 to `fallback` path.
3. Recipe-level fallback payload is generated deterministically.

So the observed behavior is not random regression; it is an expected consequence of missing/truncated instruction evidence under current guardrails.

## Current Status Relative to This Incident
Two targeted fixes were implemented after this run:
- overlap-only pass1 clamp (to preserve non-overlapping evidence)
- pass3 placeholder-step repair from pass2 extracted instructions

The incident run predates those fixes, so a fresh rerun is required to measure impact on:
- `pass2_degraded` count
- `pass3_fallback` count
- per-recipe span-loss metrics

````

### 2026-03-03_15.44.35-pass2-warning-bucket-page-layout-naming

Source:
- `docs/understandings/2026-03-03_15.44.35-pass2-warning-bucket-page-layout-naming.md`

Summary:
- Pass2 warning bucket label was renamed to page/layout-specific wording while preserving legacy compatibility in cutdown tooling.

Preserved source note:

````md
---
summary: "Pass2 warning bucket label was renamed to page/layout-specific wording while preserving legacy compatibility in cutdown tooling."
read_when:
  - "When pass2 degraded reasons mention page-marker artifacts in EPUB sources."
  - "When reconciling old ocr_or_page_artifact runs with new manifests."
---

# Discovery

`warning_bucket:ocr_or_page_artifact` was misleading for EPUB-heavy runs where the issue is usually page-marker/layout residue, not OCR itself.

# What changed

- Codex orchestrator now emits `warning_bucket:page_or_layout_artifact`.
- Benchmark cutdown tooling canonicalizes both old and new names to `page_or_layout_artifact` for consistent reporting across historical and new manifests.

# Boundary

This is a naming/diagnostic-contract change only. The degrade gate behavior is unchanged.

````

### 2026-03-03_17.12.05-single-offline-codexfarm-pass2-timeout-failure

Source:
- `docs/understandings/2026-03-03_17.12.05-single-offline-codexfarm-pass2-timeout-failure.md`

Summary:
- Single-offline codexfarm variant failed in pass2 because three tasks hit the 180s codex timeout across all retries.

Preserved source note:

````md
---
summary: "Single-offline codexfarm variant failed in pass2 because three tasks hit the 180s codex timeout across all retries."
read_when:
  - "When single-offline benchmark shows codexfarm failed for recipe.schemaorg.v1 with exit code 1"
  - "When deciding whether to increase pass2 timeout or disable codexfarm for benchmark runs"
---

## Discovery

Run `2026-03-03_16.40.36` (`seaandsmokecutdown`) succeeded for `vanilla` and failed for `codexfarm` only.

Failure details from runner error:
- `run_id=0aebb0d8a73644e78c77355005fc9144`
- `pipeline=recipe.schemaorg.v1` (pass2)
- `process_exit_code=1`, `subprocess_exit=1`
- `failure_categories=timeout:21`
- `first_error=codex exec timed out after 180s`

CodexFarm run-errors payload confirms exactly 3 failed tasks (`r0002`, `r0008`, `r0014`), each with:
- `attempts=3`
- `execution_attempts=3`
- `error=codex exec timed out after 180s`

Config source of timeout:
- `llm_pipelines/pipelines/recipe.schemaorg.v1.json` has `"codex_timeout_seconds": 180`.

Operational note:
- This is not a full benchmark crash; single-offline runner completed with `1/2` variants successful and skipped codex-vs-vanilla comparison because codexfarm failed.

````

### 2026-03-03_18.09.09-single-offline-codexfarm-pass3-timeout-failure

Source:
- `docs/understandings/2026-03-03_18.09.09-single-offline-codexfarm-pass3-timeout-failure.md`

Summary:
- Single-offline codexfarm variant failed in pass3 because every task hit the 180s codex timeout across retries.

Preserved source note:

````md
---
summary: "Single-offline codexfarm variant failed in pass3 because every task hit the 180s codex timeout across retries."
read_when:
  - "When single-offline benchmark shows codexfarm failed for recipe.final.v1 with exit code 1."
  - "When run errors report timeout-only failure_categories and no pass3 out files."
---

## Discovery

Run `2026-03-03_17.18.02` (`seaandsmokecutdown`) succeeded for `vanilla` and failed for `codexfarm` only.

Failure details from runner error:
- `run_id=fee9de2234c34e95bc62888838247877`
- `pipeline=recipe.final.v1` (pass3)
- `process_exit_code=1`, `subprocess_exit=1`
- `telemetry_rows=48`
- `failure_categories=timeout:48`
- `first_error=codex exec timed out after 180s`

Telemetry evidence:
- Pass3 started with `16` tasks.
- Pass3 ended with `errors 16` and `done 0`.
- `var/codex_exec_activity.csv` rows for this run show `attempt_index=1..3` and `failure_category=timeout` for each task (`16 * 3 = 48` rows).

Operational note:
- This is a partial benchmark result, not a full benchmark crash; single-offline completed with `1/2` variant runs and skipped codex-vs-vanilla comparison because codexfarm failed.

````

### 2026-03-03_18.18.54-llm-timeout-default-surfaces-expanded

Source:
- `docs/understandings/2026-03-03_18.18.54-llm-timeout-default-surfaces-expanded.md`

Summary:
- LLM timeout defaults include prelabel preflight, line-role fallback, and optional pass4/pass5 pipeline specs in addition to benchmark pass settings.

Preserved source note:

````md
---
summary: "LLM timeout defaults include prelabel preflight, line-role fallback, and optional pass4/pass5 pipeline specs in addition to benchmark pass settings."
read_when:
  - "When changing the project-wide default timeout policy for LLM-backed calls."
  - "When validating that no LLM call path still uses legacy 30/120/180/300 second defaults."
---

LLM timeout defaults are spread across multiple subsystems, not just benchmark pass pipelines:

- CLI/Label Studio prelabel defaults (`DEFAULT_PRELABEL_TIMEOUT_SECONDS`, ingest function defaults, and `--prelabel-timeout-seconds`) set provider call timeout policy.
- Prelabel model-access preflight is its own LLM probe and had a historical 30-second cap in the ingest call path (`min(30, prelabel_timeout_seconds)`), which must be removed to honor global timeout policy.
- Canonical line-role Codex fallback has an independent default timeout argument in `cookimport/parsing/canonical_line_roles.py`.
- Codex-farm pipeline specs for optional pass4/pass5 (`recipe.knowledge.v1`, `recipe.tags.v1`) have their own `codex_timeout_seconds` defaults and need to be aligned with pass1/pass2/pass3.

With these surfaces aligned, LLM-touching defaults are uniformly 600 seconds unless a command/runtime override is supplied.

````

### 2026-03-03_20.07.02-feedback-relevance-after-canonical-guards

Source:
- `docs/understandings/2026-03-03_20.07.02-feedback-relevance-after-canonical-guards.md`

Summary:
- Post-18.31 feedback relevance check after canonical guard updates: line-role bucket critique is partially outdated, while fallback gating and runtime-cost concerns remain active.

Preserved source note:

````md
---
summary: "Post-18.31 feedback relevance check after canonical guard updates: line-role bucket critique is partially outdated, while fallback gating and runtime-cost concerns remain active."
read_when:
  - "When revisiting external feedback that was based on SeaAndSmoke run 2026-03-03_18.31.00."
  - "When deciding whether to prioritize line-role policy work versus pass2/pass3 gating and runtime controls."
---

# Discovery

Compared the original benchmark run (`2026-03-03_18.31.00`) against later runs (`2026-03-03_19.41.28_seaandsmoke-next-buckets`, `2026-03-03_19.51.01`) plus current `codex_farm_contracts`/`codex_farm_orchestrator` behavior.

# What is now outdated

- The largest line-role miss buckets cited from `18.31.00` were materially reduced after canonical guard changes:
  - `INGREDIENT_LINE -> OTHER`: `68 -> 21`
  - `HOWTO_SECTION -> RECIPE_TITLE`: `36 -> 6`
  - `INSTRUCTION_LINE -> INGREDIENT_LINE`: `26 -> 1`
- The specific Romano-beans pass3 JSON failure class is no longer present in the latest paired run (`c9` moved from `pass3=fallback` to `pass3=ok`), and contract parsing now includes bounded JSON-object repair in `cookimport/llm/codex_farm_contracts.py`.

# What is still relevant

- Runtime cost concern remains strong:
  - `18.31.00` codex prediction time: `151.97s` vs vanilla `9.68s`
  - `19.51.01` codex prediction time: `264.81s` vs vanilla `9.71s`
- Pass2 degradation policy is still fail-closed for `page_or_layout_artifact` and still drives fallback:
  - `18.31.00`: `pass2_degraded=8`, `pass3_fallback=9`
  - `19.51.01`: `pass2_degraded=5`, `pass3_fallback=5`
  - all current fallback reasons are still `pass2 degraded: warning_bucket:page_or_layout_artifact`
- Narrative outside-span confusion remains a live bucket (`OTHER -> RECIPE_NOTES`, `OTHER -> KNOWLEDGE`) even after the canonical improvements.


````

### 2026-03-03_20.31.33-codexfarm-soft-gating-plan-rebaseline

Source:
- `docs/understandings/2026-03-03_20.31.33-codexfarm-soft-gating-plan-rebaseline.md`

Summary:
- ExecPlan rebaseline discovery: current codex-farm seams still hard-gate degraded pass2 rows, while latest SeaAndSmoke artifacts shifted fallback reasons and model/runtime profile.

Preserved source note:

````md
---
summary: "ExecPlan rebaseline discovery: current codex-farm seams still hard-gate degraded pass2 rows, while latest SeaAndSmoke artifacts shifted fallback reasons and model/runtime profile."
read_when:
  - "When revising the soft-gating/selective-pass3 ExecPlan against current runtime code and artifacts."
  - "When baseline run IDs or codex model drift make runtime comparisons ambiguous."
---

# Discovery

While reworking `docs/plans/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`, I re-audited orchestrator/parsing/cutdown seams and latest benchmark artifacts.

# Key findings

- `cookimport/llm/codex_farm_orchestrator.py` still treats any pass2 degradation reason as immediate pass3 fallback (`pass2_status="degraded"` then `pass3_status="fallback"`), and `_PASS2_DEGRADING_WARNING_BUCKETS` still includes `page_or_layout_artifact`.
- `cookimport/parsing/canonical_line_roles.py` outside-span prose still has two upgrade paths (`KNOWLEDGE` and `RECIPE_NOTES`) that can absorb narrative prose.
- `scripts/benchmark_cutdown_for_external_ai.py` currently ingests pass statuses/reasons but has no fields for pass2 severity or pass3 routing mode.
- Latest paired SeaAndSmoke runs moved beyond the original plan baseline:
  - newer runs exist after `2026-03-03_19.51.01` (`20.05.26`, `20.13.14`),
  - page/layout degradation appears in `20.05.26` but not `20.13.14`,
  - codex model changed across runs (`gpt-5.3-codex-spark` -> `gpt-5.2` -> `gpt-5.1-codex-mini`), making runtime deltas non-comparable without explicit model-locking.

# Planning implication

The ExecPlan should keep original goals, but must (1) add additive manifest diagnostics rather than status-enum changes, (2) lock codex model/effort for benchmark comparisons, and (3) include required `bench speed-discover/run/compare` runtime checks.

````

### 2026-03-03_20.46.18-codexfarm-soft-gating-pass3-routing-contract

Source:
- `docs/understandings/2026-03-03_20.46.18-codexfarm-soft-gating-pass3-routing-contract.md`

Summary:
- Soft-gated codex-farm pass3 routing now separates hard fallback from low-risk deterministic promotion while preserving pass status enums.

Preserved source note:

````md
---
summary: "Soft-gated codex-farm pass3 routing now separates hard fallback from low-risk deterministic promotion while preserving pass status enums."
read_when:
  - "When debugging why degraded pass2 rows now sometimes end as pass3_status=ok without a pass3 call."
  - "When wiring llm_manifest pass2/pass3 routing diagnostics into benchmark cutdowns or dashboards."
---

# Discovery

Pass2 degradation handling in `cookimport/llm/codex_farm_orchestrator.py` needed two distinct outcomes that were previously conflated: fail-safe hard degradation fallback and runtime-saving soft degradation promotion.

# What changed

- Pass2 degradation reasons are still emitted the same way, but now classified with `_pass2_degradation_severity(...)`.
- Only `warning_bucket:page_or_layout_artifact` is soft; any other reason (or unknown reason) is hard.
- Hard degradation keeps prior behavior (`pass3_status=fallback` + deterministic finalizer).
- Soft degradation stays `pass2_status=degraded` but enters selective routing:
  - low-risk rows (non-placeholder instruction evidence) skip pass3 and use deterministic promotion,
  - remaining soft rows can still route to pass3 LLM.
- Manifest diagnostics are additive (`pass2_degradation_severity`, `pass2_promotion_policy`, `pass3_execution_mode`, `pass3_routing_reason`) so downstream scripts can distinguish true pass3 calls from deterministic promotion.

# Why this matters

This keeps compatibility for existing status-based consumers while making runtime-control decisions visible and auditable in benchmark triage outputs.

````

### 2026-03-03_21.17.56-profeedback-relevance-audit

Source:
- `docs/understandings/2026-03-03_21.17.56-profeedback-relevance-audit.md`

Summary:
- Audit of ProFeedback suggestions against current runtime code and 2026-03-03_20.49.14 artifacts.

Preserved source note:

````md
---
summary: "Audit of ProFeedback suggestions against current runtime code and 2026-03-03_20.49.14 artifacts."
read_when:
  - "When deciding whether ProFeedback items are already implemented or still actionable."
  - "When planning the next codex-farm quality/runtime pass after 2026-03-03_20.49.14."
---

# Discovery

Validated `docs/plans/ProFeedback.md` recommendations against current code and latest paired SeaAndSmoke bundle (`2026-03-03_20.49.14`).

# Already implemented

- Pass2 degradation severity + selective pass3 routing metadata is live in `cookimport/llm/codex_farm_orchestrator.py`.
- Outside-span default-to-OTHER guard logic is live in `cookimport/parsing/canonical_line_roles.py`.
- Upload bundle v1 already has fields/hooks for prompt warning aggregate, projection trace, wrong-label full context, preprocess-trace failures, practical F1, cost signal, and candidate-label signal in `scripts/benchmark_cutdown_for_external_ai.py`.

# Still valuable

- Pass3 remains the dominant runtime/tokens cost (`842,348 / 1,354,019` tokens in latest pair), so pass3 ROI work is still high value.
- `candidate_label_signal.available` remains false in latest bundle because `line_role_predictions.jsonl` does not carry candidate labels.
- Latest `run_diagnostics` still reports requested diagnostics as `missing` for codex, even though source artifacts exist to derive several of them.
- Residual confusion buckets (`INSTRUCTION_LINE -> RECIPE_NOTES`, `OTHER -> HOWTO_SECTION`, `OTHER -> RECIPE_NOTES`, `HOWTO_SECTION -> RECIPE_TITLE`) indicate deterministic boundary/routing hygiene still matters.

````

### 2026-03-03_21.25.37-profeedback-plan-rebuild-scope-check

Source:
- `docs/understandings/2026-03-03_21.25.37-profeedback-plan-rebuild-scope-check.md`

Summary:
- ProFeedback plan rebuild check: active plan already matched OG scope and only needed working-copy refresh.

Preserved source note:

````md
---
summary: "ProFeedback plan rebuild check: active plan already matched OG scope and only needed working-copy refresh."
read_when:
  - "When wondering whether docs/plans/ProFeedback.md diverges from OG plan intent."
  - "When resuming ProFeedback work and checking why the latest edit was small."
---

# Discovery

`docs/plans/ProFeedback.md` and `docs/plans/OGplan/ProFeedback.md` were identical at rebuild time. The active plan already captured current actionable scope (pass3 ROI, candidate-label availability, upload-bundle diagnostics).

# Outcome

Rebuild work stayed intentionally small: refresh summary wording, add a new progress checkpoint, and record a new revision note confirming docs/code-context revalidation.

````

### 2026-03-03_21.33.21-profeedback-ogplan-implementation-gap-audit

Source:
- `docs/understandings/2026-03-03_21.33.21-profeedback-ogplan-implementation-gap-audit.md`

Summary:
- Audit finding: ProFeedback OG plan remains partially unimplemented despite related runtime improvements.

Preserved source note:

````md
---
summary: "Audit finding: ProFeedback OG plan remains partially unimplemented despite related runtime improvements."
read_when:
  - "When checking whether docs/plans/OGplan/ProFeedback.md milestones are fully shipped in code."
  - "When reconciling stale upload_bundle_v1 artifacts with current benchmark_cutdown script behavior."
---

# ProFeedback OG Plan vs Code Gap Audit

- Observation: Pass3 soft-gating exists, but pass2-ok rows still always route to pass3 LLM.
  Evidence: `cookimport/llm/codex_farm_orchestrator.py::_should_run_pass3_llm` returns `(True, "pass2_ok")` whenever `state.pass2_status == "ok"`.

- Observation: Candidate-label diagnostics remain unavailable because line-role prediction rows do not emit `candidate_labels`.
  Evidence: `CanonicalLineRolePrediction` has no `candidate_labels` field in `cookimport/parsing/canonical_line_roles.py`, and existing upload bundle analysis reports `candidate_label_signal.available=false`.

- Observation: Upload-bundle diagnostic completeness appears implemented in code but not reflected in older artifacts.
  Evidence: Re-running `scripts/benchmark_cutdown_for_external_ai.py` on the 2026-03-03_20.49.14 SeaAndSmoke run now yields codex `run_diagnostics` statuses of `written` for prompt-warning/projection/wrong-context/preprocess traces, while the checked-in historical `upload_bundle_v1/upload_bundle_index.json` still shows `missing`.

````

## 2026-03-03 docs/tasks consolidation batch (Pro3 + soft gating + ProFeedback OG-gap closure)

### Pro3 transport/fallback/projection hardening (task file `docs/tasks/Pro3.md`)

Source task:
- `docs/tasks/Pro3.md` (no timestamp in filename; mtime aligns with 2026-03-03 afternoon task batch)

Problems captured:
- Mechanical transport loss between pass1-selected span and pass2 payload.
- Fallback anchored on degraded pass2 outputs.
- Outside-span debug rows could inherit unrelated fallback prompt context.

Durable decisions/outcomes preserved:
- Centralized pass2 selection/audit helper with inclusive-end semantics (`codex_farm_transport.py`).
- Kept fail-safe acceptance policy and deterministic fallback fidelity anchored to `state.recipe`.
- Added explicit outside-span statuses without borrowed prompt-row attribution.
- Preserved incoming `within_recipe_span` flags for URN/non-`recipe:<int>` projection paths.

Evidence preserved:
- Task verification transcript includes broad targeted suite pass and `scripts/replay_seaandsmoke_codex_transport.py --all` exact-match replay outcomes.

### 2026-03-03_15.25.18 pass3 schema_v fallback reduction

Source task:
- `docs/tasks/2026-03-03_15.25.18-pass3-schema-v-fallback-reduction.md`

Problem captured:
- Pass3 outputs with legacy `draft_v1` families (missing `schema_v`, pass2-like or schemaorg-like shapes) triggered avoidable fallback.

Decision/outcome preserved:
- Normalize/coerce legacy pass3 `draft_v1` payloads to valid `RecipeDraftV1` before strict validation, without loosening quality gates.

Evidence preserved:
- `pytest tests/llm/test_codex_farm_orchestrator.py -k "legacy_pass3_draft_shape_without_schema_v or pass2_like_pass3_draft_shape_to_draft_v1"` -> `2 passed`.
- `pytest tests/llm/test_codex_farm_orchestrator.py` -> `29 passed`.
- `pytest tests/llm/test_codex_farm_contracts.py` -> `10 passed`.

### 2026-03-03_15.44.46 pass2 page/layout warning-bucket rename

Source task:
- `docs/tasks/2026-03-03_15.44.46-pass2-page-layout-warning-bucket-rename.md`

Problem captured:
- `ocr_or_page_artifact` wording implied OCR-only failures for EPUB-heavy layout/page-marker degradation.

Decision/outcome preserved:
- Runtime emits `warning_bucket:page_or_layout_artifact`; cutdown tooling canonicalizes legacy and new names for backwards-compatible reporting.

Evidence preserved:
- `pytest tests/llm/test_codex_farm_orchestrator.py` passed.
- Targeted/full cutdown test runs in task passed (`tests/bench/test_benchmark_cutdown_for_external_ai.py`).

### 2026-03-03_20.13.22 soft gating, selective pass3 routing, outside-span precision

Source task:
- `docs/tasks/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`

Problems captured:
- Degraded pass2 rows were hard-routed to fallback, increasing fallback churn and pass3/runtime pressure.
- Outside-span narrative lines still drifted into `KNOWLEDGE`/`RECIPE_NOTES` buckets.

Durable decisions/outcomes preserved:
- Added pass2 severity classification (`soft`/`hard`) and additive routing metadata fields/counters in `llm_manifest`.
- Soft-degraded low-risk rows can deterministically promote (`pass3_execution_mode=deterministic`) while hard degradation still fail-closes.
- Outside-span prose defaults tightened toward `OTHER` unless explicit knowledge cues are present.
- Bench cutdown ingestion/reporting updated to carry new routing/severity metadata.

Evidence preserved:
- Targeted suites in task:
  - `tests/llm/test_codex_farm_orchestrator.py`
  - `tests/parsing/test_canonical_line_roles.py`
  - `tests/bench/test_benchmark_cutdown_for_external_ai.py`
- Pending validation explicitly preserved:
  - locked-model paired SeaAndSmoke rerun not yet executed in-task.
  - required speed-suite (`speed-discover/run/compare`) not yet executed in-task.

### 2026-03-03_21.42.59 ProFeedback OG-gap implementation

Source task:
- `docs/tasks/2026-03-03_21.42.59 - profeedback-ogplan-gap-implementation.md`

Problems captured:
- Remaining OG gaps: no pass2-ok utility/skip instrumentation, missing candidate-label propagation, and weak upload-bundle coverage assertions.

Decision/outcome preserved:
- Implemented env-guarded pass2-ok deterministic skip policy (`COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK`).
- Added candidate-label propagation into line-role prediction/joined cutdown paths.
- Expanded upload-bundle tests for candidate-label signal and diagnostics status population.

Evidence preserved:
- Task command result:
  - `python -m pytest tests/llm/test_codex_farm_orchestrator.py tests/parsing/test_canonical_line_roles.py tests/bench/test_cutdown_export_consistency.py tests/bench/test_benchmark_cutdown_for_external_ai.py`
  - `84 passed, 1 warning`.

## 2026-03-03 docs/tasks consolidation batch (ProFeedback rebaseline and implementation closure)

Merged source task file:
- `docs/tasks/ProFeedback.md`

### 2026-03-03_21.17.00 to 22.13.25 ProFeedback follow-up milestones

Source task:
- `docs/tasks/ProFeedback.md`

Problem captured:
- Original ProFeedback narrative mixed already-shipped work with still-open gaps; remaining high-value items were pass3 runtime ROI, candidate-label visibility, and upload-bundle diagnostic completeness.

Decisions/outcomes preserved:
- Rebased ProFeedback into executable milestones tied to current runtime seams rather than re-planning already shipped soft-gating/outside-span work.
- Added pass2-ok utility instrumentation and deterministic skip policy path in orchestrator (`COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK`).
- Propagated candidate-label metadata through line-role predictions and cutdown export surfaces.
- Hardened upload-bundle diagnostic completeness for existing-output runs so codex statuses are derived/written when source artifacts exist.
- Kept upload-bundle-first packaging (`upload_bundle_v1`) instead of introducing a new mandatory starter-pack version.
- Included required speed-regression checks in milestone acceptance path.

Evidence snapshot preserved from task:
- Quality:
  - codex skip-off: `accuracy=0.7798`, `macro_f1=0.5749`
  - codex skip-on: `accuracy=0.7950`, `macro_f1=0.5938`
  - vanilla paired run: `accuracy=0.3966`, `macro_f1=0.3405`
- Runtime ROI:
  - pass3 inputs: `17 -> 1` (skip-off -> skip-on)
  - pass3 token share: `0.5518 -> 0.3494`
- Diagnostics completeness:
  - candidate-label signal available with non-zero rows (`rows_with_candidate_labels=699` in cited codex bundle)
  - codex run_diagnostics statuses for requested artifacts resolved to `written` on fresh bundles.
- Regression safety:
  - targeted suites passed
  - speed compare verdict recorded as `PASS` (`data/golden/bench/speed/comparisons/2026-03-03_22.09.21/`).

Key operational note preserved:
- `labelstudio-benchmark` no longer supports `--compare-vanilla`; paired evidence requires separate vanilla/codex runs.

Anti-loop reminders:
- If old bundles still show missing statuses, regenerate first; stale artifacts can misrepresent current generator behavior.
- If runtime accounting looks empty in single-run upload bundles, inspect prediction-run manifest telemetry fallback before changing orchestrator telemetry emission.
- Treat pass3 ROI tuning and candidate-label visibility as coupled observability/perf work; avoid editing one side without validating the other in bundle outputs.

## 2026-03-04 docs/understandings consolidation batch (ProFeedback audits + codexfarm failure seams)

Merged source notes below are preserved in timestamp order to keep runtime root-cause and audit evidence accessible.
### 2026-03-03_22.21.36-profeedback-ogplan-vs-completed-audit

Source:
- `docs/understandings/2026-03-03_22.21.36-profeedback-ogplan-vs-completed-audit.md`

Summary:
- Audit note: ProFeedback OG plan milestones are implemented; pass3 token-share evidence comes from prediction-run telemetry when standalone upload-bundle call inventory is empty.

Preserved source note:

````md
---
summary: "Audit note: ProFeedback OG plan milestones are implemented; pass3 token-share evidence comes from prediction-run telemetry when standalone upload-bundle call inventory is empty."
read_when:
  - "When validating ProFeedback OG milestone completion against current code and artifacts"
  - "When checking pass3 ROI evidence sources for standalone codex benchmark roots"
---

# ProFeedback OG vs completed audit (code-verified)

- Milestones 1-4 from `docs/plans/OGplan/ProFeedback.md` are implemented in code:
  - pass2-ok pass3 utility + skip policy (`cookimport/llm/codex_farm_orchestrator.py`)
  - candidate-label propagation (`cookimport/parsing/canonical_line_roles.py`, `cookimport/bench/cutdown_export.py`)
  - upload-bundle diagnostic derivation for existing-output roots (`scripts/benchmark_cutdown_for_external_ai.py`)
- Tests covering these behaviors pass in `.venv`:
  - `tests/llm/test_codex_farm_orchestrator.py`
  - `tests/parsing/test_canonical_line_roles.py`
  - `tests/bench/test_benchmark_cutdown_for_external_ai.py`
- Key nuance:
  - OG validation text expected pass3 token-share reduction from upload-bundle call inventory.
  - Current standalone codex benchmark roots can have empty `upload_bundle_index.json -> analysis.call_inventory_runtime` (`call_count=0`), so pass3 token share is computed from `prediction-run/manifest.json -> llm_codex_farm.process_runs.*.telemetry_report.summary.tokens_total`.
  - Completed ExecPlan captures this in discoveries and uses telemetry-derived shares (`0.5518 -> 0.3494`).
````

### 2026-03-03_22.32.51-profeedback-ogplan-audit-refresh

Source:
- `docs/understandings/2026-03-03_22.32.51-profeedback-ogplan-audit-refresh.md`

Summary:
- Refresh audit: ProFeedback OG milestones are implemented; existing evidence bundles may predate runtime-telemetry fallback regeneration.

Preserved source note:

````md
---
summary: "Refresh audit: ProFeedback OG milestones are implemented; existing evidence bundles may predate runtime-telemetry fallback regeneration."
read_when:
  - "When re-auditing docs/plans/OGplan/ProFeedback.md vs current code"
  - "When validating pass3 token-share ROI evidence in upload_bundle_v1 for standalone codex runs"
---

# ProFeedback OG audit refresh

- OG Milestones 1-4 are code-complete in current runtime/tests:
  - pass2-ok pass3 utility + env-guarded skip policy in `cookimport/llm/codex_farm_orchestrator.py`
  - candidate-label propagation in `cookimport/parsing/canonical_line_roles.py` and `cookimport/bench/cutdown_export.py`
  - existing-output upload-bundle diagnostic derivation in `scripts/benchmark_cutdown_for_external_ai.py`
- Milestone 5 validation artifacts exist for vanilla/codex/codex-pass3skip runs and speed compare PASS.
- Important evidence nuance:
  - historical upload bundles under `2026-03-03_22.04.09_*` and `2026-03-03_22.09.35_*` show `analysis.call_inventory_runtime.summary.call_count=0` and null token shares.
  - Current code now backfills runtime/token shares from `prediction-run/manifest.json` telemetry when call inventory rows are empty; stale bundles need regeneration to show these fields in `upload_bundle_index.json`.
- Targeted suites pass in `.venv`:
  - `tests/llm/test_codex_farm_orchestrator.py`
  - `tests/parsing/test_canonical_line_roles.py`
  - `tests/bench/test_benchmark_cutdown_for_external_ai.py`
````

### 2026-03-03_23.08.45-saltfat-codex-single-offline-collapse

Source:
- `docs/understandings/2026-03-03_23.08.45-saltfat-codex-single-offline-collapse.md`

Summary:
- SaltFat cutdown codex single-offline collapse: atomic split fragmentation + strict chunk parse fallback + outside-span title/howto rule overfire.

Preserved source note:

````md
---
summary: "SaltFat cutdown codex single-offline collapse: atomic split fragmentation + strict chunk parse fallback + outside-span title/howto rule overfire."
read_when:
  - "When codex single-offline quality collapses versus vanilla on cookbook-style narrative/front-matter sources."
  - "When line-role prompt parses fail with label_outside_allowlist or missing_atomic_index_rows and fallback takes over."
---

- Run analyzed: `data/golden/benchmark-vs-golden/2026-03-03_22.48.38` (`saltfatacidheatcutdown`).
- Regression is line-role labeling, not extraction/alignment: canonical char coverage stayed high (`vanilla 0.9937`, `codex 0.9926`) while strict accuracy dropped `0.5730 -> 0.3302`.
- Codex variant enabled `atomic_block_splitter=atomic-v1` + `line_role_pipeline=codex-line-role-v1`; vanilla used `atomic_block_splitter=off` + `line_role_pipeline=off`.
- Atomic split produced fragmented prose lines (many start with `to ...` / `for ...`) that bias heuristics and candidate allowlists away from `KNOWLEDGE`.
- Prompt parse strictness failed whole 40-line chunks when one row violated allowlist or rows were missing. This run had 7 failed chunks (`parsed_0003/0006/0008/0012/0013/0016/0017`) and forced fallback on 280 lines.
- Fallback rows were high-error (`190/280` wrong in `joined_line_table`), especially on `KNOWLEDGE` gold lines.
- Rule overfire outside recipe spans drove large false positives: `RECIPE_TITLE title_like|outside_recipe_span` (237 rule rows) and `HOWTO_SECTION howto_heading` (171 rule rows total; eval shows 100 false-positive HOWTO lines with gold total 0).
- Biggest metric shifts versus vanilla:
  - `RECIPE_TITLE`: `pred_total 20 -> 257`, precision `1.0 -> 0.1206`, F1 `0.7273 -> 0.2123`.
  - `KNOWLEDGE`: recall `0.8000 -> 0.2218`, `pred_total 897 -> 178`, F1 `0.6381 -> 0.3415`.
  - `INSTRUCTION_LINE`: `pred_total 61 -> 275`, precision `0.4754 -> 0.1709`, F1 `0.4640 -> 0.2773`.
````

### 2026-03-03_23.48.18-feedback-ogplan-code-audit-gaps

Source:
- `docs/understandings/2026-03-03_23.48.18-feedback-ogplan-code-audit-gaps.md`

Summary:
- Audit result: feedback OG plan is mostly implemented, but deterministic line-role refinements and Milestone-5 validation remain partially incomplete.

Preserved source note:

````md
---
summary: "Audit result: feedback OG plan is mostly implemented, but deterministic line-role refinements and Milestone-5 validation remain partially incomplete."
read_when:
  - "When reconciling docs/plans/OGplan/feedbackOG.md against current code behavior."
  - "When deciding what remains before declaring docs/plans/feedback.md fully complete."
---

- Milestone 4 (starter-pack/upload-bundle non-CSV triage surfaces) is implemented and backed by tests. `scripts/benchmark_cutdown_for_external_ai.py` writes `starter_pack_v1/01_recipe_triage.jsonl`, emits blame/config/low-confidence/parity artifacts, and still reads legacy CSV for old roots.
- Milestone 2 is only partially aligned with the OG intent:
  - No explicit post-classification demotion path exists for unsupported `TIME_LINE` predictions in `cookimport/parsing/canonical_line_roles.py`; `TIME_LINE` appears in deterministic labeling, but there is no sanitizer branch that remaps bad `TIME_LINE` outputs to `INSTRUCTION_LINE`.
  - No explicit ingredient-neighbor rescue branch was found in `canonical_line_roles.py` for short split quantity/name fragments based on adjacent ingredient-dominant context.
- Milestone 3 selective escalation exists, but pass2-ok skip policy is env-guarded (`COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK`) and off by default; this means broad pass3 invocation remains the default unless explicitly enabled.
- Milestone 5 validation is still incomplete as documented in `docs/plans/feedback.md`: fresh authenticated codex rerun and speed-regression compare were not completed in this cycle.
````

### 2026-03-03_23.50.30-codex-farm-no-last-agent-message-recovery-seam

Source:
- `docs/understandings/2026-03-03_23.50.30-codex-farm-no-last-agent-message-recovery-seam.md`

Summary:
- Codex-farm runner seam for recovering from no-last-agent-message chunk failures without aborting full pass runs.

Preserved source note:

````md
---
summary: "Codex-farm runner seam for recovering from no-last-agent-message chunk failures without aborting full pass runs."
read_when:
  - "When codex-farm exits non-zero with 'no last agent message' during benchmark or stage runs."
  - "When deciding whether runner failures should be hard-stop or partial-output recoverable."
---

- Failure source is `SubprocessCodexFarmRunner.run_pipeline(...)` in `cookimport/llm/codex_farm_runner.py`, where non-zero `process` exits were previously always raised as `CodexFarmRunnerError`.
- For `no last agent message` signatures (and telemetry categories limited to `nonzero_exit_no_payload`), hard-failing at runner level prevents orchestrator-level per-bundle fallback from executing.
- Safe recovery seam is runner-level: continue with warning + returned process metadata, then let orchestrators mark missing output bundles on affected recipe/chunk rows.
- This keeps broad failure behavior strict while downgrading only the known transient signature.
````

### 2026-03-03_23.53.16-feedback-og-gap-closure-routing-and-line-role

Source:
- `docs/understandings/2026-03-03_23.53.16-feedback-og-gap-closure-routing-and-line-role.md`

Summary:
- Gap-closure implementation note: canonical line-role sanitizer adds TIME_LINE demotion + neighbor ingredient rescue; pass2-ok selective pass3 skip is now default-on with env opt-out.

Preserved source note:

````md
---
summary: "Gap-closure implementation note: canonical line-role sanitizer adds TIME_LINE demotion + neighbor ingredient rescue; pass2-ok selective pass3 skip is now default-on with env opt-out."
read_when:
  - "When reconciling feedback OG-plan gap closure behavior in parsing and codex pass3 routing."
  - "When debugging why pass2-ok rows now skip pass3 unless explicitly disabled."
---

- `cookimport/parsing/canonical_line_roles.py` now enforces two extra post-label sanitizers:
  - demote non-primary `TIME_LINE` predictions to `INSTRUCTION_LINE` (or `OTHER` outside recipe spans),
  - rescue short ingredient fragments to `INGREDIENT_LINE` when adjacent ingredient-dominant neighbor context supports a split quantity/name pattern.
- `cookimport/llm/codex_farm_orchestrator.py` now treats pass2-ok deterministic pass3 skip as default behavior; `COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK=0|false|no|off` explicitly disables skip.
- Added tests:
  - `tests/parsing/test_canonical_line_roles.py` for codex `TIME_LINE` demotion and neighbor fragment rescue.
  - `tests/llm/test_codex_farm_orchestrator.py` for low-risk pass2-ok behavior when skip policy is explicitly disabled.
````

### 2026-03-03_23.55.30-codex-no-last-agent-message-content-filter-root-cause

Source:
- `docs/understandings/2026-03-03_23.55.30-codex-no-last-agent-message-content-filter-root-cause.md`

Summary:
- Root cause of codex-farm `no last agent message` on DinnerFor2 pass2: provider `content_filter` stream failures prevent final assistant message emission.

Preserved source note:

````md
---
summary: "Root cause of codex-farm `no last agent message` on DinnerFor2 pass2: provider `content_filter` stream failures prevent final assistant message emission."
read_when:
  - "When codex-farm task errors show `Warning: no last agent message; wrote empty content ...`."
  - "When pass2/pass3 fail with `nonzero_exit_no_payload` and retries do not recover."
---

- Run analyzed: `run_id=667a1d418bd8494d99d6e1184ed6630f` (`recipe.schemaorg.v1`, `dinnerfor2cutdown`, pass2).
- Failed tasks: `534901a74c114a1e962f6dd215074380` and `26a36dafd2e74a1db7c4fab646052f56`, each failed 3 attempts.
- Forensics metadata marks both as `failure_stage=codex_exec`, `failure_category=runtime_nonzero_no_payload` with only stderr tail `Warning: no last agent message...`.
- Usage telemetry rows for failed attempts include event types `thread.started`, `turn.started`, `item.completed`, `error`, `turn.failed`.
- Replaying the exact saved prompts/schemas via raw `codex exec --json` reproduced the failure and exposed hidden event error text:
  - `stream disconnected before completion: Incomplete response returned, reason: content_filter`
  - repeated reconnect attempts, then `turn.failed`.
- Conclusion: `no last agent message` is the surface symptom; root cause is provider-side content filtering interrupting stream completion before a final assistant message can be written to `--output-last-message`.
- Secondary seam: CodexFarm currently drops JSONL event error bodies from `stdout_tail` (`_parse_jsonl_events` strips event lines), so caller-visible errors can collapse to generic `no last agent message` unless raw stdout events are inspected.
````

### 2026-03-03_23.58.37-single-offline-codexfarm-full-text-block-guard

Source:
- `docs/understandings/2026-03-03_23.58.37-single-offline-codexfarm-full-text-block-guard.md`

Summary:
- Single-offline codexfarm variant can fail immediately when cached conversion payload has `full_text` lines/text but no `blocks` list.

Preserved source note:

````md
---
summary: "Single-offline codexfarm variant can fail immediately when cached conversion payload has `full_text` lines/text but no `blocks` list."
read_when:
  - "When single-offline benchmark logs `Cannot run codex-farm recipe pipeline: no full_text blocks available.`"
  - "When diagnosing why vanilla succeeds but codexfarm fails in paired single-offline runs."
---

- The codexfarm recipe orchestrator requires a `full_text` artifact containing `content.blocks[*]`; if none are found it raises `Cannot run codex-farm recipe pipeline: no full_text blocks available.`
- In this `hix_written` run, the shared split-cache entry contained `conversion_result.rawArtifacts` where `locationId=full_text` had only `content.lines` + `content.text` (`has_blocks=false`).
- Vanilla succeeded because it does not execute codexfarm; codexfarm reused the same split-cache conversion payload and hit the guard immediately.
- Single-offline split cache is intentionally shared between vanilla and codexfarm (key excludes codexfarm-specific knobs), so this behavior is expected with current contracts.
````

### 2026-03-04_00.01.53-codexfarm-content-filter-terminal-classification

Source:
- `docs/understandings/2026-03-04_00.01.53-codexfarm-content-filter-terminal-classification.md`

Summary:
- [missing frontmatter summary]

Preserved source note:

````md
# CodexFarm fix: surface provider content_filter and stop futile retries

Date: 2026-03-04

What changed:
- `src/codex_farm/codex_exec.py` now parses JSONL `error` and `turn.failed` events and appends those details to `stderr_tail` when present.
- `src/codex_farm/worker.py` now detects `content_filter` in failure text and classifies it as `failure_category="content_filter"`.
- `content_filter` is treated as terminal in retry logic, so workers stop retrying attempts that cannot succeed.

Why:
- The previous surfaced message (`no last agent message`) was a downstream symptom.
- Actual provider-side cause (`reason: content_filter`) was present in JSONL events but not surfaced in worker-visible failure text.
````

### 2026-03-04_00.03.20-feedback-ogplan-vs-code-audit-refresh

Source:
- `docs/understandings/2026-03-04_00.03.20-feedback-ogplan-vs-code-audit-refresh.md`

Summary:
- Refresh audit: OG feedback plan is mostly implemented, with remaining gaps in deterministic title/yield constraints and Milestone-5 validation evidence.

Preserved source note:

````md
---
summary: "Refresh audit: OG feedback plan is mostly implemented, with remaining gaps in deterministic title/yield constraints and Milestone-5 validation evidence."
read_when:
  - "When reconciling docs/plans/OGplan/feedbackOG.md against current code and docs/plans/feedback.md."
  - "When deciding what still remains before calling the feedback ExecPlan fully complete."
---

- Starter-pack/upload-bundle Milestone 4 is implemented in code: `scripts/benchmark_cutdown_for_external_ai.py` writes `starter_pack_v1/01_recipe_triage.jsonl`, emits triage packet + net-error blame + config metadata + low-confidence packet + baseline parity, and still falls back to `01_recipe_triage.csv` for legacy roots.
- Selective pass3 routing (Milestone 3 core) is implemented and test-covered in `cookimport/llm/codex_farm_orchestrator.py` and `tests/llm/test_codex_farm_orchestrator.py`; pass2-ok low-risk rows can deterministically skip pass3 by default.
- Milestone 2 is only partially aligned with OG wording:
  - `YIELD_LINE` gating is lexical-prefix based (`_is_yield_line` / `yield_prefix`) with ingredient rescue, but there is no explicit short-header-length/shape gate dedicated to yield lines.
  - HOWTO uses short-header + neighbor evidence (`_looks_subsection_heading_context`), but RECIPE_TITLE classification still relies on text heuristics and does not explicitly require next-line evidence.
- Milestone 5 remains incomplete in the ExecPlan itself (`docs/plans/feedback.md`): fresh authenticated codex paired rerun and speed-regression compare evidence are still open.
````

### 2026-03-04_00.03.32-codexfarm-full-text-lines-fallback

Source:
- `docs/understandings/2026-03-04_00.03.32-codexfarm-full-text-lines-fallback.md`

Summary:
- Codex-farm recipe pass now synthesizes minimal full-text blocks from `full_text.lines` when `full_text.blocks` is missing.

Preserved source note:

````md
---
summary: "Codex-farm recipe pass now synthesizes minimal full-text blocks from `full_text.lines` when `full_text.blocks` is missing."
read_when:
  - "When codexfarm recipe pass fails due to missing full_text blocks on benchmark split-cache reuse."
  - "When debugging Label Studio prediction payloads that carry line-form full_text artifacts only."
---

- `run_codex_farm_recipe_pipeline` still prefers `full_text.blocks` exactly as before.
- If `full_text.blocks` is missing or empty, `_extract_full_blocks` now falls back to `full_text.lines` and converts each `{index, text}` line into a minimal block payload.
- This keeps codexfarm pass1/pass2/pass3 runnable for legacy/split-cache payloads where full text was persisted as lines-only artifacts.
- Behavior remains fail-closed when neither block nor line rows provide usable indexed entries.
````

Anti-loop reminders from this consolidation:
- Before reopening OG feedback gaps, compare against current code paths and regenerated artifacts; several previously "missing" items were stale-output artifacts.
- For codexfarm nonzero/no-message failures, check runner recovery/content-filter classifications before changing model or prompt contracts.
- For full_text block absence failures, preserve the line-to-block synthesis fallback path unless replacement proves equivalent on benchmark replay evidence.


### 2026-03-04 understandings consolidation (profile settings vs pass3 skip runtime policy)

Merged source note:
- `docs/understandings/2026-03-04_01.06.17-top-tier-profile-vs-pass3-skip-env-boundary.md`

Problem captured:
- Operators can misattribute pass3 call-volume changes to profile selection even when profile payloads are unchanged.

Durable decision:
- Keep a strict boundary between:
  - run-settings profile control plane (pipeline/splitter knobs), and
  - codex orchestrator runtime policy plane (pass3 pass2-ok skip env/default policy).

Anti-loop reminder:
- Debug pass3 skip behavior in orchestrator env/default evaluation first; do not add pseudo pass3-skip keys to profile payloads unless the architecture intentionally changes.

### 2026-03-04 understandings merge ledger (pass policy knobs + benchmark control-plane boundary)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.21.40-pass3-skip-settings-first-qualitysuite-surface.md`
- `docs/understandings/2026-03-04_01.24.50-orchestrator-env-benchmark-control-plane.md`
- `docs/understandings/2026-03-04_01.31.25-top-tier-pass3-skip-profile-baseline-boundary.md`
- `docs/understandings/2026-03-04_01.32.00-codexfarm-policy-knobs-settings-only.md`
- `docs/understandings/2026-03-04_01.35.09-pass1-pattern-hints-top-tier-baseline-boundary.md`

#### 2026-03-04_01.21.40 pass3 skip moved to settings-first tuning surface
- `codex_farm_pass3_skip_pass2_ok` was promoted to RunSettings and propagated through stage/bench/labelstudio adapters.
- This made QualitySuite/profile tuning direct and inspectable instead of hidden inside orchestrator internals.

#### 2026-03-04_01.24.50 orchestrator/env shorthand and benchmark control plane split
- `orchestrator/env` is documentation shorthand; no standalone module exists.
- Benchmark runtime env controls (parallelism/executor/cache/ETA) remain mostly in bench runner surfaces, while pass policy routing remains in orchestrator.

#### 2026-03-04_01.31.25 top-tier baseline boundary for pass3 skip
- Built-in top-tier baselines explicitly pin `codex_farm_pass3_skip_pass2_ok=true`.
- Winner harmonization preserves winner-specific skip tuning values and does not overwrite them.

#### 2026-03-04_01.32.00 policy knobs settings-only boundary
- Pass-routing knobs (`codex_farm_pass1_pattern_hints_enabled`, `codex_farm_pass3_skip_pass2_ok`) now live in RunSettings only.
- Older orchestrator env policy toggles for these controls were retired.

#### 2026-03-04_01.35.09 top-tier baseline boundary for pass1 hints
- Built-in codex and vanilla baselines explicitly pin `codex_farm_pass1_pattern_hints_enabled=false`.
- Winner harmonization does not overwrite winner-provided pattern-hints value.

Anti-loop reminders:
- If pass1/pass3 behavior drifts, inspect resolved settings payload first; do not re-add implicit env toggles to orchestrator policy logic.
- When benchmarking, keep benchmark runner env controls distinct from pass-policy knobs to avoid mixed control-plane debugging.

## 2026-03-04 docs/understandings consolidation (Profeedback safety gates + pass1 eligibility hardening)

### 2026-03-04_09.59.00 Profeedback ExecPlan code-gap scan

Source:
- `docs/understandings/2026-03-04_09.59.00-profeedback-execplan-code-gap-scan.md`

Problem captured:
- Needed code-grounded triage of OG Profeedback plan ideas before writing the executable plan.

Durable findings:
- Pass3 low-quality/empty fallback was already implemented in orchestrator runtime.
- Canonical line-role prompt negatives + deterministic outside-span sanitization were already in place.
- Main unresolved runtime gaps at scan time:
  - no runtime do-no-harm acceptance arbitration for codex line-role overrides,
  - no structural evidence floor in pass1 eligibility before pass2.

### 2026-03-04_10.28.11 Profeedback2 vs OG ExecPlan coverage map

Source:
- `docs/understandings/2026-03-04_10.28.11-profeedback2-vs-execplan-coverage-map.md`

Problem captured:
- Needed deduped map between `Profeedback2.md` recommendations and existing OG Profeedback milestones.

Durable findings:
- Milestones 1-5 already covered core safety asks: do-no-harm gate, outside-span containment, inside-span-first low-confidence behavior, pass1 eligibility, pass2 pruning, ablation matrix.
- Partial representation noted for explicit chapter/page metadata usage in milestone wording.
- Intentional out-of-scope items captured: telemetry naming cleanup and extra `empty_mapping` finalizer changes.

### 2026-03-04_10.31.54 Profeedback line-role + pass1 gate implementation findings

Source:
- `docs/understandings/2026-03-04_10.31.54-profeedback-line-role-pass1-gates-implementation-findings.md`

Problem captured:
- Needed durable record of what actually landed for runtime do-no-harm and pass1 eligibility.

Durable outcomes:
- `cookimport/parsing/canonical_line_roles.py` now runs codex do-no-harm arbitration after sanitization.
- Outside-span policy tightened:
  - `HOWTO_SECTION` hard-denied outside spans,
  - outside-span title/variant requires compact-heading shape + nearby structural evidence,
  - outside-span instruction/ingredient requires local evidence or is downgraded.
- Outside-span low-confidence codex escalation is default-off.
- Line-role codex runs now emit:
  - `line-role-pipeline/do_no_harm_diagnostics.json`
  - `line-role-pipeline/do_no_harm_changed_rows.jsonl`
- `cookimport/llm/codex_farm_orchestrator.py` pass1 eligibility score bands are active (`proceed`/`clamp`/`drop`) with persisted eligibility telemetry fields.

Validation anchors preserved:
- `tests/parsing/test_canonical_line_roles.py`
- `tests/llm/test_codex_farm_orchestrator.py`
- `tests/labelstudio/test_canonical_line_projection.py`

### 2026-03-04_11.11.52 pass1 eligibility chapter/page negative evidence

Source:
- `docs/understandings/2026-03-04_11.11.52-pass1-eligibility-chapter-page-negative-evidence.md`

Problem captured:
- Chapter/page metadata was previously implicit in prose-dominance behavior and not auditable as explicit eligibility signal.

Durable outcomes:
- Pass1 eligibility now consumes chapter/page metadata as explicit negative evidence.
- Added score component telemetry fields:
  - `chapter_page_negative_evidence_high`
  - `chapter_page_negative_hits`
  - `chapter_page_negative_score`
- Added reason tag: `chapter_page_metadata_negative_evidence_high`.
- Test anchor:
  - `tests/llm/test_codex_farm_orchestrator.py::test_orchestrator_pass1_eligibility_uses_chapter_page_negative_metadata`

### 2026-03-04_11.14.01 Profeedback OG vs completed/code gap audit

Source:
- `docs/understandings/2026-03-04_11.14.01-profeedback-og-vs-completed-code-gap-audit.md`

Problem captured:
- Reconciled OG Profeedback plan intent against completed execplan claims and live code/tests.

Gap-state findings captured at this point:
- OG milestone wording required explicit chapter/page metadata negative evidence and kept Milestone 3 partial, while completed plan still marked it complete.
- Pass1 eligibility test failed at this time because instruction-verb detection missed `toast`, causing `drop` vs expected `clamp`.
- `labelstudio-benchmark compare` accepted only all-method roots at this time, not run-level `eval_report.json` paths.
- Milestone-5 full-stack codex acceptance remained partially unmet due auth-constrained fallback-mode runs.

Anti-loop note:
- Treat this as timestamped midpoint evidence. Follow-up compare-root + `toast` fix landed in later docs (`2026-03-04_11.33.00`) and should be checked before reopening these exact failure threads.

## 2026-03-05 to 2026-03-06 migrated understanding ledger (Codex decision, telemetry, prompt-budget seams)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-05_22.08.22-hidden-line-role-token-estimate.md`
- `docs/understandings/2026-03-05_22.12.11-hidden-line-role-billing-gap.md`
- `docs/understandings/2026-03-05_22.24.41-problem-1-safe-defaults-context.md`
- `docs/understandings/2026-03-05_22.25.41-line-role-telemetry-gap.md`
- `docs/understandings/2026-03-05_22.43.32-codexfarm-explicit-decision-compromise.md`
- `docs/understandings/2026-03-05_23.01.12-token-reduction-local-seams.md`
- `docs/understandings/2026-03-04_21.10.10-codexfarm-thinking-trace-surface-map.md`
- `docs/understandings/2026-03-04_21.19.48-prompt-sample-thinking-trace-section.md`
- `docs/understandings/2026-03-05_23.06.10-codexfarm-reasoning-trace-upstream-dependency.md`
- `docs/understandings/2026-03-05_23.06.16-line-role-prompt-provenance-seams.md`
- `docs/understandings/2026-03-05_23.09.39-profixes-local-context-seams.md`
- `docs/understandings/2026-03-05_23.12.00-execplan-token-reduction-shape.md`
- `docs/understandings/2026-03-05_23.51.27-token-reduction-implementation-seams.md`
- `docs/understandings/2026-03-05_23.28.00-codex-decision-current-architecture.md`
- `docs/understandings/2026-03-05_23.58.30-codex-decision-implementation-seams.md`
- `docs/understandings/2026-03-06_00.20.00-codex-decision-review-seams.md`

Problem cluster captured:
- Codex policy, telemetry, and prompt-budget work was drifting across plans, runtime helpers, analytics labels, and follow-up tooling. The main risk was treating one layer as the whole system and then fixing the wrong seam.

Durable decisions and findings:
- Hidden line-role usage was real enough to matter, but repo-local prompt-byte estimates are only lower-to-mid billing bounds. They prove missing telemetry, not exact account truth.
- The smallest truthful telemetry fix was to persist line-role usage at the source. That produced `prediction-run/line-role-pipeline/telemetry_summary.json`; downstream reporting should aggregate it instead of inferring spend from prompt bytes forever.
- Safe-default work had to flip all three live-Codex knobs together (`llm_recipe_pipeline`, `line_role_pipeline`, `atomic_block_splitter`). Partial default cleanup would still leave surprise Codex surfaces active.
- The practical repo compromise for Codex safety is one shared decision layer that makes silent Codex impossible:
  - command-boundary validation,
  - explicit decision metadata in manifests,
  - shared runtime classification reused by analytics.
- Current architecture must be read as three aligned layers, not one profile switch:
  - interactive top-tier family,
  - paired benchmark variant contract,
  - analytics/runtime classification.
- `cookimport/config/codex_decision.py` became the shipped seam because it can sit below interactive menus and above artifact/report consumers at the same time.
- Prompt-budget reduction work should target actual local duplication:
  - pass2 still carries duplicated evidence payloads,
  - pass3 duplication is now mostly structured-content overlap,
  - line-role already has local telemetry, so the missing artifact is unified prompt-budget reporting rather than new capture plumbing,
  - `prediction-run/prompt_budget_summary.json` is the repo-owned merge point because prediction-run generation already has both codex-farm pass telemetry and line-role telemetry in hand.
- For provenance/follow-up work, line-role prompt truth lives in `prediction-run/line-role-pipeline/prompts/*.txt|*.json` plus `extracted_archive.json`, not in recipe `full_prompt_log.jsonl`.
- Prompt-sample export now records trace metadata and reasoning excerpts when they exist, but zero-count reasoning traces should be treated as upstream data availability, not exporter failure.
- Missing prompt-sample thinking traces are usually upstream trace-classification failures, not recipeimport exporter bugs. If `.trace.json` has zero reasoning events, fix CodexFarm capture first.
- The ProFixes and token-reduction plans had to be rewritten against real repo seams (`RunSettings`, codex decision, labelstudio ingest, CLI helpers, existing line-role guardrails) rather than inventing a second config/orchestrator stack.

Open risks retained:
- `build_run_settings(...)` was a historically dangerous bypass because constructor/helper defaults can drift from `RunSettings()` even when the base model is safe.
- Review pass found two runtime traps worth keeping visible:
  - `labelstudio_benchmark(...)` had a variable-name mismatch around non-plan decision metadata,
  - `labelstudio-import --prelabel` is a distinct Codex-backed path and can bypass recipe/line-role decision accounting if policy work forgets to review it.

Anti-loop notes:
- If a run looks mysteriously Codex-backed, inspect decision metadata and classifier outputs before adding another approval flag.
- If token totals disagree with local prompt logs, remember prompt bytes are evidence of hidden work, not a perfect replacement for real telemetry.

## 2026-03-04 to 2026-03-06 docs/tasks consolidation batch (reasoning traces, safe defaults, telemetry, and decision policy)

### 2026-03-04_22.15.00 reasoning-trace capture restoration

Source task:
- `docs/tasks/2026-03-04_22.15.00-fix-codexfarm-reasoning-trace-capture.md`

Problem captured:
- CodexFarm-backed prompt samples were showing `_No thinking trace captured for this sample._` even when upstream runs should have had reasoning traces.

Durable outcome:
- Recipeimport now consumes restored nested reasoning capture from CodexFarm so prompt-sample artifacts can show real trace excerpts when upstream data exists.

Anti-loop note:
- If prompt samples still show zero traces, inspect upstream trace-classification/capture artifacts before rewriting markdown exporters.

### 2026-03-05_22.24.41 safe deterministic shared defaults

Source task:
- `docs/tasks/2026-03-05_22.24.41-fix-safe-deterministic-defaults.md`

Problem captured:
- Shared defaults still resolved to live Codex paths, so generic CLI and helper flows could become Codex-backed without explicit intent.

Durable outcomes:
- `RunSettings()` now resolves to deterministic `off/off/off`.
- `_load_settings()` and generic CLI default-loading were aligned to the same safe posture.
- Explicit codex-enabled benchmark/profile variants were preserved as opt-in paths rather than ambient defaults.

Evidence retained from task:
- `source .venv/bin/activate && pytest tests/llm/test_run_settings.py tests/cli/test_cli_output_structure_fast.py -q`
- Result: exit code `0`

Anti-loop note:
- If a generic flow becomes Codex-on again, inspect defaults and helper construction before blaming the low-level `COOKIMPORT_ALLOW_LLM` kill switch.

### 2026-03-05_22.25.41 line-role token telemetry gap

Source task:
- `docs/tasks/2026-03-05_22.25.41-fix-line-role-token-telemetry-gap.md`

Problem captured:
- Canonical line-role runs could spend Codex tokens while leaving benchmark history token columns blank because line-role prompt calls did not persist usage telemetry.

Durable outcomes:
- `canonical_line_roles.py` now tracks usage for line-role Codex prompts and includes retry attempts in totals.
- `prediction-run/line-role-pipeline/telemetry_summary.json` became the durable artifact.
- Prediction manifests, run manifests, analytics perf report collection, and dashboard collection now merge line-role telemetry with codex-farm telemetry.

Anti-loop note:
- If token totals are missing on a line-role run, inspect line-role telemetry artifact generation first; do not fall back immediately to prompt-byte estimation.

### 2026-03-05_22.43.31 to 2026-03-06_00.35.00 human-owned Codex decision boundary

Source task:
- `docs/tasks/2026-03-05_22.43.31-human-owned-codexfarm-decision-boundary.md`

Problem captured:
- The real repo problem was not “perfect human-only security”; it was silent or ambiguous Codex activation spread across helpers, benchmarks, CLI presets, and prelabel paths.

Durable outcomes:
- Added shared decision/policy layer in `cookimport/config/codex_decision.py`.
- Routed interactive top-tier profile patching, benchmark baseline/codex helpers, and command-context validation through that shared layer.
- Removed stale Codex-on helper defaults from `build_run_settings(...)`.
- Persisted Codex decision metadata into stage summaries, Label Studio manifests, and speed/quality benchmark artifacts.
- Corrected follow-up gaps:
  - benchmark manifest annotation now distinguishes command-decision metadata from execution-policy metadata,
  - Label Studio prelabel is explicitly classified as the `prelabel` Codex surface and requires explicit approval.

Evidence retained from task:
- Regression coverage added for safe defaults, direct command validation, import entrypoint forwarding, analytics deterministic-vs-Codex classification, benchmark manifest metadata, and prelabel-only approval.

Anti-loop notes:
- If a run uses Codex “mysteriously,” inspect decision metadata first.
- If prelabel starts bypassing approval again, treat it as decision-boundary regression, not a Label Studio-only quirk.
