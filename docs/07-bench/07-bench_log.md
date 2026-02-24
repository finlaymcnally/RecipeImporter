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

## 2. 2026-02-15 Task Chronology (archived merge)

### 2.1 2026-02-15_23.14.04 interactive benchmark credential resolution

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

## 3. Merged Discovery Provenance (Former docs/understandings; sources archived)

### 3.1 2026-02-15_23.06.53 interactive eval-only gate

Preserved finding:
- Interactive benchmark shows `How would you like to benchmark?` only when both artifacts are discoverable:
  - gold exports under `**/exports/freeform_span_labels.jsonl`
  - prediction runs under `**/label_studio_tasks.jsonl`
- If either side is missing, flow defaults directly to upload mode.

### 3.2 2026-02-15_23.13.18 interactive upload credential resolution

Preserved rule:
- Interactive upload must resolve creds via `_resolve_interactive_labelstudio_settings(settings)` before calling `labelstudio_benchmark(...)`.
- Relying only on `labelstudio_benchmark` env/CLI resolution causes missing-credential exits in interactive mode.

### 3.3 2026-02-15_23.23.30 split pickling failure anatomy

Preserved finding:
- Split conversion jobs in `ProcessPoolExecutor` fail if any `ConversionResult` field is unpickleable.
- `getattr(unstructured, "__version__", "unknown")` can return a module-like object in some environments.

Durable rule:
- Normalize runtime version metadata to plain string before attaching to worker return payloads.
- Keep worker return payloads restricted to primitive-safe structures (`str`, `int`, `float`, `bool`, `None`, plus dict/list compositions of those).

### 3.4 2026-02-15_23.31.19 direct-call default semantics in eval

Preserved finding:
- Direct Python calls into `labelstudio_eval(...)` (interactive/tests) previously inherited `typer.Option(...)` objects instead of runtime defaults, causing `TypeError` in threshold comparisons.

Durable rule:
- Keep CLI option metadata with `typing.Annotated[..., typer.Option(...)]` plus real Python defaults so both CLI parsing and direct calls behave correctly.
- Regression anchor: `tests/test_labelstudio_benchmark_helpers.py::test_labelstudio_eval_direct_call_uses_real_defaults`.

### 3.5 2026-02-15_23.31.46 benchmark scoring contract reminder

