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
