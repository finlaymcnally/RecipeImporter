# Split “predict” and “evaluate” into two pipelined stages

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root. If the repository does not currently contain `PLANS.md`, add it (by copying the provided `PLANS.md` into the repo) before starting implementation so future contributors have the same rules of the road.

## Purpose / Big Picture

Today, the evaluation flow likely does “predict + evaluate” in one tightly coupled loop: for each example, call the model to produce an output, then immediately compute metrics (or vice versa). The goal of this change is to split these concerns into two explicit stages, connected by a pipeline:

- A **prediction stage** that turns input examples into model outputs (predictions) and emits a durable, replayable stream of `PredictionRecord`s.
- An **evaluation stage** that consumes `PredictionRecord`s, joins them with ground-truth labels, and computes metrics/reports.

After this change, a user can:
1) Run an evaluation in “pipelined” mode and see the same final metrics as before (no accuracy regression), while prediction and evaluation overlap in time (lower wall-clock latency when both are non-trivial).
2) Optionally reuse saved predictions to re-run evaluation without re-calling the model, proving that predict and evaluate are truly decoupled.

You can see it working by running the same evaluation twice: once in legacy mode and once in pipelined mode, and confirming:
- The printed/serialized metrics match exactly (or match within an explicitly documented tolerance, if the existing evaluation is non-deterministic).
- A predictions artifact file (JSONL) is produced and can be used to run “evaluate-only” with identical results.

## Progress

- [x] (2026-02-27 00:10Z) Drafted ExecPlan for splitting predict/evaluate into pipelined stages.
- [ ] Capture baseline behavior (commands + outputs) for a small, deterministic evaluation run; record the exact invocation in this plan. (remaining: representative real-workload timing artifact for `legacy` vs `pipelined`)
- [x] (2026-02-27 11:45Z) Identify and lock concrete benchmark entrypoints in `cookimport/cli.py` (`labelstudio_benchmark`, `predict_stage`, `evaluate_stage`, `run_legacy`, `run_pipelined`).
- [x] Introduce `PredictionRecord` schema + JSONL read/write utilities and add round-trip tests.
- [x] Refactor prediction logic so benchmark prediction can run as an explicit stage (`predict_stage`) that emits deterministic per-block records.
- [x] Refactor evaluation wiring so benchmark evaluation can run as an explicit stage (`evaluate_stage`) consuming replayed prediction-record artifacts.
- [x] Implement bounded in-process pipeline runner (`run_pipelined`) with producer/consumer queue, EOS signaling, and error propagation.
- [x] Wire pipelined runner into benchmark CLI behind `--execution-mode legacy|pipelined|predict-only` while keeping legacy mode intact.
- [x] Add equivalence coverage: legacy vs pipelined report payload parity on deterministic stubbed benchmark tests.
- [x] Add evaluate-only from predictions path and tests for both per-block records and legacy pointer record compatibility.
- [x] Update docs/help text for prediction-record contract and execution modes.

## Surprises & Discoveries

- Observation: The historical speed1-4 implementation wrote a single run-pointer record, so evaluate-only replay depended on external stage/extracted artifact files remaining in place.
  Evidence: `docs/understandings/2026-02-27_10.51.52-speed1-4-implementation-gap-audit.md` (D3/D4/D6), plus the pre-change helper path that required exactly one record and path fields (`read_single_prediction_record` + `_prediction_record_path_value`).

- Observation: Real prediction/evaluation overlap inside this benchmark is bounded by when stage artifacts become available; the practical near-term improvement is bounded producer/consumer record flow + canonical prewarm overlap, with parity preserved.
  Evidence: Updated stage runners in `cookimport/cli.py` (`run_pipelined`, `predict_stage`, `evaluate_stage`) and parity tests in `tests/labelstudio/test_labelstudio_benchmark_helpers.py`.

## Decision Log

- Decision: Use a durable `PredictionRecord` stream (JSON Lines / JSONL) as the boundary between stages.
  Rationale: A line-delimited file is easy to generate incrementally, easy to inspect, can be reused for “evaluate-only,” and works as a stable contract even if we later split stages into separate processes or machines.
  Date/Author: 2026-02-27 / plan author

