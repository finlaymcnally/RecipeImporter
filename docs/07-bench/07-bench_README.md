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
- `cookimport bench ...` (offline suite/sweep/speed workflows)
- `cookimport labelstudio-benchmark` (single-run benchmark primitive also reused by interactive benchmark flows)

Current scoring surfaces:
- `stage-blocks`: compare stage evidence labels against freeform gold block labels.
- `canonical-text`: align prediction text to canonical gold text and score per canonical line.

## 2. Command Surface

### 2.1 `cookimport bench`

- `bench validate --suite <path>`: validate suite manifest paths.
- `bench run --suite <path>`: offline prediction + eval + aggregate report.
- `bench sweep --suite <path>`: parameter sweep wrapper around benchmark runs.
- `bench eval-stage --gold-spans ... --stage-run ...`: evaluate a stage run directly from `.bench/*/stage_block_predictions.json`.
- `bench knobs`: list tunable sweep knobs.
- `bench speed-discover`: build deterministic speed suite from pulled gold exports.
- `bench speed-run`: run timing scenarios (`stage_import`, `benchmark_canonical_legacy`, `benchmark_canonical_pipelined`, `benchmark_all_method_multi_source`).
- `bench speed-compare`: compare baseline/candidate speed runs with regression gates.
- `bench quality-discover`: build deterministic representative quality suite from pulled gold exports.
- `bench quality-run`: run sequential all-method quality experiments for one discovered suite.
- `bench quality-compare`: compare baseline/candidate quality runs with strict/practical/source-coverage regression gates.
- `bench run` and `bench sweep` currently execute stage-block suite evaluation (`cookimport/bench/runner.py`).
- `--sequence-matcher` on `bench run` / `bench sweep` is forwarded for compatibility/config parity; canonical-text matcher choice is actively used by canonical benchmark flows (`labelstudio-benchmark`, `bench speed-run` benchmark scenarios).

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

## 3. Artifact Contracts

### 3.1 Prediction/evidence artifacts

Primary scored prediction source:
- `stage_block_predictions.json` (`schema_version=stage_block_predictions.v1`)

Required supporting artifact:
- `extracted_archive.json` (prediction text stream and block metadata)

Generated roots:
- `labelstudio-benchmark` and `bench run` write benchmark artifacts under benchmark run roots.
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

### 3.4 Suite/sweep/speed/quality artifacts

Bench suite (`bench run`) run-root artifacts include:
- `suite_used.json`, `report.md`, `metrics.json`, `run_manifest.json`
- `knobs_effective.json`, `trace.jsonl`
- optional `cost_summary.json`
- `per_item/<item_id>/...` trees containing:
  - `pred_run/` prediction-run artifacts
  - `eval_freeform/` evaluator artifacts (`eval_report.*`, mismatch JSONL files)
  - `noise_stats.json`
- `iteration_packet/` (`summary.md`, `cases.jsonl`, `top_failures.md`, `README.md`)

Bench sweep (`bench sweep`) artifacts include:
- `leaderboard.json`
- optional `best_config.json`
- one nested benchmark run root per tested config (`config_*/<timestamp>/...`)

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
- `bench run --sequence-matcher ...`
- `bench sweep --sequence-matcher ...`
- `bench speed-run --sequence-matcher ...` (optional override; default comes from effective run settings payload)

Canonical cache:
- All-method benchmark runs share canonical alignment cache per source-group by default under:
  - `data/golden/benchmark-vs-golden/.cache/canonical_alignment/<source_group_key>`
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
- When `section_detector_backend != legacy`, all-method row dimensions include `section_detector_backend=<value>` without auto-expanding permutations; backend comparison is explicit via run settings/experiment patches.
- When `multi_recipe_splitter != legacy`, all-method row dimensions include `multi_recipe_splitter=<value>` without auto-expanding permutations; splitter comparison is explicit via run settings/experiment patches.
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
3. `cookimport bench quality-compare --baseline ... --candidate ...`

`quality-compare` gates regressions using:
- strict F1 drop threshold (`strict_f1_drop_max`)
- practical F1 drop threshold (`practical_f1_drop_max`)
- source success-rate drop threshold (`source_success_rate_drop_max`)
- run-settings parity (`run_settings_hash` match required unless `--allow-settings-mismatch` is used)

## 8. Retired Surfaces

Removed from active benchmark contracts:
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
- `cookimport/runs.py`: shared run-manifest model/writer used by bench suite and speed-suite outputs.

Benchmark package modules:
- `cookimport/bench/suite.py`: suite models and manifest loading/validation.
- `cookimport/bench/runner.py`: bench suite orchestration (`pred_run -> eval -> aggregate`) and per-item artifact writing.
- `cookimport/bench/pred_run.py`: offline prediction-run builder wrapper around ingest artifact generation.
- `cookimport/bench/eval_stage_blocks.py`: stage-block evaluator, mismatch diagnostics, and stage-block report formatting.
- `cookimport/bench/eval_canonical_text.py`: canonical-text evaluator, alignment, line-space scoring, and canonical eval report formatting.
- `cookimport/bench/prediction_records.py`: prediction-record schema v1 validation + read/write helpers for replay/evaluate-only flows.
- `cookimport/bench/packet.py`: iteration packet generation (`cases.jsonl`, summary, top failures) from bench run artifacts.
- `cookimport/bench/report.py`: suite-level metric aggregation and markdown report formatting.
- `cookimport/bench/noise.py`: dedupe/consolidation helpers for prediction noise diagnostics.
- `cookimport/bench/cost.py`: estimated LLM review cost calculator and escalation queue writer (counting only; no model calls).
- `cookimport/bench/trace.py`: structured trace collector for bench run event logs.
- `cookimport/bench/knobs.py`: tunable registry and config merge/validation helpers for sweeps.
- `cookimport/bench/sweep.py`: random-search parameter sweep wrapper over bench suite runs.
- `cookimport/bench/speed_suite.py`: deterministic speed target discovery, manifest I/O, and validation.
- `cookimport/bench/speed_runner.py`: speed scenario executor and speed-run summary/report generation.
- `cookimport/bench/speed_compare.py`: baseline-vs-candidate speed comparison and regression verdict/report formatting.
- `cookimport/bench/quality_suite.py`: deterministic representative quality target discovery, manifest I/O, and validation.
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

### 2026-02-28_01.24.58 speed suite run settings adapter parity
- Source: `docs/understandings/2026-02-28_01.24.58-speed-suite-run-settings-adapter-parity.md`
- Summary: SpeedSuite parity is primarily about sharing one RunSettings->kwargs adapter layer and carrying effective settings identity into speed artifacts/compare.

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
