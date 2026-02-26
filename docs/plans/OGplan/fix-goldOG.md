---
summary: "ExecPlan for canonical-text benchmark mode that decouples gold scoring from extractor blockization."
read_when:
  - "When implementing extractor-independent benchmark evaluation against freeform gold exports"
---

# Approach A ExecPlan: Canonical-text gold + alignment-based benchmark (extractor-independent)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS.md is checked into the repo (path: `PLANS.md` from repo root). This ExecPlan must be maintained in accordance with `PLANS.md` formatting and workflow rules.:contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}

## Purpose / Big Picture

Today, a “golden set” (human-approved labels) is indirectly tied to the extractor’s block indices. If you run benchmark predictions with a different extractor/config than the one used when the gold was created, block indices drift and the evaluator “defaults missing gold to OTHER,” which can turn correct predictions into false positives and collapse per-label metrics to zero (the RECIPE_VARIANT 0/0/0 example).:contentReference[oaicite:2]{index=2}

After this change, you can create *one* freeform-spans golden set per underlying cookbook file and benchmark *any* extraction method/config against it, without needing extractor/block parity. The benchmark will:
1) anchor gold labels to a canonical “gold text” string derived from the gold itself,
2) align each prediction-run’s extracted text to that canonical text,
3) score predictions in canonical text space (not block-index space),
4) report both label quality metrics and alignment/coverage metrics so mis-extraction shows up as “coverage gaps,” not bogus “OTHER defaults.”

You can prove it works by:
- exporting a gold set and seeing new canonical artifacts alongside the existing exports, and
- running `cookimport labelstudio-benchmark --no-upload` (or `cookimport bench run`) with deliberately mismatched extractor settings and still getting meaningful metrics plus an explicit alignment coverage section.

## Progress

- [x] (2026-02-26 00:00Z) Drafted ExecPlan for Approach A (canonical-text gold + alignment eval) and grounded it in current bench/gold behavior docs.
- [x] (2026-02-26 01:10Z) Milestone 0: Baseline orientation completed; stage-block mismatch guard failures confirmed in all-method mismatch runs.
- [x] (2026-02-26 01:45Z) Milestone 1: Added canonical export artifacts in `labelstudio-export` (`canonical_text.txt`, `canonical_block_map.jsonl`, `canonical_manifest.json`).
- [x] (2026-02-26 01:55Z) Milestone 2: Added `canonical_span_labels.jsonl` + `canonical_span_label_errors.jsonl` generation/validation in export flow.
- [x] (2026-02-26 02:15Z) Milestone 3: Implemented monotonic SequenceMatcher-based alignment from prediction text blocks to canonical text offsets.
- [x] (2026-02-26 02:35Z) Milestone 4: Implemented canonical-text evaluator and canonical eval report/diagnostic artifacts.
- [ ] (2026-02-26 02:55Z) Milestone 5: Partially completed (done: `labelstudio-benchmark --eval-mode`, all-method forced to canonical-text; remaining: `bench run/sweep` eval-mode wiring if needed).
- [ ] (2026-02-26 03:05Z) Milestone 6: In progress (docs/conventions updates underway for canonical-text mode + all-method default).

## Surprises & Discoveries

- Observation: Stage-block mismatch guard did exactly what it was designed to do and surfaced 7/15 all-method configs as invalid for block-index scoring.
  Evidence: 2026-02-25 all-method report rows for configs 7-13 failed with `gold_prediction_blockization_mismatch`.
- Observation: Existing freeform export payload already had enough segment/block metadata to derive canonical offsets without new LS schema changes.
  Evidence: `segment_text` + `data.source_map.blocks[*].segment_start/end` were sufficient to emit canonical block maps and canonical spans.

## Decision Log

- Decision: Treat the gold export’s reconstructed text stream as the “canonical text” reference for that source file, and align all prediction runs to it.
  Rationale: This achieves “one gold per underlying file” without requiring a universal extractor; the gold itself becomes the anchor.
  Date/Author: 2026-02-26 / GPT-5.2 Pro