Preserved rule:
- Benchmark scoring compares prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`).
- Stage/cookbook outputs may be written for review but are not the scoring contract.

Anti-loop note:
- Repeated attempts to "just score final outputs directly" will keep failing until a deterministic projection back to span coordinates is designed.

### 3.6 2026-02-15_23.48.49 upload confirmation removal

Preserved rule:
- Interactive upload mode selection is already explicit intent; no second y/n upload confirmation should be reintroduced.

### 3.7 2026-02-15_23.58.38 extractor runtime switch behavior

Preserved rule:
- Prediction generation path reads `C3IMP_EPUB_EXTRACTOR`.
- Benchmark flows that need deterministic extractor choice must set this explicitly for run scope (CLI flag + scoped env override), not rely on whatever environment happened to be set earlier.

### 3.8 2026-02-22_13.15.24 bench + merge progress counter wiring

Preserved rules:
- `bench run` per-item counters (`item X/Y`) belong in `cookimport/bench/runner.py:run_suite(...)`.
- `bench sweep` owns outer `config X/Y` counters in `cookimport/bench/sweep.py` and should forward nested runner updates as `config X/Y | ...`.
- Split-job merge status counters shown in worker dashboards belong in `cookimport/cli.py:_merge_split_jobs(...)` callback emission, not in renderer/UI code.
- Shared formatter usage (`cookimport/core/progress_messages.py`) keeps message shape and counter clamping consistent across runtime paths.

Anti-loop note:
- Do not "patch in" counters at display-only layers when totals are unknown there; counters should originate at runtime loop boundaries.

## 4. 2026-02-22_13.16.17 spinner-progress-counters second pass (build record)

Problem captured:
- Known-size loops outside Label Studio prelabel still emitted phase-only text, so bench and split-merge throughput looked opaque.

Behavior contract preserved:
- Keep shared helper for counter formatting (`task`/`item`/`config`/`phase`).
- `bench run` emits `item X/Y` progress.
- `bench sweep` emits `config X/Y` and forwards nested runner updates as `config X/Y | item X/Y ...`.
- Split-merge status callback emits deterministic `merge phase X/Y: ...` updates and accounts for optional chunk-write phase in totals.

Verification and evidence preserved:
- Recorded command set:
  - `python -m pip install -e .[dev]`
  - `pytest -q tests/test_progress_messages.py tests/test_bench_progress.py tests/test_split_merge_status.py tests/test_labelstudio_ingest_parallel.py tests/test_labelstudio_prelabel.py`
  - `npm run docs:list`
- Recorded result: `23 passed`.
- Recorded emitted-message examples:
  - `item 1/2 [alpha] Processing...`
  - `config 1/2 | item 1/1 [alpha] Evaluating...`
  - `merge phase 1/12: Merging job payloads...`
  - `merge phase 12/12: Merge done`

Constraints and anti-loop notes:
- Counters should be generated in runtime loops where totals are truly known, then forwarded by wrappers.
- Shared formatter adoption is additive and dependency-free; avoid forking counter format logic in separate domains.
- Split-merge phase totals must remain monotonic when optional phases are present.

Rollback path preserved:
- Revert helper adoption in `cookimport/bench/runner.py`, `cookimport/bench/sweep.py`, and `cookimport/cli.py` plus associated tests/docs if contract needs reversal.

## 2026-02-22 understanding merge batch

### 2026-02-22_18.18.40 freeform overlap duplicates in gold eval

Preserved findings:
- Segment overlap intentionally duplicates boundary text across tasks, and export `span_id` includes `segment_id`; identical labeled ranges from adjacent segments therefore serialize as separate rows.
- Freeform evaluator now dedupes gold rows by `(source_hash, source_file, start_block_index, end_block_index)` before metrics are computed.
- Duplicate-label conflicts use majority resolution; exact ties are dropped from scored gold and reported under `gold_dedupe.conflicts`.

Debugging reminder:
- When gold denominators seem inflated, group rows by source + block-range keys and inspect differing `segment_id` values before modifying scoring code.

## 5. 2026-02-22_18.44.59 freeform gold dedupe default (build record)

Problem captured:
- Overlap-generated duplicate gold spans inflated benchmark/eval denominators and could skew recall/precision interpretations.

Behavior contract preserved:
- Freeform eval dedupes gold spans by default before scoring.
- Dedupe key is `(source_hash, source_file, start_block_index, end_block_index)`.
- Conflicting labels in one key resolve by majority count; exact ties are dropped from scored gold.
- Dedupe/conflict diagnostics are exposed in report outputs.

Verification and evidence preserved:
- Recorded runs:
  - `pytest -q tests/test_labelstudio_freeform.py` -> `13 passed in 0.17s`
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py` -> `39 passed, 2 warnings in 3.19s`
  - `pytest -q tests/test_stats_dashboard.py` -> `36 passed, 2 warnings in 1.39s`
- Regression coverage captured for:
  - same-label duplicates,
  - conflicting duplicates with majority winner,
  - conflicting duplicates with tie/drop behavior.

Constraints and anti-loop notes:
- Overlap in freeform segmentation is intentional; users should not need manual export cleanup for benchmark correctness.
- Avoid arbitrary tie-break winners; dropping exact ties preserves ambiguity visibility.

Rollback path preserved:
- Revert dedupe/conflict logic in `cookimport/labelstudio/eval_freeform.py` and matching tests/docs only if replacing with a different explicit policy (for example strict-fail or manual-resolution gate).

## 2026-02-23 archival merge batch (bench)

### 2026-02-12 offline benchmark suite baseline

Problem captured:
- Pipeline iteration depended too heavily on Label Studio upload loops and lacked a deterministic offline benchmark harness.

Major decisions preserved:
- Build offline suite around existing freeform eval (`evaluate_predicted_vs_freeform`) rather than a new scoring system.
- Extract `generate_pred_run_artifacts(...)` boundary so bench runs can generate predictions without Label Studio side effects.
- Produce AI-consumable iteration packets (`cases.jsonl`, `top_failures.md`) with severity ranking.

Anti-loop note:
- If proposed bench changes introduce a new parallel evaluation format, treat that as a major contract change and justify it explicitly.

### 2026-02-16_12.18.00 stage-vs-benchmark semantics unification

Problem captured:
- Users conflated staging, task creation, label export, and evaluation due to mixed terminology and weak artifact traceability.

Major decisions preserved:
- Add `run_manifest.json` across run-producing flows as shared provenance contract.
- Keep command names for compatibility; fix semantics through help/interactive wording.
- Add explicit offline mode (`--no-upload`) to `labelstudio-benchmark`.

Serious failed-path summary:
- Analytics mismatches were not cosmetic; stage `--out` history misalignment and timestamp resolver gaps caused misleading perf/dashboard views until fixed with parity tests.

Residual risk preserved:
- Fixture-related failures outside bench scope existed in full-suite runs during implementation; targeted modified-area suites were green.

