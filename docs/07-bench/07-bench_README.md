---
summary: "Offline benchmark-suite documentation for validation, run, sweep, and tuning loops."
read_when:
  - When iterating on parser quality without Label Studio uploads
  - When running or modifying cookimport bench workflows
  - When asking why benchmark scoring differs from regular stage/import outputs
---

# Bench Section Reference

This is the source of truth for current benchmark behavior under `docs/07-bench`.
For architecture versions, build/fix-attempt history, and anti-loop notes, read `docs/07-bench/07-bench_log.md`.

Offline benchmarking is provided by `cookimport bench ...` and shares prediction/eval primitives with Label Studio benchmark flows.

If your question is "why isn’t benchmark just scoring regular import outputs?", read sections 2-6 first.

## 1. Short answer

Benchmark scores what stage writes, with two evaluator modes:
- `stage-blocks` (default): score stage evidence labels against freeform gold block labels.
- `canonical-text`: align prediction extracted text to canonical gold text and score in canonical line space (extractor-independent).

## 2. Artifact families

### 2.1 Stage artifacts (human/product outputs)

Produced by `cookimport stage` in `cookimport/cli.py`.
Examples:
- `intermediate drafts/...`
- `final drafts/...`
- `tips/...`
- `chunks/...`
- `<workbook>.excel_import_report.json`

### 2.2 Stage evidence artifacts (scored benchmark predictions)

Produced by stage writers (`cookimport/staging/writer.py`) during stage and processed-output benchmark runs.
Key file per workbook:
- `.bench/<workbook_slug>/stage_block_predictions.json`

Prediction-run roots also keep a local copy:
- `stage_block_predictions.json`

### 2.3 Prediction-run support artifacts

Produced by `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py`.
Key files:
- `extracted_archive.json` (block text for mismatch excerpts)
- `manifest.json` and `run_manifest.json`
- `label_studio_tasks.jsonl` (default for upload/offline workflows; optional in offline runs via `--no-write-labelstudio-tasks`; not the scored benchmark prediction source)

### 2.4 Gold artifacts (annotation contract)

Produced by `cookimport labelstudio-export` (freeform-only export path).
Key file:
- `exports/freeform_span_labels.jsonl`

## 3. Why stage evidence is scored

The goal is import alignment: benchmark should reflect what Cookbook import would receive from stage outputs.
Stage evidence projects staged decisions back into one deterministic label per block, then compares those labels directly to exhaustive freeform gold block labels (gold may include multiple allowed labels per block).

## 4. Flow map: stage vs benchmark

### 4.1 Regular stage flow (`cookimport stage`)

1. Convert source file(s)
2. Build recipes/tips/chunks
3. Write staged outputs
4. Write stage evidence `.bench/.../stage_block_predictions.json`
5. Done

### 4.2 Label Studio benchmark flow (`cookimport labelstudio-benchmark`)

1. Select gold freeform export + source file
2. Build prediction-run artifacts (upload or offline)
3. Ensure processed outputs are written (benchmark prediction surface)
4. Score using selected `--eval-mode`:
   - `stage-blocks`: `stage_block_predictions.json` vs freeform gold block labels
   - `canonical-text`: aligned prediction text vs canonical gold text/line labels
5. Write eval artifacts + run manifest + history CSV row

### 4.3 Offline suite flow (`cookimport bench run`)

1. For each suite item, call `generate_pred_run_artifacts` (offline, no upload)
2. Load stage predictions from `pred_run/stage_block_predictions.json`
3. Load gold spans from `<gold_dir>/exports/freeform_span_labels.jsonl`
4. Evaluate + aggregate
5. Write `report.md`, `metrics.json`, `iteration_packet/*`

`cookimport bench sweep` wraps this loop with outer `config X/Y` status updates.
`cookimport bench run` also supports direct write-toggle overrides for prediction artifacts:
- `--write-markdown/--no-write-markdown`
- `--write-labelstudio-tasks/--no-write-labelstudio-tasks`

## 5. Exact scoring surface (stage-block)

Evaluation input A (predictions):
- `stage_block_predictions.json` (`schema_version=stage_block_predictions.v1`)
- one final label per `block_index`

Evaluation input B (gold):
- `freeform_span_labels.jsonl`
- converted to one-or-more allowed labels per block
- when a block has multiple gold labels, prediction is counted correct if it matches any allowed label
- when a predicted block has no gold row, evaluator defaults that block to gold label `OTHER`
- multi-label blocks are logged to `gold_conflicts.jsonl` as diagnostics (not fatal errors)
- missing-block `OTHER` defaults are also logged to `gold_conflicts.jsonl`
- evaluator now profiles blockization metadata (extractor backend + unstructured parser/preprocess flags when present) from both sides and fails with `gold_prediction_blockization_mismatch` when severe drift suggests gold/prediction extractor mismatch

Metrics:
- `overall_block_accuracy`
- per-label precision/recall/F1
- `macro_f1_excluding_other`
- `worst_label_recall`
- confusion counts and mismatch lists

Outputs:
- `eval_report.json`
- `eval_report.md`
- `missed_gold_blocks.jsonl`
- `wrong_label_blocks.jsonl`
- legacy aliases for compatibility:
  - `missed_gold_spans.jsonl`
  - `false_positive_preds.jsonl`

## 5.2 Canonical-text scoring surface

Evaluation input A (predictions):
- `stage_block_predictions.json` (labels per prediction `block_index`)
- `extracted_archive.json` (prediction block text stream for alignment)

Evaluation input B (gold):
- canonical gold export artifacts in `exports/`:
  - `canonical_text.txt`
  - `canonical_span_labels.jsonl`
  - `canonical_manifest.json` (and block map)

How it scores:
- align prediction text stream to canonical gold text (legacy global alignment enforced; fast path deprecated for accuracy risk)
- project stage block labels onto canonical text lines
- compare predicted line labels vs gold line labels
- inspect `report.alignment` deprecation fields when validating alignment strategy behavior
- when `alignment_cache_dir` is provided, canonical alignment results are reused only for identical canonical text + prediction text + prediction block boundaries (all-method uses a shared per-source cache at `.cache/canonical_alignment`)

Outputs include `eval_report.json/md` plus canonical diagnostics:
- `missed_gold_lines.jsonl`
- `wrong_label_lines.jsonl`
- `aligned_prediction_blocks.jsonl`
- `unmatched_pred_blocks.jsonl`
- `alignment_gaps.jsonl`

### 5.1 Runtime telemetry

