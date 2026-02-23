---
summary: "Quick-start runbook for offline benchmark-suite commands, outputs, and interpretation."
read_when:
  - When running cookimport bench validate/run/sweep/knobs workflows
  - When onboarding contributors to offline benchmark iteration
---

# Offline Benchmark Runbook

Quick-start guide for running the offline bench suite — no Label Studio required.

## Prerequisites

- Python venv activated with dev deps installed
- Source files in `data/input/` (EPUB, PDF, etc.)
- Existing gold exports under `data/golden/` (from prior Label Studio annotation)

## 1. Validate a Suite

```bash
cookimport bench validate --suite data/golden/bench/suites/my_suite.json
```

This checks that all source files and gold export directories referenced in the suite actually exist.

## 2. Run the Benchmark

```bash
cookimport bench run --suite data/golden/bench/suites/my_suite.json
```

Outputs go to `data/golden/bench/runs/<timestamp>/`:

```
<timestamp>/
  suite_used.json       # Exact suite definition used
  report.md             # Aggregate recall/precision report
  metrics.json          # Machine-readable aggregate metrics
  knobs_effective.json  # Configuration values used
  iteration_packet/     # Ranked failure cases + context
    summary.md
    cases.jsonl
    top_failures.md
    README.md
  per_item/<item_id>/
    pred_run/           # Generated prediction artifacts
    eval_freeform/      # Evaluation results vs gold
```

### With a baseline for deltas

```bash
cookimport bench run \
  --suite data/golden/bench/suites/my_suite.json \
  --baseline data/golden/bench/runs/2026-02-12_10.00.00
```

The iteration packet will include metric deltas vs the baseline.

### With custom knob config

```bash
cookimport bench run \
  --suite data/golden/bench/suites/my_suite.json \
  --config my_knobs.json
```

Where `my_knobs.json` overrides defaults:
```json
{
  "segment_blocks": 60,
  "segment_overlap": 10
}
```

## 3. Interpret the Results

- **`report.md`** — Start here. Shows overall recall/precision and per-label breakdown.
- **`iteration_packet/top_failures.md`** — Top failures with block text context. Tells you exactly what the pipeline missed or hallucinated.
- **`iteration_packet/cases.jsonl`** — Machine-readable case list sorted by severity. Feed this to an agent or script.
- **`per_item/<id>/eval_freeform/eval_report.md`** — Detailed per-item evaluation with boundary diagnostics and app-aligned metrics.

## 4. Run a Parameter Sweep

```bash
cookimport bench sweep \
  --suite data/golden/bench/suites/my_suite.json \
  --budget 10 \
  --seed 42
```

Produces a leaderboard + best config under `data/golden/bench/runs/sweep_<timestamp>/`.

## 5. List Available Knobs

```bash
cookimport bench knobs
```

Shows all tunable parameters with their defaults, bounds, and descriptions.

## Suite Manifest Format

Suites are JSON files (commonly under `data/golden/bench/suites/`):

```json
{
  "name": "dev",
  "items": [
    {
      "item_id": "unique-identifier",
      "source_path": "data/input/mybook.epub",
      "gold_dir": "data/golden/<timestamp>/labelstudio/<slug>",
      "force_source_match": false,
      "notes": "Optional description"
    }
  ]
}
```

- `source_path` and `gold_dir` are repo-relative
- `gold_dir` must contain `exports/freeform_span_labels.jsonl` and `exports/freeform_segment_manifest.jsonl`
- `force_source_match` ignores source hash/file identity when matching (use for renamed/truncated variants)

## Improvement Loop

1. Run bench → read `iteration_packet/top_failures.md`
2. Identify a pattern (e.g., "ingredient lines in section X all missed")
3. Fix the parser/heuristic or adjust knobs
4. Re-run bench with `--baseline` pointing to the previous run
5. Check `iteration_packet/summary.md` for delta improvements
