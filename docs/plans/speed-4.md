---
summary: "ExecPlan to split labelstudio-benchmark prediction/evaluation into explicit stages with reusable prediction-record artifacts."
read_when:
  - "When implementing benchmark speed plan speed-4"
  - "When changing labelstudio-benchmark execution mode, evaluate-only flows, or prediction-record contracts"
---

# Split labelstudio-benchmark into explicit prediction/evaluation stages

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS guidance is checked into the repo at `docs/PLANS.md`, and this plan is maintained in accordance with that file.

## Purpose / Big Picture

`cookimport labelstudio-benchmark` already had two conceptual phases (generate predictions, then evaluate), but there was no durable stage contract that let the evaluator run independently from a saved prediction stage artifact. This made replaying evaluation and experimenting with execution orchestration harder than necessary.

After this change, benchmark runs can now emit/read a JSONL `PredictionRecord` artifact, run evaluate-only from that artifact, and select a stage-orchestrated execution mode (`legacy` or `pipelined`) without changing benchmark scoring behavior.

## Progress

- [x] (2026-02-27_00.10.00) Drafted initial speed-4 ExecPlan.
- [x] (2026-02-27_02.10.00) Replaced placeholders with repo-specific surfaces (`cookimport/cli.py::labelstudio_benchmark`, `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts`, `cookimport/bench/eval_stage_blocks.py`, `cookimport/bench/eval_canonical_text.py`).
- [x] (2026-02-27_02.25.00) Added `cookimport/bench/prediction_records.py` with versioned schema validation + JSONL read/write utilities (`schema_version=1`).
- [x] (2026-02-27_02.40.00) Added `labelstudio-benchmark` stage controls: `--execution-mode`, `--predictions-out`, `--predictions-in`.
- [x] (2026-02-27_02.40.00) Added evaluate-only flow (`--predictions-in`) that skips prediction generation/upload and reuses saved prediction-stage paths.
- [x] (2026-02-27_02.40.00) Added queue-backed staged orchestration path for `--execution-mode pipelined`.
- [x] (2026-02-27_02.55.00) Added/updated tests:
  - `tests/bench/test_prediction_records.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py`
  - `tests/conftest.py` marker/smoke mapping.
