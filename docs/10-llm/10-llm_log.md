---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Use this file for LLM debugging history that still applies to the current codebase.

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
