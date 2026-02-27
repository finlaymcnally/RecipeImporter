# Speed up stage and stage-blocks runs with accuracy-neutral “small wins” in writing and pred-run artifacts

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repo root. This ExecPlan must be maintained in accordance with `PLANS.md` (format, required sections, progress tracking, and decision logging).

## Purpose / Big Picture

After this change, `cookimport stage` and stage-blocks-style prediction runs (offline `labelstudio-benchmark --eval-mode stage-blocks` and `cookimport bench run`) should complete faster without changing any extraction/parsing results (“accuracy-neutral”). The gains come from removing redundant computation and reducing pure I/O overhead in “stage-like” writing paths, not from changing conversion logic.

You will be able to see it working by running a representative stage-block benchmark before/after and observing a lower `processed_output_write_seconds` (and often lower total `prediction_seconds`) in `eval_report.json`, while the scored metrics and labels remain identical. For stage runs, you should see lower `writing_seconds` and unchanged staged JSON outputs.

## Progress

- [ ] (2026-02-27) Baseline/perf artifact capture for one representative stage run + one stage-block benchmark run (before/after timing + digest evidence) is still pending.
- [x] (2026-02-27) Split-merge output stats now include merged `raw/.../full_text.json` and moved raw artifacts before report emission.
- [x] (2026-02-27) Markdown write toggles remain wired through stage + processed-output paths with default stage behavior unchanged.
- [x] (2026-02-27) Added prepared archive abstraction (`PreparedExtractedArchive`, `prepare_extracted_archive`) and reused it for archive/text serialization.
- [x] (2026-02-27) Label Studio task JSONL optionality is implemented and retained with offline guardrails.
- [x] (2026-02-27) Added targeted coverage for split-merge outputStats parity, prepared-archive payload parity, markdown-toggle no-drift stage predictions, and bench-run direct flag overrides.
- [x] (2026-02-27) Updated staging/bench/labelstudio docs for new behavior and knobs.
- [ ] (2026-02-27) Manual end-to-end stage-block timing proof run is still pending in-repo evidence capture.

## Surprises & Discoveries

- Observation: split-merge wrote the final report before `_merge_raw_artifacts(...)`, so `outputStats` could miss files moved from `.job_parts/**/raw`.
  Evidence: `_merge_split_jobs(...)` sequencing and new parity test in `tests/staging/test_split_merge_status.py`.
- Observation: `bench run` already supported write toggles through config plumbing (`cookimport/bench/pred_run.py`), so the lowest-risk CLI upgrade was optional direct overrides that preserve config/default behavior when omitted.
  Evidence: `build_pred_run_for_source(...)` config keys + new `bench_run(...)` override test in `tests/bench/test_bench.py`.

## Decision Log

(Record decisions as they are made.)

- Decision: Default behavior for `cookimport stage` remains unchanged (markdown summaries stay on by default).
  Rationale: Stage outputs are a human-facing product surface; speedups must be opt-in here to avoid surprising missing artifacts.
  Date/Author: 2026-02-27 / plan author

- Decision: For benchmark/bench flows, allow turning off “non-scoring” artifacts (notably Label Studio task JSONL and/or markdown summaries) when offline and stage-block scoring is the goal.
  Rationale: These artifacts are not part of scoring surface in stage-block mode; skipping them is accuracy-neutral and reduces write cost.
  Date/Author: 2026-02-27 / plan author

- Decision: split-merge must finalize raw-artifact moves before writing report JSON so `outputStats` reflects the real merged output tree without fallback directory scans.
  Rationale: report-time stats need to include all produced artifacts, including post-write merge moves.
  Date/Author: 2026-02-27 / implementation closeout

- Decision: `bench run` direct write toggles are optional overrides (`None` default) layered on top of config-file values.
  Rationale: exposes first-class CLI knobs while preserving existing config-driven behavior for users who do not pass the new flags.
  Date/Author: 2026-02-27 / implementation closeout

## Outcomes & Retrospective

- Outcome (2026-02-27): D-01/D-02/D-03/D-04/D-06 implementation gaps from the speed1-5 audit were closed in code/tests/docs. Prediction-run archive prep now has an explicit prepared object; split-merge outputStats now match a fresh directory walk in tests; bench run now has direct write-toggle flags.
- Outcome (2026-02-27): speed and no-drift proof depth improved with deterministic tests for prepared-archive payload parity and markdown-toggle stage-prediction parity.
- Remaining (2026-02-27): D-05-style baseline/performance evidence capture against a representative real dataset is still a manual artifact/documentation task.