## 2026-02-23 archival merge batch from `docs/understandings` (bench)

### 2026-02-22_22.25.41 freeform gold dedupe overlap behavior

Merged source:
- `docs/understandings/2026-02-22_22.25.41-freeform-gold-dedupe-overlap-behavior.md`

Preserved findings:
- Freeform export rows are evaluated after conversion to absolute block ranges (`touched_block_indices` / `touched_blocks` mapping).
- Dedupe key remains `(source_hash, source_file, start_block_index, end_block_index)`, so overlap changes duplicate row counts but not dedupe semantics.
- Exact-key label conflicts resolve by majority label; exact ties are dropped from scored gold.
- Different block ranges are intentionally treated as distinct examples (no near-range fuzzy merge).

## 2026-02-24 archival merge batch from `docs/understandings` (bench)

### 2026-02-23_12.31.53 freeform eval dedupe block-range explanation

Merged source:
- `docs/understandings/2026-02-23_12.31.53-freeform-eval-dedupe-block-range.md`

Preserved findings:
- Freeform exports can have zero exact-duplicate spans while still showing large eval dedupe removals, because eval normalizes spans to block ranges.
- Dedupe key remains block-range based (`source_hash`, `source_file`, `start_block_index`, `end_block_index`), so multiple sub-block spans in one block can collapse.
- `segment_overlap_requested=0` can still produce `segment_overlap_effective>0` under focus-window floor rules.

Anti-loop note:
- If dedupe looks "wrong," inspect block-range grouping and overlap-effective metadata before changing scoring code.

### 2026-02-23_12.53.47 strict-IoU collapse under span-granularity mismatch

Merged source:
- `docs/understandings/2026-02-23_12.53.47-pipeline-freeform-span-granularity-gap.md`

Preserved findings:
- Benchmark scoring compares prediction task ranges (`label_studio_tasks.jsonl`) to freeform gold ranges; it does not score staged final draft files directly.
- In observed runs, gold spans were mostly width `1` while prediction spans were often recipe-wide (`p50` ~24 blocks), forcing strict IoU below threshold even with broad overlap.
- High `any-overlap` and high `same-label any-overlap` with near-zero strict IoU indicates localization granularity mismatch, not necessarily extraction-content failure.

Anti-loop note:
- Do not treat strict `0.000` alone as parser collapse without checking width stats + any-overlap diagnostics.

### 2026-02-23_14.09.30 interactive benchmark mode contract (offline-only)

Merged source:
- `docs/understandings/2026-02-23_14.09.30-interactive-benchmark-upload-only.md`

Preserved rules:
- Interactive benchmark now branches by mode before execution and keeps only offline paths.
- Single offline mode uses benchmark run-settings chooser and can persist last-run settings snapshot.
- All-method mode stays offline, uses global defaults, and asks explicit proceed confirmation.

### 2026-02-23_14.42.57 benchmark-update original-plan audit closure

Merged source:
- `docs/understandings/2026-02-23_14.42.57-benchmark-update-original-plan-gap.md`

Preserved status:
- Practical-vs-strict metric overhaul is considered shipped end-to-end (eval, bench aggregate, CSV/dashboard, test coverage).
- Interactive benchmark drift to combo-only mode was removed; offline single-run + all-method branch is the expected runtime path.

### 2026-02-23_15.37.43 interactive benchmark split (single offline vs all-method)

Merged source:
- `docs/understandings/2026-02-23_15.37.43-interactive-all-method-benchmark-flow.md`

Preserved rules:
- Shared source/gold resolution helper is reused across benchmark modes.
- All-method runs execute offline benchmark loops per variant and produce ranked all-method reports.
- Codex-farm option prompts can remain visible but currently stay inert while recipe LLM pipeline is policy-locked off.

### 2026-02-23_16.03.51 upload mode vs offline scoring distinction

Merged source:
- `docs/understandings/2026-02-23_16.03.51-benchmark-upload-mode-vs-offline-eval.md`

Preserved findings:
- Scoring is fully local/offline against prediction artifacts and exported freeform gold; upload mode is optional side effect.
- Uploaded benchmark tasks can look blank because they are pipeline-scope tasks without prelabels.
- Scope-collision project naming can auto-suffix (`-1`, `-2`, ...) during upload.

### 2026-02-23_16.11.07 interactive default should stay offline

Merged source:
- `docs/understandings/2026-02-23_16.11.07-interactive-benchmark-default-offline.md`

Preserved rules:
- Interactive benchmark default first choice is single-offline.
- Interactive benchmark should not resolve Label Studio credentials in either single-offline or all-method mode.

