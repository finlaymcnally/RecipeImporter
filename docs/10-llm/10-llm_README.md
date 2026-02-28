---
summary: "Current LLM integration boundaries for codex-farm in stage, prediction-run, and tag flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging pass4 knowledge or pass5 tag artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is limited and optional.

## Runtime surface

Settings and entrypoints:

- `cookimport/config/run_settings.py` (canonical settings and UI choices)
- `cookimport/cli.py` (stage + benchmark + Label Studio command normalization)
- `cookimport/entrypoint.py` (saved settings -> stage defaults pass-through)
- `cookimport/labelstudio/ingest.py` (prediction-run generation + recipe-pass normalization)

Stage execution paths:

- `cookimport/cli_worker.py` (single-file stage path recipe/pass4 execution)
- `cookimport/cli.py` (`_merge_split_jobs` split-merge stage path recipe/pass4 execution)
- `cookimport/cli.py` (`run_stage_tagging_pass` trigger for pass5 after stage writes)
- `cookimport/staging/writer.py` (stage block predictions writer receives pass4 snippet path)
- `cookimport/staging/stage_block_predictions.py` (uses knowledge snippets for stage evidence labeling)

Recipe codex-farm pass modules:

- `cookimport/llm/codex_farm_orchestrator.py` (pass1/pass2/pass3 orchestration)
- `cookimport/llm/codex_farm_contracts.py` (strict pass1/2/3 bundle contracts)
- `cookimport/llm/codex_farm_ids.py` (stable slug/id/bundle filename helpers)
- `cookimport/llm/codex_farm_runner.py` (subprocess runner + shared error type)

Pass4 knowledge modules:

- `cookimport/llm/codex_farm_knowledge_orchestrator.py` (pass4 run/manifest/write orchestration)
- `cookimport/llm/codex_farm_knowledge_jobs.py` (job payload construction + context windows)
- `cookimport/llm/codex_farm_knowledge_contracts.py` (pass4 input contract models)
- `cookimport/llm/codex_farm_knowledge_models.py` (pass4 output contract models)
- `cookimport/llm/codex_farm_knowledge_ingest.py` (validated output loading)
- `cookimport/llm/codex_farm_knowledge_writer.py` (snippets + knowledge markdown writer)
- `cookimport/llm/non_recipe_spans.py` (span helpers used by pass4 job building)

Pass5 tags modules:

- `cookimport/tagging/orchestrator.py` (stage-level tag pass orchestration + index writing)
- `cookimport/tagging/llm_second_pass.py` (missing-category shortlist + fallback behavior)
- `cookimport/tagging/codex_farm_tags_provider.py` (pass5 I/O, schema validation, shortlist enforcement)
- `cookimport/tagging/cli.py` (standalone tag-recipes/tag-catalog CLI LLM options)
- `cookimport/llm/codex_farm_runner.py` and `cookimport/llm/codex_farm_ids.py` (shared runner/id helpers)

Report/model plumbing:

- `cookimport/core/models.py` (`ConversionReport.llm_codex_farm` field carried in stage/pred-run reports)
- Codex subprocess metadata is now persisted per pass:
  - recipe pass manifest/report: `process_runs.pass1|pass2|pass3`
  - pass4 knowledge report: `process_run`
  - pass5 tags report: `process_run`

## Policy boundary (current behavior)

- `llm_recipe_pipeline` supports `off` and `codex-farm-3pass-v1` without env-gate coercion.
- `RunSettings.from_dict`, CLI normalizers, and Label Studio prediction-run normalizers accept codex-farm values directly and only reject invalid enum values.
- Interactive run setup asks `Use Codex Farm recipe pipeline for this run?` (default `Yes`) and then asks model/reasoning overrides when enabled.
- Interactive all-method setup asks `Include Codex Farm permutations?` (default `Yes`); single/single-profile modes rely only on chosen run settings.
- Global defaults remain deterministic with `llm_recipe_pipeline=off`.
- `COOKIMPORT_ALLOW_CODEX_FARM` remains as a legacy no-op compatibility variable.
- `codex_farm_failure_mode` still controls behavior for active LLM passes (`fail` or `fallback`).

## 2026-02-28 merged task specs (`docs/tasks` batch)

### 2026-02-28_02.31.09 enable codex-farm in benchmarks (historical gate phase)

