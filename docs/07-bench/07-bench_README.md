---
summary: "Current benchmark-suite reference for cookimport bench and related benchmark flows."
read_when:
  - When running or modifying cookimport bench workflows
  - When debugging benchmark scoring behavior or artifacts
  - When comparing stage-blocks versus canonical-text evaluation modes
---

# Bench Section Reference

This file is the current, code-verified benchmark contract.
Historical chronology lives in `docs/07-bench/07-bench_log.md`.

## 1. Scope

Benchmarking in this repo covers two paths:
- `cookimport bench ...` (offline speed/quality/eval workflows)
- `cookimport labelstudio-benchmark` (single-run benchmark primitive also reused by interactive benchmark flows)

Current scoring surfaces:
- `stage-blocks`: compare stage evidence labels against freeform gold block labels.
- `canonical-text`: align prediction text to canonical gold text and score per canonical line.

## 2. Command Surface

### 2.1 `cookimport bench`

- `bench speed-discover`: build deterministic speed suite from pulled gold exports.
- `bench speed-run`: run timing scenarios (`stage_import`, `benchmark_canonical_legacy`, `benchmark_canonical_pipelined`, `benchmark_all_method_multi_source`). Supports bounded task-level fanout via `--max-parallel-tasks` (auto mode when omitted: `min(total_tasks, cpu_count, 4)`) and crash-safe resume via `--resume-run-dir`. Use `--require-process-workers` to fail fast when stage/all-method internals cannot establish process workers.
- Codex Farm permutations (recipe pass) can be included in all-method grids by passing `--include-codex-farm` to `bench speed-run` / `bench quality-run`. Optional overrides: `--codex-farm-model ...` and `--codex-farm-thinking-effort high` (or `--codex-farm-reasoning-effort`).
- `bench speed-run` requires explicit positive confirmation when Codex Farm is requested: `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `bench quality-run` requires explicit positive confirmation when Codex Farm is requested: `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `bench speed-compare`: compare baseline/candidate speed runs with regression gates.
- `bench gc`: benchmark artifact retention and garbage collection. Dry-run is default (`--dry-run`); use `--apply` to mutate artifacts. Policy controls include `--keep-full-runs`, `--keep-full-days`, and `--drop-speed-artifacts`. Run roots are pruned only when benchmark history durability is confirmed from CSV rows.
- `bench quality-discover`: build deterministic quality suite from pulled gold exports (curated CUTDOWN focus IDs first: `saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`; representative fallback). Discovery metadata includes `format_counts` + `selected_format_counts`, each target carries `source_extension`, and `--formats` can filter discovery inputs by extension (for example `.pdf,.epub`). Use `--no-prefer-curated` to include all matched sources by default when `--max-targets` is omitted.
- `bench quality-run`: run all-method quality experiments for one discovered suite (`--search-strategy race` default; use `exhaustive` for full-grid runs). Experiment-level concurrency is CPU-aware by default (auto cap + adaptive worker target from host load; default auto ceiling follows detected CPU count, override via `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`); pass `--max-parallel-experiments` to force a fixed cap. In runtimes that block process pools, quality-run keeps all-method `global` scope; experiment fanout auto-switches to subprocess workers while per-experiment all-method config workers continue thread-backed fallback. On WSL, quality-run applies a nested-parallelism safety guard by default (worker caps + all-method runtime caps) and records guard telemetry in `experiments_resolved.json`; set `COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD=1` only for deliberate opt-out runs. Use `--require-process-workers` to fail fast instead of allowing fallback backends. Gentle disk I/O write pacing is enabled by default and can be disabled via `--io-pace-every-writes 0` or `--io-pace-sleep-ms 0`. Live ETA status now models queued experiments (not only active experiments) using active scheduler telemetry plus completed-experiment duration fallback. Crash-safe checkpoints are persisted continuously and can be resumed via `--resume-run-dir`.
- `bench quality-lightweight-series`: disabled/retired in CLI due to extreme runtime and disk amplification from fold-based tournament artifacts. Historical artifacts remain readable under `data/golden/bench/quality/lightweight_series`.
- `scripts/quality_top_tier_tournament.py`: disabled/retired runtime entrypoint; `main()` exits immediately with a disabled message to prevent accidental tournament fanout.
- `bench quality-leaderboard`: aggregate one quality-run experiment into a global cross-source config leaderboard and Pareto frontier; optional `--by-source-extension` emits per-format leaderboard slices.
- `bench quality-compare`: compare baseline/candidate quality runs with strict/practical/source-coverage regression gates.
- `bench eval-stage --gold-spans ... --stage-run ...`: evaluate a stage run directly from `.bench/*/stage_block_predictions.json`.

### 2.2 `cookimport labelstudio-benchmark` benchmark controls

Most benchmark behavior is shared with this command. Active benchmark-specific controls include:
- action positional: `run` (default) or `compare`
- `--eval-mode stage-blocks|canonical-text`
- `--execution-mode legacy|pipelined|predict-only`
- `--predictions-out <jsonl>` / `--predictions-in <jsonl>`
- `--baseline <run_or_report_path>` / `--candidate <run_or_report_path>` (compare action)
- `--compare-out <dir>` / `--fail-on-regression`
- `--sequence-matcher dmp`
- `--pdf-ocr-policy off|auto|always`
- `--pdf-column-gap-ratio <float>`
- `--section-detector-backend legacy|shared_v1`
- `--multi-recipe-splitter legacy|off|rules_v1`
- `--multi-recipe-trace/--no-multi-recipe-trace`
- `--multi-recipe-min-ingredient-lines <int>`
- `--multi-recipe-min-instruction-lines <int>`
- `--multi-recipe-for-the-guardrail/--no-multi-recipe-for-the-guardrail`
- `--instruction-step-segmentation-policy off|auto|always`
- `--instruction-step-segmenter heuristic_v1|pysbd_v1`
- `--atomic-block-splitter off|atomic-v1`
- `--line-role-pipeline off|deterministic-v1|codex-line-role-v1`
- `--codex-farm-recipe-mode extract|benchmark`
- `--no-upload` for fully offline behavior
- `--no-write-markdown`
- `--no-write-labelstudio-tasks` (offline/no-upload path)
- `C3imp` interactive runs set `COOKIMPORT_BENCH_WRITE_MARKDOWN=1` and
  `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS=0` by default, so markdown
  summaries are enabled while task JSONL artifacts stay disabled unless
  overridden in the shell.

Interactive benchmark flows (`single_offline`, `single_offline_all_matched`, `all_method`) stay offline and use canonical-text scoring.
`labelstudio-benchmark compare` evaluates named gates (`sea_no_regression`, `foodlab_no_regression`, `foodlab_ingredient_at_least_baseline`, `foodlab_variant_recall_nonzero`, plus debug-artifact presence gates) and writes timestamped reports under `data/golden/benchmark-vs-golden/comparisons/<timestamp>/`.

Debug artifact mode checks in compare are resolved by metadata first and inferred from artifacts when metadata is absent. If the pipeline intent cannot be confirmed, the command emits explicit warnings in both CLI output and comparison artifacts and skips benchmark-only checks by design.
Interactive `single_offline` now writes into one session root:
- `data/golden/benchmark-vs-golden/<timestamp>/single-offline-benchmark/<source_slug>/vanilla/`
- optional paired codex run at `.../single-offline-benchmark/<source_slug>/codexfarm/` when run settings enable `llm_recipe_pipeline=codex-farm-3pass-v1`
- `<source_slug>` is derived from the selected source filename stem (slugified).
- `single_offline` resolves one source/gold pair once and reuses it for all planned variants (vanilla + codexfarm) in a session.
- codex variant runs now include prompt-debug text artifacts under `.../codexfarm/codexfarm/`:
  - `prompt_request_response_log.txt` (combined full dump),
  - `full_prompt_log.jsonl` (required one-row-per-call machine-readable log; no sampling/truncation),
  - `full_prompt_log.jsonl` rows include `request_payload_source` (`telemetry_csv` when `codex_exec_activity.csv` has a matching call; fallback `reconstructed_from_prompt_template` otherwise) and `request_telemetry` with per-call runtime metadata.
  - `prompt_task1_pass1_chunking.txt`, `prompt_task2_pass2_schemaorg.txt`, `prompt_task3_pass3_final.txt` (split by prompt category),
  - `prompt_category_logs_manifest.txt` (one-path-per-line index of category files).
  - benchmark `run_manifest.json` now includes `full_prompt_log_status`, `full_prompt_log_rows`, and `full_prompt_log_path` under `artifacts` for CodexFarm runs.
- optional comparison artifacts only when both variants succeed:
  - `.../single-offline-benchmark/<source_slug>/codex_vs_vanilla_comparison.json` (always)
- optional consolidated markdown summary (when markdown writes are enabled):
  - `.../single-offline-benchmark/<source_slug>/single_offline_summary.md`
Priority 8 segmentation controls (`--label-projection`, `--boundary-tolerance-blocks`, `--segmentation-metrics`) are exposed only on `bench eval-stage` (not all-method or speed-suite).
When prediction generation enables `llm_recipe_pipeline=codex-farm-3pass-v1`, benchmark progress callback spinners now receive codex-farm `task X/Y` updates from `process --progress-events` (with automatic fallback to phase-only status when that flag is unavailable). If the progress payload includes running-task metadata, callbacks also include an `active [...]` list of file-level task labels for the currently occupied workers; if it does not, only aggregate counters are shown. Spinner output is shown as a compact blue ASCII panel (bordered block) to make live worker/task state easy to track without noise.
In agent-run terminals (`CODEX_CI=1`, `CODEX_THREAD_ID`, `CLAUDE_CODE_SSE_PORT`), callback progress defaults to plain change-only status lines instead of animated spinner frames; use `COOKIMPORT_PLAIN_PROGRESS=0` to keep live spinner rendering.

## 3. Artifact Contracts

### 3.1 Prediction/evidence artifacts

Primary scored prediction source:
- `stage_block_predictions.json` (`schema_version=stage_block_predictions.v1`)

Required supporting artifact:
- `extracted_archive.json` (prediction text stream and block metadata)

Generated roots:
- `labelstudio-benchmark` writes benchmark artifacts under benchmark run roots.
- Stage runs write stage evidence under `.bench/<workbook_slug>/stage_block_predictions.json`; pred-run builders copy this into run-root `stage_block_predictions.json`.

### 3.2 Gold artifacts

Stage-block mode:
- `exports/freeform_span_labels.jsonl`

Canonical-text mode:
- `exports/canonical_text.txt`
- `exports/canonical_span_labels.jsonl`
- `exports/canonical_manifest.json`

### 3.3 Core eval outputs

Stage-block outputs include:
- `eval_report.json`
- `eval_report.md` (only when markdown writes are enabled)
- `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`
- `missed_gold_boundaries.jsonl`, `false_positive_boundaries.jsonl`
- compatibility aliases: `missed_gold_spans.jsonl`, `false_positive_preds.jsonl`
- diagnostics: `gold_conflicts.jsonl`

Canonical-text outputs include:
- `eval_report.json`
- `eval_report.md` (only when markdown writes are enabled)
- `aligned_prediction_blocks.jsonl`
- `missed_gold_lines.jsonl`, `wrong_label_lines.jsonl`
- `unmatched_pred_blocks.jsonl`, `alignment_gaps.jsonl`

### 3.4 Speed/quality artifacts

Speed suite (`bench speed-run`) artifacts include:
- `suite_resolved.json`, `samples.jsonl`, `summary.json`, `report.md`, `run_manifest.json`
- incremental crash-safe artifacts: `checkpoint.json`, `summary.partial.json`, `report.partial.md`, `samples.partial.jsonl`
- `summary.json` includes `run_settings`, `run_settings_summary`, `run_settings_hash`, Codex Farm request/confirmation flags, and resolved parallel/resume metadata so baseline/candidate comparisons can enforce settings parity and audit execution mode.
  - strict-worker telemetry is included: `require_process_workers`, `process_worker_probe_available`, `process_worker_probe_error`.
- per-sample artifacts under `scenario_runs/<target_id>/<scenario>/<phase_index>/...`
  - each sample phase folder persists `speed_sample_result.json` for resume reuse.
  - suite-level all-method samples use synthetic target id `__all_matched__` and folder `_all_matched`.

Speed comparison (`bench speed-compare`) artifacts include:
- `comparison.json`, `comparison.md`
- comparison payload includes `baseline_run_settings_hash`, `candidate_run_settings_hash`, `settings_match`, and mismatch-verdict metadata.

Benchmark GC (`bench gc`) artifacts/side effects include:
- optional history backup before mutation: `performance_history.<YYYY-MM-DD_HH.MM.SS>.gc.bak.csv`
- optional CSV hydration for benchmark rows (`per_label_json` plus strict/macro/boundary fallback fields) before deletion
- conditional stale-row prune for deleted run roots when benchmark rows have no durable metrics
- policy summary in CLI output (`kept/pruned counts`, `estimated reclaim`, `history rows updated/pruned`)

