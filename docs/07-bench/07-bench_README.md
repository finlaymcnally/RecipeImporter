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
- `bench speed-run`: run timing scenarios (`stage_import`, `benchmark_canonical_legacy`, `benchmark_canonical_pipelined`, `benchmark_all_method_multi_source`).
- Codex Farm permutations (recipe pass) can be included in all-method grids by passing `--include-codex-farm` to `bench speed-run` / `bench quality-run`. Optional overrides: `--codex-farm-model ...` and `--codex-farm-thinking-effort high` (or `--codex-farm-reasoning-effort`).
- `bench speed-compare`: compare baseline/candidate speed runs with regression gates.
- `bench quality-discover`: build deterministic quality suite from pulled gold exports (curated CUTDOWN focus IDs first: `saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`; representative fallback). Use `--no-prefer-curated` to include all matched sources by default when `--max-targets` is omitted.
- `bench quality-run`: run sequential all-method quality experiments for one discovered suite (`--search-strategy race` default; use `exhaustive` for full-grid runs). In runtimes that block process pools, quality-run keeps all-method `global` scope and falls back to thread-backed config workers.
- `bench quality-leaderboard`: aggregate one quality-run experiment into a global cross-source config leaderboard and Pareto frontier.
- `bench quality-compare`: compare baseline/candidate quality runs with strict/practical/source-coverage regression gates.
- `bench eval-stage --gold-spans ... --stage-run ...`: evaluate a stage run directly from `.bench/*/stage_block_predictions.json`.

### 2.2 `cookimport labelstudio-benchmark` benchmark controls

Most benchmark behavior is shared with this command. Active benchmark-specific controls include:
- `--eval-mode stage-blocks|canonical-text`
- `--execution-mode legacy|pipelined|predict-only`
- `--predictions-out <jsonl>` / `--predictions-in <jsonl>`
- `--sequence-matcher dmp`
- `--section-detector-backend legacy|shared_v1`
- `--multi-recipe-splitter legacy|off|rules_v1`
- `--multi-recipe-trace/--no-multi-recipe-trace`
- `--multi-recipe-min-ingredient-lines <int>`
- `--multi-recipe-min-instruction-lines <int>`
- `--multi-recipe-for-the-guardrail/--no-multi-recipe-for-the-guardrail`
- `--instruction-step-segmentation-policy off|auto|always`
- `--instruction-step-segmenter heuristic_v1|pysbd_v1`
- `--no-upload` for fully offline behavior
- `--no-write-markdown`
- `--no-write-labelstudio-tasks` (offline/no-upload path)

Interactive benchmark flows (`single_offline`, `all_method`) stay offline and use canonical-text scoring.
Priority 8 segmentation controls (`--label-projection`, `--boundary-tolerance-blocks`, `--segmentation-metrics`) are exposed only on `bench eval-stage` (not all-method or speed-suite).

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
- `eval_report.json`, `eval_report.md`
- `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`
- `missed_gold_boundaries.jsonl`, `false_positive_boundaries.jsonl`
- compatibility aliases: `missed_gold_spans.jsonl`, `false_positive_preds.jsonl`
- diagnostics: `gold_conflicts.jsonl`

Canonical-text outputs include:
- `eval_report.json`, `eval_report.md`
- `aligned_prediction_blocks.jsonl`
- `missed_gold_lines.jsonl`, `wrong_label_lines.jsonl`
- `unmatched_pred_blocks.jsonl`, `alignment_gaps.jsonl`

### 3.4 Speed/quality artifacts

Speed suite (`bench speed-run`) artifacts include:
- `suite_resolved.json`, `samples.jsonl`, `summary.json`, `report.md`, `run_manifest.json`
- `summary.json` includes `run_settings`, `run_settings_summary`, and `run_settings_hash` so baseline/candidate comparisons can enforce settings parity.
- per-sample artifacts under `scenario_runs/<target_id>/<scenario>/<phase_index>/...`
  - suite-level all-method samples use synthetic target id `__all_matched__` and folder `_all_matched`.

Speed comparison (`bench speed-compare`) artifacts include:
- `comparison.json`, `comparison.md`
- comparison payload includes `baseline_run_settings_hash`, `candidate_run_settings_hash`, `settings_match`, and mismatch-verdict metadata.

Quality suite (`bench quality-run`) artifacts include:
- `suite_resolved.json`, `experiments_resolved.json`, `summary.json`, `report.md`
- one per-experiment output root under `experiments/<experiment_id>/...` containing all-method benchmark artifacts.
- `summary.json` stores per-experiment run-settings hashes and strict/practical/source-coverage metrics for compare gating.
- `experiments_resolved.json` records resolved experiments (including any schema-v2 lever expansion), the canonical alignment cache root, and the all-method runtime knobs used for the run.

