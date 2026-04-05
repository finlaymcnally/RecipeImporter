---
summary: "Agent SOP for QualitySuite: active command flow, agent bridge, fast deterministic tuning, and promotion-safe compare flow."
read_when:
  - "When an AI agent is using QualitySuite for the first time in this repo."
  - "When choosing which QualitySuite command flow to run for tuning, validation, or older artifact reading."
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
- removed tournament workflow / old Phase A/B/B+ script path

Use this file as the only QualitySuite agent doc. Historical notes below exist only so older artifacts are interpreted correctly.

## 2. Guardrails

- Keep workflows deterministic and local-data-only.
- `bench quality-run` is deterministic-only and rejects live Codex recipe/knowledge surfaces.
- Do not enable Codex Farm permutations unless explicitly requested by the user and confirmed with:
  - `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Prefer resume/cache-aware continuation over fresh reruns.

## 3. Quick Onboarding Checklist

1. Read:
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

## 4. What To Run Next

Use this decision path:

1. Need quick directional evidence on settings:
   - `quality-discover` -> `quality-run` -> `quality-leaderboard`
2. Need promotion-safe baseline vs candidate validation:
   - `quality-run` for each side -> `quality-compare --fail-on-regression`
3. Need to understand old tournament or lightweight-series artifacts:
   - read the historical context in this doc, but do not try to reuse those flows as active commands

## 5. AI-Agent Handoff Bundle

`bench quality-run` and `bench quality-compare` write `agent_compare_control/` by default.

Bundle files:

- `qualitysuite_compare_control_index.json`: machine-readable scope/outcome map
- `<scope_id>__strict_accuracy.json` and `<scope_id>__macro_f1_excluding_other.json`: precomputed compare-control insights
- `agent_requests.jsonl`: ready follow-up requests for `cookimport compare-control agent`
- `README.md`: copy/paste local follow-up flow

Minimal agent loop:

1. Run `bench quality-run` or `bench quality-compare`.
2. Read `agent_compare_control/qualitysuite_compare_control_index.json`.
3. Inspect one scope insight JSON.
4. If needed, run:

```bash
cookimport compare-control agent --output-root data/output --golden-root data/golden \
  < agent_compare_control/agent_requests.jsonl > agent_responses.jsonl
```

This bridge is deterministic and local-data-only; it does not require LLM parsing.

## 6. SOP A: Fast Deterministic Tuning Loop

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

## 7. SOP B: Promotion-Safe Validation Loop

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

## 8. Mixed-Format Quick Loop

Use this when you want lightweight EPUB+PDF coverage without historical tournament workflows.

1. Discover with format visibility:
   - `cookimport bench quality-discover --no-prefer-curated --max-targets 6`
   - optional PDF-only: `cookimport bench quality-discover --no-prefer-curated --formats .pdf`
2. Run a small deterministic pack:
   - `cookimport bench quality-run --suite <suite.json> --experiments-file data/golden/bench/quality/experiments/2026-03-02_23.40.00_qualitysuite-pdf-first-small-pack.json`
3. Slice results:
   - `cookimport bench quality-leaderboard --run-dir <run_dir> --experiment-id baseline --by-source-extension`

## 9. Historical Context For Older Artifacts

- The former tournament workflow has been removed from the repo.
- Older runs under `data/golden/bench/quality/tournaments/` are still readable, but the current replacement path is:
  1. `cookimport bench quality-run`
  2. `cookimport bench quality-leaderboard`
  3. `cookimport bench quality-compare`
- When reading older promotion artifacts, use the old Phase A/B/B+ criteria only as artifact interpretation context, not as current runnable guidance.

## 10. Useful Preset Paths

Current commonly referenced deterministic packs:

- `data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-a-fast.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-b-confidence.json`
- `data/golden/bench/quality/thresholds/2026-03-01_10.15.00_qualitysuite-parsing-phase-b-plus-sweeps-decision.json` (optional)
- `data/golden/bench/quality/experiments/2026-03-02_23.40.00_qualitysuite-pdf-first-small-pack.json`
- `data/golden/bench/quality/experiments/2026-03-03_09.41.22_qualitysuite-line-role-det-v1.json`

## 11. Artifact Reading Order (Agent)

1. `<run_dir>/summary.json`
2. `<run_dir>/report.md`
3. `<run_dir>/experiments_resolved.json`
4. `<run_dir>/experiments/<experiment_id>/all_method_benchmark_multi_source_report.json`

If agent bridge is enabled:
1. `<run_dir>/agent_compare_control/qualitysuite_compare_control_index.json`
2. Scope insight JSONs
3. `agent_requests.jsonl`

## 12. Common Mistakes To Avoid

- Treating retired lightweight/tournament docs as runnable current flow.
- Restarting from scratch instead of `--resume-run-dir`.
- Interpreting candidate deltas when run settings are mismatched.
- Turning on deterministic sweeps during quick feedback loops when not needed.
- Enabling Codex Farm without explicit user confirmation.
