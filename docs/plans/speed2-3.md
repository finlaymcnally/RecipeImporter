# Switch canonical-text alignment to a faster diff/align engine without losing scoring accuracy

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS.md is checked into the repo root as `PLANS.md`. This ExecPlan must be maintained in accordance with `PLANS.md` and kept fully self-contained.

## Purpose / Big Picture

Canonical-text benchmarking is currently dominated by a slow global text alignment step implemented with Python’s standard library `difflib.SequenceMatcher`. The user-visible problem is that “all method benchmark” spends minutes per configuration (and sometimes hits watchdog timeouts) whenever the prediction blockization does not exactly match the golden canonical block map.

After this change, we will be able to run canonical-text evaluation using a selectable “alignment backend” that is implemented in compiled/native code (or otherwise faster than stdlib difflib) while preserving evaluation correctness. The outcome is observable in two ways:

1. Canonical-text runs that were previously alignment-bound complete significantly faster (especially mismatch cases).
2. Evaluation metrics and per-block scoring outputs match the legacy difflib backend (no accuracy loss), proven by regression tests and a golden evaluation comparison script.

We will NOT re-enable the previously-deprecated “fast bounded alignment strategy”. We will keep “global full-book alignment” semantics; we are only swapping the engine used to compute the alignment mapping.

## Progress

- [x] (2026-02-27) Updated ExecPlan to re-verify candidate libraries and embed their relevant behavior/parameters/licensing.
- [x] (2026-02-27) Added `dmp` matcher mode to the existing `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER` selector using `fast-diff-match-patch` via a SequenceMatcher-compatible adapter (`cookimport/bench/dmp_sequence_matcher.py`).
- [x] (2026-02-27) Added dmp runtime telemetry (`alignment_dmp_cleanup`, `alignment_dmp_checklines`, `alignment_dmp_timelimit`) and surfaced it in canonical eval reports when `dmp` is active.
- [x] (2026-02-27) Added regression coverage for dmp selector behavior, matching-block validity checks, and canonical eval stdlib-vs-dmp parity on a deterministic fixture.
- [x] (2026-02-27) Extended `scripts/bench_sequence_matcher_impl.py` to benchmark explicit mode sets (`stdlib`, `fallback`, `dmp`) and report speedup + opcode/matching-block parity vs stdlib.
- [x] (2026-02-27) Added benchmark matcher selection controls to CLI + interactive flows (`labelstudio-benchmark`, `bench run`, `bench sweep`, and interactive benchmark settings).
- [x] (2026-02-27) Updated canonical eval matcher telemetry to report effective mode (`alignment_sequence_matcher_mode`) separately from requested mode (`alignment_sequence_matcher_requested_mode`), eliminating ambiguous selector-only reporting.
- [ ] Implement an alignment-backend abstraction layer via `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND` (deferred because current runtime is already selector-based).
- [ ] Add an Edlib backend if feasible for this repo’s normalized text (alphabet length <= 256), behind an explicit opt-in knob.
- [ ] Decide (based on test + benchmark results) whether any non-difflib backend is safe to make the default; otherwise keep opt-in only.

## Surprises & Discoveries

- Observation: `google/diff-match-patch` is archived (read-only) and documents Myers diff plus pre/post cleanups; a maintained Python packaging exists, but it is not the native-speed option.
  Evidence: GitHub repo shows “archived”; algorithm section states Myers diff + cleanups.
- Observation: The fastest practical diff-match-patch option for Python is `fast-diff-match-patch` (import `fast_diff_match_patch`), which wraps a C++ implementation and releases the GIL while diffing.
  Evidence: PyPI and GitHub README state native wrapper + GIL release.
- Observation: `fast-diff-match-patch` exposes `timelimit`; if exceeded, it returns a valid diff that “might not be the best one”. For “no accuracy loss”, we must force `timelimit=0` (no limit) in canonical scoring.
  Evidence: PyPI text about timelimit.
- Observation: Edlib provides exact edit-distance alignments and can return a path as a CIGAR string, but it has an `alphabetLength <= 256` constraint (total unique symbols across query+target).
  Evidence: PyPI docs list this limitation explicitly.
