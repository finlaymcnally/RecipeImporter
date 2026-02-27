---
summary: "ExecPlan to reduce stage and stage-block prediction runtime by making non-scoring artifacts optional while keeping scoring outputs identical."
read_when:
  - "When implementing benchmark speed plan speed-5"
  - "When changing stage markdown outputs or labelstudio-benchmark prediction artifact writes"
  - "When tuning stage-block runtime without changing scoring behavior"
---

# Reduce stage-like write overhead by making non-scoring artifacts optional

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes ExecPlan rules at `docs/PLANS.md`. Maintain this document in accordance with that file.

## Purpose / Big Picture

`cookimport stage` and offline stage-block benchmark prediction runs spend measurable time writing human-facing markdown summaries and task JSONL artifacts that are not part of stage-block scoring. This plan introduces explicit, safe toggles so those non-scoring artifacts can be skipped when speed is the priority.

After this change, users can run:

    cookimport stage ... --no-write-markdown
    cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks ... --no-write-markdown --no-write-labelstudio-tasks

and get faster write phases while preserving stage evidence (`stage_block_predictions.json`), benchmark metrics, and evaluation diagnostics.

## Progress

- [x] (2026-02-26_20.25.36) Rebuilt `docs/plans/speed-5.md` as a code-verified ExecPlan with required front matter and current repository context.
- [ ] Capture baseline stage and stage-block timing/artifact evidence on one representative source.
- [ ] Add `write_markdown` toggles to staging writer surfaces and thread through stage + merge call paths.
- [ ] Add `write_markdown` and `write_label_studio_tasks` controls to prediction-run generation (`generate_pred_run_artifacts`) and processed-output writing.
- [ ] Expose toggles in `labelstudio-benchmark` (and bench config plumbing where appropriate) with compatibility-safe defaults.
- [ ] Update run manifests and helper logic so intentionally skipped task JSONL artifacts are represented explicitly and never mistaken for failures.
- [ ] Add regression tests for toggle behavior and scoring parity.
- [ ] Run focused pytest suites plus one manual A/B run and complete retrospective.

## Surprises & Discoveries

- Observation: Incremental output stats collection is already implemented and used broadly; there is no remaining post-write directory scan to remove.
  Evidence: `cookimport/staging/writer.py::OutputStats`, plus call sites in `cookimport/cli_worker.py::stage_one_file`, `cookimport/cli.py::_merge_split_jobs`, and `cookimport/labelstudio/ingest.py::_write_processed_outputs`.

- Observation: Prediction-run archive construction is already single-pass for current flow.
  Evidence: `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts` computes `archive = build_extracted_archive(...)` once, then reuses `archive` for task generation and `extracted_archive.json` writing.

- Observation: Stage-block scoring depends on `stage_block_predictions.json` and `extracted_archive.json`, not `label_studio_tasks.jsonl`.
  Evidence: `cookimport/bench/eval_stage_blocks.py::evaluate_stage_blocks` signature and loaders consume `stage_predictions_json` + `extracted_blocks_json`.

- Observation: Bench suite currently reads `label_studio_tasks.jsonl` only for noise/cost side artifacts; missing tasks do not block scoring.
  Evidence: `cookimport/bench/runner.py::_load_pred_dicts` returns `[]` when tasks file is missing, and `run_suite` still evaluates from stage predictions + extracted archive.

## Decision Log

- Decision: Narrow speed-5 scope to non-scoring artifact toggles (markdown summaries and task JSONL), not conversion/scoring algorithm changes.
  Rationale: This gives low-risk runtime wins while preserving evaluator correctness and established output contracts.
  Date/Author: 2026-02-26 / Codex

- Decision: Keep command defaults backward-compatible for initial rollout (`write_markdown=True`, `write_label_studio_tasks=True`) and require explicit opt-out for speed mode.
  Rationale: Existing workflows and tests assume these artifacts exist; opt-in speed mode avoids surprise regressions.
  Date/Author: 2026-02-26 / Codex

- Decision: Treat missing task JSONL in opt-out mode as intentional state, represented in manifest metadata.
  Rationale: Distinguishes "artifact intentionally skipped" from "artifact generation failed" and simplifies downstream debugging.
  Date/Author: 2026-02-26 / Codex

## Outcomes & Retrospective

Pending implementation. Populate with before/after timings, parity evidence, and any workflow tradeoffs observed.

## Context and Orientation

