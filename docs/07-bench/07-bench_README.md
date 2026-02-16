---
summary: "Offline benchmark-suite documentation for validation, run, sweep, and tuning loops."
read_when:
  - When iterating on parser quality without Label Studio uploads
  - When running or modifying cookimport bench workflows
  - When asking why benchmark scoring differs from regular stage/import outputs
---

# Bench Section Reference

Offline benchmarking is provided by `cookimport bench ...` and shares prediction/eval primitives with Label Studio benchmark flows.

If your question is "why isn’t benchmark just scoring regular import outputs?", read sections 2-6 first.

## 1. Short answer

Benchmark does **not** score staged cookbook files (`final drafts`, `tips`, etc.) directly.
It scores **prediction task artifacts** (`label_studio_tasks.jsonl`) against **gold freeform span artifacts** (`freeform_span_labels.jsonl`) because both are aligned to the same block/span coordinate system.

That shared coordinate system is what makes comparison deterministic.

## 2. The three artifact families

### 2.1 Stage artifacts (human/product outputs)

Produced by `cookimport stage` in `cookimport/cli.py`.
Examples:
- `intermediate drafts/...`
- `final drafts/...`
- `tips/...`
- `chunks/...`
- `<workbook>.excel_import_report.json`

These are excellent for product output and manual inspection, but they are not the scoring contract used by freeform gold evaluation.

### 2.2 Prediction-run artifacts (benchmark prediction contract)

Produced by `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py`.
Key files:
- `label_studio_tasks.jsonl` (predicted tasks/ranges used for scoring)
- `extracted_archive.json` (block stream used to derive tasks)
- `manifest.json` (run metadata)
- `run_manifest.json` (cross-command source/config/artifact linkage)
- `coverage.json`

These are the canonical "predictions" for both:
- `cookimport labelstudio-benchmark`
- `cookimport bench run` (offline suite)

### 2.3 Gold artifacts (annotation contract)

Produced by `cookimport labelstudio-export --export-scope freeform-spans`.
Key file:
- `exports/freeform_span_labels.jsonl`

This gold format stores span labels + touched block indices, which is why prediction side must use comparable block/range representation.

## 3. Why benchmark uses task artifacts instead of staged outputs

### 3.1 Gold is span/block based, not final-json based

Freeform gold labels represent highlighted text spans mapped to block indices.
Staged outputs are normalized recipe/tip/chunk products, not direct span annotations.

If benchmark tried to score staged outputs directly, it would need a reverse-projection layer back into block spans. That would add ambiguity and make scoring less stable.

### 3.2 Shared coordinate system prevents "apples vs oranges"

Both prediction and gold are evaluated as labeled ranges:
- Prediction ranges are loaded from `label_studio_tasks.jsonl` (`load_predicted_labeled_ranges`)
- Gold ranges are loaded from `freeform_span_labels.jsonl` (`load_gold_freeform_ranges`)
- Matching is performed by overlap logic (`evaluate_predicted_vs_freeform`)

This is a direct contract-to-contract comparison, not a derived approximation.

### 3.3 Same artifact contract works for both online and offline loops

`generate_pred_run_artifacts(...)` is reused in:
- online Label Studio import/upload flows
- offline suite benchmarking

This keeps one prediction representation for all evaluation paths.

## 4. Flow map: regular stage vs benchmark

### 4.1 Regular stage flow (`cookimport stage`)

1. Convert source file(s)
2. Build recipes/tips/chunks
3. Write staged outputs
4. Done

No scoring step is included in this command.

### 4.2 Label Studio benchmark flow (`cookimport labelstudio-benchmark`)

1. Select gold freeform export
2. Select source file
3. Build prediction-run artifacts (upload mode calls `run_labelstudio_import(...)`, which uses `generate_pred_run_artifacts(...)`; offline mode calls `generate_pred_run_artifacts(...)` directly).
4. Choose upload vs offline: upload mode (default) sends tasks to Label Studio (`--allow-labelstudio-write` required), while offline mode (`--no-upload`) skips credential resolution and Label Studio API calls.
5. Evaluate predicted ranges vs gold ranges
6. Write eval report artifacts (`eval_report.json`, `eval_report.md`, misses/FPs) plus `run_manifest.json`

### 4.3 Offline suite flow (`cookimport bench run`)

1. For each suite item, call `generate_pred_run_artifacts` (offline, no upload)
2. Load predictions from `pred_run/label_studio_tasks.jsonl`
3. Load gold spans from `<gold_dir>/exports/freeform_span_labels.jsonl`
4. Evaluate + aggregate
5. Write `report.md`, `metrics.json`, `iteration_packet/*`

