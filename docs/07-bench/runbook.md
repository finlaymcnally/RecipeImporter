---
summary: "Quick-start runbook for active offline benchmark commands, outputs, and interpretation."
read_when:
  - When running cookimport bench speed/quality/eval-stage workflows
  - When running offline labelstudio-benchmark comparisons
---

# Offline Benchmark Runbook

Quick-start guide for active offline benchmark flows.

## Prerequisites

- Project venv activated with dev deps installed.
- Source files under `data/input/`.
- Freeform gold exports under `data/golden/pulled-from-labelstudio/.../exports/`.

## 1. Single offline benchmark run (prediction + eval)

Use `labelstudio-benchmark` in offline mode when you want one end-to-end benchmark run for one source/gold pair.

```bash
cookimport labelstudio-benchmark \
  --no-upload \
  --source-file data/input/mybook.epub \
  --gold-spans data/golden/pulled-from-labelstudio/mybook/exports/freeform_span_labels.jsonl \
  --eval-mode canonical-text
```

Artifacts go under `data/golden/benchmark-vs-golden/<timestamp>/` by default.

## 2. Evaluate an existing stage run only

Use `bench eval-stage` when predictions already exist under `.bench/*/stage_block_predictions.json` in a stage run.

```bash
cookimport bench eval-stage \
  --gold-spans data/golden/pulled-from-labelstudio/mybook/exports/freeform_span_labels.jsonl \
  --stage-run data/output/2026-02-28_00.00.00
```

Optional segmentation diagnostics knobs:

```bash
cookimport bench eval-stage \
  --gold-spans ... \
  --stage-run ... \
  --label-projection core_structural_v1 \
  --boundary-tolerance-blocks 0 \
  --segmentation-metrics boundary_f1,pk,windowdiff,boundary_similarity
```

Notes:
- `pk/windowdiff/boundary_similarity` require `segeval` installed.
- `bench eval-stage` does not regenerate predictions.

## 3. Speed regression loop

### 3.1 Discover deterministic targets

```bash
cookimport bench speed-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --out data/golden/bench/speed/suites/pulled_from_labelstudio.json
```

### 3.2 Run timing scenarios

```bash
cookimport bench speed-run \
  --suite data/golden/bench/speed/suites/pulled_from_labelstudio.json \
  --scenarios stage_import,benchmark_canonical_legacy \
  --warmups 1 \
  --repeats 2
```

Optional all-method scenario:

```bash
cookimport bench speed-run \
  --suite data/golden/bench/speed/suites/pulled_from_labelstudio.json \
  --scenarios benchmark_all_method_multi_source \
  --warmups 0 \
  --repeats 1 \
  --max-targets 3
```

If you enable Codex Farm permutations for speed runs, explicit positive confirmation is required:

```bash
cookimport bench speed-run \
  --suite data/golden/bench/speed/suites/pulled_from_labelstudio.json \
  --scenarios benchmark_all_method_multi_source \
  --warmups 0 \
  --repeats 1 \
  --max-targets 3 \
  --include-codex-farm \
  --speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION
```

When this scenario is used, inspect each run’s all-method scheduler telemetry for throughput tuning:
- `scheduler_timeseries.jsonl`: `admission_active_cap`, `admission_guard_target`, `admission_wing_target`, `admission_reason`
- report scheduler summary: split-slot guard fields (`split_phase_slots_requested`, `split_phase_slot_mode`, `split_phase_slot_cap_*`) and `adaptive_admission_*` counters

Optional deterministic settings pin:

```bash
cookimport bench speed-run \
  --suite data/golden/bench/speed/suites/pulled_from_labelstudio.json \
  --run-settings-file path/to/run_settings.json
```

### 3.3 Compare baseline vs candidate

```bash
cookimport bench speed-compare \
  --baseline data/golden/bench/speed/runs/<baseline_timestamp> \
  --candidate data/golden/bench/speed/runs/<candidate_timestamp> \
  --fail-on-regression
```

By default, compare enforces run-settings parity (`run_settings_hash`).
Use `--allow-settings-mismatch` only when intentional.

## 4. Quality regression loop

### 4.1 Discover deterministic quality targets

By default, discovery prioritizes `saltfatacidheatcutdown`, `thefoodlabcutdown`, and `seaandsmokecutdown` when matched; with `--max-targets`, remaining slots are filled by representative stratified selection using the configured `--seed`.

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --out data/golden/bench/quality/suites/pulled_representative.json \
  --max-targets 12 \
  --seed 42
```

To include *all* matched golden-set sources (no curated cutdown preference), omit `--max-targets` and pass `--no-prefer-curated`:

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --out data/golden/bench/quality/suites/pulled_all.json \
  --no-prefer-curated
```

### 4.2 Run quality experiments

```bash
cookimport bench quality-run \
  --suite data/golden/bench/quality/suites/pulled_representative.json \
  --experiments-file data/golden/bench/quality/experiments/example.json
```

If you enable Codex Farm permutations, you must provide explicit positive confirmation:

```bash
cookimport bench quality-run \
  --suite data/golden/bench/quality/suites/pulled_representative.json \
  --experiments-file data/golden/bench/quality/experiments/example.json \
  --include-codex-farm \
  --qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION
```

Experiment-level parallelism is CPU-aware by default (auto cap + adaptive worker target based on host load). Auto cap ceiling defaults to `16` and can be overridden with `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`. In environments where process-pool probing fails (for example `/dev/shm` permissions), auto mode switches experiment fanout to subprocess workers; override with `COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE=thread|subprocess|auto`. To pin a fixed cap:

