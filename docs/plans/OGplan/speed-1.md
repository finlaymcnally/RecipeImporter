# Accelerate canonical-text evaluation by swapping in a drop-in accelerated SequenceMatcher

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repo root. This ExecPlan must be maintained in accordance with `PLANS.md`.


## Purpose / Big Picture

Today, `cookimport`’s canonical-text benchmark evaluation is dominated by a full-book alignment step that uses Python’s standard-library `difflib.SequenceMatcher`. In real benchmark runs this is the overwhelming hotspot, and it directly drives slow all-method sweeps (long “eval tails” per config).

After this change, canonical-text evaluation should produce **identical results** (no accuracy compromise) while running materially faster by using a **drop-in** accelerated implementation of `SequenceMatcher` (prefer `cydifflib`, with safe fallback to stdlib). A human can see it working by running the same canonical-text evaluation twice (once forcing stdlib, once allowing accelerated) and observing:

- identical evaluation outputs (same metrics / same aligned mapping outputs),
- faster `evaluate_alignment_sequence_matcher_seconds` (or equivalent timing block),
- and explicit telemetry stating which SequenceMatcher implementation was used.


## Progress

- [x] (2026-02-27) Wrote ExecPlan focusing only on replacing `difflib.SequenceMatcher` with a drop-in accelerated implementation.
- [ ] Establish a baseline: run the smallest canonical-text eval you can locally and record (a) total eval time, (b) SequenceMatcher subphase time, and (c) output artifact hash/identity.
- [ ] Add an internal “SequenceMatcher selection” module that can choose `cydifflib`/`cdifflib`/stdlib deterministically (env-var controlled) and report metadata.
- [ ] Wire canonical-text alignment to use the selected SequenceMatcher implementation with zero behavior changes besides the class implementation.
- [ ] Add parity tests proving opcode/matching-block equivalence between stdlib and accelerated SequenceMatcher for the methods actually used by canonical alignment.
- [ ] Add an end-to-end canonical alignment regression test ensuring “stdlib vs accelerated” produces byte-identical alignment outputs for a representative fixture.
- [ ] Add/extend evaluation telemetry to record which implementation/version was used, and whether we fell back to stdlib.
- [ ] Re-run baseline scenario: confirm identical outputs and faster timings; capture evidence in `Artifacts and Notes`.


## Surprises & Discoveries

(Keep this section updated as you learn things while implementing.)

- Observation: …
  Evidence: …


## Decision Log

- Decision: Prefer `cydifflib.SequenceMatcher` as the accelerated drop-in implementation.
  Rationale: It is designed to be used “in the same way as difflib” and treats any behavior difference as a bug, which matches our “no accuracy compromise” requirement. We still verify parity with tests.
  Date/Author: 2026-02-27 / ExecPlan author

- Decision: Keep a strict, always-available fallback to stdlib `difflib.SequenceMatcher`, and add an env var to force stdlib for debugging or bisecting.
  Rationale: Benchmark correctness must not depend on an extension module being present or correct on every machine; forcing stdlib is essential for reproducible comparisons.
  Date/Author: 2026-02-27 / ExecPlan author

- Decision: Do not monkey-patch `difflib.SequenceMatcher` globally; instead, change the canonical evaluator to use an explicit local import from our selector module.
  Rationale: Global monkey-patching is hard to reason about and can affect unrelated code paths. We want the smallest blast radius.
  Date/Author: 2026-02-27 / ExecPlan author

- Decision: Add parity tests that compare *values* (tuples/opcode lists), not types, when comparing `Match` / internal structs.
  Rationale: A drop-in implementation may return a compatible-but-not-identical class type, while still being behaviorally identical.
  Date/Author: 2026-02-27 / ExecPlan author


## Outcomes & Retrospective

(Fill this in as milestones complete. Summarize what improved, what stayed the same, and any follow-ups.)


## Context and Orientation

Relevant concepts, in plain language:

- **Canonical-text evaluation**: A benchmark mode that compares predicted output vs a canonical “gold” text. Because the predicted output and gold text do not share identical segmentation, evaluation aligns them first.
- **Alignment**: The process of finding which spans of predicted text correspond to which spans of gold text so scoring can be done meaningfully.
- **`difflib.SequenceMatcher`**: A standard-library class for “human friendly” diffs between sequences. In CPython it is implemented in Python and can be very slow on large inputs.