`labelstudio-benchmark` persists timing in:
- prediction `manifest.json` (`timing`)
- eval `eval_report.json` (`timing`)
- benchmark `run_manifest.json` artifacts (`timing`)
- evaluator reports also include `evaluation_telemetry`:
  - subphase timers (`load_gold_seconds`, `load_prediction_seconds`, alignment/projection/metrics/diagnostic phases),
  - canonical alignment micro-subphases (`alignment_normalize_prediction_seconds`, `alignment_normalize_canonical_seconds`, `alignment_sequence_matcher_seconds`, `alignment_block_mapping_seconds`),
  - canonical matcher implementation metadata (`alignment_sequence_matcher_impl`, `alignment_sequence_matcher_version`, `alignment_sequence_matcher_mode`, `alignment_sequence_matcher_forced_mode`),
  - canonical cache fields (`alignment_cache_enabled`, `alignment_cache_hit`, `alignment_cache_key`, `alignment_cache_load_seconds`, `alignment_cache_write_seconds`, optional `alignment_cache_validation_error`),
  - per-eval resource snapshots/deltas (CPU, peak RSS, block I/O counters when available),
  - work-unit counts (line/span/block counts plus text-size counters such as `prediction_text_char_count`, `prediction_normalized_char_count`, `canonical_text_char_count`)
- benchmark timing checkpoints now mirror evaluator telemetry with `evaluate_*`, `evaluate_resource_*`, and `evaluate_work_*` keys.
- optional eval profiling:
  - set `COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS=<seconds>` to capture cProfile for slow evals,
  - optional `COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N=<int>` controls top-call rows in `eval_profile_top.txt` (default `60`),
  - when triggered, `eval_profile.pstats` and `eval_profile_top.txt` are emitted in the eval output root and referenced in `run_manifest.json`.

SequenceMatcher acceleration notes:
- install optional acceleration deps with `python -m pip install -e '.[benchaccel]'`.
- force matcher implementation with `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib|cydifflib|cdifflib`; leave unset (or `auto`) for fallback selection.

All-method reports include timing rollups in per-source and combined summaries.

## 6. Command matrix

| Command | Uploads to Label Studio | Scores predictions | Primary prediction source |
|---|---:|---:|---|
| `cookimport stage` | No | No | N/A |
| `cookimport labelstudio-benchmark` | Optional (upload mode only; `--allow-labelstudio-write`) | Yes | `stage_block_predictions.json` |
| Interactive benchmark menu flow | No (always offline) | Yes | `stage_block_predictions.json` |
| `cookimport bench run` | No | Yes | `stage_block_predictions.json` |

`labelstudio-benchmark` mode selection:
- `--eval-mode stage-blocks` (default)
- `--eval-mode canonical-text` (extractor-independent)
- `--execution-mode legacy|pipelined|predict-only` (default `legacy`)
- `--predictions-out <path>` writes per-block prediction-record JSONL artifacts (`schema_kind=stage-block.v1`)
- `--predictions-in <path>` skips prediction generation/upload and runs evaluate-only from saved prediction records (per-block records or legacy single-record run pointers)
- `--execution-mode predict-only` generates prediction artifacts and optional prediction-record output without running evaluation
- `--no-write-markdown` skips markdown sidecars in processed stage outputs
- `--no-write-labelstudio-tasks` skips `label_studio_tasks.jsonl` for offline (`--no-upload`) prediction runs

`bench run` prediction-artifact toggle overrides:
- `--write-markdown/--no-write-markdown`
- `--write-labelstudio-tasks/--no-write-labelstudio-tasks`

Interactive benchmark menu modes (`single_offline` and `all_method`) always use `canonical-text` mode.

## 7. Common confusion points

### 8.1 "Benchmark should just score final outputs"

It now does, via stage evidence projection.
Benchmark still does not parse final draft JSON directly; it scores `.bench/.../stage_block_predictions.json`, which is generated from stage outputs and provenance.

### 8.2 "Why is upload happening during benchmark?"

`labelstudio-benchmark` supports both upload and offline generation.
If you want no Label Studio side effects, use:
- `labelstudio-benchmark --no-upload`, or
- `cookimport bench run`.

Interactive benchmark from the main menu is now offline-only, with two modes:
- single offline mode (one local eval run, no upload),
- all-method mode (offline multi-config sweep, no upload).
  - all-matched source concurrency default is bounded to `2` (`all_method_max_parallel_sources`), so multiple books can run concurrently.
  - all-method scheduler defaults are bounded: inflight pipelines=`4`, split-phase slots=`4`.
  - scheduler controls are interactive `cookimport.json` keys:
    - `all_method_max_parallel_sources`
    - `all_method_max_inflight_pipelines`
    - `all_method_max_split_phase_slots`
    - `all_method_max_eval_tail_pipelines`
    - `all_method_wing_backlog_target`
    - `all_method_smart_scheduler`
    - `all_method_config_timeout_seconds`
    - `all_method_retry_failed_configs`
  - smart mode uses phase-aware admission from worker telemetry (`prep`, `split_wait`, `split_active`, `post`, `evaluate`) written to per-config JSONL files under `.scheduler_events/`.
  - smart mode computes eval-tail headroom as configured/effective values:
    - configured headroom is explicit `all_method_max_eval_tail_pipelines` when provided, otherwise auto (`cpu_budget_per_source - configured_inflight`, clamped at `>=0`),
    - effective headroom is bounded by per-source CPU budget and remaining variants.
  - smart eval-tail admission cap is `max_active_during_eval = configured_inflight + eval_tail_headroom_effective`.
  - scheduler reports now expose `eval_tail_headroom_mode`, `eval_tail_headroom_configured`, `eval_tail_headroom_effective`, and `max_active_during_eval` (legacy `max_eval_tail_pipelines` and `smart_tail_buffer_slots` remain as compatibility aliases).
  - fixed mode preserves classic refill-on-completion behavior.
  - per-config timeout watchdog is controlled by `all_method_config_timeout_seconds` (default `900`; `0` disables):
    - timeout marks that config failed,
    - worker pool is recycled so one hung process cannot block source completion.
  - failed-config retries are controlled by `all_method_retry_failed_configs` (default `1`; `0` disables):
    - retry passes rerun only failed config indices, not already successful configs.
  - if process workers cannot start, all-method still auto-falls back to serial.
  - split-worker-heavy conversion is slot-gated across configs, so at most four configs run split conversion concurrently while other configs can pre/post-process.
  - all-method applies a runtime resource guard that caps split workers per active config from CPU+memory budgets; scheduler summaries report `split_worker_cap_per_config` plus cpu/memory cap components.
  - spinner/dashboard task output includes a scheduler state line: `scheduler heavy X/Y | wing Z | eval E | active A | pending P`.
  - when multiple configs are active, dashboard expands active slots as worker lines (`config NN: <phase> | <slug>`).
  - all-matched queue can show more than one running source row (`[>]`) at once; dashboard summary includes `active sources: N`.
  - all-matched wrapper should rerender shared dashboard state when a nested callback emits a stale/partial dashboard snapshot, instead of forwarding a broken queue payload.
  - per-source reports include scheduler utilization metrics, and all-matched combined reports include scheduler rollups.
  - all-matched combined reports include source-level parallel metadata (`source_parallelism_configured`, `source_parallelism_effective`).
  - all-method now supports `Single golden set` or `All golden sets with matching input files`.
  - all-matched scope resolves source hints from freeform export metadata in this order:
    1. run `manifest.json` `source_file`,
    2. first non-empty `freeform_span_labels.jsonl` row `source_file`,
    3. first non-empty `freeform_segment_manifest.jsonl` row `source_file`.
  - all-matched runs write the usual per-source `all_method_benchmark_report.{json,md}` files plus one combined root summary: `all_method_benchmark_multi_source_report.{json,md}`.
  - when source parallelism is greater than `1`, dashboard refresh is batched once at multi-source completion (not once per source).

