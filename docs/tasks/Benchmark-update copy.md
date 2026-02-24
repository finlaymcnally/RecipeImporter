---
summary: "ExecPlan draft for practical-vs-strict benchmark score reporting improvements."
read_when:
  - "When reviewing historical benchmark metric-overhaul planning details"
---

# ExecPlan: Make benchmark scores match real cookbook output quality


## Why this work matters


Right now, `cookimport`’s freeform benchmark can report “terrible” headline scores (often `0.000`) even when a real import into the cooking website looks reasonably accurate. This is confusing and makes it hard to use the benchmark as a reliable signal for “did we make the importer/parsing better?”

After this change, a benchmark run will report two clearly separated scores:

- A **Practical / Content score** that reflects “did the pipeline put the right label somewhere overlapping the right gold region?” (this correlates with “does the final recipe look usable?”).
- A **Localization score** that reflects “did the pipeline localize the label to roughly the same block/span boundaries as gold?” (this is still useful, but it is not the same thing as usable output).

The CLI summary, benchmark reports, CSV history, and dashboard will stop presenting strict localization as the only headline number. When the run is clearly suffering from a granularity mismatch (recipe-wide predictions vs block-precise gold), the UI will explicitly say so and will highlight the Practical score as the primary interpretation.


## Repository orientation for a novice


You will touch four areas:

1. Freeform evaluation logic (computes matches and writes `eval_report.json` / `eval_report.md`):
   - `cookimport/labelstudio/eval_freeform.py`

2. Benchmark orchestration (offline suite + labelstudio-benchmark use the same evaluation primitives):
   - `cookimport/bench/runner.py`
   - `cookimport/bench/report.py`
   - `cookimport/bench/packet.py` (iteration packet severity ranking)

3. Analytics history CSV (the long-term event log and what the dashboard reads first):
   - `cookimport/analytics/perf_report.py` (benchmark row appends)

4. Stats dashboard (reads CSV + eval JSON, renders the HTML dashboard):
   - `cookimport/analytics/dashboard_schema.py`
   - `cookimport/analytics/dashboard_collect.py`
   - `cookimport/analytics/dashboard_render.py`
   - tests (see below)

Relevant conceptual docs (these are already in the repo; you should read them before editing code):

- `docs/07-bench/07-bench_README.md` (what benchmark actually scores)
- `docs/06-label-studio/06-label-studio_README.md` (freeform eval and benchmark wiring)
- `docs/understandings/2026-02-23_12.53.47-pipeline-freeform-span-granularity-gap.md` (the specific root cause we are fixing in reporting)
- `docs/understandings/2026-02-23_12.31.53-freeform-eval-dedupe-block-range.md` (why gold dedupe numbers can look surprising)


## Current behavior and the real root cause


The benchmark is not scoring staged cookbook outputs (`final drafts/*.json`) directly. It scores:

- Predictions from `prediction-run/label_studio_tasks.jsonl`, converted into labeled ranges (block or line ranges).
- Gold from `exports/freeform_span_labels.jsonl`, converted into block ranges.

Matching is currently “strict” by default:

- Same label
- Compatible source identity
- Intersection-over-union (IoU / Jaccard overlap) >= `0.5`

This is a **range-localization test**, not a direct “final recipe correctness” test.

The observed failure mode (documented concretely in `pipeline-freeform-span-granularity-gap.md`) is:

- Gold spans are usually single-block ranges (width ~ 1).
- Pipeline predictions are often recipe-wide ranges (width ~ 20–70 blocks/lines).
- Even when the prediction covers the gold, the best possible IoU is roughly `1 / pred_width`, so it never reaches `0.5`.
- Strict precision/recall/F1 can be `0.000` while “any overlap” diagnostics are near 1.0, meaning the pipeline is “in the right neighborhood” but not localized.

Additionally, gold dedupe can reduce the gold count because the eval projects span annotations to block ranges and dedupes by `(source_hash, source_file, start_block_index, end_block_index)`. This is expected, but it should be explained prominently in the report to avoid confusion.


## What we will change


We will keep strict IoU scoring intact, but we will add and promote a second metric track that correlates with “does this import look good?”:

1. Add “coarse overlap” / “practical” matching:
   - A gold span is counted as matched if there exists a prediction with the same label that has any overlap at all (intersection > 0). No IoU threshold.
   - A prediction is counted as correct for precision if it overlaps any gold span with the same label (intersection > 0).
   - Compute precision/recall/F1 for this track.
   - Keep supported-label variants (whatever the current code considers “supported labels”; do not invent a new definition—reuse the existing supported-label logic).

2. Add explicit “granularity stats”:
   - Width distribution stats for gold and predictions (min, p50, p90, max, avg).
   - A boolean “granularity mismatch likely” flag with a short explanation string when:
     - strict metrics are near zero, and
     - any-overlap / coarse metrics are high, and
     - prediction widths are much larger than gold widths.

3. Update report rendering and CLI output:
   - `eval_report.md` must present Practical score first (or at minimum alongside strict with strong labeling).
   - The report must explicitly label strict metrics as “Localization (IoU>=threshold)” and practical metrics as “Content overlap (any-overlap)”.
   - When mismatch is detected, print a short explanatory block at the top saying: “This run looks good in cookbook output but scores near-zero on strict IoU because predictions are coarse ranges.”

4. Update bench aggregation + iteration packet ranking:
   - `cookimport bench run` aggregate `report.md` must include both metric tracks.
   - The iteration packet should not treat “strict IoU == 0” as an automatic catastrophic failure if Practical metrics are high; severity ranking should primarily reflect Practical misses (with strict used as a secondary signal for “boundary refinement” work).

5. Update history CSV + dashboard:
   - Extend `performance_history.csv` benchmark rows with new columns for the Practical track (and mismatch flag).
   - Dashboard should display both scores and label them clearly.
   - Dashboard schema version must be bumped and tests updated.

This approach fixes the user confusion immediately, without requiring a risky change to how pipeline tasks encode locations. If later we want strict IoU to become meaningful again, we can add a separate milestone to generate block-precise prediction spans, but that is intentionally out of scope for this “make scores match perceived quality” fix.


## Definitions in plain language


- Block: An extracted unit of text from a source file, indexed by `block_index` in the extracted archive.
- Span: A highlighted region of text (freeform annotation). Exported gold spans include offsets and “touched block indices.”
- Range: The unit the evaluator matches: `[start, end]` in block-index space (or a comparable integer coordinate space already used by the existing code).
- IoU (intersection-over-union): A number from 0 to 1 measuring how much two ranges overlap relative to their total combined size. If one range is 1 block wide and the other is 24 blocks wide, even perfect containment only yields about `1/24 ≈ 0.0417`.
- Strict localization scoring: Requires IoU >= threshold (currently `0.5` by default).
- Practical overlap scoring: Requires only that the ranges overlap at all (intersection > 0), plus label/source identity rules.


## Milestone 1: Lock in a failing example with a unit test


At the end of this milestone, a novice can run a unit test that reproduces the confusing situation:

- Strict IoU metrics are zero.
- Practical overlap metrics are high.
- The evaluator emits a “granularity mismatch likely” flag.

Work:

- Create a new test module, for example:
  - `tests/test_eval_freeform_practical_metrics.py`
- Build a minimal gold set and prediction set entirely in-memory (or via small JSON fixtures under `tests/fixtures/`), using the same internal “labeled range” structures that `eval_freeform.py` already uses.
- The synthetic case should look like:
  - Gold: three spans, each width 1, labels like `INGREDIENT_LINE` and `INSTRUCTION_LINE`.
  - Predictions: same labels, but each prediction range covers a large window (width ~ 20) that contains the gold.
  - Expected: strict matches = 0 at IoU>=0.5, practical matches = all.

Acceptance:

- From repo root, run:
    pytest -q tests/test_eval_freeform_practical_metrics.py
- The test must pass and must fail if you revert the practical metric additions.

Notes:

- Do not assert exact markdown output in this milestone; assert the computed numeric metrics and the mismatch flag from the JSON report structure (which we will add in Milestone 2).


## Milestone 2: Extend `eval_freeform.py` to compute and persist Practical metrics + mismatch detection


At the end of this milestone:

- `eval_report.json` includes both strict and practical metric tracks plus width stats and mismatch metadata.
- `eval_report.md` is rewritten to present both tracks clearly and to explain the mismatch when detected.

Work:

1. Add a new metrics structure to the eval report JSON.

   Do not break backward compatibility. Keep existing top-level fields (like `precision`, `recall`, `f1`) as they are today, and add new nested fields. A safe shape looks like:

   - Keep existing:
     - `precision`, `recall`, `f1`
     - `supported_precision`, `supported_recall` (and whatever else already exists)
     - `gold_total`, `gold_matched`, `pred_total`
     - boundary counters
     - existing “any-overlap” diagnostics if already present

   - Add new:
     - `practical_precision`, `practical_recall`, `practical_f1`
     - `supported_practical_precision`, `supported_practical_recall`, `supported_practical_f1` (if supported-label logic exists today)
     - `span_width_stats`:
       - `gold`: `{min, p50, p90, max, avg}`
       - `pred`: `{min, p50, p90, max, avg}`
     - `granularity_mismatch`:
       - `likely`: boolean
       - `reason`: short string
       - `ratio_p50_pred_to_gold`: number (helpful for debugging)

   Implementation detail: compute width stats using the same definition of width already implied by the evaluator’s overlap logic. If the evaluator treats ranges as inclusive bounds, width is `(end - start + 1)`. If it treats them as half-open, width is `(end - start)`. Do not guess—read the overlap function and use the consistent definition.

2. Implement Practical matching.

   Add a helper alongside the strict match logic, something like:

   - `ranges_overlap(a, b) -> bool` (intersection > 0)
   - Count a gold span as “matched” if any predicted span matches label/source rules and overlaps at all.
   - Count a predicted span as “correct” for precision if it overlaps any gold with same label/source rules.

   Reuse existing normalization rules for:
   - label normalization
   - “supported labels” filtering
   - source identity checks / `--force-source-match`

3. Implement mismatch detection.

   Add a pure function (easy to test) that takes:
   - strict metrics
   - practical metrics (or any-overlap diagnostics)
   - width stats

   And returns:
   - `likely` boolean
   - `reason` string

   Suggested default logic (tune once you can run on real artifacts):

   - Require:
     - `supported_practical_recall >= 0.8` (or the nearest available “same-label any-overlap recall” equivalent), and
     - `f1 <= 0.05` (strict F1 very low), and
     - `p50_pred_width >= 4 * p50_gold_width` (clear granularity gap)

   Then mark mismatch likely.

   Keep the thresholds as constants near the function and document them in code comments.

4. Rewrite `eval_report.md` rendering.

   The top of the markdown report should show:

   - Practical / Content overlap score section:
     - precision/recall/f1
     - supported-label variant
   - Strict / Localization score section:
     - precision/recall/f1 with IoU threshold called out explicitly (example label: “Strict IoU>=0.5 F1”)
   - If `granularity_mismatch.likely`, add a short paragraph explaining what it means and pointing the reader to width stats.

   Also add a short “Why gold dedupe can reduce counts” note if `gold_dedupe.removed_rows > 0`, referencing the key distinction:
   - export rows are spans
   - eval units are block ranges
   - dedupe collapses multiple spans touching the same block range

Acceptance:

- Re-run the unit test from Milestone 1; it must now also assert the new JSON fields exist and have the expected values.
- Run an end-to-end eval path on any existing local golden export (if available) to confirm `eval_report.md` is readable and no longer “looks catastrophically bad” when practical overlap is high. Example command paths (exact flags may differ; use the repo’s help output to confirm):
    cookimport labelstudio-benchmark --no-upload --gold-dir data/golden/<some_gold_dir> --source data/input/<some_source>
  Then open:
    data/golden/eval-vs-pipeline/<timestamp>/eval_report.md


## Milestone 3: Update bench aggregation and iteration packet ranking to use the right signal


At the end of this milestone, `cookimport bench run` will:

- Include both score tracks in `report.md` and `metrics.json`.
- Rank “top failures” using Practical misses (content overlap failures), not strict IoU failures, so the iteration packet is meaningful even when localization is coarse.

Work:

1. Extend the bench aggregate metrics model.

   In:
   - `cookimport/bench/runner.py`
   - `cookimport/bench/report.py`

   Ensure the per-item eval JSON is parsed to pick up the new practical fields. Preserve existing strict aggregate metrics for backward compatibility and for advanced users.

