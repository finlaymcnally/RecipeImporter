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

## 0. 2026-02-28 `docs/tasks` merge batch (quality suite + runtime adaptation)

### 2026-02-28_00.45.27 quality suite curated CUTDOWN targets

Source task file:
- `docs/tasks/2026-02-28_00.45.27-quality-suite-curated-cutdown-targets.md`

Problem captured:
- Default quality discovery could spread picks across many targets and miss the three high-effort CUTDOWN sets.

Durable decision:
- Prefer curated target IDs first when present (`saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`), then fall back to representative stratified selection.

Evidence preserved:
- `tests/bench/test_quality_suite_discovery.py`
- `tests/bench/test_bench.py`

Anti-loop note:
- Keep this behavior in discovery (`quality_suite.py`), not in runner, so suite manifests remain explicit and replayable.

### 2026-02-28_01.11.10 qualitysuite levers schema v2

Source task file:
- `docs/tasks/2026-02-28_01.11.10-qualitysuite-levers.md`

Problem captured:
- Quality experiments needed a compact, deterministic toggle surface; schema v1 required hand-writing each experiment row and did not carry all-method runtime knobs.

Durable decision:
- Add experiments schema v2 with `levers[]` expansion (`baseline` + each enabled lever + optional `all_on`).
- Keep schema v1 compatible.
- Validate `run_settings_patch` keys against `RunSettings` fields and `all_method_runtime_patch` keys against allowed runtime knobs.
- Fail fast if `all_on` merge encounters conflicting values for the same key.

Evidence preserved:
- `tests/bench/test_quality_suite_runner.py`
- Resolved expansion manifests written to `experiments_resolved.json` per run.

Anti-loop note:
- If run counts or experiment IDs look wrong, inspect `experiments_resolved.json` first before debugging scheduler code.

### 2026-02-28_02.28.08 quality-run process-blocked fallback to legacy source threads

Source task file:
- `docs/tasks/2026-02-28_02.28.08-quality-run-threaded-fallback-when-process-blocked.md`

Problem captured:
- Restricted runtimes without process workers made all-method quality rounds effectively serial under global scheduler settings.

Durable decision:
- Before all-method round execution, probe process-worker availability.
- If unavailable and requested scope is `global`, switch runtime scope to `legacy` and ensure `max_parallel_sources >= 2` (bounded by source count) when needed to avoid serialized source work.
- Keep experiment loop order unchanged (still sequential by experiment id).

Evidence preserved:
- `tests/bench/test_quality_suite_runner.py -k process_workers_unavailable`
- `tests/bench/test_quality_suite_runner.py -k schema_v2_levers_expand_and_pass_runtime_knobs`

Anti-loop note:
- If quality-run looks serial, inspect runtime scope adaptation and effective `max_parallel_sources` before changing scheduler internals.

### 2026-02-28_04.12.26 all-method split throughput optimization (ExecPlan merge)

Merged source file:
- Former `docs/tasks/2026-02-28_04.12.26-all-method-split-throughput-optimization.md` (removed after merge).

Problem captured:
- All-method wall time had shifted from older eval-dominant behavior to split/prediction-dominant behavior on current CUTDOWN-heavy runs, so matcher-focused tuning had lower ROI and risked churn.

Durable decisions retained:
- Prioritize scheduler/split throughput knobs before matcher changes.
- Keep matcher/eval changes as telemetry-only guardrails (`matcher_guardrails` warnings), not scoring-algorithm edits.
- Apply adaptive admission + split-slot resource guards symmetrically in both scheduler paths (`_run_all_method_benchmark_global_queue` and legacy per-source path) to avoid behavior drift.
- Add in-run prediction/split-convert reuse telemetry and treat reuse rollout as evidence-gated (instrument first, then decide).
- Reduce prediction write overhead for all-method predict-only calls by forcing `write_markdown=False` and `write_label_studio_tasks=False`.

Important outcomes preserved:
- Speed comparison evidence from the task:
  - baseline `2026-02-28_02.54.07` vs candidate `2026-02-28_09.57.10`,
  - median total seconds for `benchmark_all_method_multi_source`: `2.1447 -> 0.9532` (`-55.56%`).
- Quality comparison evidence from the task:
  - baseline `2026-02-28_02.54.03` vs candidate `2026-02-28_09.57.37`,
  - `strict_f1_macro +0.03025`, `practical_f1_macro +0.02490`, `source_success_rate` unchanged at `1.0`.

Failed/avoided paths worth keeping:
- Pre-eval over-admission can regress smart-eval-tail contracts; over-admission must remain bounded to eval-active phases.
- Expected split/convert reuse was not observed on the default 13-config single-target EPUB profile (`split_convert_reuse_candidates=0`), so treating missing reuse as a bug was a false lead for that matrix.

Anti-loop notes:
- If speed/quality compare verdict fails while metrics improved, check run-settings hash parity first; this task hit intentional mismatch from `codex_farm_cmd` path differences and used mismatch-allowed compares.
- If throughput changes diverge between `global` and `legacy`, verify admission/slot-cap edits were mirrored in both scheduler code paths before tuning new knobs.

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

## 17. 2026-02-28 migrated understandings batch (bench)

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-28_00.25.56 benchmark option coverage map

Source: `docs/understandings/2026-02-28_00.25.56-benchmark-option-coverage-map.md`
Summary: Mapped Priority 2/3/5/6/7/8 option coverage across labelstudio-benchmark all-method and speed-suite flows.

Details preserved:

- `labelstudio-benchmark` exposes run-setting options for Priority 2/3/5/6/7 (`section_detector_backend`, `multi_recipe_splitter`, `instruction_step_segmentation_*`, `p6_*`, `web_schema_*`) and forwards them through benchmark prediction generation.
- Interactive all-method benchmark uses `_build_all_method_target_variants(...)` + `_run_all_method_benchmark_multi_source(...)`; variant `run_settings` are passed through `build_benchmark_call_kwargs_from_run_settings(...)`, so these same priorities are active there.
- All-method variant expansion is explicit for:
  - `section_detector_backend != legacy` (dimension/tag only; no auto-matrix)
  - `multi_recipe_splitter != legacy` (dimension/tag only; no auto-matrix)
  - webschema inputs (`web_schema_policy` matrix: `prefer_schema|schema_only|heuristic_only`).
- `bench speed-run` loads full `RunSettings` (from `--run-settings-file` or `cookimport.json`) and passes them into stage, canonical benchmark, and all-method speed scenarios, so Priority 2/3/5/6/7 selectors flow into SpeedSuite.
- Priority 8 knobs (`--label-projection`, `--boundary-tolerance-blocks`, `--segmentation-metrics`) are implemented on `bench eval-stage`; they are not exposed in all-method or speed-suite scenario surfaces.
- Historical note: this understanding mentioned `bench run`/`bench sweep` forwarding gaps; those command surfaces are now retired (see `docs/07-bench/07-bench_README.md` Retired Surfaces).

### 2026-02-28_00.43.39 global scheduler deep-tests and smoke closeout

Source: `docs/understandings/2026-02-28_00.43.39-global-scheduler-deep-tests-and-smoke-closeout.md`
Summary: Closed global-scheduler remaining checklist with direct loop tests and manual all-matched smoke evidence.

Details preserved:

Discovery:

- Direct tests existed for scheduler-scope dispatch wiring, but not for global-loop internals in `_run_all_method_benchmark_global_queue(...)` and `_plan_all_method_global_work_items(...)`.

What was added:

1. Direct planning/interleaving guard:
- `test_plan_all_method_global_work_items_tail_pair_interleaves_sharded_sources`
- Asserts tail-pair + sharding yields interleaved global dispatch order and correct per-source config index progression.

2. Direct global-loop interleaving guard:
- `test_run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source`
- Exercises global queue end-to-end (with mocked prediction/eval workers) and asserts light-source work is scheduled before heavy-source tail completion when heavy source is sharded.

3. Direct smart eval-tail admission guard:
- `test_run_all_method_benchmark_global_queue_smart_eval_tail_admission`
- Uses scheduler event files to drive phase transitions and asserts smart scheduler opens eval-tail admission (`max_active_pipelines_observed >= 2` with configured inflight `1`).

4. Non-EPUB eval replay regression guard:
- `test_run_all_method_benchmark_global_queue_non_epub_eval_uses_default_extractor`
- Protects fix where missing `dimensions.epub_extractor` must pass `None` (not string `"None"`) into eval replay.

Bug found during manual smoke:

- `Invalid EPUB extractor: 'None'. Expected one of: unstructured, beautifulsoup.`

Root cause:
- `str(None)` conversion in all-method eval-replay call sites produced literal `"None"`.

Fix:
- Added `_row_dimension_str(...)` in `cookimport/cli.py` and used it in both global and legacy all-method eval-replay paths.

Validation evidence:

Targeted tests:
- `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "plan_all_method_global_work_items_tail_pair_interleaves_sharded_sources or run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source or run_all_method_benchmark_global_queue_smart_eval_tail_admission or run_all_method_benchmark_global_queue_non_epub_eval_uses_default_extractor"`
  - Result: `4 passed, 123 deselected, 2 warnings in 2.71s`
- `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "global_queue or scheduler_scope"`
  - Result: `5 passed, 122 deselected, 2 warnings in 2.54s`

Manual all-matched smoke (real data, global scheduler):
- Targets selected by smallest matched source size from pulled gold exports:
  - `Hix written.docx`
  - `RoastChickenAndOtherStoriesCUTDOWN.epub`
