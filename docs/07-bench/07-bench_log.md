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

## 2026-02-24_15.21.53 to 2026-02-24_21.31.58 archival merge batch from `docs/understandings` (bench)

### 2026-02-24_15.21.53 split-slot default bottleneck

Preserved findings:
- Config-level inflight parallelism was not the full throughput story; split-phase slot caps were a hidden heavy-phase limiter.
- Raising split-slot defaults to match inflight defaults was the practical correction for conversion-heavy sweeps.

### 2026-02-24_15.22.29 spinner snapshot forwarding + split-slot stdout noise

Preserved findings:
- Nested dashboard payloads were being re-rendered as task text, causing recursive/duplicated spinner lines.
- Worker runs without callbacks leaked split-slot fallback `print(...)` output into interactive spinner streams.

Durable fix pattern:
- Detect dashboard-shaped payloads and rerender from shared dashboard state.
- Keep a callback set for worker benchmark calls (no-op if needed) so split-slot telemetry avoids raw stdout fallbacks.

### 2026-02-24_15.28.12 interactive scheduler settings flow

Preserved findings:
- Scheduler caps should be user-tunable from `cookimport.json` and settings menu without code edits.
- Invalid scheduler values should fail back to bounded defaults, not silently collapse to `1`.

### 2026-02-24_15.53.58 heavy-slot flow map

Preserved findings:
- Split-slot gating occurs inside prediction generation; outer scheduler sees completion unless additional telemetry is surfaced.
- Heavy-slot occupancy depends on maintaining enough prep/split-wait backlog, not only increasing split-slot count.

### 2026-02-24_15.57.24 single-config lock stall recovery

Preserved findings:
- One stuck config future can keep source completion at `N-1/N` while other artifacts are already complete.
- In captured incident, one split-slot lock remained held and parent waited indefinitely in completion loop.

Operational recovery preserved:
- Terminate the stuck worker process only; parent flow can mark that config failed and still flush per-source + combined reports.

### 2026-02-24_16.10.45 smart scheduler event-gating dependency

Preserved findings:
- Smart-vs-fixed utilization comparisons are meaningful only when phase telemetry is faithfully captured and split-slot behavior is represented.
- `.scheduler_events/config_###.jsonl` files were the durable admission + post-run utilization data surface.

### 2026-02-24_16.11.17 timeout watchdog + failed-only retry path

Preserved findings:
- Reliability hook is source-level future orchestration (`wait(..., timeout=...)` with scheduler poll), not deep benchmark internals.
- Timeout flow marks config failed, recycles worker pool, requeues pending work, and continues.
- Retry passes rerun failed config indices only and collapse reporting to latest attempt per index.

### 2026-02-24_20.56.39 smart scheduler tail-buffer headroom

Preserved findings:
- Smart heavy-target logic can still underutilize heavy slots when long post-stage configs consume all inflight slots.
- Tail buffer headroom (equal to split slots) was identified as the fix for this starvation pattern.

### 2026-02-24_20.57.46 active-config map + ETA suffix placement

Preserved findings:
- Submission-time current-config tracking was stale in parallel mode.
- Correct rendering requires active-config map updates on start/finish and summary-level ETA suffix placement (top line only).

### 2026-02-24_21.05.24 partial nested snapshot rerender

Preserved findings:
- Nested callbacks can emit stale/partial dashboard payloads; wrapper should rerender from canonical shared state instead of forwarding broken snapshots.

### 2026-02-24_21.11.33 all-matched source serialization limit

Preserved findings:
- Serial source loop in all-matched mode capped CPU at one source scheduler at a time even with many pending sources.

### 2026-02-24_21.31.58 bounded source-parallel dispatch + refresh contract

Preserved findings:
- Safe source-level parallelism used bounded `ThreadPoolExecutor` dispatch over existing per-source runners.
- Deterministic source-order reporting required precomputed source order + indexed result slots.
- Shared spinner dashboard state needed internal locking.
- Refresh policy split: per-source refresh in serial mode; single batched refresh at multi-source completion in parallel mode.

Anti-loop note for this batch:
- If heavy slots idle with pending configs, inspect phase telemetry + tail-buffer inflight resolution before changing split-slot lock mechanics.

## 2026-02-24_22.44.09 archival merge batch from `docs/tasks` (all-method benchmark)

### 2026-02-24_15.21.53 split-slot default raised to four

Merged source:
- `docs/tasks/2026-02-24_15.21.53-all-method-split-slot-default-four.md`

Problem captured:
- Inflight already allowed 4, but split-phase default at 2 limited conversion-heavy concurrency.

Decision/outcome preserved:
- Keep inflight default at 4.
- Raise split-slot default to 4 to remove hidden heavy-phase cap.

Evidence preserved:
- `pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -k resolve_all_method_scheduler_limits_defaults` -> `1 passed, 67 deselected`.
- full helper suite at task time -> `68 passed`.

### 2026-02-24_15.22.29 spinner-noise cleanup (dashboard recursion + split stdout)

Merged source:
- `docs/tasks/2026-02-24_15.22.29-all-method-spinner-noise-cleanup.md`

Problem captured:
- Interactive spinner had duplicated dashboard/task lines and raw split-slot acquire/release output.

Decision/outcome preserved:
- Forward dashboard snapshots without recursive wrapping.
- Ensure worker benchmark paths keep callback wiring (no-op callback acceptable) so split-slot telemetry avoids raw `print(...)` fallback.
- Escape queue markers so literal `[x]` style output survives rich rendering.

Evidence preserved:
- focused spinner/helper selection -> `6 passed, 61 deselected`.

### 2026-02-24_15.28.12 scheduler settings keys added to interactive config

Merged source:
- `docs/tasks/2026-02-24_15.28.12-all-method-scheduler-settings-keys.md`

Problem captured:
- Scheduler limits required code edits instead of settings updates.

Decision/outcome preserved:
- Expose scheduler settings in menu and persist to `cookimport.json`.
- Keep these controls as operator-level global settings, not per-run extraction config.
- Invalid values fall back to bounded defaults.

Evidence preserved:
- focused settings/scheduler selection -> `4 passed, 66 deselected`.
- full helper suite at task time -> `70 passed`.

### 2026-02-24_15.52.15 smart heavy-slot scheduler implementation

Merged source:
- `docs/tasks/2026-02-24_15.52.15-smart-heavy-slot-scheduler-all-method.md`

Problem captured:
- Existing bounded queue could still produce heavy-stage CPU spikes/valleys due to non-phase-aware refill.

Decision/outcome preserved:
- Implement phase telemetry + phase-aware admission targeting heavy-slot occupancy.
- Persist per-config scheduler events under `.scheduler_events/config_###.jsonl`.
- Include scheduler metrics in per-source and multi-source reports.

Evidence preserved:
- scheduler-focused helper selection -> `6 passed, 69 deselected`.
- full helper suite at task time -> `75 passed`.

Known remaining gap recorded by original task:
- Manual interactive evidence snippet was still pending in that task session.

### 2026-02-24_16.01.56 timeout watchdog + failed-only retry

Merged source:
- `docs/tasks/2026-02-24_16.01.56-all-method-timeout-and-retry.md`

Problem captured:
- One stuck config could hold run completion indefinitely.

Decision/outcome preserved:
- Timeout enforcement in outer per-source future scheduling loop.
- Timeout marks config failed, recycles worker pool, and continues.
- Retry loop reruns failed config indices only; reporting keeps latest attempt per config index.
- Interactive/settings defaults recorded at task time: `all_method_config_timeout_seconds=900`, `all_method_retry_failed_configs=1`.

Evidence preserved:
- focused all-method timeout/retry selection -> `6 passed, 69 deselected`.
- broader all-method selection -> `21 passed, 54 deselected`.

### 2026-02-24_20.56.39 smart tail-buffer headroom

Merged source:
- `docs/tasks/2026-02-24_20.56.39-smart-scheduler-tail-buffer-headroom.md`

Problem captured:
- Pending configs remained while heavy slots idled because post-stage configs consumed inflight capacity.

Decision/outcome preserved:
- Keep smart admission target (`heavy + wing`) and add deterministic smart tail buffer headroom (`+ split slots`) to effective inflight.
- Root cause explicitly recorded as inflight accounting under post-stage drain, not missing event telemetry.

Evidence preserved:
- scheduler-focused helper selection -> `7 passed, 69 deselected`.
- full helper suite at task time -> `76 passed`.

### 2026-02-24_20.57.46 active-config tracking + ETA placement fix

Merged source:
- `docs/tasks/2026-02-24_20.57.46-all-method-spinner-polish-active-config-eta.md`

Problem captured:
- `current config` display stayed stale in parallel mode and ETA suffix landed on trailing task line.

Decision/outcome preserved:
- Track active configs as state map; render slug or index range from active state.
- For multiline dashboard payloads, append ETA/elapsed suffixes to first summary line only.

Evidence preserved:
- focused spinner/helper selection -> `6 passed, 72 deselected`.
- full helper suite command passed.

### 2026-02-24_21.05.24 stale/partial nested snapshot rerender stabilization

Merged source:
- `docs/tasks/2026-02-24_21.05.24-all-method-spinner-queue-stability-rerender.md`

Problem captured:
- Multi-source nested progress occasionally showed incomplete queue rows.

Decision/outcome preserved:
- Keep no-rewrap forwarding for dashboard-shaped messages, but rerender from shared canonical dashboard state when nested snapshot text is stale/partial.

Evidence preserved:
- focused helper selection passed.
- full helper suite command passed.

### 2026-02-24_21.09.55 source-level parallel all-matched dispatch

Merged source:
- `docs/tasks/2026-02-24_21.09.55-parallel-source-all-method-benchmark.md`

Problem captured:
- All-matched source loop was serial, leaving CPU headroom unused.

Decision/outcome preserved:
- Add settings-controlled bounded source parallelism (`all_method_max_parallel_sources`, default 2).
- Use thread-based outer source dispatcher over existing process-based per-source config layer.
- Preserve deterministic source-order report emission via indexed source slots.
- Synchronize shared dashboard model with lock.
- Batch dashboard refresh once at multi-source completion in parallel source mode.

