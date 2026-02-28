---
summary: "Retained benchmark architecture/build/fix chronology for active benchmark features."
read_when:
  - When benchmark behavior debugging is looping and you need prior decisions
  - When changing active benchmark contracts (stage-block, canonical-text, all-method, speed suite)
  - When validating why current benchmark constraints exist
---

# Bench Log: Architecture, Builds, and Fix Attempts

This log was pruned to retain only history that still maps to active benchmark features.
Entries tied to removed benchmark surfaces were retired from this file.

## 1. 2026-02-19_15.49.31 README/Log split marker

Decision retained:
- `docs/07-bench/07-bench_README.md` is the current-state benchmark contract.
- `docs/07-bench/07-bench_log.md` is chronology + anti-loop context.

## 2. 2026-02-25 stage-block benchmark contract rollout

Problem addressed:
- Legacy benchmark scoring could diverge from stage outputs and produced misleading label outcomes.

Durable decisions:
- Primary prediction surface is `stage_block_predictions.json` (stage evidence), not pipeline-task artifacts.
- `labelstudio-benchmark` and `bench run` require both:
  - `stage_block_predictions.json`
  - `extracted_archive.json`
- Stage-block evaluation is block classification and reports:
  - `overall_block_accuracy`
  - `macro_f1_excluding_other`
  - `worst_label_recall`

Anti-loop note:
- Missing stage-block artifacts is an artifact-generation/fixture contract issue, not scorer-math drift.

## 3. 2026-02-25 multi-label gold + mismatch guard hardening

Problems addressed:
- Freeform gold can contain multiple labels for one block.
- Gold/prediction extractor drift can silently produce invalid block-level comparisons.

Durable decisions:
- Multi-label gold per block is valid; prediction is correct when label is in allowed set.
- Missing-gold predicted blocks default to `OTHER` and are logged in `gold_conflicts.jsonl`.
- Evaluator fingerprints blockization metadata and fails with `gold_prediction_blockization_mismatch` when severe drift is detected.

Anti-loop note:
- If metrics look impossible, verify blockization parity and mismatch diagnostics before changing precision/recall logic.

## 4. 2026-02-26 canonical-text all-method default and eval visibility

Problems addressed:
- All-method extractor permutations are not valid under stage-block index parity.
- Long canonical eval phases looked frozen without evaluation-phase status.

Durable decisions:
- Interactive benchmark modes (`single_offline`, `all_method`) use `canonical-text`.
- Non-suppressed benchmark runs keep visible evaluation status.
- Canonical-text exists specifically to score extractor permutations in canonical line space.

## 5. 2026-02-26 canonical alignment safety boundary

Problem addressed:
- Fast canonical alignment introduced scoring-risk ambiguity.

Durable decisions:
- Canonical scoring enforces legacy global alignment semantics.
- `COOKIMPORT_CANONICAL_ALIGNMENT_STRATEGY=auto|fast` is treated as deprecated request and forced to legacy.
- Reports/telemetry keep explicit deprecation and alignment strategy fields.

## 6. 2026-02-26 to 2026-02-27 matcher selection surface

Problems addressed:
- Need benchmark runtime acceleration without changing scoring semantics.
- Need clear requested-vs-effective matcher observability.

Durable decisions:
- Matcher selector contract is `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`:
  - `fallback|stdlib|cydifflib|cdifflib|dmp|multilayer`
  - legacy `auto` alias maps to `fallback`
- Fallback chain is deterministic (`cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`) and telemetry records requested/effective/forced mode.
- `multilayer` can be explicitly forced, and fallback reaches it only after higher-priority accelerators are unavailable.

Anti-loop note:
- Byte-parity checks across matcher implementations should use `aligned_prediction_blocks.jsonl`, not `eval_report.json`.

## 7. 2026-02-27 canonical alignment cache reliability updates

Problems addressed:
- Canonical eval tails were dominated by repeated miss-path alignment work.
- Dead-owner lock files could stall progress under age-only stale lock checks.

Durable decisions:
- All-method uses shared per-source canonical cache roots.
- Cache keys include canonical text hash, prediction text hash, and boundary signature.
- Dead-owner lock reclamation checks PID liveness first, then falls back to age-based stale handling for malformed lock metadata.

Evidence retained:
- Miss->hit runs showed matcher-time and wall-time drops while preserving quality metrics.

Anti-loop note:
- When cache benefit is absent, inspect `evaluation_telemetry.alignment_cache_key` equality before changing cache policy.

## 8. 2026-02-27 speed1-4 benchmark stage/replay contract closeout

Problems addressed:
- Replay/evaluate-only paths were under-specified.
- Pipelined mode needed explicit producer/consumer boundary behavior.

Durable decisions:
- Runtime boundary functions are explicit:
  - `predict_stage(...)`
  - `evaluate_stage(...)`
  - `run_legacy(...)`
  - `run_pipelined(...)`
- `--predictions-out` emits per-block prediction records (`schema_kind=stage-block.v1`).
- `--predictions-in` evaluate-only accepts both:
  - per-block records
  - legacy run-pointer records
- `pipelined` mode is true producer/consumer replay overlap while evaluators remain path-based.

## 9. 2026-02-27 speed1-5 artifact-write controls

Problem addressed:
- Non-scoring artifact writes (markdown/tasks jsonl) added runtime cost and needed deterministic toggles.

Durable decisions:
- Stage and benchmark support write toggles:
  - `--write-markdown/--no-write-markdown`
  - `--write-labelstudio-tasks/--no-write-labelstudio-tasks` (offline paths)
- Intentional task-jsonl skips are explicit in manifests (`tasks_jsonl_status`).
- Prediction-surface no-drift checks were added for markdown-toggle variations.

