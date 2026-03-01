# Bench Module

Offline benchmark orchestration code lives in this folder.
Durable benchmark scoring/scheduler/output contracts live in `cookimport/bench/CONVENTIONS.md`.

Current scoring contract:
- Predictions come from stage evidence manifests (`stage_block_predictions.json`), not pipeline chunk tasks.
- Gold can include multiple labels per block; eval accepts any matching gold label and logs multi-label diagnostics to `gold_conflicts.jsonl`.
- Missing gold rows for predicted blocks are defaulted to `OTHER` and logged in `gold_conflicts.jsonl`.
- Canonical-text eval supports optional disk-backed alignment reuse (`cookimport/bench/canonical_alignment_cache.py`); all-method runs share a per-source cache at `.cache/canonical_alignment`.
- Canonical-text eval uses `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp` only; any non-`dmp` value is rejected and missing `fast-diff-match-patch` fails runtime selection.
- Run-level prediction-stage replay uses `cookimport/bench/prediction_records.py` (`PredictionRecord` JSONL schema v1) for `labelstudio-benchmark --predictions-out/--predictions-in`.
- `labelstudio-benchmark --execution-mode predict-only` generates prediction artifacts (and optional prediction-record JSONL) without running evaluation.
- `bench eval-stage` evaluates existing stage outputs against freeform gold and writes stage-block diagnostics (`eval_report.*`, `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`, boundary mismatch JSONL artifacts).
- canonical-text eval outputs include `aligned_prediction_blocks.jsonl` so DMP alignment mappings can be audited directly.
- Deterministic speed regression tooling lives in:
  - `speed_suite.py` (`bench speed-discover` target discovery from pulled gold exports)
  - `speed_runner.py` (`bench speed-run` repeated stage/benchmark timing samples, including optional `benchmark_all_method_multi_source`)
  - `speed_compare.py` (`bench speed-compare` baseline-vs-candidate regression gating)
- Deterministic quality regression tooling now mirrors the speed loop:
  - `quality_suite.py` (`bench quality-discover` defaults to curated CUTDOWN target IDs: `saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`; falls back to representative stratified selection when unavailable, and retries filename matching when importer-scored discovery is empty)
  - `quality_runner.py` (`bench quality-run` sequential all-method experiment execution with persistent canonical/eval cache reuse under `data/golden/bench/quality/.cache` by default; when process pools are unavailable it auto-switches global all-method scheduling to legacy source-thread scheduling)
  - `quality_compare.py` (`bench quality-compare` baseline-vs-candidate quality gating)
  - `quality_lightweight_series.py` (`bench quality-lightweight-series` main-effects-first orchestration: category screening, combined winner check, and interaction smoke variants with resume-compatible fold artifacts)
