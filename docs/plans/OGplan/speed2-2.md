# Speed up canonical-text alignment by reusing difflib.SequenceMatcher work (no accuracy tradeoffs)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root. :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}

## Purpose / Big Picture

Canonical-text benchmark evaluation currently spends almost all its time doing a full-book `difflib.SequenceMatcher` alignment. This is slow enough that “all-method” benchmark configs can hit watchdog timeouts when the prediction block stream does not match the golden canonical block map and evaluation falls back to expensive global alignment. :contentReference[oaicite:2]{index=2}

After this change, canonical-text evaluation should produce the exact same alignment and scoring results as today (no accuracy regressions), but run faster by avoiding repeated `SequenceMatcher` setup work and by short-circuiting trivially identical normalized-text cases. You should be able to verify it worked by running a canonical-text benchmark and observing lower `alignment_sequence_matcher_seconds` in `eval_report.json` telemetry, while metrics stay identical vs a baseline run. :contentReference[oaicite:3]{index=3}:contentReference[oaicite:4]{index=4}

## Progress

- [ ] Baseline: capture before-change canonical eval telemetry for one “fast” case (high canon_match) and one “slow” case (low canon_match), saving `eval_report.json` for both.
- [ ] Add a small, deterministic unit test that asserts cached vs non-cached `SequenceMatcher` produces identical `matching_blocks` / opcodes for representative strings.
- [ ] Implement a thread-local `SequenceMatcher` cache that pre-sets canonical `seq2` once and reuses it across multiple alignments in the same thread.
- [ ] Wire canonical evaluator global alignment to use the cached matcher (no algorithm change; still legacy global alignment).
- [ ] Add a zero-risk short-circuit: if normalized prediction text equals normalized canonical text, bypass `SequenceMatcher` and use identity mapping.
- [ ] Add lightweight telemetry fields proving whether cache/short-circuit was used (without changing existing telemetry keys).
- [ ] Run the full relevant test suite locally; ensure no diffs in canonical metrics vs baseline runs.
- [ ] Measure post-change telemetry; record delta in this plan.

## Surprises & Discoveries

- Observation: (fill as you implement)
  Evidence: (paste a short snippet of output or a file path)

## Decision Log

- Decision: Use thread-local caching (not a global shared matcher) to avoid concurrency hazards from mutating a shared `SequenceMatcher` instance.
  Rationale: `SequenceMatcher.set_seq1(...)` mutates internal state; sharing across threads risks corruption. Thread-local reuse preserves determinism and safety.
  Date/Author: 2026-02-27 / (your name)

## Outcomes & Retrospective

- (Fill in after milestone completion: what improved, what didn’t, and what you’d do next.)

## Context and Orientation

Canonical-text evaluation aligns a prediction “block text stream” against a golden set’s canonical text, then projects predicted block labels onto canonical lines for scoring. The alignment step is enforced as “legacy full-book” `SequenceMatcher` because a faster bounded strategy was deprecated due to observed accuracy risk. :contentReference[oaicite:5]{index=5}:contentReference[oaicite:6]{index=6}

Key files/modules you will touch:

- `cookimport/bench/eval_canonical_text.py` (canonical evaluator). It normalizes full prediction + canonical text and runs global `SequenceMatcher`; the report calls out `SequenceMatcher` as the dominant hotspot and cites the approximate line numbers (`:380` for the matcher and `:991` for `evaluate_canonical_text(...)`). :contentReference[oaicite:7]{index=7}:contentReference[oaicite:8]{index=8}
- Existing benchmark/eval telemetry includes alignment micro-subphases like `alignment_sequence_matcher_seconds`, plus text-size counters. We will preserve those keys and only add optional extra detail. :contentReference[oaicite:9]{index=9}

Why this work matters:

- When prediction blocks match the golden canonical block map block-for-block, eval can be cheap; when they do not, evaluator must do expensive global alignment and can take minutes or exceed watchdog timeouts. This plan targets that expensive case without changing the algorithm. :contentReference[oaicite:10]{index=10}

Definitions (plain language):

- “Normalization” here means whatever deterministic text cleanup the evaluator already does before alignment (for example collapsing some whitespace or normalizing line endings). We are not changing normalization rules in this plan; we only reuse the normalized results.
- `difflib.SequenceMatcher` compares two sequences to find matching regions. In our use, `seq1` is the normalized prediction text and `seq2` is the normalized canonical text.
- “Thread-local” means each OS thread gets its own cached object, so concurrent work in different threads does not share mutable state.