- Decision: Preserve accuracy by reusing the existing prediction and metric computation code paths; only reorganize control flow.
  Rationale: We want a structural performance/operability improvement without semantic drift. The safest refactor is extraction and orchestration, not rewriting scoring rules.
  Date/Author: 2026-02-27 / plan author

- Decision: Implement pipelining with a bounded queue (backpressure) using the project’s existing concurrency style (async vs threads), chosen during Milestone 0 discovery.
  Rationale: Matching the repo’s current style minimizes invasive rewrites and reduces the chance of subtle behavioral changes.
  Date/Author: 2026-02-27 / plan author

- Decision: Use per-block prediction records (`schema_kind=stage-block.v1`) as the default replay contract, with deterministic `example_id`/`example_index` tied to block index.
  Rationale: This closes the OG per-example boundary requirement while keeping scoring semantics unchanged by reconstructing evaluator inputs from record payloads.
  Date/Author: 2026-02-27 / implementation pass

- Decision: Keep evaluate-only backward compatibility for legacy single-record run-pointer artifacts.
  Rationale: Existing artifacts should remain replayable while new runs move to per-block records.
  Date/Author: 2026-02-27 / implementation pass

## Outcomes & Retrospective

2026-02-27 closure update:

- Achieved:
  - explicit stage/runner APIs in benchmark CLI (`predict_stage`, `evaluate_stage`, `run_legacy`, `run_pipelined`),
  - per-block prediction-record emission on `--predictions-out`,
  - evaluate-only replay from per-block records (with deterministic join/contiguity checks),
  - legacy run-pointer replay compatibility,
  - parity + overlap-focused regression tests.
- Remaining:
  - representative real-workload timing artifact comparing `legacy` vs `pipelined` on matched inputs.
- Lesson:
  - preserving metric semantics while changing stage boundaries is safest when record replay reconstructs the existing evaluator input contract rather than rewriting metric internals.

## Context and Orientation

You are a newcomer to this repository. Before you change anything, you must locate and name the current “predict” and “evaluate” logic precisely so the rest of this plan can refer to concrete files and functions.

Definitions used in this plan:

A **dataset example** is one unit of evaluation input (for example: a prompt, a record with fields, or an input/label pair). Examples must have a stable identity so predictions can be joined back to the right labels.

A **prediction** is the model’s output for a dataset example. This might be a string, a JSON object, a class label, or another structured output.

A **metric** is a rule that scores predictions against ground truth (for example: exact match, F1, BLEU, accuracy, pass@k). Some metrics can be updated one example at a time (“streaming metrics”). Others require seeing all examples (“batch metrics”). This plan supports both by allowing the evaluation stage to keep internal state and finalize at the end.

A **pipeline** is a producer/consumer design where stage 1 (predict) produces items into a buffer while stage 2 (evaluate) consumes them concurrently. A **bounded** buffer means it has a maximum size; if the consumer falls behind, the producer blocks instead of accumulating unbounded memory. This is “backpressure.”

### Repo-specific placeholders you must resolve in Milestone 0

Throughout this plan, you will see placeholders like `<EVAL_ENTRYPOINT_PATH>`. In Milestone 0, you will replace them with real paths and symbol names from the repo, and then update this plan accordingly (and commit the plan edit as its own commit). Do not proceed with later milestones until the placeholders are resolved.

Placeholders to resolve:

- `<EVAL_ENTRYPOINT_PATH>`: the primary script/module/command that runs evaluation end-to-end.
- `<PREDICT_CALLSITE>`: where the model is called to produce an output for one example (function name + file).
- `<METRICS_CALLSITE>`: where metrics are computed/aggregated (function name + file).
- `<DATASET_ITERATOR>`: the code that yields examples (function/class name + file).
- `<CURRENT_OUTPUT_FORMAT>`: how results are reported (stdout, JSON file, CSV, etc.), and which code writes it.

## Plan of Work

### Milestone 0: Discovery, baseline capture, and plan concretization

At the end of this milestone, you will know exactly where prediction and evaluation happen today, you will have a “baseline run” you can repeat, and this ExecPlan will be updated to replace all placeholders with real file paths and function names.

Work:

First, identify the language/toolchain and how tests are run.

Then locate the evaluation entrypoint and the predict/evaluate logic by searching for terms like “predict”, “evaluate”, “metrics”, “score”, “accuracy”, and the CLI argument parsing.

