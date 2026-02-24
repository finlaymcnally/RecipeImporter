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

Benchmark does **not** score staged cookbook files (`final drafts`, `tips`, etc.) directly.
It scores **prediction task artifacts** (`label_studio_tasks.jsonl`) against **gold freeform span artifacts** (`freeform_span_labels.jsonl`) because both are aligned to the same block/span coordinate system.

That shared coordinate system is what makes comparison deterministic.

## 2. The three artifact families

### 2.1 Stage artifacts (human/product outputs)

Produced by `cookimport stage` in `cookimport/cli.py`.
Examples:
- `intermediate drafts/...`
- `final drafts/...`
- `tips/...`
- `chunks/...`
- `<workbook>.excel_import_report.json`

These are excellent for product output and manual inspection, but they are not the scoring contract used by freeform gold evaluation.

### 2.2 Prediction-run artifacts (benchmark prediction contract)

Produced by `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py`.
Key files:
- `label_studio_tasks.jsonl` (predicted tasks/ranges used for scoring)
- `extracted_archive.json` (block stream used to derive tasks)
- `manifest.json` (run metadata)
- `run_manifest.json` (cross-command source/config/artifact linkage)
- `coverage.json`
- optional `llm_manifest.json` if recipe codex-farm correction is ever re-enabled in future (currently policy-locked `llm_recipe_pipeline=off`)

These are the canonical "predictions" for both:
- `cookimport labelstudio-benchmark`
- `cookimport bench run` (offline suite)

### 2.3 Gold artifacts (annotation contract)

Produced by `cookimport labelstudio-export --export-scope freeform-spans`.
Key file:
- `exports/freeform_span_labels.jsonl`

This gold format stores span labels + touched block indices, which is why prediction side must use comparable block/range representation.

## 3. Why benchmark uses task artifacts instead of staged outputs

### 3.1 Gold is span/block based, not final-json based

Freeform gold labels represent highlighted text spans mapped to block indices.
Staged outputs are normalized recipe/tip/chunk products, not direct span annotations.

If benchmark tried to score staged outputs directly, it would need a reverse-projection layer back into block spans. That would add ambiguity and make scoring less stable.

### 3.2 Shared coordinate system prevents "apples vs oranges"

Both prediction and gold are evaluated as labeled ranges:
- Prediction ranges are loaded from `label_studio_tasks.jsonl` (`load_predicted_labeled_ranges`)
- Gold ranges are loaded from `freeform_span_labels.jsonl` (`load_gold_freeform_ranges`)
- Matching is performed by overlap logic (`evaluate_predicted_vs_freeform`)

This is a direct contract-to-contract comparison, not a derived approximation.

### 3.3 Same artifact contract works for both online and offline loops

`generate_pred_run_artifacts(...)` is reused in:
- online Label Studio import/upload flows
- offline suite benchmarking

This keeps one prediction representation for all evaluation paths.

## 4. Flow map: regular stage vs benchmark

### 4.1 Regular stage flow (`cookimport stage`)

1. Convert source file(s)
2. Build recipes/tips/chunks
3. Write staged outputs
4. Done

No scoring step is included in this command.

### 4.2 Label Studio benchmark flow (`cookimport labelstudio-benchmark`)

1. Select gold freeform export
2. Select source file
3. Build prediction-run artifacts (upload mode calls `run_labelstudio_import(...)`, which uses `generate_pred_run_artifacts(...)`; offline mode calls `generate_pred_run_artifacts(...)` directly).
4. Choose upload vs offline: upload mode (default) sends tasks to Label Studio (`--allow-labelstudio-write` required), while offline mode (`--no-upload`) skips credential resolution and Label Studio API calls.
5. Recipe codex-farm parsing correction is currently policy-locked OFF (`--llm-recipe-pipeline off` only); benchmark prediction runs stay deterministic until this policy is revisited.
6. Evaluate predicted ranges vs gold ranges
7. Write eval report artifacts (`eval_report.json`, `eval_report.md`, misses/FPs) plus `run_manifest.json`

### 4.3 Offline suite flow (`cookimport bench run`)

1. For each suite item, call `generate_pred_run_artifacts` (offline, no upload)
   - CLI spinner/progress now reports `item X/Y [item_id] ...` through the full per-item loop.