Quality suite (`bench quality-run`) artifacts include:
- `suite_resolved.json`, `experiments_resolved.json`, `summary.json`, `report.md`
- incremental crash-safe artifacts: `checkpoint.json`, `summary.partial.json`, `report.partial.md`
- one per-experiment output root under `experiments/<experiment_id>/...` containing all-method benchmark artifacts.
- each experiment root persists `quality_experiment_result.json` after completion for resume reuse.
- `summary.json` stores per-experiment run-settings hashes and strict/practical/source-coverage metrics for compare gating, plus format visibility fields `format_counts` and `selected_format_counts`.
- quality summaries/resolved payloads include strict-worker telemetry: `require_process_workers`, `process_worker_probe_available`, `process_worker_probe_error`.
- `experiments_resolved.json` records resolved experiments (including any schema-v2 lever expansion), the canonical alignment cache root, all-method runtime knobs, Codex Farm request/confirmation flags, and WSL telemetry fields (`wsl_detected`, `wsl_safety_guard_applied`, `wsl_safety_guard_reason`, `wsl_safety_guard_worker_cap`, `wsl_safety_guard_adjusted_experiments`).

Historical lightweight-series artifacts (command now disabled in CLI) include:
- `lightweight_series_resolved.json`, `lightweight_series_summary.json`, `lightweight_series_report.md`
- round roots: `round_1_main_effects/`, `round_2_composition/`, `round_3_interaction_smoke/`
- each fold root contains `suite.json`, `experiments_effective.json`, `fold_summary_extract.json`, and `quality_runs/<timestamp>/...` quality-run artifacts
- optional round 1 confidence guard fold under `round_1_main_effects/confidence_guard/`

Quality leaderboard (`bench quality-leaderboard`) artifacts include:
- `leaderboard.json`, `leaderboard.csv`
- `pareto_frontier.json`, `pareto_frontier.csv`
- `winner_run_settings.json`, `winner_dimensions.json`
- optional (when `--by-source-extension`): `leaderboard_by_source_extension.json`, `leaderboard_by_source_extension.csv`
- interactive profile side effect: winner run settings are also saved to `data/.history/qualitysuite_winner_run_settings.json` for `Run with quality-suite winner (...)` menu selection.
- default output root: `<quality_run_dir>/leaderboards/<experiment_id>/<timestamp>/`

Quality comparison (`bench quality-compare`) artifacts include:
- `comparison.json`, `comparison.md`
- comparison payload includes baseline/candidate experiment IDs, run-settings parity fields, strict/practical/source-success deltas, thresholds, and FAIL reasons.

Prediction-record and telemetry artifacts:
- `labelstudio-benchmark --predictions-out` writes validated JSONL prediction records (`cookimport/bench/prediction_records.py` schema v1).
- `--predictions-in` supports evaluate-only replay for both per-block records and legacy run-pointer records.
- benchmark runs can emit `processing_timeseries_prediction.jsonl` and `processing_timeseries_evaluation.jsonl`.
- optional eval profiling artifacts (`eval_profile.pstats`, `eval_profile_top.txt`) are written when profiling threshold env vars are enabled and runtime crosses threshold.
- compare action writes `comparison.json` and `comparison.md` under the configured comparison output root.
- compare action prints the gate pass/fail table directly in CLI output.
- comparison.md and comparison.json include source-level debug artifact diagnostics for candidate runs, including mode resolution and warning messages when benchmark mode must be inferred or cannot be confirmed.

## 4. Scoring Contracts

### 4.1 Stage-blocks

- Gold rows can contain multiple allowed labels for a block; prediction is correct when it matches any allowed label.
- `HOWTO_SECTION` is resolved for both gold and prediction label paths before scoring:
  - `INGREDIENT_LINE` or `INSTRUCTION_LINE` is inferred from nearby structural context.
  - this keeps structural metrics comparable while preserving `HOWTO_SECTION` in task/export surfaces.
- Predicted blocks with no gold row default to gold label `OTHER` and are logged in diagnostics.
- Evaluator compares blockization fingerprints and fails fast with `gold_prediction_blockization_mismatch` when severe drift makes block-level comparison invalid.

Primary metrics:
- `strict_accuracy`
- `overall_block_accuracy`
- `macro_f1_excluding_other`
- `worst_label_recall`
- Stage/canonical `eval_report.json` now uses explicit metric keys and does not emit legacy alias keys (`precision/recall/f1`, `practical_*`).
- additive segmentation diagnostics under `segmentation`:
  - `label_projection` (currently `core_structural_v1`)
  - `boundary_tolerance_blocks`
  - `boundaries` (`ingredient_start`, `ingredient_end`, `instruction_start`, `instruction_end`, `recipe_split`, `overall_micro`)
  - `error_taxonomy` buckets (`extraction_failure`, `boundary_errors`, `ingredient_errors`, `instruction_errors`, `yield_time_errors`)
  - optional `segeval` metrics (`pk`, `windowdiff`, `boundary_similarity`) when requested and installed

### 4.2 Canonical-text

- Prediction block text is aligned against canonical gold text.
- Scoring is in canonical line space and is extractor/blockization independent.
- Canonical line labels keep `HOWTO_SECTION` as an explicit scored label (no stage-style remap).
- Legacy global alignment is enforced for scoring safety; fast alignment is deprecated and forced to legacy when requested.
- Canonical reports include explicit strict metric field `strict_accuracy` (line-space accuracy alias for benchmark consumers).
- Canonical reports now also emit `boundary` (`correct/over/under/partial`) computed in canonical line space from aligned prediction spans vs canonical gold spans (`overlap_threshold=0.5`).

Telemetry includes:
- alignment subphase timings
- matcher requested/effective mode
- cache hit/load/write fields

## 5. SequenceMatcher And Alignment Cache

