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

### 2026-02-28_01.58.55 Oracle browser login/session blocker

Source: `docs/understandings/2026-02-28_01.58.55-oracle-browser-login-session-blocker.md`

Problems captured:
- Browser-run Oracle failures with chrome disconnect/window-close errors.
- Immediate filesystem failures from unwritable default `~/.oracle/sessions/...` paths in Codex sandbox contexts.

Durable mitigations preserved:
- Wrapper defaults now target writable Oracle-home paths under `/home/mcnal/.local/share/oracle`.
- Wrappers create required dirs up front and auto-fallback to `/tmp/oracle-home-$USER` if requested paths are unwritable.
- Legacy `~/.oracle` env overrides are ignored by wrappers to avoid regressing into permission failures.
- Wrapper flow includes one-time login helper (`chromium-chatgpt-login`) before browser-headless runs.

Anti-loop note:
- If Oracle browser runs regress, verify auth/session-path health before changing prompt bundles or model ids.

### 2026-02-28_03.17.29 Codex Farm opt-in command pattern

Source: `docs/understandings/2026-02-28_03.17.29-codex-farm-opt-in-command-pattern.md`

Problem captured:
- Need command-level Codex Farm access without changing deterministic default runtime policy.

Durable pattern preserved:
- Keep `llm_recipe_pipeline` default `off` globally.
- Enable Codex Farm only via explicit command/profile selection.
- Prefer absolute `codex_farm_cmd` in run settings/overrides to avoid PATH-dependent failures.

### 2026-02-28_03.19.05 Oracle gpt-5.2-thinking browser blocker

Source: `docs/understandings/2026-02-28_03.19.05-oracle-gpt52-thinking-browser-blocker.md`

Context preserved:
- Attempted Oracle review against `docs/reports/2026-02-28_01.51.16-thefoodlab-all-method-hotspot-report.md` with mapped code attachments.

Findings preserved:
- Dry-run bundle packaging succeeded.
- Browser runs either stalled indefinitely in running state or failed with chrome-window-close errors.
- No API fallback path was available because `OPENAI_API_KEY` was unset.
- Re-login helper could time out without establishing usable session auth in this sandbox.

Durable implication:
- In this environment, the blocker is browser/auth/session execution, not prompt assembly or file selection.

### 2026-02-28_03.19.48 interactive Codex Farm gate and launcher

Source: `docs/understandings/2026-02-28_03.19.48-interactive-codex-farm-gate-and-launcher.md`

Findings preserved:
- Interactive `cookimport` already routes through run-settings `llm_recipe_pipeline` selection; no special separate interactive-only Codex Farm code path is required.
- Historical note: this finding predated ungated recipe normalization and is now superseded by the 2026-02-28_04.05.00 change.

Durable pattern:
- Use a dedicated launcher (`scripts/interactive-with-codex-farm.sh`) for opt-in sessions so default interactive behavior stays unchanged/off.

## 2026-02-28 migrated understanding ledger (03:47-04:01 LLM batch)

### 2026-02-28_03.47.42 Oracle codex-farm prompt tightening priorities

Source: `docs/understandings/2026-02-28_03.47.42-oracle-codex-farm-prompt-tightening-priorities.md`

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