- Observation: sesdiff is GPL-3.0+. If this repo is distributed, that license likely makes sesdiff unsuitable as a dependency; treat as optional/local-only experiment unless the repo owner explicitly accepts GPL.
  Evidence: PyPI metadata.
- Observation: `fast-diff-match-patch` is dramatically faster on synthetic mismatch-heavy text but does not preserve stdlib opcode or matching-block boundaries.
  Evidence: `scripts/bench_sequence_matcher_impl.py --tokens 800|1800` showed ~1900x to ~6800x faster than stdlib while reporting `opcode_parity_vs_stdlib=False` and `matching_block_parity_vs_stdlib=False`.
- Observation: despite non-parity opcodes, canonical scoring on the repo’s minimal canonical fixture remained identical between stdlib and dmp.
  Evidence: `tests/bench/test_sequence_matcher_dropin_parity.py::test_canonical_eval_stdlib_and_dmp_modes_have_equal_scoring_outputs_when_available` passes.

## Decision Log

- Decision: Introduce a new “alignment backend” selector separate from `COOKIMPORT_CANONICAL_ALIGNMENT_STRATEGY` (which is deprecated/forced to legacy in canonical scoring).
  Rationale: Avoid confusion with the deprecated “fast bounded strategy” while enabling safe experimentation with globally-aligned engines.
  Date/Author: 2026-02-27 / ChatGPT

- Decision: Define the backend interface to return `SequenceMatcher.get_matching_blocks()`-compatible triples `(a_start, b_start, length)` plus the sentinel `(len(a), len(b), 0)`.
  Rationale: This minimizes changes to canonical evaluator logic and makes it easy to build compatible outputs from multiple diff engines.
  Date/Author: 2026-02-27 / ChatGPT

- Decision: Treat sesdiff as “not in mainline” by default due to GPL licensing; only implement if the repo owner explicitly approves adding GPL dependencies.
  Rationale: License incompatibility risk is higher than the value of yet another backend.
  Date/Author: 2026-02-27 / ChatGPT

- Decision: Integrate dmp through the existing `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER` selector rather than introducing a second backend env contract.
  Rationale: Current canonical runtime, tests, and telemetry are already centered on selector implementations (`fallback|stdlib|cydifflib|cdifflib`), so adding `dmp` there avoids architecture fork and keeps observability/reporting consistent.
  Date/Author: 2026-02-27 / ChatGPT

- Decision: Keep dmp opt-in (`COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp`) and keep fallback order as `cydifflib -> cdifflib -> dmp -> stdlib`.
  Rationale: dmp is very fast but not opcode/matching-block drop-in compatible with stdlib; keeping it behind explicit opt-in (or tertiary fallback-chain behavior) preserves current parity expectations.
  Date/Author: 2026-02-27 / ChatGPT

- Decision: Expose matcher choice directly in benchmark command options and interactive benchmark settings while preserving `fallback` as the default selector mode.
  Rationale: explicit `stdlib|dmp|cydifflib|...` selection is needed for reproducible perf checks, but default behavior should stay CyDifflib-first fallback-chain behavior for safety across environments.
  Date/Author: 2026-02-27 / ChatGPT

## Outcomes & Retrospective

Partial milestone completion (2026-02-27):

- Delivered dmp integration in the active matcher-selector architecture (not the original separate-backend proposal).
- Added validation proving canonical fixture scoring parity between stdlib and forced dmp.
- Bench script evidence shows large mismatch-case speedups versus stdlib:
  - `tokens=800`: stdlib `1.137674s` mean vs dmp `0.000668s` mean (~1703x faster)
  - `tokens=1800`: stdlib `11.754282s` mean vs dmp `0.001753s` mean (~6707x faster)
- Canonical evaluator synthetic mismatch case (`evaluate_canonical_text`, legacy strategy, same fixture):
  - stdlib total `3.071774s`, alignment matcher phase `3.067203s`
  - dmp total `0.008898s`, alignment matcher phase `0.001028s`