- Run artifact:
  - `data/golden/benchmark-vs-golden/2026-02-28_00.42.13_manual-all-matched-global-smoke/all-method-benchmark/all_method_benchmark_multi_source_report.md`
- Counters:
  - `scheduler_scope=global_config_queue`
  - `matched_target_count=2`
  - `total_config_runs_planned=14`
  - `total_config_runs_completed=14`
  - `total_config_runs_successful=14`
  - `global_queue_failed_configs=0`
  - `evaluation_signatures_unique=14`
  - `evaluation_runs_executed=7`
  - `evaluation_results_reused_cross_run=7`

### 2026-02-28_00.46.58 quality suite curated target selection

Source: `docs/understandings/2026-02-28_00.46.58-quality-suite-curated-target-selection.md`
Summary: Mapped how quality-suite target IDs are derived and where to enforce curated defaults.

Details preserved:

- `bench quality-discover` delegates to `cookimport/bench/quality_suite.py::discover_quality_suite(...)` for all target selection logic.
- Target IDs come from gold export folder names via `match_gold_exports_to_inputs(...)` -> `_target_id_for_gold(...)` (`slugify_name(target_dir_name)`).
- For this repo’s pulled gold exports, curated IDs map directly to folder slugs:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
- Current workspace note: importer-scored discovery (`_list_importable_files`) can return an empty set; quality discovery retries matching against plain non-hidden files under `data/input` so gold-source filename hints still resolve.
- The safest insertion point for curated defaults is quality-suite selection (not runner), so suite manifests carry explicit `selected_target_ids` and downstream `quality-run` behavior remains unchanged.

### 2026-02-28_00.53.55 speed2-4 plan current value assessment

Source: `docs/understandings/2026-02-28_00.53.55-speed2-4-plan-current-value-assessment.md`
Summary: Assessment of `docs/plans/speed2-4.md` against the current DMP-only canonical alignment contract.

Details preserved:

- `docs/plans/speed2-4.md` assumes stdlib `difflib.SequenceMatcher` is the active canonical matcher and proposes replacing it with a MultiLayer-equivalent implementation plus a difflib/multilayer runtime switch.
- Current runtime and contracts now enforce DMP-only matcher selection:
  - `cookimport/bench/sequence_matcher_select.py` supports only `dmp` and rejects all other modes as archived.
  - `cookimport/bench/CONVENTIONS.md` states canonical alignment is locked to `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp`.
  - parity tests explicitly reject legacy modes (`fallback`, `stdlib`, `cydifflib`, `cdifflib`, `multilayer`).
- Practical implication:
  - `speed2-4` is no longer actionable as written; most of its implementation steps conflict with the enforced selector contract.
  - Residual value is mainly historical/design reference (parity-first validation ideas) if the project ever intentionally re-opens non-DMP matcher experiments behind a fresh plan.

### 2026-02-28_00.54.33 speed2-3 current value assessment

Source: `docs/understandings/2026-02-28_00.54.33-speed2-3-current-value-assessment.md`
Summary: Assesses whether speed2-3 still has practical value after dmp lock-in and cache/scheduler changes.

Details preserved:

- `docs/plans/speed2-3.md` delivered its highest-value outcome (native `dmp` matcher integration), but most remaining plan items are now low-value for the current codebase.
- Evidence from repo state + artifacts:
  - Matcher selection is hard-locked to `dmp` now (`cookimport/bench/sequence_matcher_select.py` supports only `dmp`; non-`dmp` modes error).
  - Canonical eval telemetry/CLI wiring already reports and forwards `dmp` matcher metadata (`cookimport/bench/eval_canonical_text.py`, `cookimport/cli.py`).
  - Pre-change heavy run example (`2026-02-27_17.54.41`):
    - `alignment_sequence_matcher_impl: cydifflib`
    - `alignment_sequence_matcher_seconds: 1656.1506924400164`
  - Post-change heavy run example (`2026-02-27_20.47.26`):
    - `alignment_sequence_matcher_impl: dmp`
    - `alignment_sequence_matcher_seconds: 0.0700075310014654`
  - Current repeated runs (`2026-02-27_20.50.38`) are dominated by alignment cache reuse (`alignment_cache_hit: true`, matcher seconds often `0.0`), shifting bottleneck attention to cache/scheduling/reuse policy instead of matcher backend experiments.
- Practical implication:
  - Keeping speed2-3 as historical context is useful.
  - Continuing with deferred milestones (separate backend abstraction + Edlib) is probably not a high-ROI next step unless a new parity/compatibility requirement appears.

### 2026-02-28_01.06.42 quality-run cache scope and speed

Source: `docs/understandings/2026-02-28_01.06.42-quality-run-cache-scope-and-speed.md`
Summary: Why quality-run reruns were missing cross-run all-method cache reuse and how to fix cache scope.

Details preserved:

Discovery:
- `bench quality-run` calls all-method with `root_output_dir=<quality_run>/<timestamp>/experiments/<experiment_id>`.
- Default all-method cache-root resolution treated that as a generic root and used `<quality_run>/<timestamp>/experiments/.cache/canonical_alignment`.
- Result: cache reuse worked inside one timestamped quality run, but reruns with a new timestamp could not reuse canonical alignment/eval-signature cache entries.
- Interactive all-method runs already use a stable shared cache root (`data/golden/benchmark-vs-golden/.cache/canonical_alignment`) because their root layout includes `all-method-benchmark`.

Practical fix:
- For quality-run, pass an explicit persistent cache root when invoking all-method:
  - default: `<quality_out_dir_parent>/.cache/canonical_alignment` (for default out dir, `data/golden/bench/quality/.cache/canonical_alignment`)
  - honor `COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT` override when set.
- This also stabilizes eval-signature result cache scope (`.../.cache/eval_signature_results`) across timestamped quality reruns.

### 2026-02-28_01.20.10 qualitysuite levers schema v2

Source: `docs/understandings/2026-02-28_01.20.10-qualitysuite-levers-schema-v2.md`
Summary: QualitySuite experiments schema v2: levers expansion + runtime knobs.

Details preserved:

- `cookimport bench quality-run` consumes an experiments JSON file via `cookimport/bench/quality_runner.py`.
- Schema v1:
  - Explicit list of experiments only.
  - Each experiment has `id` + `run_settings_patch` (RunSettings fields only).
- Schema v2 (additive):
  - Supports `levers[]`: each lever is a toggleable patch with `enabled: true/false`.
  - By default, the runner expands v2 into a concrete experiments list:
    - `baseline` (if `include_baseline=true`)
    - one experiment per enabled lever (experiment id = lever id)
    - optional `all_on` (if `include_all_on=true`), which merges enabled lever patches and fails fast if two levers set the same key to different values
  - Supports optional `all_method_runtime_patch` per lever/experiment for all-method runtime knobs (parallelism, timeouts, sharding, smart scheduler).
- All-method runtime defaults in quality-run:
  - Quality-run derives runtime defaults from `cookimport.json` keys like `all_method_max_parallel_sources`, and records the resolved values in `experiments_resolved.json`.
  - Schema v2 can override those defaults via top-level `all_method_runtime`, and/or per lever/experiment `all_method_runtime_patch`.

### 2026-02-28_01.34.14 quality suite validation stale target rows

Source: `docs/understandings/2026-02-28_01.34.14-quality-suite-validation-stale-target-rows.md`
Summary: Why quality-run can fail on stale non-selected target rows from quality-suite manifests.

Details preserved:

Discovery:
- `bench quality-discover` can emit additional `targets[]` rows whose `gold_spans_path` is no longer present (observed: `7_thefoodlabcutdown`, `saltfatacidheatcutdown_2`).
- `bench quality-run` validates **all** `targets[]` rows via `validate_quality_suite(...)`, not just `selected_target_ids`.
- Result: run fails before execution with `Gold spans file not found` even when selected curated targets are valid.

Practical workaround:
- Create a derived suite JSON that keeps only rows where both `source_file` and `gold_spans_path` currently exist.
- Keep `selected_target_ids` intersected with the filtered `targets[]` set.
- Run `bench quality-run` against this filtered suite.

## 18. 2026-02-28 migrated understandings batch (hotspot, race, codex-farm, profiles)

### 2026-02-28_01.52.10 thefoodlab all-method hotspot summary

Source: `docs/understandings/2026-02-28_01.52.10-thefoodlab-all-method-hotspot-summary.md`

Run examined:
- `data/golden/benchmark-vs-golden/2026-02-28_01.27.21/all-method-benchmark/thefoodlabcutdown`

Findings preserved:
- Scheduler heavy-slot utilization was high (`96.7%`) with significant split wait.
- Summed canonical eval wall was tiny versus prediction wall (`42.70s` vs `6660.64s`).
- Split convert and split wait dominated runtime (`3765.25s` + `1389.68s`).
- Executed eval rows showed high cache-hit behavior (`95/100`) and small matcher time per executed eval.

Durable implication:
- For this workload, optimize split scheduling/throughput and prediction contention before touching matcher/backend internals.

### 2026-02-28_02.05.26 all-method serial fallback in sandbox

Source: `docs/understandings/2026-02-28_02.05.26-all-method-serial-fallback-in-sandbox.md`

Findings preserved:
- Process-pool preflight can fail in restricted runtimes (`PermissionError` on semaphore creation).
- All-method now preflights and uses single-config execution when workers are unavailable.