Finally, run a small evaluation (or a dedicated unit/integration test) that is deterministic enough to compare legacy vs pipelined. Save the exact command and its resulting metrics output (or output file) into this plan as the baseline.

Promotion criteria (how you prove Milestone 0 is done):

- This plan contains real paths and symbol names instead of placeholders.
- You can run one command that produces a stable “baseline metrics” output.

### Milestone 1: Introduce `PredictionRecord` and durable prediction artifacts

At the end of this milestone, the repo will contain a small, well-tested module that defines a stable prediction record schema and can write/read a stream of predictions as JSONL.

Work:

Define a minimal schema that is sufficient to join predictions back to examples and reproduce evaluation without re-running prediction. Keep it narrow; do not attempt to dump the entire world into it.

The record must contain:

- `schema_version`: integer, starting at 1.
- `example_id`: string unique identifier. If the dataset already has an id, use it. Otherwise derive one deterministically from `(dataset_name, split, example_index)` or a stable hash of normalized input fields.
- `example_index`: integer index in the dataset iteration order (for deterministic ordering and debugging).
- `prediction`: the model output in a JSON-serializable form.
- `predict_meta`: a small dict for run metadata needed to interpret predictions (for example: model name, temperature, decoding parameters, prompt template version). Keep it focused and stable.

Add writer/reader helpers:

- Writer streams line-by-line and flushes periodically; it should write to a temporary file and rename on success to avoid partial corrupt final files.
- Reader yields records; it validates `schema_version` and required fields, and errors early with a clear message if malformed.

Tests:

- Round-trip test: write a few records, read them back, compare equality.
- Schema validation test: missing required key produces a clear exception mentioning the key.

Promotion criteria:

- `PredictionRecord` and JSONL read/write utilities exist and are tested.
- Tests pass.

### Milestone 2: Extract a pure “predict stage” without changing prediction semantics

At the end of this milestone, you will be able to run prediction as its own stage, producing a stream (iterator) of `PredictionRecord`s using the same model invocation logic as before.

Work:

Refactor the existing code so that “calling the model” and turning the result into the old prediction format happens inside a function that can be invoked independently from evaluation. The key constraint is that you must not change any of the inputs to the model (prompt construction, decoding params, preprocessing) compared to legacy mode.

Define a stage boundary function, in the repo’s dominant style:

- If the project is synchronous: `predict_stage(examples_iter, predictor, predict_meta, ...) -> Iterator[PredictionRecord]`
- If the project is asyncio-based: `async predict_stage_async(examples_iter, predictor, predict_meta, ...) -> AsyncIterator[PredictionRecord]`

Where `predictor` is either the existing model wrapper or a thin adapter around it.

Ensure the stage:
- Assigns `example_id` and `example_index` deterministically.
- Produces exactly one `PredictionRecord` per input example (unless legacy behavior intentionally skips examples; if so, record the skip reason in a controlled way and mirror legacy behavior exactly).

Promotion criteria:

- A developer can run a “predict-only” mode that writes a JSONL predictions file.
- A small test verifies that `predict_stage` produces the same per-example prediction outputs as the legacy path on a tiny deterministic dataset (use a stub predictor if needed to avoid slow external calls).

### Milestone 3: Extract a pure “evaluate stage” consuming `PredictionRecord`s

At the end of this milestone, you will be able to compute the same evaluation metrics as legacy mode by consuming prediction records rather than calling the model.

Work:

Refactor evaluation so metric computation is expressed as:
- “Initialize evaluators/metric accumulators”
- “For each example: take the prediction for that example and update accumulators”
- “Finalize and render a report/output”

The stage must accept predictions and associate them with the correct ground truth labels. Prefer joining by `example_id`; fall back to `example_index` only if ids are truly unavailable.

Define an evaluation stage boundary function:

- Synchronous: `evaluate_stage(examples_iter, predictions_iter, metrics, ...) -> EvaluationReport`
- Async: `async evaluate_stage_async(examples_iter, predictions_async_iter, metrics, ...) -> EvaluationReport`

Do not change metric definitions. If the current metrics code expects to receive raw model outputs directly, adapt the prediction record to that expected format at the boundary, not by rewriting metrics.

