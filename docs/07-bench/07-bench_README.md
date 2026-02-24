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