## Context and Orientation

### What “stage” and “stage-blocks mode” mean in this repo

- `cookimport stage` is the normal “book processing” path. It converts source inputs (EPUB/PDF/etc) into staged outputs under `data/output/<timestamp>/`, writing:
  - intermediate JSON-LD (`intermediate drafts/...`)
  - final cookbook3 drafts (`final drafts/...`)
  - sections/tips/chunks/tables artifacts
  - a per-file run report: `<workbook_slug>.excel_import_report.json`
  - stage evidence: `.bench/<workbook_slug>/stage_block_predictions.json` (deterministic block labels)

- “stage-blocks” evaluation mode is the fast benchmark evaluator that scores:
  - predictions from `stage_block_predictions.json` (one label per `block_index`)
  - against gold freeform block labels derived from `exports/freeform_span_labels.jsonl`
  - evaluation itself is very fast; prediction generation is the runtime driver.

### Where the code lives (key touchpoints)

Stage and staging:
- `cookimport/cli.py`:
  - `stage(...)` orchestrates stage jobs and split merges.
  - `_merge_split_jobs(...)` merges split PDF/EPUB job outputs.
- `cookimport/cli_worker.py`:
  - `stage_one_file(...)`, `stage_pdf_job(...)`, `stage_epub_job(...)` run worker conversion and write outputs.
- `cookimport/staging/writer.py`:
  - Writer functions for intermediate/final outputs and stage evidence:
    `write_intermediate_outputs`, `write_draft_outputs`, `write_section_outputs`, `write_tip_outputs`,
    `write_topic_candidate_outputs`, `write_chunk_outputs`, `write_table_outputs`, `write_raw_artifacts`, `write_report`.

Benchmark prediction generation:
- `cookimport/labelstudio/ingest.py`:
  - `generate_pred_run_artifacts(...)` runs conversion and writes prediction-run artifacts.
  - `_write_processed_outputs(...)` writes stage-style “processed outputs” used for benchmark parity.

Extracted archive helpers (shared):
- `cookimport/labelstudio/archive.py`:
  - Builders/normalizers for `extracted_archive.json` and related block streams used for evaluation diagnostics and (in some paths) evidence generation.

Tests that should remain green / are likely to need updates:
- `tests/test_cli_output_structure.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py`
- `tests/bench/test_eval_stage_blocks.py`
- `tests/staging/test_run_manifest_parity.py`
- (and any staging writer tests that assert file layout)

### Why these are “small wins” and why they’re accuracy-neutral

The stage-block benchmark telemetry indicates stage-block runs are dominated by prediction/conversion and then writing. Evaluation is negligible. That makes “writing-time and redundant-work” optimizations disproportionately valuable: they reduce wall time without changing parser logic.

This plan explicitly avoids algorithm changes to conversion or scoring. Changes are limited to:
- avoiding redundant recomputation of already-available deterministic data (especially normalized block streams),
- reducing filesystem work (directory walks, redundant writes),
- skipping artifacts that do not affect scoring (only when explicitly requested or in safe offline contexts),
- and preserving default stage outputs for human workflows.

## Plan of Work

Implement the following changes, in order, using small commits and validating after each milestone.

### Milestone 1: Establish a baseline and lock in “no accuracy drift” checks

At the end of this milestone you will have:
- a reproducible “before” timing snapshot for one stage-block benchmark run and one stage run,
- a scriptable way to compare “semantic equality” of key JSON outputs (parse JSON and compare data structures; do not compare raw formatting),
- and you will know which parts of the write pipeline dominate `writing_seconds` / `processed_output_write_seconds` on your dataset.

Work:

1) Pick a representative input and gold export.
   - Use something “large enough” to make writing non-trivial (a medium/large EPUB or PDF).
   - Ensure you have a matching gold export dir with `exports/freeform_span_labels.jsonl`.

