# Bench Module

Offline benchmark orchestration code lives in this folder.
Durable benchmark scoring/scheduler/output contracts live in `cookimport/bench/CONVENTIONS.md`.

Current scoring contract:
- Predictions come from stage evidence manifests (`stage_block_predictions.json`), not pipeline chunk tasks.
- Gold can include multiple labels per block; eval accepts any matching gold label and logs multi-label diagnostics to `gold_conflicts.jsonl`.
- Missing gold rows for predicted blocks are defaulted to `OTHER` and logged in `gold_conflicts.jsonl`.
- Canonical-text eval supports optional disk-backed alignment reuse (`cookimport/bench/canonical_alignment_cache.py`); all-method runs share a per-source cache at `.cache/canonical_alignment`.
- Canonical-text eval can choose SequenceMatcher implementation via `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER` (`fallback`, `stdlib`, `cydifflib`, `cdifflib`, `dmp`, `multilayer`; legacy `auto` aliases to `fallback`); evaluator telemetry records requested and effective mode. `multilayer` is an opt-in experimental mode for parity/speed spikes.
- Run-level prediction-stage replay uses `cookimport/bench/prediction_records.py` (`PredictionRecord` JSONL schema v1) for `labelstudio-benchmark --predictions-out/--predictions-in`.
- `labelstudio-benchmark --execution-mode predict-only` generates prediction artifacts (and optional prediction-record JSONL) without running evaluation.
- `bench run` writes per-item eval artifacts under `per_item/<item_id>/eval_freeform/` including:
  - `eval_report.json`, `eval_report.md`
  - `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`
- `bench run` accepts direct artifact-write overrides (`--write-markdown/--no-write-markdown`, `--write-labelstudio-tasks/--no-write-labelstudio-tasks`) that take precedence over config-file defaults for that run.
- canonical-text eval outputs include `aligned_prediction_blocks.jsonl` so alignment mappings can be compared directly across matcher implementations.
- Deterministic speed regression tooling lives in:
  - `speed_suite.py` (`bench speed-discover` target discovery from pulled gold exports)
  - `speed_runner.py` (`bench speed-run` repeated stage/benchmark timing samples)
  - `speed_compare.py` (`bench speed-compare` baseline-vs-candidate regression gating)
