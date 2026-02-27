# Auto-scale all-method eval-tail concurrency to better use CPU (scheduler-only)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes ExecPlan authoring rules in `docs/PLANS.md`. Maintain this document in accordance with that file (single fenced block, prose-first, observable outcomes, mandatory living sections, and progress timestamps).

## Purpose / Big Picture

When running the interactive **All method benchmark** in `canonical-text` eval mode, long-running evaluation (“eval tails”) can dominate wall time while CPU sits at ~60–90% utilization. The user-visible symptom is the dashboard line showing something like `scheduler heavy 0/2 | wing 0 | active 6 | pending 3` while overall CPU is not saturated: many configs are stuck in evaluation and the scheduler is not admitting enough additional pipelines to fill idle cores.

After this change, **without changing the evaluation algorithm or scoring behavior**, the all-method scheduler will more aggressively (and safely) admit additional config pipelines during eval tails so more evaluations run concurrently, raising sustained CPU utilization during the tail and reducing end-to-end wall time for all-method sweeps on multi-core machines. The improvement is observable by:
- the live dashboard line showing a higher `active` count during eval tails (and an explicit `eval` count),
- per-source reports recording the effective eval-tail headroom that was used,
- and (on typical machines) a lower `source_wall_seconds` for canonical-heavy runs, with identical `eval_report.json` metrics for each config.

## Progress

- [x] (2026-02-27 00:15Z) Authored initial ExecPlan for CPU-aware eval-tail scheduling (scheduler-only; no eval algorithm change).
- [ ] Baseline: reproduce eval-tail underutilization and capture one “before” all-method run (dashboard line + per-source report metrics + wall time).
- [x] (2026-02-27 11:18Z) Add explicit “eval phase” counting to scheduler snapshots and dashboard line.
- [x] (2026-02-27 11:18Z) Implement CPU-aware configured/effective eval-tail headroom semantics, including CPU-bounded explicit overrides.
- [x] (2026-02-27 11:18Z) Update smart admission logic to cap eval-tail growth at `base_inflight + eval_tail_headroom_effective`.
- [x] (2026-02-27 11:18Z) Ensure process pool sizing matches smart mode max-active-during-eval ceiling.
- [x] (2026-02-27 11:18Z) Add/adjust unit tests for headroom/admission behavior and runtime/report contract fields.
- [ ] Run focused pytest suites + one end-to-end all-method smoke run; verify identical scoring outputs and improved tail utilization. (completed: focused pytest suites; remaining: live all-method smoke + before/after artifact capture)
- [x] (2026-02-27 11:18Z) Update internal docs (`cookimport/bench/CONVENTIONS.md`, `docs/07-bench/07-bench_README.md`) to reflect new defaults/telemetry.
- [x] (2026-02-27 11:18Z) Write `Outcomes & Retrospective` entry for implementation closeout status.

## Surprises & Discoveries

- Observation: The previous smart scheduler utilization assertion (`> fixed + 15%`) became too strict after aligning smart eval-tail cap semantics to `base + headroom`.
  Evidence: Targeted scheduler helper test initially failed at ~40.8% vs ~27.7% heavy-slot utilization (+13.1%), and passed after threshold rebalance while preserving “smart > fixed” behavior.

## Decision Log

- Decision: Treat `all_method_max_eval_tail_pipelines` as “extra inflight headroom granted only while configs are in `evaluate` phase” (smart scheduler only), and introduce an *auto-derived effective value* based on available CPU budget when the user has not explicitly pinned a value.
  Rationale: This matches the existing “eval-tail cap bounds extra inflight” intent, preserves current knobs, and improves CPU utilization without changing evaluation correctness.
  Date/Author: 2026-02-27 / ChatGPT-5.2 Pro

- Decision: Add an explicit `eval` counter to the live scheduler status line.
  Rationale: The existing line `heavy/wing/active/pending` does not make it obvious that “active” is dominated by eval tails; showing `eval` makes tail behavior and headroom effects observable and debuggable.
  Date/Author: 2026-02-27 / ChatGPT-5.2 Pro