## 10. 2026-02-27 all-method scheduler/runtime interpretation contracts

Problems addressed:
- Operators misread heavy-slot counters and live fail counters.
- Throughput tails on multi-source runs were sensitive to source ordering and caps.

Durable decisions:
- `scheduler heavy X/Y` represents split-active occupancy only.
- Live queue fail counters are attempt-level; final truth is per-source report status after retries/timeouts.
- Scheduler runtime contract includes configured/effective eval-tail fields and explicit admission ceiling.
- Source-level orchestration includes bounded parallelism, source scheduling strategy, and optional heavy-source sharding.

Anti-loop note:
- Low late-run CPU can be structurally normal on final-source canonical tails; use scheduler events, CPU, and cache-lock health before declaring stalls.

## 11. 2026-02-27 speed-suite baseline/candidate workflow

Problem addressed:
- Quality benchmark runs are not enough for deterministic runtime regression gating.

Durable decisions:
- Introduced `bench speed-discover`, `bench speed-run`, `bench speed-compare` as a dedicated speed-regression lane.
- Shared target matching contract uses source-hint fallback order:
  1. `manifest.json` `source_file`
  2. `run_manifest.json` `source.path`
  3. first `source_file` in `freeform_span_labels.jsonl`
  4. first `source_file` in `freeform_segment_manifest.jsonl`

## 12. 2026-02-27 direct-call compatibility boundary for bench CLI helpers

Problem addressed:
- Direct Python calls to bench command helpers could receive Typer `OptionInfo` defaults and fail matcher normalization.

Durable decision:
- Bench command helpers unwrap Typer defaults at function entry before validation/normalization.

Anti-loop note:
- Treat direct-call behavior as a compatibility contract for tests/internal invocations, not incidental CLI-only behavior.

## 13. 2026-02-28 benchmark docs code-map completeness sync

Problem addressed:
- `docs/07-bench/07-bench_README.md` code map had drifted and omitted active helper modules/artifacts still used by benchmark flows.

Durable decisions:
- README now enumerates all active `cookimport/bench/*.py` modules with one-line responsibilities.
- README now calls out suite/sweep/speed/prediction-record artifact families (including trace, noise, cost, iteration packet, and replay artifacts).
- Matcher-history wording in this log now matches the actual fallback chain and multilayer behavior in code.

Anti-loop note:
- If benchmark docs feel incomplete, diff README code-map entries against `cookimport/bench/*.py` before assuming a module is retired.

## 14. Retired History Notice

The following legacy surfaces were intentionally removed from this log to keep it relevant:
- pipeline-task span-IoU benchmark scoring chronology
- upload-first interactive benchmark flow chronology
- fast canonical alignment as a production scoring path

Older artifacts referencing those surfaces are historical context only and should not be used as current contract guidance.

## 15. 2026-02-27 merged understanding ledger (all-method tail, matcher, and doc coverage)

### 2026-02-27_19.21.15 all-method 91/91 retry/eval tail semantics

Durable findings:
- `config N/N` completion reflects first pass only; retries can continue after spinner reaches `N/N`.
- Retry + canonical eval tail can keep run active with apparently frozen per-source counters.

### 2026-02-27_19.23.51 fallback chain includes multilayer before stdlib

Durable findings:
- Effective fallback order is `cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`.
- Multilayer must be ahead of final stdlib fallback to ever be selected.

### 2026-02-27_19.24.31 stopping in-flight retries without killing parent

Durable findings:
- Terminating active worker child PIDs can short-circuit retry tails while preserving final report emission.

### 2026-02-27_19.31.54 canonical cache scope and lock wait behavior

Durable findings:
- Cache hit telemetry does not imply low wall time when lock waits dominate.
- Run-local cache prevents recompute but cross-run persistence gives larger rerun wins.

### 2026-02-27_19.34.53 benchmark-vs-golden config signal

Durable findings:
- This run favored stable unstructured-v1 configs for reliability/runtime trade-off.
- Large-source instability was observed in v2/non-unstructured variants in this sample.

### 2026-02-27_19.42.47 all-method EPUB extractor default scope

Durable findings:
- Default variants are `unstructured` + `beautifulsoup`; markdown extractors are opt-in.

### 2026-02-27_19.47.10 all-method evaluation dedupe hook points

Durable findings:
- Integration point for predict/eval split is `_run_all_method_benchmark(...)` orchestration, not evaluator internals.

### 2026-02-27_19.49.45 tail-throughput plan audit

Durable findings:
- Source planning/sharding/tail-pair and shared cache-dir wiring landed in code/tests/docs.
- Remaining validation gap noted: fresh wall-clock baseline-vs-candidate confirmation was not captured in that audit.

### 2026-02-27_19.51.07 bench docs code-map completeness audit

Durable findings:
- README code map must track all active `cookimport/bench/*.py` runtime modules and artifact families.

Anti-loop summary:
- Distinguish retry/eval tail from deadlock before changing scheduler logic.
- Treat matcher fallback ordering and cache-lock behavior as first-line diagnostics for canonical-text slowness.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_20.00.30 speed suite all method scenario scope

Source: `docs/understandings/2026-02-27_20.00.30-speed-suite-all-method-scenario-scope.md`
Summary: SpeedSuite originally exercised only stage-import and single-source canonical benchmark paths; multi-source all-method scheduling needed a suite-level scenario.

Details preserved:


# Speed Suite All-Method Scenario Scope

Discovery:

- `cookimport/bench/speed_runner.py` previously modeled every scenario as target-scoped (`target x scenario x phase`), so it only called:
  - `_run_stage_import_sample(...)`
  - `_run_benchmark_sample(...)` (single-source `labelstudio_benchmark`)