- Remaining open work: broader parity corpus validation and any edlib path before considering default changes.

## Context and Orientation

This repository supports benchmark runs that generate predictions (blocks with extracted text) and evaluates them against gold labels.

Two evaluation modes exist:

- “stage-blocks”: compares stage block predictions to gold block labels directly (cheap evaluation).
- “canonical-text”: aligns the predicted text stream to a golden canonical text stream so that different blockizations/extractors can be compared (expensive evaluation).

Canonical-text evaluation relies on producing an alignment mapping between “prediction text” and “canonical text” so that labels/spans can be compared consistently. Today that mapping is computed by a global run of Python’s `difflib.SequenceMatcher`, which is known to be slow on large inputs and has quadratic worst-case time. The repo intentionally enforces this “legacy” alignment because a prior “fast bounded alignment” strategy caused scoring drift and was deprecated.

Key repo locations to orient yourself (all paths repo-relative):

- `cookimport/bench/eval_canonical_text.py`
  - Contains `evaluate_canonical_text(...)` and the alignment function `_align_prediction_blocks_to_canonical(...)`.
  - Search inside for where `difflib.SequenceMatcher` is constructed and where `get_matching_blocks()` or opcodes are consumed.
- `cookimport/bench/eval_stage_blocks.py`
  - Cheap stage-block evaluator (mostly accounting/metrics).
- Benchmark CLI entry points live in `cookimport/cli.py` and call canonical-text evaluation in benchmark flows.

Important conceptual terms used below:

- “Canonical text”: the gold reference text derived from a gold export, organized into a canonical block map.
- “Prediction blocks”: extracted text blocks produced by the importer/extractor configuration under test.
- “Global alignment”: aligning the full canonical text stream to the full prediction text stream (not a bounded window).
- “Matching blocks”: a list of triples `(a_start, b_start, length)` indicating an equal run of length `length` starting at offset `a_start` in canonical text `a` and offset `b_start` in prediction text `b`. This is the same shape produced by `SequenceMatcher.get_matching_blocks()`.

## Plan of Work

We will refactor canonical-text evaluation so that the alignment mapping is computed by a pluggable backend. The legacy behavior (difflib SequenceMatcher) remains the default. New backends will be opt-in via an environment variable and/or CLI option. Each backend must output matching blocks compatible with the current downstream code.

We will implement two non-difflib backends first:

1. `fast-diff-match-patch` backend (native C++ wrapper around Google diff-match-patch).
2. `edlib` backend (native C/C++ exact edit-distance alignment) if the normalized text meets Edlib’s alphabet constraint.

Both backends will be gated behind regression tests that compare evaluator outputs to the difflib backend. If any backend causes scoring drift in the regression suite, it remains “experimental” and must not be enabled by default.

### Milestone 1: Alignment backend abstraction (no behavior change)

At the end of this milestone:

- Canonical-text evaluation still uses difflib by default.
- The code path is refactored so the difflib logic lives behind a backend interface.
- Telemetry explicitly records which backend was used.

Work:

1. In `cookimport/bench/`, create a new module (suggested name: `cookimport/bench/text_alignment_backends.py`).
2. Define a simple interface (Python Protocol or ABC) that can compute matching blocks:

   - Type: `MatchingBlock = tuple[int, int, int]` or a `NamedTuple` for readability.
   - Interface method:

       def get_matching_blocks(self, a: str, b: str) -> list[MatchingBlock]:
           """Return SequenceMatcher-compatible matching blocks with the final sentinel block."""

   - Also provide:

       def name(self) -> str

3. Implement `DifflibSequenceMatcherBackend` that reproduces current behavior exactly.
   - Important: do not change `SequenceMatcher` initialization parameters unless you first confirm current settings. Preserve any use of `autojunk`, `isjunk`, and any normalization behavior exactly.