Evidence preserved:
- `python -m py_compile cookimport/cli.py tests/labelstudio/test_labelstudio_benchmark_helpers.py` passed.
- focused helper selection -> `15 passed`.
- full helper suite at task time -> `84 passed`.

Known remaining gap recorded by original task:
- Manual interactive all-matched evidence snippet was pending in that task session.

Anti-loop note for this merge batch:
- If throughput looks low while pending work remains, debug in this order: scheduler phase telemetry and inflight/tail-headroom resolution, then active-config/spinner forwarding, then source-level parallel cap and refresh batching. Avoid jumping first to split-lock internals unless those signals implicate lock contention directly.

## 2026-02-25 understanding merge batch (stage-vs-benchmark map + stage-block artifact contract)

### 2026-02-25_17.25.05 stage vs benchmark artifact-surface clarification

Merged source:
- `docs/understandings/stage-vs-benchmark-pipeline.md`

Problem captured:
- Repeated confusion about whether benchmark runs are equivalent to stage/import runs and whether menu `5)` outputs can be used for downstream cookbook import.

Decision/outcome preserved:
- Stage and benchmark share conversion + stage writers; benchmark is not a separate importer engine.
- Benchmark runs remain artifact-surface different by design (pred/eval roots under `data/golden/benchmark/...`).
- Processed stage outputs produced during benchmark remain valid cookbook-import artifacts.

Anti-loop note:
- Debug pipeline differences from shared conversion/stage code first, then inspect artifact-surface divergence.

### 2026-02-25_17.26.24 stage-block evidence required in prediction-run roots

Merged source:
- `docs/understandings/2026-02-25_17.26.24-stage-block-benchmark-prediction-artifacts.md`

Problem captured:
- Older helper fixtures with only `label_studio_tasks.jsonl` started failing once benchmark scoring moved to stage-block evidence.

Decision/outcome preserved:
- `labelstudio-benchmark` and `bench run` require `stage_block_predictions.json` + `extracted_archive.json` in pred-run roots.
- Generation path remains:
  - stage writer emits `.bench/<workbook_slug>/stage_block_predictions.json`,
  - pred-run builder copies that into root `stage_block_predictions.json`.

Anti-loop note:
- Missing required pred-run artifacts is a fixture/build contract break, not an eval-math regression.

### 2026-02-25_17.27.08 historical per-label zeros on legacy pipeline-task scoring

Merged source:
- `docs/understandings/2026-02-25_03.41.19-per-label-zeros-notes-yield-time-variant.md`

Problem captured:
- Historical reports showed zero precision/recall and `pred_total=0` for notes/variants/time/yield labels even when staged exports looked semantically correct.

Preserved explanation:
- Legacy pipeline-task span scoring depended on available chunk types/ranges and did not directly score staged draft semantic fields.
- Missing chunk classes for those labels caused the per-label zeros in that older surface.

Current contract clarification:
- Stage-block scoring is now the active benchmark contract and removes that specific `pred_total=0 because chunk type missing` failure mode.

Anti-loop note:
- When triaging old benchmark artifacts, verify scorer generation/version before reworking current extractor/stager logic.

## 2026-02-25_17.26.21 docs/tasks bench-refactor archival merge

Merged source:
- `docs/tasks/bench-refactor.md`

Problem captured:
- Benchmark could report near-zero or `pred_total=0` for labels like notes/time/yield/variant even when staged outputs contained those fields, because prediction surface was pipeline-task artifacts rather than staged export evidence.

Major decisions preserved:
- Canonical prediction surface is staged evidence (`.bench/.../stage_block_predictions.json` copied into pred-run roots), not Label Studio pipeline tasks.
- Scoring model is block-level classification with exhaustive gold requirements, not span IoU.
- Knowledge scoring should read stage knowledge artifacts, not recipe-local metadata.
- Keep compatibility alias mismatch files while migrating tooling to block-native artifacts.
- Preserve dashboard/CSV continuity by mapping new block metrics into existing strict/practical columns plus explicit new metrics.

Surprises/discoveries preserved:
- Pred-run roots must contain both `stage_block_predictions.json` and `extracted_archive.json`; legacy fixtures with only `label_studio_tasks.jsonl` fail immediately.
- Gold loading needed explicit conflict/missing-label enforcement to avoid silent metric inflation.
- Variant/time/yield correctness depends on provenance projection from stage outputs; pipeline chunk types were insufficient for those classes.

What shipped:
- Stage evidence writer: `cookimport/staging/stage_block_predictions.py`.
- Block evaluator: `cookimport/bench/eval_stage_blocks.py`.
- CLI wiring updates for `labelstudio-benchmark`, `bench run`, and `bench eval-stage`.
- Eval artifacts/metrics updated to include:
  - `overall_block_accuracy`
  - `macro_f1_excluding_other`
  - `worst_label_recall`

Task-recorded remaining gaps:
- Full legacy scope removal (`pipeline`, `canonical-blocks`) flagged as pending outside benchmark scorer migration.
- One real golden-set end-to-end acceptance run was still pending in that task snapshot.

Anti-loop notes:
- If benchmark fails on missing stage-block files, fix artifact generation/fixtures before changing evaluator math.
- Do not reintroduce span-IoU as primary truth for this benchmark contract; use block evidence first.

## 2026-02-25 to 2026-02-26 understanding merge batch (EPUB legacy migration + canonical eval hardening)

### 2026-02-25_18.54.00 interactive benchmark load path and legacy extractor alias migration

Merged source:
- `docs/understandings/2026-02-25_18.54.00-interactive-benchmark-legacy-epub-setting.md`

Problem captured:
- Interactive benchmark could fail before prompt flow when old `cookimport.json` stored `epub_extractor=legacy`.

Decision/outcome preserved:
- Normalize legacy extractor aliases in `RunSettings.from_dict(...)` because interactive defaults are built there.
- Do not rely on later CLI flag-only normalization to protect interactive startup.

### 2026-02-25_19.00.51 multi-label freeform gold support in stage-block eval

Merged source:
- `docs/understandings/2026-02-25_19.00.51-stage-block-eval-multilabel-gold.md`

Problem captured:
- `load_gold_block_labels(...)` treated multi-label block assignments as fatal conflicts.

Decision/outcome preserved:
- Allow multi-label gold per block.
- Score predicted block correct when label is inside allowed set.
- Keep missing predicted block rows defaulted to `OTHER` and record diagnostics in `gold_conflicts.jsonl`.

Anti-loop note:
- Do not revert to single-label-only assumptions for freeform gold exports.

### 2026-02-25_19.14.33 benchmark/gold extractor parity failure mode

Merged source:
- `docs/understandings/2026-02-25_19.14.33-benchmark-gold-extractor-parity.md`

Problem captured:
- Reports could show implausible metrics (for example per-label zero precision/recall) even with matching `source_hash`.

Evidence preserved from investigated run:
- Benchmark run: `data/golden/benchmark-vs-golden/2026-02-25_19.07.15`.
- Gold export used `epub_extractor=unstructured`; benchmark prediction used `beautifulsoup`.
- Gold block labels ended around block ~1470 while predictions extended to block 1993.
- All predicted `RECIPE_VARIANT` blocks landed in missing-gold indices, yielding zero precision/recall.

Decision/outcome preserved:
- Enforce extractor/blockization parity between gold-generation run and benchmark prediction run for stage-block mode.

### 2026-02-25_22.19.47 severe blockization-mismatch guard

Merged source:
- `docs/understandings/2026-02-25_22.19.47-gold-blockization-mismatch-guard.md`

Problem captured:
- Matching `source_hash` can still hide invalid block-level comparisons when extractor profile differs.

Decision/outcome preserved:
- Capture/compare blockization fingerprints from gold spans and prediction archives.
- Fail fast with `gold_prediction_blockization_mismatch` when fingerprint mismatch plus severe missing-gold drift indicates invalid comparison.
- Keep mild mismatch as warning-level so small fixtures remain evaluable.

### 2026-02-25_23.02.58 all-method runtime hotspot is canonical evaluation

Merged source:
- `docs/understandings/2026-02-25_23.02.58-all-method-canonical-eval-runtime-hotspot.md`

Problem captured:
- Slow all-method runs were initially suspected to be split conversion or scheduler under-utilization.

Evidence preserved from inspected report:
- Run: `.../2026-02-25_22.50.10/all-method-benchmark/seaandsmokecutdown/all_method_benchmark_report.json`.
- Wall time `399.60s` for 15 configs with ~5x effective parallelism.
- Average config runtime `133.19s`, with average `evaluation_seconds` `117.25s` (~88%).
- Slowest configs spent ~176-180s in evaluation phase.

Decision/outcome preserved:
- Treat evaluate phase as first optimization target before split scheduling tweaks.
- Add finer evaluate telemetry instead of relying on coarse scheduler events only.

### 2026-02-25_23.11.15 timing telemetry plumbing boundary

Merged source:
- `docs/understandings/2026-02-25_23.11.15-benchmark-eval-telemetry-plumbing.md`

Problem captured:
- Rich eval telemetry was lost when benchmark report timing was normalized for CSV/history outputs.

Decision/outcome preserved:
- Preserve detailed structures in `evaluation_telemetry`.
- Flatten required numeric values into `evaluate_*` (including resource/work checkpoints) so `_timing_with_updates(...)` keeps them.
- Add explicit `evaluate_started`/`evaluate_finished` scheduler events for timeline clarity.

### 2026-02-25_23.15.51 cProfile hotspot confirmation (`SequenceMatcher`)

Merged source:
- `docs/understandings/2026-02-25_23.15.51-canonical-eval-sequencematcher-profile.md`

Problem captured:
- Need proof of exact canonical-eval hotspot before attempting alignment rewrite.

Evidence preserved:
- Profiled config runtime `evaluate_canonical_text(...)`: `307.68s`.
- `_align_prediction_blocks_to_canonical(...)`: `306.02s`.
- `SequenceMatcher.get_matching_blocks` / `find_longest_match` consumed almost all alignment runtime.

