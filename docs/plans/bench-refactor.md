# Make benchmark scores reflect staged outputs using block-level scoring

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with the repository’s `PLANS.md`. :contentReference[oaicite:0]{index=0}


## Purpose / Big Picture

Right now, the benchmark can show 0.0000 for labels like `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, and `RECIPE_VARIANT` even when the staged cookbook outputs clearly contain yield/time/notes/variants. The root cause is that benchmark scoring is comparing “prediction tasks” (`label_studio_tasks.jsonl` from `task_scope="pipeline"`) against freeform gold, instead of comparing the staged outputs you actually import into your cookbook site. That makes the benchmark misleading as a tool for improving the pipeline. :contentReference[oaicite:1]{index=1}:contentReference[oaicite:2]{index=2}

After this change:

- Benchmark “predictions” come from what the stage pipeline actually exports (canonical surface: `intermediate drafts/*.jsonld`, plus the separately-exported `knowledge/` artifacts).
- Scoring is at the block level (not span IoU), because your golden sets are exhaustive and block-oriented.
- A “100% benchmark score” means: if you imported the staged outputs into your website, you’d have all the recipes and global knowledge you labeled, with the expected fields populated.

How to see it working (end-to-end):

1. Pick an existing fully-labeled freeform golden set export (contains `freeform_span_labels.jsonl`).
2. Run the benchmark against a stage run (either by re-staging the input file, or by pointing at an existing `data/output/<timestamp>/...` run folder).
3. Observe:
   - `eval_report.md` contains:
     - overall block accuracy (all blocks, including `OTHER`)
     - macro F1 (labels excluding `OTHER`)
     - “worst-label recall” highlighted
   - Per-label totals are no longer mysteriously `pred_total=0` just because the old pipeline-task surface didn’t emit that chunk type. :contentReference[oaicite:3]{index=3}


## Progress

- [ ] (YYYY-MM-DD HH:MMZ) Baseline: reproduce the current “per-label 0.0000” behavior on one known golden set and record the exact command + the path to the generated `eval_report.md`.
- [ ] (YYYY-MM-DD HH:MMZ) Audit stage output surfaces: confirm what fields exist in `intermediate drafts/*.jsonld` for yield/time-lines/notes/variants, and confirm where global knowledge artifacts are written (`knowledge/<workbook_slug>/...`). :contentReference[oaicite:4]{index=4}
- [ ] (YYYY-MM-DD HH:MMZ) Define and implement a deterministic “stage evidence” manifest written alongside staged outputs: a block-level label map derived from stage outputs.
- [ ] (YYYY-MM-DD HH:MMZ) Add unit tests for stage evidence generation on a small synthetic block list + synthetic candidates.
- [ ] (YYYY-MM-DD HH:MMZ) Implement block-level evaluation: load gold freeform export → produce gold block-label map → compare to stage evidence.
- [ ] (YYYY-MM-DD HH:MMZ) Add unit tests for block-level evaluation, including conflict detection and metric computations (overall accuracy, macro F1, worst-label recall).
- [ ] (YYYY-MM-DD HH:MMZ) Wire the new evaluator into the benchmark CLI path so “benchmark” uses stage outputs as predictions by default.
- [ ] (YYYY-MM-DD HH:MMZ) Ensure benchmark can optionally produce importable staged outputs (so the “100% means website import is correct” statement is demonstrably true).
- [ ] (YYYY-MM-DD HH:MMZ) Update `eval_report.md`/`eval_report.json` format to include the new metrics and to highlight worst-label recall.
- [ ] (YYYY-MM-DD HH:MMZ) Update dashboard/history writer to record worst-label recall and the new block metrics (or clearly map them onto existing strict/practical fields if the UI expects those columns).
- [ ] (YYYY-MM-DD HH:MMZ) Remove dead Label Studio scopes and their code paths: `pipeline` and `canonical-blocks`, plus all benchmark “pipeline chunk task generation” machinery.
- [ ] (YYYY-MM-DD HH:MMZ) Remove/adjust tests that only exist for pipeline/canonical LS scopes; ensure full test suite passes.
- [ ] (YYYY-MM-DD HH:MMZ) Update docs/help text so the only supported Label Studio workflow is freeform gold import/export, and the only supported benchmark workflow is stage-vs-gold block scoring.
- [ ] (YYYY-MM-DD HH:MMZ) End-to-end acceptance run on one real golden set: verify worst-label recall is highlighted; verify no “pred_total=0 just because surface doesn’t emit label” mismatch remains.
- [ ] (YYYY-MM-DD HH:MMZ) Outcomes & retrospective entry written after merging.


## Surprises & Discoveries

- Observation: The intermediate JSON-LD surface may not currently contain explicit representations for some labels you want to benchmark (especially `TIME_LINE` as “top-of-recipe time lines”, distinct from step `time_seconds`). If true, we must decide whether to add those fields to JSON-LD (namespaced metadata is fine) or treat their absence as a legitimate extraction miss.
  Evidence: (fill in with one inspected `r*.jsonld` excerpt and file path)

- Observation: Notes and variants can be “derived” fields (e.g., variants created by splitting instruction lists; notes assembled from description/tags). For benchmarking, only book-text-provenanced blocks should count as `RECIPE_NOTES` / `RECIPE_VARIANT`, per your requirements. :contentReference[oaicite:5]{index=5}


## Decision Log

- Decision: The canonical benchmark prediction surface for recipes is `data/output/<timestamp>/intermediate drafts/<workbook_slug>/*.jsonld`, not Label Studio pipeline tasks.
  Rationale: You want the benchmark to reflect what your website import consumes, so improving the pipeline improves the benchmark.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Knowledge is benchmarked from the separately-exported knowledge artifacts (stage “knowledge” outputs), not from recipe-local notes.
  Rationale: You define knowledge as global (applies to many recipes), extracted after recipes are done, and already exported separately.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Scoring is block-level classification, not span IoU.
  Rationale: Golden sets are exhaustive and block-oriented; IoU between segments is the wrong abstraction and creates misleading near-zero scores.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Golden sets are required to be exhaustive: every block must have exactly one label from the freeform taxonomy, including `OTHER`.
  Rationale: You stated “The golden set is 100% labelled and always will be”, and `OTHER` exists to mean “ignore”. This allows clean block-level scoring with unlabeled-as-error, not unlabeled-as-negative.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Do not benchmark step-internal `time_seconds` extraction at all.
  Rationale: You only want `TIME_LINE` to mean top-of-recipe time lines (prep/cook/total/active/etc), and times in instruction lines can remain embedded in text for now.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Recipe grouping correctness is not a benchmark requirement for now.
  Rationale: You doubt that failure mode; the first goal is coverage/selection correctness at the block level.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: “Derived metadata” must not inflate `RECIPE_NOTES` / `RECIPE_VARIANT` scores; only outputs with book-text provenance count.
  Rationale: You explicitly want these labels compared to what you labeled in the book, not to assembled metadata.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: “Worst-label recall” must be surfaced prominently in reports/UI.
  Rationale: It’s the fastest way to see what part of the pipeline is failing coverage-wise.
  Date/Author: 2026-02-25 (ChatGPT)

- Decision: Remove Label Studio task scopes `pipeline` and `canonical-blocks` entirely after the new stage-block benchmark is in place.
  Rationale: You never use them, and they create confusing dead code and mismatched benchmark behavior.
  Date/Author: 2026-02-25 (ChatGPT)


## Outcomes & Retrospective

(Write after milestone completion.)

- Outcome:
- Gaps:
- Lessons learned:
- Next step:


## Context and Orientation

Key concepts (define these for a novice):

- Block: A single extracted chunk of text from the source file (paragraph, heading, list item, etc.) with a stable `block_index` in the “extracted archive” for that run. Blocks are the atomic unit Label Studio freeform gold is meant to label and what we will score.
- Freeform gold: A Label Studio project exported as `freeform_span_labels.jsonl`, using labels:
  `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`,
  `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`. :contentReference[oaicite:6]{index=6}
- Stage outputs: The artifacts written by `cookimport stage` under `data/output/<timestamp>/...`, including:
  - `intermediate drafts/<workbook_slug>/r{index}.jsonld`
  - `final drafts/<workbook_slug>/r{index}.json`
  - optional `knowledge/<workbook_slug>/...` when pass4 knowledge harvesting is enabled
  Writer code and layout live in `cookimport/staging/writer.py`, with JSON-LD conversion in `cookimport/staging/jsonld.py`. :contentReference[oaicite:7]{index=7}

Current mismatch we are fixing:

- Stage and benchmark share conversion and can both write cookbook outputs, but benchmark scoring currently uses prediction-task artifacts (`label_studio_tasks.jsonl` from `task_scope="pipeline"`) rather than the staged cookbook outputs, so it cannot “see” labels that aren’t emitted as pipeline chunk types. :contentReference[oaicite:8]{index=8}:contentReference[oaicite:9]{index=9}

Important constraint for this plan:

- We are not adding AI “predictions” for benchmarking. Predictions are purely deterministic projections of what the pipeline already exported (or claims to have exported) in staged outputs.
- Label Studio remains only for producing gold (freeform labeling and export).


## Plan of Work

We will implement a new “stage-block predictions” surface that is generated deterministically from staged outputs and then scored against freeform gold at the block level. Then we will wire the benchmark CLI (and optionally dashboard) to use that new scoring by default. Finally, we will remove dead Label Studio task scopes (`pipeline`, `canonical-blocks`) and their associated benchmark chunk generation code.

Milestones are independent and verifiable:

Milestone 1 (Evidence manifest): At the end, any stage run produces a deterministic `stage_block_predictions.json` (or similarly named) file that maps each `block_index` to exactly one label (or defaults to `OTHER`), derived from the same data the stage writers used to emit `intermediate drafts` and `knowledge` outputs.

Milestone 2 (Evaluator): At the end, there is a new evaluator that takes:
- a freeform gold export (`freeform_span_labels.jsonl`)
- a stage run directory (or a stage evidence manifest path)
and produces `eval_report.json` and `eval_report.md` based on block-level scoring, including “overall block accuracy”, “macro F1”, and “worst-label recall”.

Milestone 3 (CLI wiring): At the end, running the benchmark command (the one users actually use) executes stage → writes staged outputs → writes stage evidence → evaluates vs gold. The resulting benchmark score now corresponds to website-import correctness.

Milestone 4 (Cleanup): At the end, pipeline/canonical Label Studio modes are removed, and there is only one supported Label Studio workflow: freeform gold creation/export. Benchmark no longer references `task_scope="pipeline"` or pipeline chunk tasks at all.

Below, “file pointers” are deliberately precise so a novice can navigate.


## Concrete Steps

All commands should be run from the repository root unless otherwise noted.

Step 0: Baseline snapshot (before changing anything)

1. Run:
   - `cookimport --help`
   - `cookimport labelstudio-benchmark --help`
   - `cookimport bench run --help`
2. Pick one existing golden set export directory that contains `exports/freeform_span_labels.jsonl`.
3. Run the current benchmark against that golden set (use whatever current command you already use).
4. Save:
   - the command line used
   - the output paths printed (benchmark run dir, eval report path)
   - a copy/paste of the “Per-Label Breakdown” section showing any 0.0000 labels.

Step 1: Implement stage evidence manifest (block-level label projection)

1. Locate staging output code:
   - `cookimport/staging/writer.py` (writes intermediate/final/knowledge artifacts) :contentReference[oaicite:10]{index=10}
   - `cookimport/staging/jsonld.py` (intermediate JSON-LD conversion) :contentReference[oaicite:11]{index=11}
2. Add a new module to define the evidence schema and helper functions:
   - Create `cookimport/staging/stage_block_predictions.py`

   In that file, define:

   - A constant list `FREEFORM_LABELS` containing the full supported label taxonomy in canonical order:
     `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`,
     `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`.

   - A function:
     `def build_stage_block_predictions(conversion_result: ConversionResult, workbook_slug: str) -> dict:`
     returning a JSON-serializable dict with keys:
       - `schema_version`: `"stage_block_predictions.v1"`
       - `source_file`: (path string if available)
       - `source_hash`: (the run’s source hash if available)
       - `workbook_slug`
       - `block_count`
       - `block_labels`: a dict mapping `"0".."N-1"` to a single label string
       - `label_blocks`: a dict mapping label -> sorted list of block indices (redundant but convenient)
       - `conflicts`: list of `{block_index, labels}` for any block that would have >1 non-OTHER label before resolution
       - `notes`: freeform text list for debug warnings (e.g., “TIME_LINE not present in JSON-LD surface”)

   - A deterministic resolution rule for conflicts (if the stage pipeline “uses” a block in two places):
     - If a block is used by `RECIPE_VARIANT`, it should be labeled `RECIPE_VARIANT` (variant lines should not remain in steps).
     - Next preference order for “recipe area” blocks:
       `RECIPE_TITLE` > `YIELD_LINE` > `TIME_LINE` > `INGREDIENT_LINE` > `RECIPE_NOTES` > `INSTRUCTION_LINE`
     - `KNOWLEDGE` is global-only; if a block is in both recipe-local and global knowledge, that is a bug; record it in `conflicts` and choose recipe-local for now.
     - Any block with no positive label is `OTHER`.

     (This rule exists so the benchmark corresponds to how you want the website import to behave.)

3. Wire evidence writing into stage output writing:

   In `cookimport/staging/writer.py`, after the code that writes staged outputs for a workbook (after intermediate/final/knowledge writers run, so the in-memory objects reflect final staged decisions), write a new file:

   - Path:
     `data/output/<timestamp>/.bench/<workbook_slug>/stage_block_predictions.json`

     Rationale: keep it alongside stage outputs, but clearly “benchmark-oriented”.

   If `writer.py` already has a “per-workbook report” or a “run manifest”, also store the relative path to this evidence file inside that manifest so the benchmark runner can find it.

4. Ensure knowledge is represented:

   Confirm where “knowledge” blocks come from for staged outputs:
   - If knowledge comes from pass4 knowledge harvesting, identify the in-memory objects (or writer inputs) that represent those snippets and their source blocks.
   - If the current knowledge output does not include block provenance, add provenance at the point it is produced (do not try to re-find text via string search as the default approach).

   Then ensure `build_stage_block_predictions(...)` marks those blocks as `KNOWLEDGE`.

5. Add unit tests:

   Add `tests/test_stage_block_predictions.py` with a tiny synthetic conversion result:
   - block list of ~8 blocks
   - one recipe candidate that uses some blocks as title/ingredients/instructions/yield/variants/notes
   - one knowledge snippet referencing a non-recipe block

   Assert:
   - every block index has exactly one label in `block_labels`
   - `label_blocks` matches the inverse of `block_labels`
   - conflict detection is stable and deterministic

Step 2: Implement block-level evaluation vs freeform gold

1. Locate freeform evaluation code:

   - `cookimport/labelstudio/eval_freeform.py` currently maps pipeline chunks to labels and computes span-overlap metrics. The per-label zeros doc indicates that mapping lives in `_map_chunk_to_label(...)`. :contentReference[oaicite:12]{index=12}

   We will not extend pipeline chunking. Instead, we will implement a new evaluator that loads stage evidence and compares it to gold.

2. Add a new evaluator module:

   Create `cookimport/bench/eval_stage_blocks.py` (or, if the repo keeps benchmark evaluation inside `cookimport/labelstudio/`, place it there but name it clearly; do not bury it in “labelstudio ingest”).

   In that file implement:

   - `load_gold_block_labels(freeform_span_labels_jsonl_path: Path) -> dict[int, str]`
     This function must:
       - Load and normalize the gold export (reuse existing gold dedupe logic if it already exists in the codebase).
       - Convert spans into per-block labels.
       - Enforce “exactly one label per block”:
         - If any block receives multiple labels, write a `gold_conflicts.jsonl` report and fail with a clear error message (gold must be fixed).
         - If any block receives no label, also fail (gold must be exhaustive).

   - `load_stage_block_labels(stage_block_predictions_json_path: Path) -> dict[int, str]`
     This function must:
       - Load the `stage_block_predictions.json`
       - Validate schema version
       - Return per-block predicted label mapping

   - `compute_block_metrics(gold: dict[int, str], pred: dict[int, str]) -> dict`
     This function computes:
       - overall block accuracy: fraction of blocks where `pred_label == gold_label` across all blocks including `OTHER`
       - per-label precision/recall/F1 and totals:
         - treat each label (including `OTHER`) as “positive set” vs the rest (one-vs-rest), derived from the per-block labels
       - macro F1: mean of F1 across labels excluding `OTHER`
       - worst-label recall: the label (excluding `OTHER`) with minimum recall, and its recall value
       - also compute and store:
         - a confusion summary: counts of `(gold_label, pred_label)` pairs (keep as dict-of-dicts, not a big table)
         - lists of missed blocks and false positives per label for debugging

3. Write evaluation artifacts:

   For an eval run output directory (reusing the benchmark run dir layout you already have), write:

   - `eval_report.json`: machine-readable report including the metrics above
   - `eval_report.md`: human-readable, with:
     - a top summary including:
       - overall accuracy
       - macro F1
       - worst-label recall (highlight this; e.g., uppercase label name and value)
     - a per-label section that includes totals and precision/recall/f1 (small prose or compact list)
     - a “most common confusions” section listing a few highest `(gold, pred)` pairs
     - a short “debug pointers” section linking to misses/false positives JSONL files

   - `missed_gold_blocks.jsonl`: one row per missed block with:
     `{block_index, gold_label, pred_label, block_text_excerpt, workbook_slug, source_file}`
   - `wrong_label_blocks.jsonl`: blocks where label mismatched, same shape

   Block text excerpts must be pulled from the extracted block list used for that run. If it is not already easy to load, locate the raw artifact path containing the block list (commonly `raw/.../full_text.json` per docs) and load it. :contentReference[oaicite:13]{index=13}

4. Add unit tests:

   Add `tests/test_eval_stage_blocks.py`:

   - Construct gold and predicted per-block label dicts for a small block set.
   - Assert accuracy/macro F1/worst-label recall.
   - Include at least one case where:
     - a rare label is missed (ensures worst-label recall is that label)
     - `OTHER` dominates (ensures macro excludes OTHER)

Step 3: Wire the new evaluator into benchmark CLI

1. Identify current benchmark entrypoints:

   - Interactive benchmark menu is “Menu 5” and runs `cookimport/cli.py:labelstudio_benchmark`. :contentReference[oaicite:14]{index=14}
   - Offline suite runs exist under `cookimport bench run` and currently do not write processed cookbook outputs by default. :contentReference[oaicite:15]{index=15}

2. Implement two user-facing benchmark flows:

   A) Evaluate an existing stage run (fast iteration)

   Add a command (or subcommand) like:

   - `cookimport bench eval-stage --gold <gold_export_dir> --stage-run <data/output/<timestamp>>`

   Behavior:
   - Locate the stage evidence manifest for the workbook(s) inside the stage run.
   - For each workbook, run the evaluator and write an eval report under:
     `data/golden/benchmark/<timestamp>/...` (or a sibling folder inside the stage run; pick one and keep consistent).
   - Print the path to `eval_report.md`.

   B) Stage + evaluate (what “benchmark” should mean)

   Modify the “benchmark” command users actually run (menu 5 / `labelstudio-benchmark` / whatever is canonical in this repo) so that:

   - It always produces staged outputs (processed output snapshot) because that is the prediction surface.
   - It writes stage evidence manifests during output writing.
   - It runs the block evaluator and writes eval artifacts.
   - It no longer generates pipeline chunk tasks (`task_scope="pipeline"`) as the source of predictions.

   If the existing CLI already supports “processed outputs as side artifacts”, make that mandatory for this benchmark mode. The user-facing effect should be: after a benchmark run, you can import the printed “Processed output” directory into your website, and the score corresponds to that import’s correctness. :contentReference[oaicite:16]{index=16}

3. Preserve (or update) run manifests:

   Ensure the benchmark run manifest (wherever it is written today) now records:
   - the processed output run directory
   - the stage evidence manifest path(s)
   - the gold export path
   - the resulting key metrics, including worst-label recall

4. Update any benchmark history CSV writing:

   If the system appends benchmark results into a history CSV consumed by `cookimport stats-dashboard`, add columns (or reuse existing ones deliberately) so the dashboard can surface:
   - macro F1
   - overall accuracy
   - worst-label recall label + value

   If you must keep legacy column names (e.g., `strict_f1`), clearly document in code comments and report output that “strict_* now represent block-level classification metrics”.

Step 4: Remove dead Label Studio task scopes and pipeline chunk benchmark generation

1. Identify the Label Studio scopes:

   From project docs and code, there are three LS “task types”: `pipeline`, `canonical-blocks`, `freeform-spans`. You only use `freeform-spans`, and you want the other two removed.

2. Remove pipeline and canonical scopes:

   - Remove the CLI options, interactive menu entries, and internal branching that create or export `pipeline` and `canonical-blocks` tasks.
   - Delete or archive (depending on repo convention) modules that only serve those scopes, such as:
     - pipeline chunk task generation
     - canonical block task generation
     - canonical evaluation paths

   Keep freeform import/export intact:
   - Sending a book to Label Studio in freeform mode (with optional AI prelabel).
   - Exporting freeform labels and pulling them into a golden set.

3. Remove `task_scope="pipeline"` from benchmark prediction generation paths:

   Any benchmark path that still calls `generate_pred_run_artifacts(...)` to produce `label_studio_tasks.jsonl` from pipeline chunks should be removed or refactored to:
   - stage outputs + stage evidence manifest
   - block evaluator vs gold

4. Update tests:

   - Delete tests that only exist for pipeline/canonical behavior.
   - Ensure freeform labeling tests still pass.
   - Add/keep tests for the new stage evidence + stage-block evaluator.

5. Update docs/help text:

   - Update any docstrings or CLI help that claims benchmark is “task vs gold via label_studio_tasks.jsonl”.
   - Replace with “stage outputs vs gold (block-level)”.

   The goal is to prevent future confusion: there should be only one supported definition of “benchmark score”.


## Validation and Acceptance

Unit-level acceptance:

- `pytest` (or the repo’s test command) passes.
- New tests exist and pass:
  - `tests/test_stage_block_predictions.py`
  - `tests/test_eval_stage_blocks.py`

Behavior-level acceptance (real run):

1. Choose a real golden set export directory:
   - It contains `exports/freeform_span_labels.jsonl`.
2. Run benchmark in the new mode (stage + eval):
   - It must write staged outputs (so it is importable into the website).
   - It must write a `stage_block_predictions.json` evidence manifest per workbook.
   - It must write `eval_report.md` with:
     - overall block accuracy
     - macro F1 (excluding OTHER)
     - worst-label recall prominently shown
3. Confirm the old failure mode is gone:
   - Labels like `YIELD_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT` must no longer show `pred_total=0` merely because the old pipeline surface didn’t emit them.
   - If they are 0, it must be because the staged outputs truly didn’t capture those labeled blocks (a legitimate extraction miss), and the misses must appear in `missed_gold_blocks.jsonl`.

Cleanup acceptance:

- The CLI no longer offers `pipeline` or `canonical-blocks` Label Studio task scopes.
- No code path references `task_scope="pipeline"` for benchmark scoring.
- Freeform Label Studio import/export still works end-to-end.


## Idempotence and Recovery

- All new artifacts must be safe to generate repeatedly:
  - Benchmark runs should remain timestamped (new run dir per invocation) unless the repo already supports `--overwrite`/`--resume` semantics; in that case, make evidence generation deterministic and overwrite-safe.
- If gold is malformed (not exhaustive or has multi-label per block), evaluation must fail fast with a clear error message and must write a conflict report (`gold_conflicts.jsonl`) so the user can fix labeling.
- If stage evidence is missing (e.g., stage run from before this change), the evaluator must error with a single actionable message:
  - “This stage run predates stage evidence manifests; re-run stage or re-run benchmark after updating.”


## Artifacts and Notes

Expected new/updated artifacts (example paths; exact run roots depend on existing conventions):

- Stage run folder:
  - `data/output/<timestamp>/.bench/<workbook_slug>/stage_block_predictions.json`
- Benchmark eval folder:
  - `.../eval_report.json`
  - `.../eval_report.md`
  - `.../missed_gold_blocks.jsonl`
  - `.../wrong_label_blocks.jsonl`

When you implement, paste short transcripts here as indented examples, showing:

- The command you ran
- The path printed to `eval_report.md`
- The first ~10 lines of `eval_report.md` showing the summary and worst-label recall

Example (fill in during implementation):

    $ cookimport bench run --gold data/golden/pulled-from-labelstudio/<project>/exports --input data/input/<book>.epub
    Processed output: data/output/2026-02-25_12.34.56/<workbook_slug>/
    Wrote stage evidence: data/output/2026-02-25_12.34.56/.bench/<workbook_slug>/stage_block_predictions.json
    Wrote eval report: data/golden/benchmark/2026-02-25_12.35.10/eval_report.md

    Summary:
    - Overall block accuracy: 0.923
    - Macro F1 (excluding OTHER): 0.811
    - WORST-LABEL RECALL: TIME_LINE 0.250


## Interfaces and Dependencies

Key modules and why they matter:

- `cookimport/staging/writer.py`: This is where staged outputs are written and where we will add writing of the stage evidence manifest. This keeps predictions aligned to actual exported outputs. :contentReference[oaicite:17]{index=17}
- `cookimport/staging/jsonld.py`: This is the “intermediate drafts JSON-LD” conversion layer; we must ensure the evidence manifest reflects what this module outputs (and optionally add namespaced fields if needed for time-lines/variants/notes). :contentReference[oaicite:18]{index=18}
- `cookimport/bench/eval_stage_blocks.py` (new): Implements the core scoring contract: block-level classification vs gold.
- `cookimport/cli.py` and/or `cookimport/bench/*`: Wires the new evaluator into the user-facing benchmark commands.

New interfaces to implement:

In `cookimport/staging/stage_block_predictions.py`, define:

    def build_stage_block_predictions(conversion_result, workbook_slug) -> dict:
        """Return JSON-serializable stage block label predictions derived from staged outputs."""

In `cookimport/bench/eval_stage_blocks.py`, define:

    def evaluate_stage_blocks(*, gold_freeform_jsonl: Path, stage_predictions_json: Path, extracted_blocks_json: Path, out_dir: Path) -> dict:
        """
        Produce eval_report.json/md plus debug JSONL files.
        Return the metrics dict (also written to eval_report.json).
        """

Any external services:

- None required for benchmark scoring. Label Studio remains only for gold creation/export and is not part of offline evaluation paths.


## Change Log (plan maintenance)

(When you revise this plan mid-implementation, add a dated note here describing what changed and why.)