- Source task: `docs/tasks/2026-02-28_02.31.09-enable-codex-farm-in-benchmarks.md`
- Added `--include-codex-farm` coverage in bench speed/quality all-method flows and made codex variants a real all-method dimension.
- Historical note: this task used an env-gated rollout (`COOKIMPORT_ALLOW_CODEX_FARM=1`); that gating was later removed by `2026-02-28_04.05.00`.
- Durable behavior that remains relevant:
  - all-method codex variants are explicit/opt-in (`--include-codex-farm`),
  - deterministic sweeps remain independent from codex inclusion choices.

### 2026-02-28_02.48.43 codex-farm CLI setup for EPUB benchmark runs

- Source task: `docs/tasks/2026-02-28_02.48.43-setup-codex-farm-cli-for-epub-benchmarks.md`
- Captured operational dependency that benchmark/stage codex paths shell out to external `codex-farm`.
- Recommended durable setup:
  - prefer absolute `codex_farm_cmd` paths,
  - set `codex_farm_root` to this repo’s `llm_pipelines` when using local packs,
  - keep pass pipeline IDs aligned (`recipe.chunking.v1`, `recipe.schemaorg.v1`, `recipe.final.v1`).
- Failure semantics:
  - missing/unresolvable `codex-farm` should fail fast with explicit invocation errors.

### 2026-02-28_03.37.51 unlock interactive llm recipe pipeline option

- Source task: `docs/tasks/2026-02-28_03.37.51-unlock-interactive-llm-recipe-pipeline-option.md`
- `run_settings_ui_specs()` now always includes `llm_recipe_pipeline=off|codex-farm-3pass-v1`.
- `Change run settings...` no longer hides codex-farm based on env state.
- This removed a repeated UX mismatch where runtime accepted codex values but editor choices hid them.

### 2026-02-28_04.05.00 codex-farm always-on in interactive and normalizers

- Source task: `docs/tasks/2026-02-28_04.05.00-codex-farm-always-on-in-interactive-and-normalizers.md`
- Recipe codex-farm normalization is ungated in `RunSettings`, CLI, and Label Studio ingest paths.
- Interactive defaults now bias to codex-enabled runs:
  - per-run chooser prompt default `Yes`,
  - all-method permutations prompt default `Yes`.
- Bench/stage behavior remains explicit opt-in at command/profile level (`--include-codex-farm` and run-settings choices); no implicit global always-on execution.

### 2026-02-28_09.26.29 codex-farm connection contract alignment

- Merged from former `docs/tasks/2026-02-28_09.26.29-codex-farm-connection-contract-alignment.md` (file removed after merge).
- Interactive model discovery now follows caller contract via `codex-farm models list --json` (best-effort fallback if unavailable).
- Subprocess-backed pass orchestration prevalidates configured pipeline ids via `codex-farm pipelines list --root <pack> --json`.
- Subprocess failure diagnostics now parse `process --json` and, when `run_id` is present, append `codex-farm run errors --run-id <run_id> --json` context.
- Boundary note:
  - strict pipeline prevalidation is scoped to subprocess-backed execution and does not block fake/injected test runners.

### 2026-02-28_09.49.32 codex-farm caller output-schema enforcement

- Merged from former `docs/tasks/2026-02-28_09.49.32-codex-farm-output-schema-enforcement.md` (file removed after merge).
- Recipe/pass4/pass5 subprocess calls now resolve each pipeline `output_schema_path` from pack pipeline definitions and pass it explicitly as `--output-schema`.
- Fail-fast guards now trigger before subprocess execution for:
  - missing/duplicate pipeline definition for requested `pipeline_id`,
  - missing `output_schema_path`,
  - missing schema file on disk.
- When `process --json` payload is present, runner now requires `output_schema_path` and validates parity with caller-expected schema path.
- Runtime auditability:
  - recipe pass manifest/report: `output_schema_paths`,
  - pass4/pass5 reports: `output_schema_path`.

### 2026-02-28_10.15.00 codex-exec telemetry contract ingest

- Merged from former `docs/tasks/2026-02-28_10.15.00-codex-farm-telemetry-contract-ingest.md` (file removed after merge).
- Runner now returns structured process metadata plus:
  - `telemetry_report` copied from `process --json.telemetry_report` (CodexFarm caller contract, schema v2),
  - `autotune_report` from `run autotune --run-id <id> --json` (flag overrides, command preview, and optional prompt/pipeline diffs),
  - compact best-effort telemetry slices from `codex_exec_activity.csv` keyed by `run_id` + `pipeline_id` under `telemetry`.
- Persisted telemetry surfaces:
  - recipe pass manifest/report: `process_runs.pass1|pass2|pass3`,
  - pass4 knowledge report: `process_run`,
  - pass5 tags report: `process_run`.