Repository locations to know (paths are repo-relative):

- `cookimport/bench/eval_canonical_text.py`
  - Contains `evaluate_canonical_text(...)` and the alignment helper `_align_prediction_blocks_to_canonical(...)` (or similarly named), where `difflib.SequenceMatcher` is used for full-book alignment.
- `cookimport/bench/CONVENTIONS.md`
  - Contains benchmark scoring contracts. In particular, canonical-text scoring enforces legacy full-book `SequenceMatcher` alignment for correctness; this plan respects that by changing only the implementation, not the algorithm or constraints.
- `cookimport/cli.py` and `cookimport/labelstudio/ingest.py`
  - Orchestrate `labelstudio-benchmark` and all-method benchmark scheduling; they rely on canonical evaluator outputs.

What “drop-in accelerated implementation” means for this plan:

- The code continues to call the same `SequenceMatcher` methods with the same parameters.
- Alignment output must be identical for the same inputs.
- We only change which class provides the implementation (`difflib.SequenceMatcher` vs an accelerated replacement), not the algorithm, not the alignment logic, and not the scoring logic.


## Plan of Work

This change is deliberately scoped to the benchmark evaluator and is designed to be safe-by-default:

1. Create a small selector module responsible for choosing the SequenceMatcher implementation:
   - Prefer `cydifflib.SequenceMatcher` when available.
   - Optionally support `cdifflib.CSequenceMatcher` as a secondary choice (if present).
   - Always support stdlib `difflib.SequenceMatcher`.
   - Allow forcing a specific choice via an environment variable so we can A/B compare correctness and performance on the same machine.

2. Update `cookimport/bench/eval_canonical_text.py` so the alignment step uses the selected `SequenceMatcher` class from the selector module instead of importing `difflib.SequenceMatcher` directly.

3. Add explicit evaluator telemetry recording:
   - Which implementation was used (`stdlib`, `cydifflib`, `cdifflib`).
   - Which package version (if applicable).
   - Whether the selection was forced or automatic.
   This is required so performance results are interpretable later from JSON artifacts without rerunning profiling.

4. Add tests that prove “no accuracy compromise”:
   - Parity tests comparing the exact methods used by canonical alignment (for a curated set of tricky strings).
   - An end-to-end alignment regression test comparing “stdlib forced” vs “accelerated allowed” outputs on a small fixture.

5. Add a tiny developer-facing benchmark script (optional but recommended) that times `get_opcodes()` (or the relevant call) on representative large-ish strings so a developer can see a quick speed delta without running a whole book benchmark.


## Milestones

### Milestone 1: Identify the exact SequenceMatcher surface used by canonical alignment (baseline + contract)

At the end of this milestone you will have a written note (in this ExecPlan’s `Artifacts and Notes`) that answers:

- Where `SequenceMatcher` is instantiated in `cookimport/bench/eval_canonical_text.py`.
- Which methods are called (`get_opcodes`, `get_matching_blocks`, `ratio`, etc.).
- Which constructor parameters are used (especially `isjunk` and `autojunk`).
- A baseline timing and a “golden output identity” for a small canonical-text eval run.

Work:

- Open `cookimport/bench/eval_canonical_text.py` and search for `SequenceMatcher(`.
- Locate the canonical alignment function (often `_align_prediction_blocks_to_canonical(...)`).
- Write down the exact SequenceMatcher call pattern and store it in this plan.
- Run the smallest canonical-text eval you can locally (choose a very small fixture/suite if available) twice:
  - once as-is (current code),
  - and once again to confirm determinism (outputs should match exactly even before changes).
- Record:
  - the eval report path(s),
  - the SequenceMatcher timing fields you have today (if any),
  - and a diff result (should be empty).

Proof:

- A short transcript showing the command(s) used and where the produced `eval_report.json` (or equivalent) lives.
- A short transcript showing “diff is empty” (or identical hash) between two baseline runs.


### Milestone 2: Add a SequenceMatcher selector module + optional dependency

At the end of this milestone, code will exist that allows:

- selecting a SequenceMatcher implementation (`stdlib` / `cydifflib` / `cdifflib`) in a single place,
- forcing stdlib for parity comparison,
- and reporting which implementation/version was chosen.