- Decision: Treat explicit `all_method_max_eval_tail_pipelines` as *configured headroom* and clamp *effective headroom* by per-source CPU budget and remaining variants.
  Rationale: This closes the explicit-override safety gap and makes configured-vs-effective behavior auditable in runtime/report payloads.
  Date/Author: 2026-02-27 / Codex GPT-5

- Decision: Set smart eval-tail admission ceiling to `max_active_during_eval = configured_inflight + eval_tail_headroom_effective`, with worker pool limit aligned to that same ceiling.
  Rationale: This matches the OG speed1-2 contract and removes prior split+wing+dynamic-tail cap drift.
  Date/Author: 2026-02-27 / Codex GPT-5

## Outcomes & Retrospective

- 2026-02-27 implementation closeout (code + tests + docs):
  - Landed scheduler runtime contract updates in `cookimport/cli.py` with configured/effective eval-tail headroom, max-active-during-eval, and CPU budgeting telemetry fields.
  - Aligned smart admission + pool sizing to `configured_inflight + eval_tail_headroom_effective` semantics.
  - Updated scheduler report payloads and markdown renderers with configured/effective headroom visibility (legacy alias keys retained).
  - Added/updated targeted unit tests; focused suites passed:
    - `pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py`
    - `pytest -q tests/labelstudio/test_labelstudio_ingest_parallel.py`
    - `pytest -q tests/bench`
  - Remaining closure gap is still real-world before/after run artifact capture for wall-time/utilization evidence.

## Context and Orientation

### What “all-method benchmark” is in this repo

All-method benchmark runs many variants (“configs”) per source (book) by repeatedly invoking the same underlying benchmark primitive (the `labelstudio_benchmark(...)` path) in `canonical-text` eval mode. In plain language: it does “generate predictions” + “evaluate vs gold” for many extractor/knob permutations and ranks them.

Key code paths (from repo root):

- `cookimport/cli.py`
  - `_run_all_method_benchmark_multi_source(...)` — orchestrates multiple sources in parallel (outer layer).
  - `_run_all_method_benchmark(...)` — per-source scheduler that submits config pipelines and decides admission.
  - `_resolve_all_method_scheduler_runtime(...)` — resolves effective scheduler limits from `cookimport.json`.
  - `_run_all_method_config_once(...)` — runs one config (calls `labelstudio_benchmark(...)`).

- `cookimport/cli.py:labelstudio_benchmark(...)` — single benchmark flow.
  - Prediction generation: `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`
  - Evaluation: `cookimport/bench/eval_canonical_text.py:evaluate_canonical_text(...)` for `canonical-text`.

### Scheduler vocabulary (define terms up front)

- **Pipeline / config pipeline**: one end-to-end execution of a single all-method variant: prediction generation + evaluation + report writing for that config.

- **Heavy slot**: a concurrency slot reserved for “split-worker-heavy conversion” work (typically parallel PDF/EPUB splitting + conversion). The live dashboard shows it as `scheduler heavy X/Y`. This is a *safety throttle* so multiple configs do not simultaneously spawn large split worker pools and overload the machine.

- **Wing backlog**: a small buffer of “light-phase” configs admitted ahead of heavy work so heavy slots stay occupied. The dashboard shows it as `wing Z`. Wing items are prepped/queued such that when a heavy slot frees, a waiting config can immediately start heavy work.

- **Eval tail / evaluate phase**: the long-running canonical evaluation phase. Canonical eval time is dominated by full-book `difflib.SequenceMatcher` alignment. We are explicitly not changing this algorithm in this ExecPlan; we are only changing how many configs are allowed to run evaluation concurrently.

- **Active vs pending**: `active` are pipelines currently running in the per-source process pool; `pending` are queued variants not yet started.

### Why CPU underutilization happens in eval tails