## Plan of Work

We will keep `difflib` and keep the same global alignment strategy, but reduce wasted work in two safe ways:

First, reuse the expensive “prepare `seq2`” work. `SequenceMatcher` builds internal indexes for the second sequence. In an all-method sweep, many evaluations align different predictions against the same canonical text. Instead of constructing a brand new matcher each time (re-indexing canonical text every time), we will keep a per-thread `SequenceMatcher` instance whose `seq2` is set to the canonical normalized text once, then repeatedly set `seq1` for each alignment.

Second, add an identity fast-path that is provably correct: if the normalized prediction text is exactly equal to the normalized canonical text, then the alignment mapping is the identity mapping (every character offset maps to the same offset), so we can skip `SequenceMatcher` entirely. This is “free” speed with zero accuracy risk.

We will not re-enable bounded/fast alignment strategies; those are explicitly deprecated for accuracy. :contentReference[oaicite:11]{index=11}

### Milestone 1: Baseline + safety net tests

At the end of this milestone, you will have:

- Two saved `eval_report.json` artifacts from before-change runs (one fast/high match, one slow/low match).
- A unit test that would detect any behavioral difference in cached vs non-cached `SequenceMatcher` usage.

Work:

1. Pick two configs from your existing benchmark artifacts (or re-run them) such that:
   - One has near-100% canonical block map match and completes quickly (SequenceMatcher near 0s).
   - One has very low canonical match and currently spends significant time in `alignment_sequence_matcher_seconds` (or times out unless you raise the timeout).
   The “all-method timeouts” report gives a concrete example pattern and explains why mismatch explodes runtime. :contentReference[oaicite:12]{index=12}:contentReference[oaicite:13]{index=13}

2. Run each config in canonical-text eval mode and save:
   - `eval_report.json`
   - (optional) `run_manifest.json` / benchmark history row for timing
   Record the key telemetry fields (`alignment_sequence_matcher_seconds`, `alignment_seconds`, `evaluation_seconds`) so you can compare after.

3. Add a new unit test file (preferably under an existing bench/labelstudio test module) that:
   - Constructs a canonical string `b` and two different prediction strings `a1`, `a2` with partial overlaps and differences.
   - Computes `matching_blocks` (and/or `opcodes`) with a “fresh matcher” path and with the new cached-matcher path.
   - Asserts exact equality of the results for each input pair.
   Keep strings small but include:
   - repeated characters / whitespace-like patterns
   - multi-line content
   - a case where the strings are identical (to validate identity fast-path behavior)

Where to put tests:

- Use the existing test suite structure referenced in docs (there are multiple labelstudio/bench tests already). For example, `tests/labelstudio/test_labelstudio_benchmark_helpers.py` is a reasonable home if it already covers benchmark helpers; otherwise create `tests/bench/test_seqmatcher_cache.py`. :contentReference[oaicite:14]{index=14}

### Milestone 2: Implement thread-local cached SequenceMatcher for canonical seq2

At the end of this milestone, you will have:

- A small helper module that returns a `SequenceMatcher` instance pre-seeded with `seq2` (canonical normalized text) and safe to use concurrently across threads (because it is thread-local).

Work:

1. Create a new helper module, for example:

- `cookimport/bench/seqmatcher_cache.py`

2. Implement a minimal API in that module:

- `get_threadlocal_seqmatcher_for_seq2(seq2: str, *, isjunk=None, autojunk: bool = <current default>) -> difflib.SequenceMatcher`

Design requirements:

- Use `threading.local()` to store a dictionary mapping a cache key to a `SequenceMatcher`.
- The cache key must include:
  - a stable identifier for `seq2` (use a SHA256 of the string, or if the project already computes text hashes, reuse that)
  - the `autojunk` value
  - whether `isjunk` is set (if you use a non-None function, you need a stable key; simplest is to only cache when `isjunk is None`, otherwise fall back to fresh matcher).
- When creating a new matcher:
  - create the matcher with `seq1=""` (or an empty list) and `seq2=seq2`
  - ensure it matches the current evaluator’s construction parameters exactly (do not change autojunk or junk rules in this plan)