2) Capture a stage-block benchmark baseline:
   - Run (explicit paths are strongly preferred so results are reproducible):

        source .venv/bin/activate
        cookimport labelstudio-benchmark \
          --no-upload \
          --eval-mode stage-blocks \
          --source-file data/input/<your_book>.epub \
          --gold-spans data/golden/<your_gold>/exports/freeform_span_labels.jsonl \
          --overwrite

   - Locate the produced `eval_report.json` under `data/golden/benchmark-vs-golden/<run_ts>/.../eval_report.json` and record:
     - `timing.prediction_seconds`
     - `timing.processed_output_write_seconds`
     - overall score metrics (so you can prove they remain unchanged)

3) Capture a stage baseline:
   - Run:

        source .venv/bin/activate
        cookimport stage data/input/<your_book>.epub --out data/output

   - Open `<run_dir>/<workbook_slug>.excel_import_report.json` and record:
     - `timing.writing_seconds`
     - any timing checkpoints related to writing (if present)

4) Capture output digests in a way that is robust to formatting changes:
   - Write a small one-off Python helper (kept outside the repo, or as a temporary local script) that:
     - loads JSON outputs (final drafts and stage_block_predictions) from the run directory,
     - normalizes them (for example: sort lists only where order is explicitly documented as irrelevant; do not reorder documented-ordered lists),
     - computes SHA-256 over a canonical JSON dump of the loaded object.
   - The goal is: after optimizations, you can prove the parsed JSON objects are identical.

Acceptance:
- You can point to (a) baseline timing numbers and (b) baseline semantic digests for at least:
  - `.bench/<workbook_slug>/stage_block_predictions.json`
  - one `final drafts/<workbook_slug>/r0.json` (or several recipes)
- You have a saved “before” record in your local notes.

### Milestone 2: Remove expensive post-write directory scans by tracking output stats incrementally

At the end of this milestone you will have:
- the same `outputStats` values in `<workbook_slug>.excel_import_report.json`,
- but produced without a full directory walk after writing,
- and with tests proving the incremental stats match a “ground truth” directory scan.

Work:

1) Find the current outputStats collection behavior.
   - In `cookimport/staging/writer.py`, locate where `ConversionReport.outputStats` is populated (likely inside `write_report(...)` or right before it).
   - Also inspect `cookimport/core/models.py` for the `ConversionReport` and the shape of `outputStats` so you preserve the schema exactly.

2) Introduce a small “output stats collector” abstraction that can be passed through writer calls.
   - Add a module such as `cookimport/staging/output_stats.py` (or keep it in `writer.py` if that is the established style).
   - Define a minimal class with responsibilities:
     - `record_written_file(path: Path)`: stat the file and update counters.
     - `record_moved_file(dst_path: Path)`: same as written, but used for raw artifact moves.
     - `to_output_stats_dict() -> dict`: returns exactly what `ConversionReport.outputStats` expects.

   - Keep it intentionally dumb and deterministic. Avoid clever caching that could go stale.

3) Wire it through writer functions.
   - In `cookimport/staging/writer.py`, update each writer that creates files to call the collector after each write.
     - JSON/JSONL writers: after the file is closed, call `collector.record_written_file(path)`.
     - Markdown/text writers: same.
     - Raw artifact writers: after copy/move, record the final destination file.
   - Ensure split-job merge path also uses the same mechanism:
     - `cookimport/cli.py:_merge_split_jobs(...)` should populate outputStats using the collector from the merged-write pass, not by scanning the directory.

4) Keep a temporary “parity mode” during rollout (recommended):
   - For 1–2 commits, compute both:
     - incremental stats (new),
     - directory scan stats (old),
     - and assert (in code, behind an env var or debug guard) that they match.
   - Use this to smoke out missing “record_written_file” calls.
   - After tests exist and pass, remove or disable the double computation by default.

5) Add tests:
   - Add a staging test that runs a tiny stage write (or uses existing fixtures that already write outputs to a temp directory) and compares:
     - `report.outputStats` vs a fresh directory walk in the test.
   - Ensure the test covers at least:
     - JSON writes
     - markdown writes (if still enabled in the fixture)
     - raw artifact writes/moves if the fixture produces them (otherwise keep a separate small fixture or simulate one write)

Acceptance:
- `pytest tests/staging -m "staging and not slow"` passes.
- A representative stage run produces the same `outputStats` as before (sanity-check by comparing JSON objects, not raw file text).
- On the representative large file, you can observe `writing_seconds` decreases measurably (even a small improvement is acceptable; the main goal is removing an O(file_count) directory walk).

### Milestone 3: Add a markdown-output toggle to staging writers and surface it safely