Durable implication:
- Slow runs in locked-down environments may be expected throughput degradation, not scoring correctness drift.

### 2026-02-28_02.12.40 quality-run race pruning contract

Source: `docs/understandings/2026-02-28_02.12.40-quality-run-race-pruning-contract.md`

Contract preserved:
- `quality-run --search-strategy race` executes deterministic staged pruning:
  1. probe round on subset
  2. optional mid round
  3. full-suite round on finalists
- `--search-strategy exhaustive` runs full config grid.
- Ranking key for pruning: mean practical F1, mean strict F1, coverage count, median duration.
- Race metadata is emitted to `experiments/<experiment_id>/search_strategy.json`.

Anti-loop note:
- If config counts differ between runs, check search-strategy and race knobs before assuming config-grid generation changed.

### 2026-02-28_02.13.34 manual top-5 all-method replay

Source: `docs/understandings/2026-02-28_02.13.34-manual-top5-all-method-replay.md`

Preserved replay method:
- Take top-ranked configs from source report `variants[]`.
- Rehydrate exact payloads from each config `run_manifest.json`.
- Normalize with `RunSettings.from_dict(...)`.
- Resolve matched targets with `_resolve_all_method_targets(DEFAULT_GOLDEN)` and run one global multi-source sweep.

Observed run evidence:
- Run root: `data/golden/benchmark-vs-golden/2026-02-28_02.03.18_manual-top5-thefoodlab-all-matched/all-method-benchmark/`
- Completed `7/7` sources, `35/35` configs.

### 2026-02-28_02.28.08 quality-run global-to-legacy thread fallback

Source: `docs/understandings/2026-02-28_02.28.08-quality-run-global-to-legacy-thread-fallback.md`

Findings preserved:
- `quality-run` remains sequential at experiment level by design.
- In restricted runtimes, forcing legacy source-thread scheduling preserves multi-source parallelism when process-based config workers are unavailable.
- To get benefit, `max_parallel_sources` must be greater than `1`.

### 2026-02-28_02.28.30 quality leaderboard global config aggregation

Source: `docs/understandings/2026-02-28_02.28.30-quality-leaderboard-global-config-aggregation.md`

Aggregation contract preserved:
- Group per-source variants by stable config identity from dimensions (excluding non-RunSettings noise keys).
- Rank by mean practical F1, mean strict F1, then coverage.
- Compute speed/quality frontier from median duration vs mean practical F1.

Anti-loop note:
- Avoid picking global winners from one source’s per-source rank only; aggregate first across source groups.

### 2026-02-28_02.33.20 quality-run serial root cause

Source: `docs/understandings/2026-02-28_02.33.20-quality-run-serial-root-cause.md`

Run examined:
- `data/golden/bench/quality/runs/2026-02-28_02.19.52`

Findings preserved:
- Direct process-pool probe failed with `PermissionError`.
- Runtime probe `_probe_all_method_process_pool_executor()` reported workers unavailable.
- Parent process had no child worker PIDs during run.
- Probe round was skewed by one heavy source, making the stream appear serial.

Durable implication:
- In this runtime, config-level process parallelism is unavailable until environment permissions change.

### 2026-02-28_02.58.54 codex-farm bench enablement smoke findings

Source: `docs/understandings/2026-02-28_02.58.54-codex-farm-bench-enablement-smoke-findings.md`

Validation preserved:
- `bench speed-run` and `bench quality-run` expose `--include-codex-farm`.
- Codex variants become effective when `--include-codex-farm` is selected and `codex-farm` command resolution is valid.

Observed smoke findings:
- DOCX codex variant failed fast: no `full_text` blocks available.
- EPUB-only smoke reached codex pass directories (`pass1_chunking`, `pass2_schemaorg`, `pass3_final`) but one sandbox run did not finalize `summary.json`/`report.md` despite no active workers.

Anti-loop note:
- Distinguish codex pipeline failure (fast explicit error) from orchestration/finalization hang (run appears stuck after codex post-start).

### 2026-02-28_03.04.14 qualitysuite profile save and cache boundaries

Source: `docs/understandings/2026-02-28_03.04.14-qualitysuite-profile-save-and-cache-boundaries.md`

Boundaries preserved:
- Preferred chooser profile file: `data/.history/preferred_run_settings.json`.
- Quality suite artifacts live under `data/golden/bench/quality/runs/<timestamp>/` with experiment subtrees and leaderboard outputs.
- Quality run telemetry stream path:
  - `data/golden/bench/quality/runs/.history/processing_timeseries/<timestamp>__bench_quality_run__<suite>.jsonl`
- Cross-run reuse is aligned to canonical-eval caches:
  - `.../.cache/canonical_alignment/...`
  - `.../.cache/eval_signature_results/...`

Durable implication:
- Changed/new configs still re-run prediction/import; cache wins are primarily on alignment/eval reuse.

### 2026-02-28_03.08.55 quality leaderboard winner profile source-of-truth

Source: `docs/understandings/2026-02-28_03.08.55-quality-leaderboard-winner-profile-source-of-truth.md`

Problem captured:
- Winner profile settings could drift from displayed winner dimensions when sourced from top-level manifest run-config.

Durable decision:
- Prefer `run_manifest.run_config.prediction_run_config` when present, then normalize through `RunSettings`.
- Persist resolved winner settings to `data/.history/qualitysuite_winner_run_settings.json`.

Outcome preserved:
- Interactive chooser can reliably offer `Run with quality-suite winner (...)` using settings that match the scored variant.

## 2026-02-28 migrated understanding ledger (03:25-03:59 benchmark batch)

### 2026-02-28_03.25.10 quality-suite deterministic sweep coverage

Source: `docs/understandings/2026-02-28_03.25.10-quality-suite-deterministic-sweeps-coverage.md`

Findings preserved:
- Interactive all-method deterministic sweep expansion and quality-suite sweep expansion now share the same variant builder path.
- `bench quality-run` added explicit `--include-deterministic-sweeps` forwarding; default remains off.
- Existing quality artifacts from pre-flag runs show empty run-settings patches; this is expected and not a regression.

Anti-loop rule:
- If deterministic variants are missing in quality output, first verify flag/lever inputs before changing variant-builder logic.

### 2026-02-28_03.25.34 all-method 869 config count explanation

Source: `docs/understandings/2026-02-28_03.25.34-all-method-869-config-breakdown.md`

Findings preserved:
- Large all-method config counts can be legitimate multiplicative expansion, not accidental duplication.
- Verified example: 7 matched targets with 11 sweep payloads and EPUB-per-sweep 13-way expansion produced 869 configs.
- Optional dependency availability (`pysbd`, `quantulum3`, `pint`) directly changes sweep payload composition.

Anti-loop rule:
- Recompute the multiplicative factors (targets * sweeps * per-source variants) before treating high config counts as a scheduler bug.

### 2026-02-28_03.27.17 preferred-profile vs all-method expansion

Source: `docs/understandings/2026-02-28_03.27.17-preferred-profile-vs-all-method-79-count.md`

Findings preserved:
- Preferred profile selection does not disable all-method source-variant expansion.
- Observed `79` configs over `7` matched targets is consistent (`6*13 + 1`).

Anti-loop rule:
- Do not attempt to force one-config-per-target through preferred-profile selection in all-method mode; use single-profile all-matched mode instead.

### 2026-02-28_03.30.47 quality-run sweep helpfulness measurement

Source: `docs/understandings/2026-02-28_03.30.47-quality-run-deterministic-sweeps-and-helpfulness.md`

Findings preserved:
- Sweep attribution should be read from `quality-leaderboard` dimensions and score columns, not from raw config labels alone.
- One-knob causal comparisons are cleaner with lever-isolated experiments and sweeps disabled.

### 2026-02-28_03.32.48 single-profile all-matched interactive benchmark mode

Source: `docs/understandings/2026-02-28_03.32.48-single-profile-all-matched-benchmark-mode.md`

Findings preserved:
- Added middle benchmark mode between single-file run and all-method permutations.
- Mode uses all-matched target resolution but executes exactly one config per matched target.

Anti-loop rule:
- If run count equals matched target count, confirm mode was `single_offline_all_matched` before investigating missing permutations.

### 2026-02-28_03.44.53 single-profile benchmark codex prompt behavior

Source: `docs/understandings/2026-02-28_03.44.53-single-profile-benchmark-codex-menu-behavior.md`

Findings preserved:
- Separate all-method codex permutation prompt is intentionally absent in single-profile mode.
- Codex enablement in single-profile mode is controlled by chooser-selected run settings.

Anti-loop rule:
- Missing all-method codex prompt in single-profile mode is expected UX, not prompt-regression.

### 2026-02-28_03.58.19 speed-suite max-targets and per-label low counts

Source: `docs/understandings/2026-02-28_03.58.19-speed-suite-max-targets-causes-one-eval-per-label.md`

Findings preserved:
- Latest benchmark timestamp can come from speed-suite scenario runs that intentionally sampled one target.
- Example run showed `target_count_selected: 1` and therefore only one eval row for diagnostics.

Anti-loop rule:
- Investigate speed-suite scenario constraints before changing analytics aggregation when diagnostics unexpectedly collapse to one eval.

### 2026-02-28_03.59.44 benchmark split progress and worker config sanitization

Source: `docs/understandings/2026-02-28_03.59.44-benchmark-split-progress-and-worker-config-sanitization.md`