Stage and benchmark prediction paths share writer-heavy behavior:

- Stage command path:
  - `cookimport/cli.py::stage`
  - `cookimport/cli_worker.py::stage_one_file`
  - `cookimport/cli.py::_merge_split_jobs` for split merge writes.

- Shared writer module:
  - `cookimport/staging/writer.py` writes JSON/JSONL and markdown artifacts.
  - Markdown outputs currently include `sections.md`, `tips.md`, `topic_candidates.md`, `chunks.md`, and `tables.md`.

- Benchmark prediction generation:
  - `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts`
  - `cookimport/labelstudio/ingest.py::_write_processed_outputs`
  - `cookimport/cli.py::labelstudio_benchmark` wires no-upload prediction generation.
  - `cookimport/bench/pred_run.py::build_pred_run_for_source` wires bench suite prediction runs.

Important definitions for this plan:

- Scoring artifacts: files required to compute stage-block metrics (`stage_block_predictions.json`, `extracted_archive.json`, gold freeform spans).
- Non-scoring artifacts: helpful but optional files for human review or upload (`*.md` summaries, `label_studio_tasks.jsonl` in offline mode).
- Accuracy-neutral: same stage-block metrics and same stage block labels for identical inputs/configuration.

## Plan of Work

Implementation proceeds in milestones so each change is independently verifiable.

### Milestone 1: Baseline evidence and acceptance contract

Capture one representative baseline for:

- `cookimport stage` write timings (`timing.writing_seconds`, optional write checkpoints),
- `cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks` timings (`timing.prediction_seconds`, `timing.checkpoints.processed_output_write_seconds`),
- semantic output digests for selected JSON artifacts.

Acceptance for this milestone is concrete before-state evidence recorded in `Artifacts and Notes`.

### Milestone 2: Markdown toggle plumbing for stage-style writers

Add `write_markdown: bool = True` controls to markdown-emitting writer functions and thread them through stage paths:

- `cookimport/staging/writer.py`:
  - `write_section_outputs`
  - `write_tip_outputs`
  - `write_topic_candidate_outputs`
  - `write_chunk_outputs`
  - `write_table_outputs`

- Stage command wiring:
  - Add `--write-markdown/--no-write-markdown` to `cookimport/cli.py::stage`.
  - Pass the resolved value through worker and merge write paths (`cli_worker.py` and `cli.py::_merge_split_jobs`).

Preserve default behavior (`True`) so existing outputs are unchanged without the new opt-out flag.

Acceptance for this milestone is passing stage output-structure and staging writer tests with existing defaults, plus new coverage for `--no-write-markdown`.

### Milestone 3: Optional task JSONL and processed-output markdown in pred-run generation

Add prediction-run toggles:

- `generate_pred_run_artifacts(..., write_markdown: bool = True, write_label_studio_tasks: bool = True, ...)`
- `_write_processed_outputs(..., write_markdown: bool = True, ...)`

Wire these through:

- `cookimport/cli.py::labelstudio_benchmark` in no-upload path with explicit flags:
  - `--write-markdown/--no-write-markdown`
  - `--write-labelstudio-tasks/--no-write-labelstudio-tasks`
- `cookimport/bench/pred_run.py::build_pred_run_for_source` via config keys so bench suites can opt in to speed mode without changing global defaults.

Manifest/report updates:

- In prediction `manifest.json` and `run_manifest.json`, emit explicit booleans for task/markdown write policy and include task artifact path only when written.
- Ensure helper code that resolves stage predictions/extracted archive does not assume tasks are present.

Acceptance for this milestone is successful offline stage-block runs with tasks skipped, unchanged scoring metrics, and clear manifest signaling.

### Milestone 4: Regression tests, docs updates, and validation runs

Tests to add or update:

- `tests/staging/test_section_outputs.py` and `tests/staging/test_tip_writer.py` for markdown toggle behavior.
- `tests/cli/test_cli_output_structure.py` for `stage --no-write-markdown` output expectations.
- `tests/labelstudio/test_labelstudio_ingest_parallel.py` for `generate_pred_run_artifacts` task toggle and manifest fields.
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` for no-upload benchmark wiring with toggles.
- `tests/staging/test_run_manifest_parity.py` for manifest parity when tasks are intentionally skipped.
- `tests/bench/test_bench_progress.py` (if needed) to guard bench behavior when task JSONL is absent.

Docs updates:

- `docs/05-staging/05-staging_readme.md` for stage markdown toggle.
- `docs/07-bench/07-bench_README.md` and `docs/07-bench/runbook.md` for optional offline task JSONL behavior.
- `docs/02-cli/02-cli_README.md` for new command flags and defaults.

Acceptance for this milestone is green targeted tests, manual A/B evidence, and updated docs.

## Concrete Steps

Run from repository root:

1. Prepare environment:

    source .venv/bin/activate
    python -m pip install -e .[dev]

2. Capture baseline runs:

    cookimport stage data/input/<source>.epub --out data/output
    cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks --source-file data/input/<source>.epub --gold-spans data/golden/<gold>/exports/freeform_span_labels.jsonl --overwrite

3. Implement milestone 2 writer and stage CLI toggle changes.

4. Implement milestone 3 pred-run/benchmark toggle changes.

5. Run focused tests:

    pytest -q tests/staging/test_section_outputs.py tests/staging/test_tip_writer.py tests/cli/test_cli_output_structure.py
    pytest -q tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/staging/test_run_manifest_parity.py
    pytest -q tests/bench/test_eval_stage_blocks.py tests/bench/test_bench_progress.py

6. Capture A/B comparison for no-upload stage-block benchmark:

    cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks --source-file data/input/<source>.epub --gold-spans data/golden/<gold>/exports/freeform_span_labels.jsonl --overwrite
    cookimport labelstudio-benchmark --no-upload --eval-mode stage-blocks --source-file data/input/<source>.epub --gold-spans data/golden/<gold>/exports/freeform_span_labels.jsonl --overwrite --no-write-markdown --no-write-labelstudio-tasks

7. Record timing/metric parity evidence in this plan and complete retrospective.

## Validation and Acceptance

Acceptance requires all of the following:

- Correctness parity:
  - stage-block metrics are identical before/after for identical inputs.
  - `stage_block_predictions.json` payloads remain semantically identical when markdown/tasks toggles change.

- Behavior parity by default:
  - running commands without new flags keeps current artifact layout and manifests.

- Opt-out behavior:
  - `--no-write-markdown` omits markdown outputs only.
  - `--no-write-labelstudio-tasks` omits `label_studio_tasks.jsonl` but still produces evaluable prediction artifacts.

- Performance signal:
  - write-focused timing fields improve (or at least do not regress) in opt-out runs on representative input.

- Tests:
  - targeted pytest suites pass in local venv.

## Idempotence and Recovery

All changes are additive and retry-safe:

- Flags are explicit and reversible on the next run.
- Default behavior remains available without rollback.
- If any downstream consumer still expects tasks markdown unconditionally, rerun with defaults (`--write-markdown --write-labelstudio-tasks`) while fixing that consumer.

## Artifacts and Notes

Populate during implementation:

- Baseline stage timing excerpt (`writing_seconds`).
- Baseline and opt-out stage-block benchmark timing excerpts (`prediction_seconds`, `processed_output_write_seconds`).
- Metrics parity diff summary.
- Manifest snippet showing explicit task/markdown write booleans.

## Interfaces and Dependencies

Planned interface changes:

- `cookimport/staging/writer.py`
  - Add `write_markdown: bool = True` to markdown-emitting writer functions.

- `cookimport/cli.py::stage`
  - Add `--write-markdown/--no-write-markdown` option and thread to worker/merge writers.

- `cookimport/labelstudio/ingest.py`
  - Add `write_markdown: bool = True` to `_write_processed_outputs`.
  - Add `write_markdown: bool = True` and `write_label_studio_tasks: bool = True` to `generate_pred_run_artifacts`.
  - Emit manifest metadata for whether optional artifacts were written.

- `cookimport/cli.py::labelstudio_benchmark`
  - Add `--write-markdown/--no-write-markdown`.
  - Add `--write-labelstudio-tasks/--no-write-labelstudio-tasks`.
  - Pass toggles only through no-upload prediction generation path.

- `cookimport/bench/pred_run.py`
  - Pass optional config keys for new toggle values.

Dependency policy:

- No new third-party dependencies are needed for this plan.
- Keep changes limited to control flow and optional artifact writes.

---

Plan change note:

- 2026-02-26_20.25.36: Rebuilt speed-5 as a front-matter-compliant, code-verified ExecPlan. Removed outdated work items that were already implemented (incremental output stats and single-pass archive build), and narrowed implementation scope to optional non-scoring artifact writes.