2. Load predictions from `pred_run/label_studio_tasks.jsonl`
3. Load gold spans from `<gold_dir>/exports/freeform_span_labels.jsonl`
4. Evaluate + aggregate
5. Write `report.md`, `metrics.json`, `iteration_packet/*`

This is the "no Label Studio write" benchmark loop.

`cookimport bench sweep` wraps this same loop with outer `config X/Y` status updates and forwards nested item progress as `config X/Y | item X/Y ...`.

## 5. Where processed/staged outputs still fit in benchmark

Benchmark can still emit staged cookbook-style outputs for review:
- `labelstudio-benchmark` passes `processed_output_root` into prediction generation.

Important:
- Those staged outputs are side artifacts for inspection.
- Scoring still uses prediction tasks vs freeform gold spans.

So your intuition is partly right: benchmark does generate regular-looking outputs too, but they are not currently the scored surface.

## 6. Exact scoring surface (freeform)

Evaluation input A (predictions):
- `label_studio_tasks.jsonl`
- Parsed into labeled ranges via `load_predicted_labeled_ranges(...)`
- Label mapping is inferred from chunk metadata (`chunk_level`, `chunk_type`, hints)

Evaluation input B (gold):
- `freeform_span_labels.jsonl`
- Parsed via `load_gold_freeform_ranges(...)`
- Uses touched block indices from export payload
- Gold rows are deduped before scoring by `(source_hash, source_file, start_block_index, end_block_index)`.
- Conflicting duplicate labels resolve by majority vote; exact ties are dropped from scored gold and reported in eval `gold_dedupe.conflicts`.

Matching:
- Practical/content-overlap scoring (`practical_precision`, `practical_recall`, `practical_f1`): same label + source-compatible + any overlap (`intersection > 0`)
- Strict/localization scoring (`precision`, `recall`, `f1`): same label + source-compatible + Jaccard overlap threshold (default `0.5`)
- Optional source identity relaxation via `--force-source-match`
- `eval_report` also persists width stats (`span_width_stats`) and a `granularity_mismatch` flag when practical overlap is high but strict IoU is near zero because prediction ranges are much wider than gold.

Outputs:
- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`
- Freeform `eval_report` now includes `recipe_counts` diagnostics:
  - golden recipes from exported `RECIPE_TITLE` header count (`summary.recipe_counts.recipe_headers` when available),
  - predicted recipes from prediction-run manifest/report context (`recipe_count` / `totalRecipes` fallback),
  - markdown summary line for predicted-vs-golden recipe deltas.

### 6.1 Runtime telemetry emitted by benchmark runs

`labelstudio-benchmark` now persists benchmark timing in:
- prediction `manifest.json` (`timing`)
- eval `eval_report.json` (`timing`)
- benchmark `run_manifest.json` artifacts (`timing`)

Timing payload keys:
- wall/runtime totals: `total_seconds`, `prediction_seconds`, `evaluation_seconds`, `artifact_write_seconds`, `history_append_seconds`
- stage-aligned runtime fields when available: `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- checkpoints: `prediction_load_seconds`, `gold_load_seconds`, `evaluate_seconds`, plus prediction-generation checkpoints (`conversion_seconds`, `task_build_seconds`, optional split/processed-output checkpoints)

Interactive all-method reports now include timing rollups:
- per-source `all_method_benchmark_report.json` / `.md` include `timing_summary` and per-config `timing`
- combined `all_method_benchmark_multi_source_report.json` / `.md` include run-level `timing_summary` with slowest source/config references

## 7. Command matrix

| Command | Uploads to Label Studio | Scores predictions | Primary prediction source |
|---|---:|---:|---|
| `cookimport stage` | No | No | N/A |
| `cookimport labelstudio-benchmark` | Optional (upload mode only; `--allow-labelstudio-write`) | Yes | `label_studio_tasks.jsonl` from prediction run |
| Interactive benchmark menu flow | No (always offline) | Yes | `label_studio_tasks.jsonl` from one or more `labelstudio-benchmark` runs |
| `cookimport bench run` | No | Yes | `label_studio_tasks.jsonl` from offline pred run |

## 8. Common confusion points

### 8.1 "Benchmark should just score final outputs"

Today, benchmark contract is span/range based because gold is span/range based. Final outputs are downstream transforms and not the direct eval contract.

### 8.2 "Why is upload happening during benchmark?"