Canonical eval is often single-core per pipeline (Python-heavy SequenceMatcher work). When many pipelines are in `evaluate` phase simultaneously, total CPU used is roughly proportional to the number of concurrent evaluating pipelines. If the scheduler caps “active pipelines” too low (or ties eval-tail headroom to split-slot counts), you can observe:
- heavy slots idle (`heavy 0/Y`),
- wing empty (`wing 0`),
- some `pending` remaining,
- and CPU < 100%.

The fix we want is purely scheduler tuning: allow more concurrent pipelines *specifically while evaluation is active*, up to a CPU-informed headroom limit, while keeping heavy-slot safety limits unchanged.

## Plan of Work

We will improve CPU usage during canonical eval tails by making the smart all-method scheduler “CPU-aware” about eval-tail concurrency. Concretely:

1. Establish a reproducible baseline: run one all-method sweep where canonical eval dominates, and record (a) the dashboard status line during the tail, (b) per-source report wall time, and (c) current effective scheduler limits.

2. Make eval tails observable:
   - ensure worker phase telemetry includes `evaluate` start/finish events (it should already),
   - update the scheduler snapshot computation to count how many active pipelines are currently in `evaluate` phase,
   - surface that as `eval E` on the dashboard line (and persist into per-source report `scheduler` block).

3. Compute an *effective eval-tail headroom* automatically from machine CPU capacity (and, when applicable, the effective number of parallel sources):
   - introduce a clear, documented formula for “auto eval-tail headroom”
   - preserve explicit user overrides when `cookimport.json` sets `all_method_max_eval_tail_pipelines`
   - bound the effective headroom to avoid absurd over-parallelism (never exceed the per-source CPU budget, and never go negative).

4. Apply that headroom in smart admission:
   - keep existing heavy-slot + wing backlog behavior unchanged,
   - but when at least one pipeline is in `evaluate` phase and there is still `pending` work, allow admitting additional pipelines up to:
     `max_active_during_eval = base_inflight + eval_tail_headroom_effective`
   - ensure the underlying `ProcessPoolExecutor(max_workers=...)` is sized to actually run that many pipelines concurrently.

5. Validate:
   - unit tests for headroom computation and admission conditions,
   - end-to-end smoke run showing:
     - identical eval outputs/metrics per config,
     - higher `active` (and `eval`) during the tail,
     - reduced wall time on the same machine/run shape.

### Milestone 1: Baseline and evidence capture (no behavioral change)

Goal: Produce a “before” snapshot proving the underutilization and current scheduler cap behavior.

Work:
- Run interactive all-method benchmark (canonical-text) on a source known to have long evals (any of the “cutdown” sources where eval dominates).
- Capture:
  - several dashboard line samples during the tail (especially when `heavy 0/Y` and `pending > 0`),
  - the per-source `all_method_benchmark_report.json` fields: `source_wall_seconds`, `scheduler` settings/metrics, and any `idle_gap_seconds`/utilization metrics,
  - and the effective scheduler limits printed before the run (configured vs effective).

Acceptance:
- You have one saved baseline run directory with those artifacts, and an annotated note in `Surprises & Discoveries` containing:
  - the observed dashboard line during underutilization, and
  - the CPU core count of the machine used (from `python -c "import os; print(os.cpu_count())"`).

### Milestone 2: Add eval-phase visibility to scheduler snapshots

Goal: The live dashboard line explicitly tells you how many pipelines are currently evaluating.

Work (implementation-level):
- Locate where per-config phase telemetry is written. In docs it is under `<source_root>/.scheduler_events/config_###.jsonl` with phase names including `prep`, `split_wait`, `split_active`, `post`, `evaluate`.
- Locate the code that reads/aggregates these events for live scheduling decisions (likely in `cookimport/cli.py` near `_run_all_method_benchmark(...)` or helper functions it calls).
- Extend the scheduler snapshot structure to include:
  - `eval_active_count`: number of active pipelines whose latest phase is `evaluate` and not yet finished.