### 2026-02-23_17.26.00 practical-vs-strict metrics wired end-to-end

Merged source:
- `docs/understandings/2026-02-23_17.26.00-practical-vs-strict-benchmark-metrics-shipped.md`

Preserved contract:
- Keep strict/localization and practical/content-overlap tracks together in eval/reporting.
- Maintain granularity-mismatch diagnostics in report and dashboard surfaces.

### 2026-02-23_23.19.10 benchmark processed-output path map

Merged source:
- `docs/understandings/2026-02-23_23.19.10-benchmark-processed-output-paths.md`

Preserved rules:
- `labelstudio-benchmark` writes processed outputs by default under configured output root.
- Interactive all-method writes processed outputs under benchmark timestamp + source/config hierarchy.
- `bench run` does not emit processed cookbook outputs by default.

### 2026-02-23_23.36.37 interactive prompt order + offline-only options

Merged source:
- `docs/understandings/2026-02-23_23.36.37-interactive-benchmark-offline-only-order.md`

Preserved rules:
- Prompt order is mode-first, then mode-specific prompts.
- Interactive menu keeps only offline options; upload remains non-interactive CLI-only behavior.

### 2026-02-23_23.38.41 all-method single-pair matching gap (historical)

Merged source:
- `docs/understandings/2026-02-23_23.38.41-all-method-single-pair-matching-gap.md`

Preserved historical finding:
- Earlier all-method flow resolved only one `(gold_spans, source_file)` pair and could miss valid exports when source hints existed only in segment-manifest metadata.

Anti-loop note:
- If all-golden mode regresses, verify segment-manifest fallback before rewriting matcher semantics.

### 2026-02-23_23.49.22 all-golden matching fallback order (current)

Merged source:
- `docs/understandings/2026-02-23_23.49.22-all-method-all-golden-matching.md`

Preserved rules:
- All-golden scope now fans out across matched freeform exports.
- Source-hint fallback order is manifest -> first labeled span row -> first segment-manifest row.
- Matching target remains top-level importable files by exact filename.

### 2026-02-24_00.20.26 all-method run-settings bypass contract

Merged source:
- `docs/understandings/2026-02-24_00.20.26-interactive-all-method-skips-run-settings.md`

Preserved rules:
- Single-offline keeps run-settings chooser.
- All-method skips chooser and uses global benchmark defaults.
- All-method should not overwrite `last_run_settings_benchmark` snapshot.

### 2026-02-24_00.29.50 all-method dashboard progress hook

Merged source:
- `docs/understandings/2026-02-24_00.29.50-all-method-dashboard-progress-hook.md`

Preserved implementation shape:
- All-method wraps per-config `labelstudio_benchmark(...)` calls with scoped benchmark progress overrides.
- Overrides forward worker activity to outer dashboard spinner while suppressing nested spinner and per-config summary noise.
- Outer dashboard tracks queue state + source/config counters + active task line.

### 2026-02-24_00.37.24 timing telemetry gap (historical baseline)

Merged source:
- `docs/understandings/2026-02-24_00.37.24-all-method-benchmark-timing-telemetry-gap.md`

Preserved historical context:
- This documented that all-method quality metrics shipped before per-stage timing telemetry existed.
- It should be read as pre-telemetry baseline for later timing-contract changes.

### 2026-02-24_00.50.03 parallel queue + split-slot + CSV locking

Merged source:
- `docs/understandings/2026-02-24_00.50.03-all-method-parallel-split-slot-locking.md`

Preserved runtime rules:
- All-method uses bounded outer queue (4 inflight by default).
- Split-heavy conversion is independently gated with 2-slot lock files under source all-method root.
- History CSV appends are guarded by file locks to prevent parallel write corruption.

### 2026-02-24_08.56.28 benchmark timing contract + fallback order

Merged source:
- `docs/understandings/2026-02-24_08.56.28-benchmark-timing-contract-and-fallbacks.md`

Preserved contract:
- Prediction generation, benchmark orchestration, and eval artifacts should all emit benchmark `timing` payloads.
- `append_benchmark_csv(...)` timing precedence is explicit argument -> processed report timing fallback -> blanks.
- Timing totals are floored against known subphase sums to avoid under-reported runtime in fast/mocked paths.
- All-method reports include per-config timing plus source/run timing summaries sufficient for coarse runtime analysis.

## 2026-02-24 docs/tasks archival merge batch (bench ExecPlans)

### 2026-02-23 Benchmark-update draft -> shipped practical-vs-strict metrics