Decision/outcome preserved:
- Prioritize bounded/alternative alignment strategies; scheduler-only optimization cannot remove this CPU wall.

### 2026-02-25_23.38.52 canonical micro-telemetry + slow-run profile artifacts

Merged source:
- `docs/understandings/2026-02-25_23.38.52-canonical-eval-micro-telemetry-and-profile-hook.md`

Problem captured:
- Coarse `evaluate_seconds` and `alignment_seconds` were insufficient for diagnosing normalization vs matcher vs mapping cost.

Decision/outcome preserved:
- Emit alignment micro-subphases in telemetry:
  - `alignment_normalize_prediction_seconds`
  - `alignment_normalize_canonical_seconds`
  - `alignment_sequence_matcher_seconds`
  - `alignment_block_mapping_seconds`
- Emit text-size work units into `evaluate_work_*` checkpoints.
- Add optional slow-run profile hooks controlled by env vars (`COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS`, `COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N`).

### 2026-02-25_23.39.17 fast alignment fallback guardrails + scheduler eval-tail cap

Merged source:
- `docs/understandings/2026-02-25_23.39.17-canonical-fast-align-and-eval-tail-cap.md`

Problem captured:
- Alignment speedups and scheduler tail tuning can regress accuracy/throughput differently if coupled without guardrails.

Decision/outcome preserved:
- Alignment auto mode should attempt bounded monotonic fast alignment first and fallback to legacy full-book alignment when confidence/coverage guardrails fail.
- Persist strategy telemetry (`requested strategy`, actual strategy, fallback reason).
- Smart scheduler tail growth is evaluate-phase-aware and capped with `all_method_max_eval_tail_pipelines`.

### 2026-02-26_03.10.00 canonical-text default for all-method benchmarks

Merged source:
- `docs/understandings/2026-02-26_03.10.00-canonical-text-all-method-default.md`

Problem captured:
- Stage-block mode fails valid cross-extractor comparisons because block indices drift between extractor permutations.

Decision/outcome preserved:
- Keep `stage-blocks` for blockization-parity checks.
- Make `canonical-text` the default for all-method sweeps so one freeform gold export can evaluate extractor permutations.
- Interactive all-method forcing of canonical-text is intentional and should remain unless contract changes.

Anti-loop notes for this batch:
- If per-label metrics look impossible, verify extractor/blockization parity and mismatch-guard diagnostics before touching scorer formulas.
- If all-method runs are slow, profile canonical alignment first; split-slot tuning alone is insufficient.
- When telemetry fields disappear from CSV/history, check numeric checkpoint flattening in `_timing_with_updates(...)` before changing renderer code.

## 2026-02-25 docs/tasks archival merge batch (bench)

### 2026-02-25_18.54.30 benchmark legacy extractor setting migration

Merged source:
- `docs/tasks/2026-02-25_18.54.30-benchmark-legacy-epub-extractor-migration.md`

Problem captured:
- Interactive benchmark setting load crashed when persisted `cookimport.json` still held `epub_extractor=legacy`.

Decision/outcome preserved:
- Add compatibility migration in `RunSettings.from_dict(...)` from `legacy` -> `beautifulsoup`.
- Keep accepted extractor choices unchanged for new settings/UI.

Evidence preserved:
- Before: enum `ValidationError`.
- After: migration warning + resolved `beautifulsoup`.
- Regression suite: `tests/llm/test_run_settings.py` with `9 passed`.

Anti-loop note:
- If settings load regresses on old configs, check migration aliases first before changing benchmark runtime flow.

### 2026-02-25_19.00.51 stage-block eval multi-label gold support

Merged source:
- `docs/tasks/2026-02-25_19.00.51-multilabel-freeform-benchmark-eval.md`

Problem captured:
- Multi-label freeform gold blocks caused hard conflicts and benchmark eval crashes.

Decision/outcome preserved:
- Allow multiple gold labels per block and treat prediction as correct on any-label match.
- Keep missing-gold default-to-`OTHER` behavior.
- Log both multi-label and missing-gold conditions into `gold_conflicts.jsonl`.
- Keep report schema stable; add `gold_labels` to mismatch rows for disambiguation.

Evidence preserved:
- Before: `ValueError: Gold conflicts detected...`.
- After: end-to-end eval passes with diagnostics.
- Verification anchor: `pytest tests/bench/test_eval_stage_blocks.py`.

### 2026-02-25 fix-gold ExecPlan (completed by 22:19Z): severe mismatch fail-fast guard

Merged source:
- `docs/tasks/fix-gold.md`

Problem captured:
- Gold/prediction runs from different extractor/blockization profiles could still score and quietly generate misleading metrics due to broad default-`OTHER` backfill.

Decision/outcome preserved:
- Build blockization profiles from gold spans + prediction archive metadata.
- Fail only on combined signal: metadata mismatch plus severe drift.
- Keep non-severe mismatch as warning to avoid breaking small fixtures.
- Persist diagnostics (`gold_prediction_blockization_mismatch`) in `gold_conflicts.jsonl` and profile snapshots in `eval_report.json`.

Evidence preserved:
- Regression coverage added for both fatal and warning-only mismatch paths in `tests/bench/test_eval_stage_blocks.py`.

Anti-loop note:
- Do not relax this guard by removing mismatch diagnostics; investigate extractor parity first when metrics look implausible.

### 2026-02-25_23.15.54 canonical eval speedup + eval-tail scheduler control

Merged source:
- `docs/tasks/2026-02-25_23.15.54-all-method-canonical-eval-speedups.md`

Problem captured:
- All-method wall time was dominated by canonical evaluation alignment (`SequenceMatcher` hot path).

Decision/outcome preserved:
- Added canonical alignment strategies (`auto`, `fast`, `legacy`) with guarded fallback.
- Replaced heavy overlap loops with interval-sweep projections.
- Added evaluate-tail scheduler cap (`all_method_max_eval_tail_pipelines`) and phase-aware admission growth.
- Kept `evaluate_canonical_text(...)` signature stable and controlled strategy via env for rollout/debug.

Evidence preserved:
- Hotspot profile from task: `evaluate_canonical_text` ~`307.68s`, alignment ~`306.02s`, nearly all in SequenceMatcher internals.
- Task-recorded targeted regression suites were green.

Known pending from task:
- Real SeaAndSmoke before/after timing acceptance threshold evidence was still outstanding in that pass.

### 2026-02-25_23.39.03 canonical eval micro-telemetry + optional cProfile artifacts

Merged source:
- `docs/tasks/2026-02-25_23.39.03-canonical-eval-telemetry-microphases.md`

Problem captured:
- Coarse timing fields could not explain which canonical-eval subphase caused slow runs.

Decision/outcome preserved:
- Emit alignment micro-subphase timers and text-size work counters.
- Add opt-in eval profiling artifacts in `labelstudio-benchmark` via env thresholds.
- Keep artifact writes best-effort so profiling errors do not fail benchmark completion.

Evidence preserved:
- Task verification set passed: `5 passed, 2 warnings in 3.38s`.
- Artifacts captured when enabled: `eval_profile.pstats`, `eval_profile_top.txt`.

## 2026-02-26 to 2026-02-27 docs/tasks archival merge batch (OG speed plans + audits)

Merged sources in file-modified timestamp order (`YYYY-MM-DD_HH.MM.SS`, local):
- `2026-02-26_19.31.45` `docs/tasks/speed-1.md`
- `2026-02-26_19.37.49` `docs/tasks/speed-2.md`
- `2026-02-26_20.13.55` `docs/tasks/speed-4.md`
- `2026-02-26_22.04.22` `docs/tasks/2026-02-26_21.02.47-og-speed-plan-implementation-audit.md`
- `2026-02-26_22.24.05` `docs/tasks/2026-02-26_21.34.23-og-speed3-speed5-implementation-audit.md`
- `2026-02-26_22.24.26` `docs/tasks/speed-5.md`
- `2026-02-26_22.24.35` `docs/tasks/speed-3.md` (contains in-doc implementation timestamps on `2026-02-27`)

### speed-1 ExecPlan archival merge (`docs/tasks/speed-1.md`)

Problem captured:
- Canonical-text evaluation runtime was dominated by global alignment using stdlib `difflib.SequenceMatcher`.

Intent preserved:
- Keep scoring and alignment algorithm semantics unchanged.
- Only swap matcher implementation behind a drop-in selector with deterministic fallback behavior.

Decisions preserved:
- Scope is implementation substitution only (no threshold/algorithm changes).
- Prefer `cydifflib` in `auto` mode; always preserve stdlib fallback.
- Avoid monkey-patching; use explicit benchmark-local selector wiring.

Status captured in plan:
- Rebuild completed as a code-verified ExecPlan.
- Remaining in-plan gap was baseline/after evidence capture (telemetry + output identity proof).

### speed-2 ExecPlan archival merge (`docs/tasks/speed-2.md`)

Problem captured:
- All-method canonical-text runs could underutilize CPU during evaluate-heavy tails due to admission guards tied to split/prewarm bookkeeping.

Intent preserved:
- Improve scheduler admission/runtime utilization only; keep scoring behavior unchanged.

Decisions preserved:
- Keep user-facing settings stable and introduce CPU-aware behavior in runtime resolution.
- Include explicit evaluate-phase visibility in snapshots/rollups as part of the same change.

Status captured in plan:
- Plan scaffold rebuilt with milestone-level implementation targets.
- Remaining in-plan gap was representative before/after evidence capture on real all-method canonical-text workloads.

### speed-4 ExecPlan archival merge (`docs/tasks/speed-4.md`)

Problem captured:
- Prediction and evaluation were conceptually staged but lacked a durable prediction-stage contract for replay/evaluate-only flows.

Implemented outcomes captured:
- Added `PredictionRecord` schema + JSONL IO in `cookimport/bench/prediction_records.py`.
- Added benchmark stage controls:
  - `--execution-mode legacy|pipelined|predict-only`
  - `--predictions-out`
  - `--predictions-in`