- Update the dashboard render string from:
  - `scheduler heavy X/Y | wing Z | active A | pending P`
  to:
  - `scheduler heavy X/Y | wing Z | eval E | active A | pending P`
  (keep ordering stable and avoid multi-line noise).

- Persist this count into per-source report payload under the `scheduler` section as a rollup (for example: `eval_active_max`, `eval_active_median`, or at minimum `eval_active_max`).

Acceptance:
- During an all-method run, the dashboard line shows `eval E`.
- In the produced per-source report JSON, `scheduler` includes at least one eval-related metric so post-run analysis can confirm “this run was eval-tail dominated”.

### Milestone 3: CPU-aware eval-tail headroom (auto) in runtime resolution

Goal: The scheduler has a higher (and sensible) effective eval-tail headroom by default on multi-core machines, without requiring the user to manually tune settings.

Work:
- In `cookimport/cli.py:_resolve_all_method_scheduler_runtime(...)`, implement a function (private helper is fine) that computes:

  Definitions:
  - `cpu = os.cpu_count() or 1`
  - `cpu_budget_total = max(1, cpu - 1)`  (reserve 1 logical CPU for OS/coordinator; document this)
  - `source_parallelism_effective = min(all_method_max_parallel_sources_configured, number_of_sources_in_this_run)` when the multi-source wrapper is active; otherwise `1`.
  - `cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism_effective)`

  Baseline inflight:
  - `base_inflight = all_method_max_inflight_pipelines_effective` (already resolved/bounded)

  Auto headroom:
  - `auto_eval_tail_headroom = max(0, cpu_budget_per_source - base_inflight)`

  User override behavior:
  - If the user explicitly set `all_method_max_eval_tail_pipelines` (non-null / non-0 depending on existing semantics), treat it as `eval_tail_headroom_configured`.
  - Compute `eval_tail_headroom_effective = min(eval_tail_headroom_configured, cpu_budget_per_source)` if you want to forbid oversubscription; or `min(eval_tail_headroom_configured, cpu_budget_per_source * 2)` if you want to allow mild oversubscription. Pick one and document it.

  Default behavior:
  - If the user did not explicitly set the knob, set:
    `eval_tail_headroom_effective = auto_eval_tail_headroom`

- Ensure the resolved runtime object carries both configured and effective values so they can be printed before the run and persisted into reports:
  - `eval_tail_headroom_configured`
  - `eval_tail_headroom_effective`
  - and (optionally) `cpu_budget_per_source` and `source_parallelism_effective` for debugging.

Acceptance:
- Running the “print scheduler limits before confirmation” step shows a non-trivial eval-tail headroom on machines where `os.cpu_count()` > base inflight.
- The per-source report records the effective headroom used.
- No changes to benchmark metrics or eval outputs occur (this milestone only changes limits, not scoring).

### Milestone 4: Use eval-tail headroom in smart admission + ensure pool sizing

Goal: When eval tails exist and pending work remains, the scheduler admits more pipelines (up to the new effective limit), improving CPU usage during the tail.

Work:
- Identify the smart scheduler admission loop in `cookimport/cli.py:_run_all_method_benchmark(...)`. It likely:
  - tracks `active` futures,
  - tracks `pending` config indices,
  - uses phase telemetry to compute `heavy` and `wing`,
  - decides whether to submit new configs.

- Keep existing prewarm behavior:
  - target `heavy + wing ~= split_slots + wing_backlog_target`.

- Add eval-tail admission behavior:
  - If `eval_active_count > 0` AND `pending > 0`, allow `active` to grow beyond the baseline cap, up to:
    `max_active = base_inflight + eval_tail_headroom_effective`.
  - Make this admission conditional on smart mode being enabled (`all_method_smart_scheduler == true`) so fixed mode remains completion-refill only.