Findings preserved:
- Split conversion progress now follows shared spinner counter contract (`task X/Y`) so ETA/counter behavior stays consistent.
- Split worker payloads should contain RunSettings-only keys to avoid warning noise from report-only fields.

Anti-loop rule:
- If split progress output is noisy, inspect callback message format and worker payload key set before touching scheduler internals.

## 2026-02-28 migrated understanding ledger (04:07-04:16 sandbox worker constraints)

### 2026-02-28_04.07.00 quality-run race runtime under sandbox

Source: `docs/understandings/2026-02-28_04.07.00-quality-run-race-runtime-under-sandbox.md`

Problem captured:
- Quality representative race runs looked "stuck/serial" in sandbox contexts compared to local-host expectations.

Findings preserved:
- Process-worker probe emitted `PermissionError: [Errno 13] Permission denied` and switched to slower fallback behavior.
- Observed large-shard config durations were roughly 129-133s each.
- Representative suite structure (target sharding + race rounds) multiplies that cost into multi-hour wall time.

Durable implication:
- In Codex sandbox planning, treat representative deterministic race defaults as long-running jobs; use reduced suites for tight iteration loops.

### 2026-02-28_04.16.21 all-method processpool semlock sandbox thread fallback

Source: `docs/understandings/2026-02-28_04.16.21-all-method-processpool-semlock-sandbox-thread-fallback.md`

Problem captured:
- `ProcessPoolExecutor` init failed at `_multiprocessing.SemLock` due to `/dev/shm` permission limits.

Durable decisions:
- Keep all-method scheduler scope `global`.
- When process workers are unavailable, run config workers on `ThreadPoolExecutor`.
- Reserve serial single-config fallback for thread executor setup failure only.
- Keep quality-run from forcing global-to-legacy scheduler downgrade just because process probe failed.

Anti-loop note:
- If throughput regresses in sandbox, verify executor fallback path and host `/dev/shm` constraints before changing all-method scheduling semantics.

## 2026-02-28 migrated understanding ledger (09:33 adaptive admission + slot guard telemetry)

### 2026-02-28_09.33.40 all-method adaptive admission and slot guard map

Source: `docs/understandings/2026-02-28_09.33.40-all-method-adaptive-admission-and-slot-guard-map.md`

Problem captured:
- Split throughput tuning had drift risk between legacy and global queue scheduler paths, and slot/worker guard telemetry lacked one coherent map.

Findings preserved:
- Split slot capping now emits explicit scheduler metadata (`split_phase_slots_requested`, `split_phase_slot_mode`, cpu/memory cap fields).
- Adaptive admission now records decision-time telemetry in both scheduler summary (`adaptive_admission_*`) and timeseries (`admission_*` fields).
- Matcher/cache guardrails are now warning-only telemetry (`matcher_guardrails`) to catch eval/cache regressions without changing matcher behavior.

Anti-loop note:
- When comparing all-method performance across runs, check split-slot cap mode and admission reasons first; do not infer scheduler regressions from utilization deltas alone.

## 2026-02-28 migrated understanding ledger (09:33-10:20 quality-run controls and outcomes)

### 2026-02-28_09.33.40 all-method adaptive admission and slot guard map

Source: `docs/understandings/2026-02-28_09.33.40-all-method-adaptive-admission-and-slot-guard-map.md`

Problem captured:
- Throughput tuning changed multiple scheduler control layers at once and risked drift between global-queue and legacy paths.

Findings preserved:
- Scheduling behavior is now explained as three layers that must be read together: split-slot capping, split-worker caps, and adaptive admission guard/target decisions.
- Resource-guard slot caps are resolved once and then applied consistently in both scheduler paths.
- Scheduler timeseries and summary payloads now expose the relevant decision fields (`split_phase_slot_*`, `adaptive_admission_*`, `admission_reason`, CPU high-water).

Anti-loop note:
- Investigate slot-cap mode and admission reason transitions before assuming scheduler regression from raw utilization changes.

### 2026-02-28_10.02.42 all-method prediction reuse telemetry scope

Source: `docs/understandings/2026-02-28_10.02.42-all-method-prediction-reuse-telemetry-scope.md`

Problem captured:
- Reuse telemetry was being interpreted as "broken" when counters stayed zero in common quality profiles.

Findings preserved:
- Reuse hashing excludes `benchmark_sequence_matcher` by design (evaluate-only) and split/convert feasibility uses narrower source+inputs keys.
- In run `2026-02-28_09.57.37` (13 configs), counters were `prediction_runs_executed=13`, `prediction_results_reused_in_run=0`, `split_convert_reuse_candidates=0`, `split_convert_reuse_safe_candidates=0`.
- Compare runs in this pass needed `--allow-settings-mismatch` only because run-settings hashes differed on `codex_farm_cmd` string shape.

Anti-loop note:
- Zero split/convert reuse on the default 13-config EPUB profile is expected matrix shape, not automatically a telemetry defect.

### 2026-02-28_10.06.02 qualitysuite runtime cardinality and walltime

Source: `docs/understandings/2026-02-28_10.06.02-qualitysuite-runtime-cardinality-and-walltime.md`

Problem captured:
- Quality-run wall time was repeatedly misestimated because total config cardinality and execution boundaries were not called out together.

Findings preserved:
- Suite-level runtime scales with experiment count while each experiment can still parallelize internally.
- Evidence snapshot:
  - `2026-02-28_00.54.37`: 3 targets / 39 configs / `2108.39s`.
  - `2026-02-28_03.39.35`: 1 target / 143 configs / `1133.07s`.
  - `2026-02-28_09.57.37`: 1 target / 13 configs / `232.41s` wall time with parallelized summed source runtime `1256.66s`.
- Process-worker restrictions remain a known multiplier in sandboxed hosts.

Anti-loop note:
- If a run "feels slow," first check experiment count and config expansion cardinality before editing scheduler code.

### 2026-02-28_10.12.51 quality sweep signal and top-tier candidates

Source: `docs/understandings/2026-02-28_10.12.51-quality-sweep-quality-signal-and-top-tier-candidates.md`

Problem captured:
- Deterministic sweeps were repeatedly assumed to improve quality without stable cross-run evidence.

Findings preserved:
- Sweep-enabled run `2026-02-28_03.39.35` did not beat non-sweep best; both top rows tied at `0.411011` practical and `0.389916` strict.
- Cross-source run `2026-02-28_00.54.37` remains the stronger top-tier signal and favored unstructured + v1 parser + semantic preprocess + header/footer skipping.
- Single-source run `2026-02-28_09.57.37` showed practical-vs-strict tradeoff families instead of one universally best setting.

Anti-loop note:
- Keep sweeps off by default for baseline until a repeatable cross-source quality lift is demonstrated.

### 2026-02-28_10.13.01 quality-run parallel experiment boundary

Source: `docs/understandings/2026-02-28_10.13.01-quality-run-parallel-experiment-boundary.md`

Problem captured:
- Experiment-level parallelism changes risked breaking summary ordering and continue-on-failure expectations.

Findings preserved:
- `run_quality_suite(...)` now supports bounded parallel experiment execution with `max_parallel_experiments`.
- Output ordering contract is unchanged: summary rows follow resolved experiment order, not completion order.
- Failure contract is unchanged: one failed experiment does not stop unrelated experiments from finishing and summarizing.

Anti-loop note:
- Out-of-order completion is expected; treat summary row order as the canonical reporting order contract.

### 2026-02-28_10.20.58 quality-run auto parallelism and load admission

Source: `docs/understandings/2026-02-28_10.20.58-quality-run-auto-parallelism-and-load-admission.md`

Problem captured:
- Manual experiment worker caps were causing either under-utilization or host overload in mixed run sizes.

Findings preserved:
- Omitted `--max-parallel-experiments` now means auto mode (effective cap `min(total_experiments, cpu_count, 8)`).
- `experiments_resolved.json` records requested/effective parallelism metadata and whether adaptive admission was active.
- Auto admission policy ramps up gradually and clamps down immediately under higher host load.

Anti-loop note:
- If experiment throughput is unstable, inspect resolved auto metadata and host load behavior before forcing fixed caps.

## 2026-02-28 migrated understanding ledger (10:31-11:12 tournament certainty, codex confirmations, and sweep behavior)

### 2026-02-28_10.31.55 quality top-tier tournament baseline and gates

Source: `docs/understandings/2026-02-28_10.31.55-quality-top-tier-tournament-baseline-and-gates.md`

Problem captured:
- Top-tier promotion debates kept mixing high-certainty cross-source evidence with weak single-source probes.

Findings preserved:
- Cross-source run `2026-02-28_00.54.37` is the strongest baseline signal for promotion decisions and favored unstructured + parser v1 + semantic preprocess + skip headers/footers.
- Single-source runs (`2026-02-28_03.39.35`, `2026-02-28_09.57.37`) are valid directional probes but weaker for default promotion.
- Tournament certainty gates are codified in `data/golden/bench/quality/thresholds/2026-02-28_10.31.55_qualitysuite-top-tier-gates.json`.

Anti-loop note:
- Do not promote defaults from a single-source win alone when cross-source evidence disagrees or is missing.

### 2026-02-28_10.35.58 qualitysuite codex-farm confirmation contract

Source: `docs/understandings/2026-02-28_10.35.58-qualitysuite-codex-farm-confirmation-contract.md`

Problem captured:
- `--include-codex-farm` could be enabled without explicit operator confirmation in quality-run workflows.

