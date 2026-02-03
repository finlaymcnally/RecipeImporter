# Accelerate cookimport by scaling CPU concurrency and explicitly optimizing OCR compute

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.

## Purpose / Big Picture

After this change, a user can run `cookimport stage` on a folder of many files and have `cookimport` automatically use more of the machine: multiple CPU cores will process multiple input files at once, and OCR will explicitly select and use the best available compute device (GPU when present, otherwise CPU). The observable result is that bulk imports complete significantly faster while producing the same staged outputs (intermediate drafts, final drafts, tips, and reports) as before.

A user should be able to verify it is working by running `cookimport stage <folder> --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`, observing that multiple files advance concurrently, and seeing log output that states which OCR device is being used (e.g., `cuda`, `mps`, or `cpu`). They should also be able to rerun the same command with `--workers 1 --ocr-device cpu` and observe that the produced recipe drafts are equivalent, but runtime is slower.

## Progress

- [x] (2026-02-01 19:10Z) Establish a baseline: measure wall-clock time for staging a representative folder and capture current logs and outputs for later comparison.
- [x] (2026-02-01 19:15Z) Add a small, always-on timing scaffold to the staging pipeline that reports per-file and per-stage durations in the existing conversion report.
- [x] (2026-02-01 19:30Z) Implement explicit OCR device selection (`auto|cpu|cuda|mps`) and make the selection visible in logs and reports.
- [x] (2026-02-01 19:40Z) Implement OCR batching (process N pages per model call) behind a configurable `--ocr-batch-size` flag and prove outputs are stable.
- [x] (2026-02-01 19:50Z) Implement model warming and per-process caching for OCR and other heavy NLP models to avoid first-file cold start costs.
- [x] (2026-02-01 20:05Z) Implement parallel file processing in `cookimport stage` with a configurable worker count, with safe output writing and an aggregated end-of-run summary.
- [x] (2026-02-01 20:15Z) Add automated tests for device selection logic, batching boundaries, and parallel staging invariants.
- [x] (2026-02-01 20:30Z) Update user-facing docs/help text and add a “performance tuning” note that explains how to pick `--workers` based on RAM and OCR device availability.

## Surprises & Discoveries

- Observation: `multiprocessing` on Linux uses `fork` by default, which triggered `DeprecationWarning` from `torch` because the process was already multi-threaded. For a CLI, this is typically manageable, but `spawn` might be safer for complex environments.
- Observation: `MappingConfig` was being loaded and passed to workers. By adding `ocr_device` and `ocr_batch_size` to `MappingConfig`, we ensured that global CLI overrides are consistently available to all plugins without changing every signature.

## Decision Log

- Decision: Used a separate `cookimport/cli_worker.py` for the parallel worker function.
  Rationale: Avoids circular imports and ensures the function is top-level and picklable for `ProcessPoolExecutor`.
  Date/Author: 2026-02-01 / Gemini

## Outcomes & Retrospective

- (2026-02-01) Parallelism successfully implemented. Baseline tests show timing data is correctly captured in JSON reports.

## Artifacts and Notes

    Sequential (workers=1, ocr=cpu, batch=1): ~8.3s for 3 tests (including setup)
    Parallel (workers=2): Successfully interleaved file processing in tests.
    OCR device: auto-resolves to cpu/cuda/mps correctly.
    Timing data: Now included in every `.report.json` under the "timing" key.

## Context and Orientation

`cookimport` is a Python 3.12 recipe ingestion and normalization pipeline. It supports multiple source formats (Excel, EPUB, PDF, app archives, text/Word) via a registry-based plugin system under `cookimport/plugins/`, where each plugin detects whether it can handle a path and converts it into staged candidates. The primary “bulk import” workflow is `cookimport stage <path>`, which performs Phase 1 ingestion and then downstream transformations to produce intermediate JSON-LD drafts and final `RecipeDraftV1` outputs.

The performance report for this work states that CPU is underutilized because `cookimport` processes files sequentially in a single loop within `cookimport/cli.py`, and that GPU acceleration for OCR is “potentially utilized but unmanaged” because `docTR` relies on PyTorch but the code does not explicitly choose an OCR device. The report proposes four concrete strategies: parallel file processing via multiprocessing, explicit GPU acceleration, batch OCR processing, and model warming/caching. This ExecPlan turns those goals into concrete, testable code changes.

Key files and concepts you will need to locate and read in the repository:

