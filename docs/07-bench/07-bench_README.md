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
- `bench run` and `bench sweep` currently execute stage-block suite evaluation (`cookimport/bench/runner.py`).
- `--sequence-matcher` on `bench run` / `bench sweep` is forwarded for compatibility/config parity; canonical-text matcher choice is actively used by canonical benchmark flows (`labelstudio-benchmark`, `bench speed-run` benchmark scenarios).

### 2.2 `cookimport labelstudio-benchmark` benchmark controls

Most benchmark behavior is shared with this command. Active benchmark-specific controls include:
- `--eval-mode stage-blocks|canonical-text`
- `--execution-mode legacy|pipelined|predict-only`
- `--predictions-out <jsonl>` / `--predictions-in <jsonl>`
- `--sequence-matcher fallback|stdlib|cydifflib|cdifflib|dmp|multilayer`
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
- compatibility aliases: `missed_gold_spans.jsonl`, `false_positive_preds.jsonl`
- diagnostics: `gold_conflicts.jsonl`

Canonical-text outputs include:
- `eval_report.json`, `eval_report.md`
- `aligned_prediction_blocks.jsonl`
- `missed_gold_lines.jsonl`, `wrong_label_lines.jsonl`
- `unmatched_pred_blocks.jsonl`, `alignment_gaps.jsonl`

### 3.4 Suite/sweep/speed artifacts

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
- per-sample artifacts under `scenario_runs/<target_id>/<scenario>/<phase_index>/...`
  - suite-level all-method samples use synthetic target id `__all_matched__` and folder `_all_matched`.

Speed comparison (`bench speed-compare`) artifacts include:
- `comparison.json`, `comparison.md`

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
- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=fallback|stdlib|cydifflib|cdifflib|dmp|multilayer`
- legacy `auto` alias maps to `fallback`
- fallback chain: `cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`
- concrete matcher implementations live in:
  - `cookimport/bench/dmp_sequence_matcher.py`
  - `cookimport/bench/sequence_matcher_multilayer.py`

CLI overrides:
- `labelstudio-benchmark --sequence-matcher ...`
- `bench run --sequence-matcher ...`
- `bench sweep --sequence-matcher ...`
- `bench speed-run --sequence-matcher ...`

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
- Uses bounded config-level parallelism with split-phase slot controls.
- Supports timeout/retry controls:
  - `all_method_config_timeout_seconds`
  - `all_method_retry_failed_configs`

Operational interpretation:
- `scheduler heavy X/Y` tracks split-active occupancy only, not evaluate/post phases.
- live queue fail counters are attempt-level; final truth is in per-source `all_method_benchmark_report.json`.
- run-local artifacts (`eval_report.json`, all-method source reports, scheduler/processing timeseries) are primary telemetry truth.

## 7. Speed Regression Workflow

Use this flow for baseline-versus-candidate runtime checks:

1. `cookimport bench speed-discover`
2. `cookimport bench speed-run --suite ...`
3. `cookimport bench speed-compare --baseline ... --candidate ...`

Default discovery source is `data/golden/pulled-from-labelstudio`.
`speed-compare` gates regressions using both:
- percent threshold (`regression_pct`)
- absolute seconds floor (`absolute_seconds_floor`)

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
- `cookimport/bench/sequence_matcher_select.py`: matcher selection contract, env parsing, fallback order, and telemetry metadata.
- `cookimport/bench/dmp_sequence_matcher.py`: diff-match-patch backed SequenceMatcher adapter.
- `cookimport/bench/sequence_matcher_multilayer.py`: multilayer matcher implementation and runtime option handling.
- `cookimport/bench/canonical_alignment_cache.py`: canonical alignment cache keys, disk cache, and lock recovery behavior.

## 10. See Also

- Runbook: `docs/07-bench/runbook.md`
- Chronology and anti-loop notes: `docs/07-bench/07-bench_log.md`
- Detailed one-off perf report: `docs/07-bench/2026-02-26_18.19.49-book-processing-vs-benchmark-performance-report.md`

## 2026-02-27 Merged Understandings: All-Method Runtime and Anti-Loop Contracts

Merged source notes:
- `docs/understandings/2026-02-27_19.21.15-all-method-91-of-91-retry-eval-tail.md`
- `docs/understandings/2026-02-27_19.23.51-fallback-chain-includes-multilayer-before-stdlib.md`
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
- Current fallback matcher chain is `cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`; placing multilayer after stdlib is ineffective.
- Default all-method EPUB extractor variants are `unstructured` and `beautifulsoup`; markdown variants are opt-in via `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS=1`.
- If retries are stuck in canonical-eval tail, terminating active worker child PIDs (not the parent CLI PID) can let the run finalize and still write reports.
- Dedupe hook point is orchestration-level two phase: predict-only per config, then evaluate-only by unique signature.
- Benchmark docs should keep active-feature chronology and retire removed benchmark surfaces (pipeline-task span-IoU primary path, upload-first interactive benchmark, fast canonical alignment production path).

High-signal benchmark findings from `2026-02-27_17.54.41` all-method run:
- `91` planned configs, `82` successful; `thefoodlabCUTDOWN.epub` dominated wall time.
- Stable `unstructured v1` variants gave best reliability/perf trade-off in this run; `v2` variants showed large-source instability due worker termination failures.