Findings preserved:
- CLI now requires `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` whenever `--include-codex-farm` is used.
- Runner contract now enforces `codex_farm_confirmed=True` for direct `run_quality_suite(...)` calls requesting Codex variants.

Anti-loop note:
- If Codex variants are rejected in quality-run, inspect confirmation-token wiring before treating it as variant-generation regression.

### 2026-02-28_10.41.47 speedsuite codex-farm confirmation contract

Source: `docs/understandings/2026-02-28_10.41.47-speedsuite-codex-farm-confirmation-contract.md`

Problem captured:
- SpeedSuite had the same missing explicit-confirmation gap for Codex variant enablement.

Findings preserved:
- CLI now requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` with `--include-codex-farm`.
- Direct `run_speed_suite(...)` callers must pass `codex_farm_confirmed=True` when requesting Codex variants.

Anti-loop note:
- Keep confirmation enforcement in both CLI and runner layers; removing one layer reopens bypass paths.

### 2026-02-28_10.44.48 quality-run sweep cardinality and stale-suite validation

Source: `docs/understandings/2026-02-28_10.44.48-quality-run-sweep-cardinality-and-stale-suite-validation.md`

Problem captured:
- Quality runs failed unexpectedly when suite files contained stale non-selected targets, and sweep expansion cost was underestimated.

Findings preserved:
- `bench quality-run` validates all suite `targets[]` rows; missing gold paths in non-selected rows still fail early.
- Fresh curated discovery produced valid selected targets (`saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`) and eliminated stale-row failures.
- Running race mode with deterministic sweeps showed large probe-round cardinality (observed: `286` configs in round 1).
- Interrupted large runs can emit `cannot schedule new futures after interpreter shutdown`; this is interruption fallout, not a benchmark-quality signal.

Anti-loop note:
- When validation fails, fix stale suite rows first; do not debug scheduler/perf paths until suite integrity is clean.

### 2026-02-28_10.56.43 deterministic sweep per-knob status

Source: `docs/understandings/2026-02-28_10.56.43-deterministic-sweep-per-knob-status.md`

Problem captured:
- Teams were close to treating deterministic sweeps as default winners without clear per-knob uplift evidence.

Findings preserved:
- Completed sweep evidence in run `2026-02-28_03.39.35` showed tie-heavy top rows across baseline and multiple sweep tags.
- Present sweeps in that run: section detector, multi-recipe splitter, missing-unit policy, segmentation policy, yield mode, temperature-unit backend.
- Missing sweeps in that run: `p6_time_backend` and `p6_temperature_backend` alternates (dependency-gated), plus `instruction_step_segmenter=pysbd_v1`.

Anti-loop note:
- Keep deterministic defaults as baseline until multi-source/multi-seed results show consistent uplift for specific knobs.

### 2026-02-28_11.12.24 qualitysuite seed variation and tournament cache/dedupe

Source: `docs/understandings/2026-02-28_11.12.24-qualitysuite-seed-variation-and-tournament-cache-dedupe.md`

Problem captured:
- Multi-seed tournaments were sometimes paying full fold cost for duplicate suites, reducing evidence value per unit runtime.

Findings preserved:
- Discovery now keeps curated IDs first and fills remaining slots with seed-driven representative selection, allowing seeds to produce different suites.
- Tournament fold runs now share canonical/eval cache root (`COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`) to reuse expensive evaluation work across folds.
- Tournament computes suite signatures, skips duplicate-suite folds, and removes skipped duplicates from certainty-gate denominators.

Anti-loop note:
- If extra seeds appear to add no signal, inspect fold suite signatures and duplicate-fold skips before widening search space.

## 2026-02-28 docs/tasks consolidation batch (quality controls + speed2-3 closeout)

### 2026-02-28_10.09.34 quality-run parallel experiments

Source task file:
- `docs/tasks/2026-02-28_10.09.34-quality-run-parallel-experiments.md`

Problem captured:
- `bench quality-run` ran experiments one-at-a-time, stretching wall time even when host capacity was idle.

Durable decisions/outcomes:
- Added bounded experiment fanout to `run_quality_suite(...)` with deterministic summary ordering by resolved experiment index.
- Kept continue-on-failure semantics unchanged under parallel fanout.
- Made omitted `--max-parallel-experiments` mean CPU/load-aware auto mode.
- Raised auto ceiling to `16` (env override: `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`).
- Added subprocess experiment fanout fallback when process-pool probing fails (`COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE`).

Evidence preserved:
- `pytest tests/bench/test_quality_suite_runner.py -q`
- `pytest tests/bench/test_bench.py -k quality_run -q`

Anti-loop note:
- If throughput looks low, inspect `experiments_resolved.json` metadata (`*_requested`, `*_effective`, executor mode, auto ceiling) before retuning scheduler internals.

### 2026-02-28_10.35.58 qualitysuite codex-farm confirmation gate

Source task file:
- `docs/tasks/2026-02-28_10.35.58-qualitysuite-codex-farm-confirmation-gate.md`

Problem captured:
- `--include-codex-farm` could be enabled without explicit user-confirmation intent.

Durable decisions/outcomes:
- Added required CLI token gate:
  - `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Enforced the same confirmation at runner boundary (`codex_farm_confirmed=True`) for direct Python callers.

Evidence preserved:
- `pytest -o addopts='' tests/bench/test_bench.py tests/bench/test_quality_suite_runner.py -q` (`34 passed` recorded in task)

Anti-loop note:
- Do not remove one of the two gate layers (CLI + runner). Single-layer checks reopen bypass paths.

### 2026-02-28_10.41.47 speedsuite codex-farm confirmation gate

Source task file:
- `docs/tasks/2026-02-28_10.41.47-speedsuite-codex-farm-confirmation-gate.md`

Problem captured:
- SpeedSuite had the same missing explicit confirmation gap for Codex Farm permutations.