- Ensure the process pool can actually run `max_active` pipelines concurrently:
  - If the pool is currently sized to `base_inflight` (or `base_inflight + split_slots`), increase to at least:
    `pool_max_workers = base_inflight + eval_tail_headroom_effective`
    (or `max(base_inflight, base_inflight + eval_tail_headroom_effective)` if you store headroom separately).
  - If there is also a separate “post tail buffer” concept already, ensure `pool_max_workers` covers the *maximum* of all headroom mechanisms.
  - Document this in code comments: pool size must match scheduler’s maximum possible concurrent pipelines.

- Update scheduler status printing to show effective max during eval (optional but recommended):
  - For example, include `limit A/B` somewhere in the debug print before the run:
    “base inflight: 4; eval-tail headroom: 3; max active during eval: 7”.

Acceptance:
- In a real all-method run with long eval tails, you can observe the dashboard line show `active` rising beyond the old ceiling when:
  - `eval > 0`, `pending > 0`, and `heavy` is low/idle.
- The run completes successfully; all artifacts are written; no new deadlocks/timeouts appear.
- Per-config eval metrics are unchanged compared to a baseline run on the same inputs/configs (see Validation section for how to compare).

## Concrete Steps

All commands are run from the repository root unless stated otherwise.

### Baseline capture (Milestone 1)

1. Confirm CPU count:

    (repo_root)$ python -c "import os; print(os.cpu_count())"

2. Run interactive all-method benchmark (canonical-text):
   - Start interactive mode:

    (repo_root)$ cookimport

   - Navigate:
     - `Generate predictions + evaluate vs freeform gold`
     - `All method benchmark (offline, no upload)`
     - Choose a golden set + source that yields long canonical evals.

3. While the run is in the tail, copy a few dashboard lines into this ExecPlan under `Surprises & Discoveries`, for example:

    task: scheduler heavy 0/2 | wing 0 | active 6 | pending 3

4. After completion, locate the per-source report file:

    data/golden/benchmark-vs-golden/<timestamp>/all-method-benchmark/<source_slug>/all_method_benchmark_report.json

   Record `source_wall_seconds` and the scheduler settings block (exact key names in that JSON) into `Surprises & Discoveries`.

### Implementation steps (Milestones 2–4)

1. Find scheduler runtime and scheduler loop code:

    (repo_root)$ python -c "import inspect, cookimport.cli as c; print('loaded cookimport.cli')"

   Then open:
   - `cookimport/cli.py` and locate:
     - `_resolve_all_method_scheduler_runtime(...)`
     - `_run_all_method_benchmark_multi_source(...)`
     - `_run_all_method_benchmark(...)`

2. Find the code that reads `.scheduler_events/config_###.jsonl` and computes phase counts. Extend it to track `evaluate`.

3. Update the dashboard render string to include `eval E`.

4. Implement the CPU-aware headroom computation in `_resolve_all_method_scheduler_runtime(...)` and ensure it can receive (or determine) `source_parallelism_effective`.

5. Update smart admission logic to apply `max_active = base_inflight + eval_tail_headroom_effective` while `eval > 0`.

6. Ensure process pool sizing (`ProcessPoolExecutor(max_workers=...)`) supports that `max_active`.

### Tests

Run fast targeted tests first, then full suite if feasible:

    (repo_root)$ pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py
    (repo_root)$ pytest -q tests/labelstudio/test_labelstudio_ingest_parallel.py
    (repo_root)$ pytest -q tests/bench

If there is no `tests/bench` directory, run:

    (repo_root)$ pytest -q

## Validation and Acceptance

### Functional acceptance (scheduler behavior)

A run is considered successful if:

1. **No change in scoring correctness**
   - For at least one config pipeline, the `eval_report.json` key metrics (precision/recall/f1 or whatever canonical report uses) match a baseline run on the same inputs.
   - Practical way to check:
     - Pick one config run directory and compare `eval_report.json` before/after by extracting only the metric keys (ignore timestamps and resource snapshots).