- Added evaluate-only replay path and queue-backed pipelined orchestration.
- Added focused regression coverage:
  - `tests/bench/test_prediction_records.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py`

Open gap preserved:
- Real workload timing proof for `legacy` vs `pipelined` remained pending in the plan.

### 2026-02-27 speed1-4 per-block record + stage-runner closure pass

Problem addressed:
- The speed1-4 audit showed remaining contract gaps: run-level prediction records, no explicit stage runner APIs, and no deterministic per-example replay join checks.

Implementation update:
- Added explicit stage/runner API surface in `cookimport/cli.py`:
  - `predict_stage(...)`
  - `evaluate_stage(...)`
  - `run_legacy(...)`
  - `run_pipelined(...)`
- `--predictions-out` now writes per-block prediction records (`schema_kind=stage-block.v1`) with deterministic `example_id`/`example_index`.
- `--predictions-in` now supports per-block replay and reconstructs evaluation artifacts from record payloads; legacy single-record run-pointer inputs remain supported for backward compatibility.
- Pipelined mode now runs a bounded producer/consumer record queue with clean EOS/error propagation.
- Added/updated benchmark helper coverage in `tests/labelstudio/test_labelstudio_benchmark_helpers.py`:
  - per-block `--predictions-out` payload shape,
  - evaluate-only from per-block records,
  - legacy record compatibility path,
  - legacy vs pipelined parity and pipelined overlap behavior checks.

Remaining open item:
- Representative real-workload timing artifact (`legacy` vs `pipelined`) is still pending; test-level overlap/parity evidence is now in place.

### 2026-02-26_21.02.47 OG implementation audit merge (`docs/tasks/2026-02-26_21.02.47-og-speed-plan-implementation-audit.md`)

Audit question preserved:
- Compare OG specs (`speed-1`, `speed-2`, `speed-4`) to runtime/test/docs evidence and mark `Complete`/`Partial`/`Missing`.

Executive verdict captured at audit time:
- `speed-1`: `Partial`
- `speed-2`: `Partial`
- `speed-4`: `Partial`

Requirement-level closure snapshot preserved:
- Speed-1:
  - complete wiring/tests/docs: `S1-R2..S1-R10`
  - missing: `S1-R1` (baseline + after evidence artifact)
- Speed-2:
  - complete runtime/test/docs semantics: `S2-R2..S2-R10`
  - missing: `S2-R1` (before/after all-method evidence)
- Speed-4:
  - complete staged controls and replay/predict-only behavior: `S4-R1..S4-R8`
  - partial: `S4-R9` (contract still run-level record, not per-example)
  - missing: `S4-R10` (timing evidence for overlap benefit)

Explicit open list preserved by audit:
1. Speed-1 evidence capture.
2. Speed-2 evidence capture.
3. Speed-4 per-example record boundary decision (if OG requirement still stands).
4. Speed-4 timing-evidence capture.

### 2026-02-26_21.34.23 OG implementation audit merge (`docs/tasks/2026-02-26_21.34.23-og-speed3-speed5-implementation-audit.md`)

Audit question preserved:
- Compare OG specs (`speed-3`, `speed-5`) to runtime/test/docs evidence and capture unresolved acceptance gaps.

Executive verdict captured at initial audit checkpoint:
- `speed-3`: `Partial` (core architecture implemented, proof/hardening gaps open).
- `speed-5`: `Partial` but mostly incomplete at that checkpoint.

Requirement-level snapshot preserved (initial checkpoint):
- Speed-3:
  - complete: `S3-R1,S3-R2,S3-R3,S3-R4,S3-R6,S3-R7,S3-R8`
  - partial: `S3-R5` (recovery branches existed but lacked direct test forcing)
  - missing: `S3-R9,S3-R10`
- Speed-5:
  - complete: `S5-R2`
  - partial: `S5-R6,S5-R11`
  - missing: `S5-R1,S5-R3,S5-R4,S5-R5,S5-R7,S5-R8,S5-R9,S5-R10,S5-R12,S5-R13,S5-R14`

Implementation update preserved in same task (`2026-02-26_22.23.35`):
- Speed-3:
  - added explicit stale-lock and corrupt-cache fallback tests in `tests/bench/test_eval_stage_blocks.py`.
- Speed-5:
  - added `write_markdown` control through staging writer, worker, merge, and stage CLI wiring.
  - added pred-run controls `write_markdown` and `write_label_studio_tasks`.
  - added benchmark CLI flags:
    - `--write-markdown/--no-write-markdown`
    - `--write-labelstudio-tasks/--no-write-labelstudio-tasks` (offline-only guardrail).
  - added manifest semantics for intentional task skip:
    - `tasks_jsonl_status` (`written|skipped_by_config`)
    - `tasks_jsonl` emitted only when written.
  - added doc/test updates across CLI, staging, label studio, and benchmark surfaces.

Residual open gaps preserved after that update:
1. Committed real-run timing evidence for speed-3 and speed-5.
2. Prepared archive abstraction (`PreparedExtractedArchive`) still not implemented.
3. Broader scoring-parity evidence artifacts for speed-5 still pending.

Anti-loop note:
- This audit file intentionally contains two states (initial gap-heavy checkpoint and later implementation update). Read both before assuming work is still missing.

### speed-5 ExecPlan archival merge (`docs/tasks/speed-5.md`)

Problem captured:
- Stage and offline benchmark prediction flows spent time writing non-scoring artifacts (markdown/task JSONL).

Implemented outcomes preserved:
- Stage supports `--no-write-markdown`.
- Offline benchmark supports `--no-write-markdown` and `--no-write-labelstudio-tasks`.
- Defaults remain compatibility-safe (`write_markdown=True`, `write_label_studio_tasks=True`).
- Intentional task-jsonl skip state is explicit in manifests (`tasks_jsonl_status`).

Guardrails preserved:
- `--no-write-labelstudio-tasks` must remain offline-only because upload mode requires tasks JSONL payloads.

Remaining plan gaps preserved:
- Representative manual A/B timing evidence.
- Representative scoring-parity evidence artifact for speed mode.

### speed-3 ExecPlan archival merge (`docs/tasks/speed-3.md`)

Problem captured:
- Canonical-text all-method runs repeated expensive global alignment for identical prediction/canonical text streams.

Implemented outcomes preserved:
- Canonical evaluator supports optional disk-backed alignment reuse via `alignment_cache_dir`.
- Cache key/signature includes canonical normalized text, prediction normalized text, and prediction block-boundary layout.
- Cache supports lock + stale-lock recovery + atomic write + corruption quarantine paths.
- Telemetry includes cache-enabled/hit/key/load/write/validation fields.
- All-method uses shared per-source cache root at `.cache/canonical_alignment`.

Validation record preserved:
- Focused runs for `tests/bench/test_eval_stage_blocks.py` and `tests/labelstudio/test_labelstudio_benchmark_helpers.py` reported green in task notes.
- Added tests for hit reuse parity, boundary-invalidation behavior, stale-lock recovery, and corrupt-entry fallback.

Remaining gap preserved:
- Real all-method telemetry bundle proving cross-config hit-rate and wall-time reduction was still pending.

### Consolidated closure order preserved across both audits

1. Capture before/after benchmark evidence for speed-1 and speed-2.
2. Capture `legacy` vs `pipelined` timing evidence for speed-4.
3. Capture speed-3 cache hit-rate + wall-time evidence and speed-5 A/B write-time + scoring-parity evidence.
4. Decide whether OG still requires per-example prediction records (`speed-4`) and prepared archive abstraction (`speed-5`) before reopening implementation loops.

## 2026-02-26 to 2026-02-27 archival merge batch from `docs/understandings` (canonical eval + scheduler surfaces + speed4/5 contracts)

Merged sources in file-created timestamp order (`YYYY-MM-DD_HH.MM.SS`):
- `2026-02-26_17.43.52` `docs/understandings/2026-02-26_17.43.52-interactive-benchmark-canonical-text-default.md`
- `2026-02-26_17.50.47` `docs/understandings/2026-02-26_17.50.47-interactive-benchmark-eval-spinner-visibility.md`
- `2026-02-26_18.05.24` `docs/understandings/2026-02-26_18.05.24-canonical-fast-align-deprecated.md`
- `2026-02-26_18.19.49` `docs/understandings/2026-02-26_18.19.49-benchmark-telemetry-source-layout.md`
- `2026-02-26_18.32.41` `docs/understandings/2026-02-26_18.32.41-all-method-failure-counters-timeout-retries.md`
- `2026-02-26_18.49.41` `docs/understandings/2026-02-26_18.49.41-all-method-dashboard-active-config-worker-lines.md`
- `2026-02-26_18.51.30` `docs/understandings/2026-02-26_18.51.30-all-method-heavy-counter-vs-eval-phase.md`
- `2026-02-26_19.30.26` `docs/understandings/2026-02-26_19.30.26-canonical-sequence-matcher-surface.md`
- `2026-02-26_19.37.52` `docs/understandings/2026-02-26_19.37.52-all-method-smart-admission-eval-tail-constraints.md`
- `2026-02-26_19.57.12` `docs/understandings/2026-02-26_19.57.12-canonical-alignment-cache-call-chain.md`
- `2026-02-26_20.26.13` `docs/understandings/2026-02-26_20.26.13-speed5-stageblock-artifact-surface.md`
- `2026-02-26_22.03.19` `docs/understandings/2026-02-26_22.03.19-speed2-eval-tail-headroom-and-speed4-pipeline-prewarm.md`
- `2026-02-26_22.23.35` `docs/understandings/2026-02-26_22.23.35-speed5-toggle-plumbing-surfaces.md`
- `2026-02-26_22.36.54` `docs/understandings/2026-02-26_22.36.54-all-method-cpu-utilization-cap-from-config-limits.md`
- `2026-02-27_03.12.00` `docs/understandings/2026-02-27_03.12.00-speed4-benchmark-stage-record-contract.md`

### 2026-02-26_17.43.52 interactive single-offline canonical-text default