Durable decisions/outcomes:
- Added required CLI token gate:
  - `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- Enforced runner-side confirmation for direct `run_speed_suite(...)` callers.

Evidence preserved:
- `pytest -o addopts='' tests/bench/test_bench.py tests/bench/test_speed_suite_runner.py -q` (`29 passed` recorded in task)

Anti-loop note:
- If Codex variants are unexpectedly rejected, debug confirmation-token plumbing first, not permutation builders.

### 2026-02-27 to 2026-02-28 speed2-3 matcher closeout + variance evidence

Source task file:
- `docs/tasks/speed2-3.md`

Problem captured:
- Canonical-text mismatch-heavy cases were alignment-bound and historically slow under stdlib matcher behavior.

Durable outcomes from this historical plan:
- High-value milestone landed: runtime matcher path is now dmp-based and benchmark telemetry reflects requested/effective matcher mode.
- Current runtime contract is dmp-only; non-dmp runtime selector values are intentionally rejected.
- Standalone matcher benchmark script keeps `stdlib` as reference baseline for parity/speed comparisons.

Critical fix preserved:
- `scripts/bench_sequence_matcher_impl.py` previously crashed when `stdlib` mode flowed through dmp-only runtime selector.
- Script now bypasses selector for explicit stdlib benchmarking and has regression coverage.

Evidence preserved:
- Narrow compare PASS:
  - baseline `data/golden/bench/speed/runs/2026-02-28_13.26.16`
  - candidate `data/golden/bench/speed/runs/2026-02-28_13.26.22`
  - compare `data/golden/bench/speed/comparisons/2026-02-28_13.26.28/comparison.json`
- Full-suite follow-up at `warmups=0,repeats=1` showed FAIL variance:
  - compare `data/golden/bench/speed/comparisons/2026-02-28_14.39.37/comparison.json`

Anti-loop note:
- Treat one-pass full-suite compare FAILs at low warmup/repeat as noisy signal; re-run with stronger sampling before tuning matcher/runtime code.

### 2026-02-28_14.30.18 qualitysuite crash-safe checkpoint + resume

Source task file:
- `docs/tasks/2026-02-28_14.30.18-qualitysuite-crash-safe-checkpoint-resume.md`

Problem captured:
- Interrupted quality runs lost progress because final summary/report artifacts were only written on clean completion.

Durable decisions/outcomes:
- Added per-experiment persisted result snapshots and run-level checkpoint artifacts.
- Added explicit resume command surface:
  - `bench quality-run --resume-run-dir <existing_run_dir>`
- Added tournament fold resume plumbing:
  - `scripts/quality_top_tier_tournament.py --resume-tournament-dir ...`
- Added compatibility guards so resume fails fast when experiment layout/settings are incompatible.

Checkpoint artifact contract retained:
- `experiments/<experiment_id>/quality_experiment_result.json`
- `checkpoint.json`
- `summary.partial.json`
- `report.partial.md`

Evidence preserved:
- `pytest tests/bench/test_quality_suite_runner.py -q`
- `pytest tests/bench/test_bench.py -k quality_run -q`

Anti-loop note:
- If resume unexpectedly reruns completed experiments, validate experiment-id compatibility + checkpoint snapshot contents before changing scheduler behavior.

## 2026-02-28 to 2026-03-01 migrated understanding ledger (quality/speed reliability batch)

Chronological merge from `docs/understandings`; source files removed after merge.

### 2026-02-28_11.14.44 qualitysuite seed variation and tournament cache/dedupe

Source: `docs/understandings/2026-02-28_11.14.44-qualitysuite-seed-variation-and-tournament-cache-dedupe.md`

Problem captured:
- Multi-seed folds were often duplicates because curated-only selection path ignored seed-driven representative variation.

Durable decisions:
- Discovery keeps curated IDs first, then uses seeded representative fill for remaining target slots.
- Tournament fold runs share alignment/eval cache root.
- Fold suite signatures are deduped; duplicate folds are skipped and excluded from gate denominators.

### 2026-02-28_11.18.07 quality tournament gate impossibility pruning

Source: `docs/understandings/2026-02-28_11.18.07-quality-tournament-gate-impossibility-pruning.md`

Problem captured:
- Candidates continued running even when mathematically unable to pass certainty gates.

Durable decisions:
- After each fold, compute optimistic upper bounds using remaining unique folds.
- Prune candidates that cannot pass gates under best-case assumptions.
- Persist prune state in fold outputs and tournament summary/report.

### 2026-02-28_11.33.22 quality-run auto cap ceiling and ramp

Source: `docs/understandings/2026-02-28_11.33.22-quality-run-auto-cap-ceiling-and-ramp.md`

Problem captured:
- Auto mode stalled at low worker cap (`8`) despite available host headroom.

Durable decisions:
- Effective cap now uses `min(total_experiments, cpu_count, auto_ceiling)`.
- Default `auto_ceiling=16`; env override `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`.
- Admission ramps faster and resolved metadata is persisted in `experiments_resolved.json`.

### 2026-02-28_11.45.55 qualitysuite low CPU due to /dev/shm restriction

Source: `docs/understandings/2026-02-28_11.45.55-qualitysuite-low-cpu-due-shm-permission-and-thread-fallback.md`

Findings preserved:
- Host-level `/dev/shm` denial forced process-worker fallbacks and reduced effective CPU scaling.
- Thread-backed fallback preserved correctness but capped throughput.

Anti-loop note:
- When this host constraint is active, tune knobs only after confirming process-worker availability state.

### 2026-02-28_12.00.19 quality-run subprocess experiment fallback

Source: `docs/understandings/2026-02-28_12.00.19-quality-run-subprocess-experiment-fallback-for-shm-restricted-hosts.md`

Problem captured:
- Thread fallback under process denial left cross-experiment fanout GIL-limited.

Durable decisions:
- Added experiment executor mode (`auto|thread|subprocess`) with env control.
- Auto mode chooses subprocess fanout when process-pool probing fails.
- Executor mode/reason metadata is persisted in `experiments_resolved.json`.

### 2026-02-28_13.24.03 qualitysuite crash-state and sweep-signal check

Source: `docs/understandings/2026-02-28_13.24.03-qualitysuite-crash-and-sweep-signal-check.md`

Findings preserved:
- Several newer runs/tournaments were partial (missing final summary/report), so they were not valid sweep-default evidence.
- Completed sweep run evidence showed ties across base and sweep families.

Durable decision:
- Keep deterministic sweep families optional until completed multi-fold/multi-source runs show stable unique uplift.

### 2026-02-28_13.27.30 speed2-3 closure: dmp selector + stdlib benchmark script

Source: `docs/understandings/2026-02-28_13.27.30-speed2-3-closure-dmp-selector-stdlib-script.md`

Problem captured:
- Runtime selector is intentionally dmp-only; standalone script incorrectly routed stdlib through selector and crashed.

Durable decisions:
- Keep runtime contract dmp-only.
- In script-only benchmarking, run stdlib directly (`difflib.SequenceMatcher`) and use selector for non-stdlib modes.
- Preserve regression test coverage for both paths.

### 2026-02-28_14.36.24 qualitysuite checkpoint/resume surface map

Source: `docs/understandings/2026-02-28_14.36.24-qualitysuite-checkpoint-resume-surface-map.md`

Problem captured:
- Run-level summary/report were written only at end, so crash recovery could not safely resume from canonical state.

Durable decisions:
- Persist per-experiment snapshots as authoritative completed-work state.
- Regenerate partial run-level artifacts incrementally.
- Support explicit resume wiring (`--resume-run-dir`) and tournament forwarding.

### 2026-02-28_14.40.12 full SpeedSuite serial-mode and variance snapshot

Source: `docs/understandings/2026-02-28_14.40.12-full-speedsuite-serial-mode-and-variance.md`

Findings preserved:
- Serial-mode warnings aligned with lower host-wide CPU.
- Back-to-back compares with `warmups=0,repeats=1` produced regression FAIL on unchanged settings hash.

Anti-loop note:
- Treat one-sample compares as noisy; increase warmups/repeats before attributing regressions.

### 2026-02-28_14.46.40 deterministic sweep decision snapshot

Source: `docs/understandings/2026-02-28_14.46.40-deterministic-sweep-must-include-decision-snapshot.md`

Findings preserved:
- Only one completed sweep-enabled run existed with final artifacts.
- Top score tuple was tied across base and all requested sweep families.

Durable decision:
- No sweep family is default-worthy yet; keep sweep knobs exploration-only until stronger evidence exists.

### 2026-02-28_14.51.46 SpeedSuite serial task loop and no-resume contract (historical)

Source: `docs/understandings/2026-02-28_14.51.46-speedsuite-serial-task-loop-and-no-resume-contract.md`

Historical snapshot preserved:
- SpeedSuite previously executed scenario/target/phase tasks serially and had no resume contract.

Superseded by later entry:
- `2026-02-28_15.31.28` establishes parallel + resume contracts.

### 2026-02-28_15.01.40 qualitysuite hot CPU + IO-guard profile

Source: `docs/understandings/2026-02-28_15.01.40-qualitysuite-hot-cpu-io-guard-profile.md`

Problem captured:
- Raising global workers alone can collapse effective per-config workers under split/source caps and increase disk thrash.

Durable decisions:
- Keep base workers higher while constraining split/source fanout.
- Use profile-guided run-settings files and pair with bounded experiment parallelism for stable high throughput.

### 2026-02-28_15.19.25 processpool restored session probe

Source: `docs/understandings/2026-02-28_15.19.25-processpool-restored-session-probe.md`

Findings preserved:
- Process pool and SemLock probing succeeded in this session; fallback paths were not active bottlenecks.

Anti-loop note:
- Re-check session capability before assuming restricted-host fallback behavior is still active.

### 2026-02-28_15.31.28 SpeedSuite parallel + checkpoint/resume contract

Source: `docs/understandings/2026-02-28_15.31.28-speedsuite-parallel-checkpoint-resume-contract.md`

Durable decisions:
- Added bounded task parallelism (`--max-parallel-tasks`, auto when omitted).
- Added resume surface (`--resume-run-dir`) with strict compatibility checks.
- Added incremental crash-safe artifacts (`checkpoint.json`, partial summary/report/samples).
- Added per-sample phase snapshots (`speed_sample_result.json`) used by resume to skip completed tasks.

### 2026-02-28_15.48.23 tournament sweeps workload and prediction-reuse scope

Source: `docs/understandings/2026-02-28_15.48.23-qualitysuite-tournament-sweeps-workload-and-prediction-reuse-scope.md`

Problem captured:
- Sweep-enabled variant explosion dominated runtime and prediction reuse scope was too narrow.

Durable findings/decisions:
- Sweeps-on variant count can be ~11x sweeps-off before pruning.
- Eval-signature cache helped evaluation, but prediction reuse remained root-scoped at that time.
- Full-tree copy reuse was correct but I/O-heavy.

### 2026-02-28_16.27.10 prediction reuse cross-root same-config-dir guard

Source: `docs/understandings/2026-02-28_16.27.10-prediction-reuse-cross-root-same-config-dir-guard.md`

Problem captured:
- Reuse was skipped when config dir names matched, even across different roots with valid reusable artifacts.

Durable decisions:
- Allow same `config_dir` names when source artifact path indicates a different root.
- Cache entries retain absolute source artifact paths.
- Shared reuse cache roots now support reuse across rounds/experiments/folds.

### 2026-02-28_20.20.04 fast shortlist fold-gate impossibility

Source: `docs/understandings/2026-02-28_20.20.04-fast-shortlist-fold-gate-impossibility-and-sweeps-decision-thresholds.md`

Problem captured:
- Gate minima exceeded feasible unique folds after duplicate-fold skipping, making promotion impossible.

Durable decisions:
- Added sweeps-decision thresholds with feasible fold gates for shortlist-shaped runs.
- Lowered `min_completed_folds` and adjusted uplift ratio threshold accordingly.

### 2026-02-28_20.35.43 qualitysuite live ETA queue-aware

Source: `docs/understandings/2026-02-28_20.35.43-qualitysuite-live-eta-queue-aware.md`

Problem captured:
- ETA only modeled active experiments, underestimating wall-time with large queued work.

Durable decisions:
- Add queued-wave ETA contribution.
- Use completed-duration fallback when active samples are sparse.
- Include queued count in live status output.

### 2026-02-28_20.50.43 qualitysuite prior-result reuse boundary

Source: `docs/understandings/2026-02-28_20.50.43-qualitysuite-when-prior-tournament-results-are-reusable.md`

Durable decision:
- Treat completed tournament results as reusable final evidence only when full input tuple matches (experiments, thresholds, fold plan/duplicate behavior, scoring semantics).

Anti-loop note:
- Prediction/alignment cache reuse does not imply fold/result memoization.

### 2026-02-28_21.01.58 race finalists no-prune overhead

Source: `docs/understandings/2026-02-28_21.01.58-qualitysuite-race-finalists-no-prune-overhead.md`

Problem captured:
- If `race_finalists` exceeds variant count, race does extra rounds without pruning and can be slower than exhaustive.

Durable decision:
- Tune `race_finalists` below variant count on low-cardinality no-sweeps profiles, or force exhaustive.

### 2026-02-28_21.14.34 live work_units can rise during normal scheduling

Source: `docs/understandings/2026-02-28_21.14.34-qualitysuite-live-work-units-can-rise-during-normal-scheduling.md`

Findings preserved:
- `work_units` is a weighted scheduler estimate, not a strict remaining-config counter.
- Queue admissions, round transitions, and retries can increase displayed units during healthy execution.

### 2026-02-28_21.29.32 tournament quick overrides for parser-answer fast path

Source: `docs/understandings/2026-02-28_21.29.32-quality-tournament-quick-overrides-for-fast-parsing-answer.md`

Durable decisions:
- Added explicit run-shape overrides (`--candidate-experiment-id`, `--max-candidates`, `--max-seeds`, `--force-no-deterministic-sweeps`, `--quality-search-strategy`).
- Added `--quick-parsing` preset for fast parser-setting answers (focused candidates, sweeps off, exhaustive, seed cap).

### 2026-02-28_21.51.19 quality lightweight series entrypoint/profile contract

Source: `docs/understandings/2026-02-28_21.51.19-quality-lightweight-series-entrypoint-and-profile-contract.md`

Durable decision:
- Lightweight series should be a first-class bench command using a versioned JSON profile under `data/golden/bench/quality/lightweight_profiles/`, not an ad-hoc standalone script flow.

### 2026-02-28_22.11.43 Oracle parsing-accuracy scope gap map

Source: `docs/understandings/2026-02-28_22.11.43-oracle-parsing-accuracy-plan-scope-gap-map.md`

Findings preserved:
- Quick-parsing lane already exists but seed-selection and observability gaps remained.
- Race no-prune waste remained unresolved for low-cardinality profiles.
- Prediction reuse coverage was broader than snapshot assumptions; remaining gap was copy I/O cost.

### 2026-03-01_00.20.00 lightweight series fold reuse and summary contract

Source: `docs/understandings/2026-03-01_00.20.00-quality-lightweight-series-fold-reuse-and-summary-contract.md`

Durable decisions:
- Keep lightweight series orchestration-only by reusing `quality-run` fold outputs.
- Base winner and interaction decisions on fold summary metrics/deltas (`practical_f1_macro`, `strict_f1_macro`, `source_success_rate`).
- Enforce two-layer resume compatibility (series-level hashes + fold-level reuse artifacts).

## 2026-02-26 to 2026-03-01 migrated understanding ledger (perf profile + phase-shape consolidation)

Chronological merge from `docs/understandings`; source files were removed after this merge.

### 2026-02-26_18.19.49 book processing vs benchmark performance profile

Source: `docs/understandings/2026-02-26_18.19.49-book-processing-vs-benchmark-performance-report.md`

Problem captured:
- Speedup conversations were mixing stage conversion cost, benchmark prediction cost, and canonical evaluator cost without one code-mapped baseline.

Findings preserved:
- Stage-block runs in the sampled window were conversion/prediction-bound (evaluation share near zero).
- Canonical-text runs were overwhelmingly alignment-bound (evaluation share near total wall time).
- Source-level all-method wall time often reflected canonical eval tails with low split-slot utilization.
- Stage split-merge and benchmark split-merge use different implementations (`_merge_split_jobs` vs `_merge_parallel_results`), so bottlenecks/regressions can diverge by path.

Durable decision:
- Keep optimization prioritization explicit:
  - stage/prediction throughput work first for shared ingestion wins,
  - alignment/runtime work first for canonical all-method wall-time reductions.

Anti-loop note:
- For this period, run-local artifacts were the reliable telemetry source; top-level history CSV alone was incomplete.

### 2026-03-01_01.30.00 parsing two-phase runtime closure

Source: `docs/understandings/2026-03-01_01.30.00-qualitysuite-parsing-two-phase-runtime-closure.md`

Problem captured:
- Tournament seed selection, race no-prune behavior, and reuse provenance were still hard to reason about from live runs.

Durable decisions:
- Seed plan resolution now records explicit source/plan metadata in `tournament_resolved.json` and honors `--seed`, `--seed-list`, and threshold fallback deterministically.
- Race mode auto-collapses to one exhaustive pass when pruning is impossible (`variants_effective <= race_finalists`) with explicit reason metadata.
- Fold checkpoint progress fields are promoted into `tournament_checkpoint.json` during active folds for live observability.
- Prediction reuse provenance is now classified as in-run vs cross-run based on source artifact root checks.
- Reuse artifact materialization is hardlink-first with copy fallback when linking is unavailable.

Anti-loop note:
- If race or reuse behavior appears inconsistent, inspect resolved metadata (`tournament_resolved.json`, `tournament_checkpoint.json`, per-config reuse source fields) before changing scheduler code.

### 2026-03-01_10.20.00 auto-handoff and phase recommendation heuristic

Source: `docs/understandings/2026-03-01_10.20.00-qualitysuite-auto-handoff-and-phase-recommendation.md`

Problem captured:
- Promotion from Phase A to Phase B needed a deterministic default that still allowed explicit operator override.

Durable decisions:
- Candidate precedence is now explicit:
  - explicit `--candidate-experiment-id` override first,
  - auto-candidate selection from prior summary second,
  - threshold/default candidate path last.
- Auto recommendation heuristic now selects:
  - one candidate when top candidate is winner or tied-top across all evaluated unique folds and at least two unique folds exist,
  - two candidates when top-two mean practical deltas are within `0.003`,
  - otherwise fallback to top-ranked candidate with warning metadata.
- Recommendation output is written into tournament `summary.json` and `report.md` as `phase_a_promotion_recommendation`.
- Explicit seeds plus cap behavior is now deterministic (dedupe explicit seed sequence, then cap with `--max-seeds`).

Anti-loop note:
- If auto mode picks one candidate where two were expected (or vice versa), inspect fold uniqueness and top-two delta first.

### 2026-03-01_10.20.19 plan-stack redundancy and suite shape

Source: `docs/understandings/2026-03-01_10.20.19-qualitysuite-plan-stack-redundancy-and-suite-shape.md`

Problem captured:
- Repeated plan churn risked treating foundational and additive QualitySuite work as duplicates.

Findings preserved:
- `2026-02-28_15.49.40` remained foundational infrastructure (faster profiles + wider prediction reuse scope).
- `2026-02-28_21.43.13` remained additive product surface (`bench quality-lightweight-series`), not a replacement.
- `2026-02-28_22.08.25` provided the two-phase parsing runtime baseline (no-prune fallback, seed handling, fold progress, reuse telemetry split).
- `2026-03-01_09.48.35` mainly extended that baseline (auto handoff, recommendation heuristic, phase defaults/precedence cleanup).

Durable decision:
- Keep suite shape explicitly three-track (lightweight directional, tournament promotion confidence, full quality-run validation) instead of collapsing into one command path.

Anti-loop note:
- Supersession is mostly profile-level; avoid deleting feature-level surfaces just because a newer thresholds snapshot exists.

### 2026-03-01_10.26.08 defaults cleanup and product-suite guide

Source: `docs/understandings/2026-03-01_10.26.08-qualitysuite-defaults-cleanup-and-product-suite-guide.md`

Problem captured:
- Default presets and historical snapshots were drifting into ambiguous "current vs legacy" operator guidance.

Durable decisions:
- Tournament default files now point to parser Phase A official candidates/thresholds (`2026-03-01_01.00.00` set).
- Removed byte-identical duplicate preset:
  - `2026-02-28_14.58.21_qualitysuite-top-tier-tournament-hot-io-guard.json`
  - duplicate of `2026-02-28_16.24.30_qualitysuite-top-tier-tournament-full-candidates.json`
- Active-vs-legacy preset status is documented in `data/golden/bench/quality/README.md`.
- Unified operator decision guide is centralized in `docs/07-bench/qualitysuite-product-suite.md`.

Anti-loop note:
- Before introducing a new preset, verify whether an equivalent run-settings payload already exists to avoid duplicate snapshot drift.

## 2026-03-01 docs/tasks merge ledger (SpeedSuite + QualitySuite)

### 2026-02-28_14.55.16 SpeedSuite task-level parallelism and resume

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_14.55.16-speedsuite-parallel-and-resume.md`