Work (implementation):

- Create a new module: `cookimport/bench/sequence_matcher_select.py` (new file).

  The module must define:

  - A small “metadata” structure (a `dataclass` is fine) like:

        class SequenceMatcherSelection:
            matcher_cls: type
            impl: str  # "stdlib" | "cydifflib" | "cdifflib"
            version: str | None
            forced_by: str | None  # env var value if forced, else None

  - A function:

        def select_sequence_matcher() -> SequenceMatcherSelection:

    Behavior:

    - Read env var `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`.
      Supported values (case-insensitive):
      - `auto` (default when unset): try `cydifflib`, else `cdifflib`, else stdlib.
      - `stdlib`: use `difflib.SequenceMatcher`.
      - `cydifflib`: require `cydifflib` import; raise a clear error if unavailable.
      - `cdifflib`: require `cdifflib` import; raise a clear error if unavailable.

    - For `cydifflib`, import:

          from cydifflib import SequenceMatcher as CySequenceMatcher

    - For `cdifflib`, import:

          from cdifflib import CSequenceMatcher

    - Determine package version using `importlib.metadata`:
      - `importlib.metadata.version("cydifflib")`
      - `importlib.metadata.version("cdifflib")`
      Catch exceptions and store `None` if version cannot be resolved.

  - A module-level cached selection so we don’t re-run imports/version checks repeatedly:

        _SELECTION = None
        def get_sequence_matcher_selection() -> SequenceMatcherSelection: ...

  - A convenience alias used by callers:

        def SequenceMatcher(*args, **kwargs):
            return get_sequence_matcher_selection().matcher_cls(*args, **kwargs)

    Important: do not change any arguments; pass through exactly.

- Add the optional dependency to `pyproject.toml`.

  Strategy:

  - Prefer to add as an optional extra, because this is benchmark-only acceleration and we want to avoid forcing a compiled extension on every consumer who just wants `stage`.
  - Create a new optional extra named `benchaccel` (or, if the repo already has an established bench extra, add to that instead).

  Example intent (adapt to the repo’s exact pyproject structure):

  - `benchaccel` should include `cydifflib` (primary).
  - Optionally include `cdifflib` (secondary fallback), or leave it out and treat it as “user-installed fallback”.
    (If you include both, still prefer `cydifflib` at runtime.)

- Ensure installation instructions exist (minimal):
  - Add one short note to `cookimport/bench/CONVENTIONS.md` describing:
    - how to install the extra, and
    - the env var for forcing stdlib vs accelerated.

Proof:

- A short transcript showing how to install the extra in editable mode, for example:

      $ python -m pip install -e '.[benchaccel]'

  (If your repo uses a different install approach, adapt the command and write it down here.)

- A short transcript showing the selector metadata prints something sensible:

      $ python -c "from cookimport.bench.sequence_matcher_select import get_sequence_matcher_selection; print(get_sequence_matcher_selection())"
      SequenceMatcherSelection(... impl='cydifflib' ...)

  And also forcing stdlib:

      $ COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib python -c "..."
      ... impl='stdlib' ...


### Milestone 3: Wire canonical evaluation to use the selector + prove zero accuracy change

At the end of this milestone:

- canonical alignment uses the selector’s SequenceMatcher implementation,
- evaluation artifacts/telemetry record which implementation was used,
- and tests prove stdlib vs accelerated produce identical results for representative cases.

Work (code wiring):

- In `cookimport/bench/eval_canonical_text.py`:
  - Replace direct uses of `difflib.SequenceMatcher` with the selector module.
  - Keep *all parameters* exactly the same as baseline (Milestone 1 contract).
  - Do not change:
    - normalization,
    - chunking,
    - the alignment algorithm,
    - thresholds,
    - fallbacks,
    - or any “fast align”/bounded behavior (this plan is explicitly “no accuracy compromise”).

- Add evaluator telemetry:
  - Wherever `evaluation_telemetry` is assembled in canonical eval, add fields like:

        evaluation_telemetry["alignment_sequence_matcher_impl"] = selection.impl
        evaluation_telemetry["alignment_sequence_matcher_version"] = selection.version
        evaluation_telemetry["alignment_sequence_matcher_forced_by"] = selection.forced_by

  - Keep numeric timing fields numeric; store these string fields in the rich telemetry object (consistent with existing telemetry conventions).