- Decision: Canonical-text evaluation will score on deterministic “canonical lines” (newline-delimited segments) derived from canonical text, not on extractor blocks.
  Rationale: Lines are stable across extractors and easy to map spans onto; avoids per-extractor block drift while keeping metrics interpretable.
  Date/Author: 2026-02-26 / GPT-5.2 Pro

- Decision: Keep existing stage-block evaluation untouched and add canonical-text evaluation as an explicit opt-in mode.
  Rationale: Stage-block scoring is intentionally “import alignment” and depends on block parity; canonical-text scoring is for extractor-independent benchmarking.
  Date/Author: 2026-02-26 / GPT-5.2 Pro

- Decision: Force interactive all-method benchmark to canonical-text mode.
  Rationale: All-method’s purpose is extractor/config comparison; forcing canonical-text avoids parity-driven false failures in exactly that flow.
  Date/Author: 2026-02-26 / GPT-5.2 Pro

## Outcomes & Retrospective

- Outcome: Canonical export artifacts and canonical evaluator are implemented; `labelstudio-benchmark` now supports `--eval-mode stage-blocks|canonical-text`, and all-method runs canonical-text by default.
  Notes: This resolves the extractor-parity blocker for all-method sweeps while preserving stage-block mode for parity-sensitive import-alignment checks.

## Context and Orientation

### Key terms (define once, use consistently)

A “block” in this repo is the importer’s deterministic unit of text (EPUB/PDF/Text importers produce an ordered stream of blocks). Bench and staging project decisions back onto this stream.:contentReference[oaicite:4]{index=4}

An “extractor” is the code path/config that turns a source file into blocks. Different extractors (or even different settings of the same extractor) can produce different block counts and boundaries.

A “golden set” (gold) is the human-approved labeling for a source file. In current practice it is created via Label Studio freeform spans and exported as `exports/freeform_span_labels.jsonl`.:contentReference[oaicite:5]{index=5}

“Stage evidence predictions” are the scored benchmark predictions produced by staging and written as one label per `block_index` in `.bench/<workbook_slug>/stage_block_predictions.json` (also copied into prediction-run roots).:contentReference[oaicite:6]{index=6}

“Stage-block evaluation” is the current benchmark scoring surface:
- predictions: `stage_block_predictions.json` (one label per `block_index`)
- gold: `freeform_span_labels.jsonl` projected to block labels
- missing gold rows default to `OTHER` (logged in `gold_conflicts.jsonl`).:contentReference[oaicite:7]{index=7}

### The current failure mode we are fixing

If the gold was created with one extractor/blockization and you benchmark with a different one, block indices no longer refer to the same underlying text. Because missing gold defaults to `OTHER`, this drift can create large numbers of false positives and collapse per-label metrics (example: RECIPE_VARIANT becomes 0/0/0 when predictions land in blocks that the gold run didn’t even have).

Operationally, this led to the documented “keep extractor parity” rule for benchmarks today.

Approach A changes the benchmark so gold does not depend on extractor block indices.

### Relevant existing modules and artifacts (you will confirm exact paths in your tree)

From docs, the key pieces are:

- Prediction-run artifact generation: `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py` writes:
  - `extracted_archive.json` (block text for mismatch excerpts),
  - `manifest.json` and `run_manifest.json`,
  - `label_studio_tasks.jsonl` (support artifact; not benchmark surface).:contentReference[oaicite:10]{index=10}

- Gold export contract: `cookimport labelstudio-export` writes:
  - `exports/labelstudio_export.json`
  - `exports/freeform_span_labels.jsonl`
  - `exports/freeform_segment_manifest.jsonl`
  - `exports/summary.json`:contentReference[oaicite:11]{index=11}

- Benchmark scoring surface: `cookimport bench run` and `labelstudio-benchmark --no-upload` compare `stage_block_predictions.json` vs gold-projected block labels.:contentReference[oaicite:12]{index=12}

## Interfaces and Dependencies

