---
summary: "Single operator guide for the QualitySuite product surface: historical discovery context plus active final validation and regression gating."
read_when:
  - When choosing which QualitySuite command flow to run for tuning or promotion
  - When you need one decision-oriented reference across historical QualitySuite flows and active quality-run compare
---

# QualitySuite Product Suite

QualitySuite now has one active operating track plus historical context for older artifacts:

1. Historical directional discovery (`bench quality-lightweight-series`)
2. Historical promotion confidence (removed tournament workflow)
3. Final validation and regression gating (`bench quality-run` + `bench quality-compare`)

Use this file as the primary "what should I run next?" reference.
For first-time AI-agent operation SOPs, see `docs/07-bench/qualitysuite-agent-sop.md`.

Current status update (2026-03-01 to 2026-03-02):
- `cookimport bench quality-lightweight-series` is retired/disabled and exits immediately.
- The old tournament script has been removed from the repo.
- Track 1 and Track 2 below are historical workflow context only (useful for reading legacy artifacts), not active runnable commands.

## AI-Agent Handoff (Active)

`bench quality-run` and `bench quality-compare` now generate an agent bridge bundle by default:

- quality-run: `<run_dir>/agent_compare_control/`
- quality-compare: `<comparison_dir>/agent_compare_control/`

Bundle files:

- `qualitysuite_compare_control_index.json`: machine-readable map of scopes, outcomes, and insight files.
- `<scope_id>__strict_accuracy.json` + `<scope_id>__macro_f1_excluding_other.json`: precomputed compare-control insights.
- `agent_requests.jsonl`: ready follow-up requests for `cookimport compare-control agent`.
- `README.md`: copy/paste command + recommended agent flow.

Minimal loop for an AI agent:

1. Run `bench quality-run` or `bench quality-compare` as normal.
2. Read `agent_compare_control/qualitysuite_compare_control_index.json`.
3. Inspect one scope insight JSON.
4. Run:

```bash
cookimport compare-control agent --output-root data/output --golden-root data/golden \
  < agent_compare_control/agent_requests.jsonl > agent_responses.jsonl
```

This keeps the bridge deterministic and local-data-only; no LLM parsing is required.

## Default Preset Pack

Official phase presets:

- `data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-a-fast.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-b-confidence.json`
- `data/golden/bench/quality/thresholds/2026-03-01_10.15.00_qualitysuite-parsing-phase-b-plus-sweeps-decision.json` (optional)
- `data/golden/bench/quality/experiments/2026-03-02_23.40.00_qualitysuite-pdf-first-small-pack.json` (small PDF-first deterministic pack)
- `data/golden/bench/quality/experiments/2026-03-03_09.41.22_qualitysuite-line-role-det-v1.json` (deterministic canonical line-role pack: `atomic_block_splitter=atomic-v1`, `line_role_pipeline=deterministic-v1`)

Official lightweight-series presets:

- `data/golden/bench/quality/lightweight_profiles/2026-03-02_00.36.30_qualitysuite-lightweight-main-effects-qualityfirst-pruned-v1.json`
- `data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-top-tier-tournament-full-candidates-qualityfirst-pruned.json`
- `data/golden/bench/quality/thresholds/2026-02-28_16.24.30_qualitysuite-top-tier-gates-fast-nosweeps.json`

Quality-first parser pruning in active presets:

- dropped `pre_br_split`, `pre_none`, `skip_headers_false`, `parser_v2_pre_br_skiphf_false`.

## Current Signal Snapshot (2026-03-01)

Evidence roots:

- `data/golden/bench/quality/runs/2026-03-01_11.08.23` (`bench quality-run`, 3 selected targets)
- `data/golden/bench/quality/tournaments/2026-03-01_11.01.44` (quick parser tournament; 1 effective fold after duplicate-suite dedupe)

Matched-pair parser/processing deltas from `2026-03-01_11.08.23` (A-B, quality-first interpretation):