4. Add a backend factory function:

       def resolve_canonical_alignment_backend() -> TextAlignmentBackend

   It should read a new environment variable like `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND`.

   - Default must be `difflib`.
   - Supported values planned: `difflib`, `dmp`, `edlib`.
   - If a non-default backend is selected but its dependency is missing, either:
     - fall back to `difflib` AND write a loud warning into evaluator telemetry, or
     - fail fast if `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND_STRICT=1` is set.

   Choose the fallback behavior explicitly and document it in code comments and telemetry. For correctness, fallback-to-difflib is safer; for benchmarking experiments, strict-fail is clearer.

5. Refactor `cookimport/bench/eval_canonical_text.py`:
   - Find where `_align_prediction_blocks_to_canonical(...)` creates a `SequenceMatcher`.
   - Replace that with a call to the backend’s `get_matching_blocks(a, b)`.
   - Keep everything else unchanged.

6. Telemetry:
   - Add `evaluation_telemetry["alignment_backend"] = <backend.name()>`.
   - Add a backend-agnostic timer key, e.g. `evaluate_alignment_backend_seconds`.
   - Preserve any existing difflib-specific timer key (like `evaluate_alignment_sequence_matcher_seconds`) for backward compatibility when the difflib backend is active.

### Milestone 2: fast-diff-match-patch backend (native Myers diff)

At the end of this milestone:

- Setting `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND=dmp` uses fast-diff-match-patch.
- It produces matching blocks compatible with SequenceMatcher downstream logic.
- It sets parameters to avoid approximation that could change alignment decisions.

Relevant library behavior (embedded here so you do not need to read external docs to implement):

- The pip package name is `fast-diff-match-patch`.
- The import name is `fast_diff_match_patch` (this avoids collision with other diff-match-patch packages).
- The main API is `diff(a, b, ...)` which returns a list of `(op, length)` tuples by default (counts-only mode).
  - `op` is one of: `"="` (equal), `"+"` (inserted), `"-"` (deleted).
- Keyword arguments to use/consider:
  - `timelimit`: default 0. If non-zero and exceeded, it returns a valid diff that may not be the “best” diff. For “no accuracy loss”, force `timelimit=0`.
  - `checklines`: default True; intended as a speed-up heuristic for line-based text.
  - `cleanup`: one of `"Semantic"`, `"Efficiency"`, `"No"`. Cleanup post-processes the diff and can move boundaries between operations. For alignment stability, start with `"No"` and only change if regression tests prove identical results.
  - `counts_only`: default True. Keep True for performance; you only need lengths for building matching blocks.
  - The library releases the Python GIL while performing the diff; this matters later if the repo adds multi-threaded evaluation.

Implementation steps:

1. Add `fast-diff-match-patch` as a dependency using this repo’s normal dependency mechanism.
   - If the repo uses `pyproject.toml`, add it under the main dependencies.
   - If it uses `requirements.txt`, add it there.
   - If it uses `uv`/`pip-tools`, follow that workflow consistently.

2. In `cookimport/bench/text_alignment_backends.py`, implement:

   class FastDiffMatchPatchBackend(TextAlignmentBackend):
       name() -> "dmp"
       get_matching_blocks(a, b) -> list[MatchingBlock]

3. Implement `get_matching_blocks` using the diff output:

   Maintain two indices:
   - `i` = current offset in `a` (canonical text)
   - `j` = current offset in `b` (prediction text)

   For each `(op, n)`:
   - If op == "=":
     - append `(i, j, n)`
     - i += n; j += n
   - If op == "-":
     - i += n
   - If op == "+":
     - j += n

   After processing all ops, append the sentinel `(len(a), len(b), 0)`.

4. Add backend parameters with safe defaults and optional env overrides for experimentation:
   - Always default to `timelimit=0`.
   - Default `cleanup="No"` unless tests show another mode is necessary to match difflib scoring.
   - Default `checklines=True` (library default), but allow `COOKIMPORT_DMP_CHECKLINES=0` to disable if it ever correlates with scoring drift.