### 8.3 "Why did split conversion fail with pickling?"

Split benchmark returns worker payloads through multiprocessing, so payload metadata must be pickle-safe primitives.
The concrete failure case that already happened was `unstructured_version` resolving to a module object (`cannot pickle 'module' object`) instead of a string.

## 8. If you want stricter import-level scoring in the future

Current benchmark already aligns to stage outputs through deterministic block-label projection.
Future enhancements can add grouping/order/import-integrity checks on top of current block classification metrics.

## 9. Core code map

- `cookimport/bench/suite.py`: suite manifest load/validate
- `cookimport/bench/pred_run.py`: offline pred-run builder (calls `generate_pred_run_artifacts`)
- `cookimport/bench/runner.py`: full suite run + per-item eval + aggregate report
- `cookimport/bench/eval_stage_blocks.py`: stage-block gold/pred loaders, metrics, and eval artifact writing
- `cookimport/bench/sweep.py`: parameter sweep orchestration
- `cookimport/bench/report.py`: aggregate metrics/report rendering
- `cookimport/bench/packet.py`: iteration packet generation
- `cookimport/labelstudio/ingest.py`: prediction-run artifact generation + optional upload
- `cookimport/cli.py`: command wiring for `stage`, `labelstudio-benchmark`, and `bench`

## 10. Runbook

For quick command examples and output interpretation:
- `docs/07-bench/runbook.md`

## 11. Merged Understandings Batch (2026-02-23 cleanup)

### 2026-02-22_22.25.41 freeform gold dedupe behavior vs overlap

Merged source:
- `docs/understandings/2026-02-22_22.25.41-freeform-gold-dedupe-overlap-behavior.md`

Durable evaluation rule:
- Gold dedupe is overlap-count-agnostic because dedupe keys use absolute block ranges (`source_hash`, `source_file`, `start_block_index`, `end_block_index`), not segment IDs or overlap settings.
- Changing overlap can increase duplicate rows in exports, but exact range matches still collapse before scoring.
- Near-duplicates with different block ranges are not merged; only exact-range matches dedupe.

## 12. Merged Understandings Batch (2026-02-24 cleanup)

### 13.1 Freeform scoring interpretation + practical-vs-strict contract

Merged sources:
- `docs/understandings/2026-02-23_12.31.53-freeform-eval-dedupe-block-range.md`
- `docs/understandings/2026-02-23_12.53.47-pipeline-freeform-span-granularity-gap.md`
- `docs/understandings/2026-02-23_14.42.57-benchmark-update-original-plan-gap.md`
- `docs/understandings/2026-02-23_17.26.00-practical-vs-strict-benchmark-metrics-shipped.md`

Durable benchmark/eval rules:
- Freeform exports are span rows, but current eval projects spans to block ranges and dedupes by `(source_hash, source_file, start_block_index, end_block_index)` before scoring.
- `segment_overlap_requested` can be `0` while `segment_overlap_effective` is raised by the focus-window floor (`segment_blocks - segment_focus_blocks`); this is expected and should be diagnosed from run manifests.
- Near-zero strict IoU with high any-overlap usually indicates granularity mismatch (coarse prediction ranges vs fine gold spans), not necessarily extraction failure.
- Keep strict and practical tracks together in interpretation/ranking; strict-only misses should not automatically be treated as catastrophic when practical overlap is strong.

### 13.2 Interactive benchmark mode contract (single offline vs all-method)

Merged sources:
- `docs/understandings/2026-02-23_14.09.30-interactive-benchmark-upload-only.md`
- `docs/understandings/2026-02-23_15.37.43-interactive-all-method-benchmark-flow.md`
- `docs/understandings/2026-02-23_16.03.51-benchmark-upload-mode-vs-offline-eval.md`
- `docs/understandings/2026-02-23_16.11.07-interactive-benchmark-default-offline.md`
- `docs/understandings/2026-02-23_23.36.37-interactive-benchmark-offline-only-order.md`
- `docs/understandings/2026-02-24_00.20.26-interactive-all-method-skips-run-settings.md`

Durable menu/runtime rules:
- Interactive benchmark is offline-only and mode-first (`single_offline` or `all_method`); no interactive upload branch remains.
- `single_offline` uses benchmark run-settings chooser, always evaluates in `canonical-text`, and can persist `last_run_settings_benchmark` snapshot.
- `all_method` skips run-settings chooser, uses current global benchmark defaults, and should not overwrite `last_run_settings_benchmark`.
- Non-interactive `labelstudio-benchmark` without `--no-upload` can still upload pipeline-scope tasks; uploaded tasks can appear blank/unlabeled in Label Studio because benchmark upload defaults do not attach prelabels.

### 13.3 All-method scope resolution + progress/parallelism contract

Merged sources:
- `docs/understandings/2026-02-23_23.38.41-all-method-single-pair-matching-gap.md`
- `docs/understandings/2026-02-23_23.49.22-all-method-all-golden-matching.md`
- `docs/understandings/2026-02-24_00.29.50-all-method-dashboard-progress-hook.md`
- `docs/understandings/2026-02-24_00.50.03-all-method-parallel-split-slot-locking.md`

Durable all-method rules:
- All-golden scope source hint resolution order is:
  1. run `manifest.json` `source_file`,
  2. first non-empty `freeform_span_labels.jsonl` row `source_file`,
  3. first non-empty `freeform_segment_manifest.jsonl` row `source_file`.
- Matching is by exact filename against top-level importable files in `data/input`; unresolved gold exports should be surfaced explicitly.
- Outer all-method progress remains one persistent dashboard spinner; per-config nested benchmark spinner + summary output should stay suppressed via benchmark progress overrides.
- Parallel all-method defaults remain bounded (inflight pipelines=`4`, split-phase slots=`4`), and benchmark CSV append paths keep file locking to avoid header duplication/partial writes.
- Split-slot wait/acquire/release telemetry should flow through progress callbacks and spinner task updates; subprocess all-method workers should not emit standalone stdout slot lines.
- All-method dashboard `current config` should reflect active config slots in parallel mode (`current configs A-B/N`), not a stale last-submitted slug.
- For `current configs A-B/N` states, keep a per-config worker section visible with phase labels (`prep`, `split wait`, `split active`, `post`, `evaluate`) so operators can see what each active slot is doing.
- ETA/elapsed suffix decoration for multi-line all-method dashboard payloads belongs on the top summary line (`overall ...`), not the trailing `task:` line.