- That shape did not execute `_run_all_method_benchmark_multi_source(...)`, which is where source scheduling (`tail_pair`), source sharding, and source-level parallel dispatch live.

Implementation direction:

- Add a suite-level speed scenario (`benchmark_all_method_multi_source`) that runs once per sample-phase using all selected targets.
- Keep existing target-scoped scenarios unchanged.
- Emit synthetic target id `__all_matched__` (folder `_all_matched`) so summary grouping remains deterministic.

### 2026-02-27_20.04.16 speedsuite all method target matching single contract

Source: `docs/understandings/2026-02-27_20.04.16-speedsuite-all-method-target-matching-single-contract.md`
Summary: All-method matched-target discovery had drifted from SpeedSuite discovery; both now share speed_suite.match_gold_exports_to_inputs.

Details preserved:


# SpeedSuite + All-Method Target Matching Contract

Discovery:

- `cookimport/cli.py:_resolve_all_method_targets(...)` had an inlined matcher flow that duplicated SpeedSuite logic.
- The duplicate path had already diverged from `cookimport/bench/speed_suite.py` behavior (notably source-hint fallback details).

Resolution:

- `_resolve_all_method_targets(...)` now delegates matching to `cookimport.bench.speed_suite.match_gold_exports_to_inputs(...)`.
- The CLI path still supplies `cli._list_importable_files(DEFAULT_INPUT)` so interactive tests can keep controlling importable-file fixtures.

Impact:

- One matcher contract now feeds both SpeedSuite and all-method matched-target selection, reducing maintenance drift risk.

### 2026-02-27_20.07.10 all method eval signature cache and provenance

Source: `docs/understandings/2026-02-27_20.07.10-all-method-eval-signature-cache-and-provenance.md`
Summary: All-method now runs predict-only per config, then evaluates once per unique signature and reuses/materializes results.

Details preserved:


# All-Method Eval Signature Cache And Provenance

Key flow now:

- Phase A runs each config with `execution_mode=predict-only` and writes `prediction-records.jsonl`.
- Phase B computes `eval_signature` from prediction payload + gold fingerprints + evaluator settings.
- One representative config per signature runs evaluate-only (`predictions_in=...`), then duplicates reuse that result.

Cache behavior:

- Cache entries are written to `.../.cache/eval_signature_results/<source_group_key>/<eval_signature>.json` when a signature is executed.
- On cache hit, the run skips evaluate-only and materializes `eval_report.json` + `eval_report.md` into the representative config directory.

Per-config provenance fields:

- `eval_signature`
- `evaluation_result_source`: `executed`, `reused_in_run`, or `reused_cross_run`
- `evaluation_representative_config_dir`

### 2026-02-27_20.09.09 recipe notes variant zero pred in canonical benchmark

Source: `docs/understandings/2026-02-27_20.09.09-recipe-notes-variant-zero-pred-in-canonical-benchmark.md`
Summary: In 2026-02-27_17.54.41 canonical all-method runs, RECIPE_NOTES had zero predictions because stage evidence sources notes only from recipe comments, which were absent; RECIPE_VARIANT was also zero for amatteroftaste because no variant-prefixed instruction text was extracted.

Details preserved:


# RECIPE_NOTES / RECIPE_VARIANT Zero-Pred Discovery

Discovery:

- The dashboard row for `2026-02-27_17.54.41` comes from:
  - `data/golden/benchmark-vs-golden/2026-02-27_17.54.41/all-method-benchmark/amatteroftastecutdown/config_001_682eb9140f50_extractor_unstructured__parser_v1__skiphf_false__pre_none/eval_report.json`
- Matching stage evidence for that record shows:
  - `label_blocks.RECIPE_NOTES = 0`
  - `label_blocks.RECIPE_VARIANT = 0`
  - `label_blocks.KNOWLEDGE = 565`
  - file: `.../prediction-run/stage_block_predictions.json`

Code-path findings:

- Stage builder emits `RECIPE_NOTES` only from `_note_texts(recipe)`.
- `_note_texts(recipe)` only reads `recipe.comments` text/name.
- In this benchmark run, intermediate recipe drafts had zero non-empty `comment` fields, so `RECIPE_NOTES` could not be emitted.
- `RECIPE_VARIANT` is derived from instruction lines matching `variations?/variants?` patterns.
- For `amatteroftastecutdown` config_001, no extracted instruction line matched that prefix, so `RECIPE_VARIANT` stayed zero.

Scope check for this all-method run:

- Across all 91 config/source evaluations under `2026-02-27_17.54.41`, `RECIPE_NOTES` predictions were zero in every `prediction-run/stage_block_predictions.json`.

### 2026-02-27_20.09.48 speedsuite runtime parity drift map

Source: `docs/understandings/2026-02-27_20.09.48-speedsuite-runtime-parity-drift-map.md`
Summary: SpeedSuite runs production entrypoints but still had duplicated run-settings-to-kwargs mapping across interactive and speed paths.

Details preserved:


# SpeedSuite Runtime Parity Drift Map

Discovery:

- SpeedSuite already executes real runtime entrypoints (`stage`, `labelstudio_benchmark`, all-method runner internals).
- Remaining drift risk is in duplicated kwargs assembly from `RunSettings`.

Where duplication exists:

- `cookimport/cli.py` interactive import builds `common_args` manually.
- `cookimport/cli.py` interactive single-offline benchmark builds `benchmark_kwargs` manually.
- `cookimport/bench/speed_runner.py` scenarios build runtime kwargs manually.

Implication:

- New run settings can silently propagate to one path and not the others.
- Speed comparisons can look valid while runtime knobs differ, unless settings identity is persisted and compared.

### 2026-02-27_20.43.12 quality suite reuse points

Source: `docs/understandings/2026-02-27_20.43.12-quality-suite-reuse-points.md`
Summary: QualitySuite can reuse speed-suite matching and all-method benchmark orchestration without adding new scoring engines.

Details preserved:


# QualitySuite Reuse Points

QualitySuite should reuse two stable contracts that already exist. Target matching can reuse `cookimport.bench.speed_suite.match_gold_exports_to_inputs`, which already handles the source-hint fallback chain and unmatched diagnostics. Quality evaluation can reuse `cookimport.cli._run_all_method_benchmark_multi_source`, which already executes canonical all-method variants, tracks scheduler telemetry, and writes per-source quality-rich report payloads.

The biggest gap is not scoring logic but workflow packaging for iterative tuning: deterministic representative target selection, experiment definition, and baseline-vs-candidate quality comparison with clear PASS/FAIL gating.

### 2026-02-27_20.49.27 quality suite plan gap audit

Source: `docs/understandings/2026-02-27_20.49.27-quality-suite-plan-gap-audit.md`
Summary: QualitySuite planning gap audit: practical metric aggregation, strict patch validation, and sharded-source aggregation rules were the critical missing contracts.

Details preserved:


# QualitySuite Plan Gap Audit

The initial QualitySuite plan had three high-risk ambiguities. First, multi-source all-method reports only expose strict winner metrics in `sources[*].winner_metrics`, so practical metrics must be read from per-source `all_method_benchmark_report.json` winner rows to support strict+practical gating. Second, `RunSettings.from_dict` ignores unknown keys, so experiment patches need an explicit unknown-key failure path to prevent silent typo bugs. Third, source sharding can emit multiple rows for one logical source, so summary aggregation must collapse by `source_group_key` instead of averaging raw rows.

### 2026-02-27_20.56.29 all method multi source scheduling vs global queue

Source: `docs/understandings/2026-02-27_20.56.29-all-method-multi-source-scheduling-vs-global-queue.md`
Summary: All-method bulk runs currently interleave at source-job level, but config scheduling/eval dedupe is per-source rather than one global mega-queue.

Details preserved:


# All-Method Multi-Source Scheduling Vs Global Queue

Observed current behavior in `cookimport/cli.py`:

- Bulk mode first builds `source_job_plans` (`_plan_all_method_source_jobs`) and dispatches those with a source-level thread pool in `_run_all_method_benchmark_multi_source`.
- Source-job order defaults to `tail_pair` (heavy/light alternating by estimated source cost), with optional source sharding when estimated source cost exceeds threshold.
- Each source job runs `_run_all_method_benchmark` independently with its own config queue/process pool and its own split-phase gate directory (`<source_root>/.split_phase_slots`).
- Inside one source job, execution is 2-phase:
  1. Run all configs in `predict-only` mode.
  2. Build eval signatures and run canonical evaluate-only once per unique signature, then reuse for duplicates.
- Eval-signature reuse and cache directories are scoped by source group key (`.../eval_signature_results/<source_group_key>/...`), so dedupe/cache sharing is not global across different source groups.

Implication:

- This is intelligent per-source scheduling + cross-source source-job interleaving, but not a single global mega-queue over all `(source, config)` units.
- A true mega-run scheduler would need a global work queue/admission policy shared across all source jobs (including global signature grouping/caching decisions if desired).

### 2026-02-27_20.56.32 all method source cap via cookimport setting

Source: `docs/understandings/2026-02-27_20.56.32-all-method-source-cap-via-cookimport-setting.md`
Summary: All-method multi-source concurrency is hard-capped by cookimport.json all_method_max_parallel_sources when set.

Details preserved:


In `_interactive_all_method_benchmark`, the all-method run forwards `all_method_max_parallel_sources` from `cookimport.json` into `_run_all_method_benchmark_multi_source`.

If that setting is present and valid, `_resolve_all_method_source_parallelism(...)` uses it as the cap, even when CPU-based defaults are higher.

Practical effect: with `all_method_max_parallel_sources = 2`, the scheduler can run at most two source jobs at once, which can leave CPU underutilized on larger hosts (for example 16 cores).

### 2026-02-27_21.00.19 og plan build status audit

Source: `docs/understandings/2026-02-27_21.00.19-og-plan-build-status-audit.md`
Summary: Audit result: the three OG plans for speed suite, all-method tail throughput, and eval-signature dedupe are implemented and covered by targeted tests.

Details preserved:


# OG Plan Build Status Audit

- Scope audited:
  - `docs/plans/OGplan/2026-02-27_18.51.16-speed-regression-benchmark-suite-from-pulled-goldens.md`
  - `docs/plans/OGplan/2026-02-27_18.55.29-all-method-tail-throughput-plan.md`
  - `docs/plans/OGplan/2026-02-27_19.45.53-all-method-eval-signature-dedupe.md`
- Result: all three are implemented in current code paths and exercised by focused tests.
- Verified by:
  - Code surface checks in `cookimport/bench/speed_*`, `cookimport/cli.py`, and benchmark docs.
  - Focused pytest slices run in `.venv`:
    - `tests/bench/test_speed_suite_discovery.py`
    - `tests/bench/test_speed_suite_runner.py`
    - `tests/bench/test_speed_suite_compare.py`
    - `tests/bench/test_bench.py -k "speed_discover or speed_run or speed_compare"`
    - `tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "tail_pair or shard or planner or source_parallelism or multi_source_parallel_cap_and_ordering"`
    - `tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "all_method or predict_only or predictions_in"`
    - `tests/bench/test_prediction_records.py tests/bench/test_canonical_alignment_cache.py`