- When reusing:
  - call `matcher.set_seq1(seq1)` before computing matches
  - after computing, clear `seq1` to avoid holding a reference to the (potentially huge) prediction string longer than necessary:
    - `matcher.set_seq1("")`
    This keeps memory stable across many alignments.

3. Add a small function to opt-out or clear cache (useful in tests):

- `clear_seqmatcher_cache_for_tests()` or a `clear_all_threadlocal_seqmatchers()` function guarded to be used only in tests.

### Milestone 3: Wire cached matcher into canonical evaluator + identity short-circuit

At the end of this milestone, you will have:

- Canonical evaluator still performing legacy full-book alignment, but now using the cached matcher path and skipping alignment when normalized texts are identical.
- Telemetry (existing and new) proving the optimization was engaged.

Work:

1. In `cookimport/bench/eval_canonical_text.py`, locate the global alignment code path:

- Search for `SequenceMatcher` and confirm it is the full-book legacy alignment branch (the repo docs call out the approximate location and that fast alignment is forced to legacy). :contentReference[oaicite:15]{index=15}

2. Add an identity short-circuit immediately after you have both normalized strings:

- If `prediction_normalized == canonical_normalized`:
  - record telemetry like `alignment_strategy="legacy_identity"` (or add a boolean `alignment_identity_short_circuit=True`)
  - skip `SequenceMatcher` timing entirely (or set it to `0.0`)
  - produce the same downstream alignment outputs that the rest of the evaluator expects.
    The safest approach is:
    - create a single “matching block” that covers the full length (plus the standard sentinel block if the code expects it), and then reuse the existing block-mapping logic.
    - OR, if the mapping code accepts an “offset mapping function”, pass identity functions.
  The important constraint: do not change downstream scoring behavior; only change how the mapping is derived.

3. Replace “construct a new `SequenceMatcher` each time” with:

- `matcher = get_threadlocal_seqmatcher_for_seq2(canonical_normalized, ...)`
- `matcher.set_seq1(prediction_normalized)`
- compute whatever the evaluator currently uses (`get_matching_blocks()` / `get_opcodes()`)
- `matcher.set_seq1("")` to release the prediction reference

4. Telemetry:

The evaluator already emits alignment micro-subphases including `alignment_sequence_matcher_seconds`. Preserve the existing timers, but add 1–2 new low-noise fields under `evaluation_telemetry` so you can prove reuse:

- `alignment_seqmatcher_used_threadlocal_cache: true|false`
- `alignment_seqmatcher_seq2_cache_key: "<short hash prefix>"` (optional; useful for debugging)
- `alignment_seqmatcher_identity_short_circuit: true|false`

Keep new fields nested under `evaluation_telemetry` so you do not disrupt any flattened checkpoint contracts unless you explicitly need it. :contentReference[oaicite:16]{index=16}

### Milestone 4: Validate correctness + measure speedup

At the end of this milestone, you will have:

- Passing tests.
- No metric diffs vs baseline for the two chosen benchmark runs.
- Measurable improvement in `alignment_sequence_matcher_seconds` for the slow/low-match case (and no regression in the fast/high-match case).

Work:

1. Run tests.

From the docs snapshot, there are established marker groups; a good starting point is:

  - `pytest -m "labelstudio or bench or staging"`

If your repo uses a different standard test command, run that instead, but keep this plan updated with the actual command and the before/after pass counts. :contentReference[oaicite:17]{index=17}

2. Re-run the same two benchmark configs you used for baseline (same inputs, same gold, same knobs). For each run, save:

- `eval_report.json`
- any aggregate report if produced

3. Compare results:

- Confirm the final metrics are identical (or within a tolerance only if the metrics include floats derived from time; ideally they should be identical).
- Confirm `eval_report.json` includes the new telemetry booleans and they behave as expected:
  - identity case hits short-circuit when applicable
  - mismatched case uses cached matcher (unless you discover evaluation runs in fresh processes every time; if so, cache reuse may be limited, and you should record that discovery)

4. Measure speed:

- Compare `alignment_sequence_matcher_seconds` before vs after for the slow case.
- Record the delta in this plan under `Surprises & Discoveries` with file paths to the two `eval_report.json` files.

## Concrete Steps

All commands below assume you are at the repository root.