Matcher selector:
- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp` (only supported value)
- non-`dmp` values fail validation/selection
- concrete matcher implementation lives in:
  - `cookimport/bench/dmp_sequence_matcher.py`

CLI overrides:
- `labelstudio-benchmark --sequence-matcher ...`
- `bench speed-run --sequence-matcher ...` (optional override; default comes from effective run settings payload)

Canonical cache:
- All-method benchmark runs share canonical alignment cache per source-group by default under:
  - `data/golden/benchmark-vs-golden/.cache/canonical_alignment/<source_group_key>`
- `bench quality-run` uses a persistent quality cache root by default:
  - `data/golden/bench/quality/.cache/canonical_alignment/<source_group_key>`
- Override root via `COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`.
- Prediction reuse cache defaults:
  - all-method local run root: `<run_root>/.prediction_reuse_cache`
  - `bench quality-run`: `data/golden/bench/quality/.cache/prediction_reuse`
  - tournament folds: shared by default at `data/golden/bench/quality/.cache/prediction_reuse`
- Override prediction reuse root via `COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT`.
- Prediction artifact materialization is hardlink-first (when filesystem permits), with automatic copy fallback.
- Cache lock recovery handles dead-owner PID locks first, then age-based fallback for malformed lock metadata.

## 6. All-Method Runtime Notes

Active all-method behavior:
- Supports `single` and `all_matched` source scopes.
- Supports bounded source-level parallelism (`all_method_max_parallel_sources`).
- Supports source scheduling strategy (`all_method_source_scheduling`, including `tail_pair`).
- Supports heavy-source sharding knobs:
  - `all_method_source_shard_threshold_seconds`
  - `all_method_source_shard_max_parts`
  - `all_method_source_shard_min_variants`
- Supports scheduler scope toggle (`all_method_scheduler_scope`):
  - `global` (default): one run-wide config queue across all matched sources.
  - `legacy`: prior per-source scheduler path.
- Uses bounded config-level parallelism with split-phase slot controls.
- Applies resource-guard split-slot capping before execution:
  - `split_phase_slots_requested` vs `split_phase_slots`
  - `split_phase_slot_mode` (`configured` or `resource_guard`)
  - `split_phase_slot_cap_by_cpu` / `split_phase_slot_cap_by_memory`
- Runs config prediction first, computes deterministic evaluation signatures, then runs canonical evaluation once per unique signature.
- All-method predict-only calls now source benchmark kwargs from `build_benchmark_call_kwargs_from_run_settings(...)`; this keeps all-method run-setting forwarding in parity with single benchmark execution (including Priority 3/6/7 families).
- Reuses canonical evaluation results in-run (`reused_in_run`) for duplicate signatures.
- Reuses cached evaluation results across runs (`reused_cross_run`) using:
  - `.../.cache/eval_signature_results/__global__/<eval_signature>.json` in global scope.
  - `.../.cache/eval_signature_results/<source_group_key>/<eval_signature>.json` in legacy scope.
- Supports timeout/retry controls:
  - `all_method_config_timeout_seconds`
  - `all_method_retry_failed_configs`

Operational interpretation:
- `scheduler heavy X/Y` tracks split-active occupancy only, not evaluate/post phases.
- live queue fail counters are attempt-level; final truth is in per-source `all_method_benchmark_report.json`.
- run-local artifacts (`eval_report.json`, all-method source reports, scheduler/processing timeseries) are primary telemetry truth.
- Per-source report counters now include:
  - `evaluation_signatures_unique`
  - `evaluation_runs_executed`
  - `evaluation_results_reused_in_run`
  - `evaluation_results_reused_cross_run`
  - `prediction_signatures_unique`
  - `prediction_runs_executed`
  - `prediction_results_reused_in_run`
  - `prediction_results_reused_cross_run`
- All-method reports now include `executor_resolution` telemetry:
  - `process_workers_required`
  - `process_worker_probe_available`
  - `process_worker_probe_error`
  - `config_executor_backends_seen`
- Multi-source report counters include:
  - `scheduler_scope` (`global_config_queue` or `legacy_per_source`)
  - `global_queue_planned_configs`
  - `global_queue_completed_configs`
  - `global_queue_failed_configs`
- Per-config rows now include:
  - `eval_signature`
  - `evaluation_result_source` (`executed`, `reused_in_run`, `reused_cross_run`)
  - `evaluation_representative_config_dir`
  - `prediction_result_source` (`executed`, `reused_in_run`, `reused_cross_run`)
- Interactive all-method benchmark can auto-sweep deterministic Priority 2–6 knobs (default on in the wizard):
  - `section_detector_backend`
  - `multi_recipe_splitter`
  - `ingredient_missing_unit_policy`
  - `instruction_step_segmentation_policy` / `instruction_step_segmenter`
  - `p6_*` time/temp/yield knobs
- When sweeps are enabled, all-method row dimensions include these keys and a `deterministic_sweep` tag for non-baseline configs.
- For webschema-capable sources (`.html`, `.htm`, `.jsonld`, and schema-like `.json`), all-method expands `web_schema_policy` variants (`prefer_schema`, `schema_only`, `heuristic_only`) and keeps other webschema knobs from base run settings.
- Scheduler telemetry now includes adaptive admission fields for throughput diagnostics:
  - summary fields: `adaptive_admission_*`, `cpu_utilization_pct_high_water`, matcher/cache `matcher_guardrails`
  - timeseries fields: `admission_active_cap`, `admission_guard_target`, `admission_wing_target`, `admission_reason`

## 7. Speed And Quality Regression Workflows

Use this flow for baseline-versus-candidate runtime checks:

1. `cookimport bench speed-discover`
2. `cookimport bench speed-run --suite ...`
   - optional: pass `--max-parallel-tasks N` to pin task fanout (omit for auto mode).
   - interrupted runs can continue with `--resume-run-dir data/golden/bench/speed/runs/<existing_timestamp>`.
3. `cookimport bench speed-compare --baseline ... --candidate ...`

Default discovery source is `data/golden/pulled-from-labelstudio`.
`speed-compare` gates regressions using both:
- percent threshold (`regression_pct`)
- absolute seconds floor (`absolute_seconds_floor`)
- run-settings parity (`run_settings_hash` match required unless `--allow-settings-mismatch` is used)

Use this parallel flow for baseline-versus-candidate quality checks:

1. `cookimport bench quality-discover`
2. `cookimport bench quality-run --suite ... --experiments-file ...`
3. `cookimport bench quality-leaderboard --run-dir ... --experiment-id ...`
4. `cookimport bench quality-compare --baseline ... --candidate ...`

`scripts/quality_top_tier_tournament.py` is now disabled/retired in this repo due to
extreme runtime and disk amplification. Historical tournament artifacts remain under
`data/golden/bench/quality/tournaments/<timestamp>/...` for read-only inspection.

For one consolidated "which command when" flow with decision criteria, use `docs/07-bench/qualitysuite-product-suite.md`.

Experiments file notes:
- Schema v1 uses explicit experiments: `{"schema_version": 1, "experiments": [{"id": "...", "run_settings_patch": {...}}]}`.
- Schema v2 adds `levers` with `enabled: true/false`.
  - Runner expands v2 into a concrete experiments list:
    - `baseline` (when `include_baseline=true`)
    - one experiment per enabled lever (experiment id = lever id)
    - optional `all_on` (when `include_all_on=true`) which merges enabled lever patches and fails fast on conflicting keys
  - Schema v2 supports optional `all_method_runtime_patch` per lever/experiment for all-method runtime knobs.
  - Schema v2 also supports top-level `all_method_runtime` for run-wide runtime defaults/overrides.
- Example lever file: `data/golden/bench/quality/experiments/2026-02-28_01.18.41_qualitysuite-levers.json`.
- `quality-run --include-deterministic-sweeps` applies interactive-style deterministic Priority 2–6 sweep expansion to each experiment’s all-method grid (in addition to experiment run-settings patches).
- `quality-run --include-codex-farm` requires `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` and will fail fast without it.
- `quality-run --resume-run-dir <existing-run-dir>` reuses completed experiment snapshots from partial runs and executes only pending experiments.

Search strategy notes:
- `quality-run --search-strategy race` (default) runs deterministic staged pruning:
  - probe subset -> mid subset -> full suite on finalists.
- `quality-run --search-strategy exhaustive` runs the full config grid across all selected targets.
- Race controls:
  - `--race-probe-targets`
  - `--race-mid-targets`
  - `--race-keep-ratio`
  - `--race-finalists`

`quality-compare` gates regressions using:
- strict F1 drop threshold (`strict_f1_drop_max`)
- practical F1 drop threshold (`practical_f1_drop_max`)
- source success-rate drop threshold (`source_success_rate_drop_max`)
- run-settings parity (`run_settings_hash` match required unless `--allow-settings-mismatch` is used)

Suite validation note:
- `bench quality-run` validates all `targets[]` rows in the suite JSON (not only `selected_target_ids`). If the suite includes stale paths, filter the suite to only rows whose `gold_spans_path` exists before running.

## 8. Retired Surfaces

Removed from active benchmark contracts:
- `bench validate`, `bench run`, `bench sweep`, and `bench knobs` command surfaces
- pipeline-task span-IoU scoring as the primary benchmark truth
- upload-first interactive benchmark mode
- fast canonical alignment as an active scoring path

If older artifacts mention those paths, treat them as historical only.

## 9. Core Code Map

CLI and settings entrypoints:
- `cookimport/cli.py`: `labelstudio-benchmark` runtime, `bench` subcommands, and all-method orchestration wiring.
- `cookimport/config/run_settings.py`: validates and exposes `benchmark_sequence_matcher` options used by run configs/UI.
- `cookimport/config/run_settings_adapters.py`: shared `RunSettings` -> runtime kwargs adapters for stage and benchmark calls used by interactive + speed/quality flows.
- `cookimport/analytics/perf_report.py`: benchmark history CSV append helpers used by benchmark command flows.
- `cookimport/runs.py`: shared run-manifest model/writer used by speed/quality outputs.

Benchmark package modules:
- `cookimport/bench/eval_stage_blocks.py`: stage-block evaluator, mismatch diagnostics, and stage-block report formatting.
- `cookimport/bench/eval_canonical_text.py`: canonical-text evaluator, alignment, line-space scoring, and canonical eval report formatting.
- `cookimport/bench/prediction_records.py`: prediction-record schema v1 validation + read/write helpers for replay/evaluate-only flows.
- `cookimport/bench/report.py`: suite-level metric aggregation and markdown report formatting.
- `cookimport/bench/noise.py`: dedupe/consolidation helpers for prediction noise diagnostics.
- `cookimport/bench/cost.py`: estimated LLM review cost calculator and escalation queue writer (counting only; no model calls).
- `cookimport/bench/segmentation_metrics.py`: segmentation boundary metrics and deterministic error taxonomy.
- `cookimport/bench/segeval_adapter.py`: optional `segeval` metric adapter used only when requested and installed.
- `cookimport/bench/speed_suite.py`: deterministic speed target discovery, manifest I/O, and validation.
- `cookimport/bench/speed_runner.py`: speed scenario executor and speed-run summary/report generation.
- `cookimport/bench/speed_compare.py`: baseline-vs-candidate speed comparison and regression verdict/report formatting.
- `cookimport/bench/quality_suite.py`: deterministic quality target discovery (curated CUTDOWN focus IDs first, representative fallback, plus filename-match retry when importer-scored discovery is empty), manifest I/O, and validation.
- `cookimport/bench/quality_runner.py`: bounded-parallel all-method quality experiment executor and quality summary/report generation.
- `cookimport/bench/quality_compare.py`: baseline-vs-candidate quality comparison and regression verdict/report formatting.
- `cookimport/bench/sequence_matcher_select.py`: matcher selection contract, env parsing, and telemetry metadata.
- `cookimport/bench/dmp_sequence_matcher.py`: diff-match-patch backed SequenceMatcher adapter.
- `cookimport/bench/canonical_alignment_cache.py`: canonical alignment cache keys, disk cache, and lock recovery behavior.

## 10. See Also

- QualitySuite product-suite run flow: `docs/07-bench/qualitysuite-product-suite.md`
- Chronology and anti-loop notes: `docs/07-bench/07-bench_log.md`
- Latest parsing/processing signal snapshot: `docs/understandings/2026-03-01_11.14.18-qualitysuite-processing-parsing-signals.md`
- Detailed one-off perf profile (merged below): `2026-02-26 merged understanding: stage vs benchmark performance profile`

## 2026-02-26 merged understanding: stage vs benchmark performance profile (Feb 25-26)

Source merged from:
- `docs/understandings/2026-02-26_18.19.49-book-processing-vs-benchmark-performance-report.md`

Profile scope (captured from Feb 25-26 run roots):
- stage runs and single benchmark runs (`labelstudio-benchmark`)
- all-method benchmark runs and source-level scheduler telemetry
- run-local reports/histories (not only top-level `data/.history/performance_history.csv`)

High-signal runtime findings retained:
- Stage-block benchmark runs were prediction/conversion-bound in this sample:
  - `total_seconds` median `30.244s`
  - `prediction_seconds` median `30.143s`
  - `evaluation_seconds` median `0.086s`
- Canonical-text benchmark runs were evaluator/alignment-bound:
  - `total_seconds` median `188.198s`
  - `prediction_seconds` median `10.970s`
  - `evaluation_seconds` median `176.539s` (median eval share `94.48%`)
  - alignment subphase dominated eval time (`evaluate_alignment_seconds / evaluation_seconds` median `0.9958`)
- All-method source wall time was often dominated by long canonical eval tails while split-slot utilization remained low (for example heavy sources with low `heavy_slot_utilization_pct` and high `idle_gap_seconds`).

Durable interpretation guidance:
- Throughput work that speeds importer conversion, split conversion, and staged-write overhead benefits both `stage` and benchmark prediction phases.
- For canonical-text all-method wall-time, scorer alignment runtime is the first-order bottleneck; scheduler tweaks alone are usually insufficient.
- `stage` split merge and benchmark prediction split merge are separate implementations (`_merge_split_jobs` vs `_merge_parallel_results`) and can drift independently.

Telemetry anti-loop checks from this profile:
- Top-level `data/.history/performance_history.csv` did not contain complete production telemetry for this window; run-local artifacts were the reliable source.
- Processed stage reports in this window often lacked populated timing blocks, so stage wall-time inference came from benchmark prediction timings.
- If all-method appears "slow but underutilized," verify canonical eval-tail behavior before retuning split/admission knobs.

## 2026-02-27 Merged Understandings: All-Method Runtime and Anti-Loop Contracts

Merged source notes:
- `docs/understandings/2026-02-27_19.21.15-all-method-91-of-91-retry-eval-tail.md`
- `docs/understandings/2026-02-27_19.23.51-fallback-chain-includes-multilayer-before-stdlib.md` (historical)
- `docs/understandings/2026-02-28_03.05.00-sequence-matcher-locked-to-dmp.md`
- `docs/understandings/2026-02-27_19.24.31-stop-inflight-all-method-retries-with-worker-term.md`
- `docs/understandings/2026-02-27_19.31.54-all-method-canonical-cache-scope-and-lock-wait.md`
- `docs/understandings/2026-02-27_19.34.01-docs-task-retirement-target-mapping.md`
- `docs/understandings/2026-02-27_19.34.53-benchmark-vs-golden-2026-02-27-config-signal.md`
- `docs/understandings/2026-02-27_19.42.47-all-method-epub-extractor-default-scope.md`
- `docs/understandings/2026-02-27_19.46.17-bench-doc-prune-retired-surfaces.md`
- `docs/understandings/2026-02-27_19.47.10-all-method-eval-dedupe-hook-points.md`
- `docs/understandings/2026-02-27_19.49.45-all-method-tail-throughput-plan-audit.md`
- `docs/understandings/2026-02-27_19.51.07-bench-doc-code-map-completeness-audit.md`

Current-contract additions:
- In all-method progress, `config N/N` is first-pass planning only; retry attempts can continue after `N/N` is shown.
- Retry runs may not update the same dashboard counters (`dashboard_tracking=False`), so per-source `ok/fail` counters can look frozen while retries are still running.
- `scheduler heavy X/Y` reports split-active occupancy; `eval > 0` with one source left can indicate canonical-eval tail, not a deadlock.
- Canonical cache hits can still include long wall time when duplicate keys wait on the same lock owner; cache scope/persistence choices matter.
- Canonical alignment sequence matcher is now locked to `dmp`; archived matcher modes are rejected.
- Default all-method EPUB extractor variants are `unstructured` and `beautifulsoup`; markdown variants are opt-in via `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS=1`.
- If retries are stuck in canonical-eval tail, terminating active worker child PIDs (not the parent CLI PID) can let the run finalize and still write reports.
- Dedupe hook point is orchestration-level two phase: predict-only per config, then evaluate-only by unique signature.
- Benchmark docs should keep active-feature chronology and retire removed benchmark surfaces (pipeline-task span-IoU primary path, upload-first interactive benchmark, fast canonical alignment production path).

High-signal benchmark findings from `2026-02-27_17.54.41` all-method run:
- `91` planned configs, `82` successful; `thefoodlabCUTDOWN.epub` dominated wall time.
- Stable `unstructured v1` variants gave best reliability/perf trade-off in this run; `v2` variants showed large-source instability due worker termination failures.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_20.00.30 speed suite all method scenario scope
- Source: `docs/understandings/2026-02-27_20.00.30-speed-suite-all-method-scenario-scope.md`
- Summary: SpeedSuite originally exercised only stage-import and single-source canonical benchmark paths; multi-source all-method scheduling needed a suite-level scenario.

### 2026-02-27_20.04.16 speedsuite all method target matching single contract
- Source: `docs/understandings/2026-02-27_20.04.16-speedsuite-all-method-target-matching-single-contract.md`
- Summary: All-method matched-target discovery had drifted from SpeedSuite discovery; both now share speed_suite.match_gold_exports_to_inputs.

### 2026-02-27_20.07.10 all method eval signature cache and provenance
- Source: `docs/understandings/2026-02-27_20.07.10-all-method-eval-signature-cache-and-provenance.md`
- Summary: All-method now runs predict-only per config, then evaluates once per unique signature and reuses/materializes results.

### 2026-02-27_20.09.09 recipe notes variant zero pred in canonical benchmark
- Source: `docs/understandings/2026-02-27_20.09.09-recipe-notes-variant-zero-pred-in-canonical-benchmark.md`
- Summary: In 2026-02-27_17.54.41 canonical all-method runs, RECIPE_NOTES had zero predictions because stage evidence sources notes only from recipe comments, which were absent; RECIPE_VARIANT was also zero for amatteroftaste because no variant-prefixed instruction text was extracted.

### 2026-02-27_20.09.48 speedsuite runtime parity drift map
- Source: `docs/understandings/2026-02-27_20.09.48-speedsuite-runtime-parity-drift-map.md`
- Summary: SpeedSuite runs production entrypoints but still had duplicated run-settings-to-kwargs mapping across interactive and speed paths.

### 2026-02-27_20.43.12 quality suite reuse points
- Source: `docs/understandings/2026-02-27_20.43.12-quality-suite-reuse-points.md`
- Summary: QualitySuite can reuse speed-suite matching and all-method benchmark orchestration without adding new scoring engines.

### 2026-02-27_20.49.27 quality suite plan gap audit
- Source: `docs/understandings/2026-02-27_20.49.27-quality-suite-plan-gap-audit.md`
- Summary: QualitySuite planning gap audit: practical metric aggregation, strict patch validation, and sharded-source aggregation rules were the critical missing contracts.

### 2026-02-27_20.56.29 all method multi source scheduling vs global queue
- Source: `docs/understandings/2026-02-27_20.56.29-all-method-multi-source-scheduling-vs-global-queue.md`
- Summary: All-method bulk runs currently interleave at source-job level, but config scheduling/eval dedupe is per-source rather than one global mega-queue.

### 2026-02-27_20.56.32 all method source cap via cookimport setting
- Source: `docs/understandings/2026-02-27_20.56.32-all-method-source-cap-via-cookimport-setting.md`
- Summary: All-method multi-source concurrency is hard-capped by cookimport.json all_method_max_parallel_sources when set.

### 2026-02-27_21.00.19 og plan build status audit
- Source: `docs/understandings/2026-02-27_21.00.19-og-plan-build-status-audit.md`
- Summary: Audit result: the three OG plans for speed suite, all-method tail throughput, and eval-signature dedupe are implemented and covered by targeted tests.

### 2026-02-27_21.00.53 priority plans vs per label metric shape
- Source: `docs/understandings/2026-02-27_21.00.53-priority-plans-vs-per-label-metric-shape.md`
- Summary: Quick mapping from Priority 1-8 plan ideas to current per-label benchmark error shape.

### 2026-02-27_21.01.55 hix all method eval exit 1 lost error
- Source: `docs/understandings/2026-02-27_21.01.55-hix-all-method-eval-exit-1-lost-error.md`
- Summary: All-method Hix source failure with error `\"1\"` is a wrapped Typer exit that drops the underlying pre-eval message.