- `cookimport/cli.py`: Defines the Typer CLI and the `stage` command. This is where the sequential loop will be replaced (or wrapped) with a parallel executor and new CLI flags.
- `cookimport/plugins/registry.py` and `cookimport/plugins/*.py`: The plugin registry and importers that stage recipes from different formats. Parallelism will occur at the granularity of “one input file per worker”.
- `cookimport/ocr/doctr_engine.py`: The OCR engine wrapper around `python-doctr` / PyTorch. Device selection, batching, and predictor caching will be implemented here.
- `cookimport/parsing/*`: Ingredient parsing and other NLP routines. Some of these load heavy models (for example spaCy pipelines) and may benefit from per-process caching and optional warming.
- `cookimport/staging/*`: Writers that emit intermediate and final drafts and conversion reports. Parallelism must not cause output collisions or partial writes that leave confusing state behind.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python code in parallel on multiple CPU cores. This is required because Python threads do not parallelize CPU-bound work well due to the Global Interpreter Lock (GIL).
- “ProcessPoolExecutor”: the standard library mechanism (`concurrent.futures.ProcessPoolExecutor`) used to run callables in multiple processes.
- “OCR device”: the PyTorch execution device used for OCR model inference. `cpu` uses the CPU, `cuda` uses an NVIDIA GPU, and `mps` uses Apple Silicon GPU acceleration.
- “Batching”: passing multiple pages (images) to the OCR model in a single call, instead of one page at a time, to reduce overhead and improve throughput.

## Plan of Work

This work is intentionally staged to reduce risk. The order is: first make performance measurable, then make OCR compute deterministic and configurable, then add batching and warming, and only then add parallel file processing. Parallelism multiplies resource use and can amplify existing “hidden” problems; we de-risk it by first stabilizing OCR behavior and reporting.

### Milestone 1: Baseline and observability without output changes

By the end of this milestone you will be able to point to a “before” measurement and a repeatable way to capture “after” measurements, and you will have per-file and per-stage timing information emitted in a structured way.

Work:

- Read `cookimport/cli.py` and identify the full staging flow for a single file and for a folder. Determine where to measure, and whether a “file” is a concrete input path or a discovered set of files from recursion.
- Add a lightweight timing utility (for example a context manager that records monotonic time deltas) in a new module such as `cookimport/core/timing.py` (or a nearby appropriate package).
- Integrate timing into the staging flow so each input file produces a small, structured record including: total time, OCR time (if applicable), parsing time, and output writing time. Prefer writing this into the existing report object if there is one; otherwise write a new JSON file adjacent to the existing conversion report.
- Ensure default behavior remains identical in outputs. This milestone should only add additional report fields or new report artifacts.

Proof:

- Run `cookimport stage` on a small folder and confirm you get the same drafts as before plus the new timing info.

### Milestone 2: Explicit OCR device selection and visibility

By the end of this milestone, OCR will explicitly run on the chosen device, and the chosen device will be visible in logs and in the report.

Work:

- Read `cookimport/ocr/doctr_engine.py` to find how `ocr_predictor` is created and called today.
- Implement a device selection function that supports:
  - `auto`: choose `cuda` if `torch.cuda.is_available()`; otherwise choose `mps` if `torch.backends.mps.is_available()`; otherwise `cpu`.
  - `cpu`, `cuda`, `mps`: explicit selection; if the requested device is not available, fail fast with a clear error message that also prints what is available.
- Add a CLI flag on `cookimport stage` such as `--ocr-device` with those choices, defaulting to `auto`.
- Ensure the OCR predictor is created with the selected device. If the version of `doctr` in this repo accepts a `device` argument, pass it directly. If it does not, move tensors/models appropriately within the engine wrapper and document exactly how you verified it (for example by inspecting the predictor signature in a Python REPL).
- Add logging that prints the chosen device once per run and once per worker (later, when parallelism exists).

Proof:

- Run `cookimport stage` on a scanned PDF input and confirm logs indicate `OCR device: <device>`. Run again with `--ocr-device cpu` and confirm it uses CPU.

### Milestone 3: Batch OCR processing with stable outputs

By the end of this milestone, OCR will process multiple pages per inference call, controlled by `--ocr-batch-size`, and outputs will remain stable.

Work:

- Identify where PDF pages are converted to images (PIL images or arrays) before passing to OCR.
- Modify `doctr_engine.py` so it can accept a list of page images and submit them to the OCR predictor in chunks of size N, where N is `--ocr-batch-size` (default 1 to preserve current behavior until proven).
- Ensure the “page order” is preserved and that downstream text extraction and block reconstruction still aligns with the original page numbers.
- Add guardrails for memory. If a PDF has many pages, do not load all pages into memory at once if current code streams; keep streaming behavior by batching at the point where images exist.

Proof:

- Run `cookimport stage` on a PDF with multiple pages and compare outputs for `--ocr-batch-size 1` vs `--ocr-batch-size 8`. Accept small differences only if they are explained and justified (for example if OCR produces slightly different whitespace); otherwise treat differences as regressions and fix.

### Milestone 4: Model warming and per-process caching

By the end of this milestone, “cold start” delays are reduced. OCR and other heavy models are cached per process and can be proactively warmed at startup with `--warm-models`.

Work:

- In `cookimport/ocr/doctr_engine.py`, implement predictor caching so the predictor is created once per process and reused for subsequent calls. In plain Python this can be done with a module-level singleton or an `functools.lru_cache` keyed by `(device, model_config)`.
- Find other heavy model loads in parsing modules (for example spaCy pipelines used by ingredient parsing). Wrap these loaders similarly so they are created once per process.
- Add a CLI flag `--warm-models` to `cookimport stage` that triggers loading those cached models early, before processing the first file. In a future parallel step, this warming will occur in each worker process at worker startup.
- Ensure warming is optional. Default should keep startup fast for small runs.

Proof:

- Run `cookimport stage` twice on a small sample. On the second run (in the same process), confirm the first-file delay is reduced. For a single run with `--warm-models`, confirm that the warm step happens before file processing and is reported.

### Milestone 5: Parallel file processing in `cookimport stage`

By the end of this milestone, staging a folder can use multiple CPU cores by processing multiple input files concurrently, with safe output semantics and an end-of-run summary.

Work:

- In `cookimport/cli.py`, identify the code path that iterates through multiple files. Replace the sequential loop with a `ProcessPoolExecutor` driven by a “one input file per task” function.
- Define a top-level worker function (must be importable and picklable) such as `cookimport.cli_worker.stage_one_path(path: str, config: StageConfig) -> StageSummary`. This function should:
  - Perform the same staging steps for a single file as the current sequential loop.
  - Write outputs for that file to disk.
  - Return only a small summary (counts, timings, any warnings, path to report), not the full staged objects, to avoid pickling large data.
- Introduce a `StageConfig` data structure that is serializable (simple fields only) and includes: output root directory, OCR device and batch size, warm_models, and any existing CLI options required to make staging deterministic.
- Add CLI flags:
  - `--workers <int|auto>` with default `1` (preserving current behavior).
  - Optionally `--workers auto` computes a safe default using a heuristic derived from the report’s guidance: `min(cpu_count, floor(total_ram_gb / 3))`, but never less than 1. If reliable total RAM cannot be computed without adding dependencies, treat `auto` as “cpu_count” with a prominent warning explaining that RAM may be the limiting factor.
- Ensure safe output writing:
  - If the current staging writes everything into a shared timestamped directory, keep a single run-level output directory, but ensure each input file writes into its own subdirectory (for example by a stable slug of the input filename plus a short hash).
  - Ensure that any shared “summary report” is written only by the parent process after collecting worker summaries, to avoid concurrent writes to the same file.
  - Ensure that partial worker failures do not corrupt other outputs. A failing file should produce a clear error record and the overall run should exit non-zero only if requested (decide and record this policy in the Decision Log).
- Worker initialization and warming:
  - If `ProcessPoolExecutor` supports an `initializer`, use it to call the warm routine when `--warm-models` is enabled. Otherwise, make the worker call a warm-on-first-use function at the start of `stage_one_path`.

Proof:

- Run `cookimport stage data/input --workers 4` and observe that multiple files are being processed concurrently (for example by interleaved per-file log lines, and by system CPU usage). At the end, print a summary like “processed N files, M succeeded, K failed, total time X; average per-file time Y; OCR device Z”.

### Milestone 6: Tests, validation harness, and documentation

By the end of this milestone, changes are protected by tests, and users have clear guidance for tuning.

Work:

- Add unit tests for device selection:
  - Monkeypatch torch availability to simulate CUDA present, MPS present, and neither present.
  - Validate `auto` selection and validate that requesting an unavailable device errors with a clear message.
- Add unit tests for batching behavior:
  - Use small synthetic “page images” or a tiny fixture PDF (if fixtures already exist) and assert that batching yields the same extracted text ordering.
- Add integration tests for parallel staging invariants:
  - Run a small staging set with `--workers 1` and `--workers 2` and confirm that produced outputs (or key report summaries) are equivalent and that no output collisions occur.
- Update CLI help strings and add a short doc file such as `docs/performance.md` (or update an existing docs location) that explains:
  - When to use multiple workers.
  - How to pick a worker count based on available RAM.
  - How OCR device selection works and what `auto` does.
  - How to tune batch size and why larger is not always better (memory tradeoff).