### 2026-02-27_21.00.53 priority plans vs per label metric shape

Source: `docs/understandings/2026-02-27_21.00.53-priority-plans-vs-per-label-metric-shape.md`
Summary: Quick mapping from Priority 1-8 plan ideas to current per-label benchmark error shape.

Details preserved:


# Priority Plans vs Per-Label Metric Shape

For the 2026-02-27 multi-source all-method run, the per-label pattern is structurally dominated by:

- Overprediction (low precision) on `RECIPE_NOTES`, `RECIPE_VARIANT`, `RECIPE_TITLE`, and `INGREDIENT_LINE`.
- Underprediction (low recall, high precision) on `YIELD_LINE` and `TIME_LINE`.
- Mixed structural confusion on `INSTRUCTION_LINE`, `KNOWLEDGE`, and `OTHER`.

Most likely high-leverage priorities for these symptoms:

1. Priority 2 (shared section detection across importers): direct structural classification improvement for ingredient/instruction/notes/variant/title-like boundaries.
2. Priority 3 (multi-recipe splitting): should reduce title/boundary-related confusion and cross-recipe bleed that can inflate false positives.
3. Priority 6 (time/yield upgrades): specifically targets low-recall `TIME_LINE`/`YIELD_LINE` behavior.
4. Priority 5 (fallback step segmentation): likely second-order boost for instruction and section clarity when importers hand off giant instruction paragraphs.

Lower direct leverage on block-label metrics:

- Priority 8: mostly measurement and diagnostics (high value for tuning loops, but does not directly improve predictions by itself).
- Priority 4: ingredient *line parsing* quality after extraction, likely limited impact on `INGREDIENT_LINE` label assignment itself.
- Priority 7: high value for HTML/JSON schema sources, limited impact for EPUB-dominated runs unless source mix changes.
- Priority 1: candidate gating can reduce gross false positives but is less targeted to per-block label confusion than Priority 2/3/6.

### 2026-02-27_21.01.55 hix all method eval exit 1 lost error

Source: `docs/understandings/2026-02-27_21.01.55-hix-all-method-eval-exit-1-lost-error.md`
Summary: All-method Hix source failure with error `\"1\"` is a wrapped Typer exit that drops the underlying pre-eval message.

Details preserved:


# Hix all-method failed variant (`error: "1"`)

- In run `data/golden/benchmark-vs-golden/2026-02-27_20.50.38`, `hix_written` completed prediction but was marked failed at evaluation aggregation (`successful=0`, `failed=1`, `evaluation_runs_executed=0`).
- The stored failure text `\"1\"` comes from catching `typer.Exit(1)` in `_run_all_method_evaluate_prediction_record_once` and serializing `str(exc)`.
- `labelstudio_benchmark` only raises `typer.Exit(1)` via `_fail(...)`; in this evaluate-only path that means a pre-eval validation guard failed (for example prediction-record input load/validation) before normal eval artifact writes.
- Evidence from this run: no eval-side replay directory under the failed config (`.prediction-record-replay` absent), matching an early exit before normal evaluate-only reconstruction.
- Re-running the same evaluate-only call against the saved `prediction-records.jsonl` now succeeds, so this looks transient/non-deterministic rather than a stable scorer bug.


### 2026-02-27_21.08.11 quality suite shard aggregation and settings guard

Source: `docs/understandings/2026-02-27_21.08.11-quality-suite-shard-aggregation-and-settings-guard.md`
Summary: QualitySuite quality-run must source practical metrics from per-source winner reports and enforce strict run_settings_patch key validation before RunSettings normalization.

Details preserved:


# QualitySuite Shard Aggregation And Settings Guard

All-method multi-source report rows only carry strict `winner_metrics` in top-level `sources[*]`. Practical metrics used for quality gating must therefore be read from per-source `all_method_benchmark_report.json` `winner_by_f1` payloads. For sharded sources, `quality-run` should inspect every shard report path in `report_json_paths`, choose the shard winner with highest strict F1, and use that shard's strict+practical metrics for one source-group row in macro aggregation.

`RunSettings.from_dict(...)` intentionally ignores unknown keys, so QualitySuite experiment payloads need a strict pre-validation gate on `run_settings_patch` keys (`RunSettings.model_fields`) before normalization. This prevents typoed patch keys from silently no-oping and contaminating baseline/candidate comparisons.

### 2026-02-27_21.29.02 all method scheduler scope dispatch and legacy payload fix

Source: `docs/understandings/2026-02-27_21.29.02-all-method-scheduler-scope-dispatch-and-legacy-payload-fix.md`
Summary: Global scheduler default changed multi-source test behavior; legacy combined payload also needed an explicit failed-config counter.

Details preserved:


# All-Method Scheduler Scope Dispatch And Legacy Payload Fix

Key implementation discoveries while shipping the global mega-run scheduler:

- `_run_all_method_benchmark_multi_source(...)` now defaults to `scheduler_scope=global`.
- Existing tests that monkeypatch `_run_all_method_benchmark(...)` were implicitly testing legacy dispatch and started executing real benchmark code until `scheduler_scope=legacy` was passed explicitly.
- Legacy combined report payload writes additive `global_queue_*` counters for contract parity; this path must compute `total_failed_config_runs` before payload render.

Fixes applied:

- Added explicit `scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY` in legacy-oriented helper tests.
- Added wrapper dispatch tests that prove default -> global helper and explicit legacy -> legacy helper.
- Fixed `_run_all_method_benchmark_multi_source_legacy(...)` to compute `total_failed_config_runs` before report payload construction.