- `epub_unstructured_html_parser_version`: `v2 - v1` => practical `-0.0296`, strict `-0.0314` (faster by `0.56s` mean).
- `epub_unstructured_preprocess_mode`: `semantic_v1 - none` => practical `+0.0262`, strict `+0.0180`.
- `epub_unstructured_preprocess_mode`: `semantic_v1 - br_split_v1` => practical `+0.0215`, strict `+0.0153`.
- `epub_unstructured_skip_headers_footers`: `false - true` => practical `-0.0012`, strict `-0.0009` (faster by `0.36s` mean).

Current default recommendation for quality-first parsing:

- Keep `epub_extractor=unstructured`.
- Prefer `parser=v1`, `preprocess=semantic_v1`, `skip_headers_footers=true`.
- Treat `section_shared_v1`, `instruction_segmentation_always`, `ingredient_missing_unit_policy=legacy_medium`, and `p6_yield_mode=scored_v1` as neutral on this 3-target sample until a larger fold set confirms uplift.

## Track 1: Fast Directional Discovery

Goal: get category-level answers quickly.

Run:

```bash
cookimport bench quality-lightweight-series \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --profile-file data/golden/bench/quality/lightweight_profiles/2026-03-02_00.36.30_qualitysuite-lightweight-main-effects-qualityfirst-pruned-v1.json \
  --experiments-file data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-top-tier-tournament-full-candidates-qualityfirst-pruned.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-02-28_16.24.30_qualitysuite-top-tier-gates-fast-nosweeps.json
```

Primary decision criteria:

- Use `round_1_main_effects.winners_by_category` to identify per-category winners.
- Require `round_2_composition.verdict == PASS` before trusting combined winner.
- Treat `round_3_interaction_smoke.findings` with `RISK` as a warning to confirm with tournament Phase B.

## Track 2: Historical Promotion Confidence (Phase A/B/B+)

Goal: promote parser settings with fold-level confidence criteria.

The former Phase A/B/B+ flow used a dedicated tournament script that has now been removed.
Legacy runs under `data/golden/bench/quality/tournaments/` can still be read, but the current replacement path is:

1. `cookimport bench quality-run`
2. `cookimport bench quality-leaderboard`
3. `cookimport bench quality-compare`

Primary decision criteria:

- Phase A: keep candidate only when fold deltas are non-regressive and mean strict/practical deltas are positive.
- Phase B promotion: candidate should satisfy confidence gates (`min_completed_folds=2`, `min_uplift_fold_ratio>=0.5`, mean strict/practical deltas `>= +0.004`, no source-success regression).
- B+ is optional and should not block parser promotion unless sweeps are part of the release decision.

## Track 3: Final Validation And Regression Gates

Goal: verify promoted config against baseline with reproducible run settings and explicit FAIL reasons.

Run baseline/candidate quality runs, then compare:

```bash
cookimport bench quality-compare \
  --baseline data/golden/bench/quality/runs/<baseline_timestamp> \
  --candidate data/golden/bench/quality/runs/<candidate_timestamp> \
  --baseline-experiment-id baseline \
  --candidate-experiment-id candidate \
  --fail-on-regression
```

Primary decision criteria:

- Treat compare `verdict=PASS` as promotion-safe under configured strict/practical/source-success thresholds.
- If `settings_match=false`, do not interpret metric deltas as pure model/setting change until parity is restored.

## Practical Escalation Path

1. Run `bench quality-run` with active pruned presets for current candidate evaluation.
2. Use `bench quality-leaderboard` to surface winner settings and Pareto tradeoffs.
3. Finish with `bench quality-compare` for formal regression gating versus baseline.
4. Use Track 1/2 notes only to interpret legacy artifacts from older runs.

## Mixed-Format Quick Loop (Active)

Use this when you want lightweight EPUB+PDF coverage without tournament workflows:

1. Discover with format visibility (and optional filter):
   - `cookimport bench quality-discover --no-prefer-curated --max-targets 6`
   - optional PDF-only: `cookimport bench quality-discover --no-prefer-curated --formats .pdf`
2. Run a small deterministic experiments pack:
   - `cookimport bench quality-run --suite <suite.json> --experiments-file data/golden/bench/quality/experiments/2026-03-02_23.40.00_qualitysuite-pdf-first-small-pack.json`
3. Generate global + by-format leaderboard slices:
   - `cookimport bench quality-leaderboard --run-dir <run_dir> --experiment-id baseline --by-source-extension`
