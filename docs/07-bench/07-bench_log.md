---
summary: "Benchmark architecture/build/fix-attempt log to prevent repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on benchmark behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical benchmark architecture versions, build attempts, and known failed paths before trying another change
---

# Bench Log: Architecture, Builds, and Fix Attempts

Read this if you are going in multi-turn circles on a benchmark/program behavior issue, or if the human says "we are going in circles on this."
This file tracks architecture versions, builds, fix attempts, and anti-loop notes so we do not repeat dead ends.

## 1. 2026-02-19_15.49.31 README/Log split marker

- Split benchmark section docs into:
  - `docs/07-bench/07-bench_README.md` for current benchmark behavior/source-of-truth.
  - `docs/07-bench/07-bench_log.md` for chronology, prior build/fix attempts, and anti-loop notes.
- Moved all prior chronology/discovery content from the README into this log without dropping details.

## 2. 2026-02-15 Task Chronology (Merged From docs/tasks)

### 2.1 2026-02-15_23.14.04 interactive benchmark credential resolution

Merged source:
- `docs/tasks/2026-02-15_23.14.04 - interactive-benchmark-credential-prompt.md`

Problem captured:
- Interactive benchmark upload exited on missing `LABEL_STUDIO_URL` / `LABEL_STUDIO_API_KEY` instead of prompting like other interactive Label Studio flows.

Decision captured:
- Reuse `_resolve_interactive_labelstudio_settings(settings)` inside upload-mode benchmark flow.
- Preserve non-interactive behavior (still env/CLI driven and fail-fast when missing).

Task verification/evidence preserved:
- targeted regression and helper suite command:
  - `. .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py`
- recorded result: `26 passed`.
- task specifically notes updated assertion that resolved URL/API key are forwarded into `labelstudio_benchmark(...)`.

### 2.2 2026-02-15_23.23.38 split benchmark pickle fix for unstructured metadata

Merged source:
- `docs/tasks/2026-02-15_23.23.38 - benchmark-split-pickle-fix-unstructured-version.md`

Problem captured:
- Split benchmark EPUB jobs failed with `cannot pickle 'module' object`; regular imports could still appear fine.

Decision captured:
- Normalize unstructured diagnostics `unstructured_version` through a helper that always returns a string, even when library version surfaces as a module-like object.
- Keep split benchmark path parallelized (no serial fallback workaround).

Task verification/evidence preserved:
- `. .venv/bin/activate && pytest -q tests/test_epub_importer.py::test_resolve_unstructured_version_handles_module_value tests/test_labelstudio_ingest_parallel.py`
- recorded result: `4 passed`.
- manual pickle reproduction in task notes confirms worker payload pickles after the fix (`diag_version_type str`, `pickle_ok`).

Anti-loop note:
- Avoid "just disable split mode" as a fix; root issue was payload shape/pickle safety.

### 2.3 2026-02-15_23.50.23 remove redundant interactive upload confirmation

Merged source:
- `docs/tasks/2026-02-15_23.50.23 - interactive-benchmark-remove-redundant-upload-confirm.md`

Problem captured:
- Upload mode asked a second confirmation (`Upload benchmark prediction tasks ... now?`) after user already selected upload mode.

Decision captured:
- Treat mode selection as sufficient intent; remove only the redundant confirm in interactive upload branch.
- Keep eval-only branch behavior unchanged.
- Keep interactive credential resolution path unchanged.

Task verification/evidence preserved:
- targeted upload/eval helper tests in `tests/test_labelstudio_benchmark_helpers.py` were recorded as passing after change.
- task notes that updated upload test fails if `questionary.confirm(...)` is invoked in upload mode.

### 2.4 2026-02-15_23.58.48 benchmark EPUB extractor selection

Merged source:
- `docs/tasks/2026-02-15_23.58.48 - benchmark-epub-extractor-choice.md`

Problem captured:
- Benchmark prediction generation was controlled by `C3IMP_EPUB_EXTRACTOR`, but benchmark command paths did not expose a per-run extractor choice.

Decision captured:
- Add `--epub-extractor` to `cookimport labelstudio-benchmark` and keep it aligned with stage extractor choices (`unstructured|legacy|markdown|auto|markitdown`).
- Prompt for extractor in interactive benchmark upload mode.
- Apply extractor choice via scoped env override around prediction import and restore previous env afterward.

