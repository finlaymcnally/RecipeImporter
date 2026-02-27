---
summary: "ExecPlan to improve all-method canonical-text runtime by making smart eval-tail admission CPU-aware and less prewarm-bound."
read_when:
  - "When implementing benchmark speed plan speed-2"
  - "When tuning all-method smart scheduler admission and eval-tail utilization"
---

# Improve all-method eval-tail utilization with CPU-aware smart admission

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes ExecPlan rules at `docs/PLANS.md`. Maintain this document in accordance with that file.

## Purpose / Big Picture

The interactive all-method benchmark already supports smart phase-aware admission, but canonical-text runs can still spend long periods in eval-heavy tails with idle CPU while pending configs remain. The current scheduler can become constrained by prewarm bookkeeping (`heavy + wing`) even when many active configs are already in `evaluate`, which limits how much eval concurrency is actually admitted.

After this change, all-method smart scheduling should admit additional config pipelines more consistently during eval tails, based on a CPU-aware eval-tail headroom limit, while preserving split-phase safety and scoring behavior. Users should observe this through a higher active count during eval tails, explicit eval visibility in scheduler snapshots, and lower wall time on eval-heavy runs with unchanged metrics.

## Progress

- [x] (2026-02-26_19.36.27) Rebuilt `docs/plans/speed-2.md` as a code-verified ExecPlan with required front matter and living-plan sections.
- [ ] Capture one baseline all-method canonical-text run that shows eval-tail underutilization (snapshot + report evidence).
- [ ] Implement CPU-aware effective eval-tail cap resolution in scheduler runtime wiring.
- [ ] Update smart admission gating so eval-tail headroom is usable when `evaluate_active > 0`.
- [ ] Expose eval activity in live scheduler snapshot text and persist eval-tail metrics in report scheduler blocks.
- [ ] Add/adjust scheduler unit tests for runtime resolution and smart-admission behavior.
- [ ] Run focused pytest coverage and one end-to-end all-method smoke run; compare correctness and runtime.
- [ ] Update bench docs for new scheduler semantics and complete retrospective.

## Surprises & Discoveries

- Observation: Eval-phase tracking already exists in scheduler internals (`evaluate_active` is computed from `.scheduler_events`), but the live snapshot line omits it.
  Evidence: `_compute_scheduler_counts(...)` returns `evaluate_active`; `_scheduler_snapshot(...)` currently renders only `heavy`, `wing`, `active`, `pending`.

- Observation: Smart admission currently uses two guards: `active < smart_active_cap` and `heavy_plus_wing < scheduler_base_target`; the second guard can stop admissions even during long eval tails.
  Evidence: `_run_all_method_benchmark(...)` loop around `smart_active_cap` and `heavy_plus_wing` in `cookimport/cli.py`.

- Observation: Default eval-tail cap is static (`max_eval_tail_pipelines` defaults to split-slot count), not CPU-aware.
  Evidence: `_resolve_all_method_scheduler_runtime(...)` sets `eval_tail_default = max(1, split_slots)`.

## Decision Log

- Decision: Keep scope scheduler-only. Do not change canonical evaluator algorithm, scoring thresholds, or label projection.
  Rationale: Speed-2 is intended to improve throughput safely; correctness-sensitive eval behavior must stay identical.
  Date/Author: 2026-02-26 / Codex

- Decision: Preserve existing settings keys (`all_method_max_eval_tail_pipelines`, `all_method_wing_backlog_target`, `all_method_smart_scheduler`) and add CPU-aware behavior as effective runtime resolution when values are not explicitly pinned.
  Rationale: Maintains user-facing compatibility while improving defaults.
  Date/Author: 2026-02-26 / Codex

- Decision: Extend scheduler observability (`eval` in snapshots plus report rollups) as part of the same change.
  Rationale: Throughput tuning is hard to validate without explicit eval-tail visibility.
  Date/Author: 2026-02-26 / Codex

## Outcomes & Retrospective

