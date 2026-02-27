---
summary: "ExecPlan to speed canonical-text evaluation by switching to a selectable drop-in SequenceMatcher implementation."
read_when:
  - "When implementing benchmark speed plan speed-1"
  - "When changing canonical-text alignment performance without changing scoring behavior"
---

# Accelerate canonical-text evaluation with a drop-in SequenceMatcher selector

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes ExecPlan requirements in `docs/PLANS.md`, and this file must be maintained in accordance with that document.

## Purpose / Big Picture

Canonical-text benchmark evaluation currently spends most of its runtime in a global text alignment step powered by Python stdlib `difflib.SequenceMatcher`. This is a correctness-critical step, so we are not changing alignment behavior or scoring rules. We are only changing the implementation used for `SequenceMatcher` to a drop-in accelerated option when available.

After this change, benchmark runs in canonical-text mode should keep identical scoring outputs while reducing alignment runtime. A human should be able to observe success by running the same evaluation once with `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib` and once with `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto`, then confirming equal outputs and lower `alignment_sequence_matcher_seconds` (or equivalent telemetry) in the accelerated run.

## Progress

- [x] (2026-02-26_19.30.26) Rebuilt this ExecPlan to be code-verified, front-matter compliant, and aligned to `docs/PLANS.md`.
- [ ] Capture a baseline canonical-text evaluation run and record timing + output identity evidence.
- [ ] Add a benchmark-local SequenceMatcher selector module with env-var controlled selection and explicit fallback behavior.
- [ ] Wire canonical alignment code to use the selector instead of direct stdlib import.
- [ ] Add parity tests for the SequenceMatcher methods used by canonical alignment.
- [ ] Add end-to-end canonical alignment regression coverage (stdlib forced vs accelerated allowed).
- [ ] Add implementation metadata to `evaluation_telemetry` and confirm it lands in `eval_report.json`.
- [ ] Re-run A/B comparison, capture evidence, and complete retrospective.

## Surprises & Discoveries

- Observation: `evaluate_canonical_text` always routes through legacy global alignment right now; fast alignment code exists but is deprecated and not selected for scoring.
  Evidence: `_align_prediction_blocks_to_canonical(...)` in `cookimport/bench/eval_canonical_text.py` always calls `_align_prediction_blocks_legacy(...)` and reports deprecation fields for fast mode.

- Observation: Current canonical alignment uses `SequenceMatcher(..., autojunk=False)` and consumes `get_matching_blocks()` output for block mapping.
  Evidence: `_align_prediction_blocks_legacy(...)` and `_collect_matching_blocks(...)` in `cookimport/bench/eval_canonical_text.py`.

## Decision Log

- Decision: Keep this plan strictly scoped to implementation substitution (`difflib` -> selectable drop-in), with no algorithm or threshold changes.
  Rationale: Canonical-text scoring is regression-sensitive and recent project guidance explicitly prioritizes correctness over risky alignment shortcuts.
  Date/Author: 2026-02-26_19.30.26 / Codex

- Decision: Prefer `cydifflib` in auto mode, with stdlib fallback always available.
  Rationale: `cydifflib` is designed as a drop-in for `difflib` and offers speedups while allowing strict parity testing.
  Date/Author: 2026-02-26_19.30.26 / Codex

- Decision: Avoid global monkey-patching of `difflib.SequenceMatcher`; use an explicit local selector module imported by benchmark alignment code.
  Rationale: Local wiring minimizes blast radius and keeps behavior explicit for debugging and rollback.
  Date/Author: 2026-02-26_19.30.26 / Codex

## Outcomes & Retrospective

Pending implementation. Fill this section as milestones complete, including measured before/after timing and any parity edge cases discovered.

## Context and Orientation

This section defines the current behavior so a new contributor can implement the plan without external context.

The canonical evaluator entrypoint is `cookimport/bench/eval_canonical_text.py:evaluate_canonical_text(...)`. It loads canonical artifacts and stage predictions, builds joined prediction text, aligns prediction blocks to canonical text, projects labels to canonical lines, computes metrics, and writes `eval_report.json` plus diagnostics.