This is the "no Label Studio write" benchmark loop.

## 5. Where processed/staged outputs still fit in benchmark

Benchmark can still emit staged cookbook-style outputs for review:
- `labelstudio-benchmark` passes `processed_output_root` into prediction generation.

Important:
- Those staged outputs are side artifacts for inspection.
- Scoring still uses prediction tasks vs freeform gold spans.

So your intuition is partly right: benchmark does generate regular-looking outputs too, but they are not currently the scored surface.

## 6. Exact scoring surface (freeform)

Evaluation input A (predictions):
- `label_studio_tasks.jsonl`
- Parsed into labeled ranges via `load_predicted_labeled_ranges(...)`
- Label mapping is inferred from chunk metadata (`chunk_level`, `chunk_type`, hints)

Evaluation input B (gold):
- `freeform_span_labels.jsonl`
- Parsed via `load_gold_freeform_ranges(...)`
- Uses touched block indices from export payload

Matching:
- Jaccard overlap threshold (default `0.5`)
- Optional source identity relaxation via `--force-source-match`

Outputs:
- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`

## 7. Command matrix

| Command | Uploads to Label Studio | Scores predictions | Primary prediction source |
|---|---:|---:|---|
| `cookimport stage` | No | No | N/A |
| `cookimport labelstudio-benchmark` | Optional (upload mode only; `--allow-labelstudio-write`) | Yes | `label_studio_tasks.jsonl` from prediction run |
| Interactive benchmark eval-only | No | Yes | existing prediction run (`label_studio_tasks.jsonl`) |
| `cookimport bench run` | No | Yes | `label_studio_tasks.jsonl` from offline pred run |

## 8. Common confusion points

### 8.1 "Benchmark should just score final outputs"

Today, benchmark contract is span/range based because gold is span/range based. Final outputs are downstream transforms and not the direct eval contract.

### 8.2 "Why is upload happening during benchmark?"

`labelstudio-benchmark` supports both upload and offline generation.
If you want no Label Studio side effects, use:
- `labelstudio-benchmark --no-upload`, or
- interactive benchmark `eval-only` mode (when prediction runs exist), or
- `cookimport bench run`.

### 8.3 "Why did split conversion fail with pickling?"

Split benchmark returns worker payloads through multiprocessing, so payload metadata must be pickle-safe primitives.
The concrete failure case that already happened was `unstructured_version` resolving to a module object (`cannot pickle 'module' object`) instead of a string.

## 9. If you want "regular output scoring" in the future

That is feasible, but it would be a different benchmark mode with a new contract.

At minimum it would need:
1. A deterministic mapping from staged outputs back to block/range coordinates
2. A label projection layer equivalent to current chunk/task label mapping
3. Consistency rules for multi-recipe and non-recipe text spans
4. Tests proving parity/reliability against current task-based scoring

Until that exists, task-artifact scoring remains the most deterministic way to compare against freeform gold spans.

## 10. Core code map

- `cookimport/bench/suite.py`: suite manifest load/validate
- `cookimport/bench/pred_run.py`: offline pred-run builder (calls `generate_pred_run_artifacts`)
- `cookimport/bench/runner.py`: full suite run + per-item eval + aggregate report
- `cookimport/bench/sweep.py`: parameter sweep orchestration
- `cookimport/bench/report.py`: aggregate metrics/report rendering
- `cookimport/bench/packet.py`: iteration packet generation
- `cookimport/labelstudio/ingest.py`: prediction artifact generation + optional upload
- `cookimport/labelstudio/eval_freeform.py`: freeform range loading + scoring
- `cookimport/cli.py`: command wiring for `stage`, `labelstudio-benchmark`, and `bench`

## 11. 2026-02-15 Task Chronology (Merged From docs/tasks)

### 11.1 2026-02-15_23.14.04 interactive benchmark credential resolution

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

### 11.2 2026-02-15_23.23.38 split benchmark pickle fix for unstructured metadata

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
- Avoid “just disable split mode” as a fix; root issue was payload shape/pickle safety.

### 11.3 2026-02-15_23.50.23 remove redundant interactive upload confirmation

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

### 11.4 2026-02-15_23.58.48 benchmark EPUB extractor selection

Merged source:
- `docs/tasks/2026-02-15_23.58.48 - benchmark-epub-extractor-choice.md`

Problem captured:
- Benchmark prediction generation was controlled by `C3IMP_EPUB_EXTRACTOR`, but benchmark command paths did not expose a per-run extractor choice.

Decision captured:
- Add `--epub-extractor` (`unstructured|legacy`) to `cookimport labelstudio-benchmark`.
- Prompt for extractor in interactive benchmark upload mode.
- Apply extractor choice via scoped env override around prediction import and restore previous env afterward.

Task verification/evidence preserved:
- helper tests added/updated for:
  - interactive extractor prompt wiring,
  - env propagation to prediction import,
  - invalid extractor rejection.

Known rejected path:
- “Use whichever extractor happens to be in env from prior runs” was explicitly treated as unreliable and replaced by explicit per-run selection.

## 12. Merged Discovery Provenance (Former `docs/understandings`)

### 12.1 2026-02-15_23.06.53 interactive eval-only gate

Merged source file:
- `2026-02-15_23.06.53-interactive-benchmark-eval-only-gate.md` (formerly in `docs/understandings`)

Preserved finding:
- Interactive benchmark shows `How would you like to benchmark?` only when both artifacts are discoverable:
  - gold exports under `**/exports/freeform_span_labels.jsonl`
  - prediction runs under `**/label_studio_tasks.jsonl`
- If either side is missing, flow defaults directly to upload mode.

### 12.2 2026-02-15_23.13.18 interactive upload credential resolution

Merged source file:
- `2026-02-15_23.13.18-interactive-benchmark-upload-credential-resolution.md` (formerly in `docs/understandings`)

Preserved rule:
- Interactive upload must resolve creds via `_resolve_interactive_labelstudio_settings(settings)` before calling `labelstudio_benchmark(...)`.
- Relying only on `labelstudio_benchmark` env/CLI resolution causes missing-credential exits in interactive mode.

### 12.3 2026-02-15_23.23.30 split pickling failure anatomy

Merged source file:
- `2026-02-15_23.23.30-benchmark-split-epub-unstructured-version-pickling.md` (formerly in `docs/understandings`)

Preserved finding:
- Split conversion jobs in `ProcessPoolExecutor` fail if any `ConversionResult` field is unpickleable.
- `getattr(unstructured, "__version__", "unknown")` can return a module-like object in some environments.

Durable rule:
- Normalize runtime version metadata to plain string before attaching to worker return payloads.
- Keep worker return payloads restricted to primitive-safe structures (`str`, `int`, `float`, `bool`, `None`, plus dict/list compositions of those).

### 12.4 2026-02-15_23.31.19 direct-call default semantics in eval

Merged source file:
- `2026-02-15_23.31.19-interactive-benchmark-eval-defaults.md` (formerly in `docs/understandings`)

Preserved finding:
- Direct Python calls into `labelstudio_eval(...)` (interactive/tests) previously inherited `typer.Option(...)` objects instead of runtime defaults, causing `TypeError` in threshold comparisons.

Durable rule:
- Keep CLI option metadata with `typing.Annotated[..., typer.Option(...)]` plus real Python defaults so both CLI parsing and direct calls behave correctly.
- Regression anchor: `tests/test_labelstudio_benchmark_helpers.py::test_labelstudio_eval_direct_call_uses_real_defaults`.

### 12.5 2026-02-15_23.31.46 benchmark scoring contract reminder

Merged source file:
- `2026-02-15_23.31.46-benchmark-scores-task-artifacts-not-stage-outputs.md` (formerly in `docs/understandings`)

Preserved rule:
- Benchmark scoring compares prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`).
- Stage/cookbook outputs may be written for review but are not the scoring contract.

Anti-loop note:
- Repeated attempts to “just score final outputs directly” will keep failing until a deterministic projection back to span coordinates is designed.

### 12.6 2026-02-15_23.48.49 upload confirmation removal

Merged source file:
- `2026-02-15_23.48.49-interactive-benchmark-upload-no-second-confirm.md` (formerly in `docs/understandings`)

Preserved rule:
- Interactive upload mode selection is already explicit intent; no second y/n upload confirmation should be reintroduced.

### 12.7 2026-02-15_23.58.38 extractor runtime switch behavior

Merged source file:
- `2026-02-15_23.58.38-benchmark-epub-extractor-runtime-switch.md` (formerly in `docs/understandings`)

Preserved rule:
- Prediction generation path reads `C3IMP_EPUB_EXTRACTOR`.
- Benchmark flows that need deterministic extractor choice must set this explicitly for run scope (CLI flag + scoped env override), not rely on whatever environment happened to be set earlier.

## 13. Runbook

For quick command examples and output interpretation:
- `docs/07-bench/runbook.md`