At the end of this milestone you will have:
- a new way to skip writing “human-friendly” markdown summaries (`sections.md`, `tips.md`, `chunks.md`, etc.) without impacting any scoring surfaces,
- default behavior preserved for `cookimport stage`,
- and a clear fast path for benchmark/bench flows to avoid markdown costs.

Work:

1) Identify which writer functions generate markdown.
   - In `cookimport/staging/writer.py`, locate writes of:
     - `sections/<workbook_slug>/sections.md`
     - `tips/<workbook_slug>/tips.md`
     - `chunks/<workbook_slug>/chunks.md`
     - `tables/<workbook_slug>/tables.md`
     - topic candidate markdown, knowledge markdown, etc. (if applicable)

2) Add a single boolean parameter (consistent across writer calls):
   - Example: `write_markdown: bool = True`
   - Apply it to the relevant writer functions. When `False`, skip `.md` generation only. Keep JSON/JSONL outputs unchanged.

3) Thread it through stage:
   - Add a CLI option to `cookimport stage`, defaulting to current behavior:
     - `--write-markdown / --no-write-markdown` (default `--write-markdown`)
   - Update `cookimport/cli_worker.py:stage_one_file(...)` to pass this option into writer calls.
   - Update split-merge path in `cookimport/cli.py:_merge_split_jobs(...)` to pass the same option when writing merged outputs.

4) Thread it through processed-output benchmark writing:
   - In `cookimport/labelstudio/ingest.py:_write_processed_outputs(...)`, add a parameter `write_markdown` and pass it into staging writers.
   - Decide how benchmark/bench should call it:
     - For non-interactive, offline, stage-block scoring contexts, prefer `write_markdown=False` (speed-focused).
     - For upload workflows or human-inspection workflows, keep `True`.
   - Implement this as either:
     - a new CLI flag on `labelstudio-benchmark` and `bench run`, or
     - an internal “safe default” for stage-block offline paths only, with an override flag to force markdown on.

   The safer initial choice is: add a flag and keep existing defaults, then (after confirming no workflows rely on markdown) consider changing defaults in a follow-up PR.

5) Update/extend output-structure tests:
   - Add one new test that runs stage with `--no-write-markdown` and asserts:
     - required JSON files exist,
     - markdown files do not exist,
     - and `.bench/<workbook_slug>/stage_block_predictions.json` still exists.
   - Ensure existing tests remain valid for the default path.

Acceptance:
- Default `cookimport stage` output tree is unchanged.
- `cookimport stage ... --no-write-markdown` omits markdown but otherwise produces identical JSON artifacts and identical stage evidence labels.
- A representative stage-block benchmark run can be configured to avoid markdown writing, and `processed_output_write_seconds` decreases.

### Milestone 4: Deduplicate extracted-archive / normalized-block computation in pred-run generation

At the end of this milestone you will have:
- `generate_pred_run_artifacts(...)` computing the “normalized block stream” (or extracted archive structure) once,
- and reusing it for whichever artifacts need it (archive file, task generation, canonical alignment inputs, stage evidence helpers if applicable),
- reducing CPU and memory churn in prediction generation without touching conversion.

Work:

1) Map which artifacts require a normalized block stream today.
   - In `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`, find where it writes:
     - `extracted_archive.json`
     - `label_studio_tasks.jsonl`
     - `coverage.json` (if it exists)
   - In `cookimport/labelstudio/archive.py`, locate the function(s) that:
     - build the extracted archive,
     - normalize block text,
     - and attach extractor/blockization metadata.

2) Confirm whether the archive builder is being invoked multiple times.
   - Use quick instrumentation (temporary timing logs) or just grep for repeated calls to the same builder.
   - The outcome should be factual: either we are duplicating work, or we are not. Record what you find in `Surprises & Discoveries`.

3) Refactor to an explicit “prepared archive” object.
   - In `cookimport/labelstudio/archive.py`, define a small data structure (dataclass is fine) that holds:
     - the normalized blocks (the exact representation the rest of the pipeline expects),
     - any metadata needed for downstream writes (extractor name, options, block count, source hash, etc.).
   - Provide one constructor function:
     - `prepare_extracted_archive(...) -> PreparedExtractedArchive`
   - Provide thin helpers that serialize the prepared object to:
     - the on-disk `extracted_archive.json` format,
     - any alternative formats task generation needs (if different).

