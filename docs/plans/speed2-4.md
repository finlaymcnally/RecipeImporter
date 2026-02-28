# Speed up canonical-text evaluation by replacing difflib.SequenceMatcher with an equivalent MultiLayer matcher

This ExecPlan is a living document. The sections `Progres:contentReference[oaicite:4]{index=4}etrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repository root. This ExecPlan must be maintained in accordance with `PLANS.md` (format, self-containment, and the required living-document sections).


## Purpose / Big Picture

Canonical-text benchmarking currently spends most of its time aligning the full prediction text stream to the canonical gold text using stdlib `difflib.SequenceMatcher`. This alignment can take minutes and, in mismatch cases, can exceed the all-method watchdog timeout. After this change, canonical-text evaluation will still run the same “legacy global alignment” (so accuracy is not reduced), but it will do so with a faster drop-in implementation of SequenceMatcher’s hierarchical longest-common-substring matching.

You will know it is working when:

1) Running canonical-text evaluation on a previously slow source/config produces the same scores and diagnostic outputs as before (or byte-for-byte identical `opcodes`/matching-blocks if you enable verification), and

2) The eval report’s alignment timers show a large reduction in `alignment_sequence_matcher_seconds`, with fewer (ideally zero) 900s timeouts in all-method runs.


## Progress

- [x] (2026-02-27) Updated ExecPlan to incorporate the 2026 MultiLayer SequenceMatcher speedup approach while preserving legacy alignment semantics.
- [ ] Implement `cookimport/bench/seqmatch_multilayer.py` (MultiLayer matcher core).
- [ ] Add parity tests comparing MultiLayer vs stdlib `difflib.SequenceMatcher` (`get_matching_blocks` and `get_opcodes`).
- [ ] Wire MultiLayer matcher into `cookimport/bench/eval_canonical_text.py` behind a new, explicit runtime switch.
- [ ] Add “verify mode” (run both matchers on the same inputs; assert identical; fallback safely).
- [ ] Run targeted canonical-text benchmarks on known-slow configs and record before/after timing + correctness evidence.
- [ ] Decide default rollout policy (keep difflib default vs switch default to multilayer) and document the decision.
- [ ] (Optional) Evaluate a compiled drop-in (`cdifflib`) as a contingency plan if MultiLayer is too risky.


## Surprises & Discoveries

- Observation: Canonical-text evaluation cost is dominated by alignment, and alignment is dominated by global SequenceMatcher in slow runs.
  Evidence: Slow canonical-text runs report alignment ≈ evaluation, and SequenceMatcher ≈ alignment in telemetry in Feb 25–26 benchmarking.

- Observation: All-method “failures” can be watchdog timeouts during evaluation (not conversion), especially when prediction blockization differs from the golden set’s canonical blockization (low `canon_match`).
  Evidence: Scheduler events show `evaluate_started` without `evaluate_finished`, and mismatch configs have very low canonical block map match.

- Observation: A 2026 proposal in the Python community shows a way to compute the same hierarchical longest-common-substring matching blocks as SequenceMatcher, but much faster in worst cases by reducing repeated recursion work.
  Evidence: The approach is “MultiLayer” (collect many maximal matches per DP pass, then layer/trim them into an identical hierarchical result).


## Decision Log

- Decision: Keep “legacy global alignment” behavior and do not re-enable bounded/heuristic alignment strategies.
  Rationale: The project explicitly deprecated “fast bounded alignment” due to accuracy risk; this work targets performance without changing correctness semantics.
  Date/Author: 2026-02-27 / assistant

- Decision: Implement a drop-in replacement that is validated against `difflib.SequenceMatcher` as the ground-truth oracle.
  Rationale: The user requirement is “faster but not less accurate.” The safest definition of “not less accurate” here is “identical match blocks/opcodes to difflib on the same inputs.”
  Date/Author: 2026-02-27 / assistant

- Decision: Gate the new matcher behind an explicit runtime switch and add a “verify mode” with safe fallback.
  Rationale: This reduces rollout risk and gives fast diagnosis if an edge case differs from difflib.
  Date/Author: 2026-02-27 / assistant

- Decision: Start with a parity-first implementation that targets the specific API the evaluator uses (`get_matching_blocks` and/or `get_opcodes`), rather than fully re-implementing every SequenceMatcher method.
  Rationale: Smaller surface area reduces bug risk and focuses work on what affects benchmark scoring.
  Date/Author: 2026-02-27 / assistant


## Outcomes & Retrospective

(TBD — update after each milestone with what improved, what stayed risky, and whether defaults changed.)


## Context and Orientation

This section explains the current system as if you are new to the repo.

Canonical-text evaluation exists so that different extractors/preprocessors can be scored against a shared “freeform” golden set. The evaluator does not assume the predicted block boundaries match the golden blocks. Instead it aligns the prediction text stream to the canonical gold text, then “projects” predicted block labels onto canonical gold lines, then computes metrics.

Key files and concepts (repo-relative paths):

- `cookimport/bench/eval_canonical_text.py`:
  This is the canonical-text evaluator. It normalizes the full prediction text and the full canonical text, then runs a global alignment using stdlib `difflib.SequenceMatcher`. This alignment is currently the primary runtime bottleneck in slow sources.

- “Alignment”:
  In this context, alignment means: produce a mapping between positions in the prediction’s normalized text and positions in the canonical gold normalized text. SequenceMatcher provides this via “matching blocks” and “opcodes.”

- “Matching block”:
  A tuple (i, j, n) meaning: `a[i:i+n] == b[j:j+n]` and those substrings are part of a hierarchical matching decomposition (find the leftmost-longest match, then recurse on left/right gaps). `difflib.SequenceMatcher.get_matching_blocks()` returns a list of these blocks plus a trailing sentinel `(len(a), len(b), 0)`.

- “Opcode”:
  A tuple (tag, i1, i2, j1, j2) describing how to transform `a[i1:i2]` into `b[j1:j2]`, where tag is one of `replace`, `delete`, `insert`, `equal`. These come from `SequenceMatcher.get_opcodes()` and are typically what consumers use for alignment.

- “Legacy global alignment”:
  The repository’s policy is to enforce the global SequenceMatcher-based alignment for canonical scoring correctness; bounded/heuristic “fast” alignment is treated as deprecated due to accuracy risk. This plan does not change that policy; it replaces the internal implementation of the same algorithmic output.

Why it’s slow:

`difflib.SequenceMatcher` finds the leftmost-longest common substring (contiguous match) and then recursively repeats on the left and right regions. In worst cases (especially small alphabets with repeated characters), it can end up doing expensive dynamic-programming work repeatedly across many recursion levels.

What “MultiLayer” means here:

Instead of doing one DP pass per recursion node (which multiplies total cost), MultiLayer collects many maximal matches in a single DP sweep, groups them by length, and then “layers” them from longest to shortest into a final ordered, non-overlapping hierarchical result. When overlaps occur, it trims and requeues the leftover segments into shorter-length buckets. With a memory cap, it can drop very short matches during the pass and then recurse only on remaining gaps. The key requirement for this repo is that the final blocks/opcodes must match difflib’s output exactly for the same inputs.


## Plan of Work

### Milestone 1: Confirm the exact SequenceMatcher contract used by canonical evaluation

At the end of this milestone you will know exactly which SequenceMatcher outputs the evaluator depends on, and you will have a minimal harness to reproduce a “slow alignment” input pair.

Work:

1) In `cookimport/bench/eval_canonical_text.py`, locate the place where the global SequenceMatcher is created (search for `SequenceMatcher` or `difflib`).
2) Confirm:
   - whether the evaluator calls `get_opcodes()` or `get_matching_blocks()` (or both),
   - whether it passes `autojunk=False` explicitly,
   - whether it uses `isjunk` (it likely does not; confirm).
3) Add a small, opt-in debug switch (environment variable) that, when set, writes the normalized prediction and canonical strings (or a safe truncated sample plus hashes and lengths) into a sidecar file under the eval output directory. This is only for development and must be off by default.

Result:

You can run a single canonical-text eval and capture an input pair for local benchmarking and parity testing.

Acceptance:

- A dev can set an env var and obtain the exact normalized `a` and `b` strings used by alignment (or a reproducible representation).


### Milestone 2: Implement a MultiLayer SequenceMatcher drop-in (parity-first)

At the end of this milestone you will have a module that can take two sequences (strings) and produce matching blocks and/or opcodes that match difflib’s output on the same inputs.

Work:

1) Create a new file: `cookimport/bench/seqmatch_multilayer.py`.

2) In that file, implement a class named `MultiLayerSequenceMatcher`. Keep its public surface minimal and focused on what the evaluator uses:
   - `__init__(self, isjunk=None, a="", b="", autojunk=True)`
   - `set_seqs(self, a, b)` (and/or `set_seq1`, `set_seq2`)
   - `get_matching_blocks(self)`
   - `get_opcodes(self)`

3) Implement the same “setup” behavior difflib uses:
   - Build a mapping from each element in `b` to the list of positions where it occurs.
   - If `isjunk` is provided, treat those elements as junk and exclude them from the mapping used by the DP core.
   - If `autojunk=True` and `len(b) >= 200`, compute the “popular” threshold and exclude popular elements from the DP mapping (but keep track of which elements were excluded so extension rules can match difflib behavior).

4) Implement the MultiLayer DP sweep to collect maximal matches:
   - Maintain `j2len` as a mapping from `j` to the length of the current match ending at `a[i-1]` and `b[j-1]`.
   - For each index `i` in `a`, compute `newj2len` by iterating all `j` in `pos2[a[i]]` and setting `newj2len[j] = j2len.get(j-1, 0) + 1`.
   - Any `j` present in `j2len` but absent in `newj2len` corresponds to a maximal match ending at `i-1`; record its endpoint (i_end, j_end, length).
   - Group recorded matches by `length` in a dict: `length -> list[(i_end, j_end)]`.

5) Add a memory cap mechanism:
   - The number of maximal matches can explode. Enforce a cap such as `cap = (len(a) + len(b)) * mem_mult`, where `mem_mult` is a small integer or fraction controlled by an env var (default conservative).
   - If recording a match would exceed the cap, drop the smallest-length bucket(s) first (and remember the cutoff length you dropped to).
   - Record that pruning occurred so that you can later recurse into gaps if needed.

6) Implement the “layering” phase to convert unordered endpoint matches into difflib-equivalent hierarchical blocks:
   - Process lengths from longest to shortest.
   - For each candidate match, convert (i_end, j_end, length) into (i_start, j_start, length).
   - Insert it into a growing list of accepted blocks in a way that preserves:
     - non-overlap in both `a` and `b`,
     - leftmost-longest tie-breaking,
     - and the same recursion-implied ordering difflib produces.
   - If a candidate overlaps an accepted block, trim it into up to two residual matches that fit into the open gaps (left and/or right), and requeue the residuals under their new shorter lengths.

7) If pruning occurred in step (5), compute the gaps between accepted blocks and recurse only on those gaps to discover shorter matches that were dropped. Merge the gap results and re-run the “merge adjacent blocks” logic that difflib uses (adjacent blocks where i and j touch get combined).

8) Implement `get_opcodes()` by translating matching blocks into opcodes exactly like difflib:
   - Walk blocks in order and emit `replace/delete/insert/equal` to cover full spans.
   - Ensure you include the trailing sentinel block and that opcodes cover the entire input ranges.

Result:

A new matcher exists that can be used as a replacement for difflib for canonical-text alignment, while being validated against difflib output.

Acceptance:

- For a representative set of inputs, `MultiLayerSequenceMatcher(...).get_opcodes()` equals `difflib.SequenceMatcher(...).get_opcodes()` exactly.
- For those same inputs, `get_matching_blocks()` matches exactly (including sentinel and block merging semantics).


### Milestone 3: Add a thorough parity test suite (correctness is the feature)

At the end of this milestone you have automated tests that fail if MultiLayer deviates from difflib output.

Work:

1) Add a new test file, for example: `tests/test_seqmatch_multilayer_parity.py`.

2) Create a helper that compares difflib vs MultiLayer on:
   - random strings (fixed seed),
   - structured repeats (e.g. lots of whitespace, lots of repeated “a” blocks),
   - “block shuffle” patterns (concatenate blocks then shuffle them),
   - small and medium lengths (so tests remain fast).

3) Test across relevant settings:
   - `autojunk=True` and `autojunk=False` (because difflib behavior differs),
   - `isjunk=None` (likely your canonical evaluator), and optionally one junk function that marks whitespace as junk (to validate correctness under junk semantics even if not used in prod).

4) Add at least one regression fixture derived from a real canonical-text run:
   - Use the Milestone 1 capture hook to save a normalized (a, b) pair for a previously slow config (or a truncated but still challenging segment).
   - Store it as a compressed fixture (e.g., gzip) in `tests/fixtures/` so tests can load it without huge repo bloat.

Result:

CI (or local `pytest`) protects correctness and makes performance work safe.

Acceptance:

- `pytest` passes with the new parity tests.
- The parity tests would fail if MultiLayer changed tie-breaking, merging behavior, or opcode coverage.


### Milestone 4: Wire MultiLayer into canonical-text evaluation behind an explicit switch

At the end of this milestone, you can run canonical-text evaluation using either difflib or MultiLayer, without changing the default behavior until you are ready.

Work:

1) In `cookimport/bench/eval_canonical_text.py`, introduce a new configuration knob, controlled by an environment variable:

   - Name: `COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL`
   - Values:
     - `difflib` (default)
     - `multilayer`

2) Add a second env var for verification:

   - Name: `COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_VERIFY`
   - Values:
     - unset/0: no verification
     - 1: run both implementations on the same inputs, assert identical, then proceed using the selected impl; if mismatch, log loudly and fall back to difflib to preserve correctness.

3) Update eval telemetry / report output so it is obvious which matcher ran:
   - Add fields such as:
     - `alignment_sequence_matcher_impl`: `difflib` or `multilayer`
     - `alignment_sequence_matcher_verify`: bool
     - optional: `alignment_sequence_matcher_mem_mult`: numeric if you make memory tunable

4) Keep the broader “alignment strategy” as legacy global alignment; only swap the matcher implementation under the hood.

Result:

Users can opt in to MultiLayer for speed while retaining a safe fallback.

Acceptance:

- Running canonical-text eval with the env var set produces a report that indicates the new matcher ran.
- Setting verify mode does not change outputs; it only adds a correctness check and (if needed) safe fallback.


### Milestone 5: Benchmark and decide rollout policy

At the end of this milestone you have concrete evidence of performance improvement on the slowest cases, and a clear decision on whether to switch defaults.

Work:

1) Choose 2–3 representative “slow alignment” sources/configs:
   - One that is slow but eventually succeeds (e.g., ~600s eval before).
   - One that used to time out at 900s in all-method.
   - One “fast alignment” case with 100% canonical block match (should remain fast; MultiLayer shouldn’t regress).

2) Run canonical-text evaluation with:
   - baseline difflib
   - multilayer (verify mode on initially, then off once stable)

3) Record:
   - total eval time
   - `alignment_sequence_matcher_seconds`
   - peak RSS if you have it
   - whether outputs match (hash eval_report.json, compare metrics and diagnostics)

4) If performance improves materially and correctness holds, decide whether:
   - default remains difflib with opt-in multilayer, or
   - default becomes multilayer with difflib fallback still available.

Result:

You can show that the program is faster in the exact place it used to time out, without reducing accuracy.

Acceptance:

- On at least one previously timing-out config, canonical-text evaluation now completes under the watchdog timeout (or under a practical threshold you choose) with unchanged metrics.
- MultiLayer either becomes default or remains opt-in with documented rationale.


### Optional contingency: Evaluate a compiled drop-in (cdifflib) if needed

If MultiLayer parity work becomes too risky or too time-consuming, a contingency is to try a compiled SequenceMatcher implementation that aims to preserve difflib semantics but run faster. This is optional and should only be pursued if it does not introduce deployment pain.

Acceptance for this branch is the same: identical `get_opcodes()` and benchmark outputs, with meaningful speedup on your real slow cases.


## Concrete Steps

All commands below assume you are at the repository root.

1) Run tests before changing anything:

    pytest

2) After implementing `MultiLayerSequenceMatcher`, run only the new parity tests while iterating:

    pytest -q tests/test_seqmatch_multilayer_parity.py

3) Run a single canonical-text benchmark in offline mode (example shape; adapt to your known-good inputs):

    COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL=difflib \
    cookimport labelstudio-benchmark --no-upload --eval-mode canonical-text <your args...>

    COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL=multilayer \
    COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_VERIFY=1 \
    cookimport labelstudio-benchmark --no-upload --eval-mode canonical-text <your args...>

4) Compare outputs:
   - Compare `eval_report.json` metrics fields.
   - Compare canonical diagnostics files (alignment_gaps, wrong_label_lines, etc.) if those are expected to remain stable.
   - Compare the telemetry section’s `alignment_sequence_matcher_seconds`.

5) Once verify mode passes repeatedly, re-run without verify to measure best-case speed:

    COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL=multilayer \
    cookimport labelstudio-benchmark --no-upload --eval-mode canonical-text <your args...>


## Validation and Acceptance

The change is accepted when all are true:

1) Correctness:
   - `pytest` passes.
   - The new parity tests demonstrate exact equality between difflib and multilayer opcodes/matching blocks on:
     - random tests (seeded),
     - structured repeat tests,
     - at least one real-world fixture captured from canonical eval.

2) Observable runtime improvement:
   - At least one previously slow canonical eval shows a clear reduction in `alignment_sequence_matcher_seconds`.
   - At least one previously watchdog-timed-out config completes under the timeout when multilayer is enabled (or at minimum progresses far enough that the timeout pattern changes and we can see it is no longer stuck in alignment).

3) Safe rollout:
   - The runtime switch exists and defaults to difflib unless you explicitly decide to flip the default.
   - Verify mode exists and can be enabled to catch regressions early.


## Idempotence and Recovery

- This plan is designed to be safe to run repeatedly. The new matcher is additive and controlled by an env var.
- If you observe any mismatch between multilayer and difflib outputs:
  - Set `COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL=difflib` to immediately restore baseline behavior.
  - Leave verify mode enabled while fixing the mismatch so the failure is reproducible.
- Avoid deleting or rewriting benchmark artifacts while debugging. Instead, re-run into a new output root so you can compare “before vs after.”


## Artifacts and Notes

Keep short evidence snippets in the repo as you go (in this ExecPlan’s future revisions):

- A tiny sample of parity-test output showing both implementations match.
- A before/after snippet from an eval report’s telemetry:

    alignment_sequence_matcher_impl: difflib
    alignment_sequence_matcher_seconds: 598.0

    alignment_sequence_matcher_impl: multilayer
    alignment_sequence_matcher_seconds: 35.2

Also record any observed memory impact (peak RSS) if it matters for your environment.


## Interfaces and Dependencies

New module to add:

- `cookimport/bench/seqmatch_multilayer.py`

Required interface (minimum):

- `class MultiLayerSequenceMatcher` with:
  - `__init__(isjunk=None, a="", b="", autojunk=True)`
  - `set_seqs(a, b)`
  - `get_matching_blocks() -> list[tuple[int,int,int]]`
  - `get_opcodes() -> list[tuple[str,int,int,int,int]]`

Integration points:

- `cookimport/bench/eval_canonical_text.py`:
  - Replace direct construction of `difflib.SequenceMatcher` with a small factory that picks difflib vs multilayer based on `COOKIMPORT_CANONICAL_SEQUENCE_MATCHER_IMPL`.

Optional dependency branch (only if needed later):

- `cdifflib` (compiled SequenceMatcher-like accelerator). Only adopt if parity checks pass and install/build burden is acceptable for this project.


## Change Note (why this plan was revised)

(2026-02-27) Updated the ExecPlan to explicitly incorporate the 2026 “MultiLayer” approach to speeding up SequenceMatcher’s hierarchical matching, including its key mechanics (collect many maximal matches in a DP sweep, layer longest-to-shortest with trimming/requeueing, and recurse only on gaps when memory-capped), and added explicit parity/verify gates so speedups cannot reduce scoring accuracy.