### 2026-02-27_22.25.29 priority8 current eval surface audit

Source: `docs/understandings/2026-02-27_22.25.29-priority8-current-eval-surface-audit.md`
Summary: Priority 8 audit: stage-block evaluator is classification-only today; segmentation metrics are still pending and should extend existing bench eval surfaces.

Details preserved:


# Priority 8 Current Eval Surface Audit

- `cookimport/bench/eval_stage_blocks.py` currently reports block-label classification metrics and mismatch artifacts only; it does not emit a `segmentation` section or taxonomy buckets.
- `cookimport/cli.py` already has `cookimport bench eval-stage` as the offline stage-block evaluator entrypoint, so Priority 8 should extend this surface first instead of introducing redundant command paths.
- `stage_block_predictions.v1` in current code expects a `block_labels` map (plus optional `block_count` completeness check), not a `predictions` list payload.
- `labelstudio-benchmark` now supports both `stage-blocks` and `canonical-text`, and modern benchmark loops heavily use canonical-text; Priority 8 must stay additive and not disturb that split.
- `pyproject.toml` has no `segeval` extra yet (`db`, `benchaccel`, `dev`, `epubdebug` only), so optional backend wiring is still future work.
- Before this update, `docs/plans/priority-8.md` was identical to `docs/plans/OGplan/priority-8.md`, which left the active plan stale.

### 2026-02-27_22.47.26 priority8 segmentation implementation shape

Source: `docs/understandings/2026-02-27_22.47.26-priority8-segmentation-implementation-shape.md`
Summary: Priority 8 implementation shape: additive segmentation metrics/taxonomy live inside stage-block eval with optional segeval extras.

Details preserved:


# Priority 8 Segmentation Implementation Shape

- `cookimport/bench/eval_stage_blocks.py` now computes classification metrics first, then additive segmentation diagnostics in the same run.
- Structural projection is fixed to `core_structural_v1` (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, everything else -> `OTHER`) and boundary tolerance is configurable.
- Boundary diagnostics now include two JSONL artifacts: `missed_gold_boundaries.jsonl` and `false_positive_boundaries.jsonl`.
- Optional metrics (`pk`, `windowdiff`, `boundary_similarity`) are lazy-loaded through `cookimport/bench/segeval_adapter.py`; requesting them without dependency installation raises clear install guidance.
- `cookimport bench eval-stage` now exposes `--label-projection`, `--boundary-tolerance-blocks`, and `--segmentation-metrics`; bench suite paths rely on evaluator defaults and still receive the additive segmentation payload.

### 2026-02-28_01.24.58 speed suite run settings adapter parity

Source: `docs/understandings/2026-02-28_01.24.58-speed-suite-run-settings-adapter-parity.md`
Summary: SpeedSuite parity is primarily about sharing one RunSettings->kwargs adapter layer and carrying effective settings identity into speed artifacts/compare.

Details preserved:


# SpeedSuite Run-Settings Adapter Parity

Discovery:

- Runtime drift was caused by duplicated kwargs assembly, not by separate execution engines. Interactive import, interactive single-offline benchmark, and speed scenarios all needed one shared mapping layer.
- The practical contract is: build effective `RunSettings` once for speed-run, pass that object through every scenario call, write `run_settings_hash` in speed artifacts, and make compare fail by default when hashes differ.

Implication:

- New run-setting fields now have one adapter surface to update (`cookimport/config/run_settings_adapters.py`) instead of per-caller dict edits.
- Baseline/candidate speed verdicts are now guarded against accidental settings drift unless the operator explicitly opts in with `--allow-settings-mismatch`.

### 2026-02-28_03.05.00 sequence matcher locked to dmp

Source: `docs/understandings/2026-02-28_03.05.00-sequence-matcher-locked-to-dmp.md`
Summary: Canonical benchmark alignment now accepts only DMP matcher mode; fallback/stdlib/cydifflib/cdifflib/multilayer modes are archived and rejected.

Details preserved:


# Sequence Matcher Locked To DMP

Discovery:

- Sequence matcher selection drift came from supporting many modes in selector/config/docs/tests while production speed evidence favored DMP.
- The stable contract is now strict: default to `dmp`, reject non-`dmp`, and error if `fast-diff-match-patch` is unavailable.

Implication:

- Benchmark run settings, CLI overrides, and canonical-eval telemetry now consistently report `dmp` as requested/effective mode.
- Older configs/tests/docs that reference `fallback` or other matcher modes must be treated as historical and migrated.

## 2026-02-27 tasks consolidation ledger (migrated from `docs/tasks`)

The following task files were merged into this section and then removed from `docs/tasks`:
- `2026-02-27_18.51.16-speed-regression-benchmark-suite-from-pulled-goldens.md`
- `2026-02-27_19.45.53-all-method-eval-signature-dedupe.md`
- `2026-02-27_20.08.17-speed-suite-runtime-parity-single-path.md`
- `2026-02-27_20.43.12-quality-suite-representative-all-method-agent-loop.md`
- `2026-02-27_20.43.54-stage-block-recipe-notes-from-description.md`
- `2026-02-27_20.58.16-all-method-global-mega-run-scheduler.md`
- `priority-8.md`

### 2026-02-27_18.51.16: deterministic speed regression suite

Problems captured:
- Existing `bench run` focused on quality metrics, not baseline-vs-candidate runtime verdicts.
- Timing evidence existed but was fragmented across stage and benchmark artifacts.
- Target matching logic was duplicated and at risk of drift.

Durable decisions:
- Default discovery source is `data/golden/pulled-from-labelstudio`.
- Speed verdicts use repeat samples with median + percent and absolute-second gates.
- Keep speed artifacts self-contained (`suite_resolved`, `samples`, `summary`, `report`, compare outputs) and LLM parsing off.
- Share matching contract with all-method target resolution.