### New “canonical gold” interface (additive)

We will add new files to gold export output under `<gold_export_dir>/exports/`:

1) `canonical_text.txt`
   - The canonical text string for this gold set.
   - Built by ordering unique gold blocks by `block_index` and joining with a fixed separator.

2) `canonical_block_map.jsonl`
   - One JSON object per canonical block with:
     - `block_index` (int)
     - `start_char` / `end_char` offsets in `canonical_text.txt` (0-based, half-open)
     - `text_sha256` (optional; for integrity)
     - `text_len`
   - This is used to translate “offset within block” to “offset within canonical_text.”

3) `canonical_span_labels.jsonl`
   - Gold spans anchored to canonical character offsets:
     - `label`
     - `start_char`, `end_char` (0-based, half-open) in `canonical_text.txt`
     - `source_hash`, `source_file`
     - `span_id` (deterministic ID; see below)
     - `provenance` fields copied from freeform export (annotator, created_at, etc) when available

4) `canonical_manifest.json`
   - `schema_version: "canonical_gold.v1"`
   - `source_hash`, `source_file`
   - `block_separator` (string literal; e.g., "\n\n")
   - `block_count`, `canonical_char_count`
   - `notes` / `warnings` summary (missing indices, conflicting block texts)

These are additive. Existing exports remain unchanged and still produced.

### New evaluator interface (opt-in)

We will introduce a new evaluation mode for benchmark/bench:

- Inputs:
  - Prediction-run dir containing:
    - `stage_block_predictions.json` (stage evidence labels)
    - `extracted_archive.json` (block texts to align)
  - Gold export dir containing:
    - `exports/canonical_text.txt`
    - `exports/canonical_span_labels.jsonl`

- Output:
  - The usual eval artifacts in the eval output dir:
    - `eval_report.json`
    - `eval_report.md`
    - diagnostics JSONL files (see below)

This mode must not require extractor parity.

### Dependencies

We will not add third-party dependencies for the initial implementation. Use Python standard library only:
- `difflib` for fallback fuzzy matching (if needed)
- `re` for token/whitespace normalization
- `hashlib` for hashing
If performance becomes a problem later, we can add an optional dependency (e.g., `rapidfuzz`) as a follow-up, but it is not required to deliver working behavior.

## Plan of Work

This plan is organized into milestones. Each milestone is independently verifiable and leaves the repo in a working state.

### Milestone 0: Baseline + orientation in your actual working tree

Goal: confirm the exact code paths and current behavior before changes.

At the end of this milestone, you will have:
- confirmed locations of labelstudio export, bench eval, and prediction-run artifacts,
- captured a “before” baseline benchmark run that demonstrates the extractor-parity failure mode (or at least confirms current block-index scoring behavior).

Proof:
- You can point to the exact files in your tree and run one existing benchmark command successfully.

### Milestone 1: Canonical text artifacts emitted by `labelstudio-export`

Goal: make the gold export self-sufficient for canonical anchoring by emitting canonical text + block offset map.

At the end of this milestone:
- running `cookimport labelstudio-export ...` produces the 2 new files:
  - `exports/canonical_text.txt`
  - `exports/canonical_block_map.jsonl`
  - plus `exports/canonical_manifest.json`

Proof:
- A gold export directory contains those files and a small integrity check passes (the map ranges exactly partition the canonical text, except for the chosen separators).

### Milestone 2: Canonical-span labels emitted and validated

Goal: produce `canonical_span_labels.jsonl` where every span can be verified against canonical_text via substring checks.

At the end of this milestone:
- `exports/canonical_span_labels.jsonl` exists
- A validation routine confirms: for each row, `canonical_text[start_char:end_char]` equals the expected selected text (or equals it after trimming only leading/trailing spaces if the export contract allows that).

Proof:
- Running the export prints a short “canonicalization validation: OK (N spans)” summary and writes an errors JSONL if any mismatches exist (empty in normal cases).

### Milestone 3: Implement alignment module (prediction blocks → canonical offsets)