Promotion criteria:

- “Evaluate-only” can run given a dataset + a predictions JSONL file and produces a report that matches the legacy report when fed the same predictions.
- Unit test coverage exists for at least one metric end-to-end through the stage.

### Milestone 4: Implement a pipelined runner (predict + evaluate concurrently) with bounded buffering

At the end of this milestone, there is an orchestrator that runs prediction and evaluation concurrently in a single command/process, overlapping their work safely.

Work:

Implement a runner that connects stages with a bounded queue.

The runner must:

- Start the prediction stage producer and evaluation stage consumer concurrently.
- Use a bounded queue to buffer `PredictionRecord`s.
- Propagate errors reliably: if prediction fails, evaluation must stop and the run must return a non-zero exit (or raise the repo’s standard exception type) with a clear error message.
- Ensure the run ends cleanly: producer signals end-of-stream, consumer finalizes metrics and returns the report.

Implementation approach, chosen in Milestone 0:

- If the repo is asyncio-native: use `asyncio.Queue(maxsize=...)`, create tasks for producer and consumer, and use cancellation semantics carefully.
- Otherwise: use `queue.Queue(maxsize=...)` and a producer thread; consumer runs in main thread (or vice versa). Use a sentinel value to signal end-of-stream.

In both cases, keep ordering deterministic for outputs that list per-example results: store `(example_index, record)` pairs and sort when writing final per-example outputs, or ensure consumer emits in order if the producer is in-order.

Optional but recommended: implement a “tee” so the pipeline can write predictions to disk while also feeding evaluation. This is the most direct way to prove stages are decoupled.

Promotion criteria:

- A pipelined mode exists that overlaps execution (evidenced by logs showing evaluation updates while prediction continues, or by measurable wall-clock improvement on a workload where evaluation is non-trivial).
- Metrics match the non-pipelined legacy mode on the baseline run captured in Milestone 0.

### Milestone 5: Wire into the existing CLI/entrypoint behind a feature flag and prove equivalence

At the end of this milestone, the default user-facing command still works, and users can enable the new architecture with a flag. A regression test proves equivalence.

Work:

In `<EVAL_ENTRYPOINT_PATH>`, add a configuration knob (CLI flag, config file option, or environment variable consistent with the repo) such as:

- `--execution-mode=legacy|pipelined`
- Or `--pipelined` boolean (default false until proven stable)

Add options for artifacts:

- `--predictions-out <path>`: write predictions JSONL.
- `--predictions-in <path>`: skip prediction and evaluate from this file (evaluate-only).
- If both are provided, define behavior explicitly: prefer `--predictions-in` for evaluation input, and still optionally write a normalized copy to `--predictions-out` (or error out; pick one and document it).

Add an equivalence test:

- Run evaluation with a deterministic stub predictor (or a fixed local model) in both modes.
- Assert that the final metrics dict/report is identical.
- Also assert that evaluate-only using the produced predictions file matches.

Promotion criteria:

- Legacy mode remains available and unchanged.
- Pipelined mode is available and passes the equivalence test.
- Documentation/help text describes the new mode and artifact flags.

## Concrete Steps

All commands below assume you are at the repository root.

### Step 0: Determine toolchain and how to run tests

Run:

    (repo root) $ ls
    (repo root) $ find . -maxdepth 2 -type f -name "pyproject.toml" -o -name "requirements.txt" -o -name "package.json" -o -name "Cargo.toml" -o -name "go.mod"

Then choose the test command based on what you find:

- If you see `pyproject.toml` or `requirements.txt`, assume Python and run:

      (repo root) $ python -m pytest -q

- If you see `package.json`, assume Node and run:

      (repo root) $ npm test

- If you see `Cargo.toml`, assume Rust and run:

      (repo root) $ cargo test

- If you see `go.mod`, assume Go and run:

      (repo root) $ go test ./...

Record the correct test command in this ExecPlan (replace this section with the repo’s actual command once confirmed).

### Step 1: Locate evaluation, prediction, and metrics code

Use ripgrep to find likely entrypoints:

    (repo root) $ rg -n "evaluate|evaluation|metrics|scor(e|ing)|accuracy" .
    (repo root) $ rg -n "predict|inference|generate|completion" .
    (repo root) $ rg -n "argparse|click|typer|fire|cobra|clap|main\(" .

