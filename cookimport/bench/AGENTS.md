# Agent Guidelines — /cookimport/bench

This folder owns benchmark/QualitySuite orchestration code.

## QualitySuite is agent-first

- Treat QualitySuite as the primary deterministic tuning surface for benchmark settings.
- Start with `docs/07-bench/qualitysuite-agent-sop.md`.
- For full contract detail, read `docs/07-bench/07-bench_README.md`.

## Required operating rules

- Use active commands only:
  - `cookimport bench quality-discover`
  - `cookimport bench quality-run`
  - `cookimport bench quality-leaderboard`
  - `cookimport bench quality-compare`
- Do not use retired paths (`quality-lightweight-series`, `quality_top_tier_tournament.py`) for new work.
- Keep runs deterministic/local-data-only.
- Do not enable Codex Farm permutations unless explicitly requested and confirmed with:
  - `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Prefer cache and resume over reruns:
  - stable cache roots
  - `--resume-run-dir` for interrupted/partial runs

## Fast feedback defaults

- Use a small discovered suite for tuning loops.
- Use `--search-strategy race` for pruning unless exhaustive is explicitly required.
- Keep deterministic sweeps off unless the task is sweep-specific.
- Disable bridge bundle when not needed for the current loop:
  - `--no-qualitysuite-agent-bridge`