- [x] (2026-02-27_03.05.00) Ran focused validation:
  - `pytest -q tests/bench/test_prediction_records.py tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- [ ] Capture one real benchmark before/after timing sample for `legacy` vs `pipelined` on a representative source/gold pair and store evidence snippets.

## Surprises & Discoveries

- Observation: Runtime already had a natural two-stage boundary at the command level: prediction artifacts are fully materialized before evaluation starts.
  Evidence: `cookimport/cli.py::labelstudio_benchmark` (pre-change flow and current staged bundle helpers).

- Observation: The first stable contract for replay is run-level (single benchmark record), not per-example streaming.
  Evidence: Evaluators consume run artifacts (`stage_block_predictions.json` + `extracted_archive.json`) instead of online per-example model outputs.

- Observation: Run metadata can include `Path` objects in some branches; prediction-record serialization needed explicit JSON-safe normalization.
  Evidence: failing test fixed in `_benchmark_prediction_record_from_bundle` with path-safe conversion.

## Decision Log

- Decision: Implement a durable run-level `PredictionRecord` contract in `cookimport/bench/prediction_records.py` with strict required keys.
  Rationale: Gives evaluate-only replay now, while keeping surface minimal and deterministic.
  Date/Author: 2026-02-27 / Codex

- Decision: Add `--predictions-in` and `--predictions-out` to `labelstudio-benchmark` rather than introducing a separate command.
  Rationale: Keeps UX centralized in the existing benchmark command and preserves current defaults.
  Date/Author: 2026-02-27 / Codex

- Decision: Keep default mode as `legacy`; add `--execution-mode pipelined` as opt-in.
  Rationale: No behavior surprise for existing workflows while enabling staged orchestration path incrementally.
  Date/Author: 2026-02-27 / Codex

- Decision: Forbid using `--predictions-in` and `--predictions-out` together in one invocation.
  Rationale: Keeps semantics explicit and avoids ambiguous read/write precedence in this initial rollout.
  Date/Author: 2026-02-27 / Codex

## Outcomes & Retrospective

Implemented outcomes:

- `labelstudio-benchmark` now supports:
  - `--execution-mode legacy|pipelined`
  - `--predictions-out <jsonl>` (emit prediction-stage record)
  - `--predictions-in <jsonl>` (evaluate-only from saved prediction-stage record)
- New prediction-record schema and IO utilities are fully covered by targeted tests.
- Existing benchmark helper suite remains green in focused regression coverage.

Remaining gap:

- Real workload timing evidence for `legacy` vs `pipelined` is still pending. Current implementation validates staging behavior and replayability, but this plan should still be updated with measured before/after runtime on a representative source.

## Context and Orientation

Primary code surfaces:

- `cookimport/cli.py`
  - `labelstudio_benchmark(...)` command entrypoint.
  - New helpers:
    - `_build_prediction_bundle_from_import_result(...)`
    - `_build_prediction_bundle_from_record(...)`
    - `_benchmark_prediction_record_from_bundle(...)`
- `cookimport/labelstudio/ingest.py`
  - `generate_pred_run_artifacts(...)` prediction-stage artifact generation.
- `cookimport/bench/eval_stage_blocks.py`
  - stage-block evaluator.
- `cookimport/bench/eval_canonical_text.py`
  - canonical-text evaluator.
- `cookimport/bench/prediction_records.py`
  - new `PredictionRecord` schema, validation, and JSONL IO.

## Plan of Work

Completed implementation sequence:

1. Added a strict run-level prediction-record data contract and atomic JSONL writer/reader.
2. Refactored benchmark prediction resolution into explicit bundle helpers so both generated and record-driven runs share the same evaluation wiring.
3. Wired new CLI options for execution mode and prediction-record read/write.
4. Added queue-backed staged orchestration branch for `pipelined` mode.
5. Added tests for record roundtrip/validation and benchmark command behavior.

## Concrete Steps

Run from repository root with the project venv active.

Predict + evaluate (legacy) and emit a record:

    cookimport labelstudio-benchmark \
      --no-upload \
      --eval-mode stage-blocks \
      --execution-mode legacy \
      --source-file data/input/<book>.epub \
      --gold-spans data/golden/<run>/exports/freeform_span_labels.jsonl \
      --predictions-out /tmp/benchmark_preds.jsonl

Evaluate-only from prior prediction record:

    cookimport labelstudio-benchmark \
      --eval-mode stage-blocks \
      --source-file data/input/<book>.epub \
      --gold-spans data/golden/<run>/exports/freeform_span_labels.jsonl \
      --predictions-in /tmp/benchmark_preds.jsonl

Run staged queue path:

    cookimport labelstudio-benchmark \
      --no-upload \
      --eval-mode canonical-text \
      --execution-mode pipelined \
      --source-file data/input/<book>.epub \
      --gold-spans data/golden/<run>/exports/freeform_span_labels.jsonl

## Validation and Acceptance

Implemented acceptance checks:

- `PredictionRecord` JSONL roundtrip/validation tests pass.
- `--predictions-in` evaluate-only mode skips prediction generation/upload and still evaluates using stored artifact paths.
- `legacy` and `pipelined` modes produce equivalent report payloads (timing removed before equality assert in test).
- Focused regression command passed:

    pytest -q tests/bench/test_prediction_records.py tests/labelstudio/test_labelstudio_benchmark_helpers.py

## Idempotence and Recovery

- `--predictions-out` uses atomic temp-file replacement; reruns overwrite cleanly.
- `--predictions-in` is replay-safe as long as referenced artifact paths still exist.
- If a prediction-record path is invalid/missing, command fails fast with a clear error and can be retried after regenerating records.

## Artifacts and Notes

Key artifacts now written by benchmark runs (when enabled):

- prediction record output:
  - `prediction_record_output_jsonl` in `run_manifest.json` artifacts.
- prediction record input (evaluate-only):
  - `prediction_record_input_jsonl` in `run_manifest.json` artifacts.

## Interfaces and Dependencies

New module:

- `cookimport/bench/prediction_records.py`
  - `PredictionRecord`
  - `make_prediction_record(...)`
  - `write_prediction_records(path, records)`
  - `read_prediction_records(path)`
  - `read_single_prediction_record(path)`

Updated benchmark CLI interface:

- `cookimport labelstudio-benchmark`
  - `--execution-mode legacy|pipelined`
  - `--predictions-out <path>`
  - `--predictions-in <path>`

Plan change note:

- 2026-02-27_03.10.00: Rebuilt speed-4 as a code-verified, front-matter-compliant ExecPlan reflecting implemented staged benchmark execution and prediction-record replay support.