Quality leaderboard (`bench quality-leaderboard`) artifacts include:
- `leaderboard.json`, `leaderboard.csv`
- `pareto_frontier.json`, `pareto_frontier.csv`
- `winner_run_settings.json`, `winner_dimensions.json`
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

## 4. Scoring Contracts

### 4.1 Stage-blocks

- Gold rows can contain multiple allowed labels for a block; prediction is correct when it matches any allowed label.
- `HOWTO_SECTION` is resolved for both gold and prediction label paths before scoring:
  - `INGREDIENT_LINE` or `INSTRUCTION_LINE` is inferred from nearby structural context.
  - this keeps structural metrics comparable while preserving `HOWTO_SECTION` in task/export surfaces.
- Predicted blocks with no gold row default to gold label `OTHER` and are logged in diagnostics.
- Evaluator compares blockization fingerprints and fails fast with `gold_prediction_blockization_mismatch` when severe drift makes block-level comparison invalid.

Primary metrics:
- `overall_block_accuracy`
- `macro_f1_excluding_other`
- `worst_label_recall`
- additive segmentation diagnostics under `segmentation`:
  - `label_projection` (currently `core_structural_v1`)
  - `boundary_tolerance_blocks`
  - `boundaries` (`ingredient_start`, `ingredient_end`, `instruction_start`, `instruction_end`, `recipe_split`, `overall_micro`)
  - `error_taxonomy` buckets (`extraction_failure`, `boundary_errors`, `ingredient_errors`, `instruction_errors`, `yield_time_errors`)
  - optional `segeval` metrics (`pk`, `windowdiff`, `boundary_similarity`) when requested and installed

### 4.2 Canonical-text

- Prediction block text is aligned against canonical gold text.
- Scoring is in canonical line space and is extractor/blockization independent.
- Canonical line labels also resolve predicted/gold `HOWTO_SECTION` into structural ingredient/instruction classes before metrics.
- Legacy global alignment is enforced for scoring safety; fast alignment is deprecated and forced to legacy when requested.

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
- Multi-source report counters include:
  - `scheduler_scope` (`global_config_queue` or `legacy_per_source`)
  - `global_queue_planned_configs`
  - `global_queue_completed_configs`
  - `global_queue_failed_configs`
- Per-config rows now include:
  - `eval_signature`
  - `evaluation_result_source` (`executed`, `reused_in_run`, `reused_cross_run`)
  - `evaluation_representative_config_dir`
- Interactive all-method benchmark can auto-sweep deterministic Priority 2–6 knobs (default on in the wizard):
  - `section_detector_backend`
  - `multi_recipe_splitter`
  - `ingredient_missing_unit_policy`
  - `instruction_step_segmentation_policy` / `instruction_step_segmenter`
  - `p6_*` time/temp/yield knobs
- When sweeps are enabled, all-method row dimensions include these keys and a `deterministic_sweep` tag for non-baseline configs.
- For webschema-capable sources (`.html`, `.htm`, `.jsonld`, and schema-like `.json`), all-method expands `web_schema_policy` variants (`prefer_schema`, `schema_only`, `heuristic_only`) and keeps other webschema knobs from base run settings.

## 7. Speed And Quality Regression Workflows

Use this flow for baseline-versus-candidate runtime checks:

1. `cookimport bench speed-discover`
2. `cookimport bench speed-run --suite ...`
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
- `cookimport/bench/quality_runner.py`: sequential all-method quality experiment executor and quality summary/report generation.
- `cookimport/bench/quality_compare.py`: baseline-vs-candidate quality comparison and regression verdict/report formatting.
- `cookimport/bench/sequence_matcher_select.py`: matcher selection contract, env parsing, and telemetry metadata.
- `cookimport/bench/dmp_sequence_matcher.py`: diff-match-patch backed SequenceMatcher adapter.
- `cookimport/bench/canonical_alignment_cache.py`: canonical alignment cache keys, disk cache, and lock recovery behavior.

## 10. See Also

- Runbook: `docs/07-bench/runbook.md`
- Chronology and anti-loop notes: `docs/07-bench/07-bench_log.md`
- Detailed one-off perf report: `docs/07-bench/2026-02-26_18.19.49-book-processing-vs-benchmark-performance-report.md`

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
- QualitySuite is implemented as deterministic representative discovery + sequential experiment runner + baseline/candidate comparator with strict/practical/source-coverage gates and strict patch-key validation.
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
- Experiment-level execution remains sequential by design; adaptation affects per-experiment all-method throughput, not result semantics.
