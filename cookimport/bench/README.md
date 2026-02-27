# Bench Module

Offline benchmark orchestration code lives in this folder.
Durable benchmark scoring/scheduler/output contracts live in `cookimport/bench/CONVENTIONS.md`.

Current scoring contract:
- Predictions come from stage evidence manifests (`stage_block_predictions.json`), not pipeline chunk tasks.
- Gold can include multiple labels per block; eval accepts any matching gold label and logs multi-label diagnostics to `gold_conflicts.jsonl`.
- Missing gold rows for predicted blocks are defaulted to `OTHER` and logged in `gold_conflicts.jsonl`.
- Canonical-text eval supports optional disk-backed alignment reuse (`cookimport/bench/canonical_alignment_cache.py`); all-method runs share a per-source cache at `.cache/canonical_alignment`.
- Run-level prediction-stage replay uses `cookimport/bench/prediction_records.py` (`PredictionRecord` JSONL schema v1) for `labelstudio-benchmark --predictions-out/--predictions-in`.
- `bench run` writes per-item eval artifacts under `per_item/<item_id>/eval_freeform/` including:
  - `eval_report.json`, `eval_report.md`
  - `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`