Goal: given a prediction-run’s block text stream, align it to `canonical_text.txt` and produce a mapping from prediction `block_index` to canonical `(start_char, end_char)`.

At the end of this milestone:
- There is a reusable library module (used by CLI and tests) that produces:
  - aligned blocks count
  - unmatched blocks count
  - canonical coverage percent (by characters and/or by lines)
  - per-block mapping records and “gap” diagnostics

Proof:
- A unit test with synthetic texts shows:
  - perfect alignment when texts match,
  - partial alignment when one side has inserted/deleted text, with sensible coverage stats.

### Milestone 4: Canonical-text evaluator for stage-block predictions

Goal: score stage-block predictions against canonical gold, without requiring block parity.

How scoring works (deterministic, documented in code and report):
1) Convert gold canonical spans → gold labels per canonical line.
   - Canonical lines are newline-delimited ranges of `canonical_text.txt` (0-based char spans).
   - For each line, the allowed gold labels are the set of labels from gold spans that overlap the line (any overlap counts).
   - If a line has no overlapping gold span, its gold label set is empty (reported), and in “strict” mode it is treated as `{OTHER}` (to mirror current default-to-OTHER behavior). This strict vs non-strict choice is a mode; default “strict” for parity with existing benchmark semantics.

2) Convert predictions → one predicted label per canonical line.
   - Align each predicted block to canonical offsets (Milestone 3).
   - For each canonical line, choose the predicted label from the aligned block that overlaps it most.
   - If no aligned block overlaps the line, predicted label is `OTHER`.

3) Compute metrics similar to stage-block eval:
   - overall accuracy
   - per-label precision/recall/F1
   - macro F1 excluding OTHER
   - worst label recall
   - plus alignment coverage metrics

At the end of this milestone:
- `eval_report.json` includes:
  - `eval_mode: "canonical_text"`
  - `unit: "canonical_line"`
  - `alignment: {...}`
  - `metrics: {...}`
  - plus aliases where needed to avoid breaking downstream consumers

Proof:
- A toy eval run produces a report where changing the prediction blockization (while keeping text same) does not change scores.

### Milestone 5: Wire canonical eval into CLI flows (opt-in, additive)

Goal: make this usable from the existing benchmark entry points without breaking the current “stage-block” mode.

At the end of this milestone:
- `cookimport labelstudio-benchmark` and `cookimport bench run` accept a new flag like:
  - `--eval-mode stage_block|canonical_text` (default `stage_block`)
- When `--eval-mode canonical_text` is used:
  - it requires canonical gold artifacts (or prints a friendly instruction to regenerate the export),
  - it runs the new canonical-text evaluator.

Proof:
- Running the same benchmark twice—once in stage-block mode, once in canonical-text mode—produces two reports with different `eval_mode` values and both succeed.

### Milestone 6: Docs + operational guidance update

Goal: update the repo docs so users understand when parity is required.

At the end of this milestone:
- The parity note is updated to explain:
  - stage-block benchmark requires parity (unchanged),
  - canonical-text benchmark does not require parity and is recommended for extractor comparisons.

Proof:
- The doc exists in-repo and mentions the new mode and how to run it.

## Concrete Steps

All commands below are intended to be run from the repository root unless stated otherwise.

### Milestone 0: Baseline + orientation

1) Find the code locations mentioned in docs.

   - Locate labelstudio export:
     rg -n "def run_labelstudio_export|labelstudio-export|freeform_span_labels" cookimport

   - Locate prediction-run artifact generation:
     rg -n "generate_pred_run_artifacts|extracted_archive.json|label_studio_tasks.jsonl" cookimport

   - Locate stage-block evaluation:
     rg -n "stage_block_predictions|overall_block_accuracy|gold_conflicts.jsonl" cookimport

2) Run help to confirm CLI surfaces exist in your tree:

     cookimport labelstudio-export --help
     cookimport labelstudio-benchmark --help
     cookimport bench run --help