Open the most relevant files and identify:

- `<EVAL_ENTRYPOINT_PATH>` (the main evaluation entrypoint)
- `<PREDICT_CALLSITE>` (the code that actually calls the model)
- `<METRICS_CALLSITE>` (the code that calculates or aggregates metrics)
- `<DATASET_ITERATOR>` (the code that iterates examples)

Update this ExecPlan by replacing placeholders everywhere, then commit just the plan edit:

    (repo root) $ git add <THIS_PLAN_FILE>
    (repo root) $ git commit -m "ExecPlan: concretize paths and symbols for predict/evaluate pipeline split"

### Step 2: Capture baseline output for a small deterministic run

Find or create a small dataset slice (or a tiny test dataset) that runs quickly.

Run the legacy evaluation command (fill in the real command once discovered):

    (repo root) $ <YOUR_EVAL_COMMAND> --execution-mode=legacy --limit 20 --seed 0

Record:

- The exact command line.
- The metrics output (copy/paste the final metrics dict/JSON into `Artifacts and Notes`).
- Any output file paths produced.

If the system is inherently non-deterministic (for example due to remote model sampling), force determinism as much as possible by setting decoding params (temperature 0) and seeds if supported, and document what remains non-deterministic and what tolerance you will accept.

### Step 3: Implement PredictionRecord + JSONL utilities

Create a new module under the evaluation package (replace with concrete path after Milestone 0). For example (Python-style):

- `<EVAL_PACKAGE_PATH>/pipeline/prediction_record.py`
- `<EVAL_PACKAGE_PATH>/pipeline/jsonl.py`

Add tests under the repo’s test layout (for example `tests/test_prediction_record_roundtrip.py`).

Run tests after implementation.

### Step 4: Extract predict stage and add predict-only mode

Refactor existing prediction logic so it can run as an iterator/async iterator producing `PredictionRecord`s.

Add a CLI or function entrypoint that produces `--predictions-out`.

Run:

    (repo root) $ <YOUR_EVAL_COMMAND> --predict-only --predictions-out /tmp/preds.jsonl --limit 20 --seed 0

Verify `/tmp/preds.jsonl` exists and contains 20 lines (one per example), and that each line parses as JSON with required keys.

### Step 5: Extract evaluate stage and add evaluate-only mode

Add `--predictions-in /tmp/preds.jsonl` to skip prediction and compute metrics.

Run:

    (repo root) $ <YOUR_EVAL_COMMAND> --evaluate-only --predictions-in /tmp/preds.jsonl --limit 20 --seed 0

Verify metrics match what you would get when running legacy prediction + evaluation over the same 20 examples.

### Step 6: Implement pipelined runner and wire `--execution-mode=pipelined`

Run pipelined mode:

    (repo root) $ <YOUR_EVAL_COMMAND> --execution-mode=pipelined --predictions-out /tmp/preds.jsonl --limit 20 --seed 0

Verify:

- Metrics match legacy baseline (exactly or within documented tolerance).
- Predictions file is produced.
- Logs indicate both stages are active (for example, evaluation updates appear before prediction completes).

### Step 7: Add equivalence tests

Add a deterministic stub predictor and a tiny fixed dataset for tests if the real predictor is slow or non-deterministic.

Create an integration test that runs:
- legacy mode
- pipelined mode
- evaluate-only-from-predictions

and asserts all metrics are equal.

Run the full test suite.

## Validation and Acceptance

This change is accepted when all of the following are true:

1) Running the baseline command in legacy mode produces the same metrics as before the refactor (no regression).

2) Running the same baseline in pipelined mode produces identical metrics to legacy mode, and produces a valid predictions artifact when `--predictions-out` is provided.

3) Running evaluate-only from the produced predictions artifact produces metrics identical to the other two modes.

4) There is at least one automated test that would fail if:
- a prediction record cannot be read back correctly,
- a prediction is mismatched to the wrong example,
- or pipelined mode diverges in metrics from legacy mode.

5) If the repo has CI, the test suite passes in CI with pipelined code enabled (even if the default user-facing mode remains legacy for now).

## Idempotence and Recovery