Problem captured:
- Interactive `single_offline` path called `labelstudio_benchmark(..., no_upload=True)` without forwarding `eval_mode`, so Typer defaulted to `stage-blocks`.
- Interactive `all_method` already forced `canonical-text`, so interactive modes diverged on scoring surface.

Decision/outcome preserved:
- Interactive benchmark modes should both pass `eval_mode=canonical-text`.
- This keeps interactive workflows extractor-agnostic and avoids stage-block blockization mismatch failures during cross-extractor checks.

Anti-loop note:
- If interactive single-offline unexpectedly reports stage-block mismatch guards, first verify `eval_mode` propagation before changing evaluator code.

### 2026-02-26_17.50.47 interactive benchmark eval-phase spinner visibility

Problem captured:
- Prediction generation had progress status wrapping; evaluation phase ran with no spinner/status wrapper.
- Canonical eval can run for minutes, making terminal output appear frozen after prediction artifacts are written.

Decision/outcome preserved:
- Non-suppressed interactive benchmark runs should keep visible status during evaluation with explicit eval-mode wording.

Anti-loop note:
- Apparent post-prediction "hang" can be normal evaluation; verify status/render path before adding watchdog logic.

### 2026-02-26_18.05.24 canonical fast alignment deprecation enforcement

Problem captured:
- Bounded fast alignment showed accuracy-risk mapping drift on real materials.
- Auto fallback preserved correctness but added uncertainty/complexity about active strategy.

Decision/outcome preserved:
- Canonical scoring enforces legacy global alignment.
- `COOKIMPORT_CANONICAL_ALIGNMENT_STRATEGY=auto|fast` is treated as deprecated alias behavior and forced to legacy with explicit telemetry.

Anti-loop note:
- Do not reopen fast alignment path without new evidence that preserves scoring parity under representative corpora.

### 2026-02-26_18.19.49 benchmark telemetry source layout

Problem captured:
- Top-level `data/.history/performance_history.csv` had very few rows relative to known benchmark volume.

Evidence preserved:
- Feb 25-26 benchmark truth was distributed across run-local files:
  - `data/golden/benchmark-vs-golden/**/eval_report.json`
  - `data/golden/benchmark-vs-golden/**/all_method_benchmark_report.json`
  - `data/output/**/all-method-benchmark/**/.history/performance_history.csv`

Decision/outcome preserved:
- Run-local eval/source reports and run-local history CSVs are primary telemetry truth for benchmark analysis.
- Top-level history remains a convenience index only.

### 2026-02-26_18.32.41 all-method fail counters vs timeout/retry semantics

Problem captured:
- Operators interpreted non-zero live `fail` counters as final source failures while source execution was still in progress.

Decision/outcome preserved:
- Queue `ok/fail` counters represent attempt outcomes during initial pass.
- Retry passes and timeout recovery can later clear failures, but live queue counters are intentionally not rewritten.
- Final source outcome belongs in `all_method_benchmark_report.json` retry/failure summary fields.

Anti-loop note:
- Avoid diagnosing "stuck failed run" from live queue counters alone; inspect report-level final status fields.

### 2026-02-26_18.49.41 active-config dashboard worker lines

Problem captured:
- Dashboard compressed multi-active state to `current configs A-B/N`, hiding per-slot phase visibility.
- Scheduler events already had per-config phase telemetry but that state was not surfaced in operator rows.

Decision/outcome preserved:
- Dashboard maintains per-config phase state and renders multi-active worker rows (`config NN: <phase> | <slug>`).

Anti-loop note:
- If operators cannot tell whether workers are in split/eval/post phases, fix dashboard state plumbing before tuning scheduler heuristics.

### 2026-02-26_18.51.30 heavy counter vs evaluate-phase activity

Problem captured:
- `scheduler heavy X/Y` was misread as total activity, causing false stall assumptions when evaluate-phase dominated.

Decision/outcome preserved:
- `heavy` reflects only `split_active` occupancy.
- During evaluate-only windows, `heavy 0/N` with active configs and pending `0` can be expected.
- Per-config scheduler event files (`.scheduler_events/config_*.jsonl`) are the liveness source when status appears idle.

Anti-loop note:
- Treat `evaluate_started` + high worker CPU as normal progress, not deadlock, unless timeout thresholds are exceeded.

### 2026-02-26_19.30.26 canonical SequenceMatcher implementation surface

Problem captured:
- Speed-1 work needed exact implementation boundary to avoid behavior drift.

Evidence preserved:
- `cookimport/bench/eval_canonical_text.py` imports stdlib `SequenceMatcher`.
- `_align_prediction_blocks_legacy(...)` uses `autojunk=False`.
- Alignment telemetry already includes `alignment_sequence_matcher_seconds`.

Decision/outcome preserved:
- Speed work may swap matcher implementation behind current call surface only; alignment/scoring semantics must remain unchanged.

### 2026-02-26_19.37.52 smart admission eval-tail guard interaction

Problem captured:
- Scheduler already tracked `evaluate_active`, but additional prewarm guards could still suppress new admissions during evaluate-heavy tails.

Decision/outcome preserved:
- Throughput tuning must include both eval-tail caps and guard-target math (`heavy + wing` vs target), not eval detection alone.
- Live snapshots should include eval-phase visibility to explain admission behavior under tail-heavy workloads.

Anti-loop note:
- "Eval-tail is ignored" is often a guard-target artifact; inspect both eval count and guard thresholds before changing phase detection.

### 2026-02-26_19.57.12 canonical alignment cache call chain and safety

Problem captured:
- Needed an exact end-to-end map of how cache paths propagate and where safety checks are enforced.

Decision/outcome preserved:
- Per-source cache root is created in `_run_all_method_benchmark(...)` and threaded through:
  - `_run_all_method_config_once(...)` -> `labelstudio_benchmark(...)` -> `evaluate_canonical_text(...)` -> `_align_prediction_blocks_to_canonical(...)`.
- Cache reuse requires canonical hash, prediction hash, boundary hash, normalization version, and algorithm version match.
- Validation failures become cache misses and are surfaced in telemetry; writes are atomic with lock+stale-lock handling.

Anti-loop note:
- If cache behavior looks inconsistent, inspect validation-error telemetry first before loosening key constraints.

### 2026-02-26_20.26.13 speed-5 artifact-surface baseline

Problem captured:
- Needed proof of which artifacts actually affect stage-block scoring before adding write-skipping toggles.

Evidence preserved:
- Stage-block scoring does not consume `label_studio_tasks.jsonl`.
- Scoring reads stage predictions plus extracted archive artifacts.
- Output stats and archive construction were already single-pass/efficient in existing paths.

Decision/outcome preserved:
- Remaining speed-5 leverage is optional markdown/task side-artifact writes, not core scorer inputs.

### 2026-02-26_22.03.19 speed-2 headroom + speed-4 prewarm boundary

Problem captured:
- Eval-tail utilization remained low despite eval activity tracking.
- Proposed speed-4 overlap ideas needed practical phase boundary grounding.

Decision/outcome preserved:
- Speed-2 needed CPU-aware eval-tail caps plus dynamic guard-target behavior while eval is active.
- Speed-4 practical overlap is prediction generation producer-threading plus canonical prewarm; evaluation still depends on run-level prediction artifacts being present.

Anti-loop note:
- Do not assume full prediction/eval overlap before run artifacts exist; replay contract is run-level, not per-example stream.

### 2026-02-26_22.23.35 speed-5 toggle plumbing surfaces

Problem captured:
- Toggle behavior drift risk across stage single-file, split-merge, and benchmark no-upload pred-run generation.

Decision/outcome preserved:
- `write_markdown` must be forwarded through both stage entry paths (`stage_one_file` and split-merge merge path).
- `write_label_studio_tasks` is meaningful only for no-upload/offline pred-run generation.
- Manifests must explicitly encode skipped tasks JSONL (`tasks_jsonl_status=skipped_by_config`) so missing file is intentional.

Anti-loop note:
- Avoid one-path-only toggle patches; mismatched plumbing reintroduces nondeterministic artifact sets.

### 2026-02-26_22.36.54 all-method CPU underutilization via config caps

Problem captured:
- Low observed CPU utilization was misdiagnosed as scheduler/worker failure in some runs.

Evidence preserved:
- Interactive all-method caps are read from `cookimport.json` keys:
  - `all_method_max_inflight_pipelines`
  - `all_method_max_split_phase_slots`
  - `all_method_max_eval_tail_pipelines`
  - `all_method_wing_backlog_target`
- Example low-cap settings (`2/2/2`) can cap effective inflight near six, underutilizing many-core hosts.

Decision/outcome preserved:
- First diagnostic step for low CPU should be resolved scheduler limits, not worker fault assumptions.

### 2026-02-27_03.12.00 speed-4 benchmark stage-record contract

Problem captured:
- Needed stable contract for evaluate-only replay and execution-mode split without scoring changes.

Decision/outcome preserved:
- `labelstudio-benchmark` already has hard prediction/eval phase boundary at run level.
- Durable replay contract is a run-level prediction record with artifact paths + minimal metadata.
- Per-example streaming contract is not required for immediate replay support and would enlarge semantic surface.

Anti-loop note:
- If replay feature requests reintroduce per-example contracts, require explicit rationale and compatibility plan against current run-level record design.

### 2026-02-27_11.27.23 OG speed1-3 closure evidence and proof-depth completion

Problem captured:
- Speed1-3 runtime code existed, but closure audit still flagged three remaining proof/documentation gaps:
  - missing dedicated `tests/bench/test_canonical_alignment_cache.py` file named by plan,
  - missing same-key concurrent writer proof depth,
  - missing real miss->hit all-method evidence bundle with wall-time signal.

Decision/outcome preserved:
- Added dedicated cache test module `tests/bench/test_canonical_alignment_cache.py` and marker mapping in `tests/conftest.py`.
- Added cache-layer multi-process same-key contention test asserting single compute + cache reuse by the competing worker.
- Captured real two-config all-method evidence using identical run settings over `DinnerFor2CUTDOWN.epub`:
  - config 1 miss: `alignment_cache_hit=false`, `alignment_sequence_matcher_seconds=12.626098081003875`, `duration_seconds=23.607534372014925`
  - config 2 hit: `alignment_cache_hit=true`, `alignment_sequence_matcher_seconds=0.0`, `duration_seconds=10.013305764994584`
  - metrics parity held (`overall_line_accuracy` and `macro_f1_excluding_other` unchanged).