5. Add internal validation (fast fail) that the returned matching blocks are monotonic and in-bounds:
   - For each block `(ai, bi, n)`:
     - 0 <= ai <= len(a), 0 <= bi <= len(b), n >= 0
     - ai + n <= len(a), bi + n <= len(b)
     - blocks are non-decreasing: next_ai >= ai + n, next_bi >= bi + n (except the sentinel)
   If violated, raise an exception (or fall back to difflib in non-strict mode).

6. Update canonical eval telemetry to record:
   - `alignment_backend="dmp"`
   - `dmp_cleanup`, `dmp_checklines`, `dmp_timelimit` so benchmark artifacts show exactly what ran.

### Milestone 3: Edlib backend (exact edit-distance alignment), only if feasible

At the end of this milestone (if feasible):

- Setting `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND=edlib` uses Edlib to compute a global alignment path and then converts it to matching blocks.

Embedded Edlib behavior:

- pip package is `edlib`.
- `edlib.align(query, target, mode="NW", task="path", k=-1, additionalEqualities=None)` returns a dict including:
  - `editDistance`
  - `alphabetLength` (must be <= 256 for Edlib to work)
  - `cigar` when `task="path"` (string encoding the alignment path)
- Edlib’s “extended CIGAR” operations:
  - `=` match
  - `X` mismatch
  - `I` insertion to target
  - `D` deletion from target

Feasibility check:

- The canonical evaluator “normalizes” text before alignment. You must confirm that normalized text does not exceed Edlib’s alphabet constraint.
- Add a quick check: when building the alignment, read `alphabetLength` from the Edlib result and fail (or fall back) if it is > 256.

Implementation steps:

1. Add `edlib` dependency using repo-standard tooling.
2. Implement `EdlibBackend(TextAlignmentBackend)` in `cookimport/bench/text_alignment_backends.py`.

3. Implement matching blocks by parsing the CIGAR:

   - Call:

       result = edlib.align(a, b, mode="NW", task="path", k=-1)

   - If `result["cigar"]` is None, treat as failure (you must use `task="path"`).
   - Parse the cigar string, which is a sequence of `<count><op>` tokens (e.g. `5=1X1=1I`).
   - Maintain indices `i` (offset in a/query) and `j` (offset in b/target).
   - For each token `(n, op)`:
     - op == "=": append `(i, j, n)`; i += n; j += n
     - op == "X": i += n; j += n
     - op == "I": j += n
     - op == "D": i += n
   - Append sentinel `(len(a), len(b), 0)`.

4. Add telemetry fields:
   - `alignment_backend="edlib"`
   - `edlib_edit_distance`, `edlib_alphabet_length`

5. If `alphabetLength > 256` occurs for real benchmark inputs, do not “hack” around it in canonical scoring (such hacks usually change semantics).
   - Instead, keep Edlib backend as unavailable for that input and fall back to difflib (or fail in strict mode).

### Milestone 4: Regression tests that guarantee “no accuracy loss” (mandatory)

At the end of this milestone:

- Tests demonstrate that on a representative suite, evaluator outputs are identical between difflib and the new backend(s).
- If they are not identical, the backend cannot become default, and the drift is documented.

Testing strategy:

1. Add low-level backend tests (fast, deterministic):

   In a new test file, e.g. `cookimport/bench/tests/test_text_alignment_backends.py`:

   - Build small string pairs where alignment is unambiguous:
     - identical strings
     - pure insertion at start/middle/end
     - pure deletion at start/middle/end
     - single substitution
     - repeated patterns that can be ambiguous (e.g. `aaaaabaaaaa` vs `aaaaacaaaaa`) to detect boundary-shift behavior
   - For each backend available in the test environment:
     - Ensure matching blocks are in-bounds and monotonic.
     - Ensure that the concatenation of all matched segments are actually equal substrings in both strings (spot-check, not full reconstruction).