4) Update call sites to reuse the prepared object.
   - In `generate_pred_run_artifacts(...)`:
     - build `PreparedExtractedArchive` once,
     - pass it to:
       - extracted archive writer
       - freeform task generator (if it needs block text)
       - any diagnostic writers that need block text.
   - Keep the produced JSON artifacts exactly the same as before (schema and content).

5) Add a unit test guardrail.
   - Add or extend tests under `tests/labelstudio/` to ensure:
     - extracted archive JSON is identical (parsed object equality) before/after refactor for a fixture input.
   - If you do not have a stable fixture for this, use an existing test helper that builds a small “fake block stream” deterministically.

Acceptance:
- Stage-block benchmark metrics remain unchanged.
- Prediction-generation time decreases measurably on representative inputs (especially when extracted archive and tasks are enabled).
- No schema changes in `extracted_archive.json` or task JSONL unless explicitly versioned and documented (this plan assumes no schema changes).

### Milestone 5: Make Label Studio task JSONL optional in offline stage-block contexts

At the end of this milestone you will have:
- the ability to skip `label_studio_tasks.jsonl` generation when it is not needed (typical offline stage-block runs),
- saving CPU and disk I/O,
- with default behavior preserved where tasks are needed for upload or human review.

Work:

1) Identify which commands and code paths truly require `label_studio_tasks.jsonl`.
   - Upload flows and `labelstudio-import` require it.
   - Pure offline scoring in stage-block mode does not use it as a scoring surface (the scoring surface is `stage_block_predictions.json`).

2) Add an explicit control knob.
   - In `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`, add a parameter:
     - `write_label_studio_tasks: bool = True`
   - In CLI entrypoints:
     - `cookimport labelstudio-benchmark`: add `--write-labelstudio-tasks/--no-write-labelstudio-tasks` (default should preserve existing behavior).
     - `cookimport bench run`: add the same flag if bench runs currently write tasks; default can remain “write” initially for compatibility, but document that disabling is a performance optimization.

3) Ensure downstream code does not assume tasks exist in offline stage-block mode.
   - Any code that reads tasks for reporting should be guarded and emit a helpful message when tasks were intentionally skipped.

4) Update docs:
   - `docs/07-bench/runbook.md`: mention the flag and that tasks are not required for scoring.
   - `docs/06-label-studio/06-label-studio_README.md`: clarify when tasks are generated and how to disable them in offline benchmark runs.

Acceptance:
- `cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks --no-write-labelstudio-tasks ...` succeeds and produces a valid `eval_report.json`.
- Metrics are unchanged relative to the “tasks written” run for the same inputs.
- Disk footprint of pred-run directories decreases, and prediction-generation time improves at least modestly.

## Concrete Steps

Run these commands from the repository root unless stated otherwise.

### Baseline capture (before changes)

1) Activate venv:

    source .venv/bin/activate

2) Run one stage-block benchmark (offline):

    cookimport labelstudio-benchmark \
      --no-upload \
      --eval-mode stage-blocks \
      --source-file data/input/<your_book>.epub \
      --gold-spans data/golden/<your_gold>/exports/freeform_span_labels.jsonl \
      --overwrite

3) Open the produced `eval_report.json` and record:
- `timing.prediction_seconds`
- `timing.processed_output_write_seconds`
- headline metrics (overall accuracy, macro F1 excluding OTHER, etc.)

4) Run stage:

    cookimport stage data/input/<your_book>.epub --out data/output

5) Open `<run_dir>/<workbook_slug>.excel_import_report.json` and record:
- `timing.writing_seconds`
- `outputStats` payload

### Focused test runs during implementation

Use a fast “slice” frequently:

    pytest -m "staging or bench or labelstudio" -q

When touching CLI output structures:

    pytest tests/test_cli_output_structure.py -q

When touching stage-block evaluator contracts:

    pytest tests/bench/test_eval_stage_blocks.py -q

When touching pred-run generation:

    pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/labelstudio/test_labelstudio_ingest_parallel.py -q

### After-change verification

1) Re-run the same stage-block benchmark command.
2) Compare:
- `eval_report.json` metrics: must match exactly.
- `timing.processed_output_write_seconds`: should be lower (or at least not higher) when markdown/tasks are disabled.
3) Re-run stage on the same input and compare:
- parsed JSON equality for:
  - `.bench/<workbook_slug>/stage_block_predictions.json`
  - a small sample of final drafts JSON