```bash
cookimport bench quality-run \
  --suite data/golden/bench/quality/suites/pulled_representative.json \
  --experiments-file data/golden/bench/quality/experiments/example.json \
  --max-parallel-experiments 4
```

If a run is interrupted, resume from the existing run directory (it reuses completed experiment snapshots):

```bash
cookimport bench quality-run \
  --suite data/golden/bench/quality/suites/pulled_representative.json \
  --experiments-file data/golden/bench/quality/experiments/example.json \
  --resume-run-dir data/golden/bench/quality/runs/<existing_timestamp>
```

Quick tuning guide for `--max-parallel-experiments`:

| Experiment count | Suggested setting |
| --- | --- |
| 1-2 | omit flag (auto) or `2` |
| 3-6 | omit flag (auto) or `3-4` |
| 7-12 | omit flag (auto) or `5-8` |
| 13+ | omit flag (auto) or `8-16` (watch thermals/background load) |

`quality-run` now defaults to `--search-strategy race`, which does staged pruning:

1. Probe round on a small source subset.
2. Mid round on a larger subset.
3. Full-suite round on finalists only.

Force exhaustive full-grid evaluation with:

```bash
cookimport bench quality-run \
  --suite data/golden/bench/quality/suites/pulled_representative.json \
  --experiments-file data/golden/bench/quality/experiments/example.json \
  --search-strategy exhaustive
```

By default, quality all-method reruns reuse canonical/eval caches under `data/golden/bench/quality/.cache` (override with `COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`).

### 4.4 Global “best config” leaderboard (across all sources)

After a `bench quality-run`, aggregate the per-source all-method variant grid into one global ranking:

```bash
cookimport bench quality-leaderboard \
  --run-dir data/golden/bench/quality/runs/<timestamp> \
  --experiment-id baseline
```

This writes `leaderboard.json`, `leaderboard.csv`, `pareto_frontier.json`, `pareto_frontier.csv`, and `winner_run_settings.json` under `data/golden/bench/quality/runs/<timestamp>/leaderboards/<experiment_id>/<timestamp>/`.

### 4.3 Compare baseline vs candidate

```bash
cookimport bench quality-compare \
  --baseline data/golden/bench/quality/runs/<baseline_timestamp> \
  --candidate data/golden/bench/quality/runs/<candidate_timestamp> \
  --baseline-experiment-id baseline \
  --candidate-experiment-id candidate \
  --fail-on-regression
```

By default, compare enforces run-settings parity (`run_settings_hash`).
Use `--allow-settings-mismatch` only when intentional.

### 4.5 Top-tier certainty tournament (multi-seed)

Use the tournament script to run repeated quality folds and apply fixed PASS/FAIL gates before promoting settings:

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-02-28_10.31.55_qualitysuite-top-tier-tournament.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-02-28_10.31.55_qualitysuite-top-tier-gates.json
```

Optional fixed experiment cap (otherwise quality-run auto parallel mode is used):

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-02-28_10.31.55_qualitysuite-top-tier-tournament.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-02-28_10.31.55_qualitysuite-top-tier-gates.json \
  --max-parallel-experiments 4
```

Resume an interrupted tournament in the same directory (reuses completed folds and resumes partial fold quality-runs):

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-02-28_10.31.55_qualitysuite-top-tier-tournament.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-02-28_10.31.55_qualitysuite-top-tier-gates.json \
  --resume-tournament-dir data/golden/bench/quality/tournaments/<existing_timestamp>
```

Outputs are written under `data/golden/bench/quality/tournaments/<timestamp>/`:
- `tournament_resolved.json`: resolved config/seeds/candidates used for the run
- `folds.json`: per-fold quality metrics and leaderboard winner snapshots
- `summary.json`, `report.md`: aggregate PASS/FAIL verdicts and promoted top-tier candidates

Notes:
- Tournament runs now share canonical/eval cache across folds by default (`COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT` is set to `data/golden/bench/quality/.cache/canonical_alignment` unless overridden in thresholds `quality_run.canonical_alignment_cache_root`).
- If two seeds resolve to the same selected target set, duplicate folds are skipped and excluded from gate denominators.
- Between evaluated folds, gate-impossible candidates are pruned using optimistic best-case remaining-fold bounds, and later folds only run the surviving candidate subset plus baseline.

## 5. Artifact map

- `bench eval-stage`:
  - `eval_report.json`, `eval_report.md`
  - `missed_gold_blocks.jsonl`, `wrong_label_blocks.jsonl`
  - `missed_gold_boundaries.jsonl`, `false_positive_boundaries.jsonl`
- `bench speed-run`:
  - `summary.json`, `report.md`, `samples.jsonl`, `run_manifest.json`
- `bench speed-compare`:
  - `comparison.json`, `comparison.md`
- `bench quality-run`:
  - `summary.json`, `report.md`, `suite_resolved.json`, `experiments_resolved.json`
  - crash-safe incremental artifacts: `checkpoint.json`, `summary.partial.json`, `report.partial.md`, `experiments/<id>/quality_experiment_result.json`
- `bench quality-compare`:
  - `comparison.json`, `comparison.md`

## Improvement loop

1. Run one flow.
2. Inspect report + JSON artifacts.
3. Change parser/importer/scheduler settings.
4. Re-run and compare baseline vs candidate artifacts.