### 13.4 Processed-output and timing telemetry contract

Merged sources:
- `docs/understandings/2026-02-23_23.19.10-benchmark-processed-output-paths.md`
- `docs/understandings/2026-02-24_00.37.24-all-method-benchmark-timing-telemetry-gap.md`
- `docs/understandings/2026-02-24_08.56.28-benchmark-timing-contract-and-fallbacks.md`

Durable output/timing rules:
- `labelstudio-benchmark` writes processed cookbook outputs by default under the configured output root (`data/output/<timestamp>` unless overridden).
- Interactive all-method writes processed outputs under `<output_dir>/<benchmark_timestamp>/all-method-benchmark/<source_slug>/config_*/<prediction_timestamp>/...`.
- `cookimport bench run` remains prediction/eval artifact-focused and does not write processed cookbook outputs by default.
- Benchmark timing precedence in CSV remains: explicit benchmark `timing` argument -> processed report `timing` fallback -> blank timing fields.
- Timing payload should be present end-to-end (prediction manifests, benchmark run manifest, eval report, all-method summaries), and `timing.total_seconds` should not under-report known subphase totals.

## 13. Merged Task Specs (2026-02-24 docs/tasks archival batch)

### 14.1 Practical-vs-strict benchmark scoring rollout

Task sources:
- `docs/tasks/Benchmark-update.md`
- `docs/tasks/Benchmark-update copy.md` (superseded draft snapshot)

Current shipped benchmark contract:
- Keep strict IoU metrics unchanged (`precision`, `recall`, `f1`) and add practical/content-overlap metrics in parallel.
- Persist granularity diagnostics (`span_width_stats`, `granularity_mismatch`) so strict-low/practical-high runs are explicitly explained.
- Bench aggregate reports and iteration-packet severity ranking treat practical misses as primary quality signal, with strict metrics retained for localization refinement.
- CSV/dashboard schema updates remain additive so old rows stay readable with blank practical fields.

Historical trap to avoid:
- A temporary mistaken interactive combo-only benchmark path was removed during this rollout; current interactive mode behavior is the contract in section 13.2.

### 14.2 Initial all-method benchmark baseline

Task source:
- `docs/tasks/All-method-benchmark.md`

Current baseline retained from implementation:
- All-method runs offline and reuses the same single-run primitive (`labelstudio_benchmark(..., no_upload=True)`), so scoring parity with normal benchmark runs is intentional.
- Per-source sweep output keeps stable artifacts:
  - `all_method_benchmark_report.json`
  - `all_method_benchmark_report.md`
- Variant-space count is shown before execution; Codex Farm inclusion remains explicit opt-in and still respects policy lock behavior.

### 14.3 All-golden-set bulk scope behavior

Task source:
- `docs/tasks/2026-02-23_23.37.00-all-method-select-all-golden-sets.md`

Current bulk-scope contract:
- Interactive all-method supports `Single golden set` and `All golden sets with matching input files`.
- Bulk scope writes combined run summary artifacts at all-method root:
  - `all_method_benchmark_multi_source_report.json`
  - `all_method_benchmark_multi_source_report.md`
- Unmatched gold exports are reported with explicit reason and skipped safely.
- Source-hint fallback order remains manifest -> first labeled span row -> first segment-manifest row.

### 14.4 Parallel scheduler + persistent progress dashboard

Task sources:
- `docs/tasks/2026-02-24_00.26.23-all-method-benchmark-parallelization.md`
- `docs/tasks/2026-02-24_00.29.50-all-method-dashboard-spinner.md`

Current runtime contract:
- All-method queue defaults are bounded (`inflight pipelines=4`, `split-phase slots=4`).
- Outer queue falls back to serial when process executor startup fails in restricted environments.
- Split-heavy conversion is slot-gated and benchmark CSV appends are file-locked for concurrency safety.
- Interactive all-method uses one persistent outer dashboard spinner; nested per-config benchmark spinner and completion dumps are suppressed during the sweep.

## 14. Merged Understandings Batch (2026-02-24 all-method scheduler + spinner refresh)

### 15.1 Split-slot bottleneck and scheduler settings contract

Merged discoveries (chronological):
- `2026-02-24_15.21.53-all-method-split-slot-default-bottleneck`
- `2026-02-24_15.28.12-all-method-scheduler-settings-flow`

Durable rules:
- `inflight` alone is not throughput truth; split-slot caps can be the actual heavy-phase ceiling.
- Interactive scheduler limits should come from `cookimport.json` keys and be validated/fallbacked to bounded defaults when invalid.
- Keeping split slots aligned with inflight defaults avoids false "parallel idle" impressions in conversion-heavy runs.

### 15.2 Heavy-slot occupancy and smart-admission telemetry contract

Merged discoveries (chronological):
- `2026-02-24_15.53.58-all-method-heavy-slot-flow-map`
- `2026-02-24_16.10.45-smart-all-method-scheduler-event-gating`
- `2026-02-24_20.56.39-smart-scheduler-post-tail-buffer`

Durable rules:
- Outer all-method scheduler decisions depend on worker phase telemetry (`prep`, `split_wait`, `split_active`, `post`, `evaluate`), not completion-only signals.
- Smart admission quality depends on preserving a wing backlog while heavy slots are active.
- Effective smart inflight is capped by `configured_inflight + eval_tail_headroom_effective`, where effective headroom is CPU-bounded and variant-bounded.
- `.scheduler_events/config_###.jsonl` remains the source for both live admission signals and post-run utilization rollups.

### 15.3 Stalls, timeout, and failed-only retry contract

Merged discoveries (chronological):
- `2026-02-24_15.57.24-all-method-stall-single-config-lock`
- `2026-02-24_16.11.17-all-method-timeout-and-failed-only-retry-flow`

Durable rules:
- A single stuck worker can hold completion at `N-1/N`; timeout handling belongs at per-source future scheduling, not deep inside one benchmark call.
- Timeout path should mark that config failed, recycle worker pool, and continue source completion/report flush.
- Retry passes should rerun failed config indices only and keep successful configs untouched.

### 15.4 Multi-source spinner and dashboard forwarding contract

Merged discoveries (chronological):
- `2026-02-24_15.22.29-all-method-spinner-snapshot-and-split-slot-flow`
- `2026-02-24_20.57.46-all-method-spinner-active-config-eta-placement`
- `2026-02-24_21.05.24-all-method-spinner-partial-snapshot-rerender`