Alignment currently depends on stdlib `SequenceMatcher` imported at module top (`from difflib import SequenceMatcher`). The main runtime path is `_align_prediction_blocks_legacy(...)`, which normalizes prediction and canonical text, constructs `SequenceMatcher(None, prediction_normalized, canonical_normalized, autojunk=False)`, then maps overlaps from `get_matching_blocks()` into block-level alignments. The helper `_collect_matching_blocks(...)` converts each match to `(pred_start, pred_end, canonical_start)` style tuples.

Runtime telemetry is emitted in `report["evaluation_telemetry"]` with subphase timings, resource counters, and work-unit counts. Canonical alignment subphase timers currently include `alignment_normalize_prediction_seconds`, `alignment_normalize_canonical_seconds`, `alignment_sequence_matcher_seconds`, and `alignment_block_mapping_seconds`. This is where implementation metadata for the selected matcher should be recorded.

Related project context:

- `docs/07-bench/07-bench_README.md` states canonical-text scoring uses legacy global alignment and tracks alignment subphase timing.
- `docs/understandings/2026-02-26_18.05.24-canonical-fast-align-deprecated.md` states fast alignment is deprecated and legacy alignment is enforced.

## Plan of Work

Implementation will proceed in small, verifiable steps. First, establish a baseline run so parity and speed claims can be proven with artifacts. Next, add a selector module dedicated to choosing a SequenceMatcher implementation using one env var and deterministic fallback logic. Then wire canonical alignment to instantiate matchers from that selector instead of stdlib directly, while preserving constructor arguments and method usage exactly.

After wiring, add tests at two levels. Unit-level parity tests compare stdlib and accelerated matcher outputs for the methods canonical alignment uses. End-to-end regression tests exercise the real canonical alignment path twice (forced stdlib and auto selection) and assert identical alignment/scoring outputs. Finally, extend telemetry with matcher implementation metadata and capture A/B run evidence.

No step in this plan changes label projection, metrics formulas, thresholds, fallback semantics for canonical scoring, or diagnostic artifact formats.

## Milestones

### Milestone 1: Baseline and contract capture

Capture current behavior before edits. Document exactly where and how SequenceMatcher is used, including constructor parameters and consumed methods. Run the smallest practical canonical-text benchmark scenario twice with current code and show deterministic output identity. Record timing fields and output paths in `Artifacts and Notes`.

Acceptance for Milestone 1 is a reproducible baseline transcript and a written call-surface contract in this plan.

### Milestone 2: Selector module and dependency wiring

Add a new module at `cookimport/bench/sequence_matcher_select.py` with a tiny selection API and metadata structure. The selector must support `auto` (default), `stdlib`, `cydifflib`, and optional `cdifflib` modes via env var `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`.

The module should expose:

- `SequenceMatcherSelection` data holder with matcher class, implementation name, version, and forced mode.
- `select_sequence_matcher()` to perform one selection.
- `get_sequence_matcher_selection()` with module-level cache.
- `SequenceMatcher(*args, **kwargs)` convenience constructor that forwards arguments unchanged.

`auto` mode should prefer `cydifflib`, then `cdifflib` if supported, then stdlib. Forced modes should raise a clear error if the requested package is unavailable.

Update dependency configuration in `pyproject.toml` to make accelerated matcher installation explicit (prefer optional extra like `benchaccel`). Update benchmark documentation with one short install/usage note.

Acceptance for Milestone 2 is a selector that reports sensible metadata in quick command-line checks and deterministic behavior for each env-var mode.

### Milestone 3: Canonical evaluator integration and telemetry

Replace direct stdlib matcher usage in `cookimport/bench/eval_canonical_text.py` with the selector-backed matcher constructor. Keep the same constructor argument pattern (`None`, normalized strings, `autojunk=False`) and the same downstream `get_matching_blocks()` workflow.

Add matcher metadata to `report["evaluation_telemetry"]`, for example implementation and version fields, while keeping numeric timing values numeric.

Acceptance for Milestone 3 is successful canonical evaluation with unchanged artifacts plus visible matcher metadata in `eval_report.json`.

### Milestone 4: Parity tests and A/B proof

Add/extend tests under `tests/bench/` to prove no accuracy change:

- parity tests for matcher outputs used by alignment (`get_matching_blocks()` and/or `get_opcodes()` if added);
- end-to-end canonical alignment regression (forced stdlib vs auto accelerated).

Then run A/B benchmark evaluation with the same input and confirm:

- identical scoring/alignment outputs,
- telemetry identifies different matcher implementations,
- accelerated run is faster in matcher subphase timing.

Acceptance for Milestone 4 is passing tests and recorded artifact evidence in this plan.

## Concrete Steps

Run all commands from repository root unless stated otherwise.

1. Prepare local Python environment.

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip

   If `pip` is unavailable inside the venv, bootstrap it locally:

    curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    python /tmp/get-pip.py

2. Install project + dev dependencies.

    python -m pip install -e .[dev]

3. Capture baseline canonical-text run twice and record output comparison.

    COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib cookimport labelstudio-benchmark ...
    COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib cookimport labelstudio-benchmark ...
    diff -u <run1>/eval_report.json <run2>/eval_report.json

4. Implement selector module and dependency changes.

5. Wire evaluator + telemetry fields.

6. Add/extend tests.

7. Run tests in venv.

    pytest -q

8. Run stdlib vs auto A/B comparison.

    COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib cookimport labelstudio-benchmark ... --eval-mode canonical-text
    COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto cookimport labelstudio-benchmark ... --eval-mode canonical-text
    diff -u <stdlib_run>/eval_report.json <auto_run>/eval_report.json

9. Update `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` with evidence and final results.

## Validation and Acceptance

This work is accepted when all of the following are true:

- Canonical-text outputs are identical between forced stdlib and auto accelerated runs for the same input.
- Matcher parity tests pass for the SequenceMatcher methods actually used by canonical alignment.
- `eval_report.json` telemetry records matcher implementation metadata.
- Alignment subphase timing shows a meaningful reduction in matcher time under accelerated mode on at least one representative run.
- If accelerated dependency is unavailable, auto mode falls back to stdlib and evaluation still completes.

## Idempotence and Recovery

All steps are safe to repeat. Dependency installs are idempotent, tests are repeatable, and baseline/A-B commands can be rerun with new output directories.

Rollback strategy is immediate and low-risk: set `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib` to force prior behavior at runtime. If a regression appears after code wiring, revert matcher wiring in `cookimport/bench/eval_canonical_text.py` first and keep selector/tests as preparatory scaffolding.

## Artifacts and Notes

Populate during implementation.

- Baseline run command(s):
  Evidence: pending.

- Baseline determinism check:
  Evidence: pending.

- Post-change stdlib vs auto output equality proof:
  Evidence: pending.

- Matcher telemetry snippet from `eval_report.json`:
  Evidence: pending.

- Before/after matcher timing excerpt:
  Evidence: pending.

## Interfaces and Dependencies

Environment variable contract:

- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`
  - `auto` (default): try accelerated matcher(s), then stdlib fallback.
  - `stdlib`: force stdlib `difflib.SequenceMatcher`.
  - `cydifflib`: force `cydifflib.SequenceMatcher`, error if unavailable.
  - `cdifflib`: force `cdifflib.CSequenceMatcher`, error if unavailable.

Planned new module:

- `cookimport/bench/sequence_matcher_select.py`
  - `SequenceMatcherSelection`
  - `select_sequence_matcher()`
  - `get_sequence_matcher_selection()`
  - `SequenceMatcher(*args, **kwargs)`

Planned modified module:

- `cookimport/bench/eval_canonical_text.py`
  - Replace direct stdlib matcher construction with selector-backed matcher construction.
  - Add matcher selection metadata into `evaluation_telemetry`.

Planned tests:

- `tests/bench/test_sequence_matcher_dropin_parity.py`
- `tests/bench/test_eval_canonical_text.py` or `tests/bench/test_canonical_alignment_regression.py`

Planned dependency config:

- Add optional extra for benchmark acceleration in `pyproject.toml` (preferred name `benchaccel`) including `cydifflib` and optional `cdifflib`.

---

Plan change notes:

- 2026-02-26_19.30.26: Rebuilt the plan to remove artifact text, align with current code paths, add required docs front matter, and tighten acceptance criteria to observable parity + speed evidence.