### 2026-02-27_21.08.11 quality suite shard aggregation and settings guard
- Source: `docs/understandings/2026-02-27_21.08.11-quality-suite-shard-aggregation-and-settings-guard.md`
- Summary: QualitySuite quality-run must source practical metrics from per-source winner reports and enforce strict run_settings_patch key validation before RunSettings normalization.

### 2026-02-27_21.29.02 all method scheduler scope dispatch and legacy payload fix
- Source: `docs/understandings/2026-02-27_21.29.02-all-method-scheduler-scope-dispatch-and-legacy-payload-fix.md`
- Summary: Global scheduler default changed multi-source test behavior; legacy combined payload also needed an explicit failed-config counter.

### 2026-02-27_22.25.29 priority8 current eval surface audit
- Source: `docs/understandings/2026-02-27_22.25.29-priority8-current-eval-surface-audit.md`
- Summary: Priority 8 audit: stage-block evaluator is classification-only today; segmentation metrics are still pending and should extend existing bench eval surfaces.

### 2026-02-27_22.47.26 priority8 segmentation implementation shape
- Source: `docs/understandings/2026-02-27_22.47.26-priority8-segmentation-implementation-shape.md`
- Summary: Priority 8 implementation shape: additive segmentation metrics/taxonomy live inside stage-block eval with optional segeval extras.

### 2026-02-28_00.25.56 benchmark option coverage map
- Source: `docs/understandings/2026-02-28_00.25.56-benchmark-option-coverage-map.md`
- Summary: Mapped Priority 2/3/5/6/7 option coverage across labelstudio-benchmark all-method and speed-suite flows, and confirmed Priority 8 knobs are eval-stage only.

### 2026-02-28_00.46.58 quality suite curated target selection
- Source: `docs/understandings/2026-02-28_00.46.58-quality-suite-curated-target-selection.md`
- Summary: Mapped how quality-suite target IDs are derived from pulled gold export folder slugs and where to enforce curated default selection.

### 2026-02-28_00.53.55 speed2-4 plan current value assessment
- Source: `docs/understandings/2026-02-28_00.53.55-speed2-4-plan-current-value-assessment.md`
- Summary: speed2-4 assumes non-DMP matcher experimentation, but canonical alignment is now DMP-only; plan is historical unless matcher experiments are intentionally re-opened.

### 2026-02-28_00.54.33 speed2-3 current value assessment
- Source: `docs/understandings/2026-02-28_00.54.33-speed2-3-current-value-assessment.md`
- Summary: speed2-3 delivered the high-ROI DMP matcher outcome; remaining milestones are low value given current cache/scheduler bottlenecks.

### 2026-02-28_01.06.42 quality-run cache scope and speed
- Source: `docs/understandings/2026-02-28_01.06.42-quality-run-cache-scope-and-speed.md`
- Summary: quality-run needed a persistent all-method canonical cache root across timestamped reruns to reuse alignment/eval-signature caches.

### 2026-02-28_01.20.10 qualitysuite levers schema v2
- Source: `docs/understandings/2026-02-28_01.20.10-qualitysuite-levers-schema-v2.md`
- Summary: Documented schema v2 lever expansion and optional all-method runtime knob patches in quality-run experiments files.

### 2026-02-28_01.24.58 speed suite run settings adapter parity
- Source: `docs/understandings/2026-02-28_01.24.58-speed-suite-run-settings-adapter-parity.md`
- Summary: SpeedSuite parity is primarily about sharing one RunSettings->kwargs adapter layer and carrying effective settings identity into speed artifacts/compare.

### 2026-02-28_01.34.14 quality suite validation stale target rows
- Source: `docs/understandings/2026-02-28_01.34.14-quality-suite-validation-stale-target-rows.md`
- Summary: quality-run validates all targets (not only selected IDs), so stale non-selected target rows can fail validation; filter suite rows to existing gold paths.

### 2026-02-28_03.05.00 sequence matcher locked to dmp
- Source: `docs/understandings/2026-02-28_03.05.00-sequence-matcher-locked-to-dmp.md`
- Summary: Canonical benchmark alignment now accepts only DMP matcher mode; fallback/stdlib/cydifflib/cdifflib/multilayer modes are archived and rejected.

## 2026-02-27 tasks consolidation (migrated from `docs/tasks`)

Merged task files (creation order in `docs/tasks`):
- `2026-02-27_18.51.16-speed-regression-benchmark-suite-from-pulled-goldens.md`
- `2026-02-27_19.45.53-all-method-eval-signature-dedupe.md`
- `2026-02-27_20.08.17-speed-suite-runtime-parity-single-path.md`
- `2026-02-27_20.43.12-quality-suite-representative-all-method-agent-loop.md`
- `2026-02-27_20.43.54-stage-block-recipe-notes-from-description.md`
- `2026-02-27_20.58.16-all-method-global-mega-run-scheduler.md`
- `priority-8.md`

Current bench contracts added/confirmed by those task files:
- Speed regression workflow is deterministic and first-class under `bench speed-discover`, `bench speed-run`, `bench speed-compare` with pulled Label Studio golds as default discovery source.
- All-method canonical evaluation uses deterministic eval signatures so prediction runs remain per-config while evaluation runs collapse to one-per-signature with in-run and cross-run reuse provenance.
- SpeedSuite is orchestrator-only and now relies on shared run-settings adapters; `run_settings_hash` is persisted and `speed-compare` fails by default on settings mismatch unless explicitly overridden.
- QualitySuite is implemented as deterministic representative discovery + bounded-parallel experiment runner (CPU-aware auto by default) + baseline/candidate comparator with strict/practical/source-coverage gates and strict patch-key validation.
- Stage-block prediction note labeling now includes description-derived recipe notes (in addition to schema comments), closing the zero-prediction `RECIPE_NOTES` gap for description-only recipes.
- Global mega-run scheduler is implemented for all-method multi-source runs (`scheduler_scope=global` default), with rollback path `scheduler_scope=legacy`.
- Priority 8 segmentation diagnostics are additive on existing stage-block contracts (`report.segmentation`, boundary mismatch JSONLs, optional `segeval` metrics).

Known anti-loop reminders from the merged task docs:
- Old speed runs without `run_settings_hash` will intentionally trip compare mismatch checks unless `--allow-settings-mismatch` is set.
- Global scheduler changes are orchestration-only; scoring semantics are intentionally unchanged.
- If RECIPE_NOTES regress to zero predictions, verify note sourcing includes description-derived notes before touching evaluator math.

## 2026-02-27_23.25.14 to 2026-02-28_00.11 migrated understandings digest (OGplan audit pack)

This batch consolidates the late-night OGplan audit set that cross-checked runtime code, tests, and stale OG checklist state.

### 2026-02-27_23.25.14 ogplan implementation audit refresh
- Source: `docs/understandings/2026-02-27_23.25.14-ogplan-implementation-audit-refresh.md`
- Summary: OGplan checklist state is stale; speed suite, tail throughput, eval-signature dedupe, global scheduler, and most Priority lanes are implemented in runtime/tests.

### 2026-02-27_23.25.40 ogplan eval signature dedupe audit
- Source: `docs/understandings/2026-02-27_23.25.40-ogplan-eval-signature-dedupe-audit.md`
- Summary: eval-signature dedupe is implemented in both scheduler scopes with in-run and cross-run reuse counters/provenance.

### 2026-02-27_23.26.10 ogplan audit live code check
- Source: `docs/understandings/2026-02-27_23.26.10-ogplan-audit-live-code-check.md`
- Summary: status model normalized to runtime+tests first; speed2-2 remains not implemented as written, speed2-4 remains partial/unwired, speed2-3 remains partial by design.

### 2026-02-27_23.26.52 ogplan global scheduler audit snapshot
- Source: `docs/understandings/2026-02-27_23.26.52-ogplan-global-scheduler-audit-snapshot.md`
- Summary: global scheduler core is shipped and defaulted, but manual all-matched smoke and deeper direct global-loop behavior tests were still open.

### 2026-02-27_23.31.29 all-method run settings forwarding audit
- Source: `docs/understandings/2026-02-27_23.31.29-all-method-run-settings-forwarding-audit.md`
- Summary: adapter supports `58` run-setting keys, all-method prediction path forwarded `25`, leaving `33` keys missing in that lane.

### 2026-02-27_23.34.54 ogplan priority 1-8 live audit
- Source: `docs/understandings/2026-02-27_23.34.54-ogplan-priority-1-8-live-audit.md`
- Summary: core Priority 2-8 runtime delivery is present; Priority 1 is partial relative to strict OG optional-additive backend matrix.

### 2026-02-28_00.11.05 ogplan audit consolidated status
- Source: `docs/understandings/2026-02-28_00.11.05-ogplan-audit-consolidated-status.md`
- Summary: merged view confirms global scheduler + dedupe architecture is active, with forwarding parity as the biggest remaining all-method correctness gap.

### 2026-02-28_00.19.46 all-method forwarding adapter parity
- Source: `docs/understandings/2026-02-28_00.19.46-all-method-forwarding-adapter-parity.md`
- Summary: all-method predict-only lane now builds kwargs from `build_benchmark_call_kwargs_from_run_settings(...)` plus explicit all-method overrides, removing manual dual-lane drift.

### 2026-02-28_00.43.39 global scheduler deep-tests and smoke closeout
- Source: `docs/understandings/2026-02-28_00.43.39-global-scheduler-deep-tests-and-smoke-closeout.md`
- Summary: Added direct global-loop tests for work-item interleaving and smart eval-tail admission, then recorded a successful real all-matched global smoke run (`14/14` configs successful) on `Hix written.docx` + `RoastChickenAndOtherStoriesCUTDOWN.epub`.

Current-contract additions from this audit pack:
- Completion precedence for benchmark planning claims is:
  1) runtime behavior in active code paths,
  2) focused tests passing,
  3) active `docs/plans/*.md` / task-state docs,
  4) OG checklist checkboxes (archival/stale).
- Global scheduler remains the default all-method scope with explicit rollback path `legacy`; manual smoke acceptance is now recorded for this audit family.
- All-method forwarding parity was the highest-risk interpretability gap in this audit family:
  - adapter key surface `58`,
  - all-method forwarded keys `25`,
  - missing in all-method forwarding `33`.
- Missing-forwarding families identified by the audit included:
  - Priority 1 recipe scoring knobs (`recipe_scorer_backend`, `recipe_score_*`)
  - Priority 3 splitter knobs (`multi_recipe_*`)
  - Priority 4 ingredient knobs (`ingredient_*`)
  - Priority 6 knobs (`p6_*`)
  - Priority 7 webschema knobs (`web_schema_*`, `web_html_text_extractor`)
  - output toggles (`write_label_studio_tasks`, `write_markdown`)
- Closure update:
  - `2026-02-28_00.19.46` migrated understanding records adapter-based forwarding parity for all-method predict-only execution.
  - all-method-specific behavior now applies as additive overrides on top of adapter payload (paths, cache/control flags, worker caps), rather than a separately maintained kwargs list.
  - `2026-02-28_00.43.39` adds direct global-loop internals tests (`_plan_all_method_global_work_items` interleaving and `_run_all_method_benchmark_global_queue` smart eval-tail admission), and records a manual all-matched smoke run at:
    - `data/golden/benchmark-vs-golden/2026-02-28_00.42.13_manual-all-matched-global-smoke/all-method-benchmark/all_method_benchmark_multi_source_report.md`
    - Key counters: `matched_target_count=2`, `total_config_runs_planned=14`, `total_config_runs_completed=14`, `total_config_runs_successful=14`, `global_queue_failed_configs=0`.
  - Smoke follow-up bugfix: all-method eval replay now normalizes missing `dimensions.epub_extractor` to `None` (instead of string `"None"`), so non-EPUB sources correctly fall back to default extractor behavior in evaluate-only replay.
- Ongoing guardrail:
  - keep `test_run_all_method_prediction_once_uses_adapter_forwarding_surface` as parity lock to prevent regression.
  - keep global-loop guards:
    - `test_plan_all_method_global_work_items_tail_pair_interleaves_sharded_sources`
    - `test_run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source`
    - `test_run_all_method_benchmark_global_queue_smart_eval_tail_admission`
    - `test_run_all_method_benchmark_global_queue_non_epub_eval_uses_default_extractor`

## 2026-02-28 migrated understandings digest (hotspots, quality-run behavior, Codex Farm bench)

### 2026-02-28_01.52.10 thefoodlab all-method hotspot summary
- Source: `docs/understandings/2026-02-28_01.52.10-thefoodlab-all-method-hotspot-summary.md`
- For run `data/golden/benchmark-vs-golden/2026-02-28_01.27.21/all-method-benchmark/thefoodlabcutdown`, wall time was prediction/split throughput bound, not canonical matcher/eval bound (`all_method_eval_wall_seconds` was ~0.64% of prediction wall).