Outcome preserved:
- `speed-discover`, `speed-run`, `speed-compare` are implemented and documented as deterministic baseline/candidate runtime workflow.

### 2026-02-27_19.45.53: all-method canonical eval-signature dedupe

Problems captured:
- Prediction and evaluation were tightly coupled per-config, repeating expensive canonical evaluation work.
- Canonical alignment cache alone did not remove per-config orchestration overhead.

Durable decisions:
- Run predict-only per config, compute deterministic evaluation signatures, evaluate once per signature, and reuse.
- Keep reuse keyed by prediction+gold+evaluator inputs, not config slug.
- Materialize cached report payloads back to per-config artifact paths for downstream compatibility.

Outcome preserved:
- Per-source/multi-source counters now expose `evaluation_signatures_unique`, `evaluation_runs_executed`, and reuse counts.
- Per-config provenance fields now include `eval_signature`, `evaluation_result_source`, and representative config path.

Anti-loop note:
- If dedupe unexpectedly misses, inspect signature payload differences (including `block_features`) before touching scheduler/evaluator internals.

### 2026-02-27_20.08.17: speed-suite runtime parity single-path refactor

Problems captured:
- SpeedSuite executed production entrypoints but still duplicated run-settings-to-kwargs mapping.
- Speed compare lacked persistent settings identity and could produce misleading comparisons.

Durable decisions:
- Keep SpeedSuite orchestrator-only; centralize arg construction in shared run-settings adapters.
- Persist effective run settings and hash in speed artifacts.
- Fail compare by default on settings mismatch; provide explicit escape hatch.

Implementation caveat preserved:
- Adapter output must avoid introducing new default-only kwargs that break direct-call tests/caller assumptions.

Outcome preserved:
- Interactive import/benchmark flows and speed scenarios now share one adapter mapping layer.
- `speed-compare` now reports settings parity and mismatch verdict metadata.

### 2026-02-27_20.43.12: quality-suite representative experiment loop

Problems captured:
- No deterministic quality-iteration harness existed parallel to speed-suite workflows.
- Practical metrics were not available as a single top-level aggregate.
- `RunSettings.from_dict(...)` ignores unknown keys, so typoed experiment patches could silently no-op.

Durable decisions:
- Deterministic representative target selection with algorithm metadata in artifacts.
- Sequential experiment execution with resilient continue-on-failure summary behavior.
- Strict patch-key validation before normalization.
- Compare gates on strict/practical/source-coverage deltas and run-settings parity.

Outcome preserved:
- `quality-discover`, `quality-run`, and `quality-compare` are implemented with actionable PASS/FAIL reasoning.

Anti-loop note:
- For sharded sources, aggregate quality by source-group winner evidence, not naive per-row averaging.

### 2026-02-27_20.43.54: stage-block RECIPE_NOTES sourcing from description

Problem captured:
- Stage-block note labeling only read comment fields, causing `RECIPE_NOTES` prediction zeros when notes existed in recipe description.

Durable decision:
- Merge deterministic description-derived recipe notes (via existing parser utility) with comment-based note sources for stage-block note labeling.

Outcome preserved:
- Regression test now covers description-only note path.
- Deterministic behavior maintained with no LLM path changes.

Anti-loop note:
- If `RECIPE_NOTES` drops to zero again, inspect note sourcing before changing benchmark scoring logic.

### 2026-02-27_20.58.16: global mega-run scheduler for all-method bulk runs

Problems captured:
- Multi-source runs interleaved at source-job level but still used independent per-source config queues and per-source dedupe scope.
- Legacy payload path initially broke with `total_failed_config_runs` reference before assignment.
- Legacy-oriented tests implicitly depended on old dispatch and started running real code after default changed.

Durable decisions:
- Default scheduler scope switched to `global`, with rollback path `legacy`.
- Flatten planned source jobs into one global config queue while retaining source planning/sharding heuristics.
- Keep scoring semantics unchanged; add only scheduler metadata/counters.
- Keep tests explicit about legacy-vs-global dispatch expectations.

Outcome preserved:
- Global queue counters added to combined report payload.
- Speed/quality runners explicitly request global scheduler scope.

Open gap captured:
- No manual interactive wall-clock smoke run was recorded in this pass.

### 2026-02-27_22.48.32: Priority 8 additive segmentation diagnostics

Problems captured:
- Stage-block evaluator was classification-only and lacked segmentation-boundary diagnostics.
- Existing tests did not lock segmentation payload shape.

Durable decisions:
- Extend existing evaluator/CLI surfaces instead of creating separate command trees.
- Keep segmentation outputs additive under `report.segmentation`.
- Keep optional metrics (`segeval`) explicit and dependency-gated.
- Always emit boundary mismatch JSONLs (possibly empty) for stable tooling contracts.

Outcome preserved:
- `evaluate_stage_blocks` now emits boundary metrics + taxonomy and optional `segeval`.
- `bench eval-stage` exposes segmentation flags (`--label-projection`, `--boundary-tolerance-blocks`, `--segmentation-metrics`).
- Optional dependency path is explicit via `segmentation_eval` extra and clear install guidance.

## 16. 2026-02-27_23.25.14 to 2026-02-28_00.11 OGplan audit pack (migrated from `docs/understandings`)