2. **Eval-tail concurrency is observable**
   - The live dashboard line includes `eval E`.
   - During the tail, `eval` is > 0 and `active` rises beyond the previous steady-state ceiling when `pending > 0`.

3. **Wall time improves in eval-dominated cases**
   - On the same machine and similar workload, the per-source `source_wall_seconds` should decrease when canonical eval dominates, because more evaluations run concurrently.
   - This is a performance acceptance; it can be “best effort” because noise exists, but you should at least demonstrate that the scheduler is now *able* to run more evals concurrently (even if the user’s machine was already near saturation).

### Safety acceptance (no new deadlocks)

- The all-method run completes without getting stuck indefinitely at `N-1/N`.
- If per-config timeout handling exists (`all_method_config_timeout_seconds`), ensure that enabling increased eval concurrency does not spuriously trigger timeouts (if it does, document in `Surprises & Discoveries` and adjust headroom bounds).

## Idempotence and Recovery

- All changes are safe to rerun: benchmark outputs are written under timestamped run roots, so a failed run does not corrupt prior outputs.
- If the new scheduling causes instability (timeouts, memory pressure), recovery should be:
  1. set `cookimport.json.all_method_max_eval_tail_pipelines` to a small explicit number (e.g., 0 or 1 depending on semantics) to reduce eval headroom,
  2. rerun the same all-method benchmark and confirm stability,
  3. adjust the auto headroom bounding rule and add a regression test.

- Keep any new metrics additive in reports so older report readers don’t break.

## Artifacts and Notes

Include evidence snippets here as you implement:

- Baseline dashboard line during underutilization:

    task: scheduler heavy 0/2 | wing 0 | active 6 | pending 3

- After change, expected style:

    task: scheduler heavy 0/2 | wing 0 | eval 6 | active 7 | pending 2

- Example of pre-run printed scheduler limits (expected to be updated to include eval-tail headroom):

    configured/effective inflight: 4/4
    split slots: 2
    wing backlog target: 2
    eval-tail headroom (configured/effective): auto/3
    max active during eval: 7

## Interfaces and Dependencies

### Files/modules to touch

- `cookimport/cli.py`
  - `_resolve_all_method_scheduler_runtime(...)`: compute and return effective eval-tail headroom (CPU-aware auto).
  - `_run_all_method_benchmark_multi_source(...)`: ensure effective source parallelism is known for CPU budgeting (pass into runtime resolver or store in scheduler context).
  - `_run_all_method_benchmark(...)`: apply eval-tail headroom in smart admission; update dashboard state rendering; ensure pool sizing matches new max active.

- (Optional but recommended) `cookimport/bench/CONVENTIONS.md` and/or `docs/07-bench/07-bench_README.md`
  - Document new auto behavior and how to override with `cookimport.json`.

### New/updated internal data shapes

- Scheduler snapshot/state object (whatever struct/dict drives the dashboard line) must include:
  - `eval_active_count` (integer)
  - and must continue to include existing fields: heavy used/limit, wing, active, pending.

- Scheduler runtime object must include:
  - `base_inflight_effective`
  - `eval_tail_headroom_effective`
  - `max_active_during_eval` (derived)
  - (Optional) CPU budgeting fields for debugging/reporting.

### No algorithm changes

This ExecPlan must not:
- change the canonical evaluation algorithm (still full legacy `SequenceMatcher` alignment),
- change any scoring thresholds or metric definitions,
- change prediction generation logic.

Only concurrency/admission decisions and related telemetry are in scope.

---

Plan change note: Initial version created on 2026-02-27 to implement CPU-aware eval-tail admission and new `eval` visibility in the all-method scheduler dashboard, while keeping evaluation correctness unchanged.
Plan change note: Updated on 2026-02-27 to record implemented runtime/admission/report semantics (`configured/effective` eval-tail headroom, CPU-bounded explicit overrides, and `max_active_during_eval` cap) plus focused verification outcomes.