Durable rules:
- Wrapper-level progress forwarding should pass worker payloads through and rerender from shared dashboard state for dashboard-shaped nested payloads.
- Active config display in parallel mode should be derived from active-slot state, not last-submitted config metadata.
- For multi-line dashboard payloads, ETA/elapsed suffixes belong on the top summary line only.
- Subprocess split-slot telemetry should flow through callbacks; raw fallback prints should not leak into spinner output.

### 15.5 Source-level parallel dispatch contract

Merged discoveries (chronological):
- `2026-02-24_21.11.33-all-method-all-matched-source-serialization-limit`
- `2026-02-24_21.31.58-all-method-source-parallel-dispatch-and-refresh-contract`

Durable rules:
- Serial source dispatch underutilizes CPU in all-matched mode even when per-source config schedulers are efficient.
- Bounded source-level thread dispatch is the safe outer parallelism layer while per-source config execution remains process-based.
- Combined reports should preserve deterministic source order via preindexed source slots.
- Dashboard refresh is per-source in serial mode and batched once at multi-source completion in parallel source mode.

## 15. 2026-02-24_22.44.09 docs/tasks archival merge batch (all-method scheduling/spinner/source parallel)

### 16.1 Archived source tasks merged into this section

- `docs/tasks/2026-02-24_15.21.53-all-method-split-slot-default-four.md`
- `docs/tasks/2026-02-24_15.22.29-all-method-spinner-noise-cleanup.md`
- `docs/tasks/2026-02-24_15.28.12-all-method-scheduler-settings-keys.md`
- `docs/tasks/2026-02-24_15.52.15-smart-heavy-slot-scheduler-all-method.md`
- `docs/tasks/2026-02-24_16.01.56-all-method-timeout-and-retry.md`
- `docs/tasks/2026-02-24_20.56.39-smart-scheduler-tail-buffer-headroom.md`
- `docs/tasks/2026-02-24_20.57.46-all-method-spinner-polish-active-config-eta.md`
- `docs/tasks/2026-02-24_21.05.24-all-method-spinner-queue-stability-rerender.md`
- `docs/tasks/2026-02-24_21.09.55-parallel-source-all-method-benchmark.md`

### 16.2 Scheduler defaults and settings contracts

Durable runtime contracts from the merged tasks:

- Effective all-method defaults remain aligned for heavy work: inflight `4`, split slots `4`.
- Scheduler limits are interactive settings (`cookimport.json`) rather than hardcoded-only constants.
- Invalid/zero scheduler overrides are bounded/fallbacked to defaults.
- Smart scheduler behavior is tunable and phase-aware, using worker lifecycle telemetry from `.scheduler_events/config_###.jsonl`.

### 16.3 Smart heavy-slot utilization contracts

- Admission decisions are phase-aware (`prep`, `split_wait`, `split_active`, `post`) and target heavy-slot occupancy, not completion-only refill.
- Smart mode includes extra tail headroom so long post-stage workers do not starve prewarm admissions.
- Scheduler metrics are persisted into all-method reports (`heavy_slot_*`, wing backlog, idle-gap style summaries).

### 16.4 Reliability contracts: timeout + failed-only retry

- Per-config timeout handling lives in outer all-method scheduler orchestration, not inside benchmark scoring internals.
- Timeout path marks config failed, recycles worker pool, and continues report completion.
- Retry passes rerun failed config indices only and keep final reporting at latest-attempt state per config.
- Interactive settings surface timeout/retry values and report metadata records resolved behavior.

### 16.5 Spinner/dashboard forwarding contracts

- Spinner forwarding treats dashboard-shaped nested payloads specially to avoid recursive/noisy rewraps.
- Worker-run split-slot status should flow via callbacks (including no-op callbacks in subprocess paths), not fallback raw stdout prints.
- ETA/elapsed suffixes for multi-line dashboard payloads belong on the top summary line.
- Active config display in parallel mode comes from active-slot state (single slug or index range), not last-submitted config metadata.

### 16.6 Source-level parallel all-matched execution contracts

- All-matched mode supports bounded source parallelism with settings-controlled effective cap.
- Outer dispatch layer is thread-based; per-source config execution remains process-based.
- Combined report ordering remains deterministic by source discovery/index, regardless of completion order.
- Dashboard refresh policy splits by mode: serial per-source refresh vs one batched refresh at multi-source completion when source parallelism is active.

## 16. Merged Understandings Batch (2026-02-25 stage-vs-benchmark clarifications)

### 16.1 2026-02-25_17.25.05 stage vs benchmark pipeline map

Merged source:
- `docs/understandings/stage-vs-benchmark-pipeline.md`

Durable contract:
- Menu `1)` stage and menu `5)` benchmark share importer conversion plus stage writer machinery.
- They differ in primary run intent and artifact roots:
  - stage run focus: cookbook artifacts under `data/output/<timestamp>/...`
  - benchmark run focus: prediction/eval artifacts under `data/golden/benchmark/<timestamp>/...`
- Menu `5)` writes processed stage outputs as side artifacts; those processed outputs are importable cookbook artifacts.
- Stage-only optional extras (for example knowledge harvest lanes) should not be assumed present in benchmark artifact roots.

Anti-loop note:
- Do not treat benchmark flow as a separate importer pipeline when debugging extraction differences; start from shared conversion/stage writer path and then inspect artifact-surface differences.

### 16.2 2026-02-25_17.26.24 required stage-block prediction artifacts in pred-run roots

Merged source:
- `docs/understandings/2026-02-25_17.26.24-stage-block-benchmark-prediction-artifacts.md`

Durable artifact contract:
- `labelstudio-benchmark` and `bench run` require these files in each prediction-run root:
  - `stage_block_predictions.json`
  - `extracted_archive.json`
- Legacy fixtures containing only `label_studio_tasks.jsonl` are insufficient for stage-block evaluation.
- Stage evidence originates under `.bench/<workbook_slug>/stage_block_predictions.json` and is copied into pred-run root by `generate_pred_run_artifacts(...)`.

Anti-loop note:
- If benchmark fails with missing stage artifacts, fix fixture/build artifact generation first instead of changing evaluator label math.

### 16.3 2026-02-25_17.27.08 historical per-label-zero caveat (legacy scoring surface)

Merged source:
- `docs/understandings/2026-02-25_03.41.19-per-label-zeros-notes-yield-time-variant.md`

Historical note preserved:
- Old pipeline-task span scoring could show `pred_total=0` for `RECIPE_NOTES`, `RECIPE_VARIANT`, `TIME_LINE`, and `YIELD_LINE` even when staged drafts carried notes/variants/time/yield fields.
- That specific failure mode depended on missing pipeline chunk types and is not the current stage-block scoring contract.