All steps in this plan should be safe to repeat.

Prediction artifact writing must be designed so that a partial run does not corrupt a “final” file path. Implement this by writing to a temporary path (for example `<path>.tmp`) and renaming to `<path>` only after the producer completes successfully.

If the pipelined run crashes, a developer should be able to:
- delete the temporary predictions file and retry, or
- keep the successful predictions file (if it exists) and re-run evaluate-only to debug evaluation without re-predicting.

If you implement a “resume” behavior (optional), document it explicitly and ensure it is conservative: never silently mix predictions from different model settings. Prefer to error with a clear message if metadata differs.

## Artifacts and Notes

Replace this section’s placeholders with real baseline outputs once Milestone 0 is complete.

Example `PredictionRecord` JSONL line (schema_version 1):

    {"schema_version":1,"example_id":"dataset/train/000000","example_index":0,"prediction":{"text":"..."},"predict_meta":{"model":"<model_name>","temperature":0,"prompt_version":"v1"}}

Baseline legacy metrics (paste the real output here):

    legacy_metrics = {"accuracy": 0.85, "exact_match": 0.80}

Expected pipelined metrics (must match legacy):

    pipelined_metrics = {"accuracy": 0.85, "exact_match": 0.80}

## Interfaces and Dependencies

This section defines the concrete interfaces that must exist at the end of the plan. Replace module paths with the repo’s actual package layout after Milestone 0.

### Data contract: PredictionRecord

In `<EVAL_PACKAGE_PATH>/pipeline/prediction_record.<ext>`, define a type named `PredictionRecord` with fields:

- `schema_version: int` (constant 1 for now)
- `example_id: str`
- `example_index: int`
- `prediction: <JSON-serializable type>`
- `predict_meta: <map/dict type>`

Define a validation function/method that:
- checks required fields exist,
- checks `schema_version` is supported,
- and raises/returns a clear error on failure.

### Artifact IO: JSONL reader/writer

In `<EVAL_PACKAGE_PATH>/pipeline/predictions_io.<ext>`, define:

- `write_prediction_records(path, records_iter) -> None` (or async equivalent)
- `read_prediction_records(path) -> Iterator[PredictionRecord]` (or async equivalent)

Writer requirements:
- writes one JSON object per line,
- flushes periodically for long runs,
- writes to temp then renames on success.

Reader requirements:
- yields records in file order,
- validates each record,
- surfaces parse errors with line number context.

### Stage APIs

In `<EVAL_PACKAGE_PATH>/pipeline/stages.<ext>`, define:

- `predict_stage(examples_iter, predictor, predict_meta, ...) -> Iterator[PredictionRecord]`
- `evaluate_stage(examples_iter, predictions_iter, metrics, ...) -> EvaluationReport`

Where `EvaluationReport` is whatever the existing system uses to represent final results (a dict, a dataclass, a JSON structure, etc.). Do not invent a new report format unless the repo currently lacks one; if you must, define it minimally and adapt legacy rendering to it.

### Runner API

In `<EVAL_PACKAGE_PATH>/pipeline/runner.<ext>`, define a runner:

- `run_legacy(...) -> EvaluationReport` (thin wrapper around existing behavior)
- `run_pipelined(..., buffer_size: int, predictions_out: Optional[path], predictions_in: Optional[path]) -> EvaluationReport`

The pipelined runner must:
- support producing predictions while evaluating,
- support evaluate-only from `predictions_in`,
- and guarantee that the mapping between example and prediction is correct.

### Dependencies

Use only the repo’s existing standard library and dependencies unless there is a strong reason to add a new one.

For Python, prefer:
- `dataclasses` (or `pydantic` if already used in the repo),
- `json`,
- `queue` and `threading` (sync) or `asyncio` (async),
- `pathlib` for paths.

Do not add a new serialization or pipeline framework for this change; keep the boundary simple and inspectable.

---

Plan change notes (append-only):

- 2026-02-27: Initial plan created. Assumes repo-specific discovery is needed before naming concrete paths; Milestone 0 requires replacing placeholders everywhere before proceeding.
- 2026-02-27: Updated after implementation pass to reflect landed stage-runner APIs, per-block prediction-record replay contract, legacy compatibility behavior, and remaining timing-evidence gap.