2. Add evaluator-level regression tests (the real “accuracy” gate):

   Goal: prove that canonical-text scoring outputs match difflib on real-ish inputs.

   Implementation approach (choose the simplest that fits this repo):

   - Option A (preferred): create a tiny synthetic “gold + prediction” fixture in test code that directly calls the internal canonical evaluator functions (not the CLI). The fixture should include:
     - a small canonical block list
     - a small prediction block list with a different blockization but identical overall text
     - a small set of gold labels/spans
     Then run `evaluate_canonical_text` twice: once with difflib backend and once with the candidate backend. Assert the resulting metrics dict is identical.

   - Option B: if the evaluator only operates on on-disk artifacts, add a minimal fixture directory under `cookimport/bench/tests/fixtures/` that mimics what `labelstudio-eval` expects, and run the evaluator on it.

   In either option, the acceptance check is:
   - overall metrics exactly equal (not “close”)
   - per-label counts identical
   - any diagnostic outputs that depend on mapping (like conflict files) match, or are explicitly excluded if they include timestamps/randomness.

3. Add a “backend drift detector” test that runs only when both backends are installed:
   - If `fast-diff-match-patch` is installed, run the evaluator test comparing difflib vs dmp.
   - If `edlib` is installed, compare difflib vs edlib.
   - If either comparison differs, fail the test with a clear diff showing which metric changed.

### Milestone 5: Benchmark harness to prove speedup and catch regressions on real data

At the end of this milestone:

- There is a repeatable way to measure alignment runtime for a known slow mismatch case.
- The harness prints both “time” and “accuracy parity” results.

Implementation:

1. Add a script, suggested path: `scripts/benchmark_canonical_alignment_backends.py`.

2. The script should:
   - Accept a prediction-run root and a gold directory (or whatever canonical-text eval needs in this repo).
   - Load the canonical and prediction texts exactly as `evaluate_canonical_text` does (reuse internal helpers, do not duplicate normalization logic).
   - Run alignment with difflib backend and print:
     - total alignment seconds
     - number of matching blocks
     - any relevant evaluator telemetry fields
   - Run alignment with the selected backend and print the same.
   - Optionally run the full evaluator and compare key metrics (recommended for safety).

3. Provide a documented “known slow” reproduction case in the script help text, based on your existing all-method benchmark artifacts:
   - When prediction blockization matches the canonical block map, eval is fast.
   - When it mismatches, alignment can dominate and hit timeouts.
   This script is meant to benchmark the mismatching scenario with a higher timeout or offline, so we can see if the backend changes eliminate the tail.

### Milestone 6: Decide whether any backend is safe to become default

Policy:

- Default remains difflib until a backend proves “no scoring drift” on:
  - the unit test suite
  - a small representative set of real sources (at least one “easy match” and one “mismatch/slow”)
- If difflib vs backend differs, the backend stays opt-in and the differences are documented.

If a backend passes parity and is significantly faster, update:
- default backend selection (optional)
- documentation/comments to explain why it is now safe
- benchmark reports/telemetry to make backend choice obvious

## Concrete Steps

All commands below assume you are at the repository root.

1. Orient yourself in the current canonical evaluator:

   - Find the alignment entry points:

       rg -n "evaluate_canonical_text|_align_prediction_blocks_to_canonical|SequenceMatcher" cookimport/bench/eval_canonical_text.py

2. Implement Milestone 1 refactor and run tests:

   - Run the unit tests (adjust to repo conventions; likely pytest):

       pytest -q

   Expectation: tests pass and canonical-text evaluation still works with difflib.

3. Install and implement fast-diff-match-patch backend:

   - Add dependency.
   - Run unit tests again:

       pytest -q

   - Run a small local benchmark eval with backend enabled (example; adjust to actual CLI flags this repo uses):

       COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND=dmp cookimport labelstudio-eval --help

   Then run a real evaluation command and inspect the eval report JSON to confirm:
   - `alignment_backend` says `dmp`
   - alignment time is reduced

4. Install and implement edlib backend (only if alphabet constraint is met):

   - Add dependency.
   - Run tests:

       pytest -q

   - Run one canonical-text evaluation with `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND=edlib` and confirm it does not fail the alphabet length check on your chosen fixture.

5. Run the benchmark harness script on a known slow mismatch case and record results in a local note.

## Validation and Acceptance

Minimum acceptance (must meet):