Current interpretation rule:
- For current runs, benchmark truth is stage-block evidence (`stage_block_predictions.json`) vs freeform gold block labels.
- When reviewing older reports produced before stage-block adoption, do not infer extractor failure solely from those legacy per-label zero rows without first confirming the scoring surface.

### 16.4 2026-02-25_17.26.21 stage-block benchmark refactor archival merge

Merged source:
- `docs/tasks/bench-refactor.md`

Durable benchmark contract from the refactor:
- Scoring surface is stage evidence (`stage_block_predictions.json`) plus knowledge exports, not pipeline-task chunks.
- Evaluation is block classification, not span IoU.
- Gold labels can be partial; missing predicted blocks are defaulted to `OTHER` with diagnostics.
- Multi-label gold blocks are allowed; evaluator treats any allowed gold label as a match and emits diagnostics for those blocks.
- Reports must surface:
  - `overall_block_accuracy`
  - `macro_f1_excluding_other`
  - `worst_label_recall`
- Compatibility aliases stay in place (`missed_gold_spans.jsonl`, `false_positive_preds.jsonl`) while block-native artifacts are primary.

Scope boundaries preserved:
- Step-internal instruction `time_seconds` extraction is not benchmarked in this contract.
- Recipe grouping correctness is currently outside benchmark scope.
- Notes/variant scoring should use stage provenance only; derived metadata should not inflate those labels.

Known pending follow-up from task record:
- Full removal of legacy Label Studio scopes (`pipeline`, `canonical-blocks`) was marked as a separate migration after scoring contract rollout.
- Real golden-set acceptance run evidence was still pending at that task checkpoint.

## 17) Merged Understandings Batch (2026-02-25_18.54.00 to 2026-02-26_03.10.00)

### 17.1 2026-02-25_18.54.00 interactive benchmark settings migration boundary

Merged source:
- `docs/understandings/2026-02-25_18.54.00-interactive-benchmark-legacy-epub-setting.md`

Durable contract:
- Interactive benchmark defaults load through `RunSettings.from_dict(...)`.
- Legacy persisted aliases (for example `epub_extractor=legacy`) must be normalized in run-settings migration, not only in CLI flag normalization paths.

### 17.2 2026-02-25_19.00.51 stage-block eval accepts multi-label gold blocks

Merged source:
- `docs/understandings/2026-02-25_19.00.51-stage-block-eval-multilabel-gold.md`

Durable contract:
- Multi-label gold assignments per block are valid.
- A prediction is correct when predicted label is in that block's allowed gold-label set.
- Missing-gold predicted block rows default to `OTHER` and diagnostics are written to `gold_conflicts.jsonl`.

### 17.3 2026-02-25_19.14.33 extractor/blockization parity between gold and prediction runs

Merged source:
- `docs/understandings/2026-02-25_19.14.33-benchmark-gold-extractor-parity.md`

Durable contract:
- Source-hash parity alone is insufficient for stage-block scoring validity.
- Gold export and benchmark prediction runs must use aligned extractor/blockization settings.
- Mismatch can create high-index missing-gold drift and misleading per-label precision/recall failures.

### 17.4 2026-02-25_22.19.47 severe mismatch guardrail

Merged source:
- `docs/understandings/2026-02-25_22.19.47-gold-blockization-mismatch-guard.md`

Durable contract:
- Evaluator fingerprints blockization metadata from gold + prediction artifacts.
- If fingerprints disagree and drift is severe, evaluation fails fast with `gold_prediction_blockization_mismatch` and diagnostics in `gold_conflicts.jsonl`.
- Mild drift remains warning-level to preserve fixture/partial-metadata usability.

### 17.5 2026-02-25_23.02.58 canonical-text eval is the all-method runtime hotspot

Merged source:
- `docs/understandings/2026-02-25_23.02.58-all-method-canonical-eval-runtime-hotspot.md`

Durable diagnosis rule:
- In slow all-method runs, `evaluation_seconds` dominates wall time; split conversion is often not the bottleneck.
- Scheduler metrics alone are insufficient without explicit evaluate-phase telemetry.

### 17.6 2026-02-25_23.11.15 telemetry plumbing boundary

Merged source:
- `docs/understandings/2026-02-25_23.11.15-benchmark-eval-telemetry-plumbing.md`

Durable telemetry contract:
- `_timing_with_updates(...)` keeps numeric top-level timing/checkpoint values only.
- Rich evaluator details should be stored in `evaluation_telemetry` for JSON inspection.
- Metrics needed by CSV/history/reports must also be flattened into numeric `evaluate_*` checkpoints.

### 17.7 2026-02-25_23.15.51 SequenceMatcher hotspot profile

Merged source:
- `docs/understandings/2026-02-25_23.15.51-canonical-eval-sequencematcher-profile.md`

Durable optimization rule:
- Canonical eval runtime is dominated by `difflib.SequenceMatcher` alignment in `_align_prediction_blocks_to_canonical(...)`.
- Biggest speedups come from changing alignment strategy/constraints, not scheduler-only tuning.

### 17.8 2026-02-25_23.38.52 micro-telemetry + opt-in eval profiling

Merged source:
- `docs/understandings/2026-02-25_23.38.52-canonical-eval-micro-telemetry-and-profile-hook.md`

Durable contract:
- Canonical eval telemetry now includes alignment micro-subphases and text-size work-unit checkpoints.
- Slow-run profiling is opt-in via:
  - `COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS`
  - `COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N`
- Profile artifacts (`eval_profile.pstats`, `eval_profile_top.txt`) are emitted only when threshold criteria are met.

### 17.9 2026-02-25_23.39.17 fast align + scheduler eval-tail cap

Merged source:
- `docs/understandings/2026-02-25_23.39.17-canonical-fast-align-and-eval-tail-cap.md`

Durable contract:
- Canonical eval should enforce legacy full-book alignment; bounded fast alignment is deprecated due to accuracy risk.
- Alignment strategy/fallback telemetry must be explicit in artifacts.
- Smart scheduler treats evaluate tails separately from split-phase prewarm and caps tail-driven inflight growth with `configured_inflight + eval_tail_headroom_effective`.

### 17.10 2026-02-26_03.10.00 canonical-text default for all-method sweeps

Merged source:
- `docs/understandings/2026-02-26_03.10.00-canonical-text-all-method-default.md`

Durable mode-selection rule:
- Keep `stage-blocks` mode for parity-sensitive same-blockization comparisons.
- Use `canonical-text` mode for extractor-permutation sweeps against one freeform gold export.
- Interactive all-method runs default to `canonical-text` to avoid invalid cross-extractor stage-block comparisons.

### 17.11 2026-02-26_18.19.49 benchmark telemetry source layout

Merged source:
- `docs/understandings/2026-02-26_18.19.49-benchmark-telemetry-source-layout.md`