- Updated `docs/plans/OGplan/speed1-3.md` Progress + Outcomes/Retrospective with closure evidence and timestamps.

Evidence artifact:
- `/tmp/2026-02-27_11.27.23-speed1-3-evidence-all-method/speed1_3_cache_summary.json`
- closure task: `docs/tasks/2026-02-27_11.29.26-speed1-3-remaining-closeout.md`
- updated audit: `docs/understandings/2026-02-27_10.51.28-og-speed1-3-implementation-audit.md`

Anti-loop note:
- If later all-method runs show no cache benefit, inspect `evaluation_telemetry.alignment_cache_key` equality first; cache is intentionally strict on canonical text hash + prediction text hash + boundary hash.

## 2026-02-26_22.53 to 2026-02-27_19.09 archival merge batch from `docs/understandings`

Merged in source creation order (`YYYY-MM-DD_HH.MM.SS`):
- `docs/understandings/2026-02-26_22.53.30-all-method-eval-lock-bottleneck.md`
- `docs/understandings/2026-02-27_10.15.12-all-method-wsl-crash-nested-process-pools.md`
- `docs/understandings/2026-02-27_10.18.26-speed-plan-implementation-audit.md`
- `docs/understandings/2026-02-27_10.30.29-canonical-alignment-byte-parity-surface.md`
- `docs/understandings/2026-02-27_10.51.28-og-speed1-3-implementation-audit.md`
- `docs/understandings/2026-02-27_10.51.52-speed1-4-implementation-gap-audit.md`
- `docs/understandings/2026-02-27_10.52.17-speed1-5-implementation-audit.md`
- `docs/understandings/2026-02-27_10.52.18-speed1-2-spec-audit.md`
- `docs/understandings/2026-02-27_11.19.52-speed1-2-scheduler-contract-alignment.md`
- `docs/understandings/2026-02-27_11.45.52-speed1-4-per-block-replay-runner-discovery.md`
- `docs/understandings/2026-02-27_12.17.58-og-speed1-1-through-1-5-implementation-status.md`
- `docs/understandings/2026-02-27_13.09.44-speed1-4-true-streaming-replay-consumer.md`
- `docs/understandings/2026-02-27_18.05.11-all-method-scheduler-snapshot-cadence.md`
- `docs/understandings/2026-02-27_18.12.47-speed2-4-plan-vs-current-sequence-matcher-state.md`
- `docs/understandings/2026-02-27_18.13.18-og-speed2-3-plan-context-drift.md`
- `docs/understandings/2026-02-27_18.14.00-speed2-2-plan-current-context-audit.md`
- `docs/understandings/2026-02-27_18.14.04-all-method-thefoodlab-stale-eta.md`
- `docs/understandings/2026-02-27_18.24.56-all-method-eta-recent-rate-tail-floor.md`
- `docs/understandings/2026-02-27_18.43.01-speed2-3-dmp-selector-integration.md`
- `docs/understandings/2026-02-27_18.45.01-canonical-cache-dead-pid-lock-recovery.md`
- `docs/understandings/2026-02-27_18.49.32-all-method-final-source-eval-tail-cpu-cap.md`
- `docs/understandings/2026-02-27_18.51.09-speed-suite-design-context-discovery.md`
- `docs/understandings/2026-02-27_18.57.58-all-method-source-scheduler-fifo-tail-risk.md`
- `docs/understandings/2026-02-27_19.02.30-benchmark-sequence-matcher-selection-surfaces.md`
- `docs/understandings/2026-02-27_19.09.42-speed-suite-shared-target-matching.md`
- `docs/understandings/2026-02-27_19.14.01-all-method-shard-aggregation-cache-sharing.md`
- `docs/understandings/2026-02-27_19.15.22-bench-cli-typer-optioninfo-defaults.md`

Cross-folder placements from the same cleanup:
- `docs/understandings/2026-02-27_12.00.28-speed1-5-split-merge-outputstats-ordering.md` merged into staging docs (`docs/05-staging/`).
- `docs/understandings/2026-02-27_18.19.11-processing-telemetry-plumbing-surfaces.md` merged into analytics docs (`docs/08-analytics/`).

### 2026-02-26_22.53.30 all-method eval-lock bottleneck (canonical miss-path)

Problem captured:
- In run `data/golden/benchmark-vs-golden/2026-02-26_22.30.40/all-method-benchmark/thefoodlabcutdown`, many configs reached `evaluate_started` while completion stayed `config 0/15`.
- Cache directory showed only lock files for first keys; process list showed a small number of CPU-saturated workers with others waiting.

Decision/outcome preserved:
- Interpret this state as canonical alignment bottleneck on first unique keys, not split/prediction starvation.
- Scheduler/inflight/split-slot tuning helps pre-eval throughput; canonical miss-path wall time is governed by unique key count and per-key matcher cost.

### 2026-02-27_10.15.12 WSL crash pattern: nested split-pool oversubscription

Problem captured:
- In run `data/golden/benchmark-vs-golden/2026-02-26_23.01.04`, configs started and entered split scheduling but never reached post/evaluate; no report artifacts landed.
- Settings implied roughly `split_slots * split_workers = 4 * 10 = 40` split workers, before parent/config overhead.

Decision/outcome preserved:
- Crash signature is consistent with nested pool oversubscription under host pressure.
- Runtime guard added in `cookimport/cli.py` to cap per-config split workers from CPU/memory budgets.
- Scheduler summaries should expose split worker caps (`split_worker_cap_per_config`, CPU cap, memory cap) for post-run diagnosis.

Anti-loop note:
- Do not diagnose early hard exits as evaluator bugs first when split worker multiplicative caps are high.

### 2026-02-27_10.18.26 speed plan implementation audit (selector plan)

Preserved audit conclusion:
- Core selector implementation landed (`sequence_matcher_select.py`, evaluator wiring, benchaccel extra, parity tests).
- Plan-closure proof gaps remained in that audit snapshot:
  - stale checklist/progress artifacts in plan file,
  - incomplete tricky-case/opcode coverage vs plan wording,
  - missing byte-identical end-to-end artifact proof target.

### 2026-02-27_10.30.29 canonical byte-parity surface choice

Durable rule preserved:
- `eval_report.json` is not a byte-parity artifact because telemetry and timing fields differ by implementation.
- Use `aligned_prediction_blocks.jsonl` for byte-identical parity checks across matcher implementations; use `eval_report.json` for runtime interpretation only.

### 2026-02-27_10.51.28 speed1-3 closure audit update

Status preserved:
- This file confirmed speed1-3 closure to OG intent (runtime + tests + plan upkeep + miss->hit real evidence).
- Detailed closure evidence is already captured in the earlier `2026-02-27_11.27.23` log entry and linked closeout task.

### 2026-02-27_10.51.52 speed1-4 implementation-gap audit

Preserved verdict:
- Speed1-4 was partially implemented at audit time.
- Closed: record schema/flags, evaluate-only path, predict-only path, parity tests.
- Missing or partial: true predict/evaluate overlap, per-example stream contract, stage-runner API shape from OG plan, real overlap timing evidence bundle.

Anti-loop note:
- Distinguish "phase overlap" (prediction + prewarm) from true producer/consumer scoring overlap before claiming speed1-4 closure.

### 2026-02-27_10.52.17 speed1-5 implementation audit update

Preserved verdict:
- Substantially closed for runtime/test/doc gaps after follow-up implementation.
- Remaining open item was manual baseline/perf evidence capture in plan artifacts.

Preserved closed items from this audit:
- prepared archive abstraction + reuse wiring,
- split-merge outputStats parity handling,
- explicit split-merge parity test,
- direct `bench run` write-toggle flags,
- no-drift stage-prediction equality checks under markdown toggle,
- ExecPlan lifecycle section updates.

### 2026-02-27_10.52.18 speed1-2 spec audit (OG semantics vs implementation)

Preserved audit conclusion:
- Functional implementation existed, but strict OG spec alignment gaps remained in that audit:
  - explicit override CPU-budget clamping semantics,
  - configured-vs-effective eval-tail contract shape visibility,
  - admission cap formula mismatch (`base_inflight + headroom` vs implemented dynamic cap),
  - incomplete plan evidence closure and invariant-focused tests.

### 2026-02-27_11.19.52 speed1-2 contract-alignment discovery

Durable contract rule preserved:
- One legacy field (`max_eval_tail_pipelines`) should not represent user intent, runtime effective headroom, and admission ceiling simultaneously.
- Runtime contract should expose explicit fields:
  - `eval_tail_headroom_mode`
  - `eval_tail_headroom_configured`
  - `eval_tail_headroom_effective`
  - `max_active_during_eval`
  - optional CPU-budget context
- Keep legacy fields as compatibility aliases only.

### 2026-02-27_11.45.52 speed1-4 per-block replay runner discovery

Preserved implementation boundary:
- Keep stable path-based evaluators; replay should reconstruct evaluator input artifacts from prediction records rather than reimplement scoring internals.
- Durable replay contract: per-block `PredictionRecord` (`schema_kind=stage-block.v1`) with deterministic `example_id`/`example_index`.
- Evaluate-only compatibility must include both new per-block records and historical single-record run-pointer artifacts.

### 2026-02-27_12.17.58 OG speed1-1 through speed1-5 implementation-status snapshot

Preserved status map:
- Speed1-3 closed with real evidence.
- Speed1-2, speed1-4, speed1-5 had core runtime/test work landed, but acceptance-evidence capture remained the recurring pending category.
- Speed1-4 pipelined path overlapped prediction with prewarm/record handling, but not full prediction/evaluation overlap at that snapshot.
- Speed1-1 runtime/tests were effectively closed, while OG plan bookkeeping still lagged in checklist/living-section maintenance.