### 2026-02-28_02.05.26 all-method serial fallback in sandbox
- Source: `docs/understandings/2026-02-28_02.05.26-all-method-serial-fallback-in-sandbox.md`
- In restricted runtimes where process workers cannot create multiprocessing semaphores, all-method preflights process-pool availability and falls back to thread-backed config workers (single-config fallback remains last resort if thread setup also fails).

### 2026-02-28_02.12.40 quality-run race pruning contract
- Source: `docs/understandings/2026-02-28_02.12.40-quality-run-race-pruning-contract.md`
- `quality-run` supports deterministic staged pruning via `--search-strategy race` (probe -> optional mid -> finalists on full suite) plus `--search-strategy exhaustive` for full-grid runs.
- Race ranking key order: mean `practical_f1`, mean strict `f1`, coverage count, then median duration.

### 2026-02-28_02.13.34 manual top-5 all-method replay
- Source: `docs/understandings/2026-02-28_02.13.34-manual-top5-all-method-replay.md`
- Confirmed practical replay pattern: rehydrate top configs from source `run_manifest.json`, normalize via `RunSettings.from_dict(...)`, and run one multi-source all-method sweep with a fixed explicit config set.

### 2026-02-28_02.28.08 quality-run global-to-legacy thread fallback
- Source: `docs/understandings/2026-02-28_02.28.08-quality-run-global-to-legacy-thread-fallback.md`
- Historical note (superseded): this described an earlier quality-run fallback that switched to legacy source-thread scheduling.

### 2026-02-28_02.28.30 quality leaderboard global config aggregation
- Source: `docs/understandings/2026-02-28_02.28.30-quality-leaderboard-global-config-aggregation.md`
- Global winner aggregation groups per-source variants by stable config key (`dimensions`/run-settings identity) and ranks by mean practical F1, strict F1, then coverage.
- The same grouped data supports Pareto analysis via median duration vs mean practical F1.

### 2026-02-28_02.33.20 quality-run serial root cause
- Source: `docs/understandings/2026-02-28_02.33.20-quality-run-serial-root-cause.md`
- Apparent serial quality-run behavior in this sandbox was environment-limited (`ProcessPoolExecutor` semaphore permission errors), not scheduler logic regression.

### 2026-02-28_04.16.21 all-method processpool semlock sandbox thread fallback
- Source: `docs/understandings/2026-02-28_04.16.21-all-method-processpool-semlock-sandbox-thread-fallback.md`
- Sandbox `/dev/shm` restrictions can block `SemLock`; all-method now keeps `global` scope and falls back to thread-backed config workers instead of immediate serial execution.

### 2026-02-28_02.58.54 codex-farm bench enablement smoke findings
- Source: `docs/understandings/2026-02-28_02.58.54-codex-farm-bench-enablement-smoke-findings.md`
- `bench speed-run`/`quality-run` Codex variants become effective with `--include-codex-farm` plus a resolvable `codex-farm` command.
- DOCX codex variant failed fast when no `full_text` blocks were available; EPUB-only smoke reached pass stages but had one observed stuck/no-final-summary session in this sandbox.

### 2026-02-28_03.04.14 qualitysuite profile save and cache boundaries
- Source: `docs/understandings/2026-02-28_03.04.14-qualitysuite-profile-save-and-cache-boundaries.md`
- Preferred profile path: `data/.history/preferred_run_settings.json`.
- Quality artifacts root: `data/golden/bench/quality/runs/<timestamp>/...` with leaderboard outputs under `leaderboards/<experiment_id>/<timestamp>/...`.
- Cache reuse boundary remains evaluation-aligned (alignment/eval-signature cache); new config variants still re-run prediction/import.

### 2026-02-28_03.08.55 quality leaderboard winner profile source of truth
- Source: `docs/understandings/2026-02-28_03.08.55-quality-leaderboard-winner-profile-source-of-truth.md`
- Winner settings should prefer `run_manifest.run_config.prediction_run_config` (when present) to match scored variant dimensions.
- `bench quality-leaderboard` now persists winner profile to `data/.history/qualitysuite_winner_run_settings.json` for interactive chooser reuse.

## 2026-02-28 migrated understandings batch (03:25-03:59)

The items below were merged from `docs/understandings` in timestamp order and folded into benchmark current-state guidance.

### 2026-02-28_03.25.10 quality-suite deterministic sweep coverage
- `bench quality-run` supports `--include-deterministic-sweeps` and forwards it through `_build_all_method_target_variants(...)`.
- Default remains off, so historical quality runs are unchanged unless explicitly enabled.
- Deterministic sweep coverage can be driven by this flag, schema-v2 experiment levers, or both.

### 2026-02-28_03.25.34 all-method 869 config count breakdown
- For one observed interactive run with deterministic sweeps enabled (`6` EPUB + `1` DOCX matched sources):
  - sweep payloads: `11` (`base`, nine single-knob variants, `all_upgrades`),
  - EPUB variants per sweep: `13`, DOCX variants per sweep: `1`,
  - total: `6 * 11 * 13 + 1 * 11 * 1 = 869`.
- Optional dependency presence changes sweep payload count (for that run: `pint` present; `pysbd`/`quantulum3` absent).

### 2026-02-28_03.27.17 preferred-profile is a seed, not a one-config lock
- Interactive `Run with preferred format` seeds base `RunSettings`; all-method variant expansion still runs.
- Example mix `6` EPUB + `1` DOCX yields `79` configs (`78` EPUB variants + `1` DOCX variant), not `7`.

### 2026-02-28_03.30.47 quality-run helpfulness workflow for deterministic sweeps
- To measure sweep usefulness: run `quality-run` with deterministic sweeps, then inspect `quality-leaderboard` by `dimensions.deterministic_sweep`.
- For cleaner one-knob attribution, keep sweep expansion off and use schema-v2 levers/experiments.

### 2026-02-28_03.32.48 single-profile all-matched benchmark mode
- Interactive benchmark has a middle path: `single_offline_all_matched` (one selected profile per matched target, no all-method permutations).
- Run cardinality is exactly matched target count, with outputs under `<run_ts>/single-profile-benchmark/<index_source_slug>/`.

### 2026-02-28_03.44.53 Codex Farm prompt expectations in single-profile mode
- `single_offline_all_matched` does not ask the all-method-only `Include Codex Farm permutations?` prompt.
- Single/offline/single-profile modes rely on run-settings `llm_recipe_pipeline`; all-method keeps its separate permutations prompt.

### 2026-02-28_03.58.19 speed-suite `max_targets` can explain tiny diagnostics samples
- Diagnostics can show `1 eval` when latest benchmark rows came from a speed-suite run with `max_targets=1`.
- Always check the latest speed run `suite_resolved.json` and `run_manifest.json` before treating low eval counts as dashboard breakage.

### 2026-02-28_03.59.44 benchmark split progress + worker-config sanitization
- Split conversion progress should use shared task-counter messaging (`task X/Y`, including initial `0/Y`) for spinner consistency.
- Split worker subprocess config should include only `RunSettings` keys; report-only metadata keys should stay in persisted run metadata, not worker init payloads.

## 2026-02-28 merged task specs (`docs/tasks` batch)

### 2026-02-28_00.45.27 quality-suite curated CUTDOWN defaults
- Source task: `docs/tasks/2026-02-28_00.45.27-quality-suite-curated-cutdown-targets.md`
- `bench quality-discover` now prioritizes curated focus IDs first when matched:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
- If curated IDs are absent, discovery keeps existing representative stratified fallback behavior.
- Keep selection logic centralized in quality-suite discovery so downstream quality-run behavior stays deterministic and unchanged.

### 2026-02-28_01.11.10 qualitysuite levers schema-v2 task merge
- Source task: `docs/tasks/2026-02-28_01.11.10-qualitysuite-levers.md`
- `bench quality-run` supports experiments schema v2 with `levers[]` and deterministic expansion:
  - optional baseline experiment,
  - one experiment per enabled lever,
  - optional `all_on` merged experiment.
- `all_on` merge is conflict-checked: if two enabled levers set the same key differently, expansion fails fast with explicit key conflicts.
- Schema v2 also supports `all_method_runtime_patch` (parallelism/timeouts/sharding/scheduler knobs) and validates runtime keys before execution.
- `experiments_resolved.json` is the canonical artifact for what was actually expanded and executed.

### 2026-02-28_02.28.08 quality-run process-blocked fallback to legacy source threads
- Source task: `docs/tasks/2026-02-28_02.28.08-quality-run-threaded-fallback-when-process-blocked.md`
- `bench quality-run` probes process-worker availability and adapts runtime when blocked.
- Adaptation applies when requested scheduler scope is `global`:
  - keep `global` scheduler scope,
  - run config workers on thread executor when process pools are unavailable.
- Historical note (superseded): this previously assumed experiment-level execution was always sequential; current runs are CPU-aware by default and still allow explicit bounded caps with `--max-parallel-experiments`.

## 2026-02-28 migrated understandings batch (04:07-10:02 sandbox throughput realities)

### 2026-02-28_04.07.00 quality-run race runtime under sandbox
- Source: `docs/understandings/2026-02-28_04.07.00-quality-run-race-runtime-under-sandbox.md`
- In this sandbox, process-worker probe failures can raise `PermissionError: [Errno 13]` and force fallback scheduling behavior that is materially slower.
- Observed representative-suite timings showed large EPUB shard configs around 129-133s each under fallback.
- Practical planning rule for this environment: representative deterministic race defaults can be an overnight run (roughly 8-10h), so use reduced targets/rounds for interactive validation.

### 2026-02-28_04.12.26 all-method split throughput optimization (merged task doc)
- Merged from former `docs/tasks/2026-02-28_04.12.26-all-method-split-throughput-optimization.md` (file removed after merge).
- Optimization focus was intentionally split/prediction throughput, not matcher/eval algorithm changes, based on newer hotspot evidence where prediction dominated wall time.
- Implemented/kept contracts from that task:
  - adaptive admission and split-slot resource-guard telemetry in both scheduler scopes (`global` + `legacy`),
  - matcher/cache regression guardrails as warning telemetry only (`matcher_guardrails`), with no scorer behavior changes,
  - prediction-reuse and split/convert-reuse counters in all-method report payloads,
  - predict-only all-method runs skip markdown/task artifact writes (`write_markdown=False`, `write_label_studio_tasks=False`).
- Baseline/candidate benchmark evidence captured in the task:
  - speed compare (`2026-02-28_02.54.07` -> `2026-02-28_09.57.10`) median total seconds `2.1447 -> 0.9532` (`-55.56%`) for `benchmark_all_method_multi_source`,
  - quality compare (`2026-02-28_02.54.03` vs `2026-02-28_09.57.37`) improved strict/practical F1 with unchanged source success rate.
- Anti-loop notes kept from the task:
  - compare verdicts can fail on `run_settings_hash` mismatch from `codex_farm_cmd` path differences even when LLM pipelines are off; use mismatch-allowed compares when validating throughput deltas.
  - zero split/convert reuse candidates on the default 13-config single-target EPUB profile is expected for that matrix and does not indicate broken reuse telemetry.

### 2026-02-28_04.16.21 all-method processpool semlock sandbox thread fallback
- Source: `docs/understandings/2026-02-28_04.16.21-all-method-processpool-semlock-sandbox-thread-fallback.md`
- Root cause in restricted runtimes: `/dev/shm` not writable -> multiprocessing `SemLock` setup fails.
- Current contract keeps all-method scheduler scope `global` and falls back to thread-backed config workers when process workers are unavailable.
- Serial single-config execution remains last-resort fallback only when thread executor setup fails.
- This supersedes older notes that implied immediate global-to-legacy scheduler downgrade on process-worker probe failure.

### 2026-02-28_10.02.42 all-method prediction reuse telemetry scope
- Source: `docs/understandings/2026-02-28_10.02.42-all-method-prediction-reuse-telemetry-scope.md`
- All-method reports now include `prediction_reuse_*` and `split_convert_reuse_*` counters plus schema-version markers for key payload contracts.
- Predict-only all-method benchmark calls now skip markdown and Label Studio task artifact writes (`write_markdown=False`, `write_label_studio_tasks=False`) to reduce prediction write overhead.
- On the default single-target 13-config EPUB quality profile, telemetry showed zero split/convert reuse candidates (instrumentation active, no natural duplicate conversion inputs in that matrix).

## 2026-02-28 merged understandings (09:33-10:20 quality-run controls and evidence)

The items below were merged from `docs/understandings` in source timestamp order.

### 2026-02-28_09.33.40 all-method adaptive admission and slot guard map
- Source: `docs/understandings/2026-02-28_09.33.40-all-method-adaptive-admission-and-slot-guard-map.md`
- All-method scheduling has three interacting controls: split-slot capping (`split_phase_slot_mode` and slot caps), split-worker capping (`split_worker_cap_*`), and adaptive admission decisions (`admission_active_cap`, `admission_guard_target`, `admission_reason`).
- Resource-guard slot capping is resolved once and applied consistently in both global-queue and legacy scheduler paths.
- Scheduler timeseries is the debug source of truth for refill/throughput changes (`adaptive_admission_*`, split-slot fields, CPU high-water).