2. Update `report.md` rendering.

   The aggregate report should include:

   - Practical aggregate precision/recall/f1
   - Strict aggregate precision/recall/f1
   - A short explanation that strict is localization and practical is content overlap

   Do not bury this explanation; put it near the headline numbers.

3. Update iteration packet severity ranking.

   In:
   - `cookimport/bench/packet.py`

   Today’s severity likely over-weights strict misses. Change it so:

   - Primary severity is based on practical misses:
     - missed gold spans under practical matching
     - false positives under practical matching (optional; include if you already compute)
   - Secondary severity can include strict boundary issues, but only after content overlap is satisfied.

   Keep both signals available in the case JSON lines so advanced users can debug localization later.

Acceptance:

- Create or update a bench-focused unit/integration test (whichever exists in this repo) that runs a tiny “suite” evaluation and asserts that a “granularity mismatch but high practical overlap” case does not dominate `top_failures.md`.
- Manually run:
    cookimport bench run --suite <some_suite.json>
  and verify:
  - `report.md` shows both score tracks.
  - `iteration_packet/top_failures.md` is not “everything failed” when practical overlap is strong.


## Milestone 4: Persist the Practical metrics to CSV history and show them in the dashboard


At the end of this milestone:

- New benchmark rows appended to `performance_history.csv` include practical metrics and mismatch flag.
- `cookimport stats-dashboard` shows Practical and Strict scores for benchmark runs, clearly labeled.
- Older CSV rows remain readable (new columns are empty / None), and the dashboard does not crash.

Work:

1. Extend CSV schema for benchmark rows.

   In `cookimport/analytics/perf_report.py` (look for `append_benchmark_csv`):

   - Add columns:
     - `practical_precision`, `practical_recall`, `practical_f1`
     - `supported_practical_precision`, `supported_practical_recall`, `supported_practical_f1` (if supported variants exist)
     - `granularity_mismatch_likely` (boolean)
     - optionally `pred_width_p50`, `gold_width_p50` (only if you want the dashboard to be able to surface the ratio)

   Ensure the existing “schema migration support” continues to work:
   - old CSV missing these columns is auto-expanded during append
   - values for old rows remain blank

2. Update dashboard schema and bump schema version.

   In `cookimport/analytics/dashboard_schema.py`:

   - Increment schema version (current docs say it is `7`).
   - Extend the benchmark record type to include the new columns.

3. Update dashboard collector.

   In `cookimport/analytics/dashboard_collect.py`:

   - Prefer reading the new practical metrics from CSV rows (CSV-first contract).
   - When scanning eval JSON (fallback), read the same fields from `eval_report.json` if present.

   Ensure missing fields remain `None` and do not get treated as zero.

4. Update dashboard renderer.

   In `cookimport/analytics/dashboard_render.py`:

   - Add columns in “Recent Benchmarks” table for:
     - `Practical F1`
     - `Strict F1` (rename existing `f1` to “Strict F1” in display text)
   - If `granularity_mismatch_likely`, show a small warning tag in the benchmark row (text-only; keep it simple and robust).

5. Update and/or add tests.

   Likely places:
   - `tests/test_stats_dashboard.py` (docs explicitly call this out as a regression anchor)

   Add coverage for:
   - CSV append adds the new columns
   - dashboard collector reads them
   - renderer includes them without breaking JS escaping rules

Acceptance:

- Run:
    pytest -q
  (or at least the dashboard + perf-report related tests if the full suite is large)
- Run end-to-end locally:
    cookimport labelstudio-benchmark --no-upload ...
    cookimport stats-dashboard
  Open:
    data/output/.history/dashboard/index.html
  Verify benchmark rows show both Practical F1 and Strict F1.


## Milestone 5: Documentation updates so future users don’t fall into the same trap


At the end of this milestone, the docs explain the new split of metrics and how to interpret them.

Work:

- Update `docs/07-bench/07-bench_README.md`:
  - In the “Exact scoring surface” section, describe both strict and practical tracks.
  - Add a short “If output looks good but strict is near zero…” subsection that points to the granularity mismatch flag.

- Update `docs/07-bench/runbook.md`:
  - In “Interpret the results,” mention Practical vs Strict explicitly and recommend Practical for “does this import look usable?” interpretation.