Durable telemetry collection rule:
- For benchmark performance analysis, use run-local artifacts as primary truth:
  - `data/golden/benchmark-vs-golden/**/eval_report.json`
  - `data/golden/benchmark-vs-golden/**/all_method_benchmark_report.json`
  - `data/output/**/all-method-benchmark/**/.history/performance_history.csv`
- Treat top-level `data/.history/performance_history.csv` as a convenience index, not a complete benchmark telemetry record.

### 17.12 2026-02-26_18.32.41 all-method live fail counters vs timeout/retry recovery

Merged source:
- `docs/understandings/2026-02-26_18.32.41-all-method-failure-counters-timeout-retries.md`

Durable runtime interpretation rule:
- Live all-method queue `ok/fail` counters are per-attempt during active execution.
- Timeout (`all_method_config_timeout_seconds`) and failed-only retry passes (`all_method_retry_failed_configs`) can recover configs later, and live counters are not retroactively corrected.
- Final truth for source status belongs in `all_method_benchmark_report.json` fields such as `failed_variants`, `retry_failed_configs_requested`, `retry_passes_executed`, and `retry_recovered_configs`.

## 18) Merged Task Specs (2026-02-25 docs/tasks archival batch)

### 18.1 2026-02-25_18.54.30 legacy `epub_extractor` settings migration

Merged source:
- `docs/tasks/2026-02-25_18.54.30-benchmark-legacy-epub-extractor-migration.md`

Durable settings contract:
- `RunSettings.from_dict(...)` must accept persisted `epub_extractor=legacy` values and migrate them to `beautifulsoup`.
- User-facing accepted extractor choices remain `unstructured|beautifulsoup|markdown|markitdown`.

Task evidence preserved:
- Before fix: `ValidationError` on `epub_extractor='legacy'`.
- After fix: migrated to `beautifulsoup` with warning.
- Regression suite: `tests/llm/test_run_settings.py` (`9 passed`).

### 18.2 2026-02-25_19.00.51 multi-label freeform gold support in stage-block eval

Merged source:
- `docs/tasks/2026-02-25_19.00.51-multilabel-freeform-benchmark-eval.md`

Durable scoring contract:
- `load_gold_block_labels(...)` accepts multiple allowed gold labels per block.
- A prediction is correct if it matches any allowed gold label for that block.
- Multi-label blocks and missing-gold defaults are logged to `gold_conflicts.jsonl`.
- Missing gold rows for predicted blocks default to `OTHER` (diagnostic + backward-compatible behavior).

Task evidence preserved:
- Before fix: eval raised `ValueError: Gold conflicts detected...` on multi-label gold.
- After fix: eval completes and preserves multi-label/missing-gold diagnostics.
- Verification anchor: `pytest tests/bench/test_eval_stage_blocks.py`.

### 18.3 2026-02-25 (fix-gold ExecPlan completed by 22:19Z): severe blockization mismatch guard

Merged source:
- `docs/tasks/fix-gold.md`

Durable guardrail contract:
- Stage-block eval fingerprints gold and prediction blockization metadata.
- Severe mismatch signal (`metadata mismatch` + high drift) fails fast with `gold_prediction_blockization_mismatch` before scoring.
- Non-severe mismatch remains warning-level and keeps default-`OTHER` behavior.
- Diagnostics are persisted to `gold_conflicts.jsonl` and summarized in `eval_report.json`.

Known failed-path context worth preserving:
- Prior behavior allowed large extractor/blockization drift to silently score with heavy default-`OTHER` backfill, producing misleading precision/recall.
- Guardrail intentionally targets this exact failure mode while keeping small-fixture tolerance.

### 18.4 2026-02-25_23.15.54 all-method canonical-text eval speedups

Merged source:
- `docs/tasks/2026-02-25_23.15.54-all-method-canonical-eval-speedups.md`

Durable runtime/perf contract:
- Canonical eval alignment enforces `legacy` for scoring correctness.
- `auto` and `fast` requests are treated as deprecated aliases and are forced to legacy with explicit deprecation telemetry.
- Canonical line-projection overlap loops use pointer-based interval sweeps.
- Smart all-method scheduler has explicit evaluate-tail headroom with configured/effective reporting and max-active eval cap semantics (`configured_inflight + effective_headroom`).

Important “known bad / pending” context preserved:
- Task recorded implementation and regression tests as complete, but real SeaAndSmoke before/after acceptance timing thresholds were not captured in that pass.

### 18.5 2026-02-25_23.39.03 canonical eval telemetry microphases + opt-in profile artifacts

Merged source:
- `docs/tasks/2026-02-25_23.39.03-canonical-eval-telemetry-microphases.md`

Durable telemetry contract:
- Canonical evaluator emits alignment micro-subphase timings and text-size work-unit counters.
- `labelstudio-benchmark` can capture slow eval cProfile artifacts behind env vars.
- Profiling stays opt-in and artifact writing is best-effort (must not fail benchmark run by itself).

Task evidence preserved:
- Verification command set passed (`5 passed, 2 warnings in 3.38s`).
- Profile artifacts:
  - `eval_profile.pstats`
  - `eval_profile_top.txt`

## 19) OG speed-plan consolidation (2026-02-27 merge from `docs/tasks`)

This section is the practical current-state summary after merging:
- `docs/tasks/speed-1.md`
- `docs/tasks/speed-2.md`
- `docs/tasks/speed-3.md`
- `docs/tasks/speed-4.md`
- `docs/tasks/speed-5.md`
- `docs/tasks/2026-02-26_21.02.47-og-speed-plan-implementation-audit.md`
- `docs/tasks/2026-02-26_21.34.23-og-speed3-speed5-implementation-audit.md`

Detailed chronology, requirement-level evidence, and anti-loop history now live in:
- `docs/07-bench/07-bench_log.md` section `2026-02-26 to 2026-02-27 docs/tasks archival merge batch (OG speed plans + audits)`.

### 19.1 What exists now (runtime contracts)

- Speed-1 (`SequenceMatcher` selector):
  - canonical evaluator uses drop-in matcher selection with env contract `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto|stdlib|cydifflib|cdifflib`.
  - telemetry captures matcher implementation/mode/version details.
  - optional accel install path documented (`.[benchaccel]`).
- Speed-2 (all-method eval-tail admission):
  - scheduler tracks evaluate-phase activity and renders `eval E` in snapshot/dashboard text.
  - runtime auto-resolves eval-tail headroom from CPU budget when no explicit override is pinned.
  - report payloads include eval-phase utilization signals.
- Speed-3 (canonical alignment cache):
  - optional disk-backed content-addressed cache in canonical evaluator.
  - all-method runs share per-source cache at `.cache/canonical_alignment`.
  - cache key safety includes canonical text, prediction text, and block-boundary signatures.
  - closure evidence now includes a real miss->hit two-config all-method run plus dedicated cache concurrency tests (`docs/tasks/2026-02-27_11.29.26-speed1-3-remaining-closeout.md`).