### 2026-02-28_10.02.42 all-method prediction reuse telemetry scope
- Source: `docs/understandings/2026-02-28_10.02.42-all-method-prediction-reuse-telemetry-scope.md`
- Prediction reuse hashing intentionally excludes `benchmark_sequence_matcher` (evaluate-only field) while split/convert feasibility uses a narrower source+inputs key.
- Candidate run `2026-02-28_09.57.37` (13 configs) recorded `prediction_runs_executed=13`, `prediction_results_reused_in_run=0`, `split_convert_reuse_candidates=0`, `split_convert_reuse_safe_candidates=0`.
- Speed/quality compares can require `--allow-settings-mismatch` when baseline/candidate differ only by `codex_farm_cmd` string shape (`codex-farm` vs absolute path) even with LLM pipelines off.

### 2026-02-28_10.06.02 qualitysuite runtime cardinality and walltime
- Source: `docs/understandings/2026-02-28_10.06.02-qualitysuite-runtime-cardinality-and-walltime.md`
- `bench quality-run` total wall time grows roughly linearly with experiment count because experiment execution is orchestrated sequentially by default contract.
- Parallelism boundary is per experiment (all-method scheduler), not unlimited cross-experiment stacking.
- Concrete evidence in this repo:
  - `2026-02-28_00.54.37`: 3 targets / 39 configs / `2108.39s`.
  - `2026-02-28_03.39.35`: 1 target / 143 configs / `1133.07s`.
  - `2026-02-28_09.57.37`: 1 target / 13 configs / `232.41s` wall time with `1256.66s` summed source runtime (parallelized).
- Restricted environments that block process workers can materially increase wall time even when scheduler settings are unchanged.

### 2026-02-28_10.12.51 quality sweep signal and top-tier candidates
- Source: `docs/understandings/2026-02-28_10.12.51-quality-sweep-quality-signal-and-top-tier-candidates.md`
- Deterministic sweeps have not shown proven quality lift yet: run `2026-02-28_03.39.35` had identical best sweep and non-sweep metrics (`mean_practical_f1=0.411011`, `mean_strict_f1=0.389916`).
- Cross-source run `2026-02-28_00.54.37` still carries strongest multi-source signal; winner dimensions were `unstructured` extractor + `v1` parser + `semantic_v1` preprocess + `skip_headers_footers=true`.
- Latest single-source run `2026-02-28_09.57.37` confirms practical-vs-strict tradeoff families instead of one dominant profile.

### 2026-02-28_10.13.01 quality-run parallel experiment boundary
- Source: `docs/understandings/2026-02-28_10.13.01-quality-run-parallel-experiment-boundary.md`
- `run_quality_suite(...)` now supports bounded experiment-level parallelism via `max_parallel_experiments`.
- `summary.json` order remains deterministic by resolved experiment order, not completion order.
- Continue-on-failure behavior is unchanged: failed experiments are isolated to failed rows while other experiments continue.

### 2026-02-28_10.20.58 quality-run auto parallelism and load admission
- Source: `docs/understandings/2026-02-28_10.20.58-quality-run-auto-parallelism-and-load-admission.md`
- When `--max-parallel-experiments` is omitted, quality-run uses auto mode with effective cap `min(total_experiments, cpu_count, auto_ceiling)` where `auto_ceiling` defaults to detected `cpu_count` and is tunable via `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`.
- `experiments_resolved.json` persists requested/effective mode metadata (`max_parallel_experiments_requested`, `*_mode`, `*_effective`, `*_cpu_count`, `*_adaptive`).
- Auto mode uses load-aware admission: gradual ramp up under lighter pressure and immediate clamp under hotter load.

### Anti-loop checks from this batch
- If throughput differs between global and legacy scheduler scopes, verify split-slot capping and admission logic are mirrored in both paths before tuning new knobs.
- If reuse counters are zero on the 13-config EPUB profile, treat that as expected dataset shape unless input-key telemetry says otherwise.
- If quality compare verdict fails while metrics improved, inspect run-settings hash parity before treating results as a regression.

## 2026-02-28 merged understandings (10:31-11:12 certainty gates, codex confirmations, and sweep evidence)

The items below were merged from `docs/understandings` in source timestamp order.

### 2026-02-28_10.31.55 quality top-tier tournament baseline and gates
- Source: `docs/understandings/2026-02-28_10.31.55-quality-top-tier-tournament-baseline-and-gates.md`
- Cross-source run `data/golden/bench/quality/runs/2026-02-28_00.54.37` remains the strongest baseline signal for top-tier promotion and favored:
  - `epub_extractor=unstructured`
  - `epub_unstructured_html_parser_version=v1`
  - `epub_unstructured_preprocess_mode=semantic_v1`
  - `epub_unstructured_skip_headers_footers=true`
- Single-source runs (`2026-02-28_03.39.35`, `2026-02-28_09.57.37`) are useful probes but weaker certainty evidence for default promotion.
- Historical note: certainty gate thresholds were fixed in `data/golden/bench/quality/thresholds/2026-02-28_10.31.55_qualitysuite-top-tier-gates.json` for this batch; active phase workflow now uses `2026-03-01_01.00.00` / `2026-03-01_10.15.00` thresholds.

### 2026-02-28_10.35.58 qualitysuite codex-farm confirmation contract
- Source: `docs/understandings/2026-02-28_10.35.58-qualitysuite-codex-farm-confirmation-contract.md`
- `bench quality-run --include-codex-farm` requires explicit token confirmation:
  - `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Programmatic callers must pass `codex_farm_confirmed=True` to `run_quality_suite(...)` when Codex permutations are requested.

### 2026-02-28_10.41.47 speedsuite codex-farm confirmation contract
- Source: `docs/understandings/2026-02-28_10.41.47-speedsuite-codex-farm-confirmation-contract.md`
- `bench speed-run --include-codex-farm` requires explicit token confirmation:
  - `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Programmatic callers must pass `codex_farm_confirmed=True` to `run_speed_suite(...)` when Codex permutations are requested.

### 2026-02-28_10.44.48 quality-run sweep cardinality and stale-suite validation
- Source: `docs/understandings/2026-02-28_10.44.48-quality-run-sweep-cardinality-and-stale-suite-validation.md`
- `bench quality-run` validates every `targets[]` row in suite JSON, not only `selected_target_ids`; stale non-selected rows still fail the run.
- Regenerated curated suite runs confirmed selected set:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
- Enabling deterministic sweeps in race mode can multiply probe-round cardinality quickly (observed round-1 probe: `286` configs).
- If large runs are interrupted, `cannot schedule new futures after interpreter shutdown` can appear as interruption fallout and should not be treated as quality signal.

### 2026-02-28_10.56.43 deterministic sweep per-knob status
- Source: `docs/understandings/2026-02-28_10.56.43-deterministic-sweep-per-knob-status.md`
- Current completed sweep evidence from `data/golden/bench/quality/runs/2026-02-28_03.39.35` showed tied top rows across base and multiple sweep tags (no clear per-knob winner).
- Observed sweeps in that run:
  - `section_detector_backend`
  - `multi_recipe_splitter`
  - `ingredient_missing_unit_policy`
  - `instruction_step_segmentation_policy`
  - `p6_yield_mode`
  - `p6_temperature_unit_backend`
- Not observed in that run (dependency-gated or absent):
  - `p6_time_backend` alternates
  - `p6_temperature_backend` alternates
  - `instruction_step_segmenter=pysbd_v1`
- Current default remains: keep deterministic baseline settings until multi-source and multi-seed uplift is repeatable.

### 2026-02-28_11.12.24 qualitysuite seed variation and tournament cache/dedupe
- Source: `docs/understandings/2026-02-28_11.12.24-qualitysuite-seed-variation-and-tournament-cache-dedupe.md`
- Discovery now uses seed-driven representative fill after curated IDs, so multi-seed folds can produce distinct suites instead of duplicates.
- Tournament execution now sets a shared fold cache root (`COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`) for fold runs to reuse eval/cache artifacts across seeds.
- Tournament dedupes repeated suite signatures and excludes duplicate folds from execution and gate denominators.

### Anti-loop checks from this batch
- If Codex permutations are unexpectedly blocked, verify both CLI token confirmation and runner-level `codex_farm_confirmed` plumbing before changing variant builders.
- If sweep evidence looks contradictory, separate single-source probes from cross-source certainty runs before changing defaults.
- If multi-seed tournaments show no new evidence, inspect fold suite signatures first; duplicate-suite folds are intentionally skipped from denominators.

## 2026-02-28 task consolidation (`docs/tasks` quality + speed2-3 batch)

Merged task files (source creation order):
- `2026-02-28_10.09.34-quality-run-parallel-experiments.md`
- `2026-02-28_10.35.58-qualitysuite-codex-farm-confirmation-gate.md`
- `2026-02-28_10.41.47-speedsuite-codex-farm-confirmation-gate.md`
- `2026-02-28_14.30.18-qualitysuite-crash-safe-checkpoint-resume.md`
- `speed2-3.md` (historical plan covering 2026-02-27 to 2026-02-28)

Current benchmark/runtime contract from this batch:
- `bench quality-run` supports bounded experiment-level parallelism via `--max-parallel-experiments`.
- Omitting `--max-parallel-experiments` enables auto mode: `min(total_experiments, cpu_count, auto_ceiling)`, where `auto_ceiling` defaults to detected `cpu_count` and is tunable via `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`.
- In `/dev/shm`-restricted environments, quality-run can switch experiment fanout to subprocess workers (`COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE`) so throughput does not stay GIL-limited.
- Codex Farm variants are confirmation-gated:
  - speed: `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
  - quality: `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- QualitySuite crash safety is now first-class:
  - per-experiment snapshot: `experiments/<id>/quality_experiment_result.json`
  - run checkpoints: `checkpoint.json`, `summary.partial.json`, `report.partial.md`
  - explicit resume path: `bench quality-run --resume-run-dir <existing_run_dir>`
  - historical-only fold reuse path (script now disabled): `scripts/quality_top_tier_tournament.py --resume-tournament-dir ...`
- Sequence matcher runtime contract remains `dmp`-only (`COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp`); `stdlib` remains available only in `scripts/bench_sequence_matcher_impl.py` for parity/speed references.

Known caveat retained from speed2-3 closeout:
- Full-suite `speed-compare` at `warmups=0,repeats=1` is noisy enough to produce false regression FAILs on unchanged code. Re-run with warmups/repeats before treating a single FAIL as actionable regression evidence.

## 2026-02-28 to 2026-03-01 merged understandings (QualitySuite/SpeedSuite reliability and fast-answer flows)

Merged source notes (chronological):
- `docs/understandings/2026-02-28_11.14.44-qualitysuite-seed-variation-and-tournament-cache-dedupe.md`
- `docs/understandings/2026-02-28_11.18.07-quality-tournament-gate-impossibility-pruning.md`
- `docs/understandings/2026-02-28_11.33.22-quality-run-auto-cap-ceiling-and-ramp.md`
- `docs/understandings/2026-02-28_11.45.55-qualitysuite-low-cpu-due-shm-permission-and-thread-fallback.md`
- `docs/understandings/2026-02-28_12.00.19-quality-run-subprocess-experiment-fallback-for-shm-restricted-hosts.md`
- `docs/understandings/2026-02-28_13.24.03-qualitysuite-crash-and-sweep-signal-check.md`
- `docs/understandings/2026-02-28_13.27.30-speed2-3-closure-dmp-selector-stdlib-script.md`
- `docs/understandings/2026-02-28_14.36.24-qualitysuite-checkpoint-resume-surface-map.md`
- `docs/understandings/2026-02-28_14.40.12-full-speedsuite-serial-mode-and-variance.md`
- `docs/understandings/2026-02-28_14.46.40-deterministic-sweep-must-include-decision-snapshot.md`
- `docs/understandings/2026-02-28_14.51.46-speedsuite-serial-task-loop-and-no-resume-contract.md`
- `docs/understandings/2026-02-28_15.01.40-qualitysuite-hot-cpu-io-guard-profile.md`
- `docs/understandings/2026-02-28_15.19.25-processpool-restored-session-probe.md`
- `docs/understandings/2026-02-28_15.31.28-speedsuite-parallel-checkpoint-resume-contract.md`
- `docs/understandings/2026-02-28_15.48.23-qualitysuite-tournament-sweeps-workload-and-prediction-reuse-scope.md`
- `docs/understandings/2026-02-28_16.27.10-prediction-reuse-cross-root-same-config-dir-guard.md`
- `docs/understandings/2026-02-28_20.20.04-fast-shortlist-fold-gate-impossibility-and-sweeps-decision-thresholds.md`
- `docs/understandings/2026-02-28_20.35.43-qualitysuite-live-eta-queue-aware.md`
- `docs/understandings/2026-02-28_20.50.43-qualitysuite-when-prior-tournament-results-are-reusable.md`
- `docs/understandings/2026-02-28_21.01.58-qualitysuite-race-finalists-no-prune-overhead.md`
- `docs/understandings/2026-02-28_21.14.34-qualitysuite-live-work-units-can-rise-during-normal-scheduling.md`
- `docs/understandings/2026-02-28_21.29.32-quality-tournament-quick-overrides-for-fast-parsing-answer.md`
- `docs/understandings/2026-02-28_21.51.19-quality-lightweight-series-entrypoint-and-profile-contract.md`
- `docs/understandings/2026-03-01_00.20.00-quality-lightweight-series-fold-reuse-and-summary-contract.md`