Problem captured:
- SpeedSuite task loop was serial and interruption recovery required full reruns.

Durable decisions:
- Add bounded task-level fanout via `--max-parallel-tasks`.
- Add run resume via `--resume-run-dir` with strict compatibility checks.
- Persist crash-safe incremental artifacts and per-sample snapshots for skip-on-resume behavior.
- Keep orchestration thread-based for bounded dispatch and deterministic checkpoint flushing.

Evidence preserved:
- `pytest tests/bench/test_speed_suite_runner.py`
- `pytest tests/bench/test_bench.py -k "speed_run or speed_compare or speed_discover"`

Anti-loop note:
- If resume skips or reruns unexpectedly, inspect run-config compatibility payload first before changing task planners.

### 2026-02-28_15.49.40 fast profile + shared prediction reuse scope

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_15.49.40-qualitysuite-fast-profile-and-shared-prediction-reuse.md`

Problem captured:
- Deterministic sweeps multiplied runtime; prediction reuse scope was too narrow (single run-root).

Durable decisions:
- Ship lower-workload tournament profile defaults (no-sweeps and narrower race breadth).
- Keep prediction reuse keys stable but widen cache root scope and retain absolute source artifact paths.
- Allow reuse across rounds/experiments/folds with shared cache roots.

Evidence preserved:
- `pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "prediction_once_reuses_cached_prediction_artifacts"` (`2 passed`)
- `pytest tests/bench/test_quality_suite_runner.py -k "run_quality_suite or quality_prediction_reuse_cache_root_honors_env_override or quality_cache_root_honors_env_override"` (`13 passed`)

Anti-loop note:
- Reuse misses with matching config names can still be valid when source paths differ; inspect artifact-root provenance before changing reuse keys.

### 2026-02-28_20.35.43 queue-aware QualitySuite ETA

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_20.35.43-qualitysuite-live-eta-queue-aware.md`