- Behavior: canonical-text evaluation runs successfully with:
  - default backend (difflib)
  - `dmp` backend when installed
  - `edlib` backend when installed and alphabet constraint is satisfied
- Accuracy: For the regression suite:
  - evaluator metrics are identical between difflib and the backend(s)
- Observability:
  - eval telemetry/report clearly states which backend ran and what parameters were used
- Performance:
  - On at least one mismatch/slow case, the backend completes materially faster than difflib (target: 2x+; if it turns timeouts into completions under the existing watchdog, that is a major win).

If accuracy parity is not achieved:
- The backend must remain opt-in only.
- The ExecPlan must be updated with a short explanation of the observed drift and any parameter tweaks tried (cleanup mode, checklines, etc.).

## Idempotence and Recovery

- All changes are additive and safe to re-run.
- If a backend causes failures or drift:
  - Set `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND=difflib` to return to baseline behavior.
  - If strict mode was added, unset it to allow fallback.
- Dependency rollback:
  - Remove optional dependencies from the dependency file and reinstall.
  - Ensure tests still pass with only difflib backend present.

## Artifacts and Notes

Example pseudocode (to be implemented in real code, not pasted verbatim):

  Build matching blocks from diff-match-patch ops:

    i = 0  # offset in canonical a
    j = 0  # offset in prediction b
    blocks = []
    for op, n in diff_ops:
        if op == "=":
            if n > 0:
                blocks.append((i, j, n))
            i += n; j += n
        elif op == "-":
            i += n
        elif op == "+":
            j += n
        else:
            raise ValueError("unexpected op")
    blocks.append((len(a), len(b), 0))

Example CIGAR parsing strategy for Edlib:

  Parse tokens like "12=3X5I2D" into (count, op) pairs, then walk indices i/j:
    "=" -> match (emit block), i+=n, j+=n
    "X" -> mismatch, i+=n, j+=n
    "I" -> insertion to target, j+=n
    "D" -> deletion from target, i+=n

## Interfaces and Dependencies

New module:

- `cookimport/bench/text_alignment_backends.py`

Define:

- `MatchingBlock`: a tuple or NamedTuple

  Suggested:

    from typing import NamedTuple

    class MatchingBlock(NamedTuple):
        a_start: int
        b_start: int
        length: int

- Backend interface:

    class TextAlignmentBackend(Protocol):
        def name(self) -> str: ...
        def get_matching_blocks(self, a: str, b: str) -> list[MatchingBlock]: ...

Factory:

- `resolve_canonical_alignment_backend() -> TextAlignmentBackend`
  - Reads `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND`
  - Default: difflib
  - Optional strict mode: `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND_STRICT=1`

Dependencies:

- Required (already): Python stdlib `difflib`
- Optional, recommended for performance:
  - `fast-diff-match-patch` (native C++ wrapper)
    - Must force `timelimit=0` for “no approximation”
    - Expose optional env toggles for `cleanup` and `checklines` for controlled experiments
  - `edlib` (native edit-distance alignment)
    - Only usable if `alphabetLength <= 256` for normalized text
- Not recommended as a committed dependency without explicit approval:
  - `sesdiff` (GPL-3.0+); do not add by default

--- 

Plan revision note (2026-02-27):

This ExecPlan was revised to re-check the candidate library links and embed the relevant implementation details (API shapes, speed/accuracy knobs like `timelimit`/`cleanup`, Edlib’s alphabet constraint, and sesdiff’s GPL licensing). The changes were made to ensure a novice can implement the backends without needing to consult external docs, and to ensure “no accuracy loss” is enforced by design via regression tests and strict parameter defaults.

Plan revision note (2026-02-27, implementation follow-up):

This ExecPlan was updated after implementation to reflect the repository’s current selector-based architecture. The delivered work adds a `dmp` mode to `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`, captures dmp runtime telemetry, adds regression coverage, and records benchmark evidence. The original `COOKIMPORT_CANONICAL_ALIGNMENT_BACKEND` abstraction and Edlib milestones remain documented as deferred work.