`labelstudio-benchmark` supports both upload and offline generation.
If you want no Label Studio side effects, use:
- `labelstudio-benchmark --no-upload`, or
- `cookimport bench run`.

Interactive benchmark from the main menu is now offline-only, with two modes:
- single offline mode (one local eval run, no upload),
- all-method mode (offline multi-config sweep, no upload).
  - all-method scheduler defaults are bounded: inflight pipelines=`4`, split-phase slots=`2`.
  - queued execution submits up to inflight capacity and refills as each config completes; if process workers cannot start, it auto-falls back to serial.
  - split-worker-heavy conversion is slot-gated across configs, so at most two configs run split conversion concurrently while other configs can pre/post-process.
  - all-method now supports `Single golden set` or `All golden sets with matching input files`.
  - all-matched scope resolves source hints from freeform export metadata in this order:
    1. run `manifest.json` `source_file`,
    2. first non-empty `freeform_span_labels.jsonl` row `source_file`,
    3. first non-empty `freeform_segment_manifest.jsonl` row `source_file`.
  - all-matched runs write the usual per-source `all_method_benchmark_report.{json,md}` files plus one combined root summary: `all_method_benchmark_multi_source_report.{json,md}`.

### 8.3 "Why did split conversion fail with pickling?"

Split benchmark returns worker payloads through multiprocessing, so payload metadata must be pickle-safe primitives.
The concrete failure case that already happened was `unstructured_version` resolving to a module object (`cannot pickle 'module' object`) instead of a string.

## 9. If you want "regular output scoring" in the future

That is feasible, but it would be a different benchmark mode with a new contract.

At minimum it would need:
1. A deterministic mapping from staged outputs back to block/range coordinates
2. A label projection layer equivalent to current chunk/task label mapping
3. Consistency rules for multi-recipe and non-recipe text spans
4. Tests proving parity/reliability against current task-based scoring

Until that exists, task-artifact scoring remains the most deterministic way to compare against freeform gold spans.

## 10. Core code map

- `cookimport/bench/suite.py`: suite manifest load/validate
- `cookimport/bench/pred_run.py`: offline pred-run builder (calls `generate_pred_run_artifacts`)
- `cookimport/bench/runner.py`: full suite run + per-item eval + aggregate report
- `cookimport/bench/sweep.py`: parameter sweep orchestration
- `cookimport/bench/report.py`: aggregate metrics/report rendering
- `cookimport/bench/packet.py`: iteration packet generation
- `cookimport/labelstudio/ingest.py`: prediction artifact generation + optional upload
- `cookimport/labelstudio/eval_freeform.py`: freeform range loading + scoring
- `cookimport/cli.py`: command wiring for `stage`, `labelstudio-benchmark`, and `bench`

## 11. Runbook

For quick command examples and output interpretation:
- `docs/07-bench/runbook.md`

## 12. Merged Understandings Batch (2026-02-23 cleanup)

### 2026-02-22_22.25.41 freeform gold dedupe behavior vs overlap

Merged source:
- `docs/understandings/2026-02-22_22.25.41-freeform-gold-dedupe-overlap-behavior.md`

Durable evaluation rule:
- Gold dedupe is overlap-count-agnostic because dedupe keys use absolute block ranges (`source_hash`, `source_file`, `start_block_index`, `end_block_index`), not segment IDs or overlap settings.
- Changing overlap can increase duplicate rows in exports, but exact range matches still collapse before scoring.
- Near-duplicates with different block ranges are not merged; only exact-range matches dedupe.

## 13. Merged Understandings Batch (2026-02-24 cleanup)

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
- `single_offline` uses benchmark run-settings chooser and can persist `last_run_settings_benchmark` snapshot.
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
- Parallel all-method defaults remain bounded (inflight pipelines=`4`, split-phase slots=`2`), and benchmark CSV append paths keep file locking to avoid header duplication/partial writes.

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

## 14. Merged Task Specs (2026-02-24 docs/tasks archival batch)

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
- All-method queue defaults are bounded (`inflight pipelines=4`, `split-phase slots=2`).
- Outer queue falls back to serial when process executor startup fails in restricted environments.
- Split-heavy conversion is slot-gated and benchmark CSV appends are file-locked for concurrency safety.
- Interactive all-method uses one persistent outer dashboard spinner; nested per-config benchmark spinner and completion dumps are suppressed during the sweep.