Problem captured:
- ETA modeled only active experiments and consistently underreported full wall-time when queues were deep.

Durable decisions:
- Include queued-wave contribution in remaining-time estimator.
- Use completed-experiment duration fallback when active ETA samples are sparse.
- Surface queued counts in live status output.

Evidence preserved:
- `pytest tests/bench/test_quality_eta.py -q`
- `pytest tests/bench/test_quality_suite_runner.py -k "run_quality_suite" -q`

Anti-loop note:
- ETA remains a heuristic; queue-aware estimation is intentionally conservative compared to active-only lowballing.

### 2026-02-28_21.43.13 lightweight main-effects series productization

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_21.43.13-qualitysuite-lightweight-main-effects-series.md`

Problem captured:
- Full tournaments were too slow for quick parser/config direction-finding.

Durable decisions:
- Implement `bench quality-lightweight-series` as a first-class bench command (not ad-hoc script-only workflow).
- Keep orchestration deterministic and non-LLM; reuse existing quality-run scorer semantics.
- Externalize category/round/scoring/risk contracts into a versioned lightweight profile JSON.
- Use strict combined-merge conflict detection (`illegal_overlap`) to prevent silent override of contradictory patch keys.

Evidence preserved:
- `pytest tests/bench/test_quality_lightweight_series.py` (`6 passed`)
- `pytest tests/bench/test_bench.py -k "bench_quality_lightweight_series_wires_runner or bench_quality_lightweight_series_rejects_missing_resume_series_dir or bench_quality_discover_writes_suite or bench_quality_run_wires_runner or bench_quality_run_rejects_missing_resume_run_dir or bench_quality_leaderboard_saves_qualitysuite_winner_profile"` (`6 passed`)
- `pytest tests/bench/test_quality_suite_runner.py -k "run_quality_suite"` (`11 passed`)

Anti-loop note:
- Lightweight series is a directional fast-answer lane; do not treat it as a replacement for promotion and full validation lanes.

### 2026-02-28_22.08.25 two-phase parser workflow and runtime waste cuts

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_22.08.25-qualitysuite-parsing-accuracy-two-phase-and-runtime-waste-cuts.md`

Problem captured:
- Parser-setting workflow lacked explicit two-phase operating surface and still spent runtime on no-prune race and opaque in-flight fold progress.

Durable decisions:
- Productize Phase A/Phase B parser workflows in versioned artifacts and runbook guidance.
- Auto-downgrade race to exhaustive when no pruning is possible; persist requested/effective strategy metadata and reason.
- Add explicit tournament seed surfaces (`--seed`, `--seed-list`) with deterministic resolution metadata.
- Add polled fold subprogress and top-level `tournament_checkpoint.json` updates.
- Add hardlink-first prediction artifact materialization with copy fallback and in-run vs cross-run reuse classification.

Evidence preserved:
- `pytest tests/bench/test_quality_top_tier_tournament.py` (`4 passed`)
- `pytest tests/bench/test_quality_suite_runner.py -k "race or run_quality_suite"` (`13 passed`)
- `pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "prediction_reuse_summary or reuses_cached_prediction_artifacts or hardlink_unavailable"` (`4 passed`)

Anti-loop note:
- If race and exhaustive results diverge unexpectedly, inspect no-prune fallback metadata before editing tournament round logic.

### 2026-03-01_09.48.35 Oracle full-ideas gap closure

Source task was merged into this log and removed from `docs/tasks`:
- `2026-03-01_09.48.35-qualitysuite-oracle-full-ideas-gap-closure.md`

Problem captured:
- Remaining Oracle recommendations needed first-class workflow surfaces: auto handoff, B+ sweeps decision presets, recommendation heuristics, and precedence cleanup.

Durable decisions:
- Add auto handoff flags (`--auto-candidates-from-summary`, `--auto-candidates-from-latest-in`) while keeping explicit candidate IDs authoritative.
- Encode one shared promotion heuristic for both auto-selection and report recommendation metadata.
- Add thresholds-driven default max-parallel behavior with CLI override precedence.
- Relax explicit-seed precedence: dedupe explicit seeds first, then apply optional `--max-seeds` cap.
- Add optional B+ sweeps-decision profile and keep it explicitly separate from default promotion loop.

Evidence preserved:
- `pytest tests/bench/test_quality_top_tier_tournament.py` (`10 passed`)
- `pytest tests/bench/test_quality_suite_runner.py -k "race"` (`2 passed`)
- `pytest tests/bench/test_bench.py -k "quality_run or quality_lightweight_series"` (`6 passed`)
- Dry-run evidence confirmed auto-handoff metadata and explicit-seed-plus-cap behavior.

Anti-loop note:
- Candidate-source precedence (`explicit > auto summary > threshold/default`) is intentional; verify resolved metadata before changing selection heuristics.

### 2026-03-01_11.47.33 quality-run WSL safety guard for nested parallelism

Source task file:
- `docs/tasks/2026-03-01_11.47.33-qualitysuite-wsl-safety-guard.md`

Problem captured:
- Parallel QualitySuite runs on WSL could combine outer experiment fanout with inner all-method/process fanout in a way that destabilized the distro and disconnected VSCode remote sessions.

Durable decisions:
- Keep non-WSL behavior unchanged.
- For WSL with `max_parallel_experiments_effective > 1`, prefer subprocess experiment isolation in auto executor mode.
- Add a WSL nested-parallelism safety guard that caps per-experiment workers and all-method runtime knobs (`max_parallel_sources`, `max_inflight_pipelines`, `max_concurrent_split_phases`, `max_eval_tail_pipelines`, `wing_backlog_target`, `smart_scheduler`) to conservative values.
- Persist safety-guard telemetry in `experiments_resolved.json` so operators can verify whether guardrails were applied.
- Allow explicit opt-out only via `COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD=1`.

Evidence preserved:
- `pytest tests/bench/test_quality_suite_runner.py -q`
- `pytest tests/bench/test_bench.py -k "quality_run" -q`

Anti-loop note:
- If a WSL run still destabilizes the host, check `experiments_resolved.json` first for `wsl_safety_guard_applied` and the effective worker cap before changing scheduler internals again.

### 2026-03-01_12.23.08 WSL single-slot guard follow-up

Source task file:
- `docs/tasks/2026-03-01_12.23.08-qualitysuite-wsl-single-slot-guard.md`

Problem captured:
- WSL instability persisted for runs with `max_parallel_experiments_effective=1` because the first guard version only activated when outer experiment fanout was greater than one.

Durable decisions:
- On WSL, force subprocess experiment isolation even for single-slot runs in auto executor mode.
- Apply WSL safety guard defaults regardless of experiment slot count (unless `COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD=1`).
- Add a hard cap (`4`) to WSL guarded worker counts so single-slot runs cannot inherit high per-config worker values from base settings.

Evidence preserved:
- `pytest tests/bench/test_quality_suite_runner.py -k "wsl" -q`
- `pytest tests/bench/test_bench.py -k "quality_run" -q`

Anti-loop note:
- If WSL still disconnects on guarded single-slot runs, inspect `experiments_resolved.json` first for `experiment_executor_reason=wsl_single_experiment_isolation` and guard telemetry before blaming Oracle/Chromium overlap.

### 2026-03-01_23.16.19 WSL guard re-enabled after OOM crash evidence

Source task file:
- `docs/tasks/2026-03-01_23.16.19-qualitysuite-wsl-guard-restore-after-oom.md`

Problem captured:
- WSL crashes were still occurring with guard telemetry showing `retired_unhobble`, and kernel OOM logs showed runaway `cookimport` fanout (dozens of concurrent processes) exhausting RAM+swap.

Durable decisions:
- Re-enable WSL safety guard rewrites in `quality_runner` by default (unless explicitly disabled).
- Cap WSL run settings workers (`workers`, `pdf_split_workers`, `epub_split_workers`) to `2`.
- Cap WSL all-method runtime knobs (`max_parallel_sources`, `max_inflight_pipelines`, `max_concurrent_split_phases`, `max_eval_tail_pipelines`, `wing_backlog_target`) and force `smart_scheduler=false`.
- Preserve guard opt-out via `COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD=1`.

Evidence preserved:
- `pytest tests/bench/test_quality_suite_runner.py -k "wsl_safety_guard" -q`

Anti-loop note:
- When WSL disconnects reappear, inspect `experiments_resolved.json` first; if `wsl_safety_guard_applied=false` with `disabled_by_env`, the guard was intentionally bypassed.
