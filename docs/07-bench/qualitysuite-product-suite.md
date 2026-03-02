---
summary: "Single operator guide for the QualitySuite product surface: lightweight discovery, phase tournament promotion, and final validation."
read_when:
  - When choosing which QualitySuite command flow to run for tuning or promotion
  - When you need one decision-oriented reference across quality-lightweight-series, tournament phases, and quality-run compare
---

# QualitySuite Product Suite

QualitySuite now has one cohesive operating model with three tracks:

1. Fast directional discovery (`bench quality-lightweight-series`)
2. Promotion confidence (`scripts/quality_top_tier_tournament.py` Phase A/B/B+)
3. Final validation and regression gating (`bench quality-run` + `bench quality-compare`)

Use this file as the primary "what should I run next?" reference.

Current status update (2026-03-01 to 2026-03-02):
- `cookimport bench quality-lightweight-series` is retired/disabled and exits immediately.
- `scripts/quality_top_tier_tournament.py` is retired/disabled and exits immediately.
- Track 1 and Track 2 below are historical workflow context only (useful for reading legacy artifacts), not active runnable commands.

## Default Preset Pack

Official phase presets:

- `data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-a-fast.json`
- `data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-b-confidence.json`
- `data/golden/bench/quality/thresholds/2026-03-01_10.15.00_qualitysuite-parsing-phase-b-plus-sweeps-decision.json` (optional)

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

## Track 2: Promotion Confidence (Phase A/B/B+)

Goal: promote parser settings with fold-level confidence criteria.

Phase A fast shortlist:

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-a-fast.json \
  --quick-parsing
```

Phase B confidence run:

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-03-01_01.00.00_qualitysuite-parsing-phase-b-confidence.json \
  --auto-candidates-from-latest-in data/golden/bench/quality/tournaments \
  --max-seeds 4
```

Optional B+ sweeps decision:

```bash
python scripts/quality_top_tier_tournament.py \
  --experiments-file data/golden/bench/quality/experiments/2026-03-02_00.36.30_qualitysuite-parsing-phase-a-candidates-qualityfirst-pruned.json \
  --thresholds-file data/golden/bench/quality/thresholds/2026-03-01_10.15.00_qualitysuite-parsing-phase-b-plus-sweeps-decision.json \
  --auto-candidates-from-latest-in data/golden/bench/quality/tournaments \
  --max-seeds 2
```

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
4. Use Track 1/2 command examples only to interpret legacy artifacts from older runs.