- Update `docs/08-analytics/dashboard_readme.md`:
  - Note new benchmark columns and what they mean.

Acceptance:

- Grep the docs to confirm the phrasing is consistent and does not imply benchmark “scores final outputs directly.”
- Run the commands in the runbook and confirm file paths still match reality.


## Validation plan (end-to-end)


You should validate both the numeric logic and the “human interpretation” layer.

Numeric validation:

- Unit tests for:
  - practical matching counts
  - strict matching unchanged
  - mismatch detection triggers only under the intended conditions

Human validation:

1. Pick a known “looks good but scores bad” case (any local golden set will do; the repo may have one under `data/golden/`).
2. Run:
    cookimport labelstudio-benchmark --no-upload ...
3. Open `eval_report.md` and verify:
   - Practical score is high.
   - Strict score is low.
   - The report explicitly explains why.
4. Run:
    cookimport bench run --suite ...
   Verify aggregate report shows both tracks and the iteration packet does not treat everything as catastrophic solely because strict IoU is low.
5. Run:
    cookimport stats-dashboard
   Verify the dashboard surfaces Practical F1 clearly.

If any of these validations fail, capture a short excerpt in the “Surprises & Discoveries” section below and update thresholds/wording accordingly.


## Backward compatibility and safety


- Do not remove or rename existing JSON fields in `eval_report.json`. Add new fields.
- Keep existing strict `precision/recall/f1` values unchanged so downstream consumers remain compatible.
- CSV schema expansion must be additive. The existing migration behavior (“auto-expand missing columns during append”) should handle old CSVs.
- Dashboard schema version bump must be paired with updated renderer and tests. Ensure the inline JSON embedding still works in `file://` mode.
- Do not change default evaluation thresholding semantics (IoU>=0.5) for the strict track; only add the practical track and change presentation emphasis.


## Progress


- [ ] Milestone 1: Add unit test reproducing strict=0, practical=high scenario
- [ ] Milestone 2: Implement practical metrics + width stats + mismatch detection in `cookimport/labelstudio/eval_freeform.py`
- [ ] Milestone 2: Update `eval_report.md` rendering to present Practical vs Strict clearly
- [ ] Milestone 3: Update `cookimport bench run` aggregation to include both tracks in `report.md` and `metrics.json`
- [ ] Milestone 3: Update iteration packet ranking to use practical misses as primary severity
- [ ] Milestone 4: Extend `performance_history.csv` benchmark rows with practical metrics + mismatch flag
- [ ] Milestone 4: Bump dashboard schema version and surface Practical vs Strict metrics in UI
- [ ] Milestone 4: Update/extend tests for perf report + dashboard
- [ ] Milestone 5: Update docs (bench README, bench runbook, dashboard readme)
- [ ] Final: Run full test suite and at least one end-to-end benchmark + dashboard regeneration


## Surprises & Discoveries


Record anything you learn while implementing that changes assumptions in this plan. Include short evidence snippets (test output or report excerpts). Suggested starting entries (known before implementation):

- Strict IoU metrics can be `0.000` even when “any overlap” diagnostics are near 1.0, because predicted spans are recipe-wide while gold spans are block-precise.
- Gold dedupe removals are expected in freeform eval because exported spans are projected to block ranges and deduped by `(source_hash, source_file, start_block_index, end_block_index)`.


## Decision Log


- Decision: Keep strict IoU scoring unchanged, but add a Practical overlap metric track and change report/dashboard emphasis.
  - Reason: This resolves user confusion immediately and makes benchmark scores correlate with “usable import” without requiring risky changes to pipeline task location encoding.
- Decision: Detect and explicitly flag “granularity mismatch likely.”
  - Reason: Users need an explicit, machine-detected explanation for why strict is low but practical is high, otherwise the confusion persists.


## Outcomes & Retrospective


Fill this in once implementation is complete.

- What shipped:
  - (example) Practical overlap metrics in eval JSON/MD, bench aggregation, CSV history, and dashboard.
- What remains:
  - (example) Optional future work to generate block-precise prediction spans so strict IoU can become meaningful for pipeline scope.
- Lessons learned:
  - (example) Benchmark “headline metrics” must match the user’s mental model of what is being measured, or users will distrust the benchmark even when it is technically correct.