- Telemetry ingestion remains non-fatal:
  - missing/unreadable telemetry CSV adds warnings in payload and does not fail conversion runs,
  - missing embedded `telemetry_report` (older codex-farm or `--no-telemetry-report`) is tolerated,
  - missing/unsupported `run autotune` command is tolerated (payload key remains null).
- CSV resolution follows codex-farm process semantics:
  - `--data-dir` override when present,
  - otherwise `<cwd>/var`.

## Active optional passes

### Pass4 knowledge harvesting

Enable with:

- `llm_knowledge_pipeline=codex-farm-knowledge-v1`
- `codex_farm_pipeline_pass4_knowledge`
- `codex_farm_knowledge_context_blocks`

Writes:

- `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge_manifest.json`
- `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
- `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`
- `data/output/<ts>/knowledge/knowledge_index.json`

### Pass5 tag suggestions

Enable with:

- `llm_tags_pipeline=codex-farm-tags-v1`
- `tag_catalog_json`
- `codex_farm_pipeline_pass5_tags`

Writes:

- `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags_manifest.json`
- `data/output/<ts>/tags/<workbook_slug>/r{index}.tags.json`
- `data/output/<ts>/tags/<workbook_slug>/tagging_report.json`
- `data/output/<ts>/tags/tags_index.json`

## Shared codex-farm controls

These settings remain part of run settings and stage execution:

- `llm_recipe_pipeline`
- `llm_knowledge_pipeline`
- `llm_tags_pipeline`
- `codex_farm_cmd`
- `codex_farm_model` (optional override passed to codex-farm)
- `codex_farm_reasoning_effort` (optional override passed to codex-farm as reasoning/thinking effort)
- `codex_farm_root`
- `codex_farm_workspace_root`
- `codex_farm_failure_mode`
- `codex_farm_pipeline_pass1`
- `codex_farm_pipeline_pass2`
- `codex_farm_pipeline_pass3`
- `codex_farm_pipeline_pass4_knowledge`
- `codex_farm_pipeline_pass5_tags`
- `codex_farm_context_blocks`
- `codex_farm_knowledge_context_blocks`
- `tag_catalog_json`

## Prediction-run boundary

- Label Studio prediction-run generation (`generate_pred_run_artifacts`) currently wires recipe-pass settings only (pass1/2/3 + codex-farm command/root/workspace/context/failure mode).
- Pass4 knowledge harvesting and pass5 tag suggestions are stage-only flows; prediction-run generation does not execute those passes.
- Benchmark prediction generation (`labelstudio-benchmark`) reuses that same prediction-run recipe-pass boundary.

Recipe pass execution in prediction-run paths follows selected run settings with no env gate.

## Test support + legacy modules

- `cookimport/llm/fake_codex_farm_runner.py` provides deterministic fake outputs for tests.

Legacy modules (not on current stage/pred-run/tag runtime path):

- `cookimport/llm/client.py`
- `cookimport/llm/prompts.py`
- `cookimport/llm/repair.py`

These modules remain for older/manual experimentation and tests; current import pipeline behavior is governed by codex-farm modules and run settings above.

## Related docs

- `docs/10-llm/10-llm_log.md`
- `docs/10-llm/knowledge_harvest.md`
- `docs/10-llm/tags_pass.md`

## 2026-02-27 Merged Understandings: Runtime Scope and Coverage Parity

Merged source notes:
- `docs/understandings/2026-02-27_19.45.57-llm-docs-runtime-scope-cleanup.md`
- `docs/understandings/2026-02-27_19.51.50-llm-docs-parity-runtime-surface-map.md`

Current-contract additions:
- Stage-relevant LLM runtime remains centered on pass4 knowledge and pass5 tags; recipe pass1/2/3 is available for stage/pred-run use via run settings.
- Prediction-run generation currently wires recipe-pass settings only; pass4/pass5 execution remains stage-only.
- LLM docs should keep runtime-adjacent module coverage explicit (prediction wrappers, pass4 helper contracts/writer paths, pass5 provider/validation layer, stage evidence/report consumers).
- Legacy modules (`client.py`, `prompts.py`, `repair.py`) remain non-primary runtime paths and should stay labeled accordingly.

## 2026-02-28 migrated understandings digest (Oracle + Codex Farm ops)

### 2026-02-28_01.58.55 Oracle browser login/session blocker
- Source: `docs/understandings/2026-02-28_01.58.55-oracle-browser-login-session-blocker.md`
- Recurring Oracle browser failures were traced to missing ChatGPT browser auth plus unwritable default session paths under `~/.oracle` in Codex sandbox contexts.
- Local wrapper defaults were moved to writable persistent paths under `/home/mcnal/.local/share/oracle` with `/tmp` fallback and pre-created `sessions/` directories.

### 2026-02-28_03.17.29 Codex Farm opt-in command pattern
- Source: `docs/understandings/2026-02-28_03.17.29-codex-farm-opt-in-command-pattern.md`
- Keep global defaults deterministic (`llm_recipe_pipeline=off`); enable Codex Farm per command/profile.
- Absolute `codex_farm_cmd` paths avoid PATH fragility when Codex Farm is outside shell defaults.

### 2026-02-28_03.19.05 Oracle gpt-5.2-thinking browser blocker
- Source: `docs/understandings/2026-02-28_03.19.05-oracle-gpt52-thinking-browser-blocker.md`
- In this sandbox, gpt-5.2-thinking Oracle browser runs were blocked by browser/auth/session constraints (stuck runs or early chrome-close errors), not prompt/file bundle construction.

### 2026-02-28_03.19.48 interactive Codex Farm gate and launcher
- Source: `docs/understandings/2026-02-28_03.19.48-interactive-codex-farm-gate-and-launcher.md`
- Interactive mode already respects run-settings `llm_recipe_pipeline`; no additional interactive-only gate path is required.
- Wrapper launcher pattern (`scripts/interactive-with-codex-farm.sh`) remains useful when you want codex-enabled sessions with preset command/model flags.

## 2026-02-28 migrated understandings batch (03:47-04:01)

The items below were merged from `docs/understandings` in timestamp order and folded into LLM current-state guidance.

### 2026-02-28_03.47.42 Oracle codex-farm prompt-tightening priorities
- External review found deterministic/schema-safety under-specification across pass prompts.
- Priority order for highest-impact tightening was:
  1. pass2 (`recipe.schemaorg.v1`)
  2. pass3 (`recipe.final.v1`)
  3. pass1 (`recipe.chunking.v1`)
  4. pass4/pass5 (medium impact)
- High-value wording improvements: explicit omit-vs-guess policy, tie-break rules, strict evidence language, stable ordering, and no-extra-properties constraints.

### 2026-02-28_04.01.52 codex toggle vs effective run settings
- Prompt-time codex selection can diverge from persisted effective run settings when normalization/gating code changes around run time.
- For run `2026-02-28_03.54.15`, artifacts showed `llm_recipe_pipeline=off` and `llm_codex_farm.enabled=false`; nearby file edits around `04:00` explain likely normalization drift during that session.
- For incident triage, trust persisted run artifacts (`run_manifest`, run settings snapshot) over assumptions from current head code.

## 2026-02-28 migrated understandings batch (04:05-10:08 Codex gate surfaces and connection contract)

### 2026-02-28_04.05.20 codex-farm gate surface map
- Source: `docs/understandings/2026-02-28_04.05.20-codex-farm-gate-surface-map.md`
- Codex behavior can drift when only one surface is edited.
- Four runtime surfaces must stay aligned:
  1. `RunSettings.from_dict(...)` coercion/normalization.
  2. `run_settings_ui_specs()` interactive enum choices.
  3. `cookimport/cli.py:_normalize_llm_recipe_pipeline(...)`.
  4. `cookimport/cli.py:_resolve_all_method_codex_choice(...)`.
- Prompt defaults (chooser/all-method yes/no) are independent from those normalization surfaces.

### 2026-02-28_04.11.09 docs-task merge codex gating drift
- Source: `docs/understandings/2026-02-28_04.11.09-docs-task-merge-codex-gating-drift.md`
- During docs consolidation, stale env-gated wording appeared alongside current ungated runtime behavior.
- Current authoritative runtime remains ungated in run-settings parser + CLI + Label Studio ingest normalizers.
- `COOKIMPORT_ALLOW_CODEX_FARM` is legacy compatibility surface (no active gate); keep old gated behavior only as historical `_log` context.

### 2026-02-28_09.26.29 codex-farm connection contract alignment
- Source: `docs/understandings/2026-02-28_09.26.29-codex-farm-connection-contract-aligned.md`
- Shared run-settings Codex model picker now discovers choices via `codex-farm models list --json` (best-effort fallback when unavailable).
- Recipe/pass4/pass5 subprocess paths now validate configured pipeline ids up front via `codex-farm pipelines list --root <pack> --json`.
- Subprocess failure diagnostics now parse `process --json` output and, when `run_id` is available, append first-error context from `codex-farm run errors --run-id <run_id> --json`.

### 2026-02-28_09.49.32 caller output-schema enforcement wiring
- Recipe/pass4/pass5 subprocess calls now resolve each pipeline's declared `output_schema_path` from the selected pack and pass it explicitly as `--output-schema` to `codex-farm process`.
- This keeps caller-side schema contract enforcement aligned with Codex Farm's structured-output retry gate.
- If pipeline definitions are missing/duplicated, or the resolved schema file is missing, subprocess invocation now fails fast before work starts.
- When `process --json` returns payload JSON, runner now expects `output_schema_path` and verifies it matches the caller-expected schema path.
- Runtime manifests/reports now surface schema paths for auditing:
  - recipe pass manifest/report: `output_schema_paths`
  - pass4/pass5 reports: `output_schema_path`

### 2026-02-28_10.08.00 codex-exec telemetry ingestion in recipeimport
- Recipe/pass4/pass5 runner calls now retain per-process metadata (`run_id`, `process_exit_code`, `subprocess_exit_code`, `process_payload`) and also surface:
  - `telemetry_report` from `process --json` (CodexFarm schema-v2 caller contract with `insights` and `tuning_playbook`),
  - `autotune_report` from `run autotune --json` (non-mutating override/diff suggestions),
  - `telemetry` CSV slices keyed by `run_id` + `pipeline_id` for compact per-row context.
- Telemetry slices are read from Codex Farm `codex_exec_activity.csv` and persisted into recipe artifacts (`process_runs` / `process_run`) with compact rows + summary counts for:
  - retry context and previous-error hashes,
  - Heads Up tip ids/texts/scores and usage flags,
  - normalized failures and suspected rate limits,
  - output hashes/previews/presence stats,
  - codex event count/type summaries and token counters.

## 2026-02-28 merged understandings (09:26-10:13 codex-farm subprocess and telemetry boundary)

The items below were merged from `docs/understandings` in source timestamp order.

### 2026-02-28_09.26.29 codex-farm connection contract aligned
- Source: `docs/understandings/2026-02-28_09.26.29-codex-farm-connection-contract-aligned.md`
- Interactive model discovery now uses `codex-farm models list --json` via runner helper so choices reflect live CLI discovery.
- Subprocess-backed recipe/pass4/pass5 flows validate pipeline IDs using `codex-farm pipelines list --root <pack> --json` before execution.
- Failure paths parse `process --json` and pull first-error details from `codex-farm run errors --run-id <run_id> --json` when available.

### 2026-02-28_09.50.17 codex-farm output schema resolution point
- Source: `docs/understandings/2026-02-28_09.50.17-codex-farm-output-schema-resolution-point.md`
- Correct caller-side insertion point for schema enforcement is `SubprocessCodexFarmRunner.run_pipeline(...)` command assembly.
- This single boundary guarantees consistent `--output-schema` handling across recipe pass1/2/3, pass4 knowledge, and pass5 tags.
- Process payload contract check also belongs here: validate returned `output_schema_path` against caller-expected schema path.

### 2026-02-28_10.03.37 codex-exec telemetry consumption boundary (historical snapshot)
- Source: `docs/understandings/2026-02-28_10.03.37-codex-exec-telemetry-consumption-boundary.md`
- Snapshot finding at that time: repo runtime did not yet ingest `codex_exec_activity.csv` rich telemetry fields; analytics consumed performance history contracts instead.
- This historical boundary is intentionally kept to prevent false assumptions when reading older artifacts or logs.
- Superseded by the implementation captured in `2026-02-28_10.13.48` and task merge entry `2026-02-28_10.08.00`.

### 2026-02-28_10.13.48 codex-farm run-id telemetry ingestion path
- Source: `docs/understandings/2026-02-28_10.13.48-codex-farm-runid-telemetry-ingestion-path.md`
- `run_id` from `process --json` is the join key into Codex Farm telemetry rows for the exact pipeline run.
- Runner now persists compact pass-level telemetry slices in:
  - recipe pass manifests/reports: `process_runs.pass1|pass2|pass3`
  - pass4/pass5 reports: `process_run`
- Telemetry ingestion remains non-fatal and warnings are carried in payloads when CSV data is missing/unreadable.
- CSV path discovery follows codex-farm semantics: explicit `--data-dir` if present, otherwise `<cwd>/var/codex_exec_activity.csv`.

### Known bad or easy-to-repeat mistakes
- Do not inject schema enforcement separately in each orchestrator; keep it centralized at subprocess runner command assembly.
- Do not treat missing telemetry CSV as conversion failure; current contract is warn-and-continue with bounded payload slices.
- When behavior differs between UI choices and runtime, verify live CLI discovery and persisted run artifacts before changing prompts or enums.