### 2026-02-27_13.09.44 speed1-4 streaming replay consumer

Preserved design decision:
- True overlap can be introduced at replay boundary: producer emits per-block records, consumer ingests stream in real time, then finalizes replay artifacts for unchanged evaluators.
- This preserves metric semantics while improving overlap opportunities.

Constraint preserved:
- Zero-block prediction runs are valid; replay assembly must allow empty streams and fallback cleanly instead of failing hard.

### 2026-02-27_18.05.11 scheduler snapshot cadence

Durable runtime interpretation rule:
- All-method scheduler loop polls at `0.15s`.
- Spinner text only updates on snapshot string changes, so visible status can appear static during long phases while polling continues.
- Persisted heartbeat/timeseries data is needed for tuning when state text is unchanged.

### 2026-02-27_18.12.47 speed2-4 plan drift vs selector architecture

Preserved finding:
- Current runtime uses selector architecture and matcher telemetry; planned MultiLayer module/API shape from OG speed2-4 was not the active path.
- In sampled run telemetry (`2026-02-27_17.54.41`), parsed eval reports showed `alignment_sequence_matcher_impl=cydifflib`, mode `auto`, with substantial cache-hit volume.

Practical implication:
- Use OG speed2-4 as historical intent context; rewrite against current selector architecture before execution.

### 2026-02-27_18.13.18 speed2-3 plan context drift

Preserved finding:
- OG backend-family plan (`dmp`/`edlib` via separate env contract) is mostly superseded by current selector+cache model.
- Canonical speedups in current code come primarily from matcher implementation choice and cache hit rate.

### 2026-02-27_18.14.00 speed2-2 plan current-context audit

Preserved finding:
- OG speed2-2 assumptions are stale where they assume stdlib-only matcher path.
- Current work should focus on miss-path cost inside selector+cache architecture; cache-hit cases already drive matcher time to zero.

### 2026-02-27_18.14.04 stale ETA on large canonical sets

Problem captured:
- In run `2026-02-27_17.54.41`, ETA looked frozen while large canonical texts (`~527k` and `~398k` chars) were still evaluating and workers were CPU-active.
- Recent finished configs showed evaluate durations around `447s`.

Decision/outcome preserved:
- Flat ETA for many minutes can be normal on large canonical eval tails.
- Better stall threshold for this shape is on the order of `>30 minutes` with low CPU + no event/file movement, not a few minutes.

### 2026-02-27_18.24.56 ETA recent-rate + stall-floor rule

Durable ETA rule:
- Full-run average completion rate underestimates tail time after fast early configs.
- Better model:
  - recent completion-rate samples as primary ETA,
  - if eval is active and completion stalls, apply floor `stalled_seconds / active`.

### 2026-02-27_18.43.01 speed2-3 dmp selector integration

Preserved implementation decision:
- Integrate `dmp` as another selector mode (not separate backend contract) to minimize architecture risk.
- `dmp` can be much faster on mismatch-heavy synthetic inputs, but matching-block/opcode shapes differ from stdlib and should not be treated as strict drop-in parity.

Evidence preserved:
- Bench script snapshots captured very large synthetic speedups for `dmp` vs stdlib; canonical minimal fixture scoring remained equal in the cited targeted regression subset.

### 2026-02-27_18.45.01 canonical cache dead-PID lock recovery

Problem captured:
- In run `2026-02-27_17.54.41`, multiple canonical cache lock files were owned by dead PIDs while configs remained stuck at `evaluate_started`.
- Existing stale-lock check used lock age only (`wait_seconds`), delaying recovery up to long timeouts.

Decision/outcome preserved:
- Dead-owner lock reclamation must use PID liveness first, with age-based stale fallback for malformed lock metadata.

Anti-loop note:
- If evaluate appears stalled with active workers, inspect lock-owner PID liveness before expanding scheduler concurrency.

### 2026-02-27_18.49.32 final-source eval-tail CPU cap

Preserved interpretation:
- Late-run CPU is naturally bounded by remaining configs for the final source and count of unique active cache keys.
- With shared-key waiting, non-saturated host CPU can be expected even without deadlock.

### 2026-02-27_18.51.09 speed-suite design context

Preserved design rules:
- `bench run` is quality-first; separate speed-gating workflow is needed for deterministic baseline-vs-candidate checks.
- Run-local artifacts are reliable timing truth (`run_manifest`, `eval_report`, processing/scheduler timeseries); top-level history CSV can lag or be incomplete.
- Matching must use robust source hints beyond manifest-only fields because pulled gold exports can have sparse manifests.

### 2026-02-27_18.57.58 source scheduler FIFO tail risk

Problem captured:
- Multi-source all-method dispatch was FIFO by discovery order (`mtime` discovery + `pop(0)` pending queue), not cost-aware.
- Observed run skew showed small sources finishing quickly while very large sources dominated final tail.

Decision/outcome preserved:
- Tail-utilization work should include source-level scheduling policy, not only per-source pipeline tuning.

### 2026-02-27_19.02.30 matcher selection surfaces

Preserved contract:
- Interactive single-run and all-method flows have separate run-setting entry points; matcher selection propagation must be wired in both.
- Prefer explicit fallback mode naming (`fallback`) for chain behavior; keep legacy `auto` accepted as alias for compatibility but not as primary surfaced choice.
- Override behavior is safest via scoped env context with selector-cache reset before/after.
- Telemetry should split requested vs effective matcher mode for clarity.

### 2026-02-27_19.09.42 speed-suite shared target matching

Preserved decision:
- Shared matching moved into `cookimport/bench/speed_suite.py` (`match_gold_exports_to_inputs(...)`) and is reused by all-method target resolution.
- Source hint resolution order:
  1. `manifest.json` `source_file`
  2. `run_manifest.json` `source.path`
  3. first `source_file` in `freeform_span_labels.jsonl`
  4. first `source_file` in `freeform_segment_manifest.jsonl`

Anti-loop note:
- Avoid duplicating matching logic in CLI-only private helpers; this drift already happened once and forced re-convergence.

### 2026-02-27_19.14.01 all-method shard aggregation + cache sharing

Problem captured:
- Source sharding can create multiple jobs for one logical source/gold pair; if each shard uses its own default canonical cache root, siblings recompute identical alignments.

Decision/outcome preserved:
- Multi-source orchestration should pass a shared canonical cache root per `source_group_key` into `_run_all_method_benchmark(...)` while still keeping shard output directories separate.
- Multi-source final report contract should aggregate shard rows back into one top-level source row for reader compatibility, with additive shard metadata fields (`source_shards`, `source_shard_total`, schedule-plan metadata).

### 2026-02-27_19.15.22 bench CLI OptionInfo defaults + target-resolution contract

Problem captured:
- Direct Python calls into `bench_run`, `bench_sweep`, and `bench_speed_run` can receive Typer `OptionInfo` objects instead of plain defaults.
- Matcher normalization can reject defaults unless values are unwrapped first.
- Replacing `_resolve_all_method_targets(...)` with alternate discovery helpers changed expected CLI-local behavior and broke helper tests.

Decision/outcome preserved:
- Unwrap Typer defaults at the start of bench command helpers before matcher normalization.
- Preserve existing `_resolve_all_method_targets(...)` contract using:
  - `cli._list_importable_files(DEFAULT_INPUT)`
  - `cli._load_source_hint_from_gold_export(...)`
  unless tests and interactive flows are migrated as one contract change.

Anti-loop note:
- Treat direct-call defaults and target-resolution wiring as compatibility contracts, not incidental implementation detail.

## 2026-02-25 to 2026-02-27 docs/tasks archival merge batch (speed closeout + matcher spike + tail-throughput)

### 2026-02-25_22.46.26 canonical-text extractor-independence ExecPlan (`docs/tasks/fix-goldOG.md`)

Problem captured:
- Stage-block evaluation tied quality scoring to extractor block indices; extractor mismatch produced missing-gold->`OTHER` artifacts and misleading per-label collapse.

Decision/outcome preserved:
- Add canonical benchmark path anchored on canonical gold text artifacts from export.
- Canonical eval aligns prediction extracted text to canonical text and scores in canonical line space.
- Keep stage-block evaluator unchanged as parity-sensitive import-alignment surface.
- Interactive all-method defaults/forces canonical-text path for extractor-comparison workflows.

Milestone state preserved from task:
- Canonical artifacts + canonical evaluator implementation marked complete.
- `labelstudio-benchmark --eval-mode` wiring marked complete.
- Task recorded remaining bench-suite wiring/docs follow-up as pending at that time.

Anti-loop note:
- Do not use stage-block mismatch outcomes to judge canonical-text scoring validity.

### 2026-02-27_10.29.44 sequence matcher speed-plan closeout (`docs/tasks/2026-02-27_10.29.44-sequence-matcher-speed-plan-closeout.md`)

Problem captured:
- Speed1 selector work had implementation but missing closure evidence depth (opcode parity, byte-identical end-to-end artifacts, plan evidence updates).

Decision/outcome preserved:
- Keep scoring algorithm unchanged.
- Add deterministic byte-identity artifact surface (`aligned_prediction_blocks.jsonl`) and parity-focused tests.
- Keep rollback knob: `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=stdlib`.

Evidence preserved from task:
- `pytest tests/bench/test_sequence_matcher_dropin_parity.py tests/bench/test_eval_stage_blocks.py -q` passed.
- Benchmark script sample showed parity true and large auto-vs-stdlib speedup:
  - `stdlib best_seconds=6.078813`
  - `auto impl=cydifflib best_seconds=0.738722`
  - `opcode_parity=True`
- A/B canonical snippet reported:
  - `score_equal=True`
  - `alignment_equal=True`
  - `aligned_bytes_equal=True`

### 2026-02-27_11.19.51 speed1-2 scheduler contract closeout (`docs/tasks/2026-02-27_11.19.51-speed1-2-remaining-implementation.md`)

Problem captured:
- OG speed1-2 audit flagged gaps in override safety, configured/effective headroom visibility, and smart-admission cap semantics.

