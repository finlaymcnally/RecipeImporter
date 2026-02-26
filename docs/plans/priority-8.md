# Implement Priority 8 boundary-first evaluation (recipe segmentation eval + error taxonomy)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. 

This plan must be maintained in accordance with `docs/PLANS.md` (if the repo keeps it at root instead, use `PLANS.md`). 


## Purpose / Big Picture

After this change, you can evaluate cookbook segmentation quality as a true boundary problem (not just “did spans overlap”), by running an offline “recipe segmentation eval” that reports:

- block-label precision/recall/F1 for stage `block_roles`
- boundary precision/recall/F1 for ingredient section starts/ends, instruction section starts/ends, and multi-recipe splits
- an error taxonomy summary (“extraction failure”, “boundary errors”, “ingredient errors”, “instruction errors”, “yield/time errors”) to make regressions and debugging faster

This is explicitly Priority 8 in `BIG PICTURE UPGRADES.md`, and it is intended to plug into the existing Label Studio + offline bench scaffolding rather than replacing it. 

User-visible proof that it works:

- Running `cookimport recipe-segmentation-eval ...` produces an `eval_report.json` and `eval_report.md` that include the new boundary metrics and taxonomy sections.
- Running existing benchmark paths (`cookimport bench run` and `cookimport labelstudio-benchmark --no-upload`) continues to work and now includes the same additional segmentation metrics in their per-item `eval_report.json`. The scoring surface remains stage-block based (`stage_block_predictions.json` vs Label Studio gold). 


## Progress

- [x] (2026-02-25) Authored ExecPlan for Priority 8 boundary-first evaluation upgrade.
- [ ] Add segmentation boundary metric primitives + unit tests (no CLI changes yet).
- [ ] Extend stage-block evaluation (`cookimport/bench/eval_stage_blocks.py`) to compute and write boundary metrics + error taxonomy (additive fields only).
- [ ] Add new offline CLI command `cookimport recipe-segmentation-eval` that wraps the same evaluator on explicit `--pred/--gold` inputs.
- [ ] Add optional `segeval` backend as an additional metric option (Pk/WindowDiff/boundary similarity), without replacing the native boundary-F1 metrics. 
- [ ] Update bench docs/conventions to describe new outputs and how to interpret them.
- [ ] Run full test suite and record results; run at least one real bench item and record boundary metric excerpts as evidence.


## Surprises & Discoveries

- (none yet)


## Decision Log

- (none yet)


## Outcomes & Retrospective

Plan authored; implementation has not started yet. Expected outcome: a cookimport-native segmentation evaluation path that scores boundaries (and summarizes errors) using the existing stage-block benchmark surface, making boundary/splitting work measurable and regression-resistant. 


## Context and Orientation

Priority 8’s core observation is that recipe detection/segmentation should be scored like segmentation: boundaries and section structure, not only span overlap. The repo already has the scaffolding (Label Studio + offline bench) and label names needed; the missing piece is boundary modeling and boundary-centric metrics. 

Key terms (used precisely in this plan):