1. Locate the alignment hotspot.

   - `rg -n "SequenceMatcher" cookimport/bench/eval_canonical_text.py`
   - Open the surrounding code and identify:
     - where prediction text is normalized
     - where canonical text is normalized
     - where the matcher is constructed and invoked

2. Add the cache helper module.

   - Create `cookimport/bench/seqmatcher_cache.py`
   - Implement `get_threadlocal_seqmatcher_for_seq2(...)` and a test-only clear function.

3. Add the unit test.

   - Add `tests/bench/test_seqmatcher_cache.py` (or place in an existing bench helper test file).
   - Run:

     pytest -q tests/bench/test_seqmatcher_cache.py

   Expected output (example):

     1 passed in 0.12s

4. Wire it into the evaluator.

   - Modify `cookimport/bench/eval_canonical_text.py`:
     - import the helper
     - add identity short-circuit
     - replace fresh matcher construction with cached matcher usage
     - add telemetry fields under `evaluation_telemetry`

5. Run the relevant suite:

     pytest -m "labelstudio or bench or staging"

   Expected output pattern:

     ... passed, ... warnings

6. Baseline + after-run comparisons.

   - Run your chosen canonical-text benchmarks (exact command depends on how you currently reproduce the two cases; keep the commands you used in this plan).
   - Diff the resulting `eval_report.json` files:
     - metrics blocks should match
     - timing blocks should show reduced `alignment_sequence_matcher_seconds` for the slow case

## Validation and Acceptance

This work is accepted when all of the following are true:

1. Correctness:

- Canonical-text evaluation still enforces legacy full-book alignment (no bounded/fast alignment toggles reintroduced). :contentReference[oaicite:18]{index=18}
- For the two chosen benchmark cases, metrics are identical vs baseline (same gold + same predictions).
- The new unit test demonstrates cached vs non-cached `SequenceMatcher` produces identical matching results for representative strings.

2. Performance:

- For at least one slow/low canon_match case (where eval previously spent significant time in `SequenceMatcher`), `alignment_sequence_matcher_seconds` decreases.
  The project evidence already shows that canonical-text timing is dominated by `SequenceMatcher`, so improving this phase should translate to lower wall time. :contentReference[oaicite:19]{index=19}:contentReference[oaicite:20]{index=20}
- No meaningful regression for high canon_match cases (which should remain fast and often already skip SequenceMatcher in practice). :contentReference[oaicite:21]{index=21}

3. Observability:

- `eval_report.json` contains a clear boolean (or strategy string) indicating whether:
  - thread-local cache was used
  - identity short-circuit was used
  This makes it obvious to future readers why runtime changed without digging through profiling.

## Idempotence and Recovery

- The cache is purely in-memory and thread-local. Re-running benchmarks or tests should not require cleanup; each fresh process starts with an empty cache.
- If any issue is discovered (incorrect metrics, flaky tests, or suspicious alignment diagnostics), the safe rollback is to:
  - keep the new helper module and tests,
  - switch the evaluator back to constructing a fresh `SequenceMatcher` each time (one small revert),
  - then iterate on the cache code behind the test harness until it is proven identical.
- If memory usage increases unexpectedly, the first mitigation is to ensure `matcher.set_seq1("")` is executed in a `finally:` block so large prediction strings are not retained after alignment.

## Artifacts and Notes

Keep these paths updated as you work:

- Baseline fast case `eval_report.json`: (path)
- Baseline slow case `eval_report.json`: (path)
- After-change fast case `eval_report.json`: (path)
- After-change slow case `eval_report.json`: (path)

When recording evidence, paste only the small relevant excerpts, for example:

- `evaluation_telemetry.alignment_sequence_matcher_seconds`
- `evaluation_telemetry.alignment_seqmatcher_used_threadlocal_cache`
- `evaluation_telemetry.alignment_seqmatcher_identity_short_circuit`

## Interfaces and Dependencies

- No new third-party dependencies are introduced. This plan uses Python stdlib (`difflib`, `threading`, `hashlib`) only.
- Public CLI behavior must not change. Only evaluation runtime/telemetry should change.
- The alignment algorithm must remain “legacy global alignment” to respect the project’s accuracy-first stance and the documented deprecation of bounded alignment. :contentReference[oaicite:22]{index=22}