- `timing.writing_seconds`: should be lower if directory-walk removal and markdown toggles are active.

## Validation and Acceptance

This change is accepted when all of the following are true:

1) Accuracy-neutral guarantee:
- For the same input + same run settings, stage-block benchmark metrics are identical before vs after:
  - same overall accuracy and per-label metrics,
  - and (crucially) the produced `stage_block_predictions.json` data structure is identical when loaded as JSON.

2) Default behavior stability:
- Running `cookimport stage ...` without new flags produces the same output tree (including markdown summaries) as before.
- Running benchmark/bench commands without new flags preserves prior artifact defaults (unless the implementation explicitly and safely scopes a default change to offline stage-block contexts, in which case it must be documented and tested).

3) Performance improvement:
- On the representative dataset:
  - `processed_output_write_seconds` is measurably lower when markdown and/or tasks are disabled.
  - `writing_seconds` for stage runs is measurably lower due to removal of directory walks for output stats.

4) Tests:
- Relevant pytest slices pass, and at least one end-to-end stage-block run is performed manually as described above.

## Idempotence and Recovery

- All new flags should be safe to run repeatedly.
- Any refactor that changes function signatures must include compatibility defaults so existing call sites behave the same until intentionally changed.
- For benchmark runs, `--overwrite` should continue to provide a clean rerun. If a new “skip tasks” mode is introduced, rerunning with the opposite setting should not crash; it may overwrite or remove only the artifacts it owns.
- If incremental outputStats tracking is found to be missing files, temporarily re-enable parity mode (compute both incremental and scan-based stats) and use the mismatch to find missed record calls.

## Artifacts and Notes

Include short evidence snippets here as implementation proceeds, for example:

- Before/after `eval_report.json` timing excerpt:

    timing:
      prediction_seconds: 30.14  -> 27.90
      processed_output_write_seconds: 3.22 -> 1.85

- Before/after digest confirmation for stage evidence:

    stage_block_predictions.json semantic digest:
      before: <sha256>
      after:  <sha256>
      match:  true

- Any discovered duplicate-work call graph for extracted archive normalization.

## Interfaces and Dependencies

### New/updated interfaces (expected end state)

1) Staging writers accept a markdown toggle.
- In `cookimport/staging/writer.py`, update relevant functions to accept:

    def write_section_outputs(..., write_markdown: bool = True, ...): ...
    def write_tip_outputs(..., write_markdown: bool = True, ...): ...
    def write_chunk_outputs(..., write_markdown: bool = True, ...): ...
    def write_table_outputs(..., write_markdown: bool = True, ...): ...

2) Output stats collector is explicit and reusable.
- Add a small class (module location is flexible, but keep it in staging):

    class OutputStatsCollector:
        def record_written_file(self, path: Path) -> None: ...
        def to_output_stats(self) -> dict: ...

- `write_report(...)` (or its caller) uses the collector instead of scanning the directory.

3) Prediction-run generation can reuse prepared archive data.
- In `cookimport/labelstudio/archive.py`:

    @dataclass(frozen=True)
    class PreparedExtractedArchive:
        # fields needed by writers and task generation

    def prepare_extracted_archive(...) -> PreparedExtractedArchive: ...

- In `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`, build it once and pass it down.

4) Prediction-run generation can skip Label Studio tasks when not needed.
- In `cookimport/labelstudio/ingest.py`:

    def generate_pred_run_artifacts(..., write_label_studio_tasks: bool = True, ...) -> ...: ...

- Threaded to CLI as `--write-labelstudio-tasks/--no-write-labelstudio-tasks`.

### Dependency policy

- Prefer not introducing new third-party dependencies for these wins. The intended speedups come from removing redundant work and reducing filesystem churn.
- If you do introduce a faster JSON encoder later (for example `orjson`), do it behind a soft dependency (import-if-available) and keep semantic output identical. That change should be its own small follow-up plan because it can have subtle formatting/typing implications.

---

Plan change note (required when revising this ExecPlan):
- 2026-02-27: Updated living sections for closeout progress; recorded split-merge outputStats sequencing fix, prepared-archive abstraction completion, bench-run direct write-toggle flags, and current remaining manual timing-evidence gap.