Task verification/evidence preserved:
- helper tests added/updated for:
  - interactive extractor prompt wiring,
  - env propagation to prediction import,
  - invalid extractor rejection.

Known rejected path:
- "Use whichever extractor happens to be in env from prior runs" was explicitly treated as unreliable and replaced by explicit per-run selection.

## 3. Merged Discovery Provenance (Former `docs/understandings`)

### 3.1 2026-02-15_23.06.53 interactive eval-only gate

Merged source file:
- `2026-02-15_23.06.53-interactive-benchmark-eval-only-gate.md` (formerly in `docs/understandings`)

Preserved finding:
- Interactive benchmark shows `How would you like to benchmark?` only when both artifacts are discoverable:
  - gold exports under `**/exports/freeform_span_labels.jsonl`
  - prediction runs under `**/label_studio_tasks.jsonl`
- If either side is missing, flow defaults directly to upload mode.

### 3.2 2026-02-15_23.13.18 interactive upload credential resolution

Merged source file:
- `2026-02-15_23.13.18-interactive-benchmark-upload-credential-resolution.md` (formerly in `docs/understandings`)

Preserved rule:
- Interactive upload must resolve creds via `_resolve_interactive_labelstudio_settings(settings)` before calling `labelstudio_benchmark(...)`.
- Relying only on `labelstudio_benchmark` env/CLI resolution causes missing-credential exits in interactive mode.

### 3.3 2026-02-15_23.23.30 split pickling failure anatomy

Merged source file:
- `2026-02-15_23.23.30-benchmark-split-epub-unstructured-version-pickling.md` (formerly in `docs/understandings`)

Preserved finding:
- Split conversion jobs in `ProcessPoolExecutor` fail if any `ConversionResult` field is unpickleable.
- `getattr(unstructured, "__version__", "unknown")` can return a module-like object in some environments.

Durable rule:
- Normalize runtime version metadata to plain string before attaching to worker return payloads.
- Keep worker return payloads restricted to primitive-safe structures (`str`, `int`, `float`, `bool`, `None`, plus dict/list compositions of those).

### 3.4 2026-02-15_23.31.19 direct-call default semantics in eval

Merged source file:
- `2026-02-15_23.31.19-interactive-benchmark-eval-defaults.md` (formerly in `docs/understandings`)

Preserved finding:
- Direct Python calls into `labelstudio_eval(...)` (interactive/tests) previously inherited `typer.Option(...)` objects instead of runtime defaults, causing `TypeError` in threshold comparisons.

Durable rule:
- Keep CLI option metadata with `typing.Annotated[..., typer.Option(...)]` plus real Python defaults so both CLI parsing and direct calls behave correctly.
- Regression anchor: `tests/test_labelstudio_benchmark_helpers.py::test_labelstudio_eval_direct_call_uses_real_defaults`.

### 3.5 2026-02-15_23.31.46 benchmark scoring contract reminder

Merged source file:
- `2026-02-15_23.31.46-benchmark-scores-task-artifacts-not-stage-outputs.md` (formerly in `docs/understandings`)

Preserved rule:
- Benchmark scoring compares prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`).
- Stage/cookbook outputs may be written for review but are not the scoring contract.

Anti-loop note:
- Repeated attempts to "just score final outputs directly" will keep failing until a deterministic projection back to span coordinates is designed.

### 3.6 2026-02-15_23.48.49 upload confirmation removal

Merged source file:
- `2026-02-15_23.48.49-interactive-benchmark-upload-no-second-confirm.md` (formerly in `docs/understandings`)

Preserved rule:
- Interactive upload mode selection is already explicit intent; no second y/n upload confirmation should be reintroduced.

### 3.7 2026-02-15_23.58.38 extractor runtime switch behavior

Merged source file:
- `2026-02-15_23.58.38-benchmark-epub-extractor-runtime-switch.md` (formerly in `docs/understandings`)

Preserved rule:
- Prediction generation path reads `C3IMP_EPUB_EXTRACTOR`.
- Benchmark flows that need deterministic extractor choice must set this explicitly for run scope (CLI flag + scoped env override), not rely on whatever environment happened to be set earlier.