- Block: one unit of extracted text in an ordered “block stream” from an importer (EPUB/PDF/etc). Each block has a stable `block_index` in that stream.
- Label / block role: a categorical tag assigned to a block, such as `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `OTHER`. Label Studio configs and bench scoring already revolve around this vocabulary. 
- Span: a contiguous run of blocks sharing a label (for this plan, ingredient spans are maximal contiguous runs of `INGREDIENT_LINE`; instruction spans are maximal contiguous runs of `INSTRUCTION_LINE`).
- Boundary: a discrete location where a span starts or ends. In this plan, boundaries are represented by block indices:
  - span start boundary = `start_block_index` (first block of the run)
  - span end boundary = `end_block_index` (last block of the run)
- Boundary precision/recall/F1: treat gold boundaries as a set and predicted boundaries as a set; a match is an exact index match (optionally within a tolerance window, controlled by a flag). Precision = matched/predicted, recall = matched/gold, F1 = harmonic mean.

Existing evaluation and where we will extend it:

- The current “exact scoring surface” for offline benchmarking is stage-block based:
  - Predictions: `stage_block_predictions.json` (schema `stage_block_predictions.v1`) with one final label per `block_index`
  - Gold: `freeform_span_labels.jsonl`, expanded into one label per block (gold must be exhaustive and conflict-free)
  - Outputs today: `eval_report.json`, `eval_report.md`, and mismatch JSONLs such as `wrong_label_blocks.jsonl` (plus legacy aliases). 
- The core implementation for this evaluation lives in `cookimport/bench/eval_stage_blocks.py` (loaders, metrics, eval artifact writing). Bench orchestration uses `cookimport/bench/runner.py` and wiring lives in `cookimport/cli.py`. 
- Priority 8 explicitly asks to:
  1) use canonical labels as gold for block-role classification,
  2) use freeform labels to improve/score metadata extraction, and
  3) add the offline segmentation eval command with boundary metrics and taxonomy. 

Important “options, not replacements” requirement (from the user):

- This plan MUST keep existing evaluation behavior and metrics intact and add new metrics/paths as additive fields and/or selectable options.
- Any new library (notably `segeval`) must be added as an additional selectable backend/metric set, not as a replacement. `segeval` is recommended specifically because it enables standard segmentation metrics (Pk/WindowDiff/boundary similarity), which are adjacent to the Priority 8 boundary focus. 


## Plan of Work

Milestone 1 (core boundary metrics primitives): Add a small, dependency-free “segmentation metrics” module that can (a) turn label sequences into spans, (b) turn spans into boundary sets, and (c) compute boundary PRF. This milestone ends with unit tests that validate boundary extraction and PRF math on a toy example that includes multi-recipe splits.

Milestone 2 (integrate into existing stage-block evaluator): Extend `cookimport/bench/eval_stage_blocks.py` to compute and write boundary metrics and the error taxonomy. This is an additive change: existing fields remain unchanged; the new results go under a new top-level key in `eval_report.json` (for example `segmentation`). This milestone ends with running `cookimport bench run` on one suite item and showing `eval_report.md` includes the new section.

Milestone 3 (new offline CLI entrypoint): Add `cookimport recipe-segmentation-eval` as an explicit offline command that runs the same evaluator given direct file paths. This provides the Priority 8 “offline recipe segmentation eval command” without requiring a suite run. It must support both canonical and freeform gold inputs as options, and must support gold-as-spans vs gold-as-per-block labels as separate options.

Milestone 4 (optional `segeval` metrics backend): Add `segeval` as an optional dependency and wire it in as additional metrics (Pk/WindowDiff/boundary similarity) behind a flag. This milestone ends with a small integration test that asserts those keys appear in `eval_report.json` when `segeval` is installed and requested, and that the evaluator still works when `segeval` is not installed (so long as the user did not request those metrics).

Milestone 5 (docs/conventions): Update bench docs and conventions to describe boundary metrics, boundary definitions, and taxonomy, so a future contributor can interpret the numbers without reading code.


## Concrete Steps

All commands in this section are run from the repository root unless stated otherwise. 

1) Establish baseline and locate the evaluator.

    - Verify tests run (use the repo’s standard command; if unsure, start with):
        python -m pytest -q

    - Locate the stage-block evaluator and current report shape:
        rg -n "eval_stage_blocks" cookimport/bench
        rg -n "wrong_label_blocks.jsonl|eval_report.md|macro_f1_excluding_other" cookimport/bench/eval_stage_blocks.py

    Expected: you find `cookimport/bench/eval_stage_blocks.py` and it already writes `eval_report.json`/`eval_report.md` and mismatch JSONLs. 

2) Milestone 1 implementation steps (add primitives + tests).

    - Create new file:
        cookimport/bench/segmentation_metrics.py

    - Create new tests file (match existing test layout; if unsure, inspect `tests/bench/`):
        mkdir -p tests/bench
        $EDITOR tests/bench/test_segmentation_metrics.py

    - Run only the new unit tests while iterating:
        python -m pytest -q tests/bench/test_segmentation_metrics.py

3) Milestone 2 implementation steps (wire into eval_stage_blocks).

    - Edit:
        cookimport/bench/eval_stage_blocks.py

      Add a call after existing block-label metrics are computed:
      - load gold labels as an ordered list by block index
      - load predicted labels as an ordered list by block index
      - call the new segmentation metrics function to compute boundary PRF
      - append results into the eval report dict under a new key (for example `segmentation`)

    - Run a single real evaluation using the existing bench suite flow (pick a small suite item).

      First, list available suites:
        ls data/golden/bench/suites

      Then run one suite (exact flags may differ; check help):
        cookimport bench run --help
        cookimport bench run --suite data/golden/bench/suites/<suite_file> --only <item_slug_or_id>

      Expected: per-item eval directories still contain the original artifacts plus updated `eval_report.json` with a new `segmentation` section. 

4) Milestone 3 implementation steps (new command).

    - Edit CLI wiring:
        cookimport/cli.py

      Add new command:
        cookimport recipe-segmentation-eval --help

      The command should accept:
      - --pred path to stage-block predictions (JSON)
      - --gold path to gold labels (JSONL; spans or per-block)
      - --gold-scope canonical-blocks|freeform-spans (option; influences label set and projections)
      - --gold-format spans|block-labels (option; treat both as benchmarkable alternatives)
      - --label-projection core_structural_v1|canonical_full|freeform_full (option)
      - --boundary-tolerance-blocks <int> (default 0)
      - --segmentation-metrics boundary_f1[,pk,windowdiff,boundary_similarity] (default boundary_f1)
      - --out-dir <path> and --overwrite

    - Validate with a toy dataset that does not depend on any golden files:

      Create a temporary directory and write minimal pred/gold files:
        mkdir -p /tmp/cookimport_seg_eval_toy
        python - <<'PY'
        import json, pathlib
        out = pathlib.Path("/tmp/cookimport_seg_eval_toy")
        gold = [
          ("RECIPE_TITLE"),
          ("INGREDIENT_LINE"),
          ("INGREDIENT_LINE"),
          ("INGREDIENT_LINE"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
          ("OTHER"),
          ("RECIPE_TITLE"),
          ("INGREDIENT_LINE"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
        ]
        pred = [
          ("RECIPE_TITLE"),
          ("INGREDIENT_LINE"),
          ("INGREDIENT_LINE"),
          ("OTHER"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
          ("OTHER"),
          ("RECIPE_TITLE"),
          ("INSTRUCTION_LINE"),
          ("INSTRUCTION_LINE"),
          ("OTHER"),
        ]
        # pred format (stage_block_predictions.v1-style): JSON
        pred_payload = {
          "schema_version": "stage_block_predictions.v1",
          "predictions": [{"block_index": i, "label": lab} for i, lab in enumerate(pred)],
        }
        (out / "pred.json").write_text(json.dumps(pred_payload, indent=2))
        # gold format (block-labels JSONL): one row per block
        with (out / "gold_block_labels.jsonl").open("w", encoding="utf-8") as f:
          for i, lab in enumerate(gold):
            f.write(json.dumps({"block_index": i, "label": lab}) + "\n")
        print("Wrote", out)
        PY

      Run the new command:
        cookimport recipe-segmentation-eval \
          --pred /tmp/cookimport_seg_eval_toy/pred.json \
          --gold /tmp/cookimport_seg_eval_toy/gold_block_labels.jsonl \
          --gold-format block-labels \
          --label-projection core_structural_v1 \
          --boundary-tolerance-blocks 0 \
          --segmentation-metrics boundary_f1 \
          --out-dir /tmp/cookimport_seg_eval_toy/out \
          --overwrite

      Expected boundary metrics (exact match, tolerance 0) for this toy case:

      - Ingredient start: gold {1,9}, pred {1} => precision 1.0, recall 0.5, f1 0.6667
      - Ingredient end: gold {3,9}, pred {2} => precision 0.0, recall 0.0, f1 0.0
      - Instruction start: gold {4,10}, pred {4,9} => precision 0.5, recall 0.5, f1 0.5
      - Instruction end: gold {6,11}, pred {6,10} => precision 0.5, recall 0.5, f1 0.5
      - Multi-recipe split: gold {8}, pred {8} => precision 1.0, recall 1.0, f1 1.0

      Also expected: `eval_report.json` and `eval_report.md` exist under `/tmp/cookimport_seg_eval_toy/out`, and the markdown report includes an “Error taxonomy” section listing bucket counts (even if small). 

5) Milestone 4 implementation steps (optional `segeval` backend).

    - Add `segeval` as an optional dependency (not required for default behavior). The exact pyproject format varies; do this in `pyproject.toml`:

      If the repo uses PEP 621 (`[project]`), add:
        [project.optional-dependencies]
        segmentation_eval = ["segeval>=<min_version_you_tested>"]

      If the repo uses Poetry (`[tool.poetry.dependencies]`), add `segeval` as an optional dependency and expose it via an extra group.

    - Add:
        cookimport/bench/segeval_adapter.py

      and wire it so that:
      - if the user requests pk/windowdiff/boundary_similarity and `segeval` is not installed, the command errors with a clear message explaining how to install the extra
      - if `segeval` is installed, metrics appear under `eval_report.json` -> `segmentation.segeval.*`

    - Verify by installing the extra locally (exact command depends on your tooling; common patterns):
        pip install -e ".[segmentation_eval]"
      or
        poetry install -E segmentation_eval

      Then re-run the toy command with:
        --segmentation-metrics boundary_f1,pk,windowdiff,boundary_similarity

      Expected: eval report contains numeric values for those keys. `boundary_f1` must remain computed by the native implementation regardless of segeval. 

6) Milestone 5 implementation steps (docs/conventions).

    - Update the bench scoring contract docs to mention boundary metrics and where they live in `eval_report.json`. Start with:
        docs/07-bench/runbook.md
        docs/07-bench/07-bench_README.md
        cookimport/bench/CONVENTIONS.md

      (Use `rg -n "eval_report.json" docs/07-bench cookimport/bench/CONVENTIONS.md` to find the right insertion points.)

    - Add a short “how to interpret boundary metrics” paragraph:
      - boundary counts are by block index boundaries, derived from contiguous runs
      - multi-recipe split boundaries are the starts of each `RECIPE_TITLE` run after the first

      This definition must match the code so that reviewers don’t guess incorrectly.


## Validation and Acceptance

Acceptance is behavioral and must be demonstrable. 

1) Unit tests:

- Run:
    python -m pytest -q

  Expect: all tests pass.
  Also expect: the new unit test file `tests/bench/test_segmentation_metrics.py` fails before the change (module missing) and passes after.

2) New offline command:

- Run:
    cookimport recipe-segmentation-eval --help

  Expect: help text documents the new options (gold format, projection, tolerance, segmentation-metrics choices).

- Run the toy scenario from “Concrete Steps” and inspect:
    /tmp/cookimport_seg_eval_toy/out/eval_report.json
    /tmp/cookimport_seg_eval_toy/out/eval_report.md

  Expect:
  - `eval_report.json` contains a `segmentation` top-level object with:
    - boundary metrics for ingredient/instruction start/end and recipe splits
    - `boundary_tolerance_blocks` echo
    - taxonomy bucket counts for the Priority 8 buckets
  - The boundary metrics match the expected toy numbers listed in Concrete Steps.

3) Existing bench/benchmark flows remain intact:

- Pick one small suite item and run:
    cookimport bench run --suite data/golden/bench/suites/<suite> --only <item>

  Expect:
  - existing metrics in `eval_report.json` remain present and unchanged in meaning
  - a new `segmentation` section appears (additive)
  - existing mismatch artifacts (`wrong_label_blocks.jsonl`, etc.) still exist; any new boundary-specific mismatch artifacts (if added) are additional, not replacements. 

4) Optional segeval metrics (only if segeval installed):

- Install extra and run:
    cookimport recipe-segmentation-eval ... --segmentation-metrics boundary_f1,pk,windowdiff,boundary_similarity

  Expect: `eval_report.json` contains `segmentation.segeval.pk`, `segmentation.segeval.windowdiff`, and `segmentation.segeval.boundary_similarity` keys. 


## Idempotence and Recovery

- The evaluation commands are read-only with respect to inputs; they only write a new output directory. Re-running is safe.
- `cookimport recipe-segmentation-eval` must either:
  - refuse to write into an existing `--out-dir` unless `--overwrite` is provided, or
  - always create a fresh timestamped subdirectory under `--out-dir`.
  Pick one behavior and keep it consistent across reruns so repeated runs don’t silently mix artifacts.
- If any step fails midway (for example, because gold is not exhaustive), the command must exit with a clear message and no partial “success” prints; rerun is safe after fixing the input or flags.

Rollback is standard git rollback of the code changes. Since this plan is additive, rollback does not require rewriting historical artifacts.


## Artifacts and Notes

New or extended artifacts written by evaluation (additive to current outputs):

- `eval_report.json`:
  - add a new top-level section `segmentation` (do not rename existing keys)
- `eval_report.md`:
  - add a new section “Segmentation boundary metrics” and a new section “Error taxonomy”
- Optional additional mismatch artifacts (if implemented):
  - `missed_gold_boundaries.jsonl`
  - `false_positive_boundaries.jsonl`

Error taxonomy buckets that must appear in the report (exact names as below), per Priority 8:

- Extraction failure (noise removed content / kept noise)
- Boundary errors (merged recipes, split one recipe, swapped sections)
- Ingredient errors (quantity/unit/name/prep/note)
- Instruction errors (step split, step order)
- Yield/time errors (nutrition misread, wrong association) 

Note: In this milestone, taxonomy bucketing is based on segmentation artifacts and label confusions. The deeper sub-causes inside “ingredient errors” (quantity/unit/name/…) are not fully inferable from block labels alone; the report should still use this bucket name but include a brief “how this bucket is assigned today” sentence so readers don’t assume deeper parsing evaluation already exists.


## Interfaces and Dependencies

Prescriptive end-state interfaces (new modules/functions) to keep the implementation stable and benchmark-friendly.

1) `cookimport/bench/segmentation_metrics.py` (new)

Define these dataclasses (plain Python dataclasses are fine):

- `Span(start: int, end: int)`
- `PRF(precision: float, recall: float, f1: float, tp: int, fp: int, fn: int, gold_count: int, pred_count: int, matched_count: int, not_applicable: bool)`
- `SegmentationBoundaryReport` with fields:
  - `ingredient_start: PRF`
  - `ingredient_end: PRF`
  - `instruction_start: PRF`
  - `instruction_end: PRF`
  - `recipe_split: PRF`
  - `overall_micro: PRF` (micro-average across all applicable boundary sets)

Define these functions (exact signatures):

- `runs(labels: list[str], target_label: str) -> list[Span]`
  - Returns maximal contiguous spans where `labels[i] == target_label`.

- `recipe_title_runs(labels: list[str]) -> list[Span]`
  - Equivalent to `runs(labels, "RECIPE_TITLE")`, but factored so we can change the definition later in one place.

- `boundaries_from_runs(runs: list[Span], which: str) -> set[int]`
  - `which` in {"start", "end"}; returns a set of block indices.

- `recipe_split_boundaries(labels: list[str]) -> set[int]`
  - Returns the start indices of each RECIPE_TITLE run after the first.
  - If there are 0 or 1 title runs, returns empty set and is marked not_applicable in PRF.

- `match_boundaries(gold: set[int], pred: set[int], tolerance: int) -> tuple[set[int], set[int], set[tuple[int,int]]]`
  - Returns (unmatched_gold, unmatched_pred, matched_pairs).
  - Must be deterministic. Use sorted lists and a stable nearest-match tie-break.

- `boundary_prf(gold: set[int], pred: set[int], tolerance: int, not_applicable_when_gold_empty: bool) -> PRF`
  - If `not_applicable_when_gold_empty` is true and `gold` is empty, return PRF with `not_applicable=True` (do not treat as “perfect 1.0”).
  - Use exact match when tolerance = 0.

- `compute_segmentation_boundaries(labels_gold: list[str], labels_pred: list[str], tolerance_blocks: int) -> SegmentationBoundaryReport`
  - Computes:
    - ingredient start/end boundaries from `INGREDIENT_LINE` runs
    - instruction start/end boundaries from `INSTRUCTION_LINE` runs
    - recipe split boundaries from `RECIPE_TITLE` runs
  - This function implements Priority 8 boundary PRF requirements. 

2) `cookimport/bench/error_taxonomy.py` (new)

Define:

- `ErrorBucket` enum with exactly these values (string values must match):
  - `extraction_failure`
  - `boundary_errors`
  - `ingredient_errors`
  - `instruction_errors`
  - `yield_time_errors`

Define:

- `bucket_block_mismatch(gold_label: str, pred_label: str) -> ErrorBucket | None`
  - Returns None when labels match.
  - Heuristic bucketing rules (deterministic and documented in code):
    - If either label is `INGREDIENT_LINE`, bucket `ingredient_errors`
    - Else if either label is `INSTRUCTION_LINE`, bucket `instruction_errors`
    - Else if either label is `YIELD_LINE` or `TIME_LINE`, bucket `yield_time_errors`
    - Else if either label is `RECIPE_TITLE`, bucket `boundary_errors` (title mislabels often reflect split/merge)
    - Else bucket `extraction_failure` (this is the “everything else” bucket initially)

- `bucket_boundary_misses(...) -> dict[ErrorBucket, int]`
  - Boundary-level misses/false-positives should increment `boundary_errors`.
  - This keeps taxonomy aligned with Priority 8’s “boundary errors” focus. 

3) Extend `cookimport/bench/eval_stage_blocks.py` (existing)

- Add new option plumbing (either as function args or by reading an existing config object) so the evaluator can be called with:
  - `label_projection` (see below)
  - `boundary_tolerance_blocks`
  - `segmentation_metrics` selection set (at least `boundary_f1`; optional `segeval_*`)

- Add an additive section to the eval report JSON dict:

  - Top-level key: `segmentation`
  - Subkeys:
    - `label_projection`
    - `boundary_tolerance_blocks`
    - `boundaries` (the PRF results)
    - `error_taxonomy` (bucket counts + pointers to example artifacts)
    - optional `segeval` (when requested and available)

4) Label projection modes (benchmarkable options)

Implement label projection as an explicit selectable option (so you can benchmark permutations), not as hidden behavior:

- `freeform_full`: use the full freeform label vocabulary as-is
- `canonical_full`: use the full canonical label vocabulary as-is
- `core_structural_v1`: collapse everything except `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE` into `OTHER`

Boundary metrics MUST be computed on `core_structural_v1` labels (even if block metrics are computed on full vocabularies), because Priority 8’s boundary definitions are specifically about ingredient/instruction/title structure. 

5) `segeval` optional backend (additional option, not replacement)

- Add `segeval` as an optional dependency and compute these additional segmentation metrics when requested:
  - Pk
  - WindowDiff
  - boundary similarity

This is explicitly called out as a useful measurement tool in `BIG PICTURE UPGRADES.md`, and it should be wired as “extra metrics” rather than changing the default scoring. 

6) New CLI command: `cookimport recipe-segmentation-eval` (in `cookimport/cli.py`)

- Must call the same underlying evaluator used by bench (no duplicated scoring logic).
- Must support:
  - canonical gold vs freeform gold inputs as options (Priority 8 asks for both) 
  - gold as spans vs gold as block-labels as options (benchmarkable permutations)
  - optional segeval metrics as options

7) Keep existing behaviors

- Existing stage-block evaluation metrics (overall accuracy, per-label PRF, macro_f1_excluding_other, mismatch lists) remain present and unchanged in meaning. The new boundary metrics are additive. 

Change note (2026-02-25): Created this ExecPlan to implement Priority 8’s boundary-first evaluation upgrade and to incorporate `segeval` as an additional, benchmarkable segmentation-metric option. 