3) Run the existing tests (choose what your repo uses; try these in order):

     python -m pytest -q
     pytest -q

   Expected: all tests pass (record the pass count in `Surprises & Discoveries`).

4) Capture a baseline benchmark report (old behavior).
   Use an existing gold export + source file and run the current offline benchmark:

     cookimport labelstudio-benchmark --no-upload

   If your interactive menu is the intended flow, run the “Benchmark vs Freeform Gold” single-offline mode, which is documented as offline-only.:contentReference[oaicite:13]{index=13}

   Save the output directory path. This is your “before” artifact.

### Milestone 1: Add canonical text artifacts to gold export

1) Add a helper module to build canonical text + block map.

   Create a new file (choose one and stick to it):
   - `cookimport/golden/canonical_gold.py`, or
   - `cookimport/labelstudio/canonical_gold.py` (if the repo prefers labelstudio-scoped helpers)

   Implement a function like:

   - `build_canonical_text_and_block_map(tasks: list[dict]) -> (canonical_text: str, block_map: list[dict], warnings: list[str])`

   Where `tasks` is the list of exported Label Studio tasks for this project (the same payload export already reads to produce `freeform_span_labels.jsonl`).

   The builder must:
   - Extract all focus blocks from `task["data"]["source_map"]["blocks"]` (docs say focus blocks are the offset-authoritative rows).:contentReference[oaicite:14]{index=14}
   - Deduplicate by `block_index`.
   - Detect and record conflicts: the same `block_index` appears with different `block_text`.
   - Sort by `block_index` and join block texts with a fixed separator string (use "\n\n" initially).
   - Compute `start_char`/`end_char` for each block and write those as the block map.

2) Edit `cookimport/labelstudio/export.py` (or the equivalent module your grep found).
   In the main export function (the one that writes `exports/freeform_span_labels.jsonl`), after loading tasks:
   - call the canonical builder
   - write:
     - `exports/canonical_text.txt`
     - `exports/canonical_block_map.jsonl`
     - `exports/canonical_manifest.json`

3) Add a small integrity check routine (called during export and available as a unit test):
   - Verify block map ranges are monotonic and in-bounds.
   - Verify `canonical_text[start:end]` equals the stored block text for each block entry.

4) Run `cookimport labelstudio-export ...` and verify new files exist:

   Expected directory contents (illustrative):

     exports/
       freeform_span_labels.jsonl
       freeform_segment_manifest.jsonl
       labelstudio_export.json
       summary.json
       canonical_text.txt
       canonical_block_map.jsonl
       canonical_manifest.json

### Milestone 2: Emit canonical span labels

1) Still inside the export code path where spans are resolved:
   - For each freeform span, compute canonical offsets.
   - Use the canonical block map:
     canonical_start_char = block_start_char(start_block_index) + start_offset_in_that_block
     canonical_end_char = block_start_char(end_block_index) + end_offset_in_that_block

   If export logic only has segment-local offsets:
   - Use the task’s `source_map.blocks` offsets to translate segment-local offsets to block-local offsets (this is already needed to produce `start_block_index/end_block_index` today, so reuse that logic rather than inventing new rules).

2) Write `exports/canonical_span_labels.jsonl`.
   Each row should include enough info to debug:
   - `label`
   - `start_char`, `end_char`
   - `source_hash`, `source_file`
   - `span_id` (deterministic; recommended: hash of (source_hash, label, start_char, end_char))
   - `origin` fields: original `segment_id`, original `start_block_index/end_block_index`, annotator info, etc.

3) Validate every span row:
   - Extract `canonical_text[start_char:end_char]` and compare to the span’s selected text (the text that Label Studio said was labeled).
   - If mismatch, write a row to `exports/canonical_span_label_errors.jsonl` and continue, but also surface a loud summary in stdout (and in manifest warnings).

4) Add unit tests.
   Create a minimal fixture that represents:
   - two overlapping tasks sharing blocks,
   - one labeled span inside one block,
   - one labeled span crossing a newline within a block (optional),
   - confirm canonical offsets map back to the same substring.