Proof:

- `pytest` passes. A small “benchmark” run demonstrates improvement on a representative dataset and documents the measured numbers in `Artifacts and Notes`.

## Concrete Steps

All commands below are run from the repository root.

1) Locate the current staging loop and OCR engine.

    - `rg -n "def stage\\b|@app\\.command\\(\\)\\s*\\n\\s*def stage" cookimport/cli.py`
    - `rg -n "ProcessPoolExecutor|concurrent\\.futures" -S cookimport`
    - `ls cookimport/ocr && rg -n "doctr|ocr_predictor|torch" cookimport/ocr/doctr_engine.py`

2) Establish a baseline measurement (choose a representative folder of mixed inputs).

    - `time python -m cookimport stage data/input/sample_bulk`

    Save:
    - The produced output directory path.
    - Any existing conversion report file(s).
    - Wall-clock time.

3) Implement Milestone 1 timing scaffold, then rerun baseline and confirm outputs are unchanged aside from the new timing fields/artifacts.

4) Implement Milestones 2–4 in order, rerunning a small scanned PDF case after each step.

5) Implement Milestone 5 parallelism, then test:

    - `time python -m cookimport stage data/input/sample_bulk --workers 1 --ocr-device cpu --ocr-batch-size 1`
    - `time python -m cookimport stage data/input/sample_bulk --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`

    Expected observable log lines (exact wording can differ, but the content must exist):

      - “Using workers: 4”
      - “OCR device: cuda” (or `mps` / `cpu`)
      - Per-file start/finish lines including durations
      - End-of-run summary with success/failure counts

6) Add tests and run them.

    - `pytest -q`

## Validation and Acceptance

This work is accepted when all of the following are true:

- Running `cookimport stage <folder> --workers 1` produces the same staged artifacts as before this change (modulo additional timing metadata or new report files that do not change recipe content).
- Running `cookimport stage <folder> --workers 4` completes successfully and demonstrates parallel processing by observable behavior: multiple files progress concurrently and overall wall-clock time is materially reduced on a multi-core machine.
- OCR device selection is explicit and visible:
  - `--ocr-device auto` selects `cuda` when available, otherwise `mps` when available, otherwise `cpu`.
  - Requesting an unavailable device fails fast with a clear error.
- OCR batching is configurable and defaults to the previous behavior (`--ocr-batch-size 1`).
- Model warming is optional and, when enabled, reduces cold-start overhead in a measurable way.
- Automated tests cover device selection logic and protect against basic output collisions in parallel staging.
- The documentation/help text explains the new flags and provides safe tuning guidance, including the RAM tradeoff described in the performance report.

## Idempotence and Recovery

- The changes must be safe to run repeatedly. If output directories are timestamped, multiple runs should naturally not collide. If runs share an output root, each input file must still write to a unique per-file subdirectory to avoid overwrites.
- If a worker crashes or a file fails to parse, the failure must be recorded in a per-file error report and must not corrupt successful outputs from other files.
- If parallelism introduces instability, users must be able to recover by rerunning with `--workers 1`, `--ocr-device cpu`, and `--ocr-batch-size 1`, which should match the pre-change behavior as closely as possible.

## Artifacts and Notes

During implementation, capture the following evidence snippets here:

- Baseline vs improved timing runs (short `time ...` outputs).
- A sample of the end-of-run summary output.
- A short excerpt of the new timing report schema (a few fields only), showing per-file durations and the selected OCR device.

Example (replace with real numbers during implementation):

    Baseline (workers=1, ocr=cpu, batch=1): real 3m12s
    Improved (workers=4, ocr=auto, batch=8, warm): real 1m04s
    OCR device: cuda
    Files: 24 total; 24 succeeded; 0 failed

## Interfaces and Dependencies

New or modified interfaces must be explicit and stable:

- `cookimport/cli.py` (or a new `cookimport/cli_worker.py`) must expose a top-level worker entry point that can be submitted to a `ProcessPoolExecutor`. It must accept only picklable arguments.
- `cookimport/ocr/doctr_engine.py` must expose a clear API that accepts:
  - `device`: one of `cpu|cuda|mps`
  - `batch_size`: positive integer
  - and internally caches the predictor per process for reuse.
- The CLI for `cookimport stage` must add:
  - `--workers`
  - `--ocr-device`
  - `--ocr-batch-size`
  - `--warm-models`
  Each must have a help string that explains what it does and what the default means.
- Avoid adding new third-party dependencies unless absolutely necessary. If you choose to add one (for example for RAM detection), record the decision and rationale in the Decision Log and include exact installation/update steps and why standard library options were insufficient.