Current benchmark contract additions from this batch:

- Multi-seed tournament evidence handling is stricter and cheaper:
  - Suite selection now varies by seed after curated IDs, duplicate suite signatures are skipped, and gate denominators use unique folds only.
  - Candidates can be pruned early when optimistic best-case remaining folds still cannot satisfy gates.
  - Fast shortlist thresholds must be feasible for planned unique folds (for example `min_completed_folds=2` when only 2 unique folds are possible).

- QualitySuite throughput and runtime shape are now explicitly environment-aware:
  - Auto parallel cap/ramp is more aggressive (`auto_ceiling` default follows detected `cpu_count`; env override supported).
  - In restricted runtimes, quality-run can switch experiment fanout to subprocess mode while keeping deterministic outputs.
  - In unrestricted runtimes, SemLock/process-pool bottlenecks may disappear; tuning should then focus on run-shape knobs instead of fallback paths.

- Crash-safety and resume boundaries are now first-class contracts:
  - Quality run-level checkpoints/partials + per-experiment snapshots support `--resume-run-dir`.
  - SpeedSuite now supports bounded task parallelism, per-sample snapshots, and resume compatibility checks.
  - Historical note retained: old SpeedSuite contract was serial-only with no resume; this is no longer true.

- Sweep and search strategy guidance is now explicit:
  - Completed sweep evidence still does not justify any must-enable deterministic-sweep default.
  - Race mode can be a pure overhead path when `race_finalists >= variant_count` (common on no-sweeps profiles).
  - For parser-setting answers, quick overrides (`--quick-parsing`, candidate/seed clamps, forced exhaustive/no-sweeps) are the preferred fast path.

- Cache/reuse boundaries are now documented clearly:
  - Prediction reuse can span rounds/experiments/folds when shared cache roots are used.
  - Cross-root reuse no longer rejects same-named config dirs if source artifact paths differ.
  - Final tournament-result reuse is valid only for full input-tuple matches; cache hits do not imply full result memoization.

- Operator-facing status semantics were hardened:
  - Live ETA includes queued-wave estimation and completed-duration fallback.
  - `work_units` is a weighted estimator and can increase during normal scheduling transitions.

- Lightweight series contract:
  - Should remain a first-class bench command using a versioned profile file.
  - Should reuse fold-level quality-run outputs and derive winners/risk from fold summary means/deltas (no new scorer).

Anti-loop reminders from this batch:
- If tournament runtime explodes, measure variant cardinality and race survivor math before changing evaluator/scorer code.
- If folds rerun unexpectedly, distinguish artifact-level cache reuse from final-result reuse eligibility.
- If live ETA/work-units look odd, validate queue state and weighted estimator behavior before treating status output as broken.
- If a no-sweeps race run is slower than exhaustive, inspect `race_finalists` against actual variant count first.

## 2026-03-01 merged understandings (two-phase closure + suite-shape consolidation)

Merged source notes (chronological):
- `docs/understandings/2026-03-01_01.30.00-qualitysuite-parsing-two-phase-runtime-closure.md`
- `docs/understandings/2026-03-01_10.20.00-qualitysuite-auto-handoff-and-phase-recommendation.md`
- `docs/understandings/2026-03-01_10.20.19-qualitysuite-plan-stack-redundancy-and-suite-shape.md`
- `docs/understandings/2026-03-01_10.26.08-qualitysuite-defaults-cleanup-and-product-suite-guide.md`

Current benchmark contract additions from this batch:
- Tournament seed precedence is explicit and deterministic:
  - explicit `--seed` / `--seed-list` are deduped in sequence order first,
  - `--max-seeds` then caps the resolved list,
  - fallback seed plans are recorded with source metadata in `tournament_resolved.json`.
- Race-mode no-prune is now surfaced and auto-collapsed:
  - when `variants_effective <= race_finalists`, tournament execution uses one exhaustive pass and records `reason=race_no_prune_variant_count_le_finalists`.
- Fold-level progress can be inspected and promoted in-flight:
  - fold `quality-run` checkpoints expose `experiment_count_total`, `experiment_count_completed`, and `pending_experiment_ids`,
  - active fold progress is mirrored into `tournament_checkpoint.json`.
- Prediction reuse provenance distinguishes local and cross-run reuse:
  - `reused_in_run` when artifacts come from current run root,
  - `reused_cross_run` when cache sources are outside the current run root.
  - hardlink-first artifact materialization with safe copy fallback remains the write contract.
- Phase A -> Phase B auto-handoff now includes a deterministic recommendation heuristic:
  - explicit `--candidate-experiment-id` always wins,
  - auto-candidate mode chooses one candidate when top candidate is winner/tied-top across all unique evaluated folds with at least two unique folds,
  - auto-candidate mode chooses two candidates when top-two mean practical deltas are within `0.003`,
  - recommendation metadata is written to tournament `summary.json` and `report.md` (`phase_a_promotion_recommendation`).
- Official phase defaults and preset hygiene were consolidated:
  - tournament defaults point to `2026-03-01_01.00.00` parser Phase A candidate/threshold files,
  - exact duplicate preset `2026-02-28_14.58.21_qualitysuite-top-tier-tournament-hot-io-guard.json` was removed as byte-identical to `2026-02-28_16.24.30_qualitysuite-top-tier-tournament-full-candidates.json`,
  - active-vs-legacy preset status is tracked in `data/golden/bench/quality/README.md`.
- Product surface is now intentionally focused on direct quality-run flows:
  1. `bench quality-run` for experiment execution,
  2. `bench quality-leaderboard` for winner analysis,
  3. `bench quality-compare` for regression gates.
- Historical note: `bench quality-lightweight-series` and `scripts/quality_top_tier_tournament.py` are retired/disabled.

Anti-loop reminders from this batch:
- If tournament path selection feels contradictory, check explicit candidate override precedence before tuning heuristics.
- If race mode unexpectedly runs long, inspect `variants_effective` versus `race_finalists` first.
- If reuse labeling seems wrong, verify whether source artifacts are inside the current run root before changing reuse math.
- If preset debates restart, use `data/golden/bench/quality/README.md` active/legacy map and keep retired duplicates removed.

## 2026-03-01 docs/tasks merge (SpeedSuite + QualitySuite)

Merged task files from `docs/tasks` (source creation order):
- `2026-02-28_14.55.16-speedsuite-parallel-and-resume.md`
- `2026-02-28_15.49.40-qualitysuite-fast-profile-and-shared-prediction-reuse.md`
- `2026-02-28_20.35.43-qualitysuite-live-eta-queue-aware.md`
- `2026-02-28_21.43.13-qualitysuite-lightweight-main-effects-series.md`
- `2026-02-28_22.08.25-qualitysuite-parsing-accuracy-two-phase-and-runtime-waste-cuts.md`

### 2026-02-28_14.55.16 SpeedSuite parallel + resume contract
- `bench speed-run` supports bounded task fanout with `--max-parallel-tasks` (auto mode when omitted).
- Crash-safe artifacts are first-class:
  - `checkpoint.json`
  - `summary.partial.json`
  - `report.partial.md`
  - `samples.partial.jsonl`
  - per-sample `speed_sample_result.json`
- Resume contract:
  - `bench speed-run --resume-run-dir <run_dir>`
  - strict compatibility check on suite/targets/scenarios/warmups/repeats/run-settings/Codex confirmation flags.
- Durable implementation detail:
  - task orchestration uses thread-level dispatch for bounded fanout and simpler checkpoint flushing.

### 2026-02-28_15.49.40 fast tournament profile + shared prediction reuse
- Top-tier fast profiles reduced workload by default (no sweeps, narrower race breadth, shortlist-first/finalist split artifacts).
- Prediction reuse now supports shared cache roots across rounds/experiments/folds instead of single-run-root scope only.
- Cross-root reuse preserves key semantics and stores absolute source artifact paths so reuse can remain deterministic.
- Tournament script exports shared prediction reuse env to fold runs, parallel to alignment cache sharing.

### 2026-02-28_20.35.43 queue-aware live ETA
- Live ETA includes queued experiments, not only active ones.
- ETA uses completed-duration fallback when active telemetry is sparse.
- Status output includes queued counts to explain optimistic/pessimistic shifts.
- Keep interpreting ETA as heuristic under heterogeneous experiment costs.

### 2026-02-28_21.43.13 lightweight main-effects series
- Added first-class `bench quality-lightweight-series` (profile-driven orchestration, not scorer rewrite).
- Flow contract is three-round:
  - Round 1 main-effects screening by category.
  - Round 2 combined-winner composition check.
  - Round 3 interaction smoke tests.
- Artifacts:
  - `lightweight_series_summary.json`
  - `lightweight_series_report.md`
  - per-round fold directories with reused quality-run outputs.
- Resume safety uses two layers:
  - series-level compatibility hash checks,
  - fold-level quality-run artifact reuse.

### 2026-02-28_22.08.25 two-phase parser workflow + runtime waste cuts
- Two-phase parser workflow artifacts were productized (Phase A shortlist + Phase B confidence) with product-suite commands.
- Race mode auto-falls back to exhaustive when pruning is impossible (`variants_effective <= race_finalists`), with reason metadata in artifacts.
- Tournament supports explicit seed resolution (`--seed`, `--seed-list`) with deterministic metadata in `tournament_resolved.json`.
- Live tournament subprogress is surfaced from fold checkpoints and mirrored to `tournament_checkpoint.json`.
- Prediction reuse materialization is hardlink-first with copy fallback; reuse telemetry distinguishes in-run vs cross-run sources.

### 2026-03-01_09.48.35 gap closure follow-through
- Added Phase A -> Phase B auto-handoff flags:
  - `--auto-candidates-from-summary`
  - `--auto-candidates-from-latest-in`
- Promotion heuristic now drives both auto-selection and summary/report recommendation block (`phase_a_promotion_recommendation`).
- Added optional Phase B+ sweeps-decision threshold profile and operator guidance.
- Threshold defaults can set `quality_run.max_parallel_experiments_default` (CLI override still wins).
- Explicit seed inputs now support cap semantics (`dedupe explicit list` then `--max-seeds` cap) with provenance metadata.

Anti-loop notes from this merge:
- If phase handoff behavior looks wrong, inspect candidate-source precedence metadata before changing filters.
- If race mode still looks slow, compare effective variant count against finalists before touching scoring logic.
- If reuse speedups disappear, verify hardlink availability/fallback telemetry before changing cache keys.

## 2026-03-01 to 2026-03-02 docs/tasks merge (QualitySuite guardrails and preset hygiene)

Merged task files (source creation order):
- `2026-03-01_11.47.33-qualitysuite-wsl-safety-guard.md`
- `2026-03-01_12.23.08-qualitysuite-wsl-single-slot-guard.md`
- `2026-03-01_19.47.08-disable-quality-lightweight-series-cli.md`
- `2026-03-01_19.51.35-disable-quality-top-tier-tournament-script.md`
- `2026-03-01_19.56.27-qualitysuite-unhobble-parallelism.md`
- `2026-03-01_23.16.19-qualitysuite-wsl-guard-restore-after-oom.md`
- `2026-03-02_00.08.28-qualitysuite-agent-spinner-noise.md`
- `2026-03-02_00.36.30-qualitysuite-drop-regressive-parser-candidates-from-active-presets.md`

Current-contract additions:
- WSL guardrails are active by default for quality runs, including single-slot runs; opt-out remains explicit via `COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD=1`.
- The short-lived unhobble attempt (`2026-03-01_19.56.27`) is historical only; OOM evidence led to guard restoration (`2026-03-01_23.16.19`).
- Retired high-cost surfaces are intentionally fail-fast:
  - `bench quality-lightweight-series`
  - `scripts/quality_top_tier_tournament.py`
- Agent terminals default benchmark progress to plain change-only lines (`CODEX_CI=1`, `CODEX_THREAD_ID`, `CLAUDE_CODE_SSE_PORT`) with explicit override via `COOKIMPORT_PLAIN_PROGRESS=1|0`.
- Active QualitySuite presets point to pruned `2026-03-02_00.36.30` files that removed:
  - `pre_br_split`
  - `pre_none`
  - `skip_headers_false`
  - `parser_v2_pre_br_skiphf_false`
- Historical timestamped preset snapshots remain intentionally untouched for replay/debug provenance.

Anti-loop reminders:
- If WSL runs destabilize again, inspect `experiments_resolved.json` guard telemetry before editing scheduler internals.
- If old parser candidates reappear, audit active preset pointers/default file references first, not archived snapshots.
- If a workflow still references lightweight-series/tournament commands, treat that as stale operator guidance and route to quality-run/leaderboard/compare.

## 2026-03-02 merged understandings digest (artifact cutdowns and interactive paired contract)

Merged sources (chronological):
- `docs/understandings/2026-03-02_00.38.06-qualitysuite-active-vs-legacy-preset-pruning-path.md`
- `docs/understandings/2026-03-02_07.55.57-codexfarm-benchmark-need-to-know-artifacts.md`
- `docs/understandings/2026-03-02_08.14.12-correct-snippet-sampling-from-canonical-eval-artifacts.md`
- `docs/understandings/2026-03-02_08.45.38-benchmark-cutdown-script-run-shape-and-pairing.md`
- `docs/understandings/2026-03-02_08.50.19-interactive-single-offline-paired-run-failure-contract.md`
- `docs/understandings/2026-03-02_11.26.00-interactive-benchmark-write-flags.md`