Work (tests):

- Create `tests/bench/test_sequence_matcher_dropin_parity.py` (new test file).

  Tests should:

  - Skip cleanly if `cydifflib` is not installed (but see note below about CI).
  - For a set of curated string pairs, compare difflib vs accelerated results for the exact methods canonical alignment uses.

  Required tricky cases to include:

  - long repeated patterns (to stress “popular element” logic and autojunk behavior),
  - many small edits (to stress opcode emission),
  - whitespace-heavy text (to stress potential junk handling),
  - and at least one “large-ish” case (but keep test runtime reasonable).

  Comparison approach:

  - Compare opcodes exactly:

        difflib_sm.get_opcodes() == accel_sm.get_opcodes()

  - If you compare matching blocks, compare the `(a, b, size)` triples rather than object identity/type.

  - Ensure you construct both matchers with the same parameters as canonical alignment (from Milestone 1).

- Add/extend an end-to-end alignment regression test.

  Where to put it depends on existing test layout. Prefer:
  - `tests/bench/test_eval_canonical_text.py` if it already exists, or
  - `tests/bench/test_canonical_alignment_regression.py` otherwise.

  The test must:

  - Run a minimal canonical alignment on a fixture that exercises the real alignment function used in evaluation (not just SequenceMatcher directly).
  - Execute twice:
    1) with `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib`
    2) with `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto` and `cydifflib` installed
  - Assert that the alignment output is identical.
    “Alignment output” should be something deterministic and meaningful in your codebase, for example:
    - the aligned span mapping,
    - the produced aligned block list,
    - or a JSON-serializable representation of alignment decisions.

  If the canonical alignment function does not currently expose a stable representation, add a small internal helper (pure function) that returns a JSON-serializable structure, and have both evaluation and the test use it. Do not change alignment behavior; only make it observable.

CI/test dependency note:

- If your CI does not install extras by default, update the CI install step (or your dev requirements) so that `cydifflib` is present when tests run. Otherwise the parity tests will always skip and won’t protect correctness.

Optional: quick local micro-benchmark script:

- Add `scripts/bench_sequence_matcher_impl.py` that:
  - generates or loads two large-ish strings,
  - times `get_opcodes()` under stdlib vs accelerated,
  - prints both times and the selected implementation.
  - Keep it simple and dependency-free.

Proof:

- Test run transcript:

      $ pytest -q
      ... passed ...

- Canonical eval A/B evidence:
  - Run one canonical-text eval forcing stdlib and save its report.
  - Run the same eval allowing accelerated selection and save its report.
  - Show:
    - a diff of the output reports is empty (or key metrics + alignment artifact equality),
    - telemetry includes your new `alignment_sequence_matcher_*` keys,
    - and the SequenceMatcher timing is lower under accelerated.

  Example shape (adapt to your project’s actual commands and paths):

      $ COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib cookimport labelstudio-benchmark ... --run-dir /tmp/eval_stdlib
      $ COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto   cookimport labelstudio-benchmark ... --run-dir /tmp/eval_accel
      $ diff -u /tmp/eval_stdlib/eval_report.json /tmp/eval_accel/eval_report.json
      (no output)


## Concrete Steps

All commands are run from the repository root unless stated otherwise.

1) Set up environment and install dependencies

- If you don’t already have a venv:

      $ python -m venv .venv
      $ source .venv/bin/activate
      $ python -m pip install --upgrade pip

- Install the project editable. Use your repo’s established extras pattern; if none exists, start with plain editable install:

      $ python -m pip install -e .

- Install the new bench acceleration extra (after you add it):

      $ python -m pip install -e '.[benchaccel]'

2) Baseline capture (before code changes)

- Run the smallest canonical-text eval you can and record output location + timing fields.
- Run it a second time and confirm deterministic identical outputs.

3) Implement selector module

- Create `cookimport/bench/sequence_matcher_select.py` with the selection logic and env var contract described above.
- Add minimal documentation to `cookimport/bench/CONVENTIONS.md`.

4) Wire canonical evaluator

- Edit `cookimport/bench/eval_canonical_text.py` to use the selector’s matcher.
- Add telemetry keys for implementation metadata.