Merged sources:
- `docs/tasks/Benchmark-update copy.md` (unchecked draft state)
- `docs/tasks/Benchmark-update.md` (completed implementation record)

Problem captured:
- Strict IoU-only headline metrics frequently looked catastrophic (`0.000`) even when cookbook outputs were practically usable, driving repeated confusion loops.

Shipped decisions/outcomes preserved:
- Keep strict IoU scoring semantics unchanged and add practical/content-overlap metrics alongside strict metrics.
- Add width stats + granularity mismatch detection so strict-low/practical-high cases are explicitly labeled.
- Extend bench aggregates, iteration-packet severity ranking, CSV history rows, and dashboard views to include practical track fields.
- Keep schema evolution additive; old rows remain readable.

Serious failed-path summary:
- A mistaken interactive combo-only benchmark direction was introduced during this period and then explicitly removed; interactive behavior was restored before later offline/all-method menu changes.

Evidence preserved from task:
- Focused regression run in `.venv` covering freeform eval, bench, dashboard analytics, and interactive benchmark helpers was recorded as passing.
- Optional follow-up left open in task: full `pytest -q` and manual end-to-end benchmark/dashboard smoke on local golden data.

Anti-loop note:
- Do not treat strict `f1=0` alone as parser failure; inspect practical metrics + width mismatch flags first.

### 2026-02-23_15.12.00 initial all-method benchmark mode

Merged source:
- `docs/tasks/All-method-benchmark.md`

Problem captured:
- Users needed one interactive way to evaluate multiple extraction configurations against the same freeform gold scorer, not extractor-heuristic race output.

Decisions preserved:
- Reuse `labelstudio_benchmark(...)` as the single-run primitive in offline mode (`no_upload=True`) for each config.
- Define method-space variant builder in one place and print total config count before execution.
- Keep Codex Farm permutations explicit opt-in with policy lock safety.

Evidence preserved:
- Task records regression coverage for variant counting, mode wiring, Codex Farm gating, and aggregate report generation.

### 2026-02-23_23.37.00 all-golden-set scope expansion

Merged source:
- `docs/tasks/2026-02-23_23.37.00-all-method-select-all-golden-sets.md`

Problem captured:
- All-method originally ran one source/gold pair and required manual repetition for multiple books.

Decisions preserved:
- Add explicit scope chooser: `single` vs `all_matched`.
- Resolve source hints by metadata filename matching with fallback order:
  1. manifest `source_file`,
  2. first non-empty freeform span row `source_file`,
  3. first non-empty segment-manifest row `source_file`.
- Keep per-source reports unchanged and add combined root summary report for multi-source runs.

Evidence preserved:
- Task records targeted helper tests plus `pytest -m smoke` passing after implementation.

### 2026-02-24_00.26.23 bounded queue parallelization + split-slot gating

Merged source:
- `docs/tasks/2026-02-24_00.26.23-all-method-benchmark-parallelization.md`

Problem captured:
- Serial all-method runs underused available compute and were too slow on long EPUB workloads.

Design revisions preserved:
- Revision 1 considered lower pipeline concurrency.
- Final shipped model kept `4` in-flight pipelines with independent `2` split-phase slots (heavy-phase bottleneck gating).

Decisions preserved:
- Outer parallelism at config layer (not ingestion rewrite).
- Process-based workers for outer queue because benchmark paths use process-global `C3IMP_EPUB_*` env overrides.
- Shared lock protection for split-slot acquisition and CSV appends.
- Startup fallback to serial when process executor cannot initialize.

Environment-specific discovery:
- Restricted environments can block multiprocessing semaphore creation (`PermissionError`); tests were adapted to deterministic queue/gate unit coverage.

Evidence preserved:
- Task records passing targeted suites (`labelstudio_benchmark_helpers`, `labelstudio_ingest_parallel`, `analytics/perf_report`) and smoke tests.

### 2026-02-24_00.29.50 persistent all-method dashboard spinner

Merged source:
- `docs/tasks/2026-02-24_00.29.50-all-method-dashboard-spinner.md`

Problem captured:
- Per-config completion dumps flooded terminal output and hid current run position during large sweeps.

Decisions preserved:
- Keep one benchmark primitive and add scoped runtime overrides instead of forking benchmark code.
- Introduce explicit `_AllMethodProgressDashboard` state model.
- Suppress nested benchmark spinner/summary output while forwarding worker telemetry to one outer spinner.

Evidence preserved:
- Task records targeted helper test run: `12 passed, 50 deselected, 2 warnings`.

Anti-loop note for this batch:
- If all-method output becomes noisy again, first inspect scoped benchmark progress override plumbing before changing report-generation code paths.