Current-contract additions:
- QualitySuite preset pruning should target active preset pointers/default references (CLI defaults + docs references), not in-place edits to historical timestamped snapshots. Keep legacy snapshots immutable for replay/debug provenance.
- For external-AI benchmark sharing, the high-signal minimal artifact set remains:
  - `run_manifest.json` (or compact subset with `run_config` and source identity)
  - `eval_report.md` (if present) + key scalar metrics from `eval_report.json`
  - bounded qualitative samples from `wrong_label_lines.jsonl`, `missed_gold_lines.jsonl`, `unmatched_pred_blocks.jsonl`
- Large raw payload bundles (`prediction-run/raw/**`, full extracted payload artifacts, full diagnostics arrays) are debug artifacts, not required for codex-vs-baseline quality judgment.
- Positive "correct" examples can be derived deterministically from canonical artifacts by taking canonical line indices absent from `wrong_label_lines.jsonl` and writing a capped sample file.
- Crossover run pairing for codex-vs-baseline cutdowns should group by `source_hash` (fallback: source filename) and treat baseline pipeline values as `{off, none, ""}`.
- C3imp interactive `single_offline` codex-enabled runs should preserve the current failure-safe contract:
  - run `vanilla` first,
  - run `codexfarm` second,
  - keep successful vanilla artifacts even if codex variant fails,
  - write comparison artifacts only when both succeed.
- Interactive benchmark sidecar writes stay env-driven and default-disabled in C3imp sessions:
  - `COOKIMPORT_BENCH_WRITE_MARKDOWN`
  - `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS`

## 2026-03-02 merged understandings digest (single-offline pairing + benchmark queue robustness)

Merged sources (chronological):
- `docs/understandings/2026-03-02_09.10.14-interactive-single-offline-paired-benchmark-contract.md`
- `docs/understandings/2026-03-02_10.10.43-benchmark-pool-picklability-debug-note.md`

Current-contract additions:
- Interactive single-offline codex runs keep baseline safety contract:
  - execute `single-offline-benchmark/<source_slug>/vanilla` first,
  - execute `single-offline-benchmark/<source_slug>/codexfarm` second,
  - preserve vanilla artifacts if codex fails,
  - write `codex_vs_vanilla_comparison.json` only when both succeed.
  - write `single_offline_summary.md` only when markdown writes are enabled.
- `_run_all_method_benchmark_global_queue` now probes callback function picklability before enabling process-pool parallelization; local/unpicklable monkeypatches trigger fallback to `ThreadPoolExecutor`.
- Benchmark all-method queue execution remains deterministic about config retries and fallback transport so benchmark reproducibility is preserved on restricted multiprocessing hosts.

## 2026-03-02 docs/tasks merge (interactive benchmark behavior and CodexFarm compare semantics)

### 2026-03-02_08.36.21 codexfarm-vanilla paired single-offline layout

Current behavior now:
- Interactive `labelstudio_benchmark` single-offline mode now writes one session root with nested variant folders:
  - `<timestamp>/single-offline-benchmark/<source_slug>/vanilla/...`
  - `<timestamp>/single-offline-benchmark/<source_slug>/codexfarm/...`
- Paired codex+vanilla runs share split conversion artifacts through a single-offline cache (`<timestamp>/single-offline-benchmark/<source_slug>/.split-cache` by default), so the second variant reuses conversion payloads instead of re-running split conversion.
- When CodexFarm is enabled, `vanilla` runs first and `codexfarm` second; vanilla artifacts remain even if Codex run fails.
- `codex_vs_vanilla_comparison.json` appears only when both variant runs complete successfully.
- `single_offline_summary.md` appears only when markdown writes are enabled and consolidates markdown output for the session.
- Comparison payload now includes optional `metadata.single_offline_split_cache` summary (shared key + per-variant hit/mode/conversion timing) when cache metadata is available.
- Comparison payload also includes optional `metadata.codex_farm_runtime` with `codex_model` and `codex_reasoning_effort` (resolved from run config, with llm-manifest fallback; `<default>` now resolves through Codex config `model_reasoning_effort` when available).
- Comparator output follows `codex_vs_vanilla_comparison.v2` schema with explicit canonical metric deltas.
- Comparison JSON and markdown now use explicit canonical metric names (`strict_accuracy`, `macro_f1_excluding_other`) rather than legacy alias keys.

Related understanding:
- `docs/understandings/2026-03-03_00.35.00-single-offline-split-cache-reuse.md`

Operational contract:
- Layout contracts are consumed by analytics collector/renderer without dedicated registration, because run discovery resolves eval reports recursively and infers run timestamps from nearest timestamped parent.

### 2026-03-02_09.37.43 recipeimport-side benchmark-native CodexFarm integration

Current behavior now:
- Recipeimport now carries benchmark-mode intent explicitly via `codex_farm_recipe_mode` (`extract|benchmark`) while preserving extraction behavior.
- `labelstudio-benchmark compare` supports named acceptance gates and explicit pass/fail reporting.
- Compare flow can include artifact-presence checks for benchmark-mode expectations and still supports legacy/all-method/evaluation-only scenarios.

Where this behavior is implemented:
- `cookimport/cli.py` for orchestration + compare path
- `cookimport/config/run_settings*` for mode propagation
- `cookimport/llm/codex_farm_orchestrator.py` + `codex_farm_runner.py` for invocation details
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` for mode-specific semantics and failure behavior

### 2026-03-02_11.57.58 compare strictness inference and warnings

Current behavior now:
- `labelstudio-benchmark compare` no longer hard-fails when benchmark metadata is missing.
- Mode is resolved as `metadata`, `inferred`, or `unknown`.
- Missing `codex_farm_recipe_mode` no longer blocks legacy outputs; benchmark-only checks can run if artifacts imply benchmark mode, with explicit warnings carried to console and comparison artifacts.
- Unknown mode skips benchmark-only checks as N/A and records warning(s).

Known warning signals to watch:
- "benchmark mode inferred; metadata missing" and equivalent warning list in comparison output indicate reduced certainty, not silent fallback.


## 2026-03-03 merged understandings digest

This batch consolidates benchmark behavior notes that were previously isolated in `docs/understandings/`.

Key benchmark contracts to keep:
- Interactive single-offline runs now resolve source/gold once per session and reuse it across variants; outputs are nested under a source slug.
- Comparison artifacts use explicit metric naming/schema and preserve legacy compatibility only where needed for older consumers.
- Markdown output controls should gate summary sidecars consistently; single-offline emits one session-root markdown summary when enabled.
- CodexFarm prompt-debug artifacts now require full per-call JSONL logs; category-specific text logs are additive convenience views.
- Benchmark cutdown packaging should prefer full logs for sampling and only fall back to legacy text logs.
- Split-cache reuse and manifest-driven runtime metadata resolution are intentional performance/consistency contracts.

Chronological merged source notes:
- 2026-03-02_12.10.59-single-offline-source-selection-reuse: Single-offline benchmark source selection fix
- 2026-03-02_19.58.15-benchmark-cutdown-sampling-flow: How benchmark_cutdown_for_external_ai currently trims diagnostics and where the biggest info loss happens.
- 2026-03-02_20.03.20-codexfarm-benchmark-prompt-log: Benchmark run now writes codex-farm prompt/request-response text logs to the eval run folder.
- 2026-03-02_21.41.40-benchmark-markdown-artifact-toggle-scope: `write_markdown` previously gated stage sidecars but not benchmark summary markdown outputs.
- 2026-03-02_21.49.36-benchmark-cutdown-prompt-log-source-and-3pairs: benchmark_cutdown now resolves prompt log path via run_manifest and samples 3 full pairs per category by default.
- 2026-03-02_21.52.38-single-offline-one-markdown-summary-contract: Interactive single-offline benchmark now consolidates markdown into one session-root summary file.
- 2026-03-02_22.09.25-single-offline-default-reasoning-effort-resolution: Single-offline comparison resolves `<default>` Codex reasoning effort using Codex config defaults.
- 2026-03-02_22.10.00-single-offline-comparison-codex-runtime-source: Single-offline codex-vs-vanilla comparison should derive Codex model/reasoning from run manifests with llm-manifest fallback.
- 2026-03-02_22.11.31-canonical-comparison-metric-aliases: Single-offline canonical comparison shows duplicated precision/recall/f1 and practical_* by design.
- 2026-03-02_22.18.48-single-offline-explicit-metric-names: Single-offline comparison markdown now reports explicit canonical metrics instead of legacy alias rows.
- 2026-03-02_22.21.31-single-offline-comparison-per-label-aggregation: Single-offline comparison per-label breakdown should use dashboard-style weighted aggregation across variant eval reports.
- 2026-03-02_22.24.14-single-offline-comparison-schema-v2-explicit-metrics: Single-offline comparison backend now uses schema v2 with explicit canonical metric keys only.
- 2026-03-02_22.40.00-single-offline-session-root-source-slug: Interactive single-offline benchmark now nests session artifacts under a source-derived slug.
- 2026-03-02_22.46.55-codexfarm-full-prompt-log-contract: CodexFarm benchmark artifacts now require a complete per-call full_prompt_log.jsonl.
- 2026-03-02_22.54.55-canonical-benchmark-boundary-metric-source: Canonical-text benchmark runs were missing dashboard boundary metrics because eval_report.json did not emit a top-level boundary object.
- 2026-03-02_23.02.50-cutdown-prompt-sampling-prefers-full-log: benchmark_cutdown convenience prompt samples now prefer full_prompt_log.jsonl and only fall back to legacy text logs.
- 2026-03-02_23.12.13-qualitysuite-mixed-format-discovery-notes: Current-state notes on how QualitySuite handles (and hides) source formats like PDF vs EPUB.
- 2026-03-02_23.23.00-codexfarm-benchmark-prompt-category-logs: CodexFarm benchmark prompt logging now emits per-task category files plus a manifest for human review.
- 2026-03-03_00.00.00-benchmark-cutdown-prompt-log-sampling: Benchmark cutdown keeps sampled prompt text as convenience while preserving full per-call JSONL logs.
- 2026-03-03_00.35.00-single-offline-split-cache-reuse: Single-offline split-cache reuse wiring

## 2026-03-03 docs/tasks merge digest (single-offline comparison, prompt logs, and cutdown context)

Merged source task files (chronological):
- `docs/tasks/2026-03-02_18.30.00-single-offline-benchmark-split-cache.md`
- `docs/tasks/2026-03-02_19.59.00 - expand benchmark cutdown context.md`
- `docs/tasks/2026-03-02_21.41.40 - benchmark-markdown-artifact-gating.md`
- `docs/tasks/2026-03-02_21.42.47 - align single-offline comparison markdown table.md`
- `docs/tasks/2026-03-02_21.52.38 - interactive-single-offline-one-markdown-summary.md`
- `docs/tasks/2026-03-02_22.09.34 - resolve-default-codex-reasoning-in-single-offline-comparison.md`
- `docs/tasks/2026-03-02_22.18.32 - single-offline-comparison-metric-names.md`
- `docs/tasks/2026-03-02_22.21.30 - add-single-offline-per-label-breakdown-to-comparison-artifacts.md`
- `docs/tasks/2026-03-02_22.29.20 - remove-benchmark-eval-metric-alias-fields.md`
- `docs/tasks/2026-03-02_22.46.55 - full codexfarm prompt log export.md`
- `docs/tasks/2026-03-02_22.54.22 - canonical-benchmark-boundary-metrics.md`
- `docs/tasks/2026-03-02_23.20.00 - codexfarm benchmark prompt category logs.md`
- `docs/tasks/2026-03-02_23.32.41 - qualitysuite-ogplan-audit-fixes-spec.md`

Current contract additions:
- Paired single-offline codex/vanilla runs should reuse split conversion via one shared split-cache key (cache key intentionally excludes LLM-only knobs so both variants can share conversion output).
- `write_markdown` now governs benchmark markdown sidecars consistently: JSON artifacts remain source-of-truth, while markdown is optional.
- Interactive single-offline markdown contract is one top-level summary (`single_offline_summary.md`) instead of per-variant markdown files.
- Single-offline comparison artifacts now use explicit canonical metrics and `codex_vs_vanilla_comparison.v2`, with optional per-label weighted breakdown and resolved codex runtime metadata.
- Stage/canonical eval reports emit explicit benchmark metrics only (no alias key duplication); compatibility fallback for old artifacts remains reader-side.
- Canonical-text eval reports now emit top-level `boundary` counts so benchmark CSV/dashboard boundary diagnostics stay current.
- CodexFarm benchmark artifacts must include full per-call JSONL logs plus category-split text logs; cutdown packaging should preserve full JSONL and use sampled text logs only as convenience.
- Benchmark cutdown defaults should keep deterministic but richer context (more diagnostics, longer excerpts, and non-trivial deterministic sampling rather than first-N truncation).
- QualitySuite mixed-format documentation and tests should preserve extension-aware discovery semantics: extension pre-selection under `max_targets` cap, then strata fill; capped-extension selection (`max_targets < extension_count`) needs explicit deterministic test coverage.