- Speed-4 (stage split and replay):
  - benchmark supports `--execution-mode legacy|pipelined|predict-only`.
  - per-block prediction-record artifacts support `--predictions-out` and evaluate-only `--predictions-in`.
  - evaluate-only remains backward-compatible with legacy single-record run-pointer artifacts.
  - legacy mode remains default for compatibility.
- Speed-5 (non-scoring artifact toggles):
  - stage supports `--no-write-markdown`.
  - offline benchmark supports `--no-write-markdown` and `--no-write-labelstudio-tasks`.
  - manifests encode intentional task-jsonl skips via `tasks_jsonl_status`.

### 19.2 Known open closure gaps (still easy to miss)

1. Evidence capture remains the main unresolved acceptance category:
   - speed-1 before/after timing + output-identity artifact.
   - speed-2 before/after all-method eval-tail utilization artifact.
   - speed-4 `legacy` vs `pipelined` timing artifact.
   - speed-5 A/B write-time + scoring-parity artifact.
2. Two OG-spec interpretation items may still require explicit decision:
   - speed-5 prepared-archive abstraction (`PreparedExtractedArchive`) vs current in-function archive reuse.

### 19.3 Anti-loop guardrails from merged tasks/audits

- Do not re-open canonical fast-align shortcuts for scoring; canonical-text scoring remains accuracy-first legacy alignment.
- Treat `--no-write-labelstudio-tasks` as offline-only; upload flows require tasks JSONL payloads.
- Speed-3 is now closed with dedicated tests + real miss->hit telemetry evidence; avoid reopening cache design unless normalization/alignment contracts change.
- Benchmark speed discussions should include both runtime implementation state and evidence state; several speed items are functionally implemented but still evidence-incomplete.

## 20) Merged Understandings Batch (2026-02-26 to 2026-02-27 cleanup)

Merged sources in creation order:
- `docs/understandings/2026-02-26_17.43.52-interactive-benchmark-canonical-text-default.md`
- `docs/understandings/2026-02-26_17.50.47-interactive-benchmark-eval-spinner-visibility.md`
- `docs/understandings/2026-02-26_18.05.24-canonical-fast-align-deprecated.md`
- `docs/understandings/2026-02-26_18.19.49-benchmark-telemetry-source-layout.md`
- `docs/understandings/2026-02-26_18.32.41-all-method-failure-counters-timeout-retries.md`
- `docs/understandings/2026-02-26_18.49.41-all-method-dashboard-active-config-worker-lines.md`
- `docs/understandings/2026-02-26_18.51.30-all-method-heavy-counter-vs-eval-phase.md`
- `docs/understandings/2026-02-26_19.30.26-canonical-sequence-matcher-surface.md`
- `docs/understandings/2026-02-26_19.37.52-all-method-smart-admission-eval-tail-constraints.md`
- `docs/understandings/2026-02-26_19.57.12-canonical-alignment-cache-call-chain.md`
- `docs/understandings/2026-02-26_20.26.13-speed5-stageblock-artifact-surface.md`
- `docs/understandings/2026-02-26_22.03.19-speed2-eval-tail-headroom-and-speed4-pipeline-prewarm.md`
- `docs/understandings/2026-02-26_22.23.35-speed5-toggle-plumbing-surfaces.md`
- `docs/understandings/2026-02-26_22.36.54-all-method-cpu-utilization-cap-from-config-limits.md`
- `docs/understandings/2026-02-27_03.12.00-speed4-benchmark-stage-record-contract.md`

### 20.1 Interactive benchmark and dashboard runtime rules

- Interactive `single_offline` and `all_method` benchmark modes should both evaluate with `canonical-text` by default; this avoids invalid extractor-dependent stage-block comparisons.
- Interactive benchmark should keep visible status during evaluation, not just prediction generation, because canonical-text eval can run for minutes with no artifact writes.
- In all-method dashboards, `scheduler heavy X/Y` reflects split-phase workers only; seeing `heavy 0/Y` while active configs remain can be normal evaluate-phase activity.
- Multi-active all-method states should show per-config worker lines with phase labels (`prep`, `split_wait`, `split_active`, `post`, `evaluate`) instead of range-only status.

### 20.2 Canonical alignment safety and performance surface

- Canonical-text scoring currently enforces legacy global `SequenceMatcher` alignment; `auto` and `fast` requests are deprecated aliases forced to legacy with deprecation telemetry.
- Canonical speed work should preserve scoring behavior and swap matcher implementation only behind the current `_align_prediction_blocks_to_canonical(...)` / `_align_prediction_blocks_legacy(...)` surface.
- Canonical alignment cache wiring is benchmark-level and shared per source in all-method:
  - `_run_all_method_benchmark(...)` creates `.cache/canonical_alignment`.
  - `_run_all_method_config_once(...)` passes cache path to `labelstudio_benchmark(...)`.
  - `labelstudio_benchmark(...)` forwards cache path only for canonical eval.
  - `evaluate_canonical_text(...)` and aligner enforce hash/version/shape validation and treat invalid cache payloads as safe misses.

### 20.3 All-method scheduler interpretation and tuning

- Live all-method `ok/fail` counters are per-attempt and are not retroactively corrected after timeout recovery or retry passes.
- Final source truth belongs in each `all_method_benchmark_report.json` (`failed_variants`, `retry_failed_configs_requested`, `retry_passes_executed`, `retry_recovered_configs`).
- Smart admission tracks evaluate-phase activity and now enforces eval-tail growth against `configured_inflight + eval_tail_headroom_effective`; prewarm guard conditions still shape how quickly admissions refill heavy slots.
- Throughput tuning should include:
  - eval-tail headroom behavior (`all_method_max_eval_tail_pipelines` configured/effective resolution with CPU bounds),
  - prewarm guard targets while evaluation is active,
  - explicit scheduler caps from `cookimport.json` (`inflight`, `split_slots`, `eval_tail`, `wing_backlog`) that can otherwise underutilize multi-core hosts.

### 20.4 Benchmark telemetry and speed-4/speed-5 artifact contract

- Run-local benchmark artifacts are primary telemetry truth; top-level `data/.history/performance_history.csv` is an index and can be incomplete.
- Canonical eval performance analysis should prioritize:
  - `.../eval_report.json`,
  - `.../all_method_benchmark_report.json`,
  - run-local `.history/performance_history.csv` under all-method roots.
- Stage-block scoring depends on `stage_block_predictions.json` and `extracted_archive.json`, not `label_studio_tasks.jsonl`.
- Speed-5 toggle plumbing must stay consistent across stage single-file and split-merge paths, plus offline pred-run generation, with manifest status marking intentional task-jsonl skips.
- Speed-4 execution/replay now uses per-block prediction-record streams as the default contract; evaluate-only keeps compatibility with legacy run-pointer records.