Decision/outcome preserved:
- `_resolve_all_method_scheduler_runtime(...)` now exposes configured/effective headroom fields and explicit admission ceiling.
- Explicit eval-tail overrides are CPU/per-source bounded, not raw variant-count-only.
- Runtime semantics anchored on:
  - `max_active_during_eval = configured_inflight + eval_tail_headroom_effective`
- Legacy keys kept as compatibility aliases only.

Evidence preserved from task:
- `pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py` passed after threshold re-balance.
- `pytest -q tests/labelstudio/test_labelstudio_ingest_parallel.py` passed.
- `pytest -q tests/bench` passed.

### 2026-02-27_11.29.26 speed1-3 closure evidence completion (`docs/tasks/2026-02-27_11.29.26-speed1-3-remaining-closeout.md`)

Problem captured:
- Remaining closure gaps: dedicated cache test module, same-key concurrency proof depth, real miss->hit runtime evidence, and living-plan completion.

Decision/outcome preserved:
- Added dedicated cache test module (`tests/bench/test_canonical_alignment_cache.py`) + marker wiring.
- Added same-key multi-process contention proof and miss->hit evidence expectations.
- Updated plan/docs to closed state with evidence references.

Evidence preserved from task:
- Fail-before recorded: missing `tests/bench/test_canonical_alignment_cache.py`.
- Pass-after recorded:
  - `pytest -q tests/bench/test_canonical_alignment_cache.py` exit `0`
  - `pytest -q tests/bench/test_eval_stage_blocks.py -k alignment_cache` exit `0`
  - `pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py -k ranked_summary` exit `0`
- Real evidence bundle path:
  - `/tmp/2026-02-27_11.27.23-speed1-3-evidence-all-method/speed1_3_cache_summary.json`
- Reported miss->hit effect:
  - miss: matcher `12.626s`, duration `23.608s`
  - hit: matcher `0.0s`, duration `10.013s`
  - quality metrics unchanged.

### 2026-02-27_11.45.18 speed1-4 runner/replay contract closeout (`docs/tasks/2026-02-27_11.45.18-speed1-4-remaining-implementation.md`)

Problem captured:
- Audit gaps: no explicit stage-runner API contract, run-level prediction record shape, replay strictness tied to path pointers, and incomplete pipelined producer/consumer behavior.

Decision/outcome preserved:
- Explicit functions/wiring expected in benchmark runtime:
  - `predict_stage(...)`
  - `evaluate_stage(...)`
  - `run_legacy(...)`
  - `run_pipelined(...)`
- `--predictions-out` contract set to per-block records (`schema_kind=stage-block.v1`) with deterministic `example_id`/`example_index`.
- `--predictions-in` evaluate-only accepts both:
  - per-block replay records,
  - legacy single-record run-pointer payloads.

Evidence preserved from task:
- Transition fail-before captured from tests still asserting single-run-level records.
- Pass-after recorded:
  - `python -m py_compile cookimport/cli.py tests/labelstudio/test_labelstudio_benchmark_helpers.py` exit `0`
  - `pytest -q tests/bench/test_prediction_records.py` exit `0`
  - `pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py` exit `0`

### 2026-02-27_12.00.02 speed1-5 closure pass (`docs/tasks/2026-02-27_12.00.02-speed1-5-remaining-implementation.md`)

Problem captured:
- Remaining implementable gaps: prepared-archive abstraction, split-merge `outputStats` ordering/undercount risk, missing stats parity coverage, direct bench-run write toggles, shallow no-drift proof.

Decision/outcome preserved:
- Added `PreparedExtractedArchive` + `prepare_extracted_archive(...)` abstraction and reuse.
- Kept split-merge report emission after raw merge; moved raw artifacts recorded in `outputStats`.
- Added direct `bench run` write toggles that override config only when passed:
  - `--write-markdown/--no-write-markdown`
  - `--write-labelstudio-tasks/--no-write-labelstudio-tasks`
- Added no-drift checks ensuring stage predictions remain identical across markdown-toggle modes.

Evidence preserved from task:
- `tests/staging/test_split_merge_status.py` targeted run passed.
- `tests/labelstudio/test_labelstudio_ingest_parallel.py` targeted speed1-5 slice passed.
- `tests/bench/test_bench.py` targeted bench-run override slice passed.
- `bench run --help` output included both direct write-toggle pairs.

Cross-folder note:
- Detailed split-merge ordering details were merged into staging docs (`docs/05-staging`).

### 2026-02-27_12.23.26 speed1-4 true streaming overlap ExecPlan closeout (`docs/tasks/2026-02-27_12.23.26-speed1-4-true-streaming-pipeline.md`)

Problem captured:
- Pipelined mode previously overlapped prediction with prewarm but not true predict->evaluate consumption overlap.

Decision/outcome preserved:
- Implement producer/consumer streaming in `run_pipelined(...)` with bounded queue, EOS signaling, and shared error propagation.
- Keep evaluator internals path-based; introduce streaming adapters/replay assembly instead of scoring rewrite.
- Keep CLI surface unchanged (`legacy|pipelined|predict-only`), redefine `pipelined` behavior to true overlap.
- Preserve replay compatibility:
  - strict per-block + legacy pointer input in evaluate-only,
  - tolerant stream-finalized reconstruction for live pipelined replay.

Evidence preserved from task:
- Overlap ordering, parity, and failure-propagation targeted tests recorded as passing.
- Plan progress marked fully complete with docs/understanding updates.

### 2026-02-27_18.04.57 all-method scheduler timeseries + CPU sampling (`docs/tasks/2026-02-27_18.04.57-all-method-scheduler-timeseries-cpu.md`)

Problem captured:
- Scheduler state only visible in spinner/rollup text; no persisted run-local scheduler+CPU timeline.

Decision/outcome preserved:
- Write `<source_root>/scheduler_timeseries.jsonl` with scheduler counters and elapsed timestamps.
- Add host CPU utilization sampling via lightweight `/proc/stat` parsing, no new dependencies.
- Emit rows on snapshot change plus 1.0s heartbeat.

Evidence preserved from task:
- Added `test_run_all_method_benchmark_writes_scheduler_timeseries`.
- Targeted scheduler tests passed (`2 passed`).

Cross-folder note:
- Processing-timeseries generalization from the same period is merged in analytics docs (`docs/08-analytics`).

### 2026-02-27_18.35.38 multilayer selector spike ExecPlan (`docs/tasks/2026-02-27_18.35.38-multilayer-sequence-matcher-spike.md`)

Problem captured:
- Need explicit A/B evidence on whether MultiLayer matcher can improve canonical tail cases vs current selector baseline.

Decision/outcome preserved:
- Ship `multilayer` as explicit opt-in selector mode (no default-order change).
- Keep `auto`/`fallback` behavior unchanged for production baseline stability.
- Add parity tests and script support for `stdlib|auto|multilayer` timing comparison.

Evidence preserved from task:
- `tests/bench/test_sequence_matcher_dropin_parity.py` passed.
- Synthetic timing samples showed:
  - `multilayer` faster than stdlib,
  - `multilayer` slower than fallback/`cydifflib` on sampled synthetic inputs.

Open item preserved:
- Real-input all-method A/B evidence remains required before adoption decision.

### 2026-02-27_18.43.40 dead-PID lock recovery for canonical cache (`docs/tasks/2026-02-27_18.43.40-canonical-cache-dead-pid-lock-recovery.md`)

Problem captured:
- Age-only stale-lock logic delayed recovery when lock owner PID was already dead, causing long waits/tails.

Decision/outcome preserved:
- Primary stale test now uses lock-owner PID liveness.
- Existing age-based stale fallback remains for malformed/non-PID lock metadata.

Evidence preserved from task:
- Fail-before showed dead-owner path waiting ~5s (`assert < 1.0` failure).
- Pass-after:
  - `pytest tests/bench/test_canonical_alignment_cache.py -k dead_owner -q` exit `0`
  - full cache tests exit `0`
  - stale-lock eval tests exit `0`

### 2026-02-27_18.55.29 all-method tail-throughput source scheduling/sharding plan (`docs/tasks/2026-02-27_18.55.29-all-method-tail-throughput-plan.md`)

Problem captured:
- Multi-source all-method dispatch was discovery/FIFO ordered; large runtime skew stranded heavy sources in final tails with low endgame utilization.

Decision/outcome preserved:
- Added source planning helpers:
  - `_estimate_all_method_source_cost`
  - `_split_all_method_source_variants`
  - `_plan_all_method_source_jobs`
- Added heavy-source variant sharding and shard metadata.
- Added source scheduling strategy (`discovery` vs `tail_pair`) with interactive/settings wiring.
- Raised practical source parallel defaults with CPU-aware effective cap handling.
- Added shared canonical cache override by `source_group_key` to avoid shard sibling recompute.
- Combined report preserves one top-level source row while surfacing additive shard metadata.

Evidence/status preserved from task:
- Focused planner/sharding/order/cap tests recorded as passing.
- Task explicitly marked manual interactive all-matched validation as pending.

### 2026-02-27_18.58.13 multilayer spike status handoff (`docs/tasks/2026-02-27_18.58.13-multilayer-spike-status-summary.md`)

Problem captured:
- Needed full status/handoff on what multilayer spike work actually landed, what evidence exists, and what was interrupted.

Decision/outcome preserved:
- Keep multilayer as opt-in mode; do not change default fallback-chain behavior.
- Document requested-vs-effective matcher telemetry split and CLI setting/override wiring.
- Preserve current interactive/bench command matcher override behavior and Typer default-unwrapping compatibility.

Evidence preserved from task:
- Parity suite and benchmark helper/bench slices listed as passing.
- Synthetic timing samples repeated with similar pattern:
  - stdlib much slower,
  - auto (`cydifflib`) fastest,
  - multilayer between stdlib and auto,
  - parity flags true.

Interrupted work preserved:
- Long real-input SaltFatAcidHeat comparison was started then cancelled before final artifact capture.

Recommendation state preserved:
- Keep `multilayer` opt-in until full benchmark-scale A/B evidence is collected.