### Milestone 3: Alignment module

1) Create a new module for alignment, e.g.:
   - `cookimport/bench/canonical_align.py`

2) Define the input contract:
   - canonical: `canonical_text.txt` + its derived canonical lines
   - prediction-run blocks: read from `extracted_archive.json` (preferred; docs say it is available in prediction-run roots).:contentReference[oaicite:15]{index=15}

3) Implement alignment as a monotonic mapping (preserves order):
   - Maintain a moving pointer into canonical text.
   - For each prediction block text in increasing `block_index`, try to find it in canonical text at or after the pointer.
   - Use a length-preserving normalization for matching only (character-wise):
     - map all whitespace characters to ' '
     - map common unicode quotes/dashes to ASCII equivalents
     - lowercase
     This keeps indices valid against canonical text because the normalized canonical is the same length as canonical.
   - First try exact substring search in normalized space.
   - If not found, attempt a bounded fuzzy fallback:
     - search within a window of canonical text (e.g., next 20k chars)
     - use `difflib.SequenceMatcher` to find the longest match and accept only if match quality exceeds a threshold
   - Record for each block:
     - `matched: bool`
     - `canonical_start_char`, `canonical_end_char`
     - `match_score` and `match_kind` ("exact" vs "fuzzy" vs "unmatched")

4) Compute alignment coverage:
   - fraction of canonical characters covered by matched blocks
   - fraction of canonical lines that have any matched block overlap
   - fraction of prediction blocks matched

5) Add unit tests with synthetic canonical and prediction texts:
   - identical streams (100% coverage)
   - one inserted block on prediction side (some unmatched blocks, still high canonical coverage)
   - one deleted block on prediction side (gap in canonical coverage)

### Milestone 4: Canonical-text evaluator

1) Create evaluator module, e.g.:
   - `cookimport/bench/eval_canonical_text.py`

2) Implement:
   - load gold canonical artifacts
   - load prediction-run stage-block predictions (`stage_block_predictions.json`)
   - load prediction-run blocks (`extracted_archive.json`)
   - align blocks to canonical
   - compute canonical lines (split by "\n"; keep ranges)
   - project gold spans → allowed labels per line
   - project aligned predicted blocks + stage labels → one predicted label per line
   - compute metrics

3) Output artifacts:
   - `eval_report.json`:
     include:
       - `eval_mode: "canonical_text"`
       - `unit: "canonical_line"`
       - `alignment` stats
       - `metrics` (overall accuracy, per-label PRF1, macro_f1_excluding_other, worst recall)
     also include compatibility aliases if the rest of the tooling expects specific keys:
       - set `overall_block_accuracy` = `overall_line_accuracy`
   - `eval_report.md`: human-readable summary including an “Alignment / Coverage” section.
   - Diagnostics JSONL (new names, plus legacy aliases if you already do that pattern):
     - `missed_gold_lines.jsonl` (gold-labeled lines predicted as OTHER or wrong)
     - `wrong_label_lines.jsonl`
     - `unmatched_pred_blocks.jsonl` (prediction blocks that could not be aligned)
     - optionally: `alignment_gaps.jsonl` describing canonical ranges with no matched prediction coverage

4) Add a toy CLI runner for fast manual validation (optional but recommended):
   - `cookimport bench eval-canonical-text --pred-run <dir> --gold-export <dir> --out <dir>`

5) Add tests that run evaluator on a tiny in-repo toy dataset and assert metric numbers.

### Milestone 5: CLI wiring (opt-in)

1) Update `cookimport/cli.py`:
   - Extend `labelstudio-benchmark` and `bench run` argument parsing to accept:
     - `--eval-mode stage_block|canonical_text`
   - Default remains `stage_block` to preserve current behavior.

2) In the benchmark code path:
   - If `eval_mode == canonical_text`:
     - require canonical gold files exist; if not, print:
       “Gold export missing canonical_text.txt. Re-run labelstudio-export with current version.”
     - call canonical evaluator instead of stage-block evaluator.

