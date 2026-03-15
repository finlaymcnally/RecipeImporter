# Bench Module

Offline benchmark orchestration code lives in this folder.
Durable benchmark scoring/scheduler/output contracts live in `cookimport/bench/CONVENTIONS.md`.
Agent quick-start for QualitySuite in this folder lives in `cookimport/bench/AGENTS.md`.

Current scoring contract:
- Predictions come from stage evidence manifests (`stage_block_predictions.json`), not pipeline chunk tasks.
- Gold can include multiple labels per block; eval accepts any matching gold label and logs multi-label diagnostics to `gold_conflicts.jsonl`.
- Missing gold rows for predicted blocks are defaulted to `OTHER` and logged in `gold_conflicts.jsonl`.
- Canonical-text eval supports optional disk-backed alignment reuse (`cookimport/bench/canonical_alignment_cache.py`); all-method runs share a per-source cache at `.cache/canonical_alignment`.
- Canonical-text eval uses `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp` only; any non-`dmp` value is rejected and missing `fast-diff-match-patch` fails runtime selection.
- Run-level prediction-stage replay uses `cookimport/bench/prediction_records.py` (`PredictionRecord` JSONL schema v1) for `labelstudio-benchmark --predictions-out/--predictions-in`.
- Public `labelstudio-benchmark` runs always use pipelined execution; all-method orchestration keeps a private skip-evaluation prediction pass for prediction-record generation/reuse.
- `bench eval-stage` evaluates existing stage outputs against freeform gold and writes stage-block diagnostics (`eval_report.*`, `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`, boundary mismatch JSONL artifacts).
- canonical-text eval outputs include `aligned_prediction_blocks.jsonl` so DMP alignment mappings can be audited directly.
- line-role Milestone-5 diagnostics now live in `cutdown_export.py`, `pairwise_flips.py`, and `slice_metrics.py`; canonical line-role runs emit joined-line tables, flips, slice/knowledge metrics, and stable sampled cutdown JSONLs keyed by one `sample_id` source table.
- `line-role-pipeline/joined_line_table.jsonl` is intentionally conservative: it only attaches candidate-label / `decided_by` / recipe-span metadata when a line-role prediction can be matched to the canonical line by exact text (same index+text first, then exact-text sequence alignment). Split/merged or ambiguous duplicate lines stay unmatched instead of borrowing another line's telemetry.
- `followup_bundle.py` now powers the standalone `cf-debug` CLI for deterministic follow-up work on `upload_bundle_v1/`. The intended top-level loop is `upload_bundle_v1 -> web AI follow-up request manifest -> followup_dataN/` packet; lower-level selector/export/audit commands remain available under the same module.
- Multi-book single-profile `upload_bundle_v1` group bundles are now curated first-pass packets: target is ~30MB, raw prompt logs/full-context trace dumps stay local for follow-up, and `upload_bundle_index.json` records the actual final bundle bytes plus any trimmed paths.
- `upload_bundle_v1` generation now has explicit flexibility seams: `upload_bundle_v1_model.py` defines the normalized source model, `upload_bundle_v1_existing_output.py` adapts current benchmark roots into that model, and `upload_bundle_v1_render.py` hosts topology-tolerant rendering helpers used by the script wrapper.
- Deterministic speed regression tooling lives in:
  - `speed_suite.py` (`bench speed-discover` target discovery from pulled gold exports)
  - `speed_runner.py` (`bench speed-run` repeated stage/benchmark timing samples, including optional `benchmark_all_method_multi_source`)
  - `speed_compare.py` (`bench speed-compare` baseline-vs-candidate regression gating)
- Deterministic quality regression tooling now mirrors the speed loop:
  - `quality_suite.py` (`bench quality-discover` defaults to curated CUTDOWN target IDs: `saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`, `dinnerfor2cutdown`, `roastchickenandotherstoriescutdown`; falls back to representative stratified selection when unavailable, and retries filename matching when importer-scored discovery is empty)
  - `quality_runner.py` (`bench quality-run` supports adaptive parallel experiment execution with persistent canonical/eval + prediction-reuse caches under `data/golden/bench/quality/.cache`; race mode auto-falls back to exhaustive when finalists cannot prune the current variant set; gentle output-write pacing is enabled by default to reduce WSL disk I/O spikes and can be disabled via `--io-pace-every-writes 0` or `--io-pace-sleep-ms 0`)
  - `quality_compare.py` (`bench quality-compare` baseline-vs-candidate quality gating)
  - `quality_lightweight_series.py` (`bench quality-lightweight-series` main-effects-first orchestration: category screening, combined winner check, and interaction smoke variants with resume-compatible fold artifacts)
- Benchmark retention/GC tooling lives in `artifact_gc.py` and is surfaced via `cookimport bench gc` (dry-run by default, `--apply` for destructive pruning; optional `--include-labelstudio-benchmark` adds `data/golden/benchmark-vs-golden/*` pruning; any run root containing `.gc_keep*`/`.keep`/`.pinned` is never pruned; GC never rewrites/prunes `performance_history.csv`).
- `labelstudio-benchmark` auto-prunes only transient benchmark slop (excluded gate/gated/smoke/test/debug/quick/probe/sample/trial/regression suffix runs and `/bench/`-scoped benchmark artifacts), and keeps normal interactive run outputs; matching processed-output roots are pruned only for excluded runs.
- Interactive `C3imp` menu sessions force prune suppression for benchmark evals; interactive outputs are retained unless you run an explicit cleanup command later.
- Interactive single-offline and single-profile benchmark runs still honor the selected top-tier profile family, but Codex-backed benchmark selections expand into a paired `vanilla` then `codexfarm` benchmark sequence so same-run comparisons are available.
- Interactive multi-book single-profile progress now renders as a shared book grid: one column per selected book, per-book state/progress/ETA rows, and one worker row per active slot.
- Unified operator decision path is documented in `docs/07-bench/qualitysuite-product-suite.md`.
- Oracle upload is a post-bundle wrapper flow in `oracle_upload.py`: interactive single-offline runs auto-upload their session `upload_bundle_v1`, multi-book single-profile runs auto-upload only the top-level group bundle, and `cookimport bench oracle-upload <existing root>` is the no-rerun/manual retry path. `--mode dry-run` stays zero-cost: it uses Oracle's real dry-run for small bundles and falls back to a local preview when the payload file exceeds Oracle's inline size cap.