Merged source files:
- `2026-02-27_23.25.14-ogplan-implementation-audit-refresh.md`
- `2026-02-27_23.25.40-ogplan-eval-signature-dedupe-audit.md`
- `2026-02-27_23.26.10-ogplan-audit-live-code-check.md`
- `2026-02-27_23.26.52-ogplan-global-scheduler-audit-snapshot.md`
- `2026-02-27_23.31.29-all-method-run-settings-forwarding-audit.md`
- `2026-02-27_23.34.54-ogplan-priority-1-8-live-audit.md`
- `2026-02-28_00.11.05-ogplan-audit-consolidated-status.md`

### 2026-02-27_23.25.14 OGplan implementation audit refresh

Problem captured:
- OGplan archive checklist state and real runtime delivery were diverging, causing repeated "is this shipped?" loops.

Durable findings:
- Runtime+tests show speed suite, tail-throughput scheduling, eval-signature dedupe, and global scheduler as implemented.
- Priority lanes are mostly implemented in runtime; strict OG archive checkboxes are not a reliable completion signal.
- `speed2-2` remained not implemented as written; `speed2-4` remained partial/unwired.

### 2026-02-27_23.25.40 eval-signature dedupe verification

Problem captured:
- Needed proof that dedupe behavior was not a docs-only claim and worked across both scheduler scopes.

Durable findings:
- Predict-only -> grouped evaluate-only flow is active.
- Reuse counters/provenance are shipped (`evaluation_runs_executed`, `evaluation_results_reused_in_run`, `evaluation_results_reused_cross_run`, `evaluation_result_source`, `evaluation_representative_config_dir`).
- Both legacy and global scheduler paths honor dedupe/reuse behavior.

Anti-loop note:
- If dedupe appears broken, inspect signature payload equality and provenance counters before changing evaluator internals.

### 2026-02-27_23.26.10 + 23.26.52 live-check/global-scheduler snapshot

Problems captured:
- Needed explicit requirement-to-evidence mapping for global scheduler rollout claims.
- Dispatch-level tests could pass while deeper global-loop behavior regressed.

Durable findings:
- `_AllMethodGlobalWorkItem`, global planning, global queue execution, and per-source report rebuild from global rows are implemented.
- Global scope is default; `legacy` remains explicit rollback.
- Explicit open items remained in this audit snapshot:
  - manual real-data all-matched smoke still deferred,
  - deeper direct tests for global-loop internals remained thinner than legacy-path tests.

Anti-loop note:
- Do not declare global scheduler acceptance "fully done" from dispatch tests alone; include manual smoke and direct global-loop behavior checks.

### 2026-02-27_23.31.29 all-method run-settings forwarding parity audit

Problem captured:
- All-method variant dimensions could imply knobs that were not actually forwarded into prediction execution.

Durable findings:
- Adapter setting surface: `58` keys.
- All-method forwarded setting surface: `25` keys.
- Missing in all-method forwarding: `33` keys.
- Missing families included `recipe_score_*`, `multi_recipe_*`, `ingredient_*`, `p6_*`, `web_schema_*`, and output toggles.

Interpretation risk captured:
- All-method rows can advertise non-default dimensions while effective prediction kwargs still use defaults for omitted families.

Anti-loop note:
- Before trusting per-dimension conclusions, verify forwarding parity for that family in `_run_all_method_prediction_once(...)`.

### 2026-02-27_23.34.54 + 2026-02-28_00.11.05 priority and consolidated status merge

Problems captured:
- Priority 1-8 status was being interpreted from stale OG checkboxes.
- Cross-audit conclusions needed one normalized completion model.

Durable findings:
- Core runtime implementation across Priority 2-8 is present; Priority 1 remains partial only against strict optional OG additive lanes.
- Consolidated completion model now documented:
  1. runtime code path exists and is reachable,
  2. focused tests pass,
  3. active plan/task docs track implemented state,
  4. OG checklist state (lowest-trust archival signal).
- Consolidated practical closeout priorities:
  - fix all-method forwarding parity for missing families,
  - add direct global-loop behavior tests,
  - capture deferred manual all-matched smoke evidence.

### 2026-02-28_00.19.46 all-method forwarding adapter parity closure

Source: `docs/understandings/2026-02-28_00.19.46-all-method-forwarding-adapter-parity.md`
Summary: all-method predict-only lane now reuses benchmark adapter payload and applies only all-method-specific overrides.

Problems captured:
- `_run_all_method_prediction_once(...)` maintained a second manual kwargs list for `labelstudio_benchmark(...)`, which drifted from the adapter-backed single benchmark lane.

Durable decisions:
- Build all-method prediction kwargs from `build_benchmark_call_kwargs_from_run_settings(...)`.
- Keep all-method-only overrides explicit and narrow:
  - run-scoped paths (`gold_spans`, `source_file`, `predictions_out`),
  - benchmark controls (`overlap_threshold`, `force_source_match`, `alignment_cache_dir`),
  - worker/resource caps (`workers`, `pdf_split_workers`, `epub_split_workers`).

Outcome preserved:
- Forwarding parity moved from manual duplication to shared-adapter contract.
- Regression lock added:
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py::test_run_all_method_prediction_once_uses_adapter_forwarding_surface`.

### Validation command snapshots preserved by this audit pack

Notable reported results from the merged audit set:
- broad OG feature slice: `94 passed`
- scheduler/dedupe target slice: `4 passed, 118 deselected`
- priority core + matcher parity slice: `41 passed`
- Priority 6 focused slice: `58 passed`
- refreshed priority sweep: `87 passed, 2 warnings` and `58 passed, 2 warnings`

Anti-loop summary:
- Do not treat stale OG checkbox counts as release truth.
- Keep adapter-parity test coverage active; this lane previously drifted and can regress if kwargs are re-manualized.
- Do not close global-scheduler acceptance until manual smoke and deeper global-loop tests are both accounted for.