3) Ensure interactive menus (if any) can still run the old path unchanged.
   Add canonical-text mode only if it’s easy; otherwise keep it non-interactive for the first iteration.

4) Run:
   - `cookimport labelstudio-benchmark --help` and confirm flag appears.
   - one benchmark run in each mode.

### Milestone 6: Docs update

1) Update `docs/understandings/2026-02-25_19.14.33-benchmark-gold-extractor-parity.md` (or the consolidated location your repo uses) to say:
   - Stage-block mode: still requires extractor/block parity.
   - Canonical-text mode: does not; use it when comparing extractors.

2) Update bench docs under `docs/07-bench` to describe the new mode and its outputs (alignment coverage section, etc). Docs summary notes `docs/07-bench` as the source of truth for current behavior.:contentReference[oaicite:16]{index=16}

## Validation and Acceptance

### Acceptance criteria (end-to-end)

1) Gold export emits canonical artifacts.
   - Run `cookimport labelstudio-export ...`
   - Confirm `exports/canonical_text.txt`, `exports/canonical_block_map.jsonl`, `exports/canonical_span_labels.jsonl`, and `exports/canonical_manifest.json` exist.
   - Confirm canonical span substring validation reports “0 mismatches” for a healthy project.

2) Canonical benchmark runs without extractor parity.
   - Choose a gold export created with extractor A.
   - Run `cookimport labelstudio-benchmark --no-upload --eval-mode canonical_text` while configuring predictions to use extractor B (or a different blockization).
   - Expected:
     - Benchmark completes successfully.
     - `eval_report.md` contains an “Alignment / Coverage” section showing non-zero coverage numbers.
     - Per-label metrics are computed; they may degrade due to extraction differences, but they must not collapse purely because block indices drift.

3) Regression: stage-block benchmark remains unchanged by default.
   - Run `cookimport labelstudio-benchmark --no-upload` without the new flag.
   - Expected: output matches baseline behavior and still uses stage-block eval (including missing-gold default OTHER semantics).:contentReference[oaicite:17]{index=17}

### Test expectations

- Run your project’s test suite (record the command and pass count as you discover it in Milestone 0).
- Add at least:
  - one unit test for canonical text/map generation,
  - one unit test for canonical span conversion validation,
  - one unit test for alignment,
  - one unit test for canonical evaluator metrics on a toy dataset.

Each new test should fail before the implementation and pass after.

## Idempotence and Recovery

- `labelstudio-export` should be safe to re-run:
  - If export dir already exists, either overwrite atomically (write to temp + rename) or require `--overwrite`.
  - Canonical artifacts must be deterministic for the same underlying Label Studio export payload.

- Canonical benchmark runs should be safe to re-run:
  - Output directories are timestamped in this repo’s conventions (YYYY-MM-DD_HH.MM.SS).:contentReference[oaicite:18]{index=18}
  - If you add `--out-dir`, support `--overwrite` or create a fresh timestamped subdir.

- Rollback:
  - If canonical mode has issues, users can revert to stage-block eval simply by not using `--eval-mode canonical_text`.
  - No existing files are removed; canonical artifacts are additive.

## Notes and References (inputs used to build this plan)

- Current benchmark scoring surface and missing-gold default behavior: docs summary section on stage-block evaluation.:contentReference[oaicite:19]{index=19}
- Prediction-run artifacts are produced by `generate_pred_run_artifacts` and include `extracted_archive.json`.:contentReference[oaicite:20]{index=20}
- Documented extractor-parity failure mode example: benchmark-vs-gold extractor parity note.
- ExecPlan formatting and required sections: `PLANS.md`.:contentReference[oaicite:22]{index=22}:contentReference[oaicite:23]{index=23}

## Revision Notes

- 2026-02-26: Updated progress/decisions/outcomes to reflect implementation status after wiring canonical-text eval into `labelstudio-benchmark` and forcing canonical-text mode for interactive all-method runs; kept remaining bench-suite wiring explicitly marked as pending.
