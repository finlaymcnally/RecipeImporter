---
summary: "Agent SOP for QualitySuite: onboarding, fast deterministic tuning loop, and promotion-safe compare flow."
read_when:
  - "When an AI agent is using QualitySuite for the first time in this repo."
  - "When you need fast, deterministic run-settings tuning with resume/cache-aware loops."
  - "When deciding how to move from quick tuning evidence to promotion-safe validation."
---

# QualitySuite Agent SOP

## 1. Scope

QualitySuite is the active benchmark path for deterministic run-settings tuning and baseline-vs-candidate quality gating.

Active command flow:
1. `cookimport bench quality-discover`
2. `cookimport bench quality-run`
3. `cookimport bench quality-leaderboard`
4. `cookimport bench quality-compare`

Retired/disabled paths (historical artifacts only):
- `cookimport bench quality-lightweight-series`
- `scripts/quality_top_tier_tournament.py`

## 2. Guardrails

- Keep workflows deterministic and local-data-only.
- Do not enable Codex Farm permutations unless explicitly requested by the user and confirmed with:
  - `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Prefer resume/cache-aware continuation over fresh reruns.

## 3. Quick Onboarding Checklist

1. Read:
   - `docs/07-bench/qualitysuite-product-suite.md`
   - `docs/07-bench/07-bench_README.md` (quality sections)
2. Discover a small suite for rapid feedback:
   - `cookimport bench quality-discover --no-prefer-curated --max-targets 3`
3. Run a fast pruning-first quality loop (see SOP below).
4. Confirm outputs exist:
   - `suite_resolved.json`
   - `experiments_resolved.json`
   - `summary.json`
   - `report.md`
5. Use leaderboard/compare before making conclusions.

## 4. SOP A: Fast Deterministic Tuning Loop

Use this when the goal is quick directional evidence on deterministic setting levers.

1. Discover a compact suite.
2. Run quality with aggressive race pruning and no extra side outputs:
```bash
cookimport bench quality-run \
  --suite <suite.json> \
  --experiments-file <experiments.json> \
  --search-strategy race \
  --race-probe-targets 1 \
  --race-mid-targets 2 \
  --race-keep-ratio 0.15 \
  --race-finalists 12 \
  --max-parallel-experiments 4 \
  --no-include-deterministic-sweeps \
  --no-qualitysuite-agent-bridge \
  --io-pace-every-writes 0 \
  --io-pace-sleep-ms 0
```
3. If interrupted, continue with:
   - `--resume-run-dir <existing_run_dir>`
4. Rank outcomes with:
   - `cookimport bench quality-leaderboard --run-dir <run_dir> --experiment-id baseline`

Notes:
- `--search-strategy race` is default and should stay default for tuning loops.
- If race pruning cannot reduce the variant set, run metadata records a fallback-to-exhaustive reason.

## 5. SOP B: Promotion-Safe Validation Loop

Use this when deciding whether a candidate is safe vs baseline.

1. Run baseline and candidate quality runs with comparable suite/experiment scope.
2. Compare with regression gating:
```bash
cookimport bench quality-compare \
  --baseline <baseline_run_dir> \
  --candidate <candidate_run_dir> \
  --baseline-experiment-id baseline \
  --candidate-experiment-id candidate \
  --fail-on-regression
```
3. Require `settings_match=true` before interpreting metric deltas as clean setting impact.

## 6. Artifact Reading Order (Agent)

1. `<run_dir>/summary.json`
2. `<run_dir>/report.md`
3. `<run_dir>/experiments_resolved.json`
4. `<run_dir>/experiments/<experiment_id>/all_method_benchmark_multi_source_report.json`

If agent bridge is enabled:
1. `<run_dir>/agent_compare_control/qualitysuite_compare_control_index.json`
2. Scope insight JSONs
3. `agent_requests.jsonl`

## 7. Common Mistakes To Avoid

- Treating retired lightweight/tournament docs as runnable current flow.
- Restarting from scratch instead of `--resume-run-dir`.
- Interpreting candidate deltas when run settings are mismatched.
- Turning on deterministic sweeps during quick feedback loops when not needed.
- Enabling Codex Farm without explicit user confirmation.