Pending implementation. Populate this section with measured before/after runtime, utilization, and correctness evidence as milestones complete.

## Context and Orientation

All-method benchmark orchestration is in `cookimport/cli.py`:

- `_run_all_method_benchmark_multi_source(...)` coordinates matched sources and source-level threading.
- `_run_all_method_benchmark(...)` executes per-source config scheduling with process workers and smart admission.
- `_resolve_all_method_scheduler_runtime(...)` resolves configured/effective scheduler limits.

Current smart scheduler behavior (today):

- Runtime resolution computes:
  - `configured_inflight_pipelines`
  - `split_phase_slots`
  - `wing_backlog_target`
  - `max_eval_tail_pipelines`
  - `effective_inflight_pipelines` (used for worker pool size)
- Event telemetry tracks per-config phases (`prep`, `split_wait`, `split_active`, `post`, `evaluate`, `done`) from `.scheduler_events/config_###.jsonl`.
- Smart admission loop computes:
  - `scheduler_base_target = split_slots + wing_target`
  - `dynamic_eval_tail = min(max_eval_tail_pipelines, evaluate_active)`
  - `smart_active_cap = scheduler_base_target + dynamic_eval_tail`
- Admission currently blocks when either:
  - `active >= smart_active_cap`, or
  - `heavy + wing >= scheduler_base_target`

This means eval-heavy tails can still be constrained by prewarm guardrails even when pending work exists and split-heavy slots are idle.

## Plan of Work

### Milestone 1: Baseline capture and acceptance contract

Run one canonical-text all-method scenario known to produce long eval tails and record:

- live snapshot lines during the tail (especially with `heavy` low and `pending > 0`),
- per-source `all_method_benchmark_report.json` scheduler fields and `source_wall_seconds`,
- machine CPU count (`os.cpu_count()`).

Write baseline evidence in `Surprises & Discoveries`. This anchors success criteria before code changes.

### Milestone 2: CPU-aware eval-tail runtime resolution

Update runtime resolution in `cookimport/cli.py` so eval-tail cap has explicit configured and effective forms.

Implementation target:

- If `all_method_max_eval_tail_pipelines` is explicitly set and valid, treat it as configured cap.
- If not explicitly set, derive an auto cap from CPU budget:
  - `cpu_total = os.cpu_count() or 1`
  - `cpu_budget_total = max(1, cpu_total - 1)` (reserve one logical core)
  - `source_parallelism_effective` comes from multi-source runtime (or `1` for single-source runs)
  - `cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism_effective)`
  - `auto_eval_tail_cap = max(0, cpu_budget_per_source - configured_inflight_pipelines)`
- Clamp effective cap to non-negative and practical bounds (`<= total_variants`).

Wire source parallelism context from `_run_all_method_benchmark_multi_source(...)` into `_run_all_method_benchmark(...)` and then into `_resolve_all_method_scheduler_runtime(...)` so the auto formula reflects real source fan-out.

Persist both configured/effective values into scheduler report payloads.

### Milestone 3: Smart admission changes for eval-tail headroom

Adjust smart admission in `_run_all_method_benchmark(...)` to use eval-tail headroom without being prematurely blocked by prewarm guardrails.

Concrete rule:

- Keep split-slot protection and prewarm behavior as the default while `evaluate_active == 0`.
- When `evaluate_active > 0`, permit additional admissions up to an eval-tail-aware cap:
  - `prewarm_target = split_slots + wing_target`
  - `eval_tail_boost = min(eval_tail_cap_effective, evaluate_active)`
  - `smart_active_cap = min(total_variants, prewarm_target + eval_tail_boost)`
- Update the second guard so `heavy + wing` is compared against a target that includes eval-tail boost while evaluation is active, instead of always comparing against `prewarm_target` only.

Keep worker pool sizing aligned with max possible active count to avoid scheduler dead zones.

### Milestone 4: Visibility, tests, and docs

Observability:

- Update snapshot string to include eval count:
  - from `scheduler heavy X/Y | wing Z | active A | pending P`
  - to `scheduler heavy X/Y | wing Z | eval E | active A | pending P`
- Add at least one eval-tail metric in report scheduler blocks (for example `max_eval_active_observed`).

Tests:

- Extend scheduler runtime tests in `tests/labelstudio/test_labelstudio_benchmark_helpers.py` to cover CPU-aware effective cap behavior and explicit override precedence.
- Update snapshot-format expectations that assert scheduler task lines.
- Add/adjust smart-scheduler behavior test so fake phase profile includes `evaluate` and asserts eval-tail admissions can exceed prewarm-only behavior while staying within effective inflight bounds.

Docs:

- Update `docs/07-bench/07-bench_README.md` and/or `cookimport/bench/CONVENTIONS.md` with the new effective-cap semantics and snapshot format.

## Concrete Steps

All commands run from repository root.

1. Prepare environment:

    source .venv/bin/activate
    python -m pip install -e .[dev]

2. Baseline evidence capture:

    python -c "import os; print(os.cpu_count())"
    cookimport

In interactive flow, run all-method benchmark in canonical-text mode and capture tail snapshots plus report paths.

3. Implement runtime + admission changes in `cookimport/cli.py`.

4. Update tests in `tests/labelstudio/test_labelstudio_benchmark_helpers.py`.

5. Run focused tests:

    source .venv/bin/activate
    pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py
    pytest -q tests/bench

6. Run one smoke all-method benchmark and compare before/after:

    source .venv/bin/activate
    cookimport

Validate snapshot behavior and compare per-source report runtime/metrics against baseline.

7. Update docs and then refresh docs index:

    npm run docs:list

8. Update this ExecPlan living sections (`Progress`, `Surprises & Discoveries`, `Decision Log`, `Outcomes & Retrospective`) with final evidence.

## Validation and Acceptance

Acceptance requires all of the following:

- Correctness parity:
  - canonical-text scoring metrics for the same config/input remain unchanged relative to baseline.
- Eval-tail observability:
  - scheduler snapshot includes `eval E`,
  - scheduler report includes at least one eval-tail activity metric.
- Throughput behavior:
  - in an eval-heavy tail with pending work, active pipelines can grow beyond prewarm-only behavior under smart mode.
- Stability:
  - no deadlock/regression in all-method completion,
  - timeout/retry behavior still works as expected.

## Idempotence and Recovery

Steps are safe to rerun because all benchmark outputs are timestamped and additive. If the new admission logic causes instability:

1. Set `all_method_smart_scheduler` to `false` in `cookimport.json` (or set eval-tail cap to a conservative explicit value).
2. Re-run the same benchmark scenario to confirm stability.
3. Keep test coverage for the failing shape, then tighten effective cap bounds before reenabling smart behavior.

## Artifacts and Notes

Collect these artifacts during implementation:

- Baseline and post-change scheduler snapshot snippets.
- Before/after per-source `all_method_benchmark_report.json` scheduler blocks.
- Before/after `source_wall_seconds` values on the same source/machine shape.
- Test output showing scheduler helper tests passing.

## Interfaces and Dependencies

Primary code surface:

- `cookimport/cli.py`
  - `_resolve_all_method_scheduler_runtime(...)`
  - `_run_all_method_benchmark(...)`
  - `_run_all_method_benchmark_multi_source(...)`

Primary tests:

- `tests/labelstudio/test_labelstudio_benchmark_helpers.py`

Related docs:

- `docs/07-bench/07-bench_README.md`
- `cookimport/bench/CONVENTIONS.md`

No evaluator algorithm changes are allowed in this plan. SequenceMatcher alignment logic and scoring formulas remain exactly as-is.

Plan change note: rebuilt on 2026-02-26_19.36.27 to replace an outdated draft with a front-matter-compliant, code-verified ExecPlan aligned to current scheduler behavior.