5) Add tests

- Add parity tests for `SequenceMatcher` outputs.
- Add end-to-end canonical alignment regression test.

6) Validate

- Run unit tests:

      $ pytest -q

- Run the canonical eval A/B comparison:

      $ COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib cookimport labelstudio-benchmark ...
      $ COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=auto   cookimport labelstudio-benchmark ...
      $ diff -u <stdlib_report> <auto_report>

- Confirm timing improvement in the report telemetry.

7) Capture evidence

- Paste minimal proof snippets into `Artifacts and Notes` and update `Progress` with timestamps.


## Validation and Acceptance

This work is accepted when all of the following are true:

- Correctness:
  - The canonical alignment produces identical outputs when using stdlib vs accelerated SequenceMatcher on the same inputs.
  - Parity tests show that the SequenceMatcher methods actually used in canonical alignment return identical results (opcodes and/or matching blocks, as appropriate).

- Observability:
  - Canonical eval artifacts include telemetry stating which SequenceMatcher implementation/version was used and whether it was forced or auto-selected.

- Performance (no hard numeric target, but must be “clearly faster”):
  - On at least one representative canonical-text evaluation run, the SequenceMatcher subphase time is lower with acceleration enabled than with stdlib forced, with the same outputs.

- Safety:
  - If the accelerated dependency is not installed, canonical evaluation still works using stdlib, and telemetry reflects the fallback.


## Idempotence and Recovery

- All changes should be safe to apply and re-run repeatedly:
  - Installing extras is idempotent.
  - Running tests is idempotent.
  - Running the same canonical eval multiple times should be deterministic (same outputs for same inputs).

- Recovery/rollback options:
  - Force stdlib SequenceMatcher at runtime by setting:

        COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib

    This should restore prior behavior even after code changes, and is the first-line mitigation if any parity issue is discovered.

  - If dependency installation fails on a platform, do not block:
    - The selector should fall back to stdlib when in `auto` mode.
    - Only the `cydifflib`/`cdifflib` forced modes should error.

  - If a regression is found:
    - revert the wiring change in `eval_canonical_text.py` and keep the selector module/tests as a preparatory step, or
    - keep wiring but default the selector to stdlib until the discrepancy is resolved.


## Artifacts and Notes

(As you implement, paste small, high-signal artifacts here.)

- Baseline canonical eval command + timing summary:
  Evidence: …

- Post-change canonical eval command + timing summary:
  Evidence: …

- Output equality proof (diff/snippet):
  Evidence: …

- Telemetry snippet showing implementation selection:
  Evidence: …


## Interfaces and Dependencies

New environment variables:

- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`
  - `auto` (default): prefer `cydifflib`, else `cdifflib`, else stdlib
  - `stdlib`: force `difflib.SequenceMatcher`
  - `cydifflib`: force `cydifflib.SequenceMatcher` (error if unavailable)
  - `cdifflib`: force `cdifflib.CSequenceMatcher` (error if unavailable)

New module:

- `cookimport/bench/sequence_matcher_select.py`
  - `SequenceMatcherSelection` (dataclass or equivalent)
  - `select_sequence_matcher()`
  - `get_sequence_matcher_selection()` (cached)
  - `SequenceMatcher(...)` convenience constructor (passes args through unchanged)

Modified module:

- `cookimport/bench/eval_canonical_text.py`
  - Replace direct `difflib.SequenceMatcher` use with `cookimport.bench.sequence_matcher_select.SequenceMatcher`.
  - Add rich telemetry keys recording selection metadata.

Dependencies:

- Add an optional extra (preferred) for benchmark acceleration:
  - Primary: `cydifflib` (drop-in difflib algorithms implementation)
  - Optional secondary: `cdifflib` (C implementation of SequenceMatcher; keep as optional fallback)

Tests:

- `tests/bench/test_sequence_matcher_dropin_parity.py`
- `tests/bench/test_canonical_alignment_regression.py` (or fold into an existing canonical eval test file)


---

Plan change notes:

- 2026-02-27: Initial version drafted. Scoped strictly to “drop-in SequenceMatcher acceleration” with no algorithmic/accuracy changes.
::contentReference[oaicite:0]{